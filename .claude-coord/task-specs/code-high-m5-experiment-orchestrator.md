# Task Specification: code-high-m5-experiment-orchestrator

## Problem Statement

M5 needs to run A/B/C/D experiments to test multiple config variants in parallel and determine which performs best. This is the "TEST" component of the M5 loop.

## Acceptance Criteria

- Class `ExperimentOrchestrator` in `src/self_improvement/experiments/orchestrator.py`
- Method `create_experiment(proposal: ImprovementProposal) -> Experiment`:
  - Creates experiment with control + variants
  - Sets up traffic split (e.g., 25/25/25/25 for 4 groups)
  - Stores experiment in database
- Method `assign_variant(execution_id: str) -> str`:
  - Hash-based deterministic assignment
  - Returns variant_id ("control", "variant_0", "variant_1", etc.)
- Method `is_complete(experiment_id: str) -> bool`:
  - Checks if target executions reached for all groups
  - Default: 50 executions per variant
- Integrates with StatisticalAnalyzer to determine winner
- Handles experiment lifecycle (running, completed, failed)

## Implementation Details

```python
class ExperimentOrchestrator:
    def __init__(self, db, statistical_analyzer: StatisticalAnalyzer):
        self.db = db
        self.statistical_analyzer = statistical_analyzer

    def create_experiment(
        self,
        proposal: ImprovementProposal
    ) -> Experiment:
        """Create A/B/C/D test with control + variants."""

        num_groups = 1 + len(proposal.variant_configs)  # control + variants
        traffic_split = 1.0 / num_groups

        experiment = Experiment(
            id=generate_id(),
            agent_name=proposal.agent_name,
            proposal_id=proposal.id,
            status="running",
            control_config=proposal.current_config,
            variant_configs=proposal.variant_configs,
            traffic_split=traffic_split,
            target_executions_per_variant=50,
            created_at=utcnow()
        )

        # Store in DB
        self.db.store_experiment(experiment)

        return experiment

    def assign_variant(
        self,
        experiment: Experiment,
        execution_id: str
    ) -> str:
        """
        Hash-based assignment for deterministic, reproducible experiments.
        """
        hash_val = int(hashlib.md5(execution_id.encode()).hexdigest(), 16)
        num_groups = 1 + len(experiment.variant_configs)
        bucket = hash_val % num_groups

        if bucket == 0:
            return "control"
        else:
            return f"variant_{bucket - 1}"

    def is_complete(self, experiment_id: str) -> bool:
        """Check if experiment has enough data."""
        experiment = self.db.get_experiment(experiment_id)
        results = self.db.get_experiment_results(experiment_id)

        # Count executions per variant
        counts = {}
        for result in results:
            counts[result.variant_id] = counts.get(result.variant_id, 0) + 1

        # All groups must reach target
        num_groups = 1 + len(experiment.variant_configs)
        for i in range(num_groups):
            variant_id = "control" if i == 0 else f"variant_{i-1}"
            if counts.get(variant_id, 0) < experiment.target_executions_per_variant:
                return False

        return True

    def get_winner(self, experiment_id: str) -> Optional[WinnerResult]:
        """Use statistical analyzer to determine winner."""
        if not self.is_complete(experiment_id):
            return None

        experiment = self.db.get_experiment(experiment_id)
        results = self.db.get_experiment_results(experiment_id)

        return self.statistical_analyzer.analyze_experiment(experiment, results)
```

## Test Strategy

1. Unit tests with mock database
2. Test experiment creation (verify traffic split)
3. Test variant assignment (verify deterministic hashing)
4. Test is_complete with partial data (should return False)
5. Test is_complete with full data (should return True)
6. Integration test with StatisticalAnalyzer

## Dependencies

- code-med-m5-experiment-assignment
- code-med-m5-statistical-analyzer
- test-med-m5-phase3-validation

## Estimated Effort

6-8 hours (orchestration logic, DB integration, testing)
