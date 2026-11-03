"""Cryptographic Ed25519 issuer, revocation, condition, and peer verification for P3 authority.

Implements N1 (pinned issuer signature verification over canonical CAJ-1 bytes,
signed revocation-status verification with freshness window and high-water
rollback/equivocation detection, closed ConditionRef evaluation, strict ASCII
decimal integer instant comparisons, and non-empty process/peer identity
matching).

Remains inert by default: ``PRODUCTION_ANCHOR_TABLE`` has no entries until
owner consent C2 is granted, and ``compose_p3_authority()`` keeps
``writes_enabled=False`` with no default verifiers wired.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, TypeGuard

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from temper_ai.config.admission_contract import (
    SUPPORTED_MODE,
    AdmissionRefused,
    DispatchIdentity,
    canonical_bytes,
    decode_canonical,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    AuthenticatedPeer,
    AuthorityRef,
    Boundary,
    CompatibilityProfile,
    ConditionRef,
    EffectSet,
    EffectState,
    ImmutableReference,
    JobKey,
    Phase,
    PreDispatchJob,
    ProjectSelection,
    Refusal,
    RefusalCode,
    Result,
    RetryKind,
    SelectedJob,
    SelectedOperation,
    SelectedSubject,
    SequenceUse,
    TrustedInstant,
    VerifiedAuthority,
)
from temper_ai.p3_authority.references import (
    NativeProcessRef,
    NativeSubject,
    NativeWitness,
)

ISSUER_SIGNATURE_LABEL: Final[bytes] = b"temper-p3-issuer/v1"
AUTHORITY_RECORD_KIND: Final[str] = "authority-record"
REVOCATION_STATUS_KIND: Final[str] = "revocation-status"
ANCHOR_PURPOSES: Final[frozenset[str]] = frozenset(
    {AUTHORITY_RECORD_KIND, REVOCATION_STATUS_KIND}
)

ISSUER_AUTHORITY_SCHEMA: Final[str] = "p3-issuer-authority/1"
ISSUER_REVOCATION_SCHEMA: Final[str] = "p3-issuer-revocation/1"
ISSUER_VERIFICATION_PROFILE: Final[str] = "p3-issuer-ed25519/1"

# Clock domain of the production table while no production clock is chosen
# (N1-SPEC r2 6.8, PLAN PRE-N2-CLOCK). A table that holds entries under it refuses
# at construction, so pinning a live anchor has to name a clock that never repeats.
PRODUCTION_CLOCK_DOMAIN_UNSET: Final[str] = "unset:production-clock-not-chosen"

# Public-key rules of N1-SPEC r2 2.3: the field prime and the five y values of the
# eight edwards25519 points of order 1, 2, 4 and 8 (spec 8.3; 32-byte little-endian
# hex, sign bit 0). Matching on y covers both sign bits, because P and -P have the
# same order.
ED25519_FIELD_PRIME: Final[int] = 2**255 - 19
ED25519_SMALL_ORDER_Y: Final[frozenset[int]] = frozenset(
    int.from_bytes(bytes.fromhex(value), "little")
    for value in (
        "0000000000000000000000000000000000000000000000000000000000000000",
        "0100000000000000000000000000000000000000000000000000000000000000",
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    )
)

CONDITION_TABLE: Final[dict[str, str]] = {
    "mode:external-db-fresh": "1",
}
CONDITION_PREDICATES: Final[dict[str, Callable[[object], bool]]] = {
    "mode:external-db-fresh": lambda job: getattr(job, "route", None) == SUPPORTED_MODE,
}

# Verify-only module: it holds no private key and has no signing function.
# Signing and the RFC 8032 TEST 1 vector live in the tests only (N1-SPEC 8.1, C2).

_DECIMAL_RE: Final[re.Pattern[str]] = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_HEX64_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_HEX128_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{128}\Z")

_ROOT_FIELDS: Final[tuple[str, ...]] = (
    "filesystem_object",
    "mount_identity",
    "namespace_identity",
    "observation_epoch",
)
_AUTHORITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "verification_profile",
        "issuer_id",
        "key_id",
        "record_id",
        "authority_revision",
        "clock_domain",
        "not_before",
        "expires_at",
        "subject",
        "actors",
        "operations",
        "roots",
        "conditions",
    }
)
_STATUS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "verification_profile",
        "issuer_id",
        "key_id",
        "clock_domain",
        "revocation_revision",
        "issued_at",
        "next_update",
        "revoked",
    }
)
_ENVELOPE_KEYS: Final[frozenset[str]] = frozenset({"record", "signature"})


def is_text(value: object) -> TypeGuard[str]:
    """Return True iff ``value`` is a non-empty ``str``."""
    return type(value) is str and value != ""


def is_decimal(value: object) -> TypeGuard[str]:
    """Return True iff ``value`` is a canonical non-negative ASCII decimal integer string that ``int()`` converts."""
    if type(value) is not str or _DECIMAL_RE.fullmatch(value) is None:
        return False
    try:
        int(value)
    except ValueError:
        return False
    return True


def parse_strict_instant_int(reading: object) -> int | None:
    """Parse a strict non-negative ASCII decimal integer string without sign or leading zeros."""
    if not is_decimal(reading):
        return None
    return int(reading)


def domain_prefix(kind: str) -> bytes:
    """Return ``b'temper-p3-issuer/v1\\x00<kind>\\x00'`` for an admitted signature kind."""
    if kind not in ANCHOR_PURPOSES:
        raise ValueError(f"unsupported signature kind: {kind!r}")
    return ISSUER_SIGNATURE_LABEL + b"\x00" + kind.encode("ascii") + b"\x00"


def signed_domain_bytes(kind: str, record: Mapping[str, object] | bytes) -> bytes:
    """Build domain-prefixed signing input from a canonical record dict or canonical bytes."""
    if type(record) is bytes:
        decoded = decode_canonical(record)
        if type(decoded) is not dict:
            raise ValueError("canonical record bytes must decode to a JSON object")
        raw = record
    elif isinstance(record, Mapping):
        raw = canonical_bytes(dict(record))
    else:
        raise TypeError("record must be a mapping or canonical bytes")
    return domain_prefix(kind) + raw


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def public_key_problem(public_key: object) -> str | None:
    """Return why ``public_key`` may not be pinned (N1-SPEC r2 2.3), or None if it may.

    ``public_key_encoding``: not 64 lowercase hex characters (32 raw bytes).
    ``public_key_noncanonical``: its low 255 bits, read little-endian, are >= 2^255 - 19.
    ``public_key_small_order``: one of the ten small-order encodings. ``cryptography``
    loads those keys, and a signature with a small-order R and S = 0 then verifies
    without any private key.
    """
    if type(public_key) is not str or _HEX64_RE.fullmatch(public_key) is None:
        return "public_key_encoding"
    y = int.from_bytes(bytes.fromhex(public_key), "little") & ((1 << 255) - 1)
    if y >= ED25519_FIELD_PRIME:
        return "public_key_noncanonical"
    if y in ED25519_SMALL_ORDER_Y:
        return "public_key_small_order"
    return None


def verify_ed25519_hex(public_hex: str, signature: bytes | str, message: bytes) -> bool:
    """Verify an Ed25519 signature under a 64-char lowercase hex public key.

    Returns False for a key ``public_key_problem`` refuses (bad encoding,
    non-canonical or small order), whatever the signature.
    """
    if public_key_problem(public_hex) is not None:
        return False
    if type(signature) is str:
        if _HEX128_RE.fullmatch(signature) is None:
            return False
        sig_bytes = bytes.fromhex(signature)
    elif type(signature) is bytes and len(signature) == 64:
        sig_bytes = signature
    else:
        return False
    if type(message) is not bytes:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(
            sig_bytes, message
        )
    except InvalidSignature:
        return False
    except Exception:  # noqa: BLE001 - N1-SPEC 4.2: a signature-check error refuses, never raises
        return False
    return True


def open_envelope(data: object) -> tuple[dict[str, object], bytes] | None:
    """Decode and validate a canonical ``{"record": ..., "signature": ...}`` envelope."""
    if type(data) is not bytes:
        return None
    try:
        obj = decode_canonical(data)
    except (AdmissionRefused, TypeError, ValueError):
        return None
    if (
        type(obj) is not dict
        or set(obj.keys()) != _ENVELOPE_KEYS
        or type(obj.get("record")) is not dict
    ):
        return None
    signature = obj.get("signature")
    if type(signature) is not str or _HEX128_RE.fullmatch(signature) is None:
        return None
    return obj["record"], bytes.fromhex(signature)


# ---------------------------------------------------------------------------
# Concrete reference carriers for verified outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IssuerWitness:
    witness_reference: str

    @property
    def witness_registration(self) -> str:
        return self.witness_reference


@dataclass(frozen=True, slots=True)
class IssuerProcessRef:
    process_registration: str

    @property
    def process_reference(self) -> str:
        return self.process_registration


@dataclass(frozen=True, slots=True)
class IssuerRootObject:
    filesystem_object: str
    mount_identity: str
    namespace_identity: str
    observation_epoch: str


@dataclass(frozen=True, slots=True)
class IssuerFutureSubject:
    selected_scope_reference: str
    subject_kind: Literal["future"] = field(default="future", init=False)


@dataclass(frozen=True, slots=True)
class IssuerExistingSubject:
    identity: IssuerProcessRef | IssuerRootObject
    subject_kind: Literal["existing"] = field(default="existing", init=False)


@dataclass(frozen=True, slots=True)
class IssuerInterval:
    clock_domain: str
    interval_witness: NativeWitness


@dataclass(frozen=True, slots=True)
class _VerifierOnlyPlaceholderRef:
    """Placeholder reference in ``IssuerVerificationEvidence``; never a source reference.

    N1 verifies issuer authority only and holds no source, closure, selection or
    compatibility facts. ``P3AuthorityRegistry`` drops this evidence and builds its own
    ``DecisionEvidence`` from its snapshot.
    """

    path: str = "n1-verifier-only/no-source"
    digest: str = "0" * 64
    length: int = 64
    revision: str = "n1-verifier-only"


_VERIFIER_ONLY_PLACEHOLDER_REF: Final[ImmutableReference] = (
    _VerifierOnlyPlaceholderRef()
)
_VERIFIER_ONLY_PLACEHOLDER_PROFILE: Final[CompatibilityProfile] = CompatibilityProfile(
    decision="p3-native-decision/1",
    reviewed_graph="p3-reviewed-source-graph/1",
    loaded_envelope="p3-reviewed-loaded-closure/1",
    comparator="systems-n3-comparator/1",
    observation="ops-host-observation/1",
    inspect="/1",
    caller="temper.candidate-admission.v1",
    corpus="ops-host-compat-corpus/1",
    receiving="qa-receiving/1",
)
_VERIFIER_ONLY_PLACEHOLDER_SELECTION: Final[ProjectSelection] = ProjectSelection(
    project_id="n1-verifier-only",
    run_id="n1-verifier-only",
    kit_id="n1-verifier-only",
    kit_sha256="0" * 64,
    build_sums_sha256="0" * 64,
    publication_ref=_VERIFIER_ONLY_PLACEHOLDER_REF,
    publication_revision="n1-verifier-only",
    build_ref=_VERIFIER_ONLY_PLACEHOLDER_REF,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class IssuerVerificationEvidence:
    """Verifier-only ``DecisionEvidence`` returned by ``Ed25519IssuerVerifier.verify()``.

    Only ``authority_revisions``, ``processes`` and ``effect`` are verified facts; the
    source, closure, selection and compatibility fields are verifier-only placeholders.
    ``P3AuthorityRegistry`` drops this evidence and builds its own from its snapshot.
    """

    selected_job: SelectedJob
    authority_revisions: tuple[AuthorityRef, ...]
    window: NativeSubject | None
    processes: tuple[NativeProcessRef, ...]
    effect: SelectedOperation
    schema: Literal["p3-native-decision/1"] = "p3-native-decision/1"
    phase: Phase = Phase.A
    boundary: Boundary = "A_PRE_CREATE"
    source: ImmutableReference = _VERIFIER_ONLY_PLACEHOLDER_REF
    closure: ImmutableReference = _VERIFIER_ONLY_PLACEHOLDER_REF
    compatibility: CompatibilityProfile = _VERIFIER_ONLY_PLACEHOLDER_PROFILE
    receiving: tuple[ImmutableReference, ...] = ()


# ---------------------------------------------------------------------------
# Projections & schema validators (N1-SPEC section 3 & 6)
# ---------------------------------------------------------------------------


class UnprojectableSubject(Exception):
    """Raised when a SelectedSubject cannot be projected to canonical N1 JSON."""


def _require_text(value: object) -> str:
    if not is_text(value):
        raise UnprojectableSubject("expected non-empty str")
    return value  # type: ignore[return-value]


def project_native_subject(subject: object) -> dict[str, object]:
    """Project a native subject (N1-SPEC 3.3): future, existing process or existing root."""
    kind = getattr(subject, "subject_kind", None)
    if type(kind) is str and kind == "future":
        return {
            "kind": "future",
            "selected_scope_reference": _require_text(
                getattr(subject, "selected_scope_reference", None)
            ),
        }
    if type(kind) is str and kind == "existing":
        identity = getattr(subject, "identity", None)
        is_process = hasattr(identity, "process_registration")
        is_root = any(hasattr(identity, name) for name in _ROOT_FIELDS)
        if is_process == is_root:
            raise UnprojectableSubject(
                "existing subject identity must be process or root"
            )
        if is_process:
            return {
                "kind": "existing-process",
                "process_registration": _require_text(
                    getattr(identity, "process_registration", None)
                ),
            }
        return {
            "kind": "existing-root",
            **{
                name: _require_text(getattr(identity, name, None))
                for name in _ROOT_FIELDS
            },
        }
    raise UnprojectableSubject("unknown subject_kind")


def project_job(job: object) -> dict[str, object]:
    """Project an exact ``PreDispatchJob``, or an exact ``JobKey`` over an exact
    ``DispatchIdentity`` (N1-SPEC 3.3); a subclass or look-alike class refuses."""
    if type(job) is PreDispatchJob:
        return {
            "kind": "pre-dispatch",
            "execution_uuid": _require_text(job.execution_uuid),
            "designated_workflow": _require_text(job.designated_workflow),
            "descriptor_digest": _require_text(job.descriptor_digest),
            "job_revision": _require_text(job.job_revision),
        }
    if type(job) is JobKey and type(job.dispatch) is DispatchIdentity:
        dispatch = job.dispatch
        attempt = dispatch.running_attempt
        if type(attempt) is not int or attempt < 1:
            raise UnprojectableSubject("running_attempt must be int >= 1")
        return {
            "kind": "job-key",
            "dispatch": {
                "execution_uuid": _require_text(dispatch.execution_uuid),
                "dispatch_nonce": _require_text(dispatch.dispatch_nonce),
                "running_attempt": attempt,
            },
            "job_revision": _require_text(job.job_revision),
        }
    raise UnprojectableSubject("unsupported job type")


def project_subject(subject: object) -> dict[str, object]:
    """Project an exact ``SelectedSubject`` to its canonical N1 object (N1-SPEC 3.3)."""
    if type(subject) is not SelectedSubject:
        raise UnprojectableSubject("subject must be SelectedSubject")
    return {
        "job": project_job(subject.job),
        "selection_revision": _require_text(subject.selection_revision),
        "subject": project_native_subject(subject.subject),
    }


def record_subject_to_native(obj: dict[str, object]) -> NativeSubject:
    kind = obj["kind"]
    if kind == "future":
        return IssuerFutureSubject(str(obj["selected_scope_reference"]))
    if kind == "existing-process":
        return IssuerExistingSubject(IssuerProcessRef(str(obj["process_registration"])))
    return IssuerExistingSubject(
        IssuerRootObject(**{name: str(obj[name]) for name in _ROOT_FIELDS})
    )


def _exact_keys(
    obj: object, keys: set[str] | frozenset[str]
) -> TypeGuard[dict[str, object]]:
    return type(obj) is dict and set(obj.keys()) == keys


def _all_texts(obj: dict[str, object], names: Sequence[str]) -> bool:
    return all(is_text(obj.get(name)) for name in names)


def _canonical_ascending(items: list[object]) -> bool:
    encoded = [canonical_bytes(item) for item in items]
    return all(left < right for left, right in zip(encoded, encoded[1:], strict=False))


def _valid_sorted_list(
    value: object,
    item_ok: Callable[[object], bool],
    *,
    non_empty: bool,
) -> bool:
    return (
        type(value) is list
        and (bool(value) or not non_empty)
        and all(item_ok(item) for item in value)
        and _canonical_ascending(value)
    )


def valid_native_subject_dict(obj: object) -> bool:
    if type(obj) is not dict or type(obj.get("kind")) is not str:
        return False
    kind = obj["kind"]
    if kind == "future":
        return _exact_keys(obj, {"kind", "selected_scope_reference"}) and is_text(
            obj["selected_scope_reference"]
        )
    if kind == "existing-process":
        return _exact_keys(obj, {"kind", "process_registration"}) and is_text(
            obj["process_registration"]
        )
    if kind == "existing-root":
        return _exact_keys(obj, {"kind", *_ROOT_FIELDS}) and _all_texts(
            obj, _ROOT_FIELDS
        )
    return False


def valid_job_dict(obj: object) -> bool:
    if type(obj) is not dict or type(obj.get("kind")) is not str:
        return False
    if obj["kind"] == "pre-dispatch":
        names = (
            "execution_uuid",
            "designated_workflow",
            "descriptor_digest",
            "job_revision",
        )
        return _exact_keys(obj, {"kind", *names}) and _all_texts(obj, names)
    if obj["kind"] == "job-key":
        if not _exact_keys(obj, {"kind", "dispatch", "job_revision"}) or not is_text(
            obj["job_revision"]
        ):
            return False
        dispatch = obj["dispatch"]
        return (
            _exact_keys(
                dispatch, {"execution_uuid", "dispatch_nonce", "running_attempt"}
            )
            and is_text(dispatch["execution_uuid"])
            and is_text(dispatch["dispatch_nonce"])
            and type(dispatch["running_attempt"]) is int
            and dispatch["running_attempt"] >= 1
        )
    return False


def valid_subject_dict(obj: object) -> bool:
    return (
        _exact_keys(obj, {"job", "selection_revision", "subject"})
        and valid_job_dict(obj["job"])
        and is_text(obj["selection_revision"])
        and valid_native_subject_dict(obj["subject"])
    )


def valid_ref_dict(obj: object) -> bool:
    names = ("issuer_id", "record_id", "authority_revision")
    return _exact_keys(obj, set(names)) and _all_texts(obj, names)


def valid_operation_dict(obj: object) -> bool:
    names = ("domain", "operation", "revision")
    return _exact_keys(obj, set(names)) and _all_texts(obj, names)


def valid_condition_dict(obj: object) -> bool:
    return (
        _exact_keys(obj, {"authority", "condition_id", "revision"})
        and valid_ref_dict(obj["authority"])
        and is_text(obj["condition_id"])
        and is_text(obj["revision"])
    )


def valid_revoked_entry_dict(obj: object) -> bool:
    return _exact_keys(obj, {"record_id", "authority_revision"}) and _all_texts(
        obj, ("record_id", "authority_revision")
    )


def valid_authority_record(rec: object) -> bool:
    if not _exact_keys(rec, _AUTHORITY_KEYS):
        return False
    assert isinstance(rec, dict)
    return (
        type(rec["schema"]) is str
        and rec["schema"] == ISSUER_AUTHORITY_SCHEMA
        and _all_texts(
            rec,
            (
                "verification_profile",
                "issuer_id",
                "key_id",
                "record_id",
                "authority_revision",
                "clock_domain",
            ),
        )
        and is_decimal(rec["not_before"])
        and is_decimal(rec["expires_at"])
        and valid_subject_dict(rec["subject"])
        and _valid_sorted_list(rec["actors"], is_text, non_empty=True)
        and _valid_sorted_list(rec["operations"], valid_operation_dict, non_empty=True)
        and _valid_sorted_list(rec["roots"], valid_native_subject_dict, non_empty=False)
        and _valid_sorted_list(rec["conditions"], valid_condition_dict, non_empty=False)
    )


def valid_status_record(rec: object) -> bool:
    if not _exact_keys(rec, _STATUS_KEYS):
        return False
    assert isinstance(rec, dict)
    return (
        type(rec["schema"]) is str
        and rec["schema"] == ISSUER_REVOCATION_SCHEMA
        and _all_texts(
            rec,
            ("verification_profile", "issuer_id", "key_id", "clock_domain"),
        )
        and all(
            is_decimal(rec[name])
            for name in ("revocation_revision", "issued_at", "next_update")
        )
        and _valid_sorted_list(
            rec["revoked"], valid_revoked_entry_dict, non_empty=False
        )
    )


# ---------------------------------------------------------------------------
# Trust anchors & stores
# ---------------------------------------------------------------------------


class AnchorTableInvalid(ValueError):
    """Deterministic construction failure for malformed pinned trust-anchor tables."""


@dataclass(frozen=True, slots=True)
class AnchorEntry:
    """Pinned Ed25519 trust anchor for one issuer key. Every field is required:
    the validity window and purposes are always named, never defaulted."""

    issuer_id: str
    key_id: str
    public_key: str
    valid_from: str
    valid_until: str
    purposes: frozenset[str]


@dataclass(frozen=True, slots=True)
class AnchorTable:
    """Pinned trust-anchor table bound to one clock domain whose readings never
    repeat or go back (N1-SPEC r2 6.8). Both fields are required."""

    clock_domain: str
    entries: tuple[AnchorEntry, ...]

    def __post_init__(self) -> None:
        validate_anchor_table(self)


def validate_anchor_table(table: object) -> AnchorTable:
    """Validate an ``AnchorTable`` and all ``AnchorEntry`` items fail-fast (N1-SPEC section 2.2)."""
    if type(table) is not AnchorTable:
        raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:table_type")
    if not is_text(table.clock_domain):
        raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:clock_domain")
    if type(table.entries) is not tuple:
        raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:entries_type")
    if table.entries and table.clock_domain == PRODUCTION_CLOCK_DOMAIN_UNSET:
        raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:clock_domain_unset")
    seen: set[tuple[str, str]] = set()
    for entry in table.entries:
        if type(entry) is not AnchorEntry:
            raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:entry_type")
        if not is_text(entry.issuer_id) or not is_text(entry.key_id):
            raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:entry_id")
        pair = (entry.issuer_id, entry.key_id)
        if pair in seen:
            raise AnchorTableInvalid(
                "p3_issuer_anchor_table_invalid:duplicate_issuer_key"
            )
        seen.add(pair)
        key_problem = public_key_problem(entry.public_key)
        if key_problem is not None:
            raise AnchorTableInvalid(f"p3_issuer_anchor_table_invalid:{key_problem}")
        if not is_decimal(entry.valid_from) or not is_decimal(entry.valid_until):
            raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:validity_encoding")
        if int(entry.valid_from) >= int(entry.valid_until):
            raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:validity_empty")
        if (
            type(entry.purposes) is not frozenset
            or not entry.purposes
            or not entry.purposes <= ANCHOR_PURPOSES
        ):
            raise AnchorTableInvalid("p3_issuer_anchor_table_invalid:purposes")
    return table


# Production trust-anchor table is empty at T5 until owner consent C2; its clock
# domain stays the unset placeholder until the production clock is chosen.
PRODUCTION_TRUST_ANCHORS: Final[tuple[AnchorEntry, ...]] = ()
PRODUCTION_ANCHOR_TABLE: Final[AnchorTable] = AnchorTable(
    clock_domain=PRODUCTION_CLOCK_DOMAIN_UNSET,
    entries=PRODUCTION_TRUST_ANCHORS,
)


class StoreUnavailable(Exception):
    """Raised when the signed authority record or revocation status store cannot be read."""


class EnvelopeStore:
    """In-memory store of canonical signed envelopes with explicit unavailability simulation."""

    def __init__(
        self,
        items: Mapping[Any, bytes] | None = None,
        *,
        unavailable: bool = False,
    ) -> None:
        self.items: dict[object, bytes] = dict(items or {})
        self.unavailable: bool = unavailable

    def read(self, key: object) -> bytes | None:
        if self.unavailable:
            raise StoreUnavailable("envelope store is unavailable")
        return self.items.get(key)


# ---------------------------------------------------------------------------
# Condition evaluation (verifier C1-C3 and registry C4-C5)
# ---------------------------------------------------------------------------


def evaluate_registry_conditions(
    job: object,
    verified_by_ref: Mapping[AuthorityRef, VerifiedAuthority],
    *,
    condition_table: Mapping[str, str] | None = CONDITION_TABLE,
    predicates: Mapping[str, Callable[[object], bool]] = CONDITION_PREDICATES,
) -> Literal["C4", "C5"] | None:
    """Evaluate N1 registry-level condition predicates and job condition bindings (C4, C5).

    Returns ``None`` when all conditions hold, ``"C4"`` when a verified authority
    condition fails table/predicate evaluation against ``job``, or ``"C5"`` when a
    job condition is malformed, bound to an authority not on the job, or absent from
    that authority's verified conditions.
    """
    selector_ref = getattr(job, "selector_issuer", None)
    auth_refs = getattr(job, "authority_refs", ())
    if type(selector_ref) is not AuthorityRef or type(auth_refs) is not tuple:
        return "C5"
    bound: tuple[AuthorityRef, ...] = (selector_ref, *auth_refs)
    for ref in bound:
        verified = verified_by_ref.get(ref)
        if verified is None:
            return "C4"
        for cond in getattr(verified, "conditions", ()):
            if type(cond) is not ConditionRef:
                return "C4"
            predicate = predicates.get(cond.condition_id)
            if predicate is None:
                return "C4"
            if (
                condition_table is not None
                and condition_table.get(cond.condition_id) != cond.revision
            ):
                return "C4"
            if not predicate(job):
                return "C4"
    job_conditions = getattr(job, "conditions", ())
    if not isinstance(job_conditions, tuple):
        return "C5"
    for cond in job_conditions:
        if (
            type(cond) is not ConditionRef
            or type(cond.authority) is not AuthorityRef
            or cond.authority not in bound
        ):
            return "C5"
        verified = verified_by_ref.get(cond.authority)
        if verified is None or cond not in verified.conditions:
            return "C5"
    return None


# ---------------------------------------------------------------------------
# Concrete peer and issuer verifiers
# ---------------------------------------------------------------------------


class PinnedPeerInvalid(ValueError):
    """A peer given to ``PinnedPeerVerifier`` lacks a non-empty str ``peer_registration``
    or ``process.process_registration``; such a peer can never be pinned."""


def _strict_peer_identity(peer: object) -> tuple[str, str] | None:
    """(peer_registration, process.process_registration) when both are non-empty str, else None.

    No fallback attribute (``peer_reference`` / ``process_reference``) is read (N1-SPEC 4.5).
    """
    peer_reg = getattr(peer, "peer_registration", None)
    proc_reg = getattr(getattr(peer, "process", None), "process_registration", None)
    if not is_text(peer_reg) or not is_text(proc_reg):
        return None
    return (peer_reg, proc_reg)


def _pinnable_peer_identity(peer: AuthenticatedPeer) -> tuple[str, str]:
    identity = _strict_peer_identity(peer)
    if identity is None:
        raise PinnedPeerInvalid(
            "pinned peer needs a non-empty str peer_registration and "
            "process.process_registration"
        )
    return identity


class PinnedPeerVerifier:
    """Concrete ``PeerVerifierProtocol`` against pinned non-empty peer and process registrations.

    Pinning or revoking a peer without both registrations raises ``PinnedPeerInvalid``;
    ``verify_peer`` never raises and returns False for such a peer.
    """

    def __init__(self, allowed_peers: Sequence[AuthenticatedPeer] = ()) -> None:
        self._allowed: dict[tuple[str, str], AuthenticatedPeer] = {}
        for peer in allowed_peers:
            self.register_peer(peer)

    def register_peer(self, peer: AuthenticatedPeer) -> None:
        self._allowed[_pinnable_peer_identity(peer)] = peer

    def revoke_peer(self, peer: AuthenticatedPeer) -> None:
        self._allowed.pop(_pinnable_peer_identity(peer), None)

    def verify_peer(self, peer: AuthenticatedPeer) -> bool:
        try:
            identity = _strict_peer_identity(peer)
            if identity is None:
                return False
            expected = self._allowed.get(identity)
            return expected is not None and bool(expected == peer)
        except Exception:  # noqa: BLE001 - an odd peer object is unverified, never an error
            return False


def _refusal(code: RefusalCode) -> Refusal:
    if code is RefusalCode.AUTHORITY_UNAVAILABLE:
        retry = RetryKind.SAME_BOUNDARY_AFTER_REPAIR
    elif code in (RefusalCode.AUTHORITY_REVOKED, RefusalCode.AUTHORITY_EXPIRED):
        retry = RetryKind.NEW_BINDING_REQUIRED
    else:
        retry = RetryKind.NOT_APPLICABLE
    return Refusal(
        code=code,
        phase=Phase.A,
        retry_kind=retry,
        admission_state=AdmissionState.NOT_ADMITTED,
        effect_state=EffectState.NONE,
        sequence_use=SequenceUse.NOT_APPLICABLE,
    )


class Ed25519IssuerVerifier:
    """Cryptographic Ed25519 implementation of the ``IssuerVerifier`` port for P3 T5 N1.

    Executes the deterministic N1 verification sequence (rows I1-I12, R1-R7,
    W1, S1, P1-P2, E1-E2, C1-C3) with an empty production trust-anchor table
    by default.
    """

    def __init__(
        self,
        anchors: AnchorTable = PRODUCTION_ANCHOR_TABLE,
        records: EnvelopeStore | Mapping[AuthorityRef, bytes] | None = None,
        statuses: EnvelopeStore | Mapping[str, bytes] | None = None,
        *,
        condition_table: Mapping[str, str] = CONDITION_TABLE,
    ) -> None:
        self.anchors: AnchorTable = validate_anchor_table(anchors)
        if isinstance(records, EnvelopeStore):
            self.records: EnvelopeStore = records
        else:
            self.records = EnvelopeStore(records)
        if isinstance(statuses, EnvelopeStore):
            self.statuses: EnvelopeStore = statuses
        else:
            self.statuses = EnvelopeStore(statuses)
        self.condition_table: dict[str, str] = dict(condition_table)
        self.high_water: dict[str, tuple[int, str]] = {}
        self._lock = threading.Lock()

    def _anchor(
        self,
        issuer_id: str,
        key_id: str,
        purpose: str,
        now: int,
    ) -> AnchorEntry | None:
        for entry in self.anchors.entries:
            if (
                entry.issuer_id == issuer_id
                and entry.key_id == key_id
                and purpose in entry.purposes
                and int(entry.valid_from) <= now < int(entry.valid_until)
            ):
                return entry
        return None

    def _read_store(
        self, store: EnvelopeStore | Mapping[object, bytes], key: object
    ) -> bytes | None:
        if hasattr(store, "read") and callable(store.read):
            return store.read(key)  # type: ignore[no-any-return]
        if isinstance(store, Mapping):
            return store.get(key)
        raise StoreUnavailable("unsupported store type")

    def _fresh_status(
        self, issuer_id: str, now: int
    ) -> tuple[dict[str, object], str] | Refusal:
        try:
            stored = self._read_store(self.statuses, issuer_id)
        except Exception:  # noqa: BLE001 - N1-SPEC 4.2: any status-store error is R1
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R1
        if stored is None:
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R1
        opened = open_envelope(stored)
        if opened is None:
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R2
        status, signature = opened
        if (
            not valid_status_record(status)
            or status["verification_profile"] != ISSUER_VERIFICATION_PROFILE
            or status["clock_domain"] != self.anchors.clock_domain
        ):
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R2
        if status["issuer_id"] != issuer_id:
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R3
        entry = self._anchor(
            str(status["issuer_id"]),
            str(status["key_id"]),
            REVOCATION_STATUS_KIND,
            now,
        )
        if entry is None:
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R3
        signed = domain_prefix(REVOCATION_STATUS_KIND) + canonical_bytes(status)
        if not verify_ed25519_hex(entry.public_key, signature, signed):
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R4
        if not (int(str(status["issued_at"])) <= now < int(str(status["next_update"]))):
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R5
        revision = int(str(status["revocation_revision"]))
        digest = sha256_hex(signed)
        with self._lock:
            seen = self.high_water.get(issuer_id)
            if seen is not None and (
                revision < seen[0] or (revision == seen[0] and digest != seen[1])
            ):
                return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)  # R6
            if seen is None or revision > seen[0]:
                self.high_water[issuer_id] = (revision, digest)
        return status, digest

    def verify(
        self,
        ref: AuthorityRef,
        peer: AuthenticatedPeer,
        subject: SelectedSubject,
        effects: EffectSet,
        at: TrustedInstant,
    ) -> Result[VerifiedAuthority]:
        # I1: AuthorityRef structural check (never caller candidate or non-AuthorityRef)
        if type(ref) is not AuthorityRef or not all(
            is_text(v) for v in (ref.issuer_id, ref.record_id, ref.authority_revision)
        ):
            return _refusal(RefusalCode.AUTHORITY_UNBOUND)

        # I2: Pinned trust anchor exists for ref.issuer_id with authority-record purpose
        if not any(
            e.issuer_id == ref.issuer_id and AUTHORITY_RECORD_KIND in e.purposes
            for e in self.anchors.entries
        ):
            return _refusal(RefusalCode.ISSUER_UNVERIFIED)

        # I3: TrustedInstant domain and strict ASCII decimal integer reading
        if (
            type(at) is not TrustedInstant
            or type(at.clock_domain) is not str
            or at.clock_domain != self.anchors.clock_domain
            or not is_decimal(at.reading)
        ):
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)
        now = int(at.reading)

        # I4 / I5: Read signed authority record from store; any store error is I4
        try:
            stored = self._read_store(self.records, ref)
        except Exception:  # noqa: BLE001 - N1-SPEC 4.2: verify never raises
            return _refusal(RefusalCode.AUTHORITY_UNAVAILABLE)
        if stored is None:
            return _refusal(RefusalCode.AUTHORITY_UNBOUND)

        # I6: Canonical envelope decode and lowercase 128-hex signature syntax
        opened = open_envelope(stored)
        if opened is None:
            return _refusal(RefusalCode.ISSUER_UNVERIFIED)
        record, signature = opened

        # I7: Closed authority-record schema & canonical sorted list invariants
        if not valid_authority_record(record):
            return _refusal(RefusalCode.ISSUER_UNVERIFIED)

        # I8: Verification profile match
        if record["verification_profile"] != ISSUER_VERIFICATION_PROFILE:
            return _refusal(RefusalCode.ISSUER_UNVERIFIED)

        # I9: Record clock_domain matches anchor table clock_domain
        if record["clock_domain"] != self.anchors.clock_domain:
            return _refusal(RefusalCode.ISSUER_UNVERIFIED)

        # I10: Trust anchor lookup for (issuer_id, key_id, authority-record) active at now
        entry = self._anchor(
            str(record["issuer_id"]),
            str(record["key_id"]),
            AUTHORITY_RECORD_KIND,
            now,
        )
        if entry is None:
            return _refusal(RefusalCode.ISSUER_UNVERIFIED)

        # I11: Ed25519 signature verification over domain_prefix || canonical_bytes(record)
        signed = domain_prefix(AUTHORITY_RECORD_KIND) + canonical_bytes(record)
        if not verify_ed25519_hex(entry.public_key, signature, signed):
            return _refusal(RefusalCode.ISSUER_UNVERIFIED)

        # I12: Signed record identity matches requested AuthorityRef (anti-substitution)
        if (
            record["issuer_id"],
            record["record_id"],
            record["authority_revision"],
        ) != (
            ref.issuer_id,
            ref.record_id,
            ref.authority_revision,
        ):
            return _refusal(RefusalCode.ISSUER_UNVERIFIED)

        digest = sha256_hex(signed)

        # R1-R6: Signed revocation status presence, schema, anchor, signature, freshness, high-water
        status_or_refusal = self._fresh_status(str(record["issuer_id"]), now)
        if isinstance(status_or_refusal, Refusal):
            return status_or_refusal
        status, status_digest = status_or_refusal

        # R7: Revocation listing check
        listed = {
            "record_id": record["record_id"],
            "authority_revision": record["authority_revision"],
        }
        revoked_entries = status["revoked"]
        assert isinstance(revoked_entries, list)
        if listed in revoked_entries:
            return _refusal(RefusalCode.AUTHORITY_REVOKED)

        # W1: Half-open integer validity window [not_before, expires_at)
        if not (int(str(record["not_before"])) <= now < int(str(record["expires_at"]))):
            return _refusal(RefusalCode.AUTHORITY_EXPIRED)

        # S1: Canonical SelectedSubject projection match. A subject that cannot be
        # projected or encoded (look-alike type, raising attribute, lone surrogate)
        # is S1, never an exception out of verify (N1-SPEC 4.2).
        try:
            projected_bytes = canonical_bytes(project_subject(subject))
        except Exception:  # noqa: BLE001
            return _refusal(RefusalCode.SUBJECT_MISMATCH)
        if projected_bytes != canonical_bytes(record["subject"]):
            return _refusal(RefusalCode.SUBJECT_MISMATCH)

        # P1-P2: Non-empty peer & process registration (P1 -> PEER_UNVERIFIED) and actor membership (P2 -> SUBJECT_MISMATCH)
        try:
            process: Any = getattr(peer, "process", None)
            registration = getattr(process, "process_registration", None)
            peer_registration = getattr(peer, "peer_registration", None)
        except Exception:  # noqa: BLE001 - an odd peer object is P1, never an error
            return _refusal(RefusalCode.PEER_UNVERIFIED)
        if not is_text(peer_registration) or not is_text(registration):
            return _refusal(RefusalCode.PEER_UNVERIFIED)
        actors_raw = record["actors"]
        assert isinstance(actors_raw, list)
        if registration not in actors_raw:
            return _refusal(RefusalCode.SUBJECT_MISMATCH)

        # E1-E2: Non-empty frozenset[SelectedOperation] (E1) and subset of granted operations (E2)
        if (
            type(effects) is not frozenset
            or not effects
            or not all(
                type(op) is SelectedOperation
                and all(is_text(v) for v in (op.domain, op.operation, op.revision))
                for op in effects
            )
        ):
            return _refusal(RefusalCode.SCOPE_MISMATCH)
        operations_raw = record["operations"]
        assert isinstance(operations_raw, list)
        granted = {
            (str(o["domain"]), str(o["operation"]), str(o["revision"]))
            for o in operations_raw
            if isinstance(o, dict)
        }
        if not all((op.domain, op.operation, op.revision) in granted for op in effects):
            return _refusal(RefusalCode.SCOPE_MISMATCH)

        # C1-C3: ConditionRef self-binding (C1), closed condition_id table (C2), and exact revision (C3)
        own = {
            "issuer_id": ref.issuer_id,
            "record_id": ref.record_id,
            "authority_revision": ref.authority_revision,
        }
        conditions_raw = record["conditions"]
        assert isinstance(conditions_raw, list)
        if any(
            not isinstance(c, dict) or c.get("authority") != own for c in conditions_raw
        ):
            return _refusal(RefusalCode.CONDITIONS_UNMET)
        if any(c["condition_id"] not in self.condition_table for c in conditions_raw):
            return _refusal(RefusalCode.CONDITIONS_UNMET)
        if any(
            c["revision"] != self.condition_table[str(c["condition_id"])]
            for c in conditions_raw
        ):
            return _refusal(RefusalCode.CONDITIONS_UNMET)

        witness = IssuerWitness(f"{ISSUER_AUTHORITY_SCHEMA}#{digest}")
        roots_raw = record["roots"]
        assert isinstance(roots_raw, list)
        verified_ops = frozenset(
            SelectedOperation(
                domain=str(o["domain"]),
                operation=str(o["operation"]),
                revision=str(o["revision"]),
            )
            for o in operations_raw
            if isinstance(o, dict)
        )
        verified_conditions = tuple(
            ConditionRef(
                authority=AuthorityRef(
                    issuer_id=str(c["authority"]["issuer_id"]),
                    record_id=str(c["authority"]["record_id"]),
                    authority_revision=str(c["authority"]["authority_revision"]),
                ),
                condition_id=str(c["condition_id"]),
                revision=str(c["revision"]),
            )
            for c in conditions_raw
            if isinstance(c, dict) and isinstance(c.get("authority"), dict)
        )
        revocation_source = AuthorityRef(
            issuer_id=str(status["issuer_id"]),
            record_id=f"{ISSUER_REVOCATION_SCHEMA}#{status_digest}",
            authority_revision=str(status["revocation_revision"]),
        )
        not_before_instant = TrustedInstant(
            clock_domain=str(record["clock_domain"]),
            reading=str(record["not_before"]),
            witness=witness,
        )
        expires_at_instant = TrustedInstant(
            clock_domain=str(record["clock_domain"]),
            reading=str(record["expires_at"]),
            witness=witness,
        )
        verified = VerifiedAuthority(
            issuer_identity=str(record["issuer_id"]),
            verified_record_digest=digest,
            subject=subject,
            actors=tuple(IssuerProcessRef(str(a)) for a in actors_raw),
            operations=verified_ops,
            roots=tuple(
                record_subject_to_native(r) for r in roots_raw if isinstance(r, dict)
            ),
            conditions=verified_conditions,
            not_before=not_before_instant,
            expires_at=expires_at_instant,
            revocation_source=revocation_source,
            revocation_revision=str(status["revocation_revision"]),
            checked_at=at,
            verification_profile=ISSUER_VERIFICATION_PROFILE,
            validity=IssuerInterval(
                clock_domain=str(record["clock_domain"]),
                interval_witness=witness,
            ),
        )
        primary_effect = sorted(
            effects,
            key=lambda item: (item.domain, item.operation, item.revision),
        )[0]
        placeholder_job = SelectedJob(
            pre_dispatch_or_running_job=subject.job,
            selector_issuer=ref,
            selection_revision=subject.selection_revision,
            selection=_VERIFIER_ONLY_PLACEHOLDER_SELECTION,
            approved_descriptor_digest="0" * 64,
            expected_source_digest="0" * 64,
            reviewed_closure_ref=_VERIFIER_ONLY_PLACEHOLDER_REF,
            compatibility_profile=_VERIFIER_ONLY_PLACEHOLDER_PROFILE,
            authorized_operations=verified_ops,
            conditions=verified_conditions,
            authority_refs=(ref,),
        )
        evidence = IssuerVerificationEvidence(
            selected_job=placeholder_job,
            authority_revisions=(ref,),
            window=None,
            processes=(process,),
            effect=primary_effect,
        )
        return AcceptedData(data=verified, evidence=evidence)


__all__ = [
    "ANCHOR_PURPOSES",
    "AUTHORITY_RECORD_KIND",
    "AnchorEntry",
    "AnchorTable",
    "AnchorTableInvalid",
    "CONDITION_PREDICATES",
    "CONDITION_TABLE",
    "ED25519_FIELD_PRIME",
    "ED25519_SMALL_ORDER_Y",
    "Ed25519IssuerVerifier",
    "EnvelopeStore",
    "ISSUER_AUTHORITY_SCHEMA",
    "ISSUER_REVOCATION_SCHEMA",
    "ISSUER_SIGNATURE_LABEL",
    "ISSUER_VERIFICATION_PROFILE",
    "IssuerExistingSubject",
    "IssuerFutureSubject",
    "IssuerInterval",
    "IssuerProcessRef",
    "IssuerRootObject",
    "IssuerVerificationEvidence",
    "IssuerWitness",
    "PRODUCTION_ANCHOR_TABLE",
    "PRODUCTION_CLOCK_DOMAIN_UNSET",
    "PRODUCTION_TRUST_ANCHORS",
    "PinnedPeerInvalid",
    "PinnedPeerVerifier",
    "REVOCATION_STATUS_KIND",
    "StoreUnavailable",
    "UnprojectableSubject",
    "domain_prefix",
    "evaluate_registry_conditions",
    "is_decimal",
    "is_text",
    "open_envelope",
    "parse_strict_instant_int",
    "project_job",
    "project_native_subject",
    "project_subject",
    "public_key_problem",
    "record_subject_to_native",
    "sha256_hex",
    "signed_domain_bytes",
    "valid_authority_record",
    "valid_status_record",
    "validate_anchor_table",
    "verify_ed25519_hex",
]
