# Task: m3-08-multi-agent-state - Multi-Agent Stage State Management

**Priority:** HIGH (P1)  
**Effort:** 8 hours  
**Status:** pending  
**Owner:** unassigned

## Summary
Update StageState schema to track individual agent outputs, execution status, and metrics during parallel execution. Handle partial failures with min_successful_agents enforcement.

## Files to Modify
- `src/compiler/langgraph_compiler.py` - Update WorkflowState schema
- `src/compiler/schemas.py` - Add MultiAgentStageState model

## Acceptance Criteria
- [ ] `agent_outputs: Dict[agent_name, output]` in state
- [ ] `agent_statuses: Dict[agent_name, "success"|"failed"]` tracking
- [ ] `agent_metrics: Dict[agent_name, metrics]` (tokens, cost, duration)
- [ ] Aggregate metrics (total_tokens, total_cost, total_duration)
- [ ] `min_successful_agents` enforcement
- [ ] Graceful handling of partial failures
- [ ] Track which agents succeeded/failed in observability
- [ ] Tests for all failure scenarios

## Dependencies
- Blocked by: m3-07-parallel-stage-execution
- Blocks: m3-09-synthesis-node

## Notes
State management must support both parallel and sequential execution modes. Track detailed metrics for cost analysis and debugging.
