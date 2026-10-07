"""The Team page's API, under ``/api/team`` (M3 contract; api.json ``missing``).

Only with the Pi switch on (``TEMPER_PI_AGENT=1``) when the server starts: with it off the
router is never included, so every route here answers 404 and nothing else changes.

* ``GET  /api/team/status``                     what the form needs: defaults, tools, limits
* ``GET  /api/team/roles``                      the roles a member can take (no paths, no ids)
* ``POST /api/team/check``                      every check a start makes; writes nothing
* ``POST /api/team/trials``                     start a trial (one call: configs + run)
* ``GET  /api/team/trials``                     the trials, newest first, one item per run
* ``GET  /api/team/runs/{id}``                  one team run's state
* ``GET  /api/team/runs/{id}/messages/{mid}``   one message's full text
* ``POST /api/team/runs/{id}/waits/{wid}/answer``  answer the open wait Temper asks
* ``POST /api/team/runs/{id}/messages``         message a member as the owner

Every write goes through the API guard (#45): a trial start counts as a start, an answer and
a message as decisions; who did it is the guard's caller, never a name the page sends. Each
write carries the page's ``request_id``: the same id with the same body gives the first
result again (``repeated: true``); the same id with another body is refused.

Every time sent is ISO 8601 with ``+00:00`` (#60): a time taken from a recorded event, whose
stored timestamp has no zone, goes through ``team_view.utc_text`` on the way out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from temper_ai.api.caller import (
    display_source,
    guard_mode,
    record_action,
    require_caller_may,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team", tags=["team"])

API_VERSION = "1"
#: The tools a member can have, in the form's order (team_status).
TOOLS_AVAILABLE = ("Read", "Grep", "Glob", "Edit", "Write", "Bash")

# Texts (contract section 6; M3 E23 for the ones #48 worded).
NO_SUCH_TRIAL = "not a team trial, or no such run"
NO_LONGER_OPEN = "That question is no longer open"
NOT_ASKED_YET = "Temper hasn't asked this question yet; answer the one before it first"
TEAM_ENDED = "the team has ended; nothing was sent"
TEAM_NOT_STARTED = "the team has not started yet; nothing was sent"
NO_SUCH_MESSAGE = "no such message in this run"
NO_VERSION = "the team has made no version yet"
EMPTY_MESSAGE = "the message is empty"

#: The limit and the words of each answer's text (M3 E13).
ANSWER_LIMITS = {"guide": ("guide_max_chars", "the guidance"),
                 "nudge": ("nudge_max_chars", "the nudge"),
                 "stop": ("stop_reason_max_chars", "the reason for stopping"),
                 "reply": ("reply_max_chars", "the reply")}


class TeamRefusal(Exception):
    """A refusal with the contract's own body (not FastAPI's ``{detail}`` wrapper)."""

    def __init__(self, status: int, body: dict):
        super().__init__(body)
        self.status = status
        self.body = body


async def _refusal_response(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, TeamRefusal)
    return JSONResponse(status_code=exc.status, content=exc.body)


def include_team_routes(app: FastAPI) -> bool:
    """Add the Team page's routes to ``app``, only with the Pi switch on. Returns whether it
    did."""
    from temper_ai.pi_agent import enabled

    if not enabled():
        return False
    app.add_exception_handler(TeamRefusal, _refusal_response)
    app.include_router(router)
    logger.info("Team page API on (/api/team)")
    return True


# --- request bodies -------------------------------------------------------------------------
# Lenient on purpose: a missing or empty field is the engine's problem text for that field,
# so the page shows the same words chat does. A wrong JSON type is a client bug (422).

class TrialInput(BaseModel):
    request_id: str | None = None
    goal: str = ""
    members: list[Any] = []
    leader: str = ""
    pause_after_rounds: Any = None
    project_path: str | None = None
    communication: str = "all"


class AnswerBody(BaseModel):
    request_id: str | None = None
    answer: str = ""
    text: str = ""


class MessageBody(BaseModel):
    request_id: str | None = None
    to: str = ""
    body: str = ""


# --- shared helpers -------------------------------------------------------------------------

_LEDGER: dict[str, Any] = {}


def _ledger() -> Any:
    """The team ledger on the server's database, its tables made once."""
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import Ledger, LedgerLayoutError

    engine = get_database().engine
    held = _LEDGER.get("ledger")
    if held is None or held.engine is not engine:
        held = Ledger(engine)
        try:
            held.ensure()
        except LedgerLayoutError as exc:  # a layout this build doesn't know (SW-13)
            raise HTTPException(status_code=503,
                                detail=f"Pi refused this database: {exc}") from None
        _LEDGER["ledger"] = held
    return held


