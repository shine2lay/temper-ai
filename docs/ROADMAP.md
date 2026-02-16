# Revised Roadmap: Path to Autonomous Product Companies

**Version:** 2.0
**Date:** 2026-02-15
**Status:** Active

---

## Quick Links

- **[Vision Document](./VISION.md)** — Philosophical foundation and ultimate goals
- **[Milestone Reports](./milestones/)** — Completed milestone documentation
- **[Quality Roadmap](./ROADMAP_TO_10_OUT_OF_10.md)** — Path to production excellence

---

# Part 1: Strategic Roadmap

## Where We Are

The framework has a solid foundation. Four milestones are complete, quality is at 100/100 (A+), and the observability stack has been expanded across three phases. M5 self-improvement code exists but is not wired into the main execution pipeline.

**Completed:**

| Milestone | What It Delivered |
|-----------|-------------------|
| M1: Core Agent System | Agent foundation, tool system, observability infrastructure |
| M2: Workflow Orchestration | LangGraph compiler, stage-based execution, YAML config |
| M2.5: Execution Engine Abstraction | Engine interface, LangGraph adapter, engine registry |
| M3: Multi-Agent Collaboration | Parallel execution, voting/consensus/debate/hierarchical strategies, merit-weighted resolution |
| M4: Safety & Governance | Policy composition, approval workflows, rollback, circuit breakers, safety gates |

**Post-Milestone Improvements:**

- Domain-based modular monolith migration (23 technical-layer modules to 13 domain-based modules)
- Quality score 85 to 100/100 (A+) with zero deductions
- LLMService extraction (clean separation of LLM call lifecycle)
- Observability: structured logging, OpenTelemetry, error fingerprinting, resilience tracking, cost rollup, data lineage, prompt versioning
- Parallel test execution (pytest-xdist), architecture scanner v2.4.0

**Available Foundation:**

- `src/experimentation/` — production-ready A/B testing engine (v1.0.0, 101 tests): experiment lifecycle, variant assignment (hash/random), statistical analysis (t-test, SPRT, Bayesian), guardrails, config merging with security validation
- `src/observability/merit_score_service.py` — agent merit scoring (not connected to safety)

**Scheduled for Removal:**

- `src/self_improvement/` — ~50 files of speculative M5 loop code, never battle-tested. The ideas (5-phase loop, strategy registry, pattern mining) are preserved in this roadmap as design reference. The experiment engine portion is redundant with `src/experimentation/`. Will be deleted when M5.1 starts; the loop will be rebuilt fresh and thin on top of `src/experimentation/`

---

## Phase I: Intelligence Layer (M5)

**Value Proposition:** The framework stops being a static executor and becomes a learning system. Agents remember past work, improve over time, and proactively apply lessons learned.

**Key Capabilities:**
- Self-improvement loop runs automatically after each workflow
- Agents have episodic, procedural, and cross-session memory
- System recommends optimal configurations based on history
- Background pattern mining surfaces actionable insights

**How It Changes User Experience:**
- Repeated problem types get solved faster and better
- "You're building auth — here's what worked in 3 previous projects"
- System auto-tunes its own configuration based on outcomes
- Quality improves measurably over time without manual intervention

---

## Phase II: Adaptive Operations (M6)

**Value Proposition:** The framework earns trust incrementally and becomes accessible as a service. Agents gain autonomy based on track record, and external products can trigger workflows via API.

**Key Capabilities:**
- Progressive autonomy — agents earn trust, human intervention decreases
- MAF Server — REST/WebSocket API for external integration
- Multi-product templates — pre-built workflow configs per product type
- Runtime budget enforcement and emergency stop

**How It Changes User Experience:**
- Low-risk operations run without approval; high-risk operations require it
- Products trigger MAF workflows via HTTP instead of CLI
- Start a new project from a proven template, customize from there
- Trust is visible — see exactly why an agent has its autonomy level

---

## Phase III: Autonomous Systems (M7)

**Value Proposition:** The framework moves from executing human-defined workflows to adapting and proposing its own. It manages multiple products, allocates resources, and generates strategic recommendations.

**Key Capabilities:**
- Self-modifying workflows — DAG structure adapts to project characteristics
- Strategic autonomy — system proposes improvements and opportunities
- Portfolio management — orchestrate multiple products simultaneously
- Cross-product learning — insights from one product benefit all others

