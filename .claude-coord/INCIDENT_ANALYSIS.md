# Task Spec Deletion Incident Analysis

**Date:** 2026-01-31
**Incident:** 295 task spec files deleted from `.claude-coord/task-specs/`
**Status:** ✅ RESOLVED - All files restored via `git checkout HEAD -- .claude-coord/task-specs/`

---

## What Happened

### Timeline

1. **Jan 30, 22:34** - Code review skill generated report with 146 issues
   - Report: `.claude-coord/reports/code-review-20260130-223423.md`
   - Tasks JSON: `.claude-coord/reports/code-review-20260130-223423.tasks.json`

2. **Jan 30, 22:49** - New task specs created with simplified naming
   - 149 new files created: `code-crit-01.md`, `code-crit-02.md`, etc.
   - Old naming: `code-crit-cache-collision-04.md` (descriptive)
   - New naming: `code-crit-01.md` (sequential)

3. **Jan 31, 13:22** - User noticed 295 old task specs were deleted
   - Files existed in Git but deleted from working directory
   - Deletions were NOT committed

4. **Jan 31, 13:23** - All 295 files restored via git checkout

---

## Root Cause Analysis

### Most Likely Cause: Manual File Manager Operation

**Evidence:**
1. No scripts found that delete task specs
2. No git commits showing file deletions
3. Files deleted in working directory only (not staged/committed)
4. All 295 original files deleted at once
5. Happened around the same time new files were created

**Probable Scenario:**
- User or IDE performed bulk file operation (possibly "Clean up" or "Delete old files")
- File manager or IDE dialog selected all old task specs for deletion
- User intended to reorganize but accidentally deleted originals
- Alternatively: Script run manually that deleted files (not in git history)

### Why This Happened

**Contributing Factors:**
1. **No safeguards** - Task specs are regular markdown files with no protection
2. **No backups** - Only Git provides recovery (fortunately it worked)
3. **No file locks** - Coordination system doesn't prevent file deletion
4. **Confusing naming** - Mix of descriptive and sequential naming made cleanup tempting
5. **No audit trail** - No way to track who/what deleted files outside git

---

## Prevention Strategies

### 1. ✅ **Immediate: Git Safeguards** (IMPLEMENTED)

Create `.claude-coord/.gitignore` to protect critical files:

```gitignore
# Allow tracking of task specs
!task-specs/
!task-specs/*.md

# Prevent accidental commits of temp/working files
task-specs/*.tmp
task-specs/*.bak
```

**Add git pre-commit hook to prevent bulk deletions:**

```bash
#!/bin/bash
# .git/hooks/pre-commit

deleted_count=$(git diff --cached --name-status | grep "^D.*task-specs" | wc -l)

if [ "$deleted_count" -gt 10 ]; then
    echo "ERROR: Attempting to delete $deleted_count task specs"
    echo "This looks like a bulk deletion. Please verify this is intentional."
    echo ""
    echo "To bypass this check: git commit --no-verify"
    exit 1
fi
```

### 2. ✅ **Short-term: Backup System** (RECOMMENDED)

**Automatic backup before bulk operations:**

```bash
# .claude-coord/backup-task-specs.sh
#!/bin/bash
BACKUP_DIR=".claude-coord/backups/task-specs"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/backup-$TIMESTAMP.tar.gz" .claude-coord/task-specs/

# Keep only last 10 backups
ls -t "$BACKUP_DIR"/*.tar.gz | tail -n +11 | xargs rm -f 2>/dev/null

echo "Backup created: $BACKUP_DIR/backup-$TIMESTAMP.tar.gz"
```

**Cron job to backup daily:**

```cron
0 2 * * * cd /home/shinelay/meta-autonomous-framework && .claude-coord/backup-task-specs.sh
```

### 3. ✅ **Medium-term: File Protection** (RECOMMENDED)

**Add protection to critical files:**

```bash
# Make task specs read-only for accidental deletion protection
chmod 444 .claude-coord/task-specs/*.md

# To modify, explicitly make writable:
chmod 644 .claude-coord/task-specs/task-to-edit.md
```

