"""What temper-ci does once master has moved.

Restart, look at the live thing, and if it is unwell put master back. Nothing
here starts a container or restarts anything: temper-deploy, git and the DM
are all stood in for, so what is tested is the *decisions* — which is where a
rollback either saves the day or makes it worse.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def dep(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPER_CI_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("TEMPER_CI_REPORTS", str(tmp_path / "reports"))
    # No real checkout is asked anything: git pointed here finds no repository.
    monkeypatch.setenv("TEMPER_CI_MAIN", str(tmp_path / "no-repo"))
    for name in [m for m in sys.modules if m.startswith("temper_ci")]:
        del sys.modules[name]
    from temper_ci import deploy, paths  # noqa: PLC0415

    paths.ensure_dirs()
    monkeypatch.setattr(deploy, "LAST_RESTART", tmp_path / "last-restart.json")
    monkeypatch.setattr(deploy, "RESTART_REQUEST", tmp_path / "request.json")
    return deploy, tmp_path


def _restarted(deploy, tmp_path, when: dt.datetime, head: str = "abc1234") -> None:
    """Stand in for temper-deploy having restarted."""
    (tmp_path / "last-restart.json").write_text(
        f'{{"at": "{when.isoformat()}", "head": "{head}", "problems": []}}', encoding="utf-8")


def test_the_first_time_it_looks_a_checked_master_becomes_the_good_one(dep, monkeypatch):
    """With no record yet, master is not a change to deploy \u2014 it is where we
    already are, and the thing a later rollback goes back to. But only if the
    gate has passed it: see the test below for the day the gate is installed."""
    deploy, _ = dep
    monkeypatch.setattr(deploy, "master_sha", lambda: "1" * 40)
    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: {"ok": True})
    assert deploy.watch_master() is None
    assert deploy.state()["last_good"] == "1" * 40
    assert deploy.state()["deployed"] == "1" * 40


def test_a_restart_that_never_happens_rolls_nothing_back(dep, monkeypatch):
    """Nothing went live, so there is nothing to undo — and undoing it would
    be a second change on top of a machine that is already not doing as it is
    told."""
    deploy, _ = dep
    asked = []
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: asked.append(sha))
    monkeypatch.setattr(deploy, "wait_for_restart", lambda since, *a, **k: None)
    monkeypatch.setattr(deploy, "live_check", lambda shots: pytest.fail("it looked at a temper that never restarted"))
    monkeypatch.setattr(deploy, "revert_to", lambda *a: pytest.fail("it rolled back without deploying"))
    out = deploy.deploy("2" * 40)
    assert asked == ["2" * 40]
    assert out["restarted"] is False
    assert "nothing went live" in out["reason"]


def test_a_good_deploy_becomes_the_one_to_go_back_to(dep, monkeypatch):
    deploy, tmp_path = dep
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: _restarted(
        deploy, tmp_path, now + dt.timedelta(seconds=5), head=sha[:8]))
    monkeypatch.setattr(deploy, "live_check", lambda shots: {"ok": True, "parts": [{"name": "check", "ok": True}]})
    monkeypatch.setattr(deploy, "revert_to", lambda *a: pytest.fail("it rolled a good deploy back"))
    out = deploy.deploy("3" * 40)
    assert out["ok"] is True
    assert deploy.state()["last_good"] == "3" * 40


def test_a_bad_deploy_goes_back_and_says_so(dep, monkeypatch):
    """The point of the whole thing: temper ends up on the last good commit,
    and the owner is told what failed and what was taken out."""
    deploy, tmp_path = dep
    deploy.save({"last_good": "4" * 40, "deployed": "4" * 40})
    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: {"ok": True})
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: _restarted(
        deploy, tmp_path, now + dt.timedelta(seconds=5), head=sha[:8]))
    monkeypatch.setattr(deploy, "live_check", lambda shots: {
        "ok": False,
        "parts": [{"name": "check", "ok": True}, {"name": "hooks", "ok": False, "detail": "Slack said 500"}],
    })
    reverted = {}
    monkeypatch.setattr(deploy, "revert_to", lambda good, bad, reason: (
        reverted.update(good=good, bad=bad, reason=reason),
        {"ok": True, "revert": "9" * 40},
    )[1])
    said = []
    monkeypatch.setattr(deploy, "dm", said.append)
    monkeypatch.setattr(deploy, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "5555555 Add a thing\n", ""))

    out = deploy.deploy("5" * 40)

    assert out["ok"] is False
    assert reverted["good"] == "4" * 40 and reverted["bad"] == "5" * 40
    assert "hooks" in reverted["reason"]
    assert deploy.state()["deployed"] == "9" * 40
    # The last good one does *not* become the broken commit.
    assert deploy.state()["last_good"] == "4" * 40
    assert said, "the owner was never told"
    told = said[0]
    assert "hooks" in told and "Add a thing" in told and "4444" in told


def test_with_nothing_good_to_go_back_to_it_says_so_instead_of_guessing(dep, monkeypatch):
    """Reverting to a commit nobody has seen working is how a bad night turns
    into a worse one."""
    deploy, tmp_path = dep
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: _restarted(
        deploy, tmp_path, now + dt.timedelta(seconds=5), head=sha[:8]))
    monkeypatch.setattr(deploy, "live_check", lambda shots: {"ok": False, "parts": [{"name": "the page", "ok": False}]})
    monkeypatch.setattr(deploy, "revert_to", lambda *a: pytest.fail("it reverted with nowhere to go"))
    said = []
    monkeypatch.setattr(deploy, "dm", said.append)
    out = deploy.deploy("6" * 40)
    assert out["rolled_back"] is False
    assert "no earlier commit the gate has passed" in said[0].replace("  ", " ")


def test_it_only_believes_a_restart_that_came_after_it_asked(dep):
    """temper-deploy's record is a file that is always there; an old one must
    not be read as "the restart happened"."""
    deploy, tmp_path = dep
    asked = dt.datetime.now(dt.UTC)
    _restarted(deploy, tmp_path, asked - dt.timedelta(minutes=5))
    assert deploy.restart_done_after(asked) is None
    _restarted(deploy, tmp_path, asked + dt.timedelta(seconds=1))
    assert deploy.restart_done_after(asked) is not None


def test_an_old_record_still_counts_when_temper_is_already_on_that_commit(dep):
    """A restart already under way when temper-ci asked can carry the commit;
    temper-deploy then lets the request go and writes no new record, and
    waiting for one waits the whole hour -- with the watcher a single loop,
    it stops checking pushed commits for that hour too. A commit queued
    behind this sat half an hour while the gate said "checking: nothing
    right now".

    But only once the request has gone: while a restart is still to come,
    the old record proves nothing (see the re-deploy test below).
    """
    deploy, tmp_path = dep
    sha = "8" * 40
    asked = dt.datetime.now(dt.UTC)
    _restarted(deploy, tmp_path, asked - dt.timedelta(minutes=5), head=sha[:8])

    assert deploy.restart_done_after(asked, sha) is not None
    # Still strict about an old record for some *other* commit.
    assert deploy.restart_done_after(asked, "9" * 40) is None
    assert deploy.restart_done_after(asked) is None
    # And about the old record while a restart is still waiting.
    (tmp_path / "request.json").write_text(json.dumps({"reasons": [{"reason": "x", "commits": [sha]}]}))
    assert deploy.restart_done_after(asked, sha) is None


def test_it_does_not_wait_out_the_hour_when_the_commit_is_already_live(dep, monkeypatch):
    """The wait must end at once, not after RESTART_PATIENCE."""
    deploy, tmp_path = dep
    sha = "7" * 40
    asked = dt.datetime.now(dt.UTC)
    _restarted(deploy, tmp_path, asked - dt.timedelta(minutes=5), head=sha[:8])
    monkeypatch.setattr(deploy.time, "sleep",
                        lambda s: pytest.fail("it slept waiting for a restart already done"))

    assert deploy.wait_for_restart(asked, sha) is not None


def test_a_half_finished_revert_does_not_block_the_next_one(dep, monkeypatch):
    """A revert killed half way \u2014 reboot, service restart \u2014 leaves its worktree
    and branch behind, and git then refuses to make them again. That would
    mean no rollback at all on the next bad deploy: the one moment it has to
    work.
    """
    deploy, _ = dep
    ran: list[tuple] = []

    def fake_sh(*args, **kwargs):
        ran.append(args)
        # Pretend the worktree could not be added, so revert_to returns early
        # and we only inspect what it did to clear the way first.
        if "add" in args:
            return subprocess.CompletedProcess(args, 1, "", "already exists")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(deploy, "sh", fake_sh)
    deploy.revert_to("g" * 40, "b" * 40, "because")

    joined = [" ".join(str(a) for a in call) for call in ran]
    assert any("worktree prune" in c for c in joined), "a stale registration is left in the way"
    assert any("branch -q -D revert-bbbbbbbb" in c.replace("  ", " ") for c in joined), \
        "a stale branch of the same name is left in the way"
    assert any(c.startswith("rm -rf") for c in joined), "the old folder is left in the way"


def test_it_will_not_go_back_to_a_commit_the_gate_never_passed(dep, monkeypatch):
    """What really happened: on the day the gate was installed, master was a
    commit from before it existed. That was written down as "the good one", so
    when a live check failed the machine reverted to it \u2014 and the revert could
    never pass its own gate, because those files have no docker-compose.ci.yml.
    Two unlandable revert commits later, master had not moved and nobody had
    been told anything useful.
    """
    deploy, _ = dep
    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: None)
    assert deploy.can_be_gone_back_to("c2ea3a6df787") is False

    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: {"ok": True})
    assert deploy.can_be_gone_back_to("c2ea3a6df787") is True

    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: {"ok": False})
    assert deploy.can_be_gone_back_to("c2ea3a6df787") is False
    assert deploy.can_be_gone_back_to("") is False


def test_a_first_look_at_an_unchecked_master_records_nowhere_to_go_back_to(dep, monkeypatch):
    deploy, _ = dep
    monkeypatch.setattr(deploy, "master_sha", lambda: "a" * 40)
    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: None)

    assert deploy.watch_master() is None
    data = deploy.state()
    assert data["deployed"] == "a" * 40, "it still knows what is live"
    assert not data.get("last_good"), "it must not claim an unchecked commit is somewhere to go back to"


def test_it_makes_one_revert_and_then_asks_for_a_person(dep, monkeypatch):
    """A second revert while the first is outstanding is the machine arguing
    with itself on master while nobody is watching."""
    deploy, _ = dep
    said: list[str] = []
    monkeypatch.setattr(deploy, "dm", lambda msg: said.append(msg))
    monkeypatch.setattr(deploy, "ask_restart", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "wait_for_restart", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(deploy, "live_check", lambda shots: {
        "ok": False, "parts": [{"name": "the dashboard", "ok": False, "detail": "no"}], "shots": []})
    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: {"ok": True})
    reverts: list[tuple] = []
    monkeypatch.setattr(deploy, "revert_to", lambda good, bad, why: (
        reverts.append((good, bad)), {"ok": False, "revert": "r" * 40})[1])

    data = deploy.state()
    data["last_good"] = "g" * 40
    deploy.save(data)

    deploy.deploy("b" * 40)
    assert len(reverts) == 1, "the first failure must be reverted"
    assert deploy.state()["revert_outstanding"] == "r" * 40

    deploy.deploy("c" * 40)
    assert len(reverts) == 1, "it reverted twice over; master is not a place to argue"
    assert "needs a person" in said[-1]


def test_it_asks_the_live_temper_where_it_is(dep, monkeypatch):
    """The bug this exists for: the live API was hard-coded to port 8000 and the
    live server is on 8420, so every part of the live check that spoke to the
    API failed on every deploy, whatever the deploy had done \u2014 and a check that
    always says no reverts good code for ever, while looking like caution.
    """
    deploy, _ = dep
    monkeypatch.setattr(deploy, "sh", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, "127.0.0.1:8420\n[::]:8420\n", ""))
    assert deploy.live_api() == "http://127.0.0.1:8420"


def test_with_docker_silent_it_falls_back_to_the_published_port(dep, monkeypatch):
    """Docker not answering is not a reason to check nothing; the compose file
    publishes one port and it is in the repository."""
    deploy, _ = dep
    monkeypatch.setattr(deploy, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "no such container"))
    assert deploy.live_api() == f"http://127.0.0.1:{deploy.LIVE_PORT_DEFAULT}"
    assert deploy.LIVE_PORT_DEFAULT == 8420, "this must match docker-compose.yml"


def test_the_live_port_default_is_the_one_compose_publishes():
    """If someone changes the published port, the fallback has to follow, or a
    deploy on a day docker is slow reverts everything."""
    import re  # noqa: PLC0415

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    # The line reads "${TEMPER_BIND:-127.0.0.1}:8420:8420" \u2014 the address is a variable,
    # the published port is not.
    published = {int(m) for m in re.findall(r"[:}](\d+):8420\"", compose)}
    assert published, "docker-compose.yml publishes no server port"

    import sys as _sys  # noqa: PLC0415
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from temper_ci import deploy as deploy_mod  # noqa: PLC0415

    assert deploy_mod.LIVE_PORT_DEFAULT in published, (
        f"the fallback is {deploy_mod.LIVE_PORT_DEFAULT}, but compose publishes {published}")


def test_it_asks_for_a_restart_the_way_temper_deploy_expects(dep, monkeypatch):
    """--commit is temper-deploy's own check that the restart really carried
    this change; getting the arguments wrong would mean a silent no-op."""
    deploy, _ = dep
    seen = {}
    monkeypatch.setattr(deploy, "_temper_deploy", lambda *a, **k: (
        seen.update(args=a), subprocess.CompletedProcess(a, 0, "ok", ""))[1])
    deploy.ask_restart("7" * 40, "temper-ci: it landed")
    assert seen["args"][0] == "restart"
    assert "--reason" in seen["args"] and "--commit" in seen["args"]
    assert seen["args"][seen["args"].index("--commit") + 1] == "7" * 40


# -- waiting for the real restart, and saying a failure once -----------------
#
# These run deploy() and watch_master() whole, with temper-deploy, its two
# files, the clock, the live check and the DM stood in for. temper-deploy's
# files live in tmp_path and the gate's state in tmp_path/state (the dep
# fixture), so nothing here reads or writes anything of the live machine's.


class _Clock:
    """Stands in for deploy's ``time``: a sleep moves it on, and whatever falls due then happens."""

    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []
        self._due: list[tuple[float, Callable[[], None]]] = []

    def time(self) -> float:
        return 1_800_000_000.0 + self.t

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds
        for item in sorted(self._due, key=lambda d: d[0]):
            if item[0] <= self.t:
                self._due.remove(item)
                item[1]()
        if self.t > 2 * 60 * 60:
            pytest.fail("still waiting after two hours")

    def after(self, seconds: float, fn: Callable[[], None]) -> None:
        self._due.append((self.t + seconds, fn))


