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
``ANTHROPIC_API_KEY``, then pi's own Claude logins. The API key wins when
it is set, because it is this provider's native credential.

Several subscriptions, one cache
-------------------------------
Without an API key the provider uses pi's Claude logins: the pi slots the
pools file lists (``pools.logins.slots``, e.g. ``anthropic``,
``anthropic-2``; see ``temper_ai.llm.pi_logins`` and docs/pools.md). Temper
holds no login of its own: each call asks temper-pi-host for its slot's
current login, good for the call's timeout, and keeps it for that call only.
The slot list is read again on each call, so a slot taken out of the file is
never picked again, without a restart; the provider itself comes up only when
the file lists at least one slot at start. When the helper can't be reached the
call fails at once, naming it; there is no other source.

The slots are separate subscriptions with separate rate-limit windows. The
pool rotates *between* agents and never *within* one — an agent's calls in a
given run all go out on the same slot, because Anthropic's prompt cache is per
account and a tool-using run re-sends its transcript every iteration. A slot
that answers 429 is cooled until its reset and the call is retried on another;
the sticky agent then loses its warm cache, which is why failover is a fallback
and not the normal path. A slot whose login pi refuses is cooled for a while
and the call goes on another. See ``temper_ai.llm.token_pool``.

A call can instead name its slot (``token: anthropic-2``). It then goes out on
that slot only: a limit there is not retried on another account but raised as
``TokenCooling``, and the agent's fallback list says where to go next.

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
import random
import threading
import time
from datetime import datetime
from typing import Any, Protocol

import httpx