**How It Changes User Experience:**
- "Based on 50 past projects, I recommend skipping formal design for this small task"
- "I noticed a pattern in your auth code — should I apply this fix across all products?"
- Human role shifts from orchestrator to strategic reviewer

---

# Part 2: Technical Execution Plan

## M5: Self-Improvement & Learning (Q1-Q2 2026)

### M5.1: Loop Activation (~3-4 weeks)

Delete `src/self_improvement/` (untested, speculative) and build a fresh, thin self-improvement loop on top of the proven `src/experimentation/` engine.

**Deliverables:**
- Delete `src/self_improvement/` and its tests; remove M5-specific DB tables (`m5_experiments`, `m5_experiment_results`, `m5_loop_state`)
- Build new loop orchestrator (~100-200 lines) in `src/improvement/` with 3 phases: Detect, Experiment, Deploy
- **Detect:** Query `src/observability/tracker.py` for performance regressions (quality drop, cost spike, error rate increase) against stored baselines
- **Experiment:** Delegate to `src/experimentation/ExperimentService` for A/B testing — gains SPRT early stopping, Bayesian analysis, and guardrails for free
- **Deploy:** Thin deployer that applies winning config through M4 safety (`ActionPolicyEngine`) with rollback on regression
- First concrete strategy: prompt optimization (one strategy, validated end-to-end, not four speculative ones)
- Hook into `src/workflow/workflow_executor.py` as post-workflow callback
- Configuration flag to enable/disable per workflow

**Key Files:**
- New `src/improvement/` module (loop orchestrator, detector, deployer, first strategy)
- `src/experimentation/` (experiment engine — used as-is)
- `src/workflow/workflow_executor.py` (integration point)
- `src/observability/tracker.py` (outcome data source)

**Success Criteria:**
- M5 loop runs automatically after workflow execution
- Detects performance regressions and proposes improvements
- Experiments run via `ExperimentService` with statistical rigor (SPRT, guardrails)
- Zero degradations from bad improvements (rollback works)
- Total new code < 500 lines (excluding tests)

**Dependencies:** None (builds on M4 foundation + existing `src/experimentation/`)

---

### M5.2: Agent Memory (~4-6 weeks)

Give agents persistent memory across sessions and workflow runs.

**Deliverables:**
- **Episodic memory:** Vector embeddings over past workflow executions with semantic search ("what happened last time we built auth?")
- **Procedural memory:** Context-aware pattern store ("for fintech products, always include these checks")
- **Cross-session memory:** Per-agent memory table, inject relevant past experiences into prompts at runtime
- New `src/memory/` module with clean interfaces for each memory type
- Memory retrieval integrated into agent prompt construction in `src/agent/standard_agent.py`

**Key Files:**
- New `src/memory/` module (episodic, procedural, cross-session stores)
- `src/observability/tracker.py` (outcome data source)
- `src/agent/standard_agent.py` (memory injection into prompts)

**Success Criteria:**
- Agents reference past projects in their reasoning
- Quality improves measurably on repeated problem types
- Memory retrieval adds < 500ms to agent startup

**Dependencies:** M5.1 (needs outcome data flowing from the loop)

---

### M5.3: Continuous Learning (~3-4 weeks)

Background pattern mining and proactive recommendations from execution history.

**Deliverables:**
- Background pattern mining job that analyzes execution history for recurring patterns
- Proactive recommendation engine ("you're building auth, here's what worked before")
- Learning dashboard: visualize what the system has learned, confidence levels, pattern quality
- Auto-tune: system recommends optimal configs (model, strategy, timeout) per project type
- Convergence detection: stop learning when no new insights emerge

**Key Files:**
- `src/improvement/` (pattern mining logic)
- `src/observability/tracker.py` (execution history source)
- `src/interfaces/dashboard/` (learning visualization)

**Success Criteria:**
- Recommendations improve measurably over 50 workflow runs
- Pattern mining discovers 10+ actionable heuristics
- Auto-tune recommendations match or exceed manual tuning
- < 5% cost increase from learning overhead

**Dependencies:** M5.2 (needs memory layer for storing/retrieving patterns)

---

## M6: Adaptive Operations (Q2-Q3 2026)

### M6.1: Progressive Autonomy (~6-8 weeks)

