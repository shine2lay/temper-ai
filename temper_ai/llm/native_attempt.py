"""The shared native Anthropic single-request reader, without selection or retries.

Named single-send and private pooled attempts use this same transport and raw
SDK event reader. The caller owns exception classification and control.finish.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from temper_ai.llm import single_send as ss
from temper_ai.llm.models import LLMResponse


@dataclass
class NativeObservation:
    """Trusted local phase observation; never inferred from an exception message."""

    stream_opened: bool = False


def send_native_once(
    shared: Any,
    body: dict[str, Any],
    control: ss.SingleSendControl,
    response: LLMResponse,
    observation: NativeObservation,
    read_usage: Callable[[Any, list[Any]], tuple[dict[str, Any], dict[str, Any] | None]],
) -> LLMResponse:
    """One owned no-retry/no-redirect HTTP client, bounded by the existing control."""
    owned = ss.new_http_client(control)
    control.own(owned.close)
    client = shared.with_options(max_retries=0, timeout=control.remaining(), http_client=owned)
    manager = client.messages.stream(**body)
    stream = manager.__enter__()
    observation.stream_opened = True
    # Explicit close belongs to the bounded, privacy-scoped worker, not a
    # potentially blocking context-manager exit on this thread.
    control.own(lambda: manager.__exit__(None, None, None))
    # Read answer and usage separately: the SDK accumulator raises on unfamiliar
    # usage before terminal events. Keep its event ordering behavior unchanged.
    text: list[str] = []
    started = stopped = False
    blocks: set[Any] = set()
    response_id = stop_reason = start_usage = None
    delta_usages: list[Any] = []
    for event in stream._raw_stream:  # locked SDK; exercised with real SDK objects
        control.check()
        kind = getattr(event, "type", None)
        if kind == "message_start":
            if not started:
                message = getattr(event, "message", None)
                response_id = ss.safe_response_id(getattr(message, "id", None))
                start_usage = getattr(message, "usage", None)
                response.raw_response = {"response_id": response_id}
                started = True
        elif not started:
            raise ss.SingleSendError("partial", response=response)
        elif kind == "content_block_start":
            block = getattr(event, "content_block", None)
            if getattr(block, "type", None) not in ("text", "thinking", "redacted_thinking"):
                raise ss.SingleSendError("partial", response=response)
            blocks.add(getattr(event, "index", None))
        elif kind in ("content_block_delta", "content_block_stop") and getattr(event, "index", None) not in blocks:
            raise ss.SingleSendError("partial", response=response)
        elif kind == "content_block_delta":
            delta = getattr(event, "delta", None)
            if delta is not None and getattr(delta, "type", None) == "text_delta":
                text.append(delta.text)
                response.content = "".join(text)
        elif kind == "message_delta":
            stop_reason = getattr(getattr(event, "delta", None), "stop_reason", None)
            delta_usages.append(getattr(event, "usage", None))
        elif kind == "message_stop":
            stopped = True
    control.check()
    if not stopped:
        raise ss.SingleSendError("partial", response=response)
    usage, usage_fault = read_usage(start_usage, delta_usages)
    stop = stop_reason if stop_reason in ("end_turn", "stop_sequence", "max_tokens", "tool_use", "pause_turn", "refusal") else None
    response.prompt_tokens = usage["input_tokens"]
    response.completion_tokens = usage["output_tokens"]
    response.finish_reason = stop
    response.raw_response = {"response_id": response_id, "usage": usage, "terminal_complete": stopped}
    if usage_fault is not None:
        response.raw_response["usage_fault"] = usage_fault
    if stop == "max_tokens":
        raise ss.SingleSendError("truncation", response=response)
    if stop not in ("end_turn", "stop_sequence"):
        raise ss.SingleSendError("partial", response=response)
    response.content = "".join(text)
    return response
