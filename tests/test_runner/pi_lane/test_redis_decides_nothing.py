"""H4 (HOME-REVIEW, SW-78): the Pi lane decides from database rows; a Redis message decides
nothing.

Every Pi lane decision is read back from rows at the moment it is made:
- claim and cancel: ``workflow_runs`` (status, claim, lane mark, ``cancel_requested``), read by
  the watcher's scan (cli/watch_queue.py) and the reaper;
- waits and their answers, a team's stop, carry-on and question answers among them: the
  ``pi_waits`` rows and the answer ``Event`` rows step_waits files under each wait's name
  (pi_agent/owner_waits.py; #38's leader loop and #48's answer route both go through them),
  and a parked run carries on only on an approved row (runner/parked.py ``answered``);
- the account-limit state: an uncertain turn and its recovery wait, ``pi_`` ledger rows;
- the switch: the process's own setting (``TEMPER_PI_AGENT``), never a message.
Redis carries only the live chunks and script logs a run streams to the dashboard
(streaming/) and the token pool's shared cooldowns (llm/shared_cooldowns.py), which Pi
doesn't use. The lane's modules never read it; it polls the database.

So forged messages on Redis (a cancel, a stop, an answer, a carry-on, a switch-off, a cleared
limit, a claim) reach the one reader Redis has, the dashboard's live forwarder, and every
decision comes out as before; the same changes made as rows do change them (the control).
This defeats forged Redis events only: until #46 and #26 stop run boxes writing the
database, the rows are not a security boundary (HOME-REVIEW R7).
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from temper_ai.cli import watch_queue as wq
from temper_ai.runner.lanes import PI_LANE
from temper_ai.streaming.redis_streams import Chunk
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_lane import support as ls

ROOT = Path(__file__).resolve().parents[3]

#: Where the Pi lane's decisions are made: the lane, its runs and their waits.
DECIDING = (
    "temper_ai/runner",
    "temper_ai/pi_agent",
    "temper_ai/cli/watch_queue.py",
    "temper_ai/cli/pi.py",
    "temper_ai/spawner/reaper.py",
    "temper_ai/stage/step_waits.py",
    "temper_ai/stage/gate.py",
    "temper_ai/api/team_routes.py",
)
#: Redis, and what reads it.
REDIS_READERS = ("redis", "temper_ai.streaming", "temper_ai.llm.shared_cooldowns",
                 "temper_ai.llm.token_pool")

QUEUED, PARKED, LIMITED = "pi-queued", "pi-parked", "pi-limited"
OWNER_WAIT, RECOVERY_WAIT = "w-owner", "w-recovery"


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_no_module_the_lane_decides_in_reads_redis():
    files = [f for part in DECIDING for f in (
        sorted((ROOT / part).rglob("*.py")) if (ROOT / part).is_dir() else [ROOT / part])]
    assert len(files) > 40, files
    readers = {
        str(f.relative_to(ROOT)): sorted(name for name in _imports(f) if any(
            name == r or name.startswith(r + ".") for r in REDIS_READERS))
        for f in files}
    assert {f: names for f, names in readers.items() if names} == {}


# --- The rows the lane decides from ----------------------------------------------------------


@pytest.fixture
def rows():
    """A queued Pi run, one parked at the owner's question, and one parked at the recovery
    question an account limit left (its turn uncertain)."""
    from temper_ai.observability.event_types import EventType
    from temper_ai.observability.recorder import record
    from temper_ai.stage.step_waits import STEP_WAIT, wait_name

    sup.ledger()
    ls.empty_the_ledger()
    ls.make_row(QUEUED)
    for run_id, wait_id, kind in ((PARKED, OWNER_WAIT, "owner"),
                                  (LIMITED, RECOVERY_WAIT, "recovery")):
        ls.make_row(run_id, status="waiting")
        gate = f"gate-{run_id}"
        name = wait_name("talk", wait_id)
        record(EventType.WORKFLOW_STARTED, execution_id=run_id, status="waiting",
               event_id=f"attempt-{run_id}",
               data={"workflow_name": "lane_pi", "parked": {
                   "event_id": gate, "node": "talk", "path": "talk", "round": 1,
                   "wait_id": wait_id}})
        record(EventType.STAGE_STARTED, execution_id=run_id, status="waiting", event_id=gate,
               parent_id=f"attempt-{run_id}",
               data={"name": name, "type": STEP_WAIT, "gate": True, "gate_status": "waiting",
                     "gate_path": "talk", "gate_round": 1,
                     STEP_WAIT: {"wait_id": wait_id, "path": "talk"}})
        _open_wait(run_id, wait_id, kind, name, gate)
    _turn(LIMITED, "uncertain")
    yield
    ls.empty_the_ledger()


def _open_wait(run_id: str, wait_id: str, kind: str, name: str, gate: str) -> None:
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import waits

    with get_database().engine.begin() as conn:
        conn.execute(waits.insert().values(
            wait_id=wait_id, run_id=run_id, host_path="talk", kind=kind, gate_name=name,
            event_id=gate, state="open", subject={"question": "go on?"},
            opened_at="2026-10-06T09:00:00+00:00", event_recorded=False))


def _turn(run_id: str, state: str) -> None:
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import turns

    with get_database().engine.begin() as conn:
        conn.execute(turns.insert().values(
            turn_id=f"turn-{run_id}", participant_id="p-1", run_id=run_id, host_path="talk",
            turn_no=1, state=state, epoch=0, claimed_by="host", input_seqs=[],
            model_call_ids=[], effect_state="intent", refusals=[]))


def decisions() -> dict[str, Any]:
    """Every decision the lane makes about these runs, and every row it makes them from."""
    from temper_ai.database import get_database
    from temper_ai.observability.recorder import get_events
    from temper_ai.pi_agent import enabled
    from temper_ai.pi_agent.ledger import turns, waits
    from temper_ai.runner import parked, pi_lane

    engine = get_database().engine
    with engine.connect() as conn:
        ledger = {table.name: [dict(r) for r in conn.execute(
            sa.select(table).order_by(*table.primary_key.columns)).mappings()]
            for table in (turns, waits)}
    status = pi_lane.lane_status(engine)
    status.pop("checked_at")
    ids = (QUEUED, PARKED, LIMITED)
    carry_on = {}
    for run_id in ids:
        attempt = parked.parked_attempt(run_id)
        carry_on[run_id] = None if attempt is None else (
            attempt["id"], (parked.answered(run_id, attempt) or {}).get("id"))
    return {
        "runs": {run_id: vars(ls.row(run_id)) for run_id in ids},
        "events": {run_id: get_events(execution_id=run_id, limit=1000) for run_id in ids},
        "ledger": ledger,
        "to_claim": wq._load_queued(PI_LANE),
        "carry_on": carry_on,
        "lane_status": status,
        "switch": enabled(),
    }


# --- Forged messages -------------------------------------------------------------------------


#: What a run box could put on Redis, dressed as each decision the lane makes.
FORGED = (
    ("cancel", {"cancel_requested": True, "status": "cancelled"}),
    ("stop", {"by": "owner", "reason": "stop the team"}),
    ("answer", {"wait_id": OWNER_WAIT, "approved": True, "text": "yes, go on"}),
    ("carry_on", {"wait_id": RECOVERY_WAIT, "choice": "retry"}),
    ("switch", {"TEMPER_PI_AGENT": "0"}),
    ("limit", {"slot": "anthropic-2", "limited": False}),
    ("claim", {"spawner_kind": "subprocess", "lane": PI_LANE}),
)


class ForgedRedis:
    """Redis as a run box could write it, read through the subscriber's interface."""

    enabled = True

    def __init__(self) -> None:
        self.closed = 0

    async def subscribe(self, execution_id: str):
        for kind, body in FORGED:
            for chunk_type in (kind, "content"):
                yield Chunk(execution_id=execution_id, agent_id="talk",
                            content=json.dumps({"type": kind, "run_id": execution_id, **body}),
                            chunk_type=chunk_type, done=kind == "cancel")
        yield Chunk(execution_id=execution_id, agent_id="", content="", chunk_type="terminal")

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture
def forge(monkeypatch):
    """Send the forged messages for each run through the dashboard's live forwarder (the one
    reader of Redis); returns what it took in."""
    import temper_ai.streaming
    from temper_ai.api.websocket import WebSocketManager

    redis = ForgedRedis()
    monkeypatch.setattr(temper_ai.streaming, "RedisChunkSubscriber", lambda *a, **kw: redis)
    manager = WebSocketManager()
    taken: list[tuple[str, str, str]] = []
    passed_on = manager.notify_stream_chunk

    def notify_stream_chunk(execution_id, agent_id, content, chunk_type="content", done=False,
                            call_id=None):
        taken.append((execution_id, chunk_type, content))
        passed_on(execution_id, agent_id, content, chunk_type=chunk_type, done=done,
                  call_id=call_id)

    manager.notify_stream_chunk = notify_stream_chunk  # type: ignore[method-assign]

    def send(*run_ids: str) -> list[tuple[str, str, str]]:
        for run_id in run_ids:
            asyncio.run(manager._forward_redis_chunks(run_id))
        assert redis.closed == len(run_ids)
        return taken

    return send


