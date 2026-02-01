# Task: Create test suite for Blast Radius Policy

## Summary

class TestBlastRadiusLimits:
    def test_max_files_exceeded(self):
        policy = BlastRadiusPolicy(max_files=10)
        action = {'files_modified': ['file{}.py'.format(i) for i in range(11)]}
        result = policy.validate(action, {})
        assert not result.valid
        assert 'max_files' in result.violations[0].message

**Priority:** CRITICAL  
**Estimated Effort:** 6.0 hours  
**Module:** Safety  
**Issues Addressed:** 1

---

## Files to Create

- `tests/safety/test_blast_radius.py` - Tests for blast radius limits (files, lines, entities, forbidden patterns)

---

## Files to Modify

_None_

---

## Acceptance Criteria


### Core Functionality

- [ ] Max files limit enforcement (default 10)
- [ ] Max lines per file limit (default 500)
- [ ] Max total lines limit (default 2000)
- [ ] Max entities affected (CRITICAL violations)
- [ ] Forbidden pattern detection (DROP TABLE, DELETE FROM, rm -rf)
- [ ] Combined limits exceeded scenarios

### Testing

- [ ] ~30 test methods covering all limits
- [ ] Edge cases: exactly at limit, 1 over limit, combined violations
- [ ] Performance: <1ms per validation
- [ ] Coverage for blast_radius.py reaches 95%+


---

## Implementation Details

class TestBlastRadiusLimits:
    def test_max_files_exceeded(self):
        policy = BlastRadiusPolicy(max_files=10)
        action = {'files_modified': ['file{}.py'.format(i) for i in range(11)]}
        result = policy.validate(action, {})
        assert not result.valid
        assert 'max_files' in result.violations[0].message

---

## Test Strategy

Test each limit independently, then test combined scenarios. Use parameterized tests for different limit values.

---

## Success Metrics

- [ ] All limits enforced correctly
- [ ] Forbidden patterns detected
- [ ] CRITICAL severity for entity violations
- [ ] Coverage >95%

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** SafetyPolicy, ActionPolicyEngine

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#21-zero-test-coverage-for-security-modules-severity-critical

---

## Notes

CRITICAL security module with 0% test coverage. Prevents large-scale damage.
