# Independently authored full-graph supplement (#316)

Fixture-only, synthetic, non-runnable. All runtime predictions are UNEXECUTED.
This additive packet repairs #306's compiler-input gaps. It neither replaces nor
edits the historical packet, and it is not candidate-admission/v2. The unchanged
#192 candidate-admission/v1 schema/spec are the only wire contract.

## Read in this order

1. `source-facts.json`: immutable source/contract/old306 pins, complete field and
   type inventories, exact defaults, accepted-key membership and factory names.
2. `INPUT/closure.json` and `INPUT/native.json`: candidate-side raw literal data.
3. `EXPECTED/graph.json`, `EXPECTED/identities.json`: independently written full
   effective graph, explicit identity correspondence and script occurrence data.
4. `INPUT/request.json` and `EXPECTED/request.json`: separately authored request
   options, with the authoritative closed T2 declaration cited in EXPECTED.
5. `EXPECTED/case-mapping.json`: every unchanged V01–V36 variant's explicit ID.
6. `wire-mapping.json`: complete source-to-frozen-v1 correspondence, not a codec
   or alternative schema. `manifest.json` binds these fixture bytes.
7. `docs/architecture/admission-oracle-v1-supplement.md`: hypothesis, original
   results, source/type reconciliation and limitations.

The request files follow Temper's closed, pre-commit T2 #198 declaration
(rm-31e24c00; REQUEST-OPTIONS.md SHA256 b6347a80…823a over base caf5c16f). It is
source metadata, not final CI evidence; rebind if that source moves.

## Two independent sides

INPUT contains one workflow, fourteen stages and three shared script agent
records. Its native table has 42 complete literal rows and an explicit common
five-field envelope: combine each row's native fields with that literal envelope
to obtain its raw agent record. The table's raw_record_id/node_path are fixture
index columns, not native config keys. Together there are **60 raw records**.
The raw Config schema_version is the exact string `"1.0"` for every record; packet
format numbers have no relationship to that field. All raw origins are synthetic
DB classifications. No actual database is read and file_base64 is null.

EXPECTED contains **126 literal nodes** in preorder: fourteen stages, 42 native
calls and 70 script occurrences. Each row names its exact children/predecessor,
full input mapping and policy differences. The separate literal node_envelope
contains every remaining effective default and the complete metadata membership.
The workflow retains all thirteen effective fields, including _KNOWN_FIELDS.
A path in a node's children is a storage reference to another EXPECTED row; a
consumer substitutes that exact row, not a value resolved from INPUT.

All fourteen roots are complete. Within each root:

    prepare → call_A1 → account_A1 → call_A2 → account_A2
            → call_A3 → account_A3 → receipt

Roots r01 through r14 are serial, with each root depending on the preceding
root. Only receipt runs after failure. No preparation/accounting/receipt edge
is inferred from a call's position. The test checks every edge and deliberately
breaks each of the 112 child edges independently.

Native EXPECTED values reuse only the pinned, unchanged #306 **EXPECTED** table
of all 42 full maps. INPUT values were written independently; neither side reads
the other. Script EXPECTED values reuse only #306's five independently pinned
effective script configs. Each of the 70 occurrences explicitly selects its old
key and literal record variables. The new source-pinned inherited _KNOWN_FIELDS
is retained alongside on_max_loops, gate and run_after_failure. Script bytes are
never executed, rendered or printed by the suite.

The explicit identities table maps every legacy rNN/AN position and dotted old
node label to a wire-safe rNN_AN position_id, a path array, record_id, variant_id,
call_id, preparation path and slot. These are **synthetic fixture identities**,
not candidate registration, run declarations, allocated UIDs or authority. No
slash/dot/path-to-ID conversion is allowed. Every root_policy is null.

## Source and wire reconciliation

* Old #306 deliberately supplied a complete graph only for r01: eight raw
  records, nine nodes and three calls. Its 42-position inventory was not a full
  compiler input. All eleven original paths and eight manifest members remain
  byte-identical; their hashes are tested, not silently repaired.
