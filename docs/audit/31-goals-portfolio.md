# Audit 31: Goals & Portfolio Modules

**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6
**Scope:** `temper_ai/goals/` (19 files), `temper_ai/portfolio/` (12 files), tests (22 files)
**Test Status:** 227/227 passing (0 failures)

---

## Executive Summary

Both modules are well-designed, following clean architecture principles with clear separation of concerns. The goals module implements a strategic goal proposal lifecycle (analyze -> propose -> review -> approve) with proper safety gates. The portfolio module implements multi-product orchestration with a WFQ scheduler, 4-metric optimizer, component analyzer, and knowledge graph. Code quality is high throughout, with proper use of constants, good error handling, and comprehensive test coverage. Five low-severity findings and two medium-severity findings were identified.

**Overall Rating: A (93/100)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 95 | Clean functions, good naming, constants extracted |
| Security | 92 | YAML safe_load, parameterized SQL, good validation |
| Error Handling | 90 | Graceful degradation, some broad exception catches |
| Modularity | 96 | Clean interfaces, proper ABC base, good separation |
| Feature Completeness | 90 | No TODOs, complete lifecycle, minor gaps noted |
| Test Quality | 95 | 227 tests, integration + unit, good edge cases |
| Architectural Alignment | 92 | Strong self-improvement pillar, good observability |

---

## 1. Code Quality

### 1.1 Strengths

- **Constants extracted properly**: Both modules use dedicated `constants.py` files with named constants for all thresholds, weights, limits, and magic numbers.
  - `/home/shinelay/meta-autonomous-framework/temper_ai/goals/constants.py` (66 lines, 28 constants)
  - `/home/shinelay/meta-autonomous-framework/temper_ai/portfolio/constants.py` (48 lines, 22 constants)

- **Function lengths**: All functions stay within the 50-line limit. Largest functions:
  - `_analyze_agent_costs()` in `goals/analyzers/cost.py:80-124` (44 lines) -- clean
  - `analyze_portfolio()` in `portfolio/component_analyzer.py:25-69` (44 lines) -- clean
  - `_compute_product_scorecard()` in `portfolio/optimizer.py:127-163` (36 lines) -- clean

- **Parameter counts**: All functions stay within the 7-parameter limit. Maximum is 5 parameters (`_make_cross_proposal` in `goals/analyzers/cross_product.py:132`).

- **Naming**: Consistent, descriptive naming throughout. Analyzer types return string identifiers. Schema types use clear enum names.

- **No dead code detected**: All imports are used, all functions are called or are part of public APIs.

### 1.2 Findings

**[LOW] F-01: Duplicate `PCT_MULTIPLIER` constant across analyzers**
- **Files:** `goals/analyzers/cost.py:27`, `goals/analyzers/cross_product.py:24`, `goals/analyzers/performance.py:28`, `goals/analyzers/reliability.py:27`, `portfolio/optimizer.py:32`
- All define `PCT_MULTIPLIER = 100` independently. Should be in `goals/constants.py` and `portfolio/constants.py` respectively.
- **Severity:** Low -- cosmetic, no functional impact

**[LOW] F-02: Duplicate `HALF_FACTOR` constant**
- **Files:** `goals/analyzers/performance.py:27`, `goals/analyzers/reliability.py:28`
- Both define `HALF_FACTOR = 0.5`. Could be in `goals/constants.py`.
- **Severity:** Low -- cosmetic

---

## 2. Security

### 2.1 Strengths

- **No SQL injection**: All database queries use SQLModel/SQLAlchemy parameterized queries via `select()`, `where()`, etc.
- **YAML safety**: All YAML loading uses `yaml.safe_load()`:
  - `portfolio/loader.py:57`
  - `portfolio/component_analyzer.py:148`
  - `portfolio/knowledge_graph.py:101`, `knowledge_graph.py:139`
- **No dangerous operations**: No `eval()`, `exec()`, `os.system()`, `shell=True`, `pickle`, or `yaml.load()`.
- **Goal safety policy**: Well-designed risk matrix with per-autonomy-level gates (`safety_policy.py:33-145`). Critical risk proposals always require human review.
- **Rate limiting**: Daily proposal limit (`MAX_PROPOSALS_PER_DAY = 20`), budget impact cap (`MAX_BUDGET_IMPACT_AUTO_USD = 10.0`), blast radius limit (`MAX_BLAST_RADIUS_AUTO = 5`).

### 2.2 Findings

