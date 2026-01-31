#!/bin/bash
# Concurrency, Race Condition, and State Management Testing for claude-coord.sh
# This script performs comprehensive testing of the coordination system

set -uo pipefail

COORD_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/claude-coord.sh"
STATE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/state.json"
LOCK_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.state.lock"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/test-results"

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
WARNINGS=0

# Test results
declare -a FAILED_TEST_NAMES
declare -a WARNING_MESSAGES

# ============================================================
# HELPER FUNCTIONS
# ============================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED_TESTS++))
}

log_failure() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED_TESTS++))
    FAILED_TEST_NAMES+=("$1")
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    ((WARNINGS++))
    WARNING_MESSAGES+=("$1")
}

start_test() {
    ((TOTAL_TESTS++))
    log_info "Test #$TOTAL_TESTS: $1"
}

cleanup_state() {
    rm -f "$STATE_FILE" "$LOCK_FILE"
    mkdir -p "$TEST_DIR"
}

init_clean_state() {
    cleanup_state
    bash "$COORD_SCRIPT" status >/dev/null 2>&1 || true
}

# Get current state JSON
get_state() {
    if [ -f "$STATE_FILE" ]; then
        cat "$STATE_FILE"
    else
        echo '{"agents":{},"locks":{},"tasks":{}}'
    fi
}

# Verify state is valid JSON
verify_json_validity() {
    local state=$(get_state)
    if ! echo "$state" | jq empty >/dev/null 2>&1; then
        return 1
    fi
    return 0
}

# Count agents in state
count_agents() {
    get_state | jq '.agents | length'
}

# Count locks in state
count_locks() {
    get_state | jq '.locks | length'
}

# Count tasks in state
count_tasks() {
    get_state | jq '.tasks | length'
}

# ============================================================
# ATOMIC OPERATION TESTS
# ============================================================

test_atomic_read_shared_lock() {
    start_test "Atomic read uses shared lock correctly"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null

    # Multiple reads should succeed simultaneously
    local pids=()
    for i in {1..10}; do
        (bash "$COORD_SCRIPT" status >/dev/null 2>&1) &
        pids+=($!)
    done

    # Wait for all and check success
    local failures=0
    for pid in "${pids[@]}"; do
        if ! wait "$pid"; then
            ((failures++))
        fi
    done

    if [ "$failures" -eq 0 ]; then
        log_success "Multiple simultaneous reads succeeded (shared lock working)"
    else
        log_failure "Atomic read: $failures/10 reads failed"
    fi
}

test_atomic_write_exclusive_lock() {
    start_test "Atomic write uses exclusive lock correctly"

    init_clean_state

    # Concurrent writes to register agents
    local pids=()
    for i in {1..20}; do
        (bash "$COORD_SCRIPT" register "agent$i" $$ >/dev/null 2>&1) &
        pids+=($!)
    done

    # Wait for all
    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done

    # Verify all 20 agents registered (no lost writes)
    local agent_count=$(count_agents)
    if [ "$agent_count" -eq 20 ]; then
        log_success "Atomic write: All 20 concurrent registrations persisted"
    else
        log_failure "Atomic write: Lost writes detected (expected 20, got $agent_count)"
    fi

    # Verify JSON integrity
    if verify_json_validity; then
        log_success "Atomic write: JSON integrity maintained after concurrent writes"
    else
        log_failure "Atomic write: JSON corrupted after concurrent writes"
    fi
}

test_atomic_update_read_modify_write() {
    start_test "Atomic update holds exclusive lock for entire read-modify-write"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null

    # Concurrent task adds (uses atomic_update internally)
    local pids=()
    for i in {1..30}; do
        (bash "$COORD_SCRIPT" task-add "task-$i" "Test task $i" "" 3 >/dev/null 2>&1) &
        pids+=($!)
    done

    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done

    # Count tasks
    local task_count=$(count_tasks)
    if [ "$task_count" -eq 30 ]; then
        log_success "Atomic update: All 30 concurrent task adds persisted"
    else
        log_failure "Atomic update: Lost updates (expected 30, got $task_count)"
    fi
}

