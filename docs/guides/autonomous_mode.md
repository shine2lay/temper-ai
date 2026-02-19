# Getting Started with Autonomous Mode

## Overview

Autonomous mode enables your workflows to learn from their own execution and improve automatically. After each workflow run, the system can:

1. **Mine patterns** from execution history (performance, cost, failures, collaboration)
2. **Propose goals** for improvement based on analysis
3. **Update portfolio** scorecards and recommendations
4. **Apply feedback** by auto-tuning configs based on learned patterns

## Quick Start

### Option 1: CLI Flag

```bash
temper-ai run configs/workflows/my_workflow.yaml --autonomous --show-details
```

### Option 2: YAML Configuration

```yaml
workflow:
  name: my_workflow
  autonomous_loop:
    enabled: true
    learning_enabled: true
    goals_enabled: true
    portfolio_enabled: true
  # ... rest of workflow config
```

## Configuration Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable post-execution analysis |
| `learning_enabled` | bool | `true` | Run pattern mining |
| `goals_enabled` | bool | `true` | Run goal proposal analysis |
| `portfolio_enabled` | bool | `true` | Update portfolio metrics |
| `auto_apply_learning` | bool | `false` | Auto-apply learned recommendations |
| `auto_apply_goals` | bool | `false` | Auto-apply approved goals |
| `auto_apply_min_confidence` | float | `0.8` | Minimum confidence for auto-apply |
| `max_auto_apply_per_run` | int | `5` | Max changes per run |

## How It Works

```
Workflow Executes
       |
       v
PostExecutionOrchestrator.run()
       |
       +---> _run_learning()    --> MiningOrchestrator + RecommendationEngine
       |
       +---> _run_goals()       --> AnalysisOrchestrator + GoalProposer
       |
       +---> _run_portfolio()   --> PortfolioOptimizer + Scorecards
       |
       v
PostExecutionReport (printed as summary table)
```

Each subsystem runs independently. If one fails, others continue (graceful degradation).

## Feedback Application

To enable automatic config changes based on learned patterns:

```yaml
autonomous_loop:
  enabled: true
  auto_apply_learning: true      # Apply high-confidence recommendations
  auto_apply_min_confidence: 0.8 # Only apply if confidence >= 0.8
  max_auto_apply_per_run: 5      # At most 5 changes per run
```

All auto-applied changes are logged to `.meta-autonomous/audit_log.jsonl` for full traceability.

### Manual Feedback Commands

```bash
# View audit trail of auto-applied changes
temper-ai autonomy audit

# Manually apply pending recommendations
temper-ai autonomy apply-pending
```

## Memory Integration

Autonomous mode syncs learned patterns into the memory system:

- **Procedural memory:** Best practices and learned procedures are injected into agent prompts
- **Semantic memory:** Portfolio knowledge graph concepts are available via the `knowledge_graph` memory provider

This means agents automatically benefit from cross-workflow learning without manual configuration.

## Experimentation

Run A/B tests on workflow variants:

```bash
# Create an experiment
temper-ai experiment create --name "temperature_test" --description "Test temp impact" --variants variants.yaml

# Start and monitor
temper-ai experiment start <experiment_id>
temper-ai experiment results <experiment_id>
temper-ai experiment stop <experiment_id>
```

## Safety

- All auto-applied changes go through `GoalSafetyPolicy` (rate limits, autonomy checks)
- Maximum changes per run capped by `max_auto_apply_per_run`
- Full audit trail in JSONL format
- Emergency stop via `temper-ai autonomy emergency-stop --reason "..."` halts all autonomous operations
