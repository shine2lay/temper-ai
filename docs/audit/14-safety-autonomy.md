# Audit Report 14: Safety Autonomy Module (Progressive Autonomy)

**Scope:** `temper_ai/safety/autonomy/` (15 files, 1835 LOC)
- `__init__.py`, `constants.py`, `schemas.py`, `models.py`
- `manager.py`, `trust_evaluator.py`, `budget_enforcer.py`
- `approval_router.py`, `shadow_mode.py`, `emergency_stop.py`
- `merit_bridge.py`, `policy.py`, `store.py`
- `dashboard_routes.py`, `dashboard_service.py`

**Tests:** `tests/test_safety/test_autonomy/` (13 files, 1670 LOC, 124 tests -- 100% pass)

**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The progressive autonomy module is the **primary implementation of the framework's core vision pillar: Progressive Autonomy**. It provides a 5-level trust ladder (SUPERVISED through STRATEGIC), merit-based evaluation, budget enforcement, shadow validation, emergency stop, and approval routing based on a severity-x-level decision matrix.

The module is **well-designed and well-tested**. The state machine in `manager.py` correctly enforces cooldowns, max-level caps, and thread-safety. The emergency stop uses O(1) `threading.Event` signaling. The approval router implements a clear decision matrix. Shadow mode provides a novel validation-before-promotion mechanism. All 124 tests pass cleanly.

Key concerns: (1) the `BudgetEnforcer` lacks thread-safety for concurrent `record_spend` calls, creating a race condition on spend accumulation; (2) status constants are duplicated between `models.py` and `constants.py`; (3) the `AutonomyStore` returns detached SQLModel objects that callers mutate and re-save, which works via `session.merge()` but is fragile; (4) dashboard routes lack authentication; (5) `force_level()` bypasses max_level cap, which is by design but should be audited; (6) the `AutonomyPolicy` uses broad `Any` typing for all wired components, losing type safety.

**Overall Grade: A-** (90/100)

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Code Quality | A | Clean decomposition, all functions within limits, proper constants |
| Security | B+ | E-stop reliable, but budget has race condition, dashboard unauthenticated |
| Error Handling | A | Fail-safe defaults (SUPERVISED on missing state), graceful degradation |
| Modularity | A | Clean separation of concerns, weak coupling via bridge pattern |
| Feature Completeness | A | No TODO/FIXME/HACK, all 5 levels functional, shadow mode complete |
| Test Quality | A- | 124 tests, good coverage, but no concurrent/stress tests |
| Architecture | A | Strong alignment with Progressive Autonomy pillar |

---

## 1. Code Quality Findings

### F-01: Duplicate status constants across `models.py` and `constants.py` [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/models.py:15-17`
```python
STATUS_ACTIVE = "active"
STATUS_WARNING = "warning"
STATUS_EXHAUSTED = "exhausted"
```

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/constants.py:60-62`
```python
STATUS_ACTIVE = "active"
STATUS_WARNING = "warning"
STATUS_EXHAUSTED = "exhausted"
```

These three constants are defined identically in both files. `budget_enforcer.py` imports from `constants.py`, while `models.py` uses its own local copy for the `BudgetRecord.status` default. This duplication risks drift if one is changed without the other.

**Impact:** Maintenance risk. No functional issue today, but a future change to one set could silently diverge behavior.
**Recommendation:** Remove the constants from `models.py` and import from `constants.py`. Update the `BudgetRecord.status` default to reference `STATUS_ACTIVE` from `constants.py`.

### F-02: `AutonomyPolicy.configure()` uses `Any` for all parameters [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/policy.py:51-62`
```python
def configure(
    self,
    manager: Any = None,
    budget_enforcer: Any = None,
    approval_router: Any = None,
    emergency_stop: Any = None,
) -> None:
    """Wire in autonomy components after construction."""
    self._manager = manager
    self._budget_enforcer = budget_enforcer
    self._approval_router = approval_router
    self._emergency_stop = emergency_stop
```

