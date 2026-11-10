#!/usr/bin/env python3
"""Stage, secret-scan, commit, and push changes from a container-local checkout to GitHub.

Contract:
- Validates `work_dir` (must be an existing container-local git repository; rejects
  `/home/shinelay*`, `/app/workspaces*`, and `WORKSPACE_DIR`), `message`, `branch`
  (defaults to current checked-out branch; refuses protected/base branches), `files`
  (optional JSON array or newline-separated repo-relative paths; rejects `..`, absolute
  paths, backslashes, `.git`, and symlink escapes), and `allow_empty` (`true`/`false`).
- Stages explicit `files` or `git add -A`, then inspects staged paths and added diff
  lines for `.env*`, `*.pem`, `*.key`, credentials files, private keys, and token
  patterns before committing. Resets the index and fails loud if any secret/credential
  material is staged.
- Clean index with `allow_empty=false`: emits
  `{"pushed": false, "branch": branch, "sha": head_sha, "clean": true}` with no empty
  commit and no push.
- Dirty index (or `allow_empty=true`): mints a fresh short-lived GitHub App installation
  token via `POST ${TEMPER_SERVER_URL}/api/github/token` (reusing `code_checkout`),
  refreshes the on-demand credential helper without persisting tokens in `.git/config`,
  commits with `message`, pushes `HEAD:refs/heads/<branch>` to `origin`, and emits
  `{"pushed": true, "branch": branch, "sha": sha, "clean": <bool>}`.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

import code_checkout  # noqa: E402

PROTECTED_BRANCHES = frozenset(
    {"main", "master", "staging", "production", "prod", "release"}
)

FORBIDDEN_STAGED_FILENAME_PATTERNS = (
    ".env",
    ".env*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "id_ecdsa",
    "id_ecdsa.*",
    "credentials",
    "credentials.json",
    "*credentials*.json",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
)

DIFF_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private key block",
        re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    ),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{16,}\b")),
    ("GitHub PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}\b")),
    ("Temper GitHub run key", re.compile(r"\btghk_[A-Za-z0-9_-]{8,}\b")),
    ("Temper run token", re.compile(r"\btrun_[A-Za-z0-9_-]{8,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b")),
    ("OpenAI/API secret key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b")),
    ("embedded x-access-token credential", re.compile(r"x-access-token:[^\s\"'@]+")),
)


class CodeSaveError(Exception):
    """Raised on any validation, secret-scan, auth, or git failure in code_save."""


def parse_strict_bool(
    value: str | bool | None,
    *,
    field: str,
    default: bool = False,
) -> bool:
    """Strictly parse boolean input ('true'/'1' -> True, 'false'/'0' -> False)."""
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"true", "1"}:
            return True
        if norm in {"false", "0"}:
            return False
    raise CodeSaveError(
        f"invalid {field} value {value!r}: expected 'true' or 'false'"
    )


def validate_work_dir(work_dir: str, env: dict[str, str] | None = None) -> Path:
    """Validate that work_dir is a container-local git checkout outside forbidden roots."""
    environ = env if env is not None else os.environ
    if not isinstance(work_dir, str) or not work_dir.strip():
        raise CodeSaveError("invalid work_dir '': work_dir path is required")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in work_dir):
        raise CodeSaveError(
            f"invalid work_dir {work_dir!r}: must not contain control characters"
        )

    raw_path = Path(work_dir)
    if not raw_path.is_absolute():
        raise CodeSaveError(
            f"invalid work_dir {work_dir!r}: work_dir must be an absolute path"
        )
    if ".." in raw_path.parts:
        raise CodeSaveError(
            f"invalid work_dir {work_dir!r}: path traversal '..' is forbidden"
        )

    resolved = raw_path.resolve(strict=False)
    if resolved in {Path("/"), Path("/tmp")}:
        raise CodeSaveError(
            f"invalid work_dir {work_dir!r}: work_dir must be a dedicated git repository directory"
        )

    forbidden_roots: list[tuple[str, Path]] = [
        ("/home/shinelay", code_checkout.FORBIDDEN_HOST_PREFIX),
        ("/app/workspaces", code_checkout.FORBIDDEN_CONTAINER_WORKSPACES),
    ]
    workspace_dir = environ.get("WORKSPACE_DIR", "").strip()
    if workspace_dir:
        ws_path = Path(workspace_dir)
        forbidden_roots.append(("WORKSPACE_DIR", ws_path))
        forbidden_roots.append(("WORKSPACE_DIR", ws_path.resolve(strict=False)))

    for label, forbidden in forbidden_roots:
        if code_checkout._is_within(raw_path, forbidden) or code_checkout._is_within(
            resolved, forbidden
        ):
            raise CodeSaveError(
                f"invalid work_dir {work_dir!r}: work_dir must not be inside {label} ({forbidden})"
            )

    if not resolved.is_dir() or not (resolved / ".git").exists():
        raise CodeSaveError(
            f"invalid work_dir {work_dir!r}: directory does not exist or is not a git repository"
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
        raise CodeSaveError(
            f"invalid work_dir {work_dir!r}: not a valid git working tree"
        )

    return resolved


def validate_commit_message(message: str) -> str:
    """Validate commit message is non-empty and contains no secret material or NUL bytes."""
    if not isinstance(message, str) or not message.strip():
        raise CodeSaveError("invalid message '': commit message is required")
    if "\x00" in message:
        raise CodeSaveError("invalid message: commit message must not contain NUL bytes")
    for kind, pattern in DIFF_SECRET_PATTERNS:
        if pattern.search(message):
            raise CodeSaveError(
                f"commit message rejected: detected {kind} in commit message"
            )
    return message.strip()


def parse_and_validate_files(
    files: str | list[str] | None,
    *,
    repo_dir: Path,
) -> list[str]:
    """Parse optional JSON array or newline-separated repo-relative file paths."""
    if files is None:
        return []
    raw_items: list[Any]
    if isinstance(files, list):
        raw_items = files
        if not raw_items:
            return []
    elif isinstance(files, str):
        stripped = files.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise CodeSaveError(
                    f"invalid files JSON list: {exc.msg}"
                ) from exc
            if not isinstance(parsed, list):
                raise CodeSaveError(
                    "invalid files value: JSON input must be an array of repo-relative paths"
                )
            raw_items = parsed
        else:
            raw_items = [
                line.strip()
                for line in files.splitlines()
                if line.strip()
            ]
    else:
        raise CodeSaveError(
            f"invalid files value {type(files).__name__}: expected string or list of paths"
        )

    validated: list[str] = []
    seen: set[str] = set()
    repo_resolved = repo_dir.resolve()

    for entry in raw_items:
        if not isinstance(entry, str) or not entry.strip():
            raise CodeSaveError(
                f"invalid file path {entry!r} in files: expected non-empty repo-relative string"
            )
        rel_str = entry.strip()
        if "\x00" in rel_str or "\\" in rel_str or any(ord(c) < 32 or ord(c) == 127 for c in rel_str):
            raise CodeSaveError(
                f"invalid file path {rel_str!r}: control characters and backslashes are forbidden"
            )
        if rel_str.startswith("/"):
            raise CodeSaveError(
                f"invalid file path {rel_str!r}: absolute paths are forbidden"
            )
        rel_path = Path(rel_str)
        parts = rel_path.parts
        if not parts or "." in parts or ".." in parts:
            raise CodeSaveError(
                f"invalid file path {rel_str!r}: '.' and '..' path segments are forbidden"
            )
        if ".git" in parts:
            raise CodeSaveError(
                f"invalid file path {rel_str!r}: '.git' paths are forbidden"
            )

        candidate = repo_dir / rel_path
        candidate_resolved = candidate.resolve(strict=False)
        if candidate_resolved == repo_resolved or not code_checkout._is_within(
            candidate_resolved, repo_resolved
        ):
            raise CodeSaveError(
                f"invalid file path {rel_str!r}: symlink or path escapes work_dir"
            )

        norm = rel_path.as_posix()
        if norm not in seen:
            seen.add(norm)
            validated.append(norm)

    return validated


def _run_local_git(
    repo_dir: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    extra_secrets: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    git_env = dict(env if env is not None else os.environ)
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_env,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = code_checkout._format_git_failure_detail(
            proc.stderr or proc.stdout or "",
            returncode=proc.returncode,
            extra_secrets=extra_secrets,
        )
        raise CodeSaveError(f"git {' '.join(args[:3])} failed: {detail}")
    return proc


def _resolve_target_branch(repo_dir: Path, branch_input: str) -> tuple[str, str]:
    """Return (target_branch, current_head_branch_or_HEAD) and refuse protected/base branches."""
    head_ref = _run_local_git(
        repo_dir, ["rev-parse", "--abbrev-ref", "HEAD"]
    ).stdout.strip()

    if branch_input and branch_input.strip():
        try:
            target_branch = code_checkout.validate_branch_name(
                branch_input.strip(), field="branch"
            )
        except code_checkout.CodeCheckoutError as exc:
            raise CodeSaveError(str(exc)) from exc
    else:
        if not head_ref or head_ref == "HEAD":
            raise CodeSaveError(
                "work_dir HEAD is detached and no explicit branch was provided"
            )
        try:
            target_branch = code_checkout.validate_branch_name(
                head_ref, field="branch"
            )
        except code_checkout.CodeCheckoutError as exc:
            raise CodeSaveError(str(exc)) from exc

    if target_branch.lower() in PROTECTED_BRANCHES:
        raise CodeSaveError(
            f"refusing to save/push directly to protected branch '{target_branch}'"
        )

    sym_proc = _run_local_git(
        repo_dir,
        ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
        check=False,
    )
    if sym_proc.returncode == 0:
        origin_head = sym_proc.stdout.strip()
        prefix = "refs/remotes/origin/"
        if origin_head.startswith(prefix):
            origin_default = origin_head[len(prefix) :]
            if target_branch == origin_default:
                raise CodeSaveError(
                    f"refusing to save/push directly to origin default branch '{target_branch}'"
                )

    return target_branch, head_ref


def _is_forbidden_secret_path(rel_path: str) -> str | None:
    """Return reason string if rel_path matches a forbidden secret/credential filename pattern."""
    p = Path(rel_path)
    name_lower = p.name.lower()
    for pat in FORBIDDEN_STAGED_FILENAME_PATTERNS:
        if fnmatch.fnmatch(name_lower, pat.lower()):
            return f"forbidden credential/secret file pattern '{pat}'"
    for part in p.parts:
        part_lower = part.lower()
        if part_lower in {".ssh", ".aws", ".gnupg"}:
            return f"forbidden credential directory '{part}'"
    return None


def _scan_staged_for_secrets(repo_dir: Path) -> None:
    """Fail loud (after unstaging) if staged paths or added diff lines contain secrets."""
    names_proc = _run_local_git(repo_dir, ["diff", "--cached", "--name-only", "-z"])
    staged_paths = [p for p in names_proc.stdout.split("\x00") if p]
    for staged_path in staged_paths:
        reason = _is_forbidden_secret_path(staged_path)
        if reason is not None:
            _run_local_git(repo_dir, ["reset", "--quiet"], check=False)
            raise CodeSaveError(
                f"refusing to commit secret/credential file '{staged_path}' ({reason})"
            )

    diff_proc = _run_local_git(
        repo_dir, ["diff", "--cached", "--unified=0", "--no-color"]
    )
    current_file = "<staged>"
    for line in diff_proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/") :]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added_text = line[1:]
        for kind, pattern in DIFF_SECRET_PATTERNS:
            if pattern.search(added_text):
                _run_local_git(repo_dir, ["reset", "--quiet"], check=False)
                raise CodeSaveError(
                    f"refusing to commit secret pattern ({kind}) in staged diff of '{current_file}'"
                )


def _stage_changes(repo_dir: Path, file_list: list[str]) -> None:
    """Stage requested files (verifying each exists in worktree or HEAD) or all changes."""
    if not file_list:
        _run_local_git(repo_dir, ["add", "-A"])
        return

    for rel_path in file_list:
        disk_path = repo_dir / rel_path
        if disk_path.exists() or disk_path.is_symlink():
            continue
        tracked = _run_local_git(
            repo_dir,
            ["cat-file", "-e", f"HEAD:{rel_path}"],
            check=False,
        )
        if tracked.returncode != 0:
            raise CodeSaveError(
                f"file '{rel_path}' in files does not exist in work_dir or HEAD"
            )

    _run_local_git(repo_dir, ["add", "-A", "--", *file_list])


def _ensure_git_identity_and_helper(
    repo_dir: Path,
    *,
    repo_slug: str,
    https_remote: str,
    git_env: dict[str, str],
    token: str,
) -> None:
    """Ensure git author config, clean https origin URL, and on-demand credential helper."""
    code_checkout.run_git(
        ["remote", "set-url", "origin", https_remote],
        cwd=repo_dir,
        git_env=git_env,
        token=token,
    )
    name_proc = code_checkout.run_git(
        ["config", "--get", "user.name"],
        cwd=repo_dir,
        git_env=git_env,
        token=token,
        check=False,
    )
    if name_proc.returncode != 0 or not name_proc.stdout.strip():
        code_checkout.run_git(
            ["config", "user.name", "temper-bot"],
            cwd=repo_dir,
            git_env=git_env,
            token=token,
        )
    email_proc = code_checkout.run_git(
        ["config", "--get", "user.email"],
        cwd=repo_dir,
        git_env=git_env,
        token=token,
        check=False,
    )
    if email_proc.returncode != 0 or not email_proc.stdout.strip():
        code_checkout.run_git(
            ["config", "user.email", "bot@temper.ai"],
            cwd=repo_dir,
            git_env=git_env,
            token=token,
        )

    helper_cmd = code_checkout.build_credential_helper_command(repo_slug)
    code_checkout.run_git(
        ["config", "--replace-all", "credential.helper", ""],
        cwd=repo_dir,
        git_env=git_env,
        token=token,
    )
    code_checkout.run_git(
        ["config", "--replace-all", "credential.https://github.com.helper", ""],
        cwd=repo_dir,
        git_env=git_env,
        token=token,
    )
    code_checkout.run_git(
        ["config", "--add", "credential.https://github.com.helper", helper_cmd],
        cwd=repo_dir,
        git_env=git_env,
        token=token,
    )
    code_checkout.run_git(
        ["config", "credential.https://github.com.useHttpPath", "true"],
        cwd=repo_dir,
        git_env=git_env,
        token=token,
    )
    code_checkout._ensure_no_persisted_credentials(repo_dir, token)


def save_code(
    *,
    work_dir: str,
    message: str,
    branch: str = "",
    files: str | list[str] | None = "",
    allow_empty: str | bool | None = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Stage, secret-check, commit, and push changes from `work_dir` to `origin/<branch>`."""
    environ = env if env is not None else os.environ

    repo_dir = validate_work_dir(work_dir, env=environ)
    clean_message = validate_commit_message(message)
    allow_empty_flag = parse_strict_bool(
        allow_empty, field="allow_empty", default=False
    )
    target_branch, head_branch = _resolve_target_branch(repo_dir, branch)
    file_list = parse_and_validate_files(files, repo_dir=repo_dir)

    origin_proc = _run_local_git(
        repo_dir, ["remote", "get-url", "origin"], check=False
    )
    if origin_proc.returncode != 0 or not origin_proc.stdout.strip():
        raise CodeSaveError("work_dir has no 'origin' remote configured")
    raw_origin = origin_proc.stdout.strip()
    try:
        _, _, repo_slug, https_remote = code_checkout.parse_and_validate_repo_url(
            raw_origin
        )
    except code_checkout.CodeCheckoutError as exc:
        raise CodeSaveError(f"invalid origin remote in work_dir: {exc}") from exc

    if head_branch != target_branch:
        _run_local_git(repo_dir, ["checkout", "--quiet", "-B", target_branch])

    _stage_changes(repo_dir, file_list)
    _scan_staged_for_secrets(repo_dir)

    diff_check = _run_local_git(
        repo_dir, ["diff", "--cached", "--quiet"], check=False
    )
    if diff_check.returncode not in (0, 1):
        detail = code_checkout.scrub_secrets(
            diff_check.stderr or diff_check.stdout or ""
        ).strip()
        raise CodeSaveError(f"git diff --cached failed: {detail}")
    is_clean = diff_check.returncode == 0

    head_sha = _run_local_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip()
    if not code_checkout.SHA40_RE.fullmatch(head_sha):
        raise CodeSaveError(f"failed to resolve 40-char HEAD SHA: got {head_sha!r}")

    if is_clean and not allow_empty_flag:
        return {
            "pushed": False,
            "branch": target_branch,
            "sha": head_sha,
            "clean": True,
        }

    try:
        token = code_checkout.fetch_github_token(
            repo_slug, repo_url=https_remote, env=environ
        )
    except code_checkout.CodeCheckoutError as exc:
        raise CodeSaveError(str(exc)) from exc

    git_env = code_checkout.build_git_env(token, base_env=environ)
    try:
        _ensure_git_identity_and_helper(
            repo_dir,
            repo_slug=repo_slug,
            https_remote=https_remote,
            git_env=git_env,
            token=token,
        )

        commit_args = ["commit", "--quiet"]
        if is_clean and allow_empty_flag:
            commit_args.append("--allow-empty")
        commit_args.extend(["-m", clean_message])
        code_checkout.run_git(
            commit_args,
            cwd=repo_dir,
            git_env=git_env,
            token=token,
        )

        new_sha = code_checkout.run_git(
            ["rev-parse", "HEAD"],
            cwd=repo_dir,
            git_env=git_env,
            token=token,
        ).stdout.strip()
        if not code_checkout.SHA40_RE.fullmatch(new_sha):
            raise CodeSaveError(
                f"failed to resolve 40-char commit SHA after commit: got {new_sha!r}"
            )

        code_checkout.run_git(
            ["push", "--quiet", "origin", f"HEAD:refs/heads/{target_branch}"],
            cwd=repo_dir,
            git_env=git_env,
            token=token,
        )
        code_checkout._ensure_no_persisted_credentials(repo_dir, token)
    except code_checkout.CodeCheckoutError as exc:
        raise CodeSaveError(str(exc)) from exc

    return {
        "pushed": True,
        "branch": target_branch,
        "sha": new_sha,
        "clean": is_clean,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stage, secret-check, commit, and push changes from a container-local checkout."
    )
    parser.add_argument("--work-dir", default="", help="Container-local git checkout path")
    parser.add_argument("--message", default="", help="Git commit message")
    parser.add_argument("--branch", default="", help="Target branch name (default: current HEAD branch)")
    parser.add_argument(
        "--files",
        default="",
        help="Optional JSON array or newline-separated repo-relative paths to stage",
    )
    parser.add_argument(
        "--allow-empty",
        default="false",
        help="Whether to create and push an empty commit when clean ('true'|'false')",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = save_code(
            work_dir=args.work_dir,
            message=args.message,
            branch=args.branch,
            files=args.files,
            allow_empty=args.allow_empty,
        )
    except (CodeSaveError, code_checkout.CodeCheckoutError) as exc:
        code_checkout.fail(str(exc))
    code_checkout.emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
