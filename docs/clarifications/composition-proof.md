# Clarification composition: synthetic proof boundary

This document describes the M4 E assembled-library proof. It is not permission
to install, invoke or activate the library. Executed results belong in the
proof's evidence handoff, not in this document.
All results retain `meaning_status=NOT_EVALUATED`. No human, meaning, real delivery,
application execution, live store, migration or deployment proof is claimed.

## Source continuity

The integration carries the already reconciled M0/M1/M2/repaired-M3/A delta once,
then the received B, C and D deltas, onto current master. It does not replay old
snapshots over the shipped foundation, v2 checker, clarified checker or schemas.
Original component branches and review subjects remain unchanged. Original
component checks and source acceptance are inputs, not assembled acceptance.

| Input | Immutable delivered subject | Role in composition |
| --- | --- | --- |
| A | `d9a134be35eb794e55b29c5bed49be1069a5ad9f` | Canonical constructors, preparation adapter, shared ports and synthetic inputs |
| B | `ef964f57c031bfce0e1a66bf5738e9dade6a23b4` | Same-engine actual delivery, ingress, checked history and current consumption |
| C | `1bae0f1b03e7729342ad3b4a0529723f66f85ed2` | Explicit supplied-input coordinator and actual source-aware checking |
| D | `04398ae3985de2792ff2673d63affb2837eb3391` | Fixed V01–V20 case definitions, controls and sealed-case mapping |

E changes tests and this proof document only. Production defects discovered by
composition go to their accountable owner, not an unreviewed integration patch.

## Actual construction

`test_caller_integration.Composition` uses:

1. `ClarificationStore(engine)` with an isolated file SQLite database or isolated
   throwaway PostgreSQL schema, never the live or default engine.
2. `ClarificationDeliveryStore(store)` on that exact store instance.
3. `TelegramClarificationStore(store, delivery, authority=..., stream=...,
   source_authority_ref=..., responder_policy_ref=...)` with explicit synthetic
   caller-owned authority and responder policy. References grant no authority.
4. Real `ClarificationEdge` and ordinary `Poller.poll_once`, with only the provider
   network replaced. Typed text and confirmation enter through genuine synthetic
   provider pulls, not saved dicts or a manufactured provider receipt.
5. `ClarificationCoordinator` with the actual M1 adapter and shipped clarified/v1
   validator / source checker. It never generates or adopts a candidate.

The ordinary Telegram offset store is explicitly bound to the same isolated
engine. Restart disposes the engine and constructs a new store, edge, coordinator
and poller (V01 asserts each is a new object). Processes use separate engines,
barriers carried as named markers over anonymous OS pipes (no filesystem FIFO),
real commits and process termination; there is no fake persistence or shared
Python lock.

Direct receipt controls are labelled **trusted M0/M3 port**, not proof that M2
captured an action or that Telegram has a correction/reopen UI. The fake provider
and synthetic authority are test inputs, not a real delivery/reader grant.

## Ordered proof and case ownership

V01 is written first and combines preparation, durable presentation, exact typed
text, explicit same-actor confirmation, atomic ingress/result, restart, recovery,
source checking, explicit acknowledgement and replay. Independent reads before
send/callback effects assert the committed state and held offset. Reference
success leaves meaning unevaluated. A duplicate callback acknowledgement may be
sent; no new question/prompt, event, consumer work or run wake is implied. The
replay's bookkeeping is pinned exactly: the re-pulled typed update logs one new
ingress row carrying the saved retained result and moves the stream's
`ingress_count` by 1 and `state_version` by 2 (the lock touch and the ingress
write, kept because that transaction commits); the re-pulled press logs nothing
and rolls back. Whether a re-pulled retained update should log a new ingress
row is B/M2 semantics; this proof records what the composition does.

V01's four discriminating controls run on the actual composition: a flipped or
foreign event ID fails the reference check (V17, V18); a caller-built update
instead of the pulled object is refused as unverified ingress (V08); changed
original text fails the exact hash (V03); and suppressing the actual store's
application commit fails the named before-acknowledgement revision assertion,
not an arbitrary exception (`test_composed_guard_bites.py`). Two more bites
keep V01's own steps honest: skipping the restart fails "restart built new
parts", and a replay that never reaches the store (offset not rewound) fails
"replay re-delivered typed 1001 to the store".

V20 observes every counter D names. The composition counts provider reads
(`get_me`, `get_updates`) apart from its send/acknowledgement effects, its own
offset-store sessions and the default-engine getters, `TelegramClient`
constructions, notify/inbox registrations and outbound httpx requests.
`unused_import_constructor` requires all of them to be zero after constructing
the composition, an ordinary `Poller(clarifications=None)` and
`TelegramService(client=<synthetic>, clarifications=None)`, and after a fresh
interpreter (spies installed before any library module loads) imports the
whole library. A bite in which `ClarificationEdge` construction calls getMe and
getUpdates must fail that named V20 assertion.

What these zeros mean, and don't (Security's delta review, O5 and O6):

- The spies count a call and then make the real one. They detect contact; they
  don't prevent it.
- The zeros cover the patched paths only: sync httpx `Client.send`, the
  default-engine getters, `TelegramClient` construction, notify/inbox
  registration, `get_me` and `get_updates`. "Operationally off" is zero contact
  through these paths, not a global no-network proof.
