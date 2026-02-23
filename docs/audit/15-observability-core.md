# Audit 15: Observability Core

**Scope:** `temper_ai/observability/` core files -- tracker, backend interface, buffer, console, sanitization, types, formatters, event bus, hooks, database shim, migrations.

**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6 (automated)
**Status:** Complete

---

## Executive Summary

The observability core is a well-architected module that serves as the primary pillar of the framework. It provides pluggable backend abstraction, multi-layer data sanitization, write-buffering with dead-letter queue, a real-time event bus, and comprehensive execution tracking via context managers. The code demonstrates strong failure isolation -- tracking never crashes the workflow -- and security-conscious design with HMAC-keyed content hashing and recursive sanitization.

**Key findings:** 3 high-severity issues (unsanitized error messages in backend writes, medium-confidence secret redaction dead code, duplicate class name collision), 5 medium-severity issues, 8 low-severity issues. Overall quality is high but several security gaps need attention.

**Overall grade: B+ (85/100)**

---

## 1. Code Quality

### 1.1 Function Length (max 50 lines)

All functions are within the 50-line limit after the helper extraction. The decomposition into `_tracker_helpers.py` and `_buffer_helpers.py` was well executed.

| File | Longest Function | Lines | Status |
|------|-----------------|-------|--------|
| `tracker.py` | `track_workflow` | ~36 | PASS |
| `_tracker_helpers.py` | `sanitize_dict` | ~50 | PASS (borderline) |
| `buffer.py` | `buffer_llm_call` | ~39 | PASS |
| `_buffer_helpers.py` | `execute_flush` | ~44 | PASS |
| `console.py` | `_update_loop` | ~38 | PASS |
| `hooks.py` | `track_workflow` decorator body | ~21 | PASS |

### 1.2 Parameter Count (max 7)

| Issue | Location | Count | Severity |
|-------|----------|-------|----------|
| `execute_flush` | `_buffer_helpers.py:126-134` | 7 | Borderline -- exactly at limit |
| `move_to_dlq` | `_buffer_helpers.py:239-247` | 7 | Borderline -- exactly at limit |
| `WorkflowTrackingParams` | `tracker.py:87-103` | 13 fields | PASS (dataclass -- appropriate) |

No violations. Dataclasses are used correctly to bundle parameters.

### 1.3 Magic Numbers

No magic numbers found in scope. All numeric constants are properly extracted to `constants.py` or `shared/constants/`. The `THRESHOLD_MEDIUM_COUNT` for recursion depth, `DEFAULT_BUFFER_SIZE`, `MAX_RETRY_ATTEMPTS`, etc., are all well-named constants.

### 1.4 Naming

| Issue | Location | Detail |
|-------|----------|--------|
| **Duplicate class name** | `_tracker_helpers.py:125` and `backend.py:97` | Both define `CollaborationEventData` with different fields. Importing both in the same scope would shadow one. |
| `types.py` aliases | `types.py:9-17` | All type aliases are `dict[str, Any]` -- provides no type safety. These are effectively no-ops. |

### 1.5 Fan-Out

| File | Distinct Module Imports | Limit | Status |
|------|------------------------|-------|--------|
| `tracker.py` | 8 (observability internal) + 3 external | 8 external | PASS -- internal imports don't count |
| `_tracker_helpers.py` | 3 | 8 | PASS |
| `hooks.py` | 3 | 8 | PASS |
| `buffer.py` | 2 | 8 | PASS |

### 1.6 f-string Usage in Logging

Multiple f-string log messages found. These evaluate the f-string even when the log level is suppressed:

| File | Line(s) | Example |
|------|---------|---------|
| `_tracker_helpers.py` | 628, 670, 945 | `f"Failed to update agent merit score: {e}"` |
| `_buffer_helpers.py` | 51, 176-178, 188, 230-231, 254-255, 278-279, 287 | `f"Purged {len(stale)} stale pending IDs"` |

**Severity: LOW** -- Performance impact is negligible; these are in error/warning paths. However, the convention should use `logger.error("msg: %s", e)` format.

---

## 2. Security

### 2.1 CRITICAL: Unsanitized Error Messages Written to Backend

**Severity: HIGH**
**Location:** `_tracker_helpers.py:883, 977, 1032`

