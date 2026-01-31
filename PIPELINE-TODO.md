# Pipeline Improvement TODO

**Date:** 2026-01-28
**Quick reference for tomorrow's work**

---

## Phase 1: Fix JSON Generation (Critical - Start Here)

### Tasks

- [ ] **Update code-reviewer agent template**
  - File: Find code-reviewer agent prompt template
  - Add: Instructions to use `json.dumps()` instead of string concatenation
  - Add: Validation step before returning JSON
  - Add: Examples of correct approach

- [ ] **Create schema validation script**
  - File: `~/.claude/skills/review-code/helpers/validate-task-schema.py`
  - Purpose: Validate JSON against schema
  - Return: Clear error messages with context

- [ ] **Create auto-fix script**
  - File: `~/.claude/skills/review-code/helpers/validate-and-fix-json.sh`
  - Fix: `],` → `},` pattern
  - Fix: Trailing commas
  - Retry: Validation after fix

- [ ] **Test with one agent**
  - Run: Single code-reviewer on small module (src/cache/)
  - Verify: JSON is valid with `jq empty`
  - Check: No `],` vs `},` errors

- [ ] **Roll out to all 8 agents**
  - Apply: Same changes to all code-reviewer prompts
  - Test: Full `/review-code` run
  - Verify: All JSON files valid

**Success Criteria:**
✅ 0 JSON syntax errors in test run
✅ No manual fixes required
✅ All validation passes automatically

**Time Estimate:** 4-6 hours

---

## Phase 2: Parallel Task Creation (High Priority)

### Tasks

- [ ] **Add JSON splitting logic**
  - File: `/review-code` skill, after aggregation
  - Split: By priority (critical, high, medium, low)
  - Output: 4 separate JSON files
  - Each: Proper metadata wrapper

- [ ] **Create task-creator agent instructions**
  - File: `~/.claude/skills/review-code/task-creator-agent.md`
  - Define: Clear job description
  - Process: Validate → Create → Generate specs → Report
  - Error handling: Continue on failures, report summary

- [ ] **Update /review-code to spawn parallel agents**
  - Add: Task() calls for 4 task-creator agents
  - Pass: Each gets different JSON file
  - Flag: `run_in_background=true`
  - Wait: For all to complete

- [ ] **Add result aggregation**
  - Collect: Results from all 4 agents
  - Display: Summary (X/Y tasks created, failures)
  - Report: Timing, errors, next steps

- [ ] **Test full pipeline**
  - Run: `/review-code --create-all`
  - Verify: 4 agents run in parallel
  - Check: All 51 tasks created
  - Measure: Completion time (target: <1min)

**Success Criteria:**
✅ 4 agents run in parallel (not sequential)
✅ All 51 tasks created successfully
✅ Completion time < 1 minute
✅ No manual steps required

**Time Estimate:** 6-8 hours

---

## Phase 3: Integration & Polish (Nice to Have)

### Tasks

- [ ] **Make /create-task-spec atomic**
  - Change: Call `task-add-detailed` automatically
  - Remove: Requirement for manual task-add first
  - Result: One operation creates task + spec

- [ ] **Add --auto flag**
  - Skip: Confirmation prompts
  - Skip: "Not approved" warnings
  - Purpose: Full automation mode

- [ ] **Add adaptive parallelization**
  - Detect: API tier from rate limits
  - Adjust: Agent count (4-5 for Tier 1, 8-10 for Tier 2)
  - Display: "Using X agents for Tier Y"

- [ ] **Improve error messages**
  - Show: Context around error
  - Suggest: Possible fixes
  - Format: Clear, actionable

- [ ] **Add retry logic**
  - Max: 3 retries per agent
  - Exponential: Backoff between retries
  - Fallback: Manual mode if all retries fail

**Success Criteria:**
✅ Pipeline runs without confirmations
✅ Adapts to API tier automatically
✅ Clear error messages
✅ Automatic retry on failure

**Time Estimate:** 4-6 hours

---

## Quick Commands Reference

```bash
# Validate JSON file
jq empty .claude-coord/reports/code-review-*.tasks.json

# Count tasks in JSON
jq '[.tasks[] | select(.enabled)] | length' file.json

# Test schema validation (after creating script)
~/.claude/skills/review-code/helpers/validate-task-schema.py file.json

# Run full pipeline (after Phase 2)
/review-code --create-all

# Check coordination system tasks
.claude-coord/claude-coord.sh task-list | grep code-

# View task spec
.claude-coord/task-spec-helpers.sh task-spec code-med-god-class-01
```

---

## Testing Checklist

### After Phase 1:
- [ ] Run /review-code on full codebase
- [ ] Check all JSON files: `jq empty *.json`
- [ ] Verify 0 syntax errors
- [ ] No manual fixes needed

### After Phase 2:
- [ ] Clean existing tasks
- [ ] Run /review-code --create-all
- [ ] Don't touch keyboard (full automation test)
- [ ] Verify 51 tasks created
- [ ] Check completion time (<1 min target)

### After Phase 3:
- [ ] Test tier detection
- [ ] Test error recovery (simulate failure)
- [ ] Test retry logic
- [ ] Full end-to-end run

---

## Files to Create/Modify

### New Files:
1. `~/.claude/skills/review-code/helpers/validate-task-schema.py`
2. `~/.claude/skills/review-code/helpers/validate-and-fix-json.sh`
3. `~/.claude/skills/review-code/task-creator-agent.md`

### Files to Modify:
1. Code-reviewer agent prompt template (find location)
2. `~/.claude/skills/review-code/SKILL.md` (add splitting + parallel logic)
3. `/create-task-spec` skill (make atomic, add --auto)

---

## Priority Order

**Day 1 (Tomorrow):**
1. Phase 1: Fix JSON generation (4-6 hours)
2. Test thoroughly
3. If successful, start Phase 2

**Day 2:**
1. Complete Phase 2: Parallel task creation (6-8 hours)
2. Test full pipeline
3. Document any issues

**Day 3:**
1. Phase 3: Polish (4-6 hours)
2. Final testing
3. Update documentation

---

## Expected Outcomes

**After Phase 1:**
- 0 JSON syntax errors (vs 4 per session currently)
- JSON generation is bulletproof
- Ready for Phase 2

**After Phase 2:**
- Full automation (0 manual steps)
- 4x faster task creation (parallel)
- 51 tasks created in ~45 seconds

**After Phase 3:**
- Production-ready pipeline
- Adapts to API tier
- Robust error handling
- Great user experience

---

## Notes

- 8 parallel agents working well (Tier 2 confirmed)
- Cost ~$17 per full review (acceptable)
- Each phase is independent (can roll back)
- Focus: Automation + error elimination
- Start small, test, then expand

---

## Questions to Resolve

- [ ] Where is code-reviewer agent prompt template?
- [ ] Should splitting be by priority or category? (Recommend: priority)
- [ ] Should --create-all be default or opt-in? (Recommend: opt-in)
- [ ] Max retries before giving up? (Recommend: 3)

---

**Ready to start Phase 1 tomorrow.**
**See PIPELINE-IMPROVEMENTS.md for full details.**
