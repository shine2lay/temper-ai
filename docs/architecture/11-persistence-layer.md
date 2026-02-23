# Architecture Document 11: Persistence Layer

**System:** temper-ai (Meta-Autonomous Framework)
**Document Version:** 1.0
**Last Updated:** 2026-02-22
**Scope:** All data storage subsystems — database models, memory system, agent registry, auth/tenant isolation, config sync, lifecycle management, learning/auto-tune, goals, portfolio, experimentation, and the autonomy persistence layer.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [High-Level Architecture Overview](#2-high-level-architecture-overview)
3. [Database Engine and Session Management](#3-database-engine-and-session-management)
4. [Core Observability Database Models](#4-core-observability-database-models)
5. [Multi-Tenancy Data Layer (M10)](#5-multi-tenancy-data-layer-m10)
6. [Authentication and Authorization System](#6-authentication-and-authorization-system)
7. [Memory System](#7-memory-system)
8. [Agent Registry (M9)](#8-agent-registry-m9)
9. [Lifecycle Persistence](#9-lifecycle-persistence)
10. [Goals Persistence](#10-goals-persistence)
11. [Portfolio Persistence](#11-portfolio-persistence)
12. [Learning and Auto-Tune Persistence](#12-learning-and-auto-tune-persistence)
13. [Autonomy Orchestrator and Cross-Subsystem Coordination](#13-autonomy-orchestrator-and-cross-subsystem-coordination)
14. [Event Bus Persistence (M9)](#14-event-bus-persistence-m9)
15. [Alembic Migration System](#15-alembic-migration-system)
16. [Data Integrity and Validation](#16-data-integrity-and-validation)
17. [Design Patterns and Architectural Decisions](#17-design-patterns-and-architectural-decisions)
18. [Extension and Integration Guide](#18-extension-and-integration-guide)
19. [Observations and Recommendations](#19-observations-and-recommendations)

---

## 1. Executive Summary

**System Name:** temper-ai Persistence Layer

**Purpose:** Provides all data durability for the temper-ai meta-autonomous framework — from workflow execution telemetry and LLM call tracing to multi-tenant configuration storage, persistent agent memory, cross-agent knowledge sharing, and continuous learning feedback loops.

**Technology Stack:**
- **ORM:** SQLModel (Pydantic + SQLAlchemy hybrid)
- **Primary Database:** PostgreSQL (production)
- **Test Database:** SQLite (in-memory)
- **Connection Pooling:** SQLAlchemy QueuePool (PostgreSQL), StaticPool (SQLite in-memory)
- **Migrations:** Alembic (version-controlled DDL)
- **Memory Adapters:** In-memory dict, PostgreSQL (ILIKE/FTS), Mem0 (vector), Knowledge Graph
- **Auth:** HMAC-SHA256 API keys, FastAPI dependency injection, RBAC (owner/editor/viewer)

**Scope of Analysis:** All files under `temper_ai/storage/`, `temper_ai/auth/`, `temper_ai/memory/`, `temper_ai/registry/`, `temper_ai/lifecycle/`, `temper_ai/goals/`, `temper_ai/portfolio/`, `temper_ai/learning/`, and `alembic/versions/`.

---

## 2. High-Level Architecture Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          TEMPER-AI PERSISTENCE LAYER                            │
├──────────────────────────────────────────────────────────────────────────────── ┤
│                                                                                  │
│  ┌──────────────────────────────────────┐   ┌──────────────────────────┐   │
│  │  FastAPI Routes                      │   │  WebSocket Connections   │   │
│  │  (auth_routes, config_routes,        │   │  (websocket.py with      │   │
│  │   workflow routes, agent_routes,     │   │   ws_tickets.py)         │   │
│  │   events, studio)                    │   └───────────┬──────────────┘  │
│  └────────┬─────────────────────────────┘               │                  │
│           │                                              │                  │
│  ┌────────▼───────────────────────▼──────────────────────────▼──────────────┐  │
│  │                      AUTH & TENANT ISOLATION (M10)                        │  │
│  │   api_key_auth.py → require_auth() → AuthContext{user_id,tenant_id,role}  │  │
│  │   tenant_scope.py → scoped_query() / get_scoped() / count_scoped()        │  │
│  │   config_sync.py  → ConfigSyncService: import/export/list                 │  │
│  │   config_seed.py  → seed_configs() from YAML files                        │  │
│  └────────┬──────────────────────────────────────────────────────────────────┘  │
│           │                                                                      │
│  ┌────────▼──────────────────────────────────────────────────────────────────┐  │
│  │                      DATABASE MANAGER (manager.py)                         │  │
│  │   init_database() → DatabaseManager → get_session() → Session             │  │
│  │   ALEMBIC_MANAGED=1 → skip create_all; run 'alembic upgrade head'         │  │
│  └────────┬──────────────────────────────────────────────────────────────────┘  │
│           │                                                                      │
│  ┌────────▼──────────────────────────────────────────────────────────────────┐  │
│  │                       ENGINE FACTORY (engine.py)                           │  │
│  │   PostgreSQL: QueuePool, pool_pre_ping, max_overflow=pool_size*2           │  │
│  │   SQLite:     StaticPool (memory) / NullPool (file), WAL+FK pragmas        │  │
│  └────────┬──────────────────────────────────────────────────────────────────┘  │
│           │                                                                      │
│  ┌────────▼──────────────────────────────────────────────────────────────────┐  │
│  │                        POSTGRESQL DATABASE                                  │  │
│  │                                                                              │  │
│  │  CORE OBSERVABILITY TABLES         TENANCY TABLES                           │  │
│  │  ───────────────────────────       ──────────────────                       │  │
│  │  workflow_executions               tenants                                  │  │
│  │    └─ stage_executions             users                                    │  │
│  │         └─ agent_executions        tenant_memberships                       │  │
│  │              ├─ llm_calls          api_keys                                 │  │
│  │              ├─ tool_executions    workflow_configs                         │  │
│  │              └─ decision_outcomes  stage_configs                            │  │
│  │  collaboration_events              agent_configs                            │  │
│  │  agent_merit_scores                                                         │  │
│  │  system_metrics                    AGENT REGISTRY (M9)                     │  │
│  │  error_fingerprints                ─────────────────                       │  │
│  │  alert_records                     agent_registry                           │  │
│  │  rollback_snapshots                                                         │  │
│  │    └─ rollback_events              EVENT BUS (M9)                          │  │
│  │  schema_version                    ─────────────                           │  │
│  │                                    event_log                                │  │
│  │  DOMAIN STORES (own engine)        event_subscriptions                     │  │
│  │  ──────────────────────────                                                 │  │
│  │  lifecycle_adaptations             EVALUATION                               │  │
│  │  lifecycle_profiles                ──────────                               │  │
│  │  goal_proposals                    agent_evaluation_results                 │  │
│  │  analysis_runs                                                               │  │
│  │  portfolios                        MEMORY (PG adapter)                      │  │
│  │  product_runs                      ─────────────────                        │  │
│  │  shared_components                 memory_records                           │  │
│  │  kg_concepts / kg_edges                                                     │  │
│  │  tech_compatibility                                                          │  │
│  │  portfolio_snapshots                                                         │  │
│  │  learned_patterns                                                            │  │
│  │  mining_runs                                                                 │  │
│  │  tune_recommendations                                                        │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Component Breakdown

| Component | Location | Purpose |
|-----------|----------|---------|
| Engine Factory | `temper_ai/storage/database/engine.py` | Creates dialect-appropriate SQLAlchemy engines |
| Database Manager | `temper_ai/storage/database/manager.py` | Global session lifecycle, isolation levels |
| Core Models | `temper_ai/storage/database/models.py` | Observability tables (13 models) |
| Registry Models | `temper_ai/storage/database/models_registry.py` | Agent registry DB table |
| Tenancy Models | `temper_ai/storage/database/models_tenancy.py` | Multi-tenant access control (7 models) |
| Evaluation Models | `temper_ai/storage/database/models_evaluation.py` | Per-agent evaluation results |
| API Key Auth | `temper_ai/auth/api_key_auth.py` | HMAC-SHA256 key validation, AuthContext, RBAC |
| Tenant Scope | `temper_ai/auth/tenant_scope.py` | Query-level tenant isolation helpers |
| Config Sync | `temper_ai/auth/config_sync.py` | YAML-to-DB import/export |
| Config Seed | `temper_ai/auth/config_seed.py` | Bulk seed from configs/ directory |
| WS Tickets | `temper_ai/auth/ws_tickets.py` | Short-lived WebSocket auth tokens |
| Session Mgmt | `temper_ai/auth/session.py` | In-memory session store with LRU |
| Memory Service | `temper_ai/memory/service.py` | High-level memory operations |
| Memory Registry | `temper_ai/memory/registry.py` | Adapter discovery and lazy loading |
| Memory Adapters | `temper_ai/memory/adapters/` | InMemory, PG, Mem0, KnowledgeGraph |
| Cross-Pollination | `temper_ai/memory/cross_pollination.py` | Cross-agent knowledge sharing |
| Agent Registry | `temper_ai/registry/` | Persistent agent store (service + store) |
| Lifecycle Store | `temper_ai/lifecycle/store.py` | Adaptation and profile persistence |
| Goals Store | `temper_ai/goals/store.py` | Goal proposals and analysis runs |
| Portfolio Store | `temper_ai/portfolio/store.py` | Portfolio, KG, runs, compatibility |
| Learning Store | `temper_ai/learning/store.py` | Patterns, mining runs, recommendations |

---

## 3. Database Engine and Session Management

### 3.1 Engine Factory (`temper_ai/storage/database/engine.py`)

The engine factory is the single point of engine creation, enforcing consistent configuration across all subsystems.

**Key function:**
```python
# temper_ai/storage/database/engine.py:40-67
def create_app_engine(
    database_url: str | None = None,
    pool_size: int = SMALL_POOL_SIZE,
) -> Engine:
```

**Dialect dispatch table:**

| Dialect | Pool Class | Extra Configuration |
|---------|-----------|---------------------|
| `postgresql://` | `QueuePool` | `pool_size`, `max_overflow=pool_size*2`, `pool_pre_ping=True` |
| `sqlite:///:memory:` | `StaticPool` | WAL mode, foreign key enforcement |
| `sqlite:///file.db` | `NullPool` | WAL mode, foreign key enforcement |

**Environment variable:** `TEMPER_DATABASE_URL`
**Default:** `postgresql://temper:temper@localhost:5432/temper`

**SQLite enforcement:** SQLite URLs are blocked in production (`pytest` not in `sys.modules`). This prevents accidental file-based SQLite usage in deployed environments.

**SQLite pragma configuration:**
```python
# temper_ai/storage/database/engine.py:107-115
@event.listens_for(engine, "connect")
def _on_connect(dbapi_conn, _rec):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for concurrency
    cursor.execute("PRAGMA foreign_keys=ON")   # Referential integrity
    cursor.close()
```

### 3.2 Database Manager (`temper_ai/storage/database/manager.py`)

The `DatabaseManager` is a class wrapping a single engine and providing context-managed sessions.

**Session lifecycle:**
```python
# temper_ai/storage/database/manager.py:91-136
@contextmanager
def session(
    self,
    isolation_level: IsolationLevel | None = None
) -> Generator[Session, None, None]:
    session = Session(self.engine)
    if isolation_level:
        session.connection().execution_options(
            isolation_level=isolation_level.value
        )
    try:
        yield session
        session.commit()   # Auto-commit on clean exit
    except Exception as e:
        session.rollback() # Auto-rollback on exception
        raise
    finally:
        session.close()    # Always close
```

**Isolation level enum:**
| Level | Use Case |
|-------|----------|
| `READ_UNCOMMITTED` | Analytics queries (rarely used) |
| `READ_COMMITTED` | Default; prevents dirty reads |
| `REPEATABLE_READ` | Preventing non-repeatable reads |
| `SERIALIZABLE` | Operations requiring strict consistency; retry logic required |

**Global singleton pattern:**
```python
# temper_ai/storage/database/manager.py:139-232
_db_manager: DatabaseManager | None = None
_db_lock = threading.Lock()

def init_database(database_url: str | None = None) -> DatabaseManager:
    """Thread-safe initialization. Verifies connection with SELECT 1."""
    ...

def get_database() -> DatabaseManager:
    """Returns initialized manager or raises RuntimeError."""
    ...

@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Primary interface used throughout the codebase."""
    db = get_database()
    with db.session() as session:
        yield session
```

**Production vs. development schema management:**

```
ALEMBIC_MANAGED=1  →  init_database() skips create_all_tables()
                       Run: alembic upgrade head

(default)          →  init_database() calls create_all_tables()
                       SQLModel.metadata.create_all() on every startup
```

**Password masking:** The `_mask_database_url()` function replaces passwords with `****` before any URL is written to logs — critical for security in log aggregation systems.

### 3.3 Datetime Utilities (`temper_ai/storage/database/datetime_utils.py`)

All timestamps in the system use timezone-aware UTC datetimes via:

```python
def utcnow() -> datetime:
    return datetime.now(UTC)
```

This replaces the deprecated `datetime.utcnow()` which returns naive datetimes. The module also provides:

- `ensure_utc(dt)` — normalizes naive/non-UTC datetimes to UTC
- `validate_utc_aware(dt, context)` — strict validation at API boundaries
- `safe_duration_seconds(start, end)` — duration calculation with clock-skew detection

### 3.4 Flow: Session Lifecycle

```mermaid
flowchart TD
    A[Application Code] -->|calls| B[get_session]
    B -->|calls| C[get_database]
    C -->|raises RuntimeError if| D{_db_manager is None}
    D -->|yes| E[RuntimeError: call init_database first]
    D -->|no| F[DatabaseManager.session]
    F --> G[Session opened]
    G --> H{Execute operations}
    H -->|success| I[session.commit]
    H -->|exception| J[session.rollback + re-raise]
    I --> K[session.close]
    J --> K
    K --> L[Return to caller]
```

---

## 4. Core Observability Database Models

All observability models reside in `temper_ai/storage/database/models.py`. They form a strict tree hierarchy with CASCADE DELETE.

### 4.1 ER Diagram

```mermaid
erDiagram
    workflow_executions {
        string id PK
        string workflow_name
        string workflow_version
        json workflow_config_snapshot
        string trigger_type
        string trigger_id
        json trigger_data
        datetime start_time
        datetime end_time
        float duration_seconds
        string status
        string error_message
        string error_stack_trace
        string error_fingerprint
        string optimization_target
        string product_type
        string environment
        float total_cost_usd
        int total_tokens
        int total_llm_calls
        int total_tool_calls
        json tags
        json extra_metadata
        json cost_attribution_tags
        string tenant_id
        datetime created_at
    }

    stage_executions {
        string id PK
        string workflow_execution_id FK
        string stage_name
        string stage_version
        json stage_config_snapshot
        datetime start_time
        datetime end_time
        float duration_seconds
        string status
        string error_message
        string error_fingerprint
        json input_data
        json output_data
        int num_agents_executed
        int num_agents_succeeded
        int num_agents_failed
        int collaboration_rounds
        json extra_metadata
        json output_lineage
        string tenant_id
    }

    agent_executions {
        string id PK
        string stage_execution_id FK
        string agent_name
        string agent_version
        json agent_config_snapshot
        datetime start_time
        datetime end_time
        float duration_seconds
        string status
        string error_message
        string error_fingerprint
        int retry_count
        string reasoning
        json input_data
        json output_data
        float llm_duration_seconds
        float tool_duration_seconds
        int total_tokens
        int prompt_tokens
        int completion_tokens
        float estimated_cost_usd
        int num_llm_calls
        int num_tool_calls
        json votes_cast
        json conflicts_with_agents
        string final_decision
        float confidence_score
        float output_quality_score
        float reasoning_quality_score
        json extra_metadata
        string tenant_id
    }

    llm_calls {
        string id PK
        string agent_execution_id FK
        string provider
        string model
        string base_url
        datetime start_time
        datetime end_time
        int latency_ms
        string prompt
        string response
        int prompt_tokens
        int completion_tokens
        int total_tokens
        float estimated_cost_usd
        float temperature
        int max_tokens
        float top_p
        string status
        string error_message
        string error_fingerprint
        int http_status_code
        int retry_count
        json failover_sequence
        string failover_from_provider
        string prompt_template_hash
        string prompt_template_source
        json extra_metadata
        string tenant_id
    }

    tool_executions {
        string id PK
        string agent_execution_id FK
        string tool_name
        string tool_version
        datetime start_time
        datetime end_time
        float duration_seconds
        json input_params
        json output_data
        string status
        string error_message
        string error_fingerprint
        int retry_count
        json safety_checks_applied
        bool approval_required
        string approved_by
        datetime approval_timestamp
        json extra_metadata
        string tenant_id
    }

    collaboration_events {
        string id PK
        string stage_execution_id FK
        string event_type
        datetime timestamp
        int round_number
        json agents_involved
        json event_data
        string resolution_strategy
        string outcome
        float confidence_score
        json extra_metadata
        string tenant_id
    }

    decision_outcomes {
        string id PK
        string agent_execution_id FK
        string stage_execution_id FK
        string workflow_execution_id FK
        string decision_type
        json decision_data
        string validation_method
        datetime validation_timestamp
        float validation_duration_seconds
        string outcome
        json impact_metrics
        string lessons_learned
        bool should_repeat
        json tags
        json extra_metadata
        string tenant_id
    }

    agent_merit_scores {
        string id PK
        string agent_name
        string domain
        int total_decisions
        int successful_decisions
        int failed_decisions
        int mixed_decisions
        int overridden_decisions
        float success_rate
        float average_confidence
        float expertise_score
        float last_30_days_success_rate
        float last_90_days_success_rate
        datetime first_decision_date
        datetime last_decision_date
        datetime last_updated
        json extra_metadata
        string tenant_id
    }

    rollback_snapshots {
        string id PK
        string workflow_execution_id FK
        string checkpoint_id
        json action
        json context
        json file_snapshots
        json state_snapshots
        datetime created_at
        datetime expires_at
        string tenant_id
    }

    rollback_events {
        string id PK
        string snapshot_id FK
        string status
        string trigger
        string operator
        json reverted_items
        json failed_items
        json errors
        datetime executed_at
        string reason
        json rollback_metadata
        string tenant_id
    }

    error_fingerprints {
        string fingerprint PK
        string error_type
        string error_code
        string classification
        string normalized_message
        string sample_message
        int occurrence_count
        datetime first_seen
        datetime last_seen
        json recent_workflow_ids
        json recent_agent_names
        bool resolved
        datetime resolved_at
        string resolution_note
        string tenant_id
    }

    system_metrics {
        string id PK
        string metric_name
        float metric_value
        string metric_unit
        string workflow_name
        string stage_name
        string agent_name
        string environment
        datetime timestamp
        string aggregation_period
        json tags
        json extra_metadata
        string tenant_id
    }

    alert_records {
        string id PK
        string rule_name
        string severity
        string message
        float metric_value
        float threshold
        datetime timestamp
        json context
        string tenant_id
    }

    schema_version {
        int id PK
        string version
        datetime applied_at
        string description
    }

    workflow_executions ||--o{ stage_executions : "has"
    stage_executions ||--o{ agent_executions : "has"
    stage_executions ||--o{ collaboration_events : "has"
    agent_executions ||--o{ llm_calls : "has"
    agent_executions ||--o{ tool_executions : "has"
    agent_executions ||--o{ decision_outcomes : "has"
    stage_executions ||--o{ decision_outcomes : "has"
    workflow_executions ||--o{ decision_outcomes : "has"
    workflow_executions ||--o{ rollback_snapshots : "has"
    rollback_snapshots ||--o{ rollback_events : "has"
```

### 4.2 Table Details

**`workflow_executions`**
- **Primary Key:** String UUID assigned by the executor
- **Status Values:** `running | completed | failed | halted | timeout` (enforced by `CheckConstraint`)
- **JSON Size Limits:** `workflow_config_snapshot` ≤ 2MB, `extra_metadata` ≤ 512KB (validated in `__init__`)
- **Tenant Isolation:** `tenant_id` column + index on all rows
- **Key Indexes:** `idx_workflow_status (status, start_time)`, `idx_workflow_name (workflow_name, start_time)`, `idx_workflow_end_time (end_time)`

**`stage_executions`**
- **Foreign Key:** `workflow_execution_id` → `workflow_executions.id` ON DELETE CASCADE
- **JSON Size Limits:** `stage_config_snapshot`, `input_data`, `output_data` ≤ 1MB each
- **Data Lineage:** `output_lineage` JSON tracks provenance of stage outputs
- **Key Indexes:** `idx_stage_workflow (workflow_execution_id, stage_name)`, `idx_stage_status`

**`agent_executions`**
- **Foreign Key:** `stage_execution_id` → `stage_executions.id` ON DELETE CASCADE
- **Quality Metrics:** `output_quality_score` and `reasoning_quality_score` (0.0–1.0) for merit tracking
- **Collaboration Fields:** `votes_cast`, `conflicts_with_agents`, `final_decision`, `confidence_score` for multi-agent strategies
- **JSON Size Limits:** `agent_config_snapshot`, `input_data`, `output_data` ≤ 1MB each

**`llm_calls`**
- **Foreign Key:** `agent_execution_id` → `agent_executions.id` ON DELETE CASCADE
- **Status Values:** `success | error | timeout | cancelled`
- **Failover Tracking:** `failover_sequence` (JSON array of tried providers), `failover_from_provider`
- **Prompt Versioning:** `prompt_template_hash` (16-char), `prompt_template_source`
- **Cost Accounting:** `estimated_cost_usd` per call

**`tool_executions`**
- **Safety Audit Fields:** `safety_checks_applied`, `approval_required`, `approved_by`, `approval_timestamp`
- **Status Values:** `success | error | failed | timeout | cancelled`

**`agent_merit_scores`**
- **Unique Constraint:** `(agent_name, domain)` — one merit record per agent per domain
- **Time-Decay Metrics:** `last_30_days_success_rate`, `last_90_days_success_rate` for recency weighting
- **Used by:** Weighted voting strategies in multi-agent stages

**`error_fingerprints`**
- **Primary Key:** 16-char hex hash (the fingerprint itself)
- **Classification Values:** `transient | permanent | safety | unknown`
- **Deduplication:** `occurrence_count` incremented on each recurrence; `recent_workflow_ids` capped JSON array

**`rollback_snapshots` and `rollback_events`**
- `rollback_snapshots` stores file and state snapshots pre-action
- `rollback_events` is the audit trail of each rollback execution
- **Cleanup:** `expires_at` index supports TTL-based cleanup jobs

### 4.3 Composite Indexes (Performance)

```python
# From temper_ai/storage/database/models.py:654-675
Index("idx_workflow_status", WorkflowExecution.status, WorkflowExecution.start_time)
Index("idx_workflow_name", WorkflowExecution.workflow_name, WorkflowExecution.start_time)
Index("idx_workflow_end_time", WorkflowExecution.end_time)
Index("idx_stage_workflow", StageExecution.workflow_execution_id, StageExecution.stage_name)
Index("idx_stage_status", StageExecution.status, StageExecution.start_time)
Index("idx_agent_stage", AgentExecution.stage_execution_id, AgentExecution.agent_name)
Index("idx_agent_name", AgentExecution.agent_name, AgentExecution.start_time)
Index("idx_llm_agent", LLMCall.agent_execution_id, LLMCall.start_time)
Index("idx_llm_model", LLMCall.model, LLMCall.start_time)
Index("idx_llm_status", LLMCall.status, LLMCall.start_time)
Index("idx_tool_agent", ToolExecution.agent_execution_id, ToolExecution.tool_name)
Index("idx_collab_stage", CollaborationEvent.stage_execution_id, CollaborationEvent.event_type)
Index("idx_merit_agent", AgentMeritScore.agent_name, AgentMeritScore.domain)
Index("idx_outcome_type", DecisionOutcome.decision_type, DecisionOutcome.outcome)
Index("idx_metrics_name", SystemMetric.metric_name, SystemMetric.timestamp)
```

---

## 5. Multi-Tenancy Data Layer (M10)

Implemented in Milestone 10, the multi-tenancy layer provides complete data isolation between organizational tenants.

### 5.1 Tenancy ER Diagram

```mermaid
erDiagram
    tenants {
        string id PK
        string name
        string slug
        bool is_active
        string plan
        int max_workflows
        datetime created_at
        datetime updated_at
        json metadata_json
    }

    users {
        string id PK
        string email
        string name
        string oauth_provider
        string oauth_subject
        bool is_active
        datetime created_at
        datetime updated_at
    }

    tenant_memberships {
        string id PK
        string tenant_id FK
        string user_id FK
        string role
        datetime created_at
    }

    api_keys {
        string id PK
        string user_id FK
        string tenant_id FK
        string label
        string key_prefix
        string key_hash
        bool is_active
        datetime expires_at
        datetime last_used_at
        int total_requests
        datetime created_at
    }

    workflow_configs {
        string id PK
        string tenant_id FK
        string name
        int version
        string description
        json config_data
        string created_by FK
        string updated_by FK
        datetime created_at
        datetime updated_at
    }

    stage_configs {
        string id PK
        string tenant_id FK
        string name
        int version
        string description
        json config_data
        string created_by FK
        string updated_by FK
        datetime created_at
        datetime updated_at
    }

    agent_configs {
        string id PK
        string tenant_id FK
        string name
        int version
        string description
        json config_data
        string created_by FK
        string updated_by FK
        datetime created_at
        datetime updated_at
    }

    tenants ||--o{ tenant_memberships : "has"
    users ||--o{ tenant_memberships : "belongs to"
    users ||--o{ api_keys : "owns"
    tenants ||--o{ api_keys : "scoped to"
    tenants ||--o{ workflow_configs : "owns"
    tenants ||--o{ stage_configs : "owns"
    tenants ||--o{ agent_configs : "owns"
    users ||--o{ workflow_configs : "created_by"
    users ||--o{ stage_configs : "created_by"
    users ||--o{ agent_configs : "created_by"
```

### 5.2 RBAC Roles

| Role | Description | Capabilities |
|------|-------------|--------------|
| `owner` | Tenant administrator | Full control: create/delete API keys, manage members, import/export configs |
| `editor` | Developer/power user | Run workflows, import configs, create API keys for self |
| `viewer` | Read-only | List and export configs, view execution history |

Role constraint enforced at DB level:
```sql
CHECK (role IN ('owner', 'editor', 'viewer'))
```

### 5.3 Tenant Isolation Strategy

The isolation is enforced at **query level** — every tenant-scoped table has a `tenant_id` column, and all queries must pass through helpers in `tenant_scope.py`:

```python
# temper_ai/auth/tenant_scope.py:17-28
def scoped_query(session: Session, model: type[T], tenant_id: str):
    """SELECT * FROM <model> WHERE tenant_id = :tenant_id"""
    return select(model).where(col(model.tenant_id) == tenant_id)

def get_scoped(session, model, tenant_id, record_id) -> T | None:
    """SELECT * FROM <model> WHERE id = :id AND tenant_id = :tenant_id"""
    ...

def count_scoped(session, model, tenant_id) -> int:
    """SELECT COUNT(*) FROM <model> WHERE tenant_id = :tenant_id"""
    ...
```

### 5.4 Tenant-Scoped Query Pipeline

```mermaid
flowchart TD
    A[Incoming HTTP Request] --> B{auth_enabled?}
    B -->|No, dev mode| C[No tenant filter applied]
    B -->|Yes, server mode| D[require_auth dependency]
    D --> E[Extract Bearer token from Authorization header]
    E --> F{Starts with 'tk_'?}
    F -->|No| G[HTTP 401: Invalid format]
    F -->|Yes| H[hash_api_key: HMAC-SHA256 with pepper]
    H --> I[DB lookup: api_keys JOIN tenant_memberships]
    I --> J{Row found?}
    J -->|No| K[HTTP 401: Invalid API key]
    J -->|Yes| L{is_active AND not expired?}
    L -->|No| M[HTTP 401: Revoked or expired]
    L -->|Yes| N[Update last_used_at + total_requests]
    N --> O[Return AuthContext{user_id, tenant_id, role, api_key_id}]
    O --> P[Route handler receives ctx: AuthContext]
    P --> Q[scoped_query / get_scoped with ctx.tenant_id]
    Q --> R[SQL: WHERE tenant_id = ctx.tenant_id]
    R --> S[Results returned — only this tenant's data]
```

### 5.5 Config Tables: Unique Constraints

All three config tables (`workflow_configs`, `stage_configs`, `agent_configs`) share the same structure:

```sql
UNIQUE (tenant_id, name)              -- Two tenants can have same-named config
CHECK (version >= 1)                  -- Version never decreases
```

`ConfigSyncService.import_config()` implements upsert logic: if `(tenant_id, name)` exists, version is incremented and `config_data` is updated. Otherwise, a new row is inserted at `version=1`.

---

## 6. Authentication and Authorization System

### 6.1 API Key Lifecycle

```mermaid
flowchart LR
    A[POST /api/auth/api-keys] --> B[generate_api_key]
    B --> C["secrets.token_urlsafe(24) → 32 chars"]
    C --> D["full_key = 'tk_' + random_part"]
    D --> E["key_prefix = full_key[:11] for display"]
    D --> F["key_hash = HMAC-SHA256(pepper, full_key)"]
    E --> G[Store in api_keys table]
    F --> G
    G --> H["Return full_key ONCE to user\n(never stored in plain text)"]
    H --> I[User stores full_key securely]
    I --> J["Future requests: Authorization: Bearer tk_..."]
```

**Key generation details:**
- `secrets.token_urlsafe(24)` produces a 32-character URL-safe random string
- The full key is `tk_` + 32 chars = 35 characters total
- The display prefix is `tk_` + first 8 chars of random part (11 chars total)
- Only the HMAC-SHA256 hash is stored in the database

**Pepper configuration:**
```python
# temper_ai/auth/api_key_auth.py:20-22
_API_KEY_PEPPER = os.environ.get("TEMPER_API_KEY_PEPPER", "")
# If not set: plain SHA-256 (development mode, logged as warning)
# If set: HMAC-SHA256(pepper, key) — production recommended
```

### 6.2 API Key Authentication Flow

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant require_auth
    participant DB

    Client->>FastAPI: GET /api/workflows Authorization: Bearer tk_abc123...
    FastAPI->>require_auth: Request object
    require_auth->>require_auth: _extract_bearer_token(request)
    Note over require_auth: auth_header[len("Bearer "):].strip()
    require_auth->>require_auth: token.startswith("tk_")?
    require_auth->>require_auth: hash_api_key(token) → SHA256/HMAC hex
    require_auth->>DB: SELECT api_keys JOIN tenant_memberships WHERE key_hash = ?
    DB-->>require_auth: {api_key_id, user_id, tenant_id, is_active, expires_at, role}
    require_auth->>DB: UPDATE api_keys SET last_used_at=now, total_requests+=1
    require_auth-->>FastAPI: AuthContext{user_id, tenant_id, role="editor", api_key_id}
    FastAPI->>FastAPI: Route handler(ctx=AuthContext)
    FastAPI-->>Client: 200 OK (tenant-scoped data)
```

### 6.3 Role-Based Access Control (RBAC)

```python
# temper_ai/auth/api_key_auth.py:183-200
def require_role(*allowed_roles: str):
    """Factory: create a dependency checking user's role.

    Usage in routes:
        @router.post("/configs", dependencies=[Depends(require_role("owner", "editor"))])
    """
    allowed = frozenset(allowed_roles)
    async def _check_role(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
        if ctx.role not in allowed:
            raise HTTPException(403, detail=f"Required: {sorted(allowed)}, got: {ctx.role}")
        return ctx
    return _check_role
```

### 6.4 WebSocket Authentication

WebSocket connections cannot use standard HTTP headers after the handshake. The system implements a two-phase approach:

**Phase 1: REST ticket exchange**
```
POST /api/auth/ws-ticket  Authorization: Bearer tk_...
→ Returns: { "ticket": "wst_AbCdEf..." }
```

**Phase 2: WebSocket connection with ticket**
```
WS /ws?token=wst_AbCdEf...
→ Server validates ticket (30-second TTL, one-time use)
→ Connection is associated with the same AuthContext
```

**Ticket store (`temper_ai/auth/ws_tickets.py`):**
```python
TICKET_TTL_SECONDS = 30          # Expires in 30 seconds
TICKET_PREFIX = "wst_"           # Distinguishable from API keys
TICKET_RANDOM_BYTES = 24         # Same entropy as API key random part

# In-memory dict; tickets are popped on use (one-time)
_store: dict[str, _TicketEntry] = {}
```

### 6.5 Session Management

The `InMemorySessionStore` (`temper_ai/auth/session.py`) provides OAuth-based session management with:

- **LRU Eviction:** `OrderedDict` with `move_to_end()` for O(1) LRU operations
- **Max Sessions:** 10,000 (configurable)
- **Lazy Cleanup:** Expired sessions purged every 100 lookups
- **Session ID Format:** `sess_` + `secrets.token_urlsafe(TOKEN_BYTES_SESSION)`
- **TTL:** Default from `DEFAULT_SESSION_TTL_SECONDS` constant

Note: The `InMemorySessionStore` is documented as development-only. Production deployments should use a DB-backed session store.

### 6.6 Config Sync: YAML to Database

```mermaid
sequenceDiagram
    participant Client as HTTP Client
    participant ConfigSyncService
    participant PydanticModel
    participant Database

    Client->>ConfigSyncService: import_config(tenant_id, "workflow", "my_wf", yaml_str, user_id)
    ConfigSyncService->>ConfigSyncService: _validate_config_type("workflow")
    ConfigSyncService->>ConfigSyncService: _parse_yaml(yaml_str) → dict
    ConfigSyncService->>PydanticModel: WorkflowConfig.model_validate(dict)
    PydanticModel-->>ConfigSyncService: Validated (or raises ValueError)
    ConfigSyncService->>Database: SELECT * FROM workflow_configs WHERE tenant_id=? AND name=?
    Database-->>ConfigSyncService: existing record or None
    alt Record exists
        ConfigSyncService->>Database: UPDATE config_data, version+=1, updated_by, updated_at
    else New record
        ConfigSyncService->>Database: INSERT new row at version=1
    end
    ConfigSyncService-->>Client: {"name": "my_wf", "config_type": "workflow", "version": 2}
```

**Validation chain:**
1. `config_type` must be `workflow | stage | agent`
2. YAML is parsed with `yaml.safe_load()` (no arbitrary code execution)
3. Parsed dict is validated against the appropriate Pydantic model (`WorkflowConfig`, `StageConfig`, or `AgentConfig`)
4. Only valid configs are written to DB

---

## 7. Memory System

### 7.1 Architecture Overview

The memory system follows the **Strategy pattern** — a common `MemoryStoreProtocol` interface with four interchangeable adapters, selected at runtime via `MemoryProviderRegistry`.

```mermaid
classDiagram
    class MemoryStoreProtocol {
        <<Protocol>>
        +add(scope, content, memory_type, metadata) str
        +search(scope, query, limit, threshold, memory_type) list[MemoryEntry]
        +get_all(scope, memory_type) list[MemoryEntry]
        +delete(scope, memory_id) bool
        +delete_all(scope) int
    }

    class InMemoryAdapter {
        -_store dict[str, list[MemoryEntry]]
        -_lock RLock
        +add(scope, content, memory_type, metadata) str
        +search(scope, query, ...) list[MemoryEntry]
        +get_all(scope, memory_type) list[MemoryEntry]
        +delete(scope, memory_id) bool
        +delete_all(scope) int
    }

    class PGAdapter {
        -_use_fts bool
        -_engine Engine
        +add(scope, content, memory_type, metadata) str
        +search(scope, query, ...) list[MemoryEntry]
        -_fts_search(session, scope, query, ...) list[MemoryEntry]
        -_ilike_search(session, scope, query, ...) list[MemoryEntry]
        +get_all(scope, memory_type) list[MemoryEntry]
        +delete(scope, memory_id) bool
        +delete_all(scope) int
    }

    class Mem0Adapter {
        -_memory Memory
        +add(scope, content, memory_type, metadata) str
        +search(scope, query, ...) list[MemoryEntry]
        +get_all(scope, memory_type) list[MemoryEntry]
        +delete(scope, memory_id) bool
        +delete_all(scope) int
    }

    class KnowledgeGraphMemoryAdapter {
        -_store PortfolioStore
        -_query KnowledgeQuery
        +add(scope, ...) str
        +search(scope, query, ...) list[MemoryEntry]
        +get_all(scope, ...) list[MemoryEntry]
        +delete(scope, ...) bool
        +delete_all(scope) int
    }

    class MemoryService {
        -_adapter MemoryStoreProtocol
        +build_scope(tenant_id, workflow_name, agent_name, namespace) MemoryScope
        +retrieve_context(scope, query, ...) str
        +store_episodic(scope, content, ...) str
        +store_procedural(scope, content, ...) str
        +store_cross_session(scope, content, ...) str
        +search(scope, query, ...) list[MemoryEntry]
        +clear_memories(scope) int
        +list_memories(scope, ...) list[MemoryEntry]
        +retrieve_with_shared(scope, shared_scope, query, ...) str
    }

    class MemoryProviderRegistry {
        <<Singleton>>
        -_instance MemoryProviderRegistry
        -_providers dict[str, type]
        -_lock RLock
        +get_instance() MemoryProviderRegistry
        +get_provider_class(name) type
        +register_provider(name, cls) void
    }

    MemoryStoreProtocol <|.. InMemoryAdapter
    MemoryStoreProtocol <|.. PGAdapter
    MemoryStoreProtocol <|.. Mem0Adapter
    MemoryStoreProtocol <|.. KnowledgeGraphMemoryAdapter
    MemoryService --> MemoryStoreProtocol : uses
    MemoryService --> MemoryProviderRegistry : resolves via
    MemoryProviderRegistry --> InMemoryAdapter : eager
    MemoryProviderRegistry --> PGAdapter : lazy
    MemoryProviderRegistry --> Mem0Adapter : lazy
    MemoryProviderRegistry --> KnowledgeGraphMemoryAdapter : lazy
```

### 7.2 Memory Scope

`MemoryScope` is a frozen dataclass that uniquely identifies a memory partition:

```python
# temper_ai/memory/_schemas.py:13-32
@dataclass(frozen=True)
class MemoryScope:
    tenant_id: str = DEFAULT_TENANT_ID    # Tenant isolation
    workflow_name: str = ""               # Workflow context
    agent_name: str = ""                  # Agent context
    namespace: str | None = None          # Custom namespace (overrides workflow_name)
    agent_id: str | None = None           # M9: persistent agent ID (overrides agent_name)

    @property
    def scope_key(self) -> str:
        """Format: 'tenant_id:namespace_or_workflow:agent_id_or_name'"""
        middle = self.namespace if self.namespace else self.workflow_name
        agent_part = self.agent_id if self.agent_id else self.agent_name
        return SCOPE_SEPARATOR.join([self.tenant_id, middle, agent_part])
```

**Example scope keys:**
- `default:my_workflow:researcher_agent`
- `tenant-123:published_knowledge__researcher:researcher`
- `default::` (shared across all workflows for a tenant)

### 7.3 Memory Types

| Type | Constant | Use Case |
|------|----------|----------|
| `episodic` | `MEMORY_TYPE_EPISODIC` | Specific past events and experiences |
| `procedural` | `MEMORY_TYPE_PROCEDURAL` | Best practices, learned procedures |
| `cross_session` | `MEMORY_TYPE_CROSS_SESSION` | Persistent knowledge across runs |
| `published` | `MEMORY_TYPE_PUBLISHED` | Cross-agent shared knowledge (M9) |
| `semantic` | `MEMORY_TYPE_SEMANTIC` | Knowledge graph concepts (KG adapter) |

### 7.4 Adapter Comparison

| Adapter | Search Method | Production? | Dependencies |
|---------|--------------|-------------|--------------|
| `in_memory` | Substring match | No (testing/fallback) | None |
| `pg` | ILIKE (default) or PostgreSQL FTS (`to_tsvector/to_tsquery`) | Yes | PostgreSQL |
| `mem0` | Vector similarity (ChromaDB + sentence-transformers or Ollama) | Yes | `uv sync --extra memory` |
| `knowledge_graph` | Substring on concept names | Read-only | `portfolio.store.PortfolioStore` |

**Provider Registry (lazy loading):**
```python
# temper_ai/memory/registry.py:44-51
def _register_builtins(self) -> None:
    from temper_ai.memory.adapters.in_memory import InMemoryAdapter
    self._providers[PROVIDER_IN_MEMORY] = InMemoryAdapter        # Eager
    self._providers[PROVIDER_PG] = _LAZY_SENTINEL                # Deferred
    self._providers[PROVIDER_MEM0] = _LAZY_SENTINEL              # Deferred
    self._providers[PROVIDER_KNOWLEDGE_GRAPH] = _LAZY_SENTINEL   # Deferred
```

The `_LAZY_SENTINEL` pattern avoids import overhead for PostgreSQL, Mem0, and KnowledgeGraph dependencies until explicitly requested.

### 7.5 PostgreSQL Memory Adapter Details

**Table: `memory_records`** (defined in `pg_adapter.py`)

| Column | Type | Index | Notes |
|--------|------|-------|-------|
| `id` | String PK | - | UUID hex |
| `scope_key` | String | `idx_mr_scope_key` | Tenant:workflow:agent composite |
| `content` | Text | - | The actual memory text |
| `memory_type` | String | `idx_mr_memory_type` | episodic/procedural/etc |
| `metadata_json` | Text | - | JSON-serialized dict |
| `relevance_score` | Float | - | Client-side scoring result |
| `created_at` | DateTime(timezone) | `idx_mr_created_at` | UTC aware |
| `tsv` | tsvector | GIN `idx_mr_tsv` | Optional FTS column |

**FTS mode** (enabled via `config["use_fts"] = True`):
```sql
-- Search query:
SELECT *, ts_rank(tsv, to_tsquery('english', 'agent & optimization')) AS rank
FROM memory_records
WHERE scope_key = :scope_key
AND tsv @@ to_tsquery('english', 'agent & optimization')
ORDER BY rank DESC LIMIT :limit

-- ts_rank normalization:
score = rank / (rank + 1.0)  -- Prevents division by zero; score in [0,1)
```

**ILIKE mode (default):**
```sql
SELECT * FROM memory_records
WHERE scope_key = :scope_key
AND content ILIKE :pattern ESCAPE '\'
-- pattern = '%escaped_query%'
-- Relevance = len(query) / len(content)  -- Simple ratio, max 1.0
```

### 7.6 Time-Decay Scoring

When `decay_factor < 1.0`, older memories have reduced relevance:

```python
# temper_ai/memory/service.py:31-44
def _apply_decay(entries, decay_factor):
    """Exponential time-decay: score *= decay_factor ^ age_days"""
    now = datetime.now(UTC)
    for entry in entries:
        age_seconds = max((now - entry.created_at).total_seconds(), 0)
        age_days = age_seconds / SECONDS_PER_DAY
        entry.relevance_score *= math.pow(decay_factor, age_days)
    return entries
```

**Example:** With `decay_factor=0.9`, a memory 10 days old has its score multiplied by `0.9^10 = 0.349`.

### 7.7 Memory Extraction via LLM

`extractors.py` provides LLM-based pattern extraction from agent outputs:

```python
# temper_ai/memory/extractors.py:34-59
def extract_procedural_patterns(text: str, llm_fn: Callable[[str], str]) -> list[str]:
    """Extract up to 5 procedural patterns using an LLM call.

    The EXTRACTION_PROMPT instructs the LLM to return a numbered list.
    Response is parsed with regex: r"^\s*\d+[\.\)][ \t]*(.+)"
    Each pattern is truncated to MAX_PATTERN_LENGTH (500 chars).
    """
```

### 7.8 Cross-Pollination: Knowledge Sharing Between Agents

```mermaid
flowchart TD
    A[Agent A completes task] -->|publishes| B[publish_knowledge]
    B --> C["MemoryScope: namespace='published_knowledge__agent_a'"]
    C --> D[memory_service.store with memory_type='published']

    E[Agent B starts task] -->|subscribes to A| F[retrieve_subscribed_knowledge]
    F --> G["For each agent in subscribe_to list:"]
    G --> H["Build published scope for that agent"]
    H --> I["memory_service.search with relevance_threshold=0.7"]
    I --> J[Collect results with agent_name labels]
    J --> K[format_cross_pollination_context]
    K --> L["Markdown: '[From agent_a]: key insight...'"]
    L --> M[Injected into Agent B's prompt context]
```

**Key function signatures:**
```python
# temper_ai/memory/cross_pollination.py
publish_knowledge(
    agent_name: str,
    content: str,
    memory_service: Any,
    metadata: dict | None = None,
    memory_type: str = "published",
) -> str | None  # Returns memory entry ID

retrieve_subscribed_knowledge(
    subscribe_to: list[str],        # List of agent names to pull from
    query: str,
    memory_service: Any,
    retrieval_k: int = 5,
    relevance_threshold: float = 0.7,
) -> list[dict]  # [{agent_name, content, relevance_score}]
```

**Namespace convention:** `published_knowledge__<agent_name>`

Content is truncated at `MAX_CONTENT_LENGTH = 10000` characters before storage.

### 7.9 Memory Context Formatting

The `formatter.py` module converts `MemorySearchResult` to a Markdown string for prompt injection:

```
# Relevant Memories

## Episodic
- [0.92] Previous research showed OAuth2 preferred for SaaS...
- [0.78] User requested minimal dependencies...

## Procedural
- [0.88] For fintech products, always include rate limiting...
```

Output is truncated to `MAX_MEMORY_CONTEXT_CHARS` (default from constants) with a truncation suffix.

---

## 8. Agent Registry (M9)

### 8.1 Overview

The agent registry persists "registered" agents that survive across sessions. Unlike workflow-scoped agents (ephemeral), registered agents maintain a fixed memory namespace and can be invoked by name indefinitely.

### 8.2 Agent Registry Table

**Table: `agent_registry`** (defined in `models_registry.py`)

| Column | Type | Constraint | Notes |
|--------|------|-----------|-------|
| `id` | String PK | - | UUID |
| `name` | String(128) | UNIQUE `uq_agent_registry_name` | Indexed |
| `description` | String | default `""` | |
| `version` | String | default `"1.0"` | |
| `agent_type` | String | default `"standard"` | |
| `config_path` | String | nullable | Original YAML file path |
| `config_snapshot` | JSON | - | Frozen config at registration time |
| `memory_namespace` | String | default `""` | Fixed memory scope key |
| `status` | String | indexed | `registered | active | inactive` |
| `total_invocations` | Integer | default `0` | Incremented on each invoke |
| `registered_at` | DateTime | - | UTC timestamp |
| `last_active_at` | DateTime | nullable | Updated on invoke |
| `metadata_json` | JSON | nullable | Arbitrary extra data |

### 8.3 Agent Registration Flow

```mermaid
flowchart TD
    A[POST /api/agents\nbody: configs/agents/researcher.yaml] --> B[AgentRegistryService.register_agent]
    B --> C[load_config_from_path: yaml.safe_load]
    C --> D{name field present?}
    D -->|No| E[ValueError: must have 'name' field]
    D -->|Yes| F[Build AgentRegistryEntry]
    F --> G["id = uuid4()"]
    F --> H["memory_namespace = 'persistent__<name>'"]
    F --> I["config_snapshot = full config dict"]
    G --> J[AgentRegistryStore.register]
    H --> J
    I --> J
    J --> K[Session.add AgentRegistryDB row]
    K --> L[session.commit]
    L --> M[Return AgentRegistryEntry]
```

**Memory namespace pattern:**
```
memory_namespace = "persistent__<agent_name>"
```
This creates a fixed, isolated memory space that persists even after the agent instance is garbage collected.

### 8.4 Agent Invocation Flow

```mermaid
flowchart TD
    A[AgentRegistryService.invoke name message] --> B[AgentRegistryStore.get by name]
    B --> C{Found?}
    C -->|No| D[KeyError: Agent not found]
    C -->|Yes| E[store.update_status to 'active']
    E --> F[execution_id = uuid4 hex]
    F --> G[_load_agent: StandardAgent from config_snapshot]
    G --> H["config_snapshot['memory_namespace'] = entry.memory_namespace"]
    H --> I[agent.run message.content]
    I --> J[store.update_last_active: last_active_at=now, total_invocations+=1]
    J --> K[Return MessageResponse{content, agent_name, execution_id}]
```

**Key design note:** The agent's `config_snapshot` is loaded from the DB row, not from the YAML file. This means the registered config is frozen at registration time. Updates require re-registration.

---

## 9. Lifecycle Persistence

### 9.1 Tables

**`lifecycle_adaptations`** — Records of workflow stage adaptations applied by the lifecycle system:

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | UUID |
| `workflow_id` | String | Indexed |
| `profile_name` | String | Indexed; which profile triggered this |
| `characteristics` | JSON | Detected workflow characteristics |
| `rules_applied` | JSON | List of rule names applied |
| `stages_original` | JSON | Stage list before adaptation |
| `stages_adapted` | JSON | Stage list after adaptation |
| `experiment_id` | String | Optional A/B experiment linkage |
| `experiment_variant` | String | Optional variant name |
| `created_at` | DateTime | UTC |

**`lifecycle_profiles`** — Named profiles that define adaptation rules:

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | UUID |
| `name` | String | UNIQUE |
| `description` | String | |
| `version` | String | default `"1.0"` |
| `product_types` | JSON | List of applicable product types |
| `rules` | JSON | List of rule dicts |
| `enabled` | Boolean | default `True` |
| `source` | String | `manual | auto | learning` |
| `confidence` | Float | default `1.0` |
| `min_autonomy_level` | Integer | Minimum autonomy level required |
| `requires_approval` | Boolean | default `True` |
| `created_at` / `updated_at` | DateTime | UTC |

### 9.2 LifecycleStore Pattern

The `LifecycleStore` creates its own engine per instance (not the global manager), following the domain store pattern:

```python
class LifecycleStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.engine = create_app_engine(self.database_url)
        SQLModel.metadata.create_all(self.engine, tables=[...])
```

This pattern is replicated across Goals, Portfolio, and Learning stores. Each domain store:
1. Creates its own engine (configurable via `database_url` parameter)
2. Creates only its own tables with `create_all(tables=[...])`
3. Opens short-lived sessions per operation (no connection sharing)

---

## 10. Goals Persistence

### 10.1 Tables

**`goal_proposals`** — Autonomous improvement proposals from analyzers:

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | UUID |
| `goal_type` | String | Indexed; e.g., `cost_reduction`, `performance` |
| `title` / `description` | String | Human-readable proposal |
| `status` | String | Indexed; `proposed | approved | rejected | applied` |
| `risk_assessment` | JSON | Risk analysis dict |
| `effort_estimate` | String | `low | medium | high` |
| `expected_impacts` | JSON | List of impact estimate dicts |
| `evidence` | JSON | Supporting data from analyzers |
| `source_product_type` | String | Indexed; product type that generated this |
| `source_agent_id` | String | Indexed; M9 persistent agent ID (nullable) |
| `applicable_product_types` | JSON | List of product types this applies to |
| `proposed_actions` | JSON | Ordered list of action strings |
| `priority_score` | Float | Sorting: higher = more important |
| `reviewer` / `review_reason` / `reviewed_at` | Various | Human review audit fields |
| `created_at` / `updated_at` | DateTime | UTC |

**`analysis_runs`** — Records of goal analysis orchestrations:

| Column | Notes |
|--------|-------|
| `id`, `started_at`, `completed_at` | Run lifecycle timestamps |
| `status` | `running | completed | failed` |
| `proposals_generated` | Count of proposals created |
| `analyzer_stats` | JSON dict with per-analyzer metrics |
| `error_message` | Set if status is `failed` |

### 10.2 GoalStore Operations

```python
# Key query patterns in temper_ai/goals/store.py
store.list_proposals(
    status="proposed",             # Filter by lifecycle status
    goal_type="cost_reduction",    # Filter by goal category
    product_type="saas_b2b",       # Filter by product type
    agent_id="persistent__planner" # M9: filter by persistent agent
)
store.count_by_status()  # Returns {"proposed": 12, "approved": 3, ...}
store.count_proposals_today()  # Proposals in last 24 hours
```

---

## 11. Portfolio Persistence

### 11.1 Tables

**`portfolios`** — Portfolio definitions (groups of related products):

| Column | Notes |
|--------|-------|
| `id`, `name` (UNIQUE, indexed), `description` | Identity |
| `config` | JSON: portfolio configuration |
| `enabled` | Boolean |
| `created_at`, `updated_at` | Timestamps |

**`product_runs`** — Execution log per product:

| Column | Notes |
|--------|-------|
| `id`, `portfolio_id`, `product_type`, `workflow_id` | All indexed |
| `status` | Indexed; `running | completed | failed` |
| `cost_usd`, `duration_s` | Performance metrics |
| `success` | Boolean outcome |
| `metadata_json` | Arbitrary metrics |
| `started_at`, `completed_at` | Timing |

**`shared_components`** — Detected component similarities between stages:

| Column | Notes |
|--------|-------|
| `source_stage`, `target_stage` | Indexed stage names |
| `similarity` | Float 0.0–1.0 |
| `shared_keys`, `differing_keys` | JSON lists of config key names |
| `status` | `detected | confirmed | dismissed` |

**`kg_concepts`** — Knowledge graph nodes:

| Column | Notes |
|--------|-------|
| `id`, `name` (indexed), `concept_type` (indexed) | |
| `properties` | JSON: arbitrary concept attributes |
| `created_at` | UTC |

**`kg_edges`** — Knowledge graph edges:

| Column | Notes |
|--------|-------|
| `source_id`, `target_id` (both indexed), `relation` (indexed) | |
| `weight` | Float edge weight |
| `properties` | JSON |

**`tech_compatibility`** — Technology pair compatibility scores:

| Column | Notes |
|--------|-------|
| `tech_a`, `tech_b` (both indexed) | Technology names |
| `compatibility_score` | Float 0.0–1.0 |
| `notes` | Human-readable explanation |

**`portfolio_snapshots`** — Periodic scorecard snapshots:

| Column | Notes |
|--------|-------|
| `portfolio_id`, `product_type` (both indexed) | |
| `success_rate`, `cost_efficiency`, `trend`, `utilization`, `composite_score` | Float metrics |
| `created_at` | UTC; ordered DESC for trend analysis |

---

## 12. Learning and Auto-Tune Persistence

### 12.1 Tables

**`learned_patterns`** — Patterns mined from execution history:

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | UUID |
| `pattern_type` | String | Indexed; `agent_performance | model_effectiveness | failure | cost | collaboration` |
| `title` / `description` | String | Human-readable |
| `evidence` | JSON | Supporting data from miners |
| `confidence` | Float | Confidence score; sorted DESC |
| `impact_score` | Float | Estimated impact magnitude |
| `recommendation` | String | Actionable recommendation text |
| `status` | String | Indexed; `active | applied | dismissed | experiment` |
| `source_workflow_ids` | JSON | List of workflow IDs that contributed |
| `created_at` / `updated_at` | DateTime | UTC |

**`mining_runs`** — Records of pattern mining orchestrations:

| Column | Notes |
|--------|-------|
| `status` | `running | completed | failed` |
| `patterns_found`, `patterns_new` | Count metrics |
| `novelty_score` | Float 0.0–1.0 novelty of findings |
| `miner_stats` | JSON: per-miner stats |

**`tune_recommendations`** — Actionable config-change recommendations:

| Column | Type | Notes |
|--------|------|-------|
| `pattern_id` | String | Indexed; links to `learned_patterns` |
| `config_path` | String | Target YAML file path |
| `field_path` | String | Dot-notation path within config |
| `current_value` | String | What the value is now |
| `recommended_value` | String | What it should be changed to |
| `rationale` | String | Why this change is recommended |
| `status` | String | `pending | applied | dismissed` |

### 12.2 Pattern Type Miners

Each `pattern_type` corresponds to a dedicated miner class:

| Pattern Type | Miner | What It Looks For |
|-------------|-------|-------------------|
| `agent_performance` | `AgentPerformanceMiner` | Success rates, latency outliers per agent |
| `model_effectiveness` | `ModelEffectivenessMiner` | Model-to-task fit, cost efficiency |
| `failure` | `FailurePatternMiner` | Common error fingerprints, retry patterns |
| `cost` | `CostPatternMiner` | Expensive operations, optimization opportunities |
| `collaboration` | `CollaborationPatternMiner` | Conflict patterns, consensus vs. debate outcomes |

---

## 13. Autonomy Orchestrator and Cross-Subsystem Coordination

### 13.1 Architecture

`PostExecutionOrchestrator` (`temper_ai/autonomy/orchestrator.py`) is the post-execution coordinator that calls all persistence subsystems after every workflow completes.

```python
# Subsystem execution order (with timeout check between each):
steps = [
    (config.learning_enabled, "_run_learning", "learning_result"),
    (config.goals_enabled, "_run_goals", "goals_result"),
    (config.auto_apply_learning or config.auto_apply_goals,
     "_run_feedback", "feedback_result"),
    (config.portfolio_enabled, "_run_portfolio", "portfolio_result"),
    (config.agent_memory_sync_enabled, "_run_agent_memory_sync", "agent_memory_result"),
]
```

**Error isolation:** Each subsystem is wrapped in `try/except`. A failure in learning does not prevent goals from running.

**Timeout enforcement:** `LOOP_TIMEOUT_SECONDS` (default 60s) caps total post-execution time. Steps are skipped if the deadline is exceeded.

### 13.2 Agent Memory Sync (M9)

```
_run_agent_memory_sync() →
  For each persistent agent found in context:
    MemoryService.store_cross_session(
      scope = persistent_agent_scope,
      content = execution_summary,
      metadata = {workflow_id, agent_name, outcome}
    )
```

This writes execution summaries into the persistent agent's memory namespace so future invocations can access cross-workflow learning.

---

## 14. Event Bus Persistence (M9)

### 14.1 Tables

**`event_log`** — Durable event log:

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | UUID |
| `event_type` | String | Indexed; e.g., `workflow.completed`, `stage.failed` |
| `timestamp` | DateTime | Indexed |
| `source_workflow_id` | String | Indexed; originating workflow |
| `source_stage_name` | String | Originating stage |
| `agent_id` | String | Originating persistent agent |
| `payload` | JSON | Event data |
| `consumed` | Boolean | default `False` |
| `consumed_at` | DateTime | When first consumed |
| `consumed_by` | String | Consumer identifier |

**`event_subscriptions`** — Registered subscriptions:

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | UUID |
| `subscriber_id` | String | Indexed; typically `agent_id` or `workflow_id` |
| `event_type` | String | Indexed; pattern matching |
| `workflow_name` | String | Optional: only trigger for specific workflow |
| `is_active` | Boolean | Indexed; soft-delete |
| `created_at` | DateTime | UTC |

### 14.2 Event Flow

```mermaid
flowchart TD
    A[workflow.completed event fired] --> B[TemperEventBus.publish]
    B --> C[ObservabilityEventBus.emit]
    C --> D[Store in event_log table: consumed=False]
    D --> E[Check event_subscriptions WHERE event_type MATCH AND is_active=True]
    E --> F{Matching subscriptions?}
    F -->|Yes| G[For each subscription, trigger callback]
    G --> H[Mark event_log.consumed=True, consumed_by=subscriber_id]
    F -->|No| I[Event remains unconsumed in log]

    J[POST /api/events/replay\nbody: workflow.completed, since=2h] --> K[Query event_log WHERE event_type AND timestamp > cutoff]
    K --> L[Re-emit each unconsumed event]
```

---

## 15. Alembic Migration System

### 15.1 Migration Chain

```
abd552d7a52e  (initial_schema)
    └── 9bba5a67eb64  (phase_1_model_changes)
        └── 99c79410e449  (phase_6_catch_up)
            └── b7e3f1a2c456  (add_error_fingerprints)
                └── c4d8e2f1a789  (add_attribution_lineage)
                    └── d5e6f7a8b901  (drop_m5_tables)
                        └── e6f7a8b90123  (add_server_runs)
                            └── f7a8b9012345  (add_learning_tables)
                                └── g8b9c0123456  (add_autonomy_tables)
                                    └── h9c0d1234567  (add_lifecycle_tables)
                                        └── j1e2f3456789  (add_portfolio_tables)
                                            └── k2f3g4567890  (add_alert_records)
                                                └── m9_001  (add_agent_registry_and_events)
                                                    └── opt_001  (add_agent_evaluation_results)
                                                        └── mt_001  (add_multi_tenancy)
                                                            └── p1_001  (tenant_scope_observability)
                                                                └── p1_002  (tenant_scope_secondary)
                                                                    └── HEAD
```

### 15.2 Initial Schema (abd552d7a52e)

Creates the core observability tables:
- `agent_merit_scores` — Merit tracking (no FK, standalone)
- `schema_version` — Migration tracking
- `system_metrics` — Time-series metrics
- `workflow_executions` — Root of the execution tree
- `rollback_snapshots` → FK to `workflow_executions`
- `stage_executions` → FK to `workflow_executions`
- `agent_executions` → FK to `stage_executions`
- `collaboration_events` → FK to `stage_executions`
- `rollback_events` → FK to `rollback_snapshots`
- `decision_outcomes` → FK to all three execution levels
- `llm_calls` → FK to `agent_executions`
- `tool_executions` → FK to `agent_executions`

### 15.3 Multi-Tenancy Migration (mt_001)

Creates:
- `tenants`, `users`, `tenant_memberships`, `api_keys`
- `workflow_configs`, `stage_configs`, `agent_configs`
- Adds `tenant_id` to `workflow_executions`, `stage_executions`, `agent_executions`
- Backfills existing rows with `DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"`

### 15.4 Tenant Scope Propagation (p1_001, p1_002)

Two follow-up migrations extend `tenant_id` to all remaining observability tables:

**p1_001** adds `tenant_id` to:
- `llm_calls`, `tool_executions`, `server_runs`

**p1_002** adds `tenant_id` to:
- `collaboration_events`, `agent_merit_scores`, `decision_outcomes`
- `system_metrics`, `error_fingerprints`, `alert_records`
- `rollback_snapshots`, `rollback_events`
- Backfills existing rows with `DEFAULT_TENANT_ID`

### 15.5 Alembic Configuration

```ini
# alembic.ini
[alembic]
script_location = %(here)s/alembic
prepend_sys_path = .
```

**Environment variable override:**
```bash
alembic -x "sqlalchemy.url=sqlite:///tmpdb" upgrade head  # Test migration
alembic upgrade head                                        # Production
alembic downgrade -1                                        # Roll back one step
alembic current                                             # Show current revision
```

**Production deployment pattern:**
```bash
ALEMBIC_MANAGED=1 python -m temper_ai.interfaces.cli.main serve  # Skip auto-create
alembic upgrade head                                               # Apply migrations
```

### 15.6 Domain Store Migration Strategy

The domain stores (Lifecycle, Goals, Portfolio, Learning) use `SQLModel.metadata.create_all(engine, tables=[...])` directly rather than Alembic. This is an acknowledged limitation:

- **Development:** Tables created automatically on first store instantiation
- **Production:** Tables also created automatically (not migration-managed)
- **Risk:** No rollback for domain store schema changes

This is called out as a technical debt item in Section 19.

---

## 16. Data Integrity and Validation

### 16.1 JSON Size Validation

All `JSON` fields with user-controlled content are pre-validated in model `__init__` methods:

```python
# temper_ai/storage/database/validators.py:16-58
def validate_json_size(
    data: dict,
    max_bytes: int = BYTES_PER_MB,   # 1MB default
    field_name: str = "JSON field"
) -> None:
    """Raises JSONSizeError if len(json.dumps(data).encode()) > max_bytes"""
```

**Size limits by field:**

| Model | Field | Limit |
|-------|-------|-------|
| `WorkflowExecution` | `workflow_config_snapshot` | 2MB |
| `WorkflowExecution` | `extra_metadata` | 512KB |
| `StageExecution` | `stage_config_snapshot` | 1MB |
| `StageExecution` | `input_data` | 1MB |
| `StageExecution` | `output_data` | 1MB |
| `AgentExecution` | `agent_config_snapshot` | 1MB |
| `AgentExecution` | `input_data` | 1MB |
| `AgentExecution` | `output_data` | 1MB |

### 16.2 Status Constraints

Database-level `CHECK` constraints enforce valid status values:

| Table | Constraint Name | Valid Values |
|-------|----------------|--------------|
| `workflow_executions` | `wf_valid_status` | `running, completed, failed, halted, timeout` |
| `stage_executions` | `stage_valid_status` | Same as workflow |
| `agent_executions` | `agent_valid_status` | Same as workflow |
| `llm_calls` | `llm_valid_status` | `success, error, timeout, cancelled` |
| `tool_executions` | `tool_valid_status` | `success, error, failed, timeout, cancelled` |
| `rollback_events` | `rollback_valid_status` | `completed, partial, failed` |
| `decision_outcomes` | `outcome_valid_value` | `success, failure, neutral, mixed` |
| `tenant_memberships` | `membership_valid_role` | `owner, editor, viewer` |

### 16.3 Unique Constraints

| Table | Constraint | Purpose |
|-------|-----------|---------|
| `agent_merit_scores` | `(agent_name, domain)` | One merit record per agent per domain |
| `agent_registry` | `name` | Unique registered agent name |
| `tenants` | `slug` | URL-safe tenant identifier |
| `users` | `email` | One account per email |
| `tenant_memberships` | `(tenant_id, user_id)` | One role per user per tenant |
| `workflow_configs` | `(tenant_id, name)` | Unique config name within tenant |
| `stage_configs` | `(tenant_id, name)` | Unique config name within tenant |
| `agent_configs` | `(tenant_id, name)` | Unique config name within tenant |
| `agent_evaluation_results` | `(agent_execution_id, evaluation_name)` | One eval result per run per name |

---

## 17. Design Patterns and Architectural Decisions

### 17.1 Patterns Identified

**1. Repository Pattern (Store Classes)**

All domain stores (`GoalStore`, `LifecycleStore`, `PortfolioStore`, `LearningStore`) and the observability system implement the Repository pattern: they provide an abstraction layer over the database, exposing domain-specific operations rather than raw SQL.

```python
# Consistent interface across all stores:
store.save_X(record: XModel) -> None       # Insert or update
store.get_X(id: str) -> XModel | None      # Fetch by PK
store.list_X(filters...) -> list[XModel]  # Filtered list
store.count_X(filters...) -> int           # Aggregate count
```

**2. Protocol-Based Adapter Pattern (Memory System)**

`MemoryStoreProtocol` is a `runtime_checkable` Protocol (structural subtyping). Any class implementing the five required methods (`add`, `search`, `get_all`, `delete`, `delete_all`) is a valid adapter without inheriting from a base class.

**3. Singleton with Lazy Initialization (Database Manager)**

```python
_db_manager: DatabaseManager | None = None
_db_lock = threading.Lock()

def init_database(...) -> DatabaseManager:  # Thread-safe double-checked locking
def get_database() -> DatabaseManager:      # Fails fast if not initialized
def get_session() -> Generator[Session]:    # Primary consumer interface
```

**4. Lazy Import (Memory Registry, Config Sync)**

Providers (PG, Mem0, KnowledgeGraph) and config validators (WorkflowConfig, StageConfig, AgentConfig) are imported only when first requested. This keeps startup times fast and prevents circular imports.

**5. Upsert via `session.merge()` (Domain Stores)**

Domain stores use SQLAlchemy's `session.merge()` which performs an "insert or update" based on primary key match. This simplifies store logic — callers never need to check if a record exists.

**6. Frozen Dataclass for Scoping (MemoryScope)**

`MemoryScope` is `@dataclass(frozen=True)` — immutable once created. This prevents scope mutation bugs and allows scope objects to be used as dict keys.

**7. Context Manager for Session Safety**

The `@contextmanager` decorator on `DatabaseManager.session()` guarantees commit/rollback/close semantics regardless of exception type. This prevents connection leaks and partial writes.

**8. Backward Compatibility Flag (`auth_enabled`)**

```python
# From app.py pattern:
auth_enabled = mode == "server"
# If not server mode: routes don't declare require_auth dependency
# No middleware, no global interception — per-route opt-in
```

### 17.2 Key Architectural Decisions

**Decision 1: Separate Engine per Domain Store**

Domain stores (Lifecycle, Goals, Portfolio, Learning) each create their own engine rather than sharing the global `DatabaseManager`. This allows domain stores to use different database URLs in testing and provides isolation between subsystems.

**Trade-off:** More connections consumed; but each store only opens sessions during active operations and closes them immediately.

**Decision 2: `tenant_id` as Column (Not Schema)**

Rather than PostgreSQL schemas or separate databases per tenant, isolation is enforced via a `tenant_id` column on every table plus query-level filtering helpers. This simplifies operations (single Alembic migration chain, single backup) at the cost of requiring explicit `WHERE tenant_id = ?` clauses.

**Decision 3: SHA-256/HMAC vs. bcrypt for API Keys**

API keys are hashed with HMAC-SHA256 (with pepper) rather than bcrypt. Rationale: API keys are already high-entropy random values (`secrets.token_urlsafe(24)`), so password-stretching algorithms like bcrypt are unnecessary. SHA-256 is O(1) vs. bcrypt's intentional slowness, making API key lookups faster under load.

**Decision 4: In-Memory Session Store**

Sessions are stored in an `OrderedDict` in process memory rather than the database. This is explicitly documented as development-only. Production deployments should replace `InMemorySessionStore` with a database-backed implementation.

**Decision 5: SQLModel over Pure SQLAlchemy**

SQLModel combines Pydantic validation with SQLAlchemy ORM mapping. This reduces boilerplate (one class serves as both Pydantic schema and ORM model) and ensures type safety at the Python layer.

**Decision 6: Alembic Only for Observability Tables**

The initial observability tables (the core hierarchy) are Alembic-managed. Domain tables (Lifecycle, Goals, Portfolio, Learning) use `create_all()`. This is a pragmatic split: core tables need careful migration management; domain tables were added incrementally and rely on SQLModel's auto-create.

---

## 18. Extension and Integration Guide

### 18.1 Adding a New Domain Store

To add a new persistent domain (e.g., `experiments`):

1. Create `temper_ai/experiments/models.py` with SQLModel table classes:
```python
class ExperimentRecord(SQLModel, table=True):
    __tablename__ = "experiments"
    id: str = Field(primary_key=True)
    # ...fields...
```

2. Create `temper_ai/experiments/store.py` following the domain store pattern:
```python
class ExperimentStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.engine = create_app_engine(database_url or get_database_url())
        SQLModel.metadata.create_all(self.engine, tables=[ExperimentRecord.__table__])
```

3. Add an Alembic migration in `alembic/versions/` for production deployments.

### 18.2 Adding a New Memory Adapter

1. Implement the `MemoryStoreProtocol` interface (all 5 methods)
2. Register with the provider registry:
```python
from temper_ai.memory.registry import MemoryProviderRegistry
MemoryProviderRegistry.get_instance().register_provider("my_provider", MyAdapter)
```
3. Configure agents to use it:
```yaml
# configs/agents/my_agent.yaml
memory:
  provider: my_provider
  config:
    custom_setting: value
```

### 18.3 Adding Tenant-Aware Tables

For any new table that should be tenant-scoped:

1. Add `tenant_id: str | None = Field(default=None, index=True)` to the model
2. Always use `scoped_query(session, Model, ctx.tenant_id)` in route handlers
3. Create a migration that adds `tenant_id` with backfill to `DEFAULT_TENANT_ID`

### 18.4 Using the Auth Dependency

```python
# Route requiring authentication:
from temper_ai.auth.api_key_auth import require_auth, require_role, AuthContext
from fastapi import Depends

@router.get("/my-resource")
async def get_resource(ctx: AuthContext = Depends(require_auth)):
    # ctx.tenant_id, ctx.user_id, ctx.role are available
    with get_session() as session:
        items = scoped_query(session, MyModel, ctx.tenant_id).all()
    return items

# Route requiring minimum role:
@router.delete("/my-resource/{id}")
async def delete_resource(
    id: str,
    ctx: AuthContext = Depends(require_role("owner", "editor"))
):
    ...
```

### 18.5 Creating Alembic Migrations

```bash
# Auto-generate from model changes:
alembic revision --autogenerate -m "add_my_new_table"

# For SQLite test compatibility:
alembic -x "sqlalchemy.url=sqlite:///tmpdb" revision --autogenerate -m "..."

# Apply:
alembic upgrade head

# Roll back:
alembic downgrade -1
```

---

## 19. Observations and Recommendations

### 19.1 Strengths

**1. Comprehensive Observability Schema**
The `workflow_executions → stage_executions → agent_executions → llm_calls/tool_executions` hierarchy provides complete execution lineage. Every LLM call can be traced back to the originating workflow.

**2. Well-Designed Memory Adapter Pattern**
The `MemoryStoreProtocol` + lazy registry is textbook Strategy pattern. Swapping from in-memory to PostgreSQL to Mem0 requires only a config change. The `scope_key` design cleanly handles tenant, workflow, and agent namespacing in a single string.

**3. Principled API Key Security**
Using HMAC-SHA256 with a server-side pepper, never storing plaintext keys, updating `last_used_at` on every request, and supporting expiry and revocation covers the key security requirements.

**4. Atomic Session Semantics**
The context manager pattern (`try: yield session; commit() except: rollback() finally: close()`) is consistently applied and prevents partial writes and connection leaks.

**5. Migration Chain Completeness**
The Alembic migration chain covers all schema evolution from the initial schema through M10 multi-tenancy, with proper backfill of `tenant_id` for existing rows.

**6. JSON Size Guards**
Pre-validating JSON field sizes in `__init__` methods prevents unbounded JSONB growth that would degrade query performance.

### 19.2 Areas of Concern

**1. Domain Store Migrations Not Alembic-Managed**
`LifecycleStore`, `GoalStore`, `PortfolioStore`, and `LearningStore` use `SQLModel.metadata.create_all()` for their tables. This means:
- No migration history for these tables
- No rollback capability for schema changes
- No `alembic history` visibility
- Risk of schema drift between environments

**Recommendation:** Add Alembic migrations for all domain store tables and gate creation on `ALEMBIC_MANAGED` env var (same pattern as core tables).

**2. In-Memory Session Store is Production-Unsafe**
`InMemorySessionStore` is explicitly documented as development-only but is the only available implementation. Sessions are lost on process restart; no session sharing between horizontally scaled instances.

**Recommendation:** Implement `DBSessionStore` backed by a `sessions` table in PostgreSQL, or integrate Redis.

**3. No Row-Level Security (RLS)**
Tenant isolation relies solely on application-layer `WHERE tenant_id = ?` queries. A query bug could expose cross-tenant data. PostgreSQL Row-Level Security policies would provide defense in depth.

**Recommendation:** Consider adding PostgreSQL RLS policies as a secondary enforcement layer, at least for the most sensitive tables.

**4. Domain Stores Create Independent Engine Instances**
Each `GoalStore`, `PortfolioStore`, `LifecycleStore`, and `LearningStore` instance creates a new SQLAlchemy engine. In production, this could exhaust the PostgreSQL connection limit if many stores are instantiated concurrently.

**Recommendation:** Refactor domain stores to accept an optional engine parameter, defaulting to the global `get_database().engine`. This allows connection pooling to be shared.

**5. KnowledgeGraphMemoryAdapter is Read-Only**
The `add()` and `delete()` operations silently no-op on the KnowledgeGraph adapter. Callers expecting confirmation that memories were stored will get incorrect results.

**Recommendation:** Raise `NotImplementedError` or return a documented sentinel to signal that writes are not supported.

**6. Ticket Store Uses Process Memory**
`ws_tickets.py` stores WebSocket tickets in a process-level dict. In a multi-process deployment, a ticket issued by process A cannot be validated by process B.

**Recommendation:** Move ticket storage to a fast shared store (e.g., Redis with 30s TTL) for multi-process deployments.

### 19.3 Best Practices Observed

- **UTC everywhere:** The `utcnow()` helper and `ensure_utc()` normalizer enforce timezone-aware datetimes throughout, preventing subtle duration calculation bugs.
- **Explicit scope isolation:** `scoped_query()` and `get_scoped()` make tenant filtering visible and auditable at call sites rather than hidden in query builders.
- **Lazy imports for cross-domain dependencies:** Memory adapters, config validators, and portfolio deps are imported inside methods to avoid circular imports and reduce module fan-out.
- **Constants over magic numbers:** Status values, role names, and size limits are all named constants (`ROLE_OWNER`, `BYTES_PER_MB`, `STATUS_ACTIVE`, etc.), centralizing configuration.
- **Idempotent seeding:** `ConfigSyncService.import_config()` uses upsert logic — safe to call repeatedly without creating duplicates.
- **Error isolation in autonomy:** Each post-execution subsystem is wrapped in `try/except`, ensuring one failing subsystem never cascades to others.

---

## Appendix A: Complete File Index

| File | Description |
|------|-------------|
| `temper_ai/storage/database/engine.py` | Engine factory (PostgreSQL/SQLite) |
| `temper_ai/storage/database/manager.py` | Global session manager, init/get/reset |
| `temper_ai/storage/database/models.py` | 13 observability models + indexes |
| `temper_ai/storage/database/models_registry.py` | `AgentRegistryDB` table |
| `temper_ai/storage/database/models_tenancy.py` | 7 multi-tenancy models |
| `temper_ai/storage/database/models_evaluation.py` | `AgentEvaluationResult` table |
| `temper_ai/storage/database/validators.py` | JSON size validation |
| `temper_ai/storage/database/datetime_utils.py` | UTC datetime helpers |
| `temper_ai/auth/api_key_auth.py` | API key generation, HMAC hash, require_auth, require_role |
| `temper_ai/auth/tenant_scope.py` | scoped_query, get_scoped, count_scoped |
| `temper_ai/auth/config_sync.py` | ConfigSyncService (import/export/list) |
| `temper_ai/auth/config_seed.py` | seed_configs (bulk YAML → DB) |
| `temper_ai/auth/ws_tickets.py` | WebSocket ticket store |
| `temper_ai/auth/session.py` | InMemorySessionStore with LRU |
| `temper_ai/auth/models.py` | User and Session dataclasses |
| `temper_ai/auth/constants.py` | Auth constants (TTLs, rate limits, field names) |
| `temper_ai/memory/service.py` | MemoryService high-level API |
| `temper_ai/memory/registry.py` | MemoryProviderRegistry singleton |
| `temper_ai/memory/protocols.py` | MemoryStoreProtocol interface |
| `temper_ai/memory/_schemas.py` | MemoryScope, MemoryEntry, MemorySearchResult |
| `temper_ai/memory/adapters/in_memory.py` | Dict-based, thread-safe, substring search |
| `temper_ai/memory/adapters/pg_adapter.py` | PostgreSQL with ILIKE/FTS |
| `temper_ai/memory/adapters/mem0_adapter.py` | Mem0 vector store |
| `temper_ai/memory/adapters/knowledge_graph_adapter.py` | Read-only KG bridge |
| `temper_ai/memory/cross_pollination.py` | Cross-agent knowledge sharing |
| `temper_ai/memory/agent_performance.py` | AgentPerformanceTracker |
| `temper_ai/memory/extractors.py` | LLM-based procedural pattern extraction |
| `temper_ai/memory/formatter.py` | Markdown context formatting |
| `temper_ai/registry/service.py` | AgentRegistryService |
| `temper_ai/registry/store.py` | AgentRegistryStore (CRUD) |
| `temper_ai/registry/_schemas.py` | AgentRegistryEntry, MessageRequest, MessageResponse |
| `temper_ai/lifecycle/store.py` | LifecycleStore |
| `temper_ai/lifecycle/models.py` | LifecycleAdaptation, LifecycleProfileRecord |
| `temper_ai/goals/store.py` | GoalStore |
| `temper_ai/goals/models.py` | GoalProposalRecord, AnalysisRun |
| `temper_ai/portfolio/store.py` | PortfolioStore (7 table types) |
| `temper_ai/portfolio/models.py` | 7 portfolio SQLModel tables |
| `temper_ai/learning/store.py` | LearningStore |
| `temper_ai/learning/models.py` | LearnedPattern, MiningRun, TuneRecommendation |
| `alembic/versions/abd552d7a52e_initial_schema.py` | Initial observability schema |
| `alembic/versions/m9_001_add_agent_registry_and_events.py` | Agent registry + event tables |
| `alembic/versions/mt_001_add_multi_tenancy.py` | Multi-tenancy tables + tenant_id FK |
| `alembic/versions/p1_001_tenant_scope_observability.py` | tenant_id for llm_calls, tool_executions |
| `alembic/versions/p1_002_tenant_scope_secondary.py` | tenant_id for all remaining tables |

---

## Appendix B: Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPER_DATABASE_URL` | `postgresql://temper:temper@localhost:5432/temper` | Primary database connection URL |
| `TEMPER_API_KEY_PEPPER` | `""` | Server-side pepper for HMAC-SHA256 API key hashing. Must be set in production. |
| `ALEMBIC_MANAGED` | `""` | If set to any non-empty value, skips `create_all_tables()` on startup. Use with `alembic upgrade head`. |

---

## Appendix C: Quick Reference — Adding Tenant Filtering to a New Table

```python
# Step 1: Add tenant_id to model
class MyNewModel(SQLModel, table=True):
    __tablename__ = "my_table"
    id: str = Field(primary_key=True)
    tenant_id: str | None = Field(default=None, index=True)
    # ... other fields

# Step 2: Use scoped_query in route handlers
from temper_ai.auth.tenant_scope import scoped_query, get_scoped, count_scoped
from temper_ai.auth.api_key_auth import require_auth, AuthContext

@router.get("/my-resources")
async def list_resources(ctx: AuthContext = Depends(require_auth)):
    with get_session() as session:
        stmt = scoped_query(session, MyNewModel, ctx.tenant_id)
        results = session.exec(stmt).all()
    return results

@router.get("/my-resources/{id}")
async def get_resource(id: str, ctx: AuthContext = Depends(require_auth)):
    with get_session() as session:
        item = get_scoped(session, MyNewModel, ctx.tenant_id, id)
    if item is None:
        raise HTTPException(404)
    return item

# Step 3: Create Alembic migration
# alembic revision --autogenerate -m "add_my_table"
# alembic upgrade head
```
