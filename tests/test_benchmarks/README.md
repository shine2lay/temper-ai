# Performance Benchmark Suite

Comprehensive performance benchmarks for meta-autonomous-framework with 62 tests covering all critical execution paths, baseline storage, regression detection (>10%), and historical tracking.

## Overview

This benchmark suite provides:

- ✅ **62 comprehensive benchmarks** across 8 categories
- ✅ **Baseline storage** with historical tracking in `.benchmarks/`
- ✅ **Regression detection** with 10% threshold for CI/CD
- ✅ **Memory profiling** for leak detection
- ✅ **Performance budgets** with alert thresholds
- ✅ **Visualization** with histograms and JSON export
- ✅ **CI/CD integration** ready for GitHub Actions

## Quick Start

### 1. Install Dependencies

```bash
pip install -e ".[dev]"
```

### 2. Run Benchmarks

```bash
# Run all 62 benchmarks
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only

# Save initial baseline (first time only)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline

# Compare against baseline (detect regressions)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-compare=baseline
```

### 3. Check Results

Output shows performance metrics:

```
----------------------- benchmark: 62 tests -----------------------
Name (time in ms)              Min       Max      Mean    StdDev
-------------------------------------------------------------------
test_compiler_simple          823.1     891.2    850.2     15.3
test_database_query             7.9       9.8      8.5      0.5
test_agent_execution           89.2     112.3     98.7      5.2
test_tool_execution            42.1      52.8     45.2      2.1
...
-------------------------------------------------------------------
```

## Benchmark Categories

### 1. Compiler Performance (12 tests)

Tests workflow compilation speed and scalability:

- Simple workflow (1 stage): Target <1s
- Medium workflow (10 stages): Target <3s
- Large workflow (50 stages): Target <5s
- Complex workflow (100 stages): Target <15s
- Config loading, schema validation, state initialization
- Sequential, parallel, and adaptive stage compilation

**Key Tests**:
- `test_compiler_simple_workflow`
- `test_compiler_large_workflow`
- `test_compiler_graph_construction`

### 2. Database & Observability (10 tests)

Tests database query throughput and observability overhead:

- Simple SELECT: Target <10ms
- Complex JOIN: Target <50ms
- Batch INSERT: Target <100ms for 100 records
- ObservabilityBuffer throughput: Target >1000 ops/sec
- Flush latency: Target <100ms

**Key Tests**:
- `test_database_simple_query`
- `test_observability_buffer_write`
- `test_database_transaction_isolation`

### 3. LLM Provider Performance (8 tests)

Tests LLM call latency and async speedup:

- Mock LLM latency: 50-200ms
- Async speedup (3 parallel calls): Target 2-3x
- Async speedup (10 parallel calls): Target 5-8x
- LLM cache hit: Target <10ms
- Provider creation: Target <50ms

**Key Tests**:
- `test_llm_async_speedup_3_calls`
- `test_llm_cache_hit`
- `test_llm_provider_creation`

### 4. Tool Execution (8 tests)

Tests tool execution overhead and concurrency:

- Tool registry lookup: Target <5ms
- Calculator execution: Target <50ms
- Executor overhead: Target <50ms
- Concurrent execution (4 workers): Target <200ms for 10 tools
- Error handling: Target <20ms

**Key Tests**:
- `test_tool_registry_lookup`
- `test_tool_calculator_execution`
- `test_tool_concurrent_execution_4_workers`

### 5. Agent Execution (8 tests)

Tests agent execution overhead and memory:

- Agent execution overhead: Target <100ms
- Agent with tools: Target <150ms
- Prompt rendering: Target <20ms
- Factory creation: Target <50ms
- Memory growth (100 executions): Target <200MB

**Key Tests**:
- `test_agent_execution_overhead`
- `test_agent_memory_usage_100_executions`
- `test_agent_concurrent_execution_3_agents`

### 6. Collaboration Strategies (6 tests)

Tests multi-agent synthesis performance:

