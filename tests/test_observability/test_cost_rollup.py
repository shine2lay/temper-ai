"""Tests for src/observability/cost_rollup.py.

Covers cost aggregation with mixed agent statuses, emit helpers,
structured logging, and edge cases.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from temper_ai.observability.cost_rollup import (
    EVENT_TYPE_COST_SUMMARY,
    AgentCostEntry,
    StageCostSummary,
    compute_stage_cost_summary,
    emit_cost_summary,
)


# ── AgentCostEntry dataclass ──


class TestAgentCostEntry:
    """Test AgentCostEntry dataclass."""

    def test_create_basic(self):
        entry = AgentCostEntry(agent_name="agent-1")
        assert entry.agent_name == "agent-1"
        assert entry.cost_usd == 0.0
        assert entry.tokens == 0
        assert entry.duration_seconds == 0.0
        assert entry.status == "unknown"

    def test_create_full(self):
        entry = AgentCostEntry(
            agent_name="agent-2",
            cost_usd=0.05,
            tokens=1500,
            duration_seconds=3.2,
            status="completed",
        )
        assert entry.cost_usd == 0.05
        assert entry.tokens == 1500
        assert entry.duration_seconds == 3.2
        assert entry.status == "completed"


# ── StageCostSummary dataclass ──


class TestStageCostSummary:
    """Test StageCostSummary dataclass."""

    def test_create_empty(self):
        s = StageCostSummary(stage_name="analysis")
        assert s.stage_name == "analysis"
        assert s.total_cost_usd == 0.0
        assert s.total_tokens == 0
        assert s.total_duration_seconds == 0.0
        assert s.agent_count == 0
        assert s.agents == []

    def test_asdict(self):
        s = StageCostSummary(stage_name="test", total_cost_usd=0.1)
        d = asdict(s)
        assert d["stage_name"] == "test"
        assert d["total_cost_usd"] == 0.1
        assert "agents" in d


# ── compute_stage_cost_summary ──


class TestComputeStageCostSummary:
    """Test compute_stage_cost_summary function."""

    def test_empty_metrics(self):
        summary = compute_stage_cost_summary("analysis", {})
        assert summary.stage_name == "analysis"
        assert summary.total_cost_usd == 0.0
        assert summary.total_tokens == 0
        assert summary.agent_count == 0
        assert summary.agents == []

    def test_single_agent(self):
        metrics = {
            "agent-1": {
                "cost_usd": 0.05,
                "tokens": 1000,
                "duration_seconds": 2.5,
            },
        }
        summary = compute_stage_cost_summary("analysis", metrics)
        assert summary.agent_count == 1
        assert summary.total_cost_usd == pytest.approx(0.05)
        assert summary.total_tokens == 1000
        assert summary.total_duration_seconds == pytest.approx(2.5)
        assert summary.agents[0].agent_name == "agent-1"
        assert summary.agents[0].cost_usd == 0.05

    def test_multiple_agents_cost_sums(self):
        metrics = {
            "agent-1": {"cost_usd": 0.05, "tokens": 1000, "duration_seconds": 2.0},
            "agent-2": {"cost_usd": 0.03, "tokens": 800, "duration_seconds": 1.5},
            "agent-3": {"cost_usd": 0.02, "tokens": 500, "duration_seconds": 3.0},
        }
        summary = compute_stage_cost_summary("review", metrics)
        assert summary.agent_count == 3
        assert summary.total_cost_usd == pytest.approx(0.10)
        assert summary.total_tokens == 2300
        # Duration is max (parallel), not sum
        assert summary.total_duration_seconds == pytest.approx(3.0)

    def test_duration_takes_max_not_sum(self):
        metrics = {
            "a1": {"cost_usd": 0.0, "tokens": 0, "duration_seconds": 5.0},
            "a2": {"cost_usd": 0.0, "tokens": 0, "duration_seconds": 10.0},
            "a3": {"cost_usd": 0.0, "tokens": 0, "duration_seconds": 3.0},
        }
        summary = compute_stage_cost_summary("parallel", metrics)
        assert summary.total_duration_seconds == pytest.approx(10.0)

    def test_with_agent_statuses_string(self):
        metrics = {"agent-1": {"cost_usd": 0.01, "tokens": 100, "duration_seconds": 1.0}}
        statuses = {"agent-1": "completed"}
        summary = compute_stage_cost_summary("s1", metrics, agent_statuses=statuses)
        assert summary.agents[0].status == "completed"

    def test_with_agent_statuses_dict(self):
        metrics = {"agent-1": {"cost_usd": 0.01, "tokens": 100, "duration_seconds": 1.0}}
        statuses = {"agent-1": {"status": "failed", "error": "timeout"}}
        summary = compute_stage_cost_summary("s1", metrics, agent_statuses=statuses)
        assert summary.agents[0].status == "failed"

    def test_without_statuses_defaults_unknown(self):
        metrics = {"agent-1": {"cost_usd": 0.01, "tokens": 100, "duration_seconds": 1.0}}
        summary = compute_stage_cost_summary("s1", metrics)
        assert summary.agents[0].status == "unknown"

    def test_missing_metric_fields_default_zero(self):
        metrics = {"agent-1": {}}
        summary = compute_stage_cost_summary("s1", metrics)
        assert summary.agents[0].cost_usd == 0.0
        assert summary.agents[0].tokens == 0
        assert summary.agents[0].duration_seconds == 0.0

    def test_mixed_success_and_failure(self):
        metrics = {
            "a1": {"cost_usd": 0.05, "tokens": 1000, "duration_seconds": 2.0},
            "a2": {"cost_usd": 0.01, "tokens": 200, "duration_seconds": 0.5},
        }
        statuses = {"a1": "completed", "a2": "failed"}
        summary = compute_stage_cost_summary("stage", metrics, agent_statuses=statuses)
        assert summary.agent_count == 2
        status_map = {a.agent_name: a.status for a in summary.agents}
        assert status_map["a1"] == "completed"
        assert status_map["a2"] == "failed"
        # Cost totals include failed agents
        assert summary.total_cost_usd == pytest.approx(0.06)


# ── emit_cost_summary ──


class TestEmitCostSummary:
    """Test emit_cost_summary emit helper."""

    def test_emits_via_tracker(self):
        tracker = Mock()
        tracker.track_collaboration_event = Mock()
        summary = StageCostSummary(
            stage_name="analysis",
            total_cost_usd=0.1,
            total_tokens=2000,
            agent_count=2,
        )

        emit_cost_summary(tracker, "stage-1", summary)

        tracker.track_collaboration_event.assert_called_once()
        call_arg = tracker.track_collaboration_event.call_args[0][0]
        assert call_arg.event_type == EVENT_TYPE_COST_SUMMARY
        assert call_arg.stage_id == "stage-1"
        assert call_arg.event_data["total_cost_usd"] == 0.1

    def test_logs_structured_info(self, caplog):
        tracker = Mock()
        tracker.track_collaboration_event = Mock()
        summary = StageCostSummary(
            stage_name="review",
            total_cost_usd=0.05,
            total_tokens=1000,
            agent_count=1,
        )

        with caplog.at_level(logging.INFO):
            emit_cost_summary(tracker, "s1", summary)

        assert any("Cost summary" in r.message for r in caplog.records)

    def test_tracker_none_no_error(self):
        summary = StageCostSummary(stage_name="test")
        emit_cost_summary(None, "s1", summary)
        assert summary.stage_name == "test"  # no exception raised

    def test_tracker_without_method_no_error(self):
        tracker = object()  # no track_collaboration_event
        summary = StageCostSummary(stage_name="test")
        emit_cost_summary(tracker, "s1", summary)
        assert summary.stage_name == "test"  # no exception raised

    def test_tracker_exception_swallowed(self):
        tracker = Mock()
        tracker.track_collaboration_event = Mock(side_effect=RuntimeError("boom"))
        summary = StageCostSummary(stage_name="test")
        emit_cost_summary(tracker, "s1", summary)
        assert summary.stage_name == "test"  # exception swallowed
