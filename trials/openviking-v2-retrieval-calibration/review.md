# Calibration reading notes

## What the measurements support
At the highest tested score cutoff, 0.65:

| Measure | Baseline | Candidate | Sample / uncertainty |
|---|---:|---:|---|
| Lead recall@5 | 57.14% | 100% | 14 positives; topic-bootstrap 95% CI 50–72.73% vs 100–100% |
| Lead negative-query injection | 10/16 | 0/16 | Wilson 95% CI 38.64–81.52% vs 0–19.36% |
| Worker total recall@5 | 33.33% | 100% | 12 plans; topic-bootstrap CI 33.33–33.33% vs 100–100% |
| Worker v2 memory recall | 0% | 100% | 24 expected memory references across 12 plans |
| Worker resource recall | 100% | 100% | 12 expected resource references |
| Retired / foreign-role leakage | 0 | 0 | Lead 30 queries; Worker 12 plans |
| Frontmatter twins decreasing | N/A | 6/6 | Each paired cosine decreases; delta −0.4098 to −0.2694 |
| V-9 gated candidate recall at 0.65 | N/A | 12/12 | Wilson 95% CI 75.75–100% |

The perfect bootstrap intervals are degenerate because all authored cases within a
policy have the same observed recall; they do NOT prove perfect unseen-case recall.
A random held-out sample is needed for a population claim.
Worker negative-plan noise is unknown (no negative-plan slice), not measured zero.

## Important negative findings
Legacy starvation was NOT demonstrated: 0 cases under the preregistered definition
(relevant notes exist but none survive truncation). The store does contain 360 retired
same-topic distractors, but equal-score URI sorting left active relevant notes visible.
Direct Lead recall was already 8/8; the recall gain comes entirely from six topic-anchored
followups (baseline 0/6, candidate 6/6). Do not cite this trial as proof that scoped search
fixes a measured truncation/starvation failure. It tests the adversarial store, not all tie orders.

All six score cutoffs give the same retrieval outcome. Therefore 0.65 is the highest
TESTED passing cutoff, not an identified optimal boundary. Keyword gating—not the
cutoff or ranking bonus—removes the ten unrelated/cross-role-query hint injections.
The keyword rule is exact §5c.5: at least one shared identifier OR two shared non-stop
stems. A noun-less followup requires the supplied topic; no topic means no hint.
The tested bonus adds no measurable benefit; recommend it off.

At simLow 0.65, three of four gate-surviving unrelated controls STILL pass. Their body-only
cosines span 0.6392–0.7921. Neither the lexical gate nor the tested similarity cutoff is a
safe deletion rule; a separate judge/evidence check remains mandatory. The nine
must-merge pairs span 0.8192–1.0000; three contradictions span 0.8497–0.9447. No cutoff
above 0.65 was preregistered, so this report does not silently optimize beyond the grid.

## Recommended contract candidates, not production changes
- simLow = 0.65, solely as candidate-generation cutoff, followed by judgment.
- leadScoreThreshold = 0.65, canonical lexical gate ON, ranking bonus OFF, topic anchor
  only when explicitly available, active-prefix retrieval before truncation.
- workerScoreThreshold = 0.65, project resources + active shared/caller category prefixes;
  no v1 entities/cases/experiences dependency; ranking bonus OFF.
- Retain the acceptance bars: Lead recall ≥85%, Worker recall ≥90%, observed unrelated
  Lead injection 0/N and retired/foreign-role leakage 0/N. Passing this small calibration
  is not a replacement for QA's held-out/final check.

## Isolation and resume receipts
The six denied operations are startup attempts to contact raw.githubusercontent.com:443,
blocked before DNS/connection. None is a live-port or live-state access. The frozen
measurement evidence records 0 port-1933 HTTP requests, 0 live configuration reads,
1,194 allowed localhost HTTP requests, and no VLM calls (vectors-only processing).
Audit guards are Python-level, not an OS syscall trace; this limitation is explicit.
Model file digests are in results.json; the final cache hashes match the first model unit.

The real 400-item store and 94-unit plan converged through cursors 0→7→60→94, followed
by a completed 94→94 skip. The 7→60 phase includes partial retrieval; resumption uses
a newly seeded throwaway store while preserving every completed measurement unit.
The attempt trail is append-only. Sealing twice leaves all sealed output bytes unchanged.

These reading notes are a post-measurement interpretation, not a change to frozen
cases, preregistered thresholds, numeric results or the immutable measurement trail.
They are included in the final manifest; the machine-generated report remains unchanged.

## Reproduce
Use /home/shinelay/.openviking/venv/bin/python to run run_calibration.py from this
folder with a new /tmp state path. Preserve that path across all resume commands:

```text
run_calibration.py --state /tmp/ov-data21-replay --max-units 7
run_calibration.py --state /tmp/ov-data21-replay --max-units 53
run_calibration.py --state /tmp/ov-data21-replay
run_calibration.py --state /tmp/ov-data21-replay
run_calibration.py --state /tmp/ov-data21-replay --seal
```

Use a fresh checkout for a new sealed report; an existing sealed manifest is immutable.
Canonical repository target is master (wt.yaml), not a nonexistent main branch.
