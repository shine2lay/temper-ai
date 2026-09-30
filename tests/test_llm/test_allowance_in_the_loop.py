"""The tool-calling loop parking for the allowance, and asking again after it.

:mod:`temper_ai.llm.allowance` decides *whether* to wait; this is what the loop
does with that decision -- park, wake, carry on with the same call and the same
transcript, and fail exactly as before when waiting is not on the table.

Nothing here sleeps for real: the wait is handed a clock and a sleep of the
test's own, so an hour-long park is a few microseconds.
"""

import threading

import httpx
import pytest

from temper_ai.llm import allowance
from temper_ai.llm.models import CallContext, LLMResponse
from temper_ai.llm.service import LLMService
from temper_ai.llm.token_pool import PoolExhausted
from temper_ai.observability import get_events

from .conftest import MockProvider

HOUR = 3600.0


def _text(content="Done", model="mock-model"):
    return LLMResponse(content=content, model=model, provider="MockProvider",
                       prompt_tokens=60, completion_tokens=40, total_tokens=100,
                       latency_ms=50, finish_reason="stop")


def _tool_call(model="mock-model"):
    return LLMResponse(content=None, model=model, provider="MockProvider",
                       prompt_tokens=60, completion_tokens=40, total_tokens=100,
                       latency_ms=50, finish_reason="tool_calls",
                       tool_calls=[{"id": "c1", "name": "bash", "arguments": "{}"}])


def _empty(model="mock-model"):
    """A call that spent its whole ceiling thinking: nothing to show for it."""
    return LLMResponse(content="", model=model, provider="MockProvider",
                       prompt_tokens=60, completion_tokens=40_000, total_tokens=40_060,
                       latency_ms=50, finish_reason="max_tokens")


class _Scripted(MockProvider):
    """A mock that raises where the script holds an exception.

    A step may be a callable, which is run when the call reaches it. That
    matters for the limits: an exception naming "an hour from now" has to be
    built when the call is made, not when the script is written, or the clock
    the park moves leaves every later reset in the past.
    """

    def __init__(self, script, name="mock", supports_tools=True, max_tokens=32_000):
        super().__init__([], max_tokens=max_tokens)
        self._script = list(script)
        self.PROVIDER_NAME = name
        self.SUPPORTS_TOOLS = supports_tools

    def _next_response(self):
        if not self._script:
            raise RuntimeError(f"{self.PROVIDER_NAME}: script exhausted")
        step = self._script.pop(0)
        if callable(step):
            step = step()
        if isinstance(step, BaseException):
            raise step
        return step


class _Parked(list):
    """Each park as the seconds it would have taken, plus the clock it moved."""

    now = 1_800_000_000.0


@pytest.fixture
def parked(monkeypatch):
    """A clock that jumps instead of a wait that sleeps.

    So a test can say "it waited an hour" without waiting one, and the park
    the loop takes is measured rather than slept.
    """
    waits = _Parked()

    def fake_sleep_until(until, *, stop=None, **kw):
        if stop is not None and stop.is_set():
            return False
        waits.append(max(0.0, until - waits.now))
        waits.now = until
        return True

    monkeypatch.setattr(allowance, "sleep_until", fake_sleep_until)
    monkeypatch.setattr(allowance.time, "time", lambda: waits.now)
    return waits


def _allowance_events(execution_id):
    return [e for e in get_events(execution_id=execution_id) if e["type"] == "llm.allowance"]


def _exhausted(parked, reset_in=HOUR, tokens=3):
    return PoolExhausted(tokens, parked.now + reset_in)


# -- parking and coming back ------------------------------------------------


