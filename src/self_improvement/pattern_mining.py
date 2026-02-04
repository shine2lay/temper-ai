"""Pattern mining for M5 self-improvement system.

Analyzes experiment history to discover recurring patterns that can guide
future improvement decisions. Patterns include:
- Strategy effectiveness by problem type
- Configuration patterns that consistently improve performance
- Agent-specific optimization strategies
"""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from src.self_improvement.strategies.strategy import LearnedPattern
from src.self_improvement.strategy_learning import StrategyLearningStore

logger = logging.getLogger(__name__)


@dataclass
class PatternCandidate:
    """Candidate pattern before statistical validation."""
    strategy_name: str
    problem_type: str
    sample_count: int
    win_rate: float
    avg_improvement: float
    agent_names: List[str]


class PatternMiner:
    """
    Mines experiment history for recurring patterns.

    Analyzes historical strategy outcomes to identify patterns like:
    - "Strategy X consistently solves problem type Y"
    - "Configuration change Z reliably improves metric M"
    - "Agent type A benefits most from strategy B"

    Discovered patterns are stored as LearnedPattern objects with
    confidence scores based on statistical significance.

    Example:
        >>> miner = PatternMiner(learning_store)
        >>>
        >>> # Mine patterns with statistical thresholds
        >>> patterns = miner.mine_patterns(
        ...     min_support=10,  # At least 10 observations
        ...     min_confidence=0.80,  # 80% success rate
        ...     min_win_rate=0.60  # Strategy wins 60% of time
        ... )
        >>>
        >>> for pattern in patterns:
        ...     print(f"{pattern.description} (confidence={pattern.confidence:.2f})")
    """

    def __init__(self, learning_store: StrategyLearningStore):
        """
        Initialize pattern miner with learning store.

        Args:
            learning_store: StrategyLearningStore for querying outcomes
        """
        self.learning_store = learning_store

    def mine_patterns(
        self,
        min_support: int = 10,
        min_confidence: float = 0.80,
        min_win_rate: float = 0.60,
        min_improvement: float = 0.05,
        days_back: Optional[int] = 90
    ) -> List[LearnedPattern]:
        """
        Mine patterns from experiment history.

        Args:
            min_support: Minimum number of observations to consider a pattern
            min_confidence: Minimum confidence score (0.0-1.0) from statistical analysis
            min_win_rate: Minimum win rate (0.0-1.0) for strategy to be considered effective
            min_improvement: Minimum average improvement (fraction) to be meaningful
            days_back: Time window in days (None = all time)

        Returns:
            List of LearnedPattern objects representing discovered patterns

        Example:
            >>> patterns = miner.mine_patterns(
            ...     min_support=15,
            ...     min_confidence=0.85,
            ...     min_win_rate=0.65
            ... )
            >>> # Patterns: strategy + problem_type combinations that work well
        """
        patterns = []

        # Get all strategy + problem_type combinations
        candidates = self._find_pattern_candidates(days_back)

        logger.info(f"Found {len(candidates)} pattern candidates")

        # Filter and validate candidates
        for candidate in candidates:
            # Check minimum support
            if candidate.sample_count < min_support:
                continue

            # Check minimum win rate
            if candidate.win_rate < min_win_rate:
                continue

            # Check minimum improvement
            if candidate.avg_improvement < min_improvement:
                continue

            # Calculate confidence score
            # Confidence increases with:
            # 1. Sample size (more data = more confident)
            # 2. Win rate (higher win rate = more confident)
            # 3. Improvement magnitude (larger improvement = more confident)
            confidence = self._calculate_confidence(
                sample_count=candidate.sample_count,
                win_rate=candidate.win_rate,
                avg_improvement=candidate.avg_improvement
            )

            # Check minimum confidence
            if confidence < min_confidence:
                continue

            # Create learned pattern
            pattern = LearnedPattern(
                pattern_type=f"strategy_effectiveness_{candidate.problem_type}",
                description=(
                    f"Strategy '{candidate.strategy_name}' consistently improves "
                    f"'{candidate.problem_type}' (win rate: {candidate.win_rate:.0%}, "
                    f"avg improvement: {candidate.avg_improvement:.1%})"
                ),
                support=candidate.sample_count,
                confidence=confidence,
                evidence={
                    "strategy_name": candidate.strategy_name,
                    "problem_type": candidate.problem_type,
                    "win_rate": candidate.win_rate,
                    "avg_improvement": candidate.avg_improvement,
                    "sample_count": candidate.sample_count,
                    "agent_names": candidate.agent_names,
                }
            )

            patterns.append(pattern)
            logger.info(
                f"Discovered pattern: {candidate.strategy_name} for {candidate.problem_type} "
                f"(confidence={confidence:.2f}, support={candidate.sample_count})"
            )

        logger.info(f"Mined {len(patterns)} patterns meeting criteria")
        return patterns

    def _find_pattern_candidates(self, days_back: Optional[int]) -> List[PatternCandidate]:
        """
        Find all strategy + problem_type combinations with sufficient data.

        Args:
            days_back: Time window in days (None = all time)

        Returns:
            List of PatternCandidate objects
        """
        candidates = []

        # Query all unique strategy + problem_type combinations
        # We need to query the database directly to get groupings
        query = """
            SELECT
                strategy_name,
                problem_type,
                COUNT(*) as sample_count,
                SUM(CASE WHEN was_winner = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
                AVG(composite_score) as avg_improvement,
                GROUP_CONCAT(DISTINCT agent_name) as agent_names
            FROM strategy_outcomes
        """

        params = []
        if days_back:
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
            query += " WHERE recorded_at >= ?"
            params.append(cutoff)

        query += """
            GROUP BY strategy_name, problem_type
            HAVING COUNT(*) >= 3
            ORDER BY sample_count DESC
        """

        rows = self.learning_store.db.query(query, tuple(params))

        for row in rows:
            agent_names = row["agent_names"].split(",") if row["agent_names"] else []

            candidates.append(PatternCandidate(
                strategy_name=row["strategy_name"],
                problem_type=row["problem_type"],
                sample_count=row["sample_count"],
                win_rate=row["win_rate"],
                avg_improvement=row["avg_improvement"],
                agent_names=agent_names,
            ))

        return candidates

    def _calculate_confidence(
        self,
        sample_count: int,
        win_rate: float,
        avg_improvement: float
    ) -> float:
        """
        Calculate confidence score for a pattern.

        Confidence is based on:
        1. Sample size (more samples = higher confidence)
        2. Win rate (higher win rate = higher confidence)
        3. Improvement magnitude (larger improvements = higher confidence)

        Args:
            sample_count: Number of observations
            win_rate: Fraction of times strategy won (0.0-1.0)
            avg_improvement: Average improvement fraction

        Returns:
            Confidence score from 0.0 to 1.0
        """
        # Sample size confidence (asymptotic to 1.0)
        # Reaches 0.9 at 50 samples, 0.95 at 100 samples
        sample_confidence = 1.0 - (1.0 / (1.0 + sample_count / 50.0))

        # Win rate confidence (linear with win rate)
        # 60% win rate = 0.6 confidence, 100% = 1.0 confidence
        win_confidence = win_rate

        # Improvement magnitude confidence
        # 5% improvement = 0.5, 20% = 0.8, 50%+ = 1.0
        improvement_confidence = min(1.0, avg_improvement / 0.5 + 0.5)

        # Weighted combination
        # Sample size is most important, then win rate, then improvement
        confidence = (
            0.5 * sample_confidence +
            0.3 * win_confidence +
            0.2 * improvement_confidence
        )

        return min(1.0, max(0.0, confidence))

    def get_patterns_for_problem_type(
        self,
        problem_type: str,
        min_confidence: float = 0.80
    ) -> List[LearnedPattern]:
        """
        Get learned patterns for a specific problem type.

        Useful for detection phase to suggest strategies based on patterns.

        Args:
            problem_type: Type of problem (quality_low, cost_high, etc.)
            min_confidence: Minimum confidence threshold

        Returns:
            List of relevant patterns sorted by confidence
        """
        all_patterns = self.mine_patterns(min_confidence=min_confidence)

        # Filter for this problem type
        relevant_patterns = [
            p for p in all_patterns
            if p.evidence.get("problem_type") == problem_type
        ]

        # Sort by confidence (descending)
        relevant_patterns.sort(key=lambda p: p.confidence, reverse=True)

        return relevant_patterns

    def get_strategy_insights(self, strategy_name: str) -> Dict[str, Any]:
        """
        Get insights about a specific strategy's performance.

        Args:
            strategy_name: Name of strategy to analyze

        Returns:
            Dictionary with strategy insights
        """
        # Get all outcomes for this strategy
        outcomes = self.learning_store.get_outcomes_for_strategy(
            strategy_name=strategy_name,
            min_confidence=0.0  # Include all outcomes
        )

        if not outcomes:
            return {
                "strategy_name": strategy_name,
                "total_experiments": 0,
                "insights": "No data available"
            }

        # Aggregate metrics
        total = len(outcomes)
        wins = sum(1 for o in outcomes if o.was_winner)
        win_rate = wins / total if total > 0 else 0.0

        # Average improvements
        avg_quality = sum(o.actual_quality_improvement for o in outcomes) / total
        avg_speed = sum(o.actual_speed_improvement for o in outcomes) / total
        avg_cost = sum(o.actual_cost_improvement for o in outcomes) / total

        # Problem type breakdown
        problem_types = {}
        for outcome in outcomes:
            pt = outcome.problem_type
            if pt not in problem_types:
                problem_types[pt] = {"count": 0, "wins": 0}
            problem_types[pt]["count"] += 1
            if outcome.was_winner:
                problem_types[pt]["wins"] += 1

        # Calculate win rates by problem type
        for pt, stats in problem_types.items():
            stats["win_rate"] = stats["wins"] / stats["count"]

        return {
            "strategy_name": strategy_name,
            "total_experiments": total,
            "overall_win_rate": win_rate,
            "avg_quality_improvement": avg_quality,
            "avg_speed_improvement": avg_speed,
            "avg_cost_improvement": avg_cost,
            "problem_type_performance": problem_types,
            "best_problem_types": sorted(
                problem_types.items(),
                key=lambda x: x[1]["win_rate"],
                reverse=True
            )[:3]  # Top 3 problem types
        }
