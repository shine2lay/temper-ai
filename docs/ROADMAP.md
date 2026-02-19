# Revised Roadmap: Path to Autonomous Product Companies

**Version:** 2.3
**Date:** 2026-02-16
**Status:** Active

---

## Quick Links

- **[Vision Document](./VISION.md)** — Philosophical foundation and ultimate goals
- **[Milestone Reports](./milestones/)** — Completed milestone documentation
- **[Quality Roadmap](./ROADMAP_TO_10_OUT_OF_10.md)** — Path to production excellence

---

# Part 1: Strategic Roadmap

## Where We Are

The framework has a solid foundation. Thirteen milestones are complete (M1-M4 + M5.1-M5.3 + M6.1-M6.3 + M7.1-M7.3), quality is at 100/100 (A+), and the optimization engine is wired into the CLI execution pipeline. Agents now have persistent memory with SQLite persistence, time-decay relevance, LLM-based procedural extraction, and cross-agent shared namespaces. The framework is exposed as an API service with REST endpoints, WebSocket streaming, persistent run history, CLI client commands, and API key authentication. Background pattern mining continuously discovers actionable heuristics from execution history, with auto-tune recommendations and convergence-aware scheduling. Workflows adapt their own structure based on project characteristics, and the system proposes strategic improvements with risk assessment and human review workflows.

**Completed:**

| Milestone | What It Delivered |
|-----------|-------------------|
| M1: Core Agent System | Agent foundation, tool system, observability infrastructure |
| M2: Workflow Orchestration | LangGraph compiler, stage-based execution, YAML config |
| M2.5: Execution Engine Abstraction | Engine interface, LangGraph adapter, engine registry |
| M3: Multi-Agent Collaboration | Parallel execution, voting/consensus/debate/hierarchical strategies, merit-weighted resolution |
| M4: Safety & Governance | Policy composition, approval workflows, rollback, circuit breakers, safety gates |
| M5.1: Optimization Engine | Composable evaluators + optimizers, CLI integration, 3 demo workflows, 85 tests |
| M5.2: Agent Memory | SQLite persistence, decay/pruning, LLM procedural extraction, cross-agent sharing, 163 tests |
| M5.3: Continuous Learning | Background pattern mining (5 miners), recommendation engine, auto-tune, learning dashboard, convergence detection, 58 tests |
| M6.2: Temper AI Server | WorkflowRunner API, persistent run history (SQLite), CLI client (trigger/status/logs), API key auth, 74 tests |
| M6.1: Progressive Autonomy | Trust-based agent escalation (5 levels), approval routing matrix, budget enforcement, emergency stop, shadow mode, 136 tests |
| M6.3: Multi-Product Templates | Copy-and-stamp template system (4 product types, 42 YAML configs), template registry/generator, CLI commands, quality gate presets, 63 tests |
| M7.1: Self-Modifying Lifecycle | Pre-compilation workflow adaptation (project classifier, profile registry, lifecycle adapter), A/B testing, rollback monitoring, 103 tests |
| M7.2: Strategic Autonomy | Goal proposal framework (4 analyzers, proposer, safety policy, review workflow), CLI + dashboard, cross-product learning, 101 tests |
| M7.3: Portfolio Management | Multi-product orchestration, resource allocation (WFQ scheduling), component sharing (Jaccard similarity), portfolio optimization (4-metric scorecard), knowledge graph (SQLite, BFS traversal), 114 tests |

**Post-Milestone Improvements:**

- Domain-based modular monolith migration (23 technical-layer modules to 13 domain-based modules)
- Quality score 85 to 100/100 (A+) with zero deductions
- LLMService extraction (clean separation of LLM call lifecycle)
- Observability: structured logging, OpenTelemetry, error fingerprinting, resilience tracking, cost rollup, data lineage, prompt versioning; async support, sampling, health monitoring, span cleanup (9 gaps closed)
- Parallel test execution (pytest-xdist), architecture scanner v2.4.0
- ExperimentService wired into optimization engine — Selection, Refinement, and Tuning optimizers now track experiments via `temper_ai/experimentation/` A/B testing engine
- Conversation history for stage:agent re-invocations — agents retain multi-turn context when re-invoked in workflow loops/branches

**Available Foundation:**

- `temper_ai/experimentation/` — production-ready A/B testing engine (v1.0.0, 101 tests): experiment lifecycle, variant assignment (hash/random), statistical analysis (t-test, SPRT, Bayesian), guardrails, config merging with security validation
- `temper_ai/observability/merit_score_service.py` — agent merit scoring (not connected to safety)

**Completed and Removed:**

- `temper_ai/self_improvement/` — deleted (~50 files of speculative M5 loop code). Replaced by `temper_ai/improvement/` (composable optimization engine, ~750 lines, 85 tests)

---

## Phase I: Intelligence Layer (M5)

**Value Proposition:** The framework stops producing "whatever the LLM gives you" and starts producing the output you actually want. A composable optimization engine lets users define how output quality is evaluated, then automatically refines, selects, and tunes until the target is met — all driven by workflow config.

