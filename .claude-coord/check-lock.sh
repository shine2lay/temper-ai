#!/bin/bash
# check-lock.sh - PreToolUse hook that enforces file locks
# Blocks Edit/Write operations on files locked by other agents

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COORD="$COORD_DIR/claude-coord.sh"

# Read JSON input from stdin (provided by Claude Code hook system)
INPUT=$(cat)

# Extract file path from tool input
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# No file path means not a file operation - allow it
[ -z "$FILE_PATH" ] && exit 0

# Get agent ID from environment (set by claude-agent wrapper)
AGENT_ID="${CLAUDE_AGENT_ID:-}"

# If no agent ID set, we're not in a coordinated session - allow everything
# This maintains backwards compatibility with normal claude usage
[ -z "$AGENT_ID" ] && exit 0

# Normalize the path
FILE_PATH=$(realpath -m "$FILE_PATH" 2>/dev/null || echo "$FILE_PATH")

# Check if we own the lock or if it's unlocked
RESULT=$("$COORD" check "$AGENT_ID" "$FILE_PATH" 2>&1) || {
    # Lock check failed - file is locked by someone else
    echo "BLOCKED: $FILE_PATH is $RESULT" >&2
    echo "" >&2
    echo "To acquire the lock, run:" >&2
    echo "  .claude-coord/claude-coord.sh lock $AGENT_ID $FILE_PATH" >&2
    echo "" >&2
    echo "Or acquire multiple locks at once:" >&2
    echo "  .claude-coord/claude-coord.sh lock-all $AGENT_ID file1 file2 ..." >&2
    exit 2  # Exit code 2 blocks the tool in Claude Code
}

# Lock check passed - we own it or it's unlocked
exit 0
