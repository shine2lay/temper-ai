"""Durable one-invocation send fence; only recorded pre-stream refusal retries."""
from sqlmodel import Session, select

from .contracts import AttemptOutcome, SendReservation
from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure
from .models import PrivateAttemptRow, PrivateContextRow, PrivateInvocationRow


def reserve_in(session: Session, row: PrivateContextRow, reservation: SendReservation) -> None:
    invocation = session.get(PrivateInvocationRow, reservation.execution_id)
    if session.get(PrivateAttemptRow, reservation.attempt_id) is not None:
        # A repeated reserve response must never grant another possible send.
        raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
    if invocation is not None:
        if invocation.invocation_id != reservation.invocation_id or invocation.state != "refused":
            raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
        previous = session.get(PrivateAttemptRow, invocation.attempt_id)
        if previous is None or previous.outcome_metadata is None:
            raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
        outcome = AttemptOutcome.model_validate_json(previous.outcome_metadata)
        if outcome.phase != "http_refused" or outcome.http_status not in {401, 403, 429, 529}:
            raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
        for attempt in session.exec(select(PrivateAttemptRow).where(PrivateAttemptRow.invocation_id == invocation.invocation_id)).all():
            if attempt.selected_slot == reservation.selected_slot and attempt.outcome_metadata is not None:
                refused = AttemptOutcome.model_validate_json(attempt.outcome_metadata)
                if refused.phase == "http_refused" and refused.http_status in {401, 403, 429}:
                    raise PrivateDraftFailure(Code.SCOPE_DENIED)
        invocation.attempt_id = reservation.attempt_id
        invocation.state = "reserved"
    else:
        invocation = PrivateInvocationRow(execution_id=reservation.execution_id, invocation_id=reservation.invocation_id, context_ref=row.context_ref, attempt_id=reservation.attempt_id)
    session.add(invocation)
    session.add(PrivateAttemptRow(attempt_id=reservation.attempt_id, invocation_id=reservation.invocation_id, execution_id=reservation.execution_id, lease_id=reservation.lease_id, runner_generation=reservation.runner_generation, selected_slot=reservation.selected_slot, deadline_at=reservation.deadline_at))
    row.state = "running"
    session.add(row)


def finish_in(session: Session, reservation: SendReservation, outcome: AttemptOutcome) -> None:
    invocation = session.get(PrivateInvocationRow, reservation.execution_id)
    attempt = session.get(PrivateAttemptRow, reservation.attempt_id)
    if invocation is None or attempt is None or invocation.invocation_id != reservation.invocation_id or invocation.attempt_id != reservation.attempt_id or (attempt.lease_id, attempt.runner_generation, attempt.selected_slot) != (reservation.lease_id, reservation.runner_generation, reservation.selected_slot):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
    encoded = outcome.model_dump_json(exclude_unset=True)
    if attempt.outcome_metadata is not None:
        if attempt.outcome_metadata != encoded:
            raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
        return
    if invocation.state != "reserved" or outcome.phase == "before_reserve":
        raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
    attempt.outcome_metadata = encoded
    invocation.state = {"reserved": "ambiguous", "streaming": "ambiguous", "http_refused": "refused", "complete": "complete"}[outcome.phase]
    session.add(attempt)
    session.add(invocation)


def require_complete(session: Session, row: PrivateContextRow, invocation_id: str) -> None:
    invocation = session.get(PrivateInvocationRow, row.execution_id)
    if invocation is None or invocation.invocation_id != invocation_id or invocation.state != "complete":
        raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
    attempt = session.get(PrivateAttemptRow, invocation.attempt_id)
    if attempt is None or attempt.outcome_metadata is None:
        raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
    outcome = AttemptOutcome.model_validate_json(attempt.outcome_metadata)
    if outcome.phase != "complete" or outcome.failure is not None:
        raise PrivateDraftFailure(Code.OUTPUT_INVALID)
