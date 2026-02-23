> **Note:** The CLI was removed in v1.0. Only `temper-ai serve` remains. All commands below are now HTTP API endpoints. See the API reference for current usage.

# Audit 18: CLI Core Module

**Scope:** `temper_ai/interfaces/cli/` core files
**Files reviewed:** `main.py`, `detail_report.py`, `stream_display.py`, `server_delegation.py`, `server_client.py`, `rollback.py`, `constants.py`, `stream_events.py`
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The CLI core module is well-structured with strong error handling, good Rich-based UX, and clean separation between local execution and server delegation. The main risks are: (1) an auth header inconsistency between `server_client.py` and `config` commands in `main.py`, (2) `_run_local_workflow` exceeding 50-line function limit at ~185 lines, and (3) missing dedicated test coverage for `server_client.py`. Overall quality is high.

**Score: 82/100 (B+)**

| Dimension | Score | Weight | Contribution |
|-----------|-------|--------|-------------|
| Code Quality | 75 | 25% | 18.8 |
| Security | 80 | 20% | 16.0 |
| Error Handling | 92 | 15% | 13.8 |
| Modularity | 85 | 15% | 12.8 |
| Feature Completeness | 90 | 10% | 9.0 |
| Test Quality | 72 | 10% | 7.2 |
| Architectural Alignment | 85 | 5% | 4.3 |

---

## 1. Code Quality

### 1.1 Function Length Violations (HIGH)

**`_run_local_workflow`** (`main.py:848-1033`) is approximately 185 lines. This is the single largest function in the codebase and 3.7x the 50-line limit. It contains nested closure definitions (`_on_config_loaded`, `_on_state_built`, `_on_after_execute`, `_on_error`) that capture mutable state via `nonlocal`, making it hard to test individual hooks in isolation.

```
main.py:848   def _run_local_workflow(  # ~185 lines
main.py:916     def _on_config_loaded(...)   # nested closure
main.py:939     def _on_state_built(...)     # nested closure, ~38 lines
main.py:979     def _on_after_execute(...)   # nested closure
main.py:994     def _on_error(...)           # nested closure
```

**Recommendation:** Extract hooks into a `_CLIRunHooks` class or top-level functions that accept a shared state dict. This would make each hook independently testable and bring every function under 50 lines.

### 1.2 Parameter Count Violations (MEDIUM)

**`_run_local_workflow`** (`main.py:848`) takes 15 parameters, nearly double the 7-param limit. The `run()` Click command (`main.py:1113`) also takes 15 params but gets a pass as a Click handler (all params are CLI args).

```python
# main.py:848-864
def _run_local_workflow(
    workflow, input_file, verbose, output, db, config_root,
    show_details, dashboard, workspace, events_to, event_format,
    run_id, autonomous, enable_plan, experiment_id,
) -> None:
```

**Recommendation:** Group related options into a `@dataclass RunOptions` (e.g., `workflow`, `input_file`, `output`, `verbose`, `show_details`) and pass that instead. The empty data class section at `main.py:67-72` suggests this was planned but never implemented.

### 1.3 Naming and Constants

- `main.py:59`: `DEFAULT_DASHBOARD_PORT = 8420` -- good, extracted as a constant.
- `main.py:60`: `DEFAULT_HOST = "127.0.0.1"` -- duplicates intent with `DEFAULT_SERVER_HOST = "0.0.0.0"` from `constants.py:41`. These serve different purposes (secure default for `serve --host` vs. dashboard bind address) but the naming is confusing.
- `server_delegation.py:24,27`: `POLL_INTERVAL = 2`, `MAX_POLL_SECONDS = 3600` -- properly extracted with scanner skip comments.
- `detail_report.py:27-30`: Table column width constants properly extracted.

### 1.4 Fan-Out

`main.py` has high import fan-out at the module level due to the command registration block (lines 2169-2251). However, these are all within `temper_ai.interfaces.cli` so they are same-package imports and do not violate cross-domain fan-out rules. Lazy imports inside functions are used correctly throughout for cross-domain dependencies.

### 1.5 Dead Code

- `main.py:67-72`: Empty section with comment "Data Classes" and blank lines. This is dead scaffolding -- either populate or remove.
- `main.py:550-554`: `_display_gantt_chart` manipulates `sys.path` to import from `examples/` -- this is a code smell. Production code should not depend on the `examples/` directory.

---

## 2. Security

### 2.1 Auth Header Inconsistency (HIGH)

**`server_client.py:37`** sends the API key as `X-API-Key`:
```python
headers["X-API-Key"] = self.api_key
```

**`main.py:1667,1694,1724,1778`** (config import/export/list/seed commands) send it as `Authorization: Bearer`:
```python
headers={"Authorization": f"Bearer {api_key}"}
```

