# Temper AI v1 — Roadmap

## Current State

v1 is a clean rewrite focused on the core engine: composable graph execution, context engineering, and radical modularity. The core is complete with 554+ tests passing.

**What's shipped:**
- Composable graph model (AgentNode + StageNode, recursive)
- One execution engine with topological sort + parallel batching
- 5 LLM providers (OpenAI, vLLM, Ollama, Anthropic, Gemini)
- 5 tools (Bash, Calculator, FileWriter, Git, Http)
- 3 topology strategies (parallel, sequential, leader)
- 3 safety policies (file access, forbidden ops, budget)
- Memory system (mem0 + InMemory backends)
- Jinja2 template prompts with token budget guard
- Dashboard with DAG visualization
- Auto-generated reference docs
- Architecture scanner with extensible rule system

---

## P0 — Blocking for Public Release

### CLI Interface
The only way to run v1 is via `uvicorn`. Need a proper CLI:
- `temper serve` — start the server
- `temper run <workflow> --input key=value` — execute a workflow from terminal
- `temper validate <workflow>` — check configs without running
- `temper config list/import` — manage configs

### CI/CD Pipeline
- GitHub Actions for: lint (ruff), type check (mypy), tests, scanner score gate
- Pre-commit hooks (already have doc generation hook)

---

## P1 — Important for Usability

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

---

## P2 — Advanced Features (Future)

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

## P3 — Nice-to-Have

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
