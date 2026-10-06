"""Trials started from the Team page (M3 ``team_check`` and ``team_trial_start``).

A trial is a one-node team workflow Temper builds from the page's form: ``team-trial-<id>``
with one stage ``trial`` (``strategy: team``) and one agent config per member,
``team-trial-<id>-<member>``. Before anything is saved, every check a run start makes runs in
memory on exactly those configs: the team check (field by field, M3 E20), the project folder
check (lexical in the server, M4 SW-62) and the run-start check itself. Then the configs and
the trial's row are saved in one transaction, frozen (E7: Studio and the configs importer
leave ``team-trial-`` names alone), and the run starts with the input ``goal``.

Nothing here talks HTTP; :mod:`temper_ai.api.team_routes` does.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from temper_ai.pi_agent.team_config import (
    LIMITS,
    TRIAL_PREFIX,
    TeamConfig,
    load_team_config,
)

logger = logging.getLogger(__name__)

#: The trial workflow's one stage; its team's step path is ``trial.team``.
TRIAL_STAGE = "trial"
#: What the Team page's members get when the form leaves ``tools`` out (team_status).
DEFAULT_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write")
#: The team's structured outcome, copied to the workflow's outputs (A2: the Team page reads
#: the outcome from ``pi_team_outcomes``, never from these).
OUTPUT_KEYS = ("decision", "reason", "review_id", "round", "version", "views", "objections",
               "summary", "rounds", "branch")
#: A start whose configs were saved but whose run never began is finished by a retry with the
#: same request id once it is this old (a start still under way is younger).
UNFINISHED_AFTER = timedelta(seconds=120)
#: The refusal for a request id used again with another body (M3 conventions, E23).
REQUEST_ID_REUSED = "this request id was already used for a different request; nothing was done"
#: A start, answer or message without its request id (E23).
REQUEST_ID_NEEDED = "the request needs a request_id (any unique text, the same on a retry)"


@dataclass
class TrialCheck:
    """A trial as the form gave it, the configs a start would save, and what the checks
    found. ``problems`` and ``notes`` are :class:`~temper_ai.pi_agent.team_check.Finding`."""

    trial_id: str
    workflow: str
    goal: str
    members: list[dict]
    leader: str
    pause_after_rounds: Any
    project_path: str | None
    communication: str = "all"
    configs: dict[tuple[str, str], dict] = field(default_factory=dict)
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def member_configs(self) -> list[str]:
        return [name for (kind, name) in self.configs if kind == "agent"]

    def record(self) -> dict:
        """The trial as started, for ``pi_team_trials.trial`` and ``team_run.trial``."""
        return {"goal": self.goal, "leader": self.leader,
                "members": [dict(m) for m in self.members],
                "pause_after_rounds": self.pause_after_rounds,
                "communication": self.communication,
                "project_path": self.project_path}


def new_trial_id() -> str:
    """12 hex characters (M3 E7)."""
    return secrets.token_hex(6)


def body_digest(body: dict) -> str:
    """The request's body, without its request id, as one hash: the same id must come with
    the same body (M3 conventions)."""
    rest = {k: v for k, v in body.items() if k != "request_id"}
    return hashlib.sha256(json.dumps(rest, sort_keys=True, default=str).encode()).hexdigest()


class OverlayStore:
    """The config store with a trial's unsaved configs laid over it, so the run-start check
    loads exactly what a start would save."""

    def __init__(self, store: Any, overlay: dict[tuple[str, str], dict]):
        self._store = store
        self._overlay = overlay

    def get(self, name: str, config_type: str) -> dict:
        if (config_type, name) in self._overlay:
            return copy.deepcopy(self._overlay[(config_type, name)])
        return self._store.get(name, config_type)


def _member_rows(raw: object) -> tuple[list[dict], list]:
    from temper_ai.pi_agent.route.model import RESERVED_IDS
    from temper_ai.pi_agent.team_check import Finding

    rows: list[dict] = []
    problems: list = []
    for index, item in enumerate(raw if isinstance(raw, list) else []):
        item = item if isinstance(item, dict) else {}
        role = str(item.get("role") or "").strip()
        name = str(item.get("name") or "").strip()
        tools = item.get("tools")
        if not role:
            problems.append(Finding(f"members: member {index + 1} needs a role", "members"))
            continue
        if not name:
            if role.lower() in RESERVED_IDS:
                problems.append(Finding(
                    f"members: the member with role '{role}' needs a name: '{role}' is "
                    "reserved for Temper's own use", "members"))
                continue
            name = role
        rows.append({"name": name, "role": role,
                     "tools": list(DEFAULT_TOOLS) if tools is None else tools})
    return rows, problems


def _project_findings(path: str, team: TeamConfig) -> tuple[list, list]:
    from temper_ai.pi_agent.team_check import Finding
    from temper_ai.pi_agent.team_folders import folder_check, roots_of

    problems = [Finding(text, "project_path") for text in team.problems]
    found, notes = folder_check(path, roots_of(team.project_roots), authoritative=False)
    problems += [Finding(text, "project_path") for text in found]
    return problems, [Finding(text, "project_path") for text in notes]


def check_trial(body: dict, *, store: Any = None, team: TeamConfig | None = None,
                trial_id: str | None = None, box: Any = None,
                box_problem: str | None = None) -> TrialCheck:
    """Every check a start makes, in memory: nothing is written. ``store`` is the config
    store the run-start check reads (the server's); ``team`` the team settings (loaded when
    None)."""
    from temper_ai.pi_agent.member import settings
    from temper_ai.pi_agent.team_check import Finding, team_findings
    from temper_ai.shared.text_limits import too_long

    tid = trial_id or new_trial_id()
    workflow = f"{TRIAL_PREFIX}{tid}"
    goal = str(body.get("goal") or "")
    leader = str(body.get("leader") or "").strip()
    raw_project = body.get("project_path")
    project: str | None = (str(raw_project).strip() if raw_project is not None else "") or None
    members, problems = _member_rows(body.get("members"))
    check = TrialCheck(trial_id=tid, workflow=workflow, goal=goal, members=members,
                       leader=leader, pause_after_rounds=body.get("pause_after_rounds"),
                       project_path=project, problems=problems,
                       communication=str(body.get("communication") or "all"))
    if len(goal) > LIMITS["goal_max_chars"]:
        check.problems.append(Finding(too_long("goal: the goal", len(goal),
                                               LIMITS["goal_max_chars"]), "goal"))
    agents: list[dict] = []
    for member in members:
        cfg = {"name": member["name"], "type": "pi", "role": member["role"],
               "tools": member["tools"], **settings({})}
        member.update(leader=member["name"] == leader, **settings(cfg))
        agents.append(cfg)
        check.configs[("agent", f"{workflow}-{member['name']}")] = {"agent": cfg}
    strategy: dict = {"mode": {"type": "leader", "leader": leader},
                      "communication": {"type": check.communication}}
    if check.pause_after_rounds is not None:
        strategy["pause_after_rounds"] = check.pause_after_rounds
    check.configs[("workflow", workflow)] = {"workflow": {
        "name": workflow,
        "description": "A team trial started from the Team page",
        "inputs": {"goal": {"type": "string", "required": True,
                            "description": "What the team works on"}},
        "nodes": [{"name": TRIAL_STAGE, "type": "stage", "strategy": "team",
                   "agents": check.member_configs(), "strategy_config": strategy}],
        "outputs": {key: f"{TRIAL_STAGE}.structured.{key}" for key in OUTPUT_KEYS},
    }}
    check.problems += team_findings(agents, strategy, inputs={"goal": goal}, box=box,
                                    box_problem=box_problem)
    if project:
        found, notes = _project_findings(project, team or load_team_config())
        check.problems += found
        check.notes += notes
    if check.ok and store is not None:
        check.problems += _run_start_findings(check, store)
    return check


def _run_start_findings(check: TrialCheck, store: Any) -> list:
    """The run start's own check (the loader with ``run_start``) on the unsaved configs."""
    from temper_ai.pi_agent.team_check import Finding
    from temper_ai.stage.loader import GraphLoader
    from temper_ai.stage.topology import run_start_options

    try:
        GraphLoader(OverlayStore(store, check.configs)).load_workflow(  # type: ignore[arg-type]
            check.workflow, inputs={"goal": check.goal}, **run_start_options())
    except Exception as exc:  # noqa: BLE001 -- every refusal is a problem the page shows
        return [Finding(str(exc))]
    return []


