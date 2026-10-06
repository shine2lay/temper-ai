"""The crash worker for the Pi step's restart test: start one run in a private in-process
Temper, then SIGKILL itself while the Pi turn is running (after the prompt reached Pi), or
-- with ``"die_at": "owner_wait"`` -- once the step has asked the owner after its turn and
the run has let its worker go (parked, C7).

Run as ``python -m tests.test_pi_agent.child '<json>'`` by the restart test only. The JSON
says ``{"db_url": "sqlite:////.../pi.db", "workflow": "pi_talk", "workspace": "...",
"give_up_s": 30}``. Output: JSON lines ``started`` then ``killing``; the process ends by
SIGKILL -- no clean-up, what a power cut or an OOM kill leaves.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time

ANNOUNCED = threading.Event()


def say(**data) -> None:
    print(json.dumps(data, default=str), flush=True)


def main(raw: str) -> int:
    args = json.loads(raw)
    url = args["db_url"]
    if not url.startswith("sqlite:///"):
        refused = _not_the_test_tier(url)
        if refused:
            say(event="refused", why="the crash worker only opens a private SQLite file or "
                f"the test tier's throwaway Postgres: {refused}")
            return 2

    import pytest

    from tests.test_pi_agent import support as sup

    # The crash worker is the Pi lane, as the test that started it is (its conftest); the
    # process dies by SIGKILL, so nothing is undone.
    sup.into_the_pi_lane(pytest.MonkeyPatch())
    guard = sup.NetGuard().install()

    from fastapi.testclient import TestClient

    import temper_ai.stage.executor as executor_mod
    from temper_ai.database import init_database
    from temper_ai.llm import shared_cooldowns
    from temper_ai.server import app

    init_database(url)
    shared_cooldowns.use(shared_cooldowns.SharedCooldowns(None))
    executor_mod.GATE_POLL_SECONDS = 0.02
    sup.register_types()
    sup.install_app_state()

    def die(box) -> None:
        ANNOUNCED.wait(10)
        say(event="killing", session_id=box.spec.session_id, pid=os.getpid(),
            net_attempts=guard.attempts)
        os.kill(os.getpid(), signal.SIGKILL)

    at_wait = args.get("die_at") == "owner_wait"
    if not at_wait:
        sup.FakeBox.on_prompt = die
    client = TestClient(app)  # no lifespan: no start-up reconcile or pick-up in the worker
    eid = sup.start(client, args["workflow"], args["workspace"])
    say(event="started", execution_id=eid, pid=os.getpid())
    ANNOUNCED.set()
    if at_wait:
        give_up = float(args.get("give_up_s", 30))
        wait = sup.open_wait(eid, "owner", timeout=give_up)
        sup.wait_for(lambda: (sup.attempts(eid)[-1]["data"] or {}).get("parked"), give_up,
                     what="the run to let its worker go")
        say(event="killing", wait_id=wait["wait_id"], ask_event_id=wait["ask_event_id"],
            pid=os.getpid(), net_attempts=guard.attempts)
        os.kill(os.getpid(), signal.SIGKILL)
    time.sleep(float(args.get("give_up_s", 30)))
    say(event="gave_up", execution_id=eid)
    return 3


def _not_the_test_tier(url: str) -> str:
    """Why ``url`` is not the test tier's throwaway Postgres (tests/pgtier.py), or "" when it
    is. The worker is handed the URL in TEMPER_DATABASE_URL too, which the tier's own check
    would take for the live database, so that one comparison is left to the test that
    started this worker (tests/conftest.py checks every database it opens)."""
    from tests import pgtier

    handed = os.environ.pop("TEMPER_DATABASE_URL", None)
    try:
        pgtier.check_url(url)
    except RuntimeError as exc:
        return str(exc)
    finally:
        if handed is not None:
            os.environ["TEMPER_DATABASE_URL"] = handed
    return ""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
