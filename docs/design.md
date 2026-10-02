# Design reviews

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
