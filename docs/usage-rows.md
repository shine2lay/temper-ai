# Native call observations (write path)

The usage tables are content-free observations in the same Temper database as
`events`. They are **not priced, allocated or complete historical cost**. This
change adds no reader, background drainer, consumer, price table or backfill.
Old retained events have no observations until separately approved reconciliation.

## Three additive tables

`usage_source_instance` has one permitted key (`id = 1`) and a random UUID4
`instance`. Startup inserts once with `ON CONFLICT DO NOTHING` and reads the
winner. The value is never derived from a host, path, time, model or container,
never cached before commit, and survives deploy, restart and rollback. Server
and workers on one database use the same instance. A restored database retains
it; this is not proof that two live copies are one source or that a restore lost
no observations.

`usage_call_rows` is append-only. Its columns are:

| Columns | Meaning |
| --- | --- |
| `seq` | Database-assigned final-row commit order; permanent gaps allowed |
| `event_id`, `revision` | Unique native observation identity; initial revision 0 |
| `instance` | UUID4 from this database's singleton |
| `execution_id`, `parent_id` | Native run and parent-agent references only |
| `event_type` | `llm.call.started`, `llm.call.completed`, `llm.call.failed` |
| `call_kind` | Native `model`, `compaction`, or NULL |
| `llm_call_id`, `started_event_id` | Native call reference and exactly proved start reference |
| `provider`, `model` | Bounded native identifier labels, or NULL plus a fault |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | Stored native counts, unchanged |
| `cache_read_tokens`, `cache_write_tokens` | Native `cached_prompt_tokens` / `cache_write_tokens`, unchanged |
| `token_source` | `pi` exactly when `executed_by == "pi"`, otherwise `service` |
| `legacy_cost_usd`, `legacy_cost_source` | Stored finite nonnegative float, `pi_estimate` / `service`, or NULL |
| `lost_attempts` | Native list length only, or NULL; never its contents |
| `event_at` | Source Event's own timestamp, normalized to UTC |
| `occurred_at`, `occurrence_basis` | Event construction time labelled `call_end`, or start self-reference labelled `call_start`; NOT provider timing proof |
| `origin` | `live` here; `reconciled` reserved for approved later work |
| `fault_codes` | Sorted closed codes, comma-separated, at most 256 characters |

`usage_pending` has exactly the same typed projection **except `seq`**, plus
`pending_at` (queue-capture time, diagnostic only) and `defer_reason` (the closed
code `ordering-lock-timeout`). Its primary key is `(event_id, revision)`. No JSON,
Event payload, exception or arbitrary text is queued. A pending observation is
not yet in the final feed, not a missing zero and not proof of a distinct call.

## Strict extraction

Never store `Event.data`, prompts, outputs, reasoning, tool data, error text,
names, paths, task/project/initiative/root, payer or scope in any usage table.
Extraction visits named numeric/reference keys only: it does not walk, hash,
serialize or stringify unknown fields. Faults never echo rejected values.

Producer references are ASCII `[A-Za-z0-9._:-]{1,128}`. An invalid required event
id refuses the transaction with a fixed message; malformed optional references
become NULL with `id-invalid`. Provider/model labels must fully match
`[A-Za-z0-9._:/@+-]{1,128}` AND pass the declared native-label shape policy:
reject slash-root, `./` / `../` roots, drive-root, scheme followed by `:/`
(including `://`), and colon-before-`@` userinfo-like shapes. A rejected value
becomes NULL plus `provider-invalid` / `model-invalid`, never truncated, hashed,
echoed or copied to a diagnostic. Slugs, qualified slash identifiers, colon
aliases and non-userinfo `@` revisions remain supported. These syntax checks
are not proof that an arbitrary configured ASCII label is public/non-secret,
and are not an export-safe/DLP or declassification certificate.

Token counts must be real Python integers in `0 .. 2**53 - 1`. Booleans, fractions,
floats (even integer-valued), negatives, NaN, infinity, oversized values and other
types become NULL with a field-specific fault. Missing values remain NULL. No
count is clamped or inferred. Legacy cost is neither recomputed nor repriced;
an invalid/nonfinite value becomes NULL with `cost-invalid`.

