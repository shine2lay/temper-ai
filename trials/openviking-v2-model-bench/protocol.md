# OpenViking v2 model benchmark — pre-registered protocol

## Question and hypothesis
Owner asked whether cheaper models can safely replace flagship consolidation. Compare `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-luna` via the installed CodexVLM backend at identical `low` reasoning effort. No configuration changes or service calls.

Historical motivation supplied by the task: 41.27M tokens / 2,740 commits; latency p50 26.4s / p90 51.6s. These are unverified background, not measurements from this experiment.

Hypothesis: Terra or Luna matches Sol with Cohen’s kappa >=0.85 on item-level merge/ejection decisions, 0 schema/corruption failures, 0 loss of retained exact paths/IDs/numbers, contradiction-ejection recall >=0.80, and p90 <15s with lower measured token consumption. Kappa 0.80–0.85 misses the expected result even if useful; <0.80 ejection recall or any corruption rejects. Actual subscription billing/quota cost is UNKNOWN; tokens are a proxy, not money or remaining allowance.

## Fixed sample and labels
- n=24 purposively stratified cases from real read-only memory markdown, not a random population sample: 14 dedup, 10 sweep; all four proposed v2 categories represented. Current memories have legacy categories; categories here are analytical mappings.
- `build_cases.py` freezes exact source excerpts, absolute source paths and whole-file SHA-256. It strips serialized MEMORY_FIELDS duplicates. It refuses different content under the same fixture ID.
- D01/D09 deliberately repeat a real excerpt (constructed exact-copy controls). Other cases use natural near-duplicates, complementary fragments or negative controls. Fragmented three-note cases are explicit constructed groupings of real lines, not naturally co-occurring folders.
- Sweep canonical evidence is later/current memory evidence, not a fresh checkout of production code. Thus code drift means recorded code/contract supersession, not an independent current-code audit. Never access the prohibited Ops/Architecture repositories.
- Historical records remain true as historical records. S02/S04/S07/S09 are negative controls against deleting history. Restoration of notebooks is explicitly NOT restoration of automatic use: the source says frozen backups and continued retirement. S05/S10 intentionally extract obsolete action instructions from an older event; the full event is not alleged false.
- `cases.json` stores expected retained groups, ejected IDs, and verbatim sentinels BEFORE model execution. Expectations never enter requests.

## Execution and safety
24 cases × 3 models × 2 repeats = 144 planned calls. Fixed randomized scheduling seed 20261115; parallelism 3. Pilot D01/D04/S04/S10 covers pass/fail/negative/reversal stages twice and counts toward the same 144, not additional data. Continue the frozen schedule, never resample failures or tune instructions after seeing results.

All execution artifacts in `/tmp/ov-v2-model-bench/`; final artifacts in this trial directory. Explicit in-memory existing credentials bypass refresh/write. Never persist credentials, full SDK exception messages, HTTP headers, raw request bodies or runtime system-prompt payloads. Store response text only, inputs as the human-curated fixture, instruction hash and reproducible harness source.

Python audit hooks reject any port 1933 connection and modifications under the live OpenViking root. Safety logs record only destination addresses/ports and denied mutations. No server starts/restarts or live API calls. Other processes may change live data; the process guard, not whole-tree equality, establishes this harness’s isolation.

Stable plan/content hash; existing matching results skip; conflicting hash refuses. Append-only attempts and safety receipts support resume. Failed requests remain measured failures, not silently retried experiments (backend SDK transport retries may still occur and count in wall latency). A quota interruption is a partial outcome with durable results and unchanged plan.

## Deterministic rubric
1. JSON only, exact top-level `items`/`ejected`, item keys `source_ids`/`text`, ejection keys `source_id`/`reason`; all note IDs covered exactly once; non-empty strings; no unknown IDs.
2. Dedup pairwise same-topic precision/recall against frozen groups; no ejection allowed. Full-case exact grouping accuracy also reported, counting schema failures as incorrect.
3. Sweep per-note ejection precision/recall/accuracy and exact-case accuracy; unaffected notes must remain separate. Must-drop IDs cannot appear in retained items. Semantic checks additionally catch stale claims retained in other prose.
4. Literal sentinel retention across retained text; all sentinel IDs/paths/numbers must survive exactly, not merely semantically. Also automatically inventory paths, flags, issue IDs, hashes and numbers in expected-retained input notes, reporting omissions separately from curated sentinels (lexical inventory can flag benign reformatting; do not silently excuse it).
5. Repeatability: exact retained grouping/ejected IDs per case; pass/fail agreement; response wording equality separately. Pairwise decisions vs Sol and vs labels; Cohen’s kappa, undefined reported null. Do not call Sol ground truth.
6. Usage: recorded input/output/total tokens and availability; missing UNKNOWN, never zero. Wall latency per-call p50/p90 (linear interpolation), sample counts and date range. Token sums only over available records, with denominators. No invented dollar savings.
7. Uncertainty: bootstrap intervals over the 24 case clusters (keeping paired models/repeats together); exact sample proportions and limitations. Two repeats are correlated, not independent replications.

## Blind semantic rubric
Produce a model-name-free packet in independently randomized A/B/C order per case/repeat (seed fixed before scoring). Do not reveal the key until grades are frozen. A semantic reviewer sees the source notes, canonical evidence and anonymized response, not model IDs or timing/token metrics.

Each response: topic separation (0/1), all distinct supported facts retained (0/1), no unsupported invention (0/1), historical versus active-policy handling (0/1), concise nonredundant merge (0/1). Flag any semantic corruption or stale active claim; quote only response defects in final report. Deterministic scores and frozen labels take precedence over impressionistic fluency. This is an anchored limited-sample review, not an external human gold standard.

## Decision
Recommend a cheaper slug only if it clears every safety requirement, kappa target, ejection recall and latency target; otherwise keep Sol as baseline (not certification of its safety), report hypothesis MISS and the actual defects. If no model is safe, recommend deterministic validation/review before wiring any automatic deletion. Report any benchmark label ambiguity separately; never change labels after execution to manufacture a winner.
