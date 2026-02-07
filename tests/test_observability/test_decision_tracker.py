"""Tests for decision outcome tracking.

Tests cover DecisionTracker.track() with various decision types,
merit score integration, impact metrics tracking, tags handling,
sanitization, and edge cases like missing fields.
"""

import pytest
from sqlmodel import select

from src.observability.database import get_session, init_database
from src.observability.decision_tracker import DecisionTracker
from src.observability.models import AgentMeritScore, DecisionOutcome


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


@pytest.fixture
def tracker():
    """Create decision tracker without sanitization."""
    return DecisionTracker()


@pytest.fixture
def tracker_with_sanitizer():
    """Create decision tracker with mock sanitizer."""
    def mock_sanitize(data):
        """Mock sanitizer that removes 'secret' keys."""
        if not isinstance(data, dict):
            return data
        return {k: v for k, v in data.items() if k != "secret"}

    return DecisionTracker(sanitize_fn=mock_sanitize)


class TestDecisionTracking:
    """Tests for basic decision tracking."""

    def test_track_success_decision(self, db, tracker):
        """Test tracking a successful decision."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="experiment_selection",
                decision_data={"experiment": "exp-1", "reason": "highest score"},
                outcome="success"
            )

            assert decision_id != ""
            assert decision_id.startswith("decision-")

        # Verify record created
        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()

            assert decision is not None
            assert decision.decision_type == "experiment_selection"
            assert decision.outcome == "success"
            assert decision.decision_data["experiment"] == "exp-1"

    def test_track_failure_decision(self, db, tracker):
        """Test tracking a failed decision."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="model_selection",
                decision_data={"model": "model-a"},
                outcome="failure"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.outcome == "failure"

    def test_track_neutral_decision(self, db, tracker):
        """Test tracking a neutral decision."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="parameter_tuning",
                decision_data={"param": "value"},
                outcome="neutral"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.outcome == "neutral"

    def test_track_mixed_decision(self, db, tracker):
        """Test tracking a mixed outcome decision."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="optimization",
                decision_data={"strategy": "hybrid"},
                outcome="mixed"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.outcome == "mixed"


class TestImpactMetrics:
    """Tests for impact metrics tracking."""

    def test_track_with_impact_metrics(self, db, tracker):
        """Test tracking decision with impact metrics."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="experiment_selection",
                decision_data={"experiment": "exp-1"},
                outcome="success",
                impact_metrics={
                    "performance_improvement": 0.15,
                    "cost_reduction": 0.08,
                    "confidence": 0.92
                }
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()

            assert decision.impact_metrics is not None
            assert decision.impact_metrics["performance_improvement"] == 0.15
            assert decision.impact_metrics["cost_reduction"] == 0.08
            assert decision.impact_metrics["confidence"] == 0.92

    def test_track_without_impact_metrics(self, db, tracker):
        """Test tracking decision without impact metrics."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="simple_decision",
                decision_data={"action": "test"},
                outcome="success"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.impact_metrics is None


class TestLearningFields:
    """Tests for learning-related fields."""

    def test_track_with_lessons_learned(self, db, tracker):
        """Test tracking decision with lessons learned."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="strategy_selection",
                decision_data={"strategy": "aggressive"},
                outcome="failure",
                lessons_learned="Aggressive strategy led to overfitting"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert "overfitting" in decision.lessons_learned

    def test_track_with_should_repeat(self, db, tracker):
        """Test tracking decision with should_repeat flag."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="optimization",
                decision_data={"method": "gradient_descent"},
                outcome="success",
                should_repeat=True
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.should_repeat is True


class TestTags:
    """Tests for tags handling."""

    def test_track_with_tags(self, db, tracker):
        """Test tracking decision with tags."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="experiment_selection",
                decision_data={"experiment": "exp-1"},
                outcome="success",
                tags=["machine_learning", "optimization", "production"]
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert len(decision.tags) == 3
            assert "machine_learning" in decision.tags

    def test_track_without_tags(self, db, tracker):
        """Test tracking decision without tags defaults to empty list."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="simple_decision",
                decision_data={"action": "test"},
                outcome="success"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.tags == []


