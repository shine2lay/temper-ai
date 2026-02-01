#!/bin/bash
# Example: Using dependencies to coordinate a multi-phase project

set -e

echo "=== Example: Building an Authentication System ==="
echo "This example shows how to use dependencies to coordinate complex projects"
echo

# Phase 1: Foundation
echo "Phase 1: Creating foundation tasks..."
.claude-coord/bin/coord task-create test-med-auth-base-1 \
    "Setup database schema" \
    "Create users, sessions, and roles tables" \
    --priority 3

echo "✓ Created foundation task"
echo

# Phase 2: Core features (depend on foundation)
echo "Phase 2: Creating core feature tasks (depend on Phase 1)..."
.claude-coord/bin/coord task-create test-med-auth-oauth-1 \
    "Implement OAuth providers" \
    "Add Google and GitHub OAuth" \
    --priority 3 \
    --depends-on test-med-auth-base-1

.claude-coord/bin/coord task-create test-med-auth-jwt-1 \
    "Add JWT token generation" \
    "Create and validate JWT tokens" \
    --priority 3 \
    --depends-on test-med-auth-base-1

echo "✓ Created 2 core features (can be done in parallel after Phase 1)"
echo

# Phase 3: Integration (depends on all core features)
echo "Phase 3: Creating integration task (depends on Phase 2)..."
.claude-coord/bin/coord task-create test-med-auth-middleware-1 \
    "Create auth middleware" \
    "Protect routes with authentication" \
    --priority 3 \
    --depends-on "test-med-auth-oauth-1,test-med-auth-jwt-1"

echo "✓ Created integration task"
echo

# Phase 4: Testing (depends on integration)
echo "Phase 4: Creating test task (depends on Phase 3)..."
.claude-coord/bin/coord task-create test-med-auth-test-1 \
    "Write integration tests" \
    "Test full auth flow end-to-end" \
    --priority 3 \
    --depends-on test-med-auth-middleware-1

echo "✓ Created test task"
echo

# Show the task graph
echo "=== Task Dependency Graph ==="
echo
echo "test-med-auth-base-1 (Setup database)"
echo "  └─> test-med-auth-oauth-1 (OAuth providers)"
echo "  └─> test-med-auth-jwt-1 (JWT tokens)"
echo "        └─> test-med-auth-middleware-1 (Auth middleware)"
echo "              └─> test-med-auth-test-1 (Integration tests)"
echo

# Show available vs blocked tasks
echo "=== Current Task Status ==="
echo
.claude-coord/bin/coord task-list --all
echo

# Show details of integration task
echo "=== Integration Task Details ==="
.claude-coord/bin/coord task-get test-med-auth-middleware-1
echo

echo "=== Workflow Explanation ==="
echo
echo "1. Only test-med-auth-base-1 is available initially"
echo "2. After completing base-1, OAuth and JWT become available in parallel"
echo "3. After completing both OAuth and JWT, middleware becomes available"
echo "4. After completing middleware, tests become available"
echo
echo "This ensures proper build order while allowing parallelism where possible."
