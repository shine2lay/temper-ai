"""A tool call's start is paired with *its* completion, not the first one by name.

Matching by tool_name alone handed the first completion to every same-named
start: an agent that called browser_extract twice under one LLM call showed
both calls with the first result and the first duration. Starts and
completions now carry a call_id and are paired on it; events recorded
before call ids existed still pair by name, but each completion is used once.
"""

from temper_ai.api.data_service import (
    _build_tool_call,
    _clear_children_index,
    _set_children_index,
)


def _ev(eid, etype, status, data, parent="llm-1", ts="2026-09-17T00:00:0"):
    return {"id": eid, "type": etype, "status": status, "parent_id": parent, "data": data, "timestamp": ts + eid[-1]}


def test_same_tool_twice_pairs_each_start_with_its_own_completion():
    events = [
        _ev("s1", "tool.call.started", "running", {"tool_name": "browser_extract", "call_id": "a", "transport": "mcp", "server": "browser"}),
        _ev("s2", "tool.call.started", "running", {"tool_name": "browser_extract", "call_id": "b", "transport": "mcp", "server": "browser"}),
        _ev("c1", "tool.call.completed", "completed", {"tool_name": "browser_extract", "call_id": "a", "duration_ms": 100, "output": "first page"}),
        _ev("c2", "tool.call.completed", "completed", {"tool_name": "browser_extract", "call_id": "b", "duration_ms": 900, "output": "second page"}),
    ]
    _set_children_index(events)
    try:
        first = _build_tool_call(events[0], events)
        second = _build_tool_call(events[1], events)
    finally:
        _clear_children_index()
    assert first["output_data"] == "first page" and first["duration_seconds"] == 0.1
    assert second["output_data"] == "second page" and second["duration_seconds"] == 0.9


def test_labels_survive_into_the_api_shape():
    events = [
        _ev("s1", "tool.call.started", "running", {"tool_name": "browser_status", "call_id": "a", "transport": "mcp", "server": "browser", "executed_by": "claude"}),
        _ev("c1", "tool.call.completed", "completed", {"tool_name": "browser_status", "call_id": "a", "duration_ms": 50, "output": "{}"}),
    ]
    _set_children_index(events)
    try:
        call = _build_tool_call(events[0], events)
    finally:
        _clear_children_index()
    assert call["transport"] == "mcp"
    assert call["server"] == "browser"
    assert call["executed_by"] == "claude"
    assert call["call_id"] == "a"
    assert call["status"] == "completed"


def test_legacy_events_without_call_ids_still_pair_but_each_completion_once():
    events = [
        _ev("s1", "tool.call.started", "running", {"tool_name": "Bash"}),
        _ev("s2", "tool.call.started", "running", {"tool_name": "Bash"}),
        _ev("c1", "tool.call.completed", "completed", {"tool_name": "Bash", "duration_ms": 10, "output": "one"}),
        _ev("c2", "tool.call.failed", "failed", {"tool_name": "Bash", "duration_ms": 20, "error": "boom"}),
    ]
    _set_children_index(events)
    try:
        first = _build_tool_call(events[0], events)
        second = _build_tool_call(events[1], events)
    finally:
        _clear_children_index()
    assert first["output_data"] == "one"
    assert second["status"] == "failed" and second["error_message"] == "boom"
