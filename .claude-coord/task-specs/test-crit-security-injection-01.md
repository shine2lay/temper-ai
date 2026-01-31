# Task: test-crit-security-injection-01 - Expand SQL Injection Pattern Coverage

**Priority:** CRITICAL
**Effort:** 1.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Expand SQL injection test coverage to include 20+ comprehensive attack patterns from OWASP.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_security/test_config_injection.py - Expand SQL injection patterns`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test all OWASP SQL injection categories
- [ ] Verify SQL injection attacks are BLOCKED (not just detected)
- [ ] Test union-based, boolean-based, time-based, error-based injection
- [ ] Test second-order SQL injection
- [ ] Test 20+ SQL injection patterns

### Testing
- [ ] Test classic injection ('; DROP TABLE)
- [ ] Test union-based injection
- [ ] Test blind SQL injection
- [ ] Test stored procedure injection
- [ ] Edge case: encoded SQL injection

### Security Controls
- [ ] Verify parameterized queries prevent injection
- [ ] Test input sanitization blocks all patterns
- [ ] Ensure error messages don't leak SQL structure

---

## Implementation Details

```python
SQL_INJECTION_PATTERNS = [
    "'; DROP TABLE users;--",
    "' OR '1'='1",
    "' UNION SELECT * FROM passwords--",
    "'; EXEC xp_cmdshell('calc')--",
    "' AND 1=1--",
    "' AND 1=2--",
    "admin'--",
    "' OR 1=1#",
    "1' ORDER BY 10--",
    "' UNION ALL SELECT NULL--",
    # ... 10+ more patterns
]

def test_sql_injection_comprehensive_patterns():
    """Test all SQL injection patterns are blocked"""
    for pattern in SQL_INJECTION_PATTERNS:
        with pytest.raises(SQLInjectionBlocked):
            execute_query_with_input(pattern)

def test_sql_injection_blocking_not_just_detection():
    """Verify attacks are BLOCKED, not just logged"""
    malicious_input = "'; DROP TABLE users;--"
    with pytest.raises(SecurityViolation):
        result = execute_query(f"SELECT * FROM users WHERE name='{malicious_input}'")
    # Verify table still exists
    assert table_exists("users")
```

---

## Test Strategy

Test comprehensive OWASP pattern library. Verify blocking, not just detection. Test with real database.

---

## Success Metrics

- [ ] All 20+ SQL injection patterns tested
- [ ] 100% blocking rate (no false negatives)
- [ ] Error messages don't leak SQL structure
- [ ] Tests run in <1 second

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** InputSanitizer, QueryBuilder

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #7

---

## Notes

Use OWASP SQL injection cheat sheet. Test with parameterized queries.
