"""OpenPullRequest: pushes only what it should, where it should, and opens the PR.

The "GitHub" here is a bare repository on disk (remote_template = file://...)
and a MockTransport for the REST API, so the real push path runs end to end.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.github_pr import OpenPullRequest

TOKEN = "ghp_test_token_0123456789abcdefghijklmnop"  # noqa: S105 - a fake token


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text)
    git("add", name, cwd=repo)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"add {name}", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def make_remote(tmp: Path, repo: str, base: str = "staging", seed: str = "seed") -> Path:
    """A bare 'GitHub' repository with one commit on `base`."""
    bare = tmp / "remote" / f"{repo}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    git("init", "-q", "--bare", str(bare))
    work = tmp / "seed" / repo
    work.mkdir(parents=True)
    git("init", "-q", "-b", base, cwd=work)
    commit(work, "README.md", seed)
    git("push", "-q", str(bare), f"{base}:{base}", cwd=work)
    return bare


def make_worktree(tmp: Path, name: str, remote: Path, slug: str, base: str = "staging") -> Path:
    """<root>/repos/<name>/main cloned from remote, and a worktree on branch `slug`."""
    main = tmp / "repos" / name / "main"
    if not main.exists():
        git("clone", "-q", str(remote), str(main))
        # No local branch in the shared clone, so any name is free for a worktree
        git("checkout", "-q", "--detach", f"origin/{base}", cwd=main)
        for local in git("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=main).split():
            git("branch", "-q", "-D", local, cwd=main)
    wt = tmp / "repos" / name / "worktrees" / slug
    git("worktree", "add", "-q", "-b", slug, str(wt), f"origin/{base}", cwd=main)
    return wt


class FakeGitHub:
    def __init__(self, open_prs: list[dict] | None = None, post_status: int = 201) -> None:
        self.open_prs = open_prs or []
        self.post_status = post_status
        self.posts: list[dict] = []
        self.auth: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.auth.append(request.headers.get("authorization", ""))
        if request.method == "GET" and request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=self.open_prs)
        if request.method == "POST" and request.url.path.endswith("/pulls"):
            body = json.loads(request.content)
            self.posts.append(body)
            if self.post_status != 201:
                return httpx.Response(self.post_status, json={"message": "Validation Failed"})
            return httpx.Response(201, json={"html_url": "https://github.com/x/pull/7", "number": 7})
        return httpx.Response(404)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPER_GITHUB_TOKEN", TOKEN)
    remote = make_remote(tmp_path, "shine2lay/roamee")
    wt = make_worktree(tmp_path, "roamee", remote, "roa-5")
    head = commit(wt, "fix.txt", "the fix")
    github = FakeGitHub()

    def tool(**config):
        t = OpenPullRequest(config={
            "roots": [str(tmp_path / "repos")],
            "remote_template": f"file://{tmp_path}/remote/{{repo}}.git",
            "api_url": "https://api.github.test",
            **config,
        })
        t._transport = httpx.MockTransport(github.handler)
        return t

    return {"tmp": tmp_path, "remote": remote, "wt": wt, "head": head, "github": github, "tool": tool}


def call(tool, **params):
    args = {"repo": "shine2lay/roamee", "base": "staging", "title": "Fix ROA-5", "body": "Fixes ROA-5", **params}
    return tool.execute(**args)


def test_it_is_registered():
    assert TOOL_CLASSES["OpenPullRequest"] is OpenPullRequest


def test_pushes_the_branch_and_opens_the_pr(env):
    result = call(env["tool"](), worktree=str(env["wt"]))
    assert result.success, result.error
    out = json.loads(result.result)
    assert out["url"] == "https://github.com/x/pull/7"
    assert out["created"] is True and out["branch"] == "roa-5" and out["head"] == env["head"]
    assert git("rev-parse", "refs/heads/roa-5", cwd=env["remote"]) == env["head"]
    assert env["github"].posts == [{"title": "Fix ROA-5", "head": "roa-5", "base": "staging",
                                    "body": "Fixes ROA-5", "draft": False}]
    assert all(a == f"Bearer {TOKEN}" for a in env["github"].auth)


def test_an_open_pr_is_returned_and_gets_the_new_commits(env):
    env["github"].open_prs = [{"html_url": "https://github.com/x/pull/3", "number": 3}]
    result = call(env["tool"](), worktree=str(env["wt"]))
    assert result.success, result.error
    out = json.loads(result.result)
    assert (out["number"], out["created"]) == (3, False)
    assert env["github"].posts == []
    assert git("rev-parse", "refs/heads/roa-5", cwd=env["remote"]) == env["head"]


def test_it_never_merges_or_touches_the_base(env):
    before = git("rev-parse", "refs/heads/staging", cwd=env["remote"])
    assert call(env["tool"](), worktree=str(env["wt"])).success
    assert git("rev-parse", "refs/heads/staging", cwd=env["remote"]) == before


def test_no_token_no_push(env, monkeypatch):
    monkeypatch.delenv("TEMPER_GITHUB_TOKEN")
    result = call(env["tool"](), worktree=str(env["wt"]))
    assert not result.success and "TEMPER_GITHUB_TOKEN is not set" in result.error


def test_a_repo_off_the_allowlist_is_refused(env):
    result = call(env["tool"](repos=["shine2lay/temper-ai"]), worktree=str(env["wt"]))
    assert not result.success and "not a repository temper may open PRs on" in result.error


def test_a_worktree_of_another_repo_is_refused(env):
    # roamee's worktree, named as temper-ai: the path says which clone it is
    result = call(env["tool"](), repo="shine2lay/temper-ai", worktree=str(env["wt"]))
    assert not result.success and "is not a worktree of shine2lay/temper-ai" in result.error


def test_history_from_another_repo_is_not_pushed(env):
    # A worktree sitting where temper-ai's would, holding roamee's commits: a private
    # repo's code must not reach a public one because of where a directory is.
    tmp = env["tmp"]
    make_remote(tmp, "shine2lay/temper-ai", base="master", seed="temper")
    wt = make_worktree(tmp, "temper-ai", env["remote"], "leak")
    commit(wt, "x.txt", "roamee code")
    result = call(env["tool"](), repo="shine2lay/temper-ai", base="master", worktree=str(wt))
    assert not result.success and "shares no history" in result.error
    assert "leak" not in git("branch", "--list", cwd=tmp / "remote" / "shine2lay/temper-ai.git")


def test_outside_the_workspaces_is_refused(env, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    result = call(env["tool"](), worktree=str(elsewhere))
    assert not result.success and "outside the workspaces" in result.error


@pytest.mark.parametrize("branch", ["main", "master", "production", "release/1.2"])
def test_protected_branches_are_refused(env, branch):
    main = env["tmp"] / "repos" / "roamee" / "main"
    wt = env["tmp"] / "repos" / "roamee" / "worktrees" / "p"
    git("worktree", "add", "-q", "-b", branch, str(wt), "origin/staging", cwd=main)
    commit(wt, "p.txt", "p")
    result = call(env["tool"](), worktree=str(wt))
    assert not result.success and "protected branch" in result.error


def test_the_base_branch_itself_is_refused(env):
    main = env["tmp"] / "repos" / "roamee" / "main"
    wt = env["tmp"] / "repos" / "roamee" / "worktrees" / "b"
    git("worktree", "add", "-q", "-b", "topic", str(wt), "origin/staging", cwd=main)
    result = call(env["tool"](), worktree=str(wt), base="topic")
    assert not result.success and "itself" in result.error


def test_nothing_to_push_is_refused(env):
    main = env["tmp"] / "repos" / "roamee" / "main"
    wt = env["tmp"] / "repos" / "roamee" / "worktrees" / "empty"
    git("worktree", "add", "-q", "-b", "empty", str(wt), "origin/staging", cwd=main)
    result = call(env["tool"](), worktree=str(wt))
    assert not result.success and "no commits" in result.error


def test_the_worktrees_hooks_and_config_do_not_run(env):
    # The implementer had a shell in the worktree: its hooks and url rewrites stay there.
    tmp, wt = env["tmp"], env["wt"]
    hooks = tmp / "evil-hooks"
    hooks.mkdir()
    marker = tmp / "hook-ran"
    (hooks / "pre-push").write_text(f"#!/bin/sh\necho ran > {marker}\n")
    (hooks / "pre-push").chmod(0o755)
    git("config", "core.hooksPath", str(hooks), cwd=wt)
    decoy = make_remote(tmp, "evil/decoy")
    git("config", f"url.file://{decoy}.insteadOf", f"file://{tmp}/remote/shine2lay/roamee.git", cwd=wt)
    result = call(env["tool"](), worktree=str(wt))
    assert result.success, result.error
    assert not marker.exists()
    assert git("rev-parse", "refs/heads/roa-5", cwd=env["remote"]) == env["head"]
    assert "roa-5" not in git("branch", "--list", cwd=decoy)


def test_a_rejected_push_is_not_forced(env):
    # Someone else moved the remote branch: the push fails and the remote keeps their commit.
    tmp = env["tmp"]
    other = tmp / "other"
    git("clone", "-q", "-b", "staging", str(env["remote"]), str(other))
    git("checkout", "-q", "-b", "roa-5", cwd=other)
    theirs = commit(other, "theirs.txt", "someone else")
    git("push", "-q", "origin", "roa-5", cwd=other)
    result = call(env["tool"](), worktree=str(env["wt"]))
    assert not result.success and "refused the push" in result.error and "never forced" in result.error
    assert git("rev-parse", "refs/heads/roa-5", cwd=env["remote"]) == theirs
    assert env["github"].posts == []


def test_the_token_never_appears_in_an_error(env):
    env["github"].post_status = 500
    result = call(env["tool"](), worktree=str(env["wt"]))
    assert not result.success
    assert TOKEN not in (result.error or "")
