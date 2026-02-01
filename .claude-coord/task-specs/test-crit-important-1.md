# Task Specification: test-crit-important-1

## Problem Statement

This is a test task to verify that critical priority tasks properly require spec files and cannot be bypassed.

## Acceptance Criteria

- Task can be created with proper spec file
- Priority is auto-derived from 'crit' category as 0
- Cannot bypass with --priority flag

## Test Strategy

1. Create task with crit category
2. Verify it requires spec file
3. Verify priority is auto-set to 0
4. Attempt to bypass with --priority 2 and verify it fails
