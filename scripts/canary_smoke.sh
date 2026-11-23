#!/usr/bin/env bash
# Starts the mock server as a stand-in canary, sends traffic, and runs the gate against it.
# Usage: scripts/canary_smoke.sh [error_rate]   (error_rate 0 = healthy, 0.5 = bad canary)
# Exit code is the gate's: 0 promote, 1 rollback, 2 bad input.
set -u
ERR="${1:-0}"
PORT="${PORT:-$(python -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ERROR_RATE="$ERR" TOKEN_DELAY=0.005 RATE_CAPACITY=1000 RATE_REFILL=1000 PORT="$PORT" \
  python -m aidelivery.mock_server >/tmp/canary-mock.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null; wait $PID 2>/dev/null' EXIT

for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null && break
  sleep 0.2
done

for _ in $(seq 1 40); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/v1/chat/completions" \
    -H 'X-Tenant-ID: canary' -H 'content-type: application/json' \
    -d '{"model":"mock-model","messages":[{"role":"user","content":"hello"}]}'
done

aidelivery gate \
  --metrics "http://127.0.0.1:$PORT/metrics" \
  --eval "$ROOT/tests/fixtures/eval_good.json" \
  --thresholds "$ROOT/config/thresholds.json"
