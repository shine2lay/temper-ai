# Task: test-fix-failures-02 - Fix Tool Execution Test Failures

**Priority:** CRITICAL
**Effort:** 1-2 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Fix 4 failing tests related to agent tool call parsing and tool not found error handling.

---

## Files to Modify
- `tests/test_agents/test_standard_agent.py` - Fix tool execution tests
- `src/agents/base_agent.py` - Fix tool call parsing logic
- `src/agents/standard_agent.py` - Fix error handling for missing tools

---

## Acceptance Criteria

### Core Functionality
- [ ] test_standard_agent_execute_with_tool_calls passes
- [ ] test_standard_agent_execute_tool_not_found passes
- [ ] Tool call parsing correctly extracts tool name and parameters
- [ ] Missing tool errors return graceful error message

### Testing
- [ ] All 4 tool execution tests pass
- [ ] Tool call parsing handles malformed JSON gracefully
- [ ] Tool registry lookup failures are caught and reported

### Error Handling
- [ ] ToolNotFoundError raised with clear message
- [ ] Agent response includes error in metadata
- [ ] Execution continues after tool failure (if configured)

---

## Implementation Details

**Current Failures:**
- test_standard_agent_execute_with_tool_calls
- test_standard_agent_execute_tool_not_found
- 2 additional tool integration tests

**Likely Issues:**
1. LLM response parser not extracting tool calls correctly
2. Tool registry lookup throwing uncaught exception
3. Tool call format changed but tests not updated

**Implementation Steps:**
1. Review agent response parsing logic
2. Check tool call format expected by parser
3. Verify tool registry integration
4. Fix error handling for missing tools
5. Ensure tests use correct mock structure

---

## Test Strategy

```bash
# Run only tool execution tests
pytest tests/test_agents/test_standard_agent.py::test_standard_agent_execute_with_tool_calls -v
pytest tests/test_agents/test_standard_agent.py::test_standard_agent_execute_tool_not_found -v

# Run all agent tests
pytest tests/test_agents/ -v
```

---

## Success Metrics
- [ ] 0/4 tests failing (100% pass rate)
- [ ] Coverage for agent tool integration >85%
- [ ] Error messages are clear and actionable

---

## Dependencies
- **Blocked by:** None
- **Blocks:** test-integration-agent-tool
- **Integrates with:** src/agents/, src/tools/

---

## Notes
- Check if LLM provider mock responses match expected format
- Verify tool call schema matches what parser expects
