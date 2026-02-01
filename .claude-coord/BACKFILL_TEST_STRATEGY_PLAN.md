# Backfill Test Strategy Implementation Plan

**Task:** Add test strategy sections to 128 crit/high task specs that are missing them

**Status:** Implementation plan ready
**Estimated:** 10 hours total (4 minutes per spec)
**Target:** .claude-coord/task-specs/*.md files

---

## Problem Statement

**Current State:**
- 492 total task specs
- 128 crit/high specs missing test strategy section
- 28.5% of specs lack test strategy
- This is a validation requirement for crit/high tasks

**Impact:**
- Tasks implemented without clear test plan
- Inadequate test coverage
- No verification strategy documented

---

## Implementation Approach

### Phase 1: Identification (30 minutes)

**Find specs needing backfill:**
```bash
# Find crit/high specs without test strategy
cd .claude-coord/task-specs

for spec in code-crit-*.md code-high-*.md test-crit-*.md test-high-*.md; do
  if ! grep -q "## Test Strategy" "$spec" 2>/dev/null; then
    echo "$spec"
  fi
done > ../backfill-list.txt

# Count
wc -l ../backfill-list.txt
```

### Phase 2: Template Preparation (30 minutes)

**Create test strategy template:**
```markdown
## Test Strategy

### Unit Tests
- **File:** `tests/test_<module>/<test_file>.py`
- **Coverage Target:** > 80%

**Test Cases:**
- [ ] Happy path: <describe expected behavior>
- [ ] Error handling: <describe error cases>
- [ ] Edge cases: <describe boundary conditions>

### Integration Tests
- **File:** `tests/integration/test_<feature>_integration.py`

**Scenarios:**
- [ ] Integration with <component A>
- [ ] Integration with <component B>
- [ ] End-to-end workflow

### Test Data
- Fixtures: `tests/fixtures/<fixture_name>.py`
- Mock data: <describe mock requirements>

### Acceptance Criteria for Tests
- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] Coverage >= 80%
- [ ] No flaky tests
```

### Phase 3: Automated Backfill (2 hours)

**Script to add test strategy:**
```python
#!/usr/bin/env python3
"""
Backfill test strategy to task specs.

Usage: python backfill_test_strategy.py [--dry-run]
"""
import re
from pathlib import Path

TEMPLATE = '''
## Test Strategy

### Unit Tests
- **Coverage Target:** > 80%

**Test Cases:**
- [ ] Happy path functionality
- [ ] Error handling
- [ ] Edge cases

### Integration Tests
**Scenarios:**
- [ ] End-to-end workflow validation

### Acceptance Criteria
- [ ] All tests pass
- [ ] Coverage target met
'''

def needs_test_strategy(spec_path: Path) -> bool:
    """Check if spec needs test strategy."""
    content = spec_path.read_text()
    return '## Test Strategy' not in content

def add_test_strategy(spec_path: Path, dry_run=False):
    """Add test strategy section to spec."""
    content = spec_path.read_text()

    # Insert before "## Related Tasks" or at end
    if '## Related Tasks' in content:
        parts = content.split('## Related Tasks')
        new_content = parts[0] + TEMPLATE + '\n## Related Tasks' + parts[1]
    else:
        new_content = content + '\n' + TEMPLATE

    if not dry_run:
        spec_path.write_text(new_content)
        print(f"✓ Added test strategy to {spec_path.name}")
    else:
        print(f"Would add test strategy to {spec_path.name}")

def main():
    import sys
    dry_run = '--dry-run' in sys.argv

    specs_dir = Path('.claude-coord/task-specs')
    patterns = ['code-crit-*.md', 'code-high-*.md',
                'test-crit-*.md', 'test-high-*.md']

    count = 0
    for pattern in patterns:
        for spec in specs_dir.glob(pattern):
            if needs_test_strategy(spec):
                add_test_strategy(spec, dry_run)
                count += 1

    print(f"\nProcessed {count} specs")

if __name__ == '__main__':
    main()
```

### Phase 4: Manual Review & Customization (6-7 hours)

**For each spec:**
1. **Read the task description** (1 min)
2. **Identify test requirements** (1 min)
3. **Customize template** (2 mins)
   - Add specific test file paths
   - List actual test cases
   - Define fixtures needed
4. **Verify** (30 sec)

**Time per spec:** ~4 minutes × 128 specs = 512 minutes (~8.5 hours)

**Optimization:** Batch similar specs together

---

## Customization Examples

### Example 1: API Endpoint Test

```markdown
## Test Strategy

### Unit Tests
- **File:** `tests/test_api/test_auth_endpoints.py`

**Test Cases:**
- [ ] POST /auth/login with valid credentials → 200 OK + token
- [ ] POST /auth/login with invalid password → 401 Unauthorized
- [ ] POST /auth/login with missing fields → 400 Bad Request
- [ ] POST /auth/refresh with valid token → 200 OK + new token
- [ ] POST /auth/refresh with expired token → 401 Unauthorized

### Integration Tests
- **File:** `tests/integration/test_auth_flow.py`

**Scenarios:**
- [ ] Complete login → access protected resource → logout flow
- [ ] Token refresh before expiration
- [ ] Concurrent login attempts from same user

### Test Data
- Fixtures: `tests/fixtures/users.py` (test users with various roles)
- Mock: External OAuth provider responses
```

### Example 2: Database Migration Test

```markdown
## Test Strategy

### Unit Tests
- **File:** `tests/test_migrations/test_add_user_roles.py`

**Test Cases:**
- [ ] Migration runs successfully on empty database
- [ ] Migration runs successfully on populated database
- [ ] Rollback restores previous state
- [ ] Foreign key constraints maintained
- [ ] Indexes created correctly

### Integration Tests
- **File:** `tests/integration/test_migration_e2e.py`

**Scenarios:**
- [ ] Migrate production-like dataset (10k records)
- [ ] Verify data integrity after migration
- [ ] Check query performance on new schema

### Test Data
- Fixtures: `tests/fixtures/legacy_schema.sql`
- Generate: 10k test records with `tests/generators/user_data.py`
```

---

## Quality Gates

Before marking complete:
- [ ] All 128 specs have test strategy section
- [ ] Test strategies are specific (not just template)
- [ ] File paths are correct
- [ ] Test cases are relevant to task
- [ ] Acceptance criteria included
- [ ] Validation passes: `coord task-create` accepts specs

---

## Validation Script

```bash
# Verify all crit/high specs have test strategy
cd .claude-coord/task-specs

missing=0
for spec in code-crit-*.md code-high-*.md test-crit-*.md test-high-*.md; do
  if [ -f "$spec" ] && ! grep -q "## Test Strategy" "$spec"; then
    echo "❌ Missing: $spec"
    ((missing++))
  fi
done

if [ $missing -eq 0 ]; then
  echo "✅ All crit/high specs have test strategy"
else
  echo "❌ $missing specs still missing test strategy"
  exit 1
fi
```

---

## Progress Tracking

**Completion Checklist:**
- [ ] Phase 1: Identification complete (128 specs identified)
- [ ] Phase 2: Template created and tested
- [ ] Phase 3: Automated backfill script written and tested
- [ ] Phase 4: Manual customization (track progress in batches of 10)
  - [ ] Batch 1: code-crit-* (0/X complete)
  - [ ] Batch 2: code-high-* (0/X complete)
  - [ ] Batch 3: test-crit-* (0/X complete)
  - [ ] Batch 4: test-high-* (0/X complete)
- [ ] Quality gates passed
- [ ] Validation script confirms 100% coverage

**Estimated Timeline:**
- Week 1: Phases 1-3 (automation)
- Week 2: Phase 4 batches 1-2 (code specs)
- Week 3: Phase 4 batches 3-4 (test specs) + validation

---

## Next Steps

1. **Run identification script** to get exact count and list
2. **Test backfill script** on 3-5 specs (dry-run, then real)
3. **Customize first 10 specs** to establish pattern
4. **Batch process** remaining specs (10 per session)
5. **Validate** and create PR

**Ready to execute:** ✅ All tools and templates prepared

---

**Last Updated:** 2026-02-01
