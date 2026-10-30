# Clarification loop: the M3 store

`temper_ai/clarifications/store.py` keeps clarification streams in temper's
database: one history per context and original brief, with a revision that only
moves by compare-and-set. Its tables are in `temper_ai/clarifications/models.py`.
It is unit M3 of plan #202 and builds on the frozen M0 contract
(`docs/clarifications/contract.md`) and the unchanged #308 foundation
(`configs/architecture/bin/context_profile_clarifications.py`).

**Not in use yet.** The tables are registered with temper's database, so landing
this creates them, empty. Nothing writes to them until M4 composes the loop and
the owner decides how real answers may be kept (D3: retention, readers, deletion,
export). Until then the store is tested with synthetic data only.

## What it keeps

Seven additive tables. No existing table changes.

| Table | One row per | Holds |
|---|---|---|
| `clarification_streams` | stream (`StreamKey`: namespace + brief digest) | the revision, the latest record's digest, the source authority, and counts of receipts, presentations, copies and consumptions |
| `clarification_revisions` | revision 1, 2, 3... of a stream | that revision's whole foundation record (canonical JSON), its digest, the previous revision's digest, and for an event revision the event and receipt it came from |
| `clarification_receipts` | action key (`ActionIdentity.key`) that was applied or retained | the exact canonical receipt JSON, its digest, and the result returned for it |
| `clarification_refusals` | refused receipt digest + code + guard | a diagnostic only: no text, no sender, never the action key |
| `clarification_presentations` | presentation | the persisted presentation; one generation per question is current |
| `clarification_copies` | delivered message of a presentation | the message IDs a receipt may bind to |
| `clarification_consumptions` | consumed (stream, revision, supplement) | the consumption identity, so a revision is consumed once |

Times are UTC. A revision with no consumption row is the pending consumption
intent: it was kept, and nothing has used it yet.

## Using it

```python
from temper_ai.clarifications.store import ClarificationStore

store = ClarificationStore(engine)                 # temper's engine; the foundation is loaded once
store.merge_candidate(caller)                      # RecordResult: create, or merge new questions into the LATEST record
store.save_presentation(presentation)              # True when new; generation g + 1 retires generation g
store.record_copy(binding)                         # True when new: the presentation was sent as this message
store.append_receipt(receipt)                      # AppendResult: applied, retained or refused
store.load(stream)                                 # StoredStream after a restart, or None if never created
store.supplement(stream, revision=n, original_brief=brief)     # compose; writes nothing
store.mark_consumed(stream, revision=n, original_brief=brief)  # True the first time only
```

Every method runs in one transaction per attempt and returns only after its
commit, or after deciding nothing needs writing. Refusals raise
`contracts.ContractRefusal` with a closed code and the guard that decided it,
except `append_receipt`, which returns a refused `AppendResult` for a receipt it
can read. Damaged history raises `ClarificationIntegrityError`. The foundation's
own refusals (`ClarificationError`) come back as `malformed` with guard
`store.candidate` or `store.foundation`.

The store opens no reference (candidate, authority and policy refs are kept as
text), signals nothing and resumes nothing. Keeping an answer authorises nothing
beyond keeping it.

## One append, step by step

`append_receipt` does all of this in one transaction:

1. **Replay first.** If the receipt's action key is already kept, the stream's
   history is checked and `check_replay` compares the bodies. Identical: the kept
   result comes back and nothing is written. Different: `changed_body`, refused,
   with a diagnostic; the history stays as it was.
