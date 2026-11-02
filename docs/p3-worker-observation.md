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
  collection, native issuer/grant authority, and effect fences remain
  unimplemented (`UNKNOWN` / refused). All 8 native join capabilities remain
  unresolved, 4 matrix rows remain `UNQUALIFIED`, P5 remains `UNTRUSTED`, and
  writes remain off.

---

## Public Modules and Callable Imports

| Module | Primary Types & Functions | Responsibility |
| --- | --- | --- |
| `temper_ai.p3_authority.worker_observation` | `WorkerObservationAdapter`, `WorkerRootObserverAdapter`, `WorkerObservationProvider`, `SuppliedWorkerFrame`, `EXISTING_TEMPER_SEAM_GUARANTEES`, `refuse_existing_seam_as_complete_coverage`, `build_worker_observation_compat_cases`, `validate_worker_observation_compat_corpus`, `map_host_envelope_gaps` | Implements `WorkerObserver` and `RootObserver` from `temper_ai.p3_authority.contract`; enforces pre-collection permission (`verify_observation_grant`), distinct `HostObservation` vs `WorkerObservation` runtimes, `publication` vs `host_evidence` roots (`BothRootObservations`), `RootOwnerVsActorAssertion` (`expected_owner != effective_actor`), and `ops-host-compat-corpus/1` (`temper.t4.worker.*`) worker cases. |
| `temper_ai.p3_authority.child_registration` | `ChildRegistrationTicket`, `RegisteredChildGeneration`, `ChildRegistrationRegistry`, `refuse_surrogate_child_registration`, `VERIFIED_LAUNCHER_REGISTRATION_SOURCE`, `NON_PROVIDER_REGISTRATION_SOURCES` | Enforces provider-verified child birth and `exec` generation lineage (`(pid, start_time_ns, exec_generation)`); refuses PID reuse (`PID_REUSED`), foreign parent/dispatch (`DISPATCH_MISMATCH`), and env/UID/owner/profile surrogates (`UNAUTHORIZED`); prevents data-class construction from registering a process. |
| `temper_ai.p3_authority.coverage_bookkeeping` | `CoverageBookkeeper`, `ProcessLoadPolicy`, `SyntheticStreamAuthTag`, `SyntheticLoadStreamEvent`, `SyntheticFrontierEvent`, `StreamCheckpointSummary`, `SystemsClosureComparisonAdapter`, `closure_outcome_to_refusal_or_ok` | Tracks authenticated synthetic load streams, sequence/epoch monotonicity, dropped-event windows (`NativeEventRange.dropped_events`), required vs permitted per-process loads, category gaps (`bootstrap_pre_interpreter`, `transitive_import`, `generated_code`, `bytecode_cache`, `lazy_runtime_import`, `native_extension`, `child_exec_lineage`), wait/resume causal frontiers (`STALE_FRONTIER`), and delegates semantic comparison exclusively to Systems' `compare_loaded_source`. |
| `temper_ai.p3_authority.launch_adapters` | `DockerLaunchObservationAdapter`, `EarlyBootstrapObservationHook`, `RunnerBootstrapObservationHook`, `ScriptLaunchObservationAdapter`, `BashChildLaunchAdapter`, `P3ObservationRefusedError` | Explicit opt-in adapters for `DockerSpawner.spawn`, `take_box_delivery_first`, `bootstrap_runner_context_from_env`, `ScriptAgent.run`, and `Bash.execute`. |

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
