# Change: Experiment Data Model

**Task ID:** code-med-m5-experiment-model
**Date:** 2026-02-01
**Type:** Feature - Data Models

## Summary

Created Experiment and ExperimentResult data models for M5 A/B/C/D testing framework, enabling configuration experiments with statistical analysis.

## What Changed

### Files Modified

1. **src/self_improvement/data_models.py**
   - Added `Experiment` dataclass for experiment tracking
   - Added `ExperimentResult` dataclass for execution results
   - Both models support full serialization (to_dict/from_dict)

2. **src/self_improvement/__init__.py**
   - Exported new models: Experiment, ExperimentResult

### Files Created

3. **tests/self_improvement/test_experiment_model.py**
   - 13 comprehensive tests for Experiment and ExperimentResult
   - Tests cover creation, serialization, status checks, and round-trips

## Model Details

### Experiment Model

Represents an A/B/C/D test comparing multiple configuration variants:

**Key Fields:**
- `id`: Unique experiment identifier
- `agent_name`: Agent being optimized
- `status`: 'running', 'completed', 'failed'
- `control_config`: Baseline configuration (AgentConfig)
- `variant_configs`: List of alternative configurations
- `proposal_id`: Link to ImprovementProposal that triggered experiment
- `created_at`, `completed_at`: Timestamps

**Helper Methods:**
- `get_all_configs()`: Returns dict mapping variant_id → config
- `get_variant_count()`: Total variants including control
- `is_running()`, `is_completed()`: Status checks
- `to_dict()`, `from_dict()`: Serialization

### ExperimentResult Model

Records individual execution outcome during experiment:

**Key Fields:**
- `id`: Unique result identifier
- `experiment_id`: Parent experiment
- `variant_id`: Which variant was used ('control', 'variant_0', etc.)
- `execution_id`: Link to agent execution
- `quality_score`, `speed_seconds`, `cost_usd`, `success`: Metrics
- `extra_metrics`: Dict for custom metrics

**Features:**
- Optional metrics (can track subset of metrics)
- Extensible via extra_metrics dictionary
- Full serialization support

## Use Cases

### Creating an Experiment
```python
from src.self_improvement import Experiment, AgentConfig

control = AgentConfig(
    agent_name="product_extractor",
    inference={"model": "llama3.1:8b", "temperature": 0.7}
)

variant1 = AgentConfig(
    agent_name="product_extractor",
    inference={"model": "mistral:7b", "temperature": 0.7}
)

experiment = Experiment(
    id="exp-001",
    agent_name="product_extractor",
    status="running",
    control_config=control,
    variant_configs=[variant1],
    proposal_id="prop-123"
)
```

### Recording Results
```python
from src.self_improvement import ExperimentResult

result = ExperimentResult(
    id="result-001",
    experiment_id="exp-001",
    variant_id="variant_0",
    execution_id="exec-456",
    quality_score=0.92,
    speed_seconds=42.5,
    cost_usd=0.15,
    success=True
)
```

### Getting All Configs for Assignment
```python
all_configs = experiment.get_all_configs()
# Returns: {
#   "control": <AgentConfig>,
#   "variant_0": <AgentConfig>,
#   "variant_1": <AgentConfig>
# }

# Use for hash-based assignment
variant_id = assign_variant(execution_id, all_configs.keys())
config = all_configs[variant_id]
```

## Testing Performed

All 13 tests pass:
- ✓ Experiment creation with variants
- ✓ get_all_configs() returns correct mapping
- ✓ get_variant_count() includes control
- ✓ Status checks (is_running, is_completed)
- ✓ Serialization (to_dict, from_dict)
- ✓ Round-trip conversion
- ✓ ExperimentResult with all fields
- ✓ ExperimentResult with optional fields
- ✓ ExperimentResult with custom metrics
- ✓ Result serialization
- ✓ Result round-trip

## Integration Points

### Depends On
- `AgentConfig` (already implemented in data_models.py)

### Enables
- `ExperimentOrchestrator` - Create and manage experiments
- `ExperimentAssignment` - Route executions to variants
- `StatisticalAnalyzer` - Analyze results, pick winners
- Experiment DB schemas (separate task)

## Database Schema (For Reference)

These models map to the following database tables:

```sql
CREATE TABLE experiments (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    proposal_id TEXT,
    status TEXT NOT NULL,
    control_config JSON NOT NULL,
    variant_configs JSON NOT NULL,
    created_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);

CREATE TABLE experiment_results (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    quality_score REAL,
    speed_seconds REAL,
    cost_usd REAL,
    success BOOLEAN,
    recorded_at TIMESTAMP NOT NULL,
    extra_metrics JSON,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
);
```

## Architecture Notes

### Design Decisions

1. **Variant Storage**: Stored as list, accessed via `get_all_configs()` with generated IDs
   - Rationale: Simpler storage, predictable variant naming

2. **Optional Metrics**: All metrics optional in ExperimentResult
   - Rationale: Different experiments track different metrics, flexibility needed

3. **Extra Metrics Dict**: Extensible custom metrics
   - Rationale: Future-proof for domain-specific metrics

4. **Status Enum as String**: "running", "completed", "failed"
   - Rationale: Simpler database storage, no enum mapping needed

### Trade-offs

**Chosen: List[AgentConfig] for variants**
- Pro: Simple, predictable variant IDs (variant_0, variant_1...)
- Pro: Easy to iterate and count
- Con: Must use get_all_configs() for ID-based access

**Alternative: Dict[str, AgentConfig]**
- Pro: Direct ID access
- Con: More complex serialization
- Con: User must provide variant IDs

## Risks & Mitigations

**Risk:** Variant ID generation (variant_0, variant_1) might not match external expectations
**Mitigation:** Well-documented get_all_configs() method with clear examples

**Risk:** Optional metrics might cause confusion about what's required
**Mitigation:** Comprehensive tests show all usage patterns, documentation clarifies requirements

## Next Steps

This model unblocks:
- `code-med-m5-experiment-db-schema` - Database tables for experiments
- `code-med-m5-experiment-assignment` - Variant assignment logic
- `code-med-m5-statistical-analyzer` - Analyze experiment results
- `code-high-m5-experiment-orchestrator` - Create and manage experiments
