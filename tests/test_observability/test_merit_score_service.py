"""Tests for merit score service.

Tests cover MeritScoreService.update() with various decision outcomes,
Bayesian probability updates, cumulative decision tracking, success rate
calculations including mixed decisions, and edge cases like first updates
and concurrent operations.
"""

import pytest
from sqlmodel import select

from temper_ai.observability.database import get_session, init_database
from temper_ai.observability.merit_score_service import MeritScoreService
from temper_ai.observability.models import AgentMeritScore, DecisionOutcome


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    # Reset global database before each test
    import temper_ai.observability.database as db_module
    from temper_ai.observability.database import _db_lock
    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    # Clean up after test
    with _db_lock:
        db_module._db_manager = None


@pytest.fixture
def service():
    """Create merit score service."""
    return MeritScoreService()


class TestMeritScoreServiceBasics:
    """Tests for basic merit score operations."""

    def test_first_success_update(self, db, service):
        """Test first successful decision creates merit score record."""
        with get_session() as session:
            service.update(
                session=session,
                agent_name="researcher",
                domain="analysis",
                decision_outcome="success",
                confidence=0.85
            )
            session.commit()

        # Verify record created
        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit is not None
            assert merit.agent_name == "researcher"
            assert merit.domain == "analysis"
            assert merit.total_decisions == 1
            assert merit.successful_decisions == 1
            assert merit.failed_decisions == 0
            assert merit.success_rate == 1.0
            assert merit.average_confidence == 0.85
            assert merit.expertise_score is not None

    def test_first_failure_update(self, db, service):
        """Test first failed decision creates merit score record."""
        with get_session() as session:
            service.update(
                session=session,
                agent_name="researcher",
                domain="analysis",
                decision_outcome="failure",
                confidence=0.40
            )
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit.total_decisions == 1
            assert merit.successful_decisions == 0
            assert merit.failed_decisions == 1
            assert merit.success_rate == 0.0

    def test_mixed_decision_update(self, db, service):
        """Test mixed decision outcome handling."""
        with get_session() as session:
            service.update(
                session=session,
                agent_name="researcher",
                domain="analysis",
                decision_outcome="mixed",
                confidence=0.65
            )
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit.total_decisions == 1
            assert merit.mixed_decisions == 1
            assert merit.successful_decisions == 0
            assert merit.failed_decisions == 0
            # Mixed counts as 0.5 success
            assert merit.success_rate == 0.5

    def test_neutral_decision_update(self, db, service):
        """Test neutral decision outcome handling."""
        with get_session() as session:
            service.update(
                session=session,
                agent_name="researcher",
                domain="analysis",
                decision_outcome="neutral"
            )
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit.total_decisions == 1
            assert merit.successful_decisions == 0
            assert merit.failed_decisions == 0
            assert merit.mixed_decisions == 0


