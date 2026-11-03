# P3 T4 Worker Observation and Child Registration (`temper_ai.p3_authority`)

## Overview

This document describes Temper's disabled-by-default P3 T4 worker/checker
observation, child/exec registration, synthetic stream coverage bookkeeping,
and explicit opt-in launch/bootstrap adapters built against the canonical
`temper_ai.p3_authority.contract` seam (`#261`).

All modules in this package are **source-only and disabled by default**:
- Importing or constructing any class performs zero filesystem, `/proc`,
  socket, container, database, or environment probing.
- No production factory, CLI command, worker startup path, or configuration
  installs a `WorkerObservationAdapter` or launch adapter by default.
- Native host join ports (`NativeHostJoin`: `N1`–`N9`), complete native code
  collection, native issuer/grant authority, and a live effect fence remain
  unimplemented (`UNKNOWN` / refused). The T5-N4 snapshot providers below are
  inert: nothing constructs them by default, and the fence is closed by default. All 8 native join capabilities remain
  unresolved, 4 matrix rows remain `UNQUALIFIED`, P5 remains `UNTRUSTED`, and
  writes remain off.

---

## Public Modules and Callable Imports

| Module | Primary Types & Functions | Responsibility |
| --- | --- | --- |
| `temper_ai.p3_authority.worker_observation` | `WorkerObservationAdapter`, `WorkerRootObservationAdapter`, `WorkerObservationProvider`, `SuppliedWorkerFrame`, `EXISTING_TEMPER_SEAM_GUARANTEES`, `refuse_existing_seam_as_complete_coverage`, `build_worker_observation_compat_cases`, `validate_worker_observation_compat_corpus`, `map_host_envelope_gaps` | Implements `WorkerObserver` and `RootObserver` from `temper_ai.p3_authority.contract`; enforces pre-collection permission (`verify_observation_grant`), distinct `HostObservation` vs `WorkerObservation` runtimes, `publication` vs `host_evidence` roots (`BothRootObservations`), `RootOwnerVsActorAssertion` (`expected_owner != effective_actor`), and `ops-host-compat-corpus/1` (`temper.t4.worker.*`) worker cases. |
| `temper_ai.p3_authority.child_registration` | `ChildRegistrationTicket`, `RegisteredChildGeneration`, `ChildRegistrationRegistry`, `refuse_surrogate_child_registration`, `VERIFIED_LAUNCHER_REGISTRATION_SOURCE`, `NON_PROVIDER_REGISTRATION_SOURCES` | Enforces provider-verified child birth and `exec` generation lineage (`(pid, start_time_ns, exec_generation)`); refuses PID reuse (`PID_REUSED`), foreign parent/dispatch (`DISPATCH_MISMATCH`), and env/UID/owner/profile surrogates (`UNAUTHORIZED`); prevents data-class construction from registering a process. |
| `temper_ai.p3_authority.coverage_bookkeeping` | `CoverageBookkeeper`, `ProcessLoadPolicy`, `SyntheticStreamAuthTag`, `SyntheticLoadStreamEvent`, `SyntheticFrontierEvent`, `StreamCheckpointSummary`, `SystemsClosureComparisonAdapter`, `closure_outcome_to_refusal_or_ok` | Tracks authenticated synthetic load streams, sequence/epoch monotonicity, dropped-event windows (`NativeEventRange.dropped_events`), required vs permitted per-process loads, category gaps (`bootstrap_pre_interpreter`, `transitive_import`, `generated_code`, `bytecode_cache`, `lazy_runtime_import`, `native_extension`, `child_exec_lineage`), wait/resume causal frontiers (`STALE_FRONTIER`), and delegates semantic comparison exclusively to Systems' `compare_loaded_source`. |
| `temper_ai.p3_authority.launch_adapters` | `DockerLaunchObservationAdapter`, `EarlyBootstrapObservationHook`, `RunnerBootstrapObservationHook`, `ScriptLaunchObservationAdapter`, `BashChildLaunchAdapter`, `P3ObservationRefusedError` | Explicit opt-in adapters for `DockerSpawner.spawn`, `take_box_delivery_first`, `bootstrap_runner_context_from_env`, `ScriptAgent.run`, and `Bash.execute`. |
| `temper_ai.p3_authority.box_observation_provider` | `BoxObservationProvider`, `BoxInspectSnapshot`, `BoxMount`, `RootPin`, `RootStatSnapshot`, `RootKind`, `ROOT_KINDS`, `ROOT_RIGHTS`, `KEPT_ENVIRONMENT`, `missing_root_halves`, `owner_vs_actor` | Concrete snapshot-driven `WorkerObservationProviderPort`: put it in `WorkerObservationAdapter(provider=...)` and the adapter (the `WorkerObserver`) and its `root_observer` (the `RootObserver`) check a real worker box, both roots and the write fence. Constructed by nobody by default. |
| `temper_ai.p3_authority.effect_fence` | `DeterministicEffectFenceProvider`, `EffectFenceCheck`, `EffectFencePhase`, `VALID_FENCE_PHASES`, `PHASE_PREDECESSOR`, `decision_evidence_for` | Deterministic phase-bound write fence (`before_request`, `before_admit`, `before_execute`) and side-effect occurrence provider implementing `EffectFenceProvider`; closed and inert by default (`writes_enabled=False`, `fence_open=False`). |

