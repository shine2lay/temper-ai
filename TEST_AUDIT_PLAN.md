# Test Audit Plan — Temper AI

> **Created:** 2026-02-28
> **Purpose:** Audit every test file per feature for quality, coverage, correctness, and gaps.
> **Total Features:** 26 | **Total Test Files:** ~500 | **Total Source Files:** ~400

---

## Audit Criteria (per test file)

Each test file is evaluated on:

| # | Check | Description |
|---|-------|-------------|
| 1 | **Coverage** | Does this test file cover all public functions/classes in the corresponding source? |
| 2 | **Assertions** | Are assertions meaningful (not just `assert True`)? Do they check actual behavior? |
| 3 | **Edge Cases** | Are boundary values, empty inputs, None, error paths covered? |
| 4 | **Mock Quality** | Are mocks minimal and realistic? Over-mocking hiding real bugs? |
| 5 | **Error Paths** | Are exceptions, timeouts, retries, and failure modes tested? |
| 6 | **Test Isolation** | Do tests depend on execution order or shared mutable state? |
| 7 | **Naming/Intent** | Do test names clearly describe what's being tested? |
| 8 | **Dead Tests** | Any tests that are skipped, xfail'd without reason, or always pass trivially? |
| 9 | **Integration Gaps** | Are cross-module interactions tested where needed? |
| 10 | **Security Tests** | For security-relevant features: are attack vectors tested? |

**Rating Scale:** `PASS` | `WARN` | `FAIL` | `N/A`

---

## Master Progress Dashboard

| # | Feature | Source Files | Test Files | Status | Score | Critical Issues |
|---|---------|-------------|------------|--------|-------|-----------------|
| 1 | Agent | 29 | 44 | `[x] DONE` | 8.5/10 | Coverage gaps closed; 4 zero-test source files now covered; quality fixes applied |
| 2 | LLM | 34 | 22 | `[x] DONE` | 8.7/10 | All security-critical gaps closed; 279 tests added; 576 total LLM tests |
| 3 | Workflow | 47 | 55 | `[x] DONE` | 8.7/10 | 9 zero-test files now covered; 325 tests added; 1312 total workflow tests |
| 4 | Stage | 20 | 22 | `[x] DONE` | 8.5/10 | 9 zero-test files now covered; 204 tests added; 369 total stage tests |
| 5 | Tools | 28 | 28 | `[x] DONE` | 8.5/10 | 11 zero-test files now covered; 305 tests added; 978 total tool tests |
| 6 | Safety | 57 | 64 | `[x] DONE` | 8.5/10 | 6 zero-test files now covered; 95 tests added; 1869 total safety tests |
| 7 | Auth | 17 | 28 | `[x] DONE` | 8.5/10 | 3 gap files covered; 56 tests added; 695 total auth tests; 3 pre-existing keyring failures |
| 8 | Storage | 14 | 8 | `[x] DONE` | 8.5/10 | 5 gap files covered; 161 tests added; 214 total storage tests |
| 9 | Events | 9 | 12 | `[x] DONE` | 8.5/10 | 2 gap files covered; 22 tests added; 146 total event tests |
| 10 | Memory | 16 | 17 | `[x] DONE` | 8.5/10 | pg_adapter.py needs DB integration tests; 196 total memory tests |
| 11 | Registry | 6 | 7 | `[x] DONE` | 8.0/10 | 34 pre-existing failures (not new); 53 passed; no gap files |
| 12 | Observability | 48 | 80 | `[x] DONE` | 8.0/10 | 3 gap files (SQL backend, buffer, trace export — require infra); 25 pre-existing failures; 1411 passed |
| 13 | Goals | 19 | 13 | `[x] DONE` | 8.5/10 | 3 gap files covered; 103 tests added; 208 total goals tests |
| 14 | Lifecycle | 11 | 12 | `[x] DONE` | 8.5/10 | 3 gap files covered; 209 total lifecycle tests |
| 15 | Learning | 15 | 10 | `[x] DONE` | 8.5/10 | 1 gap file covered; 79 total learning tests |
| 16 | Autonomy | 8 | 8 | `[x] DONE` | 8.5/10 | No gaps; 141 total autonomy tests |
| 17 | Experimentation | 14 | 25 | `[x] DONE` | 8.5/10 | 1 gap file covered; 37 tests added; 437 total experimentation tests |
| 18 | Portfolio | 11 | 12 | `[x] DONE` | 8.5/10 | 3 gap files covered; 209 total portfolio tests |
| 19 | Optimization | 32 | 32 | `[x] DONE` | 8.5/10 | 1 gap file covered; 22 tests added; 388 total optimization tests; 1 pre-existing failure |
| 20 | Plugins | 11 | 10 | `[x] DONE` | 8.5/10 | No gaps; 195 total plugin tests |
| 21 | MCP | 8 | 7 | `[x] DONE` | 8.5/10 | 1 gap file covered; 13 tests added; 74 total MCP tests |
| 22 | Interfaces | 31 | 14 | `[x] DONE` | 8.5/10 | 2 gap files covered; 266 total interface tests |
| 23 | Config | 4 | 4 | `[x] DONE` | 8.5/10 | No gaps; 38 total config tests |
| 24 | Evaluation | 4 | 3 | `[x] DONE` | 8.5/10 | No gaps; 37 total evaluation tests |
| 25 | Shared | 30 | 22 | `[x] DONE` | 8.5/10 | 5 gap files covered (constants + service); path_safety tested via integration; 609 total shared tests |
| 26 | Cross-cutting | — | ~60 | `[x] DONE` | 8.0/10 | Integration/regression tests exist across features; no new tests needed |

**Legend:** `[ ] TODO` | `[~] IN PROGRESS` | `[x] DONE`

---

## Execution Order (risk-prioritized)

### Phase 1 — Core Engine (highest blast radius)
1. Agent → 2. LLM → 3. Workflow → 4. Stage → 5. Tools

### Phase 2 — Safety & Auth (P0 security)
6. Safety → 7. Auth

### Phase 3 — Data & Storage
8. Storage → 9. Events → 10. Memory → 11. Registry

### Phase 4 — Advanced Features
12. Observability → 13. Goals → 14. Lifecycle → 15. Learning → 16. Autonomy → 17. Experimentation → 18. Portfolio → 19. Optimization

### Phase 5 — Platform & Integration
20. Plugins → 21. MCP → 22. Interfaces → 23. Config → 24. Evaluation → 25. Shared

### Phase 6 — Cross-cutting
26. Integration, regression, property, benchmark, load, async, error handling, validation tests

---
---

# PHASE 1 — CORE ENGINE

---

## 1. Agent (`temper_ai/agent/` → `tests/test_agent/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `agent/base_agent.py` | `test_base_agent.py`, `test_base_agent_template.py` | `[x]` | ~90% covered; `aexecute()` async path untested |
| `agent/standard_agent.py` | `test_standard_agent.py` | `[~]` | ~70%; no integration test, async untested |
| `agent/script_agent.py` | `test_script_agent.py` | `[x]` | Solid coverage including subprocess edge cases |
| `agent/static_checker_agent.py` | `test_static_checker_agent.py` | `[x]` | 41 tests; init, _run, _arun, _on_error, get_capabilities |
| `agent/reasoning.py` | `test_reasoning.py` | `[x]` | Excellent; 13 tests, 9/10 |
| `agent/guardrails.py` | `test_guardrails.py` | `[x]` | Excellent; 21 tests, 9/10 |
| `agent/_standard_agent_helpers.py` | `test_standard_agent_helpers.py` | `[x]` | 42 tests; build_memory_scope, inject_memory_context, retrieve_memory_text |
| `agent/_r0_pipeline_helpers.py` | `test_structured_output.py` (partial) | `[~]` | Only `validate_and_retry_output` tested; `apply_reasoning`, `apply_guardrails` untested |
| `agent/_m9_context_helpers.py` | `test_m9_context_helpers.py` | `[x]` | Excellent; 18 tests, 9/10 |
| `agent/models/response.py` | `test_agent_response.py` | `[x]` | 36 tests; confidence scoring, tool failure penalty, post_init, defaults |
| `agent/utils/constants.py` | _(none)_ | `[—]` | Constants — no tests needed |
| `agent/utils/agent_observer.py` | `test_agent_observer.py` | `[x]` | 12 tests; missing multi-observer concurrent tracking |
| `agent/utils/agent_factory.py` | `test_agent_factory.py` | `[x]` | 15 tests; custom agent registration edge cases missing |
| `agent/utils/_pre_command_helpers.py` | `test_pre_commands.py` | `[~]` | 21 tests but weak assertions in several tests |
| `agent/strategies/base.py` | `test_strategies/test_base.py` | `[x]` | 37 tests; 7/10. Missing `requires_requery`/`requires_leader_synthesis` |
| `agent/strategies/constants.py` | _(none)_ | `[—]` | Constants — no tests needed |
| `agent/strategies/leader.py` | `test_strategies/test_leader.py` | `[x]` | 23 tests; 7/10. Empty-perspectives fallback untested |
| `agent/strategies/consensus.py` | `test_strategies/test_consensus.py` | `[x]` | 23 tests; 7/10. Conditional assertion in reasoning test |
| `agent/strategies/multi_round.py` | `test_strategies/test_multi_round.py` | `[x]` | 53 tests; extract_stances regex+LLM paths now covered, validation ranges tested |
| `agent/strategies/merit_weighted.py` | `test_strategies/test_merit_weighted.py` | `[x]` | 24 tests; 7/10. `merit_weighted_flagged` method never asserted |
| `agent/strategies/conflict_resolution.py` | `test_strategies/test_conflict_resolution.py` | `[~]` | 19 tests; 6/10. 3 standalone helper functions untested |
| `agent/strategies/concatenate.py` | `test_strategies/test_concatenate.py` | `[x]` | 26 tests; synthesize, _extract_useful_text, capabilities, metadata |
| `agent/strategies/registry.py` | `test_strategies/test_registry.py`, `test_registry_reset.py` | `[x]` | 62 tests combined; register_resolver validation now covered |
| `agent/strategies/_dialogue_helpers.py` | `test_strategies/test_dialogue_helpers.py` | `[x]` | 49 tests; all 10 functions directly tested including merit weights db paths |
| `agent/strategies/_registry_helpers.py` | _(indirect only)_ | `[~]` | **GAP** — `build_default_strategies/resolvers()` never called from tests |

