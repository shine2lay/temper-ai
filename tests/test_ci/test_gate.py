"""temper-ci's judgement, without starting anything.

Which commits the gate looks at, who is allowed to have pushed them, what it
remembers and the status it posts. Since 2026-10-08 a check builds nothing and
starts no temper (one temper only, the live one, and no test copy of it): it
fetches the commit, writes its tree down and posts ``temper/boxes``. All of it
is quick enough to test here, in temper's own suite.
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

def test_a_check_records_the_commit_and_starts_nothing(ci, monkeypatch):
    """The owner's word, 2026-10-08: one temper only, the live one, and no test copy of it.
    A check fetches the commit, writes its tree down and posts temper/boxes; it runs
    nothing but git, and there is no throwaway temper left to build."""
    _, gate, _, stack = ci
    ran: list[tuple] = []
    monkeypatch.setattr(stack, "fetch", lambda: None)
    monkeypatch.setattr(stack, "has_commit", lambda sha: True)
    monkeypatch.setattr(stack, "mirror", lambda: Path("/nonexistent/mirror"))
    monkeypatch.setattr(stack, "changed_files", lambda sha: ["temper_ai/api/routes.py"])
    monkeypatch.setattr(stack, "tree_sha", lambda sha: "t9")
    monkeypatch.setattr(gate, "sh", lambda *a, **k: (
        ran.append(a), subprocess.CompletedProcess(a, 0, "Add a thing\n", ""))[1])
    posted: list[tuple] = []
    monkeypatch.setattr(gate, "post_status", lambda sha, state, said, url="": (
        posted.append((sha, state, said)), True)[1])

    verdict = gate.check("a" * 40, "some-branch")

    assert verdict["ok"] is True
    assert verdict["tree"] == "t9" and verdict["subject"] == "Add a thing"
    assert posted == [("a" * 40, "success", gate.PASSED_SHORT)]
    assert len(gate.PASSED_SHORT) <= 139, "GitHub cuts a status description at 140"
    assert gate.result_for("a" * 40)["ok"] is True, "a revert reads this record"
    assert ran and all(a[0] == "git" for a in ran), f"it ran more than git: {ran}"
    assert not hasattr(stack, "Box")
    root = Path(__file__).resolve().parents[2]
    assert not (root / "docker-compose.ci.yml").exists()
    assert not (root / "scripts/temper_ci/smoke.py").exists()


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
    """Two looks at one commit at once would write over each other's record."""
    _, gate, _, _ = ci
    with gate.one_at_a_time():
        with pytest.raises(BlockingIOError):
            with gate.one_at_a_time(wait=False):
                pass
    # The lock is given back afterwards.
    with gate.one_at_a_time(wait=False):
        pass


# -- who is allowed ----------------------------------------------------------

def test_only_our_own_branches_are_checked_never_forks_or_pull_requests(ci, monkeypatch):
    """The whole reason there is no self-hosted runner: temper-ai is public,
    so a stranger's pull request must never start anything on this machine.
    Only a branch *of this repository* \u2014 which is exactly what ls-remote on
    origin lists, and exactly what nobody without write access can create.
    """
    _, gate, _, _ = ci
    monkeypatch.setattr(gate, "only_we_can_push", lambda: True)
    listing = (
        f"{'1' * 40}\trefs/heads/ci-gate\n"
        f"{'4' * 40}\trefs/tags/v1\n"                  # a tag is not a branch
        f"{'3' * 40}\trefs/pull/7/head\n"              # a pull request, possibly a stranger's
        f"{'5' * 40}\trefs/heads/\n"                   # malformed, ignored
    )
    monkeypatch.setattr(gate, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ""))

    gate.our_pushes()                       # the first look only notes where things are
    listing_moved = f"{'9' * 40}\trefs/heads/ci-gate\n{'3' * 40}\trefs/pull/7/head\n"
    monkeypatch.setattr(gate, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, listing_moved, ""))
    got = gate.our_pushes()

    assert [p["sha"] for p in got] == ["9" * 40]
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


def _heads(gate, monkeypatch, mapping: dict[str, str]) -> None:
    """Make ``git ls-remote --heads origin`` answer with these branches."""
    text = "".join(f"{sha}\trefs/heads/{branch}\n" for branch, sha in mapping.items())
    monkeypatch.setattr(gate, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, text, ""))


def test_a_fresh_gate_notes_where_everything_is_and_checks_nothing(ci, monkeypatch):
    """On the day this was installed the repository had a dozen branches, all
    from before the gate existed. Going back over them would post statuses on
    history nobody asked about.
    """
    _, gate, _, _ = ci
    monkeypatch.setattr(gate, "only_we_can_push", lambda: True)
    _heads(gate, monkeypatch, {"master": "1" * 40, "ancient": "2" * 40})

    assert gate.our_pushes() == [], "it went back over history"
    assert gate.state()["seen_heads"] == {"master": "1" * 40, "ancient": "2" * 40}

    # Nothing moved: still nothing to do.
    assert gate.our_pushes() == []

    # One branch moves, another appears: both are work, the untouched one is not.
    _heads(gate, monkeypatch, {"master": "3" * 40, "ancient": "2" * 40, "new": "4" * 40})
    got = {p["branch"]: p["sha"] for p in gate.our_pushes()}
    assert got == {"master": "3" * 40, "new": "4" * 40}
    assert gate.our_pushes() == [], "it offered the same work twice"

    # A branch that goes away stops being its business.
    _heads(gate, monkeypatch, {"master": "3" * 40})
    assert gate.our_pushes() == []
    assert "new" not in gate.state()["seen_heads"]


def test_it_asks_git_rather_than_githubs_event_feed(ci, monkeypatch):
    """What really happened: a branch was pushed and the gate never saw it.
    GitHub's /events feed is cached hard \u2014 minutes late, and sometimes a push
    never appears on it at all. A gate that finds out about work late, or not
    at all, is one people learn to go round.
    """
    _, gate, _, _ = ci
    asked: list[tuple] = []
    monkeypatch.setattr(gate, "only_we_can_push", lambda: True)
    monkeypatch.setattr(gate, "gh", lambda *a, **k: (
        asked.append(a), subprocess.CompletedProcess(a, 1, "", "should not be asked"))[1])
    _heads(gate, monkeypatch, {"master": "1" * 40})

    gate.our_pushes()
    gate.our_pushes()

    assert not any("events" in str(a) for a in asked), "it is still trusting the cached feed"


def test_it_stops_looking_at_branches_when_someone_new_can_push(ci, monkeypatch):
    """Looking at branch heads is only safe because a branch in this repository
    can only be put there by someone with write access. Give write access to
    someone else and this machine would vouch for their commits on master's
    required check.
    """
    _, gate, paths, _ = ci
    mine = paths.ALLOWED_PUSHERS[0]

    def collaborators(logins):
        body = json.dumps([{"login": n, "permissions": {"push": True}} for n in logins])
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, body, "")

    monkeypatch.setattr(gate, "gh", collaborators([mine]))
    assert gate.only_we_can_push() is True

    monkeypatch.setattr(gate, "gh", collaborators([mine, "a-new-person"]))
    assert gate.only_we_can_push() is False

    _heads(gate, monkeypatch, {"master": "1" * 40})
    assert gate.our_pushes() == [], "it kept checking after the trust boundary moved"


def test_a_commit_already_answered_for_is_not_checked_again(ci, monkeypatch):
    """A second record and a second status for an answer we already have, on every poll."""
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
