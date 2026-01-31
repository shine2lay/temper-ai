# Task: m2-06b-demo-script - Create CLI demo script for agent execution

**Priority:** CRITICAL
**Effort:** 1 hour
**Status:** pending
**Owner:** unassigned

---

## Summary

Create a simple CLI demo script (`examples/run_workflow.py`) that loads a workflow config, executes it with real Ollama, tracks to database, and displays results. This enables quick testing and demonstration of the full system.

---

## Context

This task extracts the CLI demo portion from m2-08-e2e-execution so it can be worked on in parallel. We need a way to actually run and test workflows before the full M2 integration test is complete.

---

## Files to Create

- `examples/run_workflow.py` - Main CLI demo script
- `examples/query_trace.py` - Script to query and display execution traces
- `examples/README.md` - How to use the demo scripts

---

## Acceptance Criteria

### CLI Demo Script
- [ ] Load workflow config from path (argument)
- [ ] Accept --prompt parameter for input
- [ ] Initialize all components (DB, config loader, tool registry)
- [ ] Compile workflow to LangGraph
- [ ] Execute workflow with tracking
- [ ] Display streaming console output
- [ ] Show final summary (tokens, cost, duration)
- [ ] Handle errors gracefully

### Query Trace Script
- [ ] Accept workflow_id or show latest
- [ ] Query WorkflowExecution with all relationships
- [ ] Display full trace tree
- [ ] Show all LLM calls and tool executions
- [ ] Display metrics summary

### Command-line Interface
- [ ] `python examples/run_workflow.py <config.yaml> --prompt "text"`
- [ ] Help messages for all commands
- [ ] Check Ollama is running (helpful error if not)

### Error Handling
- [ ] Check Ollama is running (give helpful error)
- [ ] Check config file exists
- [ ] Handle LLM errors gracefully
- [ ] Handle tool errors gracefully

---

## Success Metrics

- [ ] Demo script runs successfully
- [ ] Console shows streaming updates
- [ ] Database contains full trace
- [ ] Query script displays trace
- [ ] Error messages are helpful

---

## Dependencies

- **Blocked by:** m2-04-agent-runtime, m2-05-langgraph-basic, m2-06-obs-hooks
- **Blocks:** None (enables demo/testing)

---

## Notes

- Keep script simple - for demo/testing only
- Focus on developer experience
- Can work in parallel with m2-06-obs-hooks
- Once this + m2-06 done, full demo possible
