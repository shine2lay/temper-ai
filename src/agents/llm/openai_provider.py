"""OpenAI LLM provider (GPT models)."""
from typing import Any, Dict

import httpx

from src.agents.llm.base import BaseLLM, LLMProvider, LLMResponse, StreamCallback


class OpenAILLM(BaseLLM):
    """OpenAI LLM provider (GPT models)."""

    def _get_endpoint(self) -> str:
        return "/v1/chat/completions"

    def _get_headers(self) -> Dict[str, str]:
        return self._build_bearer_auth_headers()

    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
            "stream": False,
        }

    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
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

    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Streaming not yet implemented for OpenAI provider."""
        raise NotImplementedError("Streaming support not yet implemented for OpenAI provider")

    async def _aconsume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Async streaming not yet implemented for OpenAI provider."""
        raise NotImplementedError("Async streaming support not yet implemented for OpenAI provider")
