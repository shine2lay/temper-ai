# Inert usage-feed host protocol

## H-HOST2 — written before implementation

Accountable lead Temper. Accepted paper SHA256
`4b727b3f91821fbd1744697d48b4d9ea42e83d1ced2238d4adb13d69306dd18f`;
delivered epoch core `4878890d`. Normal PHOST plan approval/application is
HOME-attested by the #131 closing receipt; it is not operational consent.

**Problem/evidence.** The delivered core fences PostgreSQL and appends exact
PREPARED/READY phases, but cannot attest host durability, reserve across a
restored DB and host history, or make READY equivalent to host completion.
The accepted paper C10–C18/C20/C39 requires a durable source-scoped operator
mutex, burned INTENT reservations, explicit split recovery and settled opaque
G/public W/native Q handoff without resolving historical G.

**One change.** Add an inert, explicit privileged host protocol: closed bounded
linked/checksummed history with complete writes, file synchronization and
creation-parent synchronization; source-bound cross-process custody;
both-history allocation; separate INTENT/PREPARED-RECEIPT/COMPLETE and express
abandonment; exact-operation recovery. A required future control verifier
validates actual authority, OFF, settled durable quiescence and native Q. This
repository supplies its contract and synthetic fixtures, NOT a production Ops
adapter. The command refuses operation until that prerequisite is delivered.
No default path is opened, and no import/startup/route/timer invokes the code.

**Expected measurement.** Finish code and docs before running the journal and
transition stages once on fixed temporary files and throwaway PostgreSQL (5455).
The opening combined case is H7/D6→8 with G/W/Q distinct from NEW T. Additional
known cases cover null/no-progress, EMPTY T, restored-empty, every commit split,
unknown acknowledgements, corrupt/torn/missing evidence, synchronization failures,
exact operation/receipt/authority mismatch, serialized operators and restart
remaining OFF. Guard removals must fail their named assertions; a setup error is
not a bite. No live journal/header/key is read or written; no external restore,
model, provider, workflow or second Temper is used.

**Refutation.** Epoch reuse, DB-only allocation, READY before synced matching
receipt, automatic release, inferred virgin state, truncated repair, target as
consumed evidence, decoded/resolved old G, an unchecked generation/Q, mixed
operation reconciliation or a SQLite reset-safety claim is a MISS. Tests do not
prove universal restore/corruption detection or hostile-admin resistance.

**Stage result: HIT (bounded inert fixtures only).** Journal+protocol+SQLite
refusal stage98 passed; independent throwaway-PG protocol stage64 passed. The
journal stage has34 cases; the protocol stage has64, including four real-PG
cases (combined H7/D6→8, two unknown-commit phases, restored-empty/actual-target).
The SQLite equivalents of those four cases prove fixed refusal, not PG parity.
Source Ruff and strict mypy checks passed. No functional failed attempt was
converted into a pass. Exact-head Architecture/Security, all eight normal checks,
detached land, automatic temper-ci deploy and look-only OFF checks remain pending.

### H-HOST2-R1 — exact saved COMPLETE receipt

**Problem/evidence.** Security's first review was explicitly incomplete, not a
clearance. Static review found that existing COMPLETE acknowledgement checked
READY's operation but did not compare the full readback phase with the saved
COMPLETE READY, so a changed canonical READY timestamp could go unnoticed.

**One change.** Compare the full actual and saved `DatabasePhase`, including
`created_at`, before acknowledging an existing COMPLETE. No phase, authority,
receipt schema or operational prerequisite changes.

**Expected measurement.** An isolated clean replay stays closed with no append
or DB write. Changing ONLY actual READY timestamp must refuse
`epoch-history-diverged`, preserving host bytes and DB phases. Bypassing phase
equality must make that same refusal assertion fail, proving the guard's bite.
Touched protocol stages and the normal full gate run on the corrected source;
both exact-head expert agreements reopen. No live state is involved.

