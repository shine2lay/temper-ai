"""Which workflows are Pi workflows, and the rules that apply only to them.

A Pi workflow is one whose config contains the Pi agent step (``type: pi``, see
docs/pi-agent.md), at any depth. Three things are different for them (docs/gates.md,
"Pi workflows"):

* a gate does not hold its worker while it waits, nor does a wait inside a step (the Pi
  step's own included, stage/step_waits.py): the run saves where it is and lets the
  worker go, and the owner's answer carries it on (runner/parked.py);
* Resume works before the first step has finished (a Pi run often starts by asking);
* every loop must end the run red when it runs out of rounds (``on_max_loops: fail``),
  because a Pi workflow must never count as done just because a loop stopped going round.

Every other workflow behaves as it always has.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from temper_ai.stage.node import Node

# The Pi step's agent type. Same value as temper_ai.pi_agent.AGENT_TYPE; written out here
# so that telling a Pi workflow apart never imports the Pi step (it stays switched off).
PI_AGENT_TYPE = "pi"

# The one loop policy a Pi workflow may use.
PI_LOOP_POLICY = "fail"


def _walk(nodes: Iterable[Node]) -> Iterator[Node]:
    for node in nodes:
        yield node
        yield from _walk(getattr(node, "child_nodes", None) or ())


def is_pi_workflow(nodes: Iterable[Node]) -> bool:
    """Whether a resolved workflow contains the Pi agent step, at any depth."""
    for node in nodes:
        try:
            configs = node.agent_configs()
        except Exception:  # noqa: BLE001 - a node that cannot say is not a Pi step
            continue
        if any(isinstance(cfg, dict) and cfg.get("type") == PI_AGENT_TYPE for cfg in configs):
            return True
    return False


def pi_loop_problems(nodes: list[Node]) -> list[str]:
    """Plain reasons a Pi workflow's loops break the loop rule; [] when they keep it, or
    when the workflow is not a Pi workflow."""
    if not is_pi_workflow(nodes):
        return []
    problems = []
    for node in _walk(nodes):
        if not node.loop_to:
            continue
        policy = node.on_max_loops or "silent"
        if policy == PI_LOOP_POLICY:
            continue
        problems.append(
            f"Node '{node.name}' loops back to '{node.loop_to}' with on_max_loops: {policy}. "
            f"In a workflow with a Pi step every loop must say on_max_loops: fail, so running out "
            f"of rounds stops the run red instead of letting it count as done."
        )
    return problems
