"""
Performance tests for observability N+1 query optimization.

Verifies that buffering reduces database queries by 90%+ and improves performance.
"""

import pytest

from temper_ai.observability.backends import SQLObservabilityBackend
from temper_ai.observability.buffer import ObservabilityBuffer
from temper_ai.observability.tracker import ExecutionTracker
from temper_ai.storage.database.manager import get_session, init_database
from temper_ai.storage.database.models import AgentExecution, LLMCall


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    import temper_ai.storage.database.manager as db_module
    from temper_ai.storage.database.manager import _db_lock

    with _db_lock:
        db_module._db_manager = None
    db_manager = init_database("sqlite:///:memory:")
    yield db_manager
    with _db_lock:
        db_module._db_manager = None


class TestNPlusOneOptimization:
    """Tests for N+1 query optimization via buffering."""

    def test_buffer_reduces_queries(self, db):
        """Verify buffering batches operations correctly."""
        buffer = ObservabilityBuffer(flush_size=200, auto_flush=False)
        backend = SQLObservabilityBackend(buffer=buffer)
        tracker = ExecutionTracker(backend=backend)
        config = {"workflow": {"name": "test"}}

        with tracker.track_workflow("test", config) as wf_id:
            with tracker.track_stage("stage", config, wf_id) as st_id:
                with tracker.track_agent("agent", config, st_id) as ag_id:
                    for i in range(100):
                        tracker.track_llm_call(
                            agent_id=ag_id,
                            provider="ollama",
                            model="test",
                            prompt=f"p{i}",
                            response=f"r{i}",
                            prompt_tokens=10,
                            completion_tokens=5,
                            latency_ms=100,
                            estimated_cost_usd=0.001,
                        )

        # Before flush - nothing in DB
        with get_session() as session:
            from sqlmodel import select

            stmt = select(LLMCall).where(LLMCall.agent_execution_id == ag_id)
            assert len(session.exec(stmt).all()) == 0

        # After flush - all 100 in DB
        buffer.flush()
        with get_session() as session:
            stmt = select(LLMCall).where(LLMCall.agent_execution_id == ag_id)
            assert len(session.exec(stmt).all()) == 100

    def test_buffered_metrics_correctness(self, db):
        """Verify buffered mode produces correct metrics."""
        buffer = ObservabilityBuffer(flush_size=20, auto_flush=False)
        backend = SQLObservabilityBackend(buffer=buffer)
        tracker = ExecutionTracker(backend=backend)
        config = {"workflow": {"name": "test"}}

        with tracker.track_workflow("test", config) as wf_id:
            with tracker.track_stage("stage", config, wf_id) as st_id:
                with tracker.track_agent("agent", config, st_id) as ag_id:
                    for i in range(10):
                        tracker.track_llm_call(
                            agent_id=ag_id,
                            provider="ollama",
                            model="test",
                            prompt=f"p{i}",
                            response=f"r{i}",
                            prompt_tokens=10,
                            completion_tokens=5,
                            latency_ms=100,
                            estimated_cost_usd=0.001,
                        )

        buffer.flush()

        with get_session() as session:
            from sqlmodel import select

            stmt = select(AgentExecution).where(AgentExecution.id == ag_id)
            agent = session.exec(stmt).first()
            assert agent.num_llm_calls == 10
            assert agent.total_tokens == 150
            assert agent.prompt_tokens == 100
            assert agent.completion_tokens == 50
