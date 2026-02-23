# Audit 13: Safety Detection and Limits Modules

**Auditor:** Claude Opus 4.6
**Date:** 2026-02-22
**Scope:** `temper_ai/safety/` -- detection, pattern matching, rate limiting, and limits modules
**Files Reviewed:** 24 source files, 6 test directories

---

## Executive Summary

The safety detection and limits subsystem is **mature and well-structured**, with strong input validation, ReDoS protection, and comprehensive test coverage. The codebase follows defensive programming principles throughout. However, the audit identified **3 security vulnerabilities** (1 critical, 2 medium), **2 documented security gaps** (SSRF, SQL injection), and **several code quality items**. The architecture adheres to the "Safety Through Composition" pillar with clean separation between detection, filtering, and policy enforcement layers.

**Overall Rating: B+ (81/100)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 85 | Clean extraction pattern, good constant use, minor items |
| Security | 72 | Known null-byte bypass, missing SQL/SSRF policies, strong ReDoS defense |
| Error Handling | 88 | Graceful degradation, fail-closed defaults, good exception specificity |
| Modularity | 90 | Excellent helper extraction, PatternConfig dataclass, composable design |
| Feature Completeness | 75 | Documented gaps: SSRF, SQL injection, limited injection patterns |
| Test Quality | 82 | 100+ tests, bypass coverage, but known vulns documented-not-fixed |
| Architecture | 88 | Composition model, centralized patterns, clean layering |

---

## 1. Code Quality

### 1.1 Function Length Compliance (>50 lines)

All functions across all 24 files comply with the 50-line limit. The extraction pattern (main class + `_helpers.py`) keeps logic well-decomposed.

**Clean examples:**
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/file_access.py:294-334` -- `_validate_impl` is 40 lines
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/rollback.py:358-398` -- `FileRollbackStrategy.create_snapshot` is 40 lines
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/forbidden_operations.py:302-323` -- `_check_all_patterns` is 21 lines

### 1.2 Parameter Count Compliance (>7 params)

All public APIs comply. The `FileSizeCheckParams` dataclass pattern at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/policies/_resource_limit_helpers.py:28-41` is a good example of bundling parameters to reduce signature size.

### 1.3 Naming and Constants

**Good:** Constants are extracted to `/home/shinelay/meta-autonomous-framework/temper_ai/safety/constants.py` (213 lines) with clear categories and `# scanner: skip-magic` annotations where needed.

**Issue -- Inconsistent priority values across constants.py vs module-level:**

| File | Priority | constants.py Value |
|------|----------|--------------------|
| `file_access.py:57` | `FILE_ACCESS_PRIORITY = 95` | `constants.py:16`: `FILE_ACCESS_PRIORITY = 80` |
| `forbidden_operations.py:47` | `FORBIDDEN_OPS_PRIORITY = 200` | `constants.py:15`: `FORBIDDEN_OPS_PRIORITY = 90` |
| `blast_radius.py:38` | `BLAST_RADIUS_PRIORITY = 90` | `constants.py:17`: `BLAST_RADIUS_PRIORITY = 70` |

**Finding [CQ-1] MEDIUM:** Priority constants are duplicated in both `constants.py` and individual module files with **different values**. `file_access.py` imports from `constants.py` but also re-defines its own constant at line 57. `forbidden_operations.py:47` defines `FORBIDDEN_OPS_PRIORITY = 200` which shadows the `constants.py` value of 90. The modules use their local values, not the centralized constants. This creates confusion about actual execution order.

**Recommendation:** Remove module-level priority constants and import exclusively from `constants.py`, or update `constants.py` to match the actual module values.

### 1.4 Dead Code

**Finding [CQ-2] LOW:** `ForbiddenOperationsPolicy.validate()` at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/forbidden_operations.py:254-300` overrides `BaseSafetyPolicy.validate()` directly instead of implementing `_validate_impl()`. This bypasses the child policy composition chain from `BaseSafetyPolicy.validate()`. All other policies use the `_validate_impl()` pattern correctly.

**Recommendation:** Refactor `ForbiddenOperationsPolicy.validate()` to `_validate_impl()` to restore composition support, or document this as intentional.

### 1.5 Module Fan-out

All modules stay well within the <8 fan-out limit. The helper extraction pattern keeps imports focused.

---

## 2. Security Analysis

### 2.1 Critical: Null Byte Path Injection (EXISTING, DOCUMENTED)

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/_file_access_helpers.py`
**Test:** `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_security_bypasses.py:146-181`

