# Audit 07: LLM Core Module

**Scope:** `temper_ai/llm/` core files (NOT `providers/`, `cache/`, `prompts/`)
**Files reviewed:** 15 files
**Tests reviewed:** 8 test files across `tests/test_llm/`, `tests/test_agent/`
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The LLM core module is well-architected with clean separation of concerns. The `LLMService` class orchestrates the full LLM call lifecycle (retry, tool calling, cost tracking, sliding window) and delegates to focused sub-modules (`_retry`, `_tool_execution`, `_prompt`, `_tracking`, `_schemas`). Security is strong -- tool output sanitization, fail-closed safety validation, and prompt injection defenses are all present. However, there are several notable issues: a **key inconsistency bug** in `_tool_execution.py`, a **dead field** in `_RunState`, a **non-functional shutdown_event** in `_retry.py`, and **significant test coverage gaps** for `_retry.py`, `_prompt.py`, `_tool_execution.py`, and `conversation.py`.

**Overall Grade: B+ (83/100)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 85/100 | Clean decomposition; minor inconsistencies |
| Security | 90/100 | Strong sanitization, fail-closed, path traversal checks |
| Error Handling | 80/100 | Good retry/failover; some gaps in edge cases |
| Modularity | 88/100 | Excellent separation; one coupling issue in `_schemas.py` |
| Feature Completeness | 78/100 | `_summarize` is a stub; `response_format` field unused |
| Test Quality | 72/100 | Good coverage for some files; significant gaps for others |
| Architecture | 85/100 | Well-aligned with modularity/observability pillars |

---

## 1. Code Quality

### 1.1 CRITICAL: Key Inconsistency in `check_safety_mode` (BUG)

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_tool_execution.py:96-112`

The `require_approval` branch (line 97-103) correctly uses `ToolKeys.NAME`, `ToolKeys.PARAMETERS`, etc., but the `require_approval_for_tools` branch (line 106-112) uses **hardcoded string literals** (`"name"`, `"parameters"`, `"result"`, `"error"`, `"success"`):

```python
# Line 97-103: Correct usage
if mode == "require_approval":
    return {
        ToolKeys.NAME: tool_name,        # Uses constant
        ToolKeys.PARAMETERS: tool_params,  # Uses constant
        ToolKeys.RESULT: None,
        ToolKeys.ERROR: f"...",
        ToolKeys.SUCCESS: False,
    }

# Line 106-112: INCONSISTENT - hardcoded strings
if tool_name in require_approval_for_tools:
    return {
        "name": tool_name,           # Should be ToolKeys.NAME
        "parameters": tool_params,    # Should be ToolKeys.PARAMETERS
        "result": None,              # Should be ToolKeys.RESULT
        "error": f"...",             # Should be ToolKeys.ERROR
        "success": False,            # Should be ToolKeys.SUCCESS
    }
```

**Impact:** While `ToolKeys.NAME == "name"` today, this inconsistency is a maintenance hazard. If `ToolKeys` constants are ever changed (e.g., to namespace keys), this branch will silently produce incorrect dict keys, breaking downstream consumers that read tool results using `ToolKeys.*`.

**Fix:** Replace hardcoded strings with `ToolKeys.*` constants at lines 107-111.

### 1.2 MEDIUM: Dead Field `response_format` in `_RunState`

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/service.py:136`

```python
@dataclass
class _RunState:
    ...
    # Structured output: response format pass-through (R0.1)
    response_format: dict[str, Any] | None = None
```

This field is declared but **never read or written** anywhere in `service.py` or any of the sub-modules. The structured output feature (R0.1) uses `output_validation.py` via a different code path. This is dead code.

**Fix:** Remove the field or wire it into `_prepare_run_state` / `_call_with_retry_*` if R0.1 intends to pass `response_format` through to providers.

### 1.3 LOW: Non-functional `shutdown_event` in Sync Retry

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_retry.py:56-58`

```python
shutdown_event = threading.Event()
if shutdown_event.wait(timeout=backoff_delay):
    raise KeyboardInterrupt("Agent execution interrupted")
```

A **new** `threading.Event()` is created on every retry attempt. Since nothing ever `.set()`s this event, `shutdown_event.wait(timeout=backoff_delay)` always returns `False` (times out), and the `KeyboardInterrupt` is never raised. This is functionally equivalent to `time.sleep(backoff_delay)` but with misleading code.

**Impact:** The intended "interruptible wait" pattern is non-functional. To actually support interruption, the event must be shared across the thread boundary (e.g., passed in as a parameter or stored as instance state on `LLMService`).

**Fix:** Either (a) replace with `time.sleep(backoff_delay)` if interruption is not needed, or (b) accept a shared `threading.Event` parameter so external code can signal shutdown.

### 1.4 LOW: `_schemas.py` Hardcoded Provider isinstance Check

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_schemas.py:73`

