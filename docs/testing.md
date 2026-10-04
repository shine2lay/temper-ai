# How temper is tested

And where to look when something is red.

## The short version

| Where | What runs | When |
| --- | --- | --- |
| Your machine, before each commit | ruff · mypy · the whole Python suite · the dashboard's checks (when it changed) · the Postgres tier (when stored data changed) | `git commit` |
| GitHub, on every push and PR | the same, on Python 3.11 **and** 3.12, plus the Postgres tier and the browser tests | push |
| GitHub, nightly at 03:17 UTC | the newest library versions · the Python suite three times · the browser tests three times | `schedule`, or by hand |
| Your machine, every 10 minutes | reads GitHub's results and DMs you on Slack when they change | a user timer |

All three install from **`uv.lock`**. That is the point of the arrangement:
what passes on your machine passes on GitHub and runs on the server, because
all three have the same versions of everything.

## One version list

Run everything through `uv`:

```bash
uv sync --frozen --extra dev      # exactly uv.lock, nothing newer
uv run pytest tests/              # in that environment
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

`uv run pytest tests/` — about 3,500 tests in roughly 20 seconds at `-n 8`.
Each test gets a fresh in-memory SQLite.

**No `-x`.** Stopping at the first failure meant one red run told you about
one broken test; you fixed it and the next run told you about the next.
Everything that fails, fails visibly, in one go.

### The database tier (Postgres)

SQLite is not what temper runs on. Its time-zone handling, unique
constraints, `ON CONFLICT` and row locking are all different, and a bug in
any of them would have reached the live database untested — which is exactly
what happened with the time-zone bug below.

So the tests that store things also run against a real Postgres:

```bash
scripts/test-postgres.sh up                      # a throwaway, port 5455, in RAM
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/ -n 8
scripts/test-postgres.sh down
```

With that variable set, the tests listed in `tests/pgtier.py` use Postgres
and the rest stay on SQLite, so the whole suite still takes about twenty
seconds. Each xdist worker gets a schema of its own, truncated before every
test.

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
npx vitest run      # unit tests
npx playwright test # the browser tests, against a running server
```

The browser tests need a server with the built dashboard:

```bash
cd frontend && npm run build
TEMPER_DATABASE_URL=sqlite:///e2e.db uv run temper serve --port 8420
cd frontend && TEMPER_E2E_BASE_URL=http://127.0.0.1:8420 npx playwright test
```

They make their own data with the zero-cost `smoke_test` workflow, so no API
key is needed. Script agents' live output and saved logs are checked the
same way, with the zero-cost `ci_script_log` and `ci_script_log_timeout`
workflows (made-up output on a timer, a failure, a timeout, a cancel and a
flood past the 10 MB limit; `frontend/e2e/scriptLog.spec.ts`). Approvals and
loops that run out of rounds use the zero-cost `ci_gate_rounds`
(`frontend/e2e/gateRounds.spec.ts`; [gates.md](gates.md)). Set
`TEMPER_PROOF_DIR` to keep its screenshots.

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
uv run pytest tests/ --timeout=120 -n 8           # the same command
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/ -n 8
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
