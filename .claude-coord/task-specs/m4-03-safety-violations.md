# Task: m4-03 - Safety Violation Types & Exceptions

**Priority:** CRITICAL (P0 - Security)
**Effort:** 4 hours
**Status:** pending
**Owner:** unassigned

## Summary
Define structured exception hierarchy and violation data models for safety system. Includes violation metadata (timestamp, agent, policy, severity), violation categories, and serialization for logging/observability integration.

## Files to Create
- `src/safety/exceptions.py` - Exception hierarchy
- `src/safety/models.py` - Violation data models
- `tests/safety/test_exceptions.md` - Exception tests

## Acceptance Criteria
- [ ] `SafetyViolation` exception with metadata (agent, policy, severity, context)
- [ ] Specific exception types: `BlastRadiusViolation`, `ActionPolicyViolation`, `RateLimitViolation`
- [ ] Violation serialization to JSON for observability integration
- [ ] Clear error messages with remediation hints
- [ ] Unit tests for all exception types (>90% coverage)

## Dependencies
- Blocked by: m4-01
- Blocks: m4-04, m4-05, m4-06, m4-07, m4-12
