# Scope 03: Workflow Compilation, Checkpoint & DAG -- Audit Report

## Overview
- **Files reviewed:** 21 source files + 19 test files
- **Source LOC:** 5,250
- **Test files:** 19
- **Test functions:** 328
- **Test LOC:** 4,508

## Findings

### Critical

None.

### High

**H-01. Literal string bug in checkpoint_manager.py log message (line 304)**
`checkpoint_manager.py:304` reads:
```python
logger.info(f"Checkpoint deleted: workflow={workflow_id}LOG_SEPARATOR_CHECKPOINT{checkpoint_id}")
```
The constant `LOG_SEPARATOR_CHECKPOINT` (value `", checkpoint="`) is embedded as a literal string `LOG_SEPARATOR_CHECKPOINT` instead of being interpolated. Every other use of this constant in the same file (lines 172, 225, 356) correctly uses `{LOG_SEPARATOR_CHECKPOINT}` inside f-strings. This produces garbled log output like `workflow=wf-123LOG_SEPARATOR_CHECKPOINTcp-001` instead of `workflow=wf-123, checkpoint=cp-001`.

**H-02. `_kahn_bfs` in dag_builder.py has O(V*E) instead of O(V+E) complexity**
`dag_builder.py:131-149` -- `_kahn_bfs()` iterates over all `stage_names` for every dequeued node to find children via `if node in predecessors[child]`. This is O(V^2) in the inner loop. For small DAGs this is harmless, but if the framework ever handles large DAGs (e.g., 100+ stages from template expansion), it degrades. The parallel `_topological_sort()` function (line 170) has the same pattern. A proper adjacency-list traversal would be O(V+E). Severity is High rather than Medium because DAG construction happens on every workflow execution.

**H-03. `_insert_fan_in_barriers` function exceeds 50-line limit (67 lines)**
`stage_compiler.py:628-692` -- the `_insert_fan_in_barriers` function is 67 lines (limit: 50). It mixes barrier insertion logic, loop stage filtering, and depth equalization in a single function. Should be decomposed into smaller helpers.

**H-04. `create_stage_node` closure exceeds 50-line limit (79 lines)**
`node_builder.py:59-136` -- the `create_stage_node` method and its inner `stage_node` closure together span 79 lines. The inner closure handles config loading, mode detection, executor delegation, failure checking, and checkpoint resume skip -- five distinct responsibilities in one function. Split at minimum the checkpoint-resume and failure-checking logic into separate methods.

### Medium

**M-01. `_build_ref_lookup` duplicated in three modules**
The function `_build_ref_lookup` appears identically in:
- `stage_compiler.py:443` (as a method)
- `dag_builder.py:210` (as a module function)
- `engines/workflow_executor.py:63` (as a module function)

All three have the same logic: build `{name: ref}` from a list of stage references. This should be extracted to a shared utility (e.g., `workflow/utils.py`).

**M-02. `StageDAG` docstring claims "Immutable" but dataclass is mutable**
`dag_builder.py:22-37` -- The `StageDAG` dataclass docstring says "Immutable result of DAG construction" but it uses `@dataclass` without `frozen=True`. All fields are mutable dicts and lists. Either add `frozen=True` (and adjust callers) or correct the docstring. The mismatch could mislead developers into assuming thread safety.

**M-03. Broad `except Exception` in checkpoint shim (checkpoint.py:201)**
`checkpoint.py:201` has `except Exception: return False` in `should_skip_stage()`. This silently swallows all exceptions including `IOError`, `json.JSONDecodeError`, and permission errors during checkpoint reads. A more targeted catch (e.g., `(FileNotFoundError, json.JSONDecodeError)`) would be safer. The same pattern at `condition_evaluator.py:66` is acceptable since it logs with `exc_info=True`.

**M-04. No checkpoint encryption -- HMAC only provides integrity, not confidentiality**
`checkpoint_backends.py` provides HMAC integrity verification, which is good. However, checkpoint files are stored in plaintext JSON. Workflow domain state may contain sensitive input data (e.g., API keys, user data passed as workflow inputs). There is no encryption layer. In a multi-tenant deployment (M10), one tenant's checkpoints could be read by another if filesystem permissions are misconfigured.

**M-05. Execution service has no input size limits**
`execution_service.py` accepts `input_data: dict[str, Any]` without any validation of size or depth. A malicious or buggy caller could submit deeply nested or very large input dictionaries, causing memory pressure or slow JSON serialization in the result sanitization path.

