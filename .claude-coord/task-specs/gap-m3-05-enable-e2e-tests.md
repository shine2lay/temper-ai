# Task: gap-m3-05-enable-e2e-tests - Enable 11 skipped E2E integration tests in test_m3_multi_agent.py

**Priority:** HIGH (P1 - Milestone completion)
**Effort:** 8-12 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

11 integration tests in `test_m3_multi_agent.py` are skipped due to missing methods in `LangGraphCompiler` and potentially missing strategy registry imports. Tests expect methods like `_get_agent_mode()` and `_execute_parallel_stage()` that don't exist. Need to either: (1) add delegation wrapper methods to LangGraphCompiler, or (2) update tests to use current executor-based architecture.

**Impact:** Cannot verify M3 multi-agent collaboration works end-to-end, test coverage at 82% instead of target 95%+.

---

## Files to Create

_None_ - Modifying existing files

---

## Files to Modify

**Option A (Recommended): Add Delegation Wrappers**
- `src/compiler/langgraph_compiler.py` - Add `_get_agent_mode()` and `_execute_parallel_stage()` as delegation wrappers
- `tests/integration/test_m3_multi_agent.py` - Remove skip decorators after methods are added

**Option B: Update Tests to Use New Architecture**
- `tests/integration/test_m3_multi_agent.py` - Rewrite tests to use executors directly instead of compiler methods

---

## Acceptance Criteria

### Core Functionality
- [ ] Identify which of the 11 skipped tests can be enabled
- [ ] Decide approach: add delegation wrappers (Option A) or rewrite tests (Option B)
- [ ] Implement chosen approach for all applicable tests
- [ ] 3 quality gates tests will be enabled by gap-m3-04 (dependency)
- [ ] Strategy registry tests work (verify REGISTRY_AVAILABLE import)
- [ ] Remove `@pytest.mark.skip` decorators from enabled tests

### Skipped Tests Analysis
- [ ] Line 258: `test_parallel_mode_detection` - needs `_get_agent_mode()`
- [ ] Line 279: `test_parallel_execution_with_consensus` - needs `_execute_parallel_stage()`
- [ ] Line 327: `test_partial_agent_failure` - needs `_execute_parallel_stage()`
- [ ] Line 377: `test_min_successful_agents_enforcement` - needs `_execute_parallel_stage()`
- [ ] Line 459: `TestStrategyRegistry` class - needs REGISTRY_AVAILABLE=True
- [ ] Line 622: `test_quality_gates_confidence_failure_escalate` - needs `_validate_quality_gates()` (gap-m3-04)
- [ ] Line 661: `test_quality_gates_proceed_with_warning` - needs `_validate_quality_gates()` (gap-m3-04)
- [ ] Line 697: `test_quality_gates_all_checks_pass` - needs `_validate_quality_gates()` (gap-m3-04)
- [ ] Line 492: `TestE2EWorkflows` - intentionally disabled (real LLM required)
- [ ] Line 595: `TestM3Performance` - intentionally disabled (benchmarks)

### Testing
- [ ] All enabled tests pass (8 tests enabled, 3 from gap-m3-04)
- [ ] No new test failures introduced
- [ ] Run full integration test suite to verify no regressions
- [ ] M3 test coverage improves from 82% to 95%+

### Code Quality
- [ ] Methods have comprehensive docstrings
- [ ] Type hints for all parameters and return values
- [ ] Consistent with existing delegation patterns
- [ ] No breaking changes to existing code

---

## Implementation Details

### Analysis of Skipped Tests

**Tests that need method implementations (7 tests):**

1. **test_parallel_mode_detection** (line 258)
   - Expects: `compiler._get_agent_mode(stage_config) -> str`
   - Returns: "parallel", "sequential", or default
   - Logic: Extract from `stage_config["execution"]["agent_mode"]`

2. **test_parallel_execution_with_consensus** (line 279)
   - Expects: `compiler._execute_parallel_stage(stage_config, agents, state) -> dict`
   - Delegates to: `ParallelStageExecutor.execute_stage()`
   - Returns: Agent outputs dict

3. **test_partial_agent_failure** (line 327)
   - Same as #2, tests error handling

4. **test_min_successful_agents_enforcement** (line 377)
   - Same as #2, tests min_successful_agents validation

**Tests fixed by gap-m3-04 (3 tests):**

5-7. Quality gates tests (lines 622, 661, 697)
   - Needs: `_validate_quality_gates()` (will be added by gap-m3-04)

**Tests that should work already (1 class with ~4 tests):**

