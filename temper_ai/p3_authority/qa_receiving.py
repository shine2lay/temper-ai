"""Deterministic P3 N5 ``QAReceivingVerifier`` over the publication cohort.

Implements ``temper_ai.p3_authority._providers.QAReceivingVerifier`` (Wave 1 row
``QA-T5-N5``) without importing from ``configs/`` or touching shared authority
files. Refuses at ``before_checker`` and ``before_count`` unless:

1. ``QAReceiving`` and ``SelectedJob`` carry complete non-empty identity fields
   (``receiving_reference.path``, lowercase 64-hex ``digest``, positive ``length``,
   ``revision``, and ``receiver.process_registration``) (else ``QA_RECEIVING_MISSING``).
2. The read-only ``PublicationCohortSource`` port returns a well-formed
   ``PublicationCohort`` (else ``QA_RECEIVING_MISSING``).
3. The cohort contains a Chromium browser leg, a WebKit browser leg, and at
   least one host-row (``RowKey``) publication (else ``QA_RECEIVING_MISSING``).
4. Every member occurrence key in the cohort is unique (else ``ALREADY_COUNTED``).
5. Cohort ``kit_id``, ``kit_sha256``, ``final_sha256``, ``cohort_schema``, and
   each member's ``publication_schema`` match ``OriginalExpectations`` by exact
   equality with no case, whitespace, or path normalization, all digests are
   strictly lowercase 64-character hex, each member's ``receipt_raw_ref.sha256``
   matches the cohort inventory digest, M02 complete-cohort state holds over all
   members with certain outcomes and complete non-uncertain terminal cleanup,
   and ``D-1`` is published before ``D-5`` (else ``RESULT_UNVERIFIED``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, runtime_checkable

from p3_host_contracts import (
    LifecycleKey,
    OccurrenceHandle,
    OperationKey,
    RawPublication,
    RawRef,
    RowKey,
)
from temper_ai.p3_authority._providers import QAReceivingVerifier
from temper_ai.p3_authority.contract import (
    Boundary,
    ImmutableReference,
    Phase,
    QAReceiving,
    Refusal,
    RefusalCode,
    RetryKind,
    SelectedJob,
)
from temper_ai.p3_authority.registry import boundary_to_phase, make_refusal

CohortLeg = Literal["chromium", "webkit", "host_row"]

_LOWER_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")
_ALLOWED_LEGS: Final[frozenset[str]] = frozenset({"chromium", "webkit", "host_row"})
_CERTAIN_OUTCOMES: Final[frozenset[str]] = frozenset(
    {"success", "app-failure", "host-failure", "refused"}
)
_CERTAIN_OCCURRENCE_STATES: Final[frozenset[str]] = frozenset({"completed", "refused"})
_COMPLETE_CLEANUP_STATES: Final[frozenset[str]] = frozenset(
    {"complete", "not-required"}
)
_PREDECESSOR_CRASH_ROW: Final[Mapping[str, str]] = {
    "D-5": "D-1",
    "API-D-5": "API-D-1",
}


def _is_exact_non_empty_str(value: object) -> bool:
    """Return True iff ``value`` is a non-empty ``str`` with no outer whitespace."""
    return type(value) is str and bool(value) and value.strip() == value


def _is_positive_int(value: object) -> bool:
    """Return True iff ``value`` is a positive ``int`` and not a ``bool``."""
    return type(value) is int and value > 0


def _is_lowercase_sha256(value: object) -> bool:
    """Return True iff ``value`` is a 64-character lowercase hexadecimal ``str``."""
    return (
        type(value) is str
        and len(value) == 64
        and all(ch in _LOWER_HEX for ch in value)
    )


def _require_exact_non_empty_str(cls_name: str, field_name: str, value: object) -> None:
    if not _is_exact_non_empty_str(value):
        raise ValueError(
            f"{cls_name}.{field_name} must be a non-empty str without outer whitespace"
        )


def _require_lowercase_sha256(cls_name: str, field_name: str, value: object) -> None:
    if not _is_lowercase_sha256(value):
        raise ValueError(
            f"{cls_name}.{field_name} must be a 64-character lowercase hex sha256"
        )


@dataclass(frozen=True, slots=True)
class OriginalExpectations:
    """QA's original pinned expectations for P3 publication-cohort verification.

    Validated fail-loud at construction: every string must be non-empty without
    leading/trailing whitespace, and ``kit_sha256`` / ``final_sha256`` must be
    strictly 64-character lowercase hexadecimal digests.
    """

    kit_id: str
    kit_sha256: str
    final_sha256: str
    publication_schema: str
    cohort_schema: str

    def __post_init__(self) -> None:
        _require_exact_non_empty_str("OriginalExpectations", "kit_id", self.kit_id)
        _require_lowercase_sha256("OriginalExpectations", "kit_sha256", self.kit_sha256)
        _require_lowercase_sha256(
            "OriginalExpectations", "final_sha256", self.final_sha256
        )
        _require_exact_non_empty_str(
            "OriginalExpectations", "publication_schema", self.publication_schema
        )
        _require_exact_non_empty_str(
            "OriginalExpectations", "cohort_schema", self.cohort_schema
        )


@dataclass(frozen=True, slots=True)
class PublicationCohortMember:
    """One member publication in a P3 QA receiving cohort.

    Reuses ``p3_host_contracts.RawPublication`` (carrying ``occurrence`` with
    ``OperationKey``, ``receipt_raw_ref: RawRef``, ``request_raw_ref: RawRef | None``,
    ``outcome``, and ``cleanup_state``) together with its publication schema and
    the cohort inventory digest recorded for ``receipt_raw_ref``.
    """

    leg: str
    publication: RawPublication[Any, Any, Any, Any, Any, Any, Any, Any, Any]
    publication_schema: str
    inventory_receipt_sha256: str


@dataclass(frozen=True, slots=True)
class PublicationCohort:
    """Complete read-only cohort snapshot loaded for a ``QAReceiving`` reference."""

    cohort_schema: str
    kit_id: str
    kit_sha256: str
    final_sha256: str
    complete_publication: bool
    members: tuple[PublicationCohortMember, ...]


@runtime_checkable
class PublicationCohortSource(Protocol):
    """Read-only port supplying the ``PublicationCohort`` for ``QAReceiving``."""

    def load_cohort(
        self,
        receiving_reference: ImmutableReference,
        *,
        selection_revision: str,
    ) -> PublicationCohort | None:
        """Return the ``PublicationCohort`` for ``receiving_reference`` or ``None``."""


class MappingPublicationCohortSource:
    """Immutable read-only ``PublicationCohortSource`` backed by an exact-key mapping.

    Keys must be exact ``(receiving_reference.digest, selection_revision)``
    2-tuples (64-character lowercase hex SHA-256 ``str`` and non-empty ``str``
    without outer whitespace), and values must be ``PublicationCohort`` or
    ``None``. Looks up only ``(receiving_reference.digest, selection_revision)``
    with no path or bare-key fallback; a real store port must key the same way.
    """

    def __init__(
        self,
        cohorts: Mapping[tuple[str, str], PublicationCohort | None],
    ) -> None:
        if not isinstance(cohorts, Mapping):
            raise ValueError("cohorts must be a Mapping")
        validated: dict[tuple[str, str], PublicationCohort | None] = {}
        for key, value in cohorts.items():
            if not (
                type(key) is tuple
                and len(key) == 2
                and _is_lowercase_sha256(key[0])
                and _is_exact_non_empty_str(key[1])
            ):
                raise ValueError(
                    "MappingPublicationCohortSource keys must be "
                    "(64-char lowercase hex digest, exact non-empty selection_revision) tuples"
                )
            if value is not None and not isinstance(value, PublicationCohort):
                raise ValueError(
                    "MappingPublicationCohortSource values must be PublicationCohort or None"
                )
            validated[(key[0], key[1])] = value
        self._cohorts: dict[tuple[str, str], PublicationCohort | None] = validated

    def load_cohort(
        self,
        receiving_reference: ImmutableReference,
        *,
        selection_revision: str,
    ) -> PublicationCohort | None:
        digest = getattr(receiving_reference, "digest", None)
        if not (
            type(digest) is str
            and _is_lowercase_sha256(digest)
            and type(selection_revision) is str
            and _is_exact_non_empty_str(selection_revision)
        ):
            return None
        return self._cohorts.get((digest, selection_revision))


def _is_well_formed_member(member: object) -> bool:
    if not isinstance(member, PublicationCohortMember):
        return False
    if type(member.leg) is not str or member.leg not in _ALLOWED_LEGS:
        return False
    pub = member.publication
    if not isinstance(pub, RawPublication):
        return False
    if not isinstance(pub.occurrence, OccurrenceHandle):
        return False
    if not isinstance(pub.occurrence.key, (LifecycleKey, RowKey)):
        return False
    if not isinstance(pub.receipt_raw_ref, RawRef):
        return False
    return True


def _is_well_formed_cohort(cohort: object) -> bool:
    return (
        isinstance(cohort, PublicationCohort)
        and isinstance(cohort.members, tuple)
        and len(cohort.members) > 0
        and all(_is_well_formed_member(member) for member in cohort.members)
    )


def _iter_member_raw_refs(member: PublicationCohortMember) -> tuple[RawRef, ...]:
    pub = member.publication
    refs: list[RawRef] = [pub.receipt_raw_ref]
    for optional_ref in (
        pub.request_raw_ref,
        pub.window_ref,
        pub.numbered_log_ref,
        pub.current_row_ref,
    ):
        if isinstance(optional_ref, RawRef):
            refs.append(optional_ref)
    for ev_ref in pub.evidence_refs:
        if isinstance(ev_ref, RawRef):
            refs.append(ev_ref)
    key = pub.occurrence.key
    if isinstance(key, RowKey):
        refs.append(key.binding_ref)
        refs.append(key.request_raw_ref)
    return tuple(refs)


def _check_qa_receiving_fields(
    qa_receiving: QAReceiving,
    *,
    selected_job: SelectedJob,
    boundary: Boundary,
) -> bool:
    """Enforce complete ``QAReceiving`` and ``SelectedJob`` fields -> ``QA_RECEIVING_MISSING``."""
    try:
        boundary_to_phase(boundary)
    except ValueError:
        return False
    if not isinstance(selected_job, SelectedJob) or not _is_exact_non_empty_str(
        selected_job.selection_revision
    ):
        return False
    ref = getattr(qa_receiving, "receiving_reference", None)
    receiver = getattr(qa_receiving, "receiver", None)
    if ref is None or receiver is None:
        return False
    proc_reg = getattr(receiver, "process_registration", None)
    if not _is_exact_non_empty_str(proc_reg):
        return False
    if not (
        _is_exact_non_empty_str(getattr(ref, "path", None))
        and _is_lowercase_sha256(getattr(ref, "digest", None))
        and _is_positive_int(getattr(ref, "length", None))
        and _is_exact_non_empty_str(getattr(ref, "revision", None))
    ):
        return False
    return True


def _check_cohort_present(cohort: PublicationCohort | None) -> bool:
    """Enforce well-formed non-empty ``PublicationCohort`` presence -> ``QA_RECEIVING_MISSING``."""
    return _is_well_formed_cohort(cohort)


def _check_chromium_leg_present(cohort: PublicationCohort | None) -> bool:
    """Enforce presence of the Chromium leg in the cohort -> ``QA_RECEIVING_MISSING``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return any(
        member.leg == "chromium"
        and isinstance(member.publication.occurrence.key, LifecycleKey)
        for member in cohort.members
    )


