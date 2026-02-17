"""Tests for individual pattern miners."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.learning.miners.agent_performance import AgentPerformanceMiner
from src.learning.miners.collaboration_patterns import CollaborationPatternMiner
from src.learning.miners.cost_patterns import CostPatternMiner
from src.learning.miners.failure_patterns import FailurePatternMiner
from src.learning.miners.model_effectiveness import ModelEffectivenessMiner
from src.learning.models import (
    PATTERN_AGENT_PERFORMANCE,
    PATTERN_COLLABORATION,
    PATTERN_COST,
    PATTERN_FAILURE,
    PATTERN_MODEL_EFFECTIVENESS,
)

_NOW = datetime.now(timezone.utc)


def _mock_agent_execution(name: str, status: str, duration: float = 5.0):
    ex = MagicMock()
    ex.agent_name = name
    ex.status = status
    ex.duration_seconds = duration
    ex.start_time = _NOW
    ex.stage = MagicMock()
    ex.stage.workflow_execution_id = "wf-1"
    return ex


def _mock_llm_call(model: str, status: str = "success", cost: float = 0.01, tokens: int = 100):
    call = MagicMock()
    call.model = model
    call.status = status
    call.estimated_cost_usd = cost
    call.total_tokens = tokens
    call.start_time = _NOW
    call.agent_execution_id = "agent-1"
    return call


def _mock_error_fingerprint(error_type: str, count: int, classification: str = "transient"):
    fp = MagicMock()
    fp.fingerprint = "abc123"
    fp.error_type = error_type
    fp.error_code = "E001"
    fp.classification = classification
    fp.normalized_message = f"Error: {error_type}"
    fp.occurrence_count = count
    fp.last_seen = _NOW
    fp.recent_workflow_ids = ["wf-1"]
    return fp


def _mock_collab_event(stage_id: str, event_type: str):
    ev = MagicMock()
    ev.stage_execution_id = stage_id
    ev.event_type = event_type
    ev.timestamp = _NOW
    return ev


class TestAgentPerformanceMiner:
    @patch("src.learning.miners.agent_performance.get_session")
    def test_low_success_rate(self, mock_session):
        execs = [_mock_agent_execution("agent-a", "failed") for _ in range(4)]
        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = execs
        mock_session.return_value = ctx

        miner = AgentPerformanceMiner()
        patterns = miner.mine()
        assert len(patterns) >= 1
        assert patterns[0].pattern_type == PATTERN_AGENT_PERFORMANCE
        assert "Low success" in patterns[0].title

    @patch("src.learning.miners.agent_performance.get_session")
    def test_empty_data(self, mock_session):
        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = []
        mock_session.return_value = ctx

        assert AgentPerformanceMiner().mine() == []


class TestModelEffectivenessMiner:
    @patch("src.learning.miners.model_effectiveness.get_session")
    def test_high_error_rate(self, mock_session):
        calls = [_mock_llm_call("gpt-4", "error") for _ in range(6)]
        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = calls
        mock_session.return_value = ctx

        patterns = ModelEffectivenessMiner().mine()
        assert any("High error" in p.title for p in patterns)

    @patch("src.learning.miners.model_effectiveness.get_session")
    def test_empty_data(self, mock_session):
        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = []
        mock_session.return_value = ctx

        assert ModelEffectivenessMiner().mine() == []


class TestFailurePatternMiner:
    @patch("src.learning.miners.failure_patterns.get_session")
    def test_recurring_errors(self, mock_session):
        fps = [_mock_error_fingerprint("TimeoutError", 5)]
        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = fps
        mock_session.return_value = ctx

        patterns = FailurePatternMiner().mine()
        assert len(patterns) == 1
        assert PATTERN_FAILURE == patterns[0].pattern_type

    @patch("src.learning.miners.failure_patterns.get_session")
    def test_below_threshold(self, mock_session):
        fps = [_mock_error_fingerprint("TimeoutError", 1)]
        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = fps
        mock_session.return_value = ctx

        assert FailurePatternMiner().mine() == []


class TestCostPatternMiner:
    @patch("src.learning.miners.cost_patterns.get_session")
    def test_cost_dominance(self, mock_session):
        # One agent dominates cost
        calls = [_mock_llm_call("model-a", cost=0.5, tokens=1000) for _ in range(5)]
        calls.append(_mock_llm_call("model-a", cost=0.01, tokens=10))
        # Override agent_execution_id — all same agent
        for c in calls[:5]:
            c.agent_execution_id = "agent-big"
        calls[5].agent_execution_id = "agent-small"

        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = calls
        mock_session.return_value = ctx

        patterns = CostPatternMiner().mine()
        assert any("Cost-dominant" in p.title for p in patterns)


class TestCollaborationPatternMiner:
    @patch("src.learning.miners.collaboration_patterns.get_session")
    def test_unresolved_debate(self, mock_session):
        events = [_mock_collab_event("stage-1", "debate_round") for _ in range(4)]
        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = events
        mock_session.return_value = ctx

        patterns = CollaborationPatternMiner().mine()
        assert any("Unresolved" in p.title for p in patterns)

    @patch("src.learning.miners.collaboration_patterns.get_session")
    def test_empty_data(self, mock_session):
        ctx = MagicMock()
        ctx.__enter__ = lambda s: ctx
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.exec.return_value.all.return_value = []
        mock_session.return_value = ctx

        assert CollaborationPatternMiner().mine() == []
