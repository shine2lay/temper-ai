# Architecture Audit Report (Team Consensus)

**Generated:** 2026-02-06 05:20
**Method:** 7 specialist agents with 2 rounds of cross-review discussion
**Discussion Rounds:** 2
**Scope:** meta-autonomous-framework — 200 source files, 282 test files

---

## Executive Summary

**Total Findings: 120** (after discussion: 8 severity changes, 1 new finding added, 6 findings merged)

| Severity | Count | Changed |
|----------|-------|---------|
| CRITICAL | 5     | +2 upgraded, -1 downgraded, +1 merged |
| HIGH     | 14    | -1 downgraded from CRITICAL, +1 merged |
| MEDIUM   | 30    | +1 downgraded from HIGH |
| LOW      | 14    | — |
| INFO     | 12    | — |

### Top Risks (team consensus)

1. **Prompt grows unboundedly in tool-calling loop, displacing system prompt** — agreed by performance-reviewer + security-auditor, severity CRITICAL (perf + security). Context window displacement bypasses prompt injection defenses. Zero test coverage for this code path.

2. **No consistent database session lifecycle management** — agreed by reliability-reviewer + data-analyst, severity CRITICAL. Three distinct session patterns (context manager, standalone, long-lived) with leak paths in SQL backend and M5 orchestrator. Can exhaust SQLite write locks.

3. **Alembic migration only covers 12 of 19 tables** — agreed by data-analyst + team-lead, severity CRITICAL. `alembic upgrade head` on fresh DB causes runtime crashes for experimentation and self_improvement subsystems.

4. **Incomplete LLM provider migration: triple-layer shim chain + dual factories** — agreed by structural-architect + api-reviewer, severity CRITICAL. Production code imports from shims, two competing factory functions with different signatures and provider coverage.

5. **Bidirectional dependency between agents and compiler** — structural-architect, severity CRITICAL. Neither module can be tested in isolation. AgentConfig in compiler imported by agents, AgentFactory in agents imported by compiler executors.

### Key Strengths

1. **Exemplary OAuth implementation** — session fixation prevention, CSRF, PKCE, secure cookies, comprehensive security headers (security-auditor)
2. **Defense-in-depth security** — SSRF protection (DNS rebinding prevention), Jinja2 sandboxing, command injection prevention, prompt injection detection, output sanitization (security-auditor)
3. **Atomic checkpoint writes** — file backend uses tempfile + fsync + os.replace, Redis backend uses pipeline transactions (data-analyst)
4. **Well-structured observability indexing** — 30+ composite indexes for common query patterns across observability and experimentation models (data-analyst)
5. **Mature circuit breaker** — state persistence, thundering herd prevention, error classification, thread-safe state transitions (reliability-reviewer)

---

## Consensus Findings by Severity

### CRITICAL

| # | Finding | File:Line | Original Agent | Consensus | Agreement | Recommendation |
|---|---------|-----------|---------------|-----------|-----------|----------------|
| C-01 | **Prompt grows unboundedly in tool loop; tail-truncation discards system prompt, bypassing injection defenses** | `standard_agent.py:790-793`, `response_parser.py:63` | performance-reviewer (PERF-01) + security-auditor (SEC-17) | CRITICAL (perf+security) | Unanimous | Sliding-window truncation that pins system prompt; re-scan tool results through prompt injection detector; enforce per-iteration prompt budget |
| C-02 | **No consistent database session lifecycle — leak paths in SQL backend, M5 orchestrator, dual schema management** | `sql_backend.py:762`, `experiment_orchestrator.py:212`, `database.py:140` | reliability-reviewer (R-01) + data-analyst (D-02, D-04) | CRITICAL (consolidated) | Unanimous | Establish codebase-wide invariant: every session via context manager. Refactor SQL backend to per-operation sessions, M5 to accept session factory |
| C-03 | **Alembic migration only covers observability tables; fresh deployment crashes for 2/3 subsystems** | `alembic/env.py:24` | data-analyst (D-01, upgraded from HIGH) | CRITICAL | Unanimous | Add imports for experimentation + self_improvement models to env.py; generate new migration |
| C-04 | **Incomplete LLM provider migration: triple shim chain + dual factory functions** | `llm_providers.py`, `llm_factory.py`, `llm/factory.py`, `src/llm/` | structural-architect (S-04) + api-reviewer (A-02, A-08) | CRITICAL (merged) | Unanimous | Delete `src/llm/` (38-line shim), deprecate `llm_providers.py`, consolidate on `llm/factory.py`, update ~5 import sites |
| C-05 | **Bidirectional dependency: agents <-> compiler** | `agents/` <-> `compiler/schemas.py` | structural-architect (S-01) | CRITICAL | Original | Extract shared schemas to `src/schemas/` or `src/contracts/` package; inject AgentFactory into executors |

