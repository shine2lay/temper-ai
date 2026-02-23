# Audit 25: Experimentation Module

**Module:** `temper_ai/experimentation/`
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6 (automated)
**Scope:** 14 source files, 24 test files
**Overall Grade: A- (91/100)**

---

## Table of Contents

1. [File Inventory](#1-file-inventory)
2. [Code Quality](#2-code-quality)
3. [Security](#3-security)
4. [Error Handling](#4-error-handling)
5. [Modularity](#5-modularity)
6. [Feature Completeness](#6-feature-completeness)
7. [Test Quality](#7-test-quality)
8. [Architectural Gaps](#8-architectural-gaps)
9. [Findings Summary](#9-findings-summary)
10. [Recommendations](#10-recommendations)

---

## 1. File Inventory

### Source Files (14)

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 64 | Module exports and version |
| `constants.py` | 93 | Centralized constants for statistical/config params |
| `models.py` | 374 | SQLModel ORM (Experiment, Variant, VariantAssignment, ExperimentResult) |
| `service.py` | 436 | ExperimentService main API |
| `experiment_crud.py` | 368 | CRUD with thread-safe LRU cache |
| `assignment.py` | 385 | Variant assignment strategies (Random, Hash, Stratified, Bandit) |
| `analyzer.py` | 416 | Statistical analysis (t-tests, guardrails, recommendations) |
| `sequential_testing.py` | 279 | SPRT and Bayesian analysis |
| `metrics_collector.py` | 382 | Metrics collection from observability DB |
| `config_manager.py` | 341 | Deep merge config with security checks |
| `validators.py` | 146 | Input validation and Unicode normalization |
| `_workflow_integration.py` | 96 | Workflow integration helpers |
| `dashboard_routes.py` | 101 | FastAPI routes for dashboard |
| `dashboard_service.py` | 72 | Data service for JSON serialization |

### Test Files (24)

| File | Tests | Coverage Focus |
|------|-------|----------------|
| `test_service.py` | ~20 | Service CRUD, lifecycle, assignment, tracking |
| `test_assignment.py` | ~15 | All 4 assignment strategies, distribution |
| `test_metrics_collector.py` | ~12 | DB integration, metric extraction/aggregation |
| `test_sequential_testing.py` | ~10 | SPRT, Bayesian, sample size, edge cases |
| `test_crud.py` | ~12 | CRUD, cache, thread safety |
| `test_models.py` | ~10 | Enums, model creation, defaults, timestamps |
| `test_validators.py` | ~15 | SQL injection, XSS, path traversal, Unicode |
| `test_config_manager.py` | ~12 | Deep merge, security, config diff |
| `test_analyzer.py` | ~10 | T-tests, percentiles, guardrails, recommendations |
| `test_workflow_integration.py` | ~8 | assign_and_merge, tracking, extraction |
| `test_dashboard_routes.py` | ~8 | FastAPI TestClient endpoints |
| `test_dashboard_service.py` | ~8 | ExperimentDataService |
| `test_early_stopping.py` | ~6 | Sequential testing + guardrails integration |
| `test_experiment_lifecycle.py` | ~8 | E2E lifecycle, config overrides, multi-variant |
| `test_observability_integration.py` | ~5 | E2E tracker + collector + analyzer |
| `test_assigner.py` | ~8 | VariantAssigner coordinator, delegation |
| `test_n1_query_32.py` | ~4 | Database-side JSON filtering, N+1 prevention |
| `test_random_assign_38.py` | ~4 | Cryptographic PRNG, thread safety |
| `test_cache_eviction.py` | ~6 | LRU eviction, bounded cache |
| `test_service_security.py` | ~6 | SQL injection prevention, security logging |
| `test_detached_orm_14.py` | ~6 | Detached instance prevention, eager loading |
| `test_database_failures.py` | ~8 | Connection failures, pool exhaustion, rollbacks |
| `conftest.py` | -- | Shared fixtures, factories |
| `__init__.py` | -- | Package marker |

---

## 2. Code Quality

### 2.1 Function Length (<=50 lines)

**Status: PASS** -- All functions are within the 50-line limit.

Longest functions (measured by body lines):
- `service.py:track_execution_complete` (lines 314-368): ~45 lines -- within limit but on the upper end
- `analyzer.py:analyze_experiment` (lines 50-126): ~40 lines -- well-decomposed with helpers
- `experiment_crud.py:create_experiment` (lines 243-279): ~25 lines -- clean delegation pattern

### 2.2 Parameter Count (<=7)

**Status: WARN** -- 1 violation found.

| File:Line | Function | Params | Notes |
|-----------|----------|--------|-------|
| `service.py:105` | `create_experiment` | 10 (8 named + `**kwargs`) | Has `# noqa: params` -- backward compat |

Mitigating factor: This method delegates to `ExperimentParams` dataclass in `experiment_crud.py:38`, which is the correct pattern. The service method preserves backward compatibility as the public API surface.

### 2.3 Naming Accuracy

**Status: PASS** -- All function and class names accurately reflect behavior.

Notable positive patterns:
- `_inconclusive_result` in `analyzer.py:404` -- clearly communicates intent
- `_check_protected_fields` in `config_manager.py:127` -- recursive security check, name is precise
- `_hash_to_variant` in `assignment.py:194` -- descriptive of hash-to-bucket mapping

### 2.4 Magic Numbers

**Status: PASS** -- Constants are well-centralized.

All statistical constants defined in `constants.py` (lines 1-93). Assignment constants use `HASH_MODULO_DIVISOR`, `HASH_FRACTION_LENGTH` locally. Shared constants imported from `temper_ai.shared.constants.limits` and `temper_ai.shared.constants.probabilities`.

One observation: `dashboard_routes.py:29` uses `limit: int = 50` with `# noqa: scanner: skip-magic`. This matches `DEFAULT_EXPERIMENT_LIMIT = 50` in `dashboard_service.py:5` -- the route could import the constant instead.

### 2.5 Module Fan-Out

**Status: PASS** -- All modules stay within the fan-out limit of 8.

Maximum fan-out observed: `service.py` imports from 7 modules (experimentation.analyzer, .assignment, .config_manager, .constants, .experiment_crud, .models, shared modules).

---

## 3. Security

### 3.1 Input Validation

**Status: EXCELLENT**

**Experiment Name Validation** (`validators.py:22-72`):
- Length check before expensive ops (line 50)
- NFKC Unicode normalization (line 55) -- prevents homograph attacks
- Regex whitelist `^[a-zA-Z0-9_-]+$` (line 58) -- strict character set
- Must start with letter (line 65) -- prevents tooling issues
- No consecutive special chars (line 69) -- prevents parsing ambiguity

**Variant Name Validation** (`validators.py:75-99`):
- Same pattern, shorter max length (30 vs 50)
- Atomic batch validation in `validate_variant_list` (line 102-138)

**Security Logging** (`validators.py:127-135`, `experiment_crud.py:128-137`):
- Uses structured `security_event` extra field
- Truncates logged input to `MAX_NAME_DISPLAY_LENGTH` (30 chars) -- prevents log injection

### 3.2 Protected Config Fields

**Status: EXCELLENT**

`config_manager.py:15-28` defines `PROTECTED_CONFIG_FIELDS`:
- `api_key`, `secret`, `password`, `token`, `credentials`, `private_key` -- credential protection
- `safety_policy` -- prevents safety bypass
- `max_retries`, `timeout` -- prevents resource exhaustion
- Recursive checking (`_check_protected_fields`, line 127-153) catches nested attempts
- Custom `SecurityViolationError` exception (line 36)

### 3.3 SQL Injection Prevention

**Status: PASS**

- No f-string SQL anywhere in the module
- `metrics_collector.py:79` uses parameterized queries: `text("json_extract(...)").params(exp_id=experiment_id)`
- `experiment_crud.py:227-241` handles `IntegrityError` with generic message (timing attack mitigation)

### 3.4 Cryptographic Assignment

**Status: EXCELLENT**

- `assignment.py:130` uses `secrets.SystemRandom()` for random assignment (cryptographic PRNG)
- `assignment.py:188` uses `hashlib.sha256` for hash assignment (not MD5/broken hashes)
- Comment at line 187 explicitly documents why SHA-256 was chosen over MD5

### 3.5 Finding: Potential Statistical Manipulation

**Severity: LOW**

`service.py:197-211` (`pause_experiment`) does not validate current status. Any experiment can be paused from any status (RUNNING, STOPPED, COMPLETED, DRAFT). While `start_experiment` correctly validates `status != DRAFT`, `pause_experiment` lacks equivalent guards.

Impact: An actor could repeatedly pause/unpause an experiment to manipulate the timing of when samples are collected, potentially biasing results.

---

## 4. Error Handling

### 4.1 Database Error Handling

**Status: GOOD**

- `experiment_crud.py:227-241` catches `IntegrityError` specifically (not broad `Exception`)
- Generic error message prevents information leakage (line 238-241)
- `service.py:341-358` uses atomic SQL `update()` expressions for variant counter increments -- prevents race conditions (C-05 pattern)

### 4.2 Session Safety

**Status: EXCELLENT**

- `experiment_crud.py:319-320` uses `session.expunge(experiment)` before caching (H-14 pattern)
- `experiment_crud.py:311-314` uses `selectinload` for eager relationship loading -- prevents N+1 and lazy-load-after-close errors
- Cache invalidation called after every mutation (`service.py:193, 209, 232, 299, 364`)

### 4.3 Statistical Computation Edge Cases

**Status: GOOD**

- `sequential_testing.py:97-99` handles zero variance: returns `stop_no_difference`
- `sequential_testing.py:220-229` handles zero variance in Bayesian analysis: returns deterministic result
- `analyzer.py:147` handles single-sample std: `np.std(values, ddof=1) if len(values) > 1 else 0.0`
- `analyzer.py:73-74` handles empty completed assignments: returns inconclusive result
- `analyzer.py:86-88` handles insufficient sample size: returns inconclusive result

### 4.4 Findings

**Finding E-1: Missing timezone in datetime.now()** (Severity: MEDIUM)

`metrics_collector.py:290`:
```python
"collected_at": datetime.now().isoformat(),
```
Should be:
```python
"collected_at": datetime.now(timezone.utc).isoformat(),
```
The codebase standard (per coding standards) requires `datetime.now(timezone.utc)` not `datetime.utcnow()` or `datetime.now()`.

**Finding E-2: Inconsistent logging import** (Severity: LOW)

`_workflow_integration.py:3` and `metrics_collector.py:10` use `import logging` directly instead of `from temper_ai.shared.utils.logging import get_logger`. All other files in the module use the shared `get_logger` utility. This inconsistency means these two files miss any custom log configuration or formatting applied by the shared logging utility.

---

## 5. Modularity

### 5.1 Service Layer Design

**Status: EXCELLENT**

Clean delegation pattern in `ExperimentService`:
- `ExperimentCRUD` for database operations and caching
- `VariantAssigner` for assignment logic
- `StatisticalAnalyzer` for statistical analysis
- `ConfigManager` for configuration management

Each component is independently testable with clear responsibilities.

### 5.2 Strategy Pattern

**Status: GOOD**

`assignment.py` implements a clean strategy pattern:
- `AssignmentStrategy` abstract base class with `assign()` method
- 4 concrete strategies: `RandomAssignment`, `HashAssignment`, `StratifiedAssignment`, `BanditAssignment`
- `VariantAssigner` coordinator with `register_strategy()` for extensibility

### 5.3 Finding: Unused Constants

**Finding E-3: Dead constants** (Severity: LOW)

`assignment.py:20-21`:
```python
HASH_MODULO_DIVISOR = 100000  # Divisor for normalizing hash to [0, 1)
HASH_FRACTION_LENGTH = 16  # Number of hex digits for hash-based assignment
```
Neither `HASH_MODULO_DIVISOR` nor `HASH_FRACTION_LENGTH` are used anywhere in the module. The hash normalization at line 211 uses `MAX_QUEUE_SIZE` from shared constants instead:
```python
hash_fraction = (hash_value % MAX_QUEUE_SIZE) / float(MAX_QUEUE_SIZE)
```
These constants appear to be leftover from an earlier implementation.

### 5.4 Finding: Private Attribute Access Across Layer Boundary

**Finding E-4: dashboard_routes accesses private _service** (Severity: MEDIUM)

`dashboard_routes.py:73, 88, 97`:
```python
exp_id = service._service.create_experiment(...)
service._service.start_experiment(experiment_id)
service._service.stop_experiment(experiment_id)
```
The routes reach through `ExperimentDataService._service` (private attribute with underscore prefix) to call `ExperimentService` methods directly. This violates encapsulation. The `ExperimentDataService` should expose `create_experiment`, `start_experiment`, and `stop_experiment` wrapper methods, consistent with how `list_experiments`, `get_experiment`, and `get_results` are already wrapped.

### 5.5 Finding: New Service Instances Per Call in Workflow Integration

**Finding E-5: Transient ExperimentService instances** (Severity: MEDIUM)

`_workflow_integration.py:28` and `_workflow_integration.py:77`:
```python
service = ExperimentService()
```
Each call to `assign_and_merge()` or `track_experiment_completion()` creates a new `ExperimentService` instance. This means:
1. A new `ExperimentCRUD` with a fresh empty cache is created each time
2. The LRU cache provides zero benefit since it's discarded after each call
3. New `VariantAssigner`, `StatisticalAnalyzer`, and `ConfigManager` instances are created unnecessarily

These should either accept a service parameter or use a module-level singleton/factory.

---

## 6. Feature Completeness

### 6.1 Placeholder Implementations

**Finding E-6: Two placeholder assignment strategies** (Severity: LOW)

`assignment.py:224-271` (`StratifiedAssignment`):
```python
# Future Enhancement: Stratified random assignment for experiment consistency
# Currently falls back to simple hash assignment
return HashAssignment().assign(experiment, variants, execution_id, context)
```

`assignment.py:274-318` (`BanditAssignment`):
```python
# Future Enhancement: Multi-armed bandit for dynamic traffic allocation
# Currently falls back to random assignment
return RandomAssignment().assign(experiment, variants, execution_id, context)
```

Both are documented as future enhancements with clear fallback behavior. Each has detailed comments describing what the full implementation would require. These are acceptable for the current iteration.

### 6.2 Missing Features

**Finding E-7: No delete experiment functionality** (Severity: LOW)

The module provides `create`, `get`, `list`, `start`, `pause`, `stop` operations but no `delete_experiment`. The `Experiment` model has `CASCADE` delete configured on all relationships (models.py:149-151), so the ORM supports deletion, but no service or route method exposes it.

**Finding E-8: No pause_experiment status validation** (Severity: MEDIUM)

`service.py:197-211`:
```python
def pause_experiment(self, experiment_id: str) -> None:
    with get_session() as session:
        experiment = session.get(Experiment, experiment_id)
        if not experiment:
            raise ValueError(...)
        experiment.status = ExperimentStatus.PAUSED
```
Unlike `start_experiment` (which validates `status != DRAFT` at line 184), `pause_experiment` accepts any current status. This allows pausing a DRAFT, STOPPED, or COMPLETED experiment, which is semantically incorrect.

**Finding E-9: No resume from PAUSED** (Severity: LOW)

There is no dedicated `resume_experiment` method. Once paused, the only path forward is `stop_experiment`. The `start_experiment` method requires `status == DRAFT`, so it cannot be used to resume. This limits the experiment lifecycle.

### 6.3 SQLite-Specific SQL

**Finding E-10: json_extract is SQLite-specific** (Severity: MEDIUM)

`metrics_collector.py:79`:
```python
query = select(WorkflowExecution).where(
    text("json_extract(extra_metadata, '$.experiment_id') = :exp_id")
)
```
And `metrics_collector.py:312-316`:
```python
text("json_extract(extra_metadata, '$.experiment_id') = :exp_id"),
text("json_extract(extra_metadata, '$.variant_id') = :var_id"),
```
`json_extract()` is SQLite-specific. PostgreSQL uses `->` / `->>` operators, or `jsonb_extract_path_text()`. Since the project has Docker/Helm deployment with PostgreSQL (R5), this will fail when running against a PostgreSQL backend. Should use SQLAlchemy's database-agnostic JSON operators or a compatibility layer.

---

## 7. Test Quality

### 7.1 Coverage Assessment

**Status: EXCELLENT** -- 24 test files for 14 source files (1.7x ratio).

Every source file has at least one dedicated test file. Several have multiple specialized test files:
- `service.py` is tested by `test_service.py`, `test_service_security.py`, `test_cache_eviction.py`
- `experiment_crud.py` is tested by `test_crud.py`, `test_detached_orm_14.py`
- `assignment.py` is tested by `test_assignment.py`, `test_assigner.py`, `test_random_assign_38.py`
- `metrics_collector.py` is tested by `test_metrics_collector.py`, `test_n1_query_32.py`

### 7.2 Security Test Coverage

**Status: EXCELLENT**

Dedicated security tests in multiple files:
- `test_validators.py` covers SQL injection (`test'; DROP TABLE--`), XSS (`<script>alert`), path traversal (`../../../etc/passwd`), Unicode homograph attacks, consecutive special chars
- `test_service_security.py` covers SQL injection through service layer, security event logging
- `test_config_manager.py` covers protected field violations (nested and top-level), `SecurityViolationError`

### 7.3 Edge Case and Regression Tests

**Status: EXCELLENT**

Dedicated regression test files with issue IDs:
- `test_n1_query_32.py` -- N+1 query prevention (issue #32)
- `test_random_assign_38.py` -- Cryptographic PRNG verification (issue #38)
- `test_detached_orm_14.py` -- Detached ORM instance prevention (issue #14)
- `test_database_failures.py` -- Connection failures, pool exhaustion, transaction rollbacks
- `test_cache_eviction.py` -- LRU eviction behavior under bounded cache

### 7.4 Statistical Testing Coverage

**Status: GOOD**

`test_sequential_testing.py` covers:
- SPRT boundaries, continue/stop decisions
- Bayesian posterior computation, credible intervals
- Sample size calculation
- Zero variance edge cases

`test_analyzer.py` covers:
- T-test computation, p-values, confidence intervals
- Percentile calculations (p50, p95, p99)
- Guardrail violation detection
- Recommendation generation for all `RecommendationType` values

### 7.5 Missing Test Coverage

**Finding E-11: No test for pause_experiment from invalid states** (Severity: LOW)

There is no test verifying that `pause_experiment` rejects experiments in DRAFT, STOPPED, or COMPLETED states (because the code itself lacks this validation -- see Finding E-8).

**Finding E-12: No test for concurrent write-write conflicts** (Severity: LOW)

`test_database_failures.py` tests connection failures and pool exhaustion, and `test_crud.py` tests concurrent cache operations, but there is no test for concurrent `track_execution_complete` calls for the same workflow_id, which would exercise the atomic SQL update pattern at `service.py:341-358`.

---

## 8. Architectural Gaps

### 8.1 Experiment Lifecycle State Machine

The experiment lifecycle has implicit state transitions but no explicit state machine. The valid transitions should be:

```
DRAFT -> RUNNING -> PAUSED -> RUNNING (resume)
                 -> STOPPED
                 -> COMPLETED
```

Currently, transitions are validated ad-hoc in each method. A `_validate_transition(current, target)` method would centralize this logic and prevent invalid transitions (see Findings E-8, E-9).

### 8.2 Multi-Tenant Isolation

The experimentation module does not integrate with the M10 multi-tenant system. `ExperimentService` and `ExperimentCRUD` have no tenant scoping. In a multi-tenant deployment:
- `list_experiments` returns all experiments across tenants
- `create_experiment` does not tag experiments with a tenant_id
- The LRU cache in `ExperimentCRUD` could serve cached experiments from other tenants

This is a gap relative to the M10 tenant isolation architecture.

### 8.3 Observability Integration

The module uses `logger.info()` for operation tracking but does not emit structured events through the `TemperEventBus` (M9). Experiment lifecycle events (created, started, paused, stopped, winner_declared) should be emitted as typed events for cross-workflow correlation and dashboard real-time updates.

### 8.4 Database Portability

As noted in Finding E-10, the `json_extract` SQL in `metrics_collector.py` is SQLite-specific. The broader codebase includes Docker/Helm deployment targeting PostgreSQL. A database-agnostic JSON query abstraction is needed.

---

## 9. Findings Summary

| ID | Severity | Category | File:Line | Description |
|----|----------|----------|-----------|-------------|
| E-1 | MEDIUM | Error Handling | `metrics_collector.py:290` | `datetime.now()` without timezone |
| E-2 | LOW | Code Quality | `_workflow_integration.py:3`, `metrics_collector.py:10` | Inconsistent `import logging` vs shared `get_logger` |
| E-3 | LOW | Dead Code | `assignment.py:20-21` | Unused `HASH_MODULO_DIVISOR` and `HASH_FRACTION_LENGTH` constants |
| E-4 | MEDIUM | Modularity | `dashboard_routes.py:73,88,97` | Accesses private `_service` attribute across layer boundary |
| E-5 | MEDIUM | Modularity | `_workflow_integration.py:28,77` | Creates transient `ExperimentService` per call (cache waste) |
| E-6 | LOW | Feature | `assignment.py:224-318` | Placeholder strategies (Stratified, Bandit) with fallback |
| E-7 | LOW | Feature | `service.py` | No delete experiment functionality |
| E-8 | MEDIUM | Feature | `service.py:197-211` | `pause_experiment` lacks status validation |
| E-9 | LOW | Feature | `service.py` | No resume from PAUSED state |
| E-10 | MEDIUM | Portability | `metrics_collector.py:79,312-316` | SQLite-specific `json_extract` SQL |
| E-11 | LOW | Tests | `tests/test_experimentation/` | No test for pause from invalid states |
| E-12 | LOW | Tests | `tests/test_experimentation/` | No concurrent write-write conflict test |

### Severity Distribution

- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 5 (E-1, E-4, E-5, E-8, E-10)
- **LOW:** 7 (E-2, E-3, E-6, E-7, E-9, E-11, E-12)

---

## 10. Recommendations

### Priority 1: Quick Fixes (< 1 hour)

1. **Fix E-1**: Replace `datetime.now()` with `datetime.now(timezone.utc)` at `metrics_collector.py:290`
2. **Fix E-2**: Replace `import logging` with `from temper_ai.shared.utils.logging import get_logger` in `_workflow_integration.py` and `metrics_collector.py`
3. **Fix E-3**: Remove unused `HASH_MODULO_DIVISOR` and `HASH_FRACTION_LENGTH` from `assignment.py`

### Priority 2: Design Improvements (1-3 hours)

4. **Fix E-4**: Add `create_experiment`, `start_experiment`, `stop_experiment` wrapper methods to `ExperimentDataService` so routes don't access `_service` directly
5. **Fix E-8/E-9**: Add status validation to `pause_experiment` (require RUNNING status) and add `resume_experiment` method (require PAUSED status, transition to RUNNING)
6. **Fix E-5**: Accept optional `ExperimentService` parameter in `assign_and_merge` and `track_experiment_completion`, or use a module-level lazy singleton

### Priority 3: Architectural (3+ hours)

7. **Fix E-10**: Abstract JSON query operations into a database-agnostic helper that dispatches to `json_extract` (SQLite) or `->>`/`jsonb_extract_path_text` (PostgreSQL) based on the configured engine dialect
8. **Multi-tenant integration**: Add `tenant_id` field to `Experiment` model and integrate with `temper_ai.auth.tenant_scope.scoped_query` for tenant isolation
9. **Event bus integration**: Emit experiment lifecycle events through `TemperEventBus` for dashboard real-time updates and cross-workflow correlation

---

## Strengths

1. **Security-first design**: Unicode normalization, protected config fields, cryptographic PRNG, parameterized queries, generic error messages to prevent information leakage
2. **Thread-safe caching**: OrderedDict + threading.Lock with LRU eviction (ST-07 pattern)
3. **Session safety**: expunge() before caching, eager loading with selectinload (H-14 pattern)
4. **Well-decomposed architecture**: Clean separation of concerns across service/CRUD/assignment/analysis/config layers
5. **Comprehensive test suite**: 24 test files with dedicated regression tests for specific issues (#14, #32, #38), security tests, and database failure tests
6. **Statistical rigor**: Both frequentist (t-tests, SPRT) and Bayesian analysis with proper edge case handling for zero variance, insufficient samples
7. **Constants discipline**: All magic numbers extracted to `constants.py` with descriptive names and section headers
