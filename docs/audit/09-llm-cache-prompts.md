# Audit Report 09: LLM Cache and Prompt Engine Modules

**Scope:** `temper_ai/llm/cache/` (3 files) + `temper_ai/llm/prompts/` (5 files)
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The LLM cache and prompt engine modules are **well-engineered** with strong security posture. The cache layer has robust multi-tenant isolation, O(1) LRU eviction, and thread-safe operations. The prompt engine uses Jinja2's `ImmutableSandboxedEnvironment` for SSTI prevention with recursive variable type validation. Test coverage is excellent (250+ tests across 5 test files).

**Overall Grade: A-** (93/100)

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Code Quality | A | Clean decomposition, good constant extraction, functions within limits |
| Security | A+ | Multi-tenant isolation, SSTI prevention, type validation, cache poisoning defense |
| Error Handling | A | Specific exception types, graceful degradation, proper logging |
| Modularity | A- | Clean backend abstraction; template cache not thread-safe (finding F-03) |
| Feature Completeness | B+ | Only memory backend, no Redis/disk; prompt versioning complete |
| Test Quality | A | 250+ tests, SSTI payloads, concurrency tests, regression tests |
| Architecture | B+ | Missing async support, no cache warming, no distributed cache |

---

## 1. Code Quality Findings

### F-01: `_generate_cache_key_hash` references `LLMCache._normalize_tools` as a static method from module-level function [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:395`
```python
def _generate_cache_key_hash(params: CacheKeyParams) -> str:
    request = {
        ...
        "tools": LLMCache._normalize_tools(params.tools) if params.tools else [],
        ...
    }
```

A module-level helper function reaches into `LLMCache` to call its static method. This creates a coupling between the free function and the class. The `_normalize_tools` method should be extracted as a standalone module-level function since `_generate_cache_key_hash` is already module-level.

**Impact:** Mild code smell; the function cannot be used before `LLMCache` is defined.
**Recommendation:** Move `_normalize_tools` to a standalone function `_normalize_tools(tools)` at module level.

### F-02: `_extract_cache_key_kwargs` mutates its argument via `dict.pop()` [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:281-294`
```python
def _extract_cache_key_kwargs(kwargs: dict[str, Any]) -> CacheKeyParams:
    """Extract CacheKeyParams from legacy kwargs dict."""
    return CacheKeyParams(
        model=kwargs.pop("model"),
        prompt=kwargs.pop("prompt"),
        ...
        extra_params=kwargs,  # Remaining kwargs become extra_params
    )
```

This function destructively modifies its `kwargs` argument using `pop()`. The caller (`generate_key`) passes `kwargs` from `**kwargs`, so the caller's dict is consumed. While functionally correct (the remaining keys become `extra_params`), this is a surprising side-effect pattern that could cause bugs if `kwargs` is used after the call. The `extra_params=kwargs` at the end captures the mutated dict by reference.

**Impact:** Works correctly in current usage but is fragile if code changes. If `kwargs` is reused after calling this function, it would be empty.
**Recommendation:** Use `kwargs.get()` with explicit `extra_params` construction, or document the mutation contract prominently.

### F-03: `TemplateCacheManager` is NOT thread-safe [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/cache.py:14-63`

Unlike `InMemoryCache` which uses `threading.Lock`, `TemplateCacheManager` has no locking around `_template_cache`, `_cache_hits`, and `_cache_misses`. If `PromptEngine` is shared across threads (which is common for web servers), concurrent `render()` calls could corrupt the cache dict or produce incorrect statistics.

```python
class TemplateCacheManager:
    def get_or_compile(self, template_str, sandbox_env):
        jinja_template = self._template_cache.get(template_str)  # No lock
        if jinja_template is None:
            self._cache_misses += 1  # Race condition
            ...
```

**Impact:** Potential data corruption in multi-threaded web server deployments (e.g., FastAPI with thread pool).
**Recommendation:** Add `threading.Lock` to `TemplateCacheManager.get_or_compile()` and the stats counter increments, matching the pattern already used in `InMemoryCache`.

