# Database Corruption Bug Fix

**Date:** 2026-02-01
**Status:** FIXED
**Severity:** CRITICAL

## Problem

Tasks were getting corrupted with `completed_at` timestamps set but `status` remaining as "pending" or "in_progress". This caused:

1. **Completed count stuck** - Even though tasks were finished, they weren't counted as completed
2. **Pending count inflating** - Corrupted tasks stayed in "pending" status forever
3. **Invisible work** - Agents were working but their progress wasn't tracked
4. **Metrics broken** - Velocity and completion tracking showed incorrect data

## Root Cause

**Location:** `.claude-coord/coord_service/database.py`

**Bug in `complete_task()` method (lines 237-253):**

```python
def complete_task(self, task_id: str, agent_id: str):
    """Mark task as completed."""
    with self.transaction() as conn:
        conn.execute(  # ❌ NO rowcount check!
            """
            UPDATE tasks
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND owner = ?
            """,
            (task_id, agent_id)
        )

        # This runs even if above UPDATE failed
        conn.execute(
            "UPDATE task_timing SET completed_at = CURRENT_TIMESTAMP WHERE task_id = ?",
            (task_id,)
        )
```

**What went wrong:**

1. First UPDATE has `WHERE id = ? AND owner = ?`
2. If task has `owner = NULL` or wrong owner, UPDATE affects **0 rows**
3. SQLite silently succeeds (no error raised)
4. Second UPDATE runs unconditionally, sets `completed_at`
5. Transaction commits successfully
6. **Result:** Task has `completed_at` but status is still "pending"

**Same bug in `claim_task()` method (lines 219-235)**

## Impact

**Corruption found:**
- **15 tasks corrupted** with completed_at but wrong status
- Most had `owner = NULL` (released when agents disconnected)
- Happened during multi-agent workload with daemon restarts

**Affected operations:**
- Task completion tracking
- Agent progress metrics
- Velocity calculations
- Status reporting

## Fix

**Added rowcount verification:**

```python
def complete_task(self, task_id: str, agent_id: str):
    """Mark task as completed."""
    with self.transaction() as conn:
        cursor = conn.execute(  # ✅ Capture cursor
            """
            UPDATE tasks
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND owner = ?
            """,
            (task_id, agent_id)
        )

        # ✅ Verify UPDATE succeeded
        if cursor.rowcount == 0:
            raise ValueError(
                f"Cannot complete task {task_id}: either task doesn't exist, "
                f"is not owned by agent {agent_id}, or is already completed"
            )

        # Only runs if first UPDATE succeeded
        conn.execute(
            "UPDATE task_timing SET completed_at = CURRENT_TIMESTAMP WHERE task_id = ?",
            (task_id,)
        )
```

**Same fix applied to `claim_task()`**

## Verification

**Data cleanup:**
```bash
# Fixed 15 corrupted tasks
sqlite3 .claude-coord/coordination.db "UPDATE tasks SET status = 'completed' WHERE completed_at IS NOT NULL AND status <> 'completed';"
```

**Regression tests created:**
- `test_cannot_complete_task_without_owner()`
- `test_cannot_complete_task_with_wrong_owner()`
- `test_cannot_claim_already_claimed_task()`
- `test_no_corruption_on_failed_complete()`

**Monitoring:**
```bash
# Check for corruption
sqlite3 .claude-coord/coordination.db "SELECT COUNT(*) FROM tasks WHERE completed_at IS NOT NULL AND status <> 'completed';"
# Should always return: 0
```

## Prevention

1. **Atomic state changes** - Always verify UPDATE rowcount before proceeding
2. **Fail fast** - Raise errors on unexpected state (0 rows affected)
3. **Transaction integrity** - Either all updates succeed or transaction rolls back
4. **Regression tests** - Tests added to prevent reintroduction

## Files Changed

- `.claude-coord/coord_service/database.py` - Fixed `complete_task()` and `claim_task()`
- `.claude-coord/coord_service/tests/test_corruption_fix.py` - Regression tests

## Deployment

1. Daemon automatically restarted with fix
2. All corrupted data cleaned
3. No new corruption detected
4. System operating normally

## Related Issues

This bug likely caused:
- Apparent task "leaks" where tasks seemed to disappear
- Inaccurate completion metrics
- Agent frustration when work wasn't credited
- Stale task counts in status reports
