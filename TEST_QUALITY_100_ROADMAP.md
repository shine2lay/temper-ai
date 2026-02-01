# Test Quality 100% Roadmap

**Date:** 2026-01-31
**Current Quality:** 90% (66.4% line coverage)
**Target Quality:** 98-100% (production-ready)
**Gap:** 33.5% quality improvement needed

**Summary:** Comprehensive audit found **8,200 LOC of new tests needed** + **687 test fixes** across 4 priority levels.

---

## Executive Summary

### Critical Findings

**🔴 P0 - BLOCKING PRODUCTION (Must Fix Now)**
- **3 security modules with 0% coverage** (datetime_utils, validation, service)
- **Missing chaos/fault injection testing** (no fault recovery tests)
- **Missing distributed system tests** (race conditions not tested)
- **Race condition bugs in tests** (assert <= instead of ==)
- **131 flaky tests** (time.sleep dependencies)

**🟡 P1 - High Priority (Fix This Sprint)**
- 2 modules with <50% coverage (checkpoint_backends, sql_backend)
- No performance regression testing
- No data migration testing
- Incomplete error propagation testing
- Weak assertions (generic instead of specific)

**Impact:** Fixing P0+P1 gaps → **90% → 98%+ quality**

---

## Priority Breakdown

### P0 - Critical (17% Impact) - TARGET: 2 WEEKS

| Gap | Tests | LOC | Impact | Files |
|-----|-------|-----|--------|-------|
| **Zero-coverage modules** | 170 | 1700 | 7% | 3 new test files |
| **Chaos/fault injection** | 80 | 1000 | 3% | 1 new directory |
| **Distributed tests** | 60 | 800 | 3% | Expand existing |
| **E2E workflows** | 30 | 500 | 2% | Expand existing |
| **Race condition fixes** | 50 | - | 2% | Fix 50 tests |
| **TOTAL P0** | **390** | **4000** | **17%** | - |

### P1 - High Priority (12.5% Impact) - TARGET: 1 MONTH

| Gap | Tests | LOC | Impact |
|-----|-------|-----|--------|
| Low-coverage modules | 70 | 900 | 2.5% |
| Performance regression | 50 | 600 | 2% |
| Data migration | 40 | 500 | 1% |
| Error propagation | 20 | 300 | 1.5% |
| Tool safety integration | 25 | 400 | 1% |
| Exception handling | 100 | 800 | 1.5% |
| Timeout scenarios | 20 | 300 | 1% |
| Flaky test fixes | 100 | - | 2% |
| **TOTAL P1** | **425** | **3800** | **12.5%** |

### P2 - Medium Priority (3% Impact) - TARGET: NEXT QUARTER

| Gap | Items | Impact |
|-----|-------|--------|
| Weak assertion fixes | 150 | 1% |
| Test independence fixes | 50 | 0.5% |
| Error message validation | 200 | 0.5% |
| State machine coverage | 30 | 0.5% |
| Test infrastructure | - | 0.5% |
| **TOTAL P2** | **430** | **3%** |

---

## Critical Path to Production (P0)

### Week 1: Zero-Coverage Modules (7% Impact)

#### Day 1-2: datetime_utils.py (2%)
**File:** `tests/test_observability/test_datetime_utils.py` (300 LOC, 40 tests)

**Required Tests:**
```python
class TestUtcnow:
    def test_returns_timezone_aware_utc(self)
    def test_always_returns_utc_timezone(self)

class TestEnsureUtc:
    def test_none_returns_none(self)
    def test_naive_datetime_converts_with_warning(self)
    def test_non_utc_aware_converts_to_utc(self)
    def test_utc_aware_preserved(self)
    def test_invalid_timezone_raises_error(self)

class TestValidateUtcAware:
    def test_accepts_utc_datetime(self)
    def test_rejects_naive_with_clear_error(self)
    def test_rejects_non_utc_with_clear_error(self)
    def test_none_handling(self)

class TestSafeDurationSeconds:
    def test_none_values_handling(self)
    def test_mixed_aware_naive_handling(self)
    def test_detects_negative_durations(self)  # Clock skew!
    def test_calculates_correct_durations(self)
    def test_very_large_durations(self)
    def test_sub_millisecond_precision(self)
```

**Critical Test (Clock Skew Detection):**
```python
def test_safe_duration_seconds_detects_negative_duration():
    """Negative duration indicates clock skew or time travel bug."""
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 11, 59, 59, tzinfo=timezone.utc)  # Earlier!

    with pytest.raises(ValueError, match="negative duration.*clock skew"):
        safe_duration_seconds(start, end)
```

