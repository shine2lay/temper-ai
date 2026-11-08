#!/usr/bin/env python3
"""Shared workspace startup and cleanup lifecycle for Temper department workflows.

Reuses Systems' task_claim + task_worktree + task_cleanup contract so any workflow can
provision an isolated full-codebase git worktree at `<workspaces_root>/<repo>/worktrees/<slug>`
with `<worktree>/.temper` and `<worktree>/.temper/<department>` ready for per-node
`workspace_path` scoping, and clean it up safely afterwards.

Subcommands:
  startup  Claim `<workspaces_root>/<repo>/claims/<task_slug>.json`, clone or fetch
           `<workspaces_root>/<repo>/main`, create/reuse `<workspaces_root>/<repo>/worktrees/<task_slug>`,
           ensure `.epd/` + any `exclude_dirs` in `<main>/.git/info/exclude`, create
           `<worktree>/.temper` (and `<worktree>/.temper/<department>` when `department` is set),
           mark the claim `worktree_ready`, and emit JSON on stdout.
  cleanup  Refuse before removing anything if uncommitted changes or unpushed commits exist
           (unless `force=true`), remove the worktree, prune git worktrees, delete the local
           branch, archive the claim to `claims/released/<task_slug>.<ts>.json`, and emit JSON
           on stdout.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

CONTAINER_WORKSPACES = Path("/app/workspaces")
DEFAULT_GITHUB_DEPLOY_DIR = Path("/app/github-deploy")
HOST_GITHUB_DEPLOY_DIR = Path("/home/shinelay/temper-ai/local/github-deploy")

CANONICAL_PRODUCT_OWNER = "shine2lay"
CANONICAL_PRODUCT_REPOS: dict[str, str] = {
    "rollcall": "git@github.com:shine2lay/rollcall.git",
    "temper-ai": "git@github.com:shine2lay/temper-ai.git",
    "inkflow": "git@github.com:shine2lay/inkflow.git",
    "roamee": "git@github.com:shine2lay/roamee.git",
    "standee": "git@github.com:shine2lay/standee.git",
    "agent-tools": "git@github.com:shine2lay/agent-tools.git",
    "pi-web-ui": "git@github.com:shine2lay/pi-web-ui.git",
}

PRODUCT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
DEPARTMENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
BASE_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")

HTTP_OR_SSH_REPO_RE = re.compile(
    r"^(?:https?|ssh)://[^/\s]+/([^/\s]+)/([^/\s]+?)(?:\.git)?/*$"
)
GIT_SCP_REPO_RE = re.compile(
    r"^git@[^:\s]+:([^/\s]+)/([^/\s]+?)(?:\.git)?/*$"
)
SSH_GITHUB_URL_RE = re.compile(
    r"^(?:git@github\.com:|ssh://git@github\.com/)([^/\s]+/[^/\s]+?)(?:\.git)?/*$"
)


class WorkspaceLifecycleError(Exception):
    """Raised when input validation or a workspace lifecycle step fails."""

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def fail(message: str, **extra: Any) -> None:
    payload: dict[str, Any] = {"status": "failed", "error": message}
    payload.update(extra)
    emit(payload)
    raise SystemExit(1)


def _clean_opt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        return "" if stripped == "None" else stripped
    return str(value).strip()


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    s = _clean_opt(value).lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no", ""):
        return False
    raise WorkspaceLifecycleError(
        f"invalid force value {value!r}: expected boolean true or false"
    )


def validate_department(department: Any) -> str:
    dept = _clean_opt(department)
    if not dept:
        return ""
    if not DEPARTMENT_RE.fullmatch(dept):
        raise WorkspaceLifecycleError(
            f"invalid department {department!r}: must match {DEPARTMENT_RE.pattern}"
        )
    return dept


def validate_base_branch(base_branch: Any) -> str:
    branch = _clean_opt(base_branch)
    if not branch:
        return ""
    if (
        branch.startswith("-")
        or branch.startswith("/")
        or branch.endswith("/")
        or branch.endswith(".lock")
        or ".." in branch
        or "@{" in branch
        or "//" in branch
        or not BASE_BRANCH_RE.fullmatch(branch)
    ):
        raise WorkspaceLifecycleError(
            f"invalid base_branch {base_branch!r}: must be a safe branch name"
        )
    return branch


def parse_exclude_dirs(exclude_dirs: Any) -> list[str]:
    if exclude_dirs is None or exclude_dirs == "" or exclude_dirs == []:
        return []
    if isinstance(exclude_dirs, (list, tuple)):
        raw_items = list(exclude_dirs)
    elif isinstance(exclude_dirs, str):
        s = exclude_dirs.strip()
        if not s or s == "None":
            return []
        if s.startswith("["):
            parsed: Any
            try:
                parsed = json.loads(s)
            except Exception:
                try:
                    parsed = ast.literal_eval(s)
                except Exception as exc:
                    raise WorkspaceLifecycleError(
                        f"invalid exclude_dirs {exclude_dirs!r}: {exc}"
                    ) from exc
            if not isinstance(parsed, (list, tuple)):
                raise WorkspaceLifecycleError(
                    f"invalid exclude_dirs {exclude_dirs!r}: expected list of relative paths"
                )
            raw_items = list(parsed)
        else:
            raw_items = [part.strip() for part in s.split(",") if part.strip()]
    else:
        raise WorkspaceLifecycleError(
            f"invalid exclude_dirs {exclude_dirs!r}: expected list or comma-separated string"
        )

    validated: list[str] = []
    for item in raw_items:
        if not isinstance(item, str):
            raise WorkspaceLifecycleError(
                f"invalid exclude_dirs entry {item!r}: must be a string"
            )
        entry = item.strip()
        if not entry:
            continue
        if "\x00" in entry or "\n" in entry or "\r" in entry:
            raise WorkspaceLifecycleError(
                f"invalid exclude_dirs entry {item!r}: control characters are forbidden"
            )
        if entry.startswith("/") or entry.startswith("~"):
            raise WorkspaceLifecycleError(
                f"invalid exclude_dirs entry {item!r}: must be a relative path"
            )
        while entry.startswith("./"):
            entry = entry[2:]
        stripped = entry.rstrip("/")
        parts = Path(stripped).parts if stripped else ()
        if not parts or ".." in parts or ".." in entry:
            raise WorkspaceLifecycleError(
                f"invalid exclude_dirs entry {item!r}: relative path without '..' required"
            )
        if entry not in validated:
            validated.append(entry)
    return validated


def resolve_workspaces_root(workspaces_root: Any = "") -> Path:
    raw = _clean_opt(workspaces_root)
    if raw:
        if "\x00" in raw or ".." in Path(raw).parts:
            raise WorkspaceLifecycleError(
                f"invalid workspaces_root {workspaces_root!r}: '..' is forbidden"
            )
        return Path(raw)
    if CONTAINER_WORKSPACES.is_dir():
        return CONTAINER_WORKSPACES / "repos"
    wd = os.environ.get("WORKSPACE_DIR", "").strip()
    if wd and Path(wd).is_dir():
        return Path(wd) / "repos"
    return Path.home() / "workspaces" / "repos"


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    url = _clean_opt(repo_url)
    if not url or "\x00" in url or "\n" in url or "\r" in url:
        raise WorkspaceLifecycleError(
            f"could not parse owner/repo from repo_url: {repo_url}"
        )

    for pattern in (HTTP_OR_SSH_REPO_RE, GIT_SCP_REPO_RE):
        m = pattern.fullmatch(url)
        if m:
            owner, repo = m.group(1), m.group(2)
            if (
                owner
                and repo
                and ".." not in (owner, repo)
                and REPO_NAME_RE.fullmatch(repo)
            ):
                return owner, repo
            break

    if url.startswith("file://") or url.startswith("/"):
        local_str = re.sub(r"^file://+", "/", url).rstrip("/")
        if local_str.endswith(".git"):
            local_str = local_str[:-4].rstrip("/")
        local_path = Path(local_str)
        parts = local_path.parts
        if len(parts) >= 2 and ".." not in parts:
            repo = local_path.name
            owner = local_path.parent.name if local_path.parent.name != "/" else "local"
            if owner and repo and REPO_NAME_RE.fullmatch(repo):
                return owner, repo

    raise WorkspaceLifecycleError(
        f"could not parse owner/repo from repo_url: {repo_url}"
    )


def resolve_repo_identity(
    *,
    repo_url: Any = "",
    product: Any = "",
    workspaces_root: Path,
) -> tuple[str, str, str]:
    """Return `(owner, repo, resolved_repo_url)` or raise WorkspaceLifecycleError."""
    clean_url = _clean_opt(repo_url)
    clean_product = _clean_opt(product)

    if not clean_url and not clean_product:
        raise WorkspaceLifecycleError(
            "either repo_url or product is required"
        )

    if clean_product:
        if not PRODUCT_RE.fullmatch(clean_product) or ".." in clean_product:
            raise WorkspaceLifecycleError(
                f"invalid product {product!r}: must match {PRODUCT_RE.pattern}"
            )

    if clean_url:
        owner, url_repo = parse_repo_url(clean_url)
        if clean_product and url_repo != clean_product:
            if not (clean_url.startswith("/") or clean_url.startswith("file://")):
                raise WorkspaceLifecycleError(
                    f"product {clean_product!r} does not match repo {url_repo!r} in repo_url {clean_url!r}"
                )
            return owner, clean_product, clean_url
        return owner, url_repo, clean_url

    # Only product was given: check <workspaces_root>/<product>/main origin first.
    main_dir = workspaces_root / clean_product / "main"
    if (main_dir / ".git").exists():
        proc = subprocess.run(
            ["git", "-C", str(main_dir), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            origin_url = proc.stdout.strip()
            try:
                owner, _ = parse_repo_url(origin_url)
            except WorkspaceLifecycleError:
                owner = CANONICAL_PRODUCT_OWNER
            return owner, clean_product, origin_url

    if clean_product in CANONICAL_PRODUCT_REPOS:
        canonical_url = CANONICAL_PRODUCT_REPOS[clean_product]
        owner, _ = parse_repo_url(canonical_url)
        return owner, clean_product, canonical_url

    raise WorkspaceLifecycleError(
        f"unknown product {clean_product!r}: no clone at {main_dir} and not in canonical {CANONICAL_PRODUCT_OWNER}/<product> map"
    )


def slugify_task_name(raw_name: str) -> str:
    slug = raw_name.lower()
    slug = re.sub(r"[^a-z0-9._/-]+", "-", slug)
    slug = re.sub(r"/+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = re.sub(r"\.\.+", ".", slug)
    slug = slug.strip("-.")
    slug = re.sub(r"-+", "-", slug)
    slug = re.sub(r"\.\.+", ".", slug)
    return slug


def resolve_task_slug(
    *,
    run_slug: Any = "",
    task_name: Any = "",
    task_slug: Any = "",
    department: str = "",
    run_id: Any = "",
) -> tuple[str, str]:
    """Return `(resolved_task_name, resolved_task_slug)` or raise WorkspaceLifecycleError."""
    clean_run_slug = _clean_opt(run_slug)
    clean_task_slug = _clean_opt(task_slug)
    clean_task_name = _clean_opt(task_name)
    clean_run_id = _clean_opt(run_id)

    for label, val in (
        ("run_slug", clean_run_slug),
        ("task_slug", clean_task_slug),
        ("task_name", clean_task_name),
        ("run_id", clean_run_id),
    ):
        if ".." in val:
            raise WorkspaceLifecycleError(
                f"invalid {label} {val!r}: '..' is forbidden"
            )

    raw_name = clean_run_slug or clean_task_slug or clean_task_name
    if not raw_name:
        if department and clean_run_id:
            raw_name = f"{department}-{clean_run_id}"
        elif clean_run_id:
            raw_name = (
                clean_run_id
                if clean_run_id.lower().startswith("run-")
                else f"run-{clean_run_id}"
            )
        else:
            raise WorkspaceLifecycleError(
                "missing task identifier: supply run_slug, task_name, task_slug, or run_id"
            )

    slug = slugify_task_name(raw_name)
    if not slug or ".." in slug or "/" in slug:
        raise WorkspaceLifecycleError(
            f"task_name produced an empty slug: {raw_name}"
        )
    return raw_name, slug


def _atomic_write_json(path: Path, data: dict[str, Any], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        if overwrite:
            os.replace(tmp_path, path)
        else:
            try:
                os.link(tmp_path, path)
            except FileExistsError as exc:
                raise WorkspaceLifecycleError(
                    f"task '{ data.get('task_slug', path.stem) }' was claimed concurrently"
                ) from exc
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def claim_workspace(
    *,
    root: Path,
    task_name: str,
    task_slug: str,
    repo_url: str,
    owner: str,
    repo: str,
    run_id: str,
    department: str,
    force: bool,
) -> tuple[Path, dict[str, Any], bool]:
    """Create or re-enter `claims/<task_slug>.json`.

    Returns `(claim_path, claim_data, created_new_claim)`.
    """
    claims_dir = root / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claims_dir / f"{task_slug}.json"

    existing: dict[str, Any] | None = None
    if claim_path.exists():
        try:
            loaded = json.loads(claim_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, ValueError):
            existing = {}

        owner_run = str((existing or {}).get("run_id") or "")
        same_run = bool(run_id) and owner_run == run_id
        if not same_run and not force:
            raise WorkspaceLifecycleError(
                f"task '{task_slug}' already claimed (run {owner_run}) at {claim_path}; pass force=true to take it over"
            )

    claimed_at = (
        str(existing.get("claimed_at"))
        if existing and existing.get("claimed_at") and bool(run_id) and existing.get("run_id") == run_id
        else dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    resolved_dept = department or str((existing or {}).get("department") or "")

    claim_data: dict[str, Any] = {
        "status": "claimed",
        "task_name": task_name,
        "task_slug": task_slug,
        "repo_url": repo_url,
        "owner": owner,
        "repo": repo,
        "run_id": run_id,
        "claimed_at": claimed_at,
        "root": str(root),
    }
    if resolved_dept:
        claim_data["department"] = resolved_dept

    created_new = existing is None
    _atomic_write_json(claim_path, claim_data, overwrite=not created_new)
    return claim_path, claim_data, created_new


def _prepare_git_env(
    repo_url: str,
    main_dir: Path,
    github_deploy_dir: Path,
) -> tuple[dict[str, str], str | None]:
    """Configure GIT_TERMINAL_PROMPT=0 and optional SSH deploy key for GitHub SSH URLs."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"

    effective_url = repo_url
    if (main_dir / ".git").is_dir():
        proc = subprocess.run(
            ["git", "-C", str(main_dir), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            effective_url = proc.stdout.strip()

    m = SSH_GITHUB_URL_RE.match(effective_url)
    if not m:
        return env, None

    slug = m.group(1)
    key_dir = github_deploy_dir
    if (
        not key_dir.is_dir()
        and github_deploy_dir == DEFAULT_GITHUB_DEPLOY_DIR
        and HOST_GITHUB_DEPLOY_DIR.is_dir()
    ):
        key_dir = HOST_GITHUB_DEPLOY_DIR

    key_file = key_dir / "id_ed25519"
    if "/" in slug and ".." not in slug and slug.count("/") == 1:
        repo_key = key_dir / slug / "id_ed25519"
        if repo_key.is_file():
            key_file = repo_key

    if not key_file.is_file():
        raise WorkspaceLifecycleError(
            f"ssh repo_url but no deploy key at {github_deploy_dir} (local/github-deploy/setup.sh owner/repo)"
        )

    fd, temp_key = tempfile.mkstemp(prefix="workspace-gh-key-")
    os.close(fd)
    shutil.copyfile(key_file, temp_key)
    os.chmod(temp_key, 0o600)
    known_hosts = key_dir / "known_hosts"
    kh_opts = (
        f"-o UserKnownHostsFile={known_hosts} -o StrictHostKeyChecking=yes"
        if known_hosts.is_file()
        else "-o StrictHostKeyChecking=accept-new"
    )
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {temp_key} -o IdentitiesOnly=yes {kh_opts} -o BatchMode=yes"
    )
    return env, temp_key


def _git(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    run_env = env if env is not None else {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=run_env,
        timeout=timeout,
    )


def _is_registered_worktree(main_dir: Path, wt_dir: Path, env: dict[str, str] | None = None) -> bool:
    if not (main_dir / ".git").is_dir():
        return False
    proc = _git(["worktree", "list", "--porcelain"], cwd=main_dir, env=env, timeout=30)
    if proc.returncode != 0:
        return False
    candidates = {f"worktree {wt_dir}", f"worktree {wt_dir.resolve()}"}
    return any(line.strip() in candidates for line in proc.stdout.splitlines())


def ensure_exclude_dirs(main_dir: Path, exclude_dirs: list[str]) -> list[str]:
    info_dir = main_dir / ".git" / "info"
    info_dir.mkdir(parents=True, exist_ok=True)
    exclude_file = info_dir / "exclude"
    existing_lines: list[str] = []
    if exclude_file.is_file():
        existing_lines = exclude_file.read_text(encoding="utf-8").splitlines()

    entries = [".epd/"]
    for item in exclude_dirs:
        if item not in entries:
            entries.append(item)

    changed = False
    for entry in entries:
        if entry not in existing_lines:
            existing_lines.append(entry)
            changed = True

    if changed or not exclude_file.is_file():
        exclude_file.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")
    return entries


def startup_workspace(
    *,
    repo_url: Any = "",
    product: Any = "",
    run_slug: Any = "",
    task_name: Any = "",
    task_slug: Any = "",
    department: Any = "",
    base_branch: Any = "",
    exclude_dirs: Any = "",
    force: Any = False,
    run_id: Any = "",
    workspaces_root: Any = "",
    github_deploy_dir: Path = DEFAULT_GITHUB_DEPLOY_DIR,
) -> dict[str, Any]:
    clean_force = parse_bool(force)
    clean_dept = validate_department(department)
    clean_base = validate_base_branch(base_branch)
    clean_excludes = parse_exclude_dirs(exclude_dirs)
    clean_run_id = _clean_opt(run_id)
    ws_root = resolve_workspaces_root(workspaces_root)
    owner, repo, resolved_url = resolve_repo_identity(
        repo_url=repo_url,
        product=product,
        workspaces_root=ws_root,
    )
    resolved_task_name, resolved_slug = resolve_task_slug(
        run_slug=run_slug,
        task_name=task_name,
        task_slug=task_slug,
        department=clean_dept,
        run_id=clean_run_id,
    )

    root = ws_root / repo
    main_dir = root / "main"
    worktrees_dir = root / "worktrees"
    wt_dir = worktrees_dir / resolved_slug

    claim_path, claim_data, created_new_claim = claim_workspace(
        root=root,
        task_name=resolved_task_name,
        task_slug=resolved_slug,
        repo_url=resolved_url,
        owner=owner,
        repo=repo,
        run_id=clean_run_id,
        department=clean_dept,
        force=clean_force,
    )

    temp_key: str | None = None
    worktree_ready = False
    try:
        worktrees_dir.mkdir(parents=True, exist_ok=True)
        git_env, temp_key = _prepare_git_env(resolved_url, main_dir, github_deploy_dir)

        if not (main_dir / ".git").is_dir():
            main_dir.parent.mkdir(parents=True, exist_ok=True)
            clone_proc = subprocess.run(
                ["git", "clone", "-q", resolved_url, str(main_dir)],
                capture_output=True,
                text=True,
                env=git_env,
                timeout=300,
            )
            if clone_proc.returncode != 0:
                raise WorkspaceLifecycleError(
                    f"git clone failed for {resolved_url}: {(clone_proc.stderr or clone_proc.stdout).strip()}"
                )
            _git(["config", "user.name", "temper-bot"], cwd=main_dir, env=git_env, timeout=15)
            _git(["config", "user.email", "bot@temper.ai"], cwd=main_dir, env=git_env, timeout=15)
            clone_state = "fresh"
        else:
            fetch_proc = _git(["fetch", "-q", "--prune", "origin"], cwd=main_dir, env=git_env, timeout=300)
            if fetch_proc.returncode != 0:
                raise WorkspaceLifecycleError(
                    f"git fetch failed in {main_dir}: {(fetch_proc.stderr or fetch_proc.stdout).strip()}"
                )
            clone_state = "reused"

        if not clean_base:
            sym = _git(
                ["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"],
                cwd=main_dir,
                env=git_env,
                timeout=15,
            )
            if sym.returncode == 0 and sym.stdout.strip():
                clean_base = sym.stdout.strip().removeprefix("origin/")
            else:
                head_branch = _git(
                    ["rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=main_dir,
                    env=git_env,
                    timeout=15,
                )
                clean_base = head_branch.stdout.strip()

        verify_base = _git(
            ["rev-parse", "-q", "--verify", f"refs/remotes/origin/{clean_base}"],
            cwd=main_dir,
            env=git_env,
            timeout=15,
        )
        if verify_base.returncode != 0:
            raise WorkspaceLifecycleError(
                f"base branch origin/{clean_base} does not exist"
            )

        if wt_dir.exists():
            if _is_registered_worktree(main_dir, wt_dir, env=git_env):
                worktree_state = "reused"
            else:
                raise WorkspaceLifecycleError(
                    f"{wt_dir} exists but is not a registered worktree of {main_dir}"
                )
        elif (
            _git(
                ["rev-parse", "-q", "--verify", f"refs/heads/{resolved_slug}"],
                cwd=main_dir,
                env=git_env,
                timeout=15,
            ).returncode
            == 0
        ):
            add_proc = _git(
                ["worktree", "add", "-q", str(wt_dir), resolved_slug],
                cwd=main_dir,
                env=git_env,
                timeout=120,
            )
            if add_proc.returncode != 0:
                raise WorkspaceLifecycleError(
                    f"git worktree add failed (existing branch {resolved_slug}): {(add_proc.stderr or add_proc.stdout).strip()}"
                )
            worktree_state = "existing_branch"
        elif (
            _git(
                ["rev-parse", "-q", "--verify", f"refs/remotes/origin/{resolved_slug}"],
                cwd=main_dir,
                env=git_env,
                timeout=15,
            ).returncode
            == 0
        ):
            add_proc = _git(
                [
                    "worktree",
                    "add",
                    "-q",
                    "--track",
                    "-b",
                    resolved_slug,
                    str(wt_dir),
                    f"origin/{resolved_slug}",
                ],
                cwd=main_dir,
                env=git_env,
                timeout=120,
            )
            if add_proc.returncode != 0:
                raise WorkspaceLifecycleError(
                    f"git worktree add failed (pushed branch origin/{resolved_slug}): {(add_proc.stderr or add_proc.stdout).strip()}"
                )
            worktree_state = "pushed_branch"
        else:
            add_proc = _git(
                [
                    "worktree",
                    "add",
                    "-q",
                    "-b",
                    resolved_slug,
                    str(wt_dir),
                    f"origin/{clean_base}",
                ],
                cwd=main_dir,
                env=git_env,
                timeout=120,
            )
            if add_proc.returncode != 0:
                raise WorkspaceLifecycleError(
                    f"git worktree add failed: {(add_proc.stderr or add_proc.stdout).strip()}"
                )
            worktree_state = "created"

        ensure_exclude_dirs(main_dir, clean_excludes)

        temper_dir = wt_dir / ".temper"
        temper_dir.mkdir(parents=True, exist_ok=True)
        dept_dir: Path | None = None
        eff_dept = clean_dept or str(claim_data.get("department") or "")
        if eff_dept:
            dept_dir = temper_dir / eff_dept
            dept_dir.mkdir(parents=True, exist_ok=True)

        branch_proc = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt_dir, env=git_env, timeout=15)
        head_proc = _git(["rev-parse", "HEAD"], cwd=wt_dir, env=git_env, timeout=15)
        base_head_proc = _git(
            ["rev-parse", f"origin/{clean_base}"], cwd=main_dir, env=git_env, timeout=15
        )
        if branch_proc.returncode != 0 or head_proc.returncode != 0 or base_head_proc.returncode != 0:
            raise WorkspaceLifecycleError(
                f"failed to read git refs for worktree {wt_dir}"
            )

        branch = branch_proc.stdout.strip()
        head = head_proc.stdout.strip()
        base_head = base_head_proc.stdout.strip()

        out: dict[str, Any] = {
            "status": "ready",
            "repo": repo,
            "repo_url": resolved_url,
            "task_slug": resolved_slug,
            "root": str(root),
            "worktree_path": str(wt_dir),
            "temper_path": str(temper_dir),
            "department_path": str(dept_dir) if dept_dir is not None else None,
            "department": eff_dept if eff_dept else None,
            "main_repo": str(main_dir),
            "branch": branch,
            "base_branch": clean_base,
            "head": head,
            "base_head": base_head,
            "claim_path": str(claim_path),
            "worktree": worktree_state,
            "clone": clone_state,
        }

        updated_claim = dict(claim_data)
        updated_claim.update(
            {
                "worktree_path": str(wt_dir),
                "temper_path": str(temper_dir),
                "department_path": str(dept_dir) if dept_dir is not None else None,
                "main_repo": str(main_dir),
                "branch": branch,
                "base_branch": clean_base,
                "head": head,
                "base_head": base_head,
                "worktree": worktree_state,
                "clone": clone_state,
                "status": "worktree_ready",
            }
        )
        if eff_dept:
            updated_claim["department"] = eff_dept
        _atomic_write_json(claim_path, updated_claim, overwrite=True)
        worktree_ready = True
        return out
    finally:
        if temp_key and os.path.exists(temp_key):
            try:
                os.unlink(temp_key)
            except OSError:
                pass
        if created_new_claim and not worktree_ready and not wt_dir.exists() and claim_path.exists():
            try:
                claim_path.unlink()
            except OSError:
                pass


def cleanup_workspace(
    *,
    repo_url: Any = "",
    product: Any = "",
    run_slug: Any = "",
    task_name: Any = "",
    task_slug: Any = "",
    department: Any = "",
    force: Any = False,
    run_id: Any = "",
    workspaces_root: Any = "",
) -> dict[str, Any]:
    clean_force = parse_bool(force)
    clean_dept = validate_department(department)
    clean_run_id = _clean_opt(run_id)
    ws_root = resolve_workspaces_root(workspaces_root)
    _, repo, _ = resolve_repo_identity(
        repo_url=repo_url,
        product=product,
        workspaces_root=ws_root,
    )
    _, resolved_slug = resolve_task_slug(
        run_slug=run_slug,
        task_name=task_name,
        task_slug=task_slug,
        department=clean_dept,
        run_id=clean_run_id,
    )

    root = ws_root / repo
    main_dir = root / "main"
    wt_dir = root / "worktrees" / resolved_slug
    claim_path = root / "claims" / f"{resolved_slug}.json"

    # --- Checks before removing anything ---
    worktree_state = "absent"
    registered = False
    if wt_dir.exists():
        if _is_registered_worktree(main_dir, wt_dir):
            registered = True
            status_proc = _git(
                ["status", "--porcelain", "--untracked-files=all"],
                cwd=wt_dir,
                timeout=60,
            )
            if status_proc.returncode != 0:
                if not clean_force:
                    raise WorkspaceLifecycleError(
                        f"git status failed in {wt_dir}: {(status_proc.stderr or status_proc.stdout).strip()}"
                    )
            else:
                dirty = len([line for line in status_proc.stdout.splitlines() if line.strip()])
                if dirty != 0 and not clean_force:
                    raise WorkspaceLifecycleError(
                        f"worktree {wt_dir} has {dirty} uncommitted change(s); commit/push them or pass force=true"
                    )
        elif not clean_force:
            raise WorkspaceLifecycleError(
                f"{wt_dir} exists but is not a registered worktree of {main_dir}; pass force=true to delete it"
            )

    branch_state = "absent"
    has_branch = False
    if (main_dir / ".git").is_dir() and (
        _git(
            ["rev-parse", "-q", "--verify", f"refs/heads/{resolved_slug}"],
            cwd=main_dir,
            timeout=15,
        ).returncode
        == 0
    ):
        has_branch = True
        sym = _git(
            ["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"],
            cwd=main_dir,
            timeout=15,
        )
        if sym.returncode == 0 and sym.stdout.strip():
            base = sym.stdout.strip().removeprefix("origin/")
        else:
            base = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=main_dir, timeout=15).stdout.strip()

        safe = False
        if (
            _git(
                ["rev-parse", "-q", "--verify", f"refs/remotes/origin/{resolved_slug}"],
                cwd=main_dir,
                timeout=15,
            ).returncode
            == 0
        ):
            ahead_origin = _git(
                ["rev-list", f"origin/{resolved_slug}..{resolved_slug}"],
                cwd=main_dir,
                timeout=30,
            )
            if ahead_origin.returncode == 0 and not ahead_origin.stdout.strip():
                safe = True

        if not safe and (
            _git(
                ["rev-parse", "-q", "--verify", f"refs/remotes/origin/{base}"],
                cwd=main_dir,
                timeout=15,
            ).returncode
            == 0
        ):
            ahead_base = _git(
                ["rev-list", f"origin/{base}..{resolved_slug}"],
                cwd=main_dir,
                timeout=30,
            )
            if ahead_base.returncode == 0 and not ahead_base.stdout.strip():
                safe = True

        if not safe and not clean_force:
            ahead_count_proc = _git(
                ["rev-list", "--count", f"origin/{base}..{resolved_slug}"],
                cwd=main_dir,
                timeout=30,
            )
            ahead_count = ahead_count_proc.stdout.strip() or "unpushed"
            raise WorkspaceLifecycleError(
                f"branch {resolved_slug} has {ahead_count} commit(s) not on origin/{resolved_slug} or origin/{base}; push them or pass force=true"
            )

    # --- 1. Remove worktree ---
    if wt_dir.exists():
        if registered:
            rm_proc = _git(
                ["worktree", "remove", "--force", str(wt_dir)],
                cwd=main_dir,
                timeout=120,
            )
            if rm_proc.returncode != 0:
                raise WorkspaceLifecycleError(
                    f"git worktree remove failed for {wt_dir}: {(rm_proc.stderr or rm_proc.stdout).strip()}"
                )
            worktree_state = "removed"
        else:
            shutil.rmtree(wt_dir)
            worktree_state = "removed_unregistered"

    if (main_dir / ".git").is_dir():
        _git(["worktree", "prune"], cwd=main_dir, timeout=30)

    # --- 2. Delete local branch ---
    if has_branch:
        del_proc = _git(["branch", "-D", "-q", resolved_slug], cwd=main_dir, timeout=30)
        if del_proc.returncode != 0:
            raise WorkspaceLifecycleError(
                f"could not delete branch {resolved_slug}: {(del_proc.stderr or del_proc.stdout).strip()}"
            )
        branch_state = "deleted"

    # --- 3. Archive claim ---
    released_claim_path = ""
    if claim_path.is_file():
        released_dir = root / "claims" / "released"
        released_dir.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now(dt.UTC)
        ts = now.strftime("%Y%m%dT%H%M%SZ")
        dst = released_dir / f"{resolved_slug}.{ts}.json"
        if dst.exists():
            dst = released_dir / f"{resolved_slug}.{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
        try:
            claim_data = json.loads(claim_path.read_text(encoding="utf-8"))
            if not isinstance(claim_data, dict):
                claim_data = {}
        except (OSError, ValueError):
            claim_data = {}
        claim_data.update(
            {
                "status": "released",
                "released_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "released_by_run": clean_run_id,
                "cleanup": {"worktree": worktree_state, "branch": branch_state},
            }
        )
        _atomic_write_json(dst, claim_data, overwrite=True)
        claim_path.unlink()
        released_claim_path = str(dst)
        claim_state = "released"
    else:
        claim_state = "absent"

    return {
        "status": "clean",
        "repo": repo,
        "task_slug": resolved_slug,
        "root": str(root),
        "worktree": worktree_state,
        "branch": branch_state,
        "claim": claim_state,
        "released_claim_path": released_claim_path,
    }


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        fail(f"invalid arguments: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="workspace_lifecycle.py",
        description="Provision and clean up isolated git worktrees for department workflows.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    start_p = sub.add_parser("startup", help="Claim and prepare an isolated worktree.")
    start_p.add_argument("--repo-url", default="", help="Git repository URL.")
    start_p.add_argument("--product", default="", help="Product name (e.g. rollcall, temper-ai).")
    start_p.add_argument("--run-slug", default="", help="Run slug for worktree/branch/claim.")
    start_p.add_argument("--task-name", default="", help="Task name (slugified into task_slug).")
    start_p.add_argument("--task-slug", default="", help="Explicit task_slug alias.")
    start_p.add_argument("--department", default="", help="Optional department id (e.g. design).")
    start_p.add_argument("--base-branch", default="", help="Optional base branch override.")
    start_p.add_argument(
        "--exclude-dirs",
        default="",
        help="Optional comma-separated or JSON list of relative dirs to add to .git/info/exclude.",
    )
    start_p.add_argument("--force", default="false", help="Take over an existing claim if true.")
    start_p.add_argument("--run-id", default="", help="Workflow run_id.")
    start_p.add_argument("--workspaces-root", default="", help="Optional workspaces repos root override.")
    start_p.add_argument(
        "--github-deploy-dir",
        default=str(DEFAULT_GITHUB_DEPLOY_DIR),
        help="Path to github-deploy SSH key directory.",
    )

    clean_p = sub.add_parser("cleanup", help="Safely remove worktree, branch, and release claim.")
    clean_p.add_argument("--repo-url", default="", help="Git repository URL.")
    clean_p.add_argument("--product", default="", help="Product name (e.g. rollcall, temper-ai).")
    clean_p.add_argument("--run-slug", default="", help="Run slug for worktree/branch/claim.")
    clean_p.add_argument("--task-name", default="", help="Task name (slugified into task_slug).")
    clean_p.add_argument("--task-slug", default="", help="Explicit task_slug alias.")
    clean_p.add_argument("--department", default="", help="Optional department id.")
    clean_p.add_argument("--force", default="false", help="Force removal even if dirty or unpushed.")
    clean_p.add_argument("--run-id", default="", help="Workflow run_id.")
    clean_p.add_argument("--workspaces-root", default="", help="Optional workspaces repos root override.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.subcommand:
        fail("missing subcommand: expected 'startup' or 'cleanup'")

    try:
        if args.subcommand == "startup":
            result = startup_workspace(
                repo_url=args.repo_url,
                product=args.product,
                run_slug=args.run_slug,
                task_name=args.task_name,
                task_slug=args.task_slug,
                department=args.department,
                base_branch=args.base_branch,
                exclude_dirs=args.exclude_dirs,
                force=args.force,
                run_id=args.run_id,
                workspaces_root=args.workspaces_root,
                github_deploy_dir=Path(args.github_deploy_dir),
            )
        elif args.subcommand == "cleanup":
            result = cleanup_workspace(
                repo_url=args.repo_url,
                product=args.product,
                run_slug=args.run_slug,
                task_name=args.task_name,
                task_slug=args.task_slug,
                department=args.department,
                force=args.force,
                run_id=args.run_id,
                workspaces_root=args.workspaces_root,
            )
        else:
            raise WorkspaceLifecycleError(f"unknown subcommand: {args.subcommand!r}")
    except WorkspaceLifecycleError as exc:
        fail(exc.message, **exc.extra)
    except Exception as exc:
        fail(f"unexpected error in workspace_lifecycle {args.subcommand}: {exc}")

    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
