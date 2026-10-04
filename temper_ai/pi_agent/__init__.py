"""The Pi agent step (``type: pi``): a Temper node that holds a conversation with one Pi role
in a sealed worker box. Switched off by default.

Switch: the environment setting ``TEMPER_PI_AGENT`` (``1``/``true``/``on``/``yes``). With it
off (the default) nothing here is imported by Temper, the ``pi`` agent type and the ``team``
strategy do not exist (a workflow naming either fails validation as unknown), no ``pi_`` table
is created and no route, page or event changes. See ``docs/pi-agent.md``.
"""

from __future__ import annotations

import os

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
