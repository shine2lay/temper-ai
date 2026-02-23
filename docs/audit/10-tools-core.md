# Audit 10: Tools Core Infrastructure

**Scope:** `temper_ai/tools/` core infrastructure files
**Files reviewed:** `__init__.py`, `base.py`, `registry.py`, `executor.py`, `loader.py`, `_executor_config.py`, `_executor_helpers.py`, `_registry_helpers.py`, `_schemas.py`, `tool_cache.py`, `workflow_rate_limiter.py`, `constants.py`, `tool_cache_constants.py`, `workflow_rate_limiter_constants.py`, `_search_helpers.py`
**Test files reviewed:** `tests/test_tools/test_executor.py`, `test_registry.py`, `test_tool_cache.py`, `test_workflow_rate_limiter.py`, `test_parameter_sanitization.py`, `test_tool_edge_cases.py`, `test_concurrent_limit_25.py`, `test_tool_config_loading.py`, `test_search_helpers.py`
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The tools core infrastructure is well-architected with strong security primitives, clean separation of concerns via helper modules, and comprehensive test coverage. The `BaseTool` abstract class provides a solid contract, the registry supports versioning, and the executor has robust timeout/rate-limiting/rollback capabilities. Security is a standout strength -- the `ParameterSanitizer` provides defense-in-depth against path traversal, command injection, SQL injection, and Unicode homoglyph attacks.

**Overall Grade: A- (91/100)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 90 | Clean decomposition; monkey-patching pattern is non-ideal |
| Security | 95 | Excellent sanitization, fail-closed policy, workspace boundaries |
| Error Handling | 92 | Comprehensive exception handling; 2 broad `except Exception` |
| Modularity | 88 | Good helper extraction; monkey-patched methods hurt discoverability |
| Feature Completeness | 93 | No TODOs/FIXMEs; all features fully implemented |
| Test Quality | 90 | Thorough coverage; minor gaps in loader template resolution |
| Architecture | 89 | Solid pillar alignment; async gap worth noting |

---

## 1. Code Quality

### 1.1 Function Length

All functions are within the 50-line limit. The longest functions are:

- `base.py:sanitize_command()` (lines 529-592) -- 63 lines including docstring, but the actual logic is split across `_check_dangerous_chars` and `_check_dangerous_patterns` helper methods. **Acceptable** given the extensive docstring.
- `_executor_helpers.py:execute_with_timeout()` (lines 537-591) -- 54 lines. Slightly over threshold when counting blank lines. The function handles cache check, workflow rate limit, concurrency slot, thread pool submission, timeout, rollback, and cache storage. **Recommendation:** Consider extracting the inner `try` block (lines 561-588) into a separate helper.

### 1.2 Parameter Count

All functions within 7-parameter limit. `ToolExecutor.__init__` uses the `ToolExecutorConfig` dataclass pattern to bundle parameters -- well done.

- `execute_with_timeout()` at `_executor_helpers.py:537` takes 7 parameters (executor, tool, params, timeout, snapshot, tool_name, context) -- exactly at the limit.

### 1.3 Nesting Depth

No functions exceed depth 4. Maximum observed is 3 levels (e.g., `_executor_helpers.py:execute_with_timeout` with try/try/if).

### 1.4 Naming and Constants

**Good:**
- All constants extracted to dedicated `constants.py`, `tool_cache_constants.py`, `workflow_rate_limiter_constants.py` files.
- No magic numbers in core files.
- Clear naming conventions throughout.

**Finding F-01 (Low): Inconsistent error prefix usage**
- `registry.py:83`: Uses `TOOL_ERROR_PREFIX` constant for error messages.
- `registry.py:100,106`: Also uses `TOOL_ERROR_PREFIX`.
- But `_registry_helpers.py:468` and other helper functions use inline `f"Tool not found: {name}"` strings without the prefix constant.
- **Impact:** Minor inconsistency, no functional issue.

### 1.5 Fan-out

Module fan-out counts (unique external module imports):

