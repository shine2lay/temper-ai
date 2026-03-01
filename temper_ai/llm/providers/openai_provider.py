"""OpenAI LLM provider (GPT models)."""

import json
import logging
import time
from typing import Any

import httpx

from temper_ai.llm.providers._stream_helpers import (
    build_stream_result,
    emit_final_chunk,
    process_chunk_content,
)
from temper_ai.llm.providers.base import (
    BaseLLM,
    LLMProvider,
    LLMResponse,
    StreamCallback,
)
from temper_ai.shared.core.context import ExecutionContext

logger = logging.getLogger(__name__)

# OpenAI SSE prefix for data lines
_SSE_DATA_PREFIX = "data: "
_SSE_DONE_SENTINEL = "[DONE]"


class OpenAILLM(BaseLLM):
    """OpenAI LLM provider (GPT models)."""

    def _get_endpoint(self) -> str:
        return "/v1/chat/completions"

    def _get_headers(self) -> dict[str, str]:
        return self._build_bearer_auth_headers()

    def _build_request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        messages = kwargs.get("messages")
        if messages is None:
            messages = [{"role": "user", "content": prompt}]
        return {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
            "stream": kwargs.get("stream", False),
        }

    def _parse_response(self, response: dict[str, Any], latency_ms: int) -> LLMResponse:
        choice = response["choices"][0]
        usage = response.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=response.get("model", self.model),
            provider=LLMProvider.OPENAI,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
            raw_response=response,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(
        self,
        prompt: str,
        context: ExecutionContext | None = None,
        on_chunk: StreamCallback | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Synchronous streaming completion using OpenAI SSE format.

        Streams tokens from OpenAI's SSE response, calling on_chunk for
        each content delta. Returns an aggregated LLMResponse. Falls back
        to complete() when no on_chunk callback is provided.
        """
        if on_chunk is None:
            return self.complete(prompt, context, **kwargs)

        self._make_streaming_call_impl(prompt, context, on_chunk, **kwargs)

        # scanner-ignore: duplicate - Circuit breaker wrapper, identical across providers by design
        def _make_streaming_call() -> LLMResponse:
            start_time = time.time()
            request_data = self._build_request(prompt, stream=True, **kwargs)
            headers = self._get_headers()
            endpoint = f"{self.base_url}{self._get_endpoint()}"

            client = self._get_client()
            request = client.build_request(
                "POST", endpoint, json=request_data, headers=headers
            )
            response = client.send(request, stream=True)
            return self._execute_streaming_impl(start_time, response, on_chunk)

        return self._circuit_breaker.call(_make_streaming_call)

    async def astream(
        self,
        prompt: str,
        context: ExecutionContext | None = None,
        on_chunk: StreamCallback | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async streaming completion using OpenAI SSE format."""
        if on_chunk is None:
            return await self.acomplete(prompt, context, **kwargs)

        self._make_streaming_call_impl(prompt, context, on_chunk, **kwargs)

        # scanner-ignore: duplicate - Circuit breaker wrapper, identical across providers by design
        async def _make_async_streaming_call() -> LLMResponse:
            start_time = time.time()
            request_data = self._build_request(prompt, stream=True, **kwargs)
            headers = self._get_headers()
            endpoint = f"{self.base_url}{self._get_endpoint()}"

            client = await self._get_async_client_safe()
            request = client.build_request(
                "POST", endpoint, json=request_data, headers=headers
            )
            response = await client.send(request, stream=True)
            return await self._execute_streaming_async_impl(
                start_time, response, on_chunk
            )

        result: LLMResponse = await self._circuit_breaker.async_call(
            _make_async_streaming_call
        )
        return result

    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume OpenAI SSE streaming response synchronously.

        Parses Server-Sent Events lines, accumulates content deltas,
        and emits a final chunk with token counts from the usage field.
        """
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        finish_reason: str | None = None

        for line in response.iter_lines():
            line = line.strip()
            if not line or not line.startswith(_SSE_DATA_PREFIX):
                continue
            payload = line[len(_SSE_DATA_PREFIX) :]
            if payload == _SSE_DONE_SENTINEL:
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                logger.debug("OpenAI stream: failed to parse SSE payload: %s", payload)
                continue

            chunk_content, fin_reason, usage = self._extract_openai_chunk(data)
            if chunk_content:
                process_chunk_content(
                    chunk_content,
                    "content",
                    content_parts,
                    thinking_parts,
                    on_chunk,
                    self.model,
                )
            if fin_reason:
                finish_reason = fin_reason
            if usage:
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")

        emit_final_chunk(
            on_chunk, self.model, prompt_tokens, completion_tokens, finish_reason
        )

        return build_stream_result(
            content_parts,
            self.model,
            LLMProvider.OPENAI,
            prompt_tokens,
            completion_tokens,
            finish_reason,
        )

    async def _aconsume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume OpenAI SSE streaming response asynchronously."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        finish_reason: str | None = None

        async for line in response.aiter_lines():
            line = line.strip()
            if not line or not line.startswith(_SSE_DATA_PREFIX):
                continue
            payload = line[len(_SSE_DATA_PREFIX) :]
            if payload == _SSE_DONE_SENTINEL:
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                logger.debug("OpenAI astream: failed to parse SSE payload: %s", payload)
                continue

            chunk_content, fin_reason, usage = self._extract_openai_chunk(data)
            if chunk_content:
                process_chunk_content(
                    chunk_content,
                    "content",
                    content_parts,
                    thinking_parts,
                    on_chunk,
                    self.model,
                )
            if fin_reason:
                finish_reason = fin_reason
            if usage:
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")

        emit_final_chunk(
            on_chunk, self.model, prompt_tokens, completion_tokens, finish_reason
        )

        return build_stream_result(
            content_parts,
            self.model,
            LLMProvider.OPENAI,
            prompt_tokens,
            completion_tokens,
            finish_reason,
        )

    @staticmethod
    def _extract_openai_chunk(
        data: dict[str, Any],
    ) -> tuple[str, str | None, dict[str, Any] | None]:
        """Extract content delta, finish_reason, and usage from an SSE chunk.

        Returns (content, finish_reason, usage).
        """
        choices = data.get("choices", [])
        content = ""
        finish_reason: str | None = None
        if choices:
            choice = choices[0]
            delta = choice.get("delta", {})
            content = delta.get("content") or ""
            finish_reason = choice.get("finish_reason")
        usage: dict[str, Any] | None = data.get("usage")
        return content, finish_reason, usage
