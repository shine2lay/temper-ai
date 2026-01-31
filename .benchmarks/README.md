# Performance Benchmarks - Baseline Storage

This directory stores performance benchmark baselines and historical data for regression detection and performance tracking.

## Directory Structure

```
.benchmarks/
├── README.md                          # This file
├── CHANGELOG.md                       # Performance changelog (track improvements/regressions)
├── Linux-CPython-3.12-64bit/          # Platform-specific benchmarks
│   ├── 0001_baseline.json            # Initial baseline
│   ├── 0002_<name>.json              # Named baselines (e.g., pre_optimization)
│   └── 0003_<commit>.json            # Auto-saved baselines
├── histograms/                        # Generated histogram visualizations
│   ├── compiler_benchmarks.svg
│   ├── database_benchmarks.svg
│   └── ...
└── reports/                           # HTML reports
    └── YYYY-MM-DD_benchmark_report.html
```

## Baseline Management

### Creating Initial Baseline

Run once when setting up benchmarks:

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline
```

This creates `.benchmarks/Linux-CPython-3.12-64bit/0001_baseline.json`

### Named Baselines

Create named baselines before major changes:

```bash
# Before optimization
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-save=pre_async_optimization

# After optimization
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-save=post_async_optimization
```

### Auto-saved Baselines

Enable auto-save to track performance over time:

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-autosave
```

This creates timestamped baselines automatically.

## Comparing Baselines

### Compare Against Baseline

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline
```

Output shows performance delta:

```
--------------------------------- benchmark: 12 tests ---------------------------------
Name (time in ms)                  Mean      StdDev    Median      Baseline
---------------------------------------------------------------------------------------
test_compiler_simple_workflow     850.2      15.3      848.1      800.1 (+6.3%)  ✓
test_database_simple_query         8.5        0.5       8.4        7.9  (+7.6%)  ✓
test_llm_call_latency            102.3       5.2      101.8      145.2 (-29.5%) ✓✓
test_tool_execution               45.2       2.1       45.0       38.5 (+17.4%)  ✗
---------------------------------------------------------------------------------------
Legend:
  ✓   = Performance within acceptable range (<10% change)
  ✓✓  = Performance improved significantly
  ✗   = Performance regression detected (>10% slower)
```

### Fail on Regression

Automatically fail CI/CD on performance regression:

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:10%
```

This fails the test suite if any benchmark is >10% slower than baseline.

### Advanced Comparison

Compare multiple metrics:

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:10% \
    --benchmark-compare-fail=median:10% \
    --benchmark-compare-fail=percentile_95:15%
```

## Regression Detection

### Automatic Alerts

Regressions are automatically detected when:

1. **Mean time increases >10%**: Overall performance degradation
2. **P95 increases >15%**: Tail latency degradation
3. **Standard deviation increases >50%**: Inconsistent performance

### Manual Review Process

When regression is detected:

1. **Identify bottleneck**: Run profiler on regressed test
   ```bash
   python -m cProfile -o profile.stats tests/test_benchmarks/test_performance_benchmarks.py::test_name
   snakeviz profile.stats
   ```

2. **Compare distributions**: Generate histogram
   ```bash
   pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
       --benchmark-histogram=regression_analysis
   ```

3. **Document findings**: Update CHANGELOG.md with root cause

4. **Fix or accept**: Either optimize code or update baseline if acceptable

## Visualization

### Histogram Generation

Generate visual comparison:

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-histogram=benchmark_histogram
```

Creates `benchmark_histogram.svg` showing distribution of benchmark results.

### JSON Export

Export detailed results for custom analysis:

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-json=benchmark_results.json
```

Use with visualization tools:
- Grafana for time-series tracking
- Jupyter notebooks for custom analysis
- CI/CD dashboards for trend visualization

## Performance Budgets

Benchmarks enforce performance budgets defined in `test_performance_benchmarks.py`:

```python
PERFORMANCE_BUDGETS = {
    "compiler_simple": {"target": 1.0, "alert": 0.9, "fail": 1.5},
    "agent_execution": {"target": 0.1, "alert": 0.09, "fail": 0.15},
    "database_simple_query": {"target": 0.01, "alert": 0.009, "fail": 0.02},
    ...
}
```

- **Target**: Desired performance goal
- **Alert**: Warning threshold (prints warning)
- **Fail**: Hard limit (fails test)

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Performance Benchmarks

on:
  push:
    branches: [main, master]
  pull_request:
    types: [opened, synchronize]

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Download baseline
        uses: actions/cache@v3
        with:
          path: .benchmarks
          key: benchmarks-${{ runner.os }}-${{ github.sha }}
          restore-keys: benchmarks-${{ runner.os }}-

      - name: Run benchmarks
        run: |
          pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
            --benchmark-compare=baseline \
            --benchmark-compare-fail=mean:10% \
            --benchmark-json=benchmark_results.json

      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: benchmark-results
          path: benchmark_results.json

      - name: Comment PR
        if: github.event_name == 'pull_request'
        uses: benchmark-action/github-action-benchmark@v1
        with:
          tool: 'pytest'
          output-file-path: benchmark_results.json
          github-token: ${{ secrets.GITHUB_TOKEN }}
          comment-on-alert: true
          alert-threshold: '110%'
```

## Historical Tracking

### Tracking Performance Over Time

1. **Auto-save on each commit**:
   ```bash
   pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
       --benchmark-autosave
   ```

