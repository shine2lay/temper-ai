"""lane-status (Systems rm-a8af8c68): which Pi runs the Pi lane has, from database rows only.

temper-deploy asks ``temper pi lane-status --json`` on the host before it recreates
pi-worker, and recreates it only when nothing is active. So every state is listed on its
own, an error never reads as "nothing active" (exit 2 and ``ok: false``, never empty lists),
and the answer holds run ids, why and wait kinds only: no content.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from temper_ai.cli.pi import LANE_STATUS_FAILED, lane_status_command
from temper_ai.runner.pi_lane import CLAIMED, TURN_RUNNING
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_lane import support as ls

T0 = datetime(2026, 10, 6, 9, 0, 0, tzinfo=UTC)
SECRET = "SECRET-CONTENT-7f3a"
PASSWORD = "hunter2-lane-status"


@pytest.fixture
def db(tmp_path, request):
    """The test's database by URL, as lane-status reaches it: a file when SQLite."""
    from temper_ai.database import init_database, reset_database
    from tests.conftest import TEST_DATABASE_URL

    url = request.node.stash.get(TEST_DATABASE_URL, "")
    if url.startswith("sqlite"):
        url = f"sqlite:///{tmp_path / 'status.db'}"
        reset_database()
        request.node.stash[TEST_DATABASE_URL] = url
        init_database(url)
    ls.empty_the_ledger()
    yield url
    ls.empty_the_ledger()
    if url.startswith("sqlite"):
        reset_database()


@pytest.fixture
def no_ledger(db):
    """No pi_ tables, as before the Pi lane ever ran; on the tier they come back after."""
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import Ledger, metadata

    engine = get_database().engine
    had = sa.inspect(engine).has_table("pi_turns")
    metadata.drop_all(engine)
    yield db
    if had:
        Ledger(engine).ensure()


def ledger() -> None:
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import Ledger

    Ledger(get_database().engine).ensure()


def run(execution_id: str, status: str, n: int, *, pi: bool = True,
        kind: str | None = None) -> None:
    ls.make_row(execution_id, "lane_pi" if pi else "lane_plain", status=status, pi=pi,
                spawner_kind=kind, handle="h" if kind else None, created_at=T0 + timedelta(
                    seconds=n), inputs={"brief": SECRET}, error={"message": SECRET})


def turn(run_id: str, state: str = "running", n: int = 1) -> None:
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import turns

    with get_database().engine.begin() as conn:
        conn.execute(turns.insert().values(
            turn_id=f"turn-{run_id}-{n}", participant_id="p-1", run_id=run_id, host_path="talk",
            turn_no=n, state=state, epoch=0, claimed_by="host", input_seqs=[],
            model_call_ids=[], effect_state="intent", refusals=[], output=SECRET,
            error=SECRET))


def wait(run_id: str, kind: str = "owner", state: str = "open", n: int = 1) -> None:
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import waits

    with get_database().engine.begin() as conn:
        conn.execute(waits.insert().values(
            wait_id=f"wait-{run_id}-{n}", run_id=run_id, host_path="talk", kind=kind,
            gate_name=f"talk~ask-{n}", event_id=f"ev-{n}", state=state,
            subject={"question": SECRET}, opened_at=f"2026-10-06T09:00:0{n}+00:00",
            event_recorded=False))


def status(url: str | None) -> tuple[int, dict, str]:
    out = io.StringIO()
    code = lane_status_command(out=out, url=url)
    text = out.getvalue()
    assert text.endswith("\n") and text.count("\n") == 1, text
    return code, json.loads(text), text


# --- Each state ------------------------------------------------------------------------------


def test_with_no_pi_runs_it_answers_ok_with_three_empty_lists(db):
    code, answer, _ = status(db)
    assert code == 0
    assert answer == {"ok": True, "checked_at": answer["checked_at"], "active": [],
                      "parked": [], "queued": []}
    assert datetime.fromisoformat(answer["checked_at"]).utcoffset() == timedelta(0)