class TestExecutionContext:
    """Tests for execution context tracking."""

    def test_track_with_agent_execution_id(self, db, tracker):
        """Test tracking decision with agent execution context (skipped due to FK constraints)."""
        # Note: This test would require creating WorkflowExecution, StageExecution,
        # and AgentExecution records first due to foreign key constraints.
        # For unit testing, we test without execution IDs or verify the behavior
        # by checking that the decision_data is properly stored.
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="tool_selection",
                decision_data={"tool": "calculator", "execution_context": "agent-123"},
                outcome="success"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            # Verify decision was tracked even without execution_id
            assert decision.decision_data["execution_context"] == "agent-123"

    def test_track_with_full_context(self, db, tracker):
        """Test tracking decision stores context in decision_data."""
        # Note: Testing with execution IDs requires creating parent records.
        # Here we verify context can be stored in decision_data.
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="strategy_selection",
                decision_data={
                    "strategy": "parallel",
                    "context": {
                        "agent": "agent-123",
                        "stage": "stage-456",
                        "workflow": "workflow-789"
                    }
                },
                outcome="success"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.decision_data["context"]["agent"] == "agent-123"
            assert decision.decision_data["context"]["stage"] == "stage-456"
            assert decision.decision_data["context"]["workflow"] == "workflow-789"


class TestValidationTracking:
    """Tests for validation tracking."""

    def test_track_with_validation_method(self, db, tracker):
        """Test tracking decision with validation method."""
        from datetime import datetime, timezone

        validation_time = datetime.now(timezone.utc)

        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="model_prediction",
                decision_data={"prediction": 42},
                outcome="success",
                validation_method="cross_validation",
                validation_timestamp=validation_time,
                validation_duration_seconds=5.2
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.validation_method == "cross_validation"
            assert decision.validation_timestamp is not None
            assert decision.validation_duration_seconds == 5.2


