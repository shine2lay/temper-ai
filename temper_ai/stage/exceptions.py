"""Stage module exceptions."""

from temper_ai.shared.exceptions import TemperError


class StageError(TemperError):
    """Error in stage/graph execution or configuration."""


class WorkflowError(StageError):
    """Error in top-level workflow execution."""


class TopologyError(StageError):
    """Error in topology generation (strategy)."""


class ConditionError(StageError):
    """Error evaluating a condition expression."""


class LoaderError(StageError):
    """Error loading or resolving graph/workflow config."""


class CyclicDependencyError(LoaderError):
    """Graph has circular dependencies."""


class ValidationError(LoaderError):
    """Graph config validation failed."""
