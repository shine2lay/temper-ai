"""Closed metadata envelopes for authenticated process-only transport.

A's records remain canonical. Context/draft bytes have private accessors only;
these models never confer authority or rebuild server-owned custody.
"""
from typing import Literal

from .contracts import AttemptOutcome, ReleaseDisposition
from .wire import ClosedModel, GeneratedID, Identifier, NonnegativeInt


class AcquireLease(ClosedModel):
    node_path: Identifier
    use: Literal["draft"]


class LeaseHandle(ClosedModel):
    lease_id: GeneratedID


class ReserveSend(LeaseHandle):
    invocation_id: GeneratedID
    attempt_id: GeneratedID
    selected_slot: NonnegativeInt


class ReservationHandle(ClosedModel):
    invocation_id: GeneratedID
    attempt_id: GeneratedID


class FinishAttempt(ReservationHandle):
    outcome: AttemptOutcome


class PublishDraft(LeaseHandle):
    invocation_id: GeneratedID


class ReleaseLease(LeaseHandle):
    disposition: ReleaseDisposition
