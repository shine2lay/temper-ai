# Clarification composition: integration vectors and boundaries

This document accompanies `tests/test_clarifications/composition_vectors.py`.
It delivers **source fixtures**, not an executed clarification loop. All V01–V20
have `execution_status="NOT_RUN"`; all meaning results remain
`meaning_status="NOT_EVALUATED"`. Writing/importing a vector, passing source gates,
or reviewing a component does not change those statuses.

## What exists, what is declared, what still needs execution

| Surface | Status at the vector source base | Integration responsibility |
| --- | --- | --- |
| `composition_scenarios.composition_profile`, `inputs`, `clarified_candidate`, `clarified_validator`, `SyntheticTelegram`, `SyntheticResponderPolicy` | Delivered A constructors | Reuse these; no alternate complete-profile/checker/provider/store implementation. |
| Canonical `CallerInput`, `Presentation`, `ActionReceipt` and identity functions in `temper_ai.clarifications.contracts` | Actual M0 API | Exact types and hashes; opaque references are not opened or treated as grants. |
| `preparation_adapter.prepare` / `compose_supplement` | Delivered exact-type bridge to real M1 | Reconstruct M1-local exact types without changing fields, weakening checks or copying validation. |
| `caller_contracts` | Delivered ports and snapshots, **not implementations** | `CoordinatorStore` reuses actual M3 result types. Its `mark_current_consumed` declaration does not implement a transaction. |
| M3 `ClarificationStore.merge_candidate`, `save_presentation`, `record_copy`, `append_receipt`, `load`, `supplement`, `mark_consumed` | Actual repaired component API | Reuse real isolated engine/transactions and checked loaders. Existing historical `mark_consumed` is not current-only acknowledgement. |
| M2 `ClarificationEdge`, `PulledBatch.claim`, `PulledIngress`, `SendIntent`, `SendRecord`, `SendResult`, injected store protocol | Actual component API | Provider/policy may be synthetic. Its existing test `FakeStore` is **not** durable integration proof. |
| `context_profile_clarified_check.check_clarified_profile(profile, original_brief, record, validator)` | Actual shipped reference checker | Supply A's loader of the actual clarified/v1 schema. Reference success is never meaning acceptance. |
| `ClarificationCoordinator` in `caller.py` | C-owned implementation, not imported by these vectors | Prepare/present/recover/check/acknowledge. E must consume C's actual delivered version, not infer availability from this document. |
| `ClarificationDeliveryStore`, `TelegramClarificationStore`, additive delivery models, `append_receipt_with_ingress`, current-only acknowledgement | B-owned extensions, not imported by these vectors | Verify actual delivered names, registration and transactional behavior before binding E. No second history or unchecked SQL adapter. |
| `ReceiptApplicationRefusal` | Proposed B-owned narrow M2 extension | Only a diagnostic committed by the adapter can become this final-application refusal. Original M2 acceptance does not cover the new catch. |
| Application route, actual source/responder authority, model/human meaning evaluation | Not supplied | No automatic caller, provider construction, polling, workflow registration, resume, migration, activation or release. |

A's component author tests and independent reviews concern their respective
source subjects. This document does not extend those verdicts to B/C, durable
composition, a live responder, or a later assembled candidate. E owns actual
integration tests in `tests/test_clarifications/test_caller_integration.py` and
its proof record; D deliberately supplies no `test_*`, skip or xfail placeholder.

## Consume the fixtures, not a second implementation

```python
from tests.test_clarifications.composition_vectors import happy_path_inputs, vectors
from tests.test_clarifications.composition_scenarios import (
    SyntheticResponderPolicy, SyntheticTelegram, clarified_validator,
)

catalogue = vectors()             # fresh concrete data, no vector is executed
first = catalogue[0]             # V01, combined happy path FIRST
fixture = happy_path_inputs()   # canonical M0 input, updates and independent expectations
provider = SyntheticTelegram(message_ids=fixture["provider_ids"])
policy = SyntheticResponderPolicy(fixture["policy_allowed"])
validator = clarified_validator()
# E supplies actual isolated store/delivery/edge/coordinator and assertions.
# Feed fixture["updates"] through provider -> edge.pull, not direct handler dicts.
```

