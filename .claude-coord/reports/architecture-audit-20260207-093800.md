# Architecture Audit Report (Team Consensus)

**Generated:** 2026-02-07 09:38
**Method:** 7 specialist agents with cross-review discussion (2 rounds)
**Discussion Rounds:** 2
**Scope:** meta-autonomous-framework — 203 source files, 293 test files
**Previous Audit:** 2026-02-07 07:03 (136 findings)

---

## Executive Summary

**Total Findings: 144** (after discussion: 12 severity changes, 5 cross-cutting insights)

| Severity | Count | Changed |
|----------|-------|---------|
| CRITICAL | 6     | P-01 ↑HIGH, Struct-4/5 ↑HIGH, R-01 ↓CRITICAL, R-03 ↓CRITICAL, S-01 ↓CRITICAL, Test-3 ↓CRITICAL |
| HIGH     | 38    | +R-01→MEDIUM, +R-03→HIGH, +S-01→HIGH, +API-19↑LOW, +R-19↑MEDIUM, -P-01→CRITICAL, -Struct-4/5→CRITICAL |
| MEDIUM   | 52    | +R-01↓CRITICAL, +Test-3↓CRITICAL |
| LOW      | 24    | — |
| INFO     | 24    | — |

### Top Risks (team consensus)

1. **Async infrastructure is dead code — thread starvation unchanged** (P-01, CRITICAL) — `aexecute()`, `acomplete()`, `_get_async_client_safe()` are all implemented but no executor calls `aexecute()`. The sync path with `time.sleep()` blocking thread pools is the only production path. Agreed by: performance-reviewer, reliability-reviewer, structural-architect.

2. **ApprovalWorkflow dict race on safety-critical path** (R-02, CRITICAL) — `_requests` dict accessed from background polling threads without locking. Multi-step read-modify patterns are non-atomic even under GIL. Zero concurrent tests. PEP 703 free-threaded Python will make single operations racy too. Agreed by: reliability-reviewer, test-analyst.

3. **Observability as hidden DB infrastructure layer** (Struct-4/5, CRITICAL) — `src/observability/` doubles as shared database layer for self_improvement (12+ files), experimentation (3 files), and core/test_support. 5 agents independently found issues tracing to this root cause. Any DB fix risks breaking tracking, experimentation, and self_improvement simultaneously. Agreed by: structural-architect, performance-reviewer, data-analyst, security-auditor.

4. **ToolRegistryProtocol.get_tool() doesn't match ToolRegistry.get()** (API-1, CRITICAL) — Protocol defines `get_tool(name)` but implementation has `get(name, version)`. No class implements `get_tool()`. Any code calling `.get_tool()` via the Protocol gets `AttributeError` at runtime. Zero contract tests. Agreed by: api-reviewer, test-analyst.

5. **Non-atomic counter increments corrupt experiment statistics** (D-01, CRITICAL) — Read-modify-write race on variant counters. Concurrent workflow executions silently lose increments. Affects experiment lifecycle decisions (early stopping, sample size thresholds). Zero concurrent tests. Agreed by: data-analyst, test-analyst.

6. **15+ self_improvement source files completely untested** (Test-1, CRITICAL) — Including deployer.py, loop/orchestrator.py, error_recovery.py. Deployment and error recovery code with zero test coverage. Agreed by: test-analyst (unanimous).

### Key Strengths
1. **Mature security posture** — Jinja2 ImmutableSandboxedEnvironment, YAML safe_load everywhere, no eval/exec, OAuth with CSRF/PKCE, 8-layer log injection prevention, secret redaction, checkpoint HMAC integrity
2. **Strong resilience patterns** — Circuit breaker with thundering-herd prevention, swap-and-flush in observability buffer, LRU eviction bounds on all shared collections, token bucket NaN/Inf validation, atomic file writes
3. **Significant remediation since last audit** — 10+ prior findings confirmed fixed: WorkflowStateDict consolidated, CASCADE deletes added, merit score columns fixed, DLQ bounded, circuit breaker eviction added, buffer flush lock fixed, SentenceTransformer singleton, native tool def caching

