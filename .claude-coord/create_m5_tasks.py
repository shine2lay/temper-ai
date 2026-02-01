#!/usr/bin/env python3
"""
Create M5 Milestone 1 tasks using Python API.
More robust than bash script - handles errors gracefully.
"""

import sys
import os

# Add coord_service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from coord_service.client import CoordinationClient

# Task definitions
TASKS = [
    # Phase 0: Foundation (already created)
    # Phase 1: Agent + Quality Metric
    {
        "id": "code-med-m5-metric-registry",
        "subject": "Implement MetricRegistry",
        "description": "Registry for metric collectors with registration and collection",
        "depends_on": ["code-high-m5-metric-collector-interface"]
    },
    {
        "id": "code-med-m5-extraction-quality-collector",
        "subject": "Build ExtractionQualityCollector",
        "description": "Collector that measures field-level accuracy for structured extraction",
        "depends_on": ["code-high-m5-metric-collector-interface"]
    },
    {
        "id": "code-med-m5-ollama-client",
        "subject": "Create OllamaClient wrapper",
        "description": "Wrapper for Ollama API with generate() method",
        "depends_on": ["code-quick-m5-ollama-setup"]
    },
    {
        "id": "code-med-m5-product-extractor",
        "subject": "Implement ProductExtractorAgent",
        "description": "Agent that extracts structured product info using Ollama",
        "depends_on": ["code-med-m5-ollama-client", "code-quick-m5-data-model-config"]
    },
    {
        "id": "code-med-m5-test-dataset",
        "subject": "Create product extraction test dataset",
        "description": "50 product descriptions with ground truth JSON",
        "depends_on": []
    },
    {
        "id": "code-med-m5-execution-tracker-integration",
        "subject": "Integrate MetricRegistry into ExecutionTracker",
        "description": "Update ExecutionTracker to call metric collectors after execution",
        "depends_on": ["code-med-m5-metric-registry", "code-med-m5-extraction-quality-collector"]
    },
    {
        "id": "test-med-m5-phase1-validation",
        "subject": "Validate Phase 1 components",
        "description": "Run agent 50 times, verify quality scores stored in DB",
        "depends_on": ["code-med-m5-execution-tracker-integration", "code-med-m5-product-extractor", "code-med-m5-test-dataset"]
    },

    # Phase 2: Performance Analysis
    {
        "id": "code-med-m5-performance-profile-model",
        "subject": "Create AgentPerformanceProfile model",
        "description": "Dataclass for performance profile with metrics aggregation",
        "depends_on": []
    },
    {
        "id": "code-high-m5-performance-analyzer",
        "subject": "Implement PerformanceAnalyzer (WATCH)",
        "description": "Core analyzer with SQL-based metric aggregation",
        "depends_on": ["code-med-m5-performance-profile-model", "test-med-m5-phase1-validation"]
    },
    {
        "id": "code-med-m5-baseline-storage",
        "subject": "Add baseline storage logic",
        "description": "Store and retrieve baseline performance profiles",
        "depends_on": ["code-high-m5-performance-analyzer"]
    },
    {
        "id": "code-med-m5-performance-comparison",
        "subject": "Add performance comparison logic",
        "description": "Compare current vs baseline profiles",
        "depends_on": ["code-high-m5-performance-analyzer"]
    },
    {
        "id": "test-med-m5-phase2-validation",
        "subject": "Validate Phase 2 components",
        "description": "Run 100 extractions, analyze performance, create baseline",
        "depends_on": ["code-med-m5-baseline-storage", "code-med-m5-performance-comparison"]
    },

    # Phase 3: Problem Detection + Strategy
    {
        "id": "code-med-m5-problem-detection",
        "subject": "Implement problem detection logic",
        "description": "Detect quality_low, cost_too_high, too_slow problems",
        "depends_on": ["test-med-m5-phase2-validation"]
    },
    {
        "id": "code-high-m5-strategy-interface",
        "subject": "Define ImprovementStrategy interface",
        "description": "Abstract base class for strategies (Modularity Point #2)",
        "depends_on": []
    },
    {
        "id": "code-med-m5-strategy-registry",
        "subject": "Implement StrategyRegistry",
        "description": "Registry for improvement strategies",
        "depends_on": ["code-high-m5-strategy-interface"]
    },
    {
        "id": "code-med-m5-model-registry",
        "subject": "Create ModelRegistry for Ollama models",
        "description": "Registry of available Ollama models with metadata",
        "depends_on": []
    },
    {
        "id": "code-med-m5-ollama-model-strategy",
        "subject": "Implement OllamaModelSelectionStrategy",
        "description": "Strategy that generates model variant configs",
        "depends_on": ["code-high-m5-strategy-interface", "code-med-m5-model-registry"]
    },
    {
        "id": "code-med-m5-improvement-proposal-model",
        "subject": "Create ImprovementProposal model",
        "description": "Dataclass for improvement proposals",
        "depends_on": []
    },
    {
        "id": "code-high-m5-improvement-detector",
        "subject": "Implement ImprovementDetector (DETECT)",
        "description": "Main detector that orchestrates problem detection and strategy invocation",
        "depends_on": ["code-med-m5-problem-detection", "code-med-m5-strategy-registry", "code-med-m5-improvement-proposal-model"]
    },
    {
        "id": "test-med-m5-phase3-validation",
        "subject": "Validate Phase 3 components",
        "description": "Detect quality_low, verify strategy generates 3 variants",
        "depends_on": ["code-high-m5-improvement-detector", "code-med-m5-ollama-model-strategy"]
    },

    # Phase 4: Experiment Framework
    {
        "id": "code-med-m5-experiment-model",
        "subject": "Create Experiment data model",
        "description": "Dataclass and DB schema for experiments",
        "depends_on": []
    },
    {
        "id": "code-med-m5-experiment-assignment",
        "subject": "Implement variant assignment logic",
        "description": "Hash-based deterministic assignment",
        "depends_on": ["code-med-m5-experiment-model"]
    },
    {
        "id": "code-med-m5-statistical-analyzer",
        "subject": "Implement StatisticalAnalyzer",
        "description": "T-test based winner selection",
        "depends_on": []
    },
    {
        "id": "code-high-m5-experiment-orchestrator",
        "subject": "Implement ExperimentOrchestrator (TEST)",
        "description": "Main orchestrator for A/B testing",
        "depends_on": ["code-med-m5-experiment-assignment", "code-med-m5-statistical-analyzer", "test-med-m5-phase3-validation"]
    },
    {
        "id": "code-med-m5-experiment-db-schema",
        "subject": "Add experiment DB schemas",
        "description": "experiments and experiment_results tables",
        "depends_on": []
    },
    {
        "id": "test-med-m5-phase4-validation",
        "subject": "Validate Phase 4 components",
        "description": "Run 4-way experiment (200 executions), verify winner selection",
        "depends_on": ["code-high-m5-experiment-orchestrator", "code-med-m5-experiment-db-schema"]
    },

    # Phase 5: Deployment
    {
        "id": "code-med-m5-deployment-db-schema",
        "subject": "Add config_deployments table",
        "description": "Track deployment history for rollback",
        "depends_on": []
    },
    {
        "id": "code-high-m5-config-deployer",
        "subject": "Implement ConfigDeployer (DEPLOY)",
        "description": "Deploy winning configs with rollback capability",
        "depends_on": ["test-med-m5-phase4-validation", "code-med-m5-deployment-db-schema"]
    },
    {
        "id": "code-med-m5-rollback-logic",
        "subject": "Implement rollback mechanism",
        "description": "Revert to previous config on regression",
        "depends_on": ["code-high-m5-config-deployer"]
    },
    {
        "id": "test-med-m5-phase5-validation",
        "subject": "Validate Phase 5 components",
        "description": "Deploy winner, run 50 extractions, verify improvement sustained",
        "depends_on": ["code-med-m5-rollback-logic"]
    },

    # Phase 6: Integration
    {
        "id": "code-high-m5-self-improvement-loop",
        "subject": "Implement M5SelfImprovementLoop",
        "description": "Main orchestrator integrating all components",
        "depends_on": ["test-med-m5-phase5-validation"]
    },
    {
        "id": "code-med-m5-cli-commands",
        "subject": "Add CLI commands for M5",
        "description": "analyze, optimize, check-experiments commands",
        "depends_on": ["code-high-m5-self-improvement-loop"]
    },

    # Phase 7: Validation
    {
        "id": "test-high-m5-scenario-validation",
        "subject": "Run end-to-end scenario test",
        "description": "Complete 'Find Best Ollama Model' scenario with 26% quality improvement",
        "depends_on": ["code-med-m5-cli-commands"]
    },
]


