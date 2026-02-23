"""Tests for TrustEvaluator."""

from unittest.mock import MagicMock

from temper_ai.safety.autonomy.schemas import AutonomyLevel
from temper_ai.safety.autonomy.trust_evaluator import TrustEvaluator


def _mock_merit(
    total: int = 25,
    successful: int = 23,
    failed: int = 2,
    success_rate: float = 0.92,
    average_confidence: float = 0.85,
    expertise_score: float = 0.80,
) -> MagicMock:
    """Create a mock merit score."""
    m = MagicMock()
    m.total_decisions = total
    m.successful_decisions = successful
    m.failed_decisions = failed
    m.success_rate = success_rate
    m.average_confidence = average_confidence
    m.expertise_score = expertise_score
    return m


class TestTrustEvaluator:
    """Tests for TrustEvaluator."""

    def test_no_merit_record(self) -> None:
        """Returns neutral when no merit record exists."""
        session = MagicMock()
        session.exec.return_value.first.return_value = None
        evaluator = TrustEvaluator()
        result = evaluator.evaluate(session, "agent-x", "domain-y")
        assert not result.eligible_for_escalation
        assert not result.needs_de_escalation

    def test_insufficient_decisions(self) -> None:
        """Not eligible with too few decisions."""
        session = MagicMock()
        session.exec.return_value.first.return_value = _mock_merit(
            total=5,
            successful=5,
            failed=0,
            success_rate=1.0,
        )
        evaluator = TrustEvaluator()
        result = evaluator.evaluate(session, "a", "d")
        assert not result.eligible_for_escalation

    def test_eligible_for_escalation(self) -> None:
        """Eligible when success rate >= threshold and enough decisions."""
        session = MagicMock()
        session.exec.return_value.first.return_value = _mock_merit(
            total=25,
            successful=23,
            failed=2,
            success_rate=0.92,
        )
        evaluator = TrustEvaluator()
        result = evaluator.evaluate(session, "a", "d")
        assert result.eligible_for_escalation
        assert result.recommended_level == AutonomyLevel.SPOT_CHECKED

    def test_not_eligible_low_success(self) -> None:
        """Not eligible with low success rate."""
        session = MagicMock()
        session.exec.return_value.first.return_value = _mock_merit(
            total=25,
            successful=20,
            failed=5,
            success_rate=0.80,
        )
        evaluator = TrustEvaluator()
        result = evaluator.evaluate(session, "a", "d")
        assert not result.eligible_for_escalation

    def test_de_escalation_high_failure(self) -> None:
        """De-escalation when failure rate >= threshold."""
        session = MagicMock()
        session.exec.return_value.first.return_value = _mock_merit(
            total=20,
            successful=15,
            failed=5,
            success_rate=0.75,
        )
        evaluator = TrustEvaluator(de_escalation_rate=0.15)
        result = evaluator.evaluate(
            session,
            "a",
            "d",
            current_level=AutonomyLevel.SPOT_CHECKED,
        )
        # failure_rate = 5/20 = 0.25 >= 0.15
        assert result.needs_de_escalation
        assert result.recommended_level == AutonomyLevel.SUPERVISED

    def test_no_de_escalation_at_supervised(self) -> None:
        """No de-escalation when already at SUPERVISED."""
        session = MagicMock()
        session.exec.return_value.first.return_value = _mock_merit(
            total=20,
            successful=15,
            failed=5,
            success_rate=0.75,
        )
        evaluator = TrustEvaluator(de_escalation_rate=0.15)
        result = evaluator.evaluate(
            session,
            "a",
            "d",
            current_level=AutonomyLevel.SUPERVISED,
        )
        assert not result.needs_de_escalation

    def test_escalation_from_higher_level(self) -> None:
        """Escalation from SPOT_CHECKED to RISK_GATED."""
        session = MagicMock()
        session.exec.return_value.first.return_value = _mock_merit(
            total=30,
            successful=28,
            failed=2,
            success_rate=0.93,
        )
        evaluator = TrustEvaluator()
        result = evaluator.evaluate(
            session,
            "a",
            "d",
            current_level=AutonomyLevel.SPOT_CHECKED,
        )
        assert result.eligible_for_escalation
        assert result.recommended_level == AutonomyLevel.RISK_GATED

    def test_evidence_populated(self) -> None:
        """Evidence dict includes merit data."""
        session = MagicMock()
        session.exec.return_value.first.return_value = _mock_merit()
        evaluator = TrustEvaluator()
        result = evaluator.evaluate(session, "a", "d")
        assert "total_decisions" in result.evidence
        assert "success_rate" in result.evidence
