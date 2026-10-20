# Semantic grading boundary v1 — output contract v3

Architecture #134, H-CTX-4, 2026-10-20. Stage 1 only. **No meaning evaluator exists in this implementation.**
This freezes the grading-output boundary, not a new profile schema, a semantic qualification or a model stage.
`context_profile/v2`, key/plant v2, STANDARD's B0–B10 definitions and every threshold/ceiling are unchanged.

## Operational output: context_profile_grade/v3

Every completed profile, consistency or pool result has:

| Field | v3 meaning |
|---|---|
| `grading_output` | `context_profile_grade/v3` (separate from the product/profile contract) |
| `kind` | `profile`, `consistency`, `pool`, or `error` |
| `status` | always `BLOCKED`: no final acceptance |
| `semantic_status` | always `NOT_MEASURED`, not FAIL/rejected or PASS |
| `semantic_score_pct`, `score_pct` | JSON null, never an invented zero/100 or accuracy estimate |
| `clean`, `meets_bars` | always false; compatibility stop signs, not semantic failure labels |
| `blockers` | includes `assertion_meaning_not_measured` |
| `bars` | status and nullable `meets_bar` for every unchanged B0–B10 |
| `structural_anchor` | independently available observations, not semantic evidence |

`B0_contract` is MEASURED using the unchanged checker when nonempty profile results exist; its boolean
can be true or false. B1–B10 are NOT_MEASURED (`meets_bar: null`) as complete stage obligations. That is
conservative: label/criterion equality and anchor counts remain measurable proxies, but this version does
not qualify the source meaning or complete coverage on which those stage obligations rely. B5 also requires
clean runs, not merely repeated labels; B6 requires actual run records. Empty pools/runs do not measure B0.
There is **no reduction or reinterpretation of a standard bar**: missing capability stays missing.

The original five wrong-meaning/right-quotation probes remain semantic misses. Their unchanged meaningful
controls are not semantically rejected either. Both receive BLOCKED/NOT_MEASURED while their real structural
observations remain green. This safety correction is not a catch of those faults or Stage 1 acceptance.

### Exact old-to-new diagnostic mapping

For one profile, `case_id` stays at the top. The old `checker_ok`, `facts`, `unknowns`, `constraints`,
`goals`, `goal_order`, `maturity`, `sensitivity`, `unknown_fields`, `invented`,
`material_unknowns_not_in_key`, `quote_words` and `failures` move unchanged under `structural_anchor`.
Their names retain their old *algorithmic* meaning only:

- `facts.captured` / `captured_ids`: one-to-one quote-anchor/allowed-section/number matches, **not fact entailment**.
- `unknowns.flagged` / `flagged_ids`: field/material-marker or term-group matches, **not meaningful questions**.
- constraint/goal `right` / `status`: anchor placement and criterion checks, **not preservation of asserted meaning**.
- `maturity` / `sensitivity`: emitted labels versus accepted labels, **not validation of supporting reasoning**.
- `invented`: known checker/unknown-field/trap **signals**, not an exhaustive count of invented assertions.
- `failures`: original reason/ref/detail observations retained verbatim. Absence proves only absence of those findings.

Old `rates` becomes `structural_anchor.proxy_rates`. Old numerical `score_pct` becomes
`structural_anchor.diagnostic_score_pct`, the unchanged mean of nine proxy rates. Old `clean` becomes
`structural_anchor.diagnostics_ok`. No diagnostic percentage is semantic accuracy. An unkeyed extra
assertion can be wrong while every proxy is 100.

Pool's old `fact_recall`, `goal_order`, `invented` become `structural_anchor.fact_anchor_recall`,
`goal_criterion_order`, `invention_signals`. Old boolean bar calculations survive only as explicitly named
`proxy_thresholds` (checker contract, invention signals, fact-anchor recall, unknown markers, constraint
anchor classification, maturity/sensitivity label membership, criterion order, goal-anchor promotion).
Those thresholds do not populate meaning-dependent `bars`. `diagnostics_ok` reflects those proxies plus
nonempty/unique cases; it is not final acceptance. Empty denominators have null aggregate rates. Duplicate
case IDs are still reported and prevent diagnostic success. `per_case` retains diagnostic percentages,
anchor recall and finding reasons, not semantic percentages.

Consistency's old comparisons survive under `structural_anchor`; `facts_agreement` is now
`fact_anchor_agreement`. Empty/single/mixed-case inputs cannot be consistent diagnostic run sets. Repeated
wrong statements can agree perfectly, so consistency does not pass B5. Aggregate inputs must be v3 profile
diagnostics of the required shape; legacy, partial, non-profile or missing outputs are refused. Shape checks
are not authenticity checks. Stored JSON can be forged; even forged green diagnostics never grant semantics.

### CLI and consumer effects

Case commands still lint keys; `--pool` reads stored results (it does not re-lint unseen source keys).
All completed scorer commands exit **1**, including `--self`, `--runs`, `--pool` and expected plants.
Exit **2** means cannot run (bad JSON, broken key, missing file, unusable aggregate); argument errors also
exit 2. There is **no exit-0 route**. Plant exact-finding comparison remains available at
`structural_anchor.planted.as_expected` and in `against_plant`; true is a fixture diagnostic, not acceptance.
The separate, unchanged checker can still exit 0 for structural validity only.

Consumers must inspect the version, scope and semantic status, not treat a green proxy, truthy status string,
plant match or absence of findings as correctness. The only in-repository caller outside this script is the
Architecture test file, migrated without dropping substantive diagnostic assertions. Old private v2 reports
stay immutable; v3 pooling refuses them rather than converting their former success into new evidence.
No semantic argument, receipt field, caller flag or success override is accepted. Candidate extra properties
remain schema errors; purported proof on aggregate JSON is never consumed for semantic decisions.

## Proposed future evidence boundary: semantic-evidence/v1 (NOT operational)

This section is a proposed interface only. It creates no producer, receipt parser, trusted actor, positive
consumer, command-line option, qualification or permission to accept meaning. A later separately planned
implementation must first qualify its evaluator on independently adjudicated known-good/bad/uncertain
cases, including the retained misses, with repeatability and false-accept/false-reject evidence. Qualification
must bind the evaluator implementation/configuration/version and its qualification report; self-declared
`qualified: true`, candidate content or a matching hash is not qualification.

Required evidence would cover **every claim and every unknown**, including unkeyed additions, assumptions,
materiality, classification, units, comparators, polarity, temporal/conditional scope and contradictions
between profile sections. It must account for missing material source claims/unknowns, not only validate
whatever the candidate elected to emit. A complete coverage inventory identifies every profile path and
every material source/key obligation; omissions/duplicates/unresolved mappings block acceptance.

Evidence must bind exact source-brief bytes and digest, exact profile bytes/canonicalisation and digest,
profile contract version, key/standard versions and digests (where used), grading-output/evidence versions,
evaluator implementation/configuration and its qualification receipt. Stale/mismatched/partial coverage is
not usable. Identity, provenance and tamper resistance require a separately designed trust boundary; a digest
or candidate-supplied result alone establishes none of them.

Each claim/unknown/obligation needs an explicit outcome: **supported, contradicted, unsupported, uncertain**,
with exact profile path, source spans, obligation mapping and rationale. Supported is not implied by quote,
number, keyword or field membership. Unsupported and uncertain must never become numeric zero/100,
unsupported acceptance or a supposed successful catch. Conflicting findings and incomplete coverage remain
explicit. Only a separately qualified implementation could define how these outcomes discharge each
unchanged bar; this task admits **no positive semantic receipt**, even one shaped like this proposal.
