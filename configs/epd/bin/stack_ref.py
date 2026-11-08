#!/usr/bin/env python3
"""Manage a ref-pinned non-live dev stack via standee (stack_up_ref, stack_seed, stack_down).

Subcommands:
  up    Ensure `<product>-dev-<slug>` is running at `<ref>` (default `origin/master`).
        Fetches `origin` first, resolves `<ref>^{commit}` to a 40-char SHA, and checks
        `standee status <env_name> --json`. When the environment is already running at
        that exact 40-char SHA with a non-empty URL, reuses it (`reused: true`, renewing
        TTL if `--ttl` was given). Otherwise runs `standee up <host_repo> --project <product>
        --as <slug> --tier dev --ref <commit> --gateway --wait` (`reused: false`).
  seed  Run `standee seed <env_name>` to reset dev seed state in place.
  down  Run `standee down <env_name> --volumes --images` and verify zero leftover docker
        volumes (`com.docker.compose.project=<env_name>` or `<env_name>_*`).

All subcommands validate their inputs up front and fail loud and fast with a single JSON
object `{"status": "failed", "error": "..."}` on stdout and exit code 1.
"""

from __future__ import annotations

import argparse
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
DEFAULT_HOST_WORKSPACES = Path("/home/shinelay/temper-ai/workspaces")
DEFAULT_HOST_HOME = Path("/home/shinelay")
DEFAULT_STANDEE_SSH_DIR = Path("/app/standee-ssh")
DEFAULT_STANDEE_SSH_TARGET = "shinelay@host.docker.internal"
DEFAULT_GITHUB_DEPLOY_DIR = Path("/app/github-deploy")

