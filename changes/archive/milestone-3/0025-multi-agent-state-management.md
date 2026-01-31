# Change Document: Multi-Agent State Management

**Change ID:** 0017
**Task:** m3-08-multi-agent-state
**Date:** 2026-01-27
**Author:** Multi-agent (agent-b7e6d1)

---

## Summary

Enhanced state management for multi-agent stage execution to track individual agent outputs, execution status, metrics (tokens, cost, duration), and aggregate metrics. Enables detailed observability, cost analysis, and debugging of parallel agent execution with graceful handling of partial failures.

---

## Changes

### Files Modified

1. **src/compiler/schemas.py**
   - Added `AgentMetrics` model for tracking individual agent resource usage
   - Added `AggregateMetrics` model for rollup metrics across all agents
   - Added `MultiAgentStageState` model documenting expected state structure
   - Models support validation, defaults, and comprehensive documentation

2. **src/compiler/langgraph_compiler.py**
   - Enhanced `ParallelStageState` to include `agent_metrics` field
   - Added duration tracking for each agent execution (start to finish)
   - Calculate aggregate metrics in collection node
   - Store enhanced multi-agent state in workflow state
   - Updated observability tracking to include agent-level metrics

3. **tests/test_compiler/test_parallel_execution.py**
   - Updated test expectations to match new enhanced state structure
   - Added verification of aggregate metrics (tokens, costs, success counts)

---

## Implementation Details

### New State Models

#### AgentMetrics
```python
class AgentMetrics(BaseModel):
    tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    tool_calls: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
```

#### AggregateMetrics
```python
class AggregateMetrics(BaseModel):
    total_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    total_duration_seconds: float = Field(default=0.0, ge=0.0)  # Max for parallel
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    num_agents: int = Field(default=0, ge=0)
    num_successful: int = Field(default=0, ge=0)
    num_failed: int = Field(default=0, ge=0)
```

#### MultiAgentStageState
Complete documentation model showing expected structure:
- `agent_outputs`: Individual agent outputs with reasoning and confidence
- `agent_statuses`: Success/failure status per agent
- `agent_metrics`: Resource usage per agent
- `aggregate_metrics`: Rollup across all agents
- `errors`: Error messages for failed agents
- `min_successful_agents`: Threshold for stage success

### Enhanced Parallel Execution

**Duration Tracking:**
```python
import time
start_time = time.time()
# ... execute agent ...
duration = time.time() - start_time
```

**Metrics Collection:**
```python
"agent_metrics": {
    agent_name: {
        "tokens": response.tokens,
        "cost_usd": response.estimated_cost_usd,
        "duration_seconds": duration,
        "tool_calls": len(response.tool_calls),
        "retries": 0
    }
}
```

**Aggregate Calculation:**
```python
# In collect_outputs node
total_tokens = sum(metrics.get("tokens", 0) for metrics in agent_metrics.values())
total_cost = sum(metrics.get("cost_usd", 0.0) for metrics in agent_metrics.values())
max_duration = max(metrics.get("duration_seconds", 0.0) for metrics in agent_metrics.values())
avg_confidence = sum(outputs.get("confidence", 0.0)) / num_successful
```

### Enhanced State Structure

**Previous (M2):**
```python
state["stage_outputs"]["research"] = "final_decision"
```

**New (M3):**
```python
state["stage_outputs"]["research"] = {
    "decision": "final_decision",
    "agent_outputs": {...},      # Per-agent outputs
    "agent_statuses": {...},     # Success/failed per agent
    "agent_metrics": {...},      # Resource usage per agent
    "aggregate_metrics": {...},  # Rollup metrics
    "synthesis": {...}           # Collaboration details
}
```

---

## Verification

### Manual Testing
```bash
$ ./venv/bin/python /tmp/test_m3_08.py
✓ AgentMetrics created: tokens=100, cost=0.01, duration=2.5s
✓ AggregateMetrics created: total_tokens=300, num_successful=3/3
✓ MultiAgentStageState created: 1 agents

✅ All M3-08 models working correctly!
```