def _owners() -> tuple[str, ...]:
    from temper_ai.pi_agent.team_config import load_team_config

    return load_team_config().owner_callers


def _request_id(value: str | None) -> str:
    from temper_ai.pi_agent.team_trials import REQUEST_ID_NEEDED

    rid = (value or "").strip()
    if not rid:
        raise TeamRefusal(400, {"problem": REQUEST_ID_NEEDED})
    return rid


def _reused() -> TeamRefusal:
    from temper_ai.pi_agent.team_trials import REQUEST_ID_REUSED

    return TeamRefusal(409, {"reason": "request_id_reused", "message": REQUEST_ID_REUSED})


def _seen(ledger: Any, rid: str, run_id: str, kind: str, digest: str) -> dict | None:
    """The first result of an answer or message with this request id, or None when the id is
    new. The same id used for anything else is refused."""
    from temper_ai.pi_agent import team_trials
    from temper_ai.pi_agent.ledger import requests

    with ledger.engine.connect() as conn:
        row = conn.execute(sa.select(requests).where(
            requests.c.request_id == rid)).mappings().first()
    if row is None:
        if team_trials.find(ledger, request_id=rid) is not None:
            raise _reused()
        return None
    if (row["run_id"], row["kind"], row["body_sha256"]) != (run_id, kind, digest):
        raise _reused()
    return {**(row["result"] or {}), "repeated": True}


def _remember(ledger: Any, rid: str, run_id: str, kind: str, digest: str,
              result: dict) -> None:
    from temper_ai.pi_agent.ledger import _now, requests

    try:
        with ledger.engine.begin() as conn:
            conn.execute(requests.insert().values(
                request_id=rid, run_id=run_id, kind=kind, body_sha256=digest,
                result=result, created_at=_now()))
    except IntegrityError:
        pass  # the same request, sent twice at once: the first one's row stands


def _workflow_of(execution_id: str) -> str | None:
    """The workflow a run ran (its run row, else its start event)."""
    from temper_ai.api.routes import _run_row
    from temper_ai.observability.recorder import get_events

    row = _run_row(execution_id)
    if row and row.get("workflow_name"):
        return row["workflow_name"]
    starts = get_events(execution_id=execution_id, event_type="workflow.started",  # type: ignore[arg-type]
                        limit=1)
    return ((starts[0].get("data") or {}).get("name")) if starts else None


@dataclass
class TeamRun:
    """One run of a trial: the trial's row, the team's outcome row and where the team is."""

    execution_id: str
    trial: dict
    outcome: dict | None
    host_path: str
    run_status: str | None

    @property
    def record(self) -> dict:
        return self.trial.get("trial") or {}

    @property
    def leader(self) -> str:
        return str(self.record.get("leader") or "")

    @property
    def members(self) -> list[dict]:
        return list(self.record.get("members") or [])


def _team_run(ledger: Any, execution_id: str) -> TeamRun:
    """The trial run ``execution_id`` (the trial's own run, or a resume, re-run or fork of
    its workflow), or a 404."""
    from temper_ai.api.data_service import run_detail_status
    from temper_ai.api.routes import _run_row
    from temper_ai.pi_agent import team_trials
    from temper_ai.pi_agent.team_config import trial_id_of

    trial = team_trials.find(ledger, execution_id=execution_id)
    outcomes = ledger.outcomes_of(execution_id)
    if trial is None:
        tid = next((o["trial_id"] for o in outcomes if o.get("trial_id")), None)
        tid = tid or trial_id_of(_workflow_of(execution_id))
        trial = team_trials.find(ledger, trial_id=tid) if tid else None
    if trial is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_TRIAL)
    run_status = run_detail_status(execution_id)
    if run_status is None:
        row = _run_row(execution_id)
        run_status = row["status"] if row else None
        if row is None and trial.get("execution_id") != execution_id:
            raise HTTPException(status_code=404, detail=NO_SUCH_TRIAL)
    outcome = outcomes[0] if outcomes else None
    host_path = outcome["host_path"] if outcome else f"{team_trials.TRIAL_STAGE}.team"
    return TeamRun(execution_id, trial, outcome, host_path, run_status)


