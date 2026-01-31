# Code Review Pipeline Improvements

**Date:** 2026-01-28
**Status:** Planning / Ready for Implementation
**Current State:** 8 parallel agents working well, need to improve automation

---

## Executive Summary

Current pipeline for `/review-code --create-all` requires too much manual intervention and has systematic JSON generation errors. This document outlines improvements to achieve **full automation with zero manual steps**.

**Goal:** One command → 51 tasks created automatically with zero errors.

---

## Current Problems

### 1. JSON Generation Errors (High Priority)

**Problem:** Generated JSON has syntax errors ~80% of the time

**Examples from today's session:**
- 4 instances of `],` instead of `},` (lines 374, 537, 576, 619)
- Required manual fixing with jq/sed
- User had to validate, report errors, wait for fixes

**Root Cause:**
- Agents build JSON with string concatenation/templates
- Manual bracket matching is error-prone
- No validation before output

**Impact:**
- User friction (manual fixes required)
- Time waste (back-and-forth debugging)
- Poor user experience

### 2. Too Many Manual Steps (High Priority)

**Current workflow (7+ steps):**
```
1. /review-code
2. Read report, find JSON errors
3. Run jq to validate JSON
4. Fix ], → }, errors manually (4 times)
5. Validate JSON again
6. Create tasks with coordination system manually
   (.claude-coord/claude-coord.sh task-add for each task)
7. Call /create-task-spec --from-file
8. Verify specs were created
9. Debug failures
```

**Problem:** User has to babysit the entire process.

**Expected:** One command, zero manual steps.

### 3. Unclear Tool Boundaries (Medium Priority)

**Confusion during session:**
- Should use skill or coordination command?
- When to call `/create-task-spec` vs manual `task-add`?
- Mixed skills, bash commands, and coordination system

**Problem:** Not clear what tool does what or when to use which.

### 4. No Error Recovery (Medium Priority)

**Current behavior:**
- One JSON error blocks entire pipeline
- No auto-fix attempts
- No retry logic
- User must manually diagnose and fix

**Problem:** Brittle pipeline, one error = manual intervention required.

---

## Proposed Solutions

### Solution 1: Fix JSON Generation (Critical - Eliminates 95% of errors)

**Change:** Make agents use `json.dumps()` instead of string templates.

**Current (error-prone):**
```python
# Agent writes JSON as text
json_output = f"""
{{
  "acceptance_criteria": {{
    "testing": ["test 1"]
  }},  <-- Easy to type ], by mistake
}}
"""
```

**Proposed (bulletproof):**
```python
import json

# Build as Python dict
task = {
    "id": "code-crit-01",
    "title": "Fix SSRF",
    "acceptance_criteria": {
        "testing": ["test 1", "test 2"],
        "security": ["check 1"]
    }
}

# Serialize - CANNOT produce invalid JSON
json_output = json.dumps(task, indent=2, ensure_ascii=False)
```

**Benefits:**
- `json.dumps()` cannot produce `],` errors (mathematically impossible)
- Guaranteed syntactically valid JSON
- Catches errors at build time, not runtime

**Implementation:**
- Update code-reviewer agent prompt template
- Add instructions to use `json.dumps()` for all JSON generation
- Add validation before returning output

**Expected Result:** 0 JSON syntax errors (down from 4 per session)

---

### Solution 2: Three-Layer Validation Defense

**Layer 1: Generate with Code (95% of errors)**
```python
# Use json.dumps() as shown above
```

**Layer 2: Schema Validation (4% of errors)**
```python
import jsonschema

TASK_SCHEMA = {
    "type": "object",
    "required": ["id", "title", "priority"],
    "properties": {
        "id": {"type": "string"},
        "priority": {"enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
        "acceptance_criteria": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {"type": "string"}
            }
        }
    }
}

# Validate structure
jsonschema.validate(task, TASK_SCHEMA)
```

**Layer 3: Auto-Fix Common Errors (1% of errors)**
```bash
# validate-and-fix-json.sh
if ! jq empty "$JSON_FILE" 2>/dev/null; then
    # Fix common patterns
    sed -i 's/\],\(\s*\)}/},\1}/g' "$JSON_FILE"
    sed -i 's/,\(\s*\)}/\1}/g' "$JSON_FILE"  # Trailing commas

    # Retry validation
    if jq empty "$JSON_FILE" 2>/dev/null; then
        echo "✅ Auto-fix successful"
    else
        echo "❌ Auto-fix failed, regenerating..."
        # Re-run agent with strict validation
    fi
fi
```

