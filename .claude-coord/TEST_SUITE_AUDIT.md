# Test Suite Audit - Critical Gaps Found

**Date:** 2026-02-01
**Auditor:** Claude Sonnet 4.5
**Trigger:** Production database corruption bug that slipped through tests

## Executive Summary

The coordination daemon test suite appeared comprehensive with 100+ tests covering:
- Database operations, transactions, concurrency
- Agent lifecycle, task workflows, file locking
- Protocol serialization, validation
- Stress testing, boundary conditions

However, a **critical database corruption bug** made it to production despite:
- ✅ Having tests for `complete_task()` and `claim_task()`
- ✅ Having tests for "wrong owner" scenarios
- ✅ Having extensive concurrency tests

**Root cause:** Tests checked observable behavior but not **operation semantics** or **data invariants**.

## The Bug That Slipped Through

**What happened:**
- `complete_task(task_id, wrong_agent_id)` silently failed (0 rows updated)
- But `completed_at` was still set in task_timing table
- Result: Task had `completed_at` but status stayed "pending"
- 15 tasks corrupted in production before detection

**Why tests didn't catch it:**

### Test: `test_complete_task_wrong_owner()` - PASSED WITH BUG ❌

```python
def test_complete_task_wrong_owner(self, db):
    """Completing task with wrong owner should not update."""
    db.create_task('test-task', 'Subject', 'Description')
    db.claim_task('test-task', 'agent1')

    db.complete_task('test-task', 'agent2')  # Wrong owner

    task = db.get_task('test-task')
    assert task['status'] == 'in_progress'  # ✅ PASSED - status unchanged
```

**What the test MISSED:**
1. ❌ Didn't check `completed_at` is still NULL
2. ❌ Didn't expect ValueError to be raised
3. ❌ Didn't verify operation semantics (should fail, not silently do nothing)
4. ❌ Didn't check database invariants

**What the test SHOULD have been:**

```python
def test_complete_task_wrong_owner(self, db):
    """Completing task with wrong owner should raise ValueError."""
    db.create_task('test-task', 'Subject', 'Description')
    db.claim_task('test-task', 'agent1')

    # Should raise error, not silently fail
    with pytest.raises(ValueError, match="Cannot complete task"):
        db.complete_task('test-task', 'agent2')

    # Verify NO partial state corruption
    task = db.get_task('test-task')
    assert task['status'] == 'in_progress'
    assert task['owner'] == 'agent1'
    assert task['completed_at'] is None  # ← CRITICAL CHECK MISSING

    # Verify database invariants
    rows = db.query(
        "SELECT * FROM tasks WHERE completed_at IS NOT NULL AND status != 'completed'"
    )
    assert len(rows) == 0  # No corrupted tasks
```

### Test: `test_claim_task_already_claimed()` - PASSED WITH BUG ❌

Same issue - checked owner didn't change but didn't:
- Expect ValueError
- Check started_at wasn't modified
- Verify no corruption

## Critical Gaps in Test Coverage

### 1. **Operation Semantics Not Tested**

**What was tested:** Observable state changes
**What was MISSED:** Whether operations succeeded or failed correctly

| Operation | Tested | Should Test |
|-----------|--------|-------------|
| complete_task(wrong_owner) | Status unchanged ✅ | Raises ValueError ❌ |
| complete_task(NULL owner) | Not tested ❌ | Raises ValueError ❌ |
| claim_task(already_claimed) | Owner unchanged ✅ | Raises ValueError ❌ |
| claim_task(completed_task) | Not tested ❌ | Raises ValueError ❌ |

**Impact:** Silent failures accepted as normal behavior

### 2. **Timestamp Integrity Not Validated**

**What was tested:** Status fields (status, owner)
**What was MISSED:** Timestamp consistency

| Scenario | Status Check | Timestamp Check |
|----------|--------------|-----------------|
| Failed complete | ✅ Still in_progress | ❌ completed_at still NULL |
| Failed claim | ✅ Owner unchanged | ❌ started_at unchanged |
| Successful complete | ✅ Status=completed | ⚠️ completed_at set (partial) |

**Impact:** Corrupted timestamps went undetected

### 3. **Database Invariants Not Verified**

