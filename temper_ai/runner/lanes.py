"""Which worker may run a run: the run's lane (M4 ADR-M4-01; docs/pi-lane.md).

A Pi run -- a workflow with a Pi step at any depth, which includes a team stage of Pi
members -- carries the mark ``{"lane": "pi"}`` in its ``workflow_runs.spawner_metadata``.
Every other run carries no mark, exactly as before. The two places that write a run row,
:func:`temper_ai.runner.queue.queue_run` and the server's direct spawn
(``api/routes.py`` ``_start_run_subprocess``), set the mark through :func:`mark_lane`, on
every insert and every re-queue, so a resumed, forked, picked-up or cleaned-up Pi run keeps
it.

Each worker claims only its own lane's rows (:func:`lane_clause`): the main watcher never
claims a marked row, and the Pi lane's watcher (``TEMPER_LANE=pi``: the pi-worker service)
claims nothing else. Whatever claimed them, Pi steps refuse to run anywhere but the Pi lane
(:func:`refuse_outside_pi_lane`), and the Pi lane runs only what :func:`pi_only_problems`
lets through: Pi steps, team stages of Pi members and gates.

Nothing here imports the Pi step: telling a Pi run apart works while Pi is switched off.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

from temper_ai.stage.pi_workflows import PI_AGENT_TYPE, is_pi_workflow

if TYPE_CHECKING:
    from temper_ai.stage.node import Node

#: The key of the mark in ``workflow_runs.spawner_metadata``.
LANE_KEY = "lane"
#: The key of the Pi lane's own record in the same metadata: the temper commit each attempt
#: ran on (runner/pi_lane.py, SW-16). Only the Pi lane writes it; a re-queue keeps it.
LANE_RECORD_KEY = "pi_lane"
#: The Pi lane's name: the mark's value and the pi-worker's ``TEMPER_LANE``.
PI_LANE = "pi"
#: Every lane a worker may be set to. No setting is the main lane.
LANES = (PI_LANE,)
#: A worker's lane setting. Only the pi-worker service sets it.
LANE_ENV = "TEMPER_LANE"

#: The agent types the Pi lane runs (the Pi-only rule): the Pi step, and nothing else. Tests
#: of the Pi step's parking and resume add their own zero-cost test step type for their
#: package only (their conftest says so); production never widens it.
PI_LANE_AGENT_TYPES: tuple[str, ...] = (PI_AGENT_TYPE,)
#: Other step classes the Pi lane runs as they are: none. A test package of the Pi step's
#: parking adds its own stand-in for a team stage (a step that isn't an agent and asks).
PI_LANE_OTHER_NODES: tuple[str, ...] = ()

#: What a queued Pi run shows while the Pi lane hasn't claimed it (SW-40, ADR-M4-11).
WAITING_FOR_PI_LANE = "waiting for the Pi lane"
#: The refusal of a Pi step anywhere but the Pi lane (SW-42).
OUTSIDE_PI_LANE = "Pi steps run only in the Pi lane"


class LaneSettingError(RuntimeError):
    """``TEMPER_LANE`` names a lane temper doesn't know: the worker doesn't start."""


class OutsidePiLane(RuntimeError):  # noqa: N818 - a refusal, named for what it refuses
    """A Pi step was about to run outside the Pi lane."""


class _Keep:
    """:data:`KEEP_LANE`'s type."""

    def __repr__(self) -> str:
        return "KEEP_LANE"


#: For a re-queue whose caller didn't load the workflow: keep the row's own mark.
KEEP_LANE: Any = _Keep()


def lane_for(nodes: Iterable[Node]) -> str | None:
    """The lane a resolved workflow runs in: :data:`PI_LANE` for a Pi workflow, else None."""
    return PI_LANE if is_pi_workflow(nodes) else None


def lane_of(metadata: Any) -> str | None:
    """The lane a row's ``spawner_metadata`` names; None for the main lane."""
    if not isinstance(metadata, dict):
        return None
    lane = metadata.get(LANE_KEY)
    return lane if isinstance(lane, str) and lane else None


def mark_lane(metadata: dict | None, lane: str | None) -> dict:
    """A copy of ``metadata`` carrying ``lane``'s mark; no mark at all for the main lane."""
    out = {k: v for k, v in (metadata or {}).items() if k != LANE_KEY}
    if lane is not None:
        if lane not in LANES:
            raise LaneSettingError(f"'{lane}' is not a lane temper knows ({', '.join(LANES)})")
        out[LANE_KEY] = lane
    return out


