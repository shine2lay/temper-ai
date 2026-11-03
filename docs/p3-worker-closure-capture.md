# P3 T5-N3W Worker Source and Git Closure Capture (`temper_ai.p3_authority.worker_closure_capture`)

## Overview

`temper_ai.p3_authority.worker_closure_capture` implements the Temper worker half of
`N3` (`Temper-T5-N3W`) for Architecture `#125`'s Wave 2 native-authority join:
deterministic, opt-in capture of the worker runtime's `LoadedClosureEnvelope`
(`p3-reviewed-loaded-closure/1`) and checkout `GitProvenance` records against the
frozen `p3_source_closure` contract (`p3-reviewed-source-graph/1`,
`p3-reviewed-loaded-closure/1`).

All capture hooks are **inert and switched off by default**:
- `WRITES_ADMITTED` in `temper_ai.p3_authority` remains `False`.
- Importing or constructing `WorkerClosureCollector` or the launch/bootstrap hooks
  with default (`closure_collector=None`) arguments performs zero Git, filesystem,
  `/proc`, container, database, or model calls.
- Runs without an opt-in `WorkerClosureCollector` are byte-for-byte unchanged across
  `DockerLaunchObservationAdapter`, `EarlyBootstrapObservationHook`,
  `RunnerBootstrapObservationHook`, `ScriptLaunchObservationAdapter`,
  `BashChildLaunchAdapter`, `ChildRegistrationRegistry`, and `CoverageBookkeeper`.

---

## Public Surface (`temper_ai.p3_authority.worker_closure_capture`)

| Symbol | Responsibility |
| --- | --- |
| `CapturedGitCheckoutProvenance` | Immutable bundle of validated `RepositoryState`, per-file `GitProvenance` records, `SourceNode` (`kind="git_source"`) entries, and `VerifiedOriginFact` (`purpose="membership"`) witnesses for a clean Git checkout. |
| `capture_git_checkout_provenance(...)` | Reads the HEAD commit, tree, tracked blob OIDs/modes and index straight from the explicit checkout's `.git` files (HEAD, refs, `packed-refs`, zlib loose objects, index; no subprocess), hashes every worktree file, and validates the result with `p3_source_closure.provenance.check_provenance`. |
| `WorkerClosureCollector` | Opt-in stateful collector wired into launch, early bootstrap, runner bootstrap, script launch, and verified child registration hooks to assemble the worker-half `LoadedClosureEnvelope` (`build_envelope`, checked by `validate_loaded_envelope`), its `ExpectedProcess` entries (`expected_processes()`) and `VerifiedOriginFact` witnesses (`verified_origin_facts()`). |
| `merge_dual_role_halves(...)` -> `DualRoleEnvelope` | Checks the worker half and the peer (host) half and each half's supplied observer identity, then merges them into one envelope whose observer origin is derived, never supplied (see below). |
| `verify_and_compare_worker_closure(...)` | Validates the reviewed graph, merges the halves with `merge_dual_role_halves`, requires both the `host` and `container` roles (`CoverageBookkeeper.verify_envelope(require_dual_role=True)`), then delegates semantic comparison to `p3_source_closure.compare_loaded_source`; accepts only `MATCH` with no reasons. |

---

## Opt-In Hook Wiring

