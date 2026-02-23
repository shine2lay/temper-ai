# Audit #32: plugins/ + mcp/ Modules

**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6
**Scope:** `temper_ai/plugins/` (11 files) + `temper_ai/mcp/` (8 files) -- 19 source files total
**Tests:** `tests/test_plugins/` (211 tests, all pass) + `tests/test_mcp/` (69 tests, all pass) -- 280 tests total

---

## Executive Summary

Both modules are **well-architected** with clean separation of concerns, proper lazy loading patterns, and comprehensive test suites. The plugin system follows the adapter pattern cleanly across four framework integrations (CrewAI, LangGraph, OpenAI Agents, AutoGen). The MCP module implements both client and server sides with a robust sync-to-async bridge.

**Overall Grade: B+**

| Dimension | Grade | Notes |
|---|---|---|
| Code Quality | A- | Clean, well-structured, all functions under 50 lines |
| Security | B | Token comparison is timing-vulnerable; LangGraph imports arbitrary modules |
| Error Handling | A | Graceful degradation everywhere; servers that fail don't block others |
| Modularity | A | Clean plugin interface, proper use of abstract base class |
| Feature Completeness | B+ | PLUGIN_DEFAULT_TIMEOUT imported but never enforced |
| Test Quality | A- | 280 tests, good coverage, every adapter tested |
| Architecture | A- | Aligns well with Radical Modularity; proper lazy imports |

**Critical findings: 1 | High: 3 | Medium: 5 | Low: 4 | Info: 3**

---

## Critical Findings

### C-01: MCP Bearer Auth Uses String Equality (Timing Attack)

**File:** `temper_ai/mcp/server.py:23`
**Severity:** CRITICAL
**Category:** Security

```python
if not auth.startswith("Bearer ") or auth[7:].strip() != self._api_key:
```

The `!=` operator for string comparison is not constant-time. An attacker can measure response time differences to brute-force the API key one character at a time. This is the sole authentication mechanism for the HTTP MCP transport.

**Fix:** Use `hmac.compare_digest()` for constant-time comparison:
```python
import hmac
if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:].strip(), self._api_key):
```

---

## High-Severity Findings

### H-01: LangGraph Adapter Imports Arbitrary Python Modules

**File:** `temper_ai/plugins/adapters/langgraph_adapter.py:49`
**Severity:** HIGH
**Category:** Security

```python
module = importlib.import_module(graph_module)
```

The `graph_module` value comes from the agent config's `plugin_config` dict. If config is user-supplied (e.g., via the config import API (`POST /api/configs/import`) or the config API), an attacker can specify any importable module path. `importlib.import_module()` executes module-level code on import, which could lead to arbitrary code execution.

**Mitigations already present:** The config must be a valid YAML agent config and must go through the plugin system. However, there is no allowlist or validation of the module path.

**Recommendation:** Add a configurable allowlist of permitted module prefixes, or at minimum validate that the module path does not start with known dangerous prefixes (e.g., `os`, `subprocess`, `shutil`). Document the security boundary clearly.

### H-02: MCP Transport Context Managers Never Closed

**File:** `temper_ai/mcp/manager.py:111-139`
**Severity:** HIGH
**Category:** Resource Leak

`disconnect_all()` only calls `session.__aexit__()` on the `ClientSession` objects. The transport context managers (stdio_client / sse_client / streamablehttp_client) stored in `self._context_managers` are never exited.

```python
# _connect_stdio stores both:
self._context_managers[config.name] = (ctx, session)  # line 204

# But disconnect_all only closes sessions, not transports:
async def _close(s: Any) -> None:
    await s.__aexit__(None, None, None)  # line 118 -- only session
```

This means subprocess pipes (stdio) or HTTP connections (SSE/streamable) are leaked on disconnect. The subprocess (e.g., `npx`) may remain running as an orphan process.

**Fix:** Iterate `self._context_managers` and call `ctx.__aexit__()` for the transport context as well, after closing the session.

### H-03: PLUGIN_DEFAULT_TIMEOUT Imported But Never Enforced

**File:** `temper_ai/plugins/base.py:17`, all 4 adapters
**Severity:** HIGH
**Category:** Feature Completeness

`PLUGIN_DEFAULT_TIMEOUT` (600s) is imported with `# noqa: F401` in `base.py` and all four adapters, but **never actually used** to enforce a timeout on external framework execution. A hung CrewAI kickoff, LangGraph graph invocation, or OpenAI Runner.run_sync call will block indefinitely with no timeout.

```python
# base.py line 17:
from temper_ai.plugins.constants import PLUGIN_DEFAULT_TIMEOUT  # noqa: F401
# All 4 adapters import it too but never reference it
```

