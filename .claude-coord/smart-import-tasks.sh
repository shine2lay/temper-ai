#!/bin/bash
# Smart task import - only import unimplemented tasks

set -e

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_SPECS_DIR="$COORD_DIR/task-specs"
COORD_SCRIPT="$COORD_DIR/claude-coord.sh"
PROJECT_ROOT="$(dirname "$COORD_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
total_specs=0
already_implemented=0
added=0
skipped_other=0

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Smart Task Import${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to extract task ID from filename
get_task_id() {
    local filename="$1"
    echo "${filename%.md}"
}

# Function to extract files to modify from task spec
get_files_to_modify() {
    local spec_file="$1"

    # Extract files between "## Files to Modify" and next "---"
    sed -n '/^## Files to Modify$/,/^---$/p' "$spec_file" | \
        grep '^- `' | \
        sed 's/^- `\([^`]*\)`.*/\1/' || true
}

# Function to extract files to create from task spec
get_files_to_create() {
    local spec_file="$1"

    # Extract files between "## Files to Create" and next "---"
    sed -n '/^## Files to Create$/,/^---$/p' "$spec_file" | \
        grep '^- `' | \
        sed 's/^- `\([^`]*\)`.*/\1/' || true
}

# Function to check if task is implemented
is_task_implemented() {
    local spec_file="$1"
    local task_id="$2"

    # Get files to modify and create
    local files_to_modify=$(get_files_to_modify "$spec_file")
    local files_to_create=$(get_files_to_create "$spec_file")

    # If no files specified, can't determine implementation status
    if [ -z "$files_to_modify" ] && [ -z "$files_to_create" ]; then
        return 1  # Not implemented (can't verify)
    fi

    # Check if files to create exist
    if [ -n "$files_to_create" ]; then
        for file in $files_to_create; do
            local full_path="$PROJECT_ROOT/$file"
            if [ ! -f "$full_path" ]; then
                return 1  # File should exist but doesn't - NOT implemented
            fi
        done
    fi

    # For files to modify, check if the changes are present
    # This is harder to verify automatically, so we'll check acceptance criteria

    # Extract acceptance criteria checkboxes
    local unchecked_count=$(grep -c '^\s*- \[ \]' "$spec_file" 2>/dev/null || echo "0")
    local checked_count=$(grep -c '^\s*- \[x\]' "$spec_file" 2>/dev/null || echo "0")

    # If all checkboxes are checked, consider it implemented
    if [ "$unchecked_count" -eq 0 ] && [ "$checked_count" -gt 0 ]; then
        return 0  # All checked - IMPLEMENTED
    fi

    # If some are checked, partial implementation
    if [ "$checked_count" -gt 0 ]; then
        return 2  # Partial implementation
    fi

    # Default: not implemented
    return 1
}

# Function to extract task metadata
extract_task_metadata() {
    local spec_file="$1"

    # Extract title (first # heading)
    local title=$(grep -m1 '^# Task:' "$spec_file" | sed 's/^# Task: //' || echo "")

    # Extract summary (text under ## Summary)
    local summary=$(sed -n '/^## Summary$/,/^---$/{/^## Summary$/d;/^---$/d;p}' "$spec_file" | \
                    tr '\n' ' ' | sed 's/  */ /g' | cut -c1-200 || echo "")

    # Extract priority from filename
    local priority=3  # Default normal
    if [[ "$spec_file" == *"-crit-"* ]]; then
        priority=1  # Critical
    elif [[ "$spec_file" == *"-high-"* ]]; then
        priority=2  # High
    elif [[ "$spec_file" == *"-low-"* ]]; then
        priority=4  # Low
    fi

    echo "$title|$summary|$priority"
}

# Process each task spec
echo -e "${BLUE}Scanning task specs...${NC}"
echo ""

for spec_file in "$TASK_SPECS_DIR"/*.md; do
    [ -f "$spec_file" ] || continue

    total_specs=$((total_specs + 1))

    filename=$(basename "$spec_file")
    task_id=$(get_task_id "$filename")

    # Check if task already exists in coordination system
    if "$COORD_SCRIPT" task-get "$task_id" &>/dev/null; then
        echo -e "${YELLOW}⊙ SKIP${NC} $task_id - already in coordination system"
        skipped_other=$((skipped_other + 1))
        continue
    fi

    # Check if task is implemented
    if is_task_implemented "$spec_file" "$task_id"; then
        impl_status=$?
        if [ $impl_status -eq 0 ]; then
            echo -e "${GREEN}✓ DONE${NC} $task_id - already implemented"
            already_implemented=$((already_implemented + 1))
            continue
        elif [ $impl_status -eq 2 ]; then
            echo -e "${YELLOW}◐ PARTIAL${NC} $task_id - partially implemented (adding to queue)"
        fi
    fi

    # Extract metadata
    metadata=$(extract_task_metadata "$spec_file")
    title=$(echo "$metadata" | cut -d'|' -f1)
    summary=$(echo "$metadata" | cut -d'|' -f2)
    priority=$(echo "$metadata" | cut -d'|' -f3)

    # Use title or task_id as subject
    subject="${title:-$task_id}"

    # Add task to coordination system
    if "$COORD_SCRIPT" task-add "$task_id" "$subject" "$summary" "$priority" "smart-import" &>/dev/null; then
        echo -e "${GREEN}+ ADD${NC}  $task_id - $subject (P$priority)"
        added=$((added + 1))
    else
        echo -e "${RED}✗ FAIL${NC} $task_id - failed to add"
        skipped_other=$((skipped_other + 1))
    fi
done

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Import Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Total specs scanned:      ${BLUE}$total_specs${NC}"
echo -e "Already implemented:      ${GREEN}$already_implemented${NC}"
echo -e "Added to queue:           ${GREEN}$added${NC}"
echo -e "Skipped (other reasons):  ${YELLOW}$skipped_other${NC}"
echo ""
echo -e "${GREEN}✓ Smart import complete!${NC}"
echo ""
echo "Run: $COORD_SCRIPT task-list pending"
echo "     to see pending tasks"
