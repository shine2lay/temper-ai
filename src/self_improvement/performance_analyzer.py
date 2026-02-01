"""
PerformanceAnalyzer for M5 Self-Improvement System.

Analyzes agent execution metrics over time windows, generating performance
profiles used by ImprovementDetector to identify optimization opportunities.

Design Principles:
- SQL aggregation (100x faster than Python loops)
- Stateless (no caching, no shared state)
- Graceful degradation (handle missing metrics)
- Clear error messages
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path
import logging
import json
import uuid
from sqlmodel import Session, select, func
from sqlalchemy import case, and_

from src.observability.models import AgentExecution
from src.self_improvement.data_models import AgentPerformanceProfile

logger = logging.getLogger(__name__)


class PerformanceAnalysisError(Exception):
    """Base exception for performance analysis errors."""
    pass


class InsufficientDataError(PerformanceAnalysisError):
    """Raised when too few executions for reliable analysis."""
    pass


class DatabaseQueryError(PerformanceAnalysisError):
    """Raised when database query fails."""
    pass


class PerformanceAnalyzer:
    """
    Analyzes agent performance over time windows.

    Core responsibilities:
    1. Query observability database for agent executions
    2. Aggregate built-in metrics (success_rate, cost, duration, tokens)
    3. Aggregate custom metrics (quality_score, etc.) - future
    4. Generate AgentPerformanceProfile with statistical aggregates

    Example:
        >>> from src.observability.database import get_session
        >>> with get_session() as session:
        ...     analyzer = PerformanceAnalyzer(session)
        ...     profile = analyzer.analyze_agent_performance("code_review_agent")
        ...     print(f"Success rate: {profile.get_metric('success_rate', 'mean')}")

    Design:
        - SQL aggregation for performance (vs Python loops)
        - Stateless (no instance variables beyond session)
        - Graceful degradation (missing metrics return partial profile)
        - Fail fast (invalid inputs raise immediately)
    """

    def __init__(self, session: Session, baseline_storage_path: Optional[Path] = None):
        """
        Initialize analyzer with database session.

        Args:
            session: SQLModel session for database queries
            baseline_storage_path: Optional path for baseline storage (default: .baselines/)
        """
        self.session = session

        # Set up baseline storage directory
        if baseline_storage_path is None:
            baseline_storage_path = Path(".baselines")
        self.baseline_storage_path = Path(baseline_storage_path)
        self.baseline_storage_path.mkdir(parents=True, exist_ok=True)

    def analyze_agent_performance(
        self,
        agent_name: str,
        window_hours: int = 168,  # 7 days default
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
        min_executions: int = 10,
        include_failed: bool = False
    ) -> AgentPerformanceProfile:
        """
        Analyze agent performance over time window.

        Args:
            agent_name: Name of agent to analyze
            window_hours: Hours to look back (default 168 = 7 days)
            window_start: Override start time (optional)
            window_end: Override end time (optional, default: now)
            min_executions: Minimum executions required (default 10)
            include_failed: Include failed executions in analysis (default False)

        Returns:
            AgentPerformanceProfile with aggregated metrics

        Raises:
            InsufficientDataError: If fewer than min_executions found
            DatabaseQueryError: If database query fails
            ValueError: If invalid parameters

        Example:
            >>> profile = analyzer.analyze_agent_performance("my_agent")
            >>> print(f"Executions: {profile.total_executions}")
            >>> print(f"Success rate: {profile.get_metric('success_rate', 'mean'):.2%}")
            >>> print(f"Avg duration: {profile.get_metric('duration_seconds', 'mean'):.2f}s")
        """
        # Validate inputs
        if not agent_name or not agent_name.strip():
            raise ValueError("agent_name cannot be empty")
        if min_executions < 1:
            raise ValueError(f"min_executions must be >= 1, got {min_executions}")
        if window_hours < 1:
            raise ValueError(f"window_hours must be >= 1, got {window_hours}")

        # Calculate time window
        if window_end is None:
            window_end = datetime.now(timezone.utc)
        if window_start is None:
            window_start = window_end - timedelta(hours=window_hours)

        # Validate time window
        if window_start >= window_end:
            raise ValueError(
                f"window_start ({window_start}) must be before window_end ({window_end})"
            )

        logger.info(
            f"Analyzing performance: agent={agent_name}, "
            f"window={window_start.isoformat()} to {window_end.isoformat()}"
        )

        try:
            # Query built-in metrics from agent_executions
            metrics_data = self._query_builtin_metrics(
                agent_name, window_start, window_end, include_failed
            )

            total_executions = metrics_data.pop("total_executions", 0)

            if total_executions < min_executions:
                raise InsufficientDataError(
                    f"Insufficient data for {agent_name}: "
                    f"{total_executions} executions found "
                    f"(minimum {min_executions} required)"
                )

            # Create profile
            profile = AgentPerformanceProfile(
                agent_name=agent_name,
                window_start=window_start,
                window_end=window_end,
                total_executions=total_executions,
                metrics=metrics_data
            )

            logger.info(
                f"Generated profile: agent={agent_name}, "
                f"executions={profile.total_executions}, "
                f"metrics={len(profile.metrics)}"
            )

            return profile

        except InsufficientDataError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Performance analysis failed: {e}", exc_info=True)
            raise DatabaseQueryError(f"Query failed: {e}") from e

    def _query_builtin_metrics(
        self,
        agent_name: str,
        window_start: datetime,
        window_end: datetime,
        include_failed: bool
    ) -> Dict[str, Any]:
        """
        Query built-in metrics from agent_executions table.

        Aggregates:
        - success_rate (mean)
        - duration_seconds (mean)
        - cost_usd (mean)
        - total_tokens (mean)

        Args:
            agent_name: Name of agent to query
            window_start: Start of time window
            window_end: End of time window
            include_failed: Whether to include failed executions

        Returns:
            Dict with metric names as keys, aggregates as values
            Always includes "total_executions" key
        """
        # Build query filters
        filters = [
            AgentExecution.agent_name == agent_name,
            AgentExecution.start_time >= window_start,
            AgentExecution.start_time < window_end
        ]

        if not include_failed:
            filters.append(AgentExecution.status == "completed")

        # Aggregate query
        statement = select(
            func.count(AgentExecution.id).label("total"),
            func.sum(
                case((AgentExecution.status == "completed", 1), else_=0)
            ).label("completed"),
            func.avg(AgentExecution.duration_seconds).label("avg_duration"),
            func.avg(AgentExecution.estimated_cost_usd).label("avg_cost"),
            func.avg(AgentExecution.total_tokens).label("avg_tokens"),
        ).where(and_(*filters))

        result = self.session.exec(statement).first()

        if not result or result.total == 0:
            return {"total_executions": 0}

        # Calculate success_rate
        success_rate = result.completed / result.total if result.total > 0 else 0.0

        # Build metrics dict
        metrics = {
            "total_executions": result.total,
            "success_rate": {"mean": success_rate}
        }

        # Add duration metrics (if available)
        if result.avg_duration is not None:
            metrics["duration_seconds"] = {"mean": float(result.avg_duration)}

        # Add cost metrics (if available)
        if result.avg_cost is not None:
            metrics["cost_usd"] = {"mean": float(result.avg_cost)}

        # Add token metrics (if available)
        if result.avg_tokens is not None:
            metrics["total_tokens"] = {"mean": float(result.avg_tokens)}

        logger.debug(
            f"Queried metrics: agent={agent_name}, "
            f"executions={metrics['total_executions']}, "
            f"success_rate={success_rate:.2%}"
        )

        return metrics

    def get_baseline(
        self,
        agent_name: str,
        window_days: int = 30
    ) -> Optional[AgentPerformanceProfile]:
        """
        Get historical baseline performance for comparison.

        First checks for a stored baseline, then falls back to calculating from data.

        Args:
            agent_name: Name of agent
            window_days: Days to use for baseline (default 30)

        Returns:
            AgentPerformanceProfile or None if insufficient data

        Example:
            >>> baseline = analyzer.get_baseline("my_agent", window_days=30)
            >>> if baseline:
            ...     current = analyzer.analyze_agent_performance("my_agent", window_hours=168)
            ...     delta = current.get_metric("success_rate", "mean") - baseline.get_metric("success_rate", "mean")
            ...     print(f"Success rate change: {delta:+.2%}")
        """
        # First, try to retrieve stored baseline
        stored_baseline = self.retrieve_baseline(agent_name)
        if stored_baseline is not None:
            logger.info(
                f"Retrieved stored baseline for {agent_name}: "
                f"{stored_baseline.total_executions} executions, "
                f"window {stored_baseline.window_start} to {stored_baseline.window_end}"
            )
            return stored_baseline

        # Fallback: Calculate baseline from data if no stored baseline exists
        logger.info(f"No stored baseline found for {agent_name}, calculating from data")
        try:
            return self.analyze_agent_performance(
                agent_name,
                window_hours=window_days * 24,
                min_executions=50  # Higher threshold for baseline
            )
        except InsufficientDataError:
            logger.warning(
                f"Insufficient data for baseline: agent={agent_name}, "
                f"window_days={window_days}"
            )
            return None

    def store_baseline(
        self,
        agent_name: str,
        profile: Optional[AgentPerformanceProfile] = None,
        window_days: int = 30
    ) -> AgentPerformanceProfile:
        """
        Store a baseline performance profile for future comparisons.

        If profile is not provided, calculates a new baseline from recent data.

        Args:
            agent_name: Name of agent
            profile: Optional pre-calculated profile to store
            window_days: Days to use if calculating new baseline (default 30)

        Returns:
            The stored AgentPerformanceProfile

        Raises:
            InsufficientDataError: If insufficient data to create baseline
            IOError: If storage fails

        Example:
            >>> # Calculate and store baseline
            >>> profile = analyzer.analyze_agent_performance("my_agent", window_hours=720)
            >>> analyzer.store_baseline("my_agent", profile)

            >>> # Or let it calculate automatically
            >>> analyzer.store_baseline("my_agent", window_days=30)
        """
        # If no profile provided, calculate one
        if profile is None:
            logger.info(f"Calculating baseline for {agent_name} using {window_days} days")
            profile = self.analyze_agent_performance(
                agent_name,
                window_hours=window_days * 24,
                min_executions=50  # Higher threshold for baseline
            )

        # Generate profile ID if not present
        if profile.profile_id is None:
            profile.profile_id = str(uuid.uuid4())

        # Ensure agent_name matches
        if profile.agent_name != agent_name:
            raise ValueError(
                f"Profile agent_name '{profile.agent_name}' does not match "
                f"provided agent_name '{agent_name}'"
            )

        # Store to file system
        baseline_file = self.baseline_storage_path / f"{agent_name}_baseline.json"
        try:
            with open(baseline_file, 'w') as f:
                json.dump(profile.to_dict(), f, indent=2)

            logger.info(
                f"Stored baseline for {agent_name}: "
                f"{profile.total_executions} executions, "
                f"window {profile.window_start} to {profile.window_end}"
            )

            return profile

        except Exception as e:
            logger.error(f"Failed to store baseline for {agent_name}: {e}")
            raise IOError(f"Baseline storage failed: {e}") from e

    def retrieve_baseline(
        self,
        agent_name: str
    ) -> Optional[AgentPerformanceProfile]:
        """
        Retrieve a stored baseline performance profile.

        Args:
            agent_name: Name of agent

        Returns:
            AgentPerformanceProfile if baseline exists, None otherwise

        Example:
            >>> baseline = analyzer.retrieve_baseline("my_agent")
            >>> if baseline:
            ...     print(f"Baseline from {baseline.window_start}")
        """
        baseline_file = self.baseline_storage_path / f"{agent_name}_baseline.json"

        if not baseline_file.exists():
            logger.debug(f"No stored baseline found for {agent_name}")
            return None

        try:
            with open(baseline_file, 'r') as f:
                data = json.load(f)

            profile = AgentPerformanceProfile.from_dict(data)

            logger.debug(
                f"Retrieved baseline for {agent_name}: "
                f"{profile.total_executions} executions"
            )

            return profile

        except Exception as e:
            logger.warning(f"Failed to retrieve baseline for {agent_name}: {e}")
            return None

    def delete_baseline(
        self,
        agent_name: str
    ) -> bool:
        """
        Delete a stored baseline for an agent.

        Args:
            agent_name: Name of agent

        Returns:
            True if baseline was deleted, False if it didn't exist

        Example:
            >>> analyzer.delete_baseline("my_agent")
            True
        """
        baseline_file = self.baseline_storage_path / f"{agent_name}_baseline.json"

        if not baseline_file.exists():
            logger.debug(f"No baseline to delete for {agent_name}")
            return False

        try:
            baseline_file.unlink()
            logger.info(f"Deleted baseline for {agent_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete baseline for {agent_name}: {e}")
            raise IOError(f"Baseline deletion failed: {e}") from e

    def list_baselines(self) -> List[str]:
        """
        List all agent names with stored baselines.

        Returns:
            List of agent names

        Example:
            >>> agents_with_baselines = analyzer.list_baselines()
            >>> print(f"Found {len(agents_with_baselines)} baselines")
        """
        baselines = []

        for baseline_file in self.baseline_storage_path.glob("*_baseline.json"):
            # Extract agent name from filename (remove "_baseline.json")
            agent_name = baseline_file.stem.replace("_baseline", "")
            baselines.append(agent_name)

        logger.debug(f"Found {len(baselines)} stored baselines")
        return sorted(baselines)

    def analyze_all_agents(
        self,
        window_hours: int = 168,
        min_executions: int = 10
    ) -> List[AgentPerformanceProfile]:
        """
        Analyze performance for all agents with sufficient data.

        Args:
            window_hours: Hours to look back (default 168 = 7 days)
            min_executions: Minimum executions per agent (default 10)

        Returns:
            List of AgentPerformanceProfiles (may be empty)

        Example:
            >>> profiles = analyzer.analyze_all_agents()
            >>> for profile in profiles:
            ...     success = profile.get_metric("success_rate", "mean")
            ...     print(f"{profile.agent_name}: {success:.1%} success rate")
        """
        # Calculate time window
        window_end = datetime.now(timezone.utc)
        window_start = window_end - timedelta(hours=window_hours)

        # Get unique agent names in time window
        statement = select(AgentExecution.agent_name).where(
            and_(
                AgentExecution.start_time >= window_start,
                AgentExecution.start_time < window_end
            )
        ).distinct()

        agent_names = self.session.exec(statement).all()

        logger.info(
            f"Found {len(agent_names)} agents with executions in window "
            f"({window_start.isoformat()} to {window_end.isoformat()})"
        )

        # Analyze each agent
        profiles = []
        for agent_name in agent_names:
            try:
                profile = self.analyze_agent_performance(
                    agent_name,
                    window_hours=window_hours,
                    window_start=window_start,
                    window_end=window_end,
                    min_executions=min_executions
                )
                profiles.append(profile)
            except InsufficientDataError:
                logger.debug(
                    f"Skipping {agent_name}: insufficient data "
                    f"(< {min_executions} executions)"
                )
                continue

        logger.info(
            f"Analyzed {len(profiles)} agents with sufficient data "
            f"({len(agent_names) - len(profiles)} skipped)"
        )

        return profiles
