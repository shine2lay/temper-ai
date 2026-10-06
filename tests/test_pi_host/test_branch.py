"""temper-pi-host's branch verb (ADR-M4-12): create-only ``team/<trial id>`` in a source repo
under the project roots, from a team member's git copy under the Pi state root.  Throwaway
git repos only."""

from __future__ import annotations

import os
import subprocess

import pytest

from .support import Host, ask_in_process, branch_of, git, make_leader, make_source, tph

TRIAL = "0123456789ab"


@pytest.fixture
def host():
    h = Host()
    yield h
    h.cleanup()


@pytest.fixture
def setup(host):
    """A source repo under the project roots, a leader copy with one new commit, a config."""
    projects = host.root / "projects"
    source = projects / "app"
    start = make_source(source)
    leader, commit = make_leader(host.state, source)
    cfg = host.cfg(bridge=None, project_roots=[str(projects) + "/*"], branch_enabled=True)
    return cfg, source, leader, commit, start


def branch(cfg, repo, leader, commit, trial=TRIAL) -> str:
    return tph.make_branch(cfg, str(repo), str(leader), commit, trial)[0]


def test_made(setup, host):
    cfg, source, leader, commit, start = setup
    hook_mark = host.root / "hook-ran"
    hook = source / ".git" / "hooks" / "reference-transaction"
    hook.write_text(f"#!/bin/sh\ntouch {hook_mark}\n")
    hook.chmod(0o755)
    assert branch(cfg, source, leader, commit) == "made"
    assert branch_of(source, TRIAL) == commit
    # Create-only: no checkout, no change to HEAD or the work tree, no temp ref left, no hook.
    assert git("-C", str(source), "rev-parse", "HEAD") == start
    assert git("-C", str(source), "status", "--porcelain") == ""
    assert not (source / "change.txt").exists()
    assert git("-C", str(source), "for-each-ref", "refs/temper") == ""
    assert not hook_mark.exists()


def test_made_through_the_socket(setup, host):
    cfg, source, leader, commit, _ = setup
    helper = tph.Helper(cfg)
    assert ask_in_process(helper, f"branch {source} {leader} {commit} {TRIAL}") == "made"
    assert branch_of(source, TRIAL) == commit


def test_a_branch_already_at_the_commit_counts_as_made(setup):
    cfg, source, leader, commit, _ = setup
    assert branch(cfg, source, leader, commit) == "made"
    assert branch(cfg, source, leader, commit) == "made"


def test_exists_never_moves_a_branch(setup):
    cfg, source, leader, commit, start = setup
    git("-C", str(source), "update-ref", f"refs/heads/team/{TRIAL}", start)
    assert branch(cfg, source, leader, commit) == "exists"
    assert branch_of(source, TRIAL) == start


def test_off(setup):
    cfg, source, leader, commit, _ = setup
    off = tph.parse_config({**_raw(cfg), "branch_enabled": False})
    assert branch(off, source, leader, commit) == "denied the branch verb is off"
    assert branch_of(source, TRIAL) == ""


def test_too_large(setup, host):
    cfg, source, _, _, _ = setup
    leader, commit = make_leader(host.state, source, member="big", extra_bytes=256 * 1024)
    small = tph.parse_config({**_raw(cfg), "branch_max_bytes": 64 * 1024})
    answer = branch(small, source, leader, commit)
    assert answer.startswith("denied branch not made: too large (") and answer.endswith(", cap 65536)")
    assert branch_of(source, TRIAL) == ""
    done = subprocess.run(["git", "-C", str(source), "cat-file", "-e", commit], capture_output=True, check=False)
    assert done.returncode != 0  # nothing was fetched
    assert branch(cfg, source, leader, commit) == "made"  # under the default cap


def test_repo_outside_the_roots(setup, host):
    cfg, _, leader, commit, _ = setup
    outside = host.root / "elsewhere" / "app"
    make_source(outside)
    assert branch(cfg, outside, leader, commit) == f"denied {outside} is not under the project roots"
    assert branch_of(outside, TRIAL) == ""