**Recommendation:** Wrap `_execute_external()` in a timeout mechanism (e.g., `concurrent.futures.ThreadPoolExecutor` with timeout, or `signal.alarm` on Unix).

---

## Medium-Severity Findings

### M-01: `_check_framework_available` Imports Full Module Instead of Using find_spec

**File:** `temper_ai/plugins/registry.py:102-109`
**Severity:** MEDIUM
**Category:** Performance / Side Effects

```python
def _check_framework_available(framework_package: str) -> bool:
    try:
        import importlib
        importlib.import_module(framework_package)
        return True
    except ImportError:
        return False
```

Using `importlib.import_module()` for an availability check executes the module's top-level code (which can be slow or have side effects for heavy frameworks like CrewAI). The `health_check()` methods in the adapters correctly use `importlib.util.find_spec()` instead.

**Fix:** Use `importlib.util.find_spec(framework_package) is not None`.

### M-02: `get_health_checks` Has Redundant Duplicate Logic

**File:** `temper_ai/plugins/registry.py:112-156`
**Severity:** MEDIUM
**Category:** Dead Code / Modularity

`get_health_checks()` and `_call_class_health_check()` duplicate the availability-checking logic that already exists in each adapter's `health_check()` method. The function tries to construct a "sentinel instance" approach but ends up never instantiating the adapter -- it just checks `find_spec` again.

Both functions also re-import `importlib` and `importlib.util` at the top of their bodies (lines 118-119, 143-145), which is redundant since the module already has `import importlib` at the function scope.

**Recommendation:** Either call the adapter's `health_check()` via a lightweight config mock, or simplify to a single `find_spec` + version check. Remove the intermediate `_call_class_health_check` wrapper.

### M-03: BearerAuthMiddleware Does Not Handle WebSocket Scope

**File:** `temper_ai/mcp/server.py:20`
**Severity:** MEDIUM
**Category:** Security

```python
if scope["type"] == "http":
    # auth check
await self._app(scope, receive, send)
```

Only `http` scope is authenticated. If the MCP server exposes WebSocket endpoints (which SSE/streamable HTTP transports may use), those requests pass through without authentication. The `streamablehttp_client` in mcp SDK uses Server-Sent Events over HTTP, but future MCP transports could use WebSockets.

**Recommendation:** Also authenticate `scope["type"] == "websocket"` connections, or explicitly document that WebSocket scopes are intentionally unauthenticated and why.

### M-04: AutoGen Adapter's async/sync Bridge Is Fragile

**File:** `temper_ai/plugins/adapters/autogen_adapter.py:69-90`
**Severity:** MEDIUM
**Category:** Reliability

```python
def _execute_external(self, input_data: dict[str, Any]) -> str:
    import asyncio
    try:
        asyncio.get_running_loop()
        raise RuntimeError("AutoGenAgent._execute_external() cannot be called from an async context.")
    except RuntimeError as exc:
        if "_execute_external" in str(exc):
            raise
```

This pattern checks if there is a running event loop by catching `RuntimeError` from `get_running_loop()`. The string match `"_execute_external" in str(exc)` is brittle -- if the RuntimeError message changes or if the exception message happens to contain that substring from another source, the behavior would be incorrect.

**Recommendation:** Use a sentinel flag or check `type(exc).__name__` more robustly. Alternatively, use `asyncio.run()` in a separate thread if a loop is already running.

### M-05: MCP Server run_workflow Allows Absolute Path Input

**File:** `temper_ai/mcp/server.py:192-197`
**Severity:** MEDIUM
**Category:** Security

```python
config_root_resolved = Path(config_root).resolve()
workflow_file = (config_root_resolved / workflow_path).resolve()
try:
    workflow_file.relative_to(config_root_resolved)
except ValueError:
    return json.dumps({"error": "Invalid workflow path: path traversal not allowed"})
```

The path traversal check is correct for relative paths (e.g., `../../etc/passwd`). However, if `workflow_path` is an absolute path like `/etc/passwd`, `(config_root_resolved / "/etc/passwd").resolve()` evaluates to `/etc/passwd` on Python, which correctly fails the `relative_to` check. This is safe but relies on subtle Python behavior. An explicit check for absolute paths would be more defensive:

```python
if Path(workflow_path).is_absolute():
    return json.dumps({"error": "Absolute paths not allowed"})
```

---

## Low-Severity Findings

### L-01: Unused `PLUGIN_CONFIG_KEY` and `FRAMEWORK_CONFIG_KEY` Constants

**File:** `temper_ai/plugins/constants.py:20-21`
**Severity:** LOW
**Category:** Dead Code

