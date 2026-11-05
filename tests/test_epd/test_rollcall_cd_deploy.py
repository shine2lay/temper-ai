"""RollCall's continuous deployer: master goes live two minutes after the last land, one release at a time.

The rule (owner, 2026-11-05): a land starts a deploy of that commit; lands that come in while a deploy
runs go out together in the next one; the wait is two minutes. Here the clock, origin's master, the
systemd units and the release itself (epd_loop.deploy_prod) are fakes, and what is under test is what
configs/epd/bin/rollcall_cd_deploy.py decides, records and refuses. The checkout tests use a real git
repository with a bare origin; the notify tests a fake Telegram sender and a fake pi-web-ui control
socket. No test ever reaches the real pi-web-ui: ROLLCALL_CD_PI_WEB_UI_DIR points every one elsewhere.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import shutil
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest
import yaml

from temper_ai.config.helpers import substitute_env_vars
from temper_ai.config.store import ConfigStore
from temper_ai.stage.loader import GraphLoader
from temper_ai.triggers import scheduler
from temper_ai.triggers.rules import parse_trigger

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "epd" / "bin"
T0 = dt.datetime(2026, 11, 5, 18, 0, tzinfo=dt.UTC)
LIVE, A, B, C = ("0" * 39 + "1"), ("a" * 40), ("b" * 40), ("c" * 40)
MIN = dt.timedelta(minutes=1)
SEC = dt.timedelta(seconds=1)


@pytest.fixture(autouse=True)
def no_real_pi_web_ui(tmp_path, monkeypatch):
    """A role message from any test goes to a pi-web-ui that is not there, never to a real chat."""
    monkeypatch.setenv("ROLLCALL_CD_PI_WEB_UI_DIR", str(tmp_path / "no-pi-web-ui"))


# ---- the deployer, with the outside world faked ----------------------------------------------------


class World:
    """Origin's master, the clock, the deploy units and the release, as the deployer sees them."""

    def __init__(self, cd):
        self.cd = cd
        self.t = T0
        self.head = A
        self.live = LIVE
        self.running: set[str] = set()
        self.launched: list[tuple[str, str]] = []  # (unit, sha)
        self.released: list[str] = []
        self.kinds: list[str] = []  # the --kind each release was given
        self.release_result = (0, "release of it is live and healthy")
        self.dirty = ""
        self.checked_out: list[str] = []

    def tick(self, at: dt.timedelta | None = None) -> dict:
        if at is not None:
            self.t = T0 + at
        return self.cd.tick()

    def launch(self, unit, sha, reason):
        self.launched.append((unit, sha))
        self.running.add(unit)

    def finish(self, at: dt.timedelta) -> int:
        """The running deploy unit does its work (cd.deploy, as `deploy --sha` would) and ends at `at`."""
        (unit,) = self.running
        sha = dict(self.launched)[unit]
        os.environ["ROLLCALL_CD_UNIT"] = unit
        try:
            self.t = T0 + at
            return self.cd.deploy(sha, "deploy", "test")
        finally:
            del os.environ["ROLLCALL_CD_UNIT"]
            self.running.discard(unit)

    def run_release(self, sha, kind, reason):
        self.released.append(sha)
        self.kinds.append(kind)
        return self.release_result

    def checkout(self, sha):
        if self.dirty:
            raise self.cd.CheckoutProblem(f"{self.cd.CHECKOUT} has changes; refusing to build from it: {self.dirty}")
        self.checked_out.append(sha)