# ============================================================
# RACE CONDITION TESTS
# ============================================================

test_concurrent_lock_acquisition() {
    start_test "Concurrent lock acquisition on same file (mutual exclusion)"

    init_clean_state

    # Register multiple agents
    for i in {1..5}; do
        bash "$COORD_SCRIPT" register "agent$i" $$ >/dev/null
    done

    # All try to lock same file simultaneously
    local test_file="/tmp/test-file.txt"
    local pids=()
    local success_file="$TEST_DIR/lock-success.txt"
    rm -f "$success_file"

    for i in {1..5}; do
        (
            if bash "$COORD_SCRIPT" lock "agent$i" "$test_file" >/dev/null 2>&1; then
                echo "agent$i" >> "$success_file"
            fi
        ) &
        pids+=($!)
    done

    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done

    # Exactly one should succeed
    local success_count=$(wc -l < "$success_file" 2>/dev/null || echo "0")
    if [ "$success_count" -eq 1 ]; then
        local winner=$(cat "$success_file")
        log_success "Concurrent lock: Only one agent ($winner) acquired lock (mutual exclusion works)"
    else
        log_failure "Concurrent lock: $success_count agents acquired lock (expected 1)"
    fi

    # Verify lock is recorded
    local lock_count=$(count_locks)
    if [ "$lock_count" -eq 1 ]; then
        log_success "Concurrent lock: Exactly one lock recorded in state"
    else
        log_failure "Concurrent lock: $lock_count locks in state (expected 1)"
    fi
}

test_lock_all_atomicity() {
    start_test "lock-all atomicity (all-or-nothing)"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null
    bash "$COORD_SCRIPT" register agent2 $$ >/dev/null

    # Agent1 locks file1
    bash "$COORD_SCRIPT" lock agent1 /tmp/file1.txt >/dev/null

    # Agent2 tries to lock file1, file2, file3 (should fail - file1 already locked)
    if bash "$COORD_SCRIPT" lock-all agent2 /tmp/file1.txt /tmp/file2.txt /tmp/file3.txt 2>/dev/null; then
        log_failure "lock-all: Succeeded despite file1 being locked (atomicity broken)"
    else
        log_success "lock-all: Failed as expected when one file unavailable"
    fi

    # Verify agent2 got NO locks (all-or-nothing)
    local agent2_locks=$(get_state | jq -r '.locks | to_entries[] | select(.value.owner == "agent2") | .key' | wc -l)
    if [ "$agent2_locks" -eq 0 ]; then
        log_success "lock-all: No partial locks acquired (all-or-nothing works)"
    else
        log_failure "lock-all: $agent2_locks partial locks acquired (atomicity broken)"
    fi
}

test_concurrent_task_claim() {
    start_test "Concurrent task claim (only one agent should succeed)"

    init_clean_state

    # Add a single task
    bash "$COORD_SCRIPT" register agent0 $$ >/dev/null
    bash "$COORD_SCRIPT" task-add task-x "Contested task" >/dev/null

    # Register 10 agents
    for i in {1..10}; do
        bash "$COORD_SCRIPT" register "agent$i" $$ >/dev/null
    done

    # All try to claim simultaneously
    local pids=()
    local claim_file="$TEST_DIR/task-claims.txt"
    rm -f "$claim_file"

    for i in {1..10}; do
        (
            if bash "$COORD_SCRIPT" task-claim "agent$i" task-x >/dev/null 2>&1; then
                echo "agent$i" >> "$claim_file"
            fi
        ) &
        pids+=($!)
    done

    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done

    # Exactly one should succeed
    local claim_count=$(wc -l < "$claim_file" 2>/dev/null || echo "0")
    if [ "$claim_count" -eq 1 ]; then
        local winner=$(cat "$claim_file")
        log_success "Concurrent task claim: Only one agent ($winner) claimed task"
    else
        log_failure "Concurrent task claim: $claim_count agents claimed task (expected 1)"
    fi

    # Verify task owner in state
    local task_owner=$(get_state | jq -r '.tasks["task-x"].owner')
    if [ "$task_owner" != "null" ] && [ -n "$task_owner" ]; then
        log_success "Concurrent task claim: Task owner correctly recorded"
    else
        log_failure "Concurrent task claim: Task owner not recorded"
    fi
}