def _check_webkit_leg_present(cohort: PublicationCohort | None) -> bool:
    """Enforce presence of the WebKit leg in the cohort -> ``QA_RECEIVING_MISSING``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return any(
        member.leg == "webkit"
        and isinstance(member.publication.occurrence.key, LifecycleKey)
        for member in cohort.members
    )


def _check_host_row_present(cohort: PublicationCohort | None) -> bool:
    """Enforce presence of at least one host-row (``RowKey``) publication -> ``QA_RECEIVING_MISSING``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return any(
        member.leg == "host_row"
        and isinstance(member.publication.occurrence.key, RowKey)
        for member in cohort.members
    )


def _check_unique_occurrence_keys(cohort: PublicationCohort | None) -> bool:
    """Enforce unique ``OperationKey`` across cohort members -> ``ALREADY_COUNTED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    seen: set[OperationKey[Any]] = set()
    for member in cohort.members:
        key = member.publication.occurrence.key
        if key in seen:
            return False
        seen.add(key)
    return True


def _check_kit_id(
    cohort: PublicationCohort | None,
    expectations: OriginalExpectations,
) -> bool:
    """Enforce exact ``cohort.kit_id == expectations.kit_id`` -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return type(cohort.kit_id) is str and cohort.kit_id == expectations.kit_id