8-11. **TestStrategyRegistry** class (line 459)
   - Skip condition: `not REGISTRY_AVAILABLE`
   - Strategy registry EXISTS at `src/strategies/registry.py`
   - Issue: Import might be failing, need to verify

### Proposed Solution (Option A): Add Delegation Wrappers

**Method 1: _get_agent_mode() (add to LangGraphCompiler ~line 165)**

```python
def _get_agent_mode(self, stage_config: Dict[str, Any]) -> str:
    """Get agent execution mode from stage configuration.

    Determines whether agents should execute sequentially or in parallel.
    This method exists for backwards compatibility with integration tests.

    Args:
        stage_config: Stage configuration dict with optional execution settings

    Returns:
        Agent mode: "parallel", "sequential", or default ("sequential")

    Example:
        >>> config = {"execution": {"agent_mode": "parallel"}}
        >>> mode = compiler._get_agent_mode(config)
        >>> assert mode == "parallel"
    """
    if "execution" in stage_config and "agent_mode" in stage_config["execution"]:
        return stage_config["execution"]["agent_mode"]
    return "sequential"  # Default mode
```

**Method 2: _execute_parallel_stage() (add to LangGraphCompiler ~line 180)**

```python
def _execute_parallel_stage(
    self,
    stage_config: Dict[str, Any],
    agents: Dict[str, Any],
    state: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute stage with parallel agent execution.

    Delegates to ParallelStageExecutor for actual execution.
    This method exists for backwards compatibility with integration tests.

    Args:
        stage_config: Stage configuration dict
        agents: Dict of agent_name -> agent_instance
        state: Current workflow state

    Returns:
        Dict with agent outputs and synthesis results

    Example:
        >>> result = compiler._execute_parallel_stage(config, agents, state)
        >>> assert "agent_outputs" in result
        >>> assert "synthesis" in result
    """
    # Delegate to ParallelStageExecutor
    # Note: This is a simplified wrapper for testing purposes
    # Real execution flow uses NodeBuilder and stage compilation
    stage_name = stage_config.get("name", "test_stage")
    return self.executors['parallel'].execute_stage(
        stage_name=stage_name,
        stage_config=stage_config,
        state=state,
        agents=agents
    )
```

### Fix Strategy Registry Import

**Check import in test file (line 43-48):**

```python
# Current code:
try:
    from src.strategies.registry import StrategyRegistry, get_strategy_from_config
    REGISTRY_AVAILABLE = True
except ImportError:
    REGISTRY_AVAILABLE = False
```

**Verify registry exists:**
- ✅ File exists: `src/strategies/registry.py`
- ✅ StrategyRegistry class exists
- ✅ get_strategy_from_config function exists

**Potential issues:**
- Missing `__init__.py` exports?
- Circular import?
- Need to verify actual import works

**Fix if needed:**

```python
# In src/strategies/__init__.py
from src.strategies.registry import StrategyRegistry, get_strategy_from_config

__all__ = [
    'CollaborationStrategy',
    'ConflictResolutionStrategy',
    'ConsensusStrategy',
    'DebateAndSynthesize',
    'MeritWeightedResolver',
    'StrategyRegistry',
    'get_strategy_from_config',
]
```

### Tests to Keep Skipped (Intentional)

**TestE2EWorkflows (line 492):**
- Reason: Requires real Ollama LLM
- Skip condition: `@pytest.mark.skipif(True, reason="...")`
- Action: KEEP SKIPPED (intentional, run with `pytest -m slow`)

**TestM3Performance (line 595):**
- Reason: Benchmark tests, slow
- Skip condition: `@pytest.mark.skipif(True, reason="...")`
- Action: KEEP SKIPPED (intentional, run with `pytest -m benchmark`)

---

## Test Strategy

### Phase 1: Verify Current State

**Step 1: Run all M3 integration tests**
```bash
python -m pytest tests/integration/test_m3_multi_agent.py -v --tb=short
```

**Expected output:**
- Some tests PASS
- 11 tests SKIPPED (with reasons)
- Note which tests are skipped and why

**Step 2: Verify registry import**
```bash
python -c "from src.strategies.registry import StrategyRegistry, get_strategy_from_config; print('✓ Import successful')"
```

**Expected:** Should print "✓ Import successful"

### Phase 2: Implement Fixes

**Step 1: Add _get_agent_mode() to LangGraphCompiler**
**Step 2: Add _execute_parallel_stage() to LangGraphCompiler**
**Step 3: Fix registry import if needed**
**Step 4: Wait for gap-m3-04 to complete (adds _validate_quality_gates)**

### Phase 3: Enable Tests

**Step 1: Remove skip decorators**

