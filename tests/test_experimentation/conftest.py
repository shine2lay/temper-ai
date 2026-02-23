"""Shared test utilities for experimentation tests."""

from datetime import UTC, datetime

import numpy as np

from temper_ai.experimentation.models import (
    AssignmentStrategyType,
    ConfigType,
    ExecutionStatus,
    Experiment,
    ExperimentStatus,
    Variant,
    VariantAssignment,
)


def create_experiment(**kwargs):
    """Helper to create experiment with sensible defaults.

    Args:
        **kwargs: Override default experiment attributes

    Returns:
        Experiment: Configured experiment instance

    Example:
        >>> exp = create_experiment(
        ...     id="test-001",
        ...     primary_metric="latency_ms",
        ...     min_sample_size_per_variant=100
        ... )
    """
    defaults = {
        "id": "test-exp",
        "name": "test_experiment",
        "description": "Test experiment",
        "status": ExperimentStatus.RUNNING,
        "assignment_strategy": AssignmentStrategyType.RANDOM,
        "traffic_allocation": {"control": 0.5, "variant_a": 0.5},
        "primary_metric": "metric",
        "confidence_level": 0.95,
        "min_sample_size_per_variant": 50,
    }
    defaults.update(kwargs)
    return Experiment(**defaults)


def create_variant(experiment_id="test-exp", is_control=True, **kwargs):
    """Helper to create variant with sensible defaults.

    Args:
        experiment_id: Experiment ID this variant belongs to
        is_control: Whether this is the control variant
        **kwargs: Override default variant attributes

    Returns:
        Variant: Configured variant instance
    """
    variant_id = "var-control" if is_control else "var-treatment"
    defaults = {
        "id": variant_id,
        "experiment_id": experiment_id,
        "name": "control" if is_control else "treatment",
        "description": "Control variant" if is_control else "Treatment variant",
        "is_control": is_control,
        "config_type": ConfigType.AGENT,
        "config_overrides": {},
        "allocated_traffic": 0.5,
    }
    defaults.update(kwargs)
    return Variant(**defaults)


def create_assignments(
    experiment_id="test-exp",
    variant_id="var-control",
    count=50,
    mean=100.0,
    std=10.0,
    metric_name="metric",
    seed=None,
):
    """Helper to create assignments with controlled distribution.

    Args:
        experiment_id: Experiment ID
        variant_id: Variant ID for these assignments
        count: Number of assignments to create
        mean: Mean value for the metric
        std: Standard deviation for the metric
        metric_name: Name of the metric to record
        seed: Random seed for reproducibility (optional)

    Returns:
        list[VariantAssignment]: List of assignment instances

    Example:
        >>> # Create 50 assignments with mean=500ms, std=50ms
        >>> assignments = create_assignments(
        ...     variant_id="var-control",
        ...     count=50,
        ...     mean=500.0,
        ...     std=50.0,
        ...     metric_name="page_load_ms"
        ... )
    """
    if seed is not None:
        np.random.seed(seed)

    assignments = []
    for i in range(count):
        metric_value = mean + np.random.normal(0, std)
        assignment = VariantAssignment(
            id=f"asn-{variant_id}-{i}",
            experiment_id=experiment_id,
            variant_id=variant_id,
            workflow_execution_id=f"wf-{variant_id}-{i}",
            assignment_strategy=AssignmentStrategyType.RANDOM,
            assigned_at=datetime.now(UTC),
            execution_status=ExecutionStatus.COMPLETED,
            metrics={metric_name: metric_value},
        )
        assignments.append(assignment)

    return assignments
