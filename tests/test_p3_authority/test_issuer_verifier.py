"""Tests for P3 T5-A (N1): Ed25519 issuer, revocation, condition, and peer verification.

Covers:
1. Combined happy path (bp-be8d76b9): RFC 8032 section 7.1 TEST 1 vector, CAJ-1 escape
   probe, exact N1-SPEC vector digests/lengths, direct ``Ed25519IssuerVerifier.verify()``,
   and end-to-end ``AuthorityRegistryService`` + ``compose_p3_authority()`` composition.
2. Anchor-table fail-fast construction validation: rows K-OK, K-OK2 and K1-K13 of
   N1-SPEC r2 2.3 (non-canonical and small-order keys included), each refusal with its
   exact ``AnchorTableInvalid`` reason, and the unset production clock domain (6.8).
3. Same-boundary refusal twins across I1-I12, R1-R7, W1, S1, P1-P2, E1-E2, C1-C5,
   and multi-fault precedence X1-X4.
4. Guard bites: empty identity inequality (``"" == ""`` refused), strict integer-only
   instant comparisons, registry snapshot ``verified_at`` + condition evaluation,
   ``P3CandidateBindings`` refused as authority, ``| file`` filter refusal in P3,
   small-order and non-canonical keys never verifying a forged signature, and
   subject projection accepting only the exact selection types.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from temper_ai.config.admission_contract import DispatchIdentity, canonical_bytes
from temper_ai.p3_authority.candidate_bindings import P3CandidateBindings
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AuthorityRef,
    ConditionRef,
    JobKey,
    Phase,
    PreDispatchJob,
    Refusal,
    RefusalCode,
    RetryKind,
    SelectedOperation,
    SelectedSubject,
    TrustedInstant,
    VerifiedAuthority,
)
from temper_ai.p3_authority.issuer_verifier import (
    ANCHOR_PURPOSES,
    AUTHORITY_RECORD_KIND,
    CONDITION_TABLE,
    ED25519_FIELD_PRIME,
    ED25519_SMALL_ORDER_Y,
    ISSUER_AUTHORITY_SCHEMA,
    ISSUER_REVOCATION_SCHEMA,
    ISSUER_VERIFICATION_PROFILE,
    PRODUCTION_ANCHOR_TABLE,
    PRODUCTION_CLOCK_DOMAIN_UNSET,
    PRODUCTION_TRUST_ANCHORS,
    REVOCATION_STATUS_KIND,
    AnchorEntry,
    AnchorTable,
    AnchorTableInvalid,
    Ed25519IssuerVerifier,
    EnvelopeStore,
    PinnedPeerInvalid,
    PinnedPeerVerifier,
    UnprojectableSubject,
    domain_prefix,
    evaluate_registry_conditions,
    project_job,
    project_subject,
    public_key_problem,
    sha256_hex,
    validate_anchor_table,
    verify_ed25519_hex,
)
from temper_ai.p3_authority.registry import (
    AuthorityRegistryService,
    ExistingSubjectRecord,
    FutureSubjectRecord,
    InMemoryIssuerVerifier,
    InMemoryPeerVerifier,
    InMemoryRequestHistoryProvider,
    default_effect_for_job,
)
from temper_ai.p3_authority.service import compose_p3_authority
from tests.test_p3_authority._composition_fixtures import (
    AUTHORITY_REF_1,
    AUTHORITY_REF_2,
    DISPATCH_1,
    FakePeer,
    FakeProcessRef,
    FakeWitness,
    make_populated_test_rig,
    make_verified_authority,
)

KIND_AUTHORITY = AUTHORITY_RECORD_KIND
KIND_STATUS = REVOCATION_STATUS_KIND
CLOCK = "monotonic:host-test-1"
ISSUER_ID = "issuer:temper-test-1"
KEY_ID = "ed25519:rfc8032-test-1"
AT_5000 = TrustedInstant(
    clock_domain=CLOCK,
    reading="5000",
    witness=FakeWitness("wit:test-1"),
)

TEST2_SEED_HEX = "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
TEST2_PUB_HEX = "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"

# Published RFC 8032 section 7.1 TEST 1 vector (TEST-ONLY, N1-SPEC 8.1). Signing
# lives here, never in temper_ai: the production module is verify-only.
RFC8032_TEST1_SECRET_KEY_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
RFC8032_TEST1_PUBLIC_KEY_HEX = (
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
RFC8032_TEST1_EMPTY_SIGNATURE_HEX = (
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)


def sign_ed25519(secret_key_hex: str, message: bytes) -> bytes:
    """Sign ``message`` with a TEST-ONLY 32-byte Ed25519 seed given as hex."""
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(secret_key_hex)).sign(
        message
    )


def make_envelope(record: dict[str, Any], signature: bytes) -> bytes:
    """Encode ``{"record": record, "signature": <128 lowercase hex>}`` as CAJ-1 bytes."""
    return canonical_bytes({"record": dict(record), "signature": signature.hex()})


def sign_record(
    kind: str,
    record: dict[str, Any],
    *,
    secret_key: str = RFC8032_TEST1_SECRET_KEY_HEX,
) -> bytes:
    """Sign ``domain_prefix(kind) + canonical_bytes(record)`` with a TEST-ONLY key."""
    return sign_ed25519(secret_key, domain_prefix(kind) + canonical_bytes(dict(record)))


def signed_envelope(
    kind: str,
    record: dict[str, Any],
    *,
    secret_key: str = RFC8032_TEST1_SECRET_KEY_HEX,
) -> bytes:
    """Sign ``record`` under ``kind`` and return its canonical envelope bytes."""
    return make_envelope(record, sign_record(kind, record, secret_key=secret_key))


# RFC 8032 section 7.1 TEST SHA(abc): a valid key whose sign bit (top bit) is set.
RFC8032_SHA_ABC_PUBLIC_KEY_HEX = (
    "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf"
)
RFC8032_SHA_ABC_SIGNATURE_HEX = (
    "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
    "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704"
)
# Spec 8.3 small-order y values (32-byte little-endian hex, sign bit 0), copied
# from n1_vectors.out independently of the module's constant.
SPEC_SMALL_ORDER_Y_HEX = (
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0100000000000000000000000000000000000000000000000000000000000000",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
)
IDENTITY_POINT_HEX = "01" + "00" * 31


@dataclass(frozen=True)
class _LookAlikeDispatchIdentity:
    """Same fields and class name as ``DispatchIdentity``, but not that type."""

    execution_uuid: str
    dispatch_nonce: str
    running_attempt: int


_LookAlikeDispatchIdentity.__name__ = "DispatchIdentity"
_LookAlikeDispatchIdentity.__qualname__ = "DispatchIdentity"

REF_1 = AuthorityRef(
    issuer_id=ISSUER_ID,
    record_id="auth:record-1",
    authority_revision="auth-rev-1",
)
PEER_1 = FakePeer("peer:worker-test-1", FakeProcessRef("proc:worker-test-1"))
JOB_KEY_1 = JobKey(dispatch=DISPATCH_1, job_revision="job-rev-run-1")
SUBJECT_1 = SelectedSubject(
    subject=FutureSubjectRecord(selected_scope_reference="scope:sel-run-1"),
    job=JOB_KEY_1,
    selection_revision="sel-run-1",
)
OP_ARM = SelectedOperation(
    domain="A_PRE_ARM", operation="A_PRE_ARM", revision="op-rev-1"
)
OP_REQ = SelectedOperation(
    domain="B_PRE_REQUEST", operation="B_PRE_REQUEST", revision="op-rev-1"
)
EFFECTS_1 = frozenset({OP_ARM, OP_REQ})

ANCHORS_1 = AnchorTable(
    clock_domain=CLOCK,
    entries=(
        AnchorEntry(
            issuer_id=ISSUER_ID,
            key_id=KEY_ID,
            public_key=RFC8032_TEST1_PUBLIC_KEY_HEX,
            valid_from="0",
            valid_until="100000",
            purposes=ANCHOR_PURPOSES,
        ),
    ),
)

AUTHORITY_RECORD_1: dict[str, Any] = {
    "schema": ISSUER_AUTHORITY_SCHEMA,
    "verification_profile": ISSUER_VERIFICATION_PROFILE,
    "issuer_id": ISSUER_ID,
    "key_id": KEY_ID,
    "record_id": "auth:record-1",
    "authority_revision": "auth-rev-1",
    "clock_domain": CLOCK,
    "not_before": "1000",
    "expires_at": "10000",
    "subject": {
        "job": {
            "kind": "job-key",
            "dispatch": {
                "execution_uuid": DISPATCH_1.execution_uuid,
                "dispatch_nonce": DISPATCH_1.dispatch_nonce,
                "running_attempt": 1,
            },
            "job_revision": "job-rev-run-1",
        },
        "selection_revision": "sel-run-1",
        "subject": {
            "kind": "future",
            "selected_scope_reference": "scope:sel-run-1",
        },
    },
    "actors": ["proc:worker-test-1"],
    "operations": [
        {"domain": "A_PRE_ARM", "operation": "A_PRE_ARM", "revision": "op-rev-1"},
        {
            "domain": "B_PRE_REQUEST",
            "operation": "B_PRE_REQUEST",
            "revision": "op-rev-1",
        },
    ],
    "roots": [
        {
            "kind": "existing-root",
            "filesystem_object": "obj:root-1",
            "mount_identity": "mount:root-1",
            "namespace_identity": "mnt:[4026531840]",
            "observation_epoch": "obs-epoch-1",
        },
        {
            "kind": "future",
            "selected_scope_reference": "scope:sel-run-1",
        },
    ],
    "conditions": [
        {
            "authority": {
                "authority_revision": "auth-rev-1",
                "issuer_id": ISSUER_ID,
                "record_id": "auth:record-1",
            },
            "condition_id": "mode:external-db-fresh",
            "revision": "1",
        }
    ],
}

STATUS_RECORD_1: dict[str, Any] = {
    "schema": ISSUER_REVOCATION_SCHEMA,
    "verification_profile": ISSUER_VERIFICATION_PROFILE,
    "issuer_id": ISSUER_ID,
    "key_id": KEY_ID,
    "clock_domain": CLOCK,
    "revocation_revision": "7",
    "issued_at": "4000",
    "next_update": "9000",
    "revoked": [],
}


def _make_verifier(
    *,
    anchors: AnchorTable = ANCHORS_1,
    authority_bytes: bytes | None = None,
    status_bytes: bytes | None = None,
    records_unavailable: bool = False,
    statuses_unavailable: bool = False,
    condition_table: dict[str, str] | None = None,
) -> Ed25519IssuerVerifier:
    env_a = (
        authority_bytes
        if authority_bytes is not None
        else signed_envelope(KIND_AUTHORITY, AUTHORITY_RECORD_1)
    )
    env_s = (
        status_bytes
        if status_bytes is not None
        else signed_envelope(KIND_STATUS, STATUS_RECORD_1)
    )
    return Ed25519IssuerVerifier(
        anchors=anchors,
        records=EnvelopeStore({REF_1: env_a}, unavailable=records_unavailable),
        statuses=EnvelopeStore({ISSUER_ID: env_s}, unavailable=statuses_unavailable),
        condition_table=(
            condition_table if condition_table is not None else dict(CONDITION_TABLE)
        ),
    )


def _assert_refusal(
    result: object,
    expected_code: RefusalCode,
    expected_retry: RetryKind,
) -> None:
    assert isinstance(result, Refusal), (
        f"Expected Refusal({expected_code}), got {result!r}"
    )
    assert result.code is expected_code
    assert result.phase is Phase.A
    assert result.retry_kind is expected_retry


def test_n1_combined_happy_path_rfc8032_vector_and_registry_composition() -> None:
    """Combined whole-feature happy path (bp-be8d76b9): RFC 8032 TEST 1 vector, CAJ-1 escape probe,
    exact N1-SPEC vector digests/lengths, direct Ed25519IssuerVerifier.verify(), and compose_p3_authority()."""
    assert (
        sign_ed25519(RFC8032_TEST1_SECRET_KEY_HEX, b"").hex()
        == RFC8032_TEST1_EMPTY_SIGNATURE_HEX
    )
    assert verify_ed25519_hex(
        RFC8032_TEST1_PUBLIC_KEY_HEX, RFC8032_TEST1_EMPTY_SIGNATURE_HEX, b""
    )
    assert not verify_ed25519_hex(
        RFC8032_TEST1_PUBLIC_KEY_HEX, RFC8032_TEST1_EMPTY_SIGNATURE_HEX, b"x"
    )

    escape_probe = canonical_bytes({"k": 'é\n"\\\x01\x7f/\u2028'})
    assert (
        escape_probe.hex() == "7b226b223a22c3a95c6e5c225c5c5c75303030317f2fe280a8227d"
    )

    vector_a: dict[str, Any] = {
        "actors": ["proc:worker-test-1"],
        "authority_revision": "rev-1",
        "clock_domain": "monotonic:host-test-1",
        "conditions": [
            {
                "authority": {
                    "authority_revision": "rev-1",
                    "issuer_id": "issuer:authority-test",
                    "record_id": "auth:grant-1",
                },
                "condition_id": "mode:external-db-fresh",
                "revision": "1",
            }
        ],
        "expires_at": "10000",
        "issuer_id": "issuer:authority-test",
        "key_id": "test-key-1",
        "not_before": "1000",
        "operations": [
            {
                "domain": "p3.boundary",
                "operation": "A_PRE_CREATE",
                "revision": "sel-rev-1",
            }
        ],
        "record_id": "auth:grant-1",
        "roots": [],
        "schema": ISSUER_AUTHORITY_SCHEMA,
        "subject": {
            "job": {
                "descriptor_digest": "424fd0cee2bd13ddbf0f2beff1107a2580f60e84db1d5847cf2ee61547ce323a",
                "designated_workflow": "designated_v1",
                "execution_uuid": "00000000-0000-4000-8000-000000000001",
                "job_revision": "job-rev-1",
                "kind": "pre-dispatch",
            },
            "selection_revision": "sel-rev-1",
            "subject": {
                "kind": "future",
                "selected_scope_reference": "scope:sel-rev-1",
            },
        },
        "verification_profile": ISSUER_VERIFICATION_PROFILE,
    }
    rec_a_bytes = canonical_bytes(vector_a)
    assert len(rec_a_bytes) == 940
    signed_a = domain_prefix(KIND_AUTHORITY) + rec_a_bytes
    assert (
        sha256_hex(signed_a)
        == "29787feb35064373c585e71a94a02ef23162dca667989c235c492a20d4ada834"
    )
    assert (
        sign_record(KIND_AUTHORITY, vector_a).hex()
        == "52ba29a5861ffddf9e3c6d1b5f9b2944e1346a43229be388c833b4c337d8456896814e6b177e94b390f8644c832421822366f0faf389d0511dcd8010c1f90b09"
    )
    env_vec_a = signed_envelope(KIND_AUTHORITY, vector_a)
    assert len(env_vec_a) == 1094
    assert (
        sha256_hex(env_vec_a)
        == "b72d506becb0a3e6a63ce1a1fa19541b4a030b5672e8029519d55589633aa315"
    )

    vector_s: dict[str, Any] = {
        "clock_domain": "monotonic:host-test-1",
        "issued_at": "4000",
        "issuer_id": "issuer:authority-test",
        "key_id": "test-key-1",
        "next_update": "6000",
        "revocation_revision": "7",
        "revoked": [{"authority_revision": "rev-1", "record_id": "auth:grant-9"}],
        "schema": ISSUER_REVOCATION_SCHEMA,
        "verification_profile": ISSUER_VERIFICATION_PROFILE,
    }
    rec_s_bytes = canonical_bytes(vector_s)
    assert len(rec_s_bytes) == 313
    signed_s = domain_prefix(KIND_STATUS) + rec_s_bytes
    assert (
        sha256_hex(signed_s)
        == "791bb47161ac0e8708c919dcd6ceca8af9c9aeecc667df51100f3b56276eded9"
    )
    assert (
        sign_record(KIND_STATUS, vector_s).hex()
        == "1cb3886268ad5b31b5fdf5382989565e25687a9aeb072d1c87f7e5011720ec02a69d039ac291ecee77f0bd634d67373084347c96554c001b1262134ab8c6180f"
    )
    env_vec_s = signed_envelope(KIND_STATUS, vector_s)
    assert len(env_vec_s) == 467
    assert (
        sha256_hex(env_vec_s)
        == "88b57cb1deade16168418bde18d999543f84e01baf1de60a9e57058aff19d376"
    )

    env_a = signed_envelope(KIND_AUTHORITY, AUTHORITY_RECORD_1)
    env_s = signed_envelope(KIND_STATUS, STATUS_RECORD_1)
    signed_rec1 = domain_prefix(KIND_AUTHORITY) + canonical_bytes(AUTHORITY_RECORD_1)
    signed_stat1 = domain_prefix(KIND_STATUS) + canonical_bytes(STATUS_RECORD_1)
    verifier = _make_verifier(authority_bytes=env_a, status_bytes=env_s)
    res = verifier.verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000)
    assert isinstance(res, AcceptedData)
    verified = res.data
    assert type(verified) is VerifiedAuthority
    assert verified.issuer_identity == ISSUER_ID
    assert verified.verified_record_digest == sha256_hex(signed_rec1)
    assert verified.subject == SUBJECT_1
    assert verified.operations == EFFECTS_1
    assert verified.revocation_revision == "7"
    assert (
        verified.revocation_source.record_id
        == f"{ISSUER_REVOCATION_SCHEMA}#{sha256_hex(signed_stat1)}"
    )
    assert verified.checked_at == AT_5000
    assert verified.verification_profile == ISSUER_VERIFICATION_PROFILE
    # The verifier's own evidence carries verifier-only placeholders, never a source.
    verifier_only_source = res.evidence.source
    assert verifier_only_source.path == "n1-verifier-only/no-source"
    assert res.evidence.selected_job.selection.project_id == "n1-verifier-only"

    # End-to-end composition through compose_p3_authority() + AuthorityRegistryService
    rig = make_populated_test_rig()
    run_job = replace(
        rig.running_job,
        conditions=(
            ConditionRef(
                authority=AUTHORITY_REF_1,
                condition_id="mode:external-db-fresh",
                revision="1",
            ),
        ),
    )
    rig_snap = replace(rig.snapshot, jobs=(rig.pre_dispatch_job, run_job))
    rig.publisher.publish_snapshot(rig_snap)
    run_subject = rig_snap.subject_for(run_job)
    run_ops = sorted(
        [
            {"domain": op.domain, "operation": op.operation, "revision": op.revision}
            for op in run_job.authorized_operations
        ],
        key=canonical_bytes,
    )
    sel_ref = run_job.selector_issuer
    auth_ref = run_job.authority_refs[0]
    sel_rec = {
        **AUTHORITY_RECORD_1,
        "issuer_id": sel_ref.issuer_id,
        "record_id": sel_ref.record_id,
        "authority_revision": sel_ref.authority_revision,
        "subject": project_subject(run_subject),
        "actors": [rig.peer_run.process.process_registration],
        "operations": run_ops,
        "conditions": [],
    }
    job_auth_rec = {
        **AUTHORITY_RECORD_1,
        "issuer_id": auth_ref.issuer_id,
        "record_id": auth_ref.record_id,
        "authority_revision": auth_ref.authority_revision,
        "subject": project_subject(run_subject),
        "actors": [rig.peer_run.process.process_registration],
        "operations": run_ops,
        "conditions": [
            {
                "authority": {
                    "authority_revision": c.authority.authority_revision,
                    "issuer_id": c.authority.issuer_id,
                    "record_id": c.authority.record_id,
                },
                "condition_id": c.condition_id,
                "revision": c.revision,
            }
            for c in run_job.conditions
        ],
    }
    rig_anchors = AnchorTable(
        clock_domain=CLOCK,
        entries=(
            AnchorEntry(
                issuer_id=sel_ref.issuer_id,
                key_id=KEY_ID,
                public_key=RFC8032_TEST1_PUBLIC_KEY_HEX,
                valid_from="0",
                valid_until="100000",
                purposes=ANCHOR_PURPOSES,
            ),
            *(
                ()
                if auth_ref.issuer_id == sel_ref.issuer_id
                else (
                    AnchorEntry(
                        issuer_id=auth_ref.issuer_id,
                        key_id=KEY_ID,
                        public_key=RFC8032_TEST1_PUBLIC_KEY_HEX,
                        valid_from="0",
                        valid_until="100000",
                        purposes=ANCHOR_PURPOSES,
                    ),
                )
            ),
        ),
    )
    composed = compose_p3_authority(
        snapshot_provider=rig.publisher.reader(),
        issuer_anchors=rig_anchors,
        issuer_records={
            sel_ref: signed_envelope(KIND_AUTHORITY, sel_rec),
            auth_ref: signed_envelope(KIND_AUTHORITY, job_auth_rec),
        },
        issuer_statuses={
            sel_ref.issuer_id: signed_envelope(
                KIND_STATUS, {**STATUS_RECORD_1, "issuer_id": sel_ref.issuer_id}
            ),
            auth_ref.issuer_id: signed_envelope(
                KIND_STATUS, {**STATUS_RECORD_1, "issuer_id": auth_ref.issuer_id}
            ),
        },
        pinned_peers=(rig.peer_run,),
    )
    assert composed.service._writes_enabled is False
    run_res = composed.registry.for_run(
        rig.peer_run, DISPATCH_1.execution_uuid, DISPATCH_1
    )
    assert isinstance(run_res, AcceptedData)
    assert run_res.data == run_job
    # The registry drops the verifier's placeholder evidence and builds its own.
    assert run_res.evidence.source != verifier_only_source
    assert run_res.evidence.selected_job == run_job
    assert "n1-verifier-only" not in repr(run_res.evidence)

    # Default compose_p3_authority() remains disabled and refuses fail-closed
    default_composed = compose_p3_authority()
    assert default_composed.service._writes_enabled is False
    assert PRODUCTION_TRUST_ANCHORS == ()
    assert PRODUCTION_ANCHOR_TABLE.entries == ()
    _assert_refusal(
        Ed25519IssuerVerifier().verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),
        RefusalCode.ISSUER_UNVERIFIED,
        RetryKind.NOT_APPLICABLE,
    )


def _anchor_variant(**changes: Any) -> AnchorTable:
    """``ANCHORS_1`` with its one entry changed (the spec script's ``anchor_variant``)."""
    return AnchorTable(
        clock_domain=CLOCK, entries=(replace(ANCHORS_1.entries[0], **changes),)
    )


def _assert_table_invalid(reason: str, build: Callable[[], object]) -> None:
    """``build()`` raises ``AnchorTableInvalid`` with exactly this reason."""
    with pytest.raises(AnchorTableInvalid) as raised:
        build()
    assert str(raised.value) == f"p3_issuer_anchor_table_invalid:{reason}"


def _assert_entry_invalid(reason: str, **changes: Any) -> None:
    """``ANCHORS_1`` with its entry changed raises exactly this reason."""
    _assert_table_invalid(reason, lambda: _anchor_variant(**changes))


def _key_hex(y: int, sign: int = 0) -> str:
    """32-byte little-endian hex of ``y`` with the top (sign) bit set to ``sign``."""
    return (y | sign << 255).to_bytes(32, "little").hex()


SPEC_SMALL_ORDER_Y = tuple(
    int.from_bytes(bytes.fromhex(value), "little") for value in SPEC_SMALL_ORDER_Y_HEX
)


def test_n1_anchor_table_construction_validation() -> None:
    """Anchor-table construction rules K-OK to K13 and the unset clock domain
    (N1-SPEC r2 2.2-2.3, 6.8), each refusal with its exact reason."""
    # K-OK, K-OK2: the production default and the TEST-ONLY table construct.
    assert validate_anchor_table(PRODUCTION_ANCHOR_TABLE) is PRODUCTION_ANCHOR_TABLE
    assert validate_anchor_table(ANCHORS_1) is ANCHORS_1
    # Valid canonical keys stay accepted, one of them with its sign bit set.
    for good_key in (
        RFC8032_TEST1_PUBLIC_KEY_HEX,
        TEST2_PUB_HEX,
        RFC8032_SHA_ABC_PUBLIC_KEY_HEX,
    ):
        assert public_key_problem(good_key) is None
        assert _anchor_variant(public_key=good_key).entries[0].public_key == good_key

    entry = ANCHORS_1.entries[0]
    _assert_table_invalid("table_type", lambda: validate_anchor_table("not-a-table"))
    _assert_entry_invalid("entry_id", issuer_id="")
    _assert_entry_invalid("entry_id", key_id="")
    _assert_table_invalid(
        "entry_type",
        lambda: AnchorTable(clock_domain=CLOCK, entries=("not-an-entry",)),  # type: ignore[arg-type]
    )
    # K1-K9
    _assert_table_invalid(
        "duplicate_issuer_key",
        lambda: AnchorTable(clock_domain=CLOCK, entries=(entry, entry)),
    )
    _assert_entry_invalid(
        "public_key_encoding", public_key=RFC8032_TEST1_PUBLIC_KEY_HEX.upper()
    )
    _assert_entry_invalid(
        "public_key_encoding", public_key=RFC8032_TEST1_PUBLIC_KEY_HEX[:62]
    )
    _assert_entry_invalid("purposes", purposes=frozenset())
    _assert_entry_invalid("purposes", purposes=frozenset({"authority"}))
    _assert_entry_invalid("validity_encoding", valid_from="00")
    _assert_entry_invalid("validity_empty", valid_from="100000")
    _assert_table_invalid(
        "clock_domain", lambda: AnchorTable(clock_domain="", entries=())
    )
    _assert_table_invalid(
        "entries_type",
        lambda: AnchorTable(clock_domain=CLOCK, entries=list(ANCHORS_1.entries)),  # type: ignore[arg-type]
    )
    # K10-K12: identity point (order 1), all-zero bytes (order 4), a point of order 8.
    _assert_entry_invalid("public_key_small_order", public_key=IDENTITY_POINT_HEX)
    _assert_entry_invalid("public_key_small_order", public_key="00" * 32)
    _assert_entry_invalid(
        "public_key_small_order", public_key=SPEC_SMALL_ORDER_Y_HEX[2]
    )
    # All ten small-order encodings: five y values, either sign bit.
    for y in SPEC_SMALL_ORDER_Y:
        for sign in (0, 1):
            _assert_entry_invalid(
                "public_key_small_order", public_key=_key_hex(y, sign)
            )
    # K13: y = p + 2 is non-canonical; so is y = p, which would read as y = 0.
    for y in (ED25519_FIELD_PRIME + 2, ED25519_FIELD_PRIME):
        for sign in (0, 1):
            _assert_entry_invalid(
                "public_key_noncanonical", public_key=_key_hex(y, sign)
            )

    # 6.8: no default clock domain, window or purposes; the production table's
    # placeholder domain refuses as soon as the table holds an entry.
    assert PRODUCTION_ANCHOR_TABLE.clock_domain == PRODUCTION_CLOCK_DOMAIN_UNSET
    assert PRODUCTION_ANCHOR_TABLE.entries == ()
    _assert_table_invalid(
        "clock_domain_unset",
        lambda: AnchorTable(
            clock_domain=PRODUCTION_CLOCK_DOMAIN_UNSET, entries=ANCHORS_1.entries
        ),
    )
    with pytest.raises(TypeError):
        AnchorTable(entries=())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        AnchorTable(clock_domain=CLOCK)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        AnchorEntry(ISSUER_ID, KEY_ID, RFC8032_TEST1_PUBLIC_KEY_HEX)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        AnchorEntry(ISSUER_ID, KEY_ID, RFC8032_TEST1_PUBLIC_KEY_HEX, "0", "100000")  # type: ignore[call-arg]


def test_n1_refusal_twins_i1_to_i12() -> None:
    """Twins I1-I12: AuthorityRef, anchor table, TrustedInstant, record store, envelope, schema, profile, domain, key, signature, and substitution."""
    verifier = _make_verifier()

    # I1: Malformed AuthorityRef / candidate dict
    for bad_ref in (
        {
            "issuer_id": ISSUER_ID,
            "record_id": "auth:record-1",
            "authority_revision": "auth-rev-1",
        },
        AuthorityRef(
            issuer_id="", record_id="auth:record-1", authority_revision="auth-rev-1"
        ),
        AuthorityRef(
            issuer_id=ISSUER_ID, record_id="", authority_revision="auth-rev-1"
        ),
        AuthorityRef(
            issuer_id=ISSUER_ID, record_id="auth:record-1", authority_revision=""
        ),
    ):
        _assert_refusal(
            verifier.verify(bad_ref, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),  # type: ignore[arg-type]
            RefusalCode.AUTHORITY_UNBOUND,
            RetryKind.NOT_APPLICABLE,
        )

    # I2: Production empty anchor table or status-only anchor
    _assert_refusal(
        Ed25519IssuerVerifier(anchors=PRODUCTION_ANCHOR_TABLE).verify(
            REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
        ),
        RefusalCode.ISSUER_UNVERIFIED,
        RetryKind.NOT_APPLICABLE,
    )
    status_only_anchors = AnchorTable(
        clock_domain=CLOCK,
        entries=(
            AnchorEntry(
                ISSUER_ID,
                KEY_ID,
                RFC8032_TEST1_PUBLIC_KEY_HEX,
                "0",
                "100000",
                frozenset({KIND_STATUS}),
            ),
        ),
    )
    _assert_refusal(
        _make_verifier(anchors=status_only_anchors).verify(
            REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
        ),
        RefusalCode.ISSUER_UNVERIFIED,
        RetryKind.NOT_APPLICABLE,
    )

    # I3: Wrong clock domain or non-decimal TrustedInstant reading
    for bad_at in (
        TrustedInstant(
            clock_domain="wall:utc", reading="5000", witness=FakeWitness("w")
        ),
        TrustedInstant(clock_domain=CLOCK, reading="05000", witness=FakeWitness("w")),
        TrustedInstant(clock_domain=CLOCK, reading="+5000", witness=FakeWitness("w")),
        TrustedInstant(clock_domain=CLOCK, reading="-1", witness=FakeWitness("w")),
        TrustedInstant(clock_domain=CLOCK, reading="5000.0", witness=FakeWitness("w")),
        TrustedInstant(clock_domain=CLOCK, reading="5000\n", witness=FakeWitness("w")),
        TrustedInstant(clock_domain=CLOCK, reading="٥٠٠٠", witness=FakeWitness("w")),
        TrustedInstant(
            clock_domain=CLOCK, reading="５０００", witness=FakeWitness("w")
        ),
        TrustedInstant(
            clock_domain=CLOCK, reading="1" * 5000, witness=FakeWitness("w")
        ),
    ):
        _assert_refusal(
            verifier.verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, bad_at),
            RefusalCode.AUTHORITY_UNAVAILABLE,
            RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
        )

    # I4 & I5: Record store unavailable (I4) vs record absent (I5)
    _assert_refusal(
        _make_verifier(records_unavailable=True).verify(
            REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
        ),
        RefusalCode.AUTHORITY_UNAVAILABLE,
        RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
    )
    _assert_refusal(
        verifier.verify(
            AuthorityRef(
                issuer_id=ISSUER_ID,
                record_id="auth:missing",
                authority_revision="auth-rev-1",
            ),
            PEER_1,
            SUBJECT_1,
            EFFECTS_1,
            AT_5000,
        ),
        RefusalCode.AUTHORITY_UNBOUND,
        RetryKind.NOT_APPLICABLE,
    )

    # I6: Non-canonical JSON envelope, duplicate keys, or uppercase/bad-length signature
    sig_hex = sign_record(KIND_AUTHORITY, AUTHORITY_RECORD_1).hex()
    for bad_env in (
        b"{ \n" + signed_envelope(KIND_AUTHORITY, AUTHORITY_RECORD_1)[1:],
        b'{"record":'
        + canonical_bytes(AUTHORITY_RECORD_1)
        + b',"record":{},"signature":"'
        + sig_hex.encode("ascii")
        + b'"}',
        canonical_bytes({"record": AUTHORITY_RECORD_1, "signature": sig_hex.upper()}),
        canonical_bytes({"record": AUTHORITY_RECORD_1, "signature": sig_hex[:-2]}),
    ):
        _assert_refusal(
            _make_verifier(authority_bytes=bad_env).verify(
                REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
            ),
            RefusalCode.ISSUER_UNVERIFIED,
            RetryKind.NOT_APPLICABLE,
        )

    # I7-I9: Closed schema, sorted lists, verification_profile, clock_domain
    for bad_rec in (
        {**AUTHORITY_RECORD_1, "schema": "p3-issuer-authority/2"},
        {**AUTHORITY_RECORD_1, "extra": "1"},
        {**AUTHORITY_RECORD_1, "actors": []},
        {**AUTHORITY_RECORD_1, "actors": ["proc:b", "proc:a"]},
        {
            **AUTHORITY_RECORD_1,
            "operations": list(reversed(AUTHORITY_RECORD_1["operations"])),
        },
        {**AUTHORITY_RECORD_1, "verification_profile": "p3-issuer-ed25519/2"},
        {**AUTHORITY_RECORD_1, "clock_domain": "monotonic:other"},
        {**AUTHORITY_RECORD_1, "not_before": "1" * 5000},
    ):
        _assert_refusal(
            _make_verifier(
                authority_bytes=signed_envelope(KIND_AUTHORITY, bad_rec)
            ).verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),
            RefusalCode.ISSUER_UNVERIFIED,
            RetryKind.NOT_APPLICABLE,
        )

    # I10-I12: Unknown key_id, anchor window expired, wrong domain prefix, bit flip, substitution
    _assert_refusal(
        _make_verifier(
            authority_bytes=signed_envelope(
                KIND_AUTHORITY, {**AUTHORITY_RECORD_1, "key_id": "ed25519:unknown"}
            )
        ).verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),
        RefusalCode.ISSUER_UNVERIFIED,
        RetryKind.NOT_APPLICABLE,
    )
    expired_anchor = AnchorTable(
        clock_domain=CLOCK,
        entries=(replace(ANCHORS_1.entries[0], valid_until="5000"),),
    )
    _assert_refusal(
        _make_verifier(anchors=expired_anchor).verify(
            REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
        ),
        RefusalCode.ISSUER_UNVERIFIED,
        RetryKind.NOT_APPLICABLE,
    )
    sig_bytes = bytearray(sign_record(KIND_AUTHORITY, AUTHORITY_RECORD_1))
    sig_bytes[0] ^= 0x01
    for bad_signed in (
        make_envelope(AUTHORITY_RECORD_1, sign_record(KIND_STATUS, AUTHORITY_RECORD_1)),
        make_envelope(AUTHORITY_RECORD_1, bytes(sig_bytes)),
        signed_envelope(
            KIND_AUTHORITY, {**AUTHORITY_RECORD_1, "record_id": "auth:other"}
        ),
        signed_envelope(
            KIND_AUTHORITY,
            {**AUTHORITY_RECORD_1, "authority_revision": "auth-rev-other"},
        ),
    ):
        _assert_refusal(
            _make_verifier(authority_bytes=bad_signed).verify(
                REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
            ),
            RefusalCode.ISSUER_UNVERIFIED,
            RetryKind.NOT_APPLICABLE,
        )