Remove `@pytest.mark.skip` from:
- Line 258: `test_parallel_mode_detection`
- Line 279: `test_parallel_execution_with_consensus`
- Line 327: `test_partial_agent_failure`
- Line 377: `test_min_successful_agents_enforcement`

**Step 2: Verify registry tests**

If registry import works, remove skip condition from:
- Line 459: `@pytest.mark.skipif(not REGISTRY_AVAILABLE, ...)`

**Step 3: Wait for gap-m3-04**

After gap-m3-04 completes, remove skip decorators from:
- Line 622: `test_quality_gates_confidence_failure_escalate`
- Line 661: `test_quality_gates_proceed_with_warning`
- Line 697: `test_quality_gates_all_checks_pass`

### Phase 4: Verification

**Run all tests:**
```bash
python -m pytest tests/integration/test_m3_multi_agent.py -v
```

**Expected output:**
```
TestParallelExecution::test_parallel_mode_detection PASSED
TestParallelExecution::test_parallel_execution_with_consensus PASSED
TestParallelExecution::test_partial_agent_failure PASSED
TestParallelExecution::test_min_successful_agents_enforcement PASSED
TestStrategyRegistry::test_get_consensus_strategy PASSED
TestStrategyRegistry::test_get_debate_strategy PASSED
TestStrategyRegistry::test_invalid_strategy_name PASSED
TestQualityGates::test_quality_gates_confidence_failure_escalate PASSED
TestQualityGates::test_quality_gates_proceed_with_warning PASSED
TestQualityGates::test_quality_gates_all_checks_pass PASSED
TestQualityGates::test_quality_gate_observability_tracking PASSED

======================== X passed, 2 skipped (E2E, benchmarks) ========================
```

---

## Success Metrics

- [ ] 8-11 tests enabled (depending on registry import issue)
- [ ] All enabled tests pass
- [ ] M3 test coverage: 95%+ (was 82%)
- [ ] No new test failures in test suite
- [ ] Integration test execution time: <30 seconds (excluding skipped E2E/benchmarks)
- [ ] Code review approved

---

## Dependencies

- **Blocked by:** gap-m3-04-fix-quality-tests (3 tests need _validate_quality_gates)
- **Blocks:** _None_
- **Integrates with:**
  - src/compiler/langgraph_compiler.py (add delegation methods)
  - src/compiler/executors/parallel.py (delegation target)
  - src/strategies/registry.py (verify import works)
  - tests/integration/test_m3_multi_agent.py (remove skip decorators)

---

## Design References

- Gap Analysis Report: `.claude-coord/reports/milestone-gaps-20260130-173000.md` (line 168)
- Skipped Tests: `tests/integration/test_m3_multi_agent.py` (lines 258, 279, 327, 377, 459, 622, 661, 697, 492, 595)
- Strategy Registry: `src/strategies/registry.py` (implementation exists)
- Parallel Executor: `src/compiler/executors/parallel.py` (delegation target)
- M3 Specification: Milestone 3 - Multi-Agent Collaboration features

---

## Notes

**Why Tests Are Skipped:**
The tests were written expecting certain methods to exist on `LangGraphCompiler` (the main API surface). During M3 development, the architecture evolved to use executors (ParallelStageExecutor, etc.) for specialized functionality. The tests are correct in expecting a clean API on LangGraphCompiler - we should add delegation wrappers rather than forcing tests to understand executor internals.

**Coordination with gap-m3-04:**
3 of the 11 skipped tests require `_validate_quality_gates()` which will be added by gap-m3-04. Coordinate these tasks so that:
1. gap-m3-04 adds _validate_quality_gates()
2. gap-m3-05 adds _get_agent_mode() and _execute_parallel_stage()
3. Both tasks remove skip decorators from their respective tests

**Registry Import Issue:**
If the registry import is failing (REGISTRY_AVAILABLE=False), this is likely a minor __init__.py issue. The registry implementation exists and is complete - just need to verify/fix the import path.

**E2E and Benchmark Tests:**
Lines 492 (E2E) and 595 (benchmarks) are INTENTIONALLY skipped and should remain skipped. They require:
- E2E: Real Ollama LLM running locally
- Benchmarks: Extended runtime for performance measurement

These tests can be run manually with:
```bash
pytest -m slow  # Run E2E tests
pytest -m benchmark  # Run benchmark tests
```

**Effort Breakdown:**
- Add _get_agent_mode(): 30 minutes
- Add _execute_parallel_stage(): 2-3 hours (complex delegation, may need state mapping)
- Fix registry import: 30 minutes
- Test and verify: 2-3 hours
- Remove skip decorators and validate: 1-2 hours
- Total: 8-12 hours
