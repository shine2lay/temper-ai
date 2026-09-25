"""Naming the token a call goes out on: `token: wai2shine`.

With several subscriptions pooled, the provider rotates across them and a
fallback entry could change the model or the provider, but not the account.
Owners with one account's allowance to spend first (or one to keep for
interactive work) had no way to say so. An agent and each fallback entry can
now name its token -- by the account set beside it in the environment, or by
the variable that holds it -- and then goes out on that one and no other. A
limit on a named token is not rotated past: it goes to the next entry.
"""

import time
import types
from typing import Any

import pytest

from temper_ai.llm.fallback import (
    FallbackTarget,
    is_capacity_error,
    parse_fallback,
    parse_token,
)
from temper_ai.llm.models import CallContext, LLMResponse
from temper_ai.llm.providers import anthropic as mod
from temper_ai.llm.service import LLMService
from temper_ai.llm.token_pool import TokenCooling, TokenPool, named_tokens_from_env
from temper_ai.observability import EventType, get_events

from .conftest import MockProvider

TOK_A = "sk-ant-oat01-aaaa"
TOK_B = "sk-ant-oat01-bbbb"
TOK_C = "sk-ant-oat01-cccc"


def _text(content="Done", model="mock-model"):
    return LLMResponse(content=content, model=model, provider="MockProvider",
                       prompt_tokens=60, completion_tokens=40, total_tokens=100,
                       latency_ms=50, finish_reason="stop")


def _events(execution_id, kind):
    return [e for e in get_events(execution_id=execution_id) if e["type"] == kind]


# -- reading the config --


class TestParseToken:
    @pytest.mark.parametrize("name", ["wai2shine", "CLAUDE_CODE_OAUTH_TOKEN_2", "me@example.com"])
    def test_an_account_or_a_variable_is_a_name(self, name):
        assert parse_token(name) == name
        assert parse_token(f"  {name} ") == name

    def test_absent_is_no_token(self):
        assert parse_token(None) is None

    @pytest.mark.parametrize("raw", [TOK_A, "sk-ant-api03-xyz", "x" * 80, "has space", "${TOKEN}"])
    def test_the_token_itself_is_refused_and_not_quoted_back(self, raw):
        with pytest.raises(ValueError, match="not be the token itself") as err:
            parse_token(raw)
        assert raw not in str(err.value)

    @pytest.mark.parametrize("raw", ["", "  ", 5, ["wai2shine"]])
    def test_what_is_not_a_name_says_so(self, raw):
        with pytest.raises(ValueError, match="must be a token's name"):
            parse_token(raw)

    def test_an_entry_can_name_only_a_token(self):
        assert parse_fallback([{"token": "wai2shine"}]) == [FallbackTarget(token="wai2shine")]
        [target] = parse_fallback([{"model": "claude-opus-5-5", "token": "shinelay"}])
        assert target.describe("anthropic") == "anthropic/claude-opus-5-5 on shinelay"

    def test_an_entrys_bad_token_says_which_entry(self):
        with pytest.raises(ValueError, match=r"fallback\[1\]\.token"):
            parse_fallback(["claude-sonnet-5", {"model": "m", "token": TOK_A}])


# -- which name is which token --


class TestNamesFromTheEnvironment:
    def test_an_account_names_its_token_and_the_variable_does_when_there_is_none(self, monkeypatch):
        monkeypatch.setenv("T", "tok-1")
        monkeypatch.setenv("T_ACCOUNT", "aungshine")
        monkeypatch.setenv("T_2", "tok-2")
        found = named_tokens_from_env("T")
        assert [(n.variable, n.account, n.label) for n in found] == [
            ("T", "aungshine", "aungshine"), ("T_2", None, "T_2")]

    def test_the_pool_logs_the_account_not_the_slot_or_the_token(self):
        p = TokenPool(name="p", tokens=["tok-1", "tok-2"], labels=["aungshine", ""])
        assert p.label_of("tok-1") == "aungshine"
        assert p.label_of("tok-2") == "slot 1"