def _caller_actions(execution_id: str) -> list[dict]:
    from temper_ai.observability.recorder import get_events

    return get_events(execution_id=execution_id, event_type="caller.action",  # type: ignore[arg-type]
                      limit=None)


def _started_by(actions: list[dict], trial: dict, owners: tuple[str, ...]) -> str | None:
    from temper_ai.pi_agent.team_outcome import UNKNOWN_CALLER, by_name

    for ev in actions:
        data = ev.get("data") or {}
        if data.get("action") == "start":
            return by_name(data.get("caller"), owners) or UNKNOWN_CALLER
    return by_name(trial.get("created_by"), owners)


def _ended(run: TeamRun) -> bool:
    from temper_ai.pi_agent.team_view import RUN_ENDED

    return bool(run.outcome and run.outcome.get("decision")) or run.run_status in RUN_ENDED


# --- reads --------------------------------------------------------------------------------

@router.get("/status")
def team_status() -> dict:
    """What the Team page's form needs: defaults, tools, limits, the allowed project folders
    and the guard's mode."""
    from temper_ai.pi_agent.member import settings
    from temper_ai.pi_agent.route.model import RESERVED_IDS
    from temper_ai.pi_agent.team_check import (
        BASH_OFF,
        bash_allowed,
        load_box_or_lane_view,
    )
    from temper_ai.pi_agent.team_config import LIMITS, NAME_PATTERN, load_team_config
    from temper_ai.pi_agent.team_trials import DEFAULT_TOOLS

    box, box_problem = load_box_or_lane_view()
    team = load_team_config()
    bash = bash_allowed()
    return {
        "api_version": API_VERSION,
        "roles_configured": box is not None,
        "roles_problem": box_problem,
        "defaults": {**settings({}), "source": "temper"},
        "tools": {"available": list(TOOLS_AVAILABLE), "default": list(DEFAULT_TOOLS),
                  "source": "temper", "bash_allowed": bash,
                  "bash_why": None if bash else BASH_OFF},
        "communication": {"available": ["all"], "later": ["edges"]},
        "limits": {**LIMITS, "name_pattern": NAME_PATTERN,
                   "reserved_names": sorted(RESERVED_IDS)},
        "project_roots": list(team.project_roots),
        "project_problems": list(team.problems),
        "guard_mode": guard_mode(),
    }


@router.get("/roles")
def team_roles() -> dict:
    """The roles a member can take: id, title, about page, whether it has a home chat, and its
    problems. Nothing else of a role's folder leaves the server. Outside the Pi lane they come
    from the Pi lane view pi-worker publishes (ADR-M4-21)."""
    from temper_ai.pi_agent.team_check import load_box_or_lane_view, role_list

    box, problem = load_box_or_lane_view()
    if box is None:
        return {"configured": False, "problem": problem, "roles": []}
    roles = role_list(box)
    return {"configured": True, "problem": None,
            "roles": [roles.card(role) for role in roles.ids()]}


def _check(body: dict) -> Any:
    from temper_ai.api.routes import _state
    from temper_ai.pi_agent.team_check import load_box_or_lane_view
    from temper_ai.pi_agent.team_trials import check_trial

    box, box_problem = load_box_or_lane_view()
    return check_trial(body, store=_state().config_store, box=box, box_problem=box_problem)


def _findings(items: list) -> list[dict]:
    return [f.as_dict() for f in items]


@router.post("/check")
def team_check(body: TrialInput) -> dict:
    """Every check a start makes, field by field (M3 E20); nothing is written."""
    check = _check(body.model_dump(exclude={"request_id"}))
    return {"ok": check.ok, "problems": _findings(check.problems),
            "notes": _findings(check.notes)}


