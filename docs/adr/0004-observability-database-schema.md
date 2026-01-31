# ADR-0004: Hierarchical Observability Database Schema

**Date:** 2026-01-25
**Status:** Accepted
**Deciders:** Framework Core Team
**Tags:** observability, database, tracing, M1

---

## Context

For the framework to achieve its vision of self-improvement and autonomous operation, it must have complete observability into all executions. This requires tracking every decision, LLM call, tool execution, and collaboration event.

**Problem Statement:**
- How do we store execution traces for workflows with multiple stages and agents?
- What level of granularity is needed for learning loops and debugging?
- How do we query traces efficiently for analysis and visualization?
- Should we use flat or hierarchical schema?

**Key Requirements:**
1. **Complete Traceability** - Track every workflow → stage → agent → LLM call → tool execution
2. **Queryable** - Fast queries for debugging, metrics, and learning loops
3. **Hierarchical** - Preserve parent-child relationships (workflow contains stages contains agents)
4. **Metrics Aggregation** - Roll up costs, tokens, duration from children to parents
5. **Flexible Schema** - Support future features (experiments, A/B testing, self-improvement)
6. **SQLite + PostgreSQL** - Dev-friendly SQLite, production PostgreSQL

**Key Questions:**
1. Flat table with foreign keys vs hierarchical model?
2. What metrics to track at each level (workflow, stage, agent, LLM, tool)?
3. How to handle many-to-many relationships (multi-agent collaboration)?
4. JSON columns for flexibility vs strongly-typed for performance?

---

## Decision Drivers

- **Self-Improvement** - Learning loops need rich execution traces
- **Debugging** - Developers need to trace errors from workflow → agent → LLM call
- **Cost Optimization** - Aggregate cost/token metrics at all levels
- **Query Performance** - Fast queries for dashboards and metrics
- **Schema Evolution** - Support future features without migrations
- **Simplicity** - SQLModel (Pydantic + SQLAlchemy) for type safety
- **Portability** - SQLite (dev) → PostgreSQL (prod)

---

## Considered Options

### Option 1: Flat Schema (Single Table with Foreign Keys)

**Description:** Store all events in a single table with type discriminator and foreign keys.

**Pros:**
- Simple queries (single table scan)
- Easy to add new event types
- Flexible schema

**Cons:**
- Loses hierarchical structure
- Hard to aggregate metrics up the tree
- Difficult to query "all LLM calls for workflow X"
- No type safety for different event types
- Parent-child relationships obscured

**Effort:** 2-3 days (MEDIUM)

---

### Option 2: Hierarchical Schema (Separate Tables)

**Description:** Separate tables for each level with relationships:
- WorkflowExecution (top-level)
- StageExecution (belongs to workflow)
- AgentExecution (belongs to stage)
- LLMCall (belongs to agent)
- ToolExecution (belongs to agent)

**Pros:**
- **Natural Hierarchy** - Preserves workflow → stage → agent → calls structure
- **Type Safety** - Each table has appropriate fields for its level
- **Easy Aggregation** - Roll up metrics from children (LLM calls → agent → stage → workflow)
- **Clear Relationships** - Foreign keys make parent-child explicit
- **Query Efficiency** - Can query specific level without scanning all events
- **Schema Evolution** - Can add fields to specific levels

**Cons:**
- More tables to manage
- Joins required for cross-level queries
- More complex initial setup

**Effort:** 3-4 days (MEDIUM)

---

### Option 3: Document Store (JSON/MongoDB)

**Description:** Store execution traces as nested JSON documents in document store.

**Pros:**
- Highly flexible schema
- Natural JSON nesting
- Easy to add fields

**Cons:**
- No type safety (Pydantic validation needed)
- No SQL queries (learning curve for NoSQL)
- Harder to aggregate metrics
- Adds MongoDB dependency (vs SQLite/Postgres)
- Overkill for structured data

**Effort:** 4-5 days (HIGH)

---

## Decision Outcome

**Chosen Option:** Option 2: Hierarchical Schema (Separate Tables)

**Justification:**

The hierarchical schema perfectly matches the framework's execution model and enables key features:

1. **Natural Model** - Workflows contain stages contain agents contain calls—schema mirrors reality

2. **Type Safety** - SQLModel (Pydantic + SQLAlchemy) provides:
   - Python type hints for all fields
   - Automatic validation
   - IDE autocomplete and type checking

3. **Metrics Aggregation** - Easy to roll up from leaves to root:
   ```sql
   -- Aggregate LLM costs up to workflow
   SELECT workflow_id, SUM(cost_usd) FROM llm_calls
   JOIN agent_executions ON llm_calls.agent_id = agent_executions.id
   JOIN stage_executions ON agent_executions.stage_id = stage_executions.id
   GROUP BY workflow_id
   ```

4. **Efficient Queries** - Index on foreign keys enables fast queries:
   - "All LLM calls for workflow X" - Join workflow → stage → agent → LLM
   - "All failed agents" - Query AgentExecution WHERE status='failed'
   - "Cost by stage" - Group by stage_id

5. **Debugging** - Trace from error to root cause:
   - Failed workflow → Failed stage → Failed agent → Erroneous LLM call

6. **Extensibility** - Add new tables (DecisionOutcome, ExperimentResult) without affecting existing schema

7. **SQLite + PostgreSQL** - Same schema works on both (via SQLModel)

