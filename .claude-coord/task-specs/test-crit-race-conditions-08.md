# Task: Fix race condition test assertions

## Summary

# Before (accepts race conditions)
assert final_value <= 10

# After (expects correctness)
with db.session(isolation_level='SERIALIZABLE'):
    assert final_value == 10

**Priority:** CRITICAL  
**Estimated Effort:** 4.0 hours  
**Module:** Async  
**Issues Addressed:** 2

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_async/test_concurrency.py` - Change <= assertions to == with proper DB transaction isolation
- `tests/test_tools/test_executor.py` - Add concurrent rate limiter tests with 10+ threads

---

## Acceptance Criteria


### Core Functionality

- [ ] Race condition tests use SERIALIZABLE isolation level
- [ ] Assertions expect exact counts (== not <=)
- [ ] Concurrent rate limiter tested with 10+ threads
- [ ] Proper database locking verified
- [ ] Thread-safe token bucket operations

### Testing

- [ ] Run tests 100 times to verify determinism
- [ ] All runs produce exact expected counts
- [ ] Zero race condition failures
- [ ] Database integrity maintained under concurrency


---

## Implementation Details

# Before (accepts race conditions)
assert final_value <= 10

# After (expects correctness)
with db.session(isolation_level='SERIALIZABLE'):
    assert final_value == 10

---

## Test Strategy

Use SERIALIZABLE transactions. Add concurrent execution tests. Verify exact counts with proper locking.

---

## Success Metrics

- [ ] All race condition tests expect exactness
- [ ] 100/100 runs pass with exact counts
- [ ] Concurrent rate limiter tests added
- [ ] No race conditions detected

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** Database, RateLimiter, TokenBucket

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#27-race-condition-tests-accept-failures-severity-critical

---

## Notes

CRITICAL: Tests currently accept race conditions as passing. Must enforce correctness.
