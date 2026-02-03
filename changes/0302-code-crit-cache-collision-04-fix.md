# code-crit-cache-collision-04: Cache Key Collision Fix

## Problem
`LLMCache.generate_key()` did not explicitly include `system_prompt` or `tools`
in cache key generation. While these could flow through `**kwargs`, the implicit
passing was fragile and tools lists were not normalized for deterministic hashing.
Different tool orderings would produce different cache keys (false misses), and
if callers omitted these parameters, different requests could collide.

## Fix

### 1. Explicit parameters in `generate_key()` (`src/cache/llm_cache.py`)
- Added `system_prompt: Optional[str]` and `tools: Optional[List[Dict[str, Any]]]`
  as explicit named parameters
- Both included in the `request` dict for cache key computation
- Added `_normalize_tools()` static method to sort tools by name and sort dict
  keys within each tool — ensures `[{a}, {b}]` and `[{b}, {a}]` produce same key
- Added both to `_RESERVED_PARAMS` frozenset to prevent kwargs injection
- Added `List` to typing imports

### 2. Updated callers in `src/agents/llm_providers.py`
- Both `complete()` and `acomplete()` now explicitly extract and pass
  `system_prompt` and `tools` from kwargs to `generate_key()`
- Added both to `_extracted_keys` to prevent double-passing via `**_remaining_kwargs`

## Testing
- 61 LLM cache tests pass
- 17 failures in test_action_policy_engine.py are pre-existing (different caching system)
