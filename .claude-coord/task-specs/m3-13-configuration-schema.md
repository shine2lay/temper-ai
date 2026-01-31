# Task: m3-13-configuration-schema - Configuration Schema Updates

**Priority:** CRITICAL (P0)  
**Effort:** 4 hours  
**Status:** pending  
**Owner:** unassigned

## Summary
Update Pydantic configuration schemas to include all M3 fields (collaboration, conflict_resolution, execution modes, quality_gates).

## Files to Modify
- `src/compiler/schemas.py` - Add M3 schema fields

## Acceptance Criteria
- [x] - [ ] `CollaborationConfig` schema (strategy, max_rounds, convergence_threshold, config)
- [x] - [ ] `ConflictResolutionConfig` schema (strategy, metrics, weights, thresholds, config)
- [x] - [ ] `ExecutionConfig` update (add adaptive mode, parallel config)
- [x] - [ ] `QualityGatesConfig` schema (enabled, thresholds, on_failure, max_retries)
- [x] - [ ] Schema validation passes for all example configs
- [x] - [ ] Type hints correct
- [x] - [ ] Docstrings complete
- [x] - [ ] Coverage >90%

## Schema Example
```python
class CollaborationConfig(BaseModel):
    strategy: str = "consensus"  # consensus | debate | custom
    max_rounds: int = 3
    convergence_threshold: float = 0.8
    config: Dict[str, Any] = {}

class ConflictResolutionConfig(BaseModel):
    strategy: str = "merit_weighted"
    metrics: List[str] = ["domain_merit", "overall_merit", "recent_performance"]
    metric_weights: Dict[str, float] = {}
    auto_resolve_threshold: float = 0.85
    escalation_threshold: float = 0.5
    config: Dict[str, Any] = {}
```

## Dependencies
- Blocked by: All m3 tasks (needs full understanding of requirements)

## Notes
Validation is critical. Invalid configs should fail early with clear messages.
