# Task: Create end-to-end integration test suite

## Summary

class TestFullWorkflowE2E:
    def test_three_stage_research_workflow(self, db, mock_llm):
        workflow_config = WorkflowConfig(stages=[
            StageConfig(name='research', agents=[...]),
            StageConfig(name='analyze', agents=[...]),
            StageConfig(name='synthesize', agents=[...])
        ])
        result = execute_workflow(workflow_config, {'query': 'test'})
        assert result.stages_completed == 3
        assert result.status == 'completed'

**Priority:** CRITICAL  
**Estimated Effort:** 24.0 hours  
**Module:** Integration  
**Issues Addressed:** 3

---

## Files to Create

- `tests/integration/test_e2e_workflows.py` - Full multi-stage workflow E2E tests
- `tests/integration/test_checkpoint_resume.py` - Checkpoint and resume scenarios
- `tests/integration/test_error_propagation_e2e.py` - Error propagation through entire stack

---

## Files to Modify

_None_

---

## Acceptance Criteria


### Core Functionality

- [ ] Full 3-stage workflow execution (research → analyze → synthesize)
- [ ] Checkpoint at each stage, resume from any point
- [ ] Real agents with mocked LLM responses
- [ ] Tool execution in workflow context
- [ ] Error propagation: tool → agent → stage → workflow
- [ ] Timeout cascading through layers
- [ ] Observability tracking for full workflow

### Testing

- [ ] 300+ LOC of E2E tests
- [ ] Test success case, failure cases, timeout cases
- [ ] Verify database state after each stage
- [ ] Test with parallel and sequential execution


---

## Implementation Details

class TestFullWorkflowE2E:
    def test_three_stage_research_workflow(self, db, mock_llm):
        workflow_config = WorkflowConfig(stages=[
            StageConfig(name='research', agents=[...]),
            StageConfig(name='analyze', agents=[...]),
            StageConfig(name='synthesize', agents=[...])
        ])
        result = execute_workflow(workflow_config, {'query': 'test'})
        assert result.stages_completed == 3
        assert result.status == 'completed'

---

## Test Strategy

Use real workflow configs with mocked LLM. Test checkpoint/resume at each stage. Verify observability tracking. Test error scenarios.

---

## Success Metrics

- [ ] Multi-stage workflows tested end-to-end
- [ ] Checkpoint/resume verified
- [ ] Error propagation correct
- [ ] Integration coverage >30%

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** WorkflowExecutor, StageCompiler, ObservabilityTracker, CheckpointManager

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#23-end-to-end-integration-tests-missing-severity-critical

---

## Notes

Essential for validating component integration. Currently missing comprehensive E2E tests.
