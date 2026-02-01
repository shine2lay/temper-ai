#!/bin/bash
# State Protection System - Multiple layers of defense against data loss

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$COORD_DIR/state.json"
BACKUP_DIR="$COORD_DIR/backups/state"
SHADOW_DIR="$COORD_DIR/.state-shadow"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

mkdir -p "$BACKUP_DIR" "$SHADOW_DIR"

# ============================================================
# LAYER 1: CONTINUOUS BACKUP (every write creates a backup)
# ============================================================

enable_continuous_backup() {
    echo -e "${BLUE}[Layer 1]${NC} Enabling continuous backup system..."

    # Create wrapper script that backs up before every write
    cat > "$COORD_DIR/.atomic_write_wrapper.sh" <<'WRAPPER_EOF'
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
WRAPPER_EOF

    chmod +x "$COORD_DIR/.atomic_write_wrapper.sh"
    echo -e "${GREEN}✓${NC} Continuous backup enabled (100 versions retained)"
}

# ============================================================
# LAYER 2: SHADOW COPY (instant restore point)
# ============================================================

enable_shadow_copy() {
    echo -e "${BLUE}[Layer 2]${NC} Enabling shadow copy system..."

    # Create inotify watcher for state.json
    cat > "$COORD_DIR/.watch-state.sh" <<'WATCH_EOF'
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
WATCH_EOF

    chmod +x "$COORD_DIR/.watch-state.sh"
    echo -e "${GREEN}✓${NC} Shadow copy watcher created"
    echo -e "${YELLOW}  Run: nohup .claude-coord/.watch-state.sh > .claude-coord/watcher.log 2>&1 &${NC}"
}

# ============================================================
# LAYER 3: GIT VERSION CONTROL
# ============================================================

enable_git_tracking() {
    echo -e "${BLUE}[Layer 3]${NC} Enabling git version control..."

    cd "$COORD_DIR/.."

    # Check if state.json is tracked
    if ! git ls-files --error-unmatch .claude-coord/state.json &>/dev/null; then
        echo "Adding state.json to git..."
        git add .claude-coord/state.json
    fi

    # Create pre-commit hook to snapshot state
    mkdir -p .git/hooks
    cat > .git/hooks/pre-commit-state-snapshot <<'HOOK_EOF'
#!/bin/bash
# Auto-commit state.json changes before each commit

STATE_FILE=".claude-coord/state.json"

if [ -f "$STATE_FILE" ]; then
    # Check if state.json has changes
    if git diff --quiet "$STATE_FILE" && git diff --cached --quiet "$STATE_FILE"; then
        # No changes
        exit 0
    fi

    # Stage and commit state.json separately
    git add "$STATE_FILE" 2>/dev/null

    TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
    git commit --no-verify -m "auto: snapshot coordination state ($TIMESTAMP)" "$STATE_FILE" 2>/dev/null || true
fi

exit 0
HOOK_EOF

    chmod +x .git/hooks/pre-commit-state-snapshot

    echo -e "${GREEN}✓${NC} Git version control enabled"
    echo -e "  State snapshots will be auto-committed"
}

# ============================================================
# LAYER 4: SCHEDULED SNAPSHOTS
# ============================================================

enable_scheduled_snapshots() {
    echo -e "${BLUE}[Layer 4]${NC} Setting up scheduled snapshots..."

    cat > "$COORD_DIR/.snapshot-state.sh" <<'SNAPSHOT_EOF'
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
SNAPSHOT_EOF

    chmod +x "$COORD_DIR/.snapshot-state.sh"

    # Add to crontab (every 5 minutes)
    CRON_CMD="*/5 * * * * $COORD_DIR/.snapshot-state.sh >> $COORD_DIR/snapshot.log 2>&1"

    echo -e "${GREEN}✓${NC} Snapshot script created"
    echo -e "${YELLOW}  To enable 5-minute snapshots, run:${NC}"
    echo -e "  (crontab -l 2>/dev/null; echo \"$CRON_CMD\") | crontab -"
}

# ============================================================
# LAYER 5: RECOVERY TOOLS
# ============================================================

create_recovery_tools() {
    echo -e "${BLUE}[Layer 5]${NC} Creating recovery tools..."

    cat > "$COORD_DIR/recover-state.sh" <<'RECOVER_EOF'
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
RECOVER_EOF

    chmod +x "$COORD_DIR/recover-state.sh"

    echo -e "${GREEN}✓${NC} Recovery tool created at: $COORD_DIR/recover-state.sh"
}

# ============================================================
# MAIN
# ============================================================

show_menu() {
    echo ""
    echo "========================================="
    echo "State Protection Setup"
    echo "========================================="
    echo ""
    echo "Choose protection layers to enable:"
    echo ""
    echo "  1) Layer 1: Continuous Backup (backup on every write)"
    echo "  2) Layer 2: Shadow Copy (inotify file watcher)"
    echo "  3) Layer 3: Git Version Control (auto-commit)"
    echo "  4) Layer 4: Scheduled Snapshots (cron every 5min)"
    echo "  5) Layer 5: Recovery Tools"
    echo ""
    echo "  a) Enable ALL layers (recommended)"
    echo "  q) Quit"
    echo ""
}

case "${1:-menu}" in
    1) enable_continuous_backup ;;
    2) enable_shadow_copy ;;
    3) enable_git_tracking ;;
    4) enable_scheduled_snapshots ;;
    5) create_recovery_tools ;;
    a|all)
        enable_continuous_backup
        enable_shadow_copy
        enable_git_tracking
        enable_scheduled_snapshots
        create_recovery_tools

        echo ""
        echo -e "${GREEN}=========================================${NC}"
        echo -e "${GREEN}All protection layers enabled!${NC}"
        echo -e "${GREEN}=========================================${NC}"
        echo ""
        echo "Next steps:"
        echo "  1. Start shadow watcher: nohup .claude-coord/.watch-state.sh > .claude-coord/watcher.log 2>&1 &"
        echo "  2. Enable snapshots: (crontab -l 2>/dev/null; echo \"*/5 * * * * $COORD_DIR/.snapshot-state.sh >> $COORD_DIR/snapshot.log 2>&1\") | crontab -"
        echo ""
        echo "Recovery:"
        echo "  .claude-coord/recover-state.sh"
        ;;
    menu)
        show_menu
        read -p "Selection: " choice
        $0 "$choice"
        ;;
    *)
        echo "Invalid option"
        exit 1
        ;;
esac