- Consensus (3 agents): Target <100ms
- Consensus (10 agents): Target <500ms
- Debate strategy: Target <200ms
- Merit-weighted: Target <150ms
- Conflict resolution: Target <100ms

**Key Tests**:
- `test_strategy_consensus_3_agents`
- `test_strategy_debate`
- `test_strategy_quality_gate_validation`

### 7. Safety & Security (4 tests)

Tests safety policy overhead:

- Action policy validation: Target <10ms
- Rate limiter: Target <5ms
- Circuit breaker: Target <5ms
- Rollback snapshot: Target <100ms

**Key Tests**:
- `test_safety_action_policy_validation`
- `test_safety_rollback_snapshot`

### 8. End-to-End Workflows (6 tests)

Tests complete workflow execution:

- Simple M2 workflow: Target <2s
- Medium M3 workflow (parallel): Target <5s
- Workflow with checkpointing: Target <3s
- Concurrent throughput: Target >2 workflows/sec
- Memory baseline: Target <100MB

**Key Tests**:
- `test_e2e_simple_m2_workflow`
- `test_e2e_medium_m3_workflow_parallel`
- `test_e2e_concurrent_workflows_throughput`

## Performance Targets

### Primary Metrics

| Component | Target | P95 Target | Budget Fail |
|-----------|--------|------------|-------------|
| Workflow Compilation (simple) | <1s | <1.5s | >1.5s |
| Workflow Compilation (50 stages) | <5s | <7s | >7s |
| Agent Execution | <100ms | <150ms | >150ms |
| Tool Execution | <50ms | <75ms | >100ms |
| Database Query | <10ms | <15ms | >20ms |
| LLM Async Speedup (3x) | 2-3x | >1.8x | <1.8x |

### Memory Targets

| Operation | Target | Alert | Fail |
|-----------|--------|-------|------|
| Agent Creation | <50MB | >65MB | >75MB |
| Workflow Compilation | <100MB | >130MB | >150MB |
| 100 Agent Executions | <200MB growth | >260MB | >300MB |

## Usage

### Running Benchmarks

```bash
# All benchmarks (62 tests, ~5-10 minutes)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only

# Specific category
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "compiler" --benchmark-only
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "database" --benchmark-only
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "agents" --benchmark-only

# Single test
pytest tests/test_benchmarks/test_performance_benchmarks.py::test_compiler_simple_workflow --benchmark-only

# Memory tests only
pytest tests/test_benchmarks/test_performance_benchmarks.py -m memory --benchmark-only

# Skip slow tests
pytest tests/test_benchmarks/test_performance_benchmarks.py -m "not slow" --benchmark-only
```

### Baseline Management

```bash
# Save initial baseline (do once)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline

# Save named baseline (before major change)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=pre_optimization

# Compare against baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-compare=baseline

# Auto-save with timestamp
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-autosave
```

### Regression Detection

```bash
# Fail if >10% slower (for CI/CD)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:10%

# Stricter threshold (5%)
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:5%

# Multiple metrics
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline \
    --benchmark-compare-fail=mean:10% \
    --benchmark-compare-fail=percentile_95:15%
```

### Visualization

```bash
# Generate histogram
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-histogram=benchmark_histogram
# Output: benchmark_histogram.svg

# Export JSON for analysis
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-json=results.json
```

### Memory Profiling

```bash
# Run memory benchmarks
pytest tests/test_benchmarks/test_performance_benchmarks.py -m memory --benchmark-only

# Advanced profiling with memray
pip install memray
memray run -m pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only
memray flamegraph memray-*.bin
```

## CI/CD Integration

### GitHub Actions

Copy `.github/workflows/benchmarks.yml.example` to `.github/workflows/benchmarks.yml`:

```bash
cp .github/workflows/benchmarks.yml.example .github/workflows/benchmarks.yml
```

This workflow:
- Runs on all PRs and pushes to main
- Compares against baseline
- Fails if >10% regression detected
- Posts results as PR comment
- Auto-updates baseline on main branch
- Runs memory profiling separately
- Matrix execution for parallel category testing

