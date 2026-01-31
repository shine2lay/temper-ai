# Task: m4-02 - Safety Composition Layer

**Priority:** CRITICAL (P0 - Security)
**Effort:** 6 hours
**Status:** pending
**Owner:** unassigned

## Summary
Implement composition layer that allows multiple safety policies to be combined and executed in sequence or parallel. Supports policy priorities, short-circuit evaluation on critical violations, and aggregated violation reporting.

## Files to Create
- `src/safety/composer.py` - Policy composition logic
- `tests/safety/test_composer.py` - Composition tests

## Acceptance Criteria
- [ ] `SafetyComposer` supports adding/removing policies dynamically
- [ ] Policies execute in priority order (P0 → P1 → P2)
- [ ] Short-circuit on CRITICAL violations (stop further validation)
- [ ] Aggregated violation reports with all policy results
- [ ] Unit tests for sequential and parallel composition (>90% coverage)

## Dependencies
- Blocked by: m4-01
- Blocks: m4-04, m4-05, m4-06, m4-07
