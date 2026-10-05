"""A run's tool calls read back from the database itself: the database tier runs this on Postgres.

Postgres keeps \\u0000 in a json column but cannot turn it into text, and some tool calls
hold one (a Bash command or output with a NUL in it). GET /api/runs/<run>/tool-calls reads
the events whole and looks inside them in Python, and follows a call up to its agent
through the model calls' ids alone (event_parents), never their prompts.
"""

from __future__ import annotations

from temper_ai.api.data_service import get_tool_calls
from temper_ai.observability import record
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import event_parents

RUN = "run-with-a-nul"


def _event(kind: str, eid: str, parent: str | None = None, **data) -> None:
    record(EventType(kind), data=data, parent_id=parent, execution_id=RUN, status="completed", event_id=eid)


def test_a_run_whose_tool_calls_hold_a_nul_reads_back():
    _event("workflow.started", "wf", name="build")
    _event("stage.started", "st", parent="wf", name="implement")
    _event("agent.started", "a1", parent="st", agent_name="coder")
    _event("llm.call.started", "l1", parent="a1", messages=[{"role": "user", "content": "nul \x00 here"}])
    _event("tool.call.started", "t1", parent="l1", tool_name="Bash",
           input_params={"command": "printf 'a\x00b'", "cwd": "/w/repo"})
    _event("tool.call.completed", "t1-end", parent="l1", tool_name="Bash", output="a\x00b")
    _event("tool.blocked", "b1", parent="a1", tool_name="Read", reason="workspace_violation",
           error="Path '/etc/\x00' escapes workspace root '/w'.")

    result = get_tool_calls(RUN, contains=["printf", "/elsewhere/"])

    assert result is not None
    [call] = result["tool_calls"]
    assert (call["attempt_id"], call["round"], call["status"]) == ("a1", 1, "completed")
    assert (call["paths"], call["hits"]) == (["/w/repo"], ["printf"])
    assert [b["attempt_id"] for b in result["blocked"]] == ["a1"]


def test_event_parents_reads_ids_of_the_types_asked_for_only():
    _event("workflow.started", "wf", name="build")
    _event("agent.started", "a1", parent="wf", agent_name="coder")
    _event("llm.call.started", "l1", parent="a1", messages=[{"role": "user", "content": "\x00"}])
    _event("llm.call.completed", "l1-end", parent="a1")
    record(EventType.LLM_CALL_STARTED, data={}, parent_id="x", execution_id="another-run", event_id="l9")

    assert event_parents(RUN, ("llm.call.started",)) == {"l1": "a1"}
    assert event_parents(RUN, ("llm.",)) == {"l1": "a1", "l1-end": "a1"}
    assert get_tool_calls("no-such-run") is None
