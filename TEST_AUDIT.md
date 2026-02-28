# Test Coverage Audit — Temper AI

**Generated:** 2026-02-28
**Target:** 90% line coverage, full branch/edge-case coverage, e2e for major features
**Total Source Files:** 543 | **Total Test Files:** 564

---

## Executive Summary

| Status | Modules | Count |
|--------|---------|-------|
| CRITICAL (<70%) | llm, interfaces, mcp | 3 |
| BELOW TARGET (70-89%) | memory, stage, shared, agent, lifecycle, plugins, workflow, registry, observability, tools, portfolio | 11 |
| MEETS TARGET (90%+) | auth, events, evaluation, goals, safety, learning, storage, optimization, autonomy, experimentation, config | 11 |

**Overall:** 25 modules audited. 14 modules below 90% target. ~94 test failures across all modules.

---

## Module-by-Module Coverage

### CRITICAL — Needs Immediate Attention

#### 1. `llm` — 48% coverage (2666 stmts, 1391 missed)
- **Tests:** 165 passed, 0 failed
- **Worst files:**
  - `providers/vllm_provider.py` — 15% (194 stmts, 165 missed)
  - `providers/ollama.py` — 17% (153 stmts, 127 missed)
  - `providers/openai_provider.py` — 17% (126 stmts, 104 missed)
  - `_prompt.py` — 18% (57 stmts, 47 missed)
  - `providers/_base_helpers.py` — 19% (236 stmts, 191 missed)
  - `_retry.py` — 23% (57 stmts, 44 missed)
  - `cost_estimator.py` — 27% (15 stmts, 11 missed)
  - `_tracking.py` — 28% (46 stmts, 33 missed)
  - `_tool_execution.py` — 30% (109 stmts, 76 missed)
  - `providers/factory.py` — 31% (45 stmts, 31 missed)
  - `providers/anthropic_provider.py` — 33% (30 stmts, 20 missed)
  - `conversation.py` — 0% (33 stmts, 33 missed)
  - `prompts/dialogue_formatter.py` — 0% (66 stmts, 66 missed)
  - `pricing.py` — 41% (136 stmts, 80 missed)
  - `providers/base.py` — 49% (263 stmts, 134 missed)
  - `failover.py` — 63% (154 stmts, 57 missed)
- **Gaps:** All LLM providers barely tested; retry/failover/tool execution logic untested; prompt engine partial
- **Priority:** P0 — core functionality
- [ ] **DONE**

#### 2. `interfaces` — 56% coverage (2507 stmts, 1113 missed)
- **Tests:** 126 passed, 0 failed
- **Worst files:**
  - `server/auth_routes.py` — 0% (137 stmts, 137 missed)
  - `server/config_routes.py` — 0% (64 stmts, 64 missed)
  - `cli/__main__.py` — 0% (3 stmts, 3 missed)
  - `server/visualize_routes.py` — 27% (74 stmts, 54 missed)
  - `server/routes.py` — 33% (179 stmts, 120 missed)
  - `server/lifecycle.py` — 37% (43 stmts, 27 missed)
  - `cli/main.py` — 38% (73 stmts, 45 missed)
  - `server/rollback_routes.py` — 41% (64 stmts, 38 missed)
  - `server/plugin_routes.py` — 41% (54 stmts, 32 missed)
  - `server/checkpoint_routes.py` — 42% (57 stmts, 33 missed)
  - `server/template_routes.py` — 44% (63 stmts, 35 missed)
  - `server/optimization_routes.py` — 45% (77 stmts, 42 missed)
  - `server/agent_routes.py` — 46% (61 stmts, 33 missed)
  - `server/health.py` — 46% (26 stmts, 14 missed)
  - `server/memory_routes.py` — 47% (87 stmts, 46 missed)
  - `server/scaffold_routes.py` — 49% (49 stmts, 25 missed)
  - `server/chat_routes.py` — 50% (78 stmts, 39 missed)
  - `server/event_routes.py` — 54% (63 stmts, 29 missed)
  - `dashboard/studio_service.py` — 59% (217 stmts, 89 missed)
  - `dashboard/visualize_trace.py` — 67% (in observability, not here)
  - `dashboard/websocket.py` — 69% (138 stmts, 43 missed)
  - `dashboard/studio_routes.py` — 70% (139 stmts, 42 missed)
  - `dashboard/app.py` — 73% (232 stmts, 62 missed)
  - `dashboard/routes.py` — 74% (95 stmts, 25 missed)
