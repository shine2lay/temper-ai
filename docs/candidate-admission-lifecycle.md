# Candidate admission: protected transport (T2, source candidate only)

## Hypothesis H-T2-TRANSPORT-1

Evidence/problem: the legacy queue replaces `spawner_metadata`, the handle writers
merge arbitrary metadata, workers update their attempt separately from their
config load, and resume/fork/preview reload a mutable workflow name. None of those
operations originally knew a reserved admission slot. A valid initial descriptor
would therefore not alone protect a later execution.

Change: one immutable owned CAJ-1 admission record in the existing
`WorkflowRun.spawner_metadata.config_admission` slot; transaction-bound install,
nonce transition and compare-once readiness; snapshot restoration before ordinary
bootstrap/loading; version-independent early tombstones on unsupported entries.

Expected measurement: combined synthetic install → watcher claim → restore →
worker dispatch → handle/update preservation → readiness → fenced native claim
passes; each altered identity/provenance/generation/entry fails without loading a
mutable workflow or invoking the native callback. Actual remote PostgreSQL races
must establish collision exclusion and a row lock held throughout the callback.
Falsification: any enumerated writer loses bytes, entry reloads a protected name,
changed authority/source is accepted, or stale claim callback runs. Test evidence
and exact candidate/patch identities belong in the delivery receipt, not a claim
that this document itself proves the composed runtime. Initial implementation is
subject to that test result.

Initial local touched-suite result: 146 passed, 7 failed. H-T2-FIXTURE-1:
the failures identify test-harness mismatches (keyword-only runner calls, mandatory
synthetic workspace, wrong-workflow registry refusal) and the HTTP test's source
field inventory still describing T0's tiny request instead of the explicit T2 HTTP
mapping. Correct those literal input fixtures and independently repin that test's
source/descriptor; do not weaken the frozen field-set guard. Expect the corrected
cases to pass; any acceptance without the correct out-of-band source pin falsifies
this repair. No production guard was relaxed for these failures. All seven corrected cases
subsequently passed; the first 146 passing cases had no behavioral changes.

H-T2-TYPES-1: whole-package mypy found 23 errors because the frozen transaction
interface accepts `object` and Python's analyzer cannot infer the relationship
between a restored record and its bound session/row/adapter. Make the existing
runtime session check return `Session`, return a required row with its checked
record, and make already-verified branch narrowing explicit. Expected: unchanged
runtime refusal behavior and a clean whole-package typecheck without ignores or
contract changes. An invalid transaction reaching a writer or a changed guard
outcome falsifies the repair; a dedicated invalid-transaction control covers it.
Whole-package mypy subsequently passed 331 source files; all three invalid-session
controls passed without touching a row.

H-T2-DEFAULT-ZERO-1: the inherited writer invariant deliberately forbids every
constructor `attempts` override, including redundant zero. Remove T2's redundant
keyword and retain the existing model's tested `Field(default=0)`. Expect unchanged
queued attempt-zero installation and an unchanged no-override guard; a nonzero
installed attempt or any need to weaken that guard falsifies this correction.

H-T2-INVENTORY-CONTROLS-1: adding legitimate writer sites must not mask future
missing/extra/count changes. Add three dedicated in-memory source controls using
the unchanged shared census, requiring the unmutated assembled source to pass
first; delete a known T2 store, duplicate that store, and introduce an unreviewed
site. Expect each altered inventory to fail closed-set/count equality. A mutant
passing, or a broken baseline hidden by the expected failure, falsifies this test.
The shared oracle's owning consent/admission is required separately for its exact
literal inventory.

Census delta (Temper lead's recorded #198 plan change on Architecture's consent
rm-369d8441; Architecture's bound review of the exact source+census pair comes
before commit): `tests/test_runner/test_writer_scan.py` gains exactly four literal
`RUN_WRITERS` entries, ten field-sites, each a real T2 run-row store; scanner,
predicates, `_require`, callers, scopes, closed set and count logic are unchanged:

* `cli/run_workflow.py::cmd_run_workflow` attribute `spawner_handle`: admitted
  candidate only, in the same transaction as `bind_dispatch`'s locked CAS.
* `DbAdmissionTransport.install` insert (all five fields): row at the
  preselected UUID; locked absence plus savepoint PK refuse a collision; attempts
  keeps the model default 0.
* `DbAdmissionTransport.bind_dispatch` attribute `status`, `attempts`,
  `spawner_metadata`: locked queued attempt 0 + nonce to running attempt 1.
* `DbAdmissionTransport.bind_root_readiness` attribute `spawner_metadata`: locked
  compare-once merge; only the slot changes.

