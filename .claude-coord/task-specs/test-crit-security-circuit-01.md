# Task: test-crit-security-circuit-01 - Add Circuit Breaker Full Recovery Cycle Tests

**Priority:** CRITICAL
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add comprehensive tests for circuit breaker full recovery cycles including OPEN→HALF_OPEN→CLOSED transitions.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_safety/test_circuit_breaker.py - Add recovery cycle tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test CLOSED → OPEN → HALF_OPEN → CLOSED full recovery cycle
- [ ] Test recovery under load (concurrent requests during HALF_OPEN)
- [ ] Test recovery failure (HALF_OPEN → OPEN loop)
- [ ] Test time-based vs count-based recovery strategies
- [ ] Verify state transitions are atomic

### Testing
- [ ] Test full recovery cycle with timing verification
- [ ] Test concurrent requests during HALF_OPEN state
- [ ] Test recovery failure scenarios
- [ ] Edge case: boundary conditions between states

### Security Controls
- [ ] Prevent race conditions during state transitions
- [ ] Ensure recovery timeout enforcement

---

## Implementation Details

```python
def test_circuit_breaker_full_recovery_cycle():
    """Test complete recovery: CLOSED→OPEN→HALF_OPEN→CLOSED"""
    cb = CircuitBreaker(failure_threshold=3, timeout=1.0)

    # Phase 1: Fail and open circuit
    for _ in range(3):
        cb.call(failing_function)
    assert cb.state == State.OPEN

    # Phase 2: Wait for timeout and enter HALF_OPEN
    time.sleep(1.1)
    assert cb.state == State.HALF_OPEN

    # Phase 3: Successful recovery to CLOSED
    cb.call(successful_function)
    assert cb.state == State.CLOSED

def test_recovery_under_load_concurrent_requests():
    """Test recovery with concurrent requests in HALF_OPEN"""
    cb = CircuitBreaker(failure_threshold=3, timeout=1.0)
    # ... force HALF_OPEN state ...
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(cb.call, successful_function) for _ in range(10)]
        results = [f.result() for f in futures]
    # Only first request should succeed in HALF_OPEN, rest rejected
    assert sum(r.success for r in results) == 1
```

---

## Test Strategy

Test all state transitions. Verify timing constraints. Test concurrent requests during recovery.

---

## Success Metrics

- [ ] All recovery cycles tested
- [ ] State transition timing verified within ±100ms
- [ ] Concurrent recovery handling tested
- [ ] Tests run in <3 seconds

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** CircuitBreaker, StateManager

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #5

---

## Notes

Use time.sleep() carefully - add margin for CI timing variability.
