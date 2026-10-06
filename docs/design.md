# Design reviews

Original editable-vector identity work: [Logo workflow and contracts](design-logo.md).
The logo workflow uses new Design-owned agents; reviewers and sealed review
benchmarks described here are unchanged.

`design_review` is an expert review of a product's pages: what a senior designer
and an accessibility auditor would flag. It is the design role's first workflow,
and the critic and grader that later design workflows reuse. Who owns it:
[departments.md](departments.md).

```
capture (script) -> [ critic_a | critic_b ] -> verify (script) -> merge
```

- **capture** (no model): opens each page in temper's browser (playwright-mcp)
  at each viewport (desktop 1280x800, mobile 390x844), saves screen-sized
  screenshots, runs axe-core 4.13.0, and measures what tools can measure:
  contrast, type sizes, headings, line length, target sizes, weak boundaries,
  where each form field's name comes from, unnamed graphics, overflow at
  390 px, landmarks, and a Tab walk with the focus ring of each stop.
  Target size follows WCAG 2.5.8 in full: a control's labels count as part of
  its target, and an undersized target passes when a 24 px circle on it meets
  no other target or undersized target's circle (the spacing exception). Text
  of inactive (disabled) controls is exempt from contrast. `facts.md` lists
  these measured passes next to the problems, so critics stop reporting them.
- **critic_a, critic_b**: the same agent run twice, apart. Each reads every
  page's screenshots and facts in one go, so it can also check consistency
  across pages. It judges what no tool can: hierarchy, wording, flow, states,
  consistency, and the WCAG 2.2 AA points that need a person (Nielsen's 10
  heuristics). It never contradicts a measured number, cites evidence a person
  can check (element, page, screenshot tile or facts value), and rates
  severity on Nielsen's 0-4 scale with anchored definitions and worked
  examples from other products (when torn, the lower level).
- **verify** (no model, `design_review_verify.py`): every critic claim about
  target size, or about an inactive control's contrast, checked against the
  facts page by page (contradicted, partly contradicted, supported), and each
  finding marked checkable or not. Writes `review/verify.json`.
- **merge**: groups the same problem found twice, drops the claims the facts
  contradict (the report says which fact), and sorts each finding into
  *confirmed* (measured, or found by both critics), *single* (one critic, with
  checkable evidence the screenshot shows: a person checks it) or *rejected*
  (contradicted, uncheckable or taste). Writes `review/report.md` (fix-first
  list, then each page, then what the facts check dropped) and
  `review/findings.json`. Without `verify.json` (the homepage workflows reuse
  the critic and merge without that step) it does the same checks from
  `facts.md`.

Each finding names the page, viewport, element and place, the evidence (a
measurement or what the screenshot shows), the Nielsen heuristic or WCAG
criterion, the severity, and a separate suggestion. A problem is claimed only
for the pages where it was seen or measured.

The critics and the merge are `provider: claude` (Claude Code), because its
Read tool shows screenshots to the model; temper's own MCP client drops image
blocks.

## Running it

```bash
curl -s -X POST http://127.0.0.1:8420/api/runs -H 'Content-Type: application/json' -d '{
  "workflow": "design_review",
  "workspace_path": "/home/shinelay/temper-ai/workspaces/<a new folder>",
  "inputs": {
    "brief": "What the product is, who uses it, what these pages are for.",
    "pages": "index.html,pricing.html",
    "base_url": "https://staging.example.com/"
  }
}'
```

- `base_url`: a deployed site the browser can reach. Or `site`: a folder
  inside the run container that capture serves over HTTP itself (the browser
  refuses `file:` URLs), e.g. `/app/configs/design/testpages/fernway-v1`.
- `pages`: paths relative to the site, comma-separated.
- `viewports`: `desktop,mobile` by default.
- `workspace_path` is needed (without it the steps get an empty workspace),
  and the folder must be writable by the run's container user.

A run of four or five pages takes about 4-5 minutes and $2.00-2.20 (v4).

If the brief has a line `Primary action: <button or link text>`, the page
checks also look for that action in the first phone screen, and a line
`Design context: <id>` (an id from
`configs/design/knowledge/context-playbook.json`) gives the critics that
context's conventions and avoid list. Both lines are optional.

## Grading it

A review is graded on **test sites with planted problems**: small fictional
products in `configs/design/testpages/`, each with an answer key listing every
planted problem (what, where, measured or judged), the real problems found
later that weren't planted (`also_true`), and things that are fine.

The keys live in `~/design-lab/answers/`, outside every folder a run
container mounts: runs see all of `~/temper-ai`, so a key anywhere in it would
be readable by the critics. Test sites carry no hints at their plants.

```bash
python3 configs/design/bin/design_trial.py fernway-v1                       # review + grade
python3 configs/design/bin/design_trial.py fernway-v1 --workflow <candidate> # a candidate workflow
python3 configs/design/bin/design_trial.py fernway-v1 --grade-only <review workspace>
```

Both of its starts send the design role's named key, read from the file named
by `TEMPER_API_KEY_FILE`, else `~/.config/temper/api-keys/design.key`, so
temper's write guard names them `design` ([api-access.md](api-access.md)).
Without a readable key file they go without one, as an unknown caller.

`design_trial.py` reads `testpages/<site>.json` (brief, pages, key path),
runs the review, then runs `design_review_grade` with the findings and the
key as text, and prints the score:

- `recall_confirmed`, `recall_any`: share of plants found as confirmed, and
  found at all; `by_kind` splits measured from judged plants.
- `true_findings`, `true_rate`: findings that match a plant or a known real
  problem.
- `invented`: findings the grader thinks are made up. `overclaims`: a real
  problem claimed for pages where it isn't.
- `unmatched_by_guess`: findings that match nothing in the key, with the
  grader's guess. The grader can't see the site, so a person checks these
  against the site's code and adds the real ones to the key's `also_true`.

## Results

