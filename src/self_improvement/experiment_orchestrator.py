"""
Experiment orchestrator for M5 self-improvement A/B testing.

Coordinates experiment creation, variant assignment, result collection,
and statistical analysis to determine winning agent configurations.

Database access uses SQLModel ORM via M5Experiment and M5ExecutionResult
models (no raw SQL).

Session management: Uses session-per-operation pattern via a context-manager
factory to avoid long-lived sessions that accumulate stale state.
"""
import logging
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

from sqlalchemy.orm import Session
from sqlmodel import select

from src.constants.limits import DEFAULT_BATCH_SIZE
from src.self_improvement._experiment_helpers import (
    EXPERIMENT_ID_UUID_LENGTH,
    ExperimentCreationData,
    ExperimentResultData,
    aggregate_variant_results,
    create_experiment_in_db,
    hash_to_variant,
    record_result_to_db,
)
from src.self_improvement._experiment_helpers import (
    get_experiment_progress as _get_experiment_progress,
)
from src.self_improvement.constants import (
    DEFAULT_ALPHA,
    EXPERIMENT_GROUP_CONTROL,
    EXPERIMENT_VARIANT_PREFIX,
    MAX_CONCURRENT_EXPERIMENTS,
)
from src.self_improvement.data_models import (
    ExecutionResult,
    SelfImprovementExperiment,
    SIOptimizationConfig,
    utcnow,
)
from src.self_improvement.statistical_analyzer import (
    ExperimentAnalysis,
    SIStatisticalAnalyzer,
)
from src.self_improvement.storage.experiment_models import (
    M5ExecutionResult,
    M5Experiment,
)
from src.utils.exceptions import FrameworkException

logger = logging.getLogger(__name__)

# Metric weights for statistical analysis (must sum to 1.0)
WEIGHT_QUALITY = 0.7
WEIGHT_SPEED = 0.2
WEIGHT_COST = 0.1


# ========== Custom Exceptions ==========

class ExperimentError(FrameworkException):
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
    variant_id: str
    config: SIOptimizationConfig
    assigned_at: Any = field(default_factory=utcnow)


@dataclass
class SIExperimentStatus:
    """Experiment progress status."""
    experiment_id: str
    status: str
    is_complete: bool
    can_analyze: bool
    sample_counts: Dict[str, int]
    progress: float
    started_at: Any
    duration_minutes: float


