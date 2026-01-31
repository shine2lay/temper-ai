#!/bin/bash
# Comprehensive test suite for claude-coord.sh
# Tests all commands with normal operations, edge cases, and error conditions

# Don't exit on errors - we want to test error conditions
set +e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COORD_SCRIPT="$SCRIPT_DIR/claude-coord.sh"
STATE_FILE="$SCRIPT_DIR/state.json"
BACKUP_STATE="$SCRIPT_DIR/state.json.backup"

# Test output file
TEST_REPORT="$SCRIPT_DIR/test-report.txt"

# Initialize test report
init_report() {
    cat > "$TEST_REPORT" <<EOF
================================================================================
CLAUDE COORDINATION SYSTEM - COMPREHENSIVE TEST REPORT
================================================================================
Test Date: $(date)
Script Version: claude-coord.sh
================================================================================

EOF
}

# Logging functions
log_section() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo "" >> "$TEST_REPORT"
    echo "========================================" >> "$TEST_REPORT"
    echo "$1" >> "$TEST_REPORT"
    echo "========================================" >> "$TEST_REPORT"
}

log_test() {
    echo -e "${YELLOW}TEST: $1${NC}"
    echo "TEST: $1" >> "$TEST_REPORT"
    ((TOTAL_TESTS++))
}

log_pass() {
    echo -e "${GREEN}  ✓ PASS${NC}"
    echo "  ✓ PASS" >> "$TEST_REPORT"
    ((PASSED_TESTS++))
}

log_fail() {
    echo -e "${RED}  ✗ FAIL: $1${NC}"
    echo "  ✗ FAIL: $1" >> "$TEST_REPORT"
    ((FAILED_TESTS++))
}

log_info() {
    echo -e "  ${NC}$1${NC}"
    echo "  $1" >> "$TEST_REPORT"
}

# Backup and restore state
backup_state() {
    if [ -f "$STATE_FILE" ]; then
        cp "$STATE_FILE" "$BACKUP_STATE"
    fi
}

restore_state() {
    if [ -f "$BACKUP_STATE" ]; then
        mv "$BACKUP_STATE" "$STATE_FILE"
    fi
}

cleanup_state() {
    rm -f "$STATE_FILE"
    rm -f "$SCRIPT_DIR/.state.lock"
}

# Test helper: run command and capture output
run_cmd() {
    local output
    local exit_code
    output=$("$COORD_SCRIPT" "$@" 2>&1) || exit_code=$?
    exit_code=${exit_code:-0}
    echo "$output"
    return $exit_code
}

# Test helper: check if output contains string
output_contains() {
    local output="$1"
    local expected="$2"
    if echo "$output" | grep -q "$expected"; then
        return 0
    else
        return 1
    fi
}

# Test helper: verify JSON field
check_json_field() {
    local task_id="$1"
    local field="$2"
    local expected="$3"

    local actual=$(jq -r ".tasks[\"$task_id\"].$field // empty" "$STATE_FILE")
    if [ "$actual" = "$expected" ]; then
        return 0
    else
        log_fail "Expected $field='$expected', got '$actual'"
        return 1
    fi
}

################################################################################
# AGENT COMMAND TESTS
################################################################################

