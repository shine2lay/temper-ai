# Clarification loop: the frozen M0 contract

`temper_ai/clarifications/contracts.py` is the one shared boundary of the
clarification loop: when requirements are unclear, temper asks a person instead
of guessing, and keeps each real answer exactly, with where it came from.

Three pieces are built against it side by side:

- **M1, the caller**: prepares questions from a `context_profile/v2` candidate
  and hands the record its exact inputs.
- **M2, the Telegram receipt**: pulls a person's reply from the provider and
  turns it into an `ActionReceipt`.
- **M3, the store**: keeps receipts and record revisions, and appends events.

The #308 foundation (`configs/architecture/bin/context_profile_clarifications.py`,
described in `docs/architecture/context-profile-clarifications.md`) is unchanged.
This module builds the events that foundation already accepts, and says who and
what each event comes from.

**Interface hash:** `ba03b8d84da5a7f83080b98a04974749281f6fee0d3d519fc217966a78f0ee4f`
(SHA-256 of the public names, fields, signatures, constants and known-answer IDs,
and of every check: each guard and shape-check call by place, every private
function's code and every compiled pattern, as normalised source without
docstrings; pinned by `test_the_public_interface_is_frozen`). A dropped, weakened
or relabelled check moves it; a reworded docstring does not. Reviewers receipt it
together with the commit and the SHA-256 of `contracts.py`.

## What it is, and what it is not

- Pure and deterministic: standard library only, no temper_ai import, and no
  file, environment, clock, network, subprocess or database access. A configs/
  script may load the file by path.
- Every object is a frozen dataclass whose fields are checked when it is built.
  A wrong value raises `ContractRefusal` with one closed `RefusalCode`, the label
  of the guard that fired (`guard`) and the field (`where`). That includes JSON
  nested past Python's recursion limit and integers past its digit limit: they
  are `malformed`, never another exception. Python's own limits are the only
  size limits.