```python
if not isinstance(llm, (OllamaLLM, OpenAILLM, AnthropicLLM)):
    return None, None
```

This imports concrete provider classes (`AnthropicLLM`, `OllamaLLM`, `OpenAILLM`) directly, creating tight coupling between the schema builder and provider implementations. Adding a new provider with native tool support requires modifying this function.

**Better pattern:** Check for a capability flag like `hasattr(llm, "supports_native_tools")` or a protocol/interface attribute. This would align with the Radical Modularity pillar.

### 1.5 LOW: `pricing.py` Singleton Re-initialization Guard

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/pricing.py:147`

```python
if hasattr(self, "_initialized"):
    return
```

The `hasattr` pattern for singleton initialization is fragile. If `__init__` raises an exception after `_initialized` is set (it is set at line 160, after the body), the singleton is in a half-initialized state and a second `__init__` call will re-run. The current code handles this correctly by setting `_initialized` last, but the `hasattr` pattern is generally discouraged per coding standards (ISSUE-13 deferred).

### 1.6 INFO: Function Lengths and Param Counts

All functions are within the 50-line limit. No function exceeds 7 parameters at the definition site, though `service.py:run()` and `service.py:arun()` have 11 keyword-only params each (mitigated by the `# noqa: params` comment). The `_RunState` dataclass holds 17 fields, which is reasonable for aggregated loop state but approaches complexity limits.

---

## 2. Security

### 2.1 STRONG: Tool Output Sanitization (AG-02)

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/response_parser.py:148-166`

The `sanitize_tool_output` function correctly escapes structural XML tags (`<tool_call>`, `<answer>`, `<reasoning>`, `<thinking>`, `<think>`, `<thought>`) and role delimiters (`Assistant:`, `User:`, `System:`, `Human:`) in tool output before it is injected into prompts. The regex is compiled at module load for performance.

**Verified coverage:** Tests in `tests/test_agent/test_response_parser.py` and `tests/test_agent/test_prompt_injection.py` cover tag escaping, case-insensitive matching, whitespace variants, nested escape attempts, and non-string input.

### 2.2 STRONG: Fail-Closed Safety Validation

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_tracking.py:108-131`

The `validate_safety` function correctly implements fail-closed behavior: if the policy engine raises an exception during validation, the LLM call is blocked (not permitted by default). The error message is sanitized via `sanitize_error_message`.

### 2.3 STRONG: No Tool Executor Fallback Blocked

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_tool_execution.py:232-242`

When no `tool_executor` is provided, tool execution is blocked with a `CRITICAL` log message rather than silently allowing unvalidated execution. This is the correct security posture.

### 2.4 STRONG: Pricing Config Path Traversal Prevention

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/pricing.py:162-185`

The `_validate_config_path` method prevents path traversal by resolving the config path and checking it is relative to the project root. File size is also checked to prevent DoS via oversized YAML files.

### 2.5 MEDIUM: Error Messages May Leak Internal Paths

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/pricing.py:175-177`

```python
raise SecurityError(
    f"Config path outside project: {self.config_path}"
)
```

The full resolved path is included in the error message. In a server context, this could leak internal filesystem structure. The `sanitize_error_message` utility is not applied here.

### 2.6 INFO: Role Delimiter Sanitization Limitation

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/response_parser.py:30`

The role delimiter pattern (`Assistant:`, `User:`, etc.) is matched by `_TOOL_RESULT_SANITIZE_PATTERN` but the replacement only escapes `<` and `>`. Since role delimiters contain no angle brackets, they pass through unmodified. The test at `tests/test_agent/test_response_parser.py:211-215` explicitly documents this as intentional -- the primary defense is XML tag injection prevention.

---

## 3. Error Handling

### 3.1 GOOD: Retry with Exponential Backoff + Jitter

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_retry.py:23-65, 68-108`

Both sync and async retry paths implement exponential backoff with jitter (`retry_delay * 2^attempt * random(0.5..1.5)`). Error messages are sanitized before logging. The retry count and delay are configurable via `inference_config`.

### 3.2 MEDIUM: Only `LLMError` Caught in Retry Loop

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_retry.py:46`

```python
except LLMError as e:
```

The retry loop only catches `LLMError`. If a provider raises `httpx.TimeoutException`, `ConnectionError`, or other transient errors that are not wrapped in `LLMError`, the exception propagates immediately without retry. The `FailoverProvider` (line 141-142) catches a broader set of transient exceptions. The retry module should arguably catch the same set for consistency.

