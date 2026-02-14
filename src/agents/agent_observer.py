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
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.warning(f"Failed to track LLM call: {e}")

    def track_tool_call(self, **kwargs: Any) -> None:
        """Track a tool call. No-op if tracker unavailable."""
        if not self.active:
            return
        try:
            self._tracker.track_tool_call(agent_id=self._agent_id, **kwargs)
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.warning(f"Failed to track tool call: {e}")

    def emit_stream_chunk(
        self,
        content: str,
        chunk_type: str = "content",
        done: bool = False,
        model: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> None:
        """Emit a streaming chunk event. Best-effort, never raises."""
        if self._tracker is None or self._agent_id is None:
            return
        try:
            event_bus = getattr(self._tracker, '_event_bus', None)
            if event_bus is None:
                return
            from src.observability._tracker_helpers import StreamChunkData, emit_llm_stream_chunk

            workflow_id = None
            stage_id = None
            if self._context is not None:
                workflow_id = getattr(self._context, 'workflow_id', None)
                stage_id = getattr(self._context, 'stage_id', None)

            data = StreamChunkData(
                agent_id=self._agent_id,
                content=content,
                chunk_type=chunk_type,
                done=done,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                workflow_id=workflow_id,
                stage_id=stage_id,
            )
            emit_llm_stream_chunk(event_bus=event_bus, data=data)
        except Exception:  # noqa: BLE001 -- best-effort streaming event
            pass
