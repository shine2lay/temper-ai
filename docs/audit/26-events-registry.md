# Audit 26: Events + Registry Modules

**Date:** 2026-02-22
**Scope:** `temper_ai/events/` (9 files) + `temper_ai/registry/` (6 files)
**Tests:** `tests/test_events/` (11 files) + `tests/test_registry/` (8 files)
**Result:** 236 tests, all passing

---

## Executive Summary

Both modules are well-structured, cleanly factored into helper modules, and demonstrate
good separation of concerns. The events module provides a persistent event bus with
cross-workflow triggering, subscription matching, and replay capabilities. The registry
module provides CRUD operations for persistent agent registration with DB backing.
Overall quality is high with a few notable issues: a timezone-naive `datetime.now()` bug,
defined-but-unenforced validation constants, dead code, and a subscription query that
performs a full table scan.

**Severity Breakdown:**
- Critical: 0
- High: 1 (timezone bug)
- Medium: 5 (unenforced limits, full table scan, no event type validation, no subscription auth, handler_ref injection surface)
- Low: 4 (dead code, unused schemas)

---

## 1. Code Quality

### 1.1 Function Length and Complexity

All functions and methods are well within the 50-line limit. The longest methods are
`TemperEventBus.emit` (~20 lines) and `CrossWorkflowTrigger._run_workflow` (~38 lines).
No deep nesting was found (max depth 3). Parameter counts are all within 7.

**Verdict:** PASS -- Clean, well-decomposed code.

### 1.2 Naming

All names follow Python conventions. Module-private helpers use `_` prefix consistently.
Constants use `UPPER_CASE`. Class names are descriptive (`TemperEventBus`,
`SubscriptionRegistry`, `AgentRegistryStore`).

### 1.3 Magic Numbers

All numeric constants are properly extracted:
- `temper_ai/events/constants.py:14` -- `MAX_PAYLOAD_SIZE_BYTES = 1048576`
- `temper_ai/events/constants.py:15` -- `DEFAULT_TRIGGER_TIMEOUT_SECONDS = 300`
- `temper_ai/events/constants.py:16` -- `MAX_SUBSCRIPTION_HANDLERS = 100`
- `temper_ai/registry/constants.py:11` -- `DEFAULT_INVOCATION_TIMEOUT = 600`

**Verdict:** PASS -- No magic numbers.

### 1.4 Fan-Out

- `events/event_bus.py` imports from 4 internal modules (bus_helpers, cross_workflow,
  subscription_helpers, subscription_registry). Within budget.
- `registry/store.py` imports from 4 internal modules. Within budget.
- Both modules use lazy imports (`from ... import` inside methods) to avoid
  circular dependencies -- good pattern.

**Verdict:** PASS -- Fan-out < 8 for all modules.

---

## 2. Bugs

### 2.1 [HIGH] Timezone-Naive `datetime.now()` in ObservabilityEvent Conversion

**File:** `temper_ai/events/_bus_helpers.py:105`
```python
return ObservabilityEvent(
    event_type=event_type,
    timestamp=datetime.now(),  # BUG: timezone-naive
    data=data,
    workflow_id=source_workflow_id,
    agent_id=agent_id,
)
```

All other timestamp generation in the codebase uses `utcnow()` from
`temper_ai/storage/database/datetime_utils` or `datetime.now(timezone.utc)`. This is
the only place using bare `datetime.now()`, which produces a naive datetime object.
This will cause inconsistencies in event timestamps, especially in environments where
the system timezone is not UTC. It also violates the project coding standard
("datetime.now(timezone.utc) not datetime.utcnow()").

**Fix:** Replace `datetime.now()` with `utcnow()` (already imported at line 11).

### 2.2 [LOW] `get_for_event` Filters Subscriptions with Source Workflow Incorrectly

**File:** `temper_ai/events/subscription_registry.py:117-120`
```python
if source_workflow_id:
    stmt = stmt.where(
        EventSubscription.source_workflow_filter == source_workflow_id
    )
```

