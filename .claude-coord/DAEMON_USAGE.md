# Coordination Daemon Usage Guide

## Overview

The coordination daemon replaces the file-based coordination system with a centralized service that provides:

- **Validation**: All operations validated before execution (task naming, spec files, invariants)
- **Velocity Tracking**: Real-time metrics on task completion, file locks, agent productivity
- **Error Tracing**: Comprehensive logging with correlation IDs for debugging
- **Dead Agent Cleanup**: Automatic cleanup of crashed agents (every 60s)
- **Performance**: 10x faster operations (<10ms vs ~50ms)

## Quick Start

### 1. Start the Daemon

```bash
# Start in background
.claude-coord/bin/coord-daemon start

# Start in foreground (for debugging)
.claude-coord/bin/coord-daemon start --foreground

# Check status
.claude-coord/bin/coord-daemon status

# Stop daemon
.claude-coord/bin/coord-daemon stop
```

### 2. Migrate Existing State (Optional)

If you have an existing `state.json`:

```bash
.claude-coord/bin/coord-client import .claude-coord/state.json
```

### 3. Use the Client

All coordination commands now go through the client:

```bash
# Register agent
.claude-coord/bin/coord-client register my-agent --pid $$

# Create task (with validation)
.claude-coord/bin/coord-client task-add test-high-example-01 "Example task" \
  --description "Detailed description here" \
  --priority 2 \
  --spec .claude-coord/task-specs/test-high-example-01.md

# Claim task
.claude-coord/bin/coord-client task-claim my-agent test-high-example-01

# Lock file
.claude-coord/bin/coord-client lock my-agent src/test.py

# Unlock file
.claude-coord/bin/coord-client unlock my-agent src/test.py

# Complete task
.claude-coord/bin/coord-client task-complete my-agent test-high-example-01

# Unregister agent
.claude-coord/bin/coord-client unregister my-agent
```

## Task Creation Validation

The daemon enforces strict validation on task creation:

### Task ID Format

Task IDs must follow the pattern: `<prefix>-<category>-<identifier>`

**Valid prefixes:** test, code, docs, gap, refactor, perf
**Valid categories:** crit, high, med/medi, low

