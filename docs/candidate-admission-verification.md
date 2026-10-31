# Candidate admission: verification of the composed seam (V1)

This is the evidence for **V1** of Architecture's accepted plan
`architecture-dept/work/context-profile/admission-binding/IMPLEMENTATION-PLAN.json`
(SHA256 `a85d44896c25650bb8123ad422e7b853c9ee552a14afedf8f4797bdc0ce01d9b`), checked
against its verification matrix `VERIFICATION-MATRIX.json`
(SHA256 `991513e8faa890a717496be177c30dd91e57cd9ba7e9125bf5e19bdc1ff0a7f5`, cases
V01-V36).

Until now the pieces of the admission seam each passed on their own. V1 puts them
on one branch and drives **one reduced synthetic candidate from submit to the
native claim** through the real engine. It compares what the engine consumes with
literal expectations independently written for that synthetic authoring, and runs
the matrix's negative controls against that composition. It does not execute
Architecture's real published topology.

Nothing here is a custody attestation, and nothing here admits a real candidate:
the authorized caller is a typed test object (see
[The production authority gap](#the-production-authority-gap)).

## Status

**Binding NOT MET; not ready to land.** Architecture resolved the V11/V14
eligibility conflict without changing the frozen matrix. The bounded raw-stage
repair and independently approved composition controls are described under D4.
V33 exercises overlapping snapshot loads as well as sequential full runs. The
full ordinary gate, exact-head CI and both source reviews remain required; no
land approval or production authority is implied by these focused results.

## What the existing checks exercise

- The composed route works end to end: **submit -> queued row -> worker -> restore
  -> scheduler -> factory -> script render -> native claim**, with the admitted
  snapshot, the protected record and the use-site checks all live at once.
- Every config the engine actually used, and every metadata value it rendered,
  equals an **independent literal oracle** written by hand in the test (json and
  hashlib only), not read back from the engine. For the clean 14-record case,
  Architecture's unmodified A1 compiler (#311) produces the same descriptor from
  the **same synthetic authoring**. This is compiler/contract compatibility, not
  an independently sourced second graph.
- At 14 records x 3 native positions the run makes **42 claims on 42 unique (root,
  slot, position) tuples across 14 physical roots**, each on the root its readiness
  receipt measured. Each record's three native slots share one root.
- The negative controls record the actual refusal boundary and fixed code, with
  counters for effects on the rejected node. The table below distinguishes observed
  checks from their limitations; a green characterization test alone does not prove
  the matrix.
- An ordinary (non-candidate) run is untouched: the admission path is entered only
  when a run row carries the reserved slot *and* the caller injected bindings.

## What this does not prove

- **No live custody.** The root, uid, mount and custodian in the fixtures are
  synthetic. A1's compiler leaves custody unresolved, and V1 does not resolve it.
- **No real provider call.** The only sender is a test sentinel that records what it
  was given and returns a fixed answer; no model, no network, and no token value is
  ever read.
- **No production authority.** See the gap section: the real designation and preload
  path stay unbound and keep refusing.
- **Not that Architecture's real 14x3 candidate is admissible today.** It is not:
  see [The real 14x3 oracle on this head](#the-real-14x3-oracle-on-this-head-f1).
- **Not a promise that a bound run succeeds.** V36 is explicit: an exact binding is
  not runtime success; a native failure after the claim stays a failure.
- **Not global stale-worker revocation.** Current-generation validation is a
  claim-time fence. It does not prove that every already-bound preparation or render
  stops immediately when generation or cancellation changes. A post-claim
  cancellation cannot retract a send: the network send is outside the exclusive
  claim callback.
- **Not an exercised rollback or old-binary fence.** Safe rollback remains
  conditional on retained admission/claim state and the operational ingress/worker
  refusal fence described below.

## The pieces composed here

| Piece | Task | Delivered head (tree) | What it contributes |
| --- | --- | --- | --- |
| Contract + fixtures | #192 | `86a9f21f`, `caf5c16f` | wire schema, refusal codes, canonical bytes, the frozen contract fixtures |
| T1 raw capture + owned snapshot | #197 | `45635747c89ae343c75ca3b999b0006b75be86b7` (`c3f1293e`) | closed-grammar raw scan, one-transaction capture, owned snapshot, the loader |
| T2 protected transport + early fences | #198 | `d1168c4b68abacfff6e5dfd73ee15bd00db5e491` (`cac0e7cf`) | reserved run-record slot, atomic install, dispatch and readiness, restore before anything mutable loads |
| T3 use-site + same-fd claim checks | #199 | `4d8378ef`, `1b4890e04dc89fef06b6e47f2b24e08c986972ae` (`4c353285`) | graph, factory, script and native checks against the current generation; same-fd claim |
| A1 compiler + oracle | architecture #311 | `ac4cba62` (`33008124`) | an independent compiler and the 14x3 oracle, used here as cross-checks only; unmodified |

The composed branch is `temper-208-admission-v1`: the seven commits above
cherry-picked in that order onto current master, then V1's composition and
follow-up repair commits carrying the test file, this document and the edits listed
below. Each delivered cherry-pick's patch-id is
identical to the delivered commit's, so the pieces arrived unchanged. The #192
contract was not on master before this branch; it lands with it. Master moved
several times while V1 was built; each time the branch was rebased and the
patch-ids checked again. The exact base, head and tree are recorded with the land
request, not here, because this document is part of the commit it describes.

## Owned by V1

- `tests/test_runner/test_candidate_admission_integration.py`: the whole composition
  proof. One happy path (V01 small, V02 14x3), the V03-V36 controls, the cross-check
  against A1's compiler, the S3/S4 controls owed from T2, and a bite for each glue
  edit and defect fix.
- `docs/candidate-admission-verification.md`: this document.

Every other change V1 makes is in the next two sections, and nowhere else.

## Glue edits

Each glue edit is the smallest change that lets the delivered pieces meet. Each has
its own bite: the edit (or each part of it) was dropped alone, a named test failed,
and the edit was restored.

### G1: the runtime-only admission fields on `ExecutionContext`

`temper_ai/shared/types.py`

T1 declared `admission` alone; T3's use-site checks also read `admission_hooks` and
`admission_required` (the triplet agreed in rm-110bfd8a and rm-02034875). V1 adds
the two missing fields with T1's exact-type rule: each is refused with
`invalid_type` unless it is exactly the declared type. The check now runs when any
of the three is set, not only `admission`. An ordinary context sets none of them.

Bites, each dropped alone:

| Dropped | Result |
| --- | --- |
| the whole edit (T1's original) | V01 fails: `ExecutionContext.__init__() got an unexpected keyword argument 'admission_hooks'`; `test_g1_...` fails |
| the widened condition (check only when `admission` is set) | `test_g1_the_runtime_only_admission_fields_are_typed_exactly` fails: a look-alike hooks object is accepted |
| the exact type check on `admission_hooks` | the same test fails |
| the exact bool check on `admission_required` | the same test fails (`1` is accepted) |

### G2: the generation fence `current_generation`

`temper_ai/runner/admission.py`

T3 needs "the record that is current right now", and must act on it while it is
still current. T2 delivered the row lock and the record reader but no single way to
ask for both. V1 adds `current_generation(binding, action)`: it takes the row lock,
reads and checks the stored record, compares every part of the binding with what is
stored (dispatch nonce, running attempt, descriptor bytes, closure digest, graph
digest, and the record's phase), and only then hands the action the record it is
holding. A wrong-typed argument refuses `invalid_type`; any mismatch refuses
`dispatch_generation`.

Bites: `test_g2_the_generation_fence_compares_the_whole_stored_generation`. Each of
the five comparisons dropped alone (nonce, running attempt, descriptor wire,
closure digest, graph digest) makes it fail at the stale-binding check. The phase
comparison cannot be isolated: the contract only accepts a queued record with
`running_attempt` 0, and a binding's attempt is always at least 1, so the attempt
comparison already covers it. It stays as defence in depth.

## Defects found in the pieces

Each defect got a written hypothesis before the fix, a failing-first test, and a
bite. Nothing was fixed by weakening a check.

### D1: the composed submit could not read a raw row (fixed)

**What was wrong.** The first composed submit refused `source_origin`.
`submit_candidate` (T2) opened its session as `with get_session() as session:`,
which starts a transaction lazily, while T1's `ConfigStore.get_raw_record`
(`temper_ai/config/store.py`) requires the caller to already be inside a
transaction, so the capture saw none. Neither piece's own tests ran the two
together.

**Hypothesis.** Opening the session as `with get_session() as session,
session.begin():` gives the capture the transaction it needs, and makes the capture
and the install commit or roll back together (which T2's design assumed). Expected:
the happy path passes; every refusal still writes no row. Disproved if a refusal
leaves a row or any ordinary test changes.

**Result: hit.** Bite: drop `session.begin()` and V01 refuses `source_origin` at
submit.

### D2: the approved side was decoded again at every node check (fixed)

**What was wrong.** The 14x3 case was far slower than its size. Profiling one run:
`canonical_bytes` 103,136 calls (40 s), `decode_canonical` 27,807 calls (31 s), and
`CandidateUse.binding` 1,315 calls, each rebuilding the expected side from the
admitted bytes. Descriptor decodes went from 1,028 for 1 record to 2,436 for 2
records: more than double for double the work.

**Hypothesis.** Everything on the *expected* side is a pure function of immutable
admitted bytes, so decoding it once when the admission is bound (in
`CandidateUse.__init__`, `temper_ai/agent/admission_use.py`) removes the growth
without changing what any check compares; the *actual* side is still re-read at
every check. Expected: the same codes from every control; decodes at most double
when records double. Disproved if any control changes its code, or decodes still
grow faster than records.

**Result: hit.** Every control kept its code. Bite:
`test_expected_side_is_decoded_once_not_on_every_node_check` fails on the old shape
(`{1: 1028, 2: 2436}`, and 2436 > 2 x 1028). One side effect, checked: a claim
whose binding has no position id now refuses `position_mismatch` instead of
crashing with `StopIteration`.

### D3: a blanket raw-field ban (refuted, reverted)

**Hypothesis.** Banning tools, memory and every control-flow-looking node field
by raw presence would satisfy V11/V14. **Result: miss, reverted.** That confuses
eligible cleanup metadata with fallback, and inactive defaults with an active
loop. It also broke T1's mixed codec/eligibility fixture. The matrix remained
unsatisfied; accepting signed prohibited content was not a valid workaround.

### D4: distinguish raw-profile eligibility from codec validity (fixed)

**Evidence and ruling.** The composition admitted approved `tools: null`,
`memory: null` and a non-null `loop_to`; other tools/memory controls refused only
at graph comparison. None meets the frozen B1 refusal requirement. Architecture's
2026-10-30 ruling (rm-126350e6) keeps V11/V14, #192 and A1 unchanged and permits
reopening only the conflicting part of T1's fixture. `on_failure` is hold/cleanup/
inheritance, and `undoes` is cleanup metadata—not model fallback. `max_loops: 1`
without a target is not a loop. This is Architecture's interpretation, not an
owner waiver or a LAND decision.

**Hypothesis H-V1-RAW-POLICY-1.** Extend only
`temper_ai/config/candidate_admission.py::validate_raw`: refuse node tools/memory
presence and workflow memory presence, even null/empty; refuse non-null loop
targets, including empty/malformed strings. Preserve the existing unknown-field
and type checks, which already reject fallback and prohibited defaults. The raw
stage runs before `_SnapshotLoader.load_workflow`, so no graph expansion, factory,
claim or send is needed to refuse. Falsifiers: prohibited content admitted, an
eligible clean twin broken, refusal only after expansion, a weakened comparison,
or a change to ordinary loading.

**T1 fixture repair.** In
`tests/test_config/test_candidate_admission.py::test_literal_raw_clean_types_and_script_exception`,
move its memory declaration to a refusal control. Keep the other literal/type/
script checks, `max_loops: 1`, gate, rename and cleanup fields; move generic JSON
coverage into metadata. No #192 fixture, compiler or ordinary-loader change.

**Result.** Before the fix, the fixed raw-stage controls had **24 failures and
40 passes**: accepted node/workflow memory, node tools and loop targets were the
failures. After the raw stage passed, the final affected-stage/composition run
passed **290 tests in 163.10 s**, with only the full-size V02 deselected (it had
passed before D4 and runs again in the ordinary full gate). The composed
`test_raw_profile_otherwise_valid_approved_controls` supplies independently
approved descriptors and literal effective projections: all 24 prohibited cases
refuse at B1 with zero expansion/factory/claim/send. Disabling only `validate_raw`
then admits the **same bytes** through submit, showing that a stale digest, wrong
type or unrelated graph mismatch cannot explain the refusal. That mutation never
starts a worker or sends anything.

Four separate guard removals—node tools, node memory, non-null loop target and
workflow memory—each make their named composition control fail with
`DID NOT RAISE AdmissionRefused`. Existing fallback/default closed-field checks
are preserved, not replaced. Clean composed twins keep absent tools/memory with
effective null defaults, explicit null loop targets, standalone loop counts,
`on_failure: null`/hold/cleanup, `undoes`, gate and rename metadata. V15 still refuses
a post-approval change to each supported policy field.

| Raw content | Fixed outcome | Boundary |
| --- | --- | --- |
| node tools/memory, including null and valid empty containers | REFUSE `wire_schema` | B1, before expansion |
| workflow memory, including null/empty | REFUSE `wire_schema` | B1, before expansion |
| node/workflow fallback; tools/memory/fallback in defaults or agent fields | REFUSE `field_set_drift` | existing B1 closed-field check |
| non-null loop target, including empty/malformed strings | REFUSE `wire_schema` | B1, before expansion |
| wrong-typed loop target | REFUSE `invalid_type` | existing B1 type check |
| absent tools/memory/fallback; null/absent target; standalone count; pinned cleanup/gate/rename | ACCEPT | literal full projection still compared |

### D5: the V30 replacement writer was inside the old worker's row fence (fixture repaired; PostgreSQL proof pending)

**Evidence.** The first composed remote PostgreSQL job stays in its test step
well beyond the base head's 15m33s PostgreSQL job. Hosted logs are not available
while it runs, so elapsed time alone does not identify the stuck test. Source
inspection finds an independently actionable fixture error: V30 supplies
`bump_dispatch` as `EntryBindings.after_prepare`; the callback runs inside
`CandidateUse.checkpointed`'s `current_generation` action, while that action holds
`SELECT FOR UPDATE` on the run row. `bump_dispatch` opens another session and
synchronously commits an update to that same row. The old worker cannot release
its fence until the nested writer returns. In-memory SQLite does not model this
PostgreSQL row-lock wait.

**Hypothesis H-V1-PG-RACE-1.** The intended replacement must win before the stale
worker enters its protected readiness action, not write through the held fence.
First add a deterministic test-side assertion that the replacement writer runs
outside the real `current_generation` callback. Then inject the replacement
immediately before the actual preparation checkpoint callback, retaining the
real row fence, full generation comparison, literal `dispatch_generation`
refusal, zero claims/sends and unchanged empty readiness. Only the V30 test's
schedule changes; no production or frozen-oracle code changes.

**Expected measurement.** The old schedule fails the new assertion even on
SQLite. The corrected schedule passes that assertion and the existing refusal
and side-effect checks. The full ordinary local gate and all eight exact-head
remote checks, including this test on PostgreSQL, must then pass afresh. A
successful SQLite check alone cannot establish the hosted job's root cause.

**Falsifiers.** The writer already runs outside the fence; the corrected test
admits stale effects, changes its expected refusal or loses its zero-effect
checks; PostgreSQL still blocks on this control. Preserve the incomplete/red
remote attempt as history, not a passing gate.

**First probe.** The added assertion failed on the old schedule in 3.24 s:
`replacement_writes == [True]`, not `[False]`. The first corrected probe did not
reach the writer (`[]`): the new callback refers to `Status` without importing it.
**Setup correction hypothesis.** Import the existing enum and record the fixed
callback metadata before checking it; expect one completed preparation callback
and one outside-fence write. A still-empty write list falsifies that diagnosis.
The clean V01 and G2 controls passed in that attempt. After importing the enum,
ruff and **all three controls (V01, V30, G2) passed in 13.35 s**. The callback saw
exactly the completed preparation, the writer ran once outside the protected
action, and the unchanged refusal/zero-effect assertions passed. This confirms
the fixture-ordering repair on SQLite; it does not by itself identify the hosted
hang or satisfy the required PostgreSQL/full exact-head gates. Those are pending.

### D6: V35 retained the same impossible replacement schedule (fixture repair)

**Evidence.** D5 repaired V30 but missed its other caller:
`test_v35_diagnostics_carry_only_fixed_code_values` still injected `bump_dispatch`
as `after_prepare`, inside the protected action. The next head's local gate passed
18,267 tests and 2,883 subtests, but its hosted PostgreSQL job remained in its test
step after an hour. Live hosted logs were unavailable; this is not identification
of that job's hung testcase or proof of its cause.

**Hypothesis H-V1-V35-SCHEDULE-1.** Reuse D5's actual-fence observer and
pre-readiness replacement schedule for both V30 and V35, rather than repairing
callers separately. First observe V35's unchanged old schedule, then move only its
replacement injection outside the protected action. Preserve all diagnostics
checks and literal `dispatch_generation`, zero claims/sends and empty readiness.
No production, frozen input, compiler or CI change. Falsifiers: no observed nested
write in the old schedule, missing preparation callback, a corrected nested write,
changed refusal/diagnostics or weakened fence. Continued hosted stalling requires
further diagnosis rather than a claim that this repair solved it.

**Failing-first result.** The old V35 schedule fails the outside-fence assertion in
2.85 s: observed writes `[True]`, expected `[False]`. The observer stops before the
second-session write, so this discriminates fixture ordering even on SQLite.
`GenerationReplacement` now reuses the real action observation and the completed
preparation callback for both tests. **V01, V30, V35 and G2 passed together in
13.48 s**, with one outside-fence replacement and one completed preparation in
each changed control. V35 retains all diagnostic/body-exclusion checks and now
also explicitly asserts zero claims/sends and empty readiness. Ruff and diff
checks passed. Full ordinary and exact-head PostgreSQL gates remain required;
these local results do not establish the hosted hang's cause.

## Predicted and actual codes

The refusal code for each new control was written down before its first run, from
the contract's semantics and the matrix. Where the composition gave another code,
the mechanism was checked before the test was pinned to it. Every difference is
below. These are code/ordering differences, not permission to change matrix
outcomes. The former V11/V14 ACCEPT-versus-REFUSE failures were repaired under D4,
not re-pinned as passing expectations.

| Control | Predicted | Actual | Why |
| --- | --- | --- | --- |
| V10 unknown extra field | `field_set_drift` after reading rows | `field_set_drift` **before any row is read** | the contract knows the source's node field set and refuses the wire first |
| V11 inline dynamic ref | refuse at submit | `wire_schema` before any row is read | an interpolated record name is not a name the wire schema allows |
| V11 template node type | refuse at submit | `graph_mismatch` before any row is read | the contract requires every non-stage node to be an agent with a factory |
| V11 extra inline model node | `graph_mismatch` after reading rows | `graph_mismatch` before any row is read | the same contract rule |
| V16 slash alias | `outside_closure` or `wire_schema` | `wire_schema` before any row is read | refused as a name |
| V24 wrong valid node path | `position_mismatch` | `graph_mismatch` | the use site looks the node up under the context's path, finds a different admitted object, and refuses before the position check |
| V27 preparer without durability | `root_readiness` | `wire_schema` | a readiness receipt with `durable: false` is not a valid receipt |
| V28 worker died mid-run, same entry again | `dispatch_generation` | `root_readiness` | the new dispatch proposal keeps the dead worker's readiness; the contract refuses readiness bound to another dispatch nonce, so roots are never trusted again |
| V31 record rewritten to format v2 | `wire_schema` | `unsupported_version` | the more specific code for "unsupported admission version" |

## Fixture independence

- **Literal oracle.** Every expected value (descriptor, raw records, queued record,
  claims) is written by hand in the test from the raw rows, with json and hashlib
  only. No loader, codec or engine output builds an expectation.
- **A1 compiler/contract compatibility for the same synthetic authoring.**
  `test_clean_case_matches_architecture_a1_compiler_unmodified` feeds the same
  14-record authoring input to A1's unchanged compiler in
  `tests/test_config/test_context_profile_admission_compile.py`. Its descriptor
  equals the handwritten synthetic descriptor byte for byte. This is an
  independently implemented compiler/encoder cross-check, not an independently
  sourced second graph or execution of Architecture's real oracle.
- **Four admission blockers illustrated by a reduced synthetic harness.** These
  are the four identified blockers below, not an exhaustive list of differences
  from Architecture's real 14x3 oracle:
  - d1: each leaf agent's body `name` equals its record key;
  - d2: script templates use supported indirection (`{{ label }}` outside quotes);
  - d3: metadata inputs are explicit and complete;
  - d4: root policies are synthetic, test-only, on temporary paths and bytes.

| Property | Reduced synthetic V02 | Real published oracle inventory |
| --- | --- | --- |
| Raw records | 85: 1 workflow, 14 stages, 70 agents | 60 |
| Flattened graph | 84 nodes: 14 stages and 70 leaves | 126 nodes, 14 top-level |
| Script positions | 28: one prepare and one receipt per record | 70 |
| Native positions | 42 | 42 |
| Output roots | 14 temporary physical roots; each record's three native slots share one | 42 distinct roots in published position metadata; custody remains unresolved |

For each synthetic record the execution is prepare -> three chained native calls
-> receipt. This reduced topology, script schedule and root sharing are additional
differences, not coverage of the real oracle's unexercised topology or cross-root
paths. Forty-two unique `(root, slot, position)` tuples do not mean 42 physical
synthetic roots. No I1-I4 blocker is cleared by this synthetic pass or A1
compatibility. This disclosure corrects Security's E1 evidence finding; it does
not change the harness to claim new real-oracle coverage.

## The real 14x3 oracle on this head (F1)

Architecture asked (rm-fcdb0a1c) for the real #316 oracle's inventory facts to be
rerun on the composed head. A read-only probe loads A1's unmodified oracle through
the real T1 loader and the real contract, and records every refusal at its call
site. Output and probe are kept privately with the handoff (probe SHA256
`ead597de2410d862ef82b15cdc06efee8ad44c5eb5939960b6a83cd0a03b0602`, output SHA256
`4dbca77c2626d649a9097a30f9a62ceb6b2930082d9484e0904816e9418e2d6e`).
This probe was repeated after D4; the same four facts and exact relaxed projection
hold, and the output records the files measured.

Oracle: descriptor wire SHA256
`e9b69ab16c6477f5dddf4647e88702edcb1d9e4535974fde5235f23b998a6bd8`, 60 records,
graph of 126 nodes (14 top-level), 42 positions, 70 scripts.

| Fact | Count | Check | Code |
| --- | --- | --- | --- |
| I1: a leaf agent's body `name` is not its record key (all are `context_profile_candidate`) | 42 of 42 | `candidate_admission.validate_raw` | `closure_mismatch` |
| I2: a script template the real ScriptAgent renderer refuses | 70 of 70 | `script_agent._rewrite_interpolations`, called by `candidate_admission._script` | `wire_schema` |
| I3: metadata inputs `{"record_id": "r01"}` against 14 declared workflow inputs; filling defaults adds 13 keys | 1 | `candidate_admission.load_candidate` | `graph_mismatch` |
| I4: a position with no root policy (custody unresolved) | 42 of 42 | `admission_contract.require_custody`, called by `DbAdmissionTransport._checked` | `unresolved_custody` |

I2's literal refusal: "script for 'admitted-script' interpolates inside single
quotes: '{{ record_id }}'. A shell expands nothing there, so the value cannot be
passed — the script would receive the variable's name as text. Remove the
surrounding single quotes; the value is quoted for you."

**d2's mechanism.** The ScriptAgent renderer never puts a value into the command
text: it moves each `{{ name }}` written outside quotes into an environment
variable and leaves only a reference to it in the command. Inside single quotes a
shell would expand nothing, so `_rewrite_interpolations` refuses that form with
`ScriptRenderError` instead of passing the variable's name as text. The real
oracle writes `'{{ record_id }}'`, so all 70 templates refuse; the synthetic case
writes `{{ label }}` outside quotes.

Unrelaxed, the real loader refuses the real oracle at its first script
(`wire_schema`). With exactly the three loader checks I1-I3 relaxed in memory
(nothing on disk changed), the load is accepted and the projected graph equals the
descriptor's graph: both SHA256
`1bbfb207b9316b088fbd08113283c97810b4d407bb7547365b9bdc43667b28a6`, 126 nodes.
This establishes graph-projection equality under those three deliberately relaxed
loader checks, not admission or end-to-end execution of the real topology,
custody, readiness, claims or sends. I1-I4 remain unresolved.

## S3 and S4, owed from T2's handoff

- **S3: the lane check at install reads the graph the run loads.** T2 decides the
  run's lane at install from the adapter's captured graph and refuses a Pi graph
  there. `test_s3_the_lane_check_at_install_reads_the_graph_the_run_loads` shows the
  graph the lane check saw at submit and the graph the worker ran are both exactly
  the approved literal graph. `test_s3_a_pi_capture_is_refused_through_the_real_adapter`
  shows a Pi step cannot reach the queue through the real adapter: a database row
  that became a Pi step refuses `digest_mismatch`; a Pi step the authority signed
  refuses `wire_schema` (the schema's factory types are script and single_call
  only); a Pi config under a native factory label refuses `graph_mismatch`.
- **S4: install refuses before the insert.** Through `submit_candidate` any refusal
  rolls the whole session back, so a check moved after the insert would still write
  nothing there. `test_s4_install_refuses_before_the_insert_even_when_the_caller_commits`
  calls install in a caller that catches the refusal and commits: an empty capture
  refuses `descriptor_authority` and a Pi graph `unsupported_mode`, and no row
  exists either way. Bite: moving both checks after the insert makes both cases
  fail with a committed row.

## Cost: checking grows faster than the graph

Every use re-projects the whole admitted graph and compares it with the approved
side, and every generation fence re-verifies the whole record. That is what catches
a tree mutated after the load (V03, V15) and a config changed between the check and
the factory (V22), so the work is real, but a candidate run's checking cost grows
with the square of its graph.

| Case | Records x leaves | Wall time |
| --- | --- | --- |
| V01 | 1 x 3 | about 4 s |
| V02 | 14 x 3 | 623.43 s test body (624.24 s total), 2026-10-30; 20-core host, starting load 25.61 / 28.95 / 34.09, ending 21.94 / 34.01 / 36.36 |

D2 removed the avoidable part (the expected side decoded again at every node). What
remains is the projection of the actual side. The cheaper shape would be to project
only the node being used and compare the tree's shape once per load; that narrows
what a single use compares, so it is a contract decision for Architecture, not a
tuning change inside V1. This branch leaves the delivered shape untouched and
records the measurement for the dev batch.

## How to run it

```
env -u TEMPER_TEST_DATABASE_URL uv run pytest tests/test_runner/test_candidate_admission_integration.py
```

No database server, no network and no model are needed locally: an in-memory
SQLite database, a counting sentinel sender and temporary roots under `tmp_path`.
`tests/test_runner/` is in the database tier (`tests/pgtier.py`), so CI's
`tests (postgres)` job runs the same file on real PostgreSQL. V02 carries its own
timeout mark.

## V01-V36

Every expected outcome below is the matrix's own text; no expected value was taken
from the engine or from A1's compiler. Codes are the contract's fixed refusal codes.
"Before any row is read" means the contract refused the wire, so the capture never
started.

| Case | Expected (matrix) | Controls and code | Result |
| --- | --- | --- | --- |
| V01 | ACCEPT through B5; consumed config and metadata equal the oracle; zero ordinary lookups or substitution | happy path `V01-tiny`: stored record equals the literal one; transformed lookups, env substitution, Guard config and template expansion all zero; one claim per position on the receipt's root | PASS |
| V02 | ACCEPT exactly 42 unique position tuples; uniqueness is root plus slot and position | happy path `V02-14x3`: 42 claims on 42 unique tuples; A1 cross-check | PASS |
| V03 | REFUSE pinned raw digest; a later mutation is caught at B4/B5; zero wrong claim | a valid A1 leaf becomes a valid A2 in the database (`digest_mismatch`); the slot changed after the load (`graph_mismatch`) | PASS |
| V04 | REFUSE; an independent node-path to position map catches the swap again at B4 | two per-call maps swapped in the database (`digest_mismatch`), and after the load (`graph_mismatch`) | PASS |
| V05 | REFUSE against the family-A oracle before provider lookup or claim | other model, other family (`digest_mismatch`) | PASS |
| V06 | REFUSE before any token lookup; the token NAME belongs to the tuple | token renamed, missing, null (`digest_mismatch`); no token value is read anywhere | PASS |
| V07 | REFUSE against the exact per-call path, digest and length | another path with the same bytes (`digest_mismatch`) | PASS |
| V08 | REFUSE; syntax is insufficient, and the root must match the permitted root at B5 | another valid 64-hex digest, another output root (`digest_mismatch`); V25 at the claim | PASS |
| V09 | REFUSE before `substitute_env_vars`/`Guard.config`/`GraphLoader`; zero environment access | a marker in a model, path, token name, identifier, nested list, dict key (`wire_schema`); env substitution counter zero | PASS |
| V10 | REFUSE raw presence or marker; cannot pass by becoming unreachable | marker in on_failure or workflow defaults, template text in another key (`wire_schema`); unknown field (`field_set_drift`, before any row is read); `_KNOWN_FIELDS` key (`field_set_drift`) | PASS |
| V11 | REFUSE before graph expansion | Jinja in a non-script field, dispatch node/config/agents, extra tool node and non-null loop target (`wire_schema`); inline dynamic ref (`wire_schema`, before any row is read); `template` node type and extra inline model node (`graph_mismatch`, before any row is read); D4 proves otherwise-valid approved loops refuse at B1 | PASS; null/absent target or a standalone count is not an active loop |
| V12 | ACCEPT; resolved metadata checked before the renderer; no private body, answer or key | happy path: every rendered command holds only references, the admitted value is in the environment; V35 | PASS |
| V13 | REFUSE; the renderer exception is per exact script field and bytes | extra placeholder, template filter (`wire_schema`); unapproved input map (`digest_mismatch`) | PASS |
| V14 | REFUSE prohibited raw presence even where loader would ignore | D4: approved node/workflow tools/memory presence (`wire_schema`); fallback and closed defaults (`field_set_drift`); null/empty/nonempty controls, zero expansion/factory/claim/send; same bytes submit if only the raw validator is disabled | PASS; supported cleanup/gate/rename metadata stays eligible and pinned |
| V15 | REFUSE the exact raw inventory; B2/B4 detect the resolved-tree mutation | remove a node, duplicate name, change dependency, timeout, condition, on_failure, undoes, gate, renamed_from, outputs, an extra referenced record (`digest_mismatch`); a body named differently from its key, an unreachable admitted record (`closure_mismatch`); node removed, dependency changed, duplicate name after the load (`graph_mismatch`) | PASS |
| V16 | REFUSE a noncanonical ref or missing tuple; never the stage-to-workflow fallback or a basename alias | missing stage row with a same-name workflow (`outside_closure`); unqualified ref (`closure_mismatch`); slash alias (`wire_schema`, before any row is read) | PASS |
| V17 | Continue the original owned snapshot, not a new row; zero execution-path get | rows rewritten and the stage row deleted after submit; every row deleted and re-imported under the same names: the run completes on the snapshot, raw reads unchanged, transformed lookups zero | PASS |
| V18 | Capture one transaction and compare every exact record digest; no mixed closure | schema version changed between approval and capture (`closure_mismatch`); a row changed during the capture (`digest_mismatch`, no row written) | PASS |
| V19 | REFUSE via the file or blob guard before `Guard.config`; no DB fallback | a database capture under a classified box, empty, with an env marker, or with other bytes (`unsupported_mode`, no sealed-file read); classified bytes parsed by a guard that is not the active one (`source_origin`); unsupported version (`unsupported_version`) | PASS; content checks inside sealed files are unreachable in v1, which refuses classified origins first |
| V20 | REFUSE before graph or claim | a candidate under a sealed box refuses at worker entry (`unsupported_mode`) | PASS |
| V21 | Aliases cannot alter the owned bytes; parses are independent; aliased or cyclic input rejected | YAML alias (`aliased_or_cyclic_value`), duplicate key (`duplicate_key`), not a mapping (`invalid_type`); cyclic raw input (`closure_mismatch`); a shared nested alias inside one raw body (`aliased_or_cyclic_value`); source objects mutated after capture change nothing | PASS |
| V22 | REFUSE before the factory; the invocation owns a fresh checked config | agent config mutated after the node check; a sibling's nested mapping mutated before the factory (`graph_mismatch`, no claim, no send) | PASS |
| V23 | Factory output type and config identity REFUSE before the claim | the factory returns another class, changes the agent config; a retained config changed before entry (`field_set_drift`); admitted bytes unchanged | PASS |
| V24 | REFUSE at input admission or at use; external run id distinct from the native id; capability bound to run and full node path | caller preselects the execution id, overrides the run id or workspace (`protected_metadata`); filled defaults (`graph_mismatch` at submit); explicit complete inputs ACCEPT; a sibling's capability (`position_mismatch`); a wrong valid node path (`graph_mismatch`) | PASS |
| V25 | REFUSE using the fd the claim would use; zero claim or send | root mode changed, root replaced, symlink parent, each after readiness (`root_readiness`, no claim, no send) | PASS; an owner change needs root privileges and is not tested here |
| V26 | ACCEPT the descriptor-bound exact root; uid, mount and custodian synthetic | happy path: readiness binds the descriptor's root; the claim is on that same inode | PASS (synthetic, as the matrix says) |
| V27 | REFUSE a new claim or send; keep the consumed state and evidence | preparer without durability (`wire_schema`); missing or stale receipt (`root_readiness`); an existing claim file is never taken again and keeps its bytes | PASS |
| V28 | Restore the original bytes and generation; roots revalidated; completed leaves not replayed | a completed run entered again (`dispatch_generation`); a worker that died after its first send, entered again (`root_readiness`): one send, claim files unchanged, record unchanged | PASS |
| V29 | REFUSE a mismatched or consumed claim; a fork needs its own admitted identity | a candidate row carrying resume or rerun (`unsupported_mode` at worker entry); a fork that copies the admission, even with a vouching authority (`protected_metadata`) | PASS |
| V30 | The current-generation check refuses stale side effects | a replacement wins before the stale worker enters its protected readiness action (`dispatch_generation`, zero claim/send, readiness unchanged); D5 asserts the writer is outside the old row fence | Corrected focused SQLite PASS; full exact-head/PostgreSQL gate pending |
| V31 | REFUSE and retain the original protected record | the handle stamp refuses to replace it (`protected_metadata`, record unchanged); a record rewritten to format v2 refuses at worker entry (`unsupported_version`) and is not rewritten | PASS |
| V32 | REFUSE; replacing the trusted caller authority is out of scope | a changed manifest carrying its own digest (`descriptor_authority`) | PASS |
| V33 | Separate fresh loaders and contexts per admitted run | overlapping real B2 snapshot loads receive the same poisoned legacy runner/loader/defaults/overrides; a barrier proves overlap; each uses a fresh resolver/loader and equals its literal graph. Separate sequential full runs prove independent contexts and claims | PASS for B2 overlap and sequential full-run isolation; not a simultaneous end-to-end worker test |
| V34 | REFUSE a designated candidate before the transformed load; ordinary workflows unchanged | a designated workflow without an admission refuses at worker entry (`admission_required`); the ordinary suite is unchanged | PASS |
| V35 | Only fixed codes, position ids and digests in evidence | a stale-generation refusal using D6's shared outside-fence replacement: the only code recorded is `dispatch_generation`, and none of the fixture's strings appear; zero claim/send and empty readiness | Corrected focused SQLite PASS; full exact-head/PostgreSQL gate pending |
| V36 | The native defence fails honestly, possibly after the claim; no retry | a native failure after the claim: run failed, the claim stays, the slot is not tried again, no send | PASS |

Also covered on this head by T2's own tests, which run in the same suite and whose
path is entirely T2's: a reserved key in a queue extra and in every ordinary metadata
writer (V31), and the API and CLI starts of a designated workflow (V34), in
`tests/test_runner/test_candidate_admission_transport.py`.

## V33 coverage repair

**Hypothesis.** The original two-run check was sequential, so it could not expose
state shared during simultaneous resolution. Add a barrier inside the actual T1
snapshot loader, run two B2 loads concurrently against the same legacy runner with
poisoned, aliased defaults/overrides, and compare each result with its own literal
descriptor. A cross-run config, shared loader/resolver, or missing overlap disproves
isolation. Keep database transactions sequential to avoid mistaking SQLite's one
connection for the concurrency property under test.

**Result: hit.** The new overlapping-load control and retained sequential
submit-to-claim control passed together (2 tests, 9.59 s). No engine check was
changed. This proves overlap at B2, not concurrent whole-worker execution.

## The production authority gap

V1's authorized caller is a **typed test object**: the test constructs the bindings
and calls the entry points directly. In production, designation and authority are
published through the existing named authorized registration caller after custody;
that is **A4** in Architecture's plan, and it is not built here.

So on the landed head:

- no production designation exists, and the real preload path stays unbound;
- an unbound designated run refuses (V34), and a sealed or classified box refuses
  before any load (V19, V20);
- the synthetic root in these fixtures is not live custody, and nothing in this
  branch should be read as custody being resolved.

V1 records this gap rather than inventing a registry, a key or an authority.

## What landing changes

- New behaviour reaches a run only when its row carries the reserved
  `config_admission` slot **and** the caller injected bindings. No ordinary run has
  either, so ordinary runs are unchanged; the ordinary suite must pass on the same head.
- The opt-in path supports only the external-db-fresh mode; every other mode refuses.
- There is no SQL schema migration, but candidate admissions create protected
  stored metadata. Rollback must retain every admission record and consumed claim,
  and retain the ingress/worker refusal compatibility fence until admitted rows are
  terminal or supported code is restored. Old code must never dispatch an admitted
  row by mutable workflow name alone. Reverting the feature is safe only with that
  operational fence in place; this task does not authorize disabling it.
- Landing does **not** release Architecture's #293 and does **not** mark binding
  MET. That decision is Architecture's, on this evidence.

## Proof required before landing

The following are still required, not results implied by this document. The exact
head/tree and receipts will be recorded outside the commit to avoid self-reference:

- the full suite through the normal pre-commit hook, on the supported local SQLite
  route (`PRECOMMIT_PG=0`), with no `--no-verify`;
- all 8 required checks on CI for the exact head, including `tests (postgres)`;
- Architecture's land check (ADR-M4-17) and Security's review of the authority and
  provenance boundary, each bound to the exact head. Neither is implied by this
  document.

The head, its tree, the CI run and both verdicts are recorded with the land request
to Architecture and the private handoff under `company-lab/temper/admission-v1-208/`.
