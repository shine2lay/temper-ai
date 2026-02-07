"""
Experiment orchestrator for M5 self-improvement A/B testing.

Coordinates experiment creation, variant assignment, result collection,
and statistical analysis to determine winning agent configurations.

Database access uses SQLModel ORM via M5Experiment and M5ExecutionResult
models (no raw SQL).

Session management: Uses session-per-operation pattern via a context-manager
factory to avoid long-lived sessions that accumulate stale state.
"""
import hashlib
import logging
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

from sqlalchemy.orm import Session
from sqlmodel import func, select

from src.self_improvement.data_models import (
    ExecutionResult,
    SelfImprovementExperiment,
    SIOptimizationConfig,
    utcnow,
)
from src.self_improvement.statistical_analyzer import (
    ExperimentAnalysis,
    SIStatisticalAnalyzer,
    VariantResults,
)
from src.self_improvement.storage.experiment_models import (
    M5ExecutionResult,
    M5Experiment,
)

logger = logging.getLogger(__name__)


# ========== Custom Exceptions ==========

class ExperimentError(Exception):
    """Base exception for experiment-related errors."""
    pass


class ExperimentNotFoundError(ExperimentError):
    """Raised when experiment ID doesn't exist."""
    pass


class ExperimentNotCompleteError(ExperimentError):
    """Raised when trying to analyze incomplete experiment."""
    pass


class InvalidVariantError(ExperimentError):
    """Raised when variant_id is invalid for experiment."""
    pass


# ========== Supporting Data Classes ==========

@dataclass
class SIVariantAssignment:
    """Assignment of execution to experiment variant."""
    experiment_id: str
    execution_id: str
    variant_id: str  # "control", "variant_0", "variant_1", etc.
    config: SIOptimizationConfig
    assigned_at: Any = field(default_factory=utcnow)


@dataclass
class SIExperimentStatus:
    """Experiment progress status."""
    experiment_id: str
    status: str  # "running", "completed", "failed"
    is_complete: bool
    can_analyze: bool
    sample_counts: Dict[str, int]  # variant_id → count
    progress: float  # 0.0 to 1.0
    started_at: Any
    duration_minutes: float


@dataclass
class WinnerResult:
    """Experiment winner analysis result."""
    experiment_id: str
    variant_id: str
    winning_config: SIOptimizationConfig

    # Performance improvements
    quality_improvement: float  # Percentage vs control
    speed_improvement: float
    cost_improvement: float
    composite_score: float

    # Statistical confidence
    is_statistically_significant: bool
    p_value: float
    confidence: float

    # Recommendation
    recommendation: str

    # Full analysis
    analysis: ExperimentAnalysis


# ========== Conversion helpers ==========

def _db_to_experiment(db_exp: M5Experiment) -> SelfImprovementExperiment:
    """Convert M5Experiment ORM model to data_models.SelfImprovementExperiment."""
    return SelfImprovementExperiment(
        id=db_exp.id,
        agent_name=db_exp.agent_name,
        status=db_exp.status,
        control_config=SIOptimizationConfig.from_dict(
            db_exp.get_control_config_dict()
        ),
        variant_configs=[
            SIOptimizationConfig.from_dict(v)
            for v in db_exp.get_variant_configs_dicts()
        ],
        proposal_id=db_exp.proposal_id,
        created_at=db_exp.created_at,
        completed_at=db_exp.completed_at,
        extra_metadata=db_exp.get_extra_metadata(),
    )


def _db_to_execution_result(row: M5ExecutionResult) -> ExecutionResult:
    """Convert M5ExecutionResult ORM model to data_models.ExecutionResult."""
    return ExecutionResult(
        id=row.id,
        experiment_id=row.experiment_id,
        variant_id=row.variant_id,
        execution_id=row.execution_id,
        quality_score=row.quality_score,
        speed_seconds=row.speed_seconds,
        cost_usd=row.cost_usd,
        success=row.success,
        recorded_at=row.recorded_at,
        extra_metrics=row.get_extra_metrics(),
    )


