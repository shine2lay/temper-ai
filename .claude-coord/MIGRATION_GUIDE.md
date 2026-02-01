# Migration Guide: File-Based → Daemon Coordination

This guide covers migrating from the file-based coordination system to the centralized daemon.

## Overview

The migration is designed to be safe, gradual, and reversible:

1. **Phase 1**: Install daemon alongside file-based system
2. **Phase 2**: Test daemon with existing state
3. **Phase 3**: Migrate workflows to use daemon
4. **Phase 4**: Deprecate file-based system

**Rollback**: At any point, you can export state and revert to file-based.

## Pre-Migration Checklist

Before starting migration:

- [ ] Backup current `state.json`: `cp .claude-coord/state.json .claude-coord/state.json.backup`
- [ ] Verify Python 3 is installed: `python3 --version`
- [ ] Ensure no active agents are running
- [ ] Complete any in-progress tasks
- [ ] Review current coordination state: `.claude-coord/claude-coord.sh status`

## Phase 1: Installation

### Step 1: Install Daemon

```bash
# Run installation script
.claude-coord/install-daemon.sh
```

This will:
- Create necessary directories
- Set executable permissions
- Start daemon
- Test basic functionality

**Manual installation:**
```bash
chmod +x .claude-coord/bin/coord-daemon
chmod +x .claude-coord/bin/coord-client

# Start daemon
.claude-coord/bin/coord-daemon start

# Verify running
.claude-coord/bin/coord-daemon status
```

### Step 2: Verify Installation

```bash
# Check daemon status
.claude-coord/bin/coord-daemon status
# Expected: Daemon running (PID XXXXX)

# Test client communication
.claude-coord/bin/coord-client status
# Expected: Status: running, Agents: 0, Tasks: {...}
```

## Phase 2: State Migration

### Step 1: Import Existing State

If you have existing `state.json`:

```bash
# Import state to daemon
.claude-coord/bin/coord-client import .claude-coord/state.json
```

This imports:
- All registered agents
- All tasks (pending, in_progress, completed)
- All file locks

**Verify import:**
```bash
# Check imported data
.claude-coord/bin/coord-client status

# List tasks
.claude-coord/bin/coord-client task-list

# Compare with original
diff <(jq -S . .claude-coord/state.json) \
     <(jq -S . <(.claude-coord/bin/coord-client export --output /dev/stdout))
```

### Step 2: Validate Migration

```bash
# Export from daemon
.claude-coord/bin/coord-client export --output .claude-coord/state-from-daemon.json

# Compare with original
diff .claude-coord/state.json .claude-coord/state-from-daemon.json
```

Any differences should be:
- Timestamp updates
- Formatting differences (JSON pretty-printing)

If you see unexpected differences, **stop and investigate** before proceeding.

## Phase 3: Workflow Migration

### Option A: Gradual Migration (Recommended)

Keep both systems running during transition.

**Step 1: Create wrapper script**

```bash
# .claude-coord/coord-wrapper.sh
#!/bin/bash
# Wrapper that uses daemon if running, otherwise falls back to file-based

if .claude-coord/bin/coord-daemon status >/dev/null 2>&1; then
    # Use daemon
    .claude-coord/bin/coord-client "$@"
else
    # Fallback to file-based
    .claude-coord/claude-coord.sh "$@"
fi
```

**Step 2: Update aliases**

```bash
# Add to ~/.bashrc or ~/.zshrc
alias coord='.claude-coord/coord-wrapper.sh'
```

**Step 3: Test workflows**

```bash
# Register agent
coord register test-agent --pid $$

# Create task
coord task-add test-high-migration-01 "Test migration" \
  --description "Verify daemon works correctly" \
  --priority 2

# Claim task
coord task-claim test-agent test-high-migration-01

# Lock file
coord lock test-agent src/test.py

# Complete task
coord task-complete test-agent test-high-migration-01

# Unregister
coord unregister test-agent
```

### Option B: Full Migration

Replace file-based system entirely.

**Step 1: Backup current system**

```bash
cp .claude-coord/claude-coord.sh .claude-coord/claude-coord.sh.backup
```

**Step 2: Update claude-coord.sh**

Transform into thin daemon client wrapper:

```bash
#!/bin/bash
# claude-coord.sh - Daemon client wrapper

COORD_CLIENT="$(dirname "$0")/bin/coord-client"

# Ensure daemon is running
if ! "$(dirname "$0")/bin/coord-daemon" status >/dev/null 2>&1; then
    echo "Starting coordination daemon..." >&2
    "$(dirname "$0")/bin/coord-daemon" start
    sleep 1
fi

# Map commands to daemon operations
case "$1" in
    register)
        "$COORD_CLIENT" register "$2" --pid "${3:-$$}"
        ;;
    unregister)
        "$COORD_CLIENT" unregister "$2"
        ;;
    task-add)
        "$COORD_CLIENT" task-add "$@"
        ;;
    task-claim)
        "$COORD_CLIENT" task-claim "$@"
        ;;
    task-complete)
        "$COORD_CLIENT" task-complete "$@"
        ;;
    lock)
        "$COORD_CLIENT" lock "$@"
        ;;
    unlock)
        "$COORD_CLIENT" unlock "$@"
        ;;
    status)
        "$COORD_CLIENT" status
        ;;
    velocity)
        "$COORD_CLIENT" velocity "$@"
        ;;
    *)
        echo "Command: $1" >&2
        "$COORD_CLIENT" "$@"
        ;;
esac
```

**Step 3: Update session scripts**

Update `.claude-coord/session-start.sh`:

```bash
#!/bin/bash
# session-start.sh

# Start daemon if not running
if ! .claude-coord/bin/coord-daemon status >/dev/null 2>&1; then
    echo "Starting coordination daemon..."
    .claude-coord/bin/coord-daemon start
fi

# Continue with normal session setup
# ...
```

## Phase 4: Deprecation

Once daemon is stable (recommended: 1 week of use):

### Step 1: Archive File-Based System

```bash
# Move old implementation to archive
mkdir -p .claude-coord/archive
mv .claude-coord/claude-coord.sh.backup .claude-coord/archive/
```

### Step 2: Update Documentation

Update any documentation referencing file-based coordination:
- README files
- Developer guides
- Onboarding docs

### Step 3: Remove Fallbacks

Remove any fallback logic in scripts:
- Remove wrapper scripts
- Update aliases to use daemon directly
- Remove old state.json references

## Validation Tests

After each phase, run these tests:

### Basic Functionality

```bash
# Agent lifecycle
coord-client register test-agent --pid $$
coord-client heartbeat test-agent
coord-client unregister test-agent

# Task workflow
coord-client task-add test-low-validate-01 "Validation test" \
  --description "Test" --priority 4
coord-client task-list
coord-client task-get test-low-validate-01
coord-client register test-agent --pid $$
coord-client task-claim test-agent test-low-validate-01
coord-client task-complete test-agent test-low-validate-01

# File locking
coord-client register agent-1 --pid $$
coord-client lock agent-1 file.py
coord-client unlock agent-1 file.py
```

### Validation

```bash
# Invalid task ID (should fail)
coord-client task-add InvalidTask "Test" --priority 1
# Expected: Error about naming convention

# Missing spec (should fail for critical)
coord-client task-add test-crit-no-spec-99 "Missing spec" --priority 1
# Expected: Error about missing spec file

# Valid task
coord-client task-add test-high-validate-02 "Valid task" \
  --description "This has enough description" \
  --priority 2
# Expected: Success
```

### Performance

```bash
# Create 100 tasks (should complete in <1s)
time for i in {1..100}; do
  coord-client task-add test-low-perf-$(printf "%03d" $i) "Perf test $i" \
    --description "Performance test" --priority 4 &
done
wait
```

### Observability

```bash
# Velocity tracking
coord-client velocity --period "1 hour"

# File hotspots
coord-client file-hotspots

# Task timing
coord-client task-timing test-high-validate-02

# Service status
coord-client status
```

## Rollback Procedure

If you need to revert to file-based system:

### Step 1: Export Current State

```bash
# Export from daemon
.claude-coord/bin/coord-client export --output .claude-coord/state.json
```

### Step 2: Stop Daemon

```bash
.claude-coord/bin/coord-daemon stop
```

### Step 3: Restore File-Based System

```bash
# Restore original claude-coord.sh
cp .claude-coord/archive/claude-coord.sh.backup .claude-coord/claude-coord.sh

# Or use git
git checkout HEAD -- .claude-coord/claude-coord.sh
```

### Step 4: Verify State

```bash
# Check state.json is valid
.claude-coord/claude-coord.sh status
```

## Common Issues

### Daemon Won't Start

**Symptom:** `coord-daemon start` fails

**Solutions:**
```bash
# Check for stale PID file
rm -f .claude-coord/daemon.pid

# Check socket file
rm -f /tmp/coord-*.sock

# Run in foreground to see errors
.claude-coord/bin/coord-daemon start --foreground
```

### State Import Fails

**Symptom:** `coord-client import` fails

**Solutions:**
```bash
# Validate state.json format
jq . .claude-coord/state.json

# Check for required fields
jq 'keys' .claude-coord/state.json
# Expected: ["agents", "tasks", "locks"]

# Try fresh database
rm .claude-coord/coordination.db
.claude-coord/bin/coord-daemon restart
.claude-coord/bin/coord-client import .claude-coord/state.json
```

