# P3 N3 pure source comparison

Status: source candidate checks passed, not yet reviewed/landed; disabled data only. Systems #71; source base
5334255e18ef3630c9f63e894f7e986bd7049322 after the ordinary base rebase;
initial source base was 786e6711ac0cb0662567443ac23f504dfeaee778.
Claim N/A: cwd-local; isolation =
/home/shinelay/temper-ai-systems-task-71, branch systems-task-71.

## Hypothesis H-N3-IMPLEMENTATION-1

R2 /1 has one runtime and three owners and cannot represent actual host+worker
closure. Add one pure comparison component with independently supplied expected
binding and verified-origin snapshots, retaining R2 grammar and behavior.
Expect fixed N3-01..15 twins to separate matching, contradictory and missing
facts; mandatory unchanged R2/R1/R5 carry tests must pass. Falsifiers: omitted or
forged fact matches; legacy grammar/results change; candidate chooses its own
expectation; comparator performs I/O; constructors are treated as authentication.
Result v1: focused N3/R2/R1/R5 run 2026-11-01, 1,924 passed / 2 failed
(66.11 seconds, CPython 3.13.15). All N3 cases and behavioral carry assertions
passed. H-N3-IMPLEMENTATION-1 is not yet accepted: the permitted extraction
conflicts with two existing source-identity checks, not behavior. R5
`test_received_modules_unchanged` pins the original R2 blob ab21d2d6, and R2
`test_static_source_has_no_exec_subprocess_git_or_producer` pins its exact imports.
Neither original assertion was weakened or edited. No native HIT asserted.

H-N3-INTEGRATION-2 was superseded before implementation. Systems' initial narrow
pin/import-expectation update permission is revoked by its final compatibility
decision: restore R2 byte-for-byte and keep every original assertion unchanged.

H-N3-PACKAGING-3: configs is not wheel-packaged and importing temper_ai initializes
a GitHub-secret hook. Relocate this candidate's single implementation to the
stdlib-only top-level p3_source_closure package; retain a re-export-only config
facade. Expect canonical object identity without engine initialization; falsifiers:
alias-loaded definitions, copied types, service imports, or a formerly supported
standalone R2 caller now requiring an unavailable dependency. Systems owns the
leaf; Temper #261 owns wheel metadata and joined installed-wheel integration.
Source leaf preparation does not wait on that integration. The standalone R2
caller/distribution boundary must be resolved, not hidden with sys.path changes.
Source/observation epoch refs and coverage/gap aliases implement adopted §8.1;
they are identities, not counters or producer completeness assertions.

H-N3-PACKAGING-3 partial result: canonical leaf/facade relocated; static lint
passes. The real standalone boundary FAILS: from outside either checkout,
`/usr/bin/python3 -I <checkout>/configs/architecture/bin/ops_host_binding.py`
exits 0 for unchanged main R2 and 1 for the factored candidate, with
`ModuleNotFoundError: No module named 'p3_source_closure'`. This is an actual
new dependency, not repaired by proposed wheel metadata or editable-source
imports. Existing first_app_check.yaml calls an absolute script through
sys.executable, and neither R2 nor that caller supplies this dependency.
No sys.path, environment, copy, legacy-hook or distribution bypass was added.
H-N3-PACKAGING-4 (Systems lead decision, 2026-11-01): restore byte-identical R2
and preserve its supported standalone invocation. Keep one canonical N3 package
with only its own schema-specific primitive/JSON/refusal checks. Sharing those
atoms across two different schema contracts would require changing an existing
caller's dependency delivery; that is outside this task. No R2 grammar, eleven-code
table or generic helper bundle is copied into N3. N3 reuses its own closed record
decoder across graph, observation and expectation records. Expect the same isolated
legacy call and unchanged carry tests to pass alongside canonical N3/facade
identity and clean/bad cases for each new-schema atom. Falsifiers: any legacy blob
change, runtime dependency retrofit, duplicate N3 implementation or omitted
new-schema check. Result: source-candidate HIT only, 2026-11-01. Focused v2
run: 1,949 passed in 52.30 seconds (CPython 3.13.15), including every unchanged
R2/R1/R5 carry test, N3-01..15, targeted single-guard mutations, canonical
facade identity, isolated standalone legacy call and explicit missing-N3
failure. Git diff confirms R2 and original carry suites byte-identical to base.
No source acceptance, installed-wheel, corpus integration or native HIT follows
from that result.