Closed faults: `prompt-invalid`, `completion-invalid`, `total-invalid`,
`cache-read-invalid`, `cache-write-invalid`, `provider-invalid`,
`provider-unproven`, `model-invalid`, `model-unproven`, `kind-invalid`,
`id-invalid`, `cost-invalid`, `lost-invalid`, `link-unproven`, `usage-missing`,
`ordering-deferred`. The last code is durable operational evidence: it survives
a drain in the existing final `fault_codes` field. It does not mean token usage
is invalid or establish a price. No fourth table/diagnostic payload or seven-day
logging assumption is needed. Even the full union fits256 characters; arbitrary
codes are refused.

## Atomic capture, sometimes deferred final visibility

`recorder.record()` uses its existing `_db_write_with_retry` session. A new call
Event and **either its final row or its typed pending observation** commit in
that same outer transaction. Neither commits alone. If extraction or pending
persistence fails, the Event rolls back too. This is deliberately an atomic
*capture* guarantee, not a promise that the final row is always immediately
visible beside the Event.

The event id remains stable across retries. An acknowledgement lost after commit
and a Pi stream replay cannot duplicate the Event or observation. Replay keeps
the original values; corrections go through `update_event()`.

Before the ordering lock the writer flushes the Event, ensures the instance,
resolves the exact start, and prepares all values and the cached statement.
The indexed lookup searches **both numeric stores in one SQL statement and
snapshot** (UNION ALL, latest revision), not Event content. A concurrent atomic
pending-to-final drain cannot hide a continuously present start between two
lookups or cause selection of its older revision. This adds no new lock or
isolation setting. Service calls link by `started_event_id`; Pi calls by
`llm_call_id`. Instance, execution,
parent, token source and call kind must match. Unproved links become NULL with
`link-unproven`. Pi compaction never inherits another call's labels.

The service adds only `started_event_id` to completed/failed event data.
Provider inheritance uses the exactly linked start: `_call_llm()` records that
start immediately before invoking; `_record_llm_started()` reads
`self.provider.provider_name`; `_invoke_provider()` invokes that same
`self.provider.stream()` / `self.provider.complete()`. A fallback is selected
only after failure and before the next start. Explicitly malformed provider
input is never repaired by inheritance. Model stays native.

On Postgres all ORM work is flushed before a raw usage-only SAVEPOINT. The
savepoint/INSERT/conflict window disables ORM autoflush and refuses any
new/dirty/deleted state immediately after SAVEPOINT: a raw rollback must never
undo an ORM flush behind its unit of work. One settings round trip **after**
SAVEPOINT sets local `lock_timeout = 2s` and
`idle_in_transaction_session_timeout = 5s`. Both previous settings are restored
by a timeout rollback. A recorder frozen after INSERT but before COMMIT loses
its idle connection within the bound; the whole transaction rolls back and its
normal stable-id retry remains safe. An active COMMIT/storage stall is not
bounded by idle timeout. `statement_timeout` must be0 or greater than2s; a
stricter value fails closed, never automatically weakened. Schema tests reject
DEFERRABLE constraints/commit-time triggers on Event and usage tables.

The ordering statement follows. One cached, parameterized Core statement takes the fixed
`pg_advisory_xact_lock(0x54454D5055534147)` in a MATERIALIZED CTE, **then** inserts
and allocates the default BIGSERIAL seq. The lock CTE supplies the INSERT's input
row, so the number is evaluated after the lock. On a successful normal append,
the caller commits immediately: no RELEASE SAVEPOINT, ORM refresh, logging or
additional SQL runs between INSERT and COMMIT. Duplicate/conflict handling below
has an explicit existing-row check before commit; its statement is prepared
before the lock. Durable commit and isolation are not weakened.

