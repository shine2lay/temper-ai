# Prefix Prioritization & Task Dependencies

## Overview

Two powerful features for controlling task execution order:

1. **Prefix Prioritization**: Work on all M3-* tasks before M4-* tasks
2. **Task Dependencies**: Task A cannot start until Task B completes

Both work together with individual task priorities (P0-P5).

---

## Prefix Prioritization

### What It Does

Ensures all tasks with one prefix complete before tasks with another prefix, regardless of individual priorities.

### Use Cases

- Complete all M3 milestone tasks before starting M4
- Finish all `auth-*` tasks before `api-*` tasks
- Work on `critical-*` tasks before `feature-*` tasks

### Commands

```bash
# Set prefix priorities (lower number = higher priority)
.claude-coord/claude-coord.sh task-prefix-set m3 1
.claude-coord/claude-coord.sh task-prefix-set m4 2
.claude-coord/claude-coord.sh task-prefix-set doc 3

# List all prefix priorities
.claude-coord/claude-coord.sh task-prefix-list
# Output:
# Prefix Priorities (lower = higher priority):
# Priority 1: m3
# Priority 2: m4
# Priority 3: doc

# Remove prefix priority
.claude-coord/claude-coord.sh task-prefix-clear m3
```

### How task-next Works

With prefix priorities configured, `task-next` returns tasks in this order:

1. **Prefix priority** (m3 before m4)
2. **Task priority** (P1 before P2 within same prefix)
3. **Dependencies** (only tasks with completed dependencies)

**Example:**

```
Tasks:
- m3-001 (priority: 2)
- m3-002 (priority: 1)  ← Higher individual priority
- m4-001 (priority: 1)  ← Highest individual priority, but wrong prefix

Prefix config:
- m3: 1
- m4: 2

task-next returns:
1. m3-002 (prefix m3=1, task priority=1)
2. m3-001 (prefix m3=1, task priority=2)
3. m4-001 (prefix m4=2, task priority=1)
```

---

## Task Dependencies

### What It Does

Prevents a task from being returned by `task-next` until all its dependencies are completed.

### Use Cases

- M4-001 cannot start until M3-001 and M3-002 are complete
- Integration tests can't run until implementation is done
- Deploy task can't run until all tests pass

### Commands

```bash
# Option 1: Set dependencies at creation time
.claude-coord/claude-coord.sh task-add m4-001 "Deploy" "Description" 1 "" "m3-001,m3-002"

# Option 2: Set dependencies after creation
.claude-coord/claude-coord.sh task-depends m4-001 m3-001 m3-002

# View dependencies
.claude-coord/claude-coord.sh task-get m4-001 | jq '.blocked_by'
# Output: ["m3-001", "m3-002"]

# Clear all dependencies
.claude-coord/claude-coord.sh task-depends-clear m4-001
```

### How It Works

`task-next` automatically filters out tasks with unmet dependencies:

```bash
# Setup
task-add m3-001 "Implement auth"
task-add m3-002 "Add tests"
task-add m4-001 "Deploy"
task-depends m4-001 m3-001 m3-002

# task-next will NOT return m4-001 until m3-001 AND m3-002 are completed
task-next agent-001
# Returns: m3-001 or m3-002 (both available)

# Complete first dependency
task-claim agent-001 m3-001
task-complete agent-001 m3-001

# task-next still won't return m4-001 (m3-002 not done yet)
task-next agent-001
# Returns: m3-002

# Complete second dependency
task-claim agent-001 m3-002
task-complete agent-001 m3-002

# NOW task-next can return m4-001
task-next agent-001
# Returns: m4-001
```

---

## Combining Prefix Priority + Dependencies + Task Priority

All three work together:

```bash
# Setup prefix priorities
task-prefix-set m3 1
task-prefix-set m4 2

# Create tasks with priorities
task-add m3-001 "Auth core" "" 1     # P1
task-add m3-002 "Auth tests" "" 2    # P2
task-add m4-001 "Deploy prep" "" 1   # P1
task-add m4-002 "Deploy" "" 1        # P1

# Set dependencies
task-depends m4-001 m3-001           # m4-001 waits for m3-001
task-depends m4-002 m4-001           # m4-002 waits for m4-001

# Execution order:
# 1. m3-001 (prefix m3=1, priority 1, no deps)
# 2. m3-002 (prefix m3=1, priority 2, no deps)
# 3. m4-001 (prefix m4=2, priority 1, dep m3-001 complete)
# 4. m4-002 (prefix m4=2, priority 1, dep m4-001 complete)
```

---

## Priority Resolution Order

`task-next` uses this priority order:

1. **Task must be available:**
   - status = pending
   - owner = null
   - All dependencies completed (blocked_by)

2. **Sort by:**
   - Prefix priority (lower number first)
   - Task priority (lower number first)

3. **Return:** First task after sorting

---

## Examples

### Example 1: Milestone Ordering

```bash
# Ensure M3 completes before M4 starts
task-prefix-set m3 1
task-prefix-set m4 2

# Now all m3-* tasks will be worked on before any m4-* task
```

### Example 2: Feature Dependencies

```bash
# Feature can't deploy until tests pass
task-depends feature-deploy feature-impl feature-tests

# Execution order guaranteed:
# 1. feature-impl
# 2. feature-tests
# 3. feature-deploy (only after both complete)
```

### Example 3: Complex Workflow

```bash
# Setup
task-prefix-set backend 1
task-prefix-set frontend 2
task-prefix-set deploy 3

# Backend tasks
task-add backend-001 "API endpoint" "" 1
task-add backend-002 "Database migration" "" 1
task-add backend-003 "Tests" "" 2

# Frontend tasks (depend on backend)
task-add frontend-001 "UI component" "" 1
task-depends frontend-001 backend-001

task-add frontend-002 "Integration" "" 2
task-depends frontend-002 backend-001 frontend-001

# Deploy (depends on everything)
task-add deploy-001 "Production deploy" "" 1
task-depends deploy-001 backend-003 frontend-002

# Execution order:
# 1. backend-001 (prefix=1, pri=1, no deps)
# 2. backend-002 (prefix=1, pri=1, no deps)
# 3. backend-003 (prefix=1, pri=2, no deps)
# 4. frontend-001 (prefix=2, pri=1, deps met: backend-001)
# 5. frontend-002 (prefix=2, pri=2, deps met: backend-001, frontend-001)
# 6. deploy-001 (prefix=3, pri=1, deps met: backend-003, frontend-002)
```

---

## Implementation Details

### State Structure

```json
{
  "tasks": {
    "m3-001": {
      "subject": "...",
      "priority": 1,
      "blocked_by": ["m2-005"],
      ...
    }
  },
  "prefix_priorities": {
    "m3": 1,
    "m4": 2,
    "doc": 3
  }
}
```

### task-next Algorithm

```
1. Get all pending tasks with no owner
2. Filter out tasks with unmet dependencies
3. Extract prefix from task ID (e.g., "m3" from "m3-001")
4. Sort by:
   a. prefix_priorities[prefix] (or 999 if not configured)
   b. task.priority (1-5)
5. Return first task
```

---

## Testing

```bash
# Test prefix priority
task-prefix-set test 1
task-add test-001 "First" "" 2
task-add other-001 "Second" "" 1

task-next agent-001
# Should return: test-001 (prefix priority overrides task priority)

# Test dependencies
task-add task-a "A" "" 1
task-add task-b "B" "" 1
task-depends task-b task-a

task-next agent-001
# Should return: task-a (task-b is blocked)

task-complete agent-001 task-a
task-next agent-001
# Should return: task-b (dependency met)
```

---

## Notes

- Prefix priorities are optional - tasks without configured prefixes use priority 999
- Dependencies use task IDs, not prefixes
- One task per agent limit still applies
- Combined with file locking for complete coordination