class _TemperDeploy:
    """Stands in for ~/.local/bin/temper-deploy, through the two files temper-ci reads.

    Asked for a restart, it writes its request before it answers, as the real
    one does. With ``restart_after`` it then restarts: the restart begins a
    second after the ask, its record is written when it is done, and only then
    does the request go -- the real waiter's order. With ``let_go_after`` it
    lets the request go with no new record instead: what happens when a
    restart already under way carried the commit, a rebuild is needed, or
    someone cancels. With neither, the request just stays. With
    ``another_after``, someone else asked during the restart for code it did
    not carry, so the request stays for them and a second restart follows.
    """

    ANSWER = ("Restarting at the next check (within 30 s); runs go on in their own boxes.\n"
              "The result goes to the owner's Slack DM. See: temper-deploy status")

    def __init__(self, tmp_path: Path, clock: _Clock) -> None:
        self.request = tmp_path / "request.json"
        self.record = tmp_path / "last-restart.json"
        self.clock = clock
        self.restart_after: float | None = 25
        self.let_go_after: float | None = None
        self.another_after: float | None = None
        self.asks: list[str] = []
        self.restarts: list[float] = []     # when each record was written

    def on_record(self, head: str, minutes_ago: float) -> None:
        """The record of a restart from before the test begins."""
        at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes_ago)
        self.record.write_text(json.dumps({"at": at.isoformat(), "head": head[:8], "problems": []}))

    def __call__(self, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
        assert args[0] == "restart", f"a test ran temper-deploy {args[0]}"
        sha = args[args.index("--commit") + 1]
        asked_at = dt.datetime.now(dt.UTC)
        self.asks.append(sha)
        self.request.write_text(json.dumps({"reasons": [
            {"reason": args[args.index("--reason") + 1], "commits": [sha], "at": asked_at.isoformat()}]}))

        def restart() -> None:
            began = asked_at + dt.timedelta(seconds=1 + len(self.restarts))
            self.record.write_text(json.dumps({"at": began.isoformat(), "head": sha[:8], "problems": []}))
            self.restarts.append(self.clock.t)
            if self.another_after is not None and len(self.restarts) == 1:
                self.request.write_text(json.dumps({"reasons": [
                    {"reason": "someone else's", "commits": ["e" * 40], "at": began.isoformat()}]}))
                self.clock.after(self.another_after, restart)
            else:
                self.request.unlink()

        if self.let_go_after is not None:
            self.clock.after(self.let_go_after, self.request.unlink)
        elif self.restart_after is not None:
            self.clock.after(self.restart_after, restart)
        return subprocess.CompletedProcess(args, 0, self.ANSWER, "")


def _stand_ins(deploy, tmp_path, monkeypatch) -> tuple[_Clock, _TemperDeploy]:
    clock = _Clock()
    td = _TemperDeploy(tmp_path, clock)
    monkeypatch.setattr(deploy, "time", clock)
    monkeypatch.setattr(deploy, "_temper_deploy", td)
    monkeypatch.setattr(deploy, "dm", lambda text: pytest.fail(f"an unexpected DM: {text}"))
    monkeypatch.setattr(deploy, "revert_to", lambda *a: pytest.fail("an unexpected revert"))
    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: {"ok": True})
    return clock, td


