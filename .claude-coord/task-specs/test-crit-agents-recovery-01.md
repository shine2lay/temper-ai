# Task: test-crit-agents-recovery-01 - Add Agent Error Recovery Tests

**Priority:** CRITICAL
**Effort:** 3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add comprehensive agent error recovery tests including retry, fallback, circuit breaker, and tool chaining security.

---

## Files to Create

- `tests/test_agents/test_error_recovery.py - New file for error recovery tests`

---

## Files to Modify

- None

---

## Acceptance Criteria


### Core Functionality
- [ ] Test retry with exponential backoff behavior
- [ ] Test fallback mechanism activation
- [ ] Test circuit breaker pattern integration
- [ ] Test graceful degradation
- [ ] Test tool chaining security bypass prevention
- [ ] Verify error recovery doesn't corrupt state

### Testing
- [ ] Test retry logic (3 retries with backoff)
- [ ] Test fallback to alternative agent
- [ ] Test circuit breaker opens after failures
- [ ] Test tool chaining attack prevention
- [ ] Edge case: all retries fail

### Security Controls
- [ ] Prevent tool chaining attacks (safe tools → unsafe result)
- [ ] Verify retry limits prevent DoS
- [ ] Ensure fallback doesn't bypass security

---

## Implementation Details

```python
def test_retry_with_exponential_backoff_behavior():
    """Test retry with exponential backoff"""
    agent = Agent(retry_policy="exponential", max_retries=3)
    call_times = []

    def failing_task():
        call_times.append(time.time())
        raise TemporaryError()

    with pytest.raises(MaxRetriesExceeded):
        agent.execute(failing_task)

    # Verify backoff: 1s, 2s, 4s delays
    delays = [call_times[i+1] - call_times[i] for i in range(len(call_times)-1)]
    assert delays[0] > 0.9  # ~1s
    assert delays[1] > 1.9  # ~2s
    assert delays[2] > 3.9  # ~4s

def test_tool_chaining_security_bypass_prevention():
    """Test composed tool attacks are prevented"""
    # Attack: Calculator computes ../../etc/passwd, pass to FileReader
    agent = Agent()
    with pytest.raises(SecurityViolation, match="Path traversal"):
        result = agent.execute_chain([
            {"tool": "calculator", "expr": "'../' * 2 + 'etc/passwd'"},
            {"tool": "file_reader", "path": "$prev_result"}
        ])
```

---

## Test Strategy

Test retry timing. Verify fallback logic. Test security bypass prevention in tool chains.

---

## Success Metrics

- [ ] All error recovery mechanisms tested
- [ ] Retry backoff timing verified
- [ ] Tool chaining attacks blocked
- [ ] Tests run in <5 seconds

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** Agent, RetryPolicy, CircuitBreaker, ToolChainValidator

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issues #14-15

---

## Notes

Test exponential backoff timing. Prevent tool chaining security bypasses.
