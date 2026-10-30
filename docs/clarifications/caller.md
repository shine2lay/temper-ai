# Clarification loop: requirements preparation (M1)

`configs/architecture/bin/context_profile_clarification_caller.py` is the piece
that turns a requirements candidate into questions for a person, without losing
anything already asked or answered, and later hands the answers back for
re-evaluation, kept apart from the original requirements text.

It adds no new contract. It joins three pieces that already exist, in one fixed
order, and leaves each of them unchanged:

- **M0's frozen contract** (`temper_ai/clarifications/contracts.py`,
  [contract.md](contract.md)): its `CallerInput` is the only input.
- **The frozen complete `context_profile/v2` checker**
  (`configs/architecture/bin/context_profile_check.py`): `check` runs first.
- **The #308 foundation** (`configs/architecture/bin/context_profile_clarifications.py`,
  [context-profile-clarifications.md](../architecture/context-profile-clarifications.md)):
  it builds and validates the record, projects states and composes the supplement.

It asks nobody, calls no model and stores nothing. M2 (the Telegram receipt) and
M3 (the store) use its output; M4 decides when a re-evaluation consumes a supplement.
Its output format is `context_profile_clarification_caller/v1`.

## The order of checks

1. **M0's input boundary.** A `CallerInput` refuses, as it is built, a missing or
   mismatched original text, an unbound candidate, a missing prior record after
   revision 0, a record at revision 0, a missing source authority, and every hash
   that doesn't match its text (`ContractRefusal`, codes in contract.md).
2. **This module's input type** (`caller.type`). Only a `CallerInput` built with
   this module's own `contracts` is accepted, so a look-alike object can't skip
   step 1. Build inputs with `context_profile_clarification_caller.contracts`.
3. **The complete v2 checker** (`candidate.complete`), on the candidate and the
   exact original text, before any record work. Every error refuses, with the
   checker's diagnostics in `errors` and the candidate's ref in the message. The
   foundation's own envelope check is not a replacement: an envelope it accepts
   is still refused here.
4. **The prior record** is validated by the foundation inside
   `create_record(candidate, original, previous=<prior record>)` (or
   `project_states` when composing). A truncated history, an event without its
   question, an event ID reused with changed content, a cross-actor correction,
   a model revision, altered question metadata or a too-deep record is refused
   with the foundation's own `ClarificationError`, unchanged. Nothing replaces or
   repairs a record.
5. **The step's own checks**: the questions to ask (`prepare`), or a committed
   record that covers the candidate (`compose_supplement`).

A structural ok is never a judgment of meaning: every output and this module's
`CallerRefusal` carry `meaning_status: NOT_EVALUATED`, never PASS. M0 and foundation
errors pass through unchanged, without added fields; no refusal establishes
meaning. The score modules' own `NOT_MEASURED` spelling is theirs, untouched; this
module doesn't import them.

## `prepare(caller) -> dict`

Builds or extends the record for one candidate and shows every question.

- The record is always `create_record(candidate, original, previous=<prior record>)`.
  Exact repeated metadata, in any order of unknowns or of an unknown's keys, keeps
  its question ID, state and history. Any change to a question's metadata (its
  text, why it matters, its decisions or their order, materiality, or its field,
  present or not) is a new question with a new ID; the old one stays in the record
  with its history. No answer moves across, and no model rephrases anything.
- `ask` is the caller's selection (`CallerInput.question_ids`), refused unless every
  selected question is a question of this candidate (`ask.current`) and not
  already answered (`ask.unresolved`). An answered question is shown, not asked.
- Nothing is stored. The store commits `record_json` with compare-and-set at
  `expected_revision` (M3).

| Field | Meaning |
| --- | --- |
| `format`, `meaning_status` | `context_profile_clarification_caller/v1`, `NOT_EVALUATED` |
| `stream_id`, `original_sha256` | M0's stream key ID and the exact original text's SHA-256 |
| `candidate_ref`, `candidate_sha256` | the candidate's ref and its exact JSON text's SHA-256 |
| `structural_check` | `{"ok": true, "counts": ...}` from the checker |
| `expected_revision`, `prior_record_sha256` | the prior revision and record hash this record extends (0 and null at first) |
| `record_json`, `record_json_sha256` | the new record as canonical JSON (sorted keys, no spaces, exact Unicode) and its SHA-256 |
| `questions` | one row per question of the record, in record order (below) |
| `unresolved_question_ids` | every question not answered, old ones included |
| `ask` | the validated selection |
| `affected_decisions` | `CallerInput.affected_decisions`, as given |

Each row holds the unknown's own keys (`question`, `why_it_matters`,
`decisions_affected`, `material`, and `field` when it has one) and:

