# Task: test-fix-failures-03 - Fix Integration Test Failures

**Priority:** CRITICAL
**Effort:** 2-3 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Fix 9 failing integration tests related to workflow execution, database tracking, and error propagation across stages.

---

## Files to Modify
- `tests/integration/test_database_integration.py` - Fix database integration tests
- `tests/integration/test_error_propagation.py` - Fix error propagation tests
- `tests/integration/test_workflow_execution.py` - Fix workflow execution tests

---

## Acceptance Criteria

### Core Functionality
- [ ] test_database_integration_full_workflow passes
- [ ] test_error_propagation_across_stages passes
- [ ] Workflow state persists correctly to database
- [ ] Errors in stage N propagate to stage N+1
- [ ] Stage outputs correctly passed between stages

### Testing
- [ ] All 9 integration tests pass
- [ ] Database transactions commit successfully
- [ ] Error metadata captured in workflow state

### Integration Points
- [ ] Compiler + Engine integration works
- [ ] Engine + Database integration works
- [ ] Stage transitions handled correctly
- [ ] Observability tracking captures all events

---

## Implementation Details

**Current Failures:**
- test_database_integration_full_workflow - workflow state not persisting
- test_error_propagation_across_stages - errors not propagating
- 7 additional integration tests

**Likely Issues:**
1. Database session management in tests
2. Async context issues in workflow execution
3. Stage output serialization failing
4. Error metadata not included in state

**Implementation Steps:**
1. Review database session lifecycle in tests
2. Check workflow state serialization
3. Verify stage transition logic
4. Fix error propagation mechanism
5. Ensure observability hooks fire correctly

---

## Test Strategy

```bash
# Run integration tests
pytest tests/integration/ -v --tb=long

# Run with database debugging
pytest tests/integration/test_database_integration.py -v -s

# Check for database issues
pytest tests/integration/ --log-cli-level=DEBUG
```

---

## Success Metrics
- [ ] 0/9 tests failing (100% pass rate)
- [ ] Integration test coverage >75%
- [ ] All workflow states persist correctly

---

## Dependencies
- **Blocked by:** test-fix-failures-01 (config loading)
- **Blocks:** test-integration-compiler-engine
- **Integrates with:** All integration paths

---

## Notes
- Integration tests may need database cleanup fixtures
- Check for race conditions in async execution
- Verify test database isolation
