# Design reviews

Original editable-vector identity work: [Logo workflow and contracts](design-logo.md).
The logo workflow uses new Design-owned agents; reviewers and sealed review
benchmarks described here are unchanged.

`design_review` is an expert review of a product's pages: what a senior designer
and an accessibility auditor would flag. It is the design role's first workflow,
and the critic and grader that later design workflows reuse. Who owns it:
[departments.md](departments.md).

```
capture (script) -> [ critic_a | critic_b ] -> merge
```

- **capture** (no model): opens each page in temper's browser (playwright-mcp)
  at each viewport (desktop 1280x800, mobile 390x844), saves screen-sized
  screenshots, runs axe-core 4.13.0, and measures what tools can measure:
  contrast, type sizes, headings, line length, target sizes, weak boundaries,
  where each form field's name comes from, unnamed graphics, overflow at
  390 px, landmarks, and a Tab walk with the focus ring of each stop.
- **critic_a, critic_b**: the same agent run twice, apart. Each reads every
  page's screenshots and facts in one go, so it can also check consistency
  across pages. It judges what no tool can: hierarchy, wording, flow, states,
  consistency, and the WCAG 2.2 AA points that need a person (Nielsen's 10
  heuristics, severity 0-4). It never contradicts a measured number.
- **merge**: groups the same problem found twice, and sorts each finding into
  *confirmed* (measured, or found by both critics), *single* (one critic: a
  person checks it) or *rejected* (the facts contradict it). Writes
  `review/report.md` (fix-first list, then each page) and
  `review/findings.json`.

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

A run of four pages takes about 7 minutes and $1.70-1.90.

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

fernway-v1 is too easy to tell versions apart: the next test site needs
subtler plants.

## Files

| Path | What |
|---|---|
| `configs/design/workflows/design_review.yaml` | the review |
| `configs/design/workflows/design_review_grade.yaml` | the grader |
| `configs/design/agents/design_{capture,critic,merge,grade,score}.yaml` | its steps |
| `configs/design/bin/design_capture.py` | capture: serves a site, drives playwright-mcp, writes `review/shots`, `review/facts`, `capture.json` |
| `configs/design/bin/design_measure.js` | the in-page measurements |
| `configs/design/bin/vendor/axe-4.13.0.min.js` | axe-core (MPL-2.0) |
| `configs/design/bin/design_trial.py` | review + grade on a test site (host) |
| `configs/design/testpages/<site>/`, `<site>.json` | test sites and their brief and pages |

## Editable Penpot homepage workflow (v1)

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

`design_homepage_v2`: brief -> 8-12 category references (screenshots, research
only; never copied or traced) -> art director drafts three named concepts (a
~400-word brief each, licensed display + text fonts, dominant colour + accent,
imagery, one signature layout move, one motion idea; hero + one section at 1440
and 390) -> automatic check -> art director refines from its renders -> check
(up to 3 more refine loops) -> **owner direction gate** -> designer builds the
full page -> measure (capture, axe, craft metrics) -> the unchanged
`design_critic` x2 + `design_merge`, plus the new craft critic -> combine (at
most 2 automatic revisions) -> convert to Penpot -> verify -> handoff -> **owner
final gate** (approve, or request changes: one more revision round, at most twice).

Agents (all `provider: claude`, `model: opus`, so they can read PNGs):
`design_homepage_art_director_v2` (phase draft|refine),
`design_homepage_designer_v2`, `design_homepage_craft_critic_v2` (writes to
`review/craft/`, never `review/critic/`, so taste never mixes with usability
findings; advisory, the owner decides taste) and `design_homepage_reviser_v2`.
Everything else is the script stage `design_homepage_stage_v2`
(`configs/design/bin/design_homepage_v2.py`).

### Inputs and gate answers

- `brief_json`: product, category, audience, purpose, cta (<=40 chars),
  `fictional` (bool; fictional needs a disclosure line), at least three facts
  (the only source for claims on the page), optional assets (path, alt, kind
  screenshot|logo|photo) and brand.
- `references_json`: 8-12 `{name, url (https), why}`.
- Direction gate: `{"concept": "A"|"B"|"C", "approval": "owner-direction", "notes": "..."}`.
- Final gate: `{"approval": "owner-final"}` or
  `{"verdict": "request_changes", "notes": ["..."]}`.

The fixture workflow accepts only `"approval": "fixture-test"` and records no
owner approval; the real workflow refuses fixture briefs and fixture answers.

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

Verify reopens the saved file and checks every layer, text, colour, typography,
component and instance; exports PNG and SVG from Penpot itself (SVG with its
fonts and images embedded, same host only); and compares each width's Penpot PNG
with the browser render. Fidelity bar per width (`FIDELITY`): same size; pixels
differing by more than 48 (with a 1 px shift allowed) at most 2.0% overall,
1.0% outside text and 12.0% inside text boxes (anti-aliasing and font
hinting differ there); and in 32 px tiles at most 20% differing and a mean
difference of at most 40, so a single lost card cannot hide in a page-wide
average. Approximations (inset shadows other than rings, dash lengths, some
background positions) are listed as issues, never hidden.

Fixture pages: `configs/design/testpages/html-fixtures/` (atlas, pulse, harbor;
vendored OFL fonts). `design_homepage_v2_fixture` runs the whole flow with
script stand-ins and no models (fixture concepts, build and reviews) but the
real gates, measure, convert and verify, so gates, resume and conversion are
proven at $0.

Stage receipts in `homepage/job.json` record each finished stage and its input
fingerprint: a resumed or re-entered stage with the same inputs is reused, and a
finished stage whose inputs changed is refused rather than repeated.

Tests: `tests/test_design_homepage_v2.py` (recorded scenes in
`tests/design_homepage_v2_scenes/`, fake Penpot). Live converter proofs, editor
checks, fixture and paid runs: `/home/shinelay/design-lab/results/homepage-v2/` on spark.
