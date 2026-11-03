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
| `ObservedLoad` | One load the observer saw: `node_id`, `loaded` (the identity of the loaded bytes, never of the node name) and `event_kind` (`"load"`, or `"cache"` when CPython ran a cached `.pyc`). It carries no coverage category. |

`temper_ai.p3_authority.executed_python_code` (what CPython actually executes):

| Symbol | Purpose |
|---|---|
| `cached_python_code_path(source_path, *, pycache_prefix, optimization)` | Where CPython looks for the `.pyc` (same rule as `importlib.util.cache_from_source`, with the worker's `sys.pycache_prefix` and `-O` level given). |
| `executed_python_code(source_path, *, pycache_prefix, optimization, check_hash_based_pycs)` -> `ExecutedPythonCode` | The bytes CPython executes on import: a `.pyc` whose header CPython accepts (magic, known flags, then the recorded source mtime and size, or the source hash per `--check-hash-based-pycs`) runs instead of the source, even a stale one. |
| `observe_python_module_execution(*, source_node_id, cached_node_id, source_path, boundary, ...)` | The `ObservedLoad` for one imported module: a used `.pyc` -> `event_kind="cache"` for the reviewed `cached_code` node with the `.pyc` bytes; a used `.pyc` with no reviewed cached node -> `CLOSURE_MISMATCH`; else the source bytes for the source node; unreadable source -> `OBSERVATION_GAP`. |

A stale but valid `.pyc` (source `X = 1`, `.pyc` compiled from `X = 2` with the same
size and mtime) is what CPython runs, even under `-B`; reported as a `cache` event for
the reviewed `cached_code` node, the comparator refuses it with `BYTE_SUBSTITUTION` +
`CACHED_CODE` (`test_refusal_twin_stale_valid_pyc_is_byte_substitution`). Reporting
the source bytes instead would hide it. Every header rule is checked against a real
CPython import in `test_executed_python_code_agrees_with_cpython`.
| `refuse_observer_scope_shortfall` | Fail-fast check of one observer scope record (`Checkpoint`) against a recorded stream: epoch, `first_sequence=0`, `last_sequence` / `last_event_id` at the stream's last event, child frontier, closure boundary, `sealed`, `loss_count=0` and both refs, else `OBSERVATION_GAP`; every `ALL_N3_COVERAGE_CATEGORIES` entry in `coverage` and not in `gaps`, else `refuse_missing_coverage`. |
| `WorkerClosureCollector` | Opt-in stateful collector wired into launch, early bootstrap, runner bootstrap, script launch, and verified child registration hooks to assemble the worker-half `LoadedClosureEnvelope` (`build_envelope`, checked by `validate_loaded_envelope`). It supplies no `ExpectedProcess` entries or `VerifiedOriginFact` witnesses: those come from the caller's own observer record, so the collector never witnesses its own claims. |
| `merge_dual_role_halves(...)` -> `DualRoleEnvelope` | Checks the worker half and the peer (host) half and each half's supplied observer identity, then merges them into one envelope whose observer origin is derived, never supplied (see below). |
| `verify_and_compare_worker_closure(...)` | Validates the reviewed graph, merges the halves with `merge_dual_role_halves`, requires both the `host` and `container` roles (`CoverageBookkeeper.verify_envelope(require_dual_role=True)`), then delegates semantic comparison to `p3_source_closure.compare_loaded_source`; accepts only `MATCH` with no reasons. |

---

## Opt-In Hook Wiring

1. **`DockerLaunchObservationAdapter`** (`temper_ai/p3_authority/launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None` and
     `runtime_loads: tuple[ObservedLoad, ...] = ()`.
   - When provided, `after_container_start` passes the authenticated
     `WorkerObservation` to `record_docker_launch`, which binds the closure to it
     before recording anything (see "Launch binding" below), then records the worker's
     trusted start event, its observed runtime loads, and takes the worker's
     epoch from the observed `exec_generation` witness. `after_container_start`
     re-checks no execution id itself: `record_docker_launch` refuses an
     `execution_id` other than the bound one (`DISPATCH_CHANGED`) and the adapter
     then keeps no record.
2. **`EarlyBootstrapObservationHook`** (`temper_ai/p3_authority/launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None`,
     `bootstrap_loads: tuple[ObservedLoad, ...] = ()`, and
     `use_box_profile_closure_as_complete: bool = False`.
   - Records the observed pre-request bootstrap loads. Explicitly ignores
     `box_profile.closure` as complete coverage.
3. **`RunnerBootstrapObservationHook`** (`temper_ai/p3_authority/launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None` and
     `loads: tuple[ObservedLoad, ...] = ()`.
   - Records the observed loads before runner execution.
4. **`ScriptLaunchObservationAdapter`** (`temper_ai/p3_authority/launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None`.
   - Verifies that launch, early bootstrap, and runner bootstrap were already
     captured on the bound `execution_uuid` before script execution (`OBSERVATION_GAP`
     on late attach).
5. **`ChildRegistrationRegistry` / `BashChildLaunchAdapter`**
   (`temper_ai/p3_authority/child_registration.py`, `launch_adapters.py`):
   - Accepts `closure_collector: WorkerClosureCollector | None = None` plus child
     profile/node metadata and `child_runtime_loads` / `child_loads:
     tuple[ObservedLoad, ...]`.
   - Records the child's birth (the worker's `child` event and the child's start
     event) only after `VERIFIED_LAUNCHER_REGISTRATION_SOURCE` verification
     (`ChildLaunchVerificationPort`); the child's `end` event and `terminated` state
     only from its observed termination (`record_child_termination`, from
     `on_terminated`). Any
     non-provider surrogate registration (`refuse_surrogate_child_registration`)
     taints the collector (`PEER_UNVERIFIED`).
   - `BashChildLaunchAdapter.on_spawned` runs
     `WorkerClosureCollector.refuse_child_spawn_before_registration` (every refusal
     `record_verified_child_spawn` gives) before the registry write, so a child the
     closure refuses is never left in the registry.
   - The host/closure pairing check (`refuse_unpaired_process_instances`: pid, boot,
     pid/mount/user namespaces, launch identity -> `RUNTIME_CHANGED`) is one function,
     used for children and for the worker's launch binding.
6. **`CoverageBookkeeper.verify_envelope`**
   (`temper_ai/p3_authority/coverage_bookkeeping.py`):
   - Accepts `require_dual_role: bool = False`. When `True`, the envelope's process
     observation locations must be exactly `{"host", "container"}`
     (`CLOSURE_INCOMPLETE` otherwise). The default keeps every current caller unchanged.

---

## Launch Binding (worker half)

`record_docker_launch` refuses, before recording anything, unless the closure names
the observed worker and its job:
- the observed `worker_instance` pairs with the collector's worker `ProcessInstance`
  (`refuse_unpaired_process_instances`) -> else `RUNTIME_CHANGED`;
- `WorkerObservation.selection_revision` and the observed job's `selection_revision`
  equal `ClosureBinding.selection_revision`, and the job's `job_revision` equals
  `ClosureBinding.job_revision` -> else `SELECTION_CHANGED`;
- the job's `route` equals `ClosureBinding.route` -> else `ROUTE_UNSUPPORTED`;
- the job is a running `JobKey` (a `PreDispatchJob` has no nonce or attempt to bind)
  whose `execution_uuid`, `dispatch_nonce` and `running_attempt` equal the binding's
  `execution_uuid`, `dispatch_nonce` and `attempt` -> else `DISPATCH_CHANGED`.

The codes follow `selection_snapshot.py` and `docs/p3-selection-snapshot.md`.

## Scope Is the Observer's Sealed Record, Never Built

No hook, adapter or registry takes a coverage or category argument, and no load carries
a category label (a label is the producer's assertion, and no kind-to-category map is
lossless). What the observer watched for a process is the observer's own sealed scope
record, its whole `Checkpoint` (Systems #95 shape): `epoch`, `first_sequence=0`,
`last_sequence`, `last_event_id`, `child_frontier`, `coverage`, `gaps`, `loss_count`,
`sealed`, `initial_state_ref`, `checkpoint_ref`, `boundary`.

`build_envelope(observer_checkpoints=...)` takes that record for every recorded
process (closure instance id -> `Checkpoint`) and copies each verbatim into the
process's observation; the collector builds none of it. Before copying it refuses:
- a recorded process without a scope record, or a scope that doesn't seal its stream
  (`refuse_observer_scope_shortfall`) -> `OBSERVATION_GAP`;
- a scope record for a process the collector never recorded -> `CLOSURE_INCOMPLETE`;
- a category the scope lacks or lists in `gaps`: `effect_fence` or `control_plane`
  -> `OBSERVATION_GAP`, any other -> `CLOSURE_INCOMPLETE`.

These are fail-fast pre-checks. The comparator stays the final decider: every load is
judged by node id against the reviewed profile, bytes and representation, and each
process's scope against the observer's facts, so an envelope claiming more than the
observer sealed never compares `MATCH`.

Shared cases: `test_shared_scope_case_worker_half_pre_check` runs Systems #95's
`scope_case(case_id, "worker")` SC-01..SC-11 (the same cases ship as
`p3_source_closure/n3_scope_cases.json`). On the observer-side worker record the
pre-check passes SC-01/SC-02 (comparator `MATCH`), refuses SC-03/SC-09 with
`CLOSURE_INCOMPLETE` and SC-04/SC-05/SC-08 with `OBSERVATION_GAP`, and refuses SC-07
(a load after the sealed `last_sequence`) with `OBSERVATION_GAP`. SC-06/SC-10/SC-11
change only the envelope's scope: the pre-check can't see them, the comparator
refuses them, and the collector never makes them because it copies the observer's
scope; their observer twins (SC-03, SC-04, SC-08) are refused by the pre-check.

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
| Late attach, skipped launch/bootstrap stage, dropped load-stream events, or an unobserved `effect_fence` / `control_plane` category | `RefusalCode.OBSERVATION_GAP` |
| Observed worker not paired with the closure's worker (pid, boot, namespaces, launch identity) | `RefusalCode.RUNTIME_CHANGED` |
| Observed selection or job revision differing from the closure binding | `RefusalCode.SELECTION_CHANGED` |
| Observed dispatch (execution, nonce, attempt) differing from the binding, or a pre-dispatch job | `RefusalCode.DISPATCH_CHANGED` |
| Observed route differing from the binding's | `RefusalCode.ROUTE_UNSUPPORTED` |
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