**Missing invariant tests:**

```sql
-- No task should have completed_at without status='completed'
SELECT COUNT(*) FROM tasks
WHERE completed_at IS NOT NULL AND status != 'completed';
-- Should ALWAYS be 0

-- No task should have started_at without owner
SELECT COUNT(*) FROM tasks
WHERE started_at IS NOT NULL AND owner IS NULL;
-- Should ALWAYS be 0

-- No task should have status='in_progress' without owner
SELECT COUNT(*) FROM tasks
WHERE status = 'in_progress' AND owner IS NULL;
-- Should ALWAYS be 0
```

**Impact:** Partial state corruption undetected

### 4. **Rowcount Validation Not Tested**

No tests verified that SQL UPDATEs actually affected rows:

```python
# Code does this (BAD):
conn.execute("UPDATE tasks SET ... WHERE id = ? AND owner = ?", ...)
# No check if 0 rows affected!

# Tests should verify:
cursor = conn.execute(...)
assert cursor.rowcount > 0  # Verify UPDATE succeeded
```

**Impact:** Silent UPDATE failures normalized

### 5. **NULL Owner Edge Cases Not Tested**

Tasks can have `owner = NULL` when:
- Newly created (pending)
- Agent unregistered (tasks released)
- Daemon restart (agents disconnected)

**Missing tests:**
- complete_task() on task with NULL owner
- claim_task() after agent unregistered
- State after daemon restart

**Impact:** Real-world scenario (agent disconnect) caused corruption

### 6. **Concurrency Tests Don't Check Invariants**

Extensive concurrency tests exist but only check:
- No deadlocks
- No duplicate claims
- Correct final ownership

**Missing in concurrency tests:**
- Database invariants after race conditions
- Timestamp consistency under load
- No partial corruption after failed operations

### 7. **Error Handling Philosophy Missing**

Tests implicitly assumed **"silent failure is acceptable"**:
- Operations that should fail just returned without error
- Code didn't raise exceptions
- Tests didn't expect exceptions

**Should be:** **"Fail fast and loud"**
- Invalid operations MUST raise errors
- Tests MUST expect and verify errors
- Silent failures are bugs

## Comparison: Before vs After

### Before (Buggy Code + Passing Tests)

```python
# Code
def complete_task(self, task_id: str, agent_id: str):
    with self.transaction() as conn:
        conn.execute(  # No rowcount check
            "UPDATE tasks SET status='completed', completed_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND owner=?", (task_id, agent_id)
        )
        # Always runs, even if above UPDATE failed
        conn.execute(
            "UPDATE task_timing SET completed_at=CURRENT_TIMESTAMP WHERE task_id=?",
            (task_id,)
        )

# Test
def test_complete_task_wrong_owner(self, db):
    db.complete_task('test-task', 'agent2')  # No exception expected
    task = db.get_task('test-task')
    assert task['status'] == 'in_progress'  # PASSED
    # ❌ Didn't check completed_at is NULL
```

**Result:** Bug shipped, 15 tasks corrupted

### After (Fixed Code + Comprehensive Tests)

```python
# Code
def complete_task(self, task_id: str, agent_id: str):
    with self.transaction() as conn:
        cursor = conn.execute(
            "UPDATE tasks SET status='completed', completed_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND owner=?", (task_id, agent_id)
        )
        if cursor.rowcount == 0:  # ✅ Verify UPDATE succeeded
            raise ValueError(f"Cannot complete task {task_id}")
        conn.execute(...)  # Only runs if above succeeded

# Test
def test_cannot_complete_task_with_wrong_owner(self, db):
    with pytest.raises(ValueError, match="Cannot complete task"):  # ✅ Expect error
        db.complete_task('test-task', 'agent2')

    task = db.get_task('test-task')
    assert task['status'] == 'in_progress'
    assert task['completed_at'] is None  # ✅ Verify timestamp integrity

    # ✅ Verify no corruption
    rows = db.query(
        "SELECT * FROM tasks WHERE completed_at IS NOT NULL AND status != 'completed'"
    )
    assert len(rows) == 0
```

**Result:** Bug prevented, corruption impossible

## Recommended Test Improvements

### Priority 1: Critical Gaps (Add Immediately)

