"""vLLM provider (self-hosted inference) with streaming support.

Uses OpenAI-compatible API with SSE streaming and reasoning token support.
Requires vLLM served with --reasoning-parser for thinking/reasoning separation.
"""
import json
import logging
import time
from typing import Any, Dict, Optional, cast

import httpx

from src.agents.constants import SSE_STREAM_DONE_MARKER
from src.agents.llm.base import (
    BaseLLM,
    LLMProvider,
    LLMResponse,
    StreamCallback,
)
from src.agents.llm._stream_helpers import (
    build_stream_result,
    emit_final_chunk,
    process_chunk_content,
)
from src.core.context import ExecutionContext

logger = logging.getLogger(__name__)


class VllmLLM(BaseLLM):
    """vLLM provider (self-hosted inference).

    Uses /v1/chat/completions with reasoning token support when served
    with --reasoning-parser. Falls back to /v1/completions only when
    explicitly requested via use_chat=False.
    Supports SSE streaming for real-time token visibility.
    """

    def _get_endpoint(self) -> str:
        return "/v1/chat/completions"

    def _get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        stream = kwargs.get("stream", False)
        tools = kwargs.get("tools")

        request: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
            "stream": stream,
        }

        # Repetition penalty (vLLM uses OpenAI-style parameter name)
        repeat_penalty = kwargs.get("repeat_penalty")
        if repeat_penalty is not None:
            request["repetition_penalty"] = repeat_penalty

        if tools:
            request["tools"] = tools

        # Request usage stats in streaming mode
        if stream:
            request["stream_options"] = {"include_usage": True}

        return request

    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        choice = response["choices"][0]
        message = choice.get("message", {})
        content = message.get("content", "")
        usage = response.get("usage", {})

        # Handle tool calls (OpenAI function calling format)
        tool_calls = message.get("tool_calls")
        if tool_calls:
            tc_parts = []
            for tc in tool_calls:
                func = tc.get("function", {})
                tc_dict = {
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", {}),
                }
                tc_parts.append(
                    f"<tool_call>\n{json.dumps(tc_dict)}\n</tool_call>"
                )
            content = content + "\n" + "\n".join(tc_parts)

        return LLMResponse(
            content=content,
            model=response.get("model", self.model),
            provider=LLMProvider.VLLM,
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
        context: Optional[ExecutionContext] = None,
        on_chunk: Optional[StreamCallback] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Synchronous streaming completion.

        Streams tokens from vLLM's SSE response, calling on_chunk
        for each token. Returns the aggregated LLMResponse.
        """
        if on_chunk is None:
            return self.complete(prompt, context, **kwargs)

        cache_key, cached = self._make_streaming_call_impl(prompt, context, **kwargs)
        if cached is not None:
            return cached

        # scanner-ignore: duplicate - Circuit breaker wrapper, identical across providers by design
        def _make_streaming_call() -> LLMResponse:
            start_time = time.time()
            request_data = self._build_request(prompt, stream=True, **kwargs)
            headers = self._get_headers()
            endpoint = f"{self.base_url}{self._get_endpoint()}"

            client = self._get_client()
            request = client.build_request("POST", endpoint, json=request_data, headers=headers)

            response = client.send(request, stream=True)
            return self._execute_streaming_impl(start_time, response, on_chunk, cache_key)

        return self._circuit_breaker.call(_make_streaming_call)

    async def astream(
        self,
        prompt: str,
        context: Optional[ExecutionContext] = None,
        on_chunk: Optional[StreamCallback] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async streaming completion."""
        if on_chunk is None:
            return await self.acomplete(prompt, context, **kwargs)

        cache_key, cached = self._make_streaming_call_impl(prompt, context, **kwargs)
        if cached is not None:
            return cached

        # scanner-ignore: duplicate - Circuit breaker wrapper, identical across providers by design
        async def _make_async_streaming_call() -> LLMResponse:
            start_time = time.time()
            request_data = self._build_request(prompt, stream=True, **kwargs)
            headers = self._get_headers()
            endpoint = f"{self.base_url}{self._get_endpoint()}"

            client = await self._get_async_client_safe()
            request = client.build_request("POST", endpoint, json=request_data, headers=headers)

            response = await client.send(request, stream=True)
            return cast(
                LLMResponse,
                await self._execute_streaming_async_impl(start_time, response, on_chunk, cache_key),
            )

        result: LLMResponse = await self._circuit_breaker.async_call(_make_async_streaming_call)
        return result

    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume SSE streaming response synchronously."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        finish_reason: Optional[str] = None

        for line in response.iter_lines():
            data = self._parse_sse_line(line)
            if data is None:
                continue

            if data == SSE_STREAM_DONE_MARKER:
                emit_final_chunk(
                    on_chunk, self.model, prompt_tokens,
                    completion_tokens, finish_reason
                )
                break

            chunk_content, chunk_type, is_done = self._extract_chunk_fields(data)

            if chunk_content:
                process_chunk_content(
                    chunk_content, chunk_type, content_parts, thinking_parts,
                    on_chunk, self.model
                )

            # Extract usage from the chunk with stream_options.include_usage
            usage = data.get("usage")
            if usage:
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")

            if is_done:
                finish_reason = data["choices"][0].get("finish_reason")

        return cast(LLMResponse, build_stream_result(
            content_parts, self.model, LLMProvider.VLLM,
            prompt_tokens, completion_tokens, finish_reason
        ))

    async def _aconsume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume SSE streaming response asynchronously."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        finish_reason: Optional[str] = None

        async for line in response.aiter_lines():
            data = self._parse_sse_line(line)
            if data is None:
                continue

            if data == SSE_STREAM_DONE_MARKER:
                emit_final_chunk(
                    on_chunk, self.model, prompt_tokens,
                    completion_tokens, finish_reason
                )
                break

            chunk_content, chunk_type, is_done = self._extract_chunk_fields(data)

            if chunk_content:
                process_chunk_content(
                    chunk_content, chunk_type, content_parts, thinking_parts,
                    on_chunk, self.model
                )

            # Extract usage from the chunk
            usage = data.get("usage")
            if usage:
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")

            if is_done:
                finish_reason = data["choices"][0].get("finish_reason")

        return cast(LLMResponse, build_stream_result(
            content_parts, self.model, LLMProvider.VLLM,
            prompt_tokens, completion_tokens, finish_reason
        ))

    @staticmethod
    def _parse_sse_line(line: str) -> Any:
        """Parse a single SSE line.

        SSE format: ``data: {json}`` or ``data: [DONE]``.
        Returns parsed JSON dict, the string ``"[DONE]"``, or None.
        """
        line = line.strip()
        if not line or not line.startswith("data:"):
            return None

        payload = line[len("data:"):].strip()
        if payload == SSE_STREAM_DONE_MARKER:
            return SSE_STREAM_DONE_MARKER

        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_chunk_fields(data: Dict[str, Any]) -> tuple[str, str, bool]:
        """Extract content, chunk_type, and done flag from an SSE chunk.

        Returns ``(content, chunk_type, done)``.

        vLLM with ``--reasoning-parser qwen3`` uses:
        - ``delta.reasoning_content`` for thinking tokens
        - ``delta.content`` for content tokens
        """
        choices = data.get("choices", [])
        if not choices:
            return "", "content", False

        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        done = finish_reason is not None

        delta = choice.get("delta", {})
        # vLLM reasoning parser puts thinking in reasoning_content
        reasoning = delta.get("reasoning_content", "")
        content = delta.get("content", "")

        if reasoning:
            return reasoning, "thinking", done
        return content or "", "content", done
