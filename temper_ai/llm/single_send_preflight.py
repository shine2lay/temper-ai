"""single_call preflight: the exact request shape of one A or B send, never sent.

preflight(config) runs the send's own credential-free checks, builds the body
with the send's own builder (anthropic_single_send_body / codex_single_send_body),
serializes it with the same library call the send makes, and stops in the
request hook before any transport. It reads the pinned prompt and pricing
files, and nothing else: no credential, no named-token store, no provider
object, no claim, no output root, no write. See docs/single-call.md, "Preflight".

    python -m temper_ai.llm.single_send_preflight CONFIG.json
    exit 0 PREFLIGHT_OK, 3 REFUSED, 2 usage error, 1 unexpected failure (no JSON)
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

import httpx

from temper_ai.llm import single_send as ss

SCHEMA = "single-call-preflight/v1"
#: Placeholder credential for the SDK constructor only. Public, fixed, never a
#: secret; the request hook stops the call before any transport.
PLACEHOLDER_CREDENTIAL = "temper-preflight-placeholder-not-a-credential"  # noqa: S105
#: The SDK's own default, passed explicitly so ANTHROPIC_BASE_URL is never read.
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
#: The endpoint is the default one, not the loaded provider's (that is checked at admission).
ENDPOINT_BASIS = "default_not_loaded"
#: What a PREFLIGHT_OK does not establish; the send still checks each of these.
NOT_CHECKED = ("credential", "loaded_route", "quota_policy", "cost_cap", "claim_slot", "deadline")

#: The send's fields the preflight needs. Every other send field is optional here.
PREFLIGHT_REQUIRED = frozenset({
    "prompt_path", "prompt_sha256", "prompt_bytes", "slot", "family", "route", "auth_mode",
    "max_tokens", "output_bound_mode", "pricing_path", "pricing_sha256",
})
#: Send-only fields: format-checked as the send checks them when present, never opened or used.
SEND_ONLY = frozenset({
    "output_root", "deadline_s", "cost_cap_usd", "experiment_id", "binding_id",
    "source_sha256", "config_sha256", "packet_sha256",
})
REFUSALS = ("prompt_mismatch", "pricing_mismatch", "unknown_slot", "route_mismatch",
            "unsupported_parameter", "bound_unestablished", "shaper_missing", "strict_parser")
_TEXT_KEYS = frozenset({"messages", "system", "instructions", "input"})
#: Request headers reported as versions: never Authorization or account ids.
_VERSION_HEADERS = {"A": ("anthropic-version", "anthropic-beta", "user-agent"),
                    "B": ("originator", "openai-beta")}
UNKNOWN = "UNKNOWN"


class Refused(Exception):
    """A refusal: the named reason, and the reason the send records for it (None: the send doesn't refuse)."""

    def __init__(self, named: str, send_refusal: str | None) -> None:
        super().__init__(named)
        self.named = named
        self.send_refusal = send_refusal


class PreflightCrashed(Exception):
    """An unexpected failure: no refusal applies. Carries no input or library text."""

    def __init__(self) -> None:
        super().__init__("single_send preflight stopped: unexpected failure, no detail kept")


class _Captured(Exception):
    """Raised from the request hook: the body is captured and nothing is sent."""


class _StopAfterCapture:
    """The request hook: keeps the built request, then stops the call before any transport."""

    def __init__(self) -> None:
        self.captured: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> None:
        self.captured.append(request)
        raise _Captured


class _RefusingTransport(httpx.BaseTransport):
    """Never sends. Reaching it means the request hook did not stop the call."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise RuntimeError("single_send preflight never sends")


def _empty() -> dict[str, Any]:
    return {"schema": SCHEMA, "terminal": "REFUSED", "refusal": None, "send_refusal": None,
            "authorizes_send": False, "not_checked": list(NOT_CHECKED),
            "slot": None, "family": None, "provider_class": None, "route": None, "endpoint": None,
            "endpoint_basis": None, "model": None, "pins": None, "versions": None, "request": None,
            "prompt_part": None, "parameters_sent": None, "output_bound": None, "overhead": None,
            "body_facts": None, "reservation_usd": None}


def _named(exc: BaseException, default: str) -> str:
    named = getattr(exc, "named", None)
    return named if named in REFUSALS else default


def _stage(default: str, step: Callable[..., Any], *args: Any,
           faults: tuple[type[Exception], ...] = ()) -> Any:
    """Run one shared check. Its refusal keeps the send's own reason (safe_failure, as the send records it)."""
    caught: tuple[type[Exception], ...] = (ss.SingleSendError, *faults)
    try:
        return step(*args)
    except caught as exc:
        raise Refused(_named(exc, default), ss.safe_failure(exc).reason) from None


def _includes_reasoning(price: dict) -> str:
    """Pinned with an https source, or UNKNOWN; never a bool or null."""
    from temper_ai.agent.single_call_agent import https_source
    value = price.get("output_bound_includes_reasoning")
    if type(value) is bool and https_source(price.get("output_bound_includes_reasoning_source")):
        return "INCLUDED" if value else "NOT_INCLUDED"
    return UNKNOWN


def _serialize_a(body: dict) -> httpx.Request:
    """The send's messages.stream(**body), stopped in the request hook."""
    import anthropic
    hook = _StopAfterCapture()
    # No environment: no proxies, no certificate settings; the hook stops before the transport anyway.
    owned = httpx.Client(transport=_RefusingTransport(), trust_env=False, event_hooks={"request": [hook]})
    try:
        # Base URL and both credentials given: None would make the SDK read
        # ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN.
        client = anthropic.Anthropic(base_url=ANTHROPIC_DEFAULT_BASE_URL, auth_token=PLACEHOLDER_CREDENTIAL,
                                     api_key=PLACEHOLDER_CREDENTIAL, max_retries=0, http_client=owned)
        stopped = False
        try:
            client.messages.stream(**body).__enter__()
        except anthropic.APIConnectionError as exc:  # the SDK wraps the hook's stop
            stopped = isinstance(exc.__cause__, _Captured)
    finally:
        owned.close()
    if not stopped or len(hook.captured) != 1:
        raise RuntimeError("single_send preflight: the request hook did not stop exactly one request")
    return hook.captured[0]


def _serialize_b(body: dict) -> httpx.Request:
    """The send's client.stream("POST", url, json=body) request, built and not sent."""
    from temper_ai.llm.providers.openai_codex import (
        DEFAULT_CODEX_BASE_URL,
        codex_credential_free_headers,
        codex_url,
    )
    with httpx.Client(transport=_RefusingTransport(), trust_env=False) as client:
        return client.build_request("POST", codex_url(DEFAULT_CODEX_BASE_URL),
                                    headers=codex_credential_free_headers(), json=body)


def _count_cache_markers(value: Any) -> int:
    if isinstance(value, dict):
        return ("cache_control" in value) + sum(_count_cache_markers(v) for v in value.values())
    if isinstance(value, list):
        return sum(_count_cache_markers(v) for v in value)
    return 0


def _build(config: Any) -> dict[str, Any]:
    from temper_ai.agent import single_call_agent as agent
    if not isinstance(config, dict) or not isinstance(config.get("single_call"), dict):
        raise Refused("strict_parser", "strict_parser")
    fixed = config["single_call"]
    # The send's order: claim_slot's checks (nothing opened here), then validate's.
    _stage("unknown_slot", agent.check_claim_fields, fixed)
    _stage("strict_parser", agent.check_fixed_fields, config, fixed, PREFLIGHT_REQUIRED)
    a = _stage("route_mismatch", agent.check_fixed_call, config, fixed, fixed["slot"])
    family = "A" if a else "B"
    file_faults = (OSError, TypeError, ValueError)
    prompt = _stage("prompt_mismatch", agent.read_fixed_prompt, fixed, faults=file_faults)
    pricing = _stage("pricing_mismatch", lambda: agent.parse_fixed_pricing(config, agent.read_fixed_pricing(fixed)),
                     faults=(*file_faults, KeyError))
    evidence = _stage("bound_unestablished", agent.fixed_bound_evidence, config, pricing, a)
    output_bound = _stage("bound_unestablished", agent.fixed_output_bound, config, fixed, pricing, a)
    # A's token NAME is only shape-checked (check_fixed_call) and never resolved;
    # the shared builder copies only body keys, as on the send.
    kwargs = _stage("unsupported_parameter", agent.fixed_optional_parameters, fixed)
    text = _stage("prompt_mismatch", prompt.decode, "utf-8", faults=(UnicodeDecodeError,))
    messages = [{"role": "user", "content": text}]
    send_kwargs = {"model": config["model"], "max_tokens": fixed["max_tokens"],
                   "output_bound_mode": fixed["output_bound_mode"], **kwargs}
    if a:
        from temper_ai.llm.providers.anthropic import (
            anthropic_single_send_body,
            get_oauth_shaper,
        )
        body = _stage("strict_parser", lambda: anthropic_single_send_body(messages, **send_kwargs))
        request = _serialize_a(body)
        provider_class = "temper_ai.llm.providers.anthropic.AnthropicLLM"
    else:
        from temper_ai.llm.providers.openai_codex import codex_single_send_body
        body = _stage("strict_parser", lambda: codex_single_send_body(messages, **send_kwargs))
        request = _serialize_b(body)
        provider_class = "temper_ai.llm.providers.openai.OpenAILLM+openai_codex.CodexTransport"
    raw = request.content
    metadata = _stage("strict_parser", ss.request_metadata, raw)
    reservation = _stage("strict_parser", agent.check_final_body, config, fixed, metadata, pricing, output_bound)
    prompts = [part for part in metadata["input_parts"] if part["kind"] == "prompt"]
    if len(prompts) != 1 or prompts[0]["sha256"] != fixed["prompt_sha256"]:
        # Preflight-only: reachable only through a shaper that rewrites the user message.
        raise Refused("prompt_mismatch", None)
    parsed = json.loads(raw)
    text_bytes = sum(part["bytes"] for part in metadata["input_parts"])
    system_bytes = sum(part["bytes"] for part in metadata["input_parts"] if part["kind"] in ("system", "instructions"))
    versions: dict[str, Any] = {"httpx": httpx.__version__}
    if a:
        import anthropic
        shaper = get_oauth_shaper()
        versions["anthropic_sdk"] = anthropic.__version__
        versions["oauth_shaper"] = f"{type(shaper).__module__}.{type(shaper).__qualname__}"
    for name in _VERSION_HEADERS[family]:
        versions[name] = request.headers.get(name)
    out = _empty()
    out.update({
        "terminal": "PREFLIGHT_OK", "slot": fixed["slot"], "family": family, "provider_class": provider_class,
        "route": fixed["route"], "endpoint": f"{request.method} {request.url}", "endpoint_basis": ENDPOINT_BASIS,
        "model": config["model"],
        "pins": {"prompt_sha256": fixed["prompt_sha256"], "prompt_bytes": fixed["prompt_bytes"],
                 "pricing_sha256": fixed["pricing_sha256"]},
        "versions": versions, "request": metadata,
        "prompt_part": {"bytes": prompts[0]["bytes"], "sha256": prompts[0]["sha256"]},
        "parameters_sent": {k: v for k, v in parsed.items() if k not in _TEXT_KEYS},
        "output_bound": {"mode": fixed["output_bound_mode"], "tokens": output_bound,
                         "sent_as": "max_tokens" if "max_tokens" in parsed else "none",
                         "includes_reasoning": _includes_reasoning(pricing["models"][config["model"]]),
                         "evidence_sha256": evidence},
        "overhead": {"system_or_instructions_bytes": system_bytes, "framing_bytes": len(raw) - text_bytes},
        "body_facts": {"cache_control_markers": _count_cache_markers(parsed),
                       "max_output_tokens_present": "max_output_tokens" in parsed},
        "reservation_usd": str(reservation),
    })
    return out


def preflight(config: Any) -> dict[str, Any]:
    """single-call-preflight/v1 for one agent config. Never sends, writes or reads a credential.

    Raises PreflightCrashed (no detail, no chained exception) on an unexpected failure.
    """
    from temper_ai.agent.single_call_agent import _SLOTS
    crashed = False
    with ss.metadata_only_logs():
        try:
            return _build(config)
        except Refused as exc:
            refusal = exc
        except Exception:  # noqa: BLE001 - library prose may hold input text; keep none of it
            crashed = True
    if crashed:
        raise PreflightCrashed  # raised outside the handler: nothing chained
    out = _empty()
    out["refusal"], out["send_refusal"] = refusal.named, refusal.send_refusal
    fixed = config.get("single_call") if isinstance(config, dict) else None
    slot = fixed.get("slot") if isinstance(fixed, dict) else None
    out["slot"] = slot if isinstance(slot, str) and slot in _SLOTS else None
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m temper_ai.llm.single_send_preflight CONFIG.json", file=sys.stderr)
        return 2
    try:
        with open(args[0], "rb") as handle:
            config = json.loads(handle.read())
    except (OSError, ValueError):
        print("single_send_preflight: config unreadable or not JSON", file=sys.stderr)
        return 2
    try:
        # As server and boxes do: the provider factory registers local providers
        # and the OAuth shaper the A send applies.
        import temper_ai.llm.providers.factory  # noqa: F401
        out = preflight(config)
    except Exception:  # noqa: BLE001 - no JSON and no detail on an unexpected failure
        print("single_send_preflight: unexpected failure, no detail kept", file=sys.stderr)
        return 1
    print(json.dumps(out, sort_keys=True))
    return 0 if out["terminal"] == "PREFLIGHT_OK" else 3


if __name__ == "__main__":
    raise SystemExit(main())
