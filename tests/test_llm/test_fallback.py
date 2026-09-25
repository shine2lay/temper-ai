"""An agent's fallback list: when its model is out of capacity, the call moves on.

The provider's own rollover (temper_ai.llm.token_pool) moves a limited call to
the next subscription. This list is what comes after that: another model, or
another provider, named in the agent's config.
"""

import httpx
import pytest

from temper_ai.llm.fallback import FallbackTarget, is_capacity_error, parse_fallback
from temper_ai.llm.models import CallContext, LLMResponse
from temper_ai.llm.service import LLMService
from temper_ai.llm.token_pool import PoolExhausted
from temper_ai.observability import EventType, get_events

from .conftest import MockProvider


def _text(content="Done", model="mock-model"):
    return LLMResponse(content=content, model=model, provider="MockProvider",
                       prompt_tokens=60, completion_tokens=40, total_tokens=100,
                       latency_ms=50, finish_reason="stop")


def _tool_call(model="mock-model"):
    return LLMResponse(content=None, model=model, provider="MockProvider",
                       prompt_tokens=60, completion_tokens=40, total_tokens=100,
                       latency_ms=50, finish_reason="tool_calls",
                       tool_calls=[{"id": "c1", "name": "bash", "arguments": "{}"}])


def _http_error(status: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://llm/v1")
    return httpx.HTTPStatusError(body or f"HTTP {status}", request=request,
                                 response=httpx.Response(status, request=request, text=body))


class _Scripted(MockProvider):
    """A mock that raises where the script holds an exception."""

    def __init__(self, script, name="mock", supports_tools=True):
        super().__init__([])
        self._script = list(script)
        self.PROVIDER_NAME = name
        self.SUPPORTS_TOOLS = supports_tools

    def _next_response(self):
        if not self._script:
            raise RuntimeError(f"{self.PROVIDER_NAME}: script exhausted")
        step = self._script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


_TOOLS = [{"type": "function", "function": {"name": "bash"}}]


def _events(execution_id, kind):
    return [e for e in get_events(execution_id=execution_id) if e["type"] == kind]


# -- reading the config --


class TestParseFallback:
    def test_absent_is_no_fallback(self):
        assert parse_fallback(None) == []

    def test_a_model_name_stays_on_the_agents_provider(self):
        assert parse_fallback(["claude-sonnet-5"]) == [FallbackTarget(model="claude-sonnet-5")]

    def test_a_single_entry_need_not_be_a_list(self):
        assert parse_fallback("claude-sonnet-5") == [FallbackTarget(model="claude-sonnet-5")]
        assert parse_fallback({"provider": "openai"}) == [FallbackTarget(provider="openai")]

    def test_a_mapping_can_change_provider_and_its_settings(self):
        [target] = parse_fallback([{"provider": "openai", "model": "gpt-5.6-luna",
                                    "provider_config": {"effort": "medium"}}])
        assert target == FallbackTarget(provider="openai", model="gpt-5.6-luna",
                                        provider_config={"effort": "medium"})

    @pytest.mark.parametrize("raw, says", [
        (5, "must be a list"),
        ([""], "empty model name"),
        ([3], "model name or a mapping"),
        ([{"modle": "x"}], "unknown key(s) modle"),
        ([{"provider_config": {"a": 1}}], "neither a provider nor a model"),
        ([{"model": ""}], "model must be a non-empty string"),
        ([{"model": "m", "provider_config": "high"}], "provider_config must be a mapping"),
    ])
    def test_a_malformed_list_says_which_entry_and_why(self, raw, says):
        with pytest.raises(ValueError, match=r"fallback") as err:
            parse_fallback(raw)
        assert says in str(err.value)


class TestIsCapacityError:
    @pytest.mark.parametrize("exc", [
        _http_error(429, "rate_limit_error"),
        _http_error(529, "overloaded_error"),
        _http_error(400, "Your credit balance is too low to access the Anthropic API"),
        PoolExhausted(3, None),
        RuntimeError("Codex endpoint returned HTTP 429: usage limit reached"),
        RuntimeError('Codex response response.failed: {"code": "rate_limit_exceeded"}'),
    ])
    def test_out_of_capacity(self, exc):
        assert is_capacity_error(exc)

    @pytest.mark.parametrize("exc", [
        _http_error(400, "messages: field required"),
        _http_error(401, "invalid x-api-key"),
        _http_error(500, "internal error"),
        httpx.ReadTimeout("timed out"),
        RuntimeError("tool schema invalid"),
    ])
    def test_other_failures_are_not(self, exc):
        """They would fail the same way on the next model, or are faults to see."""
        assert not is_capacity_error(exc)


# -- the loop --


class TestFallingBack:
    def test_same_provider_moves_to_the_next_model(self):
        own = _Scripted([_http_error(429), _text("from sonnet", model="claude-sonnet-5")])
        service = LLMService(own, fallbacks=parse_fallback(["claude-sonnet-5"]))
        ctx = CallContext(execution_id="fb-1", agent_name="a", model="claude-opus-5-5")

        result = service.run([{"role": "user", "content": "hi"}], context=ctx)

        assert result.error is None and result.output == "from sonnet"
        assert [c["kwargs"]["model"] for c in own.calls] == ["claude-opus-5-5", "claude-sonnet-5"]

    def test_another_provider_gets_its_own_settings_not_the_agents(self):
        own = _Scripted([_http_error(429)], name="anthropic")
        other = _Scripted([_text("from luna", model="gpt-5.6-luna")], name="openai")
        service = LLMService(
            own, resolve_llm={"openai": other}.__getitem__,
            fallbacks=parse_fallback([{"provider": "openai", "model": "gpt-5.6-luna",
                                       "provider_config": {"effort": "medium"}}]))
        ctx = CallContext(execution_id="fb-2", model="claude-opus-5-5",
                          provider_config={"effort": "max", "thinking": "adaptive"})

        result = service.run([{"role": "user", "content": "hi"}], context=ctx)

        assert result.output == "from luna"
        sent = other.calls[0]["kwargs"]
        assert sent["model"] == "gpt-5.6-luna"
        assert sent["effort"] == "medium" and "thinking" not in sent

    def test_the_same_provider_keeps_the_agents_settings_under_the_entrys(self):
        own = _Scripted([_http_error(429), _text()])
        service = LLMService(own, fallbacks=parse_fallback(
            [{"model": "claude-sonnet-5", "provider_config": {"effort": "high"}}]))
        ctx = CallContext(execution_id="fb-3", model="claude-opus-5-5",
                          provider_config={"effort": "max", "thinking": "adaptive"})

        service.run([{"role": "user", "content": "hi"}], context=ctx)

        sent = own.calls[1]["kwargs"]
        assert sent["effort"] == "high" and sent["thinking"] == "adaptive"

    def test_the_whole_transcript_goes_to_the_fallback(self):
        own = _Scripted([_http_error(429)], name="anthropic")
        other = _Scripted([_text()], name="openai")
        service = LLMService(own, resolve_llm={"openai": other}.__getitem__,
                             fallbacks=parse_fallback([{"provider": "openai"}]))
        messages = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]

        service.run(messages, context=CallContext(execution_id="fb-4"))

        assert other.calls[0]["messages"] == own.calls[0]["messages"]

    def test_the_move_lasts_for_the_rest_of_the_run(self):
        own = _Scripted([_http_error(429)], name="anthropic")
        other = _Scripted([_tool_call(), _text("done")], name="openai")
        service = LLMService(own, resolve_llm={"openai": other}.__getitem__,
                             fallbacks=parse_fallback([{"provider": "openai"}]))

        result = service.run([{"role": "user", "content": "hi"}], tools=_TOOLS,
                             execute_tool=lambda name, params: "ok",
                             context=CallContext(execution_id="fb-5"))

        assert result.output == "done"
        assert len(own.calls) == 1 and len(other.calls) == 2

    def test_the_next_run_starts_on_the_agents_own_model_again(self):
        own = _Scripted([_http_error(429), _text("own again")], name="anthropic")
        other = _Scripted([_text("fallback")], name="openai")
        service = LLMService(own, resolve_llm={"openai": other}.__getitem__,
                             fallbacks=parse_fallback([{"provider": "openai"}]))

        first = service.run([{"role": "user", "content": "1"}], context=CallContext(execution_id="fb-6"))
        second = service.run([{"role": "user", "content": "2"}], context=CallContext(execution_id="fb-6b"))

        assert (first.output, second.output) == ("fallback", "own again")

    def test_a_fallback_out_of_capacity_moves_on_down_the_list(self):
        own = _Scripted([_http_error(429), _http_error(529), _text("third")])
        service = LLMService(own, fallbacks=parse_fallback(["model-b", "model-c"]))
        ctx = CallContext(execution_id="fb-7", model="model-a")

        result = service.run([{"role": "user", "content": "hi"}], context=ctx)

        assert result.output == "third"
        assert [c["kwargs"]["model"] for c in own.calls] == ["model-a", "model-b", "model-c"]