- **Gaps:** Nearly all server routes untested or barely tested; CLI untested; dashboard partial
- **Priority:** P0 — API surface area
- [ ] **DONE**

#### 3. `mcp` — 67% coverage (437 stmts, 143 missed)
- **Tests:** 61 passed, 0 failed
- **Worst files:**
  - `__init__.py` — 17% (12 stmts, 10 missed)
  - `manager.py` — 51% (121 stmts, 59 missed)
  - `server.py` — 61% (139 stmts, 54 missed)
  - `_client_helpers.py` — 73% (30 stmts, 8 missed)
- **Gaps:** MCP manager connection lifecycle, server endpoint registration, initialization
- **Priority:** P1
- [ ] **DONE**

---

### BELOW TARGET — Needs Improvement

#### 4. `memory` — 72% coverage (724 stmts, 200 missed)
- **Tests:** 196 passed, 0 failed
- **Worst files:**
  - `adapters/pg_adapter.py` — 0% (172 stmts, 172 missed)
  - `registry.py` — 76% (51 stmts, 12 missed)
- **Gaps:** Postgres adapter completely untested; registry partial
- [ ] **DONE**

#### 5. `stage` — 75% coverage (1957 stmts, 499 missed)
- **Tests:** 165 passed, 0 failed
- **Worst files:**
  - `executors/_dialogue_helpers.py` — 38% (245 stmts, 152 missed)
  - `executors/base.py` — 47% (101 stmts, 54 missed)
  - `executors/_base_helpers.py` — 48% (132 stmts, 69 missed)
  - `_config_accessors.py` — 58% (77 stmts, 32 missed)
  - `executors/_sequential_retry.py` — 69% (91 stmts, 28 missed)
  - `executors/_parallel_observability.py` — 76% (55 stmts, 13 missed)
  - `executors/_agent_execution.py` — 78% (40 stmts, 9 missed)
  - `executors/_parallel_helpers.py` — 80% (214 stmts, 43 missed)
- **Gaps:** Dialogue helpers, base executor, retry logic, quality gates
- [ ] **DONE**

#### 6. `shared` — 75% coverage (2108 stmts, 531 missed)
- **Tests:** 342 passed, 0 failed
- **Worst files:**
  - `core/service.py` — 0% (10 stmts, 10 missed)
  - `utils/exception_fields.py` — 0% (12 stmts, 12 missed)
  - `core/_circuit_breaker_helpers.py` — 17% (175 stmts, 146 missed)
  - `utils/datetime_utils.py` — 25% (28 stmts, 21 missed)
  - `core/__init__.py` — 30% (10 stmts, 7 missed)
  - `core/circuit_breaker.py` — 35% (268 stmts, 173 missed)
  - `utils/path_safety/temp_directory.py` — 44% (43 stmts, 24 missed)
  - `utils/path_safety/platform_detector.py` — 55% (31 stmts, 14 missed)
  - `core/test_support.py` — 63% (67 stmts, 25 missed)
  - `constants/timeouts.py` — 0% (5 stmts, 5 missed)
- **Gaps:** Circuit breaker (core reliability pattern!) at 35%; temp directory, datetime utils
- [ ] **DONE**

#### 7. `agent` — ~85% coverage (improved from 77%)
- **Tests:** 7 failed, 1095 passed (was 880)
- **Improvements (2026-02-28):**
  - Added 5 new test files: `test_static_checker_agent.py` (41), `test_agent_response.py` (36), `test_standard_agent_helpers.py` (42), `test_strategies/test_concatenate.py` (26), `test_strategies/test_dialogue_helpers.py` (49)
  - Added 22 tests to `test_multi_round.py`, 4 to `test_registry.py`
  - Fixed 10 conditional assertions, 3 misleading names, 3 dead tests, ABC signature
  - Improved `test_agent_state_machine.py` from 3/10 to 7/10
