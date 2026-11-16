# OpenViking v2 retrieval and V-9 preregistration

## Question and hypothesis
Data task 21; Architecture #543; requests rm-057a8d1e / rm-b0a919a6.
Problem: Lead search truncates polluted namespaces before filtering; Worker Slots 2/4
still use v1 entity/cases paths. Identical YAML may inflate unrelated-pair similarity.
Evidence: frozen injector.ts and candidate-gate.ts in sources, not live data.
Change: search active category/project prefixes before top-k; topic-anchor noun-less
followups; require the canonical identifier/stem gate for Lead hints; embed only
headline + body for V-9. No production code is changed by this experiment.
Expected: higher recall, zero unrelated/retired/private injection, lower twin cosines.
Falsification: any measured bar below fails; no passing result will be invented.

## Frozen inputs and sources
Commit this protocol, cases.json, freeze_cases.py and sources before measurements.
Runner must verify the committed input bytes and record the preregistration commit.
Canonical labels: sources/acceptance.json judgment_set (12 pairs) and data24.json
(24 original cases). Provenance paths in data24 are strings, NEVER files to read.
Pairwise decisions mean eject_a, eject_b, or both_stay; complementary multi-note
merges are not duplicates. A superset permits removing the subset, not vice versa.
Sweep labels need their canonical evidence and are excluded from similarity ROC.
Singleton S04 has no pair and stays in the frozen source; do not invent a partner.
New additions: six unrelated frontmatter twins and four unrelated pairs sharing a
real identifier. All four must pass canonical §5c.5. Pair decisions do not substitute
for contradiction labels: contradictory claims are candidates, not automatic merges.
Retrieval: 8 direct, 6 paired anchored/unanchored followups, 6 unrelated, 4 cross-role
probes; 12 Worker plans across all four categories and two projects. Every plan has
one resource, one shared and one caller-role relevant item. Caller=data; shared=default.
Adversarial store: 30 retired same-topic distractors per topic (360 total), equally
split between _legacy_v1/events and _ejected. Constructed worst case, not prevalence.

## Safety and apparatus
Use only /home/shinelay/.openviking/venv/bin/python, real FastEmbed
BAAI/bge-small-en-v1.5 (384 dimensions), and OpenViking version exactly 0.5.4.
Throwaway server: ephemeral 127.0.0.1 port, all writable state under /tmp.
NEVER contact port 1933 or touch ~/.openviking/data or ~/.pi/openviking.
Install a Python audit guard in parent and child against forbidden paths and network;
network allowed only selected throwaway localhost port. Record requests and denials.
Use local cached weights (no network). No model calls: vectors_only writes and
configured unreachable VLM endpoint. Do not inspect model request bodies or tool lists.
Import the installed launcher's embedder patch only, never its main() or live config.
Keep server lifecycle in this external trial, never in production or Temper workflows.
This is a throwaway OpenViking server, NOT a separate Temper test server.

## Compared algorithms
Baseline Lead: search resources + shared + caller memory roots (8 each), discard
_ejected after search, truncate globally to 8, active/access filter, threshold, top-5;
unanchored short acknowledgments skipped even if a chat topic exists (current injector).
Candidate Lead: search project resources and each active category prefix for shared
and caller (before truncation); top-5, topic-anchor when supplied. No anchor -> skip
ack/filler. Enforce scope and retired exclusion. Compare canonical lexical gate on/off
and keyword/identifier bonus off/on (+0.15 per shared token, cap +0.30 for ranking
ONLY; threshold applies to raw server score, never bonus-adjusted score).
Baseline Worker: project resource search plus v1 entity exact-read and personal
cases/experiences post-filter (limit 6). Candidate Worker: project resources + four
active shared and caller category prefixes, each limit 8, global top-5. Same query
is taskPrompt + touches; compare bonus off/on. Do not reward unrelated resource hits.
Server scores are observed API search scores, not asserted to be raw cosine.
V-9 cosines are separately computed from real FastEmbed normalized document vectors.
For twins, Before=identical frozen YAML + headline/body, After=headline/body only.
Other pair Before=After (no fabricated metadata). Gate uses frozen canonical TS code;
parity with the source checkout is checked on all pairs and Unicode/route edge cases.

## Preregistered bars and selection
Fixed raw-score grid: 0.35, 0.45, 0.50, 0.55, 0.60, 0.65.
Lead: mean recall@5 >=0.85 on 14 positive queries; zero hints on all 16 negatives;
zero cross-role personal injection. Report each query kind separately.
Worker: baseline v2 memory recall exactly 0; candidate mean recall@5 >=0.90;
zero retired and cross-role injection. Also report resource and memory recall separately.
Noise denominator = negative queries, not all returned hits; zero noise = 0/N,
not evidence that population risk is zero. Leakage denominator = evaluated queries.
Legacy starvation = relevant items exist but none survive truncated baseline retrieval.
V-9: After < Before for EVERY one of six twins, no aggregate-only pass.
Lead/Worker recommendation = highest grid threshold meeting recall and zero-noise bars;
prefer gate on and bonus off among passing ties. If none pass, recommend NONE, not
relaxing the bar. Report all variants including ungated and unanchored.
simLow = highest grid threshold retaining >=95% of must_merge + contradiction pairs
AFTER the canonical gate; report raw recall, gate loss, unrelated pass counts and
percentiles. If no operating point meets this, report NONE and the observed ceiling.
This is candidate generation, not a safe automatic deletion threshold.
No numeric contract default changes are authorized by this study.

## Metrics and uncertainty
Recall@5 = |expected ∩ unique returned top5| / |expected|; macro-average positives.
Noise = negative queries with any hint / negative queries. Paired delta=After-Before.
Report min/p10/p50/p90/max and n per pair label and gate-surviving control slice.
Use Wilson 95% intervals for binary query risks; clustered bootstrap (2,000 draws,
seed 21) for macro recall, resampling topic families so followups do not fake extra n.
Fixed set is purposive and in-sample; intervals reflect case variation, not unbiased
population inference. Repeated deterministic embeddings are not independent trials.

## Resume and integrity
Freeze plan once: ordered units and input hash. Stable unit id + content hash;
same id/hash skips, changed hash refuses and appends a conflict attempt. Append-only
unit results; cursor advances durably after each unit. Limits yield normal partial
outcome. Rerun resumes that plan; do not re-plan against new inputs. A completed rerun
changes no measurement or output bytes (attempt log alone appends a skip receipt).
Prove real convergence by stopping after partial embeddings, resuming all queries,
and rerunning completed run. Manifest SHA-256 lists every input/output except itself
and states that self-hashing is impossible. Exact attempts and cursor are included.

## Verification and limitations
Unit tests: metrics, scope/skip, gate parity, blocked port/path, immutable plan,
conflicts, cursor recovery and completed rerun. Run once after implementation.
Run wt check, focused pytest and doc-check; land through repository's configured
canonical branch (wt.yaml currently master, not a newly invented main branch).
QA owns the independent final check; this builder report is not blind verification.
The frozen set is small, English, authored and scored in-sample: numeric recommendations
are provisional contract candidates requiring QA, not production readiness claims.