@router.get("/trials")
def team_trials_list(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     state: str | None = None) -> dict:
    """The trials, newest first: one item per run of a trial's workflow (its own run, and any
    re-run or fork of it from the run page)."""
    from temper_ai.api.data_service import run_list_statuses
    from temper_ai.pi_agent import team_trials
    from temper_ai.pi_agent.ledger import outcomes
    from temper_ai.pi_agent.team_leader import WAIT_KIND_SHOWN
    from temper_ai.pi_agent.team_outcome import by_name
    from temper_ai.pi_agent.team_view import TeamReader, team_state

    ledger = _ledger()
    owners = _owners()
    rows = team_trials.listed(ledger)
    with ledger.engine.connect() as conn:
        others = conn.execute(sa.select(outcomes).where(outcomes.c.trial_id.in_(
            [r["trial_id"] for r in rows]))).mappings().all() if rows else []
    by_trial: dict[str, dict[str, dict]] = {}
    for o in others:
        by_trial.setdefault(o["trial_id"], {})[o["run_id"]] = dict(o)
    runs: list[tuple[dict, str, dict | None]] = []
    for row in rows:
        mine = by_trial.get(row["trial_id"], {})
        eids = [row["execution_id"]] if row.get("execution_id") else []
        eids += sorted((e for e in mine if e not in eids),
                       key=lambda e: str(mine[e].get("started_at") or ""), reverse=True)
        runs += [(row, eid, mine.get(eid)) for eid in eids]
    statuses = run_list_statuses([eid for _row, eid, _o in runs])
    items = []
    for row, eid, orow in runs:
        record = row.get("trial") or {}
        host = orow["host_path"] if orow else f"{team_trials.TRIAL_STAGE}.team"
        reader = TeamReader(ledger, eid, host, str(record.get("leader") or ""))
        waits_open = [{"kind": WAIT_KIND_SHOWN.get(w["kind"], w["kind"])}
                      for w in ledger.open_waits(eid, host)]
        decision = (orow or {}).get("decision")
        run_status = statuses.get(eid)
        item_state = team_state(outcome={"decision": decision} if decision else None,
                                run_status=run_status, open_waits=waits_open,
                                began=ledger.any_turn_began(eid, host))
        if state and item_state != state:
            continue
        actions = _caller_actions(eid) if eid != row.get("execution_id") else []
        started_by = (_started_by(actions, row, owners) if actions
                      else by_name(row.get("created_by"), owners))
        items.append({
            "trial_id": row["trial_id"], "execution_id": eid, "workflow": row["workflow"],
            "goal_first_line": (str(row.get("goal") or "").strip().splitlines() or [""])[0],
            "leader": record.get("leader"),
            "members": [{"name": m.get("name"), "role": m.get("role")}
                        for m in record.get("members") or []],
            "state": item_state, "run_status": run_status, "decision": decision,
            "round": max((r["round"] for r in ledger.reviews_of(eid, host)), default=0),
            "cost_usd": reader.usage()["cost_usd"],
            "started_at": (orow or {}).get("started_at") or row.get("created_at"),
            "started_by": started_by,
            "ended_at": (orow or {}).get("at") if decision else None})
    return {"total": len(items), "trials": items[offset:offset + limit]}


@router.get("/runs/{execution_id}")
def team_run(execution_id: str) -> dict:
    """One team run, in the contract's order (section 5): its open waits, members, reviews,
    typed timeline, owner actions and outcome (read only from ``pi_team_outcomes``, A2)."""
    from temper_ai.api.routes import _waiting_gate_events
    from temper_ai.pi_agent.team_view import (
        TeamReader,
        members_view,
        open_waits_view,
        outcome_view,
        owner_actions,
        reviews_view,
        round_view,
        team_state,
        timeline,
    )

    ledger = _ledger()
    owners = _owners()
    run = _team_run(ledger, execution_id)
    reader = TeamReader(ledger, execution_id, run.host_path, run.leader)
    asked: dict[str, str] = {}
    for ev in _waiting_gate_events(execution_id):
        data = ev.get("data") or {}
        for key in (data.get("name"), data.get("gate_path")):
            if key:
                asked[key] = ev["id"]
    waits_open = open_waits_view(reader, asked)
    outcome = outcome_view(run.outcome, owners)
    actions = _caller_actions(execution_id)
    record = run.record
    done_project = ((run.outcome or {}).get("record") or {}).get("project") or {}
    project = record.get("project_path")
    return {
        "execution_id": execution_id,
        "trial_id": run.trial["trial_id"],
        "workflow": run.trial["workflow"],
        "run_status": run.run_status,
        "state": team_state(outcome=outcome, run_status=run.run_status,
                            open_waits=waits_open,
                            began=ledger.any_turn_began(execution_id, run.host_path)),
        "cost_usd": reader.usage()["cost_usd"],
        "account": _account_view(execution_id),
        "trial": {
            "goal": run.trial.get("goal"), "leader": run.leader,
            "members": [{"name": m.get("name"), "role": m.get("role"), "tools": m.get("tools"),
                         "leader": bool(m.get("leader"))} for m in run.members],
            "pause_after_rounds": record.get("pause_after_rounds"),
            "communication": record.get("communication") or "all",
            "project": ({"source": project, "start_commit": done_project.get("commit")}
                        if project else None),
            "started_at": run.trial.get("created_at"),
            "started_by": _started_by(actions, run.trial, owners),
            "request_id": run.trial.get("request_id")},
        "round": round_view(reader, record.get("pause_after_rounds")),
        "members": members_view(reader, run.members, waits_open),
        "open_waits": waits_open,
        "reviews": reviews_view(reader),
        "timeline": timeline(reader, owners),
        "owner_actions": owner_actions(reader, actions, owners),
        "outcome": outcome,
    }


