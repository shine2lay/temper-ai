# Audit Report 30: Lifecycle Module

**Module:** `temper_ai/lifecycle/`
**Files in scope:** 12 source files, 11 test files (105 tests)
**Date:** 2026-02-22
**Status:** All 105 tests passing (0.46s)

---

## Executive Summary

The lifecycle module implements self-modifying workflow configuration: it classifies
projects, matches adaptation profiles, applies structural transformation rules (skip,
add, reorder, modify stages), and monitors for quality degradation with automatic
rollback. The code is well-structured with clean separation of concerns. Key findings
include two new `create_engine` calls per `HistoryAnalyzer` query (connection leak
risk), a few `type: ignore` clusters in `profiles.py`, and missing test coverage for
the history analyzer's SQL query paths. No TODO/FIXME/HACK markers found anywhere in
the module.

**Overall quality: 88/100 (A)**

| Dimension            | Score | Notes                                      |
|----------------------|-------|--------------------------------------------|
| Code Quality         | 90    | Clean functions, good constants, minor nits |
| Security             | 85    | Parameterized SQL, but engine-per-call risk |
| Error Handling       | 92    | Consistent fail-open with logging           |
| Modularity           | 95    | Excellent layered design                    |
| Feature Completeness | 82    | No TODOs but some gaps vs vision            |
| Test Quality         | 85    | 105 tests, but SQL paths untested           |
| Architecture         | 88    | Good "Config as Product" support            |

---

## 1. Code Quality

### 1.1 Function Length and Complexity

All functions are within the 50-line limit. The longest functions:

| Function | File:Line | Lines | Assessment |
|----------|-----------|-------|------------|
| `_apply_add` | `adapter.py:354-389` | 35 | OK |
| `_apply_rules` | `adapter.py:286-321` | 35 | OK |
| `_record_adaptation` | `adapter.py:251-283` | 32 | OK |
| `adapt` | `adapter.py:57-87` | 30 | OK |
| `preview` (CLI) | `lifecycle_commands.py:154-217` | 63 | **EXCEEDS** 50-line limit |

**Finding [CQ-1] (Medium):** `preview` command in `lifecycle_commands.py:154-217` is 63
lines. Should extract the result display into a helper function.

### 1.2 Parameter Counts

All constructors and methods are within the 7-parameter limit. The most complex:

- `LifecycleAdapter.__init__`: 6 params (OK)
- `_record_adaptation`: 7 params (at limit)

### 1.3 Constants and Magic Numbers

**Good:** The module extracted all magic numbers into `constants.py`:
- `DEFAULT_LIST_LIMIT = 100` (line 13)
- `DEFAULT_LOOKBACK_HOURS = 720` (line 14)
- `DEFAULT_DEGRADATION_WINDOW = 10` (line 15)
- `DEFAULT_DEGRADATION_THRESHOLD = 0.05` (line 16)
- `TRUTHY_VALUES` (line 28)
- `COL_RUN_COUNT = 3` (line 31)

**Good:** `adapter.py` defines `UUID_HEX_LEN = 12` (line 26) and `MIN_STAGES_REQUIRED = 1`
(line 27) as module constants.

**Finding [CQ-2] (Low):** `adapter.py:223` and `adapter.py:226` use magic numbers `4` and
`2` with `# scanner: skip-magic` comments for autonomy level thresholds. These should be
named constants (e.g., `AUTONOMY_STRATEGIC = 4`, `AUTONOMY_RISK_GATED = 2`) for clarity.

### 1.4 Import Fan-Out

| File | Imports | Assessment |
|------|---------|------------|
| `adapter.py` | 7 (lifecycle internal + uuid, copy, logging) | OK |
| `store.py` | 5 | OK |
| `profiles.py` | 4 | OK |
| `dashboard_routes.py` | 2 (lazy imports inside handlers) | OK |

All files are within the 8-import fan-out limit.

### 1.5 Naming

All classes, functions, and variables follow Python naming conventions consistently.
No naming collisions detected across modules.

### 1.6 Type Annotations

**Finding [CQ-3] (Medium):** `profiles.py:152-166` (`_record_to_profile`) uses
`record: object` as the parameter type with 10 `# type: ignore[attr-defined]` markers.
This should use the actual `LifecycleProfileRecord` type or a Protocol to avoid
suppressing type safety:

```python
# profiles.py:152
def _record_to_profile(record: object) -> LifecycleProfile:
    rules = [AdaptationRule(**r) for r in getattr(record, "rules", [])]
    return LifecycleProfile(
        name=record.name,  # type: ignore[attr-defined]
        ...
    )
```

The parameter type should be `LifecycleProfileRecord` directly since it is already
imported in the same file (line 17, via `LifecycleStore` which imports it).

**Finding [CQ-4] (Low):** `experiment.py:24` and `adapter.py:47-48` use `Any` for
`experiment_service` and `autonomy_manager` parameters. These are cross-module
dependencies, so `Any` with lazy imports is acceptable to avoid fan-out, but a
`Protocol` would improve type safety.

---

## 2. Security

### 2.1 SQL Injection

**Good:** `history.py:87-101` and `history.py:134-147` use parameterized SQL via
`text(...).bindparams(wf=workflow_name, lookback=...)`. No f-string SQL.

**Finding [SEC-1] (Medium):** `history.py:99` builds the lookback string as
`f"-{lookback_hours} hours"`. While `lookback_hours` is an `int` parameter and this is
a bind parameter (not string interpolation into SQL), the SQLite `datetime('now', ...)`
function interprets the string. An attacker who controls `lookback_hours` with a
negative value could query future data (harmless but semantically wrong). The parameter
type constraint (`int`) makes actual injection impossible, but adding a bounds check
(e.g., `lookback_hours = max(1, lookback_hours)`) would be more defensive.

### 2.2 Engine Creation Pattern

**Finding [SEC-2] (High):** `history.py:85` and `history.py:132` each call
`create_engine(self._db_url, echo=False)` on every query invocation. This creates a
new connection pool per call, which:
1. Leaks engine resources if called frequently (no `engine.dispose()`)
2. Does not benefit from connection pooling
3. Contrasts with `store.py:21` which creates the engine once in `__init__`

The `HistoryAnalyzer` should create the engine once in `__init__` and reuse it, matching
the pattern in `LifecycleStore`.

### 2.3 Lifecycle Transition Validation

**Good:** `adapter.py:136-140` validates that adaptation doesn't remove all stages:
```python
if len(adapted_stages) < MIN_STAGES_REQUIRED:
    raise ValueError(
        f"Lifecycle adaptation would remove all stages (profile: {profile.name})"
    )
```

**Good:** Emergency stop integration (`adapter.py:461-476`) correctly fails-open
(proceeds if safety module is unavailable).

### 2.4 Autonomy Gate Safety

**Good:** `adapter.py:198-234` implements a layered autonomy gate:
1. No autonomy manager -> only non-approval profiles allowed
2. Min autonomy level check
3. Risk-based gating (CRITICAL risk needs level 4, learned profiles need level 2)
4. Exception fallback to `requires_approval` check

### 2.5 Jinja2 Sandboxing

**Good:** `adapter.py:296` uses `ImmutableSandboxedEnvironment()` for condition
evaluation, preventing SSTI attacks. The Jinja2 environment is created fresh per
`_apply_rules` call, which is correct for sandboxing.

### 2.6 YAML Loading

**Good:** `profiles.py:129` uses `yaml.safe_load(f)` (not `yaml.load`).
**Good:** `lifecycle_commands.py:323` and `lifecycle_commands.py:331` both use
`yaml.safe_load()`.

---

## 3. Error Handling

### 3.1 Consistent Fail-Open Pattern

The module consistently uses a fail-open pattern for optional subsystems:

| Location | Pattern | Assessment |
|----------|---------|------------|
| `adapter.py:229` | Autonomy check failure -> `not profile.requires_approval` | Good |
| `adapter.py:280` | Store save failure -> log warning, continue | Good |
| `adapter.py:332` | Condition eval failure -> skip rule | Good |
| `adapter.py:461-476` | Emergency stop check -> proceed if unavailable | Good |
| `classifier.py:99` | LLM failure -> use defaults | Good |
| `history.py:39` | Stage metrics query failure -> empty dict | Good |
| `experiment.py:91` | Assignment failure -> None (no adaptation) | Good |
| `rollback.py:54` | Insufficient data -> None (no report) | Good |