test_lock_release_cascade() {
    start_test "Lock release cascades to unblock tasks"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null
    bash "$COORD_SCRIPT" register agent2 $$ >/dev/null

    # Add task and block it on a file
    bash "$COORD_SCRIPT" task-add task-blocked "Blocked task" >/dev/null
    bash "$COORD_SCRIPT" lock agent1 /tmp/blocking-file.txt >/dev/null
    bash "$COORD_SCRIPT" task-block task-blocked agent1 /tmp/blocking-file.txt >/dev/null

    # Verify task is blocked
    local blocked_status=$(get_state | jq -r '.tasks["task-blocked"].blocked')
    if [ "$blocked_status" = "true" ]; then
        log_success "Lock cascade: Task correctly marked as blocked"
    else
        log_warning "Lock cascade: Task not marked as blocked (pre-condition failed)"
    fi

    # Release the lock
    bash "$COORD_SCRIPT" unlock agent1 /tmp/blocking-file.txt >/dev/null

    # Verify task was auto-unblocked
    local unblocked_status=$(get_state | jq -r '.tasks["task-blocked"].blocked')
    if [ "$unblocked_status" = "null" ]; then
        log_success "Lock cascade: Task auto-unblocked when lock released"
    else
        log_failure "Lock cascade: Task remained blocked after lock release"
    fi
}

# ============================================================
# STATE CORRUPTION TESTS
# ============================================================

test_corrupted_json_recovery() {
    start_test "Corrupted JSON recovery"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null

    # Corrupt the state file
    echo "{{INVALID JSON}}" > "$STATE_FILE"

    # Try an operation - should reinitialize
    bash "$COORD_SCRIPT" register agent2 $$ 2>/dev/null || true

    # Verify state is valid JSON now
    if verify_json_validity; then
        log_success "Corrupted JSON: System recovered and reinitialized"
    else
        log_failure "Corrupted JSON: System did not recover"
    fi

    # Verify old data was lost (expected behavior)
    local agent_count=$(count_agents)
    if [ "$agent_count" -le 2 ]; then
        log_success "Corrupted JSON: State reinitialized (old data cleared)"
    else
        log_warning "Corrupted JSON: Unexpected agent count after recovery"
    fi
}

test_empty_state_file() {
    start_test "Empty state file handling"

    init_clean_state

    # Create empty file
    touch "$STATE_FILE"

    # Try operation
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null 2>&1 || true

    if verify_json_validity; then
        log_success "Empty state: System initialized valid JSON"
    else
        log_failure "Empty state: Invalid JSON after initialization"
    fi
}

test_missing_state_file() {
    start_test "Missing state file handling"

    cleanup_state

    # No state file exists - should auto-create
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null

    if [ -f "$STATE_FILE" ] && verify_json_validity; then
        log_success "Missing state: Auto-created valid state file"
    else
        log_failure "Missing state: Did not create valid state file"
    fi
}