| Date | Site | Run | Recall | Findings | Invented | Over-claims | Cost |
|---|---|---|---|---|---|---|---|
| 2026-10-02 | fernway-v1 (22 plants) | 92910c36 | 22/22 confirmed | 35, all true | 0 | 1 | $1.91 |
| 2026-10-02 | fernway-v1 (after the over-claim fix) | 396c4f58 | 22/22 confirmed | 35, all true | 0 | 0 | $1.73 |
| 2026-10-04 | morrow-v2 (14 plants, 10 traps), v2 candidate | f99200aa | 14/14 | 23, all true | 0 | 0 | $1.80 |
| 2026-10-04 | morrow-v2, v2 candidate | cfbd55a0 | 14/14 | 24, all true | 0 | 0 | $1.82 |
| 2026-10-04 | fernway-v1, v2 candidate | 52ddd192 | 22/22 | 33, all true | 0 | 0 | $1.96 |
| 2026-10-05 | morrow-v2, v3 candidate | aa9f8b31 | 14/14 | 23 (21 true, 2 taste) | 0 | 0 | $1.68 |
| 2026-10-05 | morrow-v2, v3 candidate | 05815f1e | 14/14 | 23 (22 true, 1 taste) | 0 | 0 | $1.83 |
| 2026-10-05 | fernway-v1, v3 candidate | 0c448d7f | 22/22 | 31, all true | 0 | 0 | $2.03 |
| 2026-10-05 | fernway-v1, v3 candidate | f09f5b2f | 22/22 | 29, all true | 0 | 0 | $2.01 |

fernway-v1 is too easy to tell versions apart; morrow-v2 adds traps (things
that look wrong but are fine) and severity per plant.

## v2 (queue #7, 2026-10-04): findings you can act on without sorting

v1 on morrow-v2 called correctly spaced small targets a failure in both runs,
once reported a checkbox whose label is its target as too small, and rated
severity one step above the key on 8 of 14 plants. v2 was built as a test
workflow next to the live one (`design_review_next`), graded on the sealed
sites, and promoted only after it met every bar: all plants found, no invented
findings or overclaims in three runs, all 10 traps held in each morrow-v2 run
(v1: 9 and 8), severity equal to the key on 11 of 14 (v1: 6), cost 1.04-1.14x
v1. The three changes are the measured passes (capture), the facts check
(verify) and the anchored severity (critic and merge) described above.

Known residual (fixed in v3, below): on fernway-v1 the anchored scale rates
some WCAG failures one step below its key (equal on 13 of 22 plants; v1:
17-18). Results and the hand check of every unmatched finding:
`~/design-lab/results/review-precision/` (host only).

## v3 (queue #33, 2026-10-05): severity rules

v2 gave similar WCAG failures a 2 whether they sat just under the threshold
or far below it, and whether or not they blocked the main navigation; the
homepage revisions act only on confirmed severity 3 or more, so a problem
rated one step low slipped through. v3 keeps capture, the facts check and the
rest of the critic and merge prompts word for word, and adds severity rules
that set the step between minor (2) and major (3):

- **how far below the threshold**: text contrast from 3:1 to just under 4.5:1
  is 2, under 3:1 on text people read to act is 3; a control or its state
  under 2:1 is 3 when the task needs it; a page up to a fifth wider than a
  phone is 2, one and a half screens or more is 3; a failing target is 2; a
  label only missing in code is 2, no visible label in the main form is 3;
  missing text for a logo is 2, for an icon that carries needed information 3.
- **main navigation or main task**: no visible focus on the main navigation
  or the primary action is 3 (one secondary link: 2); a wrong, hidden or
  contradicting price, or a label that understates a commitment, is 3; a home
  page's first screen that doesn't say what the product does, or where
  something is louder than the headline, is 3; competing primary buttons are
  at least 2.
- **how many pages**: on most pages or in a shared part, one level up (at
  most 3).
- a passing small target's usability finding: 2 when used again and again in
  the main task at 16 px or less, else 1.

The merge sets each level by these rules (critics' ratings are input, not
votes) and may go one level above the critics only for a measured finding a
rule sets from the facts. Worked examples in the prompts come from other
products; no test site is named.

It was built as a test workflow next to the live one (`design_review_next`)
and promoted only after four graded runs (two per site) met every bar: all
plants found, no invented findings or overclaims, all 10 traps held in each
morrow-v2 run (and fernway-v1's 4 things that are fine), no plant two steps
off, severity equal to the key on 13 of 14 in both morrow-v2 runs (v2: 11)
and on 21 and 20 of 22 on fernway-v1 (v2: 13). Cost per run 0.92-1.03x v2.

Known residual: fernway-v1's 16 px week arrows are rated 1 where the key says
2. They pass WCAG 2.5.8 by the spacing exception, so the key's reason no longer
holds; a corrected key needs a new fernway version. morrow-v2's sole red
"Delete workspace" button is rated 3 where the key says 2 (as in v2). Results
and the hand check of every unmatched finding:
`~/design-lab/results/review-severity/` (host only).

## v4 (queue #39, 2026-10-05): page checks and research checks

The critics missed problems that a script can measure and that people react
to (repeated copy, a hidden main action, controls that don't look clickable,
small text in the dark theme), and nothing judged whether each picture, or
each missing picture, fits the job of its section. v4 adds:

- **Page checks without a model** (`configs/design/bin/design_page_checks.js`
  in the page, `design_page_checks.py` on the host, thresholds frozen in
  `design_page_checks_thresholds.json` before any candidate run). Capture
  runs them with `--page-checks` and writes the results into `facts.md`:
  the same word runs repeated across sections; the primary action inside
  the first 390x844 screen; the main navigation on one line at 390; an empty
  column wider than 30% of the content width; every control outside the
  header and footer bars with a visible cue (border, fill, shadow, underline
  or icon); text over an image, gradient or translucent layer, with contrast
  measured from the screenshot pixels behind its letters; body text under
  14 px in the dark theme (a `prefers-color-scheme: dark` pass is captured
  when the page has one); and the share of each section and of the first
  screen covered by pictures (img, svg, canvas, picture and CSS background
  images; icons under 48 px left out), with the sections that have none.
- **Research checks in the critic** (each finding names its `check` and the
  ids of the research evidence behind it, E###): signifiers, text over
  pictures, typicality (which conventions of the category the page follows
  and breaks; a break needs a reason), the design context's avoid list (for
  money products: no reward animation, badges or confetti near a trade, no
  hot list as the main way in, every cost visible before confirming), and
  small text in the dark theme. Worked example critiques come from made-up
  products; no test site is named.
- **Craft critic v2** (`design_homepage_craft_critic_v2`): severity anchored
  to the measured craft facts (for example spacing: under 60% of values on
  a 4 px grid is 3), the empty-column fact, and pictures judged by purpose.
  For each section the critic takes its purpose from the art director's
  imagery plan, or states it, and flags a section whose purpose needs
  showing that has words only, or a picture with no job or one that works
  against its section (pulls from the key action, misleads, crowds data).
  Styled type, rules, numbered steps and plain tables count as words; there
  is no rule by audience or page type.

`design_homepage_v2` review rounds and `design_craft_bench` capture with the
page checks. A new sealed bench, `quarry-v1` (two fictional products: an
illustrated marketing page and a dense data screen, each with a clean
control, plus one planted page per check), joins the benchmarks; its key
stays on the host.

It was built as candidates next to the live agents and promoted after these
graded runs: on `quarry-v1`, all 12 plants found in both runs with every
severity in the key's range (v3 + craft v1: 9 of 12, missing repeated copy,
signifiers and dark small text, with the spacing plant rated 2), no invented
findings and no measured-check finding on the clean controls; the review
benchmark held (morrow-v2 14/14 twice, fernway-v1 22/22 twice, no invented
findings or overclaims, severity equal to the key on 13 and 13 of 14 and 19
and 21 of 22, against v3's 13, 13, 21, 20); craft-v1 found all 7 plants at
severity 3 or more in both runs (v1: 6, spacing at 2), with no factually
wrong alarm and 61 of 63 cells agreeing between runs (v1: 59). On the three
scoreboard homepages the page checks found every problem the judge had
named, and the purpose check ranked the illustrated one first in both runs.
Cost per review run is 1.06-1.2x v3 ($2.01-2.19 on the review
benchmark); a craft-bench page about $0.52. Results:
`~/design-lab/results/critic-research/` (host only).

## Files

| Path | What |
|---|---|
| `configs/design/workflows/design_review.yaml` | the review |
| `configs/design/workflows/design_review_grade.yaml` | the grader |
| `configs/design/agents/design_{capture,critic,verify,merge,grade,score}.yaml` | its steps |
| `configs/design/bin/design_capture.py` | capture: serves a site, drives playwright-mcp, writes `review/shots`, `review/facts`, `capture.json` |
| `configs/design/bin/design_measure.js` | the in-page measurements |
| `configs/design/bin/design_page_checks.{js,py}`, `design_page_checks_thresholds.json` | the page checks (v4) and their frozen thresholds |
| `configs/design/bin/design_review_verify.py` | verify: the facts check of critic claims |
| `configs/design/bin/vendor/axe-4.13.0.min.js` | axe-core (MPL-2.0) |
| `configs/design/bin/design_trial.py` | review + grade on a test site (host) |
| `configs/design/testpages/<site>/`, `<site>.json` | test sites and their brief and pages |

## Editable Penpot homepage workflow (v1)

**Superseded by v2 (below) and left unchanged.** v1 keeps the gate names and
answer labels it had before 2026-10-05 (`owner-direction`, `owner-final`,
`owner_final_gate_recorded`); the gate convention of queue #40 (gates named for
what they decide, every answer recording `decided_by`) applies to v2 and the
logo workflow, not here. Don't start new v1 runs.