class TestParkingForTheAllowance:
    def test_a_spent_allowance_waits_and_asks_again(self, parked):
        # The whole point: what used to end the agent now costs an hour.
        own = _Scripted([_exhausted(parked), _text("done after the wait")])
        service = LLMService(own)
        ctx = CallContext(execution_id="park-1", agent_name="a")

        result = service.run([{"role": "user", "content": "hi"}], context=ctx)

        assert result.error is None
        assert result.output == "done after the wait"
        assert len(parked) == 1

    def test_it_waits_until_the_reset_the_pool_named(self, parked):
        own = _Scripted([_exhausted(parked, reset_in=2 * HOUR), _text()])
        service = LLMService(own)

        service.run([{"role": "user", "content": "hi"}],
                    context=CallContext(execution_id="park-2", agent_name="a"))

        # The reset, plus the little pad that keeps it from waking into the
        # same refusal on a clock that is a moment fast.
        assert parked[0] == pytest.approx(2 * HOUR + allowance.WAKE_PAD_S)

    def test_the_run_carries_on_from_where_it_was(self, parked):
        # The transcript is untouched by the wait: the tool call made before
        # the limit is still there, and the answer after it is the run's.
        ran: list[str] = []
        own = _Scripted([_tool_call(), _exhausted(parked), _text("finished")])
        service = LLMService(own)

        result = service.run(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "bash"}}],
            execute_tool=lambda name, args: ran.append(name) or "ok",
            context=CallContext(execution_id="park-3", agent_name="a"),
        )

        assert result.error is None and result.output == "finished"
        assert ran == ["bash"]          # not run again after the wait
        # The park sits inside the call it saved, so it costs no iteration:
        # the tool turn, then the turn that waited and then answered.
        assert result.iterations == 2

    def test_the_park_is_recorded_so_the_page_can_show_it(self, parked):
        own = _Scripted([_exhausted(parked, reset_in=HOUR), _text()])
        service = LLMService(own)

        service.run([{"role": "user", "content": "hi"}],
                    context=CallContext(execution_id="park-4", agent_name="planner"))

        opened, closed = _allowance_events("park-4")
        assert opened["status"] == "waiting"
        assert opened["data"]["waiting_for"] == "1h"
        assert opened["data"]["until"].endswith("+00:00")
        assert opened["data"]["agent_name"] == "planner"
        assert closed["status"] == "completed"
        assert closed["parent_id"] == opened["id"]

    def test_a_park_that_is_still_open_is_what_the_badge_reads(self, parked):
        # The run page finds the newest event; while parked that is the open
        # one, and its `until` is the "back around 14:20" on the badge.
        own = _Scripted([_exhausted(parked), _text()])
        LLMService(own).run([{"role": "user", "content": "hi"}],
                            context=CallContext(execution_id="park-5", agent_name="a"))
        opened = _allowance_events("park-5")[0]
        assert opened["status"] == "waiting" and opened["data"]["until"]

    def test_the_wait_does_not_count_against_the_runs_own_timeout(self, parked):
        # An hour parked must not read as an hour of work: with the wait
        # counted, every park past the timeout would fail the run it saved.
        own = _Scripted([_exhausted(parked, reset_in=4 * HOUR), _text("done")])
        service = LLMService(own, total_timeout=300)

        result = service.run([{"role": "user", "content": "hi"}],
                             context=CallContext(execution_id="park-6", agent_name="a"))

        assert result.error is None and result.output == "done"


# -- when waiting is not on the table ---------------------------------------


