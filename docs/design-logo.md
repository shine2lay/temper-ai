# Original editable-vector logo workflow v1

Design owns `design_logo_v1` and all `design_logo_*_v1` agents. This is new identity
work, not a change to live design reviewers, EPD, app branding or engine access.

```
sourced brief + pinned research -> BUDGET -> six original monochrome vectors
 -> native rough PNG + size check -> explorer sees that render and redraws
 -> sketch PNG + size check + caption-free cold read and same-name check
 -> three different shortlists + role palettes -> native equal-scale boards
 -> new logo critic -> DIRECTION GATE (a direction, or explore-again: the
    run ends and the next run's brief carries the rejected round) -> FRESH BUDGET
 -> selected refinement -> native source/exports + size check -> cold read and
    same-name check -> new logo critic -> handoff
 -> FINAL GATE (or one bounded rewind for the second refinement; past that,
    one extra round only when the final gate asks for it, see below)
```

Generation comes from a vision-capable Claude-provider LLM's own bounded vector
objects, not a fixed Temper icon catalogue or a meeting-room template. Native
Penpot boards are deterministic presentation layouts, not generated logo forms.
`design_logo_fixture_v1` is separately named, model-free and explicitly fictional;
its deterministic test shapes never pass as original generated Temper artwork.
It still pauses at the native `direction` and `final` gates; its answers are
recorded `decided_by: fixture-test`, never as anyone's approval.

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

## Research first (queue #38)

Since queue #38 the workflow starts with the shared research step
([design-files.md](design-files.md)): an inventory of the product's approved design files,
then, only for missing parts, users research, a category scan (competitor marks), context fit
against `configs/design/knowledge/context-playbook.json` and a research gate (answered like the
other gates, with `decided_by`). `research_logo_brief` merges the research into `brief_json`:
the playbook context id, the product meaning, the category comparison as pinned research, and
an approved palette as `fixed_palette` (the palette agent and `fixed_palette_check` keep it
exact). After the final gate approves, `save_files` writes the logo, its colours, the users
profile and the direction as the product's design files (approved by the final gate's
`decided_by`). The run policy is $30: the logo estimate below ($11.60) plus $18.40 for research.
Inputs add `research_json` (required) and `mode` (`real`, or `trial`: a fictional brief with
the real agents, gates answered `fixture-test`).

## Entry

Real entry takes `brief_json`, `budget_json` and `research_json`. No ordinary direction/
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
- Model-written labels and prose (shape layer names, concept name/idea/ownable
  detail/generic risk/trade-off, critic element/location/evidence/suggestion/reasons,
  palette rationale, revision notes, refinement changes/declined) that overrun their
  bound by up to four times are shortened with an ellipsis instead of failing the
  paid stage (real run ad5c270f lost a round-1 critic save to a 129-character
  location and its round-2 refinement save to a 49-character layer name). Ids,
  enums, brief and owner words, geometry and longer text stay strict.
- Two planned refinement rounds. Engine max_loops=2 permits only one rewind (its
  threshold counts the stopping attempt). A third round runs only when the final
  gate asks for it (next section); script bounds forbid a fourth in every case. Failed final
  revision is not successful completion.

## Changes after the first real Temper round (2026-10-03)

The owner rejected all three round-1 directions (run 6b9790e9): "None: fix the
workflow and explore again". Weak spots it showed, and the fix for each:

- No way to say "none": the direction gate accepts `decision: explore-again`
  with its own `note`. The run records `explore-again.json` (the rejected
  shortlist, the answer, who decided) and every later node is skipped by
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

## Extra round on the final gate's request (2026-10-03)

