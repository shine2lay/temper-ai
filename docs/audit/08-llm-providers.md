# Audit Report: LLM Providers Module

**Module:** `temper_ai/llm/providers/`
**Date:** 2026-02-22
**Files reviewed:** 9 source files, 1 primary test file (134 tests)
**Scope:** `base.py`, `_base_helpers.py`, `_stream_helpers.py`, `factory.py`, `ollama.py`, `vllm_provider.py`, `openai_provider.py`, `anthropic_provider.py`, `__init__.py`

---

## Executive Summary

The LLM providers module is a well-structured abstraction layer that unifies four LLM backends (Ollama, OpenAI, Anthropic, vLLM) behind a common `BaseLLM` interface. The design follows the Template Method pattern for `complete()`/`acomplete()` and the Factory pattern for provider construction. Infrastructure concerns (circuit breakers, HTTP client pooling, caching, SSRF protection) are handled at the base class level, giving all providers consistent resilience for free.

**Key strengths:** Consistent provider interface, SSRF validation on base_url, automatic error message sanitization, shared circuit breakers with LRU eviction, HTTP/2 auto-detection, exponential backoff with jitter, comprehensive test suite for the sync path (134 tests).

**Key weaknesses:** Anthropic provider has no streaming support (NotImplementedError), OpenAI provider ignores tool calls entirely in `_build_request`, HTTP status code constants are duplicated between two files, Ollama's `_use_chat_api` is mutable instance state set as a side-effect of `_build_request` (thread-unsafe), `_async_client_lock` initialization has a TOCTOU race, `LLMConfig` is defined but never used by any factory function, and async streaming paths have zero dedicated test coverage.

**Overall grade: B+ (85/100)**

---

## 1. Code Quality

### 1.1 Function Length Violations (>50 lines)

| File:Line | Function | Lines | Severity |
|---|---|---|---|
| `base.py:201-248` | `BaseLLM.__init__` | 48 | OK (under limit) |
| `base.py:376-428` | `BaseLLM.complete` | 53 | Low |
| `base.py:430-483` | `BaseLLM.acomplete` | 54 | Low |
| `_base_helpers.py:250-290` | `check_cache` | 41 | OK |
| `_base_helpers.py:521-529` | `bind_callable_attributes` | 9 | OK |
| `vllm_provider.py:236-294` | `VllmLLM._consume_stream` | 59 | Medium |
| `vllm_provider.py:296-354` | `VllmLLM._aconsume_stream` | 59 | Medium |
| `ollama.py:220-261` | `OllamaLLM._consume_stream` | 42 | OK |
| `ollama.py:263-304` | `OllamaLLM._aconsume_stream` | 42 | OK |

**Finding LP-01 (Low):** `base.py:376-428` `complete()` at 53 lines and `base.py:430-483` `acomplete()` at 54 lines each slightly exceed the 50-line limit. However, these are nearly identical retry-loop methods and the duplication between them is intentional (sync vs async). Moving the retry logic into a shared parameterized helper would fix the length issue and reduce duplication.

**Finding LP-02 (Medium):** `vllm_provider.py:236-294` `_consume_stream()` at 59 lines and `vllm_provider.py:296-354` `_aconsume_stream()` at 59 lines are near-identical sync/async versions. The core loop body (lines 249-293 and 309-353) is duplicated verbatim except for `for line in response.iter_lines()` vs `async for line in response.aiter_lines()`. Consider extracting the per-line processing logic into a shared helper.

### 1.2 Parameter Count

All public functions and constructors stay within the 7-parameter limit. `BaseLLM.__init__` uses a `config: LLMConfig` parameter object pattern to bundle 12 parameters, which is clean. The `**kwargs` fallback path accepts parameters loosely but this is documented as legacy.

### 1.3 Nesting Depth

No function exceeds 4 levels of nesting. The deepest nesting (3 levels) is in:
- `base.py:394-425` -- `complete()` inner `_make_api_call()` with for-loop + try/except + if-check
- `ollama.py:104-116` -- `_parse_response()` with if/for/append inside tool_calls branch

### 1.4 Magic Numbers

