# Coordination Service Test Suite Audit

**Date:** 2026-01-31
**Scope:** `.claude-coord/coord_service/` only
**Current Coverage:** 56% (4/9 source files have tests)
**Target:** 95%+ coverage

---

## Executive Summary

The coordination daemon has **good test coverage** for its core components (database, validator, protocol) but **critical gaps** in supporting infrastructure:

### ✅ Well-Tested (56% of code)
- **database.py** (20K LOC) → 80 tests ✅ (just improved!)
- **validator.py** (16K LOC) → 52 tests ✅
- **protocol.py** (2.5K LOC) → 22 tests ✅
- **daemon.py** (5.9K LOC) → 6 tests ⚠️ (minimal)

### ❌ Zero Coverage (44% of code)
- **background.py** (9.2K LOC, 9 methods) → **0 tests** ❌
- **client.py** (12K LOC, 2 methods) → **0 tests** ❌
- **operations.py** (11K LOC, 19 methods) → **0 tests** ❌
- **server.py** (5.3K LOC, 5 methods) → **0 tests** ❌

**Impact:** ~37K LOC (44%) untested, **critical infrastructure exposed**

---

## Critical Gaps (P0 - Must Fix)

### 1. background.py - 0% Coverage (P0 - HIGH RISK)

**File:** 277 LOC, 9 methods
**Risk:** Background task failures, resource leaks, dead agent accumulation

**What It Does:**
- **Dead agent cleanup** (every 60s) - Removes stale agents
- **Metrics aggregation** (every 60s) - Aggregates performance data
- **State export** (every 300s) - Backward compatibility JSON export
- **Database backup** (every 3600s) - Periodic backups

**Missing Tests (~40 tests, 500 LOC):**

```python
# tests/test_background.py (NEW FILE NEEDED)

class TestBackgroundTaskLifecycle:
    def test_start_initializes_all_threads(self)
        """All 4 background threads should start."""

    def test_stop_terminates_all_threads(self)
        """Cleanup on stop."""

    def test_stop_timeout_doesnt_hang(self)
        """Stop returns even if threads don't respond."""

class TestDeadAgentCleanup:
    def test_cleanup_removes_stale_agents(self)
        """Agents with no heartbeat in 5min removed."""

    def test_cleanup_releases_claimed_tasks(self)
        """Dead agent's tasks released back to pending."""

    def test_cleanup_releases_file_locks(self)
        """Dead agent's locks released."""

    def test_cleanup_preserves_recent_agents(self)
        """Agents with recent heartbeat not removed."""

    def test_cleanup_handles_database_errors(self)
        """DB error doesn't crash background task."""

class TestMetricsAggregation:
    def test_aggregation_calculates_velocity(self)
        """Velocity metrics calculated correctly."""

    def test_aggregation_identifies_hotspots(self)
        """File hotspots identified."""

    def test_aggregation_tracks_task_timing(self)
        """Task timing statistics tracked."""

    def test_aggregation_handles_empty_data(self)
        """Graceful handling of no data."""

class TestStateExport:
    def test_export_creates_json_file(self)
        """state.json file created."""

    def test_export_preserves_data_integrity(self)
        """Exported data matches DB state."""

    def test_export_handles_disk_full(self)
        """Disk full doesn't corrupt export."""

    def test_export_atomic_write(self)
        """Write is atomic (no partial files)."""

class TestDatabaseBackup:
    def test_backup_creates_file(self)
        """Backup file created successfully."""

    def test_backup_preserves_data(self)
        """Backup can be restored."""

    def test_backup_handles_missing_backup_dir(self)
        """Missing directory doesn't crash task."""

    def test_backup_rotation(self)
        """Old backups cleaned up."""

class TestPeriodicExecution:
    def test_task_runs_at_interval(self)
        """Task executes at specified interval."""

    def test_task_exception_doesnt_stop_loop(self)
        """Exception in task doesn't stop periodic execution."""

    def test_fast_shutdown_on_stop(self)
        """Shutdown doesn't wait full interval."""

class TestErrorHandling:
    def test_all_tasks_isolated(self)
        """Error in one task doesn't affect others."""

    def test_error_logging(self)
        """Errors logged appropriately."""
```