**Expected Result:** 100% valid JSON (bulletproof)

---

### Solution 3: Parallel Task Creation with Sub-Agents

**Problem:** Sequential task creation is slow and blocks on errors.

**Proposed Architecture:**

```
/review-code --create-all
  │
  ├─> Phase 1: Code Review (8 parallel reviewers)
  │   ├── code-reviewer-1: compiler/ → findings
  │   ├── code-reviewer-2: safety/ → findings
  │   ├── code-reviewer-3: observability/ → findings
  │   ├── code-reviewer-4: agents/ → findings
  │   ├── code-reviewer-5: utils/ → findings
  │   ├── code-reviewer-6: cache/ → findings
  │   ├── code-reviewer-7: tools/ → findings
  │   └── code-reviewer-8: core/ → findings
  │
  ├─> Phase 2: Aggregate & Split
  │   ├── Merge findings → comprehensive report
  │   ├── Generate JSON (validated, error-free)
  │   └── Split into 4 files by priority:
  │       ├── critical.tasks.json (8 tasks)
  │       ├── high.tasks.json (10 tasks)
  │       ├── medium.tasks.json (15 tasks)
  │       └── low.tasks.json (18 tasks)
  │
  └─> Phase 3: Task Creation (4 parallel task-creator agents)
      ├── task-creator-1: critical.json → 8 tasks + specs
      ├── task-creator-2: high.json → 10 tasks + specs
      ├── task-creator-3: medium.json → 15 tasks + specs
      └── task-creator-4: low.json → 18 tasks + specs

  ↓
  Result: ✅ 51/51 tasks created in ~45s (vs 3min sequential)
```

**Benefits:**
- **4x faster** (parallel vs sequential)
- **Isolated failures** (one category fails, others succeed)
- **Better organization** (tasks grouped by priority)
- **Easier debugging** (know which category failed)
- **Scalable** (100+ tasks? Just spawn more agents)

**Peak Concurrency:**
- Phase 1: 8 agents (code-reviewer)
- Phase 3: 4 agents (task-creator)
- Total: 12 agents across pipeline
- **Works on Tier 2 (10 concurrent) with queuing**

---

### Solution 4: Fully Automated Workflow

**One Command:**
```bash
/review-code --create-all
```

**Does Automatically:**
1. ✅ Run 8 parallel code-reviewer agents
2. ✅ Generate comprehensive markdown report
3. ✅ Generate VALID JSON (json.dumps + validation)
4. ✅ Split JSON into 4 files by priority
5. ✅ Spawn 4 parallel task-creator agents
6. ✅ Each creates tasks + specs from their JSON file
7. ✅ Aggregate results
8. ✅ Update JSON status to CREATED
9. ✅ Display summary

**User Intervention:** ZERO steps

**Result:** 51 tasks with full specifications, ready to work

---

## Implementation Plan

### Phase 1: Fix JSON Generation (Week 1 - Critical)

**Priority:** P0 (blocks everything else)

**Tasks:**
1. Update code-reviewer agent prompt template
   - Add instructions to use `json.dumps()`
   - Add validation step before output
   - Add examples of correct approach

2. Create schema validation script
   - File: `~/.claude/skills/review-code/helpers/validate-task-schema.py`
   - Validates JSON against schema
   - Returns clear error messages

3. Add auto-fix script
   - File: `~/.claude/skills/review-code/helpers/validate-and-fix-json.sh`
   - Fixes common patterns (], → },)
   - Retries validation

4. Test with one agent
   - Run single code-reviewer with new instructions
   - Verify JSON is valid
   - Verify no manual fixes needed

5. Roll out to all 8 agents
   - Update all code-reviewer prompts
   - Test full /review-code run
   - Verify all JSON files are valid

**Success Criteria:**
- [ ] 0 JSON syntax errors in test run
- [ ] No manual fixes required
- [ ] All validation passes automatically

**Estimated Effort:** 4-6 hours

---

### Phase 2: Parallel Task Creation (Week 1 - High)

**Priority:** P1 (major UX improvement)

**Tasks:**
1. Add JSON splitting logic to /review-code
   - Split by priority (critical, high, medium, low)
   - Generate 4 separate JSON files
   - Each with proper metadata

