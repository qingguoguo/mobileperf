#!/usr/bin/env bash

set -euo pipefail

# Usage:
#   sh bin/start_web_daemon.sh [PORT]
# Defaults:
#   PORT=5000

PORT=${1:-5000}

# Project root
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$LOG_DIR/web_server.pid"
ERR_LOG="$LOG_DIR/web_server_error.log"

mkdir -p "$LOG_DIR"

# If something already listens on the port, print info and exit
if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:"$PORT" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
    echo "[start_web_daemon] Port $PORT is already in use."
    echo "Tip: open http://localhost:$PORT"
    exit 0
  fi
fi

# If pid file exists and process is alive, keep it
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE" || true)
  if [[ -n "${OLD_PID}" ]] && ps -p "$OLD_PID" >/dev/null 2>&1; then
    echo "[start_web_daemon] Web server already running (PID: $OLD_PID)."
    echo "Tip: open http://localhost:$PORT"
    exit 0
  fi
fi

PY=${PYTHON:-python3}

echo "[start_web_daemon] Starting MobilePerf Web Server in background on port $PORT ..."

# Start as fully detached daemon via nohup
nohup "$PY" -m mobileperf.android.web.start_web_server "$PORT" \
  >/dev/null 2>>"$ERR_LOG" &

NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

echo "[start_web_daemon] Started (PID: $NEW_PID)"
echo "[start_web_daemon] Access at: http://localhost:$PORT"
echo "[start_web_daemon] Logs: $ERR_LOG"


