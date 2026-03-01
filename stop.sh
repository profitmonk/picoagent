#!/bin/bash
# Picoagent shutdown script
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Picoagent Shutdown ==="

echo "Stopping container..."
docker compose down 2>/dev/null || true

echo "Stopping ngrok..."
pkill ngrok 2>/dev/null || true

echo "Done."