During final grammar inspection, untyped schema/tag values could invoke arbitrary
candidate equality before exact primitive checks. The existing pure/closed
hypothesis requires rejecting those types before comparison. The corrected
candidate adds schema-type and inert-equality cases plus reference-identity and
adopted epoch controls. They are covered by the completed 1,949-case v2 run,
not by v1. The reference-identity check was also added after v1 started and is
covered only by v2.

H-N3-TYPING-5: the normal commit hook passed on 62ab8385, but it checks
`temper_ai/`, not the new top-level package. Explicit package type checking found
58 errors: reflection lost concrete record types, optional origin lookup and
union branches were not narrowed, and local names conflated identity/process
maps. Preserve runtime grammar and comparison semantics; represent the immutable
base as a dataclass, make decoding generic with checked output types, and narrow
locals explicitly. Expect zero package type errors and the same full focused
carry/mutation results. Falsifier: type suppressions, weaker grammar, changed
public record fields or changed comparison outcomes. Result: source-candidate
HIT, explicit mypy reports no issues in all eight package modules; no type
suppression was added. Completed v3 focused carry/mutation run: 1,949 passed in
46.33 seconds (CPython 3.13.15), with package lint passing. An empty py.typed
marker exposes the same annotations to installed consumers; it does not provide
distribution metadata or claim the future joined wheel test. Subsequent rebase
onto 5334255e changes no component bytes; the normal hook still must pass on the
final candidate. Native qualification remains unchanged.

Authority: Architecture T3-ADOPTION.md, Temper T3 INTERFACE.md §§6/8, Systems N3
CONTRACT.md. All N unresolved; four rows UNQUALIFIED; P5 UNTRUSTED;
WRITES_ADMITTED=False. No provider, collector, issuer or activation is delivered.

## Public interface and dependency direction

Public import API v1 (agreed Systems/Temper allocation, PACKAGING.md):

```python
from p3_source_closure import (
    validate_reviewed_graph, validate_loaded_envelope, compare_loaded_source,
    ReviewedSourceGraph, LoadedClosureEnvelope, NativeClosureExpectation,
    VerifiedClosureOrigins, SourceClosureComparison, TargetRefused,
    N3SourceEpoch, N3ObservationEpoch, N3Coverage, N3Gap,
)
```

Signatures:

```text
validate_reviewed_graph(value: object) -> ReviewedSourceGraph
validate_loaded_envelope(value: object) -> LoadedClosureEnvelope
compare_loaded_source(reviewed: ReviewedSourceGraph, observed: LoadedClosureEnvelope,
    *, expected: NativeClosureExpectation,
    verified: VerifiedClosureOrigins) -> SourceClosureComparison
```

Every canonical record is frozen, slotted, contains only immutable members, and
has a data-redacted repr. Records have exactly one definition in
`p3_source_closure/records.py`, re-exported by the package and the thin
`configs/architecture/bin/ops_host_source_comparison.py` facade. No service import or initialization occurs. Types, parsing, reviewed-graph
validation, observation validation, purpose-specific provenance comparison and
comparison composition each have one module. Do not import the same file under a
second top-level name, duplicate these types in the engine, or use dynamic file
loading as a distribution mechanism. The engine adapts/imports these records,
not the other way round. Temper #261 owns distribution metadata and the actual
joined non-editable wheel/import check. This source leaf does not claim that
integration complete and does not edit engine or package configuration.

Validation accepts an exact built-in dictionary or exact UTF-8 JSON bytes.
Dictionaries have canonical sorted ASCII-escaped compact JSON identity; bytes
retain their original identity, including whitespace. Transport duplicate keys,
NaN/Infinity, unknown fields, subclasses, wrong primitives (including bool as int),
unknown tags, malformed references and duplicate identities refuse. Limits reuse
R2 receiving values: 16,777,216 bytes, nesting 32, collection size 65,536; no new
runtime/spend limit. `TargetRefused.code` is `TARGET_SCHEMA_MISMATCH` for an
unsupported schema in an otherwise closed record and `TARGET_BINDING_INVALID`
for malformed shape/type/reference/encoding. This is the N3-local exception
class, not R2's class or eleven-code table. Exceptions contain fixed labels only.
No path is implicitly opened. A reference is data, never a lookup request.

