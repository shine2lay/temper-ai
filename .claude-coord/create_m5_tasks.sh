#!/bin/bash
# Create all M5 Milestone 1 tasks with dependencies

set -e  # Exit on error

COORD=".claude-coord/bin/coord"

# Helper function to create task only if it doesn't exist
create_task_if_not_exists() {
    local task_id="$1"
    shift

    # Check if task already exists
    if $COORD task-get "$task_id" &>/dev/null; then
        echo "  ⏭ Skipping $task_id (already exists)"
        return 0
    fi

    # Create the task
    create_task_if_not_exists "$task_id" "$@"
}

echo "Creating M5 Milestone 1 tasks..."
echo "================================"

# ============================================
# PHASE 0: Foundation (4 tasks, all parallel)
# ============================================
echo ""
echo "Phase 0: Foundation"

create_task_if_not_exists code-quick-m5-ollama-setup \
    "Setup Ollama and pull models" \
    "Install Ollama, pull test models (phi3:mini, llama3.1:8b, mistral:7b, qwen2.5:32b)"

create_task_if_not_exists code-quick-m5-db-schema-custom-metrics \
    "Add custom_metrics table schema" \
    "Create SQL migration for custom_metrics table"

create_task_if_not_exists code-quick-m5-data-model-config \
    "Create AgentConfig data model" \
    "Python dataclass for agent configuration"

create_task_if_not_exists code-quick-m5-data-model-execution \
    "Create AgentExecution data model" \
    "Python dataclass for execution tracking (may already exist in M1)"

# ============================================
# PHASE 1: Agent + Quality Metric (8 tasks)
# ============================================
echo ""
echo "Phase 1: Agent + Quality Metric"

# Foundation interface (blocks others)
create_task_if_not_exists code-high-m5-metric-collector-interface \
    "Define MetricCollector interface" \
    "Abstract base class for metric collectors (Modularity Point #1)"

# Parallel after interface
create_task_if_not_exists code-med-m5-metric-registry \
    "Implement MetricRegistry" \
    "Registry for metric collectors with registration and collection" \
    --depends-on code-high-m5-metric-collector-interface

create_task_if_not_exists code-med-m5-extraction-quality-collector \
    "Build ExtractionQualityCollector" \
    "Collector that measures field-level accuracy for structured extraction" \
    --depends-on code-high-m5-metric-collector-interface

create_task_if_not_exists code-med-m5-ollama-client \
    "Create OllamaClient wrapper" \
    "Wrapper for Ollama API with generate() method" \
    --depends-on code-quick-m5-ollama-setup

create_task_if_not_exists code-med-m5-product-extractor \
    "Implement ProductExtractorAgent" \
    "Agent that extracts structured product info using Ollama" \
    --depends-on "code-med-m5-ollama-client,code-quick-m5-data-model-config"

create_task_if_not_exists code-med-m5-test-dataset \
    "Create product extraction test dataset" \
    "50 product descriptions with ground truth JSON"

# Integration (depends on registry + collector)
create_task_if_not_exists code-med-m5-execution-tracker-integration \
    "Integrate MetricRegistry into ExecutionTracker" \
    "Update ExecutionTracker to call metric collectors after execution" \
    --depends-on "code-med-m5-metric-registry,code-med-m5-extraction-quality-collector"

# Validation (depends on integration + agent + dataset)
create_task_if_not_exists test-med-m5-phase1-validation \
    "Validate Phase 1 components" \
    "Run agent 50 times, verify quality scores stored in DB" \
    --depends-on "code-med-m5-execution-tracker-integration,code-med-m5-product-extractor,code-med-m5-test-dataset"

# ============================================
# PHASE 2: Performance Analysis (5 tasks)
# ============================================
echo ""
echo "Phase 2: Performance Analysis"

create_task_if_not_exists code-med-m5-performance-profile-model \
    "Create AgentPerformanceProfile model" \
    "Dataclass for performance profile with metrics aggregation"

create_task_if_not_exists code-high-m5-performance-analyzer \
    "Implement PerformanceAnalyzer (WATCH)" \
    "Core analyzer with SQL-based metric aggregation" \
    --depends-on "code-med-m5-performance-profile-model,test-med-m5-phase1-validation"

create_task_if_not_exists code-med-m5-baseline-storage \
    "Add baseline storage logic" \
    "Store and retrieve baseline performance profiles" \
    --depends-on code-high-m5-performance-analyzer

create_task_if_not_exists code-med-m5-performance-comparison \
    "Add performance comparison logic" \
    "Compare current vs baseline profiles" \
    --depends-on code-high-m5-performance-analyzer

create_task_if_not_exists test-med-m5-phase2-validation \
    "Validate Phase 2 components" \
    "Run 100 extractions, analyze performance, create baseline" \
    --depends-on "code-med-m5-baseline-storage,code-med-m5-performance-comparison"

# ============================================
# PHASE 3: Problem Detection + Strategy (8 tasks)
# ============================================
echo ""
echo "Phase 3: Problem Detection + Strategy"

create_task_if_not_exists code-med-m5-problem-detection \
    "Implement problem detection logic" \
    "Detect quality_low, cost_too_high, too_slow problems" \
    --depends-on test-med-m5-phase2-validation

