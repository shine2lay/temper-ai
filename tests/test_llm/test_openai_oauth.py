"""OpenAI provider: an API key and a ChatGPT-subscription OAuth token are told
apart by shape, and the OAuth token goes to a different endpoint speaking a
different protocol.

The SSE transcripts below are the event shapes the live Codex endpoint
returned to a probe (gpt-5.6-luna, 2026-09-17), trimmed to the fields the
parser reads — not the shapes the documentation describes.
"""

import base64
import json

import pytest

from temper_ai.llm.providers import openai as mod
from temper_ai.llm.providers.ollama import OllamaLLM
from temper_ai.llm.providers.openai import OpenAILLM, is_oauth_token, resolve_credential
from temper_ai.llm.providers.openai_codex import (
    CodexTransport,
    account_id_from_token,
    codex_url,
    to_responses_input,
    to_responses_tools,
)


def _jwt(claims: dict) -> str:
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.sig"


TOKEN = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-123"}, "exp": 4_000_000_000})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(mod.API_KEY_ENV, raising=False)
    monkeypatch.delenv(mod.OAUTH_TOKEN_ENV, raising=False)


# ---------------------------------------------------------------------------
# Credential shape
# ---------------------------------------------------------------------------


def test_an_api_key_is_not_an_oauth_token():
    assert is_oauth_token("sk-proj-abc123") is False


def test_a_jwt_is_an_oauth_token():
    assert is_oauth_token(TOKEN) is True


def test_resolution_order_and_kind(monkeypatch):
    assert resolve_credential() == (None, "none")
    monkeypatch.setenv(mod.OAUTH_TOKEN_ENV, TOKEN)
    assert resolve_credential() == (TOKEN, "oauth")
    monkeypatch.setenv(mod.API_KEY_ENV, "sk-proj-x")
    assert resolve_credential() == ("sk-proj-x", "api_key"), "API key wins when both are set"
    assert resolve_credential(TOKEN) == (TOKEN, "oauth"), "explicit argument wins over env"


def test_the_kind_comes_from_the_shape_not_the_variable(monkeypatch):
    monkeypatch.setenv(mod.API_KEY_ENV, TOKEN)  # a JWT in the api-key slot
    assert resolve_credential()[1] == "oauth"


def test_account_id_is_read_from_the_token():
    assert account_id_from_token(TOKEN) == "acct-123"


def test_a_token_without_the_claim_is_refused():
    with pytest.raises(ValueError, match="chatgpt_account_id"):
        account_id_from_token(_jwt({"sub": "x"}))


def test_codex_url_normalises():
    assert codex_url("https://chatgpt.com/backend-api") == "https://chatgpt.com/backend-api/codex/responses"
    assert codex_url("https://chatgpt.com/backend-api/codex") == "https://chatgpt.com/backend-api/codex/responses"
    assert codex_url("https://x/codex/responses") == "https://x/codex/responses"


# ---------------------------------------------------------------------------
# Provider wiring
# ---------------------------------------------------------------------------


def test_oauth_token_routes_to_the_codex_transport():
    llm = OpenAILLM(model="gpt-5.6-luna", base_url="https://api.openai.com/v1", api_key=TOKEN)
    assert llm.auth_mode == "oauth"
    assert isinstance(llm._codex, CodexTransport)
    assert llm._codex.account_id == "acct-123"


def test_api_key_keeps_the_chat_completions_path():
    llm = OpenAILLM(model="gpt-4o-mini", base_url="https://api.openai.com/v1", api_key="sk-proj-x")
    assert llm.auth_mode == "api_key"
    assert llm._codex is None
    assert llm._get_headers()["Authorization"] == "Bearer sk-proj-x"


def test_subclasses_never_pick_up_an_oauth_token_from_the_environment(monkeypatch):
    monkeypatch.setenv(mod.OAUTH_TOKEN_ENV, TOKEN)
    llm = OllamaLLM(model="llama3", base_url="http://localhost:11434")
    assert llm._codex is None
    assert llm.api_key != TOKEN


# ---------------------------------------------------------------------------
# Chat Completions shapes → Responses shapes
# ---------------------------------------------------------------------------


def test_system_becomes_instructions_and_turns_become_items():
    instructions, items = to_responses_input([
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ])
    assert instructions == "Be terse."
    assert items == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hello"}]},
    ]


def test_a_tool_round_trip_keeps_the_call_id_paired():
    """The service injects the tool result with the id the model used; the
    Responses API pairs function_call and function_call_output on call_id."""
    _, items = to_responses_input([
        {"role": "user", "content": "17*23?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "function": {"name": "Calculator", "arguments": '{"expression": "17*23"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "391"},
    ])
    assert items[1] == {"type": "function_call", "call_id": "call_1", "name": "Calculator",
                        "arguments": '{"expression": "17*23"}'}
    assert items[2] == {"type": "function_call_output", "call_id": "call_1", "output": "391"}


def test_dict_arguments_are_serialised():
    _, items = to_responses_input([
        {"role": "assistant", "tool_calls": [{"id": "c", "name": "T", "arguments": {"a": 1}}]},
    ])
    assert items[0]["arguments"] == '{"a": 1}'


def test_tools_flatten_to_the_responses_shape():
    assert to_responses_tools([{"type": "function", "function": {
        "name": "Calculator", "description": "math", "parameters": {"type": "object", "properties": {}}}}]) == [
        {"type": "function", "name": "Calculator", "description": "math",
         "parameters": {"type": "object", "properties": {}}}]


# ---------------------------------------------------------------------------
# SSE parsing — transcripts from the live endpoint
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, events, status=200):
        self.status_code = status
        self._events = events

    def iter_lines(self):
        for ev in self._events:
            yield "data: " + json.dumps(ev)

    def read(self):
        return b'{"error":"nope"}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Client:
    def __init__(self, events, status=200):
        self.events, self.status, self.sent = events, status, []

    def stream(self, method, url, headers=None, json=None):
        self.sent.append({"method": method, "url": url, "headers": headers, "json": json})
        return _Resp(self.events, self.status)


