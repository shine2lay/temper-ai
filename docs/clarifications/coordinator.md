# Explicit clarification coordinator

`temper_ai/clarifications/caller.py` is an **opt-in library**, not an authenticated
application endpoint, route, team caller, workflow node or launch permission.
Nothing registers it. It constructs no default client, engine, policy or poller.
The caller supplies the original text, canonical M0 `CallerInput`, complete v2
candidate, record snapshot, authority, store, transport and shipped clarified/v1
validator. It discovers no sources and generates no candidates.

It reuses [the preparation bridge and shared ports](composition-api.md),
the actual M1 preparation/display/composition functions, and #312's
`check_clarified_profile`. There is no second checker or store. The original
review subjects and frozen M0/foundation are unchanged.

## Interface

Construct `ClarificationCoordinator` with explicit keyword arguments:
`store: CoordinatorStore`, `transport: QuestionTransport`,
`authority: ClarificationAuthority`, `clarified_validator: v2.Validator`.
None are optional. Construction does not call any of them. Python import still
has the ordinary dependency and schema-loading behavior of M1; this is not a
claim of zero file reads during a fresh import.

| Operation | Input besides canonical `caller` | Result |
| --- | --- | --- |
| `prepare` | None | `PreparedClarification(record, display)` |
| `present` | `presentations: tuple[PresentationRequest, ...]`, explicit `resend=False` | tuple of unchanged M2 `SendResult` values |
| `recover` | None | `RecoveredClarification(stored, display, supplement)` |
| `check_candidate` | separate `profile: object`, opaque `candidate_ref: str` | `CheckedClarification` |
| `acknowledge_consumption` | `checked: CheckedClarification` | `True` for new acknowledgement, `False` for an exact kept one |

Original and candidate references are labels, **not credentials** or sources to
open. `ClarificationAuthority.require` enforces the embedding application's
already-authorized stream, source authority and responder-policy scope. Missing
ports refuse; no permissive fallback is supplied. Ordinary operations complete
real M1 validation before any port invocation. Read/write/send/acknowledge
denials precede the corresponding store/transport calls.

### Prepare

1. Adapt only exact canonical `CallerInput`; run the full real M1 checker,
   including structural diagnostics before malformed-field processing.
2. Require read/write permission, then delegate merge/current-history/CAS to M3.
   Supplied prior state never replaces durable history.
3. Check the returned stream and build the real display from the committed
   result, with no ask selection. This allows a concurrently answered selection
   to be shown rather than causing a re-ask. The original caller keeps its IDs.

Returned state may already be stale when the caller receives it. `prepare`
does not send, append a human receipt or acknowledge consumption.

### Present

Run full M1 with the explicit ask selection; require read/write/send; check exact
current revision and record digest and that the supplied candidate's questions
are in the committed record. Validate all presentation bindings before any send:
canonical presentation, selected current unresolved question, metadata, stream,
transport, chat, responder policy and source authority. Text is supplied exactly,
not generated or normalized; provider-specific text validation stays with M2.

For each request, recheck current state, save its presentation, then call the
injected M2 transport. **M2/B own durable immutable intent and atomic send
admission before provider I/O**, not this library. M2 results (including
uncertainty/not-current/answered) are not promoted to success. `resend=True` is
explicit caller intent, not an automatic retry policy.

There is no all-or-nothing batch or transaction spanning a read and a network
send. Earlier presentations/sends can survive a later refusal. A question can
change after this coordinator's read; B's eligibility fence covers movement
before admission, and K5's documented residual covers movement after admission.
The coordinator neither emulates nor claims to remove that residual.

### Recover

Require full M1 checking and read permission. Load M3's integrity-checked current
history; missing history is a refusal, never an empty replacement. A supplied
historical revision/digest is checked against its stored supplement. Revision
zero requests a read without a historical snapshot; it grants no write.

Compose the current stored record with M1 and compare every identity, exact
original/supplement text and source mapping with M3's supplement. Return
independent display/supplement containers with no asks. No sending, receipt
append, acknowledgement, downstream work or automatic resume follows recovery.
A candidate containing uncommitted questions refuses; recovery does not merge it.

### Check a separately supplied candidate

Check the v2 context first, require read permission and exact current
revision/digest. Compare real M1 composition with the store supplement; invoke
actual #312 with the exact original, supplied candidate and supplied record;
canonicalize that candidate snapshot; then recheck current state. Movement
refuses instead of refreshing its source references. Canonicalization failures
retain real checker diagnostics rather than inventing an empty candidate.

The result holds candidate bytes/digest, candidate label, stream/revision/record,
exact original/supplement, source mapping, consumption ID and the real report.
A wrong validator is reported by #312, never replaced with a fallback. The
embedding caller must supply the **actual shipped schema**; a same-labelled
custom validator is not authenticated by the library.

`references_ok` is **not semantic acceptance**: `meaning_status` remains
`NOT_EVALUATED`. It does not prove an answer supports the candidate's meaning,
that a human is authorized, or that every unrelated unknown is resolved. Unknowns
are not silently promoted to decisions or made a universal block-all rule.

### Acknowledge, without doing the consumer's work

An acknowledgement is bookkeeping of the caller's explicit action, not execution
or proof that any external effect happened. This library never calls a consumer.

1. Require canonical context, the exact checked-result type and read/acknowledge
   permission. Match original/stream/record/source/supplement/consumption identity
   to M3's checked history. Editable result dictionaries are not certificates.
2. If that exact source acknowledgement is already kept, return `False` before
   renewed candidate validation or current-revision comparison. This is the
   explicit replay exception to checker-first ordering: it neither renews
   acceptance nor performs new work. A now-invalid v2 candidate cannot erase an
   otherwise exact kept acknowledgement; wrong identities still refuse.
3. Otherwise run full M1, require current state and exact composed mapping, check
   canonical candidate JSON/hash, rerun the real #312 check and compare the full
   report (requiring `references_ok is True`). Invoke
   **`mark_current_consumed`**, never historical `mark_consumed`. B must perform
   the final current-identity check and insertion in one transaction, including
   exact kept replay if another writer won. Its refusal propagates unchanged.

A store acknowledgement cannot provide exactly-once external work. If a consumer
performs its effect and crashes before acknowledgement, separate idempotency or
operator handling is still needed. Nothing here wakes or resumes a run.

## Errors, ownership and proof limits

Canonical input/binding/staleness refusals remain `ContractRefusal`; M1 diagnostics
remain `CallerRefusal`; composition/history inconsistency remains
`ClarificationIntegrityError`. Policy, database and unexplained programming
errors propagate rather than becoming absence, denial or success. Malformed
candidate JSON is the narrow, explicit conversion exception. No raw-update or
human-dictionary intake is exposed; B/M2 own ingress/provenance/receipt handling.

`tests/test_clarifications/test_coordinator.py` starts with a combined happy path
using actual pure components and **NON-DURABLE recording ports with fixed
replies**. These are not another fake database: no mock implements merge, CAS,
delivery, persistence or receipt admission. Unit controls cover checker-first
ordering, denial, exact identity/text, supplied-candidate history, stale check/ack,
kept replay, alias isolation, explicit errors, no operational I/O/defaults and
assertion-specific guard/order bites. Shared A constructors are reused.

These tests do **not** prove durable store/transport composition, live authority,
transactional races, crash recovery or delivery. B's actual SQL/delivery/ingress
checks and E's final V01/whole-composition proof remain required. C changes only
this coordinator, its tests and this document; it selects no application caller
and authorizes no registration, land, deployment, provider call or activation.