`design_homepage_v1` is the **real-work** entry, with mandatory owner direction
and final gates. `design_homepage_pilot_v1` is fictional-only and may choose a
**provisional** direction without owner taste approval. Both are Design-owned,
use the same source steps, and reuse `design_critic` twice plus `design_merge`
**unchanged**. They do not alter the planted-problem benchmark or grade taste.

```
brief -> explore -> direction -> design -> measure -> BUDGET
        -> [critic_a | critic_b] -> merge -> REVIEW DISPOSITION
        -> (fix -> design, maximum three rounds) or handoff -> OWNER FINAL (real only)
```

### Scope and inputs

This v1 is a **bounded, template-driven meeting-room homepage system**, not
arbitrary autonomous brand invention. It takes saved JSON copy: product,
fictional boolean, audience, headline, subhead, CTA, disclosure, exactly three
rooms, steps and FAQ entries, and terms. See `DEFAULT` and `brief_contract` in
`configs/design/bin/design_homepage_v1.py`. Different briefs change live editable
copy; layouts are three authored structures, not recolours. No real transactions,
leads, external assets, publication or invented proof. Breakpoint/static-board
limitations are explicit in the handoff. Unsupported copy/brief shapes fail rather
than silently flatten or clip. This pilot supports Latin/LTR copy only.

Penpot 2.18's current WASM exporter needs its native text-layout cache; uncached
API-created text otherwise times out looking for a legacy `foreignObject`.
The Design source builder seeds that cache with advance widths from the actual
installed, licensed regular/semibold TTFs and explicit authored line boxes.
Linked component instances translate the cached coordinates too. Styled source
text stays editable; no text becomes paths or a screenshot. This is not a
kerning/complex-script shaping engine, and editor edits may recompute positions.
Source checks include advance-width fit; inspect actual exports and the editor,
not just bounding-box metadata. Fonts, version, hashes and full OFL are retained.

Run the fictional pilot with the default Morrow Rooms brief (blank `brief_json`),
or provide your saved brief JSON. Use a **fresh** writable run workspace:

```json
{"workflow":"design_homepage_pilot_v1",
 "workspace_path":"/home/shinelay/temper-ai/workspaces/<unique-homepage>",
 "inputs":{"brief_json":"","direction_json":""}}
```

The real entry requires `brief_json` with `fictional: false`, stops after the six
editable wireframe exports, and will not design without an owner direction
response. The pilot rejects real briefs before writes. No script/user input can
remove the real workflow's `direction` or `final` gate.

### Checkpoints, gates and limits

