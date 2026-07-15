#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PID_FILE="${FUND_RANKING_PID_FILE:-tmp/fund-ranking-web.pid}"

python3 - "$PID_FILE" <<'PY'
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path


pid_path = Path(sys.argv[1])
if not pid_path.exists():
    print("No PID file found. The web server may not be running.")
    sys.exit(0)

try:
    pid = int(pid_path.read_text(encoding="utf-8").strip())
except ValueError:
    pid_path.unlink(missing_ok=True)
    print("Invalid PID file removed.")
    sys.exit(0)

try:
    os.kill(pid, signal.SIGTERM)
except ProcessLookupError:
    pid_path.unlink(missing_ok=True)
    print("Web server was not running. PID file removed.")
    sys.exit(0)

for _ in range(30):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        print(f"Stopped web server PID {pid}.")
        sys.exit(0)
    time.sleep(0.2)

print(f"PID {pid} did not stop after SIGTERM. Check it manually if needed.")
PY
