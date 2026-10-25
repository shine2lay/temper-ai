# Clarified profiles: opt-in reference checking, not acceptance

Accountable lead: Architecture. Task #312 implements the source-aware reference
boundary for the owner's clarification requirement (m43065, global rule 33).
It does not implement an interactive clarification loop or accept Stage 1.

## H-CLARIFY-SOURCE-1 — written before implementation

Evidence: the frozen v2 checker checks every quote against the original brief,
with a 2–40-word quote rule. A real recorded answer such as `yes` cannot pass as
such a quote. Padding it or concatenating a supplement into the original would
misrepresent its origin. HOME recorded this hypothesis before this task in
`clarification-foundation-499e66fb-home/READBACK.md`.

Change: add a separate `context_profile_clarified/v1` candidate contract and a
pure checker. Keep original quotes on the original brief; bind clarification
references to the exact recorded question, answer and current supporting events.
Expected: literal short/Unicode answers pass reference checks without rewriting
anything; stale, invented, unresolved and model-labelled evidence fails. The
existing structural checks remain. Falsifier: wrong origin passes, any existing
check disappears, an input is mutated, or reference success claims meaning,
authorship, consent, Stage 1 acceptance or an activated workflow.

### Literal expected cases (before implementation)

- `Must it work offline?` / `yes`, and `May we share café notes with 東京?` / `no`:
  exact human-attributed current references pass, including all supporting IDs.
- ` Yes \n` and `Non.\n日本語、café 🧭`: exact text passes; stripping, padding,
  paraphrasing, changing case or Unicode normalization fails reference equality.
- Original `A synthetic scheduling app.` still passes as an original quote;
  clarification text absent from the original fails `quote_not_in_brief`.
- Assumptions stay assumptions. Empty supplements and unresolved questions do
  not by themselves fail the whole profile or impose a universal work hold.
- Missing/extra/wrong-typed fields fail structural validation. Wrong original,
  record hash, supplement identity, question ID, event list, question or answer
  fails the appropriate binding/reference check.
- Corrected answers pass only with the corrected record identity and active
  events. Reopened, conflicting, deferred, unknown and model-only states cannot
  support a clarification reference; all remain in `unresolved_questions`.
- Multiple identical answers preserve every attribution; omitting, duplicating
  or reordering the active IDs fails. Exact imported event replays do not change
  the canonical identity or revive retired answers.
- Duplicate IDs/ranks, rank gaps, unnamed unknowns, missing maturity evidence,
  unsupported numbers/names and constraint/goal overlap still fail. Numbers
  must occur in the cited source, not elsewhere in the brief or record.
- A number occurring in a question paired with `no` can pass a presence check;
  that is deliberately **not** proof that the proposed requirement is true.
- With dependencies already loaded, module execution and checking must succeed
  under filesystem/environment/network/clock/subprocess/database traps. This
  is not a cold Python dependency-loading or whole-process purity claim.

HIT at the dedicated reference boundary: the **original dedicated run passed
188 tests in 0.73s**, including the guarded preloaded-dependency case. There was
no product failure or purity-harness failure to repair. This does not prove cold
dependency loading, authenticated attribution or semantic correctness. Normal
repository hooks and exact-head remote CI/land results are recorded separately
in the final private delivery receipt; this source document is not a release gate.

## Decision, alternatives and compatibility

Use an additive internal contract rather than altering v2. All v2 product fields,
unknowns, assumptions and their constraints remain; `brief_sha256` becomes
required, and `clarification_source` is required. Quote and assumption source
forms are unchanged. A third closed form cites a clarification. No version
fallback, legacy key-file loading, automatic profile conversion or runtime
registration is provided.

Rejected alternatives: concatenating sources loses origin and changes the brief
identity; padding short answers invents evidence; silently extending v2 changes
its frozen consumers; calling the old checker and discarding quote errors also
loses unrelated checks. This checker dispatches each source type explicitly and
reuses only the existing pure schema, item, normalization and number helpers.

The caller must create a **separate candidate**, retaining the original and any
accepted profile. This checker returns a report, never a rewritten profile.
Rollback is to stop opting into the new checker/contract; no stored v2 data needs
migration. Nothing here activates a caller, workflow, UI, endpoint or persistence
path. The frozen 42-run plan and admission/custody work are unchanged.

## Pure API and source boundary

`check_clarified_profile(profile, original_brief, record, validator) -> dict`
accepts plain finite JSON data, the exact original UTF-8 string, a #308
`context_profile_clarifications/v1` record, and a preloaded
`context_profile_check.Validator` for `contract.clarified.v1.schema.json`.
The trusted caller loads that exact shipped schema; an old/v2 validator is not
an implicit fallback. No source locator is fetched and there is no CLI.

The report contains only:

- `references_ok`: no structural or reference diagnostics;
- `errors`: deterministic `{reason, path, detail}` diagnostics;
- `counts`: visited `items`, original `quoted`, `assumed`, and `clarified` items;
  these count source forms, not accepted requirements;
- `unresolved_questions`: the full #308 state projection for every state other
  than `answered`; an invalid record cannot be projected and yields an explicit
  record error, not an assertion that all questions are resolved;
- `meaning_status: "NOT_EVALUATED"`, even on reference success.