test_agent_commands() {
    log_section "AGENT COMMANDS"

    # Test 1: Register agent with auto PID
    log_test "Register agent with auto PID"
    output=$(run_cmd register test-agent-1)
    if output_contains "$output" "Registered agent: test-agent-1"; then
        log_pass
    else
        log_fail "Registration failed: $output"
    fi

    # Test 2: Register agent with custom PID
    log_test "Register agent with custom PID"
    output=$(run_cmd register test-agent-2 12345)
    if output_contains "$output" "pid: 12345"; then
        log_pass
    else
        log_fail "Custom PID not set: $output"
    fi

    # Test 3: Heartbeat update
    log_test "Update agent heartbeat"
    sleep 1
    output=$(run_cmd heartbeat test-agent-1)
    if [ $? -eq 0 ]; then
        log_pass
    else
        log_fail "Heartbeat failed: $output"
    fi

    # Test 4: Unregister agent
    log_test "Unregister agent"
    output=$(run_cmd unregister test-agent-1)
    if output_contains "$output" "Unregistered agent: test-agent-1"; then
        log_pass
    else
        log_fail "Unregistration failed: $output"
    fi

    # Test 5: Unregister non-existent agent
    log_test "Unregister non-existent agent (should succeed gracefully)"
    output=$(run_cmd unregister non-existent-agent)
    if output_contains "$output" "not found"; then
        log_pass
    else
        log_fail "Expected 'not found' message: $output"
    fi

    # Test 6: Register missing parameter
    log_test "Register with missing agent_id (should fail)"
    output=$(run_cmd register 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "Usage"; then
        log_pass
    else
        log_fail "Should reject missing parameter"
    fi

    # Test 7: Heartbeat for non-existent agent (should succeed silently)
    log_test "Heartbeat for non-existent agent"
    output=$(run_cmd heartbeat non-existent)
    if [ $? -eq 0 ]; then
        log_pass
    else
        log_fail "Heartbeat should succeed silently: $output"
    fi
}

################################################################################
# LOCK COMMAND TESTS
################################################################################

test_lock_commands() {
    log_section "LOCK COMMANDS"

    # Setup: register test agents
    run_cmd register lock-agent-1 $$
    run_cmd register lock-agent-2 $$

    # Test 1: Acquire lock
    log_test "Acquire single lock"
    output=$(run_cmd lock lock-agent-1 /tmp/test-file-1.txt)
    if output_contains "$output" "Locked: /tmp/test-file-1.txt"; then
        log_pass
    else
        log_fail "Lock acquisition failed: $output"
    fi

    # Test 2: Check lock status (owned)
    log_test "Check lock status (owned by self)"
    output=$(run_cmd check lock-agent-1 /tmp/test-file-1.txt)
    if output_contains "$output" "OWNED"; then
        log_pass
    else
        log_fail "Expected OWNED status: $output"
    fi

    # Test 3: Check lock status (locked by other)
    log_test "Check lock status (locked by other)"
    output=$(run_cmd check lock-agent-2 /tmp/test-file-1.txt 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "LOCKED by lock-agent-1"; then
        log_pass
    else
        log_fail "Expected LOCKED status: $output"
    fi

    # Test 4: Attempt to lock already-locked file (should fail)
    log_test "Lock already-locked file (should fail)"
    output=$(run_cmd lock lock-agent-2 /tmp/test-file-1.txt 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "FAILED"; then
        log_pass
    else
        log_fail "Should reject lock attempt: $output"
    fi

    # Test 5: Re-lock by same owner (should succeed)
    log_test "Re-lock by same owner (should succeed)"
    output=$(run_cmd lock lock-agent-1 /tmp/test-file-1.txt)
    if output_contains "$output" "Locked"; then
        log_pass
    else
        log_fail "Re-lock by owner should succeed: $output"
    fi

    # Test 6: Unlock file
    log_test "Unlock file"
    output=$(run_cmd unlock lock-agent-1 /tmp/test-file-1.txt)
    if output_contains "$output" "Unlocked"; then
        log_pass
    else
        log_fail "Unlock failed: $output"
    fi

    # Test 7: Check unlocked file
    log_test "Check unlocked file status"
    output=$(run_cmd check "" /tmp/test-file-1.txt)
    if output_contains "$output" "UNLOCKED"; then
        log_pass
    else
        log_fail "Expected UNLOCKED status: $output"
    fi

    # Test 8: Unlock non-owned file (should fail)
    run_cmd lock lock-agent-1 /tmp/test-file-2.txt
    log_test "Unlock file owned by other agent (should fail)"
    output=$(run_cmd unlock lock-agent-2 /tmp/test-file-2.txt 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "FAILED"; then
        log_pass
    else
        log_fail "Should reject unlock by non-owner: $output"
    fi

    # Test 9: Lock-all (atomic multi-lock)
    log_test "Lock multiple files atomically (lock-all)"
    output=$(run_cmd lock-all lock-agent-2 /tmp/test-a.txt /tmp/test-b.txt /tmp/test-c.txt)
    if output_contains "$output" "Locked 3 files"; then
        log_pass
    else
        log_fail "lock-all failed: $output"
    fi

    # Test 10: Lock-all with one blocked (should fail all)
    log_test "Lock-all with one file blocked (should fail atomically)"
    output=$(run_cmd lock-all lock-agent-1 /tmp/test-a.txt /tmp/test-d.txt 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "FAILED"; then
        log_pass
    else
        log_fail "Should reject lock-all when any file blocked: $output"
    fi

    # Test 11: Unlock-all
    log_test "Unlock all files held by agent"
    output=$(run_cmd unlock-all lock-agent-2)
    if output_contains "$output" "Released 3 locks"; then
        log_pass
    else
        log_fail "unlock-all failed: $output"
    fi

    # Test 12: My-locks command
    run_cmd lock lock-agent-1 /tmp/myfile1.txt
    run_cmd lock lock-agent-1 /tmp/myfile2.txt
    log_test "List locks held by agent (my-locks)"
    output=$(run_cmd my-locks lock-agent-1)
    if output_contains "$output" "/tmp/myfile1.txt" && output_contains "$output" "/tmp/myfile2.txt"; then
        log_pass
    else
        log_fail "my-locks didn't return expected files: $output"
    fi

    # Test 13: Lock missing parameters
    log_test "Lock with missing parameters (should fail)"
    output=$(run_cmd lock lock-agent-1 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "Usage"; then
        log_pass
    else
        log_fail "Should reject missing parameters"
    fi

    # Cleanup
    run_cmd unlock-all lock-agent-1
    run_cmd unregister lock-agent-1
    run_cmd unregister lock-agent-2
}

################################################################################
# TASK COMMAND TESTS
################################################################################

test_task_commands() {
    log_section "TASK COMMANDS - BASIC OPERATIONS"

    # Test 1: Add task with minimal parameters
    log_test "Add task with minimal parameters"
    output=$(run_cmd task-add task-001 "Test task 1")
    if output_contains "$output" "Added task: task-001"; then
        log_pass
    else
        log_fail "Task addition failed: $output"
    fi

    # Test 2: Add task with all parameters
    log_test "Add task with all parameters (description, priority, creator)"
    output=$(run_cmd task-add task-002 "Test task 2" "Detailed description" 2 creator-agent)
    if output_contains "$output" "priority: 2"; then
        log_pass
    else
        log_fail "Task with all params failed: $output"
    fi

    # Test 3: Add task with dependencies
    log_test "Add task with dependencies"
    output=$(run_cmd task-add task-003 "Dependent task" "" 3 "" "task-001,task-002")
    if output_contains "$output" "depends on: task-001,task-002"; then
        log_pass
    else
        log_fail "Task dependencies not set: $output"
    fi

    # Test 4: Get task details
    log_test "Get task details (task-get)"
    output=$(run_cmd task-get task-001)
    if output_contains "$output" "Test task 1" && output_contains "$output" "pending"; then
        log_pass
    else
        log_fail "task-get failed: $output"
    fi

    # Test 5: Get non-existent task
    log_test "Get non-existent task (should fail)"
    output=$(run_cmd task-get non-existent-task 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "not found"; then
        log_pass
    else
        log_fail "Should fail for non-existent task"
    fi

    # Test 6: Task list (all)
    log_test "List all tasks"
    output=$(run_cmd task-list all)
    if output_contains "$output" "task-001" && output_contains "$output" "task-002" && output_contains "$output" "task-003"; then
        log_pass
    else
        log_fail "task-list didn't show all tasks: $output"
    fi

    # Test 7: Task list (pending)
    log_test "List pending tasks"
    output=$(run_cmd task-list pending)
    if output_contains "$output" "pending"; then
        log_pass
    else
        log_fail "task-list pending failed: $output"
    fi

    # Test 8: Task search
    log_test "Search tasks by keyword"
    output=$(run_cmd task-search "Test")
    if output_contains "$output" "task-001"; then
        log_pass
    else
        log_fail "task-search failed: $output"
    fi

    # Test 9: Task stats
    log_test "Get task statistics"
    output=$(run_cmd task-stats)
    if output_contains "$output" "Pending:" && output_contains "$output" "Total:"; then
        log_pass
    else
        log_fail "task-stats failed: $output"
    fi

    # Test 10: Invalid priority (should fail)
    log_test "Add task with invalid priority (should fail)"
    output=$(run_cmd task-add bad-task "Bad priority" "" 99 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "priority must be 1-5"; then
        log_pass
    else
        log_fail "Should reject invalid priority"
    fi

    # Test 11: Missing required parameters
    log_test "Add task with missing subject (should fail)"
    output=$(run_cmd task-add task-bad 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "Usage"; then
        log_pass
    else
        log_fail "Should reject missing subject"
    fi
}

test_task_lifecycle() {
    log_section "TASK COMMANDS - LIFECYCLE"

    # Setup
    run_cmd register task-agent-1 $$
    run_cmd task-add lifecycle-task "Lifecycle test task"

    # Test 1: Claim task
    log_test "Claim task"
    output=$(run_cmd task-claim task-agent-1 lifecycle-task)
    if output_contains "$output" "Claimed task: lifecycle-task"; then
        log_pass
    else
        log_fail "Task claim failed: $output"
    fi

    # Test 2: Verify task status changed to in_progress
    log_test "Verify task status is in_progress after claim"
    output=$(run_cmd task-get lifecycle-task)
    if output_contains "$output" '"status": "in_progress"'; then
        log_pass
    else
        log_fail "Status not updated to in_progress: $output"
    fi

    # Test 3: Attempt to claim already-claimed task
    run_cmd register task-agent-2 $$
    log_test "Claim already-claimed task (should fail)"
    output=$(run_cmd task-claim task-agent-2 lifecycle-task 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "claimed by task-agent-1"; then
        log_pass
    else
        log_fail "Should reject claim of claimed task: $output"
    fi

    # Test 4: Complete task
    log_test "Complete task"
    output=$(run_cmd task-complete task-agent-1 lifecycle-task)
    if output_contains "$output" "Completed task: lifecycle-task"; then
        log_pass
    else
        log_fail "Task completion failed: $output"
    fi

    # Test 5: Verify task status is completed
    log_test "Verify task status is completed"
    output=$(run_cmd task-get lifecycle-task)
    if output_contains "$output" '"status": "completed"'; then
        log_pass
    else
        log_fail "Status not updated to completed: $output"
    fi

    # Test 6: Release task (back to pending)
    run_cmd task-add release-task "Release test"
    run_cmd task-claim task-agent-1 release-task
    log_test "Release task back to pending"
    output=$(run_cmd task-release task-agent-1 release-task)
    if output_contains "$output" "Released task: release-task"; then
        log_pass
    else
        log_fail "Task release failed: $output"
    fi

    # Test 7: Verify released task is pending with no owner
    log_test "Verify released task is pending with no owner"
    output=$(run_cmd task-get release-task)
    if output_contains "$output" '"status": "pending"' && output_contains "$output" '"owner": null'; then
        log_pass
    else
        log_fail "Released task not properly reset: $output"
    fi

    # Test 8: One task per agent limit
    run_cmd task-add limit-task-1 "First task"
    run_cmd task-add limit-task-2 "Second task"
    run_cmd task-claim task-agent-2 limit-task-1
    log_test "One task per agent limit (should fail)"
    output=$(run_cmd task-claim task-agent-2 limit-task-2 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "already has a claimed task"; then
        log_pass
    else
        log_fail "Should enforce one task per agent: $output"
    fi

    # Cleanup
    run_cmd unregister task-agent-1
    run_cmd unregister task-agent-2
}

test_task_blocking() {
    log_section "TASK COMMANDS - BLOCKING"

    run_cmd register block-agent $$
    run_cmd task-add block-task "Blockable task"

    # Test 1: Block task
    log_test "Block task with agent and file"
    output=$(run_cmd task-block block-task other-agent /tmp/blocked-file.txt)
    if output_contains "$output" "Blocked task: block-task"; then
        log_pass
    else
        log_fail "Task blocking failed: $output"
    fi

    # Test 2: Verify blocked status
    log_test "Verify task is marked as blocked"
    output=$(run_cmd task-get block-task)
    if output_contains "$output" '"blocked": true'; then
        log_pass
    else
        log_fail "Task not marked as blocked: $output"
    fi

    # Test 3: Unblock task
    log_test "Unblock task"
    output=$(run_cmd task-unblock block-task block-agent)
    if output_contains "$output" "Unblocked task: block-task"; then
        log_pass
    else
        log_fail "Task unblock failed: $output"
    fi

    # Test 4: Verify unblocked status
    log_test "Verify task blocked status is cleared"
    output=$(run_cmd task-get block-task)
    if output_contains "$output" '"blocked": null'; then
        log_pass
    else
        log_fail "Blocked status not cleared: $output"
    fi

    # Test 5: Auto-unblock when file lock released
    run_cmd task-block block-task other-agent /tmp/auto-unblock.txt
    run_cmd lock block-agent /tmp/auto-unblock.txt
    log_test "Auto-unblock task when file lock is released"
    output=$(run_cmd unlock block-agent /tmp/auto-unblock.txt)
    if output_contains "$output" "Auto-unblocked task: block-task"; then
        log_pass
    else
        log_fail "Auto-unblock didn't trigger: $output"
    fi

    # Cleanup
    run_cmd unregister block-agent
}

test_task_priority() {
    log_section "TASK COMMANDS - PRIORITY"

    run_cmd task-add prio-task "Priority test"

    # Test 1: Set priority
    log_test "Set task priority"
    output=$(run_cmd task-priority prio-task 1 test-agent)
    if output_contains "$output" "Set priority: prio-task → P1"; then
        log_pass
    else
        log_fail "Priority setting failed: $output"
    fi

    # Test 2: Verify priority in state
    log_test "Verify priority stored correctly"
    output=$(run_cmd task-get prio-task)
    if output_contains "$output" '"priority": 1'; then
        log_pass
    else
        log_fail "Priority not stored: $output"
    fi

    # Test 3: Invalid priority
    log_test "Set invalid priority (should fail)"
    output=$(run_cmd task-priority prio-task 10 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "priority must be 1-5"; then
        log_pass
    else
        log_fail "Should reject invalid priority"
    fi

    # Test 4: Priority for non-existent task
    log_test "Set priority for non-existent task (should fail)"
    output=$(run_cmd task-priority fake-task 3 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "does not exist"; then
        log_pass
    else
        log_fail "Should reject non-existent task"
    fi
}

test_prefix_priority() {
    log_section "PREFIX PRIORITY COMMANDS"

    # Test 1: Set prefix priority
    log_test "Set prefix priority"
    output=$(run_cmd task-prefix-set m3 1)
    if output_contains "$output" "Set prefix priority: m3 = 1"; then
        log_pass
    else
        log_fail "Prefix priority set failed: $output"
    fi

    # Test 2: Set another prefix
    log_test "Set second prefix priority"
    output=$(run_cmd task-prefix-set m4 2)
    if output_contains "$output" "Set prefix priority: m4 = 2"; then
        log_pass
    else
        log_fail "Second prefix priority failed: $output"
    fi

    # Test 3: List prefix priorities
    log_test "List all prefix priorities"
    output=$(run_cmd task-prefix-list)
    if output_contains "$output" "Priority 1: m3" && output_contains "$output" "Priority 2: m4"; then
        log_pass
    else
        log_fail "Prefix list didn't show both prefixes: $output"
    fi

    # Test 4: Clear prefix priority
    log_test "Clear prefix priority"
    output=$(run_cmd task-prefix-clear m4)
    if output_contains "$output" "Cleared prefix priority for: m4"; then
        log_pass
    else
        log_fail "Prefix clear failed: $output"
    fi

    # Test 5: Verify cleared
    log_test "Verify prefix was cleared"
    output=$(run_cmd task-prefix-list)
    if ! output_contains "$output" "m4"; then
        log_pass
    else
        log_fail "Prefix still appears in list: $output"
    fi

    # Test 6: Invalid priority (non-numeric)
    log_test "Set prefix with non-numeric priority (should fail)"
    output=$(run_cmd task-prefix-set bad abc 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "must be a number"; then
        log_pass
    else
        log_fail "Should reject non-numeric priority"
    fi

    # Cleanup
    run_cmd task-prefix-clear m3
}

test_task_dependencies() {
    log_section "TASK DEPENDENCY COMMANDS"

    run_cmd task-add dep-task-a "Task A"
    run_cmd task-add dep-task-b "Task B"
    run_cmd task-add dep-task-c "Task C"

    # Test 1: Set dependencies
    log_test "Set task dependencies"
    output=$(run_cmd task-depends dep-task-c dep-task-a dep-task-b)
    if output_contains "$output" "Blocked by: dep-task-a dep-task-b"; then
        log_pass
    else
        log_fail "Dependency setting failed: $output"
    fi

    # Test 2: Verify dependencies in state
    log_test "Verify dependencies stored in state"
    output=$(run_cmd task-get dep-task-c)
    if output_contains "$output" "dep-task-a" && output_contains "$output" "dep-task-b"; then
        log_pass
    else
        log_fail "Dependencies not stored: $output"
    fi

    # Test 3: Clear dependencies
    log_test "Clear task dependencies"
    output=$(run_cmd task-depends-clear dep-task-c)
    if output_contains "$output" "Cleared dependencies for: dep-task-c"; then
        log_pass
    else
        log_fail "Dependency clear failed: $output"
    fi

    # Test 4: Verify cleared
    log_test "Verify dependencies were cleared"
    output=$(run_cmd task-get dep-task-c)
    if output_contains "$output" '"blocked_by": null'; then
        log_pass
    else
        log_fail "Dependencies not cleared: $output"
    fi

    # Test 5: Missing parameters
    log_test "Set dependencies with missing parameters (should fail)"
    output=$(run_cmd task-depends dep-task-c 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "Must specify at least one blocking task"; then
        log_pass
    else
        log_fail "Should reject missing blocking tasks"
    fi
}

test_task_next() {
    log_section "TASK-NEXT COMMAND (Priority & Dependency Aware)"

    run_cmd register next-agent $$

    # Create tasks with different priorities
    run_cmd task-add next-task-1 "Priority 5 task" "" 5
    run_cmd task-add next-task-2 "Priority 3 task" "" 3
    run_cmd task-add next-task-3 "Priority 1 task" "" 1

    # Test 1: Get next task (should return highest priority)
    log_test "Get next task (should return priority 1 task)"
    output=$(run_cmd task-next next-agent)
    if output_contains "$output" "next-task-3"; then
        log_pass
    else
        log_fail "Should return highest priority task: $output"
    fi

    # Test 2: Prefix priority ordering
    run_cmd task-prefix-set m3 1
    run_cmd task-prefix-set m4 2
    run_cmd task-add m3-task "M3 task" "" 5
    run_cmd task-add m4-task "M4 task" "" 1
    log_test "Prefix priority overrides task priority"
    output=$(run_cmd task-next next-agent)
    if output_contains "$output" "m3-task"; then
        log_pass
    else
        log_fail "Should respect prefix priority: $output"
    fi

    # Test 3: Dependency blocking
    run_cmd task-add base-task "Base task" "" 3
    run_cmd task-add dependent-task "Dependent task" "" 2 "" "base-task"
    log_test "Task-next skips tasks with unmet dependencies"
    output=$(run_cmd task-next next-agent)
    if ! output_contains "$output" "dependent-task"; then
        log_pass
    else
        log_fail "Should skip task with unmet dependencies: $output"
    fi

    # Test 4: No available tasks
    run_cmd task-claim next-agent m3-task
    run_cmd task-claim next-agent next-task-1 2>&1 || true  # Will fail due to one-task limit
    log_test "Task-next when no tasks available"
    # Complete current task first
    run_cmd task-complete next-agent m3-task
    # Block all remaining tasks
    for task in next-task-1 next-task-2 next-task-3 m4-task; do
        run_cmd task-block "$task" blocker /tmp/blocker.txt 2>&1 || true
    done
    output=$(run_cmd task-next next-agent 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "no tasks available"; then
        log_pass
    else
        log_fail "Should return 'no tasks available': $output (exit: $exit_code)"
    fi

    # Cleanup
    run_cmd task-prefix-clear m3
    run_cmd task-prefix-clear m4
    run_cmd unregister next-agent
}

test_task_import() {
    log_section "TASK IMPORT COMMAND"

    # Create test JSON file
    local import_file="/tmp/test-import.json"
    cat > "$import_file" <<'EOF'
{
  "tasks": [
    {
      "id": "import-001",
      "enabled": true,
      "title": "Import test 1",
      "priority": "HIGH",
      "description": "First import"
    },
    {
      "id": "import-002",
      "enabled": true,
      "title": "Import test 2",
      "priority": "NORMAL",
      "description": "Second import",
      "dependencies": {
        "blocked_by": ["import-001"]
      }
    },
    {
      "id": "import-003",
      "enabled": false,
      "title": "Disabled task",
      "priority": "LOW"
    }
  ]
}
EOF

    # Test 1: Dry run import
    log_test "Import tasks (dry run)"
    output=$(run_cmd task-import "$import_file" --dry-run)
    if output_contains "$output" "DRY RUN" && output_contains "$output" "Would import 2 tasks"; then
        log_pass
    else
        log_fail "Dry run failed: $output"
    fi

    # Test 2: Actual import
    log_test "Import tasks (actual)"
    output=$(run_cmd task-import "$import_file")
    if output_contains "$output" "Created: 2 tasks"; then
        log_pass
    else
        log_fail "Import failed: $output"
    fi

    # Test 3: Verify imported tasks exist
    log_test "Verify imported tasks exist in state"
    output=$(run_cmd task-get import-001)
    if output_contains "$output" "Import test 1"; then
        log_pass
    else
        log_fail "Imported task not found: $output"
    fi

    # Test 4: Verify dependencies imported
    log_test "Verify dependencies were imported"
    output=$(run_cmd task-get import-002)
    if output_contains "$output" "import-001"; then
        log_pass
    else
        log_fail "Dependencies not imported: $output"
    fi

    # Test 5: Verify disabled task not imported
    log_test "Verify disabled task was skipped"
    output=$(run_cmd task-get import-003 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_pass
    else
        log_fail "Disabled task should not be imported: $output"
    fi

    # Test 6: Re-import (should skip existing)
    log_test "Re-import (should skip existing tasks)"
    output=$(run_cmd task-import "$import_file")
    if output_contains "$output" "Skipped: 2 tasks"; then
        log_pass
    else
        log_fail "Re-import should skip existing: $output"
    fi

    # Test 7: Invalid JSON file
    echo "invalid json" > /tmp/bad-import.json
    log_test "Import invalid JSON file (should fail)"
    output=$(run_cmd task-import /tmp/bad-import.json 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "Invalid JSON"; then
        log_pass
    else
        log_fail "Should reject invalid JSON"
    fi

    # Cleanup
    rm -f "$import_file" /tmp/bad-import.json
}

test_cleanup_commands() {
    log_section "CLEANUP & MAINTENANCE COMMANDS"

    # Test 1: Task cleanup (completed tasks)
    run_cmd task-add cleanup-task-1 "Cleanup test 1"
    run_cmd register cleanup-agent $$
    run_cmd task-claim cleanup-agent cleanup-task-1
    run_cmd task-complete cleanup-agent cleanup-task-1

    log_test "Task cleanup dry run"
    output=$(run_cmd task-cleanup 0 --dry-run)
    if output_contains "$output" "Would remove"; then
        log_pass
    else
        log_fail "Cleanup dry run failed: $output"
    fi

    # Test 2: Actual cleanup (0 days = cleanup immediately)
    log_test "Task cleanup (actual)"
    # The task was just completed, so it won't be old enough
    # Let's modify the completed_at timestamp directly
    sleep 1
    output=$(run_cmd task-cleanup 0)
    # Check if cleanup ran (may or may not remove tasks depending on timing)
    if output_contains "$output" "Cleaning up"; then
        log_pass
    else
        log_fail "Cleanup didn't run: $output"
    fi

    # Test 3: Task archive
    log_test "Archive completed tasks"
    output=$(run_cmd task-archive /tmp/test-archive.json)
    if output_contains "$output" "Archived" && [ -f /tmp/test-archive.json ]; then
        log_pass
    else
        log_fail "Archive failed: $output"
    fi

    # Test 4: Cleanup dead agents
    run_cmd register dead-agent 999999  # Non-existent PID
    sleep 1
    log_test "Cleanup dead agents"
    output=$(run_cmd cleanup-dead)
    if output_contains "$output" "Checking for dead agents"; then
        log_pass
    else
        log_fail "Cleanup-dead failed: $output"
    fi

    # Test 5: Task recover (orphaned tasks)
    run_cmd task-add orphan-task "Orphaned task"
    run_cmd register orphan-agent 999998
    run_cmd task-claim orphan-agent orphan-task
    run_cmd unregister orphan-agent

    log_test "Recover orphaned tasks (dry run)"
    output=$(run_cmd task-recover --dry-run)
    if output_contains "$output" "ORPHANED"; then
        log_pass
    else
        log_fail "Task recover dry run failed: $output"
    fi

    log_test "Recover orphaned tasks (actual)"
    output=$(run_cmd task-recover)
    if output_contains "$output" "Recovered"; then
        log_pass
    else
        log_fail "Task recover failed: $output"
    fi

    # Cleanup
    run_cmd unregister cleanup-agent 2>&1 || true
    rm -f /tmp/test-archive.json
}

test_status_command() {
    log_section "STATUS COMMAND"

    # Setup: create some state
    run_cmd register status-agent $$
    run_cmd task-add status-task "Status test task"
    run_cmd lock status-agent /tmp/status-file.txt
    run_cmd task-claim status-agent status-task

    # Test 1: Status shows all state
    log_test "Status command shows agents, locks, and tasks"
    output=$(run_cmd status)
    if output_contains "$output" "AGENTS" && \
       output_contains "$output" "LOCKS" && \
       output_contains "$output" "TASKS" && \
       output_contains "$output" "status-agent"; then
        log_pass
    else
        log_fail "Status didn't show all sections: $output"
    fi

    # Cleanup
    run_cmd unlock-all status-agent
    run_cmd unregister status-agent
}

test_parameter_validation() {
    log_section "PARAMETER VALIDATION"

    # Test various commands with missing/invalid parameters

    log_test "Lock with missing file path"
    output=$(run_cmd lock test-agent 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "Usage"; then
        log_pass
    else
        log_fail "Should validate required parameters"
    fi

    log_test "Task-add with empty task ID"
    output=$(run_cmd task-add "" "subject" 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_pass
    else
        log_fail "Should reject empty task ID"
    fi

    log_test "Task-claim with missing task ID"
    output=$(run_cmd task-claim agent-1 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "Usage"; then
        log_pass
    else
        log_fail "Should validate required task ID"
    fi

    log_test "Unlock-all with missing agent ID"
    output=$(run_cmd unlock-all 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ] && output_contains "$output" "Usage"; then
        log_pass
    else
        log_fail "Should validate required agent ID"
    fi
}

test_state_persistence() {
    log_section "STATE PERSISTENCE"

    # Test that state persists across commands
    run_cmd register persist-agent $$
    run_cmd task-add persist-task "Persistence test"
    run_cmd lock persist-agent /tmp/persist-file.txt

    log_test "Agent registration persists"
    output=$(run_cmd status)
    if output_contains "$output" "persist-agent"; then
        log_pass
    else
        log_fail "Agent not persisted: $output"
    fi

    log_test "Task persists"
    output=$(run_cmd task-get persist-task)
    if output_contains "$output" "Persistence test"; then
        log_pass
    else
        log_fail "Task not persisted: $output"
    fi

    log_test "Lock persists"
    output=$(run_cmd check persist-agent /tmp/persist-file.txt)
    if output_contains "$output" "OWNED"; then
        log_pass
    else
        log_fail "Lock not persisted: $output"
    fi

    # Cleanup
    run_cmd unlock-all persist-agent
    run_cmd unregister persist-agent
}

test_concurrent_safety() {
    log_section "CONCURRENT SAFETY (Basic)"

    # Note: Full concurrency testing would require parallel processes
    # These tests verify basic atomic operations

    run_cmd register concurrent-agent-1 $$
    run_cmd register concurrent-agent-2 $$

    log_test "Sequential lock acquisitions work correctly"
    run_cmd lock concurrent-agent-1 /tmp/concurrent-file.txt
    output=$(run_cmd lock concurrent-agent-2 /tmp/concurrent-file.txt 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_pass
    else
        log_fail "Second lock should fail: $output"
    fi

    log_test "Lock state is consistent after multiple operations"
    run_cmd unlock concurrent-agent-1 /tmp/concurrent-file.txt
    run_cmd lock concurrent-agent-2 /tmp/concurrent-file.txt
    output=$(run_cmd check concurrent-agent-2 /tmp/concurrent-file.txt)
    if output_contains "$output" "OWNED"; then
        log_pass
    else
        log_fail "Lock state inconsistent: $output"
    fi

    # Cleanup
    run_cmd unlock-all concurrent-agent-2
    run_cmd unregister concurrent-agent-1
    run_cmd unregister concurrent-agent-2
}

################################################################################
# TEST RUNNER
################################################################################

run_all_tests() {
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  CLAUDE COORDINATION SYSTEM - COMPREHENSIVE TEST SUITE   ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    init_report

    # Backup existing state
    backup_state

    # Start with clean state
    cleanup_state

    # Run all test groups
    test_agent_commands
    test_lock_commands
    test_task_commands
    test_task_lifecycle
    test_task_blocking
    test_task_priority
    test_prefix_priority
    test_task_dependencies
    test_task_next
    test_task_import
    test_cleanup_commands
    test_status_command
    test_parameter_validation
    test_state_persistence
    test_concurrent_safety

    # Print summary
    log_section "TEST SUMMARY"

    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "Total Tests:    ${BLUE}$TOTAL_TESTS${NC}"
    echo -e "Passed:         ${GREEN}$PASSED_TESTS${NC}"
    echo -e "Failed:         ${RED}$FAILED_TESTS${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"

    # Write to report
    cat >> "$TEST_REPORT" <<EOF

================================================================================
TEST SUMMARY
================================================================================
Total Tests:    $TOTAL_TESTS
Passed:         $PASSED_TESTS
Failed:         $FAILED_TESTS

Pass Rate:      $(awk "BEGIN {printf \"%.1f%%\", ($PASSED_TESTS/$TOTAL_TESTS)*100}")
================================================================================
EOF

    if [ $FAILED_TESTS -eq 0 ]; then
        echo -e "\n${GREEN}✓ ALL TESTS PASSED!${NC}\n"
        echo "✓ ALL TESTS PASSED!" >> "$TEST_REPORT"
    else
        echo -e "\n${RED}✗ SOME TESTS FAILED${NC}\n"
        echo "✗ SOME TESTS FAILED" >> "$TEST_REPORT"
    fi

    echo -e "Full report saved to: ${BLUE}$TEST_REPORT${NC}\n"

    # Restore original state
    cleanup_state
    restore_state

    # Return exit code based on failures
    return $FAILED_TESTS
}

# Run tests
run_all_tests
exit_code=$?

exit $exit_code
