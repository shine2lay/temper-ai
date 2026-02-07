# Performance & Scalability Audit Findings

**Reviewer:** Performance & Scalability Reviewer
**Date:** 2026-02-07
**Scope:** Full codebase performance analysis (commit b97ddac)
**Focus Areas:** Algorithmic efficiency, I/O patterns, memory patterns, async/sync impedance, scalability bottlenecks

---

## Summary

- **18 findings total:** 1 CRITICAL, 2 HIGH, 7 MEDIUM, 5 LOW, 3 INFO
- **Top concerns:** Dead async path (aexecute never called by any executor), blocking I/O in sync paths, thread pool sizing, unbounded data structures under sustained failures
- **Phase 2 update:** P-01 elevated from HIGH to CRITICAL after cross-review revealed that `aexecute()` is dead code -- no executor in the codebase calls it (all use sync `execute()`)

### Improvements Since Prior Audit (Confirmed Fixed)

The prior audit (2026-02-06) identified 19 findings. Many were remediated in commits b97ddac through 5d42893:

- **P-01 (was CRITICAL):** `time.sleep()` in agent retry — FIXED: `aexecute()` now exists with proper `asyncio.sleep()` at `standard_agent.py:505`. Sync path still uses `time.sleep()` but this is expected for the sync API.
- **P-02 (was HIGH):** Fixed pool size — PARTIALLY FIXED: Pool size now configurable via `AGENT_TOOL_WORKERS` env var at `standard_agent.py:65`. Default still 4 (see new P-03).
- **P-03 (was HIGH):** `asyncio.run()` in `close()` — FIXED: `close()` at `base.py:362-392` no longer calls `asyncio.run()`. Releases async client reference with a warning to use `aclose()`.
- **P-04 (was HIGH):** Unbounded circuit breakers — FIXED: LRU eviction via `OrderedDict` with `_MAX_CIRCUIT_BREAKERS=100` at `base.py:101-105`.
- **P-05 (was HIGH):** Unbounded DLQ — FIXED: `max_dlq_size=10000` parameter at `buffer.py:142,161` with overflow dropping oldest entries at lines 582-585.
- **P-06 (was HIGH):** Inline flush lock contention — FIXED: Deferred flush pattern at `buffer.py:254-260`. Lock is released before flush callback executes.
- **P-07 (was MEDIUM):** Agent recreation — PARTIALLY FIXED: `_agent_cache` added to both `SequentialStageExecutor` (line 61) and `ParallelStageExecutor` (line 49). Agent instances are now reused per-workflow.
- **P-08 (was MEDIUM):** httpx client sharing — EXISTS BUT NOT DEFAULT: `_get_shared_http_client()` exists at `base.py:204-225` but `_get_client()` still creates per-instance clients. See new P-05.
- **P-13 (was MEDIUM):** SentenceTransformer singleton — FIXED: Class-level singleton with `warm_up()` at `dialogue.py:158-189`.
- **P-15 (was LOW):** Native tool defs caching — FIXED: `_cached_native_tool_defs` with hash-based invalidation at `standard_agent.py:132-134,1042-1090`.

---

## Current Findings

