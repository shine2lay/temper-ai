#!/usr/bin/env python3
"""Portable landing attempt for `code_land` (`mode=pr` and `mode=merge`).

Responsibilities:
- Validates inputs and resolves `<owner>/<repo>` from `repo`, `work_dir` `origin`,
  or `prior_pause` (statelessly resuming when Round 1's container/`work_dir` is gone).
- `mode=pr`: idempotently finds or creates the pull request for `<branch> -> <base>`.
- Auto-resolves clean base drift (`mergeable == False`, `mergeable_state` in
  `{"dirty", "behind"}`, or HTTP 405/409 merge conflict) by fetching `origin/<base>`
  and `origin/<branch>` into a clean checkout (shallow-cloning into a disposable temp
  directory when `work_dir` was wiped), running `git merge --no-edit origin/<base>`,
  pushing `new_sha`, recording `auto_resolved=True` + `resolved_files`, and resetting
  check-run polling onto `new_sha` so pre-resolve checks are never reused.
- Aborts unclean merges (`git merge --abort`) without pushing conflict markers and
  emits `action="pause"` naming every conflicting file.
- Enforces `require_checks=true` on `head_sha` via GitHub check-runs API in both
  `mode=pr` and `mode=merge`: waits while pending, pauses (`status="blocked"`,
  `checks.state="none"`) if zero checks appear within `checks_appear_timeout_s`, and
  pauses immediately (`status="paused"`, `checks.state="failed"`) if any check fails.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

import code_checkout  # noqa: E402
from code_land_github import GitHubApiClient, GitHubApiError  # noqa: E402
from code_save import CodeSaveError, parse_strict_bool  # noqa: E402

VALID_MODES = frozenset({"pr", "merge"})
VALID_MERGE_METHODS = frozenset({"squash", "merge", "rebase"})
MAX_AUTO_RESOLVES_PER_ATTEMPT = 5


class CodeLandError(Exception):
    """Raised on hard input, boundary, auth, or missing-repository errors."""


def _parse_positive_float(raw: str | float | int, *, field: str, allow_zero: bool) -> float:
    if isinstance(raw, bool):
        raise CodeLandError(f"invalid {field} {raw!r}: expected numeric seconds")
    try:
        val = float(str(raw).strip() if isinstance(raw, str) else raw)
    except (TypeError, ValueError) as exc:
        raise CodeLandError(f"invalid {field} {raw!r}: expected numeric seconds") from exc
    if not math.isfinite(val) or (val < 0.0 if allow_zero else val <= 0.0):
        op = ">=" if allow_zero else ">"
        raise CodeLandError(f"invalid {field} {raw!r}: must be finite number {op} 0")
    return val


def _parse_prior_pause(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        raise CodeLandError("invalid prior_pause: expected JSON object string")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodeLandError(f"invalid prior_pause JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise CodeLandError("invalid prior_pause: expected JSON object")
    return parsed


def _parse_repo_spec(spec: str) -> tuple[str, str, str, str]:
    cleaned = spec.strip()
    if (
        "/" in cleaned
        and not cleaned.startswith(("http://", "https://", "git@", "ssh://"))
        and not cleaned.endswith(".git")
        and cleaned.count("/") == 1
    ):
        url = f"https://github.com/{cleaned}.git"
    else:
        url = cleaned
    try:
        return code_checkout.parse_and_validate_repo_url(url)
    except code_checkout.CodeCheckoutError as exc:
        raise CodeLandError(f"invalid repo {spec!r}: {exc}") from exc


def _inspect_optional_work_dir(
    work_dir: str,
    *,
    has_fallback_repo: bool,
    env: dict[str, str],
) -> Path | None:
    """Validate `work_dir` boundary; return `Path` if intact on disk or `None` if wiped."""
    if not work_dir or not work_dir.strip():
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in work_dir):
        raise CodeLandError(f"invalid work_dir {work_dir!r}: control characters forbidden")

    raw_path = Path(work_dir)
    if not raw_path.is_absolute() or ".." in raw_path.parts:
        raise CodeLandError(
            f"invalid work_dir {work_dir!r}: must be an absolute path without '..'"
        )
    resolved = raw_path.resolve(strict=False)
    if resolved in {Path("/"), Path("/tmp")}:
        raise CodeLandError(
            f"invalid work_dir {work_dir!r}: must be a dedicated repository directory"
        )

    forbidden_roots: list[tuple[str, Path]] = [
        ("/home/shinelay", code_checkout.FORBIDDEN_HOST_PREFIX),
        ("/app/workspaces", code_checkout.FORBIDDEN_CONTAINER_WORKSPACES),
    ]
    ws = env.get("WORKSPACE_DIR", "").strip()
    if ws:
        ws_path = Path(ws)
        forbidden_roots.append(("WORKSPACE_DIR", ws_path))
        forbidden_roots.append(("WORKSPACE_DIR", ws_path.resolve(strict=False)))

    for label, root in forbidden_roots:
        if code_checkout._is_within(raw_path, root) or code_checkout._is_within(resolved, root):
            raise CodeLandError(
                f"invalid work_dir {work_dir!r}: must not be inside {label} ({root})"
            )

    if not resolved.is_dir() or not (resolved / ".git").exists():
        if has_fallback_repo:
            return None
        raise CodeLandError(
            f"work_dir {work_dir!r} does not exist and no repo input or prior_pause state is available"
        )

    proc = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        if has_fallback_repo:
            return None
        raise CodeLandError(f"work_dir {work_dir!r} is not a valid git working tree")
    return resolved


def _resolve_repo_identity(
    *,
    repo_input: str,
    existing_work_dir: Path | None,
    prior_pause: dict[str, Any],
) -> tuple[str, str, str, str]:
    candidates: list[tuple[str, tuple[str, str, str, str]]] = []
    if repo_input.strip():
        candidates.append(("repo input", _parse_repo_spec(repo_input)))

    if existing_work_dir is not None:
        proc = subprocess.run(
            ["git", "-C", str(existing_work_dir), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            candidates.append(("work_dir origin", _parse_repo_spec(proc.stdout.strip())))

    prior_repo = str(prior_pause.get("repo") or "").strip()
    if prior_repo:
        candidates.append(("prior_pause.repo", _parse_repo_spec(prior_repo)))

    if not candidates:
        raise CodeLandError(
            "cannot determine target repository: provide work_dir, repo, or prior_pause.repo"
        )

    first_label, first_val = candidates[0]
    for other_label, other_val in candidates[1:]:
        if other_val[2].lower() != first_val[2].lower():
            raise CodeLandError(
                f"repository mismatch between {first_label} ('{first_val[2]}') and {other_label} ('{other_val[2]}')"
            )
    return first_val


def _worktree_is_clean(repo_dir: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode == 0 and not proc.stdout.strip()


def _attempt_auto_resolve(
    *,
    client: GitHubApiClient,
    existing_work_dir: Path | None,
    branch: str,
    base: str,
    env: dict[str, str],
) -> dict[str, Any]:
    """Fetch `origin/<base>` + `origin/<branch>` and attempt `git merge --no-edit origin/<base>`."""
    token = client.get_token()
    git_env = code_checkout.build_git_env(token, base_env=env)
    temp_ctx: tempfile.TemporaryDirectory[str] | None = None

    try:
        if existing_work_dir is not None and _worktree_is_clean(existing_work_dir):
            checkout_dir = existing_work_dir
            code_checkout.run_git(
                ["remote", "set-url", "origin", client.https_remote],
                cwd=checkout_dir,
                git_env=git_env,
                token=token,
            )
        else:
            temp_ctx = tempfile.TemporaryDirectory(prefix="temper-land-")
            checkout_dir = Path(temp_ctx.name) / "repo"
            checkout_dir.mkdir(parents=True, exist_ok=True)
            code_checkout.run_git(["init", "--quiet"], cwd=checkout_dir, git_env=git_env, token=token)
            code_checkout.run_git(
                ["remote", "add", "origin", client.https_remote],
                cwd=checkout_dir,
                git_env=git_env,
                token=token,
            )

        code_checkout.run_git(
            ["config", "user.name", "temper-bot"],
            cwd=checkout_dir,
            git_env=git_env,
            token=token,
        )
        code_checkout.run_git(
            ["config", "user.email", "bot@temper.ai"],
            cwd=checkout_dir,
            git_env=git_env,
            token=token,
        )

        fetch_args = ["fetch", "--quiet", "--no-tags"]
        if temp_ctx is not None:
            fetch_args.append("--depth=100")
        fetch_args.extend(
            [
                "origin",
                f"+refs/heads/{base}:refs/remotes/origin/{base}",
                f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
            ]
        )
        code_checkout.run_git(fetch_args, cwd=checkout_dir, git_env=git_env, token=token)

        mb = code_checkout.run_git(
            ["merge-base", f"refs/remotes/origin/{base}", f"refs/remotes/origin/{branch}"],
            cwd=checkout_dir,
            git_env=git_env,
            token=token,
            check=False,
        )
        if mb.returncode != 0:
            is_shallow = code_checkout.run_git(
                ["rev-parse", "--is-shallow-repository"],
                cwd=checkout_dir,
                git_env=git_env,
                token=token,
                check=False,
            )
            if is_shallow.stdout.strip() == "true":
                code_checkout.run_git(
                    [
                        "fetch",
                        "--quiet",
                        "--unshallow",
                        "origin",
                        f"+refs/heads/{base}:refs/remotes/origin/{base}",
                        f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
                    ],
                    cwd=checkout_dir,
                    git_env=git_env,
                    token=token,
                )

        code_checkout.run_git(
            ["checkout", "--quiet", "-B", branch, f"refs/remotes/origin/{branch}"],
            cwd=checkout_dir,
            git_env=git_env,
            token=token,
        )
        old_sha = code_checkout.run_git(
            ["rev-parse", "HEAD"], cwd=checkout_dir, git_env=git_env, token=token
        ).stdout.strip()

        anc = code_checkout.run_git(
            ["merge-base", "--is-ancestor", f"refs/remotes/origin/{base}", "HEAD"],
            cwd=checkout_dir,
            git_env=git_env,
            token=token,
            check=False,
        )
        if anc.returncode == 0:
            return {"outcome": "already_up_to_date", "sha": old_sha}

        merge_proc = code_checkout.run_git(
            ["merge", "--no-edit", f"refs/remotes/origin/{base}"],
            cwd=checkout_dir,
            git_env=git_env,
            token=token,
            check=False,
        )
        if merge_proc.returncode != 0:
            unmerged_proc = code_checkout.run_git(
                ["diff", "--name-only", "--diff-filter=U"],
                cwd=checkout_dir,
                git_env=git_env,
                token=token,
                check=False,
            )
            conflicting = sorted(
                {
                    line.strip()
                    for line in unmerged_proc.stdout.splitlines()
                    if line.strip()
                }
            )
            code_checkout.run_git(
                ["merge", "--abort"],
                cwd=checkout_dir,
                git_env=git_env,
                token=token,
                check=False,
            )
            return {
                "outcome": "conflict",
                "sha": old_sha,
                "conflicting_files": conflicting,
            }

        new_sha = code_checkout.run_git(
            ["rev-parse", "HEAD"], cwd=checkout_dir, git_env=git_env, token=token
        ).stdout.strip()
        diff_proc = code_checkout.run_git(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", old_sha, new_sha],
            cwd=checkout_dir,
            git_env=git_env,
            token=token,
        )
        changed_files = sorted(
            {line.strip() for line in diff_proc.stdout.splitlines() if line.strip()}
        )

        code_checkout.run_git(
            ["push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"],
            cwd=checkout_dir,
            git_env=git_env,
            token=token,
        )
        code_checkout._ensure_no_persisted_credentials(checkout_dir, token)
        return {
            "outcome": "resolved",
            "new_sha": new_sha,
            "resolved_files": changed_files,
        }
    except code_checkout.CodeCheckoutError as exc:
        raise CodeLandError(str(exc)) from exc
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()


def _build_pause_output(
    *,
    repo_slug: str,
    branch: str,
    base: str,
    mode: str,
    merge_method: str,
    require_checks: bool,
    head_sha: str,
    pr_url: str,
    pr_number: int | None,
    status: str,
    reason: str,
    question: str,
    checks_public: dict[str, Any],
    auto_resolved: bool,
    resolved_files: list[str],
    conflicting_files: list[str] | None = None,
) -> dict[str, Any]:
    target_label = f"PR #{pr_number} ({pr_url})" if pr_number else f"{branch} -> {base}"
    summary = f"Landing {repo_slug} {target_label} paused ({reason}) on commit {head_sha[:12]}."
    return {
        "action": "pause",
        "merged": False,
        "sha": head_sha,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "repo": repo_slug,
        "branch": branch,
        "base": base,
        "mode": mode,
        "merge_method": merge_method,
        "require_checks": require_checks,
        "status": status,
        "reason": reason,
        "auto_resolved": auto_resolved,
        "resolved_files": resolved_files,
        "conflicting_files": conflicting_files or [],
        "checks": checks_public,
        "summary": summary,
        "question": question,
        "questions": [
            {
                "id": "land_blocker",
                "header": f"Landing paused: {reason}",
                "question": question,
                "options": [
                    "Resolved on remote — retry landing",
                ],
            }
        ],
    }


def _build_merged_output(
    *,
    repo_slug: str,
    branch: str,
    base: str,
    mode: str,
    merge_method: str,
    require_checks: bool,
    merged_sha: str,
    pr_url: str,
    pr_number: int | None,
    checks_public: dict[str, Any],
    auto_resolved: bool,
    resolved_files: list[str],
) -> dict[str, Any]:
    return {
        "action": "merged",
        "merged": True,
        "sha": merged_sha,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "repo": repo_slug,
        "branch": branch,
        "base": base,
        "mode": mode,
        "merge_method": merge_method,
        "require_checks": require_checks,
        "status": "merged",
        "auto_resolved": auto_resolved,
        "resolved_files": resolved_files,
        "checks": checks_public,
    }


def land_code(
    *,
    work_dir: str = "",
    branch: str,
    base: str = "main",
    mode: str = "pr",
    title: str = "",
    body: str = "",
    merge_method: str = "squash",
    require_checks: str | bool | None = "true",
    repo: str = "",
    poll_interval_s: str | float = "10",
    checks_appear_timeout_s: str | float = "30",
    prior_pause: str | dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute one active landing attempt; return either `action='merged'` or `action='pause'`."""
    environ = dict(env if env is not None else os.environ)
    prior = _parse_prior_pause(prior_pause)

    raw_branch = (branch or str(prior.get("branch") or "")).strip()
    raw_base = (base or str(prior.get("base") or "main")).strip()
    try:
        clean_branch = code_checkout.validate_branch_name(raw_branch, field="branch")
        clean_base = code_checkout.validate_branch_name(raw_base, field="base")
    except code_checkout.CodeCheckoutError as exc:
        raise CodeLandError(str(exc)) from exc
    if clean_branch == clean_base:
        raise CodeLandError(f"branch and base must differ (both were '{clean_branch}')")

    clean_mode = (mode or str(prior.get("mode") or "pr")).strip().lower()
    if clean_mode not in VALID_MODES:
        raise CodeLandError(
            f"invalid mode {mode!r}: expected one of {sorted(VALID_MODES)}"
        )

    clean_merge_method = (
        merge_method or str(prior.get("merge_method") or "squash")
    ).strip().lower()
    if clean_merge_method not in VALID_MERGE_METHODS:
        raise CodeLandError(
            f"invalid merge_method {merge_method!r}: expected one of {sorted(VALID_MERGE_METHODS)}"
        )

    try:
        require_checks_flag = parse_strict_bool(
            require_checks if require_checks not in (None, "") else prior.get("require_checks", "true"),
            field="require_checks",
            default=True,
        )
    except CodeSaveError as exc:
        raise CodeLandError(str(exc)) from exc

    poll_s = _parse_positive_float(poll_interval_s, field="poll_interval_s", allow_zero=False)
    appear_s = _parse_positive_float(
        checks_appear_timeout_s, field="checks_appear_timeout_s", allow_zero=True
    )

    has_fallback_repo = bool(repo.strip() or str(prior.get("repo") or "").strip())
    existing_work_dir = _inspect_optional_work_dir(
        work_dir, has_fallback_repo=has_fallback_repo, env=environ
    )
    owner, repo_name, repo_slug, https_remote = _resolve_repo_identity(
        repo_input=repo,
        existing_work_dir=existing_work_dir,
        prior_pause=prior,
    )

    client = GitHubApiClient(
        owner=owner,
        repo_name=repo_name,
        https_remote=https_remote,
        env=environ,
    )
    try:
        client.verify_repo()
        base_sha = client.get_branch_sha(clean_base)
        if base_sha is None:
            raise CodeLandError(
                f"base branch '{clean_base}' does not exist on origin ({repo_slug})"
            )

        auto_resolved = bool(prior.get("auto_resolved", False))
        resolved_set: set[str] = {
            str(f)
            for f in (prior.get("resolved_files") or [])
            if isinstance(f, str) and f
        }
        auto_resolve_count = 0

        pr_number: int | None = (
            int(prior["pr_number"])
            if prior.get("pr_number") is not None
            else None
        )
        pr_url = str(prior.get("pr_url") or "")

        if clean_mode == "pr":
            head_sha_remote = client.get_branch_sha(clean_branch)
            if head_sha_remote is None and pr_number is None:
                closed_prs = client.find_pulls(
                    branch=clean_branch, base=clean_base, state="closed"
                )
                merged_prs = [p for p in closed_prs if p.get("merged") is True]
                if not merged_prs:
                    raise CodeLandError(
                        f"branch '{clean_branch}' does not exist on origin ({repo_slug})"
                    )
                pr = client.get_pull(int(merged_prs[0]["number"]))
            else:
                pr = client.ensure_open_pull(
                    branch=clean_branch,
                    base=clean_base,
                    title=title,
                    body=body,
                    prior_pr_number=pr_number,
                )
            pr_number = int(pr["number"])
            pr_url = str(pr.get("html_url") or "")
            if pr.get("merged") is True:
                pr_head_sha = str(pr.get("head", {}).get("sha") or "")
                chk = (
                    client.fetch_check_runs(pr_head_sha)
                    if code_checkout.SHA40_RE.fullmatch(pr_head_sha)
                    else {"state": "none", "runs": []}
                )
                merged_sha = str(pr.get("merge_commit_sha") or pr_head_sha)
                return _build_merged_output(
                    repo_slug=repo_slug,
                    branch=clean_branch,
                    base=clean_base,
                    mode=clean_mode,
                    merge_method=clean_merge_method,
                    require_checks=require_checks_flag,
                    merged_sha=merged_sha,
                    pr_url=pr_url,
                    pr_number=pr_number,
                    checks_public={"state": chk["state"], "runs": chk["runs"]},
                    auto_resolved=auto_resolved,
                    resolved_files=sorted(resolved_set),
                )
            head_sha = str(pr.get("head", {}).get("sha") or "")
            if not code_checkout.SHA40_RE.fullmatch(head_sha):
                raise CodeLandError(f"failed to resolve head SHA for PR #{pr_number}")
        else:
            pr_number = None
            pr_url = ""
            branch_sha = client.get_branch_sha(clean_branch)
            if branch_sha is None:
                raise CodeLandError(
                    f"branch '{clean_branch}' does not exist on origin ({repo_slug})"
                )
            head_sha = branch_sha

        sha_watch_started = time.monotonic()
        mergeable_unknown_polls = 0

        while True:
            # 1. Refresh PR / branch state and detect conflicts or external head updates.
            if clean_mode == "pr":
                assert pr_number is not None
                pr = client.get_pull(pr_number)
                pr_url = str(pr.get("html_url") or pr_url)
                if pr.get("merged") is True:
                    chk = client.fetch_check_runs(head_sha)
                    merged_sha = str(pr.get("merge_commit_sha") or head_sha)
                    return _build_merged_output(
                        repo_slug=repo_slug,
                        branch=clean_branch,
                        base=clean_base,
                        mode=clean_mode,
                        merge_method=clean_merge_method,
                        require_checks=require_checks_flag,
                        merged_sha=merged_sha,
                        pr_url=pr_url,
                        pr_number=pr_number,
                        checks_public={"state": chk["state"], "runs": chk["runs"]},
                        auto_resolved=auto_resolved,
                        resolved_files=sorted(resolved_set),
                    )
                latest_head = client.get_branch_sha(clean_branch) or str(
                    pr.get("head", {}).get("sha") or ""
                )
                if code_checkout.SHA40_RE.fullmatch(latest_head) and latest_head != head_sha:
                    head_sha = latest_head
                    sha_watch_started = time.monotonic()

                mergeable = pr.get("mergeable")
                mergeable_state = str(pr.get("mergeable_state") or "").lower()
                if mergeable is False or mergeable_state in {"dirty", "behind"}:
                    if auto_resolve_count >= MAX_AUTO_RESOLVES_PER_ATTEMPT:
                        chk = client.fetch_check_runs(head_sha)
                        return _build_pause_output(
                            repo_slug=repo_slug,
                            branch=clean_branch,
                            base=clean_base,
                            mode=clean_mode,
                            merge_method=clean_merge_method,
                            require_checks=require_checks_flag,
                            head_sha=head_sha,
                            pr_url=pr_url,
                            pr_number=pr_number,
                            status="paused",
                            reason="repeated base drift",
                            question=(
                                f"PR #{pr_number} ({pr_url}) on {repo_slug} ({clean_branch} -> {clean_base}) "
                                f"exceeded {MAX_AUTO_RESOLVES_PER_ATTEMPT} auto-resolve attempts on {head_sha[:12]}. "
                                f"Verify {clean_base} stability and approve to retry."
                            ),
                            checks_public={"state": chk["state"], "runs": chk["runs"]},
                            auto_resolved=auto_resolved,
                            resolved_files=sorted(resolved_set),
                        )

                    res = _attempt_auto_resolve(
                        client=client,
                        existing_work_dir=existing_work_dir,
                        branch=clean_branch,
                        base=clean_base,
                        env=environ,
                    )
                    if res["outcome"] == "resolved":
                        auto_resolve_count += 1
                        auto_resolved = True
                        resolved_set.update(res["resolved_files"])
                        head_sha = res["new_sha"]
                        sha_watch_started = time.monotonic()
                        mergeable_unknown_polls = 0
                        continue
                    if res["outcome"] == "conflict":
                        chk = client.fetch_check_runs(head_sha)
                        files_list = res["conflicting_files"]
                        files_desc = ", ".join(files_list) if files_list else "(unmerged paths)"
                        return _build_pause_output(
                            repo_slug=repo_slug,
                            branch=clean_branch,
                            base=clean_base,
                            mode=clean_mode,
                            merge_method=clean_merge_method,
                            require_checks=require_checks_flag,
                            head_sha=head_sha,
                            pr_url=pr_url,
                            pr_number=pr_number,
                            status="paused",
                            reason="merge conflict",
                            question=(
                                f"Merge conflict on {repo_slug} PR #{pr_number} ({pr_url}) merging "
                                f"'{clean_branch}' ({head_sha[:12]}) into '{clean_base}' in files: {files_desc}. "
                                f"Resolve the conflict on '{clean_branch}', push to origin, and approve to retry."
                            ),
                            checks_public={"state": chk["state"], "runs": chk["runs"]},
                            auto_resolved=auto_resolved,
                            resolved_files=sorted(resolved_set),
                            conflicting_files=files_list,
                        )
            else:
                latest_branch_sha = client.get_branch_sha(clean_branch)
                if latest_branch_sha is None:
                    raise CodeLandError(
                        f"branch '{clean_branch}' disappeared from origin ({repo_slug}) before merge"
                    )
                if latest_branch_sha != head_sha:
                    head_sha = latest_branch_sha
                    sha_watch_started = time.monotonic()

            # 2. Inspect check runs on current `head_sha`.
            check_info = client.fetch_check_runs(head_sha)
            checks_public = {
                "state": check_info["state"],
                "runs": check_info["runs"],
            }

            if require_checks_flag:
                state = check_info["state"]
                if state == "failed":
                    failing_parts = [
                        f"{r['name']} ({r['conclusion']})"
                        + (f" [{r['url']}]" if r.get("url") else "")
                        for r in check_info["failing"]
                    ]
                    failing_desc = "; ".join(failing_parts)
                    pr_clause = f" PR #{pr_number} ({pr_url})" if pr_number else ""
                    return _build_pause_output(
                        repo_slug=repo_slug,
                        branch=clean_branch,
                        base=clean_base,
                        mode=clean_mode,
                        merge_method=clean_merge_method,
                        require_checks=require_checks_flag,
                        head_sha=head_sha,
                        pr_url=pr_url,
                        pr_number=pr_number,
                        status="paused",
                        reason="checks failed",
                        question=(
                            f"Required check(s) failed on {repo_slug}{pr_clause} branch '{clean_branch}' "
                            f"at commit {head_sha[:12]}: {failing_desc}. Fix or rerun the failing check(s) "
                            f"and approve to retry landing."
                        ),
                        checks_public=checks_public,
                        auto_resolved=auto_resolved,
                        resolved_files=sorted(resolved_set),
                    )

                if state == "none":
                    elapsed = time.monotonic() - sha_watch_started
                    if elapsed >= appear_s:
                        pr_clause = f" PR #{pr_number} ({pr_url})" if pr_number else ""
                        return _build_pause_output(
                            repo_slug=repo_slug,
                            branch=clean_branch,
                            base=clean_base,
                            mode=clean_mode,
                            merge_method=clean_merge_method,
                            require_checks=require_checks_flag,
                            head_sha=head_sha,
                            pr_url=pr_url,
                            pr_number=pr_number,
                            status="blocked",
                            reason="no checks reported",
                            question=(
                                f"Blocked: no checks reported on {repo_slug}{pr_clause} branch '{clean_branch}' "
                                f"for commit {head_sha} after {appear_s:g}s (require_checks=true). "
                                f"Trigger CI check runs (or set require_checks=false if repository has no CI) "
                                f"and approve to retry."
                            ),
                            checks_public=checks_public,
                            auto_resolved=auto_resolved,
                            resolved_files=sorted(resolved_set),
                        )
                    sleep_for = min(poll_s, max(0.01, appear_s - elapsed))
                    time.sleep(sleep_for)
                    continue

                if state == "pending":
                    time.sleep(poll_s)
                    continue

            # 3. Checks satisfied (or require_checks=false) -> execute merge!
            if clean_mode == "pr":
                assert pr_number is not None
                status_code, merge_resp = client.merge_pull(
                    pr_number=pr_number,
                    head_sha=head_sha,
                    merge_method=clean_merge_method,
                    commit_title=title,
                )
                if status_code == 200 and merge_resp.get("merged") is True:
                    merged_sha = str(merge_resp.get("sha") or head_sha)
                    return _build_merged_output(
                        repo_slug=repo_slug,
                        branch=clean_branch,
                        base=clean_base,
                        mode=clean_mode,
                        merge_method=clean_merge_method,
                        require_checks=require_checks_flag,
                        merged_sha=merged_sha,
                        pr_url=pr_url,
                        pr_number=pr_number,
                        checks_public=checks_public,
                        auto_resolved=auto_resolved,
                        resolved_files=sorted(resolved_set),
                    )

                # Handle transient 405/409 (mergeable computing, head updated, or base moved).
                refreshed = client.get_pull(pr_number)
                if refreshed.get("merged") is True:
                    merged_sha = str(refreshed.get("merge_commit_sha") or head_sha)
                    return _build_merged_output(
                        repo_slug=repo_slug,
                        branch=clean_branch,
                        base=clean_base,
                        mode=clean_mode,
                        merge_method=clean_merge_method,
                        merged_sha=merged_sha,
                        require_checks=require_checks_flag,
                        pr_url=pr_url,
                        pr_number=pr_number,
                        checks_public=checks_public,
                        auto_resolved=auto_resolved,
                        resolved_files=sorted(resolved_set),
                    )
                new_pr_head = str(refreshed.get("head", {}).get("sha") or "")
                if code_checkout.SHA40_RE.fullmatch(new_pr_head) and new_pr_head != head_sha:
                    head_sha = new_pr_head
                    sha_watch_started = time.monotonic()
                    continue
                if refreshed.get("mergeable") is None and mergeable_unknown_polls < 6:
                    mergeable_unknown_polls += 1
                    time.sleep(min(poll_s, 1.0))
                    continue

                if auto_resolve_count < MAX_AUTO_RESOLVES_PER_ATTEMPT:
                    res = _attempt_auto_resolve(
                        client=client,
                        existing_work_dir=existing_work_dir,
                        branch=clean_branch,
                        base=clean_base,
                        env=environ,
                    )
                    if res["outcome"] == "resolved":
                        auto_resolve_count += 1
                        auto_resolved = True
                        resolved_set.update(res["resolved_files"])
                        head_sha = res["new_sha"]
                        sha_watch_started = time.monotonic()
                        continue
                    if res["outcome"] == "conflict":
                        files_list = res["conflicting_files"]
                        files_desc = ", ".join(files_list) if files_list else "(unmerged paths)"
                        return _build_pause_output(
                            repo_slug=repo_slug,
                            branch=clean_branch,
                            base=clean_base,
                            mode=clean_mode,
                            merge_method=clean_merge_method,
                            require_checks=require_checks_flag,
                            head_sha=head_sha,
                            pr_url=pr_url,
                            pr_number=pr_number,
                            status="paused",
                            reason="merge conflict",
                            question=(
                                f"Merge conflict on {repo_slug} PR #{pr_number} ({pr_url}) merging "
                                f"'{clean_branch}' ({head_sha[:12]}) into '{clean_base}' in files: {files_desc}. "
                                f"Resolve the conflict on '{clean_branch}', push to origin, and approve to retry."
                            ),
                            checks_public=checks_public,
                            auto_resolved=auto_resolved,
                            resolved_files=sorted(resolved_set),
                            conflicting_files=files_list,
                        )

                refusal_msg = str(merge_resp.get("message") or f"HTTP {status_code}")
                return _build_pause_output(
                    repo_slug=repo_slug,
                    branch=clean_branch,
                    base=clean_base,
                    mode=clean_mode,
                    merge_method=clean_merge_method,
                    require_checks=require_checks_flag,
                    head_sha=head_sha,
                    pr_url=pr_url,
                    pr_number=pr_number,
                    status="blocked",
                    reason="merge blocked",
                    question=(
                        f"GitHub refused merge for {repo_slug} PR #{pr_number} ({pr_url}) "
                        f"on {head_sha[:12]}: {refusal_msg}. Satisfy repository branch "
                        f"protection / review requirements and approve to retry."
                    ),
                    checks_public=checks_public,
                    auto_resolved=auto_resolved,
                    resolved_files=sorted(resolved_set),
                )

            # mode == "merge"
            status_code, merge_resp = client.merge_branch(
                base=clean_base,
                head_sha=head_sha,
                commit_message=title or f"Merge {clean_branch} into {clean_base}",
            )
            if status_code == 201:
                merged_sha = str(merge_resp.get("sha") or head_sha)
                return _build_merged_output(
                    repo_slug=repo_slug,
                    branch=clean_branch,
                    base=clean_base,
                    mode=clean_mode,
                    merge_method=clean_merge_method,
                    require_checks=require_checks_flag,
                    merged_sha=merged_sha,
                    pr_url="",
                    pr_number=None,
                    checks_public=checks_public,
                    auto_resolved=auto_resolved,
                    resolved_files=sorted(resolved_set),
                )
            if status_code == 204:
                current_base_sha = client.get_branch_sha(clean_base) or head_sha
                return _build_merged_output(
                    repo_slug=repo_slug,
                    branch=clean_branch,
                    base=clean_base,
                    mode=clean_mode,
                    merge_method=clean_merge_method,
                    require_checks=require_checks_flag,
                    merged_sha=current_base_sha,
                    pr_url="",
                    pr_number=None,
                    checks_public=checks_public,
                    auto_resolved=auto_resolved,
                    resolved_files=sorted(resolved_set),
                )

            # status_code == 409 conflict on direct branch merge -> attempt auto-resolve!
            if auto_resolve_count < MAX_AUTO_RESOLVES_PER_ATTEMPT:
                res = _attempt_auto_resolve(
                    client=client,
                    existing_work_dir=existing_work_dir,
                    branch=clean_branch,
                    base=clean_base,
                    env=environ,
                )
                if res["outcome"] == "resolved":
                    auto_resolve_count += 1
                    auto_resolved = True
                    resolved_set.update(res["resolved_files"])
                    head_sha = res["new_sha"]
                    sha_watch_started = time.monotonic()
                    continue
                if res["outcome"] == "conflict":
                    files_list = res["conflicting_files"]
                    files_desc = ", ".join(files_list) if files_list else "(unmerged paths)"
                    return _build_pause_output(
                        repo_slug=repo_slug,
                        branch=clean_branch,
                        base=clean_base,
                        mode=clean_mode,
                        merge_method=clean_merge_method,
                        require_checks=require_checks_flag,
                        head_sha=head_sha,
                        pr_url="",
                        pr_number=None,
                        status="paused",
                        reason="merge conflict",
                        question=(
                            f"Merge conflict on {repo_slug} merging '{clean_branch}' "
                            f"({head_sha[:12]}) into '{clean_base}' in files: {files_desc}. "
                            f"Resolve the conflict on '{clean_branch}', push to origin, and approve to retry."
                        ),
                        checks_public=checks_public,
                        auto_resolved=auto_resolved,
                        resolved_files=sorted(resolved_set),
                        conflicting_files=files_list,
                    )

            refusal_msg = str(merge_resp.get("message") or f"HTTP {status_code}")
            return _build_pause_output(
                repo_slug=repo_slug,
                branch=clean_branch,
                base=clean_base,
                mode=clean_mode,
                merge_method=clean_merge_method,
                require_checks=require_checks_flag,
                head_sha=head_sha,
                pr_url="",
                pr_number=None,
                status="blocked",
                reason="merge blocked",
                question=(
                    f"Direct merge failed on {repo_slug} ('{clean_branch}' -> '{clean_base}', "
                    f"{head_sha[:12]}): {refusal_msg}. Resolve on remote and approve to retry."
                ),
                checks_public=checks_public,
                auto_resolved=auto_resolved,
                resolved_files=sorted(resolved_set),
            )
    except GitHubApiError as exc:
        raise CodeLandError(str(exc)) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute an active code_land check-poll, auto-resolve, and merge attempt."
    )
    parser.add_argument("--work-dir", default="", help="Optional container-local git checkout path")
    parser.add_argument("--branch", default="", help="Head branch name to land")
    parser.add_argument("--base", default="main", help="Target base branch name")
    parser.add_argument("--mode", default="pr", help="Landing mode ('pr' or 'merge')")
    parser.add_argument("--title", default="", help="Optional PR title or merge commit message")
    parser.add_argument("--body", default="", help="Optional PR description body")
    parser.add_argument("--merge-method", default="squash", help="PR merge method")
    parser.add_argument("--require-checks", default="true", help="Enforce GitHub check runs")
    parser.add_argument("--repo", default="", help="Optional '<owner>/<repo>' or GitHub URL")
    parser.add_argument("--poll-interval-s", default="10", help="Check polling interval in seconds")
    parser.add_argument(
        "--checks-appear-timeout-s",
        default="30",
        help="Seconds to wait for checks to appear when require_checks=true",
    )
    parser.add_argument("--prior-pause", default="", help="JSON state from code_land_pause")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = land_code(
            work_dir=args.work_dir,
            branch=args.branch,
            base=args.base,
            mode=args.mode,
            title=args.title,
            body=args.body,
            merge_method=args.merge_method,
            require_checks=args.require_checks,
            repo=args.repo,
            poll_interval_s=args.poll_interval_s,
            checks_appear_timeout_s=args.checks_appear_timeout_s,
            prior_pause=args.prior_pause,
        )
    except (CodeLandError, code_checkout.CodeCheckoutError) as exc:
        code_checkout.fail(str(exc))
    code_checkout.emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