### HIGH

| # | Finding | File:Line | Original Agent | Consensus | Agreement | Recommendation |
|---|---------|-----------|---------------|-----------|-----------|----------------|
| H-01 | **Circuit breaker metrics race: `rejected_calls += 1` outside lock** | `circuit_breaker.py:365,389,413` | reliability-reviewer (R-02, downgraded from CRITICAL) | HIGH | Unanimous | Move increment inside `_reserve_execution()` lock scope |
| H-02 | **Split exception hierarchies + 683-line coupling hub** | `utils/exceptions.py`, `safety/exceptions.py` | structural-architect (S-03) + api-reviewer (A-04) | HIGH (merged) | Unanimous | Create `FrameworkException` base in `core/exceptions.py`; split domain exceptions into module-specific files |
| H-03 | **TokenBucketManager.buckets grows without bound** | `token_bucket.py:362-563` | reliability-reviewer (R-06) + performance-reviewer (PERF-05) | HIGH (merged) | Unanimous | Add LRU eviction or TTL-based cleanup for stale buckets |
| H-04 | **Approval polling blocks threads for up to 1 hour** | `executor.py:505-528` | reliability-reviewer (R-04) + performance-reviewer (PERF-09) | HIGH (merged) | Unanimous | Use `threading.Event.wait()` instead of `time.sleep()` polling |
| H-05 | **`retry_agent` error policy declared but never implemented** | `sequential.py:317-325` | reliability-reviewer (R-03) | HIGH | Original | Implement retry logic or raise `NotImplementedError` |
| H-06 | **Parallel stage retry loop has no wall-clock timeout** | `parallel.py:78` | reliability-reviewer (R-09) | HIGH | Original | Add maximum wall-clock timeout for retry loop |
| H-07 | **SQL injection via f-string LIMIT clause (zero test coverage)** | `strategy_learning.py:188` | security-auditor (SEC-01) | HIGH | Original | Use parameterized query: `query += " LIMIT ?"` |
| H-08 | **Credential logging: Redis URLs with potential passwords logged unmasked** | `state_store.py:263`, `llm_security.py:560` | security-auditor (SEC-02) | HIGH | Original | Use existing `_mask_database_url()` utility before logging |
| H-09 | **All 16 production dependencies use `>=` minimum pins only** | `pyproject.toml:17-50` | security-auditor (SEC-03) | HIGH | Original | Pin exact versions or use `~=X.Y` compatible release constraints |
| H-10 | **CLI module has zero test coverage (primary user entry point)** | `src/cli/` (entire module) | test-analyst (T-01) + security-auditor (MEDIUM security concern) | HIGH | Unanimous | Create Click `CliRunner` tests; add PathSafetyValidator to `--output` path |
| H-11 | **5 duplicate test directories create conftest conflicts** | `tests/safety/` vs `tests/test_safety/`, etc. | test-analyst (T-02) | HIGH | Original (team-lead decision: downgraded from CRITICAL — fixable without code changes) | Consolidate into canonical `tests/test_*/` dirs; merge conftest fixtures |
| H-12 | **No tests for response_parser, agent_observer, cost_estimator** | `src/agents/response_parser.py`, etc. | test-analyst (T-03) | HIGH | Original | Create dedicated test files for each |
| H-13 | **90% of mocks lack `spec=` — double-blind-spot with `Any` types** | Across 507 Mock instances | test-analyst (T-04) + api-reviewer (A-03) | HIGH | Unanimous | Add `spec=RealClass` to mocks; prioritize ConfigLoader, AgentFactory, ToolRegistry, ExecutionTracker |
| H-14 | **23 vacuous `assert True` statements verify nothing** | 13 test files | test-analyst (T-07) | HIGH | Original | Replace with meaningful assertions |

