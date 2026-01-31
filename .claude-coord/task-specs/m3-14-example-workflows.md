# Task: m3-14-example-workflows - Create Example Multi-Agent Workflows

**Priority:** HIGH (P1)  
**Effort:** 6 hours  
**Status:** pending  
**Owner:** unassigned

## Summary
Create example workflow configurations demonstrating M3 features (parallel execution, debate, merit-weighted resolution, quality gates).

## Files to Create
- `configs/workflows/multi_agent_research.yaml` - 3-agent parallel research
- `configs/workflows/debate_decision.yaml` - Debate strategy example
- `configs/stages/parallel_research_stage.yaml` - Parallel stage config
- `configs/stages/debate_stage.yaml` - Debate stage config
- `examples/run_multi_agent_workflow.py` - Demo script

## Examples to Include
1. **Parallel Research**: 3 agents (market, competitor, user research) execute in parallel, consensus synthesis
2. **Debate Decision**: 3 agents debate architecture choice, 2 rounds, convergence detection
3. **Merit-Weighted Resolution**: Conflicting agent outputs resolved by merit scores
4. **Quality Gates**: Stage with quality checks (min_confidence, min_findings)
5. **Adaptive Execution**: Mode switches from parallel to sequential

## Acceptance Criteria
- [ ] All examples runnable with `python examples/run_multi_agent_workflow.py <workflow>`
- [ ] README documentation for each example
- [ ] Clear comments explaining M3 features
- [ ] E2E tests pass for all examples
- [ ] Performance baseline documented

## Dependencies
- Blocked by: All M3 implementation tasks

## Notes
Examples are marketing material. Must be impressive and easy to understand.
