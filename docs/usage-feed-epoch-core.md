# Inert usage-feed epoch core

## H-EPOCH2 — written before implementation

Accountable lead: Temper. This additive core consumes the reviewed #125 FINAL /
source-instance schema at `ae05bc7b` and the accepted reader/reset paper SHA256
`4b727b3f91821fbd1744697d48b4d9ea42e83d1ced2238d4adb13d69306dd18f`.
Paper agreement and normal task approval are not operational permission.

**Problem/evidence.** The source already has immutable random source-instance
identity and ordered FINAL rows plus separate pending records. It has no epoch
phases, private live PostgreSQL identity, pre-snapshot read/reset fence or typed
ROW/TARGET codec. Picking the greatest READY would incorrectly serve through a
newer incomplete transition. Taking an advisory SELECT after a repeatable-read
snapshot cannot repair that stale snapshot. A sequence object's high-water is
not an actual row and cannot be progress or the cutover target.

**One change.** Add a single, inert epoch core with append-only `(epoch, phase)`
PREPARED/READY storage, exact matching operation metadata, fresh owned
transactions locking the same table BEFORE any snapshot-taking SELECT, minimum
primary/live identity scalars, and separate private ROW/TARGET codecs validated
against actual FINAL tuples. No source-writer change, host journal/operator,
HTTP route, timer, credential, collector control or live initialization.

**Expected result/measurement.** A combined fixed-fixture happy path proves
matching phases, a real fixed target, a last-returned-row cursor, source/live
identity and read-only selection. Fixed catches cover newest PREPARED suppressing
old READY, mixed metadata, mutation, denied/nonprimary identity, domain/shape and
anchor errors, null/empty separation, source/epoch mismatch and private identity
canaries. Throwaway PostgreSQL tier (5455) proves conflicting locks in BOTH
orders, lock-before-snapshot and bounded timeout; SQLite explicitly refuses
reset-safe operations. Each guard has a named negative case. Exact-head expert
reviews and the normal full gate remain required.

**Refutation.** Any old-READY fallback, mixed-operation READY, application
UPDATE/DELETE, premature snapshot, nonconflicting host lock, fabricated/high-water
anchor, TARGET accepted as ROW, private identity leak, SQLite parity claim or
live epoch/key write is a miss. Evidence of real-anchor existence is not
issuance, receipt, consumption, complete-prefix or universal tamper proof.

**Stage result: HIT (bounded fixtures only).** SQLite codec/refusal stage:
132 passed. First throwaway-PG stage: 131 passed, one fixture miss; its assumed
default denial of `pg_control_system()` was false on this test cluster. The
corrected doubtful test passed alone after H-EPOCH2a/b below, including actual
non-superuser success and actual permission denial. The other fixed cases were
unchanged. Full normal gate and exact-head review are separate release duties,
not an activation claim. Failed fixture attempts remain recorded, not passes. Source compatibility is additive only: old tables and their contents stay
unchanged; a different pre-existing epoch schema requires an explicit,
source-owner-approved migration, never destructive loss-as-initialization.

### H-EPOCH2a — denied-identity fixture correction (before change)

Evidence: the minimum non-superuser reader could already execute the required
control scalar through this test cluster's default privileges, so expecting a
denial without arranging one failed. One change: arrange a real permission
denial inside a throwaway-PG transaction (PUBLIC revoke + SET LOCAL ROLE), then
explicitly roll it back; do not commit a shared catalog privilege change or add
a shadow function. Expect fixed identity-unreadable on denial, then successful
non-superuser minimum-grant reading. Measure this doubtful test alone before a
whole gate. Refuted if the denied probe succeeds, the clean role requires broad
privileges, or the test leaves a catalog permission change. Result: denied
probe HIT; the clean role assertion found a second fixture defect.

### H-EPOCH2b — actually retain the reader role (before change)

Evidence: after the denial was fixed, the explicit `rolsuper=false` assertion
caught the new engine still running as its test owner. SQLAlchemy initialization
rolled back the connect callback's uncommitted SET ROLE. One change: commit that
session setting before initialization, keeping the production engine untouched.
Expect the same clean assertion to prove a real nonsuperuser reader and deny
host locking; refuted if it still runs as owner or needs broad privileges.
Result: HIT — corrected doubtful minimum-reader test passed on throwaway PG;
denied identity refused, real `rolsuper=false` reader succeeded with table SELECT
and scalar EXECUTE only, and reader-to-host ACCESS EXCLUSIVE was refused. No
committed denial/global privilege change. The earlier failed clean proof is not
counted as a pass.

