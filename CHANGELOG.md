# Changelog

All notable changes to Temper AI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- **Agent types** — LLM agents, Script agents, and Claude Code agents
- **5 LLM providers** — OpenAI, Anthropic, vLLM, Ollama, Claude Code CLI
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