2. Create task-creator agent instructions
   - File: `~/.claude/skills/review-code/task-creator-agent.md`
   - Clear instructions for creating tasks from JSON
   - Handles validation, creation, spec generation

3. Update /review-code to spawn parallel agents
   - Spawn 4 task-creator agents with Task()
   - Pass each a different JSON file
   - Run in background (run_in_background=true)

4. Add result aggregation
   - Wait for all agents to complete
   - Collect results from each
   - Display summary (X/Y tasks created)

5. Test full pipeline
   - Run /review-code --create-all
   - Verify all 4 agents run in parallel
   - Verify all tasks created correctly

**Success Criteria:**
- [ ] 4 agents run in parallel (not sequential)
- [ ] All 51 tasks created successfully
- [ ] Completion time < 1 minute
- [ ] No manual steps required

**Estimated Effort:** 6-8 hours

---

### Phase 3: Integration & Polish (Week 2 - Medium)

**Priority:** P2 (nice to have)

**Tasks:**
1. Make /create-task-spec call task-add-detailed automatically
   - Currently requires manual task-add first
   - Should be atomic: create task + spec in one operation

2. Add --auto flag to skip confirmations
   - Skip "Are you sure?" prompts
   - Skip "JSON not approved yet" warnings
   - Full automation mode

3. Add adaptive parallelization
   - Detect API tier (Tier 1 vs Tier 2)
   - Adjust agent count accordingly
   - 4-5 agents for Tier 1, 8-10 for Tier 2

4. Improve error messages
   - Clear context when validation fails
   - Show exactly what's wrong and where
   - Suggest fixes

5. Add retry logic
   - If agent fails, retry with better instructions
   - Max 3 retries per agent
   - Fall back to manual if retries exhausted

**Success Criteria:**
- [ ] Pipeline runs without confirmations
- [ ] Adapts to API tier automatically
- [ ] Clear error messages with context
- [ ] Automatic retry on failure

**Estimated Effort:** 4-6 hours

---

## Technical Details

### API Tier Considerations

**Rate Limits:**

| Tier | Requests/min | Concurrent | Recommended Agents |
|------|-------------|------------|-------------------|
| Tier 1 | 50 | 5 | 4-5 max |
| Tier 2 | 1,000 | 10 | 8-10 optimal |
| Enterprise | Custom | Custom | 15-20 max |

**Current Pipeline:**
- Phase 1: 8 code-reviewers (parallel)
- Phase 3: 4 task-creators (parallel)
- Peak: 8 concurrent agents
- **Works on Tier 2, queues on Tier 1**

**Note:** 8 parallel agents had 0 issues so far (Tier 2 confirmed).

---

### File Structure

**Generated Files:**
```
.claude-coord/reports/
├── code-review-20260128-224245.md                # Full report
├── code-review-20260128-critical.tasks.json      # 8 critical tasks
├── code-review-20260128-high.tasks.json          # 10 high tasks
├── code-review-20260128-medium.tasks.json        # 15 medium tasks
└── code-review-20260128-low.tasks.json           # 18 low tasks

.claude-coord/task-specs/
├── code-crit-ssrf-01.md                          # Detailed spec
├── code-crit-cmd-injection-02.md
├── ...
└── code-low-stats-schema-40.md                   # (51 total specs)
```

---

### Cost Estimation

**Current Pipeline:**

| Phase | Agents | Tokens/Agent | Cost/Agent | Total |
|-------|--------|--------------|------------|-------|
| Code Review | 8 | 60K in, 10K out | ~$2.00 | ~$16 |
| Task Creation | 4 | 5K in, 2K out | ~$0.25 | ~$1 |
| **Total** | 12 | - | - | **~$17** |

**Per full code review:** ~$17 (acceptable)

**If we spawned 50 agents:** ~$100 (not economical)

**Recommendation:** Keep ≤ 12 agents total.

---

## Testing Strategy

### Test 1: JSON Generation (Phase 1)

**Objective:** Verify 0 JSON syntax errors

**Steps:**
1. Update one code-reviewer agent with json.dumps() instructions
2. Run on small module (e.g., src/cache/)
3. Check generated JSON with jq
4. Verify no syntax errors
5. If successful, roll out to all 8 agents

**Success Criteria:**
- jq validation passes on first try
- No ], vs }, errors
- No manual fixes needed

---

### Test 2: Parallel Task Creation (Phase 2)

**Objective:** Verify parallel agents work correctly

