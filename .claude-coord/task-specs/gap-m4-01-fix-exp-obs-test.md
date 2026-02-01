# Task: gap-m4-01-fix-exp-obs-test - Fix experimentation observability integration test failure

**Priority:** MEDIUM (P2 - Nice to have, non-blocking)
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

The test `test_end_to_end_experiment_workflow` in `test_observability_integration.py` is failing because it expects to collect 20 experiment metrics from tracked workflow executions, but collects 0. This indicates that either workflow executions are not being tracked with experiment metadata correctly, or the ExperimentMetricsCollector cannot find/extract the tracked workflows.

**Impact:** Cannot verify that experimentation system integrates correctly with observability tracking. Core M4 functionality works, but E2E integration is unverified.

---

## Files to Create

_None_ - Debugging and fixing existing integration

---

## Files to Modify

**Likely files (TBD after investigation):**
- `src/experimentation/metrics_collector.py` - May need to fix query logic for finding workflow executions
- `src/observability/tracker.py` - May need to ensure experiment metadata is stored correctly
- `tests/test_experimentation/test_observability_integration.py` - May need to fix test setup or expectations

---

## Acceptance Criteria

### Investigation
- [ ] Run failing test with debug output enabled
- [ ] Identify root cause: workflow tracking issue OR collector query issue
- [ ] Verify that workflows ARE being created in database (check WorkflowExecution table)
- [ ] Verify that experiment metadata is stored in extra_metadata field
- [ ] Verify that ExperimentMetricsCollector query matches the stored data structure

### Core Functionality
- [ ] Workflows tracked with experiment metadata are queryable
- [ ] ExperimentMetricsCollector.collect_assignments() finds all 20 workflows
- [ ] Assignment metadata extracted correctly (experiment_id, variant_id, etc.)
- [ ] Custom metrics extracted from extra_metadata field
- [ ] Test passes with expected metrics count (20 assignments)

### Testing
- [ ] test_end_to_end_experiment_workflow passes
- [ ] test_track_workflow_with_experiment_metadata still passes (regression check)
- [ ] test_multiple_experiments_isolation still passes (regression check)
- [ ] No new test failures introduced

### Code Quality
- [ ] Fix is minimal and targeted (no over-engineering)
- [ ] Clear comments explaining the fix
- [ ] No breaking changes to existing code

---

## Implementation Details

### Problem Analysis

**Test Expectation:**
1. Track 20 workflow executions with experiment metadata
2. Each workflow has `experiment_id`, `variant_id`, `assignment_strategy`, `custom_metrics` in extra_metadata
3. ExperimentMetricsCollector.collect_assignments(experiment.id) should return 20 assignments
4. **Actual result:** Returns 0 assignments

**Potential Root Causes:**

**Hypothesis 1: Workflow tracking not storing experiment metadata**
- Issue: `tracker.track_workflow()` may not be storing experiment_id/variant_id in extra_metadata
- Check: Query WorkflowExecution table directly to see if metadata is present
- Fix: Ensure ExecutionTracker stores all experiment parameters in extra_metadata

**Hypothesis 2: Collector query not finding workflows**
- Issue: ExperimentMetricsCollector.collect_assignments() may have incorrect query
- Check: SQL query filters may not match the actual data structure
- Fix: Update query to correctly filter by experiment_id in extra_metadata

**Hypothesis 3: Database session isolation issue**
- Issue: Test uses in-memory database, may have session/transaction isolation problems
- Check: Verify that data committed before collector reads
- Fix: Ensure proper session management and commits

### Investigation Steps

**Step 1: Enable debug output and run test**
```bash
python -m pytest tests/test_experimentation/test_observability_integration.py::TestObservabilityIntegration::test_end_to_end_experiment_workflow -v -s
```

**Look for debug output:**
```
DEBUG: Completed: X, With metrics: Y
DEBUG: Status: ..., Metrics: ...
DEBUG: Variant IDs in assignments: ...
DEBUG: Result sample_size: ...
```

**Step 2: Direct database query**
```python
# Add to test after workflow tracking:
with get_session() as session:
    from src.observability.models import WorkflowExecution
    workflows = session.query(WorkflowExecution).filter(
        WorkflowExecution.extra_metadata.contains({"experiment_id": experiment.id})
    ).all()
    print(f"DEBUG: Found {len(workflows)} workflows in DB")
    if workflows:
        print(f"DEBUG: First workflow metadata: {workflows[0].extra_metadata}")
```

**Step 3: Check ExecutionTracker.track_workflow() implementation**
```python
# In src/observability/tracker.py
# Verify that experiment_id, variant_id, etc. are passed to backend
# Check if extra_metadata is correctly assembled
```

**Step 4: Check ExperimentMetricsCollector.collect_assignments() implementation**
```python
# In src/experimentation/metrics_collector.py
# Verify query logic for filtering by experiment_id
# Check if JSON query syntax is correct for SQLite/PostgreSQL
```

### Likely Fix Scenarios

**Scenario A: Missing metadata in track_workflow()**

```python
# In ExecutionTracker.track_workflow()
# Ensure all experiment parameters are captured in metadata dict
metadata = {
    "experiment_id": experiment_id,
    "variant_id": variant_id,
    "assignment_strategy": assignment_strategy,
    "assignment_context": assignment_context,
    "custom_metrics": custom_metrics,
    # ... other metadata
}
```

**Scenario B: Incorrect collector query**