All numeric literals are properly named as constants or have inline comments:
- `base.py:87-96` -- `DEFAULT_TEMPERATURE = 0.7`, `DEFAULT_TOP_P = 0.9`, `DEFAULT_REQUEST_TIMEOUT = 600`, `DEFAULT_CACHE_TTL = 3600`, `HTTP_OK = 200`, etc.
- `ollama.py:27` -- `DEFAULT_REPEAT_PENALTY = 1.1`
- `factory.py:17` -- `OLLAMA_DEFAULT_PORT = 11434`

No raw magic numbers found.

### 1.5 Naming and Style

All naming follows Python conventions. Class names are PascalCase (`BaseLLM`, `OllamaLLM`), private helpers use leading underscore, constants are UPPER_CASE. No naming collisions detected across modules.

### 1.6 Import Fan-Out

| File | Unique Module Imports | Status |
|---|---|---|
| `base.py` | 8 (asyncio, collections, logging, random, threading, time, httpx, + 5 internal) | OK (exactly at limit) |
| `_base_helpers.py` | 7 | OK |
| `factory.py` | 5 | OK |
| `ollama.py` | 5 | OK |
| `openai_provider.py` | 4 | OK |
| `anthropic_provider.py` | 2 | OK |
| `vllm_provider.py` | 5 | OK |
| `_stream_helpers.py` | 2 | OK |

**Finding LP-03 (Low):** `base.py` is at exactly the fan-out limit of 8 unique external module imports. This was achieved by extracting most logic to `_base_helpers.py`, but the 11 separate `from _base_helpers import ...` blocks (lines 31-63) are visually noisy. A single import with parenthesized names would be cleaner, though this is cosmetic.

### 1.7 Duplication

**Finding LP-04 (Medium):** HTTP status code constants are defined in **two** places:
- `base.py:93-96` -- `HTTP_OK = 200`, `HTTP_UNAUTHORIZED = 401`, `HTTP_RATE_LIMIT = 429`, `HTTP_SERVER_ERROR = 500`
- `_base_helpers.py:41-44` -- identical definitions

The `base.py` copies are unused; all runtime code in `_base_helpers.py` uses its own local copies. The `base.py` versions appear to be dead code left over from the refactoring that extracted `_base_helpers.py`.

**Finding LP-05 (Medium):** The `stream()` and `astream()` method bodies in `ollama.py`, `vllm_provider.py`, and `openai_provider.py` are structurally identical. Each one:
1. Checks `on_chunk is None` -> fallback to `complete()`/`acomplete()`
2. Calls `self._make_streaming_call_impl()` for rate limiting / cache
3. Defines an inner `_make_streaming_call()` closure with circuit breaker wrapping
4. Inside: builds request, gets client, sends stream, calls `_execute_streaming_impl()`

This 15-line boilerplate is repeated 6 times (sync + async for 3 providers). The scanner `# scanner-ignore: duplicate` annotations acknowledge this. A template method on `BaseLLM` that accepts a "build_stream_request" callback could eliminate this duplication.

**Finding LP-06 (Medium):** `_consume_stream()` / `_aconsume_stream()` sync/async pairs in `ollama.py` (lines 220-304), `vllm_provider.py` (lines 236-354), and `openai_provider.py` (lines 135-225) are near-identical sync/async mirrors. Ideally each provider would define only a `_process_stream_line()` method and the base class would handle the iteration variant.

---

## 2. Security

### 2.1 SSRF Protection (Good)

