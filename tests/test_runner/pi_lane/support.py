"""Helpers for the Pi lane's tests (docs/pi-lane.md): workflows, rows and the two claims.

Workflows are built from L2's stand-in nodes (tests/test_pi_agent/support.py): no model, no
network, no Docker. The server here is not the Pi lane (no ``TEMPER_LANE``) unless a test says
so with :func:`as_the_pi_lane`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from temper_ai.runner.lanes import LANE_KEY, PI_LANE
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode
from tests.test_pi_agent import support as sup


def empty_the_ledger() -> None:
    """No turn or wait of another test: the Postgres tier keeps the pi_ tables between tests
    (its truncate covers temper's own tables only), and the Pi lane's start-up sweeps the box of
    every unsettled turn it finds there."""
    import sqlalchemy as sa

    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import turns, waits

    engine = get_database().engine
    found = sa.inspect(engine)
    with engine.begin() as conn:
        for table in (turns, waits):
            if found.has_table(table.name):
                conn.execute(table.delete())


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


#: The account slots these tests' team settings allow: any labels but account 1's.
TEST_SLOTS = ("acct-b", "acct-c")


def team_settings(monkeypatch, settings_root: Path, **keys: Any) -> Path:
    """The team settings this test's Temper reads: ``keys`` merged into the owner's
    git-ignored local file under ``settings_root`` (other keys already there are kept). Only
    the default configs root is replaced. Returns the file."""
    import yaml

    from temper_ai.pi_agent import team_config

    local = settings_root / team_config.TEAM_DIR / "local" / "team.yaml"
    local.parent.mkdir(parents=True, exist_ok=True)
    have = (yaml.safe_load(local.read_text(encoding="utf-8")) or {}) if local.exists() else {}
    local.write_text(yaml.safe_dump({**have, **keys}), encoding="utf-8")
    real = team_config.settings_paths

    def settings_paths(config_dir: str | Path | None = None) -> tuple[Path, Path]:
        return real(config_dir if config_dir else settings_root)

    monkeypatch.setattr(team_config, "settings_paths", settings_paths)
    return local


def room_rows(figures: dict[str, dict], *, observed_at: str | None = None) -> list[dict]:
    """Version 1 rows (the account-room interface) for ``{slot: {five_hour, seven_day,
    five_hour_resets_at, seven_day_resets_at}}``; a slot given ``{"reason": ...}`` is
    unavailable. Observed now (whole seconds, UTC with Z) unless ``observed_at``."""
    from temper_ai.shared.clock import utcnow

    when = observed_at or utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for slot, got in figures.items():
        if "reason" in got:
            rows.append({"slot": slot, "status": "unavailable", "reason": got["reason"]})
            continue
        rows.append({"slot": slot, "status": "ok", "observed_at": when,
                     "five_hour": {"used_percent": got.get("five_hour"),
                                   "resets_at": got.get("five_hour_resets_at")},
                     "seven_day": {"used_percent": got.get("seven_day"),
                                   "resets_at": got.get("seven_day_resets_at")}})
    return rows


def write_room(path: Path, figures: dict[str, dict], *, observed_at: str | None = None) -> Path:
    """An account-room file as ops' writer publishes it (version 1; accounts.read_room)."""
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1,
                                "slots": room_rows(figures, observed_at=observed_at)}),
                    encoding="utf-8")
    return path


def give_accounts(monkeypatch, settings_root: Path, *, slots: tuple[str, ...] = TEST_SLOTS,
                  figures: dict[str, dict] | None = None) -> Path:
    """The team settings' account slots and a fresh account-room file beside them, as the
    owner's settings and ops' writer have them at switch-on: every slot has room, the first
    the most. Returns the room file."""
    room = write_room(settings_root / "account-room.json", figures if figures is not None else {
        slot: {"five_hour": 10.0, "seven_day": 20.0 + 10 * i} for i, slot in enumerate(slots)})
    team_settings(monkeypatch, settings_root, account_slots=list(slots),
                  account_room_file=str(room))
    return room


def account_of(execution_id: str) -> dict | None:
    """The account recorded on the run's row."""
    from temper_ai.pi_agent.accounts import recorded_account

    found = row(execution_id)
    return recorded_account({"spawner_metadata": found.spawner_metadata if found else None})


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
