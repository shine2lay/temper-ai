#!/bin/bash
# protect-critical-files-bash.sh - PreToolUse hook for Bash tool
# Blocks bash commands that write to protected files

# List of protected files (must match protect-critical-files.sh)
PROTECTED_FILES=(
    ".claude-coord/protect-critical-files.sh"
    ".claude-coord/claude-coord.sh"
    ".claude-coord/state.json"
    ".claude-coord/task-spec-helpers.sh"
)

# Read JSON input from stdin
INPUT=$(cat)

# Extract tool name and command
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only check Bash tool
if [[ "$TOOL_NAME" != "Bash" ]]; then
    exit 0
fi

# No command means not a bash operation
[ -z "$COMMAND" ] && exit 0

PROJECT_ROOT=$(pwd)

# Check for file redirection operators in command
for protected in "${PROTECTED_FILES[@]}"; do
    PROTECTED_PATH="$PROJECT_ROOT/$protected"

    # Check for various redirection patterns
    if echo "$COMMAND" | grep -qE "(>|>>|tee).*${protected}"; then
        echo "❌ BLOCKED: Bash command attempts to write to protected file: $protected" >&2
        echo "" >&2
        echo "Detected write operation in command:" >&2
        echo "  $COMMAND" >&2
        echo "" >&2
        echo "Protected files cannot be modified via bash redirection." >&2
        echo "Use Write or Edit tools instead, or get explicit user permission." >&2
        echo "" >&2
        exit 2  # Exit code 2 blocks the tool
    fi

    # Check for sed -i (in-place edit)
    if echo "$COMMAND" | grep -qE "sed.*-i.*${protected}"; then
        echo "❌ BLOCKED: Bash sed -i attempts to modify protected file: $protected" >&2
        exit 2
    fi

    # Check for cat/echo with EOF redirecting to file
    if echo "$COMMAND" | grep -qE "(cat|echo).*EOF.*${protected}"; then
        echo "❌ BLOCKED: Bash heredoc attempts to write to protected file: $protected" >&2
        exit 2
    fi
done

# Command doesn't affect protected files - allow it
exit 0
