"""Anthropic LLM provider — Claude models via the Anthropic API.

Uses the anthropic Python SDK. Requires: pip install anthropic

Key differences from OpenAI:
- System prompt is a separate parameter, not in messages array
- Tool results use content blocks (tool_use/tool_result), not tool_calls
- Response has content[] array with text and tool_use blocks

Credentials
-----------
The provider accepts two kinds of credential and tells them apart by
prefix. An API key (``sk-ant-api…``) is sent as ``x-api-key``. An OAuth
access token (``sk-ant-oat…``) is sent as a bearer token, which is how the
Anthropic SDK itself carries OAuth credentials (``auth_token=``).

Resolution order: an explicit ``api_key`` argument, then
``ANTHROPIC_API_KEY``, then ``CLAUDE_CODE_OAUTH_TOKEN``. The API key wins
when both are set, because it is this provider's native credential; the
opposite order is a documented source of confusion elsewhere.

Anthropic treats a bare bearer request from a third-party client
differently from one that identifies as its own tooling. What identification
to send — if any — is a policy decision that does not belong in this file.
It is delegated to an *OAuth request shaper* registered at startup
(``register_oauth_shaper``): it may add headers to, and rewrite, each
outgoing request. It is consulted per request, so registration order does
not matter. Without one, OAuth requests go out unshaped and the provider
says so once.
"""

import json
import logging
import os
import threading
from typing import Any, Protocol

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback

logger = logging.getLogger(__name__)

# The previous default, claude-sonnet-4-20250514, was retired: the API now
# answers 404 not_found for it, so every agent without ANTHROPIC_MODEL set
# failed on its first call. Dated ids are what Anthropic's deprecation
# schedule keys on; this one is current as of 2026-09 and can be overridden
# with ANTHROPIC_MODEL or per agent.
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
OAUTH_TOKEN_PREFIX = "sk-ant-oat"  # noqa: S105 - a prefix, not a secret
API_KEY_ENV = "ANTHROPIC_API_KEY"
OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"  # noqa: S105 - name, not a secret

AuthMode = str  # "api_key" | "oauth" | "none"


def resolve_credential(api_key: str | None = None) -> tuple[str | None, AuthMode]:
    """The credential this provider would use, and what kind it is.

    Returns ``(None, "none")`` when nothing is configured, so callers can
    decide whether to initialise the provider at all.
    """
    key = (
        (api_key or "").strip()
        or os.environ.get(API_KEY_ENV, "").strip()
        or os.environ.get(OAUTH_TOKEN_ENV, "").strip()
    )
    if not key:
        return None, "none"
    return key, ("oauth" if key.startswith(OAUTH_TOKEN_PREFIX) else "api_key")


class OAuthRequestShaper(Protocol):
    """How an OAuth request should present itself. Registered at startup."""

    def client_headers(self) -> dict[str, str]:
        """Default headers for every request made with an OAuth token."""
        ...

    def shape(self, create_kwargs: dict[str, Any]) -> dict[str, Any]:
        """Rewrite one outgoing ``messages.create`` payload. Must return it."""
        ...


_oauth_shaper: OAuthRequestShaper | None = None
_warned_unshaped = False
_shaper_lock = threading.Lock()


def register_oauth_shaper(shaper: OAuthRequestShaper | None) -> None:
    """Install (or, with None, remove) the shaper applied to OAuth requests."""
    global _oauth_shaper, _warned_unshaped
    with _shaper_lock:
        _oauth_shaper = shaper
        _warned_unshaped = False


def get_oauth_shaper() -> OAuthRequestShaper | None:
    return _oauth_shaper