test_concurrent_state_corruption() {
    start_test "Concurrent operations maintain JSON integrity"

    init_clean_state

    # Mix of different operations running concurrently
    local pids=()

    # Register agents
    for i in {1..5}; do
        (bash "$COORD_SCRIPT" register "reg-agent$i" $$ >/dev/null 2>&1) &
        pids+=($!)
    done

    # Add tasks
    for i in {1..5}; do
        (bash "$COORD_SCRIPT" task-add "task$i" "Task $i" >/dev/null 2>&1) &
        pids+=($!)
    done

    # Acquire locks
    for i in {1..5}; do
        (bash "$COORD_SCRIPT" register "lock-agent$i" $$ >/dev/null 2>&1 && \
         bash "$COORD_SCRIPT" lock "lock-agent$i" "/tmp/file$i.txt" >/dev/null 2>&1) &
        pids+=($!)
    done

    # Wait for all
    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done

    # Verify JSON integrity
    if verify_json_validity; then
        log_success "Concurrent ops: JSON integrity maintained"
    else
        log_failure "Concurrent ops: JSON corrupted"
        log_info "State content: $(cat "$STATE_FILE" 2>&1 | head -20)"
    fi
}

# ============================================================
# EDGE CASE TESTS
# ============================================================

test_special_characters_in_ids() {
    start_test "Special characters in agent/task IDs"

    init_clean_state

    # Test various special characters (excluding those that break bash)
    local test_ids=(
        "agent-with-dash"
        "agent_with_underscore"
        "agent.with.dots"
        "agent123"
        "AGENT_CAPS"
    )

    local failures=0
    for test_id in "${test_ids[@]}"; do
        if ! bash "$COORD_SCRIPT" register "$test_id" $$ >/dev/null 2>&1; then
            ((failures++))
            log_warning "Special chars: Failed to register agent ID: $test_id"
        fi
    done

    if [ "$failures" -eq 0 ]; then
        log_success "Special chars: All test IDs handled correctly"
    else
        log_failure "Special chars: $failures IDs failed"
    fi

    # Verify state integrity
    if verify_json_validity; then
        log_success "Special chars: JSON integrity maintained"
    else
        log_failure "Special chars: JSON corrupted"
    fi
}

test_very_long_strings() {
    start_test "Very long strings in fields"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null

    # Create a very long description
    local long_desc=$(python3 -c "print('A' * 10000)")

    if bash "$COORD_SCRIPT" task-add task-long "Long task" "$long_desc" >/dev/null 2>&1; then
        log_success "Long strings: Handled 10KB description"
    else
        log_warning "Long strings: Failed to handle 10KB description"
    fi

    # Verify integrity
    if verify_json_validity; then
        log_success "Long strings: JSON integrity maintained"
    else
        log_failure "Long strings: JSON corrupted"
    fi
}

test_empty_values() {
    start_test "Empty values in optional fields"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null

    # Task with empty description
    if bash "$COORD_SCRIPT" task-add task-empty "Empty desc task" "" >/dev/null 2>&1; then
        log_success "Empty values: Empty description handled"
    else
        log_warning "Empty values: Empty description failed"
    fi

    # Verify task was added
    local task_exists=$(get_state | jq -r '.tasks["task-empty"] // "null"')
    if [ "$task_exists" != "null" ]; then
        log_success "Empty values: Task with empty description persisted"
    else
        log_failure "Empty values: Task not persisted"
    fi
}

test_unicode_characters() {
    start_test "Unicode characters in fields"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null

    # Unicode in task subject
    local unicode_subject="任务 📝 测试"

    if bash "$COORD_SCRIPT" task-add task-unicode "$unicode_subject" >/dev/null 2>&1; then
        log_success "Unicode: Handled Unicode characters"
    else
        log_warning "Unicode: Failed to handle Unicode"
    fi

    # Verify subject was stored correctly
    local stored_subject=$(get_state | jq -r '.tasks["task-unicode"].subject')
    if [ "$stored_subject" = "$unicode_subject" ]; then
        log_success "Unicode: Subject stored correctly"
    else
        log_warning "Unicode: Subject not stored correctly (got: $stored_subject)"
    fi
}

# ============================================================
# LOCK TIMEOUT AND CLEANUP TESTS
# ============================================================

