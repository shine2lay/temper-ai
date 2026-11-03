"""QA's production ``PublicationCohortSource``: read-only, content-addressed snapshots.

``FilePublicationCohortStore`` loads the publication cohort QA issued for one
``QAReceiving.receiving_reference``. It looks a snapshot up only by the exact pair
(``receiving_reference.digest``, ``selection_revision``):

* the file is ``<root>/cohorts/<receiving_reference.digest>.json``;
* ``receiving_reference.path`` is never used to find a file (no path fallback and no
  bare-key fallback); it is only copied into the returned snapshot reference;
* the bytes read must hash to ``receiving_reference.digest`` and have exactly
  ``receiving_reference.length`` bytes;
* the snapshot's embedded ``selection_revision`` must equal the requested one exactly.

The store checks byte identity and format only. Whether a cohort is acceptable (legs,
kit and schema expectations, certainty, D-1 before D-5) stays with
``PublicationCohortQAReceivingVerifier`` in ``qa_receiving``. The store never writes,
never creates directories and never follows a symlink at the ``cohorts`` directory
or the snapshot leaf (both are opened with ``O_NOFOLLOW`` relative to their parent
directory descriptor). Symlinks above the configured root are the deployer's choice.
Same-UID writers are not excluded: a process running as the store's user can rewrite
a snapshot; the digest check only detects bytes that differ from the reference.

Snapshot format ``qa-p3-publication-cohort-snapshot/1`` (strict UTF-8 JSON: no
duplicate keys, no NaN/Infinity, every object has exactly the keys listed; text values
are non-empty strings, integers are JSON integers, never booleans):

``{"schema", "selection_revision", "cohort_schema", "kit_id", "kit_sha256",
"final_sha256", "complete_publication": bool, "members": [member, ...]}``

* member: ``{"leg": "chromium"|"webkit"|"host_row", "publication_schema",
  "inventory_receipt_sha256", "publication": publication}``
* publication (``p3_host_contracts.RawPublication``): ``{"occurrence", "producer_instance":
  process, "publisher_instance": process, "request_raw_ref": raw_ref|null,
  "receipt_raw_ref": raw_ref, "evidence_refs": [raw_ref], "window_ref": raw_ref|null,
  "numbered_log_ref": raw_ref|null, "current_row_ref": raw_ref|null,
  "publication_steps": [witness], "observed_interval": interval, "outcome",
  "cleanup_state"}``
* occurrence (``OccurrenceHandle``): ``{"key": key, "witness": witness,
  "admitting_process": process, "controller": process|null, "executing_processes":
  [process], "route_witness": witness, "targets": [subject], "source_epoch":
  N3SourceEpoch, "observation_epoch": N3ObservationEpoch, "admission_boundary":
  host_effect, "state"}``
* key: ``{"key_kind": "lifecycle", "selection", "launch_id", "operation_id"}`` or
  ``{"key_kind": "row", "selection", "window_id", "binding_ref", "writer", "row",
  "operation", "request_id", "sequence": int >= 1, "request_raw_ref"}``
* host_effect (``HostEffect``): ``{"kind", "selection", "target": subject, "operation",
  "actor": subject, "purpose", "roots": [root_scope], "boundary"}``
* root_scope (``RootScope``): ``{"role", "actor": subject, "selected_locator",
  "expected_existing_object": root_object|null, "new_leaf": str|null,
  "required_rights": [unique str]}``
* raw_ref (``RawRef``): ``{"root_locator", "relative_path", "byte_length": int >= 0,
  "sha256"}``
* selection (``HostSelectionHandle``): ``{"selection_reference", "selection_revision"}``
* witness (``NativeWitnessValue``): ``{"witness_reference"}``
* process (``NativeProcessRefValue``): ``{"process_registration"}``
* interval (``NativeIntervalValue``): ``{"clock_domain", "interval_witness": witness}``
* root_object (``NativeRootObjectValue``): ``{"filesystem_object", "mount_identity",
  "namespace_identity", "observation_epoch"}``
* subject (``FutureSubjectRecord`` / ``ExistingSubjectRecord``):
  ``{"subject_kind": "future", "selected_scope_reference"}`` or
  ``{"subject_kind": "existing", "identity": {"identity_kind": "process",
  "process_registration"} | {"identity_kind": "root_object", ...root_object}}``
* N3SourceEpoch / N3ObservationEpoch: the ``p3_source_closure`` wire encoding
  (``parsing.to_wire``), decoded with ``parsing.decode_record``.

``encode_cohort_snapshot`` writes this format canonically (sorted keys, no spaces).
It is pure and exists for tests and documentation; the store itself never writes.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, TypeVar, get_args

from p3_host_contracts import (
    HostEffect,
    LifecycleKey,
    OccurrenceHandle,
    RawPublication,
    RawRef,
    RootScope,
    RowKey,
)
from p3_source_closure import N3ObservationEpoch, N3SourceEpoch
from p3_source_closure.parsing import MAX_DOCUMENT, decode_record, to_wire
from temper_ai.p3_authority.contract import ImmutableReference
from temper_ai.p3_authority.native_values import (
    NativeIntervalValue,
    NativeProcessRefValue,
    NativeRootObjectValue,
    NativeWitnessValue,
)
from temper_ai.p3_authority.qa_receiving import (
    CohortLeg,
    PublicationCohort,
    PublicationCohortMember,
)
from temper_ai.p3_authority.registry import (
    ExistingSubjectRecord,
    FutureSubjectRecord,
    ImmutableReferenceRecord,
)
from temper_ai.p3_authority.selection_snapshot import HostSelectionHandle
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import decode_object

SNAPSHOT_SCHEMA: Final = "qa-p3-publication-cohort-snapshot/1"
COHORTS_DIRECTORY: Final = "cohorts"
# Same value as configs/architecture/bin/ops_host_binding.MAX_DOCUMENT (the R2 receiving
# limit); temper_ai never imports configs/, so it reuses p3_source_closure's constant.
MAX_SNAPSHOT_BYTES: Final = MAX_DOCUMENT

_DIRECTORY_OPEN_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_SNAPSHOT_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_HEX_DIGITS: Final = frozenset("0123456789abcdef")


class CohortSnapshotRefusal(StrEnum):
    """Why no cohort was loaded. Fixed codes only; never snapshot bytes or values."""

    DIGEST_MALFORMED = "DIGEST_MALFORMED"
    SELECTION_REVISION_MALFORMED = "SELECTION_REVISION_MALFORMED"
    REFERENCE_MALFORMED = "REFERENCE_MALFORMED"
    ROOT_UNAVAILABLE = "ROOT_UNAVAILABLE"
    COHORTS_DIRECTORY_SYMLINK = "COHORTS_DIRECTORY_SYMLINK"
    COHORTS_DIRECTORY_INVALID = "COHORTS_DIRECTORY_INVALID"
    SNAPSHOT_ABSENT = "SNAPSHOT_ABSENT"
    SNAPSHOT_SYMLINK = "SNAPSHOT_SYMLINK"
    SNAPSHOT_NOT_REGULAR = "SNAPSHOT_NOT_REGULAR"
    SNAPSHOT_UNREADABLE = "SNAPSHOT_UNREADABLE"
    SNAPSHOT_TOO_LARGE = "SNAPSHOT_TOO_LARGE"
    LENGTH_MISMATCH = "LENGTH_MISMATCH"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    JSON_INVALID = "JSON_INVALID"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    SHAPE_INVALID = "SHAPE_INVALID"
    SELECTION_REVISION_MISMATCH = "SELECTION_REVISION_MISMATCH"
    MEMBER_INVALID = "MEMBER_INVALID"


@dataclass(frozen=True, slots=True)
class CohortSnapshotRead:
    """Outcome of one lookup: a cohort and its snapshot reference, or one refusal."""

    cohort: PublicationCohort | None
    snapshot_reference: ImmutableReferenceRecord | None
    refusal: CohortSnapshotRefusal | None


def _refused(code: CohortSnapshotRefusal) -> CohortSnapshotRead:
    return CohortSnapshotRead(cohort=None, snapshot_reference=None, refusal=code)


# ---------------------------------------------------------------------------
# Guards (module functions, one rule each)
# ---------------------------------------------------------------------------


def _is_text(value: object) -> bool:
    return type(value) is str and value != ""


def _is_lowercase_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX_DIGITS


def _digest_is_well_formed(digest: object) -> bool:
    return _is_lowercase_sha256(digest)


def _selection_revision_is_well_formed(selection_revision: object) -> bool:
    return _is_text(selection_revision)


def _reference_is_well_formed(receiving_reference: object) -> bool:
    length = getattr(receiving_reference, "length", None)
    return (
        _is_text(getattr(receiving_reference, "path", None))
        and _is_text(getattr(receiving_reference, "revision", None))
        and type(length) is int
        and length > 0
    )


def _is_regular_file(mode: int) -> bool:
    return stat.S_ISREG(mode)


def _within_size_limit(size: int) -> bool:
    return size <= MAX_SNAPSHOT_BYTES


def _length_matches(raw: bytes, length: int) -> bool:
    return len(raw) == length


def _digest_matches(raw: bytes, digest: str) -> bool:
    return hashlib.sha256(raw).hexdigest() == digest


def _schema_matches(document: Mapping[str, Any]) -> bool:
    return document.get("schema") == SNAPSHOT_SCHEMA


def _selection_revision_matches(document: Mapping[str, Any], selection_revision: str) -> bool:
    return document["selection_revision"] == selection_revision


def _has_exact_keys(value: Mapping[str, Any], keys: frozenset[str]) -> bool:
    return value.keys() == keys


# ---------------------------------------------------------------------------
# Decoding (the only place snapshot shapes become records)
# ---------------------------------------------------------------------------


class _SnapshotShapeError(ValueError):
    """Internal: a value does not have the documented shape. Carries no payload."""


_SNAPSHOT_KEYS: Final = frozenset(
    {
        "schema",
        "selection_revision",
        "cohort_schema",
        "kit_id",
        "kit_sha256",
        "final_sha256",
        "complete_publication",
        "members",
    }
)
_MEMBER_KEYS: Final = frozenset(
    {"leg", "publication_schema", "inventory_receipt_sha256", "publication"}
)
_PUBLICATION_KEYS: Final = frozenset(
    {
        "occurrence",
        "producer_instance",
        "publisher_instance",
        "request_raw_ref",
        "receipt_raw_ref",
        "evidence_refs",
        "window_ref",
        "numbered_log_ref",
        "current_row_ref",
        "publication_steps",
        "observed_interval",
        "outcome",
        "cleanup_state",
    }
)
_OCCURRENCE_KEYS: Final = frozenset(
    {
        "key",
        "witness",
        "admitting_process",
        "controller",
        "executing_processes",
        "route_witness",
        "targets",
        "source_epoch",
        "observation_epoch",
        "admission_boundary",
        "state",
    }
)
_LIFECYCLE_KEY_KEYS: Final = frozenset({"key_kind", "selection", "launch_id", "operation_id"})
_ROW_KEY_KEYS: Final = frozenset(
    {
        "key_kind",
        "selection",
        "window_id",
        "binding_ref",
        "writer",
        "row",
        "operation",
        "request_id",
        "sequence",
        "request_raw_ref",
    }
)
_HOST_EFFECT_KEYS: Final = frozenset(
    {"kind", "selection", "target", "operation", "actor", "purpose", "roots", "boundary"}
)
_ROOT_SCOPE_KEYS: Final = frozenset(
    {
        "role",
        "actor",
        "selected_locator",
        "expected_existing_object",
        "new_leaf",
        "required_rights",
    }
)
_RAW_REF_KEYS: Final = frozenset({"root_locator", "relative_path", "byte_length", "sha256"})
_SELECTION_KEYS: Final = frozenset({"selection_reference", "selection_revision"})
_WITNESS_KEYS: Final = frozenset({"witness_reference"})
_PROCESS_KEYS: Final = frozenset({"process_registration"})
_INTERVAL_KEYS: Final = frozenset({"clock_domain", "interval_witness"})
_ROOT_OBJECT_KEYS: Final = frozenset(
    {"filesystem_object", "mount_identity", "namespace_identity", "observation_epoch"}
)
_FUTURE_SUBJECT_KEYS: Final = frozenset({"subject_kind", "selected_scope_reference"})
_EXISTING_SUBJECT_KEYS: Final = frozenset({"subject_kind", "identity"})
_PROCESS_IDENTITY_KEYS: Final = frozenset({"identity_kind", "process_registration"})
_ROOT_OBJECT_IDENTITY_KEYS: Final = _ROOT_OBJECT_KEYS | {"identity_kind"}

_OCCURRENCE_STATES: Final = ("admitted", "started", "completed", "refused", "failed", "uncertain")
_OUTCOMES: Final = ("success", "app-failure", "host-failure", "refused", "uncertain")
_CLEANUP_STATES: Final = ("not-required", "complete", "incomplete", "uncertain")
_ROOT_ROLES: Final = ("publication", "host-parent", "host-evidence")
_LEGS: Final[tuple[str, ...]] = get_args(CohortLeg)

_Item = TypeVar("_Item")


def _object(value: object, keys: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or not _has_exact_keys(value, keys):
        raise _SnapshotShapeError
    return value


def _text(value: object) -> str:
    if not _is_text(value):
        raise _SnapshotShapeError
    assert isinstance(value, str)
    return value


def _choice(value: object, alternatives: tuple[str, ...]) -> str:
    if type(value) is not str or value not in alternatives:
        raise _SnapshotShapeError
    return value


def _integer(value: object, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise _SnapshotShapeError
    return value


def _list(value: object, decode_item: Callable[[object], _Item]) -> tuple[_Item, ...]:
    if type(value) is not list:
        raise _SnapshotShapeError
    return tuple(decode_item(item) for item in value)


def _optional(value: object, decode_item: Callable[[object], _Item]) -> _Item | None:
    return None if value is None else decode_item(value)


def _decode_raw_ref(value: object) -> RawRef:
    fields = _object(value, _RAW_REF_KEYS)
    return RawRef(
        root_locator=_text(fields["root_locator"]),
        relative_path=_text(fields["relative_path"]),
        byte_length=_integer(fields["byte_length"], minimum=0),
        sha256=_text(fields["sha256"]),
    )


def _decode_selection(value: object) -> HostSelectionHandle:
    fields = _object(value, _SELECTION_KEYS)
    return HostSelectionHandle(
        selection_reference=_text(fields["selection_reference"]),
        selection_revision=_text(fields["selection_revision"]),
    )


def _decode_witness(value: object) -> NativeWitnessValue:
    fields = _object(value, _WITNESS_KEYS)
    return NativeWitnessValue(witness_reference=_text(fields["witness_reference"]))


def _decode_process(value: object) -> NativeProcessRefValue:
    fields = _object(value, _PROCESS_KEYS)
    return NativeProcessRefValue(process_registration=_text(fields["process_registration"]))


def _decode_interval(value: object) -> NativeIntervalValue:
    fields = _object(value, _INTERVAL_KEYS)
    return NativeIntervalValue(
        clock_domain=_text(fields["clock_domain"]),
        interval_witness=_decode_witness(fields["interval_witness"]),
    )


def _root_object_from_fields(fields: Mapping[str, Any]) -> NativeRootObjectValue:
    return NativeRootObjectValue(
        filesystem_object=_text(fields["filesystem_object"]),
        mount_identity=_text(fields["mount_identity"]),
        namespace_identity=_text(fields["namespace_identity"]),
        observation_epoch=_text(fields["observation_epoch"]),
    )


def _decode_root_object(value: object) -> NativeRootObjectValue:
    return _root_object_from_fields(_object(value, _ROOT_OBJECT_KEYS))


def _decode_identity(value: object) -> NativeProcessRefValue | NativeRootObjectValue:
    kind = value.get("identity_kind") if type(value) is dict else None
    if kind == "process":
        fields = _object(value, _PROCESS_IDENTITY_KEYS)
        return NativeProcessRefValue(process_registration=_text(fields["process_registration"]))
    if kind == "root_object":
        return _root_object_from_fields(_object(value, _ROOT_OBJECT_IDENTITY_KEYS))
    raise _SnapshotShapeError


def _decode_subject(value: object) -> FutureSubjectRecord | ExistingSubjectRecord:
    kind = value.get("subject_kind") if type(value) is dict else None
    if kind == "future":
        fields = _object(value, _FUTURE_SUBJECT_KEYS)
        return FutureSubjectRecord(
            selected_scope_reference=_text(fields["selected_scope_reference"])
        )
    if kind == "existing":
        fields = _object(value, _EXISTING_SUBJECT_KEYS)
        return ExistingSubjectRecord(identity=_decode_identity(fields["identity"]))
    raise _SnapshotShapeError


def _decode_rights(value: object) -> frozenset[str]:
    rights = _list(value, _text)
    if len(set(rights)) != len(rights):
        raise _SnapshotShapeError
    return frozenset(rights)


def _decode_root_scope(value: object) -> RootScope[Any, Any]:
    fields = _object(value, _ROOT_SCOPE_KEYS)
    return RootScope(
        role=_choice(fields["role"], _ROOT_ROLES),  # type: ignore[arg-type]
        actor=_decode_subject(fields["actor"]),
        selected_locator=_text(fields["selected_locator"]),
        expected_existing_object=_optional(
            fields["expected_existing_object"], _decode_root_object
        ),
        new_leaf=_optional(fields["new_leaf"], _text),
        required_rights=_decode_rights(fields["required_rights"]),
    )


def _decode_host_effect(value: object) -> HostEffect[Any, Any, Any, Any]:
    fields = _object(value, _HOST_EFFECT_KEYS)
    return HostEffect(
        kind=_text(fields["kind"]),  # type: ignore[arg-type]  # HostEffect checks kind
        selection=_decode_selection(fields["selection"]),
        target=_decode_subject(fields["target"]),
        operation=_text(fields["operation"]),
        actor=_decode_subject(fields["actor"]),
        purpose=_text(fields["purpose"]),
        roots=_list(fields["roots"], _decode_root_scope),
        boundary=_text(fields["boundary"]),
    )


def _decode_key(value: object) -> LifecycleKey[Any] | RowKey[Any]:
    kind = value.get("key_kind") if type(value) is dict else None
    if kind == "lifecycle":
        fields = _object(value, _LIFECYCLE_KEY_KEYS)
        return LifecycleKey(
            selection=_decode_selection(fields["selection"]),
            launch_id=_text(fields["launch_id"]),
            operation_id=_text(fields["operation_id"]),
        )
    if kind == "row":
        fields = _object(value, _ROW_KEY_KEYS)
        return RowKey(
            selection=_decode_selection(fields["selection"]),
            window_id=_text(fields["window_id"]),
            binding_ref=_decode_raw_ref(fields["binding_ref"]),
            writer=_text(fields["writer"]),
            row=_text(fields["row"]),
            operation=_text(fields["operation"]),
            request_id=_text(fields["request_id"]),
            sequence=_integer(fields["sequence"], minimum=1),
            request_raw_ref=_decode_raw_ref(fields["request_raw_ref"]),
        )
    raise _SnapshotShapeError


def _decode_source_epoch(value: object) -> N3SourceEpoch:
    return decode_record(value, N3SourceEpoch)


def _decode_observation_epoch(value: object) -> N3ObservationEpoch:
    return decode_record(value, N3ObservationEpoch)


def _decode_occurrence(value: object) -> OccurrenceHandle[Any, Any, Any, Any, Any, Any, Any, Any]:
    fields = _object(value, _OCCURRENCE_KEYS)
    return OccurrenceHandle(
        key=_decode_key(fields["key"]),
        witness=_decode_witness(fields["witness"]),
        admitting_process=_decode_process(fields["admitting_process"]),
        controller=_optional(fields["controller"], _decode_process),
        executing_processes=_list(fields["executing_processes"], _decode_process),
        route_witness=_decode_witness(fields["route_witness"]),
        targets=_list(fields["targets"], _decode_subject),
        source_epoch=_decode_source_epoch(fields["source_epoch"]),
        observation_epoch=_decode_observation_epoch(fields["observation_epoch"]),
        admission_boundary=_decode_host_effect(fields["admission_boundary"]),
        state=_choice(fields["state"], _OCCURRENCE_STATES),  # type: ignore[arg-type]
    )


def _decode_publication(
    value: object,
) -> RawPublication[Any, Any, Any, Any, Any, Any, Any, Any, Any]:
    fields = _object(value, _PUBLICATION_KEYS)
    return RawPublication(
        occurrence=_decode_occurrence(fields["occurrence"]),
        producer_instance=_decode_process(fields["producer_instance"]),
        publisher_instance=_decode_process(fields["publisher_instance"]),
        request_raw_ref=_optional(fields["request_raw_ref"], _decode_raw_ref),
        receipt_raw_ref=_decode_raw_ref(fields["receipt_raw_ref"]),
        evidence_refs=_list(fields["evidence_refs"], _decode_raw_ref),
        window_ref=_optional(fields["window_ref"], _decode_raw_ref),
        numbered_log_ref=_optional(fields["numbered_log_ref"], _decode_raw_ref),
        current_row_ref=_optional(fields["current_row_ref"], _decode_raw_ref),
        publication_steps=_list(fields["publication_steps"], _decode_witness),
        observed_interval=_decode_interval(fields["observed_interval"]),
        outcome=_choice(fields["outcome"], _OUTCOMES),  # type: ignore[arg-type]
        cleanup_state=_choice(fields["cleanup_state"], _CLEANUP_STATES),  # type: ignore[arg-type]
    )


def _decode_member(value: object) -> PublicationCohortMember:
    fields = _object(value, _MEMBER_KEYS)
    return PublicationCohortMember(
        leg=_choice(fields["leg"], _LEGS),  # type: ignore[arg-type]
        publication=_decode_publication(fields["publication"]),
        publication_schema=_text(fields["publication_schema"]),
        inventory_receipt_sha256=_text(fields["inventory_receipt_sha256"]),
    )


def _top_level_shape_is_valid(document: Mapping[str, Any]) -> bool:
    if not _has_exact_keys(document, _SNAPSHOT_KEYS):
        return False
    return (
        all(
            _is_text(document[name])
            for name in (
                "selection_revision",
                "cohort_schema",
                "kit_id",
                "kit_sha256",
                "final_sha256",
            )
        )
        and type(document["complete_publication"]) is bool
        and type(document["members"]) is list
    )


def _decode_members(members: list[Any]) -> tuple[PublicationCohortMember, ...] | None:
    try:
        return tuple(_decode_member(member) for member in members)
    except (ValueError, TypeError):
        # _SnapshotShapeError, record __post_init__ errors and p3_source_closure's
        # TargetRefused (a ValueError with a fixed code) all mean "undecodable".
        return None


# ---------------------------------------------------------------------------
# Encoding (canonical writer of the same format; pure, for tests and docs)
# ---------------------------------------------------------------------------


def _require(value: object, cls: type) -> None:
    if type(value) is not cls:
        raise TypeError(f"snapshot encoding needs {cls.__name__}")


def _encode_raw_ref(ref: object) -> dict[str, Any]:
    _require(ref, RawRef)
    assert isinstance(ref, RawRef)
    return {
        "root_locator": ref.root_locator,
        "relative_path": ref.relative_path,
        "byte_length": ref.byte_length,
        "sha256": ref.sha256,
    }


def _encode_optional_raw_ref(ref: object) -> dict[str, Any] | None:
    return None if ref is None else _encode_raw_ref(ref)


def _encode_selection(selection: object) -> dict[str, Any]:
    _require(selection, HostSelectionHandle)
    assert isinstance(selection, HostSelectionHandle)
    return {
        "selection_reference": selection.selection_reference,
        "selection_revision": selection.selection_revision,
    }


def _encode_witness(witness: object) -> dict[str, Any]:
    _require(witness, NativeWitnessValue)
    assert isinstance(witness, NativeWitnessValue)
    return {"witness_reference": witness.witness_reference}


def _encode_process(process: object) -> dict[str, Any]:
    _require(process, NativeProcessRefValue)
    assert isinstance(process, NativeProcessRefValue)
    return {"process_registration": process.process_registration}


def _encode_interval(interval: object) -> dict[str, Any]:
    _require(interval, NativeIntervalValue)
    assert isinstance(interval, NativeIntervalValue)
    return {
        "clock_domain": interval.clock_domain,
        "interval_witness": _encode_witness(interval.interval_witness),
    }


def _encode_root_object(root: object) -> dict[str, Any]:
    _require(root, NativeRootObjectValue)
    assert isinstance(root, NativeRootObjectValue)
    return {
        "filesystem_object": root.filesystem_object,
        "mount_identity": root.mount_identity,
        "namespace_identity": root.namespace_identity,
        "observation_epoch": root.observation_epoch,
    }


def _encode_subject(subject: object) -> dict[str, Any]:
    if type(subject) is FutureSubjectRecord:
        return {
            "subject_kind": "future",
            "selected_scope_reference": subject.selected_scope_reference,
        }
    _require(subject, ExistingSubjectRecord)
    assert isinstance(subject, ExistingSubjectRecord)
    identity = subject.identity
    if type(identity) is NativeProcessRefValue:
        encoded = {"identity_kind": "process", **_encode_process(identity)}
    else:
        encoded = {"identity_kind": "root_object", **_encode_root_object(identity)}
    return {"subject_kind": "existing", "identity": encoded}


def _encode_root_scope(scope: object) -> dict[str, Any]:
    _require(scope, RootScope)
    assert isinstance(scope, RootScope)
    return {
        "role": scope.role,
        "actor": _encode_subject(scope.actor),
        "selected_locator": scope.selected_locator,
        "expected_existing_object": (
            None
            if scope.expected_existing_object is None
            else _encode_root_object(scope.expected_existing_object)
        ),
        "new_leaf": scope.new_leaf,
        "required_rights": sorted(scope.required_rights),
    }


def _encode_host_effect(effect: object) -> dict[str, Any]:
    _require(effect, HostEffect)
    assert isinstance(effect, HostEffect)
    return {
        "kind": effect.kind,
        "selection": _encode_selection(effect.selection),
        "target": _encode_subject(effect.target),
        "operation": effect.operation,
        "actor": _encode_subject(effect.actor),
        "purpose": effect.purpose,
        "roots": [_encode_root_scope(scope) for scope in effect.roots],
        "boundary": effect.boundary,
    }


def _encode_key(key: object) -> dict[str, Any]:
    if type(key) is LifecycleKey:
        return {
            "key_kind": "lifecycle",
            "selection": _encode_selection(key.selection),
            "launch_id": key.launch_id,
            "operation_id": key.operation_id,
        }
    _require(key, RowKey)
    assert isinstance(key, RowKey)
    return {
        "key_kind": "row",
        "selection": _encode_selection(key.selection),
        "window_id": key.window_id,
        "binding_ref": _encode_raw_ref(key.binding_ref),
        "writer": key.writer,
        "row": key.row,
        "operation": key.operation,
        "request_id": key.request_id,
        "sequence": key.sequence,
        "request_raw_ref": _encode_raw_ref(key.request_raw_ref),
    }


def _encode_epoch(epoch: object, cls: type) -> object:
    _require(epoch, cls)
    return to_wire(epoch)


def _encode_occurrence(occurrence: object) -> dict[str, Any]:
    _require(occurrence, OccurrenceHandle)
    assert isinstance(occurrence, OccurrenceHandle)
    return {
        "key": _encode_key(occurrence.key),
        "witness": _encode_witness(occurrence.witness),
        "admitting_process": _encode_process(occurrence.admitting_process),
        "controller": (
            None if occurrence.controller is None else _encode_process(occurrence.controller)
        ),
        "executing_processes": [_encode_process(p) for p in occurrence.executing_processes],
        "route_witness": _encode_witness(occurrence.route_witness),
        "targets": [_encode_subject(target) for target in occurrence.targets],
        "source_epoch": _encode_epoch(occurrence.source_epoch, N3SourceEpoch),
        "observation_epoch": _encode_epoch(occurrence.observation_epoch, N3ObservationEpoch),
        "admission_boundary": _encode_host_effect(occurrence.admission_boundary),
        "state": occurrence.state,
    }


def _encode_publication(publication: object) -> dict[str, Any]:
    _require(publication, RawPublication)
    assert isinstance(publication, RawPublication)
    return {
        "occurrence": _encode_occurrence(publication.occurrence),
        "producer_instance": _encode_process(publication.producer_instance),
        "publisher_instance": _encode_process(publication.publisher_instance),
        "request_raw_ref": _encode_optional_raw_ref(publication.request_raw_ref),
        "receipt_raw_ref": _encode_raw_ref(publication.receipt_raw_ref),
        "evidence_refs": [_encode_raw_ref(ref) for ref in publication.evidence_refs],
        "window_ref": _encode_optional_raw_ref(publication.window_ref),
        "numbered_log_ref": _encode_optional_raw_ref(publication.numbered_log_ref),
        "current_row_ref": _encode_optional_raw_ref(publication.current_row_ref),
        "publication_steps": [_encode_witness(w) for w in publication.publication_steps],
        "observed_interval": _encode_interval(publication.observed_interval),
        "outcome": publication.outcome,
        "cleanup_state": publication.cleanup_state,
    }


def _encode_member(member: object) -> dict[str, Any]:
    _require(member, PublicationCohortMember)
    assert isinstance(member, PublicationCohortMember)
    return {
        "leg": member.leg,
        "publication_schema": member.publication_schema,
        "inventory_receipt_sha256": member.inventory_receipt_sha256,
        "publication": _encode_publication(member.publication),
    }


def encode_cohort_snapshot(cohort: PublicationCohort, *, selection_revision: str) -> bytes:
    """Canonical snapshot bytes for ``cohort`` under ``selection_revision``.

    Raises ``TypeError``/``ValueError`` for anything the format cannot carry (a
    test-only carrier, a bad revision). Pure: no I/O; the store never writes.
    """
    _require(cohort, PublicationCohort)
    if not _is_text(selection_revision):
        raise ValueError("selection_revision must be a non-empty str")
    document = {
        "schema": SNAPSHOT_SCHEMA,
        "selection_revision": selection_revision,
        "cohort_schema": cohort.cohort_schema,
        "kit_id": cohort.kit_id,
        "kit_sha256": cohort.kit_sha256,
        "final_sha256": cohort.final_sha256,
        "complete_publication": cohort.complete_publication,
        "members": [_encode_member(member) for member in cohort.members],
    }
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


def _strict_json_object(raw: bytes) -> dict[str, Any] | None:
    """Strict UTF-8 JSON object (no duplicate keys, NaN/Infinity, BOM or surrogates)."""
    try:
        return decode_object(raw)
    except PrivateDraftFailure:  # fixed code, no payload
        return None


def _read_bounded(descriptor: int) -> bytes | None:
    """Read at most MAX_SNAPSHOT_BYTES + 1 bytes; ``None`` on read error."""
    chunks: list[bytes] = []
    remaining = MAX_SNAPSHOT_BYTES + 1
    try:
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        return None
    return b"".join(chunks)


class FilePublicationCohortStore:
    """Read-only, content-addressed ``PublicationCohortSource`` over QA's snapshots."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        if not isinstance(root, (str, os.PathLike)):
            raise TypeError("root must be a str or os.PathLike path")
        root_path = os.fspath(root)
        if type(root_path) is not str or not os.path.isabs(root_path):
            raise ValueError("root must be an absolute path")
        try:
            info = os.lstat(root_path)
        except FileNotFoundError:
            raise ValueError("root does not exist") from None
        except OSError:
            raise ValueError("root cannot be inspected") from None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("root must not be a symlink")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("root must be a directory")
        self._root = root_path

    @property
    def root(self) -> str:
        return self._root

    def load_cohort(
        self,
        receiving_reference: ImmutableReference,
        *,
        selection_revision: str,
    ) -> PublicationCohort | None:
        loaded = self.load_cohort_snapshot(
            receiving_reference, selection_revision=selection_revision
        )
        return None if loaded is None else loaded[0]

    def load_cohort_snapshot(
        self,
        receiving_reference: ImmutableReference,
        *,
        selection_revision: str,
    ) -> tuple[PublicationCohort, ImmutableReferenceRecord] | None:
        read = self.read_cohort_snapshot(
            receiving_reference, selection_revision=selection_revision
        )
        if read.cohort is None or read.snapshot_reference is None:
            return None
        return read.cohort, read.snapshot_reference

    def read_cohort_snapshot(
        self,
        receiving_reference: ImmutableReference,
        *,
        selection_revision: str,
    ) -> CohortSnapshotRead:
        """One lookup with its refusal code; never raises for bad input or bytes."""
        digest = getattr(receiving_reference, "digest", None)
        if not _digest_is_well_formed(digest):
            return _refused(CohortSnapshotRefusal.DIGEST_MALFORMED)
        if not _selection_revision_is_well_formed(selection_revision):
            return _refused(CohortSnapshotRefusal.SELECTION_REVISION_MALFORMED)
        if not _reference_is_well_formed(receiving_reference):
            return _refused(CohortSnapshotRefusal.REFERENCE_MALFORMED)
        assert isinstance(digest, str)

        raw_or_code = self._read_snapshot_bytes(f"{digest}.json")
        if isinstance(raw_or_code, CohortSnapshotRefusal):
            return _refused(raw_or_code)
        raw = raw_or_code

        if not _length_matches(raw, receiving_reference.length):
            return _refused(CohortSnapshotRefusal.LENGTH_MISMATCH)
        if not _digest_matches(raw, digest):
            return _refused(CohortSnapshotRefusal.DIGEST_MISMATCH)
        return self._decode_snapshot(
            raw, receiving_reference, digest=digest, selection_revision=selection_revision
        )

    def _read_snapshot_bytes(self, leaf: str) -> bytes | CohortSnapshotRefusal:
        try:
            root_fd = os.open(self._root, _DIRECTORY_OPEN_FLAGS)
        except OSError:
            return CohortSnapshotRefusal.ROOT_UNAVAILABLE
        try:
            try:
                cohorts_fd = os.open(COHORTS_DIRECTORY, _DIRECTORY_OPEN_FLAGS, dir_fd=root_fd)
            except OSError as error:
                return _directory_refusal(error, root_fd)
            try:
                return _read_leaf(leaf, cohorts_fd)
            finally:
                os.close(cohorts_fd)
        finally:
            os.close(root_fd)

    def _decode_snapshot(
        self,
        raw: bytes,
        receiving_reference: ImmutableReference,
        *,
        digest: str,
        selection_revision: str,
    ) -> CohortSnapshotRead:
        document = _strict_json_object(raw)
        if document is None:
            return _refused(CohortSnapshotRefusal.JSON_INVALID)
        if not _schema_matches(document):
            return _refused(CohortSnapshotRefusal.SCHEMA_MISMATCH)
        if not _top_level_shape_is_valid(document):
            return _refused(CohortSnapshotRefusal.SHAPE_INVALID)
        if not _selection_revision_matches(document, selection_revision):
            return _refused(CohortSnapshotRefusal.SELECTION_REVISION_MISMATCH)
        members = _decode_members(document["members"])
        if members is None:
            return _refused(CohortSnapshotRefusal.MEMBER_INVALID)
        cohort = PublicationCohort(
            cohort_schema=document["cohort_schema"],
            kit_id=document["kit_id"],
            kit_sha256=document["kit_sha256"],
            final_sha256=document["final_sha256"],
            complete_publication=document["complete_publication"],
            members=members,
        )
        snapshot_reference = ImmutableReferenceRecord(
            path=receiving_reference.path,
            digest=digest,
            length=len(raw),
            revision=receiving_reference.revision,
        )
        return CohortSnapshotRead(
            cohort=cohort, snapshot_reference=snapshot_reference, refusal=None
        )


