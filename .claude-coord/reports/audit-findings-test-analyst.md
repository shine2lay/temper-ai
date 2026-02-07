# Audit Findings: Test Quality Analyst

**Date:** 2026-02-07
**Agent:** test-analyst
**Scope:** Full test suite (`tests/`, 259 test files, ~1254+ test functions across 248+ modules)

---

## Summary

The test suite has strong coverage for core modules (agents, compiler, safety, observability, auth) with good assertion quality and proper test isolation via the root conftest.py auto-reset fixture. However, there are significant coverage gaps in the self_improvement subsystem and utility modules, a low ratio of spec'd mocks (28.6%), concerning flakiness from 100+ `time.sleep` calls, and architectural issues including duplicate test directories and a stale test file.

| Severity | Count |
|----------|-------|
| CRITICAL | 3 |
| HIGH | 6 |
| MEDIUM | 8 |
| LOW | 4 |
| INFO | 3 |
| **Total** | **24** |

---

## Findings

| # | Severity | Category | File/Location | Finding | Recommendation |
|---|----------|----------|---------------|---------|----------------|
| 1 | CRITICAL | coverage-gap | `src/self_improvement/` (15+ files) | **15 source files completely untested**: `cli.py`, `data_models.py`, `model_registry.py`, `pattern_mining.py`, `strategy_learning.py`, `loop/error_recovery.py`, `loop/orchestrator.py`, `deployment/deployer.py`, `detection/improvement_proposal.py`, `detection/problem_config.py`, `detection/problem_models.py`, `metrics/erc721_quality.py`, `strategies/erc721_strategy.py`, `strategies/prompt_optimization_strategy.py`, `strategies/temperature_search_strategy.py`. The module has 37 source files but only 5 dedicated test files in `test_self_improvement/` (plus 21 in the older `self_improvement/` dir which uses a non-standard naming convention). | Add unit tests for `loop/orchestrator.py` and `loop/error_recovery.py` (experiment execution and error recovery). Prioritize `deployer.py` (deployment without tests is high-risk). |
| 2 | CRITICAL | coverage-gap | `src/utils/error_handling.py`, `src/utils/config_migrations.py`, `src/utils/secret_patterns.py` | **3 utility modules have zero test coverage**. `error_handling.py` provides framework-wide error handling utilities. `secret_patterns.py` contains regex patterns for secret detection -- if patterns regress, secrets could leak. `config_migrations.py` handles config schema migrations. The `utils` module has 8 source files but only 2 test files (`test_config_helpers.py`, `test_path_safety.py`). | Add dedicated tests for `secret_patterns.py` (regex validation against known secret formats) and `error_handling.py` (error transformation logic). These are security-adjacent modules. |
| 3 | CRITICAL | coverage-gap | `src/core/service.py`, `src/core/test_support.py` | **Core framework abstractions lack direct tests**. `src/core/service.py` defines the `Service` ABC (base for all framework services). `src/core/test_support.py` provides `reset_all_globals()` and `isolated_globals()` used by the root conftest -- but the module itself is untested. If `_get_all_reset_functions()` silently fails to collect reset functions, test isolation breaks across the **entire** suite. Core has 5 source files but only 2 test files (`test_context.py`, `test_registry_protocol.py`). | Add tests for `test_support.py` to verify `reset_all_globals()` actually resets state, `isolated_globals()` provides proper isolation, and `register_reset()` correctly adds to the registry. |
| 4 | HIGH | mock-quality | Tests-wide (521 unspec'd vs 209 spec'd) | **71.4% of mocks lack `spec=` parameter** (521 `Mock()`/`MagicMock()` without spec vs 209 with `spec=`/`create_autospec`). Mocks without `spec` silently accept any attribute access, masking interface drift. Heavy offenders: `test_executors_parallel.py` (31 unspec'd), `test_stage_compiler.py` (26), `test_llm_providers.py` (21), `test_node_builder.py` (20). | Enforce `spec=` for new mocks via code review. Prioritize adding `spec=` to mocks for `SafetyPolicy`, `ToolExecutor`, `BaseLLM`, and `ExecutionEngine` interfaces where interface drift has the highest impact. |
| 5 | HIGH | flaky-test | 30+ files with `time.sleep()` | **100+ `time.sleep()` calls across 30+ test files**. Examples: `test_llm_providers.py:1780` (`sleep(1.1)`), `test_auth/test_rate_limiter.py:54` (`sleep(3)`), `test_observability/test_console_streaming.py` (12 sleep calls, 0.2-0.6s each), `test_token_bucket.py:305` (comment: "increased margin for slow runners"). Total CI impact: 60+ seconds of pure sleep time plus timing-dependent flakiness. | Replace `time.sleep()` with deterministic approaches: mock `time.monotonic()`/`time.time()`, use `freezegun`/`time_machine`, or use `threading.Event.wait(timeout=)` for synchronization. |
| 6 | HIGH | test-architecture | `tests/self_improvement/` vs `tests/test_self_improvement/` | **Duplicate test directories** for the same module. `tests/self_improvement/` contains 21 test files (older style). `tests/test_self_improvement/` contains 5 test files (current convention). Developers are unsure where to add tests, and tests in the non-standard directory may be missed depending on CI path filters. | Consolidate into `tests/test_self_improvement/` following the project `test_` prefix convention. Migrate unique tests from `tests/self_improvement/` and delete the old directory. |
| 7 | HIGH | coverage-gap | `src/compiler/security_limits.py` | **Security limits module has no dedicated tests.** Defines constants protecting against memory exhaustion, stack overflow, and billion laughs attacks (MAX_CONFIG_SIZE, MAX_NESTING_DEPTH, etc.). While `test_config_security.py` may exercise some limits indirectly, there are no direct tests verifying limit values or behavior when exceeded. | Create `tests/test_compiler/test_security_limits.py` with explicit tests verifying each limit constant and the error behavior when limits are exceeded. |
| 8 | HIGH | assertion-quality | `tests/test_agents/test_llm_providers.py:1732-2015` | **Bare `except: pass` clauses in circuit breaker persistence tests.** The `TestCircuitBreakerPersistence` class uses `except: pass` to swallow all exceptions. If setup fails for unexpected reasons (NameError, AttributeError), tests may pass or fail for the wrong reason. | Replace bare `except:` with specific exception types: `except (httpx.TimeoutException, CircuitBreakerError):`. |
| 9 | HIGH | test-architecture | `tests/test_safety/test_distributed_rate_limiting.py` | **8 tests marked `@pytest.mark.xfail`** because distributed rate limiting via Redis is not implemented. These tests document missing functionality but don't validate anything. They become invisible technical debt. | Either implement the distributed backend and remove xfail, or convert to `@pytest.mark.skip` with a ticket reference. xfail should not be permanent. |
| 10 | MEDIUM | test-architecture | `tests/test_security/test_security_bypasses_OLD.py` (455 lines) | **Stale test file** with `_OLD` suffix alongside current `test_security_bypasses.py` (633 lines). Both test security bypass techniques. The OLD file adds CI time without clear value and may test against stale implementations. | Review for unique test cases, migrate any unique coverage to the current file, then delete `_OLD`. |
| 11 | MEDIUM | mock-quality | `tests/test_compiler/conftest.py:38` | **`mock_streaming_graph` fixture uses `Mock()` without `spec`**. Tests using this fixture won't catch if the real graph's API changes (e.g., `stream()` method renamed or signature changed). | Use `Mock(spec=StateGraph)` or the actual graph type. |
| 12 | MEDIUM | assertion-quality | `tests/test_observability/test_console_streaming.py` | **Tests rely on timing for assertions** -- 12 sleep calls in 320 lines. Tests verify visualization by sleeping and checking thread state. Only 27 assertions in the entire file. Inherently unreliable. | Use `threading.Event` for synchronization. Assert on `StringIO` content. Mock `poll_interval` to 0. |
| 13 | MEDIUM | test-isolation | `tests/test_observability/test_console_streaming.py:33` + multiple observability tests | **Direct mutation of module-level globals**: `db_module._db_manager = db_manager`. If a test fails before teardown, the global leaks. Found in 6+ observability test files. | Use `monkeypatch.setattr()` which guarantees cleanup even on test failure. |
| 14 | MEDIUM | over-mocking | `tests/test_compiler/test_execution_engine.py` | **12 tests verify abstract interface with `hasattr`/`__isabstractmethod__` checks** rather than testing actual behavior. These pass even if methods have wrong signatures. | Replace with concrete subclass tests that verify the interface contract. Test actual compile/execute behavior. |
| 15 | MEDIUM | coverage-gap | `src/strategies/conflict_resolution.py` | **Limited edge case coverage.** `test_conflict_resolution.py` has only 19 test functions for complex tie-breaking and multi-party disagreement logic (compare: `test_dialogue.py` has 78 tests). | Add edge cases: all-disagree, single-agent, maximum agents, identical scores, unicode content. |
| 16 | MEDIUM | assertion-quality | 5 files with bare assertions | **Weak assertions**: `test_workflow_state_transitions.py:193` (`assert valid`), `test_file_access.py:842` (`assert has_forbidden`), `test_llm_security.py:1638` (`assert allowed`), `test_rollback_api.py:143` (`assert is_safe`), `test_visualize_trace.py:220` (`assert has_tree_chars`). | Add assertion messages: `assert valid, f"Expected valid transition for {state}"`. |
| 17 | MEDIUM | test-isolation | `tests/conftest.py` | **Global state reset uses lazy imports with broad except**. `reset_all_globals()` in `test_support.py` catches `ImportError` on each module. If an import fails (e.g., due to a syntax error in a dependency), that module's globals silently won't be reset, causing cross-test pollution. | Consider making imports unconditional for core modules (observability, safety, security). Only use try/except for truly optional modules. |
| 18 | LOW | test-architecture | `tests/` root level | **12 test files at root `tests/` level** instead of subdirectories: `test_architecture_scan.py`, `test_boundary_values.py`, `test_documentation_examples.py`, `test_executor_cleanup.py`, `test_llm_cache.py`, `test_logging.py`, `test_log_redact_39.py`, `test_memory_eviction_13b.py`, `test_memory_leaks.py`, `test_prompt_caching.py`, `test_secrets.py`, `test_thread_safety_singletons.py`. | Move to appropriate subdirectories (`test_llm_cache.py` -> `test_cache/`, `test_logging.py` -> `test_utils/`). |
| 19 | LOW | test-architecture | `tests/` conftest.py distribution | **Only 7 conftest.py files for 30+ test subdirectories**. Many directories share similar setup (database init, mock creation) without shared fixtures. 6+ observability test files independently set up `db_module._db_manager`. | Add `conftest.py` for high-volume directories (test_observability, test_safety) with shared fixtures. |
| 20 | LOW | missing-edge-case | `tests/test_agents/test_standard_agent.py` | **No concurrency tests for StandardAgent.** 32 test functions cover happy paths, errors, and validation, but don't test concurrent `execute()` calls or thread safety of tool registry interaction. | Add thread-safety tests for concurrent `StandardAgent.execute()`. |
| 21 | LOW | test-architecture | `tests/test_documentation_examples.py:178` | **Skipped test** ("Requires imports to be available - run in full test suite") indicates import-order dependence or missing fixture scope. | Fix import dependency so the test works in isolation, or mark as integration test. |
| 22 | INFO | test-architecture | `tests/conftest.py` | **Strong test isolation via root conftest.py**. The `_reset_globals_after_test` autouse fixture ensures all singletons are reset between tests. `src/core/test_support.py` provides comprehensive reset function registry. Well-designed pattern. | Document this pattern for new contributors. |
| 23 | INFO | test-architecture | `tests/test_agents/conftest.py` | **Good fixture design**: `minimal_agent_config` and `agent_config_with_tools` provide reusable, well-documented test configurations. `_reset_shared_circuit_breakers` autouse fixture prevents cross-test interference. | Replicate this pattern for other test directories. |
| 24 | INFO | assertion-quality | `tests/test_agents/test_standard_agent.py:246-253` | **Strong assertion pattern with messages**: Tests include descriptive assertion messages (`f"Expected AgentResponse, got {type(response)}"`, `f"Error should mention LLM failure, got: {response.error}"`). Makes failures immediately debuggable. | Promote this pattern across the codebase. |

---

## Key Metrics

| Metric | Value | Assessment |
|--------|-------|------------|
| Total test functions | ~5,565+ | Good volume |
| Test-to-source ratio | ~28 tests per source file | Excellent ratio |
| Mock with spec rate | 28.6% (209/730) | **Poor** -- should be >80% |
| `pytest.raises` usage | 857 occurrences in 124 files | Strong error path testing |
| Bare except in tests | 31 files | Needs cleanup |
| xfail tests | 8 (all in one file) | Needs triage |
| Skip/skipif tests | ~25 | Reasonable (platform/dependency conditional) |
| Conftest fixtures | 7 conftest files | Sparse for 30+ directories |
| `time.sleep()` in tests | 100+ calls in 30+ files | **Flakiness risk** |
| Duplicate directory pairs | 2+ (`self_improvement`, root-level files) | Needs consolidation |
| Untested source modules | 18+ (self_improvement: 15, utils: 3) | **Critical gap** |
| Stale test files | 1 (`test_security_bypasses_OLD.py`) | Should be removed |

---

## Top Regression Risks

1. **Secret pattern regressions**: `src/utils/secret_patterns.py` has zero tests. If regex patterns change, secrets could leak undetected.
2. **Test isolation failure**: If `test_support.py`'s `reset_all_globals()` silently fails for any module, all tests could be polluted by stale global state. The module itself has no tests.
3. **Self-improvement deployment**: `deployer.py` and `error_recovery.py` are completely untested. A bug in deployment or error recovery would go undetected.
4. **Interface drift via unspec'd mocks**: With 71.4% of mocks lacking `spec=`, API changes to core interfaces (SafetyPolicy, BaseLLM, ToolExecutor) would not be caught by existing tests.
5. **Flaky CI**: 100+ `time.sleep()` calls contribute 60+ seconds of deterministic wait time and create timing-dependent failures on slow CI runners.

---

## Cross-Agent Questions

For each finding from other audit agents, I will assess: **"Is there a test for this?"**

- Security vulnerabilities without regression tests are doubly dangerous -- they will regress
- Reliability issues (race conditions, resource leaks) need concurrent stress tests
- API contract changes need contract tests verifying request/response shapes
- Any structural refactoring without corresponding test updates is reckless
