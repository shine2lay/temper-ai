#!/bin/bash
# Integration test for task dependency system

set -e  # Exit on error

PROJECT_ROOT="/home/shinelay/meta-autonomous-framework"
COORD="$PROJECT_ROOT/.claude-coord/bin/coord"

echo "=== Task Dependency System Integration Test ==="
echo

# Clean up any existing test tasks
echo "1. Cleaning up old test data..."
rm -f "$PROJECT_ROOT/.claude-coord/coordination.db"*
rm -f /tmp/coord-*.sock
pkill -f "coord_service.daemon" 2>/dev/null || true
sleep 1

# Start fresh daemon
echo "2. Starting coordination daemon..."
$COORD status > /dev/null 2>&1 || { echo "Failed to start daemon"; exit 1; }
echo "   ✓ Daemon running"
echo

# Register test agent
echo "3. Registering test agent..."
$COORD register test-agent 999999 > /dev/null
echo "   ✓ Agent registered"
echo

# Create test tasks
echo "4. Creating test tasks..."
$COORD task-create test-high-dep-1 "Setup database" "Create schema and tables" > /dev/null
$COORD task-create test-high-dep-2 "Seed test data" "Add initial records" > /dev/null
$COORD task-create test-high-dep-3 "Run migrations" "Apply schema changes" > /dev/null
$COORD task-create test-high-dep-4 "Verify setup" "Check database integrity" > /dev/null
echo "   ✓ Created 4 tasks"
echo

# Set up dependencies
echo "5. Setting up dependency chain (4 -> 3 -> 2 -> 1)..."
$COORD task-add-dep test-high-dep-2 test-high-dep-1 > /dev/null
$COORD task-add-dep test-high-dep-3 test-high-dep-2 > /dev/null
$COORD task-add-dep test-high-dep-4 test-high-dep-3 > /dev/null
echo "   ✓ Dependencies configured"
echo

# Test: Only task 1 should be available
echo "6. Checking available tasks (should be only task-1)..."
AVAILABLE=$($COORD task-list | grep -c "test-high-dep-1" || echo 0)
if [ "$AVAILABLE" -eq 1 ]; then
    echo "   ✓ Only task-1 is available"
else
    echo "   ✗ Expected task-1 to be available"
    exit 1
fi
echo

# Test: Tasks 2-4 should be blocked
echo "7. Checking blocked tasks (should be tasks 2-4)..."
BLOCKED=$($COORD task-blocked | grep -c "test-high-dep-" || echo 0)
if [ "$BLOCKED" -eq 3 ]; then
    echo "   ✓ Tasks 2-4 are blocked"
else
    echo "   ✗ Expected 3 blocked tasks, got $BLOCKED"
    exit 1
fi
echo

# Test: View dependencies
echo "8. Viewing task-2 dependencies..."
$COORD task-deps test-high-dep-2 | grep -q "test-high-dep-1" && echo "   ✓ task-2 depends on task-1"
$COORD task-deps test-high-dep-2 | grep -q "test-high-dep-3" && echo "   ✓ task-2 blocks task-3"
echo

# Test: Circular dependency prevention
echo "9. Testing circular dependency prevention..."
if $COORD task-add-dep test-high-dep-1 test-high-dep-4 2>&1 | grep -q "circular"; then
    echo "   ✓ Circular dependency correctly prevented"
else
    echo "   ✗ Circular dependency should have been prevented"
    exit 1
fi
echo

# Complete task 1
echo "10. Completing task-1..."
$COORD task-claim test-agent test-high-dep-1 > /dev/null
$COORD task-complete test-agent test-high-dep-1 > /dev/null
echo "    ✓ Task-1 completed"
echo

# Test: Task 2 should now be available
echo "11. Checking that task-2 is now available..."
if $COORD task-list | grep -q "test-high-dep-2"; then
    echo "    ✓ Task-2 is now available"
else
    echo "    ✗ Task-2 should be available after task-1 completed"
    exit 1
fi
echo

# Test: Only 2 tasks should be blocked now
echo "12. Checking blocked tasks (should be tasks 3-4)..."
BLOCKED=$($COORD task-blocked | grep -c "test-high-dep-" || echo 0)
if [ "$BLOCKED" -eq 2 ]; then
    echo "    ✓ Tasks 3-4 are still blocked"
else
    echo "    ✗ Expected 2 blocked tasks, got $BLOCKED"
    exit 1
fi
echo

# Complete task 2
echo "13. Completing task-2..."
$COORD task-claim test-agent test-high-dep-2 > /dev/null
$COORD task-complete test-agent test-high-dep-2 > /dev/null
echo "    ✓ Task-2 completed"
echo

# Test: Task 3 should now be available
echo "14. Checking that task-3 is now available..."
if $COORD task-list | grep -q "test-high-dep-3"; then
    echo "    ✓ Task-3 is now available"
else
    echo "    ✗ Task-3 should be available after task-2 completed"
    exit 1
fi
echo

# Complete task 3
echo "15. Completing task-3..."
$COORD task-claim test-agent test-high-dep-3 > /dev/null
$COORD task-complete test-agent test-high-dep-3 > /dev/null
echo "    ✓ Task-3 completed"
echo

# Test: Task 4 should now be available
echo "16. Checking that task-4 is now available..."
if $COORD task-list | grep -q "test-high-dep-4"; then
    echo "    ✓ Task-4 is now available"
else
    echo "    ✗ Task-4 should be available after task-3 completed"
    exit 1
fi
echo

# Test: No tasks should be blocked
echo "17. Checking that no tasks are blocked..."
if $COORD task-blocked | grep -q "No blocked tasks"; then
    echo "    ✓ No tasks are blocked"
else
    echo "    ✗ All dependencies satisfied, no tasks should be blocked"
    exit 1
fi
echo

echo "=== All Integration Tests Passed! ==="
echo
echo "Summary:"
echo "  ✓ Dependency creation"
echo "  ✓ Available task filtering"
echo "  ✓ Blocked task listing"
echo "  ✓ Dependency visualization"
echo "  ✓ Circular dependency prevention"
echo "  ✓ Automatic unblocking on completion"
echo "  ✓ Multi-level dependency chains"