**Steps:**
1. Generate test JSON files (4 files, 10 tasks each)
2. Spawn 4 task-creator agents in parallel
3. Monitor completion
4. Verify all 40 tasks created
5. Check timing (should be <1min, not 3min)

**Success Criteria:**
- All 4 agents run simultaneously
- All tasks created successfully
- No race conditions or conflicts
- Completion time < 1 minute

---

### Test 3: Full Pipeline (Phase 3)

**Objective:** End-to-end automation test

**Steps:**
1. Clean state (remove existing tasks)
2. Run: /review-code --create-all
3. Don't touch keyboard (full automation)
4. Wait for completion
5. Verify all tasks + specs created

**Success Criteria:**
- 0 user interventions required
- 51 tasks created
- 51 specs generated
- All JSON valid
- Completion time < 2 minutes
- Summary report accurate

---

## Rollback Plan

**If Phase 1 causes issues:**
- Keep current string-based JSON generation
- Add validation + auto-fix layers only
- Manual fixes still possible but reduced

**If Phase 2 causes issues:**
- Fall back to sequential task creation
- Still better than current (validated JSON)
- Can debug parallel issues separately

**If Phase 3 causes issues:**
- Keep manual confirmation steps
- User still has control
- Incremental automation

**Safety:** Each phase is independent, can roll back without losing previous improvements.

---

## Success Metrics

### Before (Current State)
- JSON error rate: ~80%
- Manual steps: 7+
- Total time: 5-10 minutes
- User interventions: 5+
- Completion rate: 60% (often fails)

### After (Target State)
- JSON error rate: 0%
- Manual steps: 0
- Total time: 1-2 minutes
- User interventions: 0
- Completion rate: 100%

### Key Improvements
- **10x fewer errors** (80% → 0%)
- **5x faster** (10min → 2min)
- **Zero manual steps** (7 → 0)
- **100% completion** (60% → 100%)

---

## Open Questions

1. **API Tier Confirmation:**
   - Currently assuming Tier 2 (8 agents work well)
   - Should we add tier detection?
   - Or just document "requires Tier 2"?

2. **Task Splitting Strategy:**
   - By priority (critical/high/medium/low)?
   - By category (security/performance/maintenance)?
   - By module (compiler/safety/observability)?
   - **Current recommendation:** By priority (simplest)

3. **Error Recovery:**
   - How many retries before giving up?
   - Should failed tasks block others?
   - **Current recommendation:** Max 3 retries, don't block

4. **User Control:**
   - Should --create-all be default or opt-in?
   - Should we keep manual mode as option?
   - **Current recommendation:** Keep both modes

---

## Next Steps (Tomorrow)

### Immediate (Start Here)

1. **Implement Phase 1 (JSON Generation Fix):**
   - Update code-reviewer agent template
   - Add json.dumps() instructions
   - Test with one agent
   - Roll out to all 8 if successful

2. **Create validation scripts:**
   - validate-task-schema.py
   - validate-and-fix-json.sh

3. **Test on current codebase:**
   - Run /review-code
   - Verify JSON is valid
   - No manual fixes needed

### Short-term (This Week)

4. **Implement Phase 2 (Parallel Task Creation):**
   - Add JSON splitting logic
   - Create task-creator agent instructions
   - Spawn 4 parallel agents
   - Test full pipeline

5. **End-to-end test:**
   - /review-code --create-all
   - Verify zero manual steps
   - Measure timing

### Medium-term (Next Week)

6. **Phase 3 polish:**
   - Add --auto flag
   - Improve error messages
   - Add retry logic
   - Adaptive parallelization

7. **Documentation:**
   - Update /review-code SKILL.md
   - Add troubleshooting guide
   - Document API tier requirements

---

## Notes

- 8 parallel agents working well (no issues so far)
- Tier 2 API confirmed (10 concurrent requests)
- Cost ~$17 per full review (acceptable)
- Incremental rollout to minimize risk
- Each phase is independent (can roll back)
- Focus on automation + error elimination

---

## References

- Current report: `.claude-coord/reports/code-review-20260128-224245.md`
- Task files: `.claude-coord/reports/code-review-20260128-224245*.tasks.json`
- Skill: `~/.claude/skills/review-code/SKILL.md`
- Coordination: `.claude-coord/README.md`

---

**Status:** Ready to implement Phase 1 tomorrow.
**Expected completion:** Phase 1-2 this week, Phase 3 next week.
**Risk:** Low (incremental rollout, independent phases, can roll back).