1. **`DockerLaunchObservationAdapter`** (`temper_ai/p3_authority/launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None`.
   - When provided, `after_container_start` records the worker process start event,
     runtime nodes (`interpreter`, `stdlib`), and `"launch"` coverage.
2. **`EarlyBootstrapObservationHook`** (`temper_ai/p3_authority/launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None`,
     `bootstrap_nodes: tuple[tuple[str, ContentIdentity], ...] = ()`, and
     `use_box_profile_closure_as_complete: bool = False`.
   - Records pre-request bootstrap module loads and `"bootstrap"` coverage.
     Explicitly ignores `box_profile.closure` as complete coverage.
3. **`RunnerBootstrapObservationHook`** (`temper_ai/p3_authority/launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None`,
     `loaded_nodes: tuple[tuple[str, ContentIdentity], ...] = ()`, and
     `coverage_categories: tuple[N3Coverage, ...]`.
   - Records worker module, generated, cache, native, dynamic, control-plane, and
     effect-fence loads prior to runner execution.
4. **`ScriptLaunchObservationAdapter`** (`temper_ai/p3_authority/launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None`.
   - Verifies that launch, early bootstrap, and runner bootstrap were already
     captured on the bound `execution_uuid` before script execution (`OBSERVATION_GAP`
     on late attach).
5. **`ChildRegistrationRegistry` / `BashChildLaunchAdapter`**
   (`temper_ai/p3_authority/child_registration.py`, `launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None` plus child
     profile/node metadata.
   - Records child spawn and sealed child `ProcessObservation` only after
     `VERIFIED_LAUNCHER_REGISTRATION_SOURCE` verification (`ChildLaunchVerificationPort`).
     Any non-provider surrogate registration (`refuse_surrogate_child_registration`)
     taints the collector (`PEER_UNVERIFIED`).
6. **`CoverageBookkeeper.verify_envelope`**
   (`temper_ai/p3_authority/coverage_bookkeeping.py`):
   - Accepts `require_dual_role: bool = False`. When `True`, the envelope's process
     observation locations must be exactly `{"host", "container"}`
     (`CLOSURE_INCOMPLETE` otherwise). The default keeps every current caller unchanged.

---

## Dual-Role Merge and Observer Origin

`compare_loaded_source` checks `VerifiedClosureOrigins.observed_bytes` against the
compared envelope's `content` (`OBSERVER_ORIGIN`); that identity must come from the
authenticated observer, never from the envelope being compared. Each half has its own
observer, so `verify_and_compare_worker_closure` takes `worker_observed_bytes` and
`peer_observed_bytes` (each `None` when that half's provider is unavailable) and
requires `verified_origins.observed_bytes` to be `None`.

`LoadedClosureEnvelope.content` and `ReviewedSourceGraph.content` are caller-set
fields: the records bind them to nothing. So each half and the reviewed graph are
revalidated (`validate_loaded_envelope`, `validate_reviewed_graph`), a `content`
field that differs from the validated content (stale or forged) is refused
(`CLOSURE_MISMATCH`), and only the validated values are merged, counted and compared.

`merge_dual_role_halves` derives the merged envelope's origin:
- a supplied half identity that differs from that half's validated `content` -> refused
  (`CLOSURE_MISMATCH`, REFUSED `OBSERVER_ORIGIN`) before merging;
- both half identities supplied and equal -> the merged envelope's `content`
  (the merge is a pure function of two verified halves);
- either half identity `None` -> `None`, so the comparator returns UNKNOWN
  `OBSERVER_ORIGIN` (`OBSERVATION_GAP`), never `MATCH`.

Before merging, the peer's envelope-level fields must equal the worker's: `binding`
and `boundary` (`SUBJECT_MISMATCH`), `reviewed_graph` and `legacy_links`
(`CLOSURE_MISMATCH`); `schema` is the one accepted envelope schema, enforced by
`validate_loaded_envelope` on each half (`CLOSURE_VERSION`). The merged envelope
puts the peer's process observations before the worker's, keeps every distinct
`provenance_refs` entry of both halves (peer first) and gets the id
`"<worker envelope_id>+<peer envelope_id>"`.

---

## Guard Invariants and Deterministic Refusals

| Condition | Refusal Code |
| --- | --- |
| Late attach, skipped launch/bootstrap stage, or dropped load-stream events | `RefusalCode.OBSERVATION_GAP` |
| Missing peer half or missing `host` / `container` role, missing any `ALL_N3_COVERAGE_CATEGORIES` category (`launch`, `bootstrap`, `python`, `generated`, `cache`, `native`, `dynamic`, `children`, `control_plane`, `effect_fence`), unauthenticated stream mechanism, or counting `box_profile.closure` as complete | `RefusalCode.CLOSURE_INCOMPLETE` |
| Non-provider / surrogate child launcher registration (`NON_PROVIDER_REGISTRATION_SOURCES` or any source `!= VERIFIED_LAUNCHER_REGISTRATION_SOURCE`) | `RefusalCode.PEER_UNVERIFIED` |
| Schema or version mismatch (`!= p3-reviewed-source-graph/1` or `!= p3-reviewed-loaded-closure/1`) | `RefusalCode.CLOSURE_VERSION` |
| Index differing from the HEAD tree, worktree bytes differing from their blob, any untracked or ignored file, symlink or submodule entry, or a requested path not in the HEAD tree | `RefusalCode.SOURCE_CHANGED` |
| Unreadable checkout, packed object (only loose objects are read), or non-hex HEAD/tree | `RefusalCode.OBSERVATION_GAP` |
| Peer `binding` or `boundary` differing from the worker's | `RefusalCode.SUBJECT_MISMATCH` |
| Peer `reviewed_graph` or `legacy_links` differing from the worker's, a half's or the reviewed graph's `content` field differing from its validated content, a supplied half observer identity differing from that half's validated `content`, or a supplied `verified_origins.observed_bytes` | `RefusalCode.CLOSURE_MISMATCH` |
| A half observer identity unavailable (`None`) | `RefusalCode.OBSERVATION_GAP` (UNKNOWN `OBSERVER_ORIGIN`, never `MATCH`) |
| `compare_loaded_source` returning `disposition="REFUSED"` (unreviewed loaded module, byte substitution, Git membership contradiction), mapped by the landed `comparison_to_refusal` | `RefusalCode.CLOSURE_MISMATCH` (`BINDING` -> `RefusalCode.SUBJECT_MISMATCH`, `PROCESS_INSTANCE` -> `RefusalCode.RUNTIME_CHANGED`) |
| `compare_loaded_source` returning `disposition="UNKNOWN"` | `RefusalCode.OBSERVATION_GAP` for `SEQUENCE_GAP` / `STALE_FRONTIER` / `OBSERVER_ORIGIN`, else `RefusalCode.CLOSURE_INCOMPLETE` (never mapped to `MATCH`) |
