"""The run waits fail on time without progress, not on time in all (#225).

pw.wait_parked and pw.wait_ended use cooperative inactivity deadlines. The newest event is
probed about once a second and again at expiry; a changed value extends the deadline, at most
to sup.PROGRESS_CAP from the start (an explicit longer initial timeout is retained). Synchronous
callbacks are not interrupted. Controlled runs at 15 % of one core reproduced a park phase
(~4 CPU-seconds) taking 31-40 s while it kept moving, beyond the old 20 s wait. This is measured
CPU sensitivity, not proof of the original failed attempt's unrecorded CPU allocation. A stopped
run still fails about its timeout after the last observed event; no-probe waits are unchanged.

A fake clock stands in for sup's ``time`` (only wait_for reads it on these paths): each sleep
moves it on, then plays the run's script due by then, so every case is exact and takes no
real seconds. The run is the test's own: its attempt rows and events go to the test's database
through the recorder, and while an attempt runs a thread named after the run holds it, as
in-process mode's run thread does.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterable
from itertools import pairwise
from types import SimpleNamespace

import pytest

from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import record, update_event
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_parking import support as pw

#: How late past the limit after the run's last event a wait that sees no more progress may
#: fail: up to one probe interval before it sees that event, plus a few polls.
LATE = sup.PROGRESS_EVERY + 0.1

Script = Iterable[tuple[float, Callable[[], object]]]


class FakeClock:
    """``time`` for sup.wait_for: ``sleep`` moves the clock on, then does what the script has
    due by then, in order."""

    def __init__(self, script: Script = ()):
        self.now = 0.0
        self.script: list[tuple[float, Callable[[], object]]] = []
        self.play(script)

    def play(self, script: Script) -> None:
        self.script = sorted([*self.script, *script], key=lambda step: step[0])

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        # Keep exact deadline equality distinct from a floating-point accumulation artifact.
        self.now = round(self.now + seconds, 8)
        assert self.now < 1000, "runaway wait: nothing stopped it"
        while self.script and self.script[0][0] <= self.now:
            self.script.pop(0)[1]()


class Run:
    """The test's stand-in run: one workflow.started row per attempt, an event each time it
    moves, and a thread named after it (pw.run_threads, sup.run_held) while an attempt runs."""

    def __init__(self):
        self.eid = str(uuid.uuid4())
        self.attempt = ""
        self.release = threading.Event()
        self.thread: threading.Thread | None = None

    def start_attempt(self) -> None:
        self.attempt = record(EventType.WORKFLOW_STARTED, execution_id=self.eid, status="running")
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.release.wait, name=f"temper-run-{self.eid}",
                                       daemon=True)
        self.thread.start()

    def move(self) -> None:
        record(EventType.AGENT_STARTED, execution_id=self.eid, status="running")

    def park(self) -> None:
        update_event(self.attempt, status="waiting", data={"parked": {"wait_id": "w-225"}})
        self.let_go()

    def end(self, status: str = "failed") -> None:
        update_event(self.attempt, status=status)
        self.let_go()

    def let_go(self) -> None:
        self.release.set()
        if self.thread is not None:
            self.thread.join(timeout=5)


@pytest.fixture
def run():
    stand_in = Run()
    stand_in.start_attempt()
    yield stand_in
    stand_in.let_go()


def moves(run: Run, start: float, stop: float, step: float) -> list[tuple[float, Callable]]:
    """The run records an event every ``step`` seconds from ``start`` to ``stop``."""
    count = int(round((stop - start) / step)) + 1
    return [(start + i * step, run.move) for i in range(count)]


def test_a_run_that_keeps_moving_past_the_limit_is_waited_for_until_it_parks_and_ends(
        monkeypatch, run):
    """The whole path, as a starved team run goes: attempt 1 moves for 42 s before it parks,
    and attempt 2 for 46 s before it ends. Each wait outlives its 20 s limit because the run
    kept recording events, and returns what it waited for."""
    clock = FakeClock([*moves(run, 5, 40, 5), (42, run.park)])
    with monkeypatch.context() as m:
        m.setattr(sup, "time", clock)
        attempt = pw.wait_parked(SimpleNamespace(running={}), run.eid)
        assert attempt["id"] == run.attempt and pw.parked(attempt) == {"wait_id": "w-225"}
        assert clock.now >= 42
        clock.play([(45, run.start_attempt), *moves(run, 50, 85, 5), (88, run.end)])
        attempts = pw.wait_ended(run.eid, 2)
    assert [a["status"] for a in attempts] == ["waiting", "failed"]
    assert clock.now >= 88


@pytest.mark.parametrize("kind", ["park", "end"])
def test_progress_just_before_expiry_counts_before_refusing(monkeypatch, run, kind):
    """A real recorder event between the last probe and expiry must buy time for readiness."""
    finish = run.park if kind == "park" else run.end
    clock = FakeClock([(19.99, run.move), (20.5, finish)])
    with monkeypatch.context() as m:
        m.setattr(sup, "time", clock)
        if kind == "park":
            result = pw.wait_parked(SimpleNamespace(running={}), run.eid)
            assert result["id"] == run.attempt and pw.parked(result)
        else:
            result = pw.wait_ended(run.eid, 1)
            assert result[-1]["id"] == run.attempt and result[-1]["status"] == "failed"
    assert clock.now == 20.5


def test_expiry_reconciles_progress_before_the_next_regular_probe(monkeypatch, run):
    """Poll/probe intervals need not divide the timeout: the final query may be sooner."""
    clock = FakeClock([(19.99, run.move)])
    asked: list[float] = []

    def probe():
        asked.append(clock.now)
        return sup.newest_event_id(run.eid)

    with monkeypatch.context() as m:
        m.setattr(sup, "time", clock)
        assert sup.wait_for(lambda: clock.now >= 20.5, every=0.03, progress=probe)
    assert clock.now == 20.52
    assert asked[-1] == 20.01
    assert asked[-1] - asked[-2] < sup.PROGRESS_EVERY
    assert all(b - a >= sup.PROGRESS_EVERY for a, b in pairwise(asked[:-1]))


@pytest.mark.parametrize("with_probe", [False, True])
@pytest.mark.parametrize("ready_at", [19.98, 20])
def test_expired_readiness_is_not_polled_without_new_progress(monkeypatch, with_probe, ready_at):
    """Reconciliation is not a final readiness poll; legacy no-probe ordering is unchanged."""
    clock = FakeClock()
    probe = (lambda: None) if with_probe else None
    with monkeypatch.context() as m:
        m.setattr(sup, "time", clock)
        if ready_at < 20:
            assert sup.wait_for(lambda: clock.now >= ready_at, progress=probe)
        else:
            with pytest.raises(AssertionError, match="timed out waiting for condition"):
                sup.wait_for(lambda: clock.now >= ready_at, progress=probe)
    assert clock.now == ready_at


def test_progress_at_the_cap_gets_no_extra_probe_or_readiness_poll(monkeypatch):
    clock = FakeClock()
    asked: list[float] = []

    def probe():
        asked.append(clock.now)
        return int(clock.now)

    with monkeypatch.context() as m, pytest.raises(AssertionError, match="still moving after 100 s"):
        m.setattr(sup, "time", clock)
        sup.wait_for(lambda: clock.now >= sup.PROGRESS_CAP, progress=probe)
    assert clock.now == sup.PROGRESS_CAP
    assert max(asked) < sup.PROGRESS_CAP


@pytest.mark.parametrize("moving", [False, True])
def test_a_longer_explicit_initial_timeout_is_not_shortened(monkeypatch, moving):
    """The extension cap is not an initial-timeout clamp; no current wrapper caller uses 120."""
    clock = FakeClock()
    with monkeypatch.context() as m, pytest.raises(AssertionError):
        m.setattr(sup, "time", clock)
        sup.wait_for(lambda: False, timeout=120,
                     progress=lambda: int(clock.now) if moving else None)
    assert clock.now == 120


def test_a_run_that_stops_moving_fails_the_limit_after_its_last_event(monkeypatch, run):
    """A frozen run (its last event at 7 s, never parked) fails the wait 20-21 s after that
    event, with the helper's message, as a hang did before."""
    clock = FakeClock(moves(run, 1, 7, 1))
    with monkeypatch.context() as m, pytest.raises(AssertionError) as failed:
        m.setattr(sup, "time", clock)
        pw.wait_parked(SimpleNamespace(running={}), run.eid)
    assert str(failed.value).startswith(
        f"timed out waiting for attempt 1 of {run.eid} to let go (no progress for 20 s,")
    assert 7 + 20 <= clock.now <= 7 + 20 + LATE

    run.end()
    clock = FakeClock([(1, run.move)])
    with monkeypatch.context() as m, pytest.raises(AssertionError, match="to end"):
        m.setattr(sup, "time", clock)
        pw.wait_ended(run.eid, 2)
    assert 1 + 20 <= clock.now <= 1 + 20 + LATE