**Description:** Null bytes embedded in path components (`/etc\x00/passwd`) can bypass forbidden directory/file checks. The `normalize_path()` function at `_file_access_helpers.py:137-168` does not strip null bytes before normalization. `os.path.normpath()` may truncate at null bytes on some platforms, causing the forbidden directory check to see a truncated path.

**Current state:** The test at line 165-174 explicitly documents this as a known vulnerability with `pytest.skip()`.

**Impact:** An attacker can bypass file access restrictions by embedding null bytes in path arguments.

**Recommendation:** Add null byte stripping to `normalize_path()`:
```python
# Strip null bytes before any processing
path = path.replace("\x00", "")
```

### 2.2 Medium: Incomplete Command Injection Detection

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/_forbidden_ops_helpers.py`
**Test:** `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_security_bypasses.py:501-563`

Three documented bypass vectors are not detected:

| Vector | Pattern | Why Missed |
|--------|---------|------------|
| `echo test \| bash` | Pipe to shell | `pipe_injection` pattern requires `> ` after pipe |
| `` echo `whoami` `` | Backtick execution | `backtick_execution` only matches rm/mv/curl inside backticks |
| `echo $(whoami)` | Subshell execution | `subshell_injection` only matches rm/mv/curl inside `$()` |

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/_forbidden_ops_helpers.py:144-164`

The injection patterns at lines 144-164 are limited to detecting only `rm`, `mv`, `curl`, and `chmod`/`wget` inside injection contexts. Arbitrary command execution via `whoami`, `id`, `cat`, `nc`, `python`, etc. is not detected.

**Recommendation:** Expand the injection pattern command list:
```python
# Current (line 146):
r";.{0,500}(\brm\b|\bmv\b|\bchmod\b|\bwget\b|\bcurl\b)"
# Recommended:
r";.{0,500}(\brm\b|\bmv\b|\bchmod\b|\bwget\b|\bcurl\b|\bbash\b|\bsh\b|\bpython\b|\bnc\b|\bnetcat\b|\bwhoami\b|\bid\b)"
```

Also add pipe-to-shell detection:
```python
"pipe_to_shell": {
    VIOLATION_PATTERN: r"\|\s*(bash|sh|zsh|python|perl|ruby|node)\b",
    ...
}
```

### 2.3 Medium: SecurityViolation.timestamp Uses Naive datetime

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/safety/security/llm_security.py:83`

```python
timestamp: datetime = field(default_factory=datetime.now)
```

This uses `datetime.now()` without timezone, violating the project coding standard: "datetime.now(timezone.utc) not datetime.utcnow()".

**Recommendation:** Change to `datetime.now(UTC)` with `from datetime import UTC`.

### 2.4 Documented Security Gaps (No Policy Coverage)

**SSRF Protection:** Documented at `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_security_bypasses.py:371-403`. No policy blocks requests to internal IPs (127.0.0.1, 10.0.0.0/8, 169.254.169.254, etc.). The test suite skips 10 SSRF bypass tests.

**SQL Injection Detection:** Documented at `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_security_bypasses.py:300-364`. No policy detects SQL injection patterns (comment obfuscation, encoding bypasses, time-based blind injection). The test suite skips 15 SQL injection tests.

**Assessment:** These are reasonable scope boundaries for the current framework -- SSRF and SQL injection are typically handled at the application layer, not at the agent safety policy layer. However, if agents can issue arbitrary HTTP requests or database queries, these become relevant.

---

## 3. ReDoS Protection Assessment

The codebase demonstrates **excellent ReDoS awareness**. Every regex pattern uses bounded quantifiers.

### 3.1 Pattern Audit (All Bounded)

**Secret patterns** (`/home/shinelay/meta-autonomous-framework/temper_ai/shared/utils/secret_patterns.py`):
- All use `{min,max}` quantifiers (e.g., `[a-zA-Z0-9]{20,200}`)
- JWT pattern bounded to `{1,2000}` per segment

**Forbidden ops patterns** (`/home/shinelay/meta-autonomous-framework/temper_ai/safety/_forbidden_ops_helpers.py`):
- `echo_redirect` uses `.{0,200}` instead of `.*`
- `ssh_no_check` uses `.{0,200}` for intermediate content
- `semicolon_injection` uses `.{0,500}` bounded match

**Prompt injection patterns** (`/home/shinelay/meta-autonomous-framework/temper_ai/safety/security/llm_security.py:122-168`):
- Comment: "ReDoS-safe - no nested quantifiers"
- `MAX_INPUT_LENGTH = 100KB` prevents DoS on pattern matching
- `MAX_ENTROPY_LENGTH = 10KB` prevents memory exhaustion

### 3.2 ReDoS Test Coverage

Dedicated test files:
- `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_llm_security_redos.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_redos_secret_detection.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_redos_redirect_fix.py`

### 3.3 Custom Pattern Validation

Custom forbidden patterns undergo ReDoS testing at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/forbidden_operations.py:158-168`:
```python
self._validate_regex_pattern(
    pattern,
    f"{CUSTOM_FORBIDDEN_PATTERNS_PREFIX}{name}']",
    max_length=MAX_EXCLUDED_PATH_LENGTH,
    test_timeout=PROB_VERY_LOW  # 0.1s
)
```

