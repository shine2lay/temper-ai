"""The Pi lane stopping and starting again (item 8, ADR-M4-06, SW-49).

On SIGTERM the Pi lane's watcher claims nothing more, raises the drain mark and waits for its
runs to leave at their next turn boundary (pi-worker's stop_grace_period covers the wait).
At its next start it sweeps leftover member boxes by exact name, puts back the runs its last
instance claimed but never started, and ends the ones it was running, so that the pick-up
carries them on from the ledger (tests/test_runner/pi_parking/test_pi_lane_restarts.py runs
that end to end).
"""

from __future__ import annotations

import argparse
import signal
from types import SimpleNamespace

import pytest

from temper_ai.cli import watch_queue as wq
from temper_ai.runner import pi_lane
from temper_ai.runner.lanes import PI_LANE
from temper_ai.worker_proto import SpawnerKind
from tests.test_runner.pi_lane import support as ls

BOX_A = "temper-pi-" + "a" * 20
BOX_B = "temper-pi-" + "b" * 20
BOX_C = "temper-pi-" + "c" * 20


@pytest.fixture
def mark(tmp_path, monkeypatch):
    path = tmp_path / "drain" / "draining"
    monkeypatch.setenv(pi_lane.DRAIN_MARK_ENV, str(path))
    return path


class Live:
    """A spawner's live runs: each call answers the next list, then the last one again."""

    def __init__(self, *answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.kind = SpawnerKind.subprocess

    def live_runs(self) -> list[str]:
        self.calls += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s

    def __call__(self) -> float:
        return self.now


# --- The mark --------------------------------------------------------------------------------


def test_the_mark_reaches_only_the_pi_lane_s_runs(mark, monkeypatch):
    pi_lane.set_draining()
    assert mark.exists()
    assert not pi_lane.draining()  # not the Pi lane: never drains
    pi_lane.leave_if_draining("step talk")
    ls.as_the_pi_lane(monkeypatch)
    assert pi_lane.draining()
    with pytest.raises(pi_lane.LaneDrained) as left:
        pi_lane.leave_if_draining("step talk")
    assert str(left.value) == "step talk"
    # Not an Exception: no step's ``except Exception`` turns leaving into a failure.
    assert not isinstance(left.value, Exception)


def test_without_a_mark_set_nothing_drains(monkeypatch):
    monkeypatch.delenv(pi_lane.DRAIN_MARK_ENV, raising=False)
    ls.as_the_pi_lane(monkeypatch)
    pi_lane.set_draining()
    assert not pi_lane.draining()


def test_the_watcher_s_start_clears_a_mark_left_from_before(mark):
    mark.parent.mkdir(parents=True)
    mark.write_text("old")
    assert pi_lane.arm_drain_mark() == mark
    assert not mark.exists()


def test_the_watcher_s_start_picks_a_mark_its_runs_inherit(tmp_path, monkeypatch):
    monkeypatch.delenv(pi_lane.DRAIN_MARK_ENV, raising=False)
    monkeypatch.setattr(pi_lane.tempfile, "gettempdir", lambda: str(tmp_path))
    path = pi_lane.arm_drain_mark()
    assert path == tmp_path / "temper-pi-lane" / "draining"
    import os

    assert os.environ[pi_lane.DRAIN_MARK_ENV] == str(path)


# --- Draining --------------------------------------------------------------------------------


def test_drain_raises_the_mark_and_waits_for_the_runs_to_leave(mark):
    clock, live = Clock(), Live(["r1", "r2"], ["r2"], [])
    assert pi_lane.drain(live, deadline_s=60, poll_s=1, sleep=clock.sleep, clock=clock) == []
    assert mark.exists()
    assert clock.slept == [1, 1]


def test_drain_gives_up_at_its_deadline_and_says_which_runs_were_left(mark, caplog):
    clock, live = Clock(), Live(["r1"])
    assert pi_lane.drain(live, deadline_s=5, poll_s=1, sleep=clock.sleep, clock=clock) == ["r1"]
    assert len(clock.slept) == 5
    assert "The Pi lane stopped with r1 still going; the next start picks them up" in \
        caplog.text


def test_drain_with_no_runs_returns_at_once(mark):
    clock = Clock()
    assert pi_lane.drain(Live([]), sleep=clock.sleep, clock=clock) == []
    assert clock.slept == [] and mark.exists()


def test_the_default_deadline_fits_inside_pi_worker_s_stop_grace_period():
    from tests.test_runner.pi_lane.test_compose import GRACE_S, pi_worker

    assert pi_lane.DRAIN_DEADLINE_S < GRACE_S == pi_worker()["stop_grace_period_s"]


def test_on_sigterm_the_pi_lane_claims_nothing_more_and_drains(tmp_path, mark, monkeypatch):
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{tmp_path / 'watch.db'}")
    monkeypatch.setenv("TEMPER_LANE", PI_LANE)
    monkeypatch.setenv("TEMPER_PI_AGENT", "1")
    live = Live(["run-1"], [])
    monkeypatch.setattr(wq, "get_spawner", lambda: live)
    monkeypatch.setattr(pi_lane, "eager_import", lambda: (0, []))
    monkeypatch.setattr(pi_lane, "start_up", lambda: {})
    monkeypatch.setattr(wq, "_requeue_stuck_claims", lambda spawner, lane=None: 0)
    reaper = SimpleNamespace(started=False, stopped=False)
    monkeypatch.setattr(wq, "Reaper", lambda *a, **kw: SimpleNamespace(
        start=lambda: setattr(reaper, "started", True),
        stop=lambda: setattr(reaper, "stopped", True)))
    scans: list[str | None] = []

    def scan(spawner, lane=None):
        scans.append(lane)
        signal.raise_signal(signal.SIGTERM)  # docker stop, while the lane is claiming
        return 0

    monkeypatch.setattr(wq, "_scan_and_dispatch", scan)
    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        code = wq.cmd_watch_queue(argparse.Namespace(poll_interval=0.01, reaper_interval=60))
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)
    assert code == 0
    assert scans == [PI_LANE], "it claimed again after the signal"
    assert mark.exists() and live.calls == 2  # the mark went up, and it waited for run-1
    assert reaper.started and reaper.stopped