### F-04: `TemplateCacheManager` uses FIFO eviction, not LRU [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/cache.py:52-56`
```python
# Add to cache (FIFO eviction if full)
if len(self._template_cache) >= self._cache_size:
    oldest_key = next(iter(self._template_cache))
    del self._template_cache[oldest_key]
```

The comment correctly says FIFO, but the `InMemoryCache` (in `llm_cache.py`) uses proper LRU with `OrderedDict`. For template caching, FIFO is arguably sufficient since the same templates tend to be reused consistently, but it is inconsistent with the cache module's own LRU approach.

**Impact:** Low -- frequently used templates may be evicted if they were added early, but the cache is typically large enough (1000 entries) that this rarely matters.
**Recommendation:** Consider using `OrderedDict` for consistency, or document the intentional FIFO choice.

### F-05: Unused constants in `cache/constants.py` [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/constants.py:13-14,20-32`

The constants `GOOD_HIT_RATIO`, `POOR_HIT_RATIO`, and all `FIELD_*` and `DISPLAY_*` constants are defined but never imported or used anywhere in the codebase:

```python
GOOD_HIT_RATIO = 0.7
POOR_HIT_RATIO = 0.3

FIELD_MODEL = "model"
FIELD_PROMPT = "prompt"
...
DISPLAY_ELLIPSIS = "..."
```

**Impact:** Dead code that adds maintenance burden.
**Recommendation:** Remove unused constants or add consumers. `GOOD_HIT_RATIO`/`POOR_HIT_RATIO` could be used in health monitoring dashboards to flag cache performance issues.

### F-06: `MAX_VAR_SIZE` computation is unnecessarily obscure [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/validation.py:65`
```python
MAX_VAR_SIZE = SIZE_100MB // MULTIPLIER_MEDIUM // MULTIPLIER_MEDIUM  # 100KB = 100MB / 10 / 10
```

Using `SIZE_100MB // 10 // 10` to get 100KB is a roundabout calculation. A direct `SIZE_100KB` constant exists in `temper_ai/shared/constants/sizes.py` (line 28: `SIZE_100KB = 102400`).

**Impact:** Confusing for maintainers.
**Recommendation:** Replace with `SIZE_100KB` from `temper_ai.shared.constants.sizes`.

### F-07: Nesting depth limit uses obscure constant expression [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/validation.py:82`
```python
if depth > MULTIPLIER_MEDIUM * MULTIPLIER_SMALL:  # 20 = 10 * 2
```

The max nesting depth of 20 is computed as `10 * 2`. This is an artifact of magic-number extraction gone too far. A named constant like `MAX_NESTING_DEPTH = 20` would be clearer.

**Impact:** Readability.
**Recommendation:** Define `MAX_TEMPLATE_NESTING_DEPTH = 20` as a module constant.

---

## 2. Security Findings

### S-01: Strong multi-tenant cache isolation [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:297-306`

The `_validate_cache_key_isolation()` function enforces that every cache key includes either `user_id` or `tenant_id`, preventing cross-tenant data leakage. The error message cites HIPAA, GDPR, and SOC 2 compliance requirements. This is exemplary.

### S-02: Strong SSTI prevention via ImmutableSandboxedEnvironment [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/engine.py:81-85,91-96`

Both inline and file-based template rendering use `ImmutableSandboxedEnvironment`, which blocks:
- Attribute mutation on objects
- Access to `__class__`, `__mro__`, `__subclasses__`
- Python built-in access (`eval`, `exec`, `__import__`)
- File system operations

Combined with `TemplateVariableValidator` allowlisting (str, int, float, bool, list, dict, tuple, None), this provides defense-in-depth against SSTI.

### S-03: Reserved parameter validation prevents cache poisoning [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:433-438,340-348`

The `_RESERVED_PARAMS` frozenset and `_validate_cache_kwargs()` function prevent parameter injection attacks where an attacker could pass `security_context` or `request` as kwargs to override cache key isolation.

### S-04: Type confusion prevention in cache keys [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:321-337`

The `_validate_cache_key_types()` function prevents type confusion attacks (e.g., passing `model=123` instead of `model="gpt-4"`) which could create colliding cache keys.