---

## Consensus Findings by Severity

### CRITICAL (6)

| # | Finding | File:Line | Agent | Consensus | Recommendation |
|---|---------|-----------|-------|-----------|----------------|
| C-01 | Async path calls sync LLM; `aexecute()` is dead code | `standard_agent.py:486-487` | performance + reliability + structural | Consensus (↑HIGH) | Use `self.llm.acomplete()` directly in `aexecute_iteration`. Wire executors to call `aexecute()`. |
| C-02 | ApprovalWorkflow._requests dict race — safety-critical, no locks | `approval.py:185-238` | reliability + test | Consensus (maintained) | Add `threading.Lock` for all `_requests` mutations and reads. Add concurrent tests. |
| C-03 | Observability as hidden DB infrastructure — systemic coupling | `src/observability/` (30+ import sites) | structural + 4 other agents | Consensus (↑HIGH) | Extract `src/database/` package with `get_session`, `DatabaseManager`, `init_database`. Let observability and others depend on it. |
| C-04 | ToolRegistryProtocol.get_tool() mismatches ToolRegistry.get() | `domain_state.py:86` vs `registry.py:145` | api + test | Unanimous | Rename Protocol method to `get(name) -> Any` matching actual implementation. Add conformance test. |
| C-05 | Non-atomic counter increments in experimentation service | `experimentation/service.py:533-539` | data + test | Consensus | Use SQL-level atomic increments: `update(Variant).values(total_executions=Variant.total_executions + 1)` |
| C-06 | 15+ self_improvement files completely untested | `src/self_improvement/` | test | Unanimous | Priority: deployer.py, loop/orchestrator.py, error_recovery.py. Add tests before any changes to these modules. |

### HIGH (38)

