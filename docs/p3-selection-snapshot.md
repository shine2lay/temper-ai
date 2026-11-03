# P3 Selection Snapshot & Request History Providers (T5-N2)

`temper_ai/p3_authority/selection_snapshot.py` provides the read-only, runner-backed `SelectionSnapshotProvider` and `RequestHistoryProvider` implementations for P3 authority composition (`AuthorityRegistryService`), joining Temper's own run and admission records (`DbAdmissionTransport`, `DispatchIdentity`) to `p3_host_contracts.selection.SelectedHostJob`.

## Scope & Switch-Off Invariants

- **Inert by default**: `WRITES_ADMITTED: Final[bool] = False`, `DEFAULT_SELECTION_SNAPSHOT_PROVIDER = None`, and `DEFAULT_REQUEST_HISTORY_PROVIDER = None`.
- **Read-only over `DbAdmissionTransport`**: Queries `WorkflowRun` and verifies the persisted `AdmissionRecord` (`spawner_metadata["config_admission"]`) through `DbAdmissionTransport._row_record` and `DbAdmissionTransport._descriptor`. Never issues `INSERT`, `UPDATE`, `DELETE`, or DDL statements.
- **Anti-spoofing**: Selected job, kit (`ProjectSelection`), calibration (`CalibrationSelection`), and execution route (`external-db-fresh`) are derived strictly from the admitted run record and `RunSelectionBinding`, ignoring caller flags (`WorkflowRun.inputs`) and process environment variables.

## Public Symbols

- `WRITES_ADMITTED`: `Final[bool] = False`
- `SUPPORTED_SELECTION_ROUTE`: `Final[str] = "external-db-fresh"`
- `DEFAULT_SELECTION_SNAPSHOT_PROVIDER`: `Final[SelectionSnapshotProvider | None] = None`
- `DEFAULT_REQUEST_HISTORY_PROVIDER`: `Final[RequestHistoryProvider | None] = None`
- `RunSelectionBinding`: Immutable binding tying an admitted `execution_uuid` and `DescriptorAuthority` to a P3 `Selection` (`ProjectSelection` or `CalibrationSelection`), `selector_issuer`, `authority_refs`, `reviewed_closure_ref`, `compatibility_profile`, and optional `expected_dispatch` (`DispatchIdentity`).
- `DbSelectionSnapshotProvider`: Implements `SelectionSnapshotProvider` (`read_snapshot() -> SelectionSnapshot | None`) and `join_host_job(...) -> Result[SelectedHostJob]`.
- `DbRequestHistoryProvider`: Implements `RequestHistoryProvider` (`lookup_history(request_identity: RequestIdentity) -> PriorRequestHistory`), returning recorded history only when the run's DB admission envelope verifies cleanly.
- `RequestHistoryEntry`: Immutable request-history entry keyed by `execution_uuid` and `RequestIdentity` (`RowKey`).
- `HostSelectionHandle`: Immutable handle pairing `selection_reference` and `selection_revision` for `SelectedHostJob` and `RowKey`.
- `project_selected_host_job`: Projects an authoritative `SelectedJob` into `p3_host_contracts.selection.SelectedHostJob`.
- `verify_selected_host_job`: Cross-checks a candidate `SelectedHostJob` against the authoritative `SelectedJob`.
- `verify_boundary_transition`: Verifies `SelectedJob` continuity across `for_submit`, `for_run`, and `check_current` boundaries.

## Refusal Matrix

| Condition | Refusal Code |
|---|---|
| Missing DB run row, missing/invalid admission envelope, or empty snapshot | `RefusalCode.SELECTION_MISSING` |
| Multiple competing active selections for the same workflow, dispatch, or revision | `RefusalCode.SELECTION_AMBIGUOUS` |
| Foreign `run_id`, `project_id`, `kit_id`/`kit_sha256`, calibration identity, or `RequestIdentity` | `RefusalCode.SELECTION_FOREIGN` |
| Descriptor digest, source closure digest, authority receipt, or `selection_revision` drifted between `for_submit`, `for_run`, and `check_current` | `RefusalCode.SELECTION_CHANGED` |
| Route is not `"external-db-fresh"` in binding or admitted descriptor | `RefusalCode.ROUTE_UNSUPPORTED` |
| `DispatchIdentity` (`execution_uuid`, `dispatch_nonce`, `running_attempt`) changed after claim | `RefusalCode.DISPATCH_CHANGED` |
| Unconfigured transport (`transport=None`) | `RefusalCode.AUTHORITY_UNAVAILABLE` |
