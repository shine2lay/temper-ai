# Task: test-crit-security-owasp-03 - Add OWASP LLM Top 10 LLM08/09 Coverage

**Priority:** CRITICAL
**Effort:** 2.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add tests for OWASP LLM08 (Excessive Agency) and LLM09 (Overreliance) including tool permission boundaries and autonomous action escalation prevention.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_security/test_llm_security.py - Add LLM08/09 tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test tool permission boundary enforcement
- [ ] Test autonomous action escalation is prevented
- [ ] Test overreliance detection (verify human-in-loop for critical actions)
- [ ] Verify tool access control lists work
- [ ] Test unauthorized tool chaining is blocked

### Testing
- [ ] Test LLM attempts to use forbidden tools
- [ ] Test LLM attempts privilege escalation via tool chaining
- [ ] Test critical actions require human approval
- [ ] Edge case: tool permission inheritance

### Security Controls
- [ ] Tool ACL enforcement (whitelist-based)
- [ ] Human approval required for P0 actions
- [ ] Audit log for all tool executions

---

## Implementation Details

```python
def test_llm08_tool_permission_boundary_tests():
    """Test tool permission boundaries"""
    agent = LLMAgent(allowed_tools=["read_file"])
    with pytest.raises(PermissionDenied):
        agent.execute_tool("delete_file", {"path": "/etc/passwd"})

def test_llm08_autonomous_action_escalation_prevention():
    """Test action escalation is blocked"""
    agent = LLMAgent(permission_level="read_only")
    with pytest.raises(EscalationAttempt):
        agent.execute_tool("write_file", {})  # Requires write permission

def test_llm09_overreliance_detection():
    """Test critical actions require human approval"""
    action = {"type": "delete_database", "criticality": "P0"}
    result = agent.plan_action(action)
    assert result.requires_approval == True
    assert result.human_in_loop == True
```

---

## Test Strategy

Test permission boundary violations. Verify human-in-loop for critical actions. Test audit logging.

---

## Success Metrics

- [ ] All LLM08/09 attack scenarios tested
- [ ] Permission boundary enforcement >99% accurate
- [ ] Human approval enforced for all P0 actions
- [ ] Audit log captures all tool executions

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** ToolRegistry, PermissionManager, ApprovalWorkflow

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #4 (LLM08/09)

---

## Notes

Use whitelist-based permission model. Test tool chaining attacks.
