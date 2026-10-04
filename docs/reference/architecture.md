# Architecture — Server + Worker

How a workflow run is hosted in Temper AI. Three execution modes, picked per server via `TEMPER_EXECUTION_MODE`. The default is `inprocess` (legacy single-process behavior); the others split orchestration from execution so engineer agents can run real tools (pytest, npm, docker, db clients) without bloating the server image.

## TL;DR

```
TEMPER_EXECUTION_MODE=inprocess (default)   server thread runs the workflow
TEMPER_EXECUTION_MODE=subprocess            server forks a child in its own container
TEMPER_EXECUTION_MODE=external              server queues; separate worker container runs it
```

Set the env var on the server. The dashboard, REST API, WebSocket stream — everything else looks the same to a user. The difference is where compute happens.

## Why split orchestration from execution

Engineer agents in coding workflows need a real toolchain to validate their work — `pytest`, `npm install`, `docker compose up`, `psql`, `alembic upgrade`. Putting all of that into the server image:

- bloats the image (~600MB of extra tooling),
- broadens the attack surface (every dep an agent might invoke is also exposed to anyone who can reach the API),
- couples server upgrades to toolchain upgrades (can't bump pytest without redeploying the API plane).

The standard fix — used by Argo, GitLab CI, GitHub Actions runners, Temporal workers — is a separate worker process. The orchestrator stays small; the worker carries whatever tools jobs need. Temper's worker container follows the same pattern.

## Execution modes in detail

### `inprocess` (default)

The server runs the workflow in a daemon thread inside its own process. This is the original Temper behavior; existing users see no change unless they opt in.

- **Where it runs:** server's process
- **Crash semantics:** server crash = workflow dies
- **Toolchain:** whatever's in the server image (Python, Node, no pytest by default)
- **Cancel:** in-memory `threading.Event` set by `POST /api/runs/{id}/cancel`
- **Live streaming:** in-memory event bus → WebSocket
- **When to use:** local dev on a single host, low-isolation OK, fastest setup

### `subprocess`

The server inserts a `WorkflowRun` row, then `subprocess.Popen`s `python -m temper_ai.cli.main run-workflow --execution-id <id>` as a child of the server process. The child runs in the same container.

- **Where it runs:** child process inside the server container
- **Crash semantics:** server crash kills children (same container); child crash leaves server intact
- **Toolchain:** still whatever's in the server image (no improvement over inprocess for this)
- **Cancel:** `POST /api/runs/{id}/cancel` flips `cancel_requested` on the WorkflowRun row; reaper sends SIGTERM to the child's process group, escalates to SIGKILL after 30s
- **Live streaming:** worker publishes to Redis Streams (`temper:chunks:{execution_id}`); server's WS handler subscribes and forwards
- **When to use:** crash isolation between concurrent runs without setting up a worker container

### `external`

The server inserts a queued `WorkflowRun` row with `status='queued'` and returns. A separate `temper-ai-worker` container runs `temper watch-queue` as a long-lived daemon, polls for queued rows, atomically claims them (race-safe across multiple watchers), and spawns workers locally to itself.

- **Where it runs:** decided by the worker's `TEMPER_SPAWNER` — `subprocess` (default): a child process inside the `temper-ai-worker` container; `docker`: a container of the run's own, started by the worker through the host's docker socket (see [Spawner abstraction](#spawner-abstraction)).
- **Crash semantics:** server can die freely; worker keeps running. Worker crash detected by reaper → row marked `orphaned`.
- **Toolchain:** worker image bakes in `pytest`, `npm`, `docker-ce-cli`, `docker-compose-plugin`, `postgresql-client`, `redis-tools`, `jq`, `vim`, build essentials. Engineer agents reach for them naturally.
- **Cancel:** `POST /api/runs/{id}/cancel` flips `cancel_requested`; worker container's reaper observes within 5s and signals.
- **Live streaming:** worker → Redis Streams → server WS forwarder → dashboard
- **When to use:** real engineering workflows where agents need to actually run their code; multi-tenant; production deploys

## How to enable `external` mode

The worker service is profile-gated in `docker-compose.yml` so existing single-container users aren't affected:

```bash
# In docker-compose.override.yml or .env, set:
TEMPER_EXECUTION_MODE=external

# Then bring everything up:
docker compose --profile worker up -d
```

This brings up four containers:

```
temper-ai-postgres-1   shared workflow_runs + events DB
temper-ai-redis-1      live chunk transport
temper-ai-server-1     FastAPI + dashboard, no engineer toolchain
temper-ai-worker-1     watch-queue daemon, full engineer toolchain
```

The worker does not get the host's docker socket by default: a node's Bash runs as the worker's `temperai-worker` user (UID 1000), and a uid that can reach the socket can start a container with the host's filesystem mounted — root on the host. Runs that need it (engineer agents bringing a repository's compose stack up) layer on the opt-in overlay `docker-compose.host-docker.yml`, which mounts the socket and adds the host's docker group:

```bash
# In .env:
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
WORKSPACE_DIR=/absolute/path/to/your/workspaces

docker compose -f docker-compose.yml -f docker-compose.host-docker.yml --profile worker up -d worker
```

The path-equivalent workspace mount (host path = container path) is required so engineer agents running `docker compose up` against the host docker daemon resolve volume mounts correctly. The source mounts (`temper_ai/`, `configs/`) are read-only in both containers: a run must not be able to rewrite the code the next run executes.

## What runs where on the owner's host, and restarts

Since 2026-09-27 the owner's temper runs `external` with `TEMPER_SPAWNER=docker`: the server only talks (dashboard, API, Slack, Telegram, Notion, Linear, the notify loop, triggers) and queues runs; the worker starts each run in its own box, a copy of the server container (`TEMPER_DOCKER_TEMPLATE_CONTAINER=temper-ai-server-1`) named `temper-run-<execution_id>`.

- **Restarting the server** (a new key, a Slack/Telegram/Notion/Linear or webhook change) takes seconds and touches no run. A run waiting at a gate keeps waiting in its box; an answer given after the restart reaches it.
- **Restarting the worker** touches no run either. At start its reaper looks for each running row's box by execution_id; only a run whose box is gone (e.g. the host itself went down) is marked `orphaned`.
- **What a new run reads.** Each run's box (`run-workflow`, through `runner/bootstrap.py`) imports `temper_ai/` and loads every config under `configs/` from `~/temper-ai` when it starts, committed or not, into the shared config table the server reads too. The exceptions are the folders the config importer skips (`NON_CONFIG_DIRS`: slack, telegram, notion, notify, triggers, tools, mcp_servers). They hold settings the server and worker read themselves and aren't loaded into that table, so plan on a restart for a change there. So a saved change to a workflow or agent config reaches the next run without a restart. Changes to the server's and worker's own code, or to those settings, need one.
- **`temper-deploy restart`** no longer waits for runs to finish in this mode. It waits only while `~/temper-ai` has uncommitted changes (new files too) that a restart would make live: `temper_ai/`, `docker-compose.yml`, the build files, and the settings folders above. It reads the settings folders from the importer's `NON_CONFIG_DIRS`. Other uncommitted config files never hold a restart, because runs already load them. `status`, `check` and the restart report name them.

Checked live on 2026-09-27/28 (queue task 7): `/run notify_probe` from Slack and from Telegram, a Linear trigger, gate answers in Slack and Telegram, a stop from Slack, a Linear docs task built by epd_task that opened its pull request (Bash, git and the Claude CLI in a box), a server restart then a worker restart with a gate-waiting run and four long runs going (all finished or kept going), and run boxes without the docker socket, as uid 999.

## Where the data lives

### `WorkflowRun` SQL table — spawner bookkeeping

Per-run row tracking what's queued / running / done. Fields: `execution_id`, `workflow_name`, `workspace_path`, `inputs`, `status`, `spawner_kind`, `spawner_handle` (PID), `cancel_requested`, `attempts`, timestamps, terminal `result` / `error`.

Lifecycle: server inserts (status=queued) → spawner/watcher claims (status=running, handle stamped) → worker writes terminal status on exit. Multi-watcher safe via single-statement atomic UPDATE...WHERE.

### `events` SQL table — milestone log

What was already there pre-Phase-7: `agent.started`, `agent.completed`, `llm.iteration`, etc. Now `llm.iteration` events also carry the `tool_calls` list (name + truncated arguments) so post-run forensic tools can reconstruct what each agent invoked without scraping Redis.

### Redis Streams — chunk transport

Per-run stream at `temper:chunks:{execution_id}` with MAXLEN ~10k entries (auto-trim) and 24h TTL after the worker writes a terminal sentinel chunk. Workers XADD; server's WS handler XREADs per connection.

### JSONL files — forensic log

`${TEMPER_LOG_DIR}/{execution_id}/events.jsonl` per run. Format:

```
line 1:    {"kind":"header","execution_id":...,"workflow_name":...,"started_at":...,"runner_version":"1.0","hostname":...,"pid":...,"metadata":{...}}
line 2..N: {"kind":"event","ts":...,"event_type":...,"data":{...}}
line N+1:  {"kind":"footer","ts":...,"reason":"cleanup"}
```

Missing footer line = the run was interrupted before clean shutdown. Append-mode opens — re-running with the same execution_id appends rather than clobbering, supporting resume semantics.

## Events from outside (the inbox)

Everything temper receives from outside is saved in Postgres, in the `inbox_events` table, before temper tells the sender it got it. It is handled from that row (`temper_ai/integrations/inbox/`). This covers Linear and Notion webhooks, Slack envelopes and Telegram updates.

| Source | Saved before | Delivery id (unique per source) |
| --- | --- | --- |
| Linear | the 200 answer (after the signature check) | `Linear-Delivery` |
| Notion | the 200 answer (after the signature check) | the event's `id` |
| Slack | the Socket Mode ack | `msg:<channel>:<ts>` for messages, else the envelope id |
| Telegram | the `getUpdates` offset moves | `update_id` |

- **Statuses.** `new` → `handling` → `done` / `skipped`, or `failed` and back to `handling` at its next try, and `gave_up` after the fifth failure. Slack items over 30 minutes old become `expired`, because their answer link has lapsed. Events that came before their signing key was set are `unverified` until checked.
- **Once.** The same delivery id is one row, so a re-sent event is noticed and not handled twice. Each status change is one UPDATE guarded by the status it expects, so two threads never take the same event.
- **Runs start once.** `start_run` writes each run on the event being handled the moment it starts. A retried event that already started a run doesn't start it again. Linear, whose one delivery can start several rules, starts only the ones that didn't start yet.
- **Retries.** A sweeper thread in the server runs every 15 s. It retries failed rows after 1 min, 5 min, 30 min and 2 h, then gives up. It also takes rows a restart left in `new` or `handling`, and checks `unverified` rows once their key is set (genuine ones are handled, the rest deleted). It starts after Slack, Telegram and Notion, so what a restart cut off meets its source already running; an event whose source is on but not running yet waits and is tried again, never closed as "off".
- **Clean-up.** Once an hour, done, skipped and expired rows older than 14 days are deleted, and failed, given-up and unverified ones after 30.
- **Looking at it.** `temper events list [--source] [--status] [--since 2h]`, `temper events show ID` and `temper events replay ID` (API: `GET /api/events`, `GET /api/events/{id}`, `POST /api/events/{id}/replay`). Replay refuses an event that already started a run, and says which run. `GET /api/hooks/linear/recent` and `/api/hooks/notion/recent` read the same table.
- **While the server itself is down**, nothing reaches the inbox. The senders cover that gap:
  - Linear and Notion send unanswered webhooks again.
  - Slack retries events such as mentions and DMs. A slash command or click made while temper is down fails in Slack at once, so the person sees it and can try again.
  - Telegram keeps updates for up to 24 hours until temper asks for them.

## Spawner abstraction

`temper_ai/spawner/` defines a `Spawner` ABC with `spawn(execution_id) → ProcessHandle`, `is_alive(handle) → bool`, `kill(handle, force=False)`, and a class-level `kind` the watcher stamps into `WorkflowRun.spawner_kind` when it claims a row. `get_spawner()` reads `$TEMPER_SPAWNER` and returns the right one; a future `K8sJobSpawner` (per-run pod) drops in without touching routes.

- **`SubprocessSpawner`** (default) — `python -m temper_ai.cli.main run-workflow` as a child process of the watcher, in the worker container. Every run shares the container: its filesystem, its uid, every other run's workspace, and the docker socket if the overlay mounted it.
- **`DockerSpawner`** (`TEMPER_SPAWNER=docker`) — one container per run. The worker inspects its own container and starts a sibling from it: same image (or `TEMPER_DOCKER_IMAGE`), same environment, same networks and read-only mounts; the broad workspaces mount replaced by the run's own workspace at the same host path (plus the git main repository when the workspace is a worktree); its own `/tmp`; never the docker socket. Named `temper-run-<execution_id>`, `--rm --init`, `no-new-privileges`, `--no-healthcheck` (the image's healthcheck asks for the server's port, which no run listens on); optional `TEMPER_DOCKER_MEMORY` / `TEMPER_DOCKER_CPUS` / `TEMPER_DOCKER_PIDS_LIMIT`. The worker needs the socket for this (`docker-compose.host-docker.yml`) and uses it for nothing else; the run tells the reaper its container name through `TEMPER_RUN_CONTAINER`, and liveness/kill are keyed on the execution_id so they survive a worker restart. This is the sandbox the tool docs refer to; the workspace check, the Bash allowlist and the platform baseline are guardrails inside it.

The reaper (`temper_ai/spawner/reaper.py`) runs on a 5s tick, polls `WorkflowRun` rows with `status='running'`, asks the spawner if each handle is alive, marks the dead as `orphaned`. For `cancel_requested=true`, sends SIGTERM, then SIGKILL after a 30s grace period. Idempotent kill — already-dead processes don't error.

## Concurrency model

- **One watcher per worker container.** Multiple workers can run in the same container (the watcher spawns each as a subprocess). Multiple worker containers also work — the atomic claim in `_claim_row` ensures only one watcher gets a given queued row.
- **Cooperative cancel inside the worker.** The executor checks `cancel_event` at node boundaries. The worker's signal handler sets `cancel_event` on SIGTERM; a second signal restores the default handler so the user (or the reaper's SIGKILL) can hard-kill if the workflow refuses to wind down.
- **Process group isolation.** `start_new_session=True` puts each worker in its own session so SIGTERM-to-pgroup catches any tools the worker forked (bash subshells, claude CLI, etc.).

## What a queued run looks like end to end

```
1. user → POST /api/runs {workflow, inputs, workspace_path}
2. server (external mode) → INSERT INTO workflow_runs (status='queued')
3. server → 200 {"execution_id": "...", "status": "queued"}

4. worker container, watch-queue daemon (every 2s):
     SELECT FROM workflow_runs WHERE status='queued' AND spawner_kind IS NULL
     UPDATE ... SET spawner_kind=<spawner.kind>, spawner_handle='claiming'  (atomic)
     spawner.spawn(execution_id) → ProcessHandle(pid | container name)
     UPDATE ... SET spawner_handle=<handle>

5. the run (`temper run-workflow --execution-id <id>`, a child process or its own container):
     UPDATE ... SET status='running', started_at=now(), attempts++
     install signal handlers (SIGTERM/SIGINT → cancel_event.set())
     bootstrap RunnerContext from env (DB, LLM providers, memory, configs)
     build CompositeNotifier(RedisChunkNotifier, JsonlNotifier)
     execute_workflow(...)  → events to DB, chunks to Redis, JSONL to disk
     UPDATE ... SET status='completed' (or 'failed' / 'cancelled'), completed_at=now()
     publish terminal sentinel chunk + close Redis client
     close JSONL file (footer line written)

6. dashboard (anytime):
     GET /api/workflows/{id}      → reads events table, builds DAG view
     WS /ws/{id}                  → server forwards Redis chunks live
```

## Failure surfaces

| Failure | Behavior |
|---------|----------|
| Server crashes mid-run | External-mode workers keep running; in-memory state lost but DB/Redis/JSONL all intact. Reaper on next server start (or in worker container) catches up. |
| Worker process crashes | Reaper detects within 5s via `is_alive()` → marks row `orphaned`. UI moves on. JSONL ends without footer (interruption marker). |
| Redis unreachable | Workers run in degraded mode (chunks dropped silently); events still go to DB; dashboard shows event-level updates only, no live tokens. |
| Postgres unreachable | Workers fail fast — bootstrap returns exit code 2, row marked `failed` with `error.kind='bootstrap'` if write succeeds, else watcher won't claim more until DB returns. |
| Bootstrap-script gap | `build_checker` looks for `scripts/build.sh` / `scripts/test.sh`; reports SKIPPED if missing. (Engineer agents can still use `pytest`, `ruff`, etc. directly.) |

## Limitations / known gaps

- **Engineer-cost rollup:** subprocess workers don't yet propagate cost back to the parent execution's top-line `total_cost_usd`. (Tracked separately.)
- **Resume + dispatched siblings:** dispatched-but-unstarted nodes at interrupt time are silently orphaned. The dispatcher re-runs but doesn't re-restore. (Engine fix needed.)
- **JSONL log volume mount:** `data/logs/` is not bind-mounted from the host by default — if the worker container is recreated, the JSONL files for completed runs are lost unless `${TEMPER_LOG_DIR}` is set to a mounted path.

## Reading further

- `temper_ai/runner/` — the portable `execute_workflow()` entry point, callable from server / CLI / subprocess
- `temper_ai/spawner/` — spawner ABC, SubprocessSpawner, reaper
- `temper_ai/streaming/` — Redis chunk publisher, subscriber, EventNotifier adapter
- `temper_ai/cli/run_workflow.py` — worker entry point lifecycle (signals, row writes, notifier composition)
- `temper_ai/cli/watch_queue.py` — long-lived watcher daemon (claim semantics, dispatch loop)
- `temper_ai/cli/run_on_server.py` — `temper run`: starts the run with `POST /api/runs` and follows it over the API; nothing runs in the terminal (README "Starting runs")
- `temper_ai/observability/jsonl_logger.py` — per-run JSONL writer
- `temper_ai/worker_proto/` — wire-protocol Pydantic types (RunRequest, ProcessHandle, etc.)