Agents earn trust incrementally based on track record. Safety policies adapt to demonstrated reliability.

**Deliverables:**
- `AutonomyLevel` enum (Supervised, Spot-Checked, Risk-Gated, Autonomous, Strategic) in agent config
- Merit-safety integration: connect `AgentMeritScore` from `src/observability/merit_score_service.py` to `ActionPolicyEngine`
- Risk-based approval routing: CRITICAL requires multi-approver, HIGH requires single approver, MEDIUM uses probabilistic sampling
- Dynamic trust escalation and de-escalation based on rolling track record
- Emergency stop controller (global halt capability across all agents)
- Runtime budget enforcement (pre-action cost estimation and caps)
- Shadow mode: new autonomy levels run in shadow alongside current approval flow before going live

**Key Files:**
- `src/safety/` (policy engine, approval workflows)
- `src/observability/merit_score_service.py` (merit scoring)
- `src/storage/schemas/agent_config.py` (autonomy level config)

**Success Criteria:**
- Human intervention rate decreases 30%+ for agents that have earned trust
- Zero safety incidents from autonomy escalation (shadow mode catches issues)
- Emergency stop halts all operations within 5 seconds
- Budget enforcement prevents cost overruns

**Dependencies:** M5.1 (needs outcome tracking for merit calculation)

---

### M6.2: MAF Server (~4-6 weeks)

Expose the framework as an API service that external products can integrate with.

**Deliverables:**
- `WorkflowRunner` library API with `on_event` callback for programmatic embedding
- FastAPI server wrapping `WorkflowRunner` (REST endpoints + WebSocket event streaming)
- Workspace isolation: L1 path restriction (immediate), L3 container isolation (production)
- Run management: queue, execute, cancel, history, status
- Event streaming to external consumers via WebSocket
- CLI extensions: `maf serve`, `maf trigger`, `maf status`, `maf logs`
- PostgreSQL migration path for multi-user scenarios (SQLite remains default)

**Key Files:**
- `src/interfaces/server/` (existing directory, expand with FastAPI app)
- `src/workflow/workflow_executor.py` (WorkflowRunner extraction)

**Success Criteria:**
- Products can trigger MAF workflows via HTTP API
- Server handles 10+ concurrent workflow runs
- WebSocket delivers real-time execution events
- Workspace isolation prevents cross-run interference

**Dependencies:** None (can parallelize with M6.1)

---

### M6.3: Multi-Product Templates (~4-6 weeks)

Product type as a configuration parameter with pre-built workflow templates.

**Deliverables:**
- Product type parameter in workflow config (`web_app`, `api`, `data_pipeline`, `cli_tool`, etc.)
- Template registry with product-specific agent/tool/stage presets
- New `configs/templates/` directory with proven workflow templates
- Product-specific quality gates and validation rules
- Template inheritance: start from base, override per product type

**Key Files:**
- New `configs/templates/` directory
- `src/workflow/config_loader.py` (template resolution and merging)

**Success Criteria:**
- 3+ product types supported with end-to-end workflow templates
- New project bootstraps in under 5 minutes using a template
- Product-specific quality gates catch type-relevant issues

**Dependencies:** M6.2 (needs server for deployment-oriented templates)

---

## M7: Autonomous Systems (Q4 2026 - Q2 2027)

### M7.1: Self-Modifying Lifecycle (~6-8 weeks)

Workflows adapt their own structure based on project characteristics and historical outcomes.

**Deliverables:**
- Runtime workflow DAG modification: add, remove, reorder, and update stages during execution
- Dynamic lifecycle selection based on project size, type, and risk profile
- Lifecycle experimentation: A/B test different stage sequences for the same project type
- Rollback mechanism: revert DAG changes if quality metrics degrade

**Key Files:**
- `src/workflow/langgraph_compiler.py` (DAG construction)
- `src/workflow/workflow_executor.py` (runtime modification hooks)
- `src/workflow/engine_registry.py` (engine-level adaptation)

**Success Criteria:**
- System adapts workflow structure based on project type and past outcomes
- Small projects automatically skip heavyweight stages
- A/B tests demonstrate measurable improvement from adaptive lifecycles

**Dependencies:** M5.3 (needs learning data for adaptation decisions), M6.1 (needs progressive autonomy for safe self-modification)

---

### M7.2: Strategic Autonomy (~8-10 weeks)

