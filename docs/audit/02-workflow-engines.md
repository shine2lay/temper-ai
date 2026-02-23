# Scope 02: Workflow Engines -- Audit Report

## Overview

- **Files reviewed:** 14 source files | **Source LOC:** 3,896 | **Test files:** 10 | **Test functions:** 264

### Source Files

| File | LOC | Role |
|---|---|---|
| `engines/__init__.py` | 32 | Package exports + legacy aliases |
| `engines/dynamic_engine.py` | 502 | Dynamic (Python-native) engine + compiled workflow |
| `engines/_dynamic_edge_helpers.py` | 318 | Dynamic edge routing (fan-out, convergence) |
| `engines/dynamic_runner.py` | 125 | ThreadPool-based parallel runner |
| `engines/langgraph_compiler.py` | 450 | LangGraph StateGraph compiler |
| `engines/langgraph_engine.py` | 408 | LangGraph engine adapter |
| `engines/native_engine.py` | 24 | Re-export shim (Native -> Dynamic) |
| `engines/native_runner.py` | 15 | Re-export shim |
| `engines/workflow_executor.py` | 772 | DAG walker, conditions, loops, negotiation |
| `engine_registry.py` | 221 | Singleton registry + factory |
| `execution_engine.py` | 298 | ABCs (ExecutionEngine, CompiledWorkflow) |
| `langgraph_engine.py` | 19 | Re-export shim |
| `langgraph_state.py` | 236 | LangGraph dataclass state + reducers |
| `workflow_executor.py` | 476 | CompiledGraphRunner (LangGraph executor) |

### Test Files

| File | LOC | Tests |
|---|---|---|
| `test_dynamic_engine.py` | 308 | 27 |
| `test_native_workflow_executor.py` | 1,341 | 71 |
| `test_native_runner.py` | 178 | 13 |
| `test_execution_engine.py` | 337 | 28 |
| `test_engine_registry.py` | 525 | 23 |
| `test_native_engine.py` | 268 | 22 |
| `test_langgraph_engine.py` | 554 | 32 |
| `test_langgraph_compiler.py` | 215 | 13 |
| `test_langgraph_state.py` | 168 | 15 |
| `test_workflow_executor.py` | 409 | 20 |

---

## Findings

### Critical

None.

### High

#### H-01: Broad `except Exception` catches in parallel execution paths (3 locations)

Three locations swallow arbitrary exceptions from parallel stage/node execution, logging them but silently continuing. This hides bugs and can produce silently-corrupt workflow state.

- `engines/dynamic_runner.py:121` -- `ThreadPoolParallelRunner._run_nodes_parallel`: catches all exceptions from parallel nodes, logs with `logger.exception`, and appends to `_failed_nodes`. The caller has no way to know a node failed unless it inspects the `_failed_nodes` list.
- `engines/workflow_executor.py:292` -- `_run_parallel_stage_batch`: catches all exceptions from parallel stages, logs, and returns a synthetic `{"stage_status": "failed"}` result. No stage-level error type is distinguished.
- `workflow_executor.py:398` -- `resume_from_checkpoint` bare `except Exception:` re-raises, but the inner `except Exception as checkpoint_error:` at line 403 swallows checkpoint-save failures during error recovery.

**Impact:** A coding bug in a stage callable (e.g., `TypeError`, `AttributeError`) is silently treated as a "completed with error" stage, not a framework bug. This makes debugging extremely difficult.

**Recommendation:** Catch specific expected exceptions (e.g., `RuntimeError`, `WorkflowStageError`) for graceful degradation. Let truly unexpected exceptions (`TypeError`, `AttributeError`, `KeyError`) propagate or at minimum mark the workflow as failed, not just the stage.

#### H-02: Cancellation flag is not thread-safe (2 locations)

Both `DynamicCompiledWorkflow._cancelled` and `LangGraphCompiledWorkflow._cancelled` are plain booleans without any synchronization. The `cancel()` method is documented as being callable from a different thread than `invoke()`/`ainvoke()`, but there is no memory barrier to ensure visibility.

- `engines/dynamic_engine.py:56,70,93,136`
- `engines/langgraph_engine.py:51,100,127,222`

