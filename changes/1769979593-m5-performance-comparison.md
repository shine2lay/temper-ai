# M5 Performance Comparison Implementation

**Date:** 2026-02-01
**Task:** code-med-m5-performance-comparison
**Type:** Feature - M5 Core Component
**Priority:** P2 (Medium)
**Impact:** High

## Summary

Implemented performance comparison module for M5's self-improvement system. This module compares current vs baseline performance profiles to detect improvements/regressions, calculate improvement scores, and identify optimization opportunities. Used by ImprovementDetector to trigger adaptive experiments.

## Changes

### New Files

1. **`src/self_improvement/performance_comparison.py`** (345 lines)
   - `compare_profiles()` - Main comparison function
   - `MetricChange` dataclass - Represents change in a single metric
   - `PerformanceComparison` dataclass - Aggregated comparison results
   - Helper functions: `_find_common_metrics()`, `_is_improvement()`, `_calculate_improvement_score()`
   - Custom exceptions: `IncomparableProfilesError`

2. **`tests/test_self_improvement/test_performance_comparison.py`** (438 lines)
   - 24 comprehensive tests (100% pass rate)
   - Test classes: TestMetricChange, TestPerformanceComparison, TestCompareProfiles
   - Test coverage: improvements, regressions, mixed scenarios, error handling, edge cases

## Technical Architecture

### Design Principles

**Metric-by-Metric Comparison:**
- Compare each metric individually (success_rate, duration, cost, tokens)
- Calculate absolute and relative changes
- Determine improvement based on metric type (higher/lower is better)

**Statistical Significance:**
- `min_improvement_threshold` parameter (default 5%)
- Filters out noise from random variance
- Only reports meaningful changes

**Flexible Weighting:**
- Optional `metric_weights` parameter
- Allows prioritizing critical metrics (e.g., success_rate over cost)
- Default: equal weights for all metrics

**Graceful Handling:**
- Handles missing metrics (compares only common metrics)
- Clear error messages for incomparable profiles
- Validates inputs before processing

### API Design

```python
def compare_profiles(
    baseline: AgentPerformanceProfile,
    current: AgentPerformanceProfile,
    min_improvement_threshold: float = 0.05,
    metric_weights: Optional[Dict[str, float]] = None
) -> PerformanceComparison
```

**Parameters:**
- `baseline` - Historical baseline profile (from PerformanceAnalyzer.get_baseline())
- `current` - Current performance profile (from PerformanceAnalyzer.analyze_agent_performance())
- `min_improvement_threshold` - Minimum relative change to consider significant (default 5%)
- `metric_weights` - Optional dict mapping metric names to weights (default: equal weights)

**Returns:**
- `PerformanceComparison` object with:
  - `metric_changes` - List of MetricChange objects
  - `overall_improvement` - Boolean (True if score > 0)
  - `improvement_score` - Float from -1.0 (total regression) to +1.0 (total improvement)

**Raises:**
- `IncomparableProfilesError` - Different agents or no common metrics
- `ValueError` - Invalid threshold (not 0.0-1.0)

### Data Models

**MetricChange:**
```python
@dataclass
class MetricChange:
    metric_name: str          # "success_rate", "duration_seconds", etc.
    stat_name: str            # "mean", "p95", etc.
    baseline_value: float
    current_value: float
    absolute_change: float    # current - baseline
    relative_change: float    # (current - baseline) / baseline
    is_improvement: bool      # True if change is positive
```

**PerformanceComparison:**
```python
@dataclass
class PerformanceComparison:
    agent_name: str
    baseline_window: str
    current_window: str
    baseline_executions: int
    current_executions: int
    metric_changes: List[MetricChange]
    overall_improvement: bool
    improvement_score: float  # -1.0 to +1.0
```

### Improvement Detection Logic

**Higher is Better Metrics:**
- `success_rate`, `quality_score`, `accuracy`, etc.
- Positive change = improvement
- Example: 0.85 → 0.90 success rate = +5.9% improvement

**Lower is Better Metrics:**
- `cost_usd`, `duration_seconds`, `error_rate`
- Negative change = improvement
- Example: 10.0s → 8.0s duration = -20% improvement (20% faster)

**Threshold Filtering:**
```python
# Change too small to matter - considered neutral
if abs(change) < threshold:
    return False

# Significant change - determine direction
if "cost" in metric_name or "duration" in metric_name:
    return change < 0  # Lower is better
else:
    return change > 0  # Higher is better
```

