#!/bin/bash
# Wrapper for atomic writes - creates backup before write

STATE_FILE="$1"
NEW_CONTENT="$2"
BACKUP_DIR="$(dirname "$STATE_FILE")/backups/state"
TIMESTAMP=$(date +%Y%m%d-%H%M%S-%N)

mkdir -p "$BACKUP_DIR"

# Create backup of current state BEFORE writing
if [ -f "$STATE_FILE" ]; then
    cp "$STATE_FILE" "$BACKUP_DIR/pre-write-$TIMESTAMP.json"
fi

# Write new content
echo "$NEW_CONTENT" > "$STATE_FILE"

# Keep only last 100 backups
ls -t "$BACKUP_DIR"/pre-write-*.json 2>/dev/null | tail -n +101 | xargs rm -f 2>/dev/null

exit 0