When a `source_workflow_id` is provided, this query only returns subscriptions whose
`source_workflow_filter` exactly matches. It **excludes** subscriptions with
`source_workflow_filter = None` (i.e., "match all workflows"). This means global
subscriptions (no filter) will not match events from specific workflows when this
method is called with a non-None source.

Note: This method is not currently used in the hot path -- `evaluate_subscriptions`
in `_bus_helpers.py` fetches all active subscriptions and applies `matches_filter()`
in Python, which correctly handles the None case. So this is not a runtime bug today,
but it is a latent bug if anyone calls `get_for_event` directly.

---

## 3. Security

### 3.1 [MEDIUM] No Validation of `handler_ref` Against Code Injection

**File:** `temper_ai/events/_subscription_helpers.py:12-14`
```python
def register_handler(name: str, fn: Callable) -> None:
    _HANDLER_REGISTRY[name] = fn
```

**File:** `temper_ai/events/subscription_registry.py:41-48`
```python
if handler_ref:
    from temper_ai.events._subscription_helpers import _HANDLER_REGISTRY
    if handler_ref not in _HANDLER_REGISTRY:
        logger.warning(...)
```

The `handler_ref` is an arbitrary string stored in the database. When resolved via
`resolve_handler()`, it is only looked up in `_HANDLER_REGISTRY` (a plain dict),
which is safe. There is no dynamic `importlib.import_module` path -- the name check
in `SubscriptionRegistry.register()` at line 44 warns but allows the subscription
to be created anyway. This is acceptable because `resolve_handler` will simply return
`None` for unknown refs.

**Risk:** Low. The lookup-only pattern is safe. However, there is no validation that
`handler_ref` is a valid dotted-path identifier. Arbitrary strings (SQL, path
traversal, etc.) can be stored in the DB field. Recommend adding a regex check:
`^[a-zA-Z_][a-zA-Z0-9_.]*$`.

### 3.2 [MEDIUM] No Event Type Validation

**File:** `temper_ai/events/event_bus.py:93-118` (emit method)

The `event_type` parameter accepts any arbitrary string. There is no validation against
the known event type constants defined in `constants.py`. While this is intentionally
flexible (the constant `EVENT_CUSTOM = "custom"` suggests extensibility), it means:
- Typos in event types silently produce undeliverable events
- No upper bound on the string length for event types stored in the DB

Recommend adding a max length check and optionally a warning for unknown event types.

### 3.3 [MEDIUM] No Authorization on Subscription Creation

**File:** `temper_ai/events/event_bus.py:122-151` (subscribe_persistent)

Any caller can create a subscription for any `agent_id`, including impersonating other
agents. The `agent_id` parameter is not validated against the calling agent's identity.
In a multi-tenant environment (M10), this could allow tenant A to create subscriptions
claiming to be tenant B's agent.

**Recommendation:** When M10 auth is active, validate that the calling AuthContext
owns the specified `agent_id`.

### 3.4 [MEDIUM] No Authorization on Agent Registration

**File:** `temper_ai/registry/service.py:29-61` (register_agent)

The `config_path` parameter is a raw filesystem path that is passed directly to
`open()` in `_helpers.py:41`. While the file is loaded with `yaml.safe_load` (good),
there is no path validation. A malicious caller could register an agent with
`config_path="/etc/shadow"` to probe filesystem contents.

**Recommendation:** Validate `config_path` against allowed directories using the
existing `temper_ai.shared.utils.path_safety` module.

---

## 4. Error Handling

### 4.1 Robust Degradation in Event Bus -- GOOD

The `TemperEventBus` demonstrates excellent error handling patterns:

- `_persist_and_emit` (line 229-244): DB failures are caught, logged as warnings,
  and the event is still forwarded to the observability bus. This prevents DB outages
  from blocking event delivery.
- `_forward_to_obs_bus` (line 260-263): ObservabilityEventBus failures are caught
  and logged.
- `_dispatch_subscriptions` (line 295-298): Individual handler failures are caught
  per-subscription, preventing one bad handler from blocking others.

### 4.2 Cross-Workflow Trigger Error Handling -- GOOD

**File:** `temper_ai/events/_cross_workflow.py:105-118`

