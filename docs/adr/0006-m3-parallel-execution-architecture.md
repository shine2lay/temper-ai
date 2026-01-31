# ADR-0006: M3 Parallel Agent Execution with Nested LangGraph Subgraphs

**Date:** 2026-01-30
**Status:** Accepted
**Deciders:** Framework Core Team
**Tags:** parallel, execution, M3, performance, langgraph, multi-agent

---

## Context

After completing Milestone 2 (M2) with single-agent workflows, Milestone 3 (M3) aimed to enable multi-agent collaboration. A critical performance requirement was executing multiple agents in parallel rather than sequentially.

**Problem Statement:**
- Sequential execution of 3+ agents takes 45-60+ seconds (15s per agent)
- Need 2-3x speedup through parallel execution
- Must safely manage concurrent state updates from multiple agents
- LangGraph provides nested graph capabilities but implementation unclear

**Use Cases:**
1. **Parallel Research** - 3 agents research different aspects simultaneously
2. **Code Review** - Multiple reviewers analyze code in parallel
3. **Expert Panels** - Different domain experts provide parallel input
4. **Quality Gates** - Multiple validators run concurrently

**Key Questions:**
- How do we execute agents in parallel within LangGraph's architecture?
- How do we prevent race conditions when multiple agents write to shared state?
- How do we track individual agent performance within parallel execution?
- How do we synthesize outputs after parallel execution completes?

---

## Decision Drivers

- **Performance** - 2-3x speedup requirement for parallel execution
- **State Safety** - No race conditions in concurrent agent updates
- **Observability** - Track individual agent performance within parallel execution
- **Quality** - Ensure synthesis doesn't degrade decision quality
- **Backward Compatibility** - Single-agent workflows still work
- **LangGraph Constraints** - Work within LangGraph's architecture
- **Developer Experience** - Reasonable learning curve and debugging

---

## Considered Options

### Option 1: Python Threading with Manual State Locking

**Description:** Use Python's threading module with manual locks for state synchronization.

**Pros:**
- Simple, familiar concurrency model
- Full control over execution
- No additional dependencies
- Python standard library

**Cons:**
- GIL (Global Interpreter Lock) limits true parallelism
- Manual lock management error-prone
- Hard to debug deadlocks
- No LangGraph integration
- Cannot leverage LangGraph observability

**Effort:** Medium (3-4 days)

---

### Option 2: Nested LangGraph Subgraphs with Annotated State

**Description:** Use LangGraph's native parallelism via nested StateGraph with Annotated state fields for automatic merge.

**Pros:**
- Native LangGraph parallelism
- Automatic state merging via custom reducers
- LangGraph observability hooks work automatically
- Graph visualization shows parallel execution
- No manual lock management
- Built-in error handling

**Cons:**
- Learning curve for Annotated state
- LangGraph-specific implementation
- Nested graph debugging more complex
- Tighter coupling to LangGraph

**Effort:** Medium (3-4 days)
**Performance:** 2.25x speedup achieved (45s → 20s)

---

### Option 3: Ray DAGs for Distributed Execution

**Description:** Use Ray framework for distributed parallel execution across multiple machines.

**Pros:**
- True distributed parallelism
- Scales beyond single machine
- Battle-tested for production
- Excellent observability

**Cons:**
- Adds Ray dependency (complex setup)
- Overkill for single-machine use case
- No LangGraph integration
- Higher operational complexity
- Requires Ray cluster management

**Effort:** High (1-2 weeks)

---

### Option 4: asyncio Concurrent Execution

**Description:** Rewrite agent execution using Python asyncio for concurrent I/O.

**Pros:**
- Python-native async/await
- No GIL limitations for I/O
- Lightweight concurrency
- Good for LLM API calls

**Cons:**
- Requires async LLM clients
- Complex error handling in async context
- State merging still manual
- No LangGraph integration
- Debugging async code harder

**Effort:** Medium-High (5-6 days)

---

## Decision Outcome

**Chosen Option:** Option 2: Nested LangGraph Subgraphs with Annotated State

**Justification:**

We selected nested LangGraph subgraphs because it leverages LangGraph's native parallelism while maintaining state safety and observability:

1. **LangGraph Native** - Works within the existing M2 architecture (ADR-0002)
2. **State Safety** - `Annotated[Dict[str, Any], merge_dicts]` with custom reducer prevents race conditions
3. **Performance** - Achieved 2.25x speedup (45s → 20s for 3 agents)
4. **Observability** - Automatic tracking via LangGraph hooks
5. **Visualization** - LangGraph tools visualize parallel branches
6. **ROI** - 3-4 day investment delivers 2-3x performance improvement

**Measured Performance:**
- Sequential baseline: 3 agents × 15s = 45s total
- Parallel execution: ~20s total (2.25x speedup)
- Orchestration overhead: <5s
- Individual agent metrics tracked automatically

**Decision Factors:**
- Single-machine use case doesn't justify Ray complexity
- Async rewrite would break existing synchronous tools
- Threading doesn't provide true parallelism due to GIL
- LangGraph subgraphs provide best balance of simplicity and performance

---

## Consequences

### Positive