def _log_lines(deploy) -> list[str]:
    return deploy.paths.LOG.read_text(encoding="utf-8").splitlines()


def test_a_redeploy_of_the_live_commit_waits_for_the_restart_it_asked_for(dep, monkeypatch):
    """2026-10-03: asked to put on the commit temper was already on, it found
    the old record naming that commit and looked at temper two seconds after
    asking -- in the middle of the very restart it had asked for. Everything
    failed, and a good commit was reverted.

    While a restart is still to come the old record proves nothing: it waits
    for the record of the restart it asked for, and only then looks.
    """
    deploy, tmp_path = dep
    clock, td = _stand_ins(deploy, tmp_path, monkeypatch)
    sha = "5" * 40
    td.on_record(sha, minutes_ago=5)
    deploy.save({"deployed": sha, "last_good": sha})
    looked: list[tuple[float, int]] = []
    monkeypatch.setattr(deploy, "live_check", lambda shots: (
        looked.append((clock.t, len(td.restarts))), {"ok": True, "parts": []})[1])

    out = deploy.deploy(sha)

    assert td.asks == [sha]
    assert len(td.restarts) == 1, "the stand-in never restarted"
    assert looked, "it never looked at temper"
    when, restarts_by_then = looked[0]
    assert restarts_by_then == 1, f"it looked at {when}s, before the restart it asked for"
    assert when >= td.restarts[0]
    assert out["ok"] is True and out["restarted"] is True
    assert set(clock.slept) == {deploy.RESTART_POLL} and deploy.RESTART_POLL == 10
    lines = _log_lines(deploy)
    order = [next(i for i, line in enumerate(lines) if what in line)
             for what in ("asked temper-deploy", "temper restarted at", "live and well")]
    assert order == sorted(order), lines


