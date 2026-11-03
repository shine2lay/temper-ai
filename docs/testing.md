# How temper is tested

And where to look when something is red.

## The short version

| Where | What runs | When |
| --- | --- | --- |
| Your machine, before each commit | ruff · mypy · selected non-heavy Python tests · affected dashboard checks · Postgres instead of SQLite when stored data changed | `git commit` |
| GitHub, on branch pushes and PRs | the selected tests on Python 3.11 **and** 3.12 and the Postgres tier · affected dashboard/browser checks | push, PR |
| GitHub, on every master push | full non-heavy Python suite on both versions and the Postgres tier · dashboard and browser checks | post-land backstop |
| GitHub, nightly at 03:17 UTC | locked full+heavy suite · newest library versions · Python suite three times · browser tests three times | `schedule`, or by hand |
| Your machine, every 10 minutes | reads GitHub's results and DMs you on Slack when they change | a user timer |

All three install from **`uv.lock`**. That is the point of the arrangement:
what passes on your machine passes on GitHub and runs on the server, because
all three have the same versions of everything.

## One version list

Run everything through `uv`:

```bash
uv sync --frozen --extra dev      # exactly uv.lock, nothing newer
uv run pytest tests/ -n auto      # local worker policy, in that environment
uv run python scripts/show_versions.py --check
```

That last line prints what is installed and fails if it is not the lock:

```
python 3.12.3 · sqlmodel 0.0.37 · sqlalchemy 2.0.48 · fastapi 0.135.1 · pytest 9.0.2
(matches uv.lock: 6 packages checked)
```

The pre-commit hook prints the same line before it runs anything, so the
versions used are in the log rather than assumed.

> **Why this exists.** For eight days in September master was red and nobody
> could reproduce it. GitHub installed with `pip install -e .[dev]`, which
> takes the newest of everything (sqlmodel 0.0.47); the hook used whatever
> was in `~/.local` (0.0.31); the server used the lock file (0.0.37). Three
> environments, three answers, and the failing one was the only one no
> developer had. Now there is one list.

## The tiers

### The Python suite

`uv run pytest tests/ -n auto` uses the local worker policy described below.
Each test gets a fresh in-memory SQLite. Omit `-n` for a serial diagnostic.

#### The shared machine pool

