# OpenViking v2: Sol vs Terra vs Luna

## Decision
**Free-form ejection hypothesis: MISS.** For Ops #943’s narrower **pair-classification** seam, recommend **gpt-6.1-terra @ low as candidate**, not four-label certification: equal dedup quality, lowest p90/tokens. No autonomous free-form deletion.

## Fixed experiment
2026-11-15 **18:51:04–18:56:31 UTC**. Source: **26 real memory files**, read-only local OpenViking data; excerpts/paths/hashes archived. **24 cases × 3 models × 2 repeats = 144 completed calls**, usage/latency available 144/144; pilot included. Strata (gotcha/system/decision/preference): dedup **4/4/3/3 =14**, sweep **1/3/3/3 =10**. Purposive excerpts/constructed controls, not random folders/current-code audit.

CodexVLM/direct backend, identical inputs, `low` effort; labels withheld. Slugs are requested, not attested revisions. Clustered decisions/model: dedup 40 pairs (32 positive/8 negative), sweep 38 notes (10 eject/28 keep).

## Strict pre-registered scores
| Metric | gpt-6.1-sol | gpt-6.1-terra | gpt-6-luna |
|---|---:|---:|---:|
| Completed / valid schema | 48/48 | 48/48 | 48/48 |
| Latency p50 / p90, seconds | 5.03 / 10.05 | 3.76 / 5.39 | 3.45 / 6.19 |
| Input tokens | 24,072 | 24,072 | 24,072 |
| Output tokens | 8,719 | 7,580 | 7,862 |
| Total tokens | 32,791 | 31,652 | 31,934 |
| Dedup exact cases | 28/28 | 28/28 | 28/28 |
| Duplicate precision / recall | 32/32 / 32/32 | 32/32 / 32/32 | 32/32 / 32/32 |
| Sweep exact cases | 10/20 | 10/20 | 14/20 |
| Ejection precision | undefined: no predictions | undefined: no predictions | 6/7 =85.7% |
| Ejection recall | 0/10 | 0/10 | 6/10 =60% |
| Sweep note accuracy | 28/38 =73.7% | 28/38 =73.7% | 33/38 =86.8% |
| All exact outcomes | 38/48 | 38/48 | 42/48 |
| Repeat identical groups/ejections | 24/24 | 24/24 | 20/24 |
| Repeat pass/fail agreement | 24/24 | 24/24 | 20/24 |
| Kappa vs Sol, 78 decisions | 1.000 | 1.000 | 0.821 |
| Kappa vs fixed labels | 0.747 | 0.747 | 0.872 |
| Curated sentinel omission calls | 1/48 | 1/48 | 1/48 |

Sol/Terra’s constant “keep” sweep decisions make stage kappa undefined; aggregate parity hides shared mistakes. Luna misses the 0.80 recall floor. Zero schema errors is not zero risk; no executable patch application was tested.

## Blind rubric and label sensitivity
QA #167: one independent rater, 144 randomized A/B/C grades, frozen **19:04:40Z**, before labels/plants; key never read by QA. Grade SHA-256 **f9e6f681a2b8e49812935927e1186e3d00086e1e6544f8de68ed1864d1daf4d3**. Plants: **10/10 caught, 0/5 controls flagged** (self-authored, potentially optimistic). Lead agreed with six sampled grades. **PASS WITH NOTES** certifies evidence, not model safety.

| Rubric passes /48 | Sol | Terra | Luna |
|---|---:|---:|---:|
| Topic separation | 48 | 48 | 46 |
| Distinct facts kept | 44 | 43 | 45 |
| No invention | 48 | 47 | 47 |
| History handled | 45 | 44 | 43 |
| Concise | 48 | 48 | 46 |
| All five / corruption flags | 43 /3 | 40 /3 | 40 /4 |

Post-hoc sensitivity accepts **9 retired/historical answers: S01 ×3, S03 ×2, S06 ×4**. Frozen labels/results remain unchanged; two harmless-remnant answers (S05/S10) are not added.

| Score, strict → history accepted | Sol | Terra | Luna |
|---|---:|---:|---:|
| All exact outcomes /48 | 38 →43 | 38 →42 | 42 →42 |
| Sweep exact outcomes /20 | 10 →15 | 10 →14 | 14 →14 |
| Safe-resolution recall /10 | 0 →5 | 0 →4 | 6 →6 |