def test_n1_refusal_twins_r1_to_r7() -> None:
    """Twins R1-R7: revocation status availability, schema, anchor, signature, freshness window, high-water rollback/equivocation, and listing."""
    # R1: Status store unavailable or missing
    _assert_refusal(
        _make_verifier(statuses_unavailable=True).verify(
            REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
        ),
        RefusalCode.AUTHORITY_UNAVAILABLE,
        RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
    )
    _assert_refusal(
        Ed25519IssuerVerifier(
            anchors=ANCHORS_1,
            records={REF_1: signed_envelope(KIND_AUTHORITY, AUTHORITY_RECORD_1)},
            statuses={},
        ).verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),
        RefusalCode.AUTHORITY_UNAVAILABLE,
        RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
    )

    # R2-R5: Malformed status, bad anchor/issuer, bad signature, stale/future status window
    bad_status_sig = bytearray(sign_record(KIND_STATUS, STATUS_RECORD_1))
    bad_status_sig[0] ^= 0x01
    for bad_status in (
        b"not-json",
        signed_envelope(KIND_STATUS, {**STATUS_RECORD_1, "schema": "bad"}),
        signed_envelope(KIND_STATUS, {**STATUS_RECORD_1, "issuer_id": "issuer:other"}),
        signed_envelope(KIND_STATUS, {**STATUS_RECORD_1, "key_id": "ed25519:unknown"}),
        make_envelope(STATUS_RECORD_1, sign_record(KIND_AUTHORITY, STATUS_RECORD_1)),
        make_envelope(STATUS_RECORD_1, bytes(bad_status_sig)),
        signed_envelope(KIND_STATUS, {**STATUS_RECORD_1, "issued_at": "5001"}),
        signed_envelope(KIND_STATUS, {**STATUS_RECORD_1, "next_update": "5000"}),
    ):
        _assert_refusal(
            _make_verifier(status_bytes=bad_status).verify(
                REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
            ),
            RefusalCode.AUTHORITY_UNAVAILABLE,
            RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
        )

    # R6: High-water rollback (revision 7 -> 6) and equivocation (revision 7 with different bytes)
    v_hw = _make_verifier()
    assert isinstance(
        v_hw.verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000), AcceptedData
    )
    v_hw.statuses.items[ISSUER_ID] = signed_envelope(
        KIND_STATUS, {**STATUS_RECORD_1, "revocation_revision": "6"}
    )
    _assert_refusal(
        v_hw.verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),
        RefusalCode.AUTHORITY_UNAVAILABLE,
        RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
    )
    v_hw.statuses.items[ISSUER_ID] = signed_envelope(
        KIND_STATUS, {**STATUS_RECORD_1, "next_update": "9001"}
    )
    _assert_refusal(
        v_hw.verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),
        RefusalCode.AUTHORITY_UNAVAILABLE,
        RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
    )

    # R7: Listed (record_id, authority_revision) -> AUTHORITY_REVOKED (NEW_BINDING_REQUIRED); other revision -> AcceptedData
    revoked_exact = signed_envelope(
        KIND_STATUS,
        {
            **STATUS_RECORD_1,
            "revoked": [
                {"record_id": "auth:record-1", "authority_revision": "auth-rev-1"}
            ],
        },
    )
    _assert_refusal(
        _make_verifier(status_bytes=revoked_exact).verify(
            REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
        ),
        RefusalCode.AUTHORITY_REVOKED,
        RetryKind.NEW_BINDING_REQUIRED,
    )
    revoked_other_rev = signed_envelope(
        KIND_STATUS,
        {
            **STATUS_RECORD_1,
            "revoked": [
                {"record_id": "auth:record-1", "authority_revision": "auth-rev-0"}
            ],
        },
    )
    assert isinstance(
        _make_verifier(status_bytes=revoked_other_rev).verify(
            REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000
        ),
        AcceptedData,
    )


