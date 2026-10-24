# P5: offline bound assessor for ops host receipts (ABI A6, A6.1-A6.3, A7, A8; CASE F5)

`configs/architecture/bin/ops_host_client_bound.py` judges one Project 3 host receipt offline,
against QA's received rules, inside one armed window that it reads and binds first. It is
UNTRUSTED end to end: its verdict is an offline comparison, never a counted row result, a row PASS,
an adoption or a native check. It writes nothing, runs nothing, opens no socket, makes no Docker or
host call and reads files only through the received P1 reader. Tests:
`tests/test_architecture/test_ops_host_client_bound.py`.

It is built on the four received source pieces, used exactly as landed:

| Piece | Module | Used for |
| --- | --- | --- |
| R1 (P1) | `ops_host_binding_files.py` | every file read (`read_private_file`) and every recheck (`recheck_files`) |
| R2 (P2) | `ops_host_binding.py` | the candidate (`load_project_candidate`, `load_calibration_candidate`, `recheck_candidate`), `SIX_PINS`, `REQUIRED_NATIVE_CHECKS` |
| R3' (P3) | `ops_host_inspect.py` | every inspect edge (`parse_inspect2`; either start/finish order is accepted there, P5 judges the order per leg) |
| R4 (P4) | `ops_host_env.py` | every Env comparison (`compare_window_env`) |

The legacy `ops_host_client.py` (c537bed9) is not imported, called or copied (helper audit below).

## API

```python
load_bound_candidate_window(path: str, window_sha256: str, *, data_context: object, uid: int) -> CandidateWindow
judge_candidate_receipt(request_raw: bytes, receipt_ref: dict, *, window: CandidateWindow, now: datetime) -> UntrustedAssessment
```

- `CandidateWindow(trust, window, target, reads)`: frozen; `trust` is always `"UNTRUSTED"`; `window` is the
  parsed armed window, read-only; `target` is R2's `CandidateTarget`; `reads` is P5's window read followed
  by every R2 read. Any other shape raises `TypeError`.
- `UntrustedAssessment(trust, verdict, code, identities)`: frozen; `trust` is always `"UNTRUSTED"`;
  `verdict` is `PASS`, `FAIL` or `BLOCKED`; PASS and FAIL carry `code="NONE"`, BLOCKED carries exactly one
  of the eleven codes; `identities` holds `(label, sha256)` pairs (at most 256), starting with the window.
- `TargetRefused(code)`: P5's own local refusal (A7), a `ValueError` whose args, str and repr are the code;
  any other code raises `TypeError`. The load raises it; the judge never raises, it returns BLOCKED.
- `CODES`: the eleven A7 codes, in R4's order. `UNRESOLVED_NATIVE_CHECKS`: see below.

There is no default UID, no clock read (the caller passes an aware `now`) and no other entry point.

## The data a caller supplies

- `path`, `window_sha256`: the armed window's absolute path and SHA-256.
- `data_context`: R2's context for the route (project or calibration, chosen by its exact key set), whose
  `window` Ref and `expected_window_sha256` must equal `path` and `window_sha256`.