class TestNotFallingBack:
    def test_a_failure_that_is_not_capacity_is_raised_as_before(self):
        own = _Scripted([_http_error(400, "messages: field required")])
        service = LLMService(own, fallbacks=parse_fallback(["model-b"]))

        with pytest.raises(httpx.HTTPStatusError):
            service.run([{"role": "user", "content": "hi"}], context=CallContext(execution_id="fb-8"))
        assert len(own.calls) == 1
        assert _events("fb-8", EventType.LLM_FALLBACK) == []

    def test_without_a_list_a_limit_fails_the_call_as_before(self):
        own = _Scripted([_http_error(429)])
        service = LLMService(own)

        with pytest.raises(httpx.HTTPStatusError):
            service.run([{"role": "user", "content": "hi"}], context=CallContext(execution_id="fb-9"))
        assert _events("fb-9", EventType.LLM_FALLBACK) == []

    def test_when_the_list_runs_out_the_last_limit_is_raised(self):
        own = _Scripted([_http_error(429), _http_error(429, "still limited")])
        service = LLMService(own, fallbacks=parse_fallback(["model-b"]))

        with pytest.raises(httpx.HTTPStatusError, match="still limited"):
            service.run([{"role": "user", "content": "hi"}],
                        context=CallContext(execution_id="fb-10", model="model-a"))
        [moved, gave_up] = _events("fb-10", EventType.LLM_FALLBACK)
        assert moved["status"] == "completed" and gave_up["status"] == "failed"
        assert gave_up["data"]["to"] is None

    def test_unusable_entries_are_passed_over_and_said_so(self):
        own = _Scripted([_http_error(429)], name="anthropic")
        no_tools = _Scripted([], name="ollama", supports_tools=False)
        good = _Scripted([_text("ok")], name="openai")
        providers = {"ollama": no_tools, "openai": good}
        service = LLMService(own, resolve_llm=providers.__getitem__, fallbacks=parse_fallback([
            {"provider": "gemini"},              # not configured here
            {"provider": "ollama"},              # cannot offer the agent's tools
            "model-a",                           # the model that just ran out
            {"provider": "openai"},
        ]))

        result = service.run([{"role": "user", "content": "hi"}], tools=_TOOLS,
                             execute_tool=lambda name, params: "ok",
                             context=CallContext(execution_id="fb-11", model="model-a"))

        assert result.output == "ok" and no_tools.calls == []
        [event] = _events("fb-11", EventType.LLM_FALLBACK)
        reasons = [s["reason"] for s in event["data"]["skipped"]]
        assert reasons[0].startswith("provider not configured")
        assert reasons[1:] == ["provider cannot offer tools", "already in use"]