def this_lane() -> str | None:
    """This process's lane, from ``TEMPER_LANE``: None for the main lane.

    Raises :class:`LaneSettingError` for a value temper doesn't know, so a typo never makes a
    worker that claims nothing (or the wrong runs) without saying so."""
    raw = os.environ.get(LANE_ENV, "").strip()
    if not raw:
        return None
    if raw not in LANES:
        raise LaneSettingError(
            f"{LANE_ENV}={raw[:40]!r} is not a lane temper knows ({', '.join(LANES)}); "
            f"leave it unset for the main lane")
    return raw


def in_pi_lane() -> bool:
    """Whether this process is the Pi lane (a bad setting is not)."""
    try:
        return this_lane() == PI_LANE
    except LaneSettingError:
        return False


def refuse_outside_pi_lane(step: str) -> None:
    """Raise :class:`OutsidePiLane` unless this process is the Pi lane (SW-42)."""
    if not in_pi_lane():
        raise OutsidePiLane(f"{OUTSIDE_PI_LANE}: step '{step}' was about to run in a worker "
                            f"that isn't the Pi lane ({LANE_ENV} is not '{PI_LANE}')")


def lane_clause(column: Any, lane: str | None) -> Any:
    """The SQL test that a row's ``spawner_metadata`` (``column``) is in ``lane``.

    The main lane (None) is every row without a Pi mark: no metadata, no ``lane`` key, or
    any other value. Works on SQLite and Postgres alike (``json_extract`` / ``->>``)."""
    value = column[LANE_KEY].as_string()
    if lane is None:
        return value.is_(None) | (value != PI_LANE)
    return value == lane


# --- The Pi-only rule (ADR-M4-01, SW-30, SW-41) ---------------------------------------------

def _walk(nodes: Iterable[Node], parent: str = "") -> Iterator[tuple[str, Node]]:
    for node in nodes:
        path = f"{parent}.{node.name}" if parent else str(node.name)
        yield path, node
        yield from _walk(getattr(node, "child_nodes", None) or (), path)


def _tool_servers(cfg: dict) -> list[str]:
    from temper_ai.tools.mcp_tool import _extract_mcp_tool_refs

    refs = sorted({str(ref).split(".", 1)[0] for ref in _extract_mcp_tool_refs(cfg)})
    servers = cfg.get("mcp_servers")
    if isinstance(servers, list | tuple | dict):
        refs += sorted(str(s) for s in servers)
    return refs


def _agent_problems(path: str, cfg: Any, what: str) -> list[str]:
    if not isinstance(cfg, dict):
        return [f"{what} '{path}' has no agent config the Pi lane can read"]
    kind = cfg.get("type") or "llm"
    if kind not in PI_LANE_AGENT_TYPES:
        return [f"{what} '{path}' is a {kind} step; the Pi lane runs only Pi steps"]
    servers = _tool_servers(cfg)
    if servers:
        return [f"{what} '{path}' asks for tool servers ({', '.join(servers)}); "
                f"the Pi lane runs no MCP or tool servers"]
    return []


def pi_only_problems(nodes: Iterable[Node], safety: dict | None = None) -> list[str]:
    """Why a workflow can't run in the Pi lane, each naming the step; [] when it can.

    The Pi lane holds the Docker socket, so it runs only what the Pi worker box contains:
    Pi steps, team stages of Pi members, and gates on any of them. Refused by name: script
    steps and every other agent type, steps that ask for MCP or tool servers, and the
    workflow's own ``safety: policies:`` (SW-30: the Pi lane doesn't run them; the member
    box is the boundary)."""
    nodes = list(nodes)
    problems: list[str] = []
    if isinstance(safety, dict) and safety.get("policies"):
        problems.append("the workflow sets safety: policies:, which the Pi lane doesn't run")
    for path, node in _walk(nodes):
        kind = type(node).__name__
        if kind == "_Refused":
            continue  # the stage's own run-start problems already stop the run
        if kind == "StageNode":
            continue  # its steps are checked one by one
        if kind in PI_LANE_OTHER_NODES:
            continue
        if kind == "AgentNode":
            problems += _agent_problems(path, getattr(node, "agent_config", None), "step")
        elif kind == "TeamNode":
            for member in getattr(node, "members", None) or ():
                name = member.get("name", "?") if isinstance(member, dict) else "?"
                problems += _agent_problems(f"{path}.{name}", member, "team member")
        else:
            problems.append(f"step '{path}' is a {kind}, which the Pi lane doesn't run")
    return problems
