# Product runs on the shared Temper server

Product uses the existing Studio config APIs and `POST /api/runs`. Direct `temper run`
creates private execution history and is **not** a visibility fallback. Past CLI archives
and `data/dev.db` remain local-only; no events have been injected into the server.

## Proven path (queue 14, 2026-10-03)

- Workflow: [Product visibility candidate](https://temper-dev.wai2shine.com/app/studio/product_q14_smoke_20261003_r3_product_visibility_smoke_8a8a496ea3).
- Run: [658ef587-0c0c-4be2-b46c-de657464d514](https://temper-dev.wai2shine.com/app/workflow/658ef587-0c0c-4be2-b46c-de657464d514).
- `prepare`, `write`, `check` all completed; zero model calls/tokens, $0.00 cost.
- Worker read staged assets, created deterministic `visibility.json`, then read it back in
  `/home/shinelay/temper-ai/workspaces/product/visibility-14`. Artifact SHA-256:
  `4f4c55db5554777c37e27884a49370e72e13fad99ac008e9d5dae07f0c2487d6`.
- Both namespaced config hashes still matched after real worker startup/import. Server search,
  run list and status returned the exact name/ID. HTTP links use the actual `/app` UI base;
  the former assumed hostname/root links returned 404 and are not valid owner links.
- Evidence, fixed bar, failed attempts and before-helper snapshots:
  `/home/shinelay/product-autopilot/results/visibility-14/`.

This proves plumbing, not research quality or a paid/model run. #20 and #21 still need their
own real outputs, evidence review and unchanged bars. No paused screening files were modified.

## Launch an existing Product workflow

Use a fresh job name and a dedicated shared workspace. Keep queue ownership and **one Product
workflow at a time**, including weekly scans. Research inputs are JSON, not shell commands.

```sh
python3 ~/product-autopilot/server.py stage ~/product-autopilot/inputs/my-assets \
  --workspace ~/temper-ai/workspaces/product/my-job --relative _assets
~/product-autopilot/start.sh my-job signal_harvest \
  --workspace ~/temper-ai/workspaces/product/my-job \
  --inputs ~/product-autopilot/inputs/my-job.json
```

For a workflow with no input assets, create its dedicated workspace first. Any absolute input
`*_dir`/`*_path` must refer inside that workspace. Relative published `state/<area>/...` outputs
now live under this workspace, **not** the old host checkout's `state/` folder. Never collect old
files as if the new server run produced them. Inspect the workflow's actual output paths first.

`server.py` loads `~/temper-ai/configs/product/bin/server_run.py` after normal landing/deploy.
For development of this helper itself, `PRODUCT_SERVER_CODE=/absolute/own-worktree/.../server_run.py`
selects that code only; it still submits to the same server and is not private execution.
API defaults to `http://127.0.0.1:8420`; UI defaults to `https://temper-dev.wai2shine.com/app`.
`PRODUCT_TEMPER_API`/`PRODUCT_TEMPER_UI` may explicitly select a deployment, never credentials.

## Launch a local candidate, including #20/#21

1. Make changes only in your own `wt new` worktree. Use a distinct `_next` or local candidate
   name. Assemble a directory containing the candidate workflow and **every transitively
   referenced Product agent/stage** (unchanged dependencies may be included). Do not include
   duplicates of the same kind/name. The helper refuses missing refs instead of fetching or
   modifying another owner's config. Dynamic templates must be explicitly expanded first.
2. Register the directory with a fresh Product namespace and a fresh receipt:

```sh
python3 ~/product-autopilot/server.py register /absolute/own-worktree/configs \
  scan_serving_trial --namespace product_screen_trial10 --receipt ~/product-autopilot/results/trial10-registration.json
```

Use the `workflow` value from that receipt when launching, not its original local name.
The helper clones only the structural reference closure; prompts, node names and input/output
maps remain unchanged. Agent names implicit in stages get explicit original node names, so
output pointers keep working. New names include the namespace and a content suffix. Both
server and deployed-tree collisions are refused; config POSTs are not retried on uncertainty.
Agents/stages register before the workflow, and exact GET hashes are verified.

3. Stage candidate script/checker files, frozen source/baseline data and any assets using
   `server.py stage SOURCE --workspace SHARED_RUN_DIR --relative DEST`. Copying checks hashes,
   never overwrites a destination, rejects credential files/symlinks, and does not edit its
   source. Update the run's input path values to these staged copies. Do not point into a
   private worktree or modify #9's frozen originals. Referenced tracked `/app/configs/...`
   scripts must already be landed before relying on that path; local scripts belong in assets.
4. Submit with `--receipt RECEIPT`, and retain that receipt with the outputs:

```sh
~/product-autopilot/start.sh screen-trial10 REGISTERED_WORKFLOW \
  --workspace ~/temper-ai/workspaces/product/screen-trial10 \
  --inputs ~/product-autopilot/inputs/screen-trial10.json \
  --receipt ~/product-autopilot/results/trial10-registration.json
```

Workers import deployed configs into the shared store at startup. A live-name upsert can be
reverted by that import; a namespaced candidate absent from disk survives. This is why pushing
over a live definition is neither supported by this Product helper nor sufficient trial proof.
Keep the registered candidates needed to inspect past runs; do not delete their definitions
or claim that deleting a private trial folder removed server history.

## Workspace permissions

The watcher is UID 1000, but current Docker runs clone `temper-ai-server-1` and execute as
UID 999. A host-owned mode-775 workspace is readable but not writable by that run. The helper
sets a **named-user ACL on the dedicated Product workspace**, with defaults granting UID 999
and the host owner access to new output directories. Staged assets receive read/traverse access.
No world-writable mode, service user/default change or infrastructure restart is used.
`setfacl` is a local helper prerequisite. `PRODUCT_TEMPER_WORKER_UID` is only for an explicitly
verified changed runtime identity; re-prove the smoke before relying on a new deployment.

## Quota, fences, completion and collection

- Research launch checks the existing subscription pool and fails closed if unreadable/exhausted.
  Accounts/tokens are handled by the server's configured providers; caller account pinning and
  secrets in run inputs are forbidden. Do not silently switch to `with_account.py` or local CLI.
- `--non-model` is only for graphs proved to contain explicit script agents and no dynamic
  nodes, agent overrides or gates. It is not a research quota escape hatch.
- The helper serializes submissions, checks local unresolved receipts, active Product units and
  shared pending/queued/running/waiting Product runs. Used names stay used after collection.
- `runs/NAME.job.json` is persisted/fsynced **before the single POST**. An ambiguous response
  remains `uncertain-submit`; no automatic replay or collection is allowed. Reconcile the
  exact server identity with the owner/application state before any new submission. There is
  intentionally no automatic “assume no run” or “start again” command.
- A confirmed ID is persisted before starting the detached systemd status monitor. If starting
  that monitor fails, the server run still exists. Resume monitoring, never submit again:
  `python3 ~/product-autopilot/server.py resume-monitor NAME`.
- The monitor reads `/api/workflows/ID` every 15 seconds. It logs only status/cost metadata,
  including waits; HTTP/read errors and unknown states retain the fence without writing `.done`.
  Completed/failed/cancelled states alone get terminal receipts, server cost and actual UI links.
  A lost monitor is not a dead remote run. `monitor NAME --once` is a single read (exit 75 means
  pending/running/waiting, not completion). `refresh-links NAME` can correct helper link metadata
  after verifying pages; it does not alter execution IDs or server events.
- The task owner inspects actual output files, source evidence and the pre-written bar before
  acceptance, then runs `python3 ~/product-autopilot/digest.py collect NAME`. Unresolved server
  jobs cannot be collected. Shared receipts and safe logs move intact into `runs/collected/`.
  Old CLI jobs are explicitly labelled local-only by the digest.

Weekly `~/product-scan-cadence/run_weekly_scan.sh` now calls `weekly_scan.py`, with the same
scheduler definition. It submits one shared run, waits for its single monitor unit, snapshots
**that run's** workspace outputs, and includes server links/cost in the digest. `SKIP_SCAN=1`
is an explicitly local-only offline digest, never a server run. It refuses existing snapshots.
#17 owns supplying the idea-register leave-out inputs; this plumbing change does not solve it.

After a new snapshot and its digest, the wrapper also starts the early tech and serving screen
(`scan_serving`, product PLAN.md step 2c) on that snapshot and returns without waiting: the
scheduler stops a command after 30 minutes and the screen takes about an hour. It stages the
snapshot's five files and `configs/agents/scan_serving_assets/{check_serving.py,fixtures.json,cite.py}`
into a fresh `weekly-serving-<date>` workspace, launches through the same one-run-at-a-time
helper and notes the run link in the daily log. A refused start leaves the scan snapshot as it
is and exits 1; `SKIP_SERVING=1` skips the screen. The Product autopilot collects and reviews
the screen run like any other (in that workspace: the re-ranked `state/scan/shortlist.md`,
`serving.json`, `independent-audit.md` and the reviewer's `serving-grade.md`). A hand start uses
the same three inputs; `retain_sources` (default false) is only for replays with an exact
retained-page registry.

## Shape a first version (`shape_mvp`)

`shape_mvp` turns one evidenced opportunity into a bounded first-version pitch (Shape Up:
problem, appetite, solution, rabbit holes, no-gos) with checkable success criteria and a
verification plan, keeping every open assumption and prerequisite. Its result is input to the
owner's betting table: not an approval to build, not a market choice, not a promise to anyone.

Input: one `shape_mvp.opportunity/1` JSON; the contract and an example are in
`configs/agents/shape_mvp_assets/contract.md`. It needs the buyer, the job, quoted evidence
(each item with its kind, the party behind it and its source), the open unknowns (fatal or
not), the appetite (`time_weeks` x `builders`, `source` `owner` or `test_fixture`), the
constraints (each with a source) and the upstream status (`open`, `parked` or `killed`, with the
decision's source). A proposed solution and owner values (target price, success bar) are
optional. Never fill in a missing owner value: leave it out and the run carries it as an
owner-input gap. Only the owner sets an appetite with `source: owner`.

```sh
JOB=shape-my-idea
mkdir ~/temper-ai/workspaces/product/$JOB
python3 ~/product-autopilot/server.py stage ~/temper-ai/configs/agents/shape_mvp_assets \
  --workspace ~/temper-ai/workspaces/product/$JOB --relative _assets
python3 ~/product-autopilot/server.py stage ~/product-autopilot/inputs/$JOB-opportunity.json \
  --workspace ~/temper-ai/workspaces/product/$JOB --relative _case/opportunity.json
~/product-autopilot/start.sh $JOB shape_mvp --workspace ~/temper-ai/workspaces/product/$JOB \
  --inputs ~/product-autopilot/inputs/$JOB.json
```

The inputs file is `{"opportunity_path": "<workspace>/_case/opportunity.json", "assets_dir":
"<workspace>/_assets"}` with the workspace's absolute path. Results land in the workspace's
`state/shape/`: `RESULT.md` (final status, the pitch in brief, why, what would unblock it, owner
inputs missing from the input and owner decisions the pitch raises), `pitch.md` (the pitch,
appetite before solution, every test-fixture value labelled), `pitch.json`, `critique.md`,
`check.json`, `grade.md` and `result.json`.

The verification plan runs riskiest first, then cheapest: each fatal assumption gets a free desk
step that can end it on its own within the first steps (the checker enforces the window), and the
decisive contact, paid or patient-data step follows with the owner's approval. A pass or kill
rule that rests on a stand-in figure says what the stand-in leaves out and has a test measure the
buyer's real figure.

The final status is the most conservative of setup, model, check and grade. `blocked`: a
critical input is missing, the idea was killed upstream and not reopened, the evidence does not
show the problem for the buyer, or no version of the core job fits the appetite; it says what
would unblock it. A setup block calls no model and costs nothing. `revise`: the checker or the
grader found a defect, or a step left no usable output (usage-limit text, say): fix the input or
rerun. `shaped`: every structural check and the fixed grader passed. Read the pitch and the
evidence it cites before taking it to the owner; a pass is not proof.

Regression benchmark: `tests/test_shape_mvp/benchmark/` holds seven fixed cases (`build.py
OUTDIR` writes them; `expected.json` says what each must produce and is never staged into a
run; `score.py CASE=WORKSPACE` scores a finished run). A changed candidate reruns all seven
through a namespaced registration; the bar, scores, costs and manual reviews of the first
version are in `~/product-autopilot/results/2026-10-03-shape-11/` (`REPORT.md`).

## Grade a signal report (`signal_grade`)

`signal_grade` grades one finished `signal_harvest` report for soundness against its own lens
files, not whether the market is good: a weak idea in a sound report passes. A script recomputes
every cell, total, overall confidence and the ranking with the synthesizer's formula, checks the
shortlist's candidates and required players, and traces figures, quotes and URLs to the lens
files; a reviewer (no web) resolves what the script could not and checks attribution, blocked
sources and honest unknowns, scope (buyer, job, population, price) and exact versus adjacent or
bundled competitors; a finding counts only when its passages are verbatim in the files. The
result is `pass`, `revise` or `unknown` per criterion Q1-Q6 and overall, in
`state/signal_grade/quality.md` and `quality.json`. It never rescores and never changes the report.

`signal_harvest` runs the same three steps after its synthesizer (outputs `quality_status`,
`quality_path`, `quality_criteria`; the research outputs are unchanged). To grade an older
report, stage it as `_case/` (`shortlist.txt`, `signal_scorecard.md`, `signal/<lens>.md`):

```sh
JOB=grade-my-report
mkdir ~/temper-ai/workspaces/product/$JOB
python3 ~/product-autopilot/server.py stage /path/to/report-folder \
  --workspace ~/temper-ai/workspaces/product/$JOB --relative _case
~/product-autopilot/start.sh $JOB signal_grade --workspace ~/temper-ai/workspaces/product/$JOB \
  --inputs ~/product-autopilot/inputs/$JOB.json
```

The inputs file is `{"report": "<workspace>/_case", "shortlist_path":
"<workspace>/_case/shortlist.txt"}`; a candidate run also stages its own
`configs/agents/signal_grade_assets` as `_assets` and passes `"assets_dir": "<workspace>/_assets"`
(`quality_assets_dir` for `signal_harvest`). A run costs about $1-2 for the review; the script
steps cost nothing.

Regression benchmark: `tests/test_signal_grade/benchmark/` holds nine fixed cases built from five
retained reports (sound and uncertain controls, labelled mutants, and the travel report's known
defects); `score.py CASE=WORKSPACE` scores a finished run against `expected.json`, which is never
staged into a run. A changed grader reruns all nine; the bar and calibration are in
`~/product-autopilot/results/2026-10-04-signal-grade-12/` (`REPORT.md`).

## Measure fit and revenue (`pmf_evidence`)

`pmf_evidence` measures one product's product-market-fit indicators from its own exports and
reports each apart, with its numerator, denominator and observation limits: the survey's
very-disappointed share among eligible respondents (bar fixed at 40%), retention by cohort and
period (only fully observed periods count; a user not yet observed for a period leaves its
denominator, never counted as lost), customer accounts that kept a payment of at least the target
price after refunds, and net revenue (gross receipts minus refunds minus payment fees; promises
are never money). The verdict is `fit_indicators_met` only when survey, retention and payment are
all met, else `fit_not_shown`: the survey alone never shows product-market fit, and even
`fit_indicators_met` is a measurement on the data given, not a fit claim. A model then writes an
interpretation and next-test proposals, and a script checks every statement against the numbered
facts the kit computed (no untraced number, no fit claim, no share said to hold over periods where
it differs, owner approval for contact, surveys or spend). It chooses no market, price or target
and contacts no one.

Inputs: a `pmf_evidence.params/1` JSON and a folder holding four CSV exports (`users.csv`,
`activity.csv`, `survey.csv`, `payments.csv`). Blank templates are in
`configs/agents/pmf_evidence_assets/templates/`; `data_dictionary.md` next to them gives every
parameter, column and rule (eligibility, censoring, duplicates, refunds, division by zero).
Every product-specific value is required, with no default: buyer, user and customer-account units,
the core value event, the last day the exports cover, the currency, survey eligibility and minimum
respondents, the retention period and adequacy and flatness settings, the target price and its
unit, the minimum paying accounts, the revenue target and horizon, the rejected-row limit, and
`data_label` (`synthetic` or `real`). Fit the retention period to the product's rhythm: 7 days for
weekly use, 91 for a few uses a year. Never fill in a missing value: a missing, misspelt or invalid
parameter, file or column blocks the run at setup, one problem per line, with no model call and
no cost. `survey_template.md` is the survey to send; sending it, or contacting anyone, needs the
owner's approval.

```sh
JOB=fit-my-product
mkdir ~/temper-ai/workspaces/product/$JOB
python3 ~/product-autopilot/server.py stage /path/to/exports-and-params \
  --workspace ~/temper-ai/workspaces/product/$JOB --relative _case
~/product-autopilot/start.sh $JOB pmf_evidence --workspace ~/temper-ai/workspaces/product/$JOB \
  --inputs ~/product-autopilot/inputs/$JOB.json
```

The inputs file is `{"params_path": "<workspace>/_case/params.json", "data_dir":
"<workspace>/_case"}` with the workspace's absolute path; a candidate run also stages its own
`configs/agents/pmf_evidence_assets` as `_assets` and passes `"assets_dir": "<workspace>/_assets"`.
Results land in the workspace's `state/pmf/`: `REPORT.md` (verdict, indicator table, survey,
retention curve and retention by cohort and period, payment and revenue kept apart, data quality, the checked
interpretation, next tests and the numbered facts), `metrics.json`, `facts.json`, `rejected.csv`
(every rejected row with its code), `interpretation.json`, `check.json` and `result.json`.

The final status is `blocked` (setup refused the input: nothing measured, no model), `revise` (the
check found a defect or a step left no usable output: the measurements stay, the interpretation is
withheld) or `reported`. Read the report and its facts before taking it to the owner. A run costs
about $0.25 for the interpretation; the script steps cost nothing.

Regression benchmark: `tests/test_pmf_evidence/benchmark/` holds nine labelled synthetic cases
(`construct.py OUTDIR` writes them; `expected.json` holds the expected metrics and is never staged
into a run; `independent.py` is a separately written second calculation; `score.py
CASE=WORKSPACE` scores a finished run). A changed kit reruns all nine; the bar, runs, costs and
reviews of the first version are in `~/product-autopilot/results/2026-10-04-pmf-kit-13/`
(`REPORT.md`).

## Checks

Run Product helper checks once after revisions:

```sh
python3 -m unittest discover -s configs/product/bin/tests -v
python3 ~/product-autopilot/tests/check_digest.py
uv run pytest tests/test_scan_serving -q
uv run pytest tests/test_shape_mvp -q
uv run pytest tests/test_signal_grade -q
uv run pytest tests/test_pmf_evidence -q
```

These use fake status/config APIs, not model request fixtures or third-party services. New
configs/helpers are Product-owned in `docs/departments.md`. Land through `wt land`; automatic
Temper CI deployment is required. Do not manually restart services.