Each `Vector` has `sealed_cases`, concrete `Case.inputs` / `Case.expected`, named
`schedule`, common required `observations`, and discriminating `Control`s.
`vectors()` returns fresh nested data each time. A consumer must not mutate its
expected bundle with the results it is testing. Some cases deliberately hold
constructor keyword changes instead of an invalid constructed object: apply
`caller_changes` through A's `inputs` **inside the refusal assertion**. Operation
faults and mutation selectors are harness instructions, not a production API or
a supplied simulator. Controls require the named assertion to fail; an unrelated
exception or fixture setup failure is not a successful bite.

### Fixed identities and independent expected data

F0 is A's complete v2 profile plus the offline-storage unknown. Every required
base unknown stays present. Its original brief is A's exact `BRIEF`, including
Unicode and CRLF; do not replace it with M3's shorter stand-alone profile.
The synthetic namespace comes from A's input factory. Bot `7001`, chat `-1001`,
authorized actor `5001` and denied control `5002` are fixtures, not real accounts.
Both actors are allowed by the provider policy only in V11's distinct-actor race.
V09's different-author guard and V12's corrections use synthetic trusted-port
receipts to reach their preconditions, not a broadened provider allow-list.

The question is `Must it work offline?`, why `It changes the storage design.`,
affected decisions `[offline storage]`, `material=false`, field `constraints`.
Q is derived by the actual M0 identity API, never a truncated/guessed ID. The
question copy is `500`; typed message `601`, update `1001`, contains **`" Yes \n"`**.
The disposition prompt copy is `600`; callback `cb-701`, update `1002`, uses the
exact stored `clar:answered` payload. Fixed update dates are synthetic constants.

`happy_path_inputs()` supplies expected typed/confirmation receipts, a literal
expected human event and an independent expected history. Event identity and
receipt digest use M0's real public identity functions; expected text, actor,
disposition, source kind and binding come from those fixed input literals, not
`validate_receipt`, a checker report or a store response. The source reference
is `clarification-receipt:<receipt_sha256>`, **not** an invented `e-1` or a generic
gate event. The existing foundation formats the independent expected history;
A's `clarified_candidate` constructs F1 from its mapping. There is no copied
validator or persistence engine.

Compare actual record/source/supplement identities to that independent bundle
before supplying F1. F1 preserves the original product quote and complete
sections, changes the contract to `context_profile_clarified/v1`, adds exact
`{source_id, record_sha256}` and C1 `Must work offline` with the closed
clarification source `{kind, source_id, question_id, event_ids, question, answer}`.
All ordered active event IDs must appear, with the exact answer text. In a race,
both legal commit orders are possible: check both event identities/actors, then
require the reference order to match the observed persisted order. Do not pick
an arbitrary winner or use checker output as the oracle.

## Coverage: immutable sealed acceptance, additional discriminating vectors

The sealed #202 acceptance is unchanged. These mappings supplement it; they do
not rewrite its meaning or make its original proposed tests executed.

| Vector | Sealed cases | Required observation |
| --- | --- | --- |
| V01 | T01 | Combined prepare → question → typed retention → confirmation → restart → F1 check → explicit ack/replay. |
| V02 | T02 | Full checker first; malformed cross-products and narrow exception recovery; no state work. |
| V03 | T02,T17 | Exact types, hashes/history/authority refusals and scoped ports. |
| V04 | T14 | Cross-process atomic send winner for questions, duplicate prompts and explicit retry. |
| V05 | T12,T14 | Both reverse-completion copies, commit-then-raise and explicit uncertainty. |
| V06 | T03,T12,T14 | K1 lost mapping: real ordinary route, explicit reconciliation, new genuine pull only. |
| V07 | T05,T14 | K5 current admission and fresh application; admitted network effects may still finish. |
| V08 | T03,T04,T06 | Captured nested values/membership/context; provenance and binding controls. |
| V09 | T06,T07 | Exact text, dispositions, author confirmation once, separate model suggestions. |
| V10 | T08 | Immutable replay/collision and refusal-key recovery. |
| V11 | T09,T10 | Both genuine concurrent actions/attributions and first-create merge. |
| V12 | T11 | Unknown corrections before retention; earlier refusal and correction/confirmation/reopen precedence. |
| V13 | T11,T14 | Exact reopen snapshot, unseen answer survival, late generation and double confirmation. |
| V14 | T12 | Child-process crashes at real commit/effect boundaries and durable recovery. |
| V15 | T13 | Strict result/copy/send/lookup damage before use; no fabricated history. |
| V16 | T05 | Exact unknown metadata identity, order/field changes and reintroduction. |
| V17 | T15 | Exact reference mapping vs stale/fabricated/model/unresolved evidence; meaning not evaluated. |
| V18 | T16 | Current-only new acknowledgement; historical exact replay; no pause/stop override. |
| V19 | T03,T12 | Committed final refusal vs accepted capture; outages propagate and hold offset. |
| V20 | T01,T17 | Imports/construction operationally inactive; unbound ordinary routes unchanged. |

