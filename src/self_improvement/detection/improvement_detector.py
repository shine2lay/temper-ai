"""
ImprovementDetector orchestrator for M5 Phase 3.

Coordinates problem detection and strategy selection to generate improvement proposals.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from src.constants.durations import DAYS_PER_WEEK, HOURS_PER_DAY
from src.constants.limits import DEFAULT_BATCH_SIZE
from src.self_improvement.detection.improvement_proposal import ImprovementProposal
from src.self_improvement.detection.problem_detector import (
    ProblemDetectionDataError as DetectorInsufficientDataError,
)
from src.self_improvement.detection.problem_detector import (
    ProblemDetector,
)
from src.self_improvement.detection.problem_models import PerformanceProblem, ProblemSeverity
from src.self_improvement.performance_analyzer import (
    PerformanceAnalyzer,
)
from src.self_improvement.performance_analyzer import (
    PerformanceDataError as AnalyzerInsufficientDataError,
)
from src.self_improvement.performance_comparison import compare_profiles
from src.self_improvement.strategies.registry import StrategyRegistry

logger = logging.getLogger(__name__)


class ImprovementDetectionError(Exception):
    """Base exception for improvement detection errors."""
    pass


class NoBaselineError(ImprovementDetectionError):
    """Raised when baseline is missing and cannot be calculated."""
    pass


class ImprovementDataError(ImprovementDetectionError):
    """Raised when too few executions for reliable detection."""
    pass


class ComponentError(ImprovementDetectionError):
    """Raised when dependent component fails."""
    pass


class ImprovementDetector:
    """
    Orchestrates improvement detection for M5 Phase 3 (DETECT).

    Coordinates the detection of performance problems and the selection of
    improvement strategies, generating actionable improvement proposals.

    Core workflow:
    1. Retrieve baseline and current performance profiles
    2. Compare profiles to identify degradation
    3. Detect specific performance problems
    4. Match problems to applicable strategies
    5. Generate improvement proposals (problem + strategy pairs)

    Example:
        >>> from src.database import get_session
        >>>
        >>> with get_session() as session:
        ...     detector = ImprovementDetector(session)
        ...     proposals = detector.detect_improvements("product_extractor")
        ...
        ...     for proposal in proposals:
        ...         print(proposal.get_summary())
        ...         # "HIGH priority: prompt_tuning for product_extractor (quality_low, est. +15%)"
    """

    def __init__(
        self,
        session: Session,
        problem_detector: Optional[ProblemDetector] = None,
        strategy_registry: Optional[StrategyRegistry] = None,
        baseline_storage_path: Optional[Path] = None,
    ):
        """
        Initialize improvement detector.

        Args:
            session: SQLModel session for database access
            problem_detector: Custom ProblemDetector (uses default if None)
            strategy_registry: Custom StrategyRegistry (creates empty if None)
            baseline_storage_path: Path for baseline storage (uses default if None)
        """
        self.session = session
        self.analyzer = PerformanceAnalyzer(
            session=session,
            baseline_storage_path=baseline_storage_path,
        )
        self.problem_detector = problem_detector or ProblemDetector()
        self.strategy_registry = strategy_registry or StrategyRegistry()

        logger.info(
            "Initialized ImprovementDetector with "
            f"{len(self.strategy_registry.get_all_strategies())} registered strategies"
        )

    def detect_improvements(
        self,
        agent_name: str,
        window_hours: int = HOURS_PER_DAY * DAYS_PER_WEEK,  # 7 days default
        min_executions: int = DEFAULT_BATCH_SIZE,
    ) -> List[ImprovementProposal]:
        """
        Detect improvement opportunities for an agent.

        This is the main entry point for improvement detection. It:
        1. Analyzes current vs baseline performance
        2. Detects performance problems
        3. Matches problems to strategies
        4. Generates prioritized improvement proposals

        Args:
            agent_name: Name of agent to analyze
            window_hours: Time window for current performance analysis (default: 7 days)
            min_executions: Minimum executions required for detection (default: 50)

        Returns:
            List of ImprovementProposal, sorted by priority (CRITICAL first)

        Raises:
            NoBaselineError: If no baseline exists for the agent
            ImprovementDataError: If too few executions for reliable detection
            ComponentError: If dependent component fails

        Example:
            >>> proposals = detector.detect_improvements("code_review_agent")
            >>> if proposals:
            ...     print(f"Found {len(proposals)} improvement opportunities")
            ...     for p in proposals:
            ...         print(f"  - {p.get_summary()}")
            ... else:
            ...     print("No improvements needed")
        """
        logger.info(
            f"Starting improvement detection: agent={agent_name}, "
            f"window_hours={window_hours}, min_executions={min_executions}"
        )

        try:
            # Step 1: Get baseline
            baseline = self._get_baseline(agent_name)
            if baseline is None:
                logger.warning(
                    f"No baseline for {agent_name}, cannot detect improvements"
                )
                raise NoBaselineError(
                    f"No baseline found for agent '{agent_name}'. "
                    "Create a baseline first using PerformanceAnalyzer.store_baseline()"
                )

            logger.info(
                f"Retrieved baseline for {agent_name}: "
                f"{baseline.total_executions} executions from "
                f"{baseline.window_start} to {baseline.window_end}"
            )

            # Step 2: Get current performance
            try:
                current = self.analyzer.analyze_agent_performance(
                    agent_name,
                    window_hours=window_hours,
                    min_executions=min_executions,
                )
            except AnalyzerInsufficientDataError as e:
                raise ImprovementDataError(
                    f"Cannot detect improvements for {agent_name}: {e}"
                ) from e

            logger.info(
                f"Analyzed current performance for {agent_name}: "
                f"{current.total_executions} executions"
            )

            # Step 3: Compare profiles
            comparison = compare_profiles(baseline, current)

            logger.info(
                f"Performance comparison: {comparison.agent_name} "
                f"{'IMPROVED' if comparison.overall_improvement else 'REGRESSED'} "
                f"(score: {comparison.improvement_score:+.2f})"
            )

            # Step 4: Detect problems
            try:
                problems = self.problem_detector.detect_problems(
                    comparison,
                    min_executions=min_executions,
                )
            except DetectorInsufficientDataError as e:
                raise ImprovementDataError(
                    f"Problem detection failed for {agent_name}: {e}"
                ) from e

            if not problems:
                logger.info(f"No problems detected for {agent_name}")
                return []

            logger.info(
                f"Detected {len(problems)} problems for {agent_name}: "
                f"{[p.problem_type.value for p in problems]}"
            )

            # Step 5: Generate proposals
            proposals = self._generate_proposals(agent_name, baseline, current, problems)

            if not proposals:
                logger.warning(
                    f"No applicable strategies found for {len(problems)} problems"
                )
            else:
                logger.info(
                    f"Generated {len(proposals)} improvement proposals for {agent_name} "
                    f"({sum(1 for p in proposals if p.priority == 0)} critical)"
                )

            return proposals

        except (NoBaselineError, ImprovementDataError):
            # Re-raise these as-is
            raise
        except Exception as e:
            logger.error(f"Improvement detection failed for {agent_name}: {e}", exc_info=True)
            raise ComponentError(f"Detection failed: {e}") from e

    def _get_baseline(self, agent_name: str) -> Optional[Any]:
        """
        Get baseline profile for agent.

        Args:
            agent_name: Agent name

        Returns:
            AgentPerformanceProfile or None if not found
        """
        try:
            return self.analyzer.get_baseline(agent_name)
        except Exception as e:
            logger.error(f"Failed to retrieve baseline for {agent_name}: {e}")
            return None

    def _generate_proposals(
        self,
        agent_name: str,
        baseline: Any,
        current: Any,
        problems: List[PerformanceProblem],
    ) -> List[ImprovementProposal]:
        """
        Generate improvement proposals for detected problems.

        For each problem, find applicable strategies and create proposals.
        Proposals are sorted by priority (severity-based).

        Args:
            agent_name: Agent name
            baseline: Baseline performance profile
            current: Current performance profile
            problems: List of detected problems

        Returns:
            List of ImprovementProposal, sorted by priority
        """
        proposals = []

        for problem in problems:
            try:
                problem_proposals = self._proposals_for_problem(
                    agent_name,
                    baseline,
                    current,
                    problem,
                )
                proposals.extend(problem_proposals)
            except Exception as e:
                logger.error(
                    f"Failed to generate proposals for {problem.problem_type.value}: {e}",
                    exc_info=True,
                )
                # Continue processing other problems
                continue

        # Sort by priority (0 = highest, 3 = lowest)
        proposals.sort(key=lambda p: p.priority)

        return proposals

    def _proposals_for_problem(
        self,
        agent_name: str,
        baseline: Any,
        current: Any,
        problem: PerformanceProblem,
    ) -> List[ImprovementProposal]:
        """
        Generate proposals for a single problem.

        Finds all applicable strategies for the problem type and creates
        a proposal for each strategy.

        Args:
            agent_name: Agent name
            baseline: Baseline performance profile
            current: Current performance profile
            problem: Performance problem

        Returns:
            List of ImprovementProposal for this problem
        """
        proposals = []

        # Get all registered strategies
        all_strategies = self.strategy_registry.get_all_strategies()

        if not all_strategies:
            logger.warning("No strategies registered in StrategyRegistry")
            return []

        # Find applicable strategies
        applicable_strategies = [
            strategy
            for strategy in all_strategies
            if strategy.is_applicable(problem.problem_type.value)
        ]

        if not applicable_strategies:
            logger.debug(
                f"No applicable strategies for problem type: {problem.problem_type.value}"
            )
            return []

        logger.debug(
            f"Found {len(applicable_strategies)} strategies for "
            f"{problem.problem_type.value}: "
            f"{[s.name for s in applicable_strategies]}"
        )

        # Create proposal for each applicable strategy
        for strategy in applicable_strategies:
            try:
                # Estimate impact (default implementation returns 0.1)
                estimated_impact = strategy.estimate_impact(problem.to_dict())

                # Map severity to priority (0=highest, 3=lowest)
                PRIORITY_CRITICAL = 0
                PRIORITY_HIGH = 1
                PRIORITY_MEDIUM = 2
                PRIORITY_LOW = 3
                severity_to_priority = {
                    ProblemSeverity.CRITICAL: PRIORITY_CRITICAL,
                    ProblemSeverity.HIGH: PRIORITY_HIGH,
                    ProblemSeverity.MEDIUM: PRIORITY_MEDIUM,
                    ProblemSeverity.LOW: PRIORITY_LOW,
                }
                priority = severity_to_priority.get(problem.severity, PRIORITY_MEDIUM)

                # Create proposal
                proposal = ImprovementProposal(
                    proposal_id=ImprovementProposal.generate_id(),
                    agent_name=agent_name,
                    problem=problem,
                    strategy_name=strategy.name,
                    estimated_impact=estimated_impact,
                    baseline_profile=baseline,
                    current_profile=current,
                    priority=priority,
                    extra_metadata={
                        "problem_summary": problem.get_summary(),
                        "strategy_description": getattr(strategy, "description", ""),
                    },
                )

                proposals.append(proposal)

                logger.debug(
                    f"Created proposal: {proposal.get_summary()}"
                )

            except Exception as e:
                logger.error(
                    f"Failed to create proposal for strategy {strategy.name}: {e}",
                    exc_info=True,
                )
                # Continue with other strategies
                continue

        return proposals

    def health_check(self) -> Dict[str, Any]:
        """
        Check health of detector and dependencies.

        Returns:
            Dictionary with health status

        Example:
            >>> health = detector.health_check()
            >>> print(health['status'])
            'healthy'
        """
        try:
            return {
                "status": "healthy",
                "components": {
                    "performance_analyzer": {
                        "status": "healthy",
                        "baseline_storage_path": str(self.analyzer.baseline_storage_path),
                        "baselines_stored": len(self.analyzer.list_baselines()),
                    },
                    "problem_detector": {
                        "status": "healthy",
                        "config": {
                            "quality_threshold": self.problem_detector.config.quality_relative_threshold,
                            "cost_threshold": self.problem_detector.config.cost_relative_threshold,
                            "speed_threshold": self.problem_detector.config.speed_relative_threshold,
                        },
                    },
                    "strategy_registry": {
                        "status": "healthy",
                        "registered_strategies": len(self.strategy_registry.get_all_strategies()),
                        "strategy_names": self.strategy_registry.list_strategy_names(),
                    },
                },
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }
