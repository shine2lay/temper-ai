"""Agent observability helper for tracking LLM and tool calls.

Encapsulates the repetitive tracker guard pattern used across StandardAgent
to eliminate boilerplate. Each tracking call is safe to call even when
tracker or execution context is unavailable.
"""
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AgentObserver:
    """Wraps observability tracker with safe guard logic.

    Eliminates the repeated pattern of:
        if self.tracker is not None and hasattr(self, '_execution_context') ...
            if self._execution_context.agent_id:
                try:
                    self.tracker.track_...()
                except Exception:
                    logger.warning(...)

    Usage:
        observer = AgentObserver(tracker, execution_context)
        observer.track_llm_call(provider=..., model=..., ...)
        observer.track_tool_call(tool_name=..., ...)
    """

    def __init__(self, tracker: Any, execution_context: Any):
        self._tracker = tracker
        self._context = execution_context
        self._agent_id: Optional[str] = None

        if execution_context is not None and hasattr(execution_context, 'agent_id'):
            self._agent_id = execution_context.agent_id

    @property
    def active(self) -> bool:
        """Whether tracking is available (tracker + agent_id present)."""
        return self._tracker is not None and self._agent_id is not None

    def track_llm_call(self, **kwargs: Any) -> None:
        """Track an LLM call. No-op if tracker unavailable."""
        if not self.active:
            return
        try:
            self._tracker.track_llm_call(agent_id=self._agent_id, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to track LLM call: {e}")

    def track_tool_call(self, **kwargs: Any) -> None:
        """Track a tool call. No-op if tracker unavailable."""
        if not self.active:
            return
        try:
            self._tracker.track_tool_call(agent_id=self._agent_id, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to track tool call: {e}")