### MEDIUM

| # | Finding | File:Line | Agent | Recommendation |
|---|---------|-----------|-------|----------------|
| M-01 | self_improvement is 12,193-line monolith (downgraded from CRITICAL) | `src/self_improvement/` | structural (S-02) | Decouple `database.py:139` import first; then refactor/extract |
| M-02 | safety/security overlapping domain boundary | `safety/` vs `security/` | structural (S-05) | Define clear boundary or merge security into safety |
| M-03 | ExecutionTracker is 1,075-line god class | `tracker.py` | structural (S-06) | Delegate to sub-trackers (workflow, stage, agent, llm_call) |
| M-04 | Dual experimentation systems | `experimentation/` vs `self_improvement/experiment_orchestrator.py` | structural (S-09) | Unify or have self_improvement build on experimentation |
| M-05 | hasattr chains instead of Protocols (30+ instances) | Multiple files | structural (S-10) | Define Protocol classes for engine capabilities |
| M-06 | ExecutionContext naming collision — two different types | `core/context.py` vs `compiler/domain_state.py:370` | api-reviewer (A-01) | Rename compiler alias to InfrastructureContext; deprecate ExecutionContext alias |
| M-07 | InfrastructureContext uses `Optional[Any]` for all 4 fields | `domain_state.py:348-352` | api-reviewer (A-03) | Define Protocol types for each field |
| M-08 | RateLimitPolicyV2 re-export name mismatch | `safety/__init__.py:94` | api-reviewer (A-05) | Rename consistently or drop "V2" alias |
| M-09 | Safety model/interface alias confusion | `safety/__init__.py:107-110` | api-reviewer (A-06) | Document canonical types; differentiate ORM vs interface types |
| M-10 | auth module has empty `__init__.py` — no public API surface | `auth/__init__.py` | api-reviewer (A-07) | Add `__all__` exports for public API |
| M-11 | Status fields use free-form strings without DB CHECK constraints | 19 SQLModel tables | data-analyst (D-03) | Add CHECK constraints or model-level validators |
| M-12 | M5Experiment stores JSON as TEXT strings | `experiment_models.py:29-37` | data-analyst (D-05) | Change to `sa_column=Column(JSON)` |
| M-13 | M5Experiment stores timestamps as TEXT strings | `experiment_models.py:35-36` | data-analyst (D-06) | Change to `datetime` fields with `default_factory=utcnow` |
| M-14 | Workflow state is a plain dict with no mutation validation | `state_manager.py:52-66` | data-analyst (D-07) | Return typed objects instead of raw dicts |
| M-15 | Mixed session commit patterns in SQL backend | `sql_backend.py:153` | data-analyst (D-08) | Standardize on single session management pattern |
| M-16 | M5 loop state uses separate coordination DB with raw SQL | `loop/state_manager.py:57-69` | data-analyst (D-09) | Migrate to main SQLModel database or create integration bridge |
| M-17 | Embedded raw SQL migration duplicates ORM model | `storage/models.py:123-161` | data-analyst (D-10) | Remove raw SQL; add CHECK constraints to SQLModel fields |
| M-18 | Deprecated raw SQL migration system still present | `migrations.py:231-319` | data-analyst (D-11) | Remove `apply_migration()` entirely; point to Alembic |
| M-19 | Experiment.updated_at not auto-updated by DB | `experimentation/models.py:140` | data-analyst (D-12) | Add `onupdate=utcnow` to field definition |
| M-20 | Duplicate state definitions: LangGraphWorkflowState vs WorkflowDomainState | `langgraph_state.py:22` + `domain_state.py:33` | data-analyst (D-13) | Extract shared domain fields into mixin |
| M-21 | Buffer flush-before-callback (downgraded from HIGH) | `buffer.py:328-379` | reliability (R-08) | Use swap-and-flush to reduce lock hold time |
| M-22 | Strategy registry silently swallows import errors | `registry.py:262,372` | reliability (R-10) | Log exception at WARNING level |
| M-23 | Background flush thread daemon runs until process exit | `buffer.py:518-528` | reliability (R-11) | Add `__del__` method or require context manager usage |
| M-24 | Circuit breaker instances not shared per endpoint | `llm/base.py:142-147` | reliability (R-12) | Share breaker per `(provider, base_url)` pair |
| M-25 | Agent error message may contain sensitive information | `standard_agent.py:252-262` | reliability (R-13) | Use `sanitize_error_message()` on exception text |
| M-26 | Agent retry uses blocking `time.sleep()` in thread pool | `standard_agent.py:322-343` | reliability (R-14) | Document parallelism impact; consider non-blocking wait |
| M-27 | async failover uses threading.Lock, blocks event loop | `llm_failover.py:180-189` | reliability (R-16) | Use `asyncio.Lock` for async path |
| M-28 | New ThreadPoolExecutor created per tool-call batch | `standard_agent.py:445-448` | performance (PERF-03) | Reuse single thread pool across batches |
| M-29 | SQLite StaticPool serializes all DB access | `database.py:86-88` | performance (PERF-06) | Enable WAL mode for SQLite; use PostgreSQL for production |
| M-30 | Cache eviction sorts entire cache O(n log n) | `action_policy_engine.py:560-567` | performance (PERF-11) | Use OrderedDict for O(1) LRU eviction |

