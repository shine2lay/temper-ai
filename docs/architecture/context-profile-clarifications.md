# Clarification records: foundation, not an interactive loop

Accountable lead: Architecture. Task #308 implements the record layer for the
owner's requirement-stage clarification request (m43065, global rule 33): ask
rather than guess, record actual answers and their source, and reuse them.

## H-CLARIFY-1 (written before implementation)

Evidence: `contract.v2.schema.json` has `unknowns` with exact questions and affected
decisions, but no answer history. Change: add a pure, versioned, provenance-preserving
record layer alongside that frozen contract. Expected result: deterministic known
cases retain exact questions, answers and attribution; reuse unchanged answers;
preserve revisions and unresolved states; and never rewrite the original brief.
Falsifier: any lost text/history, invented answer, silent conflict resolution, model
answer promoted to human evidence, or import/operation that needs ambient I/O.
Validation: dedicated synthetic tests, then the normal commit/land gates. No model
trial, runtime, new permission or service is needed.

Original dedicated run: **75 passed, 1 failed in 0.14s**. The failed purity test
blocked pytest's own `inspect` import during guard setup, before executing the
module; the record/state/schema cases passed. H-CLARIFY-1 is not falsified by that
setup failure, but its purity measurement was initially incomplete.

### H-CLARIFY-2: repair the purity measurement

Evidence: `monkeypatch.setattr` imports `inspect`; installing the import denylist
before the other traps intercepted the test harness itself. Change: install that
same import denylist last, with every I/O/environment/clock trap still active
before module execution. Expected: the isolated purity case reaches every public
operation and passes without ambient access. Falsifier: execution imports anything
outside the original five-module allowlist or triggers any access trap. **HIT:**
focused repair result **1 passed in 0.06s**, using the dedicated command below with
`::test_import_and_all_public_operations_need_no_ambient_access` appended to the
test path. No module behavior or scope changed. All 76 dedicated cases have now
passed (75 in the original run and the corrected purity case in its isolated run);
the normal hooks still run the complete suite.

## ADR-1: closed refusals, format-character blanks, same-actor corrections

