"""GitHub tools: they read and post as temper's GitHub app, and never more than they say.

Pinned: every call carries the app's installation token for that repository
(never the owner's token); a comment goes in the thread; a review only
comments, whatever the agent asks (never APPROVE, never REQUEST_CHANGES), and
a review whose line comments GitHub refuses goes again with them in its
summary; reading a thread says who the app is, so a run can tell its own
comments apart; and a repository the app is not installed on gets nothing.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from temper_ai.integrations.github import app as github_app
from temper_ai.integrations.github.app import GitHubApp
from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.github import (
    REVIEW_EVENT,
    GitHubComment,
    GitHubFiles,
    GitHubPullDiff,
    GitHubReview,
    GitHubThread,
)

API = "https://api.github.test"
REPO = "shine2lay/temper-ai"
BASE = f"/repos/{REPO}"
APP_TOKEN = "ghs_app_installation_token"  # noqa: S105


@pytest.fixture(scope="module")
def pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


class FakeGitHub:
    """One repository the app is installed on, with issue 12 and pull request 7."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict | None]] = []  # method, path, authorization, body
        self.refuse_line_comments = False
        self.comments = [
            {"id": 1, "user": {"login": "shine2lay"}, "body": "@temper-ai-bot what is this?", "created_at": "t1"},
            {"id": 2, "user": {"login": "temper-ai-bot[bot]"}, "body": "It is a page.", "created_at": "t2"},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, request.headers.get("authorization", ""), body))
        if path == f"{BASE}/installation":
            return httpx.Response(200, json={"id": 99})
        if path.endswith("/installation"):
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/app/installations/99/access_tokens":
            return httpx.Response(201, json={"token": APP_TOKEN, "expires_at": "2099-01-01T00:00:00Z"})
        if path == f"{BASE}/issues/12":
            return httpx.Response(200, json={"number": 12, "title": "Fix the typo", "state": "open",
                                             "body": "In the README", "user": {"login": "shine2lay"},
                                             "labels": [{"name": "temper"}]})
        if path == f"{BASE}/issues/7":
            return httpx.Response(200, json={"number": 7, "title": "Add a page", "state": "open", "body": "",
                                             "user": {"login": "shine2lay"}, "labels": [],
                                             "pull_request": {"url": f"https://api.github.test{BASE}/pulls/7"}})
        if path in (f"{BASE}/issues/12/comments", f"{BASE}/issues/7/comments"):
            if request.method == "POST":
                return httpx.Response(201, json={"id": 901, "html_url": f"https://github.com/{REPO}/issues/12#c901"})
            first = request.url.params.get("page", "1") == "1"
            return httpx.Response(200, json=self.comments if first else [])
        if path == f"{BASE}/pulls/7":
            return httpx.Response(200, json={"number": 7, "title": "Add a page", "draft": False, "merged": False,
                                             "head": {"ref": "add-page", "sha": "abc123",
                                                      "repo": {"full_name": REPO}},
                                             "base": {"ref": "master"}, "changed_files": 1})
        if path == f"{BASE}/pulls/7/reviews":
            if request.method == "POST":
                if self.refuse_line_comments and body and body.get("comments"):
                    return httpx.Response(422, json={"message": "Line could not be resolved"})
                return httpx.Response(200, json={"id": 77, "state": "COMMENTED",
                                                 "html_url": f"https://github.com/{REPO}/pull/7#r77"})
            return httpx.Response(200, json=[])
        if path == f"{BASE}/pulls/7/files":
            first = request.url.params.get("page", "1") == "1"
            return httpx.Response(200, json=[{"filename": "docs/page.md", "status": "added", "additions": 3,
                                              "deletions": 0, "patch": "@@ -0,0 +1,3 @@\n+a\n+b\n+c"}]
                                  if first else [])
        if path == f"{BASE}/contents/README.md":
            return httpx.Response(200, json={"type": "file", "encoding": "base64", "size": 6,
                                             "content": base64.b64encode(b"hello\n").decode()})
        if path == f"{BASE}/contents/docs":
            return httpx.Response(200, json=[{"name": "page.md", "type": "file", "size": 3}])
        return httpx.Response(404, json={"message": "Not Found"})

    def posted(self) -> list[tuple[str, dict | None]]:
        return [(path, body) for method, path, _, body in self.calls if method == "POST" and path.startswith(BASE)]

    def repo_auth(self) -> set[str]:
        return {auth for _, path, auth, _ in self.calls if path.startswith(BASE) and not path.endswith("/installation")}


@pytest.fixture
def gh(pem, monkeypatch):
    monkeypatch.setenv("TEMPER_GITHUB_TOKEN", "ghp_the_owner_s_token")
    fake = FakeGitHub()
    github_app.set_app(GitHubApp("1234", pem, api_url=API, transport=httpx.MockTransport(fake.handler)))
    yield fake
    github_app.set_app(None)


