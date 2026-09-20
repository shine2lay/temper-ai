"""Agent-specific exceptions."""

from temper_ai.shared.exceptions import TemperError


class AgentError(TemperError):
    """Base exception for agent errors."""


class MaxIterationsError(AgentError):
    """Agent exceeded max tool-calling iterations."""


class ScriptRenderError(AgentError):
    """A script template could not be rendered — raised for an undefined reference under
    ``strict_undefined``, where rendering it blank would run the command against nothing."""