def test_n1_refusal_twins_w1_s1_p1_p2_e1_e2_c1_to_c5_and_precedence_x1_to_x4() -> None:
    """Twins W1, S1, P1-P2, E1-E2, C1-C5, and multi-fault precedence X1-X4."""
    verifier = _make_verifier()

    # W1: Authority record outside [not_before, expires_at) -> AUTHORITY_EXPIRED (NEW_BINDING_REQUIRED); boundaries 1000 and 9999 accept
    fresh_wide_status = signed_envelope(
        KIND_STATUS, {**STATUS_RECORD_1, "issued_at": "0", "next_update": "20000"}
    )
    v_wide = _make_verifier(status_bytes=fresh_wide_status)
    for good_reading in ("1000", "9999"):
        assert isinstance(
            v_wide.verify(
                REF_1,
                PEER_1,
                SUBJECT_1,
                EFFECTS_1,
                TrustedInstant(
                    clock_domain=CLOCK,
                    reading=good_reading,
                    witness=FakeWitness("w"),
                ),
            ),
            AcceptedData,
        )
    for bad_reading in ("999", "10000"):
        _assert_refusal(
            v_wide.verify(
                REF_1,
                PEER_1,
                SUBJECT_1,
                EFFECTS_1,
                TrustedInstant(
                    clock_domain=CLOCK,
                    reading=bad_reading,
                    witness=FakeWitness("w"),
                ),
            ),
            RefusalCode.AUTHORITY_EXPIRED,
            RetryKind.NEW_BINDING_REQUIRED,
        )

    # S1: Subject mismatch or unprojectable subject -> SUBJECT_MISMATCH
    for bad_subject in (
        replace(SUBJECT_1, selection_revision="sel-other"),
        replace(
            SUBJECT_1,
            subject=FutureSubjectRecord(selected_scope_reference="scope:other"),
        ),
        replace(
            SUBJECT_1,
            subject=ExistingSubjectRecord(
                identity=FakeProcessRef("proc:worker-test-1")
            ),
        ),
        "not-a-subject",
    ):
        _assert_refusal(
            verifier.verify(REF_1, PEER_1, bad_subject, EFFECTS_1, AT_5000),  # type: ignore[arg-type]
            RefusalCode.SUBJECT_MISMATCH,
            RetryKind.NOT_APPLICABLE,
        )

    # P1: Empty peer_registration, empty process_registration, or duck-typed process_reference without process_registration -> PEER_UNVERIFIED
    @dataclass(frozen=True)
    class _DuckProc:
        process_reference: str = "proc:worker-test-1"

    for bad_peer in (
        FakePeer("", FakeProcessRef("proc:worker-test-1")),
        FakePeer("peer:worker-test-1", FakeProcessRef("")),
        FakePeer("peer:worker-test-1", _DuckProc()),  # type: ignore[arg-type]
    ):
        _assert_refusal(
            verifier.verify(REF_1, bad_peer, SUBJECT_1, EFFECTS_1, AT_5000),
            RefusalCode.PEER_UNVERIFIED,
            RetryKind.NOT_APPLICABLE,
        )

    # P2: Non-empty peer whose process_registration is not in record["actors"] -> SUBJECT_MISMATCH
    _assert_refusal(
        verifier.verify(
            REF_1,
            FakePeer("peer:worker-test-1", FakeProcessRef("proc:other")),
            SUBJECT_1,
            EFFECTS_1,
            AT_5000,
        ),
        RefusalCode.SUBJECT_MISMATCH,
        RetryKind.NOT_APPLICABLE,
    )

    # E1 & E2: Malformed/empty effects or non-subset operation -> SCOPE_MISMATCH.
    # The mixed set (one granted, one not) and the revision-only change bite a
    # loosened subset check (any() instead of all(), or a match without revision).
    op_foreign = SelectedOperation(
        domain="C_BEFORE_COUNT",
        operation="C_BEFORE_COUNT",
        revision="op-rev-1",
    )
    for bad_effects in (
        frozenset(),
        (OP_ARM,),
        frozenset({op_foreign}),
        frozenset({OP_ARM, op_foreign}),
        frozenset({replace(OP_ARM, revision="op-rev-other")}),
    ):
        _assert_refusal(
            verifier.verify(REF_1, PEER_1, SUBJECT_1, bad_effects, AT_5000),  # type: ignore[arg-type]
            RefusalCode.SCOPE_MISMATCH,
            RetryKind.NOT_APPLICABLE,
        )

    # C1-C3: Foreign condition authority, unknown condition_id, revision mismatch -> CONDITIONS_UNMET
    for bad_cond in (
        {
            "authority": {
                "authority_revision": "auth-rev-other",
                "issuer_id": ISSUER_ID,
                "record_id": "auth:record-1",
            },
            "condition_id": "mode:external-db-fresh",
            "revision": "1",
        },
        {
            "authority": {
                "authority_revision": "auth-rev-1",
                "issuer_id": ISSUER_ID,
                "record_id": "auth:record-1",
            },
            "condition_id": "mode:unknown",
            "revision": "1",
        },
        {
            "authority": {
                "authority_revision": "auth-rev-1",
                "issuer_id": ISSUER_ID,
                "record_id": "auth:record-1",
            },
            "condition_id": "mode:external-db-fresh",
            "revision": "2",
        },
    ):
        _assert_refusal(
            _make_verifier(
                authority_bytes=signed_envelope(
                    KIND_AUTHORITY, {**AUTHORITY_RECORD_1, "conditions": [bad_cond]}
                )
            ).verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),
            RefusalCode.CONDITIONS_UNMET,
            RetryKind.NOT_APPLICABLE,
        )

    # X1: Bad signature + missing status + expired + bad subject -> ISSUER_UNVERIFIED
    sig_flip = bytearray(sign_record(KIND_AUTHORITY, AUTHORITY_RECORD_1))
    sig_flip[0] ^= 0x01
    _assert_refusal(
        Ed25519IssuerVerifier(
            anchors=ANCHORS_1,
            records={REF_1: make_envelope(AUTHORITY_RECORD_1, bytes(sig_flip))},
            statuses={},
        ).verify(
            REF_1,
            FakePeer("", FakeProcessRef("")),
            replace(SUBJECT_1, selection_revision="sel-other"),
            frozenset(),
            TrustedInstant(
                clock_domain=CLOCK, reading="10000", witness=FakeWitness("w")
            ),
        ),
        RefusalCode.ISSUER_UNVERIFIED,
        RetryKind.NOT_APPLICABLE,
    )

    # X2: Valid signature + missing status + expired + bad subject -> AUTHORITY_UNAVAILABLE
    _assert_refusal(
        Ed25519IssuerVerifier(
            anchors=ANCHORS_1,
            records={REF_1: signed_envelope(KIND_AUTHORITY, AUTHORITY_RECORD_1)},
            statuses={},
        ).verify(
            REF_1,
            FakePeer("", FakeProcessRef("")),
            replace(SUBJECT_1, selection_revision="sel-other"),
            frozenset(),
            TrustedInstant(
                clock_domain=CLOCK, reading="10000", witness=FakeWitness("w")
            ),
        ),
        RefusalCode.AUTHORITY_UNAVAILABLE,
        RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
    )

    # X3: Valid signature + revoked + expired + bad subject -> AUTHORITY_REVOKED
    revoked_wide = signed_envelope(
        KIND_STATUS,
        {
            **STATUS_RECORD_1,
            "issued_at": "0",
            "next_update": "20000",
            "revoked": [
                {"record_id": "auth:record-1", "authority_revision": "auth-rev-1"}
            ],
        },
    )
    _assert_refusal(
        _make_verifier(status_bytes=revoked_wide).verify(
            REF_1,
            FakePeer("", FakeProcessRef("")),
            replace(SUBJECT_1, selection_revision="sel-other"),
            frozenset(),
            TrustedInstant(
                clock_domain=CLOCK, reading="10000", witness=FakeWitness("w")
            ),
        ),
        RefusalCode.AUTHORITY_REVOKED,
        RetryKind.NEW_BINDING_REQUIRED,
    )

    # X4: Valid signature + fresh status + expired + bad subject + bad peer -> AUTHORITY_EXPIRED
    _assert_refusal(
        v_wide.verify(
            REF_1,
            FakePeer("", FakeProcessRef("")),
            replace(SUBJECT_1, selection_revision="sel-other"),
            frozenset(),
            TrustedInstant(
                clock_domain=CLOCK, reading="10000", witness=FakeWitness("w")
            ),
        ),
        RefusalCode.AUTHORITY_EXPIRED,
        RetryKind.NEW_BINDING_REQUIRED,
    )