- **Performance** - 2.25x speedup for multi-agent workflows (45s → 20s)
- **State Safety** - No race conditions via Annotated state merging
- **Observability** - Individual agent metrics tracked automatically
- **Visualization** - Graph diagrams show parallel execution clearly
- **Quality Gates** - Post-synthesis validation with retry support
- **Error Handling** - Individual agent failures don't crash entire workflow
- **Metrics** - Aggregate tokens, cost, duration automatically calculated
- **Backward Compatible** - Single-agent workflows unchanged

### Negative

- **LangGraph Coupling** - Tighter dependency on LangGraph (mitigated by M2.5 abstraction layer)
- **Learning Curve** - Developers must understand Annotated state and custom reducers
- **Debugging Complexity** - Nested graph debugging more complex than sequential
- **Memory Overhead** - Parallel state management requires more memory
- **Single Machine** - Cannot scale to distributed execution without rewrite

### Neutral

- **Parallel Benefit** - Only improves workflows with 2+ agents (single-agent unchanged)
- **Sequential Fallback** - Can still run agents sequentially if needed
- **Synthesis Required** - Parallel execution requires synthesis step (adds 2-5s)

---

## Implementation Notes

**Architecture:**

```python
# State definition with custom merge function
from typing import Annotated
from langgraph.graph import StateGraph

def merge_dicts(left: dict, right: dict) -> dict:
    """Merge two dicts, combining values for same keys."""
    merged = {**left}
    for key, value in right.items():
        if key in merged:
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged

class ParallelStageState(TypedDict):
    agent_outputs: Annotated[Dict[str, Any], merge_dicts]
    agent_statuses: Annotated[Dict[str, str], merge_dicts]
    agent_metrics: Annotated[Dict[str, AgentMetrics], merge_dicts]
    errors: Annotated[Dict[str, str], merge_dicts]
    stage_input: str  # Shared input context

# Execution flow
START → init → [agent1, agent2, agent3] (parallel) → collect → synthesis → END
```

**Key Components:**

1. **ParallelStageExecutor** (`src/compiler/executors/parallel.py` - 677 lines)
   - Creates nested StateGraph for parallel stage
   - Configures parallel agent nodes
   - Implements collect node for aggregation
   - Integrates with synthesis coordinator

2. **State Management** (`src/compiler/langgraph_compiler.py`)
   - ParallelStageState with Annotated fields
   - Custom merge_dicts reducer
   - Preserves individual agent outputs

3. **Quality Gates** (`src/compiler/quality_gates.py`)
   - Post-synthesis validation
   - Configurable thresholds
   - Retry logic (max_retries: 2)
   - Failure modes: escalate, proceed_with_warning, retry_stage

4. **Metrics Collection** (`src/compiler/executors/parallel.py`)
   - Per-agent token usage
   - Per-agent cost tracking
   - Per-agent duration
   - Aggregate metrics calculation

**Configuration:**

```yaml
stages:
  - name: parallel-research
    type: parallel
    agents:
      - name: researcher-1
        role: security
      - name: researcher-2
        role: performance
      - name: researcher-3
        role: reliability
    max_concurrent: 3
    min_success: 2
    synthesis:
      strategy: consensus
    quality_gates:
      enabled: true
      max_retries: 2
      failure_mode: escalate
```

**Performance Characteristics:**

| Metric | Value |
|--------|-------|
| Sequential (3 agents) | 45s |
| Parallel (3 agents) | 20s |
| Speedup | 2.25x |
| Overhead | <5s |
| Memory increase | ~2x (parallel state) |

**Action Items:**
- [x] Implement ParallelStageExecutor
- [x] Add Annotated state with merge_dicts reducer
- [x] Integrate quality gates with retry
- [x] Add aggregate metrics collection
- [x] Create parallel workflow examples
- [x] Add observability tracking for parallel execution
- [x] Document parallel execution guide

---

## Related Decisions

- [ADR-0001: Execution Engine Abstraction](./0001-execution-engine-abstraction.md) - Abstraction enables parallel executor
- [ADR-0002: LangGraph as Initial Engine](./0002-langgraph-as-initial-engine.md) - Nested subgraphs foundation
- [ADR-0003: Multi-Agent Collaboration Strategies](./0003-multi-agent-collaboration-strategies.md) - Synthesis after parallel
- [ADR-0004: Observability Database Schema](./0004-observability-database-schema.md) - Track parallel agent metrics

---

## References

- [Milestone 3 Completion Report](../milestones/milestone3_completion.md)
- [LangGraph Documentation - Nested Graphs](https://langchain-ai.github.io/langgraph/)
- [LangGraph Documentation - Annotated State](https://langchain-ai.github.io/langgraph/concepts/low_level/#annotated)
- [Implementation: ParallelStageExecutor](../../src/compiler/executors/parallel.py)
- [Multi-Agent Collaboration Guide](../features/collaboration/multi_agent_collaboration.md)
- [TECHNICAL_SPECIFICATION.md](../../TECHNICAL_SPECIFICATION.md) - M3 specification

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-30 | agent-cf221d | Initial decision record (backfilled from M3 implementation) |
