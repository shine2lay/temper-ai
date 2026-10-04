"""The Pi agent step (``type: pi``): a Temper node that holds a conversation with one Pi role
in a sealed worker box. Switched off by default.

Switch: the environment setting ``TEMPER_PI_AGENT`` (``1``/``true``/``on``/``yes``). With it
off (the default) nothing here is imported by Temper, the ``pi`` agent type does not exist
(a workflow naming it fails validation as an unknown agent type), no ``pi_`` table is created
and no route, page or event changes. See ``docs/pi-agent.md``.
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
