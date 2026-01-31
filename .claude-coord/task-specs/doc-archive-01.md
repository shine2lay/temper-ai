# Task: doc-archive-01 - Archive task status reports

**Priority:** CRITICAL (P1)
**Effort:** 15 minutes
**Status:** pending
**Owner:** unassigned

---

## Summary

Move 11 completed task status reports from docs/ to a new archive/task_reports/ directory to declutter the main documentation folder. These are historical records that should be preserved but not mixed with active documentation.

---

## Files to Create

- `docs/archive/task_reports/README.md` - Explains purpose of archive, links to current status

---

## Files to Move

Move the following 11 files from `docs/` to `docs/archive/task_reports/`:

1. `docs/TASK_1_PROGRESS_REPORT.md` → `docs/archive/task_reports/TASK_1_PROGRESS_REPORT.md`
2. `docs/TASK_1_FINAL_STATUS.md` → `docs/archive/task_reports/TASK_1_FINAL_STATUS.md`
3. `docs/TASK_2_COMPLETE.md` → `docs/archive/task_reports/TASK_2_COMPLETE.md`
4. `docs/TASK_3_COMPLETE.md` → `docs/archive/task_reports/TASK_3_COMPLETE.md`
5. `docs/TASK_4_COMPLETE.md` → `docs/archive/task_reports/TASK_4_COMPLETE.md`
6. `docs/TASK_5_COMPLETE.md` → `docs/archive/task_reports/TASK_5_COMPLETE.md`
7. `docs/TASK_6_PROGRESS.md` → `docs/archive/task_reports/TASK_6_PROGRESS.md`
8. `docs/TASK_8_COMPLETE.md` → `docs/archive/task_reports/TASK_8_COMPLETE.md`
9. `docs/TASK_9_COMPLETE.md` → `docs/archive/task_reports/TASK_9_COMPLETE.md`
10. `docs/TASK_10_PARTIAL.md` → `docs/archive/task_reports/TASK_10_PARTIAL.md`
11. `docs/TASK_11_PROGRESS.md` → `docs/archive/task_reports/TASK_11_PROGRESS.md`

---

## Acceptance Criteria

### Core Functionality
- [ ] Create `docs/archive/` directory
- [ ] Create `docs/archive/task_reports/` subdirectory
- [ ] Move all 11 TASK_*.md files to archive/task_reports/
- [ ] Create README.md in task_reports/ explaining archive purpose
- [ ] Verify all 11 files successfully moved

### Link Updates
- [ ] Check if any other docs link to TASK_*.md files
- [ ] Update links to point to new archive/ location
- [ ] Run link checker to verify no broken links

### Cleanup
- [ ] Confirm docs/ no longer contains TASK_*.md files
- [ ] Verify archive preserves file contents unchanged

---

## Implementation Details

### Step 1: Create directory structure
```bash
mkdir -p docs/archive/task_reports
```

### Step 2: Create README in archive
Create `docs/archive/task_reports/README.md`:

```markdown
# Task Reports Archive

This directory contains historical task status reports from the documentation reorganization project.

## Purpose

These reports documented progress on quality improvements, test fixes, and documentation tasks completed during 2026-01.

## Current Status

For current project status, see:
- `/README.md` - Overall project status
- `/docs/ROADMAP.md` - Future roadmap
- `/.claude-coord/state.json` - Active task tracking

## Reports

- TASK_1: Test suite stabilization
- TASK_2: Gantt visualization improvements
- TASK_3: Quality quick start guide
- TASK_4-11: Various quality and documentation improvements

All tasks referenced here are now complete.
```

### Step 3: Move files using git (preserves history)
```bash
git mv docs/TASK_1_PROGRESS_REPORT.md docs/archive/task_reports/
git mv docs/TASK_1_FINAL_STATUS.md docs/archive/task_reports/
git mv docs/TASK_2_COMPLETE.md docs/archive/task_reports/
git mv docs/TASK_3_COMPLETE.md docs/archive/task_reports/
git mv docs/TASK_4_COMPLETE.md docs/archive/task_reports/
git mv docs/TASK_5_COMPLETE.md docs/archive/task_reports/
git mv docs/TASK_6_PROGRESS.md docs/archive/task_reports/
git mv docs/TASK_8_COMPLETE.md docs/archive/task_reports/
git mv docs/TASK_9_COMPLETE.md docs/archive/task_reports/
git mv docs/TASK_10_PARTIAL.md docs/archive/task_reports/
git mv docs/TASK_11_PROGRESS.md docs/archive/task_reports/
```

### Step 4: Check for broken links
```bash
# Search for references to TASK_*.md in other docs
grep -r "TASK_[0-9]" docs/*.md README.md
```

---

## Test Strategy

### Verification Steps:

1. **File count check:**
   ```bash
   ls docs/archive/task_reports/ | wc -l
   # Should be 12 (11 task files + 1 README)
   ```

2. **No files left behind:**
   ```bash
   ls docs/TASK_*.md 2>/dev/null
   # Should return nothing (no match)
   ```

3. **Content preservation:**
   ```bash
   # Verify file sizes match (content unchanged)
   ls -lh docs/archive/task_reports/TASK_*.md
   ```

4. **Link validation:**
   ```bash
   # Check for broken links
   grep -r "docs/TASK_" . --include="*.md" | grep -v "archive"
   # Should find no references to old paths
   ```

---

## Success Metrics

- [ ] All 11 TASK_*.md files moved to archive/
- [ ] README.md created in archive/task_reports/
- [ ] docs/ directory has 11 fewer files
- [ ] No broken links referencing old paths
- [ ] Git history preserved (files moved, not deleted)

---

## Dependencies

- **Blocked by:** None (can start immediately)
- **Blocks:** None (independent task)
- **Related:** doc-update-01 (INDEX.md should link to archive)

---

## Design References

- Documentation reorganization analysis (specialist agent reports)
- DOC_TASKS_SUMMARY.md (this task is in Stream 1: ARCHIVAL)

---

## Notes

- Use `git mv` instead of `mv` to preserve file history
- These reports are valuable historical context - archive, don't delete
- Future task reports should go directly to archive/task_reports/ when complete
- This task is fully independent and can run in parallel with other Phase 1 tasks