When workflow/stage/agent errors are tracked, the raw `str(error)` is passed directly to the backend without sanitization:

```python
# _tracker_helpers.py:883 (handle_workflow_error)
backend.track_workflow_end(
    ...
    error_message=str(error),  # UNSANITIZED
    error_stack_trace=get_stack_trace_fn(),  # Sanitized via DataSanitizer
)

# _tracker_helpers.py:977 (handle_stage_error)
backend.track_stage_end(
    ...
    error_message=str(error),  # UNSANITIZED
)

# _tracker_helpers.py:1032 (handle_agent_error)
backend.track_agent_end(
    ...
    error_message=str(error),  # UNSANITIZED
)
```

The stack trace is properly sanitized via `get_stack_trace_fn()`, but the error message itself is not. Exception messages can contain credentials, file paths, database URLs, or user data (e.g., `ConnectionError("Failed to connect to postgres://admin:secret@host/db")`).

**Similarly in event emission:** Lines 893, 988, 1045 emit `str(error)` to the event bus unsanitized.

**Fix:** Sanitize error messages via `sanitizer.sanitize_text(str(error), context="error")` before passing to backend and event bus.

### 2.2 MEDIUM: `_redact_secrets` Ignores `redact_medium_confidence_secrets` Config

**Severity: HIGH**
**Location:** `sanitization.py:263-287`

The `SanitizationConfig.redact_medium_confidence_secrets` flag (line 48) exists and defaults to `True`, but the `_redact_secrets` method never checks it. All patterns are treated identically under `redact_high_confidence_secrets`:

```python
# sanitization.py:273 - only checks high confidence
if self.config.redact_high_confidence_secrets:
    # ALL patterns redacted, regardless of confidence
```

There is no mechanism to classify patterns as "medium" vs "high" confidence. The `SECRET_PATTERNS` and `GENERIC_SECRET_PATTERNS` are merged without confidence metadata. This means:
- The `redact_medium_confidence_secrets` config flag is dead code
- Setting it to `False` has no effect
- Tests pass because they test the flag in isolation, not the actual behavior

**Fix:** Either implement confidence classification for secret patterns, or remove the `redact_medium_confidence_secrets` flag from `SanitizationConfig` to avoid misleading configuration.

### 2.3 Data Sanitization Strengths

The sanitization layer is otherwise solid:

- **HMAC content hashing** (`sanitization.py:236-241`) -- prevents rainbow table attacks on content hashes. Key sourced from `OBSERVABILITY_HMAC_KEY` env var or random generation.
- **Depth-limited recursion** (`_tracker_helpers.py:168`) -- prevents RecursionError via `THRESHOLD_MEDIUM_COUNT` depth limit.
- **Key sanitization** (`_tracker_helpers.py:175`) -- dictionary keys are sanitized too, not just values.
- **PII allowlist** (`sanitization.py:345-365`) -- pre-compiled patterns with ReDoS protection (`RecursionError`, `re.error` caught).
- **Non-serializable object handling** (`_tracker_helpers.py:202-208`) -- logged by type name only, value never exposed.

### 2.4 Event Bus Data Exposure

**Severity: LOW**
**Location:** `_tracker_helpers.py:296-314`

LLM call events include `prompt_result.sanitized_text` and `response_result.sanitized_text`, which are properly sanitized. Tool call events use `sanitized_input` and `sanitized_output`. The event bus itself does not persist data, so exposure is limited to in-process subscribers.

---

## 3. Error Handling & Failure Isolation

### 3.1 Tracker Never Crashes Workflow -- VERIFIED

Every tracking operation follows the principle that observability failures must never disrupt execution:

| Location | Pattern | Status |
|----------|---------|--------|
| `_tracker_helpers.py:756` | `_record_perf_for_llm` | `except Exception` with debug log |
| `_tracker_helpers.py:775` | `_record_perf_for_tool` | `except Exception` with debug log |
| `tracker.py:162-166` | `_record_perf_best_effort` | `except Exception` with debug log |
| `_tracker_helpers.py:840` | `_record_fingerprint_safe` | `except Exception` with debug log |
| `_tracker_helpers.py:866` | `_alert_new_error_type` | `except Exception` with debug log |
| `_tracker_helpers.py:1086` | `emit_llm_stream_chunk` | `except Exception: pass` |
| `event_bus.py:83` | `ObservabilityEventBus.emit` | Per-subscriber exception isolation |

