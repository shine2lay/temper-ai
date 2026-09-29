"""temper-ci's judgement, without starting anything.

The parts that decide *whether* to run a whole temper — a docs-only commit,
a tree that already passed, a commit already answered for, who is allowed to
have pushed it — are the parts that keep the gate quick and keep a stranger's
code off this machine. They are all pure enough to test in milliseconds, so
they are tested here, in temper's own suite, which the gate itself runs.

The stack and the smoke set are not tested here: their test is doing it for
real, which is what `temper-ci check` is.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def ci(tmp_path, monkeypatch):
    """temper_ci with its state in a scratch folder, freshly imported."""
    monkeypatch.setenv("TEMPER_CI_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("TEMPER_CI_REPORTS", str(tmp_path / "reports"))
    for name in [m for m in sys.modules if m.startswith("temper_ci")]:
        del sys.modules[name]
    import temper_ci  # noqa: PLC0415
    from temper_ci import gate, paths, stack  # noqa: PLC0415

    paths.ensure_dirs()
    return temper_ci, gate, paths, stack


# -- passing at once ---------------------------------------------------------

@pytest.mark.parametrize("files, docs_only", [
    (["docs/ci-gate.md"], True),
    (["README.md", "docs/a.md", "docs/img/shot.png"], True),
    (["CHANGELOG.txt"], True),
    (["docs/ci-gate.md", "temper_ai/api/routes.py"], False),
    (["configs/workflows/ci_smoke.yaml"], False),
    ([".github/workflows/ci.yml"], False),
    (["scripts/temper_ci/smoke.py"], False),
    ([], False),          # a commit that changed nothing still gets looked at
    (["docs/x.md", "uv.lock"], False),
])
def test_only_writing_passes_at_once(ci, files, docs_only):
    """Writing changes nothing a run reads; anything else gets a real stack.

    The list is deliberately unforgiving: a workflow YAML, a lock file or a
    script under scripts/ all change what a run does, however docs-ish they
    look.
    """
    _, _, _, stack = ci
    assert stack.docs_only(files) is docs_only


def test_a_tree_that_already_passed_is_not_run_again(ci):
    """A rebase that changed no file, or a revert to a known-good tree, is the
    same code as something that already passed — and a rollback has to be
    quick, because temper is unwell while it waits."""
    _, gate, _, _ = ci
    gate.remember("a" * 40, {"ok": True, "tree": "t1", "finished_at": "2026-01-01T00:00:00+00:00"})
    assert gate.passed_trees() == {"t1": "a" * 40}
    # A failure never lends its tree to anything.
    gate.remember("b" * 40, {"ok": False, "tree": "t2", "finished_at": "2026-01-01T00:01:00+00:00"})
    assert "t2" not in gate.passed_trees()
    # And the first commit to pass with a tree keeps the credit.
    gate.remember("c" * 40, {"ok": True, "tree": "t1", "finished_at": "2026-01-01T00:02:00+00:00"})
    assert gate.passed_trees()["t1"] == "a" * 40


def test_what_it_remembers_stays_small(ci):
    """Hundreds of commits later it must still be a file you can read."""
    _, gate, _, _ = ci
    for i in range(230):
        gate.remember(f"{i:040x}", {"ok": True, "tree": f"t{i}", "finished_at": f"2026-01-01T00:{i % 60:02d}:00+00:00"})
    commits = gate.state()["commits"]
    assert len(commits) == 200
    assert gate.state()["last"]["sha"] == f"{229:040x}"


# -- the queue ---------------------------------------------------------------

def test_a_land_can_ask_for_a_commit_without_waiting_for_github(ci):
    """`wt land` says "here is the commit" the moment it pushes, so the check
    starts at once instead of waiting for GitHub's event feed."""
    _, gate, _, _ = ci
    gate.ask_for("d" * 40, "ci-gate", "wt land")
    rows = gate.queued()
    assert [r["sha"] for r in rows] == ["d" * 40]
    assert rows[0]["branch"] == "ci-gate"
    assert rows[0]["asked_at"]


def test_one_check_at_a_time(ci):
    """Two stacks at once would fight over docker and make both slower."""
    _, gate, _, _ = ci
    with gate.one_at_a_time():
        with pytest.raises(BlockingIOError):
            with gate.one_at_a_time(wait=False):
                pass
    # The lock is given back afterwards.
    with gate.one_at_a_time(wait=False):
        pass


# -- who is allowed ----------------------------------------------------------