**Impact:** A raw `httpx.ConnectError` from a provider that forgets to wrap it in `LLMError` will not be retried, causing premature failure.

### 3.3 MEDIUM: No Timeout on Individual Tool Execution

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_tool_execution.py:252-285`

The `execute_via_executor` function measures execution time but does not enforce a per-tool timeout. A misbehaving tool could block the entire LLM iteration loop indefinitely. The parallel execution path at line 186 uses `concurrent.futures.as_completed` but also lacks a timeout parameter.

### 3.4 LOW: Failover's `asyncio.Lock` Eager Creation

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/failover.py:99-104`

```python
# NOTE: asyncio.Lock() binds to the running event loop.
self._async_state_lock = asyncio.Lock()
```

The comment acknowledges the risk. On Python 3.10+, `asyncio.Lock()` no longer requires a running event loop at creation time. However, if `FailoverProvider` is instantiated in one event loop and used in another (e.g., during testing), the lock will raise `RuntimeError`. The inline comment documents this constraint.

### 3.5 INFO: Sliding Window Budget Edge Case

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_prompt.py:85-87`

When `budget <= 0` (system prompt alone exceeds `max_prompt_length`), only the most recent turn is included. This is a reasonable degradation strategy, but the most recent turn itself is not truncated, so the returned prompt could still exceed `max_prompt_length`.

---

## 4. Modularity

### 4.1 EXCELLENT: Service Decomposition

The `LLMService` class delegates to 6 focused sub-modules:
- `_retry.py` -- sync/async retry with backoff
- `_tool_execution.py` -- tool dispatch, safety mode, parallel execution
- `_prompt.py` -- prompt injection, sliding window
- `_tracking.py` -- observer tracking, safety validation
- `_schemas.py` -- tool schema building, caching
- `llm_loop_events.py` -- event emission

Each module has a clear single responsibility and exports pure functions. This is a textbook example of the Radical Modularity pillar.

### 4.2 GOOD: `__init__.py` Lazy Import for Circular Dep Avoidance

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/__init__.py:13-20`

The `__getattr__` lazy-import pattern correctly breaks the circular dependency chain documented in the comment. This is the standard pattern used across the codebase.

### 4.3 GOOD: `llm_providers.py` Deprecation Shim

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/llm_providers.py`

The backward-compatibility shim correctly uses `__getattr__` with `DeprecationWarning` to redirect imports to the new `providers/` package. The `_SHIM_EXPORTS` dict clearly maps old names to new locations.

### 4.4 LOW: Import Fan-Out in `service.py`

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/service.py:19-36`

`service.py` imports from 8 modules within `temper_ai.llm.*` plus `temper_ai.shared`. This is at the fan-out limit of 8. The imports are all from the same package though, which is reasonable for an orchestrator module.

---

## 5. Feature Completeness

### 5.1 MEDIUM: `_summarize` Strategy is a Stub

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/context_window.py:97-109`

```python
def _summarize(text: str, target_tokens: int) -> str:
    """Placeholder: truncate with a summary marker.

    Full summarization would require an LLM call; for v1 this simply
    truncates with a descriptive marker.
    """
```

The `summarize` context window strategy is documented as a placeholder. It truncates from the end (identical to `_truncate`) but with a misleading marker `[Content summarized to fit context window]`. Users selecting `strategy="summarize"` get truncation, not summarization.

**Recommendation:** Either implement actual LLM-based summarization or remove the strategy and document that only `truncate` and `sliding_window` are available.

### 5.2 LOW: `response_format` Field Not Wired

As noted in 1.2, the `_RunState.response_format` field exists for R0.1 structured output but is never read. The actual structured output path goes through `output_validation.py` at the agent level. This suggests an incomplete integration.

### 5.3 INFO: `conversation.py` Lacks Thread Safety

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/conversation.py`

`ConversationHistory` is a mutable dataclass with no locking. If used concurrently (e.g., in a multi-agent workflow where the same stage:agent pair is re-invoked in parallel), `append_turn` and `_apply_turn_limit` could corrupt the message list. This is likely not an issue in practice since conversation history is scoped per workflow run, but it is worth noting.

---

## 6. Test Quality

### 6.1 Coverage Map