Both `FileNotFoundError` and generic `Exception` are caught with appropriate logging.
The broad `Exception` catch has a `# noqa: BLE001` annotation. The error messages
include the trigger ID, workflow path, and exception detail -- good for debugging.

### 4.3 Registry Store Missing-Agent Handling -- GOOD

**File:** `temper_ai/registry/store.py:157-162`

`update_last_active` and `update_status` both handle missing agents gracefully with
a warning log rather than raising exceptions. This is appropriate since the caller
(invoke in service.py) may be racing with unregister.

---

## 5. Modularity

### 5.1 Event Bus Architecture -- GOOD

The composition-over-inheritance pattern is well-applied:
- `TemperEventBus` wraps `ObservabilityEventBus` via composition (line 50)
- Cross-workflow triggers are delegated to `CrossWorkflowTrigger` (line 54)
- Subscription management is delegated to `SubscriptionRegistry` (line 53)
- Helper functions are extracted to `_bus_helpers.py` and `_subscription_helpers.py`

The two-phase initialization for `execution_service` (via `set_execution_service`)
correctly breaks a circular dependency.

### 5.2 Registry Architecture -- GOOD

Clean layered design:
- `_helpers.py` -- Pure functions (ID generation, config loading, namespace building)
- `_schemas.py` -- Pydantic models (no DB dependency)
- `store.py` -- DB CRUD layer (SQLModel operations)
- `service.py` -- Business logic layer (orchestration)

The `_session()` context manager pattern in `store.py` with fallback to global
`get_session()` is well-designed for testability and production use.

### 5.3 Lazy `__init__.py` in Events -- GOOD

**File:** `temper_ai/events/__init__.py:4-17`

Uses `__getattr__` for lazy loading, preventing unnecessary imports when the module
is referenced but not used. This follows the fan-out reduction pattern established
elsewhere in the codebase.

---

## 6. Dead Code and Unused Artifacts

### 6.1 [LOW] `_new_id()` in Events Models

**File:** `temper_ai/events/models.py:47-49`
```python
def _new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())
```

This function is defined but never called anywhere in the codebase. The event bus
and subscription registry both generate IDs inline with `str(uuid.uuid4())`. Should
either be used as a `default_factory` on the model `id` fields or removed.

### 6.2 [LOW] `build_persistent_memory_config` in Registry Helpers

**File:** `temper_ai/registry/_helpers.py:15-20`
```python
def build_persistent_memory_config(agent_name: str) -> dict[str, Any]:
    ...
```

Only referenced in test code (`tests/test_registry/test_helpers.py`). Never used in
production code. Could be removed or moved to test utilities.

### 6.3 [LOW] `PersistenceConfig` Schema

**File:** `temper_ai/registry/_schemas.py:10-13`
```python
class PersistenceConfig(BaseModel):
    enabled: bool = True
```

Exported from `__init__.py` but never used in production code. Only tested in
`tests/test_registry/test_schemas.py`. Appears to be a placeholder for future use.

### 6.4 [LOW] Unused Constants

- `temper_ai/registry/constants.py:11` -- `DEFAULT_INVOCATION_TIMEOUT = 600` is never
  referenced outside the constants file.
- `temper_ai/events/constants.py:14` -- `MAX_PAYLOAD_SIZE_BYTES = 1048576` is defined
  but never enforced (see section 7.2).

---

## 7. Unenforced Limits

### 7.1 [MEDIUM] `MAX_PAYLOAD_SIZE_BYTES` Defined but Not Enforced

**File:** `temper_ai/events/constants.py:14`

The 1MB payload limit constant exists but is never checked in `persist_event()` or
`TemperEventBus.emit()`. An attacker or misconfigured agent could emit events with
arbitrarily large payloads, consuming DB storage and memory.

**Recommendation:** Add a size check in `persist_event()`:
```python
import json
if payload and len(json.dumps(payload)) > MAX_PAYLOAD_SIZE_BYTES:
    raise ValueError("Event payload exceeds max size")
```