def test_guard_bite_empty_identity_never_matches_in_peer_or_process_checks() -> None:
    """Guard bite: empty process_registration or peer_registration never compares equal ("" == "" -> refused)."""
    empty_proc_a = FakeProcessRef("")
    empty_proc_b = FakeProcessRef("")
    empty_peer = FakePeer("", empty_proc_b)

    # Pinning or revoking a peer without both registrations fails loud; it is never
    # silently dropped from the pinned table.
    for unpinnable in (
        empty_peer,
        FakePeer("peer:non-empty", empty_proc_b),
        FakePeer("", PEER_1.process),
    ):
        with pytest.raises(PinnedPeerInvalid):
            PinnedPeerVerifier((unpinnable,))
        with pytest.raises(PinnedPeerInvalid):
            PinnedPeerVerifier((PEER_1,)).revoke_peer(unpinnable)

    pinned_verifier = PinnedPeerVerifier((PEER_1,))
    assert pinned_verifier.verify_peer(PEER_1)
    assert not pinned_verifier.verify_peer(empty_peer)
    assert not pinned_verifier.verify_peer(
        FakePeer(PEER_1.peer_registration, empty_proc_b)
    )
    assert not pinned_verifier.verify_peer(FakePeer("", PEER_1.process))

    in_mem_peer_verifier = InMemoryPeerVerifier((empty_peer,))
    assert not in_mem_peer_verifier.verify_peer(empty_peer)

    rig = make_populated_test_rig()
    in_mem_issuer = InMemoryIssuerVerifier()
    in_mem_issuer.register_authority(
        AUTHORITY_REF_1,
        make_verified_authority(
            subject=SUBJECT_1,
            actors=(empty_proc_a,),
            operations=EFFECTS_1,
        ),
        job=rig.running_job,
    )
    _assert_refusal(
        in_mem_issuer.verify(
            AUTHORITY_REF_1,
            FakePeer("peer:non-empty", empty_proc_b),
            SUBJECT_1,
            EFFECTS_1,
            AT_5000,
        ),
        RefusalCode.PEER_UNVERIFIED,
        RetryKind.NOT_APPLICABLE,
    )