def _directory_refusal(error: OSError, root_fd: int) -> CohortSnapshotRefusal:
    if error.errno == errno.ENOENT:
        return CohortSnapshotRefusal.SNAPSHOT_ABSENT
    try:
        info = os.stat(COHORTS_DIRECTORY, dir_fd=root_fd, follow_symlinks=False)
    except OSError:
        return CohortSnapshotRefusal.COHORTS_DIRECTORY_INVALID
    if stat.S_ISLNK(info.st_mode):
        return CohortSnapshotRefusal.COHORTS_DIRECTORY_SYMLINK
    return CohortSnapshotRefusal.COHORTS_DIRECTORY_INVALID


def _read_leaf(leaf: str, cohorts_fd: int) -> bytes | CohortSnapshotRefusal:
    try:
        descriptor = os.open(leaf, _SNAPSHOT_OPEN_FLAGS, dir_fd=cohorts_fd)
    except OSError as error:
        if error.errno == errno.ENOENT:
            return CohortSnapshotRefusal.SNAPSHOT_ABSENT
        if error.errno == errno.ELOOP:
            return CohortSnapshotRefusal.SNAPSHOT_SYMLINK
        return CohortSnapshotRefusal.SNAPSHOT_UNREADABLE
    try:
        info = os.fstat(descriptor)
        if not _is_regular_file(info.st_mode):
            return CohortSnapshotRefusal.SNAPSHOT_NOT_REGULAR
        if not _within_size_limit(info.st_size):
            return CohortSnapshotRefusal.SNAPSHOT_TOO_LARGE
        raw = _read_bounded(descriptor)
        if raw is None:
            return CohortSnapshotRefusal.SNAPSHOT_UNREADABLE
        if not _within_size_limit(len(raw)):
            return CohortSnapshotRefusal.SNAPSHOT_TOO_LARGE
        return raw
    finally:
        os.close(descriptor)


__all__ = [
    "COHORTS_DIRECTORY",
    "MAX_SNAPSHOT_BYTES",
    "SNAPSHOT_SCHEMA",
    "CohortSnapshotRead",
    "CohortSnapshotRefusal",
    "FilePublicationCohortStore",
    "encode_cohort_snapshot",
]