### Improvement Score Calculation

**Algorithm:**
1. Each metric contributes +1 for improvement, -1 for regression
2. Multiply by metric weight (if provided)
3. Sum all weighted contributions
4. Normalize to [-1.0, +1.0] range

**Examples:**

*All improvements (3 metrics, equal weights):*
```
score = (+1 + +1 + +1) / 3 = +1.0
```

*All regressions (3 metrics, equal weights):*
```
score = (-1 + -1 + -1) / 3 = -1.0
```

*Mixed (2 improvements, 1 regression):*
```
score = (+1 + +1 + -1) / 3 = +0.33
```

*Weighted (success_rate=2.0, cost=1.0, duration=1.0):*
```
# success_rate improved, cost regressed, duration improved
score = (+2.0 + -1.0 + +1.0) / (2.0 + 1.0 + 1.0) = +0.5
```

## Usage Examples

### Basic Comparison

```python
from src.observability.database import get_session
from src.self_improvement.performance_analyzer import PerformanceAnalyzer
from src.self_improvement.performance_comparison import compare_profiles

with get_session() as session:
    analyzer = PerformanceAnalyzer(session)

    # Get baseline (30 days)
    baseline = analyzer.get_baseline("code_review_agent", window_days=30)

    # Get current week
    current = analyzer.analyze_agent_performance("code_review_agent", window_hours=168)

    # Compare
    if baseline:
        comparison = compare_profiles(baseline, current)

        if comparison.overall_improvement:
            print(f"🎉 Performance improved! Score: {comparison.improvement_score:+.2f}")
            for change in comparison.get_improvements():
                print(f"  ✅ {change.metric_name}: {change.relative_change:+.1%}")
        else:
            print(f"⚠️  Performance regressed. Score: {comparison.improvement_score:+.2f}")
            for change in comparison.get_regressions():
                print(f"  ❌ {change.metric_name}: {change.relative_change:+.1%}")
```

### With Custom Weights

```python
# Prioritize success rate over cost
metric_weights = {
    "success_rate": 3.0,   # Most important
    "duration_seconds": 2.0,
    "cost_usd": 1.0        # Least important
}

comparison = compare_profiles(
    baseline, current,
    metric_weights=metric_weights
)

print(f"Weighted improvement score: {comparison.improvement_score:+.2f}")
```

### Detailed Analysis

```python
comparison = compare_profiles(baseline, current)

# Get specific metric change
success_change = comparison.get_metric_change("success_rate", "mean")
if success_change:
    print(f"Success rate: {success_change.baseline_value:.2%} → {success_change.current_value:.2%}")
    print(f"Change: {success_change.relative_change:+.1%}")

# Analyze improvements
print(f"\nImprovements ({len(comparison.get_improvements())}):")
for change in comparison.get_improvements():
    print(f"  {change}")

# Analyze regressions
print(f"\nRegressions ({len(comparison.get_regressions())}):")
for change in comparison.get_regressions():
    print(f"  {change}")
```

## Error Handling

### Exception Types

**IncomparableProfilesError:**
- Raised when profiles are from different agents
- Raised when no common metrics between profiles
- Contains detailed error message

**ValueError:**
- Raised for invalid `min_improvement_threshold` (not in 0.0-1.0)
- Validates inputs before processing

### Error Handling Strategy

```python
from src.self_improvement.performance_comparison import (
    compare_profiles,
    IncomparableProfilesError
)

try:
    comparison = compare_profiles(baseline, current)
except IncomparableProfilesError as e:
    logger.warning(f"Cannot compare profiles: {e}")
    # Skip comparison or use default behavior
except ValueError as e:
    logger.error(f"Invalid parameters: {e}")
    # Fix calling code
```

## Test Coverage

### Test Statistics

- **Total tests:** 24
- **Pass rate:** 100%
- **Execution time:** 0.08 seconds
- **Coverage:** All code paths tested

### Test Categories

**MetricChange (2 tests):**
- ✅ Creation with all fields
- ✅ String representation

**PerformanceComparison (3 tests):**
- ✅ Get specific metric change
- ✅ Get improvements
- ✅ Get regressions

