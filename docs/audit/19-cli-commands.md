> **Note:** The CLI was removed in v1.0. Only `temper-ai serve` remains. All commands below are now HTTP API endpoints. See the API reference for current usage.

# Audit 19: CLI Feature Commands

**Scope:** All `*_commands.py` files and supporting modules in `temper_ai/interfaces/cli/`
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6
**Rating:** 88/100 (A-)

---

## Files Reviewed

| File | Lines | Purpose |
|------|-------|---------|
| `agent_commands.py` | 186 | Persistent agent management (M9) |
| `autonomy_commands.py` | 272 | Progressive autonomy: trust, budgets, e-stop |
| `chat_commands.py` | 146 | Interactive agent chat (R0.4) |
| `checkpoint_commands.py` | 281 | Checkpoint list/resume (R0.6) |
| `create_commands.py` | 122 | Project scaffolding (R2) |
| `event_commands.py` | 180 | Event bus management (M9) |
| `event_output.py` | 125 | Event output routing (stderr/stdout/file) |
| `experiment_commands.py` | 186 | A/B experimentation (M8.4) |
| `goal_commands.py` | 218 | Strategic goal proposals (M7.2) |
| `learning_commands.py` | 185 | Continuous learning (M5.3) |
| `lifecycle_commands.py` | 332 | Self-modifying lifecycle (M7.1) |
| `mcp_commands.py` | 159 | MCP server/tools (R1) |
| `memory_commands.py` | 220 | Memory management (M8.3) |
| `optimize_commands.py` | 335 | DSPy prompt optimization (R7) |
| `optimize_constants.py` | 40 | Constants for optimize commands |
| `plugin_commands.py` | 141 | Plugin system (R6) |
| `plugin_constants.py` | 19 | Constants for plugin commands |
| `portfolio_commands.py` | 421 | Portfolio management (M7.3) |
| `prompt_test_commands.py` | 161 | Prompt testing harness (R8) |
| `rollback.py` | 343 | Rollback operations |
| `server_client.py` | 133 | HTTP client for server API |
| `server_delegation.py` | 187 | Server delegation for `temper-ai run` |
| `template_commands.py` | 204 | Multi-product templates |
| `visualize_commands.py` | 135 | DAG visualization (R3) |

**Total:** 24 files, ~4,530 lines

---

## 1. Code Quality

### 1.1 Function Length (>50 lines)

| File:Line | Function | Lines | Severity |
|-----------|----------|-------|----------|
| `optimize_commands.py:107` | `compile_cmd()` | 59 | Medium |
| `checkpoint_commands.py:224` | `resume_checkpoint()` | 57 | Low |
| `portfolio_commands.py:122` | `show_portfolio()` | 53 | Low |
| `server_delegation.py:50` | `delegate_to_server()` | 53 | Low |
| `lifecycle_commands.py:167` | `preview()` | 51 | Low |
| `optimize_commands.py:180` | `_run_compilation()` | 51 | Low |

**Assessment:** 6 violations, all marginal (51-59 lines). `compile_cmd` at 59 lines is the worst offender; its dry-run/compile branching could be split. The rest are within acceptable range for Click commands that handle options + display.

### 1.2 Parameter Count (>7)

| File:Line | Function | Params | Severity |
|-----------|----------|--------|----------|
| `optimize_commands.py:107` | `compile_cmd()` | 10 | High |
| `optimize_commands.py:180` | `_run_compilation()` | 10 | High |

**Assessment:** Both in optimize module. `compile_cmd` has 10 Click options which is inherent to CLI richness but `_run_compilation` taking 10 params is a design issue. Recommend wrapping params into a config dataclass.

### 1.3 Nesting Depth (>4)

| File:Line | Function | Depth | Severity |
|-----------|----------|-------|----------|
| `optimize_commands.py:68` | `_parse_key_value_pairs()` | 5 | Low |
| `server_delegation.py:105` | `_poll_with_progress()` | 4 | Low |

**Assessment:** Minimal nesting issues. The `_parse_key_value_pairs` try/except chain for int/float/str parsing causes depth 5 -- acceptable for this conversion logic.

