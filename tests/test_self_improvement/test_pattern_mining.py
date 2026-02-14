"""Tests for pattern mining."""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from src.self_improvement.pattern_mining import (
    PatternMiner,
    PatternCandidate,
    SAMPLE_SIZE_THRESHOLD,
    IMPROVEMENT_THRESHOLD,
    BASE_CONFIDENCE,
    WEIGHT_SAMPLE_SIZE,
    WEIGHT_WIN_RATE,
    WEIGHT_IMPROVEMENT,
    TOP_PROBLEM_TYPES_LIMIT,
)
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


class TestPatternCandidate:
    """Test PatternCandidate dataclass."""

    def test_create_pattern_candidate(self):
        """Test creating a PatternCandidate with all fields."""
        candidate = PatternCandidate(
            strategy_name="prompt_optimization",
            problem_type="quality_low",
            sample_count=25,
            win_rate=0.8,
            avg_improvement=0.15,
            agent_names=["agent1", "agent2"],
        )
        assert candidate.strategy_name == "prompt_optimization"
        assert candidate.problem_type == "quality_low"
        assert candidate.sample_count == 25
        assert candidate.win_rate == 0.8
        assert candidate.avg_improvement == 0.15
        assert candidate.agent_names == ["agent1", "agent2"]


class TestFindPatternCandidates:
    """Test _find_pattern_candidates method."""

    def _make_miner_with_db(self, query_results):
        """Helper to create a PatternMiner with a mocked db.query."""
        learning_store = Mock(spec=StrategyLearningStore)
        mock_db = Mock()
        mock_db.query.return_value = query_results
        learning_store.db = mock_db
        miner = PatternMiner(learning_store)
        return miner, mock_db

    def test_find_candidates_no_results(self):
        """Test _find_pattern_candidates when db returns no rows."""
        miner, mock_db = self._make_miner_with_db([])

        candidates = miner._find_pattern_candidates(days_back=None)

        assert candidates == []
        mock_db.query.assert_called_once()

    def test_find_candidates_with_results(self):
        """Test _find_pattern_candidates returns PatternCandidate objects."""
        rows = [
            {
                "strategy_name": "prompt_opt",
                "problem_type": "quality_low",
                "sample_count": 20,
                "win_rate": 0.75,
                "avg_improvement": 0.12,
                "agent_names": "agent1,agent2",
            },
        ]
        miner, mock_db = self._make_miner_with_db(rows)

        candidates = miner._find_pattern_candidates(days_back=None)

        assert len(candidates) == 1
        assert candidates[0].strategy_name == "prompt_opt"
        assert candidates[0].problem_type == "quality_low"
        assert candidates[0].sample_count == 20
        assert candidates[0].win_rate == 0.75
        assert candidates[0].avg_improvement == 0.12
        assert candidates[0].agent_names == ["agent1", "agent2"]

    def test_find_candidates_empty_agent_names(self):
        """Test _find_pattern_candidates when agent_names is empty string."""
        rows = [
            {
                "strategy_name": "strat1",
                "problem_type": "cost_high",
                "sample_count": 10,
                "win_rate": 0.6,
                "avg_improvement": 0.08,
                "agent_names": "",
            },
        ]
        miner, _ = self._make_miner_with_db(rows)

        candidates = miner._find_pattern_candidates(days_back=None)

        assert len(candidates) == 1
        assert candidates[0].agent_names == []

    def test_find_candidates_with_days_back(self):
        """Test _find_pattern_candidates adds WHERE clause when days_back set."""
        miner, mock_db = self._make_miner_with_db([])

        candidates = miner._find_pattern_candidates(days_back=90)

        assert candidates == []
        # The query should include WHERE recorded_at >= ?
        call_args = mock_db.query.call_args
        query_str = call_args[0][0]
        assert "WHERE recorded_at >= ?" in query_str
        # params tuple should have one item (the cutoff date string)
        params = call_args[0][1]
        assert len(params) == 1

    def test_find_candidates_without_days_back(self):
        """Test _find_pattern_candidates omits WHERE when days_back is None."""
        miner, mock_db = self._make_miner_with_db([])

        miner._find_pattern_candidates(days_back=None)

        call_args = mock_db.query.call_args
        query_str = call_args[0][0]
        assert "WHERE" not in query_str

    def test_find_candidates_multiple_rows(self):
        """Test _find_pattern_candidates with multiple result rows."""
        rows = [
            {
                "strategy_name": "strat_a",
                "problem_type": "quality_low",
                "sample_count": 50,
                "win_rate": 0.9,
                "avg_improvement": 0.2,
                "agent_names": "a1,a2,a3",
            },
            {
                "strategy_name": "strat_b",
                "problem_type": "cost_high",
                "sample_count": 30,
                "win_rate": 0.7,
                "avg_improvement": 0.1,
                "agent_names": "a4",
            },
        ]
        miner, _ = self._make_miner_with_db(rows)

        candidates = miner._find_pattern_candidates(days_back=None)

        assert len(candidates) == 2
        assert candidates[0].strategy_name == "strat_a"
        assert candidates[0].agent_names == ["a1", "a2", "a3"]
        assert candidates[1].strategy_name == "strat_b"
        assert candidates[1].agent_names == ["a4"]