All exception handlers use `# noqa: BLE001` annotations with explanatory comments.

### 3.2 Dashboard Routes

**Good:** All 4 dashboard handlers (`dashboard_routes.py:55-168`) catch exceptions
and return structured error responses with `{"error": str(exc)}` instead of propagating.

### 3.3 Edge Cases

**Finding [ERR-1] (Low):** `rollback.py:118-149` (`_compute_adapted_success_rate`)
accumulates `metrics.success_rate` (a 0-1 float) and divides by `measured` count. But
the function returns `total` (total adaptations) as `sample_size`, not `measured`. This
means `sample_size` may overstate the actual number of measured data points, potentially
misleading degradation reports.

```python
# rollback.py:149
return successes / measured, total  # <-- should this be `measured` not `total`?
```

---

## 4. Modularity

### 4.1 Architecture

The module follows an excellent layered architecture:

```
adapter.py (orchestrator)
  |-- classifier.py  (input classification)
  |-- profiles.py    (profile registry, YAML + DB merge)
  |-- store.py       (DB persistence)
  |-- history.py     (observability DB queries)
  |-- experiment.py  (A/B testing wrapper)
  |-- rollback.py    (degradation monitoring)
  |-- _schemas.py    (Pydantic models)
  |-- models.py      (SQLModel tables)
  |-- constants.py   (shared constants)
```

**Good:** Each file has a single, clear responsibility with minimal cross-coupling.

### 4.2 Interface Design

**Good:** `LifecycleAdapter` accepts all dependencies via constructor injection, making
it easy to test with mocks:
```python
def __init__(self, profile_registry, classifier, store=None,
             history_analyzer=None, experimenter=None, autonomy_manager=None)
```

**Good:** The adapter operates on raw dicts (`dict[str, Any]`), not Pydantic models,
so it works at the pre-compilation stage without needing validated schemas.

### 4.3 Dead Code

No dead code detected. All public functions/classes are referenced either by tests,
CLI commands, dashboard routes, or the runtime integration point
(`temper_ai/workflow/runtime.py:310-326`).

### 4.4 Separation of Concerns

**Good:** Clear separation between:
- Schema definitions (`_schemas.py` for Pydantic, `models.py` for SQLModel)
- Business logic (`adapter.py`, `classifier.py`, `rollback.py`)
- Persistence (`store.py`)
- Presentation (`lifecycle_commands.py`, `dashboard_routes.py`)

---

## 5. Feature Completeness

### 5.1 TODO/FIXME/HACK Markers

**None found.** The module is clean of incomplete markers.

### 5.2 Implemented Features

| Feature | Status | Quality |
|---------|--------|---------|
| Project classification (explicit + LLM) | Complete | Good |
| Profile registry (YAML + DB) | Complete | Good |
| Rule evaluation (Jinja2 sandboxed) | Complete | Good |
| 4 adaptation actions (skip, add, reorder, modify) | Complete | Good |
| Autonomy gate integration | Complete | Good |
| Emergency stop integration | Complete | Good |
| A/B experimentation wrapper | Complete | Good |
| Degradation monitoring + rollback | Complete | Good |
| Audit trail (adaptation records) | Complete | Good |
| CLI commands (6 subcommands) | Complete | Good |
| Dashboard API routes (4 endpoints) | Complete | Good |
| Deep-copy safety | Complete | Good |

### 5.3 Gaps vs Vision Pillars

**Finding [FC-1] (Medium):** **Self-Improvement gap.** The `rollback.py` module detects
degradation and can disable profiles, but there is no automatic feedback loop that:
1. Creates improved profiles based on degradation data
2. Adjusts rule conditions based on historical outcomes
3. Feeds back into the learning module (`temper_ai/learning/`)

The `_compute_adapted_success_rate` function relies on `workflow_name` being stored in
`characteristics`, but the `_record_adaptation` method in `adapter.py:267-277` stores
the full `chars.model_dump()` which does not include `workflow_name` (it is a
`ProjectCharacteristics` attribute, not a stored field). This means the rollback monitor
likely cannot extract workflow names from stored adaptations, making degradation detection
non-functional for real data.

**Finding [FC-2] (Low):** **Configuration as Product gap.** Profile versioning exists
(`version: str = "1.0"` in `_schemas.py:79` and `models.py:49`), but there is no
migration path when a profile version changes. No version comparison logic exists.

