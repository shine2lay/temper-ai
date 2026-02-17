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

The framework has a solid foundation. Twelve milestones are complete (M1-M4 + M5.1-M5.3 + M6.1-M6.3 + M7.1-M7.2), quality is at 96/100 (A+), and the optimization engine is wired into the CLI execution pipeline. Agents now have persistent memory with SQLite persistence, time-decay relevance, LLM-based procedural extraction, and cross-agent shared namespaces. The framework is exposed as an API service with REST endpoints, WebSocket streaming, persistent run history, CLI client commands, and API key authentication. Background pattern mining continuously discovers actionable heuristics from execution history, with auto-tune recommendations and convergence-aware scheduling. Workflows adapt their own structure based on project characteristics, and the system proposes strategic improvements with risk assessment and human review workflows.

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
| M6.2: MAF Server | WorkflowRunner API, persistent run history (SQLite), CLI client (trigger/status/logs), API key auth, 74 tests |
| M6.1: Progressive Autonomy | Trust-based agent escalation (5 levels), approval routing matrix, budget enforcement, emergency stop, shadow mode, 136 tests |
| M6.3: Multi-Product Templates | Copy-and-stamp template system (4 product types, 42 YAML configs), template registry/generator, CLI commands, quality gate presets, 63 tests |
| M7.1: Self-Modifying Lifecycle | Pre-compilation workflow adaptation (project classifier, profile registry, lifecycle adapter), A/B testing, rollback monitoring, 103 tests |
| M7.2: Strategic Autonomy | Goal proposal framework (4 analyzers, proposer, safety policy, review workflow), CLI + dashboard, cross-product learning, 101 tests |

**Post-Milestone Improvements:**

- Domain-based modular monolith migration (23 technical-layer modules to 13 domain-based modules)
- Quality score 85 to 100/100 (A+) with zero deductions
- LLMService extraction (clean separation of LLM call lifecycle)
- Observability: structured logging, OpenTelemetry, error fingerprinting, resilience tracking, cost rollup, data lineage, prompt versioning; async support, sampling, health monitoring, span cleanup (9 gaps closed)
- Parallel test execution (pytest-xdist), architecture scanner v2.4.0
- ExperimentService wired into optimization engine — Selection, Refinement, and Tuning optimizers now track experiments via `src/experimentation/` A/B testing engine
- Conversation history for stage:agent re-invocations — agents retain multi-turn context when re-invoked in workflow loops/branches

**Available Foundation:**

- `src/experimentation/` — production-ready A/B testing engine (v1.0.0, 101 tests): experiment lifecycle, variant assignment (hash/random), statistical analysis (t-test, SPRT, Bayesian), guardrails, config merging with security validation
- `src/observability/merit_score_service.py` — agent merit scoring (not connected to safety)

**Completed and Removed:**

- `src/self_improvement/` — deleted (~50 files of speculative M5 loop code). Replaced by `src/improvement/` (composable optimization engine, ~750 lines, 85 tests)

---

## Phase I: Intelligence Layer (M5)

**Value Proposition:** The framework stops producing "whatever the LLM gives you" and starts producing the output you actually want. A composable optimization engine lets users define how output quality is evaluated, then automatically refines, selects, and tunes until the target is met — all driven by workflow config.

**Key Capabilities:**
- Composable evaluators: criteria (pass/fail), comparative (A vs B), scored (0-1), human-in-the-loop
- Composable optimizers: iterative refinement (critique loop), best-of-N selection, statistical config tuning
- Any optimizer can use any evaluator — radical modularity via configuration
- Config tuning delegates to the proven `src/experimentation/` A/B testing engine
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

### M5.1: Optimization Engine — COMPLETE