**Impact:** On CPython, this is practically safe due to the GIL, but on alternative runtimes or if async cancellation is used, the flag may not be visible to the executing thread. More importantly, cancellation is only checked *before* execution starts -- a long-running workflow cannot be cancelled mid-flight.

**Recommendation:** Use `threading.Event` for the cancellation flag. Additionally, consider checking `_cancelled` between stages inside `WorkflowExecutor.run()` for cooperative mid-execution cancellation.

#### H-03: `_extract_stage_names` duplicated 3 times with near-identical logic

The same stage-name extraction logic exists in three places:

1. `engines/dynamic_engine.py:142-159` -- `DynamicCompiledWorkflow._extract_stage_names` (staticmethod)
2. `engines/langgraph_engine.py:53-83` -- `LangGraphCompiledWorkflow._extract_stage_names` (instance method)
3. `engines/langgraph_compiler.py:433-450` -- `LangGraphCompiler._extract_stage_names` (instance method, delegates to NodeBuilder)

All three handle `str`, `dict`, and object formats identically. This violates DRY and creates a maintenance risk -- if the format changes, three places must be updated.

**Recommendation:** Extract to a shared utility function in `execution_engine.py` or a new `engines/_utils.py` module, e.g., `extract_stage_names(stages: list[Any]) -> list[str]`.

### Medium

#### M-01: Validation logic duplicated between DynamicExecutionEngine and LangGraphCompiler

Both engines have nearly-identical `_validate_all_configs` methods:

- `engines/dynamic_engine.py:409-432` (`_validate_all_configs`, `_validate_stage_config`, `_validate_agent_configs_for_stage`)
- `engines/langgraph_compiler.py:348-431` (`_validate_all_configs`, `_load_and_validate_stage`, `_validate_agent_configs`)

The logic is structurally the same: iterate stages, load config, validate with Pydantic, collect errors. The dynamic engine version is slightly tighter (catches specific exceptions), while the LangGraph version catches broad `except Exception`.

**Impact:** Bug fixes or schema changes need to be applied in two places.

**Recommendation:** Extract validation into a shared `ConfigValidator` class or standalone function.

#### M-02: `_merge_dicts` implemented twice with different semantics

Two independent `_merge_dicts` implementations exist:

1. `engines/dynamic_runner.py:22-35` -- Recursive merge (nested dict values are merged, not replaced)
2. `langgraph_state.py:24-39` -- Shallow merge (simple `dict.update`, right wins)

Both are used as "merge reducers" but have different depth behavior. This inconsistency means parallel stages in the dynamic engine recursively merge nested dicts, while LangGraph parallel branches do not.

**Impact:** Subtle behavioral differences between engines. A workflow that works correctly on one engine may produce different results on the other.

**Recommendation:** Unify semantics. Either both should do recursive merge or both should do shallow merge. Document the chosen behavior.

#### M-03: `_follow_sequential_signals_from` is dead code

`_dynamic_edge_helpers.py:257-279` defines `_follow_sequential_signals_from` which is never called anywhere in the codebase. It was superseded by `_follow_sequential_signals_dedup` (line 282) but was not removed.

**Impact:** Dead code increases cognitive load and maintenance burden.

**Recommendation:** Remove the function.

#### M-04: LangGraphCompiler uses f-string in logger call

`engines/langgraph_compiler.py:368`:
```python
logger.info(f"Configuration validation passed for {len(stages)} stages")
```

The equivalent line in `dynamic_engine.py:432` correctly uses `%s` formatting:
```python
logger.info("Configuration validation passed for %d stages", len(stages))
```

**Impact:** f-string logging evaluates the format string even when the log level is disabled. Minor performance impact, but violates the codebase's own coding standard.

**Recommendation:** Change to `logger.info("Configuration validation passed for %d stages", len(stages))`.

#### M-05: `LangGraphCompiler` has broad `except Exception` catches in validation

`engines/langgraph_compiler.py:380,393,412,427` -- The `_load_and_validate_stage` and `_validate_agent_configs` methods catch bare `except Exception as e:` in several places. The dynamic engine version (`dynamic_engine.py:450`) catches specific exceptions: `(FileNotFoundError, ValueError, KeyError)`.

**Impact:** Broad catches in the LangGraph compiler may mask unexpected errors during config loading, making debugging harder.

