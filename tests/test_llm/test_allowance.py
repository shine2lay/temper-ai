"""Waiting for the model allowance instead of dying with it.

Every account has a ceiling, and when all of them are spent at once the pool
refuses -- naming the moment the allowance reopens. Eight steps died that way
in eight days, each needing a person to notice and press Resume, and each time
the thing they were waiting for came back on its own within the hour.

So the run waits. These are the rules of that wait: which refusals are worth
waiting for, how long, and what stops it.
"""

import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from temper_ai.llm import allowance
from temper_ai.llm.token_pool import PoolExhausted, TokenCooling

HOUR = 3600.0
NOW = 1_800_000_000.0   # a fixed "now", so no test depends on the wall clock


def _exhausted(reset_in: float, tokens: int = 3) -> PoolExhausted:
    """The pool's own refusal, as it raises it: all accounts cooling, reset named."""
    return PoolExhausted(tokens, NOW + reset_in)


def _http_error(status: int, headers: dict[str, str]) -> httpx.HTTPStatusError:
    """A provider's own refusal, with the headers it came back with."""
    request = httpx.Request("POST", "http://llm/v1")
    return httpx.HTTPStatusError(
        f"Error code: {status} - rate_limit_error", request=request,
        response=httpx.Response(status, request=request, headers=headers))


# -- which refusals name a moment we can wait for ---------------------------


class TestReadingTheReset:
    def test_the_pools_refusal_carries_it(self):
        assert allowance.reset_at(_exhausted(HOUR)) == NOW + HOUR

    def test_a_cooling_token_carries_it_too(self):
        # One account limited, raised when it is the only one the call may use.
        exc = TokenCooling("work", "claude-opus-5-5", NOW + 900)
        assert allowance.reset_at(exc) == NOW + 900

    def test_a_datetime_is_read_as_well_as_a_number(self):
        exc = RuntimeError("limited")
        exc.reset_at = datetime.fromtimestamp(NOW + 120, tz=UTC)
        assert allowance.reset_at(exc) == pytest.approx(NOW + 120)

    def test_a_message_naming_the_reset_is_read_when_nothing_carries_it(self):
        # A provider that wraps the pool's refusal loses the attribute but
        # keeps the words -- and the words say when.
        exc = RuntimeError(
            "call failed: token pool exhausted — all 3 tokens cooling; "
            "soonest reset 2026-09-26 14:00Z",
        )
        assert allowance.reset_at(exc) == datetime(2026, 9, 26, 14, 0, tzinfo=UTC).timestamp()

    def test_an_ordinary_failure_names_no_moment(self):
        # Nothing to wait for: this is not an allowance that comes back.
        assert allowance.reset_at(RuntimeError("connection reset by peer")) is None

    def test_a_plain_rate_limit_names_it_in_its_headers(self):
        # "This request would exceed your account's rate limit. Please try
        # again later." -- no time in the body, and three steps died on it in
        # eight days. The headers say when; it is usually seconds away.
        exc = _http_error(429, {"retry-after": "45"})
        assert allowance.reset_at(exc) == pytest.approx(time.time() + 45, abs=2)

    def test_anthropics_unified_reset_is_read_as_a_moment(self):
        exc = _http_error(429, {"anthropic-ratelimit-unified-reset": "2026-09-26T14:00:00Z"})
        assert allowance.reset_at(exc) == datetime(2026, 9, 26, 14, 0, tzinfo=UTC).timestamp()

    def test_a_wild_retry_after_is_not_believed(self):
        # A header is one call's hint, not the pool's record. A month is not a
        # hint; fall through rather than park a run on it.
        assert allowance.reset_at(_http_error(429, {"retry-after": "2600000"})) is None

    def test_a_header_that_is_not_a_time_is_ignored(self):
        assert allowance.reset_at(_http_error(429, {"retry-after": "soonish"})) is None

    def test_what_the_pool_itself_says_beats_a_header(self):
        # The pool knows every account; a header knows one call.
        exc = _http_error(429, {"retry-after": "45"})
        exc.reset_at = NOW + 900
        assert allowance.reset_at(exc) == NOW + 900

    def test_a_reset_that_is_not_a_time_is_ignored(self):
        exc = RuntimeError("limited")
        exc.reset_at = "soon"
        assert allowance.reset_at(exc) is None

    def test_a_malformed_date_in_the_message_is_ignored(self):
        assert allowance.reset_in_text("soonest reset 2026-13-45 99:99Z") is None


