#!/usr/bin/env python3
"""Clone a shallow single-branch GitHub repo and check out a work branch inside a run container.

Contract:
- Validates all inputs (repo_url, base_branch, branch, label, resume, root) up front
  before making any network or token request.
- Requests a short-lived GitHub App installation token from the Temper server via
  POST ${TEMPER_SERVER_URL:-${TEMPER_API:-http://temper-ai-server-1:8420}}/api/github/token
  with JSON body {"repo": "<owner>/<repo>"}.
  - On HTTP 404 (app not installed on repo), fails loud naming the repo and the missing
    GitHub App installation (temper-ai-bot), never falling back to any env token or deploy key.
  - Only when the Temper server /api/github/token route is unreachable (connection error or
    HTTP 503 app not configured) and single env var GITHUB_TOKEN is set, falls back to
    GITHUB_TOKEN over HTTPS.
- Passes initial clone credentials to git via ephemeral environment HTTP header config
  (GIT_CONFIG_COUNT=1, GIT_CONFIG_KEY_0=http.https://github.com/.extraheader,
  GIT_CONFIG_VALUE_0="Authorization: Basic <base64(x-access-token:token)>",
  GIT_TERMINAL_PROMPT=0, GIT_CONFIG_NOSYSTEM=1, GIT_CONFIG_GLOBAL=/dev/null),
  and configures <root>/repo/.git/config with an on-demand credential helper
  (`!<python> <code_checkout.py> --credential-helper --repo <owner>/<repo>`,
  `credential.https://github.com.useHttpPath=true`) so later `git push`/`git fetch`
  calls in long runs (>1h) re-request a fresh installation token on demand without
  ever writing or caching tokens on disk.
- Clones <root>/repo with --single-branch --branch <base_branch> --depth 1 and
  checks out <branch> directly inside <root>/repo (or resumes an existing work branch
  when resume=true). No git worktree is created.
- Callers needing deeper commit history can call `deepen_checkout(<path>, <N>)` or run
  `git -C <path> fetch --deepen=<N> origin` (or pass `--deepen <N>`), never silently
  full-cloning.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ROOT = "/tmp/temper-checkout"
DEFAULT_SERVER_URL = "http://temper-ai-server-1:8420"
FALLBACK_LOCAL_SERVER_URL = "http://127.0.0.1:8420"
FORBIDDEN_HOST_PREFIX = Path("/home/shinelay")
FORBIDDEN_CONTAINER_WORKSPACES = Path("/app/workspaces")

GITHUB_URL_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<owner>[A-Za-z0-9][A-Za-z0-9_.-]{0,99})/"
    r"(?P<repo>[A-Za-z0-9][A-Za-z0-9_.-]{0,99}?)(?:\.git)?$"
)
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
LABEL_CHECK_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"tghk_[A-Za-z0-9_-]+"),
    re.compile(r"trun_[A-Za-z0-9_-]+"),
    re.compile(r"(?i)(Authorization:\s*(?:Basic|Bearer)\s+)[A-Za-z0-9+/=._-]+"),
    re.compile(r"x-access-token:[^\s\"'@]+"),
)


class CodeCheckoutError(Exception):
    """Raised on any validation, auth, or git failure."""


CheckoutError = CodeCheckoutError

AUTH_FAILURE_RE = re.compile(
    r"(?i)(?:\b401\b|\b403\b|unauthorized|authentication failed|"
    r"invalid username or (?:password|token)|token (?:expired|revoked)|"
    r"bad credentials|could not read username|terminal prompts disabled|"
    r"unable to get password|credential helper)"
)


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _is_only_redacted_or_empty(scrubbed: str) -> bool:
    stripped = (scrubbed or "").strip()
    if not stripped:
        return True
    return bool(re.fullmatch(r"(?:\[REDACTED\]|\s|[:;,.!?\-_*'\"]+)+", stripped))


def scrub_secrets(text: str, extra_secrets: list[str] | None = None) -> str:
    """Remove any token, base64 credential, or run key from error/log text."""
    if not text:
        return ""
    out = text
    candidates: list[str] = []
    if extra_secrets:
        candidates.extend(s for s in extra_secrets if s)
    for env_key in (
        "TEMPER_RUN_GITHUB_KEY",
        "TEMPER_RUN_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ):
        val = os.environ.get(env_key, "").strip()
        if val:
            candidates.append(val)
    for secret in candidates:
        if secret and secret in out:
            out = out.replace(secret, "[REDACTED]")
        try:
            b64 = base64.b64encode(f"x-access-token:{secret}".encode()).decode("ascii")
            if b64 and b64 in out:
                out = out.replace(b64, "[REDACTED]")
        except Exception:
            pass
    for pat in SECRET_PATTERNS:
        if pat.groups:
            out = pat.sub(r"\1[REDACTED]", out)
        else:
            out = pat.sub("[REDACTED]", out)
    return out


def _format_git_failure_detail(
    raw_output: str,
    *,
    returncode: int,
    extra_secrets: list[str] | None = None,
) -> str:
    """Scrub git stderr/stdout and guarantee a loud non-empty error naming auth/token expiry when applicable."""
    raw = (raw_output or "").strip()
    if not raw:
        return f"exit code {returncode} (no stderr/stdout output)"
    scrubbed = scrub_secrets(raw, extra_secrets).strip()
    if _is_only_redacted_or_empty(scrubbed):
        return (
            f"[REDACTED] (exit code {returncode}: output contained only redacted secret material; "
            "GitHub token expired or authentication failed)"
        )
    if AUTH_FAILURE_RE.search(raw) or AUTH_FAILURE_RE.search(scrubbed):
        if "token expired" not in scrubbed.lower():
            return f"GitHub token expired or authentication failed: {scrubbed}"
    return scrubbed


def fail(message: str, extra_secrets: list[str] | None = None) -> None:
    scrubbed = scrub_secrets(message, extra_secrets).strip()
    if _is_only_redacted_or_empty(scrubbed):
        scrubbed = (
            "[REDACTED] (error message contained only redacted secret material; "
            "GitHub token expired or authentication failed)"
        )
    emit({"status": "failed", "error": scrubbed})
    raise SystemExit(1)


def _has_Unsafe_chars(value: str) -> bool:
    return any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)


def parse_and_validate_repo_url(repo_url: str) -> tuple[str, str, str, str]:
    """Validate repo_url and return (owner, repo_name, '<owner>/<repo>', https_remote_url)."""
    if not isinstance(repo_url, str) or not repo_url:
        raise CodeCheckoutError("invalid repo_url '': repository URL is required")
    if _has_Unsafe_chars(repo_url):
        raise CodeCheckoutError(
            f"invalid repo_url {repo_url!r}: must not contain whitespace or control characters"
        )
    if ".." in repo_url or "\\" in repo_url:
        raise CodeCheckoutError(
            f"invalid repo_url {repo_url!r}: path traversal is forbidden"
        )

    match = GITHUB_URL_RE.fullmatch(repo_url)
    if not match:
        raise CodeCheckoutError(
            f"invalid repo_url {repo_url!r}: expected https://github.com/<owner>/<repo>[.git] "
            "or git@github.com:<owner>/<repo>[.git] or ssh://git@github.com/<owner>/<repo>[.git]"
        )

    owner = match.group("owner")
    repo_name = match.group("repo")
    for part_name, part in (("owner", owner), ("repo", repo_name)):
        if part in {".", ".."} or ".." in part or part.endswith("."):
            raise CodeCheckoutError(
                f"invalid repo_url {repo_url!r}: malformed {part_name} {part!r}"
            )

    repo_slug = f"{owner}/{repo_name}"
    https_remote = f"https://github.com/{repo_slug}.git"
    return owner, repo_name, repo_slug, https_remote


def validate_branch_name(branch: str, *, field: str = "branch") -> str:
    """Validate a git branch name against safe git check-ref-format rules."""
    if not isinstance(branch, str) or not branch:
        raise CodeCheckoutError(
            f"invalid {field} {branch!r}: must be a non-empty branch name"
        )
    if _has_Unsafe_chars(branch):
        raise CodeCheckoutError(
            f"invalid {field} {branch!r}: must not contain whitespace or control characters"
        )
    if (
        branch.startswith(("-", "/", "."))
        or branch.endswith(("/", ".", ".lock"))
        or ".." in branch
        or "//" in branch
        or "@{" in branch
        or "\\" in branch
        or not BRANCH_RE.fullmatch(branch)
    ):
        raise CodeCheckoutError(f"invalid {field} {branch!r}: unsafe git ref syntax")
    for segment in branch.split("/"):
        if not segment or segment.startswith(".") or segment.endswith(".lock"):
            raise CodeCheckoutError(
                f"invalid {field} {branch!r}: invalid ref path component {segment!r}"
            )
    return branch


def sanitize_label(label: str) -> str:
    """Sanitize optional label slug into [a-z0-9-]+."""
    if label is None or label == "":
        return ""
    if not isinstance(label, str) or _has_Unsafe_chars(label) or ".." in label:
        raise CodeCheckoutError(
            f"invalid label {label!r}: must be a safe slug ([a-z0-9-]+)"
        )
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:48].rstrip("-")
    if not slug or not LABEL_CHECK_RE.fullmatch(slug):
        raise CodeCheckoutError(f"invalid label {label!r}: must contain [a-z0-9]")
    return slug


def resolve_run_id(env: dict[str, str] | None = None) -> str:
    """Derive a clean run identifier from $TEMPER_RUN_CONTAINER, $TEMPER_RUN_ID, or random hex."""
    environ = env if env is not None else os.environ
    container = environ.get("TEMPER_RUN_CONTAINER", "").strip()
    raw_id = ""
    if container:
        if container.startswith("temper-run-"):
            raw_id = container[len("temper-run-") :]
        else:
            raw_id = container
    elif environ.get("TEMPER_RUN_ID", "").strip():
        raw_id = environ["TEMPER_RUN_ID"].strip()

    if raw_id:
        cleaned = re.sub(r"[^a-z0-9]+", "-", raw_id.lower()).strip("-")
        if cleaned:
            return cleaned[:48].rstrip("-")
    return secrets.token_hex(6)


def resolve_branch(branch: str, label: str, env: dict[str, str] | None = None) -> str:
    """Resolve explicit branch or build default branch from label and run id."""
    if branch and branch.strip():
        if label:
            sanitize_label(label)
        return validate_branch_name(branch, field="branch")

    clean_label = sanitize_label(label)
    run_id = resolve_run_id(env=env)
    if clean_label:
        alnum_run = re.sub(r"[^a-z0-9]", "", run_id)[:8] or secrets.token_hex(4)
        candidate = f"run-{clean_label}-{alnum_run}"
    else:
        candidate = f"run-{run_id}"
    return validate_branch_name(candidate, field="branch")


def parse_resume(value: str | bool | None) -> bool:
    """Parse resume boolean from bool or string."""
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"true", "1", "yes"}:
            return True
        if norm in {"false", "0", "no"}:
            return False
    raise CodeCheckoutError(
        f"invalid resume value {value!r}: expected 'true' or 'false'"
    )


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_root(root: str, env: dict[str, str] | None = None) -> Path:
    """Validate container-local checkout root; forbid host paths and WORKSPACE_DIR."""
    environ = env if env is not None else os.environ
    if not isinstance(root, str) or not root.strip():
        raise CodeCheckoutError("invalid root '': root path is required")
    if _has_Unsafe_chars(root):
        raise CodeCheckoutError(
            f"invalid root {root!r}: must not contain whitespace or control characters"
        )

    raw_path = Path(root)
    if not raw_path.is_absolute():
        raise CodeCheckoutError(
            f"invalid root {root!r}: root must be an absolute path inside the container"
        )
    if ".." in raw_path.parts:
        raise CodeCheckoutError(
            f"invalid root {root!r}: path traversal '..' is forbidden"
        )

    resolved = raw_path.resolve(strict=False)
    if resolved in {Path("/"), Path("/tmp")}:
        raise CodeCheckoutError(
            f"invalid root {root!r}: root must be a dedicated directory such as {DEFAULT_ROOT}"
        )

    forbidden_roots: list[tuple[str, Path]] = [
        ("/home/shinelay", FORBIDDEN_HOST_PREFIX),
        ("/app/workspaces", FORBIDDEN_CONTAINER_WORKSPACES),
    ]
    workspace_dir = environ.get("WORKSPACE_DIR", "").strip()
    if workspace_dir:
        ws_path = Path(workspace_dir)
        forbidden_roots.append(("WORKSPACE_DIR", ws_path))
        forbidden_roots.append(("WORKSPACE_DIR", ws_path.resolve(strict=False)))

    for label, forbidden in forbidden_roots:
        if _is_within(raw_path, forbidden) or _is_within(resolved, forbidden):
            raise CodeCheckoutError(
                f"invalid root {root!r}: checkout root must not be inside {label} ({forbidden})"
            )

    return resolved


def fetch_github_token(
    repo_slug: str,
    *,
    repo_url: str,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> str:
    """Request a short-lived GitHub installation token from the Temper server.

    - HTTP 404 (temper-ai-bot not installed on repo): fail loud naming both the
      repository and the missing GitHub App installation, without any fallback.
    - Unreachable server (connection error / timeout) or HTTP 503 (app not configured):
      fall back to single env variable GITHUB_TOKEN if set, else fail loud.
    """
    environ = env if env is not None else os.environ
    explicit_url = (
        (environ.get("TEMPER_SERVER_URL") or environ.get("TEMPER_API") or "")
        .strip()
        .rstrip("/")
    )
    candidate_urls = (
        [explicit_url]
        if explicit_url
        else [DEFAULT_SERVER_URL, FALLBACK_LOCAL_SERVER_URL]
    )

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    bearer = (
        environ.get("TEMPER_RUN_GITHUB_KEY") or environ.get("TEMPER_RUN_TOKEN") or ""
    ).strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    body = json.dumps({"repo": repo_slug}).encode()
    last_err: str = ""

    for base_url in candidate_urls:
        endpoint = f"{base_url}/api/github/token"
        req = urllib.request.Request(
            endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_resp = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw_resp)
                token = str(data.get("token") or "").strip()
                if not token:
                    raise CodeCheckoutError(
                        f"Temper server returned empty GitHub token for {repo_slug} ({repo_url})"
                    )
                return token
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                err_body = str(exc)
            detail = err_body
            try:
                parsed = json.loads(err_body)
                if isinstance(parsed, dict) and parsed.get("detail"):
                    detail = str(parsed["detail"])
            except Exception:
                pass
            if exc.code == 404:
                if not detail:
                    detail = f"the app is not installed on {repo_slug}"
                scrubbed_404 = scrub_secrets(
                    detail, [bearer] if bearer else None
                ).strip()
                if _is_only_redacted_or_empty(scrubbed_404):
                    scrubbed_404 = f"the app is not installed on {repo_slug} ([REDACTED])"
                raise CodeCheckoutError(
                    f"GitHub App installation (temper-ai-bot) does not cover repository '{repo_slug}' ({repo_url}): {scrubbed_404}"
                ) from exc
            if exc.code == 503:
                last_err = scrub_secrets(
                    f"HTTP 503 {detail}".strip(), [bearer] if bearer else None
                )
                continue
            scrubbed_detail = scrub_secrets(
                detail, [bearer] if bearer else None
            ).strip()
            if _is_only_redacted_or_empty(scrubbed_detail):
                scrubbed_detail = (
                    "[REDACTED] (response contained only redacted secret material)"
                )
            if exc.code in (401, 403):
                auth_reason = (
                    "GitHub token expired or authentication failed"
                    if exc.code == 401
                    else "GitHub token expired, authentication failed, or access denied"
                )
                raise CodeCheckoutError(
                    f"repository '{repo_slug}' ({repo_url}) {auth_reason}: HTTP {exc.code} {scrubbed_detail}"
                ) from exc
            raise CodeCheckoutError(
                f"repository '{repo_slug}' ({repo_url}) is unreachable or token request failed: HTTP {exc.code} {scrubbed_detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            reason = getattr(exc, "reason", None) or exc
            last_err = scrub_secrets(str(reason), [bearer] if bearer else None)
            continue
        except CodeCheckoutError:
            raise
        except Exception as exc:
            raise CodeCheckoutError(
                scrub_secrets(
                    f"failed to mint GitHub token for {repo_slug} ({repo_url}): {exc}",
                    [bearer] if bearer else None,
                )
            ) from exc

    fallback_token = environ.get("GITHUB_TOKEN", "").strip()
    if fallback_token:
        return fallback_token

    raise CodeCheckoutError(
        scrub_secrets(
            f"failed to reach Temper server for GitHub token ({repo_slug}, {repo_url}): {last_err}",
            [bearer] if bearer else None,
        )
    )


def build_credential_helper_command(
    repo_slug: str,
    *,
    python_executable: str | None = None,
    script_path: Path | None = None,
) -> str:
    """Build the git credential.https://github.com.helper command string."""
    py_exe = (python_executable or sys.executable or "python3").strip()
    resolved_script = str((script_path or Path(__file__)).resolve())
    return (
        f"!{shlex.quote(py_exe)} {shlex.quote(resolved_script)} "
        f"--credential-helper --repo {shlex.quote(repo_slug)}"
    )


