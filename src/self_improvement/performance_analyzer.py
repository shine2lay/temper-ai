"""
PerformanceAnalyzer for M5 Self-Improvement System.

Analyzes agent execution metrics over time windows, generating performance
profiles used by ImprovementDetector to identify optimization opportunities.

Refactored to follow Single Responsibility Principle:
- MetricsAggregator: SQL-based metric queries
- BaselineStorage: File I/O and persistence
- AgentPathValidator: Security validation
- PerformanceAnalyzer: Orchestration and public API

Design Principles:
- Thin orchestrator (delegates to specialized modules)
- Backward compatible public API
- Clear error messages
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from sqlmodel import Session

from src.constants.durations import HOURS_PER_WEEK
from src.constants.limits import DEFAULT_BATCH_SIZE, THRESHOLD_MEDIUM_COUNT
from src.self_improvement.baseline_storage import BaselineStorage
from src.self_improvement.data_models import AgentPerformanceProfile
from src.self_improvement.metrics_aggregator import MetricsAggregator

logger = logging.getLogger(__name__)

# Default baseline window for performance analysis
DEFAULT_BASELINE_WINDOW_DAYS = 30  # Use last 30 days for baseline calculation


class PerformanceAnalysisError(Exception):
    """Base exception for performance analysis errors."""
    pass


class PerformanceDataError(PerformanceAnalysisError):
    """Raised when too few executions for reliable analysis."""
    pass


class DatabaseQueryError(PerformanceAnalysisError):
    """Raised when database query fails."""
    pass


class PerformanceAnalyzer:
    """
    Orchestrates agent performance analysis over time windows.

    Thin orchestrator that delegates to specialized modules:
    - MetricsAggregator: SQL queries and metric calculations
    - BaselineStorage: File I/O and persistence
    - AgentPathValidator: Security validation (via BaselineStorage)

    Public API remains unchanged for backward compatibility.

    Example:
        >>> from src.database import get_session
        >>> with get_session() as session:
        ...     analyzer = PerformanceAnalyzer(session)
        ...     profile = analyzer.analyze_agent_performance("code_review_agent")
        ...     print(f"Success rate: {profile.get_metric('success_rate', 'mean')}")

    Design:
        - Delegates to specialized modules (SRP)
        - Stateless (no instance variables beyond session and modules)
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

        # Initialize specialized modules
        self.metrics = MetricsAggregator(session)
        self.storage = BaselineStorage(
            baseline_storage_path if baseline_storage_path else Path(".baselines")
        )

    @property
    def baseline_storage_path(self) -> Path:
        """
        Get baseline storage path.

        DEPRECATED: This property is kept for backward compatibility.
        New code should use self.storage.storage_path directly.

        Returns:
            Path to baseline storage directory
        """
        return self.storage.storage_path

    def _validate_baseline_path(self, agent_name: str) -> Path:
        """
        Validate agent_name and return a safe path within baseline storage.

        DEPRECATED: This method is kept for backward compatibility with existing tests.
        New code should use BaselineStorage directly.

        Args:
            agent_name: Name of agent to validate

        Returns:
            Resolved Path guaranteed to be within baseline_storage_path

        Raises:
            ValueError: If agent_name is invalid or path escapes storage directory
        """
        # Delegate to BaselineStorage's validator
        return self.storage.validator.validate_and_resolve(agent_name)

    def _validate_analysis_inputs(
        self,
        agent_name: str,
        min_executions: int,
        window_hours: int
    ) -> None:
        """Validate inputs for performance analysis."""
        if not agent_name or not agent_name.strip():
            raise ValueError("agent_name cannot be empty")
        if min_executions < 1:
            raise ValueError(f"min_executions must be >= 1, got {min_executions}")
        if window_hours < 1:
            raise ValueError(f"window_hours must be >= 1, got {window_hours}")

    def _calculate_time_window(
        self,
        window_hours: int,
        window_start: Optional[datetime],
        window_end: Optional[datetime]
    ) -> tuple[datetime, datetime]:
        """Calculate and validate time window."""
        if window_end is None:
            window_end = datetime.now(timezone.utc)
        if window_start is None:
            window_start = window_end - timedelta(hours=window_hours)

        if window_start >= window_end:
            raise ValueError(
                f"window_start ({window_start}) must be before window_end ({window_end})"
            )

        return window_start, window_end

    def _build_performance_profile(
        self,
        agent_name: str,
        window_start: datetime,
        window_end: datetime,
        include_failed: bool,
        min_executions: int
    ) -> AgentPerformanceProfile:
        """Build performance profile from metrics data."""
        metrics_data = self.metrics.aggregate_metrics(
            agent_name, window_start, window_end, include_failed
        )

        total_executions = metrics_data.pop("total_executions", 0)

        if total_executions < min_executions:
            raise PerformanceDataError(
                f"Insufficient data for {agent_name}: "
                f"{total_executions} executions found "
                f"(minimum {min_executions} required)"
            )

        return AgentPerformanceProfile(
            agent_name=agent_name,
            window_start=window_start,
            window_end=window_end,
            total_executions=total_executions,
            metrics=metrics_data
        )

    def analyze_agent_performance(
        self,
        agent_name: str,
        window_hours: int = HOURS_PER_WEEK,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
        min_executions: int = THRESHOLD_MEDIUM_COUNT,
        include_failed: bool = False
    ) -> AgentPerformanceProfile:
        """Analyze agent performance over time window."""
        # Validate inputs
        self._validate_analysis_inputs(agent_name, min_executions, window_hours)

        # Calculate time window
        window_start, window_end = self._calculate_time_window(
            window_hours, window_start, window_end
        )

        logger.info(
            f"Analyzing performance: agent={agent_name}, "
            f"window={window_start.isoformat()} to {window_end.isoformat()}"
        )

        try:
            profile = self._build_performance_profile(
                agent_name, window_start, window_end, include_failed, min_executions
            )

            logger.info(
                f"Generated profile: agent={agent_name}, "
                f"executions={profile.total_executions}, "
                f"metrics={len(profile.metrics)}"
            )

            return profile

        except PerformanceDataError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Performance analysis failed: {e}", exc_info=True)
            raise DatabaseQueryError(f"Query failed: {e}") from e


    def get_baseline(
        self,
        agent_name: str,
        window_days: int = DEFAULT_BASELINE_WINDOW_DAYS
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
        # Delegate to BaselineStorage for retrieval
        stored_baseline = self.storage.retrieve(agent_name)
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
                min_executions=DEFAULT_BATCH_SIZE  # Higher threshold for baseline
            )
        except PerformanceDataError:
            logger.warning(
                f"Insufficient data for baseline: agent={agent_name}, "
                f"window_days={window_days}"
            )
            return None

    def store_baseline(
        self,
        agent_name: str,
        profile: Optional[AgentPerformanceProfile] = None,
        window_days: int = DEFAULT_BASELINE_WINDOW_DAYS
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
            PerformanceDataError: If insufficient data to create baseline
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
                min_executions=DEFAULT_BATCH_SIZE  # Higher threshold for baseline
            )

        # Delegate to BaselineStorage for persistence
        return self.storage.store(profile, agent_name)

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
        # Delegate to BaselineStorage
        return self.storage.retrieve(agent_name)

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
        # Delegate to BaselineStorage
        return self.storage.delete(agent_name)

    def list_baselines(self) -> List[str]:
        """
        List all agent names with stored baselines.

        Returns:
            List of agent names

        Example:
            >>> agents_with_baselines = analyzer.list_baselines()
            >>> print(f"Found {len(agents_with_baselines)} baselines")
        """
        # Delegate to BaselineStorage
        return self.storage.list_all()

    def analyze_all_agents(
        self,
        window_hours: int = HOURS_PER_WEEK,
        min_executions: int = THRESHOLD_MEDIUM_COUNT
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

        # Delegate to MetricsAggregator to get agent names
        agent_names = self.metrics.get_agent_names_in_window(window_start, window_end)

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
            except PerformanceDataError:
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
