# Architecture Audit Report

**Date:** 2026-02-06
**Scope:** Full codebase — post-refactor (commit 5d42893)
**Team:** 7 specialist agents (structural-architect, security-auditor, reliability-reviewer, api-reviewer, data-analyst, test-analyst, performance-reviewer)
**Process:** Phase 1 (solo exploration) → Phase 2 (cross-review discussion) → Phase 3 (consensus report)
**Codebase:** 201 source files (~50K lines), 285 test files (~2,121 test functions), 17 modules

---

## Executive Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 4 |
| HIGH | 19 |
| MEDIUM | 30 |
| LOW | 16 |
| INFO | 10 |
| **Total** | **79** |

**Raw findings:** 128 across 7 agents. After deduplication (merging overlapping findings) and cross-review severity adjustments: **79 unique findings**.

**Overall Assessment:** The codebase has a **solid foundation** with mature patterns (circuit breakers, atomic checkpoints, prompt injection prevention, buffer swap-and-release). The previous 42-finding audit fix (commit 5d42893) resolved the most critical issues (SQL injection, Redis credential logging, system prompt displacement, circular dependencies). Remaining issues are primarily: (1) untested safety-critical code, (2) async/sync impedance mismatches, (3) data layer gaps (missing migrations, missing cascades), and (4) naming/organizational debt.

**Top 5 Risks:**
1. **3 safety-critical modules with zero test coverage** (1,157 lines) — config_change_policy, alerting, error_handling
2. **time.sleep() blocks event loop** in agent retry loop — stalls all parallel agents
3. **Buffer lock held during DB I/O** — can stall all observability recording
4. **7 tables missing from Alembic migrations** — production deployments via Alembic are broken
5. **SecurityError bypasses FrameworkException** — security violations silently swallowed

---

## Findings

### CRITICAL (4)

| # | ID | Category | File:Line | Finding | Agents | Recommendation |
|---|-----|----------|-----------|---------|--------|----------------|
| 1 | C-01 | coverage-gap | `src/safety/config_change_policy.py` (435 lines) | **Safety-critical config validation module with zero test coverage.** Validates config changes before M5 deployment — model changes, temperature ranges, safety mode downgrades. A regression allows unsafe deployments. | test-analyst | Add unit tests for all validation paths. |
| 2 | C-02 | coverage-gap | `src/observability/alerting.py` (407 lines) | **Alert system completely untested.** Cost overruns, error rates, latency breaches — alerting failures are silent by nature. | test-analyst | Add tests for alert rule evaluation, thresholds, cooldowns. |
| 3 | C-03 | coverage-gap | `src/utils/error_handling.py` (315 lines) | **Retry strategy framework with zero tests.** Exponential/linear/fixed backoff used across the codebase. Bugs silently degrade reliability. | test-analyst | Add tests for each RetryStrategy variant, delay calculation. |
| 4 | C-04 | blocking-io | `src/agents/standard_agent.py:362` | **time.sleep() in agent retry loop blocks event loop.** When called from parallel executor via LangGraph's ainvoke, blocks entire event loop for up to 14s. At 10 agents: 140s of event loop starvation. | performance, reliability | Provide `async def aexecute()` with `await asyncio.sleep()`. |

### HIGH (19)

