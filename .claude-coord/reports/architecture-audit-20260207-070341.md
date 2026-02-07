# Architecture Audit Report (Team Consensus)

**Generated:** 2026-02-07 07:03
**Method:** 7 specialist agents with cross-review discussion (2 rounds)
**Discussion Rounds:** 2
**Scope:** meta-autonomous-framework — 200 source files, 285 test files

---

## Executive Summary

**Total Findings: 136** (after discussion: 8 severity changes, 3 linked finding pairs)

| Severity | Count | Changed |
|----------|-------|---------|
| CRITICAL | 5     | -3 (D-01↓, D-02↓, API-01↓) +1 (Sec-03↑) |
| HIGH     | 34    | +3 (from CRITICAL downgrades) -1 (S-01↓, P-05↓) |
| MEDIUM   | 50    | +2 (S-01↓, P-05↓) |
| LOW      | 24    | — |
| INFO     | 23    | — |

### Top Risks (team consensus)

1. **coord_service hard dependency + code injection** (S-00/Sec-03, CRITICAL) — Undeclared dependency with unguarded imports + sys.path[0] injection of writable directory with safety checks disabled. Combined structural + security risk. Agreed by: structural-architect, security-auditor.

2. **time.sleep() blocks shared thread pool in agent retry** (P-01, CRITICAL) — Blocks 8-thread pool for up to 14s per failing agent. Directly limits parallel execution. Linked with R-15 (no retry jitter). Agreed by: performance-reviewer, reliability-reviewer.

3. **Buffer _flush_unsafe() holds lock during DB I/O** (R-01/P-06, HIGH) — Inline flush path blocks all observability producers during DB writes. Background flush uses correct swap-and-release pattern. Team-lead decision: HIGH (reliability conceded, performance upgraded, team-lead chose HIGH based on mitigating factor of background thread handling common case).

4. **Safety validation fail-open** (R-03, HIGH) — Broken policy engine silently allows LLM calls without safety checks. Confirmed as security issue by security-auditor. Linked with API-05 (dual exception hierarchy makes correct error handling structurally difficult).

5. **Silent merit score data corruption** (D-01, HIGH) — Float increment on integer columns. Currently dead code path (no callers pass "mixed"), but latent integrity bomb with zero test coverage. Downgraded from CRITICAL since no data corrupted yet.

### Key Strengths
1. **Mature security posture** — Jinja2 ImmutableSandboxedEnvironment, YAML safe_load everywhere, no eval/exec, OAuth with CSRF/PKCE, 8-layer log injection prevention, secret redaction
2. **Strong resilience patterns** — Circuit breaker with thundering-herd prevention, atomic checkpoint writes, token bucket with NaN/Inf validation, observability buffer DLQ
3. **Clean domain/infrastructure separation** — WorkflowDomainState vs InfrastructureContext properly separated, Protocol definitions for infrastructure components

---

## Consensus Findings by Severity

### CRITICAL (5)

| # | Finding | File:Line | Agent | Agreement | Recommendation |
|---|---------|-----------|-------|-----------|----------------|
| C-01 | coord_service hard dependency + sys.path code injection | `deployer.py:31`, `cli.py:32`, `config_loader.py:199-212` | structural + security | Consensus (upgraded) | Make coord_service an installable optional dep in pyproject.toml, remove all sys.path.insert() calls, guard imports with try/except ImportError |
| C-02 | time.sleep() blocks shared thread pool in agent retry (linked with R-15) | `standard_agent.py:362` | performance | Consensus | Provide async def aexecute() with await asyncio.sleep() + jittered backoff |
| C-03 | Zero test coverage on 4 observability modules (alerting, merit_score_service, decision_tracker, aggregation) | `src/observability/` | test-analyst | Unanimous | Create dedicated test files; priority: alerting (HALT_WORKFLOW can silently fail) and merit_score_service (has data corruption bug) |
| C-04 | Zero test coverage on CLI rollback (safety-critical) and detail_report | `src/cli/rollback.py`, `src/cli/detail_report.py` | test-analyst | Unanimous | Add test_rollback.py with Click CliRunner; priority: rollback.py executes state changes |
| C-05 | Zero test coverage on security_limits.py (billion laughs protection) | `src/compiler/security_limits.py` | test-analyst | Maintained after challenge | Create test_security_limits.py verifying each constant and behavior when exceeded |

