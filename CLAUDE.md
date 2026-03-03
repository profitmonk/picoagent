# Picoagent

Lightweight secure AI agent (~1100 lines Python). Smart-routes messages from Telegram/WhatsApp/Web Chat to cloud AI (Claude) or local models (Ollama) based on complexity. Shell and web tools. Persistent SQLite memory. Runs in Docker on Mac or Raspberry Pi.

## Architecture

- **channels.py** – Telegram (webhook with polling fallback, shared_app support) + WhatsApp (webhook)
- **webchat.py** – Password-protected browser chat UI (session cookies, shares agent with Telegram)
- **webchat.html** – Single-page HTML/CSS/JS chat interface (no framework, no build step)
- **security.py** – 6-layer security: user allowlist, rate limiting, command blocklist, secret exfiltration prevention, container isolation, execution limits
- **agent.py** – ReAct loop with tool dispatch, uses Memory for persistence (max 5 tool rounds)
- **memory.py** – SQLite-backed conversation store (save/load/trim, 20-msg window per user)
- **router.py** – Smart routing: classifies message complexity (simple/complex/tool), routes to local or cloud, auto-escalates on failure
- **providers.py** – Provider chain with fallback (Claude → OpenAI → Ollama); Claude message format translation
- **tools.py** – Shell executor (30s timeout) + web fetcher (output truncated at 4000 chars)
- **main.py** – .env loading, ${VAR} substitution in YAML, shared aiohttp app wiring, Docker-only enforcement, asyncio startup
- **start.sh / stop.sh** – One-command ngrok (static domain support) + Docker launch/teardown (stop.sh --wipe deletes history)

## Conventions

- Python 3.11+, async/await throughout
- Secrets in `.env`, config references them via `${VAR}` syntax
- Config via YAML file (path from `PICOAGENT_CONFIG` env var or `config.yaml`)
- All providers and SmartRouter implement `async complete(messages, tools) -> LLMResponse`
- SmartRouter activates when local providers (ollama/vllm/local) are in config alongside cloud
- Web chat and Telegram webhook share port 8443 on a single aiohttp app
- Web chat uses password auth (SHA-256 + constant-time compare), HttpOnly session cookies (24h TTL)
- Security gate checked before agent processes any message
- Docker-only: refuses to start outside a container (checks `/.dockerenv`)
- Docker: non-root user, all caps dropped, pids_limit=50, mem_limit=512m
- Persistent data in Docker named volume `picoagent-data` at `/data/picoagent.db`

## Dependencies

pyyaml, aiohttp, python-telegram-bot, anthropic, openai
