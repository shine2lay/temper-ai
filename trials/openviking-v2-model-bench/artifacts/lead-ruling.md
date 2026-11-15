# QA lead's ruling on the final check of data #20

Written 2026-11-15 after reading the task's result (qa #167). The 144 grades were not touched
(sha256 f9e6f681a2b8e49812935927e1186e3d00086e1e6544f8de68ed1864d1daf4d3).

## The safety row: from FAIL to "not met as worded, met against the protocol"

The task reported FAIL on one row: the safety log shows 10 blocked write attempts on the live memory
folder, and the request to QA read "0 denied live writes".

- As the request worded it, the row is not met: 10 blocked attempts, not 0. The report does not turn
  that number into a zero.
- Against the protocol it is met, as far as the guard can see. The protocol says the guard rejects
  changes under the live folder and that the log keeps the rejected ones. What it forbids is a change,
  not an attempt. The guard's code refuses before the operation runs (run_bench.py, the `raise` at the
  end of `guard`), and 0 connections went to port 1933.

Four limits Data's report must carry with it:

1. The receipt's field is called `live_writes` and holds the number of blocked attempts (5 and 5).
   Anyone reading "live_writes: 5" reads five writes. Rename it, or explain it where it is printed.
2. A blocked record keeps the path only, not what was tried. All 10 name the data folder itself.
   Making a folder that already exists would have changed nothing; changing its permissions or times
   would have. The log cannot say which.
3. The guard watches file opens and a fixed list of file operations inside the harness's own Python
   process. It does not watch database connections, other processes the library starts, or code
   outside Python. The honest claim is "0 live changes seen by the guard", not "0 on the machine".
4. protocol.md was last saved at 18:51:00 UTC and the first call started at 18:51:04 UTC, and the
   file is not committed. "Written before the run" rests on that file time alone.

## The lead's own reading of the grades

Six graded bundles read against the packets: S06-r1-A, S06-r1-B, S01-r1-B, S02-r1-C, S10-r1-A,
D07-r2-B. The lead agrees with all six grades. S10 stays a judgment call, as the task says.

A script check on all 21 answers that did not pass: 26 of the 28 quoted fragments in the defect notes
are in that answer or in its source notes; the other two are not quotes (the pattern matched plain
text between two quote marks).

## Three more findings

- **The harness files changed after the run.** run_bench.py and evaluate.py were last saved at
  19:04:45 UTC. The last result is from 18:56:31 UTC and the re-run from 18:58:27 UTC. The protocol
  promises a reproducible harness. Data should say what changed, and show that the instruction hash
  of the file as it is now still equals the one in plan.json.
- **The packets and the key were rewritten at 19:03:10 UTC, while QA was grading** (grading ran from
  19:00 to 19:04). The grades fit the packets as they are now (the quote check above, and the task's
  check that the 144 answers match the stored outputs by hash). Data should confirm the rewrite was
  a regeneration with the same seed.
- **The second network address** in the safety log (one connection per model-calling run) resolves
  today to GitHub's raw-file host. What was fetched is not recorded.

## Not checked by the lead

Whether anything changed in the live folder during the runs (off limits, and the live service writes
there all the time, so file times would not tell). Data's report, metrics and the key: not read.
