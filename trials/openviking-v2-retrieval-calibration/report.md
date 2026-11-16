# OpenViking v2 retrieval and V-9 calibration

## Result
Source: frozen cases.json; purposive constructed store and existing Architecture/data24 labels.
Date: 2026-11-16T03:52:30.718204+00:00. Model: BAAI/bge-small-en-v1.5; real FastEmbed; OpenViking 0.5.4.
Preregistered commit: a8bed5e97b48baca57c1d26124707fc9654c4db0; no measurements preceded that commit.
Cases SHA-256: 12b40a93ba3ea2e594180c804fa0d8422ccf781e3e8744c33356f4db2d1b386e.
Hit/miss: {'twins_all_decrease': True, 'twins_n': 6, 'lead': True, 'worker': True, 'worker_baseline_v2_memory_recall_zero': True, 'gate_controls_pass': True}
Recommended constants (null means NONE meets preregistered bar): {'simLow': 0.65, 'lead': {'threshold': 0.65, 'keyword_gate': True, 'keyword_bonus': False, 'recall': 1.0, 'noise_count': 0, 'negative_n': 16}, 'worker': {'threshold': 0.65, 'keyword_gate': False, 'keyword_bonus': False, 'recall': 1.0, 'noise_count': 0, 'negative_n': 0}}

## Retrieval operating tables
Complete threshold/gate/bonus tables: retrieval-tables.md; raw queries and CIs: results.json.

Lead positives n=14 (8 direct, 6 topic-anchored followups); negatives n=16
(6 unanchored followups, 6 unrelated, 4 cross-role probes). Worker plans n=12;
expected items per plan: 1 project resource + 1 shared memory + 1 own-role memory.
No Worker negative-plan slice exists: Worker noise is N/A (0/0), NOT proved zero;
retired/cross-role leakage is separately checked across all 12 plans.
Lead zero-noise 0/16 Wilson upper 95% bound = 0.1936;
Worker zero-leakage 0/12 upper bound = 0.2425.
Per-query hits, recall-by-kind and each policy CI are retained in results.json.

## V-9 distributions
| Label | n | min | p10 | p50 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|
| contradiction | 3 | 0.8497 | 0.8683 | 0.9423 | 0.9442 | 0.9447 |
| data24_both_stay | 18 | 0.5264 | 0.6296 | 0.7029 | 0.8115 | 0.9190 |
| evidence_ejection | 5 | 0.4674 | 0.5148 | 0.6546 | 0.7761 | 0.7885 |
| gate_surviving_control | 4 | 0.6392 | 0.6474 | 0.7086 | 0.7797 | 0.7921 |
| must_merge | 9 | 0.8192 | 0.8361 | 0.9420 | 1.0000 | 1.0000 |
| near_twin | 3 | 0.7533 | 0.7814 | 0.8939 | 0.9457 | 0.9587 |
| unrelated_control | 13 | 0.4326 | 0.4408 | 0.4964 | 0.7339 | 0.7921 |

### Frontmatter twins
| Pair | Before | After | Delta | Pass |
|---|---:|---:|---:|---|
| TWIN-1 | 0.8270 | 0.4358 | -0.3913 | True |
| TWIN-2 | 0.8613 | 0.4613 | -0.4000 | True |
| TWIN-3 | 0.7893 | 0.4946 | -0.2947 | True |
| TWIN-4 | 0.7960 | 0.5266 | -0.2694 | True |
| TWIN-5 | 0.8319 | 0.4326 | -0.3992 | True |
| TWIN-6 | 0.8710 | 0.4612 | -0.4098 | True |

### simLow candidate-generation operating table
| simLow | Positive retained / n | Recall | Controls passed / n | Gate-surviving controls passed / n |
|---:|---|---:|---|---|
| 0.35 | 12/12 | 1.000 | 4/13 | 4/4 |
| 0.45 | 12/12 | 1.000 | 4/13 | 4/4 |
| 0.50 | 12/12 | 1.000 | 4/13 | 4/4 |
| 0.55 | 12/12 | 1.000 | 4/13 | 4/4 |
| 0.60 | 12/12 | 1.000 | 4/13 | 4/4 |
| 0.65 | 12/12 | 1.000 | 3/13 | 3/4 |

## Safety and reproducibility
All writes use vectors_only against a disposable localhost OpenViking workspace under /tmp.
Isolation audit: {'live_1933_requests': 0, 'forbidden_operations_denied': 6, 'allowed_http_requests': 1194, 'audited_connects': 1220, 'live_config_reads': 0, 'workspace_policy': '/tmp/ov-data21-* only', 'model_calls': 0}
Parent/child Python audit guards block live paths and all other TCP ports, including 1933.
These are Python audit observations, not an OS-wide syscall trace; native extensions are a limitation.
Raw measurement units are append-only; plan and input hashes freeze once; partial resume and
completed skip attempts are in evidence. Temporary server configuration/logs remain under /tmp;
model payloads are never copied into this trial. Model weights hashes are recorded in results.json.
manifest.json hashes all trial artifacts except itself and transient Python cache files.

## Interpretation and limits
Recommendations are in-sample candidate-generation settings, NOT safe deletion decisions.
Identifier-sharing unrelated facts may survive the gate and similarity cutoff; a judge must still
distinguish duplicates, contradictions and orthogonal facts. No constant authorizes auto-ejection.
Frontmatter twins isolate metadata contamination; ordinary pairs use unmodified source texts.
Data24 sweep ejections depend on canonical evidence and are not counted as semantic duplicates.
This English purposive sample is small and adversarially saturated (360 retired distractors).
Intervals describe frozen-case variation, not population guarantees. Recall with shared phrasing
can be optimistic; multilingual, long-tail, natural topic titles and held-out plans remain untested.
If a preregistered bar misses, keep it a miss. Architecture/Ops/QA decide implementation and QA
owns the single independent final check. No live production defaults were changed.
