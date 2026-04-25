"""Worker protocol schema tests — type construction + serialization round-trip.

Phase 0: protocol types are wire contracts. They must be constructible from
realistic inputs and round-trip through JSON without loss. Anything fancier
(behavior, validation rules) is layered on later.
"""



from temper_ai.worker_proto import (
    ChunkEvent,
    EventEnvelope,
    MilestoneEventType,
    ProcessHandle,
    RunRequest,
    RunStatus,
    SpawnerKind,
    WorkflowRunSpec,
)


class TestRunStatus:
    def test_enum_values_match_doc(self):
        assert RunStatus.queued == "queued"
        assert RunStatus.running == "running"
        assert RunStatus.completed == "completed"
        assert RunStatus.failed == "failed"
        assert RunStatus.cancelled == "cancelled"
        assert RunStatus.orphaned == "orphaned"


class TestWorkflowRunSpec:
    def test_minimal_construction(self):
        spec = WorkflowRunSpec(
            execution_id="abc-123",
            workflow_name="garmin",
            workspace_path="/workspaces/garmin/main",
        )
        assert spec.execution_id == "abc-123"
        assert spec.inputs == {}
        assert spec.max_attempts == 1
        assert spec.deadline_seconds is None

    def test_full_construction(self):
        spec = WorkflowRunSpec(
            execution_id="abc-123",
            workflow_name="garmin",
            workspace_path="/workspaces/garmin/main",
            inputs={"target": "build app"},
            max_attempts=3,
            deadline_seconds=1800,
        )
        assert spec.inputs["target"] == "build app"
        assert spec.max_attempts == 3
        assert spec.deadline_seconds == 1800

    def test_json_roundtrip(self):
        spec = WorkflowRunSpec(
            execution_id="abc-123",
            workflow_name="garmin",
            workspace_path="/workspaces/garmin/main",
            inputs={"a": 1, "b": "two"},
        )
        as_json = spec.model_dump_json()
        restored = WorkflowRunSpec.model_validate_json(as_json)
        assert restored == spec


class TestRunRequest:
    def test_minimal_request(self):
        req = RunRequest(workflow="garmin")
        assert req.workflow == "garmin"
        assert req.workspace_path is None
        assert req.inputs == {}
        assert req.max_attempts == 1


class TestProcessHandle:
    def test_subprocess_handle(self):
        h = ProcessHandle(kind=SpawnerKind.subprocess, handle="12345")
        assert h.kind == SpawnerKind.subprocess
        assert h.handle == "12345"
        assert h.spawned_at is not None

    def test_docker_handle_with_metadata(self):
        h = ProcessHandle(
            kind=SpawnerKind.docker,
            handle="abc123def456",
            metadata={"image": "temper/worker:latest", "container_name": "run-abc"},
        )
        assert h.metadata["image"] == "temper/worker:latest"

    def test_json_roundtrip(self):
        h = ProcessHandle(kind=SpawnerKind.subprocess, handle="42")
        restored = ProcessHandle.model_validate_json(h.model_dump_json())
        assert restored.kind == h.kind
        assert restored.handle == h.handle


class TestSpawnerKind:
    def test_all_known_kinds_string_safe(self):
        for kind in SpawnerKind:
            assert isinstance(kind.value, str)


class TestMilestoneEventType:
    def test_event_types_match_existing_temper_format(self):
        # These string values match what temper has been writing to the events
        # table historically — preserved so existing analytics scripts and the
        # dashboard event timeline keep working.
        assert MilestoneEventType.workflow_started == "workflow.started"
        assert MilestoneEventType.agent_started == "agent.started"
        assert MilestoneEventType.agent_completed == "agent.completed"
        assert MilestoneEventType.llm_call_started == "llm.call.started"
        assert MilestoneEventType.dispatch_applied == "dispatch.applied"


class TestEventEnvelope:
    def test_minimal_event(self):
        e = EventEnvelope(
            type=MilestoneEventType.agent_started,
            execution_id="abc-123",
        )
        assert e.execution_id == "abc-123"
        assert e.data == {}
        assert e.timestamp is not None

    def test_event_with_data(self):
        e = EventEnvelope(
            type=MilestoneEventType.llm_call_completed,
            execution_id="abc-123",
            parent_id="parent-42",
            status="completed",
            data={"cost_usd": 0.42, "tokens": 1500},
        )
        assert e.parent_id == "parent-42"
        assert e.data["cost_usd"] == 0.42

    def test_accepts_string_type_for_forward_compat(self):
        # Allows new event types to be added without breaking the protocol
        e = EventEnvelope(type="custom.future_event", execution_id="abc")
        assert e.type == "custom.future_event"

    def test_json_roundtrip(self):
        e = EventEnvelope(
            type=MilestoneEventType.workflow_started,
            execution_id="exec-7",
            data={"workflow_name": "garmin"},
        )
        restored = EventEnvelope.model_validate_json(e.model_dump_json())
        assert restored.execution_id == e.execution_id
        assert restored.data == e.data


class TestChunkEvent:
    def test_text_chunk(self):
        c = ChunkEvent(llm_call_id="call-1", chunk_text="Hello, ")
        assert c.chunk_kind == "text"
        assert c.chunk_text == "Hello, "

    def test_tool_use_chunk(self):
        c = ChunkEvent(
            llm_call_id="call-1",
            chunk_kind="tool_use",
            chunk_text="",
            metadata={"tool_name": "Bash", "tool_input": {"command": "ls"}},
        )
        assert c.chunk_kind == "tool_use"
        assert c.metadata["tool_name"] == "Bash"

    def test_done_chunk(self):
        c = ChunkEvent(llm_call_id="call-1", chunk_kind="done", token_count=1500)
        assert c.token_count == 1500

    def test_json_roundtrip(self):
        c = ChunkEvent(llm_call_id="call-1", chunk_text="hello")
        restored = ChunkEvent.model_validate_json(c.model_dump_json())
        assert restored.llm_call_id == c.llm_call_id
        assert restored.chunk_text == c.chunk_text
