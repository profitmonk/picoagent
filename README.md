# Picoagent

Lightweight, secure AI agent (~750 lines of Python) that routes messages from Telegram and WhatsApp to cloud AI (Claude, ChatGPT) or local models (Ollama, vLLM), with shell execution and web browsing capabilities. Persistent conversation memory via SQLite. Runs in a Docker container on Mac or Raspberry Pi.

## Architecture

```
You (Telegram)
     |
Telegram servers
     |  HTTPS POST (instant)
ngrok tunnel (public URL)
     |
Docker container (picoagent)
     |
Agent (ReAct Loop) --> SecurityGate
  /    |     \    \
Providers Shell Web  Memory (SQLite)
 /   |   \
Claude OpenAI Ollama
```

- **Webhook mode** — Telegram pushes messages instantly via ngrok tunnel (polling fallback available)
- **Persistent memory** — SQLite-backed conversation history survives container restarts
- **ReAct loop** with per-user conversation memory (20-message sliding window)
- **Provider chain** with automatic fallback (Claude -> OpenAI -> local)
- **Docker-only execution** — refuses to start outside a container
- **6-layer security**: user allowlist, rate limiting, command blocklist, secret exfiltration prevention, container isolation, execution limits

## Quick Start

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [ngrok](https://ngrok.com/) (free account) — `brew install ngrok`
- A Telegram bot token from [@BotFather](https://t.me/botfather)
- An Anthropic API key from [console.anthropic.com](https://console.anthropic.com)

### Setup

```bash
# 1. Clone
git clone https://github.com/profitmonk/picoagent.git
cd picoagent

# 2. Create .env with your secrets
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-your-key-here
TELEGRAM_BOT_TOKEN=your-bot-token-here
TELEGRAM_WEBHOOK_URL=
EOF

# 3. Create config.yaml
cp config.example.yaml config.yaml
# Edit config.yaml — set your Telegram user ID in the allowlist

# 4. Start everything
./start.sh
```

### Daily usage

```bash
./start.sh           # Start ngrok + Docker (one command)
./stop.sh            # Stop everything, keep conversation history
./stop.sh --wipe     # Stop everything + delete all conversation history
```

### Manage the container

```bash
docker compose ps          # Check status
docker compose logs -f     # Watch live logs
docker compose down        # Stop container only
```

## Configuration

Secrets go in `.env` (never committed to git). Config references them with `${VAR}`:

**.env**
```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_WEBHOOK_URL=https://your-tunnel.ngrok-free.dev
```

**config.yaml**
```yaml
providers:
  - type: claude
    api_key: "${ANTHROPIC_API_KEY}"
    model: "claude-sonnet-4-20250514"
  # - type: openai
  #   api_key: "${OPENAI_API_KEY}"
  #   model: "gpt-4o"
  # - type: ollama
  #   base_url: "http://host.docker.internal:11434/v1"
  #   model: "llama3.1"

telegram:
  token: "${TELEGRAM_BOT_TOKEN}"
  webhook_url: "${TELEGRAM_WEBHOOK_URL}"
  webhook_port: 8443

security:
  allowlist:
    telegram:
      - 123456789  # your Telegram user ID (get from @userinfobot)
  rate_limit: 20
  rate_window: 60
```

## Tools

The agent can use two tools via the ReAct loop:

| Tool | Description | Limits |
|------|-------------|--------|
| `shell` | Execute shell commands inside the container | 30s timeout, 4000 char output, dangerous commands blocked |
| `web_fetch` | Fetch web page content | 15s timeout, 4000 char output |

## Security

| Layer | Protection |
|-------|-----------|
| Docker-only execution | Refuses to start outside a container |
| User allowlist | Per-channel allowlists (Telegram IDs, WhatsApp numbers) |
| Rate limiting | 20 messages/user/minute (configurable) |
| Command blocklist | Blocks `rm -rf`, `sudo`, `mkfs`, `dd`, `curl\|sh`, etc. |
| Secret exfiltration prevention | Blocks `env`, `printenv`, `cat .env`, `$API_KEY`, `/proc/*/environ` |
| Container isolation | Non-root user, all capabilities dropped, 50 PID limit, 512MB memory |
| Execution limits | 30s shell timeout, 4000 char truncation, max 5 tool rounds |

## Persistent Memory

Conversation history is stored in SQLite inside a Docker named volume:

```
Docker volume: picoagent_picoagent-data
  └── /data/picoagent.db
       └── messages (conv_key, role, content, tool_calls, timestamp)
```

- Survives container restarts and rebuilds
- 20-message sliding window per user
- Isolated inside Docker — not accessible from the host filesystem
- Wipe with: `./stop.sh --wipe`

## Tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -v    # 48 tests covering all modules
```

## Project Structure

```
picoagent/
├── picoagent/
│   ├── __init__.py       - Version string
│   ├── main.py           - Config loading, .env support, Docker enforcement, startup
│   ├── agent.py          - ReAct loop, tool dispatch, uses Memory for persistence
│   ├── memory.py         - SQLite-backed conversation store (save/load/trim)
│   ├── providers.py      - Claude + OpenAI-compatible provider chain with fallback
│   ├── channels.py       - Telegram (webhook + polling fallback) + WhatsApp (webhook)
│   ├── tools.py          - Shell executor + web page fetcher
│   └── security.py       - Allowlist, blocklist, rate limiting, secret protection
├── tests/
│   └── test_picoagent.py - 48 tests
├── CLAUDE.md             - Project context and conventions
├── config.example.yaml   - Annotated config template
├── Dockerfile            - python:3.11-slim, non-root user, /data volume
├── docker-compose.yml    - Security constraints, named volume for persistence
├── requirements.txt      - pyyaml, aiohttp, python-telegram-bot, anthropic, openai
├── start.sh              - Launch ngrok + Docker in one command
└── stop.sh               - Tear down everything (--wipe to delete history)
```

## License

MIT
