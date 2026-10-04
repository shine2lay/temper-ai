"""R2 B17: ``temper trim`` never touches a Pi team's rows.

A team's conversation record (members, messages, turns, waits, review records) lives in the
``pi_`` tables, next to the run's events. Trim cuts old routine runs' events and checkpoints
only; the ``pi_`` rows of a run it trims must come out byte for byte the same.

Runs on in-memory SQLite and, with ``TEMPER_TEST_DATABASE_URL`` set, on the tier's Postgres
(tests/pgtier.py lists this folder).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from temper_ai.database import get_database, get_session
from temper_ai.observability import trim as trim_module
from temper_ai.observability.trim import TrimPolicy, run_trim
from temper_ai.pi_agent.ledger import TABLES, Binding, Ledger
from tests.test_observability.test_trim import NOW, make_run

HOST = "crew.team"


def _team(ledger: Ledger, run_id: str) -> None:
    """A team with a row in every ``pi_`` table: two members, a goal, a turn that sent a
    message, an owner wait and a review record."""
    rows = ledger.attach_team(run_id, HOST, [("lead", "scout", {"m": 1}),
                                             ("builder", "scout", {"m": 1})],
                              session_root="/state/trim", attempt_id="a1")
    lead = rows[0][0]
    ledger.post(run_id, HOST, "lead", "the goal", sender="temper", sender_kind="temper",
                kind="goal", dedupe_key=f"{run_id}:goal")
    turn, _batch = ledger.claim_turn(run_id, HOST, attempt_id="a1")
    binding = Binding(run_id=run_id, host_path=HOST, participant_id=lead["participant_id"],
                      member="lead", session_id=lead["session_id"], turn_id=turn["turn_id"],
                      epoch=turn["epoch"])
    sent = ledger.member_send(binding, {"to": "builder", "kind": "work_request",
                                        "body": "build it", "client_msg_id": "c1"})
    assert sent["ok"], sent
    assert ledger.finish_turn(turn["turn_id"], epoch=turn["epoch"], output="sent",
                              model_call_ids=["m1"], worker=None,
                              ask_owner={"question": "go on?", "options": ["yes"]},
                              attempt_id="a1") is not None
    ledger.open_review(run_id, HOST, round_no=1, leader_participant=lead["participant_id"],
                       asked_turn=turn["turn_id"], commit_sha="abc123",
                       files={"README.md": "0" * 64})


def test_b17_trim_keeps_pi_rows():
    run_id = f"pi-trim-{uuid.uuid4().hex[:8]}"
    make_run(run_id, "pi_team_routine")
    ledger = Ledger(get_database().engine)
    ledger.ensure()
    _team(ledger, run_id)
    before = ledger.snapshot(run_id)
    assert all(before[name] for name in ("participants", "messages", "turns", "waits",
                                         "reviews"))

    with get_session() as session:
        report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)

    assert report.stats.runs_trimmed >= 1  # the run itself was trimmed...
    assert ledger.snapshot(run_id) == before  # ...and its team's record was not touched


def test_b17_trim_names_no_pi_table():
    """Trim's code names only the tables it cuts: it cannot reach a ``pi_`` table."""
    source = Path(trim_module.__file__).read_text(encoding="utf-8")
    for table in TABLES:
        assert table.name not in source, table.name
