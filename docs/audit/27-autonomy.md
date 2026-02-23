# Audit 27: Autonomy Module (`temper_ai/autonomy/`)

**Auditor:** Claude Opus 4.6
**Date:** 2026-02-22
**Scope:** All 8 files in `temper_ai/autonomy/` (1,121 LOC) + 7 test files (141 tests)
**Verdict:** GOOD -- well-structured post-execution loop with solid isolation boundaries, but several architectural gaps and a dead-code subsystem

---

## Executive Summary

The `temper_ai/autonomy/` module implements the **post-execution autonomous loop** -- the mechanism that runs learning, goal analysis, feedback application, prompt optimization, memory sync, and portfolio scoring after each workflow completes. The orchestrator design is sound: each subsystem runs inside try/except with a global timeout budget, ensuring no single failure crashes the workflow. Code quality is high (no functions exceed 50 lines, no magic numbers, proper constants). However, the module has one dead subsystem (`rollout.py` is never imported outside tests), heavy reliance on untyped `object`/`Any` parameters, and the audit log has no rotation/size limit.

**Score: 81/100 (B+)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 88 | Clean, well-extracted; pervasive `Any`/`object` types hurt |
| Security | 78 | Good risk gating for goals; audit log has no size cap; no input validation on action strings |
| Error Handling | 92 | Excellent isolation per subsystem; timeout enforcement; graceful degradation |
| Modularity | 80 | Good separation; `rollout.py` is dead code; stores created inline |
| Feature Completeness | 72 | Rollout not wired; no async support; no concurrent subsystem execution |
| Test Quality | 85 | 141 tests, thorough edge coverage; no integration test with real stores |
| Arch Alignment | 75 | Pillar 1 (Progressive Autonomy) partially served; rollout/gradual adoption not integrated |

---

## 1. Code Quality

### 1.1 Strengths

- **Function length compliance.** Every function is under 50 lines. The longest is `_run_portfolio` at ~35 lines. Orchestrator subsystem methods are 20-30 lines each.
- **Constants properly extracted.** All magic numbers are in `constants.py`: `DEFAULT_LOOKBACK_HOURS = 24`, `LOOP_TIMEOUT_SECONDS = 300`, `MS_PER_SECOND = 1000`, rollout phase percentages.
- **Schema-first design.** `_schemas.py` defines `AutonomousLoopConfig`, `WorkflowRunContext`, `PostExecutionReport` as Pydantic models with sensible defaults.
- **Lazy imports.** All cross-module imports (learning, goals, portfolio, optimization, memory, registry) are deferred inside methods, keeping module fan-out at 2 (constants + _schemas).

### 1.2 Issues

**ISSUE-1: Pervasive `object` and `Any` type annotations (P2)**
Six `type: ignore[assignment]` casts in `feedback_applier.py` and extensive `Any` usage in `memory_bridge.py` and `rollout.py`. This defeats static analysis and IDE support.

| File | Line | Annotation |
|------|------|------------|
| `feedback_applier.py` | 27-28 | `learning_store: object`, `goal_store: object \| None` |
| `feedback_applier.py` | 51,83,127,163,200,211 | `# type: ignore[assignment]` casts |
| `memory_bridge.py` | 28-29 | `learning_store: Any`, `memory_service: Any \| None` |
| `memory_bridge.py` | 81,114,124 | `goal_store: Any`, `pattern: Any`, `proposal: Any` |
| `rollout.py` | 51 | `experiment_service: Any` |
| `orchestrator.py` | 272-273 | `optimizer: Any`, `report: Any` |

**Recommendation:** Use `Protocol` types or the actual base classes. For example, `feedback_applier.py` could accept `LearningStore` directly since it already imports it inside methods, or define a `LearningStoreProtocol` in `_schemas.py`.

