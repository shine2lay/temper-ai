"""A stream that breaks after it began is sent again, not failed with its agent.

The SDK retries a request whose response never began and nothing after that.
A stalled read or an "Overloaded" event mid-stream failed the call and ended
the agent, hours into a round at high effort (5 of 15,164 calls in 60 hours).
Three attempts 1 s and 2 s apart did not outlast an overload burst either, so
the call keeps being sent, waiting longer each time, until
`stream_retry_budget_s` (10 minutes) of waiting in all.
"""

import logging
import types

import httpx
import pytest

from temper_ai.llm.providers import anthropic as mod
from temper_ai.llm.providers import base as base_mod
from temper_ai.llm.token_pool import TokenCooling


class _StreamError(Exception):
    """What the SDK raises for an error event inside a stream that began with 200."""

    def __init__(self, kind: str):
        body = {"type": "error", "error": {"details": None, "type": kind, "message": kind}}
        super().__init__(str(body))
        self.body, self.status_code = body, 200


def _text_event(text: str):
    """One `content_block_delta` carrying answer text.

    The provider reads the whole event stream rather than `text_stream`,
    because thinking arrives as its own kind of delta and `text_stream` drops
    everything that is not the answer.
    """
    return types.SimpleNamespace(
        type="content_block_delta",
        delta=types.SimpleNamespace(type="text_delta", text=text),
    )


class _Stream:
    """One `messages.stream(...)`: some text, then the final message or a failure part-way."""

    def __init__(self, failure: Exception | None):
        self._failure = failure

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield _text_event("the first words")
        if self._failure is not None:
            raise self._failure
        yield _text_event(" and the rest")

    @property
    def text_stream(self):
        for event in self:
            yield event.delta.text

    def get_final_message(self):
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="the answer")],
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )


class _Messages:
    """Each stream call takes the next failure off the script; past its end every stream succeeds."""

    def __init__(self, script: list[Exception | None]):
        self.script = list(script)
        self.calls = 0

    def stream(self, **kwargs):
        failure = self.script[self.calls] if self.calls < len(self.script) else None
        self.calls += 1
        return _Stream(failure)


@pytest.fixture
def llm(monkeypatch):
    """A provider on an API key (no pool), its SDK faked, and no real waiting between attempts."""
    messages = _Messages([])
    monkeypatch.setattr(mod, "_ensure_anthropic",
                        lambda: types.SimpleNamespace(Anthropic=lambda **kw: types.SimpleNamespace(messages=messages)))
    waits: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", waits.append)
    # Half a second of jitter on every wait, so the waits can be counted.
    monkeypatch.setattr(mod, "random", types.SimpleNamespace(random=lambda: 0.5))
    provider = mod.AnthropicLLM(api_key="sk-ant-api03-abc", model="claude-opus-5-5")
    return provider, messages, waits


@pytest.fixture
def retries(monkeypatch):
    """The retry events the provider records."""
    seen: list[dict] = []
    monkeypatch.setattr(base_mod, "record", lambda kind, data=None, **kw: seen.append(data))
    return seen


def _stream(provider, **kwargs):
    return provider.stream([{"role": "user", "content": "hi"}], **kwargs)


@pytest.mark.parametrize("failure", [
    httpx.ReadTimeout("The read operation timed out"),
    httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
    _StreamError("overloaded_error"),
    _StreamError("api_error"),
], ids=["stalled read", "dropped connection", "overloaded event", "server error event"])
def test_a_stream_that_broke_part_way_is_sent_again(llm, failure, caplog):
    provider, messages, waits = llm
    messages.script = [failure]
    with caplog.at_level(logging.WARNING):
        answer = _stream(provider)
    assert answer.content == "the answer"
    assert messages.calls == 2
    assert len(waits) == 1
    assert "LLM call failed (attempt 1)" in caplog.text, "the retry is logged"


def test_an_overload_burst_longer_than_the_old_three_attempts_is_outlasted(llm, retries):
    """Broken nine times in a row -- far past the old 1 s + 2 s -- and the call still comes back."""
    provider, messages, waits = llm
    messages.script = [_StreamError("overloaded_error")] * 9
    answer = _stream(provider)
    assert answer.content == "the answer"
    assert messages.calls == 10
    assert waits == [1.5, 2.5, 4.5, 8.5, 16.5, 32.5, 60.5, 60.5, 60.5], "growing waits, then a minute each"
    assert sum(waits) < provider.stream_retry_budget_s == 600
    assert len(retries) == 9, "every retry is recorded"
    assert [r["attempt"] for r in retries] == list(range(1, 10))
    assert retries[0]["retry_budget_s"] == 600
    assert retries[0]["max_retries"] is None, "bounded by time, not by attempts"
    assert retries[-1]["waited_s"] == round(sum(waits[:-1]), 1)
    assert all("overloaded_error" in r["error"] for r in retries)


def test_it_gives_up_after_ten_minutes_of_waiting_and_raises_what_broke(llm, retries):
    provider, messages, waits = llm
    messages.script = [httpx.ReadTimeout("The read operation timed out")] * 100
    with pytest.raises(httpx.ReadTimeout):
        _stream(provider)
    assert sum(waits) == pytest.approx(600), "the whole budget, the last wait cut to what was left"
    assert waits[:7] == [1.5, 2.5, 4.5, 8.5, 16.5, 32.5, 60.5]
    assert max(waits) <= 60.5
    assert messages.calls == len(waits) + 1 == len(retries) + 1
    assert messages.calls < 100, "it stopped on the budget, not on the script"


def test_an_agents_provider_config_sets_its_own_budget(llm):
    provider, messages, waits = llm
    messages.script = [_StreamError("overloaded_error")] * 100
    with pytest.raises(_StreamError):
        _stream(provider, stream_retry_budget_s=5)
    assert waits == [1.5, 2.5, 1.0]
    assert messages.calls == 4


def test_a_budget_of_nothing_sends_it_once(llm):
    provider, messages, waits = llm
    messages.script = [_StreamError("overloaded_error")]
    with pytest.raises(_StreamError):
        _stream(provider, stream_retry_budget_s=0)
    assert messages.calls == 1
    assert waits == []


def test_the_providers_own_setting_is_the_default(monkeypatch):
    monkeypatch.setattr(mod, "_ensure_anthropic", lambda: types.SimpleNamespace(Anthropic=lambda **kw: None))
    assert mod.AnthropicLLM(api_key="sk-ant-api03-abc").stream_retry_budget_s == 600
    assert mod.AnthropicLLM(api_key="sk-ant-api03-abc", stream_retry_budget_s=30).stream_retry_budget_s == 30


@pytest.mark.parametrize("failure", [
    _StreamError("invalid_request_error"),
    TokenCooling("wai2shine", "claude-opus-5-5", None),
    ValueError("a bug of ours"),
], ids=["refused request", "capacity (the fallback list's)", "anything else"])
def test_a_failure_that_is_not_the_connection_is_not_sent_again(llm, retries, failure):
    provider, messages, waits = llm
    messages.script = [failure]
    with pytest.raises(type(failure)):
        _stream(provider)
    assert messages.calls == 1
    assert waits == []
    assert retries == []
