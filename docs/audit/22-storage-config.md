# Code Audit: `temper_ai/storage/` + `temper_ai/config/`

**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6
**Scope:** All files under `temper_ai/storage/` (14 files) and `temper_ai/config/` (4 files)
**Tests reviewed:** `tests/test_storage/` (3 files), `tests/test_config/` (4 files)

---

## Executive Summary

The storage and config modules are well-structured, with good separation of concerns between database models, engine management, schema validation, and application settings. The codebase follows modern SQLModel/Pydantic patterns and demonstrates strong security awareness (password masking, JSON size validation, UTC-aware datetimes). However, there are several concrete issues: inconsistent use of status constraint constants, missing `tenant_id` on two model files, `updated_at` fields that never auto-update, a thread-unsafe settings singleton, and the `agent_config.py` fan-out at the threshold limit of 7.

**Overall Score: 87/100 (B+)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 88 | Clean, constants extracted, one file at 776 lines |
| Security | 90 | Good credential masking, no SQL injection, minor tenant gap |
| Error Handling | 92 | Robust session management, connection validation |
| Modularity | 85 | Good model split, but main models.py is a gravity well |
| Feature Completeness | 88 | No TODOs/FIXMEs, two concrete gaps |
| Test Quality | 82 | Good coverage for manager/validators, gaps in models/engine |
| Architecture | 86 | Solid foundation, singleton issues, fan-out at limit |

---

## 1. Code Quality

### 1.1 Function/Method Length -- PASS

All functions are within the 50-line limit. The longest methods are the `__init__` validators on `WorkflowExecution` (lines 99-116, 18 lines), `StageExecution` (lines 186-205, 20 lines), and `AgentExecution` (lines 284-303, 20 lines) in `models.py`.

### 1.2 Parameter Count -- PASS

No function exceeds 7 parameters. The `safe_duration_seconds()` in `datetime_utils.py` (line 115) has 3. The `validate_json_size()` in `validators.py` (line 16) has 3.

### 1.3 File Length -- WARNING

| File | Lines | Limit | Status |
|------|-------|-------|--------|
| `storage/database/models.py` | 776 | 500 (class guideline) | **Exceeds class guideline** |
| `storage/schemas/agent_config.py` | 470 | 500 | OK |
| `storage/database/models_tenancy.py` | 298 | 500 | OK |
| `storage/database/manager.py` | 231 | 500 | OK |
| `config/settings.py` | 62 | 500 | OK |

**Finding F-1 (Medium):** `models.py` at 776 lines contains 14 SQLModel classes plus 22 composite Index declarations. While each class is lean, the file is a gravity well that imports from 3 other modules at the bottom (lines 759-776) purely for SQLModel metadata registration. Consider splitting into `models_observability.py` (execution models) and `models_system.py` (merit, metrics, alerts, rollback).

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models.py:776`

### 1.4 Naming -- PASS

Constants follow `UPPER_SNAKE_CASE` convention. Classes use `PascalCase`. Functions use `snake_case`. No naming collisions detected across modules.

### 1.5 Magic Numbers -- PASS

All numeric constants are properly extracted:
- `BYTES_PER_MB` from `shared.constants.sizes`
- `SMALL_POOL_SIZE` from `shared.constants.limits`
- `PG_POOL_OVERFLOW_MULTIPLIER = 2` (line 28, engine.py) -- named constant, acceptable

### 1.6 Module Fan-Out

| File | Fan-out | Limit | Status |
|------|---------|-------|--------|
| `storage/schemas/agent_config.py` | 7 (`llm`, `mcp`, `memory`, `optimization`, `plugins`, `safety`, `shared`) | 8 | **At threshold** |
| `storage/database/models.py` | 3 (`events`, `shared`, `storage`) | 8 | OK |

**Finding F-2 (Low):** `agent_config.py` has fan-out of 7, one below the limit of 8. All cross-domain imports (`mcp`, `optimization`, `plugins`, `memory`, `safety`) are properly lazy (inside `model_validator` methods), which is the correct pattern. No action needed now but any new lazy import would breach the limit.

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/storage/schemas/agent_config.py:11-40`

### 1.7 Inconsistent Constant Usage