### H-EPOCH2c — independently observable guard coverage (before change)

Evidence: Architecture #166 returned NO VERDICT, not land clearance. Its two
272-case controls passed, but 18 of 64 individually executed guard removals
survived; 26 further removals were unrun after the review's wrong-test-URL
authentication refusal. The initial per-guard proof is therefore a MISS even
though the bounded functional fixtures passed. Overlapping database constraints,
trigger layers, timeouts and public cursor constructors masked individual checks;
the SQLite mutation fixture never reached UPDATE or DELETE after INSERT refused.

One change: strengthen only the owned fixtures and this explanation, retaining
all production guards. Use direct host-marker SQL for unmasked DB policies,
installed catalog assertions for intentionally overlapping constraints/triggers,
controlled row seeding for unsupported SQLite mutation checks, exact independent
local timing settings and a controlled in-context clock, and codec-layer probes
before redundant outer validation. Add fixed cases for the remaining defensive
source/phase/anchor checks rather than infer their proof from green controls.

Expect every named M1/M2/M3 removal to fail its own focused selection, with
unchanged clean SQLite and throwaway-PG stages. Instrumented codec policy tests
measure the promised early checks; they do not establish a malformed-token
exploit when later checks also refuse. Refuted by any survivor, another guard
masking a case, a changed production guard, or a test requiring live DB access.
Result: HIT for these bounded corrections — clean controls309 each on SQLite
and throwaway PostgreSQL (169 core/codec plus140 unchanged writer cases);
all18 previously surviving named removals now fail their focused selections.
M1: D09/D12/D14/D15/D16/D17/D19/D20b; M2: F07/F08/F09b/F10/F13;
M3: C05/C10/C12/C14/C17. Each mutation ran alone and source was restored
exactly. Catalog/policy instrumentation is explicitly not an exploit proof.
This does not claim independent clearance of all90 guards: the26 initially
unrun review cases and the full renewed campaign remain Architecture's duty.
Renewed exact-head Architecture/Security and full gate required; the previous
NO VERDICT/coverage miss is not converted into a pass.

### H-EPOCH2d — reach the SQLite refusal without trigger-dependent seeding (before change)

Evidence: the renewed independent controls passed309 each and all90 guards
executed, but only89 were valid catches. D20 removed all SQLite creation-trigger
registrations: both populated UPDATE/DELETE cases stopped at the seed's
`scalar_one()` with `NoResultFound`, before either intended write. That is an
unproved fixture failure, not a caught policy removal or a production escape.
The18 old survivors and26 old unrun guards are independently caught in their
bounded modes; their historical proof and last26 restoration-custody limitation
are not silently upgraded by this correction.

One change: extend only the existing application-INSERT test's SQLite branch
with a direct, fully valid synthetic PREPARED insert and an exact
`usage-epoch-unsupported` refusal. Check zero rows before and after; do not
query/drop a trigger, seed a row or accept a broad exception. Retain every
production guard, the PG branch and D20b's populated UPDATE/DELETE path.

Expected measurement: the final clean SQLite and isolated-PG stages pass. The
single D20 registration removal must make this exact INSERT assertion fail
with `DID NOT RAISE`, with no setup/seed/collection error, followed by exact
source restoration. Refuted if INSERT remains rejected by another guard, the
mutation cannot reach INSERT, any permanent production byte changes, or live
access is needed.

Result: hit in the bounded implementation check, not yet independent clearance.
Final control stages pass309/309 on SQLite and actual isolated PostgreSQL
(12.77s/68.72s; zero failures/errors/skips). Their JUnit-artifact option produces
16 compatibility warnings in addition to the two inherited marker warnings;
no extra test retry or result substitution is used. Removing only all SQLite
trigger registrations makes the exact INSERT test fail with
`DID NOT RAISE <class 'sqlalchemy.exc.IntegrityError'>` at its refusal assertion,
with no seed, collection or setup error (one failure/0.20s). Source then restored:
no production/session/codec/writer diff and original SHA256 values match. The
separate populated UPDATE/DELETE checks remain unchanged; this INSERT result is
not claimed as a new UPDATE/DELETE removal proof or a rerun of the other89.
Renewed exact-head review/adoption, current Security, all8 normal checks and
off-only land/deploy receipts remain separate. No prior NO VERDICT is clearance;
no epoch/init/key/host/route is activated.

## Storage and ownership

