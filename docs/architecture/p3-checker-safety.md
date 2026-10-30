# P3 source boundary: S1–S5 (#129), terminal cleanup (#136), N1 and W1 admission (#125), Security #105 fixes (#279), W1 from readings (#280), terminal-cleanup record (#338)

Source work only. No browser, controller, host operation, network plant, qualification or run permission.
Accountable lead: Architecture. Security's a217ee1c review remains CHANGES until its new exact-pin reply.
first_app_check.py, first_app_shared.py, their tests and every page fixture stay unchanged.

## H-P3-SAFETY-1 — written before implementation

Evidence: Security #13 REVIEW-a217ee1c.md, SHA256
f89250656e983c1c656122ac2139da996fec8c699b19353c73794faa0a8b5aac.
Reviewed commit: a217ee1cab85d0ed3fff502bc7b26dc13854dcfd.

One bounded change: make the P3 driver own its observation, stop, file and disposal boundary,
reusing unchanged legacy comparators/API/store logic, not the legacy unsafe probe/file/lifetime paths.
No SDK monkey patch, controller framework or persistent authority store.

| Gap / evidence | Proposed guard and changed boundary | Fixed-input clean/fault check and falsifier |
| --- | --- | --- |
| S1: newContext and probes omit SW block | setup_js and P3 probe_js force serviceWorkers:'block'; shared P3 event observers retain console/page errors and observed SW events | Execute generated code only in fake Node browser objects for both engines/probe kinds; every created context must block SW, observed registration errors retained. Any missing block or lost error falsifies. |
| S2: pending True defeats final drain; controls always continue; ordinary writes | one invocation-local StopLatch passed through probes/sections/cleanup/cases; exact event URLs drive W4, same-origin policy remains distinct; final return after drain; distinct W4 exit and exclusive 0600 regular receipt/list files (original literal 3 superseded by H6: W4=4, BLOCKED=3) | fake clean journey/batch continues; off-origin during pin/down/row/drain/close trips once and forbids later engine/case; same-origin bad path does not W4; empty/unmatched and NOT RUN never full success. Any later operation, non-distinct W4 exit, lost/truncated URL, followed receipt symlink or permissive file falsifies. |
| S3: probes unobserved, close not drained | same event observers installed before newPage/navigation in all P3 probes and setup; retained journal after failure/partial setup; collect close logs before fallback | fake navigation, redirect/failure and close emit exact request events; pin refusal retains them; generated JS failures still return terminal logs. DOM refs/route aborts alone never count as W4 witnesses. Missing terminal event falsifies. |
| S4: fixture copying, pinning and serving follow paths | P3 directory-anchored no-follow regular-file snapshot, verified file stability; bytes used for pins and static responses; literal route map unchanged | temporary clean/variant bytes equal reviewed hashes; fixture symlink, parent symlink, FIFO and substituted path rejected without following; pin/serve frozen bytes ignore later mutation. Any outside read or changed fixture/variant/route semantics falsifies. |
| S5: partial setup and CLOSE/host errors skip cleanup; thread can restart | journal contexts immediately; independent unconditional browser_close fallback; final close drain; control try/finally covers server start/pins/host; terminal shutdown latch plus server lifecycle lock serializes late host actions | fake missing page/partial setup/CLOSE/fallback failure and host exception/cancellation/start failure all dispose or BLOCK; no next case when disposal unresolved; queued thread start after shutdown refused. Any skipped stop/fallback, late restart or falsely confirmed cleanup falsifies. |

Tests use fixed temporary files and fake browser/MCP/host/server objects only. They do not connect to
MCP, start an HTTP server, browser, Docker operation or Temper instance. Existing network-starting
server tests are outside this source-only run, not rewritten, weakened or presented as executed.
Run relevant unchanged pure first_app/shared tests plus P3 safety tests once after all edits using
wt slot (docs/testing.md) and taskset -c 0-4,10-14. Record any miss and a new hypothesis before repair.
Normal mandatory landing checks remain mandatory and use the approved normal pipeline.
Architecture's explicit amendment permits only the unmodified mandatory gate's two pre-existing
P3 server tests with temporary data, loopback HTTP clients and finally cleanup, not a manual rerun,
new server-starting test, external destination, browser/MCP operation or separate Temper.
H-P3-SAFETY-8 (rm-817c9175) bounds the listener too: P3Server has only a keyword-only internal
bind_address choice of literal 0.0.0.0 (unchanged default/container caller) or 127.0.0.1 (every
instance in those two existing unit tests). Invalid addresses are refused before fixture reads.
No CLI/profile/environment option or arbitrary bind/publication feature is added. The affected
S5 seam/lifetime stage passed 18/18 using only fake constructors; existing HTTP assertions and
finally cleanup stay intact.

## Operational contract (not a new clearance mechanism)