2. **Extract time-series data**:
   ```python
   import json
   import glob

   baselines = glob.glob('.benchmarks/*/0*.json')
   for baseline in sorted(baselines):
       with open(baseline) as f:
           data = json.load(f)
           # Extract metrics for plotting
   ```

3. **Visualize trends**: Use Grafana, Plotly, or matplotlib

### Performance Changelog

Document significant changes in `CHANGELOG.md`:

```markdown
## 2026-01-31 - Async LLM Optimization (M3.3-01)
- **Change**: Implemented async LLM providers
- **Impact**: 2.5x speedup for parallel execution
- **Benchmarks**:
  - test_llm_async_speedup_3_calls: 2.5x (was: 1.0x)
  - test_e2e_medium_m3_workflow_parallel: 2.1s (was: 5.3s, -60%)
- **Baseline**: Updated to post_async_optimization
```

## Maintenance

### Weekly Tasks
- Review CI/CD benchmark results
- Investigate any regressions >5%
- Update CHANGELOG.md with findings

### Monthly Tasks
- Update baselines after confirmed optimizations
- Archive old baselines (keep last 12 months)
- Review and adjust performance budgets

### Quarterly Tasks
- Audit benchmark suite for relevance
- Remove obsolete benchmarks
- Add benchmarks for new features

## Troubleshooting

### Inconsistent Results

**Problem**: Benchmarks vary significantly between runs

**Solutions**:
1. Ensure idle system (close background apps)
2. Disable CPU frequency scaling:
   ```bash
   echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
   ```
3. Use `--benchmark-warmup=on` for JIT warmup
4. Increase `--benchmark-min-rounds=10`

### False Regressions

**Problem**: Benchmark fails regression check but code hasn't changed

**Solutions**:
1. Check system load during benchmark
2. Verify baseline is from same hardware/OS
3. Re-run multiple times to confirm:
   ```bash
   for i in {1..5}; do
       pytest tests/test_benchmarks/test_performance_benchmarks.py::test_name --benchmark-only
   done
   ```
4. Update baseline if system configuration changed

### Missing Baseline

**Problem**: `--benchmark-compare=baseline` fails with "baseline not found"

**Solutions**:
1. Create initial baseline:
   ```bash
   pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline
   ```
2. Check platform directory exists: `.benchmarks/Linux-CPython-3.12-64bit/`
3. Verify baseline file: `0001_baseline.json`

## Resources

- **pytest-benchmark docs**: https://pytest-benchmark.readthedocs.io/
- **Performance profiling**: https://docs.python.org/3/library/profile.html
- **Memory profiling**: https://bloomberg.github.io/memray/
- **Benchmark visualization**: https://github.com/benchmark-action/github-action-benchmark

## New Benchmark Categories (Added 2026-01-31)

### Category 9: Cache Performance (6 benchmarks)
- LLM response cache hit rate (>95% target)
- Redis vs in-memory cache latency (<1ms vs <10ms)
- LRU cache eviction performance (<5ms for 1000 items)
- Concurrent access contention (<20ms P95)
- Serialization overhead (<2ms for 10KB)
- Cache invalidation propagation (<50ms)

### Category 10: Network I/O Performance (4 benchmarks)
- HTTP connection pooling (<10ms per request)
- Request batching (5-10x speedup target)
- Timeout handling overhead (<5ms)
- Retry backoff overhead (<50ms for 3 attempts)

## CI/CD Integration

### GitHub Actions Workflow

An example workflow is provided in `.github/workflows/benchmarks.yml.example`:

**Features:**
- ✓ Runs on push to main/master/develop
- ✓ Runs on all pull requests
- ✓ Daily scheduled runs at 2 AM UTC
- ✓ Compares against baseline with 10% threshold
- ✓ Tracks mean, median, and percentile regressions
- ✓ Comments on PRs with results
- ✓ Fails CI if regression >10%
- ✓ Updates baseline on main branch
- ✓ Uploads artifacts for historical tracking

**To enable:**
1. Rename `.github/workflows/benchmarks.yml.example` to `.github/workflows/benchmarks.yml`
2. Run initial baseline: `pytest --benchmark-only --benchmark-save=baseline`
3. Commit and push `.benchmarks/` directory
4. PR checks will now include benchmark regression detection

### Enhanced Comparison

Multiple regression thresholds are now enforced:

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py \
    --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:10% \
    --benchmark-compare-fail=median:10% \
    --benchmark-compare-fail=stddev:50%
```

This catches:
- Mean regression (>10% slower overall)
- Median regression (>10% slower typical case)
- StdDev regression (>50% more variance)

## Summary

This directory tracks performance baselines and historical data for:
- ✓ 72 comprehensive performance benchmarks (expanded from 62)
- ✓ Regression detection with multiple thresholds (mean, median, stddev)
- ✓ Historical trend analysis
- ✓ CI/CD integration with GitHub Actions
- ✓ Performance budget enforcement
- ✓ Visual comparison and reporting
- ✓ Cache performance benchmarks (6 new tests)
- ✓ Network I/O benchmarks (4 new tests)

**Next Steps**:
1. Run initial baseline: `pytest --benchmark-only --benchmark-save=baseline`
2. Enable auto-save for historical tracking
3. Enable CI/CD: Rename `.github/workflows/benchmarks.yml.example`
4. Set up visualization dashboard (Grafana/Plotly)