TEXT_TRANSCRIPT = [
    {"type": "response.created"},
    {"type": "response.output_item.added", "item": {"type": "message", "id": "msg_1", "role": "assistant"}},
    {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "O"},
    {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "K"},
    {"type": "response.output_item.done", "item": {"type": "message", "id": "msg_1"}},
    {"type": "response.completed", "response": {"id": "resp_1", "status": "completed",
     "usage": {"input_tokens": 18, "output_tokens": 5, "total_tokens": 23}, "output": []}},
]

TOOL_TRANSCRIPT = [
    {"type": "response.output_item.added", "item": {"type": "function_call", "id": "fc_1",
     "call_id": "call_YW3", "name": "Calculator", "arguments": "", "status": "in_progress"}},
    {"type": "response.function_call_arguments.delta", "item_id": "fc_1", "delta": '{"'},
    {"type": "response.function_call_arguments.delta", "item_id": "fc_1", "delta": 'expression":"17*23"}'},
    {"type": "response.function_call_arguments.done", "item_id": "fc_1", "arguments": '{"expression":"17*23"}'},
    {"type": "response.output_item.done", "item": {"type": "function_call", "id": "fc_1",
     "call_id": "call_YW3", "name": "Calculator", "arguments": '{"expression":"17*23"}', "status": "completed"}},
    {"type": "response.completed", "response": {"id": "resp_2", "status": "completed",
     "usage": {"input_tokens": 59, "output_tokens": 20, "total_tokens": 79}, "output": []}},
]


def _transport(events, status=200):
    client = _Client(events, status)
    return CodexTransport(TOKEN, model="gpt-5.6-luna", client=client), client


def test_text_is_assembled_from_deltas_and_usage_from_completed():
    t, client = _transport(TEXT_TRANSCRIPT)
    chunks = []
    r = t.stream([{"role": "user", "content": "Say OK"}], on_chunk=lambda c: chunks.append(c))
    assert r.content == "OK"
    assert (r.prompt_tokens, r.completion_tokens, r.total_tokens) == (18, 5, 23)
    assert r.finish_reason == "stop"
    assert r.tool_calls is None
    assert [c.content for c in chunks if not c.done] == ["O", "K"]
    assert chunks[-1].done is True


def test_a_function_call_becomes_a_tool_call_with_its_call_id():
    t, _ = _transport(TOOL_TRANSCRIPT)
    r = t.complete([{"role": "user", "content": "17*23?"}], tools=[{"function": {"name": "Calculator"}}])
    assert r.finish_reason == "tool_calls"
    assert r.tool_calls == [{"id": "call_YW3", "name": "Calculator", "arguments": {"expression": "17*23"}}]
    assert r.content == ""


def test_the_wire_request_is_the_codex_shape():
    t, client = _transport(TEXT_TRANSCRIPT)
    t.complete([{"role": "system", "content": "Be terse."}, {"role": "user", "content": "hi"}],
               tools=[{"function": {"name": "T", "parameters": {"type": "object"}}}])
    sent = client.sent[0]
    assert sent["url"] == "https://chatgpt.com/backend-api/codex/responses"
    h = sent["headers"]
    assert h["Authorization"] == f"Bearer {TOKEN}"
    assert h["chatgpt-account-id"] == "acct-123"
    assert h["originator"] == "temper"
    assert h["OpenAI-Beta"] == "responses=experimental"
    body = sent["json"]
    assert body["model"] == "gpt-5.6-luna"
    assert body["instructions"] == "Be terse."
    assert body["store"] is False and body["stream"] is True
    assert body["tools"][0]["name"] == "T"
    assert "max_tokens" not in body  # Chat Completions field; Responses would reject it
    assert "temperature" not in body  # the live endpoint answers 400 "Unsupported parameter"


def test_a_configured_temperature_is_dropped_not_sent():
    client = _Client(TEXT_TRANSCRIPT)
    t = CodexTransport(TOKEN, model="gpt-5.6-luna", temperature=0, client=client)
    t.complete([{"role": "user", "content": "hi"}])
    assert "temperature" not in client.sent[0]["json"]


def test_the_per_call_model_wins():
    t, client = _transport(TEXT_TRANSCRIPT)
    t.complete([{"role": "user", "content": "hi"}], model="gpt-5.4-mini")
    assert client.sent[0]["json"]["model"] == "gpt-5.4-mini"


def test_a_failed_response_raises_with_the_reason():
    t, _ = _transport([{"type": "response.failed", "response": {"error": {"message": "quota exhausted"}}}])
    with pytest.raises(RuntimeError, match="quota exhausted"):
        t.complete([{"role": "user", "content": "hi"}])


def test_a_non_200_raises_with_the_status():
    t, _ = _transport([], status=401)
    with pytest.raises(RuntimeError, match="HTTP 401"):
        t.complete([{"role": "user", "content": "hi"}])
