# Temper AI v1 — Roadmap

## Current State

v1 is a clean rewrite focused on the core engine: composable graph execution, context engineering, and radical modularity. The core is complete with 554+ tests passing.

**What's shipped:**
- Composable graph model (AgentNode + StageNode, recursive)
- One execution engine with topological sort + parallel batching
- 5 LLM providers (OpenAI, vLLM, Ollama, Anthropic, Gemini)
- 9 tools (Bash, Calculator, FileWriter, FileEdit, FileAppend, Git, Http, WebSearch, Delegate)
- 3 topology strategies (parallel, sequential, leader)
- 3 safety policies (file access, forbidden ops, budget)
- Memory system (mem0 + InMemory backends)
- Jinja2 template prompts with token budget guard
- Dashboard with DAG visualization, Studio editor, Library, Docs
- Checkpoint/resume/fork system
- Delegate tool for mid-agent sub-task spawning
- MCP tool integration (connect to external MCP servers)
- Loop conditions with structured output evaluation
- Sprint workflow (domain-agnostic iterative execution)
- Auto-generated reference docs
- CI pipeline (lint, typecheck, test with Python 3.11+3.12)
- 725+ tests

---

## P0 — Next Up

### CI/CD Pipeline
- GitHub Actions for: lint (ruff), type check (mypy), tests, quality check
- Add when going public — 30 min of YAML, structure mirrors main codebase

### Config Management API
Full CRUD for configs via REST:
- POST/PUT/DELETE /api/configs
- Import/export YAML
- Fork existing configs

### Database Migrations
- Alembic setup for schema evolution
- Migration scripts for observability tables

### Cancel Endpoint
- POST /api/runs/{id}/cancel — graceful workflow cancellation
- Already has threading.Event plumbing, needs the route + executor integration

### MCP Tool Integration
**What:** Agents can use any MCP server as a tool source. The MCP ecosystem (11,000+ servers) becomes Temper's tool library — web search, database access, browser automation, and more — without building each tool natively.

**How:** A single `MCPToolBridge` class wraps any MCP tool as a `BaseTool`. MCP tools use JSON Schema for parameters — same as our tools. The bridge translates between the two. Agents don't know or care whether a tool is native or MCP.

```yaml
# Agent references MCP tools alongside built-in tools
agent:
  name: researcher
  tools: [Calculator]                                  # built-in
  mcp_tools: [exa.web_search, firecrawl.scrape]        # from MCP servers
```

**Server config (infrastructure-level, not in workflow YAML):**
MCP servers are configured at the server level like LLM providers. API keys live in `.env`, never in workflow YAML. The `substitute_env_vars()` pipeline handles resolution.

**What stays the same:**
- Safety policies still gate every MCP tool call
- Events still recorded in the same event stream
- Observable in dashboard and CLI
- Token budgets still enforced

**Effort:** Medium. Needs MCP client library, server lifecycle management, and the bridge class. The tool interface already matches MCP's — the mapping is nearly 1:1.

**High-value MCP servers to support first:**
- Exa (semantic web search) — researchers get real search
- Firecrawl (web crawling) — agents can read web pages
- DBHub (database access) — agents can query data
- Fetch (simple URL fetching) — free, no API key

---

## P2 — Agentic Capabilities

Move Temper from a workflow engine (code decides the path) toward an agentic system (model decides the path). The goal: **structured autonomy** — the developer defines the possible paths, the model chooses which one at runtime, and every decision is observable.

### Dynamic Routing — Model Decides Next Step ✓ SHIPPED (as Dynamic Dispatch)

**What shipped:** An agent's output (structured or tool-calls) can add, remove, and replace pending nodes in the running DAG. Strictly more general than the original "pick a path" proposal — the agent can construct arbitrary subgraphs (including stages), fan out per-item with `for_each`, build fan-in depends_on lists from its output, and insert nodes between existing ones.

```yaml
agent:
  name: planner
  dispatch:
    - op: add
      for_each: structured.subtopics        # agent-decided fan-out
      node:
        name: "research_{{ item.slug }}"
        agent: researcher
        input_map: {topic: "{{ item.slug }}"}
    - op: remove
      target: placeholder_body              # drop pre-existing node
    - op: add                               # replace it with real content
      node:
        name: placeholder_body
        agent: researcher
```

**Two tiers:** declarative (`dispatch:` block, Jinja-rendered against agent output) and imperative (`AddNode` / `RemoveNode` tools). Plus script-agent dispatch with zero LLM cost on the dispatcher.

**Safety:** cap-enforced (max_children_per_dispatch, max_dispatch_depth, max_dynamic_nodes, cycle_detection), resume-safe (checkpointed + replayed), observable (`dispatch.applied` / `dispatch.cap_exceeded` events).