**Decision Factors:**
- **Hierarchy Depth:** 4 levels (Workflow → Stage → Agent → Calls)
- **Relationships:** Clear 1:N relationships at each level
- **Indexes:** Foreign keys + common query fields (workflow_name, status, start_time)
- **JSON Columns:** Use for flexible metadata, config snapshots
- **Type Safety:** Full Pydantic validation on all models

---

## Consequences

### Positive

- **Complete Traceability** - Every execution traced from workflow down to individual LLM tokens
- **Type-Safe** - Pydantic models prevent schema errors at development time
- **Query Flexibility** - Can query at any level (workflow, stage, agent, call)
- **Metrics Aggregation** - Roll up costs, tokens, duration automatically
- **Debugging** - Trace errors from root cause (LLM call) to impact (workflow failure)
- **Visualization** - Hierarchical tree views (workflow → stages → agents)
- **Self-Improvement** - Rich traces enable learning loops
- **Portable** - SQLite dev → PostgreSQL prod with zero code changes

### Negative

- **Joins Required** - Cross-level queries need multiple joins (mitigated by indexes)
- **More Tables** - 5+ core tables vs 1 flat table (but clearer structure)
- **Migration Complexity** - Schema changes require migrations (SQLModel makes this easy)

### Neutral

- **Storage Overhead** - Foreign keys add bytes, but negligible vs JSON payloads
- **Query Complexity** - Simple queries simple, complex queries require joins (expected tradeoff)

---

## Implementation Notes

**Schema Hierarchy:**

```
WorkflowExecution (id, name, status, cost, tokens, ...)
    │
    ├─ StageExecution (id, workflow_id, name, status, ...)
    │   │
    │   ├─ AgentExecution (id, stage_id, name, status, cost, tokens, ...)
    │   │   │
    │   │   ├─ LLMCall (id, agent_id, provider, model, prompt, response, cost, tokens, ...)
    │   │   └─ ToolExecution (id, agent_id, tool_name, params, result, duration, ...)
    │   │
    │   └─ CollaborationEvent (id, stage_id, event_type, agents, consensus, ...)
    │
    ├─ DecisionOutcome (id, workflow_id, decision, rationale, ...)
    └─ SystemMetric (id, workflow_id, metric_name, value, ...)

AgentMeritScore (id, agent_name, domain, success_rate, merit_score, ...)
```

**Key Tables:**

1. **WorkflowExecution** - Top-level tracking
   - Aggregated metrics (total_cost, total_tokens)
   - Trigger info (manual, event, cron)
   - Optimization target (cost, speed, quality)

2. **StageExecution** - Stage-level tracking
   - Stage config snapshot
   - Multi-agent synthesis events
   - Stage metrics (cost, tokens for this stage)

3. **AgentExecution** - Agent-level tracking
   - Agent performance (success/failure)
   - Agent metrics (LLM cost, tool usage)
   - Feeds into AgentMeritScore for learning

4. **LLMCall** - Individual LLM invocation
   - Prompt, response, model, provider
   - Tokens (prompt + completion)
   - Cost calculation

5. **ToolExecution** - Tool invocation
   - Tool name, parameters, result
   - Duration, success/failure
   - Safety violations (if any)

**SQLModel Implementation:**

```python
from sqlmodel import SQLModel, Field, Relationship
from typing import List, Optional
from datetime import datetime

class WorkflowExecution(SQLModel, table=True):
    id: str = Field(primary_key=True)
    workflow_name: str = Field(index=True)
    status: str = Field(index=True)
    start_time: datetime = Field(index=True)
    total_cost_usd: Optional[float]
    total_tokens: Optional[int]

    stages: List["StageExecution"] = Relationship(back_populates="workflow")

class StageExecution(SQLModel, table=True):
    id: str = Field(primary_key=True)
    workflow_id: str = Field(foreign_key="workflowexecution.id", index=True)
    stage_name: str

    workflow: WorkflowExecution = Relationship(back_populates="stages")
    agents: List["AgentExecution"] = Relationship(back_populates="stage")
```

**Indexes:**
- `workflow_name` (frequent filter)
- `status` (filter by completion)
- `start_time` (time-series queries)
- Foreign keys (join performance)

**Action Items:**
- [x] Define SQLModel schema for all tables
- [x] Add indexes on foreign keys and common query fields
- [x] Implement aggregation functions (roll up metrics)
- [x] Create migration system for schema evolution
- [x] Test with SQLite (dev) and PostgreSQL (prod)
- [x] Add query helpers for common patterns

---

## Related Decisions

- [ADR-0003: Multi-Agent Collaboration Strategies](./0003-multi-agent-collaboration-strategies.md) - CollaborationEvent table
- [ADR-0005: YAML-Based Configuration](./0005-yaml-based-configuration.md) - Config snapshots in JSON columns

---

## References

- [Observability Models Documentation](../interfaces/models/observability_models.md)
- [Milestone 1 Completion Report](../milestones/milestone1_completion.md)
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/) - SQLModel (Pydantic + SQLAlchemy)
- [TECHNICAL_SPECIFICATION.md](../../TECHNICAL_SPECIFICATION.md) - Observability specification

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-25 | Framework Core Team | Initial decision |
| 2026-01-28 | agent-d6e90e | Backfilled from M1 completion |
