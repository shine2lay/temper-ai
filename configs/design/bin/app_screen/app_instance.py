"""Provisioned product instance boundary for stage 2 capture.

One job: given base_url + credentials (and optional version override), check reachability,
read GET {base_url}/api/health for {ok, version, commit}, log in accounts, and expose
"go to screen S in state T" / shoot captures over HTTP and Playwright.
No build, no process management, no git/standee/uv/npm/docker calls, and no credentials
written to files or error messages.
"""
from __future__ import annotations

import http.client
import http.cookies
import http.server
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import product_app

HERE = Path(__file__).resolve().parent
CAPTURE_JS = HERE / "existing_capture.mjs"
MEASURE_JS = HERE / "measure_in_page.js"
LIVE_HOSTS = frozenset({"rollcall.wai2shine.com"})
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
FULL_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?\s*$")
GH_CANDIDATES = ("/home/shinelay/.local/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh")


class AppInstanceError(RuntimeError):
    """A provisioned product instance could not be reached, checked, or logged into."""


InstanceError = AppInstanceError


def _scrub(text: str, secrets: list[str]) -> str:
    out = str(text or "")
    for secret in secrets:
        if secret and len(secret) >= 2:
            out = out.replace(secret, "[REDACTED]")
    return out


def validate_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        raise AppInstanceError("base_url is required (got empty base_url)")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AppInstanceError(f"base_url {raw!r} must be an http:// or https:// URL")
    host = (parsed.hostname or "").lower()
    if host in LIVE_HOSTS:
        raise AppInstanceError(f"refusing live production base_url {raw!r}")
    return raw


def normalize_credentials(credentials: dict[str, str] | str | None) -> dict[str, str]:
    if credentials is None:
        return {}
    if isinstance(credentials, str):
        val = credentials.strip()
        if not val:
            return {}
        if val.startswith("{"):
            try:
                parsed = json.loads(val)
            except ValueError as exc:
                raise AppInstanceError(f"credentials JSON is invalid: {exc}") from None
            if not isinstance(parsed, dict):
                raise AppInstanceError("credentials JSON must be an object mapping account -> password")
            return {str(k): str(v) for k, v in parsed.items() if v is not None}
        return {"*": val, "default": val}
    if isinstance(credentials, dict):
        return {str(k): str(v) for k, v in credentials.items() if v is not None}
    raise AppInstanceError("credentials must be a dict or string")


def verify_stack_commit(stack_commit: str | None, health_commit: str | None, *, base_url: str = "") -> str:
    """Assert stack_up_ref's commit matches GET {base_url}/api/health's commit; fail loud naming both if not."""
    hc = str(health_commit or "").strip()
    if not hc or not COMMIT_RE.match(hc):
        raise AppInstanceError(f"health response is missing a valid commit for {base_url or 'instance'}: {hc!r}")
    sc = str(stack_commit or "").strip()
    if not sc:
        return hc
    if not COMMIT_RE.match(sc):
        raise AppInstanceError(
            f"stack_up_ref commit {sc!r} is not a valid commit SHA (health commit={hc!r}, base_url={base_url})"
        )
    if sc.lower() != hc.lower():
        raise AppInstanceError(
            f"commit mismatch for {base_url or 'instance'}: "
            f"stack_up_ref commit {sc!r} != health commit {hc!r}"
        )
    return hc