**Demos:** `configs/workflows/demo_dispatch*.yaml`. Reference: `llms.txt` §13b.

---

### Delegate Tool — Agent Calls Sub-Agent
**What:** A `delegate` tool that lets an agent call another agent inline and get the result back. The parent agent decides when to delegate and what context to pass.

```yaml
agent:
  name: tech_lead
  tools: [delegate]    # can call other agents
  system_prompt: |
    You can delegate tasks to specialists. Available agents:
    - security_reviewer: reviews code for vulnerabilities
    - performance_analyst: identifies performance bottlenecks
```

The LLM decides at runtime: "I should get a security review on this code" → tool call → sub-agent runs → result returns as tool response → parent continues.

**Why:** This is how Claude Code, CrewAI, and smolagents implement multi-agent coordination. The model decides when to delegate — not the YAML config. Industry standard pattern: sub-agents are tools in the parent's tool list.

**Context model (push + pull):**
- **Push:** The parent provides task + explicit context in the tool call (like `input_map` but decided by the model at runtime)
- **Pull:** The sub-agent can query shared run context if it needs more (see Shared Run Context below)

**Integration point:** A new tool that wraps `create_agent()` + `agent.run()`. Uses the same ExecutionContext, same safety policies, same event recorder.

---

### Shared Run Context — Push + Pull Knowledge Base
**What:** A run-scoped shared context that any agent in the workflow can write to and query from. Agents receive explicit inputs via `input_map` (push), but can also search shared context when they need more information (pull).

**Push (what agent receives automatically):**
```yaml
input_map:
  task: plan.output           # explicit, developer-wired
  code: coder.output          # explicit, developer-wired
```

**Pull (agent queries when it decides it needs more):**
```
Agent thinking: "I need to know what the security reviewer flagged"
Tool call: query_context(query="security constraints and findings")
→ Returns relevant entries from shared run context
```

**Why:** Mirrors how humans work — you get briefed on your task (push), but you can check shared docs when you discover you need more (pull). Avoids token explosion from injecting everything into every agent's prompt.

**Implementation:** Run-scoped memory using the existing mem0/InMemory backend. Same semantic search, just scoped to the current `execution_id`. Agents with `store_observations: true` write to it; agents with `query_context` tool can read from it.

```yaml
workflow:
  context:
    shared: true

agent:
  name: researcher
  tools: [query_context]        # can pull from shared context
  memory:
    store_observations: true    # writes findings to shared context
```

**What exists today:** Memory service already supports scoped recall. The `query_context` tool would be `memory_service.recall()` scoped to `run:{execution_id}` instead of `project:{workspace}`.

---

### Swappable Execution Engines
**What:** Add `engine:` field to workflow config. The YAML stays the same; the compiler translates it to the selected engine. Native engine (current) or LangGraph (future).

```yaml
workflow:
  engine: native              # or "langgraph" 
  engine_config:
    langgraph:
      checkpointer: sqlite
      interrupt_before: [review]
```

**Why:** Users who prefer LangGraph's execution model (checkpointing, human-in-the-loop interrupts, time travel) can use it without rewriting their workflows.

**What exists today:** `execute_graph()` is already isolated — wrapping it in an engine class and adding a registry is straightforward. Validation would split into shared (loader) and engine-specific layers.

---

### Checkpoint / Resume — Save and Resume Workflow State
**What:** Save the execution state at any point during a workflow run. Resume from that checkpoint later — same inputs, same partial results, continue from where it stopped.

**Why:** Long-running workflows (SDLC pipelines, multi-stage research) can fail midway through. Without checkpoints, you restart from scratch — wasting all the LLM calls and tool executions that already succeeded. With checkpoints, you resume from the last successful node.

**How it could work:**
```bash
# Workflow fails at node 8 of 11
temper run sdlc_deploy_test --input task="Add auth"
# → Nodes 1-7 completed, node 8 failed

# Resume from checkpoint
temper resume <execution_id>
# → Skips nodes 1-7, re-runs from node 8
```

**Implementation:** The events table already stores all node results. A resume would:
1. Load the execution's events
2. Reconstruct `node_outputs` from completed node events
3. Re-run `execute_graph()` starting from the failed batch
4. The executor already skips nodes with existing outputs

**Integration point:** Stage executor — add a `resume_from` parameter that pre-populates `node_outputs`.

**Also enables:**
- Human-in-the-loop: pause before a sensitive node (like git push), let user approve, then resume
- Debugging: re-run a single failed node with modified inputs
- Cost savings: don't re-run expensive LLM calls that already succeeded

---

## P3 — Advanced Features (Future)

