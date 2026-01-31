#!/bin/bash
# cleanup-on-exit.sh - Stop hook for session end
# Automatically releases all locks and unregisters agent when session ends
#
# IMPORTANT: This hook verifies PID ownership before unregistering to prevent
# accidentally unregistering agents from other sessions when CLAUDE_AGENT_ID
# is inherited from parent shell environment.

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COORD="$COORD_DIR/claude-coord.sh"
STATE_FILE="$COORD_DIR/state.json"

# Get agent ID from environment
AGENT_ID="${CLAUDE_AGENT_ID:-}"

# Not in coordinated session - nothing to do
[ -z "$AGENT_ID" ] && exit 0

# Get the PID that registered this agent (from state.json)
REGISTERED_PID=""
if [ -f "$STATE_FILE" ]; then
    REGISTERED_PID=$(jq -r --arg id "$AGENT_ID" '.agents[$id].pid // empty' "$STATE_FILE" 2>/dev/null)
fi

# If agent not found in state, nothing to clean up
if [ -z "$REGISTERED_PID" ]; then
    echo "[cleanup] Agent $AGENT_ID not found in state (already unregistered or never registered)" >&2
    exit 0
fi

# CRITICAL: Verify we are the owner of this agent by checking PID ancestry
# The registered PID should be an ancestor of our current process (claude)
# This prevents unregistering agents from OTHER sessions when CLAUDE_AGENT_ID
# was inherited from parent environment
OUR_PID=$$
IS_OWNER=false

# Walk up the process tree to find if REGISTERED_PID is our ancestor
check_pid=$OUR_PID
while [ "$check_pid" -gt 1 ]; do
    if [ "$check_pid" = "$REGISTERED_PID" ]; then
        IS_OWNER=true
        break
    fi
    # Get parent PID
    check_pid=$(ps -o ppid= -p "$check_pid" 2>/dev/null | tr -d ' ')
    [ -z "$check_pid" ] && break
done

if [ "$IS_OWNER" = false ]; then
    echo "[cleanup] Skipping cleanup - agent $AGENT_ID owned by PID $REGISTERED_PID (not our ancestor)" >&2
    exit 0
fi

# We verified ownership - safe to clean up
echo "[cleanup] Session ending - verified owner of agent $AGENT_ID (PID $REGISTERED_PID)" >&2

# Release all locks held by this agent
UNLOCK_RESULT=$("$COORD" unlock-all "$AGENT_ID" 2>&1)
echo "[cleanup] $UNLOCK_RESULT" >&2

# Unregister the agent
UNREG_RESULT=$("$COORD" unregister "$AGENT_ID" 2>&1)
echo "[cleanup] $UNREG_RESULT" >&2

exit 0
