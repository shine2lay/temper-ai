"""RollCall's release hook for `wt deploy` (configs/epd/bin/rollcall_cd_deploy.py deploy).

wt deploy decides when and what (agent-tools lib/deploy, tested there); this hook releases one commit from the
deploy clone through epd_loop.deploy_prod and answers with deploy_prod's exit codes. Here the release itself is
a fake; the checkout tests use a real git repository with a bare origin.
"""

from __future__ import annotations

import fcntl
import importlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "epd" / "bin"
A, B = ("a" * 40), ("b" * 40)


def fresh_module(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLLCALL_CD_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("ROLLCALL_CD_CHECKOUT", str(tmp_path / "rollcall-deploy"))
    monkeypatch.setenv("EPD_PROD_HOME", str(tmp_path / "prod-home"))
    monkeypatch.syspath_prepend(str(BIN))
    sys.modules.pop("rollcall_cd_deploy", None)
    cd = importlib.import_module("rollcall_cd_deploy")
    assert cd.STATE_DIR == tmp_path / "state" and cd.CHECKOUT == tmp_path / "rollcall-deploy"
    return cd


@pytest.fixture
def cd(tmp_path, monkeypatch):
    """The hook with the clone and the release faked: `cd.released` lists (sha, kind, reason)."""
    cd = fresh_module(tmp_path, monkeypatch)
    cd.released = []
    cd.checked_out = []
    cd.release_result = (0, "live and healthy")
    monkeypatch.setattr(cd, "ensure_clone", lambda: None)
    monkeypatch.setattr(cd, "fetch_head", lambda: A)
    monkeypatch.setattr(cd, "checkout", lambda sha: cd.checked_out.append(sha))
    monkeypatch.setattr(cd, "run_release", lambda sha, kind, reason: cd.released.append((sha, kind, reason))
                        or cd.release_result)
    # The staging put and the smoke runs: `cd.steps` lists (step, base url, password) in order, `cd.step_codes`
    # sets a step's exit code (default 0, green).
    cd.steps, cd.step_codes = [], {}

    def run_step(argv, *, env=None, ceiling_s):
        step = " ".join(argv[:2])
        cd.steps.append((step, (env or {}).get("ROLLCALL_SMOKE_BASE_URL"), (env or {}).get("ROLLCALL_QA_PASSWORD")))
        code = cd.step_codes.get(step, 0)
        return code, (["FAILED qa/smoke/test_f1_overview.py::test_f1 - net liq differs", "1 failed"] if code else ["ok"])

    monkeypatch.setattr(cd, "run_step", run_step)
    monkeypatch.setattr(cd, "container_secret", lambda container, argv: f"pw-of-{container}")
    fake_gate(cd, monkeypatch)
    return cd


def fake_gate(cd, monkeypatch):
    """The owner-action gate faked: `cd.gated` lists (sha, image); `cd.gate_code` sets its answer (default pass)."""
    og = cd.rollcall_owner_gate
    cd.gated, cd.gate_code = [], og.PASS
    records = {og.PASS: {"tried": 25, "refused": 0, "not_exercisable": 24, "ms": 20000},
               og.BLOCK: {"blocked": 1, "blocked_items": [{"action": "follow_mid", "item_id": "rc-d3b78606",
                                                          "why": "refused_not_allowed", "code": "rule_floor_unknown"}]},
               og.CANNOT_JUDGE: {"reason": "harness file changed since it was pinned: entry.py"}}

    def gate(sha, image):
        cd.gated.append((sha, image))
        return og.Gate(cd.gate_code, records[cd.gate_code])

    monkeypatch.setattr(og, "gate", gate)


# ---- what wt deploy reads: the exit code ------------------------------------------------------------


def test_the_exit_codes_are_the_ones_deploy_prod_names(cd):
    text = (BIN / "epd_loop.py").read_text()
    for name in ("DEPLOY_BUSY", "DEPLOY_REFUSED", "DEPLOY_ALREADY_LIVE"):
        assert f"{name} = {getattr(cd, name)}\n" in text, name
    assert set(cd.RELEASE_KIND) == set(cd.KINDS) and set(cd.RELEASE_KIND.values()) == {"forward", "undo"}
    assert 'RELEASE_KINDS = ("forward", "undo")' in text


def test_a_healthy_release_exits_0_after_one_release_of_that_commit(cd):
    assert cd.deploy(A, "deploy", "master aaaaaaaa, quiet 2m") == 0
    assert cd.checked_out == [A] and cd.released == [(A, "deploy", "master aaaaaaaa, quiet 2m")]


# ---- QA's smoke tests around a release (TEST-SMOKE-BOTH) ---------------------------------------------


def test_green_staging_and_live_smoke_put_staging_first_then_release_then_smoke_prod(cd):
    assert cd.deploy(A, "deploy", "master aaaaaaaa") == 0
    assert cd.steps == [
        ("rollcall-staging put", None, None),
        ("make smoke-before", "http://127.0.0.1:8030", "pw-of-rollcall-staging-rollcall-1"),
        ("make smoke-live", "http://127.0.0.1:8020", "pw-of-rollcall-prod-rollcall-1"),
    ]
    assert cd.released == [(A, "deploy", "master aaaaaaaa")]


@pytest.mark.parametrize("red", ["rollcall-staging put", "make smoke-before"])
def test_a_red_staging_put_or_smoke_before_stops_before_prod(cd, red, capsys):
    cd.step_codes[red] = 1
    assert cd.deploy(A, "deploy", "master aaaaaaaa") == 1
    assert cd.released == []  # prod untouched
    assert [s[0] for s in cd.steps][-1] == red and "make smoke-live" not in [s[0] for s in cd.steps]
    out = capsys.readouterr().out
    assert "stopped before prod" in out and "prod was not touched" in out
    assert "pw-of-" not in out  # the password is never printed


def test_a_red_live_smoke_exits_1_after_the_release_naming_the_last_good_commit(cd, monkeypatch, capsys):
    monkeypatch.setenv("DEPLOY_LIVE_SHA", B)
    cd.step_codes["make smoke-live"] = 1
    assert cd.deploy(A, "deploy", "master aaaaaaaa") == 1  # wt deploy's undo hook puts B back
    assert cd.released == [(A, "deploy", "master aaaaaaaa")]
    out = capsys.readouterr().out
    assert f"last good commit {B[:12]} back" in out and "FAILED qa/smoke/test_f1_overview.py" in out
    assert "pw-of-" not in out


# ---- RollCall's owner-action gate between staging and prod (rollcall #61) ----------------------------


def test_a_passing_gate_runs_on_the_staging_image_after_smoke_before_and_the_release_goes_on(cd, capsys):
    assert cd.deploy(A, "deploy", "master aaaaaaaa") == 0
    assert cd.gated == [(A, "rollcall:rollcall-staging")]
    assert cd.released == [(A, "deploy", "master aaaaaaaa")]
    assert "owner-action gate passed: tried 25" in capsys.readouterr().out


def test_a_gate_block_stops_the_release_before_prod(cd, capsys):
    cd.gate_code = cd.rollcall_owner_gate.BLOCK
    assert cd.deploy(A, "deploy", "master aaaaaaaa") == 1
    assert cd.released == [] and "make smoke-live" not in [s[0] for s in cd.steps]
    out = capsys.readouterr().out
    assert "stopped before prod: owner-action gate blocked 1: follow_mid on rc-d3b78606" in out
    assert "prod was not touched" in out


def test_a_gate_that_cannot_judge_stops_the_release_before_prod(cd, capsys):
    cd.gate_code = cd.rollcall_owner_gate.CANNOT_JUDGE
    assert cd.deploy(A, "deploy", "master aaaaaaaa") == 1
    assert cd.released == []
    assert "stopped before prod: owner-action gate cannot judge: harness file changed" in capsys.readouterr().out


def test_red_staging_skips_the_gate(cd):
    cd.step_codes["make smoke-before"] = 1
    assert cd.deploy(A, "deploy", "master aaaaaaaa") == 1
    assert cd.gated == []


def test_an_undo_runs_no_smoke_and_a_failed_release_no_live_smoke(cd):
    assert cd.deploy(B, "undo", "smoke-live red on aaaaaaaa") == 0
    assert cd.steps == [] and cd.gated == []  # an undo stays fast: no staging, smoke or owner-action gate
    cd.release_result = (1, "health failed; undone")
    assert cd.deploy(A, "deploy", "master aaaaaaaa") == 1
    assert [s[0] for s in cd.steps] == ["rollcall-staging put", "make smoke-before"]


def test_run_step_stops_a_run_past_its_ceiling(cd, monkeypatch, tmp_path):
    importlib.reload(cd)  # the real run_step
    monkeypatch.setattr(cd, "CHECKOUT", tmp_path)
    code, tail = cd.run_step([sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
                             ceiling_s=0.5)
    assert code == cd.CEILING_EXIT and tail[0] == "started" and "ceiling" in tail[-1]
    assert cd.run_step([sys.executable, "-c", "print('x'); raise SystemExit(3)"], ceiling_s=30) == (3, ["x"])


@pytest.mark.parametrize("release_code, exit_code", [
    (77, 0),  # deploy_prod: the commit asked for is live already; nothing changed
    (75, 75),  # deploy_prod's lock is held (epd_loop's own deploy): wt deploy tries again next tick
    (76, 76),  # the order guard refused: the live commit is no ancestor of this one
    (1, 1),  # the release failed (deploy_prod undid it by itself)
])
def test_deploy_prods_answer_is_passed_on_as_wt_deploy_reads_it(cd, release_code, exit_code, capsys):
    cd.release_result = (release_code, "why it ended")
    assert cd.deploy(B, "undo", "money test failed on aaaaaaaa") == exit_code
    assert cd.released == [(B, "undo", "money test failed on aaaaaaaa")]
    if exit_code != 0:
        assert f"ended {release_code}: why it ended" in capsys.readouterr().out


def test_a_release_while_the_clone_is_in_use_exits_75_and_changes_nothing(cd):
    cd.STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(cd.CHECKOUT_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert cd.deploy(B, "undo", "money test failed on aaaaaaaa") == cd.DEPLOY_BUSY == 75
    finally:
        os.close(fd)
    assert cd.released == [] and cd.checked_out == []
    assert cd.deploy(B, "undo", "again, next tick") == 0  # the lock is not left behind


def test_the_lock_lives_in_a_private_directory(cd):
    cd.deploy(A, "deploy", "x")
    assert stat.S_IMODE(cd.STATE_DIR.stat().st_mode) == 0o700
    assert stat.S_IMODE(cd.CHECKOUT_LOCK.stat().st_mode) == 0o600


@pytest.mark.parametrize("sha, kind, reason, match", [
    ("abc123", "deploy", "x", "full 40-character"),
    (A.upper(), "deploy", "x", "full 40-character"),
    (A, "rollback", "x", "--kind must be one of deploy, undo"),
    (A, "undo", "  ", "--reason must say why"),
])
def test_a_deploy_with_a_bad_argument_fails_before_anything(cd, sha, kind, reason, match):
    with pytest.raises(ValueError, match=match):
        cd.deploy(sha, kind, reason)
    assert cd.released == [] and cd.checked_out == []


def test_the_cli_has_only_the_deploy_verb(cd):
    with pytest.raises(SystemExit) as e:
        cd.main(["tick"])  # the interim tick moved to `wt deploy tick`
    assert e.value.code == 2
    assert cd.main(["deploy", "--sha", A, "--kind", "deploy", "--reason", "by hand"]) == 0
    assert cd.released == [(A, "deploy", "by hand")]


# ---- the deploy clone, for real ---------------------------------------------------------------------


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A bare origin with two commits on master, a plain clone of it as the deploy clone, the live home."""
    cd = fresh_module(tmp_path, monkeypatch)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    (tmp_path / "gitconfig").write_text("[user]\n\tname = t\n\temail = t@t\n[init]\n\tdefaultBranch = master\n")
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git("init", "--quiet", "--bare", str(origin), cwd=tmp_path)
    git("clone", "--quiet", str(origin), str(work), cwd=tmp_path)
    (work / "standee.yaml").write_text(
        "name: rollcall\nbackup:\n  files: [.env, fixtures/shine_book.json]\n  cold_files: [data/backtest.db]\n"
    )
    (work / ".gitignore").write_text(".env\nfixtures/shine_book.json\n*.db\n")
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
    monkeypatch.setattr(cd, "run_step", lambda argv, *, env=None, ceiling_s: (0, ["ok"]))  # staging + smoke: green
    monkeypatch.setattr(cd, "container_secret", lambda container, argv: "")
    fake_gate(cd, monkeypatch)
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
    # backup.cold_files too: the live cache the container mounts at /app/data, linked even while absent
    cold = cd.CHECKOUT / "data" / "backtest.db"
    assert os.readlink(cold) == str(cd.PROD_HOME / "data" / "backtest.db") and not cold.exists()
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


def test_a_deploy_from_a_dirty_clone_is_refused_before_any_release(repo, monkeypatch, capsys):
    cd, _, _, second = repo
    released = []
    monkeypatch.setattr(cd, "run_release", lambda sha, kind, reason: released.append(sha) or (0, "ok"))
    (cd.CHECKOUT / "scratch.txt").write_text("left over\n")
    assert cd.deploy(second, "deploy", "by hand") == 1
    out = capsys.readouterr().out
    assert released == [] and "refused:" in out and "scratch.txt" in out
    (cd.CHECKOUT / "scratch.txt").unlink()
    assert cd.deploy(second, "deploy", "by hand") == 0
    assert released == [second] and git("rev-parse", "HEAD", cwd=cd.CHECKOUT) == second


def test_a_worktree_is_not_taken_for_the_clone(repo, tmp_path, monkeypatch):
    cd, work, _, _ = repo
    wt = tmp_path / "a-worktree"
    git("worktree", "add", "--quiet", "--detach", str(wt), cwd=work)
    monkeypatch.setattr(cd, "CHECKOUT", wt)
    with pytest.raises(cd.CheckoutProblem, match="not a plain clone"):
        cd.ensure_clone()


# ---- the release ------------------------------------------------------------------------------------


def test_the_release_runs_deploy_prod_from_the_clone_with_the_live_home(tmp_path, monkeypatch):
    cd = fresh_module(tmp_path, monkeypatch)
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
    # --kind undo is release_prod's kind undo, the reason goes to its tag; each its own argument
    assert seen["cmd"][-3:] == [A, "undo", "money test failed on bbbbbbbb"]
    assert "epd_loop.release_prod(sys.argv[1], kind=sys.argv[2], reason=sys.argv[3])" in seen["cmd"][2]
    seen.clear()
    cd.run_release(A, "deploy", "master aaaaaaaa")
    assert seen["cmd"][-3:] == [A, "forward", "master aaaaaaaa"]
    assert seen["cwd"] == BIN
    assert seen["env"]["EPD_REPO_CHECKOUT"] == str(cd.CHECKOUT)
    assert seen["env"]["EPD_PROD_HOME"] == str(cd.PROD_HOME)


def test_the_hook_finds_host_tools_without_a_login_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    cd = fresh_module(tmp_path, monkeypatch)
    assert str(Path.home() / ".local" / "bin") in os.environ["PATH"].split(os.pathsep)
    assert cd.EXTRA_PATH[0] == str(Path.home() / ".local" / "bin")


def test_the_interim_deployer_is_retired():
    """wt deploy took over the tick, the verdicts and the money-test undo (Systems #112, DESIGN T6)."""
    for gone in ("configs/triggers/epd_cd.yaml", "configs/epd/workflows/epd_cd.yaml",
                 "configs/epd/agents/epd_cd.yaml", "configs/epd/bin/rollcall_cd_verdict.py"):
        assert not (ROOT / gone).exists(), gone
    assert (BIN / "rollcall_cd_money.py").exists()  # wt deploy's ci.critical_check