All `except Exception` uses have proper `# noqa: BLE001` annotations explaining why broad catching is intentional.

### 3.2 Buffer Overflow Handling

**Location:** `buffer.py`, `_buffer_helpers.py`

The buffer design is robust:

- **Size-based flush** (`buffer.py:391-399`) -- flushes when total items exceed `flush_size`
- **Time-based flush** -- flushes when `flush_interval` elapsed
- **DLQ with bounded size** (`_buffer_helpers.py:272-274`) -- oldest entries dropped when `max_dlq_size` exceeded
- **Retry with max attempts** (`_buffer_helpers.py:224`) -- items moved to DLQ after `max_retries`
- **Pending ID deduplication** (`_buffer_helpers.py:78`) -- prevents double-insertion
- **Stale pending ID purge** (`_buffer_helpers.py:33-52`) -- cleans up stale entries after timeout

### 3.3 Async Event Bus Queue Full

**Severity: LOW**
**Location:** `event_bus.py:128-134`

When the async queue is full, events are silently dropped with a warning. This is acceptable for observability data (lossy is better than blocking), but there is no metric counter for dropped events. Adding a counter would aid debugging.

### 3.4 ExecutionHook Missing Traceback for Stage/Agent Errors

**Severity: MEDIUM**
**Location:** `hooks.py:410, 449`

```python
# hooks.py:410 (end_stage)
ctx.__exit__(type(error), error, None)  # Missing traceback!

# hooks.py:449 (end_agent)
ctx.__exit__(type(error), error, None)  # Missing traceback!
```

Compare with `end_workflow` at line 371 which correctly passes `error.__traceback__`. The stage and agent error paths lose the traceback, meaning stack traces won't be captured for these error cases.

**Fix:** Change both to `ctx.__exit__(type(error), error, error.__traceback__)`.

Similarly for async variants:
- `hooks.py:550` (`aend_stage`) -- passes `None` instead of `error.__traceback__`
- `hooks.py:570` (`aend_agent`) -- passes `None` instead of `error.__traceback__`

---

## 4. Modularity & Architecture

### 4.1 Backend Interface Design -- EXCELLENT

The `ObservabilityBackend` abstract class (`backend.py:334-744`) is well-designed:

- **Clean ABC** with 13 abstract methods covering the full lifecycle
- **Parameter bundling** via 8 `@dataclass` types (`WorkflowStartData`, `LLMCallData`, etc.)
- **Async defaults** via `_AsyncBackendDefaults` mixin that delegates to sync via `asyncio.to_thread`
- **Read API** via `ReadableBackendMixin` with safe empty defaults
- **Extensibility** -- `record_error_fingerprint`, `get_top_errors` have non-abstract defaults
- **Maintenance** -- `cleanup_old_records` and `get_stats` are abstract (enforced)

### 4.2 Mixin Strategy -- GOOD

The tracker uses three mixins to decompose a large class:

1. `_TrackerAsyncMixin` -- async tracking methods
2. `TrackerCollaborationMixin` -- collaboration, safety, merit methods
3. `ExecutionTracker` inherits both

This keeps the main class manageable. The TYPE_CHECKING-guarded attribute declarations in mixins (`tracker.py:280-300`) provide IDE support without runtime cost.

### 4.3 Buffer Design -- STRONG

The `ObservabilityBuffer` follows a clean separation:
- **Buffer** manages state and threading
- **Helpers** (`_buffer_helpers.py`) contain pure logic (flush, retry, merge, DLQ)
- **Callback injection** (`set_flush_callback`) decouples buffer from backend

### 4.4 `types.py` -- VESTIGIAL

**Severity: LOW**
**Location:** `types.py:1-17`

This file contains 9 type aliases, all mapped to `dict[str, Any]`. It provides zero type safety and appears to be a leftover from before the dataclass parameter bundles were introduced. The actual tracking code uses `LLMCallTrackingData`, `ToolCallTrackingData`, etc. from `_tracker_helpers.py`.

**Recommendation:** Deprecate or remove. No code in the core modules imports from `types.py`.