**Key Capabilities:**
- Composable evaluators: criteria (pass/fail), comparative (A vs B), scored (0-1), human-in-the-loop
- Composable optimizers: iterative refinement (critique loop), best-of-N selection, statistical config tuning
- Any optimizer can use any evaluator — radical modularity via configuration
- Config tuning delegates to the proven `temper_ai/experimentation/` A/B testing engine
- Agents have episodic, procedural, and cross-session memory
- Background pattern mining surfaces actionable heuristics

**How It Changes User Experience:**
- Users define quality targets and evaluation criteria in workflow YAML
- Workflows automatically refine output until criteria are met
- Config optimization runs across multiple runs with statistical rigor
- Repeated problem types get solved faster via memory and learned patterns

---

## Phase II: Adaptive Operations (M6)

**Value Proposition:** The framework earns trust incrementally and becomes accessible as a service. Agents gain autonomy based on track record, and external products can trigger workflows via API.

**Key Capabilities:**
- Progressive autonomy — agents earn trust, human intervention decreases
- Temper AI Server — REST/WebSocket API for external integration
- Multi-product templates — pre-built workflow configs per product type
- Runtime budget enforcement and emergency stop

**How It Changes User Experience:**
- Low-risk operations run without approval; high-risk operations require it
- Products trigger Temper AI workflows via HTTP instead of CLI
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

### M5.1: Optimization Engine — COMPLETE

Deleted `temper_ai/self_improvement/` (untested, speculative) and built a composable optimization engine in `temper_ai/improvement/`. Users configure evaluators (how to judge quality) and optimizers (how to improve) as a pipeline in workflow YAML. Engine is wired into `temper-ai run` — workflows with an `optimization:` block automatically invoke the pipeline.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `OptimizationEngine` | `temper_ai/improvement/engine.py` | Done — pipeline orchestrator |
| `OptimizationConfig` / schemas | `temper_ai/improvement/_schemas.py` | Done — Pydantic models |
| `EvaluatorProtocol` / `OptimizerProtocol` | `temper_ai/improvement/protocols.py` | Done |
| `CriteriaEvaluator` | `temper_ai/improvement/evaluators/criteria.py` | Done — programmatic + LLM checks |
| `ComparativeEvaluator` | `temper_ai/improvement/evaluators/comparative.py` | Done |
| `ScoredEvaluator` | `temper_ai/improvement/evaluators/scored.py` | Done |
| `HumanEvaluator` | `temper_ai/improvement/evaluators/human.py` | Done |
| `SelectionOptimizer` | `temper_ai/improvement/optimizers/selection.py` | Done — best of N re-rolls |
| `RefinementOptimizer` | `temper_ai/improvement/optimizers/refinement.py` | Done — LLM critique loop |
| `TuningOptimizer` | `temper_ai/improvement/optimizers/tuning.py` | Done — strategy search (ExperimentService optional) |
| `OptimizationRegistry` | `temper_ai/improvement/registry.py` | Done |
| CLI wiring | `temper_ai/interfaces/cli/main.py` | Done — `_CLIWorkflowRunner`, `_CritiqueLLM` adapter |
| Workflow schema | `temper_ai/workflow/_schemas.py` | Done — `optimization: Optional[OptimizationConfig]` |
| Unit tests | `tests/test_improvement/` | Done — 85 tests |

**Demo Workflows (all tested end-to-end with `temper-ai run`):**

| Workflow | Optimizer | What It Does |
|----------|-----------|-------------|
| `configs/workflows/optimized_decision_demo.yaml` | Selection | Runs 3x, picks output with best evaluator score |
| `configs/workflows/refinement_decision_demo.yaml` | Refinement | Run → evaluate → LLM critique → re-run with feedback (max 2 iterations) |
| `configs/workflows/tuning_decision_demo.yaml` | Tuning | 3 strategies (risk_averse, growth_focused, team_centric), picks best |

**Programmatic Check Scripts:**

| Script | What It Checks |
|--------|---------------|
| `scripts/checks/has_decision.py` | Output contains a decision/final_decision key |
| `scripts/checks/has_detailed_reasoning.py` | All agent outputs >= 500 chars |
| `scripts/checks/has_agent_agreement.py` | All agents recommend the same option |
| `scripts/checks/has_high_confidence.py` | Synthesis confidence >= 0.8 |

**How Optimizers Steer Agent Behavior:**

All 3 optimizers work by modifying `input_data` (workflow inputs). The existing `_inject_input_context()` in `base_agent.py` automatically surfaces any new string keys as `## Label` sections in agent prompts — no agent code changes needed.

- **Selection:** No input changes — relies on LLM nondeterminism across runs
- **Refinement:** Injects `_optimization_critique` key (LLM-generated feedback) — agents see `## Optimization Critique` in prompt
- **Tuning:** Merges strategy dict (e.g. `_tuning_instructions`) — agents see `## Tuning Instructions` in prompt

**Remaining Gaps (for future work):**

- **Baseline comparison:** No mechanism to run once without optimization and compare scores — needed to prove optimization actually improves output
- **Per-check visibility:** Check pass/fail results not surfaced in CLI output (only logged internally)
- **Decision persistence:** No way to "keep" a winning strategy or critique — results are ephemeral
- **Strategies module:** `strategies/` directory (prompt.py, temperature.py) was not built — tuning uses YAML-defined strategy dicts instead (simpler, more flexible)
- **M5-specific DB tables:** `m5_experiments`, `m5_experiment_results`, `m5_loop_state` may still exist in Alembic migrations
- ~~**ExperimentService not exercised:** Optimizers had optional ExperimentService but it was never wired in~~ ✓ Resolved — ExperimentService wired into all 3 optimizers (Selection, Refinement, Tuning) for variant assignment, early stopping, and experiment tracking