def _account_view(execution_id: str) -> dict | None:
    """The run's one account by slot label (ADR-M4-09), as the Pi lane recorded it at start:
    never an email or an account id, and never the in-box provider name. ``capacity`` is
    ``not_checked`` for a run picked by the settings' order (ADR-M4-19), whose ``room`` is
    null: no figure is ever made up. A room pick records no ``capacity`` (null); its
    figures are in ``room``."""
    from temper_ai.pi_agent.accounts import run_account

    account = run_account(execution_id)
    if not account.get("slot"):
        return None
    return {"slot": account["slot"], "picked_at": account.get("picked_at"),
            "by": account.get("by"), "capacity": account.get("capacity"),
            "room": account.get("room")}


@router.get("/runs/{execution_id}/version")
def team_version(execution_id: str) -> dict:
    """The team's newest version (M3 contract team_version; ADR-M4-12 H, SW-36): served from
    the version record the Pi lane stored, never read from a copy. Its commit, the start
    commit, its files with sha256, and its diff against the start commit, cut past the cap
    with a note saying so. A version that held a login token is withheld: no files, no
    diff, the rules that matched only."""
    from temper_ai.pi_agent import team_versions

    ledger = _ledger()
    run = _team_run(ledger, execution_id)
    row = team_versions.latest(ledger.engine, execution_id, run.host_path)
    if row is None:
        raise HTTPException(status_code=404, detail=NO_VERSION)
    branch = ((run.outcome or {}).get("record") or {}).get("branch")
    made = branch.get("name") if isinstance(branch, dict) and branch.get("made") else None
    return team_versions.view(row, made)


@router.get("/runs/{execution_id}/messages/{message_id}")
def team_message_read(execution_id: str, message_id: str) -> dict:
    """The full text of one message of the team (the timeline shows a preview)."""
    from temper_ai.pi_agent.ledger import messages
    from temper_ai.pi_agent.team_leader import _at as _at_text

    ledger = _ledger()
    with ledger.engine.connect() as conn:
        row = conn.execute(sa.select(messages).where(
            messages.c.message_id == message_id,
            messages.c.run_id == execution_id)).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_MESSAGE)
    return {"message_id": row["message_id"], "from": row["sender"], "to": row["to_member"],
            "kind": row["kind"], "state": row["state"],
            "undelivered_reason": row["undelivered_reason"], "review_id": row["review_id"],
            "body": row["body"], "created_at": _at_text(row["created_at"]),
            "delivered_at": _at_text(row["delivered_at"])}


# --- trial start ----------------------------------------------------------------------------

@router.post("/trials", status_code=201)
def team_trial_start(body: TrialInput) -> dict:
    """Start a trial: build its workflow and member configs, check them exactly as a run start
    would (nothing is saved on a problem), save them frozen with the trial's row, and start the
    run with the input ``goal``."""
    from temper_ai.pi_agent import team_trials

    caller = require_caller_may("start")
    rid = _request_id(body.request_id)
    raw = body.model_dump()
    digest = team_trials.body_digest(raw)
    ledger = _ledger()
    first = team_trials.find(ledger, request_id=rid)
    if first is not None:
        return _repeat_start(ledger, first, digest, caller)
    with ledger.engine.connect() as conn:
        from temper_ai.pi_agent.ledger import requests

        if conn.execute(sa.select(requests.c.request_id).where(
                requests.c.request_id == rid)).first() is not None:
            raise _reused()
    check = _check({k: v for k, v in raw.items() if k != "request_id"})
    if not check.ok:
        raise TeamRefusal(400, {"problems": _findings(check.problems),
                                "notes": _findings(check.notes)})
    import uuid

    execution_id = str(uuid.uuid4())
    try:
        row = team_trials.save(ledger, check, request_id=rid, digest=digest,
                               execution_id=execution_id, by=caller.label,
                               source=display_source(caller))
    except IntegrityError:
        first = team_trials.find(ledger, request_id=rid)
        if first is None:
            raise
        return _repeat_start(ledger, first, digest, caller)
    return _finish_start(ledger, row, caller, notes=_findings(check.notes), repeated=False)