Gate free-text responses are saved JSON (the run UI/API's `response` field), not
approval prose. Approve through the existing gate UI; the fictional trial's host
supervisor may answer fictional-only review/direction checkpoints but cannot
approve real direction or final taste.

- Direction: `{"direction":"task-led","approval":"owner-direction","reason":"..."}`
  for real work; fictional decisions are always relabelled `provisional-fictional`.
  A supplied `direction_json` is saved but does not bypass the real gate.
- Budget, **before every paid round**:
  `{"pacific_day":"YYYY-MM-DD","reserve_usd":2.6,"day_spent_usd":0,
  "trial_spent_usd":0,"trial_envelope_usd":8.75,"subscription_checked":true,
  "one_design_experiment":true}`. Supervisor first reconciles actual costs,
  checks shared allowance/duplicates and reserves the entire remaining trial;
  each day's spend plus reservation must fit $10. Above-$10 trial estimates need
  owner permission; don't split experiments to evade it. Estimate/reservation is
  not an engine-enforced billing cap: supervise reviewer cost/time and record
  retries. Expired/non-finite/missing reservations fail.
- Review disposition: `{"action":"handoff","adjudication":[...],"unresolved":[...]}`
  or `{"action":"fix","issues":["D1"],"patch":{"subhead":"..."},
  "reason":"evidence..."}`. Every fix cites existing findings; allowed patches
  are bounded copy changes. Layout defects need an explicit source revision by
  Design, not invented auto-fixes. All observations/suggestions/decisions remain
  in the packet. At round three a fix request fails; unresolved issues must be
  recorded. Loop rewinds to design, **not** brief/explore/direction. A source
  revision must be committed, normally landed and deployment-verified before
  approving its fix disposition; record its exact commit in that disposition.
  The first homepage review prompted the explicit second-round revision:
  original 4/8/12-seat room schematics rather than blank placeholders, non-action
  illustration styling, a meeting-criteria checklist, mobile header anchors,
  sibling-size terms heading with labelled terms, grouped labelled card facts
  and stacked tablet steps. Final-round fixes clarify proposed-demo step context,
  fixed-order equipment (unlisted is unspecified, never falsely absent), equal
  capacity/price weight and explicit USD units, aligned prices/stacked tablet room
  rows, three visible section anchors, a seat legend and balanced desktop needs.
  The source renders every leading example-policy line, retaining the final
  disclosure; the handoff includes exact per-board `rendered-copy.json` alongside
  the brief inventory. These are Design source changes, not reviewer tuning.
- Real final: `{"approval":"owner-final","reason":"..."}`. The pilot has no
  aesthetic pass/final-approval claim.

Resume a waiting run through the gate, retaining `homepage/job.json` and saved
direction. Completed source-stage receipts are input-fingerprinted; identical
re-entry reads/verifies saved Penpot state instead of repeating it. Changed inputs
in a completed stage fail: use a new workspace. Review revisions get distinct
files/receipts and retained exports. A partial API stage saves file identity and
fails visibly rather than creating silent duplicates on retry. Do not erase its
pending receipt to make a failed prerequisite appear green.

### Source, access and evidence

Owner authorized the existing `design-agent@spark.local` login for temper runs
on 2026-10-02. Keys live only in temper's existing `.env` store:
`PENPOT_URL`, `PENPOT_AGENT_EMAIL`, `PENPOT_AGENT_PASSWORD`. This shares that
account with **all temper run containers**, not just Design. No password/session
cookie goes into a config, model input, output or artifact. The API client is
standard-library, restricts the host, checks the authenticated email and creates
new files only in design-agent's Drafts project. No owner-file mutation, new
accounts/permissions, MCP keys or browser login service is required. Script Bash
strips inherited `*_PASSWORD` variables: this Design client reads only the
explicitly authorized Penpot password from its own run-container bootstrap
(`/proc/1/environ`), after matching the full run UUID/container and design-agent
identity. It fails closed outside that run or on unreadable/mismatched identity.
It neither changes the engine's generic command filter nor puts any key into a
template, model context, checkpoint or artifact. This is Docker/Linux-specific;
the host proof uses its existing credential file, not this fallback. The save
client discovers the authenticated agent's default Drafts project/team through
`get-profile`; it never guesses a project UUID. File reads/updates fail closed if
the file is outside that same Drafts identity.

API saves use the verified Penpot 2.18 object/library/component change protocol.
Text remains live with colour/type references; component instances retain main
shape refs. Source, PNG and SVG exports come from actual Penpot, never an HTML
canvas substitute. Fresh authenticated reopen verifies boards, text, styles,
components and instances. Host inspection additionally opens the actual editor
and exported images. Standalone native SVG fonts are embedded from the same
installed regular/semibold WOFF bytes, preserving all vector/live-text markup;
only two known filenames are fetched against authorized Penpot, never arbitrary
origins from SVG. Independent offline rendering must load both fonts, not silently
use a fallback. PNG is also portable. Source Sans Pro is installed (SIL OFL 1.1); original
vectors require no third-party asset license. The host packet retains font
license/name-table/hash evidence.

Each workspace saves `homepage/BRIEF.md`, `brief.json`, six wireframe boards,
`wireframes.json`, `contact-sheet.svg`, `exploration.json`, `direction.json`,
`source-rNN.json`, `source.json`, `tokens.json`, `final-copy.json`, `exports/`,
`measure-rNN.json`, `budget-rNN.json`, `disposition-rNN.json`, `reviews/rNN/`,
`source-links.json`, `HANDOFF.md` and `manifest.json`. Source contains only our
editable design objects, not model requests or credential payloads.

Static source measurements check contrast, text sizes, intended target regions
and object bounds. They **do not** prove actual glyph fit, runtime keyboard,
ARIA, focus, zoom/reflow or overall WCAG conformance. Review facts say so.
Objective checks and human judgement/taste stay separate. The workflow's
manifest records `packet_built` but leaves `completion_verified`, deployment and
resume evidence false; only host verification can complete the pilot report.

Model-free fixtures: `tests/test_design_homepage.py` (schema/gates/three structural
directions/editability/geometry/contrast/cache/budget/loop/errors). Actual run,
deployment, pause/resume, editor persistence, exports, cost/time and residual
issues: `/home/shinelay/design-lab/results/morrow-homepage/` on spark.

## Homepage workflow v2: designed in code, converted to editable Penpot

v1's look came from fixed templates, so it could be tidy but never bold. v2 lets
the models design where they are strongest, real HTML and CSS, and then converts
the rendered page into an editable Penpot file, which stays the editable master.
v1 is unchanged.

`design_homepage_v2`: brief + the owner's taste file -> copy deck (copywriter
draft, word checks, content review, revision; see v2.1 below) and 8-12 category
references (screenshots, research only; never copied or traced) -> art director
drafts three named concepts (a
~400-word brief each, licensed display + text fonts, dominant colour + accent,
imagery, one signature layout move, one motion idea; hero + one section at 1440
and 390) -> automatic check -> only when that check fails, the art director
refines from its renders -> check (up to 3 more refine loops) -> **direction
gate** -> designer builds the
full page -> measure (capture, axe, craft metrics) -> the unchanged
`design_critic` x2 + `design_merge`, plus the craft critic, runtime checks in a
real browser and the content critic on the page's words -> combine (at
most 2 automatic revisions) -> convert to Penpot -> verify -> handoff -> **final
gate** (approve, or request changes: one more revision round, at most twice).

Agents (all `provider: claude`, `model: opus`, so they can read PNGs):
`design_homepage_copywriter_v2` (phase draft|revise),
`design_homepage_content_critic_v2` (target deck|page),
`design_homepage_art_director_v2` (phase draft|refine),
`design_homepage_designer_v2`, `design_homepage_craft_critic_v2` (writes to
`review/craft/`, never `review/critic/`, so taste never mixes with usability
findings; advisory, taste is decided at the gates) and `design_homepage_reviser_v2`.
Everything else is the script stage `design_homepage_stage_v2`
(`configs/design/bin/design_homepage_v2.py`).

