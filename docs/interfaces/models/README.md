# Data Models

Configuration schemas and observability data structures.

## Models

### [Config Schemas](./config_schema.md)
**Purpose:** Define structure and validation for all configuration files

**Key Schemas:**
- `WorkflowConfig` - Top-level workflow definition
- `StageConfig` - Workflow stage configuration
- `AgentConfig` - Agent behavior and capabilities
- `ToolConfig` - Tool parameters and permissions
- `TriggerConfig` - Conditional execution rules

**Features:**
- Pydantic-based validation
- Type safety with Python type hints
- Environment variable substitution
- Default values and optional fields
- Nested configuration support

**Use Cases:**
- Define multi-stage workflows in YAML
- Configure agent behaviors per environment
- Set tool permissions and constraints
- Create reusable configuration templates

**Example:**
```yaml
# configs/workflows/research.yaml
name: research_workflow
stages:
  - name: gather
    agents:
      - type: researcher
        llm:
          provider: ollama
          model: llama3.2:3b
        tools: [web_scraper, file_reader]
```

---

### [Observability Models](./observability_models.md)
**Purpose:** Track and query all system executions for debugging and analytics

**Key Models:**
- `WorkflowExecution` - Top-level workflow run
- `StageExecution` - Individual stage within workflow
- `AgentExecution` - Agent task execution
- `LLMCall` - LLM API call with tokens and cost
- `ToolExecution` - Tool invocation with parameters and result

**Features:**
- SQLite database backend
- Hierarchical execution tracking
- Full parameter and result capture
- Token and cost tracking
- Timestamps for performance analysis
- Queryable via SQLAlchemy

**Use Cases:**
- Debug workflow failures
- Analyze agent performance
- Track LLM costs and token usage
- Identify bottlenecks
- Generate execution traces
- Build analytics dashboards

**Relationships:**
```
WorkflowExecution
  └─ StageExecution(s)
       └─ AgentExecution(s)
            ├─ LLMCall(s)
            └─ ToolExecution(s)
```

---

## Design Principles

### Immutability
Configuration models are immutable after validation:
- Read-only after initialization
- Frozen Pydantic models
- No setters or mutators

### Validation
All models validate at load time:
- Type checking
- Range validation
- Dependency validation
- Custom validators

### Compatibility
Models support backward compatibility:
- Optional fields with defaults
- Version fields for schema evolution
- Migration scripts for breaking changes

### Serialization
All models support multiple formats:
- YAML (configuration)
- JSON (API responses)
- Database records (SQLAlchemy)
- Python dicts (internal)

## Database Schema

### Tables
- `workflow_executions` - Top-level workflows
- `stage_executions` - Workflow stages
- `agent_executions` - Agent tasks
- `llm_calls` - LLM API calls
- `tool_executions` - Tool invocations

### Indexes
- Workflow ID (for trace queries)
- Timestamps (for time-range queries)
- Status (for failure analysis)
- Agent type (for performance comparison)

### Querying
```python
from src.observability.database import get_session
from src.observability.models import WorkflowExecution

with get_session() as session:
    workflow = session.get(WorkflowExecution, workflow_id)
    print(f"Stages: {len(workflow.stages)}")
    print(f"Total cost: ${workflow.total_cost}")
```

## Related Documentation

- [Core Interfaces](../core/) - Agent, Tool, LLM interfaces
- [System Overview](../../architecture/SYSTEM_OVERVIEW.md) - Data flow
- [Documentation Index](../../INDEX.md) - All documentation
