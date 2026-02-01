"""
Variant assignment strategies for A/B testing.

Provides different strategies for assigning workflow executions to experiment variants:
- RandomAssignment: Weighted random selection
- HashAssignment: Deterministic hash-based assignment
- StratifiedAssignment: Balanced assignment across strata (future)
- BanditAssignment: Multi-armed bandit optimization (future)
"""

import random
import hashlib
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from src.experimentation.models import Experiment, Variant, AssignmentStrategyType


class AssignmentStrategy(ABC):
    """
    Base class for variant assignment strategies.

    All assignment strategies must implement the assign() method,
    which takes an experiment, its variants, an execution identifier,
    and optional context, and returns the variant_id to assign.
    """

    @abstractmethod
    def assign(
        self,
        experiment: Experiment,
        variants: List[Variant],
        execution_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Assign execution to a variant.

        Args:
            experiment: The experiment definition
            variants: List of available variants
            execution_id: Unique identifier for this execution
            context: Optional context for assignment decisions

        Returns:
            variant_id: ID of the assigned variant

        Raises:
            ValueError: If variants are invalid or traffic allocation is incorrect
        """
        pass

    def _validate_variants(self, variants: List[Variant]) -> None:
        """
        Validate that variants have valid traffic allocation.

        Args:
            variants: List of variants to validate

        Raises:
            ValueError: If traffic allocation is invalid
        """
        if not variants:
            raise ValueError("No variants available for assignment")

        total_traffic = sum(v.allocated_traffic for v in variants)
        if total_traffic <= 0 or total_traffic > 1.0:
            raise ValueError(
                f"Invalid traffic allocation: sum={total_traffic:.2f}, must be in (0, 1.0]"
            )

    def _get_control_variant(self, variants: List[Variant]) -> Optional[Variant]:
        """Get the control variant if one exists."""
        for variant in variants:
            if variant.is_control:
                return variant
        return None


class RandomAssignment(AssignmentStrategy):
    """
    Random variant assignment based on traffic allocation.

    Assigns each execution to a variant using weighted random selection.
    Each variant receives traffic proportional to its allocated_traffic percentage.

    This strategy does NOT guarantee consistent assignment for the same execution_id.
    Use HashAssignment for deterministic, consistent assignment.

    Example:
        >>> strategy = RandomAssignment()
        >>> variant_id = strategy.assign(experiment, variants, "workflow-123")
        >>> # Variant is randomly selected with probabilities from allocated_traffic
    """

    def assign(
        self,
        experiment: Experiment,
        variants: List[Variant],
        execution_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Randomly assign execution to variant based on traffic weights.

        Args:
            experiment: The experiment definition
            variants: List of available variants
            execution_id: Unique identifier for this execution (not used in random)
            context: Optional context (not used in random assignment)

        Returns:
            variant_id: Randomly selected variant ID

        Raises:
            ValueError: If variants are invalid
        """
        self._validate_variants(variants)

        # Weighted random selection
        weights = [v.allocated_traffic for v in variants]
        variant_ids = [v.id for v in variants]

        selected_id = random.choices(variant_ids, weights=weights, k=1)[0]
        return selected_id


class HashAssignment(AssignmentStrategy):
    """
    Deterministic hash-based variant assignment.

    Assigns each execution to a variant using a consistent hash function.
    The same execution_id (or context key) will always be assigned to the
    same variant, ensuring consistent user experience across sessions.

    Uses MD5 hash for fast, uniformly distributed assignment.

    Example:
        >>> strategy = HashAssignment()
        >>> variant_id = strategy.assign(experiment, variants, "user-123")
        >>> # Same user-123 will always get the same variant

        >>> # Use context key for hashing
        >>> variant_id = strategy.assign(
        ...     experiment, variants, "workflow-456",
        ...     context={"hash_key": "user-123"}
        ... )
    """

    def assign(
        self,
        experiment: Experiment,
        variants: List[Variant],
        execution_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Deterministically assign execution to variant using hash function.

        Args:
            experiment: The experiment definition
            variants: List of available variants
            execution_id: Unique identifier for this execution
            context: Optional context with "hash_key" for consistent hashing

        Returns:
            variant_id: Deterministically selected variant ID

        Raises:
            ValueError: If variants are invalid
        """
        self._validate_variants(variants)

        # Determine hash input (prefer context hash_key if provided)
        hash_input = execution_id
        if context and "hash_key" in context:
            hash_input = str(context["hash_key"])

        # Compute hash using SHA-256 (FIPS 140-2 approved, collision-resistant)
        # Security: Replaced MD5 (broken, collision vulnerable) with SHA-256
        hash_value = int(hashlib.sha256(hash_input.encode()).hexdigest(), 16)

        # Map hash to variant based on traffic allocation
        variant_id = self._hash_to_variant(hash_value, variants)
        return variant_id

    def _hash_to_variant(self, hash_value: int, variants: List[Variant]) -> str:
        """
        Map hash value to variant based on traffic allocation.

        Uses cumulative traffic allocation to partition the hash space.
        For example, with control=0.6, variant_a=0.4:
        - [0.0, 0.6) → control
        - [0.6, 1.0) → variant_a

        Args:
            hash_value: Integer hash value
            variants: List of variants with traffic allocation

        Returns:
            variant_id: Variant ID corresponding to hash bucket
        """
        # Normalize hash to [0, 1)
        hash_fraction = (hash_value % 100000) / 100000.0

        # Find variant using cumulative traffic allocation
        cumulative_traffic = 0.0
        for variant in sorted(variants, key=lambda v: v.id):  # Sort for consistency
            cumulative_traffic += variant.allocated_traffic
            if hash_fraction < cumulative_traffic:
                return variant.id

        # Fallback: return last variant (handles floating point edge cases)
        return variants[-1].id


class StratifiedAssignment(AssignmentStrategy):
    """
    Stratified assignment ensuring balance across context dimensions.

    Ensures that each stratum (e.g., environment, time_of_day, user_segment)
    receives balanced traffic across variants. This reduces confounding
    variables in experiment analysis.

    Currently a placeholder for future implementation.

    Example (future):
        >>> strategy = StratifiedAssignment(strata=["environment", "time_of_day"])
        >>> variant_id = strategy.assign(
        ...     experiment, variants, "workflow-123",
        ...     context={"environment": "prod", "time_of_day": "morning"}
        ... )
        >>> # Assignment balances across environment × time_of_day strata
    """

    def assign(
        self,
        experiment: Experiment,
        variants: List[Variant],
        execution_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Stratified assignment (placeholder).

        Currently falls back to hash-based assignment.

        Args:
            experiment: The experiment definition
            variants: List of available variants
            execution_id: Unique identifier for this execution
            context: Context with stratum values

        Returns:
            variant_id: Assigned variant ID
        """
        # TODO: Implement stratified assignment logic
        # For now, fall back to hash assignment
        return HashAssignment().assign(experiment, variants, execution_id, context)


class BanditAssignment(AssignmentStrategy):
    """
    Multi-armed bandit assignment for dynamic traffic allocation.

    Uses Thompson sampling or UCB (Upper Confidence Bound) to dynamically
    allocate more traffic to better-performing variants while still exploring.

    Currently a placeholder for future implementation (requires Bayesian backend).

    Example (future):
        >>> strategy = BanditAssignment(algorithm="thompson")
        >>> variant_id = strategy.assign(experiment, variants, "workflow-123")
        >>> # More traffic allocated to variants with better performance
    """

    def assign(
        self,
        experiment: Experiment,
        variants: List[Variant],
        execution_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Bandit-based assignment (placeholder).

        Currently falls back to random assignment.

        Args:
            experiment: The experiment definition
            variants: List of available variants
            execution_id: Unique identifier for this execution
            context: Optional context

        Returns:
            variant_id: Assigned variant ID
        """
        # TODO: Implement multi-armed bandit logic
        # For now, fall back to random assignment
        return RandomAssignment().assign(experiment, variants, execution_id, context)


class VariantAssigner:
    """
    Coordinator for variant assignment using configured strategy.

    Selects the appropriate assignment strategy based on experiment configuration
    and delegates assignment logic to that strategy.

    Example:
        >>> assigner = VariantAssigner()
        >>> variant_id = assigner.assign_variant(experiment, variants, "workflow-123")
    """

    def __init__(self) -> None:
        """Initialize variant assigner with strategy registry."""
        self._strategies: Dict[AssignmentStrategyType, AssignmentStrategy] = {
            AssignmentStrategyType.RANDOM: RandomAssignment(),
            AssignmentStrategyType.HASH: HashAssignment(),
            AssignmentStrategyType.STRATIFIED: StratifiedAssignment(),
            AssignmentStrategyType.BANDIT: BanditAssignment(),
        }

    def assign_variant(
        self,
        experiment: Experiment,
        variants: List[Variant],
        execution_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Assign variant using experiment's configured strategy.

        Args:
            experiment: The experiment definition
            variants: List of available variants
            execution_id: Unique identifier for this execution
            context: Optional context for assignment

        Returns:
            variant_id: Assigned variant ID

        Raises:
            ValueError: If strategy is unknown or variants are invalid
        """
        strategy_type = experiment.assignment_strategy

        if strategy_type not in self._strategies:
            raise ValueError(f"Unknown assignment strategy: {strategy_type}")

        strategy = self._strategies[strategy_type]
        return strategy.assign(experiment, variants, execution_id, context)

    def register_strategy(
        self,
        strategy_type: AssignmentStrategyType,
        strategy: AssignmentStrategy
    ) -> None:
        """
        Register a custom assignment strategy.

        Args:
            strategy_type: Strategy type identifier
            strategy: Strategy implementation
        """
        self._strategies[strategy_type] = strategy