Deleted `src/self_improvement/` (untested, speculative) and built a composable optimization engine in `src/improvement/`. Users configure evaluators (how to judge quality) and optimizers (how to improve) as a pipeline in workflow YAML. Engine is wired into `maf run` — workflows with an `optimization:` block automatically invoke the pipeline.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `OptimizationEngine` | `src/improvement/engine.py` | Done — pipeline orchestrator |
| `OptimizationConfig` / schemas | `src/improvement/_schemas.py` | Done — Pydantic models |
| `EvaluatorProtocol` / `OptimizerProtocol` | `src/improvement/protocols.py` | Done |
| `CriteriaEvaluator` | `src/improvement/evaluators/criteria.py` | Done — programmatic + LLM checks |
| `ComparativeEvaluator` | `src/improvement/evaluators/comparative.py` | Done |
| `ScoredEvaluator` | `src/improvement/evaluators/scored.py` | Done |
| `HumanEvaluator` | `src/improvement/evaluators/human.py` | Done |
| `SelectionOptimizer` | `src/improvement/optimizers/selection.py` | Done — best of N re-rolls |
| `RefinementOptimizer` | `src/improvement/optimizers/refinement.py` | Done — LLM critique loop |
| `TuningOptimizer` | `src/improvement/optimizers/tuning.py` | Done — strategy search (ExperimentService optional) |
| `OptimizationRegistry` | `src/improvement/registry.py` | Done |
| CLI wiring | `src/interfaces/cli/main.py` | Done — `_CLIWorkflowRunner`, `_CritiqueLLM` adapter |
| Workflow schema | `src/workflow/_schemas.py` | Done — `optimization: Optional[OptimizationConfig]` |
| Unit tests | `tests/test_improvement/` | Done — 85 tests |

**Demo Workflows (all tested end-to-end with `maf run`):**

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

**Dependencies:** None (builds on M4 foundation + existing `src/experimentation/`)

---

### M5.2: Agent Memory — COMPLETE

Persistent memory across sessions and workflow runs with pluggable backends.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `MemoryService` | `src/memory/service.py` | Done — retrieve_context, retrieve_with_shared, store_episodic/procedural/cross_session, decay, pruning |
| `MemoryScope` / schemas | `src/memory/_schemas.py` | Done — scope model (tenant, workflow, agent, namespace) |
| Memory constants | `src/memory/constants.py` | Done — providers, types, limits |
| `InMemoryAdapter` | `src/memory/adapters/in_memory.py` | Done — dict-based, thread-safe (testing/fallback) |
| `SQLiteAdapter` | `src/memory/adapters/sqlite_adapter.py` | Done — zero-dependency persistent backend, LIKE + FTS5 opt-in |
| `Mem0Adapter` | `src/memory/adapters/mem0_adapter.py` | Done — vector search via Mem0 (optional dependency) |
| `MemoryStoreProtocol` | `src/memory/protocols.py` | Done — runtime-checkable adapter contract |
| `MemoryProviderRegistry` | `src/memory/registry.py` | Done — thread-safe singleton, lazy loading |
| Procedural extraction | `src/memory/extractors.py` | Done — LLM-based pattern extraction from agent output |
| Agent memory injection | `src/agent/standard_agent.py` | Done — `_inject_memory_context()`, `_on_after_run()`, shared scope retrieval, procedural extraction |
| Agent memory config | `src/storage/schemas/agent_config.py` | Done — `MemoryConfig` (enabled, provider, decay_factor, max_episodes, auto_extract_procedural, shared_namespace) |
| CLI memory commands | `src/interfaces/cli/memory_commands.py` | Done — list/add/search/clear/seed with `--db-path` for SQLite |
| Decay & pruning | `src/memory/service.py` | Done — exponential time-decay (`_apply_decay`), max-episodes pruning (`_enforce_max_episodes`) |
| Cross-agent sharing | `src/memory/service.py` | Done — `build_shared_scope()`, `retrieve_with_shared()` (dual-scope search with dedup) |
| Demo configs | `configs/agents/memory_researcher.yaml`, `configs/workflows/memory_demo.yaml` | Done |
| Tests | `tests/test_memory/` | Done — 163 tests |

**Key Capabilities:**
- **3 backends:** in_memory (testing), SQLite (zero-dep persistence), Mem0 (vector search)
- **Decay & pruning:** Exponential time-decay on relevance scores; oldest-first pruning when max_episodes exceeded
- **LLM extraction:** Auto-extract procedural patterns from agent output (opt-in via `auto_extract_procedural: true`)
- **Cross-agent sharing:** Agents store/retrieve from both private and shared namespaces (opt-in via `shared_namespace`)