### 1.4 Fan-Out

All command files use lazy imports (imports inside function bodies) consistently, keeping module fan-out low. This is a well-established pattern across the codebase.

### 1.5 Naming

No naming collisions detected. Constants are properly extracted to `*_constants.py` companion files. Module-level `console = Console()` is consistent across all files.

### 1.6 Magic Numbers

All magic numbers are extracted to named constants:
- `DEFAULT_HISTORY_LIMIT = 20` (autonomy, lifecycle)
- `_ID_DISPLAY_LEN = 12` / `16` (display truncation)
- `_DATETIME_DISPLAY_LEN = 19` (display formatting)
- `MAX_CHECKPOINT_LIST` (checkpoint listing cap)
- `POLL_INTERVAL = 2` (server_delegation, with comment)
- `MAX_POLL_SECONDS = 3600` (server_delegation)

One inline magic survives with proper annotation:
- `event_commands.py:178`: `payload_str[:200]` -- has `# noqa: scanner: skip-magic`

---

## 2. Security

### 2.1 File Path Handling

**Good patterns observed:**
- `click.Path(exists=True)` used for file arguments requiring existence (`agent_commands.py:79`, `chat_commands.py:130`, `mcp_commands.py:105`)
- `create_commands.py:95`: Uses `Path(output_dir) / project_name` for path construction (no string concatenation)
- `server_delegation.py:77`: Resolves to absolute paths before sending to server

**Issue SEC-1: Missing encoding parameter on `open()` calls** (Severity: Low)

Several `open()` calls lack explicit `encoding="utf-8"`:

| File:Line | Context |
|-----------|---------|
| `chat_commands.py:43` | `with open(agent_config_path) as f:` |
| `checkpoint_commands.py:71` | `with open(path) as f:` |
| `lifecycle_commands.py:322` | `with open(path) as f:` |
| `lifecycle_commands.py:330` | `with open(input_file) as f:` |
| `memory_commands.py:194` | `with open(seed_file) as f:` |
| `optimize_commands.py:329` | `with open(config_path) as f:` |
| `experiment_commands.py:93` | `with open(variants_file) as f:` |

While Python 3 defaults to UTF-8 on most platforms, explicit encoding prevents issues on Windows or with non-standard locale settings. Compare with `create_commands.py:33-36` which properly uses `encoding="utf-8"`.

### 2.2 Credential Handling

**Good patterns observed:**
- `mcp_commands.py:69`: API key read from environment variable `TEMPER_MCP_API_KEY`, never from command line
- `mcp_commands.py:64-68`: Warning when binding to `0.0.0.0`
- `server_client.py:37`: API key passed in `X-API-Key` header, not URL params
- No credentials logged or printed to console

### 2.3 Input Validation

**Good patterns observed:**
- `agent_commands.py:85-89`: JSON metadata validated with explicit `JSONDecodeError` handling
- `event_commands.py:53-61`: ISO date format validated in `_parse_since()`
- `memory_commands.py:79`: Memory types validated via `click.Choice(VALID_MEMORY_TYPES)`
- `experiment_commands.py:54`: Status enum validated via `ExperimentStatus(status)`

### 2.4 YAML Loading

All YAML loading uses `yaml.safe_load()` -- no `yaml.load()` (unsafe) detected. Verified in: `chat_commands.py:44`, `lifecycle_commands.py:323,331`, `memory_commands.py:195`, `optimize_commands.py:330`, `experiment_commands.py:94`, `mcp_commands.py:114`, `prompt_test_commands.py:57`.

---

## 3. Error Handling

### 3.1 User-Facing Error Messages

**Good patterns observed:**
- Consistent `[red]Error:[/red]` prefix with Rich markup
- `SystemExit(1)` for unrecoverable errors (not `sys.exit()` except in `prompt_test_commands.py`)
- Specific exception types caught (not broad `except Exception`)

**Issue ERR-1: Broad `except Exception` in rollback.py** (Severity: Medium)

