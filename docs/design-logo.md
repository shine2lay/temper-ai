# Original editable-vector logo workflow v1

Design owns `design_logo_v1` and all `design_logo_*_v1` agents. This is new identity
work, not a change to live design reviewers, EPD, app branding or engine access.

```
sourced brief + pinned research -> BUDGET -> six original monochrome vectors
 -> native rough PNG -> explorer sees that render and redraws -> sketch PNG
 -> three different shortlists + role palettes -> native equal-scale boards
 -> new logo critic -> REAL OWNER DIRECTION (a direction, or explore-again: the
    run ends and the next run's brief carries the rejected round) -> FRESH BUDGET
 -> selected refinement -> native source/exports -> new logo critic -> handoff
 -> REAL OWNER FINAL (or one bounded rewind for the second refinement)
```

Generation comes from a vision-capable Claude-provider LLM's own bounded vector
objects, not a fixed Temper icon catalogue or a meeting-room template. Native
Penpot boards are deterministic presentation layouts, not generated logo forms.
`design_logo_fixture_v1` is separately named, model-free and explicitly fictional;
its deterministic test shapes never pass as original generated Temper artwork.
It still pauses at native direction/final gates and never claims owner approval.

## Inputs and bounds

The outer Temper run request **must** set `workspace_path` to a fresh existing
absolute host directory. The server mounts that directory into the isolated run.
This is run context, not a fictional-mode or approval input. Missing/relative/
unavailable workspace fails before login, native creation or paid generation.
The generic start tool lacking an outer workspace parameter is not a valid
launcher here: use the same Temper API run request with explicit workspace.
Artifacts must survive a failed/removed container; preserve its native file UUID.

The candidate stage uses strict template variables and safe public diagnostic
exit codes:21 missing isolated container,22 malformed run UUID,23 unavailable
absolute workspace,24 invalid mode,25 invalid stage,26 invalid budget phase,
27 missing native artwork gate,28 workspace diagnostic directory unwritable,
29 canonical native source unavailable.31–39 classify only fixed native guards/
exception classes. No captured stdout/stderr, input text, environment values or
arbitrary error strings are saved in diagnostics. After valid context, append
receipts under `workspace/logo-native-diagnostics/`, bound to run UUID/mode/stage;
these are failure evidence, never successful source/export/approval proof.
The first isolated native retry failed before any saved job state. Its generic
exit1 and missing script stream did not identify a cause; do not infer a mount,
credential or geometry error without these safe checks. This stage-only
instrumentation changes no engine access, login grants or live reviewers.

Real entry takes only `brief_json` and `budget_json`. No ordinary mode/direction/
final/approval input exists. Brief fields: product, secondary_name, explicit
fictional boolean, audience, positioning, qualities, avoid, sources (id/location/
fact/status), interpretations. V1 supports bounded Latin/LTR names/live text and
Source Sans Pro regular/semibold. Unsupported shapes/text fail rather than fall
back. Facts, claims, inference and creative name interpretations stay separate.
`logo_contracts.py` is the exact schema/rubric, saved as `logo/schema.txt`.

- Six unique monochrome concepts, shortlist three genuinely different meanings/
  silhouettes, recommendation with trade-offs. Hash uniqueness is only a
  duplicate guard, NOT semantic distinctiveness or originality proof.
- One to eight original filled rects/ellipses/closed paths per symbol. Coordinates
  0..100, finite; M/L/C/Z, max64 commands/path and192/concept. Empty negative space,
  not paper-coloured fake counters. No image, SVG strings, executable code, URLs,
  arbitrary resources, catalogue/stock assets or unbounded geometry.
- Six sRGB roles: ink/paper/accent/accent_on/muted/surface. Measured text pairs
  >=4.5, demonstrated essential-graphic pairs >=3. Logo/logotype exemptions are
  stated separately. Palette scores are not a universal colour-emotion claim.
- Source labels/type styles/role colours remain editable and library-referenced.
  D3's save/Transit/font-cache/portable-WOFF client is reused, NOT its layouts.
- One new critic per review; initial shortlist plus maximum two selected reviews.
  Element/location/evidence/suggestion required, max14 observations, no quality
  score. Preserve advice, changes and declined points. Owner decides taste.
- Advisory prose (critic element/location/evidence/suggestion/reasons, palette
  rationale, revision notes, refinement changes/declined) that overruns its bound by
  up to four times is shortened with an ellipsis instead of failing the paid stage
  (real run ad5c270f lost a round-1 critic save to a 129-character location).
  Ids, names, owner words, geometry and longer text stay strict.
- Exactly two refinement rounds maximum. Engine max_loops=2 permits only one
  rewind (its threshold counts the stopping attempt); script bounds independently
  forbid a third. Failed final revision is not successful completion.

## Changes after the first real Temper round (2026-10-03)

