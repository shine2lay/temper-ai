"""Anthropic LLM provider (Claude models)."""
from typing import Dict, Any, Optional

from src.agents.llm.base import BaseLLM, LLMProvider, LLMResponse


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
        return {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "top_p": kwargs.get("top_p", self.top_p),
        }

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
