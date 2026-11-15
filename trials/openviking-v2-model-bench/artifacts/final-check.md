# QA final check: OpenViking v2 model benchmark (data #20)

QA task #167, the one blind final check (rule 33). One rater. 2026-11-15.

## Verdict

**PASS WITH NOTES** (QA lead's ruling after reading the task's result; the grades were not touched).

The task first reported FAIL on one row: 10 blocked write attempts on the live memory folder, where the request to QA read "0 denied live writes". The lead's ruling, in full in lead-ruling.md beside this file:

- As the request worded it, the row is not met: 10, not 0. This report does not turn that into a zero.
- Against the protocol it is met as far as the guard can see: the protocol forbids a change, not an attempt, and the guard refuses before the operation runs. Limits Data's report must carry: the receipt's `live_writes` field holds blocked attempts; a blocked record does not say what was tried; the guard sees file operations in one Python process only, so the claim is "0 live changes seen by the guard".
- The lead read six graded bundles against the packets and agrees with all six grades.
- New: run_bench.py and evaluate.py were saved after the last result; the packets and key were rewritten while QA was grading (the grades still fit the packets as they are now). Data should explain both.

All other rows pass. The grader test caught 10 of 10 planted mistakes and flagged 0 of 5 untouched answers.

Before deciding on a cheaper model:
1. **Write attempts.** Each model-calling run logged exactly 5 (pilot of 24 calls: 5; main run of 120 calls: 5; the no-call re-run: 0). That is per run, not per call, so the likely source is the model library starting up, not the models. Data finds the source and writes it into the protocol as expected and blocked, or stops it.
2. **Labels.** In S01, S03 and S06, nine answers kept the old note but clearly marked it as retired or historical. The labels count them wrong; QA counts them right, per the protocol's "history stays history". Data should re-score with those nine accepted and check whether the ranking changes.

## Proof table

