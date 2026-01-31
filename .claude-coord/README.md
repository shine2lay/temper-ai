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
.claude-coord/claude-coord.sh lock $CLAUDE_AGENT_ID src/api/auth.py

# Lock multiple files (all or nothing)
.claude-coord/claude-coord.sh lock-all $CLAUDE_AGENT_ID src/api/auth.py src/models/user.py

# Release a specific lock
.claude-coord/claude-coord.sh unlock $CLAUDE_AGENT_ID src/api/auth.py

# Release all your locks
.claude-coord/claude-coord.sh unlock-all $CLAUDE_AGENT_ID

# See what you have locked
.claude-coord/claude-coord.sh my-locks $CLAUDE_AGENT_ID

# See all agents and locks
.claude-coord/claude-coord.sh status
```

### Task Coordination (Optional)

```bash
# Add shared tasks
.claude-coord/claude-coord.sh task-add task-1 "Implement OAuth login"
.claude-coord/claude-coord.sh task-add task-2 "Add payment integration"

# Claim a task
.claude-coord/claude-coord.sh task-claim $CLAUDE_AGENT_ID task-1

# Complete a task
.claude-coord/claude-coord.sh task-complete $CLAUDE_AGENT_ID task-1

# List pending tasks
.claude-coord/claude-coord.sh task-list
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

**Stale locks from dead agents:**
The system automatically cleans up locks from agents that haven't sent a heartbeat in 5 minutes or whose PID no longer exists.

**Force cleanup:**
```bash
# Check status to see who's holding locks
.claude-coord/claude-coord.sh status

# If an agent is truly dead, manually unregister
.claude-coord/claude-coord.sh unregister <agent-id>
```

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