**M-06. `save_checkpoint` in checkpoint_manager.py exceeds 50-line limit (75 lines)**
`checkpoint_manager.py:119-192` -- the `save_checkpoint` method is 75 lines including docstring. The method handles strategy checking, metadata enrichment, backend delegation, callback invocation, and cleanup in one method. The callback and cleanup sections could be extracted.

**M-07. `_check_stage_failure` in node_builder.py exceeds 50-line limit (64 lines)**
`node_builder.py:138-200` -- this method mixes error policy extraction from two config formats (dict and Pydantic) with failure evaluation logic. The config extraction should be a separate method.

**M-08. `find_embedded_stage` always returns None**
`node_builder.py:260-286` -- the method contains a comment "For now, return None (embedded configs not fully supported)" and never returns a real config. This is dead code masquerading as a feature. Either implement it or remove the method and simplify `_load_stage_config` to raise directly.

### Low

**L-01. Template generator does not validate `project_name` for special characters**
`templates/generator.py:28-64` -- `_replace_placeholder` does simple string replacement of `{{project_name}}` but does not validate that `project_name` is a valid identifier. A project name like `"../etc"` or one containing shell metacharacters could produce problematic file names or YAML values.

**L-02. `_SilentUndefined.__call__` and `__getitem__` override signatures differ from parent**
`condition_evaluator.py:131-132` -- both `__getitem__` and `__call__` have `# type: ignore[override]` comments. While functionally correct, these suppress genuine type warnings. Consider using `Any` return types on the parent signature or documenting why the override is safe.

**L-03. `execution_context.py` defines `WorkflowStateDict` as deprecated alias (line 78)**
`execution_context.py:78` has `WorkflowStateDict = WorkflowExecutionContext`. This deprecated alias should be tracked for removal. No uses found in the scope files, but may exist elsewhere.

**L-04. `list_checkpoints` in FileCheckpointBackend reads all checkpoint files**
`checkpoint_backends.py:470-496` -- `list_checkpoints()` opens and parses every `.json` file in the workflow directory. For workflows with many checkpoints (before cleanup), this is wasteful. The `get_latest_checkpoint` method already optimizes via `st_mtime`, but `list_checkpoints` does not.

**L-05. `LLMOutputExtractor._call_llm` uses rough token estimation**
`output_extractor.py:161` -- `len(prompt) // 4` is used to estimate prompt tokens. This is a very rough heuristic (comment says `scanner: skip-magic`). While acceptable for observability tracking, it may mislead cost reporting. Consider adding a comment noting the approximation.

**L-06. `_passthrough_node` naming could confuse with `PassthroughResolver`**
`stage_compiler.py:620-625` defines `_passthrough_node` for barrier pass-through, while `context_provider.py:333` defines `PassthroughResolver`. These are unrelated concepts that share the "passthrough" name.

**L-07. `compile_conditional_stages` accepts unused `_conditions` parameter**
`stage_compiler.py:490-502` -- this backward-compat method accepts a `_conditions` parameter that is explicitly unused. The method itself just delegates to `compile_stages`. Consider deprecation warnings.

## Code Quality

**Function Length Violations (>50 lines):**
| File | Function | Lines |
|---|---|---|
| `stage_compiler.py` | `_insert_fan_in_barriers` | 67 |
| `stage_compiler.py` | `compile_stages` | 55 |
| `stage_compiler.py` | `_add_dag_edges` | 50 |
| `node_builder.py` | `create_stage_node` | 79 |
| `node_builder.py` | `_check_stage_failure` | 64 |
| `checkpoint_backends.py` | `save_checkpoint` | 67 |
| `checkpoint_backends.py` | `load_checkpoint` | 60 |
| `checkpoint_manager.py` | `save_checkpoint` | 75 |
| `checkpoint_manager.py` | `load_checkpoint` | 52 |
| `execution_service.py` | `_prepare_execution` | 63 |

**Parameter Count:** All functions have 7 or fewer parameters. No violations.

**Nesting Depth:** No functions exceed depth 4. Clean.

**Fan-out:** `stage_compiler.py` imports from 7 distinct internal modules (within limit of 8). `execution_service.py` uses lazy imports to stay within limit. Clean.

**Naming:** Consistent snake_case throughout. Class names follow PascalCase. No collisions.

