# ADR-0009: Task Dependency Graph System

[🏠 Home](../../README.md) > [📚 Docs](../INDEX.md) > [ADRs](./README.md) > ADR-0009

---

**Date:** 2026-01-28
**Status:** Accepted
**Deciders:** Framework Core Team
**Tags:** coordination, dependencies, graph, M4

---

## Context

Multi-agent workflows often have natural ordering requirements. For example:
- Database setup must complete before running migrations
- API implementation must finish before writing integration tests
- Feature branches must merge before deployment

**Problem:** Without dependency management:
- Agents claim tasks in wrong order
- Work is wasted on blocked tasks
- Manual coordination required
- No way to express task relationships

**Key Questions:**
- How do we model task dependencies?
- How do we prevent circular dependencies?
- How do we efficiently query available tasks?
- How do we handle dynamic dependency changes?

---

## Decision Drivers

- **Correctness:** Prevent circular dependencies
- **Efficiency:** Fast queries for available tasks
- **Simplicity:** Easy to understand and use
- **Flexibility:** Support complex dependency graphs
- **Performance:** < 100ms to find available tasks

---

## Considered Options

### Option 1: No Dependencies (Manual Coordination)

**Description:** Agents coordinate manually through task naming/status

**Pros:**
- No implementation needed
- Simple mental model

**Cons:**
- Error-prone manual tracking
- No enforcement of order
- Wasted work on blocked tasks
- Agents must poll for dependencies

**Effort:** None (status quo)

---

### Option 2: Simple Parent-Child Relationships

**Description:** Each task can have one parent task

**Pros:**
- Simple to implement (single foreign key)
- Easy to query (one join)
- Fast performance

**Cons:**
- Cannot model complex graphs (task depends on multiple)
- Fan-in scenarios impossible (converge after parallel work)
- Too limited for real workflows

**Effort:** Low

---

### Option 3: Full Dependency Graph

**Description:** Many-to-many relationships, task can depend on multiple tasks

**Pros:**
- Supports all dependency patterns (linear, fan-out, fan-in)
- Flexible for complex workflows
- Can detect circular dependencies
- Industry standard approach

**Cons:**
- More complex queries
- Need circular dependency detection
- Slightly more storage

**Effort:** Medium

---

## Decision Outcome

**Chosen Option:** Option 3: Full Dependency Graph

**Justification:**

Real workflows need complex patterns:
- **Linear:** task-1 → task-2 → task-3
- **Fan-out:** base-task → (feature-1, feature-2, feature-3)
- **Fan-in:** (auth, api, db) → integration-test

Simple parent-child is too limiting. The complexity of graph management is worth the flexibility.

**Implementation:**
```sql
CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on) REFERENCES tasks(id) ON DELETE CASCADE
);
```

---

## Consequences

### Positive

- ✅ Supports all dependency patterns
- ✅ Automatic task ordering enforcement
- ✅ Prevents circular dependencies (validated at insertion)
- ✅ Efficient queries (indexed joins)
- ✅ Clear semantic meaning ("task X depends on task Y")

### Negative

- ❌ More complex than simple foreign key
- ❌ Circular dependency detection adds overhead
- ❌ Query complexity increases with graph depth

### Neutral

- Need to document dependency patterns for users
- CLI commands for managing dependencies
- Visualization tools would be helpful

---

## Implementation Notes

**Dependency API:**
```bash
# Create task with dependencies
coord task-create task-2 "Feature" "..." --depends-on task-1

# Add dependency to existing task
coord task-add-dep task-3 task-1
coord task-add-dep task-3 task-2  # Multiple dependencies

# Remove dependency
coord task-remove-dep task-3 task-2

# View dependencies
coord task-deps task-3
```

**Query Logic:**
```sql
-- Find available tasks (no incomplete dependencies)
SELECT t.*
FROM tasks t
LEFT JOIN task_dependencies td ON t.id = td.task_id
LEFT JOIN tasks dep ON td.depends_on = dep.id
WHERE t.status = 'pending'
  AND (dep.id IS NULL OR dep.status = 'completed')
GROUP BY t.id
HAVING COUNT(dep.id) = 0 OR COUNT(dep.id) = COUNT(CASE WHEN dep.status = 'completed' THEN 1 END)
```

**Circular Dependency Detection:**
- Run depth-first search on dependency graph
- Detect cycles before allowing insertion
- Return clear error message with cycle path

**Common Patterns:**
1. **Sequential:** task-create with --depends-on previous
2. **Parallel after setup:** All depend on setup-task, none on each other
3. **Converge:** Final task depends on all parallel tasks

**Action Items:**
- [x] Add task_dependencies table
- [x] Implement circular dependency detection
- [x] Add CLI commands (task-add-dep, task-remove-dep, task-deps)
- [x] Update task-list to filter by dependencies
- [x] Document common patterns
- [x] Add tests for cycles and complex graphs

---

## Related Decisions

- [ADR-0008: Coordination Daemon](./0008-coordination-daemon-architecture.md) - Provides database
- [ADR-0010: Task Validation](./0010-task-validation-system.md) - Validates dependency consistency

---

## References

- [DEPENDENCY_GUIDE.md](../../.claude-coord/DEPENDENCY_GUIDE.md) - User documentation
- [Graph Theory - Topological Sort](https://en.wikipedia.org/wiki/Topological_sorting)
- [Detecting Cycles in Directed Graphs](https://en.wikipedia.org/wiki/Cycle_(graph_theory))

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-28 | Framework Team | Initial implementation |
| 2026-02-01 | Documentation Team | ADR documentation |