- **Remaining worst files:**
  - `_r0_pipeline_helpers.py` — 29% (70 stmts, 50 missed)
  - `__init__.py` — 33% (12 stmts, 8 missed)
  - `standard_agent.py` — 61% (223 stmts, 87 missed)
  - `utils/agent_observer.py` — 68% (50 stmts, 16 missed)
  - `base_agent.py` — 70% (217 stmts, 66 missed)
- **Failing tests:** `test_llm_async.py::TestAsyncErrorPaths` (4), `test_standard_agent.py` (2), `test_pricing.py` (1) — pre-existing
- **Gaps:** Standard agent (core!), base agent lifecycle
- [x] **DONE** (test quality audit 8.5/10)

#### 8. `lifecycle` — 80% coverage (748 stmts, 146 missed)
- **Tests:** 100 passed, 0 failed
- **Worst files:**
  - `dashboard_routes.py` — 0% (62 stmts, 62 missed)
  - `rollback.py` — 58% (66 stmts, 28 missed)
  - `history.py` — 71% (49 stmts, 14 missed)
  - `adapter.py` — 83% (204 stmts, 34 missed)
- **Gaps:** Dashboard routes untested, rollback logic partial
- [ ] **DONE**

#### 9. `plugins` — 80% coverage (424 stmts, 85 missed)
- **Tests:** 195 passed, 0 failed
- **Worst files:**
  - `__init__.py` — 23% (13 stmts, 10 missed)
  - `registry.py` — 53% (74 stmts, 35 missed)
  - `adapters/openai_agents_adapter.py` — 79% (43 stmts, 9 missed)
  - `adapters/crewai_adapter.py` — 81% (48 stmts, 9 missed)
  - `adapters/autogen_adapter.py` — 82% (62 stmts, 11 missed)
  - `adapters/langgraph_adapter.py` — 82% (50 stmts, 9 missed)
- **Gaps:** Plugin registry loading, adapter initialization
- [ ] **DONE**

#### 10. `workflow` — 83% coverage (4086 stmts, 678 missed)
- **Tests:** 2 failed, 987 passed, 3 skipped
- **Worst files:**
  - `stage_compiler.py` — 38% (313 stmts, 195 missed)
  - `output_extractor.py` — 60% (80 stmts, 32 missed)
  - `execution_service.py` — 69% (217 stmts, 68 missed)
  - `node_builder.py` — 73% (135 stmts, 36 missed)
  - `engines/langgraph_compiler.py` — 77% (113 stmts, 26 missed)
  - `execution_engine.py` — 77% (43 stmts, 10 missed)
  - `config_loader.py` — 83% (150 stmts, 25 missed)
  - `routing_functions.py` — 85% (82 stmts, 12 missed)
  - `_schemas.py` — 86% (152 stmts, 22 missed)
  - `runtime.py` — 86% (206 stmts, 29 missed)
  - `db_config_loader.py` — 0% (42 stmts, 42 missed)
- **Failing tests:** `test_langgraph_engine.py::TestIntegration::test_metadata_and_visualize_integration`
- **Gaps:** Stage compiler (critical), output extractor, execution service
- [ ] **DONE**

#### 11. `registry` — 84% coverage (179 stmts, 29 missed)
- **Tests:** 34 failed, 53 passed
- **Worst files:**
  - `service.py` — 70% (43 stmts, 13 missed)
  - `store.py` — 80% (79 stmts, 16 missed)
- **Gaps:** Service CRUD operations, store persistence
- [ ] **DONE**

#### 12. `observability` — 85% coverage (5234 stmts, 799 missed)
- **Tests:** 26 failed, 1410 passed, 30 skipped
- **Worst files:**
  - `types.py` — 0% (10 stmts, 10 missed)
  - `trace_export.py` — 26% (43 stmts, 32 missed)
  - `otel_setup.py` — 35% (96 stmts, 62 missed)
  - `backends/otel_backend.py` — 37% (393 stmts, 246 missed)
  - `backends/__init__.py` — 47% (15 stmts, 8 missed)
  - `backends/composite_backend.py` — 56% (147 stmts, 64 missed)
  - `visualize_trace.py` — 67% (268 stmts, 89 missed)
  - `decision_tracker.py` — 76% (90 stmts, 22 missed)
  - `backend.py` — 79% (184 stmts, 39 missed)
  - `backends/_sql_backend_helpers.py` — 83% (368 stmts, 63 missed)
  - `backends/noop_backend.py` — 85% (73 stmts, 11 missed)
