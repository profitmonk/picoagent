# Picoagent

Lightweight, secure AI agent (~1100 lines of Python) that smart-routes messages from Telegram, WhatsApp, and a **password-protected web chat** to **Claude** (cloud) or **Ollama** (local) based on message complexity. Includes shell execution, web browsing, and persistent conversation memory. Runs in a locked-down Docker container on Mac or Raspberry Pi.

## How It Works

You send a message via Telegram, WhatsApp, or the **web chat UI** (accessible from any browser). The message flows through an ngrok tunnel into a Docker container running Picoagent. A regex-based router classifies the message as simple, complex, or tool-requiring, and sends it to either a local Ollama model (free, fast) or Claude (powerful, paid). The response comes back through the same channel.

```
You (Telegram / WhatsApp / Browser)
     |
     v
ngrok tunnel (HTTPS → localhost:8443, single shared port)
     |
     ├── POST /telegram/{id}  → Telegram webhook
     ├── GET  /               → Web chat UI (login page)
     ├── POST /api/login      → Password auth → session cookie
     ├── POST /api/chat       → Web chat messages
     ├── GET  /api/history    → Load conversation from SQLite
     └── POST /api/logout     → Invalidate session
     |
     v
Docker container (picoagent)
     |
     v
SecurityGate ──→ reject if not in allowlist / rate limited
     |
     v
Agent (ReAct loop, max 5 tool rounds)
     |
     v
SmartRouter (regex classifier, zero-latency)
     |
     ├── "simple" ──→ Ollama (llama3.2, 3B, runs on your Mac)
     |                    └── if fails → auto-escalate to Claude
     |
     ├── "complex" ──→ Claude (claude-sonnet via Anthropic API)
     |
     └── "tool" ──→ Claude (needs function calling)
                        ├── shell tool (run commands in container)
                        └── web_fetch tool (fetch web pages)
     |
     v
Memory (SQLite in Docker volume, 20-msg sliding window per user)
     |
     v
Reply sent back to Telegram / WhatsApp / Browser
```

## Smart Router

The router classifies every message **before** any LLM call using pure regex pattern matching — zero latency, zero cost.

### Classification Logic

| Classification | What Triggers It | Routed To | Example |
|---------------|-----------------|-----------|---------|
| **tool** | Words like `run`, `execute`, `shell`, `directory`, `file`, `fetch`, `install` | Claude | "what directory am I in?" |
| **complex** | `explain`, `analyze`, `write code`, `debug`, code blocks, `step by step`, `architecture`, `api`, `docker`, or messages >50 words | Claude | "write a Python sort function" |
| **simple** | Greetings, thanks, yes/no, jokes, definitions, short messages (<=5 words) with no complex signals | Ollama | "hello", "tell me a joke" |

The classifier uses a **scoring system**: each matching regex adds +1 to either a complex or simple score. Long messages and multi-line messages add to the complex score. If in doubt, it defaults to Claude (the safer choice).

### Auto-Escalation

If Ollama fails (connection refused, timeout) or returns an empty response, the request automatically escalates to Claude. The user never sees an error — routing is invisible.

### Why Not Use an LLM to Classify?

The regex classifier runs in **microseconds**. An LLM-based classifier would add 200-500ms latency to every single message just for routing. The regex approach is good enough for the routing decision and keeps things instant.

## Models

### Cloud: Claude (Anthropic)

| Property | Value |
|----------|-------|
| Model | `claude-sonnet-4-20250514` (configurable) |
| Provider | Anthropic API |
| Strengths | Code generation, complex reasoning, tool use (function calling) |
| Cost | Pay-per-token via Anthropic API |
| Used for | Complex queries, tool calls, code, analysis |

### Local: Ollama (llama3.2)