### 7.2 [MEDIUM] `MAX_AGENT_NAME_LENGTH` / `MAX_DESCRIPTION_LENGTH` Not Enforced in Service

**File:** `temper_ai/registry/constants.py:9-10`

While the DB model has `max_length=128` on the `name` field
(`models_registry.py:20`), the service layer (`service.py:44`) does not validate
the name length before attempting to persist. This means the DB will enforce it
(for databases that respect column length), but SQLite (used in tests and dev)
does not enforce `VARCHAR(128)`.

`MAX_DESCRIPTION_LENGTH = 1024` is defined but not enforced anywhere.

**Recommendation:** Add validation in `AgentRegistryService.register_agent()`.

---

## 8. Performance

### 8.1 [MEDIUM] Full Table Scan in `evaluate_subscriptions`

**File:** `temper_ai/events/_bus_helpers.py:72-80`
```python
stmt = select(EventSubscription).where(
    EventSubscription.active == True  # noqa: E712
)
active_subs = session.exec(stmt).all()

return [
    sub for sub in active_subs
    if matches_filter(sub, event_type, payload, source_workflow_id)
]
```

This fetches **all** active subscriptions from the database, then filters in Python.
The SQL query does not filter by `event_type`, which is indexed. For a system with
many subscriptions, this will become a performance bottleneck.

**Recommendation:** Add `event_type` to the SQL WHERE clause:
```python
stmt = select(EventSubscription).where(
    EventSubscription.active == True,
    EventSubscription.event_type == event_type,
)
```

Then apply only the source_workflow and payload_filter checks in Python.

### 8.2 Wait-for-Event Threading -- ACCEPTABLE

The `wait_for_event` mechanism uses `threading.Event` objects stored in a dict
with a lock. This is simple and correct for the expected low-concurrency use case.
Each waiter creates one `Event` object that is cleaned up in a `finally` block.
The lock scope is minimal.

---

## 9. Test Quality

### 9.1 Coverage Assessment

| Module | Test File(s) | Test Count | Coverage |
|---|---|---|---|
| `events/event_bus.py` | `test_event_bus.py`, `test_integration.py` | ~50 | High |
| `events/subscription_registry.py` | `test_subscription_registry.py` | 14 | High |
| `events/_cross_workflow.py` | `test_cross_workflow.py` | 14 | High |
| `events/_schemas.py` | `test_schemas.py` | 11 | High |
| `events/models.py` | `test_models.py` | 7 | High |
| `events/_bus_helpers.py` | (via event_bus tests) | Indirect | Medium |
| `events/_subscription_helpers.py` | (via event_bus tests) | Indirect | Medium |
| `events/constants.py` | (used in imports) | N/A | N/A |
| Workflow integration | `test_workflow_integration.py` | 13 | High |
| Stage compiler events | `test_stage_compiler_events.py` | 11 | High |
| Event-triggered node | `test_event_triggered_node.py` | 8 | High |
| CLI event commands | `test_event_commands.py` | 10 | High |
| `registry/service.py` | `test_service.py` | 12 | High |
| `registry/store.py` | `test_store.py` | 13 | High |
| `registry/_schemas.py` | `test_schemas.py` | 12 | High |
| `registry/_helpers.py` | `test_helpers.py` | 10 | High |
| CLI agent commands | `test_agent_commands.py` | 10 | High |
| API agent routes | `test_agent_routes.py` | 11 | High |
| Config schema M9 fields | `test_config_schema.py` | 12 | High |

**Total: 236 tests, all passing.**

### 9.2 Test Quality Observations

**Strengths:**
- Every test has at least one assertion
- Good use of in-memory SQLite fixtures for DB-backed tests
- Tests cover both happy paths and error paths consistently
- Tests verify behavior at multiple layers (unit, integration, CLI, API)
- Good use of mock injection via `patch()` for external dependencies
- Tests verify that errors don't crash the system (e.g., `test_emit_db_failure_does_not_crash`)

**Gaps:**
- No direct unit tests for `_bus_helpers.py` functions (`persist_event`,
  `evaluate_subscriptions`, `convert_to_observability_event`) -- only tested
  indirectly through `TemperEventBus`
