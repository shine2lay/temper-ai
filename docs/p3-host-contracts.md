# Host contract records

`p3_host_contracts` is a dependency-free Python source leaf for immutable host
record data. Import its public names from the package root. It imports only
`dataclasses`, `typing`, and its own modules; it does not load the application,
reference suppliers, adapters, services, or a source-closure implementation.
Construction does not read files, inspect processes, contact services, or look up
credentials.

**Data is not authority.** Constructing these records, including an
`OccurrenceHandle`, does not authenticate any reference, admit an effect, prove
execution, or validate a publication. A same-shaped reference is still merely
data. Authenticated consumers must bind the actual canonical supplier types and
perform the supplier's independent verification. Native result/refusal types,
issuance, observation, comparison, wire formats, and service implementation are
not part of this package.

## Public surface

The package exports 19 frozen, slotted dataclasses and one union alias. Fields
below are listed in constructor order; every argument is required. An optional
field requires an explicit value, including explicit `None`; no defaults are
inferred. Source annotations are the authoritative types.

| Export | Fields |
| --- | --- |
| `RawRef` | `root_locator, relative_path, byte_length, sha256` |
| `ProjectSelection` | `project_id, kit_ref, expected_binding_ref` |
| `CalibrationSelection` | `manifest_ref, entry_id, round_id, calibration_run, copy_id, expected_binding_ref` |
| `CallerSelection` | `entrypoint, source_review_ref, caller_role, writer, allowed_rows, inspect_variant, runtime_route` |
| `SelectedHostJob` | `selection, job_id, attempt_id, publication_id, build_ref, route, creator_launch_id, caller` |
| `ProcessInstance` | `native_identity, host_instance_id, boot_id, pid_namespace_id, pid, start_identity, exec_generation, launch_id, parent_instance, role, runtime_ref, container_instance, mount_namespace_id, user_namespace_id` |
| `RootScope` | `role, actor, selected_locator, expected_existing_object, new_leaf, required_rights` |
| `RootBinding` | `role, object_identity, actor_instance, namespace_and_mount_identity, actor_visible_path, host_visible_path, rights, grant_refs, validity, mapping_witness` |
| `ObservationScope` | `selection, phase, subjects, root_scopes, purpose, permitted_fields, reviewed, protected_effects, interval` |
| `HostObservation` | `selection, process_instances, roots, observed, source_epoch, observation_epoch, event_range, observed_interval, coverage, gaps, native_witness` |
| `HostCoverage` | `observation, comparison, native_binding, through_boundary, live_watch` |
| `HostEffect` | `kind, selection, target, operation, actor, purpose, roots, boundary` |
| `EffectLease` | `native_admission, effect, actor_instance, source_epoch, observation_epoch, validity, revocation_revision, boundary_token` |
| `LifecycleKey` | `selection, launch_id, operation_id` |
| `RowKey` | `selection, window_id, binding_ref, writer, row, operation, request_id, sequence, request_raw_ref` |
| `OperationKey` | Alias: `LifecycleKey[SelectionT] \| RowKey[SelectionT]`; not a new record |
| `OccurrenceHandle` | `key, witness, admitting_process, controller, executing_processes, route_witness, targets, source_epoch, observation_epoch, admission_boundary, state` |
| `RawPublication` | `occurrence, producer_instance, publisher_instance, request_raw_ref, receipt_raw_ref, evidence_refs, window_ref, numbered_log_ref, current_row_ref, publication_steps, observed_interval, outcome, cleanup_state` |
| `ReceiptProvenance` | `occurrence_witness, publication_witness, issuer_scope_ref, operation_key, producer_instance, publisher_instance, raw_publication, state, predecessor, disarm_relation` |
| `HostClosureJoin` | `selection, candidate_ref, host_review, worker_review_ref, host_observed, worker_observed_ref, comparison, native_witness` |

Selection, process/root, effect, observation, and publication modules each own a
single record family. Package-root exports re-export those definitions rather
than constructing a second set of classes. Helpers and type variables are
internal, not additional root exports.

## Opaque generic roles

Each external role has its own independent type parameter. This leaf defines no
native capability, placeholder service record, closure schema, or version
literal. The names in the right column designate supplier roles, **not classes
implemented here**:

| Parameter | Canonical supplier role |
| --- | --- |
| `SelectionT` | Temper `NativeSelection` |
| `WitnessT` | Temper `NativeWitness` |
| `AdmissionT` | Temper `NativeAdmission` |
| `ProcessT` | Temper `NativeProcessRef` |
| `BirthT` | Temper `NativeBirthIdentity` |
| `ContainerT` | Temper `NativeContainerIdentity` |
| `RootObjectT` | Temper `NativeRootObject` |
| `SubjectT` | Temper `NativeSubject` |
| `TargetT` | Temper `NativeEffectTarget` |
| `GrantT` | Temper `NativeGrantRef` |
| `IntervalT` | Temper `NativeInterval` |
| `FieldsT` | Temper `NativeObservationFields` |
| `EventRangeT` | Temper `NativeEventRange` |
| `DisarmT` | Temper `NativeDisarmRelation` |
| `WatchT` | Temper `ObservationSession` |
| `ReviewedT` | Systems `N3Reviewed` |
| `ObservedT` | Systems `N3Observed` |
| `ComparisonT` | Systems `N3Comparison` |
| `SourceEpochT` | Systems `N3SourceEpoch` |
| `ObservationEpochT` | Systems `N3ObservationEpoch` |
| `CoverageT` | Systems `N3Coverage` |
| `GapT` | Systems `N3Gap` |

