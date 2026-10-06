# What a run box holds

Every run executes in its own box, a container named `temper-run-<execution_id>`
that the worker starts from the server's container (`TEMPER_SPAWNER=docker`,
[reference/architecture.md](reference/architecture.md)). Whatever is in a box's
environment can be read from inside it with one `env`, by any agent in the run,
including one that a web page or a ticket talked into it. So a box gets only what
something in it reads, and an agent's tools get even less.

## Two layers

| Who | Gets | Where it's decided |
|---|---|---|
| The box (its own Python process that runs the workflow and records it) | Only the variables named on the box's allow-list, plus `TEMPER_RUN_CONTAINER` | `configs/boxes/env.yaml` + `configs/boxes/local/env.yaml`, read by `temper_ai/shared/box_env.py` at every spawn |
| An agent's tool processes: the Claude CLI and so its Bash, the Bash tool, script steps, `git`, OpenPullRequest's git, tmux for the interactive CLI | PATH, HOME, the locale, TZ, the proxies, `TEMPER_RUN_CONTAINER`, the list's `agent_tools: true` names, the one model credential that call uses, and the variables the agent's config passes explicitly (script steps' inputs) | `env_for_agent_tool()` in `temper_ai/shared/agent_env.py` |

An agent tool process never gets the database URL, the secret key, Redis, other
providers' keys or the rest of a token pool, whatever the list says. Pi steps run
in their own container with a fixed environment and get their model access over a
socket (`temper_ai/pi_agent/box.py`, [pi-agent.md](pi-agent.md)); MCP servers
started over stdio get the MCP SDK's minimal environment plus their config's `env:`.

## The allow-list

```yaml
box_env:
  - names: [WORKSPACE_DIR, TEMPER_API]
    why: scripts find the run's workspace and the server with them
    agent_tools: true          # the agent's tools may see them too
  - names: [TEMPER_DATABASE_URL]
    why: the runner records the run       # the box's own process only
```

- A name not on either file stays in the server. A new secret added to `.env`
  stays out of boxes until somebody lists it, with a reason.
- `configs/boxes/env.yaml` holds temper's own names and is tracked;
  `configs/boxes/local/env.yaml` holds this install's names (a design tool's URL,
  a browser bridge's token) and is git-ignored. The tracked file must exist; the
  local one is optional. A name listed twice is an error.
- `why:` is required: say who in the box reads the names.
- The GitHub app's keys (`integrations/github/secret.py` `SERVER_ONLY`) can never be
  listed; loading refuses them. A run asks the server for short-lived tokens instead.
- Nor can Pi's own settings, the switch `TEMPER_PI_AGENT`, the box config
  `TEMPER_PI_BOX_CONFIG` and the Pi lane's `TEMPER_LANE` and `TEMPER_PI_DRAIN_MARK`
  (`shared/box_env.py` `PI_ONLY`): Pi steps never run in a run box, so a box gets
  none of them, and with them no way to the Pi runtime, the logins or the role
  folders the box config names, nor a claim to be the Pi lane
  ([pi-agent.md](pi-agent.md), [pi-lane.md](pi-lane.md)).
- A secret (database URL, secret key, Redis URL, any `*_KEY`, `*_TOKEN`, `*_SECRET`,
  `*_PASSWORD`, `*_CREDENTIALS`) may be listed for the box's process, never with
  `agent_tools: true`.
- The list is read again for every run, so an edit reaches the next box with no
  restart. A list that does not load stops every run from starting (the spawn fails
  with "The box's allow-list is broken"); `temper check` names the problem first.
- At each spawn the worker logs the names it left out (`left out N variable(s) not
  on the box list: ...`), never a value.

## What a box no longer gets

The server keeps everything only it reads: the Slack and Telegram bots' tokens,
the Linear, Notion and GitHub webhook secrets, the API's token file, the Slack
test entry's token, and the worker's own settings. Temper's notices, questions
and answers in Slack and Telegram are sent by the server, so runs started there
work as before. The agent tools that act as a bot themselves (`SlackPost`,
`SlackReply`, `SlackReadThread`, `TelegramSend`; no shipped workflow uses them)
fail in a box with "..._TOKEN is not set" unless an install lists the token for
the box's process, which puts it within every agent's reach ("Still exposed").

## A run's own key

A box holds no key that lets it change things on the server: with the write
guard on ([api-access.md](api-access.md)), answering a wait, cancelling,
resuming or cleaning up from a box is refused. A workflow whose script steps
start other runs declares `starts_runs: true`; its run then makes a key of its
own that its script steps get as `TEMPER_RUN_TOKEN` (never agent tools), which
may only start and fork runs, and which dies with the run. The shared
`TEMPER_API_TOKEN` a box's process may carry counts for nothing there.

## The login file

A legacy box's Claude CLI finds the subscription login at
`/app/.claude/.credentials.json`. The worker's `TEMPER_BOX_LOGIN_FILE` names that file
on the host, and the spawner binds it there read-only at every box start
(`bind_login_file_from_setting()` in `temper_ai/spawner/docker_spawner.py`). The
worker never opens the file; docker binds it.

- It takes the place of a bind the template (the server's container) still has at
  that target, so docker never gets the target twice. Unset, a box gets the
  template's bind as before, or no login file when the template has none.
- Each box's profile says where its login file came from (`runtime.login_file`:
  `from` is `TEMPER_BOX_LOGIN_FILE`, `template` or `none`, with the source path,
  never the contents), and the worker logs one line per box: `login file from
  TEMPER_BOX_LOGIN_FILE: <path> -> <target> (read-only)`, `login file from the
  template's bind: ...` or `no login file (...)`.
- The worker reads the setting once, when it starts: a change needs a worker
  restart. A value that isn't a plain absolute path (relative, `..`, a trailing
  `/`, a comma, a quote or a line break) keeps the worker from starting (`Watcher
  won't start: TEMPER_BOX_LOGIN_FILE=...`), so no box starts until it is fixed or
  unset. A path with no file behind it stops each box at docker.
