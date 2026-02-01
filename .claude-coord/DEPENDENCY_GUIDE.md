# Task Dependency System Guide

The coordination system now supports task dependencies, allowing you to define which tasks must be completed before others can begin.

## Overview

**Key Concepts:**

- **Dependency**: Task A depends on Task B means Task A cannot start until Task B is completed
- **Blocks**: Task B blocks Task A means Task A is waiting for Task B to complete
- **Available Tasks**: Only tasks with all dependencies satisfied appear in `task-list`
- **Blocked Tasks**: Tasks with unsatisfied dependencies are "blocked" and unavailable for claiming

## CLI Commands

### Create Task with Dependencies

```bash
coord task-create <task-id> <subject> <description> --depends-on <task1,task2,...>
```

Create a task with dependencies specified at creation time (recommended approach).

**Example:**
```bash
# Create task that depends on task-1
coord task-create test-high-impl-2 "Add authentication" "Implement OAuth" --depends-on test-high-impl-1

# Create task with multiple dependencies
coord task-create test-high-final-1 "Integration" "Integrate all features" --depends-on "test-high-feat-1,test-high-feat-2"
```

### Add a Dependency

```bash
coord task-add-dep <task-id> <depends-on>
```

Add a dependency to an existing task. Use this when you need to add dependencies after task creation.

**Example:**
```bash
# Make task-2 depend on task-1
coord task-add-dep test-high-impl-2 test-high-impl-1
```

### Remove a Dependency

```bash
coord task-remove-dep <task-id> <depends-on>
```

Removes a dependency relationship.

**Example:**
```bash
coord task-remove-dep test-high-impl-2 test-high-impl-1
```

### View Task Dependencies

```bash
coord task-deps <task-id>
```

Shows what a task depends on and what tasks depend on it.

**Example:**
```bash
$ coord task-deps test-high-impl-2

Task: test-high-impl-2

Depends on (1):
  - test-high-impl-1

Blocks (2):
  - test-high-impl-3
  - test-high-impl-4
```

### View Blocked Tasks

```bash
coord task-blocked
```

Lists all tasks that are pending but blocked by dependencies.

**Example:**
```bash
$ coord task-blocked

Blocked tasks (2):
  test-high-impl-2: Implement user auth (blocked by 1 tasks)
  test-high-impl-3: Add payment gateway (blocked by 2 tasks)
```

## Common Workflows

### Linear Dependency Chain

When tasks must be done in sequence:

```bash
# Create tasks
coord task-create test-high-setup-1 "Setup database" "Create schema and migrations"
coord task-create test-high-setup-2 "Seed data" "Add initial test data"
coord task-create test-high-setup-3 "Run tests" "Verify database setup"

# Set up chain: 3 -> 2 -> 1
coord task-add-dep test-high-setup-2 test-high-setup-1
coord task-add-dep test-high-setup-3 test-high-setup-2

# Only task-1 is available initially
coord task-list
# Output: test-high-setup-1: Setup database [pending]

# Complete task-1
coord task-claim $CLAUDE_AGENT_ID test-high-setup-1
# ... do work ...
coord task-complete $CLAUDE_AGENT_ID test-high-setup-1

# Now task-2 becomes available
coord task-list
# Output: test-high-setup-2: Seed data [pending]
```

### Multiple Dependencies

When a task requires multiple prerequisites:

```bash
# Create tasks
coord task-create test-high-auth-1 "Implement OAuth" "Google OAuth integration"
coord task-create test-high-auth-2 "Add JWT support" "Token generation and validation"
coord task-create test-high-auth-3 "Create auth middleware" "Protect routes"

# Task 3 depends on both tasks 1 and 2
coord task-add-dep test-high-auth-3 test-high-auth-1
coord task-add-dep test-high-auth-3 test-high-auth-2

# Tasks 1 and 2 can be worked on in parallel
# Task 3 won't be available until BOTH are complete
```

### Fan-out Dependencies

When multiple tasks depend on one foundation:

```bash
# Create tasks
coord task-create test-high-base-1 "Setup API framework" "Express + routes"
coord task-create test-high-feat-1 "Add users endpoint" "CRUD for users"
coord task-create test-high-feat-2 "Add posts endpoint" "CRUD for posts"
coord task-create test-high-feat-3 "Add comments endpoint" "CRUD for comments"

# All features depend on the base
coord task-add-dep test-high-feat-1 test-high-base-1
coord task-add-dep test-high-feat-2 test-high-base-1
coord task-add-dep test-high-feat-3 test-high-base-1

# Complete base task first
coord task-claim $CLAUDE_AGENT_ID test-high-base-1
coord task-complete $CLAUDE_AGENT_ID test-high-base-1

# Now all 3 feature tasks become available and can be worked on in parallel
```

