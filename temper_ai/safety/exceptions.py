"""Safety module exceptions."""

from temper_ai.shared.exceptions import TemperError


class SafetyError(TemperError):
    """Base exception for safety policy errors."""


class BudgetExceededError(SafetyError):
    """Workflow or agent exceeded its cost/token budget."""


class SafetyConfigError(SafetyError):
    """Invalid safety policy configuration."""