**[MEDIUM] S-01: Dashboard routes lack input validation on `limit` query parameter**
- **File:** `/home/shinelay/meta-autonomous-framework/temper_ai/goals/dashboard_routes.py:49`
- **Detail:** The `get_proposals` endpoint accepts `limit: int = 50` directly from the query string with no upper bound. A user could pass `limit=1000000` causing expensive database scans.
- **Also affected:** `/home/shinelay/meta-autonomous-framework/temper_ai/portfolio/dashboard_routes.py` -- no limit validation on list endpoints.
- **Recommendation:** Add `limit = min(limit, MAX_LIMIT)` clamping, or use `Query(le=500)` FastAPI validation.

**[LOW] S-02: Blast radius parsing is simplistic**
- **File:** `/home/shinelay/meta-autonomous-framework/temper_ai/goals/safety_policy.py:80-82`
- **Detail:** Blast radius is counted by splitting on commas: `affected = len(blast.split(","))`. A crafted blast_radius string like `"a,,,,,"` would count as 6 items even though 5 are empty. This is low risk since blast_radius is system-generated, not user input.
- **Recommendation:** Filter empty strings: `affected = len([x for x in blast.split(",") if x.strip()])`.

---

## 3. Error Handling

### 3.1 Strengths

- **Analyzer isolation**: Each analyzer's failure is caught individually and logged without blocking other analyzers (`proposer.py:62-67`). This is excellent fault isolation.
- **Analysis orchestrator**: Catches exceptions during the full analysis cycle and records failure status (`analysis_orchestrator.py:54-56`).
- **Background job resilience**: The background analysis loop catches and logs errors without stopping (`background.py:60-61`).
- **Portfolio tracking**: Best-effort tracking that silently degrades if the observability tracker is unavailable (`_tracking.py:35-36`).

### 3.2 Findings

**[MEDIUM] E-01: Broad `except Exception` in critical paths**
- **Files:**
  - `goals/proposer.py:62` -- analyzer failure catch (acceptable -- resilience pattern)
  - `goals/analysis_orchestrator.py:54` -- orchestrator catch (acceptable -- records failure)
  - `goals/background.py:60` -- background loop catch (acceptable -- prevents crash)
  - `portfolio/loader.py:62` -- config parse catch (acceptable -- re-raises as ValueError)
  - `portfolio/_tracking.py:35` -- tracking catch (acceptable -- best-effort)
- **Assessment:** While all five uses are justified resilience patterns that log warnings and degrade gracefully, the `background.py:60` catch is the most concerning as it could silently swallow database connection errors that should trigger alerts. Consider distinguishing `asyncio.CancelledError` (already handled separately) from operational errors that should escalate.
- **Severity:** Medium -- the pattern is correct but the background job could mask persistent failures.
- **Recommendation:** Add a failure counter in `BackgroundAnalysisJob._run_loop()` that logs an ERROR after consecutive failures, enabling alerting.

---

## 4. Modularity

### 4.1 Strengths

- **Clean analyzer interface**: `BaseAnalyzer` ABC in `goals/analyzers/base.py` provides a minimal contract (2 abstract methods). All 4 analyzers implement it consistently.
- **Proper separation**: Schemas (`_schemas.py`) are separate from DB models (`models.py`) are separate from store (`store.py`). This allows clean layering.
- **Dashboard service layer**: Both modules have a `dashboard_service.py` that mediates between routes and store, keeping routes thin.
- **Observability integration**: Portfolio module uses a dedicated `_tracking.py` helper with lazy imports to avoid circular dependencies.
- **Lazy imports**: Both modules use lazy imports for cross-module dependencies (`goals/agent_goals.py:26`, `goals/proposer.py:149`, `portfolio/_tracking.py:23`).

### 4.2 Findings

**[LOW] M-01: `AgentGoalService` uses `source_product_type` as agent identifier instead of `source_agent_id`**
- **File:** `/home/shinelay/meta-autonomous-framework/temper_ai/goals/agent_goals.py:44-45`
- **Detail:** The `get_active_goals_for_agent()` method filters by `source_product_type == agent_id`, but the M9 schema added a dedicated `source_agent_id` field on `GoalProposalRecord` (`models.py:33`). The `propose_agent_goal()` method at line 72 also sets `source_product_type = agent_id` instead of using `source_agent_id`. The store already supports `agent_id` parameter in `list_proposals()` which filters on `source_agent_id` (`store.py:65`).
- **Impact:** The agent goal service works but stores agent identity in the wrong field, conflating product type with agent identity. If a product type and agent happen to share the same name, goal queries would return incorrect results.
- **Recommendation:** Update `AgentGoalService` to use `source_agent_id` instead of `source_product_type`.