## Safety Features

### Circular Dependency Prevention

The system automatically detects and prevents circular dependencies:

```bash
# Create chain: task-2 -> task-1
coord task-add-dep test-high-circ-2 test-high-circ-1

# Try to create cycle: task-1 -> task-2 (BLOCKED)
coord task-add-dep test-high-circ-1 test-high-circ-2
# Error: Cannot add dependency: would create circular dependency
```

This works for indirect cycles too:

```bash
# Chain: task-3 -> task-2 -> task-1
coord task-add-dep test-high-chain-2 test-high-chain-1
coord task-add-dep test-high-chain-3 test-high-chain-2

# Try to close the loop: task-1 -> task-3 (BLOCKED)
coord task-add-dep test-high-chain-1 test-high-chain-3
# Error: Cannot add dependency: would create circular dependency
```

### Automatic Unblocking

When you complete a task, any tasks depending on it automatically become available:

```bash
# Before completion
coord task-list
# Output: test-high-impl-1: Task 1 [pending]

coord task-blocked
# Output: Blocked tasks (1):
#   test-high-impl-2: Task 2 (blocked by 1 tasks)

# Complete task 1
coord task-complete $CLAUDE_AGENT_ID test-high-impl-1

# After completion - task 2 automatically unblocked
coord task-list
# Output: test-high-impl-2: Task 2 [pending]

coord task-blocked
# Output: No blocked tasks
```

## Database Schema

Dependencies are stored in the `task_dependencies` table:

```sql
CREATE TABLE task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,           -- The task that has a dependency
    depends_on TEXT NOT NULL,        -- The task it depends on
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on) REFERENCES tasks(id) ON DELETE CASCADE,
    UNIQUE(task_id, depends_on),
    CHECK (task_id != depends_on)    -- Prevent self-dependencies
);
```

## API Usage (Python)

From Python code using the coordination client:

```python
from coord_service.client import CoordinationClient

client = CoordinationClient("/path/to/project")

# Add dependency
client.call('task_add_dependency', {
    'task_id': 'test-high-impl-2',
    'depends_on': 'test-high-impl-1'
})

# Get dependencies
result = client.call('task_dependencies', {'task_id': 'test-high-impl-2'})
print(result['depends_on'])  # ['test-high-impl-1']
print(result['blocks'])      # ['test-high-impl-3']

# Get blocked tasks
result = client.call('task_blocked', {})
for task in result['tasks']:
    print(f"{task['id']}: blocked by {task['blocked_by_count']} tasks")
```

## Best Practices

1. **Keep chains short**: Long dependency chains can create bottlenecks. Try to parallelize when possible.

2. **Use fan-out for parallelization**: When multiple tasks share a common prerequisite, let them run in parallel after it completes.

3. **Document dependencies**: Use task descriptions to explain why dependencies exist.

4. **Avoid over-constraining**: Only add dependencies that are truly necessary. Over-constraining reduces parallelism.

5. **Review blocked tasks regularly**: Run `coord task-blocked` to see what's waiting and prioritize unblocking work.

## Troubleshooting

### Task won't appear in task-list

**Possible causes:**
1. Task has incomplete dependencies - check with `coord task-deps <task-id>`
2. Task is already claimed - check task status with `coord task-get <task-id>`
3. Task is completed - completed tasks don't appear in available task list

**Solution:**
```bash
# Check dependencies
coord task-deps <task-id>

# Check what's blocking it
coord task-blocked

# Remove unnecessary dependencies
coord task-remove-dep <task-id> <unnecessary-dep>
```

### Can't add dependency

**Error: "would create circular dependency"**

This means adding the dependency would create a cycle. Review your dependency graph:

```bash
# Check what the target task depends on
coord task-deps <depends-on>

# One of those dependencies likely leads back to your task
```

### Task stays blocked after dependency completes

**Possible causes:**
1. Multiple dependencies - check if task has other incomplete dependencies
2. Database cache - try `coord status` to refresh

**Solution:**
```bash
# View all dependencies
coord task-deps <task-id>

# Check status of each dependency
coord task-get <dependency-id>
```