**Dependencies:** None (builds on M4 foundation + existing `temper_ai/experimentation/`)

---

### M5.2: Agent Memory — COMPLETE

Persistent memory across sessions and workflow runs with pluggable backends.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `MemoryService` | `temper_ai/memory/service.py` | Done — retrieve_context, retrieve_with_shared, store_episodic/procedural/cross_session, decay, pruning |
| `MemoryScope` / schemas | `temper_ai/memory/_schemas.py` | Done — scope model (tenant, workflow, agent, namespace) |
| Memory constants | `temper_ai/memory/constants.py` | Done — providers, types, limits |
| `InMemoryAdapter` | `temper_ai/memory/adapters/in_memory.py` | Done — dict-based, thread-safe (testing/fallback) |
| `SQLiteAdapter` | `temper_ai/memory/adapters/sqlite_adapter.py` | Done — zero-dependency persistent backend, LIKE + FTS5 opt-in |
| `Mem0Adapter` | `temper_ai/memory/adapters/mem0_adapter.py` | Done — vector search via Mem0 (optional dependency) |
| `MemoryStoreProtocol` | `temper_ai/memory/protocols.py` | Done — runtime-checkable adapter contract |
| `MemoryProviderRegistry` | `temper_ai/memory/registry.py` | Done — thread-safe singleton, lazy loading |
| Procedural extraction | `temper_ai/memory/extractors.py` | Done — LLM-based pattern extraction from agent output |
| Agent memory injection | `temper_ai/agent/standard_agent.py` | Done — `_inject_memory_context()`, `_on_after_run()`, shared scope retrieval, procedural extraction |
| Agent memory config | `temper_ai/storage/schemas/agent_config.py` | Done — `MemoryConfig` (enabled, provider, decay_factor, max_episodes, auto_extract_procedural, shared_namespace) |
| CLI memory commands | `temper_ai/interfaces/cli/memory_commands.py` | Done — list/add/search/clear/seed with `--db-path` for SQLite |
| Decay & pruning | `temper_ai/memory/service.py` | Done — exponential time-decay (`_apply_decay`), max-episodes pruning (`_enforce_max_episodes`) |
| Cross-agent sharing | `temper_ai/memory/service.py` | Done — `build_shared_scope()`, `retrieve_with_shared()` (dual-scope search with dedup) |
| Demo configs | `configs/agents/memory_researcher.yaml`, `configs/workflows/memory_demo.yaml` | Done |
| Tests | `tests/test_memory/` | Done — 163 tests |

**Key Capabilities:**
- **3 backends:** in_memory (testing), SQLite (zero-dep persistence), Mem0 (vector search)
- **Decay & pruning:** Exponential time-decay on relevance scores; oldest-first pruning when max_episodes exceeded
- **LLM extraction:** Auto-extract procedural patterns from agent output (opt-in via `auto_extract_procedural: true`)
- **Cross-agent sharing:** Agents store/retrieve from both private and shared namespaces (opt-in via `shared_namespace`)

**Key Files:**
- `temper_ai/memory/` module (service, adapters, extractors, schemas, protocols, registry)
- `temper_ai/agent/standard_agent.py` (memory injection, extraction, sharing)
- `temper_ai/storage/schemas/agent_config.py` (`MemoryConfig` in `AgentConfig`)
- `temper_ai/interfaces/cli/memory_commands.py` (CLI management)

**Remaining Gaps (for future work):**
- **Vector search via embeddings:** Mem0 adapter exists but requires `pip install -e ".[memory]"`; no built-in embedding backend
- **Baseline comparison for memory impact:** No mechanism to A/B test "with memory" vs "without memory" runs

**Dependencies:** M5.1 (needs outcome data flowing from the loop)

---

### M5.3: Continuous Learning — COMPLETE