`_base_helpers.py:54-79` `validate_base_url()` blocks:
- Cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`)
- Private/reserved/link-local/loopback IP addresses (via `ipaddress.ip_address()`)
- Allows localhost explicitly (needed for Ollama/vLLM)

This is called for every `BaseLLM.__init__()` at `base.py:222` and `base.py:237`.

**Finding LP-07 (Low):** The SSRF check does not resolve DNS. An attacker could register `evil.com` pointing to `169.254.169.254` and bypass the check, since `urlparse("http://evil.com").hostname` returns `"evil.com"` which is not in the blocked list, and `ipaddress.ip_address("evil.com")` raises `ValueError` which is caught and ignored (line 75-78). This is a known limitation documented in most SSRF libraries but worth noting. A DNS-resolution-based check would be more robust.

### 2.2 API Key Handling (Good)

- API keys are stored as `self.api_key` (plain attribute), not logged.
- `factory.py:123-128` resolves `api_key_ref` via `os.getenv()` -- the env var name is dereferenced, not the raw key.
- Error messages are sanitized via `sanitize_error_message()` (`_base_helpers.py:333`) before being raised, using regex patterns that redact `sk-*`, `Bearer *`, `api_key=*`, JWT tokens, and AWS keys.
- Response body is truncated to `MAX_ERROR_MESSAGE_LENGTH = 500` chars before sanitization (`_base_helpers.py:333`).

**No API keys are logged in any provider code.** The `logger.debug()` calls in cleanup paths log only generic error descriptions, not request/response data.

### 2.3 Input Validation

**Finding LP-08 (Low):** `BaseLLM.__init__()` does not validate parameter ranges:
- `temperature` accepts any float (no 0.0-2.0 range check)
- `max_tokens` accepts 0 and negative values (`base.py:240` with `kwargs.get("max_tokens", 2048)`)
- `timeout` accepts 0 (could cause immediate timeouts)

The test suite documents this at `test_llm_providers.py:1386-1413` (`test_max_tokens_zero_accepted`, `test_max_tokens_negative_accepted`) as known behavior. These are soft issues -- the API endpoints will reject invalid values -- but client-side validation would give better error messages.

### 2.4 Anthropic API Version Header

`anthropic_provider.py:23` hardcodes `"anthropic-version": "2023-06-01"`. This is the correct header name and a valid API version, but it is not configurable. If Anthropic releases a breaking version change, users would need to modify source code. Consider making this configurable via `LLMConfig` or a constructor parameter.

---

## 3. Error Handling

### 3.1 Retry Logic (Good)

`base.py:394-426` (sync) and `base.py:447-480` (async) implement exponential backoff with jitter:
- `delay = retry_delay * (BACKOFF_FACTOR ** attempt) * (JITTER_MIN + random.random())`
- Retries on: `httpx.TimeoutException`, `LLMRateLimitError`
- Does NOT retry on: `LLMAuthenticationError`, `httpx.HTTPStatusError` (immediate re-raise)
- After max retries: raises `LLMTimeoutError` (for timeouts) or re-raises the last rate limit error

### 3.2 Circuit Breaker Integration (Good)

- Shared circuit breakers per `(provider, model, base_url)` tuple with LRU eviction (`_base_helpers.py:86-106`)
- Thread-safe via `threading.Lock` (`_base_helpers.py:96`)
- The complete()/acomplete() inner functions are wrapped with `self._circuit_breaker.call()` / `.async_call()`

### 3.3 HTTP Error Classification (Good)

`_base_helpers.py:331-341` `handle_error_response()` maps HTTP status codes to typed exceptions:
- 401 -> `LLMAuthenticationError`
- 429 -> `LLMRateLimitError`
- 500+ -> `LLMError` (server error)
- Other 4xx -> `LLMError` (generic)

**Finding LP-09 (Low):** The `Retry-After` header from 429 responses is not extracted. `LLMRateLimitError` has a `retry_after` attribute (defined in `exceptions.py:455`) but it is never populated by `handle_error_response()`. The retry logic uses its own backoff calculation instead. Respecting server-provided `Retry-After` headers would improve rate limit handling for providers that set this header (OpenAI does).

### 3.4 Timeout Configuration (Good)

HTTP clients use explicit `httpx.Timeout(timeout=600, connect=30)` at:
- `_base_helpers.py:177` (sync client)
- `_base_helpers.py:210` (async client, safe path)
- `_base_helpers.py:237` (async client, sync accessor)

This separates connect timeout (30s) from overall timeout (configurable, default 600s), preventing the common mistake of setting a very long connect timeout.

### 3.5 Resource Cleanup (Good)

- Context manager support via `LLMContextManagerMixin` (`_base_helpers.py:532-547`)
- `__del__` emits `ResourceWarning` if not properly closed (`base.py:281-294`)
- Sync `close()` schedules async client close if event loop is running (`_base_helpers.py:362-364`)
- Async `aclose()` properly awaits both client closures (`_base_helpers.py:378-397`)
- Shared HTTP client pool has `reset_shared_http_clients()` for test isolation

---

## 4. Modularity and Provider Swappability

### 4.1 Abstract Interface (Good)

`BaseLLM` defines 4 abstract methods that each provider must implement:
1. `_build_request(prompt, **kwargs) -> dict` -- provider-specific request payload
2. `_parse_response(response, latency_ms) -> LLMResponse` -- provider-specific response parsing
3. `_get_headers() -> dict` -- provider-specific HTTP headers
4. `_get_endpoint() -> str` -- provider-specific API path

This is the right level of abstraction. All HTTP transport, retry, caching, and circuit breaking are handled by `BaseLLM`.

### 4.2 Factory Pattern (Good)

Three factory functions cover different use cases:
- `create_llm_client(provider, model, base_url, ...)` -- individual params
- `create_llm_from_config(inference_config)` -- from YAML config
- `create_llm_provider(inference_config)` -- deprecated wrapper

Provider dispatch uses a clean `_PROVIDER_CLASSES` dict (`factory.py:20-25`).

### 4.3 Provider Feature Parity

| Feature | Ollama | OpenAI | Anthropic | vLLM |
|---|---|---|---|---|
| `complete()` | Yes | Yes | Yes | Yes |
| `acomplete()` | Yes | Yes | Yes | Yes |
| `stream()` | Yes | Yes | No* | Yes |
| `astream()` | Yes | Yes | No* | Yes |
| Tool calls | Yes (XML) | **No** | No | Yes (XML) |
| Thinking/reasoning tokens | Yes | No | No | Yes |
| System message handling | Via messages | Via messages | Extracted to top-level | Via messages |
| Bearer auth | No | Yes | No (x-api-key) | Optional |

*\* `AnthropicLLM._consume_stream()` raises `NotImplementedError`*

**Finding LP-10 (High):** `AnthropicLLM` (`anthropic_provider.py:64-78`) has **no streaming support**. Both `_consume_stream()` and `_aconsume_stream()` raise `NotImplementedError`. Since the base class `stream()` falls back to `complete()` when `on_chunk is None`, and the Anthropic subclass does not override `stream()`/`astream()`, streaming calls with a callback will fail through to the base class which calls `_consume_stream()` on the streaming HTTP response -- hitting the `NotImplementedError`. This is a **feature gap** that should either be implemented or documented with a clear error message when `on_chunk` is provided.

**Finding LP-11 (High):** `OpenAILLM._build_request()` (`openai_provider.py:38-49`) does **not** pass `tools` or `tool_choice` through to the request payload. While `VllmLLM._build_request()` at `vllm_provider.py:69-70` includes `tools` and `OllamaLLM._build_request()` at `ollama.py:68-79` does as well, the OpenAI provider silently drops them. This means OpenAI function/tool calling cannot work through this provider. The `_parse_response()` method also does not handle `tool_calls` in the response message.

### 4.4 Ollama Thread Safety Issue

**Finding LP-12 (High):** `OllamaLLM._use_chat_api` (`ollama.py:44`) is a **mutable instance variable** that is set as a side-effect of `_build_request()`:
- `ollama.py:69` -- `self._use_chat_api = True` (when tools provided)
- `ollama.py:82` -- `self._use_chat_api = True` (when messages provided)
- `ollama.py:90` -- `self._use_chat_api = False` (plain prompt)

This state is then read by `_get_endpoint()` (`ollama.py:47-49`) and `_parse_response()` (`ollama.py:99`) and `_extract_chunk_fields()` (`ollama.py:313`).

If two threads call `complete()` concurrently on the same `OllamaLLM` instance -- one with tools, one without -- the `_use_chat_api` flag could be overwritten between `_build_request()` and `_parse_response()`, causing a mismatch where the response is parsed with the wrong format expectations.

**Fix:** Instead of mutable instance state, return the API mode from `_build_request()` (e.g., include it in the request dict as metadata) or determine it in `_parse_response()` based on the response structure.

---

## 5. Feature Completeness

### 5.1 `LLMConfig` Unused

**Finding LP-13 (Medium):** `LLMConfig` dataclass (`base.py:139-157`) is defined as "recommended for new code" but is **never used by any factory function**. Neither `create_llm_client()`, `create_llm_from_config()`, nor any test constructs an `LLMConfig` instance. The `BaseLLM.__init__()` accepts it as a parameter, but the factories always pass individual kwargs. This is dead code in practice.

### 5.2 OpenAI Streaming Tool Calls

**Finding LP-14 (Medium):** `OpenAILLM._consume_stream()` and `_aconsume_stream()` (`openai_provider.py:135-225`) parse content deltas but do not accumulate streaming tool call deltas. Compare with `VllmLLM` which has `_accumulate_delta_tool_calls()` (`vllm_provider.py:209-234`) and post-stream XML conversion (`vllm_provider.py:282-289`). Since OpenAI also sends tool calls as streaming deltas, the OpenAI provider would silently drop them during streaming.

### 5.3 Anthropic System Message Handling

`AnthropicLLM._build_request()` (`anthropic_provider.py:41-45`) correctly extracts system messages and moves them to the top-level `system` parameter, as required by Anthropic's API. However, only the **first** system message is used (`system_msgs[0]["content"]`). Multiple system messages are silently dropped.

### 5.4 Hardcoded API Version

**Finding LP-15 (Low):** `anthropic_provider.py:23` hardcodes `"anthropic-version": "2023-06-01"`. This is the only non-configurable API version across all providers. The header value is nearly 3 years old. While Anthropic maintains backward compatibility, newer API features (e.g., extended thinking, tool use, computer use) may require newer API versions.

### 5.5 Cache Serialization Excludes `raw_response`

`_base_helpers.py:296-306` `cache_response()` serializes `LLMResponse` to JSON but explicitly excludes `raw_response`. This means cached responses will always have `raw_response=None` even if the original had it. This is likely intentional (raw responses can be very large) but is not documented.

---

## 6. Test Quality

### 6.1 Test Coverage Summary

The primary test file (`tests/test_agent/test_llm_providers.py`) contains **134 test functions** organized into these test classes:

| Test Class | Tests | Coverage Area |
|---|---|---|
| `TestOllamaLLM` | 6 | Init, endpoint, headers, request, parse, complete |
| `TestOpenAILLM` | 4 | Init, endpoint, headers, request, parse |
| `TestAnthropicLLM` | 5 | Init, endpoint, headers, request, parse |
| `TestVllmLLM` | 7 | Init, endpoint, headers, request (tools, stream, penalty), parse |
| `TestVllmSSEParsing` | 5 | SSE line parsing edge cases |
| `TestVllmChunkExtraction` | 5 | Streaming chunk field extraction |
| `TestErrorHandling` | 5 | Auth error, rate limit, server error, timeout, retry |
| `TestErrorResponseSanitization` | 5 | API key redaction, bearer token redaction, truncation |
| `TestCreateLLMClient` | 7 | Factory functions, unknown provider, case-insensitive |
| `TestContextManager` | 1 | Context manager cleanup |
| `TestRequestOverrides` | 2 | Temperature and max_tokens override |
| `TestCircuitBreaker` | 11 | Open/half-open/recovery, isolation, thread safety |
| `TestTokenLimitEnforcement` | 17 | Max tokens, boundaries, unicode, cost estimation |
| `TestFailoverProvider` | 10+ | Failover on errors, sticky session, async |
| Various others | ~54 | SSRF, caching, connection pool, async cleanup |

### 6.2 Coverage Gaps

**Finding LP-16 (High):** **Zero tests for async streaming.** No test calls `astream()` on any provider. The sync `stream()` is also not tested end-to-end with mocked NDJSON/SSE responses. The `TestVllmSSEParsing` and `TestVllmChunkExtraction` tests only test static helper methods, not the full streaming flow with httpx mocked responses.

**Finding LP-17 (High):** **No tests for `create_llm_from_config()`.** The test file tests `create_llm_client()` extensively but never tests `create_llm_from_config()`, which is the preferred factory function. The `api_key_ref` env-var resolution path (`factory.py:123-128`) is untested -- including the `ValueError` raised when the env var is missing.

**Finding LP-18 (Medium):** **No tests for `validate_base_url()` SSRF protection.** Despite being a security-critical function, there are no dedicated tests for the SSRF validation in `_base_helpers.py:54-79`. No test verifies that `169.254.169.254` or private IP ranges are blocked, or that localhost is allowed.

**Finding LP-19 (Medium):** **No tests for `LLMConfig` parameter path.** The `BaseLLM.__init__()` `config: LLMConfig` branch (lines 220-232) is never exercised in tests. All tests pass individual parameters.

**Finding LP-20 (Low):** Several `TestTokenLimitEnforcement` tests (lines 1337-1583) are **placeholder tests** that assert only test setup conditions (`assert len(test_cases) == 4`, `assert workflow_steps > 0`, `assert gpt4_rate > 0`). These document expected behavior but do not test actual code. At least 12 of the 17 tests in this class are placeholders.

### 6.3 Test Infrastructure

- `mock_httpx_client` fixture properly clears shared HTTP client pool before/after each test (`test_llm_providers.py:60-72`)
- `InMemoryStorage` class provides clean cache testing
- Tests use `with patch('time.sleep')` to speed up retry tests

---

## 7. Architectural Assessment

### 7.1 Radical Modularity: Are Providers Truly Swappable?

**Mostly yes, with caveats.** The `BaseLLM` abstraction successfully decouples:
- HTTP transport (shared httpx clients, connection pooling, HTTP/2)
- Resilience (circuit breakers, retry with backoff, rate limiting)
- Caching (pluggable LLMCache with TTL)
- Error handling (typed exceptions, sanitization)

A new provider can be added by:
1. Subclassing `BaseLLM`
2. Implementing 4 abstract methods
3. Adding to `_PROVIDER_CLASSES` dict in `factory.py`
4. Adding to `LLMProvider` enum in `base.py`

**However**, the providers are NOT fully interchangeable at runtime because:
- **Tool calling**: Only Ollama and vLLM support it; OpenAI silently drops tools (LP-11)
- **Streaming**: Anthropic does not support it (LP-10)
- **Thinking tokens**: Only Ollama and vLLM support reasoning/thinking token separation
- **System messages**: Anthropic requires extraction to top-level; others inline

### 7.2 Async Lock TOCTOU Race

**Finding LP-21 (Medium):** `_base_helpers.py:416-420` `get_async_lock()`:
```python
def get_async_lock(cls: Any) -> asyncio.Lock:
    if cls._async_client_lock is None:
        cls._async_client_lock = asyncio.Lock()
    return cast(asyncio.Lock, cls._async_client_lock)
