# Coordination Daemon Quick Reference

## Daemon Management

```bash
# Start daemon (background)
.claude-coord/bin/coord-daemon start

# Start daemon (foreground, for debugging)
.claude-coord/bin/coord-daemon start --foreground

# Check status
.claude-coord/bin/coord-daemon status

# Stop daemon
.claude-coord/bin/coord-daemon stop

# Restart daemon
.claude-coord/bin/coord-daemon restart
```

## Agent Operations

```bash
# Register agent
coord-client register <agent-id> --pid $$

# Update heartbeat (optional, automatic every 60s)
coord-client heartbeat <agent-id>

# Unregister agent
coord-client unregister <agent-id>
```

## Task Operations

```bash
# Create task (validated)
coord-client task-add <task-id> "<subject>" \
  --description "<description>" \
  --priority <1-5> \
  --spec <spec-file-path>

# List available tasks
coord-client task-list --limit 10

# Get task details
coord-client task-get <task-id>

# Claim task
coord-client task-claim <agent-id> <task-id>

# Complete task
coord-client task-complete <agent-id> <task-id>
```

## File Locking

```bash
# Lock file
coord-client lock <agent-id> <file-path>

# Unlock file
coord-client unlock <agent-id> <file-path>
```

## Metrics & Observability

```bash
# Service status
coord-client status

# Velocity report
coord-client velocity --period "1 hour"

# File lock hotspots
coord-client file-hotspots --limit 10

# Task timing breakdown
coord-client task-timing <task-id>
```

## State Management

```bash
# Export to JSON
coord-client export --output state.json

# Import from JSON
coord-client import state.json
```

## Task ID Format

**Pattern:** `<prefix>-<category>-<identifier>`

**Valid Prefixes:**
- `test` - Test-related tasks
- `code` - Code changes
- `docs` - Documentation
- `gap` - Gap analysis
- `refactor` - Refactoring
- `perf` - Performance

**Valid Categories:**
- `crit` - Critical priority
- `high` - High priority
- `med` / `medi` - Medium priority
- `low` - Low priority

**Examples:**
```
test-crit-secret-detection-01
code-high-refactor-engine-02
docs-med-api-endpoints-03
gap-m3-01-track-collab-event
```

## Task Spec Requirements

Critical (priority 1) and High (priority 2) tasks **must** have spec files.

**Location:** `.claude-coord/task-specs/<task-id>.md`

**Required sections:**
```markdown
# Task Specification: <task-id>

## Problem Statement
<What needs to be done and why>

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Test Strategy
<How to verify the work>
```

## Common Errors

### "Daemon not running"
```bash
# Start the daemon
coord-daemon start
```

### "Invalid task ID"
- Use format: `<prefix>-<category>-<identifier>`
- Valid prefixes: test, code, docs, gap, refactor, perf
- Valid categories: crit, high, med/medi, low

### "Missing task spec"
- Create spec file at `.claude-coord/task-specs/<task-id>.md`
- Include: Problem Statement, Acceptance Criteria, Test Strategy

### "File locked by another agent"
- Wait for other agent to release
- Or check if agent is dead (auto-cleanup in 5 min)

### "Agent has task"
- Complete or release current task first
- Each agent can only have one in_progress task

## Background Tasks

The daemon automatically runs these tasks:

| Task | Interval | Purpose |
|------|----------|---------|
| **Dead agent cleanup** | 60s | Remove crashed agents, release locks/tasks |
| **Metrics aggregation** | 60s | Calculate velocity, hotspots, timing |
| **JSON export** | 300s | Export to state.json (backward compat) |
| **Database backup** | 3600s | Hourly backup, 7-day retention |

## Database

**Location:** `.claude-coord/coordination.db`

**Backups:** `.claude-coord/backups/coordination-YYYYMMDD-HHMMSS.db`

**Direct access:**
```bash
sqlite3 .claude-coord/coordination.db

# Example queries
SELECT * FROM agents;
SELECT * FROM tasks WHERE status='pending' LIMIT 10;
SELECT * FROM file_lock_stats ORDER BY lock_count DESC;
SELECT * FROM metrics_snapshots ORDER BY timestamp DESC LIMIT 1;
```

## Performance

| Metric | Value |
|--------|-------|
| Operation latency | <10ms |
| Max concurrent agents | 100+ |
| Memory usage | <50MB |
| Startup time | <100ms |

## Troubleshooting

### Stale PID file
```bash
rm .claude-coord/daemon.pid
coord-daemon start
```

### Database corruption
```bash
coord-daemon stop
cp .claude-coord/backups/coordination-LATEST.db .claude-coord/coordination.db
coord-daemon start
```

### Socket permission denied
```bash
# Check socket exists
ls -la /tmp/coord-*.sock

# Should be: srw------- (0600, user only)
# If not, restart daemon
coord-daemon restart
```

## Installation

```bash
# Run installation script
.claude-coord/install-daemon.sh

# Or manual installation
chmod +x .claude-coord/bin/coord-daemon
chmod +x .claude-coord/bin/coord-client
.claude-coord/bin/coord-daemon start
```

## Documentation

- **User Guide:** `.claude-coord/DAEMON_USAGE.md`
- **Technical Docs:** `.claude-coord/coord_service/README.md`
- **Summary:** `.claude-coord/COORDINATION_DAEMON_SUMMARY.md`
- **This Reference:** `.claude-coord/DAEMON_QUICK_REFERENCE.md`

## Aliases (Optional)

Add to your shell profile:

```bash
alias coord-daemon='.claude-coord/bin/coord-daemon'
alias coord='.claude-coord/bin/coord-client'

# Usage:
coord status
coord task-list
coord velocity
```
