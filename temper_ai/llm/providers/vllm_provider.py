"""vLLM provider (self-hosted inference) with streaming support.

Uses OpenAI-compatible API with SSE streaming and reasoning token support.
Requires vLLM served with --reasoning-parser for thinking/reasoning separation.
"""

import json
import logging
import time
from typing import Any, cast

import httpx

from temper_ai.llm.constants import SSE_STREAM_DONE_MARKER
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


class VllmLLM(BaseLLM):
    """vLLM provider (self-hosted inference).

    Uses /v1/chat/completions with reasoning token support when served
    with --reasoning-parser. Falls back to /v1/completions only when
    explicitly requested via use_chat=False.
    Supports SSE streaming for real-time token visibility.
    """

    def _get_endpoint(self) -> str:
        return "/v1/chat/completions"

    def _get_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        stream = kwargs.get("stream", False)
        tools = kwargs.get("tools")
        messages = kwargs.get("messages")
        if messages is None:
            messages = [{"role": "user", "content": prompt}]

        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
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

        # Disable thinking/reasoning mode for models that support it
        # (e.g. Qwen3.5). Thinking wastes tokens on internal reasoning
        # that temper-ai prompts already provide via structured prompts.
        request["chat_template_kwargs"] = {"enable_thinking": False}

        # Request usage stats in streaming mode
        if stream:
            request["stream_options"] = {"include_usage": True}

        return request

    @staticmethod
    def _format_tool_calls_xml(tool_calls: list) -> str:
        """Convert native OpenAI-format tool calls to <tool_call> XML tags.

        Works with both complete tool calls (from non-streaming responses)
        and accumulated tool call buffers (from streaming deltas).

        Args:
            tool_calls: List of dicts with 'function' key containing
                        'name' and 'arguments'.

        Returns:
            Newline-separated ``<tool_call>`` XML tags, or empty string.
        """
        if not tool_calls:
            return ""
        parts = []
        for tc in tool_calls:
            func = tc.get("function", {})
            args = func.get("arguments", {})
            # Streaming accumulates arguments as a JSON string
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    pass
            tc_dict = {
                "name": func.get("name", ""),
                "arguments": args,
            }
            parts.append(f"<tool_call>\n{json.dumps(tc_dict)}\n</tool_call>")
        return "\n".join(parts)

    def _parse_response(self, response: dict[str, Any], latency_ms: int) -> LLMResponse:
        choice = response["choices"][0]
        message = choice.get("message", {})
        content = message.get("content", "")
        usage = response.get("usage", {})

        # Handle tool calls (OpenAI function calling format)
        tool_calls = message.get("tool_calls")
        xml = self._format_tool_calls_xml(tool_calls or [])
        if xml:
            content = content + "\n" + xml

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
        context: ExecutionContext | None = None,
        on_chunk: StreamCallback | None = None,
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
            request = client.build_request(
                "POST", endpoint, json=request_data, headers=headers
            )

            response = client.send(request, stream=True)
            return self._execute_streaming_impl(
                start_time, response, on_chunk, cache_key
            )

        return self._circuit_breaker.call(_make_streaming_call)

    async def astream(
        self,
        prompt: str,
        context: ExecutionContext | None = None,
        on_chunk: StreamCallback | None = None,
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
            request = client.build_request(
                "POST", endpoint, json=request_data, headers=headers
            )

            response = await client.send(request, stream=True)
            return cast(
                LLMResponse,
                await self._execute_streaming_async_impl(
                    start_time, response, on_chunk, cache_key
                ),
            )

        result: LLMResponse = await self._circuit_breaker.async_call(
            _make_async_streaming_call
        )
        return result

    @staticmethod
    def _accumulate_delta_tool_calls(
        data: dict[str, Any],
        tool_call_buf: dict[int, dict[str, str]],
    ) -> None:
        """Accumulate streamed tool call deltas into a buffer.

        OpenAI streaming sends tool calls across multiple chunks as
        ``delta.tool_calls[i].function.{name, arguments}``.  Each chunk
        may contain a partial function name or partial JSON arguments.
        This method accumulates them by index so they can be converted
        to ``<tool_call>`` XML after the stream ends.
        """
        choices = data.get("choices", [])
        if not choices:
            return
        delta = choices[0].get("delta", {})
        for tc in delta.get("tool_calls", []):
            idx = tc.get("index", 0)
            func = tc.get("function", {})
            if idx not in tool_call_buf:
                tool_call_buf[idx] = {"name": "", "arguments": ""}
            if "name" in func and func["name"]:
                tool_call_buf[idx]["name"] += func["name"]
            if "arguments" in func and func["arguments"]:
                tool_call_buf[idx]["arguments"] += func["arguments"]

    def _process_sse_chunk(  # noqa: long
        self,
        data: Any,
        content_parts: list[str],
        thinking_parts: list[str],
        tool_call_buf: dict[int, dict[str, str]],
        on_chunk: StreamCallback,
    ) -> tuple[int | None, int | None, str | None]:
        """Process one SSE data chunk. Returns (prompt_tokens, completion_tokens, finish_reason)."""
        chunk_content, chunk_type, is_done = self._extract_chunk_fields(data)
        if chunk_content:
            process_chunk_content(
                chunk_content,
                chunk_type,
                content_parts,
                thinking_parts,
                on_chunk,
                self.model,
            )
        self._accumulate_delta_tool_calls(data, tool_call_buf)
        usage = data.get("usage")
        prompt_tokens = usage.get("prompt_tokens") if usage else None
        completion_tokens = usage.get("completion_tokens") if usage else None
        finish_reason = data["choices"][0].get("finish_reason") if is_done else None
        return prompt_tokens, completion_tokens, finish_reason

    def _finalize_and_build(
        self,
        content_parts: list[str],
        tool_call_buf: dict[int, dict[str, str]],
        prompt_tokens: int | None,
        completion_tokens: int | None,
        finish_reason: str | None,
    ) -> LLMResponse:
        """Convert tool call buffer to XML and build final LLMResponse."""
        if tool_call_buf:
            tc_list = [
                {"function": tool_call_buf[idx]} for idx in sorted(tool_call_buf)
            ]
            xml = self._format_tool_calls_xml(tc_list)
            if xml:
                content_parts.append("\n" + xml)
        return cast(
            LLMResponse,
            build_stream_result(
                content_parts,
                self.model,
                LLMProvider.VLLM,
                prompt_tokens,
                completion_tokens,
                finish_reason,
            ),
        )

    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume SSE streaming response synchronously."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_call_buf: dict[int, dict[str, str]] = {}
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        finish_reason: str | None = None

        for line in response.iter_lines():
            data = self._parse_sse_line(line)
            if data is None:
                continue
            if data == SSE_STREAM_DONE_MARKER:
                emit_final_chunk(
                    on_chunk,
                    self.model,
                    prompt_tokens,
                    completion_tokens,
                    finish_reason,
                )
                break
            pt, ct, fr = self._process_sse_chunk(
                data, content_parts, thinking_parts, tool_call_buf, on_chunk
            )
            if pt is not None:
                prompt_tokens = pt
            if ct is not None:
                completion_tokens = ct
            if fr is not None:
                finish_reason = fr

        return self._finalize_and_build(
            content_parts,
            tool_call_buf,
            prompt_tokens,
            completion_tokens,
            finish_reason,
        )

    async def _aconsume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume SSE streaming response asynchronously."""  # noqa: long
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_call_buf: dict[int, dict[str, str]] = {}
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        finish_reason: str | None = None

        async for line in response.aiter_lines():
            data = self._parse_sse_line(line)
            if data is None:
                continue
            if data == SSE_STREAM_DONE_MARKER:
                emit_final_chunk(
                    on_chunk,
                    self.model,
                    prompt_tokens,
                    completion_tokens,
                    finish_reason,
                )
                break
            pt, ct, fr = self._process_sse_chunk(
                data, content_parts, thinking_parts, tool_call_buf, on_chunk
            )
            if pt is not None:
                prompt_tokens = pt
            if ct is not None:
                completion_tokens = ct
            if fr is not None:
                finish_reason = fr

        return self._finalize_and_build(
            content_parts,
            tool_call_buf,
            prompt_tokens,
            completion_tokens,
            finish_reason,
        )

    @staticmethod
    def _parse_sse_line(line: str) -> Any:
        """Parse a single SSE line.

        SSE format: ``data: {json}`` or ``data: [DONE]``.
        Returns parsed JSON dict, the string ``"[DONE]"``, or None.
        """
        line = line.strip()
        if not line or not line.startswith("data:"):
            return None

        payload = line[len("data:") :].strip()
        if payload == SSE_STREAM_DONE_MARKER:
            return SSE_STREAM_DONE_MARKER

        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_chunk_fields(data: dict[str, Any]) -> tuple[str, str, bool]:
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
