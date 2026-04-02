"""Anthropic LLM provider — Claude models via the Anthropic API.

Uses the anthropic Python SDK. Requires: pip install anthropic

Key differences from OpenAI:
- System prompt is a separate parameter, not in messages array
- Tool results use content blocks (tool_use/tool_result), not tool_calls
- Response has content[] array with text and tool_use blocks
"""

import logging
from typing import Any

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback

logger = logging.getLogger(__name__)


def _ensure_anthropic():
    try:
        import anthropic
        return anthropic
    except ImportError as exc:
        raise ImportError(
            "anthropic is required for the Anthropic provider. "
            "Install with: pip install anthropic"
        ) from exc


class AnthropicLLM(BaseLLM):
    """Provider for Anthropic Claude models."""

    PROVIDER_NAME = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
        **kwargs: Any,
    ):
        super().__init__(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )
        anthropic_mod = _ensure_anthropic()
        self._client = anthropic_mod.Anthropic(
            api_key=api_key,
            base_url=base_url if base_url != "https://api.anthropic.com" else None,
            timeout=timeout,
        )

    def complete(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        """Call Claude via the Anthropic SDK."""
        system, claude_messages = _extract_system(messages)

        tools = kwargs.get("tools")
        tool_defs = _convert_tools(tools) if tools else None

        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": claude_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system:
            create_kwargs["system"] = system
        if tool_defs:
            create_kwargs["tools"] = tool_defs

        response = self._client.messages.create(**create_kwargs)

        return _parse_response(response, self.model)

    def stream(self, messages: list[dict], on_chunk: StreamCallback | None = None,
               **kwargs: Any) -> LLMResponse:
        """Stream Claude response."""
        system, claude_messages = _extract_system(messages)

        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": claude_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system:
            create_kwargs["system"] = system

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _convert_tools(tools)

        content_parts: list[str] = []

        with self._client.messages.stream(**create_kwargs) as stream:
            for text in stream.text_stream:
                content_parts.append(text)
                if on_chunk:
                    on_chunk(LLMStreamChunk(content=text, done=False))

        if on_chunk:
            on_chunk(LLMStreamChunk(content="", done=True))

        # Get the final message for metadata
        final = stream.get_final_message()
        return _parse_response(final, self.model)

    # Override base class methods that use httpx directly
    def _get_headers(self) -> dict[str, str]:
        return {}

    def _get_endpoint(self) -> str:
        return ""

    def _build_request(self, messages: list[dict], **kwargs: Any) -> dict:
        return {}

    def _parse_response(self, response: dict, latency_ms: int = 0) -> LLMResponse:
        return LLMResponse(content="", model=self.model, provider=self.PROVIDER_NAME)

    def _consume_stream(
        self,
        response: Any,
        on_chunk: StreamCallback | None,
    ) -> LLMResponse:
        return LLMResponse(content="", model=self.model, provider=self.PROVIDER_NAME)


def _extract_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """Extract system message and convert remaining to Anthropic format.

    Anthropic takes system as a separate parameter, not in messages.
    Also converts tool_call/tool_result messages to Anthropic's format.
    """
    system = ""
    claude_messages = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            system = content
        elif role == "assistant" and msg.get("tool_calls"):
            # Convert OpenAI tool_calls to Anthropic tool_use blocks
            content_blocks = []
            if content:
                content_blocks.append({"type": "text", "text": content})
            for tc in msg["tool_calls"]:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", tc.get("name", "")),
                    "input": tc.get("function", {}).get("arguments", tc.get("arguments", {})),
                })
            claude_messages.append({"role": "assistant", "content": content_blocks})
        elif role == "tool":
            # Convert OpenAI tool result to Anthropic tool_result block
            claude_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": content,
                }],
            })
        else:
            claude_messages.append({"role": role, "content": content})

    return system, claude_messages


def _convert_tools(tools: list[dict]) -> list[dict]:
    """Convert OpenAI tool format to Anthropic tool format."""
    anthropic_tools = []
    for tool in tools:
        func = tool.get("function", tool)
        anthropic_tools.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {}),
        })
    return anthropic_tools


def _parse_response(response: Any, model: str) -> LLMResponse:
    """Parse Anthropic response to standard LLMResponse."""
    content_text = ""
    tool_calls = []

    for block in response.content:
        if block.type == "text":
            content_text += block.text
        elif block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": block.input,
                },
            })

    return LLMResponse(
        content=content_text,
        model=model,
        provider="anthropic",
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
        total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        finish_reason="tool_calls" if tool_calls else response.stop_reason or "stop",
        tool_calls=tool_calls if tool_calls else None,
    )