def _check_kit_sha256(
    cohort: PublicationCohort | None,
    expectations: OriginalExpectations,
) -> bool:
    """Enforce exact ``cohort.kit_sha256 == expectations.kit_sha256`` -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return (
        type(cohort.kit_sha256) is str and cohort.kit_sha256 == expectations.kit_sha256
    )


def _check_final_sha256(
    cohort: PublicationCohort | None,
    expectations: OriginalExpectations,
) -> bool:
    """Enforce exact ``cohort.final_sha256 == expectations.final_sha256`` -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return (
        type(cohort.final_sha256) is str
        and cohort.final_sha256 == expectations.final_sha256
    )


def _check_cohort_schema(
    cohort: PublicationCohort | None,
    expectations: OriginalExpectations,
) -> bool:
    """Enforce exact ``cohort.cohort_schema == expectations.cohort_schema`` -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return (
        type(cohort.cohort_schema) is str
        and cohort.cohort_schema == expectations.cohort_schema
    )


def _check_publication_schema(
    cohort: PublicationCohort | None,
    expectations: OriginalExpectations,
) -> bool:
    """Enforce exact ``member.publication_schema == expectations.publication_schema`` -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return all(
        type(member.publication_schema) is str
        and member.publication_schema == expectations.publication_schema
        for member in cohort.members
    )


