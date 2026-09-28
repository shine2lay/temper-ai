"""A stream that breaks after it began is sent again, not failed with its agent.

The SDK retries a request whose response never began and nothing after that.
A stalled read or an "Overloaded" event mid-stream failed the call and ended
the agent, hours into a round at high effort (5 of 15,164 calls in 60 hours).
"""

import logging
import types

import httpx
import pytest

from temper_ai.llm.providers import anthropic as mod
from temper_ai.llm.token_pool import TokenCooling


class _StreamError(Exception):
    """What the SDK raises for an error event inside a stream that began with 200."""

    def __init__(self, kind: str):
        body = {"type": "error", "error": {"details": None, "type": kind, "message": kind}}
        super().__init__(str(body))
        self.body, self.status_code = body, 200


class _Stream:
    """One `messages.stream(...)`: some text, then the final message or a failure part-way."""

    def __init__(self, failure: Exception | None):
        self._failure = failure

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        yield "the first words"
        if self._failure is not None:
            raise self._failure
        yield " and the rest"

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
    provider = mod.AnthropicLLM(api_key="sk-ant-api03-abc", model="claude-opus-5-5")
    return provider, messages, waits


def _stream(provider):
    return provider.stream([{"role": "user", "content": "hi"}])


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
    assert "attempt 1/3" in caplog.text, "the base class's retry record says so"


def test_it_gives_up_after_the_base_class_attempts_and_raises_what_broke(llm):
    provider, messages, waits = llm
    messages.script = [httpx.ReadTimeout("The read operation timed out")] * 5
    with pytest.raises(httpx.ReadTimeout):
        _stream(provider)
    assert messages.calls == provider.max_retries == 3
    assert len(waits) == 2


@pytest.mark.parametrize("failure", [
    _StreamError("invalid_request_error"),
    TokenCooling("wai2shine", "claude-opus-5-5", None),
    ValueError("a bug of ours"),
], ids=["refused request", "capacity (the fallback list's)", "anything else"])
def test_a_failure_that_is_not_the_connection_is_not_sent_again(llm, failure):
    provider, messages, waits = llm
    messages.script = [failure]
    with pytest.raises(type(failure)):
        _stream(provider)
    assert messages.calls == 1
    assert waits == []
