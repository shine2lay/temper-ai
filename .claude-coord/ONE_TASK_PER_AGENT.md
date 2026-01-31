# One Task Per Agent Limit

## What This Does

Prevents an agent from claiming multiple tasks simultaneously. An agent must complete or release their current task before claiming a new one.

## Why This Is Useful

- Prevents task hoarding
- Ensures focused work (one task at a time)
- Better task distribution across agents
- Clearer task ownership

## The Change

Add a check in `cmd_task_claim()` to verify the agent doesn't already have an in_progress task.

## How to Apply

### Option 1: Manual Edit (You Do This)

1. **Temporarily unprotect** `.claude-coord/claude-coord.sh`:
   - Edit `.claude-coord/protect-critical-files.sh`
   - Comment out the claude-coord.sh line

2. **Open** `.claude-coord/claude-coord.sh`

3. **Find** the `cmd_task_claim()` function (around line 547)

4. **Add** this code after line 580 (after the existing owner check):

```bash
        # NEW: Check if agent already has a claimed task
        existing_tasks=$(echo "$state" | jq -r --arg owner "$agent_id" \
            "[.tasks | to_entries[] | select(.value.owner == \$owner and .value.status == \"in_progress\")] | length")

        if [ "$existing_tasks" -gt 0 ]; then
            current_task=$(echo "$state" | jq -r --arg owner "$agent_id" \
                "[.tasks | to_entries[] | select(.value.owner == \$owner and .value.status == \"in_progress\")][0] | .key")
            echo "FAILED: Agent $agent_id already has a claimed task: $current_task" >&2
            echo "Release or complete $current_task before claiming a new task" >&2
            exit 1
        fi
```

5. **Re-protect** the file (uncomment the line in protect-critical-files.sh)

### Option 2: Let Claude Do It

1. **You manually unprotect** the file (edit protect-critical-files.sh)
2. **Tell Claude**: "apply the one-task-per-agent change"
3. **Claude makes the change**
4. **You re-protect** the file

## Testing the Change

```bash
# Claim first task - should succeed
.claude-coord/claude-coord.sh task-claim agent-001 task-A
# Output: Claimed task: task-A

# Try to claim second task - should fail
.claude-coord/claude-coord.sh task-claim agent-001 task-B
# Output: FAILED: Agent agent-001 already has a claimed task: task-A
#         Release or complete task-A before claiming a new task

# Release first task
.claude-coord/claude-coord.sh task-release agent-001 task-A

# Now can claim second task
.claude-coord/claude-coord.sh task-claim agent-001 task-B
# Output: Claimed task: task-B
```

## Error Messages

When an agent tries to claim a second task:

```
FAILED: Agent agent-123 already has a claimed task: my-task-01
Release or complete my-task-01 before claiming a new task
```

## Impact on Workflows

- **Automated workflows**: Must complete or release tasks before claiming new ones
- **Multi-agent coordination**: Better task distribution
- **Manual task management**: Clearer what each agent is working on

## Complete Updated Function

The complete updated function is saved in: `/tmp/cmd_task_claim_updated.sh`

You can use it as a reference when making the change.
