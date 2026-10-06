"""The Pi lane's run process, for H2 and the secret key: one model-free Pi run through
``temper run-workflow`` in a process of its own, as pi-worker starts it.

Run as ``python -m tests.test_runner.pi_lane.run_child '<json>'`` by test_run_process.py
only. The JSON says ``{"db_url": "sqlite:////.../lane.db", "workspace": "...", "eager":
true}``; with ``"eager": false`` the run process's eager import is switched off (the
negative control). The environment is pi-worker's: TEMPER_LANE=pi, TEMPER_PI_AGENT=1, a
private HOME, no TEMPER_SECRET_KEY. Output: one JSON line with the run's exit code and
status, the temper modules first imported after the first turn began, and every attempt to
open a file named secret.key or to load the key.
"""

from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
import uuid

#: Files opened whose name holds this, from the interpreter's own audit events.
KEY_NAME = "secret.key"


def say(**data) -> None:
    print(json.dumps(data, default=str), flush=True)


def main(raw: str) -> int:
    args = json.loads(raw)
    url = args["db_url"]
    if not url.startswith("sqlite:///"):
        say(event="refused", why="the run child only opens a private SQLite file")
        return 2

    key_opens: list[str] = []

    def audit(event: str, payload: tuple) -> None:
        if event == "open" and payload and KEY_NAME in str(payload[0]):
            key_opens.append(str(payload[0]))

    sys.addaudithook(audit)

    from unittest.mock import MagicMock

    import pytest

    from temper_ai.cli.run_workflow import cmd_run_workflow
    from temper_ai.cli.watch_queue import _claim_row
    from temper_ai.config import ConfigStore
    from temper_ai.database import get_session, init_database
    from temper_ai.memory import InMemoryStore, MemoryService
    from temper_ai.pi_agent.ledger import Ledger
    from temper_ai.runner import pi_lane, pi_preflight
    from temper_ai.runner.context import RunnerContext
    from temper_ai.runner.lanes import PI_LANE
    from temper_ai.runner.models import WorkflowRun
    from temper_ai.runner.queue import queue_run
    from temper_ai.tools import mcp_auth
    from tests.test_pi_agent import support as sup
    from tests.test_runner.pi_lane import support as ls

    mp = pytest.MonkeyPatch()
    # The Pi lane as pi-worker runs it (TEMPER_LANE comes from the parent), with the default
    # list: the workflow is Pi-only, so nothing is widened here. Only the preflight's checks
    # of the real machine are left out (test_preflight.py tests them).
    mp.setattr(pi_preflight, "preflight", lambda **_kw: [])
    guard = sup.NetGuard().install(mp)
    init_database(url)
    sup.register_types()
    for name, build in ls.WORKFLOWS.items():
        sup.WORKFLOWS.setdefault(name, build)

    key_loads: list[str] = []
    load_key = mcp_auth._load_or_create_key

    def counted_load(*a, **kw):
        key_loads.append("loaded")
        return load_key(*a, **kw)

    mp.setattr(mcp_auth, "_load_or_create_key", counted_load)

    ctx = RunnerContext(config_store=ConfigStore(), graph_loader=sup.StubLoader(),
                        llm_providers={"mock": MagicMock()},
                        memory_service=MemoryService(InMemoryStore()))
    mp.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
               lambda config_dir=None: ctx)
    if not args.get("eager", True):
        mp.setattr(pi_lane, "eager_import", lambda: (0, []))

    before: dict[str, set[str]] = {}
    claim_turn = Ledger.claim_turn

    def first_turn(self, *a, **kw):
        before.setdefault("modules", set(sys.modules))
        return claim_turn(self, *a, **kw)

    mp.setattr(Ledger, "claim_turn", first_turn)

    def reach_later_code(_box) -> None:
        """During the turn, the code a long run's later steps reach: every module of the
        Pi agent (its team and ledger) and runner packages, which H2 names."""
        import temper_ai.pi_agent
        import temper_ai.runner

        for package in (temper_ai.pi_agent, temper_ai.runner):
            for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
                importlib.import_module(info.name)

    sup.FakeBox.on_prompt = reach_later_code

    eid = f"h2-{uuid.uuid4().hex[:12]}"
    queue_run(eid, "lane_pi", args["workspace"], {"topic": "h2"}, lane=PI_LANE)
    if not _claim_row(eid, "subprocess", lane=PI_LANE):
        say(event="refused", why="the Pi lane couldn't claim its own run")
        return 2
    code = cmd_run_workflow(argparse.Namespace(execution_id=eid, config_dir=None, debug=False))

    with get_session() as session:
        found = session.get(WorkflowRun, eid)
        status = found.status if found else None
    turns = [t["state"] for t in sup.ledger().snapshot(eid)["turns"]]
    seen = before.get("modules")
    late = sorted(m for m in sys.modules
                  if m.startswith("temper_ai") and seen is not None and m not in seen)
    say(event="ran", execution_id=eid, exit=code, status=status, turned=seen is not None,
        turns=turns, late=late, key_opens=key_opens, key_loads=len(key_loads),
        net_attempts=guard.attempts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