**Estimated Effort:** 40 tests, 500 LOC, 1 day

---

### 2. operations.py - 0% Coverage (P0 - CRITICAL)

**File:** 353 LOC, 19 methods (RPC operation handlers)
**Risk:** RPC vulnerabilities, parameter validation bypass, operation failures

**What It Does:**
- Handles all RPC operations (register, task-claim, task-complete, lock, etc.)
- Bridges client requests to database layer
- Input validation

**Missing Tests (~60 tests, 800 LOC):**

```python
# tests/test_operations.py (NEW FILE NEEDED)

class TestAgentOperations:
    def test_op_register_success(self)
    def test_op_register_duplicate_error(self)
    def test_op_register_missing_params(self)
    def test_op_unregister_success(self)
    def test_op_unregister_nonexistent_agent(self)
    def test_op_heartbeat_updates_timestamp(self)
    def test_op_heartbeat_nonexistent_agent(self)

class TestTaskOperations:
    def test_op_task_create_success(self)
    def test_op_task_create_validation_error(self)
    def test_op_task_create_duplicate_error(self)
    def test_op_task_claim_success(self)
    def test_op_task_claim_already_claimed(self)
    def test_op_task_claim_nonexistent_task(self)
    def test_op_task_complete_success(self)
    def test_op_task_complete_not_owned(self)  # CRITICAL!
    def test_op_task_complete_nonexistent(self)
    def test_op_task_get_success(self)
    def test_op_task_get_nonexistent(self)
    def test_op_task_list_empty(self)
    def test_op_task_list_filtered(self)

class TestLockOperations:
    def test_op_lock_success(self)
    def test_op_lock_already_locked(self)
    def test_op_lock_invalid_file_path(self)
    def test_op_unlock_success(self)
    def test_op_unlock_not_owned(self)
    def test_op_unlock_nonexistent(self)
    def test_op_list_locks_agent(self)
    def test_op_list_locks_file(self)

class TestVelocityOperations:
    def test_op_velocity_current_period(self)
    def test_op_velocity_custom_period(self)
    def test_op_velocity_invalid_period(self)
    def test_op_file_hotspots_returns_top_files(self)
    def test_op_file_hotspots_limit(self)

class TestStatusOperations:
    def test_op_status_returns_all_stats(self)
    def test_op_status_accurate_counts(self)

class TestErrorPropagation:
    def test_database_error_propagates(self)
        """DB error should propagate to client."""

    def test_validation_error_propagates(self)
        """Validation error returns clear message."""

    def test_operation_not_found(self)
        """Unknown operation returns error."""
```

**Estimated Effort:** 60 tests, 800 LOC, 2 days

---

### 3. client.py - 0% Coverage (P0 - MEDIUM RISK)

**File:** 327 LOC, 2 methods (CoordinationClient class)
**Risk:** Client-server communication failures, timeout handling

**What It Does:**
- Client library for communicating with daemon
- Unix socket communication
- JSON-RPC protocol implementation
- Timeout handling

**Missing Tests (~30 tests, 400 LOC):**

```python
# tests/test_client.py (NEW FILE NEEDED)

class TestClientConnection:
    def test_connect_to_running_daemon(self)
    def test_connect_timeout_no_daemon(self)
    def test_reconnect_after_disconnect(self)
    def test_socket_file_missing(self)
    def test_socket_permission_denied(self)

class TestClientRequests:
    def test_send_request_success(self)
    def test_send_request_timeout(self)
    def test_send_request_large_payload(self)
    def test_send_request_malformed_response(self)
    def test_send_request_socket_error(self)

class TestClientErrorHandling:
    def test_error_response_raises_exception(self)
    def test_error_message_preserved(self)
    def test_connection_lost_during_request(self)
    def test_partial_response_handling(self)

class TestClientHelperMethods:
    # For all the convenience methods like register(), claim(), etc.
    def test_register_method(self)
    def test_claim_method(self)
    def test_complete_method(self)
    def test_lock_method(self)
    def test_unlock_method(self)
    def test_status_method(self)
```

