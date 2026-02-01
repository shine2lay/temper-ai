# Task: Mark slow tests and optimize CI performance

## Summary

# pytest.ini
[pytest]
markers =
    slow: marks tests as slow (>1s execution)

# Add to slow tests
@pytest.mark.slow
def test_track_10k_workflows_throughput(self):
    ...

**Priority:** HIGH  
**Estimated Effort:** 4.0 hours  
**Module:** Testing Infrastructure  
**Issues Addressed:** 17

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_observability/test_tracker.py` - Add @pytest.mark.slow to 10K workflow/stage/agent tests
- `tests/test_agents/test_prompt_engine.py` - Add @pytest.mark.slow to template performance tests
- `tests/test_load/test_stress.py` - Add @pytest.mark.slow to all stress tests
- `pytest.ini` - Add slow marker configuration

---

## Acceptance Criteria


### Core Functionality

- [ ] All 17 slow tests marked with @pytest.mark.slow
- [ ] pytest.ini configured with slow marker
- [ ] CI runs fast tests by default (pytest -m 'not slow')
- [ ] Nightly job runs all tests including slow

### Testing

- [ ] Fast CI runs complete in <2 minutes
- [ ] Nightly builds run all tests
- [ ] No unmarked tests >1s execution time


---

## Implementation Details

# pytest.ini
[pytest]
markers =
    slow: marks tests as slow (>1s execution)

# Add to slow tests
@pytest.mark.slow
def test_track_10k_workflows_throughput(self):
    ...

---

## Test Strategy

Identify all tests >1s. Mark with @pytest.mark.slow. Update CI config to exclude slow tests from default run.

---

## Success Metrics

- [ ] 17 slow tests marked
- [ ] CI time reduced by ~28s
- [ ] No false positives
- [ ] All slow tests run in nightly

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** pytest, CI/CD pipeline

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#31-slow-tests-not-marked-high---performance-impact

---

## Notes

Quick win for CI/CD performance. Total slow test overhead: ~28s.
