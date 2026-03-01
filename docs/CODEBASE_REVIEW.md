# Temper AI — Codebase Review Tracker

**Started:** 2026-02-28
**Goal:** Systematically understand every file, starting from leaf nodes (zero deps), asking questions and fixing issues before moving on.

---

## How This Works

- Files are grouped by internal dependency count (0 → 1 → 2 → ...)
- Within each group, we go file by file
- For each file: read it, understand it, discuss, fix if needed, mark done
- A file is only reviewed after all its dependencies have been reviewed

---

## Layer 0 — Zero Internal Dependencies (True Leaves)

These files import nothing from the project. Pure foundations.

### 0.1 — shared/constants/ (pure value constants)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 1 | `shared/constants/sizes.py` | 30 | ✅ | Removed 14 unused (BUFFER_SIZE_*, SIZE_8-512KB, UUID_HEX_MEDIUM) |
| 2 | `shared/constants/timeouts.py` | ~~14~~ | ✅ | DELETED — duplicate of durations.py |
| 3 | `shared/constants/durations.py` | 71 | ✅ | Removed 14 dead + moved 4 single-consumer to their files |
| 4 | `shared/constants/retries.py` | 29 | ✅ | Removed 1 dead + moved 2 circuit breaker constants to circuit_breaker.py |
| 5 | `shared/constants/limits.py` | 60 | ✅ | Moved MIN_POSITIVE_VALUE + HTTP_*_ERROR to consuming files |
| 6 | `shared/constants/probabilities.py` | 34 | ✅ | Moved TOLERANCE_TIGHT to analyzer.py |
| 7 | `shared/constants/convergence.py` | ~~6~~ | ✅ | DELETED — all 3 constants moved to stage/_schemas.py |
| 8 | `shared/constants/execution.py` | 67 | ✅ | All 20 constants used, no changes |
| 9 | `shared/constants/agent_defaults.py` | 18 | ✅ | All 6 constants used, no changes |

### 0.2 — shared/utils/ (standalone utilities)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 10 | `shared/utils/exception_fields.py` | 24 | ✅ | DELETED — entirely unused, zero imports |
| 11 | `shared/utils/constants.py` | ~~9~~ | ✅ | DELETED — remaining 2 constants moved to shared/constants/limits.py |
| 12 | `shared/utils/secret_patterns.py` | 152 | ✅ | Added 3 new SECRET_PATTERNS (bearer, http_auth, url_query), MEDIUM_CONFIDENCE_PATTERNS, expanded SECRET_KEY_NAMES. Unified all consumers to use central registry. |
| 13 | `shared/utils/datetime_utils.py` | 54 | ✅ | All 4 functions well-used (utcnow: 59 consumers). No changes. |
| 14 | `shared/utils/exceptions.py` | 651 | ✅ | Removed 2 unused functions (wrap_exception, get_error_info), 2 unused classes (SafetyError, FrameworkValidationError), 11 orphaned ErrorCode members. 752→651 LOC. |
| 15 | `shared/utils/config_helpers.py` | 156 | ✅ | Removed 5 unused functions (merge_configs, extract_required_fields, set_nested_value, validate_config_structure, resolve_config_path). 317→156 LOC. |
| 16 | `shared/utils/config_migrations.py` | ~~294~~ | ✅ | DELETED — 0 production consumers. Speculative scaffolding never integrated. |
| 17 | `shared/utils/path_safety/platform_detector.py` | 96 | ✅ | All 4 methods used by path_rules.py + validator.py. No changes. |

