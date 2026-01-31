# Fix Type Safety Errors - Part 15

**Date:** 2026-01-28
**Task:** m3.1-01 (in progress)
**Agent:** agent-d6e90e

---

## Summary

Fifteenth batch of type safety fixes targeting adaptive stage executor. Fixed __init__ parameter types, nested class annotations, and cast operations for aggregate functions. Successfully fixed all 4 direct errors in executors/adaptive.py.

---

## Changes

### Files Modified

**src/compiler/executors/adaptive.py:**
- Added import: `cast` from typing
- Fixed `__init__` method parameters and return type:
  - `synthesis_coordinator=None` → `synthesis_coordinator: Optional[Any] = None`
  - `quality_gate_validator=None` → `quality_gate_validator: Optional[Any] = None`
  - Added return type: `-> None`
- Fixed nested `MinimalSynthesisResult` class __init__:
  - `def __init__(self, votes):` → `def __init__(self, votes: Dict[str, int]) -> None:`
- Fixed `_calculate_disagreement_rate` method with casts:
  - `total_votes = sum(votes.values())` → `total_votes = cast(int, sum(votes.values()))`
  - `max_votes = max(votes.values())` → `max_votes = cast(int, max(votes.values()))`
- **Errors fixed:** 4 direct errors → 0 direct errors

---

## Progress

### Type Error Count

**Before Part 15:** 376 errors in 47 files
**After Part 15:** 372 errors in 47 files
**Direct fixes:** 4 errors in 1 file
**Net change:** -4 errors ✓

**Note:** Continued net reduction in error count!

### Files Checked Successfully

- `src/compiler/executors/adaptive.py` - 0 direct errors ✓

### Verification

```bash
source .venv/bin/activate
mypy --strict src/compiler/executors/adaptive.py
# No direct errors found
```

---

## Implementation Details

### Pattern 1: Nested Class Type Annotations

Local classes need full type annotations:

```python
# Before
class MinimalSynthesisResult:
    def __init__(self, votes):  # Error: missing type annotations
        self.votes = votes

synthesis_result = MinimalSynthesisResult(votes=synthesis_info.get("votes", {}))

# After
class MinimalSynthesisResult:
    def __init__(self, votes: Dict[str, int]) -> None:
        self.votes = votes

synthesis_result = MinimalSynthesisResult(votes=synthesis_info.get("votes", {}))
```

**Key points:**
- Nested classes follow same rules as top-level classes
- Parameter types required in strict mode
- Return type -> None for void methods
- Enables type checking within nested scope

### Pattern 2: Cast Aggregate Functions

Built-in aggregate functions return generic types:

```python
# Before
def _calculate_disagreement_rate(self, synthesis_result: Any) -> float:
    votes = synthesis_result.votes or {}

    total_votes = sum(votes.values())  # Error: returns Any
    max_votes = max(votes.values())     # Error: returns Any

    disagreement_rate = 1.0 - (max_votes / total_votes)
    return disagreement_rate  # Error: returning Any

# After
def _calculate_disagreement_rate(self, synthesis_result: Any) -> float:
    votes = synthesis_result.votes or {}

    total_votes = cast(int, sum(votes.values()))  # OK: cast to int
    max_votes = cast(int, max(votes.values()))    # OK: cast to int

    disagreement_rate = 1.0 - (max_votes / total_votes)
    return disagreement_rate  # OK: returns float
```

**Why casts are safe:**
- votes is Dict[str, int] by design
- sum() of ints is int
- max() of ints is int
- Division produces float
- Casts document runtime types

### Pattern 3: Adaptive Executor Type Safety

Full executor with proper types:

```python
class AdaptiveStageExecutor(StageExecutor):
    """Execute with adaptive mode - parallel first, sequential on high disagreement."""

    def __init__(
        self,
        synthesis_coordinator: Optional[Any] = None,
        quality_gate_validator: Optional[Any] = None
    ) -> None:
        """Initialize with coordinator and validator."""
        self.sequential_executor = SequentialStageExecutor()
        self.parallel_executor = ParallelStageExecutor(
            synthesis_coordinator=synthesis_coordinator,
            quality_gate_validator=quality_gate_validator
        )

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: Any,
        tool_registry: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Execute with adaptive strategy."""
        # Try parallel first
        parallel_state = self.parallel_executor.execute_stage(...)

        # Check disagreement
        disagreement_rate = self._calculate_disagreement_rate(synthesis_result)

        # Switch to sequential if needed
        if disagreement_rate > threshold:
            return self.sequential_executor.execute_stage(...)
        return parallel_state

    def _calculate_disagreement_rate(self, synthesis_result: Any) -> float:
        """Calculate disagreement from vote counts."""
        votes = synthesis_result.votes or {}
        total_votes = cast(int, sum(votes.values()))
        max_votes = cast(int, max(votes.values()))
        return 1.0 - (max_votes / total_votes)
```

**Type safety features:**
- Optional infrastructure components
- Nested class properly typed
- Aggregate functions cast to expected types
- Return types explicit throughout

### Pattern 4: Local Class for Runtime Duck Typing

Sometimes need minimal class for duck typing:

```python
# Calculate disagreement rate from synthesis result
# We need to reconstruct a minimal SynthesisResult-like object
class MinimalSynthesisResult:
    def __init__(self, votes: Dict[str, int]) -> None:
        self.votes = votes

synthesis_result = MinimalSynthesisResult(votes=synthesis_info.get("votes", {}))
disagreement_rate = self._calculate_disagreement_rate(synthesis_result)
```

**When to use this pattern:**
- Need to pass data to method expecting specific interface
- Don't want to import full class
- Runtime duck typing with type safety
- Keeps dependencies minimal

---

## Next Steps

### Phase 2: Remaining Compiler Files

**Next file (if unlocked):**
- `src/compiler/langgraph_compiler.py` - 4 errors (currently locked by agent-a83ad7)

**Other compiler files:**
- Various compiler files with lower error counts

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

### Nested Class Type Safety

Local/nested classes need:
- Full parameter type annotations
- Return type annotations
- Same rules as top-level classes
- Enables type checking in nested scope

### Aggregate Function Returns

Python's built-in aggregate functions:
- sum() returns type based on iterable contents
- max()/min() return type based on iterable
- Type checker can't always infer from .values()
- Use cast() to document known runtime type

### When to Use Cast vs Assertion

Use cast when:
- Runtime type guaranteed by design
- Default values ensure type
- Contract guarantees type
- Alternative would be unnecessary isinstance

Use assertion when:
- Type could vary at runtime
- Need runtime type narrowing
- Want runtime safety check
- Better than cast for Optional types

---

## Related Documentation

- Task: m3.1-01 (Fix Type Safety Errors 174 → 0)
- Previous: changes/0046-fix-type-safety-part14.md
- Python sum(): https://docs.python.org/3/library/functions.html#sum
- Python max(): https://docs.python.org/3/library/functions.html#max

---

## Notes

- executors/adaptive.py now has zero direct type errors ✓
- Second consecutive net reduction in error count (-4 errors)
- Proper type annotations for nested classes
- Cast pattern for aggregate functions
- No behavioral changes - all fixes are type annotations only
- 20 files now have 0 type errors
