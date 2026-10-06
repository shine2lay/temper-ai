"""Helpers for the Pi lane's tests (docs/pi-lane.md): workflows, rows and the two claims.

Workflows are built from L2's stand-in nodes (tests/test_pi_agent/support.py): no model, no
network, no Docker. The server here is not the Pi lane (no ``TEMPER_LANE``) unless a test says
so with :func:`as_the_pi_lane`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from temper_ai.runner.lanes import LANE_KEY, PI_LANE
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode
from tests.test_pi_agent import support as sup

#: A member of a stand-in team stage: a Pi agent config, as the loader resolves one.
MEMBER = {"type": "pi", "role": sup.ROLE, "provider": "openai-codex", "model": "gpt-6.1-sol"}


def team_stage(name: str = "crew", members: tuple[str, ...] = ("design", "qa"),
               **member_over: Any) -> StageNode:
    """A team stage of Pi members, as the loader builds one (StageNode around a TeamNode)."""
    from temper_ai.pi_agent.team_node import TeamNode

    team = TeamNode(NodeConfig(name="team"),
                    [{**MEMBER, "name": m, **member_over} for m in members],
                    settings=None)  # type: ignore[arg-type] - the rule reads members only
    return StageNode(NodeConfig(name=name), [team])


def gated_pi(name: str = "talk") -> Any:
    node = sup.pi_node(name, depends_on=())
    node.config.gate = True
    return node


#: The workflows these tests start: Pi runs the Pi lane may run, Pi runs it refuses, and
#: ordinary runs it never sees.
WORKFLOWS = {
    "lane_pi": lambda: [sup.pi_node(depends_on=())],
    "lane_pi_gate": lambda: [gated_pi()],
    "lane_team": lambda: [team_stage()],
    "lane_plain": lambda: [sup.step("brief"), sup.step("audit", ["brief"])],
    "lane_mixed": lambda: [sup.step("brief"), sup.pi_node()],
}


def as_the_pi_lane(monkeypatch) -> None:
    """This process is the Pi lane's worker (the pi-worker's own settings)."""
    from temper_ai.runner import lanes

    monkeypatch.setenv(lanes.LANE_ENV, PI_LANE)


def row(execution_id: str) -> Any:
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        found = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).first()
        if found is None:
            return None
        return SimpleNamespace(**found.model_dump())


def lane(execution_id: str) -> str | None:
    found = row(execution_id)
    assert found is not None, f"{execution_id} has no run row"
    return (found.spawner_metadata or {}).get(LANE_KEY)


def make_row(execution_id: str, workflow: str = "lane_pi", *, status: str = "queued",
             pi: bool = True, spawner_kind: str | None = None, handle: str | None = None,
             metadata: dict | None = None, **fields: Any) -> None:
    """A run row as a writer leaves it (the lane mark set through ``mark_lane``)."""
    from temper_ai.database import get_session
    from temper_ai.runner.lanes import mark_lane
    from temper_ai.runner.models import WorkflowRun

    fields.setdefault("inputs", {})
    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=execution_id, workflow_name=workflow, workspace_path="/tmp/ws",
            status=status, spawner_kind=spawner_kind, spawner_handle=handle,
            spawner_metadata=mark_lane(metadata or {}, PI_LANE if pi else None), **fields))


def set_row(execution_id: str, **fields: Any) -> None:
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        found = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).one()
        for key, value in fields.items():
            setattr(found, key, value)
        session.add(found)


def main_claims(execution_id: str) -> bool:
    """The main watcher's claim (docker spawner, no lane), undone when it got the row."""
    from temper_ai.cli.watch_queue import _claim_row, _unclaim

    won = _claim_row(execution_id, "docker")
    if won:
        _unclaim(execution_id)
    return won


def pi_lane_claims(execution_id: str) -> bool:
    """The Pi lane's claim (subprocess spawner, lane pi), undone when it got the row."""
    from temper_ai.cli.watch_queue import _claim_row, _unclaim

    won = _claim_row(execution_id, "subprocess", PI_LANE)
    if won:
        _unclaim(execution_id)
    return won


def only_the_pi_lane_claims(execution_id: str) -> None:
    found = row(execution_id)
    assert found is not None and found.status == "queued" and found.spawner_kind is None, found
    assert (found.spawner_metadata or {}).get(LANE_KEY) == PI_LANE, found.spawner_metadata
    assert not main_claims(execution_id), "the main watcher claimed a Pi run"
    assert pi_lane_claims(execution_id), "the Pi lane didn't claim its run"


def only_the_main_lane_claims(execution_id: str) -> None:
    found = row(execution_id)
    assert found is not None and found.status == "queued" and found.spawner_kind is None, found
    assert LANE_KEY not in (found.spawner_metadata or {}), found.spawner_metadata
    assert not pi_lane_claims(execution_id), "the Pi lane claimed an ordinary run"
    assert main_claims(execution_id), "the main watcher didn't claim an ordinary run"


class FakeSpawner:
    """The server's direct spawn without a process: records what it was asked to start."""

    def __init__(self) -> None:
        from temper_ai.worker_proto import SpawnerKind

        self.kind = SpawnerKind.subprocess
        self.spawned: list[str] = []

    def spawn(self, execution_id: str) -> Any:
        self.spawned.append(execution_id)
        return SimpleNamespace(kind=self.kind, handle="4242", metadata={"pid": 4242})