---

## Existing Temper Runtime Seams vs P3 Guarantees

Existing Temper container/runtime primitives are mapped only to their actual
narrow guarantees and are refused whenever presented as complete loaded bytes,
process-origin authority, or observation permission:

| Existing Seam | Actual Guarantee | Refused Overclaims (`refuse_existing_seam_as_complete_coverage`) |
| --- | --- | --- |
| `box_profile.closure` | Static container network/state negative-closure flags | Complete loaded bytes, authentic process origin, child/exec lineage, native host coverage (`RefusalCode.NATIVE_PROVIDER_UNAVAILABLE`) |
| `box_profile.tree_digest` | Pre-run static disk file-tree SHA-256 inventory | Complete loaded bytes, runtime imported modules, dynamic/lazy loads, authentic process origin (`RefusalCode.OBSERVATION_GAP`) |
| `box_view` | Startup sealed-container mount/env/UID/capability snapshot | Pre-interpreter bootstrap loads, complete loaded bytes, post-startup lazy/child loads, host runtime identity (`RefusalCode.OBSERVATION_GAP`) |
| `box_guard` | Static container launch classification (`SEALED`/`LEGACY`/`REFUSED`) | Authentic process origin, complete loaded bytes, observation permission, child birth registration (`RefusalCode.UNAUTHORIZED`) |
| `box_bootstrap` | One-shot stdin secret delivery receipt (`box-delivery/1`) | Pre-interpreter bootstrap loads, authentic process origin, complete loaded bytes, observation permission (`RefusalCode.UNAUTHORIZED`) |

---

## Opt-In Launch and Bootstrap Hook Sites

1. **`temper_ai/spawner/docker_spawner.py` (`DockerSpawner.spawn`)**:
   - Opt-in parameters: `launch_observer: DockerLaunchObservationAdapter | None = None`, `protected_launch: bool = False`.
   - When enabled, `before_container_create` verifies origin, permission, roots, and fences at `A_PRE_CREATE` **before** `_wait_for_old_box_to_go` or `_launch_container`. Missing providers raise `P3ObservationRefusedError` (`RefusalCode.NATIVE_PROVIDER_UNAVAILABLE`). Failed or revoked one-shot deliveries invoke `on_container_launch_failed(..., revoked=True)` while preserving `docker kill` and `state="revoked"` recording.
2. **`temper_ai/cli/main.py` (`take_box_delivery_first`)**:
   - Opt-in parameters: `bootstrap_observer: EarlyBootstrapObservationHook | None = None`, `protected_bootstrap: bool = False`.
   - Keeps all non-stdlib imports after `box_bootstrap.receive()`. Records `bootstrap_pre_interpreter` gaps whenever pre-interpreter module loads were not captured by an attached verified stream.
3. **`temper_ai/runner/bootstrap.py` (`bootstrap_runner_context_from_env`)**:
   - Opt-in parameters: `worker_observation: RunnerBootstrapObservationHook | None = None`, `protected_bootstrap: bool = False`.
   - Runs after `box_bootstrap.require_received()` and **before** `init_database`, `_init_llm_providers`, `_init_memory_service`, or `_load_configs_into_store`.
4. **`temper_ai/agent/script_agent.py` (`ScriptAgent.run`)**:
   - Opt-in via declared `p3_launch_adapter` / `p3_protected_launch` on `ExecutionContext` or `ScriptAgent.config` (checked via `inspect.getattr_static`).
   - Validates planned `A` subject (`workflow_name`, `node_path`, `agent_name`) and pre-spawn authorization before `context.tool_executor.execute("Bash", ...)`.
