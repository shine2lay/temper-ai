# Observability Models

## Overview

The observability system uses SQLModel (Pydantic + SQLAlchemy) to track all workflow executions, agent actions, LLM calls, and tool usage. This provides complete traceability and enables learning loops.

## Database Schema

```
WorkflowExecution (top-level)
    │
    ├─ StageExecution (1:N)
    │   │
    │   ├─ AgentExecution (1:N)
    │   │   │
    │   │   ├─ LLMCall (1:N)
    │   │   └─ ToolExecution (1:N)
    │   │
    │   └─ CollaborationEvent (1:N)
    │
    ├─ DecisionOutcome (1:N)
    └─ SystemMetric (1:N)

AgentMeritScore (standalone, tracks agent reputation)
```

## Core Models

### WorkflowExecution

Tracks top-level workflow execution.

```python
class WorkflowExecution(SQLModel, table=True):
    """Top-level workflow execution tracking."""

    # Identity
    id: str                                    # UUID
    workflow_name: str                         # Indexed
    workflow_version: Optional[str]
    workflow_config_snapshot: Dict[str, Any]   # JSON

    # Trigger
    trigger_type: Optional[str]                # manual | event | cron
    trigger_id: Optional[str]
    trigger_data: Optional[Dict[str, Any]]     # JSON

    # Timing
    start_time: datetime                       # Auto-set
    end_time: Optional[datetime]
    duration_seconds: Optional[float]

    # Status
    status: str                                # running | completed | failed | halted | timeout
    error_message: Optional[str]
    error_stack_trace: Optional[str]

    # Context
    optimization_target: Optional[str]         # cost | speed | quality
    product_type: Optional[str]
    environment: Optional[str]                 # dev | staging | prod

    # Metrics (aggregated from children)
    total_cost_usd: Optional[float]
    total_tokens: Optional[int]
    total_llm_calls: Optional[int]
    total_tool_calls: Optional[int]

    # Metadata
    tags: Optional[List[str]]                  # JSON array
    metadata: Optional[Dict[str, Any]]         # JSON

    created_at: datetime

    # Relationships
    stages: List["StageExecution"]
```

**Usage:**
```python
from src.observability.models import WorkflowExecution
from src.observability.database import get_session

with get_session() as session:
    workflow = WorkflowExecution(
        id="wf-123",
        workflow_name="simple_research",
        workflow_config_snapshot=config_dict,
        status="running",
        environment="dev"
    )
    session.add(workflow)
    session.commit()
```

### StageExecution

Tracks individual stage execution within a workflow.

```python
class StageExecution(SQLModel, table=True):
    """Stage execution tracking."""

    # Identity
    id: str
    workflow_execution_id: str                 # Foreign key
    stage_name: str                            # Indexed
    stage_version: Optional[str]
    stage_config_snapshot: Dict[str, Any]      # JSON

    # Timing
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]

    # Status
    status: str                                # running | completed | failed
    error_message: Optional[str]

    # Data
    input_data: Optional[Dict[str, Any]]       # JSON
    output_data: Optional[Dict[str, Any]]      # JSON

    # Metrics
    num_agents_executed: Optional[int]
    num_agents_succeeded: Optional[int]
    num_agents_failed: Optional[int]
    collaboration_rounds: Optional[int]        # For multi-agent stages

    # Metadata
    metadata: Optional[Dict[str, Any]]

    # Relationships
    workflow: WorkflowExecution
    agents: List["AgentExecution"]
    collaboration_events: List["CollaborationEvent"]
```

**Key Indexes:**
- `(workflow_execution_id, stage_name)` - Fast lookup of stages
- `(status, start_time)` - Query by status

### AgentExecution

Tracks individual agent execution within a stage.