def main():
    project_root = "/home/shinelay/meta-autonomous-framework"
    client = CoordinationClient(project_root)

    created = 0
    skipped = 0
    failed = 0

    print("Creating M5 Milestone 1 tasks via Python API...")
    print("=" * 60)

    for task in TASKS:
        task_id = task["id"]

        try:
            # Check if task exists
            try:
                existing = client.call('task_get', {'task_id': task_id})
                if existing:
                    print(f"  ⏭  Skipping {task_id} (already exists)")
                    skipped += 1
                    continue
            except:
                pass  # Task doesn't exist, create it

            # Create task
            params = {
                'task_id': task_id,
                'subject': task['subject'],
                'description': task['description']
            }

            # Add dependencies if any (pass as list, not string)
            if task['depends_on']:
                params['depends_on'] = task['depends_on']

            client.call('task_create', params)
            print(f"  ✓  Created {task_id}")
            created += 1

        except Exception as e:
            print(f"  ✗  Failed {task_id}: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Summary:")
    print(f"  Created: {created}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Total: {created + skipped + failed} / {len(TASKS)}")

    if failed == 0:
        print("\n✅ All tasks created successfully!")
    else:
        print(f"\n⚠️  {failed} tasks failed - review errors above")
        sys.exit(1)


if __name__ == "__main__":
    main()
