# Task: Add security bypass tests (path traversal, injection, SSRF)

## Summary

@pytest.mark.parametrize('attack_path', [
    '/etc/%2e%2e/passwd',
    '/etc/%252e%252e/passwd',
    '/etc/\\u002e\\u002e/passwd',
    '/etc/passwd\\x00.txt'
])
def test_path_traversal_bypasses_blocked(attack_path):
    policy = FileAccessPolicy()
    result = policy.validate({'path': attack_path}, {})
    assert not result.valid, f'Bypass succeeded: {attack_path}'

**Priority:** CRITICAL  
**Estimated Effort:** 12.0 hours  
**Module:** Security  
**Issues Addressed:** 4

---

## Files to Create

- `tests/test_security/test_security_bypasses.py` - Advanced attack vectors and bypass techniques

---

## Files to Modify

- `tests/test_security/test_path_injection.py` - Add URL encoding, double encoding, Unicode bypasses
- `tests/test_tools/test_parameter_sanitization.py` - Add SQL injection bypass techniques (comment obfuscation, time-based)

---

## Acceptance Criteria


### Core Functionality

- [ ] Path traversal: URL encoding (%2e%2e), double encoding (%252e)
- [ ] Path traversal: Unicode (\u002e\u002e), overlong UTF-8 (%c0%ae)
- [ ] Path traversal: Null byte injection (passwd\x00.txt)
- [ ] Command injection: Whitespace variants, tab chars, newlines
- [ ] SQL injection: Comment obfuscation (' OR 1=1--)
- [ ] SQL injection: Time-based blind (WAITFOR DELAY)
- [ ] SSRF: Internal IPs (169.254.169.254, 127.0.0.1, [::1])
- [ ] SSRF: DNS rebinding attacks

### Testing

- [ ] 50+ bypass tests covering all attack vectors
- [ ] All bypass attempts blocked by policies
- [ ] Performance: <5ms per validation
- [ ] Zero false negatives on known bypasses


---

## Implementation Details

@pytest.mark.parametrize('attack_path', [
    '/etc/%2e%2e/passwd',
    '/etc/%252e%252e/passwd',
    '/etc/\\u002e\\u002e/passwd',
    '/etc/passwd\\x00.txt'
])
def test_path_traversal_bypasses_blocked(attack_path):
    policy = FileAccessPolicy()
    result = policy.validate({'path': attack_path}, {})
    assert not result.valid, f'Bypass succeeded: {attack_path}'

---

## Test Strategy

Use parameterized tests for all bypass variants. Test each encoding/obfuscation technique. Verify policies block all known bypasses.

---

## Success Metrics

- [ ] All 50+ bypass tests pass (all blocked)
- [ ] Zero false negatives
- [ ] Coverage for security policies >90%
- [ ] Performance <5ms per test

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** FileAccessPolicy, ForbiddenOperationsPolicy, ParameterSanitizer

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#26-security-bypass-tests-missing-severity-critical

---

## Notes

Essential for production security. Tests known attack bypasses that sophisticated attackers use.
