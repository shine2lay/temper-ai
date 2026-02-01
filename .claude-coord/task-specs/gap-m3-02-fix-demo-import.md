# Task: gap-m3-02-fix-demo-import - Fix broken demo script import in run_multi_agent_workflow.py

**Priority:** CRITICAL (P0 - User-facing)
**Effort:** 30 minutes
**Status:** pending
**Owner:** unassigned

---

## Summary

Example workflow demo script has incorrect import causing ImportError. The function `create_gantt_chart` doesn't exist - it's actually named `create_hierarchical_gantt`. This prevents users from running M3 examples.

**Impact:** M3 demonstrations not runnable, user-facing failure.

---

## Files to Create

_None_

---

## Files to Modify

- `examples/run_multi_agent_workflow.py:35` - Fix import statement

---

## Acceptance Criteria

### Core Functionality
- [ ] Import statement corrected to use actual function name
- [ ] Import uses alias to preserve existing code compatibility
- [ ] Demo script runs without Import Error
- [ ] Multi-agent workflow executes successfully

### Testing
- [ ] Manually run: `python examples/run_multi_agent_workflow.py`
- [ ] Verify multi_agent_research.yaml workflow executes
- [ ] Verify debate_decision.yaml workflow executes
- [ ] No import errors in any example scripts

### Documentation
- [ ] Verify other example scripts don't have similar import issues

---

## Implementation Details

**Current Code (Line 35):**
```python
from src.observability.visualize_trace import create_gantt_chart, print_console_gantt
```

**Corrected Code:**
```python
from src.observability.visualize_trace import create_hierarchical_gantt as create_gantt_chart, print_console_gantt
```

**Root Cause:** Function was renamed from `create_gantt_chart` to `create_hierarchical_gantt` but example script wasn't updated.

**Fix Strategy:** Use import alias to maintain backward compatibility with existing script code.

---

## Test Strategy

**Manual Testing:**
1. Run demo script: `python examples/run_multi_agent_workflow.py`
2. Verify no ImportError
3. Verify Gantt chart visualization works
4. Test with both example workflows

**Validation:**
- Check all example scripts for similar issues
- Grep for `create_gantt_chart` references

---

## Success Metrics

- [ ] Demo script runs without errors
- [ ] Import statement corrected
- [ ] Visualization output generated
- [ ] No similar issues in other example files
- [ ] User can successfully demonstrate M3 capabilities

---

## Dependencies

- **Blocked by:** _None_ (can start immediately)
- **Blocks:** _None_ (independent fix)
- **Integrates with:** examples/run_multi_agent_workflow.py

---

## Design References

- Gap Analysis Report: `.claude-coord/reports/milestone-gaps-20260130-173000.md`
- Agent a4b6163 Audit: M3 example workflows broken
- Actual function: `src/observability/visualize_trace.py` (create_hierarchical_gantt)

---

## Notes

**QUICK WIN:** This is a 30-minute fix with immediate user-facing impact.

**Check for Similar Issues:** After fixing, grep for other potential import issues in examples/:
```bash
grep -r "create_gantt_chart" examples/
grep -r "from src.observability.visualize_trace import" examples/
```

**Priority:** Despite being simple, this is P0 because it affects user experience and M3 demonstrations.