class TestTheRecord:
    def test_the_failed_call_names_the_model_that_failed_and_the_move_says_where(self):
        own = _Scripted([_http_error(429, "rate_limit_error")], name="anthropic")
        other = _Scripted([_text(model="gpt-5.6-luna")], name="openai")
        service = LLMService(own, resolve_llm={"openai": other}.__getitem__,
                             fallbacks=parse_fallback([{"provider": "openai", "model": "gpt-5.6-luna"}]))
        ctx = CallContext(execution_id="fb-12", agent_name="writer", model="claude-opus-5-5")

        service.run([{"role": "user", "content": "hi"}], context=ctx)

        [failed] = _events("fb-12", EventType.LLM_CALL_FAILED)
        assert (failed["data"]["provider"], failed["data"]["model"]) == ("anthropic", "claude-opus-5-5")
        [moved] = _events("fb-12", EventType.LLM_FALLBACK)
        assert moved["data"]["from"] == {"provider": "anthropic", "model": "claude-opus-5-5"}
        assert moved["data"]["to"] == {"provider": "openai", "model": "gpt-5.6-luna"}
        assert "rate_limit_error" in moved["data"]["reason"]
        started = _events("fb-12", EventType.LLM_CALL_STARTED)
        assert [(s["data"]["provider"], s["data"]["model"]) for s in started] == [
            ("anthropic", "claude-opus-5-5"), ("openai", "gpt-5.6-luna")]
