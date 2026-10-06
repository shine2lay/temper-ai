# Design files and the research step

Every design workflow (homepage, logo, the app-screen workflow, later marketing pieces) first checks
whether the product already has approved **design files**. If it has, the design follows them. If it
has none, or only some, the workflow **researches** the product before it designs: who the users are,
the context they use it in, what people in that context like and trust (the context playbook,
`configs/design/knowledge/context-playbook.json`), and what the product's category looks like. Design
decides on a one-page research board; the designs follow that decision; and when Design approves the
final design, its direction and tokens are saved as the product's design files, so the next design for
that product follows them and skips the research. (Design queue #38, owner request 2026-10-04.)

Code: `configs/design/bin/design_files.py` (convention, registry, inventory, host commands),
`configs/design/bin/research_contracts.py` (what the research must contain),
`configs/design/bin/design_research.py` (the research stages). Tests:
`tests/test_design_files.py`, `tests/test_design_research.py`.

## A product's design files

A folder with:

| File | Holds |
|---|---|
| `DESIGN.md` | Header, then sections Users, Direction, Tokens, Logo, Library, Approvals |
| `tokens.json` | Design tokens in the DTCG 2025.10 format, one top-level group per token part |
| `logo/` | Optional: the approved logo files (SVG), listed in the Logo section |

The **parts** are `users`, `direction`, `colour`, `type`, `spacing`, `radius`, `elevation`, `motion`,
`logo` and `library`. Each part carries a status: **draft** or **approved**, who approved it and the
date. Who approves: `design` (the Design role, with its reasons), `owner` (only when he approved it in
his own words, which are quoted verbatim with where he said them), or `fixture-test` (fixture
registries only: a fixture never claims a Design or owner decision).

### DESIGN.md

```markdown
# <Product> design files

Product: <registry id>
Updated: YYYY-MM-DD
Format: design-files v1

## Users
Status: approved by design on 2026-10-05

### Dispatchers
Also called: dispatch planners; load planners
- Work 10-hour shifts on two large monitors. [source/docs/interviews.md]
- ...  (every line cites a source in the pack, a URL, or says "assumption")

## Direction
Status: draft
Contexts: marketing-landing-general (page); rollcall-trader-workspace (product, nearest)
Evidence: E001, E118, E165
Name: <direction name>
Family: <a styles string the playbook allows for the context, quoted exactly>
Axes: density medium; type scale compact; colour energy low; motion low; copy tone expert
Principles:
- ...
Do:
- ...
Don't:
- ...

## Tokens
Values live in tokens.json (DTCG 2025.10); each part's status:
- colour: approved by owner on 2026-10-03
- type: missing
- ...

## Logo
Status: approved by owner on 2026-10-03

Files: logo/<name>-lockup.svg, logo/<name>-symbol.svg
Rules:
- minimum sizes, clear space, what the approval covers

## Library
Status: missing

## Approvals
- colour: owner on 2026-10-03: "<his words, verbatim>" (<where he said them>)
- users: design on 2026-10-05: <reasons>
```

Every section starts with its `Status:` line (`approved by <who> on <date>`, `draft` or `missing`).
The Tokens section mirrors tokens.json's statuses; every approved part has a matching Approvals line.

### tokens.json

DTCG 2025.10: tokens have `$value` and a `$type` (their own or the nearest group's); colours are
objects `{"colorSpace": "srgb", "components": [r, g, b], "hex": "#RRGGBB"}`; dimensions and durations
are `{"value", "unit"}`; aliases are `"{group.token}"`. This convention adds: the top-level groups are
the token parts (`colour`, `type`, `spacing`, `radius`, `elevation`, `motion`), and each carries its
status in `$extensions`:

```json
"colour": {
  "$type": "color",
  "$extensions": {"com.temper.design-files": {"part": "colour", "status": "approved",
                                              "approved_by": "owner", "date": "2026-10-03"}},
  "ink": {"$value": {"colorSpace": "srgb", "components": [0.102, 0.102, 0.0902], "hex": "#1A1A17"}}
}
```

Types used: `color`, `dimension`, `fontFamily`, `fontWeight`, `duration`, `cubicBezier`, `number`,
`shadow`, `typography`. `design_files.py check <folder>` checks a folder.

## Where the files live: the registry

`configs/design/products.yaml` records each product's design-files location and its parts' statuses
(**locations and statuses only**: no design content, research notes or anyone's words; this repository
is public).

```yaml
version: 1
repos: {rollcall: ~/rollcall}
products:
  rollcall:
    name: RollCall
    location: {kind: repo, repo: rollcall, path: design}
    current_state: [frontend/src/styles/tokens.css]   # audited, not followed
    parts: {}
```

- The files belong with the product, in its own repo when it has one (`kind: repo`). For a repo
  Design does not own, the files go through a handoff and the owning chat lands them.
- `kind: lab` keeps them in Design's private lab (`~/design-lab/<path>`), for example while an
  identity is unpublished.
- `current_state` lists an app's existing CSS or screens: research audits them as the current state,
  never as rules.
- `force_research: true` (or a list of parts) makes research run even for approved parts.
- A **fixture registry** (`fixture: true`) holds fictional test products; all its approvals say
  `fixture-test`. Fixture products never enter the real registry.

## Defined, partial, none

The model-free inventory (`design_files.inventory`) compares what the job needs with what is approved.
A part counts as approved only when the registry and the files agree on it (status, who, date); if
they disagree the run stops rather than guess.

| Job | Needs | Also follows when approved |
|---|---|---|
| homepage, app_screen | users, direction, colour, type, spacing, radius, elevation, motion | logo, library |
| logo | users, direction, logo, colour | library |
| marketing | users, direction, colour, type, logo | library |

- **defined**: approved files cover every needed part. No style research. The workflow follows the
  files and only checks the job's audience against the approved users profile. If the job names an
  audience the profile lacks, it researches that audience only and leaves the visual system unchanged.
- **partial**: some needed parts are approved (for example Temper's logo and palette). Research covers
  only the missing parts; the approved parts are fixed constraints, copied byte-identical into outputs.
- **none**: nothing approved. Full research. An app's existing CSS or screens are the current state
  to audit, not rules.

Research parts: users research when `users` is missing (or the audience gap above); direction research
(playbook context fit and 2-3 direction candidates) when `direction` is missing; a category scan when
direction research runs, or for a logo job without an approved logo.

## Host commands (design_files.py)

| Command | Does |
|---|---|
| `pack --product ID --source DIR --workspace W [--registry R]` | Copies the source material (README, docs, owner notes) to `W/source/docs/`, the product's design files to `W/design-files/`, its current-state files to `W/source/current-state/`, and writes `W/source/pack.json` with every file's hash. The run checks the hashes; a changed pack stops it. |
| `apply --workspace W [--registry R]` | After a run's final approval: copies `W/design-files-out/` to the product's location (old files kept under `.history/`) and records the approved parts in the registry. For `kind: repo` it writes a handoff folder instead; the owning chat lands it. |
| `approve --product ID --part P --by design --reasons ...` | Marks one part approved in lab-kept files and the registry. `--by owner` needs `--words` (his own, verbatim) and `--source`. |
| `inventory --product ID --job homepage [--audience ...]` | The host's view of defined, partial or none. |
| `check FOLDER`, `registry-check` | Format checks. |

## The research step

Runs when the inventory says so (none or partial; or an audience gap). Shared by every design workflow:
the same two agents (`design_research_users_v1`, `design_research_direction_v1`) and the same stage
script (`design_research.py`, agent `design_research_stage_v1`); each workflow wires the same nodes
before its own design stages. Every stage keeps a receipt in `research/state.json`, so a resumed run
never repeats a finished (paid) stage. A stage whose saved inputs changed refuses to run (a reused
workspace), except the three that only record what earlier files say: the research gate, the decision
and the logo brief. When a fork or a rerun assembles the research again, or the gate is answered
again, those three are worked out again (the decision also when `design_research.py`, whose rules
write `FOR_DESIGN.md`, has changed); the earlier receipt stays under `superseded` in
`research/state.json`, and an earlier gate answer stays as `research/gate-superseded-<n>.json`.

1. **Product, users and contexts** (`design_research_users_v1`): what the product does, for whom, its
   value and meaning; who the users are (jobs, expertise, frequency, devices, setting, stakes, access
   needs). Sources: the pack and web research. Every claim cites a pack file or a URL with an exact
   quote, or is marked an assumption. Unsourced statements in the pack stay assumptions or are rejected;
   when a newer source contradicts an older one, the older claim is marked superseded. The check
   (`users_check`) finds every quote in its pack file (and fetches web sources); a miss sends the work
   back (stage `check`, at most two revisions). The output is USERS.md-compatible. The same agent picks
   6-10 category leaders and close competitors (`research/category/pick.json`).
2. **Category scan** (`capture`): the first screen of each picked site at 1440x900 through
   playwright-mcp, measured on the five audience axes (`design_axes.py`: first-screen fill, type sizes,
   colour saturation and lightness spread, animations, copy tone); blocked or empty pages don't count,
   and at least 4 must be usable. Captures stay in the run workspace and Design's lab, never in this
   repo.
3. **Context fit and directions** (`design_research_direction_v1`): the playbook contexts that fit
   (one page context for page jobs, plus product or audience contexts), with reasons; 2-3 direction
   candidates, each a style family the playbook allows for a chosen context (quoted exactly), with the
   five audience axes (density, type scale, colour energy, motion, copy tone), what to follow and
   differentiate, evidence ids, and assumptions to confirm. It also reads the category from the
   screenshots: what users will expect (with the sites that show it), where the product can stand out,
   and, for logo jobs, every captured site's mark (family and description). Approved parts stay fixed.
   The owner's taste file is recorded as a bias, apart from the evidence.
4. **Assemble and check** (`assemble`): `research/RESEARCH.md`, `research/research.json` (the
   playbook's recommendations for each chosen context are copied in verbatim with their evidence ids
   and confidence) and a one-page board (`research/board/board.png`, rendered from code; text at least
   16 px and contrast at least 4.5:1, both measured). Checks: every evidence id exists in the playbook,
   every direction family is allowed for its context, the category read names captured sites, schema;
   a miss sends the director back (at most two revisions).
5. **Research gate** (`research`): Design confirms or corrects the users and picks a direction, with
   reasons (answer below). On by default whenever research ran; `research_json` `{"gate": "off"}`
   switches it off (the recommendation is then recorded with `decided_by: null`). Skipped on the
   defined branch. Fixture runs answer `fixture-test`. The record (`research/gate.json`) keeps the
   sha256 of the research and users profile it answered (`answered`); when a fork assembles the
   research again, the decision refuses the old answer until the gate is answered again, and the
   earlier answer stays on record as `gate-superseded-<n>.json`.
6. **Decision** (`decision`): writes `research/decision.json`, `research/FOR_DESIGN.md` (what the
   copywriter and art director read) and `research/fixed.json` (the approved parts, their colours and
   fonts, and the five audience targets of the chosen direction; the homepage concept check measures
   each concept against them). Approved colours cannot be darkened for contrast, so where no other
   approved colour reaches 4.5:1 on one of them, FOR_DESIGN.md says so (only large text on it, or none
   below 3:1), and the concept check accepts that approved pair at 3:1; axe then checks the text each
   page actually puts on it (4.5:1, or 3:1 for large text).
7. **Logo brief** (`logo_brief`, logo jobs): the brief gains the playbook context of the product
   (`context`), the product's meaning (`meaning`), the captured first screens plus a marks table as
   pinned research (`research`, read by every logo agent through `logo/comparison.md`) and an approved
   palette (`fixed_palette`), which the palette stage must keep (`logo_contracts.fixed_palette_check`:
   every logo role takes an approved colour or white paper; token names are not matched to roles,
   because a product's `accent` need not be the logo's accent). The merged brief is checked by the
   logo brief contract right here, so a missing brief fails at this step, not later.

Research gate answer:

```json
{"decided_by": "design", "direction": "D1", "users": "confirm",
 "corrections": [], "reasons": "why this direction for these users"}
```

`users` is `confirm` or `correct` (then `corrections` lists them). `decided_by owner` only with his
own words in `notes` and where he said them in `source`.

## Saving

After the workflow's final gate approves, `save_files` writes `design-files-out/` in the run:
DESIGN.md and tokens.json with every part the run made marked approved by the final gate's
`decided_by` on that day, and `registry-update.json`. What a run makes:

- every run with research: users and direction, from the research decision;
- a homepage: colour, type, spacing, radius, elevation and motion, measured from the final page;
- a logo: the logo (the approved exports, checked against their hashes, and BRAND.md under `logo/`;
  the Logo section names the files, the mark, the wordmark font, clear space and smallest sizes) and,
  when the colour part is not approved yet, the palette chosen with it. When it is approved, the
  logo's colours must all come from it, or the save stops.

Every part approved before the run stays exactly as it was (tokens byte-identical, its DESIGN.md
section and approval line unchanged), including parts this job does not use: a logo run keeps an
approved type scale. A run replaces an approved part only when it was forced. A logo run on a product
whose logo is approved and not forced stops at its logo brief, before any paid logo stage. The host
then runs `design_files.py apply`, which refuses files that drop or change an approved part. The next
design for the product takes the defined branch for the parts now approved.

## Workflows

`design_homepage_v2_next` and `design_logo_v1_next` are the candidates with the research step (beside
the live workflows until they win their trial; docs/design.md, docs/design-logo.md), with $0 twins
`design_homepage_v2_next_fixture` and `design_logo_v1_next_fixture` (model-free stand-ins from
`configs/design/fixtures/research/<product>/`). Their inputs add `research_json`:

```json
{"job": "homepage", "audience": "", "gate": "on", "force": [], "directions": 3, "taste_md": ""}
```

`job` is homepage, logo, app_screen or marketing; `audience` names the page's audience when it differs
from the product's users; `force` lists parts to research even when approved. The research gate is
answered through the API like every gate (no agent answers it). `design_logo_v1_next` also takes `mode`:
`real`, or `trial` for a fictional brief with the real agents (its gates are then answered
`fixture-test`). The run's workspace must hold a pack made by `design_files.py pack`.
