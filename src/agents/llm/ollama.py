"""Ollama LLM provider (local models)."""
from typing import Dict, Any

from src.agents.llm.base import BaseLLM, LLMProvider, LLMResponse


class OllamaLLM(BaseLLM):
    """Ollama LLM provider (local models).

    Uses /api/chat with native tool calling when tools are provided,
    falls back to /api/generate for simple completions.
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
                    "num_ctx": kwargs.get("max_tokens", self.max_tokens) + 4096,
                },
                "tools": tools,
                "stream": False,
            }
            return request
        else:
            self._use_chat_api = False
            return {
                "model": self.model,
                "prompt": prompt,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "top_p": kwargs.get("top_p", self.top_p),
                "stream": False,
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
            return LLMResponse(
                content=response.get("response", ""),
                model=self.model,
                provider=LLMProvider.OLLAMA,
                prompt_tokens=response.get("prompt_eval_count"),
                completion_tokens=response.get("eval_count"),
                total_tokens=(response.get("prompt_eval_count", 0) + response.get("eval_count", 0)) or None,
                latency_ms=latency_ms,
                finish_reason="stop" if response.get("done") else None,
                raw_response=response,
            )