| # | Finding | File:Line | Agent | Consensus | Recommendation |
|---|---------|-----------|-------|-----------|----------------|
| H-01 | Exception hierarchy fragmentation (~15 classes bypass FrameworkException) | Multiple modules | api (↓CRITICAL) | Consensus | Rebase orphan exceptions onto FrameworkException hierarchy |
| H-02 | ValidationError backward-compat alias is a function — breaks isinstance/except | `exceptions.py:641` | api (↑LOW) | Consensus | Make proper class: `class ValidationError(FrameworkValidationError)` |
| H-03 | Async client leaked when close() called without aclose() | `llm/base.py:334-392` | reliability (↓CRITICAL) | Consensus | Add async cleanup scheduling in close(); limited callers via FailoverProvider |
| H-04 | SQL injection pattern via f-string in text() call | `database.py:192` | security (↓CRITICAL) | Consensus | Use SQLAlchemy `execution_options(isolation_level=...)`. Enum-constrained, not exploitable. |
| H-05 | LLM factory reads deprecated api_key field, ignores api_key_ref | `llm/factory.py:122` | api | Unanimous | Read `api_key_ref`, resolve secret references |
| H-06 | No async agent execution contract in BaseAgent | `base_agent.py:132` | api | Consensus | Add `aexecute()` to BaseAgent ABC |
| H-07 | Confusing backward-compat aliases in safety module | `safety/__init__.py:56-97` | api | Consensus | Remove aliases from `__all__`, keep in `__getattr__` with deprecation warnings |
| H-08 | Three unrelated rate-limit exception types with different bases | Multiple | api | Unanimous | Create shared `RateLimitError(FrameworkException)` base |
| H-09 | Registry Protocol too minimal, misaligned with implementations | `core/protocols.py:13-61` | api | Consensus | Define per-domain Protocols matching actual implementations |
| H-10 | time.sleep() in sync retry blocks parallel agents | `standard_agent.py:689` | performance | Consensus | Use `threading.Event.wait(timeout=backoff_delay)` |
| H-11 | Tool executor pool defaults to 4 workers | `standard_agent.py:65-68` | performance | Unanimous | Increase default to `min(32, os.cpu_count() * 2 + 4)` |
| H-12 | Approval callbacks silently swallow all exceptions | `approval.py:546-562` | reliability | Unanimous | Log at WARNING level |
| H-13 | Retry backoff sleep not interruptible by shutdown | `sequential.py:448` | reliability | Unanimous | Pass shared shutdown event |
| H-14 | execute_batch() has no overall timeout | `executor.py:605-641` | reliability | Consensus | Add `overall_timeout` parameter |
| H-15 | Sync retry lacks jitter (thundering herd) | `standard_agent.py:684` | reliability | Consensus | Add jitter matching async path |
| H-16 | Module-level thread pool with imperfect shutdown | `standard_agent.py:66-78` | reliability | Consensus | Lazy init with explicit lifecycle |
| H-17 | SQLite StaticPool no retry for concurrent writes | `database.py:83-90` | reliability | Unanimous | Add retry-on-lock, warn if agent count > 1 |
| H-18 | OAuth HTTP client missing pool timeout | `oauth/service.py:122-128` | reliability | Unanimous | Add explicit pool timeout |
| H-19 | acomplete() uses threading.Lock (blocks event loop) | `llm/base.py:334,625` | reliability (↑MEDIUM) | Consensus | Have acomplete() use `_get_async_client_safe()` instead |
| H-20 | Shell mode large attack surface | `tools/bash.py:308-437` | security | Unanimous | Add glob blocking, parse flag values, add fuzzing tests |
| H-21 | In-memory-only OAuth token storage | `token_store.py:236-237` | security | Unanimous | Add persistent backend option |
| H-22 | Ephemeral HMAC key defeats checkpoint integrity | `checkpoint_backends.py:210-220` | security | Unanimous | Require CHECKPOINT_HMAC_KEY in production |
| H-23 | Dependencies unbounded (>= only) | `requirements.txt` | security | Unanimous | Pin versions with upper bounds, add pip-audit CI |
| H-24 | Deprecated TOCTOU-vulnerable rate limiter methods still callable | `llm_security.py:727-798` | security | Unanimous | Remove deprecated methods (zero callers) |
| H-25 | Stale experiment cache after counter updates | `experimentation/service.py:62-100` | data | Consensus | Invalidate cache in track_execution_complete |
| H-26 | percentile_cont() PostgreSQL-only, breaks SQLite | `aggregation.py:93,345-346` | data | Unanimous | Add SQLite fallback with Python-side percentile |
| H-27 | Auth UserStore ephemeral (compound with S-03) | `auth/session.py` | data + security | Team-lead: HIGH (compound, urgent) | Create database-backed UserStore; fix priority matches CRITICAL |
| H-28 | Alembic migration coverage incomplete | `alembic/versions/` | data | Consensus | Run autogenerate, add CI schema drift check |
| H-29 | StandardAgent god module (1222 LOC) | `standard_agent.py` | structural | Unanimous | Extract tool loop, native tool defs, safety checks |
| H-30 | exceptions.py god module (721 LOC) | `utils/exceptions.py` | structural | Unanimous | Split ErrorCode, error_sanitization into separate files |
| H-31 | Observability→safety bidirectional dependency | `rollback_logger.py:23-24` | structural | Consensus | Define rollback event types in observability or shared types |
| H-32 | Experimentation imports from observability internals | `experimentation/metrics_collector.py:21-22` | structural | Consensus | Part of C-03 — extract shared DB infrastructure |
| H-33 | 71.4% of mocks lack spec= (521/730) | tests-wide | test | Unanimous | Enforce spec= for new mocks, prioritize safety-critical interfaces |
| H-34 | 100+ time.sleep() calls across 30+ test files | tests-wide | test | Unanimous | Replace with deterministic approaches (mock time, freezegun) |
| H-35 | Duplicate test directories (self_improvement) | tests/ | test | Unanimous | Consolidate into tests/test_self_improvement/ |
| H-36 | security_limits.py has no dedicated tests | `compiler/security_limits.py` | test | Unanimous | Create test_security_limits.py |
| H-37 | Bare except:pass in CB persistence tests | `test_llm_providers.py:1732-2015` | test | Unanimous | Replace with specific exception types |
| H-38 | 8 permanent xfail in distributed rate limiting | `test_distributed_rate_limiting.py` | test | Unanimous | Implement backend or convert to skip with ticket ref |