All four wired components are typed as `Any`. This is intentional to avoid circular imports (the policy is instantiated by the factory before the components exist), but it means the type checker cannot detect wiring errors. The class attributes are also `Any` on lines 31-34.

**Impact:** No runtime impact (errors caught by `AttributeError` handlers), but reduces IDE assistance and static analysis confidence.
**Recommendation:** Use `TYPE_CHECKING` imports with string annotations: `manager: "AutonomyManager | None" = None`.

### F-03: `manager.py` `_create_transition` has 7 parameters (at limit) [INFO]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/manager.py:269-278`
```python
def _create_transition(
    self,
    agent_name: str,
    domain: str,
    from_level: int,
    to_level: int,
    reason: str,
    trigger: str,
    merit_snapshot: dict | None = None,
) -> AutonomyTransition:
```

This method has 7 parameters (excluding `self`), which is at the coding standard limit. It is a private helper that constructs a dataclass, so the parameter count is justified, but future additions would exceed the limit.

**Impact:** None currently. At the boundary.
**Recommendation:** If more fields are needed, consider a `TransitionParams` dataclass.

### F-04: `_utcnow()` helper in `shadow_mode.py` is inconsistent with rest of module [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/shadow_mode.py:156-159`
```python
def _utcnow():  # type: ignore[no-untyped-def]
    """Lazy import to avoid module-level import overhead."""
    from temper_ai.storage.database.datetime_utils import utcnow
    return utcnow()
```

This is the only file in the module that uses a lazy `_utcnow()` wrapper. All other files (`manager.py`, `budget_enforcer.py`, `emergency_stop.py`, `models.py`) import `utcnow` at the top level. The claimed reason ("avoid module-level import overhead") is not applied consistently.

**Impact:** Minor inconsistency. No functional issue.
**Recommendation:** Import `utcnow` at module level like the other files, or document why this file specifically needs lazy import.

---

## 2. Security Findings

### S-01: `BudgetEnforcer.record_spend()` is not thread-safe -- race condition on spend accumulation [HIGH]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/budget_enforcer.py:110-131`
```python
def record_spend(self, scope: str, cost_usd: float) -> None:
    budget = self._get_or_create_budget(scope)
    budget.spent_usd += cost_usd
    budget.action_count += 1
    budget.updated_at = utcnow()
    # ... status update ...
    self._store.save_budget(budget)
```

The `record_spend` method reads the budget, increments `spent_usd` in Python, and writes it back. There is **no lock** and the `AutonomyStore.save_budget()` uses `session.merge()` which does a full-row overwrite. If two concurrent calls read the same initial value, one spend will be lost. This is a **TOCTOU (time-of-check-time-of-use) vulnerability** that could allow budget overruns.

Contrast with `AutonomyManager` which correctly uses `threading.Lock()` on lines 43/73/107/121/134.

**Impact:** Under concurrent autonomous agent operations, total spend could exceed the budget limit. In a multi-worker deployment with PostgreSQL, the problem is amplified since the in-memory merge would overwrite concurrent changes.
**Recommendation:** Either (a) add a `threading.Lock` to `BudgetEnforcer` for single-process safety, or (b) use a SQL `UPDATE budget_records SET spent_usd = spent_usd + :amount WHERE scope = :scope` atomic increment, or (c) wrap the read-increment-write in a database transaction with `SELECT ... FOR UPDATE`.

### S-02: `check_budget()` also has a TOCTOU gap with `record_spend()` [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/budget_enforcer.py:70-108`

The `check_budget` reads the current budget state, and a separate `record_spend` call updates it. Between a successful `check_budget` (allowed=True) and the eventual `record_spend`, another thread could exhaust the budget. The check-then-act pattern is inherently racy without atomic check-and-decrement.

**Impact:** An agent could be allowed to proceed with an action even though another concurrent action has already exhausted the budget.
**Recommendation:** Consider an atomic `check_and_reserve(scope, estimated_cost)` that decrements remaining budget within a single transaction, returning the reservation result.