**Estimated Effort:** 30 tests, 400 LOC, 1 day

---

### 4. server.py - 0% Coverage (P0 - MEDIUM RISK)

**File:** 172 LOC, 5 methods
**Risk:** Connection handling failures, resource leaks

**What It Does:**
- Unix socket server
- Connection handling
- Request routing to operations

**Missing Tests (~25 tests, 350 LOC):**

```python
# tests/test_server.py (NEW FILE NEEDED)

class TestServerStartStop:
    def test_start_creates_socket(self)
    def test_start_binds_to_socket_file(self)
    def test_stop_closes_socket(self)
    def test_stop_removes_socket_file(self)
    def test_restart_cleans_stale_socket(self)

class TestConnectionHandling:
    def test_accept_client_connection(self)
    def test_multiple_concurrent_connections(self)
    def test_connection_limit_enforced(self)
    def test_connection_timeout(self)
    def test_malformed_request_closes_connection(self)

class TestRequestProcessing:
    def test_valid_request_routed_to_operations(self)
    def test_invalid_json_returns_error(self)
    def test_missing_method_returns_error(self)
    def test_exception_during_processing_handled(self)

class TestResourceManagement:
    def test_connection_cleanup_on_error(self)
    def test_socket_file_permissions(self)
    def test_graceful_shutdown_waits_for_requests(self)
```

**Estimated Effort:** 25 tests, 350 LOC, 1 day

---

## Moderate Gaps (P1 - Should Fix)

### 5. daemon.py - Only 6 Tests (P1 - EXPAND)

**Current:** 6 tests in `test_daemon.py`
**File:** 172 LOC (main daemon orchestration)
**Current Tests:** Basic lifecycle only

**Missing Tests (~20 additional tests, 300 LOC):**

```python
# tests/test_daemon.py (EXPAND)

class TestDaemonLifecycle:
    # Current: test_agent_registration ✅
    # Current: test_task_workflow ✅
    # Current: test_file_locking ✅

    def test_daemon_start_with_existing_database(self)
        """Daemon loads existing state on start."""

    def test_daemon_start_creates_new_database(self)
        """Fresh daemon creates database."""

    def test_daemon_pid_file_creation(self)
        """PID file created on start."""

    def test_daemon_already_running_detection(self)
        """Detects if daemon already running."""

    def test_daemon_stale_pid_file_cleanup(self)
        """Cleans up stale PID file."""

class TestDaemonShutdown:
    def test_graceful_shutdown_stops_background_tasks(self)
        """Background tasks stopped on shutdown."""

    def test_graceful_shutdown_closes_server(self)
        """Server closed on shutdown."""

    def test_graceful_shutdown_closes_database(self)
        """Database connections closed."""

    def test_signal_handler_triggers_shutdown(self)
        """SIGTERM triggers graceful shutdown."""

class TestDaemonCrashRecovery:
    def test_restart_after_crash_recovers_state(self)
        """State recovered from database after crash."""

    def test_restart_cleans_up_orphaned_resources(self)
        """Orphaned locks/tasks cleaned up."""

    def test_restart_with_corrupted_database(self)
        """Handles corrupted database gracefully."""
```

**Estimated Effort:** 20 tests, 300 LOC, 0.5 days

---

## Test Quality Issues (P1-P2)

### Integration Tests - Good but Could Expand

**Current:** 21 tests in `test_integration.py`
**Status:** ✅ Good coverage of basic workflows

**Potential Additions (~15 tests):**
- More multi-client concurrent scenarios
- Network partition simulation
- Long-running daemon stress tests
- State consistency under extreme load

---

## Summary & Prioritization

