# Task: m2-08-e2e-execution - End-to-end workflow execution with real LLM

**Priority:** NORMAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Create end-to-end integration test and demo that runs a complete workflow with real Ollama LLM, tools, database tracking, and console visualization. This validates that ALL M2 components work together.

---

## Files to Create

- `tests/integration/test_m2_e2e.py` - M2 end-to-end test
- `examples/run_workflow.py` - Runnable CLI demo
- `docs/milestone2_completion.md` - M2 completion report

---

## Acceptance Criteria

### E2E Test
- [ ] Load simple_research workflow from config
- [ ] Initialize all components (DB, LLM, tools, etc.)
- [ ] Execute workflow with real Ollama
- [ ] Verify data written to database
- [ ] Verify console displays correctly
- [ ] Assert workflow completes successfully
- [ ] Assert all metrics tracked (tokens, cost, duration)

### Demo Script
- [ ] CLI: `python examples/run_workflow.py configs/workflows/simple_research.yaml`
- [ ] Options: --prompt, --verbose, --output
- [ ] Display streaming console output
- [ ] Show final summary
- [ ] Query and display execution from database

### Completion Report
- [ ] List all M2 deliverables
- [ ] Show example execution
- [ ] Known limitations
- [ ] Next steps (M3)

---

## Implementation

```python
"""End-to-end M2 integration test."""

def test_m2_full_workflow():
    """Test complete workflow execution."""

    # 1. Initialize all systems
    db = init_database(":memory:")
    loader = init_config_loader("configs")
    tool_registry = ToolRegistry()
    tool_registry.auto_discover()

    # 2. Load workflow
    workflow_config = loader.load_workflow("simple_research")

    # 3. Compile to LangGraph
    compiler = LangGraphCompiler()
    graph = compiler.compile(workflow_config)

    # 4. Execute with tracking
    tracker = ExecutionTracker()
    visualizer = StreamingVisualizer()

    visualizer.start()
    result = graph.invoke({
        "input": "Research benefits of TypeScript",
        "tracker": tracker
    })
    visualizer.stop()

    # 5. Verify results
    assert result["status"] == "success"

    # 6. Query database
    with get_session() as session:
        workflow_exec = session.query(WorkflowExecution).first()
        assert workflow_exec is not None
        assert workflow_exec.total_tokens > 0
        assert workflow_exec.total_llm_calls > 0

    print("✅ M2 E2E TEST PASSED")
```

---

## Success Metrics

- [ ] E2E test passes with real Ollama
- [ ] Demo script runs successfully
- [ ] Console shows streaming updates
- [ ] Database contains full execution trace
- [ ] Completion report written

---

## Dependencies

- **Blocked by:** ALL M2 tasks (m2-01 through m2-07)
- **Blocks:** None (completes M2)

---

## M2 Completion Checklist

**You can say M2 is done when:**

- [ ] `pytest tests/integration/test_m2_e2e.py` passes
- [ ] `python examples/run_workflow.py configs/workflows/simple_research.yaml` runs
- [ ] Console displays real-time streaming updates
- [ ] Database query shows complete execution trace
- [ ] Can see: WorkflowExecution → StageExecution → AgentExecution → LLMCall + ToolExecution
- [ ] Agent actually calls Ollama and uses Calculator tool
- [ ] Tokens and cost tracked correctly
- [ ] All individual component tests pass

---

## Notes

- Requires Ollama running locally: `ollama pull llama3.2:3b`
- This is the definitive test that M2 is complete
- If this passes, we have a working autonomous agent system!
