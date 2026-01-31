#!/bin/bash
# task-spec-helpers.sh - Helper commands for detailed task specifications
# Extends claude-coord.sh with rich task spec support

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC_DIR="$COORD_DIR/task-specs"

# Ensure spec directory exists
mkdir -p "$SPEC_DIR"

# ============================================================
# TASK SPEC COMMANDS
# ============================================================

# View detailed task specification
cmd_task_spec() {
    local task_id="$1"

    [ -z "$task_id" ] && {
        echo "Usage: $0 task-spec <task_id>" >&2
        echo "  Shows detailed specification for a task" >&2
        exit 1
    }

    local spec_file="$SPEC_DIR/${task_id}.md"

    if [ ! -f "$spec_file" ]; then
        echo "No detailed spec found for task: $task_id" >&2
        echo "  Expected: $spec_file" >&2
        echo "" >&2
        echo "Basic task info:" >&2
        "$COORD_DIR/claude-coord.sh" task-get "$task_id"
        exit 1
    fi

    # Display with syntax highlighting if available
    if command -v bat >/dev/null 2>&1; then
        bat --style=plain --paging=never "$spec_file"
    elif command -v glow >/dev/null 2>&1; then
        glow "$spec_file"
    else
        cat "$spec_file"
    fi
}

# Create task with detailed specification
cmd_task_add_detailed() {
    local task_id="$1"
    local subject="$2"
    local spec_file="${3:-}"
    local priority="${4:-3}"

    [ -z "$task_id" ] || [ -z "$subject" ] && {
        echo "Usage: $0 task-add-detailed <task_id> <subject> [spec_file] [priority]" >&2
        echo "  Creates task in coord system and links to detailed spec" >&2
        echo "  If spec_file provided, copies it to task-specs/" >&2
        echo "  If spec_file omitted, creates template in task-specs/" >&2
        exit 1
    }

    local dest_spec="$SPEC_DIR/${task_id}.md"

    # Create or copy spec file
    if [ -n "$spec_file" ] && [ -f "$spec_file" ]; then
        # Copy provided spec file
        cp "$spec_file" "$dest_spec"
        echo "Copied spec: $spec_file -> $dest_spec"
    else
        # Create template spec file
        cat > "$dest_spec" <<EOF
# Task: $task_id - $subject

**Priority:** $(case $priority in 1) echo "CRITICAL";; 2) echo "HIGH";; 3) echo "NORMAL";; 4) echo "LOW";; 5) echo "BACKLOG";; esac)
**Effort:** TBD
**Status:** pending
**Owner:** unassigned

---

## Summary

[Brief description of what needs to be done]

---

## Files to Create

- \`path/to/file.py\` - Description

---

## Files to Modify

- \`path/to/file.py\` - What changes

---

## Acceptance Criteria

### Core Functionality
- [ ] Criterion 1
- [ ] Criterion 2

### Testing
- [ ] Unit tests
- [ ] Integration tests

### Documentation
- [ ] Update relevant docs

---

## Implementation Details

[Detailed implementation notes, code examples, etc.]

---

## Test Strategy

[How to test this task]

---

## Success Metrics

- [ ] Metric 1
- [ ] Metric 2

---

## Dependencies

- **Blocked by:** [task-ids]
- **Blocks:** [task-ids]

---

## Design References

- [Links to relevant docs, specs, etc.]

---

## Notes

[Additional context, warnings, tips]
EOF
        echo "Created template spec: $dest_spec"
        echo "Edit this file to add detailed acceptance criteria"
    fi

    # Extract brief description for coord system
    local description=$(grep -A 2 "^## Summary" "$dest_spec" | tail -n 1 | sed 's/^\[//' | sed 's/\]$//')

    # Add task to coordination system
    "$COORD_DIR/claude-coord.sh" task-add "$task_id" "$subject" "$description. See: .claude-coord/task-specs/${task_id}.md" "$priority"

    echo ""
    echo "Task created successfully!"
    echo "  Coord task: $task_id"
    echo "  Detailed spec: $dest_spec"
    echo ""
    echo "View detailed spec: $0 task-spec $task_id"
    echo "Edit spec: \$EDITOR $dest_spec"
}

# List all tasks with specs
cmd_task_list_specs() {
    echo "=== TASKS WITH DETAILED SPECS ==="
    echo ""

    for spec_file in "$SPEC_DIR"/*.md; do
        [ -f "$spec_file" ] || continue

        local task_id=$(basename "$spec_file" .md)
        local subject=$(grep "^# Task:" "$spec_file" | sed 's/^# Task: [^ ]* - //')
        local status=$("$COORD_DIR/claude-coord.sh" task-get "$task_id" 2>/dev/null | jq -r '.status // "unknown"')

        printf "%-20s [%-12s] %s\n" "$task_id" "$status" "$subject"
    done
}

# Update task spec checklist
cmd_task_check() {
    local task_id="$1"
    local item_pattern="$2"

    [ -z "$task_id" ] || [ -z "$item_pattern" ] && {
        echo "Usage: $0 task-check <task_id> <item_pattern>" >&2
        echo "  Marks checklist item as complete" >&2
        echo "  Example: $0 task-check p6-p0-01 'Unit tests'" >&2
        exit 1
    }

    local spec_file="$SPEC_DIR/${task_id}.md"

    if [ ! -f "$spec_file" ]; then
        echo "No spec found for task: $task_id" >&2
        exit 1
    fi

    # Replace first matching unchecked item with checked
    sed -i "0,/- \[ \] .*${item_pattern}.*/s//- [x] &/" "$spec_file"

    echo "Marked item as complete in $task_id"
    echo ""
    echo "Progress:"
    grep -E "^- \[(x| )\]" "$spec_file" | head -10
}

# Show task progress
cmd_task_progress() {
    local task_id="$1"

    [ -z "$task_id" ] && {
        echo "Usage: $0 task-progress <task_id>" >&2
        exit 1
    }

    local spec_file="$SPEC_DIR/${task_id}.md"

    if [ ! -f "$spec_file" ]; then
        echo "No spec found for task: $task_id" >&2
        exit 1
    fi

    local total=$(grep -c "^- \[.\]" "$spec_file")
    local done=$(grep -c "^- \[x\]" "$spec_file")
    local pending=$((total - done))

    echo "Task: $task_id"
    echo "  Total items: $total"
    echo "  Completed: $done"
    echo "  Remaining: $pending"
    echo "  Progress: $((done * 100 / total))%"
    echo ""
    echo "Pending items:"
    grep "^- \[ \]" "$spec_file" | head -5
}

# ============================================================
# MAIN DISPATCH
# ============================================================

case "${1:-}" in
    task-spec)         cmd_task_spec "$2" ;;
    task-add-detailed) cmd_task_add_detailed "$2" "$3" "$4" "$5" ;;
    task-list-specs)   cmd_task_list_specs ;;
    task-check)        cmd_task_check "$2" "$3" ;;
    task-progress)     cmd_task_progress "$2" ;;
    *)
        echo "Task Spec Helper Commands:" >&2
        echo "  task-spec <id>                     - View detailed task specification" >&2
        echo "  task-add-detailed <id> <subject>   - Create task with detailed spec" >&2
        echo "  task-list-specs                    - List all tasks with specs" >&2
        echo "  task-check <id> <pattern>          - Mark checklist item complete" >&2
        echo "  task-progress <id>                 - Show task completion progress" >&2
        exit 1
        ;;
esac
