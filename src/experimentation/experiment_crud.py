"""
Experiment CRUD operations with thread-safe caching.

Handles database persistence for experiments and variants with LRU caching
to improve read performance.
"""

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import select

from src.constants.limits import THRESHOLD_LARGE_COUNT
from src.database import get_session
from src.experimentation.constants import DEFAULT_CREDIBLE_LEVEL
from src.experimentation.models import (
    AssignmentStrategyType,
    Experiment,
    ExperimentStatus,
    Variant,
    utcnow,
)
from src.experimentation.validators import (
    validate_experiment_name,
    validate_variant_list,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExperimentParams:
    """Parameters for creating an experiment."""

    name: str
    description: str
    variants: List[Dict[str, Any]]
    assignment_strategy: str = "random"
    primary_metric: str = "duration_seconds"
    secondary_metrics: Optional[List[str]] = None
    guardrail_metrics: Optional[List[Dict[str, Any]]] = None
    confidence_level: float = DEFAULT_CREDIBLE_LEVEL
    min_sample_size_per_variant: int = THRESHOLD_LARGE_COUNT
    extra_kwargs: Dict[str, Any] = field(default_factory=dict)


class ExperimentCRUD:
    """
    Handles experiment CRUD operations with thread-safe caching.

    Implements LRU cache with manual eviction for experiment objects.
    Thread-safe cache access using lock (ST-07 pattern).
    Session-safe with expunge() before caching (H-14 pattern).
    """

    # Maximum cached experiments to prevent unbounded memory growth
    MAX_CACHE_SIZE = 1000

    def __init__(self, max_cache_size: int = MAX_CACHE_SIZE) -> None:
        """Initialize CRUD handler with cache."""
        self._max_cache_size = max_cache_size
        self._experiment_cache: OrderedDict[str, Experiment] = OrderedDict()
        self._cache_lock = threading.Lock()  # ST-07: thread safety for cache
        logger.info(f"ExperimentCRUD initialized with cache size {max_cache_size}")

    def _cache_put(self, key: str, value: Experiment) -> None:
        """
        Add to cache with LRU eviction when max size exceeded.

        Thread-safe: Must be called with _cache_lock held.
        """
        with self._cache_lock:
            self._experiment_cache[key] = value
            self._experiment_cache.move_to_end(key)
            while len(self._experiment_cache) > self._max_cache_size:
                self._experiment_cache.popitem(last=False)

    def _validate_experiment_params(self, params: ExperimentParams) -> str:
        """Validate experiment parameters and return validated name.

        Args:
            params: Experiment parameters to validate.

        Returns:
            Validated experiment name.

        Raises:
            ValueError: If parameters are invalid.
        """
        # SECURITY: Validate experiment name
        try:
            name = validate_experiment_name(params.name)
        except ValueError as e:
            logger.warning(
                f"Invalid experiment name rejected: {params.name[:100]}",
                extra={
                    "security_event": "INPUT_VALIDATION_FAILED",
                    "input_name": params.name[:100],
                    "input_length": len(params.name),
                    "user": params.extra_kwargs.get("created_by"),
                    "error": str(e)
                }
            )
            raise

        # Validate inputs
        if not params.variants or len(params.variants) < 2:
            raise ValueError("Experiment must have at least 2 variants")

        return name

    def _calculate_traffic_allocation(self, variants: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate traffic allocation for variants.

        Args:
            variants: List of variant configurations.

        Returns:
            Dictionary mapping variant names to traffic allocation.

        Raises:
            ValueError: If total traffic exceeds 1.0.
        """
        traffic_allocation = {
            v["name"]: v.get("traffic", 1.0 / len(variants))
            for v in variants
        }

        total_traffic = sum(traffic_allocation.values())
        if total_traffic > 1.0:
            raise ValueError(f"Total traffic allocation {total_traffic} exceeds 1.0")

        return traffic_allocation

    def _create_variant_models(
        self,
        experiment_id: str,
        variants: List[Dict[str, Any]],
        traffic_allocation: Dict[str, float],
    ) -> List[Variant]:
        """Create variant models from configurations.

        Args:
            experiment_id: Experiment UUID.
            variants: List of variant configurations.
            traffic_allocation: Traffic allocation map.

        Returns:
            List of Variant model instances.
        """
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
        return variant_models

    def _persist_experiment(
        self,
        experiment: Experiment,
        variant_models: List[Variant],
        validated_name: str,
        kwargs: Dict[str, Any],
    ) -> None:
        """Save experiment and variants to database.

        Args:
            experiment: Experiment model to persist.
            variant_models: Variant models to persist.
            validated_name: Validated experiment name (for logging).
            kwargs: Extra kwargs (for logging created_by).

        Raises:
            ValueError: If a database constraint is violated.
        """
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
                    "experiment_name": validated_name,
                    "user": kwargs.get("created_by"),
                    "error_type": type(e).__name__
                }
            )
            raise ValueError(
                "Experiment creation failed. "
                "This may be due to a duplicate name or other constraint violation."
            )

    def create_experiment(
        self,
        name: str,
        description: str,
        variants: List[Dict[str, Any]],
        assignment_strategy: str = "random",
        primary_metric: str = "duration_seconds",
        secondary_metrics: Optional[List[str]] = None,
        guardrail_metrics: Optional[List[Dict[str, Any]]] = None,
        confidence_level: float = DEFAULT_CREDIBLE_LEVEL,
        min_sample_size_per_variant: int = THRESHOLD_LARGE_COUNT,
        **kwargs: Any
    ) -> str:
        """
        Create new experiment with variants.

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
        params = ExperimentParams(
            name=name,
            description=description,
            variants=variants,
            assignment_strategy=assignment_strategy,
            primary_metric=primary_metric,
            secondary_metrics=secondary_metrics,
            guardrail_metrics=guardrail_metrics,
            confidence_level=confidence_level,
            min_sample_size_per_variant=min_sample_size_per_variant,
            extra_kwargs=kwargs,
        )

        # Validate parameters
        validated_name = self._validate_experiment_params(params)

        # SECURITY: Validate ALL variant names first (atomic operation)
        validated_variants = validate_variant_list(params.variants, validated_name)

        # Calculate traffic allocation
        traffic_allocation = self._calculate_traffic_allocation(validated_variants)

        # Create experiment
        experiment_id = str(uuid.uuid4())
        experiment = Experiment(
            id=experiment_id,
            name=validated_name,
            description=params.description,
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType(params.assignment_strategy),
            traffic_allocation=traffic_allocation,
            primary_metric=params.primary_metric,
            secondary_metrics=params.secondary_metrics or [],
            guardrail_metrics=params.guardrail_metrics,
            confidence_level=params.confidence_level,
            min_sample_size_per_variant=params.min_sample_size_per_variant,
            tags=kwargs.get("tags", []),
            created_by=kwargs.get("created_by"),
            extra_metadata=kwargs.get("extra_metadata"),
            created_at=utcnow(),
            updated_at=utcnow(),
        )

        # Create variants
        variant_models = self._create_variant_models(
            experiment_id, validated_variants, traffic_allocation
        )

        # Save to database
        self._persist_experiment(experiment, variant_models, validated_name, kwargs)

        logger.info(f"Created experiment: {validated_name} (ID: {experiment_id})")
        return experiment_id

    def get_experiment(
        self,
        experiment_id: str,
        use_cache: bool = True
    ) -> Optional[Experiment]:
        """
        Get experiment by ID with eager-loaded relationships.

        Args:
            experiment_id: Experiment UUID
            use_cache: Whether to check cache first (default: True)

        Returns:
            Experiment with variants, assignments, results loaded,
            or None if not found.

        Thread-safe: Uses lock for cache access (ST-07).
        Session-safe: Expunges from session before caching (H-14).
        """
        # Check cache first if enabled (ST-07: thread-safe access)
        if use_cache:
            with self._cache_lock:
                if experiment_id in self._experiment_cache:
                    return self._experiment_cache[experiment_id]

        # Load from database with eager relationship loading
        with get_session() as session:
            statement = (
                select(Experiment)
                .where(Experiment.id == experiment_id)
                .options(
                    selectinload(Experiment.variants),  # type: ignore[arg-type]
                    selectinload(Experiment.assignments),  # type: ignore[arg-type]
                    selectinload(Experiment.results),  # type: ignore[arg-type]
                )
            )
            experiment = session.exec(statement).first()
            if experiment:
                # Detach from session so cached object can be used after session closes (H-14)
                session.expunge(experiment)
                if use_cache:
                    self._cache_put(experiment_id, experiment)
            return experiment

    def list_experiments(
        self,
        status: Optional[ExperimentStatus] = None
    ) -> List[Experiment]:
        """
        List experiments, optionally filtered by status.

        Args:
            status: Filter by experiment status (optional)

        Returns:
            List of experiments
        """
        with get_session() as session:
            statement = select(Experiment)
            if status:
                statement = statement.where(Experiment.status == status)
            experiments = session.exec(statement).all()
            return list(experiments)

    def invalidate_cache(self, experiment_id: str) -> None:
        """
        Invalidate cached experiment.

        Call this after mutations to ensure fresh data on next get.

        Args:
            experiment_id: Experiment UUID to invalidate
        """
        with self._cache_lock:
            self._experiment_cache.pop(experiment_id, None)

    def clear_cache(self) -> None:
        """
        Clear entire cache.

        Typically called during shutdown.
        """
        with self._cache_lock:
            self._experiment_cache.clear()


__all__ = ["ExperimentCRUD"]
