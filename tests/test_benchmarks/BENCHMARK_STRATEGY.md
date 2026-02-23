# Performance Benchmark Suite - Test Strategy

## Overview

Comprehensive performance benchmark suite for Temper AI with 50+ benchmarks covering all critical execution paths, baseline storage, regression detection, and historical tracking.

## Goals

1. **Establish Performance Baselines**: Record baseline metrics for all critical paths
2. **Detect Regressions**: Alert on >10% performance degradation
3. **Track Historical Trends**: Monitor performance evolution over time
4. **Identify Bottlenecks**: Pinpoint slow operations and optimization opportunities
5. **Validate Optimizations**: Verify M3.3 async/batching improvements

## Target Metrics

### Primary Metrics

| Component | Metric | Target | P95 Target | Current |
|-----------|--------|--------|------------|---------|
| Workflow Compilation | Time (simple) | <1s | <1.5s | TBD |
| Workflow Compilation | Time (50 stages) | <5s | <7s | TBD |
| Agent Execution | Overhead | <100ms | <150ms | TBD |
| LLM Call | Latency (mock) | 50-200ms | <300ms | TBD |
| Tool Execution | Overhead | <50ms | <75ms | TBD |
| Database Query | Simple SELECT | <10ms | <15ms | TBD |
| Database Write | Single INSERT | <20ms | <30ms | TBD |
| Observability Buffer | Write throughput | >1000 ops/s | >500 ops/s | TBD |
| Parallel Executor | Speedup (3 agents) | 2-3x | >1.8x | ✓ 2.5x |
| Query Batching | Reduction | >90% | >85% | ✓ 98% |

### Memory Baselines

| Operation | Target | Alert Threshold |
|-----------|--------|-----------------|
| Agent Creation | <50MB | >75MB |
| Workflow Compilation | <100MB | >150MB |
| 100 Agent Executions | <200MB growth | >300MB growth |
| Tool Registry | <10MB | >20MB |

## Benchmark Categories

### 1. Compiler Performance (12 benchmarks)

**Focus**: Workflow compilation speed and scalability

- Simple workflow compilation (1 stage)
- Medium workflow compilation (10 stages)
- Large workflow compilation (50 stages)
- Complex workflow compilation (100 stages with parallelism)
- Sequential stage compilation
- Parallel stage compilation
- Adaptive stage compilation
- Config loading performance
- Schema validation performance
- State initialization performance
- Node builder performance
- Graph construction performance

**Targets**:
- Simple workflows: <1s
- 50-stage workflows: <5s
- 100-stage workflows: <15s

### 2. Database & Observability (10 benchmarks)

**Focus**: Database query throughput and observability overhead

- Simple SELECT query
- Complex JOIN query
- Batch INSERT performance
- ObservabilityBuffer write throughput
- ObservabilityBuffer flush latency
- WorkflowExecution query performance
- AgentExecution query performance
- ToolExecution query performance
- Query with complex filters
- Database connection pool performance

**Targets**:
- Simple queries: <10ms
- Complex queries: <50ms
- Buffer throughput: >1000 ops/sec
- Flush latency: <100ms

### 3. LLM Provider Performance (8 benchmarks)

**Focus**: LLM call latency and async speedup

- Ollama mock call latency (p50, p95, p99)
- OpenAI mock call latency
- Anthropic mock call latency
- vLLM mock call latency
- Async LLM speedup (3 parallel calls)
- Async LLM speedup (10 parallel calls)
- LLM cache hit latency
- LLM cache miss latency

**Targets**:
- Mock latency: 50-200ms
- Async speedup (3x): 2-3x
- Cache hit: <10ms
- Cache miss: 50-200ms (depends on provider)

### 4. Tool Execution (8 benchmarks)

**Focus**: Tool execution overhead and concurrency

- Tool registry lookup
- Calculator tool execution
- Web scraper tool execution
- File writer tool execution
- Tool executor overhead
- Concurrent tool execution (4 workers)
- Concurrent tool execution (10 workers)
- Tool execution with rollback