### 4.5 Duplicate `CollaborationEventData` Class

**Severity: MEDIUM**
**Location:** `_tracker_helpers.py:125` and `backend.py:97`

Two classes with the same name but different fields exist in different modules:

```python
# _tracker_helpers.py:125 -- 13 fields (event_type, stage_id, agents_involved,
#   event_data, round_number, resolution_strategy, outcome, confidence_score,
#   extra_metadata, stage_name, agents, decision, confidence, metadata)

# backend.py:97 -- 7 fields (event_data, round_number, resolution_strategy,
#   outcome, confidence_score, extra_metadata, timestamp)
```

This creates confusion. The `_tracker_helpers.py` version has redundant fields (`agents` overlaps `agents_involved`, `confidence` overlaps `confidence_score`, `metadata` overlaps `extra_metadata`).

**Fix:** Rename one (e.g., `CollaborationTrackingInput` for the helpers version) and remove the redundant fields.

---

## 5. Feature Completeness

### 5.1 TODO/FIXME/HACK Scan

No TODO, FIXME, HACK, or XXX markers found in any of the 13 audited files. All known issues have been addressed with `# OB-XX` reference comments.

### 5.2 Deprecation Shim (`database.py`)

**Location:** `database.py:1-20`

Clean deprecation shim with:
- `warnings.warn()` with `stacklevel=2`
- Re-export of all public API from `temper_ai.storage.database.manager`
- Private internals re-exported for backward compat (`_db_lock`, `_db_manager`, `_mask_database_url`)

Test coverage exists in `test_database_shim.py`.

### 5.3 Migration Utilities (`migrations.py`)

**Location:** `migrations.py:1-84`

Clean and minimal. Raw SQL migration functions removed per Alembic adoption. Remaining functions are straightforward schema management (`create_schema`, `drop_schema`, `reset_schema`, `check_schema_version`).

**Note:** `check_schema_version` (line 75) uses parameterized query via `text()` with `:limit` -- no SQL injection risk.

### 5.4 Console Visualization Completeness

The `console.py` provides three verbosity levels (minimal, standard, verbose) with:
- Tree-based workflow visualization
- Streaming polling via `StreamingVisualizer`
- Duration/cost/token formatting

No partial implementations detected.

### 5.5 Sampling Strategy Integration

**Location:** `tracker.py:253-274`

Sampling is properly integrated:
- Skip check occurs before any backend writes
- Skipped workflows still yield `workflow_id` for upstream code
- Context cleanup happens in `finally` block
- Lazy import of `SamplingContext` avoids fan-out

---

## 6. Test Quality

### 6.1 Test Coverage Map

| Source File | Test File(s) | Test Count | Coverage |
|------------|-------------|------------|----------|
| `tracker.py` | `test_tracker.py`, `test_async_tracker.py`, `test_tracker_thread_safety.py`, `test_tracker_sampling_perf.py`, `test_tracker_session_dedup.py` | ~40+ | GOOD |
| `_tracker_helpers.py` | Tested indirectly via `test_tracker.py`, `test_llm_sanitization.py` | ~20+ | MEDIUM -- no direct unit tests for helper functions |
| `backend.py` | `test_backend.py` | ~10 | MEDIUM -- abstract interface testing only |
| `buffer.py` | `test_buffer.py`, `test_buffer_retry.py`, `test_buffer_lifecycle.py`, `test_buffer_integration.py` | ~30+ | GOOD |
| `_buffer_helpers.py` | `test_buffer_retry.py` (indirect) | ~9 | MEDIUM -- tested through buffer integration |
| `console.py` | `test_console.py`, `test_console_visualizer.py`, `test_console_streaming.py` | ~25+ | GOOD |
| `sanitization.py` | `test_sanitization_comprehensive.py`, `test_llm_sanitization.py`, `test_allowlist_pii_35.py` | ~35+ | GOOD |
| `event_bus.py` | `test_event_bus.py`, `test_async_event_bus.py` | ~25+ | GOOD |
| `hooks.py` | `test_hooks.py`, `test_async_hooks.py` | ~35+ | GOOD |
| `database.py` | `test_database_shim.py` | 2 | ADEQUATE (shim) |
| `migrations.py` | `test_migrations.py` | ~8 | ADEQUATE |
| `types.py` | None | 0 | GAP -- no tests (but file is vestigial) |
| `formatters.py` | `test_formatters.py`, `test_console.py` | ~12 | GOOD |
| `constants.py` | `test_constants.py` | ~5 | ADEQUATE |

