# P3 T4 Disabled Native-Boundary Consumer (`first_app_p3_native.py`)

## Purpose and Scope

`configs/architecture/bin/first_app_p3_native.py` and the disabled hooks in `configs/architecture/bin/first_app_p3_host.py` implement the Project 3 (`#125` / T4) disabled native-boundary consumer and offline result join over the delivered, accepted supplier exports:

- **Systems `#71` (`bfef9a61727819673fcb5df2a4f179d4c184f435`)**: `p3_source_closure` and `configs/architecture/bin/ops_host_source_comparison.py` (`NativeClosureExpectation`, `VerifiedClosureOrigins`, `LoadedClosureEnvelope`, `ReviewedSourceGraph`, `SourceClosureComparison`, `N3Coverage`, `N3Gap`, `N3ObservationEpoch`, `N3SourceEpoch`, `compare_loaded_source`, `validate_loaded_envelope`, `validate_reviewed_graph`).
- **Ops `#751` (`e30562b1244020638f671964272c47abb0a83c60`)**: `p3_host_contracts` generic host records (`RawRef`, `ProjectSelection`, `CalibrationSelection`, `CallerSelection`, `SelectedHostJob`, `ProcessInstance`, `RootScope`, `RootBinding`, `ObservationScope`, `HostObservation`, `HostCoverage`, `HostEffect`, `EffectLease`, `LifecycleKey`, `RowKey`, `OperationKey`, `OccurrenceHandle`, `RawPublication`, `ReceiptProvenance`, `HostClosureJoin`).
- **Temper `#261` (`6363983af8dc9013e5326c59df76a900ee0c2f47`)**: `temper_ai.p3_authority.contract` (`DECISION_SCHEMA`, `AcceptedData`, `Refusal`, `RefusalCode`, `Result`, `Phase`, `RetryKind`, `AdmissionState`, `EffectState`, `SequenceUse`, `P3AuthorityRegistry`, `P3NativeBoundary`, `NativeHostJoin`, `WorkerObserver`, `RootObserver`, `CreateArmDecision`, `CheckerDecision`, `RequestDecision`, `AdmissionDecision`, `ExecutionDecision`, `CountDecision`, `VerifiedReceiptBinding`, `NativeReceive`, `WindowBinding`, `CheckerBinding`, `ImmutableRequestBinding`, `AdmittedRequestBinding`, `WorkerObservation`, `RootObservation`, `BothRootObservations`).
- **Temper `#262` (`172fd7fe3f45fc7816df4947e0c5db0b07abf7b2`)**: `temper_ai.p3_authority.service`, `registry`, `candidate_bindings`, `_providers`, and `temper_ai.runner.admission` (`DEFAULT_CANDIDATE_BINDINGS = None`, `P3AuthorityComposition`, `P3AuthorityService`, `NativeHostJoinAdapter`, `compose_p3_authority`, `AuthorityRegistryService`, `P3CandidateBindings`, `SystemsSourceClosureComparator`).
- **Temper `#263` (`4310ca7f090780c805ad3276ab1716586a512c01`)**: `temper_ai.p3_authority.worker_observation`, `child_registration`, `coverage_bookkeeping`, and `launch_adapters` (`WorkerObservationAdapter`, `RootOwnerVsActorAssertion`, `ChildRegistrationTable`, `CoverageBookkeeper`, `DockerLaunchObservationAdapter`, `EarlyBootstrapObservationHook`, `RunnerBootstrapObservationHook`, `WORKER_OBSERVATION_COMPAT_CORPUS_ID`, `EXISTING_TEMPER_SEAM_GUARANTEES`, `refuse_existing_seam_as_complete_coverage`, `build_worker_observation_compat_cases`, `validate_compatibility_profile`), with corrected corpus registration `#277` (`CORPUS-REGISTRATION.md` sha256 `1407ca93454b73867497a95efb6a29961e8c9474c007f2758bc4a7672904a6fd`) verified against Ops `#760` (`57a1988bba9b3bef65fa161fd188fae292300b92`, `ops760-temper263-reregistration-source-v1`, 33/33 PASS).

## Guard-First and Disabled Posture Invariants

1. **`WRITES_ADMITTED = False` and `DEFAULT_CANDIDATE_BINDINGS = None`**:
   - Both `first_app_p3_host` and `first_app_p3_native` keep `WRITES_ADMITTED = False` and `DEFAULT_CANDIDATE_BINDINGS = None`.
   - `DEFAULT_NATIVE_BOUNDARY`, `DEFAULT_NATIVE_HOST_JOIN`, and `DEFAULT_WORKER_OBSERVER` are `None`.
   - `compose_disabled_consumer_service(**kwargs)` enforces `writes_enabled=False` and raises `ValueError` if called with `writes_enabled=True`.
2. **Short-Circuit Before Input Inspection (`H1`)**:
   - While `WRITES_ADMITTED` is `False`, `open_host`, `settle`, `run_row`, and `join_native_host_row` return `BLOCKED` with `reasons=[WRITES_OFF]` (or return immediately in `settle`) before inspecting `host`, `row`, `native_boundary`, clocks, sleeps, or filesystem paths.
3. **Offline Consumer Result Join (`H2`)**:
   - `evaluate_offline_native_join(...)` and `join_offline_supplier_results(...)` join `P3AuthorityService` (`before_create`, `before_checker`, `before_request`, `before_admit`, `before_execute`, `before_count`), `NativeHostJoin` (`lookup_occurrence`, `verify_publication`, `receive`), `p3_source_closure.compare_loaded_source`, and `WorkerObservationAdapter` (`observe`, `root_observer.verify_both_roots`).
   - Even when every injected offline supplier stage returns `AcceptedData` and `SourceClosureComparison(disposition="MATCH", reasons=())`, the outer evaluation remains `status="UNQUALIFIED"` and `count_eligible=False` while `WRITES_ADMITTED` is `False`. It never returns `status="PASS"`.
   - Any refusal in authority, worker observation, both-root verification, or native receive, or any `SourceClosureComparison` with `disposition != "MATCH"` or non-empty `reasons`, transitions the joined status to `"BLOCKED"` and records the exact refusal codes, phases, and closure reasons.
4. **Unresolved Native Obligations (`N1–N8`) and `R1–R5` Preservation**:
   - All eight native obligations (`N1` through `N8`) remain `"UNRESOLVED"`.
   - Host rows `R-1`, `R-1i`, `D-1`, and `D-5` remain `"UNQUALIFIED"`.
   - `P5` assessment remains `"UNTRUSTED"`.
   - Caller wire semantics (`R1–R5` in `first_app_p3_caller.py` and `first_app_p3_host.py`) are unchanged.