**Targets**:
- Registry lookup: <5ms
- Tool overhead: <50ms
- Concurrent throughput: >10 tools/sec

### 5. Agent Execution (8 benchmarks)

**Focus**: Agent execution overhead and memory usage

- StandardAgent execution overhead
- Agent with tool calls
- Agent prompt rendering
- Agent error handling
- Agent factory creation
- 100 sequential agent executions (memory leak detection)
- Concurrent agent execution (3 agents)
- Concurrent agent execution (10 agents)

**Targets**:
- Execution overhead: <100ms
- Prompt rendering: <20ms
- Factory creation: <50ms
- Memory growth: <2MB per 100 executions

### 6. Collaboration Strategies (6 benchmarks)

**Focus**: Multi-agent synthesis performance

- Consensus strategy synthesis (3 agents)
- Consensus strategy synthesis (10 agents)
- Debate strategy synthesis
- Merit-weighted synthesis
- Conflict resolution
- Quality gate validation

**Targets**:
- Synthesis (3 agents): <100ms
- Synthesis (10 agents): <500ms
- Quality gate: <50ms

### 7. Safety & Security (4 benchmarks)

**Focus**: Safety policy overhead

- Action policy validation
- Rate limiter overhead
- Circuit breaker overhead
- Rollback manager snapshot creation

**Targets**:
- Policy validation: <10ms
- Rate limiter: <5ms
- Circuit breaker: <5ms
- Snapshot: <100ms

### 8. End-to-End Workflows (6 benchmarks)

**Focus**: Complete workflow execution performance

- Simple M2 workflow (sequential)
- Medium M3 workflow (parallel, 3 agents)
- Complex M3 workflow (parallel, 10 agents)
- Adaptive workflow execution
- Workflow with checkpointing
- 10 concurrent workflows

**Targets**:
- Simple workflow: <2s
- Medium workflow: <5s
- Complex workflow: <15s
- Concurrent throughput: >2 workflows/sec

## Benchmark Test Structure

### Standard Test Pattern

```python
@pytest.mark.benchmark(group="category")
def test_operation_name(benchmark, fixtures):
    """Benchmark [operation] performance.

    Target: <Xms/s/ops
    Measures: [what is measured]
    """
    # Arrange
    setup_test_data()

    # Act & Benchmark
    result = benchmark(operation_to_test, *args)

    # Assert
    assert result is not None

    # Performance Expectations
    stats = benchmark.stats
    if stats['mean'] > TARGET_THRESHOLD:
        pytest.fail(f"Performance regression: {stats['mean']:.3f}s > {TARGET_THRESHOLD}s")

    # Log percentiles
    print(f"p50: {stats['median']:.3f}s, p95: {stats['percentile_95']:.3f}s")
```

### Memory Test Pattern

```python
@pytest.mark.benchmark(group="memory")
@pytest.mark.memory
def test_operation_memory_usage(benchmark):
    """Benchmark memory usage for [operation].

    Target: <XMB growth
    """
    import psutil
    import os

    process = psutil.Process(os.getpid())

    def measure_memory_growth():
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        # Perform operations
        for _ in range(100):
            operation()

        mem_after = process.memory_info().rss / 1024 / 1024  # MB
        return mem_after - mem_before

    growth_mb = benchmark(measure_memory_growth)

    assert growth_mb < TARGET_MB, f"Memory growth {growth_mb:.1f}MB exceeds target {TARGET_MB}MB"
```

## Fixtures

### Core Fixtures

