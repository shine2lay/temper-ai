# M5 CLI Guide

Complete guide to using the M5 Self-Improvement command-line interface.

## Installation

The M5 CLI is installed with the project. The `m5` command is available in the `bin/` directory.

### Add to PATH (Optional)

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$PATH:/path/to/meta-autonomous-framework/bin"
```

## Quick Start

```bash
# Check system health
m5 health

# Run improvement iteration for an agent
m5 run my_agent

# Check status
m5 status my_agent

# View metrics
m5 metrics my_agent
```

---

## Commands Reference

### m5 run

Run complete improvement iteration (all 5 phases).

**Usage:**
```bash
m5 run <agent-name> [--config CONFIG_FILE]
```

**Arguments:**
- `agent-name` - Name of agent to improve
- `--config` - Optional path to JSON config file

**Example:**
```bash
# Run with default config
m5 run product_extractor

# Run with custom config
m5 run product_extractor --config configs/aggressive.json
```

**Output:**
```
🔄 Starting M5 improvement iteration for: product_extractor

✅ Iteration 1 completed successfully!
   Phases: detect → analyze → strategy → experiment → deploy
   Duration: 45.2s
   Deployed: deploy-abc123xyz
   Rollback monitoring: enabled
```

---

### m5 analyze

Analyze agent performance (Phase 2 only - no deployment).

**Usage:**
```bash
m5 analyze <agent-name> [--window HOURS]
```

**Arguments:**
- `agent-name` - Name of agent to analyze
- `--window` - Analysis window in hours (default: 168 = 7 days)

**Example:**
```bash
# Analyze last week
m5 analyze product_extractor

# Analyze last 2 weeks
m5 analyze product_extractor --window 336
```

**Output:**
```
📊 Analyzing performance for: product_extractor
   Window: 168 hours (7.0 days)

📈 Performance Analysis:
   Total executions: 523
   Time window: 2026-01-25 16:35 to 2026-02-01 16:35

   Metrics:
   - quality_score: 0.7842 (±0.0521)
   - cost_usd: 0.0234 (±0.0012)
   - duration_seconds: 42.5 (±8.3)
```

---

### m5 optimize

Alias for `m5 run`. More intuitive name for running improvement iterations.

**Usage:**
```bash
m5 optimize <agent-name> [--config CONFIG_FILE]
```

**Example:**
```bash
m5 optimize product_extractor
```

---

### m5 status

Show current loop status for an agent.

**Usage:**
```bash
m5 status <agent-name>
```

**Example:**
```bash
m5 status product_extractor
```

**Output:**
```
📋 M5 Loop Status: product_extractor

   Current phase: deploy
   Status: running
   Iteration: 3
   Started: 2026-02-01T10:30:00+00:00
   Updated: 2026-02-01T16:35:42+00:00

   Health: healthy
   Total completed: 2
```

---

### m5 metrics

Show aggregated metrics for an agent.

**Usage:**
```bash
m5 metrics <agent-name>
```

**Example:**
```bash
m5 metrics product_extractor
```

**Output:**
```
📊 M5 Metrics: product_extractor

   Iteration Metrics:
   - Total iterations: 5
   - Successful: 4
   - Failed: 1
   - Success rate: 80.0%
   - Avg duration: 127.3s

   Improvement Metrics:
   - Experiments run: 4
   - Successful deployments: 3
   - Rollbacks: 1

   Phase Success Rates:
   - detect: 100.0%
   - analyze: 100.0%
   - strategy: 100.0%
   - experiment: 80.0%
   - deploy: 75.0%

   Last iteration: 2026-02-01T16:35:42+00:00
```

---

### m5 pause

Pause loop execution for an agent.

**Usage:**
```bash
m5 pause <agent-name>
```

**Example:**
```bash
m5 pause product_extractor
```

**Output:**
```
⏸️  Pausing M5 loop for: product_extractor
   ✅ Loop paused
```

**Use Case:**
- Maintenance window
- Manual investigation
- Configuration changes

---

### m5 resume

Resume paused loop.

**Usage:**
```bash
m5 resume <agent-name>
```

**Example:**
```bash
m5 resume product_extractor
```

**Output:**
```
▶️  Resuming M5 loop for: product_extractor
   ✅ Loop resumed
```

---

### m5 reset

Reset all loop state for an agent (with confirmation).

**Usage:**
```bash
m5 reset <agent-name>
```

**Example:**
```bash
m5 reset product_extractor
```

**Output:**
```
⚠️  Reset all state for product_extractor? This cannot be undone. [y/N]: y
🔄 Resetting M5 loop state for: product_extractor
   ✅ State reset
```

**Warning:** This deletes all state and metrics. Cannot be undone.

---

### m5 health

Check M5 system health.

**Usage:**
```bash
m5 health
```

**Example:**
```bash
m5 health
```

**Output:**
```
🏥 M5 System Health Check

   Overall status: HEALTHY
   Timestamp: 2026-02-01T16:35:42+00:00

   Components:
   ✅ coordination_db: healthy
   ✅ observability_db: healthy
   ✅ configuration: healthy