The `_validate_regex_pattern` method at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/validation.py:379-460` tests each pattern against adversarial inputs with a 100ms timeout.

---

## 4. Error Handling

### 4.1 Fail-Closed Defaults

**Good pattern -- rollback path validation** at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/rollback.py:141`:
```python
except Exception as e:  # noqa: BLE001 -- fail-closed top-level handler
    logger.error(f"Path validation error for {file_path}: {e}")
    return False, f"Path validation failed: {str(e)}"
```

All path validation failures result in denial (fail-closed), which is the correct security posture.

### 4.2 TOCTOU Protection

**Rollback file operations** at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/rollback.py:477-479`:
```python
# Re-validate path immediately before I/O (TOCTOU protection)
recheck_valid, recheck_err = validate_rollback_path(file_path)
```

The double-validation pattern (validate before snapshot, re-validate before write) mitigates TOCTOU races.

**Rate limiter** at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/security/llm_security.py:517-599`:
```python
def check_and_record_rate_limit(self, entity_id: str) -> tuple[bool, str | None]:
    """ATOMIC: Check and record rate limit in a single operation."""
```

The atomic check-and-record pattern prevents concurrent bypass of rate limits.

### 4.3 Graceful Degradation

**Resource monitoring** at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/policies/_resource_limit_helpers.py:269-270`:
```python
except (psutil.Error, OSError):
    return None
```

When `psutil` fails (e.g., in containerized environments), the policy returns `None` (no violation) rather than crashing. This is an acceptable tradeoff -- a crash would be worse than missing one check.

### 4.4 Missing Error Handling

**Finding [EH-1] LOW:** `WindowRateLimitPolicy.__init__()` at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/rate_limiter.py:97-113` does not validate its config inputs:
```python
self.limits = self.config.get("limits", self.DEFAULT_LIMITS)
self.strategy = self.config.get("strategy", "sliding_window")
self.burst_allowance = self.config.get("burst_allowance", BURST_ALLOWANCE_DEFAULT)
```

Unlike `TokenBucketRateLimitPolicy` which validates every config field, `WindowRateLimitPolicy` accepts any type without validation. A non-dict `limits` value would cause runtime errors later.

**Recommendation:** Add type validation in `__init__` to match the validation pattern used by other policies.

---

## 5. Modularity Analysis

### 5.1 Pattern Extraction (Excellent)

The codebase uses a consistent pattern:
```
policy.py          -- Public API, < 500 lines
_helpers.py        -- Extracted logic, pure functions
_pattern_config.py -- Dataclasses for parameter bundling
```

Examples:
| Policy | Main File | Helper File | Pattern Config |
|--------|-----------|-------------|----------------|
| FileAccess | `file_access.py` (472 lines) | `_file_access_helpers.py` (329 lines) | N/A |
| ForbiddenOps | `forbidden_operations.py` (403 lines) | `_forbidden_ops_helpers.py` (378 lines) | `_forbidden_ops_pattern_config.py` (23 lines) |
| SecretDetection | `secret_detection.py` (294 lines) | `_secret_detection_helpers.py` (87 lines) | N/A |
| RateLimit | `rate_limit_policy.py` (347 lines) | `_rate_limit_helpers.py` (89 lines) | N/A |
| ResourceLimit | `resource_limit_policy.py` (358 lines) | `_resource_limit_helpers.py` (368 lines) | N/A |