**Finding [FC-3] (Low):** The `_get_applied_rule_names` function (`adapter.py:450-458`)
is a crude approximation that returns ALL rule names if any change occurred, rather than
tracking which specific rules actually fired. This undermines audit trail accuracy.

```python
# adapter.py:456-458
def _get_applied_rule_names(rules, original_names, adapted_names):
    if original_names == adapted_names:
        return []
    return [r.name for r in rules]  # <-- returns ALL rules, not just applied ones
```

---

## 6. Test Quality

### 6.1 Coverage Summary

| Test File | Tests | Module Covered | Assessment |
|-----------|-------|----------------|------------|
| `test_schemas.py` | 11 | `_schemas.py` | Good |
| `test_adapter.py` | 18 | `adapter.py` | Good |
| `test_classifier.py` | 11 | `classifier.py` | Good |
| `test_profiles.py` | 10 | `profiles.py` | Good |
| `test_store.py` | 8 | `store.py` | Good |
| `test_rollback.py` | 7 | `rollback.py` | Adequate |
| `test_history.py` | 8 | `history.py` | **Gaps** |
| `test_experiment.py` | 11 | `experiment.py` | Good |
| `test_lifecycle_integration.py` | 4 | Integration | Good |
| `test_lifecycle_cli.py` | 5 | CLI | Adequate |
| **Total** | **105** | | |

### 6.2 Coverage Gaps

**Finding [TQ-1] (Medium):** `test_history.py` only tests the no-data and error paths.
The actual SQL query paths (`_query_stage_metrics` and `_query_workflow_metrics`) are
never tested with a populated database. All 8 tests verify empty/default returns. A test
should create the `stage_executions` and `workflow_executions` tables in an in-memory DB,
insert rows, and verify the aggregation logic.

**Finding [TQ-2] (Low):** `test_rollback.py` tests 7 scenarios but never exercises the
actual degradation detection path (where `check_degradation` returns a `DegradationReport`).
All tests result in `None` because the `HistoryAnalyzer` has no real DB. A test with mocked
`HistoryAnalyzer.get_workflow_metrics` returning degraded metrics is needed.

**Finding [TQ-3] (Low):** `dashboard_routes.py` has zero dedicated tests. It is tested
indirectly through CLI commands, but the 4 API handlers should have unit tests verifying
error response structure and metric aggregation logic.

**Finding [TQ-4] (Low):** No test covers the `LifecycleAdapter` with a
`LifecycleExperimenter` attached. The experiment code path in `adapter.py:106-115`
(`_resolve_profile`) is only tested via `test_experiment.py` in isolation.

### 6.3 Test Patterns

**Good:** Tests use `sqlite:///:memory:` databases, avoiding filesystem pollution.
**Good:** Tests use `tmp_path` fixtures for YAML profile files.
**Good:** Tests verify both happy paths and error/edge cases consistently.

---

## 7. File-by-File Details

### `_schemas.py` (139 lines)
- 3 enums: `ProjectSize`, `RiskLevel`, `AdaptationAction`
- 7 Pydantic models with proper Field validation
- Clean, no issues

### `constants.py` (34 lines)
- All magic numbers extracted
- `frozenset` for immutable TRUTHY_VALUES
- Clean

### `models.py` (63 lines)
- 2 SQLModel tables: `LifecycleAdaptation`, `LifecycleProfileRecord`
- Uses `utcnow()` for datetime defaults (correct pattern)
- JSON columns for complex fields
- Clean

### `adapter.py` (477 lines)
- Main orchestrator class `LifecycleAdapter` (235 lines in class)
- 6 private module functions for rule application
- **SEC-2**: Emergency stop creates new `EmergencyStopController()` each call (line 468)
- **FC-3**: `_get_applied_rule_names` returns all rules instead of tracking actually-applied ones

### `classifier.py` (175 lines)
- LLM-based classification with explicit fallback
- Proper markdown code fence stripping (line 166-168)
- Merge logic preserves explicit values over LLM (line 154-158)
- Clean

### `profiles.py` (167 lines)
- Dual-source registry (YAML + DB)
- YAML takes priority over DB (correct for "Config as Product")
- **CQ-3**: `_record_to_profile` uses `object` type with 10 type ignores