def run_credential_helper(
    repo: str,
    operation: str = "get",
    *,
    env: dict[str, str] | None = None,
) -> int:
    """Implement Git's credential helper protocol (get / store / erase) on demand."""
    environ = env if env is not None else os.environ
    op = (operation or "get").strip().lower()
    if not isinstance(repo, str) or not repo.strip():
        raise CodeCheckoutError(
            "--repo <owner>/<repo> is required for --credential-helper"
        )
    raw_repo = repo.strip()
    if (
        "/" not in raw_repo
        or raw_repo.startswith(("http://", "https://", "git@", "ssh://"))
        or raw_repo.endswith(".git")
    ):
        raise CodeCheckoutError(f"invalid --repo {repo!r}: expected '<owner>/<repo>'")
    _, _, repo_slug, https_remote = parse_and_validate_repo_url(
        f"https://github.com/{raw_repo}"
    )

    if op in {"store", "erase"} or op != "get":
        # Never persist or cache tokens on disk.
        return 0

    token = fetch_github_token(repo_slug, repo_url=https_remote, env=environ)
    sys.stdout.write(f"username=x-access-token\npassword={token}\n\n")
    sys.stdout.flush()
    return 0


def build_git_env(token: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build ephemeral git environment passing token via HTTP extraheader only."""
    env = dict(base_env if base_env is not None else os.environ)
    for key in list(env):
        if key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
            del env[key]
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
    env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {basic}"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    return env


def run_git(
    args: list[str],
    *,
    git_env: dict[str, str],
    token: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run git command with ephemeral credentials and scrubbed errors."""
    cmd = ["git"]
    if cwd is not None:
        cmd.extend(["-C", str(cwd)])
    cmd.extend(args)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=git_env,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = _format_git_failure_detail(
            proc.stderr or proc.stdout or "",
            returncode=proc.returncode,
            extra_secrets=[token] if token else None,
        )
        label_args = [a for a in args if a != "--quiet"][:3]
        if (
            label_args[:1] == ["fetch"]
            and len(label_args) >= 2
            and label_args[1].startswith("--deepen=")
        ):
            label_args = label_args[:2]
        raise CodeCheckoutError(f"git {' '.join(label_args)} failed: {detail}")
    return proc


def list_remote_heads(
    https_remote: str,
    *,
    repo_slug: str,
    repo_url: str,
    git_env: dict[str, str],
    token: str,
) -> dict[str, str]:
    """Run git ls-remote --heads and return mapping {branch_name: sha40}."""
    proc = run_git(
        ["ls-remote", "--heads", https_remote],
        git_env=git_env,
        token=token,
        check=False,
    )
    if proc.returncode != 0:
        detail = _format_git_failure_detail(
            proc.stderr or proc.stdout or "",
            returncode=proc.returncode,
            extra_secrets=[token] if token else None,
        )
        raise CodeCheckoutError(
            f"repository '{repo_slug}' ({repo_url}) is unreachable or access was denied: {detail}"
        )

    heads: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        sha, ref = line.split("\t", 1)
        prefix = "refs/heads/"
        if ref.startswith(prefix) and SHA40_RE.fullmatch(sha):
            heads[ref[len(prefix) :]] = sha
    return heads


def _local_branch_exists(
    repo_path: Path, branch: str, *, git_env: dict[str, str], token: str
) -> bool:
    proc = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo_path,
        git_env=git_env,
        token=token,
        check=False,
    )
    return proc.returncode == 0