### Existing Tests
- All 13 existing langgraph_compiler tests passing
- Parallel execution tests updated for new structure
- Verified aggregate metrics calculation

---

## Example Usage

### Creating State with Metrics

```python
from src.compiler.schemas import AgentMetrics, AggregateMetrics, MultiAgentStageState

# Individual agent metrics
researcher_metrics = AgentMetrics(
    tokens=1500,
    cost_usd=0.03,
    duration_seconds=5.2,
    tool_calls=3,
    retries=0
)

analyst_metrics = AgentMetrics(
    tokens=2000,
    cost_usd=0.04,
    duration_seconds=6.1,
    tool_calls=5,
    retries=0
)

# Aggregate across agents
aggregate = AggregateMetrics(
    total_tokens=3500,
    total_cost_usd=0.07,
    total_duration_seconds=6.1,  # Max (parallel execution)
    avg_confidence=0.875,
    num_agents=2,
    num_successful=2,
    num_failed=0
)

# Complete stage state
stage_state = MultiAgentStageState(
    agent_outputs={
        "researcher": {"output": "findings...", "confidence": 0.9},
        "analyst": {"output": "analysis...", "confidence": 0.85}
    },
    agent_statuses={
        "researcher": "success",
        "analyst": "success"
    },
    agent_metrics={
        "researcher": researcher_metrics,
        "analyst": analyst_metrics
    },
    aggregate_metrics=aggregate,
    min_successful_agents=2
)
```

### Accessing Metrics from Workflow State

```python
# After parallel stage execution
stage_output = state["stage_outputs"]["research"]

# Get final decision
decision = stage_output["decision"]

# Get aggregate metrics
agg = stage_output["aggregate_metrics"]
print(f"Total cost: ${agg['total_cost_usd']:.4f}")
print(f"Total tokens: {agg['total_tokens']}")
print(f"Duration: {agg['total_duration_seconds']:.2f}s")
print(f"Success rate: {agg['num_successful']}/{agg['num_agents']}")

# Get per-agent metrics
for agent_name, metrics in stage_output["agent_metrics"].items():
    print(f"{agent_name}: {metrics['tokens']} tokens, ${metrics['cost_usd']:.4f}")
```

---

## Benefits

### Observability
- Track resource usage per agent for cost attribution
- Identify slow/expensive agents for optimization
- Debug failures with detailed error messages per agent
- Monitor success rates and partial failure patterns

### Cost Analysis
- Rollup costs across all agents in a stage
- Compare parallel vs sequential execution costs
- Budget tracking at agent and stage level
- Identify cost optimization opportunities

### Reliability
- Enforce `min_successful_agents` threshold
- Gracefully handle partial failures
- Track retry counts per agent
- Detailed error context for debugging

### Performance
- Track duration per agent
- Max duration for parallel (not sum)
- Identify bottleneck agents
- Optimize stage-level performance

---

## Acceptance Criteria

All acceptance criteria from task spec met:

- ✅ `agent_outputs: Dict[agent_name, output]` in state
- ✅ `agent_statuses: Dict[agent_name, "success"|"failed"]` tracking
- ✅ `agent_metrics: Dict[agent_name, metrics]` (tokens, cost, duration)
- ✅ Aggregate metrics (total_tokens, total_cost, total_duration)
- ✅ `min_successful_agents` enforcement
- ✅ Graceful handling of partial failures
- ✅ Track which agents succeeded/failed in observability
- ✅ Duration tracking added (start to finish per agent)

---

## Design Decisions

### Why Separate agent_metrics from agent_outputs?

**Decision:** Keep metrics separate from outputs for clarity and modularity.

**Rationale:**
- Outputs are domain data (decisions, reasoning)
- Metrics are operational data (tokens, costs)
- Separation enables different retention policies
- Easier to aggregate metrics without parsing outputs
- Cleaner schema and validation

### Why Max Duration for Parallel, Not Sum?