### HIGH (34)

| # | Finding | File:Line | Agent | Agreement | Recommendation |
|---|---------|-----------|-------|-----------|----------------|
| H-01 | Buffer _flush_unsafe() holds lock during DB I/O | `buffer.py:338-351` | reliability + performance | Team-lead: HIGH | Refactor to swap-and-flush pattern (already exists in flush()) |
| H-02 | Safety validation error silently swallowed (fail-open) | `standard_agent.py:333-334` | reliability + security | Consensus | Change to fail-closed: block LLM call if policy validation errors |
| H-03 | Lazy asyncio.Lock TOCTOU race in failover | `llm_failover.py:166-170` | reliability | Unanimous | Initialize asyncio.Lock eagerly in __init__ |
| H-04 | Unbounded _circuit_breakers class dict | `llm/base.py:99` | reliability + performance | Consensus | Add LRU eviction or WeakValueDictionary |
| H-05 | Approval wait blocks thread pool (1 hour max) | `executor.py:505-539` | reliability | Unanimous | Dedicated approval thread pool or async notification |
| H-06 | close() calls asyncio.run() fails in nested loops | `llm/base.py:253-282` | reliability + performance | Consensus | Restructure sync/async cleanup paths |
| H-07 | Dead error handling in create_llm_client (downgraded) | `llm/factory.py:100` | api-reviewer | Consensus ↓CRITICAL | Wrap LLMProvider() in try/except like create_llm_provider does |
| H-08 | "ExecutionContext" names two different types | `domain_state.py:442`, `core/context.py:19` | api-reviewer | Unanimous | Remove DomainExecutionContext alias, strengthen deprecation |
| H-09 | Two competing LLM factory functions | `llm/factory.py:14,70` | api-reviewer | Unanimous | Unify or deprecate create_llm_provider |
| H-10 | ValidationError shadows Pydantic's ValidationError | `utils/exceptions.py:604` | api-reviewer | Unanimous | Rename to FrameworkValidationError |
| H-11 | Dual safety exception hierarchies | `safety/exceptions.py:28`, `utils/exceptions.py:573,563` | api-reviewer + security | Linked with H-02 | Unify hierarchy; make SecurityError inherit FrameworkException |
| H-12 | Six registries with inconsistent APIs | Multiple registries | api-reviewer + structural | Consensus | Define common Registry[T] Protocol |
| H-13 | Shell mode regex-before-lexer parsing fragility | `tools/bash.py:216-343` | security | Unanimous | Replace regex splitting with proper shell lexical analysis |
| H-14 | OAuth token confusion via shared "anonymous" key | `auth/routes.py:310-314` | security | Unanimous | Use per-flow identifier instead of "anonymous" |
| H-15 | sys.path manipulation (part of C-01) | `config_loader.py:199-212` | security | Upgraded to C-01 | See C-01 |
| H-16 | Overlapping safety/security domain boundary | `src/safety/` vs `src/security/` | structural | Unanimous | Define clear boundary, consolidate rate limiting |
| H-17 | ExecutionTracker god class (1075 lines) | `observability/tracker.py` | structural | Unanimous | Extract per-entity trackers |
| H-18 | Executors depend on concrete AgentFactory | `sequential.py:18`, `parallel.py:10` | structural | Unanimous | Inject AgentCreator callable |
| H-19 | Merit score float-on-int corruption (downgraded, latent) | `merit_score_service.py:81-82` | data-analyst | Consensus ↓CRITICAL | Change fields to float or add mixed_decisions counter |
| H-20 | Duplicate WorkflowStateDict (downgraded, type-hints only) | `state_manager.py:19`, `executors/base.py:20` | data-analyst | Consensus ↓CRITICAL | Consolidate to single canonical definition |
| H-21 | 7+ tables missing from Alembic migration | `alembic/versions/` | data-analyst | Unanimous | Run alembic revision --autogenerate |
| H-22 | Dual schema management (create_all bypasses Alembic) | `database.py:140-143` | data-analyst | Unanimous | Choose single DDL strategy |
| H-23 | Missing ON DELETE CASCADE on experimentation FKs | `experimentation/models.py` | data-analyst | Unanimous | Add ondelete="CASCADE" to FK columns |
| H-24 | Missing ON DELETE CASCADE on M5 FKs | `self_improvement/storage/experiment_models.py` | data-analyst | Unanimous | Add ondelete="CASCADE" and cascade_delete |
| H-25 | Auth UserStore is ephemeral (in-memory only) | `auth/session.py:193-324` | data-analyst | Unanimous | Create database-backed UserStore |
| H-26 | 89% of mocks lack spec= (561/625) | tests/ global | test-analyst | Unanimous | Adopt spec= convention, start with safety-critical files |
| H-27 | 4 duplicate test directory pairs | tests/ | test-analyst | Unanimous | Consolidate to tests/test_* convention |
| H-28 | 11 bare except: clauses in CB persistence tests | `test_llm_providers.py:1732-2015` | test-analyst | Unanimous | Replace with specific exception types |
| H-29 | OAuth service minimal unit testing | `auth/oauth/service.py` | test-analyst | Unanimous | Add isolated unit tests |
| H-30 | LLM cache lacks concurrent/error tests | `cache/llm_cache.py` | test-analyst | Unanimous | Add threading stress tests, error injection |
| H-31 | 3 timing-dependent tests (time.sleep) | Multiple test files | test-analyst | Unanimous | Mock time or use freezegun |
| H-32 | 8 permanent xfail in distributed rate limiting | `test_distributed_rate_limiting.py` | test-analyst | Unanimous | Triage: backlog with timeline or remove |
| H-33 | Tests with except:pass swallowing assertions | `test_prompt_engine.py` | test-analyst | Unanimous | Use explicit branching, pytest.raises |
| H-34 | Global ThreadPoolExecutor fixed at 8 workers | `standard_agent.py:60-63` | performance | Unanimous | Make configurable via env var or config |

