# positioning_grade benchmark (marketing queue #1)

Fixed calibration bench for the positioning grader (`configs/workflows/positioning_grade.yaml`,
rubric `configs/agents/positioning_grade_assets/rubric.md`, document format `FORMAT.md` next to
it). Frozen 2026-10-04 before the grader's first test run. Everything here is fictional:
Kettlemark, its kitchens, interviews, pilot numbers and competitors are made up. Not blind: the
marketing role that built the grader also wrote the documents, mutations and expectations, so
this is a regression and calibration bench, not a held-out test. Planted defects check
soundness. Whether the market would buy is a message test's question.

- `evidence/`: the one evidence folder every case is graded against (three interviews, pilot
  results, a features page, a pricing page, competitor notes, a support summary). It is never
  edited.
- `sources/c1/`, `sources/c2/`: two sound positioning documents (positioning.md and
  positioning.json), written differently, citing that evidence.
- `mutations.json`: eight labelled mutants (M1-M8), each with exactly one defect, applied as
  exact text edits to a source document (and to its positioning.json where section 6 is
  mirrored there).
- `expected.json`: the ten cases under opaque keys. For each case it gives the labelled
  criterion, the criteria allowed to be revise, the markers a finding must quote, the checker's
  own expected findings, and the bar B1-B6. It is never staged into a run.
- `build.py --check`: every mutation applies exactly, and the checker alone (no model) finds
  what expected.json says. `build.py OUTDIR` writes each case as OUTDIR/<key>/ (positioning.md,
  positioning.json, evidence/).
- `score.py KEY=WORKSPACE ...`: scores finished grades against expected.json.
  `score.py --stable A.json B.json`: checks that two runs give the same overall verdicts.

A changed grader is tried under its own name in a gitignored `configs/*/local/` copy. All ten
cases are rerun and scored unchanged (docs/departments.md, "How a role tests and lands a
change"). The first version met the bar on two full runs after one rubric revision (a stretch
test that sets the severity of word-level stretches). Cost was about $0.40 per grade.