def parse_bool(value: Any) -> bool:
    """Parse a workflow boolean input from bool, int, or string ('true', '1', 'yes')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


def _extract_github_repo_from_git_dir(repo_dir: Path) -> str | None:
    """Read <repo>/.git/config (or worktree gitdir config) without invoking git subprocess."""
    git_entry = repo_dir / ".git"
    config_candidates: list[Path] = []
    if git_entry.is_dir():
        config_candidates.append(git_entry / "config")
    elif git_entry.is_file():
        try:
            first = git_entry.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            first = ""
        if first.startswith("gitdir:"):
            raw_gitdir = first.split(":", 1)[1].strip()
            gitdir = Path(raw_gitdir) if Path(raw_gitdir).is_absolute() else (repo_dir / raw_gitdir).resolve()
            config_candidates.append(gitdir / "config")
            if gitdir.parent.name == "worktrees":
                config_candidates.append(gitdir.parent.parent / "config")
    for cfg in config_candidates:
        if not cfg.is_file():
            continue
        try:
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if stripped.startswith("url") and "=" in stripped:
                    rhs = stripped.split("=", 1)[1].strip()
                    m = GITHUB_REMOTE_RE.search(rhs)
                    if m:
                        return m.group(1)
        except OSError:
            continue
    return None


def resolve_github_repo(product: str, repo_path: str | Path | None = None) -> str:
    """Resolve the GitHub '<owner>/<name>' slug for `product` without invoking git."""
    env_override = os.environ.get("APP_SCREEN_GITHUB_REPO", "").strip()
    if env_override and "/" in env_override:
        return env_override
    prod = str(product or "rollcall").strip() or "rollcall"
    if "/" in prod and not Path(prod).exists():
        return prod
    candidates: list[Path] = []
    if repo_path is not None:
        candidates.append(Path(repo_path).expanduser())
    try:
        reg = product_app.registry()
        mapped = (reg.get("repos") or {}).get(prod)
        if mapped:
            candidates.append(Path(str(mapped)).expanduser())
    except Exception:
        pass
    candidates.append(Path.home() / prod)
    for cand in candidates:
        slug = _extract_github_repo_from_git_dir(cand)
        if slug:
            return slug
    return f"shine2lay/{prod}"


def _github_token_from_env() -> str:
    """Locate a GitHub token from env or sibling PID 1 environ in temper-ai-worker without printing it."""
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "TEMPER_GITHUB_TOKEN", "GITHUB_TOKEN_DESIGN"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    proc_root = Path("/proc")
    if proc_root.is_dir():
        for entry in sorted(proc_root.iterdir()):
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "environ").read_bytes()
            except OSError:
                continue
            for item in raw.split(b"\0"):
                for prefix in (b"GH_TOKEN=", b"GITHUB_TOKEN=", b"TEMPER_GITHUB_TOKEN="):
                    if item.startswith(prefix):
                        tok = item[len(prefix):].decode("utf-8", errors="ignore").strip()
                        if tok:
                            return tok
    return ""


def _find_gh_binary() -> str:
    found = shutil.which("gh")
    if found:
        return found
    for cand in GH_CANDIDATES:
        if Path(cand).is_file() and os.access(cand, os.X_OK):
            return cand
    raise AppInstanceError("gh CLI binary not found on PATH or /home/shinelay/.local/bin/gh")


def _github_api_fallback(cmd: list[str], tok: str) -> subprocess.CompletedProcess[str]:
    """Fallback for containers where the `gh` binary is not installed but TEMPER_GITHUB_TOKEN is set."""
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "temper-ai",
    }
    try:
        if len(cmd) >= 3 and cmd[1] == "api" and "/commits/" in cmd[2]:
            endpoint = cmd[2].lstrip("/")
            req = urllib.request.Request(f"https://api.github.com/{endpoint}", headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            sha = str(data.get("sha") or "").strip()
            return subprocess.CompletedProcess(cmd, 0, f"{sha}\n" if sha else "", "")
        if len(cmd) >= 3 and cmd[1] == "run" and cmd[2] == "list":
            repo = ""
            commit = ""
            for idx, part in enumerate(cmd):
                if part == "--repo" and idx + 1 < len(cmd):
                    repo = cmd[idx + 1]
                elif part == "--commit" and idx + 1 < len(cmd):
                    commit = cmd[idx + 1]
            url = f"https://api.github.com/repos/{repo}/actions/runs?head_sha={commit}&per_page=30"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            runs = [
                {
                    "headSha": r.get("head_sha"),
                    "conclusion": r.get("conclusion"),
                    "status": r.get("status"),
                    "name": r.get("display_title") or r.get("name"),
                    "workflowName": r.get("name"),
                    "databaseId": r.get("id"),
                }
                for r in (data.get("workflow_runs") or [])
                if isinstance(r, dict)
            ]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(runs), "")
    except Exception as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))
    return subprocess.CompletedProcess(cmd, 1, "", f"unsupported gh command without gh binary: {cmd!r}")


def _default_gh_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    tok = _github_token_from_env()
    try:
        gh_bin = _find_gh_binary()
    except AppInstanceError:
        if tok:
            return _github_api_fallback(cmd, tok)
        raise
    actual_cmd = [gh_bin, *cmd[1:]] if cmd and cmd[0] == "gh" else list(cmd)
    env = dict(os.environ)
    if tok and not env.get("GH_TOKEN") and not env.get("GITHUB_TOKEN"):
        env["GH_TOKEN"] = tok
    return subprocess.run(
        actual_cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


GH_RUNNER: Any = _default_gh_runner


def _invoke_gh(runner: Any, cmd: list[str], *, commit: str, repo: str, secrets_list: list[str]) -> tuple[int, str, str]:
    try:
        res = runner(cmd)
    except AppInstanceError:
        raise
    except Exception as exc:
        clean = _scrub(str(exc), secrets_list)
        raise AppInstanceError(f"gh command failed for commit {commit} in {repo}: {clean}") from None

    if isinstance(res, subprocess.CompletedProcess):
        return (
            int(res.returncode),
            _scrub(res.stdout or "", secrets_list),
            _scrub(res.stderr or "", secrets_list),
        )
    if isinstance(res, tuple):
        if len(res) == 3:
            rc, out, err = res
            return int(rc), _scrub(str(out or ""), secrets_list), _scrub(str(err or ""), secrets_list)
        if len(res) == 2:
            rc, out = res
            return int(rc), _scrub(str(out or ""), secrets_list), ""
    if isinstance(res, (list, dict)):
        return 0, json.dumps(res), ""
    if isinstance(res, str):
        return 0, _scrub(res, secrets_list), ""
    raise AppInstanceError(f"unexpected gh runner return type {type(res).__name__} for commit {commit} in {repo}")


def verify_commit_ci_status(
    commit: str | None,
    *,
    product: str = "rollcall",
    github_repo: str | None = None,
    allow_red_commit: bool | str = False,
    runner: Any = None,
) -> dict[str, Any]:
    """Deterministic GitHub CI check for `commit` via `gh` CLI.

    Resolves the 40-char commit SHA, queries `gh run list --repo <owner/name> --commit <sha>
    --json headSha,conclusion,status,name,workflowName,databaseId`, and fails loud naming the
    commit and failing check unless `conclusion == 'success'` or `allow_red_commit` is True.
    Treats 'no CI run found' and 'in progress' as not-green, and never fails open on a `gh` error.
    """
    raw_commit = str(commit or "").strip()
    if not raw_commit or not COMMIT_RE.match(raw_commit):
        raise AppInstanceError(f"CI status check requires a valid commit SHA (got {commit!r})")

    allow_red = parse_bool(allow_red_commit)
    repo = (github_repo or resolve_github_repo(product)).strip()
    eff_runner = runner if runner is not None else GH_RUNNER
    tok = _github_token_from_env()
    secrets_list = [tok] if tok else []

    full_commit = raw_commit.lower()
    prefetched_runs: list[dict[str, Any]] | None = None
    if len(full_commit) < 40:
        rc, out, err = _invoke_gh(
            eff_runner,
            ["gh", "api", f"repos/{repo}/commits/{full_commit}", "--jq", ".sha"],
            commit=full_commit,
            repo=repo,
            secrets_list=secrets_list,
        )
        if rc != 0:
            detail = (err or out).strip()[:300] or f"exit {rc}"
            raise AppInstanceError(
                f"gh failed to resolve 40-char commit SHA for {raw_commit!r} in {repo}: {detail}"
            )
        candidate = out.strip()
        if FULL_COMMIT_RE.match(candidate):
            full_commit = candidate.lower()
        elif candidate.startswith("["):
            try:
                parsed = json.loads(candidate)
            except ValueError as exc:
                raise AppInstanceError(
                    f"gh returned invalid JSON resolving commit {raw_commit!r} in {repo}: {exc}"
                ) from None
            if isinstance(parsed, list):
                prefetched_runs = [r for r in parsed if isinstance(r, dict)]
                for r in prefetched_runs:
                    h = str(r.get("headSha") or "").strip().lower()
                    if FULL_COMMIT_RE.match(h) and h.startswith(full_commit):
                        full_commit = h
                        break
        else:
            raise AppInstanceError(
                f"gh did not return a 40-char commit SHA for {raw_commit!r} in {repo}: {candidate[:120]!r}"
            )

    if prefetched_runs is None:
        rc, out, err = _invoke_gh(
            eff_runner,
            [
                "gh",
                "run",
                "list",
                "--repo",
                repo,
                "--commit",
                full_commit,
                "--json",
                "headSha,conclusion,status,name,workflowName,databaseId",
            ],
            commit=full_commit,
            repo=repo,
            secrets_list=secrets_list,
        )
        if rc != 0:
            detail = (err or out).strip()[:300] or f"exit {rc}"
            raise AppInstanceError(f"gh run list failed for commit {full_commit} in {repo}: {detail}")
        try:
            runs_raw = json.loads(out or "")
        except ValueError as exc:
            raise AppInstanceError(
                f"gh run list returned invalid JSON for commit {full_commit} in {repo}: {exc}"
            ) from None
        if not isinstance(runs_raw, list) or any(not isinstance(item, dict) for item in runs_raw):
            raise AppInstanceError(
                f"gh run list must return a JSON list of objects for commit {full_commit} in {repo}"
            )
        prefetched_runs = runs_raw

    matching_runs: list[dict[str, Any]] = []
    for item in prefetched_runs:
        head_sha = str(item.get("headSha") or "").strip().lower()
        if not head_sha or head_sha == full_commit or head_sha.startswith(raw_commit.lower()) or full_commit.startswith(head_sha):
            matching_runs.append(item)

    def _run_check_name(run_obj: dict[str, Any]) -> str:
        for key in ("failingCheck", "checkName", "jobName"):
            val = str(run_obj.get(key) or "").strip()
            if val:
                return val
        jobs = run_obj.get("jobs")
        if isinstance(jobs, list):
            for job in jobs:
                if isinstance(job, dict):
                    j_conc = str(job.get("conclusion") or "").strip().lower()
                    j_stat = str(job.get("status") or "completed").strip().lower()
                    if j_stat != "completed" or j_conc not in ("success", "skipped", "neutral", ""):
                        j_name = str(job.get("name") or "").strip()
                        if j_name:
                            return j_name
        db_id = run_obj.get("databaseId")
        if db_id:
            try:
                v_rc, v_out, _ = _invoke_gh(
                    eff_runner,
                    ["gh", "run", "view", str(db_id), "--repo", repo, "--json", "jobs"],
                    commit=full_commit,
                    repo=repo,
                    secrets_list=secrets_list,
                )
                if v_rc == 0 and (v_out or "").strip().startswith("{"):
                    v_doc = json.loads(v_out)
                    for job in v_doc.get("jobs") or []:
                        if isinstance(job, dict):
                            j_conc = str(job.get("conclusion") or "").strip().lower()
                            if j_conc and j_conc not in ("success", "skipped", "neutral"):
                                j_name = str(job.get("name") or "").strip()
                                if j_name:
                                    return j_name
            except Exception:
                pass
        return str(run_obj.get("name") or run_obj.get("workflowName") or "ci").strip() or "ci"

    if not matching_runs:
        ci_conclusion = "no_ci_run"
        failing_check: str | None = "no CI run found"
        if not allow_red:
            raise AppInstanceError(
                f"CI check failed for commit {full_commit} in {repo}: no CI run found "
                f"(pass allow_red_commit=true to proceed)"
            )
    else:
        failed_runs = [
            r
            for r in matching_runs
            if str(r.get("status") or "completed").strip().lower() == "completed"
            and str(r.get("conclusion") or "").strip().lower() not in ("", "success", "skipped", "neutral")
        ]
        in_progress_runs = [
            r
            for r in matching_runs
            if str(r.get("status") or "completed").strip().lower() != "completed"
            or not str(r.get("conclusion") or "").strip()
        ]
        success_runs = [
            r
            for r in matching_runs
            if str(r.get("status") or "completed").strip().lower() == "completed"
            and str(r.get("conclusion") or "").strip().lower() == "success"
        ]

        if failed_runs:
            bad = failed_runs[0]
            ci_conclusion = str(bad.get("conclusion") or "failure").strip().lower()
            failing_check = _run_check_name(bad)
            if not allow_red:
                raise AppInstanceError(
                    f"CI check failed for commit {full_commit} in {repo}: "
                    f"conclusion={ci_conclusion!r} on failing check {failing_check!r} "
                    f"(pass allow_red_commit=true to proceed)"
                )
        elif in_progress_runs:
            pending = in_progress_runs[0]
            ci_conclusion = "in_progress"
            failing_check = _run_check_name(pending)
            if not allow_red:
                raise AppInstanceError(
                    f"CI check failed for commit {full_commit} in {repo}: "
                    f"check {failing_check!r} is in progress (status={pending.get('status')!r}; "
                    f"pass allow_red_commit=true to proceed)"
                )
        elif not success_runs:
            first = matching_runs[0]
            ci_conclusion = str(first.get("conclusion") or "no_ci_run").strip().lower()
            failing_check = _run_check_name(first)
            if not allow_red:
                raise AppInstanceError(
                    f"CI check failed for commit {full_commit} in {repo}: "
                    f"conclusion={ci_conclusion!r} on check {failing_check!r} "
                    f"(pass allow_red_commit=true to proceed)"
                )
        else:
            ci_conclusion = "success"
            failing_check = None

    return {
        "commit": full_commit,
        "short_commit": full_commit[:12],
        "ci_conclusion": ci_conclusion,
        "allow_red_commit": allow_red,
        "ci_failing_check": failing_check,
        "repo": repo,
    }


def _resolve_gateway_ip(hostname: str, timeout: float = 5.0) -> str | None:
    """Resolve hostname via DoH or sibling gateway host when container DNS lacks a new wildcard record."""
    host = (hostname or "").strip().lower()
    if not host or not host.endswith(".wai2shine.com"):
        return None
    try:
        doh_url = f"https://1.1.1.1/dns-query?name={urllib.parse.quote(host)}&type=A"
        req = urllib.request.Request(doh_url, headers={"Accept": "application/dns-json"}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8", errors="replace"))
        for ans in doc.get("Answer") or []:
            if ans.get("type") == 1 and ans.get("data"):
                return str(ans["data"]).strip()
    except Exception:
        pass
    for fallback_host in ("temper-dev.wai2shine.com", "rollcall.wai2shine.com"):
        try:
            ip = socket.gethostbyname(fallback_host)
            if ip:
                return ip
        except OSError:
            continue
    return None


def _request_via_ip(
    url: str,
    ip: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 15.0,
) -> tuple[int, list[tuple[str, str]], bytes]:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    req_headers = dict(headers or {})
    req_headers["Host"] = host if not parsed.port else f"{host}:{parsed.port}"
    req_headers.setdefault("Accept-Encoding", "identity")
    sock = socket.create_connection((ip, port), timeout=timeout)
    if parsed.scheme == "https":
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=host)
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.sock = sock
    try:
        conn.request(method, path, body=body, headers=req_headers)
        resp = conn.getresponse()
        data = resp.read()
        return int(resp.status), list(resp.getheaders()), data
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _read_health_url(url: str, base: str, opener: Any = None, timeout: float = 15.0) -> str:
    if opener is None:
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                if status and int(status) >= 400:
                    raise AppInstanceError(f"GET {url} returned HTTP {status} (base_url={base})")
                return resp.read().decode("utf-8", errors="replace")
        except AppInstanceError:
            raise
        except urllib.error.HTTPError as exc:
            raise AppInstanceError(f"GET {url} returned HTTP {exc.code} (base_url={base})") from None
        except Exception as exc:
            parsed = urllib.parse.urlsplit(url)
            gw_ip = _resolve_gateway_ip(parsed.hostname or "", timeout=min(timeout, 5.0))
            if gw_ip:
                try:
                    status, _, raw_bytes = _request_via_ip(
                        url, gw_ip, method="GET", headers={"Accept": "application/json"}, timeout=timeout
                    )
                    if status >= 400:
                        raise AppInstanceError(f"GET {url} returned HTTP {status} (base_url={base})")
                    return raw_bytes.decode("utf-8", errors="replace")
                except AppInstanceError:
                    raise
                except Exception as inner_exc:
                    raise AppInstanceError(f"GET {url} is unreachable for base_url {base}: {inner_exc}") from None
            raise AppInstanceError(f"GET {url} is unreachable for base_url {base}: {exc}") from None

    try:
        try:
            res = opener(url, timeout)
        except TypeError:
            req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
            res = opener(req, timeout=timeout)
    except AppInstanceError:
        raise
    except urllib.error.HTTPError as exc:
        raise AppInstanceError(f"GET {url} returned HTTP {exc.code} (base_url={base})") from None
    except Exception as exc:
        raise AppInstanceError(f"GET {url} is unreachable for base_url {base}: {exc}") from None

    if isinstance(res, tuple) and len(res) == 2:
        status, body = res
        if int(status) >= 400:
            raise AppInstanceError(f"GET {url} returned HTTP {status} (base_url={base})")
        return body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
    if hasattr(res, "__enter__"):
        with res as resp:
            raw = resp.read() if hasattr(resp, "read") else resp
            return raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    if hasattr(res, "read"):
        raw = res.read()
        return raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    if isinstance(res, (bytes, bytearray)):
        return res.decode("utf-8", errors="replace")
    if isinstance(res, dict):
        return json.dumps(res)
    return str(res)


def fetch_health(base_url: str, *, version: str | None = None,
                 stack_commit: str | None = None,
                 opener: Any = None, timeout: float = 15.0) -> dict[str, Any]:
    """Fetch GET {base_url}/api/health -> {base_url, health_url, commit, version, ok}."""
    base = validate_base_url(base_url)
    url = f"{base}/api/health"
    body = _read_health_url(url, base, opener=opener, timeout=timeout)
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise AppInstanceError(f"{url} returned invalid JSON for base_url {base}: {exc}") from None
    if not isinstance(data, dict):
        raise AppInstanceError(f"{url} must return a JSON object for base_url {base}")
    if "ok" in data and data.get("ok") is not True:
        raise AppInstanceError(f"{url} reported ok={data.get('ok')!r} (expected ok=True for base_url {base})")
    commit = str(data.get("commit") or "").strip()
    if not commit or not COMMIT_RE.match(commit):
        raise AppInstanceError(f"{url} response is missing a valid 'commit' field (base_url={base})")
    verify_stack_commit(stack_commit, commit, base_url=base)
    resolved_version = str(version or data.get("version") or "").strip() or commit[:7]
    return {
        "base_url": base,
        "health_url": url,
        "commit": commit,
        "version": resolved_version,
        "ok": True,
    }


read_health = fetch_health


def resolve_screen_target(app: dict[str, Any], screen_id: str, state_name: str) -> dict[str, Any]:
    """Return the navigation recipe for 'go to screen S in state T'."""
    for item in product_app.captures(app):
        if item["screen"] == screen_id and item["state"] == state_name:
            return {
                "screen": screen_id,
                "state": state_name,
                "account": item.get("account"),
                "steps": item["steps"],
                "wait_for": item["wait_for"],
            }
    raise AppInstanceError(f"unknown screen/state ({screen_id!r}, {state_name!r}) in {app.get('product', 'app')}")


class AppInstance:
    """A reachable, health-checked product instance at base_url."""

    def __init__(self, first: dict[str, Any] | str,
                 second: dict[str, str] | str | None = None,
                 third: dict[str, str] | str | None = None,
                 *,
                 app: dict[str, Any] | None = None,
                 base_url: str | None = None,
                 credentials: dict[str, str] | str | None = None,
                 version: str | None = None,
                 stack_commit: str | None = None,
                 opener: Any = None,
                 health_opener: Any = None,
                 timeout: float = 15.0) -> None:
        if isinstance(first, dict):
            resolved_app = first
            resolved_url = str(second or base_url or "")
            resolved_creds = third if third is not None else credentials
        else:
            resolved_url = str(first or base_url or "")
            resolved_creds = second if second is not None else credentials
            resolved_app = app or {}
        self.app = resolved_app
        self.base_url = validate_base_url(resolved_url)
        self._credentials = normalize_credentials(resolved_creds)
        self._opener = health_opener or opener
        self._version_override = version
        self._stack_commit = (stack_commit or os.environ.get("APP_SCREEN_STACK_COMMIT") or "").strip() or None
        self._timeout = timeout
        self._health: dict[str, Any] | None = None
        if self._opener is not None:
            self._health = fetch_health(
                self.base_url,
                version=version,
                stack_commit=self._stack_commit,
                opener=self._opener,
                timeout=timeout,
            )

    def read_health(self) -> dict[str, Any]:
        if self._health is None:
            self._health = fetch_health(
                self.base_url,
                version=self._version_override,
                stack_commit=self._stack_commit,
                opener=self._opener,
                timeout=self._timeout,
            )
        elif self._stack_commit:
            verify_stack_commit(self._stack_commit, self._health.get("commit"), base_url=self.base_url)
        return self._health

    @property
    def health(self) -> dict[str, Any]:
        return self.read_health()

    @property
    def commit(self) -> str:
        return self.read_health()["commit"]

    @property
    def version(self) -> str:
        return self.read_health()["version"]

    def _secrets(self) -> list[str]:
        return [v for v in self._credentials.values() if v]

    def password_for(self, account: str) -> str:
        acct = str(account or "").strip()
        if not acct:
            raise AppInstanceError("account name is empty")
        short = acct.split("@", 1)[0]
        for key in (acct, short, "*", "default", "password"):
            if key in self._credentials and self._credentials[key]:
                return self._credentials[key]
        raise AppInstanceError(
            f"missing password for account {acct!r} on {self.base_url} "
            f"(supply credentials for {acct!r} or 'default')"
        )

    def validate_accounts(self, caps: list[dict[str, Any]] | None = None) -> dict[str, str]:
        if not self.app.get("login"):
            return {}
        items = caps if caps is not None else product_app.captures(self.app)
        resolved: dict[str, str] = {}
        for c in items:
            acct = c.get("account")
            if acct and acct not in resolved:
                resolved[acct] = self.password_for(acct)
        return resolved

    def login_spec(self) -> dict[str, Any] | None:
        lg = self.app.get("login")
        if not lg:
            return None
        user_sel = lg.get("email_field") or lg.get("user_field") or lg.get("user_selector")
        pwd_sel = lg.get("password_field") or lg.get("password_selector")
        fields = dict(lg.get("fields") or {})
        return {
            "path": lg["path"],
            "fields": fields,
            "user_selector": user_sel,
            "password_selector": pwd_sel,
            "submit": lg["submit"],
            "wait_for": lg["wait_for"],
        }

    def login_account(self, browser: Any, account: str) -> Any:
        """Log into `account` in a new browser context and return that context.

        On any error, raises AppInstanceError naming `account` and `base_url`, never the password.
        """
        pwd = self.password_for(account)
        lg = self.login_spec()
        if not lg:
            return browser.new_context()
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(f"{self.base_url}{lg['path']}", wait_until="domcontentloaded", timeout=20000)
            for sel, tmpl in (lg.get("fields") or {}).items():
                s = str(tmpl)
                filled = account if ("{account}@" in s and "@" in account) else s.replace("{account}", account)
                page.fill(sel, filled)
            user_sel = lg.get("user_selector")
            if user_sel and user_sel not in (lg.get("fields") or {}):
                val = account if ("@" in account or lg.get("fields")) else f"{account}@rollcall.test"
                page.fill(user_sel, val)
            if lg.get("password_selector"):
                page.fill(lg["password_selector"], pwd)
            page.click(lg["submit"])
            page.wait_for_selector(lg["wait_for"], timeout=20000)
            return ctx
        except Exception as exc:
            try:
                ctx.close()
            except Exception:
                pass
            clean = _scrub(str(exc), self._secrets())
            raise AppInstanceError(
                f"login failed for account {account!r} on {self.base_url}: {clean}"
            ) from None

    def go_to_screen(self, page: Any, screen_id: str, state_name: str) -> dict[str, Any]:
        """Drive a Playwright page to screen `screen_id` in state `state_name`."""
        target = resolve_screen_target(self.app, screen_id, state_name)
        try:
            for step in target["steps"]:
                if "goto" in step:
                    page.goto(f"{self.base_url}{step['goto']}", wait_until="domcontentloaded", timeout=20000)
                elif "click" in step:
                    page.click(step["click"], timeout=10000)
                elif "fill" in step:
                    page.fill(step["fill"]["selector"], step["fill"]["value"], timeout=10000)
                elif "wait_for" in step:
                    page.wait_for_selector(step["wait_for"], timeout=15000)
                elif "wait_ms" in step:
                    page.wait_for_timeout(step["wait_ms"])
            page.wait_for_selector(target["wait_for"], timeout=15000)
            return target
        except Exception as exc:
            clean = _scrub(str(exc), self._secrets())
            raise AppInstanceError(
                f"navigation failed for screen {screen_id!r} state {state_name!r} on {self.base_url}: {clean}"
            ) from None

    def plan(self, caps: list[dict[str, Any]], out_dir: Path, state_dir: Path) -> dict[str, Any]:
        """Build the Playwright capture plan without embedding any password."""
        self.validate_accounts(caps)
        page_spec = dict(self.app["page"])
        if "key_regions" not in page_spec and "areas" in page_spec:
            page_spec["key_regions"] = dict(page_spec["areas"])
        plan: dict[str, Any] = {
            "base_url": self.base_url,
            "commit": self.commit,
            "version": self.version,
            "out_dir": str(out_dir),
            "state_dir": str(state_dir),
            "measure_script": str(MEASURE_JS),
            "measure_js": str(MEASURE_JS),
            "page": page_spec,
            "captures": caps,
        }
        lg = self.login_spec()
        if lg:
            plan["login"] = lg
        return plan

    def shoot(self, caps: list[dict[str, Any]], out_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
        """Run existing_capture.mjs against this instance and return (raw_measures, failed_by_id)."""
        creds = self.validate_accounts(caps)
        secrets = self._secrets()
        out_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="app-screen-instance-") as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / "states"
            state_dir.mkdir(parents=True, exist_ok=True)
            plan_doc = self.plan(caps, out_dir, state_dir)
            plan_file = tmp_path / "plan.json"
            plan_file.write_text(json.dumps(plan_doc, indent=2) + "\n", encoding="utf-8")

            if CAPTURE_JS == HERE / "existing_capture.mjs" and not _local_node_playwright_available():
                return self._shoot_via_mcp(plan_doc, creds, out_dir)

            env = dict(os.environ)
            creds_json = json.dumps(creds)
            env["APP_SCREEN_CREDENTIALS"] = creds_json
            env["APP_SCREEN_CREDENTIALS_JSON"] = creds_json
            proc = subprocess.run(
                ["node", str(CAPTURE_JS), str(plan_file)],
                capture_output=True,
                text=True,
                env=env,
                timeout=600,
                check=False,
            )
            if proc.returncode != 0:
                msg = _scrub((proc.stderr or proc.stdout or "")[-1200:], secrets)
                raise AppInstanceError(
                    f"existing_capture.mjs exited {proc.returncode} against {self.base_url}: {msg}"
                )
            failed: dict[str, str] = {}
            stdout_clean = _scrub((proc.stdout or "").strip(), secrets)
            if stdout_clean.startswith("{"):
                try:
                    summary = json.loads(stdout_clean)
                except ValueError:
                    summary = {}
                failed_raw = summary.get("failed") or {}
                if isinstance(failed_raw, dict):
                    for cid, why in failed_raw.items():
                        failed[str(cid)] = _scrub(str(why), secrets)
                elif isinstance(failed_raw, list):
                    for item in failed_raw:
                        if isinstance(item, dict):
                            cid = str(item.get("id") or item.get("account") or "unknown")
                            why = _scrub(str(item.get("error") or item.get("reason") or "failed"), secrets)
                            if cid.startswith("login:"):
                                acct = cid.split(":", 1)[1]
                                raise AppInstanceError(f"login failed for account {acct!r} on {self.base_url}: {why}")
                            failed[cid] = why

            for cid, why in list(failed.items()):
                if cid.startswith("login:"):
                    acct = cid.split(":", 1)[1]
                    raise AppInstanceError(f"login failed for account {acct!r} on {self.base_url}: {why}")

            raw_path = out_dir / "raw.json"
            if not raw_path.is_file():
                raise AppInstanceError(f"existing_capture.mjs did not write {raw_path}")
            raw_data = json.loads(_scrub(raw_path.read_text(encoding="utf-8"), secrets))
            for cid, entry in raw_data.items():
                if isinstance(entry, dict) and entry.get("failed"):
                    failed.setdefault(str(cid), _scrub(str(entry["failed"]), secrets))
            return raw_data, failed

    def _shoot_via_mcp(
        self,
        plan_doc: dict[str, Any],
        creds: dict[str, str],
        out_dir: Path,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Capture via playwright-mcp when running inside a Temper worker/stage container."""
        from . import checks_render

        secrets_list = self._secrets()
        measure_src = Path(plan_doc.get("measure_script") or MEASURE_JS).read_text(encoding="utf-8")
        token = secrets.token_hex(16)
        parsed_base = urllib.parse.urlsplit(self.base_url)
        base_host = parsed_base.hostname or ""
        gw_ip = _resolve_gateway_ip(base_host)
        account_cookies: dict[str, dict[str, str]] = {}
        raw_holder: dict[str, Any] = {}
        lock = threading.Lock()

        class _ProxyHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                return

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length) if length > 0 else b""

            def _handle_all(self, method: str) -> None:
                body = self._read_body()
                if self.path == f"/__app_screen_creds__/{token}":
                    payload = json.dumps(creds).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if self.path.startswith(f"/__app_screen_png__/{token}/"):
                    cid = urllib.parse.unquote(self.path.split(f"/__app_screen_png__/{token}/", 1)[1])
                    if "/" not in cid and ".." not in cid:
                        (out_dir / f"{cid}.png").write_bytes(body)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                    return
                if self.path == f"/__app_screen_raw__/{token}":
                    with lock:
                        raw_holder["raw"] = body.decode("utf-8", errors="replace")
                    (out_dir / "raw.json").write_bytes(body)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                    return

                acct = (self.headers.get("X-App-Screen-Account") or "").strip()
                fwd_headers: dict[str, str] = {}
                for k, v in self.headers.items():
                    kl = k.lower()
                    if kl in ("host", "content-length", "connection", "accept-encoding", "x-app-screen-account"):
                        continue
                    fwd_headers[k] = v
                if acct:
                    with lock:
                        jar = dict(account_cookies.get(acct) or {})
                    if jar:
                        existing_cookie = fwd_headers.get("Cookie") or fwd_headers.get("cookie") or ""
                        jar_str = "; ".join(f"{ck}={cv}" for ck, cv in jar.items())
                        fwd_headers["Cookie"] = f"{existing_cookie}; {jar_str}".strip("; ") if existing_cookie else jar_str

                target_url = f"{plan_doc['base_url']}{self.path}"
                try:
                    if gw_ip:
                        status, resp_headers, resp_body = _request_via_ip(
                            target_url, gw_ip, method=method, headers=fwd_headers, body=body if body else None, timeout=30.0
                        )
                    else:
                        req = urllib.request.Request(
                            target_url, data=body if body else None, headers=fwd_headers, method=method
                        )
                        with urllib.request.urlopen(req, timeout=30.0) as resp:
                            status = int(getattr(resp, "status", 200))
                            resp_headers = list(resp.headers.items())
                            resp_body = resp.read()
                except urllib.error.HTTPError as exc:
                    status = int(exc.code)
                    resp_headers = list(exc.headers.items()) if exc.headers else []
                    resp_body = exc.read() if hasattr(exc, "read") else b""
                except Exception as exc:
                    err_bytes = str(exc).encode("utf-8", errors="replace")
                    self.send_response(502)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(err_bytes)))
                    self.end_headers()
                    self.wfile.write(err_bytes)
                    return

                if acct:
                    for hk, hv in resp_headers:
                        if hk.lower() == "set-cookie":
                            sc = http.cookies.SimpleCookie()
                            try:
                                sc.load(hv)
                                with lock:
                                    bucket = account_cookies.setdefault(acct, {})
                                    for morsel_key, morsel in sc.items():
                                        bucket[morsel_key] = morsel.value
                            except Exception:
                                pass

                self.send_response(status)
                for hk, hv in resp_headers:
                    if hk.lower() in ("transfer-encoding", "content-encoding", "content-length", "connection"):
                        continue
                    self.send_header(hk, hv)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            def do_GET(self) -> None:
                self._handle_all("GET")

            def do_POST(self) -> None:
                self._handle_all("POST")

            def do_PUT(self) -> None:
                self._handle_all("PUT")

            def do_DELETE(self) -> None:
                self._handle_all("DELETE")

            def do_PATCH(self) -> None:
                self._handle_all("PATCH")

        server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), _ProxyHandler)
        port = server.server_address[1]
        proxy_host = _local_container_ip()
        proxy_url = f"http://{proxy_host}:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            js_code = _build_mcp_capture_js(plan_doc, measure_src, proxy_url, token)
            res = _run_mcp_js(checks_render, js_code)
        except Exception as exc:
            clean = _scrub(str(exc), secrets_list)
            raise AppInstanceError(f"playwright-mcp capture failed against {self.base_url}: {clean}") from None
        finally:
            server.shutdown()
            server.server_close()

        failed: dict[str, str] = {}
        if isinstance(res, dict):
            failed_raw = res.get("failed") or {}
            if isinstance(failed_raw, dict):
                for cid, why in failed_raw.items():
                    w = _scrub(str(why), secrets_list)
                    if str(cid).startswith("login:"):
                        acct = str(cid).split(":", 1)[1]
                        raise AppInstanceError(f"login failed for account {acct!r} on {self.base_url}: {w}")
                    failed[str(cid)] = w

        raw_path = out_dir / "raw.json"
        if not raw_path.is_file():
            raise AppInstanceError(f"playwright-mcp capture did not write {raw_path}")
        raw_data = json.loads(_scrub(raw_path.read_text(encoding="utf-8"), secrets_list))
        for cid, entry in raw_data.items():
            if isinstance(entry, dict) and entry.get("failed"):
                failed.setdefault(str(cid), _scrub(str(entry["failed"]), secrets_list))
        return raw_data, failed