- **Gaps:** OTEL integration completely untested; trace export; composite backend
- [ ] **DONE**

#### 13. `tools` — 85% coverage (2730 stmts, 408 missed)
- **Tests:** 15 failed, 673 passed, 1 skipped
- **Worst files:**
  - `loader.py` — 19% (75 stmts, 61 missed)
  - `_executor_helpers.py` — 58% (272 stmts, 115 missed)
  - `_registry_helpers.py` — 77% (275 stmts, 64 missed)
  - `executor.py` — 81% (135 stmts, 25 missed)
  - `http_client.py` — 82% (74 stmts, 13 missed)
  - `calculator.py` — 83% (109 stmts, 18 missed)
  - `file_writer.py` — 84% (109 stmts, 17 missed)
  - `_bash_helpers.py` — 85% (183 stmts, 28 missed)
- **Gaps:** Tool loader, executor helpers, registry helpers
- [ ] **DONE**

#### 14. `portfolio` — 87% coverage (914 stmts, 123 missed)
- **Tests:** 106 passed, 0 failed
- **Worst files:**
  - `dashboard_routes.py` — 0% (61 stmts, 61 missed)
  - `store.py` — 89% (135 stmts, 15 missed)
  - `knowledge_graph.py` — 89% (211 stmts, 24 missed)
- **Gaps:** Dashboard routes completely untested
- [ ] **DONE**

---

### MEETS TARGET (90%+)

#### 15. `auth` — 90% (1475 stmts, 154 missed)
- **Tests:** 6 failed, 636 passed, 10 skipped
- **Worst files:**
  - `config_seed.py` — 0% (36 stmts)
  - `ws_tickets.py` — 0% (36 stmts)
  - `api_key_auth.py` — 80% (106 stmts, 21 missed)
  - `oauth/_token_store_helpers.py` — 84% (100 stmts, 16 missed)
- [ ] **DONE**

#### 16. `events` — 90% (314 stmts, 31 missed)
- **Tests:** 124 passed | **Gaps:** `__init__.py` 9%, `_subscription_helpers.py` 59%
- [ ] **DONE**

#### 17. `evaluation` — 90% (125 stmts, 13 missed)
- **Tests:** 37 passed | **Gaps:** `__init__.py` 33%, `runner.py` 88%
- [ ] **DONE**

#### 18. `goals` — 91% (896 stmts, 77 missed)
- **Tests:** 105 passed
- **Worst:** `dashboard_service.py` 46%, `background.py` 74%, `dashboard_routes.py` 78%
- [ ] **DONE**

#### 19. `safety` — 91% (4651 stmts, 414 missed)
- **Tests:** 1 failed, 1773 passed, 38 skipped
- **Worst:** `config_change_policy.py` 37%, `validation.py` 62%, `action_policy_engine.py` 75%
- [ ] **DONE**

#### 20. `learning` — 91% (653 stmts, 58 missed)
- **Tests:** 57 passed
- **Worst:** `dashboard_service.py` 42%, `background.py` 70%
- [ ] **DONE**

#### 21. `storage` — 91% (919 stmts, 87 missed)
- **Tests:** 53 passed
- **Worst:** `schemas/agent_config.py` 73%, `schemas/constants.py` 0% (2 stmts)
- [ ] **DONE**

#### 22. `optimization` — 93% (1487 stmts, 111 missed)
- **Tests:** 1 failed, 366 passed
- **Worst:** `dspy/__init__.py` 56%, `dspy/_helpers.py` 68%, `evaluation_dispatcher.py` 75%
- [ ] **DONE**

#### 23. `autonomy` — 95% (544 stmts, 28 missed)
- **Tests:** 141 passed | Minimal gaps
- [ ] **DONE**

#### 24. `experimentation` — 97% (1160 stmts, 39 missed)
- **Tests:** 400 passed | Minimal gaps
- [ ] **DONE**

#### 25. `config` — 98% (87 stmts, 2 missed)
- **Tests:** 38 passed | Near-perfect
- [ ] **DONE**

