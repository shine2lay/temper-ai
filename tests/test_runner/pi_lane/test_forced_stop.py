"""A stop that needs force leaves none of the run's member boxes behind (the Pi lane).

A stop asks a run's process to end (SIGTERM), and the process ends its team, member boxes
included. A process that ignores that for the grace period is killed (SIGKILL) by the Pi lane's
reaper, which marks the run cancelled; the killed process never gets to remove its member boxes,
and Docker keeps them, since a member box is created without ``--rm``.

Here the reaper runs as pi-worker's watcher runs it (``Reaper(spawner, lane=PI_LANE)``, a tick
every 5 s, 30 s of grace), on a clock only the test moves. Docker is a fake that keeps a box
listed until something removes it, and the ledger holds the member turns a killed run process
leaves behind: running, each with its box's name. No model, no network and no real Docker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from temper_ai.runner.lanes import PI_LANE
from temper_ai.spawner import reaper as reaper_module
from temper_ai.spawner.reaper import Reaper
from tests.test_runner.pi_lane import support as ls

BOX_LEAD = "temper-pi-" + "1" * 20
BOX_BUILDER = "temper-pi-" + "2" * 20
BOX_OTHER = "temper-pi-" + "3" * 20  # a member box of another run, still at work
T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
TICK = timedelta(seconds=5)  # pi-worker's reaper pace (watch-queue --reaper-interval)


def _answer(code: int, out: str = "", err: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


class Docker:
    """The Docker CLI as Temper calls it, on boxes it keeps: ``docker kill`` only stops a box,
    which ``docker ps -a`` still lists until ``docker rm`` removes it. A name in ``broken`` gets
    only an error from the daemon."""

    def __init__(self, *running: str, broken: tuple[str, ...] = ()) -> None:
        self.boxes = dict.fromkeys(running, "running")
        self.broken = set(broken)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, timeout: float = 60) -> SimpleNamespace:
        self.calls.append(args)
        if args[0] == "ps":
            return _answer(0, "".join(f"{name}\n" for name in sorted(self.boxes)))
        name = args[-1]
        if name in self.broken:
            return _answer(1, err="Error response from daemon: i/o timeout")
        if args[0] == "inspect":
            if name not in self.boxes:
                return _answer(1, err=f"Error: No such container: {name}")
            return _answer(0, "true\n" if self.boxes[name] == "running" else "false\n")
        if args[0] == "kill":
            self.boxes[name] = "exited"
        elif args[0] == "rm":
            self.boxes.pop(name, None)
        return _answer(0)

    def listed(self) -> list[str]:
        """What ``docker ps -a --filter label=temper.pi.box=1`` shows: every member box,
        running or stopped."""
        return sorted(self.boxes)

    def touched(self) -> set[str]:
        """The boxes Docker was told to stop or remove."""
        return {c[-1] for c in self.calls if c[0] in ("kill", "rm")}


class Workers:
    """The Pi lane's run processes, by handle. Every one ignores SIGTERM: it lives until a
    SIGKILL."""

    def __init__(self) -> None:
        self.signals: dict[str, list[str]] = {}

    def is_alive(self, handle) -> bool:
        return "SIGKILL" not in self.signals.get(handle.handle, [])

    def kill(self, handle, *, force: bool = False) -> None:
        self.signals.setdefault(handle.handle, []).append("SIGKILL" if force else "SIGTERM")


@pytest.fixture
def clock(monkeypatch):
    """The reaper's clock (it reads ``datetime.now(UTC)``), moved only by the test."""
    now = SimpleNamespace(at=T0)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 - always UTC here
            return now.at

    monkeypatch.setattr(reaper_module, "datetime", Frozen)
    return now


@pytest.fixture
def ledger():
    """The ledger's tables, with no other test's turns (the tier keeps pi_ rows)."""
    from tests.test_pi_agent import support as sup

    sup.ledger()
    ls.empty_the_ledger()
    yield
    ls.empty_the_ledger()


def _docker(monkeypatch, fake: Docker) -> Docker:
    """Every Docker call of Temper's Pi code goes to ``fake``."""
    from temper_ai.pi_agent import box

    monkeypatch.setattr(box, "_docker_cli", fake)
    return fake


