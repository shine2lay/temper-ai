# Performance Benchmarks - Quick Start Guide

Quick reference for running and managing performance benchmarks.

## TL;DR - Most Common Commands

```bash
# Run all benchmarks
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only

# Save initial baseline (do this once)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline

# Check for regressions (use in CI/CD)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline --benchmark-compare-fail=mean:10%
```

## First Time Setup

### 1. Install Dependencies

```bash
pip install -e ".[dev]"
```

This installs:
- pytest-benchmark>=5.0
- psutil>=5.9 (for memory profiling)
- All other dev dependencies

### 2. Run Benchmarks to Establish Baseline

```bash
# Run all 62 benchmarks (takes ~5-10 minutes)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only

# Save as baseline for future comparisons
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline
```

Output will show something like:

```
----------------------- benchmark: 62 tests -----------------------
Name (time in ms)              Min       Max      Mean    StdDev
-------------------------------------------------------------------
test_compiler_simple          823.1     891.2    850.2     15.3
test_database_query             7.9       9.8      8.5      0.5
test_agent_execution           89.2     112.3     98.7      5.2
...
-------------------------------------------------------------------
Saved benchmark data to .benchmarks/Linux-CPython-3.12-64bit/0001_baseline.json
```

## Daily Development Workflow

### Before Making Changes

```bash
# Optional: Save named baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-save=before_my_feature
```

### After Making Changes

```bash
# Compare against baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline

# Or compare against named baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=before_my_feature
```

Look for RED entries (>10% slower):

```
Name (time in ms)              Mean      Baseline
-------------------------------------------------
test_compiler_simple          850.2      800.1 (+6.3%)  ✓
test_tool_execution           58.2       49.5 (+17.6%)  ✗ REGRESSION
```

### If Regression Detected

1. **Profile the slow test**:
   ```bash
   python -m cProfile -o profile.stats \
       tests/test_benchmarks/test_performance_benchmarks.py::test_tool_execution
   snakeviz profile.stats  # Visual profiler
   ```

2. **Investigate and fix**:
   - Check what changed
   - Optimize bottleneck
   - Re-run benchmark to verify

3. **Update baseline** (only if fix applied or regression accepted):
   ```bash
   pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
       --benchmark-save=baseline
   ```

## Running Specific Benchmark Categories

```bash
# Compiler benchmarks only (12 tests)
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "compiler" --benchmark-only

# Database benchmarks only (10 tests)
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "database" --benchmark-only

# LLM benchmarks only (8 tests)
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "llm" --benchmark-only

# Tool benchmarks only (8 tests)
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "tools" --benchmark-only

# Agent benchmarks only (8 tests)
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "agents" --benchmark-only

# Strategy benchmarks only (6 tests)
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "strategies" --benchmark-only

# Safety benchmarks only (4 tests)
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "safety" --benchmark-only

# E2E benchmarks only (6 tests)
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "e2e" --benchmark-only

# Memory benchmarks only
pytest tests/test_benchmarks/test_performance_benchmarks.py -m memory --benchmark-only
```

## Running Single Benchmark

```bash
# Run specific test
pytest tests/test_benchmarks/test_performance_benchmarks.py::test_compiler_simple_workflow --benchmark-only

# Compare specific test against baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py::test_compiler_simple_workflow \
    --benchmark-only --benchmark-compare=baseline
```

## Visualization

### Generate Histogram

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-histogram=benchmark_histogram

# Output: benchmark_histogram.svg
```

### Export JSON for Analysis

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-json=results.json

# Use with Python, Jupyter, or BI tools
python -c "import json; print(json.load(open('results.json'))['benchmarks'][0])"
```

## CI/CD Integration

### Pre-commit (Optional)

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: quick-benchmarks
        name: Quick performance check
        entry: pytest tests/test_benchmarks/test_performance_benchmarks.py::test_compiler_simple_workflow --benchmark-only
        language: system
        pass_filenames: false
        stages: [pre-push]
```

### GitHub Actions

Add to `.github/workflows/benchmarks.yml`:

```yaml
name: Performance Benchmarks

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Download baseline
        uses: actions/cache@v3
        with:
          path: .benchmarks
          key: benchmarks-${{ runner.os }}
          restore-keys: benchmarks-

      - name: Run benchmarks
        run: |
          pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
            --benchmark-compare=baseline \
            --benchmark-compare-fail=mean:10%

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: benchmark-results
          path: .benchmarks/
```

## Advanced Options

### Control Benchmark Precision

```bash
# More rounds for higher precision (slower)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-min-rounds=10

# Less time per benchmark (faster, less precise)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-max-time=0.5
```

### Disable Warmup (for faster runs)

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-warmup=off
```

### Auto-save with Timestamp

```bash
# Automatically save results with timestamp
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-autosave
```

### Fail on Different Thresholds

```bash
# Fail if mean >5% slower (stricter)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:5%

# Fail if p95 >15% slower
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=percentile_95:15%

# Fail on multiple metrics
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:10% \
    --benchmark-compare-fail=median:10%
```

## Memory Profiling

### Basic Memory Benchmarks

```bash
# Run memory-specific benchmarks
pytest tests/test_benchmarks/test_performance_benchmarks.py -m memory --benchmark-only
```

### Advanced Memory Profiling with memray

```bash
# Install memray
pip install memray

# Profile benchmarks
memray run -m pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only

# Generate flame graph
memray flamegraph memray-*.bin

# Open in browser
open memray-flamegraph-*.html
```

## Troubleshooting

### Benchmarks Too Slow

```bash
# Skip slow tests
pytest tests/test_benchmarks/test_performance_benchmarks.py -m "not slow" --benchmark-only

# Or run fast categories only
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "database or tools" --benchmark-only
```

### Inconsistent Results

```bash
# Close background apps
# Disable CPU frequency scaling (Linux):
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Run with more rounds for stability
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-min-rounds=20
```

### Baseline Missing

```bash
# Create new baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-save=baseline
```

## Performance Budget Reference

Quick reference for performance targets:

| Component | Target | Alert | Fail |
|-----------|--------|-------|------|
| Workflow compilation (simple) | <1s | >900ms | >1.5s |
| Workflow compilation (50 stages) | <5s | >4.5s | >7s |
| Agent execution | <100ms | >90ms | >150ms |
| Tool execution | <50ms | >45ms | >100ms |
| Database query | <10ms | >9ms | >20ms |
| LLM cache hit | <10ms | - | - |

Memory budgets:

| Operation | Target | Fail |
|-----------|--------|------|
| Agent creation | <50MB | >75MB |
| Workflow compilation | <100MB | >150MB |
| 100 agent executions | <200MB growth | >300MB growth |

## Getting Help

- **Full documentation**: See `BENCHMARK_STRATEGY.md`
- **Baseline management**: See `.benchmarks/README.md`
- **Performance changelog**: See `.benchmarks/CHANGELOG.md`
- **pytest-benchmark docs**: https://pytest-benchmark.readthedocs.io/

## Cheat Sheet

```bash
# Most common commands
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only                    # Run all
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline  # Save baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-compare=baseline  # Compare
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "compiler" --benchmark-only    # Run category
pytest tests/test_benchmarks/test_performance_benchmarks.py::test_name --benchmark-only       # Run one test

# Regression detection (CI/CD)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline --benchmark-compare-fail=mean:10%

# Visualization
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-histogram=hist
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-json=results.json

# Memory profiling
pytest tests/test_benchmarks/test_performance_benchmarks.py -m memory --benchmark-only
memray run -m pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only
```

---

**Happy benchmarking!** Remember: measure first, optimize second, verify always.