**Recommendation:** Align with the dynamic engine's approach of catching specific exceptions.

#### M-06: `WorkflowExecutor._execute_with_loop` has 8 parameters

`engines/workflow_executor.py:533` -- `_execute_with_loop(self, stage_name, stage_ref, stage_nodes, ref_lookup, stage_refs, state, workflow_config)` has 8 parameters (including `self`), exceeding the 7-parameter threshold.

**Impact:** Code quality deduction per coding standards.

**Recommendation:** Group related parameters into a dataclass (e.g., `ExecutionContext` holding `stage_nodes`, `ref_lookup`, `stage_refs`, `workflow_config`).

#### M-07: Several functions exceed 50-line threshold

| File | Function | Lines |
|---|---|---|
| `engines/workflow_executor.py:361` | `WorkflowExecutor.run` | 72 |
| `engines/workflow_executor.py:477` | `_execute_parallel_stages` | 55 |
| `engines/workflow_executor.py:533` | `_execute_with_loop` | 53 |
| `engines/_dynamic_edge_helpers.py:28` | `follow_dynamic_edges` | 55 |
| `engines/_dynamic_edge_helpers.py:127` | `_follow_parallel_targets` | 70 |
| `engines/langgraph_engine.py:291` | `execute` | 54 |
| `langgraph_state.py:152` | `to_dict` | 68 |
| `workflow_executor.py:221` | `execute_with_checkpoints` | 82 |
| `workflow_executor.py:354` | `resume_from_checkpoint` | 57 |

9 functions exceed the 50-line limit.

**Impact:** Readability and testability. Some of these (like `execute_with_checkpoints` at 82 lines) are borderline complex.

**Recommendation:** Extract helper methods. For `WorkflowExecutor.run`, the depth-group iteration loop could be a separate method. For `execute_with_checkpoints`, the checkpoint save logic is already partially extracted.

#### M-08: STREAM mode not implemented in either engine

Both `DynamicExecutionEngine.execute()` and `LangGraphExecutionEngine.execute()` raise `NotImplementedError("STREAM mode not yet supported")` when `mode == ExecutionMode.STREAM`. However, `CompiledGraphRunner.stream()` in `workflow_executor.py` does support streaming via `graph.stream()`.

**Impact:** The `ExecutionEngine` abstraction exposes STREAM as a valid mode but neither implementation supports it, while the lower-level `CompiledGraphRunner` does.

**Recommendation:** Either remove `STREAM` from `ExecutionMode` enum, or implement streaming support in the engine adapters by delegating to the underlying graph's `stream()` method.

### Low

#### L-01: Test duplication between `test_native_engine.py` and `test_dynamic_engine.py`

`test_native_engine.py` (268 LOC, 22 tests) is an almost exact copy of `test_dynamic_engine.py` (308 LOC, 27 tests), just using the `Native*` aliases. Since `NativeExecutionEngine is DynamicExecutionEngine`, these tests exercise the exact same code paths.

**Impact:** Maintenance overhead. Any test change must be replicated.

**Recommendation:** Keep `test_dynamic_engine.py` as the primary test file. Reduce `test_native_engine.py` to only verify that the import aliases resolve correctly (5-10 tests max).

#### L-02: `_validate_quality_gates` and `_execute_parallel_stage` on `LangGraphCompiler` exist only for backward compatibility

`engines/langgraph_compiler.py:231-268` and `292-331` -- Both methods are documented as existing "for backwards compatibility with tests" and delegate directly to `ParallelStageExecutor`. They add surface area and coupling to the compiler.

**Impact:** Dead weight. If tests were updated to call the executor directly, these wrappers could be removed.

**Recommendation:** Update tests to use `ParallelStageExecutor` directly, then remove these wrappers.

#### L-03: `WorkflowExecutor` naming collision between two files

`engines/workflow_executor.py` defines `class WorkflowExecutor` (DAG walker), while `workflow_executor.py` (top-level) defines `WorkflowExecutor = CompiledGraphRunner` as an alias. Both are importable as `WorkflowExecutor` from different paths:

- `from temper_ai.workflow.engines.workflow_executor import WorkflowExecutor` (DAG walker)
- `from temper_ai.workflow.workflow_executor import WorkflowExecutor` (CompiledGraphRunner)