```

**Exit Codes:**
- `0` - Healthy
- `1` - Unhealthy or degraded

---

### m5 check-experiments

Check experiment status for an agent.

**Usage:**
```bash
m5 check-experiments <agent-name>
```

**Example:**
```bash
m5 check-experiments product_extractor
```

**Output:**
```
🧪 Checking experiments for: product_extractor

   Recent Experiments:

   Experiment: exp-abc123
   - Status: completed
   - Created: 2026-02-01T10:30:00+00:00
   - Winner: variant_1

   Experiment: exp-def456
   - Status: running
   - Created: 2026-02-01T08:15:00+00:00
```

---

### m5 list-agents

List all agents with M5 loop state.

**Usage:**
```bash
m5 list-agents
```

**Example:**
```bash
m5 list-agents
```

**Output:**
```
📋 Agents with M5 Loop State

   Agent                          Phase           Status          Iteration
   ------------------------------ --------------- --------------- ----------
   product_extractor              deploy          running         3
   code_reviewer                  experiment      running         1
   sentiment_analyzer             analyze         completed       5
```

---

## Configuration Files

Create custom configuration files in JSON format.

### Example Config

**configs/aggressive.json:**
```json
{
  "detection_window_hours": 336,
  "min_executions_for_detection": 100,
  "target_samples_per_variant": 100,
  "experiment_timeout_hours": 120,
  "enable_auto_deploy": true,
  "enable_auto_rollback": true,
  "rollback_quality_drop_pct": 5.0,
  "max_retries_per_phase": 5
}
```

**Usage:**
```bash
m5 run my_agent --config configs/aggressive.json
```

### Config Parameters

See `docs/M5_LOOP_IMPLEMENTATION.md` for complete configuration reference.

Key parameters:
- `detection_window_hours` - Time window for detection (default: 168)
- `target_samples_per_variant` - Samples per variant (default: 50)
- `experiment_timeout_hours` - Max experiment duration (default: 72)
- `enable_auto_deploy` - Auto-deploy winners (default: true)
- `enable_auto_rollback` - Auto-rollback on regression (default: true)

---

## Common Workflows

### Daily Improvement Check

```bash
#!/bin/bash
# daily-improve.sh

AGENTS=("product_extractor" "code_reviewer" "sentiment_analyzer")

for agent in "${AGENTS[@]}"; do
    echo "Checking $agent..."

    # Run optimization
    m5 optimize "$agent" || echo "Failed for $agent"

    # Show metrics
    m5 metrics "$agent"

    echo "---"
done
```

### Health Monitoring

```bash
#!/bin/bash
# health-check.sh

# Check system health
if ! m5 health; then
    echo "ALERT: M5 system unhealthy!"
    # Send alert...
fi

# Check all agents
m5 list-agents
```

### Performance Analysis

```bash
#!/bin/bash
# analyze-all.sh

# Analyze all agents
for agent in $(m5 list-agents | tail -n +4 | awk '{print $1}'); do
    echo "=== $agent ==="
    m5 analyze "$agent" --window 336
    echo
done
```

---

## Exit Codes

All commands use standard exit codes:

- `0` - Success
- `1` - Failure or error

**Example:**
```bash
if m5 run my_agent; then
    echo "Success!"
else
    echo "Failed!"
fi
```

---

## Troubleshooting

### Command Not Found

```bash
# Add to PATH
export PATH="$PATH:/path/to/meta-autonomous-framework/bin"

# Or use full path
/path/to/meta-autonomous-framework/bin/m5 health
```

### Database Not Initialized

The CLI automatically initializes databases on first use. If you see database errors:

```bash
# Check health
m5 health

# Reset state if needed
m5 reset my_agent
```

### Permission Denied

```bash
# Make script executable
chmod +x bin/m5
```

### Import Errors

Ensure virtual environment is activated:

```bash
source .venv/bin/activate
m5 health
```

---

## Advanced Usage

### Scripting

```python
#!/usr/bin/env python3
# custom-workflow.py

import subprocess
import json

def run_m5(agent, config=None):
    """Run M5 iteration."""
    cmd = ["bin/m5", "run", agent]
    if config:
        cmd.extend(["--config", config])

    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0

# Run improvements
agents = ["agent1", "agent2", "agent3"]
for agent in agents:
    if run_m5(agent):
        print(f"✓ {agent} improved")
    else:
        print(f"✗ {agent} failed")
```

### Monitoring Integration

```bash
# Prometheus metrics export (example)
m5 metrics my_agent | \
    grep "Success rate" | \
    awk '{print "m5_success_rate{agent=\"my_agent\"} " $3}' | \
    curl -X POST http://pushgateway:9091/metrics/job/m5
```

---

## See Also

- `docs/M5_LOOP_IMPLEMENTATION.md` - Loop implementation details
- `docs/M5_MODULAR_ARCHITECTURE.md` - M5 system architecture
- `temper_ai/self_improvement/loop/config.py` - Configuration options

---

## Support

For issues or questions:
- Check `m5 health` first
- Review logs in `~/.claude/logs/`
- Check state with `m5 status <agent>`
