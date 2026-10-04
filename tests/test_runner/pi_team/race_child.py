"""One racing process for test_race.py: opens the ledger on the test database, says it is
ready, waits for the start file, does one thing to one team, and prints the outcome as JSON.

    python -m tests.test_runner.pi_team.race_child URL RUN HOST ACTION NAME START_FILE

ACTION: ``claim`` (claim the team's next turn), ``take_over`` (take over the team's cut-off
turns, its old box reported gone) or ``post:N`` (post N messages to the team's members).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import sqlalchemy as sa

from temper_ai.pi_agent.ledger import Ledger


def _engine(url: str) -> sa.Engine:
    if url.startswith("sqlite"):
        from temper_ai.database.engine import create_test_engine

        return create_test_engine(url)
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


def _gone(name: str) -> dict:
    return {"box": name, "found": False, "was_running": False, "removed": False,
            "confirmed": True, "error": None}


def main(url: str, run_id: str, host: str, action: str, me: str, start: str) -> dict:
    led = Ledger(_engine(url))
    led.ensure()
    print("ready", flush=True)
    deadline = time.monotonic() + 60
    while not Path(start).exists():
        if time.monotonic() > deadline:
            raise SystemExit("start file never appeared")
        time.sleep(0.0005)
    if action == "claim":
        got = led.claim_turn(run_id, host, attempt_id=me, claimed_by=me)
        return {"me": me, "turn_id": got[0]["turn_id"] if got else None,
                "batch": [m["message_id"] for m in got[1]] if got else []}
    if action == "take_over":
        took = led.take_over(run_id, host, me, stop_box=_gone)
        return {"me": me, "took": [[t["turn_id"], w["wait_id"]] for t, w in took]}
    if action.startswith("post:"):
        names = [p["member"] for p in led.participants_of(run_id, host)]
        posted = []
        for i in range(int(action.split(":", 1)[1])):
            row = led.post(run_id, host, names[i % len(names)], f"note {i} from {me}",
                           sender="temper", sender_kind="temper", kind="info",
                           dedupe_key=f"{run_id}:{me}:{i}")
            posted.append(row["message_id"])
        return {"me": me, "posted": posted}
    raise SystemExit(f"unknown action {action!r}")


if __name__ == "__main__":
    print(json.dumps(main(*sys.argv[1:7])), flush=True)