---

## Test Failures Summary

| Module | Failed | Passed | Skipped |
|--------|--------|--------|---------|
| agent | 7 | 1095 | 0 |
| auth | 6 | 636 | 10 |
| workflow | 2 | 987 | 3 |
| safety | 1 | 1773 | 38 |
| observability | 26 | 1410 | 30 |
| tools | 15 | 673 | 1 |
| optimization | 1 | 366 | 0 |
| registry | 34 | 53 | 0 |
| **TOTAL** | **93** | **6778** | **82** |

---

## Integration & E2E Test Coverage

**Integration tests exist in:** `tests/integration/` (19 files)
- `test_e2e_workflow.py` — End-to-end workflow execution
- `test_e2e_workflows.py` — Multiple workflow scenarios
- `test_m2_e2e.py` — Multi-agent e2e
- `test_m3_multi_agent.py` — Multi-agent scenarios
- `test_multi_agent_workflows.py` — Multi-agent workflows
- `test_agent_tool_integration.py` — Agent-tool integration
- `test_checkpoint_resume.py` — Checkpoint recovery
- `test_workflow_recovery.py` — Workflow recovery
- `test_error_propagation_e2e.py` — Error propagation
- `test_component_integration.py` — Component integration
- `test_cross_module.py` — Cross-module integration
- `test_compiler_engine_observability.py` — Compiler-observability integration
- `test_timeout_propagation.py` — Timeout handling
- `test_tool_rollback.py` — Tool rollback

**Missing E2E/Integration coverage:**
- [ ] Auth flow e2e (OAuth login → token refresh → session management)
- [ ] Dashboard WebSocket e2e (connect → subscribe → receive events)
- [ ] MCP server lifecycle e2e (start → register tools → handle requests → shutdown)
- [ ] LLM failover e2e (primary failure → fallback → recovery)
- [ ] Safety circuit breaker e2e (normal → trip → half-open → recovery)
- [ ] Full optimization pipeline e2e (collect data → optimize → deploy → evaluate)
- [ ] Plugin adapter e2e per framework (CrewAI, AutoGen, LangGraph, OpenAI Agents)
- [ ] Learning pipeline e2e (mine patterns → generate recommendations → apply)
- [ ] Portfolio optimization e2e (load → analyze → optimize → schedule)

---

## Prioritized Action Plan

### Phase 1: Fix Test Failures (93 failures)
1. Fix registry failures (34 failures — likely a systemic issue)
2. Fix observability failures (26 failures)
3. Fix tools failures (15 failures)
4. Fix agent failures (8 failures)
5. Fix auth failures (6 failures)
6. Fix workflow failures (2 failures)
7. Fix safety + optimization failures (1+1 failures)

### Phase 2: Critical Coverage Gaps (<70%)
1. **LLM providers** — add unit tests for each provider (ollama, openai, vllm, anthropic)
2. **LLM core** — test retry, failover, tool execution, prompt engine
3. **Server routes** — test all REST API endpoints
4. **MCP manager** — test connection lifecycle
5. **Dashboard routes** — test all dashboard endpoints

### Phase 3: Below-Target Modules (70-89%)
1. Shared circuit breaker (35% → 90%)
2. Stage dialogue helpers (38% → 90%)
3. Workflow stage compiler (38% → 90%)
4. Agent standard agent (61% → 90%)
5. Remaining files below 80% in each module

### Phase 4: Edge Cases & Branch Coverage
- Review all modules at 90%+ for missing branches
- Add negative/error path tests
- Add boundary value tests
- Add concurrent/race condition tests for async code

### Phase 5: Missing E2E/Integration Tests
- Add integration tests listed in "Missing E2E" section above

---

## Progress Tracking

| Phase | Status | Completion |
|-------|--------|------------|
| Phase 1: Fix Failures | NOT STARTED | 0/93 |
| Phase 2: Critical Gaps | NOT STARTED | 0/3 modules |
| Phase 3: Below Target | NOT STARTED | 0/11 modules |
| Phase 4: Edge Cases | NOT STARTED | 0/11 modules |
| Phase 5: E2E Tests | NOT STARTED | 0/9 scenarios |