@dataclass
class WinnerResult:
    """Experiment winner analysis result."""
    experiment_id: str
    variant_id: str
    winning_config: SIOptimizationConfig

    quality_improvement: float
    speed_improvement: float
    cost_improvement: float
    composite_score: float

    is_statistically_significant: bool
    p_value: float
    confidence: float

    recommendation: str
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
    """M5 Experiment orchestrator for A/B testing agent configurations."""

    EXPERIMENT_ID_PATTERN = re.compile(r'^exp-[\w-]+-[0-9a-f]{8}$')
    VARIANT_ID_PATTERN = re.compile(r'^(control|variant_\d+)$')

    def __init__(
        self,
        session: Session,
        statistical_analyzer: Optional[SIStatisticalAnalyzer] = None,
        target_executions_per_variant: int = DEFAULT_BATCH_SIZE,
        session_factory: Optional[Callable[[], Any]] = None,
    ):
        """Initialize experiment orchestrator."""
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            @contextmanager
            def _legacy_session_factory() -> Generator[Session, None, None]:
                yield session

            self._session_factory = _legacy_session_factory

        self.session = session
        self.statistical_analyzer = statistical_analyzer or SIStatisticalAnalyzer(
            significance_level=DEFAULT_ALPHA,
            quality_weight=WEIGHT_QUALITY,
            speed_weight=WEIGHT_SPEED,
            cost_weight=WEIGHT_COST
        )
        self.target_executions_per_variant = target_executions_per_variant

    # ========== Input Validation ==========

    def _validate_experiment_id(self, experiment_id: str) -> None:
        """Validate experiment ID format."""
        if not experiment_id:
            raise ValueError("experiment_id cannot be empty")
        if len(experiment_id) > 100:
            raise ValueError(f"experiment_id too long: {len(experiment_id)} chars (max 100)")
        if not self.EXPERIMENT_ID_PATTERN.match(experiment_id):
            raise ValueError(
                f"Invalid experiment_id format: {experiment_id!r}. "
                f"Expected: exp-{{agent_name}}-{{8-char-hex}}"
            )

    def _validate_variant_id(self, variant_id: str) -> None:
        """Validate variant ID format."""
        if not variant_id:
            raise ValueError("variant_id cannot be empty")
        if not self.VARIANT_ID_PATTERN.match(variant_id):
            raise ValueError(
                f"Invalid variant_id format: {variant_id!r}. "
                f"Expected: 'control' or 'variant_N'"
            )

    # ========== ORM Helpers ==========

    def _get_db_experiment(self, experiment_id: str, session: Optional[Session] = None) -> M5Experiment:
        """Load M5Experiment ORM model by ID."""
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
        """Create new A/B/C/D experiment for M5 self-improvement."""
        if not variant_configs:
            raise ValueError("Must provide at least one variant configuration")
        if len(variant_configs) > MAX_CONCURRENT_EXPERIMENTS:
            raise ValueError(f"Maximum {MAX_CONCURRENT_EXPERIMENTS} variants allowed, got {len(variant_configs)}")

        all_configs = [control_config] + variant_configs
        agent_names = {cfg.agent_name for cfg in all_configs}
        if len(agent_names) > 1:
            raise ValueError(f"All configs must have same agent_name. Got: {agent_names}")

        experiment_id = f"exp-{agent_name}-{uuid.uuid4().hex[:EXPERIMENT_ID_UUID_LENGTH]}"
        target = target_executions_per_variant or self.target_executions_per_variant

        # Create experiment data bundle
        creation_data = ExperimentCreationData(
            agent_name=agent_name,
            experiment_id=experiment_id,
            control_config=control_config,
            variant_configs=variant_configs,
            target=target,
            proposal_id=proposal_id,
            extra_metadata=extra_metadata
        )

        experiment = create_experiment_in_db(
            data=creation_data,
            session_factory=self._session_factory,
        )

        logger.info(
            f"Created experiment {experiment_id} for {agent_name} "
            f"with {len(variant_configs)} variants, target={target} per variant"
        )

        return experiment

    # ========== Experiment Retrieval ==========

    def get_experiment(self, experiment_id: str) -> SelfImprovementExperiment:
        """Get experiment by ID."""
        self._validate_experiment_id(experiment_id)
        with self._session_factory() as session:
            db_exp = self._get_db_experiment(experiment_id, session=session)
            return _db_to_experiment(db_exp)

    def list_active_experiments(self, agent_name: Optional[str] = None) -> List[SelfImprovementExperiment]:
        """List active (running) experiments."""
        stmt = select(M5Experiment).where(M5Experiment.status == "running")
        if agent_name:
            stmt = stmt.where(M5Experiment.agent_name == agent_name)
        with self._session_factory() as session:
            rows = session.execute(stmt).scalars().all()
            return [_db_to_experiment(row) for row in rows]

    # ========== Variant Assignment ==========

    def assign_variant(self, experiment_id: str, execution_id: str, context: Optional[Dict[str, Any]] = None) -> SIVariantAssignment:
        """Assign execution to a variant using hash-based deterministic assignment."""
        self._validate_experiment_id(experiment_id)
        experiment = self.get_experiment(experiment_id)

        if experiment.status != "running":
            raise ValueError(
                f"Cannot assign variant: experiment {experiment_id} "
                f"has status '{experiment.status}', expected 'running'"
            )

        hash_input = execution_id
        if context and "hash_key" in context:
            hash_input = str(context["hash_key"])

        variant_id = hash_to_variant(hash_input, experiment.get_variant_count())
        config = self.get_variant_config(experiment_id, variant_id)

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

    def get_variant_config(self, experiment_id: str, variant_id: str) -> SIOptimizationConfig:
        """Get configuration for a specific variant."""
        self._validate_experiment_id(experiment_id)
        self._validate_variant_id(variant_id)
        experiment = self.get_experiment(experiment_id)

        if variant_id == EXPERIMENT_GROUP_CONTROL:
            return experiment.control_config
        elif variant_id.startswith(EXPERIMENT_VARIANT_PREFIX):
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

    def _validate_variant_for_experiment(
        self,
        experiment_id: str,
        variant_id: str
    ) -> None:
        """Validate that variant exists in experiment."""
        experiment = self.get_experiment(experiment_id)
        valid_variants = ["control"] + [f"variant_{i}" for i in range(len(experiment.variant_configs))]
        if variant_id not in valid_variants:
            raise InvalidVariantError(
                f"Invalid variant_id '{variant_id}' for experiment {experiment_id}. "
                f"Valid variants: {valid_variants}"
            )

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
        """Record experiment execution result."""
        # Validate inputs
        self._validate_experiment_id(experiment_id)
        self._validate_variant_id(variant_id)
        self._validate_variant_for_experiment(experiment_id, variant_id)

        # Create result data bundle
        result_data = ExperimentResultData(
            experiment_id=experiment_id,
            variant_id=variant_id,
            execution_id=execution_id,
            quality_score=quality_score,
            speed_seconds=speed_seconds,
            cost_usd=cost_usd,
            success=success,
            extra_metrics=extra_metrics
        )

        # Record to database
        record_result_to_db(
            data=result_data,
            session_factory=self._session_factory,
        )

        logger.debug(
            f"Recorded result for {execution_id} ({variant_id}) "
            f"in experiment {experiment_id}: quality={quality_score}, "
            f"speed={speed_seconds}s, cost=${cost_usd}"
        )

    # ========== Experiment Status ==========

    def is_experiment_complete(self, experiment_id: str) -> bool:
        """Check if experiment has collected enough data for analysis."""
        self._validate_experiment_id(experiment_id)
        progress = self.get_experiment_progress(experiment_id)
        return bool(progress["is_complete"])

    def get_experiment_progress(self, experiment_id: str) -> Dict[str, Any]:
        """Get current progress for each variant in experiment."""
        self._validate_experiment_id(experiment_id)
        return _get_experiment_progress(
            experiment_id=experiment_id,
            session_factory=self._session_factory,
            get_db_experiment_fn=self._get_db_experiment,
        )

    def get_experiment_results(self, experiment_id: str) -> List[ExecutionResult]:
        """Get all results for experiment."""
        self._validate_experiment_id(experiment_id)
        with self._session_factory() as session:
            stmt = select(M5ExecutionResult).where(M5ExecutionResult.experiment_id == experiment_id)
            rows = session.execute(stmt).scalars().all()
            return [_db_to_execution_result(row) for row in rows]

    # ========== Winner Determination ==========

    def get_winner(self, experiment_id: str, force: bool = False) -> Optional[WinnerResult]:
        """Analyze experiment and determine winner."""
        self._validate_experiment_id(experiment_id)

        if not force and not self.is_experiment_complete(experiment_id):
            raise ExperimentNotCompleteError(
                f"Experiment {experiment_id} not yet complete. Use force=True to analyze anyway."
            )

        analysis = self.analyze_experiment(experiment_id)
        if not analysis.winner:
            return None

        winner_config = self.get_variant_config(experiment_id, analysis.winner.variant_id)

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
        """Analyze experiment results using statistical tests."""
        self._validate_experiment_id(experiment_id)
        experiment = self.get_experiment(experiment_id)
        results = self.get_experiment_results(experiment_id)

        control_results = aggregate_variant_results("control", results)
        variant_results_list = [
            aggregate_variant_results(f"variant_{i}", results)
            for i in range(len(experiment.variant_configs))
        ]

        return self.statistical_analyzer.analyze_experiment(
            control=control_results,
            variants=variant_results_list,
            experiment_id=experiment_id
        )

    # ========== Experiment Completion ==========

    def complete_experiment(self, experiment_id: str, winner_variant_id: Optional[str] = None) -> None:
        """Mark experiment as completed."""
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
        """Stop experiment early."""
        self._validate_experiment_id(experiment_id)

        with self._session_factory() as session:
            db_exp = self._get_db_experiment(experiment_id, session=session)
            metadata = db_exp.get_extra_metadata()
            metadata["stop_reason"] = reason
            db_exp.status = "stopped"
            db_exp.completed_at = utcnow()
            db_exp.extra_metadata = metadata
            session.commit()

        logger.info(f"Stopped experiment {experiment_id}, reason: {reason}")

    def get_winning_config(self, experiment_id: str) -> Optional[SIOptimizationConfig]:
        """Get winning configuration after experiment completes."""
        self._validate_experiment_id(experiment_id)
        try:
            winner = self.get_winner(experiment_id, force=True)
            return winner.winning_config if winner else None
        except ExperimentNotCompleteError:
            return None