**[LOW] M-02: `GoalReviewWorkflow` accepts but does not use `safety_policy`**
- **File:** `/home/shinelay/meta-autonomous-framework/temper_ai/goals/review_workflow.py:31-36`
- **Detail:** The constructor accepts an optional `safety_policy: GoalSafetyPolicy | None` parameter and stores it as `self._safety_policy`, but it is never referenced anywhere in the class. This is likely a planned integration point that was never wired in.
- **Recommendation:** Either integrate safety policy checks into the `review()` method (e.g., validate before applying transitions) or remove the parameter to avoid confusion.

---

## 5. Feature Completeness

### 5.1 Status

- **No TODOs/FIXMEs/HACKs found** in any file across both modules.
- **Complete lifecycle**: Both modules implement their full intended workflows:
  - Goals: analyze -> propose -> deduplicate -> score -> persist -> review -> approve/reject/defer
  - Portfolio: load config -> schedule (WFQ) -> record runs -> compute scorecards -> recommend -> optimize weights -> knowledge graph

### 5.2 Gaps

**[INFO] C-01: `GoalReview.defer_until` is stored but not enforced**
- **File:** `/home/shinelay/meta-autonomous-framework/temper_ai/goals/_schemas.py:111`
- **Detail:** `GoalReview` has a `defer_until: str | None` field, and the test validates it can be set (`test_schemas.py:126-127`), but no code checks whether a deferred proposal's deferral date has passed to automatically re-surface it.
- **Impact:** Low -- deferred proposals stay deferred until manually moved, which is acceptable for v1.

**[INFO] C-02: `PortfolioRecommendation.suggested_weight_delta` always defaults to 0.0**
- **File:** `/home/shinelay/meta-autonomous-framework/temper_ai/portfolio/_schemas.py:94`
- **Detail:** The `suggested_weight_delta` field exists on `PortfolioRecommendation` but is never populated by `PortfolioOptimizer.recommend()` (`optimizer.py:82-102`). The `optimize_weights()` method computes absolute weights but doesn't feed deltas into recommendations.
- **Impact:** Low -- weight optimization exists as a separate method; the delta field is just unused metadata.

---

## 6. Test Quality

### 6.1 Coverage Summary

| Module | Tests | Assertions | Coverage Areas |
|--------|-------|-----------|----------------|
| `test_goals/test_store.py` | 10 | 17 | CRUD, filtering, counting, ordering |
| `test_goals/test_proposer.py` | 10 | 13 | Generation, dedup, scoring, enrichment |
| `test_goals/test_safety_policy.py` | 13 | 18 | Validation, auto-approve matrix, budget |
| `test_goals/test_review_workflow.py` | 11 | 14 | Transitions, pending list, acceptance rate |
| `test_goals/test_analyzers.py` | 11 | 15 | All 4 analyzers, edge cases |
| `test_goals/test_analysis_orchestrator.py` | 5 | 6 | Run lifecycle, failure handling |
| `test_goals/test_agent_goals.py` | 9 | 15 | Agent goals, context formatting |
| `test_goals/test_schemas.py` | 8 | 16 | Schema validation, enums |
| `test_goals/test_background.py` | 4 | 5 | Async job lifecycle |
| `test_goals/test_goal_routes.py` | 5 | 8 | HTTP endpoints |
| `test_goals/test_goal_commands.py` | 6 | 8 | CLI commands |
| `test_portfolio/test_store.py` | 10 | 14 | All 7 entity types CRUD |
| `test_portfolio/test_scheduler.py` | 12 | 17 | WFQ, capacity, budget, fairness |
| `test_portfolio/test_optimizer.py` | 11 | 14 | Scorecards, recommendations, weights |
| `test_portfolio/test_component_analyzer.py` | 9 | 13 | Jaccard, matches, persistence |
| `test_portfolio/test_knowledge_graph.py` | 13 | 19 | Populator, BFS, paths, stats |
| `test_portfolio/test_loader.py` | 5 | 7 | YAML loading, validation |
| `test_portfolio/test_schemas.py` | 7 | 17 | All schema types |
| `test_portfolio/test_portfolio_integration.py` | 6 | 12 | End-to-end lifecycle |
| `test_portfolio/test_portfolio_cli.py` | 6 | 8 | CLI commands |

**Total: 227 tests, all passing.**

### 6.2 Strengths

- **Integration tests**: `test_portfolio_integration.py` covers full lifecycle (scheduler + optimizer + knowledge graph + component analysis).
- **Edge cases**: Tests cover empty portfolios, missing configs, budget exhaustion, WFQ fairness over 30 rounds, BFS depth limits, bidirectional paths.
- **Fixture isolation**: All tests use `sqlite:///:memory:` databases with fresh fixtures, preventing cross-test contamination.
- **Async coverage**: `test_background.py` tests the async background job start/stop lifecycle.
- **CLI coverage**: Both modules have CLI test suites testing the Click command interface.

