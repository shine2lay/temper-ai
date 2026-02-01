# M5 Milestone 1 - Task Breakdown

## Overview

This document breaks down M5.1 into small, parallel-able tasks with dependency relationships.

**Total Tasks:** 35
**Estimated Parallelization:** Up to 8 tasks can run concurrently at peak

---

## Phase 0: Foundation (4 tasks)

### code-quick-m5-ollama-setup
**Subject:** Setup Ollama and pull models
**Description:** Install Ollama, pull test models (phi3:mini, llama3.1:8b, mistral:7b, qwen2.5:32b)
**Dependencies:** None
**Can run in parallel with:** Any Phase 0 task

### code-quick-m5-db-schema-custom-metrics
**Subject:** Add custom_metrics table schema
**Description:** Create SQL migration for custom_metrics table
**Dependencies:** None
**Can run in parallel with:** Any Phase 0 task

### code-quick-m5-data-model-config
**Subject:** Create AgentConfig data model
**Description:** Python dataclass for agent configuration
**Dependencies:** None
**Can run in parallel with:** Any Phase 0 task

### code-quick-m5-data-model-execution
**Subject:** Create AgentExecution data model
**Description:** Python dataclass for execution tracking (may already exist in M1)
**Dependencies:** None
**Can run in parallel with:** Any Phase 0 task

---

## Phase 1: Agent + Quality Metric (8 tasks)

