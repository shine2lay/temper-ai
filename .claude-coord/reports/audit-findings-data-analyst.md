# Architecture Audit: Data & State Findings

**Auditor:** Data & State Analyst
**Date:** 2026-02-07 (Phase 1 deep exploration)
**Scope:** Data models, state management, data flow, persistence, migrations, data integrity

---

## Summary

Explored all SQLModel tables (20 total across 5 model files), Pydantic config schemas (~50+), dataclass models (~60+), TypedDicts (1 canonical definition in executors/base.py), state management layers (StateManager, LoopStateManager, LangGraphWorkflowState), persistence backends (File, Redis, SQL), migration system (Alembic + create_all), session/transaction patterns, buffering system, and data sanitization paths.

Previous audit findings from Phases 1-4 remediated many issues: WorkflowStateDict consolidated, CheckConstraints added to status fields, UniqueConstraint on AgentMeritScore, FK CASCADE on experimentation/M5 tables, session.merge() for LoopStateManager, end_time calculation fixed, reserved key validation in StateManager. Remaining concerns center on: non-atomic counter increments in experimentation, stale experiment cache, percentile_cont SQLite incompatibility, auth persistence gaps, and incomplete migration coverage.

| Severity | Count |
|----------|-------|
| CRITICAL | 2     |
| HIGH     | 3     |
| MEDIUM   | 5     |
| LOW      | 3     |
| INFO     | 5     |
| **Total** | **18** |

---

## Findings