* Old #306 raw schema_version is integer 1. Source Config/ConfigStore declare
  string `"1.0"`; frozen v1 requires a string. Only this new supplement corrects
  the fixture. No cast is performed and int, bool, float and null are rejected.
* Workflow and NodeConfig metadata are complete. Only the exact engine-owned
  frozenset[str] _KNOWN_FIELDS has v1's sorted-string-array projection. An input
  list, candidate-supplied metadata or any other set is not that runtime type.
  Source/AST evidence supports this projection; runtime enforcement is untested.
* Full qualified ScriptAgent/SingleCallAgent bindings are pinned. Native optional
  absence stays absence; all other types/nulls/defaults stay exact.
* The old source basis 876e2b6 is not the new declaration source, the T2 candidate
  entry declaration or an installed runtime. Those pins remain separately named.
* v1 source.field_sets are literal in source-facts.json wire_field_sets:
  workflow (13) and node (36) include _KNOWN_FIELDS; native is the 24 inner
  SINGLE_CALL_SETTINGS keys as a permitted set, not the envelope and not a
  flattened union (Temper rm-ae19e128). Each call keeps its exact present keys.
* The request-options closed field set is taken only from Temper's authoritative
  declaration. The frozen wire schema cannot supply missing application options.
  It is exactly inputs, notify, workflow and workspace_path, all always present:
  workflow is a required string (workflow_name is only an input alias); inputs is
  a dict, null invalid; workspace_path and notify default to null. admission is
  descriptor transport only and never an option. Run ids, execution UUID, pins,
  nonce and worker identity are not options.
* Request inputs carry only record_id, as old #306 did. metadata_inputs equals
  those caller inputs exactly; the other thirteen record inputs are left to
  workflow defaults and never filled into metadata or options. Options name the
  descriptor's workflow and its exact workspace_path. Candidate identity, logical
  run id, execution UUID and workspace are labelled synthetic 316 identities,
  distinct from old #306's run_id and workspace.
* All v1 rawRecord/expectedRaw/graph/node/factory/position/script/source/descriptor
  fields have explicit correspondence in wire-mapping.json. Fixture-file hashes
  are not v1 domain digests. Use v1 CAJ-1 and its exact digest domains downstream.

## Standalone checks

Run from the repository root, without pytest/conftest or production imports:

    python3 -I tests/test_architecture/test_admission_oracle_supplement.py

The stdlib-only module checks strict JSON (duplicate/nonfinite rejection), exact
raw-reference closure and preorder membership, exact 42-path equality on both
sides, all full native maps, all serial edges, complete source/metadata/factory
inventories, explicit identities, closed request options, v1 field correspondence
and the retained 36-case/variant mapping. It reads source declarations via AST
only; source byte hashes are provenance at basis 56b833e6, checked by git at
open and close rather than in the lasting suite. It does not import or run the codec,
compiler, loader, normalizer, preparer, engine or model clients.

Known negatives include missing roots/calls, orphan/extra positions, changed
serial edges, integer/bool versions, omitted/wrong metadata, wrong factories,
missing/extra/wrong-typed options, filled defaults, null or mismatched
workspace, alias or admission keys, changed declaration pins, invalid or
confused descriptor identities, missing/colliding identities, wrong valid slots,
whole-map swaps and changed INPUT with a recomputed self hash. Hash consistency
is never used to manufacture EXPECTED semantics. V01–V36 keep their original
meanings, counters and runtime-status labels; this is not a runtime replay.

The isolation claim covers inspected source/imports and the standalone process,
not a hostile kernel or whole-engine isolation. Normal repository commit/land
checks are separate from the stdlib-only focused campaign. Normal local SQLite
and exact-head remote PostgreSQL/static-Chromium checks remain required. No
local Postgres/browser/second Temper, deployment, restart or model call is used.

## Not evidence of readiness

No real roots, grants, ownership/UID attestations, source attestations, registration,
custody, preparation receipt, claim, capability, provider access or runtime
execution is supplied. authority/custody/installed_source_attestation stay null;
runnable stays false. Required wire fields are not filled with guessed authority.
The later compiler must bind actual candidate declarations without treating this
fixture source mapping as installed/runtime proof. #293 is not released.