def _start_reply(row: dict, status: str, *, repeated: bool, notes: list[dict]) -> dict:
    return {"trial_id": row["trial_id"], "execution_id": row["execution_id"],
            "status": status, "workflow": row["workflow"], "repeated": repeated,
            "notes": notes}


def _repeat_notes(row: dict) -> list[dict]:
    from temper_ai.pi_agent.team_config import load_team_config
    from temper_ai.pi_agent.team_trials import _project_findings

    if not row.get("project"):
        return []
    return _findings(_project_findings(row["project"], load_team_config())[1])


def _repeat_start(ledger: Any, row: dict, digest: str, caller: Any) -> dict:
    """The same request id again: the first start's result, or a refusal when the body is
    different. A start whose run never began is finished now (once it is old enough that it
    isn't still under way)."""
    from temper_ai.api.routes import _run_row
    from temper_ai.pi_agent import team_trials

    if row["body_sha256"] != digest:
        raise _reused()
    notes = _repeat_notes(row)
    if row.get("start_status"):
        return _start_reply(row, row["start_status"], repeated=True, notes=notes)
    run = _run_row(row["execution_id"])
    if run is not None:
        team_trials.mark_started(ledger, row["trial_id"], "queued")
        return _start_reply(row, "queued", repeated=True, notes=notes)
    if team_trials.unfinished(row):
        return _finish_start(ledger, row, caller, notes=notes, repeated=True)
    return _start_reply(row, "queued", repeated=True, notes=notes)


def _finish_start(ledger: Any, row: dict, caller: Any, *, notes: list[dict],
                  repeated: bool) -> dict:
    """Start the saved trial's run. A start the run start refuses removes what was saved."""
    from temper_ai.api.routes import RunRequest, _start_run
    from temper_ai.pi_agent import team_trials

    request = RunRequest(workflow=row["workflow"], inputs={"goal": row["goal"]},
                         workspace_path=row.get("project"))
    try:
        response = _start_run(request, execution_id=row["execution_id"])
        status = response.status
    except HTTPException as exc:
        if exc.status_code == 409:  # already queued: an earlier copy of this start got there
            status = "queued"
        else:
            team_trials.undo(ledger, row)
            if exc.status_code in (400, 422):
                raise TeamRefusal(400, {"problems": [{"field": None,
                                                      "text": str(exc.detail)}],
                                        "notes": notes}) from exc
            raise
    except Exception:
        team_trials.undo(ledger, row)
        raise
    team_trials.mark_started(ledger, row["trial_id"], status)
    record_action(row["execution_id"], "start", caller, workflow=row["workflow"],
                  trial_id=row["trial_id"], request_id=row["request_id"])
    return _start_reply(row, status, repeated=repeated, notes=notes)


# --- answers --------------------------------------------------------------------------------

def _answer_problem(kind: str, subject: dict, leader: str, answer: str, text: str) -> str | None:
    """What is wrong with this answer to this wait, before anything is recorded."""
    from temper_ai.pi_agent.team_config import LIMITS
    from temper_ai.pi_agent.team_view import answers_for
    from temper_ai.shared.text_limits import too_long

    offered = answers_for(kind, subject, leader)
    words = [a["answer"] for a in offered]
    chosen = next((a for a in offered if a["answer"] == answer), None)
    if chosen is None:
        return f"'{answer}' is not an answer to this question (answers: {', '.join(words)})"
    if chosen["needs_text"] == "required" and not text.strip():
        if answer == "guide":
            return f"'guide' needs the words to pass to {leader}"
        return f"'{answer}' needs the words to pass to {subject.get('member') or 'the member'}"
    if chosen["needs_text"] == "none" and text.strip():
        return f"'{answer}' takes no words"
    limit = ANSWER_LIMITS.get(answer)
    if limit and len(text) > LIMITS[limit[0]]:
        return too_long(limit[1], len(text), LIMITS[limit[0]])
    return None


