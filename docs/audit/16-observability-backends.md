# Audit Report 16: Observability Backends + Aggregation

**Scope:** `temper_ai/observability/backends/` (7 files), `temper_ai/observability/aggregation/` (5 files), `temper_ai/observability/metric_aggregator.py`
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The observability backends and aggregation modules are well-architected with a clean plugin interface (`ObservabilityBackend` ABC), proper primary/secondary fan-out in the composite backend, and a solid SQL implementation with buffering. The code quality is generally high with good constant extraction and error isolation. However, there are several issues: the `cleanup_old_records` implementation is incomplete (only deletes workflows, not child records), `percentile_cont` in query_builder.py is PostgreSQL-only and will fail on SQLite, and the OTel backend has a module-level import that can crash the import if the OTEL package is partially installed. No SQL injection risks were found -- all queries use parameterized SQLAlchemy constructs.

**Overall Score: 82/100 (B+)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 85 | Clean structure, good constant extraction, minimal magic numbers |
| Security | 90 | No SQL injection, parameterized queries throughout, no credential leakage |
| Error Handling | 80 | Good isolation in composite backend; broad `except Exception` in aggregator |
| Modularity | 88 | Clean interface hierarchy, proper mixin decomposition |
| Feature Completeness | 65 | S3/Prometheus are stubs; cleanup is incomplete; OTel missing tests |
| Test Quality | 78 | Good SQL/NoOp/Composite coverage; no OTel tests; no aggregation orchestrator tests |
| Architecture | 85 | Solid plugin pattern, fan-out design, N+1 elimination via eager loading |

---

## 1. Code Quality

### 1.1 Function Length Violations (>50 lines)

**PASS** -- No functions exceed 50 lines. The largest functions are well under the limit:
- `_eager_build_workflow_dict` in `_sql_backend_helpers.py:517-542` (26 lines)
- `track_llm_call` in `sql_backend.py:319-367` (49 lines, just under)
- `_start_span` in `otel_backend.py:164-186` (23 lines)

The helper module extraction (`_sql_backend_helpers.py`, `_OTelAsyncMixin`, `_CompositeAsyncMixin`) was done well to keep class sizes manageable.

### 1.2 Parameter Count Violations (>7 params)

**WARNING** -- Several methods have 8+ parameters due to the nature of tracking interfaces:

| Location | Method | Params | Mitigation |
|----------|--------|--------|------------|
| `otel_backend.py:431` | `track_workflow_start` | 7 + **kwargs | OK -- uses data bundle pattern |
| `metric_creator.py:374` | `_create_agent_performance_metrics` | 7 | Borderline -- could use MetricParams dataclass |
| `metric_creator.py:425` | `_create_llm_performance_metrics` | 7 | Borderline -- could use MetricParams dataclass |
| `_sql_backend_helpers.py:80-90` | `SqlSafetyViolationParams` | 9 fields | Correctly uses dataclass bundling |

The codebase correctly uses the **data bundle pattern** (`WorkflowStartData`, `LLMCallData`, `ToolCallData`, etc.) to keep method signatures manageable. The abstract interface in `backend.py` consistently uses these bundles.

### 1.3 Magic Numbers

**PASS** -- Constants are well extracted:
- `otel_backend.py:83-85`: `SPAN_TTL_SECONDS = 3600`, `MAX_ACTIVE_SPANS = 10000`, `CLEANUP_THRESHOLD = 100`
- `_sql_backend_helpers.py:48`: `UUID_HEX_LENGTH = 12`
- `_sql_backend_helpers.py:821`: `_MAX_RECENT_IDS = 10`
- `query_builder.py:10`: `PERCENTILE_P99 = 0.99` (and `PROB_NEAR_CERTAIN = 0.95` imported from shared constants)
- `metric_creator.py:10`: `UUID_HEX_LENGTH = 12`

One minor issue: the `256` truncation in `otel_backend.py:480,558,607,767` uses `[:256]` with `# noqa` comments. This should be extracted to a named constant like `MAX_OTEL_ERROR_LENGTH = 256`.

### 1.4 Naming Conventions

