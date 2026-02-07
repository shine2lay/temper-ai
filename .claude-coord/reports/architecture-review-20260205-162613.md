# Codebase Audit Report

**Generated:** 2026-02-05 16:26
**Method:** 4 specialized agents with free codebase exploration
**Scope:** src/ directory — ~200 Python files, ~65,500 lines
**Agents:** Architecture (solution-architect), Security (security-engineer), Product/UX (technical-product-manager), QA (qa-engineer)

---

## Executive Summary

**Total Findings: 91**

| Severity | Architecture | Security | Product/UX | QA | Total |
|----------|-------------|----------|------------|-----|-------|
| CRITICAL | 1 | 0 | 3 | 4 | **8** |
| HIGH | 4 | 3 | 6 | 8 | **21** |
| MEDIUM | 9 | 5 | 8 | 7 | **29** |
| LOW | 5 | 4 | 5 | 2 | **16** |
| INFO | 3 | 8 | 2 | 4 | **17** |

### Top Risks (Cross-Agent)

1. **Broken First-Run Experience** (Product) — `yourusername` placeholder in clone URL, poetry vs pip confusion, three conflicting "first run" paths, and config docs that don't match actual schemas mean new users will fail before running their first workflow.

2. **200+ Tests Silently Not Running** (QA) — 11 broken test files from stale imports post-refactoring, plus hypothesis not installed. Regression coverage has degraded without anyone noticing.

3. **Supply Chain Risk from Unpinned Dependencies** (Security) — All 15 runtime dependencies use floor-only pins (`>=`) with no upper bounds or lock file. Any malicious or breaking upstream release propagates automatically.

4. **ExecutionContext Name Collision** (Architecture) — Two completely different types both named `ExecutionContext` in `src/core/context.py` and `src/compiler/domain_state.py`. Importing from the wrong path gives silently wrong behavior.

5. **CLI Module Has Zero Tests** (QA) — The primary user-facing entry point (`src/cli/`) has 3 source files and 0 test files.

### Key Strengths (Cross-Agent)

1. **Mature Security Posture** — SSRF protection, Jinja2 sandboxing, safe YAML loading, no pickle usage, OAuth 2.0 with PKCE, AST-based calculator, filtered subprocess env. 17 dedicated security test files.

2. **Strong Interface Design** — 24 ABC/Protocol definitions create clear contracts. Extension points via safety policy registry, strategy registry, and tool registry enable plugin-style extensibility.

3. **Excellent Compiler/Observability Coverage** — 30 test files for compiler, 27 for observability. Root conftest with `reset_all_globals()` provides excellent test isolation.

4. **Rich CLI Output** — `--show-details` with Rich library tables, panels, streaming logs, and Gantt charts is polished and professional.

5. **Comprehensive Documentation Architecture** — 75+ docs, 11 ADRs, 5 milestone reports, INDEX.md hub (though some content is stale).

---

## Architecture Assessment

**Agent:** solution-architect | **Findings:** 22 (1 Critical, 4 High, 9 Medium, 5 Low, 3 Info)

### Findings