# -- the decision: park, or fail as before ----------------------------------


class TestDeciding:
    def test_a_reset_within_the_ceiling_is_waited_for(self):
        wait = allowance.decide(_exhausted(HOUR), now=NOW, max_wait=6 * HOUR)
        assert wait is not None
        assert wait.seconds == pytest.approx(HOUR + allowance.WAKE_PAD_S)

    def test_the_wake_is_a_little_past_the_reset(self):
        # Waking on the second of the reset walks into the same refusal when
        # our clock is a moment fast; the pool pads its own cooling the same way.
        wait = allowance.decide(_exhausted(HOUR), now=NOW)
        assert wait.until == NOW + HOUR + allowance.WAKE_PAD_S

    def test_a_reset_past_the_ceiling_fails_as_before(self):
        # A weekly ceiling is days out. A run holding its place for three days
        # is worse than one that fails now and is resumed on Monday.
        assert allowance.decide(_exhausted(3 * 24 * HOUR), now=NOW, max_wait=6 * HOUR) is None

    def test_the_ceiling_is_against_the_wait_not_the_clock(self):
        # Just inside and just outside, with the pad counted in both.
        under = 6 * HOUR - allowance.WAKE_PAD_S - 1
        assert allowance.decide(_exhausted(under), now=NOW, max_wait=6 * HOUR) is not None
        assert allowance.decide(_exhausted(under + 2), now=NOW, max_wait=6 * HOUR) is None

    def test_what_was_already_waited_counts_towards_the_ceiling(self):
        # Otherwise a reset time that keeps being wrong parks the same call
        # again and again, an hour at a time, forever.
        exc = _exhausted(HOUR)
        assert allowance.decide(exc, now=NOW, max_wait=6 * HOUR, already_waited=4 * HOUR) is not None
        assert allowance.decide(exc, now=NOW, max_wait=6 * HOUR, already_waited=5.5 * HOUR) is None

    def test_a_failure_naming_no_moment_is_never_waited_for(self):
        # The point of the wait is that the thing comes back by itself. A
        # refusal that names no moment is not that, and must fail as it does now.
        assert allowance.decide(RuntimeError("500 internal error"), now=NOW) is None

    def test_a_workflow_can_switch_waiting_off(self):
        assert allowance.decide(_exhausted(60), now=NOW, max_wait=0) is None

    def test_a_reset_already_past_still_waits_a_little(self):
        # The provider says the ceiling reopened a minute ago and refuses
        # anyway. Asking again this instant costs a call and learns nothing.
        wait = allowance.decide(_exhausted(-60), now=NOW)
        assert wait.seconds == pytest.approx(allowance.MIN_WAIT_S)

    def test_the_default_ceiling_is_six_hours(self):
        assert allowance.DEFAULT_MAX_WAIT == timedelta(hours=6)


# -- the wait itself --------------------------------------------------------


class TestTheWait:
    def test_it_sleeps_until_the_moment_and_no_longer(self):
        slept: list[float] = []
        clock = [NOW]

        def sleep(s):
            slept.append(s)
            clock[0] += s

        assert allowance.sleep_until(NOW + 12, sleep=sleep, now=lambda: clock[0], slice_s=5) is True
        assert sum(slept) == pytest.approx(12)

    def test_it_sleeps_in_slices_rather_than_one_long_sleep(self):
        # So a stopped run is noticed within seconds, not at the reset.
        slept: list[float] = []
        clock = [NOW]

        def sleep(s):
            slept.append(s)
            clock[0] += s

        allowance.sleep_until(NOW + HOUR, sleep=sleep, now=lambda: clock[0], slice_s=5)
        assert max(slept) <= 5

    def test_a_stopped_run_stops_waiting(self):
        stop = threading.Event()
        stop.set()
        calls: list[float] = []
        assert allowance.sleep_until(
            NOW + HOUR, stop=stop, sleep=calls.append, now=lambda: NOW,
        ) is False
        assert calls == []   # not even one slice

    def test_stopping_part_way_through_is_noticed(self):
        stop = threading.Event()
        clock = [NOW]
        slept: list[float] = []

        def sleep(s):
            slept.append(s)
            clock[0] += s
            if len(slept) == 3:
                stop.set()

        assert allowance.sleep_until(
            NOW + HOUR, stop=stop, sleep=sleep, now=lambda: clock[0], slice_s=5,
        ) is False
        assert len(slept) == 3   # stopped at the next look, not at the reset

    def test_a_moment_already_past_returns_at_once(self):
        calls: list[float] = []
        assert allowance.sleep_until(NOW - 5, sleep=calls.append, now=lambda: NOW) is True
        assert calls == []

    def test_it_does_not_poll_anything(self):
        # The wait asks nobody for anything: it sleeps and looks at a flag.
        # (A tight poll against the pool is what this replaces.)
        started = time.monotonic()
        allowance.sleep_until(time.time() + 0.05, slice_s=0.01)
        assert time.monotonic() - started < 1.0


