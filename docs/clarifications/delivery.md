# Durable clarification delivery and ingress (M4 B)

**Source library, not an enabled route.** This extends the existing M3 store on
its supplied engine. No caller, workflow, poller, provider, service or migration
is installed. Synthetic author tests are not independent review, a human receipt,
a real-data retention decision (D3), or release approval. Original M0/foundation
contracts and historical `mark_consumed` semantics remain unchanged.

## Components and complete protocol

- `clarifications/store.py`: existing sessions, revision CAS, canonical digests,
  checked history and the one append implementation. Adds `protocol_view`,
  `append_receipt_with_ingress` and `mark_current_consumed`.
- `clarifications/delivery_models.py`: three additive SQLModel tables and
  `IngressAppendResult(result, guard, held, new)`; no second receipt history.
- `clarifications/delivery_store.py`: send/delivery and ingress transactions in
  that same persistence component. No provider calls, process-local mutex or
  generic inbox.
- `integrations/telegram/clarification_store.py`: `TelegramClarificationStore`
  implements **all eleven** M2 methods: `save_send`, `start_attempt`,
  `record_delivery`, `delivery`, `copies`, `current_generation`, `question_ids`,
  `answered`, `receipt`, `keep_receipt`, `keep_refusal`.

Construction needs the existing `ClarificationStore`, a
`ClarificationDeliveryStore` wrapping that exact store, and explicit `authority`,
`stream`, `source_authority_ref`, `responder_policy_ref`. It performs no I/O and
creates no permission. Each adapter lookup requires read authority; mutations
require write, and send/admission/reconciliation also require send authority.
The source reference must match the stored stream. Presentation operations
check the responder policy and stream, including when M2 calls them directly.
The supplied enforcement port raises on denial. References are not credentials.
Unbound storage APIs remain trusted Python primitives, not a sandbox: callers
must not use them to bypass their application's authorization.

`protocol_view(stream)` uses the common integrity loader and exposes checked
questions, applied-answer projection, all historical presentations/copies and
exact authoritative receipts. It neither treats delivery as an answer nor
restricts lookup to the currently displayed generation. Original `load` still
returns its original current-only presentation/copy snapshot.

## Transactions and uncertainty

A saved send is immutable canonical intent plus digest. A prompt binds the exact
kept typed action, author, text digest, presentation, reply-to and payload pairs.
`start_attempt(send_id, expected_attempts=..., resend=...)` returns the committed
`(SendRecord, won)`. Only the winner may send. In one database transaction it
checks the count, absence of **any** delivery mapping, explicit resend when the
count is nonzero, current generation and current answer eligibility. These
checks apply to questions, prompts and retries. A loser rolls back the
provisional stream touch and changes no durable row; it may truthfully still
be pending. Current generation/questions explain why it was not sent.

The lock order is stream first, send second: the existing CAS takes the stream
write lock, the history is refreshed under that lock, then the send changes.
All related writes use the same order. SQLite uses its actual writer ordering;
PostgreSQL uses its actual row lock. No transaction spans a network call.

An attempt committed before a process dies remains uncertain. An ordinary
retry does not send again. Explicit resend may overlap the first in-flight
attempt; **network and database are not atomic or exactly-once**. A generation
or answer may change after admission and before delivery (K5). Every eventual
completion is kept; application checks current state again.

`record_delivery` atomically adds the supplied ID, its unique transport/bot/chat
mapping and existing presentation-copy binding. Reverse completion order keeps
every ID, including old generations and prompts. The representative message ID
is only one member, never the membership set. Exact duplicate completion is a
no-write replay; a conflicting mapping is refused. Checked state/digests/counts
run before lookup, admission or reconciliation, including after restart.

**K1 remains a real-application decision.** An unknown message ID falls through
M2 to the ordinary route, which may execute ordinary behavior; it is not promised
to do nothing. Explicit trusted reconciliation can call `record_delivery` with
verified supplied evidence and authority. This library does not obtain that
evidence, search chat history, guess mappings, resend, or say a human checked.
A saved ordinary update is not authenticated by replaying its dict: after mapping,
a new genuine provider pull/redelivery or a new reply must enter M2. No real
fallback/reconciliation policy is chosen here.

## Receipt, ingress, refusal and offset

`append_receipt_with_ingress(ingress, receipt, validation)` reuses the **same**
append decision as `append_receipt`, but commits its result and non-body pull
linkage together. A stream lock covers the latest-state decision, including
refusal. Capture-time validation is recorded as evidence, not executed as a
command. Provenance/binding refusal precedes the existing correction →
confirmation-once → reopen checks. Unknown correction targets are diagnostic
only even for blank/no-disposition/retired evidence; known cross-actor evidence
remains retained. Distinct genuine answers both survive CAS and may conflict.

