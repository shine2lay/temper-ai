#!/bin/bash
# Setup recommended prefix priorities for task coordination

COORD_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/claude-coord.sh"

echo "=========================================="
echo "Setting Up Prefix Priorities"
echo "=========================================="
echo ""

# Priority 1 - CRITICAL (Security, Safety, Critical Tests)
echo "Priority 1 - CRITICAL..."
"$COORD_SCRIPT" task-prefix-set code-crit 1
"$COORD_SCRIPT" task-prefix-set doc-crit 1
"$COORD_SCRIPT" task-prefix-set test-crit 1
"$COORD_SCRIPT" task-prefix-set test-security 1
"$COORD_SCRIPT" task-prefix-set m4 1

# Priority 2 - HIGH (Important fixes, performance, refactoring)
echo "Priority 2 - HIGH..."
"$COORD_SCRIPT" task-prefix-set code-high 2
"$COORD_SCRIPT" task-prefix-set doc-high 2
"$COORD_SCRIPT" task-prefix-set test-high 2
"$COORD_SCRIPT" task-prefix-set test-fix 2
"$COORD_SCRIPT" task-prefix-set test-integration 2
"$COORD_SCRIPT" task-prefix-set m3.2 2
"$COORD_SCRIPT" task-prefix-set m3.3 2
"$COORD_SCRIPT" task-prefix-set cq-p0 2

# Priority 3 - NORMAL (Regular development)
echo "Priority 3 - NORMAL..."
"$COORD_SCRIPT" task-prefix-set code-med 3
"$COORD_SCRIPT" task-prefix-set doc-med 3
"$COORD_SCRIPT" task-prefix-set doc-guide 3
"$COORD_SCRIPT" task-prefix-set doc-api 3
"$COORD_SCRIPT" task-prefix-set test-med 3
"$COORD_SCRIPT" task-prefix-set test-llm 3
"$COORD_SCRIPT" task-prefix-set test-tool 3
"$COORD_SCRIPT" task-prefix-set m3 3
"$COORD_SCRIPT" task-prefix-set m3.1 3
"$COORD_SCRIPT" task-prefix-set cq-p1 3
"$COORD_SCRIPT" task-prefix-set doc-reorg 3
"$COORD_SCRIPT" task-prefix-set doc-update 3
"$COORD_SCRIPT" task-prefix-set test-agent 3
"$COORD_SCRIPT" task-prefix-set test-error 3

# Priority 4 - LOW (Code quality, polish)
echo "Priority 4 - LOW..."
"$COORD_SCRIPT" task-prefix-set code-low 4
"$COORD_SCRIPT" task-prefix-set doc-low 4
"$COORD_SCRIPT" task-prefix-set doc-consolidate 4
"$COORD_SCRIPT" task-prefix-set test-low 4
"$COORD_SCRIPT" task-prefix-set test-perf 4
"$COORD_SCRIPT" task-prefix-set test-workflow 4
"$COORD_SCRIPT" task-prefix-set m2.5 4
"$COORD_SCRIPT" task-prefix-set test-observability 4
"$COORD_SCRIPT" task-prefix-set test-boundary 4
"$COORD_SCRIPT" task-prefix-set test-collaboration 4
"$COORD_SCRIPT" task-prefix-set test-database 4
"$COORD_SCRIPT" task-prefix-set test-state 4
"$COORD_SCRIPT" task-prefix-set test-property 4
"$COORD_SCRIPT" task-prefix-set test-regression 4

# Priority 5 - BACKLOG (Old milestones, archive work)
echo "Priority 5 - BACKLOG..."
"$COORD_SCRIPT" task-prefix-set doc-archive 5
"$COORD_SCRIPT" task-prefix-set doc-adr 5
"$COORD_SCRIPT" task-prefix-set m1 5
"$COORD_SCRIPT" task-prefix-set m2 5

echo ""
echo "=========================================="
echo "Prefix Priorities Setup Complete!"
echo "=========================================="
echo ""
echo "View configured priorities:"
echo "  $COORD_SCRIPT task-prefix-list"
echo ""
echo "Test task selection:"
echo "  $COORD_SCRIPT register test-agent"
echo "  $COORD_SCRIPT task-next test-agent"
echo ""
