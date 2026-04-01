"""OpenAI-compatible LLM provider.

Handles both completion and streaming via the /v1/chat/completions endpoint.
Works with OpenAI, Azure OpenAI, and any OpenAI-compatible API.
"""

import json
import logging
from typing import Any

import httpx

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback

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

    def _build_request(self, messages: list[dict], **kwargs: Any) -> dict:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
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
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_buffer: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        model = self.model
        prompt_tokens: int | None = None
        completion_tokens: int | None = None

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

            choices = chunk.get("choices", [])
            choice = choices[0] if choices else {}
            delta = choice.get("delta", {})
            model = chunk.get("model", model)

            # Reasoning / thinking tokens (models like Qwen, DeepSeek)
            # vLLM uses "reasoning", DeepSeek/others may use "reasoning_content"
            reasoning_text = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning_text:
                reasoning_parts.append(reasoning_text)
                if on_chunk:
                    on_chunk(LLMStreamChunk(
                        content=reasoning_text,
                        done=False,
                        chunk_type="thinking",
                        model=model,
                    ))

            # Content tokens
            if delta.get("content"):
                content_parts.append(delta["content"])
                if on_chunk:
                    on_chunk(LLMStreamChunk(
                        content=delta["content"],
                        done=False,
                        model=model,
                    ))

            # Tool calls (streamed as fragments across multiple chunks)
            if delta.get("tool_calls"):
                for tc_delta in delta["tool_calls"]:
                    idx = tc_delta["index"]
                    if idx not in tool_call_buffer:
                        tool_call_buffer[idx] = {
                            "id": tc_delta.get("id", ""),
                            "name": "",
                            "arguments": "",
                        }
                    buf = tool_call_buffer[idx]
                    if tc_delta.get("id"):
                        buf["id"] = tc_delta["id"]
                    fn = tc_delta.get("function", {})
                    if fn.get("name"):
                        buf["name"] += fn["name"]
                    if fn.get("arguments"):
                        buf["arguments"] += fn["arguments"]

            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

            # Usage (usually in the final chunk)
            usage = chunk.get("usage")
            if usage:
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")

        # Signal stream end
        if on_chunk:
            on_chunk(LLMStreamChunk(
                content="",
                done=True,
                finish_reason=finish_reason,
            ))

        tool_calls = None
        if tool_call_buffer:
            tool_calls = [tool_call_buffer[i] for i in sorted(tool_call_buffer)]

        total = None
        if prompt_tokens is not None or completion_tokens is not None:
            total = (prompt_tokens or 0) + (completion_tokens or 0)

        return LLMResponse(
            content="".join(content_parts) or None,
            model=model,
            provider=self.provider_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            finish_reason=finish_reason,
            reasoning="".join(reasoning_parts) or None,
            tool_calls=tool_calls,
        )
