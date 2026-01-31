# Fix Type Safety Errors - Part 14

**Date:** 2026-01-28
**Task:** m3.1-01 (in progress)
**Agent:** agent-d6e90e

---

## Summary

Fourteenth batch of type safety fixes targeting engine registry singleton. Fixed singleton __new__ return type, initialization method return type, and **kwargs parameter type annotations. Successfully fixed all 5 direct errors in engine_registry.py.

---

## Changes

### Files Modified

**src/compiler/engine_registry.py:**
- Fixed `__new__` method return type:
  - `def __new__(cls):` → `def __new__(cls) -> "EngineRegistry":`
- Fixed `_initialize_default_engines` method return type:
  - `def _initialize_default_engines(self):` → `def _initialize_default_engines(self) -> None:`
- Fixed `get_engine` method **kwargs type annotation:
  - `**kwargs` → `**kwargs: Any`
- Fixed `get_engine_from_config` method **kwargs type annotation:
  - `**kwargs` → `**kwargs: Any`
- **Errors fixed:** 5 direct errors → 0 direct errors

---

## Progress

### Type Error Count

**Before Part 14:** 382 errors in 49 files
**After Part 14:** 376 errors in 47 files
**Direct fixes:** 5 errors in 1 file
**Net change:** -6 errors, -2 files ✓

**Note:** Actual reduction in total errors! First time seeing net decrease in several parts.

### Files Checked Successfully

- `src/compiler/engine_registry.py` - 0 direct errors ✓

### Verification

```bash
source .venv/bin/activate
mypy --strict src/compiler/engine_registry.py
# No direct errors found
```

---

## Implementation Details

### Pattern 1: Singleton __new__ Return Type

Singleton pattern __new__ must return instance type:

```python
# Before
def __new__(cls):
    """Singleton pattern - only one registry instance."""
    if cls._instance is None:
        cls._instance = super().__new__(cls)
        cls._instance._initialize_default_engines()
    return cls._instance  # Error: missing return type

# After
def __new__(cls) -> "EngineRegistry":
    """Singleton pattern - only one registry instance."""
    if cls._instance is None:
        cls._instance = super().__new__(cls)
        cls._instance._initialize_default_engines()
    return cls._instance  # OK: returns EngineRegistry
```

**Key points:**
- __new__ is special method that creates instance
- Must return instance of the class
- Use quoted string for forward reference to class name
- Enables type checking on singleton usage

### Pattern 2: Initialization Method Return Type

Methods that initialize state should return None:

```python
# Before
def _initialize_default_engines(self):
    """Register default engines on first instantiation."""
    try:
        from src.compiler.langgraph_engine import LangGraphExecutionEngine
        self._engines["langgraph"] = LangGraphExecutionEngine
    except ImportError as e:
        raise RuntimeError(...)

# After
def _initialize_default_engines(self) -> None:
    """Register default engines on first instantiation."""
    try:
        from src.compiler.langgraph_engine import LangGraphExecutionEngine
        self._engines["langgraph"] = LangGraphExecutionEngine
    except ImportError as e:
        raise RuntimeError(...)
```

**Why -> None:**
- Method has side effects (modifies _engines dict)
- Does not return a value
- Strict mode requires explicit None return type
- Documents void function behavior

### Pattern 3: Type Annotating **kwargs

Variable keyword arguments need type annotation in strict mode:

```python
# Before
def get_engine(
    self,
    name: str = "langgraph",
    **kwargs  # Error: missing type annotation
) -> ExecutionEngine:
    engine_class = self._engines[name]
    return engine_class(**kwargs)

# After
def get_engine(
    self,
    name: str = "langgraph",
    **kwargs: Any  # OK: kwargs values can be Any type
) -> ExecutionEngine:
    engine_class = self._engines[name]
    return engine_class(**kwargs)
```

**Why use Any for kwargs:**
- Different engines may accept different constructor parameters
- Provides maximum flexibility for engine implementations
- Type safety maintained at call sites
- Alternative would be generic TypedDict (overkill)

### Pattern 4: Factory Pattern Type Safety

Registry pattern with type safety:

```python
class EngineRegistry:
    """Singleton registry for execution engines."""

    _instance: Optional["EngineRegistry"] = None
    _engines: Dict[str, Type[ExecutionEngine]] = {}

    def __new__(cls) -> "EngineRegistry":
        """Ensure single instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_default_engines()
        return cls._instance

    def register_engine(
        self,
        name: str,
        engine_class: Type[ExecutionEngine]
    ) -> None:
        """Register new engine type."""
        if not issubclass(engine_class, ExecutionEngine):
            raise TypeError(...)
        self._engines[name] = engine_class

    def get_engine(
        self,
        name: str = "langgraph",
        **kwargs: Any
    ) -> ExecutionEngine:
        """Create engine instance."""
        engine_class = self._engines[name]
        return engine_class(**kwargs)
```

**Type safety achieved:**
- Singleton pattern with proper return type
- Engine classes stored as Type[ExecutionEngine]
- Runtime validation with issubclass
- Factory returns ExecutionEngine instances
- Flexible kwargs for different engine constructors

---

## Next Steps

### Phase 2: Remaining Compiler Files

**High Priority:**
- `src/compiler/langgraph_compiler.py` - 4 errors
- `src/compiler/executors/adaptive.py` - 4 errors
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

### Singleton Pattern Type Annotations

Singleton __new__ considerations:
- Returns class instance type
- Use quoted string for forward reference
- Type checker validates usage
- Maintains singleton guarantee at type level

### Factory Pattern with Generics

Factory pattern type safety:
- Store classes as Type[Interface]
- Validate with issubclass at runtime
- Return instances of Interface
- Enable compile-time checking of factory usage

### **kwargs Type Annotation

When to use Any for kwargs:
- Multiple possible parameter types
- Forwarding to different implementations
- Maximum flexibility needed
- Type safety at boundaries sufficient

---

## Related Documentation

- Task: m3.1-01 (Fix Type Safety Errors 174 → 0)
- Previous: changes/0045-fix-type-safety-part13.md
- Python __new__: https://docs.python.org/3/reference/datamodel.html#object.__new__
- Mypy Forward References: https://mypy.readthedocs.io/en/stable/kinds_of_types.html#class-name-forward-references

---

## Notes

- engine_registry.py now has zero direct type errors ✓
- First net reduction in error count in several parts (-6 errors, -2 files)
- Proper singleton pattern type annotations
- Factory pattern maintains type safety
- No behavioral changes - all fixes are type annotations only
- 19 files now have 0 type errors
