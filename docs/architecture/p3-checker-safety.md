# P3 source boundary: S1–S5 (#129)

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
scripts/test_slot.py and taskset -c 0-4,10-14. Record any miss and a new hypothesis before repair.
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
Architecture's #129 amendment (rm-66681532) preserves BLOCKED=3 and assigns unused 4 to W4,
superseding the original literal W4=3 rather than changing an existing failure code.
An empty/unmatched selection and any NOT RUN are incomplete, never qualification success.
Selected-only controls can succeed as a subset, but full_qualification is false unless every named
control is OK. No expected-destination exemptions exist in this source; future network plants
need their own exact-pin source approval and exact-URL/per-kind witnesses.

A caller seeing W4 TRIPPED must stop all further P3 controls/build browser use and use the existing
native queue_blocked hold: lead=security, need/owes naming the unresolved private receipt/run,
source/import/fixture pins, browser image/container/StartedAt pins, and affected scope; name the
related Security task and next checkpoint when known. Send Security a new exact-pin request.
Keep that unresolved receipt and pins in the native task across restart and any later invocation.
Only Security's explicit reply bound to that receipt, pins and scope releases it. No timeout,
restart, earlier GO or new case/CLI invocation releases it. No file grants clearance; no profile,
CLI bypass or automatic resume exists. This invocation-local latch is not cross-process authority.
These tests manufacture no real W4 receipt and request no release of a real hold.

Unconfirmed browser/probe/server disposal is BLOCKED and prevents the next engine/case.
Receipts and exact event observation lists are exclusively created regular 0600 files, without
following a leaf or parent symlink; existing names are refused rather than overwritten.

## Residual gates — not established by this change

- W1: actual fixed-service image identity, exactly one running container, equal full container ID,
  image and StartedAt before/after. No Docker authority is added to this checker.
- W2: separate hardening source approval and actual recreation/configuration receipt.
- W3: Security's NEW exact-pin review; actual hosting/confinement and disposal evidence.
- W4: actual event observations and native Security hold/release when tripped, not a generic FAIL.
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