### MEDIUM (50)

Key findings (abbreviated — see individual agent reports for full details):

| # | Finding | Agent |
|---|---------|-------|
| M-01 | Triple shim chain (downgraded, one layer removed) | structural |
| M-02 | Exception god module (699 lines) | structural |
| M-03 | Dual experimentation systems | structural |
| M-04 | Compiler mixes 4+ responsibilities | structural |
| M-05 | Missing __init__.py in 2 packages | structural |
| M-06 | Tool executor depends on observability | structural |
| M-07 | Safety factory hardcodes 10 policies | structural |
| M-08 | No lockfile + version conflicts (pyproject vs requirements.txt) | security |
| M-09 | InMemorySessionStore no session limit | security |
| M-10 | Denylist-based template variable filtering | security |
| M-11 | Checkpoint integrity not verified | security |
| M-12 | Encryption key falls back to env var | security |
| M-13 | Workspace path no boundary validation | security |
| M-14 | Hardcoded redirect allowlist | security |
| M-15 | Global singleton race in security components | security |
| M-16 | Circuit breaker metrics outside lock | reliability |
| M-17 | State change callbacks silently swallowed | reliability |
| M-18 | Retry inside circuit breaker masks degradation | reliability |
| M-19 | threading.Lock in async client creation | reliability |
| M-20 | Module-level thread pool wait=False at exit | reliability |
| M-21 | Parallel executor outer handler lacks logging | reliability |
| M-22 | Checkpoint save failure silently swallowed | reliability |
| M-23 | 6 bare except Exception in resource limit policy | reliability |
| M-24 | StageExecutor parameters typed as Any | api-reviewer |
| M-25 | ObservabilityBackend 16 abstract methods inconsistent | api-reviewer |
| M-26 | AgentResponse.tool_calls untyped dicts | api-reviewer |
| M-27 | Status parameters untyped strings | api-reviewer |
| M-28 | Backward-compat aliases without deprecation | api-reviewer |
| M-29 | Factory parameter typed as Any | api-reviewer |
| M-30 | SafetyPolicy.validate() untyped Dict | api-reviewer |
| M-31 | Top-level __init__.py imports through shim | api-reviewer |
| M-32 | BaseLLM.complete() leaks transport exceptions | api-reviewer |
| M-33 | BaseTool.execute() no-exception contract unenforced | api-reviewer |
| M-34 | Status fields free-form strings no DB constraints | data-analyst |
| M-35 | ExperimentOrchestrator long-lived session | data-analyst |
| M-36 | AgentMeritScore lacks unique constraint | data-analyst |
| M-37 | No data size validation on JSON blobs | data-analyst |
| M-38 | CustomMetric.execution_id not a FK | data-analyst |
| M-39 | LoopStateManager read-then-write without upsert | data-analyst |
| M-40 | DLQ unbounded growth (downgraded) | performance |
| M-41 | Agent recreated from config on every execution | performance |
| M-42 | Each BaseLLM creates own httpx.Client | performance |
| M-43 | Deliberate 10-50ms sleep on experiment creation | performance |
| M-44 | Agent metrics N+1 queries in flush | performance |
| M-45 | Hardcoded prompt size limits | performance |
| M-46 | WebScraper creates new httpx.Client per request | performance |
| M-47 | SentenceTransformer loaded mid-dialogue | performance |
| M-48 | JSON serializability probe on every input field | performance |
| M-49 | No test pyramid enforcement | test-analyst |
| M-50 | Global state reset relies on try/except ImportError | test-analyst |

