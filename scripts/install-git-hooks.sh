#!/bin/bash
# Install the tracked pre-commit hook by pointing git at scripts/git-hooks.
# Run once after cloning.
#
# What this does:
#   git config core.hooksPath scripts/git-hooks
#
# After running this, every `git commit` will execute
# scripts/git-hooks/pre-commit, which mirrors the checks that CI runs
# (.github/workflows/ci.yml). This catches lint/type/test failures locally
# before they fail the PR.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

HOOKS_DIR="scripts/git-hooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "ERROR: $HOOKS_DIR not found. Run this from the repo root."
    exit 1
fi

# Make all hooks executable (in case perms were lost through copy/clone)
chmod +x "$HOOKS_DIR"/* 2>/dev/null || true

# Point git at the tracked hooks directory
git config core.hooksPath "$HOOKS_DIR"

echo "✓ Git hooks installed. core.hooksPath = $HOOKS_DIR"
echo ""
echo "The pre-commit hook now runs the same checks as CI:"
echo "  - ruff check   (staged Python files)"
echo "  - mypy         (staged temper_ai/ files)"
echo "  - pytest       (full suite; --ignore=tests/test_database)"
echo ""
echo "Bypass for a single commit:  git commit --no-verify"
echo "Include database tests:      PRECOMMIT_RUN_DB=1 git commit"
