"""What temper-ci does once master has moved.

Restart, look at the live thing, and if it is unwell put master back. Nothing
here starts a container or restarts anything: temper-deploy, git and the DM
are all stood in for, so what is tested is the *decisions* — which is where a
rollback either saves the day or makes it worse.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def dep(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPER_CI_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("TEMPER_CI_REPORTS", str(tmp_path / "reports"))
    for name in [m for m in sys.modules if m.startswith("temper_ci")]:
        del sys.modules[name]
    from temper_ci import deploy, paths  # noqa: PLC0415

    paths.ensure_dirs()
    monkeypatch.setattr(deploy, "LAST_RESTART", tmp_path / "last-restart.json")
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
    monkeypatch.setattr(deploy, "wait_for_restart", lambda since, **k: None)
    monkeypatch.setattr(deploy, "live_check", lambda shots: pytest.fail("it looked at a temper that never restarted"))
    monkeypatch.setattr(deploy, "revert_to", lambda *a: pytest.fail("it rolled back without deploying"))
    out = deploy.deploy("2" * 40)
    assert asked == ["2" * 40]
    assert out["restarted"] is False
    assert "nothing went live" in out["reason"]


def test_a_good_deploy_becomes_the_one_to_go_back_to(dep, monkeypatch):
    deploy, tmp_path = dep
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: _restarted(deploy, tmp_path, now + dt.timedelta(seconds=5)))
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
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: _restarted(deploy, tmp_path, now + dt.timedelta(seconds=5)))
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
    monkeypatch.setattr(deploy, "ask_restart", lambda sha, why: _restarted(deploy, tmp_path, now + dt.timedelta(seconds=5)))
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
