"""``temper run`` starts the run on the server and follows it; it never runs anything itself.

Every test talks to a fake temper server on 127.0.0.1 (the few routes ``temper run`` uses, with
scripted answers), never to a live one.
"""

from __future__ import annotations

import itertools
import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from temper_ai.cli import run_on_server
from temper_ai.cli.main import main

RUN_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
UI = "https://temper.example.test"
LINK = f"{UI}/app/workflow/{RUN_ID}"


def record(status: str, *nodes: dict, duration=None, cost=0.0, error=None, output=None) -> dict:
    """The run's record as GET /api/workflows/{id} answers it (the fields `temper run` reads)."""
    return {"id": RUN_ID, "workflow_name": "wf", "status": status, "nodes": list(nodes),
            "duration_seconds": duration, "total_cost_usd": cost, "error_message": error,
            "workflow_output": output}


def node(name: str, status: str, *children: dict, duration=None, error=None) -> dict:
    return {"id": f"ev-{name}-{status}", "name": name, "type": "agent", "status": status,
            "duration_seconds": duration, "error_message": error, "child_nodes": list(children) or None}


def wait(event_id: str, *questions, node_name: str = "decide") -> dict:
    """One open wait as GET /api/runs/{id}/gates lists it."""
    return {"node_name": node_name, "status": "waiting", "event_id": event_id, "path": node_name,
            "round": 1, "opened_at": None, "upstream": [], "questions": list(questions)}


class FakeTemper:
    """Just enough of the temper server: start a run, its record, its open waits.

    ``records`` is the script: each GET of the run's record answers the next one (the last one
    repeats), and GET .../gates answers ``waits`` for that same step.
    """

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.start_answer: tuple[int, object] = (200, {"execution_id": RUN_ID, "status": "queued"})
        self.records: list[dict] = [record("completed", duration=1)]
        self.waits: list[list[dict]] = []
        self.record_status = 200
        self._step = -1
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def seen(self, method: str | None = None) -> list[str]:
        return [f"{r['method']} {r['path']}" for r in self.requests if method in (None, r["method"])]

    def _note(self, method: str, path: str, body, headers) -> None:
        with self._lock:
            self.requests.append({"method": method, "path": path, "body": body,
                                  "authorization": headers.get("Authorization")})

    def _next_record(self) -> dict:
        with self._lock:
            self._step = min(self._step + 1, len(self.records) - 1)
            return self.records[self._step]

    def _waits_now(self) -> list[dict]:
        with self._lock:
            step = max(self._step, 0)
            return self.waits[step] if step < len(self.waits) else []

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # the test output stays the CLI's
                pass

            def _answer(self, status: int, body) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"null")
                fake._note("POST", self.path, body, self.headers)
                if self.path == "/api/runs":
                    self._answer(*fake.start_answer)
                else:
                    self._answer(404, {"detail": "Not Found"})

            def do_GET(self) -> None:
                fake._note("GET", self.path, None, self.headers)
                if self.path == f"/api/workflows/{RUN_ID}":
                    if fake.record_status != 200:
                        self._answer(fake.record_status, {"detail": "the server is having a moment"})
                    else:
                        self._answer(200, fake._next_record())
                elif self.path == f"/api/runs/{RUN_ID}/gates":
                    self._answer(200, {"execution_id": RUN_ID, "gates": fake._waits_now()})
                else:
                    self._answer(404, {"detail": "Not Found"})

        return Handler