2. **Load and check** the stream named by the binding and its whole history (see
   [Damaged history](#damaged-history)). No stream: refused `missing_record`
   (`store.stream`).
3. **Bind** to a persisted presentation and its delivered copies only. Unknown
   presentation: refused `binding_mismatch` (`store.presentation`). Then M0's
   `validate_receipt` decides provenance, responder, binding, generation,
   confirmation and text.
4. **Preconditions on kept state**, in this order: every correction
   (`check_correction_precondition`, presses carrying a correction included,
   Architecture N2), then every confirming press
   (`check_confirmation_precondition`), then every reopen
   (`check_reopen_precondition` on the current revision and active set). A
   correction may set aside only the same person's answers; another person's
   answer takes a reopen.
5. **Append to the latest record.** The foundation's `append_event` adds the one
   event to the latest record, never to an older copy.
6. **Compare-and-set and insert.** The stream row moves from revision N to N + 1
   only if it is still at N, then the revision row and the receipt row are
   inserted, and the transaction commits.

Results:

- **applied**: the event is revision N + 1, kept with its receipt in the same
  commit.
- **retained** (the six retained codes, such as a stale reopen or someone else's
  correction): the receipt is kept as evidence under its key; nothing applies.
  The decision is revision-checked too: the stream row is touched where its
  revision is still N.
- **refused**: only a diagnostic row (digest, code, guard). The key stays free, so
  a refused receipt from an unverified source never blocks the genuine one
  (Security #176 N1). A refusal changes no history and keeps no key, so it is not
  revision-checked: the next delivery of the same action is decided afresh.

## Concurrency

The revision compare-and-set is the guarantee, on SQLite and PostgreSQL alike;
nothing relies on a process-local lock.

- The compare-and-set is the transaction's first write, so the database orders
  writers: SQLite allows one writer at a time; PostgreSQL makes the second
  writer wait on the row lock and then re-checks `revision = N`.
- A writer whose compare-and-set finds the stream moved rolls back and decides
  again on the new latest record (`revision_conflict` inside the store, never
  returned). Nothing is ever written from a stale record: each revision row
  extends the row before it, which the history check enforces.
- Two people answering at once are both kept. Same text: the question is
  answered, with two attributions. Different text, or different dispositions:
  conflicting. The foundation's projection decides which; the store keeps both
  events.
- Two first creations race on the stream row's primary key; the loser merges its
  candidate onto the winner's record.
- A presentation saved after a decision was read makes that decision stale: after
  its compare-and-set, an append re-reads the question's current generation and
  decides again if it moved.
- The same key kept by another writer between the reads is answered as a replay.
- A unique-key clash that no other writer's commit explains is re-raised, never
  retried.

Each retry means another writer committed first, so the loop ends when writers
stop; there is no retry cap.

## Restart and consumption

- A crash before commit keeps nothing; the provider's next delivery applies the
  receipt once.
- A crash after commit keeps the revision; the next delivery gets the kept result.
- `load` returns `pending_revision` while the latest revision has no consumption
  row. `supplement` composes that revision's supplement and its consumption ID
  the same way every time; `mark_consumed` records it once. The store never
  resumes a run: the consumer decides, and the store records that it did.

## Damaged history

Every read checks the whole stream first. Anything missing, cut short or changed
raises `ClarificationIntegrityError(stream_id, guard, detail)`. It is never
answered with a fresh record, and nothing is written.

| Guard | Means |
|---|---|
| `stream.missing` | history rows remain but the stream row is gone |
| `history.ahead` | rows go past the stream row's revision or counts, and no writer explains it |
| `stream.identity` | the stream row's namespace or brief no longer gives its ID |
| `history.revisions` | a revision between 1 and the stream's revision is missing |
| `history.digest` | a revision's record does not match its digest |
| `history.chain` | a revision does not name the previous revision's digest |
| `history.json`, `history.record`, `history.brief` | a record is not canonical, not a valid foundation record, or for another brief |
| `history.first`, `history.record_step`, `history.event_step` | a revision is not exactly one record change or one event on the one before |
| `history.latest` | the stream row does not name the latest revision's record |
| `presentation.count`, `presentation.identity` | a presentation row is missing or changed |
| `copy.count`, `copy.identity` | a copy row is missing or names another presentation |
| `receipt.count`, `receipt.digest`, `receipt.sidecar`, `receipt.identity` | a receipt row is missing, changed, unreadable or under another key |
| `receipt.missing`, `receipt.event`, `receipt.applied` | an event revision and its applied receipt do not match one to one |
| `consumption.count`, `consumption.identity` | a consumption row is missing or changed |
| `consume.record` | a supplement names another record than the one kept |
| `store.event_added`, `stream.cas` | the foundation or the database did not do what the store asked |

Rows read just after another writer commits can look ahead of the stream row;
those are read again before they are called damage.

## Notes for the next units

- A ref holding a lone surrogate passes M0's `StreamKey` but has no UTF-8 form;
  computing its ID raises `UnicodeEncodeError`. The store refuses it as
  `malformed` (`store.utf8`). The fix belongs in M0's ref check, at its land step.
- Refused corrections leave evidence: a correction of another person's answer is
  retained with its receipt, and one naming an unknown answer is refused with a
  diagnostic (`correction.known`) (Architecture N3, Security N6).

## Tests

`tests/test_clarifications/test_store.py` starts with the combined happy path,
then #202's M3 cases, then one case per guard and retry branch, each with its
bite: the guard is removed from an in-memory copy of `store.py` and its case must
then fail. Every test runs on SQLite (a file, so connections really contend) and
on PostgreSQL where `TEMPER_TEST_DATABASE_URL` is set, in the worker's throwaway
schema. Concurrency tests use separate engines and a barrier at the
compare-and-set; crash tests kill a real child process just before or after its
commit.

```
env -u TEMPER_TEST_DATABASE_URL uv run --frozen pytest tests/test_clarifications/test_store.py -n 8
```
