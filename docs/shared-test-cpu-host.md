# Shared test CPU: temper-ai's host entry

This machine runs every test job inside one shared test-CPU allowance: a single
systemd slice whose quota all test jobs share, set by Ops' `test-cpu` launcher
([agent-tools `docs/test-cpu-contract.md`](https://github.com/shine2lay/agent-tools/blob/master/docs/test-cpu-contract.md)).
This page says how temper-ai's own test commands get into it: the pre-commit
hook and pytest runs started by hand. Test containers and the test Postgres
are [docs/shared-test-cpu-containers.md](shared-test-cpu-containers.md);
`wt land`'s checks and `wt slot` are placed by wt itself.

Two separate things happen to a run:

- **Placement**: whether its processes count against the shared test CPU.
  Only the kernel decides it, by asking the launcher.
- **Admission**: whether a parallel run gets one of wt's machine slots. That is
  the pool described in [docs/testing.md](testing.md#the-shared-machine-pool),
  unchanged.

## Today: no policy, nothing changes

The policy is not installed on this machine yet. With no policy, or with an
installed but inactive one, every command runs exactly as
[docs/testing.md](testing.md#the-shared-machine-pool) describes: parallel runs
go through `wt slot`, everything else starts directly. Turning the policy on is
a separate step on the host (Ops); nothing in this repository switches it on
or off.

## The host's answer

`tests/machine_slot.py` asks once per run, from two fixed paths:

- launcher `/usr/local/libexec/test-cpu/bin/test-cpu`
- policy `/etc/agent-tools/test-cpu.json`

| What it finds | Answer |
|---|---|
| neither path exists, below real folders it can search | inactive |
| launcher says mode `absent` or `inactive` | inactive |
| launcher says `enabled`, `inside: true`, exit 0 | inside |
| launcher says `enabled`, `inside: false`, exit 1 | outside |
| a policy without its launcher; a file, symlink or unsearchable folder where a folder should be; a launcher that isn't executable, hangs past 60 s, or answers anything else | can't be known: stop with 125 |

The paths are fixed on purpose: no environment variable moves them, so none
can switch placement off.

## The pre-commit hook

The very first thing `scripts/git-hooks/pre-commit` does, before `git
rev-parse`, docs, `uv sync`, the version check, ruff, mypy, Postgres, test
selection, pytest or the dashboard checks, is ask for that answer:

- **inactive or inside** (a `wt land` check, an outer entry, a nested hook):
  the hook carries on where it is.
- **outside**: it prints `Entering the shared test CPU...` and replaces
  itself with `test-cpu exec --quiet -- bash <hook>`, so the same hook, with
  the same arguments, runs again from the top inside the slice. Every phase and
  every process it starts runs inside.
- **can't be known or made**: it prints the reason and `Can't enter the shared
  test CPU (above). Commit aborted.`, and exits 125 before any phase. A refusal
  by the launcher itself prints the launcher's reason and exits 125.

Every phase, its conditions, `PRECOMMIT_PYTEST_WORKERS`, `--timeout=120` and
its failure messages are the same as before; only where they run changes.

## pytest started by hand

`tests/conftest.py` calls `enter_machine_slot` from `pytest_configure`, before
collection and before any xdist worker starts:

| Host | Run | What happens |
|---|---|---|
| inactive | any | exactly as before (docs/testing.md) |
| inside | parallel, unmarked | restarts under `wt slot` for a machine slot; wt runs it where it is |
| inside | serial, or marked | runs where it is |
| outside | parallel, unmarked | restarts under `wt slot`, which places and admits it |
| outside | serial, or marked | restarts under `test-cpu exec --quiet` |
| inside or outside | parallel, `wt` not on PATH | stops with 125: put wt on PATH or run without `-n` |
| any but inactive | a restart that can't start | stops with 125, environment put back |

"Marked" means any of `CI`, `GITHUB_ACTIONS`, `PYTEST_CURRENT_TEST`,
`PYTEST_XDIST_WORKER` or `TEMPER_PYTEST_MACHINE_SLOT` is set, even empty. On an
enabled host a marker only skips the machine slot, never placement: `CI=1
pytest` on this machine is still placed. GitHub's runners have no policy, so
their runs are unchanged.

xdist workers are never restarted (`config.workerinput`): their controller
already placed itself, and a worker that restarted would cut its channel to it.

### Nesting and loops

- **Placement** of a nested run (a test that starts pytest or the hook, even
  under `env -i`) is decided by the kernel, not by what the environment
  carries: inside a placed run, the launcher answers inside, so it is never
  placed twice.
- **Machine slots** are wt's: `wt slot` finds the slot an ancestor holds and
  runs without taking another, so a nested run never waits for its own slot.
- **Loop guard**: a restart records `TEMPER_TEST_CPU_RESTART=<pid>:<start
  time>` of the process that restarted. If the restarted run still comes back
  outside while that process is one of its ancestors, it stops with 125
  instead of restarting again. A leftover record from an unrelated process is
  ignored.

125 always means the run couldn't be placed; it is never a test result.

## What runs before the entry

The entry can only place what starts after it. Honestly, that is:

- **Hook**: the `bash` that runs the hook, and one
  `python3 tests/machine_slot.py placement` (standard library only, no temper
  import) with its launcher query. Everything after runs inside.
- **pytest**: the interpreter, pytest's own start-up and plugins (xdist,
  timeout, asyncio, pytest-benchmark, which runs `git rev-parse --git-dir`
  while its options load) and the root conftest's imports (`temper_ai.database`,
  `temper_ai.tools.executor`, `tests.pgtier`) run outside, then run again
  inside after the restart. Collection, fixtures, tests, xdist workers and
  everything they start come after the entry.
- **Not entered at all**: anything that never loads `tests/conftest.py`:
  `--noconftest`, a Python script or `python -c` that imports temper or starts
  tests itself, and the dashboard's `tsc`/`vitest` run outside the hook.

For those, or to keep start-up inside too, start the command inside yourself:

```bash
# any command, placed
/usr/local/libexec/test-cpu/bin/test-cpu exec -- uv run pytest tests/test_x.py
# a parallel run: a machine slot and placement in one
wt slot -- uv run pytest tests/ -n auto
# from this repository, with the loop guard
python3 tests/machine_slot.py enter -- uv run python scripts/some_check.py
```

The conftest then finds itself inside (and in a slot) and carries on.

## Checked by, and what isn't proven

`tests/test_shared_test_cpu_entry.py` holds the fixed cases: the host's
answer, the conftest entry, the whole hook and real pytest runs against a fake
launcher whose slice is real process ancestry (so clearing the environment
can't fake "inside"), and a nested run through the real `wt` in a scratch pool
of one slot. `tests/test_machine_slot.py` holds the inactive answers.

Placement by the real launcher and kernel is not exercised here: with no
policy installed, that proof belongs to the host's setup (Ops).

To undo: revert this change. The machine-slot entry described in
docs/testing.md stays.
