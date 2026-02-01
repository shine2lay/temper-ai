# Task: Fix flaky timing-dependent tests

## Summary

# Before (flaky)
time.sleep(1.1)
assert breaker.state == CircuitBreakerState.HALF_OPEN

# After (stable)
from freezegun import freeze_time
initial_time = datetime.now()
with freeze_time(initial_time + timedelta(seconds=61)):
    assert breaker.state == CircuitBreakerState.HALF_OPEN

**Priority:** HIGH  
**Estimated Effort:** 12.0 hours  
**Module:** Testing Infrastructure  
**Issues Addressed:** 12

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_agents/test_prompt_engine.py` - Replace time.sleep with time mocking, increase tolerance
- `tests/test_safety/test_circuit_breaker.py` - Use freezegun for time mocking
- `tests/safety/test_token_bucket.py` - Mock time for bucket refill tests
- `tests/test_async/test_concurrency.py` - Increase timing margins or use relative comparisons

---

## Acceptance Criteria


### Core Functionality

- [ ] All 12 flaky tests fixed
- [ ] No time.sleep() in test assertions
- [ ] Time mocking using freezegun or unittest.mock
- [ ] Timing assertions use 10x margins or relative comparisons

### Testing

- [ ] Run each fixed test 100 times to verify stability
- [ ] Zero failures in 100 runs
- [ ] CI passes consistently on slow runners


---

## Implementation Details

# Before (flaky)
time.sleep(1.1)
assert breaker.state == CircuitBreakerState.HALF_OPEN

# After (stable)
from freezegun import freeze_time
initial_time = datetime.now()
with freeze_time(initial_time + timedelta(seconds=61)):
    assert breaker.state == CircuitBreakerState.HALF_OPEN

---

## Test Strategy

Replace all time.sleep() with time mocking. Use freezegun or unittest.mock.patch. Increase margins for timing assertions.

---

## Success Metrics

- [ ] Zero flaky test failures
- [ ] All tests pass 100/100 runs
- [ ] CI reliability >99%

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** freezegun, unittest.mock

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#32-flaky-tests-with-timing-dependencies-high---cicd-reliability

---

## Notes

Critical for CI/CD reliability. 12 tests have random failures on slow runners.
