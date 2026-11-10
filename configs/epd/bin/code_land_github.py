#!/usr/bin/env python3
"""GitHub REST API v3 client and check-run classifier for `code_land`.

Uses `GITHUB_API_URL` (default `https://api.github.com`) and short-lived GitHub App
installation tokens minted via `code_checkout.fetch_github_token`. Refreshes tokens
automatically before expiry or on HTTP 401 and scrubs secret material from errors.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_BIN_DIR = Path(__file__).resolve().parent
import sys  # noqa: E402

if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

import code_checkout  # noqa: E402

DEFAULT_GITHUB_API_URL = "https://api.github.com"
PASSING_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
TOKEN_REFRESH_INTERVAL_S = 2400.0  # Refresh 1h installation tokens after 40m


class GitHubApiError(Exception):
    """Raised when a GitHub REST API request fails."""

    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def resolve_github_api_url(env: dict[str, str] | None = None) -> str:
    """Validate and return the GitHub REST API base URL."""
    environ = env if env is not None else os.environ
    raw = environ.get("GITHUB_API_URL", "").strip() or DEFAULT_GITHUB_API_URL
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GitHubApiError(
            f"invalid GITHUB_API_URL {raw!r}: expected http(s)://<host>[:<port>]"
        )
    return raw.rstrip("/")


class GitHubApiClient:
    """Minimal stdlib GitHub REST client with automatic App token refresh."""

    def __init__(
        self,
        *,
        owner: str,
        repo_name: str,
        https_remote: str,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.owner = owner
        self.repo_name = repo_name
        self.repo_slug = f"{owner}/{repo_name}"
        self.https_remote = https_remote
        self.env = dict(env if env is not None else os.environ)
        self.api_base = resolve_github_api_url(self.env)
        self.timeout = timeout
        self._token: str = ""
        self._token_minted_at: float = 0.0

    def get_token(self, *, force_refresh: bool = False) -> str:
        now = time.monotonic()
        if (
            not force_refresh
            and self._token
            and (now - self._token_minted_at) < TOKEN_REFRESH_INTERVAL_S
        ):
            return self._token
        try:
            self._token = code_checkout.fetch_github_token(
                self.repo_slug,
                repo_url=self.https_remote,
                env=self.env,
            )
        except code_checkout.CodeCheckoutError as exc:
            raise GitHubApiError(str(exc)) from exc
        self._token_minted_at = time.monotonic()
        return self._token

    def _scrub(self, text: str) -> str:
        extras = [s for s in (self._token, self.env.get("TEMPER_RUN_TOKEN", "")) if s]
        return code_checkout.scrub_secrets(text, extras)

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        allow_statuses: set[int] | None = None,
    ) -> tuple[int, Any]:
        """Perform an authenticated GitHub REST API call and return `(status, data)`."""
        url = f"{self.api_base}{path}"
        allowed = allow_statuses or set()

        for attempt in range(2):
            token = self.get_token(force_refresh=(attempt > 0))
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "temper-code-land/1.0",
            }
            data_bytes: bytes | None = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                data_bytes = json.dumps(payload).encode("utf-8")

            req = urllib.request.Request(
                url, data=data_bytes, headers=headers, method=method
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    parsed = json.loads(raw) if raw.strip() else {}
                    return resp.status, parsed
            except urllib.error.HTTPError as exc:
                raw_err = ""
                try:
                    raw_err = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    raw_err = str(exc)
                parsed_err: Any = raw_err
                err_msg = raw_err.strip()
                try:
                    parsed_err = json.loads(raw_err)
                    if isinstance(parsed_err, dict) and parsed_err.get("message"):
                        err_msg = str(parsed_err["message"])
                except Exception:
                    pass

                if exc.code == 401 and attempt == 0:
                    continue
                if exc.code in allowed:
                    return exc.code, parsed_err

                clean_msg = self._scrub(err_msg)
                raise GitHubApiError(
                    f"GitHub API {method} {path} failed (HTTP {exc.code}): {clean_msg}",
                    status_code=exc.code,
                    body=parsed_err,
                ) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                reason = getattr(exc, "reason", None) or exc
                raise GitHubApiError(
                    f"GitHub API {method} {path} network failure: {self._scrub(str(reason))}"
                ) from exc

        raise GitHubApiError(f"GitHub API {method} {path} failed after token refresh")

    def verify_repo(self) -> dict[str, Any]:
        _, data = self.request("GET", f"/repos/{self.owner}/{self.repo_name}")
        return data if isinstance(data, dict) else {}

    def get_branch_sha(self, branch: str) -> str | None:
        encoded = urllib.parse.quote(branch, safe="/")
        status, data = self.request(
            "GET",
            f"/repos/{self.owner}/{self.repo_name}/git/ref/heads/{encoded}",
            allow_statuses={404},
        )
        if status == 404 or not isinstance(data, dict):
            return None
        obj = data.get("object")
        sha = str(obj.get("sha") or "") if isinstance(obj, dict) else ""
        return sha if code_checkout.SHA40_RE.fullmatch(sha) else None

    def get_pull(self, pr_number: int) -> dict[str, Any]:
        _, data = self.request(
            "GET", f"/repos/{self.owner}/{self.repo_name}/pulls/{pr_number}"
        )
        if not isinstance(data, dict):
            raise GitHubApiError(f"unexpected PR response for #{pr_number}")
        return data

    def find_pulls(
        self, *, branch: str, base: str, state: str = "open"
    ) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "state": state,
                "head": f"{self.owner}:{branch}",
                "base": base,
                "per_page": "20",
            }
        )
        _, data = self.request(
            "GET", f"/repos/{self.owner}/{self.repo_name}/pulls?{query}"
        )
        if not isinstance(data, list):
            return []
        return [
            pr
            for pr in data
            if isinstance(pr, dict)
            and pr.get("head", {}).get("ref") == branch
            and pr.get("base", {}).get("ref") == base
        ]

    def ensure_open_pull(
        self,
        *,
        branch: str,
        base: str,
        title: str,
        body: str,
        prior_pr_number: int | None = None,
    ) -> dict[str, Any]:
        """Idempotently locate an existing PR (including already-merged) or open one."""
        if prior_pr_number is not None:
            pr = self.get_pull(prior_pr_number)
            if pr.get("merged") is True or pr.get("state") == "open":
                return pr

        open_prs = self.find_pulls(branch=branch, base=base, state="open")
        if open_prs:
            return self.get_pull(int(open_prs[0]["number"]))

        all_prs = self.find_pulls(branch=branch, base=base, state="closed")
        for closed_pr in all_prs:
            if closed_pr.get("merged") is True:
                return self.get_pull(int(closed_pr["number"]))

        status, created = self.request(
            "POST",
            f"/repos/{self.owner}/{self.repo_name}/pulls",
            payload={
                "title": title.strip() or f"Merge {branch} into {base}",
                "head": branch,
                "base": base,
                "body": body,
            },
            allow_statuses={422},
        )
        if status == 422:
            retry_open = self.find_pulls(branch=branch, base=base, state="open")
            if retry_open:
                return self.get_pull(int(retry_open[0]["number"]))
            msg = (
                created.get("message")
                if isinstance(created, dict)
                else str(created)
            )
            raise GitHubApiError(
                f"failed to create PR for {branch} -> {base}: {self._scrub(str(msg))}",
                status_code=422,
                body=created,
            )
        if not isinstance(created, dict) or "number" not in created:
            raise GitHubApiError(f"unexpected response creating PR for {branch} -> {base}")
        return self.get_pull(int(created["number"]))

    def merge_pull(
        self, *, pr_number: int, head_sha: str, merge_method: str, commit_title: str = ""
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {
            "sha": head_sha,
            "merge_method": merge_method,
        }
        if commit_title.strip():
            payload["commit_title"] = commit_title.strip()
        status, data = self.request(
            "PUT",
            f"/repos/{self.owner}/{self.repo_name}/pulls/{pr_number}/merge",
            payload=payload,
            allow_statuses={405, 409},
        )
        return status, (data if isinstance(data, dict) else {"message": str(data)})

    def merge_branch(
        self, *, base: str, head_sha: str, commit_message: str
    ) -> tuple[int, dict[str, Any]]:
        status, data = self.request(
            "POST",
            f"/repos/{self.owner}/{self.repo_name}/merges",
            payload={
                "base": base,
                "head": head_sha,
                "commit_message": commit_message.strip() or f"Merge {head_sha[:12]} into {base}",
            },
            allow_statuses={204, 409},
        )
        return status, (data if isinstance(data, dict) else {"message": str(data)})

    def fetch_check_runs(self, head_sha: str) -> dict[str, Any]:
        """Fetch, paginate, deduplicate reruns, and classify check runs on `head_sha`."""
        raw_runs: list[dict[str, Any]] = []
        page = 1
        while True:
            path = (
                f"/repos/{self.owner}/{self.repo_name}/commits/{head_sha}"
                f"/check-runs?per_page=100&page={page}"
            )
            try:
                _, data = self.request("GET", path)
            except GitHubApiError as exc:
                if exc.status_code == 403:
                    raise GitHubApiError(
                        f"GitHub App installation token lacks 'checks: read' permission on "
                        f"{self.repo_slug} while querying check-runs for {head_sha}: {exc}",
                        status_code=403,
                        body=exc.body,
                    ) from exc
                raise
            if not isinstance(data, dict):
                break
            page_runs = data.get("check_runs")
            if not isinstance(page_runs, list) or not page_runs:
                break
            raw_runs.extend(r for r in page_runs if isinstance(r, dict))
            total_count = int(data.get("total_count") or len(raw_runs))
            if len(page_runs) < 100 or len(raw_runs) >= total_count:
                break
            page += 1

        return classify_check_runs(raw_runs)


def classify_check_runs(raw_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Deduplicate reruns per `(app.id, name)` by latest `id` and classify state."""
    deduped: dict[tuple[Any, str], tuple[int, int, dict[str, Any]]] = {}
    for idx, run in enumerate(raw_runs):
        name = str(run.get("name") or "").strip()
        if not name:
            continue
        app = run.get("app")
        app_id = app.get("id") if isinstance(app, dict) else None
        raw_id = run.get("id")
        run_id = int(raw_id) if isinstance(raw_id, int) else idx
        key = (app_id, name)
        prev = deduped.get(key)
        if prev is None or (run_id, idx) >= (prev[0], prev[1]):
            deduped[key] = (run_id, idx, run)

    if not deduped:
        return {"state": "none", "runs": [], "failing": []}

    ordered = [
        item[2]
        for item in sorted(
            deduped.values(),
            key=lambda entry: (str(entry[2].get("name") or ""), entry[0]),
        )
    ]

    summary_runs: list[dict[str, Any]] = []
    failing: list[dict[str, Any]] = []
    any_pending = False

    for run in ordered:
        name = str(run.get("name") or "")
        status = str(run.get("status") or "")
        conclusion_raw = run.get("conclusion")
        conclusion = str(conclusion_raw) if conclusion_raw is not None else None
        url = str(run.get("html_url") or run.get("details_url") or "")

        entry: dict[str, Any] = {
            "name": name,
            "status": status,
            "conclusion": conclusion,
        }
        if url:
            entry["url"] = url
        summary_runs.append(entry)

        if status != "completed":
            any_pending = True
        elif conclusion not in PASSING_CONCLUSIONS:
            failing.append(entry)

    if failing:
        state = "failed"
    elif any_pending:
        state = "pending"
    else:
        state = "passed"

    return {
        "state": state,
        "runs": summary_runs,
        "failing": failing,
    }