```python
@pytest.fixture(scope="session")
def benchmark_db():
    """Session-scoped in-memory database for benchmarks."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    yield db
    # Cleanup handled by SQLite memory database

@pytest.fixture
def mock_llm_fast():
    """Mock LLM with 10ms latency."""
    return create_mock_llm(latency_ms=10)

@pytest.fixture
def mock_llm_realistic():
    """Mock LLM with 100ms latency."""
    return create_mock_llm(latency_ms=100)

@pytest.fixture
def simple_workflow_config():
    """1-stage workflow for benchmarks."""
    return create_workflow_config(stages=1)

@pytest.fixture
def medium_workflow_config():
    """10-stage workflow for benchmarks."""
    return create_workflow_config(stages=10)

@pytest.fixture
def large_workflow_config():
    """50-stage workflow for benchmarks."""
    return create_workflow_config(stages=50)

@pytest.fixture
def complex_workflow_config():
    """100-stage workflow with parallelism for benchmarks."""
    return create_workflow_config(stages=100, parallel=True)
```

## Running Benchmarks

### Basic Commands

```bash
# Run all benchmarks
pytest tests/test_benchmarks/ --benchmark-only

# Run specific category
pytest tests/test_benchmarks/test_performance_benchmarks.py::test_compiler* --benchmark-only

# Run with verbose output
pytest tests/test_benchmarks/ --benchmark-only -v

# Run with warmup rounds
pytest tests/test_benchmarks/ --benchmark-only --benchmark-warmup=on
```

### Baseline Management

```bash
# Save initial baseline (first time setup)
pytest tests/test_benchmarks/ --benchmark-only --benchmark-save=baseline

# Save named baseline (e.g., before optimization)
pytest tests/test_benchmarks/ --benchmark-only --benchmark-save=pre-async-optimization

# Compare against baseline
pytest tests/test_benchmarks/ --benchmark-only --benchmark-compare=baseline

# Fail on regression (>10% slower)
pytest tests/test_benchmarks/ --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:10%

# Fail on regression (>15% slower for p95)
pytest tests/test_benchmarks/ --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=percentile_95:15%
```

### Historical Tracking

```bash
# Auto-save with timestamp
pytest tests/test_benchmarks/ --benchmark-only --benchmark-autosave

# Generate histogram
pytest tests/test_benchmarks/ --benchmark-only --benchmark-histogram=benchmark_histogram

# Generate detailed JSON report
pytest tests/test_benchmarks/ --benchmark-only --benchmark-json=benchmark_results.json
```

### Memory Profiling

```bash
# Run memory benchmarks only
pytest tests/test_benchmarks/ -m memory --benchmark-only

# Profile with memray (detailed memory analysis)
pip install memray
memray run -m pytest tests/test_benchmarks/ --benchmark-only
memray flamegraph memray-*.bin

# Profile with memory_profiler (line-by-line)
pip install memory_profiler
python -m memory_profiler tests/test_benchmarks/test_performance_benchmarks.py
```

## CI/CD Integration

### GitHub Actions Workflow

```yaml
name: Performance Benchmarks

on:
  push:
    branches: [master, main]
  pull_request:
    branches: [master, main]

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
        run: |
          pip install -e ".[dev]"

      - name: Download baseline
        uses: actions/cache@v3
        with:
          path: .benchmarks
          key: benchmarks-${{ github.sha }}
          restore-keys: benchmarks-

      - name: Run benchmarks
        run: |
          pytest tests/test_benchmarks/ --benchmark-only \
            --benchmark-compare=baseline \
            --benchmark-compare-fail=mean:10% \
            --benchmark-json=benchmark_results.json

      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: benchmark-results
          path: benchmark_results.json

      - name: Comment PR with results
        if: github.event_name == 'pull_request'
        uses: benchmark-action/github-action-benchmark@v1
        with:
          tool: 'pytest'
          output-file-path: benchmark_results.json
          github-token: ${{ secrets.GITHUB_TOKEN }}
          comment-on-alert: true
          alert-threshold: '110%'  # 10% regression
```

### Pre-commit Hook (Optional)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: quick-benchmarks
        name: Quick performance benchmarks
        entry: pytest tests/test_benchmarks/test_performance_benchmarks.py::test_compiler_simple_workflow --benchmark-only
        language: system
        pass_filenames: false
        stages: [pre-push]  # Only on push, not every commit