def test_a_restart_still_to_come_after_ours_is_waited_for_too(dep, monkeypatch):
    """Someone else asked while ours was under way, for code it did not carry,
    and temper-deploy restarts again straight after. Our record is there by
    then, but looking at temper would land in the middle of the next restart."""
    deploy, tmp_path = dep
    clock, td = _stand_ins(deploy, tmp_path, monkeypatch)
    sha = "4" * 40
    td.on_record("1" * 40, minutes_ago=30)
    deploy.save({"deployed": "1" * 40, "last_good": "1" * 40})
    td.another_after = 40
    looked: list[int] = []
    monkeypatch.setattr(deploy, "live_check", lambda shots: (
        looked.append(len(td.restarts)), {"ok": True, "parts": []})[1])

    out = deploy.deploy(sha)

    assert out["ok"] is True
    assert looked == [2], "it looked between the two restarts"


def test_a_request_let_go_without_a_restart_is_checked_in_seconds_not_an_hour(dep, monkeypatch):
    """The other side of it: a restart already under way when temper-ci asked
    can carry the commit, and then temper-deploy lets the request go with no
    new record. The old record is the answer then -- once the request has gone,
    and from that moment, not after RESTART_PATIENCE.
    """
    deploy, tmp_path = dep
    clock, td = _stand_ins(deploy, tmp_path, monkeypatch)
    sha = "6" * 40
    td.on_record(sha, minutes_ago=1)
    td.let_go_after = 15
    looked: list[tuple[float, bool]] = []
    monkeypatch.setattr(deploy, "live_check", lambda shots: (
        looked.append((clock.t, td.request.exists())), {"ok": True, "parts": []})[1])

    out = deploy.deploy(sha)

    assert out["ok"] is True
    assert looked, "it never looked at temper"
    when, still_waiting = looked[0]
    assert not still_waiting, "it took the old record while a restart was still to come"
    assert 15 <= when <= 120, f"it looked after {when}s"
    assert not td.restarts