Minimal N3 validation is tied to new-schema invariants (no legacy helper bundle):

| Local check | New-schema invariant | Independent controls |
| --- | --- | --- |
| records._typed | exact primitives, immutable members, nonempty NUL/surrogate-free text | test_new_schema_atoms_have_independent_clean_and_bad_inputs; test_records_immutable_and_single_definition |
| parsing._decode | closed dataclass fields, tagged/versioned variants, SHA-256 identity | test_closed_grammar; test_untyped_schema_is_format_refusal; test_parser_never_invokes_candidate_equality |
| parsing._object_fields | a duplicate JSON key cannot hide an earlier value | test_json_duplicate_cannot_hide_a_valid_final_field |
| reviewed_graph identifier check | graph node/repository/profile/entrypoint names are unambiguous tokens | test_new_schema_atoms_have_independent_clean_and_bad_inputs |
| validation.TargetRefused | only the two N3 format codes, no authority decisions | test_n3_refusal_is_not_the_legacy_code_table |

A source-only standalone R2 invocation remains valid outside the checkout without
N3 installed. The new config facade, unlike that legacy caller, explicitly
requires the canonical package; absence raises ModuleNotFoundError rather than
loading an alternate copy. test_legacy_standalone_and_explicit_n3_dependency_boundary
checks both with an isolated interpreter and no site packages. Temper #261's
joined wheel check is the separate proof of actual installed consumer delivery.

## Closed wire records

`p3_source_closure/records.py` is the single field/type authority. Lists on the wire
become immutable tuples, and null is accepted only on explicitly optional fields.
`ContentIdentity` is lowercase SHA-256 plus nonnegative byte length.
`EvidenceRef` adds schema, supplier and record_id; it is not authentication.

The graph's closed fields are schema, graph_id, repositories, nodes, edges,
entrypoints, process_profiles, completeness_review_ref. Repositories retain
object_format (`sha1` or `sha256`), commit and tree. Owners are explicitly
ops/architecture/qa/temper/systems. Edges use wire names `from` and `to` (Python
attributes source/target). New graphs can cycle; dangling references and duplicate
identities cannot. An entrypoint has an explicit id (the target of the adopted
entrypoint_ids), profile_id, node, symbol_or_invocation and bootstrap_chain.

Node provenance is a closed tagged union:

- git: repository/commit/tree/path/mode/object_id, membership_ref, representation
  and explicit target_chain. Membership is verified separately from file bytes;
  symlink/submodule/LFS chains cannot be silently treated as regular files.
- generated: generators, inputs, toolchain, recipe, output, execution_object and
  generation_ref. References bind exact reviewed input node identities, not names
  without content. Execution can differ from generated source bytes.
- artifact: artifact, build, sources, dependencies, interpreter, abi,
  representation, loaded_representation and provenance_ref. Relocation/JIT uses
  the verified artifact-to-loaded identity, never assumed equality with disk.
- cache: source_nodes, interpreter, cache_format, executed and provenance_ref.
  A current source hash alone does not bind the executed cache.

The envelope's closed fields are schema, envelope_id, reviewed_graph,
legacy_links, binding, boundary, process_observations, provenance_refs.
Binding retains execution/attempt/nonce/job revision/route/selection/build/parent
and creation subject, with optional window and creation association. Boundary
retains phase, operation, optional request and receipt, barrier and current
validity checkpoint. A_PRE_CREATE has no future window/receipt; A_PRE_ARM need
not fabricate a future result. B/C require actual window+creation association;
C phases require a request; C_BEFORE_COUNT requires the actual receipt.

Each process has separate host/boot/birth/PID/exec/launch/parent, namespace,
container, runtime and effective actor identities. Observation binds the process,
profile, job, graph, entrypoints, runtime, collector/version/mechanism and origin
references. Events carry actual execution-object identity and sequence/origin.
Checkpoint binds epoch, first/last sequence, last event, children, explicit
coverage/gaps/loss, initial-state evidence, seal and exact boundary. Unsupported
coverage is a gap, not an empty success. Ended children retain their sealed history.

## Service precondition: provider unavailable

`NativeClosureExpectation` is an independently selected service result: exact job,
phase, review, complete process set, policy and current frontiers. It is never
selected by inspecting candidate values. `VerifiedClosureOrigins` is supplied
only after the service independently authenticates the exact graph/envelope bytes,
expectation, purpose-specific evidence, and current validity checkpoint. These
Python constructors DO NOT authenticate anything. A caller can construct a fake
MATCH; that does not authorize it. Never expose this handoff as a wire capability.
Cross-process consumers re-verify their authenticated channel and origins.