### 5.2 Centralized Pattern Registry (Excellent)

All secret patterns are defined in a single location:
`/home/shinelay/meta-autonomous-framework/temper_ai/shared/utils/secret_patterns.py`

Consumers: `SecretDetectionPolicy`, `OutputSanitizer`, `DataSanitizer`, `detect_secret_patterns()`, log redaction, config display redaction. The comment at the top documents all consumers.

### 5.3 Composable Architecture

The `BaseSafetyPolicy` -> `_validate_impl()` pattern at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/base.py:256-298` enables:
- Child policy composition via `add_child_policy()`
- Priority-ordered execution
- Short-circuit on CRITICAL violations
- Async support via `_validate_async_impl()`

### 5.4 Pattern Extensibility

**Good:** Custom forbidden patterns are supported at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/forbidden_operations.py:74`:
```python
custom_patterns_raw = config.pop("custom_forbidden_patterns", {})
```

These are compiled at init time with ReDoS validation, making pattern extension safe and fast.

### 5.5 Duplicate Entropy Calculation

**Finding [MOD-1] LOW:** Shannon entropy calculation is implemented in three places:
1. `/home/shinelay/meta-autonomous-framework/temper_ai/safety/entropy_analyzer.py:25-58` -- `EntropyAnalyzer.calculate()`
2. `/home/shinelay/meta-autonomous-framework/temper_ai/safety/security/llm_security.py:251-269` -- `PromptInjectionDetector._calculate_entropy()`
3. Both use identical algorithms

**Recommendation:** `PromptInjectionDetector` should delegate to `EntropyAnalyzer.calculate()` instead of reimplementing the same algorithm.

---

## 6. Feature Completeness

### 6.1 TODO/FIXME/HACK Items

No TODO/FIXME/HACK markers found in any of the 24 source files in scope. All known gaps are documented in test files instead, which is a better practice.

### 6.2 Test File Documentation of Gaps

The test suite at `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_security_bypasses.py` documents gaps via `pytest.skip()`:

| Gap | Tests Skipped | Severity |
|-----|---------------|----------|
| SQL injection detection | 15 | Medium (not in scope for agent safety) |
| SSRF protection | 10 | Medium (not in scope for agent safety) |
| DNS rebinding | 2 | Low (requires runtime DNS resolution) |

### 6.3 Test Secret Filter Completeness

`/home/shinelay/meta-autonomous-framework/temper_ai/safety/test_secret_filter.py:22-57`

The filter covers 27 keywords and 5 patterns. Notably:
- "dev" and "local" keywords may cause false negatives for development API keys that happen to contain "dev" in the key name
- The function call filter at line 118-119 (`"(" in text and ")" in text`) could suppress detection of secrets that coincidentally contain parentheses

**Finding [FC-1] LOW:** The function call heuristic at line 118-119 is overly broad. A secret value like `sk-proj-abc(123)def456` would be incorrectly filtered out.

### 6.4 Rate Limiting Architecture

The system provides **three complementary rate limiting mechanisms**:

1. **Window-based** (`rate_limiter.py`) -- Sliding window with per-entity tracking, thread-safe, history cleanup
2. **Token bucket** (`token_bucket.py`) -- Classic algorithm with burst support, LRU eviction in manager
3. **LLM-specific** (`security/llm_security.py`) -- Multi-tier (minute/hour/burst) with entity normalization

**Finding [FC-2] INFO:** Three rate limiting implementations exist. While each serves a different use case, this creates maintenance burden. The `LLMSecurityRateLimiter` could potentially be replaced by a configured `TokenBucketRateLimitPolicy` with multi-tier buckets.

---

## 7. Test Quality

### 7.1 Test Coverage Summary

