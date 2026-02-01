#!/bin/bash
# Session Start - Run before beginning work

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Starting coordination session..."
echo ""

# 1. Create snapshot
echo "📸 Creating session snapshot..."
$COORD_DIR/.snapshot-state.sh

# 2. Show current status
echo ""
echo "📊 Current Status:"
$COORD_DIR/claude-coord.sh task-stats

# 3. Show active tasks
echo ""
echo "🔄 Tasks in progress:"
$COORD_DIR/claude-coord.sh task-list in_progress

# 4. Check for orphaned tasks/locks
echo ""
echo "🔍 Checking for orphaned tasks..."
ORPHANED=$($COORD_DIR/claude-coord.sh task-recover --dry-run 2>&1 | grep "ORPHANED" | wc -l)
if [ "$ORPHANED" -gt 0 ]; then
    echo "⚠️  Found $ORPHANED orphaned tasks"
    read -p "   Release them? (y/n): " release
    if [ "$release" = "y" ]; then
        $COORD_DIR/claude-coord.sh task-recover
    fi
fi

echo ""
echo "✅ Session ready!"
echo ""