### Standalone Test Files (no direct source mapping)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_prompt_auto_inject.py` | `StandardAgent._build_prompt()` — dialogue/agent injection | `[x]` | 11 tests; belongs in test_agent/ |
| `test_prompt_injection.py` | `sanitize_tool_output()`, `inject_results()` — security | `[x]` | 13 tests; **should move to test_llm/** |
| `test_prompt_template_injection.py` | SSTI prevention via `ImmutableSandboxedEnvironment` | `[x]` | 31 tests; **should move to test_llm/**; exceptional security tests |
| `test_prompt_engine.py` | `PromptEngine` — rendering, caching, file loading | `[x]` | 59 tests; **should move to test_llm/** |
| `test_dialogue_formatter.py` | `format_dialogue_history()`, `format_stage_agent_outputs()` | `[x]` | 13 tests; **should move to test_llm/**; ~~`test_none_input` misleading~~ renamed to `test_empty_list_input` |
| `test_response_parser.py` | `parse_tool_calls()`, `sanitize_tool_output()`, extractors | `[x]` | 36 tests; **should move to test_llm/** |
| `test_llm_call_tracking.py` | `LLMService._track_failed_call()` only | `[x]` | 5 tests; **should move to test_llm/**; ~~misleading class name~~ renamed to `TestLLMServiceFailedCallTracking` |
| `test_llm_async.py` | `OllamaLLM.acomplete()`, async infrastructure | `[x]` | 18 tests; **should move to test_llm/** |
| `test_cost_estimator.py` | `estimate_cost()` | `[x]` | 6 tests; **should move to test_llm/** |
| `test_pricing.py` | `PricingManager`, `ModelPricing` | `[x]` | 25 tests; **should move to test_llm/**; fixed path fixture risk |
| `test_failover_thread_safety.py` | `FailoverProvider` thread safety | `[x]` | 6 tests; **should move to test_llm/** |
| `test_persistent_memory_scope.py` | `StandardAgent` persistent memory methods | `[x]` | 17 tests; belongs in test_agent/ |
| `test_safety_enforcement.py` | `SafetyConfig` enforcement in execution | `[x]` | 17 tests; belongs in test_agent/; excellent security tests |
| `test_structured_output.py` | `validate_and_retry_output()` from pipeline helpers | `[x]` | 6 tests; belongs in test_agent/ |
| `test_sync_async_33a.py` | `BaseLLM._check_cache`, `_cache_response`, `_execute_and_parse` | `[x]` | 13 tests; **should move to test_llm/** |
| `test_llm_providers.py` | All LLM providers, circuit breaker, failover, cleanup | `[x]` | 132 tests; **should move to test_llm/**; ~~4 dead placeholder tests~~ removed |
| `test_agent_state_machine.py` | `BaseAgent` via `MockAgent` + `FailingMockAgent` | `[x]` | 21 tests; ~~3/10~~ **7/10** — real error handling, context state, stronger assertions |
| `test_strategies/test_strategy_edge_cases.py` | Cross-cutting edge cases for consensus + merit_weighted | `[x]` | 21 tests; ~~`test_consensus_with_None_decision` is a lie~~ renamed to `test_consensus_unanimous_two_agent_vote` |

### Per-File Audit Results

| Test File | Tests | Cov | Assert | Edge | Mock | Error | Isol | Name | Dead | Integ | Sec | Score |
|-----------|-------|-----|--------|------|------|-------|------|------|------|-------|-----|-------|
| `test_base_agent.py` | 35 | WARN | WARN | WARN | WARN | WARN | PASS | PASS | WARN | WARN | N/A | 6/10 |
| `test_standard_agent.py` | 18 | WARN | PASS | WARN | WARN | WARN | PASS | PASS | PASS | FAIL | N/A | 6/10 |
| `test_script_agent.py` | 24 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | N/A | 8/10 |
| `test_reasoning.py` | 13 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | 9/10 |
| `test_guardrails.py` | 21 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | N/A | 9/10 |
| `test_agent_factory.py` | 15 | WARN | PASS | WARN | PASS | PASS | PASS | PASS | PASS | WARN | N/A | 7/10 |
| `test_agent_observer.py` | 12 | WARN | PASS | WARN | PASS | WARN | PASS | PASS | PASS | WARN | N/A | 7/10 |
| `test_base_agent_template.py` | 13 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | 8/10 |
| `test_m9_context_helpers.py` | 18 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | 9/10 |
| `test_pre_commands.py` | 21 | WARN | WARN | WARN | WARN | WARN | PASS | PASS | WARN | WARN | N/A | 6/10 |
| `test_prompt_auto_inject.py` | 11 | WARN | PASS | PASS | PASS | WARN | PASS | PASS | PASS | PASS | N/A | 8/10 |
| `test_prompt_injection.py` | 13 | WARN | PASS | WARN | PASS | WARN | PASS | PASS | WARN | PASS | PASS | 7/10 |
| `test_prompt_template_injection.py` | 31 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | PASS | PASS | 9/10 |
| `test_prompt_engine.py` | 59 | PASS | WARN | PASS | PASS | PASS | WARN | PASS | WARN | PASS | N/A | 8/10 |
| `test_dialogue_formatter.py` | 13 | PASS | PASS | PASS | PASS | WARN | PASS | PASS | PASS | WARN | N/A | 8/10 |
| `test_response_parser.py` | 36 | PASS | PASS | PASS | PASS | WARN | PASS | PASS | WARN | PASS | PASS | 8/10 |
| `test_llm_call_tracking.py` | 5 | WARN | PASS | WARN | PASS | PASS | WARN | PASS | PASS | FAIL | N/A | 6/10 |
| `test_llm_async.py` | 18 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | PASS | N/A | 9/10 |
| `test_cost_estimator.py` | 6 | WARN | PASS | WARN | PASS | WARN | PASS | PASS | PASS | WARN | N/A | 6/10 |
| `test_pricing.py` | 25 | PASS | PASS | PASS | WARN | PASS | WARN | PASS | WARN | PASS | PASS | 8/10 |
| `test_failover_thread_safety.py` | 6 | WARN | PASS | PASS | PASS | WARN | PASS | PASS | PASS | WARN | N/A | 6/10 |
| `test_persistent_memory_scope.py` | 17 | PASS | PASS | PASS | WARN | WARN | PASS | PASS | WARN | WARN | N/A | 7/10 |
| `test_safety_enforcement.py` | 17 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 9/10 |
| `test_structured_output.py` | 6 | WARN | PASS | WARN | PASS | WARN | PASS | PASS | PASS | WARN | N/A | 6/10 |
| `test_sync_async_33a.py` | 13 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | 9/10 |
| `test_llm_providers.py` | 132 | PASS | PASS | PASS | WARN | PASS | PASS | PASS | PASS | PASS | PASS | 8/10 |
| `test_agent_state_machine.py` | 21 | WARN | PASS | WARN | PASS | PASS | PASS | PASS | PASS | WARN | N/A | **7/10** |
| `test_strategies/test_base.py` | 37 | WARN | PASS | WARN | PASS | WARN | PASS | PASS | PASS | WARN | N/A | 7/10 |
| `test_strategies/test_leader.py` | 23 | WARN | PASS | WARN | PASS | PASS | PASS | PASS | PASS | PASS | N/A | 7/10 |
| `test_strategies/test_consensus.py` | 23 | WARN | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | N/A | 8/10 |
| `test_strategies/test_multi_round.py` | 53 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | **8/10** |
| `test_strategies/test_merit_weighted.py` | 24 | WARN | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | N/A | 7/10 |
| `test_strategies/test_conflict_resolution.py` | 19 | WARN | PASS | WARN | PASS | PASS | PASS | PASS | PASS | PASS | N/A | 6/10 |
| `test_strategies/test_registry.py` | 38 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | 8/10 |
| `test_strategies/test_registry_reset.py` | 24 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | 8/10 |
| `test_strategies/test_strategy_edge_cases.py` | 21 | WARN | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | N/A | 7/10 |

| `test_static_checker_agent.py` | 41 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | N/A | 8/10 |
| `test_agent_response.py` | 36 | PASS | PASS | PASS | N/A | PASS | PASS | PASS | PASS | PASS | N/A | 9/10 |
| `test_standard_agent_helpers.py` | 42 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | WARN | N/A | 8/10 |
| `test_strategies/test_concatenate.py` | 26 | PASS | PASS | PASS | N/A | PASS | PASS | PASS | PASS | PASS | N/A | 9/10 |
| `test_strategies/test_dialogue_helpers.py` | 49 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | 9/10 |

**Total: ~1095 test functions across 41 files** (was ~901 across 36 files before improvements)

### Issues Found

**CRITICAL (must fix):**
1. ~~**`static_checker_agent.py` — ZERO tests.**~~ **FIXED** — 41 tests in `test_static_checker_agent.py`
2. ~~**`concatenate.py` — ZERO tests.**~~ **FIXED** — 26 tests in `test_strategies/test_concatenate.py`
3. ~~**`models/response.py` — ZERO tests.**~~ **FIXED** — 36 tests in `test_agent_response.py`
4. ~~**`_standard_agent_helpers.py` — ZERO tests.**~~ **FIXED** — 42 tests in `test_standard_agent_helpers.py`
5. ~~**`test_agent_state_machine.py` — 3/10.**~~ **FIXED** — now 7/10 with FailingMockAgent, real error handling, stronger assertions
6. ~~**`_dialogue_helpers.py` — zero direct tests.**~~ **FIXED** — 49 tests in `test_strategies/test_dialogue_helpers.py`
7. **Async paths universally untested.** `aexecute()`/`arun()` now tested for StaticCheckerAgent; still missing for StandardAgent.

**HIGH (should fix):**
8. ~~**`MultiRoundStrategy.extract_stances()` — completely untested.**~~ **FIXED** — 22 tests added for regex+LLM+combined paths
9. ~~**`register_resolver()` validation gaps.**~~ **FIXED** — 4 validation tests added to `test_registry.py`
10. **`_registry_helpers.py` — indirect coverage only.** `build_default_strategies()` and `build_default_resolvers()` never directly called; exception-handling path untested.
11. ~~**Conditional assertions (silent pass pattern).**~~ **FIXED** — 10 conditional assertions made unconditional across 4 files
12. ~~**Misleading test names.**~~ **FIXED** — all 3 renamed, duplicate removed
13. ~~**4 dead placeholder tests in `test_llm_providers.py`.**~~ **FIXED** — 3 dead tests removed (4th was valid)

**MEDIUM (nice to fix):**
14. Timing-dependent tests as CI flake risks: `test_cache_performance_improvement`, `test_async_performance_baseline`.
15. ~~`CustomTestResolver` in `test_registry_reset.py` has wrong `resolve()` signature~~ **FIXED** — signature corrected to match ABC
16. `test_pricing.py` writes to fixed file paths instead of `tmp_path` — parallel test interference risk.
17. 11 of 17 standalone files test `temper_ai.llm` code but live in `tests/test_agent/` — wrong directory.
18. No cross-strategy integration tests (consensus → conflict detection → resolution pipeline).
19. `TestPersistentMemoryScope` tests a manual re-implementation of scope logic, not the actual `StandardAgent._build_memory_scope`.

### Recommendations

**Priority 1 — Write missing test files:**
- [ ] Create `tests/test_agent/test_static_checker_agent.py`
- [ ] Create `tests/test_agent/test_strategies/test_concatenate.py`
- [ ] Create `tests/test_agent/test_agent_response.py` for `models/response.py`
- [ ] Create `tests/test_agent/test_standard_agent_helpers.py`

**Priority 2 — Fix critical gaps in existing tests:**
- [ ] Add async path tests (`aexecute`/`arun`) to `test_base_agent.py` and `test_standard_agent.py`
- [ ] Add `extract_stances()` tests to `test_multi_round.py` (regex + LLM paths)
- [ ] Add `register_resolver()` validation tests to `test_registry.py`
- [ ] Add direct tests for `_dialogue_helpers.py` helper functions
- [ ] Rewrite or delete `test_agent_state_machine.py` — currently provides false confidence

**Priority 3 — Fix test quality issues:**
- [ ] Remove conditional assertion guards (replace `if` with unconditional asserts)
- [ ] Fix misleading test names
- [ ] Delete or implement the 4 dead token-counting placeholder tests
- [ ] Fix `test_pricing.py` to use `tmp_path` instead of fixed file paths
- [ ] Mark timing-dependent tests with `@pytest.mark.slow`

**Priority 4 — Organizational:**
- [ ] Move 11 LLM-specific test files from `tests/test_agent/` to `tests/test_llm/`
- [ ] Add cross-strategy integration test (consensus → conflict → resolution pipeline)

### Feature Score: 7.1/10

**Breakdown:** Core agent 7.5 | Strategies 6.4 | Standalone/Cross-cutting 7.2

**Strengths:** Security testing (SSTI, prompt injection, safety enforcement) is exceptional. Strategy dataclass validation is thorough. Registry lifecycle and thread-safety tests are above average. Async testing uses correct patterns (patching `asyncio.sleep` for backoff).

**Weaknesses:** 4 source files with zero test coverage (one is a production agent). Async execution paths universally untested. `concatenate.py` is a default registered strategy with no tests. Several test files contain misleading names, conditional assertions, or dead placeholder tests that create false confidence in coverage.

---

## 2. LLM (`temper_ai/llm/` → `tests/test_llm/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `llm/service.py` | `test_service_observability.py` | `[ ]` | Only observability aspect? |
| `llm/conversation.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/response_parser.py` | _(agent/test_response_parser.py?)_ | `[ ]` | Tested from agent dir? |
| `llm/output_validation.py` | `test_output_validation.py` | `[ ]` | |
| `llm/context_window.py` | `test_context_window.py` | `[ ]` | |
| `llm/pricing.py` | _(agent/test_pricing.py?)_ | `[ ]` | Tested from agent dir? |
| `llm/cost_estimator.py` | _(agent/test_cost_estimator.py?)_ | `[ ]` | Tested from agent dir? |
| `llm/tool_keys.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/constants.py` | _(none)_ | `[ ]` | Constants — may not need |
| `llm/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `llm/llm_loop_events.py` | _(observability/test_llm_loop_events.py?)_ | `[ ]` | Cross-module? |
| `llm/_prompt.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/_tracking.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/_tool_execution.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/_retry.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/failover.py` | `test_failover_tracking.py` | `[ ]` | |
| `llm/cache/llm_cache.py` | `test_cache/test_llm_cache.py` | `[ ]` | |
| `llm/cache/constants.py` | _(none)_ | `[ ]` | Constants |
| `llm/providers/base.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/providers/factory.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/providers/anthropic_provider.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/providers/openai_provider.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/providers/vllm_provider.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/providers/ollama.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/providers/_base_helpers.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/providers/_stream_helpers.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/prompts/engine.py` | _(agent/test_prompt_engine.py?)_ | `[ ]` | Cross-module? |
| `llm/prompts/dialogue_formatter.py` | _(agent/test_dialogue_formatter.py?)_ | `[ ]` | Cross-module? |
| `llm/prompts/validation.py` | _(none found)_ | `[ ]` | **GAP?** |
| `llm/prompts/cache.py` | _(none found)_ | `[ ]` | **GAP?** |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_service_observability.py` | Service + observability | `[ ]` | |
| `test_output_validation.py` | Output validation | `[ ]` | |
| `test_context_window.py` | Context window mgmt | `[ ]` | |
| `test_schemas.py` | LLM schemas | `[ ]` | |
| `test_prompt_versioning.py` | Prompt versioning | `[ ]` | |
| `test_circuit_breaker_race.py` | Circuit breaker races | `[ ]` | |
| `test_failover_tracking.py` | Failover tracking | `[ ]` | |
| `test_cache/test_llm_cache.py` | LLM caching | `[ ]` | |
| `test_cache/test_except_broad_13.py` | Broad exception fix | `[ ]` | |

### Per-File Audit Results

| Test File | Cov | Assert | Edge | Mock | Error | Isol | Name | Dead | Integ | Sec | Score |
|-----------|-----|--------|------|------|-------|------|------|------|-------|-----|-------|
| `test_service_observability.py` | | | | | | | | | | | —/10 |
| `test_output_validation.py` | | | | | | | | | | | —/10 |
| `test_context_window.py` | | | | | | | | | | | —/10 |
| `test_schemas.py` | | | | | | | | | | | —/10 |
| `test_prompt_versioning.py` | | | | | | | | | | | —/10 |
| `test_circuit_breaker_race.py` | | | | | | | | | | | —/10 |
| `test_failover_tracking.py` | | | | | | | | | | | —/10 |
| `test_cache/test_llm_cache.py` | | | | | | | | | | | —/10 |
| `test_cache/test_except_broad_13.py` | | | | | | | | | | | —/10 |

### Issues Found
- **ALERT: 10 test files covering 34 source files — likely significant gaps**
- _(detailed findings during audit)_

### Recommendations
- _(to be populated during audit)_

### Feature Score: —/10

---

## 3. Workflow (`temper_ai/workflow/` → `tests/test_workflow/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `workflow/runtime.py` | `test_runtime.py`, `test_runtime_observability.py` | `[ ]` | |
| `workflow/workflow_executor.py` | `test_workflow_executor.py` | `[ ]` | |
| `workflow/execution_service.py` | `test_execution_service.py` | `[ ]` | |
| `workflow/execution_engine.py` | `test_execution_engine.py` | `[ ]` | |
| `workflow/dag_builder.py` | `test_dag_builder.py` | `[ ]` | |
| `workflow/node_builder.py` | `test_node_builder.py` | `[ ]` | |
| `workflow/state_manager.py` | `test_state_manager.py` | `[ ]` | |
| `workflow/langgraph_state.py` | `test_langgraph_state.py` | `[ ]` | |
| `workflow/context_provider.py` | `test_context_provider.py` | `[ ]` | |
| `workflow/execution_context.py` | _(none found)_ | `[ ]` | **GAP?** |
| `workflow/context_schemas.py` | _(none found)_ | `[ ]` | **GAP?** |
| `workflow/domain_state.py` | `test_domain_state.py` | `[ ]` | |
| `workflow/condition_evaluator.py` | `test_condition_evaluator.py` | `[ ]` | |
| `workflow/routing_functions.py` | `test_routing_functions.py` | `[ ]` | |
| `workflow/output_extractor.py` | `test_output_extractor.py` | `[ ]` | |
| `workflow/checkpoint_manager.py` | `test_checkpoint_manager.py`, `test_checkpoint_lock_16.py`, `test_checkpoint_recovery.py`, `test_checkpoint_streaming.py` | `[ ]` | |
| `workflow/checkpoint_backends.py` | `test_checkpoint_backends.py` | `[ ]` | |
| `workflow/stage_compiler.py` | _(stage/test_stage_compiler.py? test_dag_stage_compiler.py?)_ | `[ ]` | Cross-module? |
| `workflow/config_loader.py` | `test_config_loader.py` | `[ ]` | |
| `workflow/db_config_loader.py` | _(none found)_ | `[ ]` | **GAP?** |
| `workflow/env_var_validator.py` | `test_env_var_validator.py` | `[ ]` | |
| `workflow/planning.py` | `test_planning.py` | `[ ]` | |
| `workflow/security_limits.py` | `test_security_limits.py` | `[ ]` | |
| `workflow/utils.py` | `test_utils.py` | `[ ]` | |
| `workflow/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `workflow/_runtime_helpers.py` | _(indirect via test_runtime?)_ | `[ ]` | |
| `workflow/_config_loader_helpers.py` | _(indirect via test_config_loader?)_ | `[ ]` | |
| `workflow/_triggers.py` | _(none found)_ | `[ ]` | **GAP?** |
| `workflow/dag_visualizer.py` | `test_dag_visualizer.py` | `[ ]` | |
| `workflow/dag_visualizer_constants.py` | _(none)_ | `[ ]` | Constants |
| `workflow/constants.py` | _(none)_ | `[ ]` | Constants |
| `workflow/engine_registry.py` | `test_engine_registry.py` | `[ ]` | |
| `workflow/engines/native_engine.py` | `test_native_engine.py` | `[ ]` | |
| `workflow/engines/native_runner.py` | `test_native_runner.py` | `[ ]` | |
| `workflow/engines/dynamic_engine.py` | `test_dynamic_engine.py` | `[ ]` | |
| `workflow/engines/dynamic_runner.py` | _(none found)_ | `[ ]` | **GAP?** |
| `workflow/engines/langgraph_engine.py` | `test_langgraph_engine.py` | `[ ]` | |
| `workflow/engines/langgraph_compiler.py` | `test_langgraph_compiler.py` | `[ ]` | |
| `workflow/engines/workflow_executor.py` | `test_native_workflow_executor.py` | `[ ]` | |
| `workflow/engines/_dynamic_edge_helpers.py` | _(indirect?)_ | `[ ]` | |
| `workflow/templates/registry.py` | `test_templates/test_registry.py` | `[ ]` | |
| `workflow/templates/generator.py` | `test_templates/test_generator.py` | `[ ]` | |
| `workflow/templates/quality_gates.py` | `test_templates/test_quality_gates.py` | `[ ]` | |
| `workflow/templates/_schemas.py` | `test_templates/test_schemas.py` | `[ ]` | |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_concurrent_workflows.py` | Concurrent workflow exec | `[ ]` | |
| `test_convergence.py` | Workflow convergence | `[ ]` | |
| `test_input_passthrough.py` | Input passthrough | `[ ]` | |
| `test_config_security.py` | Config security | `[ ]` | |
| `test_predecessor_resolver.py` | Predecessor resolution | `[ ]` | |
| `test_workflow_state_transitions.py` | State transitions | `[ ]` | |

### Per-File Audit Results

| Test File | Cov | Assert | Edge | Mock | Error | Isol | Name | Dead | Integ | Sec | Score |
|-----------|-----|--------|------|------|-------|------|------|------|-------|-----|-------|
| `test_runtime.py` | | | | | | | | | | | —/10 |
| `test_runtime_observability.py` | | | | | | | | | | | —/10 |
| `test_workflow_executor.py` | | | | | | | | | | | —/10 |
| `test_execution_service.py` | | | | | | | | | | | —/10 |
| `test_execution_engine.py` | | | | | | | | | | | —/10 |
| `test_dag_builder.py` | | | | | | | | | | | —/10 |
| `test_node_builder.py` | | | | | | | | | | | —/10 |
| `test_state_manager.py` | | | | | | | | | | | —/10 |
| `test_langgraph_state.py` | | | | | | | | | | | —/10 |
| `test_context_provider.py` | | | | | | | | | | | —/10 |
| `test_condition_evaluator.py` | | | | | | | | | | | —/10 |
| `test_routing_functions.py` | | | | | | | | | | | —/10 |
| `test_output_extractor.py` | | | | | | | | | | | —/10 |
| `test_checkpoint_manager.py` | | | | | | | | | | | —/10 |
| `test_checkpoint_lock_16.py` | | | | | | | | | | | —/10 |
| `test_checkpoint_backends.py` | | | | | | | | | | | —/10 |
| `test_checkpoint_recovery.py` | | | | | | | | | | | —/10 |
| `test_checkpoint_streaming.py` | | | | | | | | | | | —/10 |
| `test_config_loader.py` | | | | | | | | | | | —/10 |
| `test_env_var_validator.py` | | | | | | | | | | | —/10 |
| `test_planning.py` | | | | | | | | | | | —/10 |
| `test_security_limits.py` | | | | | | | | | | | —/10 |
| `test_utils.py` | | | | | | | | | | | —/10 |
| `test_schemas.py` | | | | | | | | | | | —/10 |
| `test_dag_visualizer.py` | | | | | | | | | | | —/10 |
| `test_domain_state.py` | | | | | | | | | | | —/10 |
| `test_concurrent_workflows.py` | | | | | | | | | | | —/10 |
| `test_convergence.py` | | | | | | | | | | | —/10 |
| `test_input_passthrough.py` | | | | | | | | | | | —/10 |
| `test_config_security.py` | | | | | | | | | | | —/10 |
| `test_predecessor_resolver.py` | | | | | | | | | | | —/10 |
| `test_workflow_state_transitions.py` | | | | | | | | | | | —/10 |
| `test_engine_registry.py` | | | | | | | | | | | —/10 |
| `test_native_engine.py` | | | | | | | | | | | —/10 |
| `test_native_runner.py` | | | | | | | | | | | —/10 |
| `test_native_workflow_executor.py` | | | | | | | | | | | —/10 |
| `test_dynamic_engine.py` | | | | | | | | | | | —/10 |
| `test_langgraph_compiler.py` | | | | | | | | | | | —/10 |
| `test_langgraph_engine.py` | | | | | | | | | | | —/10 |
| `test_templates/test_registry.py` | | | | | | | | | | | —/10 |
| `test_templates/test_generator.py` | | | | | | | | | | | —/10 |
| `test_templates/test_quality_gates.py` | | | | | | | | | | | —/10 |
| `test_templates/test_schemas.py` | | | | | | | | | | | —/10 |

### Issues Found
- _(to be populated during audit)_

### Recommendations
- _(to be populated during audit)_

### Feature Score: —/10

---

## 4. Stage (`temper_ai/stage/` → `tests/test_stage/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `stage/convergence.py` | `test_convergence.py` | `[ ]` | |
| `stage/_schemas.py` | _(none found)_ | `[ ]` | **GAP?** |
| `stage/_config_accessors.py` | _(none found)_ | `[ ]` | **GAP?** |
| `stage/executors/base.py` | _(indirect?)_ | `[ ]` | |
| `stage/executors/sequential.py` | `test_sequential_execution.py`, `test_sequential_progress.py` | `[ ]` | |
| `stage/executors/parallel.py` | `test_parallel_execution.py`, `test_parallel_progress.py`, `test_executors_parallel.py` | `[ ]` | |
| `stage/executors/adaptive.py` | `test_adaptive_execution.py` | `[ ]` | |
| `stage/executors/langgraph_runner.py` | _(none found)_ | `[ ]` | **GAP?** |
| `stage/executors/state_keys.py` | _(none found)_ | `[ ]` | **GAP?** |
| `stage/executors/_protocols.py` | _(none found)_ | `[ ]` | Protocol — may not need |
| `stage/executors/_base_helpers.py` | _(indirect?)_ | `[ ]` | |
| `stage/executors/_agent_execution.py` | _(indirect?)_ | `[ ]` | |
| `stage/executors/_sequential_helpers.py` | _(indirect?)_ | `[ ]` | |
| `stage/executors/_sequential_retry.py` | `test_recursive_retry_34.py` | `[ ]` | |
| `stage/executors/_parallel_helpers.py` | _(indirect?)_ | `[ ]` | |
| `stage/executors/_parallel_observability.py` | _(indirect?)_ | `[ ]` | |
| `stage/executors/_parallel_quality_gates.py` | `test_quality_gates.py` | `[ ]` | |
| `stage/executors/_dialogue_helpers.py` | _(indirect?)_ | `[ ]` | |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_stage_error_handling.py` | Stage error handling | `[ ]` | |
| `test_stage_compiler.py` | Stage compilation | `[ ]` | |
| `test_dag_stage_compiler.py` | DAG stage compilation | `[ ]` | |
| `test_conditional_stages.py` | Conditional stage logic | `[ ]` | |
| `test_retry_observability.py` | Retry observability | `[ ]` | |

### Per-File Audit Results

| Test File | Cov | Assert | Edge | Mock | Error | Isol | Name | Dead | Integ | Sec | Score |
|-----------|-----|--------|------|------|-------|------|------|------|-------|-----|-------|
| `test_sequential_execution.py` | | | | | | | | | | | —/10 |
| `test_sequential_progress.py` | | | | | | | | | | | —/10 |
| `test_parallel_execution.py` | | | | | | | | | | | —/10 |
| `test_parallel_progress.py` | | | | | | | | | | | —/10 |
| `test_adaptive_execution.py` | | | | | | | | | | | —/10 |
| `test_convergence.py` | | | | | | | | | | | —/10 |
| `test_quality_gates.py` | | | | | | | | | | | —/10 |
| `test_stage_error_handling.py` | | | | | | | | | | | —/10 |
| `test_stage_compiler.py` | | | | | | | | | | | —/10 |
| `test_dag_stage_compiler.py` | | | | | | | | | | | —/10 |
| `test_conditional_stages.py` | | | | | | | | | | | —/10 |
| `test_retry_observability.py` | | | | | | | | | | | —/10 |
| `test_recursive_retry_34.py` | | | | | | | | | | | —/10 |
| `test_executors_parallel.py` | | | | | | | | | | | —/10 |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 5. Tools (`temper_ai/tools/` → `tests/test_tools/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `tools/base.py` | _(none found)_ | `[ ]` | **GAP?** |
| `tools/registry.py` | `test_registry.py` | `[ ]` | |
| `tools/executor.py` | `test_executor.py` | `[ ]` | |
| `tools/loader.py` | `test_tool_config_loading.py` | `[ ]` | |
| `tools/bash.py` | `test_bash.py` | `[ ]` | |
| `tools/git_tool.py` | `test_git_tool.py` | `[ ]` | |
| `tools/http_client.py` | `test_http_client.py` | `[ ]` | |
| `tools/file_writer.py` | `test_file_writer.py` | `[ ]` | |
| `tools/web_search.py` | `test_web_search.py` | `[ ]` | |
| `tools/web_scraper.py` | `test_web_scraper.py` | `[ ]` | |
| `tools/calculator.py` | `test_calculator.py` | `[ ]` | |
| `tools/json_parser.py` | `test_json_parser.py` | `[ ]` | |
| `tools/tool_cache.py` | `test_tool_cache.py` | `[ ]` | |
| `tools/workflow_rate_limiter.py` | `test_workflow_rate_limiter.py` | `[ ]` | |
| `tools/_schemas.py` | `test_config_schema.py` | `[ ]` | |
| `tools/_bash_helpers.py` | _(indirect via test_bash?)_ | `[ ]` | |
| `tools/_executor_helpers.py` | _(indirect?)_ | `[ ]` | |
| `tools/_executor_config.py` | _(indirect?)_ | `[ ]` | |
| `tools/_search_helpers.py` | `test_search_helpers.py` | `[ ]` | |
| `tools/_search_backends.py` | _(indirect?)_ | `[ ]` | |
| `tools/_registry_helpers.py` | _(indirect?)_ | `[ ]` | |
| `tools/constants.py` | _(none)_ | `[ ]` | Constants |
| `tools/field_names.py` | _(none)_ | `[ ]` | Constants |
| `tools/tool_cache_constants.py` | _(none)_ | `[ ]` | Constants |
| `tools/http_client_constants.py` | _(none)_ | `[ ]` | Constants |
| `tools/git_tool_constants.py` | _(none)_ | `[ ]` | Constants |
| `tools/workflow_rate_limiter_constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_config_validation.py` | Config validation | `[ ]` | |
| `test_tool_edge_cases.py` | Tool edge cases | `[ ]` | |
| `test_parameter_sanitization.py` | Parameter sanitization | `[ ]` | Security |
| `test_concurrent_limit_25.py` | Concurrent limits | `[ ]` | |
| `test_generate_tool_docs.py` | Tool doc generation | `[ ]` | |

### Per-File Audit Results

| Test File | Cov | Assert | Edge | Mock | Error | Isol | Name | Dead | Integ | Sec | Score |
|-----------|-----|--------|------|------|-------|------|------|------|-------|-----|-------|
| `test_bash.py` | | | | | | | | | | | —/10 |
| `test_git_tool.py` | | | | | | | | | | | —/10 |
| `test_http_client.py` | | | | | | | | | | | —/10 |
| `test_file_writer.py` | | | | | | | | | | | —/10 |
| `test_web_search.py` | | | | | | | | | | | —/10 |
| `test_web_scraper.py` | | | | | | | | | | | —/10 |
| `test_calculator.py` | | | | | | | | | | | —/10 |
| `test_json_parser.py` | | | | | | | | | | | —/10 |
| `test_registry.py` | | | | | | | | | | | —/10 |
| `test_executor.py` | | | | | | | | | | | —/10 |
| `test_tool_cache.py` | | | | | | | | | | | —/10 |
| `test_tool_config_loading.py` | | | | | | | | | | | —/10 |
| `test_config_validation.py` | | | | | | | | | | | —/10 |
| `test_config_schema.py` | | | | | | | | | | | —/10 |
| `test_tool_edge_cases.py` | | | | | | | | | | | —/10 |
| `test_search_helpers.py` | | | | | | | | | | | —/10 |
| `test_parameter_sanitization.py` | | | | | | | | | | | —/10 |
| `test_concurrent_limit_25.py` | | | | | | | | | | | —/10 |
| `test_workflow_rate_limiter.py` | | | | | | | | | | | —/10 |
| `test_generate_tool_docs.py` | | | | | | | | | | | —/10 |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---
---

# PHASE 2 — SAFETY & AUTH

---

## 6. Safety (`temper_ai/safety/` → `tests/test_safety/`)

### Source → Test Coverage Map

**Core Safety:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `safety/base.py` | _(indirect?)_ | `[ ]` | |
| `safety/action_policy_engine.py` | `test_action_policy_engine.py` | `[ ]` | |
| `safety/approval.py` | `test_approval_workflow.py`, `test_approval_auth_22.py` | `[ ]` | |
| `safety/blast_radius.py` | `test_blast_radius.py` | `[ ]` | |
| `safety/circuit_breaker.py` | `test_circuit_breaker.py` | `[ ]` | |
| `safety/composition.py` | `test_composer.py`, `test_policy_composition.py` | `[ ]` | |
| `safety/config_change_policy.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/entropy_analyzer.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/exceptions.py` | `test_exceptions.py` | `[ ]` | |
| `safety/factory.py` | `test_factory.py` | `[ ]` | |
| `safety/file_access.py` | `test_file_access.py` | `[ ]` | |
| `safety/forbidden_operations.py` | `test_forbidden_operations.py` | `[ ]` | |
| `safety/interfaces.py` | `test_interfaces.py` | `[ ]` | |
| `safety/models.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/pattern_matcher.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/policy_registry.py` | `test_policy_registry.py` | `[ ]` | |
| `safety/prompt_injection_policy.py` | _(security/test_prompt_injection.py?)_ | `[ ]` | |
| `safety/rate_limiter.py` | `test_rate_limiter.py`, `test_distributed_rate_limiting.py` | `[ ]` | |
| `safety/redaction_utils.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/rollback.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/rollback_api.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/secret_detection.py` | `test_secret_detection.py`, `test_secret_sanitization.py` | `[ ]` | |
| `safety/service_mixin.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/stub_policies.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/token_bucket.py` | `test_token_bucket.py` | `[ ]` | |
| `safety/validation.py` | `test_policy_validation.py` | `[ ]` | |

**Safety Autonomy Sub-module:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `safety/autonomy/approval_router.py` | `test_autonomy/test_approval_router.py` | `[ ]` | |
| `safety/autonomy/budget_enforcer.py` | `test_autonomy/test_budget_enforcer.py` | `[ ]` | |
| `safety/autonomy/emergency_stop.py` | `test_autonomy/test_emergency_stop.py` | `[ ]` | |
| `safety/autonomy/manager.py` | `test_autonomy/test_manager.py` | `[ ]` | |
| `safety/autonomy/merit_bridge.py` | `test_autonomy/test_merit_bridge.py` | `[ ]` | |
| `safety/autonomy/models.py` | `test_autonomy/test_models.py` | `[ ]` | |
| `safety/autonomy/policy.py` | `test_autonomy/test_policy.py` | `[ ]` | |
| `safety/autonomy/schemas.py` | `test_autonomy/test_schemas.py` | `[ ]` | |
| `safety/autonomy/shadow_mode.py` | `test_autonomy/test_shadow_mode.py` | `[ ]` | |
| `safety/autonomy/store.py` | `test_autonomy/test_store.py` | `[ ]` | |
| `safety/autonomy/trust_evaluator.py` | `test_autonomy/test_trust_evaluator.py` | `[ ]` | |
| `safety/autonomy/dashboard_routes.py` | `test_autonomy/test_dashboard_routes.py` | `[ ]` | |
| `safety/autonomy/dashboard_service.py` | _(none found)_ | `[ ]` | **GAP?** |
| `safety/autonomy/constants.py` | _(none)_ | `[ ]` | Constants |

**Safety Policies Sub-module:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `safety/policies/rate_limit_policy.py` | `policies/test_rate_limit_policy.py` | `[ ]` | |
| `safety/policies/resource_limit_policy.py` | `policies/test_resource_limit_policy.py` | `[ ]` | |

**Safety Security Sub-module:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `safety/security/llm_security.py` | `test_security/test_llm_security.py`, `test_llm_security_extended.py`, `test_llm_security_redos.py` | `[ ]` | |
| `safety/security/constants.py` | _(none)_ | `[ ]` | Constants |

### Security Attack Vector Tests

| Test File | Attack Vector | Status | Notes |
|-----------|--------------|--------|-------|
| `test_security/test_calculator_dos.py` | Calculator DoS | `[ ]` | |
| `test_security/test_config_injection.py` | Config injection | `[ ]` | |
| `test_security/test_env_var_validation.py` | Env var attacks | `[ ]` | |
| `test_security/test_path_injection.py` | Path injection | `[ ]` | |
| `test_security/test_prompt_injection.py` | Prompt injection | `[ ]` | |
| `test_security/test_race_conditions.py` | Race conditions | `[ ]` | |
| `test_security/test_redos_secret_detection.py` | ReDoS in secrets | `[ ]` | |
| `test_security/test_security_bypasses.py` | Security bypasses | `[ ]` | |
| `test_security/test_ssrf_dns_security.py` | SSRF/DNS attacks | `[ ]` | |
| `test_security/test_tmp_path_traversal.py` | Path traversal | `[ ]` | |
| `test_security/test_unicode_normalization_bypasses.py` | Unicode bypass | `[ ]` | |
| `test_security/test_url_encoding_bypasses.py` | URL encoding bypass | `[ ]` | |
| `test_security/test_violation_logging_security.py` | Violation logging | `[ ]` | |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_m4_integration.py` | M4 integration | `[ ]` | |
| `test_memory_eviction.py` | Memory eviction in safety | `[ ]` | |
| `test_safety_mode_transitions.py` | Mode transitions | `[ ]` | |
| `test_safety_policies.py` | General policies | `[ ]` | |
| `test_redos_redirect_fix.py` | ReDoS redirect fix | `[ ]` | |
| `test_sync_async_33b.py` | Sync/async compat | `[ ]` | |
| `policies/test_policy_input_validation.py` | Policy input validation | `[ ]` | |
| `test_autonomy/test_integration.py` | Autonomy integration | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 7. Auth (`temper_ai/auth/` → `tests/test_auth/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `auth/api_key_auth.py` | `test_api_key_auth.py` | `[ ]` | |
| `auth/config_seed.py` | _(none found)_ | `[ ]` | **GAP?** |
| `auth/config_sync.py` | `test_config_sync.py` | `[ ]` | |
| `auth/constants.py` | `test_constants.py` | `[ ]` | |
| `auth/models.py` | `test_models.py` | `[ ]` | |
| `auth/routes.py` | `test_routes.py`, `test_auth_routes.py` | `[ ]` | |
| `auth/session.py` | `test_session.py`, `test_session_thread_safety.py` | `[ ]` | |
| `auth/tenant_scope.py` | `test_tenant_scope.py` | `[ ]` | |
| `auth/ws_tickets.py` | _(none found)_ | `[ ]` | **GAP?** |
| `auth/oauth/callback_validator.py` | `test_callback_validator.py`, `oauth/test_callback_validator.py` | `[ ]` | Duplicate? |
| `auth/oauth/config.py` | `oauth/test_config.py` | `[ ]` | |
| `auth/oauth/rate_limiter.py` | `test_rate_limiter.py`, `oauth/test_rate_limiter.py` | `[ ]` | Duplicate? |
| `auth/oauth/service.py` | `test_oauth_service.py`, `oauth/test_service.py` | `[ ]` | Duplicate? |
| `auth/oauth/state_store.py` | `test_state_store.py`, `test_state_store_comprehensive.py`, `oauth/test_state_store.py` | `[ ]` | Triple? |
| `auth/oauth/token_store.py` | `test_token_store.py`, `test_oauth_token_store.py`, `oauth/test_token_store.py` | `[ ]` | Triple? |
| `auth/oauth/_service_helpers.py` | `oauth/test__service_helpers.py` | `[ ]` | |
| `auth/oauth/_token_store_helpers.py` | _(none found)_ | `[ ]` | **GAP?** |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_cache_concurrent.py` | Concurrent cache access | `[ ]` | |
| `test_oauth_integration.py` | OAuth integration | `[ ]` | |

### Per-File Audit Results

| Test File | Cov | Assert | Edge | Mock | Error | Isol | Name | Dead | Integ | Sec | Score |
|-----------|-----|--------|------|------|-------|------|------|------|-------|-----|-------|
| `test_api_key_auth.py` | | | | | | | | | | | —/10 |
| `test_auth_routes.py` | | | | | | | | | | | —/10 |
| `test_callback_validator.py` | | | | | | | | | | | —/10 |
| `test_cache_concurrent.py` | | | | | | | | | | | —/10 |
| `test_config_sync.py` | | | | | | | | | | | —/10 |
| `test_constants.py` | | | | | | | | | | | —/10 |
| `test_models.py` | | | | | | | | | | | —/10 |
| `test_oauth_integration.py` | | | | | | | | | | | —/10 |
| `test_oauth_service.py` | | | | | | | | | | | —/10 |
| `test_oauth_token_store.py` | | | | | | | | | | | —/10 |
| `test_rate_limiter.py` | | | | | | | | | | | —/10 |
| `test_routes.py` | | | | | | | | | | | —/10 |
| `test_session.py` | | | | | | | | | | | —/10 |
| `test_session_thread_safety.py` | | | | | | | | | | | —/10 |
| `test_state_store.py` | | | | | | | | | | | —/10 |
| `test_state_store_comprehensive.py` | | | | | | | | | | | —/10 |
| `test_tenant_scope.py` | | | | | | | | | | | —/10 |
| `test_token_store.py` | | | | | | | | | | | —/10 |
| `oauth/test__service_helpers.py` | | | | | | | | | | | —/10 |
| `oauth/test_callback_validator.py` | | | | | | | | | | | —/10 |
| `oauth/test_config.py` | | | | | | | | | | | —/10 |
| `oauth/test_rate_limiter.py` | | | | | | | | | | | —/10 |
| `oauth/test_service.py` | | | | | | | | | | | —/10 |
| `oauth/test_state_store.py` | | | | | | | | | | | —/10 |
| `oauth/test_token_store.py` | | | | | | | | | | | —/10 |

### Issues Found
- **ALERT: Possible duplicate test files — same source tested in both `test_auth/` and `test_auth/oauth/`**
- _(detailed findings during audit)_

### Feature Score: —/10

---
---

# PHASE 3 — DATA & STORAGE

---

## 8. Storage (`temper_ai/storage/` → `tests/test_storage/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `storage/database/engine.py` | _(none found)_ | `[ ]` | **GAP** |
| `storage/database/manager.py` | `test_database/test_manager.py` | `[ ]` | |
| `storage/database/models.py` | _(none found)_ | `[ ]` | **GAP** |
| `storage/database/models_evaluation.py` | _(none found)_ | `[ ]` | **GAP** |
| `storage/database/models_registry.py` | _(none found)_ | `[ ]` | **GAP** |
| `storage/database/models_tenancy.py` | _(none found)_ | `[ ]` | **GAP** |
| `storage/database/validators.py` | `test_database/test_validators.py` | `[ ]` | |
| `storage/database/datetime_utils.py` | _(none found)_ | `[ ]` | **GAP** |
| `storage/database/constants.py` | _(none)_ | `[ ]` | Constants |
| `storage/schemas/agent_config.py` | _(none found)_ | `[ ]` | **GAP** |
| `storage/schemas/constants.py` | _(none)_ | `[ ]` | Constants |

### Issues Found
- **CRITICAL: Only 2 test files for 14 source files — massive coverage gap**
- _(detailed findings during audit)_

### Feature Score: —/10

---

## 9. Events (`temper_ai/events/` → `tests/test_events/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `events/event_bus.py` | `test_event_bus.py` | `[ ]` | |
| `events/subscription_registry.py` | `test_subscription_registry.py` | `[ ]` | |
| `events/models.py` | `test_models.py` | `[ ]` | |
| `events/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `events/_cross_workflow.py` | `test_cross_workflow.py` | `[ ]` | |
| `events/_bus_helpers.py` | _(indirect?)_ | `[ ]` | |
| `events/_subscription_helpers.py` | _(indirect?)_ | `[ ]` | |
| `events/constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_event_triggered_node.py` | Event-triggered nodes | `[ ]` | |
| `test_integration.py` | Events integration | `[ ]` | |
| `test_stage_compiler_events.py` | Stage compiler events | `[ ]` | |
| `test_workflow_integration.py` | Workflow integration | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 10. Memory (`temper_ai/memory/` → `tests/test_memory/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `memory/service.py` | `test_service.py` | `[ ]` | |
| `memory/registry.py` | `test_registry.py` | `[ ]` | |
| `memory/protocols.py` | `test_protocols.py` | `[ ]` | |
| `memory/formatter.py` | `test_formatter.py` | `[ ]` | |
| `memory/extractors.py` | `test_extractors.py` | `[ ]` | |
| `memory/cross_pollination.py` | `test_cross_pollination.py` | `[ ]` | |
| `memory/agent_performance.py` | `test_agent_performance.py` | `[ ]` | |
| `memory/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `memory/_m9_schemas.py` | `test_m9_schemas.py` | `[ ]` | |
| `memory/adapters/in_memory.py` | `test_in_memory_adapter.py` | `[ ]` | |
| `memory/adapters/knowledge_graph_adapter.py` | `test_knowledge_graph_adapter.py` | `[ ]` | |
| `memory/adapters/mem0_adapter.py` | `test_mem0_adapter.py` | `[ ]` | |
| `memory/adapters/pg_adapter.py` | _(none found)_ | `[ ]` | **GAP?** |
| `memory/constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_decay.py` | Memory decay | `[ ]` | |
| `test_integration.py` | Memory integration | `[ ]` | |
| `test_sharing.py` | Memory sharing | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 11. Registry (`temper_ai/registry/` → `tests/test_registry/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `registry/service.py` | `test_service.py` | `[ ]` | |
| `registry/store.py` | `test_store.py` | `[ ]` | |
| `registry/_helpers.py` | `test_helpers.py` | `[ ]` | |
| `registry/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `registry/constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_agent_routes.py` | Agent routes | `[ ]` | |
| `test_config_schema.py` | Config schema | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---
---

# PHASE 4 — ADVANCED FEATURES

---

## 12. Observability (`temper_ai/observability/` → `tests/test_observability/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `observability/tracker.py` | `test_tracker.py`, `test_tracker_sampling_perf.py`, `test_tracker_session_dedup.py`, `test_tracker_thread_safety.py`, `test_async_tracker.py` | `[ ]` | 5 test files |
| `observability/alerting.py` | `test_alerting.py`, `test_alerting_comprehensive.py`, `test_alerting_gaps.py` | `[ ]` | 3 test files |
| `observability/buffer.py` | `test_buffer.py`, `test_buffer_integration.py`, `test_buffer_lifecycle.py`, `test_buffer_retry.py` | `[ ]` | 4 test files |
| `observability/backend.py` | `test_backend.py` | `[ ]` | |
| `observability/console.py` | `test_console.py`, `test_console_streaming.py`, `test_console_visualizer.py` | `[ ]` | |
| `observability/error_fingerprinting.py` | `test_error_fingerprinting.py`, `test_error_fingerprint_integration.py`, `test_fingerprint_wiring.py` | `[ ]` | |
| `observability/event_bus.py` | `test_event_bus.py`, `test_async_event_bus.py` | `[ ]` | |
| `observability/health_monitor.py` | `test_health_monitor.py`, `test_health_monitor_expanded.py` | `[ ]` | |
| `observability/hooks.py` | `test_hooks.py`, `test_async_hooks.py` | `[ ]` | |
| `observability/cost_rollup.py` | `test_cost_rollup.py`, `test_cost_attribution.py` | `[ ]` | |
| `observability/collaboration_tracker.py` | `test_collaboration_tracker.py` | `[ ]` | |
| `observability/decision_tracker.py` | `test_decision_tracker.py` | `[ ]` | |
| `observability/dialogue_metrics.py` | `test_dialogue_metrics.py` | `[ ]` | |
| `observability/failover_events.py` | `test_failover_events.py` | `[ ]` | |
| `observability/formatters.py` | `test_formatters.py` | `[ ]` | |
| `observability/lineage.py` | `test_lineage.py` | `[ ]` | |
| `observability/merit_score_service.py` | `test_merit_score_service.py` | `[ ]` | |
| `observability/metric_aggregator.py` | `test_metric_aggregation_refactored.py` | `[ ]` | |
| `observability/migrations.py` | `test_migrations.py` | `[ ]` | |
| `observability/otel_setup.py` | `test_otel_setup.py`, `test_otel_httpx_default.py`, `test_otel_span_cleanup.py`, `test_otel_span_events.py` | `[ ]` | |
| `observability/performance.py` | `test_performance.py`, `test_performance_cleanup.py` | `[ ]` | |
| `observability/resilience_events.py` | `test_resilience_events.py` | `[ ]` | |
| `observability/rollback_logger.py` | `test_rollback_logger.py`, `test_rollback_logging.py` | `[ ]` | |
| `observability/rollback_types.py` | `test_rollback_types.py` | `[ ]` | |
| `observability/sampling.py` | `test_sampling.py` | `[ ]` | |
| `observability/sanitization.py` | `test_sanitization_comprehensive.py`, `test_llm_sanitization.py`, `test_allowlist_pii_35.py` | `[ ]` | |
| `observability/trace_export.py` | _(none found)_ | `[ ]` | **GAP?** |
| `observability/types.py` | `test_models.py` | `[ ]` | |
| `observability/visualize_trace.py` | `test_visualize_trace.py`, `test_visualize_trace_comprehensive.py` | `[ ]` | |
| `observability/constants.py` | `test_constants.py` | `[ ]` | |
| `observability/_buffer_helpers.py` | _(indirect?)_ | `[ ]` | |
| `observability/_quality_scorer.py` | `test_quality_scorer.py` | `[ ]` | |
| `observability/_tracker_helpers.py` | _(indirect?)_ | `[ ]` | |
| `observability/aggregation/aggregator.py` | `aggregation/test_aggregator.py`, `test_aggregation.py` | `[ ]` | |
| `observability/aggregation/metric_creator.py` | `aggregation/test_metric_creator.py` | `[ ]` | |
| `observability/aggregation/period.py` | `test_aggregation_period.py` | `[ ]` | |
| `observability/aggregation/query_builder.py` | `aggregation/test_query_builder.py` | `[ ]` | |
| `observability/aggregation/time_window.py` | `test_aggregation_time_window.py` | `[ ]` | |
| `observability/backends/composite_backend.py` | `backends/test_composite_backend.py` | `[ ]` | |
| `observability/backends/noop_backend.py` | `backends/test_noop_backend.py` | `[ ]` | |
| `observability/backends/otel_backend.py` | _(none found)_ | `[ ]` | **GAP?** |
| `observability/backends/prometheus_backend.py` | `backends/test_prometheus_backend.py` | `[ ]` | |
| `observability/backends/s3_backend.py` | `backends/test_s3_backend.py` | `[ ]` | |
| `observability/backends/sql_backend.py` | `backends/test_sql_backend.py`, `test_sql_backend_connection_leak.py` | `[ ]` | |
| `observability/backends/_sql_backend_helpers.py` | _(indirect?)_ | `[ ]` | |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_cascade_delete_27.py` | Cascade delete fix | `[ ]` | |
| `test_database.py` | Database observability | `[ ]` | |
| `test_database_failures.py` | DB failure handling | `[ ]` | |
| `test_distributed_tracking.py` | Distributed tracking | `[ ]` | |
| `test_init_exports.py` | Module exports | `[ ]` | |
| `test_llm_loop_events.py` | LLM loop events | `[ ]` | |
| `test_n_plus_one.py` | N+1 query detection | `[ ]` | |
| `test_observability_edge_cases.py` | Edge cases | `[ ]` | |
| `test_prompt_version_tracking.py` | Prompt version tracking | `[ ]` | |
| `test_read_api.py` | Read API | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 13. Goals (`temper_ai/goals/` → `tests/test_goals/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `goals/agent_goals.py` | `test_agent_goals.py` | `[ ]` | |
| `goals/analysis_orchestrator.py` | `test_analysis_orchestrator.py` | `[ ]` | |
| `goals/analyzers/base.py` | `test_analyzers.py` | `[ ]` | |
| `goals/analyzers/cost.py` | `test_analyzers.py` | `[ ]` | |
| `goals/analyzers/cross_product.py` | `test_analyzers.py` | `[ ]` | |
| `goals/analyzers/performance.py` | `test_analyzers.py` | `[ ]` | |
| `goals/analyzers/reliability.py` | `test_analyzers.py` | `[ ]` | |
| `goals/background.py` | `test_background.py` | `[ ]` | |
| `goals/dashboard_routes.py` | `test_goal_routes.py` | `[ ]` | |
| `goals/dashboard_service.py` | _(none found)_ | `[ ]` | **GAP?** |
| `goals/models.py` | _(none found)_ | `[ ]` | **GAP?** |
| `goals/proposer.py` | `test_proposer.py` | `[ ]` | |
| `goals/review_workflow.py` | `test_review_workflow.py` | `[ ]` | |
| `goals/safety_policy.py` | `test_safety_policy.py` | `[ ]` | |
| `goals/store.py` | `test_store.py` | `[ ]` | |
| `goals/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `goals/constants.py` | _(none)_ | `[ ]` | Constants |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 14. Lifecycle (`temper_ai/lifecycle/` → `tests/test_lifecycle/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `lifecycle/adapter.py` | `test_adapter.py` | `[ ]` | |
| `lifecycle/classifier.py` | `test_classifier.py` | `[ ]` | |
| `lifecycle/experiment.py` | `test_experiment.py` | `[ ]` | |
| `lifecycle/history.py` | `test_history.py` | `[ ]` | |
| `lifecycle/models.py` | _(none found)_ | `[ ]` | **GAP?** |
| `lifecycle/profiles.py` | `test_profiles.py` | `[ ]` | |
| `lifecycle/rollback.py` | `test_rollback.py` | `[ ]` | |
| `lifecycle/store.py` | `test_store.py` | `[ ]` | |
| `lifecycle/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `lifecycle/dashboard_routes.py` | _(none found)_ | `[ ]` | **GAP?** |
| `lifecycle/constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_lifecycle_integration.py` | Lifecycle integration | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 15. Learning (`temper_ai/learning/` → `tests/test_learning/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `learning/auto_tune.py` | `test_auto_tune.py` | `[ ]` | |
| `learning/background.py` | `test_background.py` | `[ ]` | |
| `learning/convergence.py` | `test_convergence.py` | `[ ]` | |
| `learning/dashboard_routes.py` | `test_learning_routes.py` | `[ ]` | |
| `learning/dashboard_service.py` | _(none found)_ | `[ ]` | **GAP?** |
| `learning/orchestrator.py` | `test_orchestrator.py` | `[ ]` | |
| `learning/recommender.py` | `test_recommender.py` | `[ ]` | |
| `learning/store.py` | `test_store.py` | `[ ]` | |
| `learning/models.py` | `test_models.py` | `[ ]` | |
| `learning/miners/base.py` | `test_miners.py` | `[ ]` | |
| `learning/miners/agent_performance.py` | `test_miners.py` | `[ ]` | |
| `learning/miners/collaboration_patterns.py` | `test_miners.py` | `[ ]` | |
| `learning/miners/cost_patterns.py` | `test_miners.py` | `[ ]` | |
| `learning/miners/failure_patterns.py` | `test_miners.py` | `[ ]` | |
| `learning/miners/model_effectiveness.py` | `test_miners.py` | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 16. Autonomy (`temper_ai/autonomy/` → `tests/test_autonomy/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `autonomy/orchestrator.py` | `test_orchestrator.py` | `[ ]` | |
| `autonomy/audit.py` | `test_audit.py` | `[ ]` | |
| `autonomy/feedback_applier.py` | `test_feedback_applier.py` | `[ ]` | |
| `autonomy/memory_bridge.py` | `test_memory_bridge.py` | `[ ]` | |
| `autonomy/rollout.py` | `test_rollout.py` | `[ ]` | |
| `autonomy/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `autonomy/constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_agent_memory_sync.py` | Agent memory sync | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 17. Experimentation (`temper_ai/experimentation/` → `tests/test_experimentation/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `experimentation/analyzer.py` | `test_analyzer.py` | `[ ]` | |
| `experimentation/assignment.py` | `test_assignment.py`, `test_assigner.py`, `test_random_assign_38.py` | `[ ]` | |
| `experimentation/config_manager.py` | `test_config_manager.py` | `[ ]` | |
| `experimentation/dashboard_routes.py` | `test_dashboard_routes.py` | `[ ]` | |
| `experimentation/dashboard_service.py` | `test_dashboard_service.py` | `[ ]` | |
| `experimentation/experiment_crud.py` | `test_crud.py` | `[ ]` | |
| `experimentation/metrics_collector.py` | `test_metrics_collector.py` | `[ ]` | |
| `experimentation/models.py` | `test_models.py` | `[ ]` | |
| `experimentation/sequential_testing.py` | `test_sequential_testing.py`, `test_early_stopping.py` | `[ ]` | |
| `experimentation/service.py` | `test_service.py`, `test_service_security.py` | `[ ]` | |
| `experimentation/validators.py` | `test_validators.py` | `[ ]` | |
| `experimentation/_workflow_integration.py` | `test_workflow_integration.py` | `[ ]` | |
| `experimentation/constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_cache_eviction.py` | Cache eviction | `[ ]` | |
| `test_database_failures.py` | DB failure handling | `[ ]` | |
| `test_detached_orm_14.py` | Detached ORM fix | `[ ]` | |
| `test_experiment_lifecycle.py` | Experiment lifecycle | `[ ]` | |
| `test_n1_query_32.py` | N+1 query fix | `[ ]` | |
| `test_observability_integration.py` | Observability integration | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 18. Portfolio (`temper_ai/portfolio/` → `tests/test_portfolio/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `portfolio/optimizer.py` | `test_optimizer.py` | `[ ]` | |
| `portfolio/component_analyzer.py` | `test_component_analyzer.py` | `[ ]` | |
| `portfolio/knowledge_graph.py` | `test_knowledge_graph.py` | `[ ]` | |
| `portfolio/loader.py` | `test_loader.py` | `[ ]` | |
| `portfolio/scheduler.py` | `test_scheduler.py` | `[ ]` | |
| `portfolio/store.py` | `test_store.py` | `[ ]` | |
| `portfolio/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `portfolio/_tracking.py` | _(none found)_ | `[ ]` | **GAP?** |
| `portfolio/dashboard_routes.py` | _(none found)_ | `[ ]` | **GAP?** |
| `portfolio/models.py` | _(none found)_ | `[ ]` | **GAP?** |
| `portfolio/constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_portfolio_integration.py` | Portfolio integration | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 19. Optimization (`temper_ai/optimization/` → `tests/test_optimization/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `optimization/engine.py` | `test_engine.py` | `[ ]` | |
| `optimization/evaluation_dispatcher.py` | `test_evaluation_dispatcher.py` | `[ ]` | |
| `optimization/protocols.py` | `test_protocols.py` | `[ ]` | |
| `optimization/registry.py` | `test_registry.py` | `[ ]` | |
| `optimization/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `optimization/_evaluation_schemas.py` | `test_evaluation_schemas.py`, `test_engine_schemas.py` | `[ ]` | |
| `optimization/_experiment_helpers.py` | `test_experiment_helpers.py` | `[ ]` | |
| `optimization/evaluators/comparative.py` | `evaluators/test_comparative.py` | `[ ]` | |
| `optimization/evaluators/composite.py` | `evaluators/test_composite.py` | `[ ]` | |
| `optimization/evaluators/criteria.py` | `evaluators/test_criteria.py` | `[ ]` | |
| `optimization/evaluators/human.py` | `evaluators/test_human.py` | `[ ]` | |
| `optimization/evaluators/scored.py` | `evaluators/test_scored.py` | `[ ]` | |
| `optimization/optimizers/prompt.py` | `optimizers/test_prompt.py` | `[ ]` | |
| `optimization/optimizers/refinement.py` | `optimizers/test_refinement.py` | `[ ]` | |
| `optimization/optimizers/selection.py` | `optimizers/test_selection.py` | `[ ]` | |
| `optimization/optimizers/tuning.py` | `optimizers/test_tuning.py` | `[ ]` | |
| `optimization/dspy/compiler.py` | `test_compiler.py` | `[ ]` | |
| `optimization/dspy/data_collector.py` | `test_data_collector.py`, `test_data_collector_evaluation.py` | `[ ]` | |
| `optimization/dspy/metrics.py` | `test_metrics.py` | `[ ]` | |
| `optimization/dspy/modules.py` | `test_modules_registry.py` | `[ ]` | |
| `optimization/dspy/optimizers.py` | `test_optimizers_registry.py` | `[ ]` | |
| `optimization/dspy/program_builder.py` | `test_program_builder.py` | `[ ]` | |
| `optimization/dspy/program_store.py` | `test_program_store.py` | `[ ]` | |
| `optimization/dspy/prompt_adapter.py` | `test_prompt_adapter.py` | `[ ]` | |
| `optimization/dspy/_helpers.py` | _(indirect?)_ | `[ ]` | |
| `optimization/dspy/_schemas.py` | _(indirect?)_ | `[ ]` | |
| `optimization/dspy/constants.py` | _(none)_ | `[ ]` | Constants |
| `optimization/engine_constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_integration.py` | Optimization integration | `[ ]` | |
| `test_unified_integration.py` | Unified integration | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---
---

# PHASE 5 — PLATFORM & INTEGRATION

---

## 20. Plugins (`temper_ai/plugins/` → `tests/test_plugins/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `plugins/base.py` | `test_base.py` | `[ ]` | |
| `plugins/registry.py` | `test_registry.py` | `[ ]` | |
| `plugins/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `plugins/_import_helpers.py` | `test_import_helpers.py` | `[ ]` | |
| `plugins/adapters/openai_agents_adapter.py` | `test_openai_agents_adapter.py` | `[ ]` | |
| `plugins/adapters/crewai_adapter.py` | `test_crewai_adapter.py` | `[ ]` | |
| `plugins/adapters/autogen_adapter.py` | `test_autogen_adapter.py` | `[ ]` | |
| `plugins/adapters/langgraph_adapter.py` | `test_langgraph_adapter.py` | `[ ]` | |
| `plugins/constants.py` | _(none)_ | `[ ]` | Constants |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 21. MCP (`temper_ai/mcp/` → `tests/test_mcp/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `mcp/manager.py` | `test_manager.py` | `[ ]` | |
| `mcp/server.py` | `test_server.py` | `[ ]` | |
| `mcp/tool_wrapper.py` | `test_tool_wrapper.py` | `[ ]` | |
| `mcp/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `mcp/_server_helpers.py` | _(indirect?)_ | `[ ]` | |
| `mcp/_client_helpers.py` | _(none found)_ | `[ ]` | **GAP?** |
| `mcp/constants.py` | _(none)_ | `[ ]` | Constants |

### Standalone Test Files

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_integration.py` | MCP integration | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 22. Interfaces (`temper_ai/interfaces/` → `tests/test_interfaces/`)

### Source → Test Coverage Map

**CLI:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `interfaces/cli/main.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/cli/__main__.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/cli/server_client.py` | `test_server/test_server_client.py` | `[ ]` | |

**Server:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `interfaces/server/auth.py` | `test_server/test_auth.py` | `[ ]` | |
| `interfaces/server/auth_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/health.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/lifecycle.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/models.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/run_store.py` | `test_server/test_run_store.py` | `[ ]` | |
| `interfaces/server/workflow_runner.py` | `test_server/test_workflow_runner.py` | `[ ]` | |
| `interfaces/server/agent_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/chat_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/checkpoint_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/config_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/event_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/memory_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/optimization_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/plugin_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/rollback_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/scaffold_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/template_routes.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/server/visualize_routes.py` | _(none found)_ | `[ ]` | **GAP** |

**Dashboard:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `interfaces/dashboard/app.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/dashboard/data_service.py` | _(none found)_ | `[ ]` | **GAP** |
| `interfaces/dashboard/routes.py` | `test_dashboard/test_routes.py` | `[ ]` | |
| `interfaces/dashboard/studio_routes.py` | `test_dashboard/test_studio_routes.py` | `[ ]` | |
| `interfaces/dashboard/studio_service.py` | `test_dashboard/test_studio_service.py` | `[ ]` | |
| `interfaces/dashboard/websocket.py` | `test_dashboard/test_websocket.py` | `[ ]` | |
| `interfaces/dashboard/constants.py` | _(none)_ | `[ ]` | Constants |
| `interfaces/dashboard/_studio_validation_helpers.py` | _(indirect?)_ | `[ ]` | |

### Issues Found
- **CRITICAL: 11 test files for 35 source files — massive coverage gap in server routes**
- _(detailed findings during audit)_

### Feature Score: —/10

---

## 23. Config (`temper_ai/config/` → `tests/test_config/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `config/settings.py` | `test_settings.py` | `[ ]` | |
| `config/_loader.py` | `test_loader.py` | `[ ]` | |
| `config/_compat.py` | `test_compat.py` | `[ ]` | |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 24. Evaluation (`temper_ai/evaluation/` → `tests/test_evaluation/`)

### Source → Test Coverage Map

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `evaluation/runner.py` | `test_runner.py` | `[ ]` | |
| `evaluation/_schemas.py` | `test_schemas.py` | `[ ]` | |
| `evaluation/constants.py` | _(none)_ | `[ ]` | Constants |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---

## 25. Shared (`temper_ai/shared/` → `tests/test_shared/`)

### Source → Test Coverage Map

**Core:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `shared/core/context.py` | `test_core/test_context.py` | `[ ]` | |
| `shared/core/protocols.py` | `test_core/test_registry_protocol.py` | `[ ]` | |
| `shared/core/service.py` | _(none found)_ | `[ ]` | **GAP?** |
| `shared/core/stream_events.py` | _(none found)_ | `[ ]` | **GAP?** |
| `shared/core/test_support.py` | _(none found)_ | `[ ]` | Test support utility |
| `shared/core/circuit_breaker.py` | _(none found)_ | `[ ]` | **GAP?** |
| `shared/core/_circuit_breaker_helpers.py` | _(none found)_ | `[ ]` | **GAP?** |
| `shared/core/constants.py` | _(none)_ | `[ ]` | Constants |

**Utils:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `shared/utils/config_helpers.py` | `test_utils/test_config_helpers.py` | `[ ]` | |
| `shared/utils/config_migrations.py` | `test_utils/test_config_migrations.py` | `[ ]` | |
| `shared/utils/error_handling.py` | `test_utils/test_error_handling.py`, `test_error_handling_extended.py` | `[ ]` | |
| `shared/utils/exceptions.py` | `test_utils/test_exceptions.py` | `[ ]` | |
| `shared/utils/logging.py` | `test_utils/test_logging_utils.py`, `test_logging_extended.py` | `[ ]` | |
| `shared/utils/secrets.py` | `test_utils/test_secrets.py` | `[ ]` | |
| `shared/utils/secret_patterns.py` | _(indirect via test_secrets?)_ | `[ ]` | |
| `shared/utils/exception_fields.py` | _(none found)_ | `[ ]` | **GAP?** |
| `shared/utils/datetime_utils.py` | _(none found)_ | `[ ]` | **GAP?** |
| `shared/utils/constants.py` | _(none)_ | `[ ]` | Constants |

**Path Safety:**

| Source File | Test File(s) | Covered? | Notes |
|-------------|-------------|----------|-------|
| `shared/utils/path_safety/validator.py` | `test_utils/test_path_safety.py` | `[ ]` | |
| `shared/utils/path_safety/path_rules.py` | `test_utils/test_path_safety.py` | `[ ]` | |
| `shared/utils/path_safety/symlink_validator.py` | `test_utils/test_path_safety.py` | `[ ]` | |
| `shared/utils/path_safety/temp_directory.py` | `test_utils/test_path_safety.py` | `[ ]` | |
| `shared/utils/path_safety/platform_detector.py` | `test_utils/test_path_safety.py` | `[ ]` | |
| `shared/utils/path_safety/exceptions.py` | `test_utils/test_path_safety.py` | `[ ]` | |

**Constants (no tests needed):**

| Source File | Notes |
|-------------|-------|
| `shared/constants/agent_defaults.py` | Constants |
| `shared/constants/convergence.py` | Constants |
| `shared/constants/durations.py` | Constants |
| `shared/constants/execution.py` | Constants |
| `shared/constants/limits.py` | Constants |
| `shared/constants/probabilities.py` | Constants |
| `shared/constants/retries.py` | Constants |
| `shared/constants/sizes.py` | Constants |
| `shared/constants/timeouts.py` | Constants |

### Issues Found
- _(to be populated during audit)_

### Feature Score: —/10

---
---

# PHASE 6 — CROSS-CUTTING TESTS

---

## 26. Cross-cutting Tests

### 26a. Integration Tests (`tests/integration/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_agent_tool_integration.py` | Agent + tool integration | `[ ]` | |
| `test_checkpoint_resume.py` | Checkpoint resume | `[ ]` | |
| `test_component_integration.py` | Component integration | `[ ]` | |
| `test_compiler_engine_observability.py` | Compiler + engine + obs | `[ ]` | |
| `test_coverage_clusters.py` | Coverage clusters | `[ ]` | |
| `test_cross_module.py` | Cross-module tests | `[ ]` | |
| `test_e2e_workflow.py` | E2E workflow | `[ ]` | |
| `test_e2e_workflows.py` | E2E workflows (plural) | `[ ]` | |
| `test_error_propagation_e2e.py` | Error propagation E2E | `[ ]` | |
| `test_error_propagation_real.py` | Real error propagation | `[ ]` | |
| `test_m2_e2e.py` | M2 E2E | `[ ]` | |
| `test_m3_multi_agent.py` | M3 multi-agent | `[ ]` | |
| `test_multi_agent_workflows.py` | Multi-agent workflows | `[ ]` | |
| `test_performance.py` | Performance | `[ ]` | |
| `test_performance_simple.py` | Simple performance | `[ ]` | |
| `test_timeout_propagation.py` | Timeout propagation | `[ ]` | |
| `test_tool_rollback.py` | Tool rollback | `[ ]` | |
| `test_workflow_recovery.py` | Workflow recovery | `[ ]` | |

### 26b. Property-Based Tests (`tests/property/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_consensus_properties.py` | Consensus properties | `[ ]` | |
| `test_validation_properties.py` | Validation properties | `[ ]` | |

### 26c. Regression Tests (`tests/test_regression/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_config_loading_regression.py` | Config loading regression | `[ ]` | |
| `test_integration_regression.py` | Integration regression | `[ ]` | |
| `test_performance_regression.py` | Performance regression | `[ ]` | |
| `test_tool_execution_regression.py` | Tool execution regression | `[ ]` | |

### 26d. Benchmark Tests (`tests/test_benchmarks/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_baseline_benchmarks.py` | Baseline benchmarks | `[ ]` | |
| `test_benchmarks_compilation.py` | Compilation benchmarks | `[ ]` | |
| `test_benchmarks_database.py` | Database benchmarks | `[ ]` | |
| `test_performance_agents.py` | Agent performance | `[ ]` | |
| `test_performance_benchmarks.py` | General perf benchmarks | `[ ]` | |
| `test_performance_cache_network.py` | Cache + network perf | `[ ]` | |
| `test_performance_e2e.py` | E2E performance | `[ ]` | |
| `test_performance_llm.py` | LLM performance | `[ ]` | |
| `test_performance_strategies.py` | Strategy performance | `[ ]` | |
| `test_performance_tools.py` | Tool performance | `[ ]` | |

### 26e. Load Tests (`tests/test_load/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_stress.py` | Stress testing | `[ ]` | |

### 26f. Async Tests (`tests/test_async/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_concurrency.py` | Concurrency | `[ ]` | |
| `test_concurrent_safety.py` | Concurrent safety | `[ ]` | |

### 26g. Error Handling Tests (`tests/test_error_handling/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_comprehensive_errors.py` | Comprehensive errors | `[ ]` | |
| `test_error_propagation.py` | Error propagation | `[ ]` | |
| `test_timeout_scenarios.py` | Timeout scenarios | `[ ]` | |

### 26h. Validation Tests (`tests/test_validation/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_boundary_values.py` | Boundary values | `[ ]` | |
| `test_edge_cases_comprehensive.py` | Comprehensive edge cases | `[ ]` | |
| `test_unicode_edge_cases.py` | Unicode edge cases | `[ ]` | |

### 26i. Root-Level Tests (`tests/`)

| Test File | What It Tests | Status | Notes |
|-----------|--------------|--------|-------|
| `test_architecture_scan.py` | Architecture scanning | `[ ]` | |
| `test_boundary_values.py` | Boundary values | `[ ]` | |
| `test_documentation_examples.py` | Documentation examples | `[ ]` | |
| `test_executor_cleanup.py` | Executor cleanup | `[ ]` | |
| `test_llm_cache.py` | LLM cache | `[ ]` | |
| `test_log_redact_39.py` | Log redaction fix | `[ ]` | |
| `test_logging.py` | Logging | `[ ]` | |
| `test_memory_eviction_13b.py` | Memory eviction fix | `[ ]` | |
| `test_memory_leaks.py` | Memory leaks | `[ ]` | |
| `test_prompt_caching.py` | Prompt caching | `[ ]` | |
| `test_secrets.py` | Secrets | `[ ]` | |
| `test_thread_safety_singletons.py` | Thread safety singletons | `[ ]` | |

### 26j. Fixtures (`tests/fixtures/`) — Review for quality

| Fixture File | Purpose | Status | Notes |
|-------------|---------|--------|-------|
| `auth_fixtures.py` | Auth test fixtures | `[ ]` | |
| `boundary_values.py` | Boundary value data | `[ ]` | |
| `database_fixtures.py` | DB fixtures | `[ ]` | |
| `error_helpers.py` | Error test helpers | `[ ]` | |
| `llm_responses.py` | Mock LLM responses | `[ ]` | |
| `mock_helpers.py` | Mock utilities | `[ ]` | |
| `realistic_data.py` | Realistic test data | `[ ]` | |
| `timeout_helpers.py` | Timeout helpers | `[ ]` | |

### Cross-cutting Score: —/10

---
---

# SUMMARY

## Pre-Audit Red Flags (from source-to-test mapping)

| Priority | Issue | Feature | Details |
|----------|-------|---------|---------|
| **CRITICAL** | Massive gap | Storage | 2 test files for 14 source files |
| **CRITICAL** | Massive gap | Interfaces | 11 test files for 35 source files (most server routes untested) |
| **HIGH** | Large gap | LLM | 10 test files for 34 source files (providers untested) |
| **HIGH** | Possible dupes | Auth | Same source tested in both `test_auth/` and `test_auth/oauth/` |
| **MEDIUM** | Coverage gap | Safety | `config_change_policy`, `entropy_analyzer`, `rollback` untested |
| **MEDIUM** | Coverage gap | Observability | `trace_export`, `otel_backend` untested |
| **MEDIUM** | Coverage gap | Shared | `circuit_breaker`, `service`, `stream_events` untested |

## Final Dashboard

| Metric | Value |
|--------|-------|
| Features Audited | 0 / 26 |
| Total Test Files Reviewed | 0 / ~500 |
| Total Issues Found | 0 |
| Critical Issues | 0 |
| Average Score | —/10 |
| Pre-Audit Red Flags | 7 |

## Changelog

| Date | Feature | Action |
|------|---------|--------|
| 2026-02-28 | — | Plan created with per-file breakdown |
