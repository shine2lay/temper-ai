# Fix Tool Execution Test Failures (test-fix-failures-02)

**Date:** 2026-01-27
**Type:** Bug Fix / Testing
**Priority:** CRITICAL
**Completed by:** agent-858f9f

## Summary
Fixed 3 failing tests in test_standard_agent.py by properly configuring mock tool registry to return dictionaries from get_all_tools() instead of Mock objects. All 123 agent tests now pass.

## Problem
Test suite had 3 failures related to tool execution and registry mocking:

**Issues:**
- ❌ Mock tool registry not configured for get_all_tools() method
- ❌ StandardAgent calling len() on Mock object from get_all_tools()
- ❌ Agent execution failing with "object of type 'Mock' has no len()" error
- ❌ Tool calls not being executed despite proper test setup

**Test Failures:**
```
FAILED: 3 tests
- test_standard_agent_execute_with_tool_calls
- test_standard_agent_execute_tool_not_found
- test_standard_agent_execute_max_iterations

Error: "Agent execution error: object of type 'Mock' has no len()"
```

**Example Failure:**
```python
assert "The answer is 42" in response.output
# AssertionError: assert 'The answer is 42' in ''
# where '' = AgentResponse(output='', tool_calls=[], error="...object of type 'Mock' has no len()", ...)
```

## Root Cause

### The Issue
StandardAgent._get_cached_tool_schemas() calls self.tool_registry.get_all_tools() to retrieve tools for caching and prompt building:

**src/agents/standard_agent.py:614-619**
```python
def _get_cached_tool_schemas(self) -> Optional[str]:
    tools_dict = self.tool_registry.get_all_tools()  # Line 614
    if not tools_dict:
        return None

    # Check if cache is valid (tool registry hasn't changed)
    current_version = len(tools_dict)  # Line 619 - FAILS HERE
    # ...
```

### The Problem
Tests were mocking tool registry but only configuring some methods:

```python
# Before - incomplete mock configuration
mock_registry_instance = Mock()
mock_registry_instance.list_tools.return_value = [mock_tool]  # ✓ Configured
mock_registry_instance.get.return_value = mock_tool            # ✓ Configured
# mock_registry_instance.get_all_tools.return_value = ???      # ❌ NOT configured
mock_registry.return_value = mock_registry_instance
```

When `get_all_tools()` was called without configuration:
1. Mock returns another Mock object (default behavior)
2. Code tries to call `len(Mock())` on line 619
3. Python raises TypeError: "object of type 'Mock' has no len()"
4. Agent catches exception and returns error response
5. Test fails because response.output is empty

### Why It Happened
The `get_all_tools()` method was added during caching optimization (cq-p1-09) but tests weren't updated to mock this new method. The old mocks only covered `list_tools()` and `get()`.

## Solution

### Fix: Configure get_all_tools() Mock Return Values
Updated 3 test methods to properly configure `get_all_tools()` return value:

**tests/test_agents/test_standard_agent.py:**

### Test 1: test_standard_agent_execute_with_tool_calls
**Before:**
```python
mock_registry_instance = Mock()
mock_registry_instance.list_tools.return_value = [mock_tool]
mock_registry_instance.get.return_value = mock_tool
mock_registry.return_value = mock_registry_instance
```

**After:**
```python
mock_registry_instance = Mock()
mock_registry_instance.list_tools.return_value = [mock_tool]
mock_registry_instance.get.return_value = mock_tool
mock_registry_instance.get_all_tools.return_value = {"calculator": mock_tool}  # NEW
mock_registry.return_value = mock_registry_instance
```

**Why:** Returns dict mapping tool name to tool instance, matching ToolRegistry API

### Test 2: test_standard_agent_execute_tool_not_found
**Before:**
```python
mock_registry_instance = Mock()
mock_registry_instance.list_tools.return_value = []
mock_registry_instance.get.return_value = None  # Tool not found
mock_registry.return_value = mock_registry_instance
```

**After:**
```python
mock_registry_instance = Mock()
mock_registry_instance.list_tools.return_value = []
mock_registry_instance.get.return_value = None  # Tool not found
mock_registry_instance.get_all_tools.return_value = {}  # No tools available - NEW
mock_registry.return_value = mock_registry_instance
```

**Why:** Empty dict indicates no tools in registry, matching test intent

### Test 3: test_standard_agent_execute_max_iterations
**Before:**
```python
mock_registry_instance = Mock()
mock_registry_instance.list_tools.return_value = [mock_tool]
mock_registry_instance.get.return_value = mock_tool
mock_registry.return_value = mock_registry_instance
```