**Finding F-3 (Medium):** `AgentExecution` (line 214) uses an inline status constraint string `"status IN ('running', 'completed', 'failed', 'halted', 'timeout')"` instead of the `STATUS_CONSTRAINT` constant that `WorkflowExecution` (line 44) and `StageExecution` (line 125) use. Similarly, `LLMCall` (line 312), `ToolExecution` (line 382), and `RollbackEvent` (line 713) each define their own inline constraint strings instead of using named constants.

```python
# Line 214 - AgentExecution uses inline instead of STATUS_CONSTRAINT
"status IN ('running', 'completed', 'failed', 'halted', 'timeout')"

# Line 312 - LLMCall has different status values (no constant)
"status IN ('success', 'error', 'timeout', 'cancelled')"

# Line 382 - ToolExecution has different status values (no constant)
"status IN ('success', 'error', 'failed', 'timeout', 'cancelled')"
```

**Recommendation:** Extract `LLM_STATUS_CONSTRAINT`, `TOOL_STATUS_CONSTRAINT`, and `ROLLBACK_STATUS_CONSTRAINT` into `constants.py`. Fix `AgentExecution` to use `STATUS_CONSTRAINT`.

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models.py:214,312,382,713`

---

## 2. Security

### 2.1 SQL Injection -- PASS

No f-string SQL detected anywhere in `storage/` or `config/`. All queries use SQLModel/SQLAlchemy ORM. The `CheckConstraint` strings are static literals, not user-influenced.

### 2.2 Credential Storage -- PASS

- `manager.py:20-44`: `_mask_database_url()` properly masks passwords before logging using `urllib.parse`.
- `models_tenancy.py:155`: API key stored as `key_hash` (SHA-256), not plaintext. The `key_prefix` (line 154) stores only first 8 chars for display.
- `agent_config.py:48-56`: The deprecated `api_key` field migrates to `api_key_ref` with proper deprecation warning.

### 2.3 Credential Exposure in Settings

**Finding F-4 (Medium):** `config/settings.py` stores `api_key`, `openai_api_key`, and `secret_key` as plain `str | None` fields (lines 35, 61, 62). While pydantic-settings correctly reads these from environment variables, there is no `repr=False` or `SecretStr` type to prevent accidental exposure in logs or `repr()` calls.

```python
# settings.py:35,61-62 — secrets are plain strings, visible in repr()
api_key: str | None = None
openai_api_key: str | None = None
secret_key: str | None = None
```

**Recommendation:** Use `pydantic.SecretStr` for these fields to prevent accidental exposure:
```python
from pydantic import SecretStr
api_key: SecretStr | None = None
```

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/config/settings.py:35,61-62`

### 2.4 Tenant Isolation

**Finding F-5 (High):** `AgentEvaluationResult` in `models_evaluation.py` and `AgentRegistryDB` in `models_registry.py` are **missing `tenant_id` columns**. Every other model in the system has `tenant_id` for multi-tenant isolation. This means:
- Evaluation results are globally visible across tenants.
- Agent registry entries are globally visible across tenants.

This is a data isolation breach in a multi-tenant deployment.

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models_evaluation.py:18-56`
**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models_registry.py:11-32`

**Recommendation:** Add `tenant_id: str | None = Field(default=None, index=True)` to both models and create an Alembic migration.

### 2.5 YAML Loading -- PASS

`config/_loader.py:31` uses `yaml.safe_load()`, not the unsafe `yaml.load()`.

---

## 3. Error Handling

### 3.1 Database Connection Failures -- PASS (Good)

`manager.py:166-174`: `init_database()` verifies the connection with `SELECT 1` before returning. On failure, it cleans up `_db_manager = None` and raises `ConnectionError` with a masked URL.

### 3.2 Session Error Handling -- PASS (Good)

`manager.py:121-136`: The session context manager correctly implements try/commit/except/rollback/finally/close. The error logging includes masked database URL and isolation level context.

### 3.3 Config File Errors -- PASS (Good)

`config/_loader.py:43-45`: Handles `ImportError` (PyYAML not installed), non-mapping YAML, and general parse errors gracefully, returning empty dict in each case.

### 3.4 Isolation Level Error Handling -- PASS

`manager.py:111-119`: Isolation level setting failures are caught and logged as warnings, allowing the session to proceed with default isolation.

### 3.5 JSON Validation Errors -- PASS (Good)

`validators.py:38-58`: Properly chains `TypeError` from JSON serialization failures and re-raises `JSONSizeError` without wrapping.

---

## 4. Modularity

### 4.1 Model Organization -- GOOD

