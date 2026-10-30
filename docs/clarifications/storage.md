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
| `clarification_refusals` | refused receipt digest + code + guard | linkable diagnostics: integer row ID, receipt digest, **non-unique action-key digest**, stream ID, code, guard and time; no receipt JSON, answer text or sender column |
| `clarification_presentations` | presentation | the persisted presentation; one generation per question is current |
| `clarification_copies` | delivered message of a presentation | the message IDs a receipt may bind to |
| `clarification_consumptions` | consumed (stream, revision, supplement) | the consumption identity, so a revision is consumed once |

Times are UTC. A revision with no consumption row is the pending consumption
intent: it was kept, and no consumption acknowledgement has been recorded yet.
This is not proof that no downstream effect happened.

Applied and retained receipt JSON includes exact text/reason, callback data,
transport/bot/chat/action/update/sender IDs, responder policy/decision, binding
and copy IDs, correction targets, confirmation author/action/text digest, and
reopen snapshots. Revisions repeat whole foundation records, including question
metadata, applied answers and their actor/source refs. Corrections and reopens
preserve old evidence; they do not erase it. Authority and policy refs are opaque
text and can themselves contain identifying information.

Refusal identifiers remain linkable to known actions and contexts; a digest is
not an anonymity guarantee. The non-unique diagnostic action-key index is **not**
the primary key in `clarification_receipts`: it neither participates in replay
lookup nor prevents a genuine same-key receipt from being decided later. A
repeated identical refusal is deduplicated by receipt digest + code + guard.

