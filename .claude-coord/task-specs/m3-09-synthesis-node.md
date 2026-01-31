# Task: m3-09-synthesis-node - Implement Synthesis Node

**Priority:** CRITICAL (P0)  
**Effort:** 10 hours  
**Status:** pending  
**Owner:** unassigned

## Summary
Add synthesis node to LangGraph compiler that loads collaboration strategy from config, calls strategy.synthesize(), and stores result in stage output. Completes the parallel execution pipeline.

## Files to Modify
- `src/compiler/langgraph_compiler.py` - Add synthesis node creation

## Acceptance Criteria
- [ ] Load collaboration strategy from stage config via registry
- [ ] Call `strategy.synthesize(agent_outputs, config)`
- [ ] Convert agent outputs to AgentOutput objects
- [ ] Track synthesis in observability (collaboration_events table)
- [ ] Store SynthesisResult in stage output
- [ ] Handle synthesis failures gracefully (escalate or fallback)
- [ ] Pass synthesized decision to next stage
- [ ] E2E test with Consensus and Debate strategies

## Implementation
```python
def _create_synthesis_node(stage_config):
    def synthesize(state):
        # Get agent outputs from parallel execution
        agent_outputs = state["agent_outputs"]
        
        # Load strategy
        strategy = strategy_registry.get_strategy_from_config(stage_config)
        
        # Synthesize
        result = strategy.synthesize(agent_outputs, config)
        
        # Track in observability
        tracker.track_collaboration_event(...)
        
        # Store result
        state["stage_outputs"][stage_name] = result.decision
        return state
    return synthesize
```

## Dependencies
- Blocked by: m3-07-parallel-stage-execution, m3-08-multi-agent-state, m3-06-strategy-registry
- Blocks: None (completes core parallel execution)

## Notes
This is the critical integration point that makes all M3 collaboration work. Must handle both parallel and sequential agent execution.
