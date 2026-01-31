# Task: m3-07-parallel-stage-execution - Add Parallel Stage Execution to LangGraph

**Priority:** HIGH (P1)
**Effort:** 14 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Modify LangGraphCompiler to support parallel agent execution within stages. When stage config specifies `agent_mode: parallel`, all agents execute concurrently and outputs are collected for synthesis. Major M3 feature enabling true multi-agent collaboration.

---

## Files to Modify

- `src/compiler/langgraph_compiler.py` - Add parallel node creation (~300 lines added)

---

## Files to Create

- `tests/test_compiler/test_parallel_execution.py` - Parallel execution tests

---

## Acceptance Criteria

### Core Functionality
- [ ] Detect `agent_mode: parallel` in stage config
- [ ] Create parallel LangGraph nodes for all agents in stage
- [ ] Execute all agents concurrently (LangGraph parallel branches)
- [ ] Collect outputs from all agents into stage state
- [ ] Pass collected outputs to synthesis node
- [ ] Support `agent_mode: sequential` (existing behavior)
- [ ] Support fallback to sequential if parallel fails

### Performance
- [ ] Parallel execution has <10% overhead vs sequential
- [ ] Agents truly execute concurrently (not fake parallelism)
- [ ] No blocking waits during parallel execution
- [ ] Resource limits respected (max concurrent agents)

### Error Handling
- [ ] Handle individual agent failures gracefully
- [ ] Continue with successful agents if some fail
- [ ] Enforce `min_successful_agents` from stage config
- [ ] Track which agents succeeded/failed
- [ ] Aggregate error messages

### Integration
- [ ] Works with existing tracker/observability
- [ ] Works with tool registry
- [ ] Works with config loader
- [ ] Backward compatible (sequential still works)

### Testing
- [ ] Test parallel execution with 3 agents
- [ ] Test sequential execution still works
- [ ] Test partial agent failure (2/3 succeed)
- [ ] Test all agents fail
- [ ] Test min_successful_agents enforcement
- [ ] Performance test: parallel faster than sequential
- [ ] E2E test with real workflow
- [ ] Coverage >85%

---

## Implementation Details

### Architecture Changes

**Before (M2 - Sequential):**
```
Stage Node:
  → Agent 1 executes
  → Agent 2 executes
  → Agent 3 executes
  → Return last agent output
```

**After (M3 - Parallel):**
```
Stage Node (coordinator):
  → Spawn parallel branches:
      ├─ Agent 1 Node → executes
      ├─ Agent 2 Node → executes
      └─ Agent 3 Node → executes
  → Collect Node (waits for all)
      → Aggregates outputs
      → Passes to Synthesis Node
  → Synthesis Node
      → Runs collaboration strategy
      → Returns unified decision
```

### Implementation

