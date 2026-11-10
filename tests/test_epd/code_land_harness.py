"""External HTTP + smart-git test harness for `code_save` and `code_land` (Rule 29).

Stands up a single local `ThreadingHTTPServer` on `127.0.0.1:0` serving:
- `POST /api/github/token` (Temper server GitHub App token minting endpoint)
- `/git/<owner>/<repo>.git/*` backed by `/usr/lib/git-core/git-http-backend`
- GitHub REST API v3 endpoints (`/repos/...`, `/pulls`, `/merges`, `/check-runs`)
  backed by real git commits/merges against the bare repository.

Production scripts (`code_checkout.py`, `code_save.py`, `code_land.py`, `code_land_pause.py`)
contain zero test flags or mock branches.
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

GIT_BIN = "/usr/bin/git"
GIT_HTTP_BACKEND = "/usr/lib/git-core/git-http-backend"


def _git_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "author@example.com",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }


def git_raw(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        [GIT_BIN, "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    return proc.stdout.strip()


class LocalGitHubHarness:
    """Real bare-git + smart-HTTP + GitHub REST v3 test server."""

    def __init__(self, tmp_path: Path, *, repo_slug: str = "acme/widget") -> None:
        self.tmp_path = tmp_path
        self.owner, self.repo_name = repo_slug.split("/", 1)
        self.repo_slug = repo_slug
        self.run_token = "trun_test_harness_secret_998877"

        self._lock = threading.RLock()
        self.token_counter = 0
        self.valid_tokens: set[str] = set()
        self.valid_run_tokens: set[str] = {self.run_token}
        self.fail_token_status: int | None = None
        self.fail_token_message: str = ""
        self.fail_check_runs_status: int | None = None

        self.prs: dict[int, dict[str, Any]] = {}
        self._next_pr_number = 1
        # sha -> list of check_run dicts OR list of snapshots (popped per poll until last)
        self._check_sequences: dict[str, list[list[dict[str, Any]]]] = {}
        self.check_polls_by_sha: dict[str, int] = {}
        self.merge_calls: list[dict[str, Any]] = []
        self.token_requests: list[dict[str, Any]] = []
        self.force_mergeable_none_polls: int = 0
        self.force_behind_when_diverged: bool = False

        self.remotes_root = tmp_path / "remotes"
        self.bare_repo = self.remotes_root / self.owner / f"{self.repo_name}.git"
        self.bare_repo.mkdir(parents=True)
        git_raw(self.bare_repo, "init", "--bare", "-b", "main")
        git_raw(self.bare_repo, "config", "http.receivepack", "true")
        git_raw(self.bare_repo, "config", "uploadpack.allowReachableSHA1InWant", "true")

        seed = tmp_path / "seed"
        seed.mkdir(parents=True)
        git_raw(seed, "init", "-b", "main")
        (seed / "README.md").write_text("line 1\nline 2\n", encoding="utf-8")
        (seed / "shared.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        git_raw(seed, "add", "-A")
        git_raw(seed, "commit", "-m", "initial commit")
        git_raw(seed, "remote", "add", "origin", str(self.bare_repo))
        git_raw(seed, "push", "origin", "main")

        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), self._make_handler()
        )
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

        self.bin_dir = tmp_path / "git-shim-bin"
        self.bin_dir.mkdir(parents=True)
        self._install_git_http_shim()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)

    def _install_git_http_shim(self) -> None:
        """Route `https://github.com/` network transport to local `git-http-backend`."""
        shim = self.bin_dir / "git"
        shim.write_text(
            f"""#!{sys.executable}
import os, subprocess, sys

args = sys.argv[1:]
net_cmds = {{"fetch", "push", "pull", "clone", "ls-remote"}}
subcmd = None
idx = 0
while idx < len(args):
    a = args[idx]
    if a in {{"-C", "-c", "--git-dir", "--work-tree"}}:
        idx += 2
        continue
    if a.startswith("-"):
        idx += 1
        continue
    subcmd = a
    break

cmd = [{GIT_BIN!r}]
if subcmd in net_cmds:
    cmd.extend(["-c", "url.{self.base_url}/git/.insteadOf=https://github.com/"])
    auth_hdr = os.environ.get("GIT_CONFIG_VALUE_0", "")
    if auth_hdr:
        cmd.extend(["-c", f"http.{self.base_url}/.extraheader={{auth_hdr}}"])
