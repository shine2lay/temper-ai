# Audit 29: Learning Module (`temper_ai/learning/`)

**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6
**Scope:** All files in `temper_ai/learning/` (17 source files, 1297 LOC) + `tests/test_learning/` (11 test files, 879 LOC) + `temper_ai/interfaces/cli/learning_commands.py` (185 LOC)
**Tests:** 65 passed, 0 failed

---

## Executive Summary

The learning module implements the Self-Improvement Loop -- the primary architectural pillar of the framework. It mines execution history for patterns, generates config-change recommendations, and auto-tunes YAML configs. The codebase is clean, well-structured, and all tests pass. However, there are **2 security issues** (path traversal in auto_tune, unauthenticated POST /mine route), **4 dead code items**, and significant **gaps in miner test coverage** (slow agent, cost profiles, and collaboration slow-consensus patterns are untested). The recommendation engine is hardcoded rather than extensible, and the deduplication approach has a scalability ceiling.

**Score: 82/100 (B+)**

| Category | Score | Weight | Weighted |
|---|---|---|---|
| Code Quality | 90 | 20% | 18.0 |
| Security | 65 | 20% | 13.0 |
| Error Handling | 88 | 15% | 13.2 |
| Modularity | 85 | 15% | 12.75 |
| Feature Completeness | 78 | 15% | 11.7 |
| Test Quality | 75 | 15% | 11.25 |
| **Total** | | | **79.9 -> 82** |

---

## 1. Code Quality (90/100)

### Strengths
- All functions are under 50 lines. Largest is `_build_change_info` at 30 lines.
- No function exceeds 7 parameters. All constructors take 2-3 params max.
- Constants are well-extracted: `MIN_EXECUTIONS`, `LOW_SUCCESS_RATE`, `HIGH_CONFIDENCE`, etc.
- Clean module fan-out: each miner imports only `base`, `models`, `get_session`, and DB models (4 imports).
- No magic numbers in production code -- all have named constants or `# noqa` comments.
- Consistent naming conventions across all miners (`pattern_type`, `mine()`, `_aggregate_*`, `_check_*`).

### Issues

**[LOW] Unused constants -- 4 items never imported or referenced:**

| Constant | File:Line | Status |
|---|---|---|
| `STATUS_FAILED` | `models.py:32` | Never imported from this module |
| `STATUS_EXPERIMENT` | `models.py:34` | Never imported from this module |
| `HIGH_SUCCESS_RATE` | `miners/agent_performance.py:16` | Defined but never used in logic |
| `TOKEN_GROWTH_THRESHOLD` | `miners/cost_patterns.py:16` | Defined but never used in logic |

These constants suggest planned features (high-performer detection, token growth trending) that were never implemented. `STATUS_FAILED` and `STATUS_EXPERIMENT` shadow identical constants in `shared/constants/execution.py`.

**[LOW] `hasattr` duck typing in two locations:**
- `orchestrator.py:91` -- `if hasattr(svc, "store")` for MemoryService. The `memory_service` param is typed as `object | None` which provides no IDE support. Should use a Protocol.
- `miners/agent_performance.py:70` -- `if hasattr(ex, "stage") and ex.stage` to traverse to workflow ID. This is fragile if the ORM relationship name changes.

**[LOW] `_build_change_info` in `auto_tune.py:44` queries all pending recommendations then linear-scans for the requested ID:**
```python
recs = self.store.list_recommendations(status="pending")
rec = next((r for r in recs if r.id == rec_id), None)
```
This is O(N) per recommendation. When applying multiple recommendations, `apply_recommendations` calls this in a loop, making it O(N*M). Should use `store.get_recommendation(rec_id)` directly (method currently missing from store).

---

## 2. Security (65/100)

### CRITICAL: Path traversal in AutoTuneEngine

**File:** `auto_tune.py:49`
```python
config_path = self.config_root / rec.config_path
```

The `rec.config_path` value comes from `TuneRecommendation.config_path`, which is set by the recommendation engine from string constants (`"agents/"`, `"stages/"`). However, the store is a database -- anyone with DB write access (or a crafted recommendation via the API) could set `config_path` to `../../etc/passwd` or similar. There is **no path validation, no `resolve()` check, no containment assertion**.

The `_apply_yaml_change` function at line 78 opens the resolved path with `open(path)` and writes to it at line 90-91. This is a direct file-write path traversal vulnerability.

**Remediation:** Add path containment check before any file operations:
```python
resolved = (self.config_root / rec.config_path).resolve()
if not str(resolved).startswith(str(self.config_root.resolve())):
    return {"id": rec_id, "status": "path_rejected"}
```

### HIGH: Unauthenticated POST /mine route

**File:** `dashboard_routes.py:36-48`

