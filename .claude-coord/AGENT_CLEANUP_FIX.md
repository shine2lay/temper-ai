# Agent Cleanup Issue Fix

**Date:** 2026-02-01
**Issue:** Agents being cleaned up prematurely, causing tasks to reset from in-progress to pending

## Problem Description

The coordination system was experiencing state inconsistency between consecutive `coord status` calls:

```
First call:
  Agents: 4
  Tasks: Pending: 43, In Progress: 4, Completed: 2
  Locks: 6

Second call (immediately after):
  Agents: 0
  Tasks: Pending: 47, In Progress: 0, Completed: 2  # 4 tasks reset!
  Locks: 0
```

### Root Cause

1. **Background cleanup was too aggressive**: The daemon ran automatic cleanup every 60 seconds
2. **No heartbeat mechanism**: Agents weren't sending regular heartbeats to stay alive
3. **Can't distinguish crashes from normal exits**: When an agent finished work and exited:
   - Process ended (normal)
   - After 5 minutes, cleanup detected dead process
   - Cleanup called `unregister_agent()`
   - This reset all in-progress tasks to pending (line 152-155 in database.py)

### Why This Happened

The system couldn't tell the difference between:
- An agent that **crashed** while working (should reset its tasks)
- An agent that **finished normally** but process exited (should NOT reset its tasks)

## Solution Applied

**Disabled automatic agent cleanup** to prevent premature task resets.

### Changes Made

#### 1. Disabled Background Cleanup
File: `.claude-coord/coord_service/background.py`

```python
# NOTE: Automatic dead agent cleanup DISABLED to prevent in-progress tasks from being reset
# when agents exit normally. Use 'coord cleanup-stale-agents' for manual cleanup.
#
# # Start dead agent cleanup (every 60s)
# cleanup_thread = threading.Thread(...)
# ...
```

#### 2. Added Manual Cleanup Command
File: `.claude-coord/bin/coord`

Added new command: `coord cleanup-stale-agents [--dry-run]`

#### 3. Added Operation Handler
File: `.claude-coord/coord_service/operations.py`

Added `op_cleanup_stale_agents()` method to handle manual cleanup requests.

### Usage

**Check for stale agents (dry-run):**
```bash
coord cleanup-stale-agents --dry-run
```

**Cleanup stale agents:**
```bash
coord cleanup-stale-agents
```

**What gets cleaned:**
- ✓ Agents whose process (PID) is no longer running
- ✓ Agents with no heartbeat in 5+ minutes AND dead process
- ✗ Does NOT cleanup agents with running processes (even without heartbeat)

## Trade-offs

### Pros
- ✅ Prevents tasks from being reset when agents exit normally
- ✅ Fixes the inconsistent status issue
- ✅ Simple and predictable behavior
- ✅ User has full control over cleanup

### Cons
- ⚠️ Stale agent entries will accumulate in the database
- ⚠️ Requires manual cleanup when agents crash
- ⚠️ Locks from crashed agents won't be automatically released

## Manual Cleanup Required

Run `coord cleanup-stale-agents` periodically to clean up:
- Agents that crashed
- Agents whose processes exited abnormally
- Old agent entries

**Recommended:** Run cleanup before starting new work sessions:
```bash
# Check what would be cleaned
coord cleanup-stale-agents --dry-run

# Cleanup stale agents
coord cleanup-stale-agents

# Verify clean state
coord status
```

## Testing

After the fix:
1. Daemon restarted with automatic cleanup disabled
2. Manual cleanup command tested and working
3. Documentation updated in README.md

## Alternative Solutions Considered

1. **Require regular heartbeats**: More complex, requires agents to send periodic heartbeats
2. **Increase timeout to 30 minutes**: Doesn't solve fundamental issue
3. **Track graceful exits**: Would require protocol changes and more complexity
4. **Disable cleanup entirely** ← **CHOSEN** (simplest, most predictable)

## Future Improvements

If manual cleanup becomes too burdensome, consider:
1. Adding a "graceful exit" mechanism where agents call `coord unregister` before exiting
2. Distinguishing between crashed agents (reset tasks) vs exited agents (keep tasks)
3. Adding a heartbeat mechanism for long-running operations
