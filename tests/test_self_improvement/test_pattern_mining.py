"""Tests for pattern mining."""
import pytest
from unittest.mock import Mock
from datetime import datetime, timezone
from src.self_improvement.pattern_mining import PatternMiner, PatternCandidate
from src.self_improvement.strategy_learning import StrategyLearningStore
from src.self_improvement.strategies.strategy import LearnedPattern


class TestPatternMiner:
    """Test PatternMiner functionality."""

    def test_initialization(self):
        """Test miner initialization."""
        learning_store = Mock(spec=StrategyLearningStore)

        miner = PatternMiner(learning_store)

        assert miner.learning_store is learning_store

    def test_calculate_confidence_high_sample_high_win(self):
        """Test confidence with high sample count and win rate."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)

        confidence = miner._calculate_confidence(
            sample_count=100,
            win_rate=0.9,
            avg_improvement=0.3
        )

        # High sample + high win rate + good improvement = high confidence
        assert 0.8 <= confidence <= 1.0

    def test_calculate_confidence_low_sample(self):
        """Test confidence with low sample count."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)

        confidence = miner._calculate_confidence(
            sample_count=5,
            win_rate=0.9,
            avg_improvement=0.3
        )

        # Low sample reduces confidence despite high win rate
        assert confidence < 0.8

    def test_calculate_confidence_low_win_rate(self):
        """Test confidence with low win rate."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)

        confidence = miner._calculate_confidence(
            sample_count=100,
            win_rate=0.4,
            avg_improvement=0.3
        )

        # Low win rate reduces confidence
        assert confidence < 0.7

    def test_calculate_confidence_low_improvement(self):
        """Test confidence with low improvement."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)

        confidence = miner._calculate_confidence(
            sample_count=100,
            win_rate=0.9,
            avg_improvement=0.01
        )

        # Low improvement reduces confidence slightly
        assert confidence < 1.0

    def test_calculate_confidence_boundaries(self):
        """Test confidence stays within 0.0-1.0 range."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)

        # Test extreme values
        confidence_max = miner._calculate_confidence(
            sample_count=1000,
            win_rate=1.0,
            avg_improvement=1.0
        )
        assert 0.0 <= confidence_max <= 1.0

        confidence_min = miner._calculate_confidence(
            sample_count=1,
            win_rate=0.0,
            avg_improvement=0.0
        )
        assert 0.0 <= confidence_min <= 1.0

    def test_get_strategy_insights_no_data(self):
        """Test getting insights when no data available."""
        learning_store = Mock(spec=StrategyLearningStore)
        learning_store.get_outcomes_for_strategy.return_value = []
        miner = PatternMiner(learning_store)

        insights = miner.get_strategy_insights("test_strategy")

        assert insights["strategy_name"] == "test_strategy"
        assert insights["total_experiments"] == 0
        assert "No data available" in insights["insights"]

    def test_get_strategy_insights_with_data(self):
        """Test getting insights with outcome data."""
        learning_store = Mock(spec=StrategyLearningStore)

        # Mock outcomes
        from src.self_improvement.data_models import StrategyOutcome
        now = datetime.now(timezone.utc)
        outcomes = [
            StrategyOutcome(
                id="out1",
                strategy_name="test_strategy",
                problem_type="quality_low",
                agent_name="agent1",
                experiment_id="exp1",
                was_winner=True,
                actual_quality_improvement=0.3,
                actual_speed_improvement=0.1,
                actual_cost_improvement=-0.05,
                composite_score=0.25,
                confidence=0.9,
                sample_size=50,
                recorded_at=now
            ),
            StrategyOutcome(
                id="out2",
                strategy_name="test_strategy",
                problem_type="quality_low",
                agent_name="agent2",
                experiment_id="exp2",
                was_winner=False,
                actual_quality_improvement=0.1,
                actual_speed_improvement=0.05,
                actual_cost_improvement=-0.02,
                composite_score=0.08,
                confidence=0.8,
                sample_size=30,
                recorded_at=now
            ),
        ]
        learning_store.get_outcomes_for_strategy.return_value = outcomes
        miner = PatternMiner(learning_store)

        insights = miner.get_strategy_insights("test_strategy")

        assert insights["strategy_name"] == "test_strategy"
        assert insights["total_experiments"] == 2
        assert insights["overall_win_rate"] == 0.5  # 1 win out of 2
        assert insights["avg_quality_improvement"] == 0.2  # (0.3 + 0.1) / 2
        assert "quality_low" in insights["problem_type_performance"]
        assert insights["problem_type_performance"]["quality_low"]["count"] == 2
        assert insights["problem_type_performance"]["quality_low"]["wins"] == 1

    def test_get_strategy_insights_multiple_problem_types(self):
        """Test insights with multiple problem types."""
        learning_store = Mock(spec=StrategyLearningStore)

        from src.self_improvement.data_models import StrategyOutcome
        now = datetime.now(timezone.utc)
        outcomes = [
            StrategyOutcome(
                id="out1",
                strategy_name="test_strategy",
                problem_type="quality_low",
                agent_name="agent1",
                experiment_id="exp1",
                was_winner=True,
                actual_quality_improvement=0.3,
                actual_speed_improvement=0.0,
                actual_cost_improvement=0.0,
                composite_score=0.3,
                confidence=0.9,
                sample_size=50,
                recorded_at=now
            ),
            StrategyOutcome(
                id="out2",
                strategy_name="test_strategy",
                problem_type="cost_high",
                agent_name="agent2",
                experiment_id="exp2",
                was_winner=True,
                actual_quality_improvement=0.0,
                actual_speed_improvement=0.0,
                actual_cost_improvement=0.4,
                composite_score=0.4,
                confidence=0.85,
                sample_size=40,
                recorded_at=now
            ),
        ]
        learning_store.get_outcomes_for_strategy.return_value = outcomes
        miner = PatternMiner(learning_store)

        insights = miner.get_strategy_insights("test_strategy")

        assert len(insights["problem_type_performance"]) == 2
        assert "quality_low" in insights["problem_type_performance"]
        assert "cost_high" in insights["problem_type_performance"]
        assert insights["problem_type_performance"]["quality_low"]["win_rate"] == 1.0
        assert insights["problem_type_performance"]["cost_high"]["win_rate"] == 1.0

    def test_get_strategy_insights_best_problem_types(self):
        """Test best problem types sorting."""
        learning_store = Mock(spec=StrategyLearningStore)

        from src.self_improvement.data_models import StrategyOutcome
        now = datetime.now(timezone.utc)
        outcomes = [
            # quality_low: 2/3 win rate
            StrategyOutcome(
                id="out1", strategy_name="test_strategy", problem_type="quality_low",
                agent_name="agent1", experiment_id="exp1", was_winner=True,
                actual_quality_improvement=0.3, actual_speed_improvement=0.0,
                actual_cost_improvement=0.0, composite_score=0.3,
                confidence=0.9, sample_size=50, recorded_at=now
            ),
            StrategyOutcome(
                id="out2", strategy_name="test_strategy", problem_type="quality_low",
                agent_name="agent2", experiment_id="exp2", was_winner=True,
                actual_quality_improvement=0.2, actual_speed_improvement=0.0,
                actual_cost_improvement=0.0, composite_score=0.2,
                confidence=0.85, sample_size=40, recorded_at=now
            ),
            StrategyOutcome(
                id="out3", strategy_name="test_strategy", problem_type="quality_low",
                agent_name="agent3", experiment_id="exp3", was_winner=False,
                actual_quality_improvement=0.1, actual_speed_improvement=0.0,
                actual_cost_improvement=0.0, composite_score=0.1,
                confidence=0.8, sample_size=30, recorded_at=now
            ),
            # cost_high: 1/1 win rate (100%)
            StrategyOutcome(
                id="out4", strategy_name="test_strategy", problem_type="cost_high",
                agent_name="agent4", experiment_id="exp4", was_winner=True,
                actual_quality_improvement=0.0, actual_speed_improvement=0.0,
                actual_cost_improvement=0.4, composite_score=0.4,
                confidence=0.9, sample_size=50, recorded_at=now
            ),
        ]
        learning_store.get_outcomes_for_strategy.return_value = outcomes
        miner = PatternMiner(learning_store)

        insights = miner.get_strategy_insights("test_strategy")

        # Best problem types should be sorted by win rate (descending)
        best_types = insights["best_problem_types"]
        assert len(best_types) <= 3  # Top 3
        assert best_types[0][0] == "cost_high"  # 100% win rate
        assert best_types[0][1]["win_rate"] == 1.0
