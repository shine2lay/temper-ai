# design_app_screen_v1: app screens, stage by stage

Design's product-design flow for app screens (UI/UX), the one Design ran by hand for RollCall and
Inkflow, as a Temper workflow. The owner asked for it on 2026-11-04: "lets try to encode the different
stages you had of your flow into temper wf".

Version 1's skeleton (Design #198, W0) set up every stage, both owner gates, the workspace, a contract
for each step's output and the first known case. A stage that is still a stub copies the known case's
output in fixture mode and has it checked against its contract; in real mode it fails at once with "the
real stage is not built yet". Each stage's own task replaces its stub and keeps its contract, one stage
at a time (owner, 2026-11-04: "lets run one stage a time after setting up the skeleton, so we can really
hone in on it"). Built so far: stage 1, intake (Design #206; see "Stage 1: intake").

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
| `tests/test_design_app_screen_contracts.py` | contracts, gates, freeze and the CLI, on the known case |
| `tests/test_design_app_screen_intake.py` | intake's checks, steps, collector and grader, on fixed drafts |
| `tests/design_app_screen_case/rollcall-20261104/` | the known case's JSON and Markdown outputs (the pictures and pages stay in the lab) |

## Stages

| # | Stage | Steps (workflow nodes) | Leaves | Built by |
| --- | --- | --- | --- | --- |
| 1 | intake | `intake_collect`, `intake_read` (model), `intake_check`, `intake_revise` (model, only on a failed check), `intake` | the owner's words as requirements (verbatim) and the clarification questions (rule 33) | #206 |
| 2 | existing | `existing` | today's screens captured and measured; the user journeys, each problem with evidence | W2 |
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
| the other seven, both gates | stub: fixture mode only | one task per stage |

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