H-T2-CLAIM-ANCHOR-1: the shared census's removal bite for the Pi lane's
`conditions.append(WorkflowRun.status == "queued")` in `_claim_row` stopped
failing, because T2's candidate branch had added a literal copy of that statement:
removing one copy left the other to satisfy the anchor, so T2 masked an existing
guard's bite. First change: spell the candidate-only queued condition apart
(`col(WorkflowRun.status) == "queued"`) with its own source-mutation bite.
Result: MISS for the second half. The census bite failed again as expected, but the
new bite could not bite: under the same locked read `_row_record` already refuses
a row whose status, attempts or cancel flag disagrees with the record
(`dispatch_generation`), and the lock holds to the UPDATE, so the SQL condition
was dead code. Revised change (H-T2-CLAIM-ANCHOR-2): remove that redundant
condition, leaving `_claim_row`'s ordinary conditions exactly as before, and bite
the check that does the work: with only `row.status != dispatch["phase"]` removed
from `_row_record` (source mutation), the claim takes a candidate row whose status
moved on while its record phase is still queued. Expected: census bite and the new
bite both pass. Falsified if the unmutated claim takes that row or the mutant
still refuses it.

H-T2-FIXTURE-2: the API `sealed` refusal case passed earlier only because the
T0-sized request field set refused every HTTP case first (`field_set_drift`);
after H-T2-FIXTURE-1 it was accepted, exposing that the test set
`TEMPER_BOX_BOUNDARY`, not the real `TEMPER_BOX_RUNTIME_BOUNDARY`. Change: tests use
the `box_profile.BOUNDARY_ENV` constant and assert each case's own refusal code
(authority, missing, mode), so no case passes for another's reason. Expected: the
sealed case refuses with `unsupported_mode` before any row or loader. Falsified if
the sealed install accepts a candidate.

Each of the six T2 stores behind them has three own bites in
`test_candidate_admission_resume.py` (store removed, a second store in the same
scope, inventory no longer naming it), each required to fail on exactly that
site, plus one unreviewed-module control.

H-T2-ORDINARY-1: a read-only run of the unchanged writer census showed three
expected source expressions missing. The cause was T2's own over-reach, not the
census: the API direct-spawn stamp had been routed through the watcher's merging
writer (ordinary fresh-identity replace became merge-all), `queue_run_in`'s native
lock had been swapped for `locked_run` (an extra SQLite write lock for ordinary
rows), and the watcher merge expression had been rewritten. That changes ordinary
noncandidate behavior, which T2 must not do. Change: restore those three original
ordinary expressions verbatim and protect the slot by fail-closed presence checks
instead (the direct stamp refuses a row carrying the slot; the watcher stamp
refuses spawner metadata naming it before its original merge on a locked fresh
read). Expected: every existing census expectation and mutation control passes
unchanged; the only census delta left is four new T2 run-row writer entries; each
new presence check has its own deletion bite. Falsified if any original
expectation still fails, ordinary stamping/queue results differ, or either handle
writer can still drop or replace a reserved record.

## Contract and scope

Base: `caf5c16f6d9965cbcbc8e10653d75e1c47b27340` (T0 contract).
Unchanged frozen public contract:

* schema `426e1c5a12eafa5a82e64144d25e0fa08d5b844149723ea001a76fe9a0f2041d`
* codec `f9b0f36ed20afaecd12654cd80a203214f3f2d5727f4668fc0c1926fa3df1c34`
* specification `8932a4b97d0d08bea6a919223f83922804d08486545d94d747886253b5825ba7`

`runner/admission.py::DbAdmissionTransport` implements the frozen
`AdmissionTransport` methods; it does not duplicate the schema. No SQL migration.
Records are parsed into owned immutable bytes and fresh copies; metadata merging
owns nested data rather than retaining caller aliases. The original caller label,
authority receipt, descriptor/source pins and preselected execution UUID remain
inside the immutable section. A request's own `run_id` is not that UUID.

Only `external-db-fresh` is prospective supported mode. There is **no production
CandidateBindings installation**, caller registry, custody provisioning, root
creation, ACL change or activation in this candidate. No code here turns a
candidate's own expected pins into independently authenticated pins. The default
opt-in API, protected-row watcher and worker paths refuse without the composition.
Synthetic test adapters are expressly not deployment authority or T1/T3 proof.

## Authority and sibling boundaries