```python
class AgentExecution(SQLModel, table=True):
    """Agent execution tracking."""

    # Identity
    id: str
    stage_execution_id: str                    # Foreign key
    agent_name: str                            # Indexed
    agent_version: Optional[str]
    agent_config_snapshot: Dict[str, Any]      # JSON

    # Timing
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]

    # Status
    status: str                                # running | completed | failed
    error_message: Optional[str]
    retry_count: int = 0

    # Core data
    reasoning: Optional[str]                   # Agent's thought process
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]

    # Performance metrics
    llm_duration_seconds: Optional[float]
    tool_duration_seconds: Optional[float]

    # LLM metrics (aggregated from LLMCall)
    total_tokens: Optional[int]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    estimated_cost_usd: Optional[float]
    num_llm_calls: Optional[int]

    # Tool metrics
    num_tool_calls: Optional[int]

    # Collaboration (M3+)
    votes_cast: Optional[Dict[str, Any]]       # JSON
    conflicts_with_agents: Optional[List[str]] # JSON array
    final_decision: Optional[str]
    confidence_score: Optional[float]

    # Quality metrics (M5+)
    output_quality_score: Optional[float]
    reasoning_quality_score: Optional[float]

    # Metadata
    metadata: Optional[Dict[str, Any]]

    # Relationships
    stage: StageExecution
    llm_calls: List["LLMCall"]
    tool_executions: List["ToolExecution"]
```

**Query Examples:**
```python
# Get all agent executions for a workflow
with get_session() as session:
    workflow = session.get(WorkflowExecution, "wf-123")
    for stage in workflow.stages:
        for agent in stage.agents:
            print(f"{agent.agent_name}: {agent.status}")

# Find expensive agents
expensive_agents = session.query(AgentExecution)\
    .filter(AgentExecution.estimated_cost_usd > 0.01)\
    .order_by(AgentExecution.estimated_cost_usd.desc())\
    .limit(10)\
    .all()
```

### LLMCall

Tracks individual LLM API calls with full request/response data.

```python
class LLMCall(SQLModel, table=True):
    """Detailed LLM call tracking."""

    # Identity
    id: str
    agent_execution_id: str                    # Foreign key

    # Provider info
    provider: str                              # ollama | openai | anthropic | vllm
    model: str                                 # llama3.2:3b | gpt-4 | claude-3.5-sonnet
    base_url: Optional[str]

    # Timing
    start_time: datetime
    end_time: Optional[datetime]
    latency_ms: Optional[int]

    # Request/Response
    prompt: Optional[str]                      # Can be large, nullable
    response: Optional[str]

    # Token metrics
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]

    # Cost
    estimated_cost_usd: Optional[float]

    # Parameters
    temperature: Optional[float]
    max_tokens: Optional[int]
    top_p: Optional[float]

    # Status
    status: str                                # success | error | timeout
    error_message: Optional[str]
    http_status_code: Optional[int]

    # Retry info
    retry_count: int = 0

    # Metadata
    metadata: Optional[Dict[str, Any]]

    # Relationships
    agent: AgentExecution
```

**Key Indexes:**
- `(agent_execution_id, start_time)` - Get calls in order
- `(model, start_time)` - Analyze model performance
- `(status, start_time)` - Find errors

**Analytics Queries:**
```python
# Calculate average latency by model
from sqlalchemy import func

with get_session() as session:
    stats = session.query(
        LLMCall.model,
        func.avg(LLMCall.latency_ms).label("avg_latency"),
        func.count(LLMCall.id).label("total_calls"),
        func.sum(LLMCall.estimated_cost_usd).label("total_cost")
    ).group_by(LLMCall.model).all()

    for stat in stats:
        print(f"{stat.model}: {stat.avg_latency:.0f}ms, ${stat.total_cost:.4f}")
```

### ToolExecution

Tracks tool execution with input/output and safety checks.

```python
class ToolExecution(SQLModel, table=True):
    """Tool execution tracking."""

    # Identity
    id: str
    agent_execution_id: str                    # Foreign key
    tool_name: str                             # Indexed
    tool_version: Optional[str]

    # Timing
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]

    # Input/Output
    input_params: Optional[Dict[str, Any]]     # JSON
    output_data: Optional[Dict[str, Any]]      # JSON

    # Status
    status: str                                # success | error | blocked
    error_message: Optional[str]
    retry_count: int = 0

    # Safety (M4)
    safety_checks_applied: Optional[List[str]] # JSON array
    approval_required: bool = False
    approved_by: Optional[str]
    approval_timestamp: Optional[datetime]

    # Metadata
    metadata: Optional[Dict[str, Any]]

    # Relationships
    agent: AgentExecution
```

**Key Indexes:**
- `(agent_execution_id, tool_name)` - Tools used by agent
- `(tool_name, start_time)` - Tool usage over time
- `(status, start_time)` - Find errors

### CollaborationEvent

Tracks multi-agent collaboration, debates, and conflict resolution (M3+).

