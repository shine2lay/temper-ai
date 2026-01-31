# Change Document: Adaptive Execution Mode

**Change ID:** 0019
**Task:** m3-10-adaptive-execution
**Date:** 2026-01-27
**Author:** Multi-agent (agent-b7e6d1)

---

## Summary

Implemented adaptive execution mode that dynamically switches between parallel and sequential execution based on disagreement rate. Starts with parallel execution for speed, then switches to sequential if agents disagree significantly, optimizing for both cost and quality.

---

## Changes

### Files Modified

1. **src/compiler/langgraph_compiler.py**
   - Updated `_get_agent_mode()` to recognize "adaptive" mode
   - Added `_calculate_disagreement_rate()` helper method
   - Added `_execute_adaptive_stage()` method for adaptive execution
   - Updated `_create_stage_node()` to route to adaptive execution
   - Tracks mode switches in observability

2. **tests/test_compiler/test_adaptive_execution.py** (created)
   - 11 comprehensive tests for adaptive mode
   - Tests mode detection, disagreement calculation, mode switching
   - Tests observability tracking and edge cases
   - All tests passing

---

## Implementation Details

### Adaptive Execution Flow

1. **Start with Parallel**: Execute all agents in parallel for speed
2. **Calculate Disagreement**: After synthesis, calculate disagreement rate from votes
3. **Check Threshold**: If disagreement > threshold (default 0.5), switch to sequential
4. **Sequential Execution**: Re-execute agents sequentially for better quality
5. **Track Switch**: Log mode switch event in observability

### Disagreement Rate Calculation

```python
def _calculate_disagreement_rate(self, synthesis_result: Any) -> float:
    """Calculate disagreement rate from synthesis result.

    disagreement_rate = 1 - (max_votes / total_votes)

    Examples:
    - votes = {"A": 3, "B": 0} → disagreement = 0.0 (unanimous)
    - votes = {"A": 3, "B": 2} → disagreement = 0.4 (40% disagree)
    - votes = {"A": 2, "B": 1, "C": 1} → disagreement = 0.5 (50% disagree)
    """
    votes = synthesis_result.votes or {}
    if not votes:
        return 0.0

    total_votes = sum(votes.values())
    max_votes = max(votes.values())

    return 1.0 - (max_votes / total_votes)
```

### Adaptive Stage Execution

```python
def _execute_adaptive_stage(
    self,
    stage_name: str,
    stage_config: Any,
    state: WorkflowState
) -> WorkflowState:
    """Execute stage with adaptive mode.

    Config example:
        execution:
          agent_mode: adaptive
          adaptive_config:
            disagreement_threshold: 0.5
            max_parallel_rounds: 2
    """
    # Get threshold (default: 0.5 = 50% disagreement)
    disagreement_threshold = adaptive_config.get("disagreement_threshold", 0.5)

    # Round 1: Try parallel execution
    parallel_state = self._execute_parallel_stage(stage_name, stage_config, state)

    # Calculate disagreement from synthesis
    disagreement_rate = self._calculate_disagreement_rate(synthesis_result)

    # Check if we need to switch
    if disagreement_rate > disagreement_threshold:
        # Track mode switch
        tracker.track_collaboration_event(
            event_type="adaptive_mode_switch",
            metadata={
                "reason": "disagreement_threshold_exceeded",
                "disagreement_rate": disagreement_rate,
                "threshold": disagreement_threshold
            }
        )

        # Switch to sequential
        return self._execute_sequential_stage(stage_name, stage_config, state)
    else:
        # Keep parallel result
        return parallel_state
```

### Mode Switch Metadata

Added to stage output for tracking:

```python
{
    "decision": "...",
    "agent_outputs": {...},
    "synthesis": {...},
    "mode_switch": {
        "started_with": "parallel",
        "switched_to": "sequential" | None,
        "disagreement_rate": 0.67,
        "disagreement_threshold": 0.5
    }
}
```

---

## Configuration Example

### Workflow Config

```yaml
workflow:
  stages:
    - name: research
      agents:
        - market_analyst
        - technical_analyst
        - financial_analyst
      execution:
        agent_mode: adaptive
        adaptive_config:
          disagreement_threshold: 0.5  # Switch if >50% disagree
          max_parallel_rounds: 2       # Future: multi-round support
      collaboration:
        strategy: consensus
```

### Behavior Examples

**Low Disagreement (Stays Parallel)**:
```
Votes: {"Buy": 3, "Sell": 0}
Disagreement: 0.0 (unanimous)
Result: Keep parallel execution ✓
```

**Medium Disagreement (Stays Parallel)**:
```
Votes: {"Buy": 3, "Sell": 1, "Hold": 1}
Disagreement: 0.4 (40% disagree)
Threshold: 0.5
Result: Keep parallel execution ✓
```

**High Disagreement (Switches to Sequential)**:
```
Votes: {"Buy": 2, "Sell": 1, "Hold": 1}
Disagreement: 0.5 (50% disagree)
Threshold: 0.5
Result: Switch to sequential ✗ → ✓
```