| Module | Test File | Approx Tests | Bypass Tests |
|--------|-----------|--------------|--------------|
| FileAccess | `test_file_access.py` | 50+ | Yes (via test_security_bypasses.py) |
| ForbiddenOps | `test_forbidden_operations.py` | 25+ | Yes (via test_security_bypasses.py) |
| SecretDetection | `test_secret_detection.py` | 85+ | Yes (test_redos_secret_detection.py) |
| BlastRadius | `test_blast_radius.py` | 15+ | No |
| CircuitBreaker | `test_circuit_breaker.py` | 20+ | No |
| RateLimit | `test_rate_limiter.py` | 20+ | Yes (test_distributed_rate_limiting.py) |
| TokenBucket | `test_token_bucket.py` | 15+ | No |
| Rollback | `test_rollback.py`, `test_rollback_api.py` | 30+ | No |
| LLM Security | `test_llm_security.py`, `test_llm_security_extended.py`, `test_llm_security_redos.py` | 50+ | Yes |
| Bypass Tests | `test_security_bypasses.py` | 50+ | Yes (primary) |
| URL Encoding | `test_url_encoding_bypasses.py` | 20+ | Yes |
| Unicode | `test_unicode_normalization_bypasses.py` | 20+ | Yes |
| Prompt Injection | `test_prompt_injection.py` | 25+ | Yes |

### 7.2 Bypass Test Coverage (Strength)

The dedicated bypass test file at `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_security_bypasses.py` is excellent:
- 50+ parameterized test cases
- Path traversal: URL encoding, Unicode, null bytes, mixed separators
- Command injection: Whitespace variants, quote manipulation
- Performance: <5ms per validation target
- Comprehensive blocking verification with specific pattern matching

### 7.3 Test Gap: PromptInjectionPolicy Integration

**Finding [TQ-1] MEDIUM:** `PromptInjectionPolicy` at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/prompt_injection_policy.py` does not have a dedicated unit test file. It is tested indirectly through `test_prompt_injection.py` which tests the underlying `PromptInjectionDetector`, but the policy wrapper (severity mapping, prompt extraction from nested action dicts) lacks direct coverage.

### 7.4 Test Gap: Rollback TOCTOU

**Finding [TQ-2] LOW:** The TOCTOU double-validation in `FileRollbackStrategy._restore_file_atomically()` is not explicitly tested. A test that validates the second `validate_rollback_path()` call at line 478 catches a path that becomes invalid between the first and second check would increase confidence.

---

## 8. Architecture Assessment

### 8.1 Composition Model (Excellent)

The safety subsystem follows a clean composition architecture:

```
PolicyRegistry
  -> PolicyComposer (ordered execution)
    -> BaseSafetyPolicy (composition + short-circuit)
      -> _validate_impl() (specific logic)
        -> helpers (extracted pure functions)
```

This aligns perfectly with the "Safety Through Composition" vision pillar.

### 8.2 Layered Detection

Detection follows a proper layered approach:

```
Layer 1: Input normalization (URL decode, Unicode NFKC, path normalization)
Layer 2: Pattern matching (regex with ReDoS protection)
Layer 3: Entropy analysis (Shannon entropy for secret confidence)
Layer 4: Test/placeholder filtering (reduce false positives)
Layer 5: Severity classification (pattern-based + entropy-based)
Layer 6: Redaction (HMAC-based hashing, never log secrets)
```

### 8.3 Thread Safety

All rate limiters and circuit breakers use proper synchronization:
- `TokenBucket` uses `threading.Lock` with `@requires_lock` decorator
- `CircuitBreakerManager` uses `threading.Lock` for CRUD operations
- `WindowRateLimitPolicy` uses `threading.Lock` for history access
- `LLMSecurityRateLimiter` uses `Lock` for atomic check-and-record

The `@requires_lock` decorator at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/token_bucket.py:69-104` is a creative enforcement mechanism that raises `RuntimeError` if a method is called without holding the lock.

### 8.4 Information Leakage Prevention

- `create_redacted_preview()` at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/redaction_utils.py:14-35` never exposes secret values
- `hash_secret()` uses session-scoped HMAC-SHA256 for deduplication without storing secrets
- `_sanitize_context()` at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/secret_detection.py:175-179` sanitizes context before logging
- `MAX_EVIDENCE_LENGTH` at `/home/shinelay/meta-autonomous-framework/temper_ai/safety/security/llm_security.py:116` truncates evidence in violation reports

---

## 9. Findings Summary

### Critical (P0)