- No direct unit tests for `matches_filter` with edge cases (e.g., payload_filter
  with None payload, empty payload_filter dict)
- No concurrency/thread-safety tests for `_HANDLER_REGISTRY` (module-level mutable dict)
- No test for the `_new_id()` dead code in models.py (expected, since it's dead)

---

## 10. Architectural Alignment

### 10.1 Radical Modularity -- GOOD

Both modules follow the project's modular architecture principles:
- Clean separation between schemas, store, service, and helpers
- Lazy imports to avoid circular dependencies
- Context manager patterns for DB session management
- Composition over inheritance in the event bus

### 10.2 Observability Integration -- GOOD

The event bus integrates with the existing `ObservabilityEventBus` via composition,
converting events to `ObservabilityEvent` objects. This ensures all events flow through
the observability pipeline for tracing and metrics.

### 10.3 Multi-Tenancy -- GAP

Neither module has tenant scoping. Events and subscriptions are global, not scoped to
a tenant. The registry store has no `tenant_id` filtering. This is a known gap --
M10 added tenant scoping to other modules but these were not yet integrated.

---

## 11. Findings Summary

| # | Severity | Category | File:Line | Description |
|---|---|---|---|---|
| F1 | HIGH | Bug | `_bus_helpers.py:105` | `datetime.now()` produces timezone-naive timestamp; should use `utcnow()` |
| F2 | MEDIUM | Performance | `_bus_helpers.py:72-80` | Full table scan of all active subscriptions; should filter by `event_type` in SQL |
| F3 | MEDIUM | Security | `event_bus.py:93` | No `event_type` validation or length limit on emitted events |
| F4 | MEDIUM | Security | `event_bus.py:122` | No authorization check on `agent_id` in `subscribe_persistent` |
| F5 | MEDIUM | Security | `service.py:43` | No path validation on `config_path` before `open()` |
| F6 | MEDIUM | Validation | `constants.py:14` | `MAX_PAYLOAD_SIZE_BYTES` defined but never enforced |
| F7 | MEDIUM | Validation | `registry/constants.py:9-10` | `MAX_AGENT_NAME_LENGTH` / `MAX_DESCRIPTION_LENGTH` not enforced at service layer |
| F8 | LOW | Dead Code | `events/models.py:47-49` | `_new_id()` function is never called |
| F9 | LOW | Dead Code | `registry/_helpers.py:15-20` | `build_persistent_memory_config()` unused in production |
| F10 | LOW | Dead Code | `registry/_schemas.py:10-13` | `PersistenceConfig` schema unused in production |
| F11 | LOW | Dead Code | `registry/constants.py:11` | `DEFAULT_INVOCATION_TIMEOUT` constant never referenced |

---

## 12. Recommendations (Priority Order)

1. **Fix `datetime.now()` bug** (F1) -- Replace with `utcnow()` in `_bus_helpers.py:105`.
   One-line fix, high impact on data consistency.

2. **Add `event_type` to subscription SQL query** (F2) -- Modify `evaluate_subscriptions`
   to filter by `event_type` in the WHERE clause instead of Python-side filtering.

3. **Enforce `MAX_PAYLOAD_SIZE_BYTES`** (F6) -- Add a size check in `persist_event()` or
   `TemperEventBus.emit()` before persisting.

4. **Validate `config_path` in registry** (F5) -- Use `path_safety.validator` to restrict
   agent config paths to allowed directories.

5. **Add name/description length validation** (F7) -- Validate in
   `AgentRegistryService.register_agent()` before DB persistence.

6. **Remove dead code** (F8-F11) -- Clean up `_new_id()`, `build_persistent_memory_config`,
   `PersistenceConfig`, and `DEFAULT_INVOCATION_TIMEOUT` if no future use is planned.

7. **Add direct unit tests for helpers** -- Test `persist_event`, `evaluate_subscriptions`,
   `convert_to_observability_event`, and `matches_filter` edge cases directly.

8. **Tenant-scope events/registry** -- When M10 multi-tenancy is extended, add `tenant_id`
   filtering to event queries and registry operations.