- The host's Claude CLI replaces the file by rename at each login refresh, and a
  bind keeps the file it found when its container started. A box started after a
  refresh gets the new file; a box that is running keeps the old one until it ends.
  That is why the server and worker no longer bind it themselves: neither process
  reads it (in `external` mode every model call is made in a box), and their bind
  went stale at the first refresh after they started.
- Sealed boxes get no login file, with the setting or without
  ([Sealed boxes](#sealed-boxes-bs1)).

## Emergency rollback

`TEMPER_BOX_ENV=inherit` in the worker's environment brings back the old box: a copy
of the server's whole environment minus the GitHub app's keys and Pi's own settings,
and the old deny-list for agent tools. It is off by default, logs a warning on every spawn, and is for an
emergency only: with it on, any agent can read every secret the server has. Anything
else in the switch reads as the list.

## Still exposed

What temper cannot close by itself yet, handed to Architecture:

- The box's own process holds the database URL (full write access), the secret key
  (decrypts stored sign-ins) and the model providers' keys and token pool, because
  it records the run, opens stored MCP sign-ins and calls the models. It also holds
  the other credentials its own tools use: `NOTION_TOKEN`, the Linear MCP's client
  credentials (`LINEAR_CLIENT_SECRET`), `TEMPER_GITHUB_TOKEN`, `TEMPER_API_TOKEN`
  (when an install sets one) and whatever secrets an install's local list gives
  the process (a browser bridge's token, a design tool's password). In memory
  only, it holds the run's own keys: one to ask the server for GitHub tokens,
  and, for a `starts_runs` workflow, one its script steps use to start runs
  ([api-access.md](api-access.md)).
- Agent tools run as the same user as that process, so they can read
  `/proc/1/environ` and the main process's `/proc/<pid>/environ` and find those
  values there. Scrubbing the tool environment stops a casual `env`, not a
  determined agent.
- Built, switched off: a one-shot delivery into a non-dumpable runner
  (`TEMPER_BOX_SECRET_BOOTSTRAP=oneshot`, below), which closes the `/proc` read.
  Still under consideration: a separate user for agent tools; a database role per
  box limited to its own run; a model-call proxy so boxes hold no provider keys.

## The box profile

Every box gets a profile (schema version 2): what the box is, settled by the
worker before `docker run`, from its own settings, the template container and the
workflow's configs. Nothing a run controls goes into it: not agent YAML, not
workspace files, not run output, not what a caller hands `queue_run`.

- Six settings, one per step of the box-secrets work. Each defaults to how boxes
  worked before, and a value for a step that isn't built refuses every run (a
  setting that claims more than the code does would be worse than none):

  | step | setting | values |
  |---|---|---|
  | BS1 | `TEMPER_BOX_RUNTIME_BOUNDARY` | `legacy` (default), `sealed` |
  | BS2 | `TEMPER_BOX_SECRET_BOOTSTRAP` | `env` (default), `oneshot` (needs `sealed`) |
  | BS3 | `TEMPER_BOX_CAPABILITIES` | `legacy` |
  | BS4 | `TEMPER_BOX_STATE_ACCESS` | `legacy` |
  | BS5 | `TEMPER_BOX_TOOL_ISOLATION` | `in_process` |
  | BS6 | `TEMPER_BOX_MODEL_ACCESS` | `direct` |

- The profile's digest and generation go on the run's row
  (`spawner_metadata.box_profile`, with a short history) and into the box
  (`TEMPER_BOX_PROFILE`, `TEMPER_BOX_PROFILE_DIGEST`,
  `TEMPER_BOX_PROFILE_GENERATION`). The first thing `temper run-workflow` does is
  check them: the profile must match its digest, and the row must hold this box's
  generation. Each new box for the same run (a resume, a replacement, a takeover)
  gets the next generation; an older box that finds a newer one on the row leaves
  without touching it. A record changed outside the worker is refused.
- Every profile says `hardening: partial` and lists what it leaves open: BS2-BS6
  and the network, which is recorded (who can reach what) but not enforced, so its
  closure is `negative`. A legacy profile also lists BS1 itself, with the kinds of
  mounts the box still gets.
- A legacy box is never stopped by its profile: if the profile can't be compiled
  or stored, the box starts as before, without one.

## Sealed boxes (BS1)

`TEMPER_BOX_RUNTIME_BOUNDARY=sealed` (worker and server) gives each run a box
that holds its own workspace and nothing it doesn't need. It is off by default.

What changes for a sealed box:

- **A positive mount list.** None of the template container's mounts are copied.
  The box gets the runner's code and configs, the private provider code (only
  `register_providers.py`, `providers/` and `agents/` of `local/`), one Claude CLI
  executable, the run's own workspace (read-write) and any data folder its
  workflow declares in `configs/boxes/data.yaml` (read-only). Absent: the main
  repo copy (`/app/repo`), the whole workspaces tree and its `/app/workspaces`
  alias, `.env`, key and login folders, the docker socket, other runs' folders.
