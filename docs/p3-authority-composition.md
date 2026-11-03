# P3 authority source composition

This document describes the **SOURCE-ONLY, UNLANDED** P3 T4 authority composition
modules under `temper_ai.p3_authority`. It builds directly on `#261`'s canonical
contract seam (`temper_ai.p3_authority.contract`) without modifying the shared
contract files, duplicating supplier types from `p3_host_contracts` or
`p3_source_closure`, or wiring default authority providers into production
API, CLI, or worker entrypoints.

All default constructors and `compose_p3_authority()` are **disabled by default**:
every provider defaults to `None`, `writes_enabled` is permanently `False`, and
every registry, candidate-binding, native-boundary, and host-join call fails
closed when its required provider is absent.

## Module map and ownership

| Module | Role |
| --- | --- |
| `temper_ai.p3_authority.issuer_verifier` | Verify-only module (no private key, no signing function): `Ed25519IssuerVerifier`, implementing the `IssuerVerifier` port, verifying signed `p3-issuer-authority/1` records and `p3-issuer-revocation/1` status envelopes over `temper-p3-issuer/v1\x00<kind>\x00<CAJ-1 canonical bytes>` against `AnchorTable` (`PRODUCTION_ANCHOR_TABLE` / `PRODUCTION_TRUST_ANCHORS` empty at T5 until owner consent `C2`), integer-only `TrustedInstant` window comparisons (`not_before <= at < expires_at`), closed `CONDITION_TABLE` evaluation, and `PinnedPeerVerifier` (`PeerVerifierProtocol`) for non-empty `AuthenticatedPeer` verification (pinning or revoking a peer without both non-empty registrations raises `PinnedPeerInvalid`). |
| `temper_ai.p3_authority.registry` | `AuthorityRegistryService` implementing `P3AuthorityRegistry` (`for_submit`, `for_run`, `check_current`, `bind_created`), immutable `SelectionSnapshot` / `DecisionEvidenceRecord` / subject records, read-only provider protocols (`SelectionSnapshotProvider`, `PeerVerifierProtocol`, `RequestHistoryProvider`), and explicit test-only doubles (`InMemorySelectionPublisher`, `InMemorySelectionSnapshotProvider`, `InMemoryIssuerVerifier`, `InMemoryPeerVerifier`, `InMemoryRequestHistoryProvider`). |
| `temper_ai.p3_authority.candidate_bindings` | `P3CandidateBindings` implementing `temper_ai.runner.admission.CandidateBindings`, plus `CandidateCaptureAdapter` and `StaticCallerPeerProvider`, delegating capture, install, rollback, snapshot restore, context binding, and `external-db-fresh` persistence to existing V1 primitives. |
| `temper_ai.p3_authority._providers` | Internal typed provider protocols (`EffectFenceProvider`, `QAReceivingVerifier`, `HostSessionPeerResolver`), `SystemsSourceClosureComparator` delegating to `p3_source_closure.compare_loaded_source`, and explicit test-only observer/provenance/fence doubles (`InMemoryHostObserver`, `InMemoryWorkerObserver`, `InMemoryRootObserver`, `InMemoryHostProvenance`, `InMemoryEffectFenceProvider`, `InMemoryQAReceivingVerifier`, `InMemoryHostSessionPeerResolver`). |
| `temper_ai.p3_authority.service` | `P3AuthorityService` implementing `P3NativeBoundary` (`before_create`, `before_checker`, `before_request`, `before_admit`, `before_execute`, `before_count`) and the nine `NativeHostJoin` methods, `NativeHostJoinAdapter` over the same service instance, `P3AuthorityComposition`, and the `compose_p3_authority(...)` factory. |

```python
from temper_ai.p3_authority.service import (
    AnchorEntry,
    AnchorTable,
    Ed25519IssuerVerifier,
    EnvelopeStore,
    NativeHostJoinAdapter,
    P3AuthorityComposition,
    P3AuthorityService,
    PRODUCTION_ANCHOR_TABLE,
    PinnedPeerVerifier,
    compose_p3_authority,
)
from temper_ai.p3_authority.issuer_verifier import CONDITION_TABLE
from temper_ai.p3_authority.registry import AuthorityRegistryService
from temper_ai.p3_authority.candidate_bindings import P3CandidateBindings
```

## Independent selection and issuer verification (`registry.py`)

