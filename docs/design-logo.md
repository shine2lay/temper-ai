# Original editable-vector logo workflow v1

Design owns `design_logo_v1` and all `design_logo_*_v1` agents. This is new identity
work, not a change to live design reviewers, EPD, app branding or engine access.

```
sourced brief -> BUDGET -> six original monochrome vectors -> native rough PNG
 -> three different shortlists + role palettes -> native equal-scale boards
 -> new logo critic -> REAL OWNER DIRECTION -> FRESH BUDGET
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
- Exactly two refinement rounds maximum. Engine max_loops=2 permits only one
  rewind (its threshold counts the stopping attempt); script bounds independently
  forbid a third. Failed final revision is not successful completion.

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

Full trial estimate/reservation $8.15: initial exploration2.25 + shortlist1.00 +
initial critic.85 + (refinement1.00 + critic.85)*2 =7.80, plus.35 headroom.
These are conservative planning estimates, NOT per-Claude-CLI billing caps. Native
budget policy8.15 checks between calls; an in-flight call can overshoot. CLI model
iteration/time bounds do not replace financial supervision. Record all real
costs and any retry, including failures; no automatic artifact-stage paid retry.
Reconcile prior Design experiments and reserve the full bounded envelope before
spending; day spend+reservation <=$10 Pacific and whole trial<=authorization.
If the remaining honest estimate cannot fit, ask or genuinely wait; never split
or change dates. Every refinement budget gate requires a current reservation and
subscription/one-experiment checks. Gate waits may cross dates: recheck then.

Budget JSON fields: pacific_day, reserve_usd, day_spent_usd, trial_spent_usd,
trial_envelope_usd, subscription_checked:true, one_design_experiment:true and
reconciliation. Initial stage reserve>=4.10; each refinement reserve>=1.85;
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
SVG allows only safe vector/text/defs tags and local references; no scripts,
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

Files: configs/design/bin/{logo_contracts,penpot_logo_source,design_logo_v1}.py,
configs/design/{agents,workflows}/design_logo*.yaml; model-free suite
`tests/test_design_logo.py`. Actual Temper result root:
`/home/shinelay/design-lab/results/temper-logo/`.
