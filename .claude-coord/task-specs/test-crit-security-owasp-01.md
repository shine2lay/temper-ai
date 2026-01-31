# Task: test-crit-security-owasp-01 - Add OWASP LLM Top 10 LLM02 Coverage (Insecure Output Handling)

**Priority:** CRITICAL
**Effort:** 2.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add comprehensive tests for OWASP LLM02 (Insecure Output Handling) including XSS, HTML injection, and output encoding validation.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_security/test_llm_security.py - Add LLM02 attack vector tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test HTML injection in sanitized LLM output is blocked
- [ ] Test JavaScript execution prevention in output
- [ ] Test output encoding validation (HTML entities)
- [ ] Test XSS in markdown-formatted output
- [ ] Verify script tags are escaped or removed

### Testing
- [ ] Test all OWASP LLM02 attack vectors
- [ ] Test with malicious prompts designed to inject HTML/JS
- [ ] Edge case: nested script tags
- [ ] Edge case: encoded malicious payloads

### Security Controls
- [ ] Verify output sanitization blocks XSS
- [ ] Ensure HTML encoding for all untrusted output
- [ ] Validate CSP headers prevent inline scripts

---

## Implementation Details

```python
def test_llm02_html_injection_in_sanitized_output():
    """Test HTML injection is blocked"""
    malicious_output = "<script>alert('XSS')</script>Hello"
    sanitized = sanitize_llm_output(malicious_output)
    assert "<script>" not in sanitized
    assert "alert" not in sanitized
    assert "Hello" in sanitized

def test_llm02_javascript_execution_prevention():
    """Test JS execution is prevented"""
    payloads = [
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(1)>",
        "javascript:alert(1)"
    ]
    for payload in payloads:
        sanitized = sanitize_llm_output(payload)
        assert "javascript:" not in sanitized.lower()
        assert "onerror" not in sanitized.lower()
        assert "onload" not in sanitized.lower()
```

---

## Test Strategy

Test comprehensive XSS payloads. Verify sanitization blocks all attack vectors. Test encoding validation.

---

## Success Metrics

- [ ] All OWASP LLM02 attack vectors tested
- [ ] XSS prevention coverage >95%
- [ ] Zero false negatives on common XSS payloads
- [ ] Tests run in <500ms

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** OutputSanitizer, LLMOutputHandler

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #4 (LLM02)

---

## Notes

Use OWASP XSS cheat sheet for comprehensive payload coverage.