At the round-2 final gate of real run ad5c270f the owner asked for one more change
("lets make the bottom part a bit shorter right now, the bottom part look a bit
phallic") after being offered an extra round. A round-2 `revise` still records the
answer in `logo/gate-final-r02.json` (`owner-final-r02.json` in runs before
2026-10-05) and fails the run, because the loop is spent. The host then resumes
that same run with `refine_budget` ticked to run again
(Temper's resume `rerun`), so round 3 is one straight pass, not a further loop:
fresh budget gate, prepare, refine, save, critic, handoff, final gate. The script
starts round 3 only when both hold: the native final gate recorded a real
`revise` (decided_by design or owner) with its own note, and the fresh refine
budget answer names that same note (`extra_round_note`; `extra_round_owner_note`
is still read). Neither alone starts paid work, and nothing allows
a fourth round. Round 3's refinement reads that note and the previous round's
boards (each round now gets the boards of the round before it, not always round 1's).

## Size check and cold read (queue #11, 2026-10-04)

Task #4 showed two weak spots that only the critic or the owner caught: detail
that vanishes at small sizes (the Ringing Fork's arcs, the Dovetail T's seam and
the Keystone's seams at 16 px; the approved anvil's dovetail only from 48 px) and
misreadings (psi/trident, funnel, jacket/trousers, and a round-1 anvil that looked
like a goblet), plus a same-name closeness (the ontemper.com header mark) found late.

`configs/design/bin/logo_size_check.py` is model-free. From the saved vectors (the
symbol parts in the 100-unit box, as the native source holds them) it measures each
part's width (median inward thickness along its outline), each seam between
separate pieces of ink (exact closest distance) and each narrow opening inside a
piece, in px at 16/24/32/48. A symbol's honest minimum is the smallest of those
sizes where every feature and gap is at least 1 px (`floor_px`, configurable); it
also reports where all reach 2 px (`clear_px`) and the exact sizes. Values are
truncated, never rounded up to pass. It runs after exploration (`roughs.size.json`,
read by the redraw pass), after the redraw (`sketches.size.json`, read by the
shortlist and critic, printed on each actual-size board) and after every refinement
(`selected-rNN.size.json`); the handoff's `minimum_symbol_px` and BRAND.md use the
larger of the declared and measured minimum, never a smaller one. Geometry only:
antialiasing, hinting and colour are not modelled, and 1 px is a floor, not a
reading test.

The cold read shows each symbol alone, in its own native Penpot file, at 32 px and
128 px under neutral labels (S1.., seeded shuffle) to `design_logo_coldread_v1`,
which sees no caption, brief, name or idea and writes three first readings per
size. `design_logo_names_v1` separately compares each 32-px header lockup (symbol +
live wordmark) with the research marks the brief lists in `research.same_name`
(captures of other products using the name). It reads the run's research notes
(`logo/research/comparison.md`: how each same-name mark looks and what to avoid) and
judges what a glance at 32 px takes in (outline, main pieces, stacking), so a shared
shape counts even when the two depict different things up close; a shared word,
colour or generic sans alone does not. An earlier prompt without the notes missed
both known cases (#4's anvil and round 1's Declared Indent beside the ontemper.com
mark); this one caught both with no extra flags. The host validates both, maps labels
back to ids and saves `coldread-<phase>.saved.json`. Shortlist rows and critic
reviews must quote every saved reading exactly with `fits_idea` and a note, and
carry every close same-name flag (`first_reads`, `name_marks`); the host rejects a
missing, changed or extra reading. Readings are one model's first impressions, not
user research, recognition rates or a trademark search. Refinement reads the size
check and cold read of the artwork it refines.

The contract board's plant A (a wordmark cut to 'Ast' after its metrics were taken)
is now measured on the final saved objects: content text, rendered text cache,
final width and position are read back from what is saved, so an edit after
creation shows (`rendered_matches_content`, `content_matches_intended`).

`design_logo_replay_v1` (test only) re-checks saved symbols of an earlier run: size
check, caption-free boards, cold read and same-name check, with no gates, budget
answers, refinement or packet.

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

The gates are named for what they decide (queue #40, 2026-10-05; Design's gate
convention of 2026-10-04): nodes `direction` and `final`. Every answer records
who decided (`decided_by`), the choice and the reasons.

Direction answer:

```json
{"decided_by":"design","run_id":"<full UUID>","brief_hash":"<brief hash>",
 "artifact_hash":"<saved three-board artifact hash>","decision":"<shortlisted id>",
 "reason":"Why this direction","note":"Optional refinement guidance"}
```

Final answer: the same fields with the current selected artifact hash and
`decision: approve|revise`; revise needs its own `note`.

- `decided_by: design`: the chat running the workflow answers as Design, after
  looking at the boards; a queued task's chat asks its home chat first.
- `decided_by: owner`: only for the owner's own words, quoted verbatim in
  `reason` (and `note`), with `source` naming where he said them. His words
  outrank Design's. Only an owner answer may carry `source`.
- `decided_by: fixture-test`: the fictional fixture's only answer. Real runs
  refuse it and the fixture refuses the others.
- The retired `approval` and `owner_note` fields are refused in new answers.

A parent may answer budget gates within existing authorization but never answer
a gate in the owner's name without his words. The fixture refuses both a real
brief and any name containing Temper.

The gate records are `logo/gate-direction.json` and `logo/gate-final-rNN.json`;
the stage results and `manifest.json` carry `direction_approved` and
`final_approved`, each `{"approved": bool, "decided_by": ...}`, and the manifest
names the final record in `final_receipt`. A rejected round in a later brief's
`prior_rounds` is `{run_id, answer, source, decided_by, rejected, evidence}`:
decided_by design or owner in a real brief; a fixture brief may also carry a
`fixture-test` round, which a real brief refuses.

Records from before 2026-10-05 still load and are never rewritten: answers with
`approval: owner-direction|owner-final|fixture-test` and `owner_note`,
`owner-direction.json` and `owner-final-rNN.json`, `prior_rounds` rows with
`owner_answer`/`owner_source`, and runs whose gate nodes are `owner_direction` /
`owner_final` (the host tools `logo_control.py`, `logo_real.py` and
`logo_real_wait.py` accept both node names). An old `approval: owner-*` reads as
`decided_by: owner`, because that is what it claimed then.

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

Full run estimate/reservation $11.60: initial exploration2.25 + revision pass.75 +
cold read.50 + same-name check.40 + shortlist1.00 + initial critic.85 +
(refinement1.00 + cold read.50 + same-name check.40 + critic.85)*2 =11.25, plus.35
headroom (before the cold read: $8.90; v1 before the revision pass: $8.15).
The estimate is now above the script's $10 Pacific-day and trial fence
(`budget_contract`); a full run still fits when actual spend stays well under the
caps, as in task #4 ($7.31 for the whole trial, three refinement rounds included). Lifting that fence to match the
owner's 2026-10-04 no-limit rule is a separate change, not part of the cold read. These are conservative planning
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
reconciliation. Initial stage reserve>=5.75; each refinement reserve>=2.75;
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
in the task result. direction_approved/final_approved (with decided_by) are
separately recorded from the real native gates. Publication remains false. No diagnosed
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