```python
# In ExperimentMetricsCollector.collect_assignments()
# Fix JSON query syntax for filtering extra_metadata
# SQLite uses JSON functions differently than PostgreSQL

# Current (may be wrong):
workflows = session.query(WorkflowExecution).filter(
    WorkflowExecution.extra_metadata["experiment_id"] == experiment_id
).all()

# Fixed (for SQLite):
from sqlalchemy import func
workflows = session.query(WorkflowExecution).filter(
    func.json_extract(WorkflowExecution.extra_metadata, "$.experiment_id") == experiment_id
).all()

# OR use contains for dict matching:
workflows = session.query(WorkflowExecution).filter(
    WorkflowExecution.extra_metadata.contains({"experiment_id": experiment_id})
).all()
```

**Scenario C: Session/transaction isolation**

```python
# Ensure workflows are committed before collector reads
with tracker.track_workflow(...) as workflow_id:
    pass  # Work done here

# Need explicit commit or session close
# May need to use get_session() consistently
```

---

## Test Strategy

### Debug Workflow

**Step 1: Add extensive logging to failing test**
```python
def test_end_to_end_experiment_workflow(...):
    # After tracking all workflows
    print(f"\n=== AFTER TRACKING ===")
    with get_session() as session:
        from src.observability.models import WorkflowExecution
        all_workflows = session.query(WorkflowExecution).all()
        print(f"Total workflows in DB: {len(all_workflows)}")
        for wf in all_workflows[:3]:  # Show first 3
            print(f"  - ID: {wf.id}, extra_metadata: {wf.extra_metadata}")

    # Before collection
    print(f"\n=== BEFORE COLLECTION ===")
    with get_session() as session:
        collector = ExperimentMetricsCollector(session=session)
        assignments = collector.collect_assignments(experiment.id)
        print(f"Collected assignments: {len(assignments)}")
```

**Step 2: Run test and analyze output**
```bash
pytest tests/test_experimentation/test_observability_integration.py::TestObservabilityIntegration::test_end_to_end_experiment_workflow -v -s 2>&1 | tee debug.log
```

**Step 3: Based on output, identify issue:**
- If `Total workflows in DB: 0` → tracking not working
- If `Total workflows in DB: 20` but `extra_metadata: None` → metadata not stored
- If `Total workflows in DB: 20` with metadata but `Collected assignments: 0` → query issue

### Verification Tests

**After fix, verify:**
```bash
# Run the specific failing test
pytest tests/test_experimentation/test_observability_integration.py::TestObservabilityIntegration::test_end_to_end_experiment_workflow -v

# Run all observability integration tests
pytest tests/test_experimentation/test_observability_integration.py -v

# Run all experimentation tests (regression check)
pytest tests/test_experimentation/ -v
```

**Expected output:**
```
test_track_workflow_with_experiment_metadata PASSED
test_end_to_end_experiment_workflow PASSED
test_multiple_experiments_isolation PASSED

======================== 3 passed in X.XXs ========================
```

---

## Success Metrics

- [ ] test_end_to_end_experiment_workflow passes
- [ ] Collects exactly 20 assignments (not 0)
- [ ] All 3 observability integration tests pass
- [ ] No regressions in experimentation test suite (125/126 → 126/126)
- [ ] M4 test coverage: 100% (was 99.7%)
- [ ] Fix is minimal (<50 lines changed)

---

## Dependencies

- **Blocked by:** _None_ (can start immediately)
- **Blocks:** _None_ (nice-to-have fix, non-blocking)
- **Integrates with:**
  - src/observability/tracker.py (workflow tracking)
  - src/observability/backends/sql_backend.py (database storage)
  - src/experimentation/metrics_collector.py (metrics collection)
  - tests/test_experimentation/test_observability_integration.py (failing test)

---

## Design References

- Gap Analysis Report: `.claude-coord/reports/milestone-gaps-20260130-173000.md` (line 200)
- Failing Test: `tests/test_experimentation/test_observability_integration.py:130` (test_end_to_end_experiment_workflow)
- ExecutionTracker: `src/observability/tracker.py` (track_workflow method)
- MetricsCollector: `src/experimentation/metrics_collector.py` (collect_assignments method)
- M4 Specification: Milestone 4.8 - A/B Testing Framework integration with observability

---

## Notes

**Why This is P2 (Medium Priority):**
- M4 is 99.7% complete (363/364 tests passing)
- Core experimentation functionality works perfectly
- This is an INTEGRATION test failure, not a core functionality issue
- Non-blocking for production deployment

**Investigation-First Approach:**
This task requires investigation before implementing a fix. The effort estimate (2-3 hours) includes:
- 1 hour investigation and debugging
- 30 minutes implementing the fix
- 30 minutes testing and verification
- 30 minutes buffer for unexpected issues

**Likely Root Cause (Prediction):**
Based on the test code using `tracker.track_workflow()` with experiment parameters, the most likely issue is that the ExperimentMetricsCollector query doesn't correctly filter JSON metadata fields in SQLite. SQLite requires specific JSON functions (`json_extract()`) that differ from PostgreSQL's native JSON operators.

**Alternative: Test May Be Wrong:**
It's possible the test expectations are incorrect and need to be updated to match the actual implementation. The debug output will clarify whether this is the case.

**Quick Win:**
Once root cause is identified, the fix should be straightforward - either a small query adjustment or a metadata storage fix. This is a good task for improving M4 completeness from 99.7% to 100%.