### P0 - Critical (Must Fix This Week)

| File | LOC | Tests Needed | Effort | Risk |
|------|-----|--------------|--------|------|
| **background.py** | 277 | 40 | 1 day | HIGH |
| **operations.py** | 353 | 60 | 2 days | CRITICAL |
| **client.py** | 327 | 30 | 1 day | MEDIUM |
| **server.py** | 172 | 25 | 1 day | MEDIUM |
| **TOTAL P0** | **1129** | **155** | **5 days** | - |

### P1 - High Priority (This Sprint)

| File | Current Tests | Additional Tests | Effort |
|------|---------------|------------------|--------|
| **daemon.py** | 6 | 20 | 0.5 days |

### Coverage Projection

**Current:**
- Lines tested: ~44K / ~76K = 58%
- Files tested: 4 / 9 = 44%

**After P0 Fixes:**
- Lines tested: ~70K / ~76K = 92%
- Files tested: 8 / 9 = 89%

**After P1 Fixes:**
- Lines tested: ~73K / ~76K = 96%
- Files tested: 9 / 9 = 100%

---

## Comparison to Main Test Suite

### Coordination Daemon vs Main Codebase

| Metric | Coord Daemon | Main Codebase |
|--------|--------------|---------------|
| Files tested | 44% (4/9) | ~75% |
| Line coverage | 58% | 66.4% |
| Zero-coverage files | 4 | 3 |
| Test quality | B+ (87/100) | B+ (90/100) |

**Conclusion:** Coordination daemon has **similar quality** to main codebase but **smaller scope**, making it **easier to fix** (5 days vs 10 weeks for main codebase).

---

## Recommended Action Plan

### Week 1: Close P0 Gaps

**Day 1: background.py**
- Create `test_background.py`
- 40 tests for all background tasks
- Focus on dead agent cleanup (most critical)

**Day 2-3: operations.py**
- Create `test_operations.py`
- 60 tests for all RPC operations
- Ensure complete_task validation tested (regression prevention)

**Day 4: client.py**
- Create `test_client.py`
- 30 tests for client communication
- Connection error handling

**Day 5: server.py**
- Create `test_server.py`
- 25 tests for server lifecycle
- Connection handling

### Week 2: P1 + Integration

**Day 1: daemon.py expansion**
- Add 20 tests to `test_daemon.py`
- Lifecycle and crash recovery

**Day 2: Integration expansion**
- Add 15 multi-client scenarios
- Stress testing

---

## Quick Wins (Today)

### 1. Create test_background.py skeleton (30 min)
```bash
touch .claude-coord/coord_service/tests/test_background.py
# Add basic structure
```

### 2. Test dead agent cleanup (2 hours)
```python
def test_cleanup_removes_stale_agents():
    """Most critical background task - test first."""
    # ... implementation
```

### 3. Create test_operations.py (3 hours)
```python
def test_op_task_complete_not_owned():
    """Regression test for database corruption bug."""
    # This should raise ValueError (we just fixed this!)
```

---

## Success Metrics

### Definition of "Complete"

**Quantitative:**
- All source files have test files (9/9)
- Line coverage ≥90% for coord service
- Zero P0 gaps
- All RPC operations tested

**Qualitative:**
- Background task failures can't go unnoticed
- RPC operations can't bypass validation
- Client/server errors handled gracefully
- Crash recovery tested

---

## Conclusion

The coordination daemon has **solid foundations** (database, validator, protocol well-tested) but **critical infrastructure gaps** (background tasks, RPC operations, client/server untested).

**Good News:** Only **5 days** of work needed to reach **95%+ quality** for the coordination daemon (vs 2+ months for main codebase).

**Critical Path:**
1. Fix `operations.py` (2 days) - Prevents RPC bypass
2. Fix `background.py` (1 day) - Prevents resource leaks
3. Fix `client.py` + `server.py` (2 days) - Prevents comm failures

**Result:** Coordination daemon at production-ready quality in 1 week.