**Magic Numbers:** All constants are named or annotated with `scanner: skip-magic`. No violations.

**Circular Dependencies:** None detected. The stage_compiler docstring notes the module was moved from `temper_ai.stage` to `temper_ai.workflow` specifically to break a circular dep.

## Security & Error Handling

**Security Positives:**
- Checkpoint backends use HMAC-SHA256 integrity verification with constant-time comparison (`hmac.compare_digest`).
- Path traversal protection via `_sanitize_id()` and `_verify_path_containment()` with regex sanitization + `resolve().relative_to()`.
- Null byte injection blocked with explicit check.
- Atomic writes using `tempfile.mkstemp` + `os.replace()` with `os.fsync()`.
- `CHECKPOINT_HMAC_KEY` required in production (`ENVIRONMENT=production`).
- Condition evaluation uses `ImmutableSandboxedEnvironment` (Jinja2 SSTI protection).
- Template generator uses `yaml.safe_load` (not `yaml.load`).
- No `eval()`, `exec()`, `pickle`, `os.system`, or `shell=True` anywhere in scope.
- RESERVED_STATE_KEYS prevents user input from overwriting framework state.

**Error Handling:**
- `generate_workflow_plan` gracefully handles 5 specific exception types with fallback to `None`.
- `checkpoint_manager.py` provides lifecycle callbacks (`on_checkpoint_saved`, `on_checkpoint_failed`) for error observability.
- `condition_evaluator.py` logs with `exc_info=True` on evaluation failure (good for debugging).
- `execution_service.py` uses `# noqa: BLE001` for intentional broad exception catches in background threads.

**Error Handling Concerns:**
- `checkpoint.py:201` swallows all exceptions silently (see M-03).
- `checkpoint_manager.py:184` catches `Exception` and re-raises as `CheckpointSaveError` -- acceptable pattern but loses the original traceback in the log message (only `str(e)`, not the full chain).

## Dead Code

1. **`find_embedded_stage`** (`node_builder.py:260-286`): Always returns `None`. The comment says "embedded configs not fully supported". This is unused functionality.

2. **`compile_parallel_stages`** (`stage_compiler.py:482-488`): Simply delegates to `compile_stages` with no additional logic. Kept for backward compatibility but adds no value.

3. **`compile_conditional_stages`** (`stage_compiler.py:490-502`): Same as above -- delegates to `compile_stages`, accepts unused `_conditions` parameter.

4. **`_add_sequential_edges`** (`stage_compiler.py:470-480`): Legacy helper, comment says "kept for backward compat (used by tests)". Could be removed if tests are updated.

5. **`WorkflowStateDict` alias** (`execution_context.py:78`): Deprecated alias with no known users in scope.

6. **`FileCheckpointStorage` class** (`checkpoint.py:205-268`): Entire class is a backward-compatible wrapper. If no external consumers use it, this can be removed.

7. **`CheckpointManager` in `checkpoint.py`** (`checkpoint.py:57-203`): The entire `checkpoint.py` module is a backward-compatibility shim. The real implementation is in `checkpoint_manager.py` and `checkpoint_backends.py`.

## Test Quality

**Coverage Assessment:**

| Module | Test File | Test Count | Assessment |
|---|---|---|---|
| `stage_compiler.py` | (tested via integration tests) | 0 dedicated | Gap: No unit tests for `_insert_fan_in_barriers`, `_maybe_wrap_trigger_node`, `_maybe_wrap_on_complete_node` |
| `node_builder.py` | `test_node_builder.py` | 15 | Good: covers init, extraction, mode detection, delegation. Missing: `_check_stage_failure`, `wire_dag_context` |
| `checkpoint.py` | `test_checkpoint.py` | 17 | Good: covers save/load/resume/list/delete for backward-compat shim |
| `checkpoint_backends.py` | `test_checkpoint_backends.py` | 18 | Excellent: covers save/load/list/delete, HMAC, path traversal, entropy |
| `checkpoint_manager.py` | `test_checkpoint_manager.py` | 16 | Good: covers strategies, cleanup, callbacks, factory |
| `dag_builder.py` | `test_dag_builder.py` | 12 | Good: covers linear, fan-out, fan-in, diamond, errors, depths |
| `dag_visualizer.py` | `test_dag_visualizer.py` | 12 | Good: covers Mermaid, DOT, ASCII for multiple topologies |
| `condition_evaluator.py` | `test_condition_evaluator.py` | 12 | Good: covers true/false/nested/caching/syntax-error |
| `state_manager.py` | `test_state_manager.py` | 6 | Adequate: covers basic init and init-node |
| `routing_functions.py` | `test_routing_functions.py` | 11 | Good: covers conditional/loop/skip_if/default/max_loops |
| `context_provider.py` | `test_context_provider.py` + `test_predecessor_resolver.py` | 18 + ~20 | Excellent: covers source/passthrough/predecessor resolvers |
| `output_extractor.py` | `test_output_extractor.py` | 11 | Good: covers noop, LLM, parsing, factory |
| `planning.py` | `test_planning.py` | 12 | Good: covers config validation, prompt building, error handling |
| `execution_service.py` | `test_execution_service.py` | 12 | Good: covers sync/threading/sanitization/futures cleanup |
| `templates/` | `test_templates/` (5 files) | ~25 | Good: covers registry, generator, quality gates, schemas, integration |

