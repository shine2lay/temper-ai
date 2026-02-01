#!/bin/bash
# Watch state.json and maintain shadow copies

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$COORD_DIR/state.json"
SHADOW_DIR="$COORD_DIR/.state-shadow"

mkdir -p "$SHADOW_DIR"

# Install inotify-tools if not available
if ! command -v inotifywait &> /dev/null; then
    echo "WARNING: inotify-tools not installed. Install with:"
    echo "  sudo apt-get install inotify-tools"
    exit 1
fi

echo "Shadow copy watcher started for $STATE_FILE"

while inotifywait -e modify,move_self,delete_self "$STATE_FILE" 2>/dev/null; do
    if [ -f "$STATE_FILE" ]; then
        TIMESTAMP=$(date +%Y%m%d-%H%M%S)
        cp "$STATE_FILE" "$SHADOW_DIR/shadow-$TIMESTAMP.json"

        # Keep last 50 shadow copies
        ls -t "$SHADOW_DIR"/shadow-*.json | tail -n +51 | xargs rm -f 2>/dev/null

        # Alert if state was replaced (size changed dramatically)
        SIZE=$(stat -f%z "$STATE_FILE" 2>/dev/null || stat -c%s "$STATE_FILE")
        PREV_SIZE=$(ls -t "$SHADOW_DIR"/shadow-*.json | sed -n '2p' | xargs stat -f%z 2>/dev/null || echo "0")

        if [ "$SIZE" -lt $((PREV_SIZE / 2)) ]; then
            echo "⚠️  WARNING: state.json size dropped significantly!"
            echo "   Previous: $PREV_SIZE bytes → Current: $SIZE bytes"
            echo "   Backup available at: $SHADOW_DIR/shadow-$TIMESTAMP.json"
        fi
    else
        echo "⚠️  WARNING: state.json was deleted!"
        # Auto-restore from latest shadow copy
        LATEST=$(ls -t "$SHADOW_DIR"/shadow-*.json | head -n 1)
        if [ -n "$LATEST" ]; then
            cp "$LATEST" "$STATE_FILE"
            echo "✓ Auto-restored from: $LATEST"
        fi
    fi
done
