#!/bin/bash
# Periodic state snapshots

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$COORD_DIR/state.json"
SNAPSHOT_DIR="$COORD_DIR/backups/snapshots"

mkdir -p "$SNAPSHOT_DIR"

if [ -f "$STATE_FILE" ]; then
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    TASK_COUNT=$(jq '.tasks | length' "$STATE_FILE" 2>/dev/null || echo "0")

    cp "$STATE_FILE" "$SNAPSHOT_DIR/snapshot-$TIMESTAMP-tasks$TASK_COUNT.json"

    # Keep last 100 snapshots
    ls -t "$SNAPSHOT_DIR"/snapshot-*.json | tail -n +101 | xargs rm -f 2>/dev/null

    echo "$(date): Created snapshot with $TASK_COUNT tasks"
fi