def test_a_request_let_go_with_no_restart_onto_the_commit_is_not_asked_again(dep, monkeypatch):
    """When temper-deploy lets the request go and temper is not on the commit
    (a rebuild is needed -- it tells the owner so itself -- or someone
    cancelled), nothing went live and there is nothing to roll back. Before,
    the wait ran out the hour first; now the answer comes in seconds, and
    asking again every loop would mean a request, and temper-deploy's DM,
    every half minute.
    """
    deploy, tmp_path = dep
    clock, td = _stand_ins(deploy, tmp_path, monkeypatch)
    live, landed = "1" * 40, "7" * 40
    td.on_record(live, minutes_ago=30)
    deploy.save({"deployed": live, "last_good": live})
    monkeypatch.setattr(deploy, "master_sha", lambda: landed)
    td.let_go_after = 15
    monkeypatch.setattr(deploy, "live_check", lambda shots: pytest.fail("it looked at a temper not on the commit"))

    out = deploy.watch_master()

    assert out["restarted"] is False and "nothing went live" in out["reason"]
    assert clock.t <= 120, f"it waited {clock.t}s for a restart that was not coming"
    for _ in range(5):
        assert deploy.watch_master() is None
    assert td.asks == [landed], "it asked again for the same commit"


def test_a_restart_still_waiting_after_the_hour_is_asked_for_again(dep, monkeypatch):
    """Unchanged: a request temper-deploy still holds after RESTART_PATIENCE is
    not a failure of the commit, so the next loop asks again (and joins it)."""
    deploy, tmp_path = dep
    clock, td = _stand_ins(deploy, tmp_path, monkeypatch)
    td.restart_after = None
    live, landed = "1" * 40, "8" * 40
    td.on_record(live, minutes_ago=30)
    deploy.save({"deployed": live, "last_good": live})
    monkeypatch.setattr(deploy, "master_sha", lambda: landed)
    monkeypatch.setattr(deploy, "live_check", lambda shots: pytest.fail("it looked before any restart"))

    out = deploy.watch_master()

    assert out["restarted"] is False and "never restarted" in out["reason"]
    assert deploy.RESTART_PATIENCE <= clock.t < deploy.RESTART_PATIENCE + 60
    assert "handled" not in deploy.state()

    td.restart_after = 25
    monkeypatch.setattr(deploy, "live_check", lambda shots: {"ok": True, "parts": []})
    assert deploy.watch_master()["ok"] is True
    assert td.asks == [landed, landed]


def test_a_failure_with_a_revert_outstanding_is_said_once_and_not_tried_again(dep, monkeypatch):
    """2026-10-03: with a revert outstanding, a failed live check DMed "needs a
    person" and went back round the loop with nothing written down -- so the
    next loop deployed the same commit again: six restarts and six DMs in ten
    minutes, until master happened to move.
    """
    deploy, tmp_path = dep
    _, td = _stand_ins(deploy, tmp_path, monkeypatch)
    good, bad, fixed = "a" * 40, "b" * 40, "c" * 40
    master = {"sha": bad}
    monkeypatch.setattr(deploy, "master_sha", lambda: master["sha"])
    deploy.save({"last_good": good, "deployed": good, "revert_outstanding": "r" * 40})
    monkeypatch.setattr(deploy, "live_check", lambda shots: {
        "ok": master["sha"] == fixed,
        "parts": [{"name": "the dashboard", "ok": master["sha"] == fixed, "detail": ""}]})
    said: list[str] = []
    monkeypatch.setattr(deploy, "dm", said.append)

    first = deploy.watch_master()
    assert first["ok"] is False and first["rolled_back"] is False
    assert len(said) == 1 and "needs a person" in said[0]

    for _ in range(6):
        assert deploy.watch_master() is None, "it deployed the same failed commit again"
    assert td.asks == [bad], "it asked for another restart of the same commit"
    assert len(said) == 1, "the owner was told more than once"

    master["sha"] = fixed
    out = deploy.watch_master()
    assert out["ok"] is True, "a new commit on master was not deployed as usual"
    assert td.asks == [bad, fixed]
    data = deploy.state()
    assert data["deployed"] == fixed and data["last_good"] == fixed
    assert not data["revert_outstanding"]
    assert len(said) == 1


