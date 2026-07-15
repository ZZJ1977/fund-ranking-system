#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

HOST="${FUND_RANKING_HOST:-127.0.0.1}"
PORT="${FUND_RANKING_PORT:-8000}"
LOG_FILE="${FUND_RANKING_LOG:-tmp/fund-ranking-web.log}"
PID_FILE="${FUND_RANKING_PID_FILE:-tmp/fund-ranking-web.pid}"

if [ -f "$PID_FILE" ]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    DISPLAY_HOST="$HOST"
    if [ "$DISPLAY_HOST" = "0.0.0.0" ] || [ "$DISPLAY_HOST" = "::" ]; then
      DISPLAY_HOST="127.0.0.1"
    fi
    echo "Web server is already running: http://$DISPLAY_HOST:$PORT"
    echo "PID: $EXISTING_PID"
    exit 0
  fi
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -q -e .
mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$PID_FILE")"

.venv/bin/python - "$HOST" "$PORT" "$LOG_FILE" "$PID_FILE" <<'PY'
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


host, port_text, log_text, pid_text = sys.argv[1:5]
port = int(port_text)
root = Path.cwd()
log_path = root / log_text
pid_path = root / pid_text


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


if pid_path.exists():
    try:
        existing_pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        existing_pid = 0
    if existing_pid and process_is_running(existing_pid):
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        print(f"Web server is already running: http://{display_host}:{port}")
        print(f"PID: {existing_pid}")
        sys.exit(0)

family = socket.AF_INET6 if ":" in host and host != "0.0.0.0" else socket.AF_INET
bind_host = "" if host in {"0.0.0.0", "::"} else host
with socket.socket(family, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((bind_host, port))
    except OSError:
        print(f"Port {port} is already in use. Stop the existing process or set FUND_RANKING_PORT.")
        sys.exit(1)

log_path.parent.mkdir(parents=True, exist_ok=True)
pid_path.parent.mkdir(parents=True, exist_ok=True)
log_file = log_path.open("ab", buffering=0)
command = [
    str(root / ".venv/bin/fund-ranking-web"),
    "--host",
    host,
    "--port",
    str(port),
]
process = subprocess.Popen(
    command,
    cwd=root,
    stdin=subprocess.DEVNULL,
    stdout=log_file,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
pid_path.write_text(str(process.pid), encoding="utf-8")

time.sleep(1)
if process.poll() is not None:
    tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
    print("Web server failed to start. Recent log:")
    print("\n".join(tail))
    sys.exit(process.returncode or 1)

display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
health_url = f"http://{display_host}:{port}/health"
for _ in range(10):
    try:
        urllib.request.urlopen(health_url, timeout=0.5).read()
        break
    except Exception:
        time.sleep(0.5)

print(f"Started fund-ranking web: http://{display_host}:{port}")
print(f"Health check: {health_url}")
print(f"PID: {process.pid}")
print(f"Log: {log_path}")
PY