```python
# In langgraph_compiler.py

def _create_stage_node(
    self,
    stage_name: str,
    workflow_config: Any
) -> Callable:
    """Create execution node for a stage.

    Now supports both sequential and parallel agent execution.
    """
    def stage_node(state: WorkflowState) -> WorkflowState:
        """Execute stage with configured agent mode."""
        # Load stage config
        stage_config = self._load_stage_config(stage_name, workflow_config)

        # Get execution mode
        agent_mode = self._get_agent_mode(stage_config)

        if agent_mode == "parallel":
            return self._execute_parallel_stage(stage_name, stage_config, state)
        else:  # sequential or default
            return self._execute_sequential_stage(stage_name, stage_config, state)

    return stage_node


def _execute_parallel_stage(
    self,
    stage_name: str,
    stage_config: Any,
    state: WorkflowState
) -> WorkflowState:
    """Execute stage with parallel agent execution.

    Creates a nested LangGraph with parallel branches for agents.

    Args:
        stage_name: Stage name
        stage_config: Stage configuration
        state: Current workflow state

    Returns:
        Updated workflow state with synthesized output
    """
    from langgraph.graph import StateGraph, START, END
    from typing_extensions import TypedDict
    import asyncio

    # Define state for parallel execution subgraph
    class ParallelStageState(TypedDict, total=False):
        agent_outputs: Dict[str, Any]  # Agent name -> output
        agent_statuses: Dict[str, str]  # Agent name -> status (success|failed)
        errors: Dict[str, str]  # Agent name -> error message
        stage_input: Dict[str, Any]  # Input data for all agents

    # Create subgraph for parallel execution
    subgraph = StateGraph(ParallelStageState)

    # Add initialization node
    def init_parallel(s: ParallelStageState) -> ParallelStageState:
        s["agent_outputs"] = {}
        s["agent_statuses"] = {}
        s["errors"] = {}
        s["stage_input"] = {
            **state,
            "stage_outputs": state.get("stage_outputs", {})
        }
        return s

    subgraph.add_node("init", init_parallel)

    # Get agents for this stage
    agents = self._get_stage_agents(stage_config)

    # Create node for each agent
    for agent_ref in agents:
        agent_name = self._extract_agent_name(agent_ref)

        # Create agent execution node
        agent_node = self._create_agent_node(
            agent_name=agent_name,
            agent_ref=agent_ref,
            stage_name=stage_name,
            state=state
        )

        subgraph.add_node(agent_name, agent_node)

    # Create collection node (waits for all agents)
    def collect_outputs(s: ParallelStageState) -> ParallelStageState:
        """Collect and validate agent outputs."""
        # Check minimum successful agents
        min_successful = stage_config.get("error_handling", {}).get(
            "min_successful_agents", 1
        )

        successful = [
            name for name, status in s["agent_statuses"].items()
            if status == "success"
        ]

        if len(successful) < min_successful:
            raise RuntimeError(
                f"Only {len(successful)}/{len(agents)} agents succeeded. "
                f"Minimum required: {min_successful}"
            )

        return s

    subgraph.add_node("collect", collect_outputs)

    # Add edges: init → all agents → collect
    subgraph.add_edge(START, "init")

    for agent_ref in agents:
        agent_name = self._extract_agent_name(agent_ref)
        subgraph.add_edge("init", agent_name)  # Parallel: init → each agent
        subgraph.add_edge(agent_name, "collect")  # Each agent → collect

    subgraph.add_edge("collect", END)

    # Compile and execute subgraph
    compiled_subgraph = subgraph.compile()

    try:
        # Execute parallel subgraph
        parallel_result = compiled_subgraph.invoke({})

        # Extract agent outputs
        agent_outputs_dict = parallel_result["agent_outputs"]

        # Create AgentOutput objects for synthesis
        from src.strategies.base import AgentOutput

        agent_outputs = []
        for agent_name, output_data in agent_outputs_dict.items():
            agent_outputs.append(AgentOutput(
                agent_name=agent_name,
                decision=output_data.get("output", ""),
                reasoning=output_data.get("reasoning", ""),
                confidence=output_data.get("confidence", 0.8),
                metadata=output_data.get("metadata", {})
            ))

        # Run synthesis
        synthesis_result = self._run_synthesis(
            agent_outputs=agent_outputs,
            stage_config=stage_config,
            stage_name=stage_name
        )

        # Update state
        state["stage_outputs"][stage_name] = synthesis_result.decision
        state["current_stage"] = stage_name

        # Track synthesis in observability
        if state.get("tracker"):
            state["tracker"].track_collaboration_event(
                event_type="synthesis",
                stage_name=stage_name,
                agents=list(agent_outputs_dict.keys()),
                decision=synthesis_result.decision,
                confidence=synthesis_result.confidence,
                metadata=synthesis_result.metadata
            )

        return state

    except Exception as e:
        # Handle stage failure
        error_handling = stage_config.get("error_handling", {})
        on_failure = error_handling.get("on_stage_failure", "halt")

        if on_failure == "halt":
            raise
        elif on_failure == "skip":
            # Skip this stage, continue workflow
            state["stage_outputs"][stage_name] = None
            return state
        else:
            raise


def _create_agent_node(
    self,
    agent_name: str,
    agent_ref: Any,
    stage_name: str,
    state: WorkflowState
) -> Callable:
    """Create execution node for a single agent.

    Args:
        agent_name: Agent name
        agent_ref: Agent reference from stage config
        stage_name: Stage name
        state: Workflow state

    Returns:
        Callable node function
    """
    def agent_node(s: Dict[str, Any]) -> Dict[str, Any]:
        """Execute single agent."""
        try:
            # Load agent config
            agent_config_dict = self.config_loader.load_agent(agent_name)

            from src.compiler.schemas import AgentConfig
            agent_config = AgentConfig(**agent_config_dict)

            # Create agent
            from src.agents.agent_factory import AgentFactory
            agent = AgentFactory.create(agent_config)

            # Prepare input
            input_data = s["stage_input"]

            # Create execution context
            from src.agents.base_agent import ExecutionContext
            import uuid

            context = ExecutionContext(
                workflow_id=state.get("workflow_id", "unknown"),
                stage_id=f"stage-{uuid.uuid4().hex[:12]}",
                agent_id=f"agent-{uuid.uuid4().hex[:12]}",
                metadata={
                    "stage_name": stage_name,
                    "agent_name": agent_name,
                }
            )

            # Execute agent
            response = agent.execute(input_data, context)

            # Store output
            s["agent_outputs"][agent_name] = {
                "output": response.output,
                "reasoning": response.reasoning,
                "confidence": 0.8,  # TODO: Get from agent
                "tokens": response.tokens,
                "cost": response.estimated_cost_usd,
                "metadata": {}
            }

            s["agent_statuses"][agent_name] = "success"

        except Exception as e:
            # Store error
            s["agent_statuses"][agent_name] = "failed"
            s["errors"][agent_name] = str(e)

        return s

    return agent_node


def _run_synthesis(
    self,
    agent_outputs: List[Any],
    stage_config: Any,
    stage_name: str
) -> Any:
    """Run collaboration strategy to synthesize agent outputs.

    Args:
        agent_outputs: List of AgentOutput objects
        stage_config: Stage configuration
        stage_name: Stage name

    Returns:
        SynthesisResult
    """
    from src.strategies.registry import get_strategy_from_config

    # Get strategy from config
    strategy = get_strategy_from_config(stage_config)

    # Get strategy config
    collaboration_config = stage_config.get("collaboration", {}).get("config", {})

    # Synthesize
    result = strategy.synthesize(agent_outputs, collaboration_config)

    return result


def _get_agent_mode(self, stage_config: Any) -> str:
    """Get agent execution mode from stage config.

    Args:
        stage_config: Stage configuration

    Returns:
        "parallel" or "sequential"
    """
    execution = stage_config.get("execution", {})
    return execution.get("agent_mode", "sequential")
```