def test_guard_bite_integer_only_time_comparison_rejects_lexicographical_string_order() -> (
    None
):
    """Guard bite: integer-only TrustedInstant comparison catches string-order traps ('100' <= '15' < '200' and '20' <= '150' < '200')."""
    rec_trap = {
        **AUTHORITY_RECORD_1,
        "not_before": "20",
        "expires_at": "200",
    }
    env_trap = signed_envelope(KIND_AUTHORITY, rec_trap)
    env_s = signed_envelope(
        KIND_STATUS, {**STATUS_RECORD_1, "issued_at": "10", "next_update": "300"}
    )
    verifier = _make_verifier(authority_bytes=env_trap, status_bytes=env_s)

    # In string order "20" <= "15" is False and "100" <= "15" < "200" is True; in integer order 15 < 20 is expired!
    _assert_refusal(
        verifier.verify(
            REF_1,
            PEER_1,
            SUBJECT_1,
            EFFECTS_1,
            TrustedInstant(clock_domain=CLOCK, reading="15", witness=FakeWitness("w")),
        ),
        RefusalCode.AUTHORITY_EXPIRED,
        RetryKind.NEW_BINDING_REQUIRED,
    )
    # In string order "20" <= "150" is False ('2' > '1'), but integer 20 <= 150 < 200 is valid!
    res_valid = verifier.verify(
        REF_1,
        PEER_1,
        SUBJECT_1,
        EFFECTS_1,
        TrustedInstant(clock_domain=CLOCK, reading="150", witness=FakeWitness("w")),
    )
    assert isinstance(res_valid, AcceptedData)

    # Same integer-only trap on InMemoryIssuerVerifier:
    rig = make_populated_test_rig()
    in_mem = InMemoryIssuerVerifier()
    in_mem.register_authority(
        AUTHORITY_REF_1,
        make_verified_authority(
            subject=SUBJECT_1,
            actors=(PEER_1.process,),
            operations=EFFECTS_1,
            not_before=TrustedInstant(
                clock_domain=CLOCK, reading="20", witness=FakeWitness("w")
            ),
            expires_at=TrustedInstant(
                clock_domain=CLOCK, reading="200", witness=FakeWitness("w")
            ),
        ),
        job=rig.running_job,
    )
    _assert_refusal(
        in_mem.verify(
            AUTHORITY_REF_1,
            PEER_1,
            SUBJECT_1,
            EFFECTS_1,
            TrustedInstant(clock_domain=CLOCK, reading="15", witness=FakeWitness("w")),
        ),
        RefusalCode.AUTHORITY_EXPIRED,
        RetryKind.NEW_BINDING_REQUIRED,
    )
    assert isinstance(
        in_mem.verify(
            AUTHORITY_REF_1,
            PEER_1,
            SUBJECT_1,
            EFFECTS_1,
            TrustedInstant(clock_domain=CLOCK, reading="150", witness=FakeWitness("w")),
        ),
        AcceptedData,
    )