#### Day 3-4: validation.py (3%)
**File:** `tests/safety/test_validation.py` (800 LOC, 80 tests)

**Required Tests:**
```python
class TestValidatePositiveInt:
    def test_valid_positive_integers(self)
    def test_boundary_values_min_max(self)
    def test_invalid_types_rejected(self)
    def test_float_to_int_conversion(self)
    def test_overflow_handling(self)
    def test_negative_values_rejected(self)

class TestValidateTimeSeconds:
    def test_valid_time_values(self)
    def test_boundary_enforcement(self)
    def test_nan_rejected(self)
    def test_infinity_rejected(self)
    def test_negative_rejected(self)

class TestValidateRegexPattern:
    def test_valid_patterns_compile(self)
    def test_redos_detection(self)  # CRITICAL!
    def test_pattern_length_limits(self)
    def test_empty_pattern_rejected(self)
    def test_invalid_syntax_errors(self)
    def test_timeout_on_adversarial_inputs(self)

class TestValidateStringList:
    def test_valid_string_lists(self)
    def test_empty_list_handling(self)
    def test_max_items_enforced(self)
    def test_max_item_length_enforced(self)
    def test_type_checking(self)

class TestValidateBoolean:
    def test_true_false_accepted(self)
    def test_string_false_rejected(self)  # Type confusion attack!
    def test_none_with_default(self)
    def test_integer_01_rejected(self)
```

**Critical Test (ReDoS Detection):**
```python
def test_validate_regex_detects_redos():
    """Nested quantifiers cause exponential backtracking."""
    mixin = ValidationMixin()

    # Evil regex: (a+)+b
    with pytest.raises(ValueError, match="potentially unsafe.*nested quantifiers"):
        mixin._validate_regex_pattern(r"(a+)+b", "test_pattern")
```

#### Day 5: core/service.py (2%)
**File:** `tests/test_core/test_service.py` (600 LOC, 50 tests)

**Required Tests:**
```python
class TestRegisterPolicy:
    def test_policy_registration(self)
    def test_priority_sorting(self)
    def test_multiple_policies(self)

class TestValidateAction:
    def test_single_policy_validation(self)
    def test_multiple_policies_aggregated(self)
    def test_short_circuit_on_critical(self)  # Performance!
    def test_metadata_merging(self)
    def test_policy_execution_order(self)

class TestHandleViolations:
    def test_logging_levels(self)
    def test_context_sanitization(self)  # Prevent secret leakage!
    def test_execution_tracker_integration(self)
    def test_exception_on_high_violations(self)
    def test_violation_tracking_failures_graceful(self)

class TestSanitizeViolationContext:
    def test_none_to_none(self)
    def test_empty_dict_preserved(self)
    def test_string_sanitization(self)
    def test_nested_dict_sanitization(self)
    def test_list_sanitization(self)
    def test_recursive_structures(self)  # Don't infinite loop!
```

**Critical Test (Secret Leakage Prevention):**
```python
def test_sanitize_prevents_secret_leakage():
    """Violation context must not leak secrets in logs."""
    service = SafetyServiceMixin()

    context = {
        "api_key": "sk-secret123",
        "password": "hunter2",
        "user": "alice"
    }

    sanitized = service._sanitize_violation_context(context)

    assert "sk-secret123" not in str(sanitized)
    assert "hunter2" not in str(sanitized)
    assert "alice" in str(sanitized)  # Non-secret preserved
```

### Week 2: Chaos & Distributed Testing (9% Impact)

#### Day 6-8: Chaos/Fault Injection (3%)
**File:** `tests/test_chaos/test_fault_injection.py` (1000 LOC, 80 tests)

**Test Categories:**
1. **Database Failures (20 tests)**
   - Connection loss mid-transaction
   - Connection pool exhaustion
   - Transaction deadlocks
   - Corrupt checkpoint recovery
   - Database file locked

2. **Network Failures (20 tests)**
   - LLM API timeout
   - Connection reset during call
   - Intermittent network failures
   - DNS resolution failures
   - Certificate validation errors

3. **File System Failures (20 tests)**
   - Disk full during checkpoint
   - Permission denied during rollback
   - File lock timeout
   - Directory doesn't exist
   - Symlink traversal

4. **Resource Exhaustion (20 tests)**
   - Memory allocation failure
   - Thread pool exhaustion
   - Too many open files
   - Stack overflow in recursion
   - CPU throttling