### Client Timeouts

**Symptom:** Commands hang or timeout

**Solutions:**
```bash
# Check daemon is running
.claude-coord/bin/coord-daemon status

# Check daemon is responsive
.claude-coord/bin/coord-client status

# Restart daemon
.claude-coord/bin/coord-daemon restart
```

### Task Validation Errors

**Symptom:** Tasks fail validation

**Solutions:**
```bash
# Check task ID format
# Valid: test-crit-01, code-high-02, docs-med-03
# Invalid: MyTask, task-wrong-01, test-invalid-category-01

# Check spec file exists (for critical/high)
ls .claude-coord/task-specs/

# Create missing spec
cat > .claude-coord/task-specs/test-high-example-01.md << 'EOF'
# Task Specification: test-high-example-01

## Problem Statement
Example task for testing.

## Acceptance Criteria
- [ ] Task completes successfully
- [ ] Validation passes

## Test Strategy
Manual testing of workflow.
EOF
```

## Performance Comparison

### Before (File-Based)

```bash
# Task creation: ~50ms
time .claude-coord/claude-coord.sh task-add test-low-before-01 "Test"

# 100 tasks: ~5-6 seconds
time for i in {1..100}; do
  .claude-coord/claude-coord.sh task-add test-low-fb-$i "Test" &
done
wait
```

### After (Daemon)

```bash
# Task creation: ~5ms
time .claude-coord/bin/coord-client task-add test-low-after-01 "Test" \
  --description "Test" --priority 4

# 100 tasks: ~0.5-1 second
time for i in {1..100}; do
  .claude-coord/bin/coord-client task-add test-low-daemon-$i "Test" \
    --description "Test" --priority 4 &
done
wait
```

**Expected improvement: 10x faster**

## Migration Timeline

**Recommended schedule:**

| Week | Phase | Activity |
|------|-------|----------|
| 1 | Install & Test | Install daemon, import state, run side-by-side |
| 2 | Gradual Migration | Use wrapper, test workflows, validate metrics |
| 3 | Full Migration | Update scripts, train team, monitor stability |
| 4 | Deprecation | Remove fallbacks, update docs, archive old system |

**Minimum timeline:** 2 weeks (install → test → migrate → validate)

## Post-Migration

After successful migration:

### Monitor Metrics

```bash
# Daily velocity check
.claude-coord/bin/coord-client velocity --period "24 hours"

# Weekly hotspot review
.claude-coord/bin/coord-client file-hotspots

# Monthly database size check
ls -lh .claude-coord/coordination.db
```

### Optimize Based on Data

```bash
# Identify slow tasks
sqlite3 .claude-coord/coordination.db \
  "SELECT task_id, work_time_seconds FROM task_timing
   ORDER BY work_time_seconds DESC LIMIT 10"

# Find hotspot files
sqlite3 .claude-coord/coordination.db \
  "SELECT file_path, lock_count, avg_lock_duration_seconds
   FROM file_lock_stats
   ORDER BY lock_count DESC LIMIT 10"
```

### Regular Maintenance

```bash
# Weekly: Check dead agent cleanups
sqlite3 .claude-coord/coordination.db \
  "SELECT * FROM event_log
   WHERE event_type='agent_cleanup'
   AND timestamp >= datetime('now', '-7 days')"

# Monthly: Review database size
du -h .claude-coord/coordination.db

# Quarterly: Archive old data
# (Automatic via background tasks, but verify)
ls -lh .claude-coord/backups/
```

## Success Criteria

Migration is successful when:

- [x] Daemon runs stably for 1+ week
- [x] All workflows use daemon
- [x] Velocity metrics show expected performance (10x faster)
- [x] Dead agent cleanup works automatically
- [x] Task validation prevents invalid tasks
- [x] No data loss incidents
- [x] Rollback procedure tested and documented
- [x] Team trained on new system

## Support

If you encounter issues:

1. Check logs: `coord-daemon start --foreground`
2. Review documentation: `.claude-coord/DAEMON_USAGE.md`
3. Verify database: `sqlite3 .claude-coord/coordination.db "PRAGMA integrity_check"`
4. Test rollback: Export state and verify file-based system works

## Summary

The migration from file-based to daemon coordination is:

- **Safe**: Gradual rollout with rollback capability
- **Validated**: Comprehensive tests at each phase
- **Monitored**: Velocity metrics track performance
- **Documented**: Complete guides and references
- **Reversible**: Export state and restore file-based system

Follow this guide step-by-step for a smooth transition to the faster, more reliable daemon-based coordination system.
