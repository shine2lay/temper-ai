"""The Pi agent step (``type: pi``): a Temper node that holds a conversation with one Pi role
in a sealed worker box. Switched off by default.

Switch: the environment setting ``TEMPER_PI_AGENT`` (``1``/``true``/``on``/``yes``). With it
off (the default) nothing here is imported by Temper, the ``pi`` agent type and the ``team``
strategy do not exist (a workflow naming either fails validation as unknown), no ``pi_`` table
is created and no route, page or event changes. See ``docs/pi-agent.md``.
"""

from __future__ import annotations

import os
from typing import Any

SWITCH_ENV = "TEMPER_PI_AGENT"
AGENT_TYPE = "pi"


def enabled() -> bool:
    return os.environ.get(SWITCH_ENV, "").strip().lower() in ("1", "true", "on", "yes")


def register_if_enabled() -> bool:
    """Register the ``pi`` agent type when the switch is on. Returns whether it did."""
    if not enabled():
        return False
    from temper_ai.agent import register_agent_type
    from temper_ai.pi_agent.host import PiHost

    register_agent_type(AGENT_TYPE, PiHost)
    return True


def register_team_if_enabled() -> bool:
    """Register the ``team`` strategy (with its run-start check) when the switch is on."""
    if not enabled():
        return False
    from temper_ai.pi_agent.team import STRATEGY, team_topology, validate_team
    from temper_ai.pi_agent.team_check import run_start_check
    from temper_ai.stage.topology import register_topology

    register_topology(STRATEGY, team_topology, validate_team, run_start_check=run_start_check)
    return True


def end_teams_on_cancel(run_id: str) -> int:
    """A run cancelled through Temper's cancel path while parked ends its Pi conversations and
    teams (R2 C2): every message they still held or had pending is recorded undelivered, open
    waits are cancelled and members end. Nothing else would, because a parked run has no
    attempt running. Switch on only, and only where the ``pi_`` tables already exist: this
    never creates them. Returns how many teams or steps it ended."""
    if not enabled():
        return 0
    import sqlalchemy as sa

    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import Ledger

    engine = get_database().engine
    if not sa.inspect(engine).has_table("pi_participants"):
        return 0
    ledger = Ledger(engine)
    ended = len(ledger.end_teams_for_run(run_id, "run_cancelled", "cancel"))
    _settle_outcomes(ledger, run_id)
    return ended


def _settle_outcomes(ledger: Any, run_id: str) -> None:
    """A cancelled run's teams that were still going get their cancelled outcome (M3 E2),
    where the outcome table exists."""
    import sqlalchemy as sa

    if not sa.inspect(ledger.engine).has_table("pi_team_outcomes"):
        return
    from temper_ai.pi_agent.team_outcome import settle_cancelled

    settle_cancelled(ledger, run_id)


def end_cancelled_teams(ledger: Any = None) -> int:
    """End the teams of every run that was cancelled but whose teams were not ended (G-a).

    A cancel ends the run first and its teams after (``runner/parked.py``): if the process
    dies between the two, nothing else would ever record the queued and held messages
    undelivered. Ending a team is idempotent, so this sweep can run any time; it does at a
    team's open, at start-up and in the trim sweep. A run counts as cancelled when its latest
    attempt (``workflow.started`` event) is. Switch on only, and only where the ``pi_`` tables
    already exist. Returns how many teams or steps it ended."""
    if not enabled():
        return 0
    import sqlalchemy as sa

    from temper_ai.pi_agent.ledger import Ledger, messages, participants
    from temper_ai.runner.resume import find_latest_workflow_event

    if ledger is None:
        from temper_ai.database import get_database

        engine = get_database().engine
        if not sa.inspect(engine).has_table("pi_participants"):
            return 0
        ledger = Ledger(engine)
    with ledger.engine.connect() as conn:
        runs = set(conn.execute(sa.select(participants.c.run_id).where(
            participants.c.state.not_in(("ended", "retired")))).scalars())
        runs |= set(conn.execute(sa.select(messages.c.run_id).where(
            messages.c.state.in_(("pending", "held")))).scalars())
    ended = 0
    for run_id in sorted(runs):
        latest = find_latest_workflow_event(run_id)
        if latest is None or latest.get("status") != "cancelled":
            continue
        ended += len(ledger.end_teams_for_run(run_id, "run_cancelled", "sweep"))
        _settle_outcomes(ledger, run_id)
    return ended