The existing API `CallerMiddleware` / `current_caller` and
`require_caller_may("start")` checks remain. A named caller alone is insufficient.
The injected `CandidateBindings.authority_for_submit(caller, workflow_name)` and
`authority_for_run(execution_uuid)` must obtain `DescriptorAuthority` from a
genuinely authorized out-of-band registry, NOT from descriptor/body fields. The
transport compares that authority with the record and independently calls
`current_source()` on each protected operation. `InstallationVerifier` must verify
T1 capture, request, graph and original custody in the same transaction;
`PreparationVerifier` must verify T3's successful engine NodeResult plus durable
checkpoint provenance. Booleans supplied by a request are not proof.

V1 owns joining actual T1/T3 implementations to these typed seams and proving the
real composition. Deployment authority/custody owners must supply the original
registry, source measurement, worker identity and operational fence before any
actual admission row may exist. The construction of Python data classes or a
passing synthetic adapter does not satisfy that owning action.

T2 entry seams (no imports of an unfinished sibling):

* API: an optional `RunRequest.admission` is CAJ-1 **descriptor data only**. The
  descriptor's `request_options_json` must match the full literal HTTP mapping
  `{workflow, inputs, workspace_path, notify}` with API defaults in place, excluding
  `admission`. Inputs must already equal pinned effective metadata; legacy default
  filling/notify overlay is not performed on the admitted route. T1 prepares the
  record via `prepare(..., request: FrozenJSON, transaction)` before installation.
  Default entry has no binding; an opted-in request refuses before graph loading.
* `CandidateBindings.designated(name)` is an independently supplied pre-admission
  classification seam, not a new naming convention. No authoritative deployment
  designation registry exists here. Arbitrary unadmitted legacy names cannot be
  reliably recognized as candidates by spelling; that gap is not concealed by a
  guessed prefix. V1 must compose the raw/caller designation boundary as well.
* Watcher: `_claim_row(..., candidate_bindings=...)` validates the current protected
  queued record while holding its row lock, before ordinary claim ownership.
* Worker: `cmd_run_workflow(..., candidate_bindings=...)` restores the protected row
  before mutable bootstrap/graph loading. `bootstrap_snapshot`, `load_snapshot`
  and `bind_context` are typed T1/T3 seams. The runner requires a frozen
  `CandidateInvocationBinding` matching descriptor, closure, graph, generation,
  execution UUID and workspace. An omitted/mismatched binding refuses. The
  admitted route does not start the mutable MCP configuration manager.
* `worker_proto.WorkflowRunSpec` remains a legacy parameter object, not an
  authority or closed config snapshot. No unused parallel descriptor field is
  added to it: workers transport only the execution UUID and restore the protected
  record from the row. The actual HTTP request is `api/routes.py::RunRequest`, not
  the legacy similarly named internal model.

## Transactions and generation

`locked_run` refreshes the row under native PostgreSQL `FOR UPDATE`. SQLite gets a
same-value UPDATE first to acquire its write lock (SQLite ignores FOR UPDATE).
There is no commit inside a caller-supplied transaction. Installation refuses an
existing execution UUID and relies on the primary key/savepoint for absent-row
races, translating a collision to a sanitized refusal. It never substitutes a new
UUID. All mutable config/custody validation is a required trusted T1 verifier, not
something the codec claims to do.

`bind_dispatch` compares the actual row with the supplied queued snapshot under
the same fence: attempt 0 → 1, original queued nonce → a distinct fresh running
nonce, `previous_nonce` equals the original, worker matches the independently
measured worker label and descriptor root policies. Immutable bytes cannot change.
`bind_root_readiness` checks trusted preparation provenance, merges other positions
under the row fence and accepts an exact repeated receipt only; changed receipts
refuse. The factory/claim hook still owns same-fd preparation/use validation.

`claim_if_current(record, claim)` holds the row fence across the **exclusive native
claim only**, never a network send. A changed current record/status/attempt,
cancel, source or authority prevents the callback. The callback must be the
existing native single-use claim after T3's full same-fd/config/context/readiness
checks. It is not an arbitrary-send callback or a replacement for native
single-send/consumed-slot checks. T2's synthetic callback proves ordering, not
those native checks.

## Writer and entry census (bounded to this slot)

* `runner/queue.py::queue_run_in`: reserved names in ordinary `extra`
  refuse, including equal/null values. A protected existing row cannot be
  requeued/resumed/replaced via this legacy writer. Its original native
  `FOR UPDATE` read is kept verbatim. Noncandidate queue behavior remains.
