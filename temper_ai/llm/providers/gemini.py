"""Google Gemini LLM provider — via the google-genai SDK.

Uses the google-genai Python SDK. Requires: pip install google-genai

Key differences from OpenAI:
- Uses generateContent API with Part objects
- Tool calling uses FunctionDeclaration, not OpenAI function format
- Response has candidates[].content.parts[]
"""

import json
import logging
from typing import Any

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback

logger = logging.getLogger(__name__)


def _ensure_genai():
    try:
        from google import genai
        return genai
    except ImportError as exc:
        raise ImportError(
            "google-genai is required for the Gemini provider. "
            "Install with: pip install google-genai"
        ) from exc


class GeminiLLM(BaseLLM):
    """Provider for Google Gemini models."""

    PROVIDER_NAME = "gemini"

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        base_url: str = "https://generativelanguage.googleapis.com",
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
        genai = _ensure_genai()
        self._client = genai.Client(api_key=api_key)

    def complete(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        """Call Gemini via the google-genai SDK."""
        from google.genai import types

        system, contents = _convert_messages(messages)

        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
        )
        if system:
            config.system_instruction = system

        tools = kwargs.get("tools")
        if tools:
            config.tools = [_convert_tools(tools)]

        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        return _parse_response(response, self.model)

    def stream(self, messages: list[dict], on_chunk: StreamCallback | None = None,
               **kwargs: Any) -> LLMResponse:
        """Stream Gemini response."""
        from google.genai import types

        system, contents = _convert_messages(messages)

        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
        )
        if system:
            config.system_instruction = system

        tools = kwargs.get("tools")
        if tools:
            config.tools = [_convert_tools(tools)]

        content_parts: list[str] = []

        for chunk in self._client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        ):
            text = chunk.text or ""
            if text:
                content_parts.append(text)
                if on_chunk:
                    on_chunk(LLMStreamChunk(content=text, done=False))

        if on_chunk:
            on_chunk(LLMStreamChunk(content="", done=True))

        # Return final aggregated response
        full_text = "".join(content_parts)
        return LLMResponse(
            content=full_text,
            model=self.model,
            provider="gemini",
            finish_reason="stop",
        )

    # Override base class abstract methods (we use SDK, not raw HTTP)
    def _get_headers(self) -> dict[str, str]:
        return {}

    def _get_endpoint(self) -> str:
        return ""

    def _build_request(self, messages: list[dict], **kwargs: Any) -> dict:
        return {}

    def _parse_response(self, response: dict) -> LLMResponse:
        return LLMResponse(content="", model=self.model, provider=self.PROVIDER_NAME)

    def _parse_stream_chunk(self, chunk: dict) -> LLMStreamChunk | None:
        return None


def _convert_messages(messages: list[dict]) -> tuple[str, list]:
    """Convert OpenAI-format messages to Gemini format.

    Returns (system_instruction, contents).
    """
    from google.genai import types

    system = ""
    contents = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            system = content
        elif role == "user":
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=content)],
            ))
        elif role == "assistant":
            parts = []
            if content:
                parts.append(types.Part.from_text(text=content))
            # Handle tool calls in assistant messages
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    func = tc.get("function", tc)
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"raw": args}
                    parts.append(types.Part.from_function_call(
                        name=func.get("name", ""),
                        args=args,
                    ))
            contents.append(types.Content(role="model", parts=parts))
        elif role == "tool":
            # Tool result
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=msg.get("name", ""),
                    response={"result": content},
                )],
            ))

    return system, contents


def _convert_tools(tools: list[dict]) -> Any:
    """Convert OpenAI tool format to Gemini FunctionDeclaration format."""
    from google.genai import types

    declarations = []
    for tool in tools:
        func = tool.get("function", tool)
        declarations.append(types.FunctionDeclaration(
            name=func.get("name", ""),
            description=func.get("description", ""),
            parameters=func.get("parameters"),
        ))

    return types.Tool(function_declarations=declarations)


def _parse_response(response: Any, model: str) -> LLMResponse:
    """Parse Gemini response to standard LLMResponse."""
    content_text = ""
    tool_calls = []

    if response.candidates:
        candidate = response.candidates[0]
        for part in candidate.content.parts:
            if part.text:
                content_text += part.text
            elif part.function_call:
                tool_calls.append({
                    "id": f"call_{part.function_call.name}",
                    "type": "function",
                    "function": {
                        "name": part.function_call.name,
                        "arguments": dict(part.function_call.args) if part.function_call.args else {},
                    },
                })

    # Token usage
    prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) if response.usage_metadata else 0
    completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) if response.usage_metadata else 0

    return LLMResponse(
        content=content_text,
        model=model,
        provider="gemini",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        finish_reason="tool_calls" if tool_calls else "stop",
        tool_calls=tool_calls if tool_calls else None,
    )
