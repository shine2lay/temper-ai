# Task: test-high-security-flaky-01 - Fix Flaky Time-Dependent Circuit Breaker Tests

**Priority:** HIGH
**Effort:** 1.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Fix flaky time-dependent tests by replacing fixed sleep times with polling/retry and adding timeout multipliers for slow CI systems.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_safety/test_circuit_breaker.py - Fix flaky time-dependent tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Replace fixed sleep times with polling/retry
- [ ] Add timeout multipliers for slow CI systems
- [ ] Use pytest-timeout for safety
- [ ] Make tests deterministic (remove timing dependencies)

### Testing
- [ ] Polling: wait_until(condition, timeout) instead of sleep(fixed)
- [ ] Multipliers: use CI_TIMEOUT_MULTIPLIER env var
- [ ] Timeout: add pytest.mark.timeout to prevent hangs
- [ ] Determinism: mock time.time() where possible

---

## Implementation Details

```python
import os

# Get timeout multiplier for CI (default 1.0 for local)
CI_TIMEOUT_MULTIPLIER = float(os.getenv("CI_TIMEOUT_MULTIPLIER", "1.0"))

def wait_until(condition, timeout=5.0, interval=0.1):
    """Poll until condition is true or timeout"""
    timeout = timeout * CI_TIMEOUT_MULTIPLIER
    start = time.time()
    while time.time() - start < timeout:
        if condition():
            return True
        time.sleep(interval)
    return False

# Before: Flaky test with fixed sleep
def test_circuit_breaker_recovery_flaky():
    cb = CircuitBreaker(timeout=1.0)
    # ... trigger failures ...
    time.sleep(1.1)  # Fixed sleep - flaky on slow CI
    assert cb.state == State.HALF_OPEN

# After: Robust test with polling
@pytest.mark.timeout(10)
def test_circuit_breaker_recovery_robust():
    cb = CircuitBreaker(timeout=1.0)
    # ... trigger failures ...

    # Poll until state changes (or timeout)
    assert wait_until(
        lambda: cb.state == State.HALF_OPEN,
        timeout=2.0  # Will be 2.0 * CI_TIMEOUT_MULTIPLIER
    ), f"Circuit breaker didn't transition to HALF_OPEN, state: {cb.state}"
```

---

## Test Strategy

Use polling instead of fixed sleeps. Add timeout multipliers. Add safety timeouts.

---

## Success Metrics

- [ ] All fixed sleeps replaced with polling
- [ ] CI timeout multiplier supported
- [ ] Zero flaky test failures in 100 runs

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** CircuitBreaker

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 2, High Issue #10

---

## Notes

Use wait_until helper. Set CI_TIMEOUT_MULTIPLIER=2.0 on slow CI systems.
