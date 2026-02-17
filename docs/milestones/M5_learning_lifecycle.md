# M5: Continuous Learning & Self-Improvement

## M5.1: Self-Improvement Foundation
- **Scope:** Optimization engine, evaluation pipeline, experiment integration
- **Module:** `src/improvement/` (OptimizationConfig, OptimizationEngine)
- **Key design:** Config-driven optimization with A/B testing via ExperimentService

## M5.2: Experimentation Framework
- **Scope:** Statistical A/B testing for workflow variants
- **Module:** `src/experimentation/` (ExperimentService, StatisticalAnalyzer, VariantAssigner)
- **Key design:** Create experiments with variants, assign traffic, collect metrics, analyze statistical significance

## M5.3: Continuous Learning
- **Scope:** Pattern mining, recommendations, auto-tuning, convergence detection
- **Module:** `src/learning/` (MiningOrchestrator, RecommendationEngine, AutoTuneEngine, ConvergenceDetector, LearningStore)
- **Miners:** AgentPerformance, ModelEffectiveness, FailurePatterns, CostPatterns, CollaborationPatterns
- **CLI:** `maf learning mine|patterns|recommend|tune|stats`
- **Tests:** 58 tests in `tests/test_learning/`
- **Key design:** Background mining via `BackgroundMiningJob`, deduplication via content hashing, SQLite/WAL persistence