| # | ID | Category | File:Line | Finding | Agents | Recommendation |
|---|-----|----------|-----------|---------|--------|----------------|
| 1 | H-01 | resource-leak | `src/observability/buffer.py:338-351` | **Buffer `_flush_unsafe()` holds lock during DB I/O.** All threads buffering observability items block during slow DB writes. Public `flush()` correctly swaps-and-releases but inline path does not. *Cross-review: reliability rated CRITICAL, performance rated MEDIUM → consensus HIGH (fix is straightforward, correct pattern exists).* | reliability, performance | Swap buffers under lock, flush outside lock (match `flush()` pattern). |
| 2 | H-02 | race-condition | `src/agents/llm_failover.py:166-170` | **Async lock created lazily without synchronization.** Two concurrent coroutines can create separate `asyncio.Lock` instances, defeating mutual exclusion on failover state. | reliability | Initialize `asyncio.Lock` eagerly in `__init__`. |
| 3 | H-03 | error-handling | `src/compiler/checkpoint_backends.py:544` | **Redis checkpoint crashes on save with default config.** `ttl=None` → `None * 2` raises TypeError on every save. Redis backend is non-functional with defaults. | reliability | Guard with `if self.ttl is not None:`. |
| 4 | H-04 | graceful-degradation | `src/agents/llm/base.py:99` | **Circuit breaker dict grows unboundedly.** Every unique (provider, model, base_url) adds a permanent entry. In long-running multi-tenant services, leaks memory. | reliability | Add LRU eviction or periodic cleanup. |
| 5 | H-05 | injection | `src/tools/bash.py:216-343` | **Shell mode regex-before-lexer parsing is fragile.** Shell operators in quoted strings could bypass per-command allowlist. Multiple defense layers mitigate but fundamental approach is fragile. | security | Replace regex splitting with `shlex.split` first, then validate. |
| 6 | H-06 | auth | `src/auth/routes.py:310-314` | **OAuth token confusion via shared "anonymous" key.** Concurrent unauthenticated OAuth flows share one token storage key. Race condition during code exchange. | security | Use per-flow identifier (state token or UUID) as storage key. |
| 7 | H-07 | error-contract | `src/safety/exceptions.py:28` + `src/utils/exceptions.py:563` | **SecurityError bypasses FrameworkException.** `except FrameworkException` misses security violations. Two parallel safety exception hierarchies coexist. *Cross-review: api-reviewer HIGH, structural MEDIUM → consensus HIGH (correctness bug).* | api-reviewer, structural | Make SecurityError inherit from FrameworkException. Unify hierarchies. |
| 8 | H-08 | coupling | `src/agents/llm_providers.py`, `src/safety/circuit_breaker.py` | **Triple shim chain for circuit breaker.** Three modules re-export from `src/core/circuit_breaker.py`. Confuses import resolution, adds indirection. | structural | Delete `src/llm/` package; update imports to canonical paths. |
| 9 | H-09 | boundaries | `src/safety/` vs `src/security/llm_security.py` | **Overlapping safety/security domain boundary.** `security/` has 1 file (905 lines) implementing classes that should implement protocols from `safety/interfaces.py` but don't reference them. 3 separate rate limiting implementations. | structural | Define clear boundary. Consolidate rate limiting. |
| 10 | H-10 | dependency-direction | `src/compiler/executors/sequential.py:18`, `parallel.py:10` | **Executors depend on concrete AgentFactory.** Infrastructure layer imports from application layer — dependency direction violation. | structural | Inject agent creation via callable. |
| 11 | H-11 | consistency | `src/agents/llm/factory.py:14,70` | **Two competing LLM factory functions.** `create_llm_provider(Any)` vs `create_llm_client(str, str, str)` with different signatures, provider maps, and export paths. | api-reviewer | Unify or deprecate one. Add VllmLLM to both if retained. |
| 12 | H-12 | migration | `alembic/versions/abd552d7a52e_initial_schema.py` | **Alembic migration missing 7 tables.** Experimentation and M5 tables not in any migration. `alembic upgrade head` misses them. | data-analyst | Generate new Alembic revision for missing tables. |
| 13 | H-13 | data-integrity | `src/experimentation/models.py:189,251,315` | **Missing ON DELETE CASCADE on experimentation FKs.** DB-level cascades missing; Python-side ORM cascades don't protect direct SQL operations. | data-analyst | Add `ondelete="CASCADE"` to FK columns. |
| 14 | H-14 | data-integrity | `src/self_improvement/storage/experiment_models.py:90,49` | **Missing ON DELETE CASCADE on M5 FKs + no cascade on Relationship.** Orphaned results after experiment deletion. | data-analyst | Add CASCADE to FK and cascade_delete to Relationship. |
| 15 | H-15 | migration | `src/observability/database.py:140-143` | **Dual schema management: create_all vs Alembic.** `init_database()` always calls `create_all()`, making Alembic decorative. Schema evolution via `create_all` can't ALTER existing tables. | data-analyst | Choose one strategy. Remove `create_all` from production startup. |
| 16 | H-16 | coverage-gap | `src/observability/aggregation.py` (536 lines) | **Metric aggregation pipeline untested.** Success rates, P50/P95/P99 latencies, cost rollups — incorrect aggregations lead to wrong operational decisions. | test-analyst | Add tests for each aggregation type and edge cases. |
| 17 | H-17 | coverage-gap | `src/cli/rollback.py` (232 lines) | **CLI rollback commands untested.** Operator-facing recovery path — if it silently fails, incident recovery is impossible. | test-analyst | Add Click CliRunner tests. |
| 18 | H-18 | mock-quality | Multiple test files | **87% of mocks (434/498) lack `spec=`.** Interface changes to LLM providers, safety policies, executors not caught by tests. False sense of security. | test-analyst | Adopt spec= policy. Prioritize: LLM providers, httpx, AgentFactory, StateManager. |
| 19 | H-19 | coverage-gap | `src/agents/standard_agent.py` | **StandardAgent (most critical class) has only 12 test functions.** Error paths, native tool calling, concurrent execution not covered. *Cross-review: elevated from MEDIUM due to P-01 CRITICAL — most performance-critical path is also most under-tested.* | test-analyst, performance | Add tests for tool failures, native tool defs, prompt rendering failures. |