### S-03: Dashboard routes lack authentication [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/dashboard_routes.py:39-44`
```python
def create_autonomy_router(service: AutonomyDataService) -> APIRouter:
    """Create autonomy API router."""
    router = APIRouter(prefix="/autonomy", tags=["autonomy"])
    _register_get_routes(router, service)
    _register_post_routes(router, service)
    return router
```

No `Depends(require_auth)` is applied to any route. The POST routes for `/emergency-stop`, `/resume`, `/escalate`, and `/deescalate` are **unauthenticated**. Anyone with network access to the dashboard can:
- Activate emergency stop (denial of service)
- Deactivate emergency stop (bypass safety control)
- Escalate any agent to any level (privilege escalation)
- De-escalate any agent (denial of capability)

The M10 multi-tenant auth system adds `Depends(require_auth)` to other route modules but this module was not updated.

**Impact:** In server mode, any unauthenticated HTTP client can manipulate autonomy levels and emergency stop.
**Recommendation:** Add `Depends(require_auth)` to POST routes at minimum. GET routes should also require authentication in server mode.

### S-04: `force_level()` bypasses `max_level` cap and cooldown [LOW -- by design, but audit note]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/manager.py:126-149`
```python
def force_level(
    self,
    agent_name: str,
    domain: str,
    level: AutonomyLevel,
    reason: str = "forced",
) -> AutonomyTransition:
    """Force agent to a specific level (bypasses cooldown)."""
    with self._lock:
        state = self._get_or_create_state(agent_name, domain)
        from_level = state.current_level
        state.current_level = level.value
```

This method explicitly bypasses both cooldown and max_level cap. It uses `TRIGGER_EMERGENCY_STOP` as the trigger regardless of the actual reason, which could be misleading in audit logs if used for non-emergency purposes (e.g., admin override for testing).

**Impact:** Acceptable for emergency response, but the trigger label should match the actual use case.
**Recommendation:** Accept a `trigger` parameter (default `TRIGGER_EMERGENCY_STOP`) to allow callers to distinguish forced escalations from actual emergency stops in audit logs.

### S-05: Emergency stop uses module-level global state [LOW -- accepted pattern]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/emergency_stop.py:22-24`
```python
_stop_event = threading.Event()
_stop_lock = threading.Lock()
_active_event_id: str | None = None
```

Module-level globals are used for O(1) cross-thread signaling. This is an intentional design choice documented in the module docstring. The `reset_emergency_state()` function on line 128-133 is properly restricted to tests. However, in a multi-process deployment (e.g., Gunicorn workers), the emergency stop signal is **not shared across processes**. Each worker maintains its own `_stop_event`.

**Impact:** Emergency stop only works within a single process. Multiple Gunicorn workers would require an external signaling mechanism (Redis, database polling, etc.).
**Recommendation:** Document the single-process limitation. For multi-process deployments, add a database-backed poll or external signal mechanism.

---

## 3. Error Handling Findings

### E-01: Fail-safe defaults are correctly implemented [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/manager.py:45-55`
```python
def get_level(
    self, agent_name: str, domain: str
) -> AutonomyLevel:
    state = self._store.get_state(agent_name, domain)
    if state is None:
        return AutonomyLevel.SUPERVISED  # Fail-safe: most restrictive
    return AutonomyLevel(state.current_level)
```

When no state exists for an agent, the system defaults to `SUPERVISED` (most restrictive level). This is the correct fail-safe behavior -- unknown agents start with maximum supervision.

Similarly, `AutonomyConfig` defaults to `enabled: False` (line 27 of `schemas.py`), and `AutonomyPolicy._validate_impl()` returns `valid=True` with no violations when autonomy is disabled (line 70 of `policy.py`), ensuring backward compatibility.

