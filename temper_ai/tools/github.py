"""Tools that read and write one GitHub issue or pull request, as temper's GitHub app.

Everything they post shows as the app (``<app>[bot]``), never as the owner:
they call GitHub with the app's installation token for the repository
(integrations.github.app), which only temper's own code can make. An agent
names the repository and the number; it never sees a key or a token. They
work on the repositories the app is installed on and nowhere else (GitHub
refuses the rest).

* GitHubThread   -- an issue or pull request and its whole conversation.
* GitHubPullDiff -- the files a pull request changes, with their patches.
* GitHubFiles    -- a file of the repository, or a directory's entries.
* GitHubComment  -- one comment in an issue's or pull request's thread.
* GitHubReview   -- a review of a pull request that only comments. It cannot
  approve, request changes or merge: the review's event is always COMMENT,
  whatever the agent asks.

Nothing here closes, labels, edits or merges anything.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from temper_ai.integrations.github.app import GitHubAppError, check_repo, get_app
from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_BODY = 60_000          # GitHub takes up to 65536 characters in a comment or review
MAX_TEXT = 20_000          # an issue's or PR's own text, as read back
MAX_COMMENT_TEXT = 8_000   # each comment, as read back
MAX_COMMENTS = 100         # the last ones of a long thread
MAX_FILES = 300
DEFAULT_DIFF_CHARS = 60_000
REVIEW_EVENT = "COMMENT"   # never APPROVE, never REQUEST_CHANGES


class _Refused(Exception):
    pass


def _clip(text: Any, limit: int) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + f"\n[... {len(value) - limit} more characters]"


def _number(value: Any) -> int:
    try:
        number = int(str(value).strip().lstrip("#"))
    except (TypeError, ValueError) as exc:
        raise _Refused(f"'{value}' is not an issue or pull request number") from exc
    if number <= 0:
        raise _Refused(f"'{value}' is not an issue or pull request number")
    return number


def _target(params: dict[str, Any]) -> tuple[str, int]:
    try:
        repo = check_repo(str(params.get("repo") or ""))
    except GitHubAppError as exc:
        raise _Refused(str(exc)) from exc
    return repo, _number(params.get("number"))


def _said(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message") or "")[:300]
    except ValueError:
        return response.text[:300]


def _get(repo: str, path: str, **params: Any) -> Any:
    response = get_app().request("GET", repo, path, params=params or None)
    if not response.is_success:
        raise _Refused(f"GitHub answered {response.status_code} for {repo}{path}: {_said(response)}")
    return response.json()


def _pages(repo: str, path: str, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while len(out) < limit:
        batch = _get(repo, path, per_page=100, page=page)
        if not isinstance(batch, list) or not batch:
            break
        out.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
        page += 1
    return out


def _login(user: Any) -> str:
    return str(user.get("login") or "") if isinstance(user, dict) else ""


class _GitHubTool(BaseTool):
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        try:
            result = self._run(params)
        except (_Refused, GitHubAppError) as exc:
            return ToolResult(success=False, result="", error=str(exc))
        except httpx.HTTPError as exc:
            logger.warning("%s failed: %s", self.name, type(exc).__name__)
            return ToolResult(success=False, result="", error=f"could not reach GitHub ({type(exc).__name__})")
        return ToolResult(success=True, result=json.dumps(result), metadata=result)

    def _run(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class GitHubThread(_GitHubTool):
    """Read an issue or pull request and every comment on it."""

    name = "GitHubThread"
    description = (
        "Read a GitHub issue or pull request and its whole conversation: title, text, author, "
        "labels, state, and every comment (oldest first) with its author and id. For a pull "
        "request also its branches, draft state and reviews. Comments by the app itself are "
        "marked by their author, '<app>[bot]'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/name, e.g. shine2lay/temper-ai"},
            "number": {"type": "integer", "description": "The issue or pull request number"},
        },
        "required": ["repo", "number"],
    }
    modifies_state = False

    def _run(self, params: dict[str, Any]) -> dict[str, Any]:
        repo, number = _target(params)
        issue = _get(repo, f"/issues/{number}")
        is_pull = bool(issue.get("pull_request"))
        from temper_ai.integrations.github.settings import load_settings

        thread: dict[str, Any] = {
            "you": load_settings().bot_login,
            "repo": repo,
            "number": number,
            "kind": "pull" if is_pull else "issue",
            "title": issue.get("title"),
            "state": issue.get("state"),
            "author": _login(issue.get("user")),
            "labels": [str(label.get("name")) for label in issue.get("labels") or [] if isinstance(label, dict)],
            "url": issue.get("html_url"),
            "created_at": issue.get("created_at"),
            "body": _clip(issue.get("body"), MAX_TEXT),
        }
        comments = _pages(repo, f"/issues/{number}/comments", 1000)
        thread["comment_count"] = len(comments)
        thread["comments"] = [
            {"id": c.get("id"), "author": _login(c.get("user")), "created_at": c.get("created_at"),
             "url": c.get("html_url"), "body": _clip(c.get("body"), MAX_COMMENT_TEXT)}
            for c in comments[-MAX_COMMENTS:]
        ]
        if is_pull:
            pull = _get(repo, f"/pulls/{number}")
            head, base = pull.get("head") or {}, pull.get("base") or {}
            thread["pull"] = {
                "head": head.get("ref"),
                "head_repo": (head.get("repo") or {}).get("full_name"),
                "base": base.get("ref"),
                "draft": pull.get("draft"),
                "merged": pull.get("merged"),
                "commits": pull.get("commits"),
                "changed_files": pull.get("changed_files"),
                "additions": pull.get("additions"),
                "deletions": pull.get("deletions"),
            }
            reviews = _pages(repo, f"/pulls/{number}/reviews", 300)
            thread["reviews"] = [
                {"id": r.get("id"), "author": _login(r.get("user")), "state": r.get("state"),
                 "submitted_at": r.get("submitted_at"), "body": _clip(r.get("body"), MAX_COMMENT_TEXT)}
                for r in reviews[-MAX_COMMENTS:]
            ]
        return thread


class GitHubPullDiff(_GitHubTool):
    """The files a pull request changes, and their patches."""

    name = "GitHubPullDiff"
    description = (
        "Read what a GitHub pull request changes: every file with its status and line counts, "
        "and the patch of each (the unified diff), up to max_chars in all."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/name, e.g. shine2lay/temper-ai"},
            "number": {"type": "integer", "description": "The pull request number"},
            "max_chars": {"type": "integer", "description": f"Most patch text to return (default {DEFAULT_DIFF_CHARS})"},
        },
        "required": ["repo", "number"],
    }
    modifies_state = False

    def _run(self, params: dict[str, Any]) -> dict[str, Any]:
        repo, number = _target(params)
        try:
            budget = int(params.get("max_chars") or DEFAULT_DIFF_CHARS)
        except (TypeError, ValueError):
            budget = DEFAULT_DIFF_CHARS
        budget = max(1_000, min(budget, 200_000))
        pull = _get(repo, f"/pulls/{number}")
        files = _pages(repo, f"/pulls/{number}/files", MAX_FILES)
        out_files = []
        cut = False
        for f in files:
            patch = str(f.get("patch") or "")
            if len(patch) > budget:
                patch = patch[:budget] + "\n[... patch cut here]" if budget > 0 else ""
                cut = True
            budget -= len(patch)
            out_files.append({
                "file": f.get("filename"), "status": f.get("status"),
                "additions": f.get("additions"), "deletions": f.get("deletions"),
                "previous": f.get("previous_filename"), "patch": patch,
            })
        return {
            "repo": repo, "number": number, "title": pull.get("title"),
            "head": (pull.get("head") or {}).get("ref"), "base": (pull.get("base") or {}).get("ref"),
            "head_sha": (pull.get("head") or {}).get("sha"),
            "files": out_files, "file_count": pull.get("changed_files", len(files)),
            "cut": cut or len(files) >= MAX_FILES,
        }


class GitHubFiles(_GitHubTool):
    """Read one file of a repository, or list a directory."""

    name = "GitHubFiles"
    description = (
        "Read a file of a GitHub repository (its text, up to max_chars), or list a directory's "
        "entries. `path` '' is the top of the repository; `ref` is a branch, tag or commit "
        "(default: the repository's default branch)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/name, e.g. shine2lay/temper-ai"},
            "path": {"type": "string", "description": "File or directory path in the repository ('' for the top)"},
            "ref": {"type": "string", "description": "Branch, tag or commit (optional)"},
            "max_chars": {"type": "integer", "description": f"Most text to return (default {MAX_TEXT * 2})"},
        },
        "required": ["repo", "path"],
    }
    modifies_state = False

    def _run(self, params: dict[str, Any]) -> dict[str, Any]:
        import base64
        from urllib.parse import quote

        try:
            repo = check_repo(str(params.get("repo") or ""))
        except GitHubAppError as exc:
            raise _Refused(str(exc)) from exc
        path = str(params.get("path") or "").strip().strip("/")
        if ".." in path.split("/"):
            raise _Refused(f"'{path}' is not a path in the repository")
        ref = str(params.get("ref") or "").strip()
        try:
            limit = max(1_000, min(int(params.get("max_chars") or MAX_TEXT * 2), 200_000))
        except (TypeError, ValueError):
            limit = MAX_TEXT * 2
        found = _get(repo, f"/contents/{quote(path)}", **({"ref": ref} if ref else {}))
        if isinstance(found, list):
            return {"repo": repo, "path": path, "ref": ref or None, "type": "dir",
                    "entries": [{"name": e.get("name"), "type": e.get("type"), "size": e.get("size")}
                                for e in found if isinstance(e, dict)]}
        if found.get("type") != "file":
            return {"repo": repo, "path": path, "type": found.get("type"), "text": None}
        if found.get("encoding") != "base64" or not found.get("content"):
            return {"repo": repo, "path": path, "type": "file", "size": found.get("size"),
                    "text": None, "note": "too big to read through the API"}
        raw = base64.b64decode(str(found["content"]))
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"repo": repo, "path": path, "type": "file", "size": len(raw), "text": None,
                    "note": "not a text file"}
        return {"repo": repo, "path": path, "ref": ref or None, "type": "file", "size": len(raw),
                "text": _clip(text, limit)}


class GitHubComment(_GitHubTool):
    """Post one comment in an issue's or pull request's thread, as the app."""

    name = "GitHubComment"
    description = (
        "Post a comment in the thread of a GitHub issue or pull request, as temper's GitHub app. "
        "Markdown. Returns the comment's id and link."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/name, e.g. shine2lay/temper-ai"},
            "number": {"type": "integer", "description": "The issue or pull request number"},
            "body": {"type": "string", "description": "The comment (markdown)"},
        },
        "required": ["repo", "number", "body"],
    }
    modifies_state = True

    def _run(self, params: dict[str, Any]) -> dict[str, Any]:
        repo, number = _target(params)
        body = str(params.get("body") or "").strip()
        if not body:
            raise _Refused("the comment is empty")
        if len(body) > MAX_BODY:
            raise _Refused(f"the comment is {len(body)} characters; GitHub takes at most {MAX_BODY}")
        response = get_app().request("POST", repo, f"/issues/{number}/comments", json={"body": body})
        if response.status_code != 201:
            raise _Refused(f"GitHub did not post the comment ({response.status_code}): {_said(response)}")
        comment = response.json()
        logger.info("GitHubComment: %s#%s %s", repo, number, comment.get("html_url"))
        return {"id": comment.get("id"), "url": comment.get("html_url"), "repo": repo, "number": number}


class GitHubReview(_GitHubTool):
    """Review a pull request with comments only, as the app."""

    name = "GitHubReview"
    description = (
        "Post a review on a GitHub pull request, as temper's GitHub app: a summary, and optionally "
        "comments on lines of the changed files. The review only comments: it never approves, never "
        "requests changes and never merges."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/name, e.g. shine2lay/temper-ai"},
            "number": {"type": "integer", "description": "The pull request number"},
            "body": {"type": "string", "description": "The review's summary (markdown)"},
            "comments": {
                "type": "array",
                "description": "Optional comments on lines the pull request changes",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path, as in the diff"},
                        "line": {"type": "integer", "description": "Line number in the new version of the file"},
                        "body": {"type": "string", "description": "The comment"},
                    },
                    "required": ["path", "line", "body"],
                },
            },
        },
        "required": ["repo", "number", "body"],
    }
    modifies_state = True

    def _run(self, params: dict[str, Any]) -> dict[str, Any]:
        repo, number = _target(params)
        body = str(params.get("body") or "").strip()
        if not body:
            raise _Refused("the review has no summary")
        if len(body) > MAX_BODY:
            raise _Refused(f"the review is {len(body)} characters; GitHub takes at most {MAX_BODY}")
        inline = []
        for c in params.get("comments") or []:
            if not isinstance(c, dict):
                continue
            try:
                line = int(str(c.get("line")))
            except (TypeError, ValueError):
                continue
            text = str(c.get("body") or "").strip()
            path = str(c.get("path") or "").strip()
            if path and text and line > 0:
                inline.append({"path": path, "line": line, "side": "RIGHT", "body": _clip(text, MAX_COMMENT_TEXT)})
        app = get_app()
        review: dict[str, Any] = {"body": body, "event": REVIEW_EVENT}
        if inline:
            review["comments"] = inline[:50]
        response = app.request("POST", repo, f"/pulls/{number}/reviews", json=review)
        folded = False
        if response.status_code == 422 and inline:
            # A line outside the diff: the whole review is refused. Say them in the summary instead.
            notes = "\n".join(f"- `{c['path']}` line {c['line']}: {c['body']}" for c in inline[:50])
            review = {"body": _clip(f"{body}\n\n{notes}", MAX_BODY), "event": REVIEW_EVENT}
            response = app.request("POST", repo, f"/pulls/{number}/reviews", json=review)
            folded = True
        if response.status_code != 200:
            raise _Refused(f"GitHub did not post the review ({response.status_code}): {_said(response)}")
        posted = response.json()
        logger.info("GitHubReview: %s#%s %s", repo, number, posted.get("html_url"))
        return {"id": posted.get("id"), "url": posted.get("html_url"), "state": posted.get("state"),
                "inline_comments": 0 if folded else len(inline[:50]), "repo": repo, "number": number}