def test_a_link_inside_the_roots_to_a_repo_outside(setup, host):
    cfg, _, leader, commit, _ = setup
    outside = host.root / "elsewhere" / "app"
    make_source(outside)
    link = host.root / "projects" / "link"
    link.symlink_to(outside)
    assert branch(cfg, link, leader, commit) == f"denied {link} resolves outside the project roots"
    assert branch_of(outside, TRIAL) == ""


def test_a_folder_that_is_not_a_repo(setup, host):
    cfg, _, leader, commit, _ = setup
    plain = host.root / "projects" / "plain"
    plain.mkdir()
    assert branch(cfg, plain, leader, commit) == f"denied {plain} is not the top of a git work tree"


def test_a_repo_whose_git_folder_is_outside_the_roots(setup, host):
    cfg, _, leader, commit, _ = setup
    repo = host.root / "projects" / "split"
    (host.root / "gitdirs").mkdir()
    git("init", "-q", "--separate-git-dir", str(host.root / "gitdirs" / "split.git"), str(repo))
    assert branch(cfg, repo, leader, commit) == f"denied {repo} keeps its git folder outside the project roots"


@pytest.mark.parametrize("shape", ["outside", "wrong_shape", "alternates", "not_git"])
def test_leader_refusals(setup, host, shape):
    cfg, source, leader, commit, _ = setup
    if shape == "outside":
        bad = host.root / "elsewhere.git"
        git("init", "-q", "--bare", str(bad))
        expected = f"denied {bad} is not under the Pi state root"
    elif shape == "wrong_shape":
        bad = host.state / "run1" / "lead.git"
        git("init", "-q", "--bare", str(bad))
        expected = f"denied {bad} is not a team member's git copy (<run>/<team>/git/<name>.git) under the Pi state root"
    elif shape == "alternates":
        bad = leader
        (leader / "objects" / "info").mkdir(parents=True, exist_ok=True)
        (leader / "objects" / "info" / "alternates").write_text("/somewhere/objects\n")
        expected = f"denied {bad} borrows objects from elsewhere (alternates)"
    else:
        bad = host.state / "run1" / "team1" / "git" / "empty.git"
        bad.mkdir()
        expected = f"denied {bad} is not a git folder"
    assert branch(cfg, source, bad, commit) == expected
    assert branch_of(source, TRIAL) == ""


def test_a_commit_the_leader_lacks(setup):
    cfg, source, leader, _, _ = setup
    assert branch(cfg, source, leader, "f" * 40) == "denied the commit is not in the leader's copy"


@pytest.mark.parametrize("commit, trial, expected", [
    ("abc", TRIAL, "denied the commit is not a full 40-character id"),
    ("A" * 40, TRIAL, "denied the commit is not a full 40-character id"),
    (None, "../x", "denied the trial id is malformed"),
    (None, "0123456789AB", "denied the trial id is malformed"),
])
def test_malformed(setup, commit, trial, expected):
    cfg, source, leader, good, _ = setup
    assert branch(cfg, source, leader, commit or good, trial) == expected


def test_hardened_git():
    """The flags ADR-M4-12 asks for, on every git the helper runs."""
    flags = " ".join(tph.GIT)
    for flag in ("core.hooksPath=/dev/null", "fetch.fsckObjects=true", "transfer.fsckObjects=true",
                 "protocol.allow=never", "protocol.file.allow=always"):
        assert flag in flags
    env = tph.git_env(tph.parse_config({"socket": "/tmp/x.sock", "pi_state_root": "/tmp/s"}))
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert "safe.directory" not in flags


def _raw(cfg) -> dict:
    """A config's raw form, to change one value."""
    return {"socket": cfg.socket, "uid": cfg.uid, "pi_state_root": cfg.pi_state_root, "home": cfg.home,
            "pi_agent_dir": cfg.pi_agent_dir, "path": list(cfg.path), "pi_cli": list(cfg.pi_cli),
            "base_provider": cfg.base_provider, "allowed_slots": list(cfg.allowed_slots),
            "project_roots": list(cfg.project_roots), "branch_enabled": cfg.branch_enabled,
            "branch_max_bytes": cfg.branch_max_bytes, "tokens_per_hour": cfg.tokens_per_hour,
            "token_timeout_s": cfg.token_timeout_s}
