# signal_grade benchmark (queue #12)

Fixed calibration bench for the signal_harvest quality grader (`configs/workflows/signal_grade.yaml`,
rubric `configs/agents/signal_grade_assets/rubric.md`). Frozen 2026-10-04 before the grader's
first test run. Not blind: the PM who built the grader wrote the mutations and expectations, so
this is a regression and calibration bench, not a held-out test.

- `sources/<base>/`: frozen copies of five retained signal_harvest reports (shortlist,
  scorecard, lens files), byte for byte; `SOURCES.json` gives each original's path and sha256.
  The originals live outside git (temper `state/` and the product research folders); never
  edit them or these copies.
- `mutations.json`: labelled corruptions of four of the scorecards (13 planted defects, D1-D13).
  Only scorecards are mutated; the lens files stay the evidence to check them against.
- `expected.json`: the nine cases (five as-is reports, four mutants) under opaque keys, what
  each must produce (required defects with evidence markers, forbidden allegations, allowed
  items, expected status and required-player result) and the bar B1-B10.
- `build.py --check` verifies the copies and that every mutation applies exactly;
  `build.py OUTDIR` writes the nine reports as OUTDIR/<key>/ (shortlist.txt,
  signal_scorecard.md, signal/<lens>.md).
- `score.py KEY=WORKSPACE ...` scores finished grades against expected.json.

A changed grader reruns all nine through a namespaced registration (docs/product-runs.md) and
is scored unchanged. Results, run links, costs and the manual review of the first version:
`~/product-autopilot/results/2026-10-04-signal-grade-12/`.