def _gate_history(execution_id: str, gate_name: str) -> list[dict]:
    from temper_ai.observability.recorder import gate_events
    from temper_ai.stage.gate import names_gate

    return [ev for ev in gate_events(execution_id) if names_gate(ev.get("data") or {}, gate_name)]


def _answered_refusal(execution_id: str, wait: dict, owners: tuple[str, ...]) -> TeamRefusal:
    """A 409 for a wait already answered, with who answered it and where from (M3 E21)."""
    from temper_ai.pi_agent.team_outcome import UNKNOWN_CALLER, by_name
    from temper_ai.pi_agent.team_view import SOURCES, utc_text
    from temper_ai.stage.gate import WAITING, describe_gate, refusal

    events = [ev for ev in _gate_history(execution_id, wait["gate_name"])
              if describe_gate(ev)["status"] != WAITING]
    decision = wait.get("decision") or {}
    if events:
        ev = events[-1]
        data = ev.get("data") or {}
        g = describe_gate(ev)
        by = by_name(data.get("gate_caller"), owners) or UNKNOWN_CALLER
        source = data.get("gate_caller_source")
    else:
        g = {"event_id": None, "node_name": wait["gate_name"], "path": wait["gate_name"],
             "round": None, "status": "approved", "answered_at": wait.get("decided_at"),
             "request_id": decision.get("request_id"), "replaced_by": None,
             "opened_at": wait.get("opened_at")}
        by = by_name(decision.get("by"), owners) or UNKNOWN_CALLER
        source = decision.get("source")
    g["answered_by"] = by
    # a wait's opened_at is its event's timestamp, which has no zone: sent with +00:00 (#60)
    for field in ("opened_at", "answered_at"):
        g[field] = utc_text(g.get(field))
    body = refusal(g)
    body["answered_source"] = source if source in SOURCES else "unknown"
    return TeamRefusal(409, body)


def _wait_row(ledger: Any, wait_id: str) -> dict | None:
    from temper_ai.pi_agent.ledger import waits

    with ledger.engine.connect() as conn:
        row = conn.execute(sa.select(waits).where(waits.c.wait_id == wait_id)).mappings().first()
    return dict(row) if row else None


@router.post("/runs/{execution_id}/waits/{wait_id}/answer")
def team_answer(execution_id: str, wait_id: str, body: AnswerBody) -> dict:
    """Answer the open wait Temper asks, with one of its own answers (M3 contract 6.3). It is
    decided through the approve route's own code, as a typed response."""
    from temper_ai.api.routes import GateApproval, _now_iso, approve_wait
    from temper_ai.pi_agent.team_leader import WAIT_KIND_SHOWN
    from temper_ai.pi_agent.team_outcome import by_name
    from temper_ai.pi_agent.team_trials import body_digest
    from temper_ai.pi_agent.team_view import response_for

    caller = require_caller_may("approve", run_id=execution_id)
    rid = _request_id(body.request_id)
    ledger = _ledger()
    owners = _owners()
    answer, text = body.answer.strip(), body.text.strip()
    digest = body_digest({"wait_id": wait_id, "answer": answer, "text": text})
    first = _seen(ledger, rid, execution_id, "answer", digest)
    if first is not None:
        return first
    run = _team_run(ledger, execution_id)
    wait = _wait_row(ledger, wait_id)
    if wait is None or (wait["run_id"], wait["host_path"]) != (execution_id, run.host_path):
        raise HTTPException(status_code=404, detail=NO_LONGER_OPEN)
    if wait["state"] == "decided":
        raise _answered_refusal(execution_id, wait, owners)
    if wait["state"] != "open":
        raise HTTPException(status_code=404, detail=NO_LONGER_OPEN)
    open_now = ledger.open_waits(execution_id, run.host_path)
    if not open_now or open_now[0]["wait_id"] != wait_id:
        raise TeamRefusal(409, {"reason": "not_asked_yet", "message": NOT_ASKED_YET})
    asking = _gate_history(execution_id, wait["gate_name"])
    if not asking:
        raise TeamRefusal(409, {"reason": "not_asked_yet", "message": NOT_ASKED_YET})
    kind = WAIT_KIND_SHOWN.get(wait["kind"], wait["kind"])
    problem = _answer_problem(kind, wait["subject"] or {}, run.leader, answer, text)
    if problem:
        raise TeamRefusal(400, {"problem": problem})
    approval = GateApproval(response=response_for(kind, answer, text),
                            event_id=asking[-1]["id"], request_id=rid)
    try:
        reply = approve_wait(execution_id, wait["gate_name"], approval, caller)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise _answered_refusal(execution_id, _wait_row(ledger, wait_id) or wait,
                                    owners) from exc
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=NO_LONGER_OPEN) from exc
        raise
    needs_resume = bool(reply.get("needs_resume"))
    result = {"status": "approved", "wait_id": wait_id, "event_id": asking[-1]["id"],
              "answer": answer, "text": text or None, "repeated": bool(reply.get("repeated")),
              "carries_on": bool(reply.get("carries_on", not needs_resume)),
              "needs_resume": needs_resume, "by": by_name(caller.label, owners),
              "at": reply.get("answered_at") or _now_iso()}
    if reply.get("message"):
        result["message"] = reply["message"]
    _remember(ledger, rid, execution_id, "answer", digest, result)
    return result


