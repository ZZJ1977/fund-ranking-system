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

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -q -e .
.venv/bin/fund-ranking-web --host "$HOST" --port "$PORT"