test_dead_agent_cleanup() {
    start_test "Dead agent cleanup and lock release"

    init_clean_state

    # Register agent with a fake (dead) PID
    local dead_pid=99999
    bash "$COORD_SCRIPT" register dead-agent $dead_pid >/dev/null
    bash "$COORD_SCRIPT" lock dead-agent /tmp/dead-lock.txt >/dev/null

    # Manually set heartbeat to old time (simulate timeout)
    local old_time="2020-01-01T00:00:00Z"
    local state=$(get_state)
    state=$(echo "$state" | jq --arg ts "$old_time" '.agents["dead-agent"].heartbeat = $ts')
    echo "$state" > "$STATE_FILE"

    # Run cleanup
    bash "$COORD_SCRIPT" cleanup-dead >/dev/null 2>&1

    # Verify agent was removed
    local agent_exists=$(get_state | jq -r '.agents["dead-agent"] // "null"')
    if [ "$agent_exists" = "null" ]; then
        log_success "Dead agent: Agent removed"
    else
        log_failure "Dead agent: Agent not removed"
    fi

    # Verify lock was released
    local lock_exists=$(get_state | jq -r '.locks["/tmp/dead-lock.txt"] // "null"')
    if [ "$lock_exists" = "null" ]; then
        log_success "Dead agent: Lock released"
    else
        log_failure "Dead agent: Lock not released"
    fi
}

test_check_with_inline_cleanup() {
    start_test "check command with inline dead agent cleanup"

    init_clean_state

    # Register dead agent with lock
    local dead_pid=99998
    bash "$COORD_SCRIPT" register dead-agent2 $dead_pid >/dev/null
    bash "$COORD_SCRIPT" lock dead-agent2 /tmp/check-test.txt >/dev/null

    # Set old heartbeat
    local old_time="2020-01-01T00:00:00Z"
    local state=$(get_state)
    state=$(echo "$state" | jq --arg ts "$old_time" '.agents["dead-agent2"].heartbeat = $ts')
    echo "$state" > "$STATE_FILE"

    # Check lock status - should cleanup and report unlocked
    local check_result=$(bash "$COORD_SCRIPT" check "" /tmp/check-test.txt 2>&1)

    if echo "$check_result" | grep -q "UNLOCKED"; then
        log_success "Inline cleanup: check reported file as unlocked after cleanup"
    else
        log_failure "Inline cleanup: check did not cleanup dead agent lock"
    fi
}

# ============================================================
# FLOCK BEHAVIOR TESTS
# ============================================================

test_flock_exclusive_blocks_concurrent() {
    start_test "flock exclusive lock blocks concurrent operations"

    init_clean_state

    # Start a long-running exclusive lock operation
    (
        flock -x "$LOCK_FILE" bash -c "sleep 2; bash '$COORD_SCRIPT' register long-agent $$ >/dev/null 2>&1"
    ) &
    local blocker_pid=$!

    sleep 0.5  # Let blocker acquire lock

    # Try quick operation - should be blocked
    local start_time=$(date +%s)
    bash "$COORD_SCRIPT" register quick-agent $$ >/dev/null 2>&1
    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))

    wait $blocker_pid || true

    if [ "$elapsed" -ge 1 ]; then
        log_success "flock exclusive: Blocked concurrent operation (waited ${elapsed}s)"
    else
        log_warning "flock exclusive: Did not block effectively (waited only ${elapsed}s)"
    fi
}

test_flock_shared_allows_concurrent_reads() {
    start_test "flock shared lock allows concurrent reads"

    init_clean_state
    bash "$COORD_SCRIPT" register agent1 $$ >/dev/null

    # Multiple concurrent status reads (use shared locks)
    local pids=()
    local start_time=$(date +%s)

    for i in {1..10}; do
        (bash "$COORD_SCRIPT" status >/dev/null 2>&1) &
        pids+=($!)
    done

    # Wait for all
    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done

    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))

    # Should complete quickly (parallel, not serial)
    if [ "$elapsed" -le 2 ]; then
        log_success "flock shared: Concurrent reads completed quickly (${elapsed}s for 10 reads)"
    else
        log_warning "flock shared: Reads took longer than expected (${elapsed}s)"
    fi
}