### Pre-commit Hook

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

## File Structure

```
tests/test_benchmarks/
├── README.md                          # This file
├── BENCHMARK_STRATEGY.md              # Detailed strategy document
├── QUICK_START.md                     # Quick reference guide
├── test_performance_benchmarks.py     # 62 benchmark tests
└── __init__.py

.benchmarks/
├── README.md                          # Baseline management guide
├── CHANGELOG.md                       # Performance changelog
└── Linux-CPython-3.12-64bit/
    ├── 0001_baseline.json            # Baseline data
    └── ...

.github/workflows/
└── benchmarks.yml.example             # CI/CD template
```

## Documentation

- **[QUICK_START.md](QUICK_START.md)**: Quick reference for common commands
- **[BENCHMARK_STRATEGY.md](BENCHMARK_STRATEGY.md)**: Comprehensive strategy guide
- **[.benchmarks/README.md](../../.benchmarks/README.md)**: Baseline management
- **[.benchmarks/CHANGELOG.md](../../.benchmarks/CHANGELOG.md)**: Performance history

## Best Practices

### 1. Before Making Changes

```bash
# Optional: Save named baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-save=before_my_change
```

### 2. After Making Changes

```bash
# Compare against baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-compare=baseline
```

### 3. If Regression Detected

1. **Profile**: `python -m cProfile -o profile.stats tests/test_benchmarks/test_performance_benchmarks.py::test_name`
2. **Investigate**: Use `snakeviz profile.stats` for visualization
3. **Fix**: Optimize the bottleneck
4. **Verify**: Re-run benchmark
5. **Document**: Update `.benchmarks/CHANGELOG.md`

### 4. Update Baseline

Only after fix applied or regression accepted:

```bash
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
    --benchmark-save=baseline
```

## Performance Budgets

Benchmarks enforce performance budgets (see `PERFORMANCE_BUDGETS` in test file):

- **Target**: Desired performance goal
- **Alert**: Warning threshold (prints warning)
- **Fail**: Hard limit (fails test immediately)

Example:
```python
{
    "compiler_simple": {"target": 1.0, "alert": 0.9, "fail": 1.5},  # seconds
    "agent_execution": {"target": 0.1, "alert": 0.09, "fail": 0.15},  # seconds
}
```

## Troubleshooting

### Inconsistent Results

- Close background applications
- Disable CPU frequency scaling (Linux): `echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`
- Run multiple times: `--benchmark-min-rounds=10`
- Enable warmup: `--benchmark-warmup=on`

### Baseline Missing

```bash
# Create baseline
pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline
```

### Benchmarks Too Slow

```bash
# Skip slow tests
pytest tests/test_benchmarks/test_performance_benchmarks.py -m "not slow" --benchmark-only

# Run specific category
pytest tests/test_benchmarks/test_performance_benchmarks.py -k "database" --benchmark-only
```

## Resources

- **pytest-benchmark**: https://pytest-benchmark.readthedocs.io/
- **Python profiling**: https://docs.python.org/3/library/profile.html
- **memray**: https://bloomberg.github.io/memray/
- **snakeviz**: https://jiffyclub.github.io/snakeviz/

## Summary

This benchmark suite provides comprehensive performance testing for the meta-autonomous-framework:

- **62 benchmarks** covering all critical paths
- **8 categories**: Compiler, Database, LLM, Tools, Agents, Strategies, Safety, E2E
- **Baseline storage** with historical tracking
- **Regression detection** with configurable thresholds
- **Memory profiling** for leak detection
- **CI/CD ready** with GitHub Actions template
- **Performance budgets** with alert/fail thresholds
- **Visualization** with histograms and JSON export

**Get Started**: See [QUICK_START.md](QUICK_START.md) for common commands.

**Deep Dive**: See [BENCHMARK_STRATEGY.md](BENCHMARK_STRATEGY.md) for comprehensive documentation.