```python
PLUGIN_CONFIG_KEY = "plugin_config"
FRAMEWORK_CONFIG_KEY = "framework_config"
```

These constants are defined but never imported or used anywhere in the codebase.

### L-02: All Four Adapters Import `PLUGIN_DEFAULT_TIMEOUT` Unused

**File:** All adapter files line 10-11
**Severity:** LOW
**Category:** Dead Code

Every adapter file (`crewai_adapter.py`, `langgraph_adapter.py`, `openai_agents_adapter.py`, `autogen_adapter.py`) imports `PLUGIN_DEFAULT_TIMEOUT` with `# noqa: F401` but never references it. This is related to H-03 (timeout never enforced) but is additionally a dead import across 5 files (including base.py).

### L-03: `_sanitize_name` Truncation Length Is Uncommented

**File:** `temper_ai/plugins/_import_helpers.py:33`
**Severity:** LOW
**Category:** Code Quality

```python
return sanitized.lower()[:64] or "unnamed_agent"  # scanner: skip-magic
```

The `64` truncation length uses the scanner skip comment but lacks documentation explaining why 64 was chosen. Is this a database column limit? A convention?

### L-04: `disconnect_all` Defines Coroutine Inside Loop Body

**File:** `temper_ai/mcp/manager.py:117-131`
**Severity:** LOW
**Category:** Code Quality

The `async def _close(s)` coroutine and `def _do_close()` closure are redefined on every iteration of the for loop. While functionally correct (since `future.result()` blocks before the next iteration), this is unnecessary allocation. Define `_close` once outside the loop.

---

## Informational Notes

### I-01: Lazy Import Pattern Is Consistent and Well-Applied

Both `temper_ai/plugins/__init__.py` and `temper_ai/mcp/__init__.py` use the `__getattr__` pattern for lazy imports, correctly avoiding the need to import heavy optional dependencies (crewai, mcp SDK, etc.) at module load time. This aligns with the project's fan-out minimization strategy.

### I-02: Plugin Schema Classes Are Not Used by Adapters

The `_schemas.py` file defines `CrewAIPluginConfig`, `LangGraphPluginConfig`, `OpenAIAgentsPluginConfig`, and `AutoGenPluginConfig` as Pydantic models, but the adapters use `self._get_plugin_config()` which returns a raw dict. The typed schemas are useful for documentation and validation but are not enforced during execution. This is a potential enhancement opportunity: validate `plugin_config` against the appropriate schema subclass during `_initialize_external_agent()`.

### I-03: MCP `asyncio.ensure_future(coro, loop=loop)` Deprecation Path

**Files:** `temper_ai/mcp/manager.py` (3 occurrences), `temper_ai/mcp/tool_wrapper.py` (1 occurrence)

`asyncio.ensure_future(..., loop=...)` has the `loop` parameter deprecated since Python 3.10. While it still works in Python 3.12, it will be removed in a future version. The current code passes `loop=self._loop` explicitly because it runs on a background thread with a dedicated loop.

**Recommendation:** When migrating to Python 3.13+, switch to `loop.create_task(coro)` called via `loop.call_soon_threadsafe()`.

---

## Test Coverage Assessment

### Plugin Tests: 211 tests across 11 files

| File | Tests | Coverage Notes |
|---|---|---|
| test_base.py | ~35 | ABC enforcement, execution, capabilities, error handling, config extraction |
| test_registry.py | ~15 | is_plugin_type, ensure_plugin_registered, list_plugins |
| test_crewai_adapter.py | ~25 | Init, initialize, execute, translate_config, AgentFactory integration |
| test_langgraph_adapter.py | ~20 | Graph loading, custom keys, recursion limit, translate_config |
| test_openai_agents_adapter.py | ~20 | Agent creation, Runner.run_sync, translate_config |
| test_autogen_adapter.py | ~25 | Async bridge, model client config, translate_config |
| test_schemas.py | ~25 | All 5 schema classes validated |
| test_import_helpers.py | ~20 | YAML loading, sanitization, build config, write YAML |
| test_cli.py | ~15 | list, import, error paths |
| conftest.py | -- | Shared fixtures |

**Gaps:** No test for `get_health_checks()` async function. No test for `_check_framework_available` with an actual importable module.

### MCP Tests: 69 tests across 7 files

| File | Tests | Coverage Notes |
|---|---|---|
| test_schemas.py | ~10 | Transport validation, timeouts, namespace defaults |
| test_manager.py | ~8 | Max servers, connect_all, namespace collision, server failure, disconnect |
| test_tool_wrapper.py | ~12 | Annotations, namespace, schema, result conversion, timeout, safe_execute |
| test_server.py | ~18 | Scan helpers, create_mcp_server, run_workflow_impl, get_run_status_impl |
| test_cli.py | ~8 | serve help, stdio/http modes, import error, list-tools |
| test_integration.py | ~10 | Registry coexistence, AgentConfig parsing, base_agent registration |

