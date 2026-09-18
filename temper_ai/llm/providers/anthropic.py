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

Several subscriptions, one cache
-------------------------------
OAuth tokens are pooled: ``CLAUDE_CODE_OAUTH_TOKEN``, ``_BACKUP`` and
``_2``…``_9`` are separate subscriptions with separate rate-limit windows.
The pool rotates *between* agents and never *within* one — an agent's calls
in a given run all go out on the same token, because Anthropic's prompt
cache is per credential and a tool-using run re-sends its transcript every
iteration. A token that answers 429 is cooled until its reset and the call
is retried on another; the sticky agent then loses its warm cache, which is
why failover is a fallback and not the normal path. See
``temper_ai.llm.token_pool``.

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
import time
from datetime import datetime
from typing import Any, Protocol

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback
from temper_ai.llm.token_pool import (
    PoolExhausted,
    TokenPool,
    sticky_key_from_kwargs,
    tokens_from_env,
)

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

# Models that answer 400 `temperature is deprecated for this model`. Learned at
# runtime rather than listed ahead of time: the set grows with every release,
# and a hard-coded list is wrong the day after it is written. One rejected
# request per model per process teaches it.
_NO_TEMPERATURE: set[str] = set()
_no_temperature_lock = threading.Lock()


def _temperature_rejected(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status == 400 and "temperature" in str(exc).lower() and "deprecated" in str(exc).lower()


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


def _apply_prompt_caching(create_kwargs: dict[str, Any]) -> None:
    """Ask Anthropic to cache the stable prefix of this request, in place.

    A tool-using agent re-sends its whole transcript on every iteration: by the
    fortieth call the system prompt, the tool schemas and thirty-nine tool
    results have each been paid for dozens of times. Cache reads are a tenth of
    the price of fresh input, and nothing here was asking for them.

    Two of the four allowed breakpoints, in the order Anthropic assembles a
    prompt (tools, then system, then messages):

    * the last system block — covers the tool schemas and the whole system
      prompt, which never change within a run;
    * the last block of the last message — a breakpoint that moves forward each
      turn, so the previous turn's transcript is a cache hit. Earlier
      breakpoints keep working while they live, so the moving one costs one
      cache write per turn and saves re-reading everything before it.

    The cache is keyed to the credential, which is why an agent stays on one
    subscription for a whole run (see the module docstring).
    """
    system = create_kwargs.get("system")
    if isinstance(system, str) and system:
        system = [{"type": "text", "text": system}]
        create_kwargs["system"] = system
    if isinstance(system, list) and system:
        _mark(system[-1])

    messages = create_kwargs.get("messages") or []
    if not messages:
        return
    last = messages[-1]
    content = last.get("content")
    if isinstance(content, str) and content:
        content = [{"type": "text", "text": content}]
        last["content"] = content
    if isinstance(content, list) and content:
        _mark(content[-1])


def _mark(block: Any) -> None:
    """Put a cache breakpoint on one block, if it is one we may annotate."""
    if isinstance(block, dict) and "cache_control" not in block:
        block["cache_control"] = {"type": "ephemeral"}


def _is_rate_limit(exc: Exception) -> bool:
    """Whether this failure means "this subscription, not now".

    Matched on status code rather than SDK class so an overload (529) and a
    plain HTTP error from a proxy are treated the same way, and so the check
    holds if the SDK reorganises its exception types.
    """
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status in (429, 529)


def _reset_epoch(exc: Exception) -> float | None:
    """When the limited subscription is usable again, from the response headers.

    `retry-after` (seconds) or `anthropic-ratelimit-*-reset` (RFC 3339). None
    when the response says nothing, and the pool then applies a fixed wait.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            return time.time() + float(retry_after)
        except (TypeError, ValueError):
            pass
    resets = [headers.get(k) for k in (
        "anthropic-ratelimit-unified-reset",
        "anthropic-ratelimit-tokens-reset",
        "anthropic-ratelimit-requests-reset",
    ) if headers.get(k)]
    epochs = []
    for value in resets:
        try:
            epochs.append(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
        except ValueError:
            continue
    return max(epochs) if epochs else None


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
        self._anthropic = anthropic_mod
        self._base_url = base_url if base_url != "https://api.anthropic.com" else None
        self._clients: dict[str, Any] = {}
        self._clients_lock = threading.Lock()

        # Pool only the env-configured OAuth subscriptions, and only when this
        # provider is actually using one: an explicitly passed credential (a
        # test's, a caller's) is the one to use, not a hint to go looking for
        # siblings of it in the environment.
        pooled: list[str] = []
        if self.auth_mode == "oauth" and not (api_key or "").strip():
            pooled = [t for t in tokens_from_env(OAUTH_TOKEN_ENV) if t.startswith(OAUTH_TOKEN_PREFIX)]
        self._pool = TokenPool(name="anthropic-oauth", tokens=pooled) if len(pooled) > 1 else None

        self._client = self._client_for(credential) if credential else None
        logger.info(
            "Anthropic provider: auth mode %s%s",
            self.auth_mode,
            f", {len(self._pool)} pooled subscriptions" if self._pool else "",
        )

    def _client_for(self, credential: str):
        """The SDK client for one credential, created once and reused.

        One client per token rather than one per call: the SDK holds an HTTP
        connection pool, and rebuilding it for every request of a 60-iteration
        run costs a TLS handshake each time.
        """
        with self._clients_lock:
            client = self._clients.get(credential)
            if client is not None:
                return client
            client_kwargs: dict[str, Any] = {"base_url": self._base_url, "timeout": self.timeout}
            if credential.startswith(OAUTH_TOKEN_PREFIX):
                # Bearer, not x-api-key: the SDK's own way of carrying OAuth.
                client_kwargs["auth_token"] = credential
                client_kwargs["api_key"] = None
            else:
                client_kwargs["api_key"] = credential
            client = self._anthropic.Anthropic(**client_kwargs)
            self._clients[credential] = client
            return client

    def _credential_for_call(self, kwargs: dict[str, Any]) -> str | None:
        """Which subscription this call goes out on (see the module docstring)."""
        if self._pool is None:
            return self.api_key
        return self._pool.pick(sticky_key_from_kwargs(kwargs))

    def _send(self, create_kwargs: dict[str, Any], kwargs: dict[str, Any], run) -> Any:
        """One request, surviving a subscription limit and a rejected knob.

        Newer models refuse `temperature` outright (400, not a warning), which
        killed the request rather than the parameter. The first refusal per
        model teaches the process to stop sending it.
        """
        try:
            return self._call_with_pool(kwargs, run)
        except Exception as exc:  # noqa: BLE001 - narrowed immediately
            if "temperature" not in create_kwargs or not _temperature_rejected(exc):
                raise
            model = create_kwargs["model"]
            with _no_temperature_lock:
                first = model not in _NO_TEMPERATURE
                _NO_TEMPERATURE.add(model)
            if first:
                logger.warning("Anthropic: %s rejects temperature; dropping it for this model", model)
            create_kwargs.pop("temperature")
            return self._call_with_pool(kwargs, run)

    def _call_with_pool(self, kwargs: dict[str, Any], run) -> Any:
        """Run `run(client)`, moving to another subscription on a rate limit.

        Attempts are bounded by the pool size: each 429 cools exactly one
        token, so at worst every subscription is tried once and the pool then
        reports itself exhausted instead of spinning.
        """
        attempts = len(self._pool) if self._pool else 1
        last_error: Exception | None = None
        for _ in range(max(attempts, 1)):
            credential = self._credential_for_call(kwargs)
            if credential is None:
                raise RuntimeError("Anthropic provider has no credential configured")
            try:
                return run(self._client_for(credential))
            except Exception as exc:  # noqa: BLE001 - re-raised below unless it is a limit
                if self._pool is None or not _is_rate_limit(exc):
                    raise
                self._pool.cool(credential, until=_reset_epoch(exc))
                last_error = exc
        raise PoolExhausted(len(self._pool) if self._pool else 0,
                            self._pool.soonest_reset() if self._pool else None) from last_error

    def _build_create_kwargs(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        """The ``messages.create`` payload, shaped for the credential in use."""
        system, claude_messages = _extract_system(messages)

        model = self.resolve_model(kwargs)
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": self.max_tokens,
        }
        if model not in _NO_TEMPERATURE:
            create_kwargs["temperature"] = self.temperature
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
        # After shaping, so the identity blocks the shaper prepends are inside
        # the cached prefix rather than ahead of it (a block added before the
        # breakpoint on the next call would miss every time).
        _apply_prompt_caching(create_kwargs)
        return create_kwargs

    def complete(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        """Call Claude via the Anthropic SDK."""
        create_kwargs = self._build_create_kwargs(messages, **kwargs)
        response = self._send(create_kwargs, kwargs, lambda client: client.messages.create(**create_kwargs))
        return _parse_response(response, create_kwargs["model"])

    def stream(self, messages: list[dict], on_chunk: StreamCallback | None = None,
               **kwargs: Any) -> LLMResponse:
        """Stream Claude response."""
        create_kwargs = self._build_create_kwargs(messages, **kwargs)

        content_parts: list[str] = []

        def run(client):
            with client.messages.stream(**create_kwargs) as stream:
                for text in stream.text_stream:
                    content_parts.append(text)
                    if on_chunk:
                        on_chunk(LLMStreamChunk(content=text, done=False))
                return stream.get_final_message()

        # A rate limit surfaces on entering the stream, before any chunk; if it
        # ever arrives mid-stream the partial text is dropped and the retry
        # starts clean rather than emitting the same prefix twice.
        final = self._send(create_kwargs, kwargs, run)

        if on_chunk:
            on_chunk(LLMStreamChunk(content="", done=True))

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

    # Cached input is reported in its own counters, not in input_tokens. Left
    # out, a run whose prefix is being cached looks like it stopped sending a
    # prompt at all: input_tokens collapses to the few hundred new tokens and
    # the usage figures stop describing the request.
    usage = response.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    prompt_tokens = usage.input_tokens + cache_read + cache_write

    return LLMResponse(
        content=content_text,
        model=model,
        provider="anthropic",
        prompt_tokens=prompt_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=prompt_tokens + usage.output_tokens,
        finish_reason="tool_calls" if tool_calls else response.stop_reason or "stop",
        tool_calls=tool_calls if tool_calls else None,
    )
