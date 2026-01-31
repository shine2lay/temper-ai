# Task: test-high-integration-refactor-01 - Refactor and Fix Integration Test Quality Issues

**Priority:** HIGH
**Effort:** 4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Split overly comprehensive M1 E2E test, un-skip M3 tests, standardize performance baselines, and add regression tests.

---

## Files to Create

- None

---

## Files to Modify

- `tests/integration/test_milestone1_e2e.py - Split into focused tests`
- `tests/integration/test_m3_multi_agent.py - Un-skip or document skipped tests`
- `tests/regression/test_performance_regression.py - Standardize baselines`
- `tests/regression/ - Add missing regression tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Split M1 E2E test (283 LOC) into 7 focused tests
- [ ] Un-skip 8 skipped M3 tests or document why permanently skipped
- [ ] Standardize performance baselines across all regression tests
- [ ] Add regression tests for known bugs (audit git history)
- [ ] Add consensus edge case property tests

### Testing
- [ ] M1: split into compiler, executor, observability, integration tests
- [ ] M3: review each skipped test, fix or document
- [ ] Baselines: consistent thresholds (not 10μs to 5s variation)
- [ ] Regression: add test for each fixed bug in git history
- [ ] Property tests: add for consensus edge cases

---

## Implementation Details

```python
# Before: Overly comprehensive M1 test (283 LOC)
def test_milestone1_e2e_everything():
    # Tests 7 different concerns in one test
    # Hard to debug when it fails
    ...

# After: Split into focused tests
def test_m1_compiler_yaml_to_workflow():
    """Test M1: Compiler converts YAML to executable workflow"""
    ...

def test_m1_executor_runs_workflow():
    """Test M1: Executor runs compiled workflow"""
    ...

def test_m1_observability_tracks_execution():
    """Test M1: Observability tracks workflow execution"""
    ...

# ... 4 more focused tests

# M3 skipped tests - review and fix or document
@pytest.mark.skip(reason="Requires multi-agent infrastructure")
def test_m3_parallel_consensus():
    # Review: Can we add the infrastructure or is this permanently blocked?
    ...

# Standardized performance baselines
PERFORMANCE_BASELINES = {
    "workflow_compilation": 0.1,  # 100ms
    "workflow_execution": 1.0,    # 1s
    "database_query": 0.01,       # 10ms
}

def test_workflow_compilation_performance():
    duration = measure(compile_workflow)
    assert duration < PERFORMANCE_BASELINES["workflow_compilation"] * 2

# Regression tests from git history
def test_regression_issue_123_workflow_state_corruption():
    """Regression test for issue #123: workflow state corruption

    Bug: Concurrent workflow execution corrupted shared state
    Fix: Added proper locking in commit abc123
    Test: Verify concurrent execution doesn't corrupt state
    """
    ...
```

---

## Test Strategy

Split large tests. Review skipped tests. Standardize baselines. Audit git for regressions.

---

## Success Metrics

- [ ] M1 test split into 7 focused tests
- [ ] M3 skipped tests reviewed and fixed/documented
- [ ] Performance baselines standardized
- [ ] Regression tests added for known bugs

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** M1E2E, M3MultiAgent, PerformanceBaselines

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 2, High Issues #15-19

---

## Notes

Review git history for fixed bugs. Standardize baseline thresholds.