def _working(run_id: str, member: str, box_name: str) -> None:
    """A member's turn in flight as a killed run process leaves it: running, its box named."""
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import turns

    with get_database().engine.begin() as conn:
        conn.execute(turns.insert().values(
            turn_id=f"{run_id}-{member}-1", participant_id=f"{run_id}-{member}",
            run_id=run_id, host_path="team", turn_no=1, state="running", epoch=0,
            claimed_by="attempt-1", input_seqs=[], model_call_ids=[], effect_state="intent",
            refusals=[], box_name=box_name))


def _team_run(execution_id: str, handle: str, *, stop: bool, pi: bool = True) -> None:
    ls.make_row(execution_id, "lane_pi", status="running", spawner_kind="subprocess",
                handle=handle, cancel_requested=stop, started_at=T0, pi=pi)


def _reap_until_killed(reaper: Reaper, clock, workers: Workers, handle: str) -> datetime:
    """Tick at the reaper's pace until it kills ``handle``'s process; the time it did."""
    while True:
        reaper.tick()
        if workers.signals.get(handle, [])[-1:] == ["SIGKILL"]:
            return clock.at
        assert clock.at - T0 < timedelta(minutes=2), "the reaper never used force"
        clock.at += TICK


def test_a_forced_stop_leaves_none_of_the_run_s_member_boxes_a_minute_later(ledger, clock,
                                                                             monkeypatch):
    docker = _docker(monkeypatch, Docker(BOX_LEAD, BOX_BUILDER, BOX_OTHER))
    _team_run("team-stuck", "4242", stop=True)  # stopped; its process ignores the stop
    _team_run("team-other", "4343", stop=False)
    _working("team-stuck", "lead", BOX_LEAD)  # two members at work at once
    _working("team-stuck", "builder", BOX_BUILDER)
    _working("team-other", "lead", BOX_OTHER)
    workers = Workers()
    reaper = Reaper(workers, lane=PI_LANE)  # as pi-worker's watcher makes it

    forced_at = _reap_until_killed(reaper, clock, workers, "4242")
    while clock.at < forced_at + timedelta(seconds=60):
        clock.at += TICK
        reaper.tick()

    assert forced_at - T0 == timedelta(seconds=35), "SIGKILL at the first tick past 30 s"
    assert workers.signals == {"4242": ["SIGTERM", "SIGKILL"]}
    assert (ls.row("team-stuck").status, ls.row("team-other").status) == ("cancelled",
                                                                         "running")
    assert docker.listed() == [BOX_OTHER], "a minute after the forced end"
    assert docker.touched() <= {BOX_LEAD, BOX_BUILDER}, "only the stopped run's boxes"
    assert not [c for c in docker.calls if "prune" in c]


def test_a_box_already_gone_or_a_docker_error_still_ends_the_run_cancelled(ledger, clock,
                                                                           monkeypatch, caplog):
    # The lead's box is gone already; the daemon answers only errors about the builder's.
    docker = _docker(monkeypatch, Docker(BOX_BUILDER, BOX_OTHER, broken=(BOX_BUILDER,)))
    _team_run("team-stuck", "4242", stop=True)
    _working("team-stuck", "lead", BOX_LEAD)
    _working("team-stuck", "builder", BOX_BUILDER)
    _working("team-other", "lead", BOX_OTHER)
    workers = Workers()

    _reap_until_killed(Reaper(workers, lane=PI_LANE), clock, workers, "4242")

    assert ls.row("team-stuck").status == "cancelled"
    assert docker.listed() == [BOX_BUILDER, BOX_OTHER]
    assert docker.touched() == set(), "nothing to remove, and Docker couldn't say for the other"
    unsure = [r.getMessage() for r in caplog.records if "isn't confirmed gone" in r.getMessage()]
    assert len(unsure) == 1 and BOX_BUILDER in unsure[0] and "team-stuck" in unsure[0]


def test_the_main_lane_s_reaper_never_calls_docker_after_force(ledger, clock, monkeypatch):
    docker = _docker(monkeypatch, Docker(BOX_LEAD))
    _team_run("plain-stuck", "4242", stop=True, pi=False)
    _working("plain-stuck", "lead", BOX_LEAD)  # even with a box in the ledger under its id
    workers = Workers()

    _reap_until_killed(Reaper(workers), clock, workers, "4242")

    assert ls.row("plain-stuck").status == "cancelled"
    assert docker.calls == []
