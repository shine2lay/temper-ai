# M5 Self-Improvement Loop - Implementation Guide

## Overview

The M5 Self-Improvement Loop is the main orchestrator that integrates all 5 phases of the M5 self-improvement system into a unified, production-ready loop for automated agent improvement.

**Version:** 1.0.0
**Status:** ✅ Implemented
**Lines of Code:** ~1,550 LOC

---

## Architecture

### Components

The loop is implemented as a modular system with clear separation of concerns:

```
src/self_improvement/loop/
├── __init__.py              # Public API exports
├── orchestrator.py          # M5SelfImprovementLoop (main class)
├── executor.py              # LoopExecutor (phase orchestration)
├── state_manager.py         # LoopStateManager (state persistence)
├── error_recovery.py        # ErrorRecoveryStrategy (retry logic)
├── metrics.py               # MetricsCollector (observability)
├── config.py                # LoopConfig (configuration)
└── models.py                # Data models
```

### Phase Integration

| Phase | Component | Purpose |
|-------|-----------|---------|
| 1. DETECT | ImprovementDetector | Identify performance problems |
| 2. ANALYZE | PerformanceAnalyzer | Analyze current metrics |
| 3. STRATEGY | Strategy generators | Generate config variants |
| 4. EXPERIMENT | ExperimentOrchestrator | Run A/B/C/D tests |
| 5. DEPLOY | ConfigDeployer + RollbackMonitor | Deploy and monitor |

---

## Quick Start

### Basic Usage

```python
from coord_service.database import Database
from src.observability.database import get_session
from src.self_improvement.loop import M5SelfImprovementLoop

# Initialize databases
coord_db = Database()

with get_session() as obs_session:
    # Create loop
    loop = M5SelfImprovementLoop(
        coord_db=coord_db,
        obs_session=obs_session
    )

    # Run single iteration
    result = loop.run_iteration("my_agent")

    if result.success:
        print("✓ Improvement cycle completed!")
        print(f"Phases: {[p.value for p in result.phases_completed]}")

        if result.deployment_result:
            print(f"Deployed: {result.deployment_result.deployment_id}")
    else:
        print(f"✗ Failed: {result.error}")
```

### Custom Configuration

```python
from src.self_improvement.loop import LoopConfig

config = LoopConfig(
    # Phase 1: Detection
    detection_window_hours=336,  # 2 weeks
    min_executions_for_detection=100,

    # Phase 4: Experimentation
    target_samples_per_variant=100,
    experiment_timeout_hours=120,  # 5 days

    # Phase 5: Deployment
    enable_auto_deploy=True,
    enable_auto_rollback=True,
    rollback_quality_drop_pct=10.0,  # 10% quality drop triggers rollback

    # Error handling
    max_retries_per_phase=3,
)

loop = M5SelfImprovementLoop(coord_db, obs_session, config)
result = loop.run_iteration("my_agent")
```

---

## State Management

### Loop States

The loop maintains persistent state in the coordination database:

```python
# Get current state
state = loop.get_state("my_agent")
print(f"Current phase: {state['current_phase']}")
print(f"Iteration: {state['iteration_number']}")
print(f"Status: {state['status']}")

# Pause execution
loop.pause("my_agent")

# Resume later
loop.resume("my_agent")

# Reset all state
loop.reset_state("my_agent")
```

### State Persistence

State is persisted to the `m5_loop_state` table in the coordination database:

```sql
CREATE TABLE m5_loop_state (
    agent_name TEXT PRIMARY KEY,
    current_phase TEXT NOT NULL,
    status TEXT NOT NULL,
    iteration_number INTEGER DEFAULT 0,
    phase_data TEXT,  -- JSON
    last_error TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

This enables:
- **Crash recovery** - Resume from last successful phase
- **Multi-process safety** - State shared across processes
- **Audit trail** - Track loop progress over time

---

## Error Handling

### Recovery Strategy

The loop implements intelligent error recovery with:

1. **Transient Error Detection**
   - Database query errors
   - Timeout errors
   - Connection errors
   → Retry with exponential backoff

2. **Permanent Error Detection**
   - Invalid input (ValueError)
   - Configuration errors
   → Skip iteration or fail (configurable)

3. **Retry Logic**
   - Max retries: 3 (configurable)
   - Backoff multiplier: 2.0x (configurable)
   - Initial delay: 5s (configurable)

### Example Error Handling

```python
config = LoopConfig(
    max_retries_per_phase=3,
    retry_backoff_multiplier=2.0,
    initial_retry_delay_seconds=5.0,
    fail_on_permanent_error=False,  # Skip vs fail
)