Background pattern mining and proactive recommendations from execution history.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `AgentPerformanceMiner` | `temper_ai/learning/miners/agent_performance.py` | Done — detects slow/unreliable agents |
| `ModelEffectivenessMiner` | `temper_ai/learning/miners/model_effectiveness.py` | Done — identifies error-prone/expensive models |
| `FailurePatternMiner` | `temper_ai/learning/miners/failure_patterns.py` | Done — finds recurring error signatures |
| `CostPatternMiner` | `temper_ai/learning/miners/cost_patterns.py` | Done — detects cost-dominant agents |
| `CollaborationPatternMiner` | `temper_ai/learning/miners/collaboration_patterns.py` | Done — finds debate inefficiencies |
| `MiningOrchestrator` | `temper_ai/learning/orchestrator.py` | Done — runs all miners, deduplicates, publishes to MemoryService |
| `BackgroundMiningJob` | `temper_ai/learning/background.py` | Done — 6-hour async loop with convergence-aware skip |
| `RecommendationEngine` | `temper_ai/learning/recommender.py` | Done — pattern→config change mapping (model, timeout, tokens, retries, debate rounds) |
| `AutoTuneEngine` | `temper_ai/learning/auto_tune.py` | Done — preview + apply YAML config changes |
| `ConvergenceDetector` | `temper_ai/learning/convergence.py` | Done — moving avg novelty (10-run window, 0.1 threshold) |
| `LearningDataService` | `temper_ai/learning/dashboard_service.py` | Done — API data aggregation |
| Dashboard routes | `temper_ai/learning/dashboard_routes.py` | Done — 6 endpoints (`/api/learning/`) |
| Dashboard UI | `temper_ai/interfaces/dashboard/static/learning.html` | Done — Plotly charts, pattern/convergence/recommendations |
| `LearningStore` | `temper_ai/learning/store.py` | Done — SQLite persistence (WAL mode) |
| Learning models | `temper_ai/learning/models.py` | Done — `LearnedPattern`, `MiningRun`, `TuneRecommendation` (SQLModel) |
| CLI commands | `temper_ai/interfaces/cli/learning_commands.py` | Done — `temper-ai learning mine\|patterns\|recommend\|tune\|stats` |
| Alembic migration | `alembic/versions/f7a8b9012345_add_learning_tables.py` | Done — 3 tables |
| Tests | `tests/test_learning/` | Done — 58 tests |

**Key Capabilities:**
- **5 pattern miners** query observability data (AgentExecution, LLMCall, ErrorFingerprint, CollaborationEvent)
- **Auto-tune** recommends and applies config changes: model switching, timeout/retry adjustment, token reduction, debate round reduction
- **Convergence detection** stops mining when novelty score drops below threshold (moving average over 10-run window)
- **Memory integration** publishes patterns to MemoryService shared namespace (`procedural/learning`)
- **Dashboard** visualizes patterns, convergence trends, mining history, and pending recommendations

**Remaining Gaps (for future work):**
- **Empirical validation:** Framework tracks novelty and recommendations, but empirical proof over 50+ runs needs real production data
- **Embedding-based pattern similarity:** Current deduplication uses SHA256 hashing; semantic similarity would catch near-duplicates

**Dependencies:** M5.2 (needs memory layer for storing/retrieving patterns)

---

## M6: Adaptive Operations (Q2-Q3 2026)

### M6.1: Progressive Autonomy — COMPLETE

Agents earn trust incrementally based on track record. Safety policies adapt to demonstrated reliability.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `AutonomyLevel` enum + `AutonomyConfig` | `temper_ai/safety/autonomy/schemas.py` | Done — 5 levels (Supervised→Strategic), config with enabled=False default |
| `AutonomyState/Transition/Budget/Emergency` models | `temper_ai/safety/autonomy/models.py` | Done — 4 SQLModel tables |
| `AutonomyStore` | `temper_ai/safety/autonomy/store.py` | Done — SQLite/WAL CRUD for all 4 tables |
| `TrustEvaluator` | `temper_ai/safety/autonomy/trust_evaluator.py` | Done — reads AgentMeritScore, checks thresholds |
| `AutonomyManager` | `temper_ai/safety/autonomy/manager.py` | Done — state machine with cooldown, max-level cap, threading.Lock |
| `BudgetEnforcer` | `temper_ai/safety/autonomy/budget_enforcer.py` | Done — per-scope spending tracking, cost estimation from model_pricing.yaml |
| `ApprovalRouter` | `temper_ai/safety/autonomy/approval_router.py` | Done — severity × level decision matrix, spot-check sampling |
| `AutonomyPolicy` | `temper_ai/safety/autonomy/policy.py` | Done — BaseSafetyPolicy subclass, emergency/budget/approval checks |
| `MeritSafetyBridge` | `temper_ai/safety/autonomy/merit_bridge.py` | Done — rate-limited bridge from merit updates to autonomy evaluation |
| `EmergencyStopController` | `temper_ai/safety/autonomy/emergency_stop.py` | Done — O(1) threading.Event, activate/deactivate, check_or_raise |
| `ShadowMode` | `temper_ai/safety/autonomy/shadow_mode.py` | Done — non-blocking shadow validation, agreement tracking, promotion readiness |
| CLI commands | `temper_ai/interfaces/cli/autonomy_commands.py` | Done — status, escalate, deescalate, emergency-stop, resume, budget, history |
| Dashboard routes + UI | `temper_ai/safety/autonomy/dashboard_routes.py`, `autonomy.html` | Done — 8 endpoints, Plotly charts |
| Alembic migration | `alembic/versions/g8b9c0123456_add_autonomy_tables.py` | Done — 4 tables |
| Tests | `tests/test_safety/test_autonomy/`, `tests/test_interfaces/test_autonomy_cli.py` | Done — 136 tests |

**Key Capabilities:**
- **5 autonomy levels:** SUPERVISED → SPOT_CHECKED → RISK_GATED → AUTONOMOUS → STRATEGIC
- **Approval matrix:** CRITICAL=2 approvers always; HIGH=1 at lower levels, auto at AUTONOMOUS+; MEDIUM=spot-check sampling
- **Budget enforcement:** Per-scope spending caps with warning/exhausted status transitions
- **Emergency stop:** Module-level threading.Event for O(1) cross-thread halt, 5s SLA
- **Shadow mode:** Validates escalation decisions non-blocking before promotion (50+ runs, 98%+ agreement threshold)
- **Backward compatible:** AutonomyConfig.enabled=False by default; existing agents unaffected