This covers every T01–T17. E records actual case and control identities/outcomes,
including SQL dialect, not just these group labels. No unexecuted case is passed.

## Required real-store observations and schedules

Reuse `tests/test_clarifications/test_store.py`'s `Db`, `_database_url`, `db`/`lite`,
`other`, `restart`, `rows` and dump/cleanup contracts with the new tables registered
as B specifies. Its `at_once`/`race` fixtures demonstrate first-attempt barrier
placement but use threads; they **do not** discharge V04's independent-process
requirement. E must give each child its own engine to the same file SQLite or
throwaway PostgreSQL schema. Use the existing `tests/pgtier.py` safety checks,
never the live/shared database or another Temper instance. Reuse A's provider
and policy machinery, not M2 `World`/`FakeStore` for persistence assertions.

`SCHEDULES` names logical seams, not already-delivered injection methods:

- `attempt.read_count`, `attempt.before_transaction`: force both contenders to
  present the same expected count, then release. Count committed winners and
  fake provider calls. A loss leaves no provisional write; its record can still
  be `pending`. Compare delivery membership under the same serialization.
- `append.before_revision_cas`: overlap actual first attempts, then allow the
  loser to reload. Do not re-enter the barrier on its retry. First-create uses
  the real missing-row/unique-insert race. No process-local lock as proof.
- `provider.before_send`, `provider.return_id`: control post-admission K5 and
  out-of-order completion. No database transaction may stay open across the
  fake network call. B's implementation must use one stream-before-send lock
  order and real transaction/CAS behavior on each supported dialect.
- `ingress.before_commit` / `after_commit_before_return`: observe the same commit
  for pull stamp, receipt/result and event/revision (or diagnostic without a
  receipt). Callback acknowledgement, prompt send and offset advancement follow
  the durable result. A pre-commit death leaves none of those authoritative rows;
  a post-commit death replays the exact kept outcome.
- `delivery.after_commit_before_return`: restart and query every ID through
  lookup **and** presentation-copy membership, including retired presentations
  and prompts. Never infer the set from representative `SendRecord.message_id`.
- `check.before_current_recheck`, `consumption.before_current_cas`: interpose a
  rival revision. New stale ack refuses `REVISION_CONFLICT`; an exact previously
  kept ack returns False even after the stream advances. Existing historical
  `mark_consumed` semantics remain unchanged.

Parent/child event pipes establish ordering; terminate and join the child at the
specified fault point, then inspect with a fresh engine. No timing sleeps or
retry-until-green. Observe committed row counts, immutable identity/digest/result,
copy membership, application guards, revision, offset and provider/ack call order.
Do not print answer bodies or raw provider/model/tool logs to prove ordering.
PostgreSQL proof needs actual passing case identities from that dialect, not a
green job name with skipped cases.

## Input ownership, scope and application outcomes

The embedding application supplies exact original/candidate/prior history,
selected relevant question IDs, explicit presentation generation/text, transport,
source and responder-policy references, authorized scope enforcement, actual
persistent store and preloaded schema. Neither a reference nor construction of a
Python receipt is authentication. Authority denial must be enforced at the
coordinator **and the scoped transport adapter's reads/writes**. No allow-all
default, source discovery, reference dereference or implicit fork authority.

`prepare` validates the complete candidate via real M1 before store work. The
store merges current history, not M1's stale prepared JSON. Display is rebuilt
from the committed revision. Selecting an answered question is an explicit
refusal, not permission to reopen it. Unrelated unknowns remain visible without
a universal block-everything policy.

Capture validation and application are different:

- A real M2 pull captures membership/context and independent nested contents.
  A public caller-crafted update, service credential, browser hint or ordinary
  inbox row is not such a pull. Mutation of exposed data cannot replace it.