def test_guard_bite_registry_enforces_snapshot_verified_at_condition_and_revocation_checks() -> (
    None
):
    """Guard bite: AuthorityRegistryService passes snapshot.verified_at and enforces C4/C5 condition evaluation."""
    rig = make_populated_test_rig()
    seen_instants: list[TrustedInstant] = []

    class _SpyIssuerVerifier:
        def __init__(self, delegate: InMemoryIssuerVerifier) -> None:
            self._delegate = delegate

        def verify(
            self,
            ref: AuthorityRef,
            peer: Any,
            subject: SelectedSubject,
            effects: Any,
            at: TrustedInstant,
        ) -> Any:
            seen_instants.append(at)
            return self._delegate.verify(ref, peer, subject, effects, at)

    reg = AuthorityRegistryService(
        snapshot_provider=rig.publisher.reader(),
        issuer_verifier=_SpyIssuerVerifier(rig.issuer_verifier),  # type: ignore[arg-type]
        peer_verifier=rig.peer_verifier,
        history_provider=InMemoryRequestHistoryProvider(),
    )
    res = reg.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res, AcceptedData)
    assert seen_instants == [rig.snapshot.verified_at, rig.snapshot.verified_at]

    # C4 & C5 registry-level condition evaluation:
    verified = make_verified_authority(
        subject=SUBJECT_1,
        actors=(PEER_1.process,),
        operations=EFFECTS_1,
        conditions=(
            ConditionRef(
                authority=AUTHORITY_REF_1,
                condition_id="mode:external-db-fresh",
                revision="1",
            ),
        ),
    )
    verified_map = {
        rig.running_job.selector_issuer: verified,
        AUTHORITY_REF_1: verified,
        AUTHORITY_REF_2: verified,
    }
    assert (
        evaluate_registry_conditions(
            rig.running_job,
            verified_map,
            predicates={"mode:external-db-fresh": lambda _job: False},
        )
        == "C4"
    )
    extra_cond = ConditionRef(
        authority=AUTHORITY_REF_1,
        condition_id="mode:external-db-fresh",
        revision="999",
    )
    job_missing_cond = replace(rig.running_job, conditions=(extra_cond,))
    assert evaluate_registry_conditions(job_missing_cond, verified_map) == "C5"
    job_nontuple_cond = replace(
        rig.running_job,
        conditions=frozenset({extra_cond}),  # type: ignore[arg-type]
    )
    assert evaluate_registry_conditions(job_nontuple_cond, verified_map) == "C5"

    # T-PH-B & T-PH-C: Registry re-stamps Phase.A verifier refusals to boundary_to_phase(boundary)
    reg_empty_anchors = AuthorityRegistryService(
        snapshot_provider=rig.publisher.reader(),
        issuer_verifier=Ed25519IssuerVerifier(anchors=PRODUCTION_ANCHOR_TABLE),
        peer_verifier=rig.peer_verifier,
        history_provider=InMemoryRequestHistoryProvider(),
    )
    res_b = reg_empty_anchors.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "B_PRE_REQUEST",
        default_effect_for_job(rig.running_job, "B_PRE_REQUEST"),
    )
    assert isinstance(res_b, Refusal)
    assert res_b.code is RefusalCode.ISSUER_UNVERIFIED
    assert res_b.retry_kind is RetryKind.NOT_APPLICABLE
    assert res_b.phase is Phase.B
    res_c = reg_empty_anchors.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "C_BEFORE_COUNT",
        default_effect_for_job(rig.running_job, "C_BEFORE_COUNT"),
    )
    assert isinstance(res_c, Refusal)
    assert res_c.code is RefusalCode.ISSUER_UNVERIFIED
    assert res_c.retry_kind is RetryKind.NOT_APPLICABLE
    assert res_c.phase is Phase.C