### code-high-m5-metric-collector-interface
**Subject:** Define MetricCollector interface
**Description:** Abstract base class for metric collectors (Modularity Point #1)
**Dependencies:** None
**Blocks:** All other Phase 1 tasks
**Spec Required:** Yes (critical interface)

### code-med-m5-metric-registry
**Subject:** Implement MetricRegistry
**Description:** Registry for metric collectors with registration and collection
**Dependencies:** code-high-m5-metric-collector-interface
**Can run in parallel with:** code-med-m5-extraction-quality-collector, code-med-m5-product-extractor

### code-med-m5-extraction-quality-collector
**Subject:** Build ExtractionQualityCollector
**Description:** Collector that measures field-level accuracy for structured extraction
**Dependencies:** code-high-m5-metric-collector-interface
**Can run in parallel with:** code-med-m5-metric-registry, code-med-m5-product-extractor

### code-med-m5-ollama-client
**Subject:** Create OllamaClient wrapper
**Description:** Wrapper for Ollama API with generate() method
**Dependencies:** code-quick-m5-ollama-setup
**Can run in parallel with:** All Phase 1 except interface

### code-med-m5-product-extractor
**Subject:** Implement ProductExtractorAgent
**Description:** Agent that extracts structured product info using Ollama
**Dependencies:** code-med-m5-ollama-client, code-quick-m5-data-model-config
**Can run in parallel with:** code-med-m5-metric-registry, code-med-m5-extraction-quality-collector

### code-med-m5-test-dataset
**Subject:** Create product extraction test dataset
**Description:** 50 product descriptions with ground truth JSON
**Dependencies:** None
**Can run in parallel with:** All Phase 1 tasks

### code-med-m5-execution-tracker-integration
**Subject:** Integrate MetricRegistry into ExecutionTracker
**Description:** Update ExecutionTracker to call metric collectors after execution
**Dependencies:** code-med-m5-metric-registry, code-med-m5-extraction-quality-collector
**Can run in parallel with:** Nothing (integration task)

### test-med-m5-phase1-validation
**Subject:** Validate Phase 1 components
**Description:** Run agent 50 times, verify quality scores stored in DB
**Dependencies:** code-med-m5-execution-tracker-integration, code-med-m5-product-extractor, code-med-m5-test-dataset
**Can run in parallel with:** Nothing (validation task)

---

## Phase 2: Performance Analysis (5 tasks)

### code-med-m5-performance-profile-model
**Subject:** Create AgentPerformanceProfile model
**Description:** Dataclass for performance profile with metrics aggregation
**Dependencies:** None
**Can run in parallel with:** All Phase 2 tasks

### code-high-m5-performance-analyzer
**Subject:** Implement PerformanceAnalyzer (WATCH)
**Description:** Core analyzer with SQL-based metric aggregation
**Dependencies:** code-med-m5-performance-profile-model, test-med-m5-phase1-validation
**Blocks:** Phase 3
**Spec Required:** Yes (critical component)

### code-med-m5-baseline-storage
**Subject:** Add baseline storage logic
**Description:** Store and retrieve baseline performance profiles
**Dependencies:** code-high-m5-performance-analyzer
**Can run in parallel with:** code-med-m5-performance-comparison

### code-med-m5-performance-comparison
**Subject:** Add performance comparison logic
**Description:** Compare current vs baseline profiles
**Dependencies:** code-high-m5-performance-analyzer
**Can run in parallel with:** code-med-m5-baseline-storage

### test-med-m5-phase2-validation
**Subject:** Validate Phase 2 components
**Description:** Run 100 extractions, analyze performance, create baseline
**Dependencies:** code-med-m5-baseline-storage, code-med-m5-performance-comparison
**Can run in parallel with:** Nothing (validation task)

---

## Phase 3: Problem Detection + Strategy (8 tasks)

### code-med-m5-problem-detection
**Subject:** Implement problem detection logic
**Description:** Detect quality_low, cost_too_high, too_slow problems
**Dependencies:** test-med-m5-phase2-validation
**Can run in parallel with:** code-high-m5-strategy-interface, code-med-m5-improvement-proposal-model

### code-high-m5-strategy-interface
**Subject:** Define ImprovementStrategy interface
**Description:** Abstract base class for strategies (Modularity Point #2)
**Dependencies:** None
**Blocks:** code-med-m5-strategy-registry, code-med-m5-ollama-model-strategy
**Spec Required:** Yes (critical interface)

### code-med-m5-strategy-registry
**Subject:** Implement StrategyRegistry
**Description:** Registry for improvement strategies
**Dependencies:** code-high-m5-strategy-interface
**Can run in parallel with:** code-med-m5-ollama-model-strategy

### code-med-m5-model-registry
**Subject:** Create ModelRegistry for Ollama models
**Description:** Registry of available Ollama models with metadata
**Dependencies:** None
**Can run in parallel with:** All Phase 3 tasks

### code-med-m5-ollama-model-strategy
**Subject:** Implement OllamaModelSelectionStrategy
**Description:** Strategy that generates model variant configs
**Dependencies:** code-high-m5-strategy-interface, code-med-m5-model-registry
**Can run in parallel with:** code-med-m5-strategy-registry

### code-med-m5-improvement-proposal-model
**Subject:** Create ImprovementProposal model
**Description:** Dataclass for improvement proposals
**Dependencies:** None
**Can run in parallel with:** All Phase 3 tasks

### code-high-m5-improvement-detector
**Subject:** Implement ImprovementDetector (DETECT)
**Description:** Main detector that orchestrates problem detection and strategy invocation
**Dependencies:** code-med-m5-problem-detection, code-med-m5-strategy-registry, code-med-m5-improvement-proposal-model
**Blocks:** Phase 4
**Spec Required:** Yes (critical component)

### test-med-m5-phase3-validation
**Subject:** Validate Phase 3 components
**Description:** Detect quality_low, verify strategy generates 3 variants
**Dependencies:** code-high-m5-improvement-detector, code-med-m5-ollama-model-strategy
**Can run in parallel with:** Nothing (validation task)

---

## Phase 4: Experiment Framework (6 tasks)

### code-med-m5-experiment-model
**Subject:** Create Experiment data model
**Description:** Dataclass and DB schema for experiments
**Dependencies:** None
**Can run in parallel with:** All Phase 4 tasks

### code-med-m5-experiment-assignment
**Subject:** Implement variant assignment logic
**Description:** Hash-based deterministic assignment
**Dependencies:** code-med-m5-experiment-model
**Can run in parallel with:** code-med-m5-statistical-analyzer

### code-med-m5-statistical-analyzer
**Subject:** Implement StatisticalAnalyzer
**Description:** T-test based winner selection
**Dependencies:** None
**Can run in parallel with:** code-med-m5-experiment-assignment

### code-high-m5-experiment-orchestrator
**Subject:** Implement ExperimentOrchestrator (TEST)
**Description:** Main orchestrator for A/B testing
**Dependencies:** code-med-m5-experiment-assignment, code-med-m5-statistical-analyzer, test-med-m5-phase3-validation
**Blocks:** Phase 5
**Spec Required:** Yes (critical component)

### code-med-m5-experiment-db-schema
**Subject:** Add experiment DB schemas
**Description:** experiments and experiment_results tables
**Dependencies:** None
**Can run in parallel with:** All Phase 4 tasks

### test-med-m5-phase4-validation
**Subject:** Validate Phase 4 components
**Description:** Run 4-way experiment (200 executions), verify winner selection
**Dependencies:** code-high-m5-experiment-orchestrator, code-med-m5-experiment-db-schema
**Can run in parallel with:** Nothing (validation task)

---

## Phase 5: Deployment (4 tasks)

### code-med-m5-deployment-db-schema
**Subject:** Add config_deployments table
**Description:** Track deployment history for rollback
**Dependencies:** None
**Can run in parallel with:** All Phase 5 tasks

### code-high-m5-config-deployer
**Subject:** Implement ConfigDeployer (DEPLOY)
**Description:** Deploy winning configs with rollback capability
**Dependencies:** test-med-m5-phase4-validation, code-med-m5-deployment-db-schema
**Blocks:** Phase 6
**Spec Required:** Yes (critical component)

### code-med-m5-rollback-logic
**Subject:** Implement rollback mechanism
**Description:** Revert to previous config on regression
**Dependencies:** code-high-m5-config-deployer
**Can run in parallel with:** Nothing (depends on deployer)

### test-med-m5-phase5-validation
**Subject:** Validate Phase 5 components
**Description:** Deploy winner, run 50 extractions, verify improvement sustained
**Dependencies:** code-med-m5-rollback-logic
**Can run in parallel with:** Nothing (validation task)

---

## Phase 6: Integration (2 tasks)

### code-high-m5-self-improvement-loop
**Subject:** Implement M5SelfImprovementLoop
**Description:** Main orchestrator integrating all components
**Dependencies:** test-med-m5-phase5-validation
**Blocks:** Phase 7
**Spec Required:** Yes (critical component)

### code-med-m5-cli-commands
**Subject:** Add CLI commands for M5
**Description:** analyze, optimize, check-experiments commands
**Dependencies:** code-high-m5-self-improvement-loop
**Can run in parallel with:** Nothing (depends on loop)

---

## Phase 7: Validation (1 task)

### test-high-m5-scenario-validation
**Subject:** Run end-to-end scenario test
**Description:** Complete "Find Best Ollama Model" scenario with 26% quality improvement
**Dependencies:** code-med-m5-cli-commands
**Spec Required:** Yes (critical validation)

---

## Dependency Graph Summary

```
Phase 0 (4 tasks, all parallel)
    ↓
Phase 1 (8 tasks, up to 6 parallel)
    ↓
Phase 2 (5 tasks, up to 3 parallel)
    ↓
Phase 3 (8 tasks, up to 5 parallel)
    ↓
Phase 4 (6 tasks, up to 4 parallel)
    ↓
Phase 5 (4 tasks, up to 2 parallel)
    ↓
Phase 6 (2 tasks, sequential)
    ↓
Phase 7 (1 task)
```

**Total Tasks:** 38
**Critical (high) tasks needing specs:** 7
**Medium tasks:** 26
**Quick tasks:** 4
**Test tasks:** 5

---

## Parallelization Potential

**Peak parallelization points:**
- Phase 0: 4 tasks in parallel
- Phase 1: 6 tasks in parallel (after interface)
- Phase 2: 3 tasks in parallel (after analyzer)
- Phase 3: 5 tasks in parallel (after interface)
- Phase 4: 4 tasks in parallel (after validation)

**Critical path (sequential dependencies):**
1. code-high-m5-metric-collector-interface
2. code-med-m5-metric-registry + code-med-m5-extraction-quality-collector
3. code-med-m5-execution-tracker-integration
4. test-med-m5-phase1-validation
5. code-high-m5-performance-analyzer
6. code-med-m5-baseline-storage
7. test-med-m5-phase2-validation
8. code-high-m5-improvement-detector
9. test-med-m5-phase3-validation
10. code-high-m5-experiment-orchestrator
11. test-med-m5-phase4-validation
12. code-high-m5-config-deployer
13. test-med-m5-phase5-validation
14. code-high-m5-self-improvement-loop
15. code-med-m5-cli-commands
16. test-high-m5-scenario-validation

**Estimated critical path length:** 16 tasks (sequential)
**With parallelization:** Can complete in ~20-25 task completions total

---

## Next Steps

1. Create spec files for 7 critical (high) tasks
2. Create all tasks in coord system with dependencies
3. Start with Phase 0 tasks (all can run in parallel)
