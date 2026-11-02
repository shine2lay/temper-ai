# Local test workers

## Policy

Local normal auto-worker runs default to **10**, not ten reserved CPUs.
Explicit diagnostic commands stay authoritative. Existing shared launcher
settings (including 6 during rollout) still win. This adapter does not
change the shared launcher's defaults, slots, placement, timeouts, test
selection or required checks. Already running processes are unaffected.

| Runner | Local precedence | Remote (`CI` or `GITHUB_ACTIONS` present, even empty) |
| --- | --- | --- |
| pytest `-n auto` / `-n logical` | `PYTEST_XDIST_AUTO_NUM_WORKERS`, then `WT_CHECK_WORKERS`, then 10 | Original xdist env parsing / CPU discovery |
| pre-commit pytest | Nonempty `PRECOMMIT_PYTEST_WORKERS` sets the xdist env above | Same existing override and xdist behavior |
| Vitest | Explicit CLI / serial setting, then `VITEST_MAX_WORKERS`, then `WT_CHECK_WORKERS`, then 10 | Original Vitest config and env handling |

pytest without `-n`, `-n 0`, explicit `-n 2`, `--pdb`, and
`--maxprocesses` retain native behavior. Only the existing auto-worker hook
has a new default; a serial diagnostic is never made parallel. The xdist
worker path still skips admission/re-entry. `tests/machine_slot.py` is
unchanged: a restart through `wt slot` can supply the inherited worker
setting before xdist resolves again.

Vitest serial diagnostics use `--no-file-parallelism` or `--maxWorkers=1`,
not 0. CLI counts and percentages use Vitest's own parser. The local Vite
plugin temporarily consumes `VITEST_MAX_WORKERS` during configuration and
restores it after resolution (and on close), so watch reloads and test
workers retain it. Why: Vitest 4 otherwise re-applies the env **after** its
CLI/serial handling and would turn an explicit serial diagnostic parallel.
The plugin does nothing on ordinary Vite builds/dev launches or remote CI.
Playwright configurations, especially serial live-browser cases, are unchanged.

Malformed existing runner env inputs keep the runner's handling: xdist
warns and discovers CPUs for a non-integer; Vitest uses `parseInt` (a wholly
non-numeric value resolves to `NaN`, leaving its pool's native fallback).
The newly consumed `WT_CHECK_WORKERS` must contain only decimal digits:
Python accepts nonnegative integers (`0` means serial); Vitest accepts positive
integers exactly representable by JavaScript. Missing shared input uses the
supported default. Present empty, malformed, fractional, signed or negative
shared input fails with an actionable error that never prints its value,
before test collection or worker test bodies run. Empty runner-specific values
still fall through to shared input/default, as before.

Validation applies only when shared input is used: CLI/serial settings and
nonempty runner-specific env overrides still win, even over invalid shared
input. Remote CI ignores shared input as before. Vitest's existing plugin
checks the final resolved value after CLI/serial merging, before test startup;
it does not replace native parsing of `VITEST_MAX_WORKERS`.

## Hypothesis and checks

The approved hypothesis is that local auto-worker defaults bypass intended
policy at existing runner seams. Reuse xdist's first-result auto-count hook
and Vite's test configuration instead of making a runner or pool. Expected:
local unset=10, explicit=2, inherited=6, serial retained. Falsifier: different
resolved counts, lost serial diagnostics, remote resolution drift or re-entry.

Pre-change inspection at `bfef9a61`, using the locked runners:

- xdist's auto-count hook on this host returned 20 with worker env unset.
- `createVitest` with this repo's config resolved `maxWorkers` unset locally
  and on CI; env=6 resolved 6. CLI=2 plus env=6 still resolved 6, and
  `fileParallelism=false` plus env=6 also resolved 6 (the late env override).
- There was no repository xdist auto-count hook. The hook already exported
  `PRECOMMIT_PYTEST_WORKERS`; the adapter reuses that route.

Known-answer checks use the real xdist parser/hook resolution and real
Vitest config loading, not text searches for a default. They cover local,
CLI/diagnostic, inherited, malformed and remote settings. Disposable synthetic
tests prove invalid shared input stops before collection/bodies; clean controls
prove those sentinels would run. The fixtures are removed after each check.

Validation correction hypothesis: loose shared-input parsing can silently use
an unintended worker count. Whole-value validation at the existing seams
should reject consumed invalid input without breaking ignored input or native
overrides. A test body running on invalid input, a raw value in the error, or
changed CLI/remote resolution falsifies this correction. Existing machine
slot and outside/inactive fail-closed tests retain their assertions. CI
workflow and browser config files are not edited; all eight required gates
remain. These are compatibility checks, not a throughput claim or proof
that the shared default has been deployed.
