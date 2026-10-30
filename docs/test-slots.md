# The test phase waits for room

`git commit` in temper-ai runs the whole Python suite, and so does every land,
because `wt land` runs the same hook (`scripts/git-hooks/pre-commit`) as
temper-ai's check. The suite no longer starts on a machine that has no room for
it. `scripts/test_slot.py` starts it, and only when enough cores are free,
with as many xdist workers as there are free cores (8 at most, 4 at least),
and never more than 3 suites at once across the machine.

## Why

The hook used to start 8 workers however busy the machine was, and nothing
capped how many suites ran at once. On 2026-10-19 land 31-a6d875 failed: two
tests in `tests/test_runner/pi_parking/test_team_api.py` gave up on a Team run
after their 20 s wait, with a load of 23-32 on 20 cores. Both pass alone in
15 s. Earlier that evening two temper-ai hooks had run their suites at the same
time as two pi-web-ui test runs, with 1-8% of the CPU idle. The land failed
because of the machine, not the change. Architecture's review ruled that the fix
belongs in the gate, not in the tests (Systems #18).

## What it does

1. **At most 3 at once.** Each running suite holds one of 3 slots. A slot is a
   lock on a file. The lock goes away the moment its holder exits or is killed,
   and nothing the suite starts can keep it.
2. **One admission at a time.** A suite waits its turn, takes a free slot, then
   measures the free cores: idle time over 3 s on the cores it may use, minus 2
   kept for everything else. Workers = whole free cores, at most `--max-workers`. It
   starts when that is at least `--min-workers`, and otherwise measures again
   every 15 s.
3. **A 30 s ramp.** The suite just started keeps the turn for 30 s (or until it
   ends), so the next one measures after its workers have taken their cores.
   Two suites never count the same free cores.
4. **Never stuck.** After 20 minutes it runs anyway, with the minimum workers,
   and says so. If the tests then fail, the last line says they ran on a busy
   machine.
5. **Never in the way.** A fault of its own (no `/proc/stat`, a slot directory
   it can't use, a lock error, a bad setting) is reported and logged, and the
   tests run anyway without waiting. It never blocks a commit because of its
   own fault.

It runs the tests as a child and returns their exit code. Ctrl-C stops them
too. Only the pytest call is wrapped: `uv sync`, ruff, mypy and the dashboard's
checks run as before.

## What you see

On a machine with room, one extra line, about 3 s in:

```
test-slot: admitted 'temper-ai pytest' with 8 workers: free cores 14.6 of 20 (reserve 2), slot 0 of 3, after 0m03s
```

On a busy one, a line when the wait begins and then one a minute (they show
live: the hook sends them to stderr, past its `tail -40`):

```
test-slot: waiting for room (1m03s so far): free cores 1.2 of 20 (reserve 2, need 4); slots 2/3 taken: [0] pid 41322 'temper-ai pytest', 8 workers since 22:10:05, in /home/shinelay/temper-ai-x; [1] this phase, waiting for room since 22:11:40, in /home/shinelay/temper-ai-y
```

`waiting for a slot` means all 3 slots are taken. `waiting in line` means
another suite is being admitted or is in its ramp. After 20 minutes:

```
test-slot: WARNING: still no room after 20m00s (free cores 1.5 of 20, reserve 2, need 4). Running ANYWAY with 4 workers on a busy machine: a timing failure in this run may be the machine, not the change.
```

A land holds the land line while its check waits. That is the point: it waits
for room instead of failing for the lack of it.

## Who holds the slots

```bash
python3 scripts/test_slot.py status          # or --json
```

```
test slots in /run/user/1000/test-slots (cap 3)
  slot 0: pid 41322, temper-ai pytest, running 8 workers since 2026-10-19T22:10:05-07:00, in /home/shinelay/temper-ai-x
  slot 1: free
  slot 2: free
being admitted: nobody
free cores now: 9.4 of 20 (idle 11.4, reserve 2)
```

It changes nothing: it reads the lock files and `/proc/locks`, and measures for
3 s.

## Settings

All are environment variables; the hook passes them through.

| Variable | Default | What it does |
| --- | --- | --- |
| `TEST_SLOTS_MAX` | 3 | Suites at once. `0` turns admission off: the tests run at once with the most workers, and it says so. |
| `TEST_SLOTS_RESERVE` | 2 | Cores left for everything else. |
| `TEST_SLOTS_WAIT_MINUTES` | 20 | The longest wait before it runs anyway. |
| `TEST_SLOTS_DIR` | `/run/user/<uid>/test-slots` (else `~/.cache/test-slots`) | Where the locks are. Everything that should share the 3 slots must use the same one. |
| `TEST_SLOTS_LOG` | `~/.local/state/test-slots/runs.jsonl` | One line per run. |
| `PRECOMMIT_PYTEST_WORKERS` | 8 | The most workers (the hook's `--max-workers`). |
| `TEST_SLOTS_WINDOW_SECONDS`, `TEST_SLOTS_RECHECK_SECONDS`, `TEST_SLOTS_RAMP_SECONDS`, `TEST_SLOTS_PROGRESS_SECONDS` | 3, 15, 30, 60 | The measuring window, how often it measures again, the ramp, how often it says it's still waiting. |

A setting that isn't a number is reported, and the tests run without waiting.

## The log

One JSON line per run in `TEST_SLOTS_LOG` (only its owner can read it). At 5 MB
it moves to `runs.jsonl.1` and a new one starts. It holds no environment, no
command arguments beyond the label, and no secrets.

| Field | What |
| --- | --- |
| `v` | Format version (1). |
| `start`, `end`, `wall_s` | When the tests ran and for how long (not counting the wait). |
| `cwd`, `label` | Where, and the `--label`. |
| `slot`, `cap` | The slot it held (`null` when not admitted), and the cap. |
| `cores_allowed`, `free_cores`, `reserve`, `workers` | The cores it may use, the free cores at admission (after the reserve), the reserve, the workers it ran. |
| `waited_s`, `ran_anyway` | How long it waited, and whether it ran anyway after the longest wait. |
| `unadmitted` | Why it ran without admission (off, or a fault of its own), else `null`. |
| `exit` | The tests' exit code (128 + N when signal N ended them). |
| `load1_start`, `load1_end` | The 1-minute load when the tests started and ended. |
| `cpu_some_pct` | CPU pressure over the run, machine-wide: the share of the time some task waited for a CPU (`/proc/pressure/cpu`). |
| `cgroup`, `cgroup_cpu_some_pct` | Its own cgroup, and the same pressure inside it (`cpu.pressure`). |

When a timing test fails again, these say whether the machine was the cause:
high pressure while the run held a slot means work that started after it took
the cores. Admission can't stop that work.

## Another repo can join

The script needs nothing from temper-ai: standard library, Linux. Another
repo's check can share the same 3 slots by running its tests through it with
the same `TEST_SLOTS_DIR`, putting `{workers}` where the worker count goes:

```bash
python3 ~/temper-ai/scripts/test_slot.py run --label "pi-web-ui vitest" \
    --min-workers 2 --max-workers 6 -- npx vitest run --maxWorkers={workers}
```

A command without `{workers}` is refused (exit 2), because a suite that sizes
itself would use cores the script didn't count. Whether pi-web-ui's or
rollcall's checks join is their owners' call (Ops, RollCall).

## What it can't do

Admission happens once, at the start. It can't stop work that starts later:
pi-web-ui's checks, chats' own runs, containers. The log's pressure fields are
there to tell such a case from a real failure.

Nor can it help a suite that ran anyway. In #225 (2026-10-30), one such full
suite timed out in a Team run's first parking wait, before installing the
invalid config the test was meant to check. That attempt's CPU allocation
was not recorded: its cause is not proved. Separately, controlled runs at
15 % of one core reproduced the same phase failure: about 4 CPU-seconds of
work took 31–40 s while events kept arriving. This demonstrates sensitivity
to constrained CPU, not the original run's CPU share or the cause of other
Pi-run failures.

The waits in `tests/test_runner/pi_parking` (`wait_parked`, `wait_ended`)
now use observed event progress. A new event restarts the inactivity count
(20 s by default; current explicit callers use 30 s). Normal probes run
about once a second; inactivity expiry checks once more for a late event.
Progress can extend the deadline up to 100 s from the start. Explicit
initial timeouts above 100 s would be retained; no current caller uses one.
These are cooperative polls, not an interruptible wall bound: slow callbacks
can overrun a deadline. A stopped run normally fails about its timeout after
its last observed event, saying "no progress".

## How it was proven

`tests/test_scripts/test_test_slot.py` has a stage test for each rule above,
with a fake `/proc/stat` and a fake clock, and real processes for the locks
and the signals. On the real machine (2026-10-19, Systems #18, hypothesis
H-GATE-ADMIT-1), each round ran pinned to cores 10-14, sharing its cgroup with
6 busy loops at equal weight. The test set was
`tests/test_runner/pi_parking`, 185 tests:

| Round | Result |
| --- | --- |
| No loops, `-n 4` | 3 of 3 passed (76-291 s) |
| 6 loops, plain `-n 4` | 1 of 5 failed: a Team-run wait overran its 20 s |
| 6 loops for 120 s, through `test_slot.py` | each waited 123 s, was admitted with 4 workers at 4.5-4.95 free cores of 5, and passed (62-68 s); 3 of 3, 0 timeouts |

The free cores it measured were within 0.1 core of mpstat's every time, and
within 1 of 5 minus the number of loops (0, 2 or 4). On a machine with room
it adds 3.1 s, the measuring window. The evidence is in
`~/company-lab/systems/gate-test-slots/` (RESULT.md).