**Dependencies:** M5.1 (needs outcome tracking for merit calculation)

---

### M6.2: Temper AI Server — COMPLETE

Expose the framework as an API service that external products can integrate with.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `WorkflowRunner` API | `temper_ai/interfaces/server/workflow_runner.py` | Done — sync `run()` with `on_event` callback, typed `WorkflowRunResult` |
| `ServerRun` model | `temper_ai/interfaces/server/models.py` | Done — SQLModel with JSON columns for input/result |
| `RunStore` persistence | `temper_ai/interfaces/server/run_store.py` | Done — SQLite-backed CRUD, WAL mode, status filtering |
| `APIKeyMiddleware` | `temper_ai/interfaces/server/auth.py` | Done — env-var controlled, health/WebSocket bypass |
| `TemperAIServerClient` | `temper_ai/interfaces/cli/server_client.py` | Done — httpx-based HTTP client |
| CLI: `temper-ai trigger` | `temper_ai/interfaces/cli/main.py` | Done — POST /api/runs, `--wait` polls until complete |
| CLI: `temper-ai status` | `temper_ai/interfaces/cli/main.py` | Done — single run detail or list table |
| CLI: `temper-ai logs` | `temper_ai/interfaces/cli/main.py` | Done — HTTP events or `--follow` WebSocket stream |
| GET /api/runs | `temper_ai/interfaces/server/routes.py` | Done — list with status filter, pagination |
| Alembic migration | `alembic/versions/e6f7a8b90123_add_server_runs.py` | Done — `server_runs` table |
| Tests | `tests/test_interfaces/test_server/` | Done — 74 tests |

**Key Capabilities:**
- `WorkflowRunner` library API for programmatic embedding (any Python program)
- Persistent run history survives server restarts (SQLite)
- CLI client commands (`trigger`, `status`, `logs`) talk to running server via HTTP
- API key authentication via `TEMPER_AI_API_KEY` env var (disabled in dev mode)
- `ExecutionService` delegates to `WorkflowRunner`, persists status transitions to `RunStore`

**Remaining Gaps (for future work):**
- **L3 container isolation:** Only L1 path restriction implemented; container-based workspace isolation deferred
- **PostgreSQL migration path:** SQLite remains the only backend; multi-user scenarios need PostgreSQL support
- **Rate limiting:** No request rate limiting on server endpoints

**Dependencies:** None

---

### M6.3: Multi-Product Templates — COMPLETE

Copy-and-stamp template system: users run `temper-ai template create --type api --name my-api` and get a complete set of workflow/stage/agent configs generated from a proven template. No runtime merge complexity — configs are standalone once created.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| Template schemas | `temper_ai/workflow/templates/_schemas.py` | Done — TemplateManifest, TemplateQualityGates, TemplateDefaultInference |
| Template registry | `temper_ai/workflow/templates/registry.py` | Done — discover, validate, cache manifests |
| Template generator | `temper_ai/workflow/templates/generator.py` | Done — copy-and-stamp with `{{project_name}}`, inference overrides, quality gates |
| Quality gate presets | `temper_ai/workflow/templates/quality_gates.py` | Done — per-product defaults (web_app, api, data_pipeline, cli_tool) |
| Template YAML configs | `configs/templates/{web_app,api,data_pipeline,cli_tool}/` | Done — 42 files (4 manifests + 4 workflows + 17 stages + 17 agents) |
| CLI commands | `temper_ai/interfaces/cli/template_commands.py` | Done — `temper-ai template list\|info\|create` |
| Product type expansion | `temper_ai/workflow/_schemas.py` | Done — added `data_pipeline`, `cli_tool` to Literal |
| Unit + integration tests | `tests/test_workflow/test_templates/`, `tests/test_interfaces/test_template_cli.py` | Done — 63 tests |

**CLI Commands:**

```bash
temper-ai template list                                    # List available templates
temper-ai template info api                                # Show template details + quality gates
temper-ai template create --type api --name my-api         # Generate project configs
temper-ai template create --type web_app --name mysite \
    --provider ollama --model llama3 --output /tmp/out  # With inference overrides
```

**Quality Gate Presets:**

| Product Type | min_confidence | require_citations | on_failure | Custom Checks |
|---|---|---|---|---|
| web_app | 0.70 | true | retry_stage | performance, accessibility, security |
| api | 0.75 | true | retry_stage | schema_validation, backward_compatibility |
| data_pipeline | 0.80 | false | escalate | data_quality, completeness |
| cli_tool | 0.70 | false | retry_stage | help_text, exit_codes |

**Dependencies:** M6.2 (server for deployment-oriented templates)

---

## M7: Autonomous Systems (Q4 2026 - Q2 2027)

### M7.1: Self-Modifying Lifecycle — COMPLETE