class TestMinePatterns:
    """Test mine_patterns method."""

    def _make_miner_with_candidates(self, candidates):
        """Helper to create a PatternMiner with mocked _find_pattern_candidates."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)
        miner._find_pattern_candidates = Mock(return_value=candidates)
        return miner

    def test_mine_patterns_no_candidates(self):
        """Test mine_patterns with no candidates found."""
        miner = self._make_miner_with_candidates([])

        patterns = miner.mine_patterns()

        assert patterns == []

    def test_mine_patterns_candidate_below_min_support(self):
        """Test mine_patterns filters out candidates with low sample count."""
        candidates = [
            PatternCandidate(
                strategy_name="strat1",
                problem_type="quality_low",
                sample_count=2,  # Below default min_support of 10
                win_rate=0.9,
                avg_improvement=0.3,
                agent_names=["a1"],
            ),
        ]
        miner = self._make_miner_with_candidates(candidates)

        patterns = miner.mine_patterns(min_support=10)

        assert patterns == []

    def test_mine_patterns_candidate_below_min_win_rate(self):
        """Test mine_patterns filters out candidates with low win rate."""
        candidates = [
            PatternCandidate(
                strategy_name="strat1",
                problem_type="quality_low",
                sample_count=50,
                win_rate=0.3,  # Below default min_win_rate of 0.6
                avg_improvement=0.3,
                agent_names=["a1"],
            ),
        ]
        miner = self._make_miner_with_candidates(candidates)

        patterns = miner.mine_patterns(min_win_rate=0.6)

        assert patterns == []

    def test_mine_patterns_candidate_below_min_improvement(self):
        """Test mine_patterns filters out candidates with low improvement."""
        candidates = [
            PatternCandidate(
                strategy_name="strat1",
                problem_type="quality_low",
                sample_count=50,
                win_rate=0.9,
                avg_improvement=0.01,  # Below default min_improvement
                agent_names=["a1"],
            ),
        ]
        miner = self._make_miner_with_candidates(candidates)

        patterns = miner.mine_patterns(min_improvement=0.05)

        assert patterns == []

    def test_mine_patterns_candidate_below_min_confidence(self):
        """Test mine_patterns filters candidates with calculated confidence below threshold."""
        # Low sample count + moderate metrics => low confidence
        candidates = [
            PatternCandidate(
                strategy_name="strat1",
                problem_type="quality_low",
                sample_count=3,
                win_rate=0.6,
                avg_improvement=0.06,
                agent_names=["a1"],
            ),
        ]
        miner = self._make_miner_with_candidates(candidates)

        patterns = miner.mine_patterns(
            min_support=1,
            min_win_rate=0.1,
            min_improvement=0.01,
            min_confidence=0.99,  # Very high threshold
        )

        assert patterns == []

    def test_mine_patterns_returns_valid_pattern(self):
        """Test mine_patterns returns LearnedPattern for valid candidates."""
        candidates = [
            PatternCandidate(
                strategy_name="prompt_optimization",
                problem_type="quality_low",
                sample_count=100,
                win_rate=0.9,
                avg_improvement=0.3,
                agent_names=["agent1", "agent2"],
            ),
        ]
        miner = self._make_miner_with_candidates(candidates)

        patterns = miner.mine_patterns(
            min_support=5,
            min_confidence=0.5,
            min_win_rate=0.5,
            min_improvement=0.05,
        )

        assert len(patterns) == 1
        p = patterns[0]
        assert isinstance(p, LearnedPattern)
        assert p.pattern_type == "strategy_effectiveness_quality_low"
        assert "prompt_optimization" in p.description
        assert "quality_low" in p.description
        assert p.support == 100
        assert 0.5 <= p.confidence <= 1.0
        assert p.evidence["strategy_name"] == "prompt_optimization"
        assert p.evidence["problem_type"] == "quality_low"
        assert p.evidence["win_rate"] == 0.9
        assert p.evidence["sample_count"] == 100
        assert p.evidence["agent_names"] == ["agent1", "agent2"]

    def test_mine_patterns_mixed_candidates(self):
        """Test mine_patterns correctly filters mix of passing and failing candidates."""
        candidates = [
            # Should pass: high metrics
            PatternCandidate(
                strategy_name="good_strat",
                problem_type="quality_low",
                sample_count=100,
                win_rate=0.9,
                avg_improvement=0.3,
                agent_names=["a1"],
            ),
            # Should fail: low sample
            PatternCandidate(
                strategy_name="low_sample",
                problem_type="quality_low",
                sample_count=2,
                win_rate=0.9,
                avg_improvement=0.3,
                agent_names=["a1"],
            ),
            # Should fail: low win rate
            PatternCandidate(
                strategy_name="low_win",
                problem_type="cost_high",
                sample_count=100,
                win_rate=0.2,
                avg_improvement=0.3,
                agent_names=["a1"],
            ),
        ]
        miner = self._make_miner_with_candidates(candidates)

        patterns = miner.mine_patterns(
            min_support=5,
            min_confidence=0.5,
            min_win_rate=0.5,
            min_improvement=0.05,
        )

        assert len(patterns) == 1
        assert patterns[0].evidence["strategy_name"] == "good_strat"


class TestGetPatternsForProblemType:
    """Test get_patterns_for_problem_type method."""

    def test_returns_patterns_for_matching_problem_type(self):
        """Test filtering patterns by problem type."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)

        # Mock mine_patterns to return known patterns
        p1 = LearnedPattern(
            pattern_type="strategy_effectiveness_quality_low",
            description="Strat A for quality_low",
            support=50,
            confidence=0.9,
            evidence={"problem_type": "quality_low", "strategy_name": "strat_a"},
        )
        p2 = LearnedPattern(
            pattern_type="strategy_effectiveness_cost_high",
            description="Strat B for cost_high",
            support=30,
            confidence=0.85,
            evidence={"problem_type": "cost_high", "strategy_name": "strat_b"},
        )
        miner.mine_patterns = Mock(return_value=[p1, p2])

        result = miner.get_patterns_for_problem_type("quality_low")

        assert len(result) == 1
        assert result[0].evidence["problem_type"] == "quality_low"

    def test_returns_empty_for_no_matching_type(self):
        """Test returns empty list when no patterns match the problem type."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)
        miner.mine_patterns = Mock(return_value=[])

        result = miner.get_patterns_for_problem_type("unknown_type")

        assert result == []

    def test_sorts_by_confidence_descending(self):
        """Test patterns are sorted by confidence, highest first."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)

        p_low = LearnedPattern(
            pattern_type="strategy_effectiveness_quality_low",
            description="Low confidence",
            support=10,
            confidence=0.7,
            evidence={"problem_type": "quality_low", "strategy_name": "strat_low"},
        )
        p_high = LearnedPattern(
            pattern_type="strategy_effectiveness_quality_low",
            description="High confidence",
            support=100,
            confidence=0.95,
            evidence={"problem_type": "quality_low", "strategy_name": "strat_high"},
        )
        miner.mine_patterns = Mock(return_value=[p_low, p_high])

        result = miner.get_patterns_for_problem_type("quality_low")

        assert len(result) == 2
        assert result[0].confidence > result[1].confidence
        assert result[0].evidence["strategy_name"] == "strat_high"

    def test_passes_min_confidence_to_mine_patterns(self):
        """Test min_confidence is forwarded to mine_patterns."""
        learning_store = Mock(spec=StrategyLearningStore)
        miner = PatternMiner(learning_store)
        miner.mine_patterns = Mock(return_value=[])

        miner.get_patterns_for_problem_type("quality_low", min_confidence=0.5)

        miner.mine_patterns.assert_called_once_with(min_confidence=0.5)