from temper_ai.llm import pi_logins
from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback
from temper_ai.llm.token_pool import (
    PoolExhausted,
    TokenCooling,
    TokenPool,
    sticky_key_from_kwargs,
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
# The pool's name: coolings are shared under it by every temper process.
POOL_NAME = "anthropic-oauth"
_NO_SLOT = ("the pools file lists no pi slot (pools.logins.slots), so temper has no Claude "
            "login (docs/pools.md, 'Where the logins come from')")
# How long, in all, a call whose stream broke keeps waiting to send it again
# (`stream_retry_budget_s`). An overload burst outlasts a few seconds: with the
# base class's three attempts (1 s, then 2 s) one ended its agent 30 minutes in.
DEFAULT_STREAM_RETRY_BUDGET_S = 600.0
# The longest single wait between two sends of a broken stream.
_STREAM_RETRY_MAX_WAIT_S = 60.0

AuthMode = str  # "api_key" | "oauth" | "none"

# Room kept for the answer itself when a thinking budget is set: max_tokens is
# the ceiling for thinking plus reply together.
_ANSWER_HEADROOM = 8_000

# Which knob a model actually obeys. Both are *accepted* by every model here;
# only one of them changes anything, and which one flipped with the generation.
# Measured on one hard prompt, output tokens:
#
#   opus-5        effort low 427 -> max 1,302   budget 1k 753 vs 16k 734  (ignored)
#   sonnet-4-6    effort low 1,143 vs max 1,139 (ignored)   budget 1k 4,760 -> 16k 7,232
#
# So sending a budget to a Claude 5 model is not a cap, it is a no-op that
# reads like a cap — the expensive kind of silence.
# Listed one id at a time rather than by family prefix: which knob a model
# obeys has already flipped once between generations, and a prefix quietly
# decides it for a model nobody has measured.
_ADAPTIVE_EFFORT_MODELS = (
    "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
    "claude-opus-4-8", "claude-opus-4-7",
)

# What each effort level means to a model that only understands a fixed budget.
# `low` is deliberately None: on those models extended thinking is opt-in and
# enabling it *raises* output (sonnet-4-6: 1,099 tokens off, 4,760 at a 1k
# budget), so the cheapest setting is not to enable it at all.
_EFFORT_AS_BUDGET: dict[str, int | None] = {
    "low": None, "medium": 4_000, "high": 8_000, "max": 16_000,
}

# Thinking a model does but will not show is thinking nobody can check. An
# effort setting alone buys the first: measured 2026-09-28 on opus-5-5, `effort:
# low` spent 134 output tokens on an 11-character answer and returned a single
# empty thinking block. Asking for a summary as well is what makes those tokens
# readable — 273 characters of thinking on the same prompt.
_VISIBLE_THINKING = {"type": "adaptive", "display": "summarized"}

# Models that refuse the `thinking` parameter. Learned from the first refusal
# rather than listed: which knobs a generation accepts has already flipped once,
# and a request killed by a knob is worse than a request without it.
_NO_VISIBLE_THINKING: set[str] = set()

_thinking_warned: set[str] = set()


def _honours_effort(model: str) -> bool:
    return any(model.startswith(m) for m in _ADAPTIVE_EFFORT_MODELS)


def _warn_once(key: str, message: str, *args: Any) -> None:
    with _no_temperature_lock:
        if key in _thinking_warned:
            return
        _thinking_warned.add(key)
    logger.warning(message, *args)

# Models that answer 400 `temperature is deprecated for this model`. Learned at
# runtime rather than listed ahead of time: the set grows with every release,
# and a hard-coded list is wrong the day after it is written. One rejected
# request per model per process teaches it.
_NO_TEMPERATURE: set[str] = set()
_no_temperature_lock = threading.Lock()


def _temperature_rejected(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status == 400 and "temperature" in str(exc).lower() and "deprecated" in str(exc).lower()


def _thinking_rejected(exc: Exception) -> bool:
    """Whether the request was refused *for asking to see the thinking*.

    Narrow on purpose: only a 400 that names the parameter counts, so a limit,
    an overload or a bad prompt is still raised rather than quietly retried
    with one knob fewer.
    """
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status == 400 and "thinking" in str(exc).lower()


def resolve_credential(api_key: str | None = None) -> tuple[str | None, AuthMode]:
    """The credential this provider would use, and what kind it is.

    An API key (the argument, then ``ANTHROPIC_API_KEY``) is used as it is.
    Without one, pi's Claude logins when the pools file lists any slot:
    ``(None, "oauth")``, no fixed credential, each call fetches its slot's
    login. ``(None, "none")`` when neither is configured, so callers can
    decide whether to initialise the provider at all. A malformed slot list
    raises ``pi_logins.PiLoginsMisconfigured``.
    """
    key = (api_key or "").strip() or os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key, ("oauth" if key.startswith(OAUTH_TOKEN_PREFIX) else "api_key")
    if pi_logins.configured_slots():
        return None, "oauth"
    return None, "none"


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


def _apply_thinking_control(
    create_kwargs: dict[str, Any],
    model: str,
    effort: str | None,
    budget: int | None,
) -> None:
    """Ask for as much thinking as was asked for, in the dialect this model speaks.

    Thinking is billed as output, so this is the knob that caps that side of a
    run's bill. Which knob works depends on the generation (see
    `_ADAPTIVE_EFFORT_MODELS`), and the one a model ignores is accepted without
    complaint — so a setting aimed at the wrong knob looks like a control and
    is a no-op. Rather than pass it through and let it lie, translate it and say
    so once.
    """
    if not effort and not budget:
        return

    if _honours_effort(model):
        if budget and not effort:
            effort = "low" if budget <= 2_000 else "medium" if budget <= 8_000 else "high"
            _warn_once(
                f"budget-on-adaptive:{model}",
                "Anthropic: %s ignores thinking budgets (adaptive thinking); reading "
                "thinking_budget=%d as effort=%s. Set `effort` directly.",
                model, budget, effort,
            )
        create_kwargs["output_config"] = {"effort": effort}
        # Ask for the thinking back, not only for it to happen. Without this the
        # blocks arrive empty and the run page has an agent that thought for
        # thirty seconds with nothing to show for it.
        if model not in _NO_VISIBLE_THINKING:
            create_kwargs["thinking"] = dict(_VISIBLE_THINKING)
            # Sampling is the model's own business while it reasons, and the
            # API refuses any temperature but 1 once thinking is on. An agent
            # config that set 0.7 did not mean to forbid thinking.
            create_kwargs.pop("temperature", None)
        return

    # Legacy: a fixed budget is the only control, and thinking is opt-in.
    if budget is None:
        budget = _EFFORT_AS_BUDGET.get(effort or "", None)
        _warn_once(
            f"effort-on-legacy:{model}",
            "Anthropic: %s has no effort dial; reading effort=%s as %s.",
            model, effort, f"a {budget}-token thinking budget" if budget else "thinking off",
        )
    if not budget:
        return
    create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": int(budget)}
    # Extended thinking accepts no temperature but 1, and refuses the request
    # otherwise. Sampling is the model's own business while it reasons; an agent
    # config that set 0.7 did not mean to forbid thinking.
    create_kwargs.pop("temperature", None)
    # max_tokens covers thinking *and* the answer, so a budget at or above it
    # leaves nothing to reply with.
    floor = int(budget) + _ANSWER_HEADROOM
    if create_kwargs.get("max_tokens", 0) < floor:
        create_kwargs["max_tokens"] = floor


def _apply_prompt_caching(create_kwargs: dict[str, Any], ttl: str = "5m") -> None:
    """Ask Anthropic to cache this request's stable prefix, its own way.

    Request-level `cache_control` is automatic caching: the service places and
    advances the breakpoints itself as the conversation grows, which is what
    Anthropic recommends for multi-turn tool loops and what hand-placed
    breakpoints kept getting wrong (mark only the newest turn and the previous
    breakpoint vanishes from the request; mark two and you still pay a write
    premium on every boundary you guessed wrong).

    `ttl` is "5m" (write costs 1.25x) or "1h" (1.5x). A gap longer than the TTL
    between two calls of one run — a test suite, an install — expires the whole
    prefix and the next call re-writes it at full price, so a long-running agent
    is cheaper on the hour.
    """
    create_kwargs["cache_control"] = {"type": "ephemeral", "ttl": ttl}


def _is_rate_limit(exc: Exception) -> bool:
    """Whether this failure means "this subscription, not now".

    Matched on status code rather than SDK class so an overload (529) and a
    plain HTTP error from a proxy are treated the same way, and so the check
    holds if the SDK reorganises its exception types.
    """
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status in (429, 529)


def _stream_broke(exc: Exception) -> bool:
    """Whether a stream failed after it began, for a reason that is not the request's.

    The SDK retries a request whose response never began; once a stream is
    under way it retries nothing. A read that stalls or a connection that drops
    then surfaces as httpx's own error ("The read operation timed out"), and a
    server that gives out mid-answer sends an error event inside a stream that
    already began with 200 ("overloaded_error", "api_error"). Matched on the
    transport's error and the event's type rather than SDK class, as
    _is_rate_limit is.
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    body = getattr(exc, "body", None)
    kind = (body.get("error") or {}).get("type") if isinstance(body, dict) else None
    return kind in ("overloaded_error", "api_error")


def _stream_retry_delay(attempt: int) -> float:
    """The wait before sending a broken stream again: 1, 2, 4, 8, 16 and 32 s, then 60 s each.

    Each with up to a second of jitter, so calls broken by the same burst do
    not all come back at the same moment.
    """
    return min(2.0**attempt, _STREAM_RETRY_MAX_WAIT_S) + random.random()  # noqa: B311 - jitter, not security


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
    SUPPORTS_SINGLE_SEND = True
    # Every level lands: a model with an effort dial is sent it as it stands,
    # and one without is sent the matching thinking budget instead
    # (_apply_thinking_control). `xhigh` is the CLI's own step and has no API
    # equivalent, so it is not claimed here — asking for it names itself in
    # `temper check` rather than arriving as something else.
    HONOURS_EFFORT = ("low", "medium", "high", "max")

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
        temperature: float = 0.7,
        # 4096 was a 2023-era ceiling. An agent whose final answer is a plan, a
        # diff or a long tool argument hit it mid-sentence and returned nothing
        # at all, which reads as a mysterious empty response rather than a
        # truncation. Current models allow far more; an unused ceiling is free.
        max_tokens: int = 32_000,
        timeout: int = 120,
        cache_ttl: str = "5m",
        effort: str | None = None,
        thinking_budget: int | None = None,
        stream_retry_budget_s: float = DEFAULT_STREAM_RETRY_BUDGET_S,
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
        self.cache_ttl = cache_ttl
        # How hard the model thinks before answering: low | medium | high | max.
        # Unset means the model's own default, which for Opus 5 is `high` — and
        # high applies to every turn, including the ones whose whole job is to
        # read back a grep. Measured on a 36-call planning run: 149k output
        # tokens, 65% of the bill and effectively all of the 33-minute wall
        # clock, against 2 seconds of actual shell work.
        self.effort = effort
        # A hard ceiling, in tokens, on what the model may spend thinking before
        # it answers — `effort` is a dial, this is a limit. Thinking is billed as
        # output, so it is the one knob that caps that side of the bill directly.
        # None leaves the model to its own judgement.
        self.thinking_budget = thinking_budget
        # How long, in all, a call whose stream broke (an overload, an API error
        # or a stalled read once the answer began) keeps waiting to send it again
        # before it fails. Anthropic's capacity, not the account's: no cooling.
        self.stream_retry_budget_s = float(stream_retry_budget_s)
        anthropic_mod = _ensure_anthropic()
        credential, self.auth_mode = resolve_credential(api_key)
        self.api_key = credential
        self._anthropic = anthropic_mod
        self._base_url = base_url if base_url != "https://api.anthropic.com" else None
        self._clients: dict[str, Any] = {}
        self._clients_lock = threading.Lock()
        # One connection pool shared across per-call pi-login clients, holding no login.
        self._slot_http: Any = None

        # Pool pi's logins only when this provider has no fixed credential: an
        # explicitly passed one (a test's, a caller's) or an API key is the one to
        # use. Its entries are pi slot names, never logins; every slot, even a
        # single one, goes through the real picker (the private path relies on it).
        slots = pi_logins.configured_slots() if credential is None and self.auth_mode == "oauth" else []
        self._pool = TokenPool(name=POOL_NAME, tokens=slots, labels=list(slots)) if slots else None
        self._private_pool = self._pool

        self._client = self._client_for(credential) if credential else None
        logger.info(
            "Anthropic provider: auth mode %s%s",
            self.auth_mode,
            f", pi's logins: {', '.join(slots)}" if self._pool else "",
        )

    def pool_now(self) -> TokenPool | None:
        """The pi-login pool, holding the slots the pools file lists now.

        Read again on every call, so a slot taken out of the file is never
        picked or asked for again, and one put in is used, without a restart;
        a slot's coolings stay with its name. None when the provider has a
        fixed credential. A malformed list raises PiLoginsMisconfigured.
        """
        pool = self._pool
        if pool is None:
            return None
        if not hasattr(pool, "tokens"):
            return pool
        slots = pi_logins.configured_slots()
        if slots != pool.tokens:
            with self._clients_lock:
                logger.info("Anthropic: pi's logins now %s (were %s)",
                            ", ".join(slots) or "none", ", ".join(pool.tokens) or "none")
                pool.tokens, pool.labels = list(slots), list(slots)
        return pool

    def _client_for_slot(self, slot: str):
        """An SDK client carrying pi slot `slot`'s current login, for one call.

        The login comes from pi (temper_ai.llm.pi_logins.fetch), good for this
        provider's timeout plus a margin, and lives in the returned client
        only: nothing here keeps it. Real SDK clients share one HTTP connection
        pool (holding no login), so a fresh login costs no TLS handshake.
        Raises PiLoginsUnreachable or PiLoginRefused.
        """
        login = pi_logins.fetch(slot, self.timeout)
        extra: dict[str, Any] = {}
        if getattr(self._anthropic.Anthropic, "__module__", "").startswith("anthropic"):
            with self._clients_lock:
                if self._slot_http is None and hasattr(self._anthropic, "DefaultHttpxClient"):
                    self._slot_http = self._anthropic.DefaultHttpxClient(timeout=self.timeout)
                if self._slot_http is not None:
                    extra["http_client"] = self._slot_http
        # Bearer, not x-api-key: the SDK's own way of carrying OAuth.
        return self._anthropic.Anthropic(
            base_url=self._base_url, timeout=self.timeout, auth_token=login, api_key=None, **extra)

    def _client_for(self, credential: str):
        """The SDK client for one fixed credential (an API key, or a token handed
        in), created once and reused.

        One client per credential rather than one per call: the SDK holds an HTTP
        connection pool, and rebuilding it for every request of a 60-iteration
        run costs a TLS handshake each time. Pi's logins never come here: they
        change, and go through _client_for_slot.
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

    # -- named tokens (see BaseLLM) -----------------------------------------

    def names_slot(self, name: str) -> bool:
        """Whether `token: <name>` names one of pi's slots this provider uses now."""
        pool = self.pool_now()
        if pool is None:
            return False
        slots = pool.tokens if hasattr(pool, "tokens") else pi_logins.configured_slots()
        return name in slots

    def _pinned_slot(self, name: str) -> tuple[TokenPool, str]:
        pool = self.pool_now()
        if pool is None:
            raise ValueError(f"no Anthropic token is called {name!r}: this provider is not using "
                             f"pooled subscriptions (auth mode {self.auth_mode})")
        slots = pool.tokens if hasattr(pool, "tokens") else pi_logins.configured_slots()
        if name not in slots:
            raise ValueError(f"no Anthropic token is called {name!r}; pi's slots are "
                             f"{', '.join(slots) or 'none'}")
        return pool, name

    def check_token(self, name: str) -> None:
        self._pinned_slot(name)

    def token_cooling_until(self, name: str, model: str | None = None) -> float | None:
        if not self.names_slot(name):
            return None
        return self._pool.cooling_until(name, model) if self._pool is not None else None

    def _call_pinned(self, name: str, run, model: str | None, *, single_send: bool = False) -> Any:
        """Run `run(client)` on the one slot the call names, with no rotation.

        The call asked for this account, so a limit on it is not retried on
        another: it is raised as TokenCooling -- a capacity failure -- and the
        agent's fallback list decides where to go next. The slot is still
        cooled in the pool, so the calls that do rotate stop landing on it, and
        a slot already known to be cooling is refused without a request. A
        login pi refuses cools the slot the same way.
        """
        pool, slot = self._pinned_slot(name)
        until = pool.cooling_until(slot, model)
        if until:
            raise TokenCooling(slot, model, until)
        try:
            client = self._client_for_slot(slot)
        except pi_logins.PiLoginRefused as exc:
            reset = pool.cool(slot, reason="pi refused its login")
            raise TokenCooling(slot, model, reset, detail=exc.why[:200]) from None
        try:
            return run(client)
        except Exception as exc:  # noqa: BLE001 - re-raised below unless it is a limit
            if not _is_rate_limit(exc):
                raise
            reset = pool.cool(slot, until=_reset_epoch(exc), model=model)
            detail = type(exc).__name__ if single_send else str(exc)[:200]
            raise TokenCooling(slot, model, reset, detail=detail) from exc

    def _send(self, create_kwargs: dict[str, Any], kwargs: dict[str, Any], run) -> Any:
        """One request, surviving a subscription limit and a rejected knob.

        Newer models refuse `temperature` outright (400, not a warning), which
        killed the request rather than the parameter. The first refusal per
        model teaches the process to stop sending it. Asking to see the thinking
        is treated the same way: a model that refuses the `thinking` parameter
        still answers without it, and losing the answer to keep the knob would
        be the worse trade.
        """
        try:
            return self._call_with_pool(kwargs, run, model=create_kwargs.get("model"))
        except Exception as exc:  # noqa: BLE001 - narrowed immediately
            model = create_kwargs.get("model", "")
            if "thinking" in create_kwargs and _thinking_rejected(exc):
                with _no_temperature_lock:
                    first = model not in _NO_VISIBLE_THINKING
                    _NO_VISIBLE_THINKING.add(model)
                if first:
                    logger.warning(
                        "Anthropic: %s refuses the thinking parameter (%s); asking for "
                        "effort alone from here on \u2014 its thinking will not be readable",
                        model, str(exc)[:160],
                    )
                create_kwargs.pop("thinking")
                return self._call_with_pool(kwargs, run, model=model)
            if "temperature" not in create_kwargs or not _temperature_rejected(exc):
                raise
            with _no_temperature_lock:
                first = model not in _NO_TEMPERATURE
                _NO_TEMPERATURE.add(model)
            if first:
                logger.warning("Anthropic: %s rejects temperature; dropping it for this model", model)
            create_kwargs.pop("temperature")
            return self._call_with_pool(kwargs, run, model=model)

    def _call_with_pool(self, kwargs: dict[str, Any], run, model: str | None = None) -> Any:
        """Run `run(client)`, moving to another subscription on a rate limit.

        Attempts are bounded by the pool size: each 429 cools exactly one
        token, so at worst every subscription is tried once and the pool then
        reports itself exhausted instead of spinning.

        The model travels with the call so a refusal cools the credential only for
        the ceiling it actually hit; the subscription's weekly allowance is per
        model family, and cooling all of them stops work that had quota left.

        A call that names its token goes out on that one only (_call_pinned).
        Each attempt asks pi for its slot's login; a slot whose login pi
        refuses is cooled for a while and the call goes on another, and when
        pi refused every slot the call fails with pi's words. When the helper
        can't be reached the call fails at once (PiLoginsUnreachable).
        """
        if kwargs.get("token"):
            return self._call_pinned(kwargs["token"], run, model)
        pool = self.pool_now()
        if pool is None:
            if self.api_key is None:
                raise RuntimeError("Anthropic provider has no credential configured")
            return run(self._client_for(self.api_key))
        if not pool.tokens:
            raise RuntimeError(f"Anthropic provider: {_NO_SLOT}")
        last_error: Exception | None = None
        refused: dict[str, str] = {}
        for _ in range(len(pool)):
            slot = pool.pick(sticky_key_from_kwargs(kwargs), model=model)
            try:
                client = self._client_for_slot(slot)
            except pi_logins.PiLoginRefused as exc:
                pool.cool(slot, reason="pi refused its login")
                refused[slot] = exc.why
                last_error = exc
                continue
            try:
                return run(client)
            except Exception as exc:  # noqa: BLE001 - re-raised below unless it is a limit
                if not _is_rate_limit(exc):
                    raise
                pool.cool(slot, until=_reset_epoch(exc), model=model)
                last_error = exc
        if refused and set(refused) == set(pool.tokens):
            raise RuntimeError("Anthropic provider: pi refused every Claude login temper may use: "
                               + "; ".join(refused.values())) from None
        raise PoolExhausted(len(pool), pool.soonest_reset(model)) from last_error

    def _build_create_kwargs(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        """The ``messages.create`` payload, shaped for the credential in use."""
        system, claude_messages = _extract_system(messages)

        model = self.resolve_model(kwargs)
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            # Per call, so one agent can be given more room than the shared
            # provider default (agent YAML: provider_config.max_tokens).
            "max_tokens": kwargs.get("max_tokens") or self.max_tokens,
        }
        if model not in _NO_TEMPERATURE:
            create_kwargs["temperature"] = self.temperature

        _apply_thinking_control(
            create_kwargs, model,
            effort=kwargs.get("effort") or self.effort,
            budget=kwargs.get("thinking_budget") or self.thinking_budget,
        )
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
        _apply_prompt_caching(create_kwargs, ttl=kwargs.get("cache_ttl") or self.cache_ttl)
        return create_kwargs

    def complete(self, messages: list[dict], *, single_send: bool = False, **kwargs: Any) -> LLMResponse:
        """Call Claude; opt-in single_send never reaches learned/retry paths."""
        if single_send:
            return self._complete_single_send(messages, **kwargs)
        create_kwargs = self._build_create_kwargs(messages, **kwargs)
        # Timed here rather than left at None: with thinking billed as output,
        # per-call latency is the visible half of what a thinking budget buys,
        # and the event log had nothing to show for it.
        started = time.monotonic()
        response = self._send(create_kwargs, kwargs, lambda client: client.messages.create(**create_kwargs))
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return _parse_response(response, create_kwargs["model"], elapsed_ms)

    def stream(self, messages: list[dict], on_chunk: StreamCallback | None = None,
               *, single_send: bool = False, **kwargs: Any) -> LLMResponse:
        """Stream Claude response."""
        if single_send:
            from temper_ai.llm.single_send import SingleSendError
            if on_chunk is not None:
                raise SingleSendError("strict_parser")
            return self._complete_single_send(messages, **kwargs)
        create_kwargs = self._build_create_kwargs(messages, **kwargs)

        content_parts: list[str] = []

        def run(client):
            with client.messages.stream(**create_kwargs) as stream:
                # The whole event stream rather than `stream.text_stream`: that
                # helper yields the answer only, so thinking arrived nowhere and
                # the live panel had nothing to show while the model reasoned.
                # Thinking goes out as its own kind of chunk, so the page can
                # keep it apart from the answer.
                for event in stream:
                    if getattr(event, "type", None) != "content_block_delta":
                        continue
                    delta = getattr(event, "delta", None)
                    kind = getattr(delta, "type", None)
                    if kind == "text_delta":
                        text = getattr(delta, "text", "") or ""
                        if not text:
                            continue
                        content_parts.append(text)
                        if on_chunk:
                            on_chunk(LLMStreamChunk(content=text, done=False))
                    elif kind == "thinking_delta":
                        text = getattr(delta, "thinking", "") or ""
                        if text and on_chunk:
                            on_chunk(LLMStreamChunk(content=text, done=False,
                                                    chunk_type="thinking"))
                return stream.get_final_message()

        # A rate limit surfaces on entering the stream, before any chunk; if it
        # ever arrives mid-stream the partial text is dropped and the retry
        # starts clean rather than emitting the same prefix twice. A stream that
        # breaks later is sent again whole (_send_stream): the answer is the new
        # stream's, though on_chunk has already seen the broken one's first text.
        started = time.monotonic()
        final = self._send_stream(create_kwargs, kwargs, run)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        if on_chunk:
            on_chunk(LLMStreamChunk(content="", done=True))

        return _parse_response(final, create_kwargs["model"], elapsed_ms)

    def _build_single_send_kwargs(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        """Fixed, uncached parameters; NEVER consult learned parameter sets/defaults."""
        from temper_ai.llm.single_send import SingleSendError
        system, converted = _extract_system(messages)
        if not kwargs.get("model") or type(kwargs.get("max_tokens")) is not int:
            raise SingleSendError("strict_parser")
        body: dict[str, Any] = {"model": kwargs["model"], "max_tokens": kwargs["max_tokens"],
                                "messages": converted}
        if system:
            body["system"] = system
        if "temperature" in kwargs:
            body["temperature"] = kwargs["temperature"]
        if "thinking" in kwargs:
            body["thinking"] = kwargs["thinking"]
        if "thinking_budget" in kwargs:
            body["thinking"] = {"type": "enabled", "budget_tokens": kwargs["thinking_budget"]}
        if "effort" in kwargs:
            body["output_config"] = {"effort": kwargs["effort"]}
        shaper = get_oauth_shaper()
        if shaper is not None:
            body = shaper.shape(body)
            body["extra_headers"] = {**shaper.client_headers(), **(body.get("extra_headers") or {})}
        else:
            _warn_unshaped_once()
        # Cache writes would need separate pinned prices. Remove every breakpoint,
        # including shaper-added ones, and NEVER add request-level caching.
        def uncached(value: Any) -> None:
            if isinstance(value, dict):
                value.pop("cache_control", None)
                for child in value.values():
                    uncached(child)
            elif isinstance(value, list):
                for child in value:
                    uncached(child)
        uncached(body)
        return body

    def _complete_single_send(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        from temper_ai.llm import single_send as ss
        response = LLMResponse(content=None, model=str(kwargs.get("model", "")), provider="anthropic")
        failure = None
        with ss.metadata_only_logs():
            control = ss.strict_control(kwargs)
            try:
                token = kwargs.get("token")
                if self.auth_mode != "oauth" or not isinstance(token, str) or not token or not self.names_slot(token):
                    raise ss.SingleSendError("auth")
                self.check_token(token)
                body = self._build_single_send_kwargs(messages, **kwargs)
                from temper_ai.llm.native_attempt import (
                    NativeObservation,
                    send_native_once,
                )

                def run(shared: Any) -> LLMResponse:
                    return send_native_once(shared, body, control, response, NativeObservation(),
                                            _single_send_usage_never_raises)

                response = self._call_pinned(token, run, body["model"], single_send=True)
            except Exception as exc:  # noqa: BLE001 - copy only safe facts, erase prose/chain
                failure = ss.safe_failure(exc, response)
            finally:
                control.finish()
            if control.failure_reason:
                failure = ss.SingleSendError(control.failure_reason, response=response)
            if control.cleanup_uncertain:
                failure = ss.SingleSendError("timeout", response=response)
            # Outside the except handler: no retained TokenCooling __context__.
            if failure is not None:
                raise failure
            return response

    def _send_stream(self, create_kwargs: dict[str, Any], kwargs: dict[str, Any], run) -> Any:
        """`_send`, sent again whole when the stream broke after it began.

        One stalled read or one "Overloaded" event failed the call and the
        agent with it, often hours into a round at high effort: 5 of 15,164
        calls in 60 hours, each ending its agent. The request changes nothing by
        itself, so it goes out again. Not on the base class's three attempts
        (1 s, then 2 s): an overload burst outlasts them, and one ended an
        architect 30 minutes and $8 in. It waits longer each time
        (_stream_retry_delay) until `stream_retry_budget_s` of waiting in all,
        then fails as before. Each retry is recorded (the retry event).
        Anything that is not a broken stream is raised at once.
        """
        budget = kwargs.get("stream_retry_budget_s")  # an agent's provider_config wins
        budget = self.stream_retry_budget_s if budget is None else float(budget)
        attempt = 0
        waited = 0.0
        while True:
            try:
                return self._send(create_kwargs, kwargs, run)
            except Exception as exc:  # noqa: BLE001 - re-raised below unless the stream broke
                left = budget - waited
                if left <= 0 or not _stream_broke(exc):
                    raise
                delay = min(_stream_retry_delay(attempt), left)
                self._record_retry(exc, attempt, delay, extra={
                    "max_retries": None,
                    "retry_budget_s": budget,
                    "waited_s": round(waited, 1),
                })
                time.sleep(delay)
                waited += delay
                attempt += 1

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


def _parse_response(response: Any, model: str, latency_ms: int | None = None) -> LLMResponse:
    """Parse Anthropic response to standard LLMResponse."""
    content_text = ""
    thinking_parts: list[str] = []
    tool_calls = []

    for block in response.content:
        if block.type == "text":
            content_text += block.text
        # Thinking is a block of its own, never part of the answer, and it is
        # kept that way all the way to the page: read back into `reasoning`, it
        # is shown as thinking rather than mixed into what the agent said.
        # Both paths land here, so a run records the same thing whether it was
        # streamed or not. `redacted_thinking` carries no readable text.
        elif block.type == "thinking":
            text = getattr(block, "thinking", "") or ""
            if text:
                thinking_parts.append(text)
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
        cached_prompt_tokens=cache_read,
        cache_write_tokens=cache_write,
        latency_ms=latency_ms,
        finish_reason="tool_calls" if tool_calls else response.stop_reason or "stop",
        tool_calls=tool_calls if tool_calls else None,
        reasoning="\n\n".join(thinking_parts) or None,
    )


# Single-send usage (#221). Usage describes the answer; it never decides
# whether the answer is kept. Anthropic adds usage fields over time (the pinned
# SDK's MessageDeltaUsage models five), and one such field cost a whole
# single-send answer (#194, attempt 3).
_SINGLE_SEND_COUNTERS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
# Every message reports these two, so a null one is a shape we cannot read.
# The cache counters may be null: not reported.
_REQUIRED_COUNTERS = ("input_tokens", "output_tokens")
# Unmodelled fields are kept with their values up to this size; past it, or
# when not storable JSON, only how many arrived where.
_UNMODELLED_RECORD_BYTES = 4096
# A string value of an unmodelled field is kept up to this length; past it, only
# its type and length (a service tier or a region fits, free text does not).
_UNMODELLED_TEXT_CHARS = 64


def _single_send_usage_never_raises(start: Any, deltas: list[Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The usage of one single-send answer, and what was wrong with it. Never raises.

    `start` is message_start's usage; `deltas` holds each message_delta's.
    The usage always has the five single-send counters, and one we do not have
    is None, never 0. The fault is None for a clean read, otherwise a
    content-free record with a reason: "unmodelled" (fields the pinned SDK does
    not model: the counters are still read and the fields are recorded),
    "unreadable" (a usage object or counter we cannot read: every counter is
    None and `unreadable` names what) or "absent" (no usage at all: every
    counter is None). A failure of this reader itself is an unreadable usage
    too, never a lost answer.
    """
    from temper_ai.llm.single_send import USAGE_COUNTERS
    try:
        return _read_single_send_usage(start, deltas)
    except Exception:  # noqa: BLE001 - accounting must never cost the answer
        return {key: None for key in USAGE_COUNTERS}, {"reason": "unreadable", "unreadable": ["reader"]}


def _read_single_send_usage(start: Any, deltas: list[Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from pydantic import BaseModel

    from temper_ai.llm import single_send as ss
    usage = {key: None for key in ss.USAGE_COUNTERS}
    if start is None and all(delta is None for delta in deltas):
        return usage, {"reason": "absent"}
    unreadable: list[str] = [] if deltas else ["message_delta.usage"]
    unmodelled: dict[str, dict[str, Any]] = {}
    for where, value in [("message_start.usage", start), *(("message_delta.usage", delta) for delta in deltas)]:
        if not isinstance(value, BaseModel):
            if where not in unreadable:  # missing on one side, or not an object: nothing to merge
                unreadable.append(where)
        elif value.model_extra:
            unmodelled.setdefault(where, {}).update(value.model_extra)
    if not unreadable:
        # The pinned SDK's own merge (anthropic/lib/streaming/_messages.py,
        # accumulate_event), so an ordinary usage reads exactly as it always did.
        merged = {key: getattr(start, key, None) for key in _SINGLE_SEND_COUNTERS}
        for delta in deltas:
            merged["output_tokens"] = getattr(delta, "output_tokens", None)
            for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                if getattr(delta, key, None) is not None:
                    merged[key] = getattr(delta, key)
        unreadable = [key for key, count in merged.items()
                      if (count is None and key in _REQUIRED_COUNTERS) or (count is not None and ss.counter(count) is None)]
        if not unreadable:
            usage = ss.reported_usage({**merged, "total_tokens": None})
    fault: dict[str, Any] | None = {"reason": "unreadable", "unreadable": unreadable} if unreadable else None
    if unmodelled:
        fault = fault or {"reason": "unmodelled"}
        fault.update(_unmodelled_record(unmodelled))
    return usage, fault


def _unmodelled_record(unmodelled: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Unmodelled usage fields, each value as _unmodelled_value records it; only counts when too large or not storable JSON."""
    kept = {where: {field: _unmodelled_value(value) for field, value in fields.items()}
            for where, fields in unmodelled.items()}
    try:
        size = len(json.dumps(kept, allow_nan=False).encode())
    except (TypeError, ValueError):  # not JSON at all, or NaN: still never a reason to lose the counters
        size = None
    if size is not None and size <= _UNMODELLED_RECORD_BYTES:
        return {"unmodelled": kept}
    return {"unmodelled_count": {where: len(fields) for where, fields in unmodelled.items()}}


def _unmodelled_value(value: Any) -> Any:
    """How one unmodelled usage field's value is recorded.

    By definition we do not know what such a field holds, so its value is kept
    only when it is null, a boolean, a number or a string of at most
    _UNMODELLED_TEXT_CHARS characters. An object, an array or a longer string
    is recorded as its JSON type and length alone. JSON-parsed usage holds
    nothing else; anything that is not JSON fails the record's own check.
    """
    if isinstance(value, str) and len(value) <= _UNMODELLED_TEXT_CHARS:
        return value
    for kind, name in ((dict, "object"), (list, "array"), (str, "string")):
        if isinstance(value, kind):
            return {"type": name, "length": len(value)}
    return value