These two auth mechanisms are fundamentally different. The `config` commands bypass `MAFServerClient` entirely and use raw `httpx` calls with a different auth header scheme. If the server expects one format, the other will fail silently or with a confusing 401.

**Recommendation:** All server communication should go through `MAFServerClient`. Add `import_config()`, `export_config()`, `list_configs()` methods to `MAFServerClient` and use `X-API-Key` consistently.

### 2.2 Dashboard Binds to 0.0.0.0 by Default (MEDIUM)

`_start_dashboard_server` at `main.py:169` uses `DEFAULT_SERVER_HOST` (`0.0.0.0`) for the dashboard spawned by `temper-ai run --dashboard`. The `serve` command correctly defaults `--host` to `DEFAULT_HOST` (`127.0.0.1`), but the embedded dashboard has no such protection -- it is always exposed on all interfaces.

```python
# main.py:169 -- always binds to 0.0.0.0
config = uvicorn.Config(app, host=DEFAULT_SERVER_HOST, port=port, log_level="warning")
```

The warning at `main.py:1234-1235` only fires for the `serve` command, not for `--dashboard`.

**Recommendation:** Change the dashboard server bind to `DEFAULT_HOST` (`127.0.0.1`) since it is meant for local development use only.

### 2.3 WebSocket URL Construction (LOW)

`main.py:2140-2141` constructs WebSocket URLs via string replacement:
```python
ws_url = client.base_url.replace("http://", "ws://").replace("https://", "wss://")
ws_url = f"{ws_url}/ws/{workflow_id}"
```

The `workflow_id` is not validated or sanitized before URL construction. While unlikely to be exploitable (it comes from the server response), it would be safer to URL-encode the path component.

### 2.4 Input File Loading

`trigger` command at `main.py:1928-1929` opens the input file with `yaml.safe_load()` -- correct. The `run` command delegates to `WorkflowRuntime.load_input_file()` -- also correct. No YAML deserialization vulnerabilities found.

---

## 3. Error Handling

### 3.1 Strengths

Error handling is the strongest dimension of this module:

- **Graceful degradation pattern:** Optional features (dashboard, OTEL, gantt chart, detailed report, evaluation dispatcher) all use try/except ImportError with fallback to None. See `main.py:175-180`, `main.py:196-202`, `main.py:539-544`, `main.py:562-565`.
- **User-facing messages:** All errors use Rich markup for colored `[red]Error:[/red]` prefixes with specific context. Example: `main.py:884`, `main.py:998`, `main.py:1002`.
- **Signal handling:** `KeyboardInterrupt` exits with POSIX-standard code 130 (`main.py:1024-1025`). The dashboard keepalive at `main.py:726-736` handles both `signal.pause()` (Unix) and `time.sleep()` fallback (Windows).
- **Rollback command:** Exhaustive error type handling in `rollback.py` -- `ValueError`, `OSError`, `PermissionError`, `RuntimeError` are all caught with distinct user-facing messages (lines 160-251).

### 3.2 Broad Exception Catches (MEDIUM)

Several places catch `Exception` broadly:

| Location | Justification | Verdict |
|----------|--------------|---------|
| `main.py:389` (`_try_create_llm_from_agent`) | `# noqa: BLE001` -- optional LLM creation | Acceptable |
| `main.py:402` (`_create_experiment_service`) | Optional feature | Acceptable |
| `main.py:507` (`_finalize_evaluation_dispatcher`) | Cleanup must not crash | Acceptable |
| `main.py:886` (input validation in `_run_local_workflow`) | Generic catch for `rt_tmp.load_input_file` | **Should narrow** to `(yaml.YAMLError, ValueError, OSError)` |
| `main.py:1933` (`trigger` command) | Catches all exceptions from `client.trigger_run` | **Should narrow** to `httpx.HTTPError` |
| `main.py:1954` (`_poll_until_complete`) | Catches all poll errors | **Should narrow** to `httpx.HTTPError` |
| `rollback.py:80,120,336` | Three broad catches in list/info/history | **Should narrow** to specific exceptions |

### 3.3 f-string in Logger Calls (LOW)

`main.py:542-544` and `main.py:563-565` use f-strings in logger calls instead of `%s` formatting:
```python
logger.debug(f"Could not display detailed report: {e}")
```
Should be:
```python
logger.debug("Could not display detailed report: %s", e)
```

---

## 4. Modularity

### 4.1 Command Registration Pattern

The command registration at `main.py:2169-2251` uses a consistent pattern: import at module level with `# noqa: E402`, then `main.add_command()`. Optional commands use try/except ImportError (MCP at 2213, optimize at 2227, plugin at 2233). This is clean and extensible.

### 4.2 Re-Export Shims

