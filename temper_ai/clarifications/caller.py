"""Explicit supplied-input clarification coordination; no application entry point.

M1 checks/prepares, M3 owns history/CAS, M2/B own intent/admission/delivery, and
#312 checks references only. All ports and the shipped validator are supplied.
No client, engine, poller, source lookup, registration or downstream work lives
here. Imports retain the ordinary dependency/schema loads described by M1.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import Any, Literal, cast

from configs.architecture.bin import context_profile_check as v2
from configs.architecture.bin.context_profile_clarification_caller import CallerRefusal
from configs.architecture.bin.context_profile_clarified_check import (
    check_clarified_profile,
)
from temper_ai.clarifications import preparation_adapter
from temper_ai.clarifications.caller_contracts import (
    CheckedClarification,
    ClarificationAuthority,
    CoordinatorStore,
    PreparedClarification,
    PresentationRequest,
    QuestionTransport,
    RecoveredClarification,
)
from temper_ai.clarifications.contracts import (
    CallerInput,
    ContractRefusal,
    Presentation,
    RefusalCode,
)
from temper_ai.clarifications.store import (
    ClarificationIntegrityError,
    RecordResult,
    StoredStream,
    Supplement,
)
from temper_ai.integrations.telegram.clarifications import SendResult

__all__ = ["ClarificationCoordinator"]


def _require(ok: bool, code: RefusalCode, guard: str) -> None:
    if not ok:
        raise ContractRefusal(code, guard)


def _without_selection(caller: CallerInput) -> CallerInput:
    if type(caller) is not CallerInput:
        raise CallerRefusal("caller.type", "expected a canonical CallerInput")
    return replace(caller, question_ids=())


def _at_record(caller: CallerInput, record: RecordResult | StoredStream) -> CallerInput:
    return replace(caller, question_ids=(), prior_revision=record.revision,
                   prior_record_json=record.record_json, prior_record_sha256=record.record_sha256)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ClarificationCoordinator:
    """Thin synchronous library over explicitly authorized, supplied ports.

    Construction checks missing dependencies only, without invoking them. The
    embedding application must supply the shipped clarified/v1 validator and
    real scoped store/transport implementations; labels are not authority.
    """

    def __init__(self, *, store: CoordinatorStore, transport: QuestionTransport,
                 authority: ClarificationAuthority, clarified_validator: v2.Validator) -> None:
        _require(authority is not None, RefusalCode.MISSING_AUTHORITY, "coordinator.authority")
        _require(store is not None and transport is not None and clarified_validator is not None,
                 RefusalCode.MALFORMED, "coordinator.ports")
        self._store = store
        self._transport = transport
        self._authority = authority
        self._validator = clarified_validator

    def _permit(self, caller: CallerInput, *operations: Literal["read", "write", "send", "acknowledge"]) -> None:
        for operation in operations:
            self._authority.require(operation=operation, stream=caller.stream,
                                    source_authority_ref=cast(str, caller.source_authority_ref),
                                    responder_policy_ref=caller.responder_policy_ref)

    def _load(self, caller: CallerInput) -> StoredStream:
        stored = self._store.load(caller.stream)
        _require(stored is not None, RefusalCode.MISSING_RECORD, "coordinator.record_missing")
        assert stored is not None
        _require(stored.stream == caller.stream and stored.source_authority_ref == caller.source_authority_ref,
                 RefusalCode.CROSS_CONTEXT, "coordinator.scope")
        return stored

    @staticmethod
    def _current(caller: CallerInput, stored: StoredStream) -> None:
        _require(caller.prior_revision == stored.revision, RefusalCode.REVISION_CONFLICT, "coordinator.current")
        _require(caller.prior_record_sha256 == stored.record_sha256,
                 RefusalCode.HASH_MISMATCH, "coordinator.record")

    def _composed(self, caller: CallerInput) -> tuple[dict[str, Any], Supplement]:
        composed = preparation_adapter.compose_supplement(caller)
        saved = deepcopy(self._store.supplement(caller.stream, revision=caller.prior_revision,
                                               original_brief=cast(str, caller.original_text)))
        expected = (composed["stream_id"], composed["revision"], composed["record_sha256"],
                    composed["consumption_id"], composed["original_text"], composed["supplement"],
                    composed["supplement_sha256"], composed["source_mapping"])
        actual = (saved.stream_id, saved.revision, saved.record_sha256, saved.consumption_id,
                  saved.original_brief, saved.supplement, saved.supplement_sha256, saved.source_mapping)
        if actual != expected:
            raise ClarificationIntegrityError(caller.stream.stream_id, "coordinator.supplement",
                                              "stored supplement differs from the checked composition")
        return composed, saved

    def prepare(self, caller: CallerInput) -> PreparedClarification:
        """Complete checker first; merge on M3's latest history, then show its result.

        A concurrent answer can be in the committed result. The refreshed display
        has no ask selection; requested IDs remain in the original caller input.
        """
        preparation_adapter.prepare(caller)
        self._permit(caller, "read", "write")
        committed = self._store.merge_candidate(caller)
        if committed.stream_id != caller.stream.stream_id:
            raise ClarificationIntegrityError(caller.stream.stream_id, "coordinator.merge_stream",
                                              "merge returned a different stream")
        display = preparation_adapter.prepare(_at_record(caller, committed))
        return PreparedClarification(committed, display)

    def present(self, caller: CallerInput, *, presentations: tuple[PresentationRequest, ...],
                resend: bool = False) -> tuple[SendResult, ...]:
        """Save each checked presentation before its explicit transport operation.

        M2/B persist immutable intent and atomic admission before provider I/O;
        this library does not emulate those transactions. No batch atomicity or
        atomic network-plus-history guarantee: later failures can follow sends.
        """
        display = preparation_adapter.prepare(caller)
        self._permit(caller, "read", "write", "send")
        self._current(caller, self._load(caller))
        preparation_adapter.compose_supplement(_without_selection(caller))
        _require(type(presentations) is tuple and all(type(item) is PresentationRequest for item in presentations),
                 RefusalCode.MALFORMED, "coordinator.presentations")
        _require(type(resend) is bool, RefusalCode.MALFORMED, "coordinator.resend")
        rows = {row["question_id"]: row for row in display["questions"]}
        bound = []
        for request in presentations:
            presentation = request.presentation
            _require(type(presentation) is Presentation and type(request.text) is str,
                     RefusalCode.MALFORMED, "coordinator.presentation_shape")
            # CallerInput.presentation enforces explicit selection. M1 already
            # checked that every selected ID is current and unresolved.
            _require(presentation.question_id in caller.question_ids,
                     RefusalCode.UNKNOWN_QUESTION, "coordinator.selection")
            row = rows[presentation.question_id]
            expected = caller.presentation(presentation.question_id, row["metadata_sha256"], presentation.generation)
            _require(presentation == expected, RefusalCode.BINDING_MISMATCH, "coordinator.presentation_binding")
            unknown = {key: deepcopy(row[key]) for key in
                       ("question", "why_it_matters", "decisions_affected", "material", "field") if key in row}
            bound.append((request, unknown))
        results = []
        for request, unknown in bound:
            # Recheck at each effect boundary; M2/B still own the final eligibility
            # fence, including movement after this read and after admission (K5).
            self._current(caller, self._load(caller))
            self._store.save_presentation(request.presentation)
            results.append(self._transport.present(request.presentation, unknown, request.text, resend=resend))
        return tuple(results)

    def recover(self, caller: CallerInput) -> RecoveredClarification:
        """Read checked current history; never write, send or acknowledge it.

        A supplied historical snapshot is checked, not treated as replacement
        state. Revision zero is a read request without supplied history, not an
        instruction to manufacture or erase a record.
        """
        context = _without_selection(caller)
        preparation_adapter.prepare(context)
        self._permit(context, "read")
        stored = self._load(context)
        if context.prior_revision:
            previous = self._store.supplement(context.stream, revision=context.prior_revision,
                                              original_brief=cast(str, context.original_text))
            _require(context.prior_record_sha256 == previous.record_sha256,
                     RefusalCode.HASH_MISMATCH, "coordinator.recovery_record")
        current = _at_record(context, stored)
        _composed, supplement = self._composed(current)
        return RecoveredClarification(stored, preparation_adapter.prepare(current), supplement)

    def check_candidate(self, caller: CallerInput, *, profile: object, candidate_ref: str) -> CheckedClarification:
        """Check a separately supplied candidate against the exact current snapshot.

        references_ok is not semantic acceptance. Never refresh candidate source
        references; movement during this operation refuses instead of rebinding.
        """
        context = _without_selection(caller)
        preparation_adapter.prepare(context)
        # Reuse M0's opaque reference validation, without opening the reference.
        replace(context, candidate_ref=candidate_ref)
        self._permit(context, "read")
        self._current(context, self._load(context))
        composed, _saved = self._composed(context)
        candidate = deepcopy(profile)
        report = check_clarified_profile(candidate, cast(str, context.original_text),
                                         cast(dict, context.prior_record()), self._validator)
        try:
            candidate_json = _canonical(candidate)
            digest = _sha(candidate_json)
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            # The real checker ran above. Non-JSON input cannot be represented as
            # a canonical candidate snapshot; never invent a replacement value.
            raise CallerRefusal("candidate.json", "candidate has no canonical JSON snapshot",
                                tuple(report["errors"])) from error
        self._current(context, self._load(context))
        return CheckedClarification(
            stream=context.stream, revision=context.prior_revision, record_sha256=composed["record_sha256"],
            original_sha256=context.original_sha256, candidate_ref=candidate_ref, candidate_json=candidate_json,
            candidate_sha256=digest, original_text=cast(str, context.original_text),
            supplement=composed["supplement"], source_mapping=composed["source_mapping"],
            consumption_id=composed["consumption_id"], report=report,
        )

    def acknowledge_consumption(self, caller: CallerInput, *, checked: CheckedClarification) -> bool:
        """Record a caller acknowledgement only; execute and attest to nothing.

        Exact saved source acknowledgements replay before current-candidate
        validation. New acknowledgements require real reference rechecking and
        the injected store's current-only CAS, never historical mark_consumed.
        """
        context = _without_selection(caller)
        _require(type(checked) is CheckedClarification, RefusalCode.MALFORMED, "coordinator.checked_type")
        self._permit(context, "read", "acknowledge")
        _require(checked.stream == context.stream and checked.original_sha256 == context.original_sha256
                 and checked.original_text == context.original_text,
                 RefusalCode.CROSS_CONTEXT, "coordinator.checked_context")
        _require(type(checked.revision) is int and checked.revision == context.prior_revision
                 and checked.record_sha256 == context.prior_record_sha256,
                 RefusalCode.BINDING_MISMATCH, "coordinator.checked_record")
        stored = self._load(context)
        saved = self._store.supplement(context.stream, revision=checked.revision,
                                       original_brief=cast(str, context.original_text))
        _require((checked.stream.stream_id, checked.revision, checked.record_sha256, checked.consumption_id,
                  checked.original_text, checked.supplement, checked.source_mapping)
                 == (saved.stream_id, saved.revision, saved.record_sha256, saved.consumption_id,
                     saved.original_brief, saved.supplement, saved.source_mapping),
                 RefusalCode.BINDING_MISMATCH, "coordinator.checked_source")
        if saved.consumed:
            return False
        # The replay above is deliberately not renewed candidate acceptance.
        # Every new acknowledgement goes through the full real M1/#312 checks.
        preparation_adapter.prepare(context)
        self._current(context, stored)
        self._composed(context)
        replace(context, candidate_ref=checked.candidate_ref)
        try:
            candidate = json.loads(checked.candidate_json)
            canonical = _canonical(candidate)
            digest = _sha(canonical)
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise ContractRefusal(RefusalCode.MALFORMED, "coordinator.checked_json") from error
        _require(canonical == checked.candidate_json and digest == checked.candidate_sha256,
                 RefusalCode.HASH_MISMATCH, "coordinator.checked_candidate")
        report = check_clarified_profile(candidate, cast(str, context.original_text),
                                         cast(dict, context.prior_record()), self._validator)
        _require(report == checked.report and report["references_ok"] is True,
                 RefusalCode.BINDING_MISMATCH, "coordinator.checked_report")
        return self._store.mark_current_consumed(context.stream, revision=checked.revision,
                                                record_sha256=checked.record_sha256,
                                                consumption_id=checked.consumption_id,
                                                original_brief=cast(str, context.original_text))
