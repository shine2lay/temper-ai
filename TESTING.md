# Testing Guide

## Quick Start

```bash
# Activate virtual environment
source venv/bin/activate

# Run tests in parallel (recommended - 2.5x faster)
python -m pytest tests/test_compiler/ tests/test_agents/ tests/test_safety/ -n auto

# Run tests sequentially (if needed)
python -m pytest tests/test_compiler/ tests/test_agents/ tests/test_safety/
```

## Performance

| Mode | Time | Speedup | Command |
|------|------|---------|---------|
| Sequential | ~37s | 1.0x | `pytest tests/...` |
| Parallel (8 workers) | ~19s | 1.9x | `pytest tests/... -n 8` |
| **Parallel (auto/20 workers)** | **~13s** | **2.8x** | `pytest tests/... -n auto` ⚡ |

**Recommendation**: Always use `-n auto` for development to maximize speed.

## Test Organization

### Core Test Suites
- `tests/test_compiler/` - Workflow compilation and execution (803 tests)
- `tests/test_agents/` - Agent behavior and LLM integration (1,006 tests)
- `tests/test_safety/` - Safety policies and validation (408 tests)

**Total**: ~2,217 passing tests

### Excluded from Standard Runs
- `tests/property/` - Property-based tests (require hypothesis)
- `tests/self_improvement/` - Self-improvement system tests
- `tests/benchmarks/` - Performance benchmarks
- `tests/test_benchmarks/` - Benchmark validation

### Skipped Tests (Expected)
- 14 distributed rate limiting tests (require Redis)
- 5 Redis checkpoint backend tests (require Redis)
- 2 Windows-specific path tests (Linux only)
- 2 serial-only tests (skipped in parallel mode)

## Parallel Testing

### How It Works
- Uses `pytest-xdist` to distribute tests across multiple CPU cores
- Each worker runs in a separate process for true parallelism
- Tests are automatically distributed for optimal load balancing

### Worker Configuration
```bash
# Auto-detect CPU cores (recommended)
pytest -n auto

# Specific number of workers
pytest -n 4    # Use 4 workers
pytest -n 8    # Use 8 workers

# Sequential (no parallelization)
pytest         # Single process
```

### Serial-Only Tests
Some tests modify global state and must run serially:
- `test_no_recursion_with_high_max_retries` - Modifies `sys.setrecursionlimit()`
- `test_benchmark_large_input` - Performance timing sensitive

These tests use the `worker_id` fixture to skip in parallel workers.

## Common Commands

```bash
# Run all core tests in parallel
pytest tests/test_compiler/ tests/test_agents/ tests/test_safety/ -n auto

# Run specific test file
pytest tests/test_agents/test_standard_agent.py -n auto

# Run specific test
pytest tests/test_agents/test_standard_agent.py::TestStandardAgent::test_execute -v

# Run with coverage
pytest tests/ -n auto --cov=src --cov-report=html

# Run with verbose output
pytest tests/ -n auto -v

# Run failed tests only
pytest tests/ -n auto --lf

# Stop on first failure
pytest tests/ -n auto -x
```

## Debugging

```bash
# Run sequentially with full output (for debugging)
pytest tests/test_agents/test_standard_agent.py -xvs

# Show print statements
pytest tests/test_agents/ -n auto -s

# Show slowest tests
pytest tests/ -n auto --durations=10
```

## CI/CD Integration

For CI environments, use parallel testing to reduce pipeline time:

```yaml
# GitHub Actions example
- name: Run tests
  run: |
    source venv/bin/activate
    pytest tests/test_compiler/ tests/test_agents/ tests/test_safety/ -n auto --tb=short
```

## Requirements

Required packages (already in `pyproject.toml`):
- `pytest>=7.4`
- `pytest-asyncio>=0.21`
- `pytest-xdist>=3.0` - For parallel execution
- `pytest-timeout>=2.4` - Timeout protection

Optional:
- `pytest-cov>=4.1` - Code coverage
- `pytest-benchmark>=5.0` - Performance benchmarking

## Troubleshooting

### "pytest: command not found"
```bash
source venv/bin/activate
```

### Tests failing in parallel but passing sequentially
- Check for global state modifications (sys settings, environment variables)
- Use `worker_id` fixture to skip tests in parallel mode
- Consider using `@pytest.mark.xfail` for flaky tests

### Slow test execution
```bash
# Check slowest tests
pytest tests/ -n auto --durations=20

# Profile test execution
pytest tests/ -n auto --profile
```

## Test Results

Current status (as of 2026-02-07):
- ✅ 2,217 passed
- ⏭️ 24 skipped (22 environment-dependent + 2 serial-only)
- ⚠️ 2 xfailed (known test isolation issues)
- ❌ 0 failures

All critical functionality is tested and working!
