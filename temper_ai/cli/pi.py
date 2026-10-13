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

``temper pi team-alerts <execution_id>`` says which of a free-flowing team run's waits its
owner was told about (notify kind ``team_wait``, docs/notify.md) and when Slack acknowledged
each, read from ``notify_copies`` only: FLOW's measure reads it as its notices file::

    {"ok": true, "execution_id": "...",
     "notices": [{"wait_id": "...", "at": "<UTC ISO time>", "channel": "slack"}]}

One entry per wait, at its first acknowledged copy. A copy Slack did not confirm is not a
notice. Failures exit 2 the same way as lane-status.
"""

from __future__ import annotations

import json
import sys
from typing import IO, Any

#: lane-status's exit when it can't answer (argparse's own usage errors also exit 2).
LANE_STATUS_FAILED = 2
#: team-alerts' exit when it can't answer.
TEAM_ALERTS_FAILED = 2


def add_parser(subparsers: Any) -> None:
    pi = subparsers.add_parser("pi", help="The Pi lane (docs/pi-lane.md)")
    sub = pi.add_subparsers(dest="pi_command")
    status = sub.add_parser(
        "lane-status",
        help="The Pi lane's active, parked and queued runs, from database rows (JSON)",
    )
    status.add_argument("--json", action="store_true",
                        help="Print one JSON object (its only output, with or without this)")
    alerts = sub.add_parser(
        "team-alerts",
        help="A team run's acknowledged owner alerts, from database rows (JSON, for FLOW's measure)",
    )
    alerts.add_argument("execution_id", help="The team run")


def cmd_pi(args: Any) -> int:
    command = getattr(args, "pi_command", None)
    if command == "lane-status":
        return lane_status_command()
    if command == "team-alerts":
        return team_alerts_command(str(args.execution_id))
    print("usage: temper pi lane-status --json | temper pi team-alerts <execution_id>", file=sys.stderr)
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


def team_alerts_command(execution_id: str, *, out: IO[str] | None = None, url: str | None = None) -> int:
    """Print a team run's acknowledged owner alerts; 0 when it could look, 2 (with the
    error) when not. Reads only; makes no table."""
    from temper_ai.integrations.notify.team_waits import read_receipts
    from temper_ai.runner.pi_lane import plain_error, status_engine

    out = out or sys.stdout
    try:
        engine = status_engine(url)
        try:
            answer = read_receipts(engine, execution_id)
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 - every failure is an answer, never "none"
        out.write(json.dumps({"ok": False, "error": plain_error(exc)}) + "\n")
        out.flush()
        return TEAM_ALERTS_FAILED
    out.write(json.dumps({"ok": True, "execution_id": execution_id, **answer}) + "\n")
    out.flush()
    return 0
