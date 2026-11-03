"""Shared conformance kit for ``HostProvenance`` adapters.

One job: drive a ``HostProvenance`` adapter through the port's obligations and
report each case's outcome against the expected one. The cases hold good and
bad receipts, each with its expected answer, for obligations a-i of
``HostProvenance.verify_linked_receipt``, the exact-predecessor table (C2),
every boundary outside ``LINKED_RECEIPT_BOUNDARIES`` (C3) and the
``bind_publication`` obligations. ``run_conformance`` takes an adapter
factory, so the test double's tests and a live adapter's tests run the same
cases.

A case plants host facts only through the adapter's ``HostFeed`` and reads only
the port's answers. Where a rule may be checked when a receipt links or when
it is verified, the case's outcome is the first refusal of the two calls, so
either placement conforms. This is neither a test double nor authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, fields, replace
from typing import Any, Final, Literal, Protocol, cast, get_args

from p3_host_contracts import ReceiptProvenance as _ReceiptProvenanceRecord
from p3_host_contracts import RowKey as _RowKeyRecord

from .contract import (
    AcceptedData,
    Boundary,
    HostProvenance,
    NativeSelection,
    NativeSession,
    NativeWitness,
    OccurrenceHandle,
    OperationKey,
    RawPublication,
    RawRef,
    ReceiptProvenance,
    Refusal,
    RefusalCode,
    Result,
    RowKey,
    VerifiedReceiptBinding,
)
from .host_ports import LINKED_RECEIPT_BOUNDARIES
from .linked_receipt_rules import (
    exact_receipt_equal,
    is_successful_row_receipt,
    linked_predecessor_mismatch,
)
from .registry import DecisionEvidenceRecord

HOST_ROW_ORDER: Final[tuple[str, ...]] = ("R-1", "R-1i", "D-1", "D-5")
"""Host rows in their window's link order (HOST_ROWS of first_app_p3_rows.py)."""

API_ROW_ORDER: Final[tuple[str, ...]] = ("API-D-1", "API-D-5")
"""API host rows in their window's link order (QA's api_check order)."""

ACCEPTED: Final = "ACCEPTED"
"""The outcome of a case whose port answers were all accepted (and checked)."""

_VERIFIED_RECEIPT_BINDING_CLASS = getattr(
    VerifiedReceiptBinding, "__origin__", VerifiedReceiptBinding
)
_OUTSIDE_LINKED_BOUNDARIES: Final[tuple[str, ...]] = tuple(
    boundary
    for boundary in get_args(Boundary)
    if boundary not in LINKED_RECEIPT_BOUNDARIES
)