Only SQLSTATE `55P03` from that usage-ordering statement triggers deferral: roll
back the SAVEPOINT, preserving the outer Event, then persist the typed pending
observation. It is not a generic exception catch. A failure before this narrow
ordering statement or during pending persistence still aborts the Event.
`57014`, `40P01`, unique violations and all other errors propagate and roll back;
only `orig.pgcode == '55P03'` from that one statement defers. This
guard addresses a frozen ordering holder, not arbitrary database/network failure,
Event row locks, unavailable storage or a universal two-second transaction limit.

A deterministic drain helper moves **one** immutable pending observation per
caller-owned transaction. It locks the source Event id without reading its
payload (`FOR UPDATE SKIP LOCKED` on Postgres), then atomically appends the final
row and deletes pending in one lock-dependent DELETE/INSERT CTE under the
same ordering lock. All paths acquire Event locks first, ordering lock last.
`drain_pending_row()` returns `drained`, `already-final`, `deferred`, `busy` or
`missing`; only `drained` counts a new observation. No RETURNING seq after an
ON CONFLICT is not success by itself: compare the existing final projection.
Equal permits an already-final commit; different/missing rolls back the root
transaction and preserves pending with a fixed fault. Skipping a busy correction
or a held ordering statement never counts as drained. It never rereads raw Event data to reconstruct the projection,
relinks it or reinterprets its native numbers. A crash rolls back both changes;
an unknown-commit retry is safe. A held ordering lock leaves pending durable,
not falsely cleared. No scheduler or background worker is enabled here: the
approved downstream reconciler must own invocation and prove the agreed
15-minute **normal-operation** cadence before accounting activation. A held
or failed downstream component is not falsely reported within that tolerance.

## Commit order, revisions and forks

The final-row lock lasts until commit/rollback. While final row N is uncommitted,
a later writer cannot allocate and commit N+1. A reader can advance past a
committed seq without a lower seq committing later. Rollback/conflict gaps are
final: readers never wait for them. A deferred older Event receives its final
seq when drained, so its arrival is later; `event_at` is not ordered by seq.
Sequence is visibility order, NOT occurrence or revision chronology: a drained
start can follow its own end, and revision0 can follow revision2. Exact links
use only native `llm_call_id`/`event_id`, never seq/time adjacency. Consumers must
keep the highest native revision as a restatement, not overwrite it with the
last arriving older revision or add both charges.
Neither application timestamps nor uuid4 ids are cursors. SQLite serializes
writers itself; a process mutex also protects its shared in-memory connection.
An unseen rolled-back SQLite rowid may be reused; a committed cursor is not.

`update_event()` locks the source Event, compares only the pure allowlisted
projection, and allocates the next revision across **both** stores. Numeric
changes append, never overwrite. Status/content-only changes add nothing. An
unknown-commit retry sees the merged Event and adds no duplicate revision.
Legacy/fork Events with no observation stay unprojected; this is not backfill.
A correction is a restatement of a native fact, never an extra additive charge.

`copy_events_for_fork()` is unchanged and writes zero observations. Extraction
also excludes `restored_from_fork`. Real new calls in the fork have new rows.
Pi replay uses stable event ids; a new ordinal records the new attempt.

## No coverage or billing claim

Pi defaults/zeros are native observations, not known free usage. Failed service
calls have NULL usage unless the Event stored counts; reported Pi failure usage
is retained. Service inclusive/cache and Pi classes are not converted here.
`legacy_cost_usd` has no proven rate/price basis. No rate, allocation or budget
rule changes.

Occurrence coverage remains **UNKNOWN**. Event time precedes pool waits, retries
and possible late stream delivery; old-time revisions can arrive later still.
Neither newest Event time, seq advancement, queue age nor a transaction frontier
proves complete occurrence-time coverage. Later adapters must report partial
at-least lower bounds/faults rather than invent complete weekly totals or budget
headroom. Native decreases remain faithful restatements; no UI high-water rule
may suppress the correction. Manual spending authority remains unchanged.

Pending row counts, oldest pending age and latest-record-seen are diagnostics,
not distinct-call counts or complete-through timestamps. They do not expand a
closed external contract. A change to posting-time accounting is separate.

