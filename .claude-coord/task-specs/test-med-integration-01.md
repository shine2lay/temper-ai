# Task: test-med-integration-01 - Improve Integration Test Organization and Performance

**Priority:** MEDIUM
**Effort:** 5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Improve integration test organization by grouping by milestone, consolidating fixtures, adding documentation, optimizing performance, and adding baselines.

---

## Files to Create

- None

---

## Files to Modify

- `tests/integration/test_*.py - Reorganize by milestone`
- `tests/integration/conftest.py - Consolidate fixtures`
- `tests/integration/test_*.py - Add scenario documentation`
- `tests/integration/test_milestone1_e2e.py - Optimize slow tests`
- `tests/load/test_*.py - Add performance baselines`
- `tests/test_cache/test_*.py - Add cache performance tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Group integration tests by milestone (M1, M2, M3, M4)
- [ ] Consolidate duplicate fixtures to conftest.py
- [ ] Add scenario flow documentation to all integration tests
- [ ] Optimize slow M1 integration tests (<5 seconds)
- [ ] Tune Hypothesis max_examples for better performance
- [ ] Add load test performance baselines
- [ ] Add memory leak detection tests
- [ ] Add cache performance tests

### Testing
- [ ] Organize tests: tests/integration/m1/, m2/, m3/, m4/
- [ ] Fixtures: move to conftest.py, remove duplicates
- [ ] Documentation: docstrings explain test scenario flow
- [ ] Performance: optimize database setup, use transactions
- [ ] Hypothesis: reduce max_examples from 100 to 20
- [ ] Load tests: establish baseline, fail if >2x
- [ ] Memory: detect leaks with memory_profiler
- [ ] Cache: test hit rate, eviction, performance

### Quality Improvements
- [ ] Better organization improves maintainability
- [ ] Consolidated fixtures reduce duplication
- [ ] Documentation helps onboarding
- [ ] Performance optimization speeds up CI

---

## Implementation Details

```python
# tests/integration/conftest.py - Consolidate fixtures
@pytest.fixture
def test_database():
    """Shared test database fixture - used across all integration tests"""
    db = create_test_database()
    yield db
    db.cleanup()

@pytest.fixture
def sample_workflow():
    """Shared workflow fixture for integration tests"""
    return create_workflow_with_defaults()

# tests/integration/m1/test_compiler_observability.py
def test_m1_compiler_observability_integration():
    """Test M1 milestone: Compiler + Observability integration.

    Scenario Flow:
    1. Compile workflow from YAML config
    2. Execute workflow with observability enabled
    3. Verify execution metrics recorded in database
    4. Verify console output captured
    5. Verify performance tracking accurate

    Performance baseline: <3 seconds
    """
    start = time.time()

    # Step 1: Compile
    compiler = Compiler(config="test_workflow.yaml")
    workflow = compiler.compile()

    # Step 2: Execute with observability
    with observability_enabled():
        result = workflow.execute()

    # Step 3-5: Verify observability
    assert database.has_execution_metrics(workflow.id)
    assert console.has_output(workflow.id)
    assert abs(result.duration - (time.time() - start)) < 0.1

    assert time.time() - start < 3.0  # Performance baseline

# tests/load/test_performance_baselines.py
def test_workflow_execution_performance_baseline():
    """Establish baseline for workflow execution performance"""
    baseline = measure_baseline(execute_workflow, iterations=10)

    # Store baseline for future comparison
    store_baseline("workflow_execution", baseline)

    # Future runs check against baseline
    current = measure_performance(execute_workflow, iterations=10)
    assert current < baseline * 2

@pytest.mark.memory_profiler
def test_workflow_execution_memory_leak():
    """Test for memory leaks in workflow execution"""
    import tracemalloc
    tracemalloc.start()

    initial = tracemalloc.get_traced_memory()[0]

    # Execute workflow 100 times
    for _ in range(100):
        execute_workflow()
        gc.collect()

    final = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()

    # Memory should not grow significantly
    memory_increase = (final - initial) / 1024 / 1024  # MB
    assert memory_increase < 10, f"Potential memory leak: {memory_increase}MB increase"
```

---

## Test Strategy

Reorganize by milestone. Consolidate fixtures. Document scenarios. Optimize performance. Add baselines.

---

## Success Metrics

- [ ] Tests organized by milestone (M1, M2, M3, M4)
- [ ] Fixtures consolidated (50% reduction in duplicates)
- [ ] All tests documented with scenario flow
- [ ] M1 tests optimized (<5 seconds)
- [ ] Hypothesis max_examples tuned (20-50)
- [ ] Performance baselines established
- [ ] Memory leak detection added
- [ ] Cache performance tests added

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** All integration test modules

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 3, Medium Issues (Integration)

---

## Notes

Use pytest-benchmark for baselines. Use memory_profiler for leak detection. Use transactions for faster DB tests.
