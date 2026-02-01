#!/bin/bash
# create-task-spec skill
# Decomposes user requests into tasks and coordinates spec generation
# Usage: create-task-spec <request> [--prefix <prefix>]

set -e

COORD_DIR=".claude-coord"
TEMPLATES_FILE="$COORD_DIR/decomposition-templates.yaml"
CONTEXT_FILE="project-context.yaml"
SPEC_DIR="$COORD_DIR/task-specs"

# Parse arguments
REQUEST="$1"
shift || true
PREFIX="code"  # Default prefix

while [[ $# -gt 0 ]]; do
    case $1 in
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [[ -z "$REQUEST" ]]; then
    echo "Error: Request required"
    echo "Usage: create-task-spec <request> [--prefix <prefix>]"
    exit 1
fi

# Check dependencies
YQ_CMD="$HOME/.local/bin/yq"
if ! command -v "$YQ_CMD" &> /dev/null; then
    # Try system yq
    YQ_CMD="yq"
    if ! command -v "$YQ_CMD" &> /dev/null; then
        echo "Error: yq is required but not installed"
        echo "Download from: https://github.com/mikefarah/yq/releases"
        exit 1
    fi
fi

# Generate base task ID with timestamp (category will be added per-task)
TIMESTAMP=$(date +%s)
BASE_IDENTIFIER="auto${TIMESTAMP}"

echo "=========================================="
echo "Task Decomposition Request"
echo "=========================================="
echo "Request: $REQUEST"
echo "Base identifier: $BASE_IDENTIFIER"
echo ""

# Match request to template
echo "Matching request to template..."
TEMPLATE_INDEX=0
MATCHED=false
MATCHED_PATTERN=""

# Iterate through templates to find match
TEMPLATE_COUNT=$("$YQ_CMD" eval '.templates | length' "$TEMPLATES_FILE")
for ((i=0; i<TEMPLATE_COUNT; i++)); do
    PATTERN=$("$YQ_CMD" eval ".templates[$i].pattern" "$TEMPLATES_FILE")
    if echo "$REQUEST" | grep -qiP "$PATTERN"; then
        TEMPLATE_INDEX=$i
        MATCHED=true
        MATCHED_PATTERN="$PATTERN"
        break
    fi
done

if [[ "$MATCHED" != "true" ]]; then
    # Use generic template (should be last)
    TEMPLATE_INDEX=$(( TEMPLATE_COUNT - 1 ))
    echo "No specific template matched, using generic template"
else
    echo "✓ Matched template pattern: $MATCHED_PATTERN"
fi

# Extract template data
TEMPLATE_TYPE=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].type" "$TEMPLATES_FILE")
SUBTASK_COUNT=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks | length" "$TEMPLATES_FILE")

echo "Template type: $TEMPLATE_TYPE"
echo "Subtasks to create: $SUBTASK_COUNT"
echo ""

# Extract entities from request
echo "Extracting entities from request..."
PROVIDER=""
RESOURCE=""

# Try to extract provider (Google, GitHub, Stripe, Facebook, Microsoft, etc.)
if echo "$REQUEST" | grep -qiP "(google|github|stripe|facebook|microsoft|okta|auth0)"; then
    PROVIDER=$(echo "$REQUEST" | grep -ioP "(google|github|stripe|facebook|microsoft|okta|auth0)" | head -1)
    PROVIDER="$(tr '[:lower:]' '[:upper:]' <<< ${PROVIDER:0:1})${PROVIDER:1}"
fi

# Try to extract resource (user, order, payment, subscription, product, etc.)
if echo "$REQUEST" | grep -qiP "(user|order|payment|subscription|product|customer|invoice)s?"; then
    RESOURCE=$(echo "$REQUEST" | grep -ioP "(user|order|payment|subscription|product|customer|invoice)" | head -1)
fi

echo "Extracted entities:"
echo "  Provider: ${PROVIDER:-<none>}"
echo "  Resource: ${RESOURCE:-<none>}"
echo ""

# Create tasks and prepare spec requests
echo "=========================================="
echo "Creating Tasks"
echo "=========================================="

CREATED_TASKS=()
SPEC_REQUESTS=()

for ((i=0; i<SUBTASK_COUNT; i++)); do
    # Read subtask data
    ID_SUFFIX=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks[$i].id_suffix" "$TEMPLATES_FILE")
    CATEGORY=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks[$i].category" "$TEMPLATES_FILE")
    SUBJECT=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks[$i].subject" "$TEMPLATES_FILE")
    DESCRIPTION=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks[$i].description" "$TEMPLATES_FILE")
    NOTES=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks[$i].notes" "$TEMPLATES_FILE")

    # Get dependencies (may not exist for all tasks)
    DEPENDS_ON=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks[$i].depends_on[]" "$TEMPLATES_FILE" 2>/dev/null || echo "")

    # Replace placeholders
    SUBJECT="${SUBJECT//\{provider\}/$PROVIDER}"
    SUBJECT="${SUBJECT//\{resource\}/$RESOURCE}"
    SUBJECT="${SUBJECT//\{request\}/$REQUEST}"

    DESCRIPTION="${DESCRIPTION//\{provider\}/$PROVIDER}"
    DESCRIPTION="${DESCRIPTION//\{resource\}/$RESOURCE}"
    DESCRIPTION="${DESCRIPTION//\{request\}/$REQUEST}"

    NOTES="${NOTES//\{provider\}/$PROVIDER}"
    NOTES="${NOTES//\{resource\}/$RESOURCE}"

    # Generate full task ID with proper format: prefix-category-identifier
    TASK_ID="${PREFIX}-${CATEGORY}-${BASE_IDENTIFIER}-${ID_SUFFIX}"
    CREATED_TASKS+=("$TASK_ID")

    echo ""
    echo "Task $((i+1))/$SUBTASK_COUNT: $TASK_ID"
    echo "  Subject: $SUBJECT"
    echo "  Category: $CATEGORY"
    echo "  Description: $DESCRIPTION"

    # Create task in coord system
    # For high/crit tasks, create placeholder spec file first
    if [[ "$CATEGORY" == "high" ]] || [[ "$CATEGORY" == "crit" ]]; then
        # Use absolute path to ensure daemon finds it
        SPEC_FILE="$(pwd)/$SPEC_DIR/${TASK_ID}.md"
        mkdir -p "$(pwd)/$SPEC_DIR"

        echo "  Creating placeholder spec file: $SPEC_FILE"
        cat > "$SPEC_FILE" << 'SPEC_EOF'
# Task Specification

⚠️ **PLACEHOLDER** - Full spec will be generated by spec-creator agent

## Task Information
- **Task ID:** TASK_ID_PLACEHOLDER
- **Subject:** SUBJECT_PLACEHOLDER
- **Category:** CATEGORY_PLACEHOLDER
- **Description:** DESCRIPTION_PLACEHOLDER

## Problem Statement

This task is part of an automated decomposition workflow. The detailed problem statement will be generated by the spec-creator agent based on the decomposition notes and specialist analysis.

**Original Request:** REQUEST_PLACEHOLDER

## Acceptance Criteria

The spec-creator agent will generate specific, testable acceptance criteria based on:
- Decomposition template requirements
- Specialist recommendations (security, architecture, testing, etc.)
- Project patterns and conventions
- Integration with related tasks

*Placeholder criteria:*
- [ ] Implementation matches decomposition requirements
- [ ] All specialist recommendations addressed
- [ ] Tests pass
- [ ] No security vulnerabilities introduced

## Test Strategy

The spec-creator agent will define a comprehensive test strategy including:
- Unit tests for business logic
- Integration tests for external dependencies
- Security testing approach
- Test data strategy

*Placeholder strategy:*
- Tests will be designed based on specialist recommendations
- Coverage targets: >80% for critical paths
- Test approach will follow project testing patterns

## Implementation Plan

The spec-creator agent will generate detailed implementation steps with code examples based on specialist analysis.

## Decomposition Notes

NOTES_PLACEHOLDER
SPEC_EOF

        # Replace placeholders (escape special characters for sed)
        TASK_ID_ESC=$(echo "$TASK_ID" | sed 's/[\/&]/\\&/g')
        SUBJECT_ESC=$(echo "$SUBJECT" | sed 's/[\/&]/\\&/g')
        CATEGORY_ESC=$(echo "$CATEGORY" | sed 's/[\/&]/\\&/g')
        DESCRIPTION_ESC=$(echo "$DESCRIPTION" | sed 's/[\/&]/\\&/g')
        REQUEST_ESC=$(echo "$REQUEST" | sed 's/[\/&]/\\&/g')

        sed -i "s/TASK_ID_PLACEHOLDER/$TASK_ID_ESC/g" "$SPEC_FILE"
        sed -i "s/SUBJECT_PLACEHOLDER/$SUBJECT_ESC/g" "$SPEC_FILE"
        sed -i "s/CATEGORY_PLACEHOLDER/$CATEGORY_ESC/g" "$SPEC_FILE"
        sed -i "s/DESCRIPTION_PLACEHOLDER/$DESCRIPTION_ESC/g" "$SPEC_FILE"
        sed -i "s/REQUEST_PLACEHOLDER/$REQUEST_ESC/g" "$SPEC_FILE"

        # Append notes at the end (after NOTES_PLACEHOLDER marker)
        sed -i "s/NOTES_PLACEHOLDER//" "$SPEC_FILE"
        echo "" >> "$SPEC_FILE"
        echo "$NOTES" >> "$SPEC_FILE"

        # Ensure file is flushed to disk
        sync

        echo "  ✓ Placeholder spec created"

        # Verify file exists (debugging)
        if [[ ! -f "$SPEC_FILE" ]]; then
            echo "  ERROR: Spec file not found after creation: $SPEC_FILE"
            exit 1
        fi
    fi

    echo "  Creating task in coordination system..."

    # Use coord CLI to create task (pass spec path for high/crit tasks)
    if [[ "$CATEGORY" == "high" ]] || [[ "$CATEGORY" == "crit" ]]; then
        if .claude-coord/bin/coord task-create "$TASK_ID" "$SUBJECT" "$DESCRIPTION" --spec-path "$SPEC_FILE" 2>&1; then
            echo "  ✓ Task created successfully"
        else
            echo "  ✗ Failed to create task"
            exit 1
        fi
    else
        if .claude-coord/bin/coord task-create "$TASK_ID" "$SUBJECT" "$DESCRIPTION" 2>&1; then
            echo "  ✓ Task created successfully"
        else
            echo "  ✗ Failed to create task"
            exit 1
        fi
    fi

    # Add dependencies if specified
    if [[ -n "$DEPENDS_ON" ]]; then
        for dep_suffix in $DEPENDS_ON; do
            # Convert suffix to full task ID - need to find the category of the dependency
            # For now, we'll look it up from the template
            DEP_INDEX=-1
            for ((j=0; j<SUBTASK_COUNT; j++)); do
                DEP_ID_SUFFIX=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks[$j].id_suffix" "$TEMPLATES_FILE")
                if [[ "$DEP_ID_SUFFIX" == "$dep_suffix" ]]; then
                    DEP_INDEX=$j
                    break
                fi
            done

            if [[ $DEP_INDEX -ge 0 ]]; then
                DEP_CATEGORY=$("$YQ_CMD" eval ".templates[$TEMPLATE_INDEX].subtasks[$DEP_INDEX].category" "$TEMPLATES_FILE")
                DEP_TASK_ID="${PREFIX}-${DEP_CATEGORY}-${BASE_IDENTIFIER}-${dep_suffix}"
            else
                echo "  Warning: Could not find dependency $dep_suffix in template"
                continue
            fi
            echo "  Adding dependency: $TASK_ID depends on $DEP_TASK_ID"

            if .claude-coord/bin/coord task-add-dep "$TASK_ID" "$DEP_TASK_ID" 2>&1; then
                echo "  ✓ Dependency added"
            else
                echo "  ✗ Failed to add dependency"
                exit 1
            fi
        done
    fi

    # Prepare spec-creator request (JSON)
    SPEC_REQUEST=$(jq -n \
        --arg task_id "$TASK_ID" \
        --arg subject "$SUBJECT" \
        --arg description "$DESCRIPTION" \
        --arg category "$CATEGORY" \
        --arg notes "$NOTES" \
        --arg request "$REQUEST" \
        --arg provider "$PROVIDER" \
        --arg resource "$RESOURCE" \
        --arg template_type "$TEMPLATE_TYPE" \
        '{
            task_id: $task_id,
            subject: $subject,
            description: $description,
            category: $category,
            decomposition_notes: $notes,
            request: $request,
            entities: {
                provider: $provider,
                resource: $resource
            },
            template_type: $template_type
        }')

    SPEC_REQUESTS+=("$SPEC_REQUEST")
done

echo ""
echo "=========================================="
echo "Task Creation Complete"
echo "=========================================="
echo "Created ${#CREATED_TASKS[@]} tasks:"
for task in "${CREATED_TASKS[@]}"; do
    echo "  - $task"
done
echo ""

# Output spec creation requests for Claude to process
echo "=========================================="
echo "Spec Generation Requests"
echo "=========================================="
echo ""
echo "The following spec-creator requests need to be processed by Claude:"
echo ""

for ((i=0; i<${#SPEC_REQUESTS[@]}; i++)); do
    echo "SPEC_REQUEST_$((i+1)):"
    echo "${SPEC_REQUESTS[$i]}" | jq '.'
    echo ""
done

echo "=========================================="
echo "Next Steps"
echo "=========================================="
echo ""
echo "Claude should now:"
echo "1. For each SPEC_REQUEST above, invoke the spec-creator agent"
echo "2. Write the generated spec to .claude-coord/task-specs/{task_id}.md"
echo "3. Verify all specs are created successfully"
echo ""
echo "Once specs are created, agents can claim tasks with:"
echo "  coord task-list"
echo "  coord task-claim \$CLAUDE_AGENT_ID <task-id>"
echo ""
echo "=========================================="