```

## Regression Detection

### Automated Alerts

**Configuration in pytest.ini or pyproject.toml**:

```toml
[tool.pytest.ini_options]
benchmark_compare_fail = [
    "mean:10%",           # Fail if mean >10% slower
    "median:10%",         # Fail if median >10% slower
    "percentile_95:15%",  # Fail if p95 >15% slower
]
```

### Manual Review Process

1. **Run benchmarks**: `pytest --benchmark-only --benchmark-compare=baseline`
2. **Review report**: Check for RED entries (regressions)
3. **Investigate**: For regressions >10%, profile to find bottleneck
4. **Document**: Add findings to `.benchmarks/CHANGELOG.md`
5. **Update baseline**: After optimization, save new baseline

### Example Regression Report

```
------------------------------- benchmark: 8 tests -------------------------------
Name (time in ms)                    Mean      StdDev    Median      p95
------------------------------------------------------------------------------------
test_compiler_simple_workflow       850.2      15.3      848.1      875.2  (baseline: 800.1, +6.3%)  ✓
test_database_simple_query           8.5        0.5       8.4        9.2   (baseline: 7.9, +7.6%)    ✓
test_llm_call_latency              102.3       5.2      101.8      110.5   (baseline: 145.2, -29.5%) ✓✓
test_tool_execution                 45.2       2.1       45.0       48.3   (baseline: 38.5, +17.4%)  ✗ REGRESSION
------------------------------------------------------------------------------------

REGRESSIONS DETECTED:
- test_tool_execution: 45.2ms vs 38.5ms baseline (+17.4%, threshold: 10%)
  → Investigate tool executor thread pool overhead
```

## Performance Budgets

### Component Budgets

| Component | Budget | Alert at | Fail at |
|-----------|--------|----------|---------|
| Compiler (simple) | <1s | >900ms | >1.5s |
| Compiler (50-stage) | <5s | >4.5s | >7s |
| Agent execution | <100ms | >90ms | >150ms |
| Database query | <10ms | >9ms | >20ms |
| Tool execution | <50ms | >45ms | >100ms |

### Budget Tracking

```python
PERFORMANCE_BUDGETS = {
    "compiler_simple": {"target": 1.0, "alert": 0.9, "fail": 1.5},
    "compiler_large": {"target": 5.0, "alert": 4.5, "fail": 7.0},
    "agent_execution": {"target": 0.1, "alert": 0.09, "fail": 0.15},
    "database_query": {"target": 0.01, "alert": 0.009, "fail": 0.02},
    "tool_execution": {"target": 0.05, "alert": 0.045, "fail": 0.1},
}

def check_budget(test_name, result_seconds):
    budget = PERFORMANCE_BUDGETS.get(test_name)
    if not budget:
        return

    if result_seconds > budget["fail"]:
        pytest.fail(f"BUDGET EXCEEDED: {result_seconds:.3f}s > {budget['fail']}s")
    elif result_seconds > budget["alert"]:
        warnings.warn(f"APPROACHING BUDGET: {result_seconds:.3f}s > {budget['alert']}s")
```

## Benchmark Outputs

### Directory Structure

```
.benchmarks/
├── README.md                          # This file
├── CHANGELOG.md                       # Performance changelog
├── Linux-CPython-3.12-64bit/
│   ├── 0001_baseline.json            # Initial baseline
│   ├── 0002_pre_async_optimization.json
│   ├── 0003_post_async_optimization.json
│   ├── 0004_commit_abc123.json       # Auto-saved benchmarks
│   └── ...
├── histograms/
│   ├── compiler_benchmarks.svg
│   ├── database_benchmarks.svg
│   └── ...
└── reports/
    ├── 2026-01-31_benchmark_report.html
    └── ...
```

### Benchmark Changelog

Track significant performance changes:

```markdown
# Benchmark Changelog

## 2026-01-31 - Async LLM Optimization (M3.3-01)
- **Change**: Implemented async LLM providers
- **Impact**: 2.5x speedup for parallel agent execution (3 agents)
- **Benchmarks**:
  - `test_async_llm_speedup_verification`: 2.5x (was: sequential)
  - `test_concurrent_workflow_execution`: 0.35s (was: 1.2s, -70%)
