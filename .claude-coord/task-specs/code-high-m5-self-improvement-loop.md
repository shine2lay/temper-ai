# Task Specification: code-high-m5-self-improvement-loop

## Problem Statement

M5 needs a main orchestrator that integrates all components (WATCH → DETECT → PLAN → TEST → DEPLOY) into a cohesive self-improvement loop. This is the top-level component that brings everything together.

## Acceptance Criteria

- Class `M5SelfImprovementLoop` in `src/self_improvement/m5_loop.py`
- Method `run_analysis()`:
  - Analyzes all agents using PerformanceAnalyzer
  - Stores performance profiles
- Method `run_optimization()`:
  - Detects improvements using ImprovementDetector
  - Creates experiments for detected problems
  - Starts experiments
- Method `check_experiments()`:
  - Checks if experiments are complete
  - Analyzes results using StatisticalAnalyzer
  - Deploys winners using ConfigDeployer
- Integrates all 5 core M5 components
- Handles errors gracefully (log and continue)
- For MVP: manual triggering (no automatic scheduling)

## Implementation Details

```python
class M5SelfImprovementLoop:
    """Complete M5 self-improvement loop orchestrator."""

    def __init__(self, db):
        self.db = db

        # Initialize all components
        self.performance_analyzer = PerformanceAnalyzer(db)
        self.improvement_detector = ImprovementDetector(
            performance_analyzer=self.performance_analyzer,
            strategy_registry=self._init_strategy_registry(),
            pattern_learner=None  # MVP: no pattern learning yet
        )
        self.experiment_orchestrator = ExperimentOrchestrator(
            db=db,
            statistical_analyzer=StatisticalAnalyzer()
        )
        self.config_deployer = ConfigDeployer(db)

    def run_analysis(self):
        """WATCH: Analyze all agents, detect problems."""
        logger.info("Running M5 analysis...")

        agents = self.db.get_all_agent_names()
        for agent_name in agents:
            try:
                profile = self.performance_analyzer.analyze_agent_performance(agent_name)
                self.db.store_profile(profile)
                logger.info(f"Analyzed {agent_name}: {profile.metrics}")
            except Exception as e:
                logger.error(f"Failed to analyze {agent_name}: {e}")

    def run_optimization(self):
        """DETECT + PLAN: Find problems, create experiments."""
        logger.info("Running M5 optimization...")

        agents = self.db.get_all_agent_names()
        for agent_name in agents:
            try:
                proposal = self.improvement_detector.detect_improvement(agent_name)
                if proposal:
                    experiment = self.experiment_orchestrator.create_experiment(proposal)
                    logger.info(f"Created experiment {experiment.id} for {agent_name}")
            except Exception as e:
                logger.error(f"Failed to optimize {agent_name}: {e}")

    def check_experiments(self):
        """TEST + DEPLOY: Check if experiments done, deploy winners."""
        logger.info("Checking experiments...")

        running = self.db.get_running_experiments()
        for experiment in running:
            try:
                if self.experiment_orchestrator.is_complete(experiment.id):
                    winner = self.experiment_orchestrator.get_winner(experiment.id)

                    if winner and winner.is_better_than_control():
                        self.config_deployer.deploy(
                            agent_name=experiment.agent_name,
                            new_config=winner.config,
                            experiment_id=experiment.id
                        )
                        logger.info(f"Deployed winner for {experiment.agent_name}!")
                    else:
                        logger.info(f"No winner for {experiment.agent_name}, keeping control")

                    # Mark experiment as completed
                    self.db.mark_experiment_completed(experiment.id)
            except Exception as e:
                logger.error(f"Failed to check experiment {experiment.id}: {e}")

    def _init_strategy_registry(self) -> StrategyRegistry:
        """Initialize strategy registry with built-in strategies."""
        registry = StrategyRegistry()
        registry.register(OllamaModelSelectionStrategy())
        # Add more strategies here in future
        return registry
```

## Test Strategy

1. Integration test with all components
2. Test run_analysis (verify profiles stored)
3. Test run_optimization (verify experiments created)
4. Test check_experiments (verify winners deployed)
5. Test error handling (one agent fails, others continue)
6. End-to-end test with mock components

## Dependencies

- test-med-m5-phase5-validation

## Estimated Effort

4-6 hours (integration, orchestration, testing)
