# Task: Integrate error sanitization into error classes

## Summary

class AgentError(Exception):
    def __str__(self):
        message = super().__str__()
        return sanitize_error_message(message)

def test_api_key_redacted_in_agent_error():
    error = AgentError('API key AKIAIOSFODNN7EXAMPLE failed')
    assert 'AKIAIOSFODNN7EXAMPLE' not in str(error)
    assert '[REDACTED_AWS_KEY]' in str(error)

**Priority:** CRITICAL  
**Estimated Effort:** 6.0 hours  
**Module:** Error Handling  
**Issues Addressed:** 1

---

## Files to Create

_None_

---

## Files to Modify

- `src/errors/exceptions.py` - Add sanitize_error_message to __str__ methods
- `tests/test_error_handling/test_error_propagation.py` - Add integration tests verifying secrets redacted in errors

---

## Acceptance Criteria


### Core Functionality

- [ ] All error classes call sanitize_error_message in __str__
- [ ] API keys, passwords, tokens redacted in error messages
- [ ] Secrets redacted in stack traces
- [ ] Integration tests verify no secret leakage
- [ ] Performance: <1ms sanitization overhead

### Testing

- [ ] 15+ error scenarios with secrets
- [ ] Verify all secrets redacted in error.message
- [ ] Verify secrets redacted in repr(error)
- [ ] Verify secrets redacted in traceback


---

## Implementation Details

class AgentError(Exception):
    def __str__(self):
        message = super().__str__()
        return sanitize_error_message(message)

def test_api_key_redacted_in_agent_error():
    error = AgentError('API key AKIAIOSFODNN7EXAMPLE failed')
    assert 'AKIAIOSFODNN7EXAMPLE' not in str(error)
    assert '[REDACTED_AWS_KEY]' in str(error)

---

## Test Strategy

Integrate sanitization into all error classes. Test with various secret types. Verify error messages, repr, and tracebacks.

---

## Success Metrics

- [ ] All error classes sanitize messages
- [ ] Zero secrets in error output
- [ ] Integration tests pass
- [ ] Performance overhead <1ms

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** AgentError, StageExecutionError, WorkflowExecutionError, sanitize_error_message

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#210-error-sanitization-not-integrated-severity-critical

---

## Notes

CRITICAL security issue. Secrets could leak in production error logs.