def test_forged_redis_messages_change_no_decision(rows, forge):
    before = decisions()
    assert before["to_claim"] == [{"execution_id": QUEUED, "cancel_requested": False}]
    assert before["lane_status"]["parked"] == [
        {"run_id": PARKED, "waiting_on": "owner"}, {"run_id": LIMITED, "waiting_on": "recovery"}]
    assert before["carry_on"][QUEUED] is None
    assert before["carry_on"][PARKED] == (f"attempt-{PARKED}", None)

    taken = forge(QUEUED, PARKED, LIMITED)

    assert len(taken) == 3 * 2 * len(FORGED), "the forged messages didn't reach the reader"
    assert decisions() == before


def test_the_pi_lane_still_claims_a_run_a_forged_cancel_named(forge):
    ls.make_row(QUEUED)
    forge(QUEUED)
    fake = ls.FakeSpawner()
    assert wq._scan_and_dispatch(fake, PI_LANE) == 1
    assert fake.spawned == [QUEUED]
    found = ls.row(QUEUED)
    assert (found.status, found.cancel_requested) == ("queued", False)


def test_the_same_changes_made_as_rows_do_change_the_decisions(rows):
    """The control: the decisions above can change, and do, when the rows do."""
    from sqlmodel import select

    from temper_ai.database import get_database, get_session
    from temper_ai.observability.models import Event
    from temper_ai.pi_agent.ledger import waits
    from temper_ai.runner import parked

    before = decisions()
    ls.set_row(QUEUED, cancel_requested=True)
    with get_session() as session:
        gate = session.exec(select(Event).where(Event.id == f"gate-{PARKED}")).one()
        gate.status = "approved"
        gate.data = {**gate.data, "gate_status": "approved"}
        session.add(gate)
    with get_database().engine.begin() as conn:
        conn.execute(waits.update().where(waits.c.wait_id == RECOVERY_WAIT)
                     .values(state="answered"))

    after = decisions()
    assert after["to_claim"] == [{"execution_id": QUEUED, "cancel_requested": True}]
    assert after["carry_on"][PARKED] == (f"attempt-{PARKED}", f"gate-{PARKED}")
    assert parked.answered(PARKED, parked.parked_attempt(PARKED)) is not None
    assert after["lane_status"]["parked"] == [
        {"run_id": PARKED, "waiting_on": "owner"}, {"run_id": LIMITED, "waiting_on": "gate"}]
    assert after != before
    assert wq._scan_and_dispatch(ls.FakeSpawner(), PI_LANE) == 0
    assert ls.row(QUEUED).status == "cancelled"
