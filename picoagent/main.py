"""Main entry point: config loading, wiring, startup."""

import asyncio
import logging
import os
import signal
import sys

import yaml

from .agent import Agent
from .channels import TelegramChannel, WhatsAppChannel
from .providers import ProviderChain
from .security import SecurityGate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def load_config() -> dict:
    path = os.environ.get("PICOAGENT_CONFIG", "config.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


async def run():
    cfg = load_config()
    security = SecurityGate.from_config(cfg)
    providers = ProviderChain.from_config(cfg)
    agent = Agent(providers, security)

    channels = []
    stop_fns = []

    # Telegram
    tg = cfg.get("telegram", {})
    if tg.get("token"):
        ch = TelegramChannel(tg["token"], agent)
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

    if not channels:
        log.error("No channels configured. Set telegram.token or whatsapp.access_token in config.")
        sys.exit(1)

    log.info("Picoagent starting with %d channel(s)...", len(channels))
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


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
