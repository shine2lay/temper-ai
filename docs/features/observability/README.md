# Observability Features

Documentation for execution tracking, visualization, and analytics (M1).

## Features

### [Gantt Visualization](./GANTT_VISUALIZATION.md)
**Purpose:** Timeline visualization for workflow execution analysis

**Topics Covered:**
- Gantt chart generation from execution traces
- Timeline visualization of stages and agents
- Parallel execution visualization
- Performance bottleneck identification
- Export formats (PNG, HTML, interactive)

**Key Capabilities:**
- **Hierarchical View**: Workflow → Stages → Agents → LLM/Tool calls
- **Timing Analysis**: Start/end times, duration, overlaps
- **Performance Insights**: Identify slow stages, parallelization opportunities
- **Interactive Exploration**: Hover for details, zoom, filter
- **Export Options**: Save charts for reporting

**Use Cases:**
- Debugging slow workflows
- Identifying parallelization opportunities
- Performance reporting and dashboards
- Understanding execution flow
- Capacity planning

---

## Architecture

### Observability Stack
```
Execution
    ↓
ExecutionTracker (in-memory)
    ↓
Database (SQLite)
    ↓
Query Layer (SQLAlchemy)
    ↓
Visualization (Console, Gantt, Custom)
```

### Data Model
```
WorkflowExecution
  ├─ workflow_id (UUID)
  ├─ status (running|completed|failed)
  ├─ start_time, end_time
  ├─ total_cost, total_tokens
  └─ stages []
       └─ StageExecution
            ├─ stage_name
            ├─ start_time, end_time
            └─ agent_executions []
                 └─ AgentExecution
                      ├─ agent_type
                      ├─ llm_calls []
                      └─ tool_executions []
```

### Tracking Points
Every execution event captured:
- Workflow start/end
- Stage start/end
- Agent start/end
- LLM call (request, response, tokens, cost)
- Tool execution (parameters, result, duration)
- Errors and exceptions
- Collaboration events (votes, consensus, conflicts)

---

## Configuration

### Basic Observability
```yaml
# configs/system_config.yaml
observability:
  enabled: true
  database:
    path: "data/executions.db"
    echo: false  # SQL logging

  console:
    enabled: true
    verbosity: standard  # minimal|standard|detailed
```

### Advanced Tracking
```yaml
observability:
  tracking:
    llm_calls: true
    tool_executions: true
    token_usage: true
    cost_tracking: true
    collaboration_events: true

  console:
    colors: true
    show_timing: true
    show_tokens: true
    show_cost: true

  retention:
    max_age_days: 90
    auto_cleanup: true
```

### Gantt Configuration
```yaml
observability:
  gantt:
    enabled: true
    output_dir: "reports/gantt"
    format: png  # png|html|both
    max_depth: 3  # workflow|stage|agent|llm_tool
    show_labels: true
    color_by: agent_type  # status|agent_type|duration
```

---

## Usage

### Console Visualization
```python
from temper_ai.observability.tracker import ExecutionTracker
from temper_ai.observability.console import print_workflow_tree

tracker = ExecutionTracker()
workflow_id = tracker.start_workflow(...)

# Execute workflow...

# Print execution tree
with get_session() as session:
    workflow = session.get(WorkflowExecution, workflow_id)
    print_workflow_tree(workflow, verbosity="detailed")
```

Output:
```
📊 Workflow: research_workflow (45.2s, $0.05, 1.2k tokens)
├─ 🏃 Stage: gather (30.1s)
│  ├─ 🤖 Agent: researcher_web (15.3s)
│  │  ├─ 🧠 LLM Call: llama3.2:3b (12.1s, 800 tokens, $0.02)
│  │  └─ 🔧 Tool: web_scraper (3.2s)
│  └─ 🤖 Agent: researcher_academic (14.8s)
│     ├─ 🧠 LLM Call: llama3.2:3b (11.9s, 750 tokens, $0.02)
│     └─ 🔧 Tool: file_reader (2.9s)
└─ 🏃 Stage: synthesize (15.1s)
   └─ 🤖 Agent: synthesizer (15.1s)
      └─ 🧠 LLM Call: llama3.2:3b (15.0s, 1k tokens, $0.03)
```

### Gantt Chart Generation
```python
from temper_ai.observability.visualization import generate_gantt

with get_session() as session:
    workflow = session.get(WorkflowExecution, workflow_id)
    generate_gantt(
        workflow,
        output_path="reports/workflow_timeline.png",
        show_agents=True,
        show_llm_calls=True
    )
```

