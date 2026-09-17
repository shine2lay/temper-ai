"""get_events: the ordering and timing record, kept cheap.

Events carry whole prompts and outputs in their data. The point of this tool
is that reading a timeline must not cost what reading the contents costs, so
the tests check the reduction as much as the retrieval.
"""

import datetime as dt

from temper_ai.database.session import get_session
from temper_ai.mcp.tools import TemperTools
from temper_ai.observability.models import Event


def _event(session, *, etype: str, status: str, seconds_ago: int, data: dict) -> None:
    session.add(
        Event(
            id=f"{etype}-{seconds_ago}",
            type=etype,
            execution_id="run-1",
            status=status,
            data=data,
            timestamp=dt.datetime.now(dt.UTC).replace(tzinfo=None)
            - dt.timedelta(seconds=seconds_ago),
        )
    )


def _seed() -> None:
    with get_session() as s:
        _event(s, etype="workflow.started", status="running", seconds_ago=30, data={"name": "wf"})
        _event(s, etype="agent.started", status="running", seconds_ago=20,
               data={"agent_name": "writer", "node_path": "draft"})
        _event(s, etype="agent.failed", status="failed", seconds_ago=10,
               data={"agent_name": "writer", "error": "boom", "duration_seconds": 9.5,
                     "prompt": "x" * 50_000})
        s.commit()


def test_returns_events_oldest_first_with_counts():
    _seed()
    out = TemperTools().get_events("run-1")
    assert [e["type"] for e in out["events"]] == [
        "workflow.started", "agent.started", "agent.failed",
    ]
    assert out["counts_by_type"]["agent.failed"] == 1
    assert out["returned"] == 3


def test_keeps_the_identifying_fields_and_drops_the_bulk():
    _seed()
    out = TemperTools().get_events("run-1")
    failed = [e for e in out["events"] if e["type"] == "agent.failed"][0]
    assert failed["agent_name"] == "writer"
    assert failed["error"] == "boom"
    assert failed["duration_seconds"] == 9.5
    # The 50k prompt must not come along for the ride.
    assert "prompt" not in failed
    assert len(str(out)) < 4_000


def test_filters_by_type_and_status():
    _seed()
    tools = TemperTools()
    assert [e["type"] for e in tools.get_events("run-1", event_type="agent.failed")["events"]] == [
        "agent.failed"
    ]
    assert all(e["status"] == "failed" for e in tools.get_events("run-1", status="failed")["events"])


def test_says_so_when_nothing_matches():
    _seed()
    out = TemperTools().get_events("run-1", event_type="tool.called")
    assert out["events"] == []
    assert "no events matched" in out["note"]


def test_reports_truncation():
    _seed()
    out = TemperTools().get_events("run-1", limit=2)
    assert out["returned"] == 2
    assert out["truncated"] is True
    # limit takes the most recent, so the oldest event is the one dropped.
    assert [e["type"] for e in out["events"]] == ["agent.started", "agent.failed"]
