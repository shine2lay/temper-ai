#!/bin/bash
# protect-critical-files.sh - PreToolUse hook to block modifications to protected files
# Add this to your Claude Code hooks configuration

# List of protected files (relative to project root)
# NOTE: This script protects itself - cannot modify this list without explicit user permission
PROTECTED_FILES=(
    ".claude-coord/protect-critical-files.sh"  # This script itself
    ".claude-coord/claude-coord.sh"
    ".claude-coord/state.json"
    ".claude-coord/task-spec-helpers.sh"
    # Add more files here
)

# Read JSON input from stdin
INPUT=$(cat)

# Extract tool name and file path
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only check Edit and Write tools
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0  # Allow other tools
fi

# No file path means not a file operation
[ -z "$FILE_PATH" ] && exit 0

# Normalize the path
FILE_PATH=$(realpath -m "$FILE_PATH" 2>/dev/null || echo "$FILE_PATH")
PROJECT_ROOT=$(pwd)

# Check if file is in protected list
for protected in "${PROTECTED_FILES[@]}"; do
    PROTECTED_PATH=$(realpath -m "$PROJECT_ROOT/$protected" 2>/dev/null || echo "$PROJECT_ROOT/$protected")

    if [[ "$FILE_PATH" == "$PROTECTED_PATH" ]]; then
        echo "❌ BLOCKED: $protected is a protected file" >&2
        echo "" >&2
        echo "This file cannot be modified without explicit permission." >&2
        echo "If you need to modify it, please:" >&2
        echo "  1. Ask the user for explicit permission first" >&2
        echo "  2. Remove it from PROTECTED_FILES in .claude-coord/protect-critical-files.sh" >&2
        echo "  3. Or disable this hook temporarily" >&2
        echo "" >&2
        exit 2  # Exit code 2 blocks the tool in Claude Code
    fi
done

# File not protected - allow the operation
exit 0