# --- the trial's rows ---------------------------------------------------------------------

def find(ledger: Any, *, request_id: str | None = None, trial_id: str | None = None,
         execution_id: str | None = None) -> dict | None:
    """One trial row by request id, trial id or run."""
    from temper_ai.pi_agent.ledger import trials

    if request_id is not None:
        where = trials.c.request_id == request_id
    elif trial_id is not None:
        where = trials.c.trial_id == trial_id
    else:
        where = trials.c.execution_id == execution_id
    with ledger.engine.connect() as conn:
        row = conn.execute(sa.select(trials).where(where)).mappings().first()
    return dict(row) if row else None


def listed(ledger: Any) -> list[dict]:
    """Every trial row, newest first."""
    from temper_ai.pi_agent.ledger import trials

    with ledger.engine.connect() as conn:
        rows = conn.execute(sa.select(trials).order_by(
            trials.c.created_at.desc(), trials.c.trial_id)).mappings().all()
    return [dict(r) for r in rows]


def save(ledger: Any, check: TrialCheck, *, request_id: str, digest: str, execution_id: str,
         by: str | None, source: str | None) -> dict:
    """The trial's configs and its row, in one transaction. Raises IntegrityError when the
    request id (or a config name) is already taken: nothing is saved then."""
    from temper_ai.config.models import Config
    from temper_ai.database import get_session
    from temper_ai.pi_agent.ledger import _now, trials

    row = {"trial_id": check.trial_id, "request_id": request_id, "body_sha256": digest,
           "workflow": check.workflow, "member_configs": check.member_configs(),
           "goal": check.goal, "project": check.project_path, "trial": check.record(),
           "execution_id": execution_id, "created_at": _now(), "created_by": by,
           "created_source": source, "started_at": None, "start_status": None}
    with get_session() as session:
        for (kind, name), cfg in check.configs.items():
            session.add(Config(type=kind, name=name, config=copy.deepcopy(cfg)))
        session.flush()
        session.connection().execute(trials.insert().values(**row))
    logger.info("team trial %s saved (%s, run %s)", check.trial_id, check.workflow,
                execution_id)
    return row


