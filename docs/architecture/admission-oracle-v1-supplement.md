# Independent admission-oracle v1 supplement (#316)

Status: WORKING; fixture-only, non-runnable. Accountable lead: Architecture.
No runtime, custody, installed-source, quality or readiness acceptance.

## H-A1-ORACLE-2 — written before fixture changes

Evidence: #311 found eight raw records/nine nodes/three calls for r01 in #306,
while its position table has 42 entries. Independent README inspection confirms
its complete graph is deliberately limited to r01. The old raw schema_version
is an integer whereas Config and frozen #192 require a string. Its 17 passing
tests establish packet consistency, not complete compiler input.

Change: add a separate full-graph/source-and-wire reconciliation supplement,
with independently authored EXPECTED data. Never modify the historical packet
or derive expected semantics from a compiler, codec, engine, loader, normalizer,
preparer, client or observed production output.

Expected result: exact 42-path equality and complete typed field mapping pass;
missing graph/metadata/factory/identity, wrong types and coordinated whole-map
corruption fail against unchanged independent expectations. An uncovered
position, synthesized expected answer, failing clean control, missed planted
defect, or source/contract coercion falsifies this hypothesis. Test after all
changes; record original results before any bounded repair. Runtime predictions
stay UNEXECUTED. This is a fixture repair, not a model experiment.

## Opening pins (2026-10-25)

Fresh `wt new arch-316-oracle-supplement temper-ai`, normal master:
commit `56b833e6e6e990e966a1e61a204fd92c5c9f690a`,
tree `7094010accaf2164e2cb54fd9f20ba5f4006f22a`,
parent `499e66fb4b34cc7c749b78b8e6cc13e35ff7ddbf`.
No unlanded #192 branch is based on or merged.

Original #306 source basis remains separately identified as
`876e2b677a5eeb38a0371d2004cd31ae12aa0c08`.
Frozen #192 structure-only consultation:
commit `caf5c16f6d9965cbcbc8e10653d75e1c47b27340`,
tree `726bf8e8a198f1436bf8caf84bbf2a8115601e47`,
parent `86a9f21fa495c6894289f243061d7ab51ab18531`;
schema SHA256 `426e1c5a12eafa5a82e64144d25e0fa08d5b844149723ea001a76fe9a0f2041d`,
spec SHA256 `8932a4b97d0d08bea6a919223f83922804d08486545d94d747886253b5825ba7`.

Only additive supplement files, its standalone test module and this report may
change. INPUT and EXPECTED remain physically separate. Current synthetic script
and request contents are never printed in chat, even for diagnostics.

## Structural declaration (asked, then received)

Question rm-78058d55 asked Temper for the closed T2 request-options names,
types/defaults/nullability and actual candidate-entry declaration with immutable
source references. #192 structure alone is not that declaration. Graph work
continued in parallel; nothing was invented and all of #198 was not awaited.
Temper answered in rm-31e24c00; see "Request-options declaration" below.

## Independently written supplement

`configs/architecture/stages/context_profile/admission_oracles_v1_supplement/`
contains separate INPUT and EXPECTED storage. INPUT declares 60 raw records
(one workflow, fourteen stages, three shared script agents and 42 native agents).
EXPECTED explicitly lists 126 nodes (14 roots, 42 calls and 70 script occurrences),
all 42 position/path/identity mappings, every serial edge and all inherited
metadata/defaults. These are written fixture inventories, not runtime observations.

Native EXPECTED maps and script bodies reuse only immutable #306 EXPECTED data;
no INPUT, engine, compiler, codec, normalizer, preparer or model output derives
an answer. Legacy position strings and dotted paths map through explicit literal
rows, never path-to-ID coercion. The new raw Config version is exactly string
`"1.0"`; old integer 1 remains unchanged. Workflow's full thirteen fields and
NodeConfig's full 36 fields retain source-correct metadata. Native allowed keys,
optional absence and qualified factory classes are pinned separately from the
fixture's actual present fields. The full source-to-wire correspondence follows
only frozen candidate-admission/v1 and does not introduce a competing schema.

The standalone stdlib-only suite was held back until the request declaration and
complete packet were present, then run once (see Results). It includes the clean
full-graph control, exact 42-path equality, all 112 child-edge negatives, missing
roots/calls/identities, orphan/extra positions, wrong types/metadata/factories,
request-field negatives, valid-slot/whole-map swaps, and coordinated changed
INPUT/recomputed self-hash against unchanged independent EXPECTED. Original
V01–V36 semantics/counters remain pinned and mapped, all UNEXECUTED at runtime.

## Native field set confirmed

Temper rm-ae19e128 (2026-10-25) answered follow-up rm-e76e5f8e: v1
`source.field_sets.native` is SINGLE_CALL_SETTINGS
(temper_ai/agent/single_call_agent.py:33), the 24 inner single_call keys as a
permitted set (subset check). It is not the six envelope keys and not a flattened
union; required-key presence is engine validation, and the envelope is pinned by
the entire factory config_json. This matches the AST-pinned
native_permitted_keys already in source-facts.json, so no expected value changed.
`source-facts.json` now carries literal wire_field_sets for workflow (13, with
_KNOWN_FIELDS), node (36, with _KNOWN_FIELDS) and native (24); test 18 rejects
envelope-only, flattened-union, present-only, required-only, unsorted and the
contract's two-name toy list. The request set comes only from Temper's declaration.

## Request-options declaration

