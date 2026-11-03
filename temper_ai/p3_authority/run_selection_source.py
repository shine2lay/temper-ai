"""P3 T5-O2: each run's job selection, recorded at admission and read back by execution_uuid.

The selection is made at admission (``P3CandidateBindings.authority_for_submit``)
and stored once, in the same transaction and the same run-row insert as the
AdmissionRecord, under ``ADMISSION_SELECTION_KEY`` in
``WorkflowRun.spawner_metadata`` (see ``DbAdmissionTransport.install``). Only the
selection-specific fields are stored; what the AdmissionRecord already holds
(execution_uuid, descriptor and source digests, caller label, receipt id,
workflow) is referenced through the row and record checks, never copied.

``RunSelectionSource`` is the one read-only source of a run's
``RunSelectionBinding``. A missing or malformed stored selection is a refusal,
never a default. Nothing here is installed by default; no production caller
constructs it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from sqlmodel import col, select

from temper_ai.config.admission_contract import (
    AdmissionRecord,
    AdmissionRefused,
    DescriptorAuthority,
    DispatchIdentity,
    canonical_bytes,
    decode_canonical,
)
from temper_ai.config.admission_contract import RefusalCode as AdmissionRefusalCode
from temper_ai.database import get_session
from temper_ai.p3_authority.contract import (
    AuthorityRef,
    CalibrationSelection,
    CompatibilityProfile,
    ConditionRef,
    ImmutableReference,
    Phase,
    PreDispatchJob,
    ProjectSelection,
    Refusal,
    RefusalCode,
    RetryKind,
    SelectedJob,
    SelectedOperation,
    Selection,
)
from temper_ai.p3_authority.registry import ImmutableReferenceRecord, make_refusal
from temper_ai.p3_authority.selection_snapshot import RunSelectionBinding
from temper_ai.runner.admission import ADMISSION_SELECTION_KEY, DbAdmissionTransport
from temper_ai.runner.models import WorkflowRun

logger = logging.getLogger(__name__)

STORED_SELECTION_FIELDS: frozenset[str] = frozenset({
    "selection",
    "selection_revision",
    "selector_issuer",
    "job_revision",
    "reviewed_closure_ref",
    "compatibility_profile",
    "authorized_operations",
    "conditions",
    "authority_refs",
    "expected_dispatch",
})
_ACTIVE_RUN_STATUSES: tuple[str, ...] = ("queued", "running")


class _MalformedSelection(Exception):
    """Internal: the stored value is not exactly the recorded format."""


# --- encoding (the admission writer's half) ---------------------------------

def _encode_authority_ref(ref: AuthorityRef) -> dict[str, Any]:
    return {
        "issuer_id": ref.issuer_id,
        "record_id": ref.record_id,
        "authority_revision": ref.authority_revision,
    }


def _encode_reference(ref: ImmutableReference) -> dict[str, Any]:
    return {"path": ref.path, "digest": ref.digest, "length": ref.length, "revision": ref.revision}


def _encode_selection(selection: Selection) -> dict[str, Any]:
    if type(selection) is ProjectSelection:
        return {
            "kind": "project",
            "project_id": selection.project_id,
            "run_id": selection.run_id,
            "kit_id": selection.kit_id,
            "kit_sha256": selection.kit_sha256,
            "build_sums_sha256": selection.build_sums_sha256,
            "publication_ref": _encode_reference(selection.publication_ref),
            "publication_revision": selection.publication_revision,
            "build_ref": _encode_reference(selection.build_ref),
        }
    if type(selection) is CalibrationSelection:
        return {
            "kind": "calibration",
            "manifest_ref": _encode_reference(selection.manifest_ref),
            "entry_id": selection.entry_id,
            "calibration_run": selection.calibration_run,
            "round": selection.round,
            "copy_identity": selection.copy_identity,
            "expected_draft_kit": _encode_reference(selection.expected_draft_kit),
            "build_sums_sha256": selection.build_sums_sha256,
            "publication_ref": _encode_reference(selection.publication_ref),
            "publication_revision": selection.publication_revision,
            "build_ref": _encode_reference(selection.build_ref),
            "selected_runtime_profile": selection.selected_runtime_profile,
        }
    raise AdmissionRefused(AdmissionRefusalCode.LOOKUP)


def _encode_profile(profile: CompatibilityProfile) -> dict[str, Any]:
    return {
        "decision": profile.decision,
        "reviewed_graph": profile.reviewed_graph,
        "loaded_envelope": profile.loaded_envelope,
        "comparator": profile.comparator,
        "observation": profile.observation,
        "inspect": profile.inspect,
        "caller": profile.caller,
        "corpus": profile.corpus,
        "receiving": profile.receiving,
    }


def _encode_dispatch(dispatch: DispatchIdentity | None) -> dict[str, Any] | None:
    if dispatch is None:
        return None
    return {
        "execution_uuid": dispatch.execution_uuid,
        "dispatch_nonce": dispatch.dispatch_nonce,
        "running_attempt": dispatch.running_attempt,
    }


def _encode_fields(
    *,
    selection: Selection,
    selection_revision: str,
    selector_issuer: AuthorityRef,
    job_revision: str,
    reviewed_closure_ref: ImmutableReference,
    compatibility_profile: CompatibilityProfile,
    authorized_operations: frozenset[SelectedOperation],
    conditions: tuple[ConditionRef, ...],
    authority_refs: tuple[AuthorityRef, ...],
    expected_dispatch: DispatchIdentity | None,
) -> dict[str, Any]:
    return {
        "selection": _encode_selection(selection),
        "selection_revision": selection_revision,
        "selector_issuer": _encode_authority_ref(selector_issuer),
        "job_revision": job_revision,
        "reviewed_closure_ref": _encode_reference(reviewed_closure_ref),
        "compatibility_profile": _encode_profile(compatibility_profile),
        "authorized_operations": [
            {"domain": op.domain, "operation": op.operation, "revision": op.revision}
            for op in sorted(
                authorized_operations,
                key=lambda item: (item.domain, item.operation, item.revision),
            )
        ],
        "conditions": [
            {
                "authority": _encode_authority_ref(condition.authority),
                "condition_id": condition.condition_id,
                "revision": condition.revision,
            }
            for condition in conditions
        ],
        "authority_refs": [_encode_authority_ref(ref) for ref in authority_refs],
        "expected_dispatch": _encode_dispatch(expected_dispatch),
    }


def encode_run_selection(job: SelectedJob) -> dict[str, Any]:
    """The stored selection for an admission-time ``SelectedJob`` (no dispatch yet).

    Fails loud (``AdmissionRefused``) on anything that would not decode back to
    the same fields, so a bad selection cannot be admitted.
    """
    if type(job) is not SelectedJob:
        raise AdmissionRefused(AdmissionRefusalCode.LOOKUP)
    encoded = _encode_fields(
        selection=job.selection,
        selection_revision=job.selection_revision,
        selector_issuer=job.selector_issuer,
        job_revision=job.pre_dispatch_or_running_job.job_revision,
        reviewed_closure_ref=job.reviewed_closure_ref,
        compatibility_profile=job.compatibility_profile,
        authorized_operations=job.authorized_operations,
        conditions=tuple(job.conditions),
        authority_refs=tuple(job.authority_refs),
        expected_dispatch=None,
    )
    if decode_run_selection(encoded) is None:
        raise AdmissionRefused(AdmissionRefusalCode.LOOKUP)
    return encoded


def encode_admitted_selection(
    job: SelectedJob | None,
    *,
    authority: DescriptorAuthority,
    record: AdmissionRecord,
) -> dict[str, Any]:
    """The stored selection for ``record``, only when ``job`` is that admission's own selection.

    Refuses (``AdmissionRefused`` LOOKUP) unless the job is a pre-dispatch job
    for exactly this record's execution_uuid and workflow, with the record's
    descriptor digest and the authority's pins.
    """
    if type(job) is not SelectedJob or type(record) is not AdmissionRecord:
        raise AdmissionRefused(AdmissionRefusalCode.LOOKUP)
    target = job.pre_dispatch_or_running_job
    immutable = record.value()["immutable"]
    descriptor = decode_canonical(immutable["descriptor_json"].encode("utf-8"))
    if (
        type(target) is not PreDispatchJob
        or target.execution_uuid != descriptor["execution_uuid"]
        or target.designated_workflow != descriptor["workflow_name"]
        or target.descriptor_digest != immutable["descriptor_sha256"]
        or job.approved_descriptor_digest != immutable["descriptor_sha256"]
        or job.approved_descriptor_digest != authority.expected_descriptor_sha256
        or job.expected_source_digest != authority.expected_source_sha256
    ):
        raise AdmissionRefused(AdmissionRefusalCode.LOOKUP)
    return encode_run_selection(job)


# --- decoding (the reader's half) -------------------------------------------

def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise _MalformedSelection
    return value


def _exact_object(value: object, keys: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        raise _MalformedSelection
    return value


_AUTHORITY_REF_KEYS = frozenset({"issuer_id", "record_id", "authority_revision"})
_REFERENCE_KEYS = frozenset({"path", "digest", "length", "revision"})
_PROJECT_KEYS = frozenset({
    "kind", "project_id", "run_id", "kit_id", "kit_sha256", "build_sums_sha256",
    "publication_ref", "publication_revision", "build_ref",
})
_CALIBRATION_KEYS = frozenset({
    "kind", "manifest_ref", "entry_id", "calibration_run", "round", "copy_identity",
    "expected_draft_kit", "build_sums_sha256", "publication_ref", "publication_revision",
    "build_ref", "selected_runtime_profile",
})
_PROFILE_KEYS = frozenset({
    "decision", "reviewed_graph", "loaded_envelope", "comparator", "observation",
    "inspect", "caller", "corpus", "receiving",
})
_OPERATION_KEYS = frozenset({"domain", "operation", "revision"})
_CONDITION_KEYS = frozenset({"authority", "condition_id", "revision"})
_DISPATCH_KEYS = frozenset({"execution_uuid", "dispatch_nonce", "running_attempt"})


def _decode_authority_ref(value: object) -> AuthorityRef:
    v = _exact_object(value, _AUTHORITY_REF_KEYS)
    return AuthorityRef(
        issuer_id=_text(v["issuer_id"]),
        record_id=_text(v["record_id"]),
        authority_revision=_text(v["authority_revision"]),
    )


def _decode_reference(value: object) -> ImmutableReferenceRecord:
    v = _exact_object(value, _REFERENCE_KEYS)
    length = v["length"]
    if type(length) is not int:  # bool is not a length; > 0 is the record's own check
        raise _MalformedSelection
    return ImmutableReferenceRecord(
        path=_text(v["path"]),
        digest=_text(v["digest"]),
        length=length,
        revision=_text(v["revision"]),
    )


def _decode_selection(value: object) -> Selection:
    if type(value) is not dict:
        raise _MalformedSelection
    kind = value.get("kind")
    if kind == "project":
        v = _exact_object(value, _PROJECT_KEYS)
        return ProjectSelection(
            project_id=_text(v["project_id"]),
            run_id=_text(v["run_id"]),
            kit_id=_text(v["kit_id"]),
            kit_sha256=_text(v["kit_sha256"]),
            build_sums_sha256=_text(v["build_sums_sha256"]),
            publication_ref=_decode_reference(v["publication_ref"]),
            publication_revision=_text(v["publication_revision"]),
            build_ref=_decode_reference(v["build_ref"]),
        )
    if kind == "calibration":
        v = _exact_object(value, _CALIBRATION_KEYS)
        return CalibrationSelection(
            manifest_ref=_decode_reference(v["manifest_ref"]),
            entry_id=_text(v["entry_id"]),
            calibration_run=_text(v["calibration_run"]),
            round=_text(v["round"]),
            copy_identity=_text(v["copy_identity"]),
            expected_draft_kit=_decode_reference(v["expected_draft_kit"]),
            build_sums_sha256=_text(v["build_sums_sha256"]),
            publication_ref=_decode_reference(v["publication_ref"]),
            publication_revision=_text(v["publication_revision"]),
            build_ref=_decode_reference(v["build_ref"]),
            selected_runtime_profile=_text(v["selected_runtime_profile"]),
        )
    raise _MalformedSelection


def _decode_profile(value: object) -> CompatibilityProfile:
    v = _exact_object(value, _PROFILE_KEYS)
    if v["inspect"] not in ("/1", "/2") or v["corpus"] != "ops-host-compat-corpus/1":
        raise _MalformedSelection
    return CompatibilityProfile(
        decision=_text(v["decision"]),
        reviewed_graph=_text(v["reviewed_graph"]),
        loaded_envelope=_text(v["loaded_envelope"]),
        comparator=_text(v["comparator"]),
        observation=_text(v["observation"]),
        inspect=v["inspect"],
        caller=_text(v["caller"]),
        corpus=v["corpus"],
        receiving=_text(v["receiving"]),
    )


def _decode_operation(value: object) -> SelectedOperation:
    v = _exact_object(value, _OPERATION_KEYS)
    return SelectedOperation(
        domain=_text(v["domain"]),
        operation=_text(v["operation"]),
        revision=_text(v["revision"]),
    )


def _decode_condition(value: object) -> ConditionRef:
    v = _exact_object(value, _CONDITION_KEYS)
    return ConditionRef(
        authority=_decode_authority_ref(v["authority"]),
        condition_id=_text(v["condition_id"]),
        revision=_text(v["revision"]),
    )


def _decode_dispatch(value: object) -> DispatchIdentity | None:
    if value is None:
        return None
    v = _exact_object(value, _DISPATCH_KEYS)
    # DispatchIdentity's own checks refuse a non-UUID id or nonce and an attempt
    # that is not an int >= 1 (bool included).
    return DispatchIdentity(
        execution_uuid=v["execution_uuid"],
        dispatch_nonce=v["dispatch_nonce"],
        running_attempt=v["running_attempt"],
    )


def decode_run_selection(value: object) -> dict[str, Any] | None:
    """The stored selection's typed fields, or None when it is not exactly the format.

    Exact key sets, exact types, non-empty strings, and canonical form: the
    decoded fields must encode back to the same canonical bytes (so lists given
    as other types, unsorted or duplicate operations, or any value that does not
    round-trip, are refused).
    """
    try:
        v = _exact_object(value, STORED_SELECTION_FIELDS)
        fields: dict[str, Any] = {
            "selection": _decode_selection(v["selection"]),
            "selection_revision": _text(v["selection_revision"]),
            "selector_issuer": _decode_authority_ref(v["selector_issuer"]),
            "job_revision": _text(v["job_revision"]),
            "reviewed_closure_ref": _decode_reference(v["reviewed_closure_ref"]),
            "compatibility_profile": _decode_profile(v["compatibility_profile"]),
            "authorized_operations": frozenset(
                _decode_operation(op) for op in v["authorized_operations"]
            ),
            "conditions": tuple(_decode_condition(c) for c in v["conditions"]),
            "authority_refs": tuple(_decode_authority_ref(r) for r in v["authority_refs"]),
            "expected_dispatch": _decode_dispatch(v["expected_dispatch"]),
        }
        if canonical_bytes(_encode_fields(**fields)) != canonical_bytes(v):
            raise _MalformedSelection
    except (_MalformedSelection, AdmissionRefused, ValueError, TypeError):
        return None
    return fields


# --- the read-only source ---------------------------------------------------

class RunSelectionSource:
    """Read-only: a run's ``RunSelectionBinding`` from its admitted row, or a refusal.

    Built over ``DbAdmissionTransport``: the row's AdmissionRecord must pass the
    transport's row/record checks under the transport's pinned authority before
    its stored selection is trusted; when ``authority_for_run`` is given, the
    run's authority must also equal that pin. Never writes, flushes or commits.
    """

    def __init__(
        self,
        transport: DbAdmissionTransport | None,
        *,
        authority_for_run: Callable[[str], DescriptorAuthority] | None = None,
    ) -> None:
        self._transport = transport
        self._authority_for_run = authority_for_run

    def _read_row(self, execution_uuid: str) -> WorkflowRun | None:
        with get_session() as session:
            row = session.scalars(
                select(WorkflowRun).where(WorkflowRun.execution_id == execution_uuid)
            ).first()
            if row is not None:
                session.expunge(row)
            return row

    def _run_authority(self, execution_uuid: str) -> DescriptorAuthority | None:
        assert self._transport is not None
        pinned = self._transport.authority
        if self._authority_for_run is None:
            return pinned
        try:
            authority = self._authority_for_run(execution_uuid)
        except AdmissionRefused:
            return None
        return pinned if authority == pinned else None

    def binding_for(
        self,
        execution_uuid: str,
        *,
        phase: Phase = Phase.B,
    ) -> RunSelectionBinding | Refusal:
        """The run's stored selection as a ``RunSelectionBinding``, or a ``Refusal``."""
        if self._transport is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        missing = make_refusal(
            RefusalCode.SELECTION_MISSING,
            phase=phase,
            retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
        )
        if type(execution_uuid) is not str or not execution_uuid:
            return missing
        row = self._read_row(execution_uuid)
        if (
            row is None
            or not isinstance(row.spawner_metadata, Mapping)
            or ADMISSION_SELECTION_KEY not in row.spawner_metadata
        ):
            return missing
        authority = self._run_authority(execution_uuid)
        if authority is None:
            return missing
        try:
            self._transport._row_record(row)
        except AdmissionRefused:
            return missing
        fields = decode_run_selection(row.spawner_metadata[ADMISSION_SELECTION_KEY])
        dispatch = None if fields is None else fields["expected_dispatch"]
        if fields is None or (dispatch is not None and dispatch.execution_uuid != row.execution_id):
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        return RunSelectionBinding(execution_uuid=row.execution_id, authority=authority, **fields)

    def accepted_bindings(self) -> tuple[RunSelectionBinding, ...]:
        """Every queued or running run's accepted binding, for the providers' ``bindings``.

        Refused runs are left out (the provider's join then refuses them
        SELECTION_MISSING) and each run whose stored selection is refused is
        logged with its execution id; runs with no stored selection are skipped.
        """
        with get_session() as session:
            ids = list(session.scalars(
                select(WorkflowRun.execution_id).where(
                    col(WorkflowRun.status).in_(_ACTIVE_RUN_STATUSES)
                )
            ))
        accepted: list[RunSelectionBinding] = []
        for execution_uuid in sorted(ids):
            result = self.binding_for(execution_uuid)
            if isinstance(result, RunSelectionBinding):
                accepted.append(result)
            elif not self._is_unselected_run(execution_uuid):
                logger.warning(
                    "Run selection refused for %s: %s", execution_uuid, result.code.value,
                )
        return tuple(accepted)

    def _is_unselected_run(self, execution_uuid: str) -> bool:
        row = self._read_row(execution_uuid)
        meta = None if row is None else row.spawner_metadata
        return not isinstance(meta, Mapping) or ADMISSION_SELECTION_KEY not in meta


__all__ = [
    "STORED_SELECTION_FIELDS",
    "RunSelectionSource",
    "decode_run_selection",
    "encode_admitted_selection",
    "encode_run_selection",
]
