"""Read one rehearsal run back from the rig's own database; runs inside the rig's server.

rig.py pipes this file to ``docker exec -i <rig server> /app/.venv/bin/python - <run id>``,
so it needs no mount. It prints one JSON object: the run's row, the Pi ledger's rows for the
run and the guard's counts, without any message body, model output, goal text, owner words or
tool arguments (DROP). Never point it at a live database: rig.py only runs it in a container
of the rig's own compose project.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa

DROP = {"body", "output", "summary", "args", "reason", "owner_words", "goal", "text",
        "host_path"}
PI_TABLES = ("pi_participants", "pi_turns", "pi_messages", "pi_waits", "pi_reviews",
             "pi_team_acts", "pi_team_outcomes", "pi_team_trials", "pi_team_versions")


def plain(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items() if k not in DROP}
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    return value


def rows(conn: Any, table: sa.Table, where: Any) -> list[dict]:
    cols = [c for c in table.c if c.name not in DROP]
    order = [c for c in (table.c.get("seq"), table.c.get("created_at"),
                         table.c.get("opened_at"), table.c.get("started_at")) if c is not None]
    query = sa.select(*cols).where(where)
    if order:
        query = query.order_by(order[0])
    return [plain(dict(r)) for r in conn.execute(query).mappings()]


def main(run_id: str) -> dict:
    from temper_ai.database.engine import create_app_engine, get_database_url

    engine = create_app_engine(get_database_url())
    meta = sa.MetaData()
    meta.reflect(bind=engine, only=lambda name, _m: name in (*PI_TABLES, "workflow_runs",
                                                             "events", "api_guard_seen"))
    out: dict[str, Any] = {"run_id": run_id}
    with engine.connect() as conn:
        out["database"] = {"dialect": engine.dialect.name,
                           "version": conn.execute(sa.text("select version()")).scalar()}
        runs = meta.tables["workflow_runs"]
        out["run"] = rows(conn, runs, runs.c.execution_id == run_id)
        for name in PI_TABLES:
            table = meta.tables.get(name)
            if table is None:
                out[name] = None
                continue
            key = table.c.get("run_id")
            if key is None:
                key = table.c.get("execution_id")
            out[name] = rows(conn, table, key == run_id)
        events = meta.tables["events"]
        counted = conn.execute(sa.select(events.c.type, sa.func.count()).where(
            events.c.execution_id == run_id).group_by(events.c.type)).all()
        out["event_types"] = {t: n for t, n in counted}
        out["caller_actions"] = [plain(r["data"]) for r in conn.execute(
            sa.select(events.c.data).where(events.c.execution_id == run_id,
                                           events.c.type == "caller.action")
            .order_by(events.c.timestamp)).mappings()]
        seen = meta.tables["api_guard_seen"]
        out["api_guard_seen"] = [plain(dict(r)) for r in conn.execute(
            sa.select(seen).order_by(seen.c.caller, seen.c.action)).mappings()]
        gates = conn.execute(sa.select(events.c.type, events.c.status, events.c.data).where(
            events.c.execution_id == run_id, events.c.type.like("gate.%"))
            .order_by(events.c.timestamp)).mappings()
        out["gate_events"] = [{"type": g["type"], "status": g["status"],
                               **{k: plain(v) for k, v in (g["data"] or {}).items()
                                  if k in GATE_FIELDS}} for g in gates]
    return out


GATE_FIELDS = ("gate_name", "node_name", "gate_caller", "gate_caller_source", "request_id",
               "repeated", "status", "answered_at")


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), sort_keys=True, default=str))
