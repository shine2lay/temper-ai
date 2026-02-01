#!/bin/bash
# State Recovery Tool - Find and restore the best backup

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$COORD_DIR/state.json"

echo "========================================="
echo "State Recovery Tool"
echo "========================================="
echo ""

# Find all possible backups
echo "Searching for backups..."
echo ""

BACKUPS=$(find "$COORD_DIR" -name "*.json" -type f | grep -E "(backup|shadow|snapshot|pre-write)" | sort -r)

if [ -z "$BACKUPS" ]; then
    echo "No backups found!"
    exit 1
fi

# Show backups with task counts
echo "Available backups:"
echo ""
printf "%-4s %-50s %-15s %-10s\n" "#" "File" "Modified" "Tasks"
echo "─────────────────────────────────────────────────────────────────────────────────"

i=1
declare -a backup_files
declare -a backup_info

while IFS= read -r backup; do
    TIMESTAMP=$(stat -c '%y' "$backup" 2>/dev/null | cut -d. -f1)
    TASKS=$(jq '.tasks | length' "$backup" 2>/dev/null || echo "ERR")
    SIZE=$(stat -c '%s' "$backup" 2>/dev/null || echo "0")

    if [ "$TASKS" != "ERR" ] && [ "$TASKS" -gt 0 ]; then
        backup_files[$i]="$backup"
        backup_info[$i]="$TASKS tasks, $SIZE bytes"

        FILENAME=$(basename "$backup")
        printf "%-4s %-50s %-15s %-10s\n" "$i" "$FILENAME" "$TIMESTAMP" "$TASKS"
        i=$((i + 1))
    fi
done <<< "$BACKUPS"

echo ""
echo "Current state: $(jq '.tasks | length' "$STATE_FILE" 2>/dev/null || echo 'MISSING') tasks"
echo ""

read -p "Enter backup number to restore (or 'q' to quit): " choice

if [ "$choice" = "q" ]; then
    echo "Cancelled."
    exit 0
fi

if [ -n "${backup_files[$choice]}" ]; then
    SELECTED="${backup_files[$choice]}"
    echo ""
    echo "Selected: $SELECTED"
    echo "         ${backup_info[$choice]}"
    echo ""
    read -p "Restore this backup? (yes/no): " confirm

    if [ "$confirm" = "yes" ]; then
        cp "$STATE_FILE" "$COORD_DIR/state.json.before-recovery-$(date +%Y%m%d-%H%M%S)" 2>/dev/null
        cp "$SELECTED" "$STATE_FILE"
        echo "✓ State restored successfully!"
        echo "  New task count: $(jq '.tasks | length' "$STATE_FILE")"
    else
        echo "Cancelled."
    fi
else
    echo "Invalid selection."
    exit 1
fi
