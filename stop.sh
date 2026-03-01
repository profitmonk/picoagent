#!/bin/bash
# Picoagent shutdown script
# Usage: ./stop.sh          — stop container + ngrok
#        ./stop.sh --wipe   — also delete conversation history
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Picoagent Shutdown ==="

echo "Stopping container..."
docker compose down 2>/dev/null || true

echo "Stopping ngrok..."
pkill ngrok 2>/dev/null || true

if [ "$1" = "--wipe" ]; then
    echo "Wiping conversation history..."
    docker volume rm picoagent_picoagent-data 2>/dev/null && echo "Memory wiped." || echo "No volume to remove."
fi

echo "Done."