The system proposes improvements and opportunities, not just executes instructions.

**Deliverables:**
- Goal proposal framework: system generates opportunity hypotheses from execution data
- Goal-level safety policies and approval workflows (separate from action-level)
- Autonomous analysis agents: codebase scanning for improvement opportunities
- Cross-product learning: insights from Product A available to Product B

**Key Files:**
- `src/improvement/` (proposal generation)
- `src/safety/` (goal-level policies)
- `src/memory/` (cross-product memory)

**Success Criteria:**
- System proposes actionable improvements with 50%+ human acceptance rate
- Cross-product insights reduce duplicate effort
- Goal proposals include risk assessment, effort estimate, and expected impact

**Dependencies:** M7.1 (needs adaptive lifecycle), M5.2 (needs memory for cross-product learning)

---

### M7.3: Portfolio Management (~8-10 weeks)

Manage multiple products simultaneously with autonomous resource allocation.

**Deliverables:**
- Multi-product orchestration: manage N products with shared infrastructure
- Resource allocation engine: distribute compute/agent time across products by priority
- Cross-product component sharing: identify and extract reusable components
- Portfolio optimization: recommend sunset/invest decisions based on metrics
- Partial knowledge graph: semantic memory of domain concepts and technology compatibility

**Key Files:**
- `src/workflow/workflow_executor.py` (multi-product scheduling)
- `src/memory/` (knowledge graph store)
- `src/observability/` (portfolio-level metrics)

**Success Criteria:**
- System manages 3+ products with autonomous resource allocation
- Cross-product component sharing reduces build time for new products
- Portfolio recommendations align with human strategic intent

**Dependencies:** M7.2, M6.3

---

# Part 3: VCS Parallel Track

The Vibe Coding Squad (VCS) pipeline runs as a parallel effort, with integration checkpoints where framework milestones unlock VCS capabilities.

### V1: Pipeline Foundation (Current — ~90% complete)

- All 18 agents, 7 stages, and workflow config exist in `configs/`
- Remaining work: enable conditional stage bypass, end-to-end testing with a real LLM

### V2: Web Application (~3-4 weeks)

- Complete FastAPI app (routes, models, frontend) for VCS
- Embedded MAF `WorkflowRunner` or MAF Server client for pipeline execution
- Pipeline event storage and activity feed UI
- WebSocket live updates during triage
- **Dependencies:** M6.2 (MAF Server) or embedded `WorkflowRunner` approach

### V3: Self-Improving VCS (~2-3 weeks)

- VCS uses M5 loop to improve its own triage accuracy over time
- Triage quality measured, experiments run automatically
- Agents learn from past triage decisions via memory layer
- **Dependencies:** M5.1 (loop activation), M5.2 (agent memory)

### V4: Autonomous VCS (~4-6 weeks)

- VCS proposes features, not just triages user suggestions
- Analyzes codebase for improvement opportunities
- Progressive autonomy: earns trust for auto-implementing low-risk improvements
- **Dependencies:** M6.1 (progressive autonomy), M7.2 (strategic autonomy)

---

## Integration Checkpoints

| Framework Milestone | VCS Unlock | What It Enables |
|---------------------|------------|-----------------|
| M5.1 Loop Activation | V3 | VCS can self-improve triage accuracy |
| M5.2 Agent Memory | V3 | Agents remember past triage patterns |
| M6.1 Progressive Autonomy | V4 | VCS earns trust for auto-implementation |
| M6.2 MAF Server | V2 | VCS web app triggers pipelines via API |
| M7.2 Strategic Autonomy | V4 | VCS proposes features autonomously |

---

# Part 4: Timeline

```
2026 Q1 (Now)     M5.1 Loop Activation
2026 Q1-Q2        M5.2 Agent Memory + M5.3 Continuous Learning
2026 Q2            V2 VCS Web App + V3 Self-Improving VCS
2026 Q2-Q3        M6.1 Progressive Autonomy || M6.2 MAF Server (parallel)
2026 Q3            M6.3 Multi-Product Templates + V4 Autonomous VCS
2026 Q4            M7.1 Self-Modifying Lifecycle
2027 Q1            M7.2 Strategic Autonomy
2027 Q2            M7.3 Portfolio Management
```

## Milestone Dependency Graph

