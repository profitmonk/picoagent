# Picoagent

Lightweight, secure AI agent (~580 lines of Python) that routes messages from Telegram and WhatsApp to cloud AI (Claude, ChatGPT) or local models (Ollama, vLLM), with shell execution and web browsing capabilities. Runs in a Docker container on Mac or Raspberry Pi.

## Architecture

```
Telegram/WhatsApp  -->  Channel Abstraction  -->  SecurityGate
                                                       |
                                                  Agent (ReAct Loop)
                                                  /       |        \
                                           Providers   ShellTool   WebTool
                                           /    |    \
                                       Claude  OpenAI  Ollama
```

- **ReAct loop** with per-user conversation memory (sliding window)
- **Provider chain** with automatic fallback (Claude -> OpenAI -> local)
- **5-layer security**: user allowlist, rate limiting, command blocklist, container isolation, execution limits

## Quick Start

```bash
# 1. Clone
git clone https://github.com/profitmonk/picoagent.git
cd picoagent

# 2. Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your API keys and bot tokens

# 3. Run with Docker
docker compose up --build
```

## Configuration

Edit `config.yaml` (see `config.example.yaml` for all options):

```yaml
providers:
  - type: claude
    api_key: "sk-ant-..."
    model: "claude-sonnet-4-20250514"
  - type: openai
    api_key: "sk-..."
    model: "gpt-4o"
  # - type: ollama
  #   base_url: "http://localhost:11434/v1"
  #   model: "llama3.1"

telegram:
  token: "BOT_TOKEN_FROM_BOTFATHER"

security:
  allowlist:
    telegram:
      - 123456789  # your Telegram user ID
  rate_limit: 20
  rate_window: 60
```

## Tools

The agent can use two tools via the ReAct loop:

| Tool | Description | Limits |
|------|-------------|--------|
| `shell` | Execute shell commands | 30s timeout, 4000 char output, blocked dangerous commands |
| `web_fetch` | Fetch web page content | 15s timeout, 4000 char output |

## Security

| Layer | Protection |
|-------|-----------|
| User allowlist | Per-channel allowlists (Telegram IDs, WhatsApp numbers) |
| Rate limiting | 20 messages/user/minute (configurable) |
| Command blocklist | Blocks `rm -rf`, `sudo`, `mkfs`, `dd`, `curl\|sh`, etc. |
| Container isolation | Non-root user, all capabilities dropped, 50 PID limit, 512MB memory |
| Execution limits | 30s shell timeout, 4000 char truncation, max 5 tool rounds |

## Running Without Docker

```bash
pip install -r requirements.txt
export PICOAGENT_CONFIG=config.yaml
python -m picoagent.main
```

## Tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Project Structure

```
picoagent/
├── picoagent/
│   ├── __init__.py       - Version string
│   ├── main.py           - Config loading, wiring, startup
│   ├── agent.py          - ReAct loop, conversation memory, tool dispatch
│   ├── providers.py      - Claude + OpenAI-compatible provider chain
│   ├── channels.py       - Telegram (polling) + WhatsApp (webhook)
│   ├── tools.py          - Shell executor + web page fetcher
│   └── security.py       - Allowlist, blocklist, rate limiting
├── tests/
│   └── test_picoagent.py - 45 tests covering all modules
├── config.example.yaml   - Annotated config template
├── Dockerfile            - python:3.11-slim, non-root user
├── docker-compose.yml    - Security constraints
└── requirements.txt      - pyyaml, aiohttp, python-telegram-bot, anthropic, openai
```

## License

MIT