**compare_profiles() (8 tests):**
- ✅ Improvement scenario
- ✅ Regression scenario
- ✅ Mixed scenario (some improve, some regress)
- ✅ Different agents error
- ✅ No common metrics error
- ✅ Invalid threshold error
- ✅ Custom metric weights
- ✅ Min improvement threshold filtering

**_is_improvement() (3 tests):**
- ✅ Higher is better metrics
- ✅ Lower is better metrics
- ✅ Change below threshold

**_calculate_improvement_score() (5 tests):**
- ✅ All improvements
- ✅ All regressions
- ✅ Mixed changes
- ✅ Weighted score calculation
- ✅ Empty changes

**_find_common_metrics() (3 tests):**
- ✅ Identical metrics
- ✅ Partial overlap
- ✅ No overlap

## Integration Points

### Upstream Dependencies

**PerformanceAnalyzer:**
- Uses `AgentPerformanceProfile` from performance_analyzer module
- Compares profiles generated by `analyze_agent_performance()` and `get_baseline()`
- Requires common metrics between profiles

**Data Models:**
- Uses `AgentPerformanceProfile` from `src/self_improvement/data_models.py`
- Accesses metrics via `get_metric()` method
- Uses `window_start`, `window_end`, `total_executions` attributes

### Downstream Consumers

**ImprovementDetector (Future):**
- Will use `compare_profiles()` to detect performance degradation
- Triggers adaptive experiments when regressions detected
- Uses `improvement_score` to prioritize optimization opportunities

**Dashboard/UI (Future):**
- Display performance trends over time
- Show improvement/regression highlights
- Visualize metric-by-metric comparisons

## Performance Impact

**Computation:**
- O(n) where n = number of metrics
- Typical case: <1ms for 5-10 metrics
- No database queries (operates on in-memory profiles)

**Memory Usage:**
- O(n) - creates MetricChange object per metric
- Typical case: <1KB per comparison
- No caching (stateless comparison)

**Scalability:**
- Independent comparisons (parallelizable)
- No shared state (thread-safe)
- Can compare 1000s of profiles/second

## Known Limitations

### No Percentile Comparison Yet

**Status:** Not implemented in initial version

**Reason:** PerformanceAnalyzer doesn't yet calculate p95/p99 (requires SQLite 3.38+)

**Current State:**
- Only compares "mean" statistics
- Code supports comparing any stat_name (p95, p99) when available

**Future Work:**
- Add percentile comparison when PerformanceAnalyzer supports it
- Use same comparison logic (already supports stat_name parameter)

### No Time-Series Trending

**Status:** Not implemented

**Reason:** Focused on single baseline vs current comparison for Milestone 1

**Future Work:**
- Compare multiple time windows (e.g., week-over-week)
- Detect trends (improving, stable, degrading)
- Calculate velocity of improvement/regression

### No Statistical Significance Testing

**Status:** Not implemented

**Reason:** Simple threshold-based filtering sufficient for Milestone 1

**Future Work:**
- Add t-test or z-test for statistical significance
- Consider sample size when determining significance
- Report confidence intervals

## Security Considerations

**Input Validation:**
- Validates agent names match
- Validates threshold in valid range (0.0-1.0)
- Validates profiles are comparable (common metrics)

**No External Input:**
- Operates on in-memory data structures
- No database queries or file I/O
- No user-provided strings (only structured data)

**Type Safety:**
- Uses dataclasses with type hints
- Validates types at runtime
- Clear error messages for invalid inputs

## Future Enhancements

1. **Statistical Significance Testing**
   - t-test or z-test for changes
   - Confidence intervals
   - Sample size considerations

2. **Time-Series Trending**
   - Multi-window comparison
   - Trend detection (improving/degrading)
   - Velocity calculation

3. **Percentile Comparison**
   - Compare p95, p99 when available
   - Tail latency analysis
   - Outlier detection

4. **Custom Comparison Logic**
   - Pluggable comparison functions
   - Domain-specific comparison rules
   - Configurable improvement criteria

5. **Visualization Support**
   - Generate comparison charts
   - Before/after visualizations
   - Trend graphs

## References

- Task: code-med-m5-performance-comparison
- Depends on: code-high-m5-performance-analyzer (completed)
- Blocks: code-high-m5-improvement-detector
- Related: changes/1769979593-m5-performance-analyzer.md
- M5 Documentation: `docs/M5_MODULAR_ARCHITECTURE.md`