- **Reader vs. publisher separation**: `AuthorityRegistryService` accepts only
  the read-only `SelectionSnapshotProvider` protocol (`read_snapshot()`),
  `IssuerVerifier`, `PeerVerifierProtocol`, and `RequestHistoryProvider`. It
  exposes no method to publish or mutate selection snapshots. Test-only
  publication lives on `InMemorySelectionPublisher`, whose `.reader()` returns a
  read-only `InMemorySelectionSnapshotProvider`.
- **No candidate/file/controller self-selection**: `for_submit`, `for_run`,
  `check_current`, and `bind_created` require an authenticated `AuthenticatedPeer`
  verified by `PeerVerifierProtocol` and match jobs strictly from the immutable
  `SelectionSnapshot`. Missing snapshots, empty job sets, missing matches, or
  multiple matching jobs refuse with `AUTHORITY_UNAVAILABLE`, `SELECTION_MISSING`,
  `SELECTION_CHANGED`, or `SELECTION_AMBIGUOUS`.
- **Exact dispatch and authority binding**: `for_run` verifies both
  `execution_uuid` and the full `DispatchIdentity` (`execution_uuid`,
  `dispatch_nonce`, `running_attempt`), refusing mismatches with
  `DISPATCH_CHANGED`. Every job's `selector_issuer` and `authority_refs` are
  verified through `IssuerVerifier.verify(...)` against the job's exact
  `SelectedSubject`, peer actor process, required `SelectedOperation` set,
  `ConditionRef` tuple, and `TrustedInstant` validity window (`at` taken solely
  from `snapshot.verified_at` using strict non-negative integer comparisons
  `not_before <= at < expires_at`). Empty process or peer identity strings never
  compare equal (`"" == ""` refuses with `PEER_UNVERIFIED` / `SCOPE_MISMATCH`).
- **Signed Ed25519 issuer and revocation verification (`issuer_verifier.py`)**:
  `Ed25519IssuerVerifier` (implements the `IssuerVerifier` port; the module holds
  no private key and no signing function) verifies CAJ-1 canonical envelopes
  (`temper_ai.config.admission_contract.canonical_bytes` / `decode_canonical`)
  with domain separation `b"temper-p3-issuer/v1\x00" + kind + b"\x00" + canonical_bytes(record)`
  against pinned `AnchorTable` entries (`PRODUCTION_ANCHOR_TABLE` is empty by
  default, refusing with `ISSUER_UNVERIFIED`), requires a signed
  `p3-issuer-revocation/1` status record in the same clock domain (missing or
  stale status refuses `AUTHORITY_UNAVAILABLE`; listed `record_id` or
  `authority_revision` refuses `AUTHORITY_REVOKED`), and evaluates every
  `ConditionRef` against the closed `CONDITION_TABLE` (`CONDITIONS_UNMET` on
  unknown or unsatisfied conditions; the job's conditions must be an exact
  `tuple`, and `mode:external-db-fresh` holds only for a route that is the
  exact str `external-db-fresh`, see `job_runs_supported_mode`). Every
  `AnchorTable` and `AnchorEntry`
  field is required (no default clock domain, validity window or purposes) and
  the table is checked whole at construction, raising `AnchorTableInvalid`
  (`p3_issuer_anchor_table_invalid:<reason>`): a public key that is not 64
  lowercase hex, non-canonical (`public_key_noncanonical`) or one of the ten
  small-order encodings (`public_key_small_order`; `cryptography` loads those
  and accepts forged signatures for them) never enters the table, and
  `verify_ed25519_hex` refuses such keys too. The production table's clock
  domain is the placeholder `PRODUCTION_CLOCK_DOMAIN_UNSET`; a table that holds
  entries under it raises `clock_domain_unset`, so pinning a live anchor must
  name a clock that never repeats or goes back (N1-SPEC r2 6.8). Subject
  projection accepts only the exact `SelectedSubject`, `PreDispatchJob`,
  `JobKey` and `DispatchIdentity` types; a look-alike class refuses
  `SUBJECT_MISMATCH`. `verify` never raises (N1-SPEC 4.2): an error from the
  record or status store, from the signature library, or from an odd subject
  or peer object is a refusal in its row (`AUTHORITY_UNAVAILABLE` for I4, R1
  and R4, `ISSUER_UNVERIFIED` for I11, `SUBJECT_MISMATCH` for S1,
  `PEER_UNVERIFIED` for P1), and `PinnedPeerVerifier.verify_peer` answers
  `False`. `compose_p3_authority(...)` accepts
  explicit `issuer_verifier`, `peer_verifier`, `issuer_anchors`,
  `issuer_records`, `issuer_statuses`, `issuer_condition_table`, and
  `pinned_peers` parameters while keeping all defaults `None` and
  `writes_enabled=False`. The issuer parts build an `Ed25519IssuerVerifier` and
  `pinned_peers` a `PinnedPeerVerifier`; passing them with `issuer_verifier`,
  `peer_verifier` or `registry` raises `ValueError` instead of ignoring one.
