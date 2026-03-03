"""Main entry point: config loading, wiring, startup."""

import asyncio
import logging
import os
import re
import signal
import sys

import yaml

from aiohttp import web

from .agent import Agent
from .channels import TelegramChannel, WhatsAppChannel
from .memory import Memory
from .providers import ProviderChain
from .router import SmartRouter
from .security import SecurityGate
from .webchat import WebChatChannel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _load_dotenv():
    """Load .env file into os.environ if present."""
    env_path = os.path.join(os.path.dirname(os.environ.get("PICOAGENT_CONFIG", "config.yaml")), ".env")
    if not os.path.exists(env_path):
        env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _resolve_env_vars(text: str) -> str:
    """Replace ${VAR} with environment variable values."""
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), text)


def load_config() -> dict:
    _load_dotenv()
    path = os.environ.get("PICOAGENT_CONFIG", "config.yaml")
    with open(path) as f:
        raw = f.read()
    return yaml.safe_load(_resolve_env_vars(raw))


async def run():
    cfg = load_config()
    security = SecurityGate.from_config(cfg)

    # Use smart routing if local providers are configured alongside cloud
    has_local = any(p["type"] in ("ollama", "vllm", "local") for p in cfg.get("providers", []))
    if has_local:
        router = SmartRouter.from_config(cfg)
        log.info("Smart routing enabled (cloud + local)")
    else:
        router = ProviderChain.from_config(cfg)
        log.info("Cloud-only mode (no local providers)")

    db_path = cfg.get("memory", {}).get("db_path", "/data/picoagent.db")
    memory = Memory(db_path)
    agent = Agent(router, security, memory)

    channels = []
    stop_fns = []
    shared_app = None
    shared_runner = None

    # Web chat — creates shared aiohttp app if configured
    wc = cfg.get("webchat", {})
    if wc.get("password"):
        shared_app = web.Application()
        webchat = WebChatChannel(password=wc["password"], agent=agent)
        webchat.register_routes(shared_app)
        log.info("Web chat enabled")

    # Telegram
    tg = cfg.get("telegram", {})
    if tg.get("token"):
        ch = TelegramChannel(
            token=tg["token"],
            agent=agent,
            webhook_url=tg.get("webhook_url"),
            port=tg.get("webhook_port", 8443),
            shared_app=shared_app,
        )
        # Register webhook route on shared app before it's frozen by AppRunner
        if shared_app and tg.get("webhook_url"):
            ch.register_webhook(shared_app)
        channels.append(ch.start())
        stop_fns.append(ch.stop)

    # WhatsApp
    wa = cfg.get("whatsapp", {})
    if wa.get("access_token"):
        ch = WhatsAppChannel(
            verify_token=wa.get("verify_token", ""),
            access_token=wa["access_token"],
            phone_id=wa.get("phone_number_id", ""),
            agent=agent,
            port=wa.get("port", 8080),
        )
        channels.append(ch.start())
        stop_fns.append(ch.stop)

    if not channels and not shared_app:
        log.error("No channels configured. Set telegram.token, whatsapp.access_token, or webchat.password in config.")
        sys.exit(1)

    # Start shared aiohttp app (webchat + telegram webhook on same port)
    if shared_app:
        port = tg.get("webhook_port", 8443)
        shared_runner = web.AppRunner(shared_app)
        await shared_runner.setup()
        site = web.TCPSite(shared_runner, "0.0.0.0", port)
        await site.start()
        log.info("Shared HTTP server on port %d (webchat%s)", port,
                 " + telegram webhook" if tg.get("token") and tg.get("webhook_url") else "")

    log.info("Picoagent starting with %d channel(s)...", len(channels) + (1 if shared_app else 0))
    if channels:
        await asyncio.gather(*channels)

    # Keep running until interrupted
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    log.info("Shutting down...")
    for fn in stop_fns:
        await fn()
    if shared_runner:
        await shared_runner.cleanup()


def _require_container():
    """Refuse to start outside a container."""
    in_docker = os.path.exists("/.dockerenv")
    in_container = os.path.exists("/run/.containerenv")
    if not (in_docker or in_container):
        log.error("Picoagent must run inside a Docker container. Use: docker compose up")
        sys.exit(1)


def main():
    _require_container()
    asyncio.run(run())


if __name__ == "__main__":
    main()
