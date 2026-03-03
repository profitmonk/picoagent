"""Web chat channel: password-protected browser UI sharing the agent."""

import hashlib
import json
import logging
import secrets
import time
import uuid
from pathlib import Path

from aiohttp import web

from .agent import Agent

log = logging.getLogger(__name__)

SESSION_TTL = 86400  # 24 hours


class WebChatChannel:
    """Browser-based chat UI mounted on a shared aiohttp app."""

    def __init__(self, password: str, agent: Agent):
        self._password_hash = hashlib.sha256(password.encode()).hexdigest()
        self.agent = agent
        # Stable user_id derived from password — same conversation across sessions
        self._user_id = hashlib.sha256(f"webchat:{password}".encode()).hexdigest()[:16]
        self._sessions: dict[str, float] = {}  # token -> expiry timestamp
        self._html = (Path(__file__).parent / "webchat.html").read_text()

    def register_routes(self, app: web.Application):
        app.router.add_get("/", self._serve_ui)
        app.router.add_post("/api/login", self._login)
        app.router.add_post("/api/chat", self._chat)
        app.router.add_get("/api/history", self._history)
        app.router.add_post("/api/logout", self._logout)

    def _check_session(self, request: web.Request) -> bool:
        token = request.cookies.get("session")
        if not token:
            return False
        expiry = self._sessions.get(token)
        if not expiry or time.time() > expiry:
            self._sessions.pop(token, None)
            return False
        return True

    async def _serve_ui(self, request: web.Request) -> web.Response:
        return web.Response(text=self._html, content_type="text/html")

    async def _login(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        password = body.get("password", "")
        given_hash = hashlib.sha256(password.encode()).hexdigest()

        if not secrets.compare_digest(given_hash, self._password_hash):
            log.warning("Webchat login failed from %s", request.remote)
            return web.json_response({"error": "Wrong password"}, status=401)

        token = str(uuid.uuid4())
        self._sessions[token] = time.time() + SESSION_TTL

        # Clean expired sessions
        now = time.time()
        self._sessions = {k: v for k, v in self._sessions.items() if v > now}

        resp = web.json_response({"ok": True})
        # Note: Secure flag omitted because our server runs HTTP behind ngrok
        # (ngrok terminates TLS). HttpOnly + SameSite=Strict provide protection.
        resp.set_cookie("session", token, httponly=True, samesite="Strict",
                        max_age=SESSION_TTL)
        log.info("Webchat login successful from %s", request.remote)
        return resp

    async def _chat(self, request: web.Request) -> web.Response:
        if not self._check_session(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        text = body.get("message", "").strip()
        if not text:
            return web.json_response({"error": "Empty message"}, status=400)

        log.info("[IN]  webchat user=%s: %s", self._user_id, text[:80])
        reply = await self.agent.handle_message(self._user_id, "webchat", text)
        log.info("[OUT] webchat user=%s: %s", self._user_id, reply[:80])

        return web.json_response({"reply": reply})

    async def _history(self, request: web.Request) -> web.Response:
        if not self._check_session(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        conv_key = f"webchat:{self._user_id}"
        messages = self.agent.memory.load(conv_key)
        # Return only user/assistant messages for display
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] in ("user", "assistant") and m.get("content")
        ]
        return web.json_response({"messages": history})

    async def _logout(self, request: web.Request) -> web.Response:
        token = request.cookies.get("session")
        if token:
            self._sessions.pop(token, None)
        resp = web.json_response({"ok": True})
        resp.del_cookie("session")
        return resp