### 0.3 — shared/core/ (core abstractions)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 18 | `shared/core/constants.py` | ~~33~~ | ✅ | DELETED — 7 constants inlined to circuit_breaker.py (sole consumer), 6 dead constants removed. Also consolidated shared/utils/constants.py → shared/constants/limits.py and deleted it. |
| 19 | `shared/core/context.py` | 104 | ✅ | Heavily used (25 importers). All fields/methods active. Missing trace_id noted (issue #19). No changes. |
| 20 | `shared/core/service.py` | 40 | ✅ | 2 production consumers (ExperimentService, SafetyServiceMixin). Clean ABC. No changes. |
| 21 | `shared/core/protocols.py` | 97 | ✅ | Removed 4 dead Protocols (Registry[T], ToolRegistryProtocol, PolicyRegistryProtocol, StrategyRegistryProtocol). 302→97 LOC. |
| 22 | `shared/core/stream_events.py` | 46 | ✅ | Removed 4 dead symbols (LLM_TOKEN, LLM_DONE, STATUS, from_llm_chunk). 90→46 LOC. |
| 23 | `shared/core/_circuit_breaker_helpers.py` | 460 | ✅ | Renamed 3 internal-only functions to `_` prefix (should_count_failure, should_attempt_reset, get_state_key). |

### 0.4 — config/ (settings management)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 24 | `config/_compat.py` | ~~55~~ | ✅ | DELETED — entire config/ package dead in production (0 callers outside tests) |
| 25 | `config/_loader.py` | ~~64~~ | ✅ | DELETED — see #24 |
| 26 | `config/settings.py` | ~~61~~ | ✅ | DELETED — see #24 |

### 0.5 — Other module constants (zero deps)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 27 | `events/constants.py` | 7 | ✅ | Removed 9 dead constants (8 event types + MAX_PAYLOAD_SIZE_BYTES). 16→7 LOC. |
| 28 | `events/_subscription_helpers.py` | 63 | ✅ | All symbols live. No changes. |
| 29 | `memory/constants.py` | 20 | ✅ | Removed 3 dead M9 constants + SECONDS_PER_DAY (use shared/constants/durations.py). 27→20 LOC. |
| 30 | `memory/agent_performance.py` | ~~92~~ | ✅ | DELETED — entire file dead in production (0 consumers). |
| 31 | `memory/extractors.py` | 76 | ✅ | All symbols live. No changes (3 constants could get `_` prefix later). |
| 32 | `memory/_m9_schemas.py` | 20 | ✅ | All symbols live. No changes (3 constants could get `_` prefix later). |
| 33 | `storage/schemas/constants.py` | ~~11~~ | ✅ | DELETED — entire file dead in production (0 consumers). |
| 34 | `storage/database/constants.py` | 28 | ✅ | Removed 4 dead FIELD_* constants. 37→28 LOC. |
| 35 | `llm/tool_keys.py` | 11 | ✅ | All symbols live. No changes. |
| 36 | `llm/llm_loop_events.py` | 110 | ✅ | Removed dead `_CACHE_KEY_PREFIX_LENGTH`. |
| 37 | `llm/output_validation.py` | 55 | ✅ | Removed dead `build_schema_enforcement_prompt` + `_SCHEMA_INSTRUCTION`. 69→55 LOC. |
| 38 | `llm/context_window.py` | 111 | ✅ | All symbols live. `count_tokens` could get `_` prefix later. |
| 39 | `llm/conversation.py` | 76 | ✅ | All symbols live. 2 internal constants could get `_` prefix later. |
| 40 | `llm/prompts/dialogue_formatter.py` | 127 | ✅ | All symbols live. 3 internal constants could get `_` prefix later. |
| 41 | `tools/field_names.py` | 15 | ✅ | Removed 3 dead fields (SANDBOXED, ERROR_TYPE, TRACEBACK). 21→15 LOC. |
| 42 | `tools/constants.py` | 96 | ✅ | Removed 6 dead constants (2 search query limits, 4 schema field names). 110→96 LOC. |
| 43 | `tools/tool_cache_constants.py` | 5 | ✅ | All symbols live. No changes. |
| 44 | `tools/workflow_rate_limiter_constants.py` | 5 | ✅ | All symbols live. No changes. |
| 45 | `tools/http_client_constants.py` | 16 | ✅ | All symbols live. No changes. |
| 46 | `tools/git_tool_constants.py` | 34 | ✅ | Removed dead `GIT_MAX_LOG_ENTRIES`. |
| 47 | `tools/_search_helpers.py` | 28 | ✅ | Removed dead `format_results_for_llm` + `DEFAULT_FORMAT_MAX_RESULTS`. 59→28 LOC. |

**Layer 0 total: 47 files, ~3,978 LOC**

---

## Layer 1 — One Internal Dependency

These files only import from Layer 0 files.

### 1.1 — shared/utils/ (builds on Layer 0)

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 48 | `shared/utils/path_safety/exceptions.py` | 14 | exceptions | ✅ | All symbols live (6 consumers). No changes. |
| 49 | `shared/utils/logging.py` | 547 | shared/constants | ✅ | Removed `setup_logging`, `LogContext`, `log_function_call`, 4 `_configure_*` helpers, dead imports. 804→547 LOC. |
| 50 | `shared/utils/secrets.py` | 277 | shared/constants | ✅ | Removed `mask_url_password`, `ObfuscatedCredential`, `Fernet` import. 409→277 LOC. |

### 1.2 — events/

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 51 | `events/models.py` | 43 | datetime_utils | ✅ | Removed dead `_new_id` + `import uuid`. 49→43 LOC. |
| 52 | `events/_schemas.py` | 34 | events/constants | ✅ | All 3 classes live (2 consumers each). No changes. |

### 1.3 — memory/

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 53 | `memory/_schemas.py` | 54 | memory/constants | ✅ | All 3 classes well-used (11 consumers). No changes. |

### 1.4 — storage/

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 54 | `storage/database/datetime_utils.py` | 25 | shared datetime_utils | ✅ | Re-export shim, 39 consumers. No changes. |
| 55 | `storage/database/validators.py` | 54 | shared/constants | ✅ | Removed dead `validate_optional_json_size`. 64→54 LOC. |
| 56 | `storage/database/engine.py` | 115 | shared/constants | ✅ | `create_test_engine` 0 prod/4 test consumers — kept. No changes. |

### 1.5 — llm/

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 57 | `llm/constants.py` | 81 | shared/constants | ✅ | Removed 3 dead constants (DEFAULT_LLM_TIMEOUT_SECONDS, DEFAULT_RETRY_DELAY_SECONDS, CPU_OFFSET). 84→81 LOC. |
| 58 | `llm/cache/constants.py` | 13 | shared/constants | ✅ | Removed 10 dead constants (GOOD/POOR_HIT_RATIO, 7 FIELD_*, DISPLAY_ELLIPSIS). 35→13 LOC. |
| 59 | `llm/response_parser.py` | 207 | llm/constants | ✅ | All 8 public functions live (3+ consumers each). No changes. |
| 60 | `llm/_schemas.py` | 115 | llm/tool_keys | ✅ | Both functions live. No changes. |
| 61 | `llm/prompts/cache.py` | 113 | llm/cache/constants | ✅ | `TemplateCacheManager` live (1 consumer). No changes. |
| 62 | `llm/prompts/validation.py` | 107 | shared/constants, exceptions | ✅ | All symbols live (6+ consumers). No changes. |

### 1.6 — tools/

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 63 | `tools/workflow_rate_limiter.py` | 118 | exceptions, constants | ⚠️ | `WorkflowRateLimiter` never instantiated in production (0 consumers). Wiring exists but no producer. Kept for now. |
| 64 | `tools/_executor_config.py` | 45 | shared/constants | ✅ | `ToolExecutorConfig` live (1 consumer). No changes. |

**Layer 1 total: 17 files, ~1,572 LOC (was ~2,392)**

---

## Layer 2 — Two Internal Dependencies

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 65 | `shared/utils/error_handling.py` | ~~361~~ | durations, retries | ✅ | DELETED — 0 production consumers |
| 66 | `shared/utils/path_safety/symlink_validator.py` | 144 | path exceptions | ✅ | All symbols live. No changes. |
| 67 | `shared/utils/path_safety/temp_directory.py` | 137 | constants, path exceptions | ✅ | All symbols live. No changes. |
| 68 | `shared/utils/path_safety/path_rules.py` | 175 | constants, platform_detector, path exceptions | ✅ | All symbols live. No changes. |
| 69 | `memory/protocols.py` | 50 | _schemas, constants | ✅ | All symbols live. No changes. |
| 70 | `memory/formatter.py` | 50 | _schemas, constants | ✅ | All symbols live. No changes. |
| 71 | `memory/registry.py` | 92 | constants, adapters | ✅ | All symbols live. No changes. |
| 72 | `memory/cross_pollination.py` | 115 | _schemas | ✅ | All symbols live. No changes. |
| 73 | `storage/database/models_registry.py` | 35 | datetime_utils | ✅ | All symbols live. No changes. |
| 74 | `storage/database/models_tenancy.py` | 302 | datetime_utils | ✅ | Removed 4 dead constants (VALID_ROLES, API_KEY_PREFIX, API_KEY_PREFIX_DISPLAY_LEN, CONFIG_TYPE_CHECK). Renamed ROLE_CHECK → _ROLE_CHECK. 316→302 LOC. |
| 75 | `storage/database/models_evaluation.py` | 59 | db constants, datetime_utils | ✅ | All symbols live. No changes. |
| 76 | `llm/_tracking.py` | 85 | llm/constants, exceptions | ✅ | Removed dead `track_llm_iteration` function. 172→85 LOC. |
| 77 | `llm/_retry.py` | 132 | retries, exceptions | ✅ | All symbols live. No changes. |
| 78 | `llm/_prompt.py` | 117 | response_parser, tool_keys | ✅ | All symbols live. No changes. |
| 79 | `llm/prompts/engine.py` | 236 | cache constants, cache, validation | ✅ | Removed 3 dead methods (render_with_metadata, render_file_with_metadata, get_cache_stats) + dead hash util. 280→236 LOC. |
| 80 | `tools/base.py` | 452 | limits, exceptions | ✅ | Removed ToolParameter, get_config_schema, get_typed_config, ParameterSanitizer (~333 LOC). 822→452 LOC. |

**Layer 2 total: 16 files, ~2,181 LOC (was ~3,057)**

---

## Layer 3 — Three Internal Dependencies

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 81 | `shared/core/circuit_breaker.py` | 567 | retries, cb_helpers, constants, exceptions | ✅ | Removed 2 dead backward-compat aliases (CircuitBreakerState, CircuitBreakerOpen) — sole consumer was deleted safety/circuit_breaker.py. 575→567 LOC. |
| 82 | `shared/utils/path_safety/validator.py` | 284 | all path_safety sub-modules | ✅ | All symbols live. No changes. |
| 83 | `memory/adapters/in_memory.py` | 94 | _schemas, constants | ✅ | All symbols live. No changes. |
| 84 | `memory/adapters/pg_adapter.py` | 399 | _schemas, constants | ✅ | All symbols live. No changes. |
| 85 | `memory/adapters/mem0_adapter.py` | 184 | _schemas, constants | ✅ | All symbols live. No changes. |
| 86 | `memory/adapters/knowledge_graph_adapter.py` | 120 | _schemas, constants | ✅ | All symbols live. No changes. |
| 87 | `storage/database/manager.py` | 233 | engine | ✅ | All symbols live. No changes. |
| 88 | `storage/schemas/agent_config.py` | 533 | shared/constants (5 files) | ✅ | All symbols live. No changes. |
| 89 | `llm/cost_estimator.py` | 51 | constants, pricing | ✅ | All symbols live. No changes. |
| 90 | `llm/cache/llm_cache.py` | 697 | cache/constants, shared/constants, logging | ✅ | All symbols live. No changes. |
| 91 | `tools/tool_cache.py` | 174 | base, cache_constants | ✅ | All symbols live. No changes. |
| 92 | `tools/calculator.py` | 289 | base, constants | ✅ | All symbols live. No changes. |
| 93 | `tools/json_parser.py` | 199 | base | ✅ | All symbols live. No changes. |
| 94 | `tools/http_client.py` | 185 | base, http_constants | ✅ | All symbols live. No changes. |
| 95 | `tools/git_tool.py` | 173 | base, git_constants | ✅ | All symbols live. No changes. |
| 96 | `tools/_bash_helpers.py` | 522 | base, constants, field_names | ✅ | All symbols live. No changes. |
| 97 | `tools/_registry_helpers.py` | 505 | exceptions, base | ✅ | Removed dead `ToolRegistryReportingMixin` and `ToolRegistryValidationMixin` — thin wrappers never inherited. 550→505 LOC. |

**Layer 3 total: 17 files, ~5,209 LOC (was ~5,262)**

---

## Layer 4 — Four+ Internal Dependencies

### 4.1 — Dead modules (entire files deleted)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 98 | `safety/circuit_breaker.py` | ~~319~~ | ✅ | DELETED — `SafetyGate`, `SafetyGateBlocked`, `CircuitBreakerManager` had 0 production callers (only re-exported from `safety/__init__.py`) |
| 99 | `safety/composition.py` | ~~401~~ | ✅ | DELETED — `PolicyComposer`, `CompositeValidationResult` had 0 production callers (only consumer was dead SafetyGate) |
| 100 | `workflow/db_config_loader.py` | ~~109~~ | ✅ | DELETED — `DBConfigLoader` never instantiated in production |

### 4.2 — Dead code in live modules

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 101 | `safety/__init__.py` | — | ✅ | Removed 5 symbols from `_LAZY_IMPORTS` + `__all__`: PolicyComposer, CompositeValidationResult, SafetyGate, SafetyGateBlocked, CircuitBreakerManager |
| 102 | `observability/trace_export.py` | — | ✅ | Removed dead `flatten_for_waterfall` function + unused `from datetime import datetime`. |
| 103 | `observability/migrations.py` | — | ✅ | Removed dead `MigrationSecurityError` class + `check_schema_version` function + 3 unused imports |
| 104 | `tools/registry.py` | — | ✅ | Removed dead `get_global_registry`, `clear_global_cache`, `_GLOBAL_REGISTRY` + unused `Optional` import |
| 105 | `stage/_schemas.py` | — | ✅ | Removed 3 dead classes: `AgentMetrics`, `AggregateMetrics`, `MultiAgentStageState` (~37 LOC) |

### 4.3 — Test files cleaned up

| File | Action | Notes |
|------|--------|-------|
| `tests/test_safety/test_composer.py` | DELETED | All tests for dead PolicyComposer |
| `tests/test_safety/test_policy_composition.py` | DELETED | All tests for dead composition code |
| `tests/test_safety/test_sync_async_33b.py` | DELETED | All tests for dead composition code |
| `tests/test_safety/test_m4_integration.py` | DELETED | All tests used dead SafetyGate/CircuitBreakerManager/PolicyComposer |
| `tests/test_workflow/test_db_config_loader.py` | DELETED | All tests for dead DBConfigLoader |
| `tests/test_safety/test_circuit_breaker.py` | EDITED | Removed TestSafetyGate, TestCircuitBreakerManager, 2 integration tests using dead code. Kept alive tests for shared/core/circuit_breaker. |
| `tests/test_observability/test_trace_export_coverage.py` | EDITED | Removed TestFlattenForWaterfall class |
| `tests/test_observability/test_migrations.py` | EDITED | Removed TestCheckSchemaVersion, TestMigrationEdgeCases, dead imports/fixtures. Added test_migration_security_error_removed. |
| `tests/test_tools/test_registry.py` | EDITED | Removed clear_global_cache calls (use_cache=False instead), removed test_global_registry_singleton + test_clear_global_cache |
| `tests/test_stage/test_stage_schemas.py` | EDITED | Removed TestAgentMetrics, TestAggregateMetrics, TestMultiAgentStageState |
| `tests/test_thread_safety_singletons.py` | EDITED | Removed TestGlobalRegistryThreadSafety |

**Layer 4 total: 8 files reviewed, ~829 LOC deleted from production, 5 test files deleted, 6 test files edited**

---

## Layer 5 — Higher Dependencies

### 5.1 — Dead modules (entire files deleted)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 106 | `observability/otel_setup.py` | ~~192~~ | ✅ | DELETED — `is_otel_configured`, `init_otel`, `create_otel_backend` had 0 production callers |

### 5.2 — Dead code in live modules (observability batch)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 107 | `observability/formatters.py` | 160 | ✅ | Removed 3 dead functions (`format_percentage`, `truncate_text`, `format_bytes`), 1 dead constant (`DEFAULT_TRUNCATE_MAX_LENGTH`), 1 unused import. ~238→160 LOC. |
| 108 | `observability/error_fingerprinting.py` | 216 | ✅ | Removed dead `MAX_RECENT_IDS` constant, `ErrorFingerprintRecord` dataclass, 3 unused imports. ~241→216 LOC. |
| 109 | `observability/dialogue_metrics.py` | — | ✅ | Removed dead `emit_round_metrics` function (~25 lines). 0 external callers. |

### 5.3 — Dead code in live modules (safety/llm/events batch)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 110 | `safety/exceptions.py` | — | ✅ | Removed dead `EmergencyStopViolation` class (~22 lines). 0 external imports. |
| 111 | `safety/interfaces.py` | — | ✅ | Removed dead `ActionDescriptor` TypedDict (~43 lines), removed `TypedDict` import, fixed stale docstring. |
| 112 | `safety/policy_registry.py` | 158 | ✅ | Removed 9 dead public methods + 2 dead private helpers. Kept: `__init__`, `register_policy`, `list_policies`, `get_policies_for_action`, `clear`, `policy_count`, `__repr__`. ~372→158 LOC. |
| 113 | `llm/pricing.py` | — | ✅ | Removed dead `PricingConfigNotFoundError` class, 4 dead methods: `reload_pricing`, `get_pricing_info`, `list_supported_models`, `health_check`. |
| 114 | `events/subscription_registry.py` | 68 | ✅ | Removed 4 dead methods (`unregister`, `get_for_event`, `load_active`, `get_by_id`), removed unused `select` import. ~156→68 LOC. |

### 5.4 — Test files cleaned up (Layer 5)

| File | Action | Notes |
|------|--------|-------|
| `tests/test_observability/test_otel_setup.py` | DELETED | All tests for dead otel_setup |
| `tests/test_observability/test_otel_setup_coverage.py` | DELETED | All tests for dead otel_setup |
| `tests/test_observability/test_otel_httpx_default.py` | DELETED | All tests for dead otel_setup |
| `tests/test_observability/test_formatters.py` | EDITED | Removed TestFormatPercentage, TestTruncateText, TestFormatBytes. ~323→196 LOC. |
| `tests/test_observability/test_dialogue_metrics.py` | EDITED | Removed TestEmitRoundMetrics class |
| `tests/test_observability/test_console.py` | EDITED | Removed dead formatter imports and tests |
| `tests/test_safety/test_policy_registry.py` | EDITED | Removed tests for 9 dead methods. ~547→282 LOC. |
| `tests/test_safety/test_factory.py` | EDITED | Replaced `is_registered()` → `in list_policies()`, `get_policy()` → `in list_policies()` |
| `tests/test_llm/test_pricing.py` | EDITED | Removed TestGetPricingInfo, TestListSupportedModels, TestHealthCheck. ~268→186 LOC. |
| `tests/test_llm/test_pricing_coverage.py` | EDITED | Removed tests for dead methods. ~124→89 LOC. |
| `tests/test_agent/test_pricing.py` | EDITED | Removed tests for dead methods, fixed `list_supported_models()` → `manager.pricing` |
| `tests/test_events/test_subscription_registry.py` | EDITED | Removed tests for dead methods. ~140→65 LOC. |
| `tests/test_events/test_event_bus.py` | EDITED | Replaced `get_by_id()` assertions with subscription ID validation |

### 5.5 — Dead code in live modules (tools/workflow/safety batch)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 115 | `tools/executor.py` | — | ✅ | Removed 4 dead methods: `execute_batch`, `validate_tool_call`, `get_tool_info`, `is_shutdown`. Removed 3 unused imports. |
| 116 | `tools/registry.py` | — | ✅ | Removed 4 dead methods/attrs: `register_multiple`, `get_tool_schema`, `get_all_tool_schemas`, `list_all` (deprecated monkey-patch). |
| 117 | `workflow/runtime.py` | — | ✅ | Removed dead `load_input_file` method and `check_required_inputs` staticmethod re-export. Removed 3 unused imports. |
| 118 | `workflow/planning.py` | 27 | ✅ | Removed dead `generate_workflow_plan`, `build_planning_prompt`, `_PLAN_PROMPT_TEMPLATE`. Kept alive `PlanningConfig`. ~103→27 LOC. |
| 119 | `safety/action_policy_engine.py` | — | ✅ | Removed dead `get_metrics`, `reset_metrics` methods. Removed dead `EnforcementResult.get_violations_by_severity`. |
| 120 | `safety/interfaces.py` | — | ✅ | Removed dead `ValidationResult.get_violations_by_severity` method. |

### 5.6 — Test files cleaned up (tools/workflow/safety batch)

| File | Action | Notes |
|------|--------|-------|
| `tests/test_tools/test_executor.py` | EDITED | Removed 6 tests for dead executor methods |
| `tests/test_tools/test_executor_helpers.py` | EDITED | Removed TestValidateToolCall, TestExecuteBatch classes |
| `tests/test_tools/test_registry.py` | EDITED | Removed tests for dead registry methods |
| `tests/test_tools/test_coverage_boost.py` | EDITED | Removed tests for dead executor/registry methods |
| `tests/test_tools/test_tool_config_loading.py` | EDITED | Removed get_tool_schema assertions |
| `tests/test_executor_cleanup.py` | EDITED | Removed is_shutdown tests, replaced with internal state checks |
| `tests/integration/test_agent_tool_integration.py` | EDITED | Replaced register_multiple with loop |
| `tests/test_workflow/test_runtime.py` | EDITED | Removed TestLoadInputFile, TestCheckRequiredInputs classes |
| `tests/test_workflow/test_planning.py` | EDITED | Removed TestBuildPlanningPrompt, TestGenerateWorkflowPlan. Kept TestPlanningConfig. |
| `tests/test_safety/test_action_policy_engine.py` | EDITED | Removed TestMetrics class, get_violations_by_severity test, metrics assertions |
| `tests/test_safety/test_interfaces.py` | EDITED | Removed get_violations_by_severity test |

### 5.7 — Dead code in live modules (auth/observability batch)

| # | File | LOC | Status | Notes |
|---|------|-----|--------|-------|
| 121 | `auth/config_seed.py` | ~~97~~ | ✅ | DELETED — entire module dead. `seed_configs`, `_seed_directory`, `_read_yaml_file` had 0 production callers. |
| 122 | `auth/tenant_scope.py` | ~~80~~ | ✅ | DELETED — entire module dead. `scoped_query`, `get_scoped`, `count_scoped` had 0 production callers. |
| 123 | `auth/constants.py` | 61 | ✅ | Removed 17 dead constants (4 session, 5 rate-limit, 4 token, 3 OAuth state, 1 FIELD_REFRESH_TOKEN) + unused duration imports. ~107→61 LOC. |
| 124 | `auth/api_key_auth.py` | — | ✅ | Removed dead `SHA256_HEX_LEN` constant. |
| 125 | `auth/ws_tickets.py` | — | ✅ | Removed dead `cleanup_expired()` function (~8 lines). 0 production callers. |
| 126 | `auth/session.py` | — | ✅ | Removed dead `UserStore.get_user_by_email()` method (~14 lines). 0 production callers. |
| 127 | `auth/oauth/rate_limiter.py` | — | ✅ | Removed 2 dead methods: `SlidingWindowRateLimiter.get_remaining()`, `SlidingWindowRateLimiter.cleanup()`. |
| 128 | `auth/oauth/callback_validator.py` | — | ✅ | Removed 3 dead methods: `get_allowed_urls()`, `add_allowed_url()`, `remove_allowed_url()`. |
| 129 | `auth/oauth/token_store.py` | — | ✅ | Removed 4 dead methods: `rotate_key()`, `rotate_key_from_keyring()`, `get_audit_log()`, `clear_all_tokens()`. Removed unused `re_encrypt_tokens` import. |
| 130 | `auth/oauth/service.py` | — | ✅ | Removed 4 dead methods: `_generate_state()`, `_generate_code_verifier()`, `_generate_code_challenge()`, `cleanup_expired_states()`. Removed 3 unused imports. |
| 131 | `observability/performance.py` | — | ✅ | Removed 6 dead methods from `PerformanceTracker`: `get_metrics()`, `get_all_metrics()`, `get_slow_operations()`, `get_summary()`, `reset()`, `set_slow_threshold()`. |
| 132 | `observability/alerting.py` | — | ✅ | Removed 9 dead methods from `AlertManager`: `remove_rule()`, `enable_rule()`, `disable_rule()`, `register_webhook_handler()`, `register_email_handler()`, `register_halt_callback()`, `get_recent_alerts()`, `clear_history()`, `get_persisted_alerts()`. Removed dead `_query_persisted_alerts()` function + unused imports. |

### 5.8 — Test files cleaned up (auth/observability batch)

| File | Action | Notes |
|------|--------|-------|
| `tests/test_auth/test_config_seed.py` | DELETED | All tests for dead config_seed module |
| `tests/test_auth/test_tenant_scope.py` | DELETED | All tests for dead tenant_scope module |
| `tests/test_auth/test_constants.py` | DELETED | All 17 tested constants removed |
| `tests/test_auth/test_ws_tickets.py` | EDITED | Removed `cleanup_expired` import and 4 tests |
| `tests/test_auth/test_session.py` | EDITED | Removed 3 `get_user_by_email` tests |
| `tests/test_auth/test_session_thread_safety.py` | EDITED | Replaced `get_user_by_email` → `get_user_by_id` |
| `tests/test_auth/test_rate_limiter.py` | EDITED | Removed `test_get_remaining`, `test_cleanup` |
| `tests/test_auth/test_callback_validator.py` | EDITED | Removed 3 tests for removed methods |
| `tests/test_auth/oauth/test_callback_validator.py` | EDITED | Removed `TestValidatorHelperMethods` class |
| `tests/test_auth/test_token_store.py` | EDITED | Removed 7 tests for dead methods |
| `tests/test_auth/oauth/test_token_store.py` | EDITED | Removed `TestKeyRotation` (6), `TestAuditLogging` (5), `clear_all_tokens` tests |
| `tests/test_auth/test_oauth_token_store.py` | EDITED | Removed `TestKeyRotation`, `TestClearAllTokens`, `test_get_audit_log`, `test_concurrent_key_rotation` |
| `tests/test_auth/test_oauth/test_service.py` | EDITED | Removed PKCE wrapper, `cleanup_expired_states` tests |
| `tests/test_auth/test_oauth_service.py` | EDITED | Removed `test_cleanup_expired_states` |
| `tests/test_auth/test_oauth_integration.py` | EDITED | Removed 2 `cleanup_expired_states` tests |
| `tests/test_auth/test_oauth/test_rate_limiter.py` | EDITED | Removed 5 tests for `get_remaining`, `cleanup` |
| `tests/test_observability/test_performance.py` | EDITED | Removed 7 tests for dead methods, fixed 6 tests to use `tracker.metrics[op].get_percentiles()` |
| `tests/test_observability/test_performance_cleanup.py` | EDITED | Removed `test_reset_clears_all_metrics` |
| `tests/test_observability/test_alerting.py` | EDITED | Removed 5 tests, fixed 3 to use direct dict assignment instead of removed register methods |
| `tests/test_observability/test_alerting_gaps.py` | EDITED | Removed 3 tests, fixed 1 to use `_halt_callback` directly |
| `tests/test_observability/test_alerting_comprehensive.py` | EDITED | Removed 7 tests, fixed 3 to use direct dict assignment |

**Layer 5 total: 27 production files edited/deleted, ~2200+ LOC removed, 6 test files deleted, 42 test files edited**

---

## Remaining (Not Yet Reviewed)

- `llm/providers/` (base → anthropic/openai/ollama/vllm → factory)
- `llm/service.py` (11 internal deps — the LLM orchestrator)
- `tools/executor.py`, built-in tools
- `storage/database/models.py` (master schema)
- `memory/service.py` (memory orchestrator)
- `events/event_bus.py` (event bus orchestrator)
- All of: agent, stage, safety, observability (remaining), auth, workflow, interfaces

---

## Issues Found

| # | Module | Severity | Description | Fixed? |
|---|--------|----------|-------------|--------|
| 1 | shared/constants/sizes.py | Low | 13 unused constants (BUFFER_SIZE_*, 6 SIZE_*, UUID_HEX_MEDIUM_LENGTH) | Yes |
| 2 | shared/constants/timeouts.py | Medium | Entire file duplicated by durations.py; deleted file, fixed 1 import | Yes |
| 3 | memory/constants.py | Low | Local duplicate of SECONDS_PER_DAY; removed, import from durations.py | Yes |
| 4 | goals/constants.py | Low | Local duplicate of SECONDS_PER_HOUR; removed, import from durations.py | Yes |
| 5 | learning/background.py | Low | Local duplicate of SECONDS_PER_HOUR; removed, import from durations.py | Yes |
| 6 | shared/constants/durations.py | Low | 34 unused constants (DURATION_*, TIMEOUT_*, TTL_*, POLL_*, SLEEP_*, etc.) | Yes |
| 7 | shared/constants/retries.py | Low | 10 unused constants (EXTENDED_MAX_RETRIES, *_BACKOFF_*, etc.) | Yes |
| 8 | llm/constants.py | Medium | `DEFAULT_TIMEOUT_SECONDS` name collision — renamed to `DEFAULT_LLM_TIMEOUT_SECONDS` | Yes |
| 9 | optimization/engine_constants.py | Medium | `DEFAULT_TIMEOUT_SECONDS` name collision — renamed to `DEFAULT_OPTIMIZATION_TIMEOUT_SECONDS` | Yes |
| 10 | llm/providers/base.py | Low | Dead alias `DEFAULT_TIMEOUT_SECONDS = TIMEOUT_HTTP_DEFAULT` — removed | Yes |
| 11 | tools/tool_cache_constants.py | Medium | `DEFAULT_CACHE_TTL_SECONDS` name collision (300 vs 3600) — renamed to `DEFAULT_TOOL_CACHE_TTL_SECONDS` | Yes |
| 12 | shared/constants/limits.py | Low | 20 unused constants (batch/page/pool/percent/string/etc.) | Yes |
| 13 | shared/constants/probabilities.py | Low | 12 unused constants (PROB_MEDIUM_LOW, CONFIDENCE_*, FRACTION_*, TOLERANCE_*) | Yes |
| 14 | llm/providers/base.py | Info | `DEFAULT_TEMPERATURE`, `DEFAULT_TOP_P` duplicated locally (same values) — flagged, not changed | — |
| 15 | shared/utils/exceptions.py | Low | `wrap_exception` and `get_error_info` — 0 external consumers, only tested in own test file | Yes |
| 16 | shared/utils/exceptions.py | Low | `SafetyError` — 0 production consumers, only 1 test used it | Yes |
| 17 | shared/utils/exceptions.py | Low | `FrameworkValidationError` — 0 production consumers, only 2 tests used it | Yes |
| 18 | shared/utils/exceptions.py | Low | 11 orphaned ErrorCode members never referenced outside the class | Yes |
| 19 | shared/utils/exceptions.py | Info | No trace_id/request_id in ExecutionContext or error hierarchy — gap for observability | — |
| 20 | shared/utils/config_helpers.py | Low | 5 functions with 0 production consumers (merge_configs, extract_required_fields, set_nested_value, validate_config_structure, resolve_config_path) | Yes |
| 21 | shared/utils/config_migrations.py | Medium | Entire module (294 LOC) — 0 production consumers, speculative scaffolding | Yes |
| 22 | shared/utils/constants.py | Low | 2 remaining constants (MAX_PATH_LENGTH, MAX_COMPONENT_LENGTH) moved to shared/constants/limits.py; file deleted | Yes |
| 23 | shared/core/constants.py | Low | 7 single-consumer constants inlined to circuit_breaker.py, 6 dead constants removed; file deleted | Yes |
| 24 | shared/core/protocols.py | Low | 4 dead Protocols (Registry[T], ToolRegistryProtocol, PolicyRegistryProtocol, StrategyRegistryProtocol) — 0 production consumers | Yes |
| 25 | shared/core/stream_events.py | Low | 4 dead symbols (LLM_TOKEN, LLM_DONE, STATUS, from_llm_chunk) — 0 production consumers | Yes |
| 26 | shared/core/_circuit_breaker_helpers.py | Low | 3 public-named functions only used internally — renamed to `_` prefix | Yes |
| 27 | config/ package | Medium | Entire package (4 files, ~210 LOC) dead in production — zero callers; production reads os.environ directly | Yes |
| 28 | events/constants.py | Low | 9 dead constants (8 event types + MAX_PAYLOAD_SIZE_BYTES); otel_backend.py uses raw strings instead of importing | Yes |
| 29 | memory/constants.py | Low | 3 dead M9 constants (duplicated in implementation files); SECONDS_PER_DAY was local duplicate of shared constant | Yes |
| 30 | memory/agent_performance.py | Medium | Entire module (92 LOC) dead — 0 production consumers; speculative M9 scaffolding | Yes |
| 31 | storage/schemas/constants.py | Low | Entire file (11 LOC) dead — 0 consumers; callers use raw string literals inline | Yes |
| 32 | storage/database/constants.py | Low | 4 dead FIELD_* constants never imported by models.py | Yes |
| 33 | llm/output_validation.py | Low | Dead `build_schema_enforcement_prompt` — schema enforcement path never wired in | Yes |
| 34 | tools/field_names.py | Low | 3 dead ToolResultFields (SANDBOXED, ERROR_TYPE, TRACEBACK) — parallel `StateKeys` enum used instead | Yes |
| 35 | tools/constants.py | Low | 6 dead constants (2 search query limits, 4 schema field names for never-built abstraction) | Yes |
| 36 | tools/_search_helpers.py | Low | Dead `format_results_for_llm` — never wired into search tool output path | Yes |
| 37 | shared/utils/logging.py | Medium | Dead `setup_logging`, `LogContext`, `log_function_call`, 4 `_configure_*` helpers — 0 production consumers | Yes |
| 38 | shared/utils/secrets.py | Medium | Dead `mask_url_password`, `ObfuscatedCredential` — 0 production consumers; `Fernet` import only used by dead class | Yes |
| 39 | events/models.py | Low | Dead `_new_id()` function — never called | Yes |
| 40 | storage/database/validators.py | Low | Dead `validate_optional_json_size` — 0 production consumers | Yes |
| 41 | llm/constants.py | Low | 3 dead constants (DEFAULT_LLM_TIMEOUT_SECONDS, DEFAULT_RETRY_DELAY_SECONDS, CPU_OFFSET) | Yes |
| 42 | llm/cache/constants.py | Low | 10 dead constants (display/field/ratio constants) — only 2 of 12 live | Yes |
| 43 | tools/workflow_rate_limiter.py | Medium | `WorkflowRateLimiter` never instantiated — executor wiring exists but no producer creates it | — |
| 44 | shared/core/circuit_breaker.py | Low | Dead backward-compat aliases `CircuitBreakerState`/`CircuitBreakerOpen` — sole consumer was deleted `safety/circuit_breaker.py` | Yes |
| 45 | tools/_registry_helpers.py | Low | Dead `ToolRegistryReportingMixin` + `ToolRegistryValidationMixin` — thin wrappers around standalone functions, never inherited | Yes |
| 46 | safety/circuit_breaker.py | Medium | Entire module (319 LOC) dead — `SafetyGate`, `SafetyGateBlocked`, `CircuitBreakerManager` had 0 production callers | Yes |
| 47 | safety/composition.py | Medium | Entire module (401 LOC) dead — `PolicyComposer`, `CompositeValidationResult` had 0 production callers | Yes |
| 48 | workflow/db_config_loader.py | Medium | Entire module (109 LOC) dead — `DBConfigLoader` never instantiated | Yes |
| 49 | safety/__init__.py | Low | 5 lazy-import entries for dead symbols (PolicyComposer, CompositeValidationResult, SafetyGate, SafetyGateBlocked, CircuitBreakerManager) | Yes |
| 50 | observability/trace_export.py | Low | Dead `flatten_for_waterfall` function (0 callers) + unused `datetime` import | Yes |
| 51 | observability/migrations.py | Low | Dead `MigrationSecurityError` class + `check_schema_version` function + 3 unused imports | Yes |
| 52 | tools/registry.py | Low | Dead `get_global_registry`, `clear_global_cache`, `_GLOBAL_REGISTRY` — test-only code in production module | Yes |
| 53 | stage/_schemas.py | Low | Dead `AgentMetrics`, `AggregateMetrics`, `MultiAgentStageState` classes — 0 external importers | Yes |
| 54 | observability/otel_setup.py | Medium | Entire module (192 LOC) dead — 0 production consumers | Yes |
| 55 | observability/formatters.py | Low | 3 dead functions (`format_percentage`, `truncate_text`, `format_bytes`) + 1 dead constant — 0 external imports | Yes |
| 56 | observability/error_fingerprinting.py | Low | Dead `MAX_RECENT_IDS` constant + `ErrorFingerprintRecord` dataclass — 0 external imports | Yes |
| 57 | observability/dialogue_metrics.py | Low | Dead `emit_round_metrics` function — 0 external callers | Yes |
| 58 | safety/exceptions.py | Low | Dead `EmergencyStopViolation` class — 0 external imports | Yes |
| 59 | safety/interfaces.py | Low | Dead `ActionDescriptor` TypedDict — 0 external imports | Yes |
| 60 | safety/policy_registry.py | Medium | 9 dead public methods + 2 dead private helpers — ~214 LOC removed | Yes |
| 61 | llm/pricing.py | Low | Dead `PricingConfigNotFoundError` class + 4 dead methods (`reload_pricing`, `get_pricing_info`, `list_supported_models`, `health_check`) | Yes |
| 62 | events/subscription_registry.py | Low | 4 dead methods (`unregister`, `get_for_event`, `load_active`, `get_by_id`) — ~88 LOC removed | Yes |
| 63 | tools/executor.py | Low | 4 dead methods (`execute_batch`, `validate_tool_call`, `get_tool_info`, `is_shutdown`) — 0 external callers | Yes |
| 64 | tools/registry.py | Low | 4 dead methods/attrs (`register_multiple`, `get_tool_schema`, `get_all_tool_schemas`, `list_all`) — 0 external callers | Yes |
| 65 | workflow/runtime.py | Low | Dead `load_input_file` method + `check_required_inputs` static re-export — 0 external callers | Yes |
| 66 | workflow/planning.py | Medium | Dead `generate_workflow_plan` + `build_planning_prompt` — 0 callers, ~76 LOC | Yes |
| 67 | safety/action_policy_engine.py | Low | Dead `get_metrics`, `reset_metrics`, `get_violations_by_severity` — 0 external callers | Yes |
| 68 | auth/config_seed.py | Medium | Entire module dead (97 LOC) — `seed_configs` had 0 production callers | Yes |
| 69 | auth/tenant_scope.py | Medium | Entire module dead (80 LOC) — `scoped_query`, `get_scoped`, `count_scoped` had 0 production callers | Yes |
| 70 | auth/constants.py | Low | 17 dead constants (session/rate-limit/token/OAuth state config) — 0 external imports | Yes |
| 71 | auth/oauth/token_store.py | Low | 4 dead methods (`rotate_key`, `rotate_key_from_keyring`, `get_audit_log`, `clear_all_tokens`) — 0 external callers | Yes |
| 72 | auth/oauth/service.py | Low | 4 dead methods (PKCE wrappers + `cleanup_expired_states`) — 0 external callers | Yes |
| 73 | auth/oauth/callback_validator.py | Low | 3 dead methods (`get_allowed_urls`, `add_allowed_url`, `remove_allowed_url`) — 0 external callers | Yes |
| 74 | auth/oauth/rate_limiter.py | Low | 2 dead methods (`get_remaining`, `cleanup`) — 0 external callers | Yes |
| 75 | auth/session.py | Low | Dead `UserStore.get_user_by_email()` — 0 external callers | Yes |
| 76 | auth/ws_tickets.py | Low | Dead `cleanup_expired()` — 0 external callers | Yes |
| 77 | auth/api_key_auth.py | Low | Dead `SHA256_HEX_LEN` constant — 0 external uses | Yes |
| 78 | observability/performance.py | Low | 6 dead methods on `PerformanceTracker` (`get_metrics`, `get_all_metrics`, `get_slow_operations`, `get_summary`, `reset`, `set_slow_threshold`) — 0 external callers | Yes |
| 79 | observability/alerting.py | Medium | 9 dead methods on `AlertManager` + dead `_query_persisted_alerts` function — 0 external callers | Yes |

---

## Session Log

### Session 1 — 2026-02-28
- Created tracking document
- Mapped all 25 modules at high level
- Broke down into file-level dependency layers (0-3 fully mapped, 97 files)
- Next: Start reviewing Layer 0, file #1 — `shared/constants/sizes.py`
