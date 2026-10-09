#!/usr/bin/env bash
# Run the browser tests that need no temper N times and say whether every run
# agreed.
#
#   scripts/e2e-repeat.sh [N] [playwright args ...]
#
# This is how a flaky test is proved fixed: one green run proves nothing, it
# was green most of the time before. Ten in a row is the bar.
#
# The same tests GitHub runs: the spec files listed in frontend/e2e/server-free.txt,
# against the built dashboard served by scripts/e2e_static_server.py
# (frontend/playwright.server-free.config.ts). No temper is started: AGENTS.md
# rule 15 allows no copy of Temper but the live one, and a browser test that
# starts runs or writes never runs on the live one. Extra arguments go to
# Playwright, e.g. one spec file or `-g "<test title>"`.
set -euo pipefail

N="${1:-10}"
shift || true
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$(mktemp -d /tmp/temper-e2e-logs-XXXXXX)"

cd "$ROOT"
listed=$(sed -e 's/#.*//' -e 's/[[:space:]]//g' frontend/e2e/server-free.txt | grep -c . || true)
if [ "$listed" = 0 ]; then
    echo "no spec file is listed in frontend/e2e/server-free.txt, so there is nothing to repeat"
    exit 2
fi
if [ ! -f frontend/dist/index.html ]; then
    echo "no built dashboard: run 'npm run build' in frontend/ first"
    exit 1
fi
echo "$listed spec file(s) from frontend/e2e/server-free.txt, logs in $LOG"

passes=0
failures=()
for i in $(seq 1 "$N"); do
    printf 'run %2d/%s ... ' "$i" "$N"
    if (cd frontend && PLAYWRIGHT_JUNIT_OUTPUT_NAME="$LOG/run-$i.xml" \
            npx playwright test -c playwright.server-free.config.ts --reporter=junit --retries=0 "$@" \
            > "$LOG/run-$i.log" 2>&1); then
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
