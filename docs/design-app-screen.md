# design_app_screen_v1: app screens, stage by stage

Design's product-design flow for app screens (UI/UX), the one Design ran by hand for RollCall and
Inkflow, as a Temper workflow. The owner asked for it on 2026-11-04: "lets try to encode the different
stages you had of your flow into temper wf".

Version 1's skeleton (Design #198, W0) set up every stage, both owner gates, the workspace, a contract
for each step's output and the first known case. A stage that is still a stub copies the known case's
output in fixture mode and has it checked against its contract; in real mode it fails at once with "the
real stage is not built yet". Each stage's own task replaces its stub and keeps its contract, one stage
at a time (owner, 2026-11-04: "lets run one stage a time after setting up the skeleton, so we can really
hone in on it"). Built so far: stage 1, intake (Design #206; see "Stage 1: intake"), and stage 2,
existing (Design #207; see "Stage 2: existing").

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
| `tests/test_design_app_screen_existing.py` | existing's checks, steps, product file, measures and grader, on fixed drafts and broken copies |
| `tests/test_design_app_screen_contracts.py` | contracts, gates, freeze and the CLI, on the known case |
| `tests/test_design_app_screen_intake.py` | intake's checks, steps, collector and grader, on fixed drafts |
| `tests/design_app_screen_case/rollcall-20261104/` | the known case's JSON and Markdown outputs (the pictures and pages stay in the lab) |

## Stages

| # | Stage | Steps (workflow nodes) | Leaves | Built by |
| --- | --- | --- | --- | --- |
| 1 | intake | `intake_collect`, `intake_read` (model), `intake_check`, `intake_revise` (model, only on a failed check), `intake` | the owner's words as requirements (verbatim) and the clarification questions (rule 33) | #206 |
| 2 | existing | host `capture`, then `existing_collect`, `existing_sheet`, `existing_read` (model), `existing_check`, `existing_revise` (model, only on a failed check), `existing` | today's screens captured and measured; the user journeys, each problem with evidence | #207 |
| 3 | ground | `ground` | one shared fixture, the product's design files, the screens x states inventory | W2 |
| 4 | directions | `directions`, then `gate_direction` | two or more clickable directions, each with its quick checks; the owner picks one | W3, W5 |
| 5 | build | `build` | the chosen direction: a shell and one file per screen | W3 |
| 6 | checks | `checks`, then `review` | measured checks by script, then findings rated 0-4 and Must/Should/Could/Won't; a Must loops back to build | W4 |
| 7 | show | `show`, then `gate_final`, `gate_final_next` | one Show&Tell share and the owner's comments; approve, or changes back to build as targeted edits | W4, W5 |
| 8 | handoff | `handoff` | a spec per screen, the design file, the follow-ups for other roles | W4 |

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
| `<id>/checks.json`, `round-<n>/checks.json` | `checks[]`: `id`, `value`, `result` (pass, fail), `evidence`, `element`, `location` |
| `review.json` | `round`, `verdict` (done, revise); `findings[]`: `id`, `element`, `location`, `evidence`, `severity` 0-4, `priority` (must, should, could, wont) |
| `build.json` | `direction`, `round`, `page`, `widths[]`, `screens[]`: `id`, `file` (in 05-build/), optional `states[]` |
| `showtell.json` | `doc_id`, `version`, `url` |
| `comments.json` | `doc_id`; `comments[]`: `number`, `version`, `body`, `element`, `state`, optional `replies[]` |
| `gate_<name>.json` | see Gates; no fields beyond these |
| `design-file.json` | `kind` (penpot, html-prototype), `location`, `editable` (true or false) |
| `followup.json` | `items[]`: `id`, `what`, `owner_role`, `source` |

Change a contract only together with the stage that writes the file, and keep the known case passing.

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
the answer plus `prediction` (the judges' guess of his answer, filled in by W5; `null` for now) and
`taste` (W5 appends a real answer to `~/design-lab/taste/owner.md`; `pending-w5` until then, `not-taste`
in a fixture run). Answer a gate with `POST /api/runs/<run>/approve/<node>` and body `{"response": "<the
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
| 3 ground | real; met its bar 2026-11-05, round t4, 3/3 runs on every case (Stage 3, Results) | #210 |
| the other five, both gates | stub: fixture mode only | one task per stage |

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
