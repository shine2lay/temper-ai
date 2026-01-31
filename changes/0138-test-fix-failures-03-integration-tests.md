# Change Log: test-fix-failures-03 - Fix Integration Test Failures

**Date:** 2026-01-28
**Task ID:** test-fix-failures-03
**Agent:** agent-a9cf7f
**Status:** Completed ✓

---

## Summary

Fixed 2 failing integration tests in test_tool_rollback.py by correcting API signatures for SafetyViolation and ApprovalWorkflow.reject() calls.

---

## Task Status

**Original Status:** Orphaned (owned by agent-5f9de4, no active agent)
**Action Taken:** Reset task to pending, claimed, and fixed

---

## Changes Made

### Files Modified

1. **tests/integration/test_tool_rollback.py**
   - Fixed `test_policy_blocking` test (line 216-227)
     - Removed invalid `rule_id` parameter from SafetyViolation constructor
     - Added required parameters: `action` and `context`
     - Fixed parameter order to match SafetyViolation signature
   - Fixed `test_approval_rejection_callback` test (line 323)
     - Changed `rejector` parameter to `rejecter` (typo fix)
     - Matches ApprovalWorkflow.reject() signature

---

## Test Results

### Before Fixes
```
FAILED test_tool_rollback.py::TestToolRollback::test_policy_blocking
  - TypeError: SafetyViolation.__init__() got an unexpected keyword argument 'rule_id'

FAILED test_tool_rollback.py::TestApprovalRejectionRollback::test_approval_rejection_callback
  - TypeError: ApprovalWorkflow.reject() got an unexpected keyword argument 'rejector'

Result: 84 passed, 2 failed, 11 skipped
```

### After Fixes
```
tests/integration/test_tool_rollback.py: 7 PASSED
All integration tests: 86 PASSED, 11 SKIPPED, 0 FAILED
```

---

## Technical Details

### Issue 1: SafetyViolation Constructor

**Problem:**
```python
SafetyViolation(
    severity=ViolationSeverity.CRITICAL,
    message="Action blocked by policy",
    policy_name="test_policy",
    rule_id="test_rule"  # ❌ Invalid parameter
)
```

**Fix:**
```python
SafetyViolation(
    policy_name="test_policy",
    severity=ViolationSeverity.CRITICAL,
    message="Action blocked by policy",
    action="write_file",  # ✅ Required parameter
    context={}            # ✅ Required parameter
)
```

**SafetyViolation Signature:**
```python
def __init__(
    self,
    policy_name: str,
    severity: ViolationSeverity,
    message: str,
    action: str,              # Required, not optional
    context: Dict[str, Any],  # Required, not optional
    timestamp: str = <factory>,
    remediation_hint: Optional[str] = None,
    metadata: Dict[str, Any] = <factory>
) -> None
```

### Issue 2: ApprovalWorkflow.reject() Parameter Name

**Problem:**
```python
approval_workflow.reject(
    approval_request.id,
    rejector="test-user",  # ❌ Wrong parameter name
    reason="Test rejection"
)
```

**Fix:**
```python
approval_workflow.reject(
    approval_request.id,
    rejecter="test-user",  # ✅ Correct parameter name
    reason="Test rejection"
)
```

**ApprovalWorkflow.reject() Signature:**
```python
def reject(
    self,
    request_id: str,
    rejecter: str,  # Note: "rejecter" not "rejector"
    reason: Optional[str] = None
) -> bool
```

---

## Integration Test Coverage

**Total Tests:** 86 passed, 11 skipped

### Test Files
1. `test_agent_tool_integration.py` - 13 tests
2. `test_compiler_engine_observability.py` - 15 tests
3. `test_component_integration.py` - 12 tests
4. `test_m2_e2e.py` - 20 tests
5. `test_m3_multi_agent.py` - 12 tests
6. `test_milestone1_e2e.py` - 7 tests
7. `test_tool_rollback.py` - 7 tests ✅ (fixed in this change)

### Test Categories
- Agent-tool integration
- Compiler-engine-observability integration
- Component integration (registry, factory, discovery)
- M2 end-to-end workflows
- M3 multi-agent coordination
- Milestone 1 basic workflows
- Tool executor rollback integration

---

## Orphaned Task Handling

This task was orphaned (owned by agent-5f9de4 with no active agent). Resolution:

1. **Detected orphan:** No active agents, task in_progress
2. **Reset task:** Set status to "pending", owner to null
3. **Claimed task:** agent-a9cf7f claimed and fixed
4. **Verified fix:** All tests pass

This demonstrates the coordination system's ability to recover from abandoned tasks.

---

## API Signature Reference

For future test writing, here are the corrected signatures:

### SafetyViolation
```python
SafetyViolation(
    policy_name: str,      # Policy that raised violation
    severity: ViolationSeverity,  # CRITICAL, HIGH, MEDIUM, LOW
    message: str,          # Human-readable message
    action: str,           # Action that triggered violation
    context: Dict[str, Any],  # Execution context
    remediation_hint: Optional[str] = None,  # How to fix
    metadata: Dict[str, Any] = {}  # Additional data
)
```

### ApprovalWorkflow.reject()
```python
approval_workflow.reject(
    request_id: str,       # ID of approval request
    rejecter: str,         # User/agent rejecting (note spelling!)
    reason: Optional[str] = None  # Reason for rejection
) -> bool
```

---

## Warnings (Non-blocking)

The following warnings appear but don't affect test success:

1. **Unknown pytest.mark.integration** - 14 warnings
   - Tests use `@pytest.mark.integration` but marker not registered
   - Harmless, but could register in pytest.ini/pyproject.toml

2. **DeprecationWarning in schemas.py:43**
   - `deprecated` decorator warning
   - From pydantic or similar library
   - Not related to test failures

3. **ToolExecutor garbage collection warnings**
   - "Use context manager or call shutdown() explicitly"
   - Tests don't explicitly shut down executor
   - Could add cleanup in fixtures, but doesn't affect results

---

## Acceptance Criteria

- [x] All integration tests pass (86/86 passing tests)
- [x] test_tool_rollback.py tests fixed (7/7 passing)
- [x] No API signature errors
- [x] Integration test coverage maintained
- [x] Rollback integration verified
- [x] Approval workflow integration verified
- [x] Policy blocking integration verified

---

## Verification

```bash
# Run integration tests
pytest tests/integration/ -v

# Run specific file
pytest tests/integration/test_tool_rollback.py -v

# Results
86 passed, 11 skipped, 0 failed ✓
```

---

## Impact

**Scope:** Integration test suite
**Risk Level:** Low (test fixes only, no production code changes)
**Testing:** All integration tests passing

This completes the integration test failure fixes. The task spec mentioned 9 failing tests, but only 2 failures were found in the actual test suite. The remaining tests either:
- Were already fixed in previous work
- Never existed (spec referred to non-existent test files)
- Were passing from the start

All current integration tests now pass successfully.