PRODUCT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^-]{0,199}$")
ENV_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}-dev-[a-z0-9][a-z0-9-]{0,39}$")
TTL_RE = re.compile(r"^(never|[1-9][0-9]*[smhdw])$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
UP_BANNER_RE = re.compile(r"^✓\s+([^\s]+)\s+is\s+up\b", re.MULTILINE)
SSH_GITHUB_RE = re.compile(
    r"^(?:git@github\.com:|ssh://git@github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$"
)


class StackRefError(Exception):
    """Raised on any validation or execution failure."""

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


def validate_product(product: str) -> str:
    val = (product or "").strip()
    if not val or not PRODUCT_RE.fullmatch(val):
        raise StackRefError(
            f"invalid product {product!r}: must match {PRODUCT_RE.pattern}"
        )
    if val == "temper":
        raise StackRefError("product 'temper' is forbidden (Rule 15: never spin up a second Temper)")
    return val


def validate_slug(slug: str) -> str:
    val = (slug or "").strip()
    if not val or not SLUG_RE.fullmatch(val):
        raise StackRefError(
            f"invalid slug {slug!r}: must match {SLUG_RE.pattern}"
        )
    return val


def validate_ref(ref: str) -> str:
    val = (ref or "").strip()
    if (
        not val
        or val.startswith("-")
        or ".." in val
        or "@{" in val
        or not REF_RE.fullmatch(val)
    ):
        raise StackRefError(
            f"invalid git ref {ref!r}: must be a safe ref name or commit SHA"
        )
    return val


def validate_ttl(ttl: str) -> str:
    val = (ttl or "").strip()
    if not val:
        return ""
    if not TTL_RE.fullmatch(val):
        raise StackRefError(
            f"invalid ttl {ttl!r}: expected duration like '12h', '3d', '2w', or 'never'"
        )
    return val


def resolve_env_name(env_name: str, product: str, slug: str) -> str:
    raw_env = (env_name or "").strip()
    if not raw_env:
        prod = validate_product(product)
        sl = validate_slug(slug)
        raw_env = f"{prod}-dev-{sl}"
    if raw_env == "temper-dev" or not ENV_NAME_RE.fullmatch(raw_env):
        raise StackRefError(
            f"invalid env_name {raw_env!r}: must be a non-live dev environment '<product>-dev-<slug>'"
        )
    return raw_env


def _has_git_marker(path: Path) -> bool:
    git_marker = path / ".git"
    return git_marker.is_dir() or git_marker.is_file()


def locate_product_repo(
    product: str,
    repo_dir: str = "",
    host_repo_dir: str = "",
    workspace_dir_env: str | None = None,
    container_workspaces: Path = CONTAINER_WORKSPACES,
    default_host_workspaces: Path = DEFAULT_HOST_WORKSPACES,
    default_host_home: Path = DEFAULT_HOST_HOME,
) -> tuple[Path, Path]:
    """Return `(local_repo, host_repo)` for `product`, or raise StackRefError."""
    wd_raw = (
        workspace_dir_env
        if workspace_dir_env is not None
        else os.environ.get("WORKSPACE_DIR", "")
    ).strip()
    wd_path = Path(wd_raw) if wd_raw and not wd_raw.startswith(".") else None

    if repo_dir:
        local_repo = Path(repo_dir)
        if not _has_git_marker(local_repo):
            raise StackRefError(f"git repository not found at {local_repo}")
        if host_repo_dir:
            return local_repo, Path(host_repo_dir)
        try:
            rel = local_repo.relative_to(container_workspaces)
        except ValueError:
            return local_repo, local_repo
        host_base = wd_path or default_host_workspaces
        return local_repo, host_base / rel

    # 1. Container workspaces mount (/app/workspaces/repos/<product>/main)
    container_candidate = container_workspaces / "repos" / product / "main"
    if _has_git_marker(container_candidate):
        host_base = wd_path or (
            default_host_workspaces if default_host_workspaces.is_dir() else None
        )
        if host_base is None:
            raise StackRefError(
                f"repo found at {container_candidate} but WORKSPACE_DIR is not set to a host path"
            )
        return container_candidate, host_base / "repos" / product / "main"

    # 2. $WORKSPACE_DIR/repos/<product>/main
    if wd_path is not None:
        wd_candidate = wd_path / "repos" / product / "main"
        if _has_git_marker(wd_candidate):
            return wd_candidate, Path(host_repo_dir) if host_repo_dir else wd_candidate

    # 3. Default host workspaces (/home/shinelay/temper-ai/workspaces/repos/<product>/main)
    host_ws_candidate = default_host_workspaces / "repos" / product / "main"
    if _has_git_marker(host_ws_candidate):
        return (
            host_ws_candidate,
            Path(host_repo_dir) if host_repo_dir else host_ws_candidate,
        )

    # 4. Host home checkout (/home/shinelay/<product>)
    home_candidate = default_host_home / product
    if _has_git_marker(home_candidate):
        return home_candidate, Path(host_repo_dir) if host_repo_dir else home_candidate

    raise StackRefError(
        f"repository for product {product!r} not found under workspaces/repos/{product}/main or {default_host_home / product}"
    )


def _github_ssh_key_for_repo(local_repo: Path, github_deploy_dir: Path) -> Path | None:
    if not github_deploy_dir.is_dir():
        return None
    proc = subprocess.run(
        ["git", "-C", str(local_repo), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return None
    remote_url = proc.stdout.strip()
    m = SSH_GITHUB_RE.match(remote_url)
    if not m:
        return None
    slug = m.group(1)
    repo_key = github_deploy_dir / slug / "id_ed25519"
    if repo_key.is_file():
        return repo_key
    shared_key = github_deploy_dir / "id_ed25519"
    if shared_key.is_file():
        return shared_key
    return None


def fetch_and_resolve_ref(
    local_repo: Path,
    ref: str,
    github_deploy_dir: Path = DEFAULT_GITHUB_DEPLOY_DIR,
    fetch_timeout: int = 60,
) -> str:
    """Fetch `origin` in `local_repo` and resolve `ref^{commit}` to a 40-char SHA."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"

    temp_key: str | None = None
    try:
        key_source = _github_ssh_key_for_repo(local_repo, github_deploy_dir)
        if key_source is not None:
            fd, temp_key = tempfile.mkstemp(prefix="stack-ref-gh-key-")
            os.close(fd)
            shutil.copyfile(key_source, temp_key)
            os.chmod(temp_key, 0o600)
            known_hosts = github_deploy_dir / "known_hosts"
            kh_opts = (
                f"-o UserKnownHostsFile={known_hosts} -o StrictHostKeyChecking=yes"
                if known_hosts.is_file()
                else "-o StrictHostKeyChecking=accept-new"
            )
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {temp_key} -o IdentitiesOnly=yes {kh_opts} -o BatchMode=yes -o ConnectTimeout=20"
            )

        try:
            fetch_proc = subprocess.run(
                ["git", "-C", str(local_repo), "fetch", "--quiet", "--prune", "origin"],
                capture_output=True,
                text=True,
                env=env,
                timeout=fetch_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise StackRefError(
                f"git fetch origin timed out after {fetch_timeout}s in {local_repo}"
            ) from exc

        if fetch_proc.returncode != 0:
            detail = (fetch_proc.stderr or fetch_proc.stdout).strip()
            raise StackRefError(
                f"git fetch origin failed in {local_repo} (exit {fetch_proc.returncode}): {detail}"
            )
    finally:
        if temp_key and os.path.exists(temp_key):
            try:
                os.unlink(temp_key)
            except OSError:
                pass

    rev_proc = subprocess.run(
        ["git", "-C", str(local_repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    if rev_proc.returncode != 0:
        detail = (rev_proc.stderr or rev_proc.stdout).strip()
        raise StackRefError(
            f"cannot resolve ref {ref!r} in {local_repo}: {detail}"
        )
    commit = rev_proc.stdout.strip()
    if not SHA40_RE.fullmatch(commit):
        raise StackRefError(
            f"rev-parse returned non-40-hex commit {commit!r} for ref {ref!r}"
        )
    if ref in ("origin/master", "origin/main"):
        status_proc = subprocess.run(
            ["git", "-C", str(local_repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        if status_proc.returncode == 0 and not status_proc.stdout.strip():
            subprocess.run(
                ["git", "-C", str(local_repo), "merge", "--ff-only", "--quiet", commit],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
    return commit


def run_standee(
    args: list[str],
    *,
    standee_bin: str = "",
    ssh_dir: Path = DEFAULT_STANDEE_SSH_DIR,
    timeout: int = 540,
) -> subprocess.CompletedProcess[str]:
    """Invoke `standee <args>` via `standee_bin`, `/app/standee-ssh`, or host PATH."""
    resolved_bin = (standee_bin or os.environ.get("STANDEE_BIN", "")).strip()
    if resolved_bin:
        return subprocess.run(
            [resolved_bin, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    key_file = ssh_dir / "id_ed25519"
    target_file = ssh_dir / "target"
    if key_file.is_file():
        if target_file.is_file():
            target = target_file.read_text().strip()
            if not target:
                raise StackRefError(f"empty standee ssh target in {target_file}")
        else:
            target = DEFAULT_STANDEE_SSH_TARGET
        fd, temp_key = tempfile.mkstemp(prefix="stack-ref-standee-key-")
        os.close(fd)
        try:
            shutil.copyfile(key_file, temp_key)
            os.chmod(temp_key, 0o600)
            known_hosts = ssh_dir / "known_hosts"
            kh_opts = (
                ["-o", f"UserKnownHostsFile={known_hosts}", "-o", "StrictHostKeyChecking=yes"]
                if known_hosts.is_file()
                else ["-o", "StrictHostKeyChecking=accept-new"]
            )
            cmd = [
                "ssh",
                "-i",
                temp_key,
                "-o",
                "IdentitiesOnly=yes",
                *kh_opts,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=15",
                target,
                "standee",
                *args,
            ]
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        finally:
            if os.path.exists(temp_key):
                try:
                    os.unlink(temp_key)
                except OSError:
                    pass

    host_bin = shutil.which("standee") or str(Path.home() / ".local" / "bin" / "standee")
    if host_bin and Path(host_bin).is_file():
        return subprocess.run(
            [host_bin, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    raise StackRefError(
        f"standee not reachable: no key/target at {ssh_dir} and no standee binary on PATH"
    )


def _read_status_json(
    env_name: str,
    *,
    standee_bin: str = "",
    ssh_dir: Path = DEFAULT_STANDEE_SSH_DIR,
) -> dict[str, Any] | None:
    proc = run_standee(
        ["status", env_name, "--json"],
        standee_bin=standee_bin,
        ssh_dir=ssh_dir,
        timeout=60,
    )
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise StackRefError(
            f"standee status {env_name} --json returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise StackRefError(
            f"standee status {env_name} --json returned non-object JSON"
        )
    return data


def _renew_ttl(
    env_name: str,
    ttl: str,
    *,
    standee_bin: str = "",
    ssh_dir: Path = DEFAULT_STANDEE_SSH_DIR,
) -> None:
    renew_args = (
        ["renew", env_name, "--forever"]
        if ttl == "never"
        else ["renew", env_name, "--for", ttl]
    )
    proc = run_standee(
        renew_args,
        standee_bin=standee_bin,
        ssh_dir=ssh_dir,
        timeout=60,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise StackRefError(
            f"standee {' '.join(renew_args)} failed (exit {proc.returncode}): {detail}"
        )


def cmd_up(
    *,
    product: str,
    ref: str = "origin/master",
    slug: str = "design",
    ttl: str = "",
    repo_dir: str = "",
    host_repo_dir: str = "",
    standee_bin: str = "",
    ssh_dir: Path = DEFAULT_STANDEE_SSH_DIR,
    github_deploy_dir: Path = DEFAULT_GITHUB_DEPLOY_DIR,
) -> dict[str, Any]:
    prod = validate_product(product)
    sl = validate_slug(slug)
    clean_ref = validate_ref(ref)
    clean_ttl = validate_ttl(ttl)
    env_name = resolve_env_name("", prod, sl)

    local_repo, host_repo = locate_product_repo(
        prod,
        repo_dir=repo_dir,
        host_repo_dir=host_repo_dir,
    )
    commit = fetch_and_resolve_ref(
        local_repo,
        clean_ref,
        github_deploy_dir=github_deploy_dir,
    )
    short_commit = commit[:7]

    existing = _read_status_json(
        env_name,
        standee_bin=standee_bin,
        ssh_dir=ssh_dir,
    )
    if existing is not None:
        existing_status = existing.get("status")
        existing_commit = existing.get("commit")
        existing_sha = (
            existing_commit.get("sha")
            if isinstance(existing_commit, dict)
            else None
        )
        existing_url = str(existing.get("url") or "").strip()
        if (
            existing_status == "running"
            and existing_sha == commit
            and bool(existing_url)
        ):
            if clean_ttl:
                _renew_ttl(
                    env_name,
                    clean_ttl,
                    standee_bin=standee_bin,
                    ssh_dir=ssh_dir,
                )
            actual_name = str(existing.get("name") or env_name)
            return {
                "status": "up",
                "env_name": actual_name,
                "base_url": existing_url,
                "url": existing_url,
                "commit": commit,
                "short_commit": short_commit,
                "ref": clean_ref,
                "product": prod,
                "reused": True,
            }

    up_args = [
        "up",
        str(host_repo),
        "--project",
        prod,
        "--as",
        sl,
        "--tier",
        "dev",
        "--ref",
        commit,
        "--gateway",
        "--wait",
    ]
    if clean_ttl:
        up_args.extend(["--ttl", clean_ttl])

    up_proc = run_standee(
        up_args,
        standee_bin=standee_bin,
        ssh_dir=ssh_dir,
        timeout=540,
    )
    if up_proc.stdout:
        sys.stderr.write(up_proc.stdout)
    if up_proc.stderr:
        sys.stderr.write(up_proc.stderr)
    if up_proc.returncode != 0:
        detail = (up_proc.stderr or up_proc.stdout).strip()
        raise StackRefError(
            f"standee up failed for {env_name} at {short_commit} (exit {up_proc.returncode}): {detail}",
            env_name=env_name,
            commit=commit,
        )

    banner_match = UP_BANNER_RE.search(up_proc.stdout or "")
    actual_name = banner_match.group(1) if banner_match else env_name

    after = _read_status_json(
        actual_name,
        standee_bin=standee_bin,
        ssh_dir=ssh_dir,
    )
    if after is None:
        raise StackRefError(
            f"standee status {actual_name} --json failed after standee up",
            env_name=actual_name,
            commit=commit,
        )
    url = str(after.get("url") or "").strip()
    if not url:
        raise StackRefError(
            f"standee status {actual_name} --json returned empty url",
            env_name=actual_name,
            commit=commit,
        )
    if after.get("status") != "running":
        raise StackRefError(
            f"standee status {actual_name} reported status={after.get('status')!r} after up",
            env_name=actual_name,
            commit=commit,
        )

    return {
        "status": "up",
        "env_name": str(after.get("name") or actual_name),
        "base_url": url,
        "url": url,
        "commit": commit,
        "short_commit": short_commit,
        "ref": clean_ref,
        "product": prod,
        "reused": False,
    }


def cmd_seed(
    *,
    env_name: str = "",
    product: str = "",
    slug: str = "design",
    standee_bin: str = "",
    ssh_dir: Path = DEFAULT_STANDEE_SSH_DIR,
) -> dict[str, Any]:
    resolved_env = resolve_env_name(env_name, product, slug)
    proc = run_standee(
        ["seed", resolved_env],
        standee_bin=standee_bin,
        ssh_dir=ssh_dir,
        timeout=120,
    )
    if proc.stdout:
        sys.stderr.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise StackRefError(
            f"standee seed {resolved_env} failed (exit {proc.returncode}): {detail}",
            env_name=resolved_env,
        )
    return {
        "status": "seeded",
        "env_name": resolved_env,
    }


def _find_env_volumes(env_name: str, docker_bin: str) -> list[str]:
    by_label = subprocess.run(
        [
            docker_bin,
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={env_name}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    by_name = subprocess.run(
        [docker_bin, "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    found: set[str] = set()
    if by_label.returncode == 0:
        for line in by_label.stdout.splitlines():
            v = line.strip()
            if v:
                found.add(v)
    if by_name.returncode == 0:
        prefix = f"{env_name}_"
        for line in by_name.stdout.splitlines():
            v = line.strip()
            if v.startswith(prefix):
                found.add(v)
    return sorted(found)


def cmd_down(
    *,
    env_name: str = "",
    product: str = "",
    slug: str = "design",
    standee_bin: str = "",
    ssh_dir: Path = DEFAULT_STANDEE_SSH_DIR,
    docker_bin: str = "",
) -> dict[str, Any]:
    resolved_env = resolve_env_name(env_name, product, slug)
    proc = run_standee(
        ["down", resolved_env, "--volumes", "--images"],
        standee_bin=standee_bin,
        ssh_dir=ssh_dir,
        timeout=180,
    )
    if proc.stdout:
        sys.stderr.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    standee_removed = re.findall(
        rf"^Removed leftover volume '([^']+)' for '{re.escape(resolved_env)}'\.$",
        combined,
        flags=re.MULTILINE,
    )
    if "leftover volume cleanup incomplete" in combined:
        raise StackRefError(
            f"standee could not remove every leftover volume of {resolved_env}",
            env_name=resolved_env,
        )
    if proc.returncode != 0:
        if "no environment named" in combined.lower():
            down_status = "absent"
        else:
            detail = (proc.stderr or proc.stdout).strip()
            raise StackRefError(
                f"standee down {resolved_env} failed (exit {proc.returncode}): {detail}",
                env_name=resolved_env,
            )
    elif (
        standee_removed
        or f"No leftover volumes for '{resolved_env}'." in combined
        or re.search(
            rf"^Removed \d+ leftover volume\(s\) for '{re.escape(resolved_env)}'\.$",
            combined,
            flags=re.MULTILINE,
        )
    ):
        down_status = "absent"
    else:
        down_status = "down"

    resolved_docker = (
        docker_bin
        or os.environ.get("DOCKER_BIN", "").strip()
        or shutil.which("docker")
        or ""
    )
    removed_count = len(standee_removed)
    if resolved_docker:
        leftover = _find_env_volumes(resolved_env, resolved_docker)
        if leftover:
            for vol in leftover:
                rm_proc = subprocess.run(
                    [resolved_docker, "volume", "rm", "-f", vol],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if rm_proc.returncode == 0:
                    removed_count += 1
            still_left = _find_env_volumes(resolved_env, resolved_docker)
            if still_left:
                raise StackRefError(
                    "volumes remained after standee down --volumes and docker volume rm",
                    env_name=resolved_env,
                    volumes_left=" ".join(still_left),
                )

    return {
        "status": down_status,
        "env_name": resolved_env,
        "volumes_left": "none",
        "leftover_volumes_removed": removed_count,
    }


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        fail(f"invalid arguments: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="stack_ref.py",
        description="Provision, seed, and tear down ref-pinned dev stacks via standee.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    up_p = sub.add_parser("up", help="Ensure <product>-dev-<slug> is up at <ref>.")
    up_p.add_argument("--product", default="", help="Product name (e.g. rollcall).")
    up_p.add_argument(
        "--ref",
        default="origin/master",
        help="Git ref to build/verify (default: origin/master).",
    )
    up_p.add_argument(
        "--slug",
        default="design",
        help="Environment slug for <product>-dev-<slug> (default: design).",
    )
    up_p.add_argument(
        "--ttl",
        default="",
        help="Optional standee TTL (e.g. 12h, 3d, never).",
    )
    up_p.add_argument("--repo-dir", default="", help="Optional local repo path override.")
    up_p.add_argument(
        "--host-repo-dir", default="", help="Optional host repo path override."
    )
    up_p.add_argument("--standee-bin", default="", help="Optional standee binary override.")
    up_p.add_argument(
        "--standee-ssh-dir",
        default=str(DEFAULT_STANDEE_SSH_DIR),
        help="Path to standee SSH directory.",
    )
    up_p.add_argument(
        "--github-deploy-dir",
        default=str(DEFAULT_GITHUB_DEPLOY_DIR),
        help="Path to github-deploy SSH key directory.",
    )

    seed_p = sub.add_parser("seed", help="Reset dev seed data on <env_name>.")
    seed_p.add_argument("--env-name", default="", help="Environment name (<product>-dev-<slug>).")
    seed_p.add_argument("--product", default="", help="Product name if --env-name omitted.")
    seed_p.add_argument("--slug", default="design", help="Environment slug (default: design).")
    seed_p.add_argument("--standee-bin", default="", help="Optional standee binary override.")
    seed_p.add_argument(
        "--standee-ssh-dir",
        default=str(DEFAULT_STANDEE_SSH_DIR),
        help="Path to standee SSH directory.",
    )

    down_p = sub.add_parser("down", help="Tear down <env_name> and remove its volumes/images.")
    down_p.add_argument("--env-name", default="", help="Environment name (<product>-dev-<slug>).")
    down_p.add_argument("--product", default="", help="Product name if --env-name omitted.")
    down_p.add_argument("--slug", default="design", help="Environment slug (default: design).")
    down_p.add_argument("--standee-bin", default="", help="Optional standee binary override.")
    down_p.add_argument(
        "--standee-ssh-dir",
        default=str(DEFAULT_STANDEE_SSH_DIR),
        help="Path to standee SSH directory.",
    )
    down_p.add_argument("--docker-bin", default="", help="Optional docker binary override.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.subcommand:
        fail("missing subcommand: expected one of 'up', 'seed', 'down'")

    try:
        if args.subcommand == "up":
            result = cmd_up(
                product=args.product,
                ref=args.ref,
                slug=args.slug,
                ttl=args.ttl,
                repo_dir=args.repo_dir,
                host_repo_dir=args.host_repo_dir,
                standee_bin=args.standee_bin,
                ssh_dir=Path(args.standee_ssh_dir),
                github_deploy_dir=Path(args.github_deploy_dir),
            )
        elif args.subcommand == "seed":
            result = cmd_seed(
                env_name=args.env_name,
                product=args.product,
                slug=args.slug,
                standee_bin=args.standee_bin,
                ssh_dir=Path(args.standee_ssh_dir),
            )
        elif args.subcommand == "down":
            result = cmd_down(
                env_name=args.env_name,
                product=args.product,
                slug=args.slug,
                standee_bin=args.standee_bin,
                ssh_dir=Path(args.standee_ssh_dir),
                docker_bin=args.docker_bin,
            )
        else:
            raise StackRefError(f"unknown subcommand: {args.subcommand!r}")
    except StackRefError as exc:
        fail(exc.message, **exc.extra)
    except Exception as exc:
        fail(f"unexpected error in stack_ref {args.subcommand}: {exc}")

    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