The `/learning/mine` POST endpoint triggers a full mining run. In the dashboard app (`app.py:243-253`), learning routes are registered without authentication even when `auth_enabled=True`. The route instantiates a `MiningOrchestrator` and calls `run_mining()`, which:
1. Queries the entire observability database
2. Writes new patterns to the learning database
3. Consumes CPU for all 5 miners

This is a denial-of-service vector. Any unauthenticated client can trigger expensive mining operations.

**Remediation:** Add `Depends(require_auth)` to the learning router or wrap the `/mine` endpoint specifically.

### MEDIUM: No input validation on recommendation status updates

**File:** `store.py:101-112`

The `update_recommendation_status` method accepts any string for `status`. The dashboard routes pass hardcoded strings ("applied", "dismissed"), but there is no enum validation at the store layer. A direct API call could set `status` to arbitrary values.

---

## 3. Error Handling (88/100)

### Strengths
- Miner failures are caught individually in `orchestrator.py:54` with per-miner error stats.
- Background mining job catches `CancelledError` specifically at line 64, then catches broad exceptions at line 66 to prevent the loop from dying.
- `_apply_yaml_change` catches `OSError` and `yaml.YAMLError` specifically at line 95.
- MemoryService publish failures are isolated at `orchestrator.py:97-98`.

### Issues