| Field | Meaning |
| --- | --- |
| `question_id`, `metadata_sha256` | M0's question ID and metadata hash |
| `change` | `new` (not in the prior record), `repeated` (in both), `absent` (in the prior record, not in this candidate) |
| `state`, `resolved` | the foundation's state: `unanswered`, `answered`, `deferred`, `unknown`, `conflicting` or `reopened`; only `answered` is resolved |
| `answer` | the current human answer when answered, else null |
| `active`, `active_event_ids` | the current human events: ID, disposition, exact answer, actor, source |
| `history_event_ids` | every event on the question, in order, superseded ones included |
| `model_suggestions` | model events, shown apart and model-attributed; they resolve nothing |

Materiality is shown for each question's own decision; nothing blocks globally.
An old (`absent`) question stays visible with its state but can't be asked: the
candidate dropped or changed it.

## `compose_supplement(caller) -> dict`

Hands the answers back for re-evaluation, kept apart from the original.

- Needs the committed prior record, revision 1 or later (`compose.committed`),
  holding every question of this candidate (`compose.covers_candidate`): prepare
  and commit first, so no new question can go missing from the unresolved list.
- The supplement, its mapping and the unresolved list come from the foundation
  unchanged. Only current human answers enter it; model suggestions never do.
- Nothing is concatenated, padded or rewritten: `original_text` is the exact
  original string, and a short answer such as `Yes` stays exactly `Yes`.

| Field | Meaning |
| --- | --- |
| `format`, `meaning_status` | as above |
| `stream_id`, `revision` | the stream and the committed revision composed |
| `candidate_ref`, `candidate_sha256` | the candidate checked first |
| `original_text`, `original_sha256` | the exact original text, unchanged, and its SHA-256 |
| `record_json_sha256`, `record_sha256` | the committed record text's SHA-256 (M0's binding) and the foundation's canonical record hash |
| `supplement`, `supplement_sha256` | the separate supplement (canonical JSON) and its SHA-256 |
| `source_mapping` | the foundation's exact mapping: a JSON pointer to each question, answer and attribution list, and the event IDs |
| `consumption_id` | M0's `consumption_id(stream_id, revision, supplement_sha256)` |
| `unresolved_questions` | the foundation's state rows that aren't answered |

The three identities stay separate: `original_sha256`, `record_sha256` and
`supplement_sha256`. The supplement also carries the original's and the record's
hashes inside it, so a consumer binds all three. Which candidate step may consume
a supplement, and how its sources are checked, is M4's (after Architecture #312's
clarified checker); this module only composes.

## Refusals

Three layers refuse, in order, and each keeps its own error:

- M0's `ContractRefusal` (a `ValueError` with a closed `code`), when the
  `CallerInput` is built, before this module runs.
- This module's `CallerRefusal`, a subclass of the foundation's
  `ClarificationError`, with `guard` (the label below), `errors` (the checker's
  diagnostics, or empty), `meaning_status` (`NOT_EVALUATED`) and a message ending
  in `[<guard>]`.
- The foundation's own `ClarificationError` for an invalid prior record, passed
  through unchanged (its exact message, no guard).

| Guard | Refuses | Without it (its bite, in the tests) |
| --- | --- | --- |
| `caller.type` | anything but this module's own `CallerInput` | a look-alike with a hash M0 refuses is prepared, and its false hash is bound as the candidate's |
| `candidate.complete` | a candidate the complete v2 checker rejects | an envelope-only candidate becomes questions |
| `ask.current` | asking a question that isn't in this candidate | a changed question's stale old version is asked |
| `ask.unresolved` | asking an answered question | an answered question is asked again |
| `compose.committed` | composing with no committed record | composing too early is the foundation's bare "expected object", the same refusal a non-object record gets |
| `compose.covers_candidate` | a committed record that lacks some of the candidate's questions | the new questions vanish from the unresolved list |

A separate bite shows that `create_record` must get the prior record: given none,
an answered question that the candidate dropped disappears with its history.

## Loading, and what it touches

Loading the module reads two files: M0's `contracts.py`, by path into its own
module object `context_profile_clarification_contracts` (importing the
`temper_ai` package has side effects, so it never does), and the frozen v2 schema
the checker loads. It imports the checker and the foundation as
`configs.architecture.bin` modules, as #312's checker does, so they share one
`ClarificationError`.

The public functions do no file, environment, clock, network, subprocess,
database, model or transport access, return fresh plain-JSON values, and are
deterministic. They never register or invoke a workflow caller, send a message,
or store a record.

## Tests

`tests/test_architecture/test_context_profile_clarification_caller.py`, synthetic
data only: the combined happy path first (prepare, a person's exact answer through
an accepted M0 receipt, a deferral and a model suggestion, re-prepare with the
unknowns reordered, compose), then the refusals and edge cases, then one bite per
guard. A bite disables exactly one guard in an in-memory copy of the module, never
a file, and shows the unsafe outcome above.
