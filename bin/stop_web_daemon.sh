#!/usr/bin/env bash

set -euo pipefail

# Usage:
#   sh bin/stop_web_daemon.sh [PORT]
# If PID file exists, prefer it; otherwise try to kill process by listening port.

PORT=${1:-5000}

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$LOG_DIR/web_server.pid"

if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE" || true)
  if [[ -n "${PID}" ]] && ps -p "$PID" >/dev/null 2>&1; then
    echo "[stop_web_daemon] Stopping PID $PID ..."
    kill "$PID" || true
    sleep 1
    if ps -p "$PID" >/dev/null 2>&1; then
      echo "[stop_web_daemon] Force killing PID $PID ..."
      kill -9 "$PID" || true
    fi
    rm -f "$PID_FILE"
    echo "[stop_web_daemon] Stopped."
    exit 0
  fi
fi

# Fallback by port
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN -Pn || true)
  if [[ -n "$PIDS" ]]; then
    echo "[stop_web_daemon] Stopping processes on port $PORT: $PIDS"
    kill $PIDS || true
    sleep 1
    # Hard kill leftover
    for p in $PIDS; do
      if ps -p "$p" >/dev/null 2>&1; then kill -9 "$p" || true; fi
    done
    echo "[stop_web_daemon] Stopped."
    exit 0
  fi
fi

echo "[stop_web_daemon] No running web server found for port $PORT."


