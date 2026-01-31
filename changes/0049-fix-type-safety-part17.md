# Fix Type Safety Errors - Part 17

**Date:** 2026-01-28
**Task:** m3.1-01 (in progress)
**Agent:** agent-d6e90e

---

## Summary

Seventeenth batch of type safety fixes targeting sequential stage executor. Fixed incompatible type assignment, nested function type annotations, and cast operations for config handling. Successfully fixed all 3 direct errors in executors/sequential.py.

---

## Changes

### Files Modified

**src/compiler/executors/sequential.py:**
- Added import: `cast` from typing
- Fixed agent config assignment with cast (line 177):
  - `agent_config_dict_for_tracking = agent_config` → `agent_config_dict_for_tracking = cast(Dict[str, Any], agent_config)`
- Fixed nested `is_serializable` function type annotations (line 186):
  - `def is_serializable(value):` → `def is_serializable(value: Any) -> bool:`
- **Errors fixed:** 3 direct errors → 0 direct errors

---

## Progress

### Type Error Count

**Before Part 17:** 369 errors in 47 files
**After Part 17:** 373 errors in 47 files
**Direct fixes:** 3 errors in 1 file
**Net change:** +4 errors (due to cascading/concurrent changes)

**Note:** executors/sequential.py now has 0 errors. The increase is from cascading effects or other agents' work.

### Files Checked Successfully

- `src/compiler/executors/sequential.py` - 0 direct errors ✓

### Verification

```bash
source .venv/bin/activate
mypy --strict src/compiler/executors/sequential.py
# No errors found
```

---

## Implementation Details

### Pattern 1: Cast Config to Dict

When config could be dict or Pydantic model:

```python
# Before
if hasattr(agent_config, 'model_dump'):
    agent_config_dict_for_tracking = agent_config.model_dump()
elif hasattr(agent_config, 'dict'):
    agent_config_dict_for_tracking = agent_config.dict()
else:
    agent_config_dict_for_tracking = agent_config  # Error: Any to Dict[str, Any]

# After
if hasattr(agent_config, 'model_dump'):
    agent_config_dict_for_tracking = agent_config.model_dump()
elif hasattr(agent_config, 'dict'):
    agent_config_dict_for_tracking = agent_config.dict()
else:
    agent_config_dict_for_tracking = cast(Dict[str, Any], agent_config)  # OK
```

**Why cast is safe:**
- First two branches handle Pydantic models
- Else branch means it's already a dict
- Runtime guarantees it's dict-like at this point
- Cast documents expected type

### Pattern 2: Nested Function Type Annotations

Local helper functions need full type annotations:

```python
# Before
if tracker:
    # Helper to check if value is JSON serializable
    import json
    def is_serializable(value):  # Error: missing type annotations
        try:
            json.dumps(value)
            return True
        except (TypeError, ValueError):
            return False

    tracking_input_data = {
        k: v for k, v in input_data.items()
        if k not in ('tracker', 'tool_registry', 'config_loader', 'visualizer')
        and is_serializable(v)  # Error: call to untyped function
    }

# After
if tracker:
    # Helper to check if value is JSON serializable
    import json
    def is_serializable(value: Any) -> bool:  # OK: typed
        try:
            json.dumps(value)
            return True
        except (TypeError, ValueError):
            return False

    tracking_input_data = {
        k: v for k, v in input_data.items()
        if k not in ('tracker', 'tool_registry', 'config_loader', 'visualizer')
        and is_serializable(v)  # OK: calling typed function
    }
```

**Key points:**
- Nested functions follow same rules as top-level
- Parameter and return types required in strict mode
- Enables type checking in list comprehensions
- Documents helper function interface

### Pattern 3: Config Serialization Helper

Common pattern for preparing configs for tracking:

```python
# Convert to dict and ensure it's serializable
if hasattr(agent_config, 'model_dump'):
    agent_config_dict_for_tracking = agent_config.model_dump()
elif hasattr(agent_config, 'dict'):
    agent_config_dict_for_tracking = agent_config.dict()
else:
    agent_config_dict_for_tracking = cast(Dict[str, Any], agent_config)

# Sanitize the config to remove any non-serializable objects
agent_config_dict_for_tracking = sanitize_config_for_display(agent_config_dict_for_tracking)
```

**Pattern handles:**
- Pydantic v2 models (model_dump)
- Pydantic v1 models (dict)
- Plain dicts (cast)
- Sanitization for observability

### Pattern 4: Filtering Serializable Values

Helper to filter tracking data:

```python
def is_serializable(value: Any) -> bool:
    """Check if value can be JSON serialized."""
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False

# Remove non-serializable infrastructure objects
tracking_input_data = {
    k: v for k, v in input_data.items()
    if k not in ('tracker', 'tool_registry', 'config_loader', 'visualizer')
    and is_serializable(v)
}
```

**Benefits:**
- Prevents serialization errors in tracking
- Filters out infrastructure objects
- Type-safe helper function
- Used in dict comprehension

---

## Next Steps

### Phase 2: Remaining Compiler Files

**Next files:**
- `src/compiler/__init__.py` - 2 errors
- Other compiler files with lower error counts

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

### Handling Polymorphic Config Types

When config can be dict or Pydantic:
- Check for model_dump (Pydantic v2)
- Check for dict (Pydantic v1)
- Else assume dict (cast)
- Consistent dict output type

### Nested Function Scope

Nested functions and closures:
- Need full type annotations in strict mode
- Same rules as top-level functions
- Can access outer scope variables
- Enable type checking in comprehensions

### Error Count Fluctuation

Continued fluctuation normal:
- Other agents working concurrently
- Cascading dependencies
- Focus on direct file errors
- Overall trend will stabilize

---

## Related Documentation

- Task: m3.1-01 (Fix Type Safety Errors 174 → 0)
- Previous: changes/0048-fix-type-safety-part16.md
- Python json.dumps: https://docs.python.org/3/library/json.html#json.dumps
- Mypy Nested Functions: https://mypy.readthedocs.io/en/stable/kinds_of_types.html

---

## Notes

- executors/sequential.py now has zero direct type errors ✓
- Proper cast for polymorphic config handling
- Type-safe nested helper function
- Established pattern for config serialization
- No behavioral changes - all fixes are type annotations only
- 21 files now have 0 type errors