| # | Severity | Category | File:Line | Finding | Recommendation |
|---|----------|----------|-----------|---------|----------------|
| P-01 | **CRITICAL** | async-impedance | `src/agents/standard_agent.py:486-487` | **Async path is dead code AND delegates to sync LLM via `run_in_executor`.** (Elevated from HIGH during Phase 2 cross-review.) Two compounding issues: (1) **No executor calls `aexecute()`** -- `sequential.py:699`, `parallel.py:513`, and `base.py:489` all call `agent.execute()` (sync). The entire async path (`aexecute`, `_aexecute_iteration`) is dead code in production. (2) Even if called, `_aexecute_iteration` uses `loop.run_in_executor(None, lambda: self.llm.complete(prompt, ...))` to run the sync `complete()` in the default executor, which uses `time.sleep()` during retries (blocking an executor thread for up to 14s). `self.llm.acomplete()` exists with proper `asyncio.sleep()` and `httpx.AsyncClient` but is NEVER called. The async path was likely copy-pasted from the sync path without wiring the async LLM method -- a direct consequence of the god module complexity flagged by structural-architect. Zero concurrency tests exist to catch this (confirmed by test-analyst). | (1) Wire at least one executor to call `aexecute()` (parallel executor is the natural candidate). (2) Replace `self.llm.complete()` with `await self.llm.acomplete()` in `_aexecute_iteration`. (3) Add concurrency tests that verify the async path actually uses async I/O. |
| P-02 | HIGH | blocking-io | `src/agents/standard_agent.py:689` | **`time.sleep()` in sync retry loop blocks the calling thread.** The sync path `_execute_iteration` uses `time.sleep(backoff_delay)` at line 689 with exponential backoff (delay * 2^attempt). With 3 retries, a single agent blocks its thread for up to 14 seconds. In sequential stages, this is acceptable. But when `execute()` is called from within `ParallelStageExecutor._create_agent_node` (line 513), agents run in parallel via LangGraph's thread pool. Blocking sleeps in that context serialize parallel agents. | Use `threading.Event.wait(timeout=backoff_delay)` as done in `sequential.py:458`. This makes the sleep interruptible by shutdown signals while still blocking synchronously. |
| P-03 | HIGH | scalability | `src/agents/standard_agent.py:65-68` | **Module-level tool executor pool defaults to 4 workers.** `_TOOL_EXECUTOR_POOL` is configurable via `AGENT_TOOL_WORKERS` env var but defaults to 4. In a parallel stage with 5 agents each issuing 2+ tool calls concurrently, only 4 can execute simultaneously. The remaining queue behind the bottleneck. For CPU-bound tools (e.g., data parsing), this is appropriate. For I/O-bound tools (web scraping, file ops), 4 is too restrictive. | Increase default to `min(32, os.cpu_count() * 2 + 4)` or at least 8. Document the env var tuning knob in config documentation. Consider auto-sizing based on the number of agents in the workflow. |
| P-04 | MEDIUM | memory-leak | `src/agents/standard_agent.py:1170` | **`_conversation_turns` list retains all historical turns.** While `_inject_tool_results` applies a sliding window on the assembled prompt (lines 1185-1193), the raw `_conversation_turns` list is never pruned. For an agent with `max_tool_calls_per_execution=50`, all 50 turns are retained even though only the most recent N fit in the prompt window. Each turn contains the full LLM response + tool results (potentially 10-50KB). | After assembling the prompt, prune `_conversation_turns` to keep only the `included_turns`. Add: `self._conversation_turns = self._conversation_turns[-len(included_turns):]` after line 1193. |
| P-05 | MEDIUM | connection-pooling | `src/agents/llm/base.py:277-304` | **Per-instance httpx.Client despite shared pool infrastructure.** `_get_client()` creates a per-instance `httpx.Client` with `max_connections=100`. The class method `_get_shared_http_client()` (lines 204-225) exists with proper LRU eviction but is not used by the default `_get_client()`. For 10 agents targeting the same Ollama endpoint: 10 clients x 100 max connections = 1000 potential FDs to the same backend. | Have `_get_client()` call `_get_shared_http_client()` by default, with an opt-out for cases that need separate connection pools. This mirrors the circuit breaker sharing pattern that already works well. |
| P-06 | MEDIUM | n-plus-one | `src/observability/backends/sql_backend.py:938-949` | **Agent metric batch update issues N individual SELECT+UPDATE queries.** `_flush_buffer` correctly batches LLM and tool call INSERTs (1 query each), but agent metrics updates loop over `agent_metrics.items()`, issuing a SELECT+UPDATE per agent_id. For 20 agents in a flush batch: 40 queries instead of 1-2. | Use a single bulk UPDATE statement. SQLAlchemy's `session.execute(update(AgentExecution).where(...).values(...))` with CASE expressions can update all agents in one query. |
| P-07 | MEDIUM | backpressure | `src/observability/buffer.py:165-167` | **Buffer lists (`llm_calls`, `tool_calls`) have no size limit.** If the flush callback persistently fails (DB down), the retry mechanism moves items to the DLQ (which is now bounded at 10K), but NEW items keep accumulating in `llm_calls` and `tool_calls` without limit. The DLQ bounds only apply to failed-and-exhausted items, not to the primary buffer. | Add `max_buffer_size` parameter. When exceeded, either drop oldest unflushed items (with a metric counter) or reject new buffer entries and let callers handle the back-pressure signal. |
| P-08 | MEDIUM | missing-cache | `src/compiler/executors/sequential.py:631-633` | **Agent config re-loaded and re-parsed for cached agents.** `_run_agent()` calls `config_loader.load_agent(agent_name)` and `AgentConfig(**agent_config_dict)` even when the agent instance is already in `_agent_cache` (line 628-630). This re-parses YAML and re-validates Pydantic on every execution just for tracking metadata. | Cache `(agent, agent_config)` tuples in `_agent_cache`. When the agent is cached, also return the cached config for tracking instead of re-loading from disk. |
| P-09 | MEDIUM | scalability | `src/tools/executor.py:106-117` | **ToolExecutor creates two thread pools on every instantiation.** Each `ToolExecutor` creates a 4-worker tool pool and a 4-worker approval pool (8 threads total). The approval pool is only needed when `approval_workflow` is configured, but it is always created. With `weakref.finalize`, cleanup is deferred to GC, meaning threads may linger across stage boundaries. | Lazy-initialize `_approval_executor` only when `approval_workflow is not None`. This saves 4 threads per ToolExecutor when approvals are not configured (the common case). |
| P-10 | MEDIUM | blocking-io | `src/observability/tracker.py:632-634` | **Sanitization regex applied on every LLM call.** `track_llm_call` calls `sanitizer.sanitize_text()` on both the full prompt and full response. Sanitization runs 10+ regex patterns against the entire text. For 5KB prompts, this adds measurable latency per call. In a 50-iteration agent loop with 5KB prompts: 500KB of regex scanning per agent execution. | Consider: (1) sanitize only when storing to DB (not on every track call), (2) use a bloom filter or prefix check to short-circuit when no patterns are likely present, (3) cache sanitization results for repeated prompt prefixes (templates are largely constant). |
| P-11 | LOW | scalability | `src/security/llm_security.py:860` | **Shared lock for all security singleton initialization.** `_security_lock` is a single `threading.Lock` shared across `get_prompt_detector()`, `get_output_sanitizer()`, and `get_rate_limiter()`. Initializing one component blocks initialization of all others. | Use per-component locks. Each component already has its own `global` variable and double-check pattern -- they just share the same lock unnecessarily. |
| P-12 | LOW | memory-leak | `src/strategies/dialogue.py:158-161` | **SentenceTransformer model (~90MB) held as class-level singleton.** Once loaded, `_embedding_model` is never released. This is by design for the warm_up pattern, but there is no way to release the model when dialogue strategies are no longer in use. | Add `release_model()` classmethod for memory-constrained environments. Document the ~90MB memory cost in config documentation. |
| P-13 | LOW | blocking-io | `src/observability/console.py:431-439` | **`time.sleep()` in visualizer polling loop.** `StreamingVisualizer._update_loop` uses `time.sleep(self.poll_interval)` in a daemon thread. Not interruptible by stop signals during the sleep interval. | Use `self._stop_event.wait(timeout=self.poll_interval)` as done in `buffer.py:611`. This makes the thread respond promptly to stop requests. |
| P-14 | LOW | scalability | `src/safety/action_policy_engine.py:505-540` | **SHA-256 hash computed on every validation call for cache lookup.** `_get_cache_key` serializes the policy+action+context to canonical JSON and computes SHA-256. This happens on every `validate_action_sync()` call, even for cache hits. For high-throughput tool execution (100+ calls/min), the cost is small per-call but adds up. | Profile before optimizing. If cache key computation is measurable, consider a faster hash (xxhash, blake2b) or a two-level cache with cheap string-based lookup. |
| P-15 | LOW | missing-cache | `src/compiler/executors/sequential.py:616-619` | **Agent config loaded from YAML on every agent execution.** `config_loader.load_agent(agent_name)` parses YAML from disk on each call. In a 5-stage, 3-agent workflow: 15 YAML file reads. Configs are immutable during workflow execution. | Add a dict cache to `config_loader.load_agent()` keyed by agent name. Simple `@lru_cache` or dict cache eliminates redundant YAML parsing + Pydantic validation. |
| P-16 | INFO | scalability | `src/agents/agent_factory.py:64` | **AgentFactory.create() acquires a lock for dict lookup.** `cls._lock` serializes all `create()` calls even though `_agent_types` is only modified at startup via `register_type()`. Under the GIL, dict reads are atomic. | Remove lock from `create()`. Only `register_type()` needs protection. |
| P-17 | INFO | connection-pooling | `src/agents/llm/base.py:110-111` | **`_http_clients` is a plain `dict` with insertion-order eviction.** The eviction at line 218 uses `next(iter(...))` which relies on CPython 3.7+ insertion order. Unlike the `_circuit_breakers` which use `OrderedDict` for explicit LRU, the HTTP client pool evicts by insertion order, not by access recency. | Use `OrderedDict` with `move_to_end()` on access for true LRU semantics, matching the circuit breaker pattern. |
| P-18 | INFO | scalability | `src/agents/standard_agent.py:1057` | **MD5 used for tool definition cache invalidation.** `_get_native_tool_definitions` uses `hashlib.md5(tool_names_key.encode()).hexdigest()` for cache invalidation. While non-cryptographic use of MD5 is fine, the input is small enough that a simple string comparison would work equally well. | No change needed. The caching is effective and MD5 overhead on small inputs is negligible. |

