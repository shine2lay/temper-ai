# Numeric usage recovery and internal cutover

This is internal capture diagnostics, **not an occurrence-completeness feed**.
`coverage_state(session)` is pure read and always returns `status: UNKNOWN`.
There is no `complete_through`. A cutover, fresh heartbeat, empty pending table,
absence of faults, or allocation of a sequence does not change that answer.
No read route, collector, payer, project, task or scope attribution is added.

## Wake order, limits and off switch

The server owns one daemon alongside its existing sweepers. Every60seconds
(start-to-start, except an overrun), it does these stages in order:

1. Attempt pending capture drain, exclusively using the landed
   `usage_rows.drain_pending_row` helper from #125.
2. Reconcile numeric leaves in the bounded history window.
3. Check exactly linkable unended starts and the internal cutover conditions.
4. Record genuinely missing post-cutover capture faults, never fill them.

A wake admits at most200 Event-row attempts in total (drain first,
then reconciliation, unended revisions and missing-row checks), with no ordering
lock spanning those attempts. Skipped, busy and unknown candidates count too. Each diagnostic selection also has a200-candidate cap.
Pending admission budget is20s; reconciliation20s; unended5s. A50s
shared wake budget stops admitting later stages/rows. There is25ms pause between
row transactions. Each PostgreSQL statement has a5s timeout;
ordering-lock wait remains #125's2s. Budgets stop admitting another row, not kill
an atomic helper mid-write; one admitted statement can finish after its budget.
A failed sweep logs a fixed class name, never event/exception contents. There
is no model call, provider request, workflow proof, or separate Temper instance.

`TEMPER_USAGE_RECONCILER=0` disables **both** drain and reconciliation. An OFF
wake makes no heartbeat writes. Readiness registration is independent startup
version evidence, not a drain attempt or completeness certificate. The switch
is on by default. The existing `TEMPER_USAGE_CAPTURE` writer switch is separate.
Changing a server environment setting uses the usual controlled deployment.

## Pending attempt and truthful heartbeat

The drainer orders by typed `pending_at`, then native `event_at`, event ID
and revision. ID and revision are tie-breakers **only for equal timestamps**. A persisted typed
cursor resumes after attempted rows and wraps to the oldest. Thus a busy head
cannot permanently exclude later records. New entries passed by that cursor
are seen after it wraps. There is no UUID-as-time or fabricated provider time.

One Event row lock precedes #125's usage ordering statement. The caller commits
immediately after the helper, never holds the ordering lock across a200-row
Python batch. #125 owns cross-store revision uniqueness, equal-final
idempotence, unequal-final rollback/retain-pending and atomic DELETE+FINAL.
Pending is internal numeric evidence, **never an external v1 row**. Ordering
`deferred` is internal, not an external event kind.

Only after the attempt is completed is `usage_drain_heartbeat(id=1)` upserted.
`last_drain_at` is the **completed-attempt** time, including empty, busy,
deferred and fixed-fault attempts; it is NOT last successful drain time.
`drained` counts only the helper's actual `drained` outcomes. Separate counts
retain attempted, already-final, missing, busy, deferred, faulted and remaining.
Busy/deferred/faulted captures stay pending. A failed or interrupted heartbeat
write cannot advertise completion. No stamp is written before a hanging helper
returns. A drain fault is recorded with the closed `drain-fault` code.

PostgreSQL uses `clock_timestamp()` after row attempts, not the transaction-start
`CURRENT_TIMESTAMP`; SQLite uses its database `strftime(...,'now')` clock.
`pending_at` is #125's application record-construction clock. `event_at` is the
native application Event clock, not DB commit time or provider-end time.
DB-clock assessment of pending age explicitly combines those clock provenances;
a bad/fast application clock is not silently corrected into occurrence proof.

`drain_state(session)` is a separate pure read: enabled, pending count, oldest
pending time, completed-attempt time, checked-at, outcome/counts, codes, stalled,
and clock provenance. Closed codes are `pending-old` (>15minutes),
`drain-silent` (pending and no completed attempt for>5minutes), and `drain-off`
(pending while disabled). Any such code makes `stalled` true; none alters
UNKNOWN coverage. A busy but completed attempt prevents a false drain-silent
alarm, while pending-old can still truthfully remain.

### Two different time obligations

* **60seconds:** bounded attempts and completed-attempt diagnostics while
  enabled. A cadence signal, not a successful-drain claim.
