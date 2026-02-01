# Task Validation System

## Overview

The coordination system enforces task quality through validation rules that prevent bypassing important requirements while remaining flexible for simple tasks.

## Category System

### Standard Categories (with spec requirements)

| Category | Priority | Spec Required? | Description |
|----------|----------|----------------|-------------|
| `crit`   | 0        | ✅ Yes         | Critical tasks - highest urgency, requires detailed spec |
| `high`   | 1        | ✅ Yes         | High priority - important tasks, requires spec |
| `med`    | 2        | ❌ No          | Medium priority - standard tasks, no spec needed |
| `medi`   | 2        | ❌ No          | Medium (alternate spelling) |
| `low`    | 3        | ❌ No          | Low priority - backlog items, no spec needed |

### Special Category

| Category | Priority | Spec Required? | Description |
|----------|----------|----------------|-------------|
| `quick`  | 2        | ❌ No          | Quick/simple tasks - bypasses all validation |

**Use `quick` for:**
- Simple bug fixes
- Documentation updates
- Minor tweaks
- Any task that doesn't warrant full specification

## Priority Auto-Derivation

**Priority is automatically derived from the task category.**

You **cannot** manually override priority to bypass spec requirements:

```bash
# ❌ FAILS - Can't set low priority on high category task
coord task-create test-high-impl-1 "Important work" "..." --priority 3
# Error: Priority 3 doesn't match category 'high' (expected 1)

# ✅ CORRECT - Omit priority, it's auto-set from category
coord task-create test-high-impl-1 "Important work" "..."
# Priority automatically set to 1 (from 'high' category)

# ✅ ALTERNATIVE - Use quick category for simple tasks
coord task-create test-quick-impl-1 "Simple fix" "..."
# Priority auto-set to 2, no spec required
```

## Validation Rules

### 1. Task ID Format

**Required format:** `<prefix>-<category>-<identifier>`

**Valid prefixes:**
- `test` - Test-related tasks
- `code` - Code implementation tasks
- `docs` - Documentation tasks
- `gap` - Gap analysis tasks
- `refactor` - Refactoring tasks
- `perf` - Performance tasks

**Examples:**
```bash
✅ test-crit-security-audit-01
✅ code-high-auth-refactor-02
✅ docs-med-api-guide-03
✅ test-quick-typo-fix-04
❌ my-task-123  (invalid prefix)
❌ test-urgent-fix  (invalid category)
```

### 2. Subject Requirements

- **Minimum length:** 10 characters
- **Maximum length:** 100 characters
- Must be descriptive but concise

### 3. Description Requirements

**For crit/high priority tasks:**
- Minimum 20 characters
- Should explain the task in detail

**For med/low/quick tasks:**
- No minimum (can be empty or brief)

### 4. Spec File Requirements

**Required for:** `crit` and `high` categories only

**Spec file must contain:**
```markdown
# Task Specification: <task-id>

## Problem Statement
What problem does this solve?

## Acceptance Criteria
- Clear, testable criteria
- One per line

## Test Strategy
How will this be tested?
```

**Location:** `.claude-coord/task-specs/<task-id>.md`

**Example:**
```bash
# Create spec file first
cat > .claude-coord/task-specs/test-high-auth-01.md << 'EOF'
# Task Specification: test-high-auth-01

## Problem Statement
Users need secure authentication to protect their accounts.

## Acceptance Criteria
- OAuth integration with Google and GitHub
- JWT token generation and validation
- Secure session management
- Rate limiting on login attempts

## Test Strategy
1. Unit tests for token generation/validation
2. Integration tests for OAuth flow
3. Security audit of session handling
4. Load test for rate limiting
EOF

# Then create task
coord task-create test-high-auth-01 "Implement authentication" "Secure user auth system"
```

## Usage Examples

### Simple Task (No Spec Needed)

```bash
# Use quick category for simple tasks
coord task-create test-quick-typo-1 "Fix typo in docs" "Correct spelling error"

# Or use med/low for less urgent simple tasks
coord task-create docs-med-update-1 "Update README" "Add installation section"
```

