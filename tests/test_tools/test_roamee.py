"""The three roamee tools: what a run may ask, and what it may never do.

Pinned: each tool asks roamee-reader over its unix socket and nothing else
(no docker, no database library, no shell in sight); it says where every
answer came from and when; an unknown question, a container that is not
roamee's and a reader that is not there all come back as plain words, never
as a traceback; and GitHub and Linear are only ever read.

The socket is a real unix socket in a temporary folder, answered by a fake
reader: nothing here touches the live stack, GitHub or Linear.
"""

from __future__ import annotations

import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.roamee import CONTAINERS, REPO, RoameeData, RoameeStack, RoameeWork

STACK = {
    "looked_at": "2026-09-30 12:00:00Z",
    "source": "docker inspect on the box, compose project roamee-staging",
    "up": True,
    "containers": [
        {"container": CONTAINERS[0], "state": "running", "health": "healthy", "build": "abc1234",
         "up_for": "28 hours", "restarts": 0},
        {"container": CONTAINERS[1], "state": "running", "health": "healthy", "build": "abc1234",
         "up_for": "28 hours", "restarts": 2},
        {"container": CONTAINERS[2], "state": "running", "health": "healthy", "build": "",
         "up_for": "28 hours", "restarts": 0},
    ],
}


class FakeReader:
    """A roamee-reader on a real unix socket, answering from a script."""

    def __init__(self, path: Path) -> None:
        self.asked: list[tuple[str, str, dict[str, Any]]] = []
        self.answers: dict[str, tuple[int, dict[str, Any]]] = {}
        reader = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *_: Any) -> None:
                return

            def _say(self, method: str) -> None:
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                reader.asked.append((method, parsed.path, {**{k: v[0] for k, v in
                                                             parse_qs(parsed.query).items()}, **body}))
                status, payload = reader.answers.get(parsed.path, (404, {"error": "no"}))
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                self._say("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._say("POST")

        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True

            def get_request(self) -> tuple[Any, Any]:
                request, _ = super().get_request()
                return request, ("test", 0)

        self.server = Server(str(path), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def answer(self, path: str, payload: dict[str, Any], status: int = 200) -> None:
        self.answers[path] = (status, payload)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    one = FakeReader(tmp_path / "reader.sock")
    monkeypatch.setenv("ROAMEE_READER_SOCKET", str(tmp_path / "reader.sock"))
    yield one
    one.close()


# -- the stack ---------------------------------------------------------------


def test_stack_status_reads_as_a_person_would_write_it(reader: Any) -> None:
    reader.answer("/stack", STACK)
    out = RoameeStack().execute(what="status")
    assert out.success
    assert "roamee staging is up" in out.result
    assert "2026-09-30 12:00:00Z" in out.result, "the answer must say when it looked"
    assert "docker inspect" in out.result, "the answer must say where it looked"
    for name in CONTAINERS:
        assert name in out.result
    assert "abc1234" in out.result
    assert reader.asked == [("GET", "/stack", {})]


def test_stack_says_when_something_is_down(reader: Any) -> None:
    down = {**STACK, "up": False,
            "containers": [{**STACK["containers"][0], "state": "not there"}, *STACK["containers"][1:]]}
    reader.answer("/stack", down)
    out = RoameeStack().execute(what="status")
    assert "NOT fully up" in out.result
    assert "NOT THERE" in out.result


def test_stack_logs_name_the_container_and_the_time(reader: Any) -> None:
    reader.answer("/logs", {"container": CONTAINERS[1], "lines": 40, "looked_at": "2026-09-30 12:01:00Z",
                            "source": f"docker logs --tail 40 {CONTAINERS[1]}", "log": "INFO started"})
    out = RoameeStack().execute(what="logs", container=CONTAINERS[1], lines=40)
    assert out.success
    assert CONTAINERS[1] in out.result and "2026-09-30 12:01:00Z" in out.result
    assert "INFO started" in out.result
    assert reader.asked[-1][1] == "/logs"
    assert reader.asked[-1][2]["container"] == CONTAINERS[1]


def test_stack_refuses_what_it_was_not_given(reader: Any) -> None:
    out = RoameeStack().execute(what="restart", container=CONTAINERS[0])
    assert not out.success
    assert "status" in out.error and "logs" in out.error
    assert reader.asked == [], "it went to the reader for something it does not do"


def test_stack_logs_need_a_container(reader: Any) -> None:
    out = RoameeStack().execute(what="logs")
    assert not out.success
    assert CONTAINERS[0] in out.error
    assert reader.asked == []


def test_a_container_that_is_not_roamees_is_refused_by_the_reader(reader: Any) -> None:
    reader.answer("/logs", {"error": "'temper-ai-server-1' is not one of roamee's staging containers"}, status=403)
    out = RoameeStack().execute(what="logs", container="temper-ai-server-1")
    assert not out.success
    assert "not one of roamee's" in out.error


def test_no_reader_is_said_plainly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ROAMEE_READER_SOCKET", str(tmp_path / "nothing.sock"))
    out = RoameeStack().execute(what="status")
    assert not out.success
    assert "can't see the containers" in out.error
    assert "Traceback" not in out.error


# -- the database ------------------------------------------------------------


def test_a_read_comes_back_as_a_small_table(reader: Any) -> None:
    reader.answer("/sql", {"looked_at": "2026-09-30 12:02:00Z",
                           "source": "staging's database trip_planner_staging on "
                                     f"{CONTAINERS[2]}, read-only login temper_ro",
                           "columns": ["status", "count"], "rows": [["planned", "12"], ["draft", "3"]],
                           "row_count": 2, "truncated": False, "hidden_columns": []})
    out = RoameeData().execute(what="read", sql="select status, count(*) from trips group by 1")
    assert out.success
    assert "planned" in out.result and "12" in out.result
    assert "2026-09-30 12:02:00Z" in out.result and "read-only login temper_ro" in out.result
    assert reader.asked[-1][2] == {"action": "read", "sql": "select status, count(*) from trips group by 1"}


def test_the_row_cap_and_blanked_columns_are_shown(reader: Any) -> None:
    reader.answer("/sql", {"looked_at": "t", "source": "s", "columns": ["id", "password_hash"],
                           "rows": [["1", "[hidden]"]], "row_count": 1, "truncated": True,
                           "hidden_columns": ["password_hash"]})
    out = RoameeData().execute(what="read", sql="select id, password_hash from users")
    assert "more rows" in out.result
    assert "sounds like a secret" in out.result
    assert "password_hash" in out.result


def test_a_write_is_refused_by_the_reader_and_said_plainly(reader: Any) -> None:
    reader.answer("/sql", {"error": "'DELETE' is not something I will run: this reads staging's "
                                    "database and never changes it"}, status=403)
    out = RoameeData().execute(what="read", sql="delete from trips")
    assert not out.success
    assert "never changes it" in out.error


def test_the_database_tool_refuses_what_it_was_not_given(reader: Any) -> None:
    out = RoameeData().execute(what="truncate", table="trips")
    assert not out.success
    assert "tables" in out.error and "read" in out.error
    assert reader.asked == []


def test_a_read_without_a_query_and_columns_without_a_table(reader: Any) -> None:
    assert "select" in (RoameeData().execute(what="read").error or "")
    assert "table" in (RoameeData().execute(what="columns").error or "")
    assert reader.asked == []


def test_a_slow_query_comes_back_as_words(reader: Any) -> None:
    reader.answer("/sql", {"error": "that query took longer than 5 seconds, so staging's "
                                    "database stopped it"}, status=403)
    out = RoameeData().execute(what="read", sql="select * from trips t1, trips t2, trips t3")
    assert not out.success
    assert "longer than 5 seconds" in out.error


# -- what a run may never do -------------------------------------------------


def test_no_tool_here_can_change_anything() -> None:
    for tool in (RoameeStack(), RoameeData(), RoameeWork()):
        assert tool.modifies_state is False
        names = set(tool.parameters["properties"])
        assert not (names & {"command", "cmd", "shell", "script", "path", "file", "exec"}), \
            f"{tool.name} takes something free-form"
    assert set(RoameeStack().parameters["properties"]["container"]["enum"]) == set(CONTAINERS)
    assert set(RoameeStack().parameters["properties"]["what"]["enum"]) == {"status", "logs"}
    assert set(RoameeData().parameters["properties"]["what"]["enum"]) == {"tables", "columns", "read"}
    assert set(RoameeWork().parameters["properties"]["what"]["enum"]) == {"pulls", "commits", "checks", "issues"}


def test_the_three_tools_are_registered() -> None:
    for name in ("RoameeStack", "RoameeData", "RoameeWork"):
        assert TOOL_CLASSES[name].name == name


# -- GitHub and Linear -------------------------------------------------------


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload, self.status_code = payload, status
        self.is_success = 200 <= status < 300

    def json(self) -> Any:
        return self._payload


class FakeApp:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers, self.calls = answers, []

    def request(self, method: str, repo: str, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, repo, path, kwargs.get("params")))
        return FakeResponse(self.answers.get(path, []))


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> Any:
    from temper_ai.integrations.github import app as github_app

    app = FakeApp({
        "/pulls": [{"number": 7, "title": "Add the itinerary page", "user": {"login": "shine2lay"},
                    "draft": False, "head": {"ref": "itinerary"}, "updated_at": "2026-09-29T10:00:00Z"}],
        "/commits": [{"sha": "abc1234def", "commit": {"message": "Fix the map\n\nmore", "author":
                                                      {"name": "shine2lay", "date": "2026-09-03T10:00:00Z"}}}],
    })
    monkeypatch.setattr(github_app, "get_app", lambda: app)
    monkeypatch.setattr(github_app, "check_repo", lambda repo: repo)
    return app


def test_pulls_and_commits_name_their_source(github: Any) -> None:
    out = RoameeWork().execute(what="pulls")
    assert out.success and "#7" in out.result and "Add the itinerary page" in out.result
    assert f"GitHub {REPO}" in out.result

    out = RoameeWork().execute(what="commits")
    assert "abc1234d" in out.result and "Fix the map" in out.result
    assert "more" not in out.result, "a commit message is one line here"
    assert all(method == "GET" for method, *_ in github.calls), "GitHub was only ever read"


CHECKS = {
    "looked_at": "2026-10-01 06:00:00Z",
    "source": "GitHub check runs for shine2lay/roamee staging",
    "repo": REPO, "branch": "staging", "commit": "abc1234d", "total": 2, "failed": 1,
    "checks": [{"check": "tests", "status": "completed", "result": "failure"},
               {"check": "lint", "status": "completed", "result": "success"}],
}


def test_the_checks_come_from_the_reader_failing_ones_first(reader: Any, github: Any) -> None:
    """Temper's own GitHub token cannot see check runs, so this one question
    goes to roamee-reader, which asks the box's gh for exactly one branch."""
    reader.answer("/checks", CHECKS)
    out = RoameeWork().execute(what="checks")
    assert out.success
    assert "1 of 2 checks failed" in out.result and "abc1234d" in out.result
    assert out.result.index("tests") < out.result.index("lint"), "a failing check comes first"
    assert "looked at 2026-10-01 06:00:00Z" in out.result
    assert reader.asked == [("GET", "/checks", {"branch": "staging"})]
    assert github.calls == [], "not through temper's own token"


def test_all_the_checks_passing_says_so(reader: Any) -> None:
    reader.answer("/checks", {**CHECKS, "failed": 0,
                             "checks": [{"check": "lint", "status": "completed", "result": "success"}],
                             "total": 1})
    out = RoameeWork().execute(what="checks")
    assert "All 1 checks passed" in out.result


def test_no_checks_at_all_is_said_plainly(reader: Any) -> None:
    reader.answer("/checks", {**CHECKS, "total": 0, "failed": 0, "checks": [], "commit": ""})
    out = RoameeWork().execute(what="checks")
    assert out.success and "No checks have run" in out.result


def test_the_reader_refusing_the_checks_is_passed_on(reader: Any) -> None:
    reader.answer("/checks", {"error": "GitHub has no branch nope on shine2lay/roamee"}, status=403)
    out = RoameeWork().execute(what="checks", branch="nope")
    assert not out.success and "no branch nope" in out.error


def test_github_is_only_ever_asked_about_roamee(github: Any) -> None:
    RoameeWork().execute(what="pulls")
    assert {repo for _, repo, *_ in github.calls} == {REPO}


def test_a_list_it_does_not_keep_is_refused(github: Any) -> None:
    out = RoameeWork().execute(what="merge")
    assert not out.success
    assert "pulls" in out.error and "issues" in out.error
    assert github.calls == []


def test_github_not_answering_is_said_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    from temper_ai.integrations.github import app as github_app

    def boom() -> Any:
        raise github_app.GitHubAppError("no GitHub app is set up (GITHUB_APP_ID)")

    monkeypatch.setattr(github_app, "get_app", boom)
    monkeypatch.setattr(github_app, "check_repo", lambda repo: repo)
    out = RoameeWork().execute(what="pulls")
    assert not out.success
    assert "couldn't ask GitHub" in out.error
    assert "Traceback" not in out.error


def test_issues_come_from_linears_roamee_team_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from temper_ai.triggers import linear

    asked: list[tuple[str, dict]] = []

    def graphql(query: str, variables: dict | None = None, creds: Any = None) -> dict:
        asked.append((query, dict(variables or {})))
        return {"issues": {"nodes": [
            {"identifier": "ROA-12", "title": "Trips do not save", "updatedAt": "2026-09-28T10:00:00Z",
             "priorityLabel": "High", "state": {"name": "In Progress", "type": "started"},
             "assignee": {"name": "lomit"}},
            {"identifier": "ROA-9", "title": "Old one", "updatedAt": "2026-09-01T10:00:00Z",
             "priorityLabel": "Low", "state": {"name": "Done", "type": "completed"}, "assignee": None},
        ]}}

    monkeypatch.setattr(linear, "graphql", graphql)
    out = RoameeWork().execute(what="issues")
    assert out.success
    assert "ROA-12" in out.result and "In Progress" in out.result
    assert "ROA-9" not in out.result, "a finished issue is not an open one"
    assert "Linear team ROA" in out.result
    assert asked[0][1]["team"] == "ROA"
    assert "mutation" not in asked[0][0].lower(), "Linear is only ever read"


def test_linear_not_answering_is_said_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    from temper_ai.triggers import linear

    def boom(*_: Any, **__: Any) -> dict:
        raise RuntimeError("no Linear credentials")

    monkeypatch.setattr(linear, "graphql", boom)
    out = RoameeWork().execute(what="issues")
    assert not out.success
    assert "couldn't ask Linear" in out.error
    assert "no Linear credentials" not in out.error or "RuntimeError" in out.error