# -- how long, in words -----------------------------------------------------


class TestSayingHowLong:
    @pytest.mark.parametrize("seconds, words", [
        (0, "under a minute"),
        (59, "under a minute"),
        (60, "1m"),
        (45 * 60, "45m"),
        (3600, "1h"),
        (8040, "2h 14m"),
    ])
    def test_it_reads_as_a_person_would_say_it(self, seconds, words):
        assert allowance.how_long(seconds) == words

    def test_a_wait_describes_itself(self):
        wait = allowance.Wait(until=datetime(2026, 9, 26, 14, 20, tzinfo=UTC).timestamp(),
                              seconds=2 * HOUR)
        assert "2h" in str(wait)
        assert "14:20" in str(wait)


# -- the ceiling a workflow asks for ----------------------------------------


class TestTheWorkflowsCeiling:
    @pytest.fixture(autouse=True)
    def _clean(self):
        allowance.forget_settings()
        yield
        allowance.forget_settings()

    def _says(self, monkeypatch, value):
        monkeypatch.setattr(allowance, "_read_setting", lambda name: value)

    def test_a_workflow_that_says_nothing_gets_the_default(self, monkeypatch):
        self._says(monkeypatch, None)
        assert allowance.max_wait_for("epd_loop") == 6 * HOUR

    def test_a_workflow_can_sit_out_a_weekly_reset(self, monkeypatch):
        self._says(monkeypatch, "2d")
        assert allowance.max_wait_for("epd_loop") == 2 * 24 * HOUR

    @pytest.mark.parametrize("off", [0, "0", False])
    def test_a_workflow_can_switch_waiting_off(self, monkeypatch, off):
        self._says(monkeypatch, off)
        assert allowance.max_wait_for("w") == 0.0

    def test_a_setting_nobody_can_read_falls_back_to_the_default(self, monkeypatch):
        # A typo in one workflow must not stop every run from waiting.
        self._says(monkeypatch, "whenever")
        assert allowance.max_wait_for("w") == 6 * HOUR

    def test_a_config_that_cannot_be_read_falls_back_to_the_default(self, monkeypatch):
        # No config store, or a store that is down: the default, not a failure.
        def boom(self, name, kind):
            raise RuntimeError("no config store here")
        monkeypatch.setattr("temper_ai.config.store.ConfigStore.get", boom)
        assert allowance.max_wait_for("w") == 6 * HOUR

    def test_the_setting_is_read_from_a_file_written_either_way(self, monkeypatch):
        # The store hands workflow files back with their outer `workflow:` key
        # and agent files back without one. Reading only the top level is what
        # once put every workflow quietly back on the default.
        for shape in ({"workflow": {"wait_for_allowance": "90m"}}, {"wait_for_allowance": "90m"}):
            allowance.forget_settings()
            monkeypatch.setattr("temper_ai.config.store.ConfigStore.get",
                                lambda self, name, kind, _s=shape: _s)
            assert allowance.max_wait_for("w") == 90 * 60

    def test_it_is_not_read_again_on_every_call(self, monkeypatch):
        # A run parking at four agents at once should not read the same file
        # four times; an edited workflow still takes effect within the minute.
        reads: list[str] = []
        monkeypatch.setattr(allowance, "_read_setting", lambda name: reads.append(name) or "3h")
        assert allowance.max_wait_for("w") == 3 * HOUR
        assert allowance.max_wait_for("w") == 3 * HOUR
        assert reads == ["w"]