**Critical Test (Disk Full During Checkpoint):**
```python
def test_disk_full_during_checkpoint_safe():
    """Disk full during checkpoint doesn't corrupt state."""
    workflow = create_test_workflow()

    # Mock disk space check to fail mid-save
    with mock_disk_full_after_bytes(1024):
        with pytest.raises(DiskFullError):
            workflow.save_checkpoint()

    # Verify old checkpoint still valid
    restored = workflow.load_checkpoint()
    assert restored.state == workflow.state_before_save

    # Verify no partial checkpoint file
    assert not checkpoint_file_exists_partial()
```

#### Day 9-10: Distributed System Testing (3%)
**Files:** Expand `tests/test_distributed/` (800 LOC, 60 tests)

**Test Categories:**
1. **Multi-Process Coordination (20 tests)**
   - Concurrent workflow tracking
   - Distributed lock contention
   - Database transaction conflicts
   - Orphaned resource cleanup

2. **Distributed Rate Limiting (20 tests)**
   - Rate limit across processes
   - Token bucket consistency
   - Race conditions in token refill
   - Process crash recovery

3. **Distributed Circuit Breaker (20 tests)**
   - Circuit state sharing
   - State persistence across restart
   - Concurrent state transitions
   - Split-brain scenarios

**Critical Test (Race Condition in Token Bucket):**
```python
def test_distributed_token_bucket_no_overallocation():
    """Multiple processes can't exceed token limit."""
    bucket = DistributedTokenBucket(max_tokens=10, refill_rate=1)

    # Spawn 10 processes, each trying to take 5 tokens
    processes = []
    for i in range(10):
        p = Process(target=attempt_take_tokens, args=(bucket, 5))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    # At most 2 processes should succeed (10 tokens / 5 = 2)
    successes = count_successful_processes()
    assert successes <= 2, "Token bucket allowed over-allocation!"
```

#### Day 11-12: E2E Workflows & Race Fixes (3%)
**Files:**
- Expand `tests/integration/test_e2e_workflows.py` (+500 LOC, 30 tests)
- Fix race conditions in `tests/test_async/test_concurrency.py`

**Critical Fix (Race Condition):**
```python
# BEFORE (WRONG):
def test_concurrent_database_writes():
    # ... concurrent writes ...
    assert final_value <= 10  # ❌ Accepts race conditions!

# AFTER (CORRECT):
def test_concurrent_database_writes():
    # ... concurrent writes with SERIALIZABLE isolation ...
    assert final_value == 10  # ✅ Enforces correctness!
```

---

## P1 Implementation Plan (Weeks 3-6)

### Week 3: Coverage Expansion (2.5%)

**Files to Expand:**
1. `tests/test_compiler/test_checkpoint_backends.py` (+400 LOC, 30 tests)
   - Concurrent operations
   - Corruption scenarios
   - Disk full errors
   - Large checkpoint handling

2. `tests/test_observability/test_backend.py` (+500 LOC, 40 tests)
   - Session stack overflow
   - Connection pool exhaustion
   - Transaction rollback
   - Retention policy enforcement

### Week 4: Performance & Migration (3%)

**New Files:**
1. `tests/test_benchmarks/test_performance_regression.py` (+600 LOC, 50 tests)
   - Baseline measurements
   - Regression detection
   - Memory growth tracking

2. `tests/test_migrations/test_schema_evolution.py` (+500 LOC, 40 tests)
   - Schema upgrades
   - Downgrades
   - Rollback on error
   - Zero-downtime migration

### Week 5: Integration & Error Paths (4%)

**Expand Files:**
1. `tests/integration/test_error_propagation_e2e.py` (+300 LOC, 20 tests)
2. `tests/integration/test_tool_safety_integration.py` (NEW, 400 LOC, 25 tests)
3. Add 100 exception handling tests across codebase

### Week 6: Flaky Test Fixes (3%)

**Fix Categories:**
1. Replace 131 `time.sleep()` with proper synchronization
2. Fix 50 race condition assertions (`<=` → `==`)
3. Add `@pytest.mark.slow` to slow tests
4. Use `pytest.mark.timeout` instead of manual timeouts

---

## Quick Wins (Can Start Today)

### 1. Fix Critical Race Condition (5 minutes)
```bash
# File: tests/test_async/test_concurrency.py:332
- assert final_value <= 10
+ assert final_value == 10
```

### 2. Create datetime_utils Tests (2 hours)
```bash
touch tests/test_observability/test_datetime_utils.py
# Implement 40 tests as outlined above
```

### 3. Create validation Tests (4 hours)
```bash
touch tests/safety/test_validation.py
# Implement 80 tests as outlined above
```

### 4. Fix Top 10 Flaky Tests (1 day)
Replace `time.sleep()` in most problematic files:
- `tests/test_tools/test_executor.py` (13 occurrences)
- `tests/test_load/test_stress.py` (13 occurrences)
- `tests/test_llm/test_circuit_breaker_race.py` (11 occurrences)

