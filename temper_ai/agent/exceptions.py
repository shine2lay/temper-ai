"""Agent-specific exceptions."""

from temper_ai.shared.exceptions import TemperError


class AgentError(TemperError):
    """Base exception for agent errors."""


class MaxIterationsError(AgentError):
    """Agent exceeded max tool-calling iterations."""


class ScriptRenderError(AgentError):
    """A script template could not be rendered — raised for an undefined reference under
    ``strict_undefined``, where rendering it blank would run the command against nothing."""


class JevError(AgentError):
    """A Jev agent could not get its answers: its config is incomplete, the state rendered from
    nothing, the API key is missing, or TypeSafe refused the request."""


class ToolsNotRegisteredError(AgentError):
    """An agent's configured tools are not present in the executor it was given —
    raised before the first LLM call, where running anyway would let the agent
    answer from imagination instead of doing the work it was configured to do."""