`engines/langgraph_compiler.py:46` also re-exports: `WorkflowExecutor = CompiledGraphRunner`.

**Impact:** Import confusion. A developer importing `WorkflowExecutor` may get the wrong class depending on the import path.

**Recommendation:** Rename one of them. The DAG walker could be `StageDAGRunner` or `DAGWorkflowRunner`. The existing alias `CompiledGraphRunner` is already the canonical name for the LangGraph executor.

#### L-04: Singleton `EngineRegistry` uses class-level `_lock` and `_instance`

`engine_registry.py:33-34` -- `_lock` and `_instance` are class attributes. While the double-checked locking implementation is correct, the singleton pattern makes testing harder (requires `reset()`) and prevents having multiple registries.

**Impact:** Test isolation requires explicit `EngineRegistry.reset()` calls.

**Recommendation:** Acceptable as-is since `reset()` exists. Consider dependency injection for advanced use cases.

#### L-05: `_get_agent_mode` backward-compat method on `LangGraphCompiler`

`engines/langgraph_compiler.py:270-290` -- Simple accessor that exists "for backwards compatibility with integration tests". A 20-line method that does `stage_config["execution"]["agent_mode"]`.

**Impact:** Trivial dead weight.

**Recommendation:** Inline or remove when tests are updated.

---

## Code Quality

### Strengths

1. **Clean ABC hierarchy**: `ExecutionEngine` -> `CompiledWorkflow` abstractions are well-defined with proper abstract methods.
2. **Import fan-out**: All files are under the 8-module threshold (max is 6).
3. **No security issues**: No eval/exec/pickle/shell=True/yaml.load/f-string SQL found.
4. **Re-export shims**: Backward compatibility is maintained through thin re-export modules (`native_engine.py`, `native_runner.py`, top-level `langgraph_engine.py`).
5. **Helper extraction**: `_dynamic_edge_helpers.py` was correctly extracted from `workflow_executor.py` to keep the class manageable.
6. **Thread-safe registry**: `EngineRegistry` uses proper double-checked locking with threading.Lock.
7. **Docstrings**: Comprehensive docstrings on all public methods with Args/Returns/Raises sections.

### Weaknesses

1. **9 functions over 50 lines** -- The most complex being `execute_with_checkpoints` (82 lines).
2. **1 function over 7 params** -- `_execute_with_loop` (8 params).
3. **Code duplication** -- `_extract_stage_names` (3x), `_validate_all_configs` (2x), `_merge_dicts` (2x with different semantics).
4. **Broad exception catches** in LangGraph compiler validation.

---

## Security & Error Handling

### Security: Clean

- No injection vectors found (no f-string SQL, no eval/exec/pickle, no shell=True, no yaml.load).
- No secret handling in this module.
- State is passed as dicts -- no deserialization of untrusted data.
- Dynamic edge routing parses JSON from LLM output (`_parse_next_stage_from_text`), but only extracts `_next_stage` signal -- no arbitrary code execution from parsed content.

### Error Handling

| Pattern | Count | Assessment |
|---|---|---|
| Bare `except Exception:` | 2 | `dynamic_runner.py:121`, `workflow_executor.py:292` -- both in parallel execution. Logs but continues. |
| `except Exception as e:` | 6 | `langgraph_compiler.py` validation (4), `workflow_executor.py` checkpoint save (2) |
| Specific exception catches | 4 | `dynamic_engine.py:450` catches `(FileNotFoundError, ValueError, KeyError)` |
| `WorkflowStageError` propagation | 1 | `workflow_executor.py:427` -- properly halts workflow on stage error |

The dynamic engine has tighter error handling than the LangGraph compiler. The parallel execution paths are the weakest point -- they silently absorb exceptions to prevent one failed node from crashing the entire parallel batch.

---

## Dead Code

| Location | Description | Status |
|---|---|---|
| `_dynamic_edge_helpers.py:257-279` | `_follow_sequential_signals_from` | Dead -- superseded by `_follow_sequential_signals_dedup`, never called |
| `langgraph_compiler.py:231-268` | `_validate_quality_gates` | Backward compat wrapper -- delegates to executor |
| `langgraph_compiler.py:270-290` | `_get_agent_mode` | Backward compat wrapper -- trivial accessor |
| `langgraph_compiler.py:292-331` | `_execute_parallel_stage` | Backward compat wrapper -- delegates to executor |