class TestWhenItDoesNotWait:
    def test_a_reset_past_the_ceiling_fails_as_before(self, parked):
        # A weekly ceiling: three days is worse than failing now and resuming.
        own = _Scripted([_exhausted(parked, reset_in=3 * 24 * HOUR)])
        service = LLMService(own)

        with pytest.raises(PoolExhausted):
            service.run([{"role": "user", "content": "hi"}],
                        context=CallContext(execution_id="ceil-1", agent_name="a"))
        assert parked == []
        assert _allowance_events("ceil-1") == []

    def test_a_workflow_can_ask_for_longer(self, parked):
        own = _Scripted([_exhausted(parked, reset_in=20 * HOUR), _text("done")])
        service = LLMService(own)
        ctx = CallContext(execution_id="ceil-2", agent_name="a",
                          allowance_wait_max=2 * 24 * HOUR)

        assert service.run([{"role": "user", "content": "hi"}], context=ctx).output == "done"

    def test_a_workflow_can_switch_waiting_off(self, parked):
        own = _Scripted([_exhausted(parked, reset_in=60)])
        service = LLMService(own)
        ctx = CallContext(execution_id="ceil-3", agent_name="a", allowance_wait_max=0)

        with pytest.raises(PoolExhausted):
            service.run([{"role": "user", "content": "hi"}], context=ctx)
        assert parked == []

    def test_what_was_already_waited_counts_towards_the_ceiling(self, parked):
        # Three one-hour parks fit under six hours; the fourth, at four hours,
        # would not -- so it fails rather than stretch the ceiling by degrees.
        # Each refusal is built when the call reaches it, so "an hour from
        # now" means an hour from the clock the last park moved.
        own = _Scripted([
            lambda: _exhausted(parked, reset_in=HOUR),
            lambda: _exhausted(parked, reset_in=HOUR),
            lambda: _exhausted(parked, reset_in=HOUR),
            lambda: _exhausted(parked, reset_in=4 * HOUR),
        ])
        service = LLMService(own)

        with pytest.raises(PoolExhausted):
            service.run([{"role": "user", "content": "hi"}],
                        context=CallContext(execution_id="ceil-4", agent_name="a"))
        assert len(parked) == 3

    def test_an_ordinary_failure_is_not_waited_for(self, parked):
        # Not an allowance that comes back: it must fail exactly as it does now.
        request = httpx.Request("POST", "http://llm/v1")
        boom = httpx.HTTPStatusError(
            "500", request=request, response=httpx.Response(500, request=request))
        service = LLMService(_Scripted([boom]))

        with pytest.raises(httpx.HTTPStatusError):
            service.run([{"role": "user", "content": "hi"}],
                        context=CallContext(execution_id="ord-1", agent_name="a"))
        assert parked == []

    def test_a_limit_naming_no_reset_fails_as_before(self, parked):
        # Out of capacity, but nothing says when it comes back: there is no
        # moment to wake at, so waiting would be guessing.
        service = LLMService(_Scripted([PoolExhausted(3, None)]))

        with pytest.raises(PoolExhausted):
            service.run([{"role": "user", "content": "hi"}],
                        context=CallContext(execution_id="ord-2", agent_name="a"))
        assert parked == []

    def test_the_fallback_list_is_tried_before_any_waiting(self, parked):
        # Another account now beats the same account in an hour.
        from temper_ai.llm.fallback import parse_fallback

        own = _Scripted([_exhausted(parked), _text("from sonnet", model="claude-sonnet-5")])
        service = LLMService(own, fallbacks=parse_fallback(["claude-sonnet-5"]))

        result = service.run([{"role": "user", "content": "hi"}],
                             context=CallContext(execution_id="fb-park", agent_name="a",
                                                 model="claude-opus-5-5"))

        assert result.output == "from sonnet"
        assert parked == []

    def test_a_stopped_run_stops_waiting_and_fails_as_before(self, parked, monkeypatch):
        monkeypatch.setattr(allowance, "sleep_until", lambda *a, **k: False)
        stop = threading.Event()
        service = LLMService(_Scripted([_exhausted(parked)]))
        ctx = CallContext(execution_id="stop-1", agent_name="a", cancel_event=stop)

        with pytest.raises(PoolExhausted):
            service.run([{"role": "user", "content": "hi"}], context=ctx)

        opened, closed = _allowance_events("stop-1")
        assert opened["status"] == "waiting"
        assert closed["status"] == "cancelled"


# -- the empty answer -------------------------------------------------------


