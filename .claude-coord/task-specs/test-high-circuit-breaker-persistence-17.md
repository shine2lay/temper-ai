# Task: Add circuit breaker state persistence tests

## Summary

def test_circuit_breaker_state_persists_across_restart(self, redis):
    breaker1 = CircuitBreaker('llm-provider', storage=redis)
    breaker1.record_failure()  # Open circuit
    assert breaker1.state == CircuitBreakerState.OPEN
    del breaker1
    # Simulate process restart
    breaker2 = CircuitBreaker('llm-provider', storage=redis)
    assert breaker2.state == CircuitBreakerState.OPEN  # State restored

**Priority:** HIGH  
**Estimated Effort:** 6.0 hours  
**Module:** LLM  
**Issues Addressed:** 1

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_agents/test_llm_providers.py` - Add state persistence and recovery tests

---

## Acceptance Criteria


### Core Functionality

- [ ] Circuit breaker state serialization to disk/Redis
- [ ] State deserialization on process restart
- [ ] Recovery after process restart maintains OPEN state
- [ ] State migration across versions
- [ ] Multiple instances share state via Redis

### Testing

- [ ] 10+ persistence scenarios
- [ ] Test serialize → deserialize cycle
- [ ] Test process restart scenarios
- [ ] Test state migration


---

## Implementation Details

def test_circuit_breaker_state_persists_across_restart(self, redis):
    breaker1 = CircuitBreaker('llm-provider', storage=redis)
    breaker1.record_failure()  # Open circuit
    assert breaker1.state == CircuitBreakerState.OPEN
    del breaker1
    # Simulate process restart
    breaker2 = CircuitBreaker('llm-provider', storage=redis)
    assert breaker2.state == CircuitBreakerState.OPEN  # State restored

---

## Test Strategy

Use Redis for persistent storage. Test serialize/deserialize. Simulate process restart. Verify state recovery.

---

## Success Metrics

- [ ] State persists across restarts
- [ ] Serialization/deserialization works
- [ ] Multiple instances share state
- [ ] State migration tested

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** CircuitBreaker, Redis, PersistentStorage

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#37-circuit-breaker-state-persistence-high

---

## Notes

Important for distributed deployments. Circuit breaker state should persist.
