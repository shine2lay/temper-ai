"""Anthropic LLM provider (Claude models)."""
from typing import Any, Dict

import httpx

from temper_ai.llm.providers.base import BaseLLM, LLMProvider, LLMResponse, StreamCallback


class AnthropicLLM(BaseLLM):
    """Anthropic LLM provider (Claude models)."""

    def _get_endpoint(self) -> str:
        return "/v1/messages"

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        messages = kwargs.get("messages")
        if messages is None:
            messages = [{"role": "user", "content": prompt}]
        request: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "top_p": kwargs.get("top_p", self.top_p),
        }
        # Anthropic API requires system messages as a top-level param
        non_system = [m for m in messages if m.get("role") != "system"]
        system_msgs = [m for m in messages if m.get("role") == "system"]
        if system_msgs:
            request["system"] = system_msgs[0]["content"]
            request["messages"] = non_system
        return request

    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        content_block = response["content"][0]
        usage = response.get("usage", {})

        return LLMResponse(
            content=content_block["text"],
            model=response.get("model", self.model),
            provider=LLMProvider.ANTHROPIC,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            total_tokens=(usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) or None,
            latency_ms=latency_ms,
            finish_reason=response.get("stop_reason"),
            raw_response=response,
        )

    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Streaming not yet implemented for Anthropic provider."""
        raise NotImplementedError("Streaming support not yet implemented for Anthropic provider")

    async def _aconsume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Async streaming not yet implemented for Anthropic provider."""
        raise NotImplementedError("Async streaming support not yet implemented for Anthropic provider")