- **Window creation binding**: `bind_created` accepts only Phase A
  `CurrentBinding` records (`A_PRE_CREATE` / `A_PRE_ARM`) whose creator process
  is authorized, and refuses conflicting re-bindings of the same `window_id`
  with `WINDOW_INELIGIBLE`.

## CandidateBindings delegation (`candidate_bindings.py`)

- **Exact V1 protocol and primitive reuse**: `P3CandidateBindings` implements
  `temper_ai.runner.admission.CandidateBindings` with unchanged public method
  signatures (`designated`, `authority_for_submit`, `authority_for_run`,
  `transport`, `prepare`, `bootstrap_snapshot`, `load_snapshot`, `bind_context`).
  It delegates raw config capture to `RawCapture` + `ConfigStore`, candidate
  graph/node reconstruction to `load_candidate`, execution context binding to
  `CandidateUse` + `Projection`, and DB persistence/row-locking to
  `DbAdmissionTransport` (`external-db-fresh`).
- **Frozen candidate wire preserved**: No P3 fields are added to
  `docs/schemas/candidate-admission-v1.schema.json` or `DescriptorAuthority`.
  `authority_for_submit` and `authority_for_run` first require independent
  `P3AuthorityRegistry.for_submit` / `for_run` verification and check that the
  selected job's `approved_descriptor_digest` and `expected_source_digest` match
  the candidate adapter's expected digests before returning `DescriptorAuthority`.
- **Variant and fallback refusals**: Unsupported sealed, Pi-containing,
  continuation, and direct-bypass variants are refused with
  `AdmissionRefused(RefusalCode.MODE)`. Mutable `graph_loader.load_workflow`
  fallback inside `bootstrap_snapshot` is blocked and raises `AdmissionRefused`.
- **No network/RPC under DB claim lock**: `DbAdmissionTransport.claim_if_current`
  executes under its database row lock without invoking `IssuerVerifier` or
  `PeerVerifierProtocol`. Production `DEFAULT_CANDIDATE_BINDINGS` in
  `temper_ai.runner.admission` remains `None`.

## Native boundary and host join service (`service.py`)

- **Single service backing both interfaces**: `P3AuthorityService` implements all
  six `P3NativeBoundary` methods (`before_create`, `before_checker`,
  `before_request`, `before_admit`, `before_execute`, `before_count`) and all
  nine `NativeHostJoin` methods (`select_host_job`, `permit_observation`,
  `open_observation`, `observe`, `recheck_effect`, `witness_event`,
  `lookup_occurrence`, `verify_publication`, `receive`). `NativeHostJoinAdapter`
  is a thin adapter over the exact same `P3AuthorityService` instance, not a
  second controller or signer.
- **Single Systems comparator**: Source closure comparison is delegated to
  `p3_source_closure.compare_loaded_source` through
  `SystemsSourceClosureComparator`. Missing comparator or mismatched schema
  versions (`p3-reviewed-source-graph/1`, `p3-reviewed-loaded-closure/1`) refuse
  fail-closed (`AUTHORITY_UNAVAILABLE`, `CLOSURE_VERSION`, `CLOSURE_INCOMPLETE`,
  `CLOSURE_MISMATCH`).