Parameter order is explicit in each class's `Generic[...]`. For example,
`CallerSelection[ReviewedT]`, `SelectedHostJob[SelectionT, ReviewedT]`, and
`ProcessInstance[WitnessT, BirthT, ProcessT, ObservedT, ContainerT]` have distinct
roles; nested record annotations carry the same parameters through the graph.
`OperationKey[SelectionT]` preserves the selection type in both alternatives.
Consumers annotate their own aliases with the canonical types and construct
values using the unspecialized dataclass constructor. No runtime import of a
supplier is needed in the leaf. Do not replace the roles with a single
unconstrained type or copy provider definitions into this package.

Native sessions, permissions, receive results, joins with services, and closure
version records that do not occur as fields here remain entirely with their
suppliers. An annotation or a structural match is not evidence that a supplier
exists or that authentication has succeeded.

## Shape checks and semantic boundaries

- Frozen fields and exact `tuple`/`frozenset` containers reject mutable collection
  substitutes rather than silently converting them. Tuple order is retained.
  Opaque reference internals are not inspected, cloned, frozen, or authenticated;
  their supplier owns their immutability, lifetime, and validity. A frozen Python
  dataclass is not a security boundary against deliberate Python mutation.
- `byte_length` is an integer at least zero. `pid` and `sequence` are positive
  integers. `bool`, numeric text, and floats are not integers here. No upper
  identity bound, TTL, count limit, or new policy is imposed.
- Text is preserved exactly: no trimming, case folding, Unicode normalization,
  path resolution, digest rewriting, or serialization. `RawRef` describes bytes;
  it does not load them or contain a decoded replacement. Existing safe readers
  remain responsible for path/digest/access checks and exact-byte verification.
- Closed literals are checked exactly: inspection `/1` or `/2`; root role
  `publication`, `host-parent`, or `host-evidence`; observation phase `A`, `B`, or
  `C`; and the effect, occurrence, publication, cleanup, and provenance choices
  listed in source annotations. Unknown alternatives are not fallback values.
- Other string fields such as writer, row, runtime route, operation, boundary,
  and rights belong to the **independently selected existing domains**. This leaf
  has neither a dispatcher nor a selected-domain registry. It preserves those
  strings without inventing or broadening the allowed values. A consumer must
  check membership and exact agreement with its selected domain before use.
- Required references cannot be `None`; optional absence is never guessed.
  In particular, parent/container absence needs independent establishment,
  missing root identity is not a wildcard, and missing predecessor does not
  prove an initial operation.
- A row occurrence needs a controller. `started` or `completed` occurrence data
  needs executing-process references. Other states alone cannot establish
  whether execution already occurred; that is a verifier obligation.
- Lifecycle operations have no fabricated row sequence. Lifecycle publication
  may explicitly lack request/window/numbered-log/current-row references. Every
  row-final publication requires all four, for every outcome; incomplete row
  production must instead be recorded by native steps, not an optional success.
- A point comparison is not continuous coverage. Matching spellings, hashes,
  process numbers, keys, epochs, or record equality never replace independently
  verified selection, kernel birth, source applicability, event continuity,
  grants, revocation, actual production, or disarm relations. Cross-record
  consistency and external validity are the authenticated consumer's job.

Bad local shapes raise `TypeError` or `ValueError` with field-only diagnostics,
not a native acceptance/refusal result. External references are never formatted
into those errors. No fallback issuer, trusted flag, adapter, comparator, or
serializer is provided.

## Source checks and distribution

Run the isolated standard-library tests from a source checkout using its
supported Python environment:

```sh
uv run --no-sync python -m unittest discover -s tests/test_p3_host_contracts -p 'test_*.py'
```

The tests use newly authored synthetic values, enumerate fields and type
parameters, check immutable shapes and closed alternatives, distinguish row and
lifecycle publication, and prove that same-shaped data is not authentication.
Subprocess cold imports block application/provider imports and host/secret/service
hooks; negative controls prove that the guards reject those actions. Import
loader reads of Python source/bytecode are the only permitted file reads there.
No root pytest bootstrap or running application is required.

The existing **temper-ai distribution** owns packaging. This source leaf is not
a separately versioned or separately published distribution. Packaging must
include this directory, preserve its import identity, and supply any necessary
typing metadata. The distribution owner must build from the exact reviewed
source commit, record the actual built artifact digest, and test imports in a
clean installed environment outside the checkout, with no editable install or
source-path fallback. A source-checkout import does not establish wheel contents,
installed import purity, native integration, or runtime availability. No such
proof or publication is claimed by this source package.