## Lifetime, restore and rollback

All three tables use `create_all_tables()`. The additive change rewrites no old
Event or observation. Rolling code back leaves the tables, pending observations
and singleton intact; reinstalling resumes that identity. It neither drains
pending during rollback nor claims the older writer captures new events.

The existing nightly live database dump includes all three tables with Events.
Trim only blanks prompt/setup fields; it deletes neither Events nor observations.
**A future Event-deletion path must delete matching final AND pending observations
in the same transaction.** No deletion/retention change is introduced here.

An external reader still needs private current database-identity/anchor checks,
blocked handling for missing/corrupt state, and an explicitly recorded lead-only
restore/rebaseline procedure. No reader, app, timer or model may silently reset
its checkpoint or rotate the source UUID. A full retained baseline must deduplicate
stable native fact identities and fail on same-id/different-content conflicts;
restores must not erase already known spending. Those reader/security tests
belong to the separate reader/consumer before activation, not this write path.

## Fixed-input proof and hypothesis

`tests/test_observability/test_usage_rows.py` belongs to the existing Postgres
tier (`tests/pgtier.py`, test port5455), also runs on SQLite, and starts with the
combined normal/Pi happy path. Existing rollback/retry/replay/fork/instance/
malformed-value/canary/link/compaction/revision/commit-order proofs and guard
mutations remain. Added cases cover bounded ordering deferral, Event+pending
atomicity, pending revisions and start links, unknown commit, drain rollback/
idempotency and content exclusion. Real Postgres cases are counted (not skipped):
3s session-lock holder with capture<2.5s, restored settings/usable transaction,
frozen-recorder disconnect/retry, drain with held lock/locked correction,
equal/different conflict, non-55P03 failures, stricter statement timeout and
known-bad deferred constraint. SQLite tests its actual path, not fabricated PG
behavior. Mutation cases remove each critical new guard and must fail its check.
No model, provider or workflow is called.

Test Postgres uses schemas per worker, while advisory locks are database-wide.
This test module substitutes one stable test key per schema, preserving all
locking semantics and preventing intentional3–5s fault injections from blocking
other workers/runs. Production still uses the single fixed key above.

The normal gate checks correctness with4000 concurrent events, not a machine-load
latency assertion. Performance runs separately with `TEMPER_USAGE_FIXED_LOAD=1`,
only `test_eight_writers_500_events_lock_wait_p95`, pinned by
`taskset -c 0-4,10-14`:8 writers×500 events plus8 CPU-bound children, **two trials**,
each actual server ordering-wait p95<=100ms. Each must have4000 final rows,
4000 timing samples, no hidden pending fallback and no missing/duplicate event.
Admit10 CPU slots, not just one pytest worker. SQLite also proves history>1000.

Test-only profiling adds timestamp CTEs/RETURNING clocks in memory; it preserves
all production transaction boundaries and returns the original seq. It separates
server lock wait, accounted held-time segments and the actual DBAPI COMMIT call;
it does not pretend a cross-clock estimate is a server interval or that COMMIT
proves WAL alone. No timing columns are persisted. Correctness uses the original
production statement. A diagnostic is explicitly ineligible for a hypothesis hit.

The original50ms hypothesis and its narrow locked-path revision both missed;
their evidence remains recorded, not relabelled as a pass. The approved new
hypothesis adds bounded numeric deferral and adopts an explicit100ms stress budget.
A fallback in any week (its durable marker remains) or a measured daily
production p95>100ms warrants lead review of a B proposal, never automatic B
implementation or activation. This change adds no production p95 collector.
Any content leak, missing atomic capture, skipped/duplicate fact, unbounded
ordering-holder deferral, drain loss or either failed timing trial is a MISS.
Stop, record it and write a new hypothesis before changing the approach; never
retry unchanged code to fish for a pass. Exact results/reviewed heads remain in
the private task record. The full gate, exact-head Architecture/Security review,
automatic deployment/live checks and look-only numeric verification are still
required; a changed head reopens review.