### LOW

| # | Finding | File:Line | Agent |
|---|---------|-----------|-------|
| L-01 | Safety __init__.py lazy loading pattern hard to discover | `safety/__init__.py` | structural |
| L-02 | BaseLLM uses hasattr for context.agent_id unnecessarily | `llm/base.py:419,469` | structural |
| L-03 | ExecutionContext re-exported from 3+ locations | `core/context.py` → 3 re-exports | structural |
| L-04 | Subprocess workspace path not validated | `erc721_quality.py:144-330` | security |
| L-05 | Isolation level injected via f-string (enum-guarded) | `database.py:188` | security |
| L-06 | Medium-confidence secret patterns lack word boundaries | `utils/secrets.py:425-426` | security |
| L-07 | InMemorySessionStore usable in production with no guard | `session.py:53-191` | security |
| L-08 | AgentMeritScore lacks unique constraint on (agent_name, domain) | `observability/models.py:309-339` | data-analyst |
| L-09 | M5Experiment.results lacks cascade delete | `experiment_models.py:39` | data-analyst |
| L-10 | Cascade syntax inconsistency across models | `experimentation/models.py:143-145` | data-analyst |
| L-11 | LLM prompts/responses stored as unencrypted plain text | `observability/models.py:203-204` | data-analyst |
| L-12 | No database-backed UserStore implementation | `session.py` | data-analyst |
| L-13 | 8 xfail tests for unimplemented distributed rate limiting | `test_distributed_rate_limiting.py` | test-analyst |
| L-14 | Placeholder test with skip + `assert True` | `test_documentation_examples.py:178` | test-analyst |

### INFO

| # | Finding | Agent | Note |
|---|---------|-------|------|
| I-01 | 6 independent registry patterns — no shared base | structural | Low priority refactoring |
| I-02 | Secret file exclusions properly configured in .gitignore | security | Positive |
| I-03 | Jinja2 ImmutableSandboxedEnvironment | security | Positive |
| I-04 | YAML loading uses safe_load everywhere | security | Positive |
| I-05 | OAuth follows security best practices | security | Positive |
| I-06 | Comprehensive indexing strategy | data-analyst | Positive |
| I-07 | File checkpoint backend uses atomic writes | data-analyst | Positive |
| I-08 | SQLite foreign keys properly enabled per connection | data-analyst | Positive |
| I-09 | Migration failure may leave DB inconsistent | reliability | Monitor |
| I-10 | Circuit breaker dynamically imports on every failure | reliability | Minor overhead |
| I-11 | Observability buffer has mature retry/DLQ | reliability | Positive |
| I-12 | Global singletons with manual lock-based init | performance | Existing test cleanup support |

---

## Discussion Log

### Severity Changes

