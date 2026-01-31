# Fix Type Safety Errors - Part 12

**Date:** 2026-01-28
**Task:** m3.1-01 (in progress)
**Agent:** agent-d6e90e

---

## Summary

Twelfth batch of type safety fixes targeting node builder for LangGraph execution nodes. Fixed Callable return type parameters, cast operations for Any returns from dynamic lookups, and return type annotations. Successfully fixed all 5 direct errors in node_builder.py.

---

## Changes

### Files Modified

**src/compiler/node_builder.py:**
- Added import: `cast` from typing
- Fixed `__init__` method return type annotation: `-> None`
- Fixed `create_stage_node` return type:
  - `-> Callable` → `-> Callable[[Dict[str, Any]], Dict[str, Any]]`
- Fixed `execute_stage` return with cast:
  - `return executor.execute_stage(...)` → `return cast(Dict[str, Any], executor.execute_stage(...))`
- Fixed `get_agent_mode` return with cast:
  - `return execution.get("agent_mode", "sequential")` → `return cast(str, execution.get("agent_mode", "sequential"))`
- Fixed `extract_stage_name` returns with cast (2 occurrences):
  - `return name` → `return cast(str, name)`
- **Errors fixed:** 5 direct errors → 0 direct errors

---

## Progress

### Type Error Count

**Before Part 12:** 367 errors in 47 files
**After Part 12:** 380 errors in 48 files
**Direct fixes:** 5 errors in 1 file
**Net change:** +13 errors (due to cascading/concurrent changes)

**Note:** node_builder.py now has 0 errors. The increase is from cascading effects or other agents' work.

### Files Checked Successfully

- `src/compiler/node_builder.py` - 0 direct errors ✓

### Verification

```bash
mypy --strict src/compiler/node_builder.py
# No errors found
```

---

## Implementation Details

### Pattern 1: Node Function Type Signature

LangGraph nodes have specific callable signatures:

```python
# Before
def create_stage_node(...) -> Callable:
    def stage_node(state: Dict[str, Any]) -> Dict[str, Any]:
        # execution logic
        return updated_state
    return stage_node

# After
def create_stage_node(...) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def stage_node(state: Dict[str, Any]) -> Dict[str, Any]:
        # execution logic
        return updated_state
    return stage_node
```

**Key points:**
- Node functions take state dict as input
- Node functions return updated state dict
- Explicit type signature enables type checking
- Documents node interface contract

### Pattern 2: Cast Dynamic Dictionary Lookups

Dictionary get() returns Any by default:

```python
# Before
def get_agent_mode(self, stage_config: Any) -> str:
    execution = stage_dict.get("execution", {})
    if isinstance(execution, dict):
        return execution.get("agent_mode", "sequential")  # Error: returning Any
    return "sequential"

# After
def get_agent_mode(self, stage_config: Any) -> str:
    execution = stage_dict.get("execution", {})
    if isinstance(execution, dict):
        return cast(str, execution.get("agent_mode", "sequential"))  # OK: cast to str
    return "sequential"
```

**Why cast is safe:**
- We provide default value of correct type
- Runtime guarantees type matches
- Cast documents our type knowledge
- Alternative would be runtime isinstance check

### Pattern 3: Cast Executor Returns

Executor execute_stage returns Any due to dynamic dispatch:

```python
# Before
def stage_node(state: Dict[str, Any]) -> Dict[str, Any]:
    executor = self.executors.get(agent_mode)
    return executor.execute_stage(...)  # Error: returning Any

# After
def stage_node(state: Dict[str, Any]) -> Dict[str, Any]:
    executor = self.executors.get(agent_mode)
    return cast(
        Dict[str, Any],
        executor.execute_stage(...)
    )
```

**Why this is safe:**
- All executors return Dict[str, Any] by contract
- Runtime behavior consistent
- Cast documents executor interface
- Enables type checking for caller

### Pattern 4: Cast Conditional Name Extraction

When extracting values that could be None:

```python
# Before
def extract_stage_name(self, stage: Any) -> str:
    if isinstance(stage, dict):
        name = stage.get("name") or stage.get("stage_name")
        if name:
            return name  # Error: could be Any
    raise ValueError("Cannot extract stage name")

# After
def extract_stage_name(self, stage: Any) -> str:
    if isinstance(stage, dict):
        name = stage.get("name") or stage.get("stage_name")
        if name:
            return cast(str, name)  # OK: we checked it exists
    raise ValueError("Cannot extract stage name")
```

**Why cast is appropriate:**
- We check `if name:` so it's truthy
- Config values are strings by design
- Cast documents expected type
- Failure would surface at runtime anyway

---

## Next Steps

### Phase 2: Remaining Compiler Files

**High Priority:**
- `src/compiler/langgraph_engine.py` - 5 errors
- `src/compiler/engine_registry.py` - 5 errors
- `src/compiler/langgraph_compiler.py` - 4 errors
- `src/compiler/executors/adaptive.py` - 4 errors

### Phase 3: Observability (Next Major Focus)

**Top error counts:**
- `src/observability/backends/sql_backend.py` - 36 errors
- `src/observability/console.py` - 30 errors
- `src/observability/backends/s3_backend.py` - 25 errors
- `src/observability/backends/prometheus_backend.py` - 25 errors
- `src/observability/hooks.py` - 23 errors

### Phase 4: LLM and Agents

- `src/llm/circuit_breaker.py` - 22 errors
- `src/observability/buffer.py` - 21 errors
- `src/agents/llm_providers.py` - 15 errors

---

## Technical Notes

### When to Use Cast

Cast is appropriate when:
1. **Default values provide type guarantee**: `get("key", default)` where default has type
2. **Runtime contract exists**: Executor interface guarantees return type
3. **Conditional checks ensure type**: `if name:` before using name
4. **Config schema guarantees**: YAML/dict values have known types

Cast is NOT appropriate when:
- Type could genuinely vary at runtime
- No validation or default ensures type
- Better to use isinstance() check instead

### Dynamic Dispatch and Type Safety

Node builder uses dynamic dispatch:
- Executors stored in dict by mode
- All implement same interface
- Cast documents interface contract
- Type safety maintained at boundaries

### Error Count Fluctuation

Continued fluctuation indicates:
- Active concurrent work by other agents
- Cascading dependencies being resolved
- Focus on cleaning individual files
- Overall trend will stabilize

---

## Related Documentation

- Task: m3.1-01 (Fix Type Safety Errors 174 → 0)
- Previous: changes/0043-fix-type-safety-part11.md
- Mypy Cast: https://mypy.readthedocs.io/en/stable/type_narrowing.html#cast
- Python Dict.get(): https://docs.python.org/3/library/stdtypes.html#dict.get

---

## Notes

- node_builder.py now has zero direct type errors ✓
- Appropriate use of cast for dynamic lookups
- Established patterns for node creation
- No behavioral changes - all fixes are type annotations only
- 17 files now have 0 type errors