- **Applied:** current transaction adds the event and advances the revision.
- **Retained/unapplied:** exact authoritative action evidence is kept without an
  event/revision advance (for example typed words without disposition, stale
  generation, already-confirmed action or known cross-actor correction).
- **Diagnostic-only refusal:** no authoritative receipt text/key is reserved.
  Unknown correction targets must reach this outcome even where another
  condition would retain them. Earlier provenance/binding refusal still wins.
- A successful `(held_receipt, new)` tuple cannot represent diagnostic-only
  refusal. The proposed typed final-refusal bridge is raised **after commit**;
  M2 catches only that subtype and says `Not applied.`. Outages/programming errors
  remain errors and hold the offset. V19's unknown-target correction exercises
  that bridge at the trusted port, not a new Telegram correction UI.
  `Received.` acknowledges receipt, not
  requirement adoption, application success, semantic correctness or consent.

### K1 and K5 are residuals, not promises of exactly-once delivery

K1: an unknown copy can fall through to ordinary handling, including an ordinary
command/ask under its existing rules. It is not promised to be harmless. Explicit
trusted `record_delivery(send_id, message_id)` reconciliation needs independent
evidence and permission; it cannot guess from an ID or search history on its own.
Already-saved ordinary rows cannot be converted into authenticated clarification
ingress. Only a new provider pull/redelivery/new reply after mapping can bind.
The eventual application must decide whether this fallback is acceptable.

K5: current/answered checks at admission reduce needless sends, but a new answer
or generation can commit after admission and before the network completes. A
stale copy can therefore exist. Fresh append transaction checks decide its
application. Distinct genuine current answers both survive, potentially
conflicting. Explicit uncertain resend may produce multiple network copies;
retain every eventual returned ID. Do not silently reset an uncertain attempt
or automatically resend/reopen.

Acknowledgement does not execute downstream work. A downstream effect may happen
before its acknowledgement is lost. Consumers need their own permitted use of
the consumption identity/idempotency; the library promises no exactly-once
external effect and cannot override pause/off/cancel/launch/source authority.

## Data inventory and privacy boundary

The existing store retains canonical original/candidate/history bindings,
presentations/copies, authoritative receipt JSON for applied/retained actions,
immutable results, revisions, pending consumption and acknowledgement identities.
Answer text and sidecars are real stored data in a real deployment, not just
hashes. Refusal diagnostics may retain linkable action/stream IDs and digests;
"no authoritative key reservation" does not mean "no identifier stored".

B's additive delivery ledger is in the **same database**: immutable intent/text,
reply-to, payload/disposition pairs and typed confirmation link; attempts;
every delivered message ID and lookup/copy binding; ingress transport/update
ID/digest/offset plus result or diagnostic binding. No raw update JSON, second
answer cache, generic inbox substitute, new key/auth service or automatic history
search belongs here. Checked loaders must detect partial required-row loss
before replay or admission. Old pre-extension stores have no verified send
mapping; do not infer one from existing copy IDs or bless missing hashes.

Unkeyed consistency checks detect the specified damage, not a coherent trusted
writer rewrite, complete rollback or erasure. Metadata/ref strings are not
source authority. D3 reader lists, answer/input scope, retention duration,
deletion/export/backup and migration policy remain separate real-use decisions;
synthetic source delivery chooses none of them. No real data, credentials,
default connection URL or real responder list appears in these fixtures.

## Evidence reporting

Keep separate records for (1) static coverage/shape/source continuity,
(2) executed constructor/import smoke checks, (3) existing component tests and
normal full local/remote gates, (4) actual new integration executions and
mutation bites, (5) independent review, and (6) live/model/human evidence.
Only E can report category 4 for this assembled loop; categories 5/6 cannot be
inferred from author results. A NOT_RUN vector remains NOT_RUN even when category
3 is green. Source-only delivery is UNLANDED and not a deploy/restart permission.

A reference-successful F1 still says only that references match its supplied
record/original. Even an exact negative answer can accompany C1 and pass measured
reference checks. Always retain `meaning_status=NOT_EVALUATED`; do not invent an
`accepted`, semantic PASS or resumed-run field, and retain the frozen
`NOT_MEASURED` score spelling. Nothing here revives an older evaluation/release
campaign or names an application/winning-team interface.