Models are split into 4 files:
- `models.py` -- Core observability (14 tables)
- `models_evaluation.py` -- Evaluation results (1 table)
- `models_registry.py` -- Agent registry (1 table)
- `models_tenancy.py` -- Multi-tenant access control (7 tables)

The split is logical per domain. However, `models.py` at 776 lines could benefit from further decomposition (see F-1).

### 4.2 Config Module Organization -- EXCELLENT

The config module has clean separation:
- `settings.py` -- Pydantic settings model (62 lines, minimal)
- `_loader.py` -- Config file + env injection (65 lines)
- `_compat.py` -- Legacy env var migration (56 lines)
- `__init__.py` -- Public API + singleton (62 lines)

Priority hierarchy is clearly documented and correctly implemented:
`CLI flags > env vars (TEMPER_*) > ~/.temper/config.yaml > defaults`

### 4.3 Schema Location -- GOOD

`AgentConfig` lives in `storage/schemas/` as the canonical location, breaking what would otherwise be a circular dependency between `agent/` and `workflow/`. 25 files import from this location.

### 4.4 Re-export Pattern -- GOOD

`storage/schemas/__init__.py` re-exports all public types. `storage/database/__init__.py` re-exports engine, manager, and model classes.

### 4.5 Dead Code -- NONE DETECTED

No unreachable code, unused imports (beyond intentional `# noqa: F401` re-exports), or dead branches found.

### 4.6 Constants Modules -- GOOD

Both `storage/database/constants.py` and `storage/schemas/constants.py` exist. However, `storage/schemas/constants.py` defines `VALIDATOR_MODE_AFTER` and `VALIDATOR_MODE_BEFORE` which are never imported anywhere in the codebase.

**Finding F-6 (Low):** `storage/schemas/constants.py` defines two constants (`VALIDATOR_MODE_AFTER`, `VALIDATOR_MODE_BEFORE`) that appear unused.

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/storage/schemas/constants.py:10-11`

---

## 5. Feature Completeness

### 5.1 TODOs/FIXMEs/HACKs -- NONE

Zero TODO, FIXME, HACK, or XXX markers found in either `storage/` or `config/`.

### 5.2 `updated_at` Never Auto-Updates

**Finding F-7 (High):** Five models in `models_tenancy.py` have `updated_at: datetime = Field(default_factory=utcnow)` (Tenant:68, UserDB:92, WorkflowConfigDB:205, StageConfigDB:247, AgentConfigDB:289). This only sets the value at INSERT time. There is no `sa_column_kwargs={"onupdate": utcnow}`, no SQLAlchemy `@event.listens_for(..., "before_update")`, and no application-level code that sets `updated_at` on UPDATE.

This means `updated_at` will always equal `created_at`, making it semantically incorrect and misleading for any dashboard or audit trail that relies on it.

```python
# models_tenancy.py:68 -- Only sets on creation, never on update
updated_at: datetime = Field(default_factory=utcnow)
```

**Recommendation:** Add `sa_column_kwargs={"onupdate": utcnow}` or use a SQLAlchemy `@event.listens_for` hook:
```python
updated_at: datetime = Field(
    default_factory=utcnow,
    sa_column_kwargs={"onupdate": utcnow},
)
```

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models_tenancy.py:68,92,205,247,289`

### 5.3 Missing `ErrorFingerprint` Tenant Scoping

`ErrorFingerprint` (models.py:596) has a `tenant_id` field and index, which is correct. However, the composite indexes at lines 747-748 (`idx_error_fp_classification`, `idx_error_fp_last_seen`) do NOT include `tenant_id`, meaning queries filtering by classification within a tenant will not benefit from the index.

