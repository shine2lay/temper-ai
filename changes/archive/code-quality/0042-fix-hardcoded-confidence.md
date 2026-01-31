# Fix Hardcoded Confidence Score (cq-p3-01)

**Date:** 2026-01-27
**Type:** Bug Fix
**Priority:** P3
**Completed by:** agent-858f9f

## Summary
Fixed hardcoded confidence score (0.8) in LangGraphCompiler by implementing dynamic confidence calculation based on AgentResponse quality metrics.

## Problem
The LangGraphCompiler was hardcoding `confidence: 0.8` when creating agent outputs for synthesis (line 843), ignoring the actual quality and success of the agent execution.

## Solution

### 1. Added Confidence Field to AgentResponse
- Added optional `confidence` field to `AgentResponse` dataclass
- Implements automatic calculation via `__post_init__` if not explicitly provided
- Factors considered in calculation:
  - **Error presence**: Major penalty (0.3) if error exists
  - **Output length**: Penalty (-0.3) for very short outputs (<10 chars)
  - **Reasoning presence**: Bonus (+0.1) for detailed reasoning (>20 chars)
  - **Tool call success rate**: Penalty based on failed tool calls
    - <50% success: -0.2
    - <100% success: -0.1

### 2. Updated LangGraphCompiler
- Changed line 843 from `"confidence": 0.8` to `"confidence": response.confidence"`
- Now uses dynamically calculated confidence from AgentResponse

## Files Modified
- `src/agents/base_agent.py` - Added confidence field and calculation logic
- `src/compiler/langgraph_compiler.py` - Use response.confidence instead of hardcoded 0.8

## Testing
Verified confidence calculation with various scenarios:
- No error: confidence = 1.0
- With error: confidence = 0.3
- Short output: confidence = 0.7
- With reasoning: confidence = 1.0
- Mixed tool success (50%): confidence = 0.6

## Impact
- **Benefits**: More accurate confidence scores reflecting actual agent performance
- **Backward Compatibility**: Fully compatible - confidence auto-calculates if not provided
- **Performance**: Negligible - simple calculations on already-available fields

## Related
- Task: cq-p3-01
- Issue: Hardcoded confidence scores don't reflect actual agent performance
- Improves: Multi-agent synthesis quality by providing realistic confidence metrics