def _ensure_no_persisted_credentials(repo_path: Path, token: str) -> None:
    """Assert that .git/config does not contain the installation token or extraheader."""
    git_config = repo_path / ".git" / "config"
    if not git_config.is_file():
        return
    content = git_config.read_text(encoding="utf-8", errors="replace")
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    if (
        token in content
        or basic in content
        or "x-access-token:" in content
        or any(pat.search(content) for pat in SECRET_PATTERNS)
    ):
        raise CodeCheckoutError("credential leak detected in .git/config")


def deepen_checkout(
    repo_path: Path | str,
    depth: int,
    *,
    token: str = "",
    env: dict[str, str] | None = None,
    git_env: dict[str, str] | None = None,
) -> None:
    """Deepen a shallow checkout at `repo_path` by `depth` additional commits without full-cloning."""
    if isinstance(depth, bool) or not isinstance(depth, int) or depth <= 0:
        raise CodeCheckoutError(
            f"git fetch --deepen={depth} failed: invalid deepen value {depth} (must be a positive integer)"
        )
    target_path = Path(repo_path)
    if not (target_path / ".git").exists():
        raise CodeCheckoutError(
            f"git fetch --deepen={depth} failed: checkout path '{target_path}' is not a git repository"
        )
    if git_env is not None:
        effective_env = git_env
    elif token:
        effective_env = build_git_env(token, base_env=env)
    else:
        effective_env = dict(env if env is not None else os.environ)
        for key in list(effective_env):
            if (
                key == "GIT_CONFIG_COUNT"
                or key.startswith("GIT_CONFIG_KEY_")
                or key.startswith("GIT_CONFIG_VALUE_")
            ):
                del effective_env[key]
        effective_env["GIT_TERMINAL_PROMPT"] = "0"
        effective_env["GIT_CONFIG_NOSYSTEM"] = "1"
        effective_env["GIT_CONFIG_GLOBAL"] = "/dev/null"

    run_git(
        ["fetch", f"--deepen={depth}", "--quiet", "origin"],
        cwd=target_path,
        git_env=effective_env,
        token=token,
    )