def test_guard_bite_candidate_bindings_never_accepted_as_authority_and_file_filter_refused() -> (
    None
):
    """Guard bite: P3CandidateBindings is refused as an AuthorityRef, and ScriptAgent '| file' remains refused in P3 launch."""
    from temper_ai.agent.script_agent import ScriptAgent

    verifier = _make_verifier()
    candidate_bindings = P3CandidateBindings()
    _assert_refusal(
        verifier.verify(
            candidate_bindings,  # type: ignore[arg-type]
            PEER_1,
            SUBJECT_1,
            EFFECTS_1,
            AT_5000,
        ),
        RefusalCode.AUTHORITY_UNBOUND,
        RetryKind.NOT_APPLICABLE,
    )

    agent = ScriptAgent(
        {
            "name": "a1",
            "type": "script",
            "p3_protected_launch": True,
            "script_template": "cat {{ secret_payload | file }}",
        }
    )
    errors = agent.validate_config()
    assert any("| file" in err for err in errors)


class _AcceptAllPeerVerifier:
    """Peer verifier double that admits every peer, so the registry's own checks decide."""

    def verify_peer(self, peer: Any) -> bool:
        return True


class _TamperingIssuerVerifier:
    """Faulty IssuerVerifier double: changes the accepted result for one ref.

    It stands in for a wrong verifier implementation, so the registry's own
    re-checks of every verifier result (N1-SPEC 4.5, defense in depth) must catch it.
    """

    def __init__(
        self,
        delegate: InMemoryIssuerVerifier,
        target: AuthorityRef,
        tamper: Any,
    ) -> None:
        self._delegate = delegate
        self._target = target
        self._tamper = tamper

    def verify(
        self,
        ref: AuthorityRef,
        peer: Any,
        subject: SelectedSubject,
        effects: Any,
        at: TrustedInstant,
    ) -> Any:
        result = self._delegate.verify(ref, peer, subject, effects, at)
        if ref != self._target or not isinstance(result, AcceptedData):
            return result
        return AcceptedData(data=self._tamper(result.data), evidence=result.evidence)


@dataclass(frozen=True)
class _ReferenceOnlyProcess:
    """Duck-typed process carrying only ``process_reference``, no ``process_registration``."""

    process_reference: str


def test_guard_bite_registry_rechecks_every_verifier_result_for_selector_and_authorities() -> (
    None
):
    """Guard bite: the registry re-checks each verifier result (selector and every authority ref).

    Type -> ISSUER_UNVERIFIED, subject -> SUBJECT_MISMATCH, missing or empty actor ->
    PEER_UNVERIFIED (rows P1-P2), foreign actor -> SUBJECT_MISMATCH, intended effect
    -> SCOPE_MISMATCH; a peer process without a strict ``process_registration`` ->
    PEER_UNVERIFIED. The untampered twin is accepted.
    """
    rig = make_populated_test_rig()
    job = rig.pre_dispatch_job
    assert job.authority_refs

    def _registry(issuer_verifier: Any, peer_verifier: Any) -> AuthorityRegistryService:
        return AuthorityRegistryService(
            snapshot_provider=rig.publisher.reader(),
            issuer_verifier=issuer_verifier,
            peer_verifier=peer_verifier,
            history_provider=InMemoryRequestHistoryProvider(),
        )

    tampers: list[tuple[str, Any, RefusalCode]] = [
        ("not VerifiedAuthority", lambda data: object(), RefusalCode.ISSUER_UNVERIFIED),
        (
            "foreign subject",
            lambda data: replace(data, subject=SUBJECT_1),
            RefusalCode.SUBJECT_MISMATCH,
        ),
        (
            "no actors",
            lambda data: replace(data, actors=()),
            RefusalCode.PEER_UNVERIFIED,
        ),
        (
            "empty actor identity",
            lambda data: replace(data, actors=(FakeProcessRef(""),)),
            RefusalCode.PEER_UNVERIFIED,
        ),
        (
            "foreign actor",
            lambda data: replace(data, actors=(FakeProcessRef("proc:someone-else"),)),
            RefusalCode.SUBJECT_MISMATCH,
        ),
        (
            "effect not granted",
            lambda data: replace(data, operations=frozenset()),
            RefusalCode.SCOPE_MISMATCH,
        ),
    ]
    for target in (job.selector_issuer, job.authority_refs[0]):
        untampered = _registry(
            _TamperingIssuerVerifier(rig.issuer_verifier, target, lambda data: data),
            rig.peer_verifier,
        ).for_submit(rig.peer_submit, "designated_v1")
        assert isinstance(untampered, AcceptedData), (target, untampered)
        for label, tamper, expected_code in tampers:
            result = _registry(
                _TamperingIssuerVerifier(rig.issuer_verifier, target, tamper),
                rig.peer_verifier,
            ).for_submit(rig.peer_submit, "designated_v1")
            assert isinstance(result, Refusal), (target, label, result)
            assert result.code is expected_code, (target, label, result.code)
            assert result.retry_kind is RetryKind.NOT_APPLICABLE, (target, label)

    # Peer side of rows P1-P2: a process known only by ``process_reference`` passes the
    # loose pre-check, a permissive peer verifier and a faulty issuer verifier that
    # ignores the peer it is given, but the registry's actor re-check refuses it.
    class _PeerIgnoringIssuerVerifier:
        def verify(
            self,
            ref: AuthorityRef,
            peer: Any,
            subject: SelectedSubject,
            effects: Any,
            at: TrustedInstant,
        ) -> Any:
            return rig.issuer_verifier.verify(
                ref, rig.peer_submit, subject, effects, at
            )

    reference_only_peer = FakePeer(
        rig.peer_submit.peer_registration,
        _ReferenceOnlyProcess(rig.peer_submit.process.process_registration),  # type: ignore[arg-type]
    )
    result = _registry(
        _PeerIgnoringIssuerVerifier(), _AcceptAllPeerVerifier()
    ).for_submit(reference_only_peer, "designated_v1")
    assert isinstance(result, Refusal), result
    assert result.code is RefusalCode.PEER_UNVERIFIED
    assert result.retry_kind is RetryKind.NOT_APPLICABLE


def test_guard_bite_strict_identity_match_never_pairs_empty_identities() -> None:
    """Guard bite: the strict identity match itself refuses empty identities, not only its callers."""
    from temper_ai.p3_authority.registry import (
        _same_non_empty_proc_ref,
        _same_strict_proc_registration,
    )

    for same in (_same_strict_proc_registration, _same_non_empty_proc_ref):
        assert not same(FakeProcessRef(""), FakeProcessRef(""))
        assert not same(FakeProcessRef("proc:a"), FakeProcessRef(""))
        assert not same(FakeProcessRef(""), FakeProcessRef("proc:a"))
        assert not same(FakeProcessRef("proc:a"), FakeProcessRef("proc:b"))
        assert same(FakeProcessRef("proc:a"), FakeProcessRef("proc:a"))
    assert not _same_strict_proc_registration(
        _ReferenceOnlyProcess("proc:a"), _ReferenceOnlyProcess("proc:a")
    )


def test_guard_bite_production_issuer_module_is_verify_only() -> None:
    """Guard bite: the production module holds no private key and no signing function (C2)."""
    import inspect

    import temper_ai.p3_authority.issuer_verifier as issuer_module

    source = inspect.getsource(issuer_module)
    assert "Ed25519PrivateKey" not in source
    assert RFC8032_TEST1_SECRET_KEY_HEX not in source
    assert TEST2_SEED_HEX not in source
    assert not [
        name
        for name in dir(issuer_module)
        if name.startswith("sign_") or name in {"signed_envelope", "make_envelope"}
    ]
    assert PRODUCTION_TRUST_ANCHORS == ()
    assert PRODUCTION_ANCHOR_TABLE.entries == ()


def test_guard_bite_compose_refuses_conflicting_issuer_and_peer_inputs() -> None:
    """Guard bite: compose_p3_authority never silently ignores the issuer parts or pinned_peers."""
    given_registry = compose_p3_authority().registry
    conflicting_inputs: tuple[tuple[str, dict[str, Any]], ...] = (
        (
            "issuer_verifier",
            {
                "issuer_verifier": Ed25519IssuerVerifier(),
                "issuer_anchors": PRODUCTION_ANCHOR_TABLE,
            },
        ),
        (
            "issuer_verifier",
            {"issuer_verifier": Ed25519IssuerVerifier(), "issuer_records": {}},
        ),
        (
            "issuer_verifier",
            {"issuer_verifier": Ed25519IssuerVerifier(), "issuer_statuses": {}},
        ),
        (
            "issuer_verifier",
            {"issuer_verifier": Ed25519IssuerVerifier(), "issuer_condition_table": {}},
        ),
        (
            "pinned_peers",
            {"peer_verifier": PinnedPeerVerifier((PEER_1,)), "pinned_peers": (PEER_1,)},
        ),
        (
            "registry",
            {"registry": given_registry, "issuer_anchors": PRODUCTION_ANCHOR_TABLE},
        ),
        ("registry", {"registry": given_registry, "pinned_peers": (PEER_1,)}),
    )
    for named, kwargs in conflicting_inputs:
        with pytest.raises(ValueError, match=named):
            compose_p3_authority(**kwargs)

    # Positive twins: each input alone still composes, writes stay disabled, and the
    # empty production anchor table still refuses every issuer.
    for kwargs in (
        {"issuer_anchors": PRODUCTION_ANCHOR_TABLE},
        {"issuer_records": {}},
        {"pinned_peers": (PEER_1,)},
        {"issuer_verifier": Ed25519IssuerVerifier()},
        {"peer_verifier": PinnedPeerVerifier((PEER_1,))},
        {"registry": given_registry},
    ):
        composed = compose_p3_authority(**kwargs)
        assert composed.service._writes_enabled is False