### MEDIUM (52)

Key findings (abbreviated — see individual agent reports for full details):

| # | Finding | Agent |
|---|---------|-------|
| M-01 | R-01: async lock TOCTOU race (↓CRITICAL — dead code) | reliability |
| M-02 | security/ vs safety/ boundary confusion | structural |
| M-03 | src/llm/ orphaned shim package | structural |
| M-04 | Production code imports deprecated llm_providers shim | structural |
| M-05 | safety/__init__ re-exports 62+ symbols via lazy loading | structural |
| M-06 | safety/circuit_breaker split-personality (shim + domain code) | structural |
| M-07 | core/test_support imports from agents layer | structural |
| M-08 | ExecutionTracker god module (1075 LOC) | structural |
| M-09 | Compiler executors depend on concrete AgentFactory | structural |
| M-10 | Entropy check skipped for 10KB-100KB inputs | security |
| M-11 | HMAC key for observability pseudonymization ephemeral | security |
| M-12 | random.random() for retry jitter (non-security, confusing) | security |
| M-13 | IsolationLevel enum values interpolated into SQL text() | security |
| M-14 | Legacy checkpoints without HMAC accepted with warning | security |
| M-15 | JSON parsing no depth limit pre-parse | security |
| M-16 | OAuth client secrets from env vars without keyring | security |
| M-17 | RedisCheckpointBackend crashes when ttl=None | security |
| M-18 | Token signature validation returns False for all errors | reliability |
| M-19 | Rollback listener callbacks silently swallowed | reliability |
| M-20 | Half-open semaphore rejection skips rejected_calls metric | reliability |
| M-21 | WebScraper._client cleanup only in __del__ | reliability |
| M-22 | No idempotency check on checkpoint resume | reliability |
| M-23 | Daemon flush thread killed mid-flush on exit | reliability |
| M-24 | Outermost tool exception handler strips diagnostic context | reliability |
| M-25 | Observer tracking suppresses all exceptions (no backoff) | reliability |
| M-26 | Shared HTTP client eviction closes in-use client | reliability |
| M-27 | ToolCallRecord TypedDict total=False makes all fields optional | api |
| M-28 | ErrorHandlingConfig required fields without defaults | api |
| M-29 | execute()/async_execute() overlapping mode support | api |
| M-30 | ObservabilityBackend 16 abstract methods, wide interface | api |
| M-31 | DomainExecutionContext is function, not class | api |
| M-32 | Strategy name fields unvalidated strings | api |
| M-33 | SafetyPolicy.validate() parameters untyped dicts | api |
| M-34 | ToolRegistryProtocol.get_tool() returns Any | api |
| M-35 | CustomMetric.execution_id not a FK (polymorphic) | data |
| M-36 | No data size validation on JSON blobs/LLM prompts | data |
| M-37 | ExperimentOrchestrator long-lived session | data |
| M-38 | Dual DDL management (create_all vs Alembic) | data |
| M-39 | Buffer flush failures permanently lose counter updates | data |
| M-40 | Test-3: test_support.py untested (↓CRITICAL) | test |
| M-41 | 3 utility modules with zero coverage (secret_patterns, error_handling, config_migrations) | test |
| M-42 | Stale _OLD test file | test |
| M-43 | Mock without spec in conftest streaming fixture | test |
| M-44 | Timing-dependent console streaming tests | test |
| M-45 | Direct mutation of module-level globals in tests | test |
| M-46 | Over-mocking: hasattr checks instead of behavior tests | test |
| M-47 | Weak assertions without messages | test |
| M-48 | _conversation_turns list retains all historical turns | performance |
| M-49 | Per-instance httpx.Client despite shared pool | performance |
| M-50 | Agent metric N+1 queries in flush | performance |
| M-51 | Buffer lists no size limit (primary buffer unbounded) | performance |
| M-52 | Agent config re-loaded for cached agents | performance |