def test_they_are_tools_agents_can_name():
    for tool in (GitHubThread, GitHubPullDiff, GitHubFiles, GitHubComment, GitHubReview):
        assert TOOL_CLASSES[tool.name] is tool


class TestAComment:
    def test_goes_in_the_thread_as_the_app(self, gh):
        result = GitHubComment().execute(repo=REPO, number=12, body="Opened #13 for this.")
        assert result.success, result.error
        assert result.metadata["id"] == 901
        assert gh.posted() == [(f"{BASE}/issues/12/comments", {"body": "Opened #13 for this."})]
        assert gh.repo_auth() == {f"Bearer {APP_TOKEN}"}

    def test_an_empty_one_is_not_posted(self, gh):
        result = GitHubComment().execute(repo=REPO, number=12, body="  ")
        assert not result.success and "empty" in result.error
        assert gh.posted() == []

    @pytest.mark.parametrize("number", [0, -1, "twelve"])
    def test_not_a_number(self, gh, number):
        assert not GitHubComment().execute(repo=REPO, number=number, body="hi").success
        assert gh.posted() == []

    def test_not_where_the_app_is_not_installed(self, gh):
        result = GitHubComment().execute(repo="someone/else", number=1, body="hi")
        assert not result.success and "not installed on someone/else" in result.error
        assert gh.posted() == []


class TestAReview:
    def test_only_ever_comments(self, gh):
        result = GitHubReview().execute(repo=REPO, number=7, body="Looks fine; one note.", event="APPROVE",
                                        comments=[{"path": "docs/page.md", "line": 2, "body": "typo"}])
        assert result.success, result.error
        [(path, review)] = gh.posted()
        assert path == f"{BASE}/pulls/7/reviews"
        assert review["event"] == REVIEW_EVENT == "COMMENT"
        assert review["comments"] == [{"path": "docs/page.md", "line": 2, "side": "RIGHT", "body": "typo"}]
        assert gh.repo_auth() == {f"Bearer {APP_TOKEN}"}

    def test_line_comments_github_refuses_go_in_the_summary(self, gh):
        gh.refuse_line_comments = True
        result = GitHubReview().execute(repo=REPO, number=7, body="Summary.",
                                        comments=[{"path": "docs/page.md", "line": 99, "body": "off the diff"}])
        assert result.success, result.error
        assert result.metadata["inline_comments"] == 0
        first, second = gh.posted()
        assert first[1]["comments"] and "comments" not in second[1]
        assert "`docs/page.md` line 99: off the diff" in second[1]["body"]
        assert {first[1]["event"], second[1]["event"]} == {"COMMENT"}

    def test_a_review_without_a_summary_is_not_posted(self, gh):
        assert not GitHubReview().execute(repo=REPO, number=7, body="").success
        assert gh.posted() == []


class TestReading:
    def test_a_thread_says_who_the_app_is(self, gh):
        result = GitHubThread().execute(repo=REPO, number=12)
        assert result.success, result.error
        thread = result.metadata
        assert (thread["you"], thread["kind"], thread["labels"]) == ("temper-ai-bot[bot]", "issue", ["temper"])
        assert [(c["id"], c["author"]) for c in thread["comments"]] == [(1, "shine2lay"), (2, "temper-ai-bot[bot]")]
        assert gh.posted() == []

    def test_a_pull_request_s_thread_has_its_branches(self, gh):
        thread = GitHubThread().execute(repo=REPO, number=7).metadata
        assert thread["kind"] == "pull"
        assert (thread["pull"]["head"], thread["pull"]["base"], thread["pull"]["head_repo"]) == \
            ("add-page", "master", REPO)
        assert thread["reviews"] == []

    def test_a_pull_request_s_changes(self, gh):
        diff = GitHubPullDiff().execute(repo=REPO, number=7).metadata
        assert [(f["file"], f["status"]) for f in diff["files"]] == [("docs/page.md", "added")]
        assert "+a" in diff["files"][0]["patch"] and diff["head_sha"] == "abc123"

    def test_a_file_and_a_directory(self, gh):
        assert GitHubFiles().execute(repo=REPO, path="README.md").metadata["text"] == "hello\n"
        assert GitHubFiles().execute(repo=REPO, path="docs/").metadata["entries"] == \
            [{"name": "page.md", "type": "file", "size": 3}]

    def test_no_climbing_out_of_the_repository(self, gh):
        result = GitHubFiles().execute(repo=REPO, path="../other/secret")
        assert not result.success
        assert gh.calls == []

    def test_reading_never_uses_the_owner_s_token(self, gh):
        GitHubThread().execute(repo=REPO, number=7)
        assert gh.repo_auth() == {f"Bearer {APP_TOKEN}"}