### Inputs and gate answers

- `brief_json`: product, category, audience, purpose, cta (<=40 chars),
  `fictional` (bool; fictional needs a disclosure line), at least three facts
  (the only source for claims on the page), optional assets (path, alt, kind
  screenshot|logo|photo) and brand.
- `references_json`: 8-12 `{name, url (https), why}`.
- `taste_md` (optional, default empty): the owner's taste file, passed by the host
  launcher; agents see only what is passed.
- Direction gate: `{"concept": "A"|"B"|"C", "decided_by": "design", "reasons": "why this concept", "notes": "..."}`.
- Final gate: `{"decided_by": "design", "reasons": "..."}` to approve, or
  `{"verdict": "request_changes", "decided_by": "design", "reasons": "...", "notes": ["..."]}`.

**Gates are named for what they decide** (queue #40, 2026-10-05; Design's gate
convention of 2026-10-04): the nodes are `direction` and `final`, and every
answer records who decided (`decided_by`) and why (`reasons`). The chat running
the workflow answers as Design (`decided_by: design`); a queued task's chat asks
its home chat first. `decided_by: owner` is only for the owner's own words: they
go verbatim in `notes`, with `source` naming where he said them, and they
outrank Design's. Only an owner answer may carry `source`. The old `approval`
field is refused. `homepage/direction.json`, `homepage/final.json` and each
change round's `final-rNN.json` keep the answer as given, and `job.json`
and the stage results carry `direction_approved` and `final_approved`, each
`{"approved": bool, "decided_by": ...}`; a change round's fix-list items are
`G1`, `G2` ... with source `final_gate`. No key, node or flag claims an owner
approval the owner didn't give.

Records written before 2026-10-05 (`owner_direction_approved`,
`owner_final_approved`, `owner_changes`, `owner-final.json`, taste entries with
`owner_words`, fix items with source `owner`) are read under the new names and
never rewritten; an old `approval: owner-*` answer reads as `decided_by: owner`,
because that is what it claimed then.

The fixture workflow accepts only `"decided_by": "fixture-test"`; the real
workflow refuses fixture briefs and fixture answers.

`design_homepage_v2_pilot` is the fictional-only twin (same nodes, agents and
checks; every script stage runs with `mode: pilot`, and a test keeps the two in
step). Its brief stage refuses real products, and its direction gate takes only
`{"concept": ..., "decided_by": "design", "reasons": "why, 8+ words"}`:
the worker's provisional pick, recorded with `provisional: true` and
`direction_approved.approved: false`, and never added to the taste files. Its
final gate takes `decided_by` design or owner like the real one. Use it for
paid trials of the workflow on made-up products.

`design_homepage_v2_bench` is the benchmark twin (queue #10; same nodes, agents,
checks and loops, `mode: bench`, fictional briefs only, a test keeps it in step).
It has no gates: the direction step builds the art director's recommended
concept (`concepts.json` top-level `"recommended": {"concept", "reason"}`, a
reason of 8+ words, required in bench runs at both concept checks; the art
director writes it in every mode as advice, and the real direction gate never
takes it), recorded as `decided_by: design` with `benchmark: true` and
`direction_approved.approved: false`, never a taste entry. The final step
records `homepage/final-benchmark.json` (`benchmark_skipped`,
`final_approved: {"approved": false, "decided_by": null}`, labelled not
approved). The Penpot file is named
`... (benchmark)`. Benchmark pages are judged blind by the owner on Design's
scoreboard (`~/design-lab/scoreboard.md`), with an AI pairwise judge recorded
beside as advice only.

### Concept check

Each concept must meet its contract: no overused faces (Inter, Roboto, Open
Sans, Lato, Space Grotesk, Arial, Helvetica, system defaults) unless the brand
uses them; fonts fetched from Google Fonts with their licence file (OFL, Apache
or UFL) saved beside them; WCAG contrast for text on the dominant and accent
colours; a brief of real length; three layout-signature traits. Pages are local
HTML/CSS only: no `<script>`, iframes or outside URLs. Distinctness between
every pair: dominant colours at least 0.10 apart (OKLab), layout signatures
share at most half their traits, thumbnails differ by at least 6%, and the
display faces and pairings differ. A failed check sends the concepts back to the
art director with the problems; it never reaches the owner.