```python
class CollaborationEvent(SQLModel, table=True):
    """Collaboration and synthesis tracking."""

    # Identity
    id: str
    stage_execution_id: str                    # Foreign key

    # Event type
    event_type: str                            # vote | conflict | resolution | consensus | debate_round
    timestamp: datetime
    round_number: Optional[int]

    # Participants
    agents_involved: Optional[List[str]]       # JSON array of agent names

    # Data
    event_data: Optional[Dict[str, Any]]       # JSON - event-specific data

    # Outcome
    resolution_strategy: Optional[str]         # voting | merit-weighted | human | AI-judge
    outcome: Optional[str]
    confidence_score: Optional[float]

    # Metadata
    metadata: Optional[Dict[str, Any]]

    # Relationships
    stage: StageExecution
```

**Event Types:**
- `vote` - Agent cast a vote
- `conflict` - Detected disagreement
- `resolution` - Conflict resolved
- `consensus` - All agents agree
- `debate_round` - Debate iteration

### AgentMeritScore

Tracks agent reputation and expertise by domain (M3+).

```python
class AgentMeritScore(SQLModel, table=True):
    """Agent reputation/merit tracking."""

    # Identity
    id: str
    agent_name: str                            # Indexed
    domain: str                                # Indexed - e.g., "market_research", "code_generation"

    # Cumulative scores
    total_decisions: int = 0
    successful_decisions: int = 0
    failed_decisions: int = 0
    overridden_decisions: int = 0

    # Calculated metrics
    success_rate: Optional[float]              # successful / total
    average_confidence: Optional[float]
    expertise_score: Optional[float]           # 0-100

    # Time-based metrics (with decay)
    last_30_days_success_rate: Optional[float]
    last_90_days_success_rate: Optional[float]

    # Timestamps
    first_decision_date: Optional[datetime]
    last_decision_date: Optional[datetime]
    last_updated: datetime

    # Metadata
    metadata: Optional[Dict[str, Any]]
```

**Key Indexes:**
- `(agent_name, domain)` - Unique constraint
- `(expertise_score DESC)` - Find top experts

**Usage:**
```python
# Find experts for a domain
with get_session() as session:
    experts = session.query(AgentMeritScore)\
        .filter(AgentMeritScore.domain == "market_research")\
        .order_by(AgentMeritScore.expertise_score.desc())\
        .limit(5)\
        .all()

    for expert in experts:
        print(f"{expert.agent_name}: {expert.expertise_score:.1f} ({expert.success_rate:.1%})")
```

### DecisionOutcome

Tracks decision outcomes for learning loop (M5+).

```python
class DecisionOutcome(SQLModel, table=True):
    """Decision outcome tracking for learning loop."""

    # Identity
    id: str
    agent_execution_id: Optional[str]          # Foreign key
    stage_execution_id: Optional[str]          # Foreign key
    workflow_execution_id: Optional[str]       # Foreign key

    # Decision info
    decision_type: str                         # code_change | market_strategy | architecture_choice
    decision_data: Dict[str, Any]              # JSON

    # Validation
    validation_method: Optional[str]           # test_suite | user_feedback | metrics
    validation_timestamp: Optional[datetime]
    validation_duration_seconds: Optional[float]

    # Outcome
    outcome: str                               # success | failure | neutral | mixed
    impact_metrics: Optional[Dict[str, Any]]   # JSON - measurable impact

    # Learning
    lessons_learned: Optional[str]             # Natural language
    should_repeat: Optional[bool]              # Would we make same decision again?
    tags: Optional[List[str]]                  # JSON array

    # Metadata
    metadata: Optional[Dict[str, Any]]
```

**Key Indexes:**
- `(agent_execution_id, outcome)` - Agent performance
- `(decision_type, outcome)` - Analyze decision patterns
- `(validation_timestamp DESC)` - Recent validations

### SystemMetric

Aggregated system metrics for monitoring (M2+).

```python
class SystemMetric(SQLModel, table=True):
    """Aggregated system metrics."""

    # Identity
    id: str
    metric_name: str                           # cost_per_workflow | avg_latency | error_rate
    metric_value: float
    metric_unit: Optional[str]                 # usd | ms | percentage

    # Dimensions
    workflow_name: Optional[str]               # Indexed
    stage_name: Optional[str]
    agent_name: Optional[str]
    environment: Optional[str]                 # dev | staging | prod

    # Time
    timestamp: datetime                        # Indexed
    aggregation_period: Optional[str]          # minute | hour | day

    # Metadata
    tags: Optional[Dict[str, Any]]             # JSON
    metadata: Optional[Dict[str, Any]]         # JSON
```