class TestTheEmptyAnswer:
    def test_it_is_asked_once_more_with_more_room(self):
        own = _Scripted([_empty(), _text("this time with room")], max_tokens=32_000)
        service = LLMService(own)

        result = service.run([{"role": "user", "content": "hi"}],
                             context=CallContext(execution_id="room-1", agent_name="a"))

        assert result.error is None and result.output == "this time with room"
        assert own.calls[0]["kwargs"].get("max_tokens") is None   # the agent's own
        assert own.calls[1]["kwargs"]["max_tokens"] == 64_000     # doubled, that call only

    def test_only_once(self):
        # A budget the agent is set up with, not bad luck: a third full-price
        # think buys nothing the second did not, and costs the same.
        own = _Scripted([_empty(), _empty()])
        service = LLMService(own)

        result = service.run([{"role": "user", "content": "hi"}],
                             context=CallContext(execution_id="room-2", agent_name="a"))

        assert "hit max_tokens before any text was returned" in result.error
        assert len(own.calls) == 2

    def test_the_retry_is_recorded_with_the_room_it_was_given(self):
        own = _Scripted([_empty(), _text()], max_tokens=32_000)
        LLMService(own).run([{"role": "user", "content": "hi"}],
                            context=CallContext(execution_id="room-3", agent_name="a"))

        retries = [e for e in get_events(execution_id="room-3")
                   if e["type"] == "llm.iteration" and e["data"]["action"] == "output_limit_retry"]
        assert len(retries) == 1
        assert retries[0]["data"]["extra_room"] == 64_000

    def test_both_calls_are_paid_for(self):
        # The retry is a real call at a real price; the run's cost says so.
        own = _Scripted([_empty(), _text()])
        result = LLMService(own).run([{"role": "user", "content": "hi"}],
                                     context=CallContext(execution_id="room-4", agent_name="a"))

        calls = [e for e in get_events(execution_id="room-4") if e["type"] == "llm.call.completed"]
        assert len(calls) == 2
        assert result.tokens == 40_060 + 100

    def test_a_later_empty_answer_gets_its_own_retry(self):
        # The count is per stumble, not per run: an agent that answered in
        # between has shown the ceiling is workable.
        own = _Scripted([_empty(), _tool_call(), _empty(), _text("done")])
        service = LLMService(own)

        result = service.run(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "bash"}}],
            execute_tool=lambda name, args: "ok",
            context=CallContext(execution_id="room-5", agent_name="a"),
        )

        assert result.error is None and result.output == "done"

    def test_a_provider_that_will_not_take_the_raised_ceiling_is_asked_again_without_it(self):
        # Some models cap max_tokens below twice the agent's. The retry exists
        # to save the call, so a refused raise must not be what loses it.
        refusal = httpx.HTTPStatusError(
            "max_tokens: 64000 > 32000, which is the maximum allowed",
            request=httpx.Request("POST", "http://llm/v1"),
            response=httpx.Response(400, request=httpx.Request("POST", "http://llm/v1")))
        own = _Scripted([_empty(), refusal, _text("done anyway")], max_tokens=32_000)
        service = LLMService(own)

        result = service.run([{"role": "user", "content": "hi"}],
                             context=CallContext(execution_id="room-6", agent_name="a"))

        assert result.error is None and result.output == "done anyway"
        assert own.calls[2]["kwargs"].get("max_tokens") is None

    def test_an_answer_that_ran_out_of_room_is_kept_not_retried(self):
        # Truncated but not empty: the words it did produce are the answer.
        # Only a call with *nothing* to show is worth asking again.
        cut = LLMResponse(content="half an ans", model="m", provider="MockProvider",
                          prompt_tokens=10, completion_tokens=10, total_tokens=20,
                          latency_ms=5, finish_reason="max_tokens")
        own = _Scripted([cut])

        result = LLMService(own).run([{"role": "user", "content": "hi"}],
                                     context=CallContext(execution_id="room-7", agent_name="a"))

        assert result.error is None and result.output == "half an ans"
        assert len(own.calls) == 1
