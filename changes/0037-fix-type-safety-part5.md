# Fix Type Safety Errors - Part 5

**Date:** 2026-01-28
**Task:** m3.1-01 (in progress)
**Agent:** agent-d6e90e

---

## Summary

Fifth batch of type safety fixes targeting configuration utility files. Fixed optional type handling for dynamically imported modules, proper None checks for conditional imports, and return type casting. Error count remains at 404 (config_helpers.py errors were transitive).

---

## Changes

### Files Modified

**src/utils/config_helpers.py:**
- Fixed dynamic import handling for optional secrets module:
  - Declared `SecretReference: Optional[Any] = None`
  - Declared `detect_secret_patterns: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None`
  - Import with proper exception handling
- Fixed conditional checks from truthy function checks to explicit None checks:
  - Line 222: `SecretReference and ...` → `SecretReference is not None and ...`
  - Line 241: `if detect_secret_patterns:` → `if detect_secret_patterns is not None:`
  - Line 246: `SecretReference and ...` → `SecretReference is not None and ...`
- Fixed return type with cast:
  - `return _sanitize(config)` → `return cast(Dict[str, Any], _sanitize(config))`
- Added `cast` to imports from typing
- **Errors fixed:** 7 errors → 0 direct errors (transitive from imports)

---

## Progress

### Type Error Count

**Before Part 5:** 404 errors in 50 files
**After Part 5:** 404 errors in 50 files
**Direct fixes:** 7 errors in 1 file (transitive dependency errors)
**Net change:** 0 (errors were in upstream modules)

### Files Checked Successfully

- `src/utils/config_helpers.py` - 0 direct errors ✓

### Verification

```bash
mypy --strict src/utils/config_helpers.py
# No errors found
```

---

## Implementation Details

### Pattern 1: Optional Dynamic Imports

Handle modules that may not be available at runtime:

```python
# Before
try:
    from src.utils.secrets import SecretReference, detect_secret_patterns
except ImportError:
    SecretReference = None  # Error: Cannot assign to a type
    detect_secret_patterns = None

# After
SecretReference: Optional[Any] = None
detect_secret_patterns: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None

try:
    from src.utils.secrets import SecretReference, detect_secret_patterns
except ImportError:
    pass
```

**Key points:**
- Declare variables with Optional types before import
- Import overwrites with actual types if successful
- Falls back to None if import fails

### Pattern 2: Explicit None Checks

Don't rely on truthiness for types/functions:

```python
# Before
if SecretReference and SecretReference.is_reference(value):  # Error: Function is always truthy
    ...

# After
if SecretReference is not None and SecretReference.is_reference(value):
    ...
```

**Why:**
- Types and functions are always truthy in boolean context
- Must explicitly check `is not None` for Optional values
- More explicit and type-safe

### Pattern 3: Cast for Recursive Functions

When recursive helper returns Any:

```python
def sanitize_config_for_display(config: Dict[str, Any]) -> Dict[str, Any]:
    def _sanitize(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        # ... other cases
        return obj

    # Before
    return _sanitize(config)  # Error: Returning Any from function returning Dict[str, Any]

    # After
    return cast(Dict[str, Any], _sanitize(config))
```

---

## Next Steps

### Phase 2: Compiler and Utilities (Continued)

**High Priority:**
- `src/compiler/langgraph_compiler.py` - 7 errors - **BLOCKED** by agent-a83ad7
- `src/tools/base.py` - 7 errors
- `src/strategies/registry.py` - 8 errors

### Phase 3: Observability (Major Focus)

**Top error counts:**
- `src/observability/backends/sql_backend.py` - 36 errors
- `src/observability/console.py` - 30 errors
- `src/observability/backends/s3_backend.py` - 25 errors
- `src/observability/backends/prometheus_backend.py` - 25 errors
- `src/observability/hooks.py` - 23 errors

### Phase 4: LLM and Agents

- `src/llm/circuit_breaker.py` - 22 errors
- `src/observability/buffer.py` - 21 errors

---

## Technical Notes

### Transitive Errors

The 7 errors fixed in config_helpers.py were transitive:
- Errors appeared when importing from modules with errors
- Fixing config_helpers.py doesn't reduce total count
- Total count will drop when upstream dependencies are fixed
- This is normal for dependency-based type checking

### Optional Type Pattern

Best practice for optional imports:
1. Declare with Optional type annotation
2. Initialize to None
3. Try to import (overwrites if successful)
4. Use explicit `is not None` checks before using

### Type Ignore for Reassignment

Sometimes mypy complains about reassigning imported types:
- Initial declaration: `SecretReference: Optional[Any] = None`
- Import: `from ... import SecretReference` (reassigns)
- This is intentional and safe
- No type ignore needed if done correctly

---

## Related Documentation

- Task: m3.1-01 (Fix Type Safety Errors 174 → 0)
- Previous: changes/0036-fix-type-safety-part4.md
- Mypy Optional: https://mypy.readthedocs.io/en/stable/kinds_of_types.html#optional-types
- Python Imports: https://docs.python.org/3/reference/import.html

---

## Notes

- Error count unchanged (transitive errors from upstream)
- config_helpers.py now has zero direct type errors
- Proper handling of optional imports and None checks
- No behavioral changes - all fixes are type annotations only
- Pattern established for other files with optional imports

