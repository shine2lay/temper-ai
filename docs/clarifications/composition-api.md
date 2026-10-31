# Explicit clarification composition: shared API

This is **M4 A**, the shared source interface and preparation bridge. It is an
opt-in, supplied-input library foundation, not an application route or a completed
composition. There is no coordinator implementation, registered caller, workflow,
poller, source discovery, provider construction or automatic invocation here.
No store, transport, retention or responder-policy authority is granted by these
interfaces. Meaning remains `NOT_EVALUATED`.

The existing pieces remain responsible for their own behavior:

- [M0 contracts](contract.md): canonical inputs, identities and closed refusals.
- [M1 preparation](caller.md): complete checking, history display and supplement.
- [M2 Telegram edge](telegram.md): authenticated-pull boundary and synchronous
  `present` operation. Its injected store is not made durable by this API.
- [M3 store](storage.md): actual `RecordResult`, `StoredStream`, `Supplement` and
  existing history transactions. A later store extension owns delivery and ingress.
- `configs/architecture/bin/context_profile_clarified_check.py`: the shipped
  source-reference checker, not a requirements-meaning judge.

## Preparation adapter — available here

```python
from temper_ai.clarifications.preparation_adapter import prepare, compose_supplement

# canonical_input is an already constructed canonical M0 CallerInput.
display = prepare(canonical_input)
# Requires a supplied committed prior record/revision covering the candidate.
composed = compose_supplement(canonical_input)
```

Both functions return M1's dictionaries. Neither stores the prepared record or
acknowledges consumption. A supplied revision in an adapter test is not evidence
that a database committed it.

M1 deliberately loads its own M0 module by path. Its `CallerInput`, `StreamKey`
and `TransportNamespace` are therefore different **exact types** from canonical
`temper_ai.clarifications.contracts` classes. Passing a canonical input directly
to M1 still refuses with `caller.type`; subclasses and look-alikes are not accepted
at the adapter either.

The adapter reconstructs just these three types through M1's **existing** module:

| Input | Preserved exactly |
| --- | --- |
| Stream | namespace, original brief digest, resulting stream identity |
| Original | text including Unicode/whitespace/newlines, digest |
| Candidate | original JSON string and digest, reference, optional brief binding |
| Prior record | revision, original JSON string and digest; absent stays absent |
| Selection | question IDs and their order; affected decisions and their order |
| Scope | source-authority reference, transport name/bot ID, chat ID, responder-policy reference |

There is no JSON reserialization, trimming, reference dereference, second M0 load,
module identity patch, alternate validator or loosened M1 guard. The adapter calls
only M1's public `prepare` or `compose_supplement`. Reconstruction reruns the same
M0 constructor invariants, then real M1 runs the **full checker first**, before
prior-record processing or question selection. M1 alone owns its narrow recovery
for a real-schema-invalid `TypeError`; a schema-valid `TypeError` or any other
unexpected checker error still propagates. An envelope-only profile is not a
complete candidate.

Only M1's path-local `ContractRefusal` is translated, retaining canonical
`RefusalCode`, guard and location, with the original exception as its cause.
`CallerRefusal` (including `candidate.complete`, `ask.current`, `ask.unresolved`,
`compose.committed`, `compose.covers_candidate`), foundation errors and unrelated
exceptions are not caught/relabelled. There is no fallback empty history.
Returned mutable containers are fresh, as provided by M1. Exact original text,
record identity, separate supplement and source mapping are not merged into a
rewritten brief. Reference success does not establish semantic acceptance.

Public operations open no files, environment variables, sockets, subprocesses,
stores or provider clients. **Cold imports are not claimed pure**: ordinary module
imports and M1's existing schema/module loading still occur.

## Shared ports — declarations, not implementations

`temper_ai.clarifications.caller_contracts` defines structural protocols:

- `CoordinatorStore` reuses all seven existing synchronous M3 public operations:
  `merge_candidate`, `save_presentation`, `record_copy`, `append_receipt`, `load`,
  `supplement`, `mark_consumed`. It adds the required **future**
  `mark_current_consumed(stream, *, revision, record_sha256, consumption_id,
  original_brief) -> bool`. An exact already-kept acknowledgement returns False;
  otherwise all current identities must be checked in one transaction before
  recording a new acknowledgement (True). A new stale one refuses with
  `REVISION_CONFLICT`. A does not implement this extension or change historical
  `mark_consumed` behavior. An acknowledgement never executes a downstream action.