def _check_lowercase_digests(cohort: PublicationCohort | None) -> bool:
    """Enforce strictly lowercase 64-hex digests across cohort and members -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    if not (
        _is_lowercase_sha256(cohort.kit_sha256)
        and _is_lowercase_sha256(cohort.final_sha256)
    ):
        return False
    for member in cohort.members:
        if not _is_lowercase_sha256(member.inventory_receipt_sha256):
            return False
        for raw_ref in _iter_member_raw_refs(member):
            if not _is_lowercase_sha256(raw_ref.sha256):
                return False
    return True


def _check_member_inventory_digests(cohort: PublicationCohort | None) -> bool:
    """Enforce ``member.publication.receipt_raw_ref.sha256 == member.inventory_receipt_sha256`` -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    for member in cohort.members:
        receipt_ref = member.publication.receipt_raw_ref
        if (
            type(member.inventory_receipt_sha256) is not str
            or receipt_ref.sha256 != member.inventory_receipt_sha256
        ):
            return False
        if receipt_ref.byte_length <= 0:
            return False
        request_ref = member.publication.request_raw_ref
        if request_ref is not None and request_ref.byte_length <= 0:
            return False
    return True


def _check_m02_complete_publication(cohort: PublicationCohort | None) -> bool:
    """Enforce M02 cohort-wide ``complete_publication is True`` -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    return (
        type(cohort.complete_publication) is bool
        and cohort.complete_publication is True
    )


def _check_m02_member_certainty(cohort: PublicationCohort | None) -> bool:
    """Enforce M02 per-member outcome certainty and complete non-uncertain cleanup -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    for member in cohort.members:
        pub = member.publication
        if (
            pub.outcome not in _CERTAIN_OUTCOMES
            or pub.occurrence.state not in _CERTAIN_OCCURRENCE_STATES
            or pub.cleanup_state not in _COMPLETE_CLEANUP_STATES
        ):
            return False
    return True


