# Shared test CPU: Docker transports (part E)

## Hypothesis and fixed cases — written before implementation

H-SHARED-CPU-E-1: the host test launcher cannot contain work created by the
Docker daemon. The existing test PG, BoxDocker/OneshotDocker and tiny image
build have no explicit shared parent. Querying the central policy at creation,
setting the parent, and checking host PID membership should contain their work
without changing the production spawner or existing tests' results.

Falsifiers: accepting off-parent reuse as capped; an ignored build parent;
changed production flags; replacing a shared/live database. Runtime containment
remains **UNPROVEN** until Ops' part G; mocked argument tests are not CPU proof.

Fixed controls, expected results:

| Input | Expected |
| --- | --- |
| CLI absent and policy absent, or `parent` exits 3 | Original arguments, PG name/5455 and outcomes; no membership claim |
| Missing CLI with any policy present; failed/malformed parent query | FAIL before Docker work |
| Enabled valid slice, local rootful systemd/v2 daemon | One `--cgroup-parent` per create; never a per-job quota |
| Remote endpoint, rootless/Desktop daemon, wrong cgroup driver/version | FAIL before create; no fallback |
| Running container with matching parent, host init PID and all listed PIDs inside | PASS reuse/exec preflight |
| Wrong parent/PID/path/quota, stopped container, PID identity changed | FAIL, no reuse, no migration/deletion |
| Enabled PG, old PG busy on 5455 | Separate `temper-test-postgres-cpu`, loopback 5456; no old-PG commands |
| Explicit old PG name or old port while enabled | FAIL; no forced cleanup |
| Selected PG stopped/off-parent, port occupied, clients or live schemas | Refuse unsafe replacement/down; preserve locks and schema checks |
| Box run / one-shot exec success, failure, timeout and cleanup | Original return/output/exception and owned cleanup retained |
| Supported local buildx docker builder | Explicit shared build parent; original RUN content retained |
| Unsupported builder or failed enabled build | FAIL, never `None`/skip; G must repair |
| Guard removed / pre-change source | Corresponding fixed negative/old-code control fails |

## Boundaries

Accountable lead: Systems; repository/fixture reviewer: Temper. Source-only
adapter, landed inactive. A's frozen interface is
`agent-tools/docs/test-cpu-contract.md`, landed as `8334dbf4a93e625ea009428c8d842fee5d9c059a`.
The CLI is `/usr/local/libexec/test-cpu/bin/test-cpu`; it owns policy, quota and
kernel membership. This adapter neither copies the quota nor installs anything.

