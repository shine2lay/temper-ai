"""
Tests for ObservabilityBuffer batch operations.
"""
from datetime import datetime, timezone

import pytest

from src.observability.backends import SQLObservabilityBackend
from src.observability.buffer import ObservabilityBuffer
from src.observability.database import get_session, init_database
from src.observability.models import AgentExecution, LLMCall, ToolExecution
from src.observability.tracker import ExecutionTracker


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    # Reset global database before each test
    import src.observability.database as db_module
    from src.observability.database import _db_lock
    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    # Clean up after test
    with _db_lock:
        db_module._db_manager = None


class TestObservabilityBuffer:
    """Tests for ObservabilityBuffer class."""

    def test_buffer_initialization(self):
        """Test buffer can be created with custom settings."""
        buffer = ObservabilityBuffer(flush_size=50, flush_interval=2.0, auto_flush=False)
        assert buffer.flush_size == 50
        assert buffer.flush_interval == 2.0
        assert buffer.auto_flush == False

    def test_buffer_llm_call(self):
        """Test buffering LLM calls."""
        from src.observability.buffer import LLMCallBufferParams
        buffer = ObservabilityBuffer(flush_size=10, auto_flush=False)

        buffer.buffer_llm_call(LLMCallBufferParams(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="ollama",
            model="test-model",
            prompt="test prompt",
            response="test response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.001,
            start_time=datetime.now(timezone.utc)
        ))

        assert len(buffer.llm_calls) == 1
        assert buffer.llm_calls[0].llm_call_id == "llm-1"
        assert buffer.llm_calls[0].provider == "ollama"

    def test_buffer_tool_call(self):
        """Test buffering tool calls."""
        from src.observability.buffer import ToolCallBufferParams
        buffer = ObservabilityBuffer(flush_size=10, auto_flush=False)

        buffer.buffer_tool_call(ToolCallBufferParams(
            tool_execution_id="tool-1",
            agent_id="agent-1",
            tool_name="calculator",
            input_params={"a": 1, "b": 2},
            output_data={"result": 3},
            start_time=datetime.now(timezone.utc),
            duration_seconds=0.01
        ))

        assert len(buffer.tool_calls) == 1
        assert buffer.tool_calls[0].tool_execution_id == "tool-1"
        assert buffer.tool_calls[0].tool_name == "calculator"

    def test_buffer_agent_metrics_accumulation(self):
        """Test agent metrics accumulate correctly."""
        from src.observability.buffer import LLMCallBufferParams
        buffer = ObservabilityBuffer(flush_size=10, auto_flush=False)

        # Buffer multiple LLM calls for same agent
        for i in range(3):
            buffer.buffer_llm_call(LLMCallBufferParams(
                llm_call_id=f"llm-{i}",
                agent_id="agent-1",
                provider="ollama",
                model="test-model",
                prompt="test",
                response="response",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=100,
                estimated_cost_usd=0.001,
                start_time=datetime.now(timezone.utc)
            ))

        # Check metrics accumulated
        metrics = buffer.agent_metrics["agent-1"]
        assert metrics.num_llm_calls == 3
        assert metrics.total_tokens == 45  # (10 + 5) * 3
        assert metrics.prompt_tokens == 30  # 10 * 3
        assert metrics.completion_tokens == 15  # 5 * 3
        assert metrics.estimated_cost_usd == 0.003  # 0.001 * 3

    def test_buffer_size_flush(self):
        """Test buffer flushes when size limit reached."""
        from src.observability.buffer import LLMCallBufferParams
        flush_called = []

        def mock_flush(llm_calls, tool_calls, agent_metrics):
            flush_called.append((len(llm_calls), len(tool_calls), len(agent_metrics)))

        buffer = ObservabilityBuffer(flush_size=5, auto_flush=False)
        buffer.set_flush_callback(mock_flush)

        # Add 5 LLM calls (should trigger flush)
        for i in range(5):
            buffer.buffer_llm_call(LLMCallBufferParams(
                llm_call_id=f"llm-{i}",
                agent_id="agent-1",
                provider="ollama",
                model="test",
                prompt="test",
                response="response",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=100,
                estimated_cost_usd=0.001,
                start_time=datetime.now(timezone.utc)
            ))

        # Should have flushed
        assert len(flush_called) == 1
        assert flush_called[0] == (5, 0, 1)  # 5 LLM calls, 0 tool calls, 1 agent

    def test_buffer_manual_flush(self):
        """Test manual flush."""
        from src.observability.buffer import LLMCallBufferParams
        flush_called = []

        def mock_flush(llm_calls, tool_calls, agent_metrics):
            flush_called.append((len(llm_calls), len(tool_calls), len(agent_metrics)))

        buffer = ObservabilityBuffer(flush_size=100, auto_flush=False)
        buffer.set_flush_callback(mock_flush)

        # Add 3 LLM calls
        for i in range(3):
            buffer.buffer_llm_call(LLMCallBufferParams(
                llm_call_id=f"llm-{i}",
                agent_id="agent-1",
                provider="ollama",
                model="test",
                prompt="test",
                response="response",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=100,
                estimated_cost_usd=0.001,
                start_time=datetime.now(timezone.utc)
            ))

        # No auto flush yet
        assert len(flush_called) == 0

        # Manual flush
        buffer.flush()

        # Should have flushed
        assert len(flush_called) == 1
        assert flush_called[0] == (3, 0, 1)

    def test_buffer_stats(self):
        """Test buffer statistics."""
        from src.observability.buffer import LLMCallBufferParams
        buffer = ObservabilityBuffer(flush_size=10, auto_flush=False)

        buffer.buffer_llm_call(LLMCallBufferParams(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="ollama",
            model="test",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.001,
            start_time=datetime.now(timezone.utc)
        ))

        stats = buffer.get_stats()
        assert stats["llm_calls_buffered"] == 1
        assert stats["tool_calls_buffered"] == 0
        assert stats["agent_metrics_buffered"] == 1
        assert stats["total_buffered"] == 1
        assert stats["flush_size"] == 10