`rollback.py` uses bare `except Exception as e:` in three places:

| Line | Function |
|------|----------|
| 80 | `list()` |
| 120 | `info()` |
| 336 | `history()` |

This catches any exception including `KeyboardInterrupt` (via `BaseException` -- though `Exception` does not catch `KeyboardInterrupt`). The real concern is masking programming errors. These should catch specific exceptions matching the expected failure modes (e.g., `(ValueError, OSError, RuntimeError)`).

The `execute()` command in the same file does this correctly -- it catches specific exceptions in each helper function (`_validate_rollback_safety`, `_confirm_rollback_execution`, `_execute_rollback_operation`).

**Issue ERR-2: sys.exit() vs SystemExit inconsistency** (Severity: Low)

`prompt_test_commands.py:61,74,79` uses `sys.exit(1)` while all other command files use `raise SystemExit(1)`. The semantics are identical but `raise SystemExit(1)` is the project convention and provides a better traceback in testing.

### 3.2 Graceful Degradation

**Good patterns observed:**
- `mcp_commands.py:55-60,127-132`: ImportError handled for optional MCP dependency
- `optimize_commands.py:130-131,229-230`: ImportError handled for optional DSPy dependency
- `plugin_commands.py:123-128`: Missing plugin package handled gracefully
- `checkpoint_commands.py:201-203`: Unreadable checkpoints logged at debug level, not shown to user
- `event_output.py:99-100`: OSError silently caught (best-effort event output)

---

## 4. Modularity

### 4.1 Constants Extraction Pattern

All feature command modules properly extract string constants to companion `*_constants.py` files:

| Commands File | Constants File |
|---------------|----------------|
| `agent_commands.py` | `agent_constants.py` |
| `chat_commands.py` | `chat_constants.py` |
| `checkpoint_commands.py` | `checkpoint_constants.py` |
| `create_commands.py` | `create_constants.py` |
| `event_commands.py` | `event_constants.py` |
| `optimize_commands.py` | `optimize_constants.py` |
| `plugin_commands.py` | `plugin_constants.py` |
| `prompt_test_commands.py` | `prompt_test_constants.py` |

**Issue MOD-1: Missing constants files** (Severity: Low)

The following command modules define constants inline rather than in companion files:

| File | Inline Constants |
|------|-----------------|
| `autonomy_commands.py` | `LEVEL_NAMES`, `LEVEL_COLORS`, `DEFAULT_HISTORY_LIMIT`, `_OPT_*`, etc. |
| `lifecycle_commands.py` | `DEFAULT_LIFECYCLE_CONFIG_DIR`, `DEFAULT_HISTORY_LIMIT`, `_OPT_*`, etc. |
| `portfolio_commands.py` | `DEFAULT_PORTFOLIO_CONFIG_DIR`, `_OPT_*`, `_COL_*`, etc. |
| `goal_commands.py` | `DEFAULT_LOOKBACK_HOURS`, `_OPT_*`, `_COL_*`, etc. |
| `learning_commands.py` | `DEFAULT_LOOKBACK_HOURS`, `_OPT_*`, `_COL_*`, etc. |
| `experiment_commands.py` | `DEFAULT_EXPERIMENT_LIMIT`, `_OPT_*`, `_COL_*`, etc. |
| `memory_commands.py` | `VALID_MEMORY_TYPES`, `DEFAULT_*`, `_OPT_*`, etc. |
| `rollback.py` | Uses imported constants from `shared.constants` (good) but no companion file |

These modules were likely added in milestone features (M5-M8) after the constants extraction pattern was established in R0-R4 features. The inconsistency is cosmetic but breaks the established pattern.

### 4.2 Code Duplication

**Pattern: `_get_store()` / `_get_service()` helper**

This lazy-import-and-construct pattern is repeated across 9 files:

- `agent_commands.py:38` -- `_get_service()`
- `autonomy_commands.py:35` -- `_get_store(db_url)`
- `event_commands.py:39,46` -- `_get_event_bus()`, `_get_subscription_registry()`
- `goal_commands.py:40` -- `_get_store(db_url)`
- `learning_commands.py:34` -- `_get_store(db_url)`
- `lifecycle_commands.py:310` -- `_get_registry()`, `_get_db_url()`
- `portfolio_commands.py:39,47` -- `_get_store()`, `_get_loader()`
- `memory_commands.py:48` -- `_build_service_and_scope()`
- `experiment_commands.py:32` -- `_get_service()`

The pattern itself is correct (lazy imports for CLI startup speed), but the `_get_store(db_url)` + `_get_db_url()` pattern could be unified into a shared helper. This is a minor DRY improvement.

**Pattern: Duplicated `_OPT_DB` / `_HELP_DB` across files**

The strings `"--db"` and `"Database URL override"` are defined identically in:
- `autonomy_commands.py:23-24`
- `lifecycle_commands.py:29-30`
- `portfolio_commands.py:33-34`
- `goal_commands.py:33-34`
- `learning_commands.py:27-28`
- `experiment_commands.py:28-29`

These should be in `constants.py` (which already has `CLI_OPTION_DB = "--db"` but it is only used by `main.py`).

### 4.3 Consistent Patterns

**Strengths:**
- All command groups use `@click.group("name")` with consistent naming
- All use `rich.console.Console` for output, `rich.table.Table` for tabular data
- All use `raise SystemExit(1)` for fatal errors (except `prompt_test_commands.py`)
- All use lazy imports inside function bodies for heavy dependencies
- Type annotations on all function signatures

---

## 5. Feature Completeness

### 5.1 TODOs / FIXMEs / HACKs

**None found** across all files in scope. No stub commands detected.

### 5.2 Incomplete Functionality

**Issue FEAT-1: `checkpoint resume` does not actually resume** (Severity: Medium)

`checkpoint_commands.py:273-280`: The resume command loads checkpoint data and prints instructions but does not actually execute the workflow resume:

```python
console.print(
    f"[green]Checkpoint loaded.[/green] Run "
    f"'temper-ai run {workflow_path}' with resumed state."
)
```

The user must manually run the workflow with the checkpoint state. This is documented behavior but the command name "resume" implies automatic execution.

**Issue FEAT-2: `portfolio run` only records start, does not execute** (Severity: Medium)

`portfolio_commands.py:213-217`: The run command records a start event but does not invoke any workflow:

```python
workflow_id = str(uuid.uuid4())
scheduler.record_start(selected, workflow_id, portfolio_id=name)
console.print(f"[green]Started run:[/green] {workflow_id[:_ID_DISPLAY_LEN]} ({selected})")
```

This is a placeholder that records resource allocation but does not trigger actual execution.

### 5.3 Missing Error Handling

**Issue FEAT-3: `autonomy_commands.py` escalate/deescalate -- no error handling** (Severity: Low)

The `escalate()` and `deescalate()` commands at lines 97 and 122 do not catch exceptions from `AutonomyManager.escalate()` / `de_escalate()`. If the DB is down or the agent doesn't exist, the user sees an unformatted traceback.

---

## 6. Test Quality

### 6.1 Test Coverage by Command Group

| Command Module | Test File | Tests | Coverage |
|----------------|-----------|-------|----------|
| `chat_commands.py` | `test_chat_commands.py` | 15 | Good |
| `checkpoint_commands.py` | `test_checkpoint_commands.py` | 17 | Good |
| `create_commands.py` | `test_create_commands.py` | 10 | Good |
| `visualize_commands.py` | `test_visualize_commands.py` | 7 | Good |
| `rollback.py` | `test_rollback.py` | 29 | Excellent |
| `agent_commands.py` | -- | 0 | **None** |
| `autonomy_commands.py` | -- | 0 | **None** |
| `event_commands.py` | -- | 0 | **None** |
| `event_output.py` | -- | 0 | **None** |
| `experiment_commands.py` | -- | 0 | **None** |
| `goal_commands.py` | -- | 0 | **None** |
| `learning_commands.py` | -- | 0 | **None** |
| `lifecycle_commands.py` | -- | 0 | **None** |
| `mcp_commands.py` | -- | 0 | **None** |
| `memory_commands.py` | -- | 0 | **None** |
| `optimize_commands.py` | -- | 0 | **None** |
| `plugin_commands.py` | -- | 0 | **None** |
| `portfolio_commands.py` | -- | 0 | **None** |
| `prompt_test_commands.py` | -- | 0 | **None** |
| `template_commands.py` | -- | 0 | **None** |
| `server_client.py` | -- | 0 | **None** |
| `server_delegation.py` | `test_server_delegation.py` | Present | Partial |

