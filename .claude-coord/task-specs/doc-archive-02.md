# Task: doc-archive-02 - Archive fix summaries and session docs

**Priority:** CRITICAL (P1)
**Effort:** 15 minutes
**Status:** pending
**Owner:** unassigned

---

## Summary

Archive 5 historical documents (3 fix summaries + 2 session summaries) that document completed work. These clutter the root and docs/ directories but should be preserved for historical reference.

---

## Files to Create

- `docs/archive/fixes/README.md` - Explains archived fixes
- `docs/archive/session_summaries/README.md` - Explains archived sessions

---

## Files to Move

### Fix Summaries (root → docs/archive/fixes/):
1. `DEMO_FIXES.md` → `docs/archive/fixes/DEMO_FIXES.md`
2. `GANTT_CHART_FIXES.md` → `docs/archive/fixes/GANTT_CHART_FIXES.md`
3. `ALL_DEMO_FIXES_SUMMARY.md` → `docs/archive/fixes/ALL_DEMO_FIXES_SUMMARY.md`

### Session Summaries (docs/ → docs/archive/session_summaries/):
4. `docs/SESSION_SUMMARY.md` → `docs/archive/session_summaries/SESSION_SUMMARY.md`
5. `docs/FINAL_SESSION_SUMMARY.md` → `docs/archive/session_summaries/FINAL_SESSION_SUMMARY.md`

---

## Acceptance Criteria

### Core Functionality
- [ ] Create `docs/archive/fixes/` directory
- [ ] Create `docs/archive/session_summaries/` directory
- [ ] Move all 3 fix summary files from root to archive/fixes/
- [ ] Move all 2 session summary files from docs/ to archive/session_summaries/
- [ ] Create README.md in both subdirectories

### Link Updates
- [ ] Check if README.md or other docs reference these files
- [ ] Update links to point to archive/ locations
- [ ] Verify no broken links remain

### Cleanup
- [ ] Confirm root directory has 3 fewer files
- [ ] Confirm docs/ has 2 fewer files
- [ ] Verify all files preserved with original content

---

## Implementation Details

### Step 1: Create directory structure
```bash
mkdir -p docs/archive/fixes
mkdir -p docs/archive/session_summaries
```

### Step 2: Create README for fixes archive
Create `docs/archive/fixes/README.md`:

```markdown
# Fixes Archive

This directory contains historical fix summaries from early project development.

## Documents

- **DEMO_FIXES.md**: Demo and visualization fixes (2026-01)
- **GANTT_CHART_FIXES.md**: Gantt chart generation fixes
- **ALL_DEMO_FIXES_SUMMARY.md**: Consolidated fix summary

## Status

All fixes documented here have been completed and incorporated into the codebase. For current issues, see the GitHub issues tracker.

## Related

- Implementation details in `/changes/` directory
- Milestone reports in `/docs/milestones/`
```

### Step 3: Create README for session archive
Create `docs/archive/session_summaries/README.md`:

```markdown
# Session Summaries Archive

This directory contains historical development session summaries.

## Purpose

These summaries capture key decisions, progress, and learnings from development sessions.

## Documents

- **SESSION_SUMMARY.md**: Earlier development session
- **FINAL_SESSION_SUMMARY.md**: Later development session

## Current Status

For current project status, see:
- `/README.md` - Latest status and milestones
- `/docs/milestones/` - Milestone completion reports
```

### Step 4: Move files using git
```bash
# Move fix summaries
git mv DEMO_FIXES.md docs/archive/fixes/
git mv GANTT_CHART_FIXES.md docs/archive/fixes/
git mv ALL_DEMO_FIXES_SUMMARY.md docs/archive/fixes/

# Move session summaries
git mv docs/SESSION_SUMMARY.md docs/archive/session_summaries/
git mv docs/FINAL_SESSION_SUMMARY.md docs/archive/session_summaries/
```

### Step 5: Check for references
```bash
# Check README and docs for references
grep -r "DEMO_FIXES\|GANTT_CHART_FIXES\|SESSION_SUMMARY" README.md docs/*.md --include="*.md"
```

---

## Test Strategy

### Verification Steps:

1. **Directory structure check:**
   ```bash
   ls docs/archive/fixes/
   # Should show: DEMO_FIXES.md, GANTT_CHART_FIXES.md, ALL_DEMO_FIXES_SUMMARY.md, README.md

   ls docs/archive/session_summaries/
   # Should show: SESSION_SUMMARY.md, FINAL_SESSION_SUMMARY.md, README.md
   ```

2. **Root cleanup check:**
   ```bash
   ls *FIXES*.md 2>/dev/null
   # Should return nothing
   ```

3. **Docs cleanup check:**
   ```bash
   ls docs/SESSION*.md docs/FINAL*.md 2>/dev/null
   # Should return nothing
   ```

4. **Content verification:**
   ```bash
   # Verify files not corrupted
   wc -l docs/archive/fixes/*.md docs/archive/session_summaries/*.md
   ```

---

## Success Metrics

- [ ] 3 fix summaries moved to archive/fixes/
- [ ] 2 session summaries moved to archive/session_summaries/
- [ ] 2 README files created
- [ ] Root directory decluttered (3 fewer files)
- [ ] docs/ directory decluttered (2 fewer files)
- [ ] No broken links to archived files
- [ ] Git history preserved

---

## Dependencies

- **Blocked by:** None (can start immediately)
- **Blocks:** None (independent task)
- **Related:**
  - doc-archive-01 (uses same archive/ directory)
  - doc-update-01 (INDEX.md should acknowledge archive)

---

## Design References

- Documentation analysis: 45 debt items identified
- Fix summaries marked as "Low Value Documentation" (Debt Item #3)
- Session summaries marked for archival (Debt Item #9)

---

## Notes

- Archive preserves history - don't delete these files
- Fix summaries document completed work, no longer actionable
- Session summaries provide historical context for decisions
- Future fix summaries should go directly to archive/ when created
- Can run in parallel with doc-archive-01 (different file sets)
- Total time: ~15 minutes including verification
