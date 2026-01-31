# Task: test-crit-security-misc-01 - Add Missing Security Concurrency Tests

**Priority:** CRITICAL
**Effort:** 3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add missing concurrent security tests for approval workflow, policy composition, TOCTOU, and safety mode transitions.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_security/test_race_conditions.py - Add TOCTOU exploitation tests`
- `tests/test_safety/test_approval_workflow.py - Add concurrent approval tests`
- `tests/test_safety/test_policy_composition.py - Add policy conflict tests`
- `tests/test_safety/test_safety_mode_transitions.py - Add transition rollback tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test TOCTOU exploitation with multi-threaded attack simulation
- [ ] Test concurrent approval race conditions (multiple approvers)
- [ ] Test policy conflict resolution (ALLOW vs DENY)
- [ ] Test safety mode transition rollback on failure
- [ ] Verify race condition detection and mitigation

### Testing
- [ ] TOCTOU: multi-threaded file check/use race
- [ ] Approval: simultaneous approval attempts
- [ ] Policy: conflicting policy decisions
- [ ] Mode transition: mid-transition failure recovery

### Security Controls
- [ ] TOCTOU mitigation (atomic file operations)
- [ ] Approval serialization (one approver wins)
- [ ] Policy conflict resolution (DENY wins)

---

## Implementation Details

```python
def test_toctou_race_condition_exploitation():
    """Test TOCTOU attack simulation"""
    def check_and_use_file():
        if os.path.exists("/tmp/sensitive"):
            time.sleep(0.01)  # Simulated processing
            with open("/tmp/sensitive") as f:
                return f.read()

    def attacker_thread():
        os.symlink("/etc/passwd", "/tmp/sensitive")

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(check_and_use_file)
        f2 = executor.submit(attacker_thread)
        # Should detect and prevent TOCTOU
        with pytest.raises(TOCTOUDetected):
            f1.result()

def test_concurrent_approval_race_conditions():
    """Test multiple approvers approving simultaneously"""
    workflow = create_approval_workflow()
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(workflow.approve, user_id=i) for i in range(3)]
        results = [f.result() for f in futures]
    # Only one approval should succeed
    assert sum(r.approved for r in results) == 1
```

---

## Test Strategy

Use real threading for concurrency. Simulate attack scenarios. Verify mitigation effectiveness.

---

## Success Metrics

- [ ] All 4 security concurrency issues tested
- [ ] TOCTOU detection working
- [ ] Approval serialization verified
- [ ] Policy conflict resolution correct

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** ApprovalWorkflow, PolicyEngine, SafetyModeManager

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issues #8-11

---

## Notes

Use atomic file operations to prevent TOCTOU. Test policy DENY-wins rule.