`usage_feed_epochs` has composite primary key `(epoch, phase)` and a separate
unique `(transition_id, phase)`. Closed phases are PREPARED/READY. Operation
metadata comprises epoch, canonical transition/source UUID, private system id /
database oid / current WAL timeline, fixed identity basis, actor, reason and a
fixed FINAL target tuple (or all-null EMPTY). `created_at` is each phase's DB
clock timestamp, not a source occurrence time; it is intentionally not matching
operation metadata. PostgreSQL's insert trigger overwrites caller timestamps.

The PostgreSQL trigger rejects UPDATE/DELETE (including no-row statements),
application INSERT without the explicit host-transaction marker, reused/stale
PREPARED allocation, orphan/superseded/mixed READY and invalid metadata. Python
host helpers revalidate source, live identity, newest issued epoch and target.
PREPARED and READY are separate commits; helpers do not infer a receipt, create
history, allocate from DB alone, reserve a burned epoch or silently reset.
`append_ready_epoch` requires the caller to have durably reconciled the matching
host receipt; the database cannot attest an outside-mount future append.

The transaction-local host marker prevents accidental application use, not a
hostile same-UID/DB-owner caller forging it. SELECT-only readers have no INSERT,
UPDATE, DELETE or host-lock privilege. No roles/grants are created in production.
DB superuser/owner, whole-volume restore, DROP/TRUNCATE and same-UID modification
are residuals. These are not cryptographic or OS isolation guarantees.

Registration is an epoch-only import in `DatabaseManager.create_all_tables`.
Normal additive `create_all` creates the new table and its creation-time guards,
without changing the three #125 tables or their stored rows. It does not replace
an existing table, upgrade an incompatible epoch schema or repair missing
triggers. A source owner must explicitly plan such a migration; the protocol
must not operate against an unreviewed pre-existing schema. A missing table
fails unavailable; an empty compatible table is reader-uninitialized, not proof
of virgin state or permission to initialize. No import/startup helper writes an
epoch. SQLite creates only the additive schema; all core fence/phase operations
are fixed `epoch-unsupported`, and its epoch INSERT is rejected. No SQLite
primary/identity/timeline/fence equivalence is claimed.

## Private identity and fresh fence contract

`probe_primary_identity` first checks `pg_is_in_recovery()`, then selects only
`pg_control_system().system_identifier`, current database oid, and the eight
hexadecimal timeline digits from `pg_walfile_name(pg_current_wal_lsn())`. No
checkpoint timeline, statistics/query text, SELECT-star, control file, privilege
escalation or fallback. Denial/unreadable/nonprimary are fixed refusals. Values
stay in private epoch/host plumbing; representations/errors/logs/tokens contain
no identity scalars. Mismatch diagnostics are field names only: system,
database, timeline. PostgreSQL deployments must separately authorize only the
required scalar EXECUTE/SELECT privileges. The test's temporary reader role is
in throwaway PostgreSQL, not a production grant or permission receipt.

Use `reader_epoch_snapshot(engine, deadline=absolute_monotonic_deadline)`:

1. A NEW owned transaction, READ ONLY REPEATABLE READ; raw/already-used
   Connections are not admitted through the public helper.
2. SET local bounds, then ACCESS SHARE on `usage_feed_epochs`, before ANY data
   SELECT (including source/identity/max/progress).
3. `read_current_ready_epoch` takes the greatest epoch across **all** phases;
   both phases must match. Newer PREPARED never falls back to older READY.
4. Validate row/target anchors and buffer results while retaining the fence.
5. Context exit re-probes primary/live identity and checks the deadline. Only a
   successful transaction completion permits its caller to release a response.

`host_epoch_transaction` instead acquires ACCESS EXCLUSIVE on the SAME table
BEFORE any SELECT. EXCLUSIVE alone is forbidden: it does not conflict with the
reader's ACCESS SHARE. It admits only explicitly authorized host append calls;
prior synced reservation, host mutex/custody, durable Ops quiescence and feed
OFF belong to the future host protocol, not this core.

Each helper caps lock/statement timeout at two seconds and its own deadline at
three seconds (and rejects an already-expired request). It also sets an idle
transaction bound and closes/rolls back on exceptions. The future route still
owns total request admission, connection-pool wait, serialization, cancellation,
response authorization and fixed HTTP errors/Retry-After; a synchronous DB
helper alone cannot promise a complete three-second HTTP handler. Buffering and
not releasing on context/commit failure are mandatory consumer duties. Expected
conflicts must be caught and buffered **inside** the fenced scope: final primary /
live identity may override buffered success or conflict. An exception thrown
through the context yield aborts and skips the success-only re-probe; it cannot
be serialized outside the fence as an identity-authorized conflict. #128 needs
its own exception/conflict precedence and complete-handler deadline tests. A final
identity check is not protection against out-of-band volume replacement or
unannounced same-identity restore. No page-to-page held fence/snapshot.