“Safe resolution” includes marking history; **literal ejection recall remains 0/0/60%**. Ranking changes from Luna to Sol; no model reaches 0.80 even on this sensitivity. Free-form sweeps conflated deleting a note with retiring its active claim. This is not blanket evidence of inability to identify contradictions.

QA label cautions: **S10 n2** (“pi-web-deploy queues itself”) may itself be stale, so its retention/omission grades are uncertain; **S02 `--when-idle`** is omitted from curated must-keeps despite being the historical value at issue; **short sentinels** `5`, `15`, `19`, `30`, `240` ×2, `500`, `624` match too easily. S03’s retained 240-character rule may be dead; D03 n3 could defensibly stay separate. These limit the strict bar, not grounds to silently relabel.

Examples: Sol r1/Terra r2/Luna r2 omit S10 `pi-web-deploy` (uncertain); Terra drops S02 `--when-idle` twice. Luna’s `~/.local/bin/test-check.` flag includes punctuation: **not proven path loss**. QA also found “receipts” narrowed to “health receipts” and stale cleanup/test instructions.

## Cost and uncertainty
Terra/Luna p90: **46.4%/38.4% lower**; tokens: **3.47%/2.61% lower**. Dollars/Codex allowance **UNKNOWN**; preflight reported Anthropic pools. Historical 41.27M tokens/2,740 commits, 26.4s/51.6s are unverified, not comparable baseline.

5,000 paired case-cluster bootstrap draws: exact-accuracy 95% intervals **62.5–95.8% /62.5–95.8% /75.0–95.8%**. Terra/Luna accuracy difference vs Sol: **0–0 /−4.2 to +22.9 pp**. Intervals are not population guarantees; two repeats show short-run stability. Token/latency intervals are archived.

## Safety and provenance: QA lead notes
**port 1933=0; guard caught & denied 10 writes (5 per model-calling run, 0 in rerun) on /home/shinelay/.openviking/data before execution.** Four limits explicitly:
1. **“0 live changes seen by the guard”**: one Python process, selected operations; not other processes, databases or non-Python code.
2. Receipt **`live_writes` = denied count**, not successful writes.
3. **Path-only audit record**: operation type was not retained; mkdir/chmod/time changes cannot be distinguished. Static library code creates workspace directories during configuration validation; startup is plausible, not proved from these receipts.
4. **protocol.md mtime 18:51:00Z vs 18:51:04Z first call**: pre-registration timing rests on that uncommitted file time, not a pre-run commit.

There was **1 connect/run to 2606:50c0:8000::154 (raw.githubusercontent.com)**, besides model endpoint connections. Fetched content was not recorded; do not claim every connection was inference. No live service/config/deploy actions, credential copies/refresh or raw runtime request/system-prompt archives.

**Post-run mtimes:** run_bench.py/evaluate.py **19:04:45Z**: runner edits only import cleanup/UTC alias; evaluator added response hashing, invalid-schema false-negative accounting, exact-group repeat metrics and paired bootstrap reporting. No new inference or label edits. **instruction_sha256=b9fcdcbfcae0358e7415da28e1344acb1c7d0b7abe0a486e17d4457ff3a5e1bc matches plan.json**. **19:03:10Z same-seed blind regeneration** used seed 20261116. Rebuilding with the canonical generator into a disposable directory reproduces all three packet files and key **byte-for-byte**; 144 packet answers match stored responses. Details: archived review-audit/QA receipts.

Stable hashes/IDs and append-only attempts: full resume skipped **144/144**, 0 network, attempt rows still144. Largest case **855 input tokens**, six results closed; not proof of production-scale folder convergence.

## Ops #943 and verification
Lead-provided seam reference: rm-aa4ea068, `~/projects/pi-openviking/docs/hypotheses/2026-11-16-ops-943-maintenance-fyi.md` (not opened: prohibited repo). V2 moved supersession/date/authority to deterministic scripts; **F-JUDGE-01** asks only **`duplicate|conflicts|supersedes|unrelated`**. Dedup **28/28 for all three** supports the duplicate/unrelated decision slice directly. It does **not** validate four-way schema, conflicts/supersedes accuracy or long-input behavior. Terra’s p90/token advantage makes it the candidate for that narrowed seam, with its own stage assertions before wiring.

Ten harness tests, Ruff/full `wt check` passed; final markdown checked separately. QA’s final check/ruling archived. Reproduce via protocol/harness; manifest fingerprints fixtures, plan, 144 responses, metrics, sensitivity, frozen grades/plants/receipts. No model/config switch.
