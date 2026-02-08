"""Strategy learning store for tracking and querying strategy outcomes.

Provides storage and retrieval of strategy outcomes to enable strategies
to learn from past experiments and refine their impact estimates over time.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.constants.durations import DAYS_90
from src.constants.probabilities import PROB_VERY_HIGH
from src.self_improvement.data_models import StrategyOutcome

logger = logging.getLogger(__name__)


class StrategyLearningStore:
    """
    Stores and queries strategy outcomes for learning.

    Tracks actual results from strategy applications (experiments) and
    provides queries for strategies to refine their impact estimates.

    Uses the coordination database for storage.

    Example:
        >>> store = StrategyLearningStore(coord_db)
        >>>
        >>> # Record outcome after experiment
        >>> outcome = StrategyOutcome(
        ...     id="outcome-123",
        ...     strategy_name="ollama_model_selection",
        ...     problem_type="quality_low",
        ...     agent_name="researcher",
        ...     experiment_id="exp-456",
        ...     was_winner=True,
        ...     actual_quality_improvement=0.35,
        ...     actual_speed_improvement=0.15,
        ...     actual_cost_improvement=-0.10,
        ...     composite_score=0.30,
        ...     confidence=0.95,
        ...     sample_size=50
        ... )
        >>> store.record_outcome(outcome)
        >>>
        >>> # Query historical outcomes for a strategy
        >>> outcomes = store.get_outcomes_for_strategy(
        ...     strategy_name="ollama_model_selection",
        ...     problem_type="quality_low",
        ...     min_confidence=0.80
        ... )
        >>> avg_improvement = store.get_average_improvement(
        ...     strategy_name="ollama_model_selection",
        ...     problem_type="quality_low"
        ... )
    """

    def __init__(self, db: Any) -> None:
        """
        Initialize learning store with database connection.

        Args:
            db: Database instance (coordination service database)
        """
        self.db = db
        self._ensure_table_exists()

    def _ensure_table_exists(self) -> None:
        """Create strategy_outcomes table if it doesn't exist."""
        with self.db.transaction() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_outcomes (
                    id TEXT PRIMARY KEY,
                    strategy_name TEXT NOT NULL,
                    problem_type TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    experiment_id TEXT NOT NULL,
                    was_winner INTEGER NOT NULL,
                    actual_quality_improvement REAL NOT NULL,
                    actual_speed_improvement REAL NOT NULL,
                    actual_cost_improvement REAL NOT NULL,
                    composite_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    sample_size INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    context TEXT,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
                )
            """)

            # Create indexes for efficient queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_strategy
                ON strategy_outcomes(strategy_name)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_strategy_problem
                ON strategy_outcomes(strategy_name, problem_type)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_recorded_at
                ON strategy_outcomes(recorded_at)
            """)

        logger.info("Strategy outcomes table initialized")

    def record_outcome(self, outcome: StrategyOutcome) -> None:
        """
        Record a strategy outcome.

        Args:
            outcome: StrategyOutcome to store
        """
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO strategy_outcomes
                (id, strategy_name, problem_type, agent_name, experiment_id,
                 was_winner, actual_quality_improvement, actual_speed_improvement,
                 actual_cost_improvement, composite_score, confidence, sample_size,
                 recorded_at, context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.id,
                    outcome.strategy_name,
                    outcome.problem_type,
                    outcome.agent_name,
                    outcome.experiment_id,
                    1 if outcome.was_winner else 0,
                    outcome.actual_quality_improvement,
                    outcome.actual_speed_improvement,
                    outcome.actual_cost_improvement,
                    outcome.composite_score,
                    outcome.confidence,
                    outcome.sample_size,
                    outcome.recorded_at.isoformat(),
                    json.dumps(outcome.context),
                ),
            )

        logger.info(
            f"Recorded strategy outcome: {outcome.strategy_name} "
            f"for {outcome.problem_type} (winner={outcome.was_winner})"
        )

    def get_outcomes_for_strategy(
        self,
        strategy_name: str,
        problem_type: Optional[str] = None,
        min_confidence: float = 0.0,
        days_back: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[StrategyOutcome]:
        """
        Get historical outcomes for a strategy.

        Args:
            strategy_name: Name of strategy to query
            problem_type: Optional problem type filter
            min_confidence: Minimum confidence threshold (default: 0.0)
            days_back: Optional time window in days (None = all time)
            limit: Optional result limit

        Returns:
            List of StrategyOutcome objects matching criteria
        """
        query = """
            SELECT * FROM strategy_outcomes
            WHERE strategy_name = ?
              AND confidence >= ?
        """
        params: List[Any] = [strategy_name, min_confidence]

        if problem_type:
            query += " AND problem_type = ?"
            params.append(problem_type)

        if days_back:
            cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
            query += " AND recorded_at >= ?"
            params.append(cutoff)

        query += " ORDER BY recorded_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = self.db.query(query, tuple(params))

        return [self._row_to_outcome(row) for row in rows]

    def get_average_improvement(
        self,
        strategy_name: str,
        problem_type: str,
        metric: str = "composite_score",
        min_confidence: float = PROB_VERY_HIGH,
        days_back: Optional[int] = DAYS_90
    ) -> Optional[float]:
        """
        Get average improvement for a strategy on a problem type.

        Uses weighted average by confidence to give more weight to
        high-confidence results.

        Args:
            strategy_name: Name of strategy
            problem_type: Type of problem
            metric: Metric to average (composite_score, actual_quality_improvement, etc.)
            min_confidence: Minimum confidence threshold
            days_back: Time window in days (None = all time)

        Returns:
            Weighted average improvement, or None if no data
        """
        # Whitelist valid metric column names to prevent SQL injection
        allowed_metrics = {
            "composite_score", "actual_quality_improvement",
            "predicted_improvement", "confidence",
        }
        if metric not in allowed_metrics:
            raise ValueError(f"Invalid metric '{metric}'. Must be one of: {allowed_metrics}")
        query = f"""
            SELECT
                SUM({metric} * confidence) / SUM(confidence) as weighted_avg,
                COUNT(*) as count
            FROM strategy_outcomes
            WHERE strategy_name = ?
              AND problem_type = ?
              AND confidence >= ?
        """  # noqa: S608  # nosec B608 — metric validated against whitelist above
        params: List[Any] = [strategy_name, problem_type, min_confidence]

        if days_back:
            cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
            query += " AND recorded_at >= ?"
            params.append(cutoff)

        rows = self.db.query(query, tuple(params))

        if not rows or rows[0]["count"] == 0:
            return None

        result = rows[0]["weighted_avg"]
        return float(result) if result is not None else None

    def get_win_rate(
        self,
        strategy_name: str,
        problem_type: Optional[str] = None,
        days_back: Optional[int] = DAYS_90
    ) -> float:
        """
        Get win rate for a strategy.

        Args:
            strategy_name: Name of strategy
            problem_type: Optional problem type filter
            days_back: Time window in days (None = all time)

        Returns:
            Win rate from 0.0 to 1.0
        """
        query = """
            SELECT
                SUM(CASE WHEN was_winner = 1 THEN 1 ELSE 0 END) as wins,
                COUNT(*) as total
            FROM strategy_outcomes
            WHERE strategy_name = ?
        """
        params: List[Any] = [strategy_name]

        if problem_type:
            query += " AND problem_type = ?"
            params.append(problem_type)

        if days_back:
            cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
            query += " AND recorded_at >= ?"
            params.append(cutoff)

        rows = self.db.query(query, tuple(params))

        if not rows or rows[0]["total"] == 0:
            return 0.0

        return float(rows[0]["wins"]) / float(rows[0]["total"])

    def get_sample_count(
        self,
        strategy_name: str,
        problem_type: Optional[str] = None,
        days_back: Optional[int] = None
    ) -> int:
        """
        Get number of outcome samples for a strategy.

        Args:
            strategy_name: Name of strategy
            problem_type: Optional problem type filter
            days_back: Time window in days (None = all time)

        Returns:
            Number of recorded outcomes
        """
        query = "SELECT COUNT(*) as count FROM strategy_outcomes WHERE strategy_name = ?"
        params: List[Any] = [strategy_name]

        if problem_type:
            query += " AND problem_type = ?"
            params.append(problem_type)

        if days_back:
            cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
            query += " AND recorded_at >= ?"
            params.append(cutoff)

        rows = self.db.query(query, tuple(params))
        return rows[0]["count"] if rows else 0

    def _row_to_outcome(self, row: Dict[str, Any]) -> StrategyOutcome:
        """Convert database row to StrategyOutcome."""
        return StrategyOutcome(
            id=row["id"],
            strategy_name=row["strategy_name"],
            problem_type=row["problem_type"],
            agent_name=row["agent_name"],
            experiment_id=row["experiment_id"],
            was_winner=bool(row["was_winner"]),
            actual_quality_improvement=row["actual_quality_improvement"],
            actual_speed_improvement=row["actual_speed_improvement"],
            actual_cost_improvement=row["actual_cost_improvement"],
            composite_score=row["composite_score"],
            confidence=row["confidence"],
            sample_size=row["sample_size"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            context=json.loads(row["context"]) if row.get("context") else {},
        )