**Refutation.** A changed timestamp accepted, a clean replay refused, a data write
or release, or a planted-removal failure caused by setup rather than this check.
**Stage result: HIT (bounded inert fixtures only).** Corrected protocol stage66
passed on synthetic/SQLite-refusal inputs and independent throwaway-PG stage66
passed; both include the isolated clean/catch and planted-removal case. Ruff and
strict module mypy passed. The earlier stages did not cover this gap; no green
test result is renewed Security clearance. Full corrected-head gate and both
exact-head reviews remain pending.

## Ownership and operational boundary

The paper's header, atomic G/W/Q/evidence transaction, generation/admission gate,
registered-work settlement and restart-closed control are FUTURE Ops deliverables.
The types below are implementation contracts for fixtures and later integration,
not a claim those APIs exist. Runtime operation needs actual implemented APIs,
source-bound proof, separate normal operational authorization and matching
receipts. Key custody remains Temper; raw loading/rotation timing remains Ops.
COMPLETE never installs collector state, re-adds credentials or releases work.

Host history remains outside mounts/backups at the separately proposed protected
host location. No provisioning, path creation in that location, key, env, route,
collector store, grant, schema migration or live epoch write belongs to this task.
SQLite has no proved equivalent and is fixed `epoch-unsupported`.

## Typed contracts and fixed limits

`HostEpochProtocol(journal, PostgresEpochStore(engine), controls)` exposes only
`start(authorization, handoff)`, `reconcile(authorization, handoff)` and
`abandon(authorization, handoff)`. It is not wired into startup, a route, a timer
or a workflow. `scripts/usage_feed_epoch.py --describe` prints fixed availability
facts; every other argument returns fixed `epoch-operation-prerequisites-missing`
without reading configuration/environment or constructing a database/journal.
There is no operational command to switch on accidentally.

All received dictionaries have exact keys (unknown and missing keys refuse),
canonical UUIDs, strict integer/boolean domains and bounded values. Private
identity, native state and journal objects suppress data-bearing repr. Errors
are fixed codes, not payload/path/driver text. The journal contains PRIVATE host
identity and evidence references; it is not a public DTO, telemetry or collector
interface. It must never be mounted in the server or copied into its backups.

* `HostAuthorization`: `transition_id`, `source_instance`, `logical_reader_id`,
  `action` (`begin/reconcile/abandon`), `reason` (`activation/restore/migration`),
  `plan_ref`, `consent_ref`, exact `expected_head{sequence,checksum}`,
  `actor=authorized-host`, exact `paper_sha256`. Digests/reference strings are
  NOT authority by themselves. A real external authority service must verify
  their operation-specific meaning; this implementation supplies no such service.
* `ClosedHandoff`: `header`, `off_ref`, `quiescence_ref`, exact `header_digest`,
  `server_admission=OFF`, `registered_work=0`. The external control verifier must
  prove these current facts and the canonical approved journal location under
  custody, not merely accept these literal fields.
* `QuiescentHeader`: `state_version=1`, `logical_reader_id`,
  `principal=usage-collector`, `source_instance`, `mode=QUIESCENT`, old `epoch`,
  old `transition_id`, positive `generation`, `progress`, exact opaque `g`, public
  `w`, native `q`, separate old `target`, boolean `reached`, retained `prior_refs`.
  A consumed state needs G+W+Q/evidence; an initialized no-progress state needs
  explicit G=null/W=null/Q.witness=null, not an absent Q/header. Q names the
  authoritative atomic native transaction (`transaction_id`, `evidence_refs`,
  `witness`). W contains only instance/event_id/revision, NEVER seq. The retained
  old COMPLETE checksum must be included in `prior_refs`, and the installed old
  target must match that operation's host receipt. Real storage/atomic linkage
  and generation settlement still require the missing Ops APIs and proof.
* `VirginAdmission`: exact closed fields `state_version=1`, logical reader,
  principal, source, `mode=VIRGIN-ADMITTED`, positive generation,
  `admission_ref`, `prior_issuance=none-attested`. It must be independently
  recorded/authorized for that source AND reader. Empty files, missing headers,
  missing epochs and UUID/key changes never satisfy this admission.
