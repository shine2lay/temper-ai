"""Replay A2's captured Pi streams through Temper's real recording and live-view path.

The captures (fixtures/pi_a2) are real Pi 0.87.1 RPC output from scripted, offline model
calls, with Pi's system message removed. Replaying one records the run in the database
Temper reads from (``get_workflow_execution``) and sends it through the real
``WebSocketManager``, so the page's store can be tested on exactly what a browser receives.

Also a script: ``python -m tests.test_llm.pi_a2_replay --write <dir>`` writes the live
messages and snapshots of every scenario as JSON for the frontend tests (in-memory SQLite).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from temper_ai.llm.pi_stream import (
    JsonlSplitter,
    PiEventMapper,
    Redactor,
    record_outcome,
)
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.pi_agent.turn import ChunkSink

FIXTURES = Path(__file__).parent / "fixtures" / "pi_a2"
SCENARIOS = ("s1_stream", "s2_errors", "s3_large_untrusted", "s4_retry_recover", "s5_retry_fail",
             "s6_abort", "s7_compaction")
SECRET = "A2-SYNTH-SECRET-8c41f2d9"  # synthetic; planted in the scripted tool calls and thinking
SYSTEM_MARKER = "A2-FIXTURE: system message removed"
RESULT_SCHEMA = {"required": ["status", "ticks"],
                 "properties": {"status": {"type": "string"}, "ticks": {"type": "integer"}}}
# Where a page joins (or reconnects) halfway: after this many Pi events.
MID_CUT = {"s1_stream": 30, "s2_errors": 20, "s3_large_untrusted": 300, "s4_retry_recover": 12,
           "s5_retry_fail": 10, "s6_abort": 10, "s7_compaction": 14}


def raw_bytes(name: str) -> bytes:
    return (FIXTURES / f"{name}.jsonl").read_bytes()


def load_events(name: str, piece: int = 7) -> list[dict]:
    """Parse a capture the way a worker reads a pipe: in small pieces."""
    data = raw_bytes(name)
    splitter = JsonlSplitter()
    out: list[dict] = []
    for i in range(0, len(data), piece):
        out.extend(splitter.feed(data[i:i + piece]))
    splitter.finish()
    return out


class Run:
    """One Temper run holding one Pi agent, with stable ids."""

    def __init__(self, name: str, notifier: Any = None, execution_id: str | None = None):
        self.name = name
        self.execution_id = execution_id or f"a2-{name}"
        self.recorder = EventRecorder(self.execution_id, notifier=notifier)
        self.workflow_id = f"{self.execution_id}-wf"
        self.stage_id = f"{self.execution_id}-stage"
        self.agent_id = f"{self.execution_id}-agent"

    def start(self) -> None:
        r = self.recorder
        r.record(EventType.WORKFLOW_STARTED, data={"name": "pi-a2", "workflow_name": "pi-a2"},
                 execution_id=self.execution_id, status="running", event_id=self.workflow_id)
        r.record(EventType.STAGE_STARTED, data={"name": "pi", "stage_name": "pi"}, parent_id=self.workflow_id,
                 execution_id=self.execution_id, status="running", event_id=self.stage_id)
        # As the Pi step records a turn's start: the page reads it as a Pi agent.
        r.record(EventType.AGENT_STARTED, data={"agent_name": "pi-agent", "name": "pi-agent", "type": "pi",
                                                "executed_by": "pi", "agent_config": {"type": "pi"}},
                 parent_id=self.stage_id, execution_id=self.execution_id, status="running",
                 event_id=self.agent_id)

    def mapper(self, known: tuple[str, ...] = ()) -> PiEventMapper:
        # The Pi step writes through ChunkSink: Temper's chunk plumbing is unchanged, so
        # live chunks carry no seq (the page settles calls from their stored finals).
        return PiEventMapper(ChunkSink(self.recorder), execution_id=self.execution_id, agent_event_id=self.agent_id,
                             agent_name="pi-agent", session_id=f"session-{self.name}", node_path="pi",
                             redactor=Redactor([SECRET]), known_event_ids=known)

    def finish(self, mapper: PiEventMapper, schema: dict | None = None):
        outcome = mapper.finish(result_schema=schema)
        record_outcome(self.recorder, mapper, outcome)
        failed = outcome.status != "completed"
        status = "failed" if failed else "completed"
        self.recorder.record(EventType.STAGE_FAILED if failed else EventType.STAGE_COMPLETED,
                             data={"name": "pi", "error": outcome.error}, parent_id=self.stage_id,
                             execution_id=self.execution_id, status=status,
                             event_id=f"{self.stage_id}-end")
        self.recorder.record(EventType.WORKFLOW_FAILED if failed else EventType.WORKFLOW_COMPLETED,
                             data={"name": "pi-a2", "error": outcome.error}, parent_id=self.workflow_id,
                             execution_id=self.execution_id, status=status, event_id=f"{self.workflow_id}-end")
        return outcome


def schema_for(name: str) -> dict | None:
    return RESULT_SCHEMA if name in ("s1_stream", "s2_errors") else None


class FakeSocket:
    """Stands in for a browser: keeps every message the manager sends, in order."""

    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, data: dict) -> None:
        # Through JSON, as on the wire.
        self.messages.append(json.loads(json.dumps(data, default=str)))


async def _settle() -> None:
    # Sends are scheduled on the loop; chunk batches flush after CHUNK_FLUSH_MS.
    for _ in range(3):
        await asyncio.sleep(0.08)


async def view_fixture_async(name: str) -> dict:
    from temper_ai.api.data_service import get_workflow_execution
    from temper_ai.api.websocket import WebSocketManager

    manager = WebSocketManager()
    run = Run(name, notifier=manager)
    sock = FakeSocket()
    manager._connections[run.execution_id] = [sock]  # a connected page, without Redis or a server
    events = load_events(name)
    run.start()
    await _settle()
    # A page that opens the run now: this snapshot, then every message after start_index.
    start_index = len(sock.messages)
    start = get_workflow_execution(run.execution_id)
    mapper = run.mapper()
    cut = MID_CUT[name]
    mapper.handle_all(events[:cut])
    await _settle()
    mid_index = len(sock.messages)
    mid = get_workflow_execution(run.execution_id)
    mapper.handle_all(events[cut:])
    outcome = run.finish(mapper, schema_for(name))
    await _settle()
    final = get_workflow_execution(run.execution_id)
    return {
        "scenario": name,
        "agent_id": run.agent_id,
        "live": sock.messages,
        "start": {"index": start_index, "snapshot": start},
        "mid": {"index": mid_index, "snapshot": mid},
        "final": final,
        "outcome": {"status": outcome.status, "errors": outcome.errors, "tokens": outcome.tokens,
                    "structured_output": outcome.structured_output},
    }


def view_fixture(name: str) -> dict:
    return asyncio.run(view_fixture_async(name))


def shape(fixture: dict) -> dict:
    """What must not drift between the backend and the frontend fixtures (no clock values)."""
    live = []
    for m in fixture["live"]:
        d = m.get("data") or {}
        if m.get("event_type") == "llm_stream_batch":
            live.extend(("chunk", c.get("call_id"), c.get("seq"), c.get("chunk_type"), c.get("content"),
                         c.get("done")) for c in d.get("chunks", []))
        else:
            live.append(("event", m.get("event_type"), d.get("event_id"), d.get("status"),
                         d.get("response_content"), d.get("output"), d.get("error")))

    def agents(wf):
        out = []
        for node in (wf or {}).get("nodes") or []:
            for a in node.get("agents") or ([node["agent"]] if node.get("agent") else []):
                out.append((a.get("status"), a.get("error_message"),
                            [(c.get("id"), c.get("status"), c.get("response"), c.get("thinking"),
                              c.get("error_message"), c.get("total_tokens")) for c in a.get("llm_calls") or []],
                            [(t.get("id"), t.get("call_id"), t.get("status"), t.get("output_data"),
                              t.get("error_message")) for t in a.get("tool_calls") or []]))
        return out

    return {"live": live, "start_index": fixture["start"]["index"], "start": agents(fixture["start"]["snapshot"]),
            "mid_index": fixture["mid"]["index"], "mid": agents(fixture["mid"]["snapshot"]),
            "final": agents(fixture["final"]), "outcome": fixture["outcome"]}


def main() -> None:
    from temper_ai.database import init_database

    parser = argparse.ArgumentParser()
    parser.add_argument("--write", required=True, help="directory for <scenario>.json")
    args = parser.parse_args()
    init_database("sqlite:///:memory:")
    out = Path(args.write)
    out.mkdir(parents=True, exist_ok=True)
    for name in SCENARIOS:
        fixture = view_fixture(name)
        text = json.dumps(fixture, ensure_ascii=False, indent=1) + "\n"
        if SECRET in text or SYSTEM_MARKER in text:
            raise SystemExit(f"{name}: secret or system message reached the view fixture")
        (out / f"{name}.json").write_text(text, encoding="utf-8")
        print(name, len(fixture["live"]), fixture["mid"]["index"], fixture["outcome"]["status"])


if __name__ == "__main__":
    main()