---

## Test Strategy

### Unit Tests (`tests/test_compiler/test_parallel_execution.py`)

```python
import pytest
from src.compiler.langgraph_compiler import LangGraphCompiler


def test_parallel_execution_mode_detection():
    """Test detection of parallel vs sequential mode."""
    compiler = LangGraphCompiler()

    # Parallel mode
    stage_config = {
        "execution": {"agent_mode": "parallel"},
        "agents": ["agent1", "agent2"]
    }
    assert compiler._get_agent_mode(stage_config) == "parallel"

    # Sequential mode (default)
    stage_config = {"agents": ["agent1"]}
    assert compiler._get_agent_mode(stage_config) == "sequential"


def test_parallel_execution_creates_subgraph():
    """Test parallel execution creates nested graph."""
    # Test will verify subgraph structure
    pass  # Implementation test


def test_partial_agent_failure():
    """Test handling when some agents fail."""
    # 2/3 agents succeed, min_successful_agents=2
    pass  # Integration test


def test_min_successful_agents_enforcement():
    """Test enforcement of minimum successful agents."""
    # Only 1/3 succeed, min_successful_agents=2 → fail
    pass  # Integration test


@pytest.mark.performance
def test_parallel_faster_than_sequential():
    """Test parallel execution is actually faster."""
    # Compare execution time of 3 agents
    # Parallel should be ~3x faster (minus overhead)
    pass  # Performance test
```

---

## Success Metrics

- [ ] File modified: `src/compiler/langgraph_compiler.py`
- [ ] File created: `tests/test_compiler/test_parallel_execution.py`
- [ ] All tests pass
- [ ] Parallel execution <10% overhead
- [ ] Works with existing sequential stages
- [ ] E2E test with 3-agent parallel stage passes
- [ ] Coverage >85% for parallel code paths

---

## Dependencies

**Blocked by:**
- m3-01-collaboration-strategy-interface (needs AgentOutput type)
- m3-03-consensus-strategy (needs strategy for synthesis)
- m3-06-strategy-registry (needs registry to get strategies)

**Blocks:**
- m3-08-multi-agent-state-management (extends parallel execution)
- m3-09-synthesis-node (uses parallel execution)

---

## Design References

- [LangGraph Parallel Execution](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/multi-agent-collaboration/)
- [Technical Specification - Stage Execution](../../TECHNICAL_SPECIFICATION.md)

---

## Notes

**Why Parallel Execution:**
- 3x-5x speedup for independent agents
- Enables true multi-agent collaboration
- Better resource utilization
- Key M3 differentiator

**Design Decisions:**
- Nested subgraph for parallel execution (clean separation)
- Collect node waits for all agents (barrier pattern)
- min_successful_agents allows partial failures
- Synthesis runs after collection (not during)

**Critical:**
- This is the most complex M3 task (14 hours)
- Performance matters (must be truly parallel)
- Error handling is crucial (agents can fail)
- Backward compatibility required (sequential still works)

**Implementation Notes:**
- LangGraph supports parallel branches natively
- Use TypedDict for parallel stage state
- Agent nodes must be independent (no shared state)
- Collection node is synchronization point

**Future Enhancements (M4+):**
- Adaptive parallelism (switch to sequential on high contention)
- Resource pooling (limit concurrent LLM calls)
- Priority-based scheduling
- Speculative execution (start next stage early)