@pytest.mark.parametrize("how", ["nowhere to go back to", "the revert did not go through"])
def test_every_failed_live_check_is_said_once(dep, monkeypatch, how):
    """The other ways a failure ends left the same loop open: with no good
    commit to go back to, or with a revert that never moved master, the
    watcher found master still not deployed and went round again."""
    deploy, tmp_path = dep
    _, td = _stand_ins(deploy, tmp_path, monkeypatch)
    bad = "b" * 40
    monkeypatch.setattr(deploy, "master_sha", lambda: bad)
    deploy.save({"last_good": "a" * 40, "deployed": "a" * 40})
    if how == "nowhere to go back to":
        monkeypatch.setattr(deploy.gate, "result_for", lambda sha: None)
    else:
        monkeypatch.setattr(deploy, "revert_to", lambda good, sha, why: {
            "ok": False, "revert": "r" * 40, "detail": "the revert itself did not pass the gate"})
    monkeypatch.setattr(deploy, "live_check", lambda shots: {
        "ok": False, "parts": [{"name": "the dashboard", "ok": False, "detail": ""}]})
    said: list[str] = []
    monkeypatch.setattr(deploy, "dm", said.append)

    deploy.watch_master()
    for _ in range(4):
        assert deploy.watch_master() is None

    assert td.asks == [bad]
    assert len(said) == 1, said


def test_temper_ci_deploy_by_hand_tries_a_handled_commit_again(dep, monkeypatch, capsys):
    """The watcher leaves a handled commit alone; a person who has fixed what
    was wrong can still say "now"."""
    deploy, tmp_path = dep
    from temper_ci import cli  # noqa: PLC0415

    _, td = _stand_ins(deploy, tmp_path, monkeypatch)
    sha = "d" * 40
    monkeypatch.setattr(deploy, "master_sha", lambda: sha)
    deploy.save({"last_good": "a" * 40, "deployed": "a" * 40, "handled": sha})
    assert deploy.watch_master() is None
    assert td.asks == []

    monkeypatch.setattr(cli, "_resolve", lambda ref: sha)
    monkeypatch.setattr(deploy, "live_check", lambda shots: {"ok": True, "parts": []})
    assert cli.main(["deploy", sha[:12]]) == 0

    assert td.asks == [sha]
    data = deploy.state()
    assert data["deployed"] == sha and data["last_good"] == sha
    assert "handled" not in data


# -- the Pi pins: shown after every deploy, never counted ----------------------
#
# temper's pin check (scripts/pi_pins_check.py --json) is stood in for: no box config,
# image or tar is read. The live temper around it passes all four parts that count, so
# whatever the pins say is the only thing that changes -- and the live check passes anyway.


def _pin(name: str, ok: bool = True, want: object = None, have: object = None) -> dict:
    want = want or "sha256:" + hashlib.sha256(name.encode()).hexdigest()
    if ok:
        have = want
    return {"name": name, "want": want, "ok": ok,
            "have": have or "sha256:" + hashlib.sha256(b"not " + name.encode()).hexdigest()}


def _pins_said(result: str, pins: list[dict], code: int, error: str = "") -> subprocess.CompletedProcess:
    """What the pin check prints with --json, and its exit code."""
    said = {"result": result, "pins": pins, **({"error": error} if error else {})}
    return subprocess.CompletedProcess(["python3"], code, json.dumps(said) + "\n", "")


class _Answer:
    """The live API's answer to one request."""

    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _live_temper(deploy, tmp_path, monkeypatch, pins: object) -> list[tuple]:
    """Stand in for a live temper whose four counted parts all pass.

    ``pins`` is what the pin check does: a CompletedProcess to return, or an exception to
    raise. Returns the pin check's calls, each as (argv, cwd, timeout).
    """
    script = tmp_path / "checkout" / "scripts" / "pi_pins_check.py"
    script.parent.mkdir(parents=True)
    script.write_text("# stands in for temper's pin check; never run\n", encoding="utf-8")
    monkeypatch.setattr(deploy, "PIN_CHECK", script)
    monkeypatch.setattr(deploy, "_temper_deploy", lambda *a, **k: subprocess.CompletedProcess(a, 0, "well\n", ""))
    monkeypatch.setattr(deploy, "ci_key_headers", lambda *a, **k: {})

    def urlopen(req, timeout=None):
        if isinstance(req, urllib.request.Request) and req.get_method() == "POST":
            return _Answer({"execution_id": "run-0001"})
        return _Answer({"status": "completed"})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    calls: list[tuple] = []

    def sh(*args, cwd=None, timeout=120, **_kwargs):
        if args[:2] == ("docker", "port"):
            return subprocess.CompletedProcess(args, 0, "127.0.0.1:8420\n", "")
        if str(args[1]).endswith("shot.py"):
            Path(args[3]).write_bytes(b"a page")
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == str(script):
            calls.append((args, cwd, timeout))
            if isinstance(pins, BaseException):
                raise pins
            return pins
        return pytest.fail(f"an unexpected command: {args}")

    monkeypatch.setattr(deploy, "sh", sh)
    return calls


def _pins_part(out: dict) -> dict:
    [part] = [p for p in out["parts"] if p["name"] == "the Pi pins"]
    return part


