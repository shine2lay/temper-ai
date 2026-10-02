"""A script agent's live log, end to end through the real Bash tool: what the script prints is saved
under the attempt while it runs, and the agent's result, JSON hand-off and events stay as they were.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.observability.event_types import EventType


class Recorder:
    """The parts of EventRecorder a script agent uses: events, and its log's rows."""

    def __init__(self):
        self.events: list[dict] = []
        self.rows: dict[str, list[tuple[int, dict]]] = {}
        self.first_row_at: dict[str, float] = {}
        self.lock = threading.Lock()

    def record(self, event_type, data=None, parent_id=None, execution_id=None, status=None, event_id=None):
        eid = event_id or str(uuid.uuid4())
        with self.lock:
            self.events.append({"type": str(event_type), "data": dict(data or {}), "parent_id": parent_id,
                                "execution_id": execution_id, "status": status, "id": eid})
        return eid

    def record_script_log_rows(self, attempt_id, rows, execution_id=None):
        with self.lock:
            self.first_row_at.setdefault(attempt_id, time.monotonic())
            self.rows.setdefault(attempt_id, []).extend(rows)
        return [f"{attempt_id}.log.{seq:08d}" for seq, _ in rows]

    def started(self) -> list[dict]:
        return [e for e in self.events if e["type"] == str(EventType.AGENT_STARTED)]

    def ended(self, attempt: str) -> dict:
        [event] = [e for e in self.events if e["parent_id"] == attempt
                   and e["type"] in (str(EventType.AGENT_COMPLETED), str(EventType.AGENT_FAILED))]
        return event

    def entries(self, attempt: str) -> list[dict]:
        return [e for _, data in self.rows.get(attempt, []) for e in data["entries"]]

    def text(self, attempt: str, stream: str | None = None) -> str:
        return "".join(e["text"] for e in self.entries(attempt)
                       if e["stream"] != "temper" and (stream is None or e["stream"] == stream))

    def end_note(self, attempt: str) -> dict:
        note = self.entries(attempt)[-1]
        assert note["stream"] == "temper" and note["kind"] == "end"
        return note


def _context(tmp_path, recorder: Recorder, cancel: threading.Event | None = None):
    from temper_ai.tools.bash import Bash
    from temper_ai.tools.executor import ToolExecutor

    executor = ToolExecutor(workspace_root=str(tmp_path))
    executor.register_tools({"Bash": Bash(config={"workspace_root": str(tmp_path)})})
    if cancel is not None:
        executor.cancel_event = cancel
    ctx = MagicMock()
    ctx.run_id = "run-log"
    ctx.node_path = "talk"
    ctx.agent_name = "talker"
    ctx.workspace_path = str(tmp_path)
    ctx.skip_policies = None
    ctx.parent_event_id = None
    ctx.tool_executor = executor
    ctx.event_recorder = recorder
    return ctx


def _agent(script: str, **config) -> ScriptAgent:
    return ScriptAgent(config={"name": "talker", "script_template": script, **config})


TALKER = (
    "echo 'step 1'; sleep 0.8; echo 'careful' >&2; printf 'half a line, '; sleep 0.2; "
    "echo 'then the rest'; echo '{\"answer\": 42}'"
)


def test_the_log_is_saved_while_the_script_runs_and_the_result_is_unchanged(tmp_path):
    rec = Recorder()
    t0 = time.monotonic()
    result = _agent(TALKER).run({}, _context(tmp_path, rec))
    ended = time.monotonic()
    [started] = rec.started()
    attempt = started["id"]

    # The result, and the hand-off, are what they were before scripts had logs.
    assert result.status.value == "completed"
    assert result.output == "step 1\nhalf a line, then the rest\n{\"answer\": 42}\n\nSTDERR:\ncareful\n"
    assert result.structured_output == {"answer": 42}

    # The log: each stream labelled, saved while the script ran, ended with how it ended.
    assert rec.text(attempt, "stdout") == "step 1\nhalf a line, then the rest\n{\"answer\": 42}\n"
    assert rec.text(attempt, "stderr") == "careful\n"
    assert ended - rec.first_row_at[attempt] >= 0.5, "nothing was saved before the script ended"
    assert rec.end_note(attempt)["text"] == "[finished: exit code 0]"
    assert rec.rows[attempt][-1][1]["end"] == {"outcome": "completed", "exit_code": 0}
    assert [seq for seq, _ in rec.rows[attempt]] == list(range(1, len(rec.rows[attempt]) + 1))
    assert all(data["attempt_id"] == attempt for _, data in rec.rows[attempt])
    assert t0 < rec.first_row_at[attempt]

    # The completion carries the log's figures beside the output, never inside it.
    done = rec.ended(attempt)
    assert done["data"]["log"]["complete"] is True
    assert done["data"]["log"]["saved_bytes"] == len((rec.text(attempt)).encode())
    assert done["data"]["output"] == result.output
    assert done["data"]["structured_output"] == {"answer": 42}