* `RequiredHostControls.verify(authorization, handoff, journal_path)` is a
  FUTURE integration protocol, not a claim a current Ops method exists. It must
  authenticate exact authority/head/source/path, server admission withdrawal and
  settled handlers; prove durable QUIESCENT generation with all registered work
  settled; prove the exact settled logical header and authoritative Q/evidence
  atomic links; and remain closed on restart. Every boundary re-verifies it.
  The adapter is mandatory, has no default success and is not implemented here.

The approved host directory must already exist, be canonical (no symlink alias),
owned by the operator, mode0700. Journal and fixed adjacent `.lock` must be regular
single-link owner files mode0600, opened no-follow/close-on-exec. All supported
operators for one source must use that ONE approved path/lock inode; alternate
copies/paths do not form a mutex. Path custody is explicitly part of the missing
external verifier. Flock acquisition uses a bounded default2s (hard max3s), not
an unbounded blocking operator. This is not hostile same-UID/root isolation.

Journal v1 is canonical ASCII JSONL, linked by sequence+previous SHA256 and a
checksum over ALL envelope/body fields. First record is explicit ADMISSION;
INTENT, PREPARED-RECEIPT, COMPLETE or ABANDONED follow a closed semantic grammar.
Limits: 64KiB per record, 4MiB per history, 4096 records; native retained-reference
lists max64; DB snapshot max8192 phase rows. Exceeding any limit blocks rather
than trimming. Exhausted histories need a separately designed/approved custody
continuation, NOT automatic compaction/rotation or increased limits.

Creation exclusively creates owner files, synchronizes the file AND its existing
parent directory. Before using a retained exact-head history the authorized
invocation explicitly resynchronizes validated bytes and parent. Append loops
until the WHOLE canonical record is written and then fsyncs the file; O_APPEND
alone is not durability. Short writes, zero writes, file/parent sync failure,
torn suffix, bad order/checksum/semantic record, missing initialized history and
changed inode/head all block. A write/sync failure poisons that session. No
truncation, normalization, repair, silent retry, inferred virgin or partial
prefix acceptance exists. A later exact-head approved recovery may synchronize
an intact fully validated record whose earlier acknowledgement was unknown;
it cannot repair torn/corrupt bytes. Valid-suffix deletion with all independent
pins/evidence also rolled back is NOT universally detectable.

## Ordered transition and recovery

Under the single source mutex and verified OFF/settled quiescence:

1. Take a fresh core host transaction: ACCESS EXCLUSIVE BEFORE any SELECT/RR
   snapshot. Read ALL DB phases, source and live private primary identity;
   compare the live identity again. Read/validate the retained host history.
2. Reserve `E = 1 + max(DB-any-phase, host-reserved-or-issued)`. Write and sync
   INTENT with immutable source/logical-reader/transition/reason/authority,
   exact old header/G/W/Q/generation, both maxima, whole DB-history digest and
   old/new private identity. INTENT burns E even if the DB never changes.
3. In a fresh pre-snapshot exclusive transaction, revalidate the original DB
   basis and append PREPARED using the core's ACTUAL FINAL row query (or explicit
   EMPTY). Never use a sequence high-water. Commit/ack uncertainty stops here.
4. Exact fenced readback checks transition/E/source/new-I/reason/target and the
   actual fixed target. Append+sync matching PREPARED-RECEIPT, including the
   database timestamp and separate typed TARGET token. Old G is copied, never
   decoded/resolved or replaced with T. New T is not consumed evidence.
5. Only with that synced exact host receipt, revalidate under a fresh exclusive
   transaction and append matching READY. A newer PREPARED suppresses old READY.
6. Exact fenced READY readback and another control check precede append+sync
   COMPLETE. The returned outcome ALWAYS says OFF/QUIESCENT/NOT-AUTHORIZED.
   No install, re-add, release, collector DB access or auto-resume follows.

