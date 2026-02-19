# Autonomous Feedback Loop Architecture

## System Diagram

```mermaid
graph TB
    subgraph Execution
        WF[Workflow Execution] --> PE[PostExecutionOrchestrator]
    end

    subgraph "Autonomous Loop (temper_ai/autonomy/)"
        PE --> L[Learning Mining]
        PE --> G[Goal Analysis]
        PE --> P[Portfolio Update]

        L --> FB[FeedbackApplier]
        G --> FB
        FB --> AU[AuditLogger]
        FB --> CFG[Config Files]
    end

    subgraph "Learning (temper_ai/learning/)"
        L --> MO[MiningOrchestrator]
        MO --> M1[AgentPerformanceMiner]
        MO --> M2[ModelEffectivenessMiner]
        MO --> M3[FailurePatternMiner]
        MO --> M4[CostPatternMiner]
        MO --> M5[CollaborationMiner]
        MO --> LS[LearningStore]
        L --> RE[RecommendationEngine]
        RE --> LS
    end

    subgraph "Goals (temper_ai/goals/)"
        G --> AO[AnalysisOrchestrator]
        AO --> A1[PerformanceAnalyzer]
        AO --> A2[CostAnalyzer]
        AO --> A3[ReliabilityAnalyzer]
        AO --> A4[CrossProductAnalyzer]
        AO --> GS[GoalStore]
    end

    subgraph "Portfolio (temper_ai/portfolio/)"
        P --> PO[PortfolioOptimizer]
        PO --> PS[PortfolioStore]
        PS --> KG[KnowledgeGraph]
    end

    subgraph "Memory (temper_ai/memory/)"
        L --> MB[LearningToMemoryBridge]
        MB --> MS[MemoryService]
        KG --> KGA[KnowledgeGraphAdapter]
        KGA --> MS
        MS --> AG[Agent Prompt Injection]
    end
```

## Data Flow

### 1. Post-Execution Trigger
```
temper-ai run workflow.yaml --autonomous
    --> _handle_post_execution()
    --> _run_autonomous_loop()
    --> PostExecutionOrchestrator.run(context)
```

### 2. Learning Pipeline
```
MiningOrchestrator.run_mining(lookback_hours=24)
    --> 5 miners scan execution history
    --> Deduplicate patterns (content hash)
    --> Persist to LearningStore (SQLite)
    --> RecommendationEngine.generate_recommendations()
    --> Store as TuneRecommendation records
```

### 3. Goal Pipeline
```
AnalysisOrchestrator.run_analysis(lookback_hours=24)
    --> 4 analyzers scan for improvement opportunities
    --> GoalProposer.generate_proposals()
    --> Deduplicate (SHA256), score, persist
    --> GoalReviewWorkflow manages approval lifecycle
```

### 4. Feedback Application
```
FeedbackApplier.apply_learning_recommendations(min_confidence=0.8)
    --> Filter by confidence threshold
    --> Validate through GoalSafetyPolicy
    --> AutoTuneEngine applies to YAML configs
    --> AuditLogger records every change
```

## Module Dependencies (One-Directional)

```
temper_ai/autonomy/ imports from:
    ├── temper_ai/learning/    (MiningOrchestrator, RecommendationEngine, LearningStore)
    ├── temper_ai/goals/       (AnalysisOrchestrator, GoalStore)
    ├── temper_ai/portfolio/   (PortfolioOptimizer, PortfolioStore)
    └── temper_ai/memory/      (MemoryService)

Never the reverse. No circular dependencies.
```

## Safety Architecture

```
Auto-Apply Request
    --> GoalSafetyPolicy.validate_proposal()
        --> Rate limit check (20/day)
        --> Autonomy level check
        --> Risk matrix evaluation
        --> Budget impact check
    --> If approved: AutoTuneEngine.apply()
    --> AuditLogger.log(entry)  # JSONL audit trail
```
