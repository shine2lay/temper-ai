"""OpenPullRequest -- push a task's branch and open a pull request for it. Never merges.

The one tool in temper that writes to GitHub. The token is read here, in the
tool, from ``TEMPER_GITHUB_TOKEN`` in the server's environment: an agent's
shell never sees it (the Bash tool strips every ``*_TOKEN`` variable), and
the agent that calls this tool only says which worktree, which base and what
the PR says. What it may push is decided here, not by the model:

* only to a repository on the allowlist (``repos`` in the tool config, else
  ``TEMPER_GITHUB_PR_REPOS``), and only one whose clone the worktree is: the
  worktree has to be ``<workspaces>/repos/<name>/worktrees/<slug>``, with
  ``<name>`` the repository's name, and the branch has to share history with
  the repository's base branch. A worktree of the private roamee cannot be
  pushed to the public temper-ai, whatever the agent asks.
* never to a protected branch (main, master, staging, production, ...), never
  to the base branch, and never a branch with nothing on it;
* never with --force: a push GitHub would reject as non-fast-forward is
  reported, not overwritten.

The push does not run in the worktree. The implementer had a shell in there,
so its git config and hooks are the implementer's: a pre-push hook, a
credential helper, or a ``url.*.insteadOf`` could each hand the token to
someone else. So the branch is fetched into a fresh bare repository that has
no hooks and no config, and pushed from there, with the token passed as an
HTTP header through the environment (not the command line, which any process
may read).

If a PR for the branch is already open, it is returned as it is: a later run
on the same issue pushes new commits to the same PR.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess  # noqa: B404
import tempfile
from pathlib import Path
from typing import Any

import httpx

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

TOKEN_ENV = "TEMPER_GITHUB_TOKEN"  # noqa: S105 - a variable name, not a secret
REPOS_ENV = "TEMPER_GITHUB_PR_REPOS"
DEFAULT_REPOS = ("shine2lay/roamee", "shine2lay/temper-ai")
PROTECTED_BRANCHES = frozenset({
    "main", "master", "staging", "production", "prod", "develop", "dev", "release", "gh-pages",
})
REMOTE_TEMPLATE = "https://github.com/{repo}.git"
API_URL = "https://api.github.com"
GIT_TIMEOUT_S = 300
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class PushRefused(Exception):
    """A rule of this tool says no; the message says which."""


def _workspace_roots() -> list[Path]:
    roots = [Path("/app/workspaces/repos")]
    wd = os.environ.get("WORKSPACE_DIR", "").strip()
    if wd:
        roots.append(Path(wd) / "repos")
    return roots


def _clean_git_env(home: str) -> dict[str, str]:
    """No system or global config, no prompts: only what the command line says."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "HOME": home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
    })
    env.pop(TOKEN_ENV, None)
    return env