| File | Fan-out | Status |
|------|---------|--------|
| `base.py` | 4 (logging, abc, typing, pydantic, shared.constants) | OK |
| `registry.py` | 5 (logging, threading, typing, shared.utils, tools._registry_helpers, tools.base, tools.constants) | OK |
| `executor.py` | 7 (threading, weakref, collections, concurrent.futures, typing, shared.*, tools.*) | OK (at limit) |
| `_executor_helpers.py` | 6 (concurrent.futures, logging, threading, time, pathlib, typing, shared.*, tools.*) | OK |
| `_registry_helpers.py` | 5 (importlib, inspect, logging, pkgutil, pathlib, typing, shared.*, tools.*) | OK |

All within the 8-module fan-out limit.

### 1.6 Monkey-patched Methods Pattern

**Finding F-02 (Medium): Methods attached outside class body via monkey-patching**

Both `registry.py` (lines 238-247) and `executor.py` (lines 328-330) attach methods to classes after definition:

```python
# registry.py:238
ToolRegistry.list = _list  # type: ignore[attr-defined]
ToolRegistry.list_all = _list_all  # type: ignore[attr-defined]
ToolRegistry.count = _count  # type: ignore[attr-defined]
# ... 8 more
```

This is done to keep the class under the "god-class" method count threshold while preserving backward compatibility. While functional, it has drawbacks:
- Methods are invisible to IDE autocompletion and type checkers (hence `# type: ignore`)
- Code navigation tools cannot find method definitions
- `_registry_helpers.py` also defines `ToolRegistryReportingMixin` and `ToolRegistryValidationMixin` (lines 507-544) that are **never used** -- dead code left from a prior refactoring attempt

**Recommendation:** Use the mixin classes that already exist in `_registry_helpers.py`, or use `Protocol` + composition. Delete unused mixins if not adopted.

---

## 2. Security

### 2.1 Parameter Sanitization (Excellent)

`base.py` `ParameterSanitizer` provides defense-in-depth:

- **Path traversal:** Null byte detection, `..` component rejection before `resolve()`, `allowed_base` boundary check (lines 425-484)
- **Command injection:** Unicode NFKC normalization (prevents homoglyph bypass), dangerous character blocklist, pattern detection for `$()`, `${}`, brace expansion (lines 529-592)
- **SQL injection:** Pattern-based detection for UNION, stacked queries, boolean injection, stored procedures (lines 681-742)
- **Input validation:** String length and integer range validators (lines 594-678)

**Finding F-03 (Info): URL-encoded path traversal not caught**
`base.py:124-144` documents that URL-encoded payloads like `..%2F` pass through because the sanitizer works on decoded strings. The test at line 131-143 explicitly documents this as expected behavior, noting the web framework should decode first. This is a conscious design decision, not a bug.

### 2.2 Workspace Path Enforcement

`_executor_helpers.py:29-52` `validate_workspace_path()` enforces that file paths stay within the workspace:
- Null byte rejection
- Path resolution + `relative_to()` check (catches symlink escapes)
- Applied to all path-like parameters via `_WORKSPACE_PATH_KEYS` tuple (line 375)

**Finding F-04 (Low): Hardcoded path parameter keys**
`_executor_helpers.py:375`:
```python
_WORKSPACE_PATH_KEYS = ("path", "file_path", "directory", "filename", "output_path")
```
If a new tool uses a different parameter name for paths (e.g., `source_path`, `target_dir`), it would bypass workspace validation. Consider making this configurable per-tool via metadata or a method on `BaseTool`.

### 2.3 Policy Engine Integration (Fail-Closed)

`_executor_helpers.py:426-468` `validate_policy()`:
- Catches broad exception list (`TypeError, ValueError, KeyError, AttributeError, ImportError, RuntimeError`)
- On ANY exception, returns blocked `ToolResult` (fail-closed pattern)
- Line 461: `logger.error(f"Policy validation error (fail-closed): {e}")` -- good logging

The fail-closed behavior is verified by `test_executor.py:TestPolicyFailClosed` (4 tests).

### 2.4 Error Message Information Leakage

**Finding F-05 (Low): Tool execution errors may leak internal details**

`_executor_helpers.py:152`:
```python
error=f"Unhandled exception in tool: {str(e)}"
```

And `executor.py:199`:
```python
error="Tool execution failed due to an internal error"
```

The executor's `_handle_execution_error` properly sanitizes the message. However, `execute_tool_internal` passes the raw exception string. For production, consider sanitizing exception details in tool results returned to LLMs.