Recovery is an explicit separately authorized action naming the SAME immutable
transition and exact current host-head pin. It re-verifies the original settled
handoff/control/evidence and both histories under custody. Known absent PREPARED
may be retried only against its exact original DB-history digest/max/identity.
Existing exact PREPARED is reused, never relabelled or retargeted. READY without
a matching host receipt blocks; a matching READY without COMPLETE needs exact
readback and a synced COMPLETE. Existing COMPLETE can be acknowledged only after
exact DB/target readback, full saved READY phase equality (including timestamp)
and explicit resynchronization; it is never release.

| Observed split | Supported exact-authority action; everything stays OFF |
|---|---|
| INTENT only; confirmed DB absence | Reconcile the original immutable operation; or explicitly ABANDON the reserved E. |
| DB PREPARED, no host receipt | Exact fenced target/metadata readback, then synced receipt, then READY. |
| Synced host receipt, no READY | Revalidate exact PREPARED/receipt/target and append matching READY. |
| READY, no COMPLETE / unknown ack | Exact matching both-history readback, sync COMPLETE; no service enable. |
| Complete host E7, retained older DB E6/empty | Initialized restore authority, retained native Q and both histories reserve E8; never init/E1. |
| Different source/I/transition/target, newer DB phase, missing Q or unsettled generation | Refuse; no guessed rollback, mixed operation, baseline, or automatic fix. |
| Missing/torn/corrupt host bytes | Preserve and BLOCK; separately approved retained-history reconciliation is outside this implementation. |

ABANDON supports conclusively absent DB operation or its exact PREPARED without
READY (including an already retained matching receipt). It records the observed
phase/history digest and retains ALL DB phases/host evidence. READY/COMPLETE
cannot be abandoned here. A DISTINCT operation must receive new authority and a
strictly higher reservation. No abandonment resets either history or repairs
identity loss; more complicated cases stay blocked for a separate approved plan.

## Fixed test plan and scope of proof

Opening whole-protocol fixture: retained host7/DB6→8, real old G/public W/native Q
separate from new target, exact receipts and restart acknowledgement while OFF.
The same combined path runs through actual throwaway-PG transactions. Journal
stage uses only synthetic temporary files; protocol stage models the missing Ops
controls explicitly. The PG stage uses the project's protected throwaway tier,
not another Temper or live DB. Retained-older/empty fixtures adjust ONLY that
throwaway schema under fixture-only trigger control; no external restore occurs.

Finite catches cover C10–C18/C20/C39, each write/commit acknowledgement boundary,
actual file-sync uncertainty, file/parent creation failures, incomplete/torn/mixed
receipts, explicit absent/PREPARED abandonment, no-progress/EMPTY, missing W/Q,
stale generations, real evidence unavailability, wrong source/header/authority,
wrong live I/target, restored-empty, full DB-basis mismatch, cross-process mutex,
operator stale-pin races, all configured bounds and CLI refusal. Named guard-bite
checks plant removals in bounded test contexts; a setup failure is not a catch.
These are inert known-answer implementation proofs, NOT actual Ops durability,
restart, operational readiness, provider/native-truth or universal tamper proof.

## Later operation and release prerequisites

Before ANY operational invocation: approved host path provision/custody proof;
actual Ops authoritative atomic G/W/Q/header transaction API; durable generation,
registered-work settlement and restart-closed controls; real source-bound OFF and
settled handlers receipts; actual authorization verifier with current head pins;
matching complete source/runtime Architecture/Security receipts; and a separately
normally approved operational plan/consent. These are not satisfied by this task,
a paper agreement, a constructed type or a test fixture.

After a separately authorized real transition, collector install/full baseline,
credential add/re-add and release each keep their own authority/receipt gates.
T0/T1 and source activation remain unadmitted until their own required proofs.
No collector-store/key/raw-loader/route/schema/config/provisioning/grant edits or
live journal/header/key/epoch reads/writes are performed by this delivery.
