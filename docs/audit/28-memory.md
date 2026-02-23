# Audit 28: Memory Module (`temper_ai/memory/`)

**Auditor:** Claude Opus 4.6
**Date:** 2026-02-22
**Scope:** All 16 files in `temper_ai/memory/` (807 LOC) + 18 test files (206 tests) + CLI commands
**Verdict:** GOOD -- clean adapter-pattern design with solid test coverage, but a latent API-mismatch bug in cross-pollination and duplicate constant definitions

**Score: 83/100 (B+)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 90 | All functions under 50 lines; one param-count violation; one fan-out violation |
| Security | 72 | No PII sanitization on stored content; tsquery injection handled; no content validation |
| Error Handling | 88 | Graceful degradation throughout; broad `except Exception` in 3 places (justified by noqa) |
| Modularity | 85 | Clean protocol-based adapter pattern; duplicate constants across modules |
| Feature Completeness | 75 | `publish_knowledge` has API mismatch bug; `AgentPerformanceTracker` memory persistence stub |
| Test Quality | 88 | 206 tests all passing; no PG adapter tests; comprehensive M9 coverage |
| Arch Alignment | 78 | Memory & Learning vision partially served; no embedding-based search in any built-in adapter |

---

## 1. Code Quality

### 1.1 Strengths

- **Function length compliance.** Every function across all 16 files is under 50 lines. The longest is `Mem0Adapter.search` at 36 lines (`mem0_adapter.py:91-136`). All helper functions are well-extracted.
- **Constants properly centralized.** `/home/shinelay/meta-autonomous-framework/temper_ai/memory/constants.py` defines all magic numbers: `LATENCY_BUDGET_MS = 500`, `MAX_MEMORY_CONTEXT_CHARS = 4000`, `DEFAULT_RETRIEVAL_LIMIT = 5`, `MEMORY_QUERY_MAX_CHARS = 500`, `SECONDS_PER_DAY = 86400`.
- **Frozen dataclasses.** `MemoryScope` is `frozen=True` (immutable), preventing accidental mutation. Tests verify this (`test_schemas.py:40-44`).
- **Thread safety.** Both `InMemoryAdapter` and `MemoryProviderRegistry` use `threading.RLock`. The adapter locks around all mutations and reads that copy lists under lock (`in_memory.py:36-37`, `50-51`).
- **Lazy imports.** The registry lazily imports `PGAdapter`, `Mem0Adapter`, and `KnowledgeGraphMemoryAdapter` only when requested, avoiding heavy dependency loading at import time (`registry.py:64-78`).

### 1.2 Issues

