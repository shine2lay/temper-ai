# Task: m2-06-obs-hooks - Wire agent execution to observability database

**Priority:** HIGH
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Hook agent execution into the observability database. Every LLM call, tool execution, and agent decision should be tracked in real-time to the database tables created in M1.

---

## Files to Create

- `src/observability/hooks.py` - Execution hooks/callbacks
- `src/observability/tracker.py` - ExecutionTracker class
- `tests/test_observability/test_hooks.py` - Hook tests

---

## Acceptance Criteria

### Tracking Hooks
- [x] - [ ] Hook into agent.execute() to create AgentExecution record
- [x] - [x] - [ ] Hook into LLM calls to create LLMCall records
- [x] - [ ] Hook into tool calls to create ToolExecution records
- [x] - [ ] Create WorkflowExecution and StageExecution records
- [x] - [ ] Track start_time, end_time, duration for all levels
- [x] - [ ] Track tokens, cost at all levels
- [x] - [ ] Track status (running, success, failed)

### Data Flow
- [x] - [ ] Workflow start → create WorkflowExecution (status=running)
- [x] - [ ] Stage start → create StageExecution
- [x] - [ ] Agent start → create AgentExecution
- [x] - [ ] LLM call → create LLMCall record
- [x] - [ ] Tool call → create ToolExecution record
- [x] - [ ] Agent end → update AgentExecution (status, duration, metrics)
- [x] - [ ] Stage end → update StageExecution
- [x] - [ ] Workflow end → update WorkflowExecution

### Testing
- [x] - [ ] Test data is written to database
- [x] - [ ] Test metrics are calculated correctly
- [x] - [ ] Test relationships are set up correctly
- [x] - [ ] Coverage > 85%

---

## Implementation

```python
"""Observability hooks for tracking execution."""
from contextlib import contextmanager
from datetime import datetime
from src.observability.database import get_session
from src.observability.models import (
    WorkflowExecution, AgentExecution, LLMCall, ToolExecution
)


class ExecutionTracker:
    """Tracks execution and writes to observability DB."""

    @contextmanager
    def track_agent(self, agent_name: str, stage_id: str):
        """Track agent execution."""
        agent_exec = AgentExecution(
            id=str(uuid.uuid4()),
            stage_execution_id=stage_id,
            agent_name=agent_name,
            status="running",
            start_time=datetime.utcnow()
        )

        with get_session() as session:
            session.add(agent_exec)

        try:
            yield agent_exec
            # Success
            agent_exec.status = "success"
            agent_exec.end_time = datetime.utcnow()
            agent_exec.duration_seconds = (
                agent_exec.end_time - agent_exec.start_time
            ).total_seconds()
        except Exception as e:
            # Failure
            agent_exec.status = "failed"
            agent_exec.error_message = str(e)
        finally:
            with get_session() as session:
                session.add(agent_exec)

    def track_llm_call(self, agent_id: str, llm_response: LLMResponse):
        """Track LLM call."""
        llm_call = LLMCall(
            id=str(uuid.uuid4()),
            agent_execution_id=agent_id,
            provider=llm_response.provider,
            model=llm_response.model,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
            total_tokens=llm_response.total_tokens,
            estimated_cost_usd=llm_response.estimated_cost_usd,
            latency_ms=llm_response.latency_ms,
            status="success",
            start_time=datetime.utcnow()
        )

        with get_session() as session:
            session.add(llm_call)
```

---

## Success Metrics

- [x] - [ ] All execution data tracked to database
- [x] - [ ] Metrics calculated correctly
- [x] - [ ] Relationships work (can query workflow → stages → agents → LLM/tools)
- [x] - [ ] Tests pass > 85%

---

## Dependencies

- **Blocked by:** m2-04-agent-runtime, m1-01-observability-db
- **Blocks:** m2-08-e2e-execution
- **Works with:** m2-07-console-streaming (uses same data)

---

## Notes

- Use context managers for automatic start/end tracking
- Write to database asynchronously if performance is an issue
- Calculate aggregate metrics (total tokens, cost) when closing workflow
