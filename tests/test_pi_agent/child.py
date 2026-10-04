"""The crash worker for the Pi step's restart test: start one run in a private in-process
Temper, then SIGKILL itself while the Pi turn is running (after the prompt reached Pi).

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
        say(event="refused", why="the crash worker only opens a private SQLite file")
        return 2

    from tests.test_pi_agent import support as sup

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

    sup.FakeBox.on_prompt = die
    client = TestClient(app)  # no lifespan: no start-up reconcile or pick-up in the worker
    eid = sup.start(client, args["workflow"], args["workspace"])
    say(event="started", execution_id=eid, pid=os.getpid())
    ANNOUNCED.set()
    time.sleep(float(args.get("give_up_s", 30)))
    say(event="gave_up", execution_id=eid)
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