### LOW (24) and INFO (24)

See individual agent reports for full details.

---

## Discussion Log

### Severity Changes (12)

| # | Finding | Original | Final | Reason | Decided By |
|---|---------|----------|-------|--------|------------|
| 1 | P-01 (async calls sync LLM) | HIGH | CRITICAL | aexecute() dead code; no executor calls it; thread starvation unchanged | Performance self-revised |
| 2 | Struct-4/5 (observability as DB) | HIGH | CRITICAL | 5 agents found issues tracing to same root cause; systemic defect | Structural self-revised |
| 3 | R-01 (async lock TOCTOU) | CRITICAL | MEDIUM | `_get_async_client_safe()` has zero callers — dead code | Reliability self-revised |
| 4 | R-03 (async client leak) | CRITICAL | HIGH | Limited callers via FailoverProvider; not in production paths | Reliability self-revised |
| 5 | R-19 (sync lock in async) | MEDIUM | HIGH | Live path: `acomplete()` uses threading.Lock, can block event loop | Reliability self-revised |
| 6 | S-01 (SQL injection) | CRITICAL | HIGH | Enum-constrained, no runtime input path, requires source code access | Security self-revised |
| 7 | API-2 (exception hierarchy) | CRITICAL | HIGH | Same issue as prior audit H-10/H-11, better documented not worse | API self-revised |
| 8 | API-19 (ValidationError alias) | LOW | HIGH | Regression from prior fix — silently breaks isinstance/except | API self-revised |
| 9 | Test-3 (test_support untested) | CRITICAL | MEDIUM | Latent risk; 4 cross-agent CRITICALs have zero coverage and are higher priority | Test self-revised |
| 10 | D-04 (ephemeral UserStore) | HIGH | HIGH (compound, urgent) | Data-analyst argued CRITICAL; security-auditor argued HIGH (durability not exploitation); team-lead chose HIGH with elevated fix priority | Team-lead decision |
| 11 | D-04 fix priority | — | Matches CRITICAL | Compound effect: restart destroys user accounts + tokens + sessions | Team-lead annotation |
| 12 | Struct-1 (StandardAgent god module) | HIGH | HIGH | Confirmed as contributing factor to P-01 (dead async path) but not elevated | Consensus |

### Cross-Cutting Insights

1. **Entire async infrastructure is dead code.** `aexecute()`, `aexecute_iteration()`, `acomplete()`, `_get_async_client_safe()` are all implemented correctly but no executor calls `aexecute()`. The async path was added as a "fix" for the prior audit's CRITICAL (thread pool starvation) but is cosmetic — the production path is unchanged. Performance-reviewer, reliability-reviewer, and structural-architect all converged on this independently. (P-01, R-01, R-03, R-19)

2. **Database module is PostgreSQL-first, SQLite bolted on.** Security-auditor identified the systemic pattern: raw SQL for PostgreSQL features, no dialect abstraction, `if "sqlite"` guards sprinkled throughout. This root cause explains S-01 (raw SQL), D-03 (percentile_cont), and R-09 (no concurrent write retry). All three would be fixed by introducing a dialect-aware helper layer. (S-01, D-03, R-09)

3. **4 CRITICAL findings have zero test coverage.** Test-analyst confirmed that ToolRegistryProtocol mismatch, ApprovalWorkflow race, experimentation counter corruption, and SQL injection pattern all have no tests covering the vulnerable path. The test gaps and the bugs are mutually reinforcing: bugs persist because tests don't exist, and the untested code accumulates more bugs. (API-1, R-02, D-01, S-01)

