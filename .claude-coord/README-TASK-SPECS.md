# Task Specification System for Multi-Agent Coordination

**Status:** Enhanced coordination system with detailed task specs
**Date:** 2026-01-26

---

## Overview

The coordination system now supports **two-level task tracking**:

1. **Coordination Level** (state.json) - Brief task info for agent coordination
2. **Specification Level** (task-specs/*.md) - Detailed acceptance criteria, code examples, checklists

This gives multi-agent systems the same level of detail as single-agent built-in tasks.

---

## Quick Start

### View Detailed Task Spec
```bash
# View full specification with acceptance criteria
.claude-coord/task-spec-helpers.sh task-spec p6-p0-01

# Or use the short alias
./claude-coord.sh task-spec p6-p0-01  # (if integrated)
```

### Create Task with Detailed Spec
```bash
# Create task with template spec
.claude-coord/task-spec-helpers.sh task-add-detailed \
  p6-new-task \
  "Implement New Feature" \
  "" \
  2  # priority: 2=high

# Creates:
# - Task in state.json (coordination)
# - Template spec in task-specs/p6-new-task.md (details)

# Edit the spec to add acceptance criteria
$EDITOR .claude-coord/task-specs/p6-new-task.md
```

### Track Progress
```bash
# Show completion progress
.claude-coord/task-spec-helpers.sh task-progress p6-p0-01

# Mark checklist item as complete
.claude-coord/task-spec-helpers.sh task-check p6-p0-01 "Unit tests"

# List all tasks with detailed specs
.claude-coord/task-spec-helpers.sh task-list-specs
```

---

## Task Spec Template

Each spec file (`task-specs/{task-id}.md`) contains:

### 1. **Header** - Basic info
- Priority, Effort, Status, Owner

### 2. **Summary** - Brief description
- What needs to be done

### 3. **Files** - Concrete file operations
- Files to Create (with descriptions)
- Files to Modify (with what changes)

### 4. **Acceptance Criteria** - Checkboxes
- Core Functionality (what it must do)
- Testing (unit, integration, e2e)
- Security Controls (if applicable)
- Documentation
- Integration Points

### 5. **Implementation Details** - Code examples
- Class structures
- Key methods
- API contracts

### 6. **Test Strategy** - How to test
- Test scenarios
- Edge cases
- Performance benchmarks

### 7. **Success Metrics** - Done criteria
- Coverage targets
- Performance targets
- Quality gates

### 8. **Dependencies** - Task relationships
- Blocked by (prerequisite tasks)
- Blocks (downstream tasks)
- Integrates with (related systems)

### 9. **Design References** - Links
- Implementation guides
- Architecture docs
- Related PRDs/specs

### 10. **Notes** - Additional context
- Warnings, gotchas, tips

---

## Workflow: Multi-Agent with Detailed Specs

### Agent Starting a Task

```bash
# 1. Check available tasks
.claude-coord/claude-coord.sh task-list available

# 2. View detailed spec
.claude-coord/task-spec-helpers.sh task-spec p6-p0-01

# 3. Claim the task
.claude-coord/claude-coord.sh task-claim $CLAUDE_AGENT_ID p6-p0-01

# 4. Lock necessary files
.claude-coord/claude-coord.sh lock-all $CLAUDE_AGENT_ID \
  src/safety/blast_radius.py \
  tests/test_blast_radius.py

# 5. Implement following the acceptance criteria in spec

# 6. Mark checklist items as you complete them
.claude-coord/task-spec-helpers.sh task-check p6-p0-01 "ActionPolicy enforces"

# 7. Check progress
.claude-coord/task-spec-helpers.sh task-progress p6-p0-01

# 8. Complete task when all criteria met
.claude-coord/claude-coord.sh task-complete $CLAUDE_AGENT_ID p6-p0-01
```

### Creating New Tasks

```bash
# Option 1: Quick task (brief description only)
.claude-coord/claude-coord.sh task-add \
  my-task-01 \
  "Fix bug in parser" \
  "Parser fails on edge case. See issue #123"

# Option 2: Detailed task (with full spec)
.claude-coord/task-spec-helpers.sh task-add-detailed \
  my-task-02 \
  "Implement caching layer"

# Edit the generated spec template
$EDITOR .claude-coord/task-specs/my-task-02.md
```

---

## Integration with claude-coord.sh

To integrate the helper commands into the main script, add to `claude-coord.sh`:

```bash
# Add near the bottom, before the main case statement:

# Check if task spec helpers are available
if [ -f "$COORD_DIR/task-spec-helpers.sh" ]; then
    # Try task-spec helpers first
    case "${1:-}" in
        task-spec|task-add-detailed|task-list-specs|task-check|task-progress)
            exec "$COORD_DIR/task-spec-helpers.sh" "$@"
            ;;
    esac
fi

# Then continue with existing case statement...
```

This allows using both systems seamlessly:
```bash
# Works with or without integration
./claude-coord.sh task-spec p6-p0-01
./task-spec-helpers.sh task-spec p6-p0-01
```

---

## Phase 6 Tasks with Detailed Specs

Current tasks with full specifications:

| Task ID | Subject | Spec File | Progress |
|---------|---------|-----------|----------|
| p6-p0-01 | BlastRadius + ActionPolicy | task-specs/p6-p0-01.md | 0/22 (0%) |
| p6-p0-02 | DecisionAudit + Checkpoint | task-specs/p6-p0-02.md | TODO |
| p6-p0-03 | KillSwitch | task-specs/p6-p0-03.md | TODO |
| p6-p0-04 | OrthogonalValidator | task-specs/p6-p0-04.md | TODO |
| p6-p0-05 | AnomalyDetector | task-specs/p6-p0-05.md | TODO |
| p6-mem-01 | VectorStore + ChromaDB | task-specs/p6-mem-01.md | TODO |
| p6-mem-02 | FeedbackService | task-specs/p6-mem-02.md | TODO |
| p6-codegen-01 | CodeGenerationAgent | task-specs/p6-codegen-01.md | TODO |
| p6-gate-01 | Phase 6 Gate Validation | task-specs/p6-gate-01.md | TODO |

---

## Benefits of Detailed Specs

### For Individual Agents
- ✅ Clear acceptance criteria (checkboxes to verify)
- ✅ Code examples and templates
- ✅ Test strategy included
- ✅ Dependencies clearly stated

### For Multi-Agent Teams
- ✅ Consistent task format across agents
- ✅ Progress tracking visible to all agents
- ✅ Reduces ambiguity and rework
- ✅ Easy handoff if agent needs to switch tasks

### For Humans
- ✅ Can review task specs before approving agent work
- ✅ Track progress via checklist completion
- ✅ Easy to add/modify requirements mid-task

---

## Advanced: Spec File Conventions

### Naming Convention
```
task-specs/{task-id}.md
```

### Markdown Structure
- Use `##` for major sections
- Use `###` for subsections
- Use `- [ ]` for unchecked items
- Use `- [x]` for completed items
- Use code fences for implementation examples

### Updating Specs
```bash
# Manual editing
$EDITOR .claude-coord/task-specs/p6-p0-01.md

# Programmatic updates
sed -i 's/- \[ \] Unit tests/- [x] Unit tests/' \
  .claude-coord/task-specs/p6-p0-01.md

# Or use helper
.claude-coord/task-spec-helpers.sh task-check p6-p0-01 "Unit tests"
```

---

## Example: Full Workflow

```bash
# === AGENT DISCOVERS NEXT TASK ===

# List available tasks
.claude-coord/claude-coord.sh task-list available
# Output: p6-p0-01: Implement BlastRadius + ActionPolicy (P0.1)

# View detailed specification
.claude-coord/task-spec-helpers.sh task-spec p6-p0-01
# Shows: 22 acceptance criteria, code examples, test strategy

# === AGENT CLAIMS AND STARTS ===

# Claim task
.claude-coord/claude-coord.sh task-claim $CLAUDE_AGENT_ID p6-p0-01

# Lock files
.claude-coord/claude-coord.sh lock-all $CLAUDE_AGENT_ID \
  src/safety/__init__.py \
  src/safety/blast_radius.py \
  src/services/schema.py \
  tests/test_blast_radius.py

# === AGENT IMPLEMENTS ===

# [Agent writes code, following spec]

# Mark progress
.claude-coord/task-spec-helpers.sh task-check p6-p0-01 "ActionPolicy enforces"
.claude-coord/task-spec-helpers.sh task-check p6-p0-01 "Unit tests cover"

# Check progress
.claude-coord/task-spec-helpers.sh task-progress p6-p0-01
# Output: 2/22 (9%)

# === AGENT COMPLETES ===

# All criteria met, complete task
.claude-coord/claude-coord.sh task-complete $CLAUDE_AGENT_ID p6-p0-01

# Automatic: locks released
```

---

## Troubleshooting

### Spec file not found
```bash
# Create spec from template
.claude-coord/task-spec-helpers.sh task-add-detailed \
  task-id \
  "Task Subject"
```

### Progress tracking not working
```bash
# Ensure checklist items use proper format:
- [ ] Item text  # CORRECT
- [] Item text   # WRONG (missing space)
-[ ] Item text   # WRONG (missing space after dash)
```

### Integration with main script
```bash
# If task-spec command not working from claude-coord.sh,
# use direct path:
.claude-coord/task-spec-helpers.sh task-spec p6-p0-01
```

---

## Future Enhancements

Potential additions:

1. **Automated Progress Tracking** - Parse git commits to auto-check items
2. **Spec Validation** - Ensure specs have required sections
3. **Template Library** - Pre-built templates for common task types
4. **Spec Diff** - Show changes to specs over time
5. **Export** - Generate markdown reports of task progress
6. **Integration** - Link to GitHub issues, PRs, commits

---

## Summary

**Before:**
- Coordination system: Brief 1-line description
- Built-in tasks: Detailed specs (but isolated per agent)

**After:**
- Coordination system: Brief description (unchanged)
- **NEW:** Detailed specs in task-specs/*.md (shared across agents)
- Helper commands: task-spec, task-progress, task-check

**Result:** Multi-agent teams now have the same level of detail as single-agent sessions, with progress tracking visible to all agents.