### MEDIUM (30)

| # | ID | Category | File:Line | Finding | Agents |
|---|-----|----------|-----------|---------|--------|
| 1 | M-01 | naming | `src/compiler/domain_state.py:442` + `src/core/context.py:19` | **"ExecutionContext" names two different types.** *Cross-review: api-reviewer HIGH, structural LOW → consensus MEDIUM.* | api, structural |
| 2 | M-02 | god-module | `src/observability/tracker.py` (1,075 lines, 20 methods) | **ExecutionTracker remains a god class.** Handles 10+ entity types. | structural |
| 3 | M-03 | coupling | `src/utils/exceptions.py` (699 lines, 18 classes) | **Exception god module serves as coupling hub.** 15+ modules import from it. | structural |
| 4 | M-04 | organization | `src/compiler/` (16 modules, ~8,400 lines) | **Compiler mixes 4+ responsibilities.** Config, compilation, execution, checkpointing, state. | structural |
| 5 | M-05 | naming | `src/safety/rate_limiter.py:23` vs `policies/rate_limit_policy.py:25` | **Two rate-limit policies with confusing names.** `RateLimiterPolicy` vs `RateLimitPolicy`. | api-reviewer |
| 6 | M-06 | type-safety | `src/agents/llm/factory.py:14` | **Factory parameter typed as `Any`.** Loses type checking on LLM creation. | api-reviewer |
| 7 | M-07 | schema-validation | `src/observability/backend.py:73,135,205` | **Status parameters are untyped strings.** Typos pass silently. | api-reviewer |
| 8 | M-08 | contract-clarity | `src/observability/tracker.py:65-66` | **metric_registry/alert_manager typed as `Optional[Any]`.** No interface constraint. | api-reviewer |
| 9 | M-09 | backward-compat | `src/agents/llm_providers.py` + `src/agents/__init__.py:15` | **Shim imports without removal timeline.** Chains through dead-code shim. | api-reviewer |
| 10 | M-10 | contract-clarity | `src/safety/interfaces.py:288-315` | **Validator ABC exported but zero implementations.** Public API with no concrete classes. | api-reviewer |
| 11 | M-11 | consistency | `src/safety/interfaces.py:221-251` | **SafetyPolicy.validate() uses untyped Dict for action/context.** Different action types have different keys with no TypedDict. | api-reviewer |
| 12 | M-12 | backward-compat | `src/safety/__init__.py:108-111` | **Backward-compat aliases without deprecation warnings.** 3 aliases exported alongside canonical names. | api-reviewer |
| 13 | M-13 | state-management | `src/self_improvement/experiment_orchestrator.py:197-218` | **Long-lived session anti-pattern.** Accumulates stale identity-map state. | data-analyst |
| 14 | M-14 | consistency | `src/observability/models.py:37,86,135` | **Status fields use raw `str` without CHECK constraints.** Invalid values stored silently. | data-analyst |
| 15 | M-15 | data-integrity | `src/self_improvement/storage/models.py:51-54` | **CustomMetric.execution_id has no FK constraint.** Polymorphic FK without referential integrity. | data-analyst |
| 16 | M-16 | data-safety | `src/observability/models.py:204-205` | **LLM prompts/responses stored as plain text.** Can contain PII, API keys. Direct DB writes bypass sanitizer. | data-analyst |
| 17 | M-17 | schema-design | `src/observability/models.py:309-339` | **AgentMeritScore lacks unique constraint on (agent_name, domain).** Duplicate merit records possible. | data-analyst |
| 18 | M-18 | state-management | `src/observability/aggregation.py:41-47` | **MetricAggregator holds long-lived session.** Same anti-pattern as M-13. | data-analyst |
| 19 | M-19 | flaky-test | 30 test files | **139 time.sleep/asyncio.sleep calls in tests.** Timing-dependent, flaky under CI load. | test-analyst |
| 20 | M-20 | test-architecture | `tests/tools/` vs `tests/test_tools/`, etc. | **5 pairs of duplicate test directories.** Inconsistent naming, hard to find all tests. | test-analyst |
| 21 | M-21 | assertion-quality | Multiple files | **`assert False, "Should have raised..."` pattern** instead of `pytest.raises()`. Fragile. | test-analyst |
| 22 | M-22 | test-architecture | `tests/test_safety/test_distributed_rate_limiting.py` | **8 xfail tests for distributed rate limiting.** Document desired behavior that never runs. | test-analyst |
| 23 | M-23 | test-architecture | Test pyramid imbalance | **Only 184 integration tests for 201 source files.** Cross-module interaction coverage thin. | test-analyst |
| 24 | M-24 | over-mocking | `tests/test_observability/test_rollback_logging.py` | **Tests verify mock chains, not DB interactions.** Wrong column names would pass all tests. | test-analyst |
| 25 | M-25 | scalability | `src/observability/buffer.py:171` | **Dead letter queue grows without bound.** During extended DB outage: ~500MB+ overnight. | performance |
| 26 | M-26 | n-plus-one | `src/observability/backends/sql_backend.py:938-949` | **N+1 query in agent metrics batch update.** 20 queries per flush with 10 agents instead of 2. | performance |
| 27 | M-27 | blocking-io | `src/experimentation/service.py:224` | **Deliberate time.sleep(10-50ms) on every experiment creation.** Unnecessary "timing attack mitigation". | performance |
| 28 | M-28 | connection-pooling | `src/agents/llm/base.py:210-227` | **Each BaseLLM instance creates own httpx.Client (max_connections=100).** 10 agents = 1000 potential FDs. | performance |
| 29 | M-29 | missing-cache | `src/compiler/executors/sequential.py:616-619` | **Agent config loaded from YAML on every execution.** Same YAML parsed 15 times in 3-round dialogue. | performance |
| 30 | M-30 | scalability | `src/observability/tracker.py:632-654` | **Per-LLM-call sanitization runs 13+ regex patterns twice.** 2600 regex operations per workflow. | performance |