The hook and parallel runs started by hand use the same machine pool as
other repositories' land checks, through
[`wt slot`](https://github.com/shine2lay/agent-tools/blob/master/docs/wt-land-queue.md#wt-slot-a-machine-slot-for-any-command-ops-646).
That document owns the pool, worker defaults, bounded wait, fail-open behavior
and nested-slot handling; temper-ai has no separate pool.

Before pytest configures its workers, `tests/conftest.py` calls
`tests/machine_slot.py`. A run requesting `-n` / `--numprocesses` with `auto`,
`logical` or a positive number restarts the same interpreter and arguments
under `wt slot --`. An environment marker (`TEMPER_PYTEST_MACHINE_SLOT`)
prevents another restart. An explicit `-n 8` stays 8, and the caller's
`PYTEST_XDIST_AUTO_NUM_WORKERS` is left alone. The hook uses `-n auto`; its
`PRECOMMIT_PYTEST_WORKERS` override, when set, is exported as
`PYTEST_XDIST_AUTO_NUM_WORKERS` before pytest starts.

Local auto counts consume `PYTEST_XDIST_AUTO_NUM_WORKERS`, then
`WT_CHECK_WORKERS`, then default to **10**. Shared launcher settings still
win (including 6 during rollout); this repo does not activate a new shared
default. CI keeps xdist's original worker policy. Explicit counts, serial
runs, `--pdb` and `--maxprocesses` stay authoritative. See
[local-test-workers.md](local-test-workers.md) for precedence, malformed
inputs, compatibility checks and the Vitest adapter.

Single-process runs (no `-n`, or `-n 0`) start immediately without wrapping.
So do xdist workers (`PYTEST_XDIST_WORKER`), pytest subprocesses inside a test
(`PYTEST_CURRENT_TEST`), CI (`CI` or `GITHUB_ACTIONS`), runs with the restart
marker, and machines without `wt` on PATH. A failed restart prints one line
and continues unwrapped. A hook or chat already inside a machine slot reuses
it through wt, never taking a second slot.

For a longer wait before a commit, wrap it explicitly:

```bash
wt slot --wait 30 -- git commit -m "Describe the change"
```

`TEST_SLOTS_*` settings no longer do anything in this checkout. Old worktrees
keep their own hook until rebased; their live v1 state directory is left alone.

**No `-x`.** Stopping at the first failure meant one red run told you about
one broken test; you fixed it and the next run told you about the next.
Everything that fails, fails visibly, in one go.

#### Waits that follow progress

A machine slot only limits how many suites start at once. It can't slow down
load that starts later, or help a suite that runs without a slot. In #225
(2026-10-30), a full suite that ran without a slot timed out in a Team run's
first parking wait, before installing the invalid config the test was meant
to check. That attempt's CPU allocation was not recorded: its cause is not
proved. Separately, controlled runs at 15 % of one core reproduced the same
phase failure: about 4 CPU-seconds of work took 31–40 s while events kept
arriving. This demonstrates sensitivity to constrained CPU, not the original
run's CPU share or the cause of other Pi-run failures.

The waits in `tests/test_runner/pi_parking` (`wait_parked`, `wait_ended`)
now use observed event progress. A new event restarts the inactivity count
(20 s by default; current explicit callers use 30 s). Normal probes run
about once a second; inactivity expiry checks once more for a late event.
Progress can extend the deadline up to 100 s from the start. Explicit
initial timeouts above 100 s would be retained; no current caller uses one.
These are cooperative polls, not an interruptible wall bound: slow callbacks
can overrun a deadline. A stopped run normally fails about its timeout after
its last observed event, saying "no progress".

### The database tier (Postgres)

SQLite is not what temper runs on. Its time-zone handling, unique
constraints, `ON CONFLICT` and row locking are all different, and a bug in
any of them would have reached the live database untested — which is exactly
what happened with the time-zone bug below.

So the tests that store things also run against a real Postgres:

```bash
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/ -n auto
```

`url` starts the test Postgres if it is not up (port 5455, everything in
RAM, at most 4 GB), waits until it answers and prints its URL. With that variable set, the
tests listed in `tests/pgtier.py` use Postgres and the rest stay on SQLite,
so the whole suite still takes about twenty seconds.

**On Linux it is on the host's network.** With Docker's own engine on Linux
(rootful, not Docker Desktop) the container runs with `--network host`, and
Postgres listens on 127.0.0.1 only, never on the LAN or tailscale; a login
over TCP still needs the password. The tests then reach it over loopback
instead of through Docker's userland proxy (`docker-proxy`), which has to
wake up for every round trip and, on a busy machine, wait for a core each
time. Measured here on 2026-10-19: an idle `SELECT 1` took 33 µs instead of
46 µs at the median, and 196 µs instead of 648 µs at p99. Under load, the run
thread's database wait fell by a quarter in one team-run test and by half in
another. Elsewhere the port is published on 127.0.0.1 through Docker's
bridge, as before. `TEMPER_TEST_PG_NETWORK=bridge` (or `host`) chooses by
hand for a container the script starts, and the URL is the same either way.
A container started by an older script (label `temper.test-pg.version`
below 4) keeps working as it is; it moves over only once it is removed while
idle (`down`, then `url`).

**One container, shared: leave it up.** `temper-test-postgres` serves every
worktree, every chat's pre-commit hook and every run by hand, often at the
same time. Runs keep apart by schema: each xdist worker of each run gets one
of its own (`tier_p<pid>_gw0`, the pid being the run's own pytest process),
truncated before every test and dropped when the worker exits; the schemas of
a run that was killed go when the next run starts. When every run used the
same `tier_gw0`, two runs at once emptied each other's tables (25 failures in
each of two runs, 2026-10-04).

`scripts/test-postgres.sh down` would remove it under everyone, so it refuses
while a run is using it (an open connection, or a schema of a run still
going) and says why; `down --force` removes it anyway. Starting it is safe at
any time: callers take turns on a lock, and a running container is never
replaced.

A long or heavy run can have a container of its own, by name and port:

```bash
export TEMPER_TEST_PG_NAME=temper-test-postgres-mine TEMPER_TEST_PG_PORT=5481
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/ -n auto
scripts/test-postgres.sh down                    # it is yours alone: remove it after
```

**It cannot touch anything real.** `tests/pgtier.py` refuses a URL on port
5433 (where live temper's database is), refuses a database not named
something with `test` in it, and refuses the URL the server itself is
configured with. The tests truncate every table, so this is checked loudly
rather than trusted.

Which tests are in the tier is a list in `tests/pgtier.py` — the inbox,
checkpoints, events, runs, the reconciler, triggers, memory and notify. Add
to it when a new test starts storing something.

### The dashboard

```bash
cd frontend
npx tsc -b          # types
npx vitest run      # local env/shared setting, else 10 workers
npm run build && npm run e2e
                    # the browser tests that need no temper, as GitHub runs them
```

Vitest's local worker precedence is CLI/serial diagnostics, then
`VITEST_MAX_WORKERS`, then `WT_CHECK_WORKERS`, then 10. For one worker use
`--maxWorkers=1` or `--no-file-parallelism`, not 0. CI and all Playwright
configurations (including live-browser serial cases) are unchanged.

No temper is started for the browser tests, here or on GitHub: AGENTS.md
rule 15 allows no copy of Temper but the live one (temper-dev), and a browser
test that starts runs or writes never runs on the live one.

So GitHub's e2e job and the nightly run only the spec files listed in
`frontend/e2e/server-free.txt`: ones that answer every API call themselves. A
test in a listed file that does need a server is tagged `@needs-server` and
left out. They run against the commit's own build, served by
`scripts/e2e_static_server.py`, which answers every `/api` and `/ws` call with
a 503 that says there is no temper, so a test that leans on a server fails
loudly instead of writing to one. (Not `vite preview`: its proxy sends `/api`
to localhost:8420, and on the box that is the live temper.) With none listed,
the job runs no browser tests and its summary says why.

The rest need an address given on purpose: without `TEMPER_E2E_BASE_URL`, a
plain `npx playwright test` stops before any test (`frontend/e2e/requireBaseURL.ts`),
so none of them reaches the live temper by accident.

The other specs in `frontend/e2e/` make their own data on a real temper with
the zero-cost workflows, so they ran against a throwaway server until
2026-10-08 and are not run by GitHub now: `smoke_test` for the runs they look
at; `ci_script_log` and `ci_script_log_timeout` for script agents' live output
and saved logs (made-up output on a timer, a failure, a timeout, a cancel and
a flood past the 10 MB limit; `frontend/e2e/scriptLog.spec.ts`);
`ci_gate_rounds` for approvals and loops that run out of rounds
(`frontend/e2e/gateRounds.spec.ts`; [gates.md](gates.md)). The live dashboard
itself is looked at by temper-ci after every deploy, and an ordinary run's box
environment and the owner's controls (stop and resume, a gate answered through
the API) are tried there on quiet $0 runs ([ci-gate.md](ci-gate.md)). Set `TEMPER_PROOF_DIR` to keep a spec's
screenshots.

### The Pi rehearsal rig (manual)

A team run in real member boxes, with a scripted model in place of the
provider, on its own compose project: `scripts/pi_rehearsal/` (its README
has the steps). It is run by hand, never by the gate. The gate runs only
`tests/test_pi_rehearsal/`, which checks the rig's pure parts with no Docker
and no model.

### Which tests a commit runs

Not every change can reach every test. `scripts/select_tests.py` reads the
rules in `scripts/test-selection.toml` and builds a dependency graph of the
repository (`scripts/dependency_graph.py`) from Python imports, dotted
`importlib` / `monkeypatch` targets, `configs/` workflow and agent references,
and literal paths named in source and tests. `scripts/pytest_fixtures.py`
resolves fixture uses without importing application code:

```bash
python3 scripts/select_tests.py --explain                  # staged diff (or branch vs master)
python3 scripts/select_tests.py --base origin/master --explain
python3 scripts/select_tests.py --files temper_ai/mcp/server.py --explain
```

The pre-commit hook and GitHub's `select` job call the same script:

- **Shared plumbing** (`pyproject.toml`, `uv.lock`, `tests/conftest.py`,
  `tests/pgtier.py`, `tests/machine_slot.py`, `scripts/git-hooks/pre-commit`,
  `.github/workflows/ci.yml`, or the selector itself) and **any path no rule
  names** run the whole Python suite, the dashboard checks and the browser
  tests. An empty or unreadable diff also runs everything.
- **Engine, config, script and test changes** run the tests in the touched
  package (`temper_ai/<pkg>/` → `tests/test_<pkg>/`) plus every test reachable
  through the dependency graph. There are no hub traversal stops. Requested
  fixtures include their prerequisite fixtures; autouse fixtures apply to every
  test in their scope. Collection hooks, top-level conftest imports and other
  import-time expressions also apply to the entire scope. An unused optional
  fixture's body does not apply to tests that never request it. Helpers such as
  `tests/pgtier.py` retain ordinary import edges. Dynamic fixture requests,
  non-constant dynamic imports (`importlib.import_module(var)`, `__import__(var)`,
  `runpy.run_module(var)`, `find_spec(var)`, `spec_from_file_location(...)`) in
  a changed non-test Python file, or Python that cannot be parsed fall back to
  everything, not a missing edge.
- **Top-level Python packages** (a folder at the repository root that holds
  `__init__.py` in the checked tree, such as `p3_source_closure/`): a changed
  `.py` file in one runs every test reachable from it through the dependency
  graph that engine modules go through; unlike an engine module, it adds no
  package test folder. The rule
  (`top-level packages`, with `top-folder-holds = "__init__.py"`) comes last, so
  it only takes paths no other rule names. The package's other files
  (`py.typed`, data) and `.py` files in a root folder without `__init__.py`
  remain unknown paths and run everything, and so does a whole package deleted
  together with its `__init__.py`.
- **Dashboard changes** (`frontend/**`) run the dashboard type check, unit
  tests and browser tests (`e2e`), and skip pytest unless a Python test reads
  one of the changed files.
- **Documentation** (`docs/**`, `README.md`, `.temper/**`) runs only the Python
  tests that read the changed file (`docs/departments.md`, `docs/ci-gate.md`,
  and so on); a doc no test reads skips pytest, the dashboard checks and the
  browser tests.
- **Heavy sweeps** (`@pytest.mark.heavy`: full-suite subprocess mutation checks
  and all-config replays) are left out of the per-commit gate (`-m "not heavy"`)
  and run every night in `nightly.yml` (`full-and-heavy`) on `master`.
- **Every master push** calls the same selector with `--full`, independently
  of its diff. This post-land backstop runs the full non-heavy Python suite,
  dashboard and browser checks. A later master push does not cancel it. The
  nightly additionally includes heavy tests; neither is evidence that a skipped
  test was executed in an earlier branch gate.
- **Selector contract** (`dr-786672016410`): per-commit checks are a fast risk
  filter targeting zero omitted change-caused regressions in the pre-commit
  tier, with conservative full-suite fallback whenever impact cannot be
  narrowed safely; post-land `master` full runs and nightly `full-and-heavy`
  runs remain mandatory backstops that surface and track any escaped failure.

Fixture dependency answers, executed clean/injected-fault miniature repositories
for every rule and dependency mechanism, and CI event routing are tested under
`tests/test_scripts/`.
These are static selection checks, not a claim to have reproduced historical
failures or recovered missing logs.

#### Pure host-contract package

One explicit leaf route exists, not a general source-only exemption. Every
changed path must be inside `p3_host_contracts/` or
`tests/test_p3_host_contracts/`, or exactly `docs/p3-host-contracts.md`.
The selector emits `route host-contracts`; it does not build or read the
application dependency graph for this route. Any mixed change runs **all**
ordinary checks. Empty, unsafe or unknown changes and shared infrastructure
(including this route's scripts, rules, tests and CI) retain full checks.
Renames are examined as deletion plus addition, so both sides count. Symlinks
and submodules are not accepted in the leaf. Missing package or test files
cannot qualify, and pytest's zero-collection exit remains a failure.

The **ordinary pre-commit hook**, with no opt-in flag, keeps shared-CPU
placement, syncs the locked environment, then calls
`scripts/check_host_contracts.py`. That script reclassifies the actual diff,
snapshots tracked supplier blobs from the index (or checked commit) into a
temporary directory and runs real locked ruff, mypy and pytest. Even a
**documentation-only** change checks the entire package and all its tests.
Unstaged and untracked source/fixtures cannot change what it checks.

`scripts/show_versions.py --check --tools` requires each lint/type/test tool
at its locked version, using distribution metadata without application imports.
Ruff checks the package and its tests with the tracked project configuration;
mypy checks the package with missing imports rejected and site packages
excluded. Pytest uses a separate configuration, explicit locked xdist/timeout
plugins, no plugin autoload, no application/root-test conftest and an isolated
import path. Its infrastructure conftest reuses `tests/machine_slot.py` for
the ordinary `-n auto` admission/placement behavior, including nested runs.
The copied admission code is unchanged. It reads host placement policy as
usual; isolation does not bypass machine controls. Supplier-local fixtures
and conftests are included and tested.

CI consumes the same selector's **resolved merge-base** and reclassifies it
for each leaf phase. Existing `lint`, `typecheck`, and both Python test jobs
run real checks; only this exact leaf skips the application Postgres job,
dashboard and browser jobs. A failed/missing selection runs ordinary checks.
Required job names do not change. `--phase` on the runner only splits these
CI jobs; the ordinary hook always runs all three phases.

Integrate routing infrastructure through normal git first. A branch that
contains both an unlanded routing patch and supplier changes is **mixed**
against `origin/master` and must run full CI. An isolated staged commit does
not waive that branch-wide gate. Only when infrastructure is already in the
comparison base can a supplier-only branch qualify for leaf CI. Do not
change hooks, base refs or pass a skip flag to manufacture a pure diff.

This is a source-check boundary, **not a hostile-code sandbox, permission to
read private data, runtime qualification or supplier acceptance**. Checks
still execute reviewed supplier Python as the test user. Synthetic hook tests
prove the route, imports, diagnostics and failure propagation; recording-tool
phase tests prove dispatch only, never a full-suite pass.

## Flaky tests

**A flaky test is a broken test.** It is fixed, never skipped, never deleted,
never given another retry.

Playwright keeps one retry on GitHub so a single commit is not blocked by a
hiccup, but a test that passed only on its retry is *named* in the job
summary, and the nightly runs with no retries at all and treats flakiness as
a failure.

To prove one fixed:

```bash
scripts/e2e-repeat.sh 10       # ten runs, all must be green
```

> **The one that was.** "Compare › compares two runs side by side" failed at
> random for weeks. The comparison table marks a row whose values disagree by
> adding a small "differs" next to the label, and the test asked for a cell
> named exactly `Duration`. Whether two smoke runs take the same tenth of a
> second is a coin toss, so the label was sometimes "Duration" and sometimes
> "Duration differs". The fix was not to loosen the assertion: the label cells
> are now real row headers (`<th scope="row" data-row="Duration">`, which is
> what a comparison table should have had all along), the test holds on to the
> row's name rather than its rendered text, and whether the marker appears is
> pinned by a unit test with numbers that do not move
> (`frontend/src/__tests__/compareView.test.tsx`).

## Time zones

Every datetime temper stores carries UTC. There is one place that makes
them:

```python
from temper_ai.shared.clock import as_utc, utcnow

row.received_at = utcnow()       # not datetime.utcnow(), not datetime.now()
when = as_utc(row.received_at)   # reading one back
```

`datetime.utcnow()` returns a *naive* datetime — the right numbers with no
zone attached. sqlmodel 0.0.4x and up refuse to store one (`Datetime values
must have timezone information`), which is what turned master red; and
SQLite hands a naive one back even when it was stored with a zone, so
comparisons after a round trip silently mean something different.

`ruff` enforces this: `DTZ` is on, so `datetime.utcnow()` and a bare
`datetime.now()` fail the check.

## When something is red

**You get a Slack DM** from temper's bot when master's checks go red, when
they are green again, and when the nightly finds something. Each is sent
once. It comes from a timer on the box (`scripts/ci_watch.py`), not from
GitHub, so no token of ours lives in GitHub's secrets.

```bash
python3 scripts/ci_watch.py --test      # send a sample DM
python3 scripts/ci_watch.py --dry-run   # print what it would send
python3 scripts/ci_watch.py --show      # what it knows right now
scripts/systemd/install.sh --status     # is the timer running
journalctl --user -u temper-ci-watch -n 50
```

### Reading a red run

1. **The job summary first.** Every test job writes a table of what failed
   and the line that failed it, above the log. You should not have to open
   the log to learn which tests are broken.
2. **Both Pythons run to the end.** The matrix does not fail fast, so a
   break on 3.11 no longer cancels 3.12 — if one is green and the other is
   not, that is the answer.
3. **`junit-*.xml` artifacts** hold the same thing in full, for 7 days.
4. **Browser failures** upload `frontend/test-results/` with a screenshot
   and a trace of each failure, plus the server's own log.

### Reproducing it here

```bash
uv sync --frozen --extra dev                      # the same versions GitHub had
uv run pytest tests/ --timeout=120 -n auto        # keep local worker policy
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/ -n auto
```

If it passes here and fails there, the difference is the environment, and
`show_versions.py` in both logs is where to start.

### The nightly

It answers two questions the per-commit checks cannot: *would temper still
work if its libraries were upgraded* (information only — nothing here
changes what is pinned), and *which tests are flaky* (the suite three times,
in a different order each time). Start it by hand with:

```bash
gh workflow run Nightly --repo shine2lay/temper-ai
```

## Installing the watcher

```bash
scripts/systemd/install.sh
python3 scripts/ci_watch.py --test
```

It reads the Slack token from `~/temper-ai/.env` (`SLACK_BOT_TOKEN`) and
DMs the owner — the same bot and the same DM that temper-deploy's notices
use.
