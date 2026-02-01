# Claude Multi-Agent Coordination

This system allows multiple Claude Code instances to work on the same codebase without conflicts.

## Quick Start

```bash
# Terminal 1
.claude-coord/claude-agent

# Terminal 2 (different terminal)
.claude-coord/claude-agent
```

Each instance gets a unique agent ID and can coordinate via file locks.

## How It Works

1. **Start Claude with the wrapper** - registers you as an agent
2. **Lock files before editing** - prevents conflicts
3. **If locked by another agent** - move to different task
4. **Release locks when done** - let others work on those files
5. **On exit** - automatic cleanup of your locks

## Commands

### Starting a Session

```bash
# Auto-generated agent ID
.claude-coord/claude-agent

# Custom agent ID
.claude-coord/claude-agent alice

# Check who's working on what
.claude-coord/claude-agent status
```

### Inside Claude (Lock Management)

```bash
# Lock a file before editing
coord lock $CLAUDE_AGENT_ID src/api/auth.py

# Lock multiple files (all or nothing)
coord lock-all $CLAUDE_AGENT_ID src/api/auth.py src/models/user.py

# Release a specific lock
coord unlock $CLAUDE_AGENT_ID src/api/auth.py

# Release all your locks
coord unlock-all $CLAUDE_AGENT_ID

# See what you have locked
coord my-locks $CLAUDE_AGENT_ID

# See all agents and locks
coord status
```

### Task Coordination (Optional)

```bash
# Add shared tasks (task-create: <id> <subject> <description>)
coord task-create task-1 "OAuth Login" "Implement OAuth login functionality"
coord task-create task-2 "Payment Integration" "Add payment integration with Stripe"

# Claim a task
coord task-claim $CLAUDE_AGENT_ID task-1

# Complete a task
coord task-complete $CLAUDE_AGENT_ID task-1

# List pending tasks
coord task-list
```

### Task Dependencies

The coordination system supports task dependencies to ensure tasks are completed in the correct order.

```bash
# Create task with dependencies (recommended)
coord task-create task-2 "User authentication" "Implement OAuth" --depends-on task-1

# Create task with multiple dependencies
coord task-create task-3 "Final integration" "Merge all features" --depends-on "task-1,task-2"

# Add dependency to existing task
coord task-add-dep task-2 task-1

# View dependencies for a task
coord task-deps task-2
# Output:
#   Task: task-2
#   Depends on (1):
#     - task-1
#   Blocks (1):
#     - task-3

# Remove a dependency
coord task-remove-dep task-2 task-1

# View all blocked tasks (pending but waiting on dependencies)
coord task-blocked

# List all tasks (available + blocked)
coord task-list --all
```

**Key Features:**
- **Automatic blocking**: Tasks with incomplete dependencies won't appear in `task-list` (they're not available to claim)
- **Circular dependency prevention**: System detects and prevents circular dependencies
- **Automatic unblocking**: When a task completes, tasks depending on it automatically become available
- **Multiple dependencies**: A task can depend on multiple other tasks (all must complete)

**Example Workflow:**
```bash
# Create tasks with dependencies
coord task-create task-1 "Setup database schema" "Create initial tables"
coord task-create task-2 "Add user model" "User table and ORM"
coord task-create task-3 "Implement auth" "OAuth + JWT"

# Set up dependency chain: task-3 depends on task-2, task-2 depends on task-1
coord task-add-dep task-2 task-1
coord task-add-dep task-3 task-2

# List available tasks (only task-1 will show since others are blocked)
coord task-list

# Complete task-1
coord task-claim $CLAUDE_AGENT_ID task-1
# ... do work ...
coord task-complete $CLAUDE_AGENT_ID task-1

# Now task-2 becomes available automatically
coord task-list  # Shows task-2 but not task-3
```

### Convenience Commands

The coordination system provides several convenience commands to streamline common workflows:

**Task Discovery:**
```bash
# Search tasks by prefix
coord task-search test-med-      # Finds all tasks starting with "test-med-"

# Filter tasks by prefix and/or status
coord task-filter --prefix test- --status pending --limit 10
coord task-filter --status in_progress

# Get next available task for agent (auto-filters by blockedBy)
coord task-next $CLAUDE_AGENT_ID
```

**Workflow Shortcuts:**
```bash
# Claim and mark in-progress in one step
coord task-work $CLAUDE_AGENT_ID task-123

# Complete task and unlock files in one step
coord task-done $CLAUDE_AGENT_ID task-123

# Release task without completing (unclaim)
coord task-release $CLAUDE_AGENT_ID task-123
```

**Import/Export:**
```bash
# Export all tasks to JSON
coord export --output backup.json

# Import tasks from JSON
coord import tasks.json
```

