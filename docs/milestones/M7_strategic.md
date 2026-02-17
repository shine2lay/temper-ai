# M7: Strategic Autonomy & Portfolio Management

## M7.1: Self-Modifying Lifecycle
- **Scope:** Pre-compilation workflow adaptation based on project characteristics
- **Module:** `src/lifecycle/` (LifecycleAdapter, ProjectClassifier, ProfileRegistry)
- **Key design:** Classify project -> match profile -> apply rules (SKIP/ADD/REORDER/MODIFY) -> audit
- **Autonomy integration:** AutonomyLevel gating, EmergencyStopController
- **CLI:** `maf lifecycle profiles|classify|preview|history|check`
- **Tests:** 103 tests in `tests/test_lifecycle/`

## M7.2: Strategic Autonomy
- **Scope:** Goal proposal framework with analyzers scanning execution history
- **Module:** `src/goals/` (GoalProposer, AnalysisOrchestrator, GoalSafetyPolicy, GoalReviewWorkflow)
- **Analyzers:** Performance, Cost, Reliability, CrossProduct
- **Key design:** SHA256 dedup, weighted scoring (impact + confidence + effort + risk), rate-limited proposals
- **CLI:** `maf goals list|propose|review|approve|reject|status`
- **Tests:** 101 tests in `tests/test_goals/`

## M7.3: Portfolio Management
- **Scope:** Multi-product orchestration, resource allocation, knowledge graph
- **Module:** `src/portfolio/` (ResourceScheduler, ComponentAnalyzer, PortfolioOptimizer, KnowledgeGraph)
- **Key design:** WFQ scheduling, Jaccard similarity for component sharing, 4-metric scorecards
- **CLI:** `maf portfolio list|show|run|scorecards|recommend|components|graph stats|graph query`
- **Tests:** 114 tests in `tests/test_portfolio/`