def test_each_state_is_listed_on_its_own_in_the_order_runs_came(db):
    ledger()
    run("queued", "queued", 1)
    run("claimed", "queued", 2, kind="subprocess")
    run("running", "running", 3, kind="subprocess")
    run("turning", "running", 4, kind="subprocess")
    turn("turning")
    run("asks", "waiting", 5, kind="subprocess")
    wait("asks", "owner")
    run("recovers", "waiting", 6, kind="subprocess")
    wait("recovers", "recovery", n=1)
    wait("recovers", "pause", n=2)
    run("at_a_gate", "waiting", 7, kind="subprocess")
    run("turn_while_waiting", "waiting", 8, kind="subprocess")
    turn("turn_while_waiting")
    run("queued_too", "queued", 9)

    code, answer, _ = status(db)
    assert code == 0 and answer["ok"] is True
    assert answer["active"] == [
        {"run_id": "claimed", "why": CLAIMED},
        {"run_id": "running", "why": CLAIMED},
        {"run_id": "turning", "why": TURN_RUNNING},
        {"run_id": "turn_while_waiting", "why": TURN_RUNNING},
    ]
    assert answer["parked"] == [
        {"run_id": "asks", "waiting_on": "owner"},
        {"run_id": "recovers", "waiting_on": "recovery"},
        {"run_id": "at_a_gate", "waiting_on": "gate"},
    ]
    assert answer["queued"] == [{"run_id": "queued"}, {"run_id": "queued_too"}]


@pytest.mark.parametrize("state", ["completed", "failed", "uncertain", "superseded"])
def test_only_a_turn_still_running_counts_as_one(db, state):
    ledger()
    run("r", "running", 1, kind="subprocess")
    turn("r", state)
    code, answer, _ = status(db)
    assert answer["active"] == [{"run_id": "r", "why": CLAIMED}]


def test_a_closed_wait_isn_t_what_a_run_waits_on(db):
    ledger()
    run("w", "waiting", 1, kind="subprocess")
    wait("w", "owner", state="decided", n=1)
    wait("w", "stalled", state="open", n=2)
    code, answer, _ = status(db)
    assert answer["parked"] == [{"run_id": "w", "waiting_on": "stalled"}]


@pytest.mark.parametrize("ended", ["completed", "failed", "cancelled", "orphaned",
                                   "interrupted"])
def test_ended_pi_runs_and_ordinary_runs_aren_t_listed(db, ended):
    ledger()
    run("ended", ended, 1, kind="subprocess")
    turn("ended")  # a turn row left running by a crash doesn't revive an ended run
    for n, live in enumerate(("queued", "running", "waiting"), start=2):
        run(f"plain-{live}", live, n, pi=False, kind="docker" if live != "queued" else None)
    code, answer, _ = status(db)
    assert (code, answer["active"], answer["parked"], answer["queued"]) == (0, [], [], [])


def test_without_the_pi_tables_it_answers_and_makes_none(no_ledger):
    """Before the Pi lane ever ran (Pi off): no ledger yet, and lane-status adds none."""
    run("running", "running", 1, kind="subprocess")
    run("waiting", "waiting", 2, kind="subprocess")
    code, answer, _ = status(no_ledger)
    assert code == 0
    assert answer["active"] == [{"run_id": "running", "why": CLAIMED}]
    assert answer["parked"] == [{"run_id": "waiting", "waiting_on": "gate"}]
    from temper_ai.database import get_database

    tables = sa.inspect(get_database().engine).get_table_names()
    assert not [t for t in tables if t.startswith("pi_")]


@pytest.mark.parametrize("switch", [None, "0", "1"])
def test_it_answers_whether_the_pi_step_is_on_or_off(db, monkeypatch, switch):
    if switch is None:
        monkeypatch.delenv("TEMPER_PI_AGENT", raising=False)
    else:
        monkeypatch.setenv("TEMPER_PI_AGENT", switch)
    run("queued", "queued", 1)
    code, answer, _ = status(db)
    assert (code, answer["queued"]) == (0, [{"run_id": "queued"}])


