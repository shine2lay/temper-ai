#!/usr/bin/env python3
"""Prove on a COPY of the database that trimming keeps the run page whole.

Never touches the live database except to read a sample of finished old
runs. It copies those runs into a scratch database, asks the same
questions the run page asks, trims, asks again, and reports what changed.

    uv run python scripts/trim_proof.py --sample 40

What it checks, per run:
  * every outcome field the run page draws is byte-identical after the trim
  * the only differences are the bulky sent material going away
  * the event tree still joins up (every parent_id still resolves)

It prints counts and field names only — never any run material.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter

SOURCE_CONTAINER = "temper-ai-postgres-1"
SOURCE_DB = "temper_ai"
SOURCE_USER = "temper_ai"
SCRATCH_DB = "temper_trim_proof"

# What the run page draws for a finished run, by event type. These must
# survive the trim untouched. (temper_ai/api/routes.py + frontend RunDetail)
OUTCOME_KEYS = {
    "workflow.started": ["name", "cost_usd", "total_tokens", "workflow_output", "status"],
    "workflow.completed": ["cost_usd", "total_tokens", "duration_seconds", "output"],
    "agent.started": ["agent_name", "model", "provider", "node_path", "role"],
    "agent.completed": ["output", "structured_output", "tokens", "cost_usd", "duration_seconds", "llm_calls"],
    "agent.failed": ["error", "error_type"],
    "llm.call.started": ["model", "provider", "iteration", "message_count", "tools_available"],
    "llm.call.completed": ["response_content", "total_tokens", "cost_usd", "latency_ms", "finish_reason", "tool_calls"],
    "llm.call.failed": ["error", "error_type"],
    "tool.call.completed": ["tool_name", "result", "duration_ms", "success"],
    "stage.started": ["name", "gate", "gate_status", "gate_response"],
}


def psql(db: str, sql: str, *, quiet: bool = False) -> str:
    cmd = ["docker", "exec", "-i", SOURCE_CONTAINER, "psql", "-U", SOURCE_USER, "-d", db, "-v", "ON_ERROR_STOP=1"]
    if quiet:
        cmd += ["-tA"]
    result = subprocess.run([*cmd, "-c", sql], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"psql failed on {db}:\n{result.stderr.strip()}")
    return result.stdout.strip()


def pick_runs(sample: int, older_than_days: int) -> list[str]:
    """Finished runs old enough to trim, spread across workflows."""
    sql = f"""
    with finished as (
        select e.execution_id,
               max(e.timestamp) as last_seen,
               (e.data->>'name') as workflow
        from events e
        where e.type = 'workflow.started'
          and e.timestamp < now() - interval '{older_than_days} days'
        group by e.execution_id, e.data->>'name'
    ),
    ok as (
        select f.* from finished f
        where not exists (
            select 1 from events x
            where x.execution_id = f.execution_id
              and x.status in ('failed', 'running', 'cancelled', 'interrupted')
              and x.type in ('workflow.started', 'workflow.completed', 'workflow.failed')
        )
          and exists (
            select 1 from events y
            where y.execution_id = f.execution_id and y.type = 'llm.call.started'
          )
    ),
    ranked as (
        select ok.*, row_number() over (partition by workflow order by last_seen desc) as rn
        from ok
    )
    select execution_id from ranked where rn <= 3 order by random() limit {sample};
    """
    return [line for line in psql(SOURCE_DB, sql, quiet=True).splitlines() if line]


def make_scratch(runs: list[str]) -> None:
    ids = ",".join(f"'{r}'" for r in runs)
    psql("postgres", f'drop database if exists {SCRATCH_DB};')
    psql("postgres", f'create database {SCRATCH_DB};')
    # Schema only, from the live database — same shape, no rows.
    dump = subprocess.run(
        ["docker", "exec", SOURCE_CONTAINER, "pg_dump", "-U", SOURCE_USER, "-d", SOURCE_DB,
         "--schema-only", "--table=events", "--table=checkpoints"],
        capture_output=True, text=True,
    )
    if dump.returncode != 0:
        raise SystemExit(f"pg_dump failed:\n{dump.stderr.strip()}")
    load = subprocess.run(
        ["docker", "exec", "-i", SOURCE_CONTAINER, "psql", "-U", SOURCE_USER, "-d", SCRATCH_DB, "-q"],
        input=dump.stdout, capture_output=True, text=True,
    )
    if load.returncode != 0:
        raise SystemExit(f"loading the schema failed:\n{load.stderr.strip()}")

    for table in ("events", "checkpoints"):
        copy_out = subprocess.run(
            ["docker", "exec", SOURCE_CONTAINER, "psql", "-U", SOURCE_USER, "-d", SOURCE_DB,
             "-c", f"\\copy (select * from {table} where execution_id in ({ids})) to stdout"],
            capture_output=True, text=True,
        )
        if copy_out.returncode != 0:
            raise SystemExit(f"copying {table} out failed:\n{copy_out.stderr.strip()}")
        copy_in = subprocess.run(
            ["docker", "exec", "-i", SOURCE_CONTAINER, "psql", "-U", SOURCE_USER, "-d", SCRATCH_DB,
             "-c", f"\\copy {table} from stdin"],
            input=copy_out.stdout, capture_output=True, text=True,
        )
        if copy_in.returncode != 0:
            raise SystemExit(f"copying {table} in failed:\n{copy_in.stderr.strip()}")


def read_runs(runs: list[str]) -> dict:
    """Everything the run page draws, straight from the scratch database."""
    ids = ",".join(f"'{r}'" for r in runs)
    rows = psql(SCRATCH_DB, f"""
        select json_agg(row_to_json(t)) from (
            select id, type, parent_id, execution_id, status, data, timestamp::text
            from events where execution_id in ({ids}) order by execution_id, timestamp, id
        ) t
    """, quiet=True)
    events = json.loads(rows) if rows and rows != "\\N" else []
    rows = psql(SCRATCH_DB, f"""
        select json_agg(row_to_json(t)) from (
            select id, execution_id, sequence, event_type, node_name, agent_name, status,
                   length(coalesce(output, '')) as output_len, structured_output,
                   cost_usd, total_tokens, duration_seconds, error, parent_id
            from checkpoints where execution_id in ({ids}) order by execution_id, sequence
        ) t
    """, quiet=True)
    checkpoints = json.loads(rows) if rows and rows != "\\N" else []
    return {"events": events, "checkpoints": checkpoints}


def compare(before: dict, after: dict) -> tuple[bool, list[str]]:
    problems: list[str] = []
    b_events = {e["id"]: e for e in before["events"]}
    a_events = {e["id"]: e for e in after["events"]}

    if set(b_events) != set(a_events):
        problems.append(f"event rows appeared or vanished: {len(b_events)} -> {len(a_events)}")

    dropped = Counter()
    for event_id, b in b_events.items():
        a = a_events.get(event_id)
        if a is None:
            continue
        for column in ("type", "parent_id", "execution_id", "status", "timestamp"):
            if b[column] != a[column]:
                problems.append(f"{b['type']}: column {column} changed")
        b_data, a_data = b["data"] or {}, a["data"] or {}
        for key in OUTCOME_KEYS.get(b["type"], []):
            if key in b_data and b_data.get(key) != a_data.get(key):
                problems.append(f"{b['type']}: outcome field {key!r} changed")
        for key in set(b_data) - set(a_data):
            dropped[f"{b['type']}.{key}"] += 1
        for key in set(a_data) - set(b_data):
            if key != "trimmed":
                problems.append(f"{b['type']}: unexpected new field {key!r}")
        # Nested: the agent's setup keeps its shape, loses only the templates.
        b_cfg, a_cfg = b_data.get("agent_config"), a_data.get("agent_config")
        if isinstance(b_cfg, dict) and isinstance(a_cfg, dict):
            for key in set(b_cfg) - set(a_cfg):
                dropped[f"{b['type']}.agent_config.{key}"] += 1
            for key in set(a_cfg) & set(b_cfg):
                if b_cfg[key] != a_cfg[key]:
                    problems.append(f"{b['type']}: agent_config.{key} changed")

    # The tree must still join up: every parent_id resolves to a row we still have.
    known = set(a_events)
    for event in a_events.values():
        if event["parent_id"] and event["parent_id"] not in known:
            # Cross-run parents exist in real data; only flag ones in our sample.
            if event["parent_id"] in b_events:
                problems.append(f"{event['type']}: its parent event disappeared")

    b_cp = {c["id"]: c for c in before["checkpoints"]}
    a_cp = {c["id"]: c for c in after["checkpoints"]}
    if set(b_cp) != set(a_cp):
        problems.append(f"checkpoint rows appeared or vanished: {len(b_cp)} -> {len(a_cp)}")
    for cp_id, b in b_cp.items():
        a = a_cp.get(cp_id)
        if a is None:
            continue
        for column in ("status", "structured_output", "cost_usd", "total_tokens",
                       "duration_seconds", "error", "node_name", "agent_name", "event_type"):
            if b[column] != a[column]:
                problems.append(f"checkpoint: column {column} changed")

    print("\n  dropped fields (the bulky sent material):")
    for name, count in sorted(dropped.items(), key=lambda kv: -kv[1]):
        print(f"    {name:48s} {count:6d} rows")
    return not problems, problems


def _dump_bytes() -> int:
    """Size of a pg_dump of the scratch database — what a backup would carry."""
    dump = subprocess.run(
        ["docker", "exec", SOURCE_CONTAINER, "pg_dump", "-U", SOURCE_USER, "-d", SCRATCH_DB, "-Fc", "-Z", "6"],
        capture_output=True,
    )
    return len(dump.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=40)
    parser.add_argument("--older-than-days", type=int, default=30)
    parser.add_argument("--keep", action="store_true", help="Leave the scratch database behind")
    args = parser.parse_args()

    print(f"picking up to {args.sample} finished runs older than {args.older_than_days} days…")
    runs = pick_runs(args.sample, args.older_than_days)
    if not runs:
        print("no runs matched — nothing to prove", file=sys.stderr)
        return 1
    print(f"  {len(runs)} runs")

    print(f"copying them into {SCRATCH_DB} (the live database is only read)…")
    make_scratch(runs)
    sizes = psql(SCRATCH_DB, "select pg_size_pretty(pg_database_size(current_database()))", quiet=True)
    print(f"  scratch database: {sizes}")

    before = read_runs(runs)
    print(f"  {len(before['events'])} events, {len(before['checkpoints'])} checkpoints")
    print(f"  a backup of it would carry: {_dump_bytes():,} bytes")

    print("trimming the scratch database…")
    # Set the URL explicitly: several projects here export TEMPER_DATABASE_URL,
    # and an inherited one would aim this at the wrong database entirely.
    env = dict(os.environ)
    env["TEMPER_DATABASE_URL"] = f"postgresql://temper_ai:temper_dev@localhost:5433/{SCRATCH_DB}"
    trim = subprocess.run(
        [sys.executable, "-m", "temper_ai.cli.main", "trim",
         "--older-than-days", str(args.older_than_days), "--keep-recent", "0", "--no-log", "--json"],
        capture_output=True, text=True, env=env,
    )
    print(trim.stdout.strip() or trim.stderr.strip()[-2000:])
    if trim.returncode != 0:
        return 1

    after = read_runs(runs)
    ok, problems = compare(before, after)
    # What a backup would actually carry: pg_dump writes live rows only, so
    # this is the honest before/after. The database file itself does not
    # shrink until a VACUUM returns the dead rows' space.
    after_size = psql(SCRATCH_DB, "select pg_size_pretty(pg_database_size(current_database()))", quiet=True)
    print(f"\n  scratch database file: {sizes} -> {after_size} (dead rows until VACUUM)")
    print(f"  a backup of it would carry: {_dump_bytes():,} bytes")

    if not args.keep:
        psql("postgres", f"drop database if exists {SCRATCH_DB};")

    if ok:
        print("\nPASS — every outcome the run page draws came through unchanged.")
        return 0
    print(f"\nFAIL — {len(problems)} problems:")
    for problem in sorted(set(problems))[:40]:
        print(f"  {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