### 2.5 SQL Injection Sanitizer Limitations

**Finding F-06 (Low): Case-sensitive partial match in SQL sanitizer**

`base.py:729-731`:
```python
value_upper = value.upper()
for pattern in dangerous_patterns:
    if pattern in value_upper:
```

This correctly uppercases the input but the patterns are already uppercase. However, it uses simple substring matching, so legitimate strings containing "SELECT" (e.g., "Please select an option") would be falsely rejected. The docstring correctly notes this is "defense-in-depth only" and parameterized queries are the primary defense.

---

## 3. Error Handling

### 3.1 Exception Handling Patterns

The codebase consistently uses specific exception types rather than broad catches:

- `base.py:216,226`: `(TypeError, ValueError, KeyError, AttributeError)` and `(RuntimeError, TypeError, ValueError, OSError, KeyError, AttributeError)`
- `_executor_helpers.py:148`: Same pattern in `execute_tool_internal`
- `executor.py:240`: `(RuntimeError, OSError, MemoryError)` for execution errors

**Finding F-07 (Medium): Two broad `except Exception` catches**

1. `_registry_helpers.py:356`:
```python
except Exception as e:
    raise ToolRegistryError(
        f"Failed to load tool configuration '{config_name}': {e}"
    )
```
This wraps config loading errors. Since `ConfigLoader.load_tool` can raise arbitrary exceptions from YAML parsing, file I/O, and validation, this is arguably justified. Still, it would be better to catch `(OSError, ValueError, yaml.YAMLError, KeyError)`.

2. `_executor_helpers.py:490`:
```python
except Exception as e:
    logger.warning(f"Failed to persist rollback snapshot to DB: {e}")
```
This is in `create_snapshot` for observability logging -- a non-critical operation. Broad catch is acceptable here since we don't want observability failures to prevent tool execution.

### 3.2 Timeout Handling

`_executor_helpers.py:537-591` `execute_with_timeout()`:
- Uses `concurrent.futures.ThreadPoolExecutor` with `future.result(timeout=timeout)`
- On timeout: cancels future, triggers rollback if applicable, returns structured error
- Concurrent slot is released in `finally` block (line 590-591) -- prevents slot leaks

**Finding F-08 (Info): Thread pool timeout does not kill running threads**
`future.cancel()` at line 582 only prevents queued tasks from starting; it cannot interrupt a thread already executing `time.sleep()` or I/O. This is a fundamental Python limitation, documented by the timeout tests. The `weakref.finalize` cleanup (executor.py:150-155) provides eventual cleanup.

### 3.3 Rollback Error Handling

All rollback operations (`handle_auto_rollback`, `handle_timeout_rollback`, `handle_exception_rollback`) catch `(TypeError, ValueError, OSError, AttributeError)` and log failures without re-raising. This ensures rollback failures don't mask the original error.

### 3.4 Rate Limit Error Propagation

`check_rate_limit` raises `RateLimitError` which is caught by `executor.py:219` and converted to a failed `ToolResult`. Clean chain.

---

## 4. Modularity

### 4.1 Tool Registration Interface

The `BaseTool` abstract class (base.py:60-398) provides a clean, well-documented interface:
- `get_metadata()` -- required
- `get_parameters_schema()` -- required (JSON Schema format)
- `execute(**kwargs)` -- required
- `get_parameters_model()` -- optional (Pydantic model for validation)
- `get_result_schema()` -- optional (output contract for LLMs)
- `safe_execute()` -- no-exception wrapper
- `to_llm_schema()` -- OpenAI function calling format

Dual validation paths (Pydantic model or JSON Schema fallback) is a good design.

### 4.2 Plugin Extensibility

Tools can be:
1. **Auto-discovered** from the `temper_ai.tools` package (any `BaseTool` subclass)
2. **Loaded from YAML config** via `load_from_config()` with dynamic class loading
3. **Manually registered** via `registry.register(tool_instance)`

The auto-discovery includes fresh instance creation from cache (`_registry_helpers.py:112-113`) to prevent cross-agent config contamination -- a subtle but important fix.

### 4.3 Dead Code

**Finding F-09 (Low): Unused mixin classes in `_registry_helpers.py`**