**Example Workflow Using Convenience Commands:**
```bash
# Find available tasks
coord task-filter --prefix code-high- --status pending

# Claim next available task
TASK=$(coord task-next $CLAUDE_AGENT_ID | jq -r '.task_id')

# Start work (auto-claims and marks in-progress)
coord task-work $CLAUDE_AGENT_ID $TASK

# Lock files
coord lock $CLAUDE_AGENT_ID src/api/auth.py

# ... do work ...

# Complete task (auto-unlocks and marks completed)
coord task-done $CLAUDE_AGENT_ID $TASK
```

## Enforcement (Defense in Depth)

The system uses multiple Claude Code hooks for comprehensive protection:

### 1. PreToolUse Hook (Blocks unauthorized edits)
- When you try to Edit/Write a file, the hook checks if you own the lock
- If locked by someone else: **edit is blocked** with exit code 2
- If unlocked or you own it: edit proceeds normally

### 2. PostToolUse Hook (Auto-unlock on task complete)
- When you call `TaskUpdate(status="completed")`, locks are automatically released
- No need to manually unlock after finishing a task

### 3. Stop Hook (Cleanup on session end)
- When Claude session ends, all locks are released
- Agent is unregistered from the coordination system
- Prevents orphaned locks from crashed/closed sessions

### 4. TTL (Time-To-Live)
- Locks expire after 5 minutes without heartbeat
- Dead agent cleanup on every lock operation
- Catches cases where hooks don't fire (network issues, hard crashes)

## Workflow Example

```
Terminal 1 (agent-abc123)           Terminal 2 (agent-xyz789)
─────────────────────────────────────────────────────────────
Start: .claude-coord/claude-agent   Start: .claude-coord/claude-agent

"Work on OAuth feature"             "Work on payment feature"

Lock: src/api/auth.py ✓             Lock: src/api/payments.py ✓
Lock: src/models/user.py ✓          Lock: src/models/order.py ✓

Edit auth.py → allowed              Edit payments.py → allowed

                                    "I also need auth.py"
                                    Lock: src/api/auth.py ✗
                                    "FAILED - locked by agent-abc123"

                                    → Work on other files first
                                    → Come back later

Done, unlock-all

                                    Lock: src/api/auth.py ✓
                                    Now can edit it
```

## Troubleshooting

**Stale agents and locks:**
IMPORTANT: Automatic agent cleanup is DISABLED to prevent tasks from being reset when agents exit normally.
You must manually cleanup stale agents when needed.

**Manual cleanup:**
```bash
# Check for stale agents (dry-run first to see what would be cleaned)
coord cleanup-stale-agents --dry-run

# Actually cleanup stale agents (only removes agents whose processes are dead)
coord cleanup-stale-agents

# Check status to see current agents
coord status

# If an agent is truly dead and cleanup-stale-agents doesn't catch it, manually unregister
coord unregister <agent-id>
```

**What gets cleaned:**
- Agents whose process (PID) is no longer running
- Agents with no heartbeat in 5+ minutes AND dead process
- Does NOT cleanup agents with running processes (even without heartbeat)

**Hooks not working:**
Make sure `.claude/settings.local.json` has all hooks configured:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": ".claude-coord/check-lock.sh" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "TaskUpdate",
        "hooks": [
          { "type": "command", "command": ".claude-coord/auto-unlock-on-complete.sh", "async": true }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": ".claude-coord/cleanup-on-exit.sh", "async": true }
        ]
      }
    ]
  }
}
```

## Files

```
.claude-coord/
├── claude-agent              # Wrapper script to start Claude
├── claude-coord.sh           # Main coordination commands
├── check-lock.sh             # PreToolUse hook (blocks unauthorized edits)
├── auto-unlock-on-complete.sh # PostToolUse hook (releases locks on task complete)
├── cleanup-on-exit.sh        # Stop hook (releases locks on session end)
├── state.json                # Runtime state (gitignored)
├── .state.lock               # File lock for atomic ops (gitignored)
└── README.md                 # This file
```

## Task Specification System (NEW)

The coordination system now supports **detailed task specifications** beyond brief descriptions.

### Quick Reference

```bash
# View detailed task specification (acceptance criteria, code examples)
./task-spec-helpers.sh task-spec <task-id>

# Create task with detailed spec template
./task-spec-helpers.sh task-add-detailed <task-id> <subject>

# Track progress with checklists
./task-spec-helpers.sh task-progress <task-id>
./task-spec-helpers.sh task-check <task-id> <item-pattern>

# List all tasks with specs
./task-spec-helpers.sh task-list-specs
```

### Documentation

See [README-TASK-SPECS.md](./README-TASK-SPECS.md) for complete guide.

### Task Specs Directory

Detailed specifications stored in: `.claude-coord/task-specs/*.md`