| File | Dedicated Test File | Coverage |
|------|-------------------|----------|
| `service.py` | `tests/test_llm/test_service_observability.py` | Moderate -- iteration events tested; core run/arun logic tested via mocks |
| `pricing.py` | `tests/test_agent/test_pricing.py` | Strong -- 25+ tests covering singleton, security, validation |
| `failover.py` | `tests/test_llm/test_failover_tracking.py`, `tests/test_agent/test_failover_thread_safety.py` | Good -- sequence tracking and thread safety |
| `response_parser.py` | `tests/test_agent/test_response_parser.py` | Strong -- 30+ tests covering all parse paths |
| `context_window.py` | `tests/test_llm/test_context_window.py` | Good -- all strategies and edge cases |
| `output_validation.py` | `tests/test_llm/test_output_validation.py` | Good -- schema validation, retry prompts |
| `cost_estimator.py` | `tests/test_agent/test_cost_estimator.py` | Good -- split tokens, fallback model |
| `llm_loop_events.py` | `tests/test_observability/test_llm_loop_events.py` | Strong -- all event types, error handling |
| **`_retry.py`** | **No dedicated tests** | **GAP -- only tested indirectly via service mocks** |
| **`_prompt.py`** | **No dedicated tests** | **GAP -- only `inject_results` tested via `test_prompt_injection.py`** |
| **`_tool_execution.py`** | **No dedicated tests** | **GAP -- tested indirectly via integration tests** |
| **`_tracking.py`** | **No dedicated tests** | **GAP -- tested indirectly via service mocks** |
| **`_schemas.py`** | **No dedicated tests** | **GAP -- tested indirectly via service mocks** |
| **`conversation.py`** | **No dedicated tests** | **GAP -- only referenced in M9 context helper tests** |
| `constants.py` | N/A (constants only) | N/A |
| `tool_keys.py` | N/A (constants only) | N/A |

### 6.2 CRITICAL: No Unit Tests for `_retry.py`

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_retry.py`

This module handles retry with exponential backoff, error sanitization, and the (non-functional) shutdown event. There are zero dedicated unit tests. The only indirect coverage is through `test_service_observability.py` which patches `call_with_retry_sync` entirely, testing none of its internal logic.

**Missing test cases:**
- Successful call on first attempt
- Retry on `LLMError` with configurable `max_retries`
- Exponential backoff delay calculation
- Error sanitization in log messages
- Async retry path
- Non-`LLMError` exceptions not caught

### 6.3 CRITICAL: No Unit Tests for `_tool_execution.py`

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/_tool_execution.py`

This module handles safety mode checks, serial/parallel tool execution, thread pool management, and input validation. There are zero dedicated unit tests.

**Missing test cases:**
- `validate_tool_calls_input` with non-list, non-dict inputs
- `check_safety_mode` for all three modes (`require_approval`, `require_approval_for_tools`, `dry_run`)
- `execute_tools` serial vs parallel paths
- `_execute_parallel` error handling
- `execute_single_tool` missing name/params validation
- `execute_via_executor` success/failure tracking

