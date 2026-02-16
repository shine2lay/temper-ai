"""LLM iteration and cache event data + emission helpers.

Provides lightweight dataclasses for per-iteration LLM loop events and
cache hit/miss/write/eviction events, plus helper functions to emit them
via the observer or an opt-in callback.

These events are high-frequency (emitted every LLM iteration) so they
use structured logging rather than SQL writes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Key prefix length shown in logs for cache keys
_CACHE_KEY_PREFIX_LENGTH = 16


@dataclass
class LLMIterationEventData:
    """Data emitted after each LLM iteration in the tool-calling loop."""

    iteration_number: int
    agent_name: str = "unknown"
    conversation_turns_count: int = 0
    tool_calls_this_iteration: int = 0
    total_tokens_this_iteration: int = 0
    total_cost_this_iteration: float = 0.0
    cache_hit: Optional[bool] = None


@dataclass
class CacheEventData:
    """Data emitted on cache hit/miss/write/eviction."""

    event_type: str  # "hit", "miss", "write", "eviction"
    key_prefix: str = ""
    model: Optional[str] = None
    cache_size: Optional[int] = None


def emit_llm_iteration_event(
    observer: Any,
    event_data: LLMIterationEventData,
) -> None:
    """Emit an LLM iteration event via the observer and structured log.

    Args:
        observer: AgentObserver or any object (may be None).
        event_data: Iteration metrics for this LLM loop cycle.
    """
    logger.info(
        "LLM iteration %d for agent=%s: tools=%d tokens=%d cost=%.6f",
        event_data.iteration_number,
        event_data.agent_name,
        event_data.tool_calls_this_iteration,
        event_data.total_tokens_this_iteration,
        event_data.total_cost_this_iteration,
    )
    if observer is None:
        return
    _try_emit_to_observer(observer, event_data)


def _try_emit_to_observer(
    observer: Any,
    event_data: LLMIterationEventData,
) -> None:
    """Attempt to emit iteration event to observer. Best-effort."""
    try:
        track_fn = getattr(observer, "track_llm_iteration", None)
        if track_fn is not None:
            track_fn(event_data)
    except (AttributeError, TypeError, RuntimeError) as exc:
        logger.debug("Could not emit LLM iteration event: %s", exc)


def emit_cache_event(
    callback: Optional[Callable[..., Any]],
    event_data: CacheEventData,
) -> None:
    """Emit a cache event via the opt-in callback and structured log.

    Args:
        callback: Optional callable to receive the event.
        event_data: Cache event details.
    """
    logger.debug(
        "Cache event=%s key_prefix=%s model=%s size=%s",
        event_data.event_type,
        event_data.key_prefix,
        event_data.model,
        event_data.cache_size,
    )
    if callback is None:
        return
    try:
        callback(event_data)
    except (TypeError, RuntimeError, ValueError) as exc:
        logger.debug("Cache event callback error: %s", exc)