**Key Files:**
- `src/memory/` module (service, adapters, extractors, schemas, protocols, registry)
- `src/agent/standard_agent.py` (memory injection, extraction, sharing)
- `src/storage/schemas/agent_config.py` (`MemoryConfig` in `AgentConfig`)
- `src/interfaces/cli/memory_commands.py` (CLI management)

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
| `AgentPerformanceMiner` | `src/learning/miners/agent_performance.py` | Done — detects slow/unreliable agents |
| `ModelEffectivenessMiner` | `src/learning/miners/model_effectiveness.py` | Done — identifies error-prone/expensive models |
| `FailurePatternMiner` | `src/learning/miners/failure_patterns.py` | Done — finds recurring error signatures |
| `CostPatternMiner` | `src/learning/miners/cost_patterns.py` | Done — detects cost-dominant agents |
| `CollaborationPatternMiner` | `src/learning/miners/collaboration_patterns.py` | Done — finds debate inefficiencies |
| `MiningOrchestrator` | `src/learning/orchestrator.py` | Done — runs all miners, deduplicates, publishes to MemoryService |
| `BackgroundMiningJob` | `src/learning/background.py` | Done — 6-hour async loop with convergence-aware skip |
| `RecommendationEngine` | `src/learning/recommender.py` | Done — pattern→config change mapping (model, timeout, tokens, retries, debate rounds) |
| `AutoTuneEngine` | `src/learning/auto_tune.py` | Done — preview + apply YAML config changes |
| `ConvergenceDetector` | `src/learning/convergence.py` | Done — moving avg novelty (10-run window, 0.1 threshold) |
| `LearningDataService` | `src/learning/dashboard_service.py` | Done — API data aggregation |
| Dashboard routes | `src/learning/dashboard_routes.py` | Done — 6 endpoints (`/api/learning/`) |
| Dashboard UI | `src/interfaces/dashboard/static/learning.html` | Done — Plotly charts, pattern/convergence/recommendations |
| `LearningStore` | `src/learning/store.py` | Done — SQLite persistence (WAL mode) |
| Learning models | `src/learning/models.py` | Done — `LearnedPattern`, `MiningRun`, `TuneRecommendation` (SQLModel) |
| CLI commands | `src/interfaces/cli/learning_commands.py` | Done — `maf learning mine\|patterns\|recommend\|tune\|stats` |
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
| `AutonomyLevel` enum + `AutonomyConfig` | `src/safety/autonomy/schemas.py` | Done — 5 levels (Supervised→Strategic), config with enabled=False default |
| `AutonomyState/Transition/Budget/Emergency` models | `src/safety/autonomy/models.py` | Done — 4 SQLModel tables |
| `AutonomyStore` | `src/safety/autonomy/store.py` | Done — SQLite/WAL CRUD for all 4 tables |
| `TrustEvaluator` | `src/safety/autonomy/trust_evaluator.py` | Done — reads AgentMeritScore, checks thresholds |
| `AutonomyManager` | `src/safety/autonomy/manager.py` | Done — state machine with cooldown, max-level cap, threading.Lock |
| `BudgetEnforcer` | `src/safety/autonomy/budget_enforcer.py` | Done — per-scope spending tracking, cost estimation from model_pricing.yaml |
| `ApprovalRouter` | `src/safety/autonomy/approval_router.py` | Done — severity × level decision matrix, spot-check sampling |
| `AutonomyPolicy` | `src/safety/autonomy/policy.py` | Done — BaseSafetyPolicy subclass, emergency/budget/approval checks |
| `MeritSafetyBridge` | `src/safety/autonomy/merit_bridge.py` | Done — rate-limited bridge from merit updates to autonomy evaluation |
| `EmergencyStopController` | `src/safety/autonomy/emergency_stop.py` | Done — O(1) threading.Event, activate/deactivate, check_or_raise |
| `ShadowMode` | `src/safety/autonomy/shadow_mode.py` | Done — non-blocking shadow validation, agreement tracking, promotion readiness |
| CLI commands | `src/interfaces/cli/autonomy_commands.py` | Done — status, escalate, deescalate, emergency-stop, resume, budget, history |
| Dashboard routes + UI | `src/safety/autonomy/dashboard_routes.py`, `autonomy.html` | Done — 8 endpoints, Plotly charts |
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