1. **Add invariant checks to ALL database tests**
   ```python
   def verify_no_corruption(db):
       """Assert no tasks have corrupted state."""
       rows = db.query(
           "SELECT * FROM tasks WHERE completed_at IS NOT NULL AND status != 'completed'"
       )
       assert len(rows) == 0, f"Found {len(rows)} corrupted tasks"
   ```

2. **Add error expectations for invalid operations**
   - complete_task with NULL owner → ValueError
   - complete_task with wrong owner → ValueError
   - claim_task already claimed → ValueError
   - claim_task on completed task → ValueError

3. **Add timestamp integrity checks**
   - Failed operations must not modify ANY timestamps
   - Successful operations must set correct timestamps
   - Timestamps must be consistent with status

4. **Add NULL owner test scenarios**
   - Tasks without owner
   - Tasks after agent unregister
   - Tasks after daemon restart

### Priority 2: Test Quality (Refactor Existing)

5. **Update existing "wrong owner" tests**
   - Change from "should not update" to "should raise error"
   - Add timestamp validation
   - Add corruption checks

6. **Add database invariant fixtures**
   ```python
   @pytest.fixture(autouse=True)
   def verify_invariants_after_test(db):
       yield
       # After each test, verify database invariants
       verify_no_corruption(db)
       verify_consistency(db)
   ```

7. **Add rowcount validation to transaction tests**
   - Test that UPDATEs return correct rowcount
   - Test that 0 rowcount raises error
   - Test partial UPDATE rollback

### Priority 3: Coverage Expansion

8. **Add end-to-end corruption scenarios**
   - Agent crashes mid-operation
   - Daemon restart during task completion
   - Network interruption scenarios

9. **Add chaos/fuzz testing**
   - Random operation sequences
   - Database state verification after each
   - Invariant checking throughout

10. **Add monitoring/observability tests**
    - Corruption detection
    - Alerting on invariant violations
    - Health check validation

## Lessons Learned

### 1. **Testing Behavior ≠ Testing Correctness**

Existing tests checked "what happened" but not "what should happen":
- ✅ Status didn't change
- ❌ But operation should have failed with error

### 2. **Partial Assertions Are Dangerous**

Tests that check status but not timestamps:
- Give false confidence
- Allow corruption to slip through
- Create "works on my machine" scenarios

### 3. **Silent Failures Are Bugs**

Operations that should fail MUST raise errors:
- Makes bugs obvious
- Prevents corruption
- Enables debugging

### 4. **Database Invariants Are Not Optional**

Every test should verify:
- No orphaned data
- No inconsistent state
- No corrupted relationships
- Constraints maintained

### 5. **Real-World Scenarios Matter**

Tests must cover:
- Agent disconnections
- Daemon restarts
- Race conditions
- Network failures
- Not just happy paths

## Test Coverage Metrics (Estimated)

| Category | Before | After Fix | Needed |
|----------|--------|-----------|--------|
| Database operations | 90% | 90% | - |
| Error handling | 30% | 60% | 40% |
| Invariant validation | 10% | 40% | 60% |
| Timestamp integrity | 20% | 50% | 50% |
| NULL owner scenarios | 0% | 30% | 70% |
| Rowcount validation | 0% | 40% | 60% |

**Overall quality:** 60% → 70% (need 30% more)

## Action Items

- [ ] Add invariant checks to all existing database tests
- [ ] Update "wrong owner" tests to expect ValueError
- [ ] Add timestamp integrity validation to all tests
- [ ] Create NULL owner test scenarios
- [ ] Add autouse fixture for invariant verification
- [ ] Refactor concurrency tests to check invariants
- [ ] Add chaos testing for corruption detection
- [ ] Document testing philosophy (fail fast)
- [ ] Add pre-commit hook to run corruption checks
- [ ] Set up CI invariant monitoring

## Conclusion

The test suite was **quantitatively comprehensive** (100+ tests) but **qualitatively insufficient**:
- Covered code paths ✅
- Missed correctness properties ❌
- Tested behavior ✅
- Missed semantics ❌
- Checked state ✅
- Missed invariants ❌

**Bottom line:** A test that passes with buggy code is not testing the right thing.