create_task_if_not_exists code-high-m5-strategy-interface \
    "Define ImprovementStrategy interface" \
    "Abstract base class for strategies (Modularity Point #2)"

create_task_if_not_exists code-med-m5-strategy-registry \
    "Implement StrategyRegistry" \
    "Registry for improvement strategies" \
    --depends-on code-high-m5-strategy-interface

create_task_if_not_exists code-med-m5-model-registry \
    "Create ModelRegistry for Ollama models" \
    "Registry of available Ollama models with metadata"

create_task_if_not_exists code-med-m5-ollama-model-strategy \
    "Implement OllamaModelSelectionStrategy" \
    "Strategy that generates model variant configs" \
    --depends-on "code-high-m5-strategy-interface,code-med-m5-model-registry"

create_task_if_not_exists code-med-m5-improvement-proposal-model \
    "Create ImprovementProposal model" \
    "Dataclass for improvement proposals"

create_task_if_not_exists code-high-m5-improvement-detector \
    "Implement ImprovementDetector (DETECT)" \
    "Main detector that orchestrates problem detection and strategy invocation" \
    --depends-on "code-med-m5-problem-detection,code-med-m5-strategy-registry,code-med-m5-improvement-proposal-model"

create_task_if_not_exists test-med-m5-phase3-validation \
    "Validate Phase 3 components" \
    "Detect quality_low, verify strategy generates 3 variants" \
    --depends-on "code-high-m5-improvement-detector,code-med-m5-ollama-model-strategy"

# ============================================
# PHASE 4: Experiment Framework (6 tasks)
# ============================================
echo ""
echo "Phase 4: Experiment Framework"

create_task_if_not_exists code-med-m5-experiment-model \
    "Create Experiment data model" \
    "Dataclass and DB schema for experiments"

create_task_if_not_exists code-med-m5-experiment-assignment \
    "Implement variant assignment logic" \
    "Hash-based deterministic assignment" \
    --depends-on code-med-m5-experiment-model

create_task_if_not_exists code-med-m5-statistical-analyzer \
    "Implement StatisticalAnalyzer" \
    "T-test based winner selection"

create_task_if_not_exists code-high-m5-experiment-orchestrator \
    "Implement ExperimentOrchestrator (TEST)" \
    "Main orchestrator for A/B testing" \
    --depends-on "code-med-m5-experiment-assignment,code-med-m5-statistical-analyzer,test-med-m5-phase3-validation"

create_task_if_not_exists code-med-m5-experiment-db-schema \
    "Add experiment DB schemas" \
    "experiments and experiment_results tables"

create_task_if_not_exists test-med-m5-phase4-validation \
    "Validate Phase 4 components" \
    "Run 4-way experiment (200 executions), verify winner selection" \
    --depends-on "code-high-m5-experiment-orchestrator,code-med-m5-experiment-db-schema"

# ============================================
# PHASE 5: Deployment (4 tasks)
# ============================================
echo ""
echo "Phase 5: Deployment"

create_task_if_not_exists code-med-m5-deployment-db-schema \
    "Add config_deployments table" \
    "Track deployment history for rollback"

create_task_if_not_exists code-high-m5-config-deployer \
    "Implement ConfigDeployer (DEPLOY)" \
    "Deploy winning configs with rollback capability" \
    --depends-on "test-med-m5-phase4-validation,code-med-m5-deployment-db-schema"

create_task_if_not_exists code-med-m5-rollback-logic \
    "Implement rollback mechanism" \
    "Revert to previous config on regression" \
    --depends-on code-high-m5-config-deployer

create_task_if_not_exists test-med-m5-phase5-validation \
    "Validate Phase 5 components" \
    "Deploy winner, run 50 extractions, verify improvement sustained" \
    --depends-on code-med-m5-rollback-logic

# ============================================
# PHASE 6: Integration (2 tasks)
# ============================================
echo ""
echo "Phase 6: Integration"

create_task_if_not_exists code-high-m5-self-improvement-loop \
    "Implement M5SelfImprovementLoop" \
    "Main orchestrator integrating all components" \
    --depends-on test-med-m5-phase5-validation

create_task_if_not_exists code-med-m5-cli-commands \
    "Add CLI commands for M5" \
    "analyze, optimize, check-experiments commands" \
    --depends-on code-high-m5-self-improvement-loop

# ============================================
# PHASE 7: Validation (1 task)
# ============================================
echo ""
echo "Phase 7: Validation"

create_task_if_not_exists test-high-m5-scenario-validation \
    "Run end-to-end scenario test" \
    "Complete 'Find Best Ollama Model' scenario with 26% quality improvement" \
    --depends-on code-med-m5-cli-commands

# ============================================
# Done!
# ============================================
echo ""
echo "================================"
echo "✅ Created 38 M5 tasks!"
echo "================================"
echo ""
echo "View available tasks:"
echo "  $COORD task-list"
echo ""
echo "View all tasks (including blocked):"
echo "  $COORD task-list --all"
echo ""
echo "View blocked tasks:"
echo "  $COORD task-blocked"
echo ""
echo "Start working:"
echo "  $COORD task-claim \$CLAUDE_AGENT_ID <task-id>"
