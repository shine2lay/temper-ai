# Change Record: Fix Experiment Observability Integration Test

**Change ID:** 0005
**Date:** 2026-01-30
**Task:** gap-m4-01-fix-exp-obs-test
**Priority:** P2 (High - Milestone completion)
**Author:** Claude Sonnet 4.5

## Summary

Fixed failing test `test_end_to_end_experiment_workflow` in experimentation observability integration tests. The test was incorrectly assuming hash-based variant assignment would produce a perfect 50/50 split, but hash assignment is probabilistic and resulted in an 11/9 split. Adjusted the experiment configuration to use a lower `min_sample_size_per_variant` that accounts for this natural imbalance.

## Root Cause Analysis

### Investigation Process

1. **Initial symptom**: Test failed with `assert result["sample_size"] == 20` but got 0
2. **First hypothesis**: Assignments were being filtered out incorrectly
3. **Debug investigation**: Added extensive debug output to both test and analyzer
4. **Key finding**: All 20 assignments passed the filter, but analyzer returned "Insufficient sample size"
5. **Root cause discovered**: Hash assignment produced 11 treatment / 9 control split, but experiment required minimum 10 per variant

### Debug Output Evidence

```
DEBUG ANALYZER: Variant assignments: [('var-treatment', 11), ('var-control', 9)]
DEBUG ANALYZER: Min samples required: 10
  var-treatment: count=11, passes=True
  var-control: count=9, passes=False
DEBUG ANALYZER: FAILING due to insufficient sample size
```

### Why This Happened

**Hash assignment behavior:**
- Deterministic: Same `workflow_execution_id` always gets same variant
- Probabilistic distribution: Uses hash function to distribute across variants
- NOT guaranteed balanced: With 20 executions, can produce splits like 11/9, 12/8, etc.
- Expected range with 50/50 allocation: roughly 8-12 per variant for N=20

**Test assumption (incorrect):**
- Assumed hash assignment would give exactly 10 control + 10 treatment
- Set `min_sample_size_per_variant=10` expecting perfect balance
- Failed when natural variance produced 9/11 split

## Changes Made

### Files Modified

**tests/test_experimentation/test_observability_integration.py (line 70)**
- Changed: `min_sample_size_per_variant=10` → `min_sample_size_per_variant=8`
- Reason: Accounts for natural variance in hash-based assignment with N=20
- With 20 workflows and 50/50 allocation, expecting ~8-12 per variant is reasonable

### Debug Output Cleanup

Removed temporary debug output from:
- `src/experimentation/analyzer.py` (lines 63-89)
- `tests/test_experimentation/test_observability_integration.py` (lines 181-189, 204-226)

## Why This Fix Is Correct

**Statistical reasoning:**
- With N=20 and p=0.5 (50/50 allocation), binomial distribution gives:
  - Mean: 10 per variant
  - Standard deviation: √(20 × 0.5 × 0.5) = 2.24
  - 95% confidence interval: ~6-14 per variant
  - Setting min=8 allows for 1 standard deviation of variance

**Testing goals:**
- Test validates end-to-end integration, not assignment balance
- Focus: Verify observability tracking → metrics collection → statistical analysis
- Assignment balance is already tested in `test_assignment.py`
- Using min=8 still validates analyzer works correctly while being realistic

**Production implications:**
- In real experiments, much larger sample sizes (N=1000+) are used
- With larger N, variance decreases (law of large numbers)
- For N=1000, min_sample_size_per_variant=450 would be reasonable (allowing ~10% variance)

## Testing Performed

### Unit Test Results
```bash
venv/bin/pytest tests/test_experimentation/ -v
126 passed, 3 warnings in 1.11s
```

All experimentation tests pass, including:
- `test_end_to_end_experiment_workflow` (the fixed test)
- All analyzer tests (18 tests)
- All assignment tests (19 tests)
- All metrics collector tests (15 tests)
- All integration tests (8 tests)
- All sequential testing tests (25 tests)
- All observability integration tests (9 tests)

### Specific Test Verified
- `test_end_to_end_experiment_workflow`: Now passes consistently
- Workflow: 20 executions → hash assignment → ~9-11 per variant → analyzer runs successfully
- Validates: Complete integration from tracking to analysis

## Impact

**Positive:**
- ✅ Removes P2 blocking issue for M4 completion
- ✅ Test now reflects realistic assignment behavior
- ✅ More robust to natural variance in hash assignment
- ✅ Better aligns test configuration with statistical reality

**Risks:**
- ⚠️ None - This is a test-only change
- ⚠️ Fix makes test MORE robust, not less
- ⚠️ Production code unchanged (analyzer and assignment logic correct)

**Code Quality:**
- Removed debug output (cleaner code)
- More realistic test configuration
- Better documentation of hash assignment behavior

## Acceptance Criteria Met

- [x] test_end_to_end_experiment_workflow passes consistently
- [x] All 126 experimentation tests pass
- [x] Root cause identified and documented
- [x] Fix is minimal and correct
- [x] Debug output cleaned up
- [x] No production code changes required

## Lessons Learned

**Hash assignment characteristics:**
1. Deterministic but not balanced for small N
2. Balance improves with larger N (law of large numbers)
3. For N=20, expect ±2 variance from perfect 50/50

**Test design principles:**
1. Don't assume perfect balance with probabilistic assignment
2. Configure test thresholds to account for natural variance
3. Test integration paths, not implementation details
4. Separate assignment balance tests from integration tests

**Debugging approach that worked:**
1. Add debug output at filter boundary (before/after)
2. Trace data through each processing step
3. Compare expected vs actual at each stage
4. Found issue was downstream of suspected location

## References

- Task Spec: `.claude-coord/task-specs/gap-m4-01-fix-exp-obs-test.md`
- Gap Analysis: `.claude-coord/reports/milestone-gaps-20260130-173000.md` (M4 section)
- Test File: `tests/test_experimentation/test_observability_integration.py`
- Analyzer: `src/experimentation/analyzer.py`
- Assignment Tests: `tests/test_experimentation/test_assignment.py` (validates hash distribution)

## Deployment Notes

**Safe to Deploy:**
- Test-only change
- No production code modified
- More robust test configuration
- All tests passing

**Post-Deployment Verification:**
Run experimentation tests to confirm:
```bash
pytest tests/test_experimentation/ -v
# Should see: 126 passed
```

**No Rollback Needed:**
- Test fix only
- If test fails in future, investigate assignment distribution
- May need to further adjust min_sample_size_per_variant based on observed variance
