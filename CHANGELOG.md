# Changelog

All notable changes to Temper AI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Worker Protocol v1 (server + worker split)

Splits orchestration (server) from execution (worker) so engineers in workflows can actually exercise their code (pytest, npm, docker CLI, db clients) without bloating the server image. Opt-in via `TEMPER_EXECUTION_MODE`; default stays in-process so existing users see no change.

- **Three execution modes** — `inprocess` (default, legacy thread-based), `subprocess` (server spawns child in same container), `external` (server only inserts a queued WorkflowRun row; a separate watcher process picks it up). Set via `TEMPER_EXECUTION_MODE` env var.
- **`temper-ai-worker` container** — new compose service (profile-gated, opt-in via `docker compose --profile worker up -d`). Heavier image with curated toolchain: build-essential, libpq-dev, postgres-client, redis-tools, docker-ce-cli, docker-compose-plugin, jq, vim. Runs as non-root `temperai-worker` user. Workspaces mount at host-equivalent paths so engineer agents running `docker compose up` resolve volume mounts correctly through DooD.
- **`temper run-workflow --execution-id <id>`** — CLI subcommand the spawner invokes. Reads a queued `WorkflowRun` row, runs `execute_workflow()`, writes terminal status back. Process-isolated; signal-aware (SIGTERM/SIGINT → cooperative cancel via `cancel_event`).
- **`temper watch-queue`** — long-lived daemon that polls Postgres for queued runs, atomically claims them (race-safe across multiple watchers), spawns workers as subprocesses. Reaper runs in same process for liveness/cancel detection.
- **Live LLM chunk streaming via Redis Streams** — workers (in any container) publish chunks to `temper:chunks:{execution_id}` (MAXLEN ~10k entries, 24h TTL after terminal). Server's WebSocket handler subscribes per-connection and forwards to dashboard. Drop-in for the in-memory bus when worker is out-of-process.
- **Per-run JSONL forensic log** at `${TEMPER_LOG_DIR}/{execution_id}/events.jsonl` — header (workflow name, started_at, runner version, hostname, pid) → events → footer. Missing footer = interrupted run. Tool-call detail (name + truncated arguments) now included in `llm.iteration` events for forensic-time reconstruction.
- **Reaper** — server-side background thread that polls live workers, marks dead/missing-handle runs as `orphaned`, sends SIGTERM on cancel with SIGKILL escalation after 30s grace. Process-group aware (`start_new_session=True` + `os.killpg`) so child processes get cleaned up.
- **`Spawner` ABC + `SubprocessSpawner`** — pluggable backend. Future Docker / k8s_job spawners drop in without touching routes.
- **`POST /api/runs/{id}/cancel`** — now flips `cancel_requested` on `WorkflowRun` for subprocess/external runs; reaper observes and signals. In-process runs still use the legacy `cancel_event` path.

### Removed

- **`_recover_orphaned_runs`** — the startup hook that marked all running `workflow.started` events as `interrupted`. Held over from the in-process era; with workers in separate containers, server restart no longer implies the run died. Reaper handles real worker death via `spawner.is_alive()`.

### Security

- **Bash tool**: Strip all `*_API_KEY`, `*_SECRET`, `*_TOKEN`, `*_PASSWORD` env vars from subprocess — prevents LLM agents from exfiltrating credentials
- **Bash tool**: Fix allowlist bypass via newline — multi-line and chained commands are now individually checked
- **FileEdit/FileAppend**: Add path validation — forbidden system paths and workspace root enforcement, matching FileWriter
- **FileWriter**: Fix path prefix off-by-one — `/workspace` no longer matches `/workspaceevildir`
- Shared path validation module (`_path_utils.py`) for all file tools

### Added

- **Dashboard sidebar** — persistent navigation (Workflows, Studio, Library, Docs) with theme toggle
- **Docs page** — built-in config reference with schema tables, example configs, and registries
- **Re-run button** — re-run a workflow with the same inputs from the execution view
- **Run numbers** — human-readable sequential numbers (e.g., "sprint_opus #7") instead of UUIDs
- **DAG status legend** — border color legend for node status
- **Delete confirmation dialog** — proper AlertDialog modal instead of browser confirm()
- **`--debug` flag** — enables debug logging on all CLI commands
- **`.env` auto-loading** — CLI automatically reads `.env` file
- **`temper validate` provider check** — warns if workflow references an unconfigured provider
- **Makefile** — `make test`, `make lint`, `make serve`, `make build`, etc.
- **Dashboard screenshots** — README now includes DAG execution and Studio screenshots

### Fixed

- **`temper validate` bug** — was creating a second ConfigStore, losing all loaded configs
- **NewRunModal 404** — navigation used `/app/workflow/...` but basename already added `/app`
- **`useBlocker` crash** — migrated from `BrowserRouter` to `createBrowserRouter` (data router)
- **Config loading errors** — no longer silently swallowed, logged with filename
- **MiniMap theme** — colors now use CSS variables, visible in both light and dark mode
- **CSS bug** — `.bg-red-500/20` override used wrong property (`border-color` instead of `background-color`)
- **Status color inconsistency** — `WorkflowSummaryBar` now uses shared `STATUS_COLORS`
- **ThemeToggle** — replaced emoji with Lucide `Sun`/`Moon` icons
- **ErrorBoundary** — `App.tsx` now uses shared component instead of inline duplicate
- **`text-[8px]` readability** — bumped to `text-[9px]` across DAG components

### Changed

- **Example workflows** default to `openai/gpt-4o-mini` instead of `vllm/qwen3-next`
- **`.env.example`** reordered — OpenAI first, Ollama "no API key" callout
- **Docker paths** parameterized — no more hardcoded `/home/shinelay/` in docker-compose
- **Dockerfile** — frontend build stage added, no longer requires pre-built `frontend/dist`
- **Cancelled badge** — amber/orange styling with stop icon instead of plain gray
- **"0 tok" badge** — neutral gray instead of alarming red
- **Workflow list header** — split into two rows for reduced density
- **DAG fit padding** — tighter auto-fit for larger nodes
- **README** — added "Early Access" notice, "What Temper AI is NOT" section, Security Note, Postgres/SQLite docs

## [0.1.0] - 2026-04-06

### Added

- **Workflow engine** — DAG-based execution with topological batching, parallel stages, and conditional branching
- **Agent types** — LLM agents and Script agents
- **5 LLM providers** — OpenAI, Anthropic, vLLM, Ollama, Gemini
- **YAML configuration** — Define agents, workflows, safety policies, and strategies in YAML
- **Tool system** — Bash, FileWriter, FileEdit, FileAppend, Http, Git, WebSearch, Calculator, Delegate
- **Delegate tool** — Agents can spawn sub-agents as visible DAG nodes
- **Loop conditions** — Business-logic loops with structured output evaluation
- **Checkpointing** — Append-only execution history with resume and fork support
- **Safety engine** — ForbiddenOps, FileAccess, and Budget policies
- **Observability** — Event recording for every LLM call, tool invocation, and agent step
- **Web dashboard** — React frontend with DAG visualization, live streaming, agent detail panels
- **CLI** — `temper serve`, `temper run`, `temper validate` commands
- **MCP support** — Connect to MCP servers (SearXNG, Git, Puppeteer) for extended tool access
- **Context management** — Progressive message trimming to stay within model context limits
- **554 tests** across 44 test files