Applied/retained outcomes return the exact held receipt and whether it was new.
An authoritative replay returns its immutable result/guard; changed body produces
a diagnostic, never replacement text or key reservation. Refused outcomes have
`held=None`. The bound adapter raises M2's new `ReceiptApplicationRefusal` **only
after** that diagnostic plus ingress commits. M2 catches only that subtype,
reuses idempotent refusal handling, and says “Not applied.” Unexpected exceptions,
ordinary `ContractRefusal`, policy denial and storage outage still propagate and
hold the poll offset. This typed bridge is new review scope, not covered by old
M2 acceptance.

The action key is global, but the adapter's authority is not. Scoped ingress
checks only the key's ownership columns before replay: a foreign owner produces
`CROSS_CONTEXT` / `replay.stream` in the **bound** stream. It never loads that
foreign receipt's text or history, including when the competing append happens
after the adapter's first scope check. The trusted unscoped legacy append API
keeps its original replay semantics. Ingress views reject missing result links,
foreign result-stream/transport/update bindings and mismatched diagnostic links,
even when a corrupted row's individual digest was recomputed.

A commit precedes prompt sends, callback acknowledgement and offset advance.
“Received.” acknowledges receipt, not requirement adoption or successful
application: a capture-accepted action can be retained after a race. M2's counters
are capture-level; the durable result is the application outcome. A repeated
observation with the same full linkage is a no-write replay; another pull offset
may add a non-body observation, never another authoritative event/receipt.

## Current consumption acknowledgement

`mark_current_consumed(stream, revision=..., record_sha256=...,
consumption_id=..., original_brief=...)` composes the existing consumption
identity and checks the supplied originals/digests. An integrity-checked exact
saved acknowledgement returns `False`, even after the stream moves. Otherwise
it checks that revision is current under the same stream lock, then reuses the
existing consumption row and commit helper. A new stale acknowledgement raises
`revision_conflict` without a durable write. `True` records a new acknowledgement;
it does not execute downstream work, wake a run or prove an external effect.
Historical `mark_consumed` remains supported and can acknowledge an older revision.

## Additive data inventory and compatibility

All tables use the **same engine** and are explicitly registered by
`database/session.py`. SQLModel `create_all` is not a migration. Fresh synthetic
schemas include the new columns; existing pre-extension schemas must be
recreated for tests, not silently backfilled. Old operations coexist on the
new schema and may keep legacy copies with no send mapping. Never infer a
verified delivery from such a copy, or bless missing integrity hashes. A future
real-data migration/land admission must explicitly handle table creation and
required columns; this source task makes neither decision.

| Location | Additional stored data and integrity |
|---|---|
| `clarification_streams` | `send_count`, `delivery_count`, `ingress_count`; `state_version` advances on CAS touches, including non-revision attempt/representative changes. Counts detect partial loss; the version fences multi-SELECT snapshots. Loss/duplicate rollbacks keep all of these unchanged. |
| `clarification_sends` | Unique send ID, stream/presentation, canonical intent JSON/digest, `attempt_count` (exposed as M2 `SendRecord.attempts`, not workflow run-generation attempts), representative ID, state digest, created time. Intent includes display/prompt text, full presentation (policy/bot/chat), reply-to, exact payload/disposition pairs and confirmed action/author/text digest. |
| `clarification_deliveries` | Unique transport/bot/chat/message tuple, stream/send/presentation links, canonical digest and time. Every mapping is checked against the exact saved intent and copy. Many IDs per send. |
| `clarification_ingresses` | Digest identity, stream, transport/bot/update ID, update digest, pull offset, receipt/action-key digests, capture status/code/guard, exact `AppendResult` fields/guard or diagnostic row identity/code/guard, time. No raw update or receipt/answer JSON. The action-key index is **non-unique** and cannot occupy the authoritative receipt key. |

M3's seven tables and their text/history inventory remain as described in
[storage.md](storage.md). Refused/unconstructible intake has no authoritative
text row. Refusals without a receipt have no receipt/action-key link. Diagnostic
links, opaque refs, prompt text, reply-to, callback metadata, IDs and digests are
linkable data, **not anonymity**. New ingress integrity binds authoritative
results or exact diagnostics, not merely a payload hash. Unkeyed checks detect
inconsistent loss/substitution, not a trusted writer's coherent rewrite, whole
rollback or complete erasure. Existing source-authority metadata limitations
remain; no signature/key service is added.

No retention/TTL, deletion/export, reader ACL, encryption, backup erasure or
real storage grant is implemented. D3 must inventory these additions explicitly.
Tests use isolated real SQLite/PostgreSQL connections and child processes,
synthetic provider/authority, crash cuts and guard mutations. Author results,
independent reviews and future live/operator proof are separate evidence.
