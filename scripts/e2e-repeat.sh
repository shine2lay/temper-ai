#!/usr/bin/env bash
# Run the browser suite N times against a server of its own and say whether
# every run agreed.
#
#   scripts/e2e-repeat.sh [N] [PORT]
#
# This is how a flaky test is proved fixed: one green run proves nothing, it
# was green most of the time before. Ten in a row is the bar.
set -euo pipefail

N="${1:-10}"
PORT="${2:-8452}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$(mktemp -u /tmp/temper-e2e-XXXXXX.db)"
LOG="$(mktemp -d /tmp/temper-e2e-logs-XXXXXX)"

cd "$ROOT"
echo "server on :$PORT, database $DB, logs in $LOG"
TEMPER_DATABASE_URL="sqlite:///$DB" uv run temper serve --port "$PORT" > "$LOG/server.log" 2>&1 &
server=$!
trap 'kill $server 2>/dev/null || true; rm -f "$DB"' EXIT

for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$PORT/api/health" > /dev/null && break
    sleep 1
done
if ! curl -sf "http://127.0.0.1:$PORT/api/health" > /dev/null; then
    echo "the server never came up"; tail -20 "$LOG/server.log"; exit 1
fi

passes=0
failures=()
for i in $(seq 1 "$N"); do
    printf 'run %2d/%s ... ' "$i" "$N"
    if (cd frontend && TEMPER_E2E_BASE_URL="http://127.0.0.1:$PORT" \
            PLAYWRIGHT_JUNIT_OUTPUT_NAME="$LOG/run-$i.xml" \
            npx playwright test --reporter=junit --retries=0 > "$LOG/run-$i.log" 2>&1); then
        echo "green"
        passes=$((passes + 1))
    else
        echo "RED — $LOG/run-$i.log"
        failures+=("$i")
    fi
done

echo
echo "$passes of $N runs green"
if [ ${#failures[@]} -gt 0 ]; then
    echo "red runs: ${failures[*]}"
fi
python3 scripts/flaky_report.py "$LOG"/run-*.xml --title "$N local runs" --soft
[ ${#failures[@]} -eq 0 ]
