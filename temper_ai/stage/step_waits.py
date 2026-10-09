"""Waits inside a step: a step that needs the owner's answer asks for it by a stable id.

An approval step (``gate: true``) waits before its step runs. Some steps need an answer in
the middle of their own work -- a team's spend check-in, the recovery of a turn that
did not settle. They ask here::

    answer = ask_owner(context, "check-in-100", question="The team spent $100. Continue?",
                       options=("continue", "stop"))

The wait id is the step's own: it comes from the step's durable record, so a step that runs
again asks the same wait again and finds its answer instead of opening a new one.

* answered: the answer comes back at once, and the step goes on from its own record;
* still open, in a Pi workflow (``context.park_at_gates``): the run saves where it is under
  the wait's own id and lets its worker go, exactly as a Pi workflow's approval does since
  task #35 (:func:`park` is the one place both park). The owner's answer carries the run on
  through Resume's path (runner/parked.py): the finished steps are kept, this step runs
  again, asks again, and gets the answer;
* still open anywhere else: the step waits with its worker held, as any approval does
  outside a Pi workflow.

An answer belongs to the step's current go: once the step finishes, its answers are spent
(:func:`spend_answers`), so a loop's next lap asks afresh. A step that parks, fails, or whose
worker stops keeps them: the run carrying it on, a Resume, or the pick-up after a restart
runs it again and it reads them again. docs/gates.md "Waits inside a step".

The Pi step's own waits come through here too (temper_ai/pi_agent/host.py, C7): each is
written first as a row in the Pi ledger and asked under that row's id, through
temper_ai/pi_agent/owner_waits.py.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal, overload

from temper_ai.observability.event_types import EventType
from temper_ai.shared.clock import utcnow
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage.exceptions import CancellationError, RunParked
from temper_ai.stage.gate import (
    APPROVED,
    REPLACED,
    WAITING,
    GateSignal,
    earlier_waits,
    normalise_question,
    signal_key,
)

logger = logging.getLogger(__name__)

#: The event ``type`` of a wait asked from inside a step.
STEP_WAIT = "step_wait"
#: Between a step's path and its wait id in the wait's name: ``<path>~ask-<wait id>``.
ASK = "~ask-"
#: The checkpoint a step's wait saves when its run lets its worker go (a gate's is
#: ``gate_parked``); the replay that rebuilds a run's results skips both.
STEP_PARKED = "step_parked"
#: The checkpoint a step's wait saves when it holds its worker (a gate's is ``gate_waiting``).
STEP_WAITING = "step_waiting"

#: A wait id: letters, digits, dot, dash, underscore; no ``~``, so a wait's name
#: (``<path>~ask-<wait id>``) reads one way only.
WAIT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class OwnerAnswer:
    """What the owner said at a step's wait.

    ``response`` is the answer as the approval route stored it (``{response, answers,
    text}``, stage/gate.py ``normalise_response``), or None for a plain approval.
    ``decided_by`` is the name the answer gave (``by``, self-declared); ``caller`` and
    ``caller_source`` are who sent it as the server knows them (the API guard's named
    credential, :mod:`temper_ai.api.caller`), None when it wasn't recorded.
    ``request_id`` is the answer's own request id, else the request's (#45).
    """

    wait_id: str
    event_id: str
    round: int
    response: dict[str, Any] | None
    decided_by: str | None = None
    decided_at: str | None = None
    caller: str | None = None
    caller_source: str | None = None
    request_id: str | None = None

    @property
    def text(self) -> str:
        """The answer as one line of text ("" for a plain approval)."""
        r = self.response or {}
        return str(r.get("text") or r.get("response") or "")


def wait_name(path: str, wait_id: str) -> str:
    """The wait's name: what its event, GET .../gates and the approval route call it."""
    return f"{path}{ASK}{wait_id}"


def park(
    context: ExecutionContext,
    *,
    event_id: str,
    node: str,
    path: str,
    round: int,  # noqa: A002 - the wait's round, as RunParked calls it
    wait_id: str | None = None,
    log: logging.Logger | None = None,
) -> RunParked | None:
    """Save where a Pi run waits, under the wait's own id, so it can let its worker go.

    The one parking path: an approval step's wait (``wait_id`` None) and a step's own wait
    (its wait id) both come here. Returns the RunParked to raise, or None when the
    checkpoint could not be saved: then the wait holds its worker, as any wait outside a Pi
    workflow does, rather than letting go of a run nothing would know how to carry on.
    ``log`` is the logger to tell it on: the executor passes its own for approvals, so their
    lines read exactly as they did before this path was shared.
    """
    log = log or logger
    what = "Gate" if wait_id is None else "Step wait"
    service = context.checkpoint_service
    if service is None:
        log.warning("%s: '%s' would let its worker go, but the run saves no checkpoints; "
                    "waiting with the worker held", what, path)
        return None
    try:
        if wait_id is None:
            checkpoint_id = service.save_gate_parked(event_id, path, round)
        else:
            checkpoint_id = service.save_wait_parked(event_id, path, round, wait_id=wait_id)
    except Exception as exc:  # noqa: BLE001 - hold the worker instead
        log.warning("%s: could not save where '%s' waits (%s); waiting with the worker held",
                    what, path, exc)
        return None
    if wait_id is None:
        log.info("Gate: '%s' round %s waits on you; the run lets its worker go (execution %s, "
                 "event %s)", path, round, context.run_id, event_id)
    else:
        log.info("Step wait: '%s' waits on you at '%s', round %s; the run lets its worker go "
                 "(execution %s, event %s)", path, wait_id, round, context.run_id, event_id)
    return RunParked(event_id=event_id, node=node, path=path, round=round,
                     checkpoint_id=checkpoint_id, wait_id=wait_id)


def finish_usage_timer(context: ExecutionContext, wait_id: str, *, cancelled: bool = False) -> None:
    """Close the usage timer when its worker wakes or the team ends; never answer an owner
    question or permit a member claim."""
    from temper_ai.observability.recorder import get_event

    path = getattr(context, "step_path", None)
    if not getattr(context, "park_at_gates", False) or not path:
        return
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{context.run_id}:{path}:{wait_id}:timer"))
    if get_event(event_id) is not None:
        context.event_recorder.update_event(
            event_id, status="cancelled" if cancelled else "completed",
            data={"timer_finished_at": utcnow().isoformat()})


def park_until(context: ExecutionContext, wait_id: str, *, resumes_at: str) -> bool:
    """Free a Pi workflow's worker until a durable usage-limit check time. No owner question.
    The reaper uses the parked-attempt CAS; at wake the step rechecks fresh usage, not a
    member claim. Re-arming the same timer updates its time without opening another event.
    False outside Pi or if the checkpoint cannot be saved (the caller holds instead)."""
    from temper_ai.observability.recorder import get_event

    if not getattr(context, "park_at_gates", False):
        return False
    path = context.step_path
    if not path or not WAIT_ID.fullmatch(wait_id):
        raise ValueError("park_until needs the step's path and a valid stable wait id")
    cancel = context.cancel_event
    if cancel is not None and cancel.is_set():
        raise CancellationError("Workflow cancelled by user")
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{context.run_id}:{path}:{wait_id}:timer"))
    if get_event(event_id) is None:
        context.event_recorder.record(
            EventType.STAGE_STARTED,
            data={"name": wait_name(path, wait_id), "type": "step_timer", "depends_on": [],
                  "wait_id": wait_id, "wake_at": resumes_at, "reason": "usage_limit"},
            parent_id=context.parent_event_id, execution_id=context.run_id,
            status=WAITING, event_id=event_id)
    else:
        context.event_recorder.update_event(event_id, status=WAITING,
                                             data={"wake_at": resumes_at})
    parked = park(context, event_id=event_id, node=path.rsplit(".", 1)[-1], path=path,
                  round=1, wait_id=wait_id)
    if parked is not None:
        parked.wake_at = resumes_at
        raise parked
    return False


@overload
def ask_owner(context: ExecutionContext, wait_id: str, *, question: str, header: str = "",
              detail: str = "", options: tuple[str, ...] | list[str] = (),
              hold: Literal[True] = True, also: tuple[dict, ...] = ()) -> OwnerAnswer: ...


@overload
def ask_owner(context: ExecutionContext, wait_id: str, *, question: str, header: str = "",
              detail: str = "", options: tuple[str, ...] | list[str] = (),
              hold: bool, also: tuple[dict, ...] = ()) -> OwnerAnswer | None: ...


def ask_owner(
    context: ExecutionContext,
    wait_id: str,
    *,
    question: str,
    header: str = "",
    detail: str = "",
    options: tuple[str, ...] | list[str] = (),
    hold: bool = True,
    also: tuple[dict, ...] = (),
) -> OwnerAnswer | None:
    """The owner's answer at this step's wait ``wait_id``; asks for it when there is none yet.

    ``hold=False`` (a free-flowing team asking while its other members work): the question is
    put to the owner (its waiting event recorded once) and, with no answer yet, None comes
    back at once -- nothing parks and no worker is held; the caller asks again later and gets
    the answer from the history.

    ``also`` names other already-registered waits of this step. A free-flowing team parks
    on the whole set, so an answer to any member's question can carry the run on.

    ``context`` is the one the step was run with: the wait is filed under the step's own path,
    which the executor puts on it (``step_path``) for every kind of node. Raises RunParked when
    a Pi workflow lets its worker go here (let it go up: the run carries on once the owner
    answers), CancellationError when the run is stopped while the step holds its worker --
    its ReplacedByLaterAttempt when a later attempt of the run took the held wait over (this
    attempt stands down: let it go up too) -- and ValueError for a wait id that cannot name a
    wait or a context that names no step.
    """
    if not isinstance(wait_id, str) or not WAIT_ID.fullmatch(wait_id):
        raise ValueError(f"wait id {wait_id!r}: letters, digits, '.', '-', '_' only "
                         "(up to 128, starting with a letter or digit)")
    path = getattr(context, "step_path", None)
    if not path:
        raise ValueError("ask_owner needs the context the step was run with: this one names "
                         "no step (step_path)")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("ask_owner needs a question")
    cancel = getattr(context, "cancel_event", None)
    if cancel is not None and cancel.is_set():
        # A stopped run asks nothing more: an agent step retries what raised, and a retry
        # must not open a new wait after the cancel closed the last one.
        raise CancellationError("Workflow cancelled by user")
    name = wait_name(path, wait_id)
    recorder = context.event_recorder
    registry = context.gate_registry if context.gate_registry is not None else {}

    # Waits someone in this process is still waiting on (the same step running twice at
    # once) are theirs: neither taken over nor closed here.
    history = [ev for ev in _history(recorder, name)
               if signal_key(context.run_id, str(ev.get("id"))) not in registry]
    earlier = earlier_waits(history, path, name)
    new_id = str(uuid.uuid4())
    answer, adopt = earlier.answer, earlier.adopt
    for ev in earlier.retire:
        approved_meanwhile = _retire(recorder, ev, str((answer or adopt or {}).get("id") or new_id))
        if approved_meanwhile and answer is None:
            answer = approved_meanwhile
    if answer is not None:
        if adopt is not None:
            _retire(recorder, adopt, str(answer.get("id")))
        _note_asked(context, path)
        logger.info("Step wait: '%s' has its answer at '%s' (event %s); going on with it",
                    path, wait_id, answer.get("id"))
        return _answer_from(answer, wait_id)

    if adopt is not None:
        event_id = str(adopt["id"])
        round_ = int((adopt.get("data") or {}).get("gate_round") or earlier.round)
        logger.info("Step wait: '%s' is still waiting at '%s' for the answer it asked for "
                    "before (event %s); waiting on it again", path, wait_id, event_id)
    else:
        event_id, round_ = new_id, int(earlier.round)
        asked = normalise_question({"question": question, "header": header, "detail": detail,
                                    "options": list(options)}, 0)
        recorder.record(
            EventType.STAGE_STARTED,
            data={
                "name": name,
                "type": STEP_WAIT,
                "depends_on": [],
                "gate": True,
                "gate_status": WAITING,
                "gate_path": path,
                "gate_round": round_,
                "gate_context": {"upstream": [], "questions": [asked] if asked else []},
                STEP_WAIT: {"wait_id": wait_id, "path": path},
            },
            parent_id=context.parent_event_id,
            execution_id=context.run_id,
            status=WAITING,
            event_id=event_id,
        )

    if not hold:
        _note_asked(context, path)
        return None
    # A Pi workflow does not hold its worker while it waits (docs/gates.md).
    if getattr(context, "park_at_gates", False):
        park_extras: dict[str, Any] = {"also": list(also)} if also else {}
        parked = park(context, event_id=event_id, node=path.rsplit(".", 1)[-1], path=path,
                      round=round_, wait_id=wait_id, **park_extras)
        if parked is not None:
            raise parked
    return _hold(context, name, path, wait_id, event_id, round_, registry)


def spend_answers(context: ExecutionContext, path: str) -> None:
    """A step finished: the answers it was given are spent, and a later go asks afresh.

    Called by the executor when a step completes. Only a step that asked (in this process),
    a step the run's Resume found holding an unspent answer (:func:`note_unspent_answers`),
    or any step of a Pi workflow -- a step carried on in a new box may finish from its own
    record without asking again -- has anything to look up: elsewhere this reads nothing.
    After a step of this go failed holding an answer (:func:`forget_step`), the first step to
    finish looks the run's unspent answers up once: a loop may have run the failed step
    again, and it may have finished from its record without asking.
    Never raises: the step's result does not depend on it.
    """
    pi = getattr(context, "park_at_gates", False)
    asked = _ASKED.pop((context.run_id, path), None) is not None
    if not (asked or pi) and context.run_id in _LOOK_AGAIN:
        _LOOK_AGAIN.discard(context.run_id)
        note_unspent_answers(context)
        asked = _ASKED.pop((context.run_id, path), None) is not None
    if not (asked or pi):
        return
    recorder = context.event_recorder
    try:
        events = recorder.gate_events() if hasattr(recorder, "gate_events") else []
    except Exception as exc:  # noqa: BLE001 - a later go would only find an old answer
        logger.warning("Step wait: could not read the waits of '%s' to spend them: %s", path, exc)
        return
    now = utcnow().isoformat()
    for ev in events if isinstance(events, list) else []:
        data = ev.get("data") or {}
        if data.get("type") != STEP_WAIT or data.get("gate_path") != path:
            continue
        try:
            if ev.get("status") == APPROVED and not data.get("gate_used_at"):
                recorder.update_event(str(ev["id"]), status=APPROVED,
                                      data={"gate_status": APPROVED, "gate_used_at": now})
            elif ev.get("status") == WAITING:
                # Nothing waits on it any more: the step finished without its answer.
                logger.warning("Step wait: '%s' finished with its wait %s still open; closing it",
                               path, ev.get("id"))
                _retire(recorder, ev, "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Step wait: could not spend the answer %s of '%s': %s",
                           ev.get("id"), path, exc)


def note_unspent_answers(context: ExecutionContext) -> None:
    """A run is resumed: note the steps that hold an answer they have not spent yet.

    A step can take its answer, keep it in its own record, and then stop before it finished
    (the process died, or the step failed). Run again, it may finish from its record without
    asking, so nothing in this process knows it took an answer: noted here, its answer is
    spent when it finishes, and its next go asks afresh. One read of the run's waits per
    resume, none per step. Pi workflows always look when a step finishes, so they read
    nothing here. Never raises: a resume does not depend on it.
    """
    if getattr(context, "park_at_gates", False):
        return
    recorder = context.event_recorder
    try:
        events = recorder.gate_events() if hasattr(recorder, "gate_events") else []
    except Exception as exc:  # noqa: BLE001 - a later go would only find an old answer
        logger.warning("Step wait: could not read the waits of run %s on resume: %s",
                       context.run_id, exc)
        return
    for ev in events if isinstance(events, list) else []:
        data = ev.get("data") or {}
        if (data.get("type") == STEP_WAIT and data.get("gate_path")
                and ev.get("status") == APPROVED and not data.get("gate_used_at")):
            _ASKED[(context.run_id, str(data["gate_path"]))] = True


def forget_step(context: ExecutionContext, path: str) -> None:
    """The step failed: this go of it is over. Its answers stay unspent in the run's record
    for the go that carries it on (a Resume notes them again: :func:`note_unspent_answers`),
    so this process need not remember that it asked. A loop of this go may run it again,
    though: the next step to finish looks the run's unspent answers up once (``_LOOK_AGAIN``)."""
    if _ASKED.pop((context.run_id, path), None) is not None:
        _LOOK_AGAIN.add(context.run_id)


def forget_run(run_id: str) -> None:
    """This go of the run is over (finished, failed, stopped, or let its worker go): forget
    what its steps asked here. A go that carries it on asks again, or is noted on resume."""
    for key in [k for k in list(_ASKED) if k[0] == run_id]:
        _ASKED.pop(key, None)
    _LOOK_AGAIN.discard(run_id)


# --- inside ----------------------------------------------------------------------------

#: (run, step path) of steps that took an answer in this process since they last finished,
#: or that a Resume found holding an unspent answer. Emptied for a run when its go ends.
_ASKED: dict[tuple[str, str], bool] = {}
#: Runs whose go had a step fail holding an answer (:func:`forget_step`); emptied with
#: ``_ASKED`` when the go ends.
_LOOK_AGAIN: set[str] = set()


def _note_asked(context: ExecutionContext, path: str) -> None:
    _ASKED[(context.run_id, path)] = True


def _history(recorder: Any, name: str) -> list[dict[str, Any]]:
    """This run's earlier waits called ``name``, oldest first; none when it keeps no events."""
    try:
        found = recorder.gate_events(name)
    except Exception as exc:  # noqa: BLE001 - cannot look: ask afresh
        logger.warning("Step wait: could not read the earlier waits '%s': %s", name, exc)
        return []
    return found if isinstance(found, list) else []


def _retire(recorder: Any, ev: dict[str, Any], took_over_by: str) -> dict[str, Any] | None:
    """Close an open wait nobody waits on any more; the approval given meanwhile, if any."""
    won, after = recorder.decide(
        str(ev["id"]),
        expect=(WAITING,),
        status=REPLACED,
        data={"gate_status": REPLACED, "gate_replaced_at": utcnow().isoformat(),
              "gate_replaced_by": took_over_by},
    )
    if won:
        return None
    if after and after.get("status") == APPROVED and not (after.get("data") or {}).get("gate_used_at"):
        return after
    return None


def _answer_from(ev: dict[str, Any], wait_id: str) -> OwnerAnswer:
    data = ev.get("data") or {}
    response = data.get("gate_response") if isinstance(data.get("gate_response"), dict) else None
    return OwnerAnswer(wait_id=wait_id, event_id=str(ev["id"]),
                       round=int(data.get("gate_round") or 1), response=response,
                       decided_by=data.get("gate_decided_by"), decided_at=data.get("gate_decided_at"),
                       caller=data.get("gate_caller"), caller_source=data.get("gate_caller_source"),
                       request_id=_request_id(data))


def _request_id(data: dict) -> str | None:
    """The answer's request id: the one its sender gave, else the request's own (#45)."""
    return data.get("gate_request_id") or data.get("gate_caller_request_id") or None


def _hold(
    context: ExecutionContext,
    name: str,
    path: str,
    wait_id: str,
    event_id: str,
    round_: int,
    registry: dict,
) -> OwnerAnswer:
    """Wait with the worker held, as an approval outside a Pi workflow does."""
    # The gates' own wait loop and its poll setting (imported here: executor imports this).
    from temper_ai.stage import executor

    recorder = context.event_recorder
    signal = GateSignal(event_id, name, path, round_)
    key = signal_key(context.run_id, event_id)
    registry[key] = signal
    try:
        if context.checkpoint_service:
            # So a run whose server stops here can be resumed (as a gate's gate_waiting).
            context.checkpoint_service._save(event_type=STEP_WAITING, node_name=path, status="waiting")
        logger.info("Step wait: '%s' waits for an answer at '%s', round %s (execution %s, event %s)",
                    path, wait_id, round_, context.run_id, event_id)
        executor._wait_for_approval(signal, recorder, context, event_id, path)
    finally:
        registry.pop(key, None)
    response = signal.response
    data: dict[str, Any] = {}
    try:
        data = recorder.event_data(event_id) or {}
    except Exception as exc:  # noqa: BLE001 - the approval got through; the rest is best-effort
        logger.warning("Step wait: could not read the answer at '%s': %s", name, exc)
    if response is None and isinstance(data.get("gate_response"), dict):
        response = data["gate_response"]
    _note_asked(context, path)
    return OwnerAnswer(wait_id=wait_id, event_id=event_id, round=round_, response=response,
                       decided_by=data.get("gate_decided_by"), decided_at=data.get("gate_decided_at"),
                       caller=data.get("gate_caller"), caller_source=data.get("gate_caller_source"),
                       request_id=_request_id(data))
