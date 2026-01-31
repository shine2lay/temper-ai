# Task: m2-05-langgraph-basic - Implement basic LangGraph compiler for single-agent workflows

**Priority:** HIGH
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Compile WorkflowConfig → LangGraph execution graph. For M2, focus on single-agent, single-stage workflows only. Multi-agent collaboration comes in M3.

---

## Files to Create

- `src/compiler/langgraph_compiler.py` - Compiler class
- `src/compiler/workflow_executor.py` - WorkflowExecutor
- `tests/test_compiler/test_langgraph_compiler.py` - Tests

---

## Acceptance Criteria

- [ ] Compile WorkflowConfig to LangGraph StateGraph
- [ ] Single-stage execution
- [ ] Single-agent execution per stage
- [ ] Sequential execution (no parallel yet)
- [ ] State management (workflow state passed between stages)
- [ ] Checkpoint support (basic)
- [ ] Execute workflow end-to-end
- [ ] Tests with simple workflow
- [ ] Coverage > 80%

---

## Implementation

```python
from langgraph.graph import StateGraph

class LangGraphCompiler:
    """Compiles workflow configs to LangGraph."""
    
    def compile(self, workflow_config: WorkflowConfig) -> StateGraph:
        """Compile workflow to executable graph."""
        graph = StateGraph()
        
        # Add nodes for each stage
        for stage in workflow_config.workflow.stages:
            graph.add_node(stage.name, self._create_stage_node(stage))
        
        # Add edges (sequential for M2)
        stages = workflow_config.workflow.stages
        for i in range(len(stages) - 1):
            graph.add_edge(stages[i].name, stages[i+1].name)
        
        return graph.compile()
```

---

## Success Metrics

- [ ] Simple workflow compiles and executes
- [ ] State flows between stages
- [ ] Tests pass > 80%

---

## Dependencies

- **Blocked by:** m2-04-agent-runtime
- **Blocks:** m2-08-e2e-execution

