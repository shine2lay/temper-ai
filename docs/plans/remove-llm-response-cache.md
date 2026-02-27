# Plan: Remove Unused LLM Response Cache

## Problem

`LLMCache` is a 700-line in-memory LRU response cache with SHA-256 content-based keys, TTL expiration, tenant isolation, and observability hooks. It is fully built but **never enabled** in the standard agent pipeline:

- The factory (`providers/factory.py`) never passes `enable_cache=True`
- `InferenceConfig` has no `enable_cache` field
- `BaseLLM._cache` is always `None` in production
- Every `check_cache()` call short-circuits at `if instance._cache is None: return None, None`

Even if enabled, the agentic tool-calling loop mutates the prompt every iteration (tool results, sliding window, context injection), making the cache hit rate effectively zero. Useful LLM caching for agents would need semantic similarity matching, not exact SHA-256 key comparison.

The cache adds maintenance weight to `BaseLLM`, `_base_helpers.py`, `LLMConfig`, and event emission code — all for dead code paths.

## Removal Scope

### Delete entirely

| Path | What |
|---|---|
| `temper_ai/llm/cache/llm_cache.py` | Main LLMCache implementation (698 lines) |
| `temper_ai/llm/cache/constants.py` | Cache constants (DEFAULT_CACHE_SIZE, TTL, field names) |
| `temper_ai/llm/cache/__init__.py` | Re-exports |
| `tests/test_llm/test_cache/` | All test files in directory |
| `tests/test_llm_cache.py` | Root-level cache tests |
| `tests/test_auth/test_cache_concurrent.py` | Concurrency tests for LLMCache |

### Modify: `temper_ai/llm/providers/base.py`

- Remove try/except import of `LLMCache` (lines 18-24) and `CACHE_AVAILABLE` flag
- Remove from `LLMConfig`: `enable_cache: bool = False` and `cache_ttl: int | None` (lines 160-161)
- Remove `DEFAULT_CACHE_TTL` constant (line 91)
- Remove `_cache: Optional["LLMCache"]` class attribute (line 181)
- Remove `_check_cache` and `_cache_response` callable attribute declarations (lines 187-190)
- Remove `enable_cache`/`cache_ttl` reads from `__init__` (lines 237-238, 254-255)
- Simplify `_init_infrastructure()` — remove `enable_cache`/`cache_ttl` params and all cache init logic (lines 507-530)
- Remove `cache_key` handling in `complete()` (line 401) and `acomplete()` (line 464) — these call `self._check_cache` and return early on cache hit

### Modify: `temper_ai/llm/providers/_base_helpers.py`

- Delete `check_cache()` function (lines 224-266)
- Delete `cache_response()` function (lines 269-284)
- In `execute_and_parse()` (line 292): remove `cache_key` param and `cache_response()` call
- In `make_streaming_call_impl()` (line 414): remove `check_cache()` call, simplify return
- In `execute_streaming_impl()` (line 446): remove `cache_key` param and `cache_response()` call
- In `execute_streaming_async_impl()` (line 475): remove `cache_key` param and `cache_response()` call
- In `bind_callable_attributes()` (line 529): remove `_check_cache` and `_cache_response` bindings

### Modify: `temper_ai/llm/llm_loop_events.py`

- Remove `CacheEventData` dataclass (lines 44-50)
- Remove `emit_cache_event()` function (lines 89-111)

### Modify: `temper_ai/llm/prompts/engine.py` and `temper_ai/llm/prompts/cache.py`

Both import `DEFAULT_CACHE_SIZE` from `temper_ai.llm.cache.constants`. This constant controls the **Jinja2 template cache** size, which is unrelated to LLM response caching.

Move `DEFAULT_CACHE_SIZE` to `temper_ai/llm/constants.py` (or inline the value) and update both imports.

### Modify test files (partial)

| File | Change |
|---|---|
| `tests/test_benchmarks/test_performance_llm.py` | Delete `test_llm_cache_hit` and `test_llm_cache_miss` methods (lines 160-195) |
| `tests/test_llm/test_service_observability.py` | Delete `TestLLMCacheEvents` class (lines 265-352) |
| `tests/test_agent/test_sync_async_33a.py` | Delete `TestCheckCache` and `TestCacheResponse` classes |

### Do NOT touch

- `temper_ai/tools/executor.py` — has its own `tool_cache_ttl`, unrelated
- `temper_ai/llm/prompts/cache.py` — this is the Jinja2 **template** cache (`TemplateCacheManager`), not the LLM response cache. Keep it.
- Schema caches on `LLMService` (`_cached_text_schemas`, `_cached_native_defs`) — these are useful and stay

## Files Summary

| File | Action |
|---|---|
| `temper_ai/llm/cache/llm_cache.py` | **Delete** |
| `temper_ai/llm/cache/constants.py` | **Delete** (move `DEFAULT_CACHE_SIZE` to `constants.py`) |
| `temper_ai/llm/cache/__init__.py` | **Delete** |
| `temper_ai/llm/providers/base.py` | Remove cache attributes, config fields, init logic |
| `temper_ai/llm/providers/_base_helpers.py` | Remove `check_cache`, `cache_response`, cache params from helpers |
| `temper_ai/llm/llm_loop_events.py` | Remove `CacheEventData` and `emit_cache_event` |
| `temper_ai/llm/prompts/engine.py` | Update `DEFAULT_CACHE_SIZE` import |
| `temper_ai/llm/prompts/cache.py` | Update `DEFAULT_CACHE_SIZE` import |
| `temper_ai/llm/constants.py` | Add `DEFAULT_CACHE_SIZE` (moved from cache module) |
| `tests/test_llm/test_cache/` | **Delete directory** |
| `tests/test_llm_cache.py` | **Delete** |
| `tests/test_auth/test_cache_concurrent.py` | **Delete** |
| `tests/test_benchmarks/test_performance_llm.py` | Remove 2 cache test methods |
| `tests/test_llm/test_service_observability.py` | Remove `TestLLMCacheEvents` class |
| `tests/test_agent/test_sync_async_33a.py` | Remove cache test classes |

## Verification

```bash
# Confirm no remaining references to deleted modules
grep -rn "from temper_ai.llm.cache" temper_ai/ tests/
grep -rn "LLMCache" temper_ai/ tests/
grep -rn "CACHE_AVAILABLE" temper_ai/
grep -rn "check_cache\|cache_response\|_check_cache\|_cache_response" temper_ai/
grep -rn "CacheEventData\|emit_cache_event" temper_ai/

# Run affected tests
pytest tests/test_llm/ -v
pytest tests/test_benchmarks/test_performance_llm.py -v
pytest tests/test_agent/test_sync_async_33a.py -v

# Full suite
pytest tests/ -x
```
