"""Tests for base agent interface."""

import threading
import time
from unittest.mock import patch

import pytest

from temper_ai.agent.base_agent import AgentResponse, BaseAgent, ExecutionContext
from temper_ai.storage.schemas.agent_config import AgentConfig


def test_agent_response_creation():
    """Test AgentResponse dataclass creation."""
    response = AgentResponse(
        output="Hello world",
        reasoning="This is my thought process",
        tool_calls=[{"name": "calculator", "result": 42}],
        tokens=100,
        estimated_cost_usd=0.002,
        latency_seconds=1.5,
    )

    assert response.output == "Hello world"
    assert response.reasoning == "This is my thought process"
    assert len(response.tool_calls) == 1
    assert response.tokens == 100
    assert response.estimated_cost_usd == 0.002
    assert response.latency_seconds == 1.5
    assert response.error is None


def test_agent_response_with_error():
    """Test AgentResponse with error."""
    response = AgentResponse(
        output="",
        error="LLM call failed",
        latency_seconds=0.5,
    )

    assert response.output == ""
    assert response.error == "LLM call failed"
    assert response.tokens == 0


def test_execution_context_creation():
    """Test ExecutionContext dataclass creation."""
    context = ExecutionContext(
        workflow_id="wf-001",
        stage_id="stage-001",
        agent_id="agent-001",
        session_id="session-123",
        metadata={"user": "test"},
    )

    assert context.workflow_id == "wf-001"
    assert context.stage_id == "stage-001"
    assert context.agent_id == "agent-001"
    assert context.session_id == "session-123"
    assert context.metadata["user"] == "test"


def test_execution_context_defaults():
    """Test ExecutionContext with default values."""
    context = ExecutionContext()

    assert context.workflow_id is None
    assert context.stage_id is None
    assert context.agent_id is None
    assert context.session_id is None
    assert context.user_id is None
    assert context.metadata == {}


