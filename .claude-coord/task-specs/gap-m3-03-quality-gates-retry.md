# Task: gap-m3-03-quality-gates-retry - Implement quality gates retry logic for stage re-execution

**Priority:** HIGH (P1 - Milestone completion)
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Quality gates `on_failure="retry_stage"` option is not implemented - currently just raises RuntimeError with "not yet fully implemented" message. Need to implement actual retry logic that re-executes failed stages up to `max_retries` times when quality gates fail (low confidence, insufficient findings, missing citations).

**Impact:** Cannot automatically retry stages that fail quality checks, reducing workflow robustness.

---

## Files to Create

_None_ - Modifying existing files

---

## Files to Modify

- `src/compiler/executors/parallel.py:277-281` - Replace stub with retry logic implementation
- `src/compiler/stage_compiler.py` - Add conditional edge for retry loop (if needed)
- `src/compiler/langgraph_state.py` - Add retry tracking fields to state (if needed)

---

## Acceptance Criteria

### Core Functionality
- [ ] Remove "not yet fully implemented" stub at parallel.py:277-281
- [ ] Implement retry counter tracking in state (retry_count per stage)
- [ ] Check retry_count against quality_gates.max_retries (default: 2)
- [ ] If retry_count < max_retries: re-execute stage, increment counter
- [ ] If retry_count >= max_retries: escalate with descriptive error
- [ ] Preserve agent outputs and metadata from previous attempts
- [ ] Track all retry attempts in observability system
- [ ] Reset retry_count on successful quality gate pass

### Retry Logic Behavior
- [ ] First failure: retry_count=0 → re-execute (attempt 2)
- [ ] Second failure: retry_count=1 → re-execute (attempt 3, if max_retries=2)
- [ ] Third failure: retry_count=2 → escalate (exhausted retries)
- [ ] Retry uses same stage config, agents, and inputs
- [ ] Each retry attempt gets fresh agent execution (no state carryover)

### State Management
- [ ] Add `stage_retry_counts` dict to LangGraphWorkflowState
- [ ] Track retry counts per stage name
- [ ] Include retry metadata in stage_outputs
- [ ] Log retry attempts with attempt number

### Observability Integration
- [ ] Track retry event: `tracker.track_quality_gate_retry(stage_id, attempt_number, violations)`
- [ ] Include violations that triggered retry in metadata
- [ ] Differentiate between retry attempts and escalation in logs
- [ ] Track timing for each retry attempt

### Testing
- [ ] Unit test: First quality gate failure triggers retry
- [ ] Unit test: Second failure (retry_count=1, max_retries=2) triggers second retry
- [ ] Unit test: Third failure (retry_count=2, max_retries=2) escalates
- [ ] Unit test: Successful retry resets counter
- [ ] Unit test: Retry preserves stage config and inputs
- [ ] Integration test: End-to-end retry with real quality gate validation
- [ ] Edge case: max_retries=0 (immediate escalation)
- [ ] Edge case: Quality gate passes on second attempt

### Code Quality
- [ ] Clear error messages indicating retry exhaustion
- [ ] Comprehensive logging for debugging retry flow
- [ ] Type hints for all new parameters and return values
- [ ] Consistent with existing error handling patterns

---

## Implementation Details

### Current Code (parallel.py:277-281)
```python
elif on_failure == "retry_stage":
    # For now, raise exception with retry hint
    raise RuntimeError(
        f"Quality gates failed for stage '{stage_name}' (retry_stage not yet fully implemented): {'; '.join(violations)}"
    )
```

### Proposed Implementation

**Step 1: Add retry tracking to state (langgraph_state.py)**
```python
class LangGraphWorkflowState(TypedDict, total=False):
    # ... existing fields ...
    stage_retry_counts: Dict[str, int]  # Track retry attempts per stage
```

**Step 2: Implement retry logic (parallel.py:277-281)**
```python
elif on_failure == "retry_stage":
    # Initialize retry tracking if needed
    if "stage_retry_counts" not in state:
        state["stage_retry_counts"] = {}

    # Get current retry count for this stage
    retry_count = state["stage_retry_counts"].get(stage_name, 0)
    max_retries = quality_gates_config.get("max_retries", 2)

    # Check if retries exhausted
    if retry_count >= max_retries:
        # Escalate after exhausting retries
        raise RuntimeError(
            f"Quality gates failed for stage '{stage_name}' after {retry_count} retries. "
            f"Violations: {'; '.join(violations)}"
        )

    # Increment retry counter
    state["stage_retry_counts"][stage_name] = retry_count + 1
    attempt_number = retry_count + 1

    # Log retry attempt
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(
        f"Quality gates failed for stage '{stage_name}', retrying "
        f"(attempt {attempt_number + 1}/{max_retries + 1}). Violations: {'; '.join(violations)}"
    )

    # Track retry in observability
    if tracker and hasattr(tracker, 'track_quality_gate_retry'):
        tracker.track_quality_gate_retry(
            stage_id=stage_execution_id,
            attempt_number=attempt_number,
            violations=violations,
            max_retries=max_retries
        )

    # Signal retry by returning special state or raising retriable exception
    # Option A: Use custom exception that LangGraph can catch and retry
    raise QualityGateRetryableError(
        stage_name=stage_name,
        violations=violations,
        attempt_number=attempt_number
    )

    # Option B: Set state flag to trigger conditional edge back to stage
    # state["retry_stage"] = stage_name
    # return state  # LangGraph conditional edge will loop back
```

