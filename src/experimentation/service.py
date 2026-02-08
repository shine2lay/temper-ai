"""
Experiment service for A/B testing and experimentation.

Main API for creating, managing, and analyzing experiments.
Delegates to specialized modules for CRUD, lifecycle, and tracking.
"""

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import update
from sqlmodel import select

from src.core.service import Service
from src.experimentation.analyzer import StatisticalAnalyzer
from src.experimentation.assignment import VariantAssigner
from src.experimentation.config_manager import ConfigManager
from src.experimentation.experiment_crud import ExperimentCRUD
from src.experimentation.models import (
    AssignmentStrategyType,
    ExecutionStatus,
    Experiment,
    ExperimentResult,
    ExperimentStatus,
    RecommendationType,
    Variant,
    VariantAssignment,
    utcnow,
)
from src.database import get_session
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ExperimentService(Service):
    """
    A/B testing service for workflow experimentation.

    Manages experiment lifecycle, variant assignment, metrics collection,
    and statistical analysis to enable data-driven optimization.

    Example:
        >>> service = ExperimentService()
        >>> service.initialize()
        >>>
        >>> # Create experiment
        >>> exp_id = service.create_experiment(
        ...     name="temperature_test",
        ...     description="Test temperature impact",
        ...     variants=[
        ...         {"name": "control", "is_control": True, "traffic": 0.5},
        ...         {"name": "high_temp", "traffic": 0.5, "config": {"temperature": 0.9}}
        ...     ],
        ...     primary_metric="output_quality_score"
        ... )
        >>>
        >>> # Start and use
        >>> service.start_experiment(exp_id)
        >>> assignment = service.assign_variant("workflow-123", exp_id)
    """

    @property
    def name(self) -> str:
        """Service name for registration."""
        return "experiment_service"

    # Maximum cached experiments to prevent unbounded memory growth
    MAX_CACHE_SIZE = 1000

    def __init__(self, max_cache_size: int = MAX_CACHE_SIZE) -> None:
        """
        Initialize experiment service.

        Delegates to specialized modules:
        - ExperimentCRUD: Database operations and caching
        - VariantAssigner: Assignment logic
        - StatisticalAnalyzer: Analysis
        - ConfigManager: Configuration management
        """
        self._crud = ExperimentCRUD(max_cache_size)
        self._assigner = VariantAssigner()
        self._config_manager = ConfigManager()
        self._analyzer = StatisticalAnalyzer()
        logger.info("ExperimentService initialized")

    def initialize(self) -> None:
        """Initialize service resources."""
        logger.info("ExperimentService starting up")
        # Create tables if needed (handled by database manager)

    def shutdown(self) -> None:
        """Clean up service resources."""
        logger.info("ExperimentService shutting down")
        self._crud.clear_cache()

    # ========== Experiment CRUD ==========

    def create_experiment(
        self,
        name: str,
        description: str,
        variants: List[Dict[str, Any]],
        assignment_strategy: str = "random",
        primary_metric: str = "duration_seconds",
        secondary_metrics: Optional[List[str]] = None,
        guardrail_metrics: Optional[List[Dict[str, Any]]] = None,
        confidence_level: float = 0.95,
        min_sample_size_per_variant: int = 100,
        **kwargs: Any
    ) -> str:
        """
        Create new experiment.

        Args:
            name: Unique experiment name
            description: Experiment description/hypothesis
            variants: List of variant configurations
            assignment_strategy: Assignment strategy ("random", "hash", etc.)
            primary_metric: Primary success metric
            secondary_metrics: Additional metrics to track
            guardrail_metrics: Safety constraints
            confidence_level: Statistical confidence level
            min_sample_size_per_variant: Minimum samples before analysis
            **kwargs: Additional experiment metadata

        Returns:
            experiment_id: UUID of created experiment

        Raises:
            ValueError: If experiment configuration is invalid
        """
        # SECURITY: Validate experiment name
        # Note: ORM already prevents SQL injection via parameterization.
        # This validation prevents timing attacks, homograph attacks, and malicious naming patterns.
        try:
            name = validate_experiment_name(name)
        except ValueError as e:
            logger.warning(
                f"Invalid experiment name rejected: {name[:100]}",
                extra={
                    "security_event": "INPUT_VALIDATION_FAILED",
                    "input_name": name[:100],
                    "input_length": len(name),
                    "user": kwargs.get("created_by"),
                    "error": str(e)
                }
            )
            raise

        # Validate inputs
        if not variants or len(variants) < 2:
            raise ValueError("Experiment must have at least 2 variants")

        # SECURITY: Validate ALL variant names first (atomic operation)
        # This ensures we don't partially mutate the variants list on error
        variants = validate_variant_list(variants, name)

        # Calculate traffic allocation
        traffic_allocation = {
            v["name"]: v.get("traffic", 1.0 / len(variants))
            for v in variants
        }

        total_traffic = sum(traffic_allocation.values())
        if total_traffic > 1.0:
            raise ValueError(f"Total traffic allocation {total_traffic} exceeds 1.0")

        # Create experiment
        experiment_id = str(uuid.uuid4())
        experiment = Experiment(
            id=experiment_id,
            name=name,
            description=description,
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType(assignment_strategy),
            traffic_allocation=traffic_allocation,
            primary_metric=primary_metric,
            secondary_metrics=secondary_metrics or [],
            guardrail_metrics=guardrail_metrics,
            confidence_level=confidence_level,
            min_sample_size_per_variant=min_sample_size_per_variant,
            tags=kwargs.get("tags", []),
            created_by=kwargs.get("created_by"),
            extra_metadata=kwargs.get("extra_metadata"),
            created_at=utcnow(),
            updated_at=utcnow(),
        )

        # Create variants
        variant_models = []
        for variant_config in variants:
            variant_id = str(uuid.uuid4())
            variant = Variant(
                id=variant_id,
                experiment_id=experiment_id,
                name=variant_config["name"],
                description=variant_config.get("description", ""),
                is_control=variant_config.get("is_control", False),
                config_type=variant_config.get("config_type", "agent"),
                config_overrides=variant_config.get("config", {}),
                allocated_traffic=traffic_allocation[variant_config["name"]],
                extra_metadata=variant_config.get("extra_metadata"),
                created_at=utcnow(),
            )
            variant_models.append(variant)

        # Save to database
        try:
            with get_session() as session:
                session.add(experiment)
                for variant in variant_models:
                    session.add(variant)
                session.commit()
        except IntegrityError as e:
            # SECURITY: Don't reveal which constraint failed (timing attack mitigation)
            logger.warning(
                "Experiment creation failed due to constraint violation",
                extra={
                    "security_event": "DATABASE_CONSTRAINT_VIOLATION",
                    "experiment_name": name,
                    "user": kwargs.get("created_by"),
                    "error_type": type(e).__name__
                }
            )
            raise ValueError(
                "Experiment creation failed. "
                "This may be due to a duplicate name or other constraint violation."
            )

        logger.info(f"Created experiment: {name} (ID: {experiment_id})")
        return experiment_id

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        """Get experiment by ID."""
        # Check cache first (ST-07: thread-safe access)
        with self._cache_lock:
            if experiment_id in self._experiment_cache:
                return self._experiment_cache[experiment_id]

        # Load from database with eager relationship loading
        with get_session() as session:
            statement = (
                select(Experiment)
                .where(Experiment.id == experiment_id)
                .options(
                    selectinload(Experiment.variants),
                    selectinload(Experiment.assignments),
                    selectinload(Experiment.results),
                )
            )
            experiment = session.exec(statement).first()
            if experiment:
                # Detach from session so cached object can be used after session closes
                session.expunge(experiment)
                self._cache_put(experiment_id, experiment)
            return experiment

    def list_experiments(
        self,
        status: Optional[ExperimentStatus] = None
    ) -> List[Experiment]:
        """List experiments, optionally filtered by status."""
        with get_session() as session:
            statement = select(Experiment)
            if status:
                statement = statement.where(Experiment.status == status)
            experiments = session.exec(statement).all()
            return list(experiments)

    # ========== Experiment Lifecycle ==========

    def start_experiment(self, experiment_id: str) -> None:
        """Start experiment (enable variant assignment)."""
        with get_session() as session:
            experiment = session.get(Experiment, experiment_id)
            if not experiment:
                raise ValueError(f"Experiment not found: {experiment_id}")

            if experiment.status != ExperimentStatus.DRAFT:
                raise ValueError(f"Cannot start experiment in status: {experiment.status}")

            experiment.status = ExperimentStatus.RUNNING
            experiment.started_at = utcnow()
            experiment.updated_at = utcnow()
            session.commit()

            # Invalidate cache — next get_experiment() will reload with eager loading
            self._experiment_cache.pop(experiment_id, None)

        logger.info(f"Started experiment: {experiment_id}")

    def pause_experiment(self, experiment_id: str) -> None:
        """Pause experiment (stop new assignments)."""
        with get_session() as session:
            experiment = session.get(Experiment, experiment_id)
            if not experiment:
                raise ValueError(f"Experiment not found: {experiment_id}")

            experiment.status = ExperimentStatus.PAUSED
            experiment.updated_at = utcnow()
            session.commit()

            # Invalidate cache — next get_experiment() will reload with eager loading
            self._experiment_cache.pop(experiment_id, None)

        logger.info(f"Paused experiment: {experiment_id}")

    def stop_experiment(
        self,
        experiment_id: str,
        winner: Optional[str] = None
    ) -> None:
        """Stop experiment and optionally declare winner."""
        with get_session() as session:
            experiment = session.get(Experiment, experiment_id)
            if not experiment:
                raise ValueError(f"Experiment not found: {experiment_id}")

            experiment.status = ExperimentStatus.STOPPED
            experiment.stopped_at = utcnow()
            experiment.updated_at = utcnow()
            if winner:
                experiment.winner_variant_id = winner
            session.commit()

            # Invalidate cache — next get_experiment() will reload with eager loading
            self._experiment_cache.pop(experiment_id, None)

        logger.info(f"Stopped experiment: {experiment_id}, winner: {winner}")

    # ========== Variant Assignment ==========

    def assign_variant(
        self,
        workflow_id: str,
        experiment_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> VariantAssignment:
        """
        Assign workflow to variant.

        Args:
            workflow_id: Workflow execution ID
            experiment_id: Experiment ID
            context: Optional context for assignment

        Returns:
            VariantAssignment with assigned variant

        Raises:
            ValueError: If experiment not found or not running
        """
        # Load experiment and variants
        with get_session() as session:
            experiment = session.get(Experiment, experiment_id)
            if not experiment:
                raise ValueError(f"Experiment not found: {experiment_id}")

            if experiment.status != ExperimentStatus.RUNNING:
                raise ValueError(f"Experiment not running: {experiment.status}")

            # Load variants
            statement = select(Variant).where(Variant.experiment_id == experiment_id)
            variants = list(session.exec(statement).all())

            if not variants:
                raise ValueError(f"No variants found for experiment: {experiment_id}")

            # Assign variant
            variant_id = self._assigner.assign_variant(
                experiment,
                variants,
                workflow_id,
                context
            )

            # Create assignment record
            assignment_id = str(uuid.uuid4())
            assignment = VariantAssignment(
                id=assignment_id,
                experiment_id=experiment_id,
                variant_id=variant_id,
                workflow_execution_id=workflow_id,
                assigned_at=utcnow(),
                assignment_strategy=experiment.assignment_strategy,
                assignment_context=context,
                execution_status=ExecutionStatus.PENDING,
            )

            session.add(assignment)
            session.commit()

            # Invalidate experiment cache after new assignment (H-25)
            self._experiment_cache.pop(experiment_id, None)

        logger.info(f"Assigned workflow {workflow_id} to variant {variant_id}")
        return assignment

    def get_variant_config(self, variant_id: str) -> Dict[str, Any]:
        """Get variant config overrides."""
        with get_session() as session:
            variant = session.get(Variant, variant_id)
            if not variant:
                raise ValueError(f"Variant not found: {variant_id}")
            return variant.config_overrides

    # ========== Tracking ==========

    def track_execution_complete(
        self,
        workflow_id: str,
        metrics: Dict[str, float],
        status: str = "completed"
    ) -> None:
        """Update assignment with execution metrics."""
        with get_session() as session:
            # Find assignment
            statement = select(VariantAssignment).where(
                VariantAssignment.workflow_execution_id == workflow_id
            )
            assignment = session.exec(statement).first()

            if not assignment:
                logger.warning(f"No assignment found for workflow: {workflow_id}")
                return

            # Update assignment
            assignment.execution_status = ExecutionStatus(status)
            assignment.execution_completed_at = utcnow()
            assignment.metrics = metrics

            # Update variant counters atomically (C-05: prevent race conditions)
            variant_id = assignment.variant_id

            # Atomic increment of total_executions
            session.execute(
                update(Variant)
                .where(Variant.id == variant_id)
                .values(total_executions=Variant.total_executions + 1)
            )

            # Atomic increment of status-specific counter
            if status == "completed":
                session.execute(
                    update(Variant)
                    .where(Variant.id == variant_id)
                    .values(successful_executions=Variant.successful_executions + 1)
                )
            elif status == "failed":
                session.execute(
                    update(Variant)
                    .where(Variant.id == variant_id)
                    .values(failed_executions=Variant.failed_executions + 1)
                )

            # Invalidate experiment cache (H-25: ensure fresh data)
            experiment = session.get(Experiment, assignment.experiment_id)
            if experiment:
                self._experiment_cache.pop(experiment.id, None)

            session.commit()

        logger.info(f"Tracked execution complete: {workflow_id}")

    # ========== Analysis ==========

    def get_experiment_results(
        self,
        experiment_id: str,
        _include_raw_data: bool = False
    ) -> Dict[str, Any]:
        """Run statistical analysis and return results."""
        with get_session() as session:
            # Load experiment
            experiment = session.get(Experiment, experiment_id)
            if not experiment:
                raise ValueError(f"Experiment not found: {experiment_id}")

            # Load variants
            statement = select(Variant).where(Variant.experiment_id == experiment_id)
            variants = list(session.exec(statement).all())

            # Load assignments
            statement = select(VariantAssignment).where(  # type: ignore[assignment]
                VariantAssignment.experiment_id == experiment_id
            )
            assignments = list(session.exec(statement).all())

            # Run analysis
            analysis_results = self._analyzer.analyze_experiment(
                experiment,
                assignments,  # type: ignore[arg-type]
                variants
            )

            # Store results (simplified for MVP)
            result_id = str(uuid.uuid4())
            result = ExperimentResult(
                id=result_id,
                experiment_id=experiment_id,
                analyzed_at=utcnow(),
                sample_size=analysis_results["sample_size"],
                variant_metrics=analysis_results["variant_metrics"],
                statistical_tests=analysis_results["statistical_tests"],
                guardrail_violations=analysis_results["guardrail_violations"],
                recommendation=analysis_results["recommendation"],
                recommended_winner=analysis_results.get("recommended_winner"),
                confidence=analysis_results["confidence"],
            )

            session.add(result)
            session.commit()

        return analysis_results

    def check_early_stopping(self, experiment_id: str) -> Dict[str, Any]:
        """Check if experiment should stop early."""
        results = self.get_experiment_results(experiment_id)

        should_stop = results["recommendation"] in [
            RecommendationType.STOP_WINNER,
            RecommendationType.STOP_GUARDRAIL_VIOLATION,
        ]

        return {
            "should_stop": should_stop,
            "reason": results["recommendation"].value,
            "winner": results.get("recommended_winner"),
            "confidence": results["confidence"],
        }