---

## Success Metrics

### Quantitative Targets

| Metric | Current | Target | Gap |
|--------|---------|--------|-----|
| Line coverage | 66.4% | 85%+ | +18.6% |
| Branch coverage | ~60% | 75%+ | +15% |
| Critical module coverage | 33% | 100% | +67% |
| Flaky tests | 131 | 0 | -131 |
| CI pass rate | ~95% | 99%+ | +4% |
| Test execution time | ~8m | <5m | -3m |

### Qualitative Targets

- ✅ All P0 security modules have comprehensive tests
- ✅ All critical error paths covered
- ✅ All distributed scenarios tested
- ✅ All state machines fully tested
- ✅ Zero timing dependencies (no `time.sleep()`)
- ✅ All assertions specific (no generic checks)
- ✅ All `pytest.raises()` have `match=` parameter

---

## Estimation Summary

### Total Effort to 100% Quality

| Priority | Tests | LOC | Fixes | Person-Weeks |
|----------|-------|-----|-------|--------------|
| P0 | 390 | 4000 | 50 | 4 weeks |
| P1 | 425 | 3800 | 100 | 4 weeks |
| P2 | 30 | 900 | 430 | 2 weeks |
| **TOTAL** | **845** | **8700** | **580** | **10 weeks** |

**Realistic Timeline:** 2.5 months (with 1 engineer full-time)

**Critical Path:** P0 only → 2 weeks → gets to 95% quality (production-ready)

---

## Next Steps

### Immediate (Today)
1. ✅ Fix race condition in `test_concurrency.py:332`
2. ✅ Create `test_datetime_utils.py` with 40 tests
3. ✅ Create `test_validation.py` with 80 tests

### This Week (P0 Week 1)
4. ✅ Create `test_service.py` with 50 tests
5. ✅ All zero-coverage modules at 100% coverage

### Next Week (P0 Week 2)
6. ✅ Create chaos testing framework
7. ✅ Expand distributed testing
8. ✅ Fix top 50 race conditions

### This Month (P0 + P1)
9. ✅ All P0 gaps closed (90% → 95%+ quality)
10. ✅ Performance regression suite in place
11. ✅ Flaky tests eliminated

---

## Risk Mitigation

### Risk: Timeline Too Aggressive
**Mitigation:** Focus on P0 only first (2 weeks), defer P1/P2

### Risk: Test Maintenance Burden
**Mitigation:** Use parameterized tests, fixtures, test utilities

### Risk: Tests Slow Down CI
**Mitigation:** Mark slow tests, run subset in PR checks

### Risk: Developer Resistance
**Mitigation:** Show value via catching real bugs, improve developer experience

---

## Appendix: Files Created/Modified

### New Test Files (10 files, 4400 LOC)
```
tests/test_observability/test_datetime_utils.py          300 LOC
tests/safety/test_validation.py                          800 LOC
tests/test_core/test_service.py                          600 LOC
tests/test_chaos/test_fault_injection.py                1000 LOC
tests/test_distributed/test_multi_process.py             800 LOC
tests/test_migrations/test_schema_evolution.py           500 LOC
tests/integration/test_tool_safety_integration.py        400 LOC
```

### Expanded Test Files (8 files, +3800 LOC)
```
tests/test_compiler/test_checkpoint_backends.py         +400 LOC
tests/test_observability/test_backend.py                +500 LOC
tests/test_benchmarks/test_performance_benchmarks.py    +600 LOC
tests/test_distributed/test_distributed_tracking.py     +400 LOC
tests/integration/test_e2e_workflows.py                 +500 LOC
tests/integration/test_error_propagation_e2e.py         +300 LOC
tests/test_error_handling/test_timeout_scenarios.py     +300 LOC
tests/test_compiler/test_workflow_state_transitions.py  +400 LOC
```

### Test Fixes (687 items)
```
Fix 131 time.sleep() dependencies
Fix 50 race conditions
Fix 150 weak assertions
Fix 50 test independence violations
Add 200 error message validations
Fix 100 exception paths
Mark 6 slow tests
```

**Total:** 18 files modified/created, 8,200 LOC added, 687 fixes

---

## Quality Progression Chart

```
Current:  90% ████████████████████░░░░
P0 Week 1: 95% ███████████████████████░
P0 Week 2: 97% ████████████████████████
P1 Month:  98% ████████████████████████
P2 Quarter: 99% ████████████████████████
Target:   100% █████████████████████████
```

**Conclusion:** With focused effort on P0 gaps (2 weeks), we can reach production-ready quality (95%+). Full 100% quality achievable in 2.5 months.