| # | Severity | Category | File:Line | Finding | Recommendation |
|---|----------|----------|-----------|---------|----------------|
| A1 | CRITICAL | Naming Collision | `src/core/context.py:19` vs `src/compiler/domain_state.py:370` | Two distinct classes both named `ExecutionContext`: core's tracking context vs compiler's infrastructure context. Both re-exported under same name. 19+ files import one or the other. | Rename compiler's alias. Audit all 19+ importers. |
| A2 | HIGH | Duplicate Systems | `src/experimentation/` vs `src/self_improvement/` | Two parallel experimentation systems with separate ORM models against same DB. No integration point. | Unify under `src/experimentation/` (ISSUE-14 in backlog). |
| A3 | HIGH | Module Size | `src/self_improvement/` | God module: 44 files, 8 sub-packages, deep internal coupling. `improvement_detector.py` imports from 6 sub-packages. | Decompose into smaller top-level modules. |
| A4 | HIGH | Re-export Debt | 4 shim files | Four backward-compat re-export shims still in codebase, including `httpx` imports just to preserve mock paths. | Set deprecation timeline, update internal imports, remove shims. |
| A5 | HIGH | Singleton Pattern | `strategies/registry.py`, `pricing.py`, `engine_registry.py` | Three singletons, two lack thread-safe init. Makes testing harder. | Migrate to DI (ISSUE-22). Add locking at minimum. |
| A6 | MEDIUM | Upward Dependency | `src/compiler/executors/base.py:186-418` | Base executor reaches up into agent/strategy layers. | Extract synthesis logic into injected coordinator. |
| A7 | MEDIUM | Cross-module Coupling | `src/safety/factory.py:37-38` | Bidirectional dependency between safety and tools. | Move `create_safety_stack()` to a top-level wiring module. |
| A8 | MEDIUM | Excessive hasattr | 27 files, 72 occurrences | Duck-typing via `hasattr` instead of Protocols. | Define Protocols for duck-typed interfaces (ISSUE-13). |
| A9 | MEDIUM | LangGraph Coupling | `src/compiler/langgraph_compiler.py:23` | Hard import despite engine abstraction effort. | Complete engine abstraction; isolate LangGraph imports. |
| A10 | MEDIUM | Deep Internal Imports | `self_improvement/detection/improvement_detector.py` | 8 sibling sub-package imports in one file. | Introduce facade/mediator pattern. |
| A11 | MEDIUM | Ambiguous Typing | `domain_state.py:349-352`, `langgraph_state.py:80-83` | Infrastructure fields typed as `Optional[Any]`. | Use `TYPE_CHECKING` imports with proper annotations. |
| A12 | MEDIUM | Config Loading | `src/safety/factory.py:65-66` | Relative path via `__file__` assumes directory structure. | Use central config resolution mechanism. |
| A13 | MEDIUM | State Duplication | `langgraph_state.py` vs `domain_state.py` | LangGraph state manually copies fields instead of composing. | Use composition or programmatic generation. |
| A14 | MEDIUM | Lazy Init Safety | `src/safety/__init__.py:114-123` | `__getattr__`-based lazy loading for 39 entries breaks IDE completion. | Add `__dir__()` for IDE support. |
| A15 | LOW | Dead Module | `src/llm/` | Single-file module that's just a re-export shim. | Remove `src/llm/` entirely. |
| A16 | LOW | Re-export Chain | `src/agents/base_agent.py:14` | ExecutionContext re-exported through 4 different paths. | Standardize to `src/core.context`. |
| A17 | LOW | Security Isolation | `src/security/llm_security.py` | Single 700+ line file, overlaps with `src/safety/` rate limiting. | Merge into safety or expand with sub-modules. |
| A18 | LOW | Test in Production | `src/core/test_support.py` | Test utilities ship in production code. | Move to `tests/`. |
| A19 | LOW | Empty Init | `src/auth/__init__.py` | No public API defined for auth module. | Add explicit exports. |
| A20 | INFO | Extension Points | `safety/factory.py`, `strategies/registry.py` | Well-designed plugin architectures. | Document in developer guide. |
| A21 | INFO | ABC Coverage | 24 definitions across src/ | Good interface coverage at major boundaries. | Continue pattern. |
| A22 | INFO | Lazy Imports | `compiler/executors/base.py` | Good use of lazy imports for circular dependency avoidance. | Consider if circular deps indicate structural issue. |

### Module Dependency Map

```
CLI Layer
  src/cli/ ──→ compiler, observability, self_improvement

Compiler/Orchestration Layer
  src/compiler/ ──→ safety/factory, tools/, langgraph (external)
  src/compiler/executors/ ──→ agents/, strategies/ (upward!)

Agent Layer
  src/agents/ ──→ agents/llm/, tools/registry, safety/action_policy_engine
  src/agents/llm/ ──→ core/ (context, circuit_breaker)

Safety Layer
  src/safety/ ──→ safety/interfaces, core/circuit_breaker
  src/safety/factory ←→ src/tools/ (bidirectional!)

Observability Layer
  src/observability/ ──→ core/context, utils/

Infrastructure (Foundation)
  src/core/ ──→ (no src imports - clean foundation)
  src/utils/ ──→ core/context (re-export only)

Self-Improvement (Isolated)
  src/self_improvement/ ──→ observability, safety, agents/llm_providers
```

---

## Security Assessment

**Agent:** security-engineer | **Findings:** 20 (0 Critical, 3 High, 5 Medium, 4 Low, 8 Info)

### Findings