### LOW (16)

| # | ID | Category | Finding | Agents |
|---|-----|----------|---------|--------|
| 1 | L-01 | organization | Missing `__init__.py` in `src/safety/policies/` and `src/utils/` | structural |
| 2 | L-02 | coupling | ExecutionContext re-exported from 3 locations (stale re-exports) | structural |
| 3 | L-03 | boundaries | self_improvement module is semi-autonomous subsystem (12K lines) — needs boundary documentation | structural |
| 4 | L-04 | organization | Dialogue strategy imports observability models inline (hidden upward dependency) | structural |
| 5 | L-05 | naming | `SIExperimentStatus` / `SIVariantAssignment` inconsistent prefixing | api-reviewer |
| 6 | L-06 | backward-compat | `LangGraphCompiler` excluded from `__init__.py` by comment only | api-reviewer |
| 7 | L-07 | consistency | `AgentFactory` uses mutable class state with classmethods (inconsistent with instance-based registries) | api-reviewer |
| 8 | L-08 | schema-validation | Strategy/module references are bare `str` with no validation | api-reviewer |
| 9 | L-09 | contract-clarity | `ExecutionEngine.execute()` returns `Dict[str, Any]` for all modes; no streaming API | api-reviewer |
| 10 | L-10 | consistency | WorkflowStateDict defined in two places with different fields | data-analyst |
| 11 | L-11 | data-flow | `initialize_state` uses `**input_data` spread which can overwrite core keys | data-analyst |
| 12 | L-12 | consistency | Double commit pattern in session context manager | data-analyst |
| 13 | L-13 | migration | Dual schema creation paths create Alembic confusion | data-analyst |
| 14 | L-14 | input-validation | Shell mode flag arguments skip path validation (`--output=/etc/shadow`) | security |
| 15 | L-15 | input-validation | Workspace path passed to subprocess without boundary validation (erc721_quality.py) | security |
| 16 | L-16 | redos | Medium-confidence secret patterns lack word boundaries (false positives) | security |