| # | File:Line | Original | Final | Reason | Decided By |
|---|-----------|----------|-------|--------|------------|
| 1 | `circuit_breaker.py:365` | CRITICAL | HIGH | Race affects monitoring counter only, not state transitions | Unanimous (reliability + performance) |
| 2 | `buffer.py:357-360` | HIGH | MEDIUM | Original race window doesn't exist; retry queue properly handles failures | Unanimous (reliability + test) |
| 3 | `alembic/env.py:24` | HIGH | CRITICAL | `alembic upgrade head` causes runtime crashes for 2/3 database-backed subsystems | Unanimous (data + team-lead) |
| 4 | `self_improvement/` | CRITICAL | HIGH (→ M-01) | No formal public API, but has observability DB coupling; not fully isolated | Majority (api + structural) |
| 5 | Shim chains (3 findings) | 3× HIGH | 1× CRITICAL | Merged: incomplete migration with competing APIs, production code imports shims | Unanimous (structural + api) |
| 6 | Exception hierarchy (2 findings) | 2× HIGH | 1× HIGH | Merged: two aspects of same problem requiring simultaneous fix | Unanimous (structural + api) |
| 7 | Session lifecycle (3 findings) | CRITICAL+2×HIGH | 1× CRITICAL | Consolidated: shared root cause — no consistent session lifecycle pattern | Unanimous (reliability + data) |
| 8 | `standard_agent.py:790-793` | CRITICAL (perf only) | CRITICAL (perf + security) | Context displacement bypasses prompt injection defenses; new SEC-17 added | Unanimous (performance + security) |

### Cross-Cutting Insights

These insights emerged from discussion — things no single agent would have found alone:

1. **Prompt growth + injection bypass** (performance × security): The tail-truncation that discards the system prompt isn't just a token waste problem — it's an exploitable attack vector where tool output can displace safety instructions from the context window.

2. **Mock quality × untyped interfaces = double-blind-spot** (test × api): 90% of mocks lack `spec=` AND key interfaces use `Optional[Any]`. A renamed method passes both the mock (no spec check) and the type checker (Any accepts anything). Tests give false confidence.

3. **Session lifecycle is systemic, not localized** (reliability × data): Three agents found session problems in different modules. The root cause is architectural — no codebase-wide invariant for session lifecycle — not individual bugs.

4. **Alembic + create_all + raw SQL = three competing schema systems** (data × reliability): The schema management confusion means Alembic deployments are incomplete, create_all masks the gap, and deprecated raw SQL adds noise. The hidden mitigation (`create_all` on startup) makes the Alembic gap invisible until someone follows standard deployment practices.

5. **self_improvement coupling via observability DB** (structural × api × data): The monolith isn't truly isolated — observability's `create_all_tables()` hard-imports self_improvement models. This coupling must be broken before extraction is possible.

6. **Duplicate test directories + conftest conflicts** (test × all): `tests/compiler/conftest.py` defines fixtures unavailable to the 30 files in `tests/test_compiler/`. Moving tests between directories can cause cryptic "fixture not found" errors.

### Disagreements Resolved by Team Lead

| # | Topic | Resolution | Reasoning |
|---|-------|------------|-----------|
| 1 | T-02 (duplicate test dirs): CRITICAL vs HIGH | **HIGH** | Affects developer experience and test reliability, but does not cause production failures. Fix is mechanical (move files, merge conftest) with no code changes. Downgraded from test-analyst's CRITICAL to HIGH. |
| 2 | SEC-01 (SQL injection): keep HIGH or upgrade to CRITICAL given zero test coverage | **Keep HIGH** | The `limit` parameter is typed `Optional[int]` and comes from internal code, not direct user input. The attack surface is narrow. Zero test coverage is concerning but addressed separately by test findings. The fix is trivial (one-line parameterized query). |

---

## Hotspot Modules

Modules flagged by 3+ agents:

### `src/agents/standard_agent.py`
| Agent | Finding | Severity |
|-------|---------|----------|
| performance | Prompt grows unboundedly in tool loop (C-01) | CRITICAL |
| security | Context displacement bypasses injection defenses (C-01) | CRITICAL |
| reliability | Agent error message may contain sensitive info (M-25) | MEDIUM |
| reliability | Retry uses blocking time.sleep (M-26) | MEDIUM |
| performance | New ThreadPoolExecutor per tool-call batch (M-28) | MEDIUM |
| test | No test for tool-calling loop prompt management | HIGH (gap) |

**Root cause (consensus):** standard_agent.py handles too many concerns (LLM calling, tool execution, prompt management, retry logic, response parsing) in one 800+ line file.
**Fix strategy (consensus):** Extract prompt management into a dedicated PromptManager class with sliding-window truncation. Extract tool execution to reuse a shared thread pool.

### `src/observability/backends/sql_backend.py`
| Agent | Finding | Severity |
|-------|---------|----------|
| reliability | Standalone session leak (C-02) | CRITICAL |
| data | Mixed commit patterns (M-15) | MEDIUM |
| performance | SQLite StaticPool serializes access (M-29) | MEDIUM |

**Root cause (consensus):** SQL backend invented its own session management (`_session_stack`, `_standalone_session`) rather than using the standard `get_session()` context manager consistently.
**Fix strategy (consensus):** Refactor to per-operation `with get_session() as session:` pattern. Enable WAL mode for SQLite, recommend PostgreSQL for production.

### `src/self_improvement/` (entire module)
| Agent | Finding | Severity |
|-------|---------|----------|
| structural | 12,193-line monolith (M-01) | MEDIUM |
| data | JSON as TEXT, timestamps as TEXT (M-12, M-13) | MEDIUM |
| data | Long-lived session in ExperimentOrchestrator (C-02) | CRITICAL |
| data | Alembic doesn't cover M5 tables (C-03) | CRITICAL |
| api | Observability DB coupling (M-01 prerequisite) | MEDIUM |
| security | SQL injection in strategy_learning (H-07) | HIGH |
| test | Zero test coverage for strategy_learning | HIGH (gap) |

**Root cause (consensus):** self_improvement was built as a semi-autonomous subsystem with different coding standards than the main framework. Its data layer uses TEXT instead of proper column types, its session management diverges from the pattern, and its tables aren't in Alembic.
**Fix strategy (consensus):** 1) Fix SQL injection (trivial), 2) Add models to Alembic, 3) Decouple observability DB import, 4) Align data types with framework conventions, 5) Consider extraction to standalone package.

### `src/compiler/` (schemas + executors)
| Agent | Finding | Severity |
|-------|---------|----------|
| structural | Bidirectional dependency with agents (C-05) | CRITICAL |
| api | ExecutionContext naming collision (M-06) | MEDIUM |
| api | Dual LLM factory functions (C-04) | CRITICAL |
| data | Duplicate state definitions (M-20) | MEDIUM |
| reliability | retry_agent not implemented (H-05) | HIGH |
| reliability | Parallel retry no wall-clock timeout (H-06) | HIGH |

**Root cause (consensus):** Compiler module has mixed responsibilities (schemas, config loading, compilation, execution, state management) and unclear boundaries with agents module.
**Fix strategy (consensus):** Extract schemas to shared package, fix naming collisions, implement or remove retry_agent policy, add wall-clock timeout to parallel retry.

---

## Individual Agent Reports

### Structural Architecture — 16 findings
Module boundaries, coupling, dependency direction. 2 critical (bidirectional deps, self_improvement monolith→downgraded), 5 high, 6 medium, 2 low, 1 info.
Full report: `.claude-coord/reports/audit-findings-structural-architect.md`

### Security — 17 findings
Vulnerabilities, auth, injection, secrets handling. 0 critical (but contributed to C-01), 4 high, 6 medium, 3 low, 4 info.
Full report: `.claude-coord/reports/audit-findings-security-auditor.md`

### Reliability — 22 findings
Error handling, resilience, resource management, concurrency. 2 critical (1 downgraded, 1 consolidated), 7 high (1 downgraded), 8 medium, 3 low, 2 info.
Full report: `.claude-coord/reports/audit-findings-reliability-reviewer.md`

### API Contracts — 21 findings
Interface consistency, naming, schemas, error contracts. 0 critical, 4 high (2 merged with structural), 10 medium, 5 low, 2 info.
Full report: `.claude-coord/reports/audit-findings-api-reviewer.md`