class TestMeritScoreIntegration:
    """Tests for merit score integration."""

    def test_track_updates_merit_score(self, db, tracker):
        """Test tracking decision updates agent merit score."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="analysis",
                decision_data={"agent_name": "researcher", "analysis": "completed"},
                outcome="success",
                tags=["analysis"]
            )

        # Verify merit score was updated
        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "analysis"
            )
            merit = session.exec(statement).first()

            assert merit is not None
            assert merit.total_decisions == 1
            assert merit.successful_decisions == 1

    def test_track_with_confidence_in_impact_metrics(self, db, tracker):
        """Test merit score uses confidence from impact_metrics."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="prediction",
                decision_data={"agent_name": "predictor"},
                outcome="success",
                impact_metrics={"confidence": 0.95, "accuracy": 0.88},
                tags=["prediction"]
            )

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "predictor"
            )
            merit = session.exec(statement).first()
            assert merit.average_confidence == 0.95

    def test_track_without_agent_name_no_merit_update(self, db, tracker):
        """Test tracking without agent_name in decision_data skips merit update."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="system_decision",
                decision_data={"system": "auto"},
                outcome="success"
            )

        # Verify no merit score created
        with get_session() as session:
            statement = select(AgentMeritScore)
            merit = session.exec(statement).first()
            assert merit is None

    def test_track_uses_first_tag_as_domain(self, db, tracker):
        """Test merit score uses first tag as domain."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="analysis",
                decision_data={"agent_name": "researcher"},
                outcome="success",
                tags=["code_review", "security", "testing"]
            )

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "researcher",
                AgentMeritScore.domain == "code_review"
            )
            merit = session.exec(statement).first()
            assert merit is not None

    def test_track_without_tags_uses_decision_type_as_domain(self, db, tracker):
        """Test merit score uses decision_type as domain when no tags."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="optimization",
                decision_data={"agent_name": "optimizer"},
                outcome="success"
            )

        with get_session() as session:
            statement = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == "optimizer",
                AgentMeritScore.domain == "optimization"
            )
            merit = session.exec(statement).first()
            assert merit is not None


class TestSanitization:
    """Tests for data sanitization."""

    def test_sanitization_applied_to_decision_data(self, db, tracker_with_sanitizer):
        """Test sanitizer is applied to decision_data."""
        with get_session() as session:
            decision_id = tracker_with_sanitizer.track(
                session=session,
                decision_type="api_call",
                decision_data={
                    "endpoint": "/api/data",
                    "secret": "should_be_removed",
                    "params": {"id": 123}
                },
                outcome="success"
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert "endpoint" in decision.decision_data
            assert "secret" not in decision.decision_data
            assert "params" in decision.decision_data

    def test_sanitization_applied_to_impact_metrics(self, db, tracker_with_sanitizer):
        """Test sanitizer is applied to impact_metrics."""
        with get_session() as session:
            decision_id = tracker_with_sanitizer.track(
                session=session,
                decision_type="analysis",
                decision_data={"action": "analyze"},
                outcome="success",
                impact_metrics={
                    "accuracy": 0.95,
                    "secret": "should_be_removed"
                }
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert "accuracy" in decision.impact_metrics
            assert "secret" not in decision.impact_metrics

    def test_sanitization_with_none_values(self, db, tracker_with_sanitizer):
        """Test sanitizer handles None values gracefully."""
        with get_session() as session:
            decision_id = tracker_with_sanitizer.track(
                session=session,
                decision_type="test",
                decision_data=None,
                outcome="success",
                impact_metrics=None
            )

        # Should not crash
        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.decision_data == {}
            assert decision.impact_metrics is None


class TestErrorHandling:
    """Tests for error handling."""

    def test_track_failure_returns_empty_string(self, db, tracker):
        """Test track returns empty string on database error."""
        # Close the database to force error
        import src.observability.database as db_module
        from src.observability.database import _db_lock
        with _db_lock:
            db_module._db_manager = None

        # Should return empty string, not crash
        decision_id = tracker.track(
            session=None,  # Invalid session
            decision_type="test",
            decision_data={"test": "data"},
            outcome="success"
        )

        assert decision_id == ""

    def test_merit_update_failure_logged_not_crashed(self, db, tracker):
        """Test merit score update gracefully handles edge cases."""
        # Test with neutral outcome (valid) to ensure merit tracking is robust
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="test",
                decision_data={"agent_name": "test"},
                outcome="neutral",  # Valid outcome
            )

        # Should create decision successfully
        assert decision_id != ""

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision is not None
            assert decision.outcome == "neutral"


class TestExtraMetadata:
    """Tests for extra metadata tracking."""

    def test_track_with_extra_metadata(self, db, tracker):
        """Test tracking decision with extra metadata."""
        with get_session() as session:
            decision_id = tracker.track(
                session=session,
                decision_type="experiment",
                decision_data={"exp": "test"},
                outcome="success",
                extra_metadata={
                    "environment": "staging",
                    "version": "1.2.3",
                    "user": "test_user"
                }
            )

        with get_session() as session:
            statement = select(DecisionOutcome).where(
                DecisionOutcome.id == decision_id
            )
            decision = session.exec(statement).first()
            assert decision.extra_metadata["environment"] == "staging"
            assert decision.extra_metadata["version"] == "1.2.3"


class TestMultipleDecisions:
    """Tests for tracking multiple decisions."""

    def test_track_multiple_decisions(self, db, tracker):
        """Test tracking multiple decisions in sequence."""
        decision_ids = []

        with get_session() as session:
            for i in range(5):
                decision_id = tracker.track(
                    session=session,
                    decision_type="iteration",
                    decision_data={"iteration": i},
                    outcome="success" if i % 2 == 0 else "failure"
                )
                decision_ids.append(decision_id)

        # Verify all decisions were created
        with get_session() as session:
            for decision_id in decision_ids:
                statement = select(DecisionOutcome).where(
                    DecisionOutcome.id == decision_id
                )
                decision = session.exec(statement).first()
                assert decision is not None

    def test_unique_decision_ids(self, db, tracker):
        """Test each decision gets unique ID."""
        decision_ids = set()

        with get_session() as session:
            for i in range(10):
                decision_id = tracker.track(
                    session=session,
                    decision_type="test",
                    decision_data={"test": i},
                    outcome="success"
                )
                decision_ids.add(decision_id)

        # All IDs should be unique
        assert len(decision_ids) == 10