| # | Severity | Category | File:Line | Finding | Recommendation |
|---|----------|----------|-----------|---------|----------------|
| S1 | HIGH | Supply Chain | `pyproject.toml:17-49` | All 15 runtime deps use floor-only pins (`>=`). No lock file. | Pin upper bounds or add lock file. Run `pip-audit` in CI. |
| S2 | HIGH | Command Injection | `src/tools/bash.py:215-343` | `shell_mode=True` with regex-based command splitting can be bypassed. | Consider removing shell_mode or adding chroot/namespace isolation. |
| S3 | HIGH | Auth Default | `src/auth/session.py:53-64` | `InMemorySessionStore` is default; production silently uses ephemeral storage. | Fail loudly if `ENVIRONMENT=production`. |
| S4 | MEDIUM | Deprecated TOCTOU | `src/security/llm_security.py:722-793` | Deprecated `check_rate_limit()`/`record_call()` still public, bypasses rate limits under concurrency. | Remove or make private. |
| S5 | MEDIUM | Broad Exceptions | 37 occurrences across 22 files | May silently swallow security-relevant errors. | Audit and narrow to specific exceptions. |
| S6 | MEDIUM | Token Store | `src/auth/oauth/token_store.py:217-219` | In-memory token dict lost on restart. No persistence. | Add `PersistentTokenStore` backed by SQLModel. |
| S7 | MEDIUM | Raw SQL | `src/observability/migrations.py:297` | Raw SQL execution with acknowledged bypassable validation. | Complete migration to Alembic. |
| S8 | MEDIUM | Info Leakage | `src/tools/bash.py:306-310` | Error message leaks full command allowlist to LLM agent. | Return generic error; log details server-side. |
| S9 | LOW | Placeholder Key | `src/agents/llm_failover.py:50` | `api_key="..."` in docstring normalizes inline secrets. | Use `${env:OPENAI_API_KEY}` in examples. |
| S10 | LOW | Session Logging | `src/auth/session.py:116-118` | First 16 chars of session ID logged (too much entropy). | Log only 8 chars or use one-way hash. |
| S11 | LOW | Allowlist ReDoS | `src/observability/sanitization.py:143-148` | User-configurable regex patterns could cause CPU exhaustion. | Add timeout wrapper or validate patterns. |
| S12 | LOW | Missing CSRF | `src/auth/routes.py:401-459` | Logout endpoint lacks CSRF token verification. | Accept logout only via POST with CSRF token. |
| S13-S20 | INFO | Strengths | Various | No pickle, safe YAML, Jinja2 sandbox, SSRF protection, OAuth+PKCE, calculator safety, 17 security test files, filtered subprocess env. | Continue these excellent practices. |

---

## Product/UX Assessment

**Agent:** technical-product-manager | **Findings:** 24 (3 Critical, 6 High, 8 Medium, 5 Low, 2 Info)

### Findings