### 6.2 Coverage Gaps

1. **`_tracker_helpers.py` helper functions** -- No direct unit tests for `sanitize_dict`, `get_stack_trace`, `_validate_llm_metrics`, `_fill_execution_ids`, `build_extra_metadata`, `_record_fingerprint_safe`, `_alert_new_error_type`. These are tested indirectly through integration tests but would benefit from targeted unit tests, especially for edge cases in `sanitize_dict` (e.g., deeply nested structures, non-serializable objects).

2. **`sanitization.py` `_redact_secrets` medium-confidence path** -- No test verifies that `redact_medium_confidence_secrets=False` actually prevents medium-confidence redactions (because the feature is dead code -- see finding 2.2).

3. **`event_bus.py` `AsyncObservabilityEventBus.stop(drain=False)`** -- The non-draining stop path may leave unprocessed events; no test covers this path.

4. **`hooks.py` `atrack_*` async decorators** -- Test file `test_async_hooks.py` exists but should verify traceback propagation (the bug identified in 3.4).

5. **Buffer DLQ overflow** -- No test verifies that `_max_dlq_size` enforcement drops oldest entries when exceeded.

---

## 7. Architectural Alignment

### 7.1 Vision Pillar: "Observability as Foundation"

The observability core strongly aligns with this pillar:

| Capability | Status | Notes |
|-----------|--------|-------|
| Pluggable backends | COMPLETE | ABC with 13 abstract methods + async defaults |
| Write buffering | COMPLETE | Batch inserts, DLQ, retry queue |
| Data sanitization | COMPLETE | Multi-layer (secrets, PII, truncation, HMAC) |
| Real-time event bus | COMPLETE | Sync + async variants with subscriber isolation |
| Context propagation | COMPLETE | ContextVar-based, thread/task safe |
| Performance tracking | COMPLETE | Best-effort, never blocks workflow |
| Error fingerprinting | COMPLETE | Integrated into error handlers |
| Console visualization | COMPLETE | 3 verbosity levels + streaming |
| Decorator hooks | COMPLETE | Sync + async variants |
| Sampling | COMPLETE | Skip backend writes for non-sampled workflows |

### 7.2 Gap: No Structured Logging Integration

The observability module uses standard Python `logging` but does not integrate with structured logging (e.g., JSON log format). All log messages use either f-strings or `%s` format. For production observability pipelines (ELK, Datadog, etc.), structured logging would improve query-ability.

### 7.3 Gap: No OpenTelemetry Span Propagation in Tracker

While `otel_setup.py` exists (out of scope), the core `tracker.py` does not create OTel spans. The tracker creates its own execution context but does not bridge to OTel's context propagation. This means distributed tracing across services would lose the observability hierarchy.

---

## 8. Issues Summary

### HIGH Severity (3)

| ID | File:Line | Issue | Fix |
|----|-----------|-------|-----|
| OBS-01 | `_tracker_helpers.py:883,977,1032` | Unsanitized `str(error)` written to backend and event bus | Sanitize error messages via `sanitizer.sanitize_text(str(error), context="error")` |
| OBS-02 | `sanitization.py:263-287` | `redact_medium_confidence_secrets` config flag is dead code; no confidence classification exists for patterns | Implement confidence classification or remove the misleading config flag |
| OBS-03 | `_tracker_helpers.py:125` vs `backend.py:97` | Duplicate `CollaborationEventData` class name with different fields | Rename one; remove redundant fields from helpers version |

### MEDIUM Severity (5)

