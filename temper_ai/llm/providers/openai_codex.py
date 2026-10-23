"""The transport behind an OpenAI OAuth token: the Codex Responses endpoint.

A ChatGPT Plus/Pro subscription's OAuth token does not work against
``api.openai.com/v1/chat/completions``. It works against OpenAI's Codex
backend, ``https://chatgpt.com/backend-api/codex/responses``, which speaks
the *Responses* API — a different request body (``instructions`` +
``input`` items), a different tool shape, and a stream of typed SSE events
instead of ``chat.completion.chunk``. So "use the OAuth token" is not a
header change on the existing provider; it is a second wire protocol, and
this module is that protocol.

Identity is honest. The token is sent as a bearer, the account id comes
from a claim inside the token itself, and ``originator`` says ``temper``.
Nothing here pretends to be another client.

Every field below was checked against the live endpoint with a probe
before the parser was written, not taken from documentation:

  response.output_item.added      item.type ∈ {message, function_call};
                                  function_call carries call_id, name, arguments=""
  response.output_text.delta      delta, item_id
  response.function_call_arguments.delta / .done
                                  item_id; .done carries the full arguments
  response.output_item.done       the finished item (function_call → full arguments)
  response.completed              response.usage.{input,output,total}_tokens;
                                  response.output is [] here — assemble from events
  response.failed / error         raise

Token lifetime: the access token is a JWT; ``exp`` is read from it and a
warning is logged inside 24 hours of expiry. Refresh is pi's job today
(``/login openai`` in pi refreshes and stores it); ``local/sync-openai-oauth-token.sh``
copies the current one into ``.env`` for the container.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

import httpx

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import StreamCallback

logger = logging.getLogger(__name__)

DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api"
CODEX_BASE_URL_ENV = "OPENAI_CODEX_BASE_URL"
JWT_CLAIM_PATH = "https://api.openai.com/auth"
ORIGINATOR = "temper"
# The cheapest model the Codex backend lists (pi's registry: $0.20/M in,
# $1.20/M out — 4x under the next one). Override per agent or with OPENAI_MODEL.
DEFAULT_CODEX_MODEL = "gpt-5.6-luna"
EXPIRY_WARNING_S = 24 * 3600


def _jwt_payload(token: str) -> dict[str, Any]:
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("OpenAI OAuth token is not a decodable JWT") from exc


def account_id_from_token(token: str) -> str:
    """The ChatGPT account the token belongs to — required as a header."""
    claim = _jwt_payload(token).get(JWT_CLAIM_PATH) or {}
    account = claim.get("chatgpt_account_id")
    if not isinstance(account, str) or not account:
        raise ValueError("OpenAI OAuth token carries no chatgpt_account_id claim")
    return account


def token_expiry(token: str) -> float | None:
    exp = _jwt_payload(token).get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None


def codex_url(base_url: str | None = None) -> str:
    base = (base_url or os.environ.get(CODEX_BASE_URL_ENV) or DEFAULT_CODEX_BASE_URL).rstrip("/")
    if base.endswith("/codex/responses"):
        return base
    if base.endswith("/codex"):
        return base + "/responses"
    return base + "/codex/responses"


# --------------------------------------------------------------------------
# Chat-Completions-shaped messages/tools  →  Responses-shaped body
# --------------------------------------------------------------------------


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    return "" if content is None else str(content)


def to_responses_input(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    """Split the system prompt out as ``instructions``; convert the rest.

    user → message/input_text · assistant text → message/output_text ·
    assistant tool_calls → function_call items · tool → function_call_output.
    Tool call ids are carried through as ``call_id`` so a result the service
    injects later still pairs with the call the model made.
    """
    instructions: str | None = None
    items: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            instructions = _text_of(content) or instructions
            continue
        if role == "user":
            items.append({"type": "message", "role": "user",
                          "content": [{"type": "input_text", "text": _text_of(content)}]})
            continue
        if role == "assistant":
            text = _text_of(content)
            if text:
                items.append({"type": "message", "role": "assistant",
                              "content": [{"type": "output_text", "text": text}]})
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments", tc.get("arguments", {}))
                if not isinstance(args, str):
                    args = json.dumps(args)
                items.append({"type": "function_call",
                              "call_id": str(tc.get("id", "")),
                              "name": fn.get("name") or tc.get("name", ""),
                              "arguments": args})
            continue
        if role == "tool":
            items.append({"type": "function_call_output",
                          "call_id": str(msg.get("tool_call_id", "")),
                          "output": _text_of(content)})
    return instructions, items


def to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chat Completions' nested ``{type, function:{…}}`` → Responses' flat shape."""
    out = []
    for tool in tools:
        fn = tool.get("function", tool)
        out.append({
            "type": "function",
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def codex_request_body(messages: list[dict[str, Any]], model: str,
                       tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The Responses body every Codex call sends (shared with the single_send preflight)."""
    instructions, items = to_responses_input(messages)
    body: dict[str, Any] = {
        "model": model,
        "store": False,
        "stream": True,
        "instructions": instructions or "You are a helpful assistant.",
        "input": items,
        "text": {"verbosity": "low"},
        "tool_choice": "auto",
        "parallel_tool_calls": True,
    }
    # No temperature. The Codex endpoint answers 400 "Unsupported
    # parameter: temperature" for its models; sending a configured value
    # failed an entire run over a knob the endpoint will not accept.
    # Said once at construction (see CodexTransport.__init__), not silently.
    if tools:
        body["tools"] = to_responses_tools(tools)
    return body


def codex_single_send_body(messages: list[dict[str, Any]], default_model: str | None = None,
                           **kwargs: Any) -> dict[str, Any]:
    """single_send's Responses body and its bound/parameter refusals.

    Shared by the send and its preflight. No credential, client or network.
    """
    from temper_ai.llm import single_send as ss
    mode = kwargs.get("output_bound_mode")
    body = codex_request_body(messages, str(kwargs.get("model") or default_model), kwargs.get("tools"))
    if mode == "request_limit":
        if not kwargs.get("request_limit_evidence") or type(kwargs.get("max_tokens")) is not int:
            raise ss.NamedRefusal("strict_parser", "bound_unestablished")
        body["max_output_tokens"] = kwargs["max_tokens"]
    elif mode != "documented_max":
        raise ss.NamedRefusal("strict_parser", "bound_unestablished")
    if any(key in kwargs for key in ("temperature", "thinking", "thinking_budget", "effort", "tools")):
        raise ss.NamedRefusal("strict_parser", "unsupported_parameter")
    return body


def codex_credential_free_headers() -> dict[str, str]:
    """The Codex request headers that carry no credential (shared with the preflight)."""
    return {
        "originator": ORIGINATOR,
        "OpenAI-Beta": "responses=experimental",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


# --------------------------------------------------------------------------
# The transport
# --------------------------------------------------------------------------


class CodexTransport:
    """``complete``/``stream`` over the Codex Responses endpoint."""

    def __init__(self, token: str, *, model: str, base_url: str | None = None,
                 temperature: float | None = None, timeout: float = 120.0,
                 client: httpx.Client | None = None) -> None:
        self.token = token
        self.model = model
        self.temperature = temperature
        self.url = codex_url(base_url)
        self.account_id = account_id_from_token(token)
        self._client = client or httpx.Client(timeout=timeout)
        if temperature is not None:
            logger.info(
                "OpenAI OAuth (Codex) transport ignores temperature=%s: the endpoint "
                "rejects the parameter for these models", temperature,
            )
        exp = token_expiry(token)
        if exp is not None and exp - time.time() < EXPIRY_WARNING_S:
            hours = max(0.0, (exp - time.time()) / 3600)
            logger.warning(
                "OpenAI OAuth token expires in %.1fh; refresh it in pi (/login openai) "
                "and re-run local/sync-openai-oauth-token.sh", hours,
            )

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "chatgpt-account-id": self.account_id,
            **codex_credential_free_headers(),
        }

    def body(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        return codex_request_body(messages, str(kwargs.get("model") or self.model), kwargs.get("tools"))

    def complete(self, messages: list[dict[str, Any]], *, single_send: bool = False, **kwargs: Any) -> LLMResponse:
        if single_send:
            return self._complete_single_send(messages, **kwargs)
        return self.stream(messages, on_chunk=None, **kwargs)

    def stream(self, messages: list[dict[str, Any]], on_chunk: StreamCallback | None = None,
               *, single_send: bool = False, **kwargs: Any) -> LLMResponse:
        if single_send:
            from temper_ai.llm.single_send import SingleSendError
            if on_chunk is not None:
                raise SingleSendError("strict_parser")
            return self._complete_single_send(messages, **kwargs)
        body = self.body(messages, **kwargs)
        t0 = time.monotonic()
        with self._client.stream("POST", self.url, headers=self.headers(), json=body) as resp:
            if resp.status_code != 200:
                detail = resp.read().decode(errors="replace")[:400]
                raise RuntimeError(f"Codex endpoint returned HTTP {resp.status_code}: {detail}")
            result = self._consume(resp, on_chunk, body["model"])
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        if on_chunk:
            on_chunk(LLMStreamChunk(content="", done=True))
        return result

    def _complete_single_send(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        from temper_ai.llm import single_send as ss
        result = LLMResponse(content=None, model=str(kwargs.get("model", "")), provider="openai")
        failure = None
        with ss.metadata_only_logs():
            control = ss.strict_control(kwargs)
            try:
                if "token" in kwargs:
                    raise ss.SingleSendError("auth")
                body = codex_single_send_body(messages, self.model, **kwargs)
                client = ss.new_http_client(control)
                control.own(client.close)
                manager = client.stream("POST", self.url, headers=self.headers(), json=body)
                resp = manager.__enter__()
                control.own(lambda: manager.__exit__(None, None, None))
                resp.raise_for_status()
                self._consume_single_send(resp, control, result)
                control.check()
            except Exception as exc:  # noqa: BLE001 - no provider error body retained
                failure = ss.safe_failure(exc, result)
            finally:
                control.finish()
            if control.failure_reason:
                failure = ss.SingleSendError(control.failure_reason, response=result)
            if control.cleanup_uncertain:
                failure = ss.SingleSendError("timeout", response=result)
            if failure is not None:
                raise failure
            return result

    def _consume_single_send(self, resp: httpx.Response, control: Any, result: LLMResponse) -> None:
        from temper_ai.llm import single_send as ss
        text: list[str] = []
        terminal = False
        for line in resp.iter_lines():
            control.check()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                event = json.loads(payload)
            except (ValueError, TypeError):
                raise ss.SingleSendError("partial", response=result) from None
            if not isinstance(event, dict) or terminal:
                raise ss.SingleSendError("partial", response=result)
            kind = event.get("type")
            if kind == "response.output_text.delta":
                delta = event.get("delta")
                if not isinstance(delta, str):
                    raise ss.SingleSendError("partial", response=result)
                text.append(delta)
                result.content = "".join(text)
            elif kind in ("response.output_item.added", "response.output_item.done"):
                if (event.get("item") or {}).get("type") not in ("message", "reasoning"):
                    raise ss.SingleSendError("partial", response=result)
            elif kind in ("response.function_call_arguments.delta", "response.function_call_arguments.done"):
                raise ss.SingleSendError("partial", response=result)
            elif kind in ("response.completed", "response.incomplete"):
                value = event.get("response") or {}
                if any(item.get("type") not in ("message", "reasoning") for item in value.get("output", [])):
                    raise ss.SingleSendError("partial", response=result)
                completed = kind == "response.completed" and value.get("status") == "completed"
                result.raw_response = {"response_id": ss.safe_response_id(value.get("id")),
                                       "terminal_complete": completed}
                result.finish_reason = "incomplete" if kind == "response.incomplete" else "stop" if completed else None
                usage = ss.reported_usage(value.get("usage"), codex=True)
                result.prompt_tokens = usage["input_tokens"]
                result.completion_tokens = usage["output_tokens"]
                result.total_tokens = usage["total_tokens"]
                result.raw_response["usage"] = usage
                if not completed:
                    raise ss.SingleSendError("truncation", response=result)
                terminal = True
            elif kind in ("response.failed", "error"):
                raise ss.SingleSendError("transport", response=result)
        control.check()
        if not terminal:
            raise ss.SingleSendError("partial", response=result)
        result.content = "".join(text)

    def _consume(self, resp: httpx.Response, on_chunk: StreamCallback | None, model: str) -> LLMResponse:
        text_parts: list[str] = []
        calls: dict[str, dict[str, Any]] = {}  # item_id → {id, name, arguments}
        order: list[str] = []
        usage: dict[str, Any] = {}
        status = "completed"
        response_id: str | None = None

        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            ev = json.loads(payload)
            et = ev.get("type", "")

            if et == "response.output_text.delta":
                delta = ev.get("delta", "")
                if delta:
                    text_parts.append(delta)
                    if on_chunk:
                        on_chunk(LLMStreamChunk(content=delta, done=False))
            elif et == "response.output_item.added":
                item = ev.get("item") or {}
                if item.get("type") == "function_call":
                    iid = str(item.get("id"))
                    calls[iid] = {"id": item.get("call_id"), "name": item.get("name"), "arguments": ""}
                    order.append(iid)
            elif et == "response.function_call_arguments.delta":
                iid = str(ev.get("item_id"))
                calls.setdefault(iid, {"id": None, "name": None, "arguments": ""})
                calls[iid]["arguments"] += ev.get("delta", "")
            elif et == "response.output_item.done":
                item = ev.get("item") or {}
                if item.get("type") == "function_call":
                    iid = str(item.get("id"))
                    entry = calls.setdefault(iid, {"id": None, "name": None, "arguments": ""})
                    entry.update({"id": item.get("call_id") or entry["id"],
                                  "name": item.get("name") or entry["name"],
                                  "arguments": item.get("arguments") or entry["arguments"]})
                    if iid not in order:
                        order.append(iid)
            elif et == "response.completed":
                r = ev.get("response") or {}
                usage = r.get("usage") or {}
                response_id = r.get("id")
                status = r.get("status") or status
            elif et in ("response.failed", "response.incomplete", "error"):
                err = (ev.get("response") or {}).get("error") or ev.get("error") or ev
                raise RuntimeError(f"Codex response {et}: {json.dumps(err)[:400]}")

        tool_calls = []
        for iid in order:
            c = calls[iid]
            try:
                args = json.loads(c["arguments"]) if c["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": c["id"] or iid, "name": c["name"] or "", "arguments": args})

        prompt = usage.get("input_tokens")
        completion = usage.get("output_tokens")
        total = usage.get("total_tokens")
        if total is None and prompt is not None and completion is not None:
            total = prompt + completion
        return LLMResponse(
            content="".join(text_parts),
            model=model,
            provider="openai",
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            finish_reason="tool_calls" if tool_calls else ("stop" if status == "completed" else status),
            tool_calls=tool_calls or None,
            raw_response={"response_id": response_id, "status": status, "transport": "codex"},
        )
