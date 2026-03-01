# Picoagent

Lightweight secure AI agent (~680 lines Python). Routes Telegram/WhatsApp messages to cloud AI (Claude, ChatGPT) or local models (Ollama, vLLM) with shell and web tools. Runs in Docker on Mac or Raspberry Pi.

## Architecture

- **channels.py** – Telegram (webhook with polling fallback) + WhatsApp (webhook)
- **security.py** – 6-layer security: user allowlist, rate limiting, command blocklist, secret exfiltration prevention, container isolation, execution limits
- **agent.py** – ReAct loop with conversation memory (20-msg sliding window, max 5 tool rounds)
- **providers.py** – Provider chain with fallback (Claude → OpenAI → Ollama); Claude message format translation
- **tools.py** – Shell executor (30s timeout) + web fetcher (output truncated at 4000 chars)
- **main.py** – .env loading, ${VAR} substitution in YAML, Docker-only enforcement, asyncio startup
- **start.sh / stop.sh** – One-command ngrok + Docker launch/teardown

## Conventions

- Python 3.11+, async/await throughout
- Secrets in `.env`, config references them via `${VAR}` syntax
- Config via YAML file (path from `PICOAGENT_CONFIG` env var or `config.yaml`)
- All providers implement `async complete(messages, tools) -> LLMResponse`
- Security gate checked before agent processes any message
- Docker-only: refuses to start outside a container (checks `/.dockerenv`)
- Docker: non-root user, all caps dropped, pids_limit=50, mem_limit=512m

## Dependencies

pyyaml, aiohttp, python-telegram-bot, anthropic, openai
