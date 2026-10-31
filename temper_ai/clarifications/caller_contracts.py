"""Shared ports and snapshots for explicit clarification composition.

No coordinator, store, policy or provider is constructed here. These contracts
are not authority grants. The store port reuses M3's results; its current-only
acknowledgement is an explicit extension, not supplied by the original store.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from temper_ai.clarifications.contracts import (
    ActionReceipt,
    AppendResult,
    CallerInput,
    Presentation,
    PresentationBinding,
    StreamKey,
)
from temper_ai.clarifications.store import RecordResult, StoredStream, Supplement
from temper_ai.integrations.telegram.clarifications import SendResult

__all__ = [
    "CheckedClarification",
    "ClarificationAuthority",
    "CoordinatorStore",
    "PreparedClarification",
    "PresentationRequest",
    "QuestionTransport",
    "RecoveredClarification",
]


class CoordinatorStore(Protocol):
    """M3's synchronous public operations plus a current-revision acknowledgement.

    Implementations must check durable state, not trust a supplied snapshot. No
    implementation or second persistence layer is provided by this protocol.
    """

    def merge_candidate(self, caller: CallerInput) -> RecordResult: ...
    def save_presentation(self, presentation: Presentation) -> bool: ...
    def record_copy(self, binding: PresentationBinding) -> bool: ...
    def append_receipt(self, receipt: ActionReceipt) -> AppendResult: ...
    def load(self, stream: StreamKey) -> StoredStream | None: ...
    def supplement(self, stream: StreamKey, *, revision: int, original_brief: str) -> Supplement: ...
    def mark_consumed(self, stream: StreamKey, *, revision: int, original_brief: str) -> bool: ...

    def mark_current_consumed(
        self, stream: StreamKey, *, revision: int, record_sha256: str,
        consumption_id: str, original_brief: str,
    ) -> bool:
        """Exact kept replay first; otherwise require current identities in one commit.

        True means a new acknowledgement; False means an exact kept one. New
        stale acknowledgements refuse with REVISION_CONFLICT. No external effect.
        """
        ...


class QuestionTransport(Protocol):
    """The existing synchronous M2 send operation, with explicit retry intent."""

    def present(
        self, presentation: Presentation, unknown: Mapping[str, object], text: str, *, resend: bool = False,
    ) -> SendResult: ...


class ClarificationAuthority(Protocol):
    """Injected enforcement of an already-authorized scope; denial raises.

    References are labels, not credentials. The embedding application supplies
    enforcement; a missing port must never become an allow-all implementation.
    """

    def require(
        self, *, operation: Literal["read", "write", "send", "acknowledge"], stream: StreamKey,
        source_authority_ref: str, responder_policy_ref: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PresentationRequest:
    """Explicit presentation/generation plus exact display text; no inferred metadata."""

    presentation: Presentation
    text: str


@dataclass(frozen=True, slots=True)
class PreparedClarification:
    """Committed M3 record and its independent M1 display, possibly stale on return."""

    record: RecordResult
    display: dict[str, Any]
    meaning_status: Literal["NOT_EVALUATED"] = field(default="NOT_EVALUATED", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "display", deepcopy(self.display))


@dataclass(frozen=True, slots=True)
class RecoveredClarification:
    """Checked durable history, display and supplement; recovery sends/acks nothing."""

    stored: StoredStream
    display: dict[str, Any]
    supplement: Supplement
    meaning_status: Literal["NOT_EVALUATED"] = field(default="NOT_EVALUATED", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "display", deepcopy(self.display))
        object.__setattr__(self, "supplement", deepcopy(self.supplement))


@dataclass(frozen=True, slots=True)
class CheckedClarification:
    """Source-reference check snapshot, not acceptance or execution permission.

    The coordinator must revalidate before a new acknowledgement. A caller can
    edit its own returned dictionaries; they never alias the supplied ones.
    """

    stream: StreamKey
    revision: int
    record_sha256: str
    original_sha256: str
    candidate_ref: str
    candidate_json: str
    candidate_sha256: str
    original_text: str
    supplement: str
    source_mapping: dict[str, Any]
    consumption_id: str
    report: dict[str, Any]
    meaning_status: Literal["NOT_EVALUATED"] = field(default="NOT_EVALUATED", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_mapping", deepcopy(self.source_mapping))
        object.__setattr__(self, "report", deepcopy(self.report))