4. **God module complexity enables dead code drift.** StandardAgent (1222 LOC) has copy-pasted sync and async paths that have diverged. The async path calls `run_in_executor(self.llm.complete(...))` instead of `self.llm.acomplete()`. In a smaller, focused module, the author would more likely have used the async counterpart because the concern would be isolated. Structural decomposition is a precondition for correctness, not just cleanliness. (P-01, Struct-1)

5. **Auth subsystem is the only one with zero persistence.** Observability, experimentation, safety, and self_improvement all have SQL persistence. Auth stands alone with 100% ephemeral state (UserStore, SecureTokenStore, InMemorySessionStore). A server restart destroys the entire authentication layer with no recovery. Security-auditor classified this as a durability concern (HIGH), not a security one. Data-analyst argued CRITICAL based on compound impact. Team-lead kept HIGH with CRITICAL fix priority. (D-04, S-03, S-16)

### Disagreements Resolved by Team Lead

**D-04 (ephemeral UserStore): Data-analyst → CRITICAL vs Security-auditor → HIGH.**
Data-analyst argued compound impact (UserStore + SecureTokenStore + InMemorySessionStore all ephemeral = complete auth state wipe). Security-auditor countered that ephemeral state is a durability problem, not a security exploitation vector: no confidentiality breach, no privilege escalation, no integrity violation — the "attack" is DoS requiring infrastructure access. Team-lead chose **HIGH (compound, urgent)** with fix priority matching CRITICAL. The security-auditor's argument is more technically precise: severity should reflect risk type, and data loss without exploitation is HIGH. But the urgency annotation ensures the fix isn't deprioritized.

---

## Hotspot Modules

### `src/agents/standard_agent.py` (1222 LOC)
| Agent | Finding | Severity |
|-------|---------|----------|
| performance | P-01: async path calls sync LLM | CRITICAL |
| performance | P-02: time.sleep blocks parallel agents | HIGH |
| performance | P-03: tool pool defaults to 4 | HIGH |
| performance | P-04: conversation_turns not pruned | MEDIUM |
| reliability | R-07: sync retry lacks jitter | HIGH |
| reliability | R-08: module-level pool imperfect shutdown | HIGH |
| structural | #1: god module, 7+ concerns | HIGH |

**Root cause (consensus):** God module with copy-pasted sync/async paths. No executor wires to the async path.
**Fix strategy (consensus):** Extract tool loop, safety checks, native tool defs into focused modules. Wire executors to call `aexecute()`. Use `acomplete()` in async path.

### `src/agents/llm/base.py`
| Agent | Finding | Severity |
|-------|---------|----------|
| reliability | R-01: async lock TOCTOU (dead code) | MEDIUM |
| reliability | R-03: async client leak in close() | HIGH |
| reliability | R-19: sync lock blocks event loop | HIGH |
| performance | P-05: per-instance httpx clients | MEDIUM |
| api | #17: dual async client accessors | LOW |

**Root cause (consensus):** Mixed sync/async design with parallel accessor paths. `_get_async_client_safe()` exists but is never called. `acomplete()` uses the sync accessor.
**Fix strategy (consensus):** Have `acomplete()` call `_get_async_client_safe()`. Deprecate sync accessor. Share httpx clients by default.

### `src/observability/` (4400+ LOC, 14 modules)
| Agent | Finding | Severity |
|-------|---------|----------|
| structural | #4/#5: hidden DB infrastructure layer | CRITICAL |
| security | S-01: SQL injection pattern | HIGH |
| reliability | R-09: SQLite no concurrent write retry | HIGH |
| data | D-03: percentile_cont PostgreSQL-only | HIGH |
| data | D-09: dual DDL management | MEDIUM |
| data | D-10: buffer flush data loss | MEDIUM |
| performance | P-06: N+1 agent metric queries | MEDIUM |
| performance | P-10: sanitization regex on every call | MEDIUM |

**Root cause (consensus):** Observability doubles as shared DB infrastructure. PostgreSQL-first design with SQLite bolted on. No dialect abstraction.
**Fix strategy (consensus):** Extract `src/database/` package. Add dialect-aware helpers. Use SQLAlchemy built-ins for isolation levels.