- **Pinned sources.** The worker opens each source one path part at a time
  without following links and keeps it open until `docker run` returns; its
  device and inode go in the profile. A path swapped between the check and
  docker's use gives a box whose mount isn't the pinned one, and that box refuses
  to start. A workspace that is a link, sits outside `WORKSPACE_DIR`, holds or
  sits inside another run's workspace, or is a git worktree of a repository
  outside it is refused before any box starts.
- **Runtime files can't change.** The root filesystem is read-only, every grant
  but the workspace is read-only, the box drops all capabilities and runs as the
  template's unprivileged user, `PATH`, `HOME` and the Python variables are set by
  the worker, and the box starts the image's own interpreter (`python -I`, no
  `uv run`). The image is taken by its content id. Writable: the workspace,
  `/tmp`, and a `noexec` `/app/.claude` for the Claude CLI's state.
- **The box checks itself first.** Before the runner loads anything, a check the
  worker passes in as source (not code from a mount it checks) compares
  `/proc/self/mountinfo` with the profile: every grant is the pinned object with
  the right mode, nothing else is mounted, the absent paths are not there, and
  the runtime roots and their parents can't be written. Any difference: the box
  exits with code 3 and the run fails before any tool.
- **Launches are classified, fail-closed.** At every spawn (start, resume,
  replacement, takeover) the worker classifies the workflow's launch again from
  the config files themselves (`temper_ai/spawner/box_launches.py`): every agent
  (dispatched ones too), step, stage, tool, provider (fallbacks and the install's
  default too), provider setting, strategy, MCP server and file they name. A
  launch runs sealed only when every part is on the lists of what a sealed box
  enforces and is known before the run starts. One that names keys, shared roots,
  the main repo, the docker socket, a Pi step or an MCP server started in the box
  needs a legacy box; anything chosen at run time, unknown or unlisted is
  refused. The rules are engine code: nothing in a workflow, agent, workspace or
  run output can say what class it is. Agents that name no provider are sealed
  only when `TEMPER_DEFAULT_PROVIDER` pins one the lists have. The class is
  "gate-classified": no Security review of a launch stands behind it.