def test_a_failed_script_keeps_its_output_and_its_exit_code(tmp_path):
    rec = Recorder()
    result = _agent("echo 'working'; echo 'it broke' >&2; exit 3").run({}, _context(tmp_path, rec))
    attempt = rec.started()[0]["id"]
    assert result.status.value == "failed"
    assert rec.text(attempt) == "working\nit broke\n"
    assert rec.end_note(attempt)["text"] == "[failed: exit code 3]"
    assert rec.ended(attempt)["data"]["log"]["complete"] is True


def test_a_timed_out_script_keeps_what_it_printed(tmp_path):
    rec = Recorder()
    result = _agent("echo 'before the wait'; sleep 30", timeout_seconds=1).run({}, _context(tmp_path, rec))
    attempt = rec.started()[0]["id"]
    assert result.status.value == "failed"
    assert "timed out" in (result.error or "").lower()
    assert rec.text(attempt) == "before the wait\n"
    assert rec.end_note(attempt)["text"] == "[timed out after 1s: stopped, with everything it started]"
    assert rec.rows[attempt][-1][1]["end"] == {"outcome": "timed_out"}


def test_a_cancelled_script_keeps_what_it_printed(tmp_path):
    rec = Recorder()
    cancel = threading.Event()
    ctx = _context(tmp_path, rec, cancel)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(_agent("echo 'started'; sleep 30", timeout_seconds=60).run, {}, ctx)
        deadline = time.monotonic() + 10
        while not rec.rows and time.monotonic() < deadline:
            time.sleep(0.05)
        cancel.set()
        result = future.result(timeout=15)
    attempt = rec.started()[0]["id"]
    assert result.status.value == "failed"
    assert rec.text(attempt) == "started\n"
    assert rec.end_note(attempt)["text"] == "[cancelled: the run was stopped]"


def test_the_log_limit_does_not_touch_the_result(tmp_path):
    rec = Recorder()
    agent = _agent("python3 -c 'print(\"x\" * 100)'; echo '{\"done\": true}'", log_max_bytes=10)
    result = agent.run({}, _context(tmp_path, rec))
    attempt = rec.started()[0]["id"]
    assert result.output == "x" * 100 + "\n{\"done\": true}\n"
    assert result.structured_output == {"done": True}
    assert rec.text(attempt) == "x" * 10
    kinds = [e.get("kind") for e in rec.entries(attempt) if e["stream"] == "temper"]
    assert kinds == ["truncated", "end"]
    summary = rec.ended(attempt)["data"]["log"]
    assert (summary["saved_bytes"], summary["limit"], summary["truncated"]) == (10, 10, True)
    assert rec.started()[0]["data"]["agent_config"]["agent"]["log_max_bytes"] == 10


def test_an_invalid_log_limit_is_a_config_error():
    errors = _agent("echo hi", log_max_bytes=-5).validate_config()
    assert any("log_max_bytes" in e for e in errors)


def test_two_attempts_with_one_name_at_once_have_their_own_logs(tmp_path):
    rec = Recorder()
    ctx = _context(tmp_path, rec)

    def run(word: str):
        return _agent(f"for i in 1 2 3; do echo {word}$i; sleep 0.2; done").run({}, ctx)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, ["a", "b"]))
    assert {r.output for r in results} == {"a1\na2\na3\n", "b1\nb2\nb3\n"}
    attempts = [e["id"] for e in rec.started()]
    assert len(set(attempts)) == 2
    assert sorted(rec.text(a) for a in attempts) == ["a1\na2\na3\n", "b1\nb2\nb3\n"]


def test_without_an_attempt_id_there_is_no_log_and_nothing_changes(tmp_path):
    """A context whose recorder hands back no usable id (a test double) runs the script as before."""
    ctx = _context(tmp_path, Recorder())
    ctx.event_recorder = MagicMock()
    result = _agent("echo plain").run({}, ctx)
    assert result.output == "plain\n"
    ctx.event_recorder.record_script_log_rows.assert_not_called()