### LOW (24) and INFO (23)

See individual agent reports for full details.

---

## Discussion Log

### Severity Changes

| # | File:Line | Original | Final | Reason | Decided By |
|---|-----------|----------|-------|--------|------------|
| 1 | `buffer.py:338-351` | CRITICAL (R-01) | HIGH | Background thread handles common case; inline path requires specific trigger | Team-lead (reliability conceded, performance upgraded — chose reliability's reasoning) |
| 2 | `config_loader.py:199-212` | HIGH (Sec-03) | CRITICAL (merged into S-00) | Combined structural + security risk: undeclared dep + sys.path injection + safety disabled | Consensus: structural + security |
| 3 | `merit_score_service.py:81-82` | CRITICAL (D-01) | HIGH | Dead code path — no callers pass "mixed" currently | Data-analyst self-revised |
| 4 | `state_manager.py:19`, `executors/base.py:20` | CRITICAL (D-02) | HIGH | TypedDicts are type-hints only, no runtime impact | Data-analyst self-revised |
| 5 | `llm/factory.py:100` | CRITICAL (API-01) | HIGH | Users still get error (raw ValueError), just not helpful | API-reviewer self-revised |
| 6 | `src/llm/` shim chain | HIGH (S-01) | MEDIUM | One layer removed (src/llm/__init__.py deleted); 5 imports to fix for full cleanup | Structural self-revised |
| 7 | `buffer.py:171` DLQ | HIGH (P-05) | MEDIUM | Secondary symptom of already-severe DB outage | Performance self-revised |
| 8 | `buffer.py:338-351` | HIGH (P-06) | CRITICAL | Availability risk — all agents stall during DB writes | Performance self-revised (but overridden by team-lead to HIGH) |

### Cross-Cutting Insights

1. **Unspecced mocks + broad except = silent fail-open mechanism** — Test-analyst identified that 89% of mocks lacking `spec=` combined with broad `except Exception` handlers creates a pathway where interface drift is invisible. The safety validation fail-open (R-03) may be a direct consequence: if safety interfaces changed, unspecced test mocks wouldn't catch the drift, and the broad except allows the resulting error through silently.

2. **Backward compatibility accumulation** — Both structural (shim chains) and API (alias proliferation) findings stem from the same root cause: refactorings that preserve old names indefinitely without deprecation timelines. API-reviewer and structural-architect agreed on a unified deprecation policy.

3. **Exception hierarchy → error handling difficulty → broad except** — The dual safety exception hierarchy (API-05) makes it structurally hard to write correct error handling. This contributes to the pervasive `except Exception` pattern (170+ instances) and specifically to the fail-open behavior in R-03. Fixing the hierarchy reduces the motivation for broad catches.

4. **Zero test coverage on safety-critical modules** — alerting.py can silently fail to halt runaway workflows, security_limits.py protection constants are untested, merit_score_service.py has a latent data corruption bug. All three share zero test coverage, meaning bugs persist undetected.

5. **coord_service: single root cause, dual impact** — The same unguarded imports + sys.path manipulation create both an ImportError availability risk and a code injection security risk. Fixing the structural issue (proper packaging) eliminates both simultaneously.

### Disagreements Resolved by Team Lead

**Buffer flush severity (R-01/P-06):** Reliability-reviewer originally rated CRITICAL, then conceded to HIGH based on the background thread mitigating the common case. Performance-reviewer originally rated HIGH, then upgraded to CRITICAL based on the availability argument. With the two agents moving in opposite directions, I (team lead) chose HIGH based on reliability-reviewer's detailed analysis: the background flush thread handles the time-based path correctly, and the inline path requires a specific trigger (100 items + slow DB simultaneously). The fix is straightforward and should be prioritized, but the current blast radius is bounded.

---

## Hotspot Modules

### `src/observability/buffer.py`
| Agent | Finding | Severity |
|-------|---------|----------|
| reliability-reviewer | _flush_unsafe holds lock during DB I/O (R-01) | HIGH |
| performance-reviewer | Inline flush holds producer lock (P-06) | HIGH |
| performance-reviewer | DLQ grows unbounded (P-05) | MEDIUM |

**Root cause (consensus):** `_flush_unsafe()` doesn't follow the swap-and-release pattern that `flush()` already implements.
**Fix strategy (consensus):** Apply `flush()`'s pattern to `_flush_unsafe()`. Add `max_dlq_size` cap.

### `src/agents/standard_agent.py`
| Agent | Finding | Severity |
|-------|---------|----------|
| performance-reviewer | time.sleep() blocks thread pool (P-01) | CRITICAL |
| reliability-reviewer | Safety validation fail-open (R-03) | HIGH |
| performance-reviewer | Fixed 8-thread pool (P-02) | HIGH |
| reliability-reviewer | Module-level pool wait=False (R-11) | MEDIUM |

**Root cause (consensus):** No async execution path for agents; sync-only design with shared thread pool.
**Fix strategy (consensus):** Add `async def aexecute()` with proper async sleep + jitter. Make pool size configurable. Change safety validation to fail-closed.

### `src/agents/llm/base.py`
| Agent | Finding | Severity |
|-------|---------|----------|
| reliability-reviewer | Unbounded circuit breaker dict (R-04) | HIGH |
| performance-reviewer | Same (P-04) | HIGH |
| reliability-reviewer | close() asyncio.run in nested loop (R-06) | HIGH |
| performance-reviewer | Same (P-03) | HIGH |
| reliability-reviewer | threading.Lock in async path (R-10) | MEDIUM |
| reliability-reviewer | Retry masks degradation (R-09) | MEDIUM |
| performance-reviewer | Each instance creates own httpx.Client (P-08) | MEDIUM |
| reliability-reviewer | No retry jitter (R-15) | LOW |

**Root cause (consensus):** Mixed sync/async design with shared mutable state. HTTP client lifecycle not aligned with circuit breaker sharing.
**Fix strategy (consensus):** Share httpx clients like circuit breakers. Initialize async resources eagerly. Add LRU eviction to circuit breaker dict. Add jitter to retry.

### `src/observability/merit_score_service.py`
| Agent | Finding | Severity |
|-------|---------|----------|
| data-analyst | Float-on-int silent corruption (D-01) | HIGH |
| test-analyst | Zero test coverage | CRITICAL |

**Root cause (consensus):** Module built with "mixed" outcome support but integer-typed columns + no tests = latent corruption.
**Fix strategy (consensus):** Add dedicated tests first, then fix column types or add mixed_decisions counter.

---

## Individual Agent Reports

### Structural Architecture — 15 findings
1 critical (coord_service), 4 high, 6 medium, 3 low, 1 info
Full report: `.claude-coord/reports/audit-findings-structural-architect.md`

### Security — 19 findings
0 critical (Sec-03 upgraded to C-01), 3 high, 7 medium, 3 low, 6 info
Full report: `.claude-coord/reports/audit-findings-security-auditor.md`

### Reliability — 18 findings
1 critical (R-01 downgraded to HIGH), 5 high, 8 medium, 3 low, 1 info
Full report: `.claude-coord/reports/audit-findings-reliability-reviewer.md`

### API Contracts — 24 findings
1 critical (API-01 downgraded to HIGH), 5 high, 10 medium, 5 low, 3 info
Full report: `.claude-coord/reports/audit-findings-api-reviewer.md`

### Data & State — 20 findings
2 critical (both downgraded to HIGH), 5 high, 6 medium, 4 low, 3 info
Full report: `.claude-coord/reports/audit-findings-data-analyst.md`

### Test Quality — 21 findings
3 critical, 7 high, 6 medium, 3 low, 2 info
Full report: `.claude-coord/reports/audit-findings-test-analyst.md`

### Performance — 19 findings
1 critical, 5 high, 8 medium, 3 low, 2 info
Full report: `.claude-coord/reports/audit-findings-performance-reviewer.md`

---

## Recommended Actions (Prioritized by Team Consensus)

### Immediate (CRITICAL — fix now)

1. **C-01: Guard coord_service imports** — Remove sys.path.insert(), add try/except ImportError, declare as optional dependency
2. **C-02: Add async agent execution path** — async def aexecute() with asyncio.sleep() + jittered backoff
3. **C-03/C-04/C-05: Add tests for untested safety-critical modules** — alerting.py (HALT_WORKFLOW), rollback.py, security_limits.py, merit_score_service.py

### Short-term (HIGH — next sprint)

4. **H-02: Fix safety fail-open → fail-closed** in StandardAgent + unify exception hierarchy (H-11)
5. **H-01: Fix buffer _flush_unsafe** — apply swap-and-flush pattern
6. **H-03: Fix asyncio.Lock race** in FailoverProvider
7. **H-04: Add LRU eviction** to circuit breaker dict
8. **H-19: Fix merit score columns** — change to float or add mixed_decisions counter
9. **H-20: Consolidate WorkflowStateDict** to single definition
10. **H-21/H-22: Fix Alembic migrations** — add missing tables, choose single DDL strategy
11. **H-23/H-24: Add ON DELETE CASCADE** to experimentation/M5 FKs
12. **H-26: Adopt spec= convention** for mocks, starting with safety-critical test files

### Backlog (MEDIUM + LOW)

See individual agent reports for full backlog items. Key themes:
- Exception module decomposition (M-02)
- Backward-compat deprecation policy (M-28, M-31)
- Performance optimizations (M-41 through M-48)
- Test architecture improvements (M-49, M-50)