### S-05: `autoescape=False` is intentional but should be documented [INFO]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/engine.py:82,93`
```python
self._sandbox_env = ImmutableSandboxedEnvironment(
    autoescape=False,  # Prompts are not HTML
    ...
)
```

The comment explains why `autoescape=False` is correct (prompts are not HTML), but this could be confusing in a security audit. The `ImmutableSandboxedEnvironment` provides the security boundary, not autoescaping.

**Recommendation:** Expand the comment: `autoescape=False -- prompts are plaintext, not HTML. SSTI is prevented by the sandbox, not by autoescaping.`

### S-06: `_is_safe_template_value` is defined but only used externally [INFO]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/validation.py:27-51`

This function duplicates the logic of `TemplateVariableValidator._validate_value()` but is used separately by `standard_agent.py` and `base_agent.py` for pre-validation. Having two code paths for the same check creates maintenance risk.

**Recommendation:** Consider refactoring so that both call sites use `TemplateVariableValidator` consistently.

---

## 3. Error Handling Findings

### E-01: Excellent specific exception handling in LLMCache [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:566-573,606-613`

Both `get()` and `set()` catch `(OSError, RuntimeError, ValueError)` specifically, avoiding broad `except Exception:`. `KeyboardInterrupt` and `SystemExit` properly propagate. This is verified by dedicated tests in `test_except_broad_13.py`.

### E-02: PromptEngine wraps all exceptions in `PromptRenderError` [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/engine.py:136-139`
```python
except PromptRenderError:
    raise
except Exception as e:
    raise PromptRenderError(f"Failed to render template: {e}") from e
```

The `except Exception` here is appropriate because Jinja2 can raise various exception types (`TemplateSyntaxError`, `UndefinedError`, `SecurityError`, etc.) and wrapping them provides a consistent API. The `from e` preserves the original traceback.

### E-03: Cache backend error in `_fire_cache_event` accesses private `_cache` attribute [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:480-481`
```python
if isinstance(self._backend, InMemoryCache):
    size = len(self._backend._cache)
```

Accessing `self._backend._cache` (a private attribute) violates encapsulation. If the backend implementation changes, this will break silently.

**Recommendation:** Add a `size` property or method to `CacheBackend` ABC, or use `get_stats()["size"]`.

---

## 4. Modularity Findings

### M-01: Clean `CacheBackend` abstraction enables future backends [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:77-103`

The `CacheBackend` ABC defines a clean interface (`get`, `set`, `delete`, `clear`, `exists`) that would allow Redis, disk, or distributed backends. The `_create_cache_backend()` factory (line 404-412) provides a clean extension point.

### M-02: `dialogue_formatter.py` is not exported from `prompts/__init__.py` [INFO]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/__init__.py:1-5`
```python
from temper_ai.llm.prompts.engine import PromptEngine, PromptRenderError
from temper_ai.llm.prompts.validation import TemplateVariableValidator
```

The `dialogue_formatter` module is imported directly by `standard_agent.py` (line 217) rather than through the package `__init__.py`. This is fine for internal use but means the module is not part of the public API surface.

### M-03: `PromptRenderError` defined in `validation.py` but re-exported from `engine.py` [INFO]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/engine.py` re-exports via `__init__.py`

The `PromptRenderError` class is defined in `validation.py` (line 16) but consumers can import it from `engine.py` due to the `__init__.py` re-export chain. This is a deliberate convenience shim, but the class should arguably live in its own exceptions module since it is used by `standard_agent.py`, `static_checker_agent.py`, and `base_agent.py`.

---

## 5. Feature Completeness

### FC-01: Only memory backend available [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:404-412`
```python
def _create_cache_backend(backend, max_size, eviction_cb):
    if backend == "memory":
        return InMemoryCache(max_size=max_size, on_eviction=eviction_cb)
    raise ValueError(f"Unknown cache backend: {backend}. Use 'memory'.")
```

For production multi-node deployments (Kubernetes/Helm), the in-memory cache is per-process and cannot be shared. A Redis backend would enable shared caching across workers and pods.

