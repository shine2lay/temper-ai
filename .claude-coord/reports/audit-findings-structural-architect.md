# Structural Architecture Audit Findings

**Auditor:** Structural Architect
**Date:** 2026-02-07
**Scope:** Module boundaries, dependency direction, coupling, package organization, extensibility
**Context:** Fresh structural audit of current codebase state (commit b97ddac)

## Summary

- **Total findings:** 19
- **Critical:** 0, **High:** 5, **Medium:** 8, **Low:** 4, **Info:** 2

The codebase has a generally sound top-level structure with clear module separation. However, several significant structural issues persist: `src/observability/` doubles as the shared database layer creating hidden coupling, deprecated shim modules are still used by production code, and two god modules (StandardAgent at 1222 LOC, ExecutionTracker at 1075 LOC) concentrate too many concerns.

## Findings Table

| # | Severity | Category | File/Location | Finding | Recommendation |
|---|----------|----------|---------------|---------|----------------|
| 1 | HIGH | god-module | `src/agents/standard_agent.py` (1222 LOC) | StandardAgent is the largest source file. It handles prompt rendering, LLM calling, tool execution loop, caching, cost estimation, policy validation, and native tool definitions all in one class. Multiple concerns are interleaved in the `execute` method. | Split into focused modules: extract tool loop into `ToolLoop`, extract native tool def builder into a utility, extract safety check wrapper. StandardAgent should orchestrate, not implement every detail. |
| 2 | HIGH | god-module | `src/utils/exceptions.py` (721 LOC) | Contains 20+ exception classes, ErrorCode enum (38 codes), error sanitization utility, execution context re-export, and base exception with complex initialization. Simultaneously serves as exception hierarchy, error utility, and context re-export hub. | Split into: `src/utils/error_codes.py` (ErrorCode enum), `src/utils/error_sanitization.py` (sanitize_error_message). Keep `exceptions.py` for the exception hierarchy only. Remove ExecutionContext re-export (import from `src.core.context` directly). |
| 3 | HIGH | dependency-direction | `src/observability/rollback_logger.py:23-24` | Observability imports from `src.safety.rollback` (RollbackResult, RollbackSnapshot). This creates a bidirectional dependency: safety depends on observability (indirectly via database), and observability depends on safety (rollback types). Observability should be a pure sink, not coupled to domain modules. | Define rollback event types in observability or a shared types module. Have safety push events to observability via a protocol/callback, rather than observability pulling from safety. |
| 4 | HIGH | coupling | `src/self_improvement/` (12+ files import from `src.observability`) | self_improvement deeply couples to `src.observability.database.get_session`, `src.observability.models.AgentExecution`, and `src.observability.datetime_utils`. This makes self_improvement unportable and means observability is secretly a shared infrastructure layer. | Extract database infrastructure (`get_session`, `DatabaseManager`, `init_database`) into a dedicated `src/database/` or `src/infrastructure/database/` package. Let observability and self_improvement both depend on it. |
| 5 | HIGH | coupling | `src/experimentation/metrics_collector.py:21-22`, `service.py:33` | Experimentation module imports `get_session` and models directly from `src.observability`. Same infrastructure-as-domain-module coupling as finding #4. Experimentation cannot be used without the full observability stack. | Same fix as #4: extract shared DB infrastructure into dedicated package. Experimentation should only depend on database infrastructure, not the full observability module. |
| 6 | MEDIUM | boundaries | `src/security/llm_security.py` (905 LOC, single file) | Entire `src/security/` package is a single 905-line file with no `__init__.py`. Its only consumer is `src/core/test_support.py:114` (for `reset_security_components`). The module name overlaps with `src/safety/` causing confusion about security vs. safety boundaries. `src/safety/interfaces.py` defines Protocols that `llm_security.py` classes should implement but don't reference. | Either: (a) merge into `src/safety/` as `src/safety/llm_security.py` since it implements security policies, or (b) add proper `__init__.py`, split the god file into prompt injection detector, output sanitizer, and rate limiter submodules, and have them implement the protocols from `src/safety/interfaces.py`. |
| 7 | MEDIUM | circular-deps | `src/llm/circuit_breaker.py` (35 LOC shim) | `src/llm/` is a top-level package containing ONLY a deprecated shim for circuit_breaker. Two production files still import from it: `src/agents/llm/base.py:35` and `src/compiler/executors/sequential.py:14`. This orphaned package adds confusion to the module tree. | Migrate the two remaining consumers to import from `src.core.circuit_breaker` directly and delete `src/llm/` entirely. |
| 8 | MEDIUM | coupling | `src/agents/standard_agent.py:31-37`, `src/agents/llm_failover.py:13,46`, `src/self_improvement/ollama_client.py:16` | Three production files still import from the deprecated `src/agents/llm_providers` shim instead of from `src/agents/llm`. This triggers deprecation warnings at runtime and adds unnecessary indirection. | Update imports in all three files to use `src.agents.llm` directly. The shim can remain for third-party backward compatibility but core code should not use it. |
| 9 | MEDIUM | organization | `src/safety/__init__.py` (244 LOC, 117 lazy imports) | The safety package __init__ re-exports 62+ symbols via lazy loading including 8 deprecated aliases (SafetyViolationModel, ValidationResultModel, ViolationSeverityEnum, RateLimitPolicyV2, RateLimiterPolicy, RateLimitPolicy). This creates a massive, hard-to-understand API surface. | Reduce the public API surface. Group re-exports by concern. Set expiration dates on deprecated aliases and create a plan to remove them. |
| 10 | MEDIUM | boundaries | `src/safety/circuit_breaker.py` (369 LOC) | This file is split-personality: it's partly a deprecated shim (lines 29-72 re-exporting from `src.core.circuit_breaker`) AND partly original domain code (`SafetyGate`, `CircuitBreakerManager` classes, ~290 LOC). The shim and domain code live in the same file. | Separate the shim from the domain code: move `SafetyGate` and `CircuitBreakerManager` to `src/safety/safety_gate.py`, leaving the shim as a thin re-export module. |
| 11 | MEDIUM | dependency-direction | `src/core/test_support.py:127,133` | Core module imports from `src.agents.agent_factory` and `src.agents.pricing`. Core should be leaf-level infrastructure; it should never import from domain layers like agents. | Move `test_support.py` out of core into `src/testing/` or `tests/support/`. It provides test fixtures, not core framework infrastructure. |
| 12 | MEDIUM | god-module | `src/observability/tracker.py` (1075 LOC) | ExecutionTracker has 7 dependencies and manages 5 tracking levels (workflow, stage, agent, LLM, tool) plus delegation to DecisionTracker, MetricAggregator, CollaborationEventTracker, and DataSanitizer. At 1075 LOC it's the second-largest file. | Split by tracking level: extract `WorkflowTracker`, `AgentTracker`, etc. ExecutionTracker becomes a thin facade. The common create-record/context-manager/update-duration pattern should be a shared template method. |
| 13 | MEDIUM | coupling | `src/compiler/executors/parallel.py:10`, `sequential.py:19`, `__init__.py:7` | Compiler executors import directly from `src.agents.agent_factory` and `src.agents.base_agent`. This couples the compiler/execution layer to the agent layer. The compiler should depend on abstractions, not concrete agent implementations. | Define a `CreateAgentCallable` protocol in `src/compiler/domain_state.py` (which already defines protocols) and inject agent creation as a dependency. |
| 14 | LOW | organization | `src/compiler/schemas.py` (617 LOC) | This file re-exports 12 schemas from `src.schemas.agent_config` (lines 18-30) AND defines its own workflow/stage/trigger schemas (lines 31-617). Having both re-exports and original definitions in one file is confusing. | Split: keep workflow/stage schemas in `src/compiler/schemas.py`, move the re-export block to a separate `src/compiler/_compat.py` or document more clearly which schemas are local vs re-exported. |
| 15 | LOW | extensibility | `src/core/protocols.py` (62 LOC) | Core protocols module defines only a single `Registry` protocol. There are several other protocol-worthy abstractions scattered across the codebase (`TrackerProtocol`, `ConfigLoaderProtocol`, `ToolRegistryProtocol` in `compiler/domain_state.py`). | Gradually consolidate cross-cutting protocol definitions into `src/core/protocols.py` for discoverability. |
| 16 | LOW | coupling | `src/agents/base_agent.py:14`, `src/utils/exceptions.py:16`, `src/observability/__init__.py:10` | `ExecutionContext` is re-exported from 3 places beyond its canonical home (`src.core.context`). Most consumers already import from `src.core.context` directly (9 direct imports found). | Document the canonical import path (`src.core.context`), deprecate re-exports from `utils/exceptions.py` and `agents/base_agent.py`. |
| 17 | LOW | organization | `src/self_improvement/` (13 modules, 5500+ LOC, 8 subpackages) | self_improvement is a semi-autonomous subsystem with its own agents, strategies, loop, detection, deployment, and storage. It's effectively a sub-framework tightly coupled to observability for DB access. No other module imports from it except `src/cli/main.py`. | Make self_improvement a more autonomous subsystem with explicit dependency injection for database access rather than importing observability internals directly. Consider documenting it as a separate bounded context. |
| 18 | INFO | extensibility | `src/agents/llm/factory.py`, `src/safety/factory.py` | Both LLM and safety use factory patterns with hardcoded type maps (provider name -> class). Adding new LLM providers or safety policies requires modifying these factory files. | Consider a registry-based approach where providers/policies self-register via entry points or decorators, similar to how `ToolRegistry` uses auto-discovery. |
| 19 | INFO | organization | `src/observability/` (14 modules, 4400+ LOC) | observability serves triple duty: (1) execution tracking, (2) database infrastructure (DatabaseManager, get_session, migrations), (3) visualization (console, visualize_trace). These are distinct concerns. | The database infrastructure role (finding #4/#5) should be extracted. The visualization could be a separate `src/visualization/` package. |

## Dependency Flow Analysis

### Ideal Flow (top to bottom)
```
  cli -> compiler -> agents -> core
          |            |
        safety      schemas
          |
    observability -> core
          |
      database (infrastructure)
```

### Actual Violations Found
```
  1. observability -> safety (rollback_logger imports safety.rollback) [Finding #3]
  2. core -> agents (test_support imports agent_factory, pricing) [Finding #11]
  3. self_improvement -> observability (deep coupling to DB internals) [Finding #4]
  4. experimentation -> observability (same DB coupling) [Finding #5]
  5. agents -> deprecated shim (llm_providers) instead of agents.llm [Finding #8]
  6. agents.llm.base -> src.llm (orphaned top-level shim) [Finding #7]
  7. compiler.executors -> agents (direct import, no abstraction) [Finding #13]
```

## Top 3 Structural Risks

1. **Observability as hidden infrastructure layer** (#4, #5, #19): `src/observability/` doubles as the shared database layer. Multiple domain modules (self_improvement, experimentation) depend on it for DB access. This means observability changes can break unrelated subsystems, and observability cannot be made optional.

2. **Deprecated shim debt** (#7, #8, #10): Production code still routes through 3 deprecated shim modules (`src/llm/circuit_breaker`, `agents/llm_providers`, `safety/circuit_breaker`). Each adds runtime overhead (deprecation warnings, lazy imports) and makes the dependency graph harder to trace.

3. **God modules** (#1, #2, #12): StandardAgent (1222 LOC), utils/exceptions.py (721 LOC), and ExecutionTracker (1075 LOC) concentrate too many concerns. These are the riskiest files to modify -- any change requires understanding the entire file.

## Module Size Overview

| Module | Lines (approx) | Files | Largest File |
|--------|----------------|-------|-------------|
| self_improvement | ~5,500 | 30+ | experiment_orchestrator.py (917) |
| safety | ~5,200 | 18 | rollback.py (906) |
| observability | ~4,400 | 14 | tracker.py (1,075) |
| compiler | ~5,800 | 16 | config_loader.py (799) |
| agents | ~3,500 | 11 | standard_agent.py (1,222) |
| tools | ~3,700 | 8 | registry.py (838) |
| strategies | ~2,800 | 8 | dialogue.py (855) |
| auth | ~2,200 | 9 | oauth/service.py (668) |
| experimentation | ~1,600 | 8 | service.py (610) |
| utils | ~1,600 | 7 | exceptions.py (721) |
| security | ~905 | 1 | llm_security.py (905) |
| core | ~870 | 4 | circuit_breaker.py (757) |
| cache | ~790 | 3 | llm_cache.py (779) |
| llm | ~35 | 1 | circuit_breaker.py (35) -- orphaned shim |