def test_guard_bite_small_order_and_noncanonical_keys_never_verify() -> None:
    """N1-SPEC r2 2.3: ``cryptography`` loads small-order keys and accepts a forged
    signature (small-order R, S = 0) under them. The key rule refuses them at
    construction and in ``verify_ed25519_hex``, even in a table changed after it."""
    # The module's five y values are the spec's, and each is the y of a point of
    # order dividing 8: y = 1 (order 1), y = p - 1 (order 2), y = 0 (order 4), and
    # the two order-8 values solve d*y^4 + 2*y^2 - 1 = 0 (doubling gives y = 0).
    p = ED25519_FIELD_PRIME
    assert p == 2**255 - 19
    assert ED25519_SMALL_ORDER_Y == frozenset(SPEC_SMALL_ORDER_Y)
    d = (-121665 * pow(121666, -1, p)) % p
    order8 = set(SPEC_SMALL_ORDER_Y) - {0, 1, p - 1}
    assert {0, 1, p - 1} <= set(SPEC_SMALL_ORDER_Y) and len(order8) == 2
    assert all((d * pow(y, 4, p) + 2 * pow(y, 2, p) - 1) % p == 0 for y in order8)

    # Under the identity key, R = identity and S = 0 pass cryptography's check for
    # every message; verify_ed25519_hex refuses the key whatever the signature.
    forged = bytes.fromhex(IDENTITY_POINT_HEX) + bytes(32)
    signed_record = domain_prefix(KIND_AUTHORITY) + canonical_bytes(AUTHORITY_RECORD_1)
    for message in (b"", b"N1 forged authority", signed_record):
        assert not verify_ed25519_hex(IDENTITY_POINT_HEX, forged, message)
        assert not verify_ed25519_hex(IDENTITY_POINT_HEX, forged.hex(), message)
    for y in SPEC_SMALL_ORDER_Y:
        for sign in (0, 1):
            assert public_key_problem(_key_hex(y, sign)) == "public_key_small_order"
            assert not verify_ed25519_hex(_key_hex(y, sign), forged, b"probe")
    assert public_key_problem(_key_hex(p + 2)) == "public_key_noncanonical"
    # A valid key with its sign bit set still verifies its RFC 8032 vector.
    assert verify_ed25519_hex(
        RFC8032_SHA_ABC_PUBLIC_KEY_HEX,
        RFC8032_SHA_ABC_SIGNATURE_HEX,
        hashlib.sha512(b"abc").digest(),
    )

    # A table whose entry is swapped for the identity key after construction:
    # forged record and status envelopes still refuse at I11.
    planted_table = AnchorTable(clock_domain=CLOCK, entries=ANCHORS_1.entries)
    planted = _make_verifier(
        anchors=planted_table,
        authority_bytes=make_envelope(AUTHORITY_RECORD_1, forged),
        status_bytes=make_envelope(STATUS_RECORD_1, forged),
    )
    object.__setattr__(
        planted_table,
        "entries",
        (replace(ANCHORS_1.entries[0], public_key=IDENTITY_POINT_HEX),),
    )
    _assert_refusal(
        planted.verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000),
        RefusalCode.ISSUER_UNVERIFIED,
        RetryKind.NOT_APPLICABLE,
    )


def test_guard_bite_subject_projection_accepts_only_exact_types() -> None:
    """N1-SPEC 3.3: only an exact SelectedSubject, PreDispatchJob, JobKey and
    DispatchIdentity project. A look-alike class with the same name and fields
    refuses SUBJECT_MISMATCH where its projection would match the signed subject."""

    def _look_alike(name: str, *fields: str) -> type:
        cls: type = dataclass(frozen=True)(
            type(name, (), {"__annotations__": dict.fromkeys(fields, object)})
        )
        cls.__qualname__ = name
        return cls

    look_alike_dispatch = _LookAlikeDispatchIdentity(
        execution_uuid=DISPATCH_1.execution_uuid,
        dispatch_nonce=DISPATCH_1.dispatch_nonce,
        running_attempt=1,
    )
    look_alike_job_key = _look_alike("JobKey", "dispatch", "job_revision")
    look_alike_subject = _look_alike(
        "SelectedSubject", "subject", "job", "selection_revision"
    )
    verifier = _make_verifier()
    assert isinstance(
        verifier.verify(REF_1, PEER_1, SUBJECT_1, EFFECTS_1, AT_5000), AcceptedData
    )
    for subject in (
        replace(
            SUBJECT_1,
            job=JobKey(dispatch=look_alike_dispatch, job_revision="job-rev-run-1"),  # type: ignore[arg-type]
        ),
        replace(SUBJECT_1, job=look_alike_job_key(DISPATCH_1, "job-rev-run-1")),
        look_alike_subject(
            SUBJECT_1.subject, SUBJECT_1.job, SUBJECT_1.selection_revision
        ),
    ):
        _assert_refusal(
            _make_verifier().verify(REF_1, PEER_1, subject, EFFECTS_1, AT_5000),  # type: ignore[arg-type]
            RefusalCode.SUBJECT_MISMATCH,
            RetryKind.NOT_APPLICABLE,
        )

    # Pre-dispatch job: the exact type verifies, a look-alike refuses.
    pre_job = PreDispatchJob(
        execution_uuid=DISPATCH_1.execution_uuid,
        designated_workflow="designated_v1",
        descriptor_digest="0" * 64,
        job_revision="job-rev-pre-1",
    )
    pre_record = {
        **AUTHORITY_RECORD_1,
        "subject": {
            **AUTHORITY_RECORD_1["subject"],
            "job": {
                "kind": "pre-dispatch",
                "execution_uuid": pre_job.execution_uuid,
                "designated_workflow": pre_job.designated_workflow,
                "descriptor_digest": pre_job.descriptor_digest,
                "job_revision": pre_job.job_revision,
            },
        },
    }
    look_alike_pre_job = _look_alike(
        "PreDispatchJob",
        "execution_uuid",
        "designated_workflow",
        "descriptor_digest",
        "job_revision",
    )
    for job, accepted in (
        (pre_job, True),
        (
            look_alike_pre_job(
                pre_job.execution_uuid,
                pre_job.designated_workflow,
                pre_job.descriptor_digest,
                pre_job.job_revision,
            ),
            False,
        ),
    ):
        result = _make_verifier(
            authority_bytes=signed_envelope(KIND_AUTHORITY, pre_record)
        ).verify(REF_1, PEER_1, replace(SUBJECT_1, job=job), EFFECTS_1, AT_5000)
        if accepted:
            assert isinstance(result, AcceptedData)
        else:
            _assert_refusal(
                result, RefusalCode.SUBJECT_MISMATCH, RetryKind.NOT_APPLICABLE
            )

    # Existing process subject: a str identity with the registration on the
    # subject itself is neither a process nor a root identity and refuses.
    process_record = {
        **AUTHORITY_RECORD_1,
        "subject": {
            **AUTHORITY_RECORD_1["subject"],
            "subject": {
                "kind": "existing-process",
                "process_registration": "proc:worker-test-1",
            },
        },
    }
    look_alike_existing = _look_alike(
        "ExistingSubjectRecord",
        "identity",
        "subject_kind",
        "process_registration",
        "filesystem_object",
    )
    for native, accepted in (
        (ExistingSubjectRecord(identity=FakeProcessRef("proc:worker-test-1")), True),
        (
            look_alike_existing(
                "proc:worker-test-1", "existing", "proc:worker-test-1", None
            ),
            False,
        ),
    ):
        result = _make_verifier(
            authority_bytes=signed_envelope(KIND_AUTHORITY, process_record)
        ).verify(REF_1, PEER_1, replace(SUBJECT_1, subject=native), EFFECTS_1, AT_5000)
        if accepted:
            assert isinstance(result, AcceptedData)
        else:
            _assert_refusal(
                result, RefusalCode.SUBJECT_MISMATCH, RetryKind.NOT_APPLICABLE
            )

    # running_attempt must be an exact int >= 1, even if changed after construction.
    for bad_attempt in (0, True):
        tampered = DispatchIdentity(
            execution_uuid=DISPATCH_1.execution_uuid,
            dispatch_nonce=DISPATCH_1.dispatch_nonce,
            running_attempt=1,
        )
        object.__setattr__(tampered, "running_attempt", bad_attempt)
        with pytest.raises(UnprojectableSubject, match="running_attempt"):
            project_job(JobKey(dispatch=tampered, job_revision="job-rev-run-1"))