**Finding F-8 (Low):** Composite indexes on `ErrorFingerprint` should include `tenant_id` for multi-tenant query performance:
```python
Index("idx_error_fp_classification", ErrorFingerprint.classification, ErrorFingerprint.tenant_id, ErrorFingerprint.last_seen)
```

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models.py:747-748`

---

## 6. Test Quality

### 6.1 Test Coverage Summary

| Module | Test File | Tests | Coverage |
|--------|-----------|-------|----------|
| `storage/database/manager.py` | `test_storage/test_database/test_manager.py` | 22 | **Good** -- sessions, isolation, thread safety, ALEMBIC_MANAGED |
| `storage/database/validators.py` | `test_storage/test_database/test_validators.py` | 15 | **Good** -- edge cases, unicode, nested, size accuracy |
| `storage/database/engine.py` | (none dedicated) | 0 | **Gap** -- tested implicitly via manager |
| `storage/database/datetime_utils.py` | `test_observability/test_datetime_utils_shim.py` | ~5 | **Partial** -- covered via observability tests |
| `storage/database/models*.py` | (none dedicated) | 0 | **Gap** -- no model unit tests |
| `storage/schemas/agent_config.py` | (none dedicated) | 0 | **Gap** -- validated indirectly via integration |
| `config/settings.py` | `test_config/test_settings.py` | 15 | **Good** -- defaults, env override, kwargs, singleton |
| `config/_compat.py` | `test_config/test_compat.py` | 7 | **Good** -- migration, no-overwrite, integration |
| `config/_loader.py` | `test_config/test_loader.py` | 7 | **Good** -- missing file, valid yaml, env injection |

### 6.2 Missing Test Coverage

**Finding F-9 (Medium):** No dedicated tests for:
1. **`storage/database/engine.py`** -- `create_app_engine()` SQLite-in-production rejection, `_register_sqlite_pragmas()` WAL mode, `create_test_engine()`. Currently tested only implicitly through `DatabaseManager`.
2. **`storage/database/models*.py`** -- No tests for model `__init__` JSON size validation, `CheckConstraint` enforcement, relationship cascade behavior, or `UniqueConstraint` enforcement.
3. **`storage/schemas/agent_config.py`** -- No tests for `AgentConfigInner` model validators (`validate_autonomy`, `validate_mcp_servers`, `validate_prompt_optimization`, `validate_plugin_config`, `validate_cross_pollination`, `validate_agent_type_fields`), `PromptConfig` mutual exclusivity validation, `ErrorHandlingConfig` strategy/fallback validation, or `InferenceConfig.migrate_api_key` deprecation behavior.

### 6.3 Test Quality Observations

- **Good pattern:** All test files use `pytest.raises` with `match=` for specific error messages.
- **Good pattern:** `test_settings.py` properly cleans TEMPER_* env vars and resets singleton between tests.
- **Good pattern:** `test_compat.py` saves and restores env vars in fixture teardown.
- **Minor:** `test_manager.py:1` has outdated docstring referencing "src/database/manager.py" instead of "temper_ai/storage/database/manager.py".

---

## 7. Architectural Observations

### 7.1 Settings Singleton Not Thread-Safe

**Finding F-10 (Medium):** `config/__init__.py` uses a module-level `_settings` variable for singleton caching but has no thread lock, unlike `manager.py` which uses `_db_lock = threading.Lock()`. In a multi-threaded server startup, two threads could race on `get_settings()` and both call `load_settings()`, which modifies `os.environ` (via `inject_config_as_env` and `apply_compat_env_vars`). This could produce inconsistent environment state.

```python
# config/__init__.py:47-55 -- No lock protection
def get_settings() -> TemperSettings:
    global _settings
    if _settings is None:
        _settings = load_settings()  # Modifies os.environ!
    return _settings
```

**Recommendation:** Add a threading lock:
```python
_settings_lock = threading.Lock()

def get_settings() -> TemperSettings:
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                _settings = load_settings()
    return _settings
```

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/config/__init__.py:47-55`

### 7.2 SQLite Production Guard

**Good:** `engine.py:59-64` explicitly rejects SQLite URLs outside of test mode (`"pytest" not in sys.modules`). This prevents accidental use of SQLite in production.

### 7.3 Alembic Production Strategy

**Good:** `manager.py:176-186` checks `ALEMBIC_MANAGED` env var to skip `create_all_tables()` in production, deferring DDL to `alembic upgrade head`. This is the correct pattern for production schema management.

### 7.4 Cross-Module Import Strategy at Bottom of `models.py`

`models.py:759-776` imports from `events.models`, `models_evaluation`, `models_registry`, and `models_tenancy` at the bottom of the file. These imports exist solely to register the models with SQLModel's shared metadata. While this works correctly, it creates a hidden dependency and makes the file appear to have higher fan-out than its core logic requires.

**Finding F-11 (Low):** Consider adding a `models_all.py` or `_registry.py` file that imports all model modules in one place for metadata registration, rather than using bottom-of-file imports in `models.py`.

### 7.5 Pydantic vs SQLModel Dual Schema System

