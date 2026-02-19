"""LLM call retry logic (sync and async).

Provides retry-with-backoff for LLM calls, used by LLMService.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
from typing import Any, Callable, Dict, List, Optional

from temper_ai.shared.constants.retries import DEFAULT_BACKOFF_MULTIPLIER, RETRY_JITTER_MIN
from temper_ai.shared.utils.exceptions import LLMError, sanitize_error_message

logger = logging.getLogger(__name__)


def call_with_retry_sync(
    llm: Any,
    inference_config: Any,
    prompt: str,
    stream_callback: Optional[Callable],
    native_tool_defs: Optional[List[Dict[str, Any]]],
    observer: Any,
    track_failed_call: Callable,
) -> tuple[Optional[Any], Optional[Exception]]:
    """Call LLM with retries and exponential backoff (sync)."""
    max_retries = inference_config.max_retries
    retry_delay = float(inference_config.retry_delay_seconds)
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            llm_kwargs: Dict[str, Any] = {}
            if native_tool_defs:
                llm_kwargs["tools"] = native_tool_defs
            if stream_callback:
                return llm.stream(prompt, on_chunk=stream_callback, **llm_kwargs), None
            else:
                return llm.complete(prompt, **llm_kwargs), None
        except LLMError as e:
            last_error = e
            safe_err = sanitize_error_message(str(e))
            track_failed_call(observer, prompt, e, attempt + 1, max_retries + 1)
            if attempt < max_retries:
                backoff_delay = retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_retries + 1, safe_err, backoff_delay,
                )
                shutdown_event = threading.Event()
                if shutdown_event.wait(timeout=backoff_delay):
                    raise KeyboardInterrupt("Agent execution interrupted")
            else:
                logger.error(
                    "LLM call failed after %d attempts: %s",
                    max_retries + 1, safe_err, exc_info=True,
                )

    return None, last_error


async def call_with_retry_async(
    llm: Any,
    inference_config: Any,
    prompt: str,
    stream_callback: Optional[Callable],
    native_tool_defs: Optional[List[Dict[str, Any]]],
    observer: Any,
    track_failed_call: Callable,
) -> tuple[Optional[Any], Optional[Exception]]:
    """Call LLM with retries and exponential backoff (async)."""
    max_retries = inference_config.max_retries
    retry_delay = float(inference_config.retry_delay_seconds)
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            llm_kwargs: Dict[str, Any] = {}
            if native_tool_defs:
                llm_kwargs["tools"] = native_tool_defs
            if stream_callback:
                return await llm.astream(prompt, on_chunk=stream_callback, **llm_kwargs), None
            else:
                return await llm.acomplete(prompt, **llm_kwargs), None
        except LLMError as e:
            last_error = e
            safe_err = sanitize_error_message(str(e))
            track_failed_call(observer, prompt, e, attempt + 1, max_retries + 1)
            if attempt < max_retries:
                backoff_delay = retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_retries + 1, safe_err, backoff_delay,
                )
                await asyncio.sleep(backoff_delay)
            else:
                logger.error(
                    "LLM call failed after %d attempts: %s",
                    max_retries + 1, safe_err, exc_info=True,
                )

    return None, last_error