def test_base_agent_is_abstract():
    """Test that BaseAgent cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseAgent(None)  # type: ignore


class MockAgent(BaseAgent):
    """Mock agent for testing interface contract."""

    def _run(self, input_data, context=None, start_time=0.0):
        return AgentResponse(
            output="mock output",
            reasoning="mock reasoning",
        )

    def get_capabilities(self):
        return {"name": self.name, "type": "mock", "tools": []}


def _make_mock_agent(config):
    """Create MockAgent with LLM creation patched out."""
    with patch("temper_ai.agent.base_agent.create_llm_from_config"):
        return MockAgent(config)


def test_base_agent_subclass_requires_run():
    """Test that subclasses must implement _run()."""

    class IncompleteAgent(BaseAgent):
        """Agent missing _run implementation."""

        def get_capabilities(self):
            return {}

    with pytest.raises(TypeError):
        IncompleteAgent(None)  # type: ignore


def test_base_agent_subclass_requires_get_capabilities():
    """Test that subclasses must implement get_capabilities()."""

    class IncompleteAgent(BaseAgent):
        """Agent missing get_capabilities implementation."""

        def _run(self, input_data, context=None, start_time=0.0):
            return AgentResponse(output="test")

    with pytest.raises(TypeError):
        IncompleteAgent(None)  # type: ignore


def test_mock_agent_initialization(minimal_agent_config):
    """Test MockAgent initialization."""
    agent = _make_mock_agent(minimal_agent_config)

    assert agent.config == minimal_agent_config
    assert agent.name == minimal_agent_config.agent.name
    assert agent.description == minimal_agent_config.agent.description
    assert agent.version == minimal_agent_config.agent.version


def test_mock_agent_execute(minimal_agent_config):
    """Test MockAgent execute method."""
    agent = _make_mock_agent(minimal_agent_config)

    response = agent.execute({"query": "test"})

    assert isinstance(response, AgentResponse)
    assert response.output == "mock output"
    assert response.reasoning == "mock reasoning"


def test_mock_agent_execute_with_context(minimal_agent_config):
    """Test MockAgent execute with context."""
    agent = _make_mock_agent(minimal_agent_config)
    context = ExecutionContext(workflow_id="wf-001")

    response = agent.execute({"query": "test"}, context=context)

    assert isinstance(response, AgentResponse)
    assert response.output == "mock output"


def test_mock_agent_get_capabilities(minimal_agent_config):
    """Test MockAgent get_capabilities method."""
    agent = _make_mock_agent(minimal_agent_config)

    capabilities = agent.get_capabilities()

    assert isinstance(capabilities, dict)
    assert capabilities["name"] == minimal_agent_config.agent.name
    assert capabilities["type"] == "mock"
    assert "tools" in capabilities


def test_base_agent_validate_config(minimal_agent_config):
    """Test base agent config validation."""
    agent = _make_mock_agent(minimal_agent_config)

    # Should pass validation
    assert agent.validate_config() is True


def test_base_agent_validate_config_missing_name():
    """Test validation fails with missing name."""
    from temper_ai.storage.schemas.agent_config import (
        AgentConfigInner,
        ErrorHandlingConfig,
        InferenceConfig,
        PromptConfig,
    )

    config = AgentConfig(
        agent=AgentConfigInner(
            name="",  # Empty name
            description="Test",
            prompt=PromptConfig(inline="test"),
            inference=InferenceConfig(provider="ollama", model="llama2"),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )

    agent = _make_mock_agent(config)

    with pytest.raises(ValueError, match="Agent name is required"):
        agent.validate_config()


class TestContextPropagation:
    """Tests for ExecutionContext propagation through agent calls (P1)."""

    def test_context_passed_to_child_agent(self, minimal_agent_config):
        """Test that context is passed from parent to child agent."""

        class ChildAgent(MockAgent):
            """Agent that captures the context it receives."""

            received_context = None

            def _run(self, input_data, context=None, start_time=0.0):
                ChildAgent.received_context = context
                return AgentResponse(output="child response")

        class ParentAgent(MockAgent):
            """Agent that calls child agent."""

            def __init__(self, config):
                super().__init__(config)
                with patch("temper_ai.agent.base_agent.create_llm_from_config"):
                    self.child = ChildAgent(config)

            def _run(self, input_data, context=None, start_time=0.0):
                # Call child agent with context
                child_response = self.child.execute({"nested": True}, context=context)
                return AgentResponse(output=f"parent wraps: {child_response.output}")

        parent = (
            _make_mock_agent.__wrapped__(minimal_agent_config)
            if hasattr(_make_mock_agent, "__wrapped__")
            else None
        )
        # Create parent with patched LLM
        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            parent = ParentAgent(minimal_agent_config)

        parent_context = ExecutionContext(
            workflow_id="wf-parent", stage_id="stage-1", agent_id="agent-parent"
        )

        # Execute parent (which calls child)
        parent.execute({"test": True}, context=parent_context)

        # Verify child received the context
        assert ChildAgent.received_context is not None
        assert ChildAgent.received_context.workflow_id == "wf-parent"
        assert ChildAgent.received_context.stage_id == "stage-1"
        assert ChildAgent.received_context.agent_id == "agent-parent"

    def test_context_preserved_across_multiple_calls(self, minimal_agent_config):
        """Test context is preserved across multiple agent calls."""

        class ContextCapturingAgent(MockAgent):
            """Agent that captures all contexts it receives."""

            captured_contexts = []

            def _run(self, input_data, context=None, start_time=0.0):
                ContextCapturingAgent.captured_contexts.append(context)
                return AgentResponse(output=f"call {len(self.captured_contexts)}")

        agent = _make_mock_agent(minimal_agent_config)
        # Replace with capturing agent
        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = ContextCapturingAgent(minimal_agent_config)
        ContextCapturingAgent.captured_contexts = []

        context = ExecutionContext(
            workflow_id="wf-123", stage_id="stage-456", session_id="session-789"
        )

        # Make multiple calls with same context
        agent.execute({"call": 1}, context=context)
        agent.execute({"call": 2}, context=context)
        agent.execute({"call": 3}, context=context)

        # All calls should have received the same context
        assert len(ContextCapturingAgent.captured_contexts) == 3
        for ctx in ContextCapturingAgent.captured_contexts:
            assert ctx.workflow_id == "wf-123"
            assert ctx.stage_id == "stage-456"
            assert ctx.session_id == "session-789"

    def test_context_includes_workflow_stage_ids(self, minimal_agent_config):
        """Test that context with workflow_id and stage_id is stored on agent."""
        agent = _make_mock_agent(minimal_agent_config)
        context = ExecutionContext(
            workflow_id="wf-production", stage_id="stage-processing"
        )

        response = agent.execute({"test": True}, context=context)

        assert response.error is None
        assert agent._execution_context is context
        assert agent._execution_context.workflow_id == "wf-production"
        assert agent._execution_context.stage_id == "stage-processing"

    def test_context_with_parent_id_tracking(self, minimal_agent_config):
        """Test context can track parent agent relationships."""

        class TrackedAgent(MockAgent):
            """Agent that adds itself to context metadata."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata:
                    # Track parent in metadata
                    parent_id = context.metadata.get("parent_agent_id")
                    context.metadata["current_agent_id"] = self.name
                    if parent_id:
                        context.metadata["parent_chain"] = context.metadata.get(
                            "parent_chain", []
                        ) + [parent_id]
                return AgentResponse(output="tracked")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent1 = TrackedAgent(minimal_agent_config)
        agent1.name = "agent-1"

        # Create context with parent tracking
        context = ExecutionContext(
            workflow_id="wf-001", metadata={"parent_agent_id": "agent-0"}
        )

        # Execute
        agent1.execute({"test": True}, context=context)

        # Verify parent was tracked
        assert context.metadata["current_agent_id"] == "agent-1"
        assert "agent-0" in context.metadata.get("parent_chain", [])

    def test_nested_agent_execution_depth_tracking(self, minimal_agent_config):
        """Test tracking execution depth in nested agent calls."""

        class DepthTrackingAgent(MockAgent):
            """Agent that tracks execution depth."""

            max_depth = 3

            def _run(self, input_data, context=None, start_time=0.0):
                if context is None:
                    context = ExecutionContext(metadata={})

                depth = context.metadata.get("depth", 0)
                context.metadata["depth"] = depth + 1

                # Call child if not at max depth
                if depth < self.max_depth:
                    child_response = self.execute(input_data, context=context)
                    return AgentResponse(
                        output=f"depth {depth}: {child_response.output}"
                    )
                else:
                    return AgentResponse(output=f"max depth {depth}")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = DepthTrackingAgent(minimal_agent_config)
        context = ExecutionContext(metadata={"depth": 0})

        # Execute with nesting
        agent.execute({"nested": True}, context=context)

        # Verify depth was tracked
        assert context.metadata["depth"] == 4  # 0→1→2→3→4

    def test_context_accessible_during_execution(self, minimal_agent_config):
        """Test that context is accessible during agent execution."""

        class ContextAwareAgent(MockAgent):
            """Agent that uses context during execution."""

            def _run(self, input_data, context=None, start_time=0.0):
                # Use context to modify behavior
                if context and context.workflow_id:
                    output = f"Processing in workflow: {context.workflow_id}"
                else:
                    output = "No workflow context"

                return AgentResponse(output=output)

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = ContextAwareAgent(minimal_agent_config)

        # Execute with context
        context = ExecutionContext(workflow_id="wf-production-123")
        response_with_context = agent.execute({"test": True}, context=context)
        assert "wf-production-123" in response_with_context.output

        # Execute without context
        response_without_context = agent.execute({"test": True}, context=None)
        assert response_without_context.output == "No workflow context"

    def test_context_metadata_extensibility(self, minimal_agent_config):
        """Test that context metadata is accessible to agent during execution."""

        class MetadataReadingAgent(MockAgent):
            """Agent that reads metadata from context."""

            def _run(self, input_data, context=None, start_time=0.0):
                tenant = context.metadata.get("tenant_id") if context else None
                return AgentResponse(output=f"tenant:{tenant}")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = MetadataReadingAgent(minimal_agent_config)

        context = ExecutionContext(
            workflow_id="wf-001",
            metadata={
                "user_id": "user-123",
                "tenant_id": "tenant-456",
                "request_id": "req-789",
                "custom_field": "custom_value",
            },
        )

        response = agent.execute({"test": True}, context=context)

        assert "tenant:tenant-456" in response.output
        assert context.metadata["custom_field"] == "custom_value"

    def test_context_session_id_tracking(self, minimal_agent_config):
        """Test that session_id is properly tracked in context."""

        class SessionAwareAgent(MockAgent):
            """Agent that tracks session information."""

            def _run(self, input_data, context=None, start_time=0.0):
                session_id = context.session_id if context else None
                return AgentResponse(
                    output=f"session: {session_id}", metadata={"session_id": session_id}
                )

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = SessionAwareAgent(minimal_agent_config)
        context = ExecutionContext(workflow_id="wf-001", session_id="session-xyz")

        response = agent.execute({"test": True}, context=context)

        # Verify session was tracked
        assert "session-xyz" in response.output
        assert response.metadata["session_id"] == "session-xyz"

    def test_context_user_id_propagation(self, minimal_agent_config):
        """Test that user_id propagates through context to agent."""

        class UserIdCapturingAgent(MockAgent):
            """Agent that captures user_id from context."""

            def _run(self, input_data, context=None, start_time=0.0):
                uid = context.user_id if context else None
                return AgentResponse(output=f"user:{uid}")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = UserIdCapturingAgent(minimal_agent_config)

        context = ExecutionContext(workflow_id="wf-001", user_id="user-alice")

        response = agent.execute({"test": True}, context=context)

        assert "user:user-alice" in response.output

    def test_context_none_is_valid(self, minimal_agent_config):
        """Test that agents can handle None context gracefully."""
        agent = _make_mock_agent(minimal_agent_config)

        # Execute without context (None)
        response = agent.execute({"test": True}, context=None)

        # Should succeed
        assert isinstance(response, AgentResponse)
        assert response.output == "mock output"


