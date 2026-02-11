"""Ollama LLM provider (local models) with streaming support."""
import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

from src.agents.llm.base import (
    HTTP_OK,
    BaseLLM,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
    StreamCallback,
)
from src.constants.sizes import SIZE_4KB
from src.core.context import ExecutionContext

logger = logging.getLogger(__name__)


class OllamaLLM(BaseLLM):
    """Ollama LLM provider (local models).

    Uses /api/chat with native tool calling when tools are provided,
    falls back to /api/generate for simple completions.
    Supports streaming for real-time token visibility.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._use_chat_api: bool = False

    def _get_endpoint(self) -> str:
        if self._use_chat_api:
            return "/api/chat"
        return "/api/generate"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
        }

    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        tools = kwargs.get("tools")
        stream = kwargs.get("stream", False)
        if tools:
            self._use_chat_api = True
            request = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "options": {
                    "temperature": kwargs.get("temperature", self.temperature),
                    "top_p": kwargs.get("top_p", self.top_p),
                    "num_predict": kwargs.get("max_tokens", self.max_tokens),
                    "num_ctx": kwargs.get("max_tokens", self.max_tokens) + SIZE_4KB,
                },
                "tools": tools,
                "stream": stream,
            }
            return request
        else:
            self._use_chat_api = False
            return {
                "model": self.model,
                "prompt": prompt,
                "options": {
                    "temperature": kwargs.get("temperature", self.temperature),
                    "top_p": kwargs.get("top_p", self.top_p),
                    "num_predict": kwargs.get("max_tokens", self.max_tokens),
                },
                "stream": stream,
            }

    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        if self._use_chat_api:
            message = response.get("message", {})
            content = message.get("content", "")
            tool_calls = message.get("tool_calls")

            if tool_calls:
                import json as _json
                tc_parts = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tc_dict = {
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", {}),
                    }
                    tc_parts.append(
                        f"<tool_call>\n{_json.dumps(tc_dict)}\n</tool_call>"
                    )
                content = content + "\n" + "\n".join(tc_parts)

            prompt_tokens = response.get("prompt_eval_count")
            completion_tokens = response.get("eval_count")
            total = (prompt_tokens or 0) + (completion_tokens or 0) or None

            return LLMResponse(
                content=content,
                model=self.model,
                provider=LLMProvider.OLLAMA,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total,
                latency_ms=latency_ms,
                finish_reason="stop" if response.get("done") else None,
                raw_response=response,
            )
        else:
            content = response.get("response", "")
            if not content:
                content = response.get("thinking", "")
            return LLMResponse(
                content=content,
                model=self.model,
                provider=LLMProvider.OLLAMA,
                prompt_tokens=response.get("prompt_eval_count"),
                completion_tokens=response.get("eval_count"),
                total_tokens=(response.get("prompt_eval_count", 0) + response.get("eval_count", 0)) or None,
                latency_ms=latency_ms,
                finish_reason="stop" if response.get("done") else None,
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

        Streams tokens from Ollama's NDJSON response, calling on_chunk
        for each token. Returns the aggregated LLMResponse.
        """
        if on_chunk is None:
            return self.complete(prompt, context, **kwargs)

        # Rate limiter check
        if self._rate_limiter is not None:
            entity_id = (context.agent_id if context and hasattr(context, 'agent_id') else self.model)
            allowed, reason = self._rate_limiter.check_and_record_rate_limit(entity_id)
            if not allowed:
                from src.utils.exceptions import LLMRateLimitError
                raise LLMRateLimitError(reason or "LLM rate limit exceeded")

        # Cache check
        cache_key, cached = self._check_cache(prompt, context, **kwargs)
        if cached is not None:
            return cached

        def _make_streaming_call() -> LLMResponse:
            start_time = time.time()
            request_data = self._build_request(prompt, stream=True, **kwargs)
            headers = self._get_headers()
            endpoint = f"{self.base_url}{self._get_endpoint()}"

            client = self._get_client()
            request = client.build_request("POST", endpoint, json=request_data, headers=headers)

            response = client.send(request, stream=True)
            try:
                if response.status_code != HTTP_OK:
                    response.read()
                    from src.agents.llm._base_helpers import handle_error_response
                    handle_error_response(response)

                result = self._consume_stream(response, on_chunk)
            finally:
                response.close()

            latency_ms = int((time.time() - start_time) * 1000)
            result.latency_ms = latency_ms

            # Cache the result
            self._cache_response(cache_key, result)
            return result

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

        # Rate limiter check
        if self._rate_limiter is not None:
            entity_id = (context.agent_id if context and hasattr(context, 'agent_id') else self.model)
            allowed, reason = self._rate_limiter.check_and_record_rate_limit(entity_id)
            if not allowed:
                from src.utils.exceptions import LLMRateLimitError
                raise LLMRateLimitError(reason or "LLM rate limit exceeded")

        # Cache check
        cache_key, cached = self._check_cache(prompt, context, **kwargs)
        if cached is not None:
            return cached

        async def _make_async_streaming_call() -> LLMResponse:
            start_time = time.time()
            request_data = self._build_request(prompt, stream=True, **kwargs)
            headers = self._get_headers()
            endpoint = f"{self.base_url}{self._get_endpoint()}"

            client = await self._get_async_client_safe()
            request = client.build_request("POST", endpoint, json=request_data, headers=headers)

            response = await client.send(request, stream=True)
            try:
                if response.status_code != HTTP_OK:
                    await response.aread()
                    from src.agents.llm._base_helpers import handle_error_response
                    handle_error_response(response)

                result = await self._aconsume_stream(response, on_chunk)
            finally:
                await response.aclose()

            latency_ms = int((time.time() - start_time) * 1000)
            result.latency_ms = latency_ms

            # Cache the result
            self._cache_response(cache_key, result)
            return result

        result: LLMResponse = await self._circuit_breaker.async_call(_make_async_streaming_call)
        return result

    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume NDJSON streaming response synchronously."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        finish_reason: Optional[str] = None

        for line in response.iter_lines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            chunk_content, chunk_type, done = self._extract_chunk_fields(data)

            if chunk_content:
                if chunk_type == "thinking":
                    thinking_parts.append(chunk_content)
                else:
                    content_parts.append(chunk_content)

                on_chunk(LLMStreamChunk(
                    content=chunk_content,
                    chunk_type=chunk_type,
                    done=False,
                    model=self.model,
                ))

            if done:
                prompt_tokens = data.get("prompt_eval_count")
                completion_tokens = data.get("eval_count")
                finish_reason = "stop" if data.get("done") else None

                on_chunk(LLMStreamChunk(
                    content="",
                    chunk_type="content",
                    done=True,
                    model=self.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    finish_reason=finish_reason,
                ))
                break

        full_content = "".join(content_parts)
        total = (prompt_tokens or 0) + (completion_tokens or 0) or None

        return LLMResponse(
            content=full_content,
            model=self.model,
            provider=LLMProvider.OLLAMA,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            finish_reason=finish_reason,
            raw_response=None,
        )

    async def _aconsume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume NDJSON streaming response asynchronously."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        finish_reason: Optional[str] = None

        async for line in response.aiter_lines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            chunk_content, chunk_type, done = self._extract_chunk_fields(data)

            if chunk_content:
                if chunk_type == "thinking":
                    thinking_parts.append(chunk_content)
                else:
                    content_parts.append(chunk_content)

                on_chunk(LLMStreamChunk(
                    content=chunk_content,
                    chunk_type=chunk_type,
                    done=False,
                    model=self.model,
                ))

            if done:
                prompt_tokens = data.get("prompt_eval_count")
                completion_tokens = data.get("eval_count")
                finish_reason = "stop" if data.get("done") else None

                on_chunk(LLMStreamChunk(
                    content="",
                    chunk_type="content",
                    done=True,
                    model=self.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    finish_reason=finish_reason,
                ))
                break

        full_content = "".join(content_parts)
        total = (prompt_tokens or 0) + (completion_tokens or 0) or None

        return LLMResponse(
            content=full_content,
            model=self.model,
            provider=LLMProvider.OLLAMA,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            finish_reason=finish_reason,
            raw_response=None,
        )

    def _extract_chunk_fields(self, data: Dict[str, Any]) -> tuple[str, str, bool]:
        """Extract content, chunk_type, and done flag from an NDJSON chunk.

        Returns (content, chunk_type, done).
        """
        done = data.get("done", False)

        if self._use_chat_api:
            # /api/chat: message.content and message.thinking
            message = data.get("message", {})
            thinking = message.get("thinking", "")
            content = message.get("content", "")
            if thinking:
                return thinking, "thinking", done
            return content, "content", done
        else:
            # /api/generate: response and thinking fields
            thinking = data.get("thinking", "")
            content = data.get("response", "")
            if thinking:
                return thinking, "thinking", done
            return content, "content", done