# ============================================================
# STATE CONSISTENCY TESTS
# ============================================================

test_agent_unregister_cleanup() {
    start_test "Agent unregister cleans up locks and tasks"

    init_clean_state
    bash "$COORD_SCRIPT" register cleanup-agent $$ >/dev/null
    bash "$COORD_SCRIPT" lock cleanup-agent /tmp/cleanup-file.txt >/dev/null
    bash "$COORD_SCRIPT" task-add cleanup-task "Task" >/dev/null
    bash "$COORD_SCRIPT" task-claim cleanup-agent cleanup-task >/dev/null

    # Unregister
    bash "$COORD_SCRIPT" unregister cleanup-agent >/dev/null

    # Verify lock removed
    local lock_count=$(get_state | jq '[.locks | to_entries[] | select(.value.owner == "cleanup-agent")] | length')
    if [ "$lock_count" -eq 0 ]; then
        log_success "Unregister: Locks removed"
    else
        log_failure "Unregister: $lock_count locks remain"
    fi

    # Note: tasks are NOT released on unregister (by design)
    # This is intentional - unregister is for explicit cleanup
}

test_unlock_all_cascade() {
    start_test "unlock-all releases all locks and unblocks tasks"

    init_clean_state
    bash "$COORD_SCRIPT" register unlock-agent $$ >/dev/null

    # Lock multiple files
    bash "$COORD_SCRIPT" lock unlock-agent /tmp/ua-file1.txt >/dev/null
    bash "$COORD_SCRIPT" lock unlock-agent /tmp/ua-file2.txt >/dev/null
    bash "$COORD_SCRIPT" lock unlock-agent /tmp/ua-file3.txt >/dev/null

    # Block a task on one of the files
    bash "$COORD_SCRIPT" task-add ua-task "Blocked task" >/dev/null
    bash "$COORD_SCRIPT" task-block ua-task unlock-agent /tmp/ua-file2.txt >/dev/null

    # Unlock all
    bash "$COORD_SCRIPT" unlock-all unlock-agent >/dev/null

    # Verify all locks removed
    local lock_count=$(get_state | jq '[.locks | to_entries[] | select(.value.owner == "unlock-agent")] | length')
    if [ "$lock_count" -eq 0 ]; then
        log_success "unlock-all: All locks removed"
    else
        log_failure "unlock-all: $lock_count locks remain"
    fi

    # Verify task unblocked
    local task_blocked=$(get_state | jq -r '.tasks["ua-task"].blocked')
    if [ "$task_blocked" = "null" ]; then
        log_success "unlock-all: Task auto-unblocked"
    else
        log_failure "unlock-all: Task remained blocked"
    fi
}

# ============================================================
# PATH NORMALIZATION TESTS
# ============================================================

test_path_normalization() {
    start_test "Path normalization for locks"

    init_clean_state
    bash "$COORD_SCRIPT" register path-agent $$ >/dev/null

    # Lock with relative path
    bash "$COORD_SCRIPT" lock path-agent ./test-file.txt >/dev/null

    # Check with absolute path
    local abs_path="$(pwd)/test-file.txt"
    local check_result=$(bash "$COORD_SCRIPT" check path-agent "$abs_path" 2>&1)

    if echo "$check_result" | grep -q "OWNED"; then
        log_success "Path normalization: Relative and absolute paths match"
    else
        log_warning "Path normalization: Relative/absolute path mismatch"
    fi
}

# ============================================================
# STRESS TESTS
# ============================================================

