# Task: Create test suite for Secret Detection Policy

## Summary

import pytest
from src.safety.secret_detection import SecretDetectionPolicy

class TestAWSKeyDetection:
    def test_valid_aws_key_detected(self):
        policy = SecretDetectionPolicy()
        result = policy.validate({'content': 'AKIAIOSFODNN7EXAMPLE'}, {})
        assert not result.valid
        assert 'aws_access_key' in result.violations[0].message

**Priority:** CRITICAL  
**Estimated Effort:** 8.0 hours  
**Module:** Safety  
**Issues Addressed:** 1

---

## Files to Create

- `tests/safety/test_secret_detection.py` - Comprehensive test suite for secret detection patterns and entropy calculation

---

## Files to Modify

_None_

---

## Acceptance Criteria


### Core Functionality

- [ ] AWS access key pattern detection (AKIA[0-9A-Z]{16})
- [ ] Private key detection (-----BEGIN.*PRIVATE KEY-----)
- [ ] Shannon entropy calculation (no division by zero)
- [ ] Test secret allowlist validation
- [ ] High entropy threshold enforcement (>4.5)
- [ ] Path exclusion logic (skip .git/, node_modules/)
- [ ] Multiline secret detection
- [ ] Multiple secret types in same content

### Testing

- [ ] ~50 test methods covering all secret patterns
- [ ] Edge cases: empty strings, very long strings, high entropy non-secrets
- [ ] Performance: <5ms per detection
- [ ] Coverage for secret_detection.py reaches 95%+


---

## Implementation Details

import pytest
from src.safety.secret_detection import SecretDetectionPolicy

class TestAWSKeyDetection:
    def test_valid_aws_key_detected(self):
        policy = SecretDetectionPolicy()
        result = policy.validate({'content': 'AKIAIOSFODNN7EXAMPLE'}, {})
        assert not result.valid
        assert 'aws_access_key' in result.violations[0].message

---

## Test Strategy

Use parameterized tests for different secret types. Test each pattern independently. Verify both detection and false positive rates.

---

## Success Metrics

- [ ] All AWS/private key patterns detected
- [ ] Entropy calculation returns correct values
- [ ] False positive rate <1%
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

CRITICAL security module with 0% test coverage. Must be fixed before production.