- A failed fresh import reports only its exit code (Security F1). The test
  asserts on a plain integer, so pytest's explanation never carries the
  child's stdout or stderr into a CI log or JUnit file. A bite feeds a failed
  synthetic child with a canary in both streams and requires the canary to
  stay out of the failure text.

| Test module | Vectors |
| --- | --- |
| `test_caller_integration.py` | V01 combined flow |
| `test_composed_boundaries.py` | V02–V03 full checker/type/authority; V16–V18 metadata/reference/consumption; V20 default-off |
| `test_composed_transactions.py` | V04–V07 admission/copies/K1/K5; V11 cross-process histories; V14 crash cuts |
| `test_composed_ingress.py` | V08 captured membership/content and exact provenance refusals (wrong chat `transport_mismatch`, denied sender `responder_not_authorised`, bot sender `bot_sender`, forwarded `forwarded_message`: one refused ingress row, no routing, receipt or send); V19 capture versus final application/refusal |
| `test_composed_history.py` | V09–V10 exact text/replay; V12 correction ordering/privacy; V13 reopen/fences |
| `test_composed_damage.py` | V15 result/copy/send/history damage |

`test_composed_guard_bites.py` removes one guard at a time in memory, on the
actual stores, and requires the named assertion to fail: coordinator
consumption guards, the application commit before the callback
acknowledgement, the poll offset order, B's locked admission terms
(generation, answered) after a rival commit, the store's final generation and
confirmation fences after capture validation ran intact, and M2's pre-present
generation read, with the clean control that two distinct genuine answers to
one generation both apply.

The unchanged D catalogue maps these to T01–T17. Definitions are never counted
as executed tests. Executed node identities, dialects, pass/fail/skip statuses,
mutation assertions and source/gate/review applicability must be enumerated in
the final evidence handoff. A PostgreSQL job name is not actual PG coverage.
Changed stages qualify before V01/full composition; local/full exact-head checks
and independent actual-delta review remain separate evidence.

## Where the actual composition differs from a fixed vector

D's data is not edited to make a test pass. A fixed expectation the actual
components cannot produce is listed in `NOT_REALIZED`
(`test_composed_transactions.py`), reported as **not realized**, never as a
pass, and handed to Architecture's review.

| Vector case | D expects | Actual composition |
| --- | --- | --- |
| V07 `generation_before_present` | `stale_coordinator_refusal: true` | No coordinator refusal, with a caller snapshot from before generation 2 or after it: saving a known presentation ID is a store touch that keeps the revision and record digest, which are all the coordinator checks. M2's pre-present generation check answers it first: exactly one `not_current`, no provider send, no attempt, no row change. B's locked `start_attempt` eligibility is the second fence: with M2's read stale, the result is `delivered` or `pending`, never a send. D's `edge_state: not_current` and `sends: 0` hold. |

C's own recording-port test simulates a stale-presentation store refusal that
the real store never raises for a known ID. M2 is the only source of
`not_current`, and E's M2 bite proves that report; E's admission bites, which
call the edge's send directly, prove B's generation and answered terms; and the
M2 bite's mutant arm asserts no extra send.

Two boundaries are covered elsewhere, not by a composed bite here. V11's
cross-process histories have no single-guard composed bite; they rest on M3's
retry-branch bites and B's lock bite, and the composed losing path is B's
lock-then-refresh. V11's `first_create` stops both processes after each has seen
the missing stream, then releases the profile-only child first and waits for
it, so the other child's first-create insert is the one that loses and merges
its extra question (revisions 1 then 2, as D fixes them). Released together,
either may win; when the wider candidate wins, the narrower one's merge is a
no-op at revision 1, with the question union intact. V08's `wrong_bot` pulls through another bot's own edge; the
older construction, a reply on our own bot whose quoted author is another bot,
is not exercised here and binds by design, because the quoted author is not a
binding input (Security's E review, finding 4).

## Retained limits and later work

- Every returned completion ID must survive, including reversed overlapping
  sends. Representative `message_id` is not the copy membership set.
- DB admission cannot make network delivery exactly-once. A crash can lose a
  delivery ID. Ordinary retry does not send again; explicit verified reconciliation
  or resend is caller work, not automatic recovery.
- K1: an unknown reply copy falls through to ordinary behavior, which can have
  effects. Only a fresh genuine pull after explicitly verified reconciliation can
  become clarification ingress. A saved ordinary dict is not authenticated input.
- K5: after admission, a send may complete while the state changes. Final
  application checks under the transaction retain stale/duplicate actions rather
  than trusting earlier capture acceptance. Distinct genuine answers remain valid.
- Diagnostic-only refusal keeps no answer text or authoritative action key;
  genuine same-key recovery remains possible. Known other-actor evidence can be
  retained without application. Scoped readers must not expose foreign bodies.
- Unkeyed hashes/counts do not authenticate coherent privileged rewrite, whole
  rollback or erasure. Linkable references are not anonymization.
- B registers the real tables on the same engine. `create_all` is not a migration;
  neither table creation nor old-schema handling is admitted by this source proof.
- Explicit consumption is only a durable acknowledgement of supplied source
  consumption. No consumer/network effect is atomic with it and no automatic
  application, resume, wake or poller/engine registration is provided.
- D3 readers/retention/TTL/deletion/export/encryption/backup erasure, real K1
  policy, live source/responder authority, M0 UTF-8/S10 carry-forwards, actual
  invocation, migration/land and activation remain separate. Existing holds and
  excluded historical work are not revived.
