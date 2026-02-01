# Task: Add missing AgentResponse fields to API docs

## Summary

AgentResponse documentation missing important fields like reasoning, tokens, confidence.

**Priority:** CRITICAL  
**Category:** doc-code-mismatch  
**Impact:** HIGH - Users won't know about important fields

---

## Files to Create

_None_

---

## Files to Modify

- `docs/API_REFERENCE.md` - Update documentation

---

## Current State

**Location:** docs/API_REFERENCE.md:932-947

**Current:** Only documents output, metadata, tool_calls, error

**Should be:** Document all fields including reasoning, tokens, confidence, etc.

---

## Acceptance Criteria

### Core Functionality

- [ ] Add reasoning: Optional[str]
- [ ] Add tokens: int
- [ ] Add estimated_cost_usd: float
- [ ] Add latency_seconds: float
- [ ] Add confidence: Optional[float]
- [ ] Document auto-calculation behavior for confidence

### Testing

- [ ] Verify: python -c 'from src.agents import AgentResponse; import inspect; print(inspect.signature(AgentResponse))'
- [ ] Cross-reference with src/agents/base_agent.py:14-38

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
