# Change 0135: Register Custom Pytest Marks

**Date:** 2026-01-28
**Type:** Configuration
**Priority:** P3 (Minor)

## Summary

Registered custom pytest marks (`slow`, `memory`, `benchmark`) in pyproject.toml to eliminate pytest warnings during test collection. This improves test suite clarity and follows pytest best practices.

## Problem

When running pytest, multiple warnings appeared:
```
PytestUnknownMarkWarning: Unknown pytest.mark.slow - is this a typo?
PytestUnknownMarkWarning: Unknown pytest.mark.memory - is this a typo?
```

These warnings occurred because custom marks were being used in tests but not registered in pytest configuration.

## Solution

Added `markers` configuration to `[tool.pytest.ini_options]` in pyproject.toml:

```toml
[tool.pytest.ini_options]
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "memory: marks tests that check for memory leaks",
    "benchmark: marks tests that measure performance",
]
```

## Benefits

1. **Eliminates Warnings**: Test collection now runs cleanly without warnings
2. **Better Documentation**: Mark descriptions explain their purpose
3. **Selective Test Running**: Users can now easily filter tests:
   ```bash
   # Skip slow tests
   pytest -m "not slow"

   # Run only memory tests
   pytest -m memory

   # Run only benchmarks
   pytest -m benchmark
   ```
4. **Follows Best Practices**: pytest recommends registering all custom marks

## Usage Examples

### Skip Slow Tests in CI

```bash
pytest -m "not slow" --maxfail=1
```

### Run Only Memory Leak Tests

```bash
pytest -m memory
```

### Run Performance Benchmarks

```bash
pytest -m benchmark --benchmark-only
```

### Combine Marks

```bash
# Run slow memory tests
pytest -m "slow and memory"

# Run tests that are NOT slow OR memory
pytest -m "not (slow or memory)"
```

## Files Changed

```
pyproject.toml  # Added markers configuration
```

## Testing

Before:
```bash
$ pytest --co -q 2>&1 | grep Warning | wc -l
12  # Multiple warnings
```

After:
```bash
$ pytest --co -q 2>&1 | grep Warning | wc -l
0  # No warnings
```

## Related

- `tests/test_memory_leaks.py` - Uses `@pytest.mark.memory` and `@pytest.mark.slow`
- `tests/test_benchmarks/test_performance.py` - Uses `@pytest.mark.benchmark`

## Impact

**Breaking:** None
**Migration:** None required
**Performance:** No impact (configuration only)