### M6.2: MAF Server — COMPLETE

Expose the framework as an API service that external products can integrate with.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| `WorkflowRunner` API | `src/interfaces/server/workflow_runner.py` | Done — sync `run()` with `on_event` callback, typed `WorkflowRunResult` |
| `ServerRun` model | `src/interfaces/server/models.py` | Done — SQLModel with JSON columns for input/result |
| `RunStore` persistence | `src/interfaces/server/run_store.py` | Done — SQLite-backed CRUD, WAL mode, status filtering |
| `APIKeyMiddleware` | `src/interfaces/server/auth.py` | Done — env-var controlled, health/WebSocket bypass |
| `MAFServerClient` | `src/interfaces/cli/server_client.py` | Done — httpx-based HTTP client |
| CLI: `maf trigger` | `src/interfaces/cli/main.py` | Done — POST /api/runs, `--wait` polls until complete |
| CLI: `maf status` | `src/interfaces/cli/main.py` | Done — single run detail or list table |
| CLI: `maf logs` | `src/interfaces/cli/main.py` | Done — HTTP events or `--follow` WebSocket stream |
| GET /api/runs | `src/interfaces/server/routes.py` | Done — list with status filter, pagination |
| Alembic migration | `alembic/versions/e6f7a8b90123_add_server_runs.py` | Done — `server_runs` table |
| Tests | `tests/test_interfaces/test_server/` | Done — 74 tests |

**Key Capabilities:**
- `WorkflowRunner` library API for programmatic embedding (any Python program)
- Persistent run history survives server restarts (SQLite)
- CLI client commands (`trigger`, `status`, `logs`) talk to running server via HTTP
- API key authentication via `MAF_API_KEY` env var (disabled in dev mode)
- `ExecutionService` delegates to `WorkflowRunner`, persists status transitions to `RunStore`

**Remaining Gaps (for future work):**
- **L3 container isolation:** Only L1 path restriction implemented; container-based workspace isolation deferred
- **PostgreSQL migration path:** SQLite remains the only backend; multi-user scenarios need PostgreSQL support
- **Rate limiting:** No request rate limiting on server endpoints

**Dependencies:** None

---

### M6.3: Multi-Product Templates — COMPLETE

Copy-and-stamp template system: users run `maf template create --type api --name my-api` and get a complete set of workflow/stage/agent configs generated from a proven template. No runtime merge complexity — configs are standalone once created.

**What Was Built:**

| Component | File(s) | Status |
|-----------|---------|--------|
| Template schemas | `src/workflow/templates/_schemas.py` | Done — TemplateManifest, TemplateQualityGates, TemplateDefaultInference |
| Template registry | `src/workflow/templates/registry.py` | Done — discover, validate, cache manifests |
| Template generator | `src/workflow/templates/generator.py` | Done — copy-and-stamp with `{{project_name}}`, inference overrides, quality gates |
| Quality gate presets | `src/workflow/templates/quality_gates.py` | Done — per-product defaults (web_app, api, data_pipeline, cli_tool) |
| Template YAML configs | `configs/templates/{web_app,api,data_pipeline,cli_tool}/` | Done — 42 files (4 manifests + 4 workflows + 17 stages + 17 agents) |
| CLI commands | `src/interfaces/cli/template_commands.py` | Done — `maf template list\|info\|create` |
| Product type expansion | `src/workflow/_schemas.py` | Done — added `data_pipeline`, `cli_tool` to Literal |
| Unit + integration tests | `tests/test_workflow/test_templates/`, `tests/test_interfaces/test_template_cli.py` | Done — 63 tests |

**CLI Commands:**

