"""``temper pi``: the Pi lane's own commands (docs/pi-lane.md).

``temper pi lane-status --json`` says which Pi runs the Pi lane has, read from database rows
only (H4): no model, no API call, no credential, and it answers with the Pi step switched off.
temper-deploy asks it on the host before it recreates the Pi lane's worker::

    docker compose exec -T server /app/.venv/bin/temper pi lane-status --json

Exit 0 and one JSON object::

    {"ok": true, "checked_at": "<UTC ISO time>",
     "active": [{"run_id": "...", "why": "turn_running" | "claimed"}],
     "parked": [{"run_id": "...", "waiting_on": "<wait kind>"}],
     "queued": [{"run_id": "..."}]}

``active``: a member turn is running, or the run is claimed and not parked. ``parked``: the
run waits with no process. ``queued``: not claimed yet. Run ids, why and wait kinds only.

Any failure (no database configured, the database unreachable, tables missing or not as
expected) exits 2 with ``{"ok": false, "error": "<plain text>"}``: never an empty list.
"""

from __future__ import annotations

import json
import sys
from typing import IO, Any

#: lane-status's exit when it can't answer (argparse's own usage errors also exit 2).
LANE_STATUS_FAILED = 2


def add_parser(subparsers: Any) -> None:
    pi = subparsers.add_parser("pi", help="The Pi lane (docs/pi-lane.md)")
    sub = pi.add_subparsers(dest="pi_command")
    status = sub.add_parser(
        "lane-status",
        help="The Pi lane's active, parked and queued runs, from database rows (JSON)",
    )
    status.add_argument("--json", action="store_true",
                        help="Print one JSON object (its only output, with or without this)")


def cmd_pi(args: Any) -> int:
    if getattr(args, "pi_command", None) == "lane-status":
        return lane_status_command()
    print("usage: temper pi lane-status --json", file=sys.stderr)
    return LANE_STATUS_FAILED


def lane_status_command(*, out: IO[str] | None = None, url: str | None = None) -> int:
    """Print lane-status's answer; 0 when it could look, 2 (with the error) when not."""
    from temper_ai.runner.pi_lane import lane_status, plain_error, status_engine

    out = out or sys.stdout
    try:
        engine = status_engine(url)
        try:
            answer = lane_status(engine)
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 - every failure is an answer, never "none"
        out.write(json.dumps({"ok": False, "error": plain_error(exc)}) + "\n")
        out.flush()
        return LANE_STATUS_FAILED
    out.write(json.dumps(answer) + "\n")
    out.flush()
    return 0