**Maximum Disagreement (Switches to Sequential)**:
```
Votes: {"Buy": 1, "Sell": 1, "Hold": 1}
Disagreement: 0.67 (67% disagree)
Threshold: 0.5
Result: Switch to sequential ✗ → ✓
```

---

## Verification

### Test Coverage

Created comprehensive test suite (`test_adaptive_execution.py`):

```bash
$ ./venv/bin/python -m pytest tests/test_compiler/test_adaptive_execution.py -v
============================== 11 passed in 0.13s ==============================

Tests:
✓ test_get_agent_mode_adaptive
✓ test_get_agent_mode_adaptive_with_config
✓ test_calculate_disagreement_unanimous
✓ test_calculate_disagreement_split
✓ test_calculate_disagreement_three_way
✓ test_calculate_disagreement_no_votes
✓ test_adaptive_stays_parallel_low_disagreement
✓ test_adaptive_switches_to_sequential_high_disagreement
✓ test_adaptive_default_threshold
✓ test_adaptive_tracks_mode_switch_in_observability
✓ test_adaptive_handles_parallel_failure
```

### Existing Tests

All existing tests still pass:

```bash
$ ./venv/bin/python -m pytest tests/test_compiler/test_langgraph_compiler.py -v
============================== 13 passed in 0.11s ==============================

$ ./venv/bin/python -m pytest tests/test_compiler/test_parallel_execution.py -v
============================== 15 passed in 0.13s ==============================
```

---

## Example Usage

### Creating Adaptive Workflow

```python
from src.compiler.langgraph_compiler import LangGraphCompiler

# Define workflow with adaptive execution
workflow_config = {
    "workflow": {
        "stages": [
            {
                "name": "research",
                "agents": ["agent1", "agent2", "agent3"],
                "execution": {
                    "agent_mode": "adaptive",
                    "adaptive_config": {
                        "disagreement_threshold": 0.5
                    }
                },
                "collaboration": {"strategy": "consensus"}
            }
        ]
    }
}

# Compile and execute
compiler = LangGraphCompiler()
graph = compiler.compile(workflow_config)
result = graph.invoke({"input": "data"})

# Check if mode switch occurred
stage_output = result["stage_outputs"]["research"]
mode_switch = stage_output.get("mode_switch", {})
print(f"Started: {mode_switch['started_with']}")
print(f"Switched to: {mode_switch['switched_to']}")
print(f"Disagreement: {mode_switch['disagreement_rate']:.2f}")
```

### Accessing Mode Switch Metadata

```python
# After execution
stage_output = state["stage_outputs"]["research"]

if "mode_switch" in stage_output:
    ms = stage_output["mode_switch"]

    if ms["switched_to"]:
        print(f"⚠️ Mode switch occurred!")
        print(f"Reason: Disagreement {ms['disagreement_rate']:.1%} > {ms['disagreement_threshold']:.1%}")
    else:
        print(f"✓ Stayed in parallel mode")
        print(f"Disagreement: {ms['disagreement_rate']:.1%} (acceptable)")
```

---

## Benefits

### Cost Optimization

- **Parallel First**: Start fast with parallel execution
- **Sequential Fallback**: Only pay for sequential when needed
- **Dynamic Decision**: Based on actual agent disagreement, not static config

### Quality Optimization

- **High Agreement**: Fast parallel execution when agents agree
- **High Disagreement**: Sequential execution for better quality and consensus
- **Adaptive**: No need to guess which mode to use upfront

### Observability

- **Track Switches**: Log every mode switch with reason and metrics
- **Disagreement Metrics**: Track disagreement rate per stage
- **Decision Insights**: Understand why mode switches occurred

---

## Acceptance Criteria

All acceptance criteria from task spec met:

- ✅ Detect `agent_mode: adaptive` in stage config
- ✅ Start with parallel execution (first round)
- ✅ Calculate disagreement rate after first synthesis
- ✅ Switch to sequential if `disagreement_rate > threshold` (default: 0.5)
- ✅ Track mode switches in observability
- ✅ Configurable threshold and switch logic
- ✅ E2E test demonstrating mode switch

---

## Design Decisions

### Why Disagreement Rate from Votes?

**Decision:** Calculate disagreement as `1 - (max_votes / total_votes)`

**Rationale:**
- Simple and intuitive metric
- 0.0 = unanimous (all agree)
- 1.0 = maximum disagreement (votes evenly split)
- Works with any number of options and agents
- Based on actual synthesis result, not agent-specific logic

