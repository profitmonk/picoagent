"""Channels: Telegram (webhook) and WhatsApp (webhook)."""

import json
import logging

import aiohttp
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters

from .agent import Agent

log = logging.getLogger(__name__)

MAX_TG_LEN = 4096


class TelegramChannel:
    """Telegram bot using webhook mode (or polling as fallback)."""

    def __init__(self, token: str, agent: Agent, webhook_url: str | None = None,
                 port: int = 8443):
        self.token = token
        self.agent = agent
        self.webhook_url = webhook_url
        self.port = port
        self.app = ApplicationBuilder().token(token).build()
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        self._runner: web.AppRunner | None = None

    async def _on_message(self, update: Update, context):
        msg = update.message
        if not msg or not msg.text:
            return
        user_id = str(msg.from_user.id)
        log.info("[IN]  user=%s: %s", user_id, msg.text)

        reply = await self.agent.handle_message(user_id, "telegram", msg.text)
        log.info("[OUT] user=%s: %s", user_id, reply)

        # Split long replies
        for i in range(0, len(reply), MAX_TG_LEN):
            await msg.reply_text(reply[i:i + MAX_TG_LEN])

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Handle incoming Telegram webhook POST."""
        data = await request.json()
        update = Update.de_json(data, self.app.bot)
        await self.app.process_update(update)
        return web.Response(status=200)

    async def start(self):
        await self.app.initialize()
        await self.app.start()

        if self.webhook_url:
            # Webhook mode
            webhook_path = f"/telegram/{self.token.split(':')[0]}"
            full_url = f"{self.webhook_url}{webhook_path}"

            # Set webhook with Telegram
            await self.app.bot.set_webhook(url=full_url)
            log.info("Telegram webhook set: %s", full_url)

            # Start aiohttp server to receive webhooks
            srv = web.Application()
            srv.router.add_post(webhook_path, self._handle_webhook)
            self._runner = web.AppRunner(srv)
            await self._runner.setup()
            site = web.TCPSite(self._runner, "0.0.0.0", self.port)
            await site.start()
            log.info("Telegram webhook listener on port %d", self.port)
        else:
            # Fallback to polling
            log.info("No webhook URL configured, using polling...")
            await self.app.updater.start_polling()

    async def stop(self):
        if self.webhook_url:
            await self.app.bot.delete_webhook()
            if self._runner:
                await self._runner.cleanup()
        else:
            await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()


class WhatsAppChannel:
    """WhatsApp via Meta Cloud API webhooks."""

    def __init__(self, verify_token: str, access_token: str, phone_id: str,
                 agent: Agent, port: int = 8080):
        self.verify_token = verify_token
        self.access_token = access_token
        self.phone_id = phone_id
        self.agent = agent
        self.port = port
        self._runner: web.AppRunner | None = None

    async def start(self):
        app = web.Application()
        app.router.add_get("/webhook", self._verify)
        app.router.add_post("/webhook", self._on_message)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        log.info("Starting WhatsApp webhook on port %d...", self.port)
        await site.start()

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()

    async def _verify(self, request: web.Request) -> web.Response:
        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge", "")
        if mode == "subscribe" and token == self.verify_token:
            return web.Response(text=challenge)
        return web.Response(status=403, text="Forbidden")

    async def _on_message(self, request: web.Request) -> web.Response:
        body = await request.json()
        # Return 200 immediately per Meta requirements
        try:
            entry = body.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                if msg.get("type") != "text":
                    continue
                phone = msg["from"]
                text = msg["text"]["body"]
                log.info("WA message from %s: %s", phone, text[:80])
                reply = await self.agent.handle_message(phone, "whatsapp", text)
                await self._send(phone, reply)
        except Exception:
            log.exception("WhatsApp message processing error")
        return web.Response(status=200)

    async def _send(self, to: str, text: str):
        url = f"https://graph.facebook.com/v18.0/{self.phone_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        log.error("WA send error %d: %s", resp.status, await resp.text())
        except Exception:
            log.exception("WhatsApp send error")