| ID | File:Line | Issue | Fix |
|----|-----------|-------|-----|
| OBS-04 | `hooks.py:410,449,550,570` | `end_stage`/`end_agent` (sync+async) pass `None` instead of `error.__traceback__` | Pass `error.__traceback__` like `end_workflow` does |
| OBS-05 | `types.py:1-17` | Vestigial file with 9 `dict[str, Any]` aliases providing no type safety | Deprecate or remove |
| OBS-06 | `_tracker_helpers.py:125-141` | `CollaborationEventData` has redundant fields (`agents`/`agents_involved`, `confidence`/`confidence_score`, `metadata`/`extra_metadata`) | Remove redundant fields |
| OBS-07 | `_tracker_helpers.py` | No direct unit tests for extracted helper functions | Add targeted unit tests for `sanitize_dict` edge cases, `_validate_llm_metrics`, `_fill_execution_ids` |
| OBS-08 | `event_bus.py:128-134` | Async event bus drops events on queue full with no drop counter | Add an `_events_dropped` counter for monitoring |

### LOW Severity (8)

| ID | File:Line | Issue | Fix |
|----|-----------|-------|-----|
| OBS-09 | `_tracker_helpers.py:628,670,945` | f-string in `logger.error()` / `logger.warning()` | Use `%s` format |
| OBS-10 | `_buffer_helpers.py:51,176,188,230,254,278,287` | f-string in logging calls | Use `%s` format |
| OBS-11 | `console.py:438` | f-string in `logger.debug()` | Use `%s` format |
| OBS-12 | `sanitization.py:154` | f-string in `logger.warning()` | Use `%s` format |
| OBS-13 | `console.py:249-255` | `_format_duration` in `WorkflowVisualizer` duplicates `formatters.py:14-41` | Delegate to `formatters.format_duration` |
| OBS-14 | `console.py:218-236` | `_status_icon` duplicates `formatters.py:135-161` + `106-132` | Delegate to `formatters.status_to_icon` + `status_to_color` |
| OBS-15 | `buffer.py:244` | `defaultdict` with factory returning `AgentMetricUpdate(agent_id="")` -- the empty `agent_id` is overwritten but is technically incorrect at construction time | Use regular dict with explicit key check (already done at lines 319-320) |
| OBS-16 | No test for `_buffer_helpers.py:272-274` | DLQ overflow drop-oldest logic untested | Add test for DLQ size enforcement |

---

## 9. Positive Highlights

1. **Failure isolation is exemplary** -- Every tracking path catches exceptions without disrupting workflow execution. The `# noqa: BLE001` annotations explain the intentional broad catching.

2. **HMAC content hashing** (`sanitization.py:236-241`) -- Proper cryptographic approach to content correlation without enabling brute-force attacks.

3. **Depth-limited recursion** in `sanitize_dict` -- Prevents stack overflow on adversarial input.

4. **ContextVar-backed session stack** (`tracker.py:539-541`) -- Properly handles async task isolation.

5. **Buffer deduplication** (`_buffer_helpers.py:78-97`) -- Prevents double-insertion via pending ID tracking.

6. **Clean deprecation** of `database.py` -- Proper `warnings.warn()` with re-exports for backward compatibility.

7. **Parameter bundling via dataclasses** -- Consistent use throughout tracker, buffer, and backend interfaces.

8. **Subscriber exception isolation** in event bus (`event_bus.py:81-84`) -- One failing subscriber never prevents others from receiving events.

9. **DLQ with bounded size** and configurable callbacks -- Production-ready buffer overflow handling.

10. **Double-check locking** for global tracker singleton (`hooks.py:52-55`) -- Thread-safe lazy initialization.

---

## 10. Recommendations Priority

### Immediate (before v1.0)

1. **OBS-01**: Sanitize error messages before backend storage -- security risk of credential leakage in exception messages.
2. **OBS-04**: Fix missing traceback propagation in `end_stage`/`end_agent` hooks -- functional correctness.

### Short-term (next sprint)

3. **OBS-02**: Resolve the medium-confidence secret redaction dead code -- remove the misleading config flag or implement the feature.
4. **OBS-03/OBS-06**: Resolve duplicate `CollaborationEventData` naming collision and redundant fields.
5. **OBS-07**: Add direct unit tests for `_tracker_helpers.py` helper functions.

### Backlog

6. **OBS-05**: Deprecate `types.py`.
7. **OBS-08**: Add dropped-event counter to async event bus.
8. **OBS-09 through OBS-12**: Convert f-string logging to `%s` format.
9. **OBS-13/OBS-14**: DRY up console.py by delegating to formatters.py.
10. **OBS-16**: Add DLQ overflow test.