class HostFeed(Protocol):
    """Host facts a case plants through the adapter's own feed (a test shim over it)."""

    def register_evidence(
        self, selection_revision: str, evidence: DecisionEvidenceRecord
    ) -> None: ...

    def register_occurrence(
        self,
        key: OperationKey,
        occurrence: OccurrenceHandle,
        witness: NativeWitness | None = None,
    ) -> None: ...

    def anchor_window(self, selection_revision: str, window_id: str) -> None: ...

    def taint_window(self, selection_revision: str, window_id: str) -> None: ...

    def publish_receipt(
        self,
        provenance: ReceiptProvenance,
        *,
        request_raw: bytes | None,
        receipt_raw: bytes | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AdapterUnderTest:
    """The port under test and the feed that plants its host facts."""

    port: HostProvenance
    feed: HostFeed


AdapterFactory = Callable[[], AdapterUnderTest]


def _witness_reference(witness: object) -> str:
    reference = getattr(witness, "witness_reference", "")
    return reference if isinstance(reference, str) else ""


@dataclass(frozen=True, slots=True)
class ConformanceTemplates:
    """What the kit cannot invent for an adapter: one valid receipt and its context.

    ``receipt`` is a complete, successful receipt of a completed RowKey
    occurrence that starts its window (no predecessor); every case derives
    its rows from it. ``evidence`` is what the adapter holds for the
    receipt's selection revision. ``other_witness`` is a witness the receipt
    does not carry; ``foreign_selection`` is another selection revision.
    """

    session: NativeSession
    receipt: ReceiptProvenance
    evidence: DecisionEvidenceRecord
    other_witness: NativeWitness
    foreign_selection: NativeSelection

    def __post_init__(self) -> None:
        receipt = self.receipt
        if type(receipt) is not _ReceiptProvenanceRecord or not is_successful_row_receipt(
            receipt
        ):
            raise ValueError(
                "templates.receipt must be a complete, successful ReceiptProvenance "
                "of a completed RowKey occurrence"
            )
        if receipt.predecessor is not None:
            raise ValueError("templates.receipt must start its window (predecessor None)")
        if receipt.raw_publication.cleanup_state not in ("not-required", "complete"):
            raise ValueError("templates.receipt must have finished its cleanup")
        if _witness_reference(receipt.occurrence_witness) != _witness_reference(
            receipt.raw_publication.occurrence.witness
        ):
            raise ValueError(
                "templates.receipt occurrence_witness must be its occurrence's witness"
            )
        other = _witness_reference(self.other_witness)
        if not other or other in (
            _witness_reference(receipt.occurrence_witness),
            _witness_reference(receipt.publication_witness),
        ):
            raise ValueError(
                "templates.other_witness must be a witness the receipt does not carry"
            )
        if (
            self.foreign_selection.selection_revision
            == receipt.operation_key.selection.selection_revision
        ):
            raise ValueError(
                "templates.foreign_selection must be another selection revision"
            )


@dataclass(frozen=True, slots=True)
class DerivedReceipt:
    """A receipt derived from the template for one row, with its original bytes."""

    provenance: ReceiptProvenance
    request_raw: bytes
    receipt_raw: bytes

    @property
    def key(self) -> RowKey:
        return cast(RowKey, self.provenance.operation_key)

    @property
    def publication(self) -> RawPublication:
        return self.provenance.raw_publication

    @property
    def occurrence(self) -> OccurrenceHandle:
        return self.provenance.raw_publication.occurrence


def _raw_ref_for(base: RawRef, name: str, payload: bytes) -> RawRef:
    return replace(
        base,
        relative_path=f"{base.relative_path}/{name}",
        byte_length=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def derive_row_receipt(
    template: ReceiptProvenance,
    *,
    row: str,
    sequence: int,
    predecessor: ReceiptProvenance | None,
    window_id: str | None = None,
    outcome: Literal["success", "app-failure"] = "success",
) -> DerivedReceipt:
    """The template's receipt moved to ``row`` at ``sequence`` in ``window_id``.

    New request and receipt bytes with their references (digest and length),
    key, occurrence and publication; every other field is the template's.
    ``outcome="app-failure"`` gives the receipt of a failed occurrence.
    """
    if type(template.operation_key) is not _RowKeyRecord:
        raise ValueError("derive_row_receipt needs the receipt of a RowKey occurrence")
    base_key = cast(RowKey, template.operation_key)
    window = base_key.window_id if window_id is None else window_id
    stem = f"{window}/{row}/{sequence}"
    request_raw = f'{{"window":"{window}","row":"{row}","sequence":{sequence}}}'.encode()
    receipt_raw = (
        f'{{"window":"{window}","row":"{row}","sequence":{sequence},'
        f'"outcome":"{outcome}"}}'
    ).encode()
    request_ref = _raw_ref_for(base_key.request_raw_ref, f"{stem}/request", request_raw)
    receipt_ref = _raw_ref_for(
        template.raw_publication.receipt_raw_ref, f"{stem}/receipt", receipt_raw
    )
    key = replace(
        base_key,
        window_id=window,
        row=row,
        request_id=f"{base_key.request_id}/{stem}",
        sequence=sequence,
        request_raw_ref=request_ref,
    )
    occurrence = replace(
        template.raw_publication.occurrence,
        key=key,
        state="completed" if outcome == "success" else "failed",
    )
    publication = replace(
        template.raw_publication,
        occurrence=occurrence,
        request_raw_ref=request_ref,
        receipt_raw_ref=receipt_ref,
        outcome=outcome,
    )
    provenance = replace(
        template,
        operation_key=key,
        raw_publication=publication,
        predecessor=predecessor,
        state="complete",
    )
    return DerivedReceipt(
        provenance=provenance, request_raw=request_raw, receipt_raw=receipt_raw
    )


class _LookalikeRowKey(_RowKeyRecord):  # type: ignore[type-arg]
    """Same fields as a RowKey, another class: exactness must refuse it."""

    __slots__ = ()


class _LookalikeReceipt(_ReceiptProvenanceRecord):  # type: ignore[type-arg]
    """Same fields as a ReceiptProvenance, another class: exactness must refuse it."""

    __slots__ = ()


def _copy_as(record_class: type[Any], record: Any) -> Any:
    return record_class(**{field.name: getattr(record, field.name) for field in fields(record)})


def _other_digest(digest: str) -> str:
    return hashlib.sha256(digest.encode()).hexdigest()


def _tampered(receipt: ReceiptProvenance) -> ReceiptProvenance:
    """The receipt with another receipt digest."""
    publication = receipt.raw_publication
    tampered_ref = replace(
        publication.receipt_raw_ref,
        sha256=_other_digest(publication.receipt_raw_ref.sha256),
    )
    return replace(receipt, raw_publication=replace(publication, receipt_raw_ref=tampered_ref))


def _forged_success(receipt: ReceiptProvenance) -> ReceiptProvenance:
    """A failed occurrence's receipt rewritten to claim success."""
    publication = receipt.raw_publication
    occurrence = replace(publication.occurrence, state="completed")
    return replace(
        receipt,
        raw_publication=replace(publication, occurrence=occurrence, outcome="success"),
    )


def _with_publication(receipt: ReceiptProvenance, **changes: Any) -> ReceiptProvenance:
    return replace(receipt, raw_publication=replace(receipt.raw_publication, **changes))


def _with_occurrence(receipt: ReceiptProvenance, **changes: Any) -> ReceiptProvenance:
    return _with_publication(
        receipt, occurrence=replace(receipt.raw_publication.occurrence, **changes)
    )


def _outcome_of(result: object) -> str:
    if isinstance(result, Refusal):
        return result.code.name
    if isinstance(result, AcceptedData):
        return ACCEPTED
    return f"NOT_A_RESULT:{type(result).__name__}"


def _first_not_accepted(outcomes: Iterable[str]) -> str:
    for outcome in outcomes:
        if outcome != ACCEPTED:
            return outcome
    return ACCEPTED


def _binding_mismatch(
    result: AcceptedData[Any], linked: ReceiptProvenance, evidence: object
) -> str | None:
    """Obligation i: the field of the returned binding that is not the link's, if any."""
    binding = result.data
    if type(binding) is not _VERIFIED_RECEIPT_BINDING_CLASS:
        return "type"
    checks = (
        ("disposition", binding.disposition == "verified"),
        ("selection", binding.selection == linked.operation_key.selection),
        ("operation_key", binding.operation_key == linked.operation_key),
        ("provenance", exact_receipt_equal(binding.provenance, linked)),
        ("publication", binding.publication == linked.raw_publication),
        ("occurrence", binding.occurrence == linked.raw_publication.occurrence),
        (
            "predecessor",
            linked_predecessor_mismatch(linked.predecessor, binding.predecessor) is None,
        ),
        ("receiving", bool(_witness_reference(binding.receiving))),
        ("evidence", result.evidence == evidence),
    )
    for name, matches in checks:
        if not matches:
            return name
    return None


class _SetupRefused(Exception):
    """A case's setup step was refused: the adapter fails that case."""

    def __init__(self, step: str, outcome: str) -> None:
        super().__init__(f"{step}: {outcome}")
        self.step = step
        self.outcome = outcome


class CaseWorld:
    """One case's adapter and templates, and the receipts the case derives."""

    def __init__(self, adapter: AdapterUnderTest, templates: ConformanceTemplates) -> None:
        self._port = adapter.port
        self._feed = adapter.feed
        self._templates = templates
        template_key = cast(RowKey, templates.receipt.operation_key)
        self.selection_revision = template_key.selection.selection_revision
        self.window_id = template_key.window_id
        self.other_window_id = f"{template_key.window_id}-other"

    @property
    def other_witness(self) -> NativeWitness:
        return self._templates.other_witness

    @property
    def foreign_selection(self) -> NativeSelection:
        return self._templates.foreign_selection

    # -- host facts ----------------------------------------------------------

    def ready(self, *, evidence: bool = True, anchor: bool = True) -> None:
        if evidence:
            self._feed.register_evidence(self.selection_revision, self._templates.evidence)
        if anchor:
            self.anchor()

    def anchor(self, window_id: str | None = None) -> None:
        self._feed.anchor_window(self.selection_revision, window_id or self.window_id)

    def taint(self, window_id: str | None = None) -> None:
        self._feed.taint_window(self.selection_revision, window_id or self.window_id)

    def observe(self, receipt: DerivedReceipt) -> None:
        self._feed.register_occurrence(
            receipt.key, receipt.occurrence, receipt.occurrence.witness
        )

    def publish(self, receipt: DerivedReceipt) -> None:
        self.publish_as(
            receipt.provenance,
            request_raw=receipt.request_raw,
            receipt_raw=receipt.receipt_raw,
        )

    def publish_as(
        self,
        provenance: ReceiptProvenance,
        *,
        request_raw: bytes | None,
        receipt_raw: bytes | None,
    ) -> None:
        self._feed.publish_receipt(
            provenance, request_raw=request_raw, receipt_raw=receipt_raw
        )

    # -- receipts ------------------------------------------------------------

    def receipt(
        self,
        row: str,
        sequence: int,
        *,
        after: DerivedReceipt | None = None,
        window_id: str | None = None,
        outcome: Literal["success", "app-failure"] = "success",
    ) -> DerivedReceipt:
        return derive_row_receipt(
            self._templates.receipt,
            row=row,
            sequence=sequence,
            predecessor=None if after is None else after.provenance,
            window_id=window_id,
            outcome=outcome,
        )

    def link(self, receipt: DerivedReceipt) -> DerivedReceipt:
        """Publish and link ``receipt``; a refusal fails the case's setup."""
        self.publish(receipt)
        outcome = _outcome_of(self.bind(receipt))
        if outcome != ACCEPTED:
            raise _SetupRefused(f"link {receipt.key.row}", outcome)
        return receipt

    def link_rows(
        self, rows: Sequence[str], *, window_id: str | None = None
    ) -> list[DerivedReceipt]:
        """Link ``rows`` in order from an empty window, each after the one before."""
        linked: list[DerivedReceipt] = []
        for sequence, row in enumerate(rows, start=1):
            after = linked[-1] if linked else None
            linked.append(
                self.link(self.receipt(row, sequence, after=after, window_id=window_id))
            )
        return linked

    # -- port calls ----------------------------------------------------------

    def bind(
        self,
        receipt: DerivedReceipt,
        *,
        occurrence: OccurrenceHandle | None = None,
        publication: RawPublication | None = None,
        witness: NativeWitness | None = None,
    ) -> Result[ReceiptProvenance]:
        return self._port.bind_publication(
            self._templates.session,
            receipt.occurrence if occurrence is None else occurrence,
            receipt.publication if publication is None else publication,
            receipt.provenance.publication_witness if witness is None else witness,
        )

    def bind_published(self, provenance: ReceiptProvenance) -> Result[ReceiptProvenance]:
        return self._port.bind_publication(
            self._templates.session,
            provenance.raw_publication.occurrence,
            provenance.raw_publication,
            provenance.publication_witness,
        )

    def verify_outcome(
        self,
        receipt: DerivedReceipt,
        *,
        key: OperationKey | None = None,
        provenance: ReceiptProvenance | None = None,
        boundary: Boundary = "C_BEFORE_COUNT",
    ) -> str:
        return _outcome_of(
            self._port.verify_linked_receipt(
                receipt.key if key is None else key,
                receipt.provenance if provenance is None else provenance,
                boundary,
            )
        )

    def verify_linked(
        self, receipt: DerivedReceipt, boundary: Boundary = "C_BEFORE_COUNT"
    ) -> str:
        """Verify a linked receipt as its caller would, and check the binding."""
        result = self._port.verify_linked_receipt(
            receipt.key, receipt.provenance, boundary
        )
        if not isinstance(result, AcceptedData):
            return _outcome_of(result)
        mismatch = _binding_mismatch(result, receipt.provenance, self._templates.evidence)
        return ACCEPTED if mismatch is None else f"BINDING_MISMATCH:{mismatch}"

    def bind_then_verify(self, receipt: DerivedReceipt) -> str:
        """The first refusal of linking and then verifying ``receipt``."""
        outcome = _outcome_of(self.bind(receipt))
        if outcome != ACCEPTED:
            return outcome
        return self.verify_outcome(receipt)


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    """One good or bad case: the obligation it checks, its expected answer, its steps."""

    name: str
    obligation: str
    expected: RefusalCode | None
    run: Callable[[CaseWorld], str]

    @property
    def expected_outcome(self) -> str:
        return ACCEPTED if self.expected is None else self.expected.name


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """A case's expected and actual outcome on one adapter."""

    name: str
    obligation: str
    expected: str
    actual: str

    @property
    def passed(self) -> bool:
        return self.actual == self.expected


# -- good cases ---------------------------------------------------------------


def _host_rows_linked_in_order(world: CaseWorld) -> str:
    world.ready()
    return _first_not_accepted(
        world.verify_linked(receipt) for receipt in world.link_rows(HOST_ROW_ORDER)
    )


def _api_rows_linked_in_order(world: CaseWorld) -> str:
    world.ready()
    return _first_not_accepted(
        world.verify_linked(receipt) for receipt in world.link_rows(API_ROW_ORDER)
    )


def _linked_boundaries_accepted(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    return _first_not_accepted(
        world.verify_linked(first, cast(Boundary, boundary))
        for boundary in sorted(LINKED_RECEIPT_BOUNDARIES)
    )


def _relink_answers_its_link(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    again = world.bind(first)
    if not isinstance(again, AcceptedData):
        return _outcome_of(again)
    return ACCEPTED if exact_receipt_equal(again.data, first.provenance) else "OTHER_ANSWER"


# -- a, C3: types and boundary ------------------------------------------------


def _boundaries_outside_linked_set(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    if not _OUTSIDE_LINKED_BOUNDARIES:
        return "NO_BOUNDARY_OUTSIDE_THE_SET"
    for boundary in _OUTSIDE_LINKED_BOUNDARIES:
        outcome = world.verify_outcome(first, boundary=cast(Boundary, boundary))
        if outcome != RefusalCode.SCOPE_MISMATCH.name:
            return f"{outcome}@{boundary}"
    return RefusalCode.SCOPE_MISMATCH.name


def _key_of_another_class(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    return world.verify_outcome(first, key=_copy_as(_LookalikeRowKey, first.key))


def _receipt_of_another_class(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    return world.verify_outcome(
        first, provenance=_copy_as(_LookalikeReceipt, first.provenance)
    )


def _receipt_for_another_key(world: CaseWorld) -> str:
    world.ready()
    first, second = world.link_rows(HOST_ROW_ORDER[:2])
    return world.verify_outcome(second, provenance=first.provenance)


# -- b, c, d: window and link -------------------------------------------------


def _window_not_anchored(world: CaseWorld) -> str:
    """Bound before its window's genesis: still unverified once the window is anchored."""
    world.ready(anchor=False)
    first = world.receipt("R-1", 1)
    world.publish(first)
    bound = _outcome_of(world.bind(first))
    world.anchor()
    return _first_not_accepted((bound, world.verify_outcome(first)))


def _key_in_unanchored_window(world: CaseWorld) -> str:
    world.ready()
    world.link_rows(HOST_ROW_ORDER[:1])
    return world.verify_outcome(world.receipt("R-1", 1, window_id=world.other_window_id))


def _window_tainted_after_link(world: CaseWorld) -> str:
    world.ready()
    linked = world.link_rows(HOST_ROW_ORDER)
    world.taint()
    return world.verify_outcome(linked[-1])


def _window_tainted_before_link(world: CaseWorld) -> str:
    """Linking into a tainted window is refused (the join's verify_publication)."""
    world.ready()
    world.taint()
    first = world.receipt("R-1", 1)
    world.publish(first)
    return _outcome_of(world.bind(first))


def _published_never_linked(world: CaseWorld) -> str:
    world.ready()
    first = world.receipt("R-1", 1)
    world.publish(first)
    return world.verify_outcome(first)


def _observed_never_linked(world: CaseWorld) -> str:
    world.ready()
    first = world.receipt("R-1", 1)
    world.observe(first)
    return world.verify_outcome(first)


# -- e, C2: the caller's receipt and predecessor against the link -------------


def _caller_omits_linked_predecessor(world: CaseWorld) -> str:
    world.ready()
    _, second = world.link_rows(HOST_ROW_ORDER[:2])
    return world.verify_outcome(
        second, provenance=replace(second.provenance, predecessor=None)
    )


def _caller_names_predecessor_none_linked(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    stranger = world.receipt("R-1i", 2)
    return world.verify_outcome(
        first, provenance=replace(first.provenance, predecessor=stranger.provenance)
    )


def _caller_predecessor_tampered(world: CaseWorld) -> str:
    world.ready()
    first, second = world.link_rows(HOST_ROW_ORDER[:2])
    return world.verify_outcome(
        second,
        provenance=replace(second.provenance, predecessor=_tampered(first.provenance)),
    )


def _caller_predecessor_of_another_class(world: CaseWorld) -> str:
    world.ready()
    first, second = world.link_rows(HOST_ROW_ORDER[:2])
    return world.verify_outcome(
        second,
        provenance=replace(
            second.provenance,
            predecessor=_copy_as(_LookalikeReceipt, first.provenance),
        ),
    )


def _caller_predecessor_chain_of_another_class(world: CaseWorld) -> str:
    world.ready()
    first, second, third = world.link_rows(HOST_ROW_ORDER[:3])
    lookalike_chain = replace(
        second.provenance, predecessor=_copy_as(_LookalikeReceipt, first.provenance)
    )
    return world.verify_outcome(
        third, provenance=replace(third.provenance, predecessor=lookalike_chain)
    )


def _caller_predecessor_forged_success(world: CaseWorld) -> str:
    world.ready()
    failed = world.link(world.receipt("R-1", 1, outcome="app-failure"))
    second = world.link(world.receipt("R-1i", 2, after=failed))
    return world.verify_outcome(
        second,
        provenance=replace(
            second.provenance, predecessor=_forged_success(failed.provenance)
        ),
    )


def _caller_receipt_tampered(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    return world.verify_outcome(first, provenance=_tampered(first.provenance))


def _caller_receipt_forged_success(world: CaseWorld) -> str:
    world.ready()
    failed = world.link(world.receipt("R-1", 1, outcome="app-failure"))
    return world.verify_outcome(failed, provenance=_forged_success(failed.provenance))


# -- f: link order (window head) ----------------------------------------------


def _link_without_naming_head(world: CaseWorld) -> str:
    world.ready()
    world.link_rows(HOST_ROW_ORDER[:1])
    orphan = world.receipt("R-1i", 2)
    world.publish(orphan)
    return world.bind_then_verify(orphan)


def _link_after_non_head(world: CaseWorld) -> str:
    world.ready()
    first, _ = world.link_rows(HOST_ROW_ORDER[:2])
    skipping = world.receipt("D-1", 3, after=first)
    world.publish(skipping)
    return world.bind_then_verify(skipping)


def _link_after_planted_predecessor(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    planted = world.receipt("R-1i", 2, after=first)
    world.publish(planted)
    world.observe(planted)
    after_planted = world.receipt("D-1", 3, after=planted)
    world.publish(after_planted)
    return world.bind_then_verify(after_planted)


def _link_after_other_window_receipt(world: CaseWorld) -> str:
    world.ready()
    world.anchor(world.other_window_id)
    (elsewhere,) = world.link_rows(HOST_ROW_ORDER[:1], window_id=world.other_window_id)
    world.link_rows(HOST_ROW_ORDER[:1])
    crossing = world.receipt("R-1i", 2, after=elsewhere)
    world.publish(crossing)
    return world.bind_then_verify(crossing)


def _link_after_tainted_window_receipt(world: CaseWorld) -> str:
    world.ready()
    world.anchor(world.other_window_id)
    (tainted,) = world.link_rows(HOST_ROW_ORDER[:1], window_id=world.other_window_id)
    world.taint(world.other_window_id)
    crossing = world.receipt("R-1i", 2, after=tainted)
    world.publish(crossing)
    return world.bind_then_verify(crossing)


# -- g: continuation rows (REQUIRED_PREDECESSOR_ROW) --------------------------


def _continuation_without_predecessor(row: str) -> Callable[[CaseWorld], str]:
    def run(world: CaseWorld) -> str:
        world.ready()
        continuation = world.receipt(row, 1)
        world.publish(continuation)
        return world.bind_then_verify(continuation)

    return run


def _continuation_after_other_row(world: CaseWorld) -> str:
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    continuation = world.receipt("D-5", 2, after=first)
    world.publish(continuation)
    return world.bind_then_verify(continuation)


def _continuation_after_failed_required_row(world: CaseWorld) -> str:
    world.ready()
    _, second = world.link_rows(HOST_ROW_ORDER[:2])
    failed = world.link(world.receipt("D-1", 3, after=second, outcome="app-failure"))
    continuation = world.receipt("D-5", 4, after=failed)
    world.publish(continuation)
    return world.bind_then_verify(continuation)


def _continuation_after_interleaved_link(world: CaseWorld) -> str:
    """Another link lands between D-1 and D-5 in one window: D-5 fails closed."""
    world.ready()
    (required,) = world.link_rows(("D-1",))
    world.link(world.receipt("R-1", 2, after=required))
    continuation = world.receipt("D-5", 3, after=required)
    world.publish(continuation)
    return world.bind_then_verify(continuation)


def _api_continuation_after_other_row(world: CaseWorld) -> str:
    world.ready()
    (host_row,) = world.link_rows(("D-1",))
    continuation = world.receipt("API-D-5", 2, after=host_row)
    world.publish(continuation)
    return world.bind_then_verify(continuation)


# -- h, i: held bytes and evidence ----------------------------------------------


def _held_bytes(
    request_raw: Callable[[DerivedReceipt], bytes | None],
    receipt_raw: Callable[[DerivedReceipt], bytes | None],
) -> Callable[[CaseWorld], str]:
    def run(world: CaseWorld) -> str:
        world.ready()
        first = world.receipt("R-1", 1)
        world.publish_as(
            first.provenance,
            request_raw=request_raw(first),
            receipt_raw=receipt_raw(first),
        )
        return world.bind_then_verify(first)

    return run


def _no_evidence(world: CaseWorld) -> str:
    world.ready(evidence=False)
    first = world.receipt("R-1", 1)
    world.publish(first)
    return world.bind_then_verify(first)


# -- bind_publication obligations -----------------------------------------------


def _bind_never_published(world: CaseWorld) -> str:
    world.ready()
    first = world.receipt("R-1", 1)
    world.observe(first)
    return _outcome_of(world.bind(first))


def _relink_with_another_receipt(world: CaseWorld) -> str:
    """A linked key never takes a second, different receipt."""
    world.ready()
    (first,) = world.link_rows(HOST_ROW_ORDER[:1])
    receipt_ref = first.publication.receipt_raw_ref
    if receipt_ref is None:
        return "TEMPLATE_HAS_NO_RECEIPT_RAW_REF"
    other_bytes = first.receipt_raw + b" again"
    other = _with_publication(
        first.provenance,
        receipt_raw_ref=_raw_ref_for(receipt_ref, "again", other_bytes),
    )
    world.publish_as(other, request_raw=first.request_raw, receipt_raw=other_bytes)
    return _outcome_of(world.bind_published(other))


def _bind_selection_foreign(world: CaseWorld) -> str:
    world.ready()
    first = world.receipt("R-1", 1)
    foreign_key = replace(first.key, selection=world.foreign_selection)
    world.publish_as(
        replace(first.provenance, operation_key=foreign_key),
        request_raw=first.request_raw,
        receipt_raw=first.receipt_raw,
    )
    return _outcome_of(world.bind(first))


def _bind_occurrence_witness_differs(world: CaseWorld) -> str:
    world.ready()
    first = world.receipt("R-1", 1)
    world.publish(first)
    return _outcome_of(
        world.bind(first, occurrence=replace(first.occurrence, witness=world.other_witness))
    )


def _bind_publication_witness_differs(world: CaseWorld) -> str:
    world.ready()
    first = world.receipt("R-1", 1)
    world.publish(first)
    return _outcome_of(world.bind(first, witness=world.other_witness))


def _bind_published_variant(
    vary: Callable[[ReceiptProvenance], ReceiptProvenance],
) -> Callable[[CaseWorld], str]:
    def run(world: CaseWorld) -> str:
        world.ready()
        first = world.receipt("R-1", 1)
        varied = vary(first.provenance)
        world.publish_as(
            varied, request_raw=first.request_raw, receipt_raw=first.receipt_raw
        )
        return _outcome_of(world.bind_published(varied))

    return run


def _bind_publication_differs(world: CaseWorld) -> str:
    world.ready()
    first = world.receipt("R-1", 1)
    world.publish(first)
    log_ref = first.publication.numbered_log_ref
    if log_ref is None:
        return "TEMPLATE_HAS_NO_NUMBERED_LOG_REF"
    other_publication = replace(
        first.publication,
        numbered_log_ref=replace(log_ref, sha256=_other_digest(log_ref.sha256)),
    )
    return _outcome_of(world.bind(first, publication=other_publication))


_MISSING = RefusalCode.PRIOR_MISSING
_UNVERIFIED_PRIOR = RefusalCode.PRIOR_UNVERIFIED
_UNVERIFIED_RESULT = RefusalCode.RESULT_UNVERIFIED

CONFORMANCE_CASES: Final[tuple[ConformanceCase, ...]] = (
    ConformanceCase("host-rows-linked-in-order", "a-i", None, _host_rows_linked_in_order),
    ConformanceCase("api-rows-linked-in-order", "a-i", None, _api_rows_linked_in_order),
    ConformanceCase("linked-boundaries-accepted", "C3", None, _linked_boundaries_accepted),
    ConformanceCase("relink-answers-its-link", "bind", None, _relink_answers_its_link),
    ConformanceCase(
        "boundary-outside-linked-set",
        "C3",
        RefusalCode.SCOPE_MISMATCH,
        _boundaries_outside_linked_set,
    ),
    ConformanceCase("key-of-another-class", "a", _UNVERIFIED_RESULT, _key_of_another_class),
    ConformanceCase(
        "receipt-of-another-class", "a", _UNVERIFIED_RESULT, _receipt_of_another_class
    ),
    ConformanceCase(
        "receipt-for-another-key", "a", _UNVERIFIED_RESULT, _receipt_for_another_key
    ),
    ConformanceCase("window-not-anchored", "b", _MISSING, _window_not_anchored),
    ConformanceCase("key-in-unanchored-window", "b", _MISSING, _key_in_unanchored_window),
    ConformanceCase(
        "window-tainted-after-link",
        "c",
        RefusalCode.WINDOW_INELIGIBLE,
        _window_tainted_after_link,
    ),
    ConformanceCase(
        "window-tainted-before-link",
        "c",
        RefusalCode.WINDOW_INELIGIBLE,
        _window_tainted_before_link,
    ),
    ConformanceCase(
        "published-never-linked", "d", _UNVERIFIED_RESULT, _published_never_linked
    ),
    ConformanceCase(
        "observed-never-linked", "d", _UNVERIFIED_RESULT, _observed_never_linked
    ),
    ConformanceCase(
        "caller-omits-linked-predecessor",
        "C2",
        _MISSING,
        _caller_omits_linked_predecessor,
    ),
    ConformanceCase(
        "caller-names-predecessor-none-linked",
        "C2",
        _UNVERIFIED_PRIOR,
        _caller_names_predecessor_none_linked,
    ),
    ConformanceCase(
        "caller-predecessor-tampered", "C2", _UNVERIFIED_PRIOR, _caller_predecessor_tampered
    ),
    ConformanceCase(
        "caller-predecessor-of-another-class",
        "C2",
        _UNVERIFIED_PRIOR,
        _caller_predecessor_of_another_class,
    ),
    ConformanceCase(
        "caller-predecessor-chain-of-another-class",
        "C2",
        _UNVERIFIED_PRIOR,
        _caller_predecessor_chain_of_another_class,
    ),
    ConformanceCase(
        "caller-predecessor-forged-success",
        "C2",
        _UNVERIFIED_PRIOR,
        _caller_predecessor_forged_success,
    ),
    ConformanceCase(
        "caller-receipt-tampered", "e", _UNVERIFIED_RESULT, _caller_receipt_tampered
    ),
    ConformanceCase(
        "caller-receipt-forged-success",
        "e",
        _UNVERIFIED_RESULT,
        _caller_receipt_forged_success,
    ),
    ConformanceCase("link-without-naming-head", "f", _MISSING, _link_without_naming_head),
    ConformanceCase("link-after-non-head", "f", _UNVERIFIED_PRIOR, _link_after_non_head),
    ConformanceCase(
        "link-after-planted-predecessor",
        "f",
        _UNVERIFIED_PRIOR,
        _link_after_planted_predecessor,
    ),
    ConformanceCase(
        "link-after-other-window-receipt",
        "f",
        _UNVERIFIED_PRIOR,
        _link_after_other_window_receipt,
    ),
    ConformanceCase(
        "link-after-tainted-window-receipt",
        "f",
        _UNVERIFIED_PRIOR,
        _link_after_tainted_window_receipt,
    ),
    ConformanceCase(
        "continuation-without-predecessor",
        "g",
        _MISSING,
        _continuation_without_predecessor("D-5"),
    ),
    ConformanceCase(
        "api-continuation-without-predecessor",
        "g",
        _MISSING,
        _continuation_without_predecessor("API-D-5"),
    ),
    ConformanceCase(
        "continuation-after-other-row", "g", _UNVERIFIED_PRIOR, _continuation_after_other_row
    ),
    ConformanceCase(
        "continuation-after-failed-required-row",
        "g",
        _UNVERIFIED_PRIOR,
        _continuation_after_failed_required_row,
    ),
    ConformanceCase(
        "continuation-after-interleaved-link",
        "g",
        _UNVERIFIED_PRIOR,
        _continuation_after_interleaved_link,
    ),
    ConformanceCase(
        "api-continuation-after-other-row",
        "g",
        _UNVERIFIED_PRIOR,
        _api_continuation_after_other_row,
    ),
    ConformanceCase(
        "no-bytes-held",
        "h",
        _UNVERIFIED_RESULT,
        _held_bytes(lambda receipt: None, lambda receipt: None),
    ),
    ConformanceCase(
        "receipt-bytes-differ",
        "h",
        _UNVERIFIED_RESULT,
        _held_bytes(
            lambda receipt: receipt.request_raw, lambda receipt: receipt.receipt_raw + b" "
        ),
    ),
    ConformanceCase(
        "request-bytes-differ",
        "h",
        _UNVERIFIED_RESULT,
        _held_bytes(
            lambda receipt: receipt.request_raw + b" ", lambda receipt: receipt.receipt_raw
        ),
    ),
    ConformanceCase("no-evidence", "i", _UNVERIFIED_RESULT, _no_evidence),
    ConformanceCase(
        "bind-never-published", "bind", _UNVERIFIED_RESULT, _bind_never_published
    ),
    ConformanceCase(
        "relink-with-another-receipt",
        "bind",
        _UNVERIFIED_RESULT,
        _relink_with_another_receipt,
    ),
    ConformanceCase(
        "bind-selection-foreign",
        "bind",
        RefusalCode.SELECTION_FOREIGN,
        _bind_selection_foreign,
    ),
    ConformanceCase(
        "bind-occurrence-witness-differs",
        "bind",
        _UNVERIFIED_PRIOR,
        _bind_occurrence_witness_differs,
    ),
    ConformanceCase(
        "bind-publication-witness-differs",
        "bind",
        _UNVERIFIED_PRIOR,
        _bind_publication_witness_differs,
    ),
    ConformanceCase(
        "bind-incomplete-receipt",
        "bind",
        _UNVERIFIED_RESULT,
        _bind_published_variant(lambda receipt: replace(receipt, state="incomplete")),
    ),
    ConformanceCase(
        "bind-cleanup-incomplete",
        "bind",
        _UNVERIFIED_RESULT,
        _bind_published_variant(
            lambda receipt: _with_publication(receipt, cleanup_state="incomplete")
        ),
    ),
    ConformanceCase(
        "bind-outcome-uncertain",
        "bind",
        _UNVERIFIED_RESULT,
        _bind_published_variant(
            lambda receipt: _with_publication(receipt, outcome="uncertain")
        ),
    ),
    ConformanceCase(
        "bind-occurrence-started",
        "bind",
        _UNVERIFIED_RESULT,
        _bind_published_variant(
            lambda receipt: _with_occurrence(receipt, state="started")
        ),
    ),
    ConformanceCase(
        "bind-publication-differs", "bind", _UNVERIFIED_RESULT, _bind_publication_differs
    ),
)
"""Every case, good ones first; names are unique."""


def run_conformance(
    factory: AdapterFactory,
    templates: ConformanceTemplates,
    *,
    cases: Sequence[ConformanceCase] = CONFORMANCE_CASES,
) -> tuple[CaseOutcome, ...]:
    """Run each case on a fresh adapter from ``factory``; return every outcome.

    An adapter's refusal in a case's setup, or an exception it raises, fails
    that case (outcome ``SETUP_REFUSED:...`` or ``RAISED:<type>``) without
    ending the run. Bad arguments fail at once.
    """
    if not callable(factory):
        raise TypeError("factory must be a callable returning AdapterUnderTest")
    if type(templates) is not ConformanceTemplates:
        raise TypeError("templates must be ConformanceTemplates")
    if not cases:
        raise ValueError("cases must not be empty")
    outcomes: list[CaseOutcome] = []
    for case in cases:
        adapter = factory()
        if type(adapter) is not AdapterUnderTest:
            raise TypeError("factory must return AdapterUnderTest")
        world = CaseWorld(adapter, templates)
        try:
            actual = case.run(world)
        except _SetupRefused as refused:
            actual = f"SETUP_REFUSED:{refused.step}:{refused.outcome}"
        except Exception as error:  # the adapter's failure is that case's outcome
            actual = f"RAISED:{type(error).__name__}"
        outcomes.append(
            CaseOutcome(
                name=case.name,
                obligation=case.obligation,
                expected=case.expected_outcome,
                actual=actual,
            )
        )
    return tuple(outcomes)


def failed_outcomes(outcomes: Iterable[CaseOutcome]) -> tuple[CaseOutcome, ...]:
    """The outcomes that did not match their expected answer."""
    return tuple(outcome for outcome in outcomes if not outcome.passed)


__all__ = [
    "ACCEPTED",
    "API_ROW_ORDER",
    "CONFORMANCE_CASES",
    "HOST_ROW_ORDER",
    "AdapterFactory",
    "AdapterUnderTest",
    "CaseOutcome",
    "CaseWorld",
    "ConformanceCase",
    "ConformanceTemplates",
    "DerivedReceipt",
    "HostFeed",
    "derive_row_receipt",
    "failed_outcomes",
    "run_conformance",
]