class TestBufferedSQLBackend:
    """Tests for SQL backend with buffering enabled."""

    def test_buffered_backend_creation(self, db):
        """Test creating SQL backend with buffer."""
        buffer = ObservabilityBuffer(flush_size=10, auto_flush=False)
        backend = SQLObservabilityBackend(buffer=buffer)
        assert backend._buffer is buffer

    def test_buffered_llm_call_batching(self, db):
        """Test LLM calls are buffered and batched."""
        buffer = ObservabilityBuffer(flush_size=5, auto_flush=False)
        backend = SQLObservabilityBackend(buffer=buffer)
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test"}}

        with tracker.track_workflow("test_workflow", config) as workflow_id:
            with tracker.track_stage("test_stage", config, workflow_id) as stage_id:
                with tracker.track_agent("test_agent", config, stage_id) as agent_id:
                    # Track 5 LLM calls (buffered)
                    for i in range(5):
                        tracker.track_llm_call(
                            agent_id=agent_id,
                            provider="ollama",
                            model="test-model",
                            prompt=f"prompt {i}",
                            response=f"response {i}",
                            prompt_tokens=10,
                            completion_tokens=5,
                            latency_ms=100,
                            estimated_cost_usd=0.001
                        )

        # Check buffer state before flush
        # Buffer should have auto-flushed at size 5
        assert len(buffer.llm_calls) == 0  # Flushed

        # Check database has all 5 LLM calls
        with get_session() as session:
            from sqlmodel import select
            statement = select(LLMCall).where(LLMCall.agent_execution_id == agent_id)
            llm_calls = session.exec(statement).all()
            assert len(llm_calls) == 5

    def test_buffered_tool_call_batching(self, db):
        """Test tool calls are buffered and batched."""
        buffer = ObservabilityBuffer(flush_size=10, auto_flush=False)
        backend = SQLObservabilityBackend(buffer=buffer)
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test"}}

        with tracker.track_workflow("test_workflow", config) as workflow_id:
            with tracker.track_stage("test_stage", config, workflow_id) as stage_id:
                with tracker.track_agent("test_agent", config, stage_id) as agent_id:
                    # Track 3 tool calls (buffered)
                    for i in range(3):
                        tracker.track_tool_call(
                            agent_id=agent_id,
                            tool_name="calculator",
                            input_params={"a": i, "b": i+1},
                            output_data={"result": i + (i+1)},
                            duration_seconds=0.01
                        )

        # Manual flush
        buffer.flush()

        # Check database has all 3 tool calls
        with get_session() as session:
            from sqlmodel import select
            statement = select(ToolExecution).where(ToolExecution.agent_execution_id == agent_id)
            tool_calls = session.exec(statement).all()
            assert len(tool_calls) == 3

    def test_buffered_agent_metrics_update(self, db):
        """Test agent metrics are updated correctly after flush."""
        buffer = ObservabilityBuffer(flush_size=10, auto_flush=False)
        backend = SQLObservabilityBackend(buffer=buffer)
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test"}}

        with tracker.track_workflow("test_workflow", config) as workflow_id:
            with tracker.track_stage("test_stage", config, workflow_id) as stage_id:
                with tracker.track_agent("test_agent", config, stage_id) as agent_id:
                    # Track 3 LLM calls
                    for i in range(3):
                        tracker.track_llm_call(
                            agent_id=agent_id,
                            provider="ollama",
                            model="test-model",
                            prompt="test",
                            response="response",
                            prompt_tokens=10,
                            completion_tokens=5,
                            latency_ms=100,
                            estimated_cost_usd=0.001
                        )

        # Manual flush
        buffer.flush()

        # Check agent metrics were updated
        with get_session() as session:
            from sqlmodel import select
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            assert agent.num_llm_calls == 3
            assert agent.total_tokens == 45  # (10 + 5) * 3
            assert agent.prompt_tokens == 30
            assert agent.completion_tokens == 15
            assert agent.estimated_cost_usd == 0.003


class TestBufferContextManager:
    """Tests for buffer context manager usage."""

    def test_buffer_context_manager(self, db):
        """Test buffer auto-flushes on context exit."""
        from src.observability.buffer import LLMCallBufferParams
        flush_called = []

        def mock_flush(llm_calls, tool_calls, agent_metrics):
            flush_called.append((len(llm_calls), len(tool_calls), len(agent_metrics)))

        with ObservabilityBuffer(flush_size=100, auto_flush=False) as buffer:
            buffer.set_flush_callback(mock_flush)

            buffer.buffer_llm_call(LLMCallBufferParams(
                llm_call_id="llm-1",
                agent_id="agent-1",
                provider="ollama",
                model="test",
                prompt="test",
                response="response",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=100,
                estimated_cost_usd=0.001,
                start_time=datetime.now(timezone.utc)
            ))

        # Should have flushed on exit
        assert len(flush_called) == 1
        assert flush_called[0] == (1, 0, 1)
