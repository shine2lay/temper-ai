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
| `capture_git_checkout_provenance(...)` | Reads HEAD commit, tree, tracked blob OIDs/modes, worktree cleanliness (`git status --porcelain`), and disk byte SHA-256 digests from an explicit checkout path; validates provenance via `p3_source_closure.provenance.check_provenance`. |
| `WorkerClosureCollector` | Opt-in stateful collector wired into launch, early bootstrap, runner bootstrap, script launch, and verified child registration hooks to assemble the worker-half `LoadedClosureEnvelope` (`validate_loaded_envelope`) and `ProcessExpectation` records. |
| `verify_and_compare_worker_closure(...)` | Checks schema versions, coverage completeness across `ALL_N3_COVERAGE_CATEGORIES`, and both `host` + `worker` envelope halves (`CoverageBookkeeper.verify_complete_and_compare`), then delegates semantic comparison to `p3_source_closure.comparison.compare_loaded_source`. |

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
6. **`CoverageBookkeeper.verify_complete_and_compare`**
   (`temper_ai/p3_authority/coverage_bookkeeping.py`):
   - Enforces presence of both `"host"` and `"worker"` process observations before
     calling `compare_loaded_source` (`CLOSURE_INCOMPLETE` if one half is missing).

---

## Guard Invariants and Deterministic Refusals

| Condition | Refusal Code |
| --- | --- |
| Late attach, skipped launch/bootstrap stage, or dropped load-stream events | `RefusalCode.OBSERVATION_GAP` |
| Missing `host` or `worker` envelope half, missing any `ALL_N3_COVERAGE_CATEGORIES` category (`launch`, `bootstrap`, `python`, `generated`, `cache`, `native`, `dynamic`, `children`, `control_plane`, `effect_fence`), unauthenticated stream mechanism, or counting `box_profile.closure` as complete | `RefusalCode.CLOSURE_INCOMPLETE` |
| Non-provider / surrogate child launcher registration (`NON_PROVIDER_REGISTRATION_SOURCES` or any source `!= VERIFIED_LAUNCHER_REGISTRATION_SOURCE`) | `RefusalCode.PEER_UNVERIFIED` |
| Schema or version mismatch (`!= p3-reviewed-source-graph/1` or `!= p3-reviewed-loaded-closure/1`) | `RefusalCode.CLOSURE_VERSION` |
| Dirty Git worktree, untracked file, submodule dirty state, or disk-vs-HEAD blob digest mismatch | `RefusalCode.SOURCE_CHANGED` |
| `compare_loaded_source` returning `disposition="REFUSED"` (unreviewed loaded module, byte substitution, Git membership contradiction), mapped by the landed `comparison_to_refusal` | `RefusalCode.CLOSURE_MISMATCH` (`BINDING` -> `RefusalCode.SUBJECT_MISMATCH`, `PROCESS_INSTANCE` -> `RefusalCode.RUNTIME_CHANGED`) |
| `compare_loaded_source` returning `disposition="UNKNOWN"` | `RefusalCode.OBSERVATION_GAP` for `SEQUENCE_GAP` / `STALE_FRONTIER` / `OBSERVER_ORIGIN`, else `RefusalCode.CLOSURE_INCOMPLETE` (never mapped to `MATCH`) |