**ISSUE-2: `orchestrator.py` `_run_subsystems` uses `getattr`/`setattr` dispatch (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/autonomy/orchestrator.py:70`:
```python
setattr(report, attr, getattr(self, method_name)(context, report))
```
This is a string-based dispatch pattern. While it keeps the step table concise, it prevents static analysis from finding broken method references and makes refactoring fragile.

---

## 2. Security

### 2.1 Strengths

- **Goal risk gating.** `feedback_applier.py:216`: goals with `risk_assessment.level` of "high" or "critical" are blocked when a safety policy is configured.
- **Max auto-apply cap.** Both learning recommendations and goal applications respect `max_auto_apply_per_run` (default 5), preventing runaway config changes.
- **Audit trail.** Every auto-applied change is logged to JSONL with source_id, old_value, new_value, timestamp.

### 2.2 Issues

**ISSUE-3: Audit log has no rotation or size limit (P2)**
`/home/shinelay/meta-autonomous-framework/temper_ai/autonomy/audit.py:48`:
```python
with open(self._path, "a", encoding="utf-8") as fh:
    fh.write(line)
```
The audit JSONL file grows unboundedly. `_read_all()` at line 68 reads the **entire file** into memory on every `get_entries()` call. In a long-running system with frequent autonomous loops, this will degrade performance and eventually OOM.

**Recommendation:** Add log rotation (e.g., rotate at 10MB or 10,000 entries) or switch to the database backend. At minimum, add a size check in `log()`.

**ISSUE-4: `_parse_action` does no input sanitization (P2)**
`/home/shinelay/meta-autonomous-framework/temper_ai/autonomy/feedback_applier.py:240-255`:
The `_parse_action` function parses `config_path:field_path=value` from goal `proposed_actions`. These strings originate from LLM-generated goal proposals. There is no validation that:
- `config_path` is a safe filesystem path (no `../` traversal)
- `field_path` targets an allowed configuration field
- `new_value` is within acceptable bounds

While the current code only marks actions as "translated" and does not directly write to disk, the action dict flows to audit logging with the raw values. If future code uses `config_path` for file operations, this becomes a path traversal vector.

**Recommendation:** Validate `config_path` against an allowlist of config directories and reject paths containing `..` or absolute paths.

**ISSUE-5: No safety policy is passed from orchestrator to FeedbackApplier (P2)**
`/home/shinelay/meta-autonomous-framework/temper_ai/autonomy/orchestrator.py:211-214`:
```python
applier = FeedbackApplier(
    learning_store=store,
    max_auto_apply=self._config.max_auto_apply_per_run,
)
```
And at line 225:
```python
applier = FeedbackApplier(
    learning_store=LearningStore(),
    goal_store=GoalStore(),
    max_auto_apply=self._config.max_auto_apply_per_run,
)
```
Neither instantiation passes `safety_policy`. This means `_check_goal_safety()` always returns `True` (line 206-207: `if self._safety_policy is None: return True`), effectively **bypassing risk gating for all auto-applied goals**.

**Recommendation:** The orchestrator should construct a safety policy (e.g., `GoalSafetyPolicy` from `temper_ai.goals.safety_policy`) and pass it to `FeedbackApplier`.

---

## 3. Error Handling

### 3.1 Strengths

- **Subsystem isolation is excellent.** Every `_run_*` method in the orchestrator wraps its body in `try/except Exception`. Failures append to `report.errors` and return `None`, never crashing the loop.
- **Timeout enforcement.** `_budget_exhausted()` checks elapsed time after each subsystem, bailing out with a "Timeout: skipped remaining subsystems" error if `LOOP_TIMEOUT_SECONDS` (300s) is exceeded.
- **Memory bridge failure isolation.** `_sync_memory_bridge()` has its own try/except inside `_run_learning()`, so bridge failures don't lose the learning results.
- **Goal completion failure handled.** `_complete_goal()` at `feedback_applier.py:199-202` catches exceptions from `update_proposal_status` and logs a warning.

### 3.2 Issues

**ISSUE-6: 12 broad `except Exception` clauses with `noqa: BLE001` (P3)**
All are justified by the "subsystem failures must not crash workflow" pattern, and all log warnings. This is acceptable for an orchestration layer but worth noting: if a subsystem has a programming error (e.g., `AttributeError`), it will be silently swallowed.

**Recommendation:** Consider catching only `(RuntimeError, IOError, ImportError, ValueError)` for tighter safety, or at minimum log at `ERROR` level instead of `WARNING` for unexpected exception types.

---

## 4. Modularity

### 4.1 Strengths

- **Clean dependency direction.** `_schemas.py` and `constants.py` have zero cross-module imports. `orchestrator.py` imports only from `_schemas` and `constants` at module level; everything else is lazy.
- **Workflow schema integration is well-designed.** `_default_autonomous_loop_config()` uses a lazy factory with `field_validator` to avoid fan-out issues.
- **CLI integration is clean.** `main.py:582-621` constructs `AutonomousLoopConfig` from YAML + CLI flag override, runs the orchestrator, prints summary.

### 4.2 Issues

**ISSUE-7: `rollout.py` is dead code -- never imported outside tests (CRITICAL, P1)**
`RolloutManager` is a 194-line module with 4 classes implementing gradual rollout with experiment backing, phase advancement, guardrails, and rollback. However:
- It is **never imported** by `orchestrator.py` or any other production code
- The only imports come from `tests/test_autonomy/test_rollout.py`
- There is no CLI command, API endpoint, or orchestrator step that uses it

This is a significant architectural gap. Gradual rollout is a core capability for Progressive Autonomy (the system's primary pillar), yet it sits unused.

**Recommendation:** Either integrate `RolloutManager` into the feedback application pipeline (wrap auto-applied changes in a rollout), or document it as a future integration point. Do not ship dead code in v1.0.

**ISSUE-8: Stores are created inline in every subsystem method (P2)**
`/home/shinelay/meta-autonomous-framework/temper_ai/autonomy/orchestrator.py`:
- Line 104: `store = LearningStore()`
- Line 150: `goal_store = GoalStore()`
- Line 154: `learning_store = LearningStore()`
- Line 210: `store = LearningStore()`
- Line 226-227: `LearningStore()`, `GoalStore()`
- Line 317: `store = AgentRegistryStore()`
- Line 346: `store = PortfolioStore()`

Each subsystem method creates its own store instances. This prevents dependency injection for testing (tests must patch class constructors instead of passing mocks) and creates redundant `LearningStore()` instances (created at lines 104, 154, 210, 226).

**Recommendation:** Accept stores as constructor parameters with lazy defaults:
```python
def __init__(self, config, learning_store=None, goal_store=None, ...):
```

**ISSUE-9: `__init__.py` exports nothing (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/autonomy/__init__.py`:
```python
"""Post-execution autonomous loop..."""
```
No re-exports. External callers must import from submodules. This is a minor but consistent pattern issue.

---

## 5. Feature Completeness

### 5.1 What is implemented

| Feature | Status | File |
|---------|--------|------|
| Learning mining + recommendations | Complete | `orchestrator.py:95-127` |
| Goal analysis with 4 analyzers | Complete | `orchestrator.py:142-186` |
| Feedback: learning recommendations auto-apply | Complete | `feedback_applier.py:39-72` |
| Feedback: goal auto-apply with safety check | Complete | `feedback_applier.py:151-195` |
| Prompt optimization (DSPy auto-compile) | Complete | `orchestrator.py:232-301` |
| Memory bridge (patterns + goals to memory) | Complete | `memory_bridge.py` |
| Agent memory sync (M9 persistent agents) | Complete | `orchestrator.py:303-335` |
| Portfolio scorecards | Complete | `orchestrator.py:337-374` |
| Audit trail (JSONL) | Complete | `audit.py` |
| Gradual rollout with experiments | **Dead code** | `rollout.py` |

### 5.2 Issues

**ISSUE-10: No async support -- entire loop is synchronous (P2)**
`PostExecutionOrchestrator.run()` is synchronous. Each subsystem runs sequentially. For a loop that touches 6 subsystems (learning, goals, feedback, optimization, portfolio, memory sync), this means the 300s timeout budget is shared serially. Learning and goals (which involve DB queries and LLM calls) could easily consume the entire budget, starving later subsystems.

**Recommendation:** Make `run()` async and execute independent subsystems concurrently with `asyncio.gather()`, or at minimum run learning+goals in parallel since they are independent.

**ISSUE-11: No TODO/FIXME comments (Positive)**
Zero TODO, FIXME, HACK, or XXX markers in the entire module. All features are fully implemented.

**ISSUE-12: `feedback_applier.py` marks goals "applied" without actual config file writes (P2)**
`/home/shinelay/meta-autonomous-framework/temper_ai/autonomy/feedback_applier.py:186`:
```python
if item.get("status") == "translated":
    item["status"] = "applied"
    applied_count += 1
```
The status is changed from "translated" to "applied" without any actual file modification. The `_parse_action` output is logged to audit but never written to the config file. The `apply_approved_goals` method claims to "apply" but only translates and audits.

For learning recommendations, actual application happens via `AutoTuneEngine.apply_recommendations()` (line 70). But for goals, there is no equivalent engine -- translation is treated as application.

**Recommendation:** Either rename to `translate_and_audit_goals()` or implement actual config file writes through a safe mechanism.

---

## 6. Test Quality

### 6.1 Coverage Summary

| Test File | Tests | Coverage Area |
|-----------|-------|---------------|
| `test_orchestrator.py` | 38 | Orchestrator: enable/disable, subsystem calls, graceful degradation, timeout, feedback wiring, prompt optimization, memory bridge |
| `test_feedback_applier.py` | 32 | FeedbackApplier: learning recs, goal translation, goal application, safety, audit, errors, parse_action |
| `test_rollout.py` | 17 | RolloutManager: create, advance, guardrails, complete, rollback |
| `test_audit.py` | 12 | AuditLogger: log, retrieve, persistence, JSONL, malformed, filter |
| `test_memory_bridge.py` | 12 | LearningToMemoryBridge: sync patterns/goals, dedup, metadata, formatting |
| `test_schemas.py` | 10 | Schema defaults, serialization, validation |
| `test_agent_memory_sync.py` | 10 | Agent memory sync: enable/disable, multiple agents, failure handling |
| **Total** | **141** | |

### 6.2 Strengths

- **Edge cases well covered.** Confidence boundaries (exact threshold), equals-in-value parsing, malformed JSONL lines, blank lines, empty actions.
- **Error propagation tested.** Tests verify that FeedbackApplier propagates engine exceptions, that goal store exceptions propagate, and that safety check exceptions block goals.
- **Timeout tested.** `TestOrchestratorTimeout` patches `time.monotonic` to simulate budget exhaustion.

### 6.3 Issues

**ISSUE-13: No integration test with real stores (P2)**
All 141 tests use mocks for `LearningStore`, `GoalStore`, `PortfolioStore`, `AgentRegistryStore`, `ExperimentService`. There is no test that exercises the actual store implementations or verifies that the orchestrator produces correct results with real data.

**ISSUE-14: `test_orchestrator.py` graceful degradation tests are incomplete (P3)**
`TestOrchestratorGracefulDegradation` tests that `None` returns from mocked subsystems don't crash, but doesn't test that actual exceptions from subsystem methods are caught and logged to `report.errors`. The `test_learning_import_error_graceful` test at line 178 does test this for learning, but there is no equivalent for feedback or prompt optimization subsystem exceptions propagating through `_run_subsystems`.

**ISSUE-15: `DEFAULT_ENTRY_LIMIT` imported but unused in tests (P3)**
`/home/shinelay/meta-autonomous-framework/tests/test_autonomy/test_audit.py:8`:
```python
from temper_ai.autonomy.audit import AuditEntry, AuditLogger, DEFAULT_ENTRY_LIMIT
```
`DEFAULT_ENTRY_LIMIT` is imported but never referenced in any test assertion.

---

## 7. Architectural Alignment with Vision Pillars

### Pillar 1: Progressive Autonomy (PRIMARY)

The module **partially** serves this pillar:
- The autonomous loop itself is a step toward progressive autonomy (auto-apply learning, auto-apply goals)
- `AutonomousLoopConfig` provides fine-grained toggles (learning, goals, portfolio, feedback, optimization)
- `auto_apply_min_confidence` allows tuning the confidence threshold

**Gaps:**
- `RolloutManager` (gradual rollout) is fully implemented but **not integrated** -- this is the most direct expression of "progressive" autonomy
- No integration with `temper_ai/safety/autonomy/` (trust levels, budget enforcer, emergency stop) -- the autonomous loop does not check the agent's autonomy level before auto-applying changes
- No feedback loop from auto-applied changes back to the trust evaluator

### Pillar 2: Safety

- Good: Subsystem isolation, audit trail, max-auto-apply cap, risk gating
- Gap: Safety policy not wired in orchestrator (ISSUE-5), no path validation on actions (ISSUE-4)

### Pillar 3: Observability

- Good: Audit JSONL for all changes, structured `PostExecutionReport` with per-subsystem results and errors
- Gap: No metrics/spans emitted for autonomy loop duration or subsystem latency

---

## 8. File-by-File Summary

| File | LOC | Verdict |
|------|-----|---------|
| `__init__.py` | 1 | Empty; could re-export key types |
| `constants.py` | 19 | Clean, well-organized constants |
| `_schemas.py` | 61 | Solid Pydantic models with good defaults |
| `audit.py` | 86 | Functional but lacks rotation (ISSUE-3) |
| `feedback_applier.py` | 255 | Core logic sound; heavy `object`/`Any` typing (ISSUE-1); goal "application" is misleading (ISSUE-12) |
| `memory_bridge.py` | 132 | Clean bridge with dedup; `Any` typing throughout (ISSUE-1) |
| `rollout.py` | 193 | **Dead code** -- well-implemented but never used (ISSUE-7) |
| `orchestrator.py` | 374 | Good design; inline store creation (ISSUE-8); no safety policy (ISSUE-5) |

---

## 9. Recommendations (Priority Order)

| # | Issue | Priority | Effort | Impact |
|---|-------|----------|--------|--------|
| 1 | Wire `RolloutManager` into feedback pipeline or remove dead code (ISSUE-7) | P1 | Medium | High -- core pillar feature |
| 2 | Pass safety policy to `FeedbackApplier` in orchestrator (ISSUE-5) | P2 | Small | High -- security bypass |
| 3 | Add audit log rotation or size limit (ISSUE-3) | P2 | Small | Medium -- production reliability |
| 4 | Validate `config_path` in `_parse_action` (ISSUE-4) | P2 | Small | Medium -- defense in depth |
| 5 | Replace `object`/`Any` params with Protocol types (ISSUE-1) | P2 | Medium | Medium -- type safety |
| 6 | Accept stores via constructor for DI (ISSUE-8) | P2 | Medium | Medium -- testability |
| 7 | Add async support or parallel subsystem execution (ISSUE-10) | P2 | Large | Medium -- timeout budget |
| 8 | Clarify goal "application" semantics (ISSUE-12) | P2 | Small | Medium -- correctness |
| 9 | Add integration test with real stores (ISSUE-13) | P2 | Medium | Medium -- confidence |
| 10 | Connect to safety/autonomy trust levels (arch gap) | P2 | Large | High -- pillar alignment |