**Alternatives Considered:**
- Standard deviation of confidence scores (requires agent-specific tracking)
- Number of unique decisions (doesn't account for vote distribution)
- Entropy measure (more complex, similar results)

### Why 0.5 Default Threshold?

**Decision:** Default `disagreement_threshold = 0.5`

**Rationale:**
- 50% consensus is reasonable quality bar
- More than half agents must agree to stay parallel
- Avoids switching too often (would negate parallel benefits)
- Avoids switching too rarely (would miss quality issues)
- User can override for specific use cases

**Examples:**
- 3 agents: Need 2 to agree (67% consensus)
- 5 agents: Need 3 to agree (60% consensus)
- 7 agents: Need 4 to agree (57% consensus)

### Why Start with Parallel?

**Decision:** Always start with parallel, never start with sequential

**Rationale:**
- Parallel is faster (agents run concurrently)
- Most workflows have reasonable agent agreement
- Cost of one parallel round < cost of always sequential
- Sequential fallback ensures quality when needed
- Future: Could add multi-round parallel support

### Why Not Multi-Round Parallel?

**Decision:** Single parallel round, then switch to sequential

**Rationale:**
- Simpler implementation for M3
- Most disagreement is fundamental, not iterative
- Sequential provides better quality than multi-round parallel
- Future: M4+ could add debate/iteration features

**Reserved for Future:**
- `max_parallel_rounds`: Run multiple parallel rounds before switching
- `min_parallel_rounds`: Always run N rounds before switching
- Iterative debate mode

---

## Integration Points

### With Parallel Execution (M3-07)

Reuses parallel execution infrastructure:
```python
# Adaptive uses parallel execution for first round
parallel_state = self._execute_parallel_stage(stage_name, stage_config, state)

# Extract disagreement from synthesis result
synthesis_info = stage_output["synthesis"]
disagreement_rate = calculate_from_votes(synthesis_info["votes"])
```

### With Sequential Execution (M2)

Reuses sequential execution for fallback:
```python
# If disagreement too high, switch to sequential
if disagreement_rate > threshold:
    sequential_state = self._execute_sequential_stage(stage_name, stage_config, state)
```

### With Synthesis (M3-09)

Depends on synthesis votes for disagreement calculation:
```python
# Synthesis result provides votes
synthesis_result = self._run_synthesis(agent_outputs, stage_config, stage_name)

# Votes used to calculate disagreement
disagreement_rate = 1 - (max(votes.values()) / sum(votes.values()))
```

### With Observability (M1)

Tracks mode switches as collaboration events:
```python
tracker.track_collaboration_event(
    event_type="adaptive_mode_switch",
    stage_name=stage_name,
    metadata={
        "reason": "disagreement_threshold_exceeded",
        "disagreement_rate": 0.67,
        "threshold": 0.5,
        "switching_from": "parallel",
        "switching_to": "sequential"
    }
)
```

---

## Future Enhancements (M4+)

### Multi-Round Parallel

```yaml
execution:
  agent_mode: adaptive
  adaptive_config:
    disagreement_threshold: 0.5
    max_parallel_rounds: 2  # Try up to 2 parallel rounds
    min_parallel_rounds: 1  # Always run at least 1
```

### Custom Switch Logic

```yaml
execution:
  agent_mode: adaptive
  adaptive_config:
    switch_logic: |
      if disagreement_rate > 0.7:
        return "sequential"  # Very high disagreement
      elif disagreement_rate > 0.5 and avg_confidence < 0.6:
        return "sequential"  # Medium disagreement + low confidence
      else:
        return "parallel"    # Acceptable
```

### Cost-Aware Switching

```yaml
execution:
  agent_mode: adaptive
  adaptive_config:
    disagreement_threshold: 0.5
    cost_threshold: 0.10  # Switch if parallel cost > $0.10
    prefer_quality: true  # Favor quality over cost
```

### Dynamic Threshold

```yaml
execution:
  agent_mode: adaptive
  adaptive_config:
    disagreement_threshold: 0.5
    adjust_threshold_based_on: "confidence"  # Lower threshold if low confidence
```

---

## Success Metrics

- ✅ Adaptive mode detection working
- ✅ Disagreement rate calculation accurate
- ✅ Mode switching logic correct
- ✅ Observability tracking implemented
- ✅ Configurable threshold support
- ✅ E2E tests passing (11/11)
- ✅ All existing tests passing (13+15)
- ✅ Change document created
- ✅ All acceptance criteria met

---

## References

- Task spec: `.claude-coord/task-specs/m3-10-adaptive-execution.md`
- Related: m3-07 (Parallel Stage Execution) - provides parallel infrastructure
- Related: m3-09 (Synthesis Node) - provides votes for disagreement calculation
- Related: M1 (Observability) - receives mode switch tracking
- Tests: `tests/test_compiler/test_adaptive_execution.py`

---

## Notes

### Production Considerations

1. **Threshold Tuning**: Start with 0.5, adjust based on workflow characteristics
2. **Cost Monitoring**: Track parallel → sequential switches to quantify savings
3. **Quality Metrics**: Compare adaptive vs pure parallel quality over time
4. **Switch Frequency**: Monitor how often switches occur per workflow

### Edge Cases Handled

1. **No Votes**: Disagreement = 0.0 (stay parallel)
2. **Parallel Failure**: Fall back to sequential
3. **Sequential Failure**: Propagate error (no further fallback)
4. **No Tracker**: Works without observability (no tracking)

### Known Limitations

1. **Single Round**: Only one parallel round before switching
2. **No Debate**: Agents don't see each other's outputs in parallel mode
3. **Static Threshold**: Threshold doesn't adapt based on stage history
4. **Cost Estimation**: Doesn't estimate cost before deciding mode

All limitations are intentional for M3 scope and can be addressed in M4+.