Pre-compilation workflow adaptation based on project characteristics and historical profiles.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `ProjectClassifier` | `temper_ai/lifecycle/classifier.py` | Done — LLM-based + explicit-input fallback classification |
| `ProfileRegistry` | `temper_ai/lifecycle/profiles.py` | Done — YAML + DB merge, profile matching |
| `LifecycleAdapter` | `temper_ai/lifecycle/adapter.py` | Done — classify → match → autonomy gate → apply rules (SKIP/ADD/REORDER/MODIFY) → audit |
| `HistoryAnalyzer` | `temper_ai/lifecycle/history.py` | Done — historical outcome analysis for adaptation decisions |
| `LifecycleExperimenter` | `temper_ai/lifecycle/experiment.py` | Done — wraps ExperimentService for A/B testing lifecycle variants |
| `RollbackMonitor` | `temper_ai/lifecycle/rollback.py` | Done — degradation detection, automatic rollback |
| `LifecycleStore` | `temper_ai/lifecycle/store.py` | Done — SQLite/WAL persistence |
| Lifecycle models | `temper_ai/lifecycle/models.py` | Done — SQLModel tables |
| Lifecycle schemas | `temper_ai/lifecycle/_schemas.py` | Done — Pydantic models, LifecycleConfig in WorkflowConfigInner |
| CLI commands | `temper_ai/interfaces/cli/lifecycle_commands.py` | Done — `temper-ai lifecycle profiles\|classify\|preview\|history\|check` |
| Dashboard routes | `temper_ai/lifecycle/dashboard_routes.py` | Done — 4 API endpoints |
| Profile configs | `configs/lifecycle/{lean_small_projects,security_aware}.yaml` | Done |
| Demo workflow | `configs/workflows/lifecycle_demo.yaml` | Done |
| CLI wiring | `temper_ai/interfaces/cli/main.py` | Done — `_maybe_adapt_lifecycle()` between load and compile |
| Tests | `tests/test_lifecycle/` | Done — 103 tests |

**Key Capabilities:**
- **Project classification:** LLM-based or explicit-input classification by size, type, risk profile
- **Profile matching:** YAML-defined lifecycle profiles merged with DB-stored overrides
- **Adaptation rules:** SKIP stages (small projects skip design), ADD stages (security-aware adds audit), REORDER, MODIFY
- **Autonomy gating:** Full M6.1 integration — adaptation level constrained by AutonomyLevel
- **A/B testing:** LifecycleExperimenter wraps ExperimentService for lifecycle variant experiments
- **Rollback monitoring:** RollbackMonitor detects quality degradation and reverts to previous lifecycle

**Dependencies:** M5.3 (learning data for adaptation decisions), M6.1 (progressive autonomy for safe self-modification)

---

### M7.2: Strategic Autonomy — COMPLETE

The system proposes improvements and opportunities, not just executes instructions.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| Goal schemas | `temper_ai/goals/_schemas.py` | Done — GoalType, GoalStatus, GoalRiskLevel, GoalProposal, RiskAssessment, ImpactEstimate, GoalEvidence |
| Goal models | `temper_ai/goals/models.py` | Done — GoalProposalRecord, AnalysisRun (SQLModel) |
| `GoalStore` | `temper_ai/goals/store.py` | Done — SQLite/WAL CRUD, filtering, counting |
| `PerformanceAnalyzer` | `temper_ai/goals/analyzers/performance.py` | Done — slow stages, degradation detection |
| `CostAnalyzer` | `temper_ai/goals/analyzers/cost.py` | Done — high-cost agents, expensive model detection |
| `ReliabilityAnalyzer` | `temper_ai/goals/analyzers/reliability.py` | Done — recurring errors, high failure rate agents |
| `CrossProductAnalyzer` | `temper_ai/goals/analyzers/cross_product.py` | Done — cross-product performance gaps, pattern transfer |
| `GoalProposer` | `temper_ai/goals/proposer.py` | Done — orchestrates analyzers, deduplicates, scores (weighted formula), persists |
| `AnalysisOrchestrator` | `temper_ai/goals/analysis_orchestrator.py` | Done — runs proposer, records analysis run metadata |
| `BackgroundAnalysisJob` | `temper_ai/goals/background.py` | Done — periodic async loop for server mode |
| `GoalSafetyPolicy` | `temper_ai/goals/safety_policy.py` | Done — rate limits, risk validation, auto-approve matrix by autonomy level |
| `GoalReviewWorkflow` | `temper_ai/goals/review_workflow.py` | Done — state machine (proposed→approved/rejected/deferred), acceptance rate tracking |
| `GoalDataService` | `temper_ai/goals/dashboard_service.py` | Done — dashboard data aggregation |
| Dashboard routes | `temper_ai/goals/dashboard_routes.py` | Done — 8 endpoints (list, detail, stats, runs, analyze, approve, reject, defer) |
| CLI commands | `temper_ai/interfaces/cli/goal_commands.py` | Done — `temper-ai goals list\|propose\|review\|approve\|reject\|status` |
| CLI wiring | `temper_ai/interfaces/cli/main.py` | Done — `goals_group` mounted |
| Dashboard wiring | `temper_ai/interfaces/dashboard/app.py` | Done — goals router mounted |
| Constants | `temper_ai/goals/constants.py` | Done — thresholds, weights, limits |
| Tests | `tests/test_goals/` | Done — 101 tests |