`stream_events.py` is a proper re-export shim pointing to the canonical location `temper_ai.shared.core.stream_events`. This follows the established project pattern.

### 4.3 Separation of Concerns

Good separation between:
- **`main.py`:** Command definitions, CLI-specific logic, hook wiring
- **`detail_report.py`:** Rich rendering of execution results (pure display logic)
- **`stream_display.py`:** Thread-safe streaming display (independent of CLI)
- **`server_delegation.py`:** Server communication for delegated runs
- **`server_client.py`:** HTTP client abstraction
- **`rollback.py`:** Rollback-specific CLI commands
- **`constants.py`:** Shared constants

### 4.4 Config Commands Not Using Server Client (MEDIUM)

The `config import/export/list/seed` commands (`main.py:1654-1791`) build raw `httpx` requests instead of using `MAFServerClient`. This duplicates URL construction, header management, and error handling patterns.

---

## 5. Feature Completeness

### 5.1 No TODO/FIXME/HACK Markers

Zero TODO/FIXME/HACK markers found across all six scoped files. This is excellent.

### 5.2 Gantt Chart Depends on Examples Directory (LOW)

`_display_gantt_chart` at `main.py:548-565` imports from `examples.export_waterfall`. This is a production feature depending on the examples directory, which may not be installed in production deployments.

### 5.3 Config Seed Lacks Progress Indication (LOW)

`config_seed` at `main.py:1750-1791` iterates all YAML files synchronously with no progress bar. For large config directories this could appear to hang.

### 5.4 Complete Feature Set

All advertised CLI commands are registered and functional:
- `run`, `serve`, `validate`, `list`, `trigger`, `status`, `logs`, `rollback`, `config`
- All M5-M10 subcommands properly mounted

---

## 6. Test Quality

### 6.1 Coverage Summary

| Module | Test File | Tests | Coverage Assessment |
|--------|-----------|-------|-------------------|
| `main.py` | `test_main.py`, `test_main_extended.py`, `test_run_helpers.py`, `test_dashboard_flag.py` | ~65 | Good -- covers run, validate, list, helpers |
| `detail_report.py` | `test_detail_report.py` | ~25 | Good -- edge cases, legacy keys, filtering |
| `stream_display.py` | `test_stream_display.py` | ~8 | Minimal -- only stage context propagation |
| `server_delegation.py` | `test_server_delegation.py` | ~12 | Good -- success, failure, timeout, save |
| `server_client.py` | **None** | 0 | **Missing** |
| `rollback.py` | `test_rollback.py` | ~30 | Excellent -- all commands, all error paths |

### 6.2 Missing Test Coverage (HIGH)

**`server_client.py`** has zero dedicated tests. While `test_server_delegation.py` tests `is_server_running()` via mocking, the following are untested:
- `health_check()` -- success and failure paths
- `trigger_run()` -- parameter serialization, HTTP error handling
- `get_status()` -- response parsing
- `list_runs()` -- parameter passing, pagination
- `cancel_run()` -- success and failure paths
- `_headers()` -- API key inclusion/exclusion
- `_client()` -- timeout configuration

### 6.3 Weak `stream_display.py` Coverage (MEDIUM)

Tests only cover stage name propagation and panel title rendering. Missing:
- `on_chunk()` -- backward compatibility path
- `make_callback()` -- event routing
- `_apply_event()` -- all event types (LLM_TOKEN, LLM_DONE, TOOL_START, TOOL_RESULT, STATUS, PROGRESS)
- `_stop()` -- cleanup behavior
- `_build_display()` -- multi-panel rendering
- Thread safety (concurrent `_on_event` calls)
- `_truncated_tail()` -- truncation logic

### 6.4 `_run_local_workflow` Hook Coverage (MEDIUM)

The nested hooks (`_on_config_loaded`, `_on_state_built`, `_on_after_execute`, `_on_error`) are tested only via end-to-end `runner.invoke()` calls. Because they are closures, they cannot be unit-tested in isolation. This is a direct consequence of the function length issue in 1.1.

### 6.5 Config Commands Untested (MEDIUM)

The `config import/export/list/seed` commands (`main.py:1643-1791`) have no dedicated tests. These are M10 features that make HTTP calls to the server.

---

## 7. Architectural Alignment

### 7.1 Configuration as Product

- **Config validation** (`validate` command) is comprehensive: schema validation via `WorkflowRuntime.load_config()`, stage reference checking, agent reference checking, tool reference checking, and DAG-aware source reference validation with transitive predecessor computation.
- **Config check** (`config check` command) validates entire config directories.
- **JSON output mode** (`--format json`) for CI/CD integration is properly supported.
- **Config import/export/seed** commands support the DB-backed config management from M10.

### 7.2 Observability