### Querying Execution Data
```python
from temper_ai.observability.database import get_session
from temper_ai.observability.models import WorkflowExecution, AgentExecution
from sqlalchemy import func

with get_session() as session:
    # Get all workflows from last 7 days
    recent = session.query(WorkflowExecution).filter(
        WorkflowExecution.start_time >= datetime.now() - timedelta(days=7)
    ).all()

    # Calculate total cost
    total_cost = session.query(
        func.sum(WorkflowExecution.total_cost)
    ).scalar()

    # Find slowest agents
    slow_agents = session.query(
        AgentExecution.agent_type,
        func.avg(AgentExecution.duration).label("avg_duration")
    ).group_by(AgentExecution.agent_type).order_by("avg_duration DESC").all()
```

---

## Performance Insights

### Identifying Bottlenecks
Gantt charts reveal:
- **Sequential vs Parallel**: Which stages could be parallelized
- **Slow Agents**: Which agents take longest
- **LLM vs Tool Time**: Time spent in LLM calls vs tool executions
- **Idle Time**: Gaps where agents are waiting

### Optimization Opportunities
```
Before Optimization (Sequential):
[Agent1]████████████████
        [Agent2]████████████████
                [Agent3]████████████████
Total: 45s

After Optimization (Parallel):
[Agent1]████████████████
[Agent2]████████████████
[Agent3]████████████████
Total: 15s (3x faster)
```

### Cost Analysis
Track costs across dimensions:
- **Per Workflow**: Total cost per workflow run
- **Per Agent Type**: Which agents cost most
- **Per LLM Provider**: Compare provider costs
- **Over Time**: Trend analysis

---

## Database Schema

### Tables
```sql
CREATE TABLE workflow_executions (
    workflow_id TEXT PRIMARY KEY,
    config_hash TEXT,
    status TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    total_tokens INTEGER,
    total_cost REAL
);

CREATE TABLE stage_executions (
    stage_id TEXT PRIMARY KEY,
    workflow_id TEXT,
    stage_name TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    FOREIGN KEY (workflow_id) REFERENCES workflow_executions
);

CREATE TABLE agent_executions (
    agent_id TEXT PRIMARY KEY,
    stage_id TEXT,
    agent_type TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    FOREIGN KEY (stage_id) REFERENCES stage_executions
);

CREATE TABLE llm_calls (
    call_id TEXT PRIMARY KEY,
    agent_id TEXT,
    provider TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost REAL,
    duration REAL,
    FOREIGN KEY (agent_id) REFERENCES agent_executions
);

CREATE TABLE tool_executions (
    execution_id TEXT PRIMARY KEY,
    agent_id TEXT,
    tool_name TEXT,
    parameters TEXT,
    result TEXT,
    duration REAL,
    FOREIGN KEY (agent_id) REFERENCES agent_executions
);
```

### Indexes
```sql
CREATE INDEX idx_workflow_start_time ON workflow_executions(start_time);
CREATE INDEX idx_stage_workflow_id ON stage_executions(workflow_id);
CREATE INDEX idx_agent_stage_id ON agent_executions(stage_id);
CREATE INDEX idx_llm_agent_id ON llm_calls(agent_id);
CREATE INDEX idx_tool_agent_id ON tool_executions(agent_id);
```

---

## Examples

### Basic Execution Tracking
```python
from temper_ai.observability.tracker import ExecutionTracker

tracker = ExecutionTracker()

# Track workflow
workflow_id = tracker.start_workflow(config)

# Track stage
stage_id = tracker.start_stage(workflow_id, "research")

# Track agent
agent_id = tracker.start_agent(stage_id, "researcher")

# Track LLM call
llm_call_id = tracker.start_llm_call(agent_id, provider="ollama")
tracker.end_llm_call(llm_call_id, response, tokens=800, cost=0.02)

# Track tool execution
tool_id = tracker.start_tool(agent_id, "web_scraper")
tracker.end_tool(tool_id, result)

# Complete
tracker.end_agent(agent_id)
tracker.end_stage(stage_id)
tracker.end_workflow(workflow_id)
```

### Performance Analysis
```python
from temper_ai.observability.analytics import analyze_workflow

analysis = analyze_workflow(workflow_id)

print(f"Total duration: {analysis.total_duration}s")
print(f"LLM time: {analysis.llm_time}s ({analysis.llm_percentage}%)")
print(f"Tool time: {analysis.tool_time}s ({analysis.tool_percentage}%)")
print(f"Parallelization opportunity: {analysis.parallelization_gain}x speedup")
print(f"Total cost: ${analysis.total_cost}")
print(f"Most expensive agent: {analysis.most_expensive_agent}")
```

---

## Testing

See observability tests:
- `tests/test_observability/test_tracker.py` - Tracker unit tests
- `tests/test_observability/test_database.py` - Database tests
- `tests/test_observability/test_console.py` - Console visualization tests
- `tests/test_observability/test_gantt.py` - Gantt chart generation tests

---

## Related Documentation

- [Collaboration Features](../collaboration/) - Multi-agent collaboration
- [Execution Features](../execution/) - Workflow execution
- [Data Models](../../interfaces/models/observability_models.md) - Database schema
- [Milestone 1 Report](../../milestones/milestone1_completion.md) - M1 completion