**Key Capabilities:**
- **4 analyzers** scan execution history: performance (slow/degrading stages), cost (expensive agents/models), reliability (recurring errors, high failure rates), cross-product (performance gaps, pattern transfer)
- **Weighted scoring:** 0.35×impact + 0.25×confidence + 0.20×(1/effort) + 0.20×(1/risk)
- **Deduplication:** SHA256 hash of goal_type + title, skips if matching active proposal exists
- **Safety policy:** Rate limiting (20/day), auto-approve matrix by autonomy level (SUPERVISED=never, RISK_GATED=low, AUTONOMOUS=medium, STRATEGIC=high, CRITICAL=never)
- **Review workflow:** State machine with PROPOSED→UNDER_REVIEW→APPROVED/REJECTED/DEFERRED transitions
- **Cross-product learning:** CrossProductAnalyzer cross-references LearnedPattern data with product-type execution metrics
- **Budget integration:** Read-only checks against BudgetEnforcer for cost-impacting proposals
- **CLI:** `temper-ai goals propose` runs analysis, `temper-ai goals list` shows results, `temper-ai goals approve/reject` applies decisions

**Remaining Gaps (for future work):**
- **Empirical acceptance rate:** Framework tracks acceptance rate but needs 50+ proposals to validate 50%+ target
- **Auto-execution of approved goals:** Currently proposals are informational; approved goals don't auto-trigger workflow changes

**Dependencies:** M7.1 (adaptive lifecycle), M5.2 (memory for cross-product learning)

---

### M7.3: Portfolio Management — COMPLETE

Multi-product orchestration with autonomous resource allocation, component sharing, and strategic optimization.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| Portfolio schemas | `temper_ai/portfolio/_schemas.py` | Done — PortfolioConfig, ProductConfig, AllocationStatus, ProductScorecard, Recommendation |
| Portfolio models | `temper_ai/portfolio/models.py` | Done — 7 SQLModel tables (portfolios, product_runs, shared_components, kg_concepts, kg_edges, tech_compatibility, snapshots) |
| `PortfolioStore` | `temper_ai/portfolio/store.py` | Done — SQLite/WAL CRUD for all 7 tables |
| `PortfolioLoader` | `temper_ai/portfolio/loader.py` | Done — YAML config loading and validation |
| `ResourceScheduler` | `temper_ai/portfolio/scheduler.py` | Done — WFQ scheduling (virtual_time = completed/weight), concurrency + budget gates, record_start/complete lifecycle |
| `ComponentAnalyzer` | `temper_ai/portfolio/component_analyzer.py` | Done — Jaccard similarity (|A∩B|/|A∪B|) for cross-product stage config reuse, MIN_SIMILARITY=0.6 |
| `PortfolioOptimizer` | `temper_ai/portfolio/optimizer.py` | Done — 4-metric scorecard (success_rate, cost_efficiency, trend, utilization) → composite_score → invest/maintain/reduce/sunset |
| `KnowledgePopulator` + `KnowledgeQuery` | `temper_ai/portfolio/knowledge_graph.py` | Done — SQLite graph (concepts, edges, tech_compatibility), BFS traversal, concept_stats |
| Portfolio constants | `temper_ai/portfolio/constants.py` | Done — thresholds, weights, limits |
| Dashboard routes | `temper_ai/portfolio/dashboard_routes.py` | Done — 6 API endpoints via create_portfolio_router() |
| CLI commands | `temper_ai/interfaces/cli/portfolio_commands.py` | Done — `temper-ai portfolio list\|show\|run\|scorecards\|recommend\|components\|graph stats\|graph query` |
| CLI wiring | `temper_ai/interfaces/cli/main.py` | Done — `portfolio_group` mounted |
| Dashboard wiring | `temper_ai/interfaces/dashboard/app.py` | Done — portfolio router mounted |
| Portfolio config | `configs/portfolios/example_portfolio.yaml` | Done — 3 products (web_app, api, data_pipeline) |
| Tests | `tests/test_portfolio/` | Done — 114 tests (9 test files) |

**Key Capabilities:**
- **WFQ scheduling:** Weighted Fair Queuing selects next product by lowest virtual_time (completed/weight), with concurrency and budget gates
- **Component sharing:** Jaccard similarity detects reusable stage configurations across products (threshold 0.6)
- **Portfolio optimization:** 4-metric scorecard → composite score → invest/maintain/reduce/sunset recommendations
- **Knowledge graph:** SQLite-backed concept graph with BFS traversal, technology compatibility tracking
- **Dashboard:** 6 API endpoints for portfolio data and analysis

**Remaining Gaps (for future work):**
- **Full knowledge graph:** Current implementation covers domain concepts and tech compatibility; full semantic memory deferred
- **Empirical validation:** Portfolio recommendations need 50+ runs to validate alignment with human strategic intent

**Dependencies:** M7.2, M6.3

---

# Part 3: VCS Parallel Track

The Vibe Coding Squad (VCS) pipeline runs as a parallel effort, with integration checkpoints where framework milestones unlock VCS capabilities.

### V1: Pipeline Foundation (Current — ~90% complete)

- All 18 agents, 7 stages, and workflow config exist in `configs/`
- Remaining work: enable conditional stage bypass, end-to-end testing with a real LLM