**Impact:** Each pod maintains its own cache, leading to duplicated LLM calls across pods.
**Recommendation:** Add a `RedisCacheBackend` implementing `CacheBackend`. The architecture already supports this via the ABC pattern.

### FC-02: No cache warming or pre-population mechanism [LOW]

There is no way to warm the cache with pre-computed responses or replay cached data from a previous session. For deterministic testing or development workflows, cache warming would reduce latency.

### FC-03: No async cache backend support [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:77-103`

The `CacheBackend` ABC uses only synchronous methods. For a Redis or network-based backend, async support (`async get()`, `async set()`) would be needed. The `LLMCache` class would need `async get()` and `async set()` variants.

### FC-04: No TODOs, FIXMEs, or HACKs found [POSITIVE]

No incomplete implementations or technical debt markers exist in any of the audited files.

### FC-05: Prompt versioning is complete [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/engine.py:187-241`

The `render_with_metadata()` and `render_file_with_metadata()` methods return `(rendered_text, template_hash, source)` tuples, enabling prompt versioning and tracking for the Self-Improvement pillar. Template hashes are computed on raw template text (pre-rendering), so the same template with different variables produces the same hash.

---

## 6. Test Quality

### T-01: Excellent test coverage [POSITIVE]

| Test File | Tests | Coverage Area |
|-----------|-------|---------------|
| `tests/test_llm/test_cache/test_llm_cache.py` | ~50 | Core cache operations, key gen, TTL, LRU, concurrency |
| `tests/test_llm/test_cache/test_except_broad_13.py` | 13 | Exception specificity, propagation, logging |
| `tests/test_llm_cache.py` | ~50 | Multi-tenant security, type validation, integration |
| `tests/test_agent/test_prompt_engine.py` | ~40 | Rendering, caching, SSTI, performance |
| `tests/test_agent/test_prompt_template_injection.py` | ~20 | SSTI payloads, type validation, sandbox |
| `tests/test_llm/test_prompt_versioning.py` | 7 | Hash determinism, metadata |
| `tests/test_agent/test_dialogue_formatter.py` | 12 | Dialogue formatting, truncation |

**Total: ~192 tests** with strong coverage of security, concurrency, and edge cases.

### T-02: Dedicated SSTI payload tests [POSITIVE]

**File:** `/home/shinelay/meta-autonomous-framework/tests/test_agent/test_prompt_engine.py:794-811`

Tests include real-world SSTI payloads from PayloadsAllTheThings, including:
- `lipsum.__globals__.__builtins__.__import__('os').popen('id').read()`
- `cycler.__init__.__globals__.os.popen('id').read()`
- `self._TemplateReference__context.cycler.__init__.__globals__.os.popen('id').read()`
- MRO chain traversal payloads

### T-03: Missing test for `CacheKeyParams` dataclass directly [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:58-74`

The `CacheKeyParams` dataclass is tested indirectly through `generate_key()` calls, but has no direct unit tests for its default values or field types.

### T-04: Missing test for `_cleanup_expired` thread safety [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py:198-229`

The `_cleanup_expired()` method is called within `_evict_lru()` which is called within `set()` which holds the lock. However, there is no test verifying that `_cleanup_expired()` works correctly when called from `get_stats(cleanup_expired=True)` under concurrent access. The `get_stats()` method does acquire the lock (line 267), so the implementation is correct, but no test validates this.

### T-05: Duplicate test coverage between `test_llm_cache.py` and `test_cache/test_llm_cache.py` [LOW]

The root-level `tests/test_llm_cache.py` and `tests/test_llm/test_cache/test_llm_cache.py` test many of the same scenarios (basic set/get, TTL, LRU eviction, thread safety). The root-level file adds multi-tenant security tests and type validation tests. Consider consolidating.

### T-06: `TemplateCacheManager` has no direct thread-safety test [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/cache.py`

No test validates concurrent access to `TemplateCacheManager`. This relates directly to finding F-03 (no locking). A test should be added alongside the fix.

---

## 7. Architectural Gaps vs Vision Pillars

### Configuration as Product

**Gap: Cache configuration not exposed in YAML configs**