**Test Gaps:**
1. **`stage_compiler.py` has no dedicated unit tests.** The complex DAG compilation, barrier insertion, and event trigger/on_complete wrapping logic is only tested through integration tests. This is the most critical gap.
2. **`_check_stage_failure` in `node_builder.py` is untested.** The halt/skip policy logic with both dict and Pydantic config formats has no direct tests.
3. **`wire_dag_context` in `node_builder.py` is untested.** The predecessor resolver wiring logic has no direct tests.
4. **No tests for `_maybe_wrap_trigger_node` or `_maybe_wrap_on_complete_node`.** Event trigger integration is untested at the unit level.
5. **No test for HMAC key requirement in production mode** (`ENVIRONMENT=production` + missing key should raise).

**Test Quality Positives:**
- Tests use `tempfile` and `tmp_path` consistently (no leftover files).
- Security tests for path traversal, null bytes, and checkpoint ID entropy are thorough.
- Tests use proper assertion patterns (no `assert True`, no missing assertions).
- Good use of parameterized fixtures and class-based grouping.

## Feature Completeness

**No TODO/FIXME/HACK comments found** in any file in scope. All implementations appear complete.

**Partial Implementations:**
1. `find_embedded_stage` always returns `None` -- embedded stage configs are not supported.
2. `create_checkpoint_manager` factory only supports `"file"` backend. No S3, Redis, or database backends.
3. Template system only supports 6 product types (literal enum). No plugin mechanism for custom product types.
4. `PlanningConfig` is limited to 5 providers as a Literal type. Cannot use custom providers.

## Architectural Gaps vs Vision

### Radical Modularity
**Score: 8/10**
- Checkpoint backends are properly abstracted via `CheckpointBackend` ABC -- adding new backends (S3, Redis, database) requires only implementing the interface.
- Context resolution is modular: `SourceResolver`, `PredecessorResolver`, `PassthroughResolver` are all implementations of the `ContextProvider` protocol.
- Output extraction is pluggable via the `OutputExtractor` protocol.
- DAG construction (`build_stage_dag`) is decoupled from visualization (`export_mermaid`, `export_dot`, `render_console_dag`).
- **Gap:** Only `FileCheckpointBackend` exists. For production deployments with multiple workers, a shared storage backend (database, S3) is needed.
- **Gap:** The `_build_ref_lookup` duplication (3 copies) violates DRY.

### Configuration as Product
**Score: 7/10**
- All compilation options (conditional, loop, DAG) are driven by YAML config.
- Checkpoint strategy is configurable (`EVERY_STAGE`, `PERIODIC`, `MANUAL`, `DISABLED`).
- Template system provides quality gate configuration per product type.
- Planning pass is configurable via `PlanningConfig`.
- **Gap:** No way to configure checkpoint backend type from YAML (hardcoded to file).
- **Gap:** No way to configure barrier insertion strategy or fan-in behavior.

### Observability as Foundation
**Score: 6/10**
- Checkpoint lifecycle has callback hooks (`on_checkpoint_saved`, `on_checkpoint_loaded`, `on_checkpoint_failed`).
- LLM extraction calls are tracked via `tracker.track_llm_call()`.
- Log messages use structured formatting with `LOG_PREFIX_CHECKPOINT` and `LOG_SEPARATOR_CHECKPOINT` constants.
- **Gap:** Stage compilation events are not traced. There is no observability for DAG construction, barrier insertion, conditional routing decisions, or loop iteration counts outside of debug logs.
- **Gap:** No metrics emitted for compilation time, DAG complexity, or barrier count.
- **Gap:** Condition evaluation failures are logged but not tracked as observability events.