- **The engine's own launch paths are classified too.** The worker scans the
  code and local folders the box would mount for every place that starts a
  program, and starts no sealed box while one is missing from
  `box_launches.ENGINE_LAUNCHES` (`python -m temper_ai.spawner.box_launches
  sites` lists them; a test fails when the code and the list differ).
- **The box backs the classification.** Before loading anything, the runner
  checks every file of its launch against the profile; it then reads its configs
  only from those files (never the database) and refuses any agent type, tool,
  provider or MCP server outside the launch where it would be used, before any
  tool of it runs (`temper_ai/spawner/box_guard.py`).
- **What a sealed install refuses.** The subprocess spawner, runs in the server's
  own process (`TEMPER_EXECUTION_MODE=inprocess`), `TEMPER_BOX_ENV=inherit`,
  `TEMPER_DOCKER_WORKSPACES=all`, `TEMPER_DOCKER_IMAGE`, a run command other than
  `<python> -m temper_ai.cli.main run-workflow`, and a template running as root.
  Explicit no-socket development is not a protected fallback.
- **Never the subprocess spawner beside a Docker socket** (any install, HOME-REVIEW
  H1): a worker with `TEMPER_SPAWNER=subprocess` that can reach Docker (a socket at
  `/var/run/docker.sock` or `/run/docker.sock`, or `DOCKER_HOST`) refuses to start,
  because every run's tools would share the socket (`spawner/factory.py`). The one
  exception is the Pi lane's worker, which runs nothing but Pi steps
  ([pi-lane.md](pi-lane.md)); it in turn refuses any other spawner.
- **No going back for a run.** A run that ever had a sealed box never gets a
  legacy one. Rolling back means setting `legacy` again and starting fresh runs.

What sealed does not change (later steps), so a sealed profile is BS1-partial
and names these as still open: the runner's environment and memory hold its
secrets, the run's GitHub key among them (BS2); integrations use the box's own
keys (BS3); the runner and its tools reach the database with the shared login,
and Redis (BS4, and SQL until BS5); tools share the runner's process, mount and
network namespace, and the network is open (BS5); model calls hold credentials
in the box (BS6).

## One-shot secret delivery (BS2)

`TEMPER_BOX_SECRET_BOOTSTRAP=oneshot` (worker and server) keeps a box's secrets
out of everything another process in the box can read. It is off by default and
needs BS1's sealed profile: on a legacy install every run is refused.

- **The box starts with no secret.** The worker splits the box's environment: only
  fixed settings and names agent tools may see go to `docker run` (and so to
  docker-init's and the runner's start environment, `docker inspect`, argv,
  labels and the healthcheck, which is off); everything named or valued like a
  secret (a URL with a password, a run key) is delivered instead. The worker
  refuses an image that bakes in a secret-named or secret-valued variable, and a
  command that would carry a delivered value.
- **The runner protects itself before it reads.** The final interpreter
  (`temper run-workflow`, after the box's self-check) first sets
  `PR_SET_DUMPABLE 0` and turns core dumps off; then other processes of the same
  user can't read its `/proc/<pid>/environ`, memory or descriptors, or attach to
  it. No wrapper loads secrets and then execs: an exec resets the protection, so a
  replacement process has to take its own delivery, and a box takes one.
- **One bounded delivery.** The box has a private tmpfs, `/run/temper-boot`
  (0700, the box user's, `noexec,nosuid,nodev`, listed in the profile). The runner
  checks it, says it is waiting, and the worker's writer (`docker exec -i` as the
  box user, its program passed as source, the envelope on its stdin, never on
  disk outside the box) writes one 0600 file there. The runner checks the file's
  kind, owner, mode and links, reads a fixed-size header, checks run, profile
  digest, generation, expiry, names and schema, then reads the rest once, closes
  it, removes it, and only then acknowledges and allows tools. Every descriptor is
  close-on-exec. Sizes and the ready, delivery and acknowledgement deadlines are
  profile fields (`bootstrap`).
- **Failures stop the box.** A refused envelope, a timeout, a cancel before or
  after the runner is ready, or a missing acknowledgement: the worker stops the
  box, records the delivery as revoked on the run's row with a safe reason (never
  a value) and fails the spawn. The runner exits with code 4 (`box refused: ...`).
- **Nothing starts first.** Until the delivery is acknowledged, the box guard
  refuses every tool, `env_for_agent_tool` refuses every tool process, and the
  runner's bootstrap refuses to load.