No production provider is supplied. The explicit unavailable snapshot is
`VerifiedClosureOrigins(None, None, None, None, ())`; it yields UNKNOWN, not a
fallback to local filesystem/process inventory. Missing initial collection,
bootstrap/native/cache/JIT/child history or an effect-coupled barrier stays UNKNOWN.
A Python import hook, sys.modules scan, current disk hash or same-UID file is not
that missing proof. Native producer/enforcement/transport/issuer implementation
and real review applicability remain separate Temper/Ops obligations.

A `VerifiedOriginFact(ref, purpose, claim)` binds an independently verified claim,
encoded by `p3_source_closure.parsing.claim_identity` (pure encoding, not a verifier).
The provider must establish the claim independently, not sign candidate hashes:

| Purpose | Exact claim bound |
| --- | --- |
| review | whole SourceGraph, including policy and completeness review reference |
| membership | (Repository, SourceNode), including commit/tree/path/mode/blob/byte identity |
| generation | (node, exact nodes for generators + inputs + toolchain, in that order) |
| artifact | (node, exact nodes for sources + dependencies + interpreter) |
| cache | (node, exact nodes for source_nodes + interpreter) |
| condition | complete SourceEdge |
| policy | complete ProcessProfile |
| legacy | LegacyLink; each mapping separately binds (LegacyNodeLink, SourceNode) |
| process | (instance, profile_id, binding, graph_id) |
| collector | (process claim, collector_id, collector_version, mechanism, epoch, coverage) |
| collector (initial) | ("initial", collector claim) |
| event | (process claim, epoch, LoadEvent) |
| checkpoint | (process claim, Checkpoint) |

Exact immutable reference identities select facts, not an issuer supplied by the
candidate. Missing facts yield UNKNOWN; a verified claim contradicting the input
yields REFUSED. Repeated origin keys refuse rather than silently choosing one.
The service must bind all purpose-specific authorities and revocation/applicability
at its current effect fence; the comparator neither creates nor renews that fence.

## Result and legacy compatibility

Result is MATCH, REFUSED or UNKNOWN, with sorted unique fixed reasons from T3.
Contradictions take REFUSED precedence without hiding gaps. MATCH binds exact
expectation, boundary, review and covered process frontiers. Non-MATCH results
contain no claimed covered frontiers. Neither result mutates state, grants writes,
admits an operation, counts PASS or establishes native N3 qualification. After a
hold, new load, process replacement, revocation or barrier advance, the service
must supply fresh current inputs. There is no freshness timeout or cached MATCH
reuse rule.

R2 `qa-ops-host-source-closure/1` retains ops/architecture/qa owners, one runtime,
its closed keys, existing bounds, acyclicity and refusal precedence. R2, R1,
R5, their source pins/import expectations and their fixtures are byte-identical;
no helper moves from the standalone legacy implementation. N3's local refusal
has only its two new-schema format codes, not R2's full code table or grammar. Optional explicit legacy
byte/node links in N3 do not reinterpret or upgrade legacy records. No /1 sniff,
downgrade or implicit conversion exists.

## Fixed cases and delivery boundaries

`tests/test_architecture/ops_host_n3_cases.py` exports FAMILIES, clean_world,
bad_twin and the immutable Inputs bundle for N3-01..15 synthetic twins. Expected
answers are fixed independently; test-only witnesses model an invented world,
never real authority. The runner is `test_ops_host_source_comparison.py`; it
includes closed grammar, raw identity, missing provider, purity, immutability,
chronology, terminated child, gap precedence and targeted mutation controls.
Existing R2/R1/R5 suites and all their assertions remain unchanged.

Canonical registration belongs to QA's actual `ops-host-compat-corpus/1` seam.
No local registry is invented here; registration is NOT COMPLETE until QA's
actual materialized artifact is available from Ops #739 (after Ops #738), per
QA #95's frozen contract. Its cases[] and consumer_registrations[] live inside
one manifest; this module exports cases but does not invent a second registry. Component export completion and
canonical registration completion must be reported separately. Source acceptance
and exact final-head gate reconciliation are separate steps; missing native
provider values do not block preparation or source review.