`brief_sha256` hashes the exact original UTF-8 string without newline, Unicode,
case or whitespace normalization. Required closed `clarification_source` holds
`source_id` and `record_sha256`, exactly equal to the corresponding values of
`compose_supplement(record, original_brief).source_mapping`. #308 canonicalizes
question order and identical event replays, but preserves distinct event order,
history and attribution. Even an empty supplement has its own source identity.

A clarification source is exactly:
`{kind: "clarification", source_id, question_id, event_ids, question, answer}`.
It must cite a currently answered question in the validated supplied record;
`event_ids` must equal the complete ordered active supporting list. Exact question
and answer strings are compared without stripping, padding, normalization or
paraphrase. There is no quote-word threshold on answers. Model output cannot
resolve human state or enter the supplement. Other unresolved states cannot be
used as evidence, but their presence is not a universal work-blocking rule.

Hashes prove consistency with the **supplied** record, not authenticated history.
A caller that changes a record and recomputes all bindings can make a different,
self-consistent candidate. The checker cannot discover an omitted historical
record, authenticate a responder, or detect a caller lying about authorship.
Actor/source labels remain attribution, never authenticated identity, authority,
consent or permission. No reference check grants execution or source access.

## Audit of every existing check

| Frozen v2 check | Clarified contract behavior |
| --- | --- |
| Closed schema, required sections, enums and field constraints | Preserved; new required source identities and one closed source variant only. |
| Optional brief identity | Strengthened to required exact original UTF-8 hash. |
| Original quote normalization, 2–40 words, contiguous brief span | Unchanged; original quotes never search the supplement. |
| Numeric presence | Original quotes unchanged; clarification items use only their exact question and answer, tokenized separately, never another answer or global brief text. Presence is not meaning, units or negation proof. |
| External system name presence | Original quote unchanged; clarification name must occur in its own question or answer under the existing normalization. |
| Observed workload and known current-system state require a quote | Require original quote or valid clarification evidence, never an assumption. Legacy diagnostic names retained. |
| Unknown scalar and empty-list naming, including current-system items | Preserved; record projection is separate from profile unknown-field naming. |
| Non-unknown maturity needs evidence | Preserved. |
| Unique constraint/goal IDs; unique contiguous 1..n goal ranks | Preserved; malformed values report schema errors rather than crashing set/dict operations. |
| Constraint/goal quote overlap | Preserved normalized substring rule within original quotes. Reusing the same valid clarification question/events for a constraint and a goal also fails. Different sources are not merged by matching a word such as `yes`; cross-source semantic overlap needs separate evaluation. |

## Remaining caller and semantic evaluation work

Temper's separately admitted integration must supply genuine response/message
provenance, stable event IDs, concurrent-safe persistence, correction/reopening
and restart/resume behavior through the existing trusted interface. Reuse the
existing question metadata and IDs instead of regenerating paraphrases. Present
unresolved states and decide which decisions need answers; this module chooses
neither a disposition nor a universal hold policy.

A separately reviewed evaluator must assess whether an answer actually supports
the proposed fact, including negation, scope, units, authority and trade-offs.
It must maintain source/instruction separation, ordinary permissions and consent,
and compare a new candidate without mutating an accepted profile. Matching text,
a schema pass or number presence does not do that work. There is no model call,
semantic grader, Stage 1 admission or activation in this task.

## Verification and base

Worktree base: `499e66fb4b34cc7c749b78b8e6cc13e35ff7ddbf`, tree
`31d57d2a0a087522fc15c8057b2d0d0d7fcfe5a4`, parent
`876e2b677a5eeb38a0371d2004cd31ae12aa0c08`. The four protected #308 SHA256s:

| Path | SHA256 |
| --- | --- |
| `configs/architecture/bin/context_profile_clarifications.py` | `dc7ad96bfbb3e367f855d9a9f7f128239d98148e2d287489d015b998f35b0805` |
| `configs/architecture/stages/context_profile/clarifications.v1.schema.json` | `03a2a526e1c2d3a395ef046fc61884dc833e7a79bd4fe04174793a689306df21` |
| `tests/test_architecture/test_context_profile_clarifications.py` | `4869caee2b7957332afd11b3f9461d394e0befd8d5957ae2e09280b83cfa2d74` |
| `docs/architecture/context-profile-clarifications.md` | `e6d67c809b92f4e4337be02afe6c1447d67f163c199c9fb7cba8109a6d6249e7` |

The protected original v2 checker SHA256 is
`f49f759d1f91b69e3f02fb9c36bc272d838f7e11ea2651550550687320a67c46`;
the v2 schema SHA256 is
`965a75c384ab0b72220c507a78004aafc478bdcb4916ec1f050d8780ad377fbe`.
They matched before and after the dedicated run. The final tree comparison must
also show no edits to any old candidate, prompt, fixture, dataset or #308 file.

The dedicated command uses only literal synthetic data and public source/schema
helpers, excluding the runtime/database conftest and automatic plugins:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --frozen --extra dev python -m pytest -c /dev/null --rootdir=. --confcutdir=tests/test_architecture -p no:cacheprovider tests/test_architecture/test_context_profile_clarified_check.py -q
```

After implementation, run this suite, then the normal repository commit hooks
and `wt land` gates, including remote GitHub runner PostgreSQL and static
Chromium. No local database/browser or second Temper is part of this task.
Report original results and any harness repair separately, plus exact final
commit/tree/parent, four-file scope, hashes and final-head CI/land evidence.