### Data & State — 21 findings
Data models, state management, persistence, integrity. 0 critical (1 upgraded), 4 high (1 consolidated), 9 medium, 5 low, 3 info.
Full report: `.claude-coord/reports/audit-findings-data-analyst.md`

### Test Quality — 20 findings
Coverage gaps, test quality, mock quality, test architecture. 3 critical (1 downgraded by team-lead), 8 high, 6 medium, 3 low/info.
Full report: `.claude-coord/reports/audit-findings-test-analyst.md`

### Performance — 24 findings
Bottlenecks, scalability, resource usage. 2 critical (1 elevated with security), 6 high (2 merged with reliability), 8 medium, 3 low, 3 info.
Full report: `.claude-coord/reports/audit-findings-performance-reviewer.md`

---

## Recommended Actions (Prioritized by Team Consensus)

### Immediate (CRITICAL — fix before next release)

1. **C-01: Fix prompt truncation in tool-calling loop** — Implement sliding-window that pins system prompt; re-scan tool results for injection; add regression tests. *Blocks:* security + LLM output quality.

2. **C-02: Standardize database session lifecycle** — Refactor SQL backend to per-operation context managers; refactor M5 orchestrator to session factory; document the pattern. *Blocks:* database connection exhaustion under load.

3. **C-03: Complete Alembic migration coverage** — Add missing model imports to `alembic/env.py`; generate migration for 7 missing tables. *Blocks:* deployment correctness.

4. **C-04: Complete LLM provider migration** — Delete `src/llm/`, update imports from shims to canonical packages, consolidate factory functions. *Blocks:* developer confusion, missing VllmLLM in old factory.

5. **C-05: Break agents<->compiler circular dependency** — Extract `AgentConfig` and shared schemas to `src/schemas/`; inject factory into executors. *Blocks:* module independence, testability.

### Short-term (HIGH — fix within next 2 sprints)

6. **H-01: Fix circuit breaker metrics race** — Move `rejected_calls` increment inside lock. Trivial fix.
7. **H-02: Unify exception hierarchies** — Create `FrameworkException` base; split domain exceptions. Medium effort.
8. **H-03: Add LRU eviction to TokenBucketManager** — Prevent memory growth in long-running services.
9. **H-04: Replace approval polling with event-based wait** — Prevent thread pool starvation.
10. **H-05: Implement or remove retry_agent policy** — Eliminate silent misconfiguration.
11. **H-06: Add wall-clock timeout to parallel retry loop** — Prevent indefinite execution.
12. **H-07: Fix SQL injection in strategy_learning** — One-line parameterized query fix.
13. **H-08: Mask Redis URLs before logging** — Use existing `_mask_database_url()`.
14. **H-09: Pin dependency versions** — Add upper bounds to security-critical packages.
15. **H-10: Create CLI test suite** — Click CliRunner tests for YAML loading, validation, `--output` path.
16. **H-11: Consolidate duplicate test directories** — Merge into canonical `tests/test_*/`.
17. **H-12: Add tests for untested agent components** — response_parser, agent_observer, cost_estimator.
18. **H-13: Add `spec=` to high-risk mocks** — Prioritize ConfigLoader, AgentFactory, ToolRegistry, ExecutionTracker.
19. **H-14: Replace vacuous `assert True` with real assertions** — 23 instances across 13 files.

### Backlog (MEDIUM + LOW)

20. Decouple observability DB from self_improvement imports (M-01 prerequisite)
21. Define safety/security domain boundary (M-02)
22. Split ExecutionTracker into sub-trackers (M-03)
23. Unify experimentation systems (M-04) — estimated ~4 weeks
24. Replace hasattr chains with Protocols (M-05)
25. Fix ExecutionContext naming collision (M-06)
26. Type InfrastructureContext fields with Protocols (M-07)
27. Add DB CHECK constraints for status fields (M-11)
28. Align M5 data types with framework conventions (M-12, M-13)
29. Enable SQLite WAL mode for development (M-29)
30. Use OrderedDict for policy cache LRU (M-30)