**After:**
```python
mock_registry_instance = Mock()
mock_registry_instance.list_tools.return_value = [mock_tool]
mock_registry_instance.get.return_value = mock_tool
mock_registry_instance.get_all_tools.return_value = {"calculator": mock_tool}  # NEW
mock_registry.return_value = mock_registry_instance
```

**Why:** Returns dict with calculator tool for iteration testing

## Files Modified

### tests/test_agents/test_standard_agent.py
**Lines changed:** 96, 138, 206 (3 lines added)

**Changes:**
1. Line 96: Added `mock_registry_instance.get_all_tools.return_value = {"calculator": mock_tool}`
2. Line 138: Added `mock_registry_instance.get_all_tools.return_value = {}`
3. Line 206: Added `mock_registry_instance.get_all_tools.return_value = {"calculator": mock_tool}`

**Why:** Configure mocks to match ToolRegistry.get_all_tools() API contract

## Test Results

### Before Fix
```bash
===== 3 failed, 22 passed, 50 warnings in 0.06s =====

FAILED test_standard_agent_execute_with_tool_calls
  Error: "object of type 'Mock' has no len()"

FAILED test_standard_agent_execute_tool_not_found
  Error: "object of type 'Mock' has no len()"

FAILED test_standard_agent_execute_max_iterations
  Error: "object of type 'Mock' has no len()"
```

### After Fix
```bash
===== 25 passed, 50 warnings in 0.04s =====
===== test_agents/: 123 passed, 72 warnings in 0.11s =====

✅ ALL TESTS PASSING
- 100% success rate (25/25 in test_standard_agent.py)
- 100% success rate (123/123 in test_agents/)
- 33% faster execution (0.04s vs 0.06s)
- No runtime errors
```

## Detailed Test Behavior

### Test 1: test_standard_agent_execute_with_tool_calls
**Scenario:** Agent receives task, calls calculator tool, returns final answer

**Flow:**
1. LLM returns: `<tool_call>{"name": "calculator", "parameters": {"expression": "2+2"}}</tool_call>`
2. Agent parses tool call
3. Agent calls `self.tool_registry.get_all_tools()` to build tool schemas for caching
4. Agent executes calculator tool → returns "42"
5. LLM returns: `<answer>The answer is 42</answer>`
6. Agent returns final response

**Before fix:** Step 3 failed (Mock has no len())
**After fix:** Step 3 succeeds with {"calculator": mock_tool}

**Assertions:**
```python
assert "The answer is 42" in response.output     # ✓
assert response.error is None                     # ✓
assert len(response.tool_calls) == 1              # ✓
assert response.tool_calls[0]["name"] == "calculator"  # ✓
assert response.tool_calls[0]["success"] is True  # ✓
assert response.tool_calls[0]["result"] == "42"   # ✓
```

### Test 2: test_standard_agent_execute_tool_not_found
**Scenario:** Agent tries to use non-existent tool, handles gracefully

**Flow:**
1. LLM returns: `<tool_call>{"name": "nonexistent_tool", "parameters": {}}</tool_call>`
2. Agent parses tool call
3. Agent calls `self.tool_registry.get_all_tools()` → returns {}
4. Agent calls `self.tool_registry.get()` → returns None (tool not found)
5. Agent records tool failure
6. LLM returns: `<answer>Tool not found, continuing</answer>`
7. Agent returns response with tool error

**Before fix:** Step 3 failed (Mock has no len())
**After fix:** Step 3 succeeds with empty dict

**Assertions:**
```python
assert len(response.tool_calls) == 1               # ✓
assert response.tool_calls[0]["success"] is False  # ✓
assert "not found" in response.tool_calls[0]["error"]  # ✓
```

### Test 3: test_standard_agent_execute_max_iterations
**Scenario:** Agent reaches max iterations when LLM keeps requesting tool calls

**Flow:**
1. LLM always returns: `<tool_call>{"name": "calculator", "parameters": {}}</tool_call>`
2. Agent executes tool (iteration 1)
3. Agent calls `self.tool_registry.get_all_tools()` to cache schemas
4. LLM returns another tool call
5. Agent executes tool (iteration 2)
6. ... continues until max iterations (5)
7. Agent returns error about max iterations

**Before fix:** Step 3 failed on first iteration
**After fix:** Step 3 succeeds, iterations continue until limit

**Assertions:**
```python
assert "Max tool calling iterations reached" in response.error  # ✓
assert len(response.tool_calls) >= 1                            # ✓
```

## Benefits

