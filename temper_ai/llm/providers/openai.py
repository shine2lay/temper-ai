"""OpenAI-compatible LLM provider.

Handles both completion and streaming via the /v1/chat/completions endpoint.
Works with OpenAI, Azure OpenAI, and any OpenAI-compatible API.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback


@dataclass
class _StreamState:
    """Mutable state accumulated during SSE streaming."""

    content_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    tool_call_buffer: dict[int, dict[str, str]] = field(default_factory=dict)
    finish_reason: str | None = None
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

logger = logging.getLogger(__name__)


class OpenAILLM(BaseLLM):
    """Provider for OpenAI and OpenAI-compatible APIs."""

    PROVIDER_NAME = "openai"

    def _get_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_endpoint(self) -> str:
        return "/v1/chat/completions"

    # Model context window limits (total input + output tokens)
    MODEL_CONTEXT_LIMIT: int = 262144

    def _estimate_message_tokens(self, messages: list[dict]) -> int:
        """Rough token estimate: ~4 chars per token, plus overhead per message."""
        total = 0
        for msg in messages:
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            total += len(str(content)) // 3 + 4  # ~3 chars/token, 4 tokens overhead
            for tc in msg.get("tool_calls", []):
                total += len(str(tc.get("function", {}).get("arguments", ""))) // 3
            # Tool results in content (assistant messages with tool_call_id)
            if msg.get("role") == "tool":
                total += 10  # tool response framing overhead
        return total

    def _build_request(self, messages: list[dict], **kwargs: Any) -> dict:
        # Dynamically cap max_tokens so input + output <= context limit
        estimated_input = self._estimate_message_tokens(messages)
        headroom = 512  # safety margin
        available = self.MODEL_CONTEXT_LIMIT - estimated_input - headroom
        effective_max_tokens = max(1024, min(self.max_tokens, available))
        if effective_max_tokens < self.max_tokens:
            logger.info(
                "Capping max_tokens %d -> %d (estimated input: %d tokens)",
                self.max_tokens, effective_max_tokens, estimated_input,
            )

        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": effective_max_tokens,
        }

        if kwargs.get("stream"):
            request["stream"] = True

        tools = kwargs.get("tools")
        if tools:
            request["tools"] = tools

        # Pass through extra kwargs from provider config
        for key, value in self.extra_kwargs.items():
            request.setdefault(key, value)

        return request

    def _parse_response(self, response: dict, latency_ms: int) -> LLMResponse:
        choice = response["choices"][0]
        message = choice["message"]
        usage = response.get("usage", {})

        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = [
                {
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                }
                for tc in message["tool_calls"]
            ]

        return LLMResponse(
            content=message.get("content"),
            model=response.get("model", self.model),
            provider=self.provider_name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
            reasoning=message.get("reasoning_content") or message.get("reasoning"),
            tool_calls=tool_calls,
            raw_response=response,
        )

    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback | None,
    ) -> LLMResponse:
        state = _StreamState(model=self.model)

        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            self._process_stream_chunk(chunk, on_chunk, state)

        return self._finalize_stream_response(on_chunk, state)

    def _process_stream_chunk(self, chunk: dict, on_chunk: StreamCallback | None, s: _StreamState) -> None:
        """Process a single SSE chunk, updating state in place."""
        choices = chunk.get("choices", [])
        choice = choices[0] if choices else {}
        delta = choice.get("delta", {})
        s.model = chunk.get("model", s.model)

        reasoning_text = delta.get("reasoning_content") or delta.get("reasoning")
        if reasoning_text:
            s.reasoning_parts.append(reasoning_text)
            if on_chunk:
                on_chunk(LLMStreamChunk(content=reasoning_text, done=False, chunk_type="thinking", model=s.model))

        if delta.get("content"):
            s.content_parts.append(delta["content"])
            if on_chunk:
                on_chunk(LLMStreamChunk(content=delta["content"], done=False, model=s.model))

        if delta.get("tool_calls"):
            _accumulate_tool_calls(delta["tool_calls"], s.tool_call_buffer)
            if on_chunk:
                _stream_tool_call_deltas(delta["tool_calls"], s.tool_call_buffer, on_chunk, s.model)

        if choice.get("finish_reason"):
            s.finish_reason = choice["finish_reason"]

        usage = chunk.get("usage")
        if usage:
            s.prompt_tokens = usage.get("prompt_tokens")
            s.completion_tokens = usage.get("completion_tokens")

    def _finalize_stream_response(self, on_chunk: StreamCallback | None, s: _StreamState) -> LLMResponse:
        """Signal stream end and assemble the final LLMResponse."""
        if on_chunk:
            on_chunk(LLMStreamChunk(content="", done=True, finish_reason=s.finish_reason))

        tool_calls = [s.tool_call_buffer[i] for i in sorted(s.tool_call_buffer)] if s.tool_call_buffer else None
        total = (s.prompt_tokens or 0) + (s.completion_tokens or 0) if (
            s.prompt_tokens is not None or s.completion_tokens is not None
        ) else None

        return LLMResponse(
            content="".join(s.content_parts) or None,
            model=s.model,
            provider=self.provider_name,
            prompt_tokens=s.prompt_tokens,
            completion_tokens=s.completion_tokens,
            total_tokens=total,
            finish_reason=s.finish_reason,
            reasoning="".join(s.reasoning_parts) or None,
            tool_calls=tool_calls,
        )


def _stream_tool_call_deltas(
    tc_deltas: list, tool_call_buffer: dict[int, dict],
    on_chunk: StreamCallback, model: str,
) -> None:
    """Stream tool call fragments to the frontend as they arrive."""
    for tc_delta in tc_deltas:
        idx = tc_delta["index"]
        buf = tool_call_buffer.get(idx, {})
        fn = tc_delta.get("function", {})
        name_part = fn.get("name", "")
        args_part = fn.get("arguments", "")
        if name_part:
            on_chunk(LLMStreamChunk(content=f"\n🔧 {name_part}(", done=False, chunk_type="tool_call", model=model))
        if args_part:
            on_chunk(LLMStreamChunk(content=args_part, done=False, chunk_type="tool_call", model=model))


def _accumulate_tool_calls(tc_deltas: list, tool_call_buffer: dict[int, dict]) -> None:
    """Merge streamed tool call fragments into the buffer."""
    for tc_delta in tc_deltas:
        idx = tc_delta["index"]
        if idx not in tool_call_buffer:
            tool_call_buffer[idx] = {"id": tc_delta.get("id", ""), "name": "", "arguments": ""}
        buf = tool_call_buffer[idx]
        if tc_delta.get("id"):
            buf["id"] = tc_delta["id"]
        fn = tc_delta.get("function", {})
        if fn.get("name"):
            buf["name"] += fn["name"]
        if fn.get("arguments"):
            buf["arguments"] += fn["arguments"]
