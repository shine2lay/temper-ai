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
| 65 | `shared/utils/error_handling.py` | 361 | durations, retries | ⬜ | Retry/backoff decorators |
| 66 | `shared/utils/path_safety/symlink_validator.py` | 144 | path exceptions | ⬜ | TOCTOU-safe symlink checks |
| 67 | `shared/utils/path_safety/temp_directory.py` | 137 | constants, path exceptions | ⬜ | Secure temp dir management |
| 68 | `shared/utils/path_safety/path_rules.py` | 175 | constants, platform_detector, path exceptions | ⬜ | Path validation rules |
| 69 | `memory/protocols.py` | 50 | _schemas, constants | ⬜ | MemoryStoreProtocol |
| 70 | `memory/formatter.py` | 50 | _schemas, constants | ⬜ | Memory → markdown formatter |
| 71 | `memory/registry.py` | 92 | constants, adapters | ⬜ | Provider registry singleton |
| 72 | `memory/cross_pollination.py` | 115 | _schemas | ⬜ | Cross-agent knowledge sharing |
| 73 | `storage/database/models_registry.py` | 35 | datetime_utils | ⬜ | AgentRegistryDB table |
| 74 | `storage/database/models_tenancy.py` | 316 | datetime_utils | ⬜ | Multi-tenant RBAC models |
| 75 | `storage/database/models_evaluation.py` | 59 | db constants, datetime_utils | ⬜ | Evaluation result model |
| 76 | `llm/_tracking.py` | 172 | llm/constants, exceptions | ⬜ | LLM call observer tracking |
| 77 | `llm/_retry.py` | 132 | retries, exceptions | ⬜ | Retry with exp backoff |
| 78 | `llm/_prompt.py` | 117 | response_parser, tool_keys | ⬜ | Prompt injection/sliding window |
| 79 | `llm/prompts/engine.py` | 280 | cache constants, cache, validation | ⬜ | Jinja2 prompt renderer |
| 80 | `tools/base.py` | 822 | limits, exceptions | ⬜ | BaseTool ABC + ToolResult |

**Layer 2 total: 16 files, ~3,057 LOC**

---

## Layer 3 — Three Internal Dependencies

| # | File | LOC | Depends On | Status | Notes |
|---|------|-----|-----------|--------|-------|
| 81 | `shared/core/circuit_breaker.py` | 575 | retries, cb_helpers, constants, exceptions | ⬜ | Circuit breaker state machine |
| 82 | `shared/utils/path_safety/validator.py` | 284 | all path_safety sub-modules | ⬜ | Path validation orchestrator |
| 83 | `memory/adapters/in_memory.py` | 94 | _schemas, constants | ⬜ | In-memory store adapter |
| 84 | `memory/adapters/pg_adapter.py` | 399 | _schemas, constants | ⬜ | PostgreSQL store adapter |
| 85 | `memory/adapters/mem0_adapter.py` | 184 | _schemas, constants | ⬜ | Mem0 store adapter |
| 86 | `memory/adapters/knowledge_graph_adapter.py` | 120 | _schemas, constants | ⬜ | Knowledge graph adapter |
| 87 | `storage/database/manager.py` | 233 | engine | ⬜ | DB connection manager |
| 88 | `storage/schemas/agent_config.py` | 533 | shared/constants (5 files) | ⬜ | Agent config Pydantic models |
| 89 | `llm/cost_estimator.py` | 51 | constants, pricing | ⬜ | LLM cost estimation |
| 90 | `llm/cache/llm_cache.py` | 697 | cache/constants, shared/constants, logging | ⬜ | LLM response cache (LRU+TTL) |
| 91 | `tools/tool_cache.py` | 174 | base, cache_constants | ⬜ | Tool result cache |
| 92 | `tools/calculator.py` | 289 | base, constants | ⬜ | Safe math evaluator |
| 93 | `tools/json_parser.py` | 199 | base | ⬜ | JSON parser tool |
| 94 | `tools/http_client.py` | 185 | base, http_constants | ⬜ | HTTP client tool |
| 95 | `tools/git_tool.py` | 173 | base, git_constants | ⬜ | Git operations tool |
| 96 | `tools/_bash_helpers.py` | 522 | base, constants, field_names | ⬜ | Bash tool helpers |
| 97 | `tools/_registry_helpers.py` | 550 | exceptions, base | ⬜ | Tool registry helpers |

**Layer 3 total: 17 files, ~5,262 LOC**

---

## Layer 4+ — Higher Dependencies

Will be broken down as we reach them. Includes:
- `llm/providers/` (base → anthropic/openai/ollama/vllm → factory)
- `llm/service.py` (11 internal deps — the LLM orchestrator)
- `tools/executor.py`, `tools/registry.py`, built-in tools
- `storage/database/models.py` (master schema)
- `memory/service.py` (memory orchestrator)
- `events/event_bus.py` (event bus orchestrator)
- All of: agent, stage, safety, observability, auth, workflow, interfaces

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

---

## Session Log

### Session 1 — 2026-02-28
- Created tracking document
- Mapped all 25 modules at high level
- Broke down into file-level dependency layers (0-3 fully mapped, 97 files)
- Next: Start reviewing Layer 0, file #1 — `shared/constants/sizes.py`