The owner rejected all three round-1 directions (run 6b9790e9): "None: fix the
workflow and explore again". Weak spots it showed, and the fix for each:

- No way to say "none": the direction gate accepts `decision: explore-again`
  with the owner's own `owner_note`. The run records `explore-again.json` (the
  rejected shortlist, the owner's answer) and every later node is skipped by
  condition, so nothing is refined or spent. The next run's brief carries it in
  `prior_rounds` (at most two), with that round's boards as pinned research.
- The run never saw the research screen: an optional brief `research` block
  names an absolute folder and its files pinned by sha256 (`comparison.md` plus
  up to 15 PNG/MD files). The brief stage copies them into `logo/research/`,
  failing on any changed, linked or oversized file, and writes
  `logo/comparison.md` listing the images, rejected rounds and notes. Explore,
  palette and critic read it. The folder must be visible inside the run: put
  it inside the run's own `workspace_path` (for example `research-input/`);
  `~/design-lab` is not mounted.
- Ideas were described but not visible (the "shifted half" never showed): a
  second explorer pass opens its own render and redraws, recording what it saw
  and changed (`revisions`); the shortlist is made from these sketches.
- Plain primitives, forgettable: each concept declares a family
  (geometric/letterform/pictorial/emblem), an `ownable_detail` and a
  `generic_risk`; six concepts span three families with at most two geometric,
  the shortlist two families. Holes use nonzero winding (inner subpath drawn the
  other way), never paper-coloured patches.
- Board text cut mid-word: descriptions are fitted by whole words with an
  ellipsis; measurements keep `full_text`/`abridged`, and any rendered text that
  is not the full text or a whole-word prefix is a violation.

These are prompt/contract fixes checked by model-free tests and the fictional
fixture; whether round 2 is better is the owner's judgement at the real gate.

## Colour in the mark (round 2 direction gate, 2026-10-03)

The owner picked an anvil-shaped T and asked for "some color on it", but
symbols could only be drawn in one colour. A shape may now carry
`tone: 'accent'`: colour versions (primary, secondary, reverse, symbol, symbol
reverse, 512 avatar, actual-size board) draw it in the palette accent, while
monochrome versions draw every part alike. A colour mark keeps at least one
untoned part. Accent legibility on both backgrounds rests on the existing palette
rule (accent >= 3:1 on paper and on ink). Exploration boards stay monochrome. A
refinement reads the current schema from `logo/schema-refine.txt` (named in
`refine-context.json`), so a run started before this change keeps its pinned
`schema.txt` intact for resume checks. The fixture's chosen direction has an
accent part, so the $0 run proves native save, reopen and export of two-tone vectors.

## Measurable rubric versus judgement

Measure source identity/set/geometry, live spelling/style refs, native text cache,
advance fit/bounds, palette companion contrast, actual exported safe XML and
standalone licensed fonts. Visually inspect same-scale monochrome silhouettes,
negative spaces at16/24/32/48/64px,512 avatar,160/320 lockups, optical balance,
light/dark/reverse, exact spelling and obvious clipping. Recommend an HONEST
minimum; showing16px is not passing16px. Judge purpose/association/distinctiveness
with brief evidence, not invented user-testing or aesthetic scores.

Critic sees an independent fictional Aster board, labelled neutral cells A..E.
Host answer key stays OUTSIDE all mounted repositories, in
`/home/shinelay/design-lab/answers/logo-v1.json`. Contract recall/false findings
must be source-adjudicated separately from real-brand feedback. This tiny board
is a prompt-contract smoke check, not proof of aesthetic quality, general recall,
reliability or equivalence to the sealed homepage/page benchmark. Those remain
unchanged. Dated official-source captures support a bounded similarity screen;
no resemblance to these few examples is NOT uniqueness/trademark clearance.

## Real gates, input fingerprints and partial saves

Every artwork gate response is native gate free text containing JSON. The stage
wrapper passes `--native-gate` only when Temper supplies the actual gate context,
never from an input field or model output. This trusts the host workflow/gate
configuration; it is not an engine-wide cryptographic authentication change.

Direction answer:

```json
{"approval":"owner-direction","run_id":"<full UUID>","brief_hash":"<brief hash>",
 "artifact_hash":"<saved three-board artifact hash>","decision":"<shortlisted id>",
 "reason":"Actual owner choice","owner_note":"Optional actual refinement guidance"}
```

Final answer uses `approval: owner-final`, current selected artifact hash and
`decision: approve|revise`. Revise requires actual owner_note. Real answers must
come from the owner after visible previews. A parent may answer budget gates
within existing authorization but never invent direction/final responses.
The separate fictional fixture accepts only `approval: fixture-test` and records
real approval false. It refuses both a real brief and any name containing Temper.