The original brief is supplied when composing a supplement, not persisted as a
separate plaintext brief field. Candidate envelopes/refs/content digests and
caller affected-decision selections are not stored as such; selected question
metadata is. No TTL, purge, export, reader ACL, payload encryption or backup
erasure facility is implemented here. D3 must cover all these data categories,
including diagnostic links, repeated historical text and opaque refs.

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
4. **Preconditions on kept state**, after accepted or retention-eligible
   validation, never in place of an earlier provenance/binding refusal.
   `check_correction_precondition` comes first (presses carrying a correction
   included, Architecture N2), then `check_confirmation_precondition`, then
   `check_reopen_precondition` on the current revision and active set. For
   accepted validation the first failing precondition decides the outcome.
   For retained validation only an unknown correction target overrides the
   existing outcome: `missing_record / correction.known`, diagnostic-only.
   That includes no disposition, blank text and retired presentations. M0
   checks **all** target IDs for existence before checking actors, so an
   unknown plus another person's answer is refused in either order. Known
   targets preserve other retained outcomes. A correction may set aside only
   the same person's answers; another person's answer takes a reopen.
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
- **refused**: only the linkable diagnostic row inventoried above. The unique
  authoritative receipt key stays free, so a refused receipt from an unverified
  source or with an unknown correction target never blocks the genuine one
  (Security #176 N1). A refusal changes no foundation history or authoritative
  receipt and is not revision-checked: the next delivery is decided afresh.

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

Every stream read checks its authoritative history first. **Detected
inconsistencies**, not every possible change, raise
`ClarificationIntegrityError(stream_id, guard, detail)`. Such a failure is never
answered with a fresh record, and nothing is written.

DB writers and the application's store callers are trusted. Digests, links and
counts are unkeyed and kept beside the data: they check internal consistency,
not authenticity against a writer who can change those tables. A consistent
rewrite with updated dependent hashes/counts, complete removal of a stream's
authoritative/history rows, or restoration of a complete earlier valid snapshot
cannot be authenticated by these checks. Complete removal returns `None`, just
like a stream never created; refusal rows do not serve as an existence witness.
A valid rollback cannot prove which later receipts/effects once existed.

### Checked and unchecked fields

These are the read-time predicates, not a promise of comprehensive corruption
coverage. Shape checks and SQL constraints do not authenticate historical values.

| Table | Checked | Not independently checked/authenticated |
|---|---|---|
| `clarification_streams` | namespace + brief digest reproduce the stream ID; contiguous revision range and latest record digest; counts agree with associated rows | `source_authority_ref` and timestamps. Merges compare the authority label to the currently stored label, not an independent original. |
| `clarification_revisions` | record digest/canonical JSON/foundation validity/brief, previous digest, first-record rule, one-record-change or one-event step, applied receipt/action/event correspondence | timestamps; a consistent rewrite/rollback of records and dependent links has no independent witness |
| `clarification_receipts` | JSON digest, parsed M0 shape and result shape, action key, bound stream, verified-ingress label, non-refused status; every applied receipt corresponds to a revision whose event matches validation and receipt source digest | timestamps and `guard`; retained outcomes are not revalidated/recomputed on load. Result shape checks constrain status/code/event/revisions but do not establish the original decision; retained code/decision revision and a shape-valid applied result `event_id` are not independently compared to their original values. |
| `clarification_presentations` | count, reconstructed presentation identity covering binding/policy/transport/generation fields, namespace/brief match, known question and metadata digest | timestamps; no external proof of who actually presented it or of the policy ref's authority |
| `clarification_copies` | count and referenced presentation existence; applied events also need their receipt's copy ID still present | timestamps and unused `message_id` values. Replacing an unused numeric copy ID with another valid unused one is undetected; the replacement is then trusted as delivered. |
| `clarification_consumptions` | count, revision range, record digest for that revision, identity derived from stream/revision/supplement digest | timestamps, actual downstream effect/acknowledgement, and correctness of a consistently replaced supplement digest + identity; load does not recompose supplements |
| `clarification_refusals` | schema constraints only; not loaded into the authoritative history check | all diagnostic contents/identifiers/timestamps and deletion; no content integrity or anonymity promise |

In particular, changing a stream's authority ref or an unused copy ID needs no
hash-chain rewrite to escape these checks. The synthetic test
`test_unused_copy_and_authority_metadata_are_not_authenticated` pins that
limitation, rather than adding cryptography or silently expanding coverage.

### Failure guards

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
| `presentation.count`, `presentation.identity` | presentation count, reconstructed identity or question metadata does not match |
| `copy.count`, `copy.identity` | copy count disagrees, or a copy names a presentation not kept in this stream |
| `receipt.count`, `receipt.digest`, `receipt.sidecar`, `receipt.identity` | receipt count, JSON digest, shape, action/stream identity, verified-ingress label or stored status fails its check |
| `receipt.missing`, `receipt.event`, `receipt.applied` | an event revision and its applied receipt do not match one to one |
| `consumption.count`, `consumption.identity` | consumption count, revision range, record digest or derived identity fails its check |
| `consume.record` | a supplement names another record than the one kept |
| `store.event_added`, `stream.cas` | the foundation or the database did not do what the store asked |

Rows read just after another writer commits can look ahead of the stream row;
those are read again before they are called damage.

## Notes for the next units

- A ref holding a lone surrogate passes M0's `StreamKey` but has no UTF-8 form;
  computing its ID raises `UnicodeEncodeError`. The store refuses it as
  `malformed` (`store.utf8`). The fix belongs in M0's ref check, at its land step.
- Corrections leave evidence: known cross-actor corrections remain retained,
  unapplied; unknown targets are diagnostic-only before any authoritative
  retention (`correction.known`) (Architecture N3, Security N6). Earlier
  provenance/binding refusals remain earlier refusals.
- M0's S10 test-only follow-up remains at M0's eventual land step.
- M4 must enforce trusted ingress, responder decisions and namespace/read/write
  authority at the service boundary. A stored `provider_pull` label or knowledge
  of a digest/ID does not itself authenticate a human, grant read access or
  authorise resume. It must also keep provider delivery mapping and current-state
  send/continuation decisions correct; M2's repairs are separate.
- Consumption identity is available for downstream idempotency, not a proof of
  exactly-once external execution. M4 must handle effect/acknowledgement crash
  ordering. D3 must decide retention/readers/deletion/export/backup handling and
  trusted DB-writer scope before real answers; this repair chooses none of them.

## Tests

`tests/test_clarifications/test_store.py` starts with the combined happy path,
then #202's M3 cases, then one case per guard and retry branch, each with its
bite: the guard is removed from an in-memory copy of `store.py` and its case must
then fail. Every test runs on SQLite (a file, so connections really contend) and
on PostgreSQL where `TEMPER_TEST_DATABASE_URL` is set, in the worker's throwaway
schema. Concurrency tests use separate engines and a barrier at the
compare-and-set; crash tests kill a real child process just before or after its
commit. Combined correction-state regressions cover accepted, blank,
no-disposition, retired and confirming actions, mixed targets in both orders,
prior provenance/binding refusals, unchanged known-target outcomes and genuine
same-key recovery. Targeted in-memory mutations require the specific regression
assertion and then verify the wrong retained result; an unrelated exception is
not counted as that semantic bite.

```
env -u TEMPER_TEST_DATABASE_URL uv run --frozen pytest tests/test_clarifications/test_store.py -n 8
```