### `src/experimentation/service.py`
| Agent | Finding | Severity |
|-------|---------|----------|
| data | D-01: non-atomic counter increments | CRITICAL |
| data | D-02: stale experiment cache | HIGH |
| structural | #5: coupling to observability internals | HIGH |

**Root cause (consensus):** Read-modify-write pattern on counters + no cache invalidation on writes.
**Fix strategy (consensus):** Use SQL-level atomic increments. Invalidate cache on counter updates. Extract DB dependency to shared infrastructure.

---

## Individual Agent Reports

### Structural Architecture — 19 findings
0 critical, 5 high (→ 1 CRITICAL after discussion), 8 medium, 4 low, 2 info
Full report: `.claude-coord/reports/audit-findings-structural-architect.md`

### Security — 22 findings
1 critical (→ HIGH after discussion), 5 high, 8 medium, 4 low, 4 info
Full report: `.claude-coord/reports/audit-findings-security-auditor.md`

### Reliability — 21 findings
3 critical (→ 1 CRITICAL, 1 HIGH, 1 MEDIUM after discussion), 7 high (→ 8 high), 8 medium (→ 9), 2 low, 1 info
Full report: `.claude-coord/reports/audit-findings-reliability-reviewer.md`

### API Contracts — 22 findings
2 critical (→ 1 CRITICAL, 1 HIGH after discussion), 5 high (→ 6), 8 medium, 4 low (→ 3), 3 info
Full report: `.claude-coord/reports/audit-findings-api-reviewer.md`

### Data & State — 18 findings
1 critical, 4 high, 5 medium, 3 low, 5 info
Full report: `.claude-coord/reports/audit-findings-data-analyst.md`

### Test Quality — 24 findings
3 critical (→ 2 CRITICAL, 1 MEDIUM after discussion), 6 high, 8 medium (→ 9), 4 low, 3 info
Full report: `.claude-coord/reports/audit-findings-test-analyst.md`

### Performance — 18 findings
0 critical (→ 1 CRITICAL after discussion), 3 high (→ 2), 7 medium, 5 low, 3 info
Full report: `.claude-coord/reports/audit-findings-performance-reviewer.md`

---

## Comparison with Previous Audit (2026-02-07 07:03)

### Findings Fixed Since Last Audit (confirmed by agents)
| Prior Finding | Status | Verified By |
|--------------|--------|-------------|
| Float-on-int merit score corruption (D-01 → H-19) | FIXED | data-analyst |
| Duplicate WorkflowStateDict definitions (D-02 → H-20) | FIXED | data-analyst |
| Missing ON DELETE CASCADE on experimentation FKs (H-23) | FIXED | data-analyst |
| Missing ON DELETE CASCADE on M5 FKs (H-24) | FIXED | data-analyst |
| Status fields without DB constraints | FIXED | data-analyst |
| AgentMeritScore missing unique constraint | FIXED | data-analyst |
| LoopStateManager read-then-write race | FIXED | data-analyst |
| time.sleep in agent retry — aexecute() added (C-02) | COSMETIC FIX | performance (aexecute exists but is dead code) |
| Unbounded circuit breaker dict (H-04) | FIXED | performance |
| Unbounded DLQ (P-05) | FIXED | performance |
| Buffer inline flush lock contention (H-01/P-06) | FIXED | performance |
| SentenceTransformer singleton (P-13) | FIXED | performance |
| close() calls asyncio.run() (H-06) | PARTIAL FIX | reliability (no asyncio.run, but client leaked) |
| Fixed pool size non-configurable (H-34) | FIXED | performance |
| Native tool def caching (P-15) | FIXED | performance |