def test_the_answer_holds_only_run_ids_why_and_wait_kinds(db):
    ledger()
    run("turning", "running", 1, kind="subprocess")
    turn("turning")
    run("claimed", "running", 2, kind="subprocess")
    run("asks", "waiting", 3, kind="subprocess")
    wait("asks")
    run("queued", "queued", 4)
    code, answer, text = status(db)
    assert code == 0
    assert SECRET not in text and "lane_pi" not in text and "talk" not in text
    assert set(answer) == {"ok", "checked_at", "active", "parked", "queued"}
    assert [set(e) for e in answer["active"]] == [{"run_id", "why"}] * 2
    assert [set(e) for e in answer["parked"]] == [{"run_id", "waiting_on"}]
    assert [set(e) for e in answer["queued"]] == [{"run_id"}]


# --- Errors are never "nothing active" -------------------------------------------------------


def _failed(code: int, answer: dict) -> str:
    assert code == LANE_STATUS_FAILED == 2
    assert set(answer) == {"ok", "error"} and answer["ok"] is False
    assert isinstance(answer["error"], str) and answer["error"]
    return answer["error"]


def test_no_database_configured_is_an_error(monkeypatch):
    monkeypatch.delenv("TEMPER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    code, answer, _ = status(None)
    assert _failed(code, answer) == ("LaneStatusError: no database is configured "
                                     "(TEMPER_DATABASE_URL)")


def test_an_unreachable_database_is_an_error_that_hides_its_password():
    url = (f"postgresql://temper_ai:{PASSWORD}@/temper_ai"
           f"?host=/nonexistent/temper-lane-status")
    code, answer, text = status(url)
    assert _failed(code, answer).startswith("OperationalError: ")
    assert PASSWORD not in text


def test_a_database_without_the_run_table_is_an_error_and_stays_empty(tmp_path):
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    code, answer, _ = status(url)
    assert "workflow_runs" in _failed(code, answer)
    assert sa.inspect(sa.create_engine(url)).get_table_names() == []


def test_a_run_table_not_as_expected_is_an_error(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE workflow_runs (execution_id TEXT, status TEXT)"))
        conn.execute(sa.text("INSERT INTO workflow_runs VALUES ('r', 'running')"))
    engine.dispose()
    code, answer, _ = status(url)
    _failed(code, answer)


# --- The command, as temper-deploy runs it ---------------------------------------------------


def _cli(tmp_path, url: str | None, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("TEMPER_") and k != "DATABASE_URL"}
    env["PYTHONPATH"] = str(sup.WORKTREE)
    if url:
        env["TEMPER_DATABASE_URL"] = url
    return subprocess.run([sys.executable, "-m", "temper_ai.cli.main", "pi", *args],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def test_the_command_answers_in_a_process_of_its_own(db, tmp_path):
    run("queued", "queued", 1)
    done = _cli(tmp_path, db, "lane-status", "--json")
    assert done.returncode == 0, done.stderr[-2000:]
    answer = json.loads(done.stdout)
    assert (answer["ok"], answer["active"], answer["queued"]) == (True, [], [{"run_id":
                                                                               "queued"}])


def test_the_command_fails_with_exit_two_and_json_when_it_can_t_look(tmp_path):
    done = _cli(tmp_path, f"sqlite:///{tmp_path / 'empty.db'}", "lane-status", "--json")
    assert done.returncode == 2, done.stderr[-2000:]
    answer = json.loads(done.stdout)
    assert answer["ok"] is False and "workflow_runs" in answer["error"]


def test_the_command_with_no_subcommand_says_how_to_use_it(tmp_path):
    done = _cli(tmp_path, None)
    assert done.returncode == 2
    assert "usage: temper pi lane-status --json" in done.stderr