Temper rm-31e24c00 (2026-10-25) answered rm-78058d55 with a pre-commit T2 #198
declaration: /home/shinelay/company-lab/candidate-admission-t2-198/REQUEST-OPTIONS.md,
SHA256 `b6347a80cd927df39430aed954acef561cfcece51b6d3179d73bb10d985b823a`
(re-hashed here before use), base `caf5c16f6d9965cbcbc8e10653d75e1c47b27340`/tree
`726bf8e8a198f1436bf8caf84bbf2a8115601e47`, branch temper-198-admission-transport,
staged diff SHA256 `59e9ef9e074d896e5e65114e43af61087ac0fd0f1ed787573ad446e1aef93d4d`;
temper_ai/api/routes.py blob `4cd4ec72eece985b7f6c37cdbef6b8c51a044814`
(SHA256 `594b565be89e1b59409cef8a20452ad9052deaa14e5c3a6a170ea84b3abc3222`) and
temper_ai/runner/admission.py blob `7b943da86e62dc2c940f52fc973d9918107e922a`
(SHA256 `cbe67b609e328fccc7f72177e838e077bad8800eebbf16090194bf1ce97481ff`).
It is uncommitted source metadata, not CI, installed-source or runtime evidence;
the pins must be rebound if that source moves.

request_options_json is canonical_bytes(RunRequest.model_dump(exclude={"admission"})),
after Pydantic field parsing and before graph/default/notify parsing. Closed
sorted inventory: inputs, notify, workflow, workspace_path; all four keys are
always present. workflow: str, required, null invalid, aliases workflow and
workflow_name, dump key workflow. inputs: dict, default {}, null invalid, also
bound separately to metadata_inputs_json, no workflow defaults applied.
workspace_path: str | None, default None, null same as absent; ingress needs exact
equality with the descriptor's non-null workspace_path. notify: dict | str | None,
default None, null same as absent, unparsed. admission is descriptor transport only
and excluded. Unknown HTTP fields follow ordinary Pydantic ignore; no new rejection
policy is claimed. Logical run id, execution UUID, pins, nonce and worker identity
are not option keys. submit_candidate's execution_id must equal the descriptor
UUID; the only mode is external-db-fresh. Production authority stays unbound and
refused (Temper HOME rm-02034875).

Supplement mapping: INPUT/request.json and EXPECTED/request.json are written
separately. Options are inputs {record_id} (old #306's single synthetic request
input), notify null, workflow oracle306 and workspace_path
/synthetic/316/workspace. metadata_inputs equals the caller inputs exactly; the
thirteen record_rNN inputs are recorded as left to workflow defaults. Descriptor
metadata (candidate identity, logical run id, execution UUID, workspace) are
labelled synthetic 316 identities, distinct from old #306's run_id and workspace.
The test keeps a second literal copy of the declaration pins and checks the
structure against it.

## Test-design change before the first run (H-A1-ORACLE-2a)

What was wrong: the written suite compared live bytes of seven engine source
files with their basis-56b833e6 hashes. In a lasting suite that fails on any
unrelated edit (a comment, another class) and would block other roles' lands.
One change: keep those byte hashes as provenance, checked by git at open and
close, and let the suite assert only the declarations the fixture uses (AST:
fields, annotations, defaults, _KNOWN_FIELDS membership, native sets, factories).
Expected: the clean suite passes now and fails only when a declaration the
fixture depends on changes. Wrong if a declaration change slips past the AST
checks. Written before any test ran; not a reaction to a failure.

## Inspection note

An early metadata inspection accidentally printed old synthetic case mutation
values, including script/request mutation fragments. No private or actual
model-bound payload was accessed. Subsequent inspections emit only field names,
types, counts and hashes. No fixture body is emitted by the test assertions.
A metadata-only query initially addressed old inputs at the wrong nesting level
and raised KeyError; this was source inspection, not a test campaign. The actual
historical field is INPUT.schema_version; no fixture was changed to accommodate it.

## Results

Original #306: 17 packet tests passed (attributed historical result); this
supplement does not reinterpret that as full compiler coverage.

Focused campaign, run once after every change was written (2026-10-25T23:00:27Z,
worktree HEAD 56b833e6e6e990e966a1e61a204fd92c5c9f690a plus the three new areas):
`python3 -I tests/test_architecture/test_admission_oracle_supplement.py` ->
"Ran 20 tests in 0.832s", "OK", exit 0. Original output, 25 lines, SHA256
`cefa7cc1ba905ad415d7777558d2aa6d0016c4a02fccccf608b2b04109cf4115`. No test
failed, so no repair hypothesis was needed and no assertion was changed after
the run. `ruff check` on the module passed before commit.

Packet manifest (manifest.json, ordinary SHA256 of exact bytes): case-mapping
ecde2813, graph ffe9ba18, identities 460f9fc1, EXPECTED request 662b21d5, closure
4ae4982e, native ab939a81, INPUT request 3ac12556, README bf31c138, source-facts
6e821c2e, wire-mapping 2685c5b6 (full values in manifest.json). Proved: 60 raw
records close exactly; 126 nodes match in preorder; the 42 raw single_call paths,
the 42 EXPECTED single_call factory paths and the 42 explicit positions are the
same ordered list (r01..r14 x call_A1..A3); every serial edge and policy, full
native maps, metadata, factories, identities, request options and field sets
match literal expectations, and every planted defect is caught.

Unexecuted runtime predictions: everything in V01-V36 and every compiler, codec,
ingress, preparer or engine behaviour stays UNEXECUTED. Runtime metadata type
checks, Pydantic alias/ignore behaviour, workspace equality enforcement and
execution-UUID binding are declared by source, not observed here.

Normal gates, landing and exact-head remote CI follow below. No production code,
old306 file, #192 schema/codec/spec or another worktree has been edited.