5. **`temper_ai/tools/bash.py` (`Bash.execute` / `_run_subprocess`)**:
   - Opt-in via `_p3_launch_adapter` / `_p3_protected_launch` (internal `_`-prefixed parameters stripped from LLM tool calls).
   - Verifies `before_spawn` prior to `subprocess.Popen`. Immediately after `Popen`, resolves and registers the child `(pid, start_time_ns, exec_generation)`. If registration refuses, kills and reaps the process group (`_kill_group(proc)`) and records termination without leaking child stdout, stderr, or argv.

---

## P3 T5-N4 Concrete Snapshot Providers (`box_observation_provider` and `effect_fence`)

1. **`temper_ai/p3_authority/box_observation_provider.py` (`BoxObservationProvider`)**:
   - Implements `WorkerObservationProviderPort` (`verify_grant`, `collect_worker_frame`, `collect_root_observation`, `verify_child_launch`), plus `observe_both_roots` and `root_owner_assertions`; `snapshot_reads` counts the snapshot reads made after a grant passed.
   - The service's lookups answer only what the adapter itself accepted, at exactly the selection and boundary it accepted it at, with the same keys as the in-memory doubles: `WorkerObservationAdapter.lookup_worker_observation(selection_revision=, boundary=)`; its `root_observer`: `lookup_root_binding(selection_revision=, boundary=)` (the binding of the latest one-root read the root observer accepted there, whichever root kind or actor made it; a refused read or a refused worker observation there leaves none) and `lookup_root_observation(process_registration=, root_kind=)` (the root accepted for that actor at its selection's latest attempted boundary). A worker frame's roots are kept only once the whole worker observation is accepted; `verify_both_roots` is a pure check that keeps nothing; every attempt first drops what it would replace, so a refused or newer attempt leaves no earlier answer.
   - Where the in-memory doubles differ (both differences fail closed in the adapter): `InMemoryRootObserver` answers the last registered binding and root whatever reads happened later, and its `lookup_root_observation` ignores selection and boundary; the adapter answers none after a refused read or worker observation, and roots only at the selection's latest attempted boundary. A join tested only on the doubles can pass where the adapter refuses.
   - The binding slot `(selection, boundary)` has no root kind or actor in its key: `service.py` `before_create` sees whichever one-root read was accepted last at `A_PRE_CREATE`. Keying by root kind changes `lookup_root_binding`'s signature, the double and the service call together, so it is left to T6 (Architecture W4, Security N2).
   - Container environment: `BoxInspectSnapshot` keeps only `KEPT_ENVIRONMENT` (the box profile variables `box_view` reads, HOME, PATH), never prints it (`repr=False`), and a malformed `Config.Env` entry is named by its index, never echoed.
   - Constructor inputs, all supplied by the caller: `selected_job`, `sealed_profile` (the document `box_profile.compile_profile` sealed), `inspect` (`BoxInspectSnapshot.from_inspect(docker_inspect_json, pid_namespace_id=..., mount_namespace_id=..., user_namespace_id=..., launch_requests=...)`), `worker_frame` (the N3 `SuppliedWorkerFrame`), `actor`, `permitted_observation`, `root_pins` and `root_stats` (per root kind), `effect_fence` and `fence_frontier`. It makes no Docker, host `stat`, database or model call.
   - Checked against the sealed profile, from the inspect snapshot: the profile's image (`image.id`); started with the sealed profile (`box_view.profile_from_env` over the inspected environment, same `box_view.digest_of`); the profile's non-root user; a read-only root; the profile's HOME and PATH; a network the profile names (or none); the launcher's hardening (`SecurityOpt` has no-new-privileges and no `seccomp=unconfined`, `apparmor=unconfined`, `label=disable` or `systempaths=unconfined`; `CapDrop` has ALL; no `CapAdd`, privilege, devices, device cgroup rules or extra groups; a private cgroup namespace); `HostConfig.Tmpfs` equal to the profile's tmpfs list and options; every `Mounts[]` entry at a grant target, a bind from the grant's source with the grant's write access and private propagation, and nothing else mounted; every launch request classified (`box_guard.Guard.check`); no pid/ipc/user/uts/network mode `host` or `container:<id>`; the container id, namespaces and UID/GID of the worker process equal the inspected ones and its pid/mount/user namespaces differ from the host's; for the two roots, the `(dev, ino)` pin the profile grants at the root's mount.
   - Not attested here (this provider sees only what the snapshots show): the `(dev, ino)` pins and type of grants other than the two roots; writable ancestors of `runtime.immutable` paths and of HOME; writable PATH directories; writable import roots (`sys.path`); `runtime.absent` paths being absent; the no-new-privileges flag and effective capabilities as the kernel reports them for the running process. Those are enforced inside the box by `box_view.check_box` at start (`temper_ai/cli/run_workflow.py:117`) and by the launcher's flags (`temper_ai/spawner/docker_spawner.py:1212`, `:1298`: `--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only`), not by this provider. `box_view.view_problems` / `check_box` examine the calling process (`os.getuid`, `/proc/self`, `os.stat`), so they run only inside the box. `temper_ai/spawner/` is reused read-only.
   - A malformed inspect field (missing, wrong type, a mount destination twice, a duplicate `Config.Env` key) raises `ValueError` naming the field.
   - Refusals:
     - Missing or unpermitted `ObservationGrant`, checked before any snapshot is read -> `OBSERVATION_NOT_AUTHORIZED` (another selection -> `SELECTION_CHANGED`; another job -> `DISPATCH_CHANGED`; an actor the grant doesn't name -> `SUBJECT_MISMATCH`).
     - Collapsed host/worker runtime (Docker pid/ipc/user/uts/network mode `host` or `container:<id>`, or a pid/mount/user namespace shared with the host) or container/image/UID/GID/namespace/mount/hardening/profile drift -> `RUNTIME_CHANGED`.
     - Missing half-root (`publication` without `host_evidence` or the reverse), `(dev, ino, generation)` drift, a path that differs, isn't normal or escapes, a root not mounted where the sealed profile grants it with the same `(dev, ino)` pin, both roots one object, or no provenance -> `ROOT_MISMATCH`.
     - Missing read/traverse/write right, a write right through a read-only mount, rights reported for another UID/principal, or the actor owning its root (same UID or principal; checked again by `WorkerRootObservationAdapter.verify_both_roots` through `actor_owns_root`) -> `RIGHTS_MISSING`.
     - Absent, closed or write-disabled fence -> `WRITES_DISABLED`; a fence bound to another selection, job or actor -> `SELECTION_CHANGED`, `DISPATCH_CHANGED`, `SUBJECT_MISMATCH`; stale frontier after a wait -> `RUNTIME_CHANGED`.
     - Child launches -> `PEER_UNVERIFIED` (not this provider's; children are N3W's).
2. **`temper_ai/p3_authority/effect_fence.py` (`DeterministicEffectFenceProvider`)**:
   - Implements `_providers.EffectFenceProvider` (`record_admission`, `record_execution_leg`, `mark_counted`, `lookup_occurrence`, `lookup_history`) and phase-bound write fence checks (`verify_fence`, `before_request`, `before_admit`, `before_execute`).
   - Closed by default (`writes_enabled=False`, `fence_open=False`); `WRITES_ADMITTED` remains `False`. An open or write-enabled fence must be built with its `selected_job`, `fenced_actor` and `expected_frontier` (else `ValueError`), and it compares the whole selected job, not only its selection revision.
   - Phases are kept per request only: each request walks `before_request` -> `before_admit` -> `before_execute` itself; another request's phases never count, and an earlier phase after a later one is refused.
   - Record path: `record_admission` needs the request's own `before_admit`, and `record_execution_leg` and `mark_counted` its own `before_execute`, each passed at the frontier the fence expects now. `service.py` calls only the record methods today and never the `before_*` checks, so with this provider every record it makes is refused `WRITES_DISABLED` until the Wave 2 join calls the phases at their points (Architecture W1).
   - Refusals:
     - `writes_enabled=False`, `fence_open=False`, `fence_available=False`, an unpermitted phase, a phase out of order for its request, or a record without its own phase -> `WRITES_DISABLED`.
     - Another selection -> `SELECTION_CHANGED`; another job with the same selection revision -> `DISPATCH_CHANGED`; another actor -> `SUBJECT_MISMATCH`. (There is no open fence without a selected job, so the round-1 `AUTHORITY_UNAVAILABLE` branch is gone: building one raises `ValueError`.)
     - Stale frontier after a wait (`advance_frontier` / `mark_frontier_stale`), or a phase passed at an earlier frontier than the fence expects now, or window drift -> `RUNTIME_CHANGED`.