Lines 507-544 define `ToolRegistryReportingMixin` and `ToolRegistryValidationMixin` that are never imported or used anywhere in the codebase. These appear to be remnants of a refactoring that was replaced by the monkey-patching approach.

```python
class ToolRegistryReportingMixin:
    """Mixin providing reporting and query methods for ToolRegistry."""
    ...

class ToolRegistryValidationMixin:
    """Mixin providing validation methods for ToolRegistry."""
    ...
```

### 4.4 Helper Module Decomposition

The extraction of helpers is well-done:
- `_executor_config.py` -- config dataclass (reduces constructor params)
- `_executor_helpers.py` -- all execution logic (concurrency, rate limiting, rollback, batch, validation, policy, cache)
- `_registry_helpers.py` -- auto-discovery, config loading, validation, reporting, version comparison
- `_search_helpers.py` -- shared search result models

Each helper module has clear responsibilities and the `TYPE_CHECKING` pattern prevents circular imports.

### 4.5 Loader Module

`loader.py` provides template resolution for tool configs, supporting Jinja2 `{{ variable }}` syntax. The template system:
- Saves original templates in `_templates` key for re-execution (lines 65-68)
- Creates new dicts to prevent cross-agent contamination (lines 46-49)
- Uses simple regex replacement instead of full Jinja2 (simpler but less flexible)

**Finding F-10 (Low): Template rendering uses regex, not Jinja2**

Despite the docstrings mentioning "Jinja2 template strings", `_render_template_value` (loader.py:113-120) uses `re.finditer(r"\{\{\s*(\w+)\s*\}\}", template)` for simple variable substitution. This doesn't support Jinja2 features like filters, conditionals, or nested access (`{{ data.name }}`). The function name and docstrings should clarify this is simple variable interpolation, not full Jinja2.

---

## 5. Feature Completeness

### 5.1 TODO/FIXME/HACK Search

**Zero** TODO, FIXME, or HACK markers found in any scoped file. All features appear fully implemented.

### 5.2 Feature Inventory

| Feature | Status | Quality |
|---------|--------|---------|
| Tool base class + interface | Complete | Excellent |
| Parameter validation (JSON Schema + Pydantic) | Complete | Good |
| Parameter sanitization (path, command, SQL) | Complete | Excellent |
| Tool registry with versioning | Complete | Good |
| Auto-discovery + caching | Complete | Good |
| Config-based tool loading | Complete | Good |
| Tool executor with timeout | Complete | Good |
| Concurrent execution limiting | Complete | Excellent |
| Rate limiting (per-executor) | Complete | Good |
| Workflow-level rate limiting | Complete | Good |
| Tool result caching (LRU + TTL) | Complete | Excellent |
| Policy engine integration (fail-closed) | Complete | Excellent |
| Rollback/snapshot integration | Complete | Good |
| Batch execution | Complete | Good |
| Template resolution for configs | Complete | Good |
| LLM schema generation | Complete | Good |

### 5.3 Async Support Gap

**Finding F-11 (Medium): No async tool execution path**

All tool execution is synchronous, wrapped in a `ThreadPoolExecutor`. There is no `async execute()` or `async safe_execute()` on `BaseTool`, and no `async execute()` on `ToolExecutor`. For I/O-bound tools (HTTP, web scraping, search), this means each concurrent tool occupies a thread.

The workflow engine uses `asyncio` elsewhere, but tool execution is always synchronous. This is a known architectural decision but limits scalability for I/O-heavy tool workloads.

---

## 6. Test Quality

### 6.1 Coverage Analysis

| Module | Test File | Test Count | Coverage |
|--------|-----------|------------|----------|
| `base.py` (ParameterSanitizer) | `test_parameter_sanitization.py` | 45+ tests | Excellent |
| `registry.py` | `test_registry.py` | 40+ tests | Excellent |
| `executor.py` + helpers | `test_executor.py` | 50+ tests | Excellent |
| `executor.py` (concurrency) | `test_concurrent_limit_25.py` | 7 tests | Excellent |
| `tool_cache.py` | `test_tool_cache.py` | 22 tests | Excellent |
| `workflow_rate_limiter.py` | `test_workflow_rate_limiter.py` | 12 tests | Good |
| `_registry_helpers.py` (config) | `test_tool_config_loading.py` | 13 tests | Good |
| `_search_helpers.py` | `test_search_helpers.py` | 12 tests | Excellent |
| `loader.py` | **No dedicated tests** | 0 | **Gap** |