- **Baseline**: Updated to `0003_post_async_optimization`

## 2026-01-30 - Query Batching (M3.3-02)
- **Change**: Implemented ObservabilityBuffer with batching
- **Impact**: 98% reduction in database queries
- **Benchmarks**:
  - `test_query_reduction_verification`: 98% reduction (was: N+1 pattern)
  - `test_database_write_throughput`: 1200 ops/s (was: 50 ops/s, +2300%)
- **Baseline**: Updated to `0002_post_batching`
```

## Best Practices

### 1. Benchmark Hygiene

- **Isolate benchmarks**: Use separate test file for benchmarks
- **Mock external dependencies**: Never call real APIs in benchmarks
- **Use consistent hardware**: Run on same machine/CI for comparability
- **Warmup**: Enable `--benchmark-warmup=on` for JIT-compiled code
- **Multiple rounds**: pytest-benchmark runs multiple iterations automatically

### 2. Avoiding False Positives

- **System load**: Run benchmarks on idle system
- **Background processes**: Close unnecessary applications
- **CPU frequency**: Disable CPU frequency scaling if possible
- **Thermals**: Ensure adequate cooling (thermal throttling affects results)
- **Variance tolerance**: Set reasonable thresholds (10-15% for mean)

### 3. Interpreting Results

- **Focus on median/p95**: Mean can be skewed by outliers
- **Check standard deviation**: High StdDev indicates inconsistent performance
- **Compare distributions**: Use `--benchmark-histogram` to visualize
- **Identify outliers**: p99 spikes may indicate GC pauses or I/O stalls

### 4. Optimization Workflow

1. **Measure first**: Run benchmarks to establish baseline
2. **Profile**: Use profilers (cProfile, memray) to find bottlenecks
3. **Optimize**: Make targeted changes
4. **Verify**: Re-run benchmarks to validate improvement
5. **Document**: Update changelog with findings

## Maintenance

### Regular Tasks

- **Weekly**: Review benchmark results on CI
- **Monthly**: Update baselines after confirmed optimizations
- **Quarterly**: Audit benchmarks for relevance (remove obsolete, add new)
- **Annually**: Archive old baselines, reset to current as new baseline

### Adding New Benchmarks

1. Identify performance-critical path
2. Write benchmark test following pattern above
3. Add to appropriate category/group
4. Document in this strategy doc
5. Run to establish initial baseline
6. Add to CI/CD pipeline

### Removing Benchmarks

1. Mark as deprecated with `@pytest.mark.skip(reason="Deprecated")`
2. Wait one release cycle
3. Remove from codebase
4. Document removal in changelog

## Tools & Resources

### Profiling Tools

- **cProfile**: Python built-in profiler
- **py-spy**: Sampling profiler (no code changes needed)
- **memray**: Advanced memory profiler
- **memory_profiler**: Line-by-line memory usage
- **psutil**: System resource monitoring

### Visualization

- **pytest-benchmark**: Built-in histogram generation
- **snakeviz**: Interactive cProfile visualization
- **gprof2dot**: Call graph visualization
- **flamegraph**: Flame graph for profiling data

### References

- pytest-benchmark docs: https://pytest-benchmark.readthedocs.io/
- Python profiling: https://docs.python.org/3/library/profile.html
- memray: https://bloomberg.github.io/memray/

## Summary

This benchmark suite provides:
- ✓ 50+ comprehensive performance tests
- ✓ Baseline storage and historical tracking
- ✓ Regression detection with 10% threshold
- ✓ CI/CD integration for automated testing
- ✓ Memory leak detection
- ✓ Performance budget enforcement
- ✓ Detailed reporting and visualization

**Next Steps**:
1. Implement remaining benchmarks (currently 11/50+ implemented)
2. Establish initial baselines for all tests
3. Integrate into CI/CD pipeline
4. Set up automated alerting
5. Document performance improvements over time
