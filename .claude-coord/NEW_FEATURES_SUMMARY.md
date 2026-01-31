# Coordination System New Features

## Summary of Additions

All features added to `.claude-coord/claude-coord.sh`:

### ✅ 1. One Task Per Agent Limit
Agents can only claim one task at a time.

**Commands:**
```bash
# This will work:
task-claim agent-001 task-a

# This will fail:
task-claim agent-001 task-b
# Error: Agent agent-001 already has a claimed task: task-a

# Release first:
task-release agent-001 task-a

# Now can claim second:
task-claim agent-001 task-b
```

---

### ✅ 2. Prefix Prioritization
Work on all tasks with one prefix before another (e.g., all m3-* before m4-*).

**Commands:**
```bash
# Set priorities (lower number = higher priority)
task-prefix-set m3 1
task-prefix-set m4 2
task-prefix-set doc 3

# List all prefix priorities
task-prefix-list

# Remove prefix priority
task-prefix-clear m3
```

**Example:**
```bash
# Setup
task-prefix-set m3 1
task-prefix-set m4 2

# Create tasks
task-add m3-002 "M3 task" "" 2  # Lower individual priority
task-add m4-001 "M4 task" "" 1  # Higher individual priority

# task-next will return m3-002 (prefix priority wins)
task-next agent-001
# Returns: m3-002
```

---

### ✅ 3. Task Dependencies
Tasks can depend on other tasks completing first.

**Commands:**
```bash
# Set dependencies after creation
task-depends m4-001 m3-001 m3-002

# Set dependencies at creation
task-add m4-001 "Deploy" "Deploy to prod" 1 "" "m3-001,m3-002"

# View dependencies
task-get m4-001 | jq '.blocked_by'

# Clear dependencies
task-depends-clear m4-001
```

**Example:**
```bash
# Create tasks with dependencies
task-add impl "Implement" "" 1
task-add test "Test" "" 2 "" "impl"
task-add deploy "Deploy" "" 1 "" "impl,test"

# task-next will only return tasks with met dependencies
task-next agent-001  # Returns: impl
# Complete impl
task-claim agent-001 impl
task-complete agent-001 impl

task-next agent-001  # Returns: test (impl done, deploy still blocked)
# Complete test
task-claim agent-001 test
task-complete agent-001 test

task-next agent-001  # Returns: deploy (all deps met)
```

---

### ✅ 4. Enhanced task-next
Now considers:
1. **Prefix priority** (configured order)
2. **Task dependencies** (blocked_by)
3. **Task priority** (P0-P5)
4. **One task per agent** limit

**Priority resolution:**
```
1. Filter tasks:
   - status = pending
   - owner = null
   - All dependencies completed

2. Sort by:
   - prefix_priorities[prefix] (lower first)
   - task.priority (lower first)

3. Return first task
```

---

### ✅ 5. Batch Task Import
Import multiple tasks from JSON file.

**Commands:**
```bash
# Dry run (preview without creating)
task-import tasks.json --dry-run

# Actually import
task-import tasks.json
```

**JSON Format:**
```json
{
  "tasks": [
    {
      "id": "task-001",
      "enabled": true,
      "title": "Task title",
      "description": "Description",
      "priority": "HIGH",
      "dependencies": {
        "blocked_by": ["other-task"]
      }
    }
  ]
}
```

**Priority mapping:**
- CRITICAL → 1
- HIGH → 2
- MEDIUM/NORMAL → 3
- LOW → 4
- BACKLOG → 5

---

## Complete Workflow Example

```bash
# 1. Setup prefix priorities
task-prefix-set backend 1
task-prefix-set frontend 2
task-prefix-set deploy 3

# 2. Import tasks from JSON
task-import .claude-coord/reports/docs-review-20260128-tasks.json

# 3. Add manual dependencies
task-depends frontend-001 backend-001
task-depends deploy-001 frontend-001 backend-002

# 4. Start working
task-next agent-001          # Returns: backend-* task (highest prefix priority)
task-claim agent-001 backend-001
task-complete agent-001 backend-001

task-next agent-001          # Returns: next backend-* or frontend-* if deps met
```

---

## Import Your Documentation Tasks

```bash
# Preview what will be imported
.claude-coord/claude-coord.sh task-import \
  .claude-coord/reports/docs-review-20260128-tasks.json \
  --dry-run

# Actually import all 64 tasks
.claude-coord/claude-coord.sh task-import \
  .claude-coord/reports/docs-review-20260128-tasks.json

# Set prefix priorities to work on critical first
.claude-coord/claude-coord.sh task-prefix-set doc-crit 1
.claude-coord/claude-coord.sh task-prefix-set doc-high 2
.claude-coord/claude-coord.sh task-prefix-set doc-med 3
.claude-coord/claude-coord.sh task-prefix-set doc-low 4

# Now task-next will return critical tasks first
.claude-coord/claude-coord.sh task-next agent-001
```

---

## Testing

Test script created: `/tmp/test_dependencies_at_creation.sh`

```bash
chmod +x /tmp/test_dependencies_at_creation.sh
/tmp/test_dependencies_at_creation.sh
```

---

## Files Modified

- `.claude-coord/claude-coord.sh` - All new features

## Documentation Created

- `.claude-coord/PREFIX_PRIORITY_AND_DEPENDENCIES.md` - Detailed guide
- `.claude-coord/ONE_TASK_PER_AGENT.md` - One task limit guide
- `.claude-coord/NEW_FEATURES_SUMMARY.md` - This file

---

## Next Steps

1. **Re-protect claude-coord.sh**:
   Edit `.claude-coord/protect-critical-files.sh` and uncomment:
   ```bash
   ".claude-coord/claude-coord.sh"
   ```

2. **Import documentation tasks**:
   ```bash
   .claude-coord/claude-coord.sh task-import \
     .claude-coord/reports/docs-review-20260128-tasks.json
   ```

3. **Set up prefix priorities** (if desired):
   ```bash
   .claude-coord/claude-coord.sh task-prefix-set doc-crit 1
   .claude-coord/claude-coord.sh task-prefix-set doc-high 2
   # etc.
   ```

4. **Start working**:
   ```bash
   .claude-coord/claude-coord.sh task-next <your-agent-id>
   ```
