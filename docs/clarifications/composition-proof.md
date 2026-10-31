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
and poller. Processes use separate engines, named pipe barriers, real commits and
process termination; there is no fake persistence or shared Python lock.

Direct receipt controls are labelled **trusted M0/M3 port**, not proof that M2
captured an action or that Telegram has a correction/reopen UI. The fake provider
and synthetic authority are test inputs, not a real delivery/reader grant.

## Ordered proof and case ownership

V01 is written first and combines preparation, durable presentation, exact typed
text, explicit same-actor confirmation, atomic ingress/result, restart, recovery,
source checking, explicit acknowledgement and replay. Independent reads before
send/callback effects assert the committed state and held offset. Reference
success leaves meaning unevaluated. A duplicate callback acknowledgement may be
sent; no new question/prompt, event, consumer work or run wake is implied.

V01's four discriminating controls run on the actual composition: a flipped or
foreign event ID fails the reference check (V17, V18); a caller-built update
instead of the pulled object is refused as unverified ingress (V08); changed
original text fails the exact hash (V03); and suppressing the actual store's
application commit fails the named before-acknowledgement revision assertion,
not an arbitrary exception (`test_composed_guard_bites.py`).

| Test module | Vectors |
| --- | --- |
| `test_caller_integration.py` | V01 combined flow |
| `test_composed_boundaries.py` | V02–V03 full checker/type/authority; V16–V18 metadata/reference/consumption; V20 default-off |
| `test_composed_transactions.py` | V04–V07 admission/copies/K1/K5; V11 cross-process histories; V14 crash cuts |
| `test_composed_ingress.py` | V08 captured membership/content; V19 capture versus final application/refusal |
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
| V07 `generation_before_present` | `stale_coordinator_refusal: true` | No coordinator refusal, with a caller snapshot from before generation 2 or after it: saving a known presentation ID is a store touch that keeps the revision and record digest, which are all the coordinator checks. M2 alone fences it: exactly one `not_current`, no provider send, no attempt, no row change. D's `edge_state: not_current` and `sends: 0` hold. |

C's own recording-port test simulates a stale-presentation store refusal that
the real store never raises for a known ID; for this case M2 is the single
fence, and a bite on its generation read proves it.

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