# --- messages -------------------------------------------------------------------------------

@router.post("/runs/{execution_id}/messages", status_code=201)
def team_message_post(execution_id: str, body: MessageBody) -> dict:
    """Message a member as the owner. Held while any wait is open (every member's turn waits
    then), else it reaches the member at its next turn."""
    from temper_ai.pi_agent.ledger import LedgerConflict
    from temper_ai.pi_agent.team_config import LIMITS
    from temper_ai.pi_agent.team_outcome import by_name
    from temper_ai.pi_agent.team_trials import body_digest
    from temper_ai.shared.text_limits import too_long

    caller = require_caller_may("approve", run_id=execution_id)
    rid = _request_id(body.request_id)
    ledger = _ledger()
    owners = _owners()
    to = body.to.strip()
    digest = body_digest({"to": to, "body": body.body})
    first = _seen(ledger, rid, execution_id, "message", digest)
    if first is not None:
        return first
    run = _team_run(ledger, execution_id)
    names = [str(m.get("name")) for m in run.members]
    not_member = f"'{to}' is not a member of this team (members: {', '.join(names)})"
    if to not in names:
        raise TeamRefusal(400, {"problem": not_member})
    if not body.body.strip():
        raise TeamRefusal(400, {"problem": EMPTY_MESSAGE})
    if len(body.body) > LIMITS["message_max_chars"]:
        raise TeamRefusal(400, {"problem": too_long("the message", len(body.body),
                                                    LIMITS["message_max_chars"])})
    if _ended(run):
        raise TeamRefusal(409, {"reason": "team_ended", "message": TEAM_ENDED})
    if not ledger.participants_of(execution_id, run.host_path):
        raise TeamRefusal(409, {"reason": "team_not_started", "message": TEAM_NOT_STARTED})
    try:
        posted = ledger.post(execution_id, run.host_path, to, body.body, sender="owner",
                             sender_kind="owner", kind="owner_reply", dedupe_key=rid)
    except LedgerConflict as exc:
        raise _reused() from exc
    if posted["state"] == "undelivered":
        why = posted.get("undelivered_reason")
        if why == "recipient_retired":
            raise TeamRefusal(409, {"reason": "member_ended",
                                    "message": f"'{to}' has left the team; nothing was sent"})
        if why == "recipient_unknown":
            raise TeamRefusal(400, {"problem": not_member})
        raise TeamRefusal(409, {"reason": "team_ended", "message": TEAM_ENDED})
    held = bool(ledger.open_waits(execution_id, run.host_path))
    if not posted.get("duplicate"):
        record_action(execution_id, "message", caller, to=to, message_id=posted["message_id"],
                      request_id=rid)
    result = {"message_id": posted["message_id"], "to": to,
              "state": "held" if held else "pending",
              "delivers": "after_open_wait" if held else "next_turn",
              "repeated": bool(posted.get("duplicate")), "by": by_name(caller.label, owners),
              "at": str(posted.get("created_at"))}
    _remember(ledger, rid, execution_id, "message", digest, result)
    return result