| ID | Finding | File | Line | Impact |
|----|---------|------|------|--------|
| SEC-1 | Null byte path injection bypass | `_file_access_helpers.py` | `normalize_path()` | Bypasses file access restrictions |

### Medium (P1)

| ID | Finding | File | Line | Impact |
|----|---------|------|------|--------|
| SEC-2 | Incomplete command injection detection (3 vectors) | `_forbidden_ops_helpers.py` | 144-164 | Arbitrary command execution via backtick/subshell/pipe |
| SEC-3 | Naive datetime in SecurityViolation | `llm_security.py` | 83 | Coding standard violation, potential timezone issues |
| CQ-1 | Priority constant duplication with conflicting values | `constants.py` / module files | Multiple | Confusing policy execution order |
| TQ-1 | Missing PromptInjectionPolicy unit tests | N/A | N/A | Integration-only coverage |

### Low (P2)

| ID | Finding | File | Line | Impact |
|----|---------|------|------|--------|
| CQ-2 | ForbiddenOperationsPolicy bypasses composition chain | `forbidden_operations.py` | 254 | Cannot use child policies |
| EH-1 | WindowRateLimitPolicy missing config validation | `rate_limiter.py` | 97-113 | Runtime errors on bad config |
| MOD-1 | Duplicate entropy calculation (EntropyAnalyzer vs PromptInjectionDetector) | `llm_security.py` | 251 | Maintenance burden |
| FC-1 | Overly broad function call heuristic in test filter | `test_secret_filter.py` | 118-119 | Possible false negatives |
| TQ-2 | Missing TOCTOU rollback test | `rollback.py` | 477-479 | Low confidence in race protection |

### Informational

| ID | Finding | Notes |
|----|---------|-------|
| FC-2 | Three rate limiting implementations | Consider consolidation long-term |
| GAP-1 | No SSRF protection policy | Documented in tests, acceptable scope boundary |
| GAP-2 | No SQL injection detection policy | Documented in tests, acceptable scope boundary |

---

## 10. Recommendations (Prioritized)

### Immediate (P0)

1. **Fix null byte bypass** in `_file_access_helpers.py:normalize_path()` -- add `path = path.replace("\x00", "")` as the first normalization step. This is a single-line fix that closes a documented vulnerability.

### Short-term (P1)

2. **Expand injection patterns** in `_forbidden_ops_helpers.py` -- add `bash|sh|python|nc|whoami|id` to injection command lists and add a `pipe_to_shell` pattern.

3. **Fix SecurityViolation timestamp** -- change `datetime.now` to `datetime.now(UTC)`.

4. **Reconcile priority constants** -- remove module-level duplicates and import from `constants.py` exclusively, updating `constants.py` values to match actual desired priorities.

### Medium-term (P2)

5. **Add PromptInjectionPolicy unit tests** -- test severity mapping, nested action dict extraction, and edge cases.

6. **Refactor ForbiddenOperationsPolicy** to use `_validate_impl()` instead of overriding `validate()` directly.

7. **Consolidate entropy calculation** -- `PromptInjectionDetector._calculate_entropy()` should delegate to `EntropyAnalyzer.calculate()`.

8. **Add config validation to WindowRateLimitPolicy** -- validate `limits`, `strategy`, and `burst_allowance` types.

---

## Appendix: Files Reviewed

### Source Files (24)
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/file_access.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/_file_access_helpers.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/forbidden_operations.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/_forbidden_ops_helpers.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/_forbidden_ops_pattern_config.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/secret_detection.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/_secret_detection_helpers.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/pattern_matcher.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/blast_radius.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/circuit_breaker.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/rate_limiter.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/token_bucket.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/prompt_injection_policy.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/entropy_analyzer.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/redaction_utils.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/rollback.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/rollback_api.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/test_secret_filter.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/security/llm_security.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/policies/rate_limit_policy.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/policies/_rate_limit_helpers.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/policies/resource_limit_policy.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/policies/_resource_limit_helpers.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/constants.py`

### Supporting Files
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/base.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/validation.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/safety/security/constants.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/shared/utils/secret_patterns.py`

### Test Files Reviewed
- `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_security/test_security_bypasses.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_file_access.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_safety/test_secret_detection.py`
- Plus 60+ additional test files in `tests/test_safety/`