**ISSUE-1: `retrieve_with_shared()` exceeds 7-parameter limit (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/service.py:244`:
```python
def retrieve_with_shared(
    self,
    scope: MemoryScope,
    shared_scope: MemoryScope,
    query: str,
    retrieval_k: int = DEFAULT_RETRIEVAL_LIMIT,
    relevance_threshold: float = 0.0,
    max_chars: int = MAX_MEMORY_CONTEXT_CHARS,
    decay_factor: float = 1.0,
) -> str:
```
This has 8 parameters (including `self`). The retrieval parameters (`retrieval_k`, `relevance_threshold`, `max_chars`, `decay_factor`) could be bundled into a `RetrievalOptions` dataclass.

**ISSUE-2: `pg_adapter.py` fan-out is 9 (limit: 8) (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/adapters/pg_adapter.py` imports from 9 distinct top-level modules: `sqlalchemy`, `sqlmodel`, `json`, `logging`, `uuid`, `collections`, `datetime`, `temper_ai.storage`, `temper_ai.memory`. The `temper_ai.storage` import (for `create_app_engine`) could be moved to a lazy import inside `_build_engine()`, which it already is -- but AST counting still flags it because `from temper_ai.storage.database.engine import ...` appears at module level within the method. This is marginal but worth noting.

**ISSUE-3: Duplicate constant definitions across modules (P2)**
Three constants are defined in both `constants.py` AND their respective usage modules:

| Constant | `constants.py` line | Duplicate location |
|----------|---------------------|--------------------|
| `PUBLISHED_KNOWLEDGE_NAMESPACE` | 25 | `cross_pollination.py:7` |
| `PERFORMANCE_NAMESPACE` | 26 | `agent_performance.py:8` |
| `MEMORY_TYPE_PUBLISHED` | 27 | `cross_pollination.py:9` |

The modules define their own copies instead of importing from `constants.py`. This means changing the value in one place won't propagate. The constants in `constants.py` are exported via `__init__.py` but the local copies are what the code actually uses. Neither `cross_pollination.py` nor `agent_performance.py` imports from `constants.py`.

**Recommendation:** Delete the local copies in `cross_pollination.py` and `agent_performance.py`; import from `constants.py` instead.

---

## 2. Security

### 2.1 Strengths

- **tsquery injection prevention.** `PGAdapter._sanitize_tsquery()` (`pg_adapter.py:272-286`) properly escapes single quotes by doubling them and wraps each token in quotes before joining with `&`. This prevents PostgreSQL tsquery injection.
- **ILIKE pattern escaping.** `_escape_ilike()` (`pg_adapter.py:389-396`) escapes `%`, `_`, and backslash characters in user queries before using them in `ILIKE` patterns. Uses bind parameters (`:pattern`) throughout.
- **Parameterized SQL throughout.** All SQL queries in `pg_adapter.py` use SQLAlchemy `text()` with named bind parameters (`:scope_key`, `:id`, `:query`, etc.). No string interpolation of user input into SQL.
- **Content truncation.** `cross_pollination.py:36-37` truncates content exceeding `MAX_CONTENT_LENGTH = 10000` before storage.
- **`yaml.safe_load`** used in CLI seed command (`memory_commands.py:195`).

### 2.2 Issues

**ISSUE-4: No sanitization of stored memory content (P1 -- Security)**
Memory content is stored as-is from agent output, user input (via CLI `add` command), or cross-pollination. No sanitization or redaction is applied before persisting. This means:
- PII (emails, phone numbers, SSNs, API keys) in agent outputs can be persisted to memory stores (PostgreSQL, Mem0/ChromaDB).
- Memory content is later injected into prompts via `format_memory_context()`, creating a potential prompt injection vector if an attacker can pollute the memory store.
- The framework has `temper_ai/observability/sanitization.py` and `temper_ai/safety/redaction_utils.py` for LLM output sanitization, but these are not applied to memory writes.

**Affected paths:**
- `service.py:149` (`store_episodic`)
- `service.py:165` (`store_procedural`)
- `service.py:181` (`store_cross_session`)
- `cross_pollination.py:46` (`publish_knowledge`)
- `memory_commands.py:127` (`add_memory` CLI)

**Recommendation:** Add an optional `sanitize_content()` hook (or integrate with the existing `redaction_utils.py`) that runs before `adapter.add()`. At minimum, apply the existing secret detection patterns from `temper_ai/shared/utils/secret_patterns.py` to prevent API keys/tokens from being persisted in memory.

**ISSUE-5: Memory content injected into prompts without escaping (P2)**
`format_memory_context()` in `formatter.py:36` injects raw memory content into markdown that is later concatenated into LLM prompts. If an adversary can write to the memory store (e.g., via shared namespace cross-pollination), they can inject prompt instructions.

```python
line = f"- [{entry.relevance_score:.2f}] {entry.content}"  # formatter.py:36
```

This is mitigated somewhat by the relevance threshold filtering, but content is never escaped or sandboxed.

**ISSUE-6: `_sanitize_tsquery` does not strip special tsquery operators (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/adapters/pg_adapter.py:272-286`:
The sanitizer wraps tokens in single quotes but does not strip tsquery operators like `!`, `|`, `<->`, or `*`. While these are quoted (and thus treated as literal text by `to_tsquery`), if a future refactoring changes the quoting approach, these operators could become active. The current implementation is safe but fragile.

---

## 3. Error Handling

### 3.1 Strengths

- **Graceful degradation pattern consistently applied.** The `MemoryService.retrieve_context()` method is wrapped by callers (e.g., `standard_agent.py:_inject_memory_context`) in try/except that returns the original prompt on failure. Memory failures never crash agent execution.
- **Latency budget warnings.** Both `MemoryService.retrieve_context()` (`service.py:118-123`) and `Mem0Adapter.search()` (`mem0_adapter.py:108-113`) log warnings when search latency exceeds `LATENCY_BUDGET_MS = 500ms`, providing observability without failing.
- **Cross-pollination resilience.** `publish_knowledge()` catches `Exception` and returns `None` on failure (`cross_pollination.py:48-50`). `retrieve_subscribed_knowledge()` catches per-agent search failures and continues to the next agent (`cross_pollination.py:88-91`).

### 3.2 Issues

**ISSUE-7: `InMemoryAdapter.search` mutates shared `MemoryEntry` objects (P2)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/adapters/in_memory.py:61`:
```python
entry.relevance_score = min(score, 1.0)
```
This mutates the `relevance_score` of the `MemoryEntry` stored in `self._store`. Since `MemoryEntry` is not frozen (unlike `MemoryScope`), subsequent searches will see the previously assigned score, not the original `0.0`. If the same entry matches different queries, its score reflects only the last search.

The `get_all()` method at line 75 copies the list (`list(self._store.get(...))`), but the entries themselves are the same objects. This means callers of `get_all()` also see mutated scores.

**Recommendation:** Create a shallow copy of each entry before mutating: `import copy; e = copy.copy(entry); e.relevance_score = ...; results.append(e)`. Alternatively, make `MemoryEntry` a frozen dataclass and use `dataclasses.replace()`.

**ISSUE-8: `_enforce_max_episodes` deletes oldest entries regardless of type (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/service.py:47-58`:
The function calls `adapter.get_all(scope)` without a `memory_type` filter, then deletes the oldest entries across all types. If a scope has 3 episodic and 3 procedural entries and `max_episodes=3`, it will delete the 3 oldest regardless of type, potentially deleting all procedural entries while keeping only episodic ones (or vice versa). This may not match user intent.

---

## 4. Modularity

### 4.1 Strengths

- **Protocol-based adapter interface.** `MemoryStoreProtocol` (`protocols.py:12-50`) is a `runtime_checkable` protocol defining exactly 5 methods. All 4 adapters implement this interface. Tests verify protocol compliance (`test_protocols.py`).
- **Singleton registry with lazy loading.** `MemoryProviderRegistry` uses the singleton pattern with `RLock` for thread safety and lazy sentinel for heavy adapters (`registry.py:16-78`). It provides `reset_for_testing()` for test isolation.
- **Clean separation of concerns.** The module has clear layering:
  - Schemas (`_schemas.py`, `_m9_schemas.py`) -- data structures
  - Protocol (`protocols.py`) -- adapter contract
  - Registry (`registry.py`) -- provider discovery
  - Service (`service.py`) -- orchestration
  - Formatter (`formatter.py`) -- output formatting
  - Extractors (`extractors.py`) -- LLM-based pattern extraction
  - Adapters (`adapters/`) -- storage backends

### 4.2 Issues

**ISSUE-9: `cross_pollination.py` uses `Any` for `memory_service` parameter (P2)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/cross_pollination.py:25`:
```python
def publish_knowledge(
    agent_name: str,
    content: str,
    memory_service: Any,
    ...
```
All three functions in `cross_pollination.py` accept `memory_service: Any`. This hides the API mismatch bug (ISSUE-10) from type checkers. Using `MemoryService` as the type annotation would catch the bug at development time.

**ISSUE-10: `KnowledgeGraphMemoryAdapter` ignores `scope` parameter (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/adapters/knowledge_graph_adapter.py:54-79`:
The `search()` and `get_all()` methods accept a `scope` parameter but completely ignore it. All searches go against the entire knowledge graph regardless of tenant/workflow/agent scope. This violates the scoping contract of `MemoryStoreProtocol` and could leak data across tenants in a multi-tenant deployment.

---

## 5. Feature Completeness

### 5.1 Latent Bug

**ISSUE-11: `publish_knowledge` calls `memory_service.store()` which does not exist (P0 -- BUG)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/cross_pollination.py:46`:
```python
entry_id = memory_service.store(scope, entry)
```
`MemoryService` does not have a `store()` method. It has `store_episodic()`, `store_procedural()`, and `store_cross_session()`. This call will always raise `AttributeError`, which is caught by the `except Exception` on line 48 and returns `None`.

This means **cross-pollination publishing has never actually worked** -- it silently fails on every call. The callers in `standard_agent.py:442` and `_m9_context_helpers.py:112` also swallow the error via their own try/except blocks.

The test `test_cross_pollination.py:37-43` passes because it mocks `memory_service` as a `MagicMock()`, which auto-creates `.store()`. A real `MemoryService` instance would fail.

**Fix:** Change line 46 to use the adapter's `add()` method via the service, e.g.:
```python
entry_id = memory_service._adapter.add(
    scope, content, memory_type, metadata or {}
)
```
Or better, add a generic `store()` method to `MemoryService`:
```python
def store(self, scope: MemoryScope, content: str, memory_type: str, ...) -> str:
    return self._adapter.add(scope, content, memory_type, metadata)
```

### 5.2 Incomplete Implementations

**ISSUE-12: `AgentPerformanceTracker._memory_service` is never used (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/agent_performance.py:45-46`:
```python
def __init__(self, memory_service: Any = None) -> None:
    self._memory_service = memory_service
    self._records: dict[str, list[ExecutionMetrics]] = {}
```
The `_memory_service` parameter is accepted and stored but never referenced anywhere in the class. Performance data is only stored in the in-memory `_records` dict. This means performance tracking is lost across process restarts even when a persistent memory service is provided.

**ISSUE-13: No `async` variants of memory operations (P3)**
All memory operations (`add`, `search`, `get_all`) are synchronous. The `Mem0Adapter.search()` and `PGAdapter.search()` perform network I/O that could block the event loop when called from async agent execution paths. The protocol and all adapters are synchronous-only.

### 5.3 Missing Features vs Vision

**ISSUE-14: No embedding-based semantic search in built-in adapters (P2)**
The `InMemoryAdapter` uses substring matching for search (`in_memory.py:58`). The `PGAdapter` uses ILIKE or PostgreSQL full-text search. Neither provides true semantic/embedding-based similarity search. Only `Mem0Adapter` provides vector search, but it requires an external dependency. For the "Memory & Learning" vision pillar (intelligent memory retrieval), an embedding-based adapter using the framework's own LLM providers would be valuable.

---

## 6. Test Quality

### 6.1 Strengths

- **206 tests, all passing** (3.96s with `-n auto`). Zero failures.
- **Comprehensive adapter coverage.** `test_in_memory_adapter.py` (28 tests) covers CRUD, search semantics, scope isolation, and thread safety. `test_knowledge_graph_adapter.py` (20 tests) covers all protocol methods with mocked KG store. `test_mem0_adapter.py` (12 tests) covers all operations with mocked mem0.
- **M9 feature coverage.** `test_m9_schemas.py` (12 tests) validates `CrossPollinationConfig` bounds, `MemoryScope.agent_id` behavior, and backward compatibility. `test_cross_pollination.py` (15 tests) covers publish, retrieve, and formatting. `test_agent_performance.py` (13 tests) covers recording, aggregation, and formatting.
- **Edge cases covered.** Empty inputs, boundary thresholds, truncation, concurrent access, scope isolation, case-insensitive search, deduplication.
- **Integration tests.** `test_integration.py` (14 tests) tests agent-level memory injection, graceful degradation on failure, and procedural extraction with mocked LLM.
- **CLI tests.** `test_cli_commands.py` (7 tests) covers list, add, search, clear, and seed commands.

### 6.2 Gaps

**ISSUE-15: No tests for `PGAdapter` (P1)**
There are zero test files or test cases for `/home/shinelay/meta-autonomous-framework/temper_ai/memory/adapters/pg_adapter.py` (397 lines, the largest file in the module). No tests cover:
- FTS search path (`_fts_search`, `_build_fts_sql`, `_rows_to_entries_with_rank`)
- ILIKE search path (`_ilike_search`, `_score_and_limit`)
- Schema initialization (`_init_schema`, `_ensure_fts_column`)
- `_sanitize_tsquery` edge cases (empty tokens, special characters)
- `_escape_ilike` edge cases
- `_row_to_memory_entry` with string vs datetime `created_at`
- Delete operations with actual database

This is the most complex adapter and the only one deployed in production (PostgreSQL). It should have at least a SQLite-based test suite covering the ILIKE path.

**ISSUE-16: Cross-pollination tests use `MagicMock` masking ISSUE-11 (P1)**
`/home/shinelay/meta-autonomous-framework/tests/test_memory/test_cross_pollination.py:32-35`:
```python
def _make_service(self, entry_id: str = "test-id") -> MagicMock:
    svc = MagicMock()
    svc.store.return_value = entry_id
    return svc
```
Because `MagicMock` auto-creates any attribute accessed on it, calling `svc.store(...)` succeeds even though `MemoryService` has no `store()` method. This masks the API-mismatch bug. Tests should use `MagicMock(spec=MemoryService)` to catch this.

**ISSUE-17: No test for `Mem0Adapter.delete_all` under partial failure (P3)**
`/home/shinelay/meta-autonomous-framework/temper_ai/memory/adapters/mem0_adapter.py:171-178`:
`delete_all` iterates over entries and calls `delete` one-by-one. If `delete` fails mid-way (e.g., after 1 of 3), the returned count will be 1, but the remaining entries are silently skipped. No test verifies this partial-failure behavior.

**ISSUE-18: No test for `_enforce_max_episodes` cross-type deletion behavior (P3)**
As noted in ISSUE-8, `_enforce_max_episodes` deletes across types. No test verifies whether this is intended behavior.

---

## 7. Architectural Alignment

### 7.1 Vision Pillar: Memory & Learning

The memory module provides the foundation for the "Memory & Learning" vision pillar:
- Scoped storage (tenant/workflow/agent)
- Multiple memory types (episodic, procedural, cross-session)
- Time decay for relevance
- Cross-agent knowledge sharing (M9 cross-pollination)
- Pluggable backends via protocol

**Gaps:**
- Cross-pollination is broken (ISSUE-11)
- No semantic search capability without external Mem0 dependency
- Performance tracking doesn't persist (ISSUE-12)
- No memory consolidation/summarization (compacting old memories into summaries)

### 7.2 Vision Pillar: Self-Improvement

The `extractors.py` module enables procedural pattern extraction from agent outputs, feeding the self-improvement loop. This works correctly when enabled. However:
- Extraction runs synchronously in the agent's `_on_after_run` path
- No quality gate on extracted patterns (any LLM output matching `\d+\.` is stored)
- No deduplication of extracted patterns across runs

### 7.3 Multi-Tenant Safety

The scoping model (`MemoryScope.scope_key` = `tenant:workflow:agent`) provides tenant isolation at the application level. However:
- `KnowledgeGraphMemoryAdapter` ignores scope entirely (ISSUE-10)
- No row-level security or tenant filtering in `PGAdapter` -- relies on `scope_key` matching only
- Shared namespaces (`build_shared_scope`) strip `agent_name`, allowing cross-agent access within a workflow, which is intentional but should be documented as a security boundary

---

## Summary of Issues

| # | Issue | Severity | File:Line |
|---|-------|----------|-----------|
| 1 | `retrieve_with_shared` has 8 params (limit: 7) | P3 | `service.py:244` |
| 2 | `pg_adapter.py` fan-out is 9 (limit: 8) | P3 | `pg_adapter.py:1` |
| 3 | Duplicate constants in `cross_pollination.py` and `agent_performance.py` | P2 | `cross_pollination.py:7-9`, `agent_performance.py:8` |
| 4 | No sanitization of stored memory content (PII, secrets) | P1 | `service.py:149,165,181` |
| 5 | Memory content injected into prompts without escaping | P2 | `formatter.py:36` |
| 6 | `_sanitize_tsquery` does not strip special operators | P3 | `pg_adapter.py:272` |
| 7 | `InMemoryAdapter.search` mutates shared `MemoryEntry` objects | P2 | `in_memory.py:61` |
| 8 | `_enforce_max_episodes` deletes across all memory types | P3 | `service.py:51` |
| 9 | `cross_pollination.py` uses `Any` for `memory_service` | P2 | `cross_pollination.py:25` |
| 10 | `KnowledgeGraphMemoryAdapter` ignores `scope` parameter | P3 | `knowledge_graph_adapter.py:66` |
| 11 | **`publish_knowledge` calls nonexistent `memory_service.store()` -- always fails** | **P0** | `cross_pollination.py:46` |
| 12 | `AgentPerformanceTracker._memory_service` is never used | P3 | `agent_performance.py:46` |
| 13 | No async variants of memory operations | P3 | `protocols.py:12` |
| 14 | No embedding-based semantic search in built-in adapters | P2 | Module-wide |
| 15 | **No tests for PGAdapter (397 lines, production adapter)** | **P1** | `pg_adapter.py` |
| 16 | Cross-pollination tests mask API mismatch with unspec'd `MagicMock` | P1 | `test_cross_pollination.py:32` |
| 17 | No test for `Mem0Adapter.delete_all` partial failure | P3 | `mem0_adapter.py:171` |
| 18 | No test for `_enforce_max_episodes` cross-type behavior | P3 | `service.py:47` |

**Critical fixes needed (P0-P1):**
1. Fix `publish_knowledge` to call an actual method on `MemoryService` (ISSUE-11)
2. Add PG adapter tests with SQLite backend (ISSUE-15)
3. Add content sanitization before memory storage (ISSUE-4)
4. Use `MagicMock(spec=MemoryService)` in cross-pollination tests (ISSUE-16)

---

## File-Level Summary

| File | LOC | Tests | Quality | Key concern |
|------|-----|-------|---------|-------------|
| `service.py` | 285 | 22 | A | 8-param method; no sanitization hook |
| `_schemas.py` | 55 | 17 | A+ | Clean frozen dataclass |
| `_m9_schemas.py` | 21 | 12 | A+ | Proper Pydantic validation |
| `constants.py` | 28 | -- | A- | Duplicate defs in other modules |
| `protocols.py` | 51 | 5 | A+ | Clean runtime-checkable protocol |
| `registry.py` | 90 | 9 | A | Solid singleton with lazy loading |
| `formatter.py` | 51 | 10 | A | Truncation handled correctly |
| `extractors.py` | 77 | 13 | A | Pattern extraction well-bounded |
| `cross_pollination.py` | 111 | 15 | C | **P0 bug**: calls nonexistent `.store()` |
| `agent_performance.py` | 91 | 13 | B | `_memory_service` stub never used |
| `adapters/in_memory.py` | 95 | 28 | B+ | Entry mutation on search (ISSUE-7) |
| `adapters/pg_adapter.py` | 397 | **0** | B- | **P1**: no tests; proper SQL safety |
| `adapters/mem0_adapter.py` | 179 | 12 | B+ | Good mocked coverage |
| `adapters/kg_adapter.py` | 120 | 20 | B | Ignores scope; read-only design OK |
| `memory_commands.py` | 220 | 7 | A- | Clean Click commands |