Receipts bind run UUID, mode, brief/schema and exact stage inputs/artifact hashes.
Identical resume returns completed work, not another paid exploration. Changed
inputs/missing/tampered artifacts fail closed. Keep the same UUID/workspace through
pause/cancel/resume, save original receipts/times and prove paid completed-stage
reuse. Before creation/update, local identity and exact expected-object pending
checkpoints survive failures. Retry may recover the same known empty revision0
file or an exact fully saved file; ambiguous partial/foreign saves fail without
creating duplicates or overwriting. Pending identity is evidence, not rubbish to
remove. No product/owner Penpot file is reused. Fresh authenticated get-file is
required after save; real editor verification remains additional host evidence.

## Budget and retries

Full run estimate/reservation $8.90: initial exploration2.25 + revision pass.75 +
shortlist1.00 + initial critic.85 + (refinement1.00 + critic.85)*2 =8.55, plus.35
headroom (v1 before the revision pass: $8.15). These are conservative planning
estimates, NOT per-Claude-CLI billing caps. Native
budget policy8.90 checks between calls; an in-flight call can overshoot. CLI model
iteration/time bounds do not replace financial supervision. Record all real
costs and any retry, including failures; no automatic artifact-stage paid retry.
Reconcile prior Design experiments and reserve the full bounded envelope before
spending; day spend+reservation <=$10 Pacific and whole trial<=authorization.
If the remaining honest estimate cannot fit, ask or genuinely wait; never split
or change dates. Every refinement budget gate requires a current reservation and
subscription/one-experiment checks. Gate waits may cross dates: recheck then.

Budget JSON fields: pacific_day, reserve_usd, day_spent_usd, trial_spent_usd,
trial_envelope_usd, subscription_checked:true, one_design_experiment:true and
reconciliation. Initial stage reserve>=4.85; each refinement reserve>=1.85;
host must reserve the FULL outstanding trial in the shared ledger, not merely
these stage minima. No paid call while allowance is near limits or deployment
revision/duplicate work is uncertain. Native script and fictional tests cost0.

## Source and portable packet

Existing authorized Design Penpot login only, scoped to that agent's Drafts.
No new account/MCP key/provider/image service. The unchanged D3 client safeguards
secrets and authenticates ownership; credentials never reach an agent/artifact.
New job stages use that client, including its authorized run bootstrap fallback.

Each native source remains an editable file with original vectors/live text/
shared colours/type. Actual PNGs and standalone SVGs come from native exporter.
SVG allows only safe vector/text/defs tags (including Penpot's plain-colour
vector `pattern` fills) and local references. Every pattern child/resource is
still checked; allowing the harmless wrapper never permits raster/script/URLs.
No scripts,
events, foreignObject, raster images, remote URLs/styles or unbounded numeric
attributes. Same installed OFL WOFFs are embedded, not private font URLs or
silent font fallback. Keep source JSON + original TTF/license/name-table/SHA
receipts alongside portable SVG and PNG. Native text cache uses actual advances,
not a kerning/complex-script engine; editor edits can recompute it.

Host must additionally render exports with networking blocked, assert embedded
font loading, inspect real editor/fresh source/edit roundtrip and actual-size
previews. SVG logo-only files without text need no fake font-loading claim.
Reverse transparent variants need a dark background. Preserve symbol/wordmark,
primary/secondary, mono/reverse variants,512px avatar and local light/dark/sidebar/
document previews. Palette tokens, fonts/licences, clear space/minimum/misuse,
dated sources/similarity, all reviews/declines and run/cost/revision evidence are
part of BRAND.md + host packet.

Workflow manifest deliberately leaves workflow_verified/source_verified/
exports_verified false: only independently collected host evidence can set them
in the task result. direction_owner_approved/final_owner_approved are separately
recorded from the real native gates. Publication remains false. No diagnosed
blocker, pending approval, isolated save, test-only shape or unrun workflow counts
as an approved completed identity packet.

## Retained first native fixture failure

Actual model-free run142aa8ee-b591-4eec-bd56-95cc865844b7 ($0) saved a native
Northline rough file, fresh source and native PNG, then the strict SVG checker
rejected a harmless `pattern` wrapper. This was not a vector/path schema error
and does not justify relaxing external-resource, script or raster bans. Its
launcher also omitted the outer persistent workspace; container removal lost
local checkpoints. The populated original file is retained, never overwritten
or treated as an empty-retry source. A new explicitly mounted fictional fixture
must prove persistence and same-UUID cancel/resume before real-brand generation.
Host safe failure/source/export evidence stays in results/temper-logo/control/.
Unit mocks did not detect these two actual-runtime issues. Native proof is still
required; no paid experiment or real artwork approval occurred in this fixture.

Files: configs/design/bin/{logo_contracts,penpot_logo_source,design_logo_v1}.py,
configs/design/{agents,workflows}/design_logo*.yaml; model-free suite
`tests/test_design_logo.py`. Actual Temper result root:
`/home/shinelay/design-lab/results/temper-logo/`.