The codebase correctly maintains two schema systems:
- **Pydantic models** (`storage/schemas/agent_config.py`) for configuration validation and API contracts
- **SQLModel models** (`storage/database/models*.py`) for database persistence

These do not duplicate each other -- the Pydantic schemas define agent configuration structure while SQLModel defines observability/execution tracking. The `agent_config_snapshot` JSON column on `AgentExecution` bridges the two by storing a serialized copy of the Pydantic config at execution time.

### 7.6 `AgentConfigInner` Lazy Validation Pattern

`agent_config.py` uses 5 `@model_validator(mode="after")` methods with lazy imports for cross-domain types (`AutonomyConfig`, `MCPServerConfig`, `PromptOptimizationConfig`, `PluginConfig`, `CrossPollinationConfig`). This is the correct pattern to avoid circular imports and keep fan-out manageable, as documented in MEMORY.md.

---

## 8. Findings Summary

| ID | Severity | Category | Description | File:Line |
|----|----------|----------|-------------|-----------|
| F-1 | Medium | Quality | `models.py` at 776 lines; consider splitting | `models.py:776` |
| F-2 | Low | Quality | `agent_config.py` fan-out at 7/8 threshold | `agent_config.py:11-40` |
| F-3 | Medium | Quality | Inconsistent status constraint constants (4 inline strings) | `models.py:214,312,382,713` |
| F-4 | Medium | Security | Secret fields in settings use plain `str` not `SecretStr` | `settings.py:35,61-62` |
| F-5 | **High** | Security | `AgentEvaluationResult` and `AgentRegistryDB` missing `tenant_id` | `models_evaluation.py:18`, `models_registry.py:11` |
| F-6 | Low | Modularity | Unused constants in `schemas/constants.py` | `schemas/constants.py:10-11` |
| F-7 | **High** | Completeness | `updated_at` fields never auto-update on UPDATE | `models_tenancy.py:68,92,205,247,289` |
| F-8 | Low | Performance | Composite indexes on `ErrorFingerprint` missing `tenant_id` | `models.py:747-748` |
| F-9 | Medium | Tests | No dedicated tests for engine.py, models, or agent_config schemas | Multiple |
| F-10 | Medium | Architecture | Settings singleton not thread-safe (no lock) | `config/__init__.py:47-55` |
| F-11 | Low | Architecture | Bottom-of-file imports for metadata registration | `models.py:759-776` |

### Priority Actions

1. **F-5 (High):** Add `tenant_id` to `AgentEvaluationResult` and `AgentRegistryDB` + Alembic migration
2. **F-7 (High):** Add `onupdate` trigger for `updated_at` fields in tenancy models
3. **F-3 (Medium):** Extract all status constraint strings to named constants in `constants.py`
4. **F-4 (Medium):** Convert secret fields in `TemperSettings` to `pydantic.SecretStr`
5. **F-10 (Medium):** Add threading lock to `config/__init__.py` settings singleton
6. **F-9 (Medium):** Add test coverage for engine, models, and agent_config validators

---

## Files Reviewed

### `temper_ai/storage/database/`
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/__init__.py` (72 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/constants.py` (37 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/datetime_utils.py` (162 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/engine.py` (115 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/manager.py` (231 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models.py` (776 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models_evaluation.py` (56 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models_registry.py` (32 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/models_tenancy.py` (298 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/database/validators.py` (68 lines)

### `temper_ai/storage/schemas/`
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/schemas/__init__.py` (39 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/schemas/agent_config.py` (470 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/storage/schemas/constants.py` (11 lines)

### `temper_ai/config/`
- `/home/shinelay/meta-autonomous-framework/temper_ai/config/__init__.py` (62 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/config/_compat.py` (55 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/config/_loader.py` (64 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/config/settings.py` (62 lines)

### Tests
- `/home/shinelay/meta-autonomous-framework/tests/test_config/test_settings.py` (144 lines, 15 tests)
- `/home/shinelay/meta-autonomous-framework/tests/test_config/test_compat.py` (100 lines, 7 tests)
- `/home/shinelay/meta-autonomous-framework/tests/test_config/test_loader.py` (113 lines, 7 tests)
- `/home/shinelay/meta-autonomous-framework/tests/test_storage/test_database/test_manager.py` (303 lines, 22 tests)
- `/home/shinelay/meta-autonomous-framework/tests/test_storage/test_database/test_validators.py` (215 lines, 15 tests)