### 6.2 Coverage Gaps

**Issue TEST-1: 16 command modules have zero dedicated tests** (Severity: High)

Only 6 of 22 command modules have dedicated test files. The untested modules were added in milestones M5-M10 and R1-R7 without corresponding CLI test files. Some may have indirect coverage through integration tests (e.g., `test_main.py` and `test_main_extended.py` test the `main` group which registers these subcommands), but the feature-specific logic (table rendering, error handling branches, option parsing) is not tested.

**Highest priority missing tests:**
1. `autonomy_commands.py` -- Safety-critical (emergency stop, escalation)
2. `memory_commands.py` -- Data operations (clear is destructive)
3. `optimize_commands.py` -- Complex option parsing, dry-run logic
4. `agent_commands.py` -- Persistent agent CRUD
5. `event_commands.py` -- Event bus interactions

### 6.3 Test Quality of Existing Tests

The existing test files follow good practices:
- Use `CliRunner` for Click command testing
- Mock external dependencies with `@patch`
- Test both success and error paths
- Test edge cases (empty results, missing files, invalid input)
- `test_rollback.py` is exemplary: 29 tests covering every error path in the execute flow

---

## 7. Architectural Analysis

### 7.1 Strengths

1. **Lazy imports everywhere.** Every command file defers heavy imports (`temper_ai.*`) to inside function bodies, keeping `temper-ai --help` fast. This is a critical UX win and is consistently applied.

2. **Constants extraction pattern.** Help text, column names, error messages are extracted to `*_constants.py` files for the R0-R4 era commands. This enables localization and keeps command logic clean.

3. **Consistent Rich output.** All modules use `Console()` + `Table()` from Rich. No raw `print()` calls detected in command files (only `click.echo` in `rollback.py` which predates the Rich convention).

4. **Click best practices.** `click.Path(exists=True)` for file validation, `click.Choice()` for enums, `envvar=` for environment variable fallbacks, `show_default=True` for discoverability.

5. **Separation of concerns.** Command files are thin CLI layers that delegate to service classes. No business logic in command files.

### 7.2 Gaps

**Issue ARCH-1: Inconsistent error exit pattern in rollback.py** (Severity: Low)

`rollback.py` uses `click.echo()` and `click.Abort()` for error handling, while every other command file uses `console.print()` and `raise SystemExit(1)`. This file also uses emoji characters in output (`"Warning:"`, etc.) while all other files use Rich markup like `[yellow]Warning:[/yellow]`. This appears to be an older module that predates the standardized CLI patterns.

**Issue ARCH-2: `_display_all_budgets()` directly queries DB** (Severity: Medium)

`autonomy_commands.py:206-236`: The `_display_all_budgets()` function directly imports `sqlmodel.Session` and `select`, then queries the database with raw SQLModel. All other command files go through a service or store layer. This breaks the abstraction boundary:

```python
def _display_all_budgets(store) -> None:
    from sqlmodel import Session, select
    from temper_ai.safety.autonomy.models import BudgetRecord
    with Session(store.engine) as session:
        budgets = list(session.exec(select(BudgetRecord)).all())
```

This should be encapsulated as a method on `AutonomyStore` or `BudgetEnforcer`.

**Issue ARCH-3: `event_output.py` file handle resource leak risk** (Severity: Low)

`event_output.py:36`: Opens a file handle in `__init__` that is only closed by an explicit `close()` call. There is no `__del__`, `__enter__`/`__exit__`, or context manager protocol. If `close()` is not called (e.g., on an unhandled exception), the file handle leaks. Adding `__del__` or implementing the context manager protocol would be defensive.