**PASS** -- Naming is consistent:
- Backend classes: `SQLObservabilityBackend`, `OTelBackend`, `CompositeBackend`, `NoOpBackend`
- Private helpers prefixed with `_`: `_start_span`, `_end_span`, `_add_event`, `_fan_out`
- Constants: `UPPER_CASE` throughout
- Mixins: `_OTelAsyncMixin`, `_CompositeAsyncMixin`, `_CompositeReadMixin`, `SQLDelegatedMethodsMixin`

### 1.5 Fan-Out

**PASS** -- Module fan-out is within limits:
- `otel_backend.py`: 4 imports (temper_ai + stdlib)
- `sql_backend.py`: 6 imports from temper_ai modules
- `_sql_backend_helpers.py`: 5 imports from temper_ai modules
- `composite_backend.py`: 2 imports from temper_ai
- `aggregation/aggregator.py`: 4 imports from temper_ai

---

## 2. Security

### 2.1 SQL Injection

**PASS** -- All database queries use parameterized SQLAlchemy/SQLModel constructs:
- `sql_backend.py:141`: `select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)` -- parameterized
- `_sql_backend_helpers.py:293-296`: `select(func.count(...)).where(col(...) < cutoff_date)` -- parameterized
- `query_builder.py:48-58`: All queries use SQLAlchemy ORM with bound parameters
- No string concatenation or f-string SQL anywhere in the modules

### 2.2 Credential Handling

**PASS for current code** -- The S3 and Prometheus backends are stubs and do not handle credentials yet. When implemented:
- `s3_backend.py:53-58`: Takes `bucket_name`, `prefix`, `region` -- no AWS credentials stored in code. Future implementation should use IAM roles or environment variables, never hardcoded keys.
- `prometheus_backend.py:43`: Takes `push_gateway_url` only -- no auth tokens. Future implementation should support token-based auth.

### 2.3 Data Leakage

**LOW RISK** -- The SQL backend stores full prompt/response text in `LLMCall` records (`sql_backend.py:345-346`). The observability sanitization module (out of scope) should filter these before storage. The OTel backend correctly skips large data: `set_stage_output` at `otel_backend.py:562-567` is a deliberate no-op to avoid putting large payloads in spans.

### 2.4 Error Messages in Logs

**WARNING** -- Several places use f-strings in log messages that include user-controlled data:
- `_sql_backend_helpers.py:221`: `f"Foreign key violation: stage {data.stage_id} not found..."` -- stage_id is system-generated, low risk
- `_sql_backend_helpers.py:252`: `f"Tracked collaboration event {event_id}: type={data.event_type}..."` -- event_type comes from internal code

These are acceptable since the values are system-generated IDs, not user input.

---

## 3. Error Handling

### 3.1 Backend Failure Isolation (CompositeBackend)

**GOOD** -- The `CompositeBackend` correctly isolates secondary backend failures:
- `composite_backend.py:232-242`: `_fan_out` catches `Exception` (with `# noqa: BLE001`) and logs at WARNING
- `composite_backend.py:40-55`: `_afan_out` uses `asyncio.gather(*tasks, return_exceptions=True)` for async fan-out
- Primary errors propagate as expected (verified by `test_primary_error_propagates` in tests)

### 3.2 Broad Exception Catching

**WARNING** -- Several places use `except Exception` broadly:

| Location | Context | Risk |
|----------|---------|------|
| `otel_backend.py:113` | `_add_event` fire-and-forget | **Acceptable** -- documented as fire-and-forget |
| `otel_backend.py:211` | `_end_span` | **Acceptable** -- OTEL spans should never crash the app |
| `otel_backend.py:835,854` | `_cleanup_stale_spans` | **Acceptable** -- cleanup is best-effort |
| `aggregation/aggregator.py:94,152,209` | Aggregation methods | **ISSUE** -- catches all exceptions including `KeyboardInterrupt` (since `Exception` actually doesn't catch `KeyboardInterrupt`, this is OK). But the broad catch swallows legitimate errors like schema mismatches. Should catch `SQLAlchemyError` specifically. |
| `_sql_backend_helpers.py:878` | `record_error_fingerprint` | **OK** -- catches `(IntegrityError, SQLAlchemyError)` specifically |

### 3.3 Connection/Session Handling

**GOOD** -- The SQL backend uses per-operation sessions via `with get_session() as session:` pattern consistently. This avoids long-lived session state. The async session context (`sql_backend.py:418-438`) correctly wraps the sync CM lifecycle in `asyncio.to_thread`.

### 3.4 Missing Error Handling

**ISSUE** -- `sql_backend.py:282-315` (`set_agent_output`): imports `compute_quality_score` from `_quality_scorer` inside the method. If this import fails or `compute_quality_score` raises, the entire `set_agent_output` call fails silently (no try/except). The quality scoring should be wrapped in a try/except since it's non-critical.

---

## 4. Modularity

### 4.1 Backend Interface Consistency

**GOOD** -- All backends implement the `ObservabilityBackend` ABC from `backend.py`. The interface defines 13 abstract methods plus 2 optional methods (`record_error_fingerprint`, `get_top_errors`) with default no-op implementations.

The `ReadableBackendMixin` provides default empty implementations for read operations, which only the SQL backend overrides.

### 4.2 Mixin Decomposition

**GOOD** -- The mixin strategy is well-executed:
- `_AsyncBackendDefaults` -- default async-to-sync delegation via `asyncio.to_thread`
- `_OTelAsyncMixin` -- OTel-specific async (delegates to sync since OTEL is in-memory)
- `_NoOpAsyncMixin` -- pure `pass` async methods (avoids `to_thread` overhead)
- `_CompositeAsyncMixin` -- async fan-out to secondaries
- `SQLDelegatedMethodsMixin` -- thin wrappers delegating to module-level helpers

### 4.3 Dead Code

**MINOR** -- `sql_backend.py:500-503`: Comment at end of class lists methods "provided by SQLDelegatedMethodsMixin" -- this is documentation, not dead code. No actual dead code found.

### 4.4 Duplication

**MINOR ISSUE** -- `UUID_HEX_LENGTH = 12` is defined in both:
- `_sql_backend_helpers.py:48`
- `metric_creator.py:10`

Should be extracted to `temper_ai/observability/constants.py`.

**MINOR ISSUE** -- The `make_workflow_id()`, `make_stage_id()`, `make_agent_id()` helper functions are duplicated across 4 test files. Should be extracted to a test conftest or shared fixture module.

### 4.5 Stub Backend Code Smell

**OBSERVATION** -- S3 and Prometheus backends use `**kwargs` with `# type: ignore[override]` to avoid matching the exact abstract method signatures:
- `s3_backend.py:77`: `def track_workflow_start(self, workflow_id: str, workflow_name: str, **kwargs: Any) -> None:  # type: ignore[override]`
- `prometheus_backend.py:58`: Same pattern

This is acceptable for stubs but means they will silently accept incorrect argument names. When implementing these for real, they should match the full abstract signatures.

---

## 5. Feature Completeness

### 5.1 Stub Implementations

**S3 Backend** (`s3_backend.py`): Entirely stub. Docstring references "M6 multi-backend support" which appears to have never been prioritized.
- Lines 1-13: Clearly marked as `STUB IMPLEMENTATION`
- `get_stats()` returns `"note": "M6 implementation pending"`
- No actual S3 integration code exists

**Prometheus Backend** (`prometheus_backend.py`): Entirely stub. Same M6 reference.
- Lines 1-12: Clearly marked as `STUB IMPLEMENTATION`
- `get_stats()` returns `"note": "M6 implementation pending"`
- No prometheus-client integration code exists

### 5.2 Incomplete `cleanup_old_records`

**ISSUE (Medium)** -- `_sql_backend_helpers.py:271-308`: The `cleanup_old_records` function:
1. Only counts and deletes `WorkflowExecution` records
2. Returns `counts` dict with keys for `stages`, `agents`, `llm_calls`, `tool_executions` but they are always `0`
3. Relies on CASCADE deletes from the DB schema to clean child records, but the counts are misleading

The function should either:
- Count all entity types before deletion, OR
- Document that only workflow count is returned and child counts are implicit via CASCADE

### 5.3 `percentile_cont` SQLite Incompatibility

**ISSUE (Medium)** -- `query_builder.py:54,134-135`: Uses `func.percentile_cont(...).within_group(...)` which is PostgreSQL-specific. This will fail with `OperationalError` on SQLite (used for dev/test).

```python
# query_builder.py:54
func.percentile_cont(PROB_NEAR_CERTAIN).within_group(
    WorkflowExecution.duration_seconds
).label("p95_duration")
```

**Fix:** Add a SQLite fallback or document that aggregation requires PostgreSQL. Alternatively, compute percentiles in Python for SQLite.

### 5.4 Missing OTel Backend Tests

**ISSUE (Medium)** -- There is no test file for `otel_backend.py`. The OTel backend is the most complex backend (903 lines) with span lifecycle management, cleanup, and metrics recording, yet has zero dedicated tests. This is a significant gap.

### 5.5 TODO/FIXME/HACK

None found in any of the scoped files. The stub backends clearly document their planned future work inline.

### 5.6 Missing `track_llm_iteration` / `track_cache_event` in interface

**OBSERVATION** -- `OTelBackend` defines `track_llm_iteration` (line 728) and `track_cache_event` (line 742) which are not part of the `ObservabilityBackend` abstract interface. This means these methods are OTel-specific and not available through the backend abstraction. If other backends need these, they should be added to the interface.

---

## 6. Test Quality

### 6.1 Test Coverage Summary

| Backend | Test File | Test Count | Coverage |
|---------|-----------|------------|----------|
| SQL | `test_sql_backend.py` | 20 tests | Good -- lifecycle, CRUD, buffering, errors |
| NoOp | `test_noop_backend.py` | 28 tests | Thorough -- null object pattern, perf |
| Composite | `test_composite_backend.py` | 10 tests | Good -- fan-out, isolation, read delegation |
| S3 | `test_s3_backend.py` | 18 tests | Thorough for stub -- init, logging, lifecycle |
| Prometheus | `test_prometheus_backend.py` | 18 tests | Thorough for stub -- init, logging, lifecycle |
| OTel | **NONE** | 0 | **GAP** -- no tests at all |
| Aggregation Orchestrator | **NONE** | 0 | **GAP** -- no tests for `aggregator.py` |
| MetricAggregator | `test_aggregation.py` | 20 tests | Good -- delegation, error resilience, edge cases |
| AggregationPeriod | `test_aggregation_period.py` | 8 tests | Thorough |
| TimeWindowCalculator | `test_aggregation_time_window.py` | 14 tests | Thorough -- edge cases, leap year |
| MetricRecordCreator | **NONE** | 0 | **GAP** |
| QueryBuilder | **NONE** | 0 | **GAP** -- most critical for correctness |

### 6.2 Missing Test Coverage

1. **OTel Backend** (`otel_backend.py`, 903 lines) -- **Critical gap**. Should test:
   - Span lifecycle (start/end)
   - Span parent-child relationships
   - Stale span cleanup (`_cleanup_stale_spans`)
   - Metrics recording
   - Error handling when OTEL SDK not installed
   - Active span registry memory management

2. **AggregationOrchestrator** (`aggregation/aggregator.py`) -- No tests. Should test:
   - `aggregate_workflow_metrics` with real DB data
   - `aggregate_agent_metrics` with real DB data
   - `aggregate_llm_metrics` with real DB data
   - `aggregate_all_metrics` composition
   - Error recovery (rollback behavior)

3. **QueryBuilder** (`aggregation/query_builder.py`) -- No tests. Should test:
   - Generated SQL correctness
   - Time window filtering
   - GROUP BY behavior
   - `percentile_cont` behavior (or SQLite fallback)

4. **MetricRecordCreator** (`aggregation/metric_creator.py`) -- No tests. Should test:
   - Metric ID generation
   - Conditional creation (skip when value is 0)
   - All metric types (workflow, agent, LLM)

### 6.3 Test Quality Issues

- `test_noop_backend.py:63`: Uses `datetime.utcnow()` (deprecated) instead of `datetime.now(timezone.utc)`. This appears throughout the NoOp, S3, and Prometheus test files.
- `test_sql_backend.py:17`: Imports `Dict` from `typing` (Python 3.9 style, unnecessary with modern Python)
- Good use of `pytest.approx` for duration assertions
- Good use of fixtures for backend initialization

---

## 7. Architectural Analysis

### 7.1 Backend Plugin Architecture

The backend plugin architecture is well-designed:

```
ObservabilityBackend (ABC)
  +-- _AsyncBackendDefaults (mixin: async-to-sync delegation)
  |
  +-- SQLObservabilityBackend (primary, with ReadableBackendMixin)
  +-- OTelBackend (secondary, in-memory spans + metrics)
  +-- CompositeBackend (fan-out: primary + N secondaries)
  +-- NoOpBackend (null object pattern)
  +-- S3ObservabilityBackend (stub)
  +-- PrometheusObservabilityBackend (stub)
```

This follows the **Strategy pattern** well. The `CompositeBackend` enables runtime composition of multiple backends (e.g., SQL primary + OTel secondary).

### 7.2 N+1 Query Elimination

**GOOD** -- `_sql_backend_helpers.py:545-568` (`read_get_workflow`) uses `selectinload` for eager loading:

```python
select(WorkflowExecution)
    .options(
        selectinload(WorkflowExecution.stages).options(
            selectinload(StageExecution.agents).options(
                selectinload(AgentExecution.llm_calls),
                selectinload(AgentExecution.tool_executions),
            ),
            selectinload(StageExecution.collaboration_events),
        )
    )
```

This reduces ~20-40 individual queries to ~5 batch queries. The `read_get_stage` function (line 586) still uses N+1 queries for agent children -- it could benefit from the same eager loading pattern.

### 7.3 Buffering Strategy

**GOOD** -- The SQL backend supports optional write buffering (`sql_backend.py:84-107`):
- `buffer=None` (default): Auto-creates buffer with defaults from constants
- `buffer=False`: Disables buffering (direct inserts)
- `buffer=<instance>`: Custom buffer

The buffer flush callback (`_flush_buffer`) performs batch INSERTs and batch UPDATEs, which is efficient for high-throughput scenarios.

### 7.4 Aggregation Pipeline

The aggregation pipeline is clean:
```
AggregationOrchestrator
  -> AggregationQueryBuilder (builds SQL)
  -> MetricRecordCreator (creates SystemMetric records)
  -> TimeWindowCalculator (calculates time ranges)
  -> AggregationPeriod (enum: MINUTE, HOUR, DAY)
```

However, the pipeline is tightly coupled to PostgreSQL due to `percentile_cont`. This limits the aggregation feature to production environments only.

### 7.5 OTel Span Memory Management

**GOOD** -- The OTel backend implements span lifecycle management to prevent memory leaks:
- `otel_backend.py:83-85`: Constants for TTL (1 hour), max spans (10000), cleanup threshold (100)
- `otel_backend.py:817-860`: `_cleanup_stale_spans` with two phases:
  1. TTL eviction (spans older than 1 hour)
  2. Capacity eviction (oldest first when exceeding 10000)
- Cleanup is amortized: only runs when span count > `CLEANUP_THRESHOLD` (100)

**ISSUE** -- The module-level import at `otel_backend.py:899-902` uses a try/except to handle missing OTEL:
```python
try:
    from opentelemetry import trace as otel_trace
except ImportError:
    otel_trace = None
```
But `_start_span` at line 181 uses `otel_trace.set_span_in_context(span)` unconditionally. If `otel_trace` is `None`, this will raise `AttributeError`. The class constructor already checks for OTEL availability (line 413-420), so the module-level import is redundant and potentially confusing. The function should either use the lazy import from the constructor or guard the usage.

---

## 8. Findings Summary

### Critical (0)

None.

### High (3)

| # | Location | Finding | Recommendation |
|---|----------|---------|----------------|
| H-1 | `query_builder.py:54,134-135` | `percentile_cont` is PostgreSQL-only; fails on SQLite | Add SQLite fallback or document requirement |
| H-2 | `otel_backend.py` | 903-line backend with zero test coverage | Create `tests/test_observability/backends/test_otel_backend.py` |
| H-3 | `otel_backend.py:181,899-902` | Module-level `otel_trace` may be None; `_start_span` uses it unconditionally | Guard usage or remove redundant module-level import |

### Medium (4)

| # | Location | Finding | Recommendation |
|---|----------|---------|----------------|
| M-1 | `_sql_backend_helpers.py:271-308` | `cleanup_old_records` only counts/deletes workflows; child counts always 0 | Count child records or document CASCADE behavior |
| M-2 | `sql_backend.py:287` | `compute_quality_score` import can fail; no error handling | Wrap in try/except with fallback |
| M-3 | `aggregation/aggregator.py:94,152,209` | Broad `except Exception` in aggregation methods | Catch `SQLAlchemyError` specifically |
| M-4 | `_sql_backend_helpers.py:586-631` | `read_get_stage` still uses N+1 queries | Use `selectinload` like `read_get_workflow` |

### Low (5)

| # | Location | Finding | Recommendation |
|---|----------|---------|----------------|
| L-1 | `otel_backend.py:480,558,607,767` | Magic number `256` for error message truncation | Extract to `MAX_OTEL_ERROR_LENGTH = 256` |
| L-2 | `_sql_backend_helpers.py:48`, `metric_creator.py:10` | `UUID_HEX_LENGTH = 12` duplicated | Move to `observability/constants.py` |
| L-3 | Test files | `make_workflow_id()` duplicated in 4+ test files | Extract to shared conftest |
| L-4 | NoOp/S3/Prometheus test files | Use deprecated `datetime.utcnow()` | Replace with `datetime.now(timezone.utc)` |
| L-5 | `otel_backend.py:728,742` | `track_llm_iteration`/`track_cache_event` not in ABC | Add to `ObservabilityBackend` interface or document as OTel-specific |

---

## 9. Test Gap Prioritization

| Priority | Test Target | Estimated Tests | Rationale |
|----------|------------|-----------------|-----------|
| P0 | OTel backend (`otel_backend.py`) | ~25 tests | Largest untested module (903 lines), complex span lifecycle |
| P1 | QueryBuilder (`query_builder.py`) | ~10 tests | Critical SQL correctness, percentile_cont compatibility |
| P1 | AggregationOrchestrator (`aggregator.py`) | ~12 tests | End-to-end aggregation pipeline |
| P2 | MetricRecordCreator (`metric_creator.py`) | ~15 tests | Metric creation correctness |
| P3 | Async methods on all backends | ~10 tests | Verify async delegation works correctly |

---

## 10. Files Reviewed

| File | Lines | Status |
|------|-------|--------|
| `temper_ai/observability/backend.py` | 745 | Interface -- clean |
| `temper_ai/observability/backends/otel_backend.py` | 903 | Needs tests; module-level import issue |
| `temper_ai/observability/backends/sql_backend.py` | 508 | Good; minor quality scorer error handling |
| `temper_ai/observability/backends/_sql_backend_helpers.py` | 1019 | Good; cleanup incomplete |
| `temper_ai/observability/backends/s3_backend.py` | 186 | Stub -- acceptable |
| `temper_ai/observability/backends/prometheus_backend.py` | 179 | Stub -- acceptable |
| `temper_ai/observability/backends/composite_backend.py` | 500 | Good design |
| `temper_ai/observability/backends/noop_backend.py` | 373 | Clean null object |
| `temper_ai/observability/aggregation/__init__.py` | 13 | Clean |
| `temper_ai/observability/aggregation/aggregator.py` | 245 | Needs tests; broad exception catch |
| `temper_ai/observability/aggregation/metric_creator.py` | 455 | Needs tests |
| `temper_ai/observability/aggregation/query_builder.py` | 141 | PostgreSQL-only issue |
| `temper_ai/observability/aggregation/time_window.py` | 59 | Clean |
| `temper_ai/observability/aggregation/period.py` | 10 | Clean |
| `temper_ai/observability/metric_aggregator.py` | 123 | Clean |
| `tests/test_observability/backends/test_sql_backend.py` | 1134 | Good coverage |
| `tests/test_observability/backends/test_composite_backend.py` | 157 | Good coverage |
| `tests/test_observability/backends/test_noop_backend.py` | 674 | Thorough |
| `tests/test_observability/backends/test_s3_backend.py` | 575 | Thorough for stub |
| `tests/test_observability/backends/test_prometheus_backend.py` | 518 | Thorough for stub |
| `tests/test_observability/test_aggregation.py` | 528 | Good MetricAggregator coverage |
| `tests/test_observability/test_aggregation_period.py` | 88 | Thorough |
| `tests/test_observability/test_aggregation_time_window.py` | 196 | Thorough |
