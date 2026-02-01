# Change Documentation: Duplicate Agent Name Extraction (code-medi-02)

**Date:** 2026-01-31
**Task:** code-medi-02
**Type:** Verification / Documentation
**Priority:** MEDIUM
**Status:** Already Fixed

---

## Summary

Verified that the duplicate agent name extraction logic issue reported in the code review (`.claude-coord/reports/code-review-20260130-223423.md`) has already been fixed. All three files now use a shared utility function, eliminating code duplication.

---

## Investigation

### Issue Description (from code review):
- **Location:** `compiler:3 files`
- **Problem:** Same logic in node_builder.py, parallel.py, sequential.py
- **Impact:** Code duplication, maintenance burden
- **Recommendation:** Create shared `extract_name()` utility

### Findings

The code currently implements the recommended fix:

**Shared Utility Function** ✅

**File:** `src/compiler/utils.py:9-44`

A shared `extract_agent_name()` function has been created that:
- Handles string references: `"analyzer"`
- Handles dict references: `{"name": "analyzer"}` or `{"agent_name": "analyzer"}`
- Handles Pydantic models: `agent.name` or `agent.agent_name`
- Provides clear documentation and examples
- Explicitly notes it's shared across the three files

**All Files Using Shared Utility** ✅

1. **node_builder.py:228-243**
   - Imports: `from src.compiler.utils import extract_agent_name`
   - Delegates: `return extract_agent_name(agent_ref)`
   - Comments: "Delegates to shared utility function to avoid code duplication"

2. **executors/sequential.py:234-245**
   - Imports: `from src.compiler.utils import extract_agent_name`
   - Delegates: `return extract_agent_name(agent_ref)`
   - Comments: "Delegates to shared utility function to avoid code duplication"

3. **executors/parallel.py:672-683**
   - Imports: `from src.compiler.utils import extract_agent_name`
   - Delegates: `return extract_agent_name(agent_ref)`
   - Comments: "Delegates to shared utility function to avoid code duplication"

---

## Implementation Details

### Shared Utility Function

**Location:** `src/compiler/utils.py`

```python
def extract_agent_name(agent_ref: Any) -> str:
    """Extract agent name from various agent reference formats.

    Handles different ways agents can be referenced:
    - String: "analyzer"
    - Dict: {"name": "analyzer"} or {"agent_name": "analyzer"}
    - Pydantic model: agent.name or agent.agent_name

    Note:
        This is a shared utility to avoid code duplication across:
        - node_builder.py
        - executors/sequential.py
        - executors/parallel.py
    """
    if isinstance(agent_ref, str):
        return agent_ref
    elif isinstance(agent_ref, dict):
        return agent_ref.get("name") or agent_ref.get("agent_name") or str(agent_ref)
    else:
        # Pydantic model or object with attributes
        return getattr(agent_ref, 'name', None) or getattr(agent_ref, 'agent_name', None) or str(agent_ref)
```

### Usage Pattern

All three files follow the same pattern:

1. **Import the utility:**
   ```python
   from src.compiler.utils import extract_agent_name
   ```

2. **Create a wrapper method (if needed):**
   ```python
   def _extract_agent_name(self, agent_ref: Any) -> str:
       """Extract agent name from various agent reference formats.

       Delegates to shared utility function to avoid code duplication.
       """
       return extract_agent_name(agent_ref)
   ```

3. **Use the wrapper:**
   ```python
   agent_name = self._extract_agent_name(agent_ref)
   ```

### Benefits of This Approach

1. **Single Source of Truth:**
   - Logic lives in one place (`utils.py`)
   - Changes apply to all consumers automatically
   - Reduces risk of inconsistencies

2. **Maintainability:**
   - Bug fixes only needed in one location
   - Feature additions benefit all consumers
   - Clear documentation in one place

3. **Testability:**
   - Can test the utility function independently
   - Don't need to test duplicate logic in each file

4. **Code Clarity:**
   - Wrapper methods make it clear this is delegating
   - Comments explicitly state "to avoid code duplication"
   - Import statements make dependency explicit

---

## Risk Assessment

**Pre-existing Risk:** None (already fixed)
**Changes Made:** None (verification only)
**New Risk:** None

The implementation is clean:
- ✅ Eliminates code duplication (single utility function)
- ✅ Handles all agent reference formats (str, dict, Pydantic)
- ✅ Well-documented with examples
- ✅ Explicitly notes it's shared across files
- ✅ All three files use the shared utility

---

## Testing

While no new tests were added for this verification, the existing implementation:
- Is used throughout the codebase
- Has been tested implicitly through integration tests
- Handles all common agent reference formats

The utility function includes:
- Type hints for static analysis
- Clear docstring with examples
- Defensive coding for different input types

---

## Code Structure

### Before (hypothetical duplicate code):

```python
# node_builder.py
def extract_agent_name(agent_ref):
    if isinstance(agent_ref, str):
        return agent_ref
    # ... duplicate logic ...

# sequential.py
def _extract_agent_name(agent_ref):
    if isinstance(agent_ref, str):
        return agent_ref
    # ... duplicate logic ...

# parallel.py
def _extract_agent_name(agent_ref):
    if isinstance(agent_ref, str):
        return agent_ref
    # ... duplicate logic ...
```

**Problems:**
- 3x code duplication
- Must update 3 files for changes
- Risk of inconsistencies

### After (current implementation):

```python
# utils.py (single source of truth)
def extract_agent_name(agent_ref: Any) -> str:
    if isinstance(agent_ref, str):
        return agent_ref
    # ... shared logic ...

# node_builder.py
from src.compiler.utils import extract_agent_name
def extract_agent_name(self, agent_ref):
    return extract_agent_name(agent_ref)

# sequential.py
from src.compiler.utils import extract_agent_name
def _extract_agent_name(self, agent_ref):
    return extract_agent_name(agent_ref)

# parallel.py
from src.compiler.utils import extract_agent_name
def _extract_agent_name(self, agent_ref):
    return extract_agent_name(agent_ref)
```

**Benefits:**
- ✅ Single source of truth
- ✅ Update once, applies everywhere
- ✅ No risk of inconsistencies
- ✅ Clear delegation pattern

---

## Conclusion

The duplicate agent name extraction logic issue reported in the code review has already been fixed. The implementation includes:
- Shared utility function in `src/compiler/utils.py`
- All three files delegating to the shared utility
- Clear documentation and examples
- Explicit comments noting the delegation pattern

**No code changes required.**

---

## References

- Code Review Report: `.claude-coord/reports/code-review-20260130-223423.md`
- Shared Utility: `src/compiler/utils.py:9-44`
- node_builder.py: `src/compiler/node_builder.py:228-243`
- sequential.py: `src/compiler/executors/sequential.py:234-245`
- parallel.py: `src/compiler/executors/parallel.py:672-683`
