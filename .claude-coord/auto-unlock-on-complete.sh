#!/bin/bash
# auto-unlock-on-complete.sh - PostToolUse hook for TaskUpdate
# Automatically releases all locks when a task is marked as completed

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COORD="$COORD_DIR/claude-coord.sh"

# Get agent ID from environment
AGENT_ID="${CLAUDE_AGENT_ID:-}"

# Not in coordinated session - nothing to do
[ -z "$AGENT_ID" ] && exit 0

# Read hook input from stdin
INPUT=$(cat)

# Check if this TaskUpdate set status to "completed"
STATUS=$(echo "$INPUT" | jq -r '.tool_input.status // empty' 2>/dev/null)

if [ "$STATUS" = "completed" ]; then
    # Auto-release all locks held by this agent
    RESULT=$("$COORD" unlock-all "$AGENT_ID" 2>&1)
    echo "[auto-unlock] Task completed - $RESULT" >&2
fi

exit 0