* **15minutes under declared NORMAL ARRIVAL:** eligible pending records drain
  within15minutes with available DB, working writer helper, no permanent Event
  or ordering locks, initial backlog<=200, arrival<=10records/minute, and normal
  row service<=100ms plus25ms spacing, with one wake/minute. Fixed-input tests exercise this case with an accelerated
  queue clock. Actual server ordering-lock HOLD is separately measured below.

No universal15minute promise covers outages, busy/unequal-final/deferred
captures, clock faults, or sustained overload. Those keep their actual evidence,
outcomes and ages visible; the system never invents success to quiet an alarm.

## Leaf-only historical recovery

Recovery uses fixed SQL leaves: native event references/type/timestamp,
model/provider labels, numeric token/cost slots, llm_call_id, call_kind,
started_event_id, executed_by, restored_from_fork, and **array length only** for
lost_attempts. Malformed containers never cross that SQL boundary; fixed invalid
sentinels preserve #125 extraction fault codes. No whole Event.data, messages,
prompts, tools, answers, or lost-attempt payloads are loaded. Syntactic label
validation is not a general secret-detection guarantee (the #125 boundary).

Current Pacific week is attempted first, previous Pacific week second.
America/Los_Angeles Monday00:00 defines weeks; calendar arithmetic preserves DST.
The lower bound is the previous week's start, never older history and always
less than15days ago. Older history is **not-backfilled**. Upper bound is the
current DB-clock assessment, not arbitrary future-dated events. Fixed finite
batches traverse a typed `(week-priority,event timestamp,event ID)` keyset.
Each lap has a frozen DB-clock upper bound and wraps to the window start;
rows committed behind the cursor are revisited on the next lap. A cursor
is only scheduling state, never progress or coverage proof.

The anti-join excludes BOTH final and pending captures (any revision), skips
fork copies, then rechecks after the source Event lock. Only #125 extraction
and its idempotent writer append `origin=reconciled`; no independent insert or
pending-drain implementation exists. A concurrent live projection wins rather
than being overwritten by a differing reconciled projection.

`TEMPER_USAGE_BACKFILL_FROM` is not accepted here. Widening needs a later normally
approved plan and sizing. This work does not change Events, run totals,
retention, trim, or backup policy.

## Internal cutover and faults

Server, normal watch-queue worker and Pi watch-queue worker each upsert a fixed
`usage_writer_ready` kind with writer_version1 and DB-clock ready_at at startup.
The existing worker lane selects worker versus pi-worker. Missing readiness
blocks cutover. T is the latest of those three ready times.

Every execution whose first native event predates T must be terminal:
completed, failed, cancelled or interrupted. Parked, waiting, queued, running,
unknown and orphaned are not terminal evidence; old run-box code mounts are
therefore covered, even outside the backfill window. Both WorkflowRun and
workflow.started state are checked; no terminal evidence also blocks.

After that barrier, start one full bounded recovery lap, bound to the exact
ready times and window. Persist its DB-clock start, typed keyset and dirty/
complete flags. A failed/skipped row or a new deferred capture makes the lap
dirty; finishing a cursor alone never suffices. A new ready boundary or window
resets it. Only a clean, completed lap started after readiness AND a final
whole-window empty anti-join can record `cutover_at=T` and `cutover_seq` once.
This catches eligible rows committed behind a construction-clock cursor.
They never move on later startups. The sequence is an internal observation,
NOT a coverage prefix or occurrence watermark. Pending captures need not be
externally visible to qualify as captured evidence.

After cutover no missing capture is silently filled by reconciliation.
Eligible nonfork post-T call events with NEITHER final nor pending capture
receive `post-cutover-missing-row`, including events from a rolled-back old
writer. Event-lock recheck prevents a concurrent capture becoming a false fault.
Existing numeric pending continues through #125's drain helper, not recovery.

`usage_faults` is capped globally at10000 rows with unique event/code pairs.
Thereafter `fault_overflow` counts **encounters** that could not be stored,
not distinct omitted events. Repeat encounters may increment it again; it is
not a fabricated unique-event count. Fault codes and diagnostic phases are
closed. Fault counts, phase, history lower bound, cutover and checked-at are
returned by `coverage_state`; status remains UNKNOWN in every phase.

### Exactly linked unended-start diagnostic

This is a new revision of an already captured start, not an end or zero cost.
The existing stored basis stays `call_start` (no live CHECK/VARCHAR migration).
Its closed fault code is `call-unended`; #127 maps that combination to the wire
basis `call_start_unended`. Token and legacy-cost fields are NULL, origin is
`reconciled`, and occurred_at remains the start's native application timestamp.
The original live revision stays append-only. No usage or cost is inferred.

All qualifying evidence is checked in ONE SQL snapshot after that wake's drain:

* The start has its own same-instance LIVE final or pending capture. A service
  start's producer therefore has #125's atomic recorder and writes
  started_event_id on both service end paths. A reconciled old service start,
  deploy time, agent, iteration, amount or proximity is never producer proof.
* Pi is deliberately LIVE-only too: exact non-NULL llm_call_id and call kind,
  same instance, execution, parent and token source, with no duplicate start
  for that exact compound key. No claim is made about historical Pi emitters.
* A native WorkflowRun is terminal with a known completed_at at least15minutes
  old, and no workflow.started state contradicts it. completed_at is the native
  application's terminal clock, NOT DB/provider time. A terminal Event without
  a known terminal timestamp is UNKNOWN: leave the start unmarked, never fault.
  This conservative15minute delay is not proof that no late write is in flight.
* No exact end observation exists in final, pending OR native call-end Event
  leaves. Service links by started_event_id; Pi by the exact compound key above.
  Fork copies and malformed/non-string native identifier leaves are not ends.
* No pending record exists for the start Event itself: only #125's drain may
  move it. New marks are limited to the same current/previous-week window.

One unended revision is idempotent; Event locking serializes concurrent sweepers.
A late exact end requires a higher superseding start revision **removing**
call-unended, not a STOP/fault/ignored end. Existing marked starts remain eligible
for that correction even after the backfill window rolls past them; it is not
backfill of previously uncaptured history. NULL usage remains NULL. A typed start
cursor wraps each lap, so unknown/busy starts cannot permanently starve later
ones. No joining by time, iteration, agent, amount or model is permitted.

## Timing, storage and recovery

The original #126 bar is **batch ordering-lock HOLD p95<=50ms**, under four
concurrent live-writer transactions. It is not batch wall-clock duration and
not #125's separately approved100ms per-call lock-WAIT bar. Test instrumentation
samples the DB clock in a materialized CTE dependent on the real lock grant,
and the first DB clock after real COMMIT gives a conservative release upper
bound. Every exercised ordering acquisition in the batch and all four live
writers is sampled; report separate batch and combined p95/max. Both endpoints
use the same DB clock. No runtime instrumentation or
relaxed threshold is shipped; a miss returns to Temper lead.

Tables are additive and work with older code. Backup/restore must keep usage
instance/rows/pending and these diagnostic tables together under the existing
backup policy; restoring a partial set cannot establish coverage. No backup or
retention boundary is expanded. Rollback may stop new diagnostic writes, but
leaves numeric captures and the immutable internal cutover for diagnosis.

## Verification

Opening combined happy path then fixed clean/catch tests run on SQLite and the
isolated Postgres5455 schema tier; the same locked versions run the full gate.
Tests cover anti-join guards/races, fork/history/content boundaries, typed busy
rotation, completed empty/busy/fault/OFF attempts, normal-arrival age, readiness,
parked old executions, a full clean post-ready lap (not cursor exhaustion),
immutable cutover, live producer/terminal/link evidence, pending-aware unended
and late-end supersession, fault cap and always UNKNOWN coverage.
The initial stage proof covered92 cases per database tier; after repairing a
lexical test-audit false positive (SQLite `json_type` takes raw data as an
operand, not a projection), all93 distinct cases have green evidence per tier.
The added nonexecuted AST self-test rejects whole-data projections, labels,
casts, subqueries and opaque text while allowing fixed JSON leaves/type guards.
No runtime query was weakened to satisfy the test. A94th compatibility case
proves a maximal malformed start plus unended revision fits the existing256-byte
fault field. The legacy complete catalog (246bytes) remains accepted; the
extended lifecycle catalog (259bytes) is deliberately rejected if combined in
one row. The full pre-commit gate caught that old synthetic-catalog assumption;
its existing test is retained and expanded, never skipped or removed. No stored
field/CHECK or256-byte bound changes; no existing code is renamed or discarded.

The four-writer Postgres timing proof sampled100 batch grants: p95=3.011ms,
max=4.996ms. Writer sample counts were428/418/412/421; all1779 grants together
had p95=3.242ms, max=13.397ms. These are fixed-workload stage results, not a
latency or completeness promise. The required head gate still enforces50ms.

Every new guard needs its own mutation bite. Exact-head Architecture LAND TRUE,
exact-byte Security no-open-findings, all eight checks and deployed live checks
remain mandatory. Live verification is read-only counts/codes only: three ready
kinds, fresh completed heartbeat, pending falling or zero, progress, no burst.