| # | Severity | Category | File:Line | Finding | Recommendation |
|---|----------|----------|-----------|---------|----------------|
| D-01 | CRITICAL | data-integrity | `src/experimentation/service.py:533-539` | **Non-atomic counter increments in experimentation service.** `variant.total_executions += 1`, `variant.successful_executions += 1`, and `variant.failed_executions += 1` are read-modify-write operations. Under concurrent access (multiple workflow executions reporting results simultaneously), two sessions can read the same counter value and both write value+1, losing one increment. This silently corrupts experiment statistics, invalidating A/B test results. The code uses per-operation sessions via `get_session()` with default isolation level, which does not protect against this race. | Use SQL-level atomic increments: `session.execute(update(Variant).where(Variant.id == variant_id).values(total_executions=Variant.total_executions + 1))`. Alternatively, use SERIALIZABLE isolation for the transaction. |
| D-02 | HIGH | data-integrity | `src/experimentation/service.py:62-100` (cache) + `service.py:533-541` (track_execution_complete) | **Stale experiment cache after counter updates.** `ExperimentService` maintains an in-memory `OrderedDict` cache (max 100 entries) for experiments. Cache is invalidated on lifecycle methods (`create_experiment`, `complete_experiment`) but NOT on `track_execution_complete` or `assign_variant`. After counters are updated in the DB, stale cached experiments still show old counter values. Subsequent reads from cache return incorrect `total_executions` / `successful_executions` counts. | Invalidate cache entry in `track_execution_complete` and `assign_variant` after modifying variant data. Or use a write-through cache pattern. |
| D-03 | HIGH | persistence | `src/observability/aggregation.py:93,345-346` | **percentile_cont() is PostgreSQL-only, breaks on SQLite.** MetricAggregator uses `func.percentile_cont(0.95).within_group(...)` for P95/P99 latency calculations. This function does not exist in SQLite. Since the framework supports SQLite (used in dev/test), these aggregation queries will raise `OperationalError` at runtime on SQLite. No fallback is provided. | Add a SQLite fallback using Python-side percentile calculation (sort + index), or use a conditional path based on `engine.dialect.name`. |
| D-04 | CRITICAL | persistence | `src/auth/session.py` + `src/auth/models.py` + `src/auth/oauth/token_store.py` | **Complete auth state wipe on server restart (compound with S-03).** `UserStore` (session.py:223) stores user accounts in a Python dict. `SecureTokenStore` (token_store.py:62) stores encrypted OAuth tokens in-memory. `InMemorySessionStore` (session.py:59) stores sessions in-memory. A single server restart permanently destroys ALL user accounts, OAuth tokens (access + refresh), and active sessions. Users cannot recover without full re-authentication through external OAuth provider. Auth is the only subsystem with zero durability guarantee. Elevated from HIGH during cross-review discussion (compound effect with security-auditor finding S-03). | Create a database-backed `UserStore` using SQLModel infrastructure. The `User` dataclass should become a SQLModel table with indexes on email and oauth_subject. Add persistent token storage backend (SQL or Redis). |
| D-05 | HIGH | migration | `alembic/versions/` (2 migration files) | **Alembic migration coverage is incomplete for newer tables.** While the Phase 1 migration added experimentation and M5 tables, any schema changes after that commit (e.g., new CHECK constraints, UniqueConstraints from Phase 1-4 remediation) may not be captured in migrations. Production databases upgraded via `alembic upgrade head` may have schema drift from fresh installations using `create_all()`. The `ALEMBIC_MANAGED` env var pattern helps but requires discipline. | Run `alembic revision --autogenerate` to capture any schema drift since the last migration. Add a CI check that compares `alembic upgrade head` schema against `create_all()` schema. |
| D-06 | MEDIUM | data-integrity | `src/self_improvement/storage/models.py:51-54` | **CustomMetric.execution_id is not a foreign key.** Indexed string field with no FK constraint. Description says it "links to AgentExecution or WorkflowExecution" but there is no referential integrity. Orphaned metrics accumulate for deleted executions. This is a polymorphic FK pattern that requires application-level validation. | Document explicitly that this is an intentional polymorphic FK. Add application-level validation on write, or split into `agent_execution_id` and `workflow_execution_id` with proper FKs. |
| D-07 | MEDIUM | data-safety | `src/observability/backends/sql_backend.py:130-132` + models with JSON columns | **No data size validation before persisting JSON blobs and LLM prompts.** `workflow_config_snapshot`, `input_data`, `output_data`, `prompt`, `response`, etc. are stored as unbounded JSON/text. A large LLM response or deeply-nested config can create multi-MB rows. LLM prompts/responses stored as plain text may contain PII or API keys. While the tracker has `DataSanitizer`, direct DB writes bypass it. | Add size validation for large text/JSON fields before persistence. Log warnings for payloads > 1MB. For production, consider column-level encryption for sensitive prompt/response data. |
| D-08 | MEDIUM | state-management | `src/self_improvement/experiment_orchestrator.py` | **ExperimentOrchestrator holds a long-lived session.** Stores `self.session` from `__init__` and uses it across multiple operations. Long-lived sessions accumulate stale identity-map state, hold connections, and conflict with the per-operation session pattern used elsewhere (sql_backend.py, experimentation service). | Refactor to accept a session factory or use `get_session()` per operation, consistent with the rest of the codebase. |
| D-09 | MEDIUM | consistency | `src/observability/database.py:254-259` | **Dual DDL management persists for dev/test.** `init_database()` calls `create_all_tables()` when `ALEMBIC_MANAGED` is not set (the default). This means dev/test environments always use `create_all()` while production uses Alembic. Schema differences between the two paths can cause bugs that only appear in production (e.g., missing CHECK constraints that `create_all()` includes but older migrations don't). | Consider always running Alembic migrations even in dev/test (`alembic upgrade head`), or run both and validate they produce identical schemas in CI. |
| D-10 | MEDIUM | data-flow | `src/observability/buffer.py` | **Buffer flush failures can permanently lose observability data.** The `ObservabilityBuffer` has a retry queue and dead-letter queue, but agent metric counter updates (`total_tokens`, `total_cost_usd` on parent entities) are applied during flush. If a flush permanently fails after MAX_RETRY_ATTEMPTS, the buffered LLM/tool calls are dead-lettered but the parent entity counter updates are lost with no recovery path. | Add a dead-letter recovery mechanism that can replay failed flushes. Log sufficient detail in dead-letter entries to enable manual recovery. |
| D-11 | LOW | schema-design | `src/self_improvement/storage/experiment_models.py:49` | **M5Experiment status field lacks CHECK constraint.** Unlike observability models which now have `CheckConstraint` on status fields, `M5Experiment.status` is an unconstrained string. Invalid status values can be stored. | Add `CheckConstraint("status IN ('draft','running','completed','failed','cancelled')")` to `M5Experiment.__table_args__`. |
| D-12 | LOW | consistency | `src/observability/database.py:199-201` + `src/observability/rollback_logger.py` | **Inconsistent commit conventions across session usage.** The `session()` context manager auto-commits on successful exit. Some callers also commit explicitly inside the `with` block (double commit). Others rely on implicit commit only. This asymmetry is a maintenance hazard -- new code may incorrectly assume one convention or the other. | Document the chosen commit convention. Standardize on either auto-commit in context manager (remove caller commits) or explicit commits only (remove auto-commit from CM). |
| D-13 | LOW | schema-design | `src/auth/models.py:19-20` | **Auth User model has no field-level validation.** `email` and `user_id` are plain strings with no format validation. Invalid email formats or empty strings can be stored. The `User` dataclass lacks the validation that Pydantic/SQLModel models get automatically. | Add `__post_init__` validation for email format and non-empty user_id, or migrate to Pydantic BaseModel. |
| D-14 | INFO | schema-design | `src/observability/models.py:16-501` | **Observability schema is well-designed.** 16 tables with proper relationships, CASCADE deletes, composite indexes, FK constraints, CHECK constraints on status fields, and UniqueConstraint on AgentMeritScore. Good use of `utcnow()` defaults. This is the reference pattern for the codebase. | No action needed. |
| D-15 | INFO | state-management | `src/compiler/domain_state.py:106-384` | **Domain/Infrastructure state separation is clean.** `WorkflowDomainState` (serializable, checkpointable) cleanly separated from `InfrastructureContext` (non-serializable, recreated on resume). Robust `to_dict()`/`from_dict()` with datetime handling, unknown-field preservation, and validation. | No action needed. Good architecture. |
| D-16 | INFO | state-management | `src/compiler/executors/base.py:24-70` + `src/compiler/state_manager.py:15` | **WorkflowStateDict is now properly consolidated.** Single canonical definition in `executors/base.py` with all fields, imported by `state_manager.py`. Previous duplicate definitions have been eliminated. | No action needed. Good consolidation from prior audit. |
| D-17 | INFO | migration | `alembic/versions/9bba5a67eb64_phase_1_model_changes_constraints_.py` | **Phase 1 migration adds CHECK constraints and new tables.** The second migration properly adds experimentation tables, M5 tables, CHECK constraints on status fields, and UniqueConstraint on AgentMeritScore. Good incremental migration practice. | No action needed. |
| D-18 | INFO | schema-design | `src/experimentation/models.py:63-148` + `src/self_improvement/storage/experiment_models.py:17-75` | **Two parallel experiment systems with separate schemas.** The `experimentation` package has 4 well-normalized tables. The `self_improvement` package has 2 simpler M5 tables. Both serve A/B testing for different contexts. Known issue (ISSUE-14). | Long-term unification opportunity but not blocking. |

---

## Cross-Cutting Themes

### 1. Non-Atomic Counter Updates (D-01, D-02)
The experimentation service's read-modify-write counter pattern is the most impactful finding. Under concurrent access, experiment statistics can be silently corrupted. The stale cache compounds this by serving outdated counter values to readers even after DB updates. Together, these undermine the reliability of A/B test results.

### 2. SQLite vs PostgreSQL Compatibility (D-03, D-09)
The framework supports both SQLite (dev/test) and PostgreSQL (production), but `percentile_cont()` is PostgreSQL-only. Combined with the dual DDL management (create_all vs Alembic), bugs can appear only in production. The `ALEMBIC_MANAGED` env var helps but doesn't fully close the gap.

### 3. Auth Persistence Gap (D-04 CRITICAL, D-13)
Auth models (User, Session) are plain dataclasses stored in-memory. Unlike the observability layer (SQLModel + Alembic + SQL backend), auth has no persistent storage for user accounts, OAuth tokens, or sessions. A server restart silently destroys the entire authentication layer -- user identities, OAuth grants, and active sessions -- with no recovery path. Compounds with security-auditor finding S-03.

### 4. Data Size and Safety (D-07, D-10)
Unbounded JSON/text storage in observability tables combined with buffer flush failure modes can lead to both data bloat and data loss. Large LLM responses are stored without size validation, and permanent flush failures lose counter updates with no recovery path.

---

## Remediation Status from Prior Audit

The following issues from the previous audit have been successfully remediated:

| Prior Finding | Status | How Fixed |
|--------------|--------|-----------|
| Float-on-int merit score corruption | FIXED | `mixed_decisions` is now a separate int field (models.py:355) |
| Duplicate WorkflowStateDict definitions | FIXED | Single canonical definition in executors/base.py, imported elsewhere |
| Missing ON DELETE CASCADE on experimentation FKs | FIXED | All FKs now have `ondelete="CASCADE"` |
| Missing ON DELETE CASCADE on M5 FKs | FIXED | `ondelete="CASCADE"` added (experiment_models.py:94) |
| Status fields without DB constraints | FIXED | CHECK constraints added to all observability status fields |
| AgentMeritScore missing unique constraint | FIXED | UniqueConstraint("agent_name", "domain") added |
| LoopStateManager read-then-write race | FIXED | Uses session.merge() upsert pattern |
| Tool execution end_time set to start_time | FIXED | Now calculated as start_time + duration |
| State manager missing reserved key validation | FIXED | RESERVED_STATE_KEYS validation added |

---

## Top 3 Issues by Data Integrity Impact

1. **D-01 (CRITICAL)**: Non-atomic counter increments in experimentation service. Concurrent workflow executions can silently lose counter updates. Blast radius: variant assignment is safe (uses traffic weights, not counters), statistical tests are safe (count assignments directly), but reporting dashboards and sample-size threshold checks are affected. Zero test coverage (confirmed by test-analyst).
2. **D-04 (CRITICAL, elevated from HIGH)**: Complete auth state wipe on server restart. Compounds with S-03 (security-auditor): UserStore + SecureTokenStore + InMemorySessionStore are all in-memory. A restart destroys user accounts, OAuth tokens, and sessions simultaneously with no recovery path. Auth is the only subsystem with zero durability.
3. **D-03 (HIGH)**: percentile_cont() PostgreSQL-only function used in MetricAggregator. Dev/test environments using SQLite will crash on aggregation queries. Bugs in aggregation logic will only be caught in production.