- `QuestionTransport.present(presentation, unknown, text, *, resend=False) ->
  SendResult` describes existing synchronous M2 behavior. The future coordinator
  obtains `unknown` from the checked M1 row and compares it with the canonical
  presentation. It must not trust an unrelated supplied unknown dictionary.
  Real binding needs the durable store extension, not the existing locked fake.
- `ClarificationAuthority.require(*, operation, stream, source_authority_ref,
  responder_policy_ref) -> None` is injected enforcement of an already-authorized
  scope. Operations are `read`, `write`, `send`, `acknowledge`; denial raises.
  The future coordinator must refuse a missing port, not substitute allow-all.
  A reference is a label, not a credential or grant.

No protocol is runtime authentication or persistence proof. M2's `SendResult`
retains `sent`, `delivered`, `uncertain`, `answered`, `not_current` and an actual
lost-admission record state which can remain `pending`. Nothing here maps these
states to success or promises exactly-once network delivery.

## Shared requests and snapshots

All wrappers are frozen dataclasses with slots; the mappings inside snapshots
remain caller-editable **copies**, not immutable attestations. Their constructors
do not validate that a supplied report, record or authority is true. Consumers
must revalidate at the effect boundary, not trust a mutated flag.

| Type | Contents |
| --- | --- |
| `PresentationRequest` | Canonical frozen M0 `Presentation`, exact display `text`; generation is supplied, not inferred. |
| `PreparedClarification` | Actual M3 `RecordResult`, independent M1 `display`, fixed `meaning_status`. |
| `RecoveredClarification` | Actual M3 `StoredStream`, independent M1 `display`, copied actual M3 `Supplement`, fixed `meaning_status`. No implicit send/ack. |
| `CheckedClarification` | Canonical stream, revision, record/original digests, candidate ref/JSON/digest, original text, separate supplement, copied source mapping, consumption ID, copied checker report, fixed `meaning_status`. No accepted/PASS/resume field. |

Immutable M3 record/stream containers are reused rather than duplicated. Display,
report, source-mapping and supplement containers do not alias constructor inputs
or one another. Every meaning field is `NOT_EVALUATED` and is not an init argument.
A snapshot may already be stale when returned. Future current-state checks,
atomic acknowledgement, real enforcement and durable send/intake are separate work.

## Reusable synthetic inputs

`tests/test_clarifications/composition_scenarios.py` contains test-only reuse:

- M1's complete-profile/input builders (canonical by default; an explicit
  `contracts` module variant keeps M1's original tests on its local types), row
  lookup and M0-validated synthetic event constructor. The latter is not evidence
  of a genuine provider pull or authenticated person.
- M2's recording responder policy, parameterized by an explicit allowed set, and
  a small subclass of the existing `FakeTelegram` with explicit bot/copy IDs.
- The source-reference constructor and **real shipped** clarified/v1 validator.
- F0: the original complete profile plus `Must it work offline?`, non-material,
  with decisions `[offline storage]`. F1: a separate clarified candidate with
  supplied exact question, answer, ordered active event IDs and source mapping.

These are data constructors, not a fake persistence layer, alternate checker or
copied fixture framework. They never infer expected reference success from a
checker's output. Original M1/M2/checker test assertions remain in place; only
constructor reuse changes. Frozen M0 and the foundation remain unchanged.

## Verification boundary

`tests/test_clarifications/test_preparation_adapter.py` begins with a combined
canonical prepare → synthetic answer → reprepare → compose test. It then checks
full-checker-first malformed inputs (missing section, unhashable field/IDs and
combined cases), every input field, exact types, narrow exception translation,
internal-error propagation, hashes, namespaces, no aliases and no operational I/O.
It also exercises the shared synthetic constructors against the actual clarified
checker. In-memory mutations bite the exact-type guard, translation scope and
each snapshot-copy site with named assertions; no frozen component is rewritten.

This is **adapter/interface proof**, not the M4 end-to-end vector: it does not
exercise durable send admission, pull-plus-append atomicity, cross-process races,
restart recovery or current-consumption CAS. The downstream store, coordinator
and vector tasks share this source base but own separate modules/tests/docs.
Real invocation, D3, release, land, deployment and activation remain separate.