def test_pins_that_match_are_shown_as_ok(dep, monkeypatch):
    """temper's own command, run the way docs/pi-lane.md gives it, after the four parts that
    count, with a backstop of its own on top of the check's 60 s."""
    deploy, tmp_path = dep
    pins = [_pin(name) for name in ("image", "image tar", "runtime", "add-on pi-tldr")]
    calls = _live_temper(deploy, tmp_path, monkeypatch, _pins_said("pass", pins, 0))

    out = deploy.live_check(tmp_path / "shots")

    assert out["ok"] is True
    assert out["parts"][-1] == {"name": "the Pi pins", "ok": True, "info": True, "result": "pass",
                                "detail": "pass: all 4 pins match"}
    assert all(not p.get("info") for p in out["parts"][:-1]), "only the pins are information only"
    [(argv, cwd, timeout)] = calls
    assert argv == ("python3", str(deploy.PIN_CHECK), "--json")
    assert cwd == deploy.PIN_CHECK.parent.parent
    assert timeout == deploy.PIN_CHECK_TIMEOUT == 120


def test_a_pin_mismatch_names_the_pins_and_the_live_check_still_passes(dep, monkeypatch):
    """A pin that's off is shown, and nothing else happens: the live check still passes, so
    nothing is reverted. The Pi lane's own preflight refuses Pi runs meanwhile."""
    deploy, tmp_path = dep
    runtime, login = _pin("runtime", ok=False), _pin("login extension", ok=False)
    pins = [_pin("image"), runtime, login,
            _pin("add-ons", ok=False, want=["pi-image-trim", "pi-tldr"], have=["pi-tldr"])]
    _live_temper(deploy, tmp_path, monkeypatch, _pins_said("mismatch", pins, 1))

    out = deploy.live_check(tmp_path / "shots")

    assert out["ok"] is True, "a pin that's off never fails the live check"
    part = _pins_part(out)
    assert (part["ok"], part["info"], part["result"]) == (False, True, "mismatch")
    assert part["detail"].splitlines() == [
        "mismatch: 3 of 4 pins: runtime, login extension, add-ons",
        f"runtime: want {runtime['want'][:19]}\u2026, have {runtime['have'][:19]}\u2026",
        f"login extension: want {login['want'][:19]}\u2026, have {login['have'][:19]}\u2026",
        "add-ons: want [pi-image-trim, pi-tldr], have [pi-tldr]",
    ]

    # However many pins are off, the part stays within its 600 characters.
    many = [_pin(f"add-on a-rather-long-add-on-name-{i:02d}", ok=False) for i in range(40)]
    said = _pins_said("mismatch", many, 1)
    monkeypatch.setattr(deploy, "sh", lambda *a, **k: said)
    long = deploy.pin_check()
    assert long["result"] == "mismatch" and len(long["detail"]) <= 600
    assert long["detail"].startswith("mismatch: 40 of 40 pins: add-on a-rather-long-add-on-name-00, ")


def test_with_no_box_config_the_pins_are_a_plain_info_line(dep, monkeypatch):
    """No private box config yet: the Pi lane was never set up on this host. Nothing is
    wrong, and the line says so plainly."""
    deploy, tmp_path = dep
    from temper_ci import report  # noqa: PLC0415

    _live_temper(deploy, tmp_path, monkeypatch,
                 _pins_said("not_set_up", [], 3, error="there is no private box config yet"))

    out = deploy.live_check(tmp_path / "shots")

    assert out["ok"] is True
    part = _pins_part(out)
    assert (part["ok"], part["info"], part["result"]) == (False, True, "not_set_up")
    assert part["detail"].startswith("not set up: there is no private box config yet")
    assert report.mark(part) == "info"


def test_a_pin_check_that_hangs_is_given_up_on_and_shown(dep, monkeypatch):
    deploy, tmp_path = dep
    from temper_ci import report  # noqa: PLC0415

    _live_temper(deploy, tmp_path, monkeypatch, subprocess.TimeoutExpired(["python3"], 120))

    out = deploy.live_check(tmp_path / "shots")

    assert out["ok"] is True
    part = _pins_part(out)
    assert (part["ok"], part["info"], part["result"]) == (False, True, "couldnt_run")
    assert part["detail"] == "couldn't run: no answer within 120 s"
    assert report.mark(part) == "FAIL (doesn't block)"


@pytest.mark.parametrize(("how", "pins", "reason"), [
    ("it crashed",
     subprocess.CompletedProcess(["python3"], 1, "", "Traceback (most recent call last):\n  ...\n"
                                 "RuntimeError: the docker socket went away\n"),
     "couldn't run (exit 1): RuntimeError: the docker socket went away"),
    ("it said error", _pins_said("error", [], 2, error="Docker did not answer"),
     "couldn't run (exit 2): Docker did not answer"),
    ("its exit and its JSON disagree", _pins_said("pass", [_pin("image")], 1),
     "couldn't run (exit 1): it said pass"),
    ("it printed nothing", subprocess.CompletedProcess(["python3"], 1, "", ""),
     "couldn't run (exit 1): it printed nothing"),
    ("python3 isn't there", FileNotFoundError(2, "No such file or directory"),
     "couldn't run: FileNotFoundError: [Errno 2] No such file or directory"),
    ("the checkout has no pin check", None,
     "couldn't run: this checkout has no scripts/pi_pins_check.py"),
])
def test_a_pin_check_that_crashes_is_shown_with_its_reason(dep, monkeypatch, how, pins, reason):
    """A crash also exits 1, so a mismatch is only believed when the JSON says so too.
    Whatever went wrong, the live check passes and the part says why."""
    deploy, tmp_path = dep
    from temper_ci import report  # noqa: PLC0415

    calls = _live_temper(deploy, tmp_path, monkeypatch, pins)
    if pins is None:
        deploy.PIN_CHECK.unlink()

    out = deploy.live_check(tmp_path / "shots")

    assert out["ok"] is True, how
    part = _pins_part(out)
    assert (part["ok"], part["info"], part["result"], part["detail"]) == (
        False, True, "couldnt_run", reason)
    assert report.mark(part) == "FAIL (doesn't block)"
    assert len(calls) == (0 if pins is None else 1)