deepen_history = deepen_checkout


def checkout_code(
    *,
    repo_url: str,
    base_branch: str,
    branch: str = "",
    label: str = "",
    resume: str | bool = False,
    root: str = DEFAULT_ROOT,
    deepen: int = 0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate inputs, mint short-lived GitHub token, shallow-clone repo into <root>/repo, and check out/resume branch."""
    environ = env if env is not None else os.environ

    # 1. Validate all inputs before any network or token request.
    _, _, repo_slug, https_remote = parse_and_validate_repo_url(repo_url)
    valid_base = validate_branch_name(base_branch, field="base_branch")
    resume_flag = parse_resume(resume)
    valid_branch = resolve_branch(branch, label, env=environ)
    if valid_branch == valid_base:
        raise CodeCheckoutError(
            f"work branch '{valid_branch}' must differ from base_branch '{valid_base}'"
        )
    root_path = validate_root(root, env=environ)
    if isinstance(deepen, bool) or not isinstance(deepen, int) or deepen < 0:
        raise CodeCheckoutError(
            f"git fetch --deepen={deepen} failed: invalid deepen value {deepen}: must be >= 0"
        )

    repo_path = root_path / "repo"
    repo_existed = (repo_path / ".git").exists()

    # 2. Fast local check before network when resume=false.
    if not resume_flag and repo_existed:
        check_proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{valid_branch}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if check_proc.returncode == 0:
            raise CodeCheckoutError(
                f"work branch '{valid_branch}' already exists locally in {repo_path} (resume=false)"
            )

    # 3. Request short-lived installation token from Temper server.
    token = fetch_github_token(repo_slug, repo_url=repo_url, env=environ)
    git_env = build_git_env(token, base_env=environ)

    # 4. Check remote reachability and branch refs via git ls-remote --heads.
    remote_heads = list_remote_heads(
        https_remote,
        repo_slug=repo_slug,
        repo_url=repo_url,
        git_env=git_env,
        token=token,
    )
    if valid_base not in remote_heads:
        raise CodeCheckoutError(
            f"base_branch '{valid_base}' does not exist on origin for {repo_slug} ({repo_url})"
        )
    branch_on_origin = valid_branch in remote_heads
    if branch_on_origin and not resume_flag:
        raise CodeCheckoutError(
            f"work branch '{valid_branch}' already exists on origin for {repo_slug} (resume=false)"
        )

    # 5. Clone or refresh <root>/repo (--single-branch --branch <base_branch> --depth 1).
    root_path.mkdir(parents=True, exist_ok=True)
    if repo_existed:
        run_git(
            ["remote", "set-url", "origin", https_remote],
            cwd=repo_path,
            git_env=git_env,
            token=token,
        )
        run_git(
            [
                "fetch",
                "--quiet",
                "--depth",
                "1",
                "origin",
                f"+refs/heads/{valid_base}:refs/remotes/origin/{valid_base}",
            ],
            cwd=repo_path,
            git_env=git_env,
            token=token,
        )
    else:
        if repo_path.exists():
            if any(repo_path.iterdir()):
                raise CodeCheckoutError(
                    f"checkout path '{repo_path}' already exists and is not a git repository"
                )
            shutil.rmtree(repo_path)
        run_git(
            [
                "clone",
                "--quiet",
                "--single-branch",
                "--branch",
                valid_base,
                "--depth",
                "1",
                https_remote,
                str(repo_path),
            ],
            git_env=git_env,
            token=token,
        )

    helper_cmd = build_credential_helper_command(repo_slug)
    run_git(
        ["config", "user.name", "temper-bot"],
        cwd=repo_path,
        git_env=git_env,
        token=token,
    )
    run_git(
        ["config", "user.email", "bot@temper.ai"],
        cwd=repo_path,
        git_env=git_env,
        token=token,
    )
    run_git(
        ["config", "--replace-all", "credential.helper", ""],
        cwd=repo_path,
        git_env=git_env,
        token=token,
    )
    run_git(
        ["config", "--replace-all", "credential.https://github.com.helper", ""],
        cwd=repo_path,
        git_env=git_env,
        token=token,
    )
    run_git(
        ["config", "--add", "credential.https://github.com.helper", helper_cmd],
        cwd=repo_path,
        git_env=git_env,
        token=token,
    )
    run_git(
        ["config", "credential.https://github.com.useHttpPath", "true"],
        cwd=repo_path,
        git_env=git_env,
        token=token,
    )

    head_proc = run_git(
        ["rev-parse", "--verify", "refs/remotes/origin/" + valid_base + "^{commit}"],
        cwd=repo_path,
        git_env=git_env,
        token=token,
    )
    base_head = head_proc.stdout.strip()
    if not SHA40_RE.fullmatch(base_head):
        raise CodeCheckoutError(
            f"failed to resolve 40-char SHA for origin/{valid_base}: got {base_head!r}"
        )

    # 6. Check out or resume <branch> directly inside <root>/repo.
    if not resume_flag:
        if _local_branch_exists(repo_path, valid_branch, git_env=git_env, token=token):
            raise CodeCheckoutError(
                f"work branch '{valid_branch}' already exists locally in {repo_path} (resume=false)"
            )
        run_git(
            [
                "checkout",
                "--quiet",
                "-b",
                valid_branch,
                f"refs/remotes/origin/{valid_base}",
            ],
            cwd=repo_path,
            git_env=git_env,
            token=token,
        )
        mode = "cloned"
    else:
        current_branch = ""
        if repo_existed:
            branch_proc = run_git(
                ["rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
                git_env=git_env,
                token=token,
                check=False,
            )
            if branch_proc.returncode == 0:
                current_branch = branch_proc.stdout.strip()

        if repo_existed and current_branch == valid_branch:
            mode = "resumed"
        elif branch_on_origin:
            run_git(
                [
                    "fetch",
                    "--quiet",
                    "--depth",
                    "1",
                    "origin",
                    f"+refs/heads/{valid_branch}:refs/remotes/origin/{valid_branch}",
                ],
                cwd=repo_path,
                git_env=git_env,
                token=token,
            )
            run_git(
                [
                    "checkout",
                    "--quiet",
                    "-B",
                    valid_branch,
                    f"refs/remotes/origin/{valid_branch}",
                ],
                cwd=repo_path,
                git_env=git_env,
                token=token,
            )
            mode = "resumed"
        elif _local_branch_exists(
            repo_path, valid_branch, git_env=git_env, token=token
        ):
            run_git(
                [
                    "checkout",
                    "--quiet",
                    valid_branch,
                ],
                cwd=repo_path,
                git_env=git_env,
                token=token,
            )
            mode = "resumed"
        else:
            run_git(
                [
                    "checkout",
                    "--quiet",
                    "-b",
                    valid_branch,
                    f"refs/remotes/origin/{valid_base}",
                ],
                cwd=repo_path,
                git_env=git_env,
                token=token,
            )
            mode = "cloned"

    if deepen > 0:
        deepen_checkout(repo_path, deepen, token=token, git_env=git_env)

    _ensure_no_persisted_credentials(repo_path, token)

    return {
        "status": "ready",
        "repo": repo_slug,
        "repo_url": repo_url,
        "base_branch": valid_base,
        "base_head": base_head,
        "branch": valid_branch,
        "path": str(repo_path),
        "mode": mode,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Shallow-clone a GitHub repo and check out a work branch."
    )
    parser.add_argument(
        "--credential-helper",
        action="store_true",
        help="Run as a Git credential helper (get/store/erase) for --repo <owner>/<repo>",
    )
    parser.add_argument(
        "--repo",
        default="",
        help="Repository slug (<owner>/<repo>) for --credential-helper mode",
    )
    parser.add_argument(
        "operation",
        nargs="?",
        default="get",
        help="Git credential helper operation (get, store, erase)",
    )
    parser.add_argument("--repo-url", default="", help="GitHub repository URL")
    parser.add_argument(
        "--base-branch", default="", help="Existing branch on origin to start from"
    )
    parser.add_argument("--branch", default="", help="Work branch to create or resume")
    parser.add_argument(
        "--label", default="", help="Optional slug for default branch naming"
    )
    parser.add_argument(
        "--resume", default="false", help="true to resume an existing work branch"
    )
    parser.add_argument(
        "--root", default=DEFAULT_ROOT, help="Container-local root directory"
    )
    parser.add_argument(
        "--deepen",
        type=int,
        default=0,
        help="Optional additional commit depth to fetch via git fetch --deepen=<N>",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    if args.credential_helper:
        try:
            return run_credential_helper(
                repo=args.repo,
                operation=args.operation,
            )
        except CodeCheckoutError as exc:
            sys.stderr.write(scrub_secrets(str(exc)) + "\n")
            sys.stderr.flush()
            return 1
        except Exception as exc:
            sys.stderr.write(scrub_secrets(f"unexpected error: {exc}") + "\n")
            sys.stderr.flush()
            return 1

    try:
        result = checkout_code(
            repo_url=args.repo_url,
            base_branch=args.base_branch,
            branch=args.branch,
            label=args.label,
            resume=args.resume,
            root=args.root,
            deepen=args.deepen,
        )
        emit(result)
        return 0
    except CodeCheckoutError as exc:
        fail(str(exc))
    except Exception as exc:
        fail(f"unexpected error: {exc}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
