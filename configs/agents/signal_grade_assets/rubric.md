# signal_harvest output quality rubric (signal_grade/1)

Frozen 2026-10-04 for queue #12 before the grader's first test run. Do not edit it to fit
results: a change is a new rubric version, and the benchmark (tests/test_signal_grade/) must be
re-frozen and re-run in full against it.

## What this judges, and what it does not

The grader judges whether one signal_harvest report is internally sound and faithful to its own
evidence. A report is: the shortlist the run was given, the scorecard (state/signal_scorecard.md)
and the lens files it was built from (state/signal/search.md, jobs.md, pain.md, competitors.md,
or a lens variant such as spend.md in place of jobs.md).

It does not judge whether a market is good. A weak-scoring idea in a sound report passes; a
top-scoring idea in a defective report gets revise. The quality status is never a demand score.

The grader never rescores, re-weights or re-ranks. The demand formula (signal scores 0-3, the
confidence discount, the weights, the overall-confidence rule) belongs to the synthesizer
(configs/agents/signal_synthesize.yaml) and is checked exactly as written there. Reading a
crowded competitor field as demand is part of that formula and is not a defect.

The grader works only from the files. It does not browse the web, so it cannot see the pages
behind the lens files.

## Judgments

Each criterion gets one status:

- pass: checked, no material defect found.
- revise: at least one verified, material defect.
- unknown: could not be checked from the files (a file missing or unreadable, a table that
  cannot be parsed, a lead the review did not resolve). Unknown is not a defect allegation.

A finding counts only when it is verified: its supporting passages are found verbatim in the
files it names. A finding that alleges something is absent (a figure, quote or URL in no lens
file) is verified by searching the lens files for it.

Material: the defect changes or props up a score, an overall confidence, the ranking or the
recommendation, or presents evidence the files do not contain or do not say. Minor: wording or
presentation that changes no decision. Minor findings are notes; they never set revise.

Overall status: revise if any criterion is revise; otherwise unknown if any criterion is
unknown; otherwise pass.

## Criteria

Q1 Candidate identity and completeness. Every shortlist candidate appears exactly once in the
scorecard table, has its own per-idea section and one ranking entry, under its own identity (its
id and name are not swapped with or merged into another candidate's).
Revise: a candidate missing from the table, or missing its per-idea section or ranking entry; a
candidate duplicated; two candidates merged or swapped; a row that is not on the shortlist and is
not labelled as such.

Q2 Arithmetic, confidence and ranking reproduce. Each signal cell is raw x multiplier =
discounted, with raw 0-3 and the multiplier matching its confidence label (high 1.0, med 0.8,
low 0.5). weighted_score = 0.15 x search + 0.35 x jobs (or the lens variant's money signal at the
same weight, for example spend) + 0.20 x pain + 0.30 x competitors, to 2 decimals (within 0.005;
a 3-decimal value is fine). Arithmetic lines agree with the table. Overall confidence follows the
rule: low if jobs (or the money signal) or competitors is low-confidence, or if 2 or more signals
are low-confidence; otherwise med; high only if 3 or more signals are med or high. The ranking
follows weighted_score (ties broken by overall confidence, then jobs score), and every score it
quotes matches the table.
Revise: a miscalculated cell, total or arithmetic line; an overall confidence above what the rule
allows; a ranking out of order or quoting a different score. An overall confidence below what the
rule allows is a minor note.

Q3 Evidence provenance and attribution. Every figure, quote and URL that the scorecard presents
as evidence exists in a lens file and keeps the lens file's attribution: the same candidate,
source or venue, date, speaker role and meaning. A figure derived from the report's own numbers
(for example a share of a weighted score) is fine when the computation holds.
Revise: a figure, quote or URL found in no lens file (unsupported); a lens quote or figure moved to
another candidate, venue, date or speaker (misattributed); a quote altered so that it says
something the lens quote does not.
Not a defect: framing phrases in quotation marks that are the report's own words; a light
paraphrase in quotation marks whose meaning matches the lens (a minor note at most); evidence the
lens itself labels snippet-only, secondary, unverified or estimated, when the scorecard keeps that
label.

Q4 Blocked sources and honest unknowns. A source the lens files record as blocked, inaccessible,
rate-limited, empty or not attempted is never presented as read or checked, and a zero or low
score that rests on such gaps is presented as unknown or unverified, not as evidence of no demand.
Revise: a blocked or unreached source described as read or checked; nothing found in limited
venues presented as proof that the users are untroubled or the demand is absent; a caveat the lens
attaches to a zero or low score removed so that the absence reads as measured.
Not a defect: an honest zero ("0 found in the venues checked; X and Y were blocked"). That is the
correct handling and must not be flagged.

Q5 Scope match: buyer, job, population and price. Evidence counted for a candidate is about that
candidate's named buyer or payer, job and population (as the shortlist states them), and every
figure keeps its own denominator, unit, population and price basis.
Revise: evidence about a different payer or population presented as this candidate's buyer budget
or demand without saying so (for example employers' salaries for people who do the task by hand
counted as consumers' willingness to pay for an app); a figure's denominator or population widened
or narrowed (a statistic about one segment presented as about all of them, a count over all
employers presented as the target subset); prices compared on different bases without saying so.
Not a defect: a proxy that the scorecard labels as a proxy and discounts or caveats.

Q6 Competitors: exact versus adjacent or bundled, and coverage. A vendor counts as selling this
exact job only when the lens files show that it sells that job to this buyer. Adjacent tools,
general platforms, free features bundled into a larger product and outsourced-service firms must
be labelled as such when they support the competitors score. Every player the shortlist explicitly
asks to check is covered (reviewed, or reported as not found or blocked) in the competitors lens
or the scorecard.
Revise: an adjacent, bundled or general vendor presented as an exact seller; a contradiction
between lens files on this point silently resolved in favour of a higher score; a required player
neither covered nor reported.
Not a defect: the formula's own reading of a crowded market as demand (never rescored here);
adjacent vendors that the scorecard labels adjacent; a cross-lens disagreement that the scorecard
surfaces.

## What the grade reports

Per criterion: status and a short note of what was checked. Findings: id, criterion, candidate,
kind, severity (material or minor), the claim, the problem, and supporting passages (file and
verbatim text). The deterministic results: recomputed cells and totals, the confidence rule,
ranking order, candidate coverage and required-player coverage. Unverified findings, listed apart
and not counted. Limitations. Integrity: the report files were not changed by grading.

## Limits

The grader trusts the lens files as the record of what was found. An error inside a lens file (a
wrong date, a misread page, a figure taken from a search snippet the lens did not label) is out of
its reach unless the files contradict each other. It cannot detect a fabrication that is
consistent across the lens files and the scorecard.