### INFO (10)

| # | ID | Category | Finding | Agents |
|---|-----|----------|---------|--------|
| 1 | I-01 | extensibility | Six registries with no shared base (ToolRegistry, StrategyRegistry, PolicyRegistry, etc.) | structural |
| 2 | I-02 | documentation | Safety lazy-import pattern well-implemented | api-reviewer |
| 3 | I-03 | documentation | Exception hierarchy well-designed (FrameworkException -> BaseError) | api-reviewer |
| 4 | I-04 | schema-design | Observability schema well-designed (16 tables, proper CASCADE, composite indexes) | data-analyst |
| 5 | I-05 | state-management | Domain/Infrastructure state separation is clean | data-analyst |
| 6 | I-06 | persistence | Checkpoint writes are atomic (tempfile+fsync+replace, Redis pipeline) | data-analyst |
| 7 | I-07 | secrets | .gitignore secret exclusions well-configured | security |
| 8 | I-08 | injection | Jinja2 sandbox, YAML safe_load, SSRF protection all well-implemented | security |
| 9 | I-09 | auth | OAuth follows security best practices (PKCE, CSRF, encrypted tokens, secure cookies) | security |
| 10 | I-10 | scalability | Module-level shared ThreadPoolExecutor well-designed | performance |

---

## Cross-Cutting Themes

### 1. Async/Sync Impedance (C-04, H-01, H-02, M-28, M-30)
The codebase has robust sync patterns but async paths are second-class citizens. `time.sleep()` in retry loops (C-04), threading.Lock in async contexts (H-02), and per-instance httpx clients (M-28) all degrade performance under parallel execution. This is the **primary bottleneck for the parallel executor** — the core value proposition of the framework.

### 2. Untested Safety-Critical Code (C-01, C-02, C-03, H-16, H-17, H-19)
12 modules totaling ~3,143 lines have zero test coverage. The 3 most critical (config_change_policy, alerting, error_handling) directly affect deployment safety and operational reliability. Combined with 87% of mocks lacking `spec=` (H-18), the test suite provides a **false sense of security** — tests pass but interface drift goes undetected.

### 3. Data Layer Gaps (H-12, H-13, H-14, H-15, M-13, M-14, M-17, M-18)
The experimentation and M5 subsystems have systematic data integrity issues: missing Alembic migrations, missing DB-level cascades, long-lived sessions, and missing constraints. The observability subsystem (gold standard) shows the correct patterns exist — they were not applied to newer modules.

### 4. Naming Proliferation (M-01, M-05, M-12, L-05)
Multiple names for the same concept: ExecutionContext (2 types), RateLimitPolicy (3 names), safety aliases (6 doubled exports). Root cause: backward compatibility concerns leading to alias accumulation without deprecation timelines.

### 5. Security Posture: GOOD
No critical security vulnerabilities. Shell mode attack surface (H-05) and OAuth race condition (H-06) are the most notable risks, both mitigated by multiple defense layers. Previous audit's HIGH findings (SQL injection, credential logging, prompt displacement) all fixed.

---

## Positive Observations