### Recurring Issues (present in both audits)
| Issue | Prior ID | Current ID | Status |
|-------|----------|-----------|--------|
| Exception hierarchy fragmentation | H-10, H-11 | H-01 | Same scope, better documented |
| Auth UserStore ephemeral | H-25 | H-27 | Unfixed |
| StandardAgent god module | Hotspot | H-29 | Unfixed, now linked to dead async path |
| ExecutionTracker god module | H-17 | M-08 | Unfixed |
| security/ vs safety/ boundary confusion | H-16 | M-02 | Unfixed |
| Compiler executors depend on concrete AgentFactory | H-18 | M-09 | Unfixed |
| Thread pool starvation under parallel load | C-02 | C-01 | Cosmetic fix (aexecute exists but unused) |
| Duplicate test directories | H-27 | H-35 | Unfixed |
| Mocks lacking spec= | H-26 | H-33 | Unfixed (28.6% spec rate, was ~11% — partial improvement) |
| xfail tests in distributed rate limiting | H-32 | H-38 | Unfixed |
| Shell mode attack surface | H-13 | H-20 | Unfixed |
| Alembic migration gaps | H-21 | H-28 | Partially fixed (new migration added) |
| Dual DDL management | H-22 | M-38 | Unfixed |
| Missing ON DELETE CASCADE gaps | H-23/H-24 | FIXED | Fully remediated |

### New Issues Not in Previous Audit
| Current ID | Finding | Why New |
|-----------|---------|---------|
| C-02 | ApprovalWorkflow dict race | New discovery — approval.py not deeply examined before |
| C-03 | Observability as hidden DB layer (systemic) | Elevated from structural observation to CRITICAL via cross-agent evidence |
| C-04 | ToolRegistryProtocol mismatch | New discovery — Protocol conformance not checked before |
| C-05 | Non-atomic experimentation counters | New discovery — experimentation service counters not examined before |
| H-02 | ValidationError alias is function (regression) | Created by prior audit's fix |
| H-19 | acomplete() uses threading.Lock | New — revealed by tracing actual call paths |
| H-05 | LLM factory reads deprecated api_key | New — api_key migration not traced through factory |

---

## Recommended Actions (Prioritized by Team Consensus)

### Immediate (CRITICAL — fix now)

1. **C-01: Wire async path end-to-end** — Have `aexecute_iteration` call `self.llm.acomplete()`. Have at least one executor call `aexecute()`. This is the single highest-impact change for parallel performance.
2. **C-02: Add threading.Lock to ApprovalWorkflow._requests** — Safety-critical component, trivial fix, prevents race condition.
3. **C-03: Extract src/database/ from observability** — Move `get_session`, `DatabaseManager`, `init_database` to dedicated package. This unblocks fixes for 6+ downstream issues.
4. **C-04: Fix ToolRegistryProtocol.get_tool() → get()** — One-line Protocol fix + add conformance test.
5. **C-05: Use SQL atomic increments for experiment counters** — Replace `variant.total_executions += 1` with `update().values(total_executions=Variant.total_executions + 1)`.
6. **C-06: Add tests for untested self_improvement modules** — Priority: deployer.py, orchestrator.py, error_recovery.py.

### Short-term (HIGH — next sprint)

7. **H-01: Rebase orphan exceptions onto FrameworkException** — Fix ~15 exception classes.
8. **H-02: Fix ValidationError alias** — Make proper class instead of function.
9. **H-03/H-19: Fix async client lifecycle** — `acomplete()` should use `_get_async_client_safe()`.
10. **H-04: Replace f-string SQL with execution_options()** — Quick fix for dangerous pattern.
11. **H-27: Create database-backed UserStore** — Compound urgency with S-03/S-16.
12. **H-29: Begin StandardAgent decomposition** — Extract tool loop, safety checks as first step.
13. **H-33: Adopt spec= convention for test mocks** — Start with safety-critical interfaces.
14. **H-10/H-15: Fix sync retry (jitter + interruptibility)** — Match async path behavior.

### Backlog (MEDIUM + LOW)

See individual agent reports for full backlog items. Key themes:
- Database dialect abstraction (S-01, D-03, R-09)
- Deprecated shim cleanup (M-03, M-04, M-06)
- Exception module decomposition (H-30)
- Test infrastructure improvements (M-40 through M-47)
- Performance optimizations (M-48 through M-52)
