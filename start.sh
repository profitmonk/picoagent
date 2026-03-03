#!/bin/bash
# Picoagent startup script — launches ngrok + Docker together
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Picoagent Startup ==="

# Kill any existing ngrok/picoagent
pkill ngrok 2>/dev/null || true
docker compose down 2>/dev/null || true

# Load NGROK_DOMAIN from .env if set
NGROK_DOMAIN=$(grep -s '^NGROK_DOMAIN=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")

# Start ngrok in background
echo "[1/3] Starting ngrok tunnel..."
if [ -n "$NGROK_DOMAIN" ]; then
    ngrok http 8443 --domain="$NGROK_DOMAIN" --log=stdout > /dev/null 2>&1 &
else
    ngrok http 8443 --log=stdout > /dev/null 2>&1 &
fi
NGROK_PID=$!

# Wait for ngrok to be ready
for i in $(seq 1 15); do
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null) && break
    sleep 1
done

if [ -z "$NGROK_URL" ]; then
    echo "ERROR: ngrok failed to start. Is it installed?"
    kill $NGROK_PID 2>/dev/null
    exit 1
fi

echo "       Tunnel: $NGROK_URL"

# Update .env with new ngrok URL
echo "[2/3] Updating webhook URL..."
if grep -q "TELEGRAM_WEBHOOK_URL" .env; then
    sed -i '' "s|TELEGRAM_WEBHOOK_URL=.*|TELEGRAM_WEBHOOK_URL=$NGROK_URL|" .env
else
    echo "TELEGRAM_WEBHOOK_URL=$NGROK_URL" >> .env
fi

# Start Docker container
echo "[3/3] Starting Docker container..."
docker compose up --build -d 2>&1 | tail -3

sleep 3
echo ""
echo "=== Picoagent Running ==="
echo "Tunnel:    $NGROK_URL"
echo "Web Chat:  $NGROK_URL  (open in browser)"
echo "ngrok PID: $NGROK_PID"
echo "Container: $(docker compose ps --format '{{.Status}}')"
echo ""
echo "Commands:"
echo "  Logs:    docker compose logs -f"
echo "  Stop:    ./stop.sh  (or: docker compose down && pkill ngrok)"
echo "  Status:  docker compose ps"
