"""A provider's error is never a step's answer.

A provider that hands back an error where the answer should be marks it
`finish_reason: "error"` -- "Error: claude token pool exhausted ...", "Error:
Claude Code CLI timed out", a CLI's limit banner. Read as an answer, the step
completed on it and the run carried on as if the work was done. The service
now fails such a call: a limit goes down the agent's fallback list and on to
the allowance park like any capacity failure, anything else fails the call.

Decided on the finish reason alone. An answer that merely talks about limits,
or quotes one of these sentences, completes like any other answer: the engine
never reads an answer's words.
"""

import pytest

from temper_ai.llm import allowance
from temper_ai.llm.fallback import is_capacity_error, parse_fallback
from temper_ai.llm.models import CallContext, LLMResponse
from temper_ai.llm.service import LLMService, ProviderErrorResponse
from temper_ai.llm.token_pool import _fmt
from temper_ai.observability import get_events

from .conftest import MockProvider

HOUR = 3600.0

# What the Claude CLI really handed back (llm.call.completed outputs of runs
# 99732fd1 and d2b4feb2, and of 95e242c1 and 023b82af).
RECORDED_LIMITS = [
    "You've hit your session limit \u00b7 resets 10:50pm (UTC)",
    "You've hit your session limit \u00b7 resets 6am (UTC)",
]
RECORDED_REFUSAL = (
    "Your organization has disabled Claude subscription access for Claude Code \u00b7 "
    "Use an Anthropic API key instead, or ask your admin to enable access"
)


def _answer(content, finish_reason="stop", model="mock-model"):
    return LLMResponse(content=content, model=model, provider="claude",
                       prompt_tokens=60, completion_tokens=40, total_tokens=100,
                       latency_ms=50, finish_reason=finish_reason)


def _error(content, model="mock-model"):
    return _answer(content, finish_reason="error", model=model)


class _Scripted(MockProvider):
    """A mock whose steps are responses, or callables run when the call reaches them."""

    def __init__(self, script):
        super().__init__([])
        self._script = list(script)

    def _next_response(self):
        if not self._script:
            raise RuntimeError("script exhausted")
        step = self._script.pop(0)
        return step() if callable(step) else step


class _Parked(list):
    now = 1_800_000_000.0


@pytest.fixture
def parked(monkeypatch):
    """The allowance park, measured instead of slept."""
    waits = _Parked()

    def fake_sleep_until(until, *, stop=None, **kw):
        waits.append(max(0.0, until - waits.now))
        waits.now = until
        return True

    monkeypatch.setattr(allowance, "sleep_until", fake_sleep_until)
    monkeypatch.setattr(allowance.time, "time", lambda: waits.now)
    return waits


def _run(service, execution_id):
    return service.run([{"role": "user", "content": "research the market"}],
                       context=CallContext(execution_id=execution_id, agent_name="brief",
                                           model="claude-opus-5-5"))


def _completed_outputs(execution_id):
    return [e["data"].get("response_content") for e in get_events(execution_id=execution_id)
            if e["type"] == "llm.call.completed"]