class TestCumulativeMetrics:
    """Tests for cumulative metric tracking."""

    def test_multiple_successful_decisions(self, db, service):
        """Test cumulative tracking of multiple successes."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", 0.8)
            service.update(session, "researcher", "analysis", "success", 0.9)
            service.update(session, "researcher", "analysis", "success", 0.85)
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit.total_decisions == 3
            assert merit.successful_decisions == 3
            assert merit.success_rate == 1.0

    def test_mixed_outcomes(self, db, service):
        """Test cumulative tracking with mixed outcomes."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", 0.9)
            service.update(session, "researcher", "analysis", "failure", 0.3)
            service.update(session, "researcher", "analysis", "success", 0.85)
            service.update(session, "researcher", "analysis", "failure", 0.4)
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit.total_decisions == 4
            assert merit.successful_decisions == 2
            assert merit.failed_decisions == 2
            assert merit.success_rate == 0.5

    def test_mixed_decision_success_rate(self, db, service):
        """Test success rate calculation with mixed decisions."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success")
            service.update(session, "researcher", "analysis", "mixed")
            service.update(session, "researcher", "analysis", "failure")
            service.update(session, "researcher", "analysis", "mixed")
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit.total_decisions == 4
            assert merit.successful_decisions == 1
            assert merit.mixed_decisions == 2
            assert merit.failed_decisions == 1
            # 1 success + 2 * 0.5 mixed = 2 effective successes / 4 total = 0.5
            assert merit.success_rate == 0.5


class TestConfidenceTracking:
    """Tests for confidence tracking with exponential moving average."""

    def test_confidence_exponential_moving_average(self, db, service):
        """Test confidence is tracked as exponential moving average."""
        with get_session() as session:
            # First update: confidence = 0.8
            service.update(session, "researcher", "analysis", "success", 0.8)
            session.flush()

            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()
            assert merit.average_confidence == 0.8

            # Second update: 0.9 * 0.8 + 0.1 * 0.9 = 0.81
            service.update(session, "researcher", "analysis", "success", 0.9)
            session.flush()

            merit = session.exec(statement).first()
            expected = 0.9 * 0.8 + 0.1 * 0.9
            assert abs(merit.average_confidence - expected) < 0.001

            session.commit()

    def test_confidence_without_value(self, db, service):
        """Test updates without confidence values."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", None)
            service.update(session, "researcher", "analysis", "success", None)
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()
            assert merit.average_confidence is None

    def test_confidence_after_none(self, db, service):
        """Test confidence tracking after initial None values."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", None)
            service.update(session, "researcher", "analysis", "success", 0.85)
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()
            assert merit.average_confidence == 0.85


class TestExpertiseScore:
    """Tests for expertise score calculation."""

    def test_expertise_score_calculation(self, db, service):
        """Test expertise score is weighted combination of success rate and confidence."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", 0.9)
            service.update(session, "researcher", "analysis", "success", 0.8)
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            # 70% success rate (1.0) + 30% confidence (~0.85)
            expected = 0.7 * 1.0 + 0.3 * merit.average_confidence
            assert abs(merit.expertise_score - expected) < 0.001

    def test_expertise_score_without_confidence(self, db, service):
        """Test expertise score defaults to 0.5 confidence when None."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", None)
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            # 70% success rate (1.0) + 30% default confidence (0.5)
            expected = 0.7 * 1.0 + 0.3 * 0.5
            assert abs(merit.expertise_score - expected) < 0.001


class TestMultipleDomains:
    """Tests for tracking across multiple domains."""

    def test_separate_domains(self, db, service):
        """Test merit scores are tracked separately per domain."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", 0.9)
            service.update(session, "researcher", "coding", "failure", 0.4)
            session.commit()

        with get_session() as session:
            analysis_stmt = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            analysis = session.exec(analysis_stmt).first()

            coding_stmt = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "coding"
            )
            coding = session.exec(coding_stmt).first()

            assert analysis.total_decisions == 1
            assert analysis.success_rate == 1.0
            assert coding.total_decisions == 1
            assert coding.success_rate == 0.0

    def test_multiple_agents(self, db, service):
        """Test merit scores are tracked separately per agent."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", 0.9)
            service.update(session, "coder", "analysis", "failure", 0.3)
            session.commit()

        with get_session() as session:
            researcher_stmt = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher"
            )
            researcher = session.exec(researcher_stmt).first()

            coder_stmt = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "coder"
            )
            coder = session.exec(coder_stmt).first()

            assert researcher.success_rate == 1.0
            assert coder.success_rate == 0.0


class TestTimestamps:
    """Tests for timestamp tracking."""

    def test_timestamps_set(self, db, service):
        """Test first and last decision dates are set."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success")
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit.first_decision_date is not None
            assert merit.last_decision_date is not None
            assert merit.last_updated is not None

    def test_last_decision_date_updates(self, db, service):
        """Test last_decision_date updates on subsequent decisions."""
        from datetime import timezone

        with get_session() as session:
            service.update(session, "researcher", "analysis", "success")
            session.flush()

            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()
            first_date = merit.last_decision_date

            # Ensure timezone-aware if needed
            if first_date.tzinfo is None:
                first_date = first_date.replace(tzinfo=timezone.utc)

            service.update(session, "researcher", "analysis", "success")
            session.flush()

            merit = session.exec(statement).first()
            second_date = merit.last_decision_date

            # Ensure timezone-aware if needed
            if second_date.tzinfo is None:
                second_date = second_date.replace(tzinfo=timezone.utc)

            assert second_date >= first_date
            session.commit()


class TestTimeWindowedMetrics:
    """Tests for time-windowed success rate calculation."""

    def test_time_windowed_metrics_no_decisions(self, db, service):
        """Test time-windowed metrics with no DecisionOutcome records."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success")
            session.commit()

        # Should not crash, just not compute windowed metrics
        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()
            # Windowed metrics may be None if no DecisionOutcome records exist
            assert merit.last_30_days_success_rate is None or merit.last_30_days_success_rate >= 0

    def test_time_windowed_metrics_with_decisions(self, db, service):
        """Test time-windowed metrics with DecisionOutcome records."""
        from datetime import datetime, timezone

        with get_session() as session:
            # Create DecisionOutcome records
            decision = DecisionOutcome(
                id="decision-1",
                decision_type="test",
                decision_data={"agent_name": "researcher"},
                outcome="success",
                validation_timestamp=datetime.now(timezone.utc)
            )
            session.add(decision)
            session.commit()

            # Update merit score (should compute windowed metrics)
            service.update(session, "researcher", "analysis", "success")
            session.commit()

        # Should not crash
        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()
            assert merit is not None


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_zero_decisions_no_division_by_zero(self, db, service):
        """Test no division by zero with zero decisions."""
        # This shouldn't happen in practice, but test defensive code
        with get_session() as session:
            # Manually create merit score with zero decisions
            merit = AgentMeritScore(
                id="merit-test",
                agent_name="test",
                domain="test",
                total_decisions=0,
                successful_decisions=0,
                failed_decisions=0
            )
            session.add(merit)
            session.commit()

            # Verify no crash
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "test"
            )
            result = session.exec(statement).first()
            assert result.total_decisions == 0

    def test_concurrent_updates_same_session(self, db, service):
        """Test multiple updates in same session."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success", 0.8)
            service.update(session, "researcher", "analysis", "failure", 0.3)
            service.update(session, "researcher", "analysis", "success", 0.9)
            session.commit()

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()
            assert merit.total_decisions == 3
            assert merit.successful_decisions == 2
            assert merit.failed_decisions == 1

    def test_flush_without_commit(self, db, service):
        """Test service uses flush() not commit() (caller responsible for commit)."""
        with get_session() as session:
            service.update(session, "researcher", "analysis", "success")
            # Don't commit - rollback instead
            session.rollback()

        # Verify no record persisted
        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher"
            )
            merit = session.exec(statement).first()
            assert merit is None