def test_only_our_own_pushes_to_our_own_branches_are_checked(ci, monkeypatch):
    """The whole reason there is no self-hosted runner: temper-ai is public,
    so a stranger's pull request must never start anything on this machine.
    Only a branch *of this repository*, pushed by someone on the list."""
    _, gate, paths, _ = ci
    events = [
        {"type": "PushEvent", "actor": {"login": paths.ALLOWED_PUSHERS[0]},
         "payload": {"ref": "refs/heads/ci-gate", "head": "1" * 40}},
        {"type": "PushEvent", "actor": {"login": "a-stranger"},
         "payload": {"ref": "refs/heads/sneaky", "head": "2" * 40}},
        {"type": "PullRequestEvent", "actor": {"login": paths.ALLOWED_PUSHERS[0]},
         "payload": {"ref": "refs/heads/pr", "head": "3" * 40}},
        {"type": "PushEvent", "actor": {"login": paths.ALLOWED_PUSHERS[0]},
         "payload": {"ref": "refs/tags/v1", "head": "4" * 40}},
    ]
    monkeypatch.setattr(gate, "gh", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(events), ""))
    got = gate.our_pushes()
    assert [p["sha"] for p in got] == ["1" * 40]
    assert got[0]["branch"] == "ci-gate"


def test_it_starts_again_when_its_own_code_is_landed_over(ci, monkeypatch, tmp_path):
    """What really happened: a fix to the live check landed; the running gate
    still had the old code in memory; the old check failed as it always had;
    and the old rollback reverted the fix. The gate lives in the repository it
    guards, so it has to notice when it has been replaced.
    """
    _, gate, _, _ = ci

    before = gate.own_code_fingerprint()
    assert before, "it must be able to see its own code"
    # Unchanged code: no restart, and the same answer.
    assert gate.restart_if_our_code_changed(before) == before

    started: list[list[str]] = []
    monkeypatch.setattr(gate.os, "execv", lambda exe, argv: started.append(argv))
    gate.restart_if_our_code_changed("something else entirely")
    assert started, "its code changed underneath it and it carried on regardless"

    # And with nothing known yet (first time round) it does not restart.
    started.clear()
    gate.restart_if_our_code_changed("")
    assert not started


def test_a_fresh_gate_leaves_history_alone(ci, monkeypatch):
    """GitHub's event feed hands back the last hundred pushes. On a first start
    that is a pile of commits from before this gate existed \u2014 they have no CI
    compose file and could not pass even in principle. Judging them puts red
    crosses on commits nobody is landing and spends ten minutes each doing it.
    """
    _, gate, paths, _ = ci
    old = {"type": "PushEvent", "actor": {"login": paths.ALLOWED_PUSHERS[0]},
           "created_at": "2020-01-01T00:00:00Z",
           "payload": {"ref": "refs/heads/ancient", "head": "1" * 40}}
    new = {"type": "PushEvent", "actor": {"login": paths.ALLOWED_PUSHERS[0]},
           "created_at": "2099-01-01T00:00:00Z",
           "payload": {"ref": "refs/heads/today", "head": "2" * 40}}
    monkeypatch.setattr(gate, "gh", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, json.dumps([old, new]), ""))

    got = gate.our_pushes()

    assert [p["sha"] for p in got] == ["2" * 40], "it went back over history"
    # And the watermark is remembered, so a restart does not start judging history again.
    first = gate.state()["watching_since"]
    gate.our_pushes()
    assert gate.state()["watching_since"] == first
    assert first.endswith("Z"), "the watermark must be in GitHub's own shape to compare with it"


def test_a_commit_already_answered_for_is_not_checked_again(ci, monkeypatch):
    """Ten minutes of docker for an answer we already have, on every poll."""
    _, gate, _, _ = ci
    gate.remember("e" * 40, {"ok": True, "tree": "t", "finished_at": "2026-01-01T00:00:00+00:00"})
    monkeypatch.setattr(gate, "check", lambda *a, **k: pytest.fail("it checked a commit it already knew"))
    assert gate.check_if_new("e" * 40) is None
    # Nor one GitHub already shows an answer for (another run of the watcher, say).
    monkeypatch.setattr(gate, "already_posted", lambda sha: "failure")
    assert gate.check_if_new("f" * 40) is None


def test_the_status_it_posts_is_the_one_protection_waits_for(ci, monkeypatch):
    """The name has to match the required check on GitHub exactly, or master
    would wait for a status nobody ever posts."""
    _, gate, paths, _ = ci
    seen = {}

    def fake_gh(*args, **kwargs):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(gate, "gh", fake_gh)
    assert gate.post_status("a" * 40, "success", "all eight passed", "http://127.0.0.1:8434/aaaa/")
    flat = " ".join(seen["args"])
    assert f"repos/{paths.GH_REPO}/statuses/{'a' * 40}" in flat
    assert "context=temper/boxes" in flat
    assert "state=success" in flat
    assert "target_url=http://127.0.0.1:8434/aaaa/" in flat


def test_a_description_too_long_for_github_is_cut_not_refused(ci, monkeypatch):
    """GitHub refuses a description over 140 characters, and a failure with a
    long reason is exactly when the status matters most."""
    _, gate, _, _ = ci
    seen = {}
    monkeypatch.setattr(gate, "gh", lambda *a, **k: (seen.update(args=a), subprocess.CompletedProcess(a, 0, "{}", ""))[1])
    gate.post_status("a" * 40, "failure", "x" * 400)
    description = next(a for a in seen["args"] if a.startswith("description="))
    assert len(description) <= len("description=") + 139