### 6.4 MEDIUM: No Unit Tests for `conversation.py`

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/llm/conversation.py`

No tests for `ConversationHistory.append_turn`, `to_message_list`, `to_dict`, `from_dict`, or the turn limit trimming logic.

### 6.5 MEDIUM: `test_circuit_breaker_race.py` Tests Wrong Module

**File:** `/home/shinelay/meta-autonomous-framework/tests/test_llm/test_circuit_breaker_race.py`

This test file is in `tests/test_llm/` but tests `temper_ai.shared.core.circuit_breaker`, not any file in `temper_ai.llm/`. It should be moved to `tests/test_shared/test_core/`.

### 6.6 LOW: Mock-Heavy Service Tests

**File:** `/home/shinelay/meta-autonomous-framework/tests/test_llm/test_service_observability.py:85-161`

The `TestLLMServiceIterationEvents` class patches 4-9 functions per test. While this isolates the iteration event emission, it means the actual `run()` orchestration logic (state management, tool loop termination, error handling) is not tested with real sub-module behavior. No integration-level tests exercise `LLMService.run()` end-to-end with real (or minimally-mocked) sub-modules.

---

## 7. Architectural Alignment

### 7.1 Radical Modularity: GOOD

The decomposition of `LLMService` into 6 sub-modules with pure-function interfaces is exemplary. Each module can be tested, replaced, or extended independently. The `ToolKeys` constants class ensures dictionary key consistency (modulo the bug in 1.1).

### 7.2 Configuration as Product: MODERATE

- **Pricing:** Fully configurable via `config/model_pricing.yaml` with Pydantic validation, schema versioning, and runtime hot-reloading. This is best-in-class.
- **Retry/Timeout:** Configurable via `InferenceConfig` (max_retries, retry_delay_seconds). Good.
- **Context Window:** `DEFAULT_MODEL_CONTEXT = 128000` is hardcoded. Should be per-model configurable.
- **Tool Pool Size:** Configurable via `AGENT_TOOL_WORKERS` env var. Good.
- **Summarize Strategy:** Not configurable (stub). Gap.

### 7.3 Observability: STRONG

- Per-iteration events via `LLMIterationEventData` emitted to observer
- Cache events via `CacheEventData` with opt-in callback
- Successful/failed LLM calls tracked with full metadata (provider, model, tokens, cost, latency)
- Structured logging at appropriate levels (INFO for iteration events, DEBUG for cache events, WARNING for failures)
- Safety validation logged at WARNING level with fail-closed semantics

---

## 8. Findings Summary

### Critical (Fix Required)

| # | Finding | File:Line | Impact |
|---|---------|-----------|--------|
| C1 | Key inconsistency in `check_safety_mode` -- hardcoded strings vs ToolKeys constants | `_tool_execution.py:106-112` | Maintenance hazard; will break if ToolKeys values change |
| C2 | No unit tests for `_retry.py` (retry backoff logic untested) | `tests/test_llm/` | Regression risk for core retry behavior |
| C3 | No unit tests for `_tool_execution.py` (safety mode, parallel execution untested) | `tests/test_llm/` | Regression risk for tool execution safety |

### High (Should Fix)

| # | Finding | File:Line | Impact |
|---|---------|-----------|--------|
| H1 | Non-functional `shutdown_event` in sync retry -- new Event per attempt, never set | `_retry.py:56-58` | Dead code; misleading; interruptible wait does not work |
| H2 | Only `LLMError` caught in retry loop -- transient httpx errors not retried | `_retry.py:46` | Premature failure if provider does not wrap errors |
| H3 | No unit tests for `conversation.py` | `tests/test_llm/` | Turn trimming logic untested |

### Medium (Consider Fixing)

| # | Finding | File:Line | Impact |
|---|---------|-----------|--------|
| M1 | Dead `response_format` field in `_RunState` | `service.py:136` | Dead code; incomplete R0.1 integration |
| M2 | `_summarize` strategy is a truncation stub | `context_window.py:97-109` | Misleading; users expect summarization |
| M3 | `_schemas.py` hardcodes isinstance check for 3 providers | `_schemas.py:73` | Tight coupling; adding providers requires modifying |
| M4 | Error message in pricing.py leaks filesystem path | `pricing.py:175-177` | Potential info disclosure in server context |
| M5 | `test_circuit_breaker_race.py` mislocated in `tests/test_llm/` | `tests/test_llm/` | Organizational issue |
| M6 | No per-tool execution timeout | `_tool_execution.py:252-285` | Misbehaving tool can block LLM loop indefinitely |
| M7 | Sliding window does not truncate the final turn when budget <= 0 | `_prompt.py:85-87` | Prompt may exceed max_prompt_length |

### Low (Nice to Have)

| # | Finding | File:Line | Impact |
|---|---------|-----------|--------|
| L1 | No unit tests for `_tracking.py` or `_schemas.py` | `tests/test_llm/` | Indirect-only coverage |
| L2 | `conversation.py` not thread-safe | `conversation.py` | Unlikely issue in practice |
| L3 | `pricing.py` hasattr singleton guard | `pricing.py:147` | Fragile pattern (deferred ISSUE-13) |
| L4 | `pricing.py` TOKENS_PER_MILLION duplicated in constants.py | `pricing.py:30` vs `constants.py:66` | Two definitions of the same constant |

---

## 9. Recommended Actions (Priority Order)

1. **Fix C1:** Replace hardcoded dict keys in `check_safety_mode` with `ToolKeys.*` constants (5 min)
2. **Fix H1:** Replace non-functional `shutdown_event` with `time.sleep()` or accept a shared event (10 min)
3. **Fix C2+C3:** Write dedicated unit tests for `_retry.py` and `_tool_execution.py` (2-3 hours)
4. **Fix M1:** Remove dead `response_format` field from `_RunState` or wire it in (10 min)
5. **Fix H2:** Broaden retry catch clause to include transient httpx exceptions (15 min)
6. **Fix M5:** Move `test_circuit_breaker_race.py` to `tests/test_shared/test_core/` (5 min)
7. **Fix H3:** Write unit tests for `conversation.py` (1 hour)
8. **Fix M3:** Replace isinstance check in `_schemas.py` with capability flag (30 min)
9. **Fix M2:** Either implement real summarization or remove the `summarize` strategy (depends on scope)
10. **Fix M6:** Add configurable per-tool timeout to `execute_via_executor` (1 hour)