# --- The start-up pass -----------------------------------------------------------------------


class Docker:
    """The Docker CLI as the sweep uses it: lists labelled boxes, removes them by name."""

    def __init__(self, listed: list[str], *, fail: bool = False) -> None:
        self.listed = listed
        self.present = set(listed)
        self.calls: list[tuple[str, ...]] = []
        self.fail = fail

    def __call__(self, *args: str, timeout: float = 60) -> SimpleNamespace:
        self.calls.append(args)
        if self.fail:
            raise OSError("docker: not found")
        if args[0] == "ps":
            return SimpleNamespace(returncode=0, stdout="\n".join(self.listed) + "\n",
                                   stderr="")
        name = args[-1]
        if args[0] == "inspect":
            if name in self.present:
                return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
            return SimpleNamespace(returncode=1, stdout="",
                                   stderr=f"Error: No such container: {name}")
        if args[0] == "rm":
            self.present.discard(name)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _turn(run_id: str, n: int, state: str, box: str | None) -> None:
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import turns

    with get_database().engine.begin() as conn:
        conn.execute(turns.insert().values(
            turn_id=f"sweep-{run_id}-{n}", participant_id="p-1", run_id=run_id,
            host_path="talk", turn_no=n, state=state, epoch=0, claimed_by="host",
            input_seqs=[], model_call_ids=[], effect_state="intent", refusals=[],
            box_name=box))


@pytest.fixture
def clean_turns():
    """The tier keeps pi_ rows between tests: none of another test's turns here."""
    from tests.test_pi_agent import support as sup

    sup.ledger()
    ls.empty_the_ledger()
    yield
    ls.empty_the_ledger()


def test_the_start_up_sweeps_leftover_member_boxes_by_exact_name(clean_turns):
    _turn("r1", 1, "running", BOX_A)       # an unsettled turn's box
    _turn("r1", 2, "uncertain", BOX_B)
    _turn("r2", 1, "completed", BOX_C)     # settled: its box is not looked at by the ledger
    docker = Docker([BOX_A, "temper-pi-sidecar", "temper-run-xyz"])
    out = pi_lane.start_up(docker=docker)
    assert [b["box"] for b in out["boxes"]] == [BOX_A, BOX_B]
    assert [b["confirmed"] for b in out["boxes"]] == [True, True]
    assert ("ps", "-a", "--filter", "label=temper.pi.box=1", "--format", "{{.Names}}") in \
        docker.calls
    assert ("rm", "--force", BOX_A) in docker.calls
    touched = {c[-1] for c in docker.calls if c[0] != "ps"}
    assert touched == {BOX_A, BOX_B}, "only member boxes, each by its exact name"
    assert not [c for c in docker.calls if "prune" in c]


def test_the_start_up_puts_back_and_ends_only_the_pi_lane_s_runs(clean_turns):
    ls.make_row("pi-claimed", status="queued", spawner_kind="subprocess", handle="__claiming__")
    ls.make_row("pi-running", status="running", spawner_kind="subprocess", handle="4242")
    ls.make_row("plain-claimed", "lane_plain", pi=False, status="queued",
                spawner_kind="docker", handle="__claiming__")
    ls.make_row("plain-running", "lane_plain", pi=False, status="running",
                spawner_kind="docker", handle="temper-run-plain")
    out = pi_lane.start_up(docker=Docker([]))
    assert out["requeued"] == 1
    claimed = ls.row("pi-claimed")
    assert (claimed.status, claimed.spawner_kind, claimed.spawner_handle) == ("queued", None,
                                                                            None)
    assert ls.lane("pi-claimed") == PI_LANE
    ended = ls.row("pi-running")
    assert ended.status == "orphaned" and ended.error["kind"] == "orphaned"
    assert ls.row("plain-claimed").spawner_kind == "docker"
    assert ls.row("plain-running").status == "running"


def test_the_start_up_never_raises_when_docker_fails(clean_turns, caplog):
    _turn("r1", 1, "running", BOX_A)
    ls.make_row("pi-claimed", status="queued", spawner_kind="subprocess", handle="__claiming__")
    out = pi_lane.start_up(docker=Docker([], fail=True))
    assert out["boxes"] == [] and out["requeued"] == 1
    assert "Pi lane: sweeping leftover member boxes failed" in caplog.text
