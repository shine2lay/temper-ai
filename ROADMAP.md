# Temper AI — Roadmap

## Backlog (Not Yet Implemented)

### Memory System (P0 — currently non-functional)
The current default `InMemoryStore` is useless — it resets on every restart so agents never accumulate expertise. Remove it entirely and make real persistence the only option.

- [ ] Remove `InMemoryStore` — it masks bugs by pretending memory works when it doesn't
- [ ] Make `Mem0Store` the only backend (or use SQLite/Postgres for simple key-value persistence)
- [ ] Bundle `mem0ai` in Docker image so memory works out of the box
- [ ] Configure vector DB (ChromaDB or Qdrant) in docker-compose for persistence
- [ ] When memory is disabled on an agent, it's truly off — no fake store
- [ ] Memory viewer in execution view — show what an agent recalled and stored
- [ ] Memory browser — search and manage stored memories across agents
- [ ] Memory config in Workflow Settings overlay (connection string, embedding model)

### Execution Engine
- [ ] Re-run from specific stage (skip completed upstream stages)
- [ ] Per-stage timeout enforcement (field exists in UI, backend ignores it)
- [ ] Per-stage error handling (continue/halt/retry per stage, not just workflow-level)
- [ ] Convergence detection (similarity-based, not just loop count)
- [ ] Multi-round collaboration (debate, consensus, round-robin strategies)
- [ ] Conflict resolution system (voting, LLM judge, merit-based)
- [ ] Quality gates (min confidence, min findings, citation requirements)
- [ ] Output schema validation (enforce JSON structure from agent output)
- [ ] Output guardrails (content safety checks on agent output)
- [ ] Pre-execution commands (run scripts before agent starts)
- [ ] Merit tracking (agent performance scoring across runs)
- [ ] Persistent agents (maintain state across workflow runs)
- [ ] Checkpointing & resume (persist node outputs to DB at stage boundaries, resume from last checkpoint on crash/restart)
- [ ] Human-in-the-loop gates (pause execution at designated nodes, wait for human approval/input before continuing)
- [ ] Budget pacing & mid-run alerts (track spend rate vs progress, warn when budget consumption outpaces completion)

### DAG Layout (P1 — currently breaks with complex workflows)
The execution DAG layout uses static height estimates that break for multi-agent stages and stages with varying content. Needs a "measure-first, layout-second" approach.

- [ ] Render nodes off-screen first, measure actual DOM dimensions, then compute layout
- [ ] Propagate tall stage heights to adjacent depth columns to prevent vertical overlap
- [ ] Handle empty/skipped stages (0-height nodes) without wasting space
- [ ] Account for I/O sections, source tags, and output previews in height calculations
- [ ] Same approach for Studio canvas layout (currently uses `estimateNodeHeight`)

### Studio UX
- [ ] Undo granularity — batch rapid text edits into single undo entries
- [ ] Input wiring autocomplete — suggest valid source paths from upstream stages
- [ ] Inline validation — real-time field validation as you type
- [ ] Confirmation dialogs for destructive actions (delete stage, remove agent)
- [ ] Agent reordering in multi-agent stages (drag to change execution order)
- [ ] Stage duplication (copy a stage with all its config)
- [ ] YAML import — paste YAML to create/update workflow
- [ ] Workflow templates — pre-built patterns (pipeline, fan-out, review loop)

### Execution View UX
- [ ] Thinking/reasoning content preservation (currently lost after streaming ends)
- [ ] Side-by-side agent output comparison for review stages
- [ ] Agent config diff — compare current config vs what was used in a run

### Infrastructure
- [ ] Structured output persistence — `structured_output` not stored in event DB
- [ ] Stale run auto-cleanup on server restart (mark orphaned "running" as failed)
- [ ] Webhook notifications for workflow completion/failure
- [ ] API authentication (currently open)

## Recently Completed

### This Session
- Prompt rendering fix — `{{ other_agents }}` was rendering as `None`
- LLM pricing updated (30+ models across 9 providers)
- 80+ phantom UI fields removed (backend doesn't implement them)
- Agent serializer structural mismatch fixed (top-level vs nested fields)
- Light mode contrast overhaul
- YAML preview with annotations and download bundle
- MCP server discovery in registry
- Structured output demo workflow with conditional branching
- SmartContent renderer (JSON tree, markdown, code with line numbers)
- Global output search on DAG
- Export workflow as Markdown report
- 15+ execution view UI improvements
- 15+ studio UI improvements
- 8 audit agent reports with 30+ bug fixes