---

## Architecture-Level Observations

### Positive Patterns (Well Done)

1. **Async execution path (`aexecute`)**: The infrastructure exists (`aexecute`, `acomplete`, `_get_async_client_safe`) with proper `asyncio.sleep()` and `httpx.AsyncClient`. However, no executor calls `aexecute()` and `_aexecute_iteration` still calls sync `complete()` -- so this is currently dead code (see P-01 CRITICAL).
2. **Observability buffer deferred flush**: `buffer_llm_call` now defers the flush outside the lock (lines 254-260), eliminating the lock-during-IO bottleneck.
3. **LRU-bounded shared pools**: Circuit breakers (max 100), HTTP clients (max 50), token buckets (max 10000) all have bounded sizes with LRU eviction.
4. **Per-workflow agent caching**: Both sequential and parallel executors cache agent instances, avoiding redundant LLM client creation.
5. **Native tool definition caching**: Hash-based cache invalidation avoids recomputing tool schemas on every iteration.
6. **Conversation sliding window**: Prevents unbounded prompt growth during multi-turn execution.
7. **Connection pooling infrastructure**: HTTP/2 support, configurable connection limits, lazy initialization all present.

### Scale-Dependent Risk Summary

| Component | Current Scale (1-5 agents) | 10x Scale (50 agents) | Risk |
|-----------|---------------------------|----------------------|------|
| Dead async path + sync `complete()` via executor | Async path never called; sync blocks 14s per retry | 50 agents x 14s = executor exhaustion; no async alternative available | **CRITICAL** |
| `time.sleep()` in parallel agent retries | ~14s blocking per agent | 50x contention on LangGraph pool | **HIGH** |
| Tool pool 4 workers | Occasional queueing | 50 tool calls on 4 threads = 12x oversubscription | **HIGH** |
| Buffer lists no max size | Negligible | Unbounded during DB outage | **MEDIUM** |
| Agent metrics N+1 queries | 5 queries | 100 queries per flush | **MEDIUM** |
| Per-instance httpx clients | 500 FDs | 5000 FDs (OS limit risk) | **MEDIUM** |
| Config re-loading for cached agents | ~15ms per agent | ~750ms total overhead | **LOW** |
| Sanitization regex per LLM call | ~2ms per call | ~100ms per 50-call agent | **LOW** |

### Top 3 Impact Areas for Remediation

1. **Async path is dead code and broken (P-01, CRITICAL):** No executor calls `aexecute()` -- the entire async path is dead code. Even if wired, it delegates to sync `complete()` via `run_in_executor`, negating async benefits. `acomplete()` exists with proper async I/O but is never called. Fix requires: (a) wire parallel executor to call `aexecute()`, (b) replace sync `complete()` with `await acomplete()` inside `_aexecute_iteration`. Cross-review confirmed this is compounded by zero concurrency tests (test-analyst) and god module complexity (structural-architect).

2. **Tool executor pool sizing (P-03):** The default 4-worker tool pool is a bottleneck for any workflow with more than 2 concurrent agents using tools. Combined with the blocking LLM retries (P-02), the effective parallelism of the framework is severely constrained by thread pool contention.

3. **HTTP client sharing (P-05):** The infrastructure for shared HTTP clients exists but is not wired as the default. Enabling it would reduce file descriptor usage by 10x in multi-agent scenarios and improve connection reuse to LLM endpoints.

---

*End of Performance & Scalability Audit*