**Key Indexes:**
- `(metric_name, timestamp)` - Time series data
- `(workflow_name, timestamp)` - Workflow metrics

## Database Management

### Initialization

```python
from src.observability.database import init_database

# SQLite (development)
db = init_database("sqlite:///workflow_execution.db")

# PostgreSQL (production)
db = init_database("postgresql://user:pass@localhost/workflow_db")

# From environment variable
db = init_database()  # Uses DATABASE_URL env var
```

### Session Management

```python
from src.observability.database import get_session

# Context manager (recommended)
with get_session() as session:
    workflow = WorkflowExecution(...)
    session.add(workflow)
    session.commit()
    # Auto-rollback on exception

# Manual session
from src.observability.database import get_database

db = get_database()
with db.session() as session:
    # Use session
    pass
```

### Querying

```python
from src.observability.models import WorkflowExecution, AgentExecution
from src.observability.database import get_session
from sqlalchemy import func

with get_session() as session:
    # Simple query
    workflow = session.get(WorkflowExecution, "wf-123")

    # Filter query
    recent_workflows = session.query(WorkflowExecution)\
        .filter(WorkflowExecution.status == "completed")\
        .order_by(WorkflowExecution.start_time.desc())\
        .limit(10)\
        .all()

    # Join query
    expensive_agents = session.query(AgentExecution)\
        .join(StageExecution)\
        .join(WorkflowExecution)\
        .filter(WorkflowExecution.workflow_name == "simple_research")\
        .order_by(AgentExecution.estimated_cost_usd.desc())\
        .all()

    # Aggregate query
    stats = session.query(
        func.count(WorkflowExecution.id).label("total"),
        func.avg(WorkflowExecution.duration_seconds).label("avg_duration"),
        func.sum(WorkflowExecution.total_cost_usd).label("total_cost")
    ).first()
```

## Complete Schema DDL

All indexes are created automatically from model definitions:

```python
# Composite indexes
Index("idx_workflow_status", WorkflowExecution.status, WorkflowExecution.start_time)
Index("idx_workflow_name", WorkflowExecution.workflow_name, WorkflowExecution.start_time)
Index("idx_stage_workflow", StageExecution.workflow_execution_id, StageExecution.stage_name)
Index("idx_stage_status", StageExecution.status, StageExecution.start_time)
Index("idx_agent_stage", AgentExecution.stage_execution_id, AgentExecution.agent_name)
Index("idx_agent_name", AgentExecution.agent_name, AgentExecution.start_time)
Index("idx_llm_agent", LLMCall.agent_execution_id, LLMCall.start_time)
Index("idx_llm_model", LLMCall.model, LLMCall.start_time)
Index("idx_llm_status", LLMCall.status, LLMCall.start_time)
Index("idx_tool_agent", ToolExecution.agent_execution_id, ToolExecution.tool_name)
Index("idx_tool_name", ToolExecution.tool_name, ToolExecution.start_time)
Index("idx_tool_status", ToolExecution.status, ToolExecution.start_time)
Index("idx_collab_stage", CollaborationEvent.stage_execution_id, CollaborationEvent.event_type)
Index("idx_merit_agent", AgentMeritScore.agent_name, AgentMeritScore.domain)
Index("idx_merit_score", AgentMeritScore.expertise_score.desc())
Index("idx_outcome_agent", DecisionOutcome.agent_execution_id, DecisionOutcome.outcome)
Index("idx_outcome_type", DecisionOutcome.decision_type, DecisionOutcome.outcome)
Index("idx_outcome_validation", DecisionOutcome.validation_timestamp.desc())
Index("idx_metrics_name", SystemMetric.metric_name, SystemMetric.timestamp)
Index("idx_metrics_workflow", SystemMetric.workflow_name, SystemMetric.timestamp)
```

## Related Documentation

- [Agent Interface](./agent_interface.md)
- [System Overview](../architecture/SYSTEM_OVERVIEW.md)
- [Observability Console](./observability_console.md) (TODO)