### E-02: `AutonomyPolicy` gracefully handles missing/erroring components [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/policy.py:88-105`
```python
def _check_emergency_stop(
    self, action: dict[str, Any], context: dict[str, Any]
) -> SafetyViolation | None:
    if self._emergency_stop is None:
        return None
    try:
        if self._emergency_stop.is_active():
            return SafetyViolation(...)
    except (AttributeError, RuntimeError) as exc:
        logger.debug("Emergency stop check error: %s", exc)
    return None
```

Each check method (`_check_emergency_stop`, `_check_budget`, `_check_approval`) guards against `None` components and catches `(AttributeError, RuntimeError)`. This means the policy degrades gracefully -- if a component fails, the check is skipped rather than crashing the validation pipeline.

**However**, the fail-open behavior on component error (returning `None`/skipping the check) means a broken budget enforcer would allow actions through. For the emergency stop, this is the correct behavior (fail to the previous check's result). For budget, it means a broken enforcer allows unchecked spending.

**Impact:** Intentional graceful degradation. The trade-off (availability over strict enforcement on error) is reasonable for a policy that runs on every action.
**Recommendation:** Log at WARNING level instead of DEBUG when safety checks fail, and consider adding an observability counter for check failures.

### E-03: `MeritSafetyBridge` correctly suppresses evaluation errors [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/merit_bridge.py:52-64`
```python
try:
    transition = self._manager.evaluate_and_transition(
        session, agent_name, domain
    )
    ...
except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
    logger.warning("Autonomy evaluation failed: %s", exc)
```

The bridge catches a specific set of exceptions and logs at WARNING level. This prevents evaluation failures from disrupting the merit score recording pipeline. The counter still advances after an error (line 47-48), so evaluation won't be permanently stuck.

### E-04: `TrustEvaluator._load_merit_score` catches ImportError gracefully [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/trust_evaluator.py:107-119`
```python
def _load_merit_score(
    self, session: Any, agent_name: str, domain: str
) -> Any:
    try:
        from sqlmodel import select
        from temper_ai.storage.database.models import AgentMeritScore
        stmt = select(AgentMeritScore).where(...)
        return session.exec(stmt).first()
    except (ImportError, AttributeError) as exc:
        logger.debug("Could not load merit score: %s", exc)
        return None
```

The lazy import of `sqlmodel` and `AgentMeritScore` is wrapped in a try/except that handles both `ImportError` (if sqlmodel is not installed) and `AttributeError` (if the model doesn't have the expected columns). This allows the trust evaluator to work in environments without a full database setup.

---

## 4. Modularity Findings

### M-01: Clean separation of concerns across 15 files [POSITIVE]

The module demonstrates excellent Single Responsibility Principle adherence:

| File | Responsibility | LOC |
|------|---------------|-----|
| `constants.py` | All magic numbers extracted to named constants | 71 |
| `schemas.py` | Pydantic config models and AutonomyLevel enum | 34 |
| `models.py` | SQLModel persistence tables (4 tables) | 85 |
| `store.py` | Database CRUD operations | 125 |
| `manager.py` | State machine (transitions, cooldowns, thread-safety) | 291 |
| `trust_evaluator.py` | Merit-based trust scoring | 136 |
| `budget_enforcer.py` | Cost budget enforcement | 208 |
| `approval_router.py` | Severity x level decision matrix | 114 |
| `shadow_mode.py` | Shadow validation for promotion readiness | 159 |
| `emergency_stop.py` | O(1) cross-thread halt signal | 133 |
| `merit_bridge.py` | Bridge between merit updates and autonomy eval | 64 |
| `policy.py` | SafetyPolicy integration point | 158 |
| `dashboard_routes.py` | FastAPI REST endpoints | 142 |
| `dashboard_service.py` | Data service for dashboard | 105 |

No file exceeds 291 lines. No function exceeds 50 lines. The largest class (`AutonomyManager`) has 12 methods, well within the 20-method limit.

### M-02: Weak coupling via bridge pattern [POSITIVE]

`MeritSafetyBridge` uses a no-op pattern when `autonomy_manager` is `None`:
```python
def on_decision_recorded(self, ...):
    if self._manager is None:
        return
```

This means the merit scoring system can function independently of the autonomy system. The bridge is the only coupling point, and it is optional.

Similarly, `AutonomyPolicy.configure()` allows wiring components individually, and the policy operates with any subset (or none) of its components configured.

### M-03: Dashboard routes create new manager instances per request [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/dashboard_routes.py:104-117`
```python
@router.post("/escalate")
def escalate_agent(req: EscalateRequest) -> dict[str, Any]:
    from temper_ai.safety.autonomy.manager import AutonomyManager
    from temper_ai.safety.autonomy.schemas import AutonomyLevel
    manager = AutonomyManager(
        store=service.store, max_level=AutonomyLevel.STRATEGIC,
    )
```

Each POST request creates a new `AutonomyManager` instance. While the `AutonomyStore` is shared (from the service), the `AutonomyManager` has a `threading.Lock()` that is per-instance. This means two concurrent escalation requests could race because they hold different locks.

The same issue applies to the `/emergency-stop` and `/resume` endpoints which create new `EmergencyStopController` instances per request (lines 85-88, 94-97). However, since the emergency stop uses module-level `_stop_event`, the controller instances are effectively stateless and this is not a real issue for emergency stop.

**Impact:** Concurrent dashboard escalation/de-escalation requests could produce inconsistent results (e.g., two escalations applied when cooldown should block the second).
**Recommendation:** Use a shared `AutonomyManager` instance within the `AutonomyDataService`, or accept that dashboard operations are low-frequency and the race window is negligible.

---

## 5. Feature Completeness Findings

### FC-01: All 5 autonomy levels are fully implemented [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/schemas.py:10-17`
```python
class AutonomyLevel(IntEnum):
    SUPERVISED = 0      # All actions require human approval
    SPOT_CHECKED = 1    # Random sampling of actions
    RISK_GATED = 2      # Only high-risk actions need approval
    AUTONOMOUS = 3      # Only critical violations need approval
    STRATEGIC = 4       # Fully autonomous, critical still blocked
```

The approval matrix in `approval_router.py` (lines 28-37) correctly implements the severity-x-level decision table. All transitions between levels are exercised in integration tests.

### FC-02: Shadow mode provides novel validation-before-promotion [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/shadow_mode.py`

The shadow mode runs non-blocking parallel validation at a proposed higher level and tracks agreement rate. Promotion is only recommended when `shadow_runs >= 50` and `agreement_rate >= 0.98`. This provides a data-driven safety net before granting additional autonomy.

### FC-03: No TODO/FIXME/HACK comments anywhere in the module [POSITIVE]

Zero incomplete implementations found. All features are fully implemented and tested.

### FC-04: Budget period enforcement is partial [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/autonomy/budget_enforcer.py:184-191`
```python
budget = BudgetRecord(
    id=f"bg-{uuid.uuid4().hex[:UUID_HEX_LEN]}",
    scope=scope,
    period="unlimited",
    budget_usd=self._default_budget,
)
```

Budget records have a `period` field but it is always set to `"unlimited"`. There is no mechanism to reset spent amounts at period boundaries (e.g., monthly budget resets). The `period` field exists in the model but is never acted upon.

**Impact:** No time-based budget reset. Budgets can only be managed by creating new records.
**Recommendation:** Either implement period-based resets or document that budgets are lifetime aggregates and consider removing the `period` field to avoid confusion.

### FC-05: Shadow mode is not automatically wired into the escalation flow [MEDIUM]

The `ShadowMode` component exists and works, but it is not automatically invoked during `AutonomyManager.evaluate_and_transition()`. The manager evaluates trust and transitions directly without consulting shadow readiness. Shadow validation must be explicitly invoked by external code.

**Impact:** The shadow mode safety net is available but not enforced by default. An agent could be escalated by the manager without passing shadow validation.
**Recommendation:** Add an optional `shadow_mode` parameter to `AutonomyManager.__init__()` and gate escalation on `check_promotion_ready()` when shadow mode is enabled.

---

## 6. Test Quality Findings

### T-01: Comprehensive test coverage with 124 tests [POSITIVE]

| Test File | Tests | Coverage Area |
|-----------|-------|--------------|
| `test_manager.py` | 11 | State machine, escalation, de-escalation, cooldown, force |
| `test_trust_evaluator.py` | 7 | Merit-based evaluation, thresholds |
| `test_budget_enforcer.py` | 9 | Budget check, spend recording, estimation |
| `test_approval_router.py` | 10 | Full decision matrix coverage |
| `test_shadow_mode.py` | 7 | Agreement tracking, promotion readiness, reset |
| `test_emergency_stop.py` | 7 | Activate/deactivate, persistence, check_or_raise |
| `test_merit_bridge.py` | 6 | Rate limiting, error handling, per-agent counters |
| `test_policy.py` | 9 | Disabled mode, emergency, budget, approval integration |
| `test_store.py` | 9 | CRUD for all 4 models |
| `test_schemas.py` | 8 | Enum ordering, config defaults, backward compat |
| `test_models.py` | 6 | Model creation, defaults, JSON fields |
| `test_integration.py` | 7 | Full lifecycle, emergency+policy, budget exhaustion |
| `test_dashboard_routes.py` | 9 | API endpoints GET/POST |

All tests pass. Each test file tests one component. Integration tests verify cross-component flows.

### T-02: Missing concurrent/thread-safety tests [MEDIUM]

No tests verify thread-safety of `AutonomyManager` (which has a lock) or test concurrent `BudgetEnforcer.record_spend()` (which does not). The `threading.Lock()` in the manager is untested under contention.

**Impact:** The thread-safety guarantees are not verified by tests. Regressions could remove locking without test failure.
**Recommendation:** Add a test that spawns N threads calling `manager.escalate()` concurrently and verifies no state corruption.

### T-03: Dashboard route tests use in-memory SQLite [POSITIVE]

All test fixtures use `sqlite:///:memory:` for isolation. The `autouse=True` fixture `_reset_stop()` properly resets the module-level emergency state between tests.

### T-04: `test_trust_evaluator.py` uses mocked DB sessions [POSITIVE]

Trust evaluator tests mock the database session, avoiding database setup complexity while still verifying the evaluation logic. The mock merit score helper `_mock_merit()` is well-structured.

### T-05: No negative cost or negative budget tests [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_autonomy/test_budget_enforcer.py`

No tests verify behavior when `record_spend()` is called with a negative `cost_usd`, when `BudgetEnforcer` is initialized with `default_budget=0` or `default_budget=-1`, or when `estimated_cost` is negative. The `record_spend` method does no input validation and would happily accept negative costs (increasing remaining budget).

**Impact:** Negative spend could bypass budget enforcement.
**Recommendation:** Add input validation to `record_spend` (`if cost_usd < 0: raise ValueError`) and add tests for edge cases.

---

## 7. Architectural Alignment with Vision Pillars

### Progressive Autonomy (PRIMARY PILLAR) -- Grade: A

The module is the **direct implementation** of this pillar:

- **5-level trust ladder**: `AutonomyLevel` enum with SUPERVISED -> SPOT_CHECKED -> RISK_GATED -> AUTONOMOUS -> STRATEGIC
- **Merit-based evaluation**: `TrustEvaluator` reads agent performance history and recommends escalation/de-escalation
- **Shadow validation**: `ShadowMode` tracks agreement rate before promotion
- **Cooldown enforcement**: 24-hour escalation cooldown, 1-hour de-escalation cooldown
- **Budget enforcement**: Per-scope cost tracking with warning/exhaustion thresholds
- **Emergency stop**: O(1) cross-thread halt signal
- **Audit trail**: All transitions recorded with reason, trigger, and merit snapshot

The architecture correctly implements the Progressive Autonomy pillar's core requirement: agents must **earn** higher autonomy levels through demonstrated reliability, with safety mechanisms (shadow validation, budget limits, emergency stop) at every level.

### Safety Through Composition -- Grade: A

`AutonomyPolicy` extends `BaseSafetyPolicy` and integrates cleanly into the `PolicyRegistry` via the `factory.py` mapping (line 56: `"autonomy_policy": AutonomyPolicy`). It follows the fail-closed pattern (emergency stop blocks everything) and the composition pattern (multiple independent checks are aggregated).

### Observable Decisions -- Grade: B+

All transitions are persisted to the database with full audit trail (`AutonomyTransition` model). Dashboard endpoints expose status, transitions, budgets, and emergency history. However, there is no integration with the main observability event bus -- autonomy transitions are not emitted as observability events that would appear in the main trace timeline.

**Recommendation:** Emit `AutonomyTransitionEvent` through the observability event bus when transitions occur, so they appear in the execution timeline alongside agent decisions.

---

## 8. Summary of Recommendations (Priority Order)

| # | Finding | Severity | Effort | Recommendation |
|---|---------|----------|--------|----------------|
| S-01 | `BudgetEnforcer.record_spend()` race condition | HIGH | Small | Add `threading.Lock` or use SQL atomic increment |
| S-03 | Dashboard routes unauthenticated | MEDIUM | Small | Add `Depends(require_auth)` to POST routes |
| FC-05 | Shadow mode not wired into escalation flow | MEDIUM | Medium | Gate escalation on shadow readiness in manager |
| T-02 | No concurrent/thread-safety tests | MEDIUM | Small | Add multi-threaded escalation/budget tests |
| S-02 | `check_budget` + `record_spend` TOCTOU | MEDIUM | Medium | Consider atomic `check_and_reserve()` |
| T-05 | No negative cost validation | LOW | Small | Add input validation and edge case tests |
| F-01 | Duplicate status constants | LOW | Small | Import from `constants.py` in `models.py` |
| FC-04 | Budget period field unused | LOW | Small | Implement period resets or remove field |
| M-03 | New manager per dashboard request | LOW | Small | Share manager instance in service |
| F-02 | `Any` typing on policy components | LOW | Small | Use `TYPE_CHECKING` imports |
| F-04 | Inconsistent `_utcnow()` wrapper | LOW | Trivial | Align with module convention |
| S-04 | `force_level` trigger label | LOW | Trivial | Accept custom trigger parameter |
| S-05 | Emergency stop single-process limitation | LOW | Large | Document limitation; defer to deployment guide |

---

## 9. File-by-File Summary

| File | LOC | Grade | Key Notes |
|------|-----|-------|-----------|
| `constants.py` | 71 | A+ | All magic numbers extracted, well-organized sections |
| `schemas.py` | 34 | A+ | Clean Pydantic model with validation, safe defaults |
| `models.py` | 85 | A- | Duplicate status constants (F-01) |
| `store.py` | 125 | A | Clean CRUD, `session.merge()` pattern works but fragile |
| `manager.py` | 291 | A | Thread-safe state machine, all guards correct |
| `trust_evaluator.py` | 136 | A | De-escalation checked first (safety priority) |
| `budget_enforcer.py` | 208 | B+ | Race condition on `record_spend` (S-01) |
| `approval_router.py` | 114 | A | Clean decision matrix, `random` usage properly annotated |
| `shadow_mode.py` | 159 | A- | Not wired into escalation flow (FC-05) |
| `emergency_stop.py` | 133 | A | O(1) signaling, proper test reset function |
| `merit_bridge.py` | 64 | A+ | Clean no-op pattern, rate-limited evaluation |
| `policy.py` | 158 | A- | Graceful degradation, but `Any` typing (F-02) |
| `dashboard_routes.py` | 142 | B | No authentication (S-03), new manager per request (M-03) |
| `dashboard_service.py` | 105 | A | Clean data transformation layer |
| `__init__.py` | 10 | A | Exports `AutonomyConfig` and `AutonomyLevel` |
