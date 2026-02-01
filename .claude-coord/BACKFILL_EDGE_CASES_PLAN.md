# Backfill Edge Cases Implementation Plan

**Task:** Add edge case documentation to 430+ task specs

**Status:** Implementation plan ready
**Estimated:** 8 hours total (1 minute per spec)
**Target:** .claude-coord/task-specs/*.md files

---

## Problem Statement

**Current State:**
- 492 total task specs
- Only 19 specs (4.2%) have edge case documentation
- 430+ specs need edge cases added
- Edge cases critical for robust implementations

**Impact:**
- Missing edge case handling in implementations
- Bugs discovered in production
- Inadequate error handling
- Security vulnerabilities overlooked

---

## Edge Case Categories

### 1. Input Edge Cases
- Empty input
- Null/None values
- Maximum length/size
- Minimum length/size
- Special characters
- Unicode/encoding issues
- Malformed data

### 2. State Edge Cases
- Initial state (first run)
- Concurrent access
- Partial completion
- Already completed
- Locked/in-use resources
- Race conditions

### 3. Error Edge Cases
- Network timeout
- Database locked
- Permission denied
- Disk full
- Out of memory
- External service unavailable

### 4. Security Edge Cases
- Path traversal (../)
- Code injection
- XSS attacks
- SQL injection
- Authentication bypass
- Authorization escalation

---

## Implementation Approach

### Phase 1: Template Creation (1 hour)

**Edge Case Template:**
```markdown
## Edge Cases

### Input Edges
- **Empty input:** `function("")` → ValueError("Input required")
- **Null input:** `function(None)` → TypeError("Cannot be None")
- **Max length:** `function("a" * 10000)` → ValueError("Max length 1000")
- **Special chars:** `function("test@#$")` → depends on validation rules
- **Unicode:** `function("test🚀emoji")` → should handle or reject gracefully

### State Edges
- **First run:** No existing data → create default state
- **Already running:** Process lock exists → fail with "Already running"
- **Partial state:** Interrupted mid-operation → resume or rollback
- **Concurrent access:** Two agents modify same resource → second waits for lock

### Error Edges
- **Network timeout:** API call > 30s → retry with backoff (3 attempts)
- **Database locked:** SQLite in use → wait and retry (WAL mode prevents)
- **Permission denied:** File not accessible → clear error message
- **Disk full:** Cannot write → catch OSError, cleanup temp files

### Security Edges
- **Path traversal:** `../../../etc/passwd` → blocked by file access policy
- **Code injection:** `eval()` in input → forbidden by safety policy
- **Long input:** DoS via 10MB string → size validation at API boundary
```

### Phase 2: Automation Script (1 hour)

**Edge case backfill script:**
```python
#!/usr/bin/env python3
"""Add edge case template to task specs."""
from pathlib import Path
import re

EDGE_CASE_TEMPLATE = '''
## Edge Cases

### Input Edges
- **Empty/null input:** How should the implementation handle empty or null values?
- **Boundary values:** Maximum/minimum acceptable input sizes
- **Invalid format:** Malformed or unexpected input format

### State Edges
- **First use:** Behavior when no prior state exists
- **Concurrent access:** Handling simultaneous operations
- **Partial completion:** Recovery from interrupted operations

### Error Edges
- **External failures:** Network timeout, service unavailable
- **Resource constraints:** Disk full, out of memory
- **Permission issues:** Access denied scenarios

### Security Edges
- **Injection attacks:** SQL, code, command injection prevention
- **Path traversal:** Directory escape attempts
- **Denial of service:** Resource exhaustion protection
'''

def categorize_task(spec_path: Path) -> str:
    """Determine task category from filename."""
    name = spec_path.stem

    if name.startswith('code-'):
        return 'code'
    elif name.startswith('test-'):
        return 'test'
    elif name.startswith('docs-'):
        return 'docs'
    elif name.startswith('refactor-'):
        return 'refactor'
    else:
        return 'other'

def get_relevant_edges(category: str) -> str:
    """Get relevant edge cases for task category."""
    templates = {
        'code': '''
## Edge Cases

### Input Validation
- Empty/null inputs
- Boundary values (min/max)
- Invalid data types
- Special characters

### Error Handling
- External service failures
- Database errors
- File system errors
- Permission issues

### Security
- Input sanitization
- Path traversal prevention
- Resource limits
''',
        'test': '''
## Edge Cases

### Test Coverage
- Boundary value testing
- Negative test cases
- Concurrent execution
- Error conditions

### Test Data
- Minimal valid input
- Maximum valid input
- Invalid input variations
- Edge case fixtures
''',
        'docs': '''
## Edge Cases

### Documentation Quality
- Missing sections
- Broken links
- Code examples that don't run
- Outdated screenshots

### Accessibility
- Screen reader compatibility
- Different screen sizes
- Print formatting
''',
        'refactor': '''
## Edge Cases

### Backward Compatibility
- Existing API usage
- Data migration
- Configuration changes
- Rollback scenarios

### Testing
- Regression testing
- Performance impact
- Integration breakage
'''
    }

    return templates.get(category, EDGE_CASE_TEMPLATE)

def add_edge_cases(spec_path: Path, dry_run=False):
    """Add edge cases to spec."""
    content = spec_path.read_text()

    if '## Edge Cases' in content:
        print(f"⏭  Skip {spec_path.name} (already has edge cases)")
        return False

    category = categorize_task(spec_path)
    template = get_relevant_edges(category)

    # Insert before "## Related Tasks" or "## References"
    if '## Related Tasks' in content:
        parts = content.split('## Related Tasks')
        new_content = parts[0] + template + '\n## Related Tasks' + parts[1]
    elif '## References' in content:
        parts = content.split('## References')
        new_content = parts[0] + template + '\n## References' + parts[1]
    else:
        new_content = content + '\n' + template

    if not dry_run:
        spec_path.write_text(new_content)
        print(f"✓ Added {category} edge cases to {spec_path.name}")
        return True
    else:
        print(f"Would add {category} edge cases to {spec_path.name}")
        return False

def main():
    import sys
    dry_run = '--dry-run' in sys.argv

    specs_dir = Path('.claude-coord/task-specs')
    added = 0

    for spec in sorted(specs_dir.glob('*.md')):
        if spec.name in ['template.md', 'README.md']:
            continue

        if add_edge_cases(spec, dry_run):
            added += 1

    print(f"\n{'Would add' if dry_run else 'Added'} edge cases to {added} specs")

if __name__ == '__main__':
    main()
```

### Phase 3: Automated Backfill (2 hours)

**Run script:**
```bash
# Dry run first
python .claude-coord/backfill_edge_cases.py --dry-run

# Review sample outputs
# Then run for real
python .claude-coord/backfill_edge_cases.py
```

**Expected output:**
```
✓ Added code edge cases to code-crit-auth-01.md
✓ Added code edge cases to code-high-api-02.md
✓ Added test edge cases to test-crit-e2e-01.md
⏭  Skip docs-med-readme-01.md (already has edge cases)
...
Added edge cases to 430 specs
```

### Phase 4: Spot Check & Validation (4 hours)

**Sample validation (10% review):**
```bash
# Randomly sample 43 specs (10% of 430)
ls .claude-coord/task-specs/*.md | shuf -n 43 > sample-for-review.txt

# Manually review each:
# 1. Edge cases appropriate for task type?
# 2. Specific enough?
# 3. Security cases included where relevant?
```

**Time:** ~5 minutes per spec × 43 specs = ~3.5 hours

---

## Customization Examples

### Example: Code Task (API Implementation)

```markdown
## Edge Cases

### Input Validation
- **Empty email:** `""` → ValidationError("Email required")
- **Invalid email:** `"notanemail"` → ValidationError("Invalid format")
- **SQL in email:** `"'; DROP TABLE users--"` → sanitized/rejected
- **Max length:** Email > 255 chars → ValidationError("Too long")
- **Unicode email:** `"test@日本.jp"` → should validate per RFC

### State Handling
- **User exists:** Creating duplicate → UniqueViolationError
- **Concurrent creation:** Two requests same email → second fails
- **Database down:** Cannot connect → ServiceUnavailableError (503)

### Security
- **Email verification bypass:** Manipulated token → rejected
- **Rate limiting:** > 100 signups/minute → rate limit (429)
- **Password strength:** "123456" → ValidationError("Too weak")
```

### Example: Test Task (Integration Tests)

```markdown
## Edge Cases

### Test Coverage Edge Cases
- **No database:** Tests run without DB → use in-memory SQLite
- **Slow external API:** Timeout in tests → use mocks/VCR
- **Flaky tests:** Intermittent failures → identify and fix or skip
- **Parallel execution:** Test interference → proper isolation

### Test Data Edge Cases
- **Empty database:** Fresh state for each test
- **Large datasets:** Performance tests with 10k+ records
- **Invalid fixtures:** Malformed test data → clear error
```

---

## Quality Gates

- [ ] All specs have edge case section
- [ ] Edge cases are specific to task type
- [ ] Security edges included where relevant
- [ ] Input/State/Error edges covered
- [ ] 10% sample review passed

---

## Validation

```bash
# Count specs with edge cases
grep -r "## Edge Cases" .claude-coord/task-specs/*.md | wc -l

# Should be: 492 (or close to it)

# Find specs still missing edge cases
for spec in .claude-coord/task-specs/*.md; do
  if ! grep -q "## Edge Cases" "$spec"; then
    echo "Missing: $(basename $spec)"
  fi
done
```

---

## Progress Tracking

- [ ] Phase 1: Template created
- [ ] Phase 2: Automation script written
- [ ] Phase 3: Automated backfill complete (430 specs)
- [ ] Phase 4: Sample review (43 specs checked)
- [ ] Validation passed

**Timeline:** 1-2 days focused work

---

**Last Updated:** 2026-02-01
**Ready to execute:** ✅
