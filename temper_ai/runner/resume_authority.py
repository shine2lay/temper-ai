"""DB-only resume admission and token-owned recovery, before any runtime opens.

A refusal is an attempt diagnostic, never a run outcome. Queue reservations retain
what enqueue replaces; only their owner may restore it. See docs/pi-agent.md.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from weakref import WeakValueDictionary

from sqlalchemy import exists, update
from sqlmodel import Session, col, select

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.database import get_database, get_session
from temper_ai.observability.models import Event
from temper_ai.runner.models import ResumeClaim, WorkflowRun
from temper_ai.shared.clock import as_utc, utcnow
from temper_ai.shared.types import NodeResult

logger = logging.getLogger(__name__)

RESERVATION_KEY = "resume_reservation"
RESERVATION_ENV = "TEMPER_RESUME_RESERVATION"
RESERVED_KEYS = (RESERVATION_KEY, "resume_authority", "resume_prior_projection", "resume_refusal")
RESUME_ATTEMPT_REFUSED_EXIT = 7
_PENDING = ("reserved", "refused", "invalid")
_SQLITE_LOCK = threading.RLock()
_LAUNCH_BINDING: ContextVar[tuple[str, str] | None] = ContextVar("resume_launch", default=None)
_ISSUED_LOCK = threading.Lock()
_ISSUED: WeakValueDictionary[int, ResumeAdmission] = WeakValueDictionary()
# Queue changes these fields. Worker attempt counts and append-only audit history are
# deliberately outside this projection; cancellation is checked separately before restore.
_PROJECTION = ("workflow_name", "workspace_path", "inputs", "status", "spawner_kind",
               "spawner_handle", "cancel_requested", "created_at", "started_at",
               "completed_at", "result", "error")
_TIMES = ("created_at", "started_at", "completed_at")


class ResumeAttemptRefused(RuntimeError):
    """This attempt was not admitted; no adapter may turn it into run failure."""

    def __init__(self, code: str, *, execution_id: str = "", token: str | None = None):
        super().__init__(code)
        self.code = code
        self.execution_id = execution_id
        self.token = token
        self.recorded = False
        self.restored = False
        self.seen_attempt: str | None = None
        self.seen_claims: dict[str, Any] | None = None
        # Only an issued admission, or this helper's own unconfirmed commit,
        # may restore an admitted capsule. A duplicate token is not permission.
        self.allow_admitted_restore = False


class ResumeAuthorityUnreadable(ResumeAttemptRefused):
    """Unknown saved authority, not genuine absence or a fabricated cancellation."""

    def __init__(self, *, execution_id: str = "", token: str | None = None,
                 code: str = "resume_authority_unreadable"):
        super().__init__(code, execution_id=execution_id, token=token)


@dataclass(frozen=True)
class ResumeAuthority:
    """Trusted checkpoint snapshot, bound to the seen attempt and claim ownership."""

    version: str
    state: dict[str, Any]
    outputs: dict[str, NodeResult]
    attempt: str
    claims: dict[str, Any]
    prior: dict[str, Any] | None

    @property
    def stopped(self) -> bool:
        marker = self.state.get("self_cancelled")
        return isinstance(marker, dict) and bool(marker.get("path"))


@dataclass(frozen=True)
class ResumeAdmission:
    """Permission already committed before runtime; never supplied by a request."""

    authority: ResumeAuthority
    token: str | None = None
    execution_id: str = ""


def require_admitted_resume(execution_id: str, admission: ResumeAdmission) -> None:
    """Reject a caller-constructed baseline/permission, even at the Python boundary."""
    with _ISSUED_LOCK:
        issued = _ISSUED.get(id(admission)) is admission
    if not issued or admission.execution_id != execution_id:
        raise ResumeAttemptRefused("resume_admission_not_issued", execution_id=execution_id)


def read_resume_authority(execution_id: str, *,
                          checkpoint_service: CheckpointService | None = None) -> ResumeAuthority:
    """Read authority before claims, hold take-over, enqueue or runtime registration.

    Only this DB-reader scope translates faults into typed refusal. No execution or
    revised-configuration exception is caught here. Empty successful history is valid.
    """
    seen_attempt: str | None = None
    seen_claims: dict[str, Any] | None = None
    saved_marker: dict[str, Any] | None = None
    prior: dict[str, Any] | None = None
    try:
        with get_session() as session:
            row = session.get(WorkflowRun, execution_id)
            attempt, claims = _attempt_and_claims(session, execution_id)
            seen_attempt, seen_claims = attempt, claims
            ended = session.get(Event, attempt) if attempt else None
            raw_stop = (ended.data or {}).get("stopped") if ended is not None else None
            if (ended is not None and ended.status == "cancelled" and isinstance(raw_stop, dict)
                    and raw_stop.get("kind") == "cancelled"
                    and isinstance(raw_stop.get("path"), str) and raw_stop["path"]):
                saved_marker = {"path": raw_stop["path"], "reason": raw_stop.get("reason")}
            if ended is not None:
                data = ended.data or {}
                began = as_utc(ended.timestamp)
                if began is None:
                    raise ValueError("Missing original attempt time")
                prior = {"status": ended.status,
                         "result": {k: data[k] for k in ("cost_usd", "total_tokens") if k in data},
                         "error": ({"message": data["error"]} if data.get("error") else None),
                         "started_at": began.isoformat(), "completed_at": None}
            if row is not None:
                prior = capture_projection(row)
        cp = checkpoint_service or CheckpointService(execution_id)
        version, state, outputs = cp.resume_snapshot()
        if not isinstance(state, dict) or not isinstance(outputs, dict) or not isinstance(version, str):
            raise ValueError("Malformed resume authority")
        marker = state.get("self_cancelled")
        if marker is not None and (not isinstance(marker, dict) or not isinstance(marker.get("path"), str)
                                   or not marker["path"]):
            raise ValueError("Malformed saved stop")
        if saved_marker is not None:
            state = {**state, "self_cancelled": saved_marker}
        return ResumeAuthority(version, state, outputs, attempt, claims, prior)
    except ResumeAttemptRefused:
        raise
    except Exception:
        # A positive saved run-stop is authority too. Failed checkpoint reconciliation
        # does not turn it into an unknown or a new outcome. This snapshot only observes;
        # stopped=True prevents reservation, runtime registration or producer permission.
        if saved_marker is not None and seen_attempt is not None:
            return ResumeAuthority(f"saved-stop:{seen_attempt}", {"self_cancelled": saved_marker},
                                   {}, seen_attempt, seen_claims or {}, prior)
        # Bounded reason only: no SQL parameters, checkpoint contents or original output.
        refused = ResumeAuthorityUnreadable(execution_id=execution_id)
        refused.seen_attempt, refused.seen_claims = seen_attempt, seen_claims
        raise refused from None


def stopped_metrics(authority: ResumeAuthority) -> tuple[float, int, str | None]:
    """Original cancellation/costs without loading a producer or revised runtime."""
    if not authority.stopped:
        raise ValueError("No qualifying saved stop")
    marker = authority.state["self_cancelled"]
    results = {**authority.outputs, **(authority.state.get("self_cancelled_results") or {})}
    outer = {p: r for p, r in results.items() if not any(p.startswith(f"{q}.") for q in results if q != p)}
    total = (authority.prior or {}).get("result") or {}
    cost = total.get("cost_usd", sum(r.cost_usd for r in outer.values()))
    tokens = total.get("total_tokens", sum(r.total_tokens for r in outer.values()))
    reason = marker.get("reason")
    return cost, tokens, str(reason) if reason is not None else None


def record_saved_stop(execution_id: str, authority: ResumeAuthority) -> None:
    """State-only observation; even a reconciliation fault cannot change the old outcome."""
    if not authority.stopped:
        raise ValueError("No qualifying saved stop")
    try:
        with get_session() as session:
            session.add(Event(type="caller.action", execution_id=execution_id, data={
                "action": "resume_saved_stop", "diagnostic": "saved_stop_retained",
                "checkpoint_version": authority.version,
            }))
    except Exception:
        logger.warning("Run %s: saved cancellation retained; state-only observation unavailable",
                       execution_id)


def automatic_resume_refused(execution_id: str) -> bool:
    """A refused attempt waits for an explicit Resume, never a startup/reaper retry.

    The diagnostic is separate from the canonical outcome. It also covers a refusal
    before queue mutation (which has no reservation). A new admitted attempt supersedes
    it with its own workflow.started event, not by modifying an answer or a wait.
    """
    try:
        with get_session() as session:
            latest = session.exec(select(Event).where(Event.execution_id == execution_id,
                                                     Event.type == "workflow.started")
                                  .order_by(col(Event.timestamp).desc()).limit(1)).first()
            refused = session.exec(select(Event).where(
                Event.execution_id == execution_id, Event.type == "caller.action",
                col(Event.data)["action"].as_string() == "resume_attempt_refused",
                col(Event.data)["blocks_auto_resume"].as_boolean().is_(True),
            ).order_by(col(Event.timestamp).desc()).limit(1)).first()
            blocked = (refused is not None and ((refused.data or {}).get("from_attempt")
                       == (latest.id if latest is not None else "")))
            if blocked and refused is not None:
                row = session.get(WorkflowRun, execution_id)
                capsule = reservation(row.spawner_metadata if row is not None else None)
                if (capsule is not None and capsule.get("phase") == "reserved"
                        and capsule.get("token") != (refused.data or {}).get("reservation_token")):
                    reserved_at = as_utc(datetime.fromisoformat(capsule["reserved_at"]))
                    refused_at = as_utc(refused.timestamp)
                    if reserved_at is not None and refused_at is not None and reserved_at > refused_at:
                        return False  # A newly validated explicit Resume supersedes the refusal.
            return blocked
    except Exception:
        raise ResumeAuthorityUnreadable(execution_id=execution_id) from None


def mark_admitted_resume_running(admission: ResumeAdmission, *, handle: str) -> None:
    """Only the admitted reservation may cross into running; never undo a newer cancel."""
    execution_id = admission.execution_id
    require_admitted_resume(execution_id, admission)
    try:
        with one_resume_at_a_time(), get_session() as session:
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)
                               .with_for_update()).first()
            capsule = reservation(row.spawner_metadata if row is not None else None)
            if row is None or capsule is None or admission.token is None:
                raise ResumeAttemptRefused("resume_owner_changed", execution_id=execution_id,
                                           token=admission.token)
            won = session.exec(update(WorkflowRun).where(  # type: ignore[call-overload]
                *_owner_where(execution_id, capsule, admission.token, phases=("admitted",)),
            ).values(status="running", started_at=utcnow(), spawner_handle=handle,
                     attempts=WorkflowRun.attempts + 1)
              .execution_options(synchronize_session=False)).rowcount == 1
            if not won:
                raise ResumeAttemptRefused("resume_owner_changed", execution_id=execution_id,
                                           token=admission.token)
    except ResumeAttemptRefused:
        raise
    except Exception:
        raise ResumeAuthorityUnreadable(execution_id=execution_id, token=admission.token,
                                        code="resume_running_unconfirmed") from None


def capture_projection(row: WorkflowRun) -> dict[str, Any]:
    """Capture the server-owned baseline before enqueue clears any terminal field."""
    prior = {key: deepcopy(getattr(row, key)) for key in _PROJECTION}
    for key in _TIMES:
        at = as_utc(prior[key])
        prior[key] = at.isoformat() if at is not None else None
    prior["metadata"] = {k: deepcopy(v) for k, v in (row.spawner_metadata or {}).items()
                         if k not in RESERVED_KEYS}
    return prior


def reserve_resume(session: Session, row: WorkflowRun, metadata: dict[str, Any], *,
                   created_for_resume: bool = False) -> tuple[dict[str, Any], ResumeAuthority]:
    """Queue's shared invariant: read first, then atomically retain its old projection.

    The caller already holds the row lock and has not cleared it. Authority/baseline
    are never accepted from caller extra. A known stop must not be put in the queue.
    """
    authority = read_resume_authority(row.execution_id)
    if authority.stopped:
        return metadata, authority
    attempt, claims = _attempt_and_claims(session, row.execution_id)
    if (attempt, claims) != (authority.attempt, authority.claims):
        raise ResumeAttemptRefused("resume_owner_changed", execution_id=row.execution_id)
    prior = capture_projection(row)
    try:
        if created_for_resume:
            # In-process runs predate the spawner row: their original visible outcome
            # is the workflow event. Read it before inserting the first canonical row,
            # not from that row's new queued defaults. No original means no baseline.
            if authority.prior is None:
                raise ResumeAuthorityUnreadable(execution_id=row.execution_id,
                                                code="resume_original_projection_missing")
            prior.update(deepcopy(authority.prior))
        _validate_projection(prior, row.execution_id, None)
    except ResumeAttemptRefused as refused:
        # A successful authority read observes even an empty original-attempt identity.
        # Bind quarantine to that SAME attempt/claim, never to a later owner. Otherwise
        # a missing-original refusal would be retried automatically on every scan.
        refused.seen_attempt, refused.seen_claims = attempt, deepcopy(claims)
        raise
    capsule = {
        "token": uuid.uuid4().hex,
        "execution_id": row.execution_id,
        "phase": "reserved",
        "version": authority.version,
        "from_attempt": attempt,
        "claims": claims,
        "prior": prior,
        "created_for_resume": created_for_resume,
        "reserved_at": utcnow().isoformat(),
    }
    return {**metadata, RESERVATION_KEY: capsule}, authority


def admit_resume(execution_id: str, *, expected_token: str | None = None,
                 expected_attempt: str | None = None) -> ResumeAdmission:
    """Re-read and commit permission before mark-running/bootstrap/preconnect.

    A spawned box carries its token in RESERVATION_ENV. A direct/inprocess caller
    has no queued capsule; its successful read still precedes all runtime work.
    """
    token = expected_token
    admitted_here = False
    try:
        with one_resume_at_a_time(), get_session() as session:
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)
                               .with_for_update()).first()
            capsule = reservation(row.spawner_metadata if row is not None else None)
            queued_resume = (row is not None and (row.spawner_metadata or {}).get("start") == "resume"
                             and (row.status in ("queued", "running") or expected_token is not None))
            if queued_resume:
                assert row is not None
                if capsule is None:
                    raise ResumeAuthorityUnreadable(execution_id=execution_id, token=token,
                                                    code="resume_reservation_missing")
                if token is None:
                    raise ResumeAttemptRefused("resume_reservation_token_required", execution_id=execution_id)
                if capsule.get("phase") != "reserved" or not _owned(session, row, capsule, token):
                    raise ResumeAttemptRefused("resume_owner_changed", execution_id=execution_id, token=token)
                _validate_projection(capsule.get("prior"), execution_id, token)
            authority = read_resume_authority(execution_id)
            if expected_attempt is not None and authority.attempt != expected_attempt:
                raise ResumeAttemptRefused("resume_owner_changed", execution_id=execution_id, token=token)
            if queued_resume and row is not None and row.cancel_requested:
                raise ResumeAttemptRefused("resume_cancel_requested", execution_id=execution_id, token=token)
            if queued_resume:
                assert row is not None and capsule is not None
                if authority.version != capsule.get("version"):
                    raise ResumeAttemptRefused("resume_authority_changed", execution_id=execution_id, token=token)
                admitted = {**capsule, "phase": "admitted", "admitted_at": utcnow().isoformat()}
                won = session.exec(update(WorkflowRun).where(  # type: ignore[call-overload]
                    *_owner_where(execution_id, capsule, token, phases=("reserved",)),
                ).values(spawner_metadata={**(row.spawner_metadata or {}), RESERVATION_KEY: admitted})
                  .execution_options(synchronize_session=False)).rowcount == 1
                if not won:
                    raise ResumeAttemptRefused("resume_owner_changed", execution_id=execution_id, token=token)
                admitted_here = True
                capsule = admitted
                # Use the BEFORE-enqueue baseline, never the now-cleared canonical row.
                authority = ResumeAuthority(authority.version, authority.state, authority.outputs,
                                            authority.attempt, authority.claims, deepcopy(capsule["prior"]))
            admission = ResumeAdmission(authority, token, execution_id)
        # The transaction has committed before anyone may exercise producer permission.
        with _ISSUED_LOCK:
            _ISSUED[id(admission)] = admission
        return admission
    except ResumeAttemptRefused as caught_refusal:
        if caught_refusal.token is None:
            caught_refusal.token = token
        caught_refusal.allow_admitted_restore = admitted_here
        raise
    except Exception:
        # This scope contains only DB admission, never runtime/configuration work.
        refused = ResumeAuthorityUnreadable(execution_id=execution_id, token=token,
                                           code="resume_admission_unconfirmed")
        refused.allow_admitted_restore = admitted_here
        raise refused from None


def reservation(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """The internal reservation, never a caller-supplied baseline."""
    raw = (metadata or {}).get(RESERVATION_KEY)
    return deepcopy(raw) if isinstance(raw, dict) else None


def reservation_never_admitted(metadata: dict[str, Any] | None, *,
                              execution_id: str | None = None) -> bool:
    """No generic terminal write for a refused/not-started reservation.

    A lost admission-commit acknowledgement can leave 'admitted' in the DB
    without ever issuing producer permission. Once its box is gone, an unchanged
    workflow.started fence distinguishes that from a workflow that did start.
    """
    capsule = reservation(metadata)
    if capsule is None:
        # A resumed row with a missing baseline is still not permission to
        # manufacture failure/orphaning, transfer holds or automatically retry it.
        return (metadata or {}).get("start") == "resume"
    if capsule.get("phase") in (*_PENDING, "recovered"):
        return True
    if capsule.get("phase") != "admitted" or execution_id is None:
        return False
    try:
        with get_session() as session:
            attempt, _claims = _attempt_and_claims(session, execution_id)
            return attempt == capsule.get("from_attempt")
    except Exception:
        raise ResumeAuthorityUnreadable(execution_id=execution_id, token=_token(capsule),
                                        code="resume_recovery_unreadable") from None


@contextmanager
def bind_resume_launch(execution_id: str, token: str | None) -> Iterator[None]:
    """The watcher's observed reservation follows only this spawn, not a later row.

    This transport is not workflow admission. A ContextVar avoids changing fresh
    spawners' interface/DB dependence or leaking a token across parallel launches.
    """
    mark = _LAUNCH_BINDING.set((execution_id, token) if token is not None else None)
    try:
        yield
    finally:
        _LAUNCH_BINDING.reset(mark)


def launch_resume_token(execution_id: str) -> str | None:
    binding = _LAUNCH_BINDING.get()
    return binding[1] if binding is not None and binding[0] == execution_id else None


def refuse_resume(execution_id: str, refused: ResumeAttemptRefused, *,
                  expected_handle: str | None = None) -> bool:
    """Restore only this reservation's baseline, and append a nonterminal diagnostic.

    False means the DB/fence/baseline would not permit restoration. It is not permission
    for failure, retry or cleanup. A surviving reserved capsule remains recoverable.
    """
    if refused.recorded:
        return refused.restored
    restored = False
    try:
        with one_resume_at_a_time(), get_session() as session:
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)
                               .with_for_update()).first()
            capsule = reservation(row.spawner_metadata if row is not None else None)
            phases = (*_PENDING, "admitted") if refused.allow_admitted_restore else _PENDING
            if (row is not None and capsule is not None and refused.token is not None
                    and refused.code not in ("resume_owner_changed", "resume_cancel_requested")
                    and _token(capsule) == refused.token and capsule.get("phase") in phases):
                # A refusal at an adapter's final admission transition can occur after
                # permission committed but before workflow.started. The same original
                # attempt/claim/cancel fence applies; not a later started workflow.
                where = _owner_where(execution_id, capsule, refused.token,
                                     phases=phases, expected_handle=expected_handle)
                try:
                    prior = _validate_projection(capsule.get("prior"), execution_id, refused.token)
                except ResumeAuthorityUnreadable:
                    metadata = {**(row.spawner_metadata or {}), RESERVATION_KEY: {
                        **capsule, "phase": "invalid", "refusal": "resume_baseline_unreadable"}}
                    session.exec(update(WorkflowRun).where(*where).values(  # type: ignore[call-overload]
                        spawner_metadata=metadata).execution_options(synchronize_session=False))
                else:
                    # SQL compare-and-set fences SQLite too: its process lock does not
                    # serialize an independent cancel writer or another process.
                    # Import after registration: lanes -> loader -> PiHost -> lanes
                    # otherwise forms a cycle when Pi is enabled in a fresh worker.
                    from temper_ai.runner.lanes import LANE_RECORD_KEY
                    audit = {k: deepcopy(v) for k, v in (row.spawner_metadata or {}).items()
                             if k in ("box_profile", LANE_RECORD_KEY)}
                    metadata = {**deepcopy(prior["metadata"]), **audit, RESERVATION_KEY: {
                        **capsule, "phase": "recovered", "refusal": refused.code,
                        "refused_at": utcnow().isoformat()}}
                    restored = session.exec(update(WorkflowRun).where(*where).values(  # type: ignore[call-overload]
                        **{k: prior[k] for k in _PROJECTION}, spawner_metadata=metadata,
                    ).execution_options(synchronize_session=False)).rowcount == 1
                    if restored:
                        _release_owned_claims(session, execution_id, capsule)
            attempt, current_claims = _attempt_and_claims(session, execution_id)
            if refused.token is not None:
                owned = (capsule is not None and _token(capsule) == refused.token
                         and attempt == capsule.get("from_attempt")
                         and current_claims == capsule.get("claims"))
            else:
                # An unreadable pre-request identity must not pin a later owner.
                owned = (refused.seen_attempt is not None and attempt == refused.seen_attempt
                         and current_claims == refused.seen_claims)
                if (refused.code == "resume_reservation_missing" and row is not None
                        and capsule is None and row.status == "queued" and not row.cancel_requested
                        and (row.spawner_metadata or {}).get("start") == "resume"):
                    owned = True  # Unknown baseline stays held, not retried each scan.
            blocks_auto = (restored or owned) and refused.code not in (
                "resume_owner_changed", "resume_cancel_requested", "resume_requires_explicit_request",
            )
            session.add(Event(type="caller.action", execution_id=execution_id, data={
                "action": "resume_attempt_refused", "diagnostic": refused.code,
                "reservation_token": refused.token, "restored": restored,
                "from_attempt": attempt, "blocks_auto_resume": blocks_auto,
            }))
        refused.recorded = True
        refused.restored = restored
    except Exception:
        logger.warning("Run %s: resume refusal awaits token-fenced DB recovery", execution_id)
    return restored


def refuse_admitted_resume(execution_id: str, refused: ResumeAttemptRefused,
                          admission: ResumeAdmission) -> bool:
    """Only the issued grant may roll back its admitted-but-not-started attempt."""
    require_admitted_resume(execution_id, admission)
    if refused.token is None:
        refused.token = admission.token
    refused.allow_admitted_restore = True
    return refuse_resume(execution_id, refused)


def recover_resume_reservation(execution_id: str, *, expected_token: str,
                               expected_handle: str | None = None,
                               box_proved_gone: bool = False) -> bool:
    """Recover an ungranted reservation; granted ones also require THIS box proved gone.

    Also recovers a lost commit acknowledgement. The atomic original-attempt,
    token, claim, handle and independent-cancel predicates still gate the write.
    Never automatically retries or closes a viewer/wait/setup resource.
    """
    refused = ResumeAttemptRefused("resume_attempt_not_admitted",
                                   execution_id=execution_id, token=expected_token)
    refused.allow_admitted_restore = box_proved_gone
    return refuse_resume(execution_id, refused, expected_handle=expected_handle)


@contextmanager
def one_resume_at_a_time() -> Iterator[None]:
    """SQLite process serialization; Postgres uses the canonical row lock."""
    sqlite = get_database().engine.dialect.name == "sqlite"
    with _SQLITE_LOCK if sqlite else nullcontext():
        yield


def _token(capsule: dict[str, Any]) -> str | None:
    value = capsule.get("token")
    return value if isinstance(value, str) and value else None


def _attempt_and_claims(session: Session, execution_id: str) -> tuple[str, dict[str, Any]]:
    latest = session.exec(select(Event).where(Event.execution_id == execution_id,
                                             Event.type == "workflow.started")
                          .order_by(col(Event.timestamp).desc()).limit(1)).first()
    attempt = latest.id if latest is not None else ""
    resume_claim = session.get(ResumeClaim, execution_id)
    claims: dict[str, Any] = {}
    if resume_claim is not None:
        claims["resume"] = {"token": resume_claim.token, "from_attempt": resume_claim.from_attempt}
    if latest is not None:
        parked = (latest.data or {}).get("parked") or {}
        if isinstance(parked, dict) and parked.get("carried_on_at"):
            claims["parked"] = {"id": latest.id, "carried_on_at": parked["carried_on_at"]}
    return attempt, claims


def _owned(session: Session, row: WorkflowRun, capsule: dict[str, Any], token: str | None) -> bool:
    if (token is None or _token(capsule) != token or capsule.get("phase") not in _PENDING
            or row.cancel_requested):
        return False
    attempt, claims = _attempt_and_claims(session, row.execution_id)
    return attempt == capsule.get("from_attempt") and claims == capsule.get("claims")


def _owner_where(execution_id: str, capsule: dict[str, Any], token: str | None, *,
                 phases: tuple[str, ...] = _PENDING, expected_handle: str | None = None) -> list[Any]:
    """Atomic owner/claim/cancel predicates, not just a stale object check."""
    meta = col(WorkflowRun.spawner_metadata)
    where = [col(WorkflowRun.execution_id) == execution_id,
             col(WorkflowRun.cancel_requested).is_(False),
             col(WorkflowRun.status).in_(("queued", "running")),
             meta[RESERVATION_KEY]["token"].as_string() == token,
             meta[RESERVATION_KEY]["execution_id"].as_string() == execution_id,
             meta[RESERVATION_KEY]["phase"].as_string().in_(phases),
             meta[RESERVATION_KEY]["version"].as_string() == capsule.get("version")]
    if expected_handle is not None:
        where.append(col(WorkflowRun.spawner_handle) == expected_handle)
    latest = select(Event.id).where(Event.execution_id == execution_id, Event.type == "workflow.started")\
        .order_by(col(Event.timestamp).desc()).limit(1).scalar_subquery()
    attempt = capsule.get("from_attempt")
    where.append(latest == attempt if attempt else latest.is_(None))
    claims = capsule.get("claims") or {}
    claim = select(ResumeClaim.execution_id).where(ResumeClaim.execution_id == execution_id)
    resume = claims.get("resume")
    if isinstance(resume, dict):
        where.append(exists(claim.where(ResumeClaim.token == resume.get("token"),
                                        ResumeClaim.from_attempt == resume.get("from_attempt"))))
    else:
        where.append(~exists(claim))
    parked = claims.get("parked")
    if isinstance(parked, dict):
        where.append(exists(select(Event.id).where(
            Event.id == parked.get("id"),
            col(Event.data)["parked"]["carried_on_at"].as_string() == parked.get("carried_on_at"),
        )))
    elif attempt:
        where.append(exists(select(Event.id).where(
            Event.id == attempt, col(Event.data)["parked"]["carried_on_at"].as_string().is_(None),
        )))
    return where


def _validate_projection(raw: Any, execution_id: str, token: str | None) -> dict[str, Any]:
    try:
        if not isinstance(raw, dict) or not all(k in raw for k in (*_PROJECTION, "metadata")):
            raise ValueError("Missing server projection")
        if (not isinstance(raw["status"], str) or not isinstance(raw["metadata"], dict)
                or not isinstance(raw["inputs"], dict) or not isinstance(raw["cancel_requested"], bool)):
            raise ValueError("Malformed server projection")
        prior = deepcopy(raw)
        for key in _TIMES:
            at = prior[key]
            prior[key] = as_utc(datetime.fromisoformat(at)) if at is not None else None
        return prior
    except Exception:
        raise ResumeAuthorityUnreadable(execution_id=execution_id, token=token,
                                        code="resume_baseline_unreadable") from None


def _release_owned_claims(session: Session, execution_id: str, capsule: dict[str, Any]) -> None:
    # Ownership was checked under the row lock; each release is conditional too. Never
    # use parked.release(), whose old status-only fence can touch a newer claimant.
    from sqlalchemy import delete

    claims = capsule.get("claims") or {}
    resume = claims.get("resume")
    if isinstance(resume, dict) and resume.get("token"):
        session.exec(delete(ResumeClaim).where(  # type: ignore[call-overload]
            col(ResumeClaim.execution_id) == execution_id, col(ResumeClaim.token) == resume["token"]))
    parked = claims.get("parked")
    if isinstance(parked, dict):
        from temper_ai.runner.parked import CARRIED_ON, WAITING
        event = session.exec(select(Event).where(Event.id == str(parked.get("id")))
                             .with_for_update()).first()
        note = ((event.data or {}).get("parked") or {}) if event is not None else {}
        if (event is not None and event.status == CARRIED_ON and isinstance(note, dict)
                and note.get("carried_on_at") == parked.get("carried_on_at")):
            event.status = WAITING
            event.data = {**(event.data or {}), "parked": {k: v for k, v in note.items() if k != "carried_on_at"}}
            session.add(event)
