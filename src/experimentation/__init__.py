"""
A/B Testing and Experimentation Framework.

Enables systematic experimentation on agent configurations, prompts,
collaboration strategies, and workflows to support data-driven optimization
and self-improvement capabilities.

Key Components:
- Experiment: Define A/B tests with variants and success criteria
- VariantAssigner: Assign workflow executions to experiment variants
- ConfigManager: Merge variant configuration overrides with base configs
- StatisticalAnalyzer: Perform hypothesis testing and determine winners
- ExperimentService: Main API for experiment management

Example:
    >>> from src.experimentation import ExperimentService
    >>> service = ExperimentService()
    >>>
    >>> # Create experiment
    >>> experiment_id = service.create_experiment(
    ...     name="temperature_test",
    ...     description="Test impact of temperature on quality",
    ...     variants=[
    ...         {"name": "control", "is_control": True, "traffic": 0.5, "config": {}},
    ...         {"name": "high_temp", "traffic": 0.5, "config": {"temperature": 0.9}}
    ...     ],
    ...     primary_metric="output_quality_score"
    ... )
    >>>
    >>> # Start experiment
    >>> service.start_experiment(experiment_id)
    >>>
    >>> # Assign variant to workflow
    >>> assignment = service.assign_variant(workflow_id, experiment_id)
    >>> variant_config = service.get_variant_config(assignment.variant_id)
    >>>
    >>> # Analyze results
    >>> results = service.get_experiment_results(experiment_id)
    >>> print(f"Winner: {results.recommended_winner}")
"""

from src.experimentation.models import (
    Experiment,
    Variant,
    VariantAssignment,
    ExperimentResult,
    ExperimentStatus,
    AssignmentStrategyType,
)

from src.experimentation.service import ExperimentService
from src.experimentation.metrics_collector import ExperimentMetricsCollector

__all__ = [
    "Experiment",
    "Variant",
    "VariantAssignment",
    "ExperimentResult",
    "ExperimentStatus",
    "AssignmentStrategyType",
    "ExperimentService",
    "ExperimentMetricsCollector",
]

__version__ = "0.1.0"