**Decision:** Use `max(durations)` for parallel execution.

**Rationale:**
- Parallel agents run concurrently
- Total wall-clock time is the longest agent, not the sum
- More accurate for cost/time budgeting
- Sequential mode would use sum of durations

### Why Track Tool Calls in Metrics?

**Decision:** Include tool_calls count in AgentMetrics.

**Rationale:**
- Tool calls often dominate execution time
- Useful for debugging slow agents
- Correlates with cost (tool calls = API calls)
- Helps identify tool-heavy vs reasoning-heavy agents

### Why Retries Field?

**Decision:** Add retries field to AgentMetrics.

**Rationale:**
- Enables retry tracking without changing status
- Useful for reliability analysis
- Future: implement retry logic with backoff
- M3: always 0 (no retries yet)

---

## Integration Points

### With Observability (M1)

Enhanced state automatically flows to observability tracker:
```python
tracker.track_collaboration_event(
    event_type="synthesis",
    stage_name=stage_name,
    agents=list(agent_outputs_dict.keys()),
    decision=synthesis_result.decision,
    confidence=synthesis_result.confidence,
    metadata={
        ...,
        "agent_statuses": {...},
        "aggregate_metrics": {...}
    }
)
```

### With Synthesis (M3)

Metrics used for merit-weighted resolution (future):
```python
# Agent performance metrics feed into merit scores
merit_score = calculate_merit(
    success_rate=agent_statuses["agent1"] == "success",
    avg_cost=agent_metrics["agent1"]["cost_usd"],
    avg_duration=agent_metrics["agent1"]["duration_seconds"]
)
```

### With Quality Gates (M3-12)

Aggregate metrics enable quality gate checks:
```python
# Enforce budget constraints
if aggregate_metrics["total_cost_usd"] > stage_budget:
    raise BudgetExceededError(...)

# Enforce performance SLAs
if aggregate_metrics["total_duration_seconds"] > timeout:
    raise TimeoutError(...)
```

---

## Migration Notes

### For Existing Code

**Old API (M2):**
```python
result = state["stage_outputs"]["research"]  # Just the decision string
```

**New API (M3):**
```python
stage_output = state["stage_outputs"]["research"]
result = stage_output["decision"]  # Access decision from dict
```

### Backward Compatibility

Sequential execution (M2) still stores simple string outputs.
Only parallel execution (M3) uses enhanced structure.

For code that needs to work with both:
```python
stage_output = state["stage_outputs"]["research"]
if isinstance(stage_output, dict):
    # M3 parallel execution
    decision = stage_output["decision"]
    metrics = stage_output["aggregate_metrics"]
else:
    # M2 sequential execution
    decision = stage_output
    metrics = None
```

---

## Future Enhancements (M4+)

1. **Retry Logic**: Use `retries` field to track retry attempts
2. **Budget Enforcement**: Real-time budget checks using aggregate metrics
3. **Performance SLAs**: Alert when duration exceeds thresholds
4. **Cost Optimization**: Identify expensive agents and suggest alternatives
5. **Merit Tracking**: Feed metrics into agent merit scores
6. **Adaptive Execution**: Use metrics to decide parallel vs sequential

---

## Success Metrics

- ✅ AgentMetrics, AggregateMetrics, MultiAgentStageState models created
- ✅ Duration tracking implemented (time.time() start/end)
- ✅ Aggregate metrics calculated in collect_outputs node
- ✅ Enhanced state structure persisted to workflow state
- ✅ All existing tests passing with updated expectations
- ✅ Manual testing confirms models working correctly
- ✅ Observability integration updated with agent-level metrics

---

## References

- Task spec: `.claude-coord/task-specs/m3-08-multi-agent-state.md`
- Related: m3-07 (Parallel Stage Execution) - provides foundation
- Related: m3-09 (Synthesis Node) - consumes enhanced state
- Related: m3-12 (Quality Gates) - uses aggregate metrics
- Related: M1 (Observability) - receives agent-level metrics