loop = M5SelfImprovementLoop(coord_db, obs_session, config)

try:
    result = loop.run_iteration("my_agent")
except Exception as e:
    print(f"Iteration failed: {e}")

    # Check state for details
    state = loop.get_state("my_agent")
    print(f"Failed at phase: {state['current_phase']}")
    print(f"Last error: {state['last_error']}")
```

---

## Monitoring & Observability

### Progress Tracking

```python
# Get current progress
progress = loop.get_progress("my_agent")
print(f"Current phase: {progress.current_phase.value}")
print(f"Iteration: {progress.current_iteration}")
print(f"Health: {progress.health_status}")
print(f"Total completed: {progress.total_iterations_completed}")
```

### Metrics Collection

```python
# Get aggregated metrics
metrics = loop.get_metrics("my_agent")

if metrics:
    print(f"Total iterations: {metrics['total_iterations']}")
    print(f"Success rate: {metrics['success_rate']:.1%}")
    print(f"Avg duration: {metrics['avg_iteration_duration']:.1f}s")
    print(f"Total experiments: {metrics['total_experiments']}")
    print(f"Successful deployments: {metrics['successful_deployments']}")
    print(f"Rollbacks: {metrics['rollbacks']}")

    # Phase-specific metrics
    for phase, success_rate in metrics['phase_success_rates'].items():
        print(f"  {phase}: {success_rate:.1%} success rate")
```

### Health Checks

```python
# Check system health
health = loop.health_check()

print(f"Status: {health['status']}")
for component, status in health['components'].items():
    print(f"  {component}: {status}")
```

---

## Configuration Reference

### LoopConfig Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| **Phase 1: Detection** | | |
| `detection_window_hours` | 168 (7 days) | Time window for problem detection |
| `min_executions_for_detection` | 50 | Min samples needed for detection |
| **Phase 2: Analysis** | | |
| `analysis_window_hours` | 168 (7 days) | Time window for performance analysis |
| `min_executions_for_analysis` | 10 | Min samples for analysis |
| **Phase 3: Strategy** | | |
| `max_variants_per_experiment` | 3 | Max variants to test (A/B/C/D) |
| `enable_model_variants` | True | Test different LLM models |
| `enable_prompt_variants` | True | Test different prompts |
| **Phase 4: Experimentation** | | |
| `target_samples_per_variant` | 50 | Samples per variant for significance |
| `experiment_timeout_hours` | 72 (3 days) | Max experiment duration |
| `min_improvement_threshold` | 0.05 (5%) | Min improvement to deploy |
| **Phase 5: Deployment** | | |
| `enable_auto_deploy` | True | Auto-deploy winners |
| `enable_auto_rollback` | True | Auto-rollback on regression |
| `rollback_quality_drop_pct` | 10.0 | Quality drop triggers rollback |
| `rollback_cost_increase_pct` | 20.0 | Cost increase triggers rollback |
| `rollback_speed_increase_pct` | 30.0 | Speed degradation triggers rollback |
| **Error Handling** | | |
| `max_retries_per_phase` | 3 | Max retries per phase |
| `retry_backoff_multiplier` | 2.0 | Exponential backoff multiplier |
| `initial_retry_delay_seconds` | 5.0 | Initial retry delay |

---

## Data Models

### IterationResult

```python
@dataclass
class IterationResult:
    agent_name: str
    iteration_number: int
    success: bool
    phases_completed: List[Phase]
    detection_result: Optional[DetectionResult]
    analysis_result: Optional[AnalysisResult]
    strategy_result: Optional[StrategyResult]
    experiment_result: Optional[ExperimentResult]
    deployment_result: Optional[DeploymentResult]
    error: Optional[Exception]
    error_phase: Optional[Phase]
    duration_seconds: float
    timestamp: datetime
