# Task: gap-m3-04-fix-quality-tests - Fix 9 failing quality gates unit tests (location mismatch)

**Priority:** HIGH (P1 - Milestone completion)
**Effort:** 1-2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

9 out of 12 quality gates unit tests are failing due to location mismatch - tests call `self.compiler._validate_quality_gates()` on `LangGraphCompiler` instance, but the method is actually in `ParallelStageExecutor`. Need to add the method to `LangGraphCompiler` as a delegation wrapper to make tests pass.

**Impact:** Cannot verify quality gates work correctly, M3 test coverage at 82% instead of 90%+.

---

## Files to Create

_None_ - Modifying existing files

---

## Files to Modify

- `src/compiler/langgraph_compiler.py` - Add `_validate_quality_gates()` method that delegates to ParallelStageExecutor
- `tests/test_compiler/test_quality_gates.py` - Update 3 placeholder integration tests (optional, for completeness)

---

## Acceptance Criteria

### Core Functionality
- [ ] Add `_validate_quality_gates()` method to `LangGraphCompiler` class
- [ ] Method signature matches executor version: `(synthesis_result, stage_config, stage_name) -> Tuple[bool, List[str]]`
- [ ] Method delegates to `self.executors['parallel']._validate_quality_gates()`
- [ ] Pass empty state dict `{}` for the state parameter (backward compatibility)
- [ ] Method is private (`_validate_quality_gates`) to match test expectations
- [ ] Return tuple: (passed: bool, violations: List[str])

### Testing
- [ ] All 9 failing unit tests now pass:
  - test_quality_gates_disabled
  - test_quality_gates_confidence_pass
  - test_quality_gates_confidence_fail
  - test_quality_gates_findings_pass
  - test_quality_gates_findings_fail
  - test_quality_gates_citations_pass
  - test_quality_gates_citations_fail
  - test_quality_gates_multiple_violations
  - test_quality_gates_default_config
- [ ] Verify test count: 12/12 tests passing (was 3/12)
- [ ] No new test failures introduced
- [ ] Run full test suite to verify no regressions

### Code Quality
- [ ] Add docstring explaining delegation pattern
- [ ] Type hints for parameters and return value
- [ ] Consistent with other delegation methods in LangGraphCompiler
- [ ] No breaking changes to existing code

---

## Implementation Details

### Problem Analysis

**Current Situation:**
- Method location: `src/compiler/executors/parallel.py:520` (`ParallelStageExecutor._validate_quality_gates()`)
- Test expectation: `src/compiler/langgraph_compiler.py` (`LangGraphCompiler._validate_quality_gates()`)
- Tests setup: `self.compiler = LangGraphCompiler(config_loader=Mock())`
- Tests call: `self.compiler._validate_quality_gates(synthesis_result, stage_config, "test_stage")`
- Result: **AttributeError** - method doesn't exist on LangGraphCompiler

**Why Delegation?**
- Backwards compatibility with tests
- Clear API surface on main compiler class
- Avoids duplicating quality gate logic
- Follows existing pattern (LangGraphCompiler delegates to specialized components)

### Proposed Solution

**Add to LangGraphCompiler (after `compile()` method, ~line 160):**

```python
def _validate_quality_gates(
    self,
    synthesis_result: Any,
    stage_config: Dict[str, Any],
    stage_name: str
) -> tuple[bool, list[str]]:
    """Validate synthesis result against quality gates.

    Delegates to ParallelStageExecutor for actual validation logic.
    This method exists for backwards compatibility with tests and
    provides a convenient API on the main compiler class.

    Args:
        synthesis_result: SynthesisResult from agent synthesis
        stage_config: Stage configuration dict with quality_gates settings
        stage_name: Name of the stage being validated

    Returns:
        Tuple of (passed: bool, violations: List[str])
            - passed: True if all quality gates passed
            - violations: List of violation messages (empty if passed)

    Example:
        >>> result = SynthesisResult(decision="A", confidence=0.9, ...)
        >>> config = {"quality_gates": {"enabled": True, "min_confidence": 0.7}}
        >>> passed, violations = compiler._validate_quality_gates(result, config, "research")
        >>> assert passed is True
        >>> assert violations == []
    """
    # Delegate to ParallelStageExecutor which has the validation logic
    # Pass empty state dict for backward compatibility (state not used in validation)
    return self.executors['parallel']._validate_quality_gates(
        synthesis_result=synthesis_result,
        stage_config=stage_config,
        stage_name=stage_name,
        state={}  # Empty state for testing/backward compatibility
    )
```

**Import Requirements:**

```python
from typing import Dict, Any, Optional, Tuple, List  # Add Tuple, List if not already imported
```