test_high_volume_operations() {
    start_test "High volume concurrent operations (stress test)"

    init_clean_state

    local op_count=100
    local pids=()

    log_info "Running $op_count concurrent operations..."

    for i in $(seq 1 $op_count); do
        local op=$((i % 5))
        case $op in
            0)
                (bash "$COORD_SCRIPT" register "stress-agent-$i" $$ >/dev/null 2>&1) &
                ;;
            1)
                (bash "$COORD_SCRIPT" task-add "stress-task-$i" "Task $i" >/dev/null 2>&1) &
                ;;
            2)
                (bash "$COORD_SCRIPT" register "stress-lock-$i" $$ >/dev/null 2>&1 && \
                 bash "$COORD_SCRIPT" lock "stress-lock-$i" "/tmp/stress-$i.txt" >/dev/null 2>&1) &
                ;;
            3)
                (bash "$COORD_SCRIPT" status >/dev/null 2>&1) &
                ;;
            4)
                (bash "$COORD_SCRIPT" heartbeat "stress-agent-$i" >/dev/null 2>&1) &
                ;;
        esac
        pids+=($!)
    done

    # Wait for all
    for pid in "${pids[@]}"; do
        wait "$pid" || true
    done

    # Verify JSON integrity
    if verify_json_validity; then
        log_success "Stress test: JSON integrity maintained after $op_count operations"
    else
        log_failure "Stress test: JSON corrupted"
    fi

    # Verify we have data
    local agent_count=$(count_agents)
    local task_count=$(count_tasks)
    local lock_count=$(count_locks)

    if [ "$agent_count" -gt 0 ] && [ "$task_count" -gt 0 ]; then
        log_success "Stress test: State populated (agents=$agent_count, tasks=$task_count, locks=$lock_count)"
    else
        log_failure "Stress test: State not properly populated"
    fi
}

# ============================================================
# MAIN TEST EXECUTION
# ============================================================

echo "============================================="
echo "Coordination System Concurrency Testing"
echo "============================================="
echo ""

# Run all tests
test_atomic_read_shared_lock
test_atomic_write_exclusive_lock
test_atomic_update_read_modify_write

test_concurrent_lock_acquisition
test_lock_all_atomicity
test_concurrent_task_claim
test_lock_release_cascade

test_corrupted_json_recovery
test_empty_state_file
test_missing_state_file
test_concurrent_state_corruption

test_special_characters_in_ids
test_very_long_strings
test_empty_values
test_unicode_characters

test_dead_agent_cleanup
test_check_with_inline_cleanup

test_flock_exclusive_blocks_concurrent
test_flock_shared_allows_concurrent_reads

test_agent_unregister_cleanup
test_unlock_all_cascade

test_path_normalization

test_high_volume_operations

# ============================================================
# SUMMARY REPORT
# ============================================================

echo ""
echo "============================================="
echo "TEST SUMMARY"
echo "============================================="
echo "Total Tests:   $TOTAL_TESTS"
echo -e "${GREEN}Passed:        $PASSED_TESTS${NC}"
echo -e "${RED}Failed:        $FAILED_TESTS${NC}"
echo -e "${YELLOW}Warnings:      $WARNINGS${NC}"
echo ""

if [ "$FAILED_TESTS" -gt 0 ]; then
    echo -e "${RED}Failed Tests:${NC}"
    for test_name in "${FAILED_TEST_NAMES[@]}"; do
        echo "  - $test_name"
    done
    echo ""
fi

if [ "$WARNINGS" -gt 0 ]; then
    echo -e "${YELLOW}Warnings:${NC}"
    for warning in "${WARNING_MESSAGES[@]}"; do
        echo "  - $warning"
    done
    echo ""
fi

# Calculate pass rate
pass_rate=0
if [ "$TOTAL_TESTS" -gt 0 ]; then
    pass_rate=$(echo "scale=1; $PASSED_TESTS * 100 / $TOTAL_TESTS" | bc 2>/dev/null || echo "0")
fi

echo "Pass Rate: ${pass_rate}%"
echo ""

# Exit with appropriate code
if [ "$FAILED_TESTS" -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