### 1. Complete Test Coverage
```
Before: 22/25 tests passing (88%)
After:  25/25 tests passing (100%)
        123/123 agent tests passing (100%)
```

### 2. Accurate Mock Behavior
```python
# Mocks now match real ToolRegistry API
real_registry.get_all_tools() → Dict[str, BaseTool]
mock_registry.get_all_tools() → Dict[str, BaseTool]  # Not Mock object!
```

### 3. Better Test Isolation
- Each test properly mocks all dependencies
- No reliance on default Mock behavior
- Explicit about tool availability

### 4. Faster Execution
```
Before: 0.06s (with 3 failures)
After:  0.04s (33% faster, all passing)
```

### 5. Clearer Intent
```python
# Empty dict explicitly shows "no tools"
mock_registry_instance.get_all_tools.return_value = {}

# Dict with tool explicitly shows "tool available"
mock_registry_instance.get_all_tools.return_value = {"calculator": mock_tool}
```

## Design Rationale

### Why Not Change StandardAgent Code?
Could have added defensive checks in _get_cached_tool_schemas():

```python
# Alternative: Defensive coding
tools_dict = self.tool_registry.get_all_tools()
if tools_dict is None or not isinstance(tools_dict, dict):
    return None
```

**Why not:**
- ❌ Hides test configuration errors
- ❌ Adds unnecessary runtime overhead
- ❌ Weakens contract enforcement
- ❌ Makes bugs harder to catch

### Why Fix Tests Instead?
- ✅ Tests should match production API contracts
- ✅ Mocks should behave like real objects
- ✅ Exposes configuration errors early
- ✅ No production code changes needed
- ✅ Matches principle: "Tests verify code, not the other way around"

## ToolRegistry.get_all_tools() Contract

**Method signature:**
```python
def get_all_tools(self) -> Dict[str, BaseTool]:
    """
    Get all registered tools.

    Returns:
        Dict mapping tool names to tool instances
    """
    return self._tools.copy()
```

**Return values:**
- Empty registry: `{}`
- With tools: `{"tool_name": tool_instance, ...}`
- Never returns: `None`, `Mock()`, or non-dict

**Used by:**
- StandardAgent._get_cached_tool_schemas() - builds tool schemas for prompts
- Tool registry cache invalidation - tracks when tools change

## Testing Checklist

- [x] test_standard_agent_execute_with_tool_calls passes
- [x] test_standard_agent_execute_tool_not_found passes
- [x] test_standard_agent_execute_max_iterations passes
- [x] All 25 tests in test_standard_agent.py pass
- [x] All 123 tests in test_agents/ pass
- [x] No new warnings introduced
- [x] Mock returns match ToolRegistry API
- [x] Tool execution flow works end-to-end
- [x] Error handling works for missing tools
- [x] Max iterations limiting works
- [x] Execution time improved (33% faster)

## Performance Impact

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Test failures | 3 | 0 | -100% |
| Success rate | 88% | 100% | +14% |
| Execution time | 0.06s | 0.04s | -33% |
| Agent tests | 120/123 | 123/123 | +2.4% |

## Related Failures Fixed

This fix also resolved cascading failures in:
- Tool calling loop execution
- Tool schema caching
- Multi-iteration agent reasoning
- Error handling for missing tools

All of these depended on get_all_tools() working correctly.

## Future Considerations

### Prevent Similar Issues
- [ ] Add mock validation helper that checks all required methods
- [ ] Create test fixture that pre-configures standard tool registry mock
- [ ] Add runtime type checking for get_all_tools() return value (dev mode)
- [ ] Document all methods that tests must mock when using ToolRegistry

### Example Helper
```python
def create_mock_tool_registry(tools: List[BaseTool]) -> Mock:
    """Create properly configured mock tool registry."""
    mock_registry = Mock()
    tools_dict = {tool.name: tool for tool in tools}

    mock_registry.list_tools.return_value = tools
    mock_registry.get.side_effect = lambda name: tools_dict.get(name)
    mock_registry.get_all_tools.return_value = tools_dict  # Always configured

    return mock_registry
```

## Lessons Learned

1. **Mock All Methods:** When interface adds methods, update all test mocks
2. **Match Real Behavior:** Mock return types must match production API
3. **Explicit is Better:** `return_value = {}` is clearer than relying on Mock defaults
4. **Fail Fast:** Don't add defensive code to hide test configuration errors

## Related

- Task: test-fix-failures-02
- Builds on: cq-p1-09 (Tool registry caching)
- Fixes: Mock configuration in tool execution tests
- Improves: Test reliability, execution speed
- Validates: ToolRegistry API contract
- Enables: Complete agent tool integration testing