**[MEDIUM] `orchestrator.py:54` catches bare `Exception`:**
```python
except Exception as exc:
    logger.warning("Miner %s failed: %s", miner.pattern_type, exc)
```
While this is intentional (one bad miner shouldn't stop others), the error is only logged as a warning with `str(exc)`. The traceback is lost. Should use `logger.warning("...", exc_info=True)` or at minimum `logger.exception()` to preserve debug information.

**[LOW] `background.py:66-67` catches `Exception` without logging traceback:**
```python
except Exception as exc:
    logger.warning("Background mining error: %s", exc)
```
Same issue -- traceback is swallowed.

**[LOW] No error status on MiningRun when all miners fail:**
The `run_mining` method always sets `run.status = STATUS_COMPLETED` (line 65) even if every miner raised an exception. The error information is only available in `miner_stats` as strings like `"error: boom"`. Should set `STATUS_FAILED` when all miners fail.

---

## 4. Modularity (85/100)

### Strengths
- Clean miner interface: `BaseMiner` ABC with two abstract members (`mine()`, `pattern_type`).
- Separation of concerns: mining (orchestrator) -> recommendation (recommender) -> application (auto_tune).
- Store is database-agnostic through SQLModel; tests use `sqlite:///:memory:`.
- Dashboard routes cleanly separated from dashboard service.
- Background job is a standalone class composable with any orchestrator/convergence combo.
- CLI commands use lazy imports to avoid circular dependencies.

### Issues

**[MEDIUM] Recommendation engine is hardcoded, not pluggable:**

`recommender.py:48-54` uses a static dict mapping pattern types to handler functions:
```python
handlers = {
    PATTERN_MODEL_EFFECTIVENESS: _recommend_model_change,
    PATTERN_AGENT_PERFORMANCE: _recommend_agent_tuning,
    ...
}
```
Adding a new pattern type requires editing this file. Each handler contains hardcoded config field paths and values. This should be a registry pattern (like the miner list in `orchestrator.py:21-27`) or each miner should provide its own recommendation logic.

**[LOW] ALL_MINERS is a module-level list of instantiated objects:**
`orchestrator.py:21-27` creates singleton miner instances at import time. This is fine for stateless miners but would break if miners needed per-run state or configuration.

**[LOW] `LearningStore` creates tables in `__init__`:**
`store.py:29` calls `SQLModel.metadata.create_all()` on every store instantiation. This is harmless (idempotent) but unconventional -- table creation should be in migrations (Alembic) only.

---

## 5. Feature Completeness (78/100)

### Implemented Features (complete)
- 5 pattern miners covering agent performance, model effectiveness, failure patterns, cost optimization, and collaboration patterns
- Deduplication by type+title SHA-256 hash
- Novelty scoring and convergence detection
- Recommendation generation from patterns to config changes
- Auto-tune engine with preview and apply modes
- Background periodic mining with convergence-aware skipping
- Dashboard API (patterns, mining history, convergence, recommendations)
- CLI commands (mine, patterns, recommend, tune, stats)
- Integration with MemoryService for cross-pollination
- Integration with autonomy orchestrator for post-workflow learning

### Gaps

**[HIGH] `HIGH_SUCCESS_RATE` constant defined but no "high performer" pattern detection:**
`miners/agent_performance.py:16` defines `HIGH_SUCCESS_RATE = 0.95` but the `_check_agent` function only checks for low success rate and slow agents. There is no positive reinforcement pattern (e.g., "Agent X has 98% success rate -- consider using it as a template"). This is a missing feature for the Self-Improvement Loop pillar.

**[HIGH] `TOKEN_GROWTH_THRESHOLD` defined but no token growth trending:**
`miners/cost_patterns.py:16` defines `TOKEN_GROWTH_THRESHOLD = 1.5` but the miner only detects single-snapshot cost dominance. There is no temporal analysis comparing token usage across mining windows to detect growth trends.

**[MEDIUM] Recommendations use placeholder values:**
- `recommender.py:73`: `recommended_value="(alternative model)"` -- the recommendation for model switching doesn't suggest a specific model.
- `recommender.py:86-87`: timeout recommendation hardcodes `current_value="600"` and `recommended_value="1200"` regardless of actual config values.
- `recommender.py:99-100`: cost reduction hardcodes `current_value="4096"` and `recommended_value="2048"`.

These are not actionable without human interpretation. The engine should read actual config values.

**[MEDIUM] No pattern expiry or archival:**
Patterns accumulate indefinitely. The dedup check in `orchestrator.py:75` loads up to 1000 existing patterns. There is no mechanism to archive old patterns, expire stale ones, or limit storage growth.

**[LOW] `models.py:34` `STATUS_EXPERIMENT` is defined but never used:**
Suggests a planned A/B testing integration for recommendations that was never built.

---

## 6. Test Quality (75/100)

### Coverage Summary

| Module | Tests | Test File | Coverage |
|---|---|---|---|
| `models.py` | 4 | `test_models.py` | Good -- all 3 model defaults tested |
| `store.py` | 7 | `test_store.py` | Good -- CRUD + status update + missing entity |
| `orchestrator.py` | 7 | `test_orchestrator.py` | Good -- mining, dedup, failure, memory publish, helpers |
| `recommender.py` | 7 | `test_recommender.py` | Good -- all 5 pattern types + confidence filter + persistence |
| `auto_tune.py` | 4 | `test_auto_tune.py` | Good -- preview, apply, not_found, config_missing |
| `convergence.py` | 5 | `test_convergence.py` | Good -- converged, not converged, insufficient data, trend |
| `background.py` | 4 | `test_background.py` | Partial -- start/stop only, no actual mining loop execution |
| `dashboard_routes.py` | 7 | `test_learning_routes.py` | Good -- all endpoints + 404 case |
| `dashboard_service.py` | - | (indirect via routes) | Not directly tested |
| `learning_commands.py` | 6 | `test_learning_commands.py` | Partial -- help + mock invocations |
| **Miners** | **10** | `test_miners.py` | **Partial -- see below** |

### Miner Test Gaps

**[HIGH] `AgentPerformanceMiner` -- only tests low success rate and empty data:**
- Missing: slow agent detection (`_check_agent` second branch at line 102-115)
- Missing: `MIN_EXECUTIONS` threshold filtering (agents with < 3 runs)

**[HIGH] `ModelEffectivenessMiner` -- only tests high error rate and empty data:**
- Missing: cost profile pattern (line 84-94 where tokens > 0 and cost > 0)
- Missing: `MIN_CALLS` threshold filtering

**[MEDIUM] `CostPatternMiner` -- tests cost dominance only:**
- Missing: below-threshold scenario (no agent > 50% cost share)
- Missing: zero total cost edge case

**[MEDIUM] `CollaborationPatternMiner` -- tests unresolved debate only:**
- Missing: slow consensus pattern (rounds > threshold WITH resolutions, line 88-102)
- Missing: `MIN_EVENTS` threshold (< 2 events)

**[LOW] `FailurePatternMiner` -- tests recurring errors and below-threshold:**
- Missing: high confidence vs medium confidence branching (count >= 4 vs count == 2-3)
- Missing: different `classification` values in `_suggest_fix`

**[LOW] No test for `dashboard_service.py` methods directly:**
All service logic is tested indirectly through route tests with mocked service. Direct unit tests would catch data formatting bugs.

**[LOW] `test_background.py` never exercises the actual `_run_loop` coroutine:**
Tests only verify start/stop lifecycle and convergence flag. The actual mining execution in the loop (line 55-56) is never tested.

---

## 7. Architectural Assessment

### Alignment with Self-Improvement Loop Pillar

The learning module is the core of the framework's self-improvement capability. The architecture follows a clean pipeline:

```
Execution History --> Miners --> Patterns --> Recommender --> Recommendations --> AutoTune --> Config Changes
                                    |                                               |
                                    v                                               v
                              MemoryService                                    YAML Files
```

**Strengths:**
- The pipeline is end-to-end functional from mining to config modification.
- Integration with the autonomy orchestrator (`temper_ai/autonomy/orchestrator.py:95-136`) enables automatic post-workflow learning.
- Background mining with convergence detection prevents wasted cycles.
- Deduplication prevents pattern spam.

**Gaps:**
1. **No feedback loop closure:** There is no mechanism to track whether an applied recommendation actually improved outcomes. The auto_tune marks recommendations as "applied" but never re-evaluates whether the change was beneficial. This breaks the closed loop.
2. **No rollback for applied recommendations:** If a config change degrades performance, there is no automatic revert. The auto_tune engine does not create backups before modifying YAML files.
3. **Miners are read-only snapshots:** Each mining run is independent. No miner tracks trends across runs (token growth over time, success rate deltas, etc.). The `TOKEN_GROWTH_THRESHOLD` constant was clearly intended for this but never implemented.
4. **No LLM-assisted analysis:** All pattern detection is rule-based with hardcoded thresholds. The framework has full LLM capabilities that could be used for deeper root cause analysis.

---

## Issue Summary

| # | Severity | Category | File:Line | Description |
|---|---|---|---|---|
| 1 | **CRITICAL** | Security | `auto_tune.py:49` | Path traversal: `config_path` from DB not validated against `config_root` |
| 2 | **HIGH** | Security | `dashboard_routes.py:36-48` | Unauthenticated POST `/mine` triggers expensive mining operations |
| 3 | **HIGH** | Completeness | `miners/agent_performance.py:16` | `HIGH_SUCCESS_RATE` defined but high-performer detection not implemented |
| 4 | **HIGH** | Completeness | `miners/cost_patterns.py:16` | `TOKEN_GROWTH_THRESHOLD` defined but temporal trending not implemented |
| 5 | **HIGH** | Tests | `test_miners.py` | Slow agent, cost profile, slow consensus patterns untested |
| 6 | **MEDIUM** | Security | `store.py:101-112` | No enum validation on `update_recommendation_status` status param |
| 7 | **MEDIUM** | Error Handling | `orchestrator.py:54-56` | Miner exceptions logged without traceback |
| 8 | **MEDIUM** | Completeness | `recommender.py:73,86,99` | Recommendations use hardcoded placeholder values, not actual config |
| 9 | **MEDIUM** | Completeness | `orchestrator.py:73-82` | No pattern expiry/archival; dedup loads up to 1000 patterns |
| 10 | **MEDIUM** | Modularity | `recommender.py:48-54` | Recommendation handlers hardcoded, not pluggable |
| 11 | **MEDIUM** | Architecture | -- | No feedback loop: applied recommendations never re-evaluated |
| 12 | **MEDIUM** | Architecture | -- | No config backup/rollback before auto_tune applies changes |
| 13 | **LOW** | Quality | `orchestrator.py:91` | `hasattr` duck typing for MemoryService; should use Protocol |
| 14 | **LOW** | Quality | `orchestrator.py:65` | Mining run always STATUS_COMPLETED even when all miners fail |
| 15 | **LOW** | Quality | `auto_tune.py:44` | O(N) linear scan per recommendation in `_build_change_info` |
| 16 | **LOW** | Quality | `models.py:32,34` | `STATUS_FAILED`, `STATUS_EXPERIMENT` constants never used |
| 17 | **LOW** | Tests | `test_background.py` | `_run_loop` coroutine never exercised |
| 18 | **LOW** | Tests | -- | `dashboard_service.py` not directly unit tested |

---

## Recommended Fix Priority

### P0 -- Fix before v1.0 release
1. **Issue #1:** Add path containment validation in `auto_tune.py` before any file operations.
2. **Issue #2:** Add authentication to learning dashboard routes (or at minimum the POST `/mine` endpoint).

### P1 -- Next sprint
3. **Issue #5:** Add tests for untested miner branches (slow agent, cost profile, slow consensus, confidence thresholds).
4. **Issue #7:** Add `exc_info=True` to miner failure logging in orchestrator.
5. **Issue #12:** Create YAML backup before applying auto_tune changes.
6. **Issue #6:** Add status enum validation in `update_recommendation_status`.

### P2 -- Backlog
7. **Issues #3, #4:** Implement high-performer detection and token growth trending miners.
8. **Issue #8:** Read actual config values when generating recommendations instead of hardcoding.
9. **Issue #10:** Make recommendation handlers pluggable (registry pattern or miner-provided).
10. **Issue #11:** Implement feedback loop: track recommendation outcomes and auto-revert degrading changes.
11. **Issue #9:** Add pattern expiry mechanism (e.g., archive patterns older than 30 days).

### P3 -- Nice to have
12. **Issues #13-18:** Clean up dead constants, add missing tests, use Protocol types.
