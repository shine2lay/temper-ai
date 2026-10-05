"""GET /api/runs/<run>/tool-calls: a run's tool calls and the files they named, never their contents.

A script step auditing its own run (did any builder or grader read outside its folder?) has
no database: it reads this. Each call says which attempt made it, the agent, node and round
as the agent index numbers them, the tool, its status and the paths it named. `contains=`
says which of the given strings a call's inputs hold, because a Bash `cat` names no path
key. Nothing a call was given beyond its paths ever comes back: no Write content, no Edit
strings, no Bash command, no output.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.observability import record
from temper_ai.observability.event_types import EventType
from temper_ai.stage.loader import GraphLoader

RUN = "run-tool-calls"
URL = f"/api/runs/{RUN}/tool-calls"


@pytest.fixture
def client():
    store = ConfigStore()
    init_app_state(AppState(
        config_store=store,
        graph_loader=GraphLoader(store),
        llm_providers={"mock": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    ))
    from temper_ai.server import app
    return TestClient(app)


def _event(kind: str, eid: str, parent: str | None = None, status: str = "running", **data) -> str:
    return record(EventType(kind), data=data, parent_id=parent, execution_id=RUN, status=status, event_id=eid)


def _agent(eid: str, stage: str, name: str, *, step: str = "implement") -> None:
    _event("stage.started", stage, parent="wf", status="completed", name=step)
    _event("agent.started", eid, parent=stage, status="completed", agent_name=name)


def _call(eid: str, model_call: str, tool: str, params: dict, *, end: str | None = "completed",
          call_id: str | None = None, agent: str = "coder", output: str = "done") -> None:
    """A tool call as temper records it: its start, then (unless cut off) its end."""
    ids = {"call_id": call_id} if call_id else {}
    _event("tool.call.started", eid, parent=model_call, tool_name=tool, input_params=params,
           agent_name=agent, executed_by="temper", **ids)
    if end == "completed":
        _event("tool.call.completed", f"{eid}-end", parent=model_call, status="completed",
               tool_name=tool, output=output, **ids)
    elif end == "failed":
        _event("tool.call.failed", f"{eid}-end", parent=model_call, status="failed",
               tool_name=tool, error="it broke", **ids)


def _calls(client, **params) -> list[dict]:
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()["tool_calls"]


def test_each_call_names_its_attempt_and_round_through_loops_and_a_resume(client):
    _event("workflow.started", "wf", status="failed", name="build")
    _agent("a1", "st1", "coder")
    _event("llm.call.started", "l1", parent="a1", iteration=1)
    _call("t1", "l1", "Read", {"path": "src/app.py", "offset": 10})
    _agent("a2", "st2", "coder")  # the loop's second round
    _event("llm.call.started", "l2", parent="a2", iteration=1)
    _call("t2", "l2", "Grep", {"pattern": "def main", "path": "src"})
    _event("workflow.started", "wf-resumed", status="completed", name="build")
    _event("stage.started", "st3", parent="wf-resumed", status="completed", name="implement")
    _event("agent.started", "a3", parent="st3", status="completed", agent_name="coder")
    _event("llm.call.started", "l3", parent="a3", iteration=1)
    _call("t3", "l3", "Read", {"file_path": "/repo/README.md"})

    calls = _calls(client)

    assert [(c["attempt_id"], c["agent_name"], c["node_name"], c["round"], c["tool_name"], c["paths"])
            for c in calls] == [
        ("a1", "coder", "implement", 1, "Read", ["src/app.py"]),
        ("a2", "coder", "implement", 2, "Grep", ["src"]),
        ("a3", "coder", "implement", 3, "Read", ["/repo/README.md"]),
    ]
    # The same attempts and rounds the agent index (and so the run page) gives.
    agents = client.get(f"/api/workflows/{RUN}/agents").json()["agents"]
    assert [(a["id"], a["round"]) for a in agents] == [("a1", 1), ("a2", 2), ("a3", 3)]
    assert all(c["executed_by"] == "temper" and c["hits"] == [] for c in calls)


def test_a_call_whose_chain_breaks_keeps_its_own_agent_and_node_but_no_attempt(client):
    _event("workflow.started", "wf", name="build")
    _call("t1", "a-model-call-nobody-recorded", "Read", {"path": "x.py"})

    [call] = _calls(client)

    assert call["attempt_id"] is None and call["round"] is None
    assert call["agent_name"] == "coder" and call["paths"] == ["x.py"]


def test_paths_come_from_the_path_keys_only_in_order_and_once(client):
    _event("workflow.started", "wf", name="build")
    _agent("a1", "st1", "coder")
    _event("llm.call.started", "l1", parent="a1", iteration=1)
    _call("t1", "l1", "Odd", {"worktree": "/w", "cwd": "/w", "filename": ["a.png", "b.png"],
                             "path": "p", "file_path": "p", "notebook_path": "n.ipynb",
                             "pattern": "not/a/path/key", "target": "/not/either"})
    _call("t2", "l1", "Bash", {"command": "ls /somewhere"})

    calls = _calls(client)

    assert calls[0]["paths"] == ["p", "n.ipynb", "a.png", "b.png", "/w"]
    assert calls[1]["paths"] == []


def test_contains_finds_a_hidden_file_a_bash_command_reads(client):
    _event("workflow.started", "wf", name="build")
    _agent("a1", "st1", "grader")
    _event("llm.call.started", "l1", parent="a1", iteration=1)
    _call("t1", "l1", "Bash", {"command": "cat /app/workspaces/epd/rollcall/bets/b037/outcome.md"})
    _call("t2", "l1", "Read", {"path": "notes.md"})

    marked = _calls(client, contains=["/epd/rollcall/bets/", "outcome.md", "/repos/rollcall/main"])
    unmarked = _calls(client)

    assert [c["hits"] for c in marked] == [["/epd/rollcall/bets/", "outcome.md"], []]
    assert [c["hits"] for c in unmarked] == [[], []]
    assert marked[0]["paths"] == []


def test_no_content_a_call_was_given_or_gave_back_is_in_the_response(client):
    _event("workflow.started", "wf", name="build")
    _agent("a1", "st1", "coder")
    _event("llm.call.started", "l1", parent="a1", iteration=1,
           messages=[{"role": "user", "content": "PROMPT-a61f"}])
    _call("t1", "l1", "Write", {"path": "notes.md", "content": "WRITE-CONTENT-7f3a"})
    _call("t2", "l1", "Edit", {"path": "app.py",
                               "edits": [{"old_text": "EDIT-OLD-91c2", "new_text": "EDIT-NEW-4d8e"}]})
    _call("t3", "l1", "Bash", {"command": "echo BASH-COMMAND-55aa", "timeout": 30},
          output="OUTPUT-0b1e")

    response = client.get(URL, params={"contains": ["/nowhere/"]})

    assert response.status_code == 200
    assert [c["paths"] for c in response.json()["tool_calls"]] == [["notes.md"], ["app.py"], []]
    for secret in ("WRITE-CONTENT-7f3a", "EDIT-OLD-91c2", "EDIT-NEW-4d8e", "BASH-COMMAND-55aa",
                   "OUTPUT-0b1e", "PROMPT-a61f", "content", "command", "edits"):
        assert secret not in response.text


def test_status_comes_from_the_calls_own_end(client):
    _event("workflow.started", "wf", name="build")
    _agent("a1", "st1", "coder")
    _event("llm.call.started", "l1", parent="a1", iteration=1)
    # A provider ran two Reads at once; the second ended first. Paired by call_id, not by name.
    _event("tool.call.started", "p1", parent="l1", tool_name="Read", call_id="toolu_1",
           input_params={"file_path": "a.py"}, executed_by="claude-code")
    _event("tool.call.started", "p2", parent="l1", tool_name="Read", call_id="toolu_2",
           input_params={"file_path": "b.py"}, executed_by="claude-code")
    _event("tool.call.completed", "p2-end", parent="l1", status="completed", tool_name="Read",
           call_id="toolu_2", output="b")
    _event("tool.call.failed", "p1-end", parent="l1", status="failed", tool_name="Read",
           call_id="toolu_1", error="no such file")
    # Temper's own calls carry no call_id: one at a time, each start takes the next end.
    _event("llm.call.started", "l2", parent="a1", iteration=2)
    _call("t1", "l2", "Bash", {"command": "true"}, end="completed")
    _call("t2", "l2", "Bash", {"command": "false"}, end="failed")
    _call("t3", "l2", "Bash", {"command": "sleep 99"}, end=None)
    # A Pi agent's tool hangs right under its agent.
    _event("tool.call.started", "pi1", parent="a1", tool_name="read", call_id="pi:s:x:1",
           input_params={"path": "c.py"}, executed_by="pi")
    _event("tool.call.completed", "pi1-end", parent="a1", status="completed", tool_name="read",
           call_id="pi:s:x:1", output="c")

    calls = _calls(client)

    assert [(c["call_id"], c["status"], c["attempt_id"]) for c in calls] == [
        ("toolu_1", "failed", "a1"),
        ("toolu_2", "completed", "a1"),
        (None, "completed", "a1"),
        (None, "failed", "a1"),
        (None, "running", "a1"),
        ("pi:s:x:1", "completed", "a1"),
    ]
    assert [c["executed_by"] for c in calls] == ["claude-code", "claude-code", "temper", "temper", "temper", "pi"]


def test_refused_calls_are_listed_with_their_attempt(client):
    _event("workflow.started", "wf", name="build")
    # A script agent tells the executor its attempt: the refusal hangs under it.
    _agent("s1", "st1", "prepare", step="prepare")
    _event("tool.blocked", "b1", parent="s1", status="blocked", tool_name="Read",
           reason="workspace_violation", error="Path '/etc/hosts' escapes workspace root '/w'.")
    # An LLM agent's executor is told nothing: the refusal is placed in the call it refused.
    _agent("a1", "st2", "coder")
    _event("llm.call.started", "l1", parent="a1", iteration=1)
    _event("tool.call.started", "t1", parent="l1", tool_name="Read",
           input_params={"path": "/app/configs/x.yaml"}, agent_name="coder")
    _event("tool.blocked", "b2", status="blocked", tool_name="Read", reason="workspace_violation",
           error="Path '/app/configs/x.yaml' escapes workspace root '/app/workspaces'.")
    _event("tool.call.completed", "t1-end", parent="l1", status="completed", tool_name="Read",
           output="Error: Path '/app/configs/x.yaml' escapes workspace root '/app/workspaces'.")
    _event("tool.blocked", "b3", status="blocked", tool_name="Glob", reason="not_declared_by_caller",
           agent_name="coder", declared=["Read"])

    body = client.get(URL).json()

    assert body["blocked"] == [
        {"attempt_id": "s1", "agent_name": "prepare", "round": 1, "tool_name": "Read",
         "reason": "workspace_violation", "error": "Path '/etc/hosts' escapes workspace root '/w'."},
        {"attempt_id": "a1", "agent_name": "coder", "round": 1, "tool_name": "Read",
         "reason": "workspace_violation",
         "error": "Path '/app/configs/x.yaml' escapes workspace root '/app/workspaces'."},
        # No open Glob call to place it in: its own agent name, no attempt.
        {"attempt_id": None, "agent_name": "coder", "round": None, "tool_name": "Glob",
         "reason": "not_declared_by_caller", "error": None},
    ]
    assert body["counts"] == {"tool_calls": 1, "blocked": 3}


def test_a_refusal_two_attempts_could_have_made_names_neither(client):
    _event("workflow.started", "wf", name="build")
    _agent("a1", "st1", "coder")
    _agent("a2", "st2", "tester", step="test")
    _event("llm.call.started", "l1", parent="a1", iteration=1)
    _event("llm.call.started", "l2", parent="a2", iteration=1)
    _event("tool.call.started", "t1", parent="l1", tool_name="Read", input_params={"path": "/x"})
    _event("tool.call.started", "t2", parent="l2", tool_name="Read", input_params={"path": "/y"})
    _event("tool.blocked", "b1", status="blocked", tool_name="Read", reason="workspace_violation",
           error="Path '/x' escapes workspace root '/w'.")
    _event("tool.call.completed", "t1-end", parent="l1", status="completed", tool_name="Read", output="x")
    _event("tool.call.completed", "t2-end", parent="l2", status="completed", tool_name="Read", output="y")

    [refused] = client.get(URL).json()["blocked"]

    assert (refused["attempt_id"], refused["agent_name"], refused["round"]) == (None, None, None)


def test_every_call_of_a_run_longer_than_the_run_pages_cap(client, monkeypatch):
    monkeypatch.setattr("temper_ai.api.data_service.MAX_CALL_EVENTS", 4)
    _event("workflow.started", "wf", name="build")
    _agent("a1", "st1", "coder")
    for i in range(6):
        _event("llm.call.started", f"l{i}", parent="a1", iteration=i)
        _call(f"t{i}", f"l{i}", "Read", {"path": f"f{i}.py"})

    body = client.get(URL).json()

    assert body["counts"]["tool_calls"] == 6
    assert [c["paths"] for c in body["tool_calls"]] == [[f"f{i}.py"] for i in range(6)]
    assert {c["attempt_id"] for c in body["tool_calls"]} == {"a1"}


def test_an_event_holding_a_nul_still_loads(client):
    # Postgres stores \u0000 in a json column but cannot turn it into text: reading in
    # Python is what keeps such a run readable.
    _event("workflow.started", "wf", name="build")
    _agent("a1", "st1", "coder")
    _event("llm.call.started", "l1", parent="a1", iteration=1)
    _call("t1", "l1", "Bash", {"command": "printf 'a\x00b' | tr '\\0' x"}, output="a\x00b")
    _call("t2", "l1", "Read", {"path": "ok.py"})

    calls = _calls(client, contains=["printf"])

    assert [(c["paths"], c["hits"]) for c in calls] == [([], ["printf"]), (["ok.py"], [])]


@pytest.mark.parametrize("contains", [
    [f"marker-{i}" for i in range(21)],
    ["x" * 301],
    [""],
])
def test_too_many_or_too_long_or_empty_strings_are_refused(client, contains):
    _event("workflow.started", "wf", name="build")

    assert client.get(URL, params={"contains": contains}).status_code == 400


def test_twenty_strings_of_three_hundred_characters_are_fine(client):
    _event("workflow.started", "wf", name="build")

    response = client.get(URL, params={"contains": [f"{i:03d}" + "x" * 297 for i in range(20)]})

    assert response.status_code == 200
    assert response.json() == {"execution_id": RUN, "tool_calls": [], "blocked": [],
                               "counts": {"tool_calls": 0, "blocked": 0}}


def test_an_unknown_run_is_not_found(client):
    assert client.get("/api/runs/no-such-run/tool-calls").status_code == 404


def test_the_route_is_behind_the_token_like_the_rest_of_a_run(client, monkeypatch):
    _event("workflow.started", "wf", name="build")
    monkeypatch.setenv("TEMPER_API_TOKEN", "secret-for-this-test")

    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={"Authorization": "Bearer secret-for-this-test"}).status_code == 200