## Private ROW, TARGET and real anchors

Private format version 1 uses separate `r1.` and `t1.` domains, canonical unpadded
base64url and a closed binary layout: version byte, 16 source UUID bytes, uint64
epoch, uint64 FINAL seq, uint32 native revision, byte event-id length, and exact
ASCII event id. Bounds match reviewed FINAL storage: positive signed-BIGINT
seq/epoch, nonnegative PostgreSQL INTEGER revision and 1..128 native-id bytes.
Entire token is at most 256 ASCII characters. Unknown domain/version,
noncanonical encoding, padding, trailing bytes, malformed ids or out-of-bounds
values are fixed `usage-cursor-invalid`. No I, MAC, public seq, external DTO,
new secret or historical resolver is introduced.

`capture_final_target` selects the **actual highest FINAL row tuple** in the
PREPARED snapshot, or EMPTY. Never pending, sequence `last_value`/`nextval` or a
moving maximum. `validate_fixed_target` validates that retained real tuple;
`validate_target_cursor` additionally requires this exact authorized target,
including explicit null only for EMPTY. Later FINAL rows do not move T. A ROW
cursor validates source/epoch, visible max and the exact real tuple; seq beyond
visible max is seq-regression, missing/changed tuple is anchor-changed. A
TARGET is rejected in ROW domain even when it contains the same tuple.

`InitializedNoProgress` is a separate typed no-anchor position, not a seq-zero
cursor. Missing DB epoch, authorized EMPTY target and initialized null progress
are three different states. Token existence is **not** issuance, client receipt,
consumption, complete-prefix, per-client history or universal corruption proof.
A feed principal can manufacture a cursor for another real row within its
whole-feed authority. Ops retains exact opaque G + native W + atomic Q/evidence,
never a private seq; the host copies these and separately captures NEW T. No
old-G resolver is needed or supplied.

## Consumer limits and stage evidence

Host protocol (#139 / PHOST) consumes these interfaces only after its own normal
implementation/reviews and prior authorization. Route (#128) consumes fresh
read-only fence/current READY/identity/anchor checks, and alone binds generated
ROW to the last actually returned DTO row. It must validate retained T every
page, keep target and G separate, preserve exact G on empty replay and implement
accepted error precedence. It never calls host append. Neither consumer may
infer admission, initialized state, restore approval or release from a READY.

Fixed tests are `tests/test_observability/test_usage_feed_epochs.py` and
`tests/test_observability/test_usage_feed_cursor.py`. Combined happy paths lead;
negative cases exercise phases/metadata/source/identity/null/real tuple/encoding
bounds, application mutation and minimum read privileges. Actual throwaway PG
lock tests cover reader-first and reset-first waits/timeouts, statement ordering
and real newest-phase observation. Mutation bites plant max-READY fallback,
EXCLUSIVE instead of ACCESS EXCLUSIVE, and a forbidden early-snapshot statement
trace; each reuses its clean assertion and must fail. The latter is an ordering
assertion, not a claim of simulating every restore interleaving. No model, HTTP,
collector, operator journal or whole workflow proof is part of these tests.

Guard-to-case mapping: greatest-any-phase -> newer-PREPARED/bite; exact metadata
-> phase-field fixtures + DB raw insert; append-only/host-only -> direct and host
UPDATE/DELETE + application INSERT + reader write; primary/identity/bounds ->
nonprimary, actual denied role/minimum grant, scalar fixtures and final re-probe
rollback; source/observed-max/epoch -> mismatch and stale-max fixtures; fence ->
closed/unadmitted/expired + both lock orders and planted lock/order faults;
ROW/TARGET/real anchors -> cross-domain, wrong source/epoch/tuple, missing and
changed FINAL, high-water/pending/moving-max and null/empty cases; wire ->
version/alphabet/length/binary shape/canonical bits/trailing bytes/range cases.
All performance, native source findings, host/Q/generation/recovery, route/auth,
full gate, exact-head reviews, off-only deployment and later activation gates
remain independent; none is waived by green core fixtures.