```

This check-then-set pattern is not atomic. If two coroutines call `get_async_lock()` concurrently before any lock exists, they could each create a separate `asyncio.Lock()` instance. The second assignment overwrites the first, but the first coroutine may already be using the discarded lock. In practice this is unlikely to cause issues because asyncio is single-threaded, but if called from multiple threads each running their own event loop, it could lead to two coroutines holding different "class-level" locks simultaneously.

### 7.3 Callable Attribute Binding Pattern

`_base_helpers.py:521-529` `bind_callable_attributes()` uses lambdas to attach helper functions as instance attributes rather than methods. This was done to "reduce class method count" per the comment, but it has trade-offs:
- Pro: Keeps `BaseLLM` class body small for readability
- Con: These attributes bypass `super()` and method resolution order
- Con: Type hints on the class body (lines 181-187) use complex `Callable[...]` signatures that are hard to read
- Con: IDE navigation and refactoring tools cannot follow lambda references

This is an unusual but functional pattern. It works correctly for the use case.

---

## 8. Findings Summary

| ID | Severity | Category | Description | File:Line |
|---|---|---|---|---|
| LP-01 | Low | Code Quality | `complete()` and `acomplete()` slightly exceed 50-line limit | `base.py:376-483` |
| LP-02 | Medium | Code Quality | `_consume_stream`/`_aconsume_stream` sync/async duplication in vLLM | `vllm_provider.py:236-354` |
| LP-03 | Low | Code Quality | 11 separate `from _base_helpers import` blocks in base.py | `base.py:31-63` |
| LP-04 | Medium | Code Quality | HTTP status code constants duplicated in base.py and _base_helpers.py | `base.py:93-96`, `_base_helpers.py:41-44` |
| LP-05 | Medium | Code Quality | `stream()`/`astream()` boilerplate duplicated across 3 providers (6x) | `ollama.py:151-218`, `openai_provider.py:71-133`, `vllm_provider.py:141-207` |
| LP-06 | Medium | Code Quality | Sync/async stream consumer mirroring across all providers | Multiple files |
| LP-07 | Low | Security | SSRF check does not resolve DNS (hostname bypass possible) | `_base_helpers.py:54-79` |
| LP-08 | Low | Security | No client-side validation of temperature, max_tokens, timeout ranges | `base.py:238-247` |
| LP-09 | Low | Error Handling | `Retry-After` header from 429 responses not extracted | `_base_helpers.py:336-337` |
| LP-10 | **High** | Feature Gap | Anthropic provider has no streaming support | `anthropic_provider.py:64-78` |
| LP-11 | **High** | Feature Gap | OpenAI provider silently drops tools in `_build_request()` | `openai_provider.py:38-49` |
| LP-12 | **High** | Thread Safety | Ollama `_use_chat_api` mutable state set in `_build_request()` | `ollama.py:44,69,82,90` |
| LP-13 | Medium | Dead Code | `LLMConfig` dataclass defined but never used by factories | `base.py:139-157` |
| LP-14 | Medium | Feature Gap | OpenAI streaming does not handle tool call deltas | `openai_provider.py:135-225` |
| LP-15 | Low | Feature Gap | Hardcoded Anthropic API version `2023-06-01` | `anthropic_provider.py:23` |
| LP-16 | **High** | Test Gap | No tests for async streaming (`astream()`) on any provider | `test_llm_providers.py` |
| LP-17 | **High** | Test Gap | No tests for `create_llm_from_config()` or `api_key_ref` resolution | `test_llm_providers.py` |
| LP-18 | Medium | Test Gap | No tests for SSRF `validate_base_url()` protection | `test_llm_providers.py` |
| LP-19 | Medium | Test Gap | No tests for `LLMConfig` constructor path | `test_llm_providers.py` |
| LP-20 | Low | Test Gap | 12 of 17 token limit tests are placeholder assertions | `test_llm_providers.py:1337-1583` |
| LP-21 | Medium | Architecture | `get_async_lock()` TOCTOU race on class-level lock initialization | `_base_helpers.py:416-420` |

### Severity Distribution

- **High:** 5 findings (LP-10, LP-11, LP-12, LP-16, LP-17)
- **Medium:** 9 findings (LP-02, LP-04, LP-05, LP-06, LP-13, LP-14, LP-18, LP-19, LP-21)
- **Low:** 7 findings (LP-01, LP-03, LP-07, LP-08, LP-09, LP-15, LP-20)

---

## 9. Recommendations (Priority Order)

### P0 -- Must Fix

1. **LP-12:** Fix Ollama `_use_chat_api` thread safety. Return the API mode from `_build_request()` as part of the request dict or determine it from response shape in `_parse_response()`. This is a correctness bug under concurrent use.

2. **LP-11:** Add tool/function call support to `OpenAILLM._build_request()`. Pass `tools` and `tool_choice` kwargs through to the request payload. Add `_format_tool_calls_xml()` to `_parse_response()` similar to vLLM.

### P1 -- Should Fix

3. **LP-10:** Implement Anthropic streaming using their SSE API (`stream: true` with `event: content_block_delta` events). At minimum, override `stream()` to raise a clear error when `on_chunk` is provided, rather than letting it fall through to `NotImplementedError` from deep in the call stack.

4. **LP-16, LP-17:** Add test coverage for:
   - `astream()` on at least one provider with mocked SSE/NDJSON
   - `create_llm_from_config()` with both `api_key` and `api_key_ref` paths
   - `validate_base_url()` SSRF blocking (private IPs, metadata endpoints)

5. **LP-04:** Remove the dead HTTP status code constants from `base.py:93-96`. They are only used in `_base_helpers.py`.

### P2 -- Nice to Have

6. **LP-05, LP-06:** Extract streaming boilerplate into base class template methods to reduce the 6x duplication.

7. **LP-13:** Either wire `LLMConfig` into the factory functions or remove it if it's unused.

8. **LP-09:** Extract `Retry-After` header from 429 responses and use it for backoff calculation.

9. **LP-08:** Add client-side validation for `temperature` (0.0-2.0), `max_tokens` (>0), `timeout` (>0).

10. **LP-21:** Use a module-level `asyncio.Lock()` initialized at import time or a lazy descriptor to avoid the TOCTOU race.
