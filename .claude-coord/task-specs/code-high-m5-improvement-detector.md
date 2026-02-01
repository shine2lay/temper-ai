# Task Specification: code-high-m5-improvement-detector

## Problem Statement

M5 needs to automatically detect when agents have performance problems (quality too low, cost too high, etc.) and invoke appropriate strategies to generate solutions. This is the "DETECT" component of the M5 loop.

## Acceptance Criteria

- Class `ImprovementDetector` in `src/self_improvement/detection/improvement_detector.py`
- Method `detect_improvement(agent_name: str) -> Optional[ImprovementProposal]`:
  - Compares current performance vs baseline
  - Detects problems using threshold-based rules
  - Finds applicable strategies from registry
  - Invokes strategy to generate variants
  - Returns ImprovementProposal or None
- Method `_detect_problems(current, baseline) -> List[Dict]`:
  - quality_low: current < baseline * 0.9
  - cost_too_high: current > baseline * 1.3
  - too_slow: current > baseline * 1.5
  - Returns list of detected problems with severity
- Integrates with PerformanceAnalyzer and StrategyRegistry
- Handles cases with no baseline (first run)
- Handles cases with no applicable strategies

## Implementation Details

```python
class ImprovementDetector:
    def __init__(
        self,
        performance_analyzer: PerformanceAnalyzer,
        strategy_registry: StrategyRegistry,
        pattern_learner: Optional[PatternLearner] = None  # MVP: can be None
    ):
        self.performance_analyzer = performance_analyzer
        self.strategy_registry = strategy_registry
        self.pattern_learner = pattern_learner

    def detect_improvement(
        self,
        agent_name: str
    ) -> Optional[ImprovementProposal]:
        """Main entry point - detects optimization opportunities."""

        # Step 1: Analyze current vs baseline
        current = self.performance_analyzer.analyze_agent_performance(
            agent_name, window_hours=168
        )
        baseline = self.performance_analyzer.get_baseline(
            agent_name, window_days=30
        )

        if not baseline:
            return None  # No baseline yet, can't detect problems

        # Step 2: Detect problems
        problems = self._detect_problems(current, baseline)
        if not problems:
            return None  # No problems found

        # Step 3: For each problem, create improvement proposal
        # For MVP: just handle first problem
        problem = problems[0]
        return self._create_improvement_proposal(agent_name, problem)

    def _detect_problems(
        self,
        current: AgentPerformanceProfile,
        baseline: AgentPerformanceProfile
    ) -> List[Dict]:
        """Detect problems using threshold rules."""
        problems = []

        # Check quality
        if current.metrics.get("extraction_quality", {}).get("mean", 1.0) < \
           baseline.metrics.get("extraction_quality", {}).get("mean", 1.0) * 0.9:
            problems.append({
                "type": "quality_low",
                "severity": ...,
                "current": ...,
                "baseline": ...
            })

        # Check cost, speed, etc.
        # ...

        return problems

    def _create_improvement_proposal(
        self,
        agent_name: str,
        problem: Dict
    ) -> Optional[ImprovementProposal]:
        """Create proposal using strategy."""

        # Find applicable strategies
        strategies = self.strategy_registry.find_applicable(problem["type"])
        if not strategies:
            return None

        # Select best strategy (for MVP: just pick first)
        strategy = strategies[0]

        # Get patterns (MVP: empty list)
        patterns = self.pattern_learner.extract_patterns(agent_name) if self.pattern_learner else []

        # Load current config
        current_config = self._load_agent_config(agent_name)

        # Generate variants
        variants = strategy.generate_variants(current_config, patterns)
        if not variants:
            return None

        # Create proposal
        return ImprovementProposal(
            id=generate_id(),
            agent_name=agent_name,
            problem_type=problem["type"],
            problem_severity=problem["severity"],
            strategy_name=strategy.name,
            current_config=current_config,
            variant_configs=variants,
            expected_improvement=strategy.estimate_impact(problem),
            created_at=utcnow()
        )
```

## Test Strategy

1. Unit tests with mock PerformanceAnalyzer and StrategyRegistry
2. Test with no baseline (should return None)
3. Test with no problems (should return None)
4. Test with quality_low problem (should create proposal)
5. Test with no applicable strategies (should return None)
6. Verify proposal contains 2-4 variant configs

## Dependencies

- code-med-m5-problem-detection
- code-med-m5-strategy-registry
- code-med-m5-improvement-proposal-model

## Estimated Effort

6-8 hours (orchestration logic, edge cases, testing)