P3 exit codes: 0 complete success; 1 FAIL/incomplete controls; 2 invalid live profile;
3 BLOCKED; 4 **W4 TRIPPED** only. Ordinary P3 and legacy first_app/shared exit codes are unchanged.
Since DECISION-11 (#280) the checker itself never says PASS for P3: a run whose rows all pass ends
BLOCKED (3) with a why starting "W1 pending: " and w1.on_count PASS, and the controls end 1 with
all_ok and full_qualification false while W1 is PROVISIONAL (the measured values are kept under
w1.on_count). Only first_app_p3_w1.py finalize's COUNT (exit 0) lets that result count.
Architecture's #129 amendment (rm-66681532) preserves BLOCKED=3 and assigns unused 4 to W4,
superseding the original literal W4=3 rather than changing an existing failure code.
An empty/unmatched selection and any NOT RUN are incomplete, never qualification success.
Selected-only controls can succeed as a subset, but full_qualification is false unless every named
control is OK. No expected-destination exemptions exist in this source; future network plants
need their own exact-pin source approval and exact-URL/per-kind witnesses.

Gate-plant controls (Security #105 G5-Q): a plant control is OK only when its plant is caught on
every engine that ran. A MISS is WRONG. Not exercised on an engine that ran (or no G5 result at all)
is NOT EXERCISED: the case's gap names the plant, its kind and the engines, and it is never OK.
full_qualification is also false unless every plant kind is caught on every engine that ran, or
Security has named the kind a blind spot (G5_BLIND_SPOTS in first_app_p3.py: a code constant, empty
now). all_ok follows the case statuses; summary g5 per kind stays, with g5_gaps beside it. DNS-only
lookups are a stated residual, not a plant kind.

W4 (DECISION-9 (b); Security #105 W4-X): an off-origin request that isn't a declared plant endpoint
stops the batch. The invocation exits 4 and runs nothing further (no later engine, probe or case).
Keep the request list (the receipt's w4 observations and observations.json) and send it to Security;
work resumes once the cause is known. Holding later runs is an operator rule, not a checker
refusal: W1 admission does not read an earlier receipt's W4 status, and there is no release record,
clearance file, profile key, CLI bypass or automatic resume. The older receipt-bound release wording
(only Security's reply bound to that receipt releases it) is dropped; the receipt's operator_hold
text (first_app_p3_guard.HOLD) still carries it, and DECISION-9 (b) supersedes it. This
invocation-local latch is not cross-process authority. These tests manufacture no real W4 receipt
and request no release of a real hold.

Unconfirmed browser/probe/server disposal is BLOCKED and prevents the next engine/case.
Receipts and exact event observation lists are exclusively created regular 0600 files, without
following a leaf or parent symlink; existing names are refused rather than overwritten.

## Terminal cleanup (#136, Security R1) — what the code does

Every P3 session (probe or journey) ends with exactly two steps, in this order, on every path
(success, failure, partial setup, cancellation):

1. One terminal CLOSE (first_app_p3_guard.CLOSE -> p3.close(true)). Inside it the driver closes each
   tracked context (page close and a context retry only on escalation), then its own carrier page and
   carrier context, reads the terminal state (guard_page_closed, guard_context_closed,
   other_contexts_left, untracked) and takes the last drain inside the same call (out.log = p3.drain()
   is its final statement). No DRAIN or other call addresses the carrier after CLOSE. A page without
   the P3 journal still has its page and context closed and returns an incomplete journal
   ("P3 journal missing").
2. One MCP browser_close, always the last MCP call of the session, attempted exactly once even when
   CLOSE raised or returned garbage. Its outcome is ok, error or unknown.

The terminal journal is {status complete|incomplete, reasons, boundary}; the boundary says what CLOSE
cannot see: "terminal CLOSE; subsequent MCP browser_close is unobserved". Any reason makes it
incomplete. A cleanup is confirmed only with a complete journal, no errors, browser_close ok, exactly
the expected contexts, each page_closed true and context_still_in_browser false, the carrier context
closed, other_contexts_left 0 and nothing untracked. Incomplete or unconfirmed -> BLOCKED (3) and no
later engine or case in that invocation.

When browser_close fails or its outcome is unknown, the receipt (cleanup or probe_cleanup entry, and
the receipt's top-level list) records mcp_service_recreation_required = {service, phase, reason,
enforcer, required_receipt}: that browser service is in an unknown state and needs Ops' reviewed W2
recreation (new container id and StartedAt, receipts to Security) before any further P3 use. The W1
admission refusal below enforces this across invocations.

A run that ends without a final receipt (Security #105 A6). Before a unit's first MCP call (a live
run; each control case), the checker writes started.json beside where that unit's receipt.json will
go: created once, 0600, fsync'd, naming the MCP service URLs and phases it is about to contact (both
engines' services, since WebKit may follow). The checker never deletes or rewrites it, and adds no
signal handler or timeout, so a SIGKILL leaves it too. If it cannot be written, no MCP call is made
(BLOCKED). A P3 run, live or controls, that ends without a final receipt.json (killed, timed out,
crashed, its container or Temper stopped) counts as a failed teardown: the services its marker names
are recreation-required, exactly as if browser_close had failed, and the marker makes W1 admission
enforce it.

### N1 (#125, Security's source GO note on ecd4cf2b): nothing between CLOSE and browser_close raises

- read_terminal() is total: a non-object result, contexts that are not an object, a non-object
  context state, errors that are not a list, an error entry without text step and error, a journal
  that is missing or not an object, reasons that are not a list of text, non-boolean guard flags,
  other_contexts_left that is not the integer 0, a missing or malformed event log: each becomes an
  incomplete reason (and the raw value, cut to 400 characters, is kept in errors), never an exception.
- Any object-shaped log in the CLOSE result reaches collect() before the shape check, so an
  off-origin request in a malformed result still trips W4 (exit 4) with its exact URL.
- collect() passes only object events to the W4 latch; a non-object event, a non-list kind or a
  watched event (requests, responses, failed, websockets, serviceworkers, popups) without a text URL
  blocks the invocation and is listed under malformed_logs.
- The reader and the confirmation are also wrapped, so a reader bug becomes an incomplete journal.
  browser_close and the recreation record always happen.

### Terminal-cleanup record (#338, #298's R1): which step failed, as fields

The prose stays as it was (each errors line, each journal reason). Beside it, the record now says which
terminal-cleanup step failed in fields a script reads, so a caught carrier-context close error and a
failed terminal CLOSE call no longer have to be told apart from wording.

- The guard's error entries inside CLOSE are {step, error, error_name, error_message}. error is String(e)
  as before. error_name is the error's name (or the thrown value's type); error_message is the first line
  of its message; at most 80 and 400 characters. No stack, no later line (Playwright's call log), no page,
  console or DOM value. Building them never throws.
- Every cleanup and probe_cleanup entry gets two more fields, after confirmed:
  - close_call: how the terminal CLOSE call itself ended. returned: it returned context and journal
    metadata. no-metadata: it returned something else. raised: the MCP call raised, timed out or was
    cancelled.
  - close_steps: one entry per step that failed, {scope, context, step, error_name, error_message}.
- step comes from a fixed list (CLOSE_STEPS in first_app_p3.py), and scope says which part of cleanup
  the step belongs to:
  - user: context-close, page-close, context-retry, escalation, disposal (a tracked context's disposal
    inside CLOSE; context is the checker's own name for it);
  - carrier: guard-page-close, guard-context-close, terminal-state (the guard's own page and context, and
    reading the terminal state);
  - mcp: mcp-close (the CLOSE call raised), close-metadata (it returned no context or journal metadata);
  - checker: close-reader (reading the result raised).
  Any other step text becomes step unlisted, scope unknown, and a context the checker did not expect
  becomes unlisted: the driver's own text never enters step, scope or context.
- error_name and error_message come from the guard's fields, capped again. For mcp-close and
  close-reader they are the Python exception's class name and the first line of its message (after an
  MCP "### Error" heading), cut from the same text the errors line beside them already holds. A malformed
  guard entry stays an errors line and a reason, as before, and adds no close_step.
- The two failures, by fields alone: a caught carrier-context close error is close_call returned with
  close_steps [{scope carrier, step guard-context-close, error_name Error, …}]; a failed terminal CLOSE
  call is close_call raised with close_steps [{scope mcp, step mcp-close, error_name RuntimeError (or the
  exception's own class), …}]. One guard error is one close_step, so the three phrases run 59850933 printed
  for a single error ("guard context close raised", "terminal journal not complete", "terminal disposal
  raised") show as one failed step.
- Where a reader finds it: the receipt's cleanup and probe_cleanup entries, and each unconfirmed
  session's entry in cleanup_unconfirmed (below), which reaches summary.md, the live line on stdout and
  controls.json. final_verdict's "cleanup not confirmed: …" text leaves the two new fields out, so it reads
  as before.
- What it does not change: the close order, the last drain, the journal and its reasons, the
  confirmation rule, browser_close and the recreation record. It makes no lifecycle claim: which boundary
  failed in a real run stays open until the next occurrence's record is read. Its fields are step
  identity and the error's name and message only; there is no page, console, DOM, prompt or tool-payload
  field.
- Why error_message holds no page content (Security rm-e2f1f6ba): no close step runs page JavaScript
  (ctx.close, page.close({runBeforeUnload: false}), ctx.pages, browser.contexts, page.isClosed, the
  drain), so a page cannot author the thrown value and the message is Playwright or Node text. That is a
  property of today's close body, not a constraint: the first close step that calls evaluate or
  waitForFunction makes error_message page-controlled, so such a step needs Security's look first. The
  same note sits beside CLOSE_STEPS and in the guard.

### Cleanup not confirmed (#338): the receipt, summary.md and controls.json say so

- finish() builds cleanup_unconfirmed from the receipt: one entry per MCP session, probes first, whose
  cleanup is not confirmed: {section (probe_cleanup or cleanup), phase, service (the MCP service URL that
  session used, else "unknown MCP service for <phase>"), close_call, browser_close, failed_steps (its
  close_steps), recreation}. recreation is one fixed text: the service must be recreated before any
  further P3 use, because its final teardown failed or is unknown (DECISION-12).
- No URL secret in it (Security rm-e2f1f6ba, Low): cleanup_unconfirmed is printed to stdout, which is
  the workflow's captured output, while receipt.json, summary.md and controls.json are 0600 files. An MCP
  endpoint URL can carry a user name, password or query token, and the MCP client's HTTP errors print the
  full URL (httpx: "Client error '401 Unauthorized' for url '…'"). So every scheme://… in the service and
  in each failed step's error_message is cut to scheme://host:port/path (without_url_secrets); a URL that
  cannot be read becomes "<unreadable URL>". The receipt keeps the verbatim URL where it already was:
  sessions, probe_services, errors and close_steps.
- summary.md: the Cleanup line is unchanged when every cleanup was confirmed. Otherwise it reads
  "Cleanup: NOT confirmed for N MCP session(s) (journey {…}; probes {…})", then the recreation line, then
  one line per session: its service, how the terminal CLOSE ended, browser_close and the failed steps.
  Before #338, a run whose only unconfirmed cleanup was a probe's printed "Cleanup: {}." (the journey
  had none), as run 59850933 did.
- controls.json: each case carries cleanup_unconfirmed, and the run level lists all of them with their
  case. The live line on stdout carries it too.
- mcp_service_recreation_required (recreation_required in controls.json) keeps its meaning: browser_close
  failures only. A failed terminal CLOSE followed by a successful browser_close still leaves it [], because
  that record is written only when browser_close fails; no recreation record is invented.
- Not enforced across runs: W1 admission (first_app_p3_admission.py) still holds a service only for
  mcp_service_recreation_required and unfinished markers, and does not read cleanup_unconfirmed. Until
  it does, the operator and the calling lead enforce DECISION-12's recreation from these lines.

### W1 admission refusal (#125, Security #16 condition 4)

Before the first MCP call to a browser service (the Chromium stage-A probe; the WebKit engine probe),
first_app_p3_admission.admit() reads the earlier receipts beside this run:
<root>/<run>/<out>/receipt.json and <root>/<run>/<out>/<case>/receipt.json, where <root> is the
parent of the run folder (main() derives it from --out; there is no flag for it). Receipts whose
journey is not "p3" are ignored. Among the P3 receipts that used the service (a probe, a session
that ran or was cleaned up, or a recreation entry naming it), the newest by finished_at decides. If
it lists mcp_service_recreation_required for the service (an "unknown MCP service" entry counts
against every service that receipt used), the service is refused: BLOCKED, with no MCP call.

The one way in is Ops' W2 recreation evidence, named by path and sha256 (live: the profile's optional
w2_recreation key; controls: --w2-recreation, the same JSON {service URL: {path, sha256[, before]}}).
The after record (#124 shape: mode "after", containers keyed by the compose service name, which is the
URL's host) must hash to the named sha256, show the service running with a full container id that
differs from the old one (from the failing receipt's own checked W1 before-reading, w1.before.id, or
the optional before record, taken after that receipt finished) and a StartedAt later than the failing
receipt's finished_at. For WebKit, this run's checked W1 before-reading (DECISION-11, below) must
also be that new container (same full id and StartedAt, running). The reference is evidence checked
byte for byte, not an override: there is no skip flag, no store of its own, and the checker gets no
network or docker access for it.

An unreadable, partial, non-JSON or malformed receipt, a symlink anywhere on the path, a missing
receipts root or more than 5000 receipts -> BLOCKED. The result is recorded in the receipt under
admission[service URL].

Started markers (A6) are uses too. A started.json with no receipt.json beside it is held like a
recreation entry for every service it names, timed by its started_at in the newest-use rule: only a
later P3 receipt for the service, or W2 evidence newer than the marker (a container started after it;
a before record taken after it), lets the service in. A marker whose content is malformed holds every
service, timed by its file's modification time, and is never treated as unused; a marker that is not
a regular file, is oversize or unreadable -> BLOCKED. Beside its receipt, a marker is only checked to
be a regular file: the receipt decides. The unit's own marker (admission is asked again before the
WebKit probe) is not an earlier run and is skipped by its exact path. Markers without a receipt are
listed under admission[service URL].unfinished_markers.

WebKit after a recorded recreation is admitted only when the W2 after record and this run's checked
W1 before-reading name the same new container. Without a before-reading, or with one the pre-check
refuses, WebKit is NOT RUN before admission is asked.

### WebKit W1 from two plain container readings (DECISION-11, #280)

W1 no longer comes from the W-IMG engine-image host operation (its armed window has never existed:
Ops #299, owner cards #403 and #508). It comes from two closed webkit-reading/1 files that Ops'
read-only reading tool writes (chromium-reading take --webkit, Ops #534; record shape in agent-tools
docs/ops-host-chromium-reading.md, "WebKit readings"): one before the checker starts, one after the
rows and teardown. Security agreed with conditions (rm-46a8c5a7). first_app_p3_w1.py reads only the
files it is named; the checker has no Docker, network or subprocess access for them. Host rows (R-1,
R-1i, D-1, D-5) are unchanged.

- Input: live, the profile's optional key w1_before {path, sha256}; controls, --w1-before with the same
  JSON (live mode refuses the flag). It follows the w2_recreation pattern.
- Pre-check (rule 2), before the first WebKit MCP call (the engine probe), after the profile's
  engine_image pin check and before W1 admission. In order, the first failure decides: input exactly
  {path, sha256}; a regular file read without following a symlink anywhere on its path (missing:before);
  sha256 = the named one (sha256:before); a closed webkit-reading/1 record, with no extra or missing
  key, the right types, sorted networks and holders, count = number of holders, alias
  playwright-mcp-webkit on network temper-ai_default, the fixed limits line and status OK
  (bad-schema:before; an UNKNOWN record is unknown:before with the tool's reason); image =
  ops_host_client.ENGINE_PIN (image-not-pin:before); running true, paused false, restarting false
  (not-running/paused/restarting:before; a missing or non-boolean state is bad-schema); exactly one
  holder (count-not-1:before) and it is the id (holder-not-id:before); taken_at earlier than the
  checker's start, the receipt's started_at (live) or the controls invocation's start
  (before-not-earlier). Any failure: WebKit NOT RUN, every WebKit row NOT RUN with "W1 before-reading
  refused: <rule>: ..." (no before-reading: W1_MISSING), and no WebKit MCP call. image-not-pin also
  blocks the invocation and names the image under security_fyi.
- Provisional (rule 3): the receipt's w1 holds the before-reading's path, sha256 and facts. Every WebKit
  step records w1 {before {path, sha256}, note "W1: provisional until the after-check"}; a measured PASS
  becomes PROVISIONAL (kept as measured; PH-1 and the verdict read measured). WebKit is never PASS or
  counted before finalize's COUNT.
- Admission (rule 4): the WebKit W2 match uses the checked before-reading (full id, StartedAt, running);
  the evidence names its path and sha256.
- Finalize (rule 5): first_app_p3_w1.py finalize --receipt <receipt.json or controls.json> --after
  <after-reading> --after-sha256 <its sha256>, after the run and its teardown. Files only: it re-reads the
  receipt, the before-reading it names (sha256 again) and the after-reading, checks both ends as above,
  then needs the same id, image, StartedAt, RestartCount and networks (a recreation is BLOCKED even with
  the same image: field-differs:<field>), the before-reading earlier than the run's started_at and the
  after-reading later than its finished_at (after-not-later). It writes one new closed record next to
  the receipt, w1.json (schema p3-w1/1: after, before, finalized_at, limits, receipt {path, sha256},
  result COUNT or BLOCKED, rule), 0600, created exclusively: an existing one is never overwritten (exit
  2, nothing written). Exit 0 COUNT, 1 BLOCKED, 2 not written (bad input, an unreadable receipt).
- Stated limit (Security, rm-46a8c5a7; the fixed limits line of every reading and of w1.json):
  "same-UID actors and in-container changes are not detected; readings are endpoint samples, not
  continuous monitoring".

## Canonical rows (#125): what the journey runs and how

- Rows, texts and judges: first_app_p3_rows.py, wired from QA #32 (specs-rows.json d7690a0e…,
  ARCH-EXTENSION-SPEC.md 49247ff8…) on Product FINAL v3.1 (c2a5ddbd…). The profile must carry that
  rows hash (kit_sha256); another version needs its own wiring. first_app_p3.py keeps how they run.
- Engines: Chromium runs its 37 rows in fresh contexts A, B, C, L, U, V; WebKit (390x844, scale 3,
  isMobile, hasTouch, native UA, taps) runs its 23 rows in fresh contexts A, B, C, U, V on its own copy
  of the build (origin_webkit, fresh data), then PH-1. WebKit does not depend on Chromium's row results;
  it stops only when the invocation is stopped (W4, BLOCKED, unconfirmed disposal).
- W1 in the run: the profile's engine_image must be Security's pin (ops_host_client.ENGINE_PIN); any
  other ID is BLOCKED and recorded under security_fyi. The W1 before-reading is checked before the first
  WebKit MCP call and every WebKit step names it; without a checked one WebKit is NOT RUN with no WebKit
  MCP call. WebKit results stay PROVISIONAL until finalize judges the after-reading COUNT (DECISION-11,
  above). W1 no longer uses the W-IMG engine-image operation.
- Host rows (R-1, R-1i, D-1, D-5) go only through first_app_p3_host: #126's ops_host_client writes the
  request (read_sequence, make_request, write_request, unchanged) and P5's ops_host_client_bound judges
  the receipt. Live writes are off: WRITES_ADMITTED is False, so open_host and run_row read nothing, load
  nothing and write nothing, and every live host row is BLOCKED. Only a reviewed code change turns it on,
  after a real admitted run bundle loads through P5, every native, access and Owner requirement holds, and
  #259's fresh R5' landing and QA's fresh receiving hold (lead DECISION-6 D6.4); no flag, file or profile
  key does. The profile's host_binding {context_path, context_sha256, uid} names a private file
  {window_path, window_sha256, data_context}; the wire reads it without following links, checks its hash,
  and loads the window through P5 (load_bound_candidate_window); the run bundle itself is issued only in a
  separately authorised launch (D6.3). Before the first row it settles its own pending WAITING requests
  (Ops' plan 6.2, QA rm-568d6d6e duty a, lead DECISION-7 D7.4) with two checks: a pending request must
  pass #126's validate_request and be this writer's and its file's row, else "WAITING-<row>.json is not
  this writer's valid request"; a <row>.json carrying its request id settles it only if it echoes it in
  full (the echo rule below), else "<row>.json does not match its pending request". It waits no longer
  than the pending request's ORIGINAL expires_at; settled requests are recorded, and nothing is judged
  with P5 or counted at settle. A receipt beside it with another id must be a validated earlier one;
  anything else is BLOCKED before SEQ is read. The legacy client's own HostClient.initialize skips,
  rather than refuses, an unmatched receipt at startup (c537bed9 lines 1218-1221; DECISION-7 D7.1);
  #125 doesn't use it, only read_sequence, make_request and write_request. Per
  row (duty b): the D6.1 action/expected texts and the D6.2 budget (R-1 and R-1i 120 s, D-1 and D-5 60 s);
  since = not_before = now, wait_seconds = budget, expires_at = since + budget; less window time left than
  the budget is BLOCKED with nothing written, never a shorter request. A prior <row>.json must be a
  validated earlier receipt (schema, window, binding, row, writer, operation; lower sequence, or the same
  sequence only for an unadmitted REFUSED receipt as #126's _prior allows; another request id; ended no
  later than this request's since), else BLOCKED before writing, and so is a prior #126's read_bound
  can't read (not JSON, not an object, a link, wrong mode, oversize), both "never ignored silently";
  a validated prior's unchanged bytes are then ignored. New
  bytes must echo the request in full: row, operation, host_action, writer, request_id, sequence,
  window_id and binding in value and type, and request_sha256 of the exact request file. The exact request
  and receipt bytes go to judge_candidate_receipt, and the row is UNQUALIFIED
  "P5 assessment: <verdict>, not counted": P5's verdict is untrusted data and counted admission is not
  settled (COUNTED_ADMISSION_AND_ROW_RESULT), so a host row is never PASS and the run is never PASS while
  it has one. No binding, a refused load, a missing or unsafe receipt by the deadline, or a write failure:
  BLOCKED (missing host evidence is never an app FAIL), and that engine's later rows are NOT RUN.
  One checker process per window is how runs are started; the wire does not lock across processes. In
  controls the
  fake controller acts on the check's own fixture server (restart, crash, start; never a real app or
  host) so the later browser rows are stage-tested; the host verdict is UNQUALIFIED, never PASS.
- The traffic gate in controls (G1-G5): each gate-plant control lists its plant's exact URLs
  (GATE_PLANTS: dedicated worker, WebSocket, EventSource, beacon, redirect, prefetch; literal *.invalid
  hosts in the served app.js; the redirect is the fixture server's fixed /plant-redirect route, 302 to
  https://redirect.invalid/r, served only in that copy). StopLatch.observe records an exact match
  (scheme, host, port with defaults, path, query, and no user name or password: a URL with userinfo is
  never a plant, Security #105 G3-a) in gate_catches; anything else off the origin trips W4.
  Builds and the other controls pass no list. In control runs a context.route aborts the off-origin
  http(s) requests it is handed and logs them as a second witness (log.aborted); a plant counts as
  caught only from the gate's own event record (G2). Builds never get the route. The route does not see
  everything (Security #105 DOC-R): Playwright calls route handlers only for the first URL of a redirect
  chain, so the 302 hop to https://redirect.invalid/r is not routed, and WebSockets are not routable
  without an in-page shim (there is none). So in controls the redirect and WebSocket plants are not
  aborted: they reach DNS for their fixed .invalid names. Report it as "DNS lookup expected; not zero
  egress". If a resolver answers anyway, TLS validation fails before any request or upgrade (no
  ignoreHTTPSErrors). Plants stay https/wss and controls-only; any other origin is W4. G5 per engine:
  caught, MISS (the page marked it sent, or the abort route saw it, and the gate did not) or not
  exercised (the engine lacks the feature). The rows' own page routes (held writes, the list abort)
  match only the build's origin and pass everything else on with route.fallback(), so they never take a
  request away from the context abort route (Security #105 R-1). Context routing also turns off the
  HTTP cache in control runs: a known difference from build runs.
- The fixture server serves only the literal STATIC map (/, /index.html, /style.css, /app.js,
  /favicon.svg), GET /api/items and the API writes, plus /plant-redirect in its own copy: no listing, no
  symlinks, nothing else. It binds on the docker network for the run only. Each control case runs two
  copies (a for Chromium, b for WebKit) with their own data and the same captured bytes;
  webkit_tree_sha256 is the sha256 of the copy's 'sha256  name' lines.
- Out of this checker's scope (listed in every receipt): CR-1, API-D-1, API-D-5 (QA's api_check), HOST-L
  and the host's own records, QA #31's larger corpus and matrices and D-6's newer-failure recipes,
  wording rows 15-17, DNS-only lookups, real iPhone/iOS Safari.

## Residual gates — not established by this change

- W1: the rules are in source (DECISION-11); the readings themselves are Ops' tool's. They are endpoint
  samples at two moments, not continuous monitoring, and same-UID actors and in-container changes are
  not detected (Security's stated limit). No Docker authority is added to this checker. Not yet shown:
  a real WebKit control run with a before-reading whose image is the pin and a finalize COUNT
  (H-125-W1-READING-1's measure).
- W2: separate hardening source approval and actual recreation/configuration receipt.
- W3: Security's NEW exact-pin review; actual hosting/confinement and disposal evidence.
- W4: actual event observations; when tripped, the batch stops and the request list goes to Security
  (an operator rule, DECISION-9 (b)), not a generic FAIL.
- Cleanup not confirmed (#338): the receipt, summary.md, controls.json and the live line say so and name
  the service, but W1 admission does not refuse on it yet; the next run's operator enforces DECISION-12's
  recreation from those lines.
- G1–G5: approved constant .invalid network plants, exact expected versus extra destinations,
  independent event witnesses, per-kind caught/MISS/not-exercised and blind spots. DNS-only
  traffic and worker/network-kind coverage are not claimed by source or fake tests.
- QA's exact row/kit mapping and Ops host-wire compatibility remain #125 after source clearance;
  #126's independent wire work is not a prerequisite for this source repair.
- No Project app/build/hosting, Chromium/WebKit control or calibration, runtime clearance,
  browser qualification, model/provider probe or spending route is authorized or performed here.

## Source-stage results

H-P3-SAFETY-1 implemented. The initial post-edit offline stage ran 315 fixed inputs: 314 passed and
one old P3 option-equality assertion failed because S1 deliberately adds serviceWorkers:'block'.
H-P3-SAFETY-3 strengthened that P3 assertion (legacy options still exact/unchanged); the affected S1
stage passed 9/9. The 220 unchanged first_app/shared pure tests passed. The two existing P3 tests
that start HTTP servers were excluded from the manual source-only stage, not modified or claimed run.
All 70 initial new safety inputs passed without a browser, MCP, server or host operation.

Final source review found two additional gaps and recorded before-edit hypotheses: H-P3-SAFETY-4
removed legacy BLOCKED=3 delegation from P3 (ordinary P3 BLOCKED=1; legacy stays 3), and
H-P3-SAFETY-5 distinguished explicit port zero from a default origin port. Thirteen new fixed inputs
plus the affected existing S2 stop/selection controls passed, 28/28. Both hypotheses HIT for their then-current scope. H-P3-SAFETY-6 subsequently supersedes H4's
P3-local BLOCKED=1 mapping: Architecture's amended plan keeps BLOCKED=3 and assigns W4=4,
with five exact live codes and existing sticky control/terminal-event tests retained. The H6 stage
passed 35/36; H7 corrected one remaining conditional-literal 3 in the P3 batch fake assertion to 4
(no source behavior change), and that affected batch stage passed 8/8. Both original misses remain
in their private JUnit artifacts. A runner-only
PTY job-control interruption before test execution was preserved separately (H-P3-SAFETY-2); the
same stage completed after noninteractive stdin, with admission/CPU affinity unchanged.

Exact source/import/fixture/test hashes, original misses, JUnit outcomes, final commit, normal gate
and deployment receipts, and Security's NEW source-review request are bound in Architecture's private
p3-checker-security/129 report. The report is the delivery record; these source tests do not establish
Security approval, runtime disposal/observation coverage, QA mapping or browser qualification.

#125 stages 4b and 4c (tests/test_architecture/test_first_app_p3_admission.py, 67 fixed cases, fakes
only): on the 5b0be339 base 54 failed and 13 passed (all 21 admission cases, and 33 of the 40
malformed-CLOSE variants, including every off-origin one whose log was lost before the shape check).
The first post-edit run: 57 passed, 10 failed; 8 were malformed event logs that still confirmed the
cleanup (read_terminal now turns a malformed log into an incomplete reason) and 2 a test helper that
did not create a nested folder. Then 67/67. Mutations: Chromium admission removed (killed, 1 case),
named recreation ignored (killed, 9), StartedAt later -> later-or-equal (survived at first because the
equal-start case also failed on its W1 start; the case now matches W1 to the W2 container and checks
the reason; killed).

#125 canonical rows (tests/test_architecture/test_first_app_p3_rows.py, fixed observations): every
browser row passes a correct page in each of its engines, and each fault fails at its own judge or is
BLOCKED when the measurement is not good enough (a short hold, no abort, no observation). First run: the
judges raised on a non-object observation; judge() now turns any unreadable observation into BLOCKED.
73/73 after that. Mutations: busy text within 2 s instead of 1 s (killed), the CR-3 abort witness
ignored (killed), the Hebrew item's rtl check dropped (survived at first: the test only flipped the
Arabic item; it now flips each on its own; killed). A separate stage script checks every literal against
QA's spec and Product's FINAL byte for byte (161 checks) and caught all four planted mismatches.

#279, Security #105 fixes (hypotheses H-279-A6, -G5Q, -R1, -G3a, -W4X, -DOCR, written before the code;
record /home/shinelay/architecture-dept/reviews/p3-security-105-fixes/): 25 new fixed cases, fakes and
Node only (A6 18, G5-Q 2, G3-a 4, R-1 1); the six P3/shared test files passed 458/458 in one run, with
no existing test or assertion changed. Bites: the A6 fix disabled (no marker written, markers not read)
failed 17 of its 18 cases (the marker-beside-its-receipt clean case passes either way); G5-Q disabled
failed both of its cases; G3-a and R-1 reverted to the base lines failed theirs (4 and 1). Each was
restored byte for byte (sha256 checked). Served fixture bytes are unchanged.

#280, W1 from two plain container readings (DECISION-11, hypothesis H-125-W1-READING-1; record
/home/shinelay/architecture-dept/reviews/p3-w1-readings/): the record shape is Ops' landed
webkit-reading/1 (agent-tools docs/ops-host-chromium-reading.md, "WebKit readings"), and a live reading
from that tool passes the pre-check. New fixed cases in tests/test_architecture/test_first_app_p3_w1.py
(79, fakes and files only): the pre-check catches 28 record faults and the file faults (wrong sha256,
symlinks, not a regular file, too big, bad JSON); five failing readings leave WebKit NOT RUN with no MCP
call; finalize catches 19 faults (each of id, image, started_at, restart_count and networks differing,
a recreation with the same image, after not later than the finish, before not earlier than the start,
the after-side state, holder and shape rules), a wrong after-hash, a before-reading changed since the
run, and a receipt without a PROVISIONAL W1; it writes one new 0600 record and never overwrites one.
Three new safety cases show the journey opens no WebKit session without a checked before-reading. The
first run of the six P3 test files had 3 failures, all in that new safety test: the existing NOT RUN
verdict answers before "not every row was observed", so the expectation was wrong, not the code; after
the fix 444/444 passed. Bites, one at a time and restored byte for byte (sha256 checked): the pin check
off failed 2 cases, the paused check 4, the holder = id check 3, the after-time check 2.

#338, terminal-cleanup record and unconfirmed cleanup (#298's R1; hypothesis and result in
/home/shinelay/architecture-dept/reviews/p3-r1-terminal-record-338/HYPOTHESIS.md): 17 new fixed cases in
tests/test_architecture/test_first_app_p3_safety.py, fakes and Node only (the carrier-context error runs
the real guard in Node): 5 for the record and the unconfirmed cleanup, 12 for Security's URL finding
(11 fixed texts for without_url_secrets, and a controls run whose CLOSE error carries a credential URL,
checked on the captured stdout and controls.json). On the parent source (628ed017) all 17 failed
(KeyError close_call or cleanup_unconfirmed, AttributeError UNCONFIRMED_RECREATION or
without_url_secrets) and the other 112 passed; at the head 129/129. On the parent, the unconfirmed probe
case wrote "Cleanup: {}." and "Service recreation
required: []." to summary.md, the run-59850933 shape. Each test's written receipt, summary.md and
controls.json, parent against head, after normalizing paths, times and the two module pins: 84 files,
79 byte-identical once only the keys #338 adds are removed (close_call, close_steps, cleanup_unconfirmed,
the guard entries' error_name and error_message); the other 5 are summary.md files whose Cleanup lines
changed because a cleanup was not confirmed, as intended. The success path (confirmed, complete journal,
latch not blocked), the carrier-failure cases (BLOCKED, exit 3) and the fallback recreation cases wrote
identical records.
