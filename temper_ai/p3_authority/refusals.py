"""Closed native refusal data, separate from candidate and R1–R5 refusals.

These records describe a boundary's result, not executable admission policy.
They never infer history from a refusal code or automatically retry anything.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

DECISION_SCHEMA: Literal["p3-native-decision/1"] = "p3-native-decision/1"


class RefusalCode(StrEnum):
    AUTHORITY_UNBOUND = "authority_unbound"
    ISSUER_UNVERIFIED = "issuer_unverified"
    SUBJECT_MISMATCH = "subject_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    CONDITIONS_UNMET = "conditions_unmet"
    AUTHORITY_EXPIRED = "authority_expired"
    AUTHORITY_REVOKED = "authority_revoked"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"
    SELECTION_MISSING = "selection_missing"
    SELECTION_AMBIGUOUS = "selection_ambiguous"
    SELECTION_FOREIGN = "selection_foreign"
    SELECTION_CHANGED = "selection_changed"
    ROUTE_UNSUPPORTED = "route_unsupported"
    DISPATCH_CHANGED = "dispatch_changed"
    PEER_UNVERIFIED = "peer_unverified"
    RUNTIME_CHANGED = "runtime_changed"
    ROOT_MISMATCH = "root_mismatch"
    OBSERVATION_NOT_AUTHORIZED = "observation_not_authorized"
    RIGHTS_MISSING = "rights_missing"
    SOURCE_CHANGED = "source_changed"
    CLOSURE_VERSION = "closure_version"
    CLOSURE_INCOMPLETE = "closure_incomplete"
    CLOSURE_MISMATCH = "closure_mismatch"
    OBSERVATION_GAP = "observation_gap"
    QA_RECEIVING_MISSING = "qa_receiving_missing"
    COMPATIBILITY_UNQUALIFIED = "compatibility_unqualified"
    PRIOR_MISSING = "prior_missing"
    PRIOR_FOREIGN = "prior_foreign"
    PRIOR_UNVERIFIED = "prior_unverified"
    WINDOW_INELIGIBLE = "window_ineligible"
    RESULT_UNVERIFIED = "result_unverified"
    ALREADY_COUNTED = "already_counted"
    WRITES_DISABLED = "writes_disabled"


class Phase(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class RetryKind(StrEnum):
    SAME_BOUNDARY_AFTER_REPAIR = "same_boundary_after_repair"
    NEW_BINDING_REQUIRED = "new_binding_required"
    NOT_APPLICABLE = "not_applicable"


class AdmissionState(StrEnum):
    NOT_ADMITTED = "not_admitted"
    ALREADY_ADMITTED = "already_admitted"


class EffectState(StrEnum):
    NONE = "none"
    ADMITTED_ONLY = "admitted_only"
    PARTIAL = "partial"
    COMPLETE = "complete"
    UNCERTAIN = "uncertain"


class SequenceUse(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    UNUSED = "unused"
    USED = "used"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, kw_only=True)
class Refusal:
    """Diagnostic data only. Caller supplies observed history explicitly.

    ``not_admitted`` describes the refused operation, not earlier lifecycle
    effects. ``unknown`` is never silently rewritten to ``unused``. There is
    intentionally no default phase/history and no inference from the code.
    This is not a wire decoder; transport validation belongs to the service.
    """

    code: RefusalCode
    phase: Phase
    retry_kind: RetryKind
    admission_state: AdmissionState
    effect_state: EffectState
    sequence_use: SequenceUse
    schema: Literal["p3-native-decision/1"] = field(default=DECISION_SCHEMA, init=False)
    counted: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        # Exact enums only: no foreign code family or fuzzy string matching.
        fields = (
            (self.code, RefusalCode),
            (self.phase, Phase),
            (self.retry_kind, RetryKind),
            (self.admission_state, AdmissionState),
            (self.effect_state, EffectState),
            (self.sequence_use, SequenceUse),
        )
        for value, expected in fields:
            if type(value) is not expected:
                raise ValueError("p3_contract_field_type") from None