### Important Task (Spec Required)

```bash
# 1. Create spec file
mkdir -p .claude-coord/task-specs
cat > .claude-coord/task-specs/code-high-payment-1.md << 'EOF'
# Task Specification: code-high-payment-1

## Problem Statement
Need to integrate payment processing for subscription billing.

## Acceptance Criteria
- Stripe integration for card processing
- Subscription plan management
- Webhook handling for payment events
- Proper error handling and retries

## Test Strategy
1. Unit tests for payment logic
2. Integration tests with Stripe test mode
3. Webhook simulation tests
4. Error scenario coverage
EOF

# 2. Create task (priority auto-set to 1 from 'high')
coord task-create code-high-payment-1 "Payment integration" "Stripe subscription billing"
```

### Task with Dependencies

```bash
# Quick tasks can have dependencies too
coord task-create test-quick-setup-1 "Setup test env" "Configure test database"
coord task-create test-quick-seed-1 "Seed test data" "Add sample records" \
    --depends-on test-quick-setup-1
```

## Bypassing Validation (Intentional)

**The `quick` category exists specifically for this purpose.**

Instead of trying to bypass validation with incorrect priorities, use the proper category:

```bash
# ❌ DON'T DO THIS (trying to game the system)
coord task-create test-high-simple-1 "Quick fix" "..." --priority 3
# Error: Priority doesn't match category

# ✅ DO THIS (use the right category)
coord task-create test-quick-simple-1 "Quick fix" "..."
# Works! No spec required, priority auto-set to 2
```

## Validation Error Messages

### Priority Mismatch

```
Error: Priority 3 doesn't match category 'high' (expected 1)
Hint: Category 'high' must have priority 1, or omit --priority flag to auto-set
```

**Solution:** Don't specify `--priority`, it will be auto-derived from category.

### Missing Spec File

```
Error: Critical/high priority task missing spec file
Hint: Create spec file with acceptance criteria, test strategy, or use 'quick' category
```

**Solutions:**
1. Create the spec file at `.claude-coord/task-specs/<task-id>.md`
2. OR use `quick` category if task is actually simple

### Invalid Task ID

```
Error: Task ID 'my-task' doesn't follow naming convention
Hint: Format: <prefix>-<category>-<identifier>
```

**Solution:** Use format like `test-quick-my-task-1`

### Invalid Category

```
Error: Unknown category 'urgent'
Hint: Use standard categories: crit, high, med/medi, low, quick
```

**Solution:** Use one of the valid categories listed above.

## Migration Guide

### If You Have Existing Tasks

Tasks created before this validation update may have mismatched priorities:

```sql
-- Check for mismatches
SELECT id, priority FROM tasks WHERE
    (id LIKE '%-crit-%' AND priority != 0) OR
    (id LIKE '%-high-%' AND priority != 1) OR
    (id LIKE '%-med-%' AND priority != 2) OR
    (id LIKE '%-medi-%' AND priority != 2) OR
    (id LIKE '%-low-%' AND priority != 3);

-- Fix mismatches
UPDATE tasks SET priority = 0 WHERE id LIKE '%-crit-%';
UPDATE tasks SET priority = 1 WHERE id LIKE '%-high-%';
UPDATE tasks SET priority = 2 WHERE id LIKE '%-med-%' OR id LIKE '%-medi-%';
UPDATE tasks SET priority = 3 WHERE id LIKE '%-low-%';
```

## Philosophy

**The validation system balances:**

1. **Quality:** Important tasks (crit/high) require proper planning via spec files
2. **Flexibility:** Simple tasks (quick/med/low) can be created quickly without bureaucracy
3. **Enforcement:** Can't game the system by setting wrong priority
4. **Clarity:** Category name clearly indicates task importance and requirements

**Use the right category for the job:**
- Important work that needs planning? → `crit` or `high`
- Standard work? → `med`
- Simple/quick fixes? → `quick`
- Backlog items? → `low`

This ensures high-quality planning for complex work while avoiding unnecessary overhead for simple tasks.