- It checks shape, binding and consistency. **It authenticates nobody.** A
  receipt is only as true as the provider-pull ingress that built it (M2, for
  Security's review). An object forged consistently inside the trusted process
  is out of its reach.
- No storage, transport, caller or registration lives here.
- **Attribution is not authority.** An event's `actor.ref`, an `authorised`
  `ResponderDecision` and `source_authority_ref` record who answered, under
  which responder policy, and under which authority the answer is kept. None of
  them is authentication beyond the provider-pull ingress, owner consent, a
  requirement or plan approval, an execution, spending or release approval,
  permission to resume work, or permission to use a source. An accepted answer
  answers its one question and authorises nothing else.

## Identities

Seven identities, each with its own prefix and its own digest domain, so no two
kinds can collide. `digest(name, body)` is SHA-256 of canonical JSON (sorted keys,
compact separators, Unicode kept) of
`{"contract": "temper_clarification_loop/v1", "identity": name, "body": body}`.

| Identity | Function or property | Built from |
|---|---|---|
| Stream (record) `s-` | `StreamKey.stream_id` | `digest("stream", {namespace, brief_sha256})` |
| Question `q-` | `question_id(brief_sha256, unknown)` | the foundation's own recipe: brief hash plus the exact unknown metadata. No namespace: that lives in the stream. |
| Presentation `p-` | `Presentation.presentation_id` | `digest("presentation", {stream_id, question_id, metadata_sha256, generation, responder_policy_ref, transport, chat_id})` |
| Action `a-` | `ActionIdentity.key` | `digest("action", {transport: {transport, bot_id}, chat_id, kind, action_id})` |
| Event `e-` | `event_id(receipt)` | `digest("event", {action, binding: {stream_id, question_id, presentation_id}})` |
| Receipt sidecar | `receipt_sha256(receipt)` | SHA-256 of `receipt_json(receipt)`; an event's `source.ref` is `clarification-receipt:<that hash>` |
| Consumption `c-` | `consumption_id(stream_id, revision, supplement_sha256)` | `digest("consumption", {stream_id, revision, supplement_sha256})` |

The supplement a `c-` ID binds is the foundation's `compose_supplement` output,
consumed as its own source next to the original brief: never concatenated into
the brief, and an answer is never presented as a quote from the original brief
or candidate.

The event ID never includes the response text, disposition, update ID, time or
retry count. An exact replay keeps its ID; two different actions with the same
text get different IDs; the same action identity with a changed body is refused
(`check_replay`), never re-keyed.

A displayed ordinal ("2", "#2", "Q2", "question 2.") is never a question ID:
every place that takes one refuses it with `ordinal_as_question_id`.

`metadata_sha256(unknown)` is the digest a presentation binds, so a question
whose metadata changes is a different presentation.

`question_id` only recomputes an ID; it does not check the unknown's shape. M1
derives the questions themselves with the foundation's `derive_questions`.

## Functions

All pure. A wrong argument raises `ContractRefusal`.

| Function | Signature | Gives |
|---|---|---|
| `question_id` | `(brief_sha256, unknown) -> str` | the `q-` ID |
| `metadata_sha256` | `(unknown) -> str` | the digest a presentation binds |
| `receipt_json` | `(receipt) -> str` | the canonical sidecar text |
| `receipt_sha256` | `(receipt) -> str` | the sidecar's SHA-256 |
| `receipt_from_json` | `(text) -> ActionReceipt` | the receipt, from its exact canonical text only |
| `event_id` | `(receipt) -> str` | the `e-` ID |
| `validate_receipt` | `(receipt, *, presentation, copies, current_generation, question_ids, confirmed=None) -> ReceiptValidation` | accepted (with the event), retained or refused |
| `check_replay` | `(stored, incoming) -> bool` | `True` exact replay, `False` another action; raises `changed_body` |
| `check_reopen_precondition` | `(receipt, *, revision, active_event_ids) -> None` | raises `stale_reopen` when the seen answers changed |
| `check_correction_precondition` | `(receipt, *, answer_actors) -> None` | raises `cross_actor_correction` for someone else's answer, `missing_record` for an unknown one |
| `check_confirmation_precondition` | `(receipt, *, confirmed_actions) -> None` | raises `already_confirmed` when the typed message already gave an event |
| `check_expected_revision` | `(expected, current) -> None` | raises `revision_conflict` when the stream moved |
| `consumption_id` | `(stream_id, revision, supplement_sha256) -> str` | the `c-` ID; revision 1 or later |

## The caller's input boundary: `CallerInput`

The caller is handed data, never paths, and opens nothing:

- `stream` (`StreamKey`: authority `namespace` reference plus `brief_sha256`).
- `original_text` and `original_sha256`: the exact original brief. Missing is
  `missing_original`; a hash that does not match is `hash_mismatch`.
- `candidate_json`, `candidate_sha256` and `candidate_ref`: the exact
  `context_profile/v2` candidate text, its hash and where it came from.
- `candidate_brief_sha256`: the brief digest recorded with the candidate's run.
  It and the candidate's own `brief_sha256`, whichever are present, must equal
  the stream's brief hash (`hash_mismatch`). With neither, the candidate is
  `missing_binding`: it is never assumed to belong to this brief.
- `prior_revision`, `prior_record_json`, `prior_record_sha256`: the stored
  record. Revision 0 means a first creation with no record. Any later revision
  without its record is `missing_record`: never replaced by an empty history.
- `question_ids`: the selected questions (full `q-` IDs).
- `source_authority_ref`: the authority the answers will be kept under. Missing
  is `missing_authority`. It says where answers are kept, not what they
  authorise.
- `transport`, `chat_id`, `responder_policy_ref`: where questions go and who may
  answer. `affected_decisions` are optional notes.

`candidate()` and `prior_record()` return fresh parses of the exact checked text;
`presentation(question_id, metadata_sha256, generation)` builds a `Presentation`
for one selected question (an unselected one is `unknown_question`). Pass
`metadata_sha256(unknown)` of that same question's unknown: nothing else ties the
two together.

## Receipts: `ActionReceipt`

One person's transport action exactly as the ingress received it. Its canonical
JSON, `receipt_json(receipt)`, is the immutable sidecar; `receipt_from_json`
decodes it and refuses anything but that exact canonical text (closed shapes at
every level, no duplicate keys, no NaN).

- `ingress`: how it reached the server. Only `provider_pull` (`VERIFIED_INGRESS`)
  can yield a human event. The `UNVERIFIED_INGRESSES` (`caller_label`,
  `service_credential`, `browser_hint`, `inbox_row`, `handler_dict`) and
  `model_output` (`MODEL_INGRESS`) are representable so a refusal can be kept,
  and are never accepted.
- `action` (`ActionIdentity`): `transport` (`TransportNamespace`: provider and
  bot identity), `chat_id`, `kind` (`message` or `callback`) and `action_id` (a
  message ID or callback query ID). Its `key` is the store's unique receipt key.
- `update_id`, `sender_id`, `sender_is_bot`, `forwarded`: as the provider sent
  them. The event's `actor.ref` is `<transport>-user:<sender_id>`.
- Telegram IDs are the provider's numbers: user, bot and message IDs and the
  delivered copies match `[1-9][0-9]*`, chat IDs `-?[1-9][0-9]*`. A username or
  a bot token (`<digits>:<secret>`) is refused, so neither can reach a sidecar.
  Callback query IDs stay opaque, as the provider makes them.
- `text` and `text_sha256`: the exact text, never stripped or reformatted. A
  callback carries no text; its provider payload is kept in `callback_data`.
  Text is blank when every character is whitespace or an invisible format
  character (Unicode category Cf, such as U+200B): a lone zero-width space is
  blank, `a` followed by one is not. The same rule holds for every reason.
- `binding` (`PresentationBinding`): the stream, question, presentation,
  generation and delivered `message_id` the action answered.
- `responder` (`ResponderDecision`): the ingress's decision for this sender under
  a policy; chat membership alone is never authority. `authorised` means this
  sender may answer this question, and nothing more.
- `intent`: `answer`, `correct` (names the answers it `supersedes`, with a
  `reason`) or `reopen` (with a `reason` and the snapshot the person saw:
  `seen_revision`, `seen_active_event_ids`).
- `disposition`: `answered`, `deferred` or `unknown`. Typed text without one is
  kept, not applied: a later button press by the same person (`confirms`, a
  `ConfirmedText` naming the typed message's action, author and text hash)
  applies that exact text. A callback without `confirms` carries no text, so it
  is kept as `blank_text`: a bare button never records a disposition by itself.
  M2 asks for typed text first, then a button press confirms it. One typed
  message gives at most one event (`check_confirmation_precondition`); a change
  of mind is a correction.

## Validation: `validate_receipt`

`validate_receipt(receipt, *, presentation, copies, current_generation,
question_ids, confirmed=None)` runs every receipt check before any human event
exists and returns a `ReceiptValidation`:

- `accepted`: carries `event_id` and `event_json`, the canonical #308 event
  (`event()` returns a fresh copy).
- `retained`: a well-formed receipt kept as evidence; nothing is applied
  (`RETAINED_CODES`).
- `refused`: the receipt is rejected; only the diagnostic is kept
  (`REFUSED_CODES`).

Checks, in order: provenance (not model output, verified ingress, not a bot, not
forwarded, the presentation's transport and chat); responder (the policy's
decision is about this sender, under the presentation's policy, `authorised` on
the `responder_policy` basis); binding (same stream, question, presentation,
generation, and a delivered copy); the question is in the latest record; the
presentation is current; for a confirmation, the typed message is supplied, is
the one linked, has the linked text and author, and the confirmer is its
author; then an explicit disposition and non-blank text. Wrongly typed
arguments raise `ContractRefusal` instead of returning a result.

## Replay, preconditions and the revision check

`validate_receipt` never compares a receipt with stored receipts, the question's
current answers or the stream's revision. The store does, in the append
transaction: `check_replay` on a known action key before validating;
`check_reopen_precondition` before appending any reopen,
`check_correction_precondition` before any correction and
`check_confirmation_precondition` before any confirming button press; and
`check_expected_revision` in its compare-and-set. Only accepted or retained
receipts occupy an action key; a refused attempt is kept as a diagnostic under
its `receipt_sha256`.

- `check_replay(stored, incoming)`: `True` for an exact replay, `False` for a
  different action, `changed_body` for the same action identity with any other
  content. A stored receipt that did not come through `provider_pull` is
  `malformed`: it can never hold a genuine action's key.
- `check_reopen_precondition(receipt, revision=, active_event_ids=)`: a reopen
  holds only while the question's active answers are the ones the person saw;
  otherwise `stale_reopen` (retained). Another question moving the revision does
  not make it stale.
- `check_correction_precondition(receipt, answer_actors=)`: `answer_actors` maps
  each stored answer of the question (event ID) to its `actor.ref`. A correction
  supersedes only its sender's own answers: another person's is
  `cross_actor_correction` (retained, never applied), and an answer the store
  does not have is `missing_record`. Another person's answer changes only through
  a reopen and then a new answer.
- `check_confirmation_precondition(receipt, confirmed_actions=)`:
  `confirmed_actions` are the action keys of typed messages that already gave an
  event in the stream. A press confirming one of them is `already_confirmed`
  (retained), whatever its disposition.
- `check_expected_revision(expected, current)`: the compare-and-set predicate;
  `revision_conflict` when the stream moved.
- `AppendResult`: what one append attempt did to one stream. `applied` carries
  the `event_id` and moves the revision by exactly one; `retained` and `refused`
  carry a code and leave the revision unchanged, except a `revision_conflict`,
  which reports the stream's current revision.

## Refusal codes

`RefusalCode` is closed: adding, removing or renaming a code is a contract change.

| Code | Status | Meaning |
|---|---|---|
| `malformed` | refused | A value has the wrong type, shape or pattern, or a result is inconsistent. |
| `missing_original` | refused | The exact original brief was not supplied. |
| `missing_record` | refused | A stored record, the typed message a confirmation names, or an answer a correction names, was not supplied. |
| `missing_authority` | refused | No source authority for keeping answers. |
| `missing_binding` | refused | The candidate is not bound to a brief: no digest from its run and none of its own. |
| `hash_mismatch` | refused | A text and its hash, or two bound hashes, disagree. |
| `cross_context` | refused | The action is bound to another stream. |
| `ordinal_as_question_id` | refused | A displayed position was used as a question ID. |
| `unknown_question` | refused | The question is not in the latest record or selection. |
| `binding_mismatch` | refused | Wrong question, presentation, generation, delivered copy or confirmation link. |
| `transport_mismatch` | refused | Another bot, provider or chat than the presentation's. |
| `unverified_ingress` | refused | A label, service credential, browser hint, inbox row or handler dictionary posing as a person. |
| `model_not_human` | refused | Model output can never be a human event. |
| `bot_sender` | refused | The sender is a bot. |
| `forwarded_message` | refused | A forwarded message is not its sender's own answer. |
| `responder_not_authorised` | refused | The responder decision is not an authorisation of this sender under this policy. |
| `confirmer_not_author` | refused | A confirmer never becomes the author of someone else's text. |
| `changed_body` | refused | The same action identity arrived with different content. |
| `revision_conflict` | refused | The stream moved since it was read. |
| `no_explicit_disposition` | retained | Typed text without a disposition; kept until its author confirms it. |
| `blank_text` | retained | Blank text is kept as evidence, never applied. |
| `stale_presentation` | retained | An answer to an earlier presentation of the question. |
| `stale_reopen` | retained | The answers the person saw have changed since. |
| `cross_actor_correction` | retained | A correction names someone else's answer. |
| `already_confirmed` | retained | The typed message a press confirms already gave an event. |

## Constants

`CONTRACT` (`temper_clarification_loop/v1`), `FOUNDATION_CONTRACT`
(`context_profile_clarifications/v1`), `PROFILE_CONTRACT` (`context_profile/v2`),
`RECEIPT_REF_SCHEME` (`clarification-receipt`), `TRANSPORTS`, `VERIFIED_INGRESS`,
`UNVERIFIED_INGRESSES`, `MODEL_INGRESS`, `INGRESSES`, `ACTION_KINDS`, `INTENTS`,
`DISPOSITIONS`, `RESPONDER_DECISIONS`, `RESPONDER_BASES`, `VALIDATION_STATUSES`,
`APPEND_STATUSES`, `RETAINED_CODES`, `REFUSED_CODES`.

## Example

Synthetic data only. This runs as a test (`test_the_doc_names_every_public_name_code_and_the_interface_hash_and_its_example_runs`).

```python
import hashlib

from temper_ai.clarifications.contracts import (
    ActionIdentity,
    ActionReceipt,
    Presentation,
    PresentationBinding,
    ResponderDecision,
    StreamKey,
    TransportNamespace,
    metadata_sha256,
    question_id,
    validate_receipt,
)

brief = "A synthetic booking tool."
brief_sha256 = hashlib.sha256(brief.encode("utf-8")).hexdigest()
unknown = {
    "question": "Must it work offline?", "why_it_matters": "Changes storage and sync.",
    "decisions_affected": ["client storage"], "material": True,
}
stream = StreamKey("temper-clarify:example/project", brief_sha256)
bot = TransportNamespace("telegram", "7001")  # the bot's numeric ID, never its token
policy = "responder-policy:example/owner-only"
question = question_id(brief_sha256, unknown)
presentation = Presentation(stream, question, metadata_sha256(unknown), 1, policy, bot, "-1001")
text = "Yes, offline first."
receipt = ActionReceipt(
    ingress="provider_pull",
    action=ActionIdentity(bot, "-1001", "message", "42"),
    update_id=1001, sender_id="5001", sender_is_bot=False, forwarded=False,
    text=text, text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    binding=PresentationBinding(stream.stream_id, question, presentation.presentation_id, 1, "41"),
    responder=ResponderDecision(policy, "5001", "authorised", "responder_policy"),
    intent="answer", disposition="answered",
)
result = validate_receipt(
    receipt, presentation=presentation, copies={"41"}, current_generation=1, question_ids={question},
)
assert result.status == "accepted"
event = result.event()  # the #308 event; its source.ref names the receipt sidecar
```

## Changing the contract

The interface hash above is pinned in
`tests/test_clarifications/test_contracts.py`. Changing any public name, field,
signature, constant, refusal code, ID recipe, check or pattern changes it: update
the pin and this page together, and have Architecture (meaning) and Security
(provenance) receipt the new hash, with its commit and the `contracts.py` SHA-256,
before M1–M3 build on it.

The tests run the combined happy path first, through the unchanged foundation,
then the refusal cases, then one literal case for every guard, field check and
argument check. Each case also runs against a copy of the module with that one
check removed (in memory, never a file), and must then fail; that copy's checks
must also differ from the frozen ones, so removing any check moves the hash.