- **Event routing** (`--events-to`, `--event-format`) supports stderr, stdout, and file outputs with text, json, and jsonl formats.
- **OTEL integration** via `_create_otel_backend_factory()` is properly lazy-loaded.
- **Dashboard integration** is available as both embedded (`--dashboard`) and standalone (`serve --dev`).
- **Gantt chart** post-execution visualization is automatically displayed.

### 7.3 Missing: Structured Logging for CLI Operations

CLI operations themselves (config validation, server delegation, rollback execution) do not emit observability events. Only workflow execution is instrumented. This creates a gap for operational monitoring of administrative CLI usage.

---

## 8. Findings Summary

### Critical (0)

None.

### High (4)

| # | Finding | Location | Recommendation |
|---|---------|----------|---------------|
| H1 | `_run_local_workflow` is 185 lines (limit: 50) | `main.py:848-1033` | Extract hooks into a class or top-level functions |
| H2 | Auth header inconsistency: `X-API-Key` vs `Authorization: Bearer` | `server_client.py:37` vs `main.py:1667` | Route all server calls through `MAFServerClient` |
| H3 | `server_client.py` has zero test coverage | N/A | Write dedicated unit tests for all 6 methods |
| H4 | `_run_local_workflow` takes 15 parameters (limit: 7) | `main.py:848-864` | Group into `@dataclass RunOptions` |

### Medium (7)

| # | Finding | Location | Recommendation |
|---|---------|----------|---------------|
| M1 | Dashboard binds to `0.0.0.0` when spawned by `--dashboard` flag | `main.py:169` | Use `DEFAULT_HOST` (`127.0.0.1`) instead |
| M2 | Config commands duplicate HTTP logic instead of using `MAFServerClient` | `main.py:1654-1791` | Add methods to `MAFServerClient` |
| M3 | Broad `except Exception` in `trigger` and `_poll_until_complete` | `main.py:1933,1954` | Narrow to `httpx.HTTPError` |
| M4 | Broad `except Exception` in rollback list/info/history | `rollback.py:80,120,336` | Narrow to specific exceptions |
| M5 | `stream_display.py` test coverage is minimal (~8 tests) | `test_stream_display.py` | Add tests for all event types and thread safety |
| M6 | Config commands (import/export/list/seed) have no tests | N/A | Add Click runner tests |
| M7 | `_display_gantt_chart` imports from `examples/` directory | `main.py:548-565` | Move `export_waterfall_trace` to `temper_ai.observability` |

### Low (5)

| # | Finding | Location | Recommendation |
|---|---------|----------|---------------|
| L1 | f-string in logger.debug calls | `main.py:542,544,563,565` | Use `%s` formatting |
| L2 | Empty "Data Classes" section | `main.py:67-72` | Remove or implement `RunOptions` dataclass |
| L3 | WebSocket URL constructed without path encoding | `main.py:2140-2141` | URL-encode `workflow_id` |
| L4 | `DEFAULT_HOST` vs `DEFAULT_SERVER_HOST` naming confusion | `main.py:60` vs `constants.py:41` | Rename to `LOCALHOST_BIND` and `ALL_INTERFACES_BIND` |
| L5 | `config_seed` lacks progress indication | `main.py:1750-1791` | Add Rich progress bar |

---

## 9. Positive Observations

1. **Excellent Rich UX:** Consistent use of `[red]Error:[/red]`, `[green]...[/green]`, `[cyan]...[/cyan]` color coding. Tables for structured output. Live streaming display with multi-source panels.

2. **Strong graceful degradation:** Every optional feature (dashboard, OTEL, gantt, evaluation, MCP, plugins, DSPy) is guarded by try/except ImportError and degrades gracefully with user-visible warnings.

3. **Proper signal handling:** SIGINT produces POSIX-standard exit code 130. Windows fallback for `signal.pause()`. Clean shutdown of dashboard and evaluation dispatcher in finally blocks.

4. **Good constant extraction:** Magic numbers are consistently extracted to named constants with scanner skip comments. Column headers, exit codes, timeouts, and ports all have proper constants.

5. **Security-conscious defaults:** `DEFAULT_HOST = "127.0.0.1"` for the serve command. YAML loaded with `safe_load()` everywhere. Path resolution with `Path.resolve()` for server delegation.

6. **Comprehensive rollback safety:** The rollback command has multi-layer safety: validation checks, safety warnings, force override, confirmation prompt, and dry-run mode. Error handling covers ValueError, OSError, PermissionError, and RuntimeError separately with distinct messages.

7. **Zero TODO/FIXME debt:** No outstanding markers in any scoped file, indicating all features are complete implementations.

8. **Text sanitization in detail_report.py:** LLM-generated content is always wrapped in `Text()` (plain) while framework labels use `Text.from_markup()`. This prevents Rich markup injection from LLM outputs.