class OpenPullRequest(BaseTool):
    """Push a worktree's branch to GitHub and open (or find) its pull request."""

    name = "OpenPullRequest"
    description = (
        "Push the branch checked out in a task's git worktree to GitHub and open a pull "
        "request for it into `base`. Returns the PR's URL. If a PR for the branch is already "
        "open, pushes the new commits and returns that PR. It never merges, never force-pushes, "
        "and refuses protected branches (main, master, staging, ...)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/name of the GitHub repository, e.g. shine2lay/roamee"},
            "worktree": {"type": "string", "description": "Path of the task's git worktree (the build's worktree_path)"},
            "base": {"type": "string", "description": "Branch the PR merges into, e.g. staging or master"},
            "title": {"type": "string", "description": "PR title"},
            "body": {"type": "string", "description": "PR description (markdown)"},
            "draft": {"type": "boolean", "description": "Open as a draft PR (default false)"},
        },
        "required": ["repo", "worktree", "base", "title", "body"],
    }
    modifies_state = True
    local_paths = False  # `worktree` is checked here, against the workspaces root

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._transport: httpx.BaseTransport | None = None  # tests put a MockTransport here

    # --- config ---------------------------------------------------------------------------------

    def _allowed_repos(self) -> set[str]:
        configured = self.config.get("repos")
        if not configured:
            env = os.environ.get(REPOS_ENV, "").strip()
            configured = [r for r in env.split(",") if r.strip()] if env else list(DEFAULT_REPOS)
        return {str(r).strip().lower() for r in configured if str(r).strip()}

    def _roots(self) -> list[Path]:
        configured = self.config.get("roots")
        return [Path(r) for r in configured] if configured else _workspace_roots()

    def _token(self) -> str:
        token = os.environ.get(str(self.config.get("token_env") or TOKEN_ENV), "").strip()
        if not token:
            raise PushRefused(f"{TOKEN_ENV} is not set, so temper cannot push to GitHub")
        return token

    # --- the tool -------------------------------------------------------------------------------

    def execute(self, **params: Any) -> ToolResult:
        try:
            token = self._token()
        except PushRefused as exc:
            return ToolResult(success=False, result="", error=str(exc))
        try:
            outcome = self._open(token, **params)
        except PushRefused as exc:
            return ToolResult(success=False, result="", error=_scrub(str(exc), token))
        except (OSError, subprocess.SubprocessError, httpx.HTTPError) as exc:
            logger.warning("OpenPullRequest failed: %s", _scrub(str(exc), token))
            return ToolResult(success=False, result="", error=_scrub(f"{type(exc).__name__}: {exc}", token))
        return ToolResult(success=True, result=json.dumps(outcome), metadata=outcome)

    def _open(self, token: str, **params: Any) -> dict[str, Any]:
        repo = str(params.get("repo") or "").strip()
        worktree = str(params.get("worktree") or "").strip()
        base = str(params.get("base") or "").strip()
        title = str(params.get("title") or "").strip()
        body = str(params.get("body") or "")
        draft = bool(params.get("draft", False))
        if not (repo and worktree and base and title):
            raise PushRefused("repo, worktree, base and title are all required")

        repo = self._check_repo(repo)
        path = self._check_worktree(worktree, repo)
        branch = self._branch_of(path)
        self._check_branches(branch, base)

        scratch = tempfile.mkdtemp(prefix="temper-pr-")
        try:
            env = _clean_git_env(scratch)
            bare = os.path.join(scratch, "push.git")
            _git(env, "init", "-q", "--bare", bare)
            # From the worktree: objects only. Its config and hooks do not come along.
            _git(env, "-C", bare, "fetch", "-q", "--no-tags", str(path),
                 f"+refs/heads/{branch}:refs/heads/{branch}")
            auth_env = {**env, **_auth_config(token, self._remote(repo))}
            remote = self._remote(repo)
            _git(auth_env, "-C", bare, "fetch", "-q", "--no-tags", remote,
                 f"+refs/heads/{base}:refs/remotes/origin/{base}",
                 hint=f"base branch '{base}' could not be fetched from {repo}")
            shared = _git(env, "-C", bare, "merge-base", f"refs/heads/{branch}", f"refs/remotes/origin/{base}",
                          check=False)
            if shared.returncode != 0 or not shared.stdout.strip():
                raise PushRefused(
                    f"branch '{branch}' shares no history with {repo}'s '{base}': this worktree "
                    f"is not a clone of {repo}, so it is not pushed there")
            ahead = int(_git(env, "-C", bare, "rev-list", "--count",
                             f"refs/remotes/origin/{base}..refs/heads/{branch}").stdout.strip() or 0)
            if ahead == 0:
                raise PushRefused(f"branch '{branch}' has no commits that '{base}' does not have; nothing to open a PR for")
            head_sha = _git(env, "-C", bare, "rev-parse", f"refs/heads/{branch}").stdout.strip()
            pushed = _git(auth_env, "-C", bare, "push", "-q", "--porcelain", remote,
                          f"refs/heads/{branch}:refs/heads/{branch}", check=False)
            if pushed.returncode != 0:
                detail = (pushed.stderr or pushed.stdout).strip()
                raise PushRefused(f"GitHub refused the push of '{branch}' (never forced): {detail[-600:]}")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        pr, created = self._pull_request(token, repo, branch, base, title, body, draft)
        outcome = {
            "url": pr.get("html_url"),
            "number": pr.get("number"),
            "created": created,
            "repo": repo,
            "branch": branch,
            "base": base,
            "head": head_sha,
            "commits_ahead": ahead,
        }
        logger.info("OpenPullRequest: %s #%s (%s) %s", repo, outcome["number"],
                    "opened" if created else "already open", outcome["url"])
        return outcome

    # --- checks ---------------------------------------------------------------------------------

    def _check_repo(self, repo: str) -> str:
        if not _REPO_RE.match(repo):
            raise PushRefused(f"'{repo}' is not an owner/name repository")
        if repo.lower() not in self._allowed_repos():
            raise PushRefused(f"{repo} is not a repository temper may open PRs on "
                              f"(allowed: {', '.join(sorted(self._allowed_repos()))})")
        return repo

    def _check_worktree(self, worktree: str, repo: str) -> Path:
        path = Path(worktree).resolve()
        name = repo.split("/", 1)[1].lower()
        for root in self._roots():
            try:
                rel = path.relative_to(root.resolve())
            except ValueError:
                continue
            parts = rel.parts
            if len(parts) == 3 and parts[0].lower() == name and parts[1] == "worktrees":
                if not (path / ".git").exists():
                    raise PushRefused(f"{path} is not a git worktree")
                return path
            raise PushRefused(f"{path} is not a worktree of {repo} (expected <workspaces>/repos/{name}/worktrees/<slug>)")
        raise PushRefused(f"{path} is outside the workspaces ({', '.join(str(r) for r in self._roots())})")

    def _branch_of(self, path: Path) -> str:
        env = _clean_git_env(tempfile.gettempdir())
        branch = _git(env, "-C", str(path), "symbolic-ref", "-q", "--short", "HEAD", check=False).stdout.strip()
        if not branch:
            raise PushRefused(f"{path} has no branch checked out (detached HEAD)")
        return branch

    @staticmethod
    def _check_branches(branch: str, base: str) -> None:
        for label, value in (("branch", branch), ("base", base)):
            if not _BRANCH_RE.match(value) or ".." in value or value.startswith(("-", "/")):
                raise PushRefused(f"{label} '{value}' is not a branch name temper pushes")
        if branch == base:
            raise PushRefused(f"the worktree is on '{base}' itself; temper only pushes task branches")
        if branch.lower() in PROTECTED_BRANCHES or branch.lower().startswith("release/"):
            raise PushRefused(f"'{branch}' is a protected branch; temper never pushes to it")

    def _remote(self, repo: str) -> str:
        return str(self.config.get("remote_template") or REMOTE_TEMPLATE).format(repo=repo)

    # --- GitHub API -----------------------------------------------------------------------------

    def _pull_request(self, token: str, repo: str, branch: str, base: str, title: str,
                      body: str, draft: bool) -> tuple[dict[str, Any], bool]:
        api = str(self.config.get("api_url") or API_URL).rstrip("/")
        owner = repo.split("/", 1)[0]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(timeout=30.0, headers=headers, transport=self._transport) as client:
            existing = self._open_pr_for(client, api, repo, owner, branch)
            if existing:
                return existing, False
            response = client.post(f"{api}/repos/{repo}/pulls", json={
                "title": title, "head": branch, "base": base, "body": body, "draft": draft,
            })
            if response.status_code == 201:
                return response.json(), True
            if response.status_code == 422:
                again = self._open_pr_for(client, api, repo, owner, branch)
                if again:  # opened between the two calls
                    return again, False
            raise PushRefused(
                f"GitHub did not open the PR ({response.status_code}): {response.text[:500]}")

    @staticmethod
    def _open_pr_for(client: httpx.Client, api: str, repo: str, owner: str, branch: str) -> dict[str, Any] | None:
        response = client.get(f"{api}/repos/{repo}/pulls", params={"head": f"{owner}:{branch}", "state": "open"})
        response.raise_for_status()
        pulls = response.json()
        return pulls[0] if isinstance(pulls, list) and pulls else None


def _auth_config(token: str, remote: str) -> dict[str, str]:
    """The token as an HTTP header for this remote's host, passed through the environment."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    match = re.match(r"^(https?://[^/]+/)", remote)
    key = f"http.{match.group(1)}.extraheader" if match else "http.extraheader"
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": key,
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


def _git(env: dict[str, str], *args: str, check: bool = True, hint: str = "") -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: B603 - fixed argv, no shell
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        capture_output=True, text=True, timeout=GIT_TIMEOUT_S, env=env, check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-600:]
        raise PushRefused(f"{hint or 'git ' + args[0 if args[0] != '-C' else 2]} failed: {detail}")
    return result


def _scrub(text: str, token: str) -> str:
    if not token:
        return text
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return text.replace(token, "***").replace(basic, "***")
