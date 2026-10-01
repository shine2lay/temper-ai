"""Export a real run as a dashboard test fixture: a snapshot plus its events.

    python3 scripts/export_run_fixture.py <execution_id> <out.json> [--at N]

The result is what the dashboard sees: the snapshot `GET /api/workflows/<id>`
returns, and every event the run recorded, in order. A test can open the page
on part of it and replay the rest, which is what watching a live run is.

Long strings and bulk call events are trimmed: a fixture is about shapes, not
about megabytes of model output.
"""

from __future__ import annotations

import argparse
import json
import subprocess

MAX_STR = 200
# A fixture is about shapes, not about volume: a hundred tool calls prove
# nothing a handful does not, and the whole of a real EPD build is 116 MB.
MAX_LIST = 8

# One JSON document on one line: `json_agg` escapes newlines inside strings,
# and psql's -A -t prints it unchanged. (COPY would escape the backslashes
# again and the result no longer parses.)
SQL = """
select coalesce(json_agg(row_to_json(e) order by e.timestamp, e.id), '[]')::text
from (
  select id, type, parent_id, execution_id, status, data, timestamp
  from events where execution_id = '{run}'
) e
"""


# The fields that carry the weight of a run — what a model said, what a tool
# returned. A fixture keeps the fact that they are there, not their contents.
HEAVY = {
    "output", "structured_output", "workflow_output", "prompt", "system_prompt",
    "messages", "content", "result", "tool_result", "input_data", "arguments",
    "thinking", "error",
}


def trim_event(event: dict) -> dict:
    """One stored event, trimmed \u2014 still a mapping, which `trim` cannot promise."""
    trimmed = trim(event)
    assert isinstance(trimmed, dict)
    return trimmed


def trim(value: object) -> object:
    if isinstance(value, str):
        return value[:MAX_STR]
    if isinstance(value, list):
        return [trim(v) for v in value[:MAX_LIST]]
    if isinstance(value, dict):
        return {
            k: (f"<{k}>" if k in HEAVY and isinstance(v, str) else trim(v))
            for k, v in value.items()
        }
    return value


# A run's model and tool calls run to thousands; the fixture keeps enough of
# them to be the real stream and not enough to be a seven-megabyte file.
CALL_TYPES = ("llm.", "tool.")
KEEP_CALLS = 60


def drop_bulk_calls(events: list[dict]) -> list[dict]:
    """Every structural event, and the first few of the repetitive ones."""
    kept: list[dict] = []
    calls = 0
    for e in events:
        if any(str(e.get("type", "")).startswith(p) for p in CALL_TYPES):
            calls += 1
            if calls > KEEP_CALLS:
                continue
        kept.append(e)
    return kept


def thin_snapshot(value: object) -> object:
    """The run's tree, with each agent's call lists cut to a few entries."""
    if isinstance(value, list):
        return [thin_snapshot(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for k, v in value.items():
            if k in ("llm_calls", "tool_calls") and isinstance(v, list):
                out[k] = [thin_snapshot(c) for c in v[:3]]
            else:
                out[k] = thin_snapshot(v)
        return out
    return value


def psql(sql: str) -> str:
    out = subprocess.run(
        ["docker", "exec", "-i", "temper-ai-postgres-1", "psql", "-U", "temper_ai",
         "-d", "temper_ai", "-t", "-A", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("out")
    args = ap.parse_args()

    raw = psql(SQL.format(run=args.run))
    # A stored tool result can contain a NUL byte, which Postgres hands back
    # as an escape Python's json refuses; nothing in a fixture needs it.
    rows: list[dict] = json.loads(raw.replace("\\u0000", ""))
    events = drop_bulk_calls([trim_event(e) for e in rows])

    snapshot = json.loads(
        subprocess.run(
            ["curl", "-s", f"http://127.0.0.1:8420/api/workflows/{args.run}"],
            capture_output=True, text=True, check=True,
        ).stdout
    )

    with open(args.out, "w") as fh:
        json.dump(
            {"snapshot": thin_snapshot(trim(snapshot)), "events": events}, fh, indent=1
        )
    print(f"{len(events)} events, {len(json.dumps(snapshot))} bytes of snapshot -> {args.out}")


main()