### 6.3 Observations

- **No negative test for knowledge graph injection**: While the KG uses parameterized SQL, there's no test verifying that concept names with special characters (quotes, semicolons) are handled safely. This is mitigated by SQLModel/SQLAlchemy's parameterized queries.
- **No test for `PortfolioOptimizer.optimize_weights` with zero-score products**: The `optimize_weights()` method handles `total_score <= 0` by distributing equal weights, but no test covers this edge case.

---

## 7. Architectural Alignment

### 7.1 Self-Improvement Pillar

Both modules are core to the Self-Improvement vision pillar:

- **Goals module**: Implements autonomous goal proposal from execution data analysis. The 4 analyzers (performance, cost, reliability, cross-product) map directly to the system's ability to identify its own improvement opportunities.
- **Portfolio module**: The optimizer's invest/maintain/reduce/sunset recommendations enable strategic resource allocation across product types, directly supporting autonomous optimization.
- **Safety integration**: The goal safety policy's risk matrix and autonomy-level-gated auto-approve system aligns well with the graduated autonomy model.

### 7.2 Merit-Based Collaboration

- **Cross-product analyzer** (`goals/analyzers/cross_product.py`): Enables knowledge transfer between product types, supporting collaborative improvement.
- **Knowledge graph** (`portfolio/knowledge_graph.py`): Provides a queryable relationship model between products, stages, and agents, enabling merit-based component sharing.
- **Pattern enrichment** (`goals/proposer.py:143-169`): Cross-references goal proposals with learned patterns from the learning module.

### 7.3 Observability

- **Goals**: Analysis run records (`AnalysisRun` model) provide full audit trail of when analyses ran, how many proposals were generated, and any errors.
- **Portfolio**: Comprehensive tracking via `_tracking.py` -- every scheduler decision, optimizer computation, and knowledge graph operation is recorded through the observability tracker.

---

## 8. Finding Summary

| ID | Severity | Category | Description | File |
|----|----------|----------|-------------|------|
| F-01 | Low | Quality | Duplicate `PCT_MULTIPLIER` across 5 files | analyzers/*.py, optimizer.py |
| F-02 | Low | Quality | Duplicate `HALF_FACTOR` across 2 files | performance.py, reliability.py |
| S-01 | Medium | Security | No upper bound on `limit` query parameter | dashboard_routes.py (both) |
| S-02 | Low | Security | Simplistic blast radius parsing | safety_policy.py:80-82 |
| E-01 | Medium | Error | Background job could mask persistent failures | background.py:60 |
| M-01 | Low | Modularity | Agent goals use wrong field for agent identity | agent_goals.py:44,72 |
| M-02 | Low | Modularity | Unused `safety_policy` parameter in review workflow | review_workflow.py:31-36 |
| C-01 | Info | Feature | `defer_until` stored but not enforced | _schemas.py:111 |
| C-02 | Info | Feature | `suggested_weight_delta` never populated | _schemas.py:94, optimizer.py |

**Critical: 0 | Medium: 2 | Low: 5 | Info: 2**

---

## 9. Recommendations

### Priority 1 (Should Fix)

1. **S-01**: Add `limit` clamping on dashboard endpoints:
   ```python
   MAX_API_LIMIT = 500
   limit = min(limit, MAX_API_LIMIT)
   ```

2. **E-01**: Add consecutive failure tracking to `BackgroundAnalysisJob`:
   ```python
   if consecutive_failures > MAX_CONSECUTIVE_FAILURES:
       logger.error("Background analysis has failed %d times consecutively", consecutive_failures)
   ```

### Priority 2 (Should Fix When Convenient)

3. **M-01**: Update `AgentGoalService` to use `source_agent_id` instead of `source_product_type` for agent identity, and leverage `store.list_proposals(agent_id=...)` which already filters on the correct field.

4. **M-02**: Either wire `safety_policy` into `GoalReviewWorkflow.review()` or remove the parameter.

### Priority 3 (Nice to Have)

5. **F-01/F-02**: Extract shared constants (`PCT_MULTIPLIER`, `HALF_FACTOR`) to `goals/constants.py`.

6. **S-02**: Tighten blast radius parsing to filter empty segments.

7. **C-02**: Populate `suggested_weight_delta` in `PortfolioOptimizer.recommend()` or document it as reserved for future use.