@pytest.fixture
def fake():
    server = FakeTemper()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def _no_server_settings(monkeypatch):
    """The developer's own server address, links and token never reach these tests."""
    for name in ("TEMPER_SERVER_URL", "TEMPER_UI_URL", "TEMPER_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def dead_url() -> str:
    """An address on this machine where nothing listens."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def start(fake: FakeTemper, inputs: dict | None = None, **kw) -> int:
    kw.setdefault("server", fake.url)
    kw.setdefault("ui", UI)
    kw.setdefault("sleep", lambda seconds: None)
    return run_on_server.run("wf", {"topic": "cats"} if inputs is None else inputs, **kw)


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


# --- starting -----------------------------------------------------------------------------------


class TestStart:
    def test_posts_the_workflow_its_inputs_and_no_workspace(self, fake):
        assert start(fake, {"topic": "cats", "n": 2}) == 0
        posts = [r for r in fake.requests if r["method"] == "POST"]
        assert [(p["path"], p["body"]) for p in posts] == [
            ("/api/runs", {"workflow": "wf", "inputs": {"topic": "cats", "n": 2}, "workspace_path": None}),
        ]

    def test_a_relative_workspace_is_sent_as_an_absolute_path(self, fake, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        start(fake, workspace="ws")
        assert fake.requests[0]["body"]["workspace_path"] == str(tmp_path / "ws")

    def test_prints_the_run_id_and_its_dashboard_link(self, fake, capsys):
        start(fake)
        out = capsys.readouterr().out
        assert RUN_ID in out
        assert LINK in out

    def test_the_link_and_server_come_from_the_environment(self, fake, monkeypatch, capsys):
        monkeypatch.setenv("TEMPER_SERVER_URL", fake.url + "/")
        monkeypatch.setenv("TEMPER_UI_URL", "https://dash.example.test/")
        assert run_on_server.run("wf", {}, sleep=lambda s: None) == 0
        assert f"https://dash.example.test/app/workflow/{RUN_ID}" in capsys.readouterr().out
        assert fake.seen("POST") == ["POST /api/runs"]

    def test_the_default_link_is_the_temper_dashboard(self, fake, capsys):
        start(fake, ui=None)
        assert f"https://temper.wai2shine.com/app/workflow/{RUN_ID}" in capsys.readouterr().out

    def test_the_api_token_goes_along_when_set(self, fake, monkeypatch):
        monkeypatch.setenv("TEMPER_API_TOKEN", "sekrit")
        start(fake)
        assert {r["authorization"] for r in fake.requests} == {"Bearer sekrit"}

    def test_no_token_no_authorization_header(self, fake):
        start(fake)
        assert {r["authorization"] for r in fake.requests} == {None}


class TestServerRefusesTheStart:
    def test_a_400_is_printed_in_one_line_and_nothing_is_followed(self, fake, capsys):
        fake.start_answer = (400, {"detail": "Workflow 'nope' not found\n  (searched configs/workflows)"})
        assert start(fake) == run_on_server.NOT_STARTED
        err = lines(capsys.readouterr().err)
        assert len(err) == 1
        assert "400" in err[0]
        assert "Workflow 'nope' not found (searched configs/workflows)" in err[0]
        assert fake.seen("GET") == []

    def test_a_422_list_of_problems_is_one_line_too(self, fake, capsys):
        fake.start_answer = (422, {"detail": [
            {"loc": ["body", "inputs"], "msg": "Input should be a valid dictionary", "type": "dict_type"},
            {"loc": ["body", "workflow"], "msg": "Field required", "type": "missing"},
        ]})
        assert start(fake) == run_on_server.NOT_STARTED
        err = lines(capsys.readouterr().err)
        assert len(err) == 1
        assert "422" in err[0]
        assert "inputs: Input should be a valid dictionary" in err[0]
        assert "workflow: Field required" in err[0]


# --- the server not answering: refuse, run nothing ------------------------------------------------


class TestServerNotAnswering:
    def test_refuses_with_one_plain_line_and_runs_nothing(self, capsys):
        url = dead_url()
        with (
            patch("temper_ai.stage.executor.execute_graph", side_effect=AssertionError("ran in the terminal")),
            patch("temper_ai.database.session.init_database", side_effect=AssertionError("opened a database")),
        ):
            code = run_on_server.run("wf", {}, server=url, ui=UI, sleep=lambda s: None)
        assert code == run_on_server.NOT_STARTED
        captured = capsys.readouterr()
        assert lines(captured.err) == [
            f"The temper server at {url} isn't answering; runs start only on the server "
            "so they show on the dashboard. Nothing was run.",
        ]
        assert captured.out == ""

    def test_the_whole_command_imports_no_runner_and_opens_no_database(self, tmp_path):
        """The real `temper` entry point in a fresh interpreter: nothing of the engine is even
        imported, no database is opened, and no data/dev.db appears where it was typed."""
        db = tmp_path / "would-be.db"
        script = textwrap.dedent(f"""
            import json, sys
            from temper_ai.cli.main import main
            sys.argv = ["temper", "run", "ci_slow", "-i", "seconds=5", "--server", {dead_url()!r}]
            try:
                main()
                code = None
            except SystemExit as exc:
                code = exc.code
            session = sys.modules.get("temper_ai.database.session")
            print(json.dumps({{
                "code": code,
                "engine": [m for m in ("temper_ai.stage.executor", "temper_ai.server", "temper_ai.runner")
                           if m in sys.modules],
                "database_opened": bool(session and session._db_manager is not None),
            }}))
        """)
        env = {k: v for k, v in os.environ.items()
               if k not in ("TEMPER_SERVER_URL", "TEMPER_UI_URL", "TEMPER_API_TOKEN")}
        env["TEMPER_DATABASE_URL"] = f"sqlite:///{db}"
        done = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=25, check=False)
        assert done.stdout.strip(), done.stderr
        assert json.loads(done.stdout.strip().splitlines()[-1]) == {
            "code": run_on_server.NOT_STARTED, "engine": [], "database_opened": False,
        }
        assert "isn't answering" in done.stderr
        assert "Nothing was run." in done.stderr
        assert not db.exists()
        assert not (tmp_path / "data").exists()


# --- following ----------------------------------------------------------------------------------


class TestFollow:
    def test_one_line_as_each_stage_starts_and_ends(self, fake, capsys):
        fake.records = [
            record("queued"),
            record("running", node("plan", "running")),
            record("running", node("plan", "completed", duration=2), node("write", "running")),
            record("running", node("plan", "completed", duration=2), node("write", "running")),
            record("completed", node("plan", "completed", duration=2), node("write", "completed", duration=65),
                   duration=70, cost=0.0),
        ]
        assert start(fake) == 0
        out = lines(capsys.readouterr().out)
        stage_lines = [line for line in out if line.split()[0] in ("started", "done")]
        assert stage_lines == ["started  plan", "done     plan (2s)", "started  write", "done     write (1m05s)"]
        assert out[-1] == f"Run completed in 1m10s, $0.00: {LINK}"

    def test_a_stage_seen_only_when_it_ended_gets_its_end_line(self, fake, capsys):
        fake.records = [record("completed", node("quick", "completed", duration=0.2), node("never", "skipped"),
                               duration=1)]
        start(fake)
        out = lines(capsys.readouterr().out)
        assert "done     quick (0s)" in out
        assert "skipped  never" in out
        assert not any(line.startswith("started") for line in out)

    def test_nested_stages_show_only_with_verbose(self, fake, capsys):
        fake.records = [record("completed", node("outer", "completed", node("inner", "completed")), duration=3)]
        start(fake)
        quiet = capsys.readouterr().out
        assert "outer" in quiet and "inner" not in quiet
        start(fake, verbose=1)
        loud = capsys.readouterr().out
        assert "inner" in loud
        inner_line = next(line for line in loud.splitlines() if "inner" in line)
        outer_line = next(line for line in loud.splitlines() if "outer" in line)
        assert len(inner_line) - len(inner_line.lstrip()) > len(outer_line) - len(outer_line.lstrip())

    def test_verbose_prints_the_output_at_the_end(self, fake, capsys):
        fake.records = [record("completed", duration=1, output={"answer": "forty-two"})]
        start(fake, verbose=1)
        assert "forty-two" in capsys.readouterr().out

    def test_waiting_on_you_is_printed_once_per_wait(self, fake, capsys):
        first = wait("ev-1", {"question": "Where should the data live?", "header": "Storage",
                              "options": [{"label": "Postgres"}]})
        second = wait("ev-2", "Ship it?")
        fake.records = [record("running", node("ask", "completed"), node("decide", "waiting"))] * 3 + [
            record("running", node("decide", "running")),
            record("running", node("decide", "running")),
            record("completed", node("decide", "completed"), duration=9),
        ]
        fake.waits = [[first], [first], [first], [second], [second], []]
        assert start(fake) == 0
        out = lines(capsys.readouterr().out)
        waiting = [line for line in out if line.startswith("waiting on you")]
        assert waiting == [
            "waiting on you: Where should the data live? Answer on the dashboard or in Slack/Telegram.",
            "waiting on you: Ship it? Answer on the dashboard or in Slack/Telegram.",
        ]
        # A stage waiting at its gate has not started; it starts when it is answered.
        assert [line for line in out if line.endswith("decide")] == ["started  decide", "done     decide"]

    def test_a_wait_with_no_question_names_its_step(self, fake, capsys):
        fake.records = [record("waiting"), record("cancelled", duration=1)]
        fake.waits = [[wait("ev-9", node_name="review")]]
        start(fake)
        assert "waiting on you: review needs your approval. Answer on the dashboard or in Slack/Telegram." in \
            lines(capsys.readouterr().out)

    def test_temper_run_never_answers_a_wait_itself(self, fake):
        fake.records = [record("waiting"), record("cancelled", duration=1)]
        fake.waits = [[wait("ev-3", "Approve?")]]
        start(fake)
        assert fake.seen("POST") == ["POST /api/runs"]

    @pytest.mark.parametrize(("status", "code"), [("completed", 0), ("failed", 1), ("cancelled", 2)])
    def test_exits_with_the_runs_outcome(self, fake, capsys, status, code):
        fake.records = [record("running"), record(status, duration=4, cost=0.5, error="boom" if status == "failed" else None)]
        assert start(fake) == code
        last = lines(capsys.readouterr().out)[-1]
        assert last.startswith(f"Run {status}")
        assert "$0.50" in last
        assert LINK in last
        if status == "failed":
            assert "boom" in last

    def test_an_unknown_status_is_not_an_ending(self, fake, capsys):
        fake.records = [record("interrupted"), record("interrupted"), record("completed", duration=2)]
        assert start(fake) == 0
        out = lines(capsys.readouterr().out)
        assert sum("interrupted" in line for line in out) == 1

    def test_detach_prints_the_link_and_returns_at_once(self, fake, capsys):
        fake.records = [record("running")]  # would follow forever
        assert start(fake, detach=True) == 0
        assert LINK in capsys.readouterr().out
        assert fake.seen() == ["POST /api/runs"]

    def test_ctrl_c_stops_following_and_leaves_the_run_alone(self, fake, capsys):
        fake.records = [record("running", node("plan", "running"))]

        def interrupted(seconds):
            raise KeyboardInterrupt

        assert start(fake, sleep=interrupted) == run_on_server.INTERRUPTED
        out = capsys.readouterr().out
        assert "Stopped following" in out
        assert "keeps going" in out
        assert LINK in out.splitlines()[-1]
        assert fake.seen("POST") == ["POST /api/runs"]  # no cancel

    def test_keeps_trying_while_the_server_is_away_then_gives_up(self, fake, capsys):
        fake.record_status = 503
        clock = itertools.count(0, 60)  # each look at the clock is a minute later
        assert start(fake, clock=lambda: next(clock)) == run_on_server.LOST
        out = capsys.readouterr().out
        assert out.count("isn't answering about the run") == 1
        assert "still trying" in out
        assert LINK in lines(out)[-1]
        assert fake.seen("POST") == ["POST /api/runs"]

    def test_a_short_outage_is_ridden_out(self, fake, capsys):
        fake.records = [record("running"), record("completed", duration=5)]
        fake.record_status = 502  # the first look fails; the server is back after the pause

        def sleep(seconds):
            fake.record_status = 200

        assert start(fake, sleep=sleep) == 0
        out = capsys.readouterr().out
        assert out.count("isn't answering about the run") == 1
        assert "answering again" in out
        assert lines(out)[-1].startswith("Run completed")


# --- the command line ---------------------------------------------------------------------------


def run_cli(*argv: str) -> int:
    with patch("sys.argv", ["temper", "run", *argv]), pytest.raises(SystemExit) as exc:
        main()
    return exc.value.code


class TestCommandLine:
    def test_temper_run_starts_on_the_server_and_follows(self, fake, monkeypatch, capsys):
        monkeypatch.setenv("TEMPER_UI_URL", UI)
        monkeypatch.setattr(run_on_server, "POLL_MIN_S", 0.0)
        fake.records = [record("running", node("only", "running")), record("completed", node("only", "completed"),
                                                                          duration=1)]
        assert run_cli("wf", "-i", "topic=cats", "-i", "n=2", "--server", fake.url) == 0
        assert fake.requests[0]["body"] == {"workflow": "wf", "inputs": {"topic": "cats", "n": 2},
                                            "workspace_path": None}
        assert LINK in capsys.readouterr().out

    def test_detach_from_the_command_line(self, fake, monkeypatch):
        monkeypatch.setenv("TEMPER_SERVER_URL", fake.url)
        assert run_cli("wf", "--detach") == 0
        assert fake.seen() == ["POST /api/runs"]

    @pytest.mark.parametrize(("flag", "says"), [
        (["--provider", "openai"], "agent or workflow config"),
        (["--model", "gpt-4o"], "agent or workflow config"),
        (["--config-dir", "/tmp/cfgs"], "~/temper-ai"),
        (["--no-db"], "dashboard"),
    ])
    def test_terminal_only_flags_are_refused_with_what_to_do_instead(self, fake, capsys, flag, says):
        assert run_cli("wf", *flag, "--server", fake.url) == run_on_server.NOT_STARTED
        err = lines(capsys.readouterr().err)
        assert len(err) == 1
        assert flag[0] in err[0]
        assert says in err[0]
        assert fake.requests == []

    def test_each_refused_flag_gets_its_own_line(self, fake, capsys):
        assert run_cli("wf", "--model", "x", "--no-db", "--server", fake.url) == run_on_server.NOT_STARTED
        err = lines(capsys.readouterr().err)
        assert len(err) == 2
        assert fake.requests == []

    def test_a_malformed_input_starts_nothing(self, fake, capsys):
        assert run_cli("wf", "-i", "no_equals_sign", "--server", fake.url) == run_on_server.NOT_STARTED
        assert "key=value" in capsys.readouterr().err
        assert fake.requests == []

    def test_help_says_the_server_runs_it_with_its_own_configs(self, capsys):
        assert run_cli("--help") == 0
        text = " ".join(capsys.readouterr().out.split())
        assert "temper server" in text
        assert "~/temper-ai" in text
        assert "--detach" in text
        for gone in ("--provider", "--model", "--config-dir", "--no-db"):
            assert gone not in text