### Progressive Autonomy
**Score: 5/10**
- Quality gates exist in the template system (`TemplateQualityGates`).
- Stage failure policies (`halt`, `skip`) provide basic autonomy control.
- **Gap:** No approval gates in the compilation pipeline. A stage marked as requiring human approval cannot pause compilation.
- **Gap:** No trust-level-based conditional execution (e.g., skip safety gates for high-trust workflows).

### Self-Improvement Loop
**Score: 3/10**
- **Gap:** Compilation metrics are not fed back to optimization. There is no tracking of which DAG topologies perform best, which checkpoint strategies have the lowest overhead, or which conditional routing patterns are most effective.
- **Gap:** Planning pass results are not stored or evaluated for effectiveness.
- **Gap:** No compilation caching -- the same workflow is recompiled on every execution.

### Merit-Based Collaboration
**Score: N/A** -- Not directly relevant to compilation/checkpoint/DAG modules. Agent collaboration is handled at the stage executor level, which is outside this scope.

### Safety Through Composition
**Score: 7/10**
- Safety policies in node_builder (`on_stage_failure: halt/skip`) prevent unsafe workflow continuation.
- Checkpoint HMAC prevents tampering with stored workflow state.
- Path traversal protection prevents checkpoint file access outside designated directories.
- `RESERVED_STATE_KEYS` prevents user input from corrupting framework state.
- Condition evaluation uses sandboxed Jinja2.
- **Gap:** No safety policy enforcement during compilation itself (e.g., ensuring that a workflow with `shell=True` tools has mandatory review stages).
- **Gap:** No maximum loop iteration enforcement at the configuration validation level -- only at runtime via `max_loops`.

## Improvement Opportunities

### Quick Wins (Low Effort, High Impact)
1. **Fix literal string bug** in `checkpoint_manager.py:304` -- change `LOG_SEPARATOR_CHECKPOINT` to `{LOG_SEPARATOR_CHECKPOINT}`.
2. **Extract `_build_ref_lookup`** to `workflow/utils.py` and import from all three locations.
3. **Correct `StageDAG` docstring** from "Immutable" to "Result" or add `frozen=True`.

### Medium Effort
4. **Add unit tests for `stage_compiler.py`** -- especially for barrier insertion, event trigger wrapping, and DAG edge compilation.
5. **Decompose long functions** in `stage_compiler.py` and `node_builder.py` to meet the 50-line limit.
6. **Improve `_kahn_bfs`** to use proper adjacency list traversal (O(V+E) instead of O(V^2)).
7. **Add observability events** for compilation (DAG construction, barrier insertion, routing decisions).
8. **Add checkpoint backend type to workflow YAML config** so users can switch between file/database/S3.

### Larger Initiatives
9. **Implement a database checkpoint backend** for multi-worker production deployments.
10. **Add compilation caching** to avoid recompiling unchanged workflows.
11. **Track planning pass effectiveness** by storing plans and correlating with execution outcomes.
12. **Add safety policy validation** at compilation time (not just runtime).

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 4 |
| Medium | 8 |
| Low | 7 |

The workflow compilation, checkpoint, and DAG modules are **well-architected with strong security fundamentals**. The checkpoint system has excellent path traversal protection, HMAC integrity verification, and atomic writes. The DAG builder correctly handles cycle detection, topological sorting, and asymmetric fan-in via barrier nodes. Context resolution is cleanly decomposed into three resolver strategies.

The main areas for improvement are:
1. **A literal string bug** in checkpoint_manager.py that produces garbled log output (H-01).
2. **Several functions exceed the 50-line limit** (H-03, H-04, M-06, M-07), particularly in stage_compiler.py and node_builder.py.
3. **Quadratic complexity** in the DAG topological sort (H-02) that should be linear.
4. **Code duplication** of `_build_ref_lookup` across three modules (M-01).
5. **Missing unit tests** for stage_compiler.py, which contains the most complex compilation logic.
6. **Observability gaps** -- compilation events and metrics are not traced.

Overall code quality is high. No security vulnerabilities, no unsafe operations, no circular dependencies. The backward-compatibility shim pattern (checkpoint.py) is well-executed with clean delegation.