def fresh_modules(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLLCALL_CD_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("ROLLCALL_CD_CHECKOUT", str(tmp_path / "rollcall-deploy"))
    monkeypatch.setenv("EPD_PROD_HOME", str(tmp_path / "prod-home"))
    monkeypatch.setenv("ROLLCALL_CD_TELEGRAM_SENDER", str(tmp_path / "no-sender.mjs"))
    monkeypatch.delenv("ROLLCALL_CD_UNIT", raising=False)
    monkeypatch.syspath_prepend(str(BIN))
    for name in ("rollcall_cd_notify", "rollcall_cd_deploy"):
        sys.modules.pop(name, None)
    notify = importlib.import_module("rollcall_cd_notify")
    cd = importlib.import_module("rollcall_cd_deploy")
    assert cd.notify is notify and cd.STATE_DIR == tmp_path / "state"
    return cd, notify


@pytest.fixture
def cd(tmp_path, monkeypatch):
    cd, _ = fresh_modules(tmp_path, monkeypatch)
    w = World(cd)
    cd.world = w
    monkeypatch.setattr(cd, "now", lambda: w.t)
    monkeypatch.setattr(cd, "ensure_clone", lambda: None)
    monkeypatch.setattr(cd, "fetch_head", lambda: w.head)
    monkeypatch.setattr(cd, "dirty", lambda: w.dirty)
    monkeypatch.setattr(cd, "checkout", w.checkout)
    monkeypatch.setattr(cd, "unit_running", lambda unit: unit in w.running)
    monkeypatch.setattr(cd, "launch", w.launch)
    monkeypatch.setattr(cd, "run_release", w.run_release)
    monkeypatch.setattr(cd, "live_commit", lambda: w.live)
    return cd


def unit(sha):
    return "rollcall-cd-deploy-" + sha[:8]


def state(cd) -> dict:
    return json.loads(cd.STATE_FILE.read_text())


def events(cd) -> list[dict]:
    return [json.loads(line) for line in cd.LOG_FILE.read_text().splitlines()] if cd.LOG_FILE.exists() else []


def outbox(cd) -> list[dict]:
    path = cd.notify.OUTBOX
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# ---- the quiet window ------------------------------------------------------------------------------


def test_master_goes_live_two_minutes_after_the_last_land(cd):
    w = cd.world
    first = w.tick(dt.timedelta(0))
    assert first["decision"] == "waiting" and first["due_at"] == (T0 + 2 * MIN).isoformat()
    assert state(cd)["deployed_sha"] == LIVE  # what was live already, from standee
    assert w.tick(MIN)["decision"] == "waiting"
    assert w.tick(2 * MIN - SEC)["decision"] == "waiting"
    assert w.launched == []
    out = w.tick(2 * MIN)
    assert out["decision"] == "deploy" and out["unit"] == unit(A)
    assert w.launched == [(unit(A), A)]
    assert state(cd)["deploy_running_unit"] == unit(A)
    started = events(cd)[-1]
    assert (started["kind"], started["sha"], started["from_sha"], started["result"], started["unit"]) == (
        "deploy", A, LIVE, "started", unit(A))
    assert outbox(cd) == []  # a start is logged, not messaged
    assert w.tick(3 * MIN)["decision"] == "running"
    assert w.finish(5 * MIN) == 0
    st = state(cd)
    assert (st["deployed_sha"], st["deploy_running_unit"], st["last_deploy_end_at"]) == (
        A, None, (T0 + 5 * MIN).isoformat())
    assert w.checked_out == w.released == [A]
    done = events(cd)[-1]
    assert (done["kind"], done["sha"], done["from_sha"], done["result"], done["unit"]) == (
        "deploy", A, LIVE, "ok", unit(A))
    (msg,) = outbox(cd)
    assert msg["to"] == "rollcall" and msg["kind"] == "fyi" and msg["text"].startswith("rollcall-cd deploy aaaaaaaa")
    assert w.tick(9 * MIN)["decision"] == "idle"
    assert len(w.launched) == 1


def test_a_land_inside_the_window_starts_it_again(cd):
    w = cd.world
    w.tick(dt.timedelta(0))
    w.head = B
    w.tick(90 * SEC)  # B landed 90 s after A
    out = w.tick(2 * MIN)
    assert out["decision"] == "waiting" and out["due_at"] == (T0 + 90 * SEC + 2 * MIN).isoformat()
    assert w.tick(90 * SEC + 2 * MIN - SEC)["decision"] == "waiting"
    assert w.tick(90 * SEC + 2 * MIN)["decision"] == "deploy"
    assert w.launched == [(unit(B), B)]  # A never went out on its own: B carries it


def test_lands_during_a_deploy_go_out_together_in_one_later_deploy(cd):
    w = cd.world
    w.tick(dt.timedelta(0))
    assert w.tick(2 * MIN)["decision"] == "deploy"  # A
    w.head = B
    assert w.tick(3 * MIN)["decision"] == "running"
    w.head = C
    assert w.tick(4 * MIN)["decision"] == "running"
    assert w.finish(4 * MIN + 30 * SEC) == 0
    # C has been quiet since 4:00, but the deploy only ended at 4:30: two more minutes from there.
    out = w.tick(6 * MIN)
    assert out["decision"] == "waiting" and out["due_at"] == (T0 + 6 * MIN + 30 * SEC).isoformat()
    assert w.tick(6 * MIN + 30 * SEC)["decision"] == "deploy"
    assert w.launched == [(unit(A), A), (unit(C), C)]  # one deploy for B and C, of HEAD
    assert w.finish(9 * MIN) == 0
    assert state(cd)["deployed_sha"] == C
    assert w.tick(12 * MIN)["decision"] == "idle"
    assert len(w.launched) == 2


def test_what_is_live_already_is_not_deployed_again(cd):
    w = cd.world
    w.live = A
    assert w.tick(dt.timedelta(0))["decision"] == "idle"
    assert w.tick(10 * MIN)["decision"] == "idle"
    assert w.launched == []


def test_a_first_tick_with_nothing_stood_up_deploys_after_the_window(cd):
    w = cd.world
    w.live = None
    w.tick(dt.timedelta(0))
    assert w.tick(2 * MIN)["decision"] == "deploy"


# ---- what is never released on its own ------------------------------------------------------------


def test_an_undone_commit_is_skipped_once_said_and_a_new_land_goes_out(cd):
    w = cd.world
    cd.save_state({**cd.STATE_DEFAULTS, "deployed_sha": LIVE, "undone_shas": [A]})
    out = w.tick(dt.timedelta(0))
    assert out["decision"] == "skip" and "undone_shas" in out["reason"]
    assert w.tick(5 * MIN)["decision"] == "skip"
    skips = [e for e in events(cd) if e["kind"] == "skip"]
    assert len(skips) == 1 and skips[0]["sha"] == A and skips[0]["result"] == "skipped"
    assert len(outbox(cd)) == 1 and "skip aaaaaaaa" in outbox(cd)[0]["text"]
    w.head = B
    w.tick(6 * MIN)
    assert w.tick(8 * MIN)["decision"] == "deploy"
    assert w.launched == [(unit(B), B)]


def test_a_failed_release_is_said_and_not_tried_again_on_its_own(cd):
    w = cd.world
    w.release_result = (1, "/api/health says ok=False; Undone: images put back. Prod now: healthy")
    w.tick(dt.timedelta(0))
    w.tick(2 * MIN)
    assert w.finish(4 * MIN) == 1
    st = state(cd)
    assert st["deployed_sha"] == LIVE and st["undone_shas"] == [A] and st["deploy_running_unit"] is None
    failed = events(cd)[-1]
    assert (failed["kind"], failed["result"]) == ("deploy", "failed") and "Prod now: healthy" in failed["reason"]
    assert "failed" in outbox(cd)[-1]["text"]
    assert w.tick(10 * MIN)["decision"] == "skip"
    w.head = B  # the fix lands
    w.tick(11 * MIN)
    assert w.tick(13 * MIN)["decision"] == "deploy"
    assert [s for _, s in w.launched] == [A, B]


def test_an_undone_commit_released_by_hand_comes_off_the_list_and_is_idle(cd):
    """As in the Systems #97 rehearsal: a release fails, the cause is fixed outside the tree, and
    `deploy --sha` puts the same commit live by hand. It is live now, not undone."""
    w = cd.world
    w.release_result = (1, "migration failed; Undone: images put back")
    w.tick(dt.timedelta(0))
    w.tick(2 * MIN)
    assert w.finish(4 * MIN) == 1 and state(cd)["undone_shas"] == [A]
    w.release_result = (0, "release of it is live and healthy")
    w.t = T0 + 6 * MIN
    assert cd.deploy(A, "deploy", "by hand after the fix") == 0  # no unit: a person's shell
    st = state(cd)
    assert st["deployed_sha"] == A and st["undone_shas"] == [] and st["deploy_running_unit"] is None
    assert (events(cd)[-1]["result"], events(cd)[-1]["unit"]) == ("ok", None)
    assert w.tick(9 * MIN)["decision"] == "idle"
    assert w.launched == [(unit(A), A)]


def test_a_commit_already_live_ends_ok_and_is_live_now(cd):
    """deploy_prod exits DEPLOY_ALREADY_LIVE (77) for the commit live now (deployed_sha was stale: a hand
    release put it live): ok, nothing changed, deployed_sha follows, and the next tick is idle, no loop."""
    w = cd.world
    w.release_result = (cd.DEPLOY_ALREADY_LIVE, f"refusing to release {A[:12]} (forward): {A[:12]} is already live")
    w.tick(dt.timedelta(0))
    w.tick(2 * MIN)
    assert w.finish(2 * MIN + 5 * SEC) == 0
    st = state(cd)
    assert st["deployed_sha"] == A and st["undone_shas"] == []
    e = events(cd)[-1]
    assert (e["kind"], e["result"]) == ("deploy", "ok") and "already live" in e["reason"]
    assert w.tick(5 * MIN)["decision"] == "idle"
    assert w.kinds == ["deploy"]


def test_an_out_of_order_refusal_is_not_tried_again_on_its_own(cd):
    """deploy_prod's order guard exits DEPLOY_REFUSED (76): a refusal, nothing changed, and the commit
    goes on undone_shas because the guard would refuse it again every tick; the next land goes out."""
    w = cd.world
    w.release_result = (cd.DEPLOY_REFUSED, f"refusing to release {A[:12]} (forward): {LIVE[:12]}, live now, "
                                           f"is not an ancestor of {A[:12]}")
    w.tick(dt.timedelta(0))
    w.tick(2 * MIN)
    assert w.finish(2 * MIN + 5 * SEC) == 76
    st = state(cd)
    assert st["deployed_sha"] == LIVE and st["undone_shas"] == [A]
    e = events(cd)[-1]
    assert (e["kind"], e["result"]) == ("refusal", "out of order") and "not an ancestor" in e["reason"]
    assert "out of order" in outbox(cd)[-1]["text"]
    assert w.tick(6 * MIN)["decision"] == "skip"
    w.head = B
    w.tick(7 * MIN)
    assert w.tick(9 * MIN)["decision"] == "deploy"


def test_the_exit_codes_are_the_ones_deploy_prod_names(cd):
    text = (BIN / "epd_loop.py").read_text()
    for name in ("DEPLOY_BUSY", "DEPLOY_REFUSED", "DEPLOY_ALREADY_LIVE"):
        assert f"{name} = {getattr(cd, name)}\n" in text, name
    assert set(cd.RELEASE_KIND) == set(cd.KINDS) and set(cd.RELEASE_KIND.values()) == {"forward", "undo"}
    assert 'RELEASE_KINDS = ("forward", "undo")' in text


def test_a_unit_that_ended_without_saying_how_is_not_guessed(cd):
    w = cd.world
    w.tick(dt.timedelta(0))
    w.tick(2 * MIN)
    w.running.clear()  # killed: no end line
    out = w.tick(3 * MIN)
    st = state(cd)
    assert st["deploy_running_unit"] is None and st["undone_shas"] == [A] and st["deployed_sha"] == LIVE
    lost = [e for e in events(cd) if e["result"] == "lost"]
    assert len(lost) == 1 and lost[0]["sha"] == A and lost[0]["unit"] == unit(A)
    assert out["decision"] == "skip"


# ---- one at a time ---------------------------------------------------------------------------------


def test_a_release_while_the_checkout_is_in_use_changes_nothing(cd):
    import fcntl

    w = cd.world
    cd.STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(cd.CHECKOUT_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert cd.deploy(B, "undo", "money test failed on aaaaaaaa") == cd.DEPLOY_BUSY == 75
    finally:
        os.close(fd)
    assert w.released == [] and w.checked_out == []
    e = events(cd)[-1]
    assert (e["kind"], e["sha"], e["result"]) == ("refusal", B, "busy")
    st = state(cd)
    assert st["undone_shas"] == [] and st["deploy_running_unit"] is None


def test_a_release_while_another_unit_is_releasing_changes_nothing(cd):
    w = cd.world
    w.tick(dt.timedelta(0))
    w.tick(2 * MIN)  # A is releasing
    assert cd.deploy(B, "undo", "by hand") == 75
    assert w.released == []
    assert state(cd)["deploy_running_unit"] == unit(A)  # still A's
    assert events(cd)[-1]["result"] == "busy"


def test_deploy_prod_busy_with_the_loops_own_deploy_is_tried_again_later(cd):
    """epd_loop's own deploy after a merge holds deploy_prod's lock: exit 75, nothing changed."""
    w = cd.world
    w.release_result = (cd.DEPLOY_BUSY, "another production deploy is running (it holds ...); nothing was changed")
    w.tick(dt.timedelta(0))
    w.tick(2 * MIN)
    assert w.finish(2 * MIN + 5 * SEC) == 75
    st = state(cd)
    assert st["undone_shas"] == [] and st["deployed_sha"] == LIVE
    assert events(cd)[-1]["kind"] == "refusal" and events(cd)[-1]["result"] == "busy"
    assert w.tick(3 * MIN)["decision"] == "waiting"
    w.release_result = (0, "live")
    assert w.tick(4 * MIN + 5 * SEC)["decision"] == "deploy"
    assert [s for _, s in w.launched] == [A, A]


def test_a_launch_that_fails_is_said_and_leaves_no_running_unit(cd, monkeypatch):
    w = cd.world

    def broken(unit, sha, reason):
        raise RuntimeError("`systemd-run --unit=x` exited 1: Failed to connect to bus")

    monkeypatch.setattr(cd, "launch", broken)
    w.tick(dt.timedelta(0))
    with pytest.raises(RuntimeError, match="Failed to connect to bus"):
        w.tick(2 * MIN)
    st = state(cd)
    assert st["deploy_running_unit"] is None and st["undone_shas"] == []
    assert events(cd)[-1]["kind"] == "refusal" and "could not start" in events(cd)[-1]["reason"]


# ---- fail loud -------------------------------------------------------------------------------------


def test_a_tick_with_changes_in_the_checkout_refuses_and_says_it_once(cd):
    w = cd.world
    w.dirty = " M deploy/compose.yaml"
    w.tick(dt.timedelta(0))
    out = w.tick(2 * MIN)
    assert out["decision"] == "refused" and "has changes" in out["reason"]
    assert w.tick(3 * MIN)["decision"] == "refused"
    refusals = [e for e in events(cd) if e["kind"] == "refusal"]
    assert len(refusals) == 1 and len(outbox(cd)) == 1
    assert w.launched == [] and state(cd)["deploy_running_unit"] is None
    w.dirty = ""
    assert w.tick(4 * MIN)["decision"] == "deploy"


def test_the_cli_exits_non_zero_on_a_refusal(cd, capsys):
    cd.world.dirty = "?? scratch.txt"
    assert cd.main(["tick"]) == 0  # first sight: waiting
    capsys.readouterr()
    cd.world.t = T0 + 2 * MIN
    assert cd.main(["tick"]) == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["decision"] == "refused"


@pytest.mark.parametrize("sha, kind, reason, match", [
    ("abc123", "deploy", "x", "full 40-character"),
    (A.upper(), "deploy", "x", "full 40-character"),
    (A, "rollback", "x", "--kind must be one of deploy, undo"),
    (A, "undo", "  ", "--reason must say why"),
])
def test_a_deploy_with_a_bad_argument_fails_before_anything(cd, sha, kind, reason, match):
    with pytest.raises(ValueError, match=match):
        cd.deploy(sha, kind, reason)
    assert cd.world.released == [] and not cd.LOG_FILE.exists()


def test_a_state_file_that_is_not_the_deployers_is_an_error_not_a_reset(cd):
    cd.STATE_DIR.mkdir(mode=0o700, parents=True)
    cd.STATE_FILE.write_text(json.dumps({"undone_shas": "aaaa"}))
    with pytest.raises(ValueError, match="not a deployer state"):
        cd.tick()


def test_state_and_log_are_private(cd):
    w = cd.world
    w.tick(dt.timedelta(0))
    w.tick(2 * MIN)
    assert stat.S_IMODE(cd.STATE_DIR.stat().st_mode) == 0o700
    for path in (cd.STATE_FILE, cd.LOG_FILE):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    line = events(cd)[-1]
    assert set(line) == {"ts", "kind", "sha", "from_sha", "reason", "result", "unit"}
    assert set(state(cd)) == {"deployed_sha", "deploy_running_unit", "last_seen_head", "last_seen_at",
                              "last_deploy_end_at", "undone_shas"}


# ---- the deploy checkout, for real -----------------------------------------------------------------


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A bare origin with two commits on master, a plain clone of it as the deploy checkout, the live home."""
    cd, _ = fresh_modules(tmp_path, monkeypatch)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    (tmp_path / "gitconfig").write_text("[user]\n\tname = t\n\temail = t@t\n[init]\n\tdefaultBranch = master\n")
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git("init", "--quiet", "--bare", str(origin), cwd=tmp_path)
    git("clone", "--quiet", str(origin), str(work), cwd=tmp_path)
    (work / "standee.yaml").write_text("name: rollcall\nbackup:\n  files: [.env, fixtures/shine_book.json]\n")
    (work / ".gitignore").write_text(".env\nfixtures/shine_book.json\n")
    git("add", ".", cwd=work)
    git("commit", "--quiet", "-m", "one", cwd=work)
    first = git("rev-parse", "HEAD", cwd=work)
    (work / "app.py").write_text("print('two')\n")
    git("add", ".", cwd=work)
    git("commit", "--quiet", "-m", "two", cwd=work)
    second = git("rev-parse", "HEAD", cwd=work)
    git("push", "--quiet", "origin", "HEAD:master", cwd=work)
    home = tmp_path / "prod-home"
    (home / "fixtures").mkdir(parents=True)
    (home / ".env").write_text("NOT_A_SECRET=1\n")
    monkeypatch.setattr(cd, "REPO_URL", str(origin))
    cd.ensure_clone()
    return cd, work, first, second


def test_the_checkout_is_a_plain_clone_detached_at_the_commit_and_clean(repo):
    cd, _, first, second = repo
    assert (cd.CHECKOUT / ".git").is_dir()  # a plain clone, not a wt worktree (whose .git is a file)
    assert cd.fetch_head() == second
    cd.checkout(first)
    assert git("rev-parse", "HEAD", cwd=cd.CHECKOUT) == first
    assert subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=cd.CHECKOUT).returncode == 1  # detached
    env = cd.CHECKOUT / ".env"
    assert env.is_symlink() and os.readlink(env) == str(cd.PROD_HOME / ".env")
    assert os.readlink(cd.CHECKOUT / "fixtures" / "shine_book.json") == str(cd.PROD_HOME / "fixtures" / "shine_book.json")
    assert cd.dirty() == ""
    cd.checkout(second)  # and on to the next, links kept
    assert git("rev-parse", "HEAD", cwd=cd.CHECKOUT) == second


def test_a_checkout_with_changes_is_refused(repo):
    cd, _, first, _ = repo
    (cd.CHECKOUT / "scratch.txt").write_text("left over\n")
    with pytest.raises(cd.CheckoutProblem, match="has changes; refusing to build from it: \\?\\? scratch.txt"):
        cd.checkout(first)


def test_a_commit_that_is_not_on_master_is_refused(repo):
    cd, work, _, second = repo
    (work / "side.py").write_text("x = 1\n")
    git("add", ".", cwd=work)
    git("commit", "--quiet", "-m", "never pushed", cwd=work)
    local_only = git("rev-parse", "HEAD", cwd=work)
    git("fetch", "--quiet", str(work), "HEAD", cwd=cd.CHECKOUT)  # the object exists, but not on origin/master
    cd.fetch_head()
    with pytest.raises(cd.CheckoutProblem, match="is not a commit on origin/master"):
        cd.checkout(local_only)
    with pytest.raises(cd.CheckoutProblem, match="is not a commit on origin/master"):
        cd.checkout("f" * 40)
    assert git("rev-parse", "HEAD", cwd=cd.CHECKOUT) == second  # untouched


def test_a_real_file_where_a_live_link_belongs_is_refused(repo):
    cd, _, first, _ = repo
    (cd.CHECKOUT / ".env").write_text("A_COPY=1\n")  # gitignored, so not "changes": still refused
    with pytest.raises(cd.CheckoutProblem, match="is a file of its own"):
        cd.checkout(first)


def test_a_deploy_from_a_dirty_checkout_is_a_refusal_not_a_failed_release(repo, monkeypatch):
    cd, _, _, second = repo
    released = []
    monkeypatch.setattr(cd, "run_release", lambda sha, kind, reason: released.append(sha) or (0, "ok"))
    (cd.CHECKOUT / "scratch.txt").write_text("left over\n")
    assert cd.deploy(second, "deploy", "by hand") == 1
    assert released == []
    e = json.loads(cd.LOG_FILE.read_text().splitlines()[-1])
    assert (e["kind"], e["result"]) == ("refusal", "refused") and "scratch.txt" in e["reason"]
    st = json.loads(cd.STATE_FILE.read_text())
    assert st["undone_shas"] == [] and st["deployed_sha"] is None and st["deploy_running_unit"] is None
    (cd.CHECKOUT / "scratch.txt").unlink()
    assert cd.deploy(second, "deploy", "by hand") == 0
    assert released == [second] and json.loads(cd.STATE_FILE.read_text())["deployed_sha"] == second


def test_a_worktree_is_not_taken_for_the_clone(repo, tmp_path, monkeypatch):
    cd, work, _, _ = repo
    wt = tmp_path / "a-worktree"
    git("worktree", "add", "--quiet", "--detach", str(wt), cwd=work)
    monkeypatch.setattr(cd, "CHECKOUT", wt)
    with pytest.raises(cd.CheckoutProblem, match="not a plain clone"):
        cd.ensure_clone()


# ---- the release and the unit ----------------------------------------------------------------------


def test_the_release_runs_deploy_prod_from_the_checkout_with_the_live_home(tmp_path, monkeypatch):
    cd, _ = fresh_modules(tmp_path, monkeypatch)
    seen = {}

    class P:
        def __init__(self, cmd, cwd, env, **kw):
            seen.update(cmd=cmd, cwd=cwd, env=env)
            self.stdout = iter(["[18:00:01] backing up\n", "[18:03:00] ERROR: /api/health says ok=False\n",
                                "Undone: images put back. Prod now: healthy\n"])

        def wait(self):
            return 1

    monkeypatch.setattr(cd.subprocess, "Popen", P)
    code, why = cd.run_release(A, "undo", "money test failed on bbbbbbbb")
    assert code == 1 and why == "/api/health says ok=False"
    # --kind undo is deploy_prod's kind undo, the reason goes to its tag; each its own argument
    assert seen["cmd"][-3:] == [A, "undo", "money test failed on bbbbbbbb"]
    assert "epd_loop.deploy_prod(sys.argv[1], kind=sys.argv[2], reason=sys.argv[3])" in seen["cmd"][2]
    seen.clear()
    cd.run_release(A, "deploy", "master aaaaaaaa")
    assert seen["cmd"][-3:] == [A, "forward", "master aaaaaaaa"]
    assert seen["cwd"] == BIN
    assert seen["env"]["EPD_REPO_CHECKOUT"] == str(cd.CHECKOUT)
    assert seen["env"]["EPD_PROD_HOME"] == str(cd.PROD_HOME)


def test_a_deploy_unit_is_detached_with_umask_022_and_no_values_on_its_command_line(tmp_path, monkeypatch):
    cd, _ = fresh_modules(tmp_path, monkeypatch)
    monkeypatch.setenv("EPD_PROD_ENV", "rollcall-cd-rehearsal")
    monkeypatch.setenv("SOME_TOKEN", "do-not-pass-me")
    ran = []
    monkeypatch.setattr(cd.subprocess, "run", lambda cmd, **kw: ran.append((cmd, kw)) or
                        subprocess.CompletedProcess(cmd, 0, "", ""))
    cd.launch(unit(A), A, "master aaaaaaaa, quiet")
    (cmd, kw), = ran
    assert cmd[:2] == ["systemd-run", "--user"]
    assert f"--unit={unit(A)}" in cmd and "--property=UMask=0022" in cmd
    assert f"--property=WorkingDirectory={cd.CHECKOUT}" in cmd
    assert f"--setenv=ROLLCALL_CD_UNIT={unit(A)}" in cmd
    assert "--setenv=EPD_PROD_ENV" in cmd  # by name: systemd-run copies the value
    assert not any("SOME_TOKEN" in a or "do-not-pass-me" in a for a in cmd)
    forwarded = [a.removeprefix("--setenv=") for a in cmd if a.startswith("--setenv=")]
    assert all("=" not in name for name in forwarded if not name.startswith("ROLLCALL_CD_UNIT="))
    i = cmd.index("--")
    assert cmd[i + 2].endswith("configs/epd/bin/rollcall_cd_deploy.py")
    assert cmd[i + 3:] == ["deploy", "--sha", A, "--kind", "deploy", "--reason", "master aaaaaaaa, quiet"]
    assert kw["env"]["XDG_RUNTIME_DIR"]


# ---- notify ----------------------------------------------------------------------------------------


class FakePiWebUI:
    """pi-web-ui's control socket, as docs/script-notice.md describes it: one JSON line in, one out."""

    TOKEN = "test-app-token-not-real"

    def __init__(self, path: Path):
        self.dir = path
        self.got: list[dict] = []
        self.answer = lambda req: {"ok": True, "id": f"rm-{len(self.got):08d}", "duplicate": False}
        self.server = None
        (path / "app-token").write_text(self.TOKEN + "\n")

    def start(self):
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                req = json.loads(self.rfile.readline())
                fake.got.append(req)
                self.wfile.write((json.dumps(fake.answer(req)) + "\n").encode())

        self.server = socketserver.ThreadingUnixStreamServer(str(self.dir / "pi-web-ui.sock"), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            (self.dir / "pi-web-ui.sock").unlink(missing_ok=True)
            self.server = None


@pytest.fixture
def pi_web_ui(monkeypatch):
    # A unix socket path is limited to 108 bytes: a short directory, not pytest's tmp_path.
    path = Path(tempfile.mkdtemp(prefix="cdn", dir="/tmp"))
    monkeypatch.setenv("ROLLCALL_CD_PI_WEB_UI_DIR", str(path))
    fake = FakePiWebUI(path)
    yield fake
    fake.stop()
    shutil.rmtree(path, ignore_errors=True)


def outbox_lines(notify) -> list[dict]:
    return [json.loads(x) for x in notify.OUTBOX.read_text().splitlines()] if notify.OUTBOX.exists() else []


def test_a_role_message_is_a_script_notice_to_pi_web_ui(tmp_path, monkeypatch, pi_web_ui):
    _, notify = fresh_modules(tmp_path, monkeypatch)
    pi_web_ui.start()
    assert notify.role("rollcall", "fyi", "rollcall-cd deploy aaaaaaaa: ok") is True
    (req,) = pi_web_ui.got
    assert set(req) == {"cmd", "token", "role", "kind", "sender", "text", "key"}
    assert (req["cmd"], req["token"], req["role"], req["kind"], req["text"]) == (
        "script_notice", FakePiWebUI.TOKEN, "rollcall", "fyi", "rollcall-cd deploy aaaaaaaa: ok")
    assert req["sender"] == {"id": "rollcall-cd", "title": "RollCall deployer"}
    assert req["key"].startswith("rollcall-cd-") and len(req["key"]) <= 200
    assert notify.role("rollcall", "request", "second", key="undo-bbbbbbbb") is True
    assert pi_web_ui.got[1]["kind"] == "request" and pi_web_ui.got[1]["key"] == "undo-bbbbbbbb"
    assert outbox_lines(notify) == []


def test_a_role_message_waits_in_the_outbox_while_pi_web_ui_is_down_and_goes_first_next_time(
        tmp_path, monkeypatch, pi_web_ui):
    _, notify = fresh_modules(tmp_path, monkeypatch)
    assert notify.role("rollcall", "fyi", "first") is False  # no socket: pi-web-ui is restarting
    assert notify.role("rollcall", "fyi", "second") is False
    lines = outbox_lines(notify)
    assert [(x["text"], x["delivered"], x["refused"]) for x in lines] == [("first", False, False),
                                                                         ("second", False, False)]
    assert "did not answer" in lines[0]["why"]
    assert stat.S_IMODE(notify.OUTBOX.stat().st_mode) == 0o600
    assert FakePiWebUI.TOKEN not in notify.OUTBOX.read_text()
    pi_web_ui.start()
    assert notify.role("rollcall", "fyi", "third") is True
    assert [r["text"] for r in pi_web_ui.got] == ["first", "second", "third"]
    assert [r["key"] for r in pi_web_ui.got[:2]] == [x["key"] for x in lines]  # a resend is a duplicate
    assert outbox_lines(notify) == []


def test_a_refused_notice_is_kept_for_a_person_and_never_sent_again(tmp_path, monkeypatch, pi_web_ui):
    _, notify = fresh_modules(tmp_path, monkeypatch)
    pi_web_ui.start()
    pi_web_ui.answer = lambda req: {"ok": False, "error": "no role named rollcall has a home chat"}
    assert notify.role("rollcall", "fyi", "refused one") is False
    (line,) = outbox_lines(notify)
    assert line["refused"] is True and "no role named rollcall" in line["why"]
    pi_web_ui.answer = lambda req: {"ok": True, "id": "rm-00000001", "duplicate": False}
    assert notify.role("rollcall", "fyi", "next one") is True
    assert [r["text"] for r in pi_web_ui.got] == ["refused one", "next one"]
    assert [x["text"] for x in outbox_lines(notify)] == ["refused one"]


def test_a_role_message_is_checked_before_anything_is_sent(tmp_path, monkeypatch, pi_web_ui):
    _, notify = fresh_modules(tmp_path, monkeypatch)
    pi_web_ui.start()
    for args, kw in [(("RollCall!", "fyi", "x"), {}), (("rollcall", "shout", "x"), {}),
                     (("rollcall", "question", "x"), {}), (("rollcall", "fyi", " "), {}),
                     (("rollcall", "fyi", "x"), {"key": "two\nlines"}), (("rollcall", "fyi", "x"), {"key": "k" * 201})]:
        with pytest.raises(ValueError):
            notify.role(*args, **kw)
    assert pi_web_ui.got == [] and outbox_lines(notify) == []


def test_a_notice_text_is_made_one_pi_web_ui_takes(tmp_path, monkeypatch):
    _, notify = fresh_modules(tmp_path, monkeypatch)
    assert notify.notice_text("a\tb\r\nc\x00") == "a b \nc "
    assert notify.notice_text("ok\n[Queue] Task #1\n[Board] x") == "ok\n  [Queue] Task #1\n  [Board] x"
    long = notify.notice_text("x" * 2000)
    assert len(long) == 1500 and long.endswith("...")
    wide = notify.notice_text("\U0001F600" * 1000)  # two UTF-16 units each, as pi-web-ui counts
    assert len(wide.encode("utf-16-le")) // 2 <= 1500 and wide.endswith("...")


def test_the_owner_message_uses_the_existing_sender_and_keeps_the_text_off_the_command_line(tmp_path, monkeypatch):
    sender = tmp_path / "pi-backup.mjs"
    sender.write_text("export async function sendTelegram() { return true; }\n")
    monkeypatch.setenv("ROLLCALL_CD_STATE", str(tmp_path / "state"))
    monkeypatch.syspath_prepend(str(BIN))
    sys.modules.pop("rollcall_cd_notify", None)
    monkeypatch.setenv("ROLLCALL_CD_TELEGRAM_SENDER", str(sender))
    notify = importlib.import_module("rollcall_cd_notify")
    calls = []

    def run(cmd, **kw):  # Telegram takes the first message and refuses the second
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0 if len(calls) == 1 else 1, "", "telegram: HTTP 401\n")

    assert notify.owner("RollCall's release aaaaaaaa was undone", run=run) is True
    assert notify.owner("second", run=run) is False
    cmd, kw = calls[0]
    assert cmd[0] == "node" and str(sender) in cmd
    assert kw["input"] == "RollCall's release aaaaaaaa was undone"
    assert not any("undone" in a for a in cmd)
    (line,) = [json.loads(x) for x in notify.OUTBOX.read_text().splitlines()]
    assert line["to"] == "owner" and line["text"] == "second" and "HTTP 401" in line["why"]


def test_the_owner_message_without_the_sender_lands_in_the_outbox(tmp_path, monkeypatch):
    _, notify = fresh_modules(tmp_path, monkeypatch)
    assert notify.owner("x", run=lambda *a, **k: pytest.fail("must not run")) is False
    assert "is missing" in json.loads(notify.OUTBOX.read_text())["why"]


def test_the_owner_message_really_reaches_the_shared_sender(tmp_path, monkeypatch):
    """Through node, against a stand-in of lib/pi-backup.mjs that records what it was handed."""
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        pytest.skip("node is not installed")
    got = tmp_path / "got.json"
    sender = tmp_path / "pi-backup.mjs"
    sender.write_text(
        "import { writeFileSync } from 'node:fs';\n"
        "export async function sendTelegram(text, opts) {\n"
        f"  writeFileSync({json.dumps(str(got))}, JSON.stringify({{ text, envFile: opts.envFile, "
        "configFile: opts.configFile }));\n  return true;\n}\n")
    monkeypatch.setenv("ROLLCALL_CD_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("ROLLCALL_CD_TELEGRAM_SENDER", str(sender))
    monkeypatch.setenv("ROLLCALL_CD_TEMPER_ENV", str(tmp_path / "temper.env"))
    monkeypatch.syspath_prepend(str(BIN))
    sys.modules.pop("rollcall_cd_notify", None)
    notify = importlib.import_module("rollcall_cd_notify")
    assert notify.owner("release cccccccc is live") is True
    assert json.loads(got.read_text()) == {"text": "release cccccccc is live", "envFile": str(tmp_path / "temper.env"),
                                           "configFile": str(notify.TELEGRAM_CONFIG)}


def test_the_real_sender_is_the_one_agent_tools_exports():
    sender = Path("/home/shinelay/projects/agent-tools/lib/pi-backup.mjs")
    if not sender.exists():
        pytest.skip("agent-tools is not on this machine")
    assert "export async function sendTelegram" in sender.read_text()


# ---- the workflow and its trigger -------------------------------------------------------------------


def test_the_trigger_ticks_every_minute_and_lands_switched_off():
    raw = yaml.safe_load((ROOT / "configs" / "triggers" / "epd_cd.yaml").read_text())
    trigger = parse_trigger(raw, "epd_cd.yaml")
    assert trigger.enabled is False
    assert trigger.workflow == "epd_cd" and trigger.source == "schedule"
    p = scheduler.plan(trigger)
    assert p.every == dt.timedelta(minutes=1) and p.catch_up is False


def test_the_workflow_is_one_script_step_with_no_model():
    flow = yaml.safe_load((ROOT / "configs" / "epd" / "workflows" / "epd_cd.yaml").read_text())["workflow"]
    agent = substitute_env_vars(yaml.safe_load((ROOT / "configs" / "epd" / "agents" / "epd_cd.yaml").read_text()))["agent"]
    assert agent["type"] == "script" and "model" not in agent
    assert '"epd-cd tick"' in agent["script_template"]
    store = ConfigStore()
    store.put("epd_cd", "workflow", flow)
    store.put("epd_cd", "agent", agent)
    loaded, config = GraphLoader(store).load_workflow("epd_cd")
    assert [n.name for n in loaded] == ["tick"] and config.name == "epd_cd"