- **Phase A / B / C and D-1 -> D-5 ordering**:
  - `before_create` (Phase A, `A_PRE_CREATE`) and `before_checker` (Phase A,
    `A_PRE_ARM`) verify current authority, complete gap-free observations
    authenticated against the injected `HostObserver`, `WorkerObserver`, and
    `RootObserver` providers, registered window creation bindings
    (`AuthorityRegistryService.bind_created`), root bindings (`publication` and
    `host_evidence`), compatibility corpus (`ops-host-compat-corpus/1`), QA
    receiving registration, and recomputed `MATCH` source closure comparisons
    against registered `ReviewedSourceGraph` / `LoadedClosureEnvelope` inputs.
  - `select_host_job` and `permit_observation` derive `SelectedHostJob.caller`
    (`source_review_ref`, `inspect_variant`, `allowed_rows`) from the registered
    `ReviewedSourceGraph` and `CompatibilityProfile` rather than synthesizing
    placeholders.
  - `before_request` (Phase B, `B_PRE_REQUEST`), `before_admit` (Phase B,
    `C_PRE_REQUEST`), `before_execute` (Phase B, `C_PRE_EXECUTION`), and
    `before_count` (Phase C, `C_BEFORE_COUNT`) enforce `window_id` continuity
    against `checker.window.actual_creation.window_id` alongside row scope,
    non-empty observation cursors, and current authority. Pre-admission refusals
    preserve `AdmissionState.NOT_ADMITTED` and `SequenceUse.UNUSED`.
  - `record_admitted_occurrence` records the D-1 row occurrence in the injected
    `EffectFenceProvider`. `before_execute` (Phase B, `C_PRE_EXECUTION`) and
    `before_count` (Phase C, `C_BEFORE_COUNT`) refuse with `PRIOR_MISSING` if
    D-1 was not recorded first, `PRIOR_FOREIGN` on foreign selection/key, and
    `PRIOR_UNVERIFIED` on digest or witness mismatch.
  - `lookup_occurrence`, `verify_publication`, and `receive` link D-1 occurrence
    witnesses to D-5 publication provenance and `VerifiedReceiptBinding` without
    granting count permission (`receive` returns `VerifiedReceiptBinding` with
    `evidence.receiving == ()`).
  - `before_count` requires `P5Assessment.trust == "UNTRUSTED"` and
    `verdict in ("PASS", "FAIL")` (`BLOCKED` refuses `RESULT_UNVERIFIED`),
    complete receipt provenance (`state == "complete"`), terminal publication
    outcome (`"success"`, `"app-failure"`, `"host-failure"`), complete cleanup
    state (`"not-required"`, `"complete"`), terminal occurrence state
    (`"completed"`, `"failed"`), consistency between native failure outcome and
    P5 verdict (native failure paired with `verdict == "PASS"` refuses
    `RESULT_UNVERIFIED`), verified D-1 -> D-5 predecessor provenance when
    `provenance.predecessor` is present, complete receipt provenance before
    disarm (`during`/`after`/`unknown` disarm relations refuse
    `WINDOW_INELIGIBLE`), committed effect state (`EffectState.UNCERTAIN` from
    lost ack refuses `RESULT_UNVERIFIED`), and exact QA receiving verification.
    Duplicate counting for the same request or idempotency identity refuses
    `ALREADY_COUNTED` with `SequenceUse.USED`.

## Unavailable native capabilities and limits

- **No production authority or collectors**: Real issuer enrollment, trust roots,
  authenticated peer channels, writer exclusion, host/worker/root native
  collectors, default IPC listeners, and live QA/compatibility receiving stores
  are not implemented in this source composition.
- **Local transaction guarantees vs. distributed effect fencing**:
  `DbAdmissionTransport` row locking (`FOR UPDATE NOWAIT` on PostgreSQL) and
  `InMemoryEffectFenceProvider` provide local transactional / in-process test
  guarantees only. Distributed revision-to-effect fencing across hosts is not
  implemented; `InMemoryEffectFenceProvider(distributed_enforced=True)` raises
  `ValueError`.
- **Qualification and writes**: All `N` checks remain unresolved, rows remain
  `UNQUALIFIED`, P5 assessments remain `UNTRUSTED`, and `writes_enabled` is
  permanently `False`.
- **Contact spy limits**: Cold-import and constructor spies in
  `tests/test_p3_authority/test_service.py` verify that importing the modules and
  calling default-off constructors make zero calls through the patched Python
  `socket`, `urllib`, `http.client`, `httpx`, `temper_ai.database`, and
  `subprocess` entrypoints; they detect contacts on those patched paths in the
  test process rather than enforcing kernel-level sandboxing.
