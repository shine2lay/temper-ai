#!/bin/bash
# Setup prefix priorities: Milestones first, then tests, code, docs

COORD_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/claude-coord.sh"

echo "=========================================="
echo "Setting Up Milestone-First Priority Order"
echo "=========================================="
echo ""
echo "Order: m1 → m2 → m2.5 → m3 → m3.1 → m3.2 → m3.3 → m4 → tests → code → docs"
echo ""

# Clear all existing prefix priorities first
echo "Clearing existing priorities..."
jq -r '.prefix_priorities | keys[]' "$COORD_SCRIPT/../state.json" 2>/dev/null | while read prefix; do
    "$COORD_SCRIPT" task-prefix-clear "$prefix" 2>/dev/null || true
done

echo ""
echo "Setting new priorities..."
echo ""

# Milestone priorities (1-10)
echo "Priority 1 - m1 (Foundation)..."
"$COORD_SCRIPT" task-prefix-set m1 1

echo "Priority 2 - m2 (Core Features)..."
"$COORD_SCRIPT" task-prefix-set m2 2

echo "Priority 3 - m2.5 (Engine Abstraction)..."
"$COORD_SCRIPT" task-prefix-set m2.5 3

echo "Priority 4 - m3 (Multi-Agent Core)..."
"$COORD_SCRIPT" task-prefix-set m3 4

echo "Priority 5 - m3.1 (Type Safety)..."
"$COORD_SCRIPT" task-prefix-set m3.1 5

echo "Priority 6 - m3.2 (Compiler Refactoring)..."
"$COORD_SCRIPT" task-prefix-set m3.2 6

echo "Priority 7 - m3.3 (Performance)..."
"$COORD_SCRIPT" task-prefix-set m3.3 7

echo "Priority 8 - m4 (Safety System)..."
"$COORD_SCRIPT" task-prefix-set m4 8

# Test priorities (11-20)
echo "Priority 11 - test-crit..."
"$COORD_SCRIPT" task-prefix-set test-crit 11

echo "Priority 12 - test-security..."
"$COORD_SCRIPT" task-prefix-set test-security 12

echo "Priority 13 - test-high..."
"$COORD_SCRIPT" task-prefix-set test-high 13

echo "Priority 14 - test-fix..."
"$COORD_SCRIPT" task-prefix-set test-fix 14

echo "Priority 15 - test-integration..."
"$COORD_SCRIPT" task-prefix-set test-integration 15

echo "Priority 16 - test-med..."
"$COORD_SCRIPT" task-prefix-set test-med 16

echo "Priority 17 - test-llm..."
"$COORD_SCRIPT" task-prefix-set test-llm 17

echo "Priority 18 - test-tool..."
"$COORD_SCRIPT" task-prefix-set test-tool 18

echo "Priority 19 - test-perf..."
"$COORD_SCRIPT" task-prefix-set test-perf 19

echo "Priority 20 - test-workflow..."
"$COORD_SCRIPT" task-prefix-set test-workflow 20

echo "Priority 21 - test-agent..."
"$COORD_SCRIPT" task-prefix-set test-agent 21

echo "Priority 22 - test-error..."
"$COORD_SCRIPT" task-prefix-set test-error 22

echo "Priority 23 - test-low..."
"$COORD_SCRIPT" task-prefix-set test-low 23

echo "Priority 24 - test-* (other)..."
"$COORD_SCRIPT" task-prefix-set test-observability 24
"$COORD_SCRIPT" task-prefix-set test-boundary 24
"$COORD_SCRIPT" task-prefix-set test-collaboration 24
"$COORD_SCRIPT" task-prefix-set test-database 24
"$COORD_SCRIPT" task-prefix-set test-state 24
"$COORD_SCRIPT" task-prefix-set test-property 24
"$COORD_SCRIPT" task-prefix-set test-regression 24

# Code priorities (31-40)
echo "Priority 31 - code-crit..."
"$COORD_SCRIPT" task-prefix-set code-crit 31

echo "Priority 32 - code-high..."
"$COORD_SCRIPT" task-prefix-set code-high 32

echo "Priority 33 - code-med..."
"$COORD_SCRIPT" task-prefix-set code-med 33

echo "Priority 34 - code-low..."
"$COORD_SCRIPT" task-prefix-set code-low 34

echo "Priority 35 - cq-p0..."
"$COORD_SCRIPT" task-prefix-set cq-p0 35

echo "Priority 36 - cq-p1..."
"$COORD_SCRIPT" task-prefix-set cq-p1 36

# Doc priorities (41-50)
echo "Priority 41 - doc-crit..."
"$COORD_SCRIPT" task-prefix-set doc-crit 41

echo "Priority 42 - doc-high..."
"$COORD_SCRIPT" task-prefix-set doc-high 42

echo "Priority 43 - doc-guide..."
"$COORD_SCRIPT" task-prefix-set doc-guide 43

echo "Priority 44 - doc-api..."
"$COORD_SCRIPT" task-prefix-set doc-api 44

echo "Priority 45 - doc-med..."
"$COORD_SCRIPT" task-prefix-set doc-med 45

echo "Priority 46 - doc-adr..."
"$COORD_SCRIPT" task-prefix-set doc-adr 46

echo "Priority 47 - doc-reorg..."
"$COORD_SCRIPT" task-prefix-set doc-reorg 47

echo "Priority 48 - doc-consolidate..."
"$COORD_SCRIPT" task-prefix-set doc-consolidate 48

echo "Priority 49 - doc-low..."
"$COORD_SCRIPT" task-prefix-set doc-low 49

echo "Priority 50 - doc-archive..."
"$COORD_SCRIPT" task-prefix-set doc-archive 50

echo "Priority 51 - doc-update..."
"$COORD_SCRIPT" task-prefix-set doc-update 51

echo ""
echo "=========================================="
echo "Milestone-First Priority Setup Complete!"
echo "=========================================="
echo ""
echo "Execution Order:"
echo "  1. m1 (Foundation) - 8 tasks"
echo "  2. m2 (Core Features) - 8 tasks"
echo "  3. m2.5 (Engine Abstraction) - 5 tasks"
echo "  4. m3 (Multi-Agent Core) - 11 tasks"
echo "  5. m3.1 (Type Safety) - 6 tasks"
echo "  6. m3.2 (Compiler Refactoring) - 14 tasks"
echo "  7. m3.3 (Performance) - 6 tasks"
echo "  8. m4 (Safety System) - 15 tasks"
echo "  9. Tests (all test-* prefixes) - 71 tasks"
echo "  10. Code (all code-* prefixes) - 49 tasks"
echo "  11. Docs (all doc-* prefixes) - 85 tasks"
echo ""
echo "View configured priorities:"
echo "  $COORD_SCRIPT task-prefix-list"
echo ""
echo "Start working:"
echo "  $COORD_SCRIPT register my-agent"
echo "  $COORD_SCRIPT task-next my-agent"
echo ""