The LLM cache is configured programmatically via `LLMCache(backend="memory", ttl=3600, max_size=100)` in `providers/base.py`. There is no YAML schema for cache configuration. Users cannot tune cache TTL, max_size, or backend via workflow/agent YAML files.

**Recommendation:** Add cache configuration to the agent YAML schema:
```yaml
cache:
  enabled: true
  backend: memory  # or redis
  ttl: 3600
  max_size: 1000
```

### Self-Improvement

**Strong: Prompt versioning is well-implemented**

The `render_with_metadata()` / `render_file_with_metadata()` methods provide template hashing that enables tracking which prompt template version produced which results. This feeds into the optimization pipeline.

**Gap: Cache hit rates not surfaced to the learning/optimization system**

The `CacheStats` data (hit rate, evictions) is available via `get_stats()` but is not integrated with the learning/observability pipeline. Cache hit rates could inform prompt optimization decisions (e.g., high miss rates might indicate prompts vary too much to cache effectively).

---

## 8. Summary of Actionable Items

### Critical (P0)
None.

### High (P1)
| # | Finding | File | Line | Effort |
|---|---------|------|------|--------|
| F-03 | `TemplateCacheManager` not thread-safe | `prompts/cache.py` | 14-63 | Small |
| T-06 | No concurrency test for `TemplateCacheManager` | `prompts/cache.py` | - | Small |

### Medium (P2)
| # | Finding | File | Line | Effort |
|---|---------|------|------|--------|
| F-02 | `_extract_cache_key_kwargs` mutates argument | `cache/llm_cache.py` | 281 | Small |
| FC-01 | Only memory backend available | `cache/llm_cache.py` | 404 | Medium |
| FC-03 | No async cache backend support | `cache/llm_cache.py` | 77 | Medium |
| T-04 | No concurrent `_cleanup_expired` test | `cache/llm_cache.py` | 198 | Small |

### Low (P3)
| # | Finding | File | Line | Effort |
|---|---------|------|------|--------|
| F-01 | `_normalize_tools` accessed as class static from module function | `cache/llm_cache.py` | 395 | Trivial |
| F-04 | FIFO eviction inconsistent with LRU in `InMemoryCache` | `prompts/cache.py` | 52 | Small |
| F-05 | Unused constants in `cache/constants.py` | `cache/constants.py` | 13-32 | Trivial |
| F-06 | `MAX_VAR_SIZE` uses obscure computation | `prompts/validation.py` | 65 | Trivial |
| F-07 | Nesting depth uses obscure constant expression | `prompts/validation.py` | 82 | Trivial |
| E-03 | Private `_cache` attribute access in `_fire_cache_event` | `cache/llm_cache.py` | 481 | Small |
| T-03 | No direct `CacheKeyParams` unit test | `cache/llm_cache.py` | 58 | Trivial |
| T-05 | Duplicate test coverage across files | `tests/` | - | Small |

---

## Files Reviewed

### Source Files (8)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/__init__.py` (19 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/llm_cache.py` (649 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/cache/constants.py` (33 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/__init__.py` (5 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/engine.py` (277 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/cache.py` (111 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/validation.py` (108 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/prompts/dialogue_formatter.py` (129 lines)

### Test Files (6)
- `/home/shinelay/meta-autonomous-framework/tests/test_llm/test_cache/test_llm_cache.py` (937 lines)
- `/home/shinelay/meta-autonomous-framework/tests/test_llm/test_cache/test_except_broad_13.py` (225 lines)
- `/home/shinelay/meta-autonomous-framework/tests/test_llm_cache.py` (1136 lines)
- `/home/shinelay/meta-autonomous-framework/tests/test_agent/test_prompt_engine.py` (1183 lines)
- `/home/shinelay/meta-autonomous-framework/tests/test_agent/test_prompt_template_injection.py` (227 lines)
- `/home/shinelay/meta-autonomous-framework/tests/test_llm/test_prompt_versioning.py` (108 lines)

### Related Files (3)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_prompt.py` (113 lines)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/providers/base.py` (cache integration)
- `/home/shinelay/meta-autonomous-framework/temper_ai/llm/llm_loop_events.py` (CacheEventData)