- `uid`: the owner every read file and folder must have (R1's rule).
- `request_raw`: the exact `ops-host-request/1` bytes the controller wrote (P5 hashes them for the
  receipt's `request_sha256` echo).
- `receipt_ref`: `{path, sha256, byte_length}` of the receipt at `<host_dir>/<row>.json`, the request's
  own `receipt_file`.

## Order of checks

Load: argument shapes (CONTEXT_MISSING) -> window Ref equal to the arguments (BINDING_INVALID) -> the
window read FIRST through R1 with its declared length (PUBLICATION_INVALID; drift stays SOURCE_DRIFT) ->
strict JSON -> R2's loader for the route (R2's codes pass through) -> the closed armed window of
host-publication-v2 O 6.6, every member typed, TTL and bytes consistent (EVIDENCE_INVALID) -> cross-check
with the candidate: same window bytes and hash, same binding, same calibration selection and the six
pins re-derived from R2's retained closure (BINDING_INVALID) -> recheck at `load-complete`.

Judge: the window is a `CandidateWindow` and `now` is aware (CONTEXT_MISSING) -> recheck at `receiving`
-> the request (unsupported dispatch first, then its closed shape and its echo of the window) -> the
receipt through R1 by the exact Ref -> the common envelope and echoes -> the operation's own rules ->
recheck at `before-count` of the window and every file the judgment read.

## Codes (A7)

| Code | When |
| --- | --- |
| TARGET_CONTEXT_MISSING | bad arguments or context shape; a window that is not a `CandidateWindow`; a naive or non-`datetime` `now` |
| TARGET_PUBLICATION_INVALID | the window itself cannot be read through R1 or is not one strict JSON object |
| TARGET_BINDING_INVALID | the window Ref differs from the arguments; any binding object (window, request, receipt, prior receipt) or the S4 selection differs |
| TARGET_SOURCE_MISSING | unsupported dispatch: standalone `stop-graceful`/`stop`, W-IMG `engine-image`, HOST-L `launch-cases`, LIST, `ops-host-request/2`, `ops-host-receipt/3` (format or document), a Target2 `operation_binding` member |
| TARGET_SCHEMA_MISMATCH | any other unknown request or receipt schema; an `ops-host-inspect/1` edge (R3') |
| TARGET_SOURCE_DRIFT | any recheck finds a changed file |
| TARGET_EVIDENCE_INVALID | everything else, including all four bad-Env cases (malformed, missing, lying, unbound: QA61 r3 N2, the F5-EDGE-ENV row wins over ABI.md:152) |
| R2's own codes | ISSUER_UNTRUSTED, SELECTOR_MISSING, SELECTOR_AMBIGUOUS, REVIEW_MISSING and the rest pass through from the load |

## Verdicts (A6.1)

- Crash (D-1, API-D-1): KILL, exit 137, listener gone, origin refused, a terminal `stop_inspect` whose
  exit time equals `exited_at`, `oom_killed` false. Only an Env miss at the terminal edge is FAIL (with a
  truthful `FAILED`/`app`); any other miss is BLOCKED, even beside an Env miss.
- Start (D-5, API-D-5): before-inspects stopped, after-inspects running, the start audit by its exact
  sibling leaf, the probe cadence, first 200 within 30.000 s, the health observation, identity evidence
  with truthful `before_matches_creation`/`after_matches_creation`. The prior crash receipt is loaded by
  its row, writer, request id, sequence, hash and length and judged as a complete crash; a truthful
  complete prior whose Env was false carries FAIL through a clean later start (the start receipt's own
  decision is judged against its own leg only).
- Restart (R-1 TERM, R-1i INT): exactly `[stop-graceful, start]`. Stop misses that FAIL: nonzero exit,
  both measures over 10 s, forced kill, no `Stopped.` line, a traceback, an Env miss. Precedence: any
  BLOCKED leg makes the row BLOCKED, else any FAIL makes it FAIL, else PASS; the parent decision must be
  `FAILED`/`app` exactly when a leg failed, the parent exit code equals the stop leg's, and the start
  leg's exit code is null. A missing, lying, host-failed or refused leg, a second start leg or a second
  `docker start`, drift, a start outside the armed window or after its TTL are BLOCKED.
- Truth: `DONE` must have no miss; `FAILED`/`app` must have a miss; `FAILED`/`host` and `REFUSED` are
  BLOCKED.

## Timing (A6.2, TD-1)

- Every number is a `Decimal` parsed from the original JSON number text (`parse_float=Decimal`); `true`,
  `false`, strings and null are not numbers. Instants are parsed by a fresh ASCII grammar (real calendar,
  `Z` or `+HH:MM`/`-HH:MM`, `-00:00` refused, one to nine fraction digits) into integer microseconds.
- One band, `BAND = 0.001` s, inclusive. A reported value and its computed twin must agree within it and
  fall on the same side of the limit, or the row is BLOCKED.
- Health: only the first 200 and its `seconds_to_health` decide the 30.000 s deadline; the observation's
  end and elapsed are checked against each other (band) and against `health_elapsed_seconds` (exact
  equality), never as the deadline.
- `seconds_to_exit` is one-sided: at least the daemon-computed exit time minus the band and at most the
  leg span plus the band; `within_10s` must equal the computed answer.

## Witnesses (A6.3)

- Request ids are lower-case hyphenated UUIDs of any version.
- The probe host header is the literal `<address>:<port>`; a 400 is BLOCKED (E16).
- Cadence: probes are serial, each with the fixed 3 s timeout, the first within 0.750 s after the
  forwarder start, gaps of at most 0.750 s, none started at or after the deadline, none after the first
  200; a late in-flight 200 keeps its real times (FAIL), a clamped or synthesized one is BLOCKED; a miss
  needs coverage up to the deadline.
- runtime23: the 22 immutable members of every edge must equal the window's creation record (drift is
  BLOCKED); `env` is compared through R4 against the creation record, which must itself be the bound Env
  (the image baseline plus the four APP overrides).

## HOME additions (A6.1 chronology; for QA's R5 receiving)

These implement A6.1's existing "chronology" per leg. They are not a contract change; QA receives them
with R5.

- F5-LEG-ORDER-START: on a start leg, the running observation has `running` true, a real `started_at`
  (not the zero sentinel) at or after the start was sent and at or before `observed_at`, and a
  `finished_at` that is either the sentinel (first start: never exited) or before `started_at` (a
  previous exit). `finished_at` at or after `started_at` while running is BLOCKED, TARGET_EVIDENCE_INVALID.
- F5-LEG-ORDER-STOP: a stop or crash leg's terminal observation has `running` false and a real
  `finished_at` at or after `started_at`. A `finished_at` before `started_at`, or a sentinel one, is
  BLOCKED, TARGET_EVIDENCE_INVALID.
- F5-SENTINEL-NO-EVENT: `0001-01-01T00:00:00Z` means no event. A running observation with a sentinel
  `started_at` is BLOCKED, TARGET_EVIDENCE_INVALID; a first start's sentinel `finished_at` reads as never
  exited.

P5 supports host-driven operations only. The received specs fix `restart_policy`'s shape and its
immutability, not its value; the leg-order rule assumes no restart by the engine.

## Native versus data

Everything P5 returns is data. A PASS here proves only that the receipt agrees with QA's rules over the
bytes P5 read; it is never counted, adopted, a row PASS or a compatibility claim. These stay unresolved:

`UNRESOLVED_NATIVE_CHECKS` = R2's five `REQUIRED_NATIVE_CHECKS`, then
`NATIVE_PRIOR_RECEIPT_ISSUER_SCOPE_AND_JOB`,
`ACTUAL_INSPECT2_PRODUCER_VALIDATOR_CORPUS_AND_CALLER_COMPATIBILITY` and
`COUNTED_ADMISSION_AND_ROW_RESULT`.

## Residuals and notes for QA's receiving

- Armed interval: read as `[window_started_at, window_expires_at)`; a start before it is NOT ARMED, a
  `docker start` at or after its end is past the TTL. No BINDINGS field states it; QA receives the reading.
- `now`: a receipt whose `at` or `seen_at` is after `now` is BLOCKED.
- LD-1 1.4 (bytecode-cache exclusion for app-copy comparisons) is not judged; a truncated
  `app_copy_changes` listing is BLOCKED. Optional listings other than `data` are checked for grammar,
  window and hash only.
- No new tolerance beyond TD-1's band; any other timing idea is a note for QA, not code.

## Helper audit (legacy `ops_host_client.py`, c537bed9)

Nothing is imported or copied. `Evidence.load/listing/inspect/terminal`, `_audit`, `_probe`,
`_start_facts`, `_health`, `_prior_crash`, `_judge`, `judge_receipt`, `_common`, `_envelope`, `verdict`,
`_agree`, `read_bound` and `load_window` are direct-read paths or carry unqualified success branches.
`_num` accepts binary floats, `instant` uses Unicode `\d`, accepts `-00:00` and truncates digits,
`_uuid4` accepts only version 4, and `_cross`, `_exit_cross` and `_pairs` have the right logic over the
float path or the legacy exception class: all re-implemented fresh.

## Tests

`tests/test_architecture/test_ops_host_client_bound.py` builds its own synthetic future /2 world in
`tmp_path` (0700 folders, 0600 files), with restart-leg data of its own (Ops R5-A42 A1). Every F5 row
and each HOME addition has named N and C cases with the exact verdict and code; the eleven-code pin, the
CODE-VERDICT constructor pairs, the window-first recorder and static scan, the direct-read trap, the
recheck boundaries and a check-disable bite for each required guard have their own tests; a coverage
test checks the 89 F5 IDs and the 3 additions against the case table.