### 6.2 Test Strengths

- **Concurrency testing** is exemplary: `test_executor.py` includes 15-thread rate limiter tests, TOCTOU verification, sliding window correctness across phases, stress tests with 50 concurrent calls
- **Security testing** is thorough: OWASP payloads, Unicode homoglyph bypass, null bytes, command substitution patterns
- **Thread safety** tests use `threading.Barrier` for synchronized starts
- All tests use proper `try/finally` with `executor.shutdown()` for cleanup

### 6.3 Coverage Gaps

**Finding F-12 (Medium): No tests for `loader.py` template resolution**

`loader.py` has 121 lines of template resolution logic (`resolve_tool_config_templates`, `_resolve_single_tool_templates`, `_render_template_value`, `ensure_tools_discovered`, `resolve_tool_spec`, `apply_tool_config`) with no dedicated test file. While some of this is tested indirectly through integration tests, the following scenarios lack coverage:

- Template re-resolution on subsequent executions (the `_templates` save/restore logic)
- `apply_tool_config` creating new dict to prevent contamination
- `resolve_tool_spec` with both string and object tool specs
- `_render_template_value` with multiple variables and partial matches
- `ensure_tools_discovered` edge cases

**Finding F-13 (Low): Missing test for `_executor_helpers.py:validate_workspace_path`**

While workspace path validation is tested indirectly through `test_file_writer.py`, there are no direct unit tests for `validate_workspace_path()` in `_executor_helpers.py`. Edge cases like symlink escapes and concurrent path creation could benefit from targeted tests.

**Finding F-14 (Low): `ToolRegistryReportingMixin` and `ToolRegistryValidationMixin` untested**

