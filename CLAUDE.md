# Picoagent

Lightweight secure AI agent (~750 lines Python). Routes Telegram/WhatsApp messages to cloud AI (Claude, ChatGPT) or local models (Ollama, vLLM) with shell and web tools. Persistent SQLite memory. Runs in Docker on Mac or Raspberry Pi.

## Architecture

- **channels.py** – Telegram (webhook with polling fallback) + WhatsApp (webhook)
- **security.py** – 6-layer security: user allowlist, rate limiting, command blocklist, secret exfiltration prevention, container isolation, execution limits
- **agent.py** – ReAct loop with tool dispatch, uses Memory for persistence (max 5 tool rounds)
- **memory.py** – SQLite-backed conversation store (save/load/trim, 20-msg window per user)
- **providers.py** – Provider chain with fallback (Claude → OpenAI → Ollama); Claude message format translation
- **tools.py** – Shell executor (30s timeout) + web fetcher (output truncated at 4000 chars)
- **main.py** – .env loading, ${VAR} substitution in YAML, Docker-only enforcement, asyncio startup
- **start.sh / stop.sh** – One-command ngrok + Docker launch/teardown (stop.sh --wipe deletes history)

## Conventions

- Python 3.11+, async/await throughout
- Secrets in `.env`, config references them via `${VAR}` syntax
- Config via YAML file (path from `PICOAGENT_CONFIG` env var or `config.yaml`)
- All providers implement `async complete(messages, tools) -> LLMResponse`
- Security gate checked before agent processes any message
- Docker-only: refuses to start outside a container (checks `/.dockerenv`)
- Docker: non-root user, all caps dropped, pids_limit=50, mem_limit=512m
- Persistent data in Docker named volume `picoagent-data` at `/data/picoagent.db`

## Dependencies

pyyaml, aiohttp, python-telegram-bot, anthropic, openai