**Step 3: Handle successful retry (parallel.py - after quality gate validation)**
```python
# After successful quality gate pass
if "stage_retry_counts" in state and stage_name in state["stage_retry_counts"]:
    # Quality gate passed, reset retry counter
    logger.info(f"Stage '{stage_name}' passed quality gates after {state['stage_retry_counts'][stage_name]} retries")
    del state["stage_retry_counts"][stage_name]
```

**Step 4: Add custom exception (new file or in executors/__init__.py)**
```python
class QualityGateRetryableError(Exception):
    """Raised when quality gate fails but retry is allowed."""

    def __init__(self, stage_name: str, violations: List[str], attempt_number: int):
        self.stage_name = stage_name
        self.violations = violations
        self.attempt_number = attempt_number
        super().__init__(
            f"Quality gate failed for stage '{stage_name}' (attempt {attempt_number}): {'; '.join(violations)}"
        )
```

**Alternative: LangGraph Conditional Edge Approach**

If using conditional edges instead of exceptions:

```python
# In stage_compiler.py
def should_retry_stage(state: LangGraphWorkflowState) -> str:
    """Conditional edge: retry stage or continue to next."""
    retry_stage = state.get("retry_stage")
    if retry_stage:
        # Clear retry flag and loop back to stage
        state["retry_stage"] = None
        return retry_stage  # Return stage name to retry
    return "__end__"  # Continue to next stage

# Add conditional edge after each stage
graph.add_conditional_edges(
    stage_name,
    should_retry_stage,
    {
        stage_name: stage_name,  # Loop back to retry
        "__end__": next_stage or END
    }
)
```

---

## Test Strategy

### Unit Tests (test_quality_gates.py)

**Test 1: First retry attempt**
```python
def test_quality_gate_retry_first_attempt():
    """Test that first quality gate failure triggers retry."""
    # Setup: quality_gates enabled, on_failure=retry_stage, max_retries=2
    # Mock synthesis_result with low confidence
    # Assert: retry_count incremented to 1, stage re-executed
    # Assert: No exception raised (retry instead)
```

**Test 2: Second retry attempt**
```python
def test_quality_gate_retry_second_attempt():
    """Test that second failure triggers another retry."""
    # Setup: retry_count=1, max_retries=2
    # Mock second failure
    # Assert: retry_count incremented to 2, stage re-executed
```

**Test 3: Retry exhaustion**
```python
def test_quality_gate_retry_exhaustion():
    """Test that third failure escalates after retries exhausted."""
    # Setup: retry_count=2, max_retries=2
    # Mock third failure
    # Assert: RuntimeError raised with "after 2 retries" message
```

**Test 4: Successful retry**
```python
def test_quality_gate_retry_success():
    """Test that successful retry resets counter."""
    # Setup: retry_count=1
    # Mock quality gate pass
    # Assert: retry_count removed from state
```

**Test 5: max_retries=0**
```python
def test_quality_gate_no_retries():
    """Test that max_retries=0 escalates immediately."""
    # Setup: max_retries=0
    # Mock first failure
    # Assert: Immediate escalation, no retry
```

### Integration Tests (test_m3_multi_agent.py)

**Test: End-to-end retry workflow**
```python
def test_quality_gate_retry_integration():
    """Test full retry flow in multi-agent workflow."""
    # Create workflow with quality gates enabled
    # Mock first execution to fail quality gates
    # Mock second execution to pass
    # Assert: Stage executed twice, final result is from second attempt
    # Assert: Observability tracked both attempts
```

---

## Success Metrics

- [ ] Quality gate retry logic fully implemented (no stub code)
- [ ] All unit tests pass (5+ new tests)
- [ ] Integration test verifies end-to-end retry flow
- [ ] Retry attempts tracked in observability system
- [ ] Clear error messages when retries exhausted
- [ ] Documentation updated with retry behavior
- [ ] Performance: Retry overhead <50ms per attempt

---

## Dependencies

- **Blocked by:** gap-m3-01-track-collab-event (need observability tracking method)
- **Blocks:** gap-m3-04-fix-quality-tests (tests may need retry logic to pass)
- **Integrates with:**
  - src/compiler/executors/parallel.py (main implementation)
  - src/compiler/langgraph_state.py (state schema)
  - src/observability/tracker.py (retry tracking)
  - QualityGatesConfig schema (max_retries field)

---

## Design References

- Gap Analysis Report: `.claude-coord/reports/milestone-gaps-20260130-173000.md` (M3 section, line 440-443)
- QualityGatesConfig: `src/compiler/schemas.py:366-374` (on_failure, max_retries fields)
- Current Stub: `src/compiler/executors/parallel.py:277-281`
- Related Tests: `tests/test_compiler/test_quality_gates.py` (TestQualityGateIntegration placeholders)
- M3 Specification: Milestone 3.12 - Quality gates and confidence thresholds

---

## Notes

**Implementation Choice:** There are two approaches to implement retry logic:

1. **Exception-based approach**: Raise custom `QualityGateRetryableError`, catch in executor, retry in loop
   - Pros: Simple, contained within executor
   - Cons: Harder to integrate with LangGraph's graph structure

2. **Conditional edge approach**: Use LangGraph conditional edges to loop back to stage
   - Pros: Native LangGraph pattern, cleaner graph visualization
   - Cons: Requires changes to stage_compiler.py

**Recommendation:** Use conditional edge approach for better LangGraph integration.

**Observability Method:** May need to add `track_quality_gate_retry()` method to ExecutionTracker (similar to gap-m3-01). If so, coordinate with gap-m3-01 task or add minimal tracking.

**Performance Consideration:** Each retry executes the full stage (all agents), which can be expensive. Consider future optimization: retry with different parameters (e.g., higher temperature) or subset of agents.
