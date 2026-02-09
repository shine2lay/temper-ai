"""Tests for strategy learning store."""
import pytest
from unittest.mock import Mock
from datetime import datetime, timezone, timedelta
from src.self_improvement.strategy_learning import StrategyLearningStore
from src.self_improvement.data_models import StrategyOutcome


class TestStrategyLearningStore:
    """Test StrategyLearningStore functionality."""

    def test_initialization(self):
        """Test store initialization."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)

        store = StrategyLearningStore(mock_db)

        assert store.db is mock_db
        # Should have created table
        assert mock_db.transaction.called

    def test_record_outcome(self):
        """Test recording strategy outcome."""
        mock_db = Mock()
        mock_conn = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)

        store = StrategyLearningStore(mock_db)

        now = datetime.now(timezone.utc)
        outcome = StrategyOutcome(
            id="outcome-123",
            strategy_name="ollama_model_selection",
            problem_type="quality_low",
            agent_name="test_agent",
            experiment_id="exp-456",
            was_winner=True,
            actual_quality_improvement=0.35,
            actual_speed_improvement=0.15,
            actual_cost_improvement=-0.10,
            composite_score=0.30,
            confidence=0.95,
            sample_size=50,
            recorded_at=now,
            context={"model": "qwen3-next"}
        )

        store.record_outcome(outcome)

        # Should have executed INSERT
        assert mock_conn.execute.call_count >= 1

    def test_get_outcomes_for_strategy_basic(self):
        """Test getting outcomes for strategy."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)

        now = datetime.now(timezone.utc)
        mock_db.query.return_value = [
            {
                "id": "out1",
                "strategy_name": "test_strategy",
                "problem_type": "quality_low",
                "agent_name": "agent1",
                "experiment_id": "exp1",
                "was_winner": 1,
                "actual_quality_improvement": 0.3,
                "actual_speed_improvement": 0.1,
                "actual_cost_improvement": -0.05,
                "composite_score": 0.25,
                "confidence": 0.9,
                "sample_size": 50,
                "recorded_at": now.isoformat(),
                "context": '{"key": "value"}'
            }
        ]

        store = StrategyLearningStore(mock_db)
        outcomes = store.get_outcomes_for_strategy("test_strategy")

        assert len(outcomes) == 1
        assert outcomes[0].strategy_name == "test_strategy"
        assert outcomes[0].was_winner is True
        assert outcomes[0].composite_score == 0.25

    def test_get_outcomes_for_strategy_with_problem_type(self):
        """Test getting outcomes filtered by problem type."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = []

        store = StrategyLearningStore(mock_db)
        store.get_outcomes_for_strategy(
            "test_strategy",
            problem_type="quality_low"
        )

        # Check query includes problem_type filter
        call_args = mock_db.query.call_args
        query = call_args[0][0]
        assert "problem_type = ?" in query

    def test_get_outcomes_for_strategy_with_confidence(self):
        """Test getting outcomes filtered by confidence."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = []

        store = StrategyLearningStore(mock_db)
        store.get_outcomes_for_strategy(
            "test_strategy",
            min_confidence=0.8
        )

        # Check query includes confidence filter
        call_args = mock_db.query.call_args
        assert call_args[0][1][1] == 0.8  # Second parameter

    def test_get_outcomes_for_strategy_with_time_window(self):
        """Test getting outcomes with time window."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = []

        store = StrategyLearningStore(mock_db)
        store.get_outcomes_for_strategy(
            "test_strategy",
            days_back=30
        )

        # Check query includes time filter
        call_args = mock_db.query.call_args
        query = call_args[0][0]
        assert "recorded_at >= ?" in query

    def test_get_outcomes_for_strategy_with_limit(self):
        """Test getting outcomes with limit."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = []

        store = StrategyLearningStore(mock_db)
        store.get_outcomes_for_strategy(
            "test_strategy",
            limit=10
        )

        # Check query includes LIMIT
        call_args = mock_db.query.call_args
        query = call_args[0][0]
        assert "LIMIT" in query

    def test_get_average_improvement_basic(self):
        """Test getting average improvement."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [
            {"weighted_avg": 0.25, "count": 10}
        ]

        store = StrategyLearningStore(mock_db)
        avg = store.get_average_improvement(
            "test_strategy",
            "quality_low"
        )

        assert avg == 0.25

    def test_get_average_improvement_no_data(self):
        """Test getting average improvement with no data."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [{"weighted_avg": None, "count": 0}]

        store = StrategyLearningStore(mock_db)
        avg = store.get_average_improvement(
            "test_strategy",
            "quality_low"
        )

        assert avg is None

    def test_get_average_improvement_empty_result(self):
        """Test getting average improvement with empty result."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = []

        store = StrategyLearningStore(mock_db)
        avg = store.get_average_improvement(
            "test_strategy",
            "quality_low"
        )

        assert avg is None

    def test_get_average_improvement_different_metrics(self):
        """Test getting average for different metrics."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [
            {"weighted_avg": 0.3, "count": 5}
        ]

        store = StrategyLearningStore(mock_db)

        # Test different valid metrics
        for metric in ["composite_score", "actual_quality_improvement", "confidence"]:
            avg = store.get_average_improvement(
                "test_strategy",
                "quality_low",
                metric=metric
            )
            assert avg == 0.3

    def test_get_average_improvement_invalid_metric(self):
        """Test that invalid metric raises ValueError."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)

        store = StrategyLearningStore(mock_db)

        with pytest.raises(ValueError, match="Invalid metric"):
            store.get_average_improvement(
                "test_strategy",
                "quality_low",
                metric="invalid_metric"
            )

    def test_get_win_rate_basic(self):
        """Test getting win rate."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [
            {"wins": 7, "total": 10}
        ]

        store = StrategyLearningStore(mock_db)
        win_rate = store.get_win_rate("test_strategy")

        assert win_rate == 0.7

    def test_get_win_rate_with_problem_type(self):
        """Test getting win rate filtered by problem type."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [
            {"wins": 5, "total": 5}
        ]

        store = StrategyLearningStore(mock_db)
        win_rate = store.get_win_rate(
            "test_strategy",
            problem_type="quality_low"
        )

        assert win_rate == 1.0

    def test_get_win_rate_no_data(self):
        """Test getting win rate with no data."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [{"wins": 0, "total": 0}]

        store = StrategyLearningStore(mock_db)
        win_rate = store.get_win_rate("test_strategy")

        assert win_rate == 0.0

    def test_get_win_rate_with_time_window(self):
        """Test getting win rate with time window."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [
            {"wins": 3, "total": 5}
        ]

        store = StrategyLearningStore(mock_db)
        win_rate = store.get_win_rate(
            "test_strategy",
            days_back=90
        )

        # Check query includes time filter
        call_args = mock_db.query.call_args
        query = call_args[0][0]
        assert "recorded_at >= ?" in query
        assert win_rate == 0.6

    def test_get_sample_count_basic(self):
        """Test getting sample count."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [{"count": 15}]

        store = StrategyLearningStore(mock_db)
        count = store.get_sample_count("test_strategy")

        assert count == 15

    def test_get_sample_count_with_problem_type(self):
        """Test getting sample count filtered by problem type."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [{"count": 8}]

        store = StrategyLearningStore(mock_db)
        count = store.get_sample_count(
            "test_strategy",
            problem_type="quality_low"
        )

        assert count == 8

    def test_get_sample_count_no_data(self):
        """Test getting sample count with no data."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = []

        store = StrategyLearningStore(mock_db)
        count = store.get_sample_count("test_strategy")

        assert count == 0

    def test_get_sample_count_with_time_window(self):
        """Test getting sample count with time window."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)
        mock_db.query.return_value = [{"count": 5}]

        store = StrategyLearningStore(mock_db)
        count = store.get_sample_count(
            "test_strategy",
            days_back=30
        )

        # Check query includes time filter
        call_args = mock_db.query.call_args
        query = call_args[0][0]
        assert "recorded_at >= ?" in query
        assert count == 5

    def test_row_to_outcome(self):
        """Test converting database row to StrategyOutcome."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)

        store = StrategyLearningStore(mock_db)

        now = datetime.now(timezone.utc)
        row = {
            "id": "out1",
            "strategy_name": "test_strategy",
            "problem_type": "quality_low",
            "agent_name": "agent1",
            "experiment_id": "exp1",
            "was_winner": 1,
            "actual_quality_improvement": 0.3,
            "actual_speed_improvement": 0.1,
            "actual_cost_improvement": -0.05,
            "composite_score": 0.25,
            "confidence": 0.9,
            "sample_size": 50,
            "recorded_at": now.isoformat(),
            "context": '{"key": "value"}'
        }

        outcome = store._row_to_outcome(row)

        assert isinstance(outcome, StrategyOutcome)
        assert outcome.id == "out1"
        assert outcome.strategy_name == "test_strategy"
        assert outcome.was_winner is True
        assert outcome.composite_score == 0.25
        assert outcome.context == {"key": "value"}

    def test_row_to_outcome_no_context(self):
        """Test converting row without context."""
        mock_db = Mock()
        mock_db.transaction.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.transaction.return_value.__exit__ = Mock(return_value=False)

        store = StrategyLearningStore(mock_db)

        now = datetime.now(timezone.utc)
        row = {
            "id": "out1",
            "strategy_name": "test_strategy",
            "problem_type": "quality_low",
            "agent_name": "agent1",
            "experiment_id": "exp1",
            "was_winner": 0,
            "actual_quality_improvement": 0.1,
            "actual_speed_improvement": 0.0,
            "actual_cost_improvement": 0.0,
            "composite_score": 0.1,
            "confidence": 0.8,
            "sample_size": 30,
            "recorded_at": now.isoformat()
        }

        outcome = store._row_to_outcome(row)

        assert outcome.context == {}
        assert outcome.was_winner is False