| # | Severity | Category | File:Line | Finding | Recommendation |
|---|----------|----------|-----------|---------|----------------|
| P1 | CRITICAL | Documentation | `README.md:167` | `yourusername` placeholder in git clone URL, pyproject.toml, QUICK_START.md. | Replace with actual GitHub org/user. |
| P2 | CRITICAL | CLI UX | Multiple | Two incompatible CLIs: `maf` vs `run_workflow.py` with different arg interfaces. | Consolidate to `maf` as primary. |
| P3 | CRITICAL | Config UX | `docs/CONFIGURATION.md:54-71` | Docs show `type`, `agent_ref`, `input_mapping` fields that don't exist in actual Pydantic schema. | Align docs with `WorkflowStageReference` schema. |
| P4 | HIGH | Documentation | `examples/README.md:9` | `poetry install` but project uses setuptools. | Change to `pip install -e ".[dev]"`. |
| P5 | HIGH | Config UX | `configs/README.md:325` | Docs suggest `--agent` flag that doesn't exist in `maf` CLI. | Remove or replace with actual commands. |
| P6 | HIGH | Documentation | `docs/QUICK_START.md:106-110` | Quick Start shows `--provider`/`--model` flags that don't exist. | Update to actual working commands. |
| P7 | HIGH | User Journey | `docs/QUICK_START.md:456-460` | References `data_analysis` workflow that doesn't exist. | Remove phantom reference or create workflow. |
| P8 | HIGH | Feature Coherence | `configs/triggers/` | Trigger system fully designed in schemas but completely unimplemented. | Mark as "Planned" or remove from docs. |
| P9 | HIGH | Config UX | `src/compiler/schemas.py:155-169` | `error_handling` required but not in "Minimal Config" docs. | Add default or update docs. |
| P10 | MEDIUM | Documentation | `docs/INDEX.md:103,109-110` | Three docs marked TODO, never created. Status says "M4 In Progress" but README says "COMPLETE". | Update status, create or remove stubs. |
| P11 | MEDIUM | CLI UX | `src/cli/main.py:493-496` | `maf m5` commands fail opaquely without coordination daemon. | Add clear error messages about dependency. |
| P12 | MEDIUM | Documentation | `docs/CONFIGURATION.md:124-128` | Unclear if `${env:...}` syntax actually works at runtime. | Document env var resolution mechanism. |
| P13 | MEDIUM | Config UX | `configs/agents/researcher.yaml:29` | Default model `qwen3-next:latest` is uncommon. | Use commonly available model or document dependency. |
| P14 | MEDIUM | Feature Coherence | `configs/tools/` | Only `calculator.yaml` despite docs describing many tool configs. | Create missing configs or clarify programmatic registration. |
| P15 | MEDIUM | Feature Coherence | `configs/prompts/` | Only one file; docs describe rich Jinja2 template system. | Provide example templates or document inline pattern. |
| P16 | MEDIUM | Examples | `examples/` | 40+ scripts with no categorization, unclear names. | Organize into subdirectories with index. |
| P17 | MEDIUM | User Journey | `README.md:196-200` | First demo is `milestone1_demo.py`, not a real workflow. | Point to `maf run` with quick_decision_demo. |
| P18 | MEDIUM | CLI UX | `src/cli/main.py:69` | Version hardcoded to `"0.1.0"` instead of reading from pyproject.toml. | Use `importlib.metadata`. |
| P19-P24 | LOW-INFO | Various | Various | Stale model IDs, excessive timeouts, duplicate starting points, shallow validation, orphaned OAuth, stale doc links. | Various targeted fixes. |

### User Journey Analysis

| Step | Experience | Blocker? |
|------|-----------|----------|
| 1. Clone | `yourusername` placeholder | YES |
| 2. Install | `poetry install` vs `pip install` confusion | Partial |
| 3. First Run | Three different paths, none clearly canonical | Confusing |
| 4. Custom Workflow | Docs show wrong schema fields → validation errors | YES |
| 5. Advanced | M5 requires coordination daemon (not obvious) | Partial |

---

## QA Assessment

**Agent:** qa-engineer | **Findings:** 25 (4 Critical, 8 High, 7 Medium, 2 Low, 4 Info)

### Findings

| # | Severity | Category | File:Line | Finding | Recommendation |
|---|----------|----------|-----------|---------|----------------|
| Q1 | CRITICAL | Broken Tests | `tests/test_safety/test_circuit_breaker.py:6` | ImportError: `CircuitBreakerMetrics` removed in refactoring. Tests silently uncollected. | Fix imports or delete if covered elsewhere. |
| Q2 | CRITICAL | Broken Tests | `tests/self_improvement/strategies/test_strategy.py:15` | ImportError: `AgentConfig` no longer exported. 11 total collection errors = ~200+ tests not running. | Fix all 11 import errors. |
| Q3 | CRITICAL | Duplicate Dirs | `tests/safety/` vs `tests/test_safety/` | 5 pairs of duplicate test directories. Same-named files testing different things. | Consolidate to single `test_<module>/` per module. |
| Q4 | CRITICAL | No Tests | `src/cli/` | 3 source files, 0 test files. Primary user entry point untested. | Add CLI unit tests. |
| Q5 | HIGH | Flaky Tests | 100+ locations | 100+ `time.sleep()` calls. Worst: `test_executor.py` (14), `test_console_streaming.py` (12). | Replace with event-based sync or mock clocks. |
| Q6 | HIGH | Zero Assertions | `tests/test_coordination/test_daemon_recovery.py` | 8 tests with 0 asserts. Exercise code but verify nothing. | Add assertions or mark as smoke tests. |
| Q7 | HIGH | Zero Assertions | `tests/test_coordination/test_minimal.py`, `test_crash_minimal.py` | 2 more tests with 0 assertions. | Add post-condition checks. |
| Q8 | HIGH | Low Assertions | `tests/test_observability/test_migrations.py` | 49 tests, 7 asserts (0.1 ratio). | Add DB state assertions. |
| Q9 | HIGH | Coverage Gap | `src/core/` | 4 source files, 1 test file. Circuit breaker untested at core level. | Add core-level tests. |
| Q10 | HIGH | Coverage Gap | `src/utils/` | 8 source files, 3 test files. 5 files untested. | Add tests for error_handling, exceptions, logging, config_migrations. |
| Q11 | HIGH | Broken Tests | `tests/property/` | hypothesis not installed, property tests fail collection. | Install hypothesis or add importorskip. |
| Q12 | HIGH | Stale Test | `test_security_bypasses_OLD.py` | _OLD file still collected and run. | Delete or archive. |
| Q13-Q25 | MED-INFO | Various | Various | Fixture duplication, `assert True`, skipped tests, xfail debt, TODOs in tests, root-level sprawl, mock overuse, missing categories, marker inconsistency, good conftest, good fixtures, good security tests. | Various targeted fixes. |

