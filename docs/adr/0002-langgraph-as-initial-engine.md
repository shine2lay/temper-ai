# ADR-0002: LangGraph as Initial Workflow Execution Engine

**Date:** 2026-01-26
**Status:** Accepted
**Deciders:** Framework Core Team
**Tags:** execution, langgraph, workflow, M2

---

## Context

During Milestone 2 (M2), the framework needed a workflow execution engine to orchestrate multi-stage workflows with sequential and parallel execution of agents. The system required:

**Problem Statement:**
- Compile YAML workflow definitions into executable graphs
- Support sequential stage execution with conditional routing
- Enable parallel agent execution within stages (M3)
- Manage workflow state across stage transitions
- Provide nested graph support (workflows → stages → agents)
- Integrate with LLM providers and tool execution

**Key Requirements:**
1. **Graph-Based Workflows** - Workflows are DAGs (directed acyclic graphs) with nodes and edges
2. **State Management** - Workflow state must propagate between stages
3. **Nested Graphs** - Support hierarchical execution (workflow contains stages contains agents)
4. **Conditional Routing** - Route based on stage outcomes (on_success, on_failure)
5. **Parallel Execution** - Run multiple agents concurrently within a stage
6. **Python Native** - First-class Python support, easy integration

**Key Questions:**
1. Should we build a custom workflow engine or use an existing solution?
2. Which execution engine best fits our graph-based workflow model?
3. Can it support both M2 (sequential) and M3 (parallel) requirements?
4. What's the learning curve and community support?

---

## Decision Drivers

- **Graph-Based Model** - Workflows are naturally modeled as state graphs
- **Nested Graph Support** - Need hierarchical execution (workflow → stage → agent)
- **State Management** - Stateful workflows with state propagation between stages
- **Parallel Execution** - M3 requires concurrent agent execution
- **Time to Market** - Prefer proven solution over custom implementation
- **Python Ecosystem** - Must integrate cleanly with Python LLM libraries
- **Extensibility** - Support for custom nodes, edges, conditions
- **Community Support** - Active development and documentation

---

## Considered Options

### Option 1: Custom Workflow Engine

**Description:** Build a custom workflow execution engine from scratch tailored to framework needs.

**Pros:**
- Complete control over execution logic
- Perfect fit for framework requirements
- No external dependencies
- Custom optimizations possible

**Cons:**
- **High Effort:** 4-6 weeks to build robust engine
- **Maintenance Burden:** Now maintaining complex execution engine
- **Bug Risk:** Custom engines are bug-prone, require extensive testing
- **Delayed Launch:** Delays M2 completion significantly
- **Reinventing Wheel:** Solving already-solved problems

**Effort:** 4-6 weeks (HIGH)

---

### Option 2: Apache Airflow

**Description:** Use Airflow DAG (Directed Acyclic Graph) for workflow orchestration.

**Pros:**
- Mature, battle-tested workflow engine
- Strong community and documentation
- Web UI for workflow visualization
- Scheduling capabilities

**Cons:**
- **Heavyweight:** Designed for batch ETL, not real-time agent workflows
- **Complex Setup:** Requires database, scheduler, workers
- **Not Real-Time:** Focused on scheduled batch jobs
- **Limited State Management:** Not designed for stateful agent conversations
- **Overkill:** Too much infrastructure for simple workflows

**Effort:** 2-3 weeks (MEDIUM)

---

### Option 3: Temporal

**Description:** Use Temporal workflow engine for durable, fault-tolerant execution.

**Pros:**
- Excellent fault tolerance and durability
- Strong state management
- Good for long-running workflows
- Event sourcing built-in

**Cons:**
- **Complex Infrastructure:** Requires Temporal server cluster
- **Learning Curve:** Temporal SDK is complex
- **Over-Engineering:** Durable execution not critical for M2 (can add later)
- **Heavyweight:** Too much for simple sequential workflows
- **Multi-Language:** Go backend adds deployment complexity

**Effort:** 3-4 weeks (MEDIUM-HIGH)

---

### Option 4: LangGraph

**Description:** Use LangGraph from LangChain ecosystem for graph-based LLM workflows.

**Pros:**
- **Purpose-Built:** Designed specifically for LLM agent workflows
- **Graph Model:** Native state graph abstraction (perfect fit for our model)
- **Nested Graphs:** Supports hierarchical graphs (workflow → stage)
- **State Management:** Built-in state propagation between nodes
- **Parallel Execution:** Support for concurrent branches (M3 ready)
- **Python Native:** Pure Python, easy integration
- **LangChain Ecosystem:** Integrates with LangChain tools and agents
- **Low Overhead:** Lightweight, no external infrastructure required
- **Fast Adoption:** 2-3 days to integrate

**Cons:**
- **Vendor Dependency:** Tied to LangGraph API evolution
- **Relatively New:** Younger project, smaller community than Airflow/Temporal
- **Limited Docs:** Documentation still evolving

**Effort:** 2-3 days (LOW)

---

## Decision Outcome

**Chosen Option:** Option 4: LangGraph

**Justification:**

LangGraph is the perfect fit for M2 requirements and future milestones:

1. **Purpose-Built for LLM Workflows** - Designed specifically for the agent workflow use case, not retrofitted from ETL or general orchestration

2. **Graph Model Match** - Native StateGraph abstraction perfectly matches our workflow model (stages as nodes, transitions as edges)

3. **Nested Graph Support** - Can compile workflows into nested graphs (workflow graph contains stage subgraphs)

4. **State Management** - Built-in state propagation between nodes eliminates custom state handling

5. **M3 Ready** - Parallel execution support enables multi-agent collaboration in M3 without engine changes

6. **Minimal Overhead** - Lightweight Python library with no infrastructure requirements (perfect for M2)

7. **Fast Integration** - Can integrate in 2-3 days vs 4-6 weeks for custom or 2-4 weeks for Airflow/Temporal

8. **Python Ecosystem** - Integrates seamlessly with LangChain, Ollama, OpenAI, Anthropic SDKs

**Tradeoffs Accepted:**
- **Vendor Lock-In** - Mitigated by M2.5 abstraction layer (see ADR-0001)
- **Young Project** - Risk mitigated by active development and LangChain backing
- **Limited Docs** - Acceptable for 1.5-day learning curve savings

**Decision Timeline:**
- M2: Use LangGraph directly for fast time-to-market
- M2.5: Add abstraction layer to prevent vendor lock-in
- M5+: Can migrate to custom/alternative engines if needed

---

## Consequences

### Positive

- **Fast M2 Completion** - 2-3 day integration vs weeks for alternatives
- **Graph-Based Workflows** - Natural fit for YAML workflow → StateGraph compilation
- **Nested Graph Support** - Workflows contain stages contain agents (hierarchical execution)
- **State Propagation** - Built-in state management between stages
- **M3 Compatibility** - Parallel execution ready for multi-agent collaboration
- **No Infrastructure** - Pure Python library, no servers or databases required
- **LangChain Integration** - Access to LangChain tools, agents, prompts

### Negative

- **Vendor Dependency** - Tied to LangGraph API (mitigated by M2.5 abstraction layer)
- **Learning Curve** - Team needs to learn LangGraph StateGraph API
- **Younger Ecosystem** - Fewer Stack Overflow answers than Airflow/Temporal
- **Limited Advanced Features** - No built-in scheduling, retries, monitoring (we build these)

### Neutral

- **LangChain Ecosystem** - Useful for M2-M3, but may want independence later (M2.5 abstraction enables this)
- **Graph Compilation** - Need to build YAML → LangGraph compiler (but would need compiler for any engine)

---

## Implementation Notes

**LangGraph Compiler Architecture:**

```python
class LangGraphCompiler:
    """Compile YAML workflow into LangGraph StateGraph."""

    def compile(self, workflow_config: Dict) -> StateGraph:
        # 1. Create top-level workflow graph
        workflow_graph = StateGraph(WorkflowState)

        # 2. For each stage, create nested subgraph
        for stage in workflow_config['stages']:
            stage_graph = self._compile_stage(stage)
            workflow_graph.add_node(stage['name'], stage_graph)

        # 3. Add edges for stage transitions
        for i in range(len(stages) - 1):
            workflow_graph.add_edge(stages[i]['name'], stages[i+1]['name'])

        # 4. Compile and return
        return workflow_graph.compile()

    def _compile_stage(self, stage_config: Dict) -> Callable:
        # Create nested graph for parallel agent execution
        # (M3 feature, simplified in M2)
        ...
```

**Key Implementation Files:**
- `temper_ai/compiler/langgraph_compiler.py` - YAML → LangGraph compilation
- `temper_ai/compiler/langgraph_engine.py` - M2.5 adapter wrapper (see ADR-0001)
- `configs/workflows/*.yaml` - YAML workflow definitions

**Action Items:**
- [x] Implement LangGraphCompiler
- [x] Test sequential stage execution
- [x] Test state propagation between stages
- [x] Integrate with observability tracking
- [x] Test with real Ollama LLM execution
- [x] Add M2.5 abstraction layer to prevent vendor lock-in

---

## Related Decisions

- [ADR-0001: Execution Engine Abstraction](./0001-execution-engine-abstraction.md) - M2.5 abstraction layer to decouple from LangGraph
- [ADR-0003: Multi-Agent Collaboration Strategies](./0003-multi-agent-collaboration-strategies.md) - M3 parallel execution using LangGraph subgraphs
- [ADR-0005: YAML-Based Configuration](./0005-yaml-based-configuration.md) - Workflow definition format

---

## References

- [LangGraph Documentation](https://python.langchain.com/docs/langgraph) - Official LangGraph docs
- [Milestone 2 Completion Report](../milestones/milestone2_completion.md) - M2 deliverables
- [Milestone 2.5 Completion Report](../milestones/milestone2.5_completion.md) - Abstraction layer
- [TECHNICAL_SPECIFICATION.md](../../TECHNICAL_SPECIFICATION.md) - Section on workflow execution

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-26 | Framework Core Team | Initial decision |
| 2026-01-28 | agent-d6e90e | Backfilled from M2 completion |
