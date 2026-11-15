# Benchmark quality checklist

- [ ] Owner question (2026-11-15 task): “do you think other models can do a good enough job? i am concerned, lets test it out we should have enough data” — answer from measured task quality, not model reputation.
- [ ] Exactly 24 fixed real-source cases: 14 consolidation / 10 contradiction sweeps; all four proposed categories; exact copies explicitly constructed; negative controls present.
- [ ] Exactly 144 planned unique result IDs, two repeats each; no resampling or hidden failure retries; largest case closes; rerun skips completed IDs.
- [ ] Expectations and canonical evidence excluded from model inputs except canonical evidence intentionally supplied for sweep decisions; labels/hash fixed before pilot.
- [ ] Live memory data read-only; no service on port 1933 contacted. Count blocked mutation attempts separately from actual writes; audit-hook limits disclosed.
- [ ] Unknown quota/dollar savings are UNKNOWN. Token availability denominator shown. Small-sample zero observed errors is not zero risk.
- [ ] Sol is a comparator, not ground truth. Kappa across tasks must not hide a constant no-ejection classifier on sweeps; undefined kappa stays null.
- [ ] Historical fact is not an active instruction. Notebook frozen-backup restoration is not reactivation. Newer dated ledger count does not falsify an earlier dated count.
- [ ] Preserve exact paths, IDs, numeric values and command flags for retained facts. Inventory sentence punctuation is not part of the real path; disclose false positives without changing frozen primary labels.
- [ ] Semantic grades frozen before unblinding, model-name-free randomized A/B/C order, all five anchored fields for all 144 responses; record reviewer identity/method and uncertainty.
- [ ] Report per-model n, source/date, latency percentiles, tokens, pair precision/recall, per-note ejection accuracy, repeatability, failure examples and hypothesis HIT/MISS.
- [ ] Do not recommend automatic deletion when recall misses 0.80 or identifiers are lost, even if faster/cheaper or rubric agreement with baseline is high.
- [ ] No deploy/config edits here; hand measured recommendation to Ops. Standard checks recorded, no production-engine/workflow changes.