---

## 8. Summary of Issues

### Critical (P0) -- None

### High (P1)

| ID | Issue | File | Effort |
|----|-------|------|--------|
| TEST-1 | 16 command modules have zero dedicated tests | Multiple | Large |

### Medium (P2)

| ID | Issue | File | Effort |
|----|-------|------|--------|
| ERR-1 | Broad `except Exception` in rollback.py (3 sites) | `rollback.py:80,120,336` | Small |
| FEAT-1 | `checkpoint resume` does not actually resume execution | `checkpoint_commands.py:273` | Medium |
| FEAT-2 | `portfolio run` records start but does not execute workflow | `portfolio_commands.py:213` | Medium |
| ARCH-2 | `_display_all_budgets()` bypasses store abstraction | `autonomy_commands.py:206` | Small |

### Low (P3)

| ID | Issue | File | Effort |
|----|-------|------|--------|
| SEC-1 | Missing `encoding="utf-8"` on 7 `open()` calls | Multiple | Small |
| ERR-2 | `sys.exit()` vs `raise SystemExit()` inconsistency | `prompt_test_commands.py:61,74,79` | Trivial |
| MOD-1 | 8 command modules missing companion `*_constants.py` | Multiple | Small |
| FEAT-3 | Missing error handling in autonomy escalate/deescalate | `autonomy_commands.py:97,122` | Small |
| ARCH-1 | rollback.py uses click.echo/Abort instead of Rich/SystemExit | `rollback.py` | Medium |
| ARCH-3 | `EventOutputHandler` file handle has no context manager | `event_output.py:36` | Small |

---

## 9. Recommendations

### Immediate (Sprint)

1. **Add `encoding="utf-8"` to all `open()` calls** in command files (SEC-1). 7 sites, trivial fix.
2. **Narrow `except Exception` in `rollback.py`** to specific types (ERR-1). 3 sites.
3. **Move `_display_all_budgets` DB query into `AutonomyStore`** (ARCH-2).

### Next Sprint

4. **Add test files for the 5 highest-priority untested modules**: `autonomy_commands`, `memory_commands`, `optimize_commands`, `agent_commands`, `event_commands` (TEST-1 partial).
5. **Normalize `rollback.py` to use Rich output and `raise SystemExit(1)`** (ARCH-1).
6. **Fix `prompt_test_commands.py` to use `raise SystemExit(1)`** (ERR-2).

### Backlog

7. **Extract shared `_OPT_DB`/`_HELP_DB` to `constants.py`** and create companion constants files for M5-M8 command modules (MOD-1).
8. **Add `__enter__`/`__exit__` to `EventOutputHandler`** (ARCH-3).
9. **Consider making `checkpoint resume` actually resume** by integrating with the runtime (FEAT-1).
10. **Implement actual workflow execution in `portfolio run`** (FEAT-2).
11. **Wrap `_run_compilation` params into a config dataclass** to reduce parameter count below 7.

---

## 10. Score Breakdown

| Dimension | Weight | Score | Notes |
|-----------|--------|-------|-------|
| Code Quality | 25% | 90/100 | 6 marginal function length violations, 2 high param count |
| Security | 20% | 95/100 | Safe YAML, proper credential handling, minor encoding gaps |
| Error Handling | 15% | 82/100 | 3 broad Exception catches, 1 inconsistent exit pattern |
| Modularity | 15% | 88/100 | Good lazy imports and delegation, some DRY violations |
| Feature Completeness | 10% | 85/100 | No TODOs, but 2 stub commands and missing error handling |
| Test Quality | 10% | 65/100 | 16 of 22 modules untested; existing tests are excellent |
| Architecture | 5% | 90/100 | Consistent patterns with few exceptions |

**Weighted Total: 88/100 (A-)**

The CLI command layer is clean, well-structured, and follows consistent patterns. The primary concern is the test coverage gap for the M5-M10 era command modules. The code quality and security posture are strong.
