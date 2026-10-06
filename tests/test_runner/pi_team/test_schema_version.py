"""The pi_ tables' layout version (M4 ADR-M4-07: SW-12, SW-13), on SQLite and on the tier's
Postgres, each test on a database of its own with no pi_ table in it yet.

* SW-12: every path-built column is Text, so a step path longer than 255 characters is stored
  whole -- on Postgres, a VARCHAR(255) refused it.
* SW-13: ``pi_schema_version`` holds the version; :meth:`Ledger.ensure` moves an older
  database forward by additive steps under a lock, keeping every row, and refuses -- changing
  nothing -- a database newer than this build or pi_ tables with no version record.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from temper_ai.pi_agent import ledger as ledger_module
from temper_ai.pi_agent.ledger import (
    SCHEMA_LOCK_KEY,
    SCHEMA_VERSION,
    TABLES,
    Ledger,
    LedgerLayoutError,
    LedgerVersionError,
    gate_name_for,
    schema_version,
)
from tests.pgtier import TIER_ENV, check_url, schema_name

RUN = "run-schema"
#: A step path deeper than 255 characters: nested stages and a long team node name.
DEEP = "/".join(["a_stage_with_quite_a_long_name"] * 12) + "/team"
assert len(DEEP) > 300


@pytest.fixture
def fresh(db_url, tmp_path):
    """An engine on a database with no pi_ table: a private SQLite file, or on the tier a
    Postgres schema of this test's own, dropped after it (named after the worker's schema, so
    the tier's sweep removes it if the run dies)."""
    if db_url.startswith("sqlite"):
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'fresh.db'}", poolclass=NullPool)
        yield engine
        engine.dispose()
        return
    base = check_url(os.environ[TIER_ENV].strip())
    schema = f"{schema_name()}_v{uuid.uuid4().hex[:8]}"
    admin = sa.create_engine(base, poolclass=NullPool)
    with admin.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    joiner = "&" if "?" in base else "?"
    engine = sa.create_engine(f"{base}{joiner}options=-csearch_path%3D{schema}",
                              poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def stored(engine) -> int | None:
    with engine.connect() as conn:
        return conn.execute(sa.select(schema_version.c.version)).scalar()


def names(engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def columns(engine, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


# --- SW-13: the version ---------------------------------------------------------------------


def test_sw13_a_fresh_database_is_made_at_this_build_s_version_and_again_changes_nothing(fresh):
    Ledger(fresh).ensure()
    assert stored(fresh) == SCHEMA_VERSION == 3
    assert {t.name for t in TABLES} | {"pi_schema_version"} <= names(fresh)
    assert "snapshot_sha256" in columns(fresh, "pi_participants")
    assert "account_slot" in columns(fresh, "pi_turns") and "pi_team_versions" in names(fresh)
    with fresh.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(schema_version)).scalar() == 1
    Ledger(fresh).ensure()
    assert stored(fresh) == SCHEMA_VERSION


def test_sw13_an_older_version_is_moved_forward_by_its_steps_keeping_every_row(fresh):
    """A database at version 1 (before the snapshot digest): ensure adds the column and moves
    the record to 2; the rows already there are kept exactly, the new column empty."""
    led = Ledger(fresh)
    led.ensure()
    p, _ = led.attach_participant(RUN, "talk", "scout", session_root="/state/run/talk",
                                  pin={"model": "m"}, attempt_id="a1")
    led.post(RUN, "talk", "scout", "hello", dedupe_key=f"{RUN}:talk:seed:0")
    with fresh.begin() as conn:  # back to version 1's layout
        conn.execute(sa.text("ALTER TABLE pi_participants DROP COLUMN snapshot_sha256"))
        conn.execute(sa.text("ALTER TABLE pi_turns DROP COLUMN account_slot"))
        conn.execute(sa.text("DROP TABLE pi_team_versions"))
        conn.execute(schema_version.update().values(version=1))
    assert "snapshot_sha256" not in columns(fresh, "pi_participants")

    Ledger(fresh).ensure()
    assert stored(fresh) == SCHEMA_VERSION
    assert "snapshot_sha256" in columns(fresh, "pi_participants")
    assert "account_slot" in columns(fresh, "pi_turns") and "pi_team_versions" in names(fresh)
    (row,) = led.participants_of(RUN, "talk")
    assert row == {**p, "snapshot_sha256": None}
    assert [m["body"] for m in led.pending_for(p["participant_id"])] == ["hello"]
    assert led.record_snapshot(p["participant_id"], "d" * 64) == "d" * 64


def test_version_3_s_step_adds_the_turn_s_account_and_the_version_records_keeping_rows(fresh):
    """A database at version 2 (before ADR-M4-09's turn account and ADR-M4-12's version
    records): ensure adds the nullable column and the table, moving the record to 3; the turn
    already there is kept, its account empty, and a turn after it records its slot."""
    led = Ledger(fresh)
    led.ensure()
    p, _ = led.attach_participant(RUN, "talk", "scout", session_root="/state/run/talk",
                                  pin={"model": "m"}, attempt_id="a1")
    led.post(RUN, "talk", "scout", "hello", dedupe_key=f"{RUN}:talk:seed:0")
    claimed = led.claim_turn(RUN, "talk", attempt_id="a1")
    assert claimed is not None
    turn, _batch = claimed
    with fresh.begin() as conn:  # back to version 2's layout
        conn.execute(sa.text("ALTER TABLE pi_turns DROP COLUMN account_slot"))
        conn.execute(sa.text("DROP TABLE pi_team_versions"))
        conn.execute(schema_version.update().values(version=2))

    Ledger(fresh).ensure()
    assert stored(fresh) == SCHEMA_VERSION == 3
    assert "account_slot" in columns(fresh, "pi_turns") and "pi_team_versions" in names(fresh)
    with fresh.connect() as conn:
        rows = conn.execute(sa.text("SELECT turn_id, state, account_slot FROM pi_turns")).all()
    assert [(r[0], r[2]) for r in rows] == [(turn["turn_id"], None)]
    assert led.set_turn_agent_event(turn["turn_id"], "ev-1", epoch=turn["epoch"],
                                    account_slot="acct-b")
    with fresh.connect() as conn:
        assert conn.execute(sa.text("SELECT account_slot FROM pi_turns")).scalar() == "acct-b"
    Ledger(fresh).ensure()  # again: nothing changes
    assert stored(fresh) == SCHEMA_VERSION


def test_sw13_a_table_missing_at_the_current_version_comes_back_at_this_layout(fresh):
    Ledger(fresh).ensure()
    with fresh.begin() as conn:
        conn.execute(sa.text("DROP TABLE pi_team_requests"))
    Ledger(fresh).ensure()
    assert "pi_team_requests" in names(fresh) and stored(fresh) == SCHEMA_VERSION


def test_sw13_a_database_newer_than_this_build_is_refused_changing_nothing(fresh):
    Ledger(fresh).ensure()
    with fresh.begin() as conn:
        conn.execute(schema_version.update().values(version=SCHEMA_VERSION + 1))
        conn.execute(sa.text("DROP TABLE pi_team_requests"))  # ensure would make it again
    with pytest.raises(LedgerVersionError) as refused:
        Ledger(fresh).ensure()
    assert str(refused.value) == (
        f"this database's Pi tables are at layout version {SCHEMA_VERSION + 1}, but this "
        f"Temper knows only up to version {SCHEMA_VERSION}: a newer Temper made them; Temper changed nothing. Run the newer Temper, or "
        "use another database for Pi")
    assert isinstance(refused.value, LedgerLayoutError)
    assert stored(fresh) == SCHEMA_VERSION + 1 and "pi_team_requests" not in names(fresh)


def test_sw13_pi_tables_from_before_versioning_are_refused_changing_nothing(fresh):
    """pi_ tables with no version record come from a Pi build before versioning: their layout
    is unknown, so nothing is made or changed -- not even the version table."""
    with fresh.begin() as conn:
        ledger_module.metadata.create_all(conn, tables=[ledger_module.participants,
                                                        ledger_module.messages])
    with pytest.raises(LedgerVersionError) as refused:
        Ledger(fresh).ensure()
    assert str(refused.value) == (
        "this database has Pi tables (pi_messages, pi_participants) from a Pi build before "
        "their layout was versioned, so their layout is unknown; Temper changed nothing. Use a "
        "fresh database for Pi")
    assert names(fresh) == {"pi_messages", "pi_participants"}


def test_sw13_a_version_record_whose_tables_lack_a_column_is_refused(fresh):
    """A record that says version 3 over tables without version 2's column (made by hand, or
    a step undone): refused, never written to."""
    Ledger(fresh).ensure()
    with fresh.begin() as conn:
        conn.execute(sa.text("ALTER TABLE pi_turns DROP COLUMN box_stop"))
    with pytest.raises(LedgerLayoutError, match=r"don't match their layout version 3 \(missing "
                                                r"pi_turns\.box_stop\); Temper changed nothing"):
        Ledger(fresh).ensure()


def test_sw13_the_steps_run_under_the_database_lock(fresh):
    """On Postgres every step is taken under one advisory lock: while another session holds
    it, ensure waits, and then finds the work done. (SQLite: one process, its own lock.)"""
    if fresh.dialect.name != "postgresql":
        pytest.skip("the advisory lock is Postgres's; SQLite steps under the process lock")
    done: list[BaseException | None] = []

    def step():
        try:
            Ledger(fresh).ensure()
            done.append(None)
        except BaseException as exc:  # noqa: BLE001 - reported by the assert below
            done.append(exc)

    with fresh.connect() as holder:
        tx = holder.begin()
        holder.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": SCHEMA_LOCK_KEY})
        worker = threading.Thread(target=step, daemon=True)
        worker.start()
        time.sleep(0.5)
        assert done == [] and worker.is_alive(), "ensure stepped without the lock"
        assert "pi_schema_version" not in names(fresh)
        tx.commit()
    worker.join(30)
    assert done == [None] and stored(fresh) == SCHEMA_VERSION


# --- SW-12: path-built columns are Text -----------------------------------------------------


def test_sw12_path_built_columns_are_text():
    widened = {(t.name, c.name) for t in TABLES for c in t.columns
               if isinstance(c.type, sa.Text)}
    for table in TABLES:
        if "host_path" in table.c:
            assert (table.name, "host_path") in widened, table.name
    assert {("pi_messages", "dedupe_key"), ("pi_turns", "claim_key"),
            ("pi_turns", "claimed_by"), ("pi_turns", "box_name"), ("pi_waits", "gate_name"),
            ("pi_participants", "session_dir"), ("pi_team_requests", "request_id")} <= widened
    # no column of any pi_ table keeps the old 255 cap
    assert [(t.name, c.name) for t in TABLES for c in t.columns
            if isinstance(c.type, sa.String) and c.type.length == 255] == []


def test_sw12_a_step_path_over_255_characters_is_stored_whole(fresh):
    """Every row a deep team node writes -- the member, the goal (its dedupe key), the claimed
    turn (claim key, claimed by, box name) and a wait (gate name) -- keeps the whole path."""
    led = Ledger(fresh)
    led.ensure()
    claimed_by = "spark-" + "x" * 280 + ":4242:boot"
    p, _ = led.attach_participant(RUN, DEEP, "scout", session_root=f"/state/{RUN}/{DEEP}",
                                  pin={"model": "m"}, attempt_id="a1")
    key = f"{RUN}:{DEEP}:seed:0"
    led.post(RUN, DEEP, "scout", "hello", dedupe_key=key)
    turn, batch = led.claim_turn(RUN, DEEP, attempt_id="a1", claimed_by=claimed_by)
    box = "temper-pi-" + DEEP.replace("/", "-")
    assert led.record_box(turn["turn_id"], turn["epoch"], box)
    wait = led.open_wait(RUN, DEEP, "owner", {"question": "go on?"}, "a1")

    snap = led.snapshot(RUN)
    assert snap["participants"][0]["host_path"] == DEEP
    assert snap["participants"][0]["session_dir"].startswith(f"/state/{RUN}/{DEEP}/")
    (msg,) = snap["messages"]
    assert (msg["host_path"], msg["dedupe_key"]) == (DEEP, key)
    assert [m["message_id"] for m in batch] == [msg["message_id"]]
    (row,) = snap["turns"]
    assert (row["host_path"], row["claimed_by"], row["box_name"]) == (DEEP, claimed_by, box)
    assert row["claim_key"] == f"{RUN}|{DEEP}"
    (w,) = snap["waits"]
    assert (w["host_path"], w["gate_name"]) == (DEEP, gate_name_for(DEEP, wait["wait_id"]))
    assert len(w["gate_name"]) > 300
    assert p["host_path"] == DEEP