Fresh type pairings and accessibility (queue #34):

- **Pairing record.** `configs/design/knowledge/type-pairings.json` holds the
  display + text pairings the test fixtures and earlier runs used (font names and
  generic sources only). Runs cannot write configs, so each run appends to a
  shared log beside the run workspaces (`<workspaces>/.design/type-pairings.jsonl`,
  or `DESIGN_PAIRING_LOG`): the three pairings offered at a passed final concept
  check, and the pairing picked at the direction step (fixture runs too). Before
  drafting, the model-free `pairings` stage writes `homepage/PAIRINGS.md` (record +
  log, minus the run's own workspace, plus the faces reached for most), which the
  art director reads. The concept check rejects a concept whose pairing is
  recorded, either way round, unless the brief's brand owns both faces; fixture
  concepts are exempt (they are the record's own).
- **axe on every concept.** axe-core (WCAG 2.2 A/AA tags) runs on each concept
  at 1440 and 390, twice: with reduced motion, and with motion allowed after the
  load animations finish (looping animations are stopped first). Never
  mid-animation, which reported 2-5 false contrast failures per page in #5. Any
  violation is a concept problem with its rule, where it failed and an example
  element; results are in `check.json` (`axe`). The planted page
  `testpages/html-fixtures/planted-contrast.html` (one low-contrast note, plus a
  fading headline and a looping badge that must not be reported) proves it.
- **Drafts kept.** The draft check copies the concepts as checked (pages, fonts,
  renders, `concepts.json`, `check.json`) to `homepage/concept-drafts/` before a
  refine pass can rewrite them, so draft and refined concepts can be compared.
- **Refine only when the draft check fails.** The craft critic compared draft and
  refined concepts on three fictional benchmark briefs (9 concepts, two blind
  critic runs per page, summed severities per checklist item): refining won 5 of
  the 10 items, short of the 6 needed to keep it, while costing a third of the
  concept stage. So `refine` has the condition
  `check_draft.structured.verdict == retry`. When it is skipped, the final check
  sees the same pages and spec as the passed draft check and reuses it (nothing
  rendered or measured twice; output `reused_draft_check`), then records the
  offered pairings and asks the direction gate as before. Drafts that fail the
  check are refined and re-checked in full, with up to 3 more refine loops.

### Converter (`html_to_penpot.py` + `html_dom_extract.js`)

The browser renders the page at 390, 768 and 1440 with motion frozen; the
extractor walks the DOM and records boxes, fills (solid, linear and radial
gradients, images), borders, radii, shadows, inline SVG as absolute paths, and
text from the browser's own line boxes with real font, size, weight, colour,
line height and letter spacing. The converter makes one Penpot board per width,
sections as named boards or groups, CSS colour variables as shared colours,
text styles as shared typographies, and elements marked `data-component` as
Penpot components (one main, linked instances at every width). Page fonts are
uploaded to the Penpot team as custom fonts only when a licence file sits beside
them (recorded in the report); images become Penpot media.

**Layouts that reflow (`penpot_layout.py`, queue #9).** The extractor also
records each element's computed layout (display, flex direction, wrap, gaps,
padding, alignment, grid tracks as written and as computed, margins, min/max
sizes, natural size). For every board the planner picks the Penpot layout that
reproduces where the browser put each child, checked against a model of Penpot
2.18.1's own flex and grid algorithms (1 px): CSS flex becomes Penpot flex
(direction, gap, padding, alignment, wrap, each child fill, fixed or hug); CSS
grid becomes Penpot grid (fr, px, % and auto tracks, each child in its cell);
block flow becomes a column with the measured spacing, side-by-side children a
row. Only what none of these can reproduce keeps its position, and every such
fallback (positioned, or a flex/grid mapped to a measured row or column, e.g.
`space-around` or `row-reverse`) is listed in the report (`layout.fallbacks`,
issues `layout-positioned` / `layout-measured`). Texts grow: auto-height, or
auto-width for one-line labels, boxed by their CSS line boxes so Penpot's own
re-measure lands where the browser did. Penpot breaks lines like CSS
`white-space: break-spaces` (the space at a line's end takes room; the browser
drops it), so each wrapping text gets a width between the one where a line's
last word would drop and the one where the next line's first word would come
up, from per-line facts the extractor measures; a text no width can reproduce is
listed in `layout.notes`. Grid `fr` tracks below 1 are scaled so the smallest is
1fr (Penpot shares free space by max(1, fr)), keeping CSS's ratios. Boards hug
their content, so a longer text grows its card and pushes everything after it; Penpot passes growth up
only through boards that hug, so in a row of stretched cards the tallest hugs
and the others fill (they stretch with it); a shorter card that grows past the
row does not grow the row (a Penpot 2.18.1 limit). A page board has a fixed
width and hugs its height: typing a new width reflows the page. Penpot has no
media queries and no viewport units, so each width's board keeps the layout and
sizes the browser used at that width: a board narrowed past one of the page's
breakpoints keeps its own layout (the 390 and 768 boards carry the others), and
type or spacing set with `vw` (`clamp(3rem, 8vw, 8rem)`) keeps its captured
size. Sizes written as a share of the parent (`max-width: calc((100% - 128px) / 3)`)
keep today's pixels too, since Penpot sizes boards in pixels (grid tracks are the
only percentages), so such a box does not narrow with its parent. Centred
containers (`width: min(100% - 48px, 1200px)`) fill up to their cap with the
gutter as margins; a block held at its `max-width` (in a flex row, a column or
a grid cell) fills up to it, so a narrower parent narrows it; a one-line text
with room to spare in a row fills up to today's width and wraps when the row
narrows, as CSS does (one word or `white-space: nowrap` keeps growing
sideways). Boxes sized by their content do the same: a `dd` around its words
in a row with room to spare, a width-auto box in a flex column that doesn't
stretch it, and a grid item at the start of a wider column fill up to
today's width, and their words wrap inside them. `align-items: baseline` keeps
each item's offset from its line's top as a margin. Layers that keep their
position (borders, focus rings, badges, positioned children, and the layers of
a board with nothing to lay out, such as a dotted leader drawn by its border)
get Penpot constraints from where they sit, so a top border keeps spanning its
board, a corner badge keeps its corner, a badge hung past the right edge
(`right: -116px`) keeps to that edge and a centred one stays centred when the
board is resized; a box that fills up to its width keeps the room its design
leaves after it for such a badge, as a right margin. Glyphs
that overflow a tight line-height never become margins (the text box is its
line boxes, as in CSS); the whole pixels Penpot adds to a text's box come out
of its margins, so a board that hugs a row of labels is as wide as in the
browser; and the planner models Penpot's rule that a filling board never
shrinks below its content. Elements with `:hover` /
`:focus-visible` rules become Penpot variant sets (property `State`: Default, Hover, Focus) and their instances link to the
Default variant; component copies link to their main by place in the tree and
mark layout differences as overrides. Verify also checks that layouts, text
growth and variants come back from the server as sent.

Verify reopens the saved file and checks every layer, text, colour, typography,
component and instance; exports PNG and SVG from Penpot itself (SVG with its
fonts and images embedded, same host only); and compares each width's Penpot PNG
with the browser render. Fidelity bar per width (`FIDELITY`): same size; pixels
differing by more than 48 (with a 1 px shift allowed) at most 2.0% overall,
1.0% outside text and 12.0% inside text boxes (anti-aliasing and font
hinting differ there); and in 32 px tiles at most 20% differing and a mean
difference of at most 40, so a single lost card cannot hide in a page-wide
average.

**Rich details (queue #31).** What real designed pages use comes across as
native, editable Penpot shapes:

- *Borders.* Four equal borders are one native stroke (dashed and dotted
  included); a double border is the box's stroke for the outer line plus an
  inset layer `Border / double (inner line)` for the inner one. Borders on some
  sides only: a side whose corners are square is a rectangle (solid), two
  rectangles (double) or a line with a native dashed or dotted stroke, snapped
  to whole pixels as the browser paints them. A rounded box with borders on
  some sides (a ticket notch, an arch with no bottom border) gets one path
  layer `Border / <sides>` following the rounded outline: a stroked centre line
  when the sides match, or a filled ring when widths differ or a border tapers
  out at a rounded corner. Inline boxes (a dotted underline on a word) and form
  controls get their side borders too.
- *Radii* are the browser's used radii: when corners would overlap (a
  `12rem` top radius on a short card) all of them shrink by the same factor,
  as CSS and Penpot both do; elliptical corners are listed as
  `radius-elliptical-approximated`.
- *Backgrounds.* Every layer is kept, bottom to top: colours and gradients
  that cover the box are native gradient fills (radial size keywords and
  explicit sizes, transparent stops fading the neighbouring colour, not grey).
  A layer Penpot can't draw (a tiled or repeating pattern, a gradient smaller
  than its box) is drawn by the browser alone at the box's size and becomes a
  picture fill on a layer named `Background texture (raster)`, in its place
  between the native layers (`Background layers` above it); each is listed as
  a `background-rasterized` issue. Never a wrong approximation.
- *Paint order.* Positioned children and their contents stack as in CSS
  (stacking contexts, z-index, then tree order), also inside flex and grid
  boards: a step number drawn over a route line stays on top.
- *Whole pixels.* A painted box (fill or border) sits on whole pixels, as
  Chrome paints it; Penpot would draw half-tone seams at fractional edges. A
  fixed size inside a layout never grows by the snap (a full row can't wrap
  when Penpot lays it out again), and component copies compare with their
  main by the unsnapped boxes.
- Text in `aria-hidden` elements is drawn: it hides text from screen readers,
  not from the screen.

What stays approximate (inset shadows other than rings, Penpot's own dash
lengths, groove/ridge/inset/outset borders drawn solid as
`border-style-approximated`, some background positions) is listed as issues,
never hidden.

Fixture pages: `configs/design/testpages/html-fixtures/` (atlas, pulse, harbor,
rich: the queue #31 details; vendored OFL fonts). `design_homepage_v2_fixture` runs the whole flow with
script stand-ins and no models (fixture concepts, build and reviews) but the
real gates, measure, convert and verify, so gates, resume and conversion are
proven at $0.

Stage receipts in `homepage/job.json` record each finished stage and its input
fingerprint: a resumed or re-entered stage with the same inputs is reused, and a
finished stage whose inputs changed is refused rather than repeated.

### v2.1 (queue #8): words, real-use checks and the owner's taste

**Copy deck before concepts.** The copywriter writes `homepage/copy/copy.json`
from the brief: a one-sentence promise (<=25 words), 3-5 headline options
(<=10 words, each with its angle), a subhead (<=35 words), exactly three proof
points (each citing the brief facts it rests on, by number), CTA labels
(verb first, <=4 words), 3-6 FAQ answers, voice notes, defined terms, worked
examples wherever a price, number or rule appears, and each required notice
stated once with its placement (a fictional brief has exactly one fictional
notice; disclaimer words appear nowhere else). The script checks the contract
(lengths, generic CTAs, hedges such as "proposed" or "in the demo", numbers the
brief does not support, arithmetic in worked examples), then the content critic
reviews it, the copywriter revises (one `CHANGES.md` line per finding) and the
script checks again: every finding must quote the deck word for word (others are
dropped), and every blocking finding (severity >= 3) must be gone or answered in
`CHANGES.md`; up to two more revisions, then the run fails. `COPY-DIFF.md` keeps
the words before and after. Concepts must use one of the deck's headlines word
for word, and the built page must show each notice exactly once and no hedges
outside it.

**Content review of the page.** After each build or revision the content critic
reads the page's text (from the runtime stage, as the browser shows it) and the
screenshots, and checks clarity, specificity, jargon, consistent terms,
scannability, CTA clarity, worked examples, notices, unsupported claims and drift
from the deck. Findings carry element + quoted text + problem + suggestion +
severity (anchored 0-4); the combine stage keeps only findings whose quote is on
the page, and severity >= 3 blocks.

**Runtime checks** (`configs/design/bin/design_runtime_checks.py`, no model) run
the built page in the shared browser: Tab order (no keyboard trap, no positive
tabindex, every visible control reachable), visible focus on every stop (a
visible change against the unfocused page, an outline indicator at least 3:1,
not hidden off screen or under sticky parts), accessible names (words in every
name, alt on images, no placeholder-only fields, an aria-label that contains the
visible label), reflow at 320 x 640 (no sideways scroll, no clipped text), 400%
zoom (a 320 x 200 CSS viewport: fixed or sticky parts covering at most 40%, no
sideways scroll or clipped text, zoom allowed), WCAG 1.4.12 text spacing at 1440
and 390 (line height 1.5, paragraph 2 em, letter 0.12 em, word 0.16 em: no text
newly clipped or spilling), reduced motion (no moving or looping animation still
declared under `prefers-reduced-motion: reduce`; short fades allowed) and
hover/focus states on links and buttons.
Findings go to `review/runtime/` (RUNTIME.md, runtime.json); failures (severity
3; missing hover 2) block like the other critics. Planted proof page
`configs/design/testpages/runtime/planted.html` (nine plants listed in
`expected.json`) and a clean control `control.html`: all nine found, 0 false
alarms on the control (`design_runtime_checks.py --fixture-proof`).

**Revision loop (v2.2, queue #32).** Three fixed rules, no model, keep
revisions honest:

- *The signature in the first screen.* The measure stage finds the chosen
  concept's signature element (`data-signature`, which the page rules ask the
  designer for, or else the element whose name shares the most words with the
  signature move) and measures its bounding box at 390 x 844 and 1440 x 900,
  reduced motion, page at the top, minus any fixed bar over it
  (`review/signature.md`, `signature.json`). When the concept puts it first (its
  move says hero, first screen and the like, or it sits in the first section),
  the first screen must show a quarter of its height of it (211 px on mobile,
  225 px on desktop) or all of it if shorter; otherwise the fix list gets a
  severity-3 `measure` item with the numbers. The next round measures again.
- *Repeats.* A blocker that matches one the reviser was already asked to fix
  (same rule for measure and runtime; the same words for content; the same
  check and enough shared words for craft and usability; any finding about the
  signature missing from the first screen matches the measure item) goes back
  as REDESIGN (rework that section, not a tweak) or, for words, REWRITE, with
  the earlier rounds and the reviser's answers from `REVISION.md`. A content
  finding raised in an earlier round joins the fix list past the six-minor cap
  as RAISED BEFORE: fix it or say why the words stay. `decision.json` records
  per round the blockers with the rounds they were seen in, the content repeats,
  the signature numbers and kept text; the handoff lists them round by round.
- *Kept text.* The runtime stage records, per block at 1440 and 390, what is
  shown and what assistive tech reaches (text outside `aria-hidden`/`inert`,
  visually hidden text, alt, aria-label). From round 2 it compares with the
  previous round's `raw.json`: words a matched block no longer gives assistive
  tech, or screen-reader-only text that is gone, are a severity-3 `kept_text`
  finding (WCAG 1.3.1, 4.1.2). Rewritten or removed visible content is the
  content review's business, moved words and spelled-out letter tiles are not
  losses, and a loss stays flagged in later rounds until it is given back. A
  previous round recorded before this check is reported "not compared", never
  passed. Each round's page is kept in `homepage/rounds/rNN/site/`.

**Owner taste file.** The direction and final gate stages save each answer (the
choice, the options passed over, who decided, the reasons and the answer's own
words) in the workspace (`homepage/taste/entries.json`). The host launcher
(`~/design-lab/tools/homepage_v2_control.py`) appends each new answer once to
`~/design-lab/taste/owner.md` (private, host only; fixture answers go to a
separate `fixture.md`), each entry headed with who decided (only an owner answer
is quoted as the owner's words), and passes the file into the next run as
`taste_md`. The
art director must say for each concept how it uses the taste file (`taste_use`,
citing entries T1, T2 ... once there are any); the contact sheet shows it.

**Craft-critic benchmark (queue #10).** `design_craft_bench` runs the live craft
critic (`design_homepage_craft_critic_v2`; its v2 prompt since queue #39) on
one page of `configs/design/testpages/craft-v1/` (two clean homepages for two
fictional products and variants that each carry one measurable craft
problem), or of `quarry-v1`. Its
prepare step copies the page and its fonts into `homepage/site` and writes what
a live review round shows the critic through the same code as the measure stage
(`write_review_inputs`: screenshots and facts with the page checks, brief,
craft facts, direction);
there are no category references for test pages, so `review/references.md`
says so. Its collect step checks and summarises `review/craft/craft.json`. One
run per page, about $0.5-0.6 each:

```json
{"workflow":"design_craft_bench","workspace_path":"/app/workspaces/<fresh>",
 "inputs":{"site":"/app/configs/design/testpages/craft-v1","page":"page-03"}}
```

Which pages carry which problems, the bars and the grading rules stay on the
host (`~/design-lab/answers/craft-v1.yaml`, sealed before any model run;
`~/design-lab/specs/craft-v1.md`); findings are graded there for recall, false
alarms on the clean pages and run-to-run stability. Nothing on the box may hint
at the plants (`tests/test_design_craft_bench.py` checks).

**Pairwise judge (queue #10, advice only).** `design_pairwise_judge` shows the
judge (`design_pairwise_judge`, opus) one homepage, or two under neutral
letters, as screenshot tiles the host lays out in the run's workspace:
`judge/task.json` (`{"mode": "pair" | "single", "pages": ["A", "B"]}`) and, per
letter, `judge/<letter>/brief.md`, `desktop-NN.png` (1440 wide) and
`mobile-NN.png` (390 wide). It rates each page 1-5 on "would this wow its
visitor?" and picks the stronger of a pair (no ties; strength slight, clear or
strong); the `check` step validates `judge/verdict.json` and flags a pick that
contradicts the ratings. Which page is which version stays on the host. Run
each pair twice with the letters swapped to see position bias. Its picks are
recorded beside the owner's blind picks on `~/design-lab/scoreboard.md` to
measure agreement; they never approve anything. Tests:
`tests/test_design_pairwise_judge.py`.

Tests: `tests/test_design_homepage_v2.py` (recorded scenes in
`tests/design_homepage_v2_scenes/`, fake Penpot), `tests/test_penpot_layout.py`
(hand-made scenes: flex, wrap, grid, cards, fallbacks, variants, text line
boxes, constraints, baseline rows, max-width blocks, boxes fitted to their
content, texts that rewrap) and `tests/test_design_runtime_checks.py`
(recorded browser results in
`tests/design_runtime_scenes/`). Live converter proofs, editor
checks, fixture and paid runs: `/home/shinelay/design-lab/results/homepage-v2/` on spark;
v2.1 proofs in `/home/shinelay/design-lab/results/homepage-v2.1/`; reflow proofs
(text and width edits in the real editor) in
`/home/shinelay/design-lab/results/penpot-reflow/`.

## Local image models (queue #36)

Design steps can make pictures (3D objects, textures, backgrounds, product
scenes, illustrations, patterns), edit a picture by instruction, and cut a
picture into transparent RGBA layers, with open models that run on the host:
no key, no cost, nothing leaves the machine. The models, their licences and
the service itself live outside this repo (`~/opt/image-gen/README.md` and
`LICENSES.md` on spark); every model in use is Apache-2.0, so the images can
be used commercially.

| Command | Model | What for |
|---|---|---|
| `generate` | Z-Image Turbo (default, 8 steps) or Z-Image (`--model z-image`, 30 steps) | text to image, 256-2048 px a side |
| `edit` | Qwen-Image-Edit-2511 (`--quality fast`, `balanced` or `full`) | change an image by instruction, up to two reference images |
| `layers` | Qwen-Image-Layered | transparent layers from a prompt or from an image |

The helper is `configs/design/bin/design_image.py` (standard library only).
In a run container:

    "$TEMPER_PYTHON" /app/configs/design/bin/design_image.py generate \
        --prompt "..." --size 1536x640 --seed 7 --out images/hero.png

It finds the service at `$IMAGE_GEN_URL` (`http://HOST:PORT` or
`unix:///path`), else at the socket `/app/local/image-gen/gateway.sock` (run
containers mount the host's `local/` folder read-only, and unix sockets work
through read-only mounts), else `~/temper-ai/local/image-gen/gateway.sock` on
the host, else `http://127.0.0.1:8190`. No port is opened to the docker
network.

Every PNG is written with `<name>.provenance.json` beside it (schema
`design-image-provenance/1`): model, weight files and revisions, licence,
prompt, seed, size, settings, inputs (sha256), seconds and memory. `layers`
writes `<name>-layer-N.png` and one provenance file for the set. One JSON line
on stdout says where the files are.

Exit codes: 0 written; 2 the call is wrong (bad option or input image);
3 the service can't do it now (not running, busy, low on memory, timed out);
4 the job failed. On 3 or 4 a design step makes the picture in code instead
(CSS or SVG gradients, shapes, patterns); it never waits on the service.

Rules (Design handbook 5.5): no words inside generated images (text stays live
HTML on top; the helper warns when a prompt asks for words); keep the
provenance file with the image; only models listed in the service's licence
manifest; prompts carry the product's style family so a product's images
look like one set.

Tests: `tests/test_design_image.py` (a fake service on a unix socket or TCP; no
model, GPU or real service).
