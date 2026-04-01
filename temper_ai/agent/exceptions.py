"""Agent-specific exceptions."""

from temper_ai.shared.exceptions import TemperError


class AgentError(TemperError):
    """Base exception for agent errors."""


class MaxIterationsError(AgentError):
    """Agent exceeded max tool-calling iterations."""