@pytest.mark.parametrize(("part", "mark"), [
    ({"ok": True}, "ok"),
    ({"ok": False}, "FAIL"),
    ({"ok": True, "info": True, "result": "pass"}, "ok"),
    ({"ok": False, "info": True, "result": "mismatch"}, "FAIL (doesn't block)"),
    ({"ok": False, "info": True, "result": "couldnt_run"}, "FAIL (doesn't block)"),
    ({"ok": False, "info": True, "result": "not_set_up"}, "info"),
])
def test_each_part_reads_as_what_it_is(dep, part, mark):
    """Only a part that counts reads as a plain FAIL."""
    from temper_ci import report  # noqa: PLC0415

    assert report.mark(part) == mark


def _counted_parts(failing: str = "") -> list[dict]:
    return [{"name": name, "ok": name != failing, "detail": "it said no" if name == failing else ""}
            for name in ("temper-deploy check", "temper-deploy hooks",
                         "a free run on the live temper", "the dashboard")]


PINS_OFF = {"name": "the Pi pins", "ok": False, "info": True, "result": "mismatch",
            "detail": "mismatch: 1 of 13 pins: runtime\nruntime: want 1.0.1, have 1.0.2"}


def test_a_deploy_with_a_pin_off_stays_live_and_its_report_says_so(dep, monkeypatch, capsys):
    """The deploy goes through and becomes the one to go back to; the commit's report and
    `temper-ci status` show the pins, marked as not blocking."""
    deploy, tmp_path = dep
    from temper_ci import cli, report  # noqa: PLC0415

    sha = "6" * 40
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: _restarted(
        deploy, tmp_path, now + dt.timedelta(seconds=5), head=sha[:8]))
    monkeypatch.setattr(deploy, "live_check", lambda shots: {
        "at": "2026-10-06T20:00:00Z", "api": "http://127.0.0.1:8420", "ok": True,
        "parts": [*_counted_parts(), PINS_OFF], "shots": []})
    monkeypatch.setattr(deploy, "revert_to", lambda *a: pytest.fail("it reverted over a pin"))
    monkeypatch.setattr(deploy, "dm", lambda text: pytest.fail(f"it told the owner about a pin: {text}"))

    out = deploy.deploy(sha)

    assert out["ok"] is True
    assert deploy.state()["last_good"] == sha and deploy.state()["deployed"] == sha
    page = html.unescape((report.folder(sha) / "index.html").read_text(encoding="utf-8"))
    assert "After it went live" in page and "Live and well" in page
    assert "FAIL (doesn't block)" in page and "runtime: want 1.0.1, have 1.0.2" in page
    assert report.INFO_ONLY in page

    # A machine check written over the page later keeps the live check on it.
    report.write(sha, {"ok": True, "sha": sha, "checks": []})
    page = html.unescape((report.folder(sha) / "index.html").read_text(encoding="utf-8"))
    assert "After it went live" in page and "FAIL (doesn't block)" in page

    monkeypatch.setattr(deploy, "master_sha", lambda: sha)
    assert cli.main(["status"]) == 0
    shown = capsys.readouterr().out
    assert f"last deploy: {sha[:12]} live and well" in shown
    assert "FAIL (doesn't block) the Pi pins \u2014 mismatch: 1 of 13 pins: runtime\n" in shown
    assert "ok   the dashboard\n" in shown


def test_a_failed_deploy_is_put_down_to_what_counts_never_to_the_pins(dep, monkeypatch):
    """When a part that counts fails, the revert and the owner's message name that part,
    not the pins that were off at the same time."""
    deploy, tmp_path = dep
    deploy.save({"last_good": "4" * 40, "deployed": "4" * 40})
    monkeypatch.setattr(deploy.gate, "result_for", lambda sha: {"ok": True})
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: _restarted(
        deploy, tmp_path, now + dt.timedelta(seconds=5), head=sha[:8]))
    monkeypatch.setattr(deploy, "live_check", lambda shots: {
        "ok": False, "parts": [*_counted_parts(failing="the dashboard"), PINS_OFF]})
    reverted: dict = {}
    monkeypatch.setattr(deploy, "revert_to", lambda good, bad, reason: (
        reverted.update(reason=reason), {"ok": True, "revert": "9" * 40})[1])
    said: list[str] = []
    monkeypatch.setattr(deploy, "dm", said.append)
    monkeypatch.setattr(deploy, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "5555555 Add a thing\n", ""))

    deploy.deploy("5" * 40)

    assert reverted["reason"] == "the live check failed: the dashboard"
    assert len(said) == 1 and "what failed: the dashboard\n" in said[0] and "Pi pins" not in said[0]