### Alternative Solution (Not Recommended)

**Option B: Update Tests to Use Executor Directly**

Change tests from:
```python
def setup_method(self):
    self.compiler = LangGraphCompiler(config_loader=Mock())

passed, violations = self.compiler._validate_quality_gates(...)
```

To:
```python
def setup_method(self):
    self.executor = ParallelStageExecutor()

passed, violations = self.executor._validate_quality_gates(..., state={})
```

**Why Not Recommended:**
- Requires changing 9 test methods (more work)
- Breaks existing test structure
- Less intuitive API (quality gates are a compiler-level concern)
- Reduces encapsulation (tests shouldn't know about executor internals)

---

## Test Strategy

### Verification Steps

**Step 1: Run Quality Gates Tests**
```bash
python -m pytest tests/test_compiler/test_quality_gates.py -v
```

**Expected Output:**
```
test_quality_gates_disabled PASSED
test_quality_gates_confidence_pass PASSED
test_quality_gates_confidence_fail PASSED
test_quality_gates_findings_pass PASSED
test_quality_gates_findings_fail PASSED
test_quality_gates_citations_pass PASSED
test_quality_gates_citations_fail PASSED
test_quality_gates_multiple_violations PASSED
test_quality_gates_default_config PASSED
test_quality_gate_escalate_action PASSED (or SKIPPED)
test_quality_gate_proceed_with_warning_action PASSED (or SKIPPED)
test_quality_gate_observability_tracking PASSED (or SKIPPED)

======================== 12 passed in X.XXs ========================
```

**Step 2: Run Full Test Suite**
```bash
python -m pytest tests/ -v --tb=short
```

**Step 3: Verify No Regressions**
- Check that test count increases by 9 (from 3/12 to 12/12)
- No new failures in other test files
- M3 test coverage improves from 82% to 90%+

### Edge Cases to Verify

- [ ] Quality gates disabled (should always pass)
- [ ] Missing quality_gates key in stage_config (should use defaults)
- [ ] Empty violations list when passing
- [ ] Multiple violations collected correctly
- [ ] Confidence threshold exact boundary (0.7 vs 0.69999)

---

## Success Metrics

- [ ] 12/12 quality gates tests passing (was 3/12)
- [ ] No new test failures in test suite
- [ ] M3 test coverage: 90%+ (was 82%)
- [ ] Test execution time: <5 seconds for quality_gates suite
- [ ] Zero breaking changes to existing code
- [ ] Code review approved

---

## Dependencies

- **Blocked by:** _None_ (can start immediately)
- **Blocks:** gap-m3-05-enable-e2e-tests (may need quality gates for E2E tests)
- **Integrates with:**
  - src/compiler/executors/parallel.py (delegation target)
  - src/compiler/langgraph_compiler.py (add delegation method)
  - tests/test_compiler/test_quality_gates.py (tests that will pass)

---

## Design References

- Gap Analysis Report: `.claude-coord/reports/milestone-gaps-20260130-173000.md` (line 142)
- Failing Tests: `tests/test_compiler/test_quality_gates.py` (9 failing tests)
- Actual Implementation: `src/compiler/executors/parallel.py:520-570` (_validate_quality_gates method)
- LangGraphCompiler Pattern: Delegates to specialized components (StateManager, NodeBuilder, StageCompiler)
- M3 Specification: Milestone 3.12 - Quality gates and confidence thresholds

---

## Notes

**Why This Issue Exists:**
During M3 development, quality gate validation logic was correctly implemented in `ParallelStageExecutor` (where it's actually used during workflow execution). However, the tests were written expecting the method to exist on `LangGraphCompiler` (the main API surface). This is a reasonable test expectation since quality gates are a compiler-level concept, not an executor-level detail.

**Fix Strategy:**
Add a simple delegation method to `LangGraphCompiler` that forwards to the executor. This is the minimal change that:
1. Makes tests pass with zero test changes
2. Provides better API encapsulation
3. Follows existing delegation patterns in the compiler
4. Takes <1 hour to implement

**Integration Test TODOs (Lower Priority):**
The file has 3 placeholder integration tests:
- `test_quality_gate_escalate_action` (line 285)
- `test_quality_gate_proceed_with_warning_action` (line 291)
- `test_quality_gate_observability_tracking` (line 297)

These are marked as "pass" (placeholders) and could be filled in later for comprehensive coverage. They're not blocking since the core validation logic is tested in the 9 unit tests.

**Performance Note:**
The delegation adds negligible overhead (<1ms per call) since it's a simple method forwarding. The actual validation logic in ParallelStageExecutor is already optimized.