### V2: Web Application (~3-4 weeks)

- Complete FastAPI app (routes, models, frontend) for VCS
- Embedded Temper AI `WorkflowRunner` or Temper AI Server client for pipeline execution
- Pipeline event storage and activity feed UI
- WebSocket live updates during triage
- **Dependencies:** M6.2 (Temper AI Server) or embedded `WorkflowRunner` approach

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
| M5.1 Optimization Engine | V3 | VCS can optimize triage accuracy via evaluator pipeline |
| M5.2 Agent Memory | V3 | Agents remember past triage patterns |
| M6.1 Progressive Autonomy | V4 | VCS earns trust for auto-implementation |
| M6.2 Temper AI Server | V2 | VCS web app triggers pipelines via API |
| M7.2 Strategic Autonomy | V4 | VCS proposes features autonomously |

---

# Part 4: Timeline

```
2026 Q1            M5.1 Optimization Engine ✓ COMPLETE
2026 Q1            M5.2 Agent Memory ✓ COMPLETE
2026 Q1            M6.2 Temper AI Server ✓ COMPLETE
2026 Q1            M5.3 Continuous Learning ✓ COMPLETE
2026 Q1            M6.1 Progressive Autonomy ✓ COMPLETE
2026 Q1            M6.3 Multi-Product Templates ✓ COMPLETE
2026 Q1            M7.1 Self-Modifying Lifecycle ✓ COMPLETE
2026 Q1            M7.2 Strategic Autonomy ✓ COMPLETE
2026 Q1            M7.3 Portfolio Management ✓ COMPLETE
2026 Q2 (Now)     V2 VCS Web App + V3 Self-Improving VCS
2026 Q3            V4 Autonomous VCS
```

## Milestone Dependency Graph

```
M5.1 Optimization Engine ✓ COMPLETE
 ├──→ M5.2 Agent Memory ✓ COMPLETE
 │     ├──→ M5.3 Continuous Learning ✓ COMPLETE
 │     │     └──→ M7.1 Self-Modifying Lifecycle ✓ COMPLETE ──→ M7.2 Strategic Autonomy ✓ COMPLETE ──→ M7.3 Portfolio Management ✓ COMPLETE
 │     └──→ M7.2 Strategic Autonomy ✓ COMPLETE
 └──→ M6.1 Progressive Autonomy ✓ COMPLETE
       └──→ M7.1 Self-Modifying Lifecycle ✓ COMPLETE

M6.2 Temper AI Server ✓ COMPLETE
 └──→ M6.3 Multi-Product Templates ✓ COMPLETE ──→ M7.3 Portfolio Management ✓ COMPLETE
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
| ~~Speculative M5 code as tech debt~~ | ~~50 files of untested code blocking fresh design~~ | ~~High~~ | ~~Resolved: `temper_ai/self_improvement/` deleted, `temper_ai/improvement/` built and tested (85 tests)~~ |
| Vector search adds new dependency | Increased complexity, deployment friction | Medium | Start with simple embedding (numpy), upgrade to dedicated vector DB later |
| Progressive autonomy safety gaps | Trust erosion if agent causes harm | Medium | Shadow mode, conservative defaults, feature flags, emergency stop |
| Runtime DAG modification complexity | Workflow instability, hard-to-debug failures | High | Extensive testing, rollback mechanisms, shadow execution |
| LLM cost multiplication from optimization | Refinement + selection + tuning multiplies LLM calls per workflow | High | Max iteration caps per optimizer, cost tracking per pipeline run, budget enforcement in M6.1 |
| Memory retrieval latency | Agent startup slowdown from memory queries | Low | Cache hot paths, async prefetch, latency budget (< 500ms) |

---

# Part 7: Success Metrics

### M5 Success

- ~~Evaluators and optimizers compose freely via config (no code changes for new combinations)~~ ✓ Done — any optimizer + any evaluator via YAML
- ~~Refinement optimizer iterates until criteria pass (or max iterations)~~ ✓ Done — tested with critique loop
- ~~Selection optimizer picks measurably better output from N candidates~~ ✓ Done — tested with 3 runs, differentiated scores
- ~~Tuning optimizer searches config space~~ ✓ Done — tested with 3 strategies, picks best score
- Optimization pipeline produces measurably better output than single-run baseline (needs baseline comparison mechanism)
- ~~Tuning optimizer finds statistically significant config improvements via ExperimentService (ExperimentService integration exists but not exercised in demos)~~ ✓ Done — ExperimentService wired into all 3 optimizers; variant assignment, early stopping, and experiment tracking operational
- ~~Agents reference past projects in reasoning (verifiable in traces)~~ ✓ Done — memory injection into prompts via `_inject_memory_context`, episodic + procedural + cross-session types, cross-agent sharing
- ~~Pattern mining discovers 10+ actionable heuristics~~ ✓ Done — 5 miners × 2-4 pattern types each = 10-20 discoverable heuristic types (agent performance, model effectiveness, failure, cost, collaboration)
- < 5% cost increase from optimization overhead (per-run, excluding tuning batches) — not yet measured

### M6 Success

- Human intervention rate decreases 30%+ for trusted agents
- Temper AI Server handles 10+ concurrent workflow runs
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

**Last Updated:** 2026-02-16