```bash
maf template list                                    # List available templates
maf template info api                                # Show template details + quality gates
maf template create --type api --name my-api         # Generate project configs
maf template create --type web_app --name mysite \
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
| `ProjectClassifier` | `src/lifecycle/classifier.py` | Done — LLM-based + explicit-input fallback classification |
| `ProfileRegistry` | `src/lifecycle/profiles.py` | Done — YAML + DB merge, profile matching |
| `LifecycleAdapter` | `src/lifecycle/adapter.py` | Done — classify → match → autonomy gate → apply rules (SKIP/ADD/REORDER/MODIFY) → audit |
| `HistoryAnalyzer` | `src/lifecycle/history.py` | Done — historical outcome analysis for adaptation decisions |
| `LifecycleExperimenter` | `src/lifecycle/experiment.py` | Done — wraps ExperimentService for A/B testing lifecycle variants |
| `RollbackMonitor` | `src/lifecycle/rollback.py` | Done — degradation detection, automatic rollback |
| `LifecycleStore` | `src/lifecycle/store.py` | Done — SQLite/WAL persistence |
| Lifecycle models | `src/lifecycle/models.py` | Done — SQLModel tables |
| Lifecycle schemas | `src/lifecycle/_schemas.py` | Done — Pydantic models, LifecycleConfig in WorkflowConfigInner |
| CLI commands | `src/interfaces/cli/lifecycle_commands.py` | Done — `maf lifecycle profiles\|classify\|preview\|history\|check` |
| Dashboard routes | `src/lifecycle/dashboard_routes.py` | Done — 4 API endpoints |
| Profile configs | `configs/lifecycle/{lean_small_projects,security_aware}.yaml` | Done |
| Demo workflow | `configs/workflows/lifecycle_demo.yaml` | Done |
| CLI wiring | `src/interfaces/cli/main.py` | Done — `_maybe_adapt_lifecycle()` between load and compile |
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
| Goal schemas | `src/goals/_schemas.py` | Done — GoalType, GoalStatus, GoalRiskLevel, GoalProposal, RiskAssessment, ImpactEstimate, GoalEvidence |
| Goal models | `src/goals/models.py` | Done — GoalProposalRecord, AnalysisRun (SQLModel) |
| `GoalStore` | `src/goals/store.py` | Done — SQLite/WAL CRUD, filtering, counting |
| `PerformanceAnalyzer` | `src/goals/analyzers/performance.py` | Done — slow stages, degradation detection |
| `CostAnalyzer` | `src/goals/analyzers/cost.py` | Done — high-cost agents, expensive model detection |
| `ReliabilityAnalyzer` | `src/goals/analyzers/reliability.py` | Done — recurring errors, high failure rate agents |
| `CrossProductAnalyzer` | `src/goals/analyzers/cross_product.py` | Done — cross-product performance gaps, pattern transfer |
| `GoalProposer` | `src/goals/proposer.py` | Done — orchestrates analyzers, deduplicates, scores (weighted formula), persists |
| `AnalysisOrchestrator` | `src/goals/analysis_orchestrator.py` | Done — runs proposer, records analysis run metadata |
| `BackgroundAnalysisJob` | `src/goals/background.py` | Done — periodic async loop for server mode |
| `GoalSafetyPolicy` | `src/goals/safety_policy.py` | Done — rate limits, risk validation, auto-approve matrix by autonomy level |
| `GoalReviewWorkflow` | `src/goals/review_workflow.py` | Done — state machine (proposed→approved/rejected/deferred), acceptance rate tracking |
| `GoalDataService` | `src/goals/dashboard_service.py` | Done — dashboard data aggregation |
| Dashboard routes | `src/goals/dashboard_routes.py` | Done — 8 endpoints (list, detail, stats, runs, analyze, approve, reject, defer) |
| CLI commands | `src/interfaces/cli/goal_commands.py` | Done — `maf goals list\|propose\|review\|approve\|reject\|status` |
| CLI wiring | `src/interfaces/cli/main.py` | Done — `goals_group` mounted |
| Dashboard wiring | `src/interfaces/dashboard/app.py` | Done — goals router mounted |
| Constants | `src/goals/constants.py` | Done — thresholds, weights, limits |
| Tests | `tests/test_goals/` | Done — 101 tests |

**Key Capabilities:**
- **4 analyzers** scan execution history: performance (slow/degrading stages), cost (expensive agents/models), reliability (recurring errors, high failure rates), cross-product (performance gaps, pattern transfer)
- **Weighted scoring:** 0.35×impact + 0.25×confidence + 0.20×(1/effort) + 0.20×(1/risk)
- **Deduplication:** SHA256 hash of goal_type + title, skips if matching active proposal exists
- **Safety policy:** Rate limiting (20/day), auto-approve matrix by autonomy level (SUPERVISED=never, RISK_GATED=low, AUTONOMOUS=medium, STRATEGIC=high, CRITICAL=never)
- **Review workflow:** State machine with PROPOSED→UNDER_REVIEW→APPROVED/REJECTED/DEFERRED transitions
- **Cross-product learning:** CrossProductAnalyzer cross-references LearnedPattern data with product-type execution metrics
- **Budget integration:** Read-only checks against BudgetEnforcer for cost-impacting proposals
- **CLI:** `maf goals propose` runs analysis, `maf goals list` shows results, `maf goals approve/reject` applies decisions

**Remaining Gaps (for future work):**
- **Empirical acceptance rate:** Framework tracks acceptance rate but needs 50+ proposals to validate 50%+ target
- **Auto-execution of approved goals:** Currently proposals are informational; approved goals don't auto-trigger workflow changes

**Dependencies:** M7.1 (adaptive lifecycle), M5.2 (memory for cross-product learning)

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
| M5.1 Optimization Engine | V3 | VCS can optimize triage accuracy via evaluator pipeline |
| M5.2 Agent Memory | V3 | Agents remember past triage patterns |
| M6.1 Progressive Autonomy | V4 | VCS earns trust for auto-implementation |
| M6.2 MAF Server | V2 | VCS web app triggers pipelines via API |
| M7.2 Strategic Autonomy | V4 | VCS proposes features autonomously |

---

# Part 4: Timeline

```
2026 Q1            M5.1 Optimization Engine ✓ COMPLETE
2026 Q1            M5.2 Agent Memory ✓ COMPLETE
2026 Q1            M6.2 MAF Server ✓ COMPLETE
2026 Q1            M5.3 Continuous Learning ✓ COMPLETE
2026 Q1            M6.1 Progressive Autonomy ✓ COMPLETE
2026 Q1            M6.3 Multi-Product Templates ✓ COMPLETE
2026 Q1            M7.1 Self-Modifying Lifecycle ✓ COMPLETE
2026 Q1            M7.2 Strategic Autonomy ✓ COMPLETE
2026 Q2 (Now)     V2 VCS Web App + V3 Self-Improving VCS
2026 Q3            V4 Autonomous VCS
2026 Q4            M7.3 Portfolio Management
```

## Milestone Dependency Graph

```
M5.1 Optimization Engine ✓ COMPLETE
 ├──→ M5.2 Agent Memory ✓ COMPLETE
 │     ├──→ M5.3 Continuous Learning ✓ COMPLETE
 │     │     └──→ M7.1 Self-Modifying Lifecycle ✓ COMPLETE ──→ M7.2 Strategic Autonomy ✓ COMPLETE ──→ M7.3 Portfolio Management
 │     └──→ M7.2 Strategic Autonomy ✓ COMPLETE
 └──→ M6.1 Progressive Autonomy ✓ COMPLETE
       └──→ M7.1 Self-Modifying Lifecycle ✓ COMPLETE

M6.2 MAF Server ✓ COMPLETE
 └──→ M6.3 Multi-Product Templates ✓ COMPLETE ──→ M7.3 Portfolio Management
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
| ~~Speculative M5 code as tech debt~~ | ~~50 files of untested code blocking fresh design~~ | ~~High~~ | ~~Resolved: `src/self_improvement/` deleted, `src/improvement/` built and tested (85 tests)~~ |
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

**Last Updated:** 2026-02-16