- **Where the values live.** In the runner's Python mapping only (`os.environ`),
  so existing readers work unchanged; they are not in its C environment, so a
  child started without an explicit environment doesn't get them, and a tool's
  child still gets the scrubbed one (`env_for_agent_tool`).
- **Not closed by it, recorded in the profile:** a token handed on purpose to a
  CLI child (the Claude CLI's) is in that child's environment (`cli credential`,
  until BS6), and the runner still holds the values in memory (BS3-BS6).
- **Penpot.** A oneshot box has no channel for the Penpot password, so workflows
  that use it are refused with a plain reason (`box_launches.ONESHOT_MARKERS`) and
  run only on an explicit legacy profile until BS3; the design script reads no
  `/proc` there and has no other fallback.
- **Rolling back** is setting `env` again and starting fresh runs, never an
  automatic fallback.

## Checking it

- `temper check` loads both files.
- `ci_box_env` (no model, $0) lists the names in a box's tool environment and in
  every `/proc/*/environ` it can read, and fails on a server-only name anywhere in
  the box (Pi's `TEMPER_PI_AGENT`, `TEMPER_PI_BOX_CONFIG`, `TEMPER_LANE` and
  `TEMPER_PI_DRAIN_MARK` count as such) or a
  secret in a tool's environment. The machine check runs it on every
  commit ([ci-gate.md](ci-gate.md)); after a change to a list, run it live:
  `POST /api/runs {"workflow": "ci_box_env"}`.
  It also checks the box's profile: present, matching its digest and generation,
  listing what it leaves open, and in a sealed box the absent paths and
  unwritable runtime roots. In a oneshot box it also checks that no readable
  process started with a secret or delivered name, that the runner's environ and
  memory refuse it, that only the acknowledgement is left of the delivery, and
  that the profile records the CLI token's exposure. It prints facts and path
  names, never values.
- `tests/test_spawner/test_docker_spawner.py` (TestBoxEnvAllowList; the box
  profile tests: every current launch replayed against the command before BS1,
  and the sealed refusals), `tests/test_spawner/test_box_profile.py`,
  `tests/test_shared/test_box_env.py` and `tests/test_shared/test_agent_env.py`.
- `tests/test_spawner/test_box_launches.py` (the classification rules, fail-closed,
  and the engine's launch list against the code; `TEMPER_TEST_LOCAL_CODE=<folder>`
  checks the private local code's list too) and
  `tests/test_spawner/test_box_guard.py` (what a sealed box's runner refuses).
- `tests/test_spawner/test_box_sealed_docker.py` starts real sealed boxes in
  labeled throwaway containers with synthetic secrets: two runs, their own
  writes, declared data, every path a sealed box must not have, writes to the
  runtime, and swaps of the sources between the worker's check and docker's use.
  It skips without docker; `TEMPER_TEST_BOX_REQUIRED=1` makes that a failure, and
  `TEMPER_TEST_BOX_IMAGE` picks the image (else the newest `temper-ci-server`, else
  a tiny one it builds).
- The login file: `tests/test_spawner/test_docker_spawner.py` (the setting's bind,
  no second bind beside the template's, unset with and without the template's,
  sealed boxes, refused values) and `tests/test_spawner/test_box_login_file_docker.py`
  (real boxes before and after the host file is replaced by rename, with synthetic
  text, never a real login).
- `tests/test_spawner/test_box_bootstrap.py` (both ends of the delivery on the
  host: wrong, stale, oversized and malformed envelopes, mode, link, timeout,
  prctl and cleanup failures, early tool starts, error children, exec reset) and
  `tests/test_spawner/test_box_bootstrap_docker.py` (the G02 gate: real oneshot
  boxes with the real entry code, probed from outside the runner; a positive
  control without the protection; refusals, cancels and a restart).
- Both real-container files take every run id from `box_fixtures.run_id()` (the
  test's name, the pid and a few random hex characters), so each box name is its
  test process's own, and clean up only boxes with their own `temper.test.pid`
  label: two test runs at once (two checkouts' commit hooks, `pytest -n` workers)
  neither take the same name nor remove each other's boxes.
- In a live box, list names only, never values:
  `env | cut -d= -f1 | sort` and
  `for f in /proc/[0-9]*/environ; do tr '\0' '\n' < "$f" 2>/dev/null | cut -d= -f1; done | sort -u`.
