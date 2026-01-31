# Task: test-crit-security-owasp-02 - Add OWASP LLM Top 10 LLM04 Coverage (Model DoS)

**Priority:** CRITICAL
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add comprehensive tests for OWASP LLM04 (Model Denial of Service) including token-based DoS, regex DoS, and recursive prompt attacks.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_security/test_llm_security.py - Add LLM04 DoS attack tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test token-based DoS (million token inputs) is blocked
- [ ] Test regex DoS in input validation
- [ ] Test recursive prompt attacks are detected
- [ ] Verify rate limiting prevents DoS
- [ ] Test resource exhaustion protection

### Testing
- [ ] Test with extremely large inputs (1M+ tokens)
- [ ] Test regex catastrophic backtracking patterns
- [ ] Test recursive/nested prompt structures
- [ ] Edge case: near-limit inputs (just below threshold)

### Security Controls
- [ ] Token limit enforcement (<100k tokens)
- [ ] Regex timeout protection (<1s)
- [ ] Recursive depth limit (<10 levels)

---

## Implementation Details

```python
def test_llm04_token_based_dos_million_tokens():
    """Test million-token input is rejected"""
    huge_input = "word " * 1_000_000
    with pytest.raises(TokenLimitExceeded):
        validate_input(huge_input, max_tokens=100_000)

def test_llm04_regex_dos_in_input_validation():
    """Test regex DoS protection"""
    # Catastrophic backtracking pattern
    evil_regex = r"(a+)+$"
    evil_input = "a" * 50 + "b"
    with timeout(1.0):  # Should complete in <1s
        result = validate_with_timeout(evil_input, pattern=evil_regex)
    assert result is False  # Invalid but doesn't hang

def test_llm04_recursive_prompt_attacks():
    """Test recursive prompt detection"""
    recursive_prompt = "Repeat this: " * 100
    with pytest.raises(RecursivePromptDetected):
        validate_prompt_structure(recursive_prompt, max_depth=10)
```

---

## Test Strategy

Test extreme inputs. Verify timeouts work. Test rate limiting integration.

---

## Success Metrics

- [ ] All LLM04 attack vectors tested
- [ ] Token limit enforcement verified
- [ ] Regex DoS protection <1s timeout
- [ ] Tests run in <3 seconds total

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** InputValidator, RateLimiter, TokenCounter

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #4 (LLM04)

---

## Notes

Use pytest timeout fixture. Test near-limit inputs to avoid false positives.