### `history.py` (163 lines)
- Raw SQL queries against observability DB
- **SEC-2**: Creates new engine per query call
- Proper parameterized queries
- Graceful fallback on missing tables

### `store.py` (102 lines)
- Standard SQLModel CRUD
- Creates tables on init (line 27)
- Clean, well-structured

### `experiment.py` (127 lines)
- Thin wrapper over ExperimentService
- Variant name resolution with fallback (lines 27-42)
- Best-effort tracking
- Clean

### `rollback.py` (170 lines)
- Degradation detection with configurable threshold
- Profile disable on detection
- **ERR-1**: Sample size reporting bug
- **FC-1**: Cannot extract workflow_name from stored characteristics

### `dashboard_routes.py` (169 lines)
- 4 GET endpoints
- Lazy imports in handlers (correct pattern for optional deps)
- Consistent error response structure
- **TQ-3**: No dedicated tests

### `lifecycle_commands.py` (332 lines)
- 6 CLI subcommands: profiles list/show, classify, preview, history, check
- Rich table output
- **CQ-1**: `preview` command exceeds 50-line limit

---

## 8. Summary of Findings

### High Priority
| ID | Finding | File:Line |
|----|---------|-----------|
| SEC-2 | `create_engine()` called per query in `HistoryAnalyzer` -- connection pool leak risk | `history.py:85,132` |

### Medium Priority
| ID | Finding | File:Line |
|----|---------|-----------|
| CQ-1 | `preview` CLI command exceeds 50-line function limit (63 lines) | `lifecycle_commands.py:154-217` |
| CQ-3 | `_record_to_profile` uses `object` type with 10 `type: ignore` markers | `profiles.py:152-166` |
| FC-1 | Rollback monitor cannot extract workflow_name from stored adaptation characteristics; degradation detection likely non-functional on real data | `rollback.py:138`, `adapter.py:271` |
| TQ-1 | History SQL query paths have zero test coverage | `test_history.py` |

### Low Priority
| ID | Finding | File:Line |
|----|---------|-----------|
| CQ-2 | Autonomy level thresholds use magic numbers with scanner skip | `adapter.py:223,226` |
| CQ-4 | `Any` types for cross-module deps (experiment_service, autonomy_manager) | `experiment.py:24`, `adapter.py:47-48` |
| ERR-1 | `_compute_adapted_success_rate` returns `total` as sample_size instead of `measured` | `rollback.py:149` |
| FC-2 | Profile versioning exists but has no migration/comparison logic | `_schemas.py:79`, `models.py:49` |
| FC-3 | `_get_applied_rule_names` returns all rule names, not just those that actually applied | `adapter.py:450-458` |
| TQ-2 | Rollback degradation detection path never tested (always returns None) | `test_rollback.py` |
| TQ-3 | Dashboard routes have no dedicated tests | `dashboard_routes.py` |
| TQ-4 | Adapter + experimenter integration path untested | `adapter.py:106-115` |
| SEC-1 | No lower-bound check on `lookback_hours` parameter | `history.py:99` |

---

## 9. Recommendations

### Immediate (High)
1. **Fix `HistoryAnalyzer` engine creation** -- Move `create_engine()` to `__init__` and
   store as `self._engine`, matching the `LifecycleStore` pattern. Dispose in a
   `close()` method or context manager.

### Short-term (Medium)
2. **Fix `_record_to_profile` typing** -- Change parameter type from `object` to
   `LifecycleProfileRecord` (already importable in the file).
3. **Store workflow_name in adaptation record** -- Either add `workflow_name` to
   `LifecycleAdaptation` model or include it in the `characteristics` dict during
   `_record_adaptation`.
4. **Add history SQL integration tests** -- Create `stage_executions` and
   `workflow_executions` tables in test setup and verify aggregation queries.
5. **Extract preview display logic** -- Split `preview` command into command handler
   + `_display_preview_diff()` helper.

### Long-term (Low)
6. **Track actually-applied rules** -- Refactor `_apply_rules` to return which rules
   fired alongside the adapted stages, instead of inferring from before/after comparison.
7. **Add dashboard route tests** -- 4 unit tests for the API handlers.
8. **Define autonomy level constants** -- Replace `4` and `2` with named constants in
   `constants.py`.
