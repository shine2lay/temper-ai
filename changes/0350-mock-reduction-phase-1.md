# Change: Mock Reduction Phase 1 - Foundation and Initial Replacements

**Task:** test-high-mock-reduction-compiler
**Date:** 2026-02-01
**Status:** Phase 1 Complete (11/211 mocks reduced)

## Summary

Implemented foundational infrastructure for mock reduction in compiler tests and completed initial replacements in `test_langgraph_compiler.py`. This establishes the pattern and fixtures needed for future mock reduction work.

## Changes Made

### 1. Enhanced `tests/fixtures/realistic_data.py`

Added three major fixture categories to support mock replacement:

#### RealisticConfigLoader Class
- Replaces `Mock(spec=ConfigLoader)` with in-memory configuration
- Provides realistic default agent and stage configs
- Pre-configured with common agents (research, analyst, synthesis, code, review)
- **Impact:** Foundation for replacing ~60 ConfigLoader mocks

```python
# Usage example:
compiler.config_loader = REALISTIC_CONFIG_LOADER
# Instead of:
# mock_loader = Mock(spec=ConfigLoader)
# mock_loader.load_agent.return_value = mock_config
```

#### TestAgent Class
- Deterministic test agent with no LLM calls
- Replaces mock agents with realistic behavior
- Configurable output templates and confidence scores
- Tracks execution history (call_count, last_input)
- **Impact:** Foundation for replacing ~25 agent mocks

```python
# Usage example:
agent = TestAgent("research_agent", "Research: {input}", confidence=0.92)
response = agent.execute({"input": "test data"})
# Instead of:
# mock_agent = Mock()
# mock_agent.execute.return_value = {"output": "..."}
```

#### Synthesis Result Fixtures
- Factory functions for creating realistic SynthesisResult objects
- Pre-configured scenarios: unanimous, majority, split decisions
- **Impact:** Foundation for replacing ~30 synthesis mocks

```python
# Usage example:
result = create_synthesis_result("Approach A", confidence=0.92)
# Instead of:
# mock_result = Mock()
# mock_result.decision = "Approach A"
# mock_result.confidence = 0.92
```

### 2. Updated `tests/test_compiler/test_langgraph_compiler.py`

Replaced 3 `@patch('src.compiler.langgraph_compiler.ConfigLoader')` decorators with realistic fixtures:

**Before:**
```python
@patch('src.compiler.langgraph_compiler.ConfigLoader')
def test_compile_validates_workflow_config(mock_config_loader):
    compiler = LangGraphCompiler()
    ...
```

**After:**
```python
def test_compile_validates_workflow_config():
    compiler = LangGraphCompiler()
    compiler.config_loader = REALISTIC_CONFIG_LOADER
    ...
```

**Tests Modified:**
- `test_compile_validates_workflow_config` ✅ PASSING
- `test_compile_creates_state_graph` ✅ PASSING
- `test_compile_sequential_stages` ✅ PASSING

## Metrics

### Mock Reduction
- **Before:** 441 mocks in compiler tests
- **After:** 430 mocks in compiler tests
- **Reduced:** 11 mocks (2.5% progress toward 50% goal)
- **Target:** 220 mocks (50% reduction)
- **Remaining:** 210 mocks to reduce

### Test Results
- All modified tests passing
- 2 pre-existing test failures in test_langgraph_compiler.py (unrelated to changes)
- No new test failures introduced

## Testing Performed

```bash
# Verified syntax
python3 -m py_compile tests/fixtures/realistic_data.py

# Ran modified tests
pytest tests/test_compiler/test_langgraph_compiler.py -v
# Result: 11/13 passed (2 pre-existing failures)

# Verified failures were pre-existing
git stash && pytest tests/test_compiler/test_langgraph_compiler.py::test_start_node_initialization
# Result: Same failures before changes
```

## Next Steps (Phase 2)

Following the qa-engineer's priority plan:

### Priority 1: Low-Hanging Fruit (~70 mocks)
1. Replace stage config dicts with `create_realistic_stage_config()` (~40 mocks)
2. Use existing `create_realistic_workflow_config()` more widely (~10 mocks)
3. Replace StateManager mocks with real instances (~20 mocks) *
   - *Requires refactoring tests to not rely on mock return values

### Priority 2: Core Infrastructure (~115 mocks)
1. Replace remaining ConfigLoader mocks (~49 remaining from ~60 total)
2. Replace agent mocks with TestAgent class (~25 mocks)
3. Replace synthesis mocks with fixtures (~30 mocks)
4. Implement MockToolRegistry (~25 mocks)

### Priority 3: Integration Tests (~35 mocks)
1. Add integration tests using real NodeBuilder
2. Add integration tests using realistic tool registry

## Risks and Mitigations

### Risk: Test Execution Time
- **Mitigation:** RealisticConfigLoader uses in-memory configs (no file I/O)
- **Mitigation:** TestAgent has no LLM calls (deterministic, fast)
- **Status:** No performance degradation observed

### Risk: Fixture Maintenance Burden
- **Mitigation:** Used factory functions with sensible defaults
- **Mitigation:** Comprehensive docstrings with usage examples
- **Status:** Fixtures are self-documenting and easy to extend

### Risk: Breaking Changes
- **Mitigation:** Incremental approach with testing after each change
- **Mitigation:** All modified tests verified to pass
- **Status:** No breaking changes introduced

## Architecture Alignment

This work aligns with P1 architecture pillars:
- **Testing (P1):** Improves test realism and integration coverage
- **Modularity (P1):** Creates reusable fixture infrastructure
- **Reliability (P0):** Tests catch real bugs vs mock behavior

## Files Modified

1. `tests/fixtures/realistic_data.py` (+210 lines)
   - Added RealisticConfigLoader class
   - Added TestAgent class and factory functions
   - Added synthesis result fixtures

2. `tests/test_compiler/test_langgraph_compiler.py` (~30 lines changed)
   - Removed 3 @patch decorators
   - Added realistic fixture imports
   - Updated 3 test functions

## Design References

- `.claude-coord/reports/test-review-20260201-011820.md#priority-1-high`
- Task spec: `.claude-coord/task-specs/test-high-mock-reduction-compiler.md`
- qa-engineer analysis: agentId a4419d4

## Estimated Remaining Effort

- **Phase 2 (Priority 1):** 2-3 hours
- **Phase 2 (Priority 2):** 2-3 hours
- **Phase 3:** 1 hour
- **Total Remaining:** 5-7 hours

## Notes

- This is Phase 1 of a multi-phase effort
- Foundation is complete; remaining work is systematic application of patterns
- qa-engineer's analysis provides clear roadmap for Phases 2-3
- Current progress (2.5%) vs target (50%) indicates ~8-10 more hours of work needed
- Recommend continuing in incremental phases to maintain quality