The unused mixin classes in `_registry_helpers.py:507-544` have no tests (nor should they, since they're dead code).

### 6.4 Test Quality Issues

**Finding F-15 (Info): Duplicate `@pytest.mark.timeout` decorators**

`test_executor.py:653-654`:
```python
@pytest.mark.timeout(30)
@pytest.mark.timeout(15)
def test_timeout_during_batch_execution(self):
```
Two timeout decorators on the same test. The second (15) likely overrides the first. This is harmless but suggests copy-paste.

---

## 7. Architectural Alignment with Vision Pillars

### Pillar 1: Reliability
**Score: 9/10** -- Excellent timeout handling, concurrent slot release in `finally`, rate limiting, rollback on failure. The `weakref.finalize` pattern for thread pool cleanup prevents resource leaks even if `shutdown()` is not called.

### Pillar 2: Security
**Score: 9.5/10** -- Outstanding. ParameterSanitizer covers OWASP top vectors. Fail-closed policy engine. Workspace boundary enforcement. Unicode normalization for homoglyph attacks. Only gap is the hardcoded path parameter keys.

### Pillar 3: Observability
**Score: 8/10** -- Execution time tracked in metadata. Rollback events logged to observability. Cache hit/miss/eviction stats. Rate limit usage reporting. No OpenTelemetry spans for individual tool executions (those are in the LLM layer).

### Pillar 4: Extensibility
**Score: 8.5/10** -- Clean `BaseTool` interface. Three registration paths (auto, config, manual). Version support. Pydantic-first validation with JSON Schema fallback. The monkey-patching pattern slightly hurts extensibility since subclassing `ToolRegistry` would be confusing.

### Pillar 5: Performance
**Score: 8/10** -- LRU cache with TTL for read-only tools. Global tool discovery cache. Workflow-level rate limiting with blocking mode. No async path is the main gap.

### Pillar 6: Modularity
**Score: 8.5/10** -- Well-decomposed into helpers. Clean TYPE_CHECKING imports prevent cycles. The dead mixin code and monkey-patching pattern are minor blemishes.

### Pillar 7: Testability
**Score: 9/10** -- Excellent test coverage with concurrency, security, and edge case tests. The template resolution gap is the main miss.

---

## Findings Summary

| ID | Severity | File:Line | Description |
|----|----------|-----------|-------------|
| F-01 | Low | `_registry_helpers.py:468` | Inconsistent error prefix usage vs `TOOL_ERROR_PREFIX` constant |
| F-02 | Medium | `registry.py:238-247`, `executor.py:328-330` | Monkey-patched methods hurt IDE discoverability and type checking |
| F-03 | Info | `base.py:124-144` | URL-encoded path traversal not caught (documented as by-design) |
| F-04 | Low | `_executor_helpers.py:375` | Hardcoded `_WORKSPACE_PATH_KEYS` may miss custom tool path params |
| F-05 | Low | `_executor_helpers.py:152` | Raw exception strings in tool results may leak internal details |
| F-06 | Low | `base.py:710-731` | SQL sanitizer uses substring matching (false positives on "SELECT") |
| F-07 | Medium | `_registry_helpers.py:356`, `_executor_helpers.py:490` | Two broad `except Exception` catches |
| F-08 | Info | `_executor_helpers.py:582` | `future.cancel()` cannot kill running threads (Python limitation) |
| F-09 | Low | `_registry_helpers.py:507-544` | Dead code: unused `ToolRegistryReportingMixin` and `ToolRegistryValidationMixin` |
| F-10 | Low | `loader.py:113-120` | Template rendering uses regex, not actual Jinja2 despite docstring claims |
| F-11 | Medium | N/A | No async tool execution path (all sync + ThreadPoolExecutor) |
| F-12 | Medium | `loader.py` | No dedicated tests for template resolution logic |
| F-13 | Low | `_executor_helpers.py:29-52` | No direct unit tests for `validate_workspace_path` |
| F-14 | Low | `_registry_helpers.py:507-544` | Dead mixin classes untested |
| F-15 | Info | `test_executor.py:653-654` | Duplicate `@pytest.mark.timeout` decorator on same test |

---

## Recommendations (Priority Order)

### P1 (Should Fix)

1. **Add tests for `loader.py`** (F-12): Create `tests/test_tools/test_loader.py` covering template resolution, re-resolution, config contamination prevention, and edge cases. Estimated: 15-20 tests.

2. **Replace monkey-patching with composition or mixins** (F-02): Either use the already-defined mixin classes (`ToolRegistryReportingMixin`, `ToolRegistryValidationMixin`) or convert to a composition pattern. This will improve IDE support and code navigation.

3. **Narrow the two `except Exception` catches** (F-07): Replace with specific exception types:
   - `_registry_helpers.py:356`: `except (OSError, ValueError, KeyError, TypeError) as e:`
   - `_executor_helpers.py:490`: Acceptable as-is (non-critical observability path)

### P2 (Nice to Have)

4. **Remove dead mixin classes** (F-09): Delete `ToolRegistryReportingMixin` and `ToolRegistryValidationMixin` from `_registry_helpers.py` if the monkey-patching approach is kept.

5. **Make workspace path keys configurable** (F-04): Add a `get_path_parameters()` method to `BaseTool` or use tool metadata to declare which parameters are file paths.

6. **Clarify template docstrings** (F-10): Update `loader.py` docstrings to say "simple variable interpolation" instead of "Jinja2 template strings".

7. **Sanitize exception details in tool results** (F-05): For production, consider replacing raw exception strings with generic messages in `ToolResult.error` to prevent information leakage to LLMs.

### P3 (Future Consideration)

8. **Add async tool execution path** (F-11): Add `async execute()` to `BaseTool` and `ToolExecutor` for I/O-bound tools. This would improve scalability for web scraping, HTTP, and search tools.

9. **Add `validate_workspace_path` unit tests** (F-13): Direct tests with symlink escapes and edge cases.

---

## Files Reviewed (Full Paths)

### Source Files
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/__init__.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/base.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/registry.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/executor.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/loader.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/_executor_config.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/_executor_helpers.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/_registry_helpers.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/_schemas.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/_search_helpers.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/tool_cache.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/workflow_rate_limiter.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/constants.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/tool_cache_constants.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/tools/workflow_rate_limiter_constants.py`

### Test Files
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_executor.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_registry.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_tool_cache.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_workflow_rate_limiter.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_parameter_sanitization.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_tool_edge_cases.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_concurrent_limit_25.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_tool_config_loading.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_tools/test_search_helpers.py`