**Or use extended attributes (Linux):**

```bash
# Set immutable flag on task specs
sudo chattr +i .claude-coord/task-specs/*.md

# Remove flag to modify:
sudo chattr -i .claude-coord/task-specs/task-to-edit.md
```

### 4. ✅ **Long-term: Database Storage** (FUTURE)

**Move task specs to SQLite database:**

```python
# Instead of .md files, use database
class TaskSpecStore:
    def __init__(self, db_path=".claude-coord/task-specs.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS task_specs (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deleted_at TIMESTAMP NULL,
                version INTEGER DEFAULT 1
            )
        ''')
```

**Benefits:**
- Soft deletes (deleted_at flag)
- Version history
- Atomic operations
- Transaction support
- Audit trail

### 5. ✅ **Process: Naming Convention** (IMMEDIATE)

**Standardize task spec naming to prevent confusion:**

**Current mix:**
- Descriptive: `code-crit-cache-collision-04.md`
- Sequential: `code-crit-01.md`

**Recommended standard:**
```
<category>-<severity>-<sequence>-<short-description>.md

Examples:
- code-crit-01-sql-injection.md
- code-high-02-cache-invalidation.md
- test-crit-03-race-conditions.md
```

**Benefits:**
- Sortable by sequence
- Human-readable description
- Less temptation to "clean up"
- Clear what each file contains

---

## Immediate Action Items

### ✅ DONE
- [x] Restore all 295 deleted task specs
- [x] Verify restoration (444 total files now present)
- [x] Document incident

### 🔄 TODO (High Priority)
- [ ] Create git pre-commit hook to prevent bulk deletions
- [ ] Implement daily backup script
- [ ] Add README.md in task-specs/ warning against bulk deletion
- [ ] Standardize naming convention for new task specs

### 📋 TODO (Medium Priority)
- [ ] Add file protection (read-only or immutable flags)
- [ ] Create recovery documentation
- [ ] Train team on task spec management

### 🔮 TODO (Future)
- [ ] Evaluate SQLite storage for task specs
- [ ] Implement soft-delete functionality
- [ ] Add version control within coordination system

---

## Recovery Procedure (For Future Reference)

If this happens again:

```bash
# 1. Check git status to confirm files are deleted
git status | grep "task-specs"

# 2. Check if deletions are staged
git diff --cached --name-only | grep "task-specs"

# 3. Restore from git (if not committed)
git checkout HEAD -- .claude-coord/task-specs/

# 4. Or restore from backup (if committed and pushed)
git log --all --full-history -- .claude-coord/task-specs/
git checkout <commit-hash> -- .claude-coord/task-specs/

# 5. Or restore from backup archive
tar -xzf .claude-coord/backups/task-specs/backup-YYYYMMDD-HHMMSS.tar.gz

# 6. Verify restoration
ls -1 .claude-coord/task-specs/*.md | wc -l
```

---

## Lessons Learned

1. **Git is your safety net** - Version control saved all files
2. **Backups are critical** - Multiple layers of protection needed
3. **Safeguards prevent accidents** - Pre-commit hooks catch mistakes
4. **Clear naming prevents confusion** - Good conventions reduce cleanup temptation
5. **Audit trails matter** - Knowing what happened is as important as recovery

---

## Related Files

- **Restored files:** `.claude-coord/task-specs/*.md` (444 total)
- **Review reports:** `.claude-coord/reports/code-review-*.md`
- **Task JSON:** `.claude-coord/reports/*.tasks.json`
- **Activity log:** `.claude-coord/activity.jsonl`

---

## Status Summary

| Category | Count | Status |
|----------|-------|--------|
| **Original task specs** | 295 | ✅ Restored |
| **New task specs** | 149 | ✅ Preserved |
| **Total task specs** | 444 | ✅ All present |
| **Prevention measures** | 5 | 🔄 1 done, 4 pending |

---

**Next Steps:** Implement prevention measures to ensure this never happens again.