1. **Circuit breaker** — Mature implementation with thundering-herd prevention, error classification, shared per-endpoint
2. **Prompt injection defense** — ReDoS-safe patterns, system prompt pinning, output sanitization, size limits
3. **OAuth implementation** — PKCE, CSRF, encrypted tokens, session fixation prevention, comprehensive security headers
4. **SSRF protection** — DNS rebinding prevention, redirect validation, private network blocking, IPv6 coverage
5. **Atomic checkpoints** — tempfile+fsync+os.replace on file, pipeline transactions on Redis
6. **Observability buffer** — Swap-and-release pattern, DLQ with bounded retries (public flush path)
7. **Error classification** — Transient vs permanent errors for retry decisions
8. **Path safety** — Symlink detection, Unicode normalization, null byte checks, secure temp dirs

---

## Recommended Remediation Priority

### Immediate (safety/correctness)
1. **C-01/C-02/C-03** — Add tests for untested safety-critical modules
2. **H-03** — Fix Redis checkpoint TypeError (1-line fix, currently non-functional)
3. **H-07** — Make SecurityError inherit from FrameworkException
4. **H-12** — Generate Alembic migration for 7 missing tables
5. **H-13/H-14** — Add ON DELETE CASCADE to experimentation/M5 FKs

### Short-term (reliability/performance)
6. **C-04** — Add async execution path to StandardAgent
7. **H-01** — Fix buffer inline flush to swap-and-release
8. **H-02** — Initialize async lock eagerly in FailoverProvider
9. **H-06** — Fix OAuth token confusion with per-flow keys
10. **M-25** — Add max_dlq_size to bound dead letter queue

### Medium-term (architecture/maintainability)
11. **H-08** — Clean up shim chain (delete `src/llm/`, update imports)
12. **H-09** — Define safety/security boundary
13. **H-10** — Inject AgentFactory into executors
14. **H-15** — Resolve dual schema management (create_all vs Alembic)
15. **H-18** — Adopt spec= policy for mocks (start with priority classes)

### Deferred (large scope)
- **M-02** — ExecutionTracker god class extraction (~1,075 lines)
- **Self-improvement monolith** — 12K lines, needs its own project
- **Experimentation unification** — Dual systems, ~4 weeks estimated

---

## Agent Reports

Individual findings files for deeper analysis:
- `.claude-coord/reports/audit-findings-structural-architect.md` (14 findings)
- `.claude-coord/reports/audit-findings-security-auditor.md` (17 findings)
- `.claude-coord/reports/audit-findings-reliability-reviewer.md` (17 findings)
- `.claude-coord/reports/audit-findings-api-reviewer.md` (21 findings)
- `.claude-coord/reports/audit-findings-data-analyst.md` (17 findings)
- `.claude-coord/reports/audit-findings-test-analyst.md` (28 findings)
- `.claude-coord/reports/audit-findings-performance-reviewer.md` (14 findings)

---

## Severity Resolution Log (Phase 2 Discussion)

| Finding | Agent A | Agent B | Resolution | Rationale |
|---------|---------|---------|------------|-----------|
| Buffer inline flush lock | reliability CRITICAL (R-01) | performance MEDIUM (P-09) | **HIGH** | Correct pattern exists in same file; fix is straightforward; but reliability impact under DB slowness is real |
| time.sleep blocks event loop | performance CRITICAL (P-01) | reliability LOW (R-14) | **CRITICAL** | Performance framing is correct — event loop starvation at scale. Reliability reviewer's LOW was for interruptibility, not blocking impact |
| ExecutionContext naming | api-reviewer HIGH (#1) | structural LOW (#11) | **MEDIUM** | Theoretical confusion risk mitigated by deprecation warnings; most consumers already use canonical path |
| Exception hierarchy split | api-reviewer HIGH (#4) | structural MEDIUM (#5) | **HIGH** | SecurityError bypassing FrameworkException is a correctness bug, not just organizational debt |
| StandardAgent under-tested | test-analyst MEDIUM (#17) | cross-ref with P-01 CRITICAL | **HIGH** | Most performance-critical code path is also most under-tested |

---

*Generated by architecture-audit team (7 agents, 2 discussion rounds)*
*Report: `.claude-coord/reports/architecture-audit-20260206-013426.md`*