| Property | Value |
|----------|-------|
| Model | `llama3.2` — Meta's Llama 3.2, 3B parameters |
| Size | 2.0 GB on disk |
| Source | Downloaded from [ollama.com/library](https://ollama.com/library) (pre-quantized GGUF) |
| Runs on | Your Mac/Pi via Ollama, served on `localhost:11434` |
| Strengths | Fast responses (~100ms), free, fully private |
| Cost | Zero — runs entirely on your hardware |
| Used for | Greetings, simple chat, basic Q&A, jokes |

**Alternative local models** (change `model` in config.yaml):

| Model | Size | Notes |
|-------|------|-------|
| `llama3.2` (default) | 2 GB | Fastest, good for simple chat |
| `llama3.1:8b` | 4.7 GB | Better quality, slower |
| `mistral` | 4.1 GB | Good balance of speed and quality |
| `gemma2:9b` | 5.4 GB | Strong reasoning for its size |

## Security (6 Layers)

| Layer | What It Does | Details |
|-------|-------------|---------|
| **Docker-only execution** | Refuses to start outside a container | Checks for `/.dockerenv` at startup |
| **User allowlist** | Only authorized users can use the bot | Per-channel allowlists in config.yaml; web chat uses password auth |
| **Rate limiting** | 20 messages/user/minute | Sliding window, configurable |
| **Command blocklist** | Blocks dangerous shell commands | `rm -rf`, `sudo`, `mkfs`, `dd`, `curl\|sh`, `chmod 777`, `shutdown`, `nc -e` |
| **Secret exfiltration prevention** | Blocks attempts to read API keys | `env`, `printenv`, `cat .env`, `$API_KEY`, `$TOKEN`, `/proc/*/environ` |
| **Container isolation** | Locked-down Docker container | Non-root user, all capabilities dropped, 50 PID limit, 512MB memory, no privilege escalation |

## Web Chat

A password-protected browser UI that lets you chat with the same agent from anywhere in the world. No app install needed — just open the ngrok URL in any browser.

- **Password auth**: Set `WEBCHAT_PASSWORD` in `.env`, log in via browser
- **Session cookies**: `HttpOnly; SameSite=Strict`, 24h TTL, in-memory (restart = re-login)
- **Persistent history**: Conversations stored in SQLite, reload the page and history loads back
- **Port sharing**: Web chat and Telegram webhook share port 8443 on the same aiohttp server (works with ngrok free tier's single tunnel)
- **No new dependencies**: Uses stdlib `hashlib`, `secrets`, `uuid` + existing `aiohttp`

### Setup

1. Add to `.env`:
   ```
   WEBCHAT_PASSWORD=your-secret-password
   ```

2. Add to `config.yaml`:
   ```yaml
   webchat:
     password: "${WEBCHAT_PASSWORD}"
   ```

3. Run `./start.sh` and open the ngrok URL in your browser.

### Static Domain (Optional)

By default, ngrok assigns a random URL on every restart. Claim a free static domain at [dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains), then add to `.env`:

```
NGROK_DOMAIN=your-name.ngrok-free.dev
```

The URL will stay the same across restarts.

## Tools

The agent can use two tools via the ReAct loop (Claude only — local models don't get tools):

| Tool | Description | Limits |
|------|-------------|--------|
| `shell` | Execute shell commands inside the container | 30s timeout, 4000 char output, blocked commands rejected |
| `web_fetch` | Fetch web page content as text | 15s timeout, 4000 char output |

The ReAct loop allows up to **5 tool rounds** per message. The LLM calls a tool, observes the result, and decides whether to call another tool or respond.

## Persistent Memory

Conversation history is stored in SQLite inside a Docker named volume:

```
Docker volume: picoagent_picoagent-data
  └── /data/picoagent.db
       └── messages table (conv_key, role, content, tool_calls, timestamp)
```

- **Survives** container restarts and image rebuilds
- **20-message sliding window** per user (older messages trimmed)
- **Isolated** inside Docker — not directly accessible from the host
- **Wipe** with: `./stop.sh --wipe`

---

## Build Your Own Picoagent (Step by Step)

### Prerequisites

You need these installed on your Mac (or Linux/Pi):

| Tool | Install | What It's For |
|------|---------|---------------|
| **Docker Desktop** | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) | Runs Picoagent in a secure container |
| **ngrok** | `brew install ngrok` | Tunnels Telegram webhooks to your local machine |
| **Ollama** | `brew install ollama` | Runs local LLM (llama3.2) for simple queries |
| **Git** | Pre-installed on Mac | Clone the repository |

You also need these accounts/keys:

| Account | Where to Get It | What It's For |
|---------|----------------|---------------|
| **Telegram bot token** | [@BotFather](https://t.me/botfather) on Telegram | Your bot's identity |
| **Your Telegram user ID** | [@userinfobot](https://t.me/userinfobot) on Telegram | Allowlist (only you can use the bot) |
| **Anthropic API key** | [console.anthropic.com](https://console.anthropic.com) | Claude API access |
| **ngrok account** | [ngrok.com](https://ngrok.com/) (free tier works) | Authenticate ngrok |

### Step 1: Create Your Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g., "My Picoagent")
4. Choose a username (must end in `bot`, e.g., `my_picoagent_bot`)
5. BotFather gives you a **bot token** like `8267213402:AAG...DrA` — save this

### Step 2: Get Your Telegram User ID

1. Open Telegram and search for **@userinfobot**
2. Send any message
3. It replies with your **user ID** (a number like `1015155520`) — save this

### Step 3: Get Your Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up / log in
3. Go to **API Keys** and create a new key
4. Save the key (starts with `sk-ant-...`)

### Step 4: Set Up ngrok

1. Go to [ngrok.com](https://ngrok.com/) and create a free account
2. Get your auth token from the ngrok dashboard
3. Run:
```bash
ngrok config add-authtoken YOUR_NGROK_AUTH_TOKEN
```

### Step 5: Install and Start Ollama

```bash
# Install
brew install ollama

# Start the server
ollama serve &

# Pull the model (2 GB download)
ollama pull llama3.2

# Verify it works
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.2","messages":[{"role":"user","content":"say hi"}]}'
```

### Step 6: Clone and Configure Picoagent

```bash
# Clone the repo
git clone https://github.com/profitmonk/picoagent.git
cd picoagent

# Create .env with your secrets
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-your-key-here
TELEGRAM_BOT_TOKEN=your-bot-token-here
TELEGRAM_WEBHOOK_URL=
WEBCHAT_PASSWORD=your-secret-password
# NGROK_DOMAIN=your-name.ngrok-free.dev
EOF

# Create config.yaml from the template
cp config.example.yaml config.yaml
```

Now edit **config.yaml** — replace `123456789` with your Telegram user ID:

```yaml
providers:
  - type: claude
    api_key: "${ANTHROPIC_API_KEY}"
    model: "claude-sonnet-4-20250514"

  - type: ollama
    base_url: "http://host.docker.internal:11434/v1"
    model: "llama3.2"

telegram:
  token: "${TELEGRAM_BOT_TOKEN}"
  webhook_url: "${TELEGRAM_WEBHOOK_URL}"
  webhook_port: 8443

webchat:
  password: "${WEBCHAT_PASSWORD}"

security:
  allowlist:
    telegram:
      - YOUR_TELEGRAM_USER_ID    # <-- replace this
  rate_limit: 20
  rate_window: 60
```

### Step 7: Start Everything

```bash
./start.sh
```

This single command:
1. Starts an ngrok tunnel to port 8443
2. Updates `.env` with the new ngrok URL
3. Builds the Docker image and starts the container
4. Registers the webhook with Telegram

You should see:

```
=== Picoagent Running ===
Tunnel:    https://xxxx.ngrok-free.dev
Web Chat:  https://xxxx.ngrok-free.dev  (open in browser)
Container: Up 3 seconds (healthy)
```

### Step 8: Test It

Open the ngrok URL in your browser to use the **web chat**, or send messages to your Telegram bot:

| Test | Send This | Expected |
|------|-----------|----------|
| Simple (Ollama) | `hello` | Fast reply from local model |
| Complex (Claude) | `explain how Docker works` | Detailed reply from Claude |
| Tool use (Claude) | `what directory are you in?` | Calls `pwd`, returns `/home/agent/app` |
| Security | `cat .env` | Blocked by security policy |
| Web fetch | `what's on example.com?` | Fetches and summarizes the page |

Watch the logs in another terminal:
```bash
docker compose logs -f
```

You'll see lines like:
```
Router: complexity=simple for: hello...
Router: handled locally
Router: complexity=complex for: explain how Docker works...
Router: complexity=tool for: what directory are you in?...
```

### Daily Usage

```bash
./start.sh           # Start ngrok + Docker (one command)
./stop.sh            # Stop everything, keep conversation history
./stop.sh --wipe     # Stop everything + delete all conversation history
```

### Managing the Container

```bash
docker compose ps          # Check status
docker compose logs -f     # Watch live logs
docker compose down        # Stop container only
docker compose up -d       # Restart container only (no ngrok)
```

---

## Project Structure

```
picoagent/
├── picoagent/                    # Core Python package (~1100 lines)
│   ├── __init__.py        (2)   - Package version string
│   ├── main.py          (156)   - Config loading, .env → ${VAR} substitution, Docker enforcement, startup
│   ├── agent.py          (92)   - ReAct loop: LLM → tool call → observe → repeat (max 5 rounds)
│   ├── router.py        (181)   - Smart routing: regex classifier + SmartRouter (cloud/local dispatch)
│   ├── providers.py     (148)   - ClaudeProvider + OpenAICompatibleProvider + ProviderChain (fallback)
│   ├── channels.py      (165)   - TelegramChannel (webhook + polling, shared_app support) + WhatsAppChannel
│   ├── webchat.py       (119)   - WebChatChannel: password auth, session cookies, chat/history API
│   ├── webchat.html     (200)   - Single-page chat UI: login, message bubbles, history, mobile-responsive
│   ├── memory.py         (80)   - SQLite conversation store: save/load/trim (20-msg window)
│   ├── tools.py          (76)   - Shell executor (30s timeout) + web fetcher (15s timeout)
│   └── security.py       (81)   - SecurityGate: allowlist, rate limit, command blocklist, secret protection
├── tests/
│   └── test_picoagent.py (693)  - 79 tests: security, tools, providers, memory, agent, router, config, webchat
├── config.example.yaml          - Annotated config template (copy to config.yaml)
├── Dockerfile                   - python:3.11-slim, non-root user, curl/wget/jq/git, /data volume
├── docker-compose.yml           - Security: cap_drop ALL, pids 50, mem 512m, host.docker.internal
├── requirements.txt             - pyyaml, aiohttp, python-telegram-bot, anthropic, openai
├── start.sh                     - One-command launch: ngrok tunnel (static domain support) + Docker build + start
├── stop.sh                      - Teardown: Docker + ngrok (--wipe to delete history)
└── CLAUDE.md                    - Project conventions for AI assistants
```

### How the Files Connect

```
main.py
  ├── loads .env → os.environ
  ├── loads config.yaml (resolves ${VAR} references)
  ├── creates SecurityGate (from config allowlist/rates)
  ├── creates SmartRouter or ProviderChain (auto-detects local providers)
  ├── creates Memory (SQLite at /data/picoagent.db)
  ├── creates Agent (wires router + security + memory)
  ├── creates shared aiohttp app (if webchat configured)
  ├── creates WebChatChannel (registers routes on shared app)
  ├── creates TelegramChannel (registers webhook on shared app)
  └── starts single HTTP server on port 8443

WebChatChannel (webchat.py)
  └── POST /api/chat → agent.handle_message(user_id, "webchat", text)

TelegramChannel (channels.py)
  └── POST /telegram/{id} → agent.handle_message(user_id, "telegram", text)

Agent (agent.py)
  ├── security.authorize() → reject if not allowed
  ├── memory.save() → persist user message
  ├── router.complete(messages, tools) → get LLM response
  │     ├── classify(text) → "simple" / "complex" / "tool"
  │     ├── simple → Ollama (local, free) → fallback to Claude if fails
  │     └── complex/tool → Claude (cloud, paid)
  ├── if tool_calls → execute tools → save results → loop (max 5)
  └── memory.save() → persist assistant reply
```

## Tests

```bash
# Install dependencies (needed for running tests outside Docker)
pip install -r requirements.txt

# Run all 79 tests
python -m pytest tests/ -v
```

Tests cover: security allowlist/blocklist/rate limiting, shell tool execution/timeout/truncation, provider chain config/fallback, SQLite memory persistence/trimming, agent ReAct loop/tool dispatch/security enforcement, router classification/routing/escalation, config loading, and web chat login/session/chat/history/logout.

## License

MIT
