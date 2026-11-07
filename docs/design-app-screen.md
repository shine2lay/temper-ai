# design_app_screen_v1: app screens, stage by stage

Design's product-design flow for app screens (UI/UX), the one Design ran by hand for RollCall and
Inkflow, as a Temper workflow. The owner asked for it on 2026-11-04: "lets try to encode the different
stages you had of your flow into temper wf".

Version 1's skeleton (Design #198, W0) set up every stage, both owner gates, the workspace, a contract
for each step's output and the first known case. A stage that is still a stub copies the known case's
output in fixture mode and has it checked against its contract; in real mode it fails at once with "the
real stage is not built yet". Each stage's own task replaces its stub and keeps its contract, one stage
at a time (owner, 2026-11-04: "lets run one stage a time after setting up the skeleton, so we can really
hone in on it"). Built so far: stage 1, intake (Design #206; see "Stage 1: intake"), stage 2, existing
(Design #207; see "Stage 2: existing"), stage 3, ground (Design #210; see "Stage 3: ground"), step 4,
reuse/store/tools (Design #214), stage 4, directions (Design #223; see "Stage 4: directions"), stage 5, build (Design #219 5a scaffold + Design #221 5b model screen writer; see
"Stage 5: build"), stage 6a, measured checks (Design #216; see "Stage 6a: checks"), stage 6b, fenced design
and UX review + build-loop proof (Design #222; see "Stage 6b: review"), stage 7, show + W5 gates prediction
and owner taste encoding, and stage 8, handoff + end-to-end real proof (Design #224; see "Stage 7: show, W5 gates, and Stage 8: handoff"). All 8 stages and both gates are now real and proven on `temper-dev`.

Files, one job each:

| File | Job |
| --- | --- |
| `configs/design/workflows/design_app_screen_v1.yaml` | the workflow: 8 stages, 2 owner gates, 2 loops back to build |
| `configs/design/agents/design_app_screen_stage_v1.yaml` | script agent: runs one step through the CLI (no model, no network) |
| `configs/design/bin/design_app_screen.py` | CLI: one step on a workspace, or the host commands pack, freeze, verify |
| `configs/design/bin/app_screen/workspace.py` | the workspace: stage folders, `run.json`, rounds |
| `configs/design/bin/app_screen/contracts.py` | one JSON schema per output file, plus `validate(step, workspace)` |
| `configs/design/bin/app_screen/gates.py` | the two owner gates: check and record the answer |
| `configs/design/bin/app_screen/known_case.py` | known cases: freeze, verify, pack, copy a stage's output |
| `configs/design/bin/app_screen/fixture_stage.py` | what a stub stage does: fixture copy, or fail loud in real mode |
| `configs/design/bin/app_screen/<stage>.py` | one module per stage: `intake`, `existing`, `ground`, `directions`, `build`, `checks`, `show`, `handoff` |
| `configs/design/bin/app_screen/intake_sources.py` | intake's sources: the owner's words as numbered verbatim items, collected on the host |
| `configs/design/bin/app_screen/intake_check.py` | intake's measured checks on the model's draft, and the final files from a clean draft |
| `configs/design/bin/app_screen/intake_grade.py` | grade an intake run against a trial case's answer key (host) |
| `configs/design/agents/design_app_screen_intake_v1.yaml` | intake's model step: the owner's words -> draft requirements and questions |
| `configs/design/workflows/design_app_screen_v1_intake.yaml` | stage 1 alone (the same nodes), for intake's trials |
| `configs/design/bin/app_screen/product_app.py` | the product file (`~/design-lab/products/<product>/app.yaml`): load, check, the capture list |
| `configs/design/bin/app_screen/throwaway_app.py` | start a throwaway copy of the product (pinned commit, own folder, loopback port, seed) or a static folder, and stop it |
| `configs/design/bin/app_screen/existing_capture.mjs` | Playwright on the host: log in, follow the screen's steps, measure in the page, screenshot the first view (look-only) |
| `configs/design/bin/app_screen/measure_in_page.js` | the in-page measurement (layout width, text sizes, targets, cut text, side scrollers, key regions, errors, text runs) |
| `configs/design/bin/app_screen/existing_measures.py` | one capture's measurement -> the audit's flat measures, which side of each line is a problem, totals per width |
| `configs/design/bin/app_screen/existing_sheet.py` | the contact sheet: every first view at one width, labelled, in one PNG under the image budget |
| `configs/design/bin/app_screen/existing_host.py` | host `capture`: start the copy, run the capture, write the audit, texts, app summary and sheet |
| `configs/design/bin/app_screen/existing_task.py` | the model's task text (job, requirements, measures with problem marks, visible text) and the revise text |
| `configs/design/bin/app_screen/existing_check.py` | stage 2's measured checks on the model's draft, journeys by refs, and the final `journeys.json` |
| `configs/design/bin/app_screen/existing_grade.py` | grade a stage-2 run against a case's answer key (host `grade-existing`) |
| `configs/design/agents/design_app_screen_existing_v1.yaml` | existing's model step: the contact sheet (image) + task text -> draft journeys and problems |
| `configs/design/workflows/design_app_screen_v1_existing.yaml` | stage 2 alone (the same nodes), for existing's trials |
| `configs/design/bin/app_screen/directions.py` | stage 4's deterministic collector (`04-directions/task.md`), draft checker wrapper, prototype compiler (`04-directions/<id>/`), quick measured check runner (`04-directions/<id>/checks.json`), and `04-directions/directions.json` writer |
| `configs/design/bin/app_screen/directions_check.py` | stage 4's 5 deterministic checks on `04-directions/draft.json` (schema, distinct directions, entry screen coverage, show/field grounding, state/action quality) |
| `configs/design/agents/design_app_screen_directions_v1.yaml` | directions' fenced model step: `task.md` -> `draft.json` with 2-3 distinct directions (`claude-opus-5-5`, token `anthropic-2` / `roamee`, no tools, no temperature) |
| `configs/design/workflows/design_app_screen_v1_directions.yaml` | stage 4 alone (`directions_collect` -> `directions_read` -> `directions_check` -> `directions_revise` -> `directions`), for directions' trials |
| `tests/test_design_app_screen_directions.py` | directions' 15 planted-fault checks, retry loop, prototype compilation, quick measured checks (`04-directions/<id>/checks.json`), and Stage 5 `build_task` handoff |
| `configs/design/bin/app_screen/build_scaffold.py` | stage 5's deterministic writer and draft compiler (also shared with stage 4): shell, hash router, per-screen files, tokens CSS, fixture copy, `select_entry_screens`, `compile_direction_prototype`, `build_task(ws)`, `render_draft(ws, draft)` and `build.json` |
| `configs/design/bin/app_screen/build_check.py` | stage 5's measured checks on a written `05-build/` and `draft.json` against ground and direction inputs (9 5a + 5 5b rules) |
| `configs/design/agents/design_app_screen_build_v1.yaml` | build's fenced model step: `task.md` -> `draft.json` per-screen, per-state design specs (`claude-opus-5-5`, token `anthropic-2` / `roamee`) |
| `configs/design/workflows/design_app_screen_v1_build.yaml` | stage 5 alone (`build` -> `build_read` -> `build_check` -> `build_revise` -> `build_finish`), for build's trials |
| `configs/design/bin/app_screen/review.py` | stage 6b's deterministic collector (`measured_items.json`, `sheet.png`, `task.md`), draft checker wrapper, and final `review.json` merger + deterministic `verdict` (`revise` iff `must > 0` else `done`) |
| `configs/design/bin/app_screen/review_check.py` | stage 6b's 7 deterministic checks on `06-checks/round-<n>/draft.json` (measured coverage, demotion/wont reasons, must suggestions, no invented measurements, grounded locations/evidence) |
| `configs/design/bin/app_screen/review_grade.py` | stage 6b's trial workspace builder and grader (`clean-parcelly`, `measured-inkflow`, `taste-planted`, `loop-round-2`, host `prep-review` / `grade-review`) |
| `configs/design/agents/design_app_screen_review_v1.yaml` | review's fenced model step: contact sheet (`sheet.png`) + `task.md` -> `draft.json` (`claude-opus-5-5`, token `anthropic-2` / `roamee`, no tools, no temperature) |
| `configs/design/workflows/design_app_screen_v1_review.yaml` | stage 6b alone (`review_collect` -> `review_read` -> `review_check` -> `review_revise` -> `review`), for review's trials |
| `tests/test_design_app_screen_review.py` | review's 7 planted-fault checks, retry loop, round-level measured grouping, 2-round `review -> build -> checks -> review` loop, and grader |
| `configs/design/bin/app_screen/show.py` | stage 7's deterministic Show&Tell bundle compiler (`07-show/bundle.html` + `bundle-round-<n>.html`), round-over-round non-blank line retention check (`bp-bc056d81`), `showtell.json` + `comments.json` writer, targeted comment resolution on Round > 1, and host `prep-show` |
| `configs/design/bin/app_screen/show_check.py` | stage 7's 4 deterministic checks (`review_done`, `bundle_self_contained`, `showtell_and_comments_match`, `targeted_comments_answered`) -> `07-show/check.json` |
| `configs/design/bin/app_screen/handoff.py` | stage 8's deterministic per-screen Markdown spec generator (`08-handoff/spec/<screen-id>.md`), `design-file.json`, and `followup.json` (`F1..Fn`) |
| `configs/design/bin/app_screen/handoff_check.py` | stage 8's 6 deterministic checks (`gate_final_approved`, `spec_per_inventory_screen`, `spec_sections_complete`, `design_file_valid`, `followup_valid`, `no_open_must_or_unanswered_comment`) -> `08-handoff/check.json` |
| `tests/test_design_app_screen_show_handoff.py` | stage 7's 4 planted-fault checks, W5 gate predictions and owner taste encoding, stage 8's 6 planted-fault checks, and the 2-round `gate_final (changes) -> Round 2 -> gate_final (approve) -> handoff` loop |
| `tests/test_design_app_screen_build.py` | build's scaffold, input guards, 5a + 5b planted faults, broken-draft retry loop, determinism and stage-6a checks |
| `tests/test_design_app_screen_existing.py` | existing's checks, steps, product file, measures and grader, on fixed drafts and broken copies |
| `tests/test_design_app_screen_contracts.py` | contracts, gates, freeze and the CLI, on the known case |
| `tests/test_design_app_screen_intake.py` | intake's checks, steps, collector and grader, on fixed drafts |
| `tests/design_app_screen_case/rollcall-20261104/` | the known case's JSON and Markdown outputs (the pictures and pages stay in the lab) |

## Stages

| # | Stage | Steps (workflow nodes) | Leaves | Built by |
| --- | --- | --- | --- | --- |
| 1 | intake | `intake_collect`, `intake_read` (model), `intake_check`, `intake_revise` (model, only on a failed check), `intake` | the owner's words as requirements (verbatim) and the clarification questions (rule 33) | #206 |
| 2 | existing | host `capture`, then `existing_collect`, `existing_sheet`, `existing_read` (model), `existing_check`, `existing_revise` (model, only on a failed check), `existing` | today's screens captured and measured; the user journeys, each problem with evidence | #207 |
| 3 | ground | `ground` | one shared fixture, the product's design files, the screens x states inventory | #210, #214 |
| 4 | directions | `directions_collect`, `directions_read` (model), `directions_check`, `directions_revise` (model, only on a failed check), `directions`, then `gate_direction` | two or more genuinely distinct clickable directions (`04-directions/<id>/index.html`), each with its measured `04-directions/<id>/checks.json` and `04-directions/directions.json`; the owner picks one | #223, W5 |
| 5 | build | `build`, `build_read` (model), `build_check`, `build_revise` (model, only on a failed check), `build_finish` | the chosen direction: a shell and one compiled file per screen with real per-state layout, copy, action controls and `fixture.json` figure bindings | #219 (5a), #221 (5b) |
| 6 | checks | `checks`, then `review_collect`, `review_read` (model), `review_check`, `review_revise` (model, only on a failed check), `review` | measured checks by script, then findings rated 0-4 and Must/Should/Could/Won't; a Must loops back to build | #216 (6a), #222 (6b) |
| 7 | show | `show`, then `gate_final`, `gate_final_next` | one self-contained Show&Tell bundle (`07-show/bundle.html`), `showtell.json`, `comments.json`, and `07-show/check.json`; approve, or changes back to build as targeted edits | #224 |
| 8 | handoff | `handoff` | a spec per screen (`08-handoff/spec/<screen-id>.md`), `design-file.json`, `followup.json`, and `08-handoff/check.json` | #224 |

Loops: `review` goes back to `build` while its verdict is `revise` (a Must finding is open), and
`gate_final_next` goes back to `build` when the final answer is `changes`. Each loop runs at most twice
(`max_loops: 2`); a third time fails the run (`on_max_loops: fail`), it does not hand off a design that
still has an open Must. Each pass through `checks` starts a new `06-checks/round-<n>/`.

Inputs: `product` (a lowercase id, e.g. `rollcall`), `mode` (`real`, the default, or `fixture`) and
`request_json` (intake's sources document, or a plain request; see Stage 1; unused in fixture mode). Outputs: the direction picked and
who decided it, the review rounds and verdict, and the final verdict and who decided it.

## Workspace

Every step reads and writes only inside the run's workspace:

```
run.json                    product, mode real|fixture, round, status of every step
known-case/                 fixture mode only: the known case, packed by the host, with FREEZE.json
01-request/                 requirements.json, questions.json; real mode also sources.json, draft.json,
                            check.json, check-final.json (draft-first.json when the model revised)
02-existing/                captures/*.png, audit.json (measured), journeys.json (model; each claim has evidence)
03-ground/                  fixture.json, design-files/ (DESIGN.md, tokens.json), inventory.json (screens x states)
04-directions/<id>/         index.html, checks.json; plus directions.json and gate_direction.json
05-build/                   shell/, screens/, index.html, build.json
06-checks/round-<n>/        checks.json, review.json
07-show/                    showtell.json, comments.json, gate_final.json
08-handoff/                 spec/*.md, design-file.json, followup.json
```

`run.json` records each step as `running`, `done` or `failed` with a time; a failed step keeps its reason.

## Contracts

`contracts.validate(step, workspace)` checks every file the step must leave: that it exists (at least
the stated number for a pattern), that JSON files parse and match their schema, that PNG and HTML files
are PNG and HTML, and the rules a schema can't say (a capture, direction page or screen file named in a
JSON file exists; the direction gate picks a direction that exists; a review with an open Must finding
says `revise`). A broken output fails the step with every problem, each as `<file>: <field>: <reason>`,
for example:

```
review: 1 problem(s): 06-checks/round-1/review.json: verdict: is 'done' but must be 'revise' (a Must finding is open)
```

The fields, by file (the full schemas are in `contracts.py`). A file holds only its schema's fields, so
a new field is a contract change; only `fixture.json`, `tokens.json` and an audit screen's `measures` are
open objects:

| File | Must hold |
| --- | --- |
| `sources.json` | `product`, `description`; `items[]`: `id` (S1...), `kind` (request, comment, answer, history), `text` (his words verbatim), `source`; optional `context`, `ref` |
| `requirements.json` | `product`; `items[]`: `id` (R1...), `owner_words` (verbatim), `source`, `kind` (goal, feature, change, constraint, taste), `maps_to[]`; from intake also `item` (S...), `means`, optional `open_questions[]` |
| `questions.json` | `questions[]`: `id`, `question`, `status` (open, answered); an answered one also `answer` and `answer_source`; from intake also `about[]`, `why`, `choices[]` (2-4) |
| `check.json`, `check-final.json` | `verdict` (ok, retry), `pass` (draft, final), `counts`, `problems[]`: `check`, `where`, `problem` |
| `audit.json` | `source`; `screens[]`: `id`, `width`, `state`, `capture` (a PNG in 02-existing/), `measures` |
| `journeys.json` | `journeys[]`: `id` (J1...), `name`, `goal`, `problems[]` of `claim` + `evidence[]` |
| `fixture.json` | any JSON object: the product's shared sample data |
| `inventory.json` | `design_files` (defined, partial, none); `screens[]`: `id`, `name`, `states[]`, `widths[]`, optional `spec` |
| `directions.json` | `directions[]`: `id`, `name`, `idea`, `page` (an HTML file in 04-directions/); at least two |
| `<id>/checks.json`, `round-<n>/checks.json` | `checks[]`: `id`, `value`, `result` (pass, fail), `evidence`, `element`, `location`; optional `severity` (blocker, should), `screen`, `state`, `width`, `view`, `count` |
| `review.json` | `round`, `verdict` (done, revise); `findings[]`: `id`, `element`, `location`, `evidence`, `severity` 0-4, `priority` (must, should, could, wont) |
| `build.json` | `direction`, `round`, `page`, `widths[]`, `screens[]`: `id`, `file` (in 05-build/), optional `states[]`; optional `views[]` (see Prototype contract) |
| `showtell.json` | `doc_id`, `version`, `url` |
| `comments.json` | `doc_id`; `comments[]`: `number`, `version`, `body`, `element`, `state`, optional `replies[]` |
| `gate_<name>.json` | see Gates; no fields beyond these |
| `design-file.json` | `kind` (penpot, html-prototype), `location`, `editable` (true or false) |
| `followup.json` | `items[]`: `id`, `what`, `owner_role`, `source` |

Change a contract only together with the stage that writes the file, and keep the known case passing.

## Prototype contract

What stages 4 (directions) and 5 (build) must leave behind, so stage 6a can measure it and 6b can review
it. It is the seam between the stages that draw and the stage that judges; a prototype that follows it
can be opened view by view by script, and every measured failure can be named by screen, state and width.

- **One self-contained HTML prototype** per build, at `05-build/index.html` (a direction's draft at
  `04-directions/<id>/index.html`). Self-contained means it opens from `file://` or a plain static
  server with no backend: its own CSS and JS, its figures from the run's `03-ground/fixture.json`.
- **Screen roots** carry `data-screen="<inventory screen id>"`: the element that holds one screen of
  `03-ground/inventory.json`.
- **States** carry `data-view-state="loading|empty|normal|error|<inventory state>"` on the screen root or
  inside it. Never `data-state` or `data-st-state` below `html`/`body`: Show&Tell's state helper hides
  those elements, so a page that uses them goes blank for the owner.
- **A view opens by its hash**: `#<screen>/<state>` shows that screen in that state, from a cold load.
  `#<screen>` alone means its `normal` state.
- **Requirements**: every element that meets a requirement carries `data-req="R3 R7"` (ids from
  `01-request/requirements.json`, space-separated).
- **Actions**: every action of `inventory.json` carries `data-action="<action id>"` on the control that
  performs it, and the control shows visible feedback on click before any server reply (AGENTS.md
  Design checklist: "when i click on something there should be feedback that its been clicked even if
  backend hasn't responded yet").
- **Figures** (money, percent, count) come from `03-ground/fixture.json`, never invented.

`build.json` may name the views directly, which is the compatible extension a prototype that cannot
follow the hash convention needs (an older build, or a direction draft that opens its screens by
clicking):

```
"views": [{"screen": "overview", "state": "normal", "open": {"hash": "#overview/normal"}},
          {"screen": "positions", "state": "normal",
           "open": {"steps": [{"click": "[data-nav=\"positions\"]"}, {"wait": 400}]}}]
```

`open` is `{"hash": "#..."}`, or `{"steps": [...]}` of `{"click": "<css selector>"}`, `{"goto": "<url or
hash>"}` and `{"wait": <ms>}`. Without `views[]` the views are `inventory.json`'s screens x states x
widths, opened by the hash convention. `views[]` is optional, so an older `build.json` stays valid.

**A prototype that carries no `data-screen` mark at all does not claim this contract.** The checks step
still measures everything it can see (render, overflow, type, contrast, targets, focus, axe, hierarchy,
tokens, figures, integration) but cannot prove coverage, so each coverage check writes one Should row
saying so instead of a blocker per missing mark. This is what lets a prototype built before the contract
(the `rollcall-20261104` known case's draft A) be measured honestly rather than failed 64 times over.

## Gates

Two owner gates for now, direction and final (owner, 2026-11-04: "to gather information and maybe
taste"; to be encoded later so the workflow can run fully on its own). Each is a Temper gate node; the
answer is its gate response, JSON text:

```
{"choice": "a", "decided_by": "owner", "owner_words": "I like the direction of A better",
 "source": "owner in Design lead dialog 2026-11-05T00:38Z", "reason": "..."}
```

`choice` is a direction id at the direction gate, and `approve` or `changes` at the final gate (`changes`
also gives `comments`, the Show&Tell comment numbers the next build answers). `decided_by` is `owner` or
`design`; `owner_words` is required for the owner, verbatim, and refused for design. Nobody's answer is
invented: a missing, non-JSON or incomplete answer fails the gate. The step writes `gate_<name>.json` with
the answer plus:
- `prediction`: deterministic judge prediction (`{"choice": pred_choice, "matched": bool, "basis": "..."}`).
  For `direction`, uses `04-directions/directions.json`'s `recommended` field, else picks the direction with
  the fewest `should`/non-pass rows in `04-directions/<id>/checks.json` (tie-breaking to the first direction id).
  For `final`, reads `06-checks/round-<ws.round>/review.json` and `07-show/comments.json`, predicting
  `"approve"` iff `review.verdict == "done"` and 0 comments have `state == "open"`, else `"changes"`.
- `taste`: `"not-taste"` when `ws.mode == "fixture"` or `decided_by == "design"`; `"saved"` when
  `ws.mode == "real"` and `decided_by == "owner"`, appending a structured taste entry (timestamp, product,
  gate, choice, verbatim `owner_words`, `source`, `reason`, `prediction.choice`, `prediction.matched`) to
  `ws.path / "taste-owner.md"` (and `DESIGN_TASTE_FILE` when set in the environment).
Answer a gate with `POST /api/runs/<run>/approve/<node>` and body `{"response": "<the
JSON text>"}`, signed (`~/design-lab/tools/temper_call.py`).

## Known cases and fixture runs

A known case is a finished job frozen as each stage's real output, so each stage can be tested alone on
fixed inputs with known answers (AGENTS.md rule 16). It lives in
`~/design-lab/app-screen-workflow/known-cases/<name>/`, laid out like a workspace, plus `gates/` (the gate
answers really given) and `FREEZE.json` (`case`, `product`, `frozen_at`, `source`, and a sha256 per file).
A changed, missing or extra file fails `verify`, `pack` and every fixture step; a frozen case is never
re-frozen.

Known case 1, `rollcall-20261104`: the RollCall phone and desktop redesign of 2026-11-04 (Design
#170-#196). Its request is the owner's ask and his Show&Tell comments on option A with his dialog answers;
existing is the #170 audit (56 captures, measures, 6 journeys from the 12 findings); ground is the
shared fixture, direction A's design files and 17 screens x 5 states x 3 widths; directions are the quick
drafts A and B with the owner's pick (A); build is draft A after his comments and the gap screens;
checks are draft A's 15 check scripts re-run on a snapshot, with one Should finding from the one that
failed; show is his comments on Show&Tell `d_kgrxir5ezb`; handoff is the 13 screen specs and the
follow-ups RollCall and Frontend sent. RollCall's numbers are its invented sample book; no client or
private data. It was built by `build_rollcall_20261104.py` next to it.

A fixture run (the worker can't see Design's lab, so the host packs the case into the workspace first;
the workspace must be under `~/temper-ai/workspaces`, which runs mount):

```
python3 configs/design/bin/design_app_screen.py pack \
  --case ~/design-lab/app-screen-workflow/known-cases/rollcall-20261104 \
  --workspace ~/temper-ai/workspaces/<run folder>
python3 ~/design-lab/tools/temper_call.py POST /api/runs '{"workflow": "design_app_screen_v1",
  "workspace_path": "<run folder>", "inputs": {"product": "rollcall", "mode": "fixture"}}'
```

then answer both gates with `decided_by` `design` (a fixture answer is never the owner's). Every step
reports `valid: true`; the direction gate also reports `known_case_choice`, the owner's real pick, to
compare with. Costs $0: no model runs.

To add a known case: lay out a finished job's real outputs as a workspace under
`known-cases/<product>-<date>/`, with `06-checks/round-1/` and `gates/gate_direction.json`,
`gates/gate_final.json` (the answers really given, the owner's words verbatim with their source). Keep it
free of client or private data. Check each stage with `design_app_screen.py <step>` on a packed workspace,
then freeze it once:

```
python3 configs/design/bin/design_app_screen.py freeze --case <dir> --product <id> --source "<what it is>"
python3 configs/design/bin/design_app_screen.py verify --case <dir>
```

Write a builder script next to it, as `build_rollcall_20261104.py` is, so how it was made stays readable.

## Stage status

| Stage | Real stage | Task |
| --- | --- | --- |
| 1 intake | real; met its bar 2026-11-05, 3/3 runs on every case (Stage 1, Results) | #206 |
| 2 existing | real; see Stage 2, Results | #207 |
| 3 ground | real; met its bar 2026-11-05, round t4, 3/3 runs on every case (Stage 3, Results) | #210, #214 |
| 4 directions | real (fenced model directions draft + shared HTML/JS compiler + quick measured checks); met its bar 2026-11-07, 3/3 runs on `parcelly-clean` and 3/3 runs on `rollcall-20261104` with 0 blockers (Stage 4, Results) | #223 |
| 5 build | real (5a scaffold + 5b fenced model screen writer); met its bar 2026-11-06, 3/3 runs on `parcelly-clean` and 3/3 runs on `rollcall-20261104` with 0 Stage 6a blockers (Stage 5, Results) | #219, #221 |
| 6a checks | real (24 measured Playwright + axe + contrast + token checks); met its bar 2026-11-06 (Stage 6a, Results) | #216 |
| 6b review | real (fenced review over `checks.json`, contact sheet and rendered copy + deterministic `review -> build -> checks -> review` loop); met its bar 2026-11-07, 3/3 runs on `clean-parcelly`, `measured-inkflow`, and `taste-planted`, plus 2-round loop proof on `temper-dev` (Stage 6b, Results) | #222 |
| 7 show + W5 gates | real (deterministic single-file interactive Show&Tell bundle compiler, round-over-round line retention, targeted comment resolution, 4-rule `show_check.py`, deterministic gate prediction and owner taste encoding); met its bar 2026-11-07 on `temper-dev` (Stage 7, W5 & Stage 8, Results) | #224 |
| 8 handoff | real (deterministic per-screen Markdown specs `08-handoff/spec/<screen-id>.md`, `design-file.json`, `followup.json`, 6-rule `handoff_check.py`, and full 37-node end-to-end real run `3480264f` on `temper-dev`); met its bar 2026-11-07 (Stage 7, W5 & Stage 8, Results) | #224 |

## Tests

`python3 -m pytest -q tests/test_design_app_screen_contracts.py`: the known case passes every contract
and a whole fixture run; a broken copy of each file fails for its named reason; the gates refuse invented
or incomplete answers; a changed or extra known-case file fails the freeze check; the CLI refuses an
unknown step and a missing workspace; a real-mode stub fails loud. On spark it also verifies the frozen
case in the lab and that the repo copy matches it.

`python3 -m pytest -q tests/test_design_app_screen_intake.py`: intake's script checks, each with a good
and a bad fixed draft (mapping, verbatim substring, unsourced, invented number, ids, schema); a clean
draft becomes the final files with source lines from the items; a bad draft retries, then fails loud;
the collector on a plain request, Show&Tell comments and dialog answers (with fake servers); fixture mode
passes through; the grader's key, question, conflict and specifics counts, and a key point split over
two requirements on its item (met together; unmet when one part is gone); the trial workflow's nodes
equal the whole workflow's; the agent is fenced (no tools block, JSON-only draft).

`python3 -m pytest -q tests/test_design_app_screen_existing.py`: existing's script checks, each with a
good and a bad fixed draft (unknown capture, measure the capture lacks, a number the audit doesn't hold, a
number no ref shows, text not on the capture, a measured kind without its measure, a measure that
contradicts the claim, an orphan problem, an unknown screen or requirement, a suggestion field); a clean
draft becomes `journeys.json` and turns back into the same draft; journeys get the problems seen on their
screens; a bad draft retries, then fails loud; the product file loader and its refusals (no route or steps, a
width not in sizes, a login without an account, a checkout inside the repo, an unknown field); the measures' problem sides, totals and the
missing-value rule; the grader on a good run and broken copies (an unsupported number, a missing evidence
id, a claim on the clean twin, a missed planted defect, a failed capture), and a key held to its bar, not
to every entry; the trial workflow's nodes equal the whole workflow's; the agent is fenced (no tools, one
image, JSON only).

`python3 -m pytest -q tests/test_design_app_screen_ground.py`: the capability map read back with every
entry's kind, group and intent; the product file's ground entries and their refusals; the host's prep
(map, knowledge files, fixture and parts copied and recorded; a used workspace and a part named like a
fixture key refused); source items with one id each, seen words without the frame; collect writes the
sources, fixture check and task, and fails loud without the prep or on a fixture changed after it; the
invariants (one value per entity, totals, paths that reach nothing) and the fixture's states at any
depth; ground's script checks, each with a good and a bad fixed draft (invented id, unsourced state, page,
requirement, captured screen or knowledge line neither placed nor excluded, an excluded route or captured
screen, a missing base or action state, a named outcome drawn as a generic refusal, duplicate ids, a
screen citing nothing, a non-slug state, a suggestion field); an unreadable reply gets a revision task;
check then final write the inventory, the revised reply is the one checked last, and a broken invariant
fails the stage after the inventory is written; the grader on a good run, its key, planted measures and
final recheck; the trial workflow's nodes equal the whole workflow's; the agent is fenced (no tools, no
image, JSON only, a ceiling that holds RollCall's draft).

## Stage 1: intake

Intake turns the owner's words into requirements and open questions. Every later stage builds from
them, so a missed or invented requirement here spoils the whole run (RollCall's v2 round needed 7
comments and 2 dialog answers the first drafts had missed). Scripts do everything a script can (rule 17);
one fenced model step reads meaning.

| Step | Kind | Does |
| --- | --- | --- |
| host `collect` | script, on spark | the owner's words into `sources.json`: a request, Show&Tell comments (`--doc d_x[@versions]`, from `http://127.0.0.1:8650/api/docs/<doc>`: body verbatim, the element it is on as context), dialog answers (`--record dr-x[:question ids]`, from `~/.pi-web-ui/decisions/records.jsonl`: typed words and picked labels, the question as context), `history.json` from the product store if one exists (`--history`). Temper's workers reach neither the Show&Tell server nor the records, so this runs on the host. |
| `intake_collect` | script | checks the sources document (from `request_json`, or already in `01-request/sources.json`) against its contract and writes it; a plain `{"request", "source", "description"}` becomes one request item. Fails loud with no sources. |
| `intake_read` | model (`design_app_screen_intake_v1`, opus) | reads `sources.json`, writes `draft.json`: requirements (`item`, `owner_words`, `kind`, `means`, `maps_to`, `open_questions`) and questions (`about`, `question`, `why`, `choices`, `status`). Fenced: fixed input, a 10-point checklist (cover every item; split compound items; copy words exactly; add no scope, number or reason; ask with 2-4 choices instead of guessing; record his answers as answered questions; never pick a side in a conflict), JSON only. |
| `intake_check` | script | the measured checks below -> `check.json`; any problem -> verdict `retry` |
| `intake_revise` | model, only on `retry` | fixes exactly the problems in `check.json` (one revision) |
| `intake` | script | the same checks on the final draft -> `check-final.json`; clean: `requirements.json` and `questions.json`, each requirement's `source` line filled from its item (the model never writes one); any problem left fails the stage loud |

The measured checks (`intake_check.py`): schema (the draft's contract), ids (unique; every
`open_questions` id exists), unsourced (every requirement names an existing item; every question's
`about` and `answer_source` are items), not_verbatim (`owner_words`, and an answer, are exact parts of
the item's text), coverage (every item is in some requirement or question), invented (a requirement's
`means` and `maps_to` state no number that no source text, context, source line or the product's
description states).

Requirement kinds stay W0's contract (goal, feature, change, constraint, taste), which the frozen known
case uses; the task plan's screen/behaviour/rule/data split is carried by `maps_to` (the screen or part)
and `kind`.

### Bar (written before the first trial run)

Per run, on every case, on every one of 3 runs (rule 16): coverage 100%, invented 0, unsourced 0,
not_verbatim 0, the stage ends with a clean final output, and every point of the case's answer key is
met. Case C: at least 2 open questions, one on what is wrong today (or what nicer means), another on
which parts; 0 invented specifics (no design move or settings topic nobody said). Case D: an open
question about both conflicting items that names the conflict; 0 silent picks (a requirement on either
item that doesn't wait for that question).

The grader (`design_app_screen.py grade-intake --case DIR --workspace W`) measures all of it from the
run's files; no model judges. A key point is met when the requirements on its items together say, in
their `means` and `maps_to` (not his quoted words, which would meet it by copying), a term from each of
the point's groups: one requirement or several, since the stage splits a compound comment into one
requirement per ask (changed after round t1, hypothesis H1 below; at first it needed one requirement).

### Trial cases

In `~/design-lab/app-screen-workflow/known-cases/intake/<case>/`: `sources.json` (what the run gets) and
`expected.json` (the answer key, written before any run). `build_intake_cases.py` there rebuilds the
sources with `collect`. The owner's words stay in the lab, not in this public repo.

| Case | Sources | Key |
| --- | --- | --- |
| A `a-rollcall-v2` | his 7 comments on RollCall option A v2 (`d_kgrxir5ezb`) and his 2 dialog answers (`dr-6a0d81e7839b`) | 9 points, from what Design did with them: account figures (buying power, margin excess, net liq) instead of Safe, Analysis replaces Alerts, Analysis as today's analysis page, the full ladder to pick from, the premium line collapsible, no simulated labels, a real top, More lists every screen, Safe not useful |
| B1 `b1-inkflow` | his 3 comments on the Inkflow prototype (`d_3tur6fjfuq`) | 4 points: draft where the chat input goes, several reply options by lifecycle stage, client information such as lifecycle first, the page not only chat history. Design's own "2-4 options" and "7 stages" were its choices: stating them is invented |
| B2 `b2-showtell` | his 3 comments on the Show&Tell redesign v1 (`d_vpbz2ubipi`): "the page is empty", "i cant click on anything", both side panels collapsible | 3 points. The task plan put this doc under Inkflow; it is Show&Tell's own redesign, so it is its own case |
| C `c-vague` | planted request "make the settings page nicer" (RollCall) | 1 point (the settings page, nothing more); 2 questions (what is wrong today, which parts); 0 invented specifics |
| D `d-conflict` | A plus a planted comment "show simulated on every account", against his "we dont need to show simulated" | an open question about both naming the conflict; 0 silent picks; A's other 8 points |

A trial run: put the case's `sources.json` in as `request_json` on a fresh folder under
`~/temper-ai/workspaces/` (given as its full path, and open to the worker, which writes as another user:
`chmod 777`), run `design_app_screen_v1_intake` with `product` and `mode real`, then grade:

```
python3 ~/design-lab/tools/temper_call.py POST /api/runs @body.json   # {"workflow": "design_app_screen_v1_intake",
    # "workspace_path": "<folder>", "inputs": {"product": "rollcall", "mode": "real", "request_json": "<sources.json text>"}}
python3 configs/design/bin/design_app_screen.py grade-intake --case <case dir> --workspace ~/temper-ai/workspaces/<folder>
```

### Results

**Met the bar, 2026-11-05: every case, 3/3 runs, in a fresh round (t2) graded by the corrected
grader; 0 invented, 0 unsourced, 0 not verbatim, 100% coverage in all 30 runs.** Stage live as landed
in `47289ee9` (opus, one model call; the revision step never had to run: 30/30 first drafts were clean).
Cost about $0.10 (C) to $0.29 (A) a run, 16-74 s. Full run ids, grades and the broken-draft check:
`~/design-lab/app-screen-workflow/results/intake-trials/`.

**Round t1 (15 runs): 10 passed on the first grade.** All 5 misses were the grader, not the stage:

- A r2, B2 r1-r3: the stage split a compound comment into one requirement per ask ("things like buying
  power, margin excess net liq" into three; "both left and right collapsible panels ... so it doesn't
  overload the top" into panels and top), as its checklist says. The grader wanted one requirement
  holding every part of the key point.
- C r2, r3: the question "What about the settings page is not nice right now?" is N1 in other words;
  N1's word list had "nicer" but not "nice".

**H1 (written before the grader change).** Wrong: 5 of 15 runs fail a key point the drafts do meet
(evidence above, read in the drafts). Change: a key point is met by the requirements on its items
together, and N1 takes "nice". Expected: the same 15 runs re-graded pass 15/15 with no change in the
measured counts, and a fresh round on the unchanged stage passes 15/15. Wrong if: the looser grader
passes a draft that misses a point. Checked with 6 broken copies of real t1 drafts (A: two of the three
figures dropped; A and D: figures named but never as Safe's replacement; B2: "collapsible" dropped; B2:
"top" dropped; C: the what-is-wrong question removed): the corrected grader fails all 6. That check
found one more weak key term: A's and D's Safe groups held "margin", which the figure "margin excess"
met; they now need "safe" or "tile". Both key changes are dated in the cases' `expected.json`
(`amended`). **Hit:** t1 re-graded 15/15, t2 15/15.

Seen in the drafts, not a bar: the stage asks a lot (A: 6-9 open questions on 7 comments and 2
answers). Each is about a real gap and has choices, but the direction gate will need them bundled and
ranked before they reach the owner; that belongs to the stage that asks them.

| Round | Case | Run | Run id | Coverage | Invented | Unsourced | Not verbatim | Key | C: questions | D: conflict asked / silent picks | Reqs / open qs | First grade (t1) | Grade | Cost | Time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t1 | A | 1 | `2e2f7940` | 100% | 0 | 0 | 0 | 9/9 | - | - | 12 / 8 | pass | pass | $0.29 | 74s |
| t1 | A | 2 | `a868fe4c` | 100% | 0 | 0 | 0 | 9/9 | - | - | 13 / 8 | fail: K1 not met | pass | $0.29 | 71s |
| t1 | A | 3 | `0f7a98b7` | 100% | 0 | 0 | 0 | 9/9 | - | - | 11 / 9 | pass | pass | $0.28 | 73s |
| t1 | B1 | 1 | `8e782d51` | 100% | 0 | 0 | 0 | 4/4 | - | - | 6 / 6 | pass | pass | $0.23 | 58s |
| t1 | B1 | 2 | `c2f0c49e` | 100% | 0 | 0 | 0 | 4/4 | - | - | 4 / 5 | pass | pass | $0.20 | 46s |
| t1 | B1 | 3 | `e339b8e1` | 100% | 0 | 0 | 0 | 4/4 | - | - | 5 / 6 | pass | pass | $0.24 | 54s |
| t1 | B2 | 1 | `71b5e69d` | 100% | 0 | 0 | 0 | 3/3 | - | - | 4 / 3 | fail: K3 not met | pass | $0.14 | 30s |
| t1 | B2 | 2 | `3a25a2b5` | 100% | 0 | 0 | 0 | 3/3 | - | - | 4 / 3 | fail: K3 not met | pass | $0.15 | 31s |
| t1 | B2 | 3 | `a3a83b2d` | 100% | 0 | 0 | 0 | 3/3 | - | - | 4 / 4 | fail: K3 not met | pass | $0.14 | 30s |
| t1 | C | 1 | `2b4c37a6` | 100% | 0 | 0 | 0 | 1/1 | 2/2 | - | 1 / 3 | pass | pass | $0.10 | 19s |
| t1 | C | 2 | `0ba9c415` | 100% | 0 | 0 | 0 | 1/1 | 2/2 | - | 1 / 3 | fail: N2 not asked | pass | $0.10 | 16s |
| t1 | C | 3 | `f9bdeaf2` | 100% | 0 | 0 | 0 | 1/1 | 2/2 | - | 1 / 3 | fail: N1 not asked | pass | $0.10 | 17s |
| t1 | D | 1 | `091c7934` | 100% | 0 | 0 | 0 | 8/8 | - | 1/1 / 0 | 11 / 8 | pass | pass | $0.28 | 64s |
| t1 | D | 2 | `008f1e81` | 100% | 0 | 0 | 0 | 8/8 | - | 1/1 / 0 | 12 / 6 | pass | pass | $0.26 | 60s |
| t1 | D | 3 | `23fcae9c` | 100% | 0 | 0 | 0 | 8/8 | - | 1/1 / 0 | 12 / 6 | pass | pass | $0.24 | 54s |
| t2 | A | 1 | `65bf42dd` | 100% | 0 | 0 | 0 | 9/9 | - | - | 11 / 9 | - | pass | $0.27 | 66s |
| t2 | A | 2 | `25fc39e2` | 100% | 0 | 0 | 0 | 9/9 | - | - | 12 / 6 | - | pass | $0.29 | 65s |
| t2 | A | 3 | `79fe0a02` | 100% | 0 | 0 | 0 | 9/9 | - | - | 11 / 9 | - | pass | $0.27 | 68s |
| t2 | B1 | 1 | `ef58fdcf` | 100% | 0 | 0 | 0 | 4/4 | - | - | 4 / 6 | - | pass | $0.20 | 51s |
| t2 | B1 | 2 | `a2fa490d` | 100% | 0 | 0 | 0 | 4/4 | - | - | 5 / 6 | - | pass | $0.22 | 54s |
| t2 | B1 | 3 | `a45097e0` | 100% | 0 | 0 | 0 | 4/4 | - | - | 6 / 6 | - | pass | $0.21 | 51s |
| t2 | B2 | 1 | `909ad72e` | 100% | 0 | 0 | 0 | 3/3 | - | - | 4 / 3 | - | pass | $0.15 | 32s |
| t2 | B2 | 2 | `59c1d3f5` | 100% | 0 | 0 | 0 | 3/3 | - | - | 5 / 4 | - | pass | $0.15 | 31s |
| t2 | B2 | 3 | `e13e655e` | 100% | 0 | 0 | 0 | 3/3 | - | - | 4 / 4 | - | pass | $0.16 | 33s |
| t2 | C | 1 | `0c47c971` | 100% | 0 | 0 | 0 | 1/1 | 2/2 | - | 1 / 3 | - | pass | $0.10 | 19s |
| t2 | C | 2 | `68c41f09` | 100% | 0 | 0 | 0 | 1/1 | 2/2 | - | 1 / 3 | - | pass | $0.10 | 16s |
| t2 | C | 3 | `2d579327` | 100% | 0 | 0 | 0 | 1/1 | 2/2 | - | 1 / 3 | - | pass | $0.11 | 17s |
| t2 | D | 1 | `6e18c328` | 100% | 0 | 0 | 0 | 8/8 | - | 1/1 / 0 | 12 / 7 | - | pass | $0.28 | 67s |
| t2 | D | 2 | `991a9d97` | 100% | 0 | 0 | 0 | 8/8 | - | 1/1 / 0 | 12 / 6 | - | pass | $0.27 | 62s |
| t2 | D | 3 | `7ee57dfd` | 100% | 0 | 0 | 0 | 8/8 | - | 1/1 / 0 | 12 / 8 | - | pass | $0.28 | 62s |

Run ids are temper-dev execution ids (first 8 characters; full ids in the results folder). Cost: t1
$3.05, t2 $3.07. The revision step is proven by the pytest (a fixed bad draft), not yet by a live run,
since no live draft needed it.

## Stage 2: existing

Existing reads the product as it is today: it captures every screen and state at 1440, 390 and 320,
measures each capture by script, and has one fenced model call write the user journeys and the problems
in them. Every problem is tied to a capture and a measure or the capture's visible text. Later stages
design from this read, so a missed problem or an invented one spoils the redesign. In the hand-run
RollCall redesign (#170) this read found 23 of 26 phone screens wider than 320 px and the attention list
3.3 screens down; those findings drove the redesign.

| Step | Kind | Does |
| --- | --- | --- |
| host `capture` | script, on spark | `design_app_screen.py capture --product P --workspace W`: reads the product file, starts a throwaway copy (or a static folder), logs in, opens every screen x width x state look-only, measures it in the page and screenshots its first view. Writes `02-existing/captures/<screen>-<width>-<state>.png`, `raw.json`, `capture.json` (what was captured, what failed), `audit.json` (flat measures per capture, totals per width), `texts.json` (each capture's visible text), `app.json` (the screens) and `sheet.png` (the contact sheet). Workers reach neither the app nor a browser, so this runs on the host before the workflow. |
| `existing_collect` | script | checks the capture is there and complete, writes `task.md`: the product's job, the stage-1 requirements, every capture's measures with a `!` on each value on its problem side, the visible text, the totals |
| `existing_sheet` | script | passes `sheet.png` on as the model's one image (Temper's tool-free image input takes one PNG per call; a script's output is capped at 256,000 characters, so the sheet is kept under 180,000 bytes) |
| `existing_read` | model (`design_app_screen_existing_v1`, anthropic `claude-opus-5-5` on token label `roamee`, no tools, no temperature) | the sheet + `task.md` -> `draft.json`: journeys (name, goal, screens, steps, requirement ids, keep items with evidence) and problems (claim, severity 0-4, kind, evidence refs). Fenced checklist in the prompt: journeys from the job and the requirements, one goal per journey, a screen with its own job its own journey; each problem an observation with evidence, no suggestions; walk every state; Nielsen severity; name what works; cite refs of fixed shapes; never claim what a measure contradicts; state only numbers the refs show; JSON only |
| `existing_check` | script | the measured checks below -> `check.json`; any problem -> `retry` |
| `existing_revise` | model, only on `retry` | the same agent fixes exactly the problems in `check.json` (one revision) |
| `existing` | script | the same checks on the final draft -> `check-final.json`; clean: `journeys.json`, each journey with every problem seen on its screens (by the refs, a script fact, not the model's word); any problem left fails the stage loud |

A ref is one of `{"capture", "measure", "value"}`, `{"capture", "text"}` or `{"total": "<measure>@<width>",
"value", "of"}`. The checks (`existing_check.py`): schema; ids (unique, journeys name problems that exist,
requirement ids exist); screens (journeys name app screens); refs (the capture exists, the measure is the
capture's, the total exists); values (a measure ref's value equals the audit's exactly); texts (a text ref
is visible in that capture); unsupported (a problem cites no capture, or a measured kind cites none of its
kind's measures on the problem side); contradicted (a problem's measures of its kind all sit on the OK
side, or a keep item cites a problem-side measure); invented (a claim states a number none of its refs,
the capture's size, the screen sizes or a fixed threshold shows); orphan (a problem no journey names).
Which side of a line is a problem lives in one place, `existing_measures.PROBLEM_WHEN`, used by the task
text's `!` marks, the checks, the totals and the grader.

Measures per capture (`existing_measures.measures`, from `measure_in_page.js`): layout width and how much
wider than the screen; page height and screens tall; tab bar height and rows; content left in the first
view; text runs, runs under 12 and 16 px, sentence-length runs under 16 px, distinct sizes, smallest size;
tap targets under 24x24 (inline links excluded, WCAG 2.2 2.5.8); sideways-scrolling boxes and the widest
one's content and box width; cut text (ellipsis, clamp, clipping); always-open blocks; error messages
with no button or link beside them; page errors; each key region's top and screens down (regions named
in the product file); missing values (a dash where a sentence needs a value, "These numbers are from
—.").

### Product file

`~/design-lab/products/<product>/app.yaml`, checked by `product_app.py` (a broken file fails loud with
every problem): `product`, `name`, `job`; `app`: a `server` (repo, pinned commit, its own checkout
folder never inside the repo, loopback port, build commands, env, seed and serve commands, ready path)
or `static` (folder, port); `login` (form fields with `{account}`, submit, wait-for); `page` (the main
region, chrome regions, key regions, loading text, error selector, the delayed-API trick for loading
states); `sizes` (width -> height, phone or not); `sheet_width`; and `screens`, each with an `id`, a
`name`, a `route` or `steps` (`goto`, `follow_first_link`, `click_first` with a text pattern; anything
that would send, place, confirm, submit or delete is never clicked), its `states` (each with its account,
`what` and widths) and its `widths`. Step 4 adds reuse and skip.

RollCall's file pins commit `81117dd`, exported with `git archive` to `/tmp/app-screen/rollcall-81117dd`
(the repo itself is never touched), with a fresh SQLite database seeded by `rollcall dev seed` with the
invented QA books, throwaway keys beside the database, live trading off, on port 8174 (the plan said
8171, #170's port; Frontend's task chats now start RollCall on 8171 and 8172, so stage 2 keeps clear).
Never the live server, the owner's book or client data; tickets open, nothing is sent.

Reuse (rule 36): the capture, the in-page measurement and the measures are #170's tools
(`results/rollcall-mobile-redesign-20261104/current/tools/`: `capture.mjs`, `measure_in_page.js`,
`build_measurements.py`), made product-agnostic and moved into the stage; #170's folder is left as it
was, and the stage's modules are the one copy from now on. `capture_page` (live on temper-dev) is not
reused: it captures public pages through the Playwright MCP server with a cookie policy and occlusion
checks, and has no login, no click steps, no throwaway app and no per-state accounts, which every app
screen here needs.

### Bar (written before the first trial run)

Per run, on 3 of 3 runs per case (rule 16): capture 0 failed, every listed screen x width x state
captured; unsupported claims 0 (the final `journeys.json`, turned back into its draft, passes every
check again); case A: every measure in the measured key exact, key recall at least 15 of 17, journeys at
least 5 of 6 matched; case P: recall 6 of 6; clean twin: 0 problems at severity 2 or more, and any lower
one backed by a measure on its problem side.

The grader (`design_app_screen.py grade-existing --case DIR --workspace W`, `existing_grade.py`) measures
all of it from the run's files; no model judges. A key journey is matched one to one to a draft journey
that names one of its screens and holds one of its terms in its name or goal; a key problem entry is met
when the matched journey's problems together hold a term of every group (intake's H1 rule). A planted
defect is found when a problem cites a capture of its screens and either one of its measures on the
problem side, or its kind and one of its terms. Entries and defects missed within the bar are reported as
notes; only bar failures fail the run.

The grader was proven on broken copies of real drafts (`results/existing-trials/broken_copies.py`): an
unsupported number, a missing evidence id and a number no ref shows (P), and a claim on the clean twin
(C) each fail; the untouched copies pass.

### Trial cases

In `~/design-lab/app-screen-workflow/known-cases/existing/<case>/`: `requirements.json` (stage 1's
output the run gets) and `expected.json` (the answer key, written before any run; later key changes are
dated in its `changed`).

| Case | Product | Key |
| --- | --- | --- |
| A `a-rollcall` | RollCall at `81117dd` on the invented QA books, 26 screens and states, 56 captures | measured: #170's numbers (`measured.json` from its `measurements.json`): layout width of all 52 phone captures, 23 of 26 wider than 320, the roll ticket's strike list 821 px in a 356 px box, Overview's attention list 3.3 screens down at 390. Journeys and problems: the known case's `02-existing/journeys.json` (6 journeys, 17 problem entries) as must-term groups |
| P `p-planted` | Parcelly, a 4-screen static app (home, parcels, parcel, account, plus the parcels error state; 14 captures) built by `build_parcelly.py`, with one planted defect each: layout wider than 320 (account), 10 px body text (account), 18 px tap targets (parcels), the key status line clamped (parcel), the main status 3 screens down at 390 (home), an error with no recovery (parcels error) | recall 6 of 6 |
| C `c-clean` | Parcelly's clean twin: the same screens without the six defects | 0 problems at severity 2 or more |

A trial run: `results/existing-trials/trial.py` (`prep` runs the host capture into a fresh workspace,
`clone` copies a capture to re-run the model part on the same pictures, `start`, `wait`, `grade`); the
trial workflow `design_app_screen_v1_existing` runs the same nodes as the whole workflow.

Capture check against #170 (case A, first capture): all 56 captured, 0 failed, 3 min 14 s; layout width
equal on all 56; 23 of 26 wider at 320; the roll ticket's `pk-body` 821 of 356 px; Overview's attention
list 3.3 screens down at 390 (4.8 at 320, 1.6 at 1440). Drift only where the data or the clock moves:
the empty Overview, the alerts list's height, the system page's audit log.

### Results

**Met the bar, 2026-11-05: every case, 3/3 runs, in one fresh round (t7) on the landed config.** A: key
17, 17 and 15 of 17, journeys 6, 6 and 5 of 6, all 56 measures exact; P: 6/6 planted defects on every run,
no other findings; clean twin: 0 problems on every run; unsupported claims 0 and capture failures 0 on
all 9. Cost about $0.90 (A), $0.28 (P), $0.11-0.21 (clean) a run, 28-198 s, plus the host capture (A 3
min 14 s, Parcelly about 20 s). Seven rounds, 48 runs, $21.98 in all. Full run ids and grades:
`~/design-lab/app-screen-workflow/results/existing-trials/` (`runs.json`, `grades/`, `table.py`).

Captures: the host capture ran 3 times per case on fresh workspaces (A: `a-r1`..`a-r3`; P and C:
`p-r4`..`p-r6`, `c-r4`..`c-r6`, after H2-1), 0 failed each time, every measure in A's key exact each time.
Later rounds re-ran the model part on those same captures (`trial.py clone`), so each round's change is
the only thing that moved; H2-5's new measure was added by re-measuring the stored raw measurement
(`existing_host.remeasure`), no new browser run.

What each round changed, with its hypothesis (rule 20), written before the round ran:

- **t1, first build.** P 3/3. A 0/3: key 13-14 of 17, Alerts and Orders merged into one journey on all 3,
  the loading state's blank date (P11) missed on all 3. C 1/3: c-r2 and c-r3 raised real flaws that were in
  both Parcelly twins by my own mistake (Home's tip says "add a note" but no screen lets you; a parcel id
  shown as a tab; the arrival window in three formats).
- **H2-1 (the case, not the stage).** Wrong: the clean twin wasn't clean (evidence above, read in the
  drafts). Change: fix those three in both twins (an Edit notes button, three tabs, one window format);
  planted defects unchanged; recapture. Expected C 0 problems 3/3 and P still 6/6. Wrong if the model
  still raised severity 2+ on the fixed twin. **Hit** (t2: C 0, 0, 0; P 6/6 x3).
- **H2-2 (prompt).** Wrong: the prompt asked for "4 to 8" journeys, and the model joined jobs ("Review
  orders and alerts") to fit. Change: no count; one goal per journey, a goal joining two jobs with "and" is
  two journeys. Expected journeys 6/6 on 3/3. Wrong if journeys still merged. **Hit on journeys** (t3: 6/6
  x3), key 15, 14, 16.
- **G1 (grader bug, found in t3).** The grader failed a run for any single unmet key entry, stricter than
  the written bar (15 of 17, 5 of 6): a-r4 (15/17, 6/6) graded fail. Fix: a missed entry within the bar
  is a note, only a bar failure is a miss; t1 and t3 re-graded; the broken copies still fail.
- **H2-3 (prompt).** Wrong: P11 ("These numbers are from —." while loading) missed in 6 of 6 runs; the
  model seemed to skip non-normal states. Change: "walk every state too", naming them. Expected P11 3/3.
  Wrong if still missed. **Miss** (t4: 1 of 3). Learned: the model now read the loading captures (its
  keep items cite them) but judged the skeleton fine; the blank date is in the text as a lone dash and it
  didn't see it as missing. That is a measurable fact, so it went to a script.
- **H2-4 (script).** Wrong: problems seen on a journey's screen were often not named in that journey (the
  tab bar problem not in the Glance journey). Where a problem was seen is a fact of its refs (rule 17).
  Change: `existing_check.journey_problems` adds to each journey every problem with a ref to a capture of
  its screens. Expected more key entries met, none lost. Checked offline on all 9 A drafts so far
  (`rederive.py`): +1, +2 and +2 on three runs, none lost. **Hit.**
- **H2-5 (measure).** Change: a `missing_values` measure (a lone dash after a word that needs a value,
  such as "from", "of", "the"), marked in the task text like any measure. Flags only Overview's loading
  captures on A, nothing on P or C (7 test cases, including the false hit "rate of 6.25% — set your"
  the first version made). Expected P11 met 3/3. **Hit** (t5: 3 of 3). t5: P 3/3, C 3/3, A 2/3 (14,
  15, 15).
- **H2-6 (script) and G2 (key).** Wrong in t5: a problem citing a per-width total (23 of 26 wider at 320)
  reached no journey through H2-4; and two runs said "Orders opens with practice-broker explanations
  before the order list", the known case's "two practice-broker notices fill the first screen" in other
  words, which P9's second term group lacked. Change: a total ref counts as seen on every capture that
  total flags; P9's second group gains "opens on", "opens with", "before the order" (dated in the case's
  `changed`; a key change made after reading outputs, so stated here). Offline on t5: 16, 16, 15. **Hit.**
- **t6** on that config: P 3/3, C 3/3, A 1/3 (17, 14, 14): two runs put the Alerts screen among the
  screens of "See what needs me" ("What do I have to do today: rolls, closes..."), so the key's Alerts
  journey matched nothing and lost its two entries. Merges since H2-2: 4 of 12 runs, steady, not noise.
- **H2-7 (prompt).** Wrong: the goal never names alerts, yet the journey lists the screen. Change: every
  screen is in a journey whose goal is what that screen is for; a screen with a job of its own (a history,
  a log, settings) that a goal doesn't name is its own journey, not a stop on another. Expected Alerts
  matched 3/3 and A 3/3; P and C unchanged. Wrong if alerts still folded in. **Hit** (t7: an alerts journey
  in 3 of 3; A, P and C all 3/3).

Still missed within the bar, worth knowing: the roll ticket's long opening note (P9 in the roll journey)
is called jargon, not length, in most runs; a-r18 folded the roll ticket into "Act on what needs me"
(5 of 6 journeys). The revision step runs on most real drafts (first drafts had 1-7 problems, mostly a
number the refs don't show or a text ref cut short) and every revision came back clean.

The lead's look (cited captures): `~/temper-ai/workspaces/design207-a-r17/02-existing/journeys.json`
(A, 17/17) and `~/temper-ai/workspaces/design207-p-r14/02-existing/journeys.json` (P, 6/6), each problem's
`refs` naming its captures in `02-existing/captures/`.

Run ids are temper-dev execution ids (first 8 characters). Grades are by the grader as it stood from G1
on; t5's A rows are as first graded (before H2-6 and G2).

| Round | Case | Run | Run id | Capture failed | Unsupported | Result | Journeys / problems (sev 0/1/2/3/4) | Revised (first-draft problems) | Grade | Cost | Time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t1 | A | a-r1 | `d04b1d70` | 0 | 0 | key 14/17, journeys 5/6, measures exact (56) | 8 / 19 (0/4/11/4/0) | yes (2) | fail: key recall 14/17 | $0.82 | 156s |
| t1 | A | a-r2 | `c2b09323` | 0 | 0 | key 14/17, journeys 5/6, measures exact (56) | 8 / 17 (0/2/10/5/0) | yes (1) | fail: key recall 14/17 | $0.90 | 182s |
| t1 | A | a-r3 | `0923cfa2` | 0 | 0 | key 13/17, journeys 5/6, measures exact (56) | 8 / 17 (0/1/9/7/0) | yes (3) | fail: key recall 13/17 | $0.98 | 219s |
| t1 | P | p-r1 | `c02c07d9` | 0 | 0 | recall 6/6 | 5 / 6 (0/0/3/3/0) | yes (1) | pass | $0.28 | 66s |
| t1 | P | p-r2 | `361340f5` | 0 | 0 | recall 6/6 | 5 / 6 (0/0/3/3/0) | yes (2) | pass | $0.26 | 63s |
| t1 | P | p-r3 | `28f9bb54` | 0 | 0 | recall 6/6 | 5 / 6 (0/0/3/3/0) | yes (1) | pass | $0.26 | 59s |
| t1 | C | c-r1 | `887503f6` | 0 | 0 | severity 2+ 0 | 5 / 0 | yes (2) | pass | $0.21 | 50s |
| t1 | C | c-r2 | `7bc17ed7` | 0 | 0 | severity 2+ 1 | 6 / 1 (0/0/1/0/0) | yes (2) | fail: severe 1 | $0.25 | 61s |
| t1 | C | c-r3 | `b4d37606` | 0 | 0 | severity 2+ 1, low unmeasured 2 | 5 / 3 (0/2/1/0/0) | yes (2) | fail: severe 1, 2 lows unmeasured | $0.24 | 56s |
| t2 | P | p-r4 | `f5d714a2` | 0 | 0 | recall 6/6 | 6 / 6 (0/0/3/3/0) | yes (1) | pass | $0.27 | 61s |
| t2 | P | p-r5 | `29bdd985` | 0 | 0 | recall 6/6 | 5 / 7 (0/0/4/3/0) | yes (1) | pass | $0.31 | 79s |
| t2 | P | p-r6 | `078c7d8f` | 0 | 0 | recall 6/6 | 6 / 6 (0/0/3/3/0) | yes (1) | pass | $0.30 | 74s |
| t2 | C | c-r4 | `809359a7` | 0 | 0 | severity 2+ 0 | 5 / 0 | yes (2) | pass | $0.20 | 44s |
| t2 | C | c-r5 | `f6828eed` | 0 | 0 | severity 2+ 0 | 5 / 0 | yes (1) | pass | $0.20 | 46s |
| t2 | C | c-r6 | `270d7c47` | 0 | 0 | severity 2+ 0 | 5 / 0 | yes (2) | pass | $0.20 | 43s |
| t3 | A | a-r4 | `12723d7d` | 0 | 0 | key 15/17, journeys 6/6, measures exact (56) | 10 / 19 (0/2/11/6/0) | yes (3) | pass | $0.92 | 196s |
| t3 | A | a-r5 | `85c917e8` | 0 | 0 | key 14/17, journeys 6/6, measures exact (56) | 10 / 17 (0/2/11/4/0) | no | fail: key recall 14/17 | $0.49 | 128s |
| t3 | A | a-r6 | `13ffd021` | 0 | 0 | key 16/17, journeys 6/6, measures exact (56) | 9 / 17 (0/2/10/5/0) | yes (3) | pass | $0.82 | 161s |
| t4 | A | a-r7 | `86c396e8` | 0 | 0 | key 12/17, journeys 5/6, measures exact (56) | 8 / 20 (0/4/12/4/0) | yes (6) | fail: key recall 12/17 | $0.85 | 175s |
| t4 | A | a-r8 | `15c53493` | 0 | 0 | key 15/17, journeys 6/6, measures exact (56) | 10 / 18 (0/2/10/6/0) | yes (3) | pass | $0.92 | 197s |
| t4 | A | a-r9 | `0aa6b7c4` | 0 | 0 | key 13/17, journeys 6/6, measures exact (56) | 11 / 22 (0/2/16/4/0) | yes (1) | fail: key recall 13/17 | $0.86 | 166s |
| t5 | A | a-r10 | `7c4034a8` | 0 | 0 | key 14/17, journeys 6/6, measures exact (56) | 10 / 21 (0/3/11/7/0) | yes (7) | fail: key recall 14/17 | $1.06 | 239s |
| t5 | A | a-r11 | `86dca942` | 0 | 0 | key 15/17, journeys 6/6, measures exact (56) | 10 / 21 (0/3/14/4/0) | yes (3) | pass | $0.88 | 180s |
| t5 | A | a-r12 | `e9d6d81f` | 0 | 0 | key 15/17, journeys 5/6, measures exact (56) | 10 / 19 (0/3/11/5/0) | yes (1) | pass | $0.89 | 185s |
| t5 | P | p-r7 | `e8668b70` | 0 | 0 | recall 6/6 | 4 / 6 (0/0/3/3/0) | yes (2) | pass | $0.24 | 52s |
| t5 | P | p-r8 | `9d47ccdb` | 0 | 0 | recall 6/6 | 3 / 6 (0/0/3/3/0) | yes (1) | pass | $0.24 | 53s |
| t5 | P | p-r9 | `1fc9c79b` | 0 | 0 | recall 6/6 | 3 / 6 (0/0/3/3/0) | yes (1) | pass | $0.26 | 59s |
| t5 | C | c-r7 | `57a3b7d2` | 0 | 0 | severity 2+ 0 | 4 / 0 | no | pass | $0.09 | 23s |
| t5 | C | c-r8 | `b61403ba` | 0 | 0 | severity 2+ 0 | 3 / 0 | no | pass | $0.09 | 23s |
| t5 | C | c-r9 | `b51d369c` | 0 | 0 | severity 2+ 0 | 5 / 0 | no | pass | $0.10 | 26s |
| t6 | A | a-r13 | `c52a3bee` | 0 | 0 | key 17/17, journeys 6/6, measures exact (56) | 11 / 19 (0/4/10/5/0) | no | pass | $0.48 | 122s |
| t6 | A | a-r14 | `aeb5839c` | 0 | 0 | key 14/17, journeys 5/6, measures exact (56) | 8 / 20 (0/2/12/6/0) | yes (2) | fail: key recall 14/17 | $0.95 | 198s |
| t6 | A | a-r15 | `a2609a48` | 0 | 0 | key 14/17, journeys 5/6, measures exact (56) | 9 / 18 (0/2/13/3/0) | yes (5) | fail: key recall 14/17 | $0.96 | 207s |
| t6 | P | p-r10 | `e455912f` | 0 | 0 | recall 6/6 | 4 / 6 (0/0/3/3/0) | yes (2) | pass | $0.25 | 58s |
| t6 | P | p-r11 | `8c747d0b` | 0 | 0 | recall 6/6 | 3 / 6 (0/0/3/3/0) | yes (2) | pass | $0.28 | 65s |
| t6 | P | p-r12 | `965d76ef` | 0 | 0 | recall 6/6 | 3 / 6 (0/0/3/3/0) | yes (1) | pass | $0.25 | 58s |
| t6 | C | c-r10 | `a030615e` | 0 | 0 | severity 2+ 0 | 3 / 0 | no | pass | $0.09 | 21s |
| t6 | C | c-r11 | `81f47c63` | 0 | 0 | severity 2+ 0 | 5 / 0 | no | pass | $0.10 | 23s |
| t6 | C | c-r12 | `0f10c367` | 0 | 0 | severity 2+ 0 | 3 / 0 | no | pass | $0.10 | 25s |
| **t7** | A | a-r16 | `75538cde` | 0 | 0 | key 17/17, journeys 6/6, measures exact (56) | 10 / 22 (0/4/15/3/0) | yes (2) | **pass** | $0.94 | 198s |
| **t7** | A | a-r17 | `cfc81378` | 0 | 0 | key 17/17, journeys 6/6, measures exact (56) | 10 / 22 (0/2/13/7/0) | yes (5) | **pass** | $0.88 | 176s |
| **t7** | A | a-r18 | `1b6f35cc` | 0 | 0 | key 15/17, journeys 5/6, measures exact (56) | 9 / 22 (0/2/13/7/0) | yes (1) | **pass** | $0.92 | 194s |
| **t7** | P | p-r13 | `ea0a40d4` | 0 | 0 | recall 6/6 | 5 / 7 (0/0/4/3/0) | yes (1) | **pass** | $0.29 | 68s |
| **t7** | P | p-r14 | `1e1684c3` | 0 | 0 | recall 6/6 | 5 / 6 (0/0/3/3/0) | yes (1) | **pass** | $0.28 | 66s |
| **t7** | P | p-r15 | `ee311ef0` | 0 | 0 | recall 6/6 | 5 / 6 (0/0/3/3/0) | yes (1) | **pass** | $0.29 | 68s |
| **t7** | C | c-r13 | `ae3cc08d` | 0 | 0 | severity 2+ 0 | 4 / 0 | yes (2) | **pass** | $0.21 | 50s |
| **t7** | C | c-r14 | `e2bcae09` | 0 | 0 | severity 2+ 0 | 4 / 0 | yes (2) | **pass** | $0.21 | 48s |
| **t7** | C | c-r15 | `7e13e4e9` | 0 | 0 | severity 2+ 0 | 4 / 0 | no | **pass** | $0.11 | 28s |

Cost by round: t1 $4.19, t2 $1.48, t3 $2.23, t4 $2.63, t5 $3.86, t6 $3.45, t7 $4.13; all $21.98.


### Backlog (seen here, for later stages)

- Intake's A drafts carry 6-11 open questions. Many are designer decisions or are answered by the current
  app (what the analysis page holds, for example). The direction stage must answer those from evidence,
  from this stage's journeys and captures, and bring the owner only owner-only ones.
- Journeys now carry every problem seen on their screens (H2-4, H2-6), so product-wide problems (page
  wider than the phone, small text) appear in nearly every journey. That is true, but the direction stage
  should rank them by severity times reach once, not once per journey.
- The model reads words from the task text, not the small tiles; a screen whose problem is only visual
  (overlap, a hidden column) relies on the measures. A second image per call (a zoomed tile) needs
  Temper's image input to take more than one PNG.

## Stage 3: ground

Ground decides what the design must cover before any direction is drawn: the product's design files
(defined, partial or none), every screen with its states, what it shows and its actions, and one shared
sample-data fixture. It reads the product's own sources, so nothing the app already does is left out. In
the hand-run RollCall redesign, option A v3 missed whole screens and flows today's app has (RollCall's
audit rm-57e6ca43: the actions inbox, the ticket's market-shut and refusal states, partial fills, new
entries from the Screener, sign-out and sign-up, Settings' sections, the More pages left as one-line
stubs); they cost 13 gap tasks (#185-#197). Ground must catch those from the sources up front.

| Step | Kind | Does |
| --- | --- | --- |
| host `ground-prep` | script, on spark | `design_app_screen.py ground-prep --product P --workspace W`: packs the design files with `design_files.pack` (a product not in `configs/design/products.yaml` gets a manifest saying so, status `none`); reads the product's sources: the capability map (`git show <commit>:<path>` for a server app, a path relative to the product file for a static one, or `derive`, which runs `configs/epd/bin/capabilities.py` on the throwaway checkout) and its notes files; copies the product's shared fixture as it is (its file and its part files). Writes `03-ground/design-files/`, `03-ground/source/` (`pack.json`, `prep.json`: what was read, from where, with sha256), `03-ground/product/` (`capabilities.md`, `notes/`), `03-ground/fixture.json` and `03-ground/fixtures/`. Workers reach neither the lab nor the repo, so this runs on the host before the workflow, as stage 2's capture does |
| `ground_collect` | script | the design-file status from `design_files.inventory` on the pack; every source item with a stable id (`page:<route>`, `api:<METHOD path>`, `note:<file>#L<n>`, `screen:<id>` from stage 2 (its text lists the states stage 2 captured), `seen:<id>` (the words stage 2's captures of that screen show, every width and state, once each, the app's frame on half the screens or more left out; context since H3-3), `journey:<id>`, `req:<id>`); the fixture's invariant check -> `fixture-check.json`; `sources.json` and `task.md` for the model |
| `ground_read` | model (`design_app_screen_ground_v1`, anthropic `claude-opus-5-5` on token label `roamee`, no tools, no temperature) | `task.md` -> `draft.json`: screens (id, name, sources, what each shows, its states, its actions with their states) and `excluded[]` (a source left out, with the reason). Fenced checklist: place every page, API item and knowledge line or exclude it with a reason (dev-only, a test harness, an alias, internal); every stage-2 screen and every requirement placed; each screen's base states plus every data condition the sources name; each action's pending, done and error plus confirm, refused, retry, undo where the sources name them; cite only ids from the task; JSON only |
| `ground_check` | script | the checks below -> `check.json`; any problem -> `retry` |
| `ground_revise` | model, only on `retry` | the same agent fixes exactly the problems in `check.json` (one revision) |
| `ground` | script | the same checks on the final draft -> `check-final.json`; clean: `inventory.json` (widths from the product file, `data_needed` by script); then a failed fixture invariant fails the stage loud, as does any problem left |

The checks (`ground_check.py`): schema; ids (screen ids and action ids unique); invented (a cited id that
is no source item); unsourced (a screen, a shown fact, an action or a state beyond the base ones that
cites no source); coverage (every `page:` and `api:` item is cited by a screen, or sits in `excluded[]`
with a reason; every stage-2 screen and every requirement is cited); placed and excluded (an item both
cited and excluded); base states (every screen has loading, empty, error, partial and normal); action
states (every action has pending, done and error); named conditions (an outcome code a cited item names,
"refused with `locker_full`", is a state of the screen, state or action citing it: the code's words in
the state's name; since H3-2, below). Knowledge lines (`note:` items) count like pages and
API routes: each is cited or excluded with a reason (since H3-1, below; before it they were context).

`data_needed` (script): a state beyond the base ones is covered when a `states` field anywhere in the
fixture or its parts (a list of names or an object's keys) holds the same words (`stale-quote` ->
`stale_quote`); every other one is listed for build, as `<state>` on the screen or `<action id>: <state>`.
RollCall's fixture lists only the five base states, so every extra state there is `data_needed`.

Contract (compatible, rule 36): `inventory.json` keeps `design_files`, `screens[]` (`id`, `name`,
`states[]` of strings, `widths[]`, optional `spec`) and gains optional `source` (product, commit,
capability map, notes), `excluded[]` (`source`, `reason`), and per screen optional `sources[]`, `shows[]`
(`what`, `sources[]`), `actions[]` (`id`, `what`, `states[]`, `sources[]`) and `data_needed[]`. `shows`
is beyond the plan: the audit's first group (the account figures, a position row's facts, an alert's
details) is what a screen shows, not a state or an action, so it needs its own place. The known case
rollcall-20261104 keeps passing.

Product file additions (all optional, checked by `product_app.py`): `capabilities` (a path to the
capability map, or `derive`); `notes` (paths to other knowledge files that name states, such as RollCall's
`.temper/topics/testing.md`, which names the broker refusal, the timeout, the market shut, the brake, the
catch line and the working order); `fixture`: `file` (the product's shared fixture), optional `parts` (a
folder of part files, each added under its file name; a name already a key of the fixture fails loud) and
`invariants`: `same_value` (`key`, `field`: every object holding that key carries one value of that field
per key value, one spot price per symbol) and `totals` (`total`, `plus[]`, `minus[]` paths; `[]` in a path
sums over a list), checked over the fixture with its parts. The plan had a `builder` (run the product's
fixture script on a copy); it was dropped before the first trial because RollCall's real shared fixture
is not its builder's output: #170's `build_fixture.py` now writes sha256 `2c9dd1b3...`, while the
fixture the redesign used (and the known case froze, `7f178e10...5004`) was later edited by hand by the
gap tasks, with 17 part files beside it (`current/fixtures/`, merged the same way by `draft-a/build.py`).
Copying the fixture and its parts is what the product really uses (rule 36: no builder kind without a
real use). `from_api` (look-only GETs against the throwaway app) is not built either: no case needs it
yet, and the schema refuses it.

### Bar (written before the first trial run)

Per run, on 3 of 3 runs per case (rule 16): ground-prep and collect errors 0; invented 0 and unsourced 0
(the final `inventory.json`, turned back into its draft, passes every check again); every capability
page placed (a screen cites it, or it is excluded with a reason); case A: the rm-57e6ca43 key at least 90%
of its items on each run, and 100% of the pages; case P: 6 of 6 planted items; clean twin: 0 false gaps
and the fixture invariants pass; the design-file status exactly `design_files.inventory`'s answer
(rollcall none, temper partial, parcelly none; the brief guessed rollcall partial, but
`configs/design/products.yaml` holds no approved RollCall part and `~/rollcall/design` does not exist, so the
bar is the function's answer); RollCall's fixture copied byte-identical to the frozen `fixture.json` (sha256
`7f178e10...5004`), its invariants passing over the fixture and its 17 parts; Parcelly planted's invariants
failing on the planted parcel, the clean twin's passing.

The grader (`design_app_screen.py grade-ground --case DIR --workspace W`, `ground_grade.py`) measures
all of it from the run's files; no model judges. A key item is met when a screen whose id or name holds
one of the item's screen terms (any screen when it lists none) holds a term of every group of the item
in its text: name, shown facts, states, actions (id, what, states) and cited source ids. A planted item is
found by its own measure (below). A false gap on the clean twin is a planted item's measure firing, or a
screen citing no page, stage-2 screen or requirement. Items missed within the bar are notes; only bar
failures fail the run. The grader is proven on broken copies of real drafts before the trial rounds.

### Trial cases

In `~/design-lab/app-screen-workflow/known-cases/ground/<case>/`: `01-request/` and `02-existing/` (frozen
stage 1 and 2 outputs, copied into the run's workspace) and `expected.json` (the answer key, written before any run; later key changes are
dated in its `changed`).

| Case | Product | Key |
| --- | --- | --- |
| A `a-rollcall-v3` | RollCall at `81117dd`: stage 1 case A's requirements and questions (round t2), stage 2 case A's outputs (round t7), the capability map and the notes `testing.md`, `figures.md`, `contextual-help.md`, `alerts.md` at `81117dd` (110 items: 85 API, 25 pages) | the 25 pages, and RollCall's audit of option A v3 (rm-57e6ca43, copy in `rollcall-audit-rm-57e6ca43.md`) written out item by item with v3's stub screens: Today's figures, inbox and action kinds and flows; the ticket's market shut, stale quote, refused, timeout, brake, outside-rules and debit confirms, partial fill, new entries from Screener, Browse and Ladder; Positions' lanes, row facts and detail; Orders' unfinished entry groups; Alerts' details and deep link; the account menu, sign-in, sign-up, invite, the per-login Robinhood tab, glossary tips, keyboard; Settings' sections; Robinhood's filter, CSV and settings; the Screener's run, progress and exclusions; the More pages as real screens; 95 items, and the 19 pages a screen must cite (25 less `/dev/states`, `/load-check`, `/phone-check`, `/*`, `/recommendations`, `/logout`). Five items are named by no source the run gets (buy to close, the stale quote, the debit confirm, the partial fill, Ideas), so they are marked `unsourced`; the 90% bar (at most 9 misses) leaves room for them |
| P `p-planted` | Parcelly (stage 2's static app), with stage 2 case P's outputs, stage 2's requirements plus a planted R4, its capability map and fixture in `known-cases/ground/sources/parcelly-planted/`, and one planted item each: a page reached only by a URL (`/track/:code`), an action only in the API (`POST /api/parcels/{id}/redirect`), a data condition named in the code (`locker_full` on the locker request), a requirement for a new screen (returns), a dev-only page that must be excluded (`/dev/seed`), and one parcel with two statuses in the fixture (the invariant check must fail) | 6 of 6: a screen cites the URL-only page; an action cites the API-only action; a state holds `locker full` on the screen or action citing the locker request; a screen not in stage 2 cites the returns requirement and holds `return`; `/dev/seed` is excluded and cited by no screen; `fixture-check.json` fails on that parcel |
| C `c-clean` | Parcelly's clean twin: the same sources without the six planted items | 0 false gaps; invariants pass |
| design files | rollcall, temper, parcelly | status none, partial, none (`design_files.inventory`; a script case, no model) |

RollCall's fixture is #170's `current/fixture.json` with its parts in `current/fixtures/`; ground-prep
copies them. Parcelly's capability maps and fixtures are written by
`known-cases/ground/build_parcelly_ground.py`. The design-files case is `known-cases/ground/design-files/`
(`check.py` runs `design_files.inventory` per product against `expected.json`).

### Results

Runs on temper-dev through the stage-alone workflow `design_app_screen_v1_ground.yaml` (trial copies
`_d210`), with the runner `~/design-lab/app-screen-workflow/results/ground-trials/trial.py` (`prep` copies
the case's `01-request/` and `02-existing/` into a fresh workspace and runs `ground-prep`; `start`, `wait`,
`grade`, `cleanup`); grades in `results/ground-trials/grades/`, runs in `runs.json`.

Design-files case (script, no model): rollcall `none`, temper `partial`, parcelly-planted `none`,
parcelly-clean `none`: pass.

Round t1 (smoke, one run per case, before the rounds of three):

| Run | Case | Temper run | Bar | Key / planted / false gaps | Pages | Screens, actions, excluded | Cost, time |
| --- | --- | --- | --- | --- | --- | --- | --- |
| t1-a1 | A | `057a55a1` | fail | key 84/95 (88%) | 19/19 | 23, 91, 12 | $0.91, 299 s |
| t1-p1 | P | `87118a9f` | pass | planted 6/6 | 6/6 | 7, 12, 3 | $0.10, 32 s |
| t1-c1 | C | `6478ddbb` | pass | false gaps 0 | 5/5 | | $0.08, 28 s |

Invented, unsourced and collect errors 0 on all three; no revision needed; RollCall's fixture copied
byte-identical (`7f178e10...`) with its invariants passing; Parcelly planted's invariant failed on PX-2041
as planted (the run ends `failed` at `ground`, as the bar wants), the clean twin's passed.

t1-a1's eleven misses: four of the five unsourced items (buy to close, the stale quote, the debit
confirm, Ideas); the next open (a grader gap, G1 below); and six real ones: assignment watch (no
`assign` anywhere: the notes' "one call assigned away" became the state `settled`), Let it be called as
an action, a confirm on the inbox card's actions, the ticket's live price banner, fees on the ticket, and
the InfoTip / HelpText pattern. Two of those (fees, InfoTip) are named only by knowledge lines
(`contextual-help` L6, L9) that the draft never cited: it cited 64 of the 102 lines (testing 19/46,
figures 38/43, contextual-help 4/8, alerts 3/5), because the task called the notes context ("covering
every line is not needed") and the check did not count them.

G1 (grader, 2026-11-05): `ticket-next-open` lacked the source's own words for the next open (figures.md
L26 "The market opens again in N hours"); t1-a1's trade screen shows "Session line: open and closes at, or
opens again in" and was scored a miss. The key item gains `opens again` (dated in `expected.json`'s
`changed`). t1-a1 still fails with it: 85/95.

Hypotheses (rule 20):

- H3-1 (after t1-a1). Wrong: items named only in knowledge lines are dropped (fees, InfoTip; 38 of 102
  lines uncited), because notes are context that nothing counts. Change: knowledge lines become items to
  account for like pages and API routes: each one cited where it names something a screen shows, a state
  or an action, or excluded with the reason (`ground_sources.PLACED`/`EXCLUDABLE` gain `note`; the task's
  notes header, the reader's step 6 and its checklist say so); a measured check, not a prompt plea
  (stage 2's lesson). Expect: on A every one of the 102 lines cited or excluded after the check; fees and
  InfoTip placed on at least 2 of 3 runs; the key at least 87/95 on every run; invented and unsourced 0;
  P and C unchanged (Parcelly has no notes); A's cost up by less than a third. Wrong if: the lines are
  all accounted for but fees and InfoTip still missing (excluded, or cited without their words), or the key
  stays under 86/95.

Round t2 (H3-1, three runs per case):

| Run | Case | Temper run | Bar | Key / planted / false gaps | Pages | Screens, actions, excluded | Revised | Cost, time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t2-a1 | A | `ab7fc8b5` | fail | key 83/95 (87%) | 19/19 | 20, 69, 44 | yes | $1.79, 594 s |
| t2-a2 | A | `1d6b3846` | fail | key 84/95 (88%) | 19/19 | 21, 84, 45 | no | $0.91, 302 s |
| t2-a3 | A | `187ab0c3` | fail | key 85/95 (89%) | 19/19 | 24, 86, 45 | no | $0.99, 332 s |
| t2-p1 | P | `e6b1a153` | fail | planted 5/6 | 6/6 | 7, 11, 3 | no | $0.09, 34 s |
| t2-p2 | P | `1cb36aca` | fail | planted 5/6 | 6/6 | 7, 9, 3 | no | $0.09, 28 s |
| t2-p3 | P | `94fbafeb` | fail | planted 5/6 | 6/6 | 7, 9, 3 | no | $0.10, 39 s |
| t2-c1 | C | `67fa9162` | pass | false gaps 0 | 5/5 | 5, 8, 1 | no | $0.06, 26 s |
| t2-c2 | C | `745c0125` | pass | false gaps 0 | 5/5 | 5, 9, 1 | no | $0.07, 28 s |
| t2-c3 | C | `55fcc4aa` | pass | false gaps 0 | 5/5 | 5, 9, 1 | no | $0.08, 28 s |

Invented, unsourced and coverage problems 0 on every run; RollCall's fixture byte-identical with its
invariants passing; Parcelly planted's invariant failing as planted, the clean twin's passing.

H3-1: miss. Every knowledge line was now accounted for (33-34 of 102 excluded each run), but fees stayed
missing 3 of 3 (contextual-help L6 was cited on the overview, the roll ticket and the app frame without
the word) and InfoTip 2 of 3 (L9 cited on the glossary without its words, or excluded as "component
implementation"); the key fell to 83-85. Citing a line is not carrying what it names. Two new misses
showed instead: the broker timeout and the outside-rules confirm (3 of 3; t1-a1 had both): testing.md's
broker codes were cited on the overview only. The run that needed a revision cost twice as much ($1.79).
The sourced misses across t2: Let it be called 3/3, card actions' confirm 3/3, timeout 3/3, outside rules
3/3, fees 3/3, InfoTip 2/3, assignment watch 2/3, live price 1/3, hold shares 1/3. With four unsourced
items missed every run, the 90% bar leaves room for at most five sourced misses.

P's planted data condition (`locker_full`) was found 1 of 4 times over t1 and t2: three drafts drew the
locker request's refusal as a plain `refused`, losing which refusal it was.

- H3-2 (after t2, P). Wrong: an outcome the sources name by its code ("refused with `locker_full`") is
  drawn as a generic `refused`, so the designers never draw the full-locker message; t2-p1..p3 all did it.
  A source's code is a measurable fact, so a script measure, not a prompt line: `ground_sources`
  reads the codes an item's text names ("refused/rejected/fails/declined/denied/blocked with <code>", the
  code snake or kebab case), and a new check `named_conditions` sends back any cited item whose code no
  state of the screen, state or action citing it names (`locker_full` -> a state holding the words
  `locker` and `full`); the reader's checklist and the revision text say the same. Offline, on the t1/t2
  drafts it flags t2-p1..p3 (and t2-c3's `bad_password`, `notes_too_long`), and none of A's (A's sources
  name no such code). Expect: P planted 6/6 on 3 of 3 runs; C still 0 false gaps (its codes become
  states, which no false-gap measure counts); A unchanged by it. Wrong if: P still misses `locker_full`
  after the check (the revision fails to fix it), or C gains a false gap.
- H3-3 (after t2, A). Wrong: what today's screens show is lost before the model reads it. Stage 3 gets
  from stage 2 only the screen and state names (`app.json`) and the journeys, not the words the captures
  show (`texts.json`), though the brief names stage 2's outputs as inputs. The captures hold what the
  misses lack: the positions row's "Let assign" button and "assignment risk" lane, the roll ticket's
  "Any listed call, including off-rule choices" and "which of your rules disagrees". Change (one):
  `ground_collect` adds a `seen:<screen>` item per stage-2 screen: the screen's visible text runs over all
  its captures (every width and state), once each, without runs of the app's frame (on half the screens
  or more) or runs with no word (`ground_sources.seen`); citable context, not counted for coverage. The
  reader's step 2 says to carry each label, row fact, button and message into the screen that replaces
  it, in the app's own words. The task grows from 57,634 to 110,982 characters. Expect: assignment watch,
  Let it be called and the outside-rules confirm met on at least 2 of 3 runs; the key at least 86/95 on
  every run; invented and unsourced 0; A's cost up by less than half. Wrong if: any run's key stays under
  86/95, or those three items are not gained.

G2 (grader, 2026-11-05, set before t3): `action-let-it-be-called` gains `let assign`, the app's own label
for that flow (the positions row button in stage 2's capture). No t1 or t2 inventory holds the words, so
their scores do not change. H3-2 and H3-3 touch different cases (P/C codes; A has none), so round t3
measures both.

Round t3 (H3-2 and H3-3, three runs per case; A's keys with G3, below):

| Run | Case | Temper run | Bar | Key / planted / false gaps | Pages | Screens, actions, excluded | Revised | Cost, time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t3-a1 | A | `c35bebca` | pass | key 86/95 (91%; 84 before G3) | 19/19 | 23, 118, 49 | yes (first draft cut off) | $2.26, 699 s |
| t3-a2 | A | `8b14e522` | fail | run failed: both drafts cut off | - | - | yes (cut off again) | $2.36, 742 s |
| t3-a3 | A | `aa2522ac` | pass | key 86/95 (91%; 84 before G3) | 19/19 | 20, 113, 50 | yes (first draft cut off) | $2.26, 701 s |
| t3-p1 | P | `7d5cdcfe` | pass | planted 6/6 | 6/6 | 7, 11, 3 | no | $0.14, 48 s |
| t3-p2 | P | `2bdfaacf` | pass | planted 6/6 | 6/6 | 7, 11, 3 | no | $0.14, 47 s |
| t3-p3 | P | `4ca7209e` | pass | planted 6/6 | 6/6 | 7, 11, 3 | no | $0.16, 55 s |
| t3-c1 | C | `447db24e` | pass | false gaps 0 | 5/5 | 5, 11, 1 | no | $0.12, 40 s |
| t3-c2 | C | `a681b693` | pass | false gaps 0 | 5/5 | 5, 13, 1 | no | $0.12, 41 s |
| t3-c3 | C | `2127510c` | pass | false gaps 0 | 5/5 | 5, 9, 1 | no | $0.11, 38 s |

H3-2: hit. P found all six planted items on 3 of 3 runs (`locker_full` drawn as its own state on every
run, without a revision); C stayed at 0 false gaps; invented, unsourced and coverage 0 everywhere.

H3-3: miss on its own wrong-if (a run failed, and both readable runs scored 84/95 before G3), but its
target items came: Let it be called, the assignment watch and the outside-rules confirm were met on both
readable runs (0 of 3 in t2), and hold shares too. Two things hid the gain. (1) Every A first draft was
cut off mid-JSON ("Unterminated string" or "Expecting value" at 42,752-56,790 characters); each read cost
exactly $1.18, the price of the full 48,000-token ceiling, which holds thinking and reply together. The
revision then rewrote the whole inventory from nothing, doubling the cost ($2.26), and t3-a2's revision
was cut off too, so the run failed. (2) With the screens' words in front of it, the reader wrote the
settings connection in the app's own words ("Real money: Off: this server was started read-only",
"Sources: All 2 sources answered") instead of the capability map's "live flag, port status", which the
key's terms did not hold (G3). P and C cost about half as much again as in t2 ($0.11-0.16), for the
words read.

G3 (grader, 2026-11-05, after t3): `settings-live-flag` gains `read-only`, `read only` and
`settings-port-status` gains `sources answer`, the app's own words for those two in /settings'
Connection section (stage 2's capture: "Real money · Off: this server was started read-only", "Sources ·
All 2 sources answered at", "Did your sources answer?"), one for one with the capability map's
"Connection (broker kind, write-only credentials, live flag, port status)" (Broker, Keys, Real money,
Sources). "real money" is not added: it is the separate `settings-real-money` item's term. Rescored, t1 and t2
keep their scores (83-85/95); t3-a1 and t3-a3 go from 84 to 86/95.

- H3-4 (after t3, A). Wrong: the reader's ceiling cuts RollCall's inventory off. Evidence: 3 of 3 first
  drafts unreadable at 42-57 thousand characters, every read at the identical $1.18 (the full 48,000
  tokens), one revision cut off as well; a run that fails is a hard miss of the bar (errors 0). Change
  (one): the reader's `max_tokens` goes from 48,000 to 128,000, what the repository's other long Opus
  readers use (an unused ceiling costs nothing), and its timeout from 1,500 s to 2,400 s to match.
  Expect: every A first draft readable (no revision for a schema problem), every A run completes, each A
  run costs less than t3's $2.26 (one read instead of two), key at least 86/95 on every run; P and C
  unchanged (their drafts are far under the old ceiling). Wrong if: an A draft is still cut off, a run
  fails, or the key falls under 86/95 on any run.

Round t4 (H3-4; the fresh round that meets the bar, every case 3 of 3):

| Run | Case | Temper run | Bar | Key / planted / false gaps | Pages | Screens, actions, excluded | Revised | Cost, time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t4-a1 | A | `58feecf0` | pass | key 89/95 (94%) | 19/19 | 23, 127, 50 | no | $1.22, 376 s |
| t4-a2 | A | `7578e3f5` | pass | key 88/95 (93%) | 19/19 | 20, 130, 46 | no | $1.56, 494 s |
| t4-a3 | A | `f64f26e3` | pass | key 88/95 (93%) | 19/19 | 21, 135, 46 | no | $1.37, 432 s |
| t4-p1 | P | `f51b191b` | pass | planted 6/6 | 6/6 | 7, 10, 3 | no | $0.18, 62 s |
| t4-p2 | P | `6398f04c` | pass | planted 6/6 | 6/6 | 7, 10, 3 | no | $0.16, 58 s |
| t4-p3 | P | `7e05c8cb` | pass | planted 6/6 | 6/6 | 7, 10, 3 | no | $0.16, 55 s |
| t4-c1 | C | `92d2f4de` | pass | false gaps 0 | 5/5 | 5, 12, 1 | no | $0.11, 39 s |
| t4-c2 | C | `879dc438` | pass | false gaps 0 | 5/5 | 5, 10, 1 | no | $0.12, 40 s |
| t4-c3 | C | `7fbc2a0e` | pass | false gaps 0 | 5/5 | 5, 11, 1 | no | $0.11, 37 s |

Every run: ground-prep and collect errors 0, invented 0, unsourced 0, coverage 0 (236 of 236 required
source items placed on A, the final inventory rechecked clean); design files `none` as the key says;
RollCall's fixture copied byte-identical (`7f178e10...`) with its 4 invariants passing over the fixture
and its 17 parts; Parcelly planted's invariant failing on PX-2041 (each P run ends `failed` at `ground`,
as the bar wants), the clean twin's passing. Bar met on 9 of 9 runs. The round cost $4.99 in all.

H3-4: hit. Every A first draft read whole and passed the check without a revision; every run completed;
each A run cost $1.22-1.56 (t3: $2.26-2.36); the key rose to 88-89/95 (t3: 86). P and C stayed
at 6/6 and 0 false gaps, a few cents dearer than t3 (more thinking under the higher ceiling).

A's misses on t4 (notes, within the bar): the unsourced buy to close, debit confirm and Ideas on 3 of 3
and the stale quote on 2 of 3 (named by no source the run gets: the item text is from RollCall's audit,
not from the app at `81117dd`); the broker timeout 3 of 3 (testing.md names the broker codes, but the
reader puts them on the overview, not on the ticket); the ticket's fees 3 of 3 (contextual-help.md's
fee rule is general, not the ticket's); a position's upcoming events 2 of 3; the per-login Robinhood tab
1 of 3. These go to stage 4+ as known gaps of the sources, not of the stage: build checks them against
the audit itself.

Grader proof (`results/ground-trials/broken_copies.py t4-a1 t4-p1 t4-c1`, broken copies of these real
runs' files, `broken-copies.json`): 28 of 28 right. Each untouched copy passes; each broken one fails for
its named reason: A an invented source, an unsourced state, a dropped base state, a wrong design-file
status, `/orders` and `/glossary` uncited, a swapped fixture, the 4 largest screens dropped (53/95), the
actions dropped (38/95); P an invented source, an unsourced state, a wrong status and each of the six
planted items broken alone; C an invented source, a dropped base state, the three planted measures
firing, a screen citing nothing, a failing fixture.

Lessons (for later stages): a measurable fact the model misses becomes a script check that names it,
not a prompt line (H3-2: a named outcome code must be a state); give the reader the screens' own words,
not only their names (H3-3); a reader's token ceiling holds thinking and reply together, and a draft cut
off costs the whole ceiling twice (H3-4: same cost on every run was the tell).

## Reuse and tools (step 4)

Stages 2 and 3 learn the product, and every run redid them: about $0.9 and 3 minutes for existing and
$1.2-1.6 and 6-8 minutes for ground on RollCall. The owner, 2026-11-04 (m27185): "we should able to skip
stages if we have prior work done, i don't think we need to figure out what rollcall does again for
example, and may what tools exists". Step 4 (Design #214) keeps each product's proven stage outputs in a
store, decides by script before a run whether each of stages 2-3 is reused, re-run only for what changed
(delta) or run in full, and gives the stages a registry of the design tools that already exist (rule 36:
use them first).

Where it runs: the same split as stages 1-3 (workers reach neither `~/design-lab` nor the app).

| Step | Kind | Does |
| --- | --- | --- |
| host `prepare` | script, on spark, before the run | `design_app_screen.py prepare --product P --workspace W [--force existing,ground]`: reads the product's store, decides existing (reuse, delta, run) with its reason, copies the stored files into `02-existing/` and re-captures only the changed screens (delta) or captures in full (run); runs `ground-prep` fresh (it is cheap and host-only) and puts the stored ground into `03-ground/stored/`; writes each stage's decision into `run.json` |
| `existing_*` | script steps | reused: no model, no checks; the copied files are re-validated against the stage's contract and fail loud when broken. delta: the host re-captured the changed screens; the one `existing_read` runs over the merged audit (journeys span screens). run: as before |
| `ground_collect` | script | finishes ground's decision (the requirements are known only after intake): reuse when nothing to place is new; delta: the stored inventory, with citations of changed or removed sources taken out, is the base, and the task holds only the items still unplaced plus what changed on screens already placed, with one added input section, "Already placed, keep"; run: as before |
| `ground_check`, `ground` | script | delta: the reply's additions are merged into the base by script, then the full `ground_check` runs over the merged inventory (coverage over all items) and a kept check proves every base entry is unchanged (base lists are prefixes of the merged ones) |
| host `store` | script, on spark, after the run | `design_app_screen.py store --workspace W [--run ID]`: accepts only a completed stage whose final checks pass when re-run on the host (existing: `existing_check` over `journeys.json`; ground: `ground_check` over `inventory.json` and the fixture invariants); anything else is refused loud. Writes a new version (older ones stay), `current.json` and a `history.json` entry |

Modules, one job each: `product_store.py` (read, validate and write `~/design-lab/products/<product>/store/`),
`reuse.py` (fingerprint and decide; deterministic, no model), `reuse_host.py` (the host commands `prepare`
and `store`), `ground_delta.py` (ground's base, unplaced items, merge and kept check),
`tools_registry.py` with `configs/design/knowledge/tools.yaml`, and
`tests/test_design_app_screen_reuse.py`. `run.json` gains the stage statuses `reused`, `delta` and
`planned` and keeps each stage's `decision`, `reason`, `source_run` and `store_version`; the contracts are
extended compatibly (a delta reply's schema, `ground_additions`).

Store layout, beside `app.yaml`: `store/existing/v<N>/` holds `02-existing/` as the workspace had it
(captures, audit, texts, app summary, sheet, raw measurements, journeys, checks); `store/ground/v<N>/`
holds `03-ground/` (inventory, sources, fixture and parts, `source/`, `product/`, design files, checks).
Each version has a `source.json`: product, stage, version, the app file's sha256, the app commit (server)
or static folder, a sha per UI file and over all of them, a sha over the other files, a sha over the
screens, sizes and page block, the viewports, date, run id, workspace, workflow commit, the request's ids
and words, and for ground the existing version it was built on. `current.json` points at each stage's
version; `history.json` lists each stored request with its run id and every stage's status and reason.
Gate answers join when the gate stages are built.

Fingerprint: the product file's new optional `ui_globs` (RollCall `frontend/src/**`; Parcelly's static folder
`**`), hashed per file at the app commit (`git ls-tree`, the repo only read) or over the static folder, the
files outside the globs hashed together, and the product file's screens, sizes and page block.

Decisions:

- existing: reuse when a valid stored version exists and the fingerprint is unchanged. delta when only UI
  files changed and every changed file maps to screens: a static page by its route; a server file by its
  path's folder and file names matching a capability page's component (the stored sources), that page's
  route to the product file's screens, and the stored inventory's screens citing that page and a captured
  screen. Only those screens are re-captured and re-measured; the other screens' captures, audit entries
  and measures stay byte-identical. run when nothing is stored, the store is invalid, the screens, sizes
  or page block changed, a file outside the UI globs changed, a changed file maps to no screen, or on
  `--force`; the reason says which.
- ground: the product part follows the same rule (run for the same reasons). The request part changes with
  every request, so new requirements are always placed: citations of a requirement (or any placed item)
  whose words changed, and of removed items, leave the base; an entry left citing nothing leaves with them.
  reuse (no reader) only when nothing is unplaced, nothing changed on placed screens and the prep (capability
  map, notes, fixture, design-file status) is the stored one; else delta.
- intake and the later stages always run.

A reused existing keeps `journeys.json` byte-identical, including the requirement ids its journeys name, which
belong to the stored run's request (its ids and words are in the version's `source.json`). Nothing after stage
2 reads those links today (ground's journey items carry no requirement ids), and the proven ground runs read
journeys written for another request too; stage 5+ should link requirements through ground's placements.

Tool registry: `configs/design/knowledge/tools.yaml`, one entry per existing tool (id, path, job, inputs,
outputs, proven_on, owner, stages). `tools_registry.check()` fails on a missing path or field;
`stage_tools(stage)` lists a stage's entries; existing's and ground's task texts get them as the input
section "Existing tools; use before writing new code". Only directions and build will act on it; the section
is wired now.

### Bar (written before the first trial run)

Script (`tests/test_design_app_screen_reuse.py`): reuse when unchanged; delta when one route file changes (a
temporary git repository) re-captures only its screens and keeps the others byte-identical; run when forced,
when the stored contract is invalid, when the product file's screens change, and when an unmapped file
changes; ground's base, unplaced items, merge and kept check on fixed inventories; store refuses a failed run;
the registry fails on a missing path.

On temper-dev:

- RollCall, unchanged app, new request (stage 1 case A's round t2 r2 requirements, 12 items, whose words differ
  from the stored request's 11): existing reused, its files byte-identical to the store, $0 for the stage;
  ground delta places every new requirement: final check 0 problems (invented 0, unsourced 0, coverage 0),
  kept entries unchanged; the grade-ground key on the merged inventory at least 86/95 with pages 19/19; at
  least 90% of the requirements (11 of 12) placed on a screen the hand-written key expects; 3 of 3 runs,
  since the ground delta has a model in it.
- Parcelly delta: a copy of the clean twin (product `parcelly-delta`), stored from a full run, then one page
  changed (Account gains a "Saved addresses" card with an empty-state message). Existing re-captures only
  Account (3 captures); every other capture byte-identical to the store and their audit entries equal; the
  new message in the re-captured screen's words (`texts.json`); ground delta places the new state on Account
  (a state whose name holds "address"), final check 0 problems, kept unchanged; 3 of 3.
- Forced (`--force existing,ground`) on the unchanged Parcelly copy: both stages run in full, 1 run.
- Cost and time recorded, reused against full.

A miss gets a hypothesis here (rule 20); one change; only that is rerun.

### Trial cases

| Case | Store before | Request | Key |
| --- | --- | --- | --- |
| R `rollcall` | existing v1 from round t7 run `cfc81378` (workspace `design207-a-r17`), ground v1 from round t4 run `58feecf0` (`design210-t4-a1`), both at `81117dd` | intake t2 r2 (`25fc39e2`, 12 requirements) | `known-cases/reuse/rollcall-r2-placements.json`, below; grade-ground with `a-rollcall-v3` |
| D `parcelly-delta` | v1 from its own full run, v2 from the forced run | stage 2 case C's | Account re-captured alone, others byte-identical; a state holding "address" on Account |
| F forced | parcelly-delta v1 | the same | both stages `run` with reason forced |

Expected placements for the 12 requirements (written by hand before the runs, against the stored inventory's
screens): R1 the Safe tile is not useful -> overview; R2 buying power, margin excess, net liq -> overview; R3
no need to show simulated -> app-frame or overview; R4 the top looks off, R5 there's no top -> app-frame or
overview; R6 analysis instead of alerts -> app-frame, analysis or alerts; R7 look at today's analysis page ->
analysis; R8 other screens in More -> more or app-frame; R9 the premium summary not always present, R10
collapsible -> overview or app-frame; R11 see the full ladder, R12 and pick -> roll-ticket, actions or trade.
A requirement is placed on an expected screen when a screen in its set cites it (sources, shows, states or
actions).

Seeds: RollCall as above. `parcelly-planted`'s existing is seeded from its round t7 run; its ground cannot be
stored, by design: the planted parcel breaks a fixture invariant, so every P ground run ends failed, and the
store refuses it.

### Results

Round t1 (2026-11-05, worktree code through a mirror, trial workflow `design_app_screen_v1_reuse_d214` = the
committed existing and ground nodes; runner `~/design-lab/app-screen-workflow/results/reuse-trials/trial.py`,
grades in `grades/`). Every run met its bar; no hypothesis was needed.

| Run | Case | existing | ground | Measures | Cost | Time |
| --- | --- | --- | --- | --- | --- | --- |
| `e8759b57` | R | reused, 69 files byte-identical, $0 | delta, 12 unplaced | key 89/95, pages 19/19, placements 12/12, final 0 problems, kept 0 | $0.047 | see note |
| `8de91d2c` | R | reused, 69 identical, $0 | delta, 12 unplaced | key 89/95, pages 19/19, placements 12/12, 0 problems, kept 0 | $0.114 | see note |
| `878ba823` | R | reused, 69 identical, $0 | delta, 12 unplaced | key 89/95, pages 19/19, placements 12/12, 0 problems, kept 0 | $0.127 | see note |
| `1f6ec152` | R (timing) | reused, 69 identical, $0 | delta, 12 unplaced | key 89/95, pages 19/19, placements 12/12, 0 problems, kept 0 | $0.123 | 25 s (prepare 0.3 s) |
| `7e69ed01` | D0 full | run (nothing stored) | run | final 0 problems; stored as v1 | $0.343 (0.230 + 0.112) | 91 s (prepare 15 s) |
| `dde8d011` | F forced | run (forced) | run (forced) | both done; stored as v2 | $0.364 (0.246 + 0.118) | 99 s (prepare 15 s) |
| `c3f60c00` | D1 | delta: Account only | delta | 12 other captures identical, other audit entries equal, new words in texts, state `no-saved-addresses` on Account, 0 problems, kept 0 | $0.265 (0.224 + 0.042) | 63 s (prepare 4.4 s) |
| `4db30897` | D2 | delta: Account only | delta | the same | $0.273 (0.227 + 0.045) | 67 s (prepare 4.4 s) |
| `05064063` | D3 | delta: Account only | delta | the same | $0.291 (0.250 + 0.042) | 72 s (prepare 4.6 s) |

Round total $1.95 for 9 runs (one D0 start lost at once to a model-account error, $0, run again).

Reused against full, RollCall: stages 2-3 cost $0.05-0.13 and took 25 s, against about $0.9 and 3 minutes
(existing) plus $1.22-1.56 and 376-494 s (ground) when run in full (stages 2 t7 and 3 t4). Note: R1-R3's
`ground_read` waited 1 h 53 min on the model account's five-hour limit, so their wall time (6,800 s) is not
the stage's; R4 was run after it reset for the time.

What the runs showed:

- R's ground was a delta, not a reuse, for two true reasons the decision named: the new request (its 11
  ids R1-R11 carry new words, so their old citations left the base: 11 stale ids, 37 citations) and a
  changed prep: two fixture parts (`glossary`, `analysis_more`) in the draft-a folder changed since t4.
  Reusing would have kept an inventory built on old words. 17 of the 23 screens are byte-identical to the
  store; the other 6 differ only where the old request's citations left and the new ones were placed (the
  kept check, 0 problems, proves no other part of a stored entry changed).
- Parcelly delta re-captured the 3 Account views; 2 changed bytes (1440, 390) and 320 came out identical (its
  first view ends above the new card), and all 12 other captures stayed byte-identical. Ground had nothing
  unplaced; the 4-6 changed context items (Account's seen words, and journeys from the new `existing_read`)
  went to the reader, which put the new state on Account each time.
- An existing delta costs about what a full existing does ($0.22-0.25 on Parcelly), because its one
  `existing_read` reads the whole merged audit (journeys span screens). It saves the capture time only.
  Backlog: a journey-scoped read (only journeys crossing a changed screen) would cut it, if a later product
  makes that worth a hypothesis.

Stores after the round: `rollcall` existing v1 + ground v1 (seeds), `parcelly-planted` existing v1,
`parcelly-delta` v1 (D0) and v2 (F); all validate (`design_app_screen.py validate-store --product P`). The
Parcelly copy keeps its planted Account card (`known-cases/existing/apps/parcelly-delta/account.html`), so a
new `prepare` against v2 is a delta again. Tool registry: 21 entries, `check-tools` passes.

Landed in temper-ai `2ce846d9` (land 235-11cb76; pre-commit suite 1951 passed). Fixture run of the whole
workflow after the land: `873fd775`, all 19 nodes completed at $0 (gates answered as Design, the known case's
choices).

## Stage 4: directions

Stage 4 (`directions`, Design #223) generates two or three genuinely distinct, clickable HTML direction
prototypes (`04-directions/<id>/index.html`, `<id>` in `a`, `b`, `c`) for the product's primary entry
screens before `gate_direction`, measures each direction with deterministic quick checks
(`04-directions/<id>/checks.json`), and writes `04-directions/directions.json`. When Stage 5 (`build`)
runs after `gate_direction`, `build_scaffold.build_task(ws)` reads the chosen direction's `name`, `idea`,
and `04-directions/draft.json` screen layout and copy as the starting direction for all screens.

### How Stage 4 works (rule 17: fenced JSON draft + shared HTML/JS compiler + quick measured checks)

`directions` remains the final node of Stage 4 in `design_app_screen_v1.yaml` and
`design_app_screen_v1_directions.yaml` so `gate_direction` (`depends_on: [directions]`) works unchanged:

1. `directions_collect` (script, `design_app_screen_stage_v1`, `depends_on: [ground]`): in `fixture` mode
   returns `model: "no"`. In `real` mode reads `01-request/requirements.json`, `02-existing/journeys.json`,
   and `03-ground/{inventory.json,fixture.json,design-files/}`, selects the primary entry screens from
   `inventory.json` (`build_scaffold.select_entry_screens`, first 1-2 screens so directions focus on the
   opening experience), writes `04-directions/task.md`, and returns `model: "yes"`, `task`.
2. `directions_read` (fenced LLM agent `configs/design/agents/design_app_screen_directions_v1.yaml`:
   `anthropic / claude-opus-5-5`, `token: anthropic-2` (`roamee` slot), `tools: []`, no `temperature`,
   `max_tokens: 64000`, `total_timeout: 1800`, `condition: directions_collect.structured.model == "yes"`):
   outputs ONE JSON object (`04-directions/draft.json`, schema `directions_draft` in `contracts.py`) with
   2-3 distinct directions (`id` in `"a"`, `"b"`, `"c"`, `name`, `idea`, `screens[]` reusing the shared
   `BUILD_SHOW` / `BUILD_ACTION` / `BUILD_STATE` schemas from `contracts.py`).
3. `directions_check` (script, `design_app_screen_stage_v1`, `condition: directions_collect.structured.model == "yes"`):
   runs `directions_check.py` over `04-directions/draft.json`, reusing `build_check.validate_screen_draft_spec`
   for screen/state/show/field/action/copy rules (rule 36) plus Stage 4 direction rules. Writes
   `04-directions/check.json` (`verdict: "ok" | "retry"`), and on `"retry"` prepares `revise_task`.
4. `directions_revise` (same agent `design_app_screen_directions_v1`, `condition: directions_check.structured.verdict == "retry"`):
   one bounded revision pass fixing any reported problems.
5. `directions` (script, `design_app_screen_stage_v1`, `depends_on: [directions_revise]`): in `fixture`
   mode runs `run_fixture(ws, "directions")`. In `real` mode applies the revised draft if any, runs final
   `directions_check` -> `04-directions/check-final.json` (fails loud on any remaining problem), compiles
   each direction `<id>` into `04-directions/<id>/` (`index.html`, `styles/tokens.css`, `shell/router.js`,
   `screens/*.js`, `fixture.json`, `build.json`) via `build_scaffold.compile_direction_prototype`, runs
   quick measured checks (`directions.measure_direction_checks`, reusing `checks_rules.py` and `build_check.py`)
   to write `04-directions/<id>/checks.json` (`direction_checks` with 0 blockers), writes
   `04-directions/directions.json`, and validates `contracts.validate("directions", ws)`.

### Checks (`directions_check.py`) and planted faults

`directions_check.check_workspace(ws)` enforces 5 rule families over `04-directions/draft.json`:

1. `directions_draft_schema`: valid JSON matching `directions_draft` with at least 2 directions and unique
   slug ids (`a`, `b`, `c`).
2. `distinct_directions`: each direction has a distinct `name`, a distinct `idea`, and differs from the
   other directions in primary screen `layout` (`ledger`, `board`, `split`, `stack`, `detail`, `form`) and
   normal-state `headline`.
3. `entry_screen_coverage`: every direction covers all target entry screens and every required state
   (`normal`, `loading`, `empty`, `error`, plus any screen-specific state) with non-empty `headline` and
   `summary`.
4. `show_and_field_grounding`: every `shows[]` ref (`S1..Sn`) on an entry screen is covered and every
   `shows[].fields[]` path resolves in `03-ground/fixture.json`.
5. `state_and_action_quality`: distinct state headlines/summaries within each screen, exactly 1 primary
   action (`kind: "primary"`), at least 1 error-recovery action (`"error"` in `actions[].states`), no
   hardcoded figures (`build_check.has_hardcoded_figure`), and no banned filler copy
   (`build_check.has_banned_copy`).

All 15 planted faults are caught in `tests/test_design_app_screen_directions.py`:

| Planted fault | Mutation on `04-directions/draft.json` | Caught by | Message |
| --- | --- | --- | --- |
| `single_direction` | keep only 1 direction in `directions[]` | `directions_draft_schema` | `directions[] has 1 direction(s); at least 2 distinct directions are required` |
| `duplicate_direction_id` | set `directions[1].id = "a"` | `directions_draft_schema` | `duplicate direction id 'a'; each direction must have a distinct id ('a', 'b', 'c', ...)` |
| `duplicate_direction_name` | copy `directions[0].name` to `directions[1].name` | `distinct_directions` | `direction 'b' repeats name 'Morning Ledger Band' of direction 'a'` |
| `duplicate_direction_idea` | copy `directions[0].idea` to `directions[1].idea` | `distinct_directions` | `direction 'b' repeats idea of direction 'a'` |
| `duplicate_primary_layout` | set `directions[1].screens[0].layout` equal to `directions[0]` | `distinct_directions` | `direction 'b' primary screen layout 'ledger' duplicates direction 'a'; directions must use different layouts` |
| `duplicate_normal_headline` | copy `directions[0]` normal headline to `directions[1]` | `distinct_directions` | `direction 'b' normal-state headline ... duplicates direction 'a'` |
| `missing_entry_screen` | drop the second entry screen from `directions[1].screens` | `entry_screen_coverage` | `direction 'b' is missing target entry screen 'positions'` |
| `missing_required_state` | delete `error` state from `directions[0].screens[0].states` | `entry_screen_coverage` | `screen 'today' state 'error' is missing a non-empty headline or summary` |
| `missing_show_ref` | empty `directions[0].screens[0].shows` | `show_and_field_grounding` | `screen 'today' draft is missing shows[] refs ['S1']` |
| `ungrounded_field_path` | set `fields` to `["invented.nonexistent.field"]` | `show_and_field_grounding` | `draft field 'invented.nonexistent.field' on screen 'today' is absent from fixture.json` |
| `duplicate_state_headline` | copy `normal` headline into `loading` headline | `state_and_action_quality` | `screen 'today' state 'loading' repeats headline of state 'normal'` |
| `missing_primary_action` | change all actions on `today` to `kind: "secondary"` | `state_and_action_quality` | `screen 'today' has no primary action (kind='primary')` |
| `missing_error_recovery` | remove `"error"` from all `actions[].states` on `today` | `state_and_action_quality` | `screen 'today' has no error recovery action with 'error' in actions[].states` |
| `hardcoded_figure` | inject `"$500 across 12 contracts"` into `normal.summary` | `state_and_action_quality` | `hardcoded figure '$500' in ...states.normal.summary; bind figures via fields[] paths` |
| `banned_filler_copy` | inject `"TBD placeholder text coming soon"` into `shows[0].copy` | `state_and_action_quality` | `banned filler copy 'TBD' in ...shows[0].copy` |

### Results on temper-dev

Run on `temper-dev` through `design_app_screen_v1_directions.yaml` (runner
`~/design-lab/app-screen-workflow/results/directions-trials/temper_trial_4.py`, full results in
`~/design-lab/app-screen-workflow/results/directions-trials/summary.json`):

| Case | Run | Execution ID | Status | Draft / final problems | Revise | Directions (`id`: name / layout / views / blockers) | Cost | Time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `parcelly-clean` | 1 | `239b1ef4-596a-4641-8564-bff2e0acc458` | `completed` | 0 / 0 | skipped | `a`: Today First Stack (`stack`, 24 views, 0 blockers); `b`: Delivery Desk Split (`split`, 24 views, 0 blockers) | $0.0985 | 33.5 s |
| `parcelly-clean` | 2 | `7f6158e1-abe7-411d-af09-997c9adc2a44` | `completed` | 0 / 0 | skipped | `a`: Today First Stack (`stack`, 24 views, 0 blockers); `b`: Delivery Desk Split (`split`, 24 views, 0 blockers) | $0.0828 | 35.6 s |
| `parcelly-clean` | 3 | `84a4f499-0dec-40b1-9f72-24c781081a3a` | `completed` | 0 / 0 | skipped | `a`: Today First Stack (`stack`, 24 views, 0 blockers); `b`: Split Desk (`split`, 24 views, 0 blockers) | $0.0869 | 43.0 s |
| `rollcall-20261104` | 1 | `a3b97266-961b-4ea9-a3c2-22fea1f12b66` | `completed` | 0 / 0 | skipped | `a`: Tide Table Stack (`stack`, 30 views, 0 blockers); `b`: Friday Split (`split`, 30 views, 0 blockers) | $0.1219 | 41.3 s |
| `rollcall-20261104` | 2 | `3c6eca27-13db-4f96-bbe6-ab1e11a459ea` | `completed` | 0 / 0 | skipped | `a`: Tide Table (`stack`, 30 views, 0 blockers); `b`: Urgency Board (`board`, 30 views, 0 blockers) | $0.0822 | 39.5 s |
| `rollcall-20261104` | 3 | `e313a33d-bee9-475c-82c6-93fe126025b5` | `completed` | 0 / 0 | skipped | `a`: Tide Table (`stack`, 30 views, 0 blockers); `b`: Harbour Board (`split`, 30 views, 0 blockers) | $0.0781 | 34.9 s |
| Whole workflow (`fixture`) | 1 | `6e004623-be4d-4d62-bf84-c1c6e8590d11` | `completed` | 0 / 0 | skipped | 37 nodes (25 completed + 12 reader/reviser nodes skipped in fixture mode; gates `direction="a"`, `final="approve"`) | $0.0000 | 14.1 s |

## Stage 5: build

Stage 5 writes the prototype that Stage 6a measures and Stage 6b reviews. Because it is the largest stage in
`design_app_screen_v1`, it is split by rule 17 (deterministic steps first, a model only where judgement is
needed):

- **Stage 5a (Design #219, built):** everything a script can do. Reads `03-ground/` and `04-directions/`,
  validates all boundary inputs loud and fast (rule 36), writes the complete, contract-valid prototype
  skeleton into `05-build/` with a marked placeholder per screen (`data-build-placeholder="<screen-id>"`),
  and verifies the build with `build_check.py`. $0.00 model cost.
- **Stage 5b (planned):** the one model step that replaces each screen's `data-build-placeholder="<screen-id>"`
  region with the screen's real layout and words for the chosen direction, while keeping `build_check.py` and
  Stage 6a green.

### What Stage 5a reads and validates

`build_scaffold.validate_build_inputs(ws)` validates inputs at the boundary before writing anything
(rule 36, fail loud and fast) and raises `BuildInputError` naming the exact missing or malformed file or
field:

- `03-ground/inventory.json`: must exist, parse as a JSON object, name `design_files` (`defined`, `partial`
  or `none`), and carry a non-empty `screens[]` list with unique slug `id`s, non-empty `name`, non-empty
  `states[]` (slugs) and valid `widths[]`. It never invents a screen or a state.
- `03-ground/fixture.json`: must exist and parse as a non-empty JSON object holding the product's figures. It
  never invents a figure.
- `03-ground/design-files/tokens.json`: must exist and hold at least one colour, font or size token (`color` /
  `colours`, `font` / `fonts` / `typography`, `size` / `sizes` / `type`, `space`, `radius`, or
  `css_root_vars`); when `design_files` is `defined` or `partial`, `03-ground/design-files/DESIGN.md` must
  also be present and non-empty.
- `04-directions/directions.json` and `04-directions/gate_direction.json`: `directions.json` must hold at
  least two directions and each direction's quick checks (`04-directions/<id>/checks.json`) must exist; the
  chosen direction comes from `gate_direction.json`'s `choice` (or `directions.json`'s `chosen`) and must
  match one of `directions[].id`.
- `01-request/requirements.json` (when present): requirement `id`s (`R1...`) and `maps_to[]` screen mappings
  are read so every requirement mapped to a screen is wired onto that screen's `[data-req]` attributes.

### What Stage 5a writes

`build_scaffold.write_scaffold(ws)` writes a deterministic `05-build/` folder:

| File | Job |
| --- | --- |
| `05-build/index.html` | the prototype shell: links `styles/tokens.css`, loads `shell/router.js` and every `screens/<screen-id>.js` in inventory order, embeds `fixture.json` as `#rc-fixture-data` for offline `file://` and static HTTP serving, renders the global screen navigation (`href="#<screen>/<default-state>"`), and mounts the active screen inside `#rc-screen-host` |
| `05-build/shell/router.js` | hash router (`#<screen>/<state>`, `#<screen>` -> default state) that mounts exactly one `[data-screen]` root at a time and wires `[data-action]` click handlers so every action updates its `[data-action-feedback]` region immediately before any server reply |
| `05-build/styles/tokens.css` | CSS custom properties generated deterministically from `03-ground/design-files/tokens.json` (`--token-*` plus derived `--rc-bg`, `--rc-surface`, `--rc-fg`, `--rc-fg-muted`, `--rc-border`, `--rc-primary`, `--rc-primary-fg`, `--rc-focus`, `--rc-font-sans`, `--rc-font-mono`, `--rc-size-body`, `--rc-size-title`, `--rc-size-meta`), plus the responsive shell and placeholder layout rules |
| `05-build/screens/<screen-id>.js` | one self-contained module per inventory screen: registers `window.__APP_SCREENS__["<screen-id>"]` with the screen's `states`, `routes` (`#<screen>/<state>`), `regions`, `actions`, `req_fields` (fixture paths), `requirements` (`R...` ids) and `render(state, fixture)`. Renders `<section data-screen="<screen-id>" data-view-state="<state>" data-route="#<screen-id>/<state">`, state navigation links, regions, `[data-action]` buttons, `[data-req]` elements, and `<div class="rc-placeholder" data-build-placeholder="<screen-id>" data-placeholder-state="<state>">` reading figures at runtime from `fixture.json` |
| `05-build/fixture.json` | exact deterministic copy of `03-ground/fixture.json` as the single source of figures |
| `05-build/build.json` | `direction`, `round`, `page` (`"index.html"`), `widths` (`[1440, 390, 320]`), `screens[]` (`{id, file, states}`) and `views[]` (`{screen, state, open: {hash: "#<screen>/<state>"}}` for every screen x state) |

### Checks (`build_check.py`) and planted faults

`build_check.check_workspace(ws)` runs after `write_scaffold(ws)` and verifies 9 rules on `05-build/` before
`contracts.validate("build", ws)`:

1. `screen_file_per_inventory_screen`: every screen in `03-ground/inventory.json` has `05-build/screens/<id>.js`
   and an entry in `05-build/build.json`'s `screens[]`.
2. `shell_loads_every_screen_file`: `05-build/index.html` has a `<script src="screens/<id>.js">` tag for every
   screen and loads `shell/router.js`.
3. `view_per_screen_state`: `05-build/build.json`'s `views[]` has a view for every `screen x state` in the
   inventory.
4. `view_has_routing_target`: every `build.json` view has `open.hash == "#<screen>/<state>"` and that hash is
   registered in `screens/<screen>.js` and reachable from the shell.
5. `screen_has_data_screen_root`: every `screens/<id>.js` carries `data-screen="<id>"`, `data-view-state`,
   `data-build-placeholder="<id>"`, and never uses banned `data-state` or `data-st-state` attributes.
6. `routing_reaches_every_view`: `shell/router.js` listens to `hashchange` and every state of every screen has
   an `<a href="#<screen>/<state>" data-route-target="#<screen>/<state>">` link in `screens/<id>.js`.
7. `data_req_in_fixture`: every `data-req` token in `05-build/` either resolves in `05-build/fixture.json`
   (top-level key, dotted path or `slices.<state>`) or is a valid requirement id in
   `01-request/requirements.json`, and `05-build/fixture.json` matches `03-ground/fixture.json`.
8. `no_hardcoded_figures`: no money (`$1,234.56`), percent (`12.3%`) or formatted count (`1,234`, `12.34`)
   literal is hardcoded inside `05-build/screens/*.js` or `05-build/index.html` markup.
9. `tokens_from_product_file`: `05-build/styles/tokens.css` is linked by `05-build/index.html` and every expected
   `--token-*` custom property from `03-ground/design-files/tokens.json` has its exact value in `tokens.css`.

All six required planted faults are caught on the frozen `rollcall-20261104` build (`tests/test_design_app_screen_build.py`
and `~/design-lab/app-screen-workflow/results/build-trials/temper-results.json`):

| Planted fault | Mutation on `05-build/` | Caught by | Location | Message |
| --- | --- | --- | --- | --- |
| Screen file missing from inventory | delete `05-build/screens/positions.js` | `screen_file_per_inventory_screen` | `05-build/screens/positions.js` | `screen 'positions' in inventory.json has no screen file at 05-build/screens/positions.js` |
| `build.json` view with no routing target | set `views[0].open.hash` to `#today/unreachable-view` | `view_has_routing_target` | `05-build/build.json:views[0]` | `view (today/normal) open.hash is '#today/unreachable-view', expected '#today/normal'` |
| `data-req` naming a field absent from fixture | replace `data-req="today"` with `data-req="today.nonexistent_metric"` in `screens/today.js` | `data_req_in_fixture` | `05-build/screens/today.js` | `data-req 'today.nonexistent_metric' names a field absent from fixture.json` |
| Hardcoded figure in a screen file | inject `$148,320.00` into `screens/today.js` | `no_hardcoded_figures` | `05-build/screens/today.js` | `hardcoded figure '$148,320.00' in 05-build/screens/today.js; figures must come from fixture.json` |
| Screen with no `data-screen` root | remove `data-screen="today"` from `screens/today.js` | `screen_has_data_screen_root` | `05-build/screens/today.js` | `screen 'today' has no data-screen="today" root element` |
| State unreachable by `#<screen>/<state>` | change `href="#today/error"` to `href="#today/broken"` in `screens/today.js` | `routing_reaches_every_view` | `05-build/screens/today.js` | `state 'error' of screen 'today' has no #today/error link in 05-build/screens/today.js` |

### Results on temper-dev

Run on temper-dev through the stage-alone workflow `design_app_screen_v1_build.yaml` (trial mirror
`design_app_screen_v1_build_d219`, runner `~/design-lab/app-screen-workflow/results/build-trials/temper_trial.py`,
full output in `~/design-lab/app-screen-workflow/results/build-trials/temper-results.json`) against the frozen
`rollcall-20261104` ground + direction inputs (17 screens, 5 states each = 85 views, direction `a`):

| Run | Workflow | Mode | Outcome | Cost | Time | `05-build/` SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| `fd7d1d93` (`fd7d1d93-018b-4c91-91d2-ee9998a87720`) | `design_app_screen_v1_build` | `real` | `completed`; 22 files written, `build_check` 0 problems, contract valid | $0.00 | 0.34 s | `c72931f5ca0061cd74e70bd284f8f8f77def3e7348db42a40a8be3ced208be8a` |
| `0e5b11d1` (`0e5b11d1-3fca-4565-89ae-ce5dcc81e134`) | `design_app_screen_v1_build` | `real` | `completed`; all 22 files byte-identical to `fd7d1d93` | $0.00 | 0.57 s | `c72931f5ca0061cd74e70bd284f8f8f77def3e7348db42a40a8be3ced208be8a` |
| `1845c1f6` (`1845c1f6-8a30-49a9-bdbc-331c63634f2e`) | `design_app_screen_v1_checks` | `real` | `completed` over `fd7d1d93`'s `05-build/`; 255 views measured (17 screens x 5 states x 3 widths), 0 blockers, 0 shoulds | $0.00 | 733.0 s | - |

Stage 6a (`1845c1f6`) per-family rows over the Stage 5a skeleton (255 views = 17 screens x 5 states x 3 widths
`1440`/`390`/`320`), establishing Stage 5b's baseline:

| Family | Kind | Result | Failing rows | Severity | Evidence |
| --- | --- | --- | --- | --- | --- |
| `render` (`render.open`, `render.console`, `render.request`) | structural | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `contract` (`contract.marks`, `contract.screen`, `contract.state`, `contract.state_attr`) | structural | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `coverage` (`coverage.view`, `coverage.action`, `coverage.feedback`, `coverage.requirement`) | structural | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `figures` (`figures.invented`) | structural | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `integration` (`integration.duplicate_id`, `integration.dead_link`, `integration.two_screens`, `integration.handler`) | structural | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `overflow` (`overflow.layout_width`, `overflow.horizontal`, `overflow.element`, `overflow.truncated`, `overflow.label`) | layout baseline (5b) | `pass` | 0 | blocker / should | `no failure over 255 view(s)` |
| `type` (`type.floor`, `type.body`) | layout baseline (5b) | `pass` | 0 | blocker / should | `no failure over 255 view(s)` |
| `contrast` (`contrast.text`, `contrast.ui`) | layout baseline (5b) | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `targets` (`targets.size`) | layout baseline (5b) | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `focus` (`focus.ring`, `focus.none`) | layout baseline (5b) | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `axe` (`axe.violation`) | layout baseline (5b) | `pass` | 0 | blocker | `no failure over 255 view(s)` |
| `hierarchy` (`hierarchy.sizes`, `hierarchy.levels`, `hierarchy.primary`) | layout baseline (5b) | `pass` | 0 | should | `no failure over 255 view(s)` |
| `tokens` (`tokens.colour`, `tokens.font`, `tokens.size`) | layout baseline (5b) | `skipped` | 0 | should | `design_files: partial` in `rollcall-20261104/03-ground/inventory.json` (passes with 0 failing rows when `design_files: defined`, tested in `tests/test_design_app_screen_build.py`) |

### Stage 5b: fenced model screen writer and Stage 6a layout proof

Stage 5b (Design #221) completes Stage 5 (`build`) by adding the fenced model screen writer and deterministic
HTML/JS compiler that replace each screen's `<div class="rc-placeholder" data-build-placeholder="<screen-id>">`
with its real per-state layout, hierarchy, copy, action controls, and `fixture.json` figure bindings for the
chosen direction, while keeping `build_check.py` (all 14 rules: 9 from 5a + 5 from 5b) and Stage 6a (`checks`,
all 13 families across `1440`, `390`, `320`) green at 0 blockers.

#### How Stage 5b works (rule 17: fenced JSON draft + deterministic HTML/JS compiler + script checks)

`build` remains the first node of Stage 5 in `design_app_screen_v1.yaml` and `design_app_screen_v1_build.yaml`
so `review` (`loop_to: build`) and `gate_final_next` (`loop_to: build`) need no target change:

1. `build` (script, `design_app_screen_stage_v1`): in `fixture` mode copies the known case and returns
   `model: "no"`, `verdict: "ok"`, `problems: 0`. In `real` mode validates `03-ground/` and `04-directions/`
   (`build_scaffold.validate_inputs`), writes the base scaffold (`write_scaffold`), builds `05-build/task.md`
   (`build_scaffold.build_task`: chosen direction idea, `DESIGN.md` summary, token names, per-screen inventory
   `shows[]` with `S1..Sn` refs, `states[]`, `actions[]`, mapped `R...` requirements, available `fixture.json`
   field paths with sample types, and on round > 1 only the screens touched by open Must findings or owner
   comments), and returns `model: "yes"`, `task`.
2. `build_read` (fenced LLM agent `configs/design/agents/design_app_screen_build_v1.yaml`:
   `anthropic / claude-opus-5-5`, `token: anthropic-2` (`roamee` slot), `tools: []`, no `temperature`,
   `max_tokens: 128000`, `total_timeout: 2400`, `condition: build.structured.model == "yes"`): outputs ONE JSON
   object (`05-build/draft.json`, schema `build_draft` in `contracts.py`) with per-screen, per-state design
   specs: `layout` pattern, `headline`, `subhead`, per-state user-facing copy (`states.<state>.{title, summary,
   callout, badge}`), `shows[]` coverage cards (`{ref, title, summary, fields[]}` binding figures by
   `fixture.json` field path, never literal numbers in prose), `actions[]` (`{id, label, kind, feedback}` with
   at most one `"primary"` per screen), and `notes`.
3. `build_check` (script, `design_app_screen_stage_v1`, `condition: build.structured.model == "yes"`): parses
   `build_read.output` -> `05-build/draft-first.json` and `05-build/draft.json`, compiles the screens into
   `05-build/screens/<id>.js` via `build_scaffold.render_draft(ws, draft)` (replacing every
   `data-build-placeholder` with semantic, token-styled per-state sections `.rc-built-state`, `.rc-shows-grid`
   cards, `.rc-kv-band` key-value figure bindings resolved at runtime from `fixture.json`, and `.rc-callout`
   banners, plus visible `[data-req]` coverage on `.rc-screen__header`), and runs `build_check.py` with
   `require_5b=True` (all 9 Stage 5a rules PLUS 5 Stage 5b rules). Writes `05-build/check.json`
   (`verdict: "ok" | "retry"`), and on `"retry"` prepares `revise_task`.
4. `build_revise` (same agent `design_app_screen_build_v1`, `condition: build_check.structured.verdict == "retry"`):
   one bounded revision pass fixing the reported problems.
5. `build_finish` (script, `design_app_screen_stage_v1`, `depends_on: [build_revise]`): in `fixture` mode
   validates `05-build/` and writes `05-build/check-final.json`; in `real` mode applies the revised draft if
   `build_revise` ran, runs final `build_check.check_workspace(ws, draft=draft, require_5b=True)` ->
   `05-build/check-final.json` (fails loud on any remaining problem), and validates
   `contracts.validate("build", ws)`. In `design_app_screen_v1.yaml`, `checks` now `depends_on: [build_finish]`.

#### Stage 5b checks (`build_check.py`) and planted faults

In addition to the 9 Stage 5a rules, `build_check.check_workspace(ws, draft=draft, require_5b=True)` enforces 5
Stage 5b rules:

10. `no_placeholder_left`: zero `data-build-placeholder` attributes remain anywhere in `05-build/screens/*.js`
    or `05-build/index.html`.
11. `every_screen_state_designed`: every `screen x state` in `03-ground/inventory.json` has a non-empty state
    entry (`title` and `summary`) in `05-build/draft.json` and a compiled `data-state-panel="<state>"` section
    in `05-build/screens/<id>.js`.
12. `every_show_covered`: every `shows[]` item (`S1..Sn`, or `S1` when `shows` is empty) on a screen in
    `03-ground/inventory.json` is cited in that screen's `draft.json` `shows[]` with non-empty `title`,
    `summary`, and valid `fields[]`.
13. `single_primary_action`: at most 1 action has `kind: "primary"` per screen in `05-build/draft.json` and at
    most 1 `.rc-btn--primary` is rendered per screen in `05-build/screens/<id>.js`.
14. `no_hardcoded_figures` (draft + compiled JS) & `data_req_in_fixture` (draft `shows[].fields`): no money
    (`$1,234.56`), percent (`12.3%`) or formatted count (`1,234`, `12.34`) literal appears in any `draft.json`
    copy field (`headline`, `subhead`, `states.*`, `shows[].{title,summary}`, `actions[].{label,feedback}`) or
    compiled `05-build/screens/*.js`, and every field path in `shows[].fields` resolves in `05-build/fixture.json`.

All 5 new Stage 5b planted faults (11 planted faults total across 5a + 5b) are tested in
`tests/test_design_app_screen_build.py`:

| Planted fault (5b) | Mutation on `draft.json` / `05-build/` | Caught by | Location | Message |
| --- | --- | --- | --- | --- |
| Leftover `data-build-placeholder` | re-inject `data-build-placeholder="today"` into `05-build/screens/today.js` | `no_placeholder_left` | `05-build/screens/today.js` | `screen 'today' still contains data-build-placeholder in 05-build/screens/today.js` |
| Missing `shows[]` item | drop `S2` from `today`'s `shows[]` in `draft.json` | `every_show_covered` | `05-build/draft.json:screens[today].shows` | `screen 'today' draft is missing shows[] ref 'S2'` |
| Missing state design | remove `error` from `today`'s `states` in `draft.json` | `every_screen_state_designed` | `05-build/draft.json:screens[today].states` | `screen 'today' state 'error' is missing from draft states` |
| Two primary actions on one screen | set two actions on `today` to `kind: "primary"` | `single_primary_action` | `05-build/draft.json:screens[today].actions` | `screen 'today' has 2 primary actions in draft (at most 1 primary action allowed per view)` |
| Hardcoded figure in draft copy | inject `$148,320.00` into `today.states.normal.summary` | `no_hardcoded_figures` | `05-build/draft.json:screens[today]` | `hardcoded figure '$148,320.00' in draft copy for screen 'today'; bind figures via fixture.json fields instead` |

#### Stage 5b bar (written before trials, rule 16)

- Every planted fault in `build_check.py` (6 from 5a + 5 from 5b = 11) is caught by the right check.
- Case P (`parcelly-clean`, 4 screens, 16 screen-states = 48 views across `1440`, `390`, `320`,
  `design_files: "defined"` so Stage 6a `tokens.colour`, `tokens.font`, `tokens.size` run in full): 3/3 runs on
  temper-dev pass `build_finish` with 0 problems and 0 placeholders left, and Stage 6a (`checks`) over the
  built `05-build/` passes with 0 blocker rows and 0 should rows across all 48 views.
- Case A (`rollcall-20261104`, 17 screens, 85 screen-states = 255 views across `1440`, `390`, `320`): 3/3 runs
  on temper-dev pass `build_finish` with 0 problems and 0 placeholders left, and Stage 6a (`checks`) over the
  built `05-build/` passes with 0 blocker rows and 0 should rows across all 255 views.
- Whole-workflow fixture run (`design_app_screen_v1` in `fixture` mode) completes all 29 nodes at $0.00.

#### Hypotheses tested during Stage 5b calibration (rule 20)

- **Hypothesis H1 (first-pass `build_draft` schema compliance).**
  - *What was wrong and evidence:* On the first `parcelly-clean` probe run, `build_read` emitted `notes` as a
    JSON array of strings instead of a string and used `pattern` instead of `layout` on screen entries because
    `task.md` described the required keys in prose without an inline JSON example.
  - *One change and why:* Include a concrete one-screen `build_draft` JSON skeleton inside both
    `design_app_screen_build_v1.yaml` and `build_scaffold.build_task(ws)` showing the exact key names and scalar
    types (`layout`, `notes: "..."`, `shows[].{ref,title,summary,fields}`, `actions[].{id,label,kind,feedback}`).
  - *Expected result and measure:* `build_read` passes `contracts.validate_data("build_draft", draft)` on the
    first pass (`build_check` verdict `"ok"`, 0 retries) on 3/3 `parcelly-clean` and 3/3 `rollcall-20261104`
    runs.
  - *What would prove it wrong:* Any trial run failing `build_draft` schema validation in `build_check`.
  - *Outcome:* **Hit** — 6/6 trial runs (`parcelly-r1..r3`, `rollcall-r1..r3`) passed `build_draft` schema
    validation on the first pass (`build_revise` skipped on all 6 runs).
- **Hypothesis H2 (Stage 6a `tokens.font`, `hierarchy.sizes`, and `coverage.requirement` over model-built screens).**
  - *What was wrong and evidence:* On the initial `parcelly-clean` Stage 6a probe (`6dbc9e30`), Stage 6a
    reported 3 failures: (1) `coverage.requirement` on `home` (`R1`) because `R1` was declared on `home`'s
    action (`source: "req:R1"`) while `requirements.json` had `maps_to: []`, and `.rc-req-strip` used
    `sr-only` (`1x1 px`, invisible to `checks_measure.js`'s `visible(el)` check); (2) `tokens.font` because
    `tokens.json` defined `family: "Inter, system-ui, sans-serif"`, and when `Inter` is not installed locally
    Chromium resolves `getComputedStyle(el).fontFamily` to `system-ui`, which was absent from `tokens.css`; and
    (3) `hierarchy.sizes` (`4 > 3`) because `.rc-screen__title` (`24px`), `.rc-state-panel__title` (`18px`),
    body (`16px`) and meta (`13px`) created 4 distinct font sizes per view.
  - *One change and why:* (1) Map action `source: "req:R*"` onto the screen's requirements and place
    `data-req="<R...>"` on the visible `.rc-screen__header`; (2) append `, system-ui, sans-serif` to `--rc-font-sans`
    in `tokens.css` so the fallback font matches `tokens.css`; and (3) unify card/section headings onto
    `var(--rc-size-body)` (`16px` with `font-weight: 600`) so every view uses at most 3 distinct font sizes
    (`title`, `body`, `meta`).
  - *Expected result and measure:* Stage 6a `checks` reports 0 blockers and 0 shoulds across all 48 views of
    `parcelly-clean` (`design_files: "defined"`) and all 255 views of `rollcall-20261104`.
  - *What would prove it wrong:* Any `coverage.requirement`, `tokens.font`, or `hierarchy.sizes` row failing
    on `parcelly-clean` or `rollcall-20261104`.
  - *Outcome:* **Hit** — 0 blockers and 0 shoulds across all 3 `parcelly-clean` runs (48 views each) and all 3
    `rollcall-20261104` runs (255 views each).
- **Hypothesis H3 (empty `shows[]` in `inventory.json` + full `fixture.json` field coverage on 17-screen products).**
  - *What was wrong and evidence:* On `rollcall-20261104`, `03-ground/inventory.json` has `shows: []` on its
    screens and 90+ scalar paths in `fixture.json`. When `build_task(ws)` printed `S1..S0: (none)` and truncated
    available fixture paths at 60, `build_read` invented fixture paths for screens 8–17 (`orders`, `alerts`,
    `tickets`, `analysis`).
  - *One change and why:* When `shows` is empty on a screen, synthesize `ref S1` (`Primary overview and key
    figures for <screen>`) in `build_task(ws)` and include every screen's `default_fields` in the listed
    `Available Fixture Field Paths` instructing the model to copy paths from `Default fixture field paths for
    this screen`.
  - *Expected result and measure:* 3/3 `rollcall-20261104` runs pass `build_check` and `build_finish` on the
    first pass with 0 `data_req_in_fixture` or `every_show_covered` problems.
  - *What would prove it wrong:* Any `rollcall-20261104` run needing a retry or failing `build_finish`.
  - *Outcome:* **Hit** — 3/3 `rollcall-20261104` runs (`c533be4a`, `7d809d61`, `c97d2d44`) passed `build_check`
    and `build_finish` on the first pass with 0 problems.

#### Stage 5b results on temper-dev

Run on temper-dev via `~/design-lab/app-screen-workflow/results/build-trials/temper_trial_5b.py` (full output in
`~/design-lab/app-screen-workflow/results/build-trials/temper-5b-results.json`):

| Case | Run # | `build` execution id | `build` status | `build_finish` problems | `build` cost | `build` time | `checks` execution id | Views measured | Stage 6a blockers | Stage 6a shoulds | `checks` time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `parcelly-clean` (4 screens, 16 states, `design_files: defined`) | 1 | `d002f36d-267e-48d8-8f98-1eb06eb69a74` | `completed` | 0 | $0.0585 | 25.0 s | `fb6cf643-786d-40db-b6fd-f437e7a59ac3` | 48 (16 x 3 widths) | 0 | 0 | 145.6 s |
| `parcelly-clean` (4 screens, 16 states, `design_files: defined`) | 2 | `97aa4292-0718-4ab1-adef-e4f169de8011` | `completed` | 0 | $0.0574 | 21.8 s | `a1a9407f-2d62-4bf6-b27d-4dcffed3efbe` | 48 (16 x 3 widths) | 0 | 0 | 146.5 s |
| `parcelly-clean` (4 screens, 16 states, `design_files: defined`) | 3 | `bdadccae-cb15-4a76-b7a2-bb76df332f7d` | `completed` | 0 | $0.0590 | 22.9 s | `063358d3-3d6c-4a6c-af37-50c63718d36f` | 48 (16 x 3 widths) | 0 | 0 | 145.6 s |
| `rollcall-20261104` (17 screens, 85 states, `design_files: partial`) | 1 | `c533be4a-1d2c-48f9-9f4e-16089988073e` | `completed` | 0 | $0.2228 | 69.4 s | `b1a8af69-ae98-4679-8c6b-6c5e6caef564` | 255 (85 x 3 widths) | 0 | 0 | 714.2 s |
| `rollcall-20261104` (17 screens, 85 states, `design_files: partial`) | 2 | `7d809d61-19b8-4d4d-8326-53af66fb5f98` | `completed` | 0 | $0.2265 | 69.7 s | `dbf2232f-7ccc-42fc-bd77-046da88e4371` | 255 (85 x 3 widths) | 0 | 0 | 714.6 s |
| `rollcall-20261104` (17 screens, 85 states, `design_files: partial`) | 3 | `c97d2d44-ed2f-42df-96a5-8b46a6af137f` | `completed` | 0 | $0.2240 | 69.2 s | `3ba45019-89ce-4061-9cc6-951cc489ae80` | 255 (85 x 3 widths) | 0 | 0 | 716.4 s |
| Whole-workflow fixture (`rollcall-20261104`) | 1 | `d155d8d1-2646-4039-b60f-aadd9fbc843f` | `completed` (29/29 nodes) | 0 | $0.0000 | 10.0 s | (inside `d155d8d1`) | 85 (fixture `1440`) | 0 | 0 | - |

Stage 5b bar table:

| Bar | Measure | Target | Actual | Pass/Fail | Evidence |
| --- | --- | --- | --- | --- | --- |
| Planted faults in `build_check.py` (5a + 5b) | faults caught by exact check name | 11 / 11 | 11 / 11 | **PASS** | `tests/test_design_app_screen_build.py` (69 tests pass) |
| `parcelly-clean` Stage 5b `build_finish` | runs with 0 problems & 0 placeholders | 3 / 3 | 3 / 3 (`d002f36d`, `97aa4292`, `bdadccae`) | **PASS** | `05-build/check-final.json` (`verdict: "ok"`, `problems: []`) |
| `parcelly-clean` Stage 6a `checks` (all 13 families incl. `tokens.*`) | blocker rows / should rows across 48 views (`1440`/`390`/`320`) | 0 blockers, 0 shoulds on 3 / 3 | 0 blockers, 0 shoulds on 3 / 3 (`fb6cf643`, `a1a9407f`, `063358d3`) | **PASS** | `06-checks/round-1/checks.json` |
| `rollcall-20261104` Stage 5b `build_finish` | runs with 0 problems & 0 placeholders | 3 / 3 | 3 / 3 (`c533be4a`, `7d809d61`, `c97d2d44`) | **PASS** | `05-build/check-final.json` (`verdict: "ok"`, `problems: []`) |
| `rollcall-20261104` Stage 6a `checks` | blocker rows / should rows across 255 views (`1440`/`390`/`320`) | 0 blockers on 3 / 3 | 0 blockers, 0 shoulds on 3 / 3 (`b1a8af69`, `dbf2232f`, `3ba45019`) | **PASS** | `06-checks/round-1/checks.json` |
| Whole-workflow fixture run (`design_app_screen_v1`) | nodes completed & model cost | 29 / 29 nodes, $0.00 | 29 / 29 nodes, $0.00 (`d155d8d1-2646-4039-b60f-aadd9fbc843f`) | **PASS** | `temper-5b-results.json` (`whole-workflow-fixture`) |

## Stage 6a: checks

The `checks` step, model-free: it opens every view of the round's build in a real browser and measures it,
writing one `06-checks/round-<n>/checks.json`. Stage 6b (the review) reads those measured facts first, so a
model judges taste and language only, never what a script can measure (AGENTS.md rule 17). $0 of model cost.

**Where it runs.** Inside the Temper run, in the worker, like the Design role's other capture: the worker
serves `05-build/` over HTTP on its own address and drives temper's `playwright-mcp` service
(`http://playwright-mcp:8931/mcp`). `configs/design/bin/design_capture.py`'s `serve`, `run`, `result`,
`FOCUS_FN`, `AXE_TAGS` and its axe build are imported, not copied; the in-page measuring is
`design_measure.js` (contrast, targets by WCAG 2.5.8 in full, reflow, type styles, graphics without a name)
and `app_screen/measure_in_page.js` (truncation, the type histogram, visible text runs), both as they are.
`app_screen/checks_measure.js` is new and holds only what neither measures: the contract marks, the figures
in the rendered text, token use, the hierarchy counts and labels that split.

**What it opens.** `checks_views.py` builds the view list from `05-build/build.json`'s `views[]` when it has
one, else from `03-ground/inventory.json`'s screens x states x the build's widths, opened by the hash
convention (Prototype contract). Every view is measured at every width; focus order and action feedback are
walked once per screen and state, at the widest width, because a Tab walk and a click per action at every
width buys nothing and costs minutes.

**The checks.** `checks_rules.py` turns measures into rows: one row per failing element, plus one summary row
per check per view. Each row is `{id, value, result, evidence, element, location}` with `severity`
(`blocker` or `should`), `screen`, `state`, `width` and `view`.

| id | what it measures | severity |
| --- | --- | --- |
| `render.open` | the view opened and drew | blocker |
| `render.console` | a console or page error while opening the view | blocker |
| `render.request` | a request the page made that failed (404, refused). The browser's own favicon request is answered by the harness, so a prototype is never judged for it | blocker |
| `contract.marks` | no view carries a `data-screen` root, so the contract checks cannot be read | blocker |
| `contract.screen` | the visible screen is not the one the view opened | blocker |
| `contract.state` | the view's state is not what `data-view-state` says | blocker |
| `contract.state_attr` | `data-state` or `data-st-state` below `body`, which the Show&Tell helper hides | blocker |
| `coverage.view` | every inventory screen x state is present and opens | blocker |
| `coverage.action` | every inventory action has a `data-action` element | blocker |
| `coverage.feedback` | that element answers a click visibly, before any server reply | blocker |
| `coverage.requirement` | every requirement mapped to a screen has a visible `data-req` element at every width | blocker |
| `overflow.layout_width` | the layout viewport is wider than the screen (the page widened itself) | blocker |
| `overflow.horizontal` | the page scrolls sideways | blocker |
| `overflow.element` | an element past the viewport that no scrolling box clips | blocker |
| `overflow.truncated` | text cut by ellipsis, clipping or line-clamp | blocker |
| `overflow.label` | a control label wrapped onto a second line although its row has the room to show it on one line | should |
| `type.floor` | visible text below the product's floor (12 px) | blocker |
| `type.body` | a sentence-length run in the body below the body size (16 px) | should |
| `contrast.text` | text below WCAG 2.2 AA 4.5:1 (3:1 large), on its computed background | blocker |
| `contrast.ui` | a field or control boundary below 3:1 (1.4.11) | blocker |
| `targets.size` | a target under 24x24 that the spacing exception does not save (2.5.8) | blocker |
| `focus.ring` | a Tab stop with no focus ring (2.4.11, 2.4.7) | blocker |
| `focus.none` | nothing takes focus on a screen that has controls | blocker |
| `axe.violation` | axe-core 4.13.0, WCAG 2.0-2.2 A/AA rules | blocker |
| `hierarchy.sizes` | more than 3 text sizes in one view | should |
| `hierarchy.levels` | more than 3 text contrast levels in one view, counted by strength against the background (12:1, 7:1, 4.5:1, 3:1), not by hue | should |
| `hierarchy.primary` | more than one solid primary action in one view | should |
| `tokens.colour`, `tokens.font`, `tokens.size` | a colour, font or size that `tokens.json` does not hold (only when `inventory.json` says `design_files: defined`) | should |
| `figures.invented` | a money, percent or count in the rendered text that `fixture.json` does not hold or derive | blocker |
| `integration.duplicate_id` | the same element id twice, which breaks hash opening and labels | blocker |
| `integration.dead_link` | a link to a view the build does not have | blocker |
| `integration.two_screens` | two screen roots visible at once | blocker |
| `integration.handler` | a `data-action` control the click could not reach | blocker |

Blocker rows are 6b's Must input, Should rows its Should input; 6b still rates and may demote with a reason,
but it may not invent a measured fact. Thresholds live in `app_screen/checks_thresholds.json`, frozen before
the first run: the AA ratios 4.5 and 3.0 are the same numbers `design_page_checks_thresholds.json` uses, the
type floors come from the Design checklist ("body, messages and inputs 16px or more ... 12px floor only for
uppercase eyebrows"), and the hierarchy limits from the notebook ("max 3 text sizes + 3 contrast levels per
view", "one solid primary per view"). They are never loosened to make a case pass.

**Figures.** A figure is a money token (`$1,234.56`), a percent (`12.3%`) or a number with a thousands
separator or two decimals. It passes when `fixture.json` holds a number it matches after rounding to the
decimals shown, or one of the derivations the step allows (absolute value, x100 or /100 for a ratio shown as
a percent, /1,000 for `k`, /1,000,000 for `M`), or when the figure's exact text sits in one of the fixture's
strings. Dates, times, ordinals and bare counts under 100 are not figures. The tolerance follows the
decimals shown, as `checks_pattern/check-integration.mjs` does it.

### Bar (written before the first trial run)

- **Planted:** 100% of the planted faults caught, by the right check id, at the right screen and width.
- **The real-prototype case** (`c-inkflow-onboarding`, see "Trial cases"): 0 blocker rows that a hand read
  finds false; every failing row read and recorded as real or false.
- **Deterministic:** 3 runs give identical `checks.json`, ignoring times and run ids.
- **u-unseen** (a real prototype the checks never saw): at least 90% of its failing rows real on a hand read,
  and at least 80% of the by-eye list caught (the obvious problems written down from its screenshots before
  the first run).
- Runs in real mode inside temper-dev as the `checks` step of `design_app_screen_v1_checks`, $0 model cost;
  the runtime recorded.

A miss gets a written hypothesis (rule 20), one change, and only that case re-run.

### Trial cases

Under `~/design-lab/app-screen-workflow/known-cases/checks/`, each a case folder the host copies into a
run workspace (`01-request/requirements.json`, `03-ground/{inventory.json, fixture.json,
design-files/tokens.json}`, `05-build/`, `expected.json`), frozen once with `FREEZE.json`:

- `base-clean`: a small Parcelly prototype that follows the Prototype contract in full (2 screens, 7 states,
  widths 1440/390/320, so 21 views) and is meant to pass every check. It is also the worked example of the
  contract for stage 5, and the clean twin every planted copy is measured against.
- 23 planted copies of `base-clean` (`p01-console-error` ... `p23-two-screens`), one planted fault each,
  covering all 13 check families, written by `build_cases.py` next to them: one exact string edit of
  `05-build/index.html` per copy, with `expected.json` (check id, screen, state, width) written before any
  run. Where one plant honestly trips a second rule (an off-token grey is both low contrast and off the
  palette), `expect.allow` names that rule and `expect.allow_why` says why.
- `c-inkflow-onboarding`: the false-positive test, a real hand-built prototype where every failing row is
  read by hand and recorded as real or false in `expected.json`'s `read` block, one entry per rule with the
  reason; the grader then fails the case if a rule was left unread or a blocker rule was read as false. It
  is Inkflow's mobile onboarding and client tracker
  (Design #165, 2026-11-02, shown to the owner), copied from
  `~/design-lab/results/inkflow-mobile-onboarding-20261102/inkflow-mobile-onboarding-prototype.html`, with
  `build.json` naming its 10 views.
  - **Why not the planned `c-rollcall`:** the `rollcall-20261104` known case's `05-build/` is draft A, a
    device-framed mock: one page that draws a phone and a desk frame (`?view=phone|desk`), with no hash
    routing, no state marks and screens reached only by clicking `data-act` buttons. There is no way to
    open one screen in one state, so the measured checks could not be pointed at it without rewriting it,
    which this task may not do (the frozen case is copy-only). A real prototype that does route by hash is
    the same test and an honest one, so the Design lead swapped the case and recorded it here.
- `u-unseen`: a real prototype the checks never saw, with `expected-by-eye.md` written from its screenshots
  before the first run: Inkflow's UI refresh (Design #164, 2026-11-01), copied from
  `~/design-lab/results/inkflow-ui-refresh-20261101/inkflow-prototype.html`, 12 views named in `build.json`.
- Neither real case carries `data-screen` marks (both were built before the prototype contract), so each
  gives exactly one true `contract.marks` blocker and the whole `coverage` family is skipped and says so;
  neither has a run fixture or tokens, so `figures` and `tokens` are skipped too. What they really test is
  render, overflow, type, contrast, targets, focus, axe, hierarchy and integration on a real page.

`checks_host.py` (CLI `prep-checks`) copies a case into a fresh workspace and marks the build done at round
1; `checks_grade.py` (CLI `grade-checks`) grades the run against `expected.json` and gives the digest three
runs are compared by. `~/design-lab/app-screen-workflow/results/checks-trials/trial.py` runs cases on the
host against the same `playwright-mcp` service (`CHECKS_BROWSER`, `CHECKS_SITE_HOST`) for quick rounds; the
proof of record is the temper-dev run of `design_app_screen_v1_checks`.

### Hypotheses (rule 20)

**H6a-1: the small-targets plant was wrong, not the check.** `p09-small-targets` planted 18 px nav links
and the targets check passed. Reading WCAG 2.5.8 back: links that far apart pass, because their 24 px
circles never meet, so the plant was not a fault. Change: plant two 18x18 icon buttons 2 px apart at the
end of every parcel row, with `font-family: inherit; font-size: 16px` so no token row rides along. Expect:
`targets.size` catches it at every width, 0 unexplained rows. Wrong if it still passes, which would mean
the spacing measure is broken. **Hit** (t5): caught 1/1, 27 rows, 0 false. It also found a real engine bug:
`design_measure.js` reports `small_targets[].hit` as a word (`target`, `circle`), and the row builder read
it as a number, so the step crashed; it now reads the neighbour's `edge`.

**H6a-2: a wrapped control label is craft, not a blocker.** On `c-inkflow-onboarding`, `overflow.label`
gave 149 of 309 rows from 16 distinct labels, every one of them an intentional, fully readable two-line
chip or tab (`Clients (4)`, `1. Studio & Deposit`). A hand read calls all of them false Musts, which would
fail the "0 false Must" bar, and raising the line limit to 2 would lose `p05-wrapped-label`, whose plant
wraps to exactly 2 lines as well. The Design checklist's own rule is that wrapping is the accepted remedy
and only cut or clamped text blocks. Change: `overflow.label` moves from blocker to should. Expect:
`c-inkflow` keeps the rows as craft feedback, its blocker count drops by about 149, and `p05` is still
caught (the grader matches the check id, not the class). Wrong if `p05` stops being caught, or if a hand
read finds cut text that only `overflow.label` saw. **Hit** (t7/t8).

**H6a-3: the click step lost controls because it looked for them by CSS path.** Six
`integration.handler` rows on `c-inkflow` said "could not be clicked" with no reason at all; a probe
(`/tmp/checks-probe/probe.py`) re-opened the view and found the recorded paths
(`... > button.chip-btn.active:nth-of-type(1)`) no longer matched, because the prototype re-renders those
panels between the measure and the click, so classes and indexes move. The controls are real and
clickable. Change: `checks_measure.js` records each action's `idx` among the elements carrying the same
`data-action`, and the click step finds it again as `[data-action="<id>"]`.nth(idx), keeping the CSS path
as evidence only; the click's answer is now the control's own state plus the page's text and route, so a
control that re-renders itself away still counts as feedback. Expect: the 6 handler rows go, and
`p16-missing-action` and `p17-no-click-feedback` are still caught. Wrong if those plants stop being
caught, or if the handler rows come back. **Hit** (t7/t8).

**H6a-4: the font 404s were my case, not the prototype.** Seven `render.request`/`render.console` rows on
`c-inkflow` were 404s for `assets/fonts/...`: the prototype loads them from a sibling folder I had not
copied into the case. Change: copy `~/design-lab/results/inkflow-mobile-onboarding-20261102/assets` into
the case's `05-build/`. Expect: the render rows go and the type rows shift slightly (the real fonts are
wider). Wrong if the 404s remain, which would mean the prototype itself points at a missing file. **Hit**
(t8).

**H6a-5: a row of dots is not text below the floor.** `c-inkflow` gave 3 `type.floor` blockers for
`"● ● ● ● ●"`, an 11 px step-dot row. Nobody reads dots, so the row is a false Must: the check is meant
to find text too small to read. Change: the type floor skips a run with no letter and no digit. Expect:
the 3 dot rows go, the 43 real 11 px eyebrow and caption rows stay, and `p06-tiny-type` is still caught.
Wrong if `p06` stops being caught, or if a real small label is dropped because it is written in symbols.
**Hit** (t10/t11).

**H6a-6: a control the view already shows as chosen has answered the click before it.** `c-inkflow` gave 2
`coverage.feedback` blockers for `All drafts (3)` and `All clients (4)`: both are the filter chip that is
already active, so a click cannot change anything, and the view already says so. Change: the click step
records `already_on` (`aria-pressed="true"`, `aria-current`, or an `active`/`selected`/`current` class
before the click) and the rule does not ask for a change from a control that is already the chosen one.
Expect: those 2 rows go and `p17-no-click-feedback` is still caught (its plant is not a selected control).
Wrong if `p17` stops being caught, or if a dead control that happens to carry `.active` escapes.
**Hit** (t10/t11).

**H6a-9: a contrast level is a strength, not a hue.** The too-many-levels check counted distinct text
colours, so it fired on all 30 `c-inkflow` views ("5 text colours in one view"), counting a purple link and
a green status word as levels of their own although they stand as strongly as the body text beside them.
The eye sorts text by how strongly it stands out, not by its hue, so those rows are false. Change: the
measure puts every text run in a contrast band against its own background (12:1, 7:1, 4.5:1, 3:1 ->
strongest, strong, normal, soft, faint) and the check counts bands. Expect: views that really use one dark
and one grey keep passing, the hue-only rows go, and a view with four true strengths still fires. Wrong if
the rows stay at the same volume, or if a view with five obvious strengths now passes. **Hit** (t16/t17:
`c-inkflow` 30 -> 0, the planted size and primary cases unchanged).

**H6a-8: a label that wraps in a full row is the layout, not a flaw.** The split-label check fired 149
times on `c-inkflow` and about as often on `u-unseen`, always for a nav chip, tab or step name taking two
full lines ("Clients (4)", "Settings / Setup", "1. Studio & Deposit"). Those controls sit in a column or a
row that is already full, so there is nowhere for the label to go: a hand read calls them false, and at
that volume they would drown the real rows. Demoting the check to a Should (H6a-2) kept the noise. The
planted fault is different in a way a browser can measure: a 64 px button in a row with 120 px to spare.
Change: the measure compares what the label needs laid end to end (a `Range` over its line pieces) with
the control's content width plus what its row has left beside it, and reports only a label that would fit
on one line if the control used the room its row already has. Expect: `p05-wrapped-label` is still caught,
and the `c-inkflow` and `u-unseen` split-label rows drop to the few controls that really are too narrow.
Wrong if `p05` is lost, or if the two real prototypes still give dozens of split-label rows. **Hit**
(t13/t14/t15: `p05` caught, `c-inkflow` 149 -> 0, `u-unseen` 150 -> 5).

**H6a-7: scrolling to what the control points at is visible feedback.** `u-unseen` gave 3
`coverage.feedback` blockers for `For Mara's message at 10:42 am ↓`, a jump link that scrolls the thread to
that message: the page sign held text, classes, style and route, but not the scroll position, so the
answer was invisible to the measure. Change: the page sign includes `window.scrollY`. Expect: those 3 rows
go and the plants still fail. Wrong if a control that does nothing now passes because the page happened to
scroll. **Hit** (t12).

**H6a-10: a view the row contract cannot hold is refused before the browser opens.** The unseen case's
`build.json` named the state `not_sent`; the step rendered all 36 views, wrote `checks.json`, and only
then failed in `contracts.validate` with 18 messages about `checks/41/state`, after six minutes of work
(run `1915449c`). Change: `checks_views.plan` checks every screen and state id against the row contract
first and names the field (`05-build/build.json: 1 problem(s): views/0/state: 'not_sent' is not an id`);
the hash that opens a view stays free text, so the case keeps `?state=not_sent` under the id `not-sent`.
Expect: a build the contract cannot hold is refused in under a second, and a build with slug ids runs as
before. Wrong if a build that used to run is now refused. **Hit** (`47490cb9` ran the fixed case through
in 365 s; the bad id is now refused in under a second, and the 64 pytest cases still pass).

### Results

All of these are temper-dev runs of `design_app_screen_v1_checks` as the `checks` step, in real mode, with
no model call: **$0.00** on every run. The host runner
(`~/design-lab/app-screen-workflow/results/checks-trials/trial.py`) was used for the rounds in between; the
figures below are the proof runs on temper-dev
(`.../checks-trials/temper_trial.py`, results in `.../checks-trials/temper-results/`).

**Planted: 23 of 23 faults caught by the right check, at the right screen and width, with no other row.**
The clean base gives no row at all.

| Case | Run | Caught | Other rows | Digest |
| - | - | - | - | - |
| `base-clean` | `d4c3f1ad` | - | 0 | `4f53cda18c2baa0c` |
| `p01-console-error` | `75494bcf` | `render.console` | 0 | `ec01b8febdafc87b` |
| `p02-failed-request` | `038ecf63` | `render.request` | 0 | `d5922e1f8bc30950` |
| `p03-sideways-scroll` | `3360884d` | `overflow.horizontal` | 0 | `722202780d1056e9` |
| `p04-truncated-meta` | `c3e62ef2` | `overflow.truncated` | 0 | `b8f18d8498ae5637` |
| `p05-wrapped-label` | `98c4a436` | `overflow.label` | 0 | `6daf97eb8ef212cd` |
| `p06-tiny-type` | `3acb8e80` | `type.floor` | 0 | `861b843231bf4e31` |
| `p07-grey-on-white` | `0b9aab7a` | `contrast.text` | 0 | `49abc756d6530065` |
| `p08-faint-field` | `6f57eb0c` | `contrast.ui` | 0 | `aeb893ece0fb95c6` |
| `p09-small-targets` | `bdae1bfd` | `targets.size` | 0 | `d42e2818feb953e1` |
| `p10-no-focus-ring` | `5dee6806` | `focus.ring` | 0 | `497bf163ce02ebc0` |
| `p11-unlabelled-field` | `f46acf72` | `axe.violation` | 0 | `d3ff3bbf0e110ab6` |
| `p12-size-soup` | `da00a6f3` | `hierarchy.sizes` | 0 | `12587e5b32a1239b` |
| `p13-two-primaries` | `2cd272ac` | `hierarchy.primary` | 0 | `907b1e1eedfb440f` |
| `p14-off-palette` | `a4f1e449` | `tokens.colour` | 0 | `6d26d80e55c3a0b7` |
| `p15-missing-state` | `39d00202` | `contract.state` | 0 | `87a9c192e36adb88` |
| `p16-missing-action` | `0c925aa9` | `coverage.action` | 0 | `fd8f76f90e064ee3` |
| `p17-no-click-feedback` | `d15616f7` | `coverage.feedback` | 0 | `a51eda59383356da` |
| `p18-missing-requirement` | `73c9d5ff` | `coverage.requirement` | 0 | `b13f5c3110f68ee6` |
| `p19-invented-figure` | `858436fb` | `figures.invented` | 0 | `c256ffd19a00582a` |
| `p20-dead-link` | `a87b0870` | `integration.dead_link` | 0 | `1bb6b92d8e056482` |
| `p21-duplicate-id` | `ab92387b` | `integration.duplicate_id` | 0 | `3fcfaf209c5be90d` |
| `p22-banned-state-attr` | `9576b0e9` | `contract.state_attr` | 0 | `e23176c7417be01d` |
| `p23-two-screens` | `b533b873` | `integration.two_screens` | 0 | `e5eb46c13792f660` |

"Other rows" counts rows the case did not plant and did not allow. Each case allows the rules that see the
same fault a second time, named with the reason in its `expected.json` (for one, `p07` allows
`axe.violation` and `tokens.colour`: the same grey text, read by axe's own rule and by the palette).

Each planted run opens 21 views (3 screens x 3 screen-states x 3 widths, 320/390/1440) in **about 59 s**.
Every digest matches the host runner's digest for the same case.

**The real prototype (`c-inkflow-onboarding`): 120 rows, 44 blockers, 0 false on a hand read.** Runs
`6a3562e6`, `1ba1bd6b`, `a2d0ea0a` (and `89bd351a` before the last two fixes), 30 views, **about 180 s**.
Every one of the four runs wrote a byte-identical `checks.json`
(md5 `18832341f712a3e428cb68dc38f6c60f`), so the **determinism bar is met**: 3 runs, no difference at all,
not even in ordering.

The hand read is recorded rule by rule in the case's `expected.json` `read` block, and the grader fails the
case if any failing rule is unread:

| Rule | Rows | Read as | Why |
| - | - | - | - |
| `contract.marks` | 1 | real | built 2026-11-02, before the prototype contract, so no `data-screen` root |
| `type.floor` | 43 | real | 11 px eyebrows, brand caption and tracker eyebrow against the 12 px floor |
| `type.body` | 30 | real | 13-14 px sentence text where the product's body size is 16 px |
| `hierarchy.sizes` | 30 | real | 8 to 11 text sizes in one view, against a limit of 3 |
| `overflow.label` | 15 | real | wizard-rail labels split in two although their row has the room |
| `hierarchy.primary` | 1 | real | wizard-3 at 1440 shows two solid purple controls |

**The unseen prototype (`u-unseen`, Inkflow's UI refresh): precision 191/191 rows real (100%).** Run
`47490cb9`, 36 views, **365 s**. Rows: `type.floor` 118, `type.body` 36, `hierarchy.sizes` 36,
`contract.marks` 1; the hand read is in its `expected.json`.

Its by-eye list (`expected-by-eye.md`, written from the screenshots before the first run) graded out at
**4 of 10 caught**, and the grade of each item is written back under that list. Six of the ten were my own
eye being wrong on high-DPR screenshots, each struck by a measurement, not by a loosened threshold: the
strip links measure 74x32 px, the timestamps 6.7:1, the row arrow is a span inside a clickable row, the
chips carry 16 px text, the disclosure is 358x44 px, and at 320 the page does not widen. Of the four items
that really are faults, the run caught all four, and it found a family the list had not thought of (36
`type.body` rows). So the recall bar is met against the real items (4/4) and missed against the list as
written (4/10); the fault is the list, and the lesson (read type sizes and contrast from the measure,
never from a scaled screenshot) is in the Design checklist.

**The whole workflow still runs in fixture mode.** Run `47f81ee9` of `design_app_screen_v1` on the frozen
`rollcall-20261104` case: 19 nodes completed, 18.0 s, $0.00, the 6 skipped ones being the reader and
reviser nodes that fixture mode never calls. Both gates were answered as this doc says (`gate_direction`
choice `a`, `gate_final` `approve`), the `checks` node wrote `06-checks/round-1/checks.json`, and the run
ended with the handoff. The runner is
`~/design-lab/app-screen-workflow/results/fixture_run.py` (`start`, then `watch <tag>`), which packs the
case, starts the run and answers each gate as it opens. A gate answer's `comments` must be a list, even
when empty.

What this does not prove: stage 5a (`fd7d1d93`, `0e5b11d1`) and stage 6a (`1845c1f6`) proved the deterministic
build scaffold (`index.html`, `shell/router.js`, `styles/tokens.css`, `screens/<id>.js`, `fixture.json`,
`build.json`) and every structural check family across all 255 views of `rollcall-20261104`. Stage 5b (#221) and
Stage 6b (#222, below) subsequently built and proved the real screen writer and the fenced review + `review -> build -> checks -> review` fix loop.

## Stage 6b: review

Stage 6b (`review`, Design #222) is the fenced design, UX, hierarchy, state, and language review that sits right
after Stage 6a (`checks`) and drives the `review -> build -> checks -> review` loop when any finding has
`priority == "must"`.

### Architecture (rule 17: deterministic script steps first, fenced model only where judgment is needed)

`review` stays the final node of Stage 6 in `design_app_screen_v1.yaml` so its existing `loop_to: build`
(`max_loops: 2`, `loop_condition: review.structured.verdict == "revise"`) works without changing downstream
edges. Both `design_app_screen_v1.yaml` and the stage-alone trial workflow `design_app_screen_v1_review.yaml`
run the same 5-node Stage 6b pipeline:

1. `review_collect` (`design_app_screen_stage_v1`, `depends_on: [checks]` in the full workflow):
   - In `fixture` mode, returns `model: "no"` so the model nodes are skipped at $0.00.
   - In `real` mode, validates `06-checks/round-<n>/checks.json`, `05-build/build.json`,
     `01-request/requirements.json`, and `03-ground/inventory.json`; groups failing Stage 6a check rows by
     `(check_id, screen)` into numbered measured items `M1..Mk` (`06-checks/round-<n>/measured_items.json`,
     blockers ordered first); builds a 12-panel contact sheet `06-checks/round-<n>/sheet.png` (`<= 1568 px`,
     `<= 180,000 bytes`, canonical RGB PNG via `existing_sheet.py`) from `06-checks/round-<n>/views/*.png`; and
     writes `06-checks/round-<n>/task.md` containing the product requirements, rendered per-screen state
     headlines/summaries, card copy/figure bindings, action labels/feedback, `M1..Mk`, and (when `round > 1`)
     the previous round's Must findings to verify fixed.
2. `review_read` (`configs/design/agents/design_app_screen_review_v1.yaml`: `anthropic / claude-opus-5-5`,
   `token: anthropic-2` / `roamee`, `image_input: review_collect.structured.sheet_path`, `tools: []`, no
   `temperature`, `max_tokens: 64000`, `total_timeout: 1800`, `condition: review_collect.structured.model == "yes"`):
   outputs one JSON object (`06-checks/round-<n>/draft.json`, schema `review_draft` in `contracts.py`) with:
   - `measured[]`: one decision per `M1..Mk` item (`id`, `severity` 0-4, `priority` `must|should|could|wont`,
     `suggestion`, and `reason` required whenever a Stage 6a `blocker` is demoted below `must` or any item is
     rated `wont`).
   - `findings[]`: UX, taste, hierarchy, state recovery, and language findings (`element`, `location`, verbatim
     `evidence`, `severity` 0-4, `priority` `must|should|could|wont`, `suggestion`, optional `reason`).
3. `review_check` (`design_app_screen_stage_v1`, `condition: review_collect.structured.model == "yes"`):
   runs `review_check.py` over `06-checks/round-<n>/draft.json` against 7 deterministic rules, writes
   `06-checks/round-<n>/check.json` (`verdict: "ok" | "retry"`), and on `"retry"` prepares `revise_task`.
4. `review_revise` (`design_app_screen_review_v1`, `condition: review_check.structured.verdict == "retry"`):
   one bounded revision pass when `review_check` finds any rule violation.
5. `review` (`design_app_screen_stage_v1`, `depends_on: [review_revise]`):
   - In `fixture` mode, copies the known case's `review.json`.
   - In `real` mode, applies the revised draft if `review_check` returned `"retry"`, runs final `review_check`
     (`06-checks/round-<n>/check-final.json`, failing loud on any remaining problem), merges `measured[]`
     (carrying each `M*` item's exact `element`, `location`, `evidence`, and `check` from `measured_items.json`)
     and `findings[]` into `06-checks/round-<n>/review.json` (`F1..Fn`), computes deterministic
     `verdict = "revise"` iff any finding has `priority == "must"` else `"done"`, and validates
     `contracts.validate("review", ws)`.
- Round-2 build feedback wiring (`build_scaffold.build_task(ws)`): when `ws.round > 1` and
  `06-checks/round-<ws.round - 1>/review.json` has `priority == "must"` findings (or `07-show/comments.json` has
  owner change requests), `05-build/task.md` includes a `"Must Findings From Round <n-1> To Fix"` section naming
  each Must finding's screen, element, location, evidence, and suggestion so `build_read` repairs them on Round 2.

### Deterministic draft checks (`review_check.py`) and planted-fault proof

Every rule in `review_check.py` is proven by a dedicated planted-fault test in
`tests/test_design_app_screen_review.py`:

| # | Check ID | What it checks | Planted fault in `test_design_app_screen_review.py` | Caught |
| --- | --- | --- | --- | --- |
| 1 | `review_draft_schema` | Valid JSON matching `review_draft` (`measured[]`, `findings[]`, severity 0-4, priority `must\|should\|could\|wont`) | Non-JSON or schema-invalid draft | **PASS** (`test_planted_fault_1_schema_invalid`) |
| 2 | `every_measured_item_covered` | Every `M1..Mk` item in `measured_items.json` appears exactly once in `measured[]` | Omit `M2` or duplicate `M1` in `measured[]` | **PASS** (`test_planted_fault_2_missing_or_duplicate_measured_item`) |
| 3 | `demoted_blocker_has_reason` | Any Stage 6a `blocker` item in `M1..Mk` rated below `must` has a non-empty `reason` (`>= 15` chars) | Demote blocker `M1` to `should` without `reason` | **PASS** (`test_planted_fault_3_demoted_blocker_without_reason`) |
| 4 | `wont_has_reason` | Every `measured[]` or `findings[]` entry with `priority == "wont"` has a non-empty `reason` (`>= 10` chars) | Rate `M2` or a finding `wont` with empty `reason` | **PASS** (`test_planted_fault_4_wont_without_reason`) |
| 5 | `must_has_suggestion` | Every `measured[]` or `findings[]` entry with `priority == "must"` has a non-empty `suggestion` (`>= 10` chars) | Rate `M1` or a finding `must` with empty `suggestion` | **PASS** (`test_planted_fault_5_must_without_suggestion`) |
| 6 | `no_invented_measurement` | No `findings[]` entry claims a script-measured metric failure (`4.5:1` contrast ratio, sub-floor `px` font size, `24x24` target size, `axe` violation, horizontal overflow) that passed in `checks.json` | Finding claims `"Body text is 11px and fails 4.5:1 contrast ratio"` when `checks.json` passed both | **PASS** (`test_planted_fault_6_invented_measurement_claim`) |
| 7 | `valid_location_and_evidence` | Every finding's `location` names a valid screen in `05-build/build.json` and quotes grounded text/elements from the build | Finding cites unknown screen `checkout/normal` or ungrounded quote `"Quantum flux capacitor offline"` | **PASS** (`test_planted_fault_7_unknown_screen_or_ungrounded_evidence`) |

### Bar (written before trials, rules 16, 17, 19)

| Check / Trial case | Bar | Measured result | Status |
| --- | --- | --- | --- |
| `review_check.py` planted faults (7 rules) | 7 / 7 planted faults caught by their named check ID; retry loop recovers on valid revised draft and fails loud on still-broken draft | 7 / 7 caught (`tests/test_design_app_screen_review.py`, 13 passed) | **PASS** |
| Case 1: `clean-parcelly` (4 screens, 48 Stage 6a views, 0 blockers, 0 shoulds, clean copy) | 3 / 3 runs on `temper-dev` pass `review` with `verdict: "done"`, `must: 0`, 0 false Musts | 3 / 3 passed (`c37bd955`, `7f9f9e57`, `b3fd5a7b`): `verdict: "done"`, `must: 0`, `findings: 0` | **PASS** |
| Case 2: `measured-inkflow` (`c-inkflow-onboarding`, 30 views, 44 blocker rows + 76 should rows grouped into `M1..M12`) | 3 / 3 runs on `temper-dev` pass `review` with `verdict: "revise"`, 12 / 12 `M*` items accounted for, 0 invented measurements | 3 / 3 passed (`1a8be65f`, `3ae6f2ca`, `b5c58c4b`): `verdict: "revise"`, 12 / 12 `M*` covered, `must: 5` | **PASS** |
| Case 3: `taste-planted` (`parcelly-clean` passing all 24 Stage 6a checks across 48 views with 0 blockers/shoulds, with 3 planted UX/language flaws on `home`: `T1` raw SQL + `auth_token=sk_live_9981_parcelly` leak with no recovery in `error`, `T2` robotic button label `Submit action_btn_1`, `T3` reassurance fluff replacing parcel figures on `home`) | 3 / 3 runs on `temper-dev` catch all 3 planted UX/language flaws (`recall == 1.0`) and output `verdict: "revise"` (`must >= 3`) | 3 / 3 passed (`615815bb`, `d141fd47`, `4072f854`): `verdict: "revise"`, 3 / 3 planted flaws caught as `must` on every run (`recall: 1.0`) | **PASS** |
| Case 4: 2-round `review -> build -> checks -> review` fix loop on `temper-dev` | Starting from `taste-planted` Round 1 (`verdict: "revise"`), Round 2 `build` fixes all Round 1 Must findings, Round 2 `checks` passes with 0 blockers/shoulds across 48 views, and Round 2 `review` outputs `verdict: "done"` (`must: 0`) | Round 1 `review` `615815bb` (`revise`, 7 Musts) -> Round 2 `build` `c6a67792` -> Round 2 `checks` `bc070a36` (48 views, 0 blockers, 0 shoulds) -> Round 2 `review` `3dc56eb6` (`done`, `must: 0`, `findings: 0`) | **PASS** |
| Whole-workflow fixture run (`design_app_screen_v1`, `mode: "fixture"`) | Completes all 33 nodes on `temper-dev` at $0.00 | `c55cf237-52f6-43d2-8b68-374280167426`: 33 / 33 nodes completed in 11.20 s at $0.00 | **PASS** |

### Hypothesis log (rule 20)

- **Hypothesis H6b-1 (Round-level Stage 6a check rows with `screen: null` and `location: "the round"`).**
  - *What was wrong and evidence:* On the first `measured-inkflow` probe (`62b70f19-d3f3-43d1-9e87-9981f9e37e2d`),
    `review_collect` failed contract validation before calling the model:
    `06-checks/round-1/measured_items.json: items/0/screen: 'the round' does not match '^[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}$'`.
    Stage 6a's `contract.marks` check is a round-level check with `"screen": null` and `"location": "the round"`,
    and `review._row_screen()` returned the raw location prefix `"the round"` even when it was not an `_ID` slug.
  - *The one change and why it should fix it:* In `configs/design/bin/app_screen/review.py:_row_screen()`, accept
    `screen` or a location prefix only when it matches `_ID` (`^[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}$`) or a known
    screen ID in `05-build/build.json`; otherwise assign the round-level row to the first screen ID in
    `valid_screens` (or `"round"` if empty).
  - *Expected result and measure:* `review_collect` writes contract-valid `measured_items.json` (`M1..M12`) on
    `c-inkflow-onboarding`, and 3 / 3 `measured-inkflow` runs complete on `temper-dev` with 12 / 12 `M*` items
    covered.
  - *What would prove us wrong:* Any schema error on `measured_items.json` or any uncovered `M*` item.
  - *Outcome:* **HIT** — 3 / 3 `measured-inkflow` runs (`1a8be65f`, `3ae6f2ca`, `b5c58c4b`) completed with
    12 / 12 `M*` items covered and `verdict: "revise"`, plus unit test
    `test_group_measured_items_maps_round_level_location_to_valid_id`.

### Results on `temper-dev`

Stage 6b trial results are saved in `~/design-lab/app-screen-workflow/results/review-trials/temper-6b-results.json`:

| Case | Run # | Execution ID | Status | Verdict | Findings (`must`) | Measured covered | Planted recall | Cost (USD) | Duration |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `clean-parcelly` (4 screens, 48 views, 0 Stage 6a issues) | 1 | `c37bd955-d33a-403a-8744-c906a636eb71` | `completed` | `done` | 0 (`0`) | 0 / 0 | — | $0.0328 | 4.87 s |
| `clean-parcelly` (4 screens, 48 views, 0 Stage 6a issues) | 2 | `7f9f9e57-c214-4b20-8d28-6f6a7afc23ce` | `completed` | `done` | 0 (`0`) | 0 / 0 | — | $0.0323 | 4.44 s |
| `clean-parcelly` (4 screens, 48 views, 0 Stage 6a issues) | 3 | `b3fd5a7b-7978-41e2-b09e-e27b6f007a36` | `completed` | `done` | 0 (`0`) | 0 / 0 | — | $0.0325 | 4.11 s |
| `measured-inkflow` (30 views, 44 blockers + 76 shoulds -> `M1..M12`) | 1 | `1a8be65f-4d04-4b03-9f30-4990efc86bb0` | `completed` | `revise` | 18 (`5`) | 12 / 12 | — | $0.0871 | 24.37 s |
| `measured-inkflow` (30 views, 44 blockers + 76 shoulds -> `M1..M12`) | 2 | `3ae6f2ca-dcf7-4de1-95f1-e8debfb92a10` | `completed` | `revise` | 19 (`5`) | 12 / 12 | — | $0.0950 | 26.82 s |
| `measured-inkflow` (30 views, 44 blockers + 76 shoulds -> `M1..M12`) | 3 | `b5c58c4b-4a59-47f2-b03c-82268198aa63` | `completed` | `revise` | 18 (`5`) | 12 / 12 | — | $0.0882 | 24.27 s |
| `taste-planted` (Stage 6a base `feca9df3`: 48 views, 0 blockers/shoulds; 3 planted UX/copy flaws) | 1 | `615815bb-a719-4d28-a224-c83fb02ae2aa` | `completed` | `revise` | 7 (`7`) | 0 / 0 | 3 / 3 (100%) | $0.0501 | 11.98 s |
| `taste-planted` (Stage 6a base `feca9df3`: 48 views, 0 blockers/shoulds; 3 planted UX/copy flaws) | 2 | `d141fd47-5642-4a14-bf5d-c66241771adc` | `completed` | `revise` | 7 (`7`) | 0 / 0 | 3 / 3 (100%) | $0.0491 | 10.52 s |
| `taste-planted` (Stage 6a base `feca9df3`: 48 views, 0 blockers/shoulds; 3 planted UX/copy flaws) | 3 | `4072f854-b73f-478d-8b23-55b46cc2b46d` | `completed` | `revise` | 8 (`7`) | 0 / 0 | 3 / 3 (100%) | $0.0516 | 11.29 s |

2-round `review -> build -> checks -> review` fix loop proof on `temper-dev` (workspace
`/home/shinelay/temper-ai/workspaces/design222-loop-proof-1794049119`):

| Round & Stage | Workflow | Execution ID | Status | Key output / result | Cost (USD) | Duration |
| --- | --- | --- | --- | --- | --- | --- |
| Round 1 `checks` | `design_app_screen_v1_checks` | `feca9df3-6aaf-4093-843a-7e057d57ad60` | `completed` | 48 views measured, 0 blockers, 0 shoulds | $0.0000 | 182.97 s |
| Round 1 `review` | `design_app_screen_v1_review` | `615815bb-a719-4d28-a224-c83fb02ae2aa` | `completed` | `verdict: "revise"`, 7 Must findings (`F1..F7`) catching `T1`, `T2`, `T3` | $0.0501 | 11.98 s |
| Round 2 `build` | `design_app_screen_v1_build` | `c6a67792-9168-4c82-b72d-ebc05bf9c318` | `completed` | Read `"Must Findings From Round 1 To Fix"`, replaced leaked SQL/token error with recovery copy, renamed `Submit action_btn_1` to `"Track today's parcel"`, restored grounded parcel delivery window/shop copy | $0.1268 | 40.04 s |
| Round 2 `checks` | `design_app_screen_v1_checks` | `bc070a36-0a48-4ee3-8697-b0381ee43562` | `completed` | 48 views measured in `06-checks/round-2/views/`, 0 blockers, 0 shoulds | $0.0000 | 183.38 s |
| Round 2 `review` | `design_app_screen_v1_review` | `3dc56eb6-bad8-475b-8ea2-e4ec4f99b7b4` | `completed` | `verdict: "done"`, `must: 0`, `findings: 0`, all Round 1 Musts verified fixed | $0.0357 | 4.35 s |
| Whole-workflow fixture | `design_app_screen_v1` (`fixture`) | `c55cf237-52f6-43d2-8b68-374280167426` | `completed` | 33 / 33 nodes completed (including `review_collect` -> `review_read` -> `review_check` -> `review_revise` -> `review`) | $0.0000 | 11.20 s |

## Stage 7: show, W5 gates, and Stage 8: handoff

Design #224 replaced the final remaining stubs of `design_app_screen_v1` — Stage 7 (`show`), W5 (`gates`
prediction and owner taste encoding), and Stage 8 (`handoff`) — with 100% deterministic scripts ($0.00 model
cost), proved the 2-round `gate_final (changes) -> build -> checks -> review -> show -> gate_final (approve) -> handoff`
loop on both `parcelly-clean` and `rollcall-20261104`, and proved the full 37-node end-to-end `mode: "real"`
workflow run from Stage 1 (`intake`) to Stage 8 (`handoff`) on `temper-dev`.

### Architecture (rule 17: 100% deterministic scripts, $0.00 model cost)

1. **Stage 7 (`configs/design/bin/app_screen/show.py` + `show_check.py`)**:
   - In `fixture` mode: runs `run_fixture(ws, "show")`.
   - In `real` mode:
     - Validates upstream prerequisites loud and fast: `05-build/index.html`, `05-build/build.json`,
       `05-build/fixture.json`, and `06-checks/round-<ws.round>/review.json` must exist, and `review.json`
       must have `verdict == "done"` (0 open Must findings).
     - Compiles a self-contained single-file interactive Show&Tell bundle `07-show/bundle.html` (and
       `07-show/bundle-round-<ws.round>.html`) by inlining `05-build/styles/tokens.css`,
       `05-build/fixture.json`, `05-build/screens/*.js`, and `05-build/shell/router.js` into
       `05-build/index.html`, ensuring `<html ... data-st-interactive="true">` and stripping any forbidden
       `data-state` or `data-st-state` attributes below `html`/`body` (note `n131`). Never shares externally
       or sends Telegram notifications from inside a worker run (lead-only rule).
     - On `ws.round > 1`: archives the prior round's `07-show/gate_final.json` to
       `07-show/gate_final-round-<ws.round - 1>.json` (so `gate_final` can be freshly answered on the new
       round), computes non-blank line retention (`kept_lines`, `prev_non_blank_lines`, `kept_ratio`,
       `change_note` per `bp-bc056d81`) against `07-show/bundle-round-<ws.round - 1>.html`, and resolves
       targeted comments listed in `gate_final-round-<ws.round - 1>.json`'s `comments[]` to
       `state = "answered"` with a versioned reply (`version = ws.round`, `outcome = "done"`) in
       `07-show/comments.json`.
     - Writes `07-show/showtell.json` (`doc_id`, `version = ws.round`, `url = f"/showtell/#/d/{doc_id}"`,
       `title`, `bundle: "07-show/bundle.html"`, plus line-retention fields on Round > 1) and
       `07-show/comments.json` (`doc_id`, `comments[]`).
     - Also exposes host command `design_app_screen.py prep-show --workspace W [--doc DOC_ID] [--description TITLE] [--source COMMENTS_JSON]`
       so the lead can seed `07-show/showtell.json` and `07-show/comments.json` before `show` runs.
     - Runs `show_check.py` (4 rules) -> `07-show/check.json`, failing loud on any violation, and validates
       `contracts.validate("show", ws)`.
     - Furthermore, `build_scaffold.build_task(ws)` now reads `07-show/gate_final.json` (or
       `07-show/gate_final-round-<ws.round - 1>.json`) and `07-show/comments.json` when `ws.round > 1`,
       injecting a `"Show&Tell Comments From Round <n-1> To Address"` section into `05-build/task.md` so
       Stage 5b addresses each targeted comment.

2. **W5 (`configs/design/bin/app_screen/gates.py`)**:
   - Computes deterministic `prediction = {"choice": pred_choice, "matched": pred_choice == record["choice"], "basis": "..."}`
     before writing `gate_direction.json` or `gate_final.json`:
     - `gate == "direction"`: reads `04-directions/directions.json` (`recommended` if valid, else selects the
       direction with the fewest `should`/non-pass rows in `04-directions/<id>/checks.json`, tie-breaking to
       the first direction id).
     - `gate == "final"`: reads `06-checks/round-<ws.round>/review.json` and `07-show/comments.json`; predicts
       `"approve"` when `review.verdict == "done"` and 0 comments have `state == "open"`, else `"changes"`.
   - Encodes owner taste (`taste` field in `gate_<name>.json`):
     - When `ws.mode == "fixture"` or `record["decided_by"] == "design"`, sets `"taste": "not-taste"` (keeping
       `test_fixture_run_passes_every_contract` green).
     - When `ws.mode == "real"` and `record["decided_by"] == "owner"`, appends a structured taste entry
       (timestamp, product, gate, choice, verbatim `owner_words`, `source`, `reason`, `prediction.choice`,
       `prediction.matched`) to `ws.path / "taste-owner.md"` (and `DESIGN_TASTE_FILE` when set in env) and
       sets `"taste": "saved"`.

3. **Stage 8 (`configs/design/bin/app_screen/handoff.py` + `handoff_check.py`)**:
   - In `fixture` mode: runs `run_fixture(ws, "handoff")`.
   - In `real` mode:
     - Validates upstream prerequisites loud and fast: `07-show/gate_final.json` must exist with
       `choice == "approve"`, `06-checks/round-<ws.round>/review.json` must have `verdict == "done"`, and
       `03-ground/inventory.json`, `05-build/build.json`, and `05-build/draft.json` must exist.
     - Generates one comprehensive Markdown spec per screen in `08-handoff/spec/<screen-id>.md` covering:
       `## Route & Layout` (`#<screen>/<state>`, layout, widths `1440`, `390`, `320`),
       `## Mapped Requirements` (`R*` with verbatim `owner_words`), `## What It Shows` (`S*` with `fields[]`
       paths and sample values from `03-ground/fixture.json`), `## Interactive Actions` (`A*` with immediate
       click feedback), `## States & Copy Table` (`normal`, `loading`, `empty`, `error`, plus screen-specific
       states), and `## Review & Show&Tell Notes` (Stage 6 checks/review + Stage 7 Show&Tell comment notes).
     - Writes `08-handoff/design-file.json` (`kind: "html-prototype"`, `location: "05-build/index.html"`,
       `editable: True`, `note`) and `08-handoff/followup.json` (`F1..Fn`: `frontend` implementation items
       per screen + `design` follow-ups for any non-blocking `should`/`could` review findings or excluded
       ground items).
     - Runs `handoff_check.py` (6 rules) -> `08-handoff/check.json`, failing loud on any violation, and
       validates `contracts.validate("handoff", ws)`.

### Planted-fault proof (`show_check.py`, `gates.py`, and `handoff_check.py`)

All 17 unit and planted-fault tests in `tests/test_design_app_screen_show_handoff.py` pass:

| Component | Rule / Feature | Planted fault in `test_design_app_screen_show_handoff.py` | Caught / Verified |
| --- | --- | --- | --- |
| `show_check.py` | 1. `review_done` | Set `06-checks/round-1/review.json` `verdict` to `"revise"` or inject an open `"must"` finding | **PASS** (`test_show_check_planted_fault_1_review_not_done`) |
| `show_check.py` | 2. `bundle_self_contained` | Remove `data-st-interactive="true"`, leave relative `<script src="screens/home.js">`, or inject `<div data-state="normal">` below `<body>` | **PASS** (`test_show_check_planted_fault_2_bundle_not_self_contained`) |
| `show_check.py` | 3. `showtell_and_comments_match` | Mismatch `doc_id` between `showtell.json` and `comments.json` or set `version != ws.round` | **PASS** (`test_show_check_planted_fault_3_showtell_and_comments_mismatch`) |
| `show_check.py` | 4. `targeted_comments_answered` | On Round 2 after `gate_final (changes, comments=[1])`, leave comment `#1` `"open"` or omit `kept_ratio` | **PASS** (`test_show_check_planted_fault_4_targeted_comments_unanswered_on_round_2`) |
| `gates.py` (W5) | `direction` & `final` gate `prediction` + owner `taste` encoding | Direction tie-break on fewest `should` rows; final gate `"changes"` vs `"approve"` prediction; `"saved"` + `taste-owner.md` when `real` + `owner` vs `"not-taste"` in `fixture` or `design` | **PASS** (`test_w5_direction_gate_prediction_and_owner_taste_encoding`, `test_w5_final_gate_prediction_changes_when_open_comment_and_approve_when_resolved`) |
| `handoff_check.py` | 1. `gate_final_approved` | Set `07-show/gate_final.json` `choice` to `"changes"` | **PASS** (`test_handoff_check_planted_fault_1_gate_final_not_approved`) |
| `handoff_check.py` | 2. `spec_per_inventory_screen` | Delete `08-handoff/spec/parcel.md` | **PASS** (`test_handoff_check_planted_fault_2_missing_screen_spec`) |
| `handoff_check.py` | 3. `spec_sections_complete` | Strip `## Interactive Actions`, `#home/normal`, or state `loading` from `home.md` | **PASS** (`test_handoff_check_planted_fault_3_incomplete_spec_sections`) |
| `handoff_check.py` | 4. `design_file_valid` | Point `design-file.json` `location` at a nonexistent path or set `editable: false` | **PASS** (`test_handoff_check_planted_fault_4_invalid_design_file`) |
| `handoff_check.py` | 5. `followup_valid` | Remove `frontend` item for `parcel` or duplicate follow-up ID `F1` | **PASS** (`test_handoff_check_planted_fault_5_invalid_followup`) |
| `handoff_check.py` | 6. `no_open_must_or_unanswered_comment` | Re-open a Show&Tell comment in `07-show/comments.json` or inject a `"must"` finding in `review.json` | **PASS** (`test_handoff_check_planted_fault_6_open_must_or_unanswered_comment`) |

### Results on `temper-dev`

Trial results are saved in `~/design-lab/app-screen-workflow/results/show-handoff-trials/temper_trials_224.json`:

| Trial | Workflow | Execution ID | Status | Key results | Cost (USD) | Duration |
| --- | --- | --- | --- | --- | --- | --- |
| 1. 2-round `gate_final (changes -> Round 2 -> approve -> handoff)` loop on `parcelly-clean` | `design_app_screen_v1` (Stage 7 -> Round 2 -> Stage 8) | `a8459409-479a-47b3-9ece-10dc33670b62` | `completed` | Round 1 `show` (v1) -> `gate_final` (`choice: "changes"`, `comments: [1]`, `prediction.matched: true`, `taste: "saved"`) -> Round 2 `build` + live `checks` (48 views, 0 blockers) + `review` (`verdict: "done"`) -> Round 2 `show` (v2, `kept_ratio: 0.9989`, `1778/1780` lines kept, comment `#1` `"answered"`) -> `gate_final` (`choice: "approve"`, `prediction.matched: true`, `taste: "saved"`) -> `handoff` (`account.md`, `home.md`, `parcel.md`, `parcels.md`, `check.json` `passed: true`) | $0.0325 | 195.94 s |
| 2. 2-round `gate_final (changes -> Round 2 -> approve -> handoff)` loop on `rollcall-20261104` | `design_app_screen_v1` (Stage 7 -> Round 2 -> Stage 8) | `06dcb6e9-141c-444b-b92e-f8bd65181aad` | `completed` | Round 1 `show` (v1) -> `gate_final` (`choice: "changes"`, `comments: [1]`, `prediction.matched: true`, `taste: "saved"`) -> Round 2 `build` + `show` (v2, `kept_ratio: 1.0`, `24432/24432` lines kept, comment `#1` `"answered"`) -> `gate_final` (`choice: "approve"`, `prediction.matched: true`, `taste: "saved"`) -> `handoff` (17 screen specs `today.md`..`tickets.md`, `check.json` `passed: true`) | $0.0000 | 7.10 s |
| 3. Full end-to-end `mode: "real"` run on `parcelly-clean` (all 8 stages + both gates) | `design_app_screen_v1` (`mode: "real"`) | `3480264f-ae15-45eb-b583-c3f60bfd491a` | `completed` | 37 nodes (`32 completed`, `5 skipped` `_revise` nodes): Stage 1 `intake` -> Stage 2 `existing` -> Stage 3 `ground` -> Stage 4 `directions` -> `gate_direction` (`choice: "a"`, `prediction.matched: true`, `taste: "saved"`) -> Stage 5 `build` -> Stage 6a `checks` (`0 blockers`, `0 shoulds`) -> Stage 6b `review` (`verdict: "done"`) -> Stage 7 `show` (`show_check_passed: true`) -> `gate_final` (`choice: "approve"`, `prediction.matched: true`, `taste: "saved"`) -> Stage 8 `handoff` (`handoff_check_passed: true`, 5 specs: `account.md`, `home.md`, `login.md`, `parcel.md`, `parcels.md`) | $0.8020 | 553.58 s |
| 4. Whole-workflow `mode: "fixture"` run on `rollcall-20261104` | `design_app_screen_v1` (`mode: "fixture"`) | `5bff5706-a424-4f9c-bae0-4e3c50adb990` | `completed` | 37 nodes (`24 completed`, `13 skipped` model/revise/loop nodes), both gates recorded `prediction.matched: true` and `taste: "not-taste"`, all 11 step contracts validated | $0.0000 | 11.37 s |