---

## Test Quality

### Coverage Assessment

| Source Module | Test File(s) | Test Count | Verdict |
|---|---|---|---|
| `engines/dynamic_engine.py` | `test_dynamic_engine.py` | 27 | Good: engine lifecycle, features, compilation, cancellation |
| `engines/dynamic_engine.py` | `test_native_engine.py` | 22 | Redundant: nearly identical via alias |
| `engines/_dynamic_edge_helpers.py` | `test_native_workflow_executor.py` | ~15 | Good: parallel fan-out, convergence tested indirectly |
| `engines/dynamic_runner.py` | `test_native_runner.py` | 13 | Good: parallel execution, error handling, state isolation |
| `engines/langgraph_compiler.py` | `test_langgraph_compiler.py` | 13 | Adequate: compilation, validation, init_node |
| `engines/langgraph_engine.py` | `test_langgraph_engine.py` | 32 | Good: adapter pattern, metadata, visualization, feature detection |
| `engines/workflow_executor.py` | `test_native_workflow_executor.py` | 71 | Excellent: conditions, loops, negotiation, dynamic routing, multi-target |
| `engine_registry.py` | `test_engine_registry.py` | 23 | Excellent: singleton, thread safety, config parsing, error cases |
| `execution_engine.py` | `test_execution_engine.py` | 28 | Good: ABC enforcement, cancellation, enum behavior |
| `langgraph_state.py` | `test_langgraph_state.py` | 15 | Good: cache safety, field exclusion, post-init |
| `workflow_executor.py` | `test_workflow_executor.py` | 20 | Good: init, execute, stream, checkpoints, resume |

### Strengths

1. **264 total test functions** for 3,896 LOC (ratio: 1 test per ~15 LOC) -- very good coverage density.
2. **Thread safety tests** in `test_engine_registry.py` using barriers and concurrent read/write patterns.
3. **Multi-target dynamic routing** thoroughly tested with sequential, parallel, chain, dedup, and max-hop scenarios.
4. **Cancellation** tested in both sync and async paths, including background threads.

### Gaps

1. **No test for `_follow_sequential_signals_from`** (dead code, so acceptable).
2. **No test for convergence stage execution** (`_execute_convergence` in `_dynamic_edge_helpers.py`). The parallel fan-out + convergence path is only tested indirectly.
3. **No test for `execute_with_optimization`** in `workflow_executor.py:433-472`.
4. **No negative test for `_negotiate_with_producer` when producer is not in stage_nodes** -- the warning log path is untested.
5. **Mock overuse**: Some tests (e.g., `test_langgraph_compiler.py`) rely heavily on mocks for config_loader, which means they don't catch real config-loading failures.

---

## Feature Completeness

### TODO/FIXME/HACK Inventory

None found across all source files in scope.

### Partial Implementations

| Feature | Status | Location | Notes |
|---|---|---|---|
| STREAM mode | Not implemented | Both engines | `NotImplementedError` raised. `CompiledGraphRunner.stream()` exists separately. |
| Mid-execution cancellation | Partial | Both engines | Flag checked only before `invoke()`/`ainvoke()`, not between stages. |
| Distributed execution | Not supported | Both engines | `supports_feature("distributed_execution")` returns False. |
| Nested workflows | Not supported | Both engines | `supports_feature("nested_workflows")` returns False. |

---

## Architectural Gaps vs Vision

### Radical Modularity

**Score: Strong (8/10)**

The engine system is well-modularized:
- `ExecutionEngine` ABC enables swapping engines at runtime.
- `EngineRegistry` provides factory-pattern creation from YAML config.
- `CompiledWorkflow` ABC allows engine-specific internal representations.
- Clean separation: compiler -> compiled workflow -> executor.

**Gap:** The validation logic is duplicated rather than shared, reducing true modularity.

### Configuration as Product

**Score: Strong (9/10)**

- Engine selection is YAML-driven: `workflow.engine: "dynamic"` or `"langgraph"`.
- `engine_config` section supports per-engine kwargs.
- `EngineRegistry.get_engine_from_config()` handles the full parsing.

**Gap:** None significant.