def _warn_unshaped_once() -> None:
    global _warned_unshaped
    with _shaper_lock:
        if _warned_unshaped:
            return
        _warned_unshaped = True
    logger.warning(
        "Anthropic provider is using an OAuth token with no request shaper "
        "registered. Requests go out as a bare bearer token; Anthropic "
        "classifies those as third-party usage. Register one with "
        "temper_ai.llm.providers.anthropic.register_oauth_shaper()."
    )


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
        model: str = DEFAULT_MODEL,
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
        credential, self.auth_mode = resolve_credential(api_key)
        self.api_key = credential
        client_kwargs: dict[str, Any] = {
            "base_url": base_url if base_url != "https://api.anthropic.com" else None,
            "timeout": timeout,
        }
        if self.auth_mode == "oauth":
            # Bearer, not x-api-key: the SDK's own way of carrying OAuth.
            client_kwargs["auth_token"] = credential
            client_kwargs["api_key"] = None
        else:
            client_kwargs["api_key"] = credential
        self._client = anthropic_mod.Anthropic(**client_kwargs)
        logger.info("Anthropic provider: auth mode %s", self.auth_mode)

    def _build_create_kwargs(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        """The ``messages.create`` payload, shaped for the credential in use."""
        system, claude_messages = _extract_system(messages)

        create_kwargs: dict[str, Any] = {
            "model": self.resolve_model(kwargs),
            "messages": claude_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system:
            create_kwargs["system"] = system

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _convert_tools(tools)

        if self.auth_mode == "oauth":
            # Resolved per request, not at construction: the shaper is
            # registered from local/ when the provider factory loads, which
            # can be after this provider was built. Headers ride along as
            # the SDK's per-call extra_headers for the same reason.
            shaper = get_oauth_shaper()
            if shaper is None:
                _warn_unshaped_once()
            else:
                create_kwargs = shaper.shape(create_kwargs)
                create_kwargs["extra_headers"] = {
                    **shaper.client_headers(),
                    **(create_kwargs.get("extra_headers") or {}),
                }
        return create_kwargs

    def complete(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        """Call Claude via the Anthropic SDK."""
        create_kwargs = self._build_create_kwargs(messages, **kwargs)
        response = self._client.messages.create(**create_kwargs)
        return _parse_response(response, create_kwargs["model"])

    def stream(self, messages: list[dict], on_chunk: StreamCallback | None = None,
               **kwargs: Any) -> LLMResponse:
        """Stream Claude response."""
        create_kwargs = self._build_create_kwargs(messages, **kwargs)

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
        return _parse_response(final, create_kwargs["model"])

    # The Anthropic and Gemini providers use their SDK clients directly
    # (via complete()/stream()) rather than the httpx-based base class methods.
    # These stubs satisfy the abstract interface but are never called in practice.
    def _get_headers(self) -> dict[str, str]:
        return {}

    def _get_endpoint(self) -> str:
        return ""

    def _build_request(self, messages: list[dict], **kwargs: Any) -> dict:
        return {}

    def _parse_response(self, response: dict, latency_ms: int = 0) -> LLMResponse:
        # Not used — SDK-based providers override complete()/stream() directly.
        return LLMResponse(content="", model=self.model, provider=self.PROVIDER_NAME)

    def _consume_stream(
        self,
        response: Any,
        on_chunk: StreamCallback | None,
    ) -> LLMResponse:
        # Not used — streaming is handled in stream() via the Anthropic SDK client.
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
                raw_args = tc.get("function", {}).get("arguments", tc.get("arguments", {}))
                # Anthropic requires input as dict; _inject_tool_results may serialize to JSON string
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        raw_args = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", tc.get("name", "")),
                    "input": raw_args,
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
    """Convert OpenAI tool format to Anthropic tool format.

    Passes through Anthropic-native server tools (e.g. web_search) as-is.
    """
    anthropic_tools = []
    for tool in tools:
        # Server tools (web_search, code_execution, etc.) have a "type" field
        # like "web_search_20250305" — pass through without conversion.
        if tool.get("type", "").startswith(("web_search", "code_execution")):
            anthropic_tools.append(tool)
            continue
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
                "name": block.name,
                "arguments": block.input,
            })
        # Server-side tool blocks (web_search, code_execution) — handled by
        # Anthropic, not our agent loop. Just skip them; text blocks carry the results.
        elif block.type in ("server_tool_use", "web_search_tool_result", "code_execution_tool_result"):
            pass

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
