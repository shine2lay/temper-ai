# Temper AI — Roadmap

## Backlog (Not Yet Implemented)

### Memory System
- [x] Persist memories (`SqlMemoryStore`, now the default backend) — they
      survive restarts, and the worker processes that actually run workflows
- [x] `in_memory` is opt-in and warns that it persists nothing
- [ ] Bundle `mem0ai` in Docker image so semantic memory works out of the box
- [ ] Configure vector DB (ChromaDB or Qdrant) in docker-compose
- [ ] Semantic recall in the SQL backend (today: recency + substring match)
- [ ] Memory viewer in execution view — show what an agent recalled and stored
- [ ] Memory browser — search and manage stored memories across agents
- [ ] Memory config in Workflow Settings overlay (connection string, embedding model)

### Execution Engine
- [ ] Re-run from specific stage (skip completed upstream stages)
- [x] Per-stage timeout enforcement (`timeout_seconds`; verified enforced)
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
- [x] Checkpointing & resume (checkpoints per node; `POST /api/runs/{id}/resume`
      and `/fork`; resume replays the original inputs)
- [x] Human-in-the-loop gates (`gate: true`, approved from the dashboard or
      `POST /api/runs/{id}/approve/{node}`; works across worker processes)
- [ ] Budget pacing & mid-run alerts (track spend rate vs progress, warn when budget consumption outpaces completion)

### DAG Layout
ELK now resolves positions, container sizes and edge routing in one pass, so
the old "estimate heights, then fix them up" problems are gone.

- [x] Auto-fit follows the resolved layout (and stops once the user pans/zooms)
- [x] Skipped nodes are rendered rather than dropped, with a toggle to hide them
- [ ] Same ELK approach for the Studio canvas (still uses `estimateNodeHeight`)

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
<!-- Removed: "structured output persistence". It is persisted — 278,520
     agent.completed events carry structured_output, which is why the DAG,
     the API and the MCP tools can all show it. -->
- [x] Runs left "running" by a restart are resolved at startup. An in-process
      run cannot record its own death, so its status stayed `running` for
      ever. Startup marks them `interrupted` (not `failed`: it was cut off,
      not a failure on its own terms). Narrow by design — in-process mode
      only, only runs older than this process, with a kill switch — because
      the risk is burying a live run, not missing a dead one. Cleared 59
      accumulated orphans on the dev database, two of them 19 hours old.
- [x] A run parked on a gate said "running" beside a banner saying it was
      paused. The header now derives `waiting` for display; the stored
      status is untouched, so the API and MCP keep their meaning.
- [x] Webhook notifications — `TEMPER_WEBHOOK_URL` gets one POST when a run
      reaches a terminal state, carrying status, workflow, duration, cost,
      tokens and the error. Off by default; bounded retries; delivery
      failures are logged and never touch the run's own outcome.
- [x] API authentication — `TEMPER_API_TOKEN` gates the API, the MCP
      endpoint and the WebSocket at the HTTP edge (off by default)
- [ ] Named, revocable per-client tokens (today: one shared token)
- [x] `get_events` MCP tool — the event timeline was websocket-only, so an
      agent could see final states and contents but never the sequence that
      produced them. Summary-first like the rest: 3.3 KB where the raw
      events are 27 KB on a 21-event run.
- [ ] Support the MCP 2.x SDK (pinned to `mcp<2`: v2 renames FastMCP to
      MCPServer and changes other APIs that both `temper_ai/mcp` and the
      MCP tool client are written against)

### Studio
Studio preserves the parts of the workflow schema it cannot edit (they
round-trip untouched), but it still cannot *edit* them:

- [ ] Edit per-agent overrides inside a stage (`name`, `task_template`, `role`)
- [ ] Edit workflow-level `inputs:` / `outputs:` *types*. The names are
      already editable (required/optional lists) and a typed `inputs:` block
      round-trips a no-op save byte-identically — verified on
      ui_dispatch_slowkids, whose `items: {type: array, required: true}`
      survives untouched. What is missing is editing the type and required
      flag from the UI rather than the YAML.
- [ ] An editor for `type: template` nodes (currently read-only passthrough)

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