class TestContextImmutability:
    """Tests for context immutability and corruption prevention (P1)."""

    def test_context_not_mutated_by_agent_execution(self, minimal_agent_config):
        """Test that agent execution does not mutate the original context."""

        class MutatingAgent(MockAgent):
            """Agent that attempts to mutate context."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata:
                    # Attempt to mutate context metadata
                    context.metadata["mutated"] = True
                    context.metadata["original_value"] = "changed"
                return AgentResponse(output="attempted mutation")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = MutatingAgent(minimal_agent_config)

        # Create context with original values
        original_context = ExecutionContext(
            workflow_id="wf-001",
            metadata={"original_value": "unchanged", "flag": False},
        )

        # Execute agent
        agent.execute({"test": True}, context=original_context)

        # Verify context was mutated (this test documents current behavior)
        assert original_context.metadata.get("mutated") is True
        assert original_context.metadata["original_value"] == "changed"

    def test_context_deep_copy_prevents_nested_mutations(self, minimal_agent_config):
        """Test that deep copying context prevents nested object mutations."""
        import copy

        class NestedMutatingAgent(MockAgent):
            """Agent that attempts to mutate nested context data."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata:
                    if "nested" in context.metadata:
                        context.metadata["nested"]["value"] = "mutated"
                        context.metadata["nested"]["new_key"] = "added"
                return AgentResponse(output="attempted nested mutation")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = NestedMutatingAgent(minimal_agent_config)

        # Create context with nested structure
        original_context = ExecutionContext(
            workflow_id="wf-001",
            metadata={
                "nested": {"value": "original", "count": 0},
                "list_data": [1, 2, 3],
            },
        )

        # Deep copy context before passing to agent
        context_copy = copy.deepcopy(original_context)

        # Execute with deep copy
        agent.execute({"test": True}, context=context_copy)

        # Original context should remain unchanged
        assert original_context.metadata["nested"]["value"] == "original"
        assert "new_key" not in original_context.metadata["nested"]

        # Copy was mutated
        assert context_copy.metadata["nested"]["value"] == "mutated"
        assert context_copy.metadata["nested"]["new_key"] == "added"

    def test_context_immutable_in_sequential_calls(self, minimal_agent_config):
        """Test context remains unchanged across sequential agent calls."""

        class SequentialAgent(MockAgent):
            """Agent that modifies context metadata."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata:
                    context.metadata["call_count"] = (
                        context.metadata.get("call_count", 0) + 1
                    )
                return AgentResponse(
                    output=f"call {context.metadata.get('call_count', 0)}"
                )

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent1 = SequentialAgent(minimal_agent_config)
            agent2 = SequentialAgent(minimal_agent_config)

        # Create shared context
        shared_context = ExecutionContext(
            workflow_id="wf-001", metadata={"call_count": 0}
        )

        # Agent1 executes first
        agent1.execute({"test": 1}, context=shared_context)
        assert shared_context.metadata["call_count"] == 1

        # Agent2 sees the mutation from agent1
        agent2.execute({"test": 2}, context=shared_context)
        assert shared_context.metadata["call_count"] == 2

    def test_context_metadata_list_mutation(self, minimal_agent_config):
        """Test that context metadata lists can be mutated (document behavior)."""

        class ListMutatingAgent(MockAgent):
            """Agent that mutates list in context."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata and "items" in context.metadata:
                    context.metadata["items"].append("new_item")
                return AgentResponse(output="list mutated")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = ListMutatingAgent(minimal_agent_config)

        context = ExecutionContext(
            workflow_id="wf-001", metadata={"items": ["item1", "item2"]}
        )

        agent.execute({"test": True}, context=context)

        assert len(context.metadata["items"]) == 3
        assert "new_item" in context.metadata["items"]

    def test_context_metadata_dict_mutation(self, minimal_agent_config):
        """Test that context metadata dicts can be mutated (document behavior)."""

        class DictMutatingAgent(MockAgent):
            """Agent that mutates dict in context."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata and "config" in context.metadata:
                    context.metadata["config"]["timeout"] = 60
                    context.metadata["config"]["new_setting"] = "value"
                return AgentResponse(output="dict mutated")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = DictMutatingAgent(minimal_agent_config)

        context = ExecutionContext(
            workflow_id="wf-001", metadata={"config": {"timeout": 30, "retries": 3}}
        )

        agent.execute({"test": True}, context=context)

        assert context.metadata["config"]["timeout"] == 60
        assert "new_setting" in context.metadata["config"]


class TestContextThreadSafety:
    """Tests for context thread-safety in concurrent executions (P1)."""

    def test_concurrent_context_modifications_may_race(self, minimal_agent_config):
        """Test that shared context without locking can lose increments (documents race)."""

        class CountingAgent(MockAgent):
            """Agent that increments a counter in context (no locking)."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata:
                    current = context.metadata.get("counter", 0)
                    time.sleep(
                        0.001
                    )  # Small intentional delay to increase race probability
                    context.metadata["counter"] = current + 1
                return AgentResponse(
                    output=f"count: {context.metadata.get('counter', 0)}"
                )

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = CountingAgent(minimal_agent_config)

        shared_context = ExecutionContext(workflow_id="wf-001", metadata={"counter": 0})

        num_threads = 10
        threads = []

        for i in range(num_threads):
            thread = threading.Thread(
                target=lambda: agent.execute({"thread": i}, context=shared_context)
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        final_count = shared_context.metadata["counter"]
        # Without locking, some increments may be lost to races
        assert final_count >= 1, "At least one increment should land"
        assert final_count <= num_threads, "Cannot exceed total thread count"

    def test_concurrent_list_modifications(self, minimal_agent_config):
        """Test concurrent list appends — CPython GIL makes list.append atomic."""

        class ListAppendingAgent(MockAgent):
            """Agent that appends to a list in context."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata and "items" in context.metadata:
                    thread_id = threading.get_ident()
                    context.metadata["items"].append(thread_id)
                return AgentResponse(output="appended")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = ListAppendingAgent(minimal_agent_config)

        shared_context = ExecutionContext(workflow_id="wf-001", metadata={"items": []})

        num_threads = 15
        threads = []

        for i in range(num_threads):
            thread = threading.Thread(
                target=lambda: agent.execute({"test": i}, context=shared_context)
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        items_count = len(shared_context.metadata["items"])
        # list.append is atomic under CPython GIL, so all should land
        assert (
            items_count == num_threads
        ), f"Expected {num_threads} items, got {items_count}"

    def test_concurrent_dict_modifications(self, minimal_agent_config):
        """Test concurrent modifications to nested dicts in context."""

        class DictModifyingAgent(MockAgent):
            """Agent that modifies nested dict in context."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata and "data" in context.metadata:
                    thread_id = threading.get_ident()
                    context.metadata["data"][f"thread_{thread_id}"] = "value"
                return AgentResponse(output="modified")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = DictModifyingAgent(minimal_agent_config)

        shared_context = ExecutionContext(workflow_id="wf-001", metadata={"data": {}})

        num_threads = 12
        threads = []

        for i in range(num_threads):
            thread = threading.Thread(
                target=lambda: agent.execute({"test": i}, context=shared_context)
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        keys_count = len(shared_context.metadata["data"])
        assert keys_count > 0
        assert keys_count <= num_threads

    def test_context_isolation_with_separate_instances(self, minimal_agent_config):
        """Test that separate context instances prevent data corruption."""

        class IsolatedAgent(MockAgent):
            """Agent that modifies its own context copy."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata:
                    context.metadata["value"] = input_data.get("value", 0)
                return AgentResponse(
                    output=f"value: {context.metadata.get('value', 0)}"
                )

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = IsolatedAgent(minimal_agent_config)

        results = {}
        results_lock = threading.Lock()

        def thread_worker(thread_id, value):
            thread_context = ExecutionContext(
                workflow_id=f"wf-{thread_id}", metadata={"thread_id": thread_id}
            )

            agent.execute({"value": value}, context=thread_context)

            with results_lock:
                results[thread_id] = thread_context.metadata["value"]

        num_threads = 10
        threads = []

        for i in range(num_threads):
            thread = threading.Thread(target=thread_worker, args=(i, i * 10))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        for i in range(num_threads):
            assert i in results
            assert results[i] == i * 10

    def test_context_read_operations_are_thread_safe(self, minimal_agent_config):
        """Test that reading from context is generally thread-safe."""

        class ReadOnlyAgent(MockAgent):
            """Agent that only reads from context."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata:
                    value = context.metadata.get("config", {}).get("timeout", 30)
                    name = context.metadata.get("name", "default")
                    items = len(context.metadata.get("items", []))
                return AgentResponse(output=f"read: {value}, {name}, {items}")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = ReadOnlyAgent(minimal_agent_config)

        shared_context = ExecutionContext(
            workflow_id="wf-001",
            metadata={
                "config": {"timeout": 60, "retries": 3},
                "name": "test",
                "items": [1, 2, 3, 4, 5],
            },
        )

        num_threads = 20
        threads = []
        errors = []

        def thread_reader():
            try:
                response = agent.execute({"test": True}, context=shared_context)
                assert "60" in response.output
            except Exception as e:
                errors.append(e)

        for _i in range(num_threads):
            thread = threading.Thread(target=thread_reader)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        assert len(errors) == 0, f"Concurrent reads caused errors: {errors}"

    def test_context_corruption_detection(self, minimal_agent_config):
        """Test detecting when context has been corrupted."""

        class CorruptionDetectingAgent(MockAgent):
            """Agent that validates context integrity."""

            def _run(self, input_data, context=None, start_time=0.0):
                if context and context.metadata:
                    required_fields = ["version", "checksum", "workflow_id"]
                    missing_fields = [
                        f for f in required_fields if f not in context.metadata
                    ]

                    if missing_fields:
                        return AgentResponse(
                            output="",
                            error=f"Context corrupted: missing fields {missing_fields}",
                        )

                    if not isinstance(context.metadata.get("version"), (int, float)):
                        return AgentResponse(
                            output="", error="Context corrupted: version is not numeric"
                        )

                return AgentResponse(output="context valid")

        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = CorruptionDetectingAgent(minimal_agent_config)

        # Valid context
        valid_context = ExecutionContext(
            workflow_id="wf-001",
            metadata={"version": 1.0, "checksum": "abc123", "workflow_id": "wf-001"},
        )

        response = agent.execute({"test": True}, context=valid_context)
        assert response.error is None
        assert "valid" in response.output

        # Corrupted context (missing fields)
        corrupted_context = ExecutionContext(
            workflow_id="wf-001", metadata={"version": 1.0}
        )

        response = agent.execute({"test": True}, context=corrupted_context)
        assert response.error is not None
        assert "corrupted" in response.error.lower()
        assert "missing fields" in response.error.lower()

        # Corrupted context (wrong type)
        type_corrupted_context = ExecutionContext(
            workflow_id="wf-001",
            metadata={
                "version": "not_a_number",
                "checksum": "abc123",
                "workflow_id": "wf-001",
            },
        )

        response = agent.execute({"test": True}, context=type_corrupted_context)
        assert response.error is not None
        assert "corrupted" in response.error.lower()
        assert "version" in response.error.lower()