```
M5.1 Loop Activation
 ├──→ M5.2 Agent Memory
 │     ├──→ M5.3 Continuous Learning
 │     │     └──→ M7.1 Self-Modifying Lifecycle ──→ M7.2 Strategic Autonomy ──→ M7.3 Portfolio Management
 │     └──→ M7.2 Strategic Autonomy
 └──→ M6.1 Progressive Autonomy
       └──→ M7.1 Self-Modifying Lifecycle

M6.2 MAF Server (independent)
 └──→ M6.3 Multi-Product Templates ──→ M7.3 Portfolio Management
```

All dependencies are acyclic. M6.2 is fully independent and can run in parallel with any M5 or M6.1 work.

---

# Part 5: Deferred / Out of Scope

Items from the [Vision Document](./VISION.md) explicitly deferred:

| Vision Item | Status | Rationale |
|-------------|--------|-----------|
| Visual Workflow Builder (drag-drop UI) | Deferred to post-M7 | Requires stable workflow API; low demand vs. YAML config |
| Department Expansion (Design, Marketing, Support) | Deferred to post-M7 | Engineering-first; other departments depend on mature M7 |
| Regulatory compliance automation | Deferred | Enterprise feature; needs production deployment baseline |
| Autonomous incident response | Deferred | Needs production deployment and ops maturity first |
| Plugin marketplace with ratings | Deferred | Needs community and ecosystem to justify |
| Full knowledge graph (semantic memory) | Partial in M7.3 | Full implementation deferred; start with domain concepts |
| Multi-stakeholder orchestration | Deferred | Enterprise feature; single-user focus through M7 |
| Competitive intelligence service | Deferred | Requires real product deployment and market presence |
| Agent specialization evolution | Implicit in M5-M6 | Emerges naturally from learning and merit; no dedicated milestone |

---

# Part 6: Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| SQLite bottleneck at scale | Performance degradation under concurrent load | Medium | PostgreSQL migration path planned in M6.2 |
| Speculative M5 code as tech debt | 50 files of untested code blocking fresh design | High | Delete `src/self_improvement/` in M5.1, rebuild thin loop on `src/experimentation/` |
| Vector search adds new dependency | Increased complexity, deployment friction | Medium | Start with simple embedding (numpy), upgrade to dedicated vector DB later |
| Progressive autonomy safety gaps | Trust erosion if agent causes harm | Medium | Shadow mode, conservative defaults, feature flags, emergency stop |
| Runtime DAG modification complexity | Workflow instability, hard-to-debug failures | High | Extensive testing, rollback mechanisms, shadow execution |
| LLM cost explosion in continuous loop | Budget overrun from unbounded experimentation | Medium | Budget enforcement in M6.1, convergence detection in M5.3 |
| Memory retrieval latency | Agent startup slowdown from memory queries | Low | Cache hot paths, async prefetch, latency budget (< 500ms) |

---

# Part 7: Success Metrics

### M5 Success

- 20%+ improvement in agent performance after self-improvement cycles
- Agents reference past projects in reasoning (verifiable in traces)
- Pattern mining discovers 10+ actionable heuristics
- < 5% cost increase from experimentation overhead
- Convergence within 100 experiments per hypothesis

### M6 Success

- Human intervention rate decreases 30%+ for trusted agents
- MAF Server handles 10+ concurrent workflow runs
- 3+ product type templates with end-to-end workflows
- Emergency stop halts all operations within 5 seconds
- Budget enforcement prevents cost overruns in 100% of cases

### M7 Success

- System proposes improvements with 50%+ human acceptance rate
- Manages 3+ products with autonomous resource allocation
- Workflow structure adapts based on project characteristics (measurable via A/B test)
- Cross-product insights reduce duplicate effort by 20%+

### VCS Success

- Triage accuracy improves over time (measurable via M5 loop)
- End-to-end suggestion-to-code-change pipeline works reliably
- Users can watch agent reasoning in real-time via WebSocket
- VCS proposes features that humans accept at 30%+ rate

---

## Related Documentation

- [Vision Document](./VISION.md) — Long-term philosophical vision
- [Quality Roadmap](./ROADMAP_TO_10_OUT_OF_10.md) — Path to 10/10 codebase
- [Milestone Reports](./milestones/) — Completed milestone documentation
- [Documentation Index](./INDEX.md) — All documentation

---

**Last Updated:** 2026-02-15