def mark_started(ledger: Any, trial_id: str, status: str) -> None:
    from temper_ai.pi_agent.ledger import _now, trials

    with ledger.engine.begin() as conn:
        conn.execute(trials.update().where(trials.c.trial_id == trial_id).values(
            started_at=_now(), start_status=status))


def undo(ledger: Any, row: dict) -> None:
    """Remove a trial that never started: its configs and its row."""
    from temper_ai.config.models import Config
    from temper_ai.database import get_session
    from temper_ai.pi_agent.ledger import trials

    names = [row["workflow"], *(row.get("member_configs") or [])]
    with get_session() as session:
        conn = session.connection()
        table = Config.__table__  # type: ignore[attr-defined]
        conn.execute(sa.delete(table).where(table.c.name.in_(names)))
        conn.execute(sa.delete(trials).where(trials.c.trial_id == row["trial_id"]))
    logger.info("team trial %s undone: its run did not start", row["trial_id"])


def unfinished(row: dict) -> bool:
    """A saved trial whose start never finished and is old enough to finish now."""
    from temper_ai.shared.clock import as_utc, utcnow

    if row.get("started_at"):
        return False
    try:
        created = as_utc(datetime.fromisoformat(str(row["created_at"])))
    except (TypeError, ValueError):
        return True
    return created is None or utcnow() - created >= UNFINISHED_AFTER