| Check item | Command / file | Observed | Result |
|---|---|---|---|
| 144 valid grade records | `qa_packet.py validate` on the grades | records=144, exact id match, types ok | PASS |
| Frozen before plants, labels, metrics | freeze.txt, file times | sha256 f9e6f681…daf4d3 at 19:04:40 UTC; freeze.txt older than plants.json; cases.json first opened after the plant comparison; key never opened | PASS |
| Graded answers = model outputs | `qa_artifacts.py` | 144 packet answers match the 144 stored outputs by hash; packet hashes match Data's manifest | PASS |
| Grader trust (planted mistakes) | `qa_plants.py compare` | 10/10 caught (2/2 per field), 0/5 controls flagged; plant grades frozen first (sha256 7b005267…cd8eb5) | PASS |
| n = 24, 14 dedup / 10 sweep | cases.* | 24 unique; 14/10 | PASS |
| Four categories | cases.categories | decision 6, gotcha 5, preference 6, system 7 | PASS |
| Labels consistent | labels.structurally_consistent | each note once; every must-keep string sits in a kept note | PASS |
| 144 planned, each case × model × repeat once | plan.* | 144 jobs, 24 × 3 × 2, no duplicates | PASS |
| 144 completed once | results.*, attempts.* | 144 results and 144 attempt records, ids equal the plan, 144 ok | PASS |
| Plan hash stable | results.plan_hash | 144/144 match plan.json; plan's case hash matches cases.json | PASS |
| Token usage | usage.* | in/out/total present 144/144 (0 unknown, 0 zero); total = in + out 144/144 | PASS |
| Latency | usage.latency_s | 144/144 in results and in attempts | PASS |
| No port 1933 | safety.port_1933_total | 0 in 3 runs | PASS |
| No blocked live writes (as the request worded it) | safety.denied_live_writes_total | **10**, all on the live data folder, all blocked; Data's manifest also says 10 | **NOT MET as worded** |
| No live change seen by the guard (the protocol's rule) | run_bench.py `guard`; safety-attempts.jsonl | each of the 10 refused before the operation; guard covers file operations in one Python process only | PASS, with limits |
| Harness source unchanged since the run | file times | run_bench.py and evaluate.py saved 19:04:45 UTC, after the last result | NOTE |
| What the log records | safety.run1-3 | address and port of each connection and path of each blocked write; 146 HTTPS connects: 144 to the model endpoint plus 1 per model run to GitHub's raw-file host | recorded |
| Resume skips finished work | safety.run3, attempts | full re-run: 13 ms, 0 connections; attempt log stayed at 144; pilot jobs not repeated; harness skips matching-hash results and refuses a mismatch | PASS |
| No credentials or request bodies | secrets.* (164 files) | 0 hits: tokens, keys, auth headers, chat bodies, instruction text | PASS |
| Label review | cases.json | 7 questionable points, nothing changed | NOTES |
| doc-check protocol.md | `doc-check` | PASS (max 42 lines / 1733 tokens, 0 broken paths) | PASS |
| doc-check this file | `doc-check` | PASS | PASS |
| wt check | `wt check --fast` in the data worktree | PASS (types/tests skipped in fast mode). Trial folder untracked, so maybe not scanned; its Python files are under 500 lines (max 230) | PASS |

## Grade totals (144 answers, no model names)

Topics separate 142, facts kept 132, nothing invented 142, history right 132, concise 142, corruption 10, not gradable 0, all fields pass 123.

Sample defects: an out-of-date cleanup kept as current ("For the requested Rule 34 cleanup, use a standalone task..."); old test cases from the replaced 30-minute rule kept ("snapshot age 16m with a rebuild in flight -> health_state healthy"); history rewritten ("pi-web-deploy --when-idle with the landed SHA" became "pi-web-deploy with the landed SHA"); "receipts" narrowed to "health receipts".

## QA grades vs labels

Agree on 128 of 144, matched by answer hash with no model names.
- **QA pass, label wrong (11):** 9 history-marked notes (S01 ×3, S03 ×2, S06 ×4). Two kept a harmless remnant and dropped the old part: S05-r1-C kept the test setup line, S10-r1-B kept "Wait live.". A stricter rater might fail those two.
- **QA flag, label right (5):** narrowed facts (D02-r1-C, D10-r2-C) that word matching cannot see; the past "--when-idle" step dropped or rewritten (S02-r1-C, S02-r2-B); evidence pasted into a note (S04-r2-A).

## Questionable labels (not changed)

1. **S06:** the evidence itself keeps the retired route's rules as history, so a history-marked n1 is as correct as removing it (4 answers scored wrong).
2. **S01, S03:** same issue (3 + 2 answers).
3. **S10 n2:** "pi-web-deploy queues itself..." may be out of date given "deploy immediately". QA marked down 4 answers that dropped it; that grade is uncertain.
4. **S02:** the must-keep list leaves out "--when-idle", the one history value under test.
5. **S03 n2:** a 240-character notebook rule that may be dead now that notebooks are read-only.
6. **D03:** n3 shares no clause with n1/n2; separate items would be defensible.
7. **Must-keep strings of 1-3 characters (8):** "5", "15", "19", "30", "240" ×2, "500", "624" match almost anywhere.

## Not tested, and how sure

- One rater; no second grader or agreement score. The S10 grade and history-marked notes are judgment calls.
- QA planted the mistakes itself after seeing the answers, so 10/10 is likely on the high side.
- 24 hand-picked cases, not a random sample.
- QA did not look in the live folder (off limits), so nothing here shows the folder was unchanged.
- No model calls or service access by QA; Data's report not read.
- Confidence: high for the artifact counts, medium-high for the grades, medium for the label points.

## Files

Grades at /tmp/ov-v2-model-bench/blind-grades.json (sha256 f9e6f681a2b8e49812935927e1186e3d00086e1e6544f8de68ed1864d1daf4d3). Rubric (sha256 107dfbd6…115276), scripts, plants, outputs and lead-ruling.md at /home/shinelay/qa-lab/ov-v2-model-bench/. This report and the ruling are in both places.
