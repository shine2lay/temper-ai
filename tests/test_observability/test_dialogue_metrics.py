"""Tests for src/observability/dialogue_metrics.py.

Covers round metrics computation, confidence trajectory, convergence speed,
stance change detection, quality gate violation details, and emit helpers.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from temper_ai.observability.dialogue_metrics import (
    EVENT_TYPE_QUALITY_GATE_DETAIL,
    QualityGateViolationDetail,
    RoundMetrics,
    build_quality_gate_details,
    compute_round_metrics,
    emit_quality_gate_details,
)

# ── RoundMetrics dataclass ──


class TestRoundMetrics:
    """Test RoundMetrics dataclass."""

    def test_create_basic(self):
        m = RoundMetrics(round_number=0)
        assert m.round_number == 0
        assert m.confidence_trajectory == []
        assert m.avg_confidence == 0.0
        assert m.convergence_speed is None
        assert m.stance_changes == 0
        assert m.agent_count == 0

    def test_create_with_all_fields(self):
        m = RoundMetrics(
            round_number=2,
            confidence_trajectory=[0.5, 0.7, 0.85],
            avg_confidence=0.85,
            convergence_speed=0.15,
            stance_changes=1,
            agent_count=3,
        )
        assert m.round_number == 2
        assert m.confidence_trajectory == [0.5, 0.7, 0.85]
        assert m.avg_confidence == 0.85
        assert m.convergence_speed == 0.15
        assert m.stance_changes == 1
        assert m.agent_count == 3

    def test_asdict(self):
        m = RoundMetrics(round_number=1, avg_confidence=0.75)
        d = asdict(m)
        assert d["round_number"] == 1
        assert d["avg_confidence"] == 0.75
        assert "confidence_trajectory" in d


# ── QualityGateViolationDetail ──


class TestQualityGateViolationDetail:
    """Test QualityGateViolationDetail dataclass."""

    def test_create_basic(self):
        d = QualityGateViolationDetail(gate_name="min_confidence")
        assert d.gate_name == "min_confidence"
        assert d.expected is None
        assert d.actual is None
        assert d.deficit is None

    def test_create_full(self):
        d = QualityGateViolationDetail(
            gate_name="min_confidence",
            expected=0.8,
            actual=0.6,
            deficit=0.2,
        )
        assert d.expected == 0.8
        assert d.actual == 0.6
        assert d.deficit == 0.2


# ── compute_round_metrics ──


class TestComputeRoundMetrics:
    """Test compute_round_metrics function."""

    def _make_output(self, name: str, confidence: float, stance: str = ""):
        out = Mock()
        out.agent_name = name
        out.confidence = confidence
        out.metadata = {"stance": stance} if stance else {}
        return out

    def test_empty_outputs(self):
        m = compute_round_metrics(
            current_outputs=[],
            dialogue_history=[],
            round_number=0,
        )
        assert m.agent_count == 0
        assert m.avg_confidence == 0.0
        assert m.convergence_speed is None
        assert m.stance_changes == 0

    def test_first_round_basic(self):
        outputs = [
            self._make_output("a1", 0.8),
            self._make_output("a2", 0.6),
        ]
        history = [
            {"round": 0, "agent": "a1", "confidence": 0.8},
            {"round": 0, "agent": "a2", "confidence": 0.6},
        ]
        m = compute_round_metrics(
            current_outputs=outputs,
            dialogue_history=history,
            round_number=0,
        )
        assert m.agent_count == 2
        assert m.avg_confidence == pytest.approx(0.7)
        assert len(m.confidence_trajectory) == 1
        assert m.confidence_trajectory[0] == pytest.approx(0.7)
        assert m.stance_changes == 0  # round 0 has no previous

    def test_convergence_speed(self):
        m = compute_round_metrics(
            current_outputs=[self._make_output("a1", 0.9)],
            dialogue_history=[],
            round_number=1,
            convergence_score=0.85,
            previous_convergence=0.6,
        )
        assert m.convergence_speed == pytest.approx(0.25)

    def test_convergence_speed_none_when_missing(self):
        m = compute_round_metrics(
            current_outputs=[self._make_output("a1", 0.9)],
            dialogue_history=[],
            round_number=1,
            convergence_score=None,
            previous_convergence=0.6,
        )
        assert m.convergence_speed is None

    def test_convergence_speed_negative_diverging(self):
        m = compute_round_metrics(
            current_outputs=[self._make_output("a1", 0.5)],
            dialogue_history=[],
            round_number=1,
            convergence_score=0.4,
            previous_convergence=0.7,
        )
        assert m.convergence_speed == pytest.approx(-0.3)

    def test_confidence_trajectory_multi_round(self):
        history = [
            {"round": 0, "agent": "a1", "confidence": 0.5},
            {"round": 0, "agent": "a2", "confidence": 0.7},
            {"round": 1, "agent": "a1", "confidence": 0.8},
            {"round": 1, "agent": "a2", "confidence": 0.9},
        ]
        outputs = [
            self._make_output("a1", 0.8),
            self._make_output("a2", 0.9),
        ]
        m = compute_round_metrics(
            current_outputs=outputs,
            dialogue_history=history,
            round_number=1,
        )
        assert len(m.confidence_trajectory) == 2
        assert m.confidence_trajectory[0] == pytest.approx(0.6)
        assert m.confidence_trajectory[1] == pytest.approx(0.85)

    def test_stance_changes_detected(self):
        history = [
            {"round": 0, "agent": "a1", "stance": "for"},
            {"round": 0, "agent": "a2", "stance": "against"},
        ]
        outputs = [
            self._make_output("a1", 0.8, stance="against"),  # changed
            self._make_output("a2", 0.7, stance="against"),  # same
        ]
        m = compute_round_metrics(
            current_outputs=outputs,
            dialogue_history=history,
            round_number=1,
        )
        assert m.stance_changes == 1

    def test_stance_changes_none_in_round_zero(self):
        outputs = [self._make_output("a1", 0.8, stance="for")]
        m = compute_round_metrics(
            current_outputs=outputs,
            dialogue_history=[],
            round_number=0,
        )
        assert m.stance_changes == 0

    def test_stance_changes_no_previous_stances(self):
        history = [
            {"round": 0, "agent": "a1", "confidence": 0.5},  # no stance
        ]
        outputs = [self._make_output("a1", 0.8, stance="for")]
        m = compute_round_metrics(
            current_outputs=outputs,
            dialogue_history=history,
            round_number=1,
        )
        assert m.stance_changes == 0

    def test_avg_confidence_with_none_values(self):
        out1 = Mock()
        out1.confidence = None
        out2 = Mock()
        out2.confidence = 0.6
        m = compute_round_metrics(
            current_outputs=[out1, out2],
            dialogue_history=[],
            round_number=0,
        )
        assert m.avg_confidence == pytest.approx(0.3)


# ── build_quality_gate_details ──


class TestBuildQualityGateDetails:
    """Test build_quality_gate_details function."""

    def test_confidence_violation(self):
        synthesis = Mock()
        synthesis.confidence = 0.6
        config = {"min_confidence": 0.8}
        details = build_quality_gate_details(
            violations=["Confidence below threshold"],
            synthesis_result=synthesis,
            quality_gates_config=config,
        )
        assert len(details) == 1
        d = details[0]
        assert d.gate_name == "min_confidence"
        assert d.expected == 0.8
        assert d.actual == 0.6
        assert d.deficit == pytest.approx(0.2)

    def test_findings_violation(self):
        synthesis = Mock()
        config = {"min_findings": 3}
        details = build_quality_gate_details(
            violations=["Not enough findings"],
            synthesis_result=synthesis,
            quality_gates_config=config,
        )
        assert len(details) == 1
        assert details[0].gate_name == "min_findings"
        assert details[0].expected == 3

    def test_citation_violation(self):
        details = build_quality_gate_details(
            violations=["Missing citation references"],
            synthesis_result=Mock(),
            quality_gates_config={},
        )
        assert len(details) == 1
        assert details[0].gate_name == "require_citations"
        assert details[0].expected is True
        assert details[0].actual is False

    def test_unknown_violation(self):
        details = build_quality_gate_details(
            violations=["Some unknown rule broken"],
            synthesis_result=Mock(),
            quality_gates_config={},
        )
        assert len(details) == 1
        assert details[0].gate_name == "unknown"
        assert details[0].actual == "Some unknown rule broken"

    def test_multiple_violations(self):
        synthesis = Mock()
        synthesis.confidence = 0.5
        config = {"min_confidence": 0.8, "min_findings": 2}
        details = build_quality_gate_details(
            violations=[
                "Confidence too low",
                "Not enough findings",
                "No citation provided",
            ],
            synthesis_result=synthesis,
            quality_gates_config=config,
        )
        assert len(details) == 3
        gate_names = [d.gate_name for d in details]
        assert "min_confidence" in gate_names
        assert "min_findings" in gate_names
        assert "require_citations" in gate_names

    def test_empty_violations(self):
        details = build_quality_gate_details(
            violations=[],
            synthesis_result=Mock(),
            quality_gates_config={},
        )
        assert details == []


# ── emit_quality_gate_details ──


class TestEmitQualityGateDetails:
    """Test emit_quality_gate_details emit helper."""

    def test_emits_via_tracker(self):
        tracker = Mock()
        tracker.track_collaboration_event = Mock()
        details = [
            QualityGateViolationDetail(gate_name="min_confidence", deficit=0.2),
        ]

        emit_quality_gate_details(tracker, "stage-1", "analysis", details)

        tracker.track_collaboration_event.assert_called_once()
        call_arg = tracker.track_collaboration_event.call_args[0][0]
        assert call_arg.event_type == EVENT_TYPE_QUALITY_GATE_DETAIL
        assert call_arg.event_data["violation_count"] == 1
        assert call_arg.event_data["stage_name"] == "analysis"

    def test_tracker_none_no_error(self):
        details = [QualityGateViolationDetail(gate_name="test")]
        emit_quality_gate_details(None, "s1", "stage", details)
        assert len(details) == 1  # no exception raised

    def test_logs_structured_info(self, caplog):
        tracker = Mock()
        tracker.track_collaboration_event = Mock()
        details = [
            QualityGateViolationDetail(gate_name="min_confidence"),
            QualityGateViolationDetail(gate_name="min_findings"),
        ]

        with caplog.at_level(logging.INFO):
            emit_quality_gate_details(tracker, "s1", "review", details)

        assert any("Quality gate violation" in r.message for r in caplog.records)