**Gaps:** No test for transport context manager cleanup (relates to H-02). No test for `BearerAuthMiddleware` authentication logic directly (tested only via CLI test indirectly). No test for `_connect_stdio` or `_connect_http` directly (requires mcp SDK).

---

## Recommendations Summary

### Must Fix (Before v1.0)

1. **C-01:** Replace string `!=` with `hmac.compare_digest()` in BearerAuthMiddleware
2. **H-02:** Close transport context managers in `disconnect_all()` to prevent subprocess/connection leaks
3. **H-03:** Implement actual timeout enforcement for external plugin execution using `PLUGIN_DEFAULT_TIMEOUT`

### Should Fix

4. **H-01:** Add module path allowlist or validation for LangGraph `graph_module` import
5. **M-01:** Use `find_spec()` instead of `import_module()` in `_check_framework_available`
6. **M-03:** Authenticate WebSocket scopes in BearerAuthMiddleware
7. **M-05:** Add explicit absolute path rejection in `_run_workflow_impl`

### Nice to Have

8. **M-02:** Simplify `get_health_checks` / remove `_call_class_health_check`
9. **M-04:** Use a more robust async loop detection pattern in AutoGen adapter
10. **L-01/L-02:** Remove unused constants and dead imports
11. **I-02:** Validate plugin_config against typed schema during initialization
12. **I-03:** Plan migration path for deprecated `asyncio.ensure_future(loop=)` parameter

---

## File Index

### temper_ai/plugins/ (11 files, ~550 LOC)

| File | LOC | Functions | Classes | Notes |
|---|---|---|---|---|
| `__init__.py` | 33 | 1 | 0 | Lazy `__getattr__` pattern |
| `constants.py` | 22 | 0 | 0 | 4 type constants, timeout, 2 unused key constants |
| `_schemas.py` | 67 | 0 | 5 | Pydantic models for all frameworks |
| `base.py` | 155 | 0 | 1 | `ExternalAgentPlugin` ABC, template method pattern |
| `registry.py` | 157 | 5 | 0 | Lazy loading, thread-safe registration |
| `_import_helpers.py` | 78 | 4 | 0 | YAML loading, config building, file writing |
| `adapters/__init__.py` | 2 | 0 | 0 | Empty docstring |
| `adapters/crewai_adapter.py` | 104 | 0 | 1 | CrewAI Agent + Crew + Task |
| `adapters/langgraph_adapter.py` | 95 | 0 | 1 | importlib.import_module for graph loading |
| `adapters/openai_agents_adapter.py` | 88 | 0 | 1 | agents.Agent + Runner.run_sync |
| `adapters/autogen_adapter.py` | 133 | 0 | 1 | Async-first with sync bridge |

### temper_ai/mcp/ (8 files, ~500 LOC)

| File | LOC | Functions | Classes | Notes |
|---|---|---|---|---|
| `__init__.py` | 26 | 1 | 0 | Lazy `__getattr__` pattern |
| `constants.py` | 16 | 0 | 0 | Timeouts, limits, separator |
| `_schemas.py` | 66 | 0 | 1 | `MCPServerConfig` with transport validation |
| `_client_helpers.py` | 81 | 3 | 0 | Event loop thread, annotation mapping |
| `_server_helpers.py` | 77 | 3 | 0 | Config scanning, result formatting |
| `manager.py` | 262 | 0 | 1 | `MCPManager` with connection lifecycle |
| `server.py` | 263 | 6 | 1 | FastMCP server, Bearer auth, workflow execution |
| `tool_wrapper.py` | 141 | 0 | 1 | `MCPToolWrapper` extends BaseTool |

---

## Code Quality Metrics

| Metric | plugins/ | mcp/ | Standard |
|---|---|---|---|
| Max function length | 34 lines (translate_config) | 38 lines (connect_all) | <=50 |
| Max params per function | 5 (build_agent_config_dict) | 5 (MCPToolWrapper.__init__) | <=7 |
| Max nesting depth | 3 | 3 | <=4 |
| Fan-out per module | 4 | 5 | <8 |
| Magic numbers | 0 (all extracted to constants) | 0 | 0 |
| Broad exceptions | 1 (get_health_checks) | 3 (BLE001 annotated) | Justified |
| TODO/FIXME/HACK | 0 | 0 | 0 |
| Unused imports (noqa: F401) | 6 (PLUGIN_DEFAULT_TIMEOUT) | 0 | Should clean up |