### Coverage Gap Analysis

| Module | Source Files | Test Files | Assessment |
|--------|-------------|------------|------------|
| `src/agents/` | 17 | 15 | GOOD |
| `src/auth/` | 9 | 8 | GOOD (split across 2 dirs) |
| `src/cache/` | 2 | 4 | GOOD |
| **`src/cli/`** | **3** | **0** | **CRITICAL GAP** |
| `src/compiler/` | 23 | 30 | EXCELLENT |
| **`src/core/`** | **4** | **1** | **HIGH GAP** |
| `src/experimentation/` | 7 | 15 | EXCELLENT |
| `src/observability/` | 25 | 27 | EXCELLENT |
| `src/safety/` | 24 | 38 | EXCELLENT (but split dirs) |
| `src/security/` | 1 | 18 | EXCELLENT |
| `src/self_improvement/` | 37 | 26 | ADEQUATE (some broken) |
| `src/strategies/` | 7 | 12 | GOOD |
| `src/tools/` | 7 | 11 | GOOD (split dirs) |
| **`src/utils/`** | **8** | **3** | **HIGH GAP** |

---

## Recommended Actions

### Immediate (This Sprint)

| # | Action | Source | Effort |
|---|--------|--------|--------|
| 1 | Fix 11 broken test imports (restore ~200+ tests) | QA Q1-Q2 | S |
| 2 | Replace `yourusername` placeholder across all files | Product P1 | S |
| 3 | Align CONFIGURATION.md with actual Pydantic schemas | Product P3 | M |
| 4 | Consolidate 5 duplicate test directory pairs | QA Q3 | M |
| 5 | Rename compiler's `ExecutionContext` alias | Arch A1 | M |
| 6 | Pin dependency upper bounds or add lock file | Security S1 | S |
| 7 | Consolidate CLI to `maf` as canonical entry point | Product P2 | M |

### Short-Term (Next 2-4 Weeks)

| # | Action | Source | Effort |
|---|--------|--------|--------|
| 8 | Add CLI module tests | QA Q4 | M |
| 9 | Fix all stale Quick Start / README commands | Product P4-P7 | S |
| 10 | Replace `time.sleep` in tests with event-based sync | QA Q5 | L |
| 11 | Remove re-export shims, update internal imports | Arch A4 | M |
| 12 | Add assertions to zero-assertion tests | QA Q6-Q8 | M |
| 13 | Move `create_safety_stack()` to top-level wiring module | Arch A7 | M |
| 14 | Mark trigger system as "Planned" in docs | Product P8 | S |
| 15 | Add `utils/` and `core/` tests | QA Q9-Q10 | M |

### Backlog

| # | Action | Source | Effort |
|---|--------|--------|--------|
| 16 | Unify experimentation systems (ISSUE-14) | Arch A2 | XL |
| 17 | Decompose `self_improvement` god module | Arch A3 | XL |
| 18 | Define Protocols for 72 `hasattr` sites (ISSUE-13) | Arch A8 | L |
| 19 | Migrate singletons to DI (ISSUE-22) | Arch A5 | L |
| 20 | Complete LangGraph engine abstraction | Arch A9 | M |
| 21 | Organize 40+ examples into subdirectories | Product P16 | M |
| 22 | Remove `shell_mode=True` or add namespace isolation | Security S2 | L |
| 23 | Add persistent token store | Security S6 | M |
| 24 | Complete Alembic migration, remove raw SQL path | Security S7 | M |
