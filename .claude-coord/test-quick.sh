#!/bin/bash
# Quick concurrency tests

COORD="./.claude-coord/claude-coord.sh"
STATE="./.claude-coord/state.json"

cleanup() {
    rm -f "$STATE" ./.claude-coord/.state.lock
}

# Test 1: Concurrent registrations
cleanup
bash "$COORD" status >/dev/null 2>&1

for i in {1..20}; do
    bash "$COORD" register "agent$i" $$ >/dev/null 2>&1 &
done
wait

count=$(cat "$STATE" 2>/dev/null | jq '.agents | length' 2>/dev/null || echo "0")
echo "Test 1 - Concurrent registrations: $count/20 agents"

# Test 2: Mutual exclusion
cleanup
for i in {1..5}; do bash "$COORD" register "agent$i" $$ >/dev/null; done

success=0
for i in {1..5}; do
    (bash "$COORD" lock "agent$i" "/tmp/contested.txt" >/dev/null 2>&1 && ((success++))) &
done
wait

locks=$(cat "$STATE" 2>/dev/null | jq '.locks | length' 2>/dev/null || echo "0")
echo "Test 2 - Mutual exclusion: $locks lock(s) acquired"

# Test 3: Concurrent task claims
cleanup
bash "$COORD" register agent0 $$ >/dev/null
bash "$COORD" task-add task-x "Test" >/dev/null

for i in {1..10}; do bash "$COORD" register "agent$i" $$ >/dev/null; done

claims=0
for i in {1..10}; do
    (bash "$COORD" task-claim "agent$i" task-x >/dev/null 2>&1 && ((claims++))) &
done
wait

owner=$(cat "$STATE" 2>/dev/null | jq -r '.tasks["task-x"].owner' 2>/dev/null || echo "null")
echo "Test 3 - Task claim atomicity: owner=$owner"

# Test 4: JSON integrity after concurrent ops
cleanup
for i in {1..30}; do
    bash "$COORD" task-add "task-$i" "Task $i" >/dev/null 2>&1 &
done
wait

valid=$(cat "$STATE" 2>/dev/null | jq empty 2>&1 && echo "valid" || echo "invalid")
tasks=$(cat "$STATE" 2>/dev/null | jq '.tasks | length' 2>/dev/null || echo "0")
echo "Test 4 - Concurrent task adds: $tasks tasks, JSON $valid"

echo ""
echo "All tests complete"
