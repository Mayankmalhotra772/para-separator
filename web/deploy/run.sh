#!/usr/bin/env bash
set -euo pipefail

# Serve the app and connect the cloudflared tunnel in one command.
# Expected layout (as on iit-hyderabad):
#   <base>/cloudflared                       - cloudflared binary
#   <base>/.cloudflared/config-remarks.yml   - tunnel config (ingress -> localhost:8013)
#   <base>/.cloudflared/remarks.json         - tunnel credentials
#   <base>/parawise-remarks/                 - this repo (run.sh lives in deploy/)

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_DIR="$(dirname "$APP_DIR")"
PORT=8013
CONFIG="$BASE_DIR/.cloudflared/config-remarks.yml"
CLOUDFLARED="$BASE_DIR/cloudflared"

[ -x "$CLOUDFLARED" ] || { echo "ERROR: cloudflared binary not found at $CLOUDFLARED"; exit 1; }
[ -f "$CONFIG" ]      || { echo "ERROR: tunnel config not found at $CONFIG"; exit 1; }

cd "$APP_DIR"
# bind to localhost only - the site is reachable exclusively through the tunnel
python3 -m http.server "$PORT" --bind 127.0.0.1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

echo "Serving $APP_DIR on http://127.0.0.1:$PORT"
echo "Connecting tunnel -> https://remarks.jaypokale.me"
"$CLOUDFLARED" --config "$CONFIG" tunnel run