def test_a_run_that_never_stops_moving_fails_at_the_cap_with_the_helpers_message(
        monkeypatch, run):
    clock = FakeClock(moves(run, 2, 300, 2))
    with monkeypatch.context() as m, pytest.raises(AssertionError) as failed:
        m.setattr(sup, "time", clock)
        pw.wait_parked(SimpleNamespace(running={}), run.eid)
    assert str(failed.value) == (f"timed out waiting for attempt 1 of {run.eid} to let go "
                                 f"(still moving after {sup.PROGRESS_CAP:.0f} s)")
    assert sup.PROGRESS_CAP <= clock.now <= sup.PROGRESS_CAP + 0.05


def test_a_wait_without_a_probe_still_fails_its_limit_after_it_started(monkeypatch, run):
    """sup.wait_for's other callers pass no probe: their limit is time in all, as before,
    whatever the run does meanwhile."""
    clock = FakeClock(moves(run, 1, 60, 1))
    with monkeypatch.context() as m, pytest.raises(AssertionError) as failed:
        m.setattr(sup, "time", clock)
        sup.wait_for(lambda: None, what="the thing")
    assert str(failed.value) == "timed out waiting for the thing"
    assert 20 <= clock.now <= 20 + 0.05


def test_the_probe_is_asked_about_once_a_second(monkeypatch):
    """The probe reads the database; the polls in between stay as cheap as before (#113)."""
    clock = FakeClock()
    asked: list[float] = []

    def probe() -> int:
        asked.append(clock.now)
        return len(asked)  # a new value each time: always moving

    with monkeypatch.context() as m:
        m.setattr(sup, "time", clock)
        assert sup.wait_for(lambda: clock.now >= 30, progress=probe)
    gaps = [later - earlier for earlier, later in pairwise(asked)]
    assert gaps and min(gaps) >= sup.PROGRESS_EVERY
    assert len(asked) <= 30 / sup.PROGRESS_EVERY + 1