# -- the Anthropic provider: the call goes out on the named token only --


class _RateLimited(Exception):
    status_code = 429
    response = types.SimpleNamespace(status_code=429, headers={"retry-after": "3600"})


class _Messages:
    def __init__(self, token: str, sent: list):
        self._token, self._sent = token, sent

    def create(self, **kwargs):
        self._sent.append((self._token, kwargs))
        if self._token in _Messages.limited:
            raise _RateLimited("rate_limit_error")
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=f"from {self._token}")],
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )

    limited: set[str] = set()


@pytest.fixture
def accounts(monkeypatch):
    """Three pooled subscriptions: aungshine, wai2shine and one without an account."""
    for var in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN_BACKUP"):
        monkeypatch.delenv(var, raising=False)
    for i in range(2, 10):
        monkeypatch.delenv(f"CLAUDE_CODE_OAUTH_TOKEN_{i}", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", TOK_A)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_ACCOUNT", "aungshine")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_2", TOK_B)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_2_ACCOUNT", "wai2shine")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_3", TOK_C)
    sent: list[tuple[str, dict[str, Any]]] = []
    _Messages.limited = set()

    def fake_anthropic(**kw):
        return types.SimpleNamespace(messages=_Messages(kw.get("auth_token") or kw.get("api_key"), sent))

    monkeypatch.setattr(mod, "_ensure_anthropic", lambda: types.SimpleNamespace(Anthropic=fake_anthropic))
    llm = mod.AnthropicLLM(model="claude-opus-5-5")
    return llm, sent


def _ask(llm, **kwargs):
    return llm.complete([{"role": "user", "content": "hi"}], **kwargs)


class TestAPinnedCall:
    @pytest.mark.parametrize("name, token", [
        ("wai2shine", TOK_B), ("CLAUDE_CODE_OAUTH_TOKEN_2", TOK_B),
        ("aungshine", TOK_A), ("CLAUDE_CODE_OAUTH_TOKEN_3", TOK_C),
    ])
    def test_goes_out_on_the_token_it_names(self, accounts, name, token):
        llm, sent = accounts
        for _ in range(3):
            _ask(llm, token=name, execution_id="run-1", agent_name="a")
        assert [t for t, _ in sent] == [token] * 3

    def test_the_name_is_not_sent_to_the_api(self, accounts):
        llm, sent = accounts
        _ask(llm, token="wai2shine")
        assert "token" not in sent[0][1]

    def test_a_limit_is_not_rotated_past_but_raised_as_out_of_capacity(self, accounts):
        llm, sent = accounts
        _Messages.limited = {TOK_B}
        with pytest.raises(TokenCooling) as err:
            _ask(llm, token="wai2shine")
        assert [t for t, _ in sent] == [TOK_B], "no other account was tried"
        assert is_capacity_error(err.value)
        assert "wai2shine" in str(err.value) and TOK_B not in str(err.value)

    def test_the_limit_cools_the_token_for_the_calls_that_rotate(self, accounts):
        llm, sent = accounts
        _Messages.limited = {TOK_B}
        with pytest.raises(TokenCooling):
            _ask(llm, token="wai2shine")
        assert llm.token_cooling_until("wai2shine", "claude-opus-5-5") > time.time()
        assert llm.token_cooling_until("wai2shine", "claude-sonnet-5") is None, "per model family"
        sent.clear()
        for i in range(6):
            _ask(llm, execution_id=f"run-{i}", agent_name="a")
        assert TOK_B not in [t for t, _ in sent]

    def test_a_token_known_to_be_cooling_is_refused_without_a_request(self, accounts):
        llm, sent = accounts
        _Messages.limited = {TOK_B}
        with pytest.raises(TokenCooling):
            _ask(llm, token="wai2shine")
        sent.clear()
        with pytest.raises(TokenCooling, match="rate limited for opus"):
            _ask(llm, token="wai2shine")
        assert sent == []

    def test_an_unknown_name_lists_the_names_there_are_and_no_token(self, accounts):
        llm, _ = accounts
        with pytest.raises(ValueError, match="no Anthropic token is called 'wai2shien'") as err:
            llm.check_token("wai2shien")
        says = str(err.value)
        assert "aungshine" in says and "wai2shine" in says and "CLAUDE_CODE_OAUTH_TOKEN_3" in says
        assert not any(t in says for t in (TOK_A, TOK_B, TOK_C))

    def test_an_api_key_has_no_named_tokens(self, monkeypatch):
        monkeypatch.setattr(mod, "_ensure_anthropic",
                            lambda: types.SimpleNamespace(Anthropic=lambda **kw: types.SimpleNamespace()))
        llm = mod.AnthropicLLM(api_key="sk-ant-api03-abc")
        with pytest.raises(ValueError, match="not using pooled subscriptions"):
            llm.check_token("wai2shine")