class TestAnErrorIsAFailedCall:
    def test_a_limit_goes_to_the_fallback_then_the_park_then_fails_and_never_completes(self, parked):
        exhausted = lambda: _error(  # noqa: E731 - built when the call is made, after the clock moved
            f"Error: claude token pool exhausted \u2014 all 3 tokens cooling; soonest reset {_fmt(parked.now + HOUR)}")
        own = _Scripted([_error(RECORDED_LIMITS[0]), exhausted, _error(RECORDED_LIMITS[1])])
        service = LLMService(own, fallbacks=parse_fallback(["claude-sonnet-5"]))

        with pytest.raises(ProviderErrorResponse) as raised:
            _run(service, "err-chain")

        # The banner sent the call to the next model on the list; that one was
        # out too, and named its reset, so the call waited for it; after the
        # wait the banner came back, naming no reset it could wait for.
        assert [c["kwargs"].get("model") for c in own.calls] == [
            "claude-opus-5-5", "claude-sonnet-5", "claude-sonnet-5"]
        assert parked == [pytest.approx(HOUR + allowance.WAKE_PAD_S)]
        assert "You've hit your session limit" in str(raised.value)
        assert is_capacity_error(raised.value)
        assert _completed_outputs("err-chain") == [], "no call completed on an error"

    def test_after_the_park_the_answer_is_the_steps(self, parked):
        own = _Scripted([
            lambda: _error("Error: claude token pool exhausted \u2014 all 3 tokens cooling; "
                           f"soonest reset {_fmt(parked.now + 2 * HOUR)}"),
            _answer("the market is growing"),
        ])
        result = _run(LLMService(own), "err-park")
        assert result.error is None
        assert result.output == "the market is growing"
        assert parked == [pytest.approx(2 * HOUR + allowance.WAKE_PAD_S)], "the allowance read the reset"

    @pytest.mark.parametrize("text", [
        "Error: Claude Code CLI timed out",
        "[claude_code error] stream ended with no result event",
        "",
    ], ids=["timeout", "no result event", "no text"])
    def test_a_plain_error_fails_at_once_and_is_not_capacity(self, parked, text):
        own = _Scripted([_error(text), _answer("never reached")])
        service = LLMService(own, fallbacks=parse_fallback(["claude-sonnet-5"]))

        with pytest.raises(ProviderErrorResponse) as raised:
            _run(service, "err-plain")

        assert not is_capacity_error(raised.value)
        assert len(own.calls) == 1, "not sent down the fallback list"
        assert parked == []

    def test_a_disabled_account_fails_and_never_parks(self, parked):
        own = _Scripted([_error(RECORDED_REFUSAL), _answer("never reached")])
        service = LLMService(own, fallbacks=parse_fallback(["claude-sonnet-5"]))

        with pytest.raises(ProviderErrorResponse) as raised:
            _run(service, "err-disabled")

        assert not is_capacity_error(raised.value), "no wait brings a disabled account back"
        assert len(own.calls) == 1
        assert parked == []

    @pytest.mark.parametrize("text", RECORDED_LIMITS)
    def test_both_recorded_banners_read_as_capacity(self, text):
        assert is_capacity_error(ProviderErrorResponse(_error(text)))
        assert is_capacity_error(RuntimeError(text))

    def test_the_error_names_the_provider_and_carries_the_response(self):
        response = _error(RECORDED_LIMITS[0])
        exc = ProviderErrorResponse(response)
        assert str(exc).startswith("claude answered with an error: You've hit your session limit")
        assert exc.llm_response is response
        assert allowance.reset_at(exc) is None, "a banner's local time is not read as a reset"


class TestAnAnswerIsAnAnswer:
    """The false-positive guard: the engine never reads an answer's words."""

    @pytest.mark.parametrize("text", [*RECORDED_LIMITS, RECORDED_REFUSAL])
    def test_an_answer_quoting_the_sentence_completes(self, parked, text):
        answer = (f"## What happened tonight\n\nThe account answered \"{text}\" and the step "
                  "completed at $0. It should have failed over to another account.")
        own = _Scripted([_answer(answer), _answer("never reached")])
        service = LLMService(own, fallbacks=parse_fallback(["claude-sonnet-5"]))

        result = _run(service, "ans-quote")

        assert result.error is None
        assert result.output == answer
        assert len(own.calls) == 1, "no fallback"
        assert parked == []

    @pytest.mark.parametrize("text", [*RECORDED_LIMITS, RECORDED_REFUSAL])
    def test_even_the_sentence_alone_is_left_to_the_provider(self, parked, text):
        # Telling a banner from an answer that is only that sentence takes the
        # call's own result (is the result the CLI's limit message?), which
        # only the provider has. The engine goes by the finish reason.
        result = _run(LLMService(_Scripted([_answer(text)])), "ans-alone")
        assert result.error is None
        assert result.output == text
        assert parked == []