def _local_node_playwright_available() -> bool:
    try:
        proc = subprocess.run(
            ["node", "-e", "import('playwright').then(()=>process.exit(0)).catch(()=>process.exit(1))"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _local_container_ip() -> str:
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _format_exc(exc: BaseException) -> str:
    sub = getattr(exc, "exceptions", None)
    if sub:
        return "; ".join(_format_exc(item) for item in sub)
    return str(exc)


def _run_mcp_js(checks_render_mod: Any, js_code: str) -> Any:
    import asyncio  # noqa: PLC0415

    browser_url = os.environ.get("CHECKS_BROWSER") or checks_render_mod.BROWSER
    dc = checks_render_mod._design_capture()
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.streamable_http import streamablehttp_client  # noqa: PLC0415

    async def _go() -> Any:
        async with streamablehttp_client(browser_url) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                out = await dc.run(s, js_code)
                await s.call_tool("browser_close", {})
                return out

    try:
        return asyncio.run(_go())
    except BaseException as exc:
        if isinstance(exc, Exception) and not hasattr(exc, "exceptions"):
            raise
        raise RuntimeError(_format_exc(exc)) from None


def _build_mcp_capture_js(plan_doc: dict[str, Any], measure_src: str, proxy_url: str, token: str) -> str:
    parsed = urllib.parse.urlsplit(str(plan_doc.get("base_url") or ""))
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    return (
        "async (rootPage) => {\n"
        f"  const plan = {json.dumps(plan_doc)};\n"
        f"  const measureSrc = {json.dumps(measure_src)};\n"
        f"  const proxyUrl = {json.dumps(proxy_url)};\n"
        f"  const token = {json.dumps(token)};\n"
        f"  const baseOrigin = {json.dumps(base_origin)};\n"
        "  const BASE = String(plan.base_url || '').replace(/\\/$/, '');\n"
        "  const PAGE = plan.page || {};\n"
        "  const NEVER_SRC = 'send|place|confirm|submit|delete|cancel order';\n"
        "  const browser = rootPage.context().browser();\n"
        "  const credResp = await rootPage.context().request.fetch(`${proxyUrl}/__app_screen_creds__/${token}`);\n"
        "  const creds = await credResp.json();\n"
        "  const states = {};\n"
        "  const raw = {};\n"
        "  const failed = {};\n"
        "  const matchDelay = (rel, delay) => {\n"
        "    if (!delay) return false;\n"
        "    if (typeof delay === 'string') return rel.includes(delay);\n"
        "    if (delay.except && rel.includes(delay.except)) return false;\n"
        "    const m = String(delay.match || '/api/');\n"
        "    const needle = m.replace(/^\\*+/, '').replace(/\\*+$/, '') || '/api/';\n"
        "    return rel.includes(needle);\n"
        "  };\n"
        "  const attachProxy = async (ctx, pageForWait, account, delay) => {\n"
        "    await ctx.route(`${baseOrigin}/**`, async (route) => {\n"
        "      const req = route.request();\n"
        "      const rawUrl = req.url();\n"
        "      const withoutOrigin = rawUrl.startsWith(baseOrigin) ? rawUrl.slice(baseOrigin.length) : rawUrl.replace(/^https?:\\/\\/[^/]+/, '');\n"
        "      const hashIdx = withoutOrigin.indexOf('#');\n"
        "      const rel = (hashIdx >= 0 ? withoutOrigin.slice(0, hashIdx) : withoutOrigin) || '/';\n"
        "      if (matchDelay(rel, delay)) {\n"
        "        const ms = (typeof delay === 'object' && delay.delay_ms) ? delay.delay_ms : 8000;\n"
        "        try { await pageForWait.waitForTimeout(ms); } catch (_e) { return; }\n"
        "      }\n"
        "      const headers = Object.assign({}, await req.allHeaders());\n"
        "      delete headers['host'];\n"
        "      delete headers['content-length'];\n"
        "      if (account) headers['x-app-screen-account'] = account;\n"
        "      const postBuf = req.postDataBuffer();\n"
        "      try {\n"
        "        const resp = await ctx.request.fetch(`${proxyUrl}${rel}`, {\n"
        "          method: req.method(),\n"
        "          headers,\n"
        "          data: postBuf || undefined,\n"
        "          maxRedirects: 0,\n"
        "          timeout: 25000,\n"
        "        });\n"
        "        await route.fulfill({ response: resp });\n"
        "      } catch (_e) {\n"
        "        try { await route.abort(); } catch (_e2) {}\n"
        "      }\n"
        "    });\n"
        "  };\n"
        "  const settle = async (p) => {\n"
        "    if (PAGE.main) await p.waitForSelector(PAGE.main, { timeout: 20000 }).catch(() => {});\n"
        "    await p.waitForTimeout(PAGE.settle_ms ?? 1800);\n"
        "    if (!PAGE.loading_text) return;\n"
        "    for (let i = 0; i < 16; i++) {\n"
        "      const loading = await p.evaluate(([sel, re]) => new RegExp(re).test(document.querySelector(sel)?.innerText || ''), [PAGE.main || 'body', PAGE.loading_text]);\n"
        "      if (!loading) break;\n"
        "      await p.waitForTimeout(500);\n"
        "    }\n"
        "  };\n"
        "  const followFirstLink = async (p, prefix) => {\n"
        "    const href = await p.evaluate(([main, pref]) => {\n"
        "      const a = [...document.querySelectorAll(`${main} a[href^=\"${pref}\"]`)].find((x) => x.getAttribute('href') !== pref && x.offsetParent);\n"
        "      return a ? a.getAttribute('href') : null;\n"
        "    }, [PAGE.main || 'body', prefix]);\n"
        "    if (!href) throw new Error(`no ${prefix} link on ${p.url()}`);\n"
        "    await p.goto(BASE + href, { waitUntil: 'load', timeout: 25000 });\n"
        "    await settle(p);\n"
        "    return href;\n"
        "  };\n"
        "  const clickFirst = async (p, spec) => {\n"
        "    const clicked = await p.evaluate(([main, text, not, never]) => {\n"
        "      const words = new RegExp(text, 'i');\n"
        "      const notRe = not ? new RegExp(not, 'i') : null;\n"
        "      const neverRe = new RegExp(never, 'i');\n"
        "      const btn = [...document.querySelectorAll(`${main} button, ${main} a`)].find((b) => {\n"
        "        const t = (b.innerText || '').trim();\n"
        "        return b.offsetParent && words.test(t) && !(notRe && notRe.test(t)) && !neverRe.test(t);\n"
        "      });\n"
        "      if (!btn) return null;\n"
        "      btn.click();\n"
        "      return (btn.innerText || '').trim().slice(0, 40);\n"
        "    }, [PAGE.main || 'body', spec.text, spec.not || null, NEVER_SRC]);\n"
        "    if (!clicked) throw new Error(`nothing to click matching ${spec.text} on ${p.url()}`);\n"
        "    await p.waitForTimeout(2000);\n"
        "    return clicked;\n"
        "  };\n"
        "  const loginState = async (account) => {\n"
        "    if (!plan.login || !account || account === 'none') return undefined;\n"
        "    if (states[account]) return states[account];\n"
        "    if (failed[`login:${account}`]) throw new Error(failed[`login:${account}`]);\n"
        "    const short = String(account).split('@')[0];\n"
        "    const password = creds[account] || creds[short] || creds['*'] || creds.default || creds.password || '';\n"
        "    if (!password) {\n"
        "      failed[`login:${account}`] = `missing runtime credentials for account ${account}`;\n"
        "      throw new Error(failed[`login:${account}`]);\n"
        "    }\n"
        "    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });\n"
        "    const p = await ctx.newPage();\n"
        "    try {\n"
        "      await attachProxy(ctx, p, account, null);\n"
        "      await p.goto(BASE + plan.login.path, { waitUntil: 'load', timeout: 25000 });\n"
        "      for (const [sel, tmpl] of Object.entries(plan.login.fields || {})) {\n"
        "        const s = String(tmpl);\n"
        "        const val = (s.includes('{account}@') && account.includes('@')) ? account : s.replaceAll('{account}', account);\n"
        "        await p.fill(sel, val);\n"
        "      }\n"
        "      const userSel = plan.login.user_selector || plan.login.email_field || plan.login.user_field;\n"
        "      if (userSel && !(plan.login.fields && userSel in plan.login.fields)) {\n"
        "        const val = (account.includes('@') || plan.login.fields) ? account : `${account}@rollcall.test`;\n"
        "        await p.fill(userSel, val);\n"
        "      }\n"
        "      const pwdSel = plan.login.password_selector || plan.login.password_field;\n"
        "      if (pwdSel) await p.fill(pwdSel, password);\n"
        "      await p.click(plan.login.submit);\n"
        "      await p.waitForSelector(plan.login.wait_for, { timeout: 20000 });\n"
        "      await p.waitForTimeout(1000);\n"
        "      const st = await ctx.storageState();\n"
        "      states[account] = st;\n"
        "      return st;\n"
        "    } catch (err) {\n"
        "      const msg = `login failed for account ${account} at ${BASE}${plan.login.path}: ${err && err.message ? err.message : err}`;\n"
        "      failed[`login:${account}`] = msg;\n"
        "      const e = new Error(msg);\n"
        "      e.loginFailed = true;\n"
        "      throw e;\n"
        "    } finally {\n"
        "      await ctx.close();\n"
        "    }\n"
        "  };\n"
        "  for (const cap of (plan.captures || [])) {\n"
        "    let ctx = null;\n"
        "    try {\n"
        "      const storageState = await loginState(cap.account);\n"
        "      ctx = await browser.newContext({\n"
        "        viewport: { width: cap.width, height: cap.height },\n"
        "        deviceScaleFactor: 2,\n"
        "        isMobile: Boolean(cap.phone),\n"
        "        hasTouch: Boolean(cap.phone),\n"
        "        storageState,\n"
        "      });\n"
        "      const p = await ctx.newPage();\n"
        "      const delay = cap.delay_api ? PAGE.delay_api : null;\n"
        "      await attachProxy(ctx, p, cap.account || '', delay);\n"
        "      const errors = [];\n"
        "      p.on('pageerror', (e) => errors.push(String(e && e.message ? e.message : e).slice(0, 160)));\n"
        "      const did = [];\n"
        "      const steps = cap.steps || [];\n"
        "      for (let i = 0; i < steps.length; i++) {\n"
        "        const step = steps[i];\n"
        "        const last = i === steps.length - 1;\n"
        "        if (step.goto) {\n"
        "          await p.goto(BASE + step.goto, { waitUntil: 'load', timeout: 25000 });\n"
        "          if (delay && last) await p.waitForTimeout(delay.wait_ms ?? 400);\n"
        "          else await settle(p);\n"
        "          did.push(`goto ${step.goto}`);\n"
        "        } else if (step.follow_first_link) {\n"
        "          did.push(`follow ${await followFirstLink(p, step.follow_first_link)}`);\n"
        "        } else if (step.click_first) {\n"
        "          if (typeof step.click_first === 'string') {\n"
        "            await p.locator(step.click_first).first().click({ timeout: 10000 });\n"
        "            did.push(`click ${step.click_first}`);\n"
        "          } else {\n"
        "            did.push(`click \"${await clickFirst(p, step.click_first)}\"`);\n"
        "          }\n"
        "        } else if (step.click) {\n"
        "          await p.click(step.click, { timeout: 10000 });\n"
        "          did.push(`click ${step.click}`);\n"
        "        } else if (step.fill) {\n"
        "          await p.fill(step.fill.selector, step.fill.value, { timeout: 10000 });\n"
        "          did.push(`fill ${step.fill.selector}`);\n"
        "        } else if (step.wait_for) {\n"
        "          await p.waitForSelector(step.wait_for, { state: 'visible', timeout: 15000 });\n"
        "        } else if (step.wait_ms) {\n"
        "          await p.waitForTimeout(step.wait_ms);\n"
        "        }\n"
        "      }\n"
        "      await p.evaluate(() => window.scrollTo(0, 0));\n"
        "      await p.waitForTimeout(200);\n"
        "      const cfg = {\n"
        "        main: PAGE.main || 'body',\n"
        "        areas: PAGE.areas || {},\n"
        "        key_regions: PAGE.key_regions || PAGE.areas || {},\n"
        "        loading_text: PAGE.loading_text || null,\n"
        "        error_selector: PAGE.error_selector || null,\n"
        "      };\n"
        "      const measured = await p.evaluate(`(${measureSrc})(${JSON.stringify(cfg)})`);\n"
        "      const png = await p.screenshot({ fullPage: false });\n"
        "      await ctx.request.fetch(`${proxyUrl}/__app_screen_png__/${token}/${encodeURIComponent(cap.id)}`, {\n"
        "        method: 'POST',\n"
        "        headers: { 'content-type': 'image/png' },\n"
        "        data: png,\n"
        "      });\n"
        "      raw[cap.id] = Object.assign({}, measured, { steps: did, pageErrors: errors });\n"
        "    } catch (err) {\n"
        "      const msg = String(err && err.message ? err.message : err).slice(0, 300);\n"
        "      failed[cap.id] = msg;\n"
        "      raw[cap.id] = { failed: msg };\n"
        "      if (err && err.loginFailed) break;\n"
        "    } finally {\n"
        "      if (ctx) await ctx.close();\n"
        "    }\n"
        "  }\n"
        "  await rootPage.context().request.fetch(`${proxyUrl}/__app_screen_raw__/${token}`, {\n"
        "    method: 'POST',\n"
        "    headers: { 'content-type': 'application/json' },\n"
        "    data: JSON.stringify(raw, null, 2),\n"
        "  });\n"
        "  return { captures: (plan.captures || []).length, ok: (plan.captures || []).length - Object.keys(failed).length, failed };\n"
        "}"
    )