Status: accepted, 2026-10-25 (Architecture #323; rulings by HOME). Hypothesis
H-CLARIFY-3 and its measured result are in that task's report.

Context: Security's #174 notes on the #308 foundation (rm-40b3722a) found three
gaps. O1: deep or huge input escaped as `RecursionError` or `ValueError` instead of
`ClarificationError` (a recursive `_json_data`; `json`'s recursion and Python's
4300-digit integer limit in `_canonical`/`_copy`). O5: `str.strip()` let text made
only of invisible format characters (U+200B, U+2060, U+FEFF) count as an answer.
O3: a correction could supersede another person's answer, so one person could
silently replace another's, against this module's no-last-answer-wins rule.

Decision: every refusal by every public function is a `ClarificationError`.
`_json_data` walks with an explicit stack, in the same order and with the same
checks and messages; a container is an ancestor only while it is open, so cycles
are refused and shared objects are not. `_canonical`/`_copy` turn the encoder's
`ValueError`/`RecursionError` into `data too deep or too large to encode`. No depth
or size cap is added (global rule 31). Text is blank when every character is
whitespace or in Unicode category Cf; minimum lengths are unchanged and nothing is
normalised. A correction may supersede only answers whose `actor` object equals its
own; a reopen stays the explicit cross-person route. The contract stays
`context_profile_clarifications/v1` and the schema file is unchanged, because no
stored records exist yet and only refusals tighten.

Consequences: callers catch one exception type; outputs for accepted input are
byte-identical. The bad one: a delegate cannot fix another person's typo without a
reopen (a sourced reopen with a reason, then a fresh answer). A human cannot
supersede a model-attributed answer either; it never counts, so a human answer needs
no supersession. Blankness follows the interpreter's Unicode database: U+13439 to
U+1343F are unassigned on Python 3.11 (Unicode 14) and Cf from 3.12 (Unicode 15).
Invisible characters outside Cf, such as U+3164 HANGUL FILLER, still count as text.
The module now imports `unicodedata`, so the purity allowlist has six modules.

## Scope and files

- `configs/architecture/bin/context_profile_clarifications.py`: pure functions.
- `configs/architecture/stages/context_profile/clarifications.v1.schema.json`:
  closed persisted-record schema, `context_profile_clarifications/v1`.
- `tests/test_architecture/test_context_profile_clarifications.py`: fixed synthetic
  cases, with no project runtime imports or real briefs/answers.
- This document: caller contract and the still-unimplemented integration boundary.

The module neither asks through a UI nor authenticates attribution. A source/actor
label, including one named "owner", is **not** owner consent, execution authority,
a requirement approval or permission to use a source. It cannot detect a caller
lying about authorship. The trusted caller must not label generated text as a human
response. A model suggestion can be retained explicitly as `model`/`model_output`,
but never resolves a question, supersedes an answer, reopens a question, or enters
the clarification source supplement. No endpoint, runtime registration, activation,
prompt/workflow edit, accepted-profile rewrite or Stage 1 acceptance is delivered.
The frozen v2 profile contract, candidate, prompts, fixtures and 42-run plan stay
unchanged. Not every unknown must block all work: the caller/lead determines which
affected decisions need clarification; `material` is preserved, not a global gate.

## Pure API

All arguments and outputs are plain JSON data, except `original_brief`, a Python
string. Inputs are never mutated; output containers are independent. Only standard
library hashing, JSON serialization, finite-number checks, regular expressions and
the compiled-in Unicode database (for blank text) are used. No filesystem, environment, network, subprocess, database, clock or random
source is consulted by the module body or operations. Python's normal source and
standard-library loading are not a new file-access mechanism. There is no CLI.

- `derive_questions(profile, original_brief) -> list[dict]`: the caller supplies an
  already-validated `context_profile/v2` profile. Checks the envelope, exact unknown
  metadata and any supplied `brief_sha256`, not every other v2 field or its meaning.
  Full v2 checking remains the existing caller's responsibility. Copies `question`,
  `why_it_matters`, `decisions_affected`, `material`, and optional `field` without
  rewriting or normalizing. Rejects unknown envelope/unknown metadata fields.
- `create_record(profile, original_brief, *, previous=None) -> dict`: creates or
  extends history. Same brief and exact metadata reuse the same question, even
  when unknowns are duplicated/reordered. Previous questions/events remain, even
  if the supplied profile no longer lists them. Metadata edits create a new ID;
  matching paraphrases or migrating to another original brief is not inferred.
- `validate_record(record) -> None`: raises `ClarificationError` for bad shapes,
  unknown keys, non-JSON/nonfinite/cyclic data, non-UTF-8 strings, bad references,
  content-ID mismatch or inconsistent event history. It does not fetch a schema.
- `append_event(record, event) -> dict`: returns a new record. Same event ID and
  identical content is a no-op; differing content under that ID is refused.
- `project_states(record) -> list[dict]`: sorted question metadata plus `state`,
  `answer` (exact text only when answered; otherwise null), `active_event_ids`,
  `history_event_ids`, and `model_event_ids`. Show every state other than `answered`
  to the caller as unresolved; do not repeatedly ask an unchanged answered question.
- `compose_supplement(record, original_brief) -> dict`: returns three separate
  values: unchanged `original_brief`, a deterministic JSON `supplement` string,
  and `source_mapping`. Only currently answered human-attributed responses appear
  in the supplement; all unresolved states/history remain in the record/projection.

Every refusal by every public function is a `ClarificationError`; bad input lets no
other exception type escape. Nesting is walked with an explicit stack, so depth
meets no recursion limit. Data the interpreter itself cannot encode (too deep for
`json`, or an integer past Python's 4300-digit conversion limit) is refused as
`data too deep or too large to encode`. No depth or size cap is added: deep or huge
data in a profile field this module does not read is accepted.

### IDs, exact text and structural validation

`brief_sha256` hashes the exact UTF-8 encoding of the supplied original text: no
newline, Unicode, whitespace or case normalization. The caller must preserve the
original decoding/newlines if comparing this with a file digest.

Question IDs are `q-` plus SHA256 of compact, sorted-key, non-ASCII-preserving JSON
of `{contract, brief_sha256, unknown}`. The complete exact unknown metadata is the
identity. Order inside `decisions_affected` is preserved; changing it changes the
identity. Questions are returned sorted by ID. An omitted `field` stays omitted.

Event IDs are caller-stable `e-` tokens matching `e-[A-Za-z0-9][A-Za-z0-9._:-]*`.
Choose them from a stable response identity, not from this module's current time
or a retry counter. References use an opaque `scheme:nonempty-suffix` syntax with
no whitespace/ASCII controls. They are recorded exactly, never opened or treated
as authenticated URLs. The same source may contain multiple separately identified
answers; source/actor references do not replace event IDs.

Every record object is closed by the schema. Cross-object invariants also require
`validate_record`: hash binding, duplicate consistency, ordered references,
actor/source-kind pairing, correction reason, unique supersession targets and
model-output restrictions are semantic checks, not assertions JSON Schema makes.
All inputs must be plain finite JSON and valid UTF-8. Text (`question`,
`why_it_matters`, each `decisions_affected` entry, `answer`, `reason`) must be
nonblank: text made only of whitespace (`str.isspace`) and invisible format
characters (Unicode category Cf, such as U+200B, U+2060 and U+FEFF) is refused.
The schema's `\S` pattern is only the structural floor. Text is never normalised:
an answer of `a` followed by U+200B is kept exactly. The implementation's allowed `field` values are checked against the frozen
v2 unknown-field enum in the tests. No new dependency is needed to use the module.

## Events and state transitions

An answer event contains `event_id`, `question_id`, `kind: "answer"`, `actor`,
`source`, exact `answer`, `disposition` and `supersedes`. Actor is `{kind, ref}`;
source is `{kind, ref}`. Allowed matching kinds are `human`/`human_response` and
`model`/`model_output`. Never expand "yes" or "no" into an explanatory sentence.
The question travels with it so its meaning is not detached from the answer.

Disposition is explicitly supplied by the trusted caller: `answered`, `deferred`
or `unknown`. This module does not infer meaning from prose, decide whether a
response fully answers the question, or classify who is authorised to answer it.
For example, retain "I don't know" exactly with disposition `unknown`, not as a
new product requirement. If the caller cannot determine the disposition, it must
keep the question unresolved, not guess `answered`.

Supersession is explicit: a human correction lists named **earlier answer events
by the same actor for the same question** in `supersedes` and supplies a nonblank
`reason`. It removes only those answers from the active set. Missing, future, self,
duplicate, cross-question, other-actor and reopening-event targets are refused; a
target whose `actor` object differs from the correction's gives "supersession must
name the same actor's answer". One person cannot silently replace another's answer:
to set it aside, use an explicit sourced reopen (below); who may reopen stays with
the caller's responder policy. Already inactive earlier answers may be cited again
without reactivating them. An identical duplicate event
in imported history is permitted and processed once; append never adds that replay.

A reopen event has `kind: "reopen"`, its own event/question IDs, human actor/source,
and exact nonblank `reason`; it has no answer/disposition/supersedes. It explicitly
retires all prior active answers for that question without deleting history.
A later human answer can resolve it again. Old duplicate retries cannot resurrect
answers retired by correction/reopening.

Projection rules (no last-answer-wins):

| Active human history | State |
| --- | --- |
| No answers and no reopening | `unanswered` |
| Explicit reopening, no later active answer | `reopened` |
| All active dispositions `answered`, exactly identical answer text | `answered` |
| All active dispositions `deferred` | `deferred` |
| All active dispositions `unknown` | `unknown` |
| Differing answered text, or mixed dispositions | `conflicting` |

Even case/whitespace differences in answers are conflicts unless explicitly
superseded; semantic equivalence is not guessed. Multiple identical answers keep
all their attributions. Deferred/unknown responses remain unresolved regardless
of their text. Models have their own history IDs but cannot change these states.
This is not a quorum, decision-authority system or universal work-blocking policy.

## Synthetic caller example

`clarifications` below is the already-imported standalone module. The abbreviated
profile shows just the consumed envelope; a production caller must first validate
its complete v2 profile through the existing checks. This is test data, not a
real source or an invented Temper endpoint.

```python
brief = "A synthetic scheduling app.\n"
profile = {
    "contract": "context_profile/v2",
    "unknowns": [{
        "question": "Must it work offline?",
        "why_it_matters": "Changes local storage and synchronization.",
        "decisions_affected": ["client storage", "sync design"],
        "material": True,
        "field": "constraints",
    }],
}
record = clarifications.create_record(profile, brief)
question_id = record["questions"][0]["question_id"]
record = clarifications.append_event(record, {
    "event_id": "e-synthetic-response-1",
    "question_id": question_id,
    "kind": "answer",
    "actor": {"kind": "human", "ref": "person:synthetic-requester"},
    "source": {"kind": "human_response", "ref": "conversation:synthetic#response-1"},
    "answer": "yes",
    "disposition": "answered",
    "supersedes": [],
})
record = clarifications.create_record(profile, brief, previous=record)
states = clarifications.project_states(record)
remaining = [state for state in states if state["state"] != "answered"]
source = clarifications.compose_supplement(record, brief)
assert remaining == []
assert states[0]["answer"] == "yes"
assert source["original_brief"] == brief
```

## Supplemental source and mapping

The supplement is compact sorted-key JSON with `contract`, `original_brief_sha256`,
`record_sha256` and `answers`. Each answer has exact question metadata, exact answer
text and an attribution per active supporting event. It is serialized data; quotes,
newlines, Unicode and instruction-like text remain inert in these functions. This
is not a model prompt-injection defence; any later caller still needs its source/
instruction boundary and permission checks.

`source_mapping` contains `source_id: "clarifications-sha256:<digest>"`, the UTF-8
`supplement_sha256`, `original_brief_sha256`, `record_sha256` and `entries`. Each
entry binds the question ID and optional field to JSON pointers within the parsed
supplement (`question_pointer`, `answer_pointer`, `attributions_pointer`) and the
supporting `event_ids`. Resolve pointers against the supplement object, not the
original brief. They are not offsets or quotes from the original brief.

The record digest canonicalizes question order and identical event replays, while
preserving the order of distinct events. History or attribution changes therefore
change the source identity even if the current answer text does not. An empty
supplement is allowed and contains no invented answer. The function never joins
these sources into a replacement brief or mutates an accepted profile.

## Remaining integration: HOME owns separate admission

The next interactive caller/profile re-evaluation step is **not implemented**:

1. At the existing requirements-stage call site, validate the v2 profile and bind
   the exact original brief. Supply the prior clarification record on revisit.
   Use the project's existing trusted persistence and real response path; no new
   storage or endpoint is implied here.
2. Show relevant unresolved questions, their why/affected decisions and states.
   Capture the actual response, actor and message/source reference through that
   trusted path. Keep generated suggestions labelled as models, never human
   responses. Persist the returned history atomically through that existing path.
   This pure module does not solve concurrent writers; callers must prevent lost
   appends rather than overwrite each other's histories.
3. Require explicit named supersession for corrections, or sourced reopening;
   present unresolved conflicts instead of selecting the newest reply. Use existing
   source permissions, authority and consent checks outside this module.
4. Consume the **separate source identity and mapping** during profile re-evaluation.
   The frozen v2 checker only anchors quotes to the original brief and has no
   supplemental-source references. Do not concatenate the supplement and pretend
   its answer was in the original brief, overwrite `brief_sha256`, pad a one-word
   answer to meet a quote-length rule, or call the old checker source-aware.
   A separately admitted source-aware evaluator/adapter must bind original and
   clarification sources, preserve short question/answer context, keep unresolved
   questions explicit and produce newly reviewed evidence/profile output without
   rewriting the existing accepted profile.
5. Test this caller and evaluator integration stage by stage before any whole
   workflow proof. Module tests alone do not ship the clarification loop, accept
   Stage 1, change custody/binding results or amend the 42-run plan.

## Checks and delivery

Run the dedicated model-free cases once after implementation, without loading the
repository's runtime/database conftest or automatic plugins:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --frozen --extra dev python -m pytest -c /dev/null --rootdir=. --confcutdir=tests/test_architecture -p no:cacheprovider tests/test_architecture/test_context_profile_clarifications.py -q
```

The tests use only inline synthetic inputs and these new files plus the existing
public v2 schema/checker. Purity is checked by an import allowlist and executing
preloaded module code and every public operation with I/O, environment, clock,
network, subprocess and database access denied. No project runtime import is used
by this dedicated command. Normal repository hooks may run the wider suite as
usual; they are not replaced or skipped. Land through `wt land`, including its
normal remote GitHub static Chromium/PG gates. No local browser, PostgreSQL or
second Temper service is authorised. Inspect the final diff for precisely these
four added paths and report exact commit/tree, original results and land outcome
back to HOME for its source review and next integration admission.