# ========== Main Orchestrator ==========

class ExperimentOrchestrator:
    """
    M5 Experiment orchestrator for A/B testing agent configurations.

    Coordinates experiment creation, variant assignment, result collection,
    and winner determination for M5 self-improvement loop.

    Example:
        >>> orchestrator = ExperimentOrchestrator(session)
        >>>
        >>> # Create experiment from proposal
        >>> experiment = orchestrator.create_experiment(
        ...     agent_name="product_extractor",
        ...     control_config=baseline_config,
        ...     variant_configs=[variant1, variant2]
        ... )
        >>>
        >>> # During execution: assign variant
        >>> assignment = orchestrator.assign_variant(
        ...     experiment.id,
        ...     execution_id="exec-123"
        ... )
        >>> config = assignment.config
        >>>
        >>> # After execution: record results
        >>> orchestrator.record_result(
        ...     experiment.id,
        ...     assignment.variant_id,
        ...     "exec-123",
        ...     quality_score=0.85,
        ...     speed_seconds=42.5,
        ...     cost_usd=0.02
        ... )
        >>>
        >>> # Check if experiment complete
        >>> status = orchestrator.get_experiment_progress(experiment.id)
        >>> if status["is_complete"]:
        ...     winner = orchestrator.get_winner(experiment.id)
        ...     if winner:
        ...         print(f"Winner: {winner.variant_id}")
    """

    # Validation patterns for input sanitization
    EXPERIMENT_ID_PATTERN = re.compile(r'^exp-[\w-]+-[0-9a-f]{8}$')
    VARIANT_ID_PATTERN = re.compile(r'^(control|variant_\d+)$')

    def __init__(
        self,
        session: Session,
        statistical_analyzer: Optional[SIStatisticalAnalyzer] = None,
        target_executions_per_variant: int = 50,
        session_factory: Optional[Callable[[], Any]] = None,
    ):
        """
        Initialize experiment orchestrator.

        Args:
            session: SQLAlchemy database session (kept for backward compat).
                     If session_factory is not provided, this session is wrapped
                     in a trivial context manager and reused (legacy behavior).
            statistical_analyzer: Analyzer for statistical tests (creates default if None)
            target_executions_per_variant: Default sample size per variant (default: 50)
            session_factory: Optional callable returning a context manager that
                             yields a Session. Preferred over raw session for
                             session-per-operation pattern.
        """
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            # Backward-compat: wrap the passed session in a no-op context manager
            # so existing callers work unchanged.
            @contextmanager
            def _legacy_session_factory() -> Generator[Session, None, None]:
                yield session

            self._session_factory = _legacy_session_factory

        # Keep self.session for any external code that accesses it directly
        self.session = session
        self.statistical_analyzer = statistical_analyzer or SIStatisticalAnalyzer(
            significance_level=0.05,
            quality_weight=0.7,
            speed_weight=0.2,
            cost_weight=0.1
        )
        self.target_executions_per_variant = target_executions_per_variant

    # ========== Input Validation ==========

    def _validate_experiment_id(self, experiment_id: str) -> None:
        """
        Validate experiment ID format to prevent injection and DOS attacks.

        Args:
            experiment_id: Experiment identifier to validate

        Raises:
            ValueError: If experiment_id is invalid
        """
        if not experiment_id:
            raise ValueError("experiment_id cannot be empty")

        if len(experiment_id) > 100:  # Reasonable limit for DOS prevention
            raise ValueError(
                f"experiment_id too long: {len(experiment_id)} chars (max 100)"
            )

        if not self.EXPERIMENT_ID_PATTERN.match(experiment_id):
            raise ValueError(
                f"Invalid experiment_id format: {experiment_id!r}. "
                f"Expected: exp-{{agent_name}}-{{8-char-hex}}"
            )

    def _validate_variant_id(self, variant_id: str) -> None:
        """
        Validate variant ID format.

        Args:
            variant_id: Variant identifier to validate

        Raises:
            ValueError: If variant_id is invalid
        """
        if not variant_id:
            raise ValueError("variant_id cannot be empty")

        if not self.VARIANT_ID_PATTERN.match(variant_id):
            raise ValueError(
                f"Invalid variant_id format: {variant_id!r}. "
                f"Expected: 'control' or 'variant_N'"
            )

    # ========== ORM Helpers ==========

    def _get_db_experiment(self, experiment_id: str, session: Optional[Session] = None) -> M5Experiment:
        """Load M5Experiment ORM model by ID.

        Args:
            experiment_id: Experiment identifier
            session: Optional session to use (for mutations within a session scope).
                     If None, opens a new session via the factory.

        Raises:
            ExperimentNotFoundError: If experiment doesn't exist
        """
        s = session if session is not None else self.session
        stmt = select(M5Experiment).where(M5Experiment.id == experiment_id)
        db_exp = s.execute(stmt).scalars().first()
        if not db_exp:
            raise ExperimentNotFoundError(f"Experiment not found: {experiment_id}")
        return db_exp

    # ========== Experiment Creation ==========

    def create_experiment(
        self,
        agent_name: str,
        control_config: SIOptimizationConfig,
        variant_configs: List[SIOptimizationConfig],
        proposal_id: Optional[str] = None,
        target_executions_per_variant: Optional[int] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> SelfImprovementExperiment:
        """
        Create new A/B/C/D experiment for M5 self-improvement.

        Creates experiment with control + N variants, sets up equal traffic split,
        and stores in database for tracking.

        Args:
            agent_name: Name of agent being optimized
            control_config: Baseline configuration (current production config)
            variant_configs: List of variant configurations to test (1-3 variants)
            proposal_id: ID of improvement proposal that triggered this experiment
            target_executions_per_variant: Sample size per variant (defaults to orchestrator default)
            extra_metadata: Additional metadata to store

        Returns:
            SelfImprovementExperiment: Created experiment with all variants configured

        Raises:
            ValueError: If variant_configs is empty or exceeds 3 variants
            ValueError: If configs have mismatched agent_name
        """
        # Validation
        if not variant_configs:
            raise ValueError("Must provide at least one variant configuration")
        if len(variant_configs) > 3:
            raise ValueError(f"Maximum 3 variants allowed, got {len(variant_configs)}")

        # Validate all configs have same agent_name
        all_configs = [control_config] + variant_configs
        agent_names = {cfg.agent_name for cfg in all_configs}
        if len(agent_names) > 1:
            raise ValueError(
                f"All configs must have same agent_name. Got: {agent_names}"
            )

        # Generate experiment ID
        experiment_id = f"exp-{agent_name}-{uuid.uuid4().hex[:8]}"

        # Set target
        target = target_executions_per_variant or self.target_executions_per_variant

        now = utcnow()

        # Create ORM model and store (session-per-operation)
        db_exp = M5Experiment(
            id=experiment_id,
            agent_name=agent_name,
            status="running",
            control_config=control_config.to_dict(),
            variant_configs=[v.to_dict() for v in variant_configs],
            target_samples_per_variant=target,
            proposal_id=proposal_id,
            created_at=now,
            extra_metadata=extra_metadata or {},
        )
        with self._session_factory() as session:
            session.add(db_exp)
            session.commit()

        # Build domain model for return value
        experiment = SelfImprovementExperiment(
            id=experiment_id,
            agent_name=agent_name,
            status="running",
            control_config=control_config,
            variant_configs=variant_configs,
            proposal_id=proposal_id,
            created_at=now,
            extra_metadata=extra_metadata or {},
        )

        logger.info(
            f"Created experiment {experiment_id} for {agent_name} "
            f"with {len(variant_configs)} variants, target={target} per variant"
        )

        return experiment

    # ========== Experiment Retrieval ==========

    def get_experiment(self, experiment_id: str) -> SelfImprovementExperiment:
        """
        Get experiment by ID.

        Args:
            experiment_id: Experiment identifier

        Returns:
            SelfImprovementExperiment: Experiment object

        Raises:
            ExperimentNotFoundError: If experiment doesn't exist
        """
        self._validate_experiment_id(experiment_id)
        with self._session_factory() as session:
            db_exp = self._get_db_experiment(experiment_id, session=session)
            return _db_to_experiment(db_exp)

    def list_active_experiments(self, agent_name: Optional[str] = None) -> List[SelfImprovementExperiment]:
        """
        List active (running) experiments.

        Args:
            agent_name: Optional filter by agent

        Returns:
            List of running experiments
        """
        stmt = select(M5Experiment).where(M5Experiment.status == "running")
        if agent_name:
            stmt = stmt.where(M5Experiment.agent_name == agent_name)

        with self._session_factory() as session:
            rows = session.execute(stmt).scalars().all()
            return [_db_to_experiment(row) for row in rows]

    # ========== Variant Assignment ==========

    def assign_variant(
        self,
        experiment_id: str,
        execution_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> SIVariantAssignment:
        """
        Assign execution to a variant using hash-based deterministic assignment.

        Uses SHA-256 hashing to ensure:
        - Same execution_id always gets same variant
        - Reproducible experiments
        - Balanced traffic across variants

        Args:
            experiment_id: Experiment identifier
            execution_id: Unique execution identifier (used for hashing)
            context: Optional context for assignment (e.g., {"user_id": "123"})

        Returns:
            SIVariantAssignment: Assignment with variant_id and config

        Raises:
            ExperimentNotFoundError: If experiment not found
            ValueError: If experiment is not in "running" status
        """
        self._validate_experiment_id(experiment_id)

        # Load experiment
        experiment = self.get_experiment(experiment_id)

        # Validate experiment is running
        if experiment.status != "running":
            raise ValueError(
                f"Cannot assign variant: experiment {experiment_id} "
                f"has status '{experiment.status}', expected 'running'"
            )

        # Determine hash input (prefer context hash_key if provided)
        hash_input = execution_id
        if context and "hash_key" in context:
            hash_input = str(context["hash_key"])

        # Hash-based assignment
        variant_id = self._hash_to_variant(hash_input, experiment.get_variant_count())

        # Get config for variant
        config = self.get_variant_config(experiment_id, variant_id)

        # Create assignment
        assignment = SIVariantAssignment(
            experiment_id=experiment_id,
            execution_id=execution_id,
            variant_id=variant_id,
            config=config
        )

        logger.debug(
            f"Assigned execution {execution_id} to {variant_id} "
            f"in experiment {experiment_id}"
        )

        return assignment

    def _hash_to_variant(self, hash_input: str, num_variants: int) -> str:
        """
        Map hash input to variant ID using consistent hashing.

        Args:
            hash_input: String to hash
            num_variants: Total number of variants (including control)

        Returns:
            variant_id: "control", "variant_0", "variant_1", etc.
        """
        # Compute SHA-256 hash
        hash_value = hashlib.sha256(hash_input.encode()).hexdigest()
        hash_int = int(hash_value[:8], 16)

        # Map to variant index (equal distribution)
        variant_index = hash_int % num_variants

        if variant_index == 0:
            return "control"
        else:
            return f"variant_{variant_index - 1}"

    def get_variant_config(self, experiment_id: str, variant_id: str) -> SIOptimizationConfig:
        """
        Get configuration for a specific variant.

        Args:
            experiment_id: Experiment identifier
            variant_id: Variant identifier ("control", "variant_0", etc.)

        Returns:
            SIOptimizationConfig: Configuration for the variant

        Raises:
            ExperimentNotFoundError: If experiment not found
            InvalidVariantError: If variant_id invalid for this experiment
        """
        self._validate_experiment_id(experiment_id)
        self._validate_variant_id(variant_id)

        experiment = self.get_experiment(experiment_id)

        if variant_id == "control":
            return experiment.control_config
        elif variant_id.startswith("variant_"):
            try:
                variant_index = int(variant_id.split("_")[1])
                return experiment.variant_configs[variant_index]
            except (IndexError, ValueError):
                raise InvalidVariantError(
                    f"Invalid variant_id '{variant_id}' for experiment {experiment_id}. "
                    f"Valid variants: control, variant_0..variant_{len(experiment.variant_configs) - 1}"
                )
        else:
            raise InvalidVariantError(
                f"Invalid variant_id format: '{variant_id}'. "
                f"Expected 'control' or 'variant_N'"
            )

    # ========== Result Recording ==========

    def record_result(
        self,
        experiment_id: str,
        variant_id: str,
        execution_id: str,
        quality_score: Optional[float] = None,
        speed_seconds: Optional[float] = None,
        cost_usd: Optional[float] = None,
        success: Optional[bool] = None,
        extra_metrics: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Record experiment execution result.

        Stores metrics for this execution. Results are aggregated by variant
        for statistical analysis.

        Args:
            experiment_id: Experiment identifier
            variant_id: Variant that was used
            execution_id: Unique execution identifier
            quality_score: Quality metric (0-1 scale, higher better)
            speed_seconds: Duration in seconds (lower better)
            cost_usd: Cost in USD (lower better)
            success: Whether execution succeeded
            extra_metrics: Additional metrics to track

        Raises:
            ExperimentNotFoundError: If experiment not found
            InvalidVariantError: If variant_id invalid for this experiment
        """
        self._validate_experiment_id(experiment_id)
        self._validate_variant_id(variant_id)

        # Validate experiment and variant exist
        experiment = self.get_experiment(experiment_id)

        # Validate variant_id
        valid_variants = ["control"] + [f"variant_{i}" for i in range(len(experiment.variant_configs))]
        if variant_id not in valid_variants:
            raise InvalidVariantError(
                f"Invalid variant_id '{variant_id}' for experiment {experiment_id}. "
                f"Valid variants: {valid_variants}"
            )

        # Create and store ORM result (session-per-operation)
        result_id = f"result-{uuid.uuid4().hex[:12]}"
        db_result = M5ExecutionResult(
            id=result_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
            execution_id=execution_id,
            quality_score=quality_score,
            speed_seconds=speed_seconds,
            cost_usd=cost_usd,
            success=success,
            recorded_at=utcnow(),
            extra_metrics=extra_metrics or {},
        )
        with self._session_factory() as session:
            session.add(db_result)
            session.commit()

        logger.debug(
            f"Recorded result for {execution_id} ({variant_id}) "
            f"in experiment {experiment_id}: quality={quality_score}, "
            f"speed={speed_seconds}s, cost=${cost_usd}"
        )

    # ========== Experiment Status ==========

    def is_experiment_complete(self, experiment_id: str) -> bool:
        """
        Check if experiment has collected enough data for analysis.

        Experiment is complete when ALL variants have reached target sample size.

        Args:
            experiment_id: Experiment identifier

        Returns:
            bool: True if all variants have sufficient samples
        """
        self._validate_experiment_id(experiment_id)
        progress = self.get_experiment_progress(experiment_id)
        return progress["is_complete"]

    def get_experiment_progress(self, experiment_id: str) -> Dict[str, Any]:
        """
        Get current progress for each variant in experiment.

        Args:
            experiment_id: Experiment identifier

        Returns:
            Dict with progress information
        """
        self._validate_experiment_id(experiment_id)

        with self._session_factory() as session:
            # Get experiment via ORM
            db_exp = self._get_db_experiment(experiment_id, session=session)
            experiment = _db_to_experiment(db_exp)
            target = db_exp.target_samples_per_variant

            # Get sample counts per variant via ORM
            count_stmt = (
                select(M5ExecutionResult.variant_id, func.count())
                .where(M5ExecutionResult.experiment_id == experiment_id)
                .group_by(M5ExecutionResult.variant_id)
            )
            count_rows = session.execute(count_stmt).all()
            count_map = {row[0]: row[1] for row in count_rows}

        # Build variant progress
        variant_progress = {}
        expected_variants = ["control"] + [
            f"variant_{i}" for i in range(len(experiment.variant_configs))
        ]

        for vid in expected_variants:
            count = count_map.get(vid, 0)
            variant_progress[vid] = {
                "collected": count,
                "target": target,
                "pct": (count / target * 100) if target > 0 else 0,
            }

        # Check if complete (all variants reached target)
        is_complete = all(vp["collected"] >= target for vp in variant_progress.values())

        # Calculate totals
        total_collected = sum(vp["collected"] for vp in variant_progress.values())
        total_target = target * len(expected_variants)

        return {
            "experiment_id": experiment_id,
            "status": experiment.status,
            "target_per_variant": target,
            "variants": variant_progress,
            "total_collected": total_collected,
            "total_target": total_target,
            "is_complete": is_complete,
            "can_analyze": is_complete,
        }

    def get_experiment_results(self, experiment_id: str) -> List[ExecutionResult]:
        """
        Get all results for experiment.

        Args:
            experiment_id: Experiment ID

        Returns:
            List of all execution results
        """
        self._validate_experiment_id(experiment_id)

        with self._session_factory() as session:
            stmt = (
                select(M5ExecutionResult)
                .where(M5ExecutionResult.experiment_id == experiment_id)
            )
            rows = session.execute(stmt).scalars().all()
            return [_db_to_execution_result(row) for row in rows]

    # ========== Winner Determination ==========

    def get_winner(self, experiment_id: str, force: bool = False) -> Optional[WinnerResult]:
        """
        Analyze experiment and determine winner.

        Runs statistical analysis comparing variants to control:
        1. Check minimum sample size reached (unless force=True)
        2. Run SIStatisticalAnalyzer
        3. Apply M5 winner criteria (quality + composite score)
        4. Return winner or None

        Args:
            experiment_id: Experiment to analyze
            force: If True, analyze even if experiment not complete

        Returns:
            WinnerResult with winning config and analysis, or None if no winner

        Raises:
            ExperimentNotFoundError: If experiment not found
            ExperimentNotCompleteError: If not complete and force=False
        """
        self._validate_experiment_id(experiment_id)

        # Check completion
        if not force and not self.is_experiment_complete(experiment_id):
            raise ExperimentNotCompleteError(
                f"Experiment {experiment_id} not yet complete. "
                f"Use force=True to analyze anyway."
            )

        # Run analysis
        analysis = self.analyze_experiment(experiment_id)

        # Check for winner
        if not analysis.winner:
            return None

        # Get winning config
        winner_config = self.get_variant_config(experiment_id, analysis.winner.variant_id)

        # Create WinnerResult
        winner_result = WinnerResult(
            experiment_id=experiment_id,
            variant_id=analysis.winner.variant_id,
            winning_config=winner_config,
            quality_improvement=analysis.winner.quality_improvement,
            speed_improvement=analysis.winner.speed_improvement,
            cost_improvement=analysis.winner.cost_improvement,
            composite_score=analysis.winner.composite_score,
            is_statistically_significant=analysis.winner.quality_significant,
            p_value=analysis.winner.quality_p_value,
            confidence=analysis.confidence_level,
            recommendation=analysis.winner.recommendation,
            analysis=analysis
        )

        logger.info(
            f"Winner for experiment {experiment_id}: {winner_result.variant_id} "
            f"(quality: +{winner_result.quality_improvement:.1f}%, "
            f"composite: +{winner_result.composite_score:.1f}%)"
        )

        return winner_result

    def analyze_experiment(self, experiment_id: str) -> ExperimentAnalysis:
        """
        Analyze experiment results using statistical tests.

        Args:
            experiment_id: Experiment identifier

        Returns:
            ExperimentAnalysis: Full analysis with comparisons and winner
        """
        self._validate_experiment_id(experiment_id)

        experiment = self.get_experiment(experiment_id)
        results = self.get_experiment_results(experiment_id)

        # Aggregate results per variant
        control_results = self._aggregate_variant_results("control", results)
        variant_results_list = [
            self._aggregate_variant_results(f"variant_{i}", results)
            for i in range(len(experiment.variant_configs))
        ]

        # Run statistical analysis
        analysis = self.statistical_analyzer.analyze_experiment(
            control=control_results,
            variants=variant_results_list,
            experiment_id=experiment_id
        )

        return analysis

    def _aggregate_variant_results(
        self,
        variant_id: str,
        results: List[ExecutionResult]
    ) -> VariantResults:
        """Aggregate results for a specific variant."""
        variant_results = [r for r in results if r.variant_id == variant_id]

        quality_scores = [r.quality_score for r in variant_results if r.quality_score is not None]
        speed_scores = [r.speed_seconds for r in variant_results if r.speed_seconds is not None]
        cost_scores = [r.cost_usd for r in variant_results if r.cost_usd is not None]

        return VariantResults(
            variant_id=variant_id,
            variant_name=variant_id,
            sample_size=len(variant_results),
            quality_scores=quality_scores,
            speed_scores=speed_scores,
            cost_scores=cost_scores
        )

    # ========== Experiment Completion ==========

    def complete_experiment(
        self,
        experiment_id: str,
        winner_variant_id: Optional[str] = None
    ) -> None:
        """
        Mark experiment as completed.

        Args:
            experiment_id: Experiment to complete
            winner_variant_id: Optional winner to record
        """
        self._validate_experiment_id(experiment_id)
        if winner_variant_id is not None:
            self._validate_variant_id(winner_variant_id)

        with self._session_factory() as session:
            db_exp = self._get_db_experiment(experiment_id, session=session)
            db_exp.status = "completed"
            db_exp.completed_at = utcnow()
            db_exp.winner_variant_id = winner_variant_id
            session.commit()

        logger.info(f"Completed experiment {experiment_id}, winner: {winner_variant_id}")

    def stop_experiment(self, experiment_id: str, reason: str = "manual_stop") -> None:
        """
        Stop experiment early (before completion).

        Updates experiment status to "stopped" to prevent new assignments.

        Args:
            experiment_id: Experiment identifier
            reason: Reason for stopping
        """
        self._validate_experiment_id(experiment_id)

        with self._session_factory() as session:
            db_exp = self._get_db_experiment(experiment_id, session=session)

            # Update metadata with stop reason
            metadata = db_exp.get_extra_metadata()
            metadata["stop_reason"] = reason

            db_exp.status = "stopped"
            db_exp.completed_at = utcnow()
            db_exp.extra_metadata = metadata
            session.commit()

        logger.info(f"Stopped experiment {experiment_id}, reason: {reason}")

    def get_winning_config(self, experiment_id: str) -> Optional[SIOptimizationConfig]:
        """
        Get winning configuration after experiment completes.

        Returns None if experiment not complete or no winner determined.

        Args:
            experiment_id: Experiment identifier

        Returns:
            SIOptimizationConfig: Winning configuration, or None if no winner
        """
        self._validate_experiment_id(experiment_id)

        try:
            winner = self.get_winner(experiment_id, force=True)
            return winner.winning_config if winner else None
        except ExperimentNotCompleteError:
            return None
