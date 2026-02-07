"""M5 Self-Improvement System.

Bounded context: this package is a separate domain from the core framework.
It depends on observability and compiler but should not be imported by them.
"""

from .data_models import (
    AgentPerformanceProfile,
    ExecutionResult,
    SelfImprovementExperiment,
    SIOptimizationConfig,
    utcnow,
)
from .experiment_orchestrator import (
    ExperimentError,
    ExperimentNotCompleteError,
    ExperimentNotFoundError,
    ExperimentOrchestrator,
    InvalidVariantError,
    SIExperimentStatus,
    SIVariantAssignment,
    WinnerResult,
)

__all__ = [
    "AgentPerformanceProfile",
    "SIOptimizationConfig",
    "SelfImprovementExperiment",
    "ExecutionResult",
    "utcnow",
    "ExperimentOrchestrator",
    "SIVariantAssignment",
    "SIExperimentStatus",
    "WinnerResult",
    "ExperimentError",
    "ExperimentNotFoundError",
    "ExperimentNotCompleteError",
    "InvalidVariantError",
]
