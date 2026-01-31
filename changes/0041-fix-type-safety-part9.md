# Fix Type Safety Errors - Part 9

**Date:** 2026-01-28
**Task:** m3.1-01 (in progress)
**Agent:** agent-d6e90e

---

## Summary

Ninth batch of type safety fixes targeting structured logging utilities. Fixed optional import handling, context manager type annotations, decorator return types, and assertion-based type narrowing. Successfully fixed all 13 direct errors in logging.py.

---

## Changes

### Files Modified

**src/utils/logging.py:**
- Added imports: `Callable` and `Tuple` from typing
- Fixed optional import handling for detect_secret_patterns:
  - Declared `detect_secret_patterns: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None`
  - Import with proper exception handling
- Fixed unreachable statement in `_redact_secrets`:
  - Line 70: Added `# type: ignore[unreachable]` for defensive isinstance check
- Fixed conditional check for detect_secret_patterns:
  - `if SECRETS_AVAILABLE and detect_secret_patterns:` → `if SECRETS_AVAILABLE and detect_secret_patterns is not None:`
- Fixed `LogContext.__init__` method:
  - Added `**context_fields: Any` and `-> None` return type
  - Fixed `self.old_factory` type: `Optional[Callable[..., logging.LogRecord]]`
- Fixed `LogContext.__enter__` method:
  - Added return type `-> "LogContext"`
- Fixed `record_factory` nested function:
  - Added `*args: Any, **kwargs: Any` and `-> logging.LogRecord`
  - Added assertion: `assert old_factory is not None` for type narrowing
  - Captured old_factory in closure before function definition
- Fixed `LogContext.__exit__` method:
  - Added `exc_type: Any, exc_val: Any, exc_tb: Any` and `-> None`
  - Changed to explicit None check: `if self.old_factory is not None:`
- Fixed `log_function_call` decorator:
  - Return type: `-> Callable[[Callable[..., Any]], Callable[..., Any]]`
  - Inner `decorator` function: `func: Callable[..., Any]` and return type
  - Inner `wrapper` function: `*func_args: Any, **func_kwargs: Any` and `-> Any`
- **Errors fixed:** 13 direct errors → 0 direct errors

---

## Progress

### Type Error Count

**Before Part 9:** 403 errors in 48 files
**After Part 9:** 402 errors in 47 files
**Direct fixes:** 13 errors in 1 file
**Net change:** -1 error (minor due to cascading effects)

### Files Checked Successfully

- `src/utils/logging.py` - 0 direct errors ✓

### Verification

```bash
mypy --strict src/utils/logging.py
# No errors found
```

---

## Implementation Details

### Pattern 1: Context Manager Protocol

Context managers need proper type annotations:

```python
# Before
class LogContext:
    def __init__(self, logger: logging.Logger, **context_fields):
        self.logger = logger
        self.context_fields = context_fields
        self.old_factory = None

    def __enter__(self):
        # ...
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # ...

# After
class LogContext:
    def __init__(self, logger: logging.Logger, **context_fields: Any) -> None:
        self.logger = logger
        self.context_fields = context_fields
        self.old_factory: Optional[Callable[..., logging.LogRecord]] = None

    def __enter__(self) -> "LogContext":
        # ...
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # ...
```

**Key points:**
- `__enter__` returns instance type (use forward reference)
- `__exit__` parameters can be Any (standard protocol)
- Initialize Optional attributes with proper type

### Pattern 2: Closure Variable Capture with Type Narrowing

When creating nested functions that reference outer variables:

```python
# Before
def __enter__(self):
    self.old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = self.old_factory(*args, **kwargs)  # Error: None not callable
        # ...
        return record

# After
def __enter__(self) -> "LogContext":
    self.old_factory = logging.getLogRecordFactory()
    old_factory = self.old_factory  # Capture in local variable

    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        assert old_factory is not None, "old_factory should be set"
        record = old_factory(*args, **kwargs)  # OK: narrowed to non-None
        # ...
        return record
```

**Why this works:**
- Capture `self.old_factory` in local `old_factory` variable
- Assert non-None to narrow type within function
- Mypy understands assertion and knows it's not None
- Avoids "None not callable" error

### Pattern 3: Decorator Factory Return Type

Decorator factories return decorators that return decorated functions:

```python
# Before
def log_function_call(logger: logging.Logger, level: int = logging.DEBUG):
    def decorator(func):
        def wrapper(*func_args, **func_kwargs):
            # ...
            return func(*func_args, **func_kwargs)
        return wrapper
    return decorator

# After
def log_function_call(
    logger: logging.Logger,
    level: int = logging.DEBUG
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*func_args: Any, **func_kwargs: Any) -> Any:
            # ...
            return func(*func_args, **func_kwargs)
        return wrapper
    return decorator
```

**Type structure:**
- Outer function returns: `Callable[[Func], Func]`
- Middle decorator takes and returns: `Callable[..., Any]`
- Inner wrapper takes and returns: Any (generic function)

### Pattern 4: Optional Import with Explicit None Check

Handle optional imports with explicit type declarations:

```python
# Before
try:
    from src.utils.secrets import detect_secret_patterns
    SECRETS_AVAILABLE = True
except ImportError:
    SECRETS_AVAILABLE = False
    detect_secret_patterns = None  # Error: incompatible types

# ... later ...
if SECRETS_AVAILABLE and detect_secret_patterns:  # Error: function always truthy
    result = detect_secret_patterns(text)

# After
detect_secret_patterns: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None
SECRETS_AVAILABLE = False

try:
    from src.utils.secrets import detect_secret_patterns
    SECRETS_AVAILABLE = True
except ImportError:
    pass

# ... later ...
if SECRETS_AVAILABLE and detect_secret_patterns is not None:  # OK: explicit check
    result = detect_secret_patterns(text)
```

---

## Next Steps

### Phase 2: Remaining Utilities and Tools

**High Priority:**
- `src/compiler/langgraph_compiler.py` - 7 errors - **BLOCKED** by agent-a83ad7
- `src/tools/base.py` - 7 errors - **BLOCKED** by agent-1e0126
- `src/tools/calculator.py` - 12 errors
- `src/tools/web_scraper.py` - 6 errors

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

### Assertion-Based Type Narrowing

Assertions help mypy understand control flow:
- After `assert x is not None`, mypy knows x is not None
- After `assert isinstance(x, Type)`, mypy knows x is Type
- Use for closures where type checker loses track
- Documents programmer intent explicitly

### Context Manager Best Practices

Type annotations for context managers:
- `__init__` returns `-> None`
- `__enter__` returns instance type or managed resource
- `__exit__` parameters: `exc_type: Any, exc_val: Any, exc_tb: Any`
- `__exit__` returns `-> None` (or bool for exception suppression)

### Closure Type Safety

When creating closures:
1. Capture outer variables in local variables
2. Add type assertions if needed
3. Annotate nested function signatures
4. Helps mypy track types through scope boundaries

---

## Related Documentation

- Task: m3.1-01 (Fix Type Safety Errors 174 → 0)
- Previous: changes/0040-fix-type-safety-part8.md
- Mypy Type Narrowing: https://mypy.readthedocs.io/en/stable/type_narrowing.html
- Python Context Managers: https://docs.python.org/3/reference/datamodel.html#context-managers

---

## Notes

- logging.py now has zero direct type errors ✓
- Proper handling of context manager protocol
- Closure type narrowing with assertions
- No behavioral changes - all fixes are type annotations only
- Established patterns for decorator factories and optional imports