**Examples:**
- `test-crit-secret-detection-01` ✅
- `code-high-refactor-engine-02` ✅
- `docs-med-api-endpoints-03` ✅
- `MyTask` ❌ (doesn't follow convention)
- `test-invalid-01` ❌ (unknown category)

### Subject Requirements

- **Length:** 10-100 characters
- **Required:** Must not be empty

### Description Requirements

- **Critical/High priority (1-2):** Minimum 20 characters
- **Medium/Low priority (3-5):** Optional

### Task Spec Requirements

Critical and high priority tasks (priority 1-2) **must** have a spec file.

**Required sections:**
- `# Task Specification`
- `## Problem Statement`
- `## Acceptance Criteria`
- `## Test Strategy`

**Spec file location:** `.claude-coord/task-specs/<task-id>.md`

Example spec file:

```markdown
# Task Specification: test-crit-auth-bypass-01

## Problem Statement
Authentication bypass vulnerability in login flow allows unauthorized access.

## Acceptance Criteria
- [ ] Fix identified in authentication middleware
- [ ] All existing tests pass
- [ ] New regression test added
- [ ] Security audit confirms fix

## Test Strategy
1. Add unit test for bypass scenario
2. Add integration test for full login flow
3. Run security scanner to verify fix
4. Manual penetration testing
```

## Velocity Tracking

### Real-Time Metrics

```bash
# Get velocity report
.claude-coord/bin/coord-client velocity --period "1 hour"

# Output:
# Velocity Report (1 hour):
#   Completed tasks: 12
#   Avg duration: 8.5 minutes
#   Tasks/hour: 12
```

### File Lock Hotspots

```bash
# See most frequently locked files
.claude-coord/bin/coord-client file-hotspots --limit 10

# Output:
# File Lock Hotspots:
# File                                   Locks  Avg Duration  Contention
# src/core/engine.py                     42     12.5 min      8
# src/safety/rollback.py                 28     8.2 min       5
```

### Task Timing Breakdown

```bash
# Get detailed timing for a task
.claude-coord/bin/coord-client task-timing test-crit-01

# Output:
# Task Timing: test-crit-01
#   Created:     2026-01-31 10:15:30
#   Claimed:     2026-01-31 10:16:45  (wait: 1m 15s)
#   Completed:   2026-01-31 10:32:15  (total: 16m 45s)
#
#   Wait time:   1m 15s  (7%)    - Time in pending queue
#   Work time:   15m 30s (93%)   - Time from claim to completion
#   Active time: 15m 10s (91%)   - Time with files locked
#   Idle time:   20s     (2%)    - Time between locks
#
# Files worked on:
#   - src/safety/rollback.py (8m 20s, 5 edits)
#   - tests/test_safety/rollback.py (6m 15s, 4 edits)
```

## Dead Agent Cleanup

The daemon automatically cleans up dead agents every 60 seconds:

1. **Heartbeat Timeout**: Agents with no heartbeat in 5 minutes are marked stale
2. **Process Check**: Daemon verifies if the agent's process is still running
3. **Cleanup**: If process is dead:
   - All file locks released
   - Claimed tasks returned to pending
   - Agent unregistered
   - Event logged for auditing

**Manual heartbeat** (optional, for long-running operations):

```bash
# Update heartbeat manually
.claude-coord/bin/coord-client heartbeat my-agent
```

## Error Messages

The daemon provides clear, actionable error messages:

### Example: Invalid Task ID

```
Error: Task ID 'MyTask' doesn't follow naming convention
Hint: Format: <prefix>-<category>-<number> (e.g., test-crit-01)
```

### Example: Missing Task Spec

```
Error: Critical/high priority task missing spec file
Expected: .claude-coord/task-specs/test-crit-new-01.md
Hint: Create spec file with acceptance criteria, test strategy
```

### Example: File Locked

```
Error: File src/test.py is locked by agent-xyz
Hint: Wait for agent-xyz to release the lock
```

## Service Status

```bash
# Get comprehensive status
.claude-coord/bin/coord-client status

# Output:
# Status: running
# Agents: 3
# Tasks: {'pending': 15, 'in_progress': 3, 'completed': 42}
# Locks: 5
```

## State Export (Backward Compatibility)

The daemon automatically exports state to `state.json` every 5 minutes for backward compatibility.

**Manual export:**

```bash
.claude-coord/bin/coord-client export --output state.json
```

**State format** (compatible with file-based system):

```json
{
  "agents": {
    "agent-1": {
      "pid": 12345,
      "registered_at": "2026-01-31 10:00:00",
      "last_heartbeat": "2026-01-31 10:05:00"
    }
  },
  "tasks": {
    "test-high-01": {
      "subject": "Example task",
      "description": "Description",
      "priority": 2,
      "status": "pending",
      "owner": null
    }
  },
  "locks": {
    "src/test.py": [
      {
        "owner": "agent-1",
        "acquired_at": "2026-01-31 10:03:00"
      }
    ]
  }
}
```

## Database

- **Location:** `.claude-coord/coordination.db`
- **Type:** SQLite with WAL mode (better concurrency)
- **Backups:** Automatic hourly backups to `.claude-coord/backups/`
- **Retention:** Last 7 days

## Troubleshooting

### Daemon won't start

```bash
# Check if already running
.claude-coord/bin/coord-daemon status

# Check for stale PID file
rm -f .claude-coord/daemon.pid

# Try starting in foreground to see errors
.claude-coord/bin/coord-daemon start --foreground
```

### Client timeouts

```bash
# Check daemon is running
.claude-coord/bin/coord-daemon status

# Restart daemon
.claude-coord/bin/coord-daemon restart
```

### Database corruption

```bash
# Stop daemon
.claude-coord/bin/coord-daemon stop

# Restore from backup
cp .claude-coord/backups/coordination-LATEST.db .claude-coord/coordination.db

# Restart daemon
.claude-coord/bin/coord-daemon start
```

## Performance

- **Operation latency:** <10ms (vs ~50ms file-based)
- **Concurrency:** Supports 100+ concurrent agents
- **Memory:** <50MB RAM usage
- **Startup time:** <100ms

## Architecture

```
┌────────────┐  ┌────────────┐  ┌────────────┐
│  Agent 1   │  │  Agent 2   │  │  Agent 3   │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │
      └───────────────┼───────────────┘
                      ▼
              ┌───────────────────────────────┐
              │  Coordination Daemon          │
              │  (Unix Socket Server)         │
              │                               │
              │  ┌──────────────────────┐     │
              │  │ Validation Layer     │     │
              │  └──────────────────────┘     │
              │                               │
              │  ┌──────────────────────┐     │
              │  │ SQLite Database      │     │
              │  └──────────────────────┘     │
              │                               │
              │  ┌──────────────────────┐     │
              │  │ Background Tasks     │     │
              │  │ - Cleanup (60s)      │     │
              │  │ - Metrics (60s)      │     │
              │  │ - Backup (3600s)     │     │
              │  │ - Export (300s)      │     │
              │  └──────────────────────┘     │
              └───────────────────────────────┘
                      │           │
                      ▼           ▼
              coordination.db  state.json
```

## Next Steps

1. Update `claude-coord.sh` to use daemon client
2. Update session startup scripts to auto-start daemon
3. Migrate existing workflows to use validated task creation
4. Monitor velocity metrics to track productivity