# -- the service: the agent's token, and each entry's --


class _Accounts(MockProvider):
    """A provider with named tokens; the script says what each call gets."""

    def __init__(self, script, names=("aungshine", "wai2shine", "shinelay"), cooling=None):
        super().__init__([])
        self._script = list(script)
        self.PROVIDER_NAME = "anthropic"
        self._names = set(names)
        self.cooling = dict(cooling or {})

    def check_token(self, name):
        if name not in self._names:
            raise ValueError(f"no token is called {name!r}")

    def token_cooling_until(self, name, model=None):
        return self.cooling.get(name)

    def _next_response(self):
        step = self._script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def _limit(name="aungshine"):
    return TokenCooling(name, "claude-opus-5-5", time.time() + 3600)


def _sent(provider):
    return [(c["kwargs"].get("model"), c["kwargs"].get("token")) for c in provider.calls]


class TestTheService:
    def test_the_agents_token_goes_with_every_call(self):
        own = _Accounts([_text(), _text()])
        service = LLMService(own, token="aungshine")
        ctx = CallContext(execution_id="nt-1", model="claude-opus-5-5")
        service.run([{"role": "user", "content": "hi"}], context=ctx)
        service.run([{"role": "user", "content": "again"}], context=ctx)
        assert _sent(own) == [("claude-opus-5-5", "aungshine")] * 2

    def test_without_one_the_provider_rotates(self):
        own = _Accounts([_text()])
        LLMService(own).run([{"role": "user", "content": "hi"}],
                            context=CallContext(execution_id="nt-2", model="claude-opus-5-5"))
        assert "token" not in own.calls[0]["kwargs"]

    def test_a_token_in_provider_config_cannot_pin_a_call(self):
        own = _Accounts([_text()])
        LLMService(own).run([{"role": "user", "content": "hi"}], context=CallContext(
            execution_id="nt-3", model="claude-opus-5-5", provider_config={"token": "wai2shine"}))
        assert "token" not in own.calls[0]["kwargs"]

    def test_an_entry_naming_only_a_token_is_the_same_model_on_that_account(self):
        own = _Accounts([_limit(), _text("from wai2shine")])
        service = LLMService(own, token="aungshine", fallbacks=parse_fallback([{"token": "wai2shine"}]))
        result = service.run([{"role": "user", "content": "hi"}],
                             context=CallContext(execution_id="nt-4", model="claude-opus-5-5"))
        assert result.error is None and result.output == "from wai2shine"
        assert _sent(own) == [("claude-opus-5-5", "aungshine"), ("claude-opus-5-5", "wai2shine")]

    def test_the_list_spends_the_accounts_in_its_order_then_changes_model(self):
        own = _Accounts([_limit(), _limit("wai2shine"), _limit("shinelay"), _text("sonnet, any account")])
        service = LLMService(own, token="aungshine", fallbacks=parse_fallback([
            {"token": "wai2shine"}, {"model": "claude-opus-5-5", "token": "shinelay"}, "claude-sonnet-5"]))
        result = service.run([{"role": "user", "content": "hi"}],
                             context=CallContext(execution_id="nt-5", model="claude-opus-5-5"))
        assert result.output == "sonnet, any account"
        assert _sent(own) == [("claude-opus-5-5", "aungshine"), ("claude-opus-5-5", "wai2shine"),
                              ("claude-opus-5-5", "shinelay"), ("claude-sonnet-5", None)]

    def test_an_entry_does_not_inherit_the_agents_token(self):
        own = _Accounts([_limit(), _text()])
        service = LLMService(own, token="aungshine", fallbacks=parse_fallback(["claude-sonnet-5"]))
        service.run([{"role": "user", "content": "hi"}],
                    context=CallContext(execution_id="nt-6", model="claude-opus-5-5"))
        assert _sent(own)[1] == ("claude-sonnet-5", None)

    def test_an_entry_whose_token_is_cooling_is_passed_over_and_said_so(self):
        own = _Accounts([_limit(), _text("from shinelay")], cooling={"wai2shine": time.time() + 3600})
        service = LLMService(own, token="aungshine", fallbacks=parse_fallback(
            [{"token": "wai2shine"}, {"token": "shinelay"}]))
        result = service.run([{"role": "user", "content": "hi"}],
                             context=CallContext(execution_id="nt-7", model="claude-opus-5-5"))
        assert result.output == "from shinelay"
        assert [t for _, t in _sent(own)] == ["aungshine", "shinelay"]
        [event] = _events("nt-7", EventType.LLM_FALLBACK)
        [skip] = event["data"]["skipped"]
        assert skip["fallback"] == "anthropic/claude-opus-5-5 on wai2shine", "the model it would ask for"
        assert skip["reason"].startswith("wai2shine is rate limited for claude-opus-5-5 until ")

    def test_the_record_names_the_tokens_it_moved_between(self):
        own = _Accounts([_limit(), _text()])
        service = LLMService(own, token="aungshine", fallbacks=parse_fallback([{"token": "wai2shine"}]))
        service.run([{"role": "user", "content": "hi"}],
                    context=CallContext(execution_id="nt-8", model="claude-opus-5-5"))
        [event] = _events("nt-8", EventType.LLM_FALLBACK)
        assert event["data"]["from"] == {"provider": "anthropic", "model": "claude-opus-5-5", "token": "aungshine"}
        assert event["data"]["to"] == {"provider": "anthropic", "model": "claude-opus-5-5", "token": "wai2shine"}
        started = _events("nt-8", EventType.LLM_CALL_STARTED)
        assert [e["data"].get("token") for e in started] == ["aungshine", "wai2shine"]


class TestAMisspeltNameFailsBeforeTheFirstCall:
    def test_the_agents_own(self):
        with pytest.raises(ValueError, match="no token is called 'aungshien'"):
            LLMService(_Accounts([]), token="aungshien")

    def test_an_entrys_says_which_entry(self):
        with pytest.raises(ValueError, match=r"fallback\[1\]: no token is called 'wai2shien'"):
            LLMService(_Accounts([]), fallbacks=parse_fallback(["claude-sonnet-5", {"token": "wai2shien"}]))

    def test_a_provider_without_named_tokens_refuses_any(self):
        other = MockProvider([])
        other.PROVIDER_NAME = "openai"
        with pytest.raises(ValueError, match=r"fallback\[0\]: the openai provider has no named tokens"):
            LLMService(_Accounts([]), resolve_llm={"openai": other}.__getitem__,
                       fallbacks=parse_fallback([{"provider": "openai", "token": "wai2shine"}]))

    def test_an_entry_on_an_unconfigured_provider_is_left_to_be_passed_over(self):
        LLMService(_Accounts([]), resolve_llm={}.__getitem__,
                   fallbacks=parse_fallback([{"provider": "gemini", "token": "x"}]))