### Observability as Foundation

**Score: Adequate (6/10)**

- `LangGraphCompiledWorkflow` accepts an optional `tracker` and injects it into state.
- `CompiledGraphRunner` passes `tracker` to `initialize_state`.
- Stage execution logging is present throughout `WorkflowExecutor.run`.

**Gaps:**
- `DynamicCompiledWorkflow` does NOT accept or propagate a tracker. The dynamic engine has no tracker injection point.
- No span/trace creation at the engine level. Tracing depends on lower-level stage executors.
- Checkpoint save/load events are logged but not emitted as structured events to the event bus.

### Progressive Autonomy

**Score: Minimal (3/10)**

- No trust escalation in the engine layer.
- No approval gates between stages.
- The safety stack is initialized (`create_safety_stack`) and passed to executors, but the engine layer does not enforce progressive autonomy policies.

**Gap:** Engine should check if a stage requires approval before execution, especially for high-impact stages.

### Self-Improvement Loop

**Score: Minimal (3/10)**

- `CompiledGraphRunner.execute_with_optimization()` exists and delegates to `OptimizationEngine`, but this is a one-shot optimization, not a feedback loop.
- No execution metrics are fed back to improve future runs.
- No learning from checkpoint/resume patterns.

**Gap:** The engine should emit execution telemetry (stage durations, error rates) that the learning system can consume.

### Merit-Based Collaboration

**Score: N/A**

Engine layer does not participate in agent collaboration decisions. This is appropriately handled at the stage executor level.

### Safety Through Composition

**Score: Good (7/10)**

- Both engines create a `create_safety_stack()` by default with `ActionPolicyEngine`, `ApprovalWorkflow`, `RollbackManager`.
- Safety stack is injected into all stage executors.
- `ToolExecutor` wraps all tool calls through the safety pipeline.

**Gaps:**
- Safety policies are not evaluated at the engine level (e.g., before compiling or executing a workflow).
- No blast radius checking for dynamic edge routing -- a stage can dynamically fan-out to any other stage without safety review.

---

## Improvement Opportunities

### Priority 1 (High Value, Moderate Effort)

1. **Extract shared utilities**: Create `engines/_utils.py` with `extract_stage_names()`, `validate_configs()`, and `merge_dicts()` to eliminate the 3x/2x/2x duplication.
2. **Tighten exception handling in parallel paths**: Replace broad `except Exception` with specific exception types in `_run_nodes_parallel` and `_run_parallel_stage_batch`. Let unexpected errors propagate.
3. **Add tracker support to DynamicCompiledWorkflow**: Accept optional `tracker` parameter and inject into state, matching `LangGraphCompiledWorkflow` behavior.

### Priority 2 (Medium Value, Small Effort)

4. **Remove dead code**: Delete `_follow_sequential_signals_from` and the three backward-compat wrappers on `LangGraphCompiler`.
5. **Fix f-string logger call**: `langgraph_compiler.py:368`.
6. **Unify `_merge_dicts` semantics**: Choose recursive or shallow, use one implementation.
7. **Use `threading.Event` for cancellation**: Thread-safe and supports blocking `wait()` for cooperative cancellation.

### Priority 3 (Incremental)

8. **Reduce function lengths**: Split `WorkflowExecutor.run` and `execute_with_checkpoints`.
9. **Reduce test duplication**: Collapse `test_native_engine.py` into import-alias-only tests.
10. **Add convergence test**: Directly test `_execute_convergence` path.
11. **Implement STREAM mode**: Or remove from `ExecutionMode` if not planned.

---

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 3 |
| Medium | 8 |
| Low | 5 |

The workflow engines module is architecturally sound with clean ABC abstractions, proper engine swapping via registry, and YAML-driven configuration. The dual-engine design (LangGraph + Dynamic) provides genuine execution flexibility. Test coverage is excellent at 264 tests across 10 files.

The main areas for improvement are: (1) code duplication across the two engine implementations (validation, stage name extraction, merge functions), (2) overly-broad exception handling in parallel execution paths that can mask bugs, and (3) the cancellation mechanism which is cooperative but not truly thread-safe. No security issues were found. The module would benefit most from extracting shared utilities and tightening exception handling -- both achievable with moderate effort and high payoff.