The Docker CLI is **client** work (part C's host launcher). Container init,
Postgres, box children, `docker exec` and build RUN instructions are **daemon**
work (this adapter). Production DockerSpawner, live compose and daemon defaults
are unchanged. No old container is moved, stopped or adopted. No privileged
builder, daemon restart, docker-group change or second Temper instance.

Worktree: `/home/shinelay/temper-ai-systems-task-60`, branch `systems-task-60`.
Claim N/A: cwd-local claims cannot cover this repository from the queue chat's
RollCall folder; isolation is this pre-created task-owned worktree.

## Repair hypothesis — full-hook compatibility control

H-SHARED-CPU-E-2 (before repair, 2026-10-30): the first normal hook passed
17,433 tests but failed the existing kill-accounting unit test. That test mocks
all `subprocess.run` calls; the absent canonical CLI therefore appeared to
return an empty successful parent rather than FileNotFoundError. This is our
adapter's missing-install detection, not load, PG state or an allowed kill.

Change: establish canonical CLI/policy absence with `lstat` before invoking the
CLI. No installation and no policy still means inactive; any policy or a broken
installed CLI still refuses. The fixed fake CLI transport must explicitly model
an installed CLI. Expected: the unchanged kill-accounting test passes with the
same original Docker calls/results; absent-policy and present-policy controls
stay correct. Falsifier: present policy is accepted without a usable CLI, or
kill accounting changes. Run this doubtful stage and its regression once after
the repair, then the normal hook. Do not rerun the unchanged failing hook.

Result: **LIMITED HIT** on an absent-install host: **103 passed in 60.54 s**
(`systems60-compatibility`). Present-policy refusal and kill accounting passed,
but Temper #235 reproduced the installed-CLI hole below; this is not acceptance.

## Temper review repair hypotheses (before edits)

Written first in `shared-test-cpu-plan/evidence-E/REPAIR-HYPOTHESES.md`.
Systems Lead's queue answer (2026-10-30) admits the eighth file,
`tests/test_spawner/test_box_refused_ending.py`, solely for hermetic injection.
This is a technical repair decision, not owner consent or activation.

- **H-SHARED-CPU-E-3 / R1:** the installed CLI is still swallowed by the old
  kill-accounting test's global subprocess mock. Inject its unchanged fake at
  OneshotDocker's placement boundary; retain every kill/exit/refusal assertion.
  Fixed absent, installed-inactive and installed-enabled states must all pass
  without policy queries; the old broad patch must still fail when installed.
  Any weakened policy validation or fabricated membership falsifies the fix.
- **H-SHARED-CPU-E-4 / R2:** Temper's fixed 1.0-second caller budget reached 1.7
  because verification renewed each query's allowance. Capture one original
  caller deadline and pass remaining time through policy, daemon, PID and
  builder queries plus payload work. Fixed slow successes must exhaust at 1.0,
  release no payload and retain TimeoutExpired/cleanup; an independent-query
  mutation must miss that answer. The one-second case is test design, not a
  runtime cap. Non-finite caller timeouts remain non-finite.
- **H-SHARED-CPU-E-5 / R3:** source review found the cancellation timer armed
  before potentially slow preflight (not a claimed live reproduction). Verify
  first, then invoke the callback once immediately before exec. A fixed clock
  must spend over two seconds in unarmed preflight, then cancel while the fake
  writer waits. Exercise the real spawner's revoked-delivery/error handling and
  unchanged kill validator. Callback-before-preflight must fail that answer.
  Command/stdin tampering remains; switching the verified container must fail.

R1/R2 were independently reproduced; R3 started as static reasoning. Repair
stage **PASS: 140 passed in 69.17 s**, 2026-10-30 16:52:52 PDT, detached
`systems60-review-repairs`. H-E-3/E-4/E-5 are **HIT for the fixed synthetic
controls**: installed-state compatibility, one shared deadline, deterministic
cancellation and their negative mutations. R3 now has a reproduced synthetic
ordering failure, not live Docker evidence. Malformed builder diagnostics and
PG override/stopped-parent controls also passed. The in-flight old hook was
left unchanged to finish before edits. These results are not live builder,
PG concurrency or aggregate CPU proof.

## Implemented transport and safeguards

- `container_parent()` uses only the canonical installed CLI. Exit 3 means
  inactive. Missing CLI is inactive only when the CLI and policy are both
  absent; malformed policy, missing/broken installation with policy present,
  parent/status disagreement or a foreign cgroup namespace fail visibly.
- Enabled creation requires a local Docker socket, rootful daemon and systemd
  cgroup v2. Docker context precedence matches the CLI. Neither the daemon nor
  a production container's defaults are changed.
- Reuse inspects the configured parent and host init PID, then checks the CLI's
  membership result for init and every PID Docker currently lists. PID start
  time and container identity are rechecked. Exec does the same preflight;
  exec descendants inherit the container cgroup. Short-lived descendants that
  already ended are not observed proof: G must hold exec/children to measure.
- Foreground box probes would end before a reliable inspect. Enabled mode
  holds the entry on an stdin handshake, checks the host PID, then `exec`s the
  original entry and arguments. No added mount, environment or network access.
  No successful return is accepted without proof. The original timeout and
  output/exit contract remain, and fixture cleanup still removes only its own
  named containers. Policy/daemon/identity checks and payload share the original
  caller deadline; no fresh per-query budget extends it. Exec callbacks run
  after preflight, immediately before exec. Inactive argv/stdin/output behavior
  stays unchanged, with only elapsed discovery deducted from a finite timeout.
- PG selects `temper-test-postgres-cpu` on 127.0.0.1:5456 when enabled. Custom
  capped names use its `-suffix`; ports 5432/5433/5455 and legacy names are
  refused. Old 5455 PG is not inspected, replaced, stopped or migrated.
  Per-name lock, collision check, tmpfs, authentication and client/live-schema
  checks remain. Existing stopped off-parent containers are refused before
  removal. Running reused PG also has to match its requested port/binding.
  Enabled `down --force` cannot override shared-PG safety.
- When a tiny-image build is needed, it pins the selected local buildx `docker` driver,
  uses `--load` and supplies `--cgroup-parent`. Other builders, endpoint mismatch,
  absent flag support and enabled build failure raise an error, never `None`
  (which the existing fixtures would interpret as unavailable/skip). Image
  cache hits are reuse, not build RUN containment evidence.

G's required live proof: uncached build RUN with held work; fresh and reused
capped PG while old PG is busy; box init and held exec/children host PIDs;
negative endpoint/driver/reuse and builder-no-op cases; combined CPU accounting.
An installed builder that ignores/refuses the parent is **FAIL** for G to repair,
not a skipped case or permission to enable. G/H own installation and activation.

## Qualification ledger

- Fixed transport controls: **PASS**, 86 passed in 44.60 s (2026-10-30), in
  detached `systems60-focused`. Includes seven helper guard-removal controls,
  two PG guard-removal controls and the old BoxDocker call-site wiring control.
  This is a hit for the argument/refusal contract, not a live containment hit.
- Source-preservation check: **PASS**, all seven existing fixture test function
  bodies and decorators in the touched modules are AST-identical to the base.
  Syntax, focused lint and diff-whitespace checks passed.
- First mandatory hook: **FAIL**, 1 failed / 17,433 passed / 34 skipped / 2,804
  subtests passed in 1201.51 s. The single failure is
  `test_the_wrapper_counts_only_a_kill_of_that_box_docker_took`; H-SHARED-CPU-E-2
  records the bounded repair. Ruff and mypy passed. No commit was made.
- Compatibility repair stage: **PASS**, 103 passed in 60.54 s; no live placement
  trial. Receipt: `shared-test-cpu-plan/evidence-E/compatibility.log`.
- Pre-review-repair hook: **PASS**, 17,435 passed / 34 skipped / 2,804 subtests
  passed in 1594.00 s; Ruff and mypy passed. Commit
  `075a682cac598aff6c954bd4ddf149708e0fe7bd`, before R1/R2/R3 repairs, is not
  accepted or landed. The missing installed/slow-preflight controls explain
  why this green hook did not close Temper's findings.
- Review repairs: **PASS**, 140 passed in 69.17 s, including original offline
  kill accounting and fixed installed-state, clock/cancellation, malformed
  builder and PG override/stopped-parent controls. Receipt:
  `shared-test-cpu-plan/evidence-E/review-repairs.log`.
- Final repaired hook, eight CI checks, post-land temper-ci: UNPROVEN.
- Enabled Docker/PG/build RUN PID and descendant placement: UNPROVEN, reserved
  for G. Successful CLI parsing/flags or a cached image cannot establish it.
- Aggregate CPU allowance: UNPROVEN, G's joined proof, not this task's claim.
- Policy/helper installation and activation: not performed; G/H own them.

Focused suite receipt: `shared-test-cpu-plan/evidence-E/focused.log`. It waited
for the existing machine slot, then the existing `wt slot` timeout ran it without
a slot; no slot setting was changed. Source test results are not quiet-host CPU
measurements.

## Recorded requirements clarification

Temper consultation rm-e66acff1 (2026-10-30), answering rm-192a5358:

- Sibling name/5456 collision? No conflict observed at that instant, not reserved.
- Endpoint timing? Select before pytest and keep stable throughout its Python
  process; the schema-ready cache keys schema, not URL. The script selects once
  per invocation; no pytest endpoint switching or pgtier edits are introduced.
- Shell output? `url` stdout stays exactly the connection URL; all placement
  refusals go to stderr. PG schema/client/live-database fences stay in place.
- Fixture semantics? Keep BoxDocker foreground/finally cleanup distinct from
  OneshotDocker detached/retained exit inspection, tampering callbacks, ownership
  labels and recorded spawner kills. Observer cleanup is not a spawner kill.
- Build reuse? Explicit/existing/cached image branches stay; unsupported enabled
  builds must fail rather than return into skip. Actual live proof remains G.

This was source/semantics consultation, not final candidate acceptance.

Read-only preflight (2026-10-30): installed Docker 29.2.1, systemd cgroup v2,
rootful local `unix:///var/run/docker.sock`; buildx 0.31.1, default docker driver,
BuildKit v0.27.1. Both installed CLI and canonical policy absent. Buildx inspect
has no JSON `--format` here; buildx ls does. Build-parent support must be proved
with uncached RUN work in G, not inferred from these version strings.