These features exist in the main codebase. They're potential improvements, not core requirements. Each is self-contained and can be added independently.

### Experimentation — A/B Testing for Workflows
**What:** Run multiple variants of a workflow (different prompts, models, configs) and statistically compare results. Variant assignment strategies (random, hash, bandit). t-tests, confidence intervals, early stopping.

**Why:** Core to the vision of "experiment with different use cases." Lets users answer: "Is GPT-4o or Claude better for my code review agent?" with data, not guessing.

**Integration point:** Workflow execution — assign variant before run, merge config overrides, collect metrics after.

**Effort:** Medium. The architecture is clean (ExperimentService, VariantAssigner, StatisticalAnalyzer). Needs DB tables and a few API endpoints.

---

### Plugin System — External Agent Frameworks
**What:** Adapter framework for running CrewAI, LangGraph, OpenAI Agents SDK, and AutoGen agents inside Temper workflows. Each adapter translates config and execution between frameworks.

**Why:** Users shouldn't have to rewrite agents to use Temper. Bring your existing CrewAI crew or LangGraph graph and orchestrate it alongside native Temper agents.

**Integration point:** Agent registry — register a plugin adapter as an agent type. `type: crewai` or `type: langgraph` in YAML.

**Effort:** Medium per adapter. Base class (ExternalAgentPlugin) is straightforward. Each framework adapter is independent work.

---

### Self-Improvement Loop — Learning + Goals + Autonomy
**What:** Three modules that work together:
1. **Learning** — mines execution history for patterns (slow agents, failing models, cost anomalies). Five specialized miners.
2. **Goals** — proposes improvements from patterns with scored priorities (impact × confidence + effort_inverse).
3. **Autonomy** — orchestrates the post-execution loop: learn → propose goals → apply approved changes → sync to memory.

**Why:** No other framework does this. The system gets better over time without manual tuning. A `FeedbackApplier` writes config changes with safety gates (risk-based gating, rollback on degradation).

**Integration point:** Post-execution hook in the workflow runner. All three modules are opt-in via config.

**Effort:** Large. These are tightly coupled (goals depends on learning, autonomy orchestrates both). Port as a package deal. Needs execution history tables populated first.

---

### Lifecycle Adaptation — Self-Modifying Workflows
**What:** Pre-execution adaptation of workflow configs based on project characteristics (size, risk, complexity). Classifies the project, selects a profile, applies adaptation rules (skip stages, add stages, modify configs). Has rollback monitoring that disables profiles if quality degrades.

**Why:** A code review workflow for a 10-line script doesn't need the same stages as a 10,000-line refactor. The workflow adapts itself.

**Integration point:** Pre-compilation hook in the loader. Runs before `GraphLoader.load_workflow()`.

**Effort:** Medium. The adapter pattern is clean. Needs Jinja2 condition evaluation and a profile registry.

---

### Prompt Optimization — DSPy Integration
**What:** Composable optimization pipeline with DSPy for prompt compilation. Collects training examples from execution history, builds DSPy modules (Predict, ChainOfThought), compiles with BootstrapFewShot or MIPRO.

**Why:** Automated prompt engineering. Instead of manually tweaking `task_template`, the system compiles an optimized prompt from examples.

**Integration point:** Optimization registry + autonomy orchestrator (when `prompt_optimization_enabled`).

**Effort:** Medium. DSPy is an optional dependency. The pipeline architecture (evaluators + optimizers) is extensible.

---

### Portfolio Management — Multi-Product Orchestration
**What:** Manages multiple products/workflows as a portfolio. Generates 4-metric scorecards (success rate, cost efficiency, trend, utilization). Classifies products as INVEST/MAINTAIN/REDUCE/SUNSET. Knowledge graph for cross-product visibility.

**Why:** Enterprise feature for teams running many workflows. Answers: "Which workflows are worth investing in?"

**Integration point:** Post-execution hook (records product runs) + dashboard (scorecard visualization).

**Effort:** Medium. Self-contained module. Lower priority for community/OSS release.

---

## P4 — Nice-to-Have

### Additional Scanner Rules
- Import density (fan-out/fan-in analysis)
- Layer violation detection (configurable layer map)
- Radon complexity integration
- Test coverage tracking
- Magic number detection (with better false-positive filtering)

### Additional Tools
- WebSearch tool
- Database query tool
- Image generation tool

### Additional Strategies
- Debate topology (agents argue until consensus)
- Voting topology (majority wins)
- Iterative refinement (agent refines own output N times)

### Additional Providers
- AWS Bedrock
- Azure OpenAI
- Groq
- Together AI

### Documentation
- Architecture guide (how modules fit together)
- Tutorial (build your first workflow)
- Configuration reference (full YAML schema)
- Contributing guide