def _check_d1_before_d5(cohort: PublicationCohort | None) -> bool:
    """Enforce that ``D-1`` crash publication precedes ``D-5`` start publication -> ``RESULT_UNVERIFIED``."""
    if not _is_well_formed_cohort(cohort):
        return True
    assert cohort is not None
    host_rows: list[tuple[int, RowKey[Any]]] = []
    for index, member in enumerate(cohort.members):
        key = member.publication.occurrence.key
        if member.leg == "host_row" and isinstance(key, RowKey):
            host_rows.append((index, key))

    for index, key in host_rows:
        if key.row in ("D-1", "API-D-1") and key.operation != "crash":
            return False
        if key.row in _PREDECESSOR_CRASH_ROW:
            if key.operation != "start":
                return False
            expected_crash_row = _PREDECESSOR_CRASH_ROW[key.row]
            matching_crashes = [
                (prior_index, prior_key)
                for prior_index, prior_key in host_rows
                if prior_key.row == expected_crash_row
                and prior_key.operation == "crash"
                and prior_key.selection == key.selection
                and prior_key.window_id == key.window_id
            ]
            if not matching_crashes:
                return False
            if any(
                prior_index >= index or prior_key.sequence >= key.sequence
                for prior_index, prior_key in matching_crashes
            ):
                return False
    return True


def _refuse(code: RefusalCode, boundary: Boundary) -> Refusal:
    try:
        phase = boundary_to_phase(boundary)
    except ValueError:
        phase = Phase.A
    retry_kind = (
        RetryKind.SAME_BOUNDARY_AFTER_REPAIR
        if code is RefusalCode.QA_RECEIVING_MISSING
        else RetryKind.NOT_APPLICABLE
    )
    return make_refusal(
        code,
        phase=phase,
        retry_kind=retry_kind,
    )


class PublicationCohortQAReceivingVerifier(QAReceivingVerifier):
    """Concrete read-only ``QAReceivingVerifier`` over a ``PublicationCohortSource``."""

    def __init__(
        self,
        *,
        cohort_source: PublicationCohortSource,
        expectations: OriginalExpectations,
    ) -> None:
        if not isinstance(expectations, OriginalExpectations):
            raise ValueError("expectations must be an OriginalExpectations instance")
        if cohort_source is None or not callable(
            getattr(cohort_source, "load_cohort", None)
        ):
            raise ValueError("cohort_source must implement load_cohort")
        self._cohort_source = cohort_source
        self._expectations = expectations

    @property
    def expectations(self) -> OriginalExpectations:
        return self._expectations

    def verify_qa_receiving(
        self,
        qa_receiving: QAReceiving,
        *,
        selected_job: SelectedJob,
        boundary: Boundary,
    ) -> Refusal | None:
        if not _check_qa_receiving_fields(
            qa_receiving,
            selected_job=selected_job,
            boundary=boundary,
        ):
            return _refuse(RefusalCode.QA_RECEIVING_MISSING, boundary)

        cohort: PublicationCohort | None = None
        ref = getattr(qa_receiving, "receiving_reference", None)
        sel_rev = getattr(selected_job, "selection_revision", None)
        if ref is not None and type(sel_rev) is str:
            try:
                cohort = self._cohort_source.load_cohort(
                    ref,
                    selection_revision=sel_rev,
                )
            except Exception:
                cohort = None

        try:
            if not _check_cohort_present(cohort):
                return _refuse(RefusalCode.QA_RECEIVING_MISSING, boundary)
            if not _check_chromium_leg_present(cohort):
                return _refuse(RefusalCode.QA_RECEIVING_MISSING, boundary)
            if not _check_webkit_leg_present(cohort):
                return _refuse(RefusalCode.QA_RECEIVING_MISSING, boundary)
            if not _check_host_row_present(cohort):
                return _refuse(RefusalCode.QA_RECEIVING_MISSING, boundary)
            if not _check_unique_occurrence_keys(cohort):
                return _refuse(RefusalCode.ALREADY_COUNTED, boundary)
            if not _check_kit_id(cohort, self._expectations):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_kit_sha256(cohort, self._expectations):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_final_sha256(cohort, self._expectations):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_cohort_schema(cohort, self._expectations):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_publication_schema(cohort, self._expectations):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_lowercase_digests(cohort):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_member_inventory_digests(cohort):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_m02_complete_publication(cohort):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_m02_member_certainty(cohort):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
            if not _check_d1_before_d5(cohort):
                return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)
        except Exception:
            return _refuse(RefusalCode.RESULT_UNVERIFIED, boundary)

        return None


__all__ = [
    "CohortLeg",
    "MappingPublicationCohortSource",
    "OriginalExpectations",
    "PublicationCohort",
    "PublicationCohortMember",
    "PublicationCohortQAReceivingVerifier",
    "PublicationCohortSource",
]