```

### Phase Results

Each phase returns a specific result type:

- **DetectionResult** - Problem detection outcome
- **AnalysisResult** - Performance metrics and profile
- **StrategyResult** - Control + variant configs
- **ExperimentResult** - Winner variant and metrics
- **DeploymentResult** - Deployment ID and rollback status

---

## Testing

### Unit Tests

```bash
# Run loop tests
pytest tests/self_improvement/test_m5_loop.py -v

# Run with coverage
pytest tests/self_improvement/test_m5_loop.py --cov=src/self_improvement/loop
```

### Integration Tests

```python
# End-to-end test
from src.self_improvement.loop import M5SelfImprovementLoop

def test_complete_iteration():
    """Test complete improvement cycle."""
    loop = M5SelfImprovementLoop(coord_db, obs_session)

    result = loop.run_iteration("test_agent")

    assert result.success
    assert Phase.DETECT in result.phases_completed
    assert Phase.ANALYZE in result.phases_completed
    # ... etc
```

---

## Production Deployment

### Environment Variables

```bash
# Enable M5 loop (optional feature flag)
export M5_LOOP_ENABLED=true

# Logging
export M5_LOG_LEVEL=INFO
```

### Monitoring Recommendations

1. **Alert on Failed Iterations**
   ```python
   if not result.success:
       send_alert(f"M5 iteration failed for {agent_name}: {result.error}")
   ```

2. **Track Success Rate**
   - Monitor `success_rate` metric
   - Alert if drops below threshold (e.g., 80%)

3. **Monitor Rollbacks**
   - Track `rollbacks` metric
   - Investigate frequent rollbacks

4. **Phase Duration Tracking**
   - Monitor `phase_avg_durations`
   - Alert on slow phases (> threshold)

---

## Known Limitations

1. **No Continuous Mode** - Must use external scheduler (e.g., cron)
2. **No History Persistence** - Iteration history not yet stored
3. **Single Agent Per Iteration** - No batch processing (by design)
4. **No Mid-Iteration Resume** - Can only resume at phase boundaries

---

## Future Enhancements

1. **Continuous Mode** - Background monitoring loop
2. **Scheduled Execution** - Built-in cron support
3. **Multi-Agent Batching** - Process multiple agents in parallel
4. **Iteration History Storage** - Persist results to database
5. **Advanced Strategies** - More sophisticated variant generation
6. **Real-time Dashboards** - Web UI for monitoring

---

## API Reference

### M5SelfImprovementLoop

**Methods:**
- `run_iteration(agent_name, start_phase=Phase.DETECT) -> IterationResult`
- `get_state(agent_name) -> Optional[Dict]`
- `reset_state(agent_name) -> None`
- `pause(agent_name) -> None`
- `resume(agent_name) -> None`
- `get_progress(agent_name) -> ProgressReport`
- `get_metrics(agent_name) -> Optional[Dict]`
- `health_check() -> Dict`

### LoopConfig

**Constructor:**
```python
LoopConfig(
    detection_window_hours=168,
    target_samples_per_variant=50,
    enable_auto_deploy=True,
    enable_auto_rollback=True,
    # ... see Configuration Reference
)
```

**Methods:**
- `validate() -> None` - Validate configuration
- `to_dict() -> dict` - Export as dictionary
- `from_dict(data) -> LoopConfig` - Load from dictionary

---

## Support

For issues or questions:
- Check logs: `~/.claude/logs/m5_loop.log`
- Review state: `coord_db.query("SELECT * FROM m5_loop_state")`
- Run health check: `loop.health_check()`

---

## Changelog

### v1.0.0 (2026-02-01)
- ✅ Initial implementation
- ✅ All 5 phases integrated
- ✅ State persistence and crash recovery
- ✅ Error recovery with retry logic
- ✅ Metrics collection and observability
- ✅ Pause/resume support
- ✅ Health checks