* `cli/watch_queue.py::_claim_row`, `_stamp_handle`, `_requeue_stuck_claims`:
  admission-aware claim; a handle stamp that refuses spawner metadata naming the
  slot (even null), then performs its original merge on a `locked_run` fresh read
  so it cannot overwrite a concurrent admission transition; and locked recovery of
  a queued claiming sentinel. `_unclaim` updates only claim columns; it never
  rewrites JSON. A pre-execution SpawnerBusy unwind has not dispatched/consumed a
  slot and may retain the same queued admission.
* `api/routes.py::_start_run_subprocess`: refuses protected/direct candidate use
  before insert/spawn. Its original fresh-identity handle stamp is unchanged for
  ordinary rows; if a reserved record is ever present at stamp time it refuses
  (409, row untouched) instead of dropping it. `_start_run_external` refuses a
  direct bypass of the admitted HTTP path.
* `cli/run_workflow.py::_update_run_row`: locked preserving metadata merge; generic
  writes cannot change the UUID/workflow/workspace/inputs/attempt or manufacture a
  queued/running/waiting transition. Terminal status/error writers keep the slot.
* Existing cancellation, reaper, attempt, parked, lane and cleanup writers change
  selected columns or merge the current JSON. They do not replace the slot.
  Protected records are not Pi-lane runs. The install refuses a Pi run
  (`unsupported_mode`, nothing written) by the existing `lanes.lane_for` on the
  graph the installation verifier returns from the verified capture
  (`captured_nodes`; the real adapter is V1's, and must return the same graph
  `load_snapshot` runs), and writes main-lane rows only, with no mark. An empty
  capture is refused (`descriptor_authority`, nothing written): it would read as
  main lane whatever the real graph is. Later writes copy the row's own metadata, and any
  lane/resume/rerun/only metadata is rejected on restoration and before any
  dispatch or readiness write. Source scans and ordinary regression suites remain
  necessary when those writers change.
* API `_plan_for`, `_resume_run`, `_start_resume`, `_fork_run`,
  `_release_cleanups`, `_queue_cleanup_pass`, direct/inprocess and checkpoint
  execution helpers fence by **row slot presence** before legacy loading/claim or
  hold changes. Renaming/reclassifying the workflow cannot bypass that fence.
* `runner/execute.py` refuses a protected row unless given a matching bound
  snapshot, and refuses resume/replay/rerun/cleanup continuation flags. Worker
  entry refuses unbound or sealed protected rows before ordinary bootstrap.
  CLI validation refuses caller-designated candidates before config import.

`external-db-fresh` infrastructure re-attempts are not blanket-banned retries:
a separately authorized **new execution UUID, new descriptor and new unconsumed
slot** can be admitted as fresh. This never permits resend of a consumed slot,
replacement of a malformed answer, cross-resume claim duplication or erasure of
an old record to make it look new. No new retry/spend/runtime limit is introduced.

## Rollback: two different cases

1. **Retained supported-code tombstone:** keep the presence-only entry fences and
   preserving writers even if the admission feature/classification is removed.
   Null, unknown-version and malformed slots refuse; renaming to an ordinary
   workflow does not erase the record or reload it by legacy name. Refuse, preserve
   and inspect through an authorized operator—never strip metadata to retry.
2. **Older binaries without this slot:** they cannot recognize these records. The
   codec cannot retrofit them. Before admitting any real row, the operational
   deployment boundary must ensure no such API/watcher/worker/CLI/pickup/cleanup
   binary can access the admitted rows or dispatch them. Rollback must retain the
   tombstone-capable build, or keep dispatch/access fenced while a separately
   approved reconciliation handles the rows. Reverting to an unaware binary with
   shared dispatch access is unsafe. This candidate installs no operational fence
   and grants no authority to do so.

## Evidence plan and limits

Dedicated suites `tests/test_runner/test_candidate_admission_transport.py` and
`tests/test_runner/test_candidate_admission_resume.py` are in the existing remote
PostgreSQL test tier. They open with combined synthetic happy paths, then literal
input/authority/source/UUID/nonce/version/writer/entry/readiness mutations and
in-memory guard-deletion controls. PostgreSQL-only branches state explicitly when
local SQLite supplies **no concurrency evidence**. Remote tests arbitrate two
absent-row installs and prove a NOWAIT competitor cannot take the row while the
native claim callback holds it. No local PG, separate Temper, model or shared DB.

Local checks use the ordinary supported SQLite hook method:
`env -u TEMPER_TEST_DATABASE_URL PRECOMMIT_PG=0 ...`; normal hooks are retained.
Exact final-head remote `tests (postgres)` and the other seven required checks
must pass before source delivery. Passing tests remain source-only evidence: no
actual admission row, original packet transfer, registration, runtime proof,
custody, land, deployment or release is claimed.