cmd.extend(args)
raise SystemExit(subprocess.call(cmd, env=os.environ))
""",
            encoding="utf-8",
        )
        shim.chmod(0o755)

    def env(self, *, workspace_dir: Path | None = None) -> dict[str, str]:
        ws = workspace_dir or (self.tmp_path / "forbidden_workspace")
        ws.mkdir(parents=True, exist_ok=True)
        base_path = os.environ.get("PATH", "/usr/bin:/bin")
        return {
            **os.environ,
            "PATH": f"{self.bin_dir}:{base_path}",
            "TEMPER_SERVER_URL": self.base_url,
            "TEMPER_RUN_TOKEN": self.run_token,
            "GITHUB_API_URL": f"{self.base_url}/api/v3",
            "TEMPER_BOX_ENV": "inherit",
            "WORKSPACE_DIR": str(ws),
        }

    # --- Git & check-run state helpers for tests ---

    def branch_sha(self, branch: str) -> str | None:
        proc = subprocess.run(
            [GIT_BIN, "--git-dir", str(self.bare_repo), "rev-parse", "--verify", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
        return proc.stdout.strip() if proc.returncode == 0 else None

    def commit_on_remote(
        self,
        branch: str,
        files: dict[str, str],
        *,
        message: str = "remote update",
        base: str = "main",
        merge_base: str | None = None,
    ) -> str:
        with self._lock, tempfile.TemporaryDirectory(prefix="harness-edit-") as td:
            work = Path(td) / "w"
            git_raw(Path(td), "clone", str(self.bare_repo), str(work))
            existing = self.branch_sha(branch)
            if existing:
                git_raw(work, "checkout", "-B", branch, f"origin/{branch}")
                if merge_base:
                    subprocess.run(
                        [GIT_BIN, "-C", str(work), "merge", "--no-commit", "--no-ff", f"origin/{merge_base}"],
                        capture_output=True,
                        text=True,
                        check=False,
                        env=_git_env(),
                    )
            else:
                git_raw(work, "checkout", "-B", branch, f"origin/{base}")
            for rel, content in files.items():
                target = work / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            git_raw(work, "add", "-A")
            git_raw(work, "commit", "-m", message)
            if merge_base and existing:
                second_parent = git_raw(work, "rev-parse", "HEAD^2")
                assert len(second_parent) == 40
            sha = git_raw(work, "rev-parse", "HEAD")
            git_raw(work, "push", "origin", f"HEAD:refs/heads/{branch}")
            return sha

    def set_checks(self, sha: str, runs: list[dict[str, Any]]) -> None:
        with self._lock:
            self._check_sequences[sha] = [runs]

    def set_check_sequence(self, sha: str, sequence: list[list[dict[str, Any]]]) -> None:
        with self._lock:
            self._check_sequences[sha] = list(sequence)

    def set_default_checks_callback(
        self, fn: Callable[[str, int], list[dict[str, Any]]] | None
    ) -> None:
        with self._lock:
            self._default_checks_fn = fn

    def _compute_mergeability(self, base: str, head_sha: str) -> tuple[bool, str]:
        base_sha = self.branch_sha(base)
        if not base_sha:
            return False, "dirty"
        anc = subprocess.run(
            [GIT_BIN, "--git-dir", str(self.bare_repo), "merge-base", "--is-ancestor", base_sha, head_sha],
            check=False,
            env=_git_env(),
        )
        mt = subprocess.run(
            [GIT_BIN, "--git-dir", str(self.bare_repo), "merge-tree", "--write-tree", base_sha, head_sha],
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
        if mt.returncode != 0:
            return False, "dirty"
        if anc.returncode != 0:
            if self.force_behind_when_diverged:
                return False, "behind"
            return True, "clean"
        return True, "clean"

    def _perform_git_merge_on_bare(
        self, *, base: str, head_sha: str, method: str, title: str
    ) -> tuple[int, dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="harness-merge-") as td:
            work = Path(td) / "m"
            git_raw(Path(td), "clone", str(self.bare_repo), str(work))
            git_raw(work, "checkout", "-B", base, f"origin/{base}")
            base_before = git_raw(work, "rev-parse", "HEAD")
            if base_before == head_sha:
                return 204, {}
            anc = subprocess.run(
                [GIT_BIN, "-C", str(work), "merge-base", "--is-ancestor", head_sha, base_before],
                check=False,
                env=_git_env(),
            )
            if anc.returncode == 0:
                return 204, {}

            if method == "squash":
                proc = subprocess.run(
                    [GIT_BIN, "-C", str(work), "merge", "--squash", head_sha],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=_git_env(),
                )
                if proc.returncode != 0:
                    return 405, {"message": "Merge conflict"}
                git_raw(work, "commit", "-m", title or f"Squash {head_sha[:12]}")
            elif method == "rebase":
                proc = subprocess.run(
                    [GIT_BIN, "-C", str(work), "merge", "--no-edit", head_sha],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=_git_env(),
                )
                if proc.returncode != 0:
                    return 405, {"message": "Base branch cannot be rebased cleanly"}
            else:
                proc = subprocess.run(
                    [GIT_BIN, "-C", str(work), "merge", "--no-ff", "-m", title or f"Merge {head_sha[:12]}", head_sha],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=_git_env(),
                )
                if proc.returncode != 0:
                    return 409, {"message": "Merge conflict"}

            merged_sha = git_raw(work, "rev-parse", "HEAD")
            git_raw(work, "push", "origin", f"HEAD:refs/heads/{base}")
            return 200, {"merged": True, "sha": merged_sha}

    def _make_handler(self):
        harness = self
        default_checks_Attr = "_default_checks_fn"

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                return

            def _send_json(self, code: int, payload: Any) -> None:
                body = json.dumps(payload).encode("utf-8") if payload is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _check_github_bearer(self) -> bool:
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    self._send_json(401, {"message": "Bad credentials"})
                    return False
                tok = auth.removeprefix("Bearer ").strip()
                with harness._lock:
                    ok = tok in harness.valid_tokens
                if not ok:
                    self._send_json(401, {"message": f"Expired or invalid token {tok}"})
                return ok

            def _handle_git_http(self) -> None:
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Basic "):
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="GitHub"')
                    self.end_headers()
                    return
                decoded = base64.b64decode(auth.removeprefix("Basic ").strip()).decode("utf-8", errors="replace")
                _, _, tok = decoded.partition(":")
                with harness._lock:
                    valid = tok in harness.valid_tokens
                if not valid:
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(f"invalid token {tok}".encode())
                    return

                parsed = urllib.parse.urlsplit(self.path)
                rel_path = parsed.path.removeprefix("/git")
                length = int(self.headers.get("Content-Length") or 0)
                req_body = self.rfile.read(length) if length > 0 else b""
                cgi_env = {
                    **os.environ,
                    "GIT_PROJECT_ROOT": str(harness.remotes_root),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "PATH_INFO": rel_path,
                    "QUERY_STRING": parsed.query,
                    "REQUEST_METHOD": self.command,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": str(len(req_body)),
                    "REMOTE_USER": "x-access-token",
                    "REMOTE_ADDR": "127.0.0.1",
                }
                proc = subprocess.run(
                    [GIT_HTTP_BACKEND],
                    input=req_body,
                    capture_output=True,
                    env=cgi_env,
                    check=False,
                )
                raw = proc.stdout
                sep = b"\r\n\r\n" if b"\r\n\r\n" in raw else b"\n\n"
                hdr_bytes, _, out_body = raw.partition(sep)
                status_code = 200
                out_headers: list[tuple[str, str]] = []
                for line in hdr_bytes.decode("utf-8", errors="replace").splitlines():
                    if ":" not in line:
                        continue
                    k, v = line.split(":", 1)
                    k_clean, v_clean = k.strip(), v.strip()
                    if k_clean.lower() == "status":
                        status_code = int(v_clean.split()[0])
                    else:
                        out_headers.append((k_clean, v_clean))
                self.send_response(status_code)
                for k, v in out_headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(out_body)))
                self.end_headers()
                if out_body:
                    self.wfile.write(out_body)

            def _handle_token_mint(self) -> None:
                auth = self.headers.get("Authorization", "")
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                with harness._lock:
                    harness.token_requests.append({"auth": auth, "body": body})
                    bearer = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
                    if bearer not in harness.valid_run_tokens:
                        self._send_json(401, {"detail": f"bad bearer {auth}"})
                        return
                    if harness.fail_token_status is not None:
                        self._send_json(
                            harness.fail_token_status,
                            {"detail": harness.fail_token_message or "token mint refused"},
                        )
                        return
                    harness.token_counter += 1
                    tok = f"ghs_liveHarnessToken_{harness.token_counter:04d}_secretXYZ"
                    harness.valid_tokens.add(tok)
                self._send_json(200, {"token": tok})

            def _refresh_pr(self, pr: dict[str, Any]) -> dict[str, Any]:
                if pr["merged"]:
                    return dict(pr)
                head_branch = pr["head"]["ref"]
                base_branch = pr["base"]["ref"]
                latest_sha = harness.branch_sha(head_branch)
                if latest_sha:
                    pr["head"]["sha"] = latest_sha
                latest_base = harness.branch_sha(base_branch)
                if latest_base:
                    pr["base"]["sha"] = latest_base

                if harness.force_mergeable_none_polls > 0:
                    harness.force_mergeable_none_polls -= 1
                    pr["mergeable"] = None
                    pr["mergeable_state"] = "unknown"
                elif pr.get("force_dirty_for_sha") == pr["head"]["sha"]:
                    pr["mergeable"] = False
                    pr["mergeable_state"] = "dirty"
                else:
                    ok, st = harness._compute_mergeability(base_branch, pr["head"]["sha"])
                    pr["mergeable"] = ok
                    pr["mergeable_state"] = st
                return dict(pr)

            def _dispatch_api(self) -> None:
                if not self._check_github_bearer():
                    return
                parsed = urllib.parse.urlsplit(self.path)
                api_path = parsed.path.removeprefix("/api/v3")
                query = urllib.parse.parse_qs(parsed.query)
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length > 0 else {}

                prefix = f"/repos/{harness.repo_slug}"
                if api_path == prefix and self.command == "GET":
                    self._send_json(200, {"full_name": harness.repo_slug, "default_branch": "main"})
                    return

                m_ref = re.fullmatch(rf"{re.escape(prefix)}/git/ref/heads/(.+)", api_path)
                if m_ref and self.command == "GET":
                    branch = urllib.parse.unquote(m_ref.group(1))
                    sha = harness.branch_sha(branch)
                    if not sha:
                        self._send_json(404, {"message": "Not Found"})
                    else:
                        self._send_json(200, {"ref": f"refs/heads/{branch}", "object": {"sha": sha}})
                    return

                if api_path == f"{prefix}/pulls" and self.command == "GET":
                    state = (query.get("state") or ["open"])[0]
                    head_q = (query.get("head") or [""])[0]
                    base_q = (query.get("base") or [""])[0]
                    head_ref = head_q.split(":", 1)[1] if ":" in head_q else head_q
                    with harness._lock:
                        out = []
                        for pr in harness.prs.values():
                            refreshed = self._refresh_pr(pr)
                            if state != "all" and refreshed["state"] != state:
                                continue
                            if head_ref and refreshed["head"]["ref"] != head_ref:
                                continue
                            if base_q and refreshed["base"]["ref"] != base_q:
                                continue
                            out.append(refreshed)
                    self._send_json(200, out)
                    return

                if api_path == f"{prefix}/pulls" and self.command == "POST":
                    head_ref = payload["head"]
                    base_ref = payload["base"]
                    head_sha = harness.branch_sha(head_ref)
                    base_sha = harness.branch_sha(base_ref)
                    if not head_sha or not base_sha:
                        self._send_json(422, {"message": "Invalid head or base branch"})
                        return
                    with harness._lock:
                        for existing in harness.prs.values():
                            if (
                                existing["state"] == "open"
                                and existing["head"]["ref"] == head_ref
                                and existing["base"]["ref"] == base_ref
                            ):
                                self._send_json(422, {"message": "A pull request already exists"})
                                return
                        num = harness._next_pr_number
                        harness._next_pr_number += 1
                        pr = {
                            "number": num,
                            "state": "open",
                            "merged": False,
                            "merge_commit_sha": None,
                            "title": payload.get("title") or head_ref,
                            "body": payload.get("body") or "",
                            "html_url": f"https://github.com/{harness.repo_slug}/pull/{num}",
                            "head": {"ref": head_ref, "sha": head_sha},
                            "base": {"ref": base_ref, "sha": base_sha},
                            "mergeable": True,
                            "mergeable_state": "clean",
                        }
                        harness.prs[num] = pr
                        refreshed = self._refresh_pr(pr)
                    self._send_json(201, refreshed)
                    return

                m_pr = re.fullmatch(rf"{re.escape(prefix)}/pulls/(\d+)", api_path)
                if m_pr and self.command == "GET":
                    num = int(m_pr.group(1))
                    with harness._lock:
                        pr = harness.prs.get(num)
                        if not pr:
                            self._send_json(404, {"message": "Not Found"})
                            return
                        refreshed = self._refresh_pr(pr)
                    self._send_json(200, refreshed)
                    return

                m_merge_pr = re.fullmatch(rf"{re.escape(prefix)}/pulls/(\d+)/merge", api_path)
                if m_merge_pr and self.command == "PUT":
                    num = int(m_merge_pr.group(1))
                    with harness._lock:
                        pr = harness.prs.get(num)
                        if not pr:
                            self._send_json(404, {"message": "Not Found"})
                            return
                        refreshed = self._refresh_pr(pr)
                        req_sha = payload.get("sha")
                        if req_sha and req_sha != refreshed["head"]["sha"]:
                            self._send_json(409, {"message": "Head branch was modified"})
                            return
                        if refreshed["mergeable"] is None:
                            self._send_json(405, {"message": "Mergeability is still being calculated"})
                            return
                        if refreshed["mergeable"] is False:
                            self._send_json(405, {"message": "Pull Request is not mergeable"})
                            return
                        code, res = harness._perform_git_merge_on_bare(
                            base=refreshed["base"]["ref"],
                            head_sha=refreshed["head"]["sha"],
                            method=payload.get("merge_method") or "squash",
                            title=payload.get("commit_title") or refreshed["title"],
                        )
                        if code in (200, 204):
                            merged_sha = res.get("sha") or harness.branch_sha(refreshed["base"]["ref"])
                            pr["merged"] = True
                            pr["state"] = "closed"
                            pr["merge_commit_sha"] = merged_sha
                            harness.merge_calls.append(
                                {"mode": "pr", "pr_number": num, "head_sha": refreshed["head"]["sha"], "merged_sha": merged_sha}
                            )
                            self._send_json(200, {"merged": True, "sha": merged_sha})
                        else:
                            self._send_json(code, res)
                    return

                if api_path == f"{prefix}/merges" and self.command == "POST":
                    base_ref = payload["base"]
                    head_sha = payload["head"]
                    msg = payload.get("commit_message") or f"Merge {head_sha[:12]}"
                    with harness._lock:
                        code, res = harness._perform_git_merge_on_bare(
                            base=base_ref, head_sha=head_sha, method="merge", title=msg
                        )
                        if code == 200:
                            harness.merge_calls.append(
                                {"mode": "merge", "base": base_ref, "head_sha": head_sha, "merged_sha": res["sha"]}
                            )
                            self._send_json(201, {"sha": res["sha"]})
                        elif code == 204:
                            self.send_response(204)
                            self.end_headers()
                        else:
                            self._send_json(409, {"message": "Merge conflict"})
                    return

                m_chk = re.fullmatch(rf"{re.escape(prefix)}/commits/([0-9a-f]{{40}})/check-runs", api_path)
                if m_chk and self.command == "GET":
                    sha = m_chk.group(1)
                    with harness._lock:
                        if harness.fail_check_runs_status is not None:
                            self._send_json(
                                harness.fail_check_runs_status,
                                {"message": "Resource not accessible by integration"},
                            )
                            return
                        poll_idx = harness.check_polls_by_sha.get(sha, 0) + 1
                        harness.check_polls_by_sha[sha] = poll_idx
                        seq = harness._check_sequences.get(sha)
                        if seq:
                            runs = seq.pop(0) if len(seq) > 1 else seq[0]
                        elif getattr(harness, default_checks_Attr, None) is not None:
                            runs = getattr(harness, default_checks_Attr)(sha, poll_idx)
                        else:
                            runs = []
                    self._send_json(200, {"total_count": len(runs), "check_runs": runs})
                    return

                self._send_json(404, {"message": f"Unhandled API route {self.command} {api_path}"})

            def do_GET(self) -> None:
                if self.path.startswith("/git/"):
                    self._handle_git_http()
                elif self.path.startswith("/api/v3/"):
                    self._dispatch_api()
                else:
                    self._send_json(404, {"detail": "not found"})

            def do_POST(self) -> None:
                if self.path == "/api/github/token":
                    self._handle_token_mint()
                elif self.path.startswith("/git/"):
                    self._handle_git_http()
                elif self.path.startswith("/api/v3/"):
                    self._dispatch_api()
                else:
                    self._send_json(404, {"detail": "not found"})

            def do_PUT(self) -> None:
                if self.path.startswith("/api/v3/"):
                    self._dispatch_api()
                else:
                    self._send_json(404, {"detail": "not found"})

        return Handler
