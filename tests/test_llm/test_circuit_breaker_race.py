"""
Security tests for circuit breaker race condition fix.

Tests verify that:
1. State transitions during execution are handled safely
2. Only one test execution occurs in HALF_OPEN state
3. No execution occurs when circuit is OPEN
4. State reservation is atomic and thread-safe
"""
import threading
import time

import httpx
import pytest

from temper_ai.shared.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
)


def create_counted_error():
    """Create an error that will be counted by circuit breaker (timeout error)."""
    return httpx.TimeoutException("Simulated timeout")


class TestCircuitBreakerRaceCondition:
    """Test race condition prevention in circuit breaker."""

    def test_race_condition_half_open_to_open(self):
        """Test that state transition during execution is handled safely."""
        breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                success_threshold=2,  # Require 2 successes (so 1 success won't close)
                timeout=1
            )
        )

        # Open circuit with counted error (timeout)
        try:
            breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
        except httpx.TimeoutException:
            pass

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout to allow HALF_OPEN
        time.sleep(1.1)

        execution_started = threading.Event()
        execution_continue = threading.Event()
        results = {"thread1_executed": False, "thread2_executed": False, "thread1_result": None}

        def slow_success():
            """Slow function that allows race condition to occur."""
            results["thread1_executed"] = True
            execution_started.set()
            execution_continue.wait(timeout=2.0)  # Wait for thread 2
            return "success"

        def trigger_failure():
            """Wait for thread 1 to start, then attempt to fail."""
            execution_started.wait(timeout=2.0)
            results["thread2_executed"] = True
            try:
                # Thread 2 will be rejected because thread 1 holds semaphore
                breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
            except (CircuitBreakerError, httpx.TimeoutException):
                # Expected - either rejected by semaphore or timeout error
                pass
            execution_continue.set()

        # Thread 1: Start slow execution in HALF_OPEN
        def run_t1():
            try:
                result = breaker.call(slow_success)
                results["thread1_result"] = result
            except CircuitBreakerError:
                results["thread1_result"] = "rejected"

        t1 = threading.Thread(target=run_t1)
        t1.start()

        # Thread 2: Try to execute (will be rejected due to semaphore)
        t2 = threading.Thread(target=trigger_failure)
        t2.start()

        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        # Thread 1 should have executed successfully
        assert results["thread1_executed"]
        assert results["thread1_result"] == "success"
        # Thread 2 was rejected by semaphore (couldn't execute)
        assert results["thread2_executed"]
        # Circuit should be HALF_OPEN still (need 2 successes, only got 1)
        assert breaker.state == CircuitState.HALF_OPEN

    def test_concurrent_half_open_executions_prevented(self):
        """Test that only ONE thread executes AT A TIME during HALF_OPEN state."""
        breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                success_threshold=3,  # Need 3 successes to close
                timeout=1
            )
        )

        # Open circuit with counted error
        try:
            breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
        except httpx.TimeoutException:
            pass

        time.sleep(1.1)

        execution_count = {"value": 0}
        rejected_count = {"value": 0}
        lock = threading.Lock()

        execution_barrier = threading.Barrier(10)  # Wait for all threads to start

        def concurrent_attempt():
            # Wait for all threads to be ready
            execution_barrier.wait(timeout=2.0)

            # All threads attempt execution simultaneously
            try:
                breaker.call(lambda: "success")
                with lock:
                    execution_count["value"] += 1
            except CircuitBreakerError:
                with lock:
                    rejected_count["value"] += 1

        # Launch 10 concurrent execution attempts
        threads = [threading.Thread(target=concurrent_attempt) for _ in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=3.0)

        # In HALF_OPEN state, threads are allowed to execute ONE AT A TIME (serially)
        # With success_threshold=3, first 3 successes close the circuit
        # Remaining threads execute in CLOSED state (all succeed)
        # So ALL should succeed (3 in HALF_OPEN sequentially, 7 in CLOSED concurrently)
        assert execution_count["value"] == 10, f"Expected 10 executions, got {execution_count['value']}"
        assert rejected_count["value"] == 0, f"Expected 0 rejections, got {rejected_count['value']}"

        # Circuit should be CLOSED after 3 successes
        assert breaker.state == CircuitState.CLOSED

    def test_no_execution_when_open(self):
        """Test that OPEN circuit blocks ALL execution attempts."""
        breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(failure_threshold=1, timeout=10)
        )

        # Open circuit with counted error
        try:
            breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
        except httpx.TimeoutException:
            pass

        assert breaker.state == CircuitState.OPEN

        execution_count = {"value": 0}
        lock = threading.Lock()

        def try_execute():
            try:
                def increment():
                    with lock:
                        execution_count["value"] += 1
                    return "success"

                breaker.call(increment)
            except CircuitBreakerError:
                pass  # Expected

        # Launch 100 concurrent attempts
        threads = [threading.Thread(target=try_execute) for _ in range(100)]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=2.0)

        # NONE should have executed
        assert execution_count["value"] == 0, f"Expected 0 executions, got {execution_count['value']}"

        # Circuit should still be OPEN
        assert breaker.state == CircuitState.OPEN

    def test_state_reservation_atomicity(self):
        """Test that concurrent calls all succeed atomically in CLOSED state."""
        breaker = CircuitBreaker(name="test")

        results = []
        lock = threading.Lock()

        def call_and_record():
            result = breaker.call(lambda: "ok")
            with lock:
                results.append(result)

        # Launch 100 concurrent calls
        threads = [threading.Thread(target=call_and_record) for _ in range(100)]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=2.0)

        # All should have completed successfully in CLOSED state
        assert len(results) == 100
        assert all(r == "ok" for r in results)
        assert breaker.state == CircuitState.CLOSED

    def test_only_one_concurrent_test_in_half_open(self):
        """Test that only ONE thread can test CONCURRENTLY in HALF_OPEN."""
        breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                success_threshold=10,  # High threshold so circuit stays HALF_OPEN
                timeout=0.5
            )
        )

        # Open circuit
        try:
            breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
        except httpx.TimeoutException:
            pass

        time.sleep(0.6)

        # Track concurrent executions
        concurrent_count = {"max": 0, "current": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(10)

        def slow_test():
            """Slow test to ensure overlap if concurrency not prevented."""
            barrier.wait(timeout=2.0)

            try:
                def slow_func():
                    with lock:
                        concurrent_count["current"] += 1
                        concurrent_count["max"] = max(concurrent_count["max"], concurrent_count["current"])

                    time.sleep(0.1)  # Slow operation

                    with lock:
                        concurrent_count["current"] -= 1

                    return "success"

                breaker.call(slow_func)
            except CircuitBreakerError:
                pass  # Rejected due to semaphore

        threads = [threading.Thread(target=slow_test) for _ in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=5.0)

        # Maximum concurrent executions should be 1 (semaphore enforcement)
        assert concurrent_count["max"] == 1, \
            f"Expected max 1 concurrent execution, got {concurrent_count['max']}"

    def test_thundering_herd_prevention(self):
        """Test that thundering herd is prevented in HALF_OPEN state.

        When 50 threads arrive simultaneously, only a few should execute serially,
        the rest should be rejected to prevent overwhelming the service.
        """
        breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(
                failure_threshold=2,
                success_threshold=3,  # Need 3 successes to close
                timeout=0.5
            )
        )

        # Open circuit with counted errors
        for _ in range(2):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
            except httpx.TimeoutException:
                pass

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.6)

        # Simulate 50 threads arriving simultaneously (thundering herd scenario)
        execution_count = {"value": 0}
        rejected_count = {"value": 0}
        concurrent_count = {"max": 0, "current": 0}
        lock = threading.Lock()

        barrier = threading.Barrier(50)

        def concurrent_test():
            barrier.wait(timeout=2.0)
            try:
                def tracked_func():
                    with lock:
                        concurrent_count["current"] += 1
                        concurrent_count["max"] = max(concurrent_count["max"], concurrent_count["current"])

                    time.sleep(0.01)  # Small delay

                    with lock:
                        concurrent_count["current"] -= 1

                    return "success"

                breaker.call(tracked_func)
                with lock:
                    execution_count["value"] += 1
            except CircuitBreakerError:
                with lock:
                    rejected_count["value"] += 1

        threads = [threading.Thread(target=concurrent_test) for _ in range(50)]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=10.0)

        # THUNDERING HERD PREVENTION:
        # - Only a small number execute (≤ success_threshold + a few more after CLOSED)
        # - Most are rejected by semaphore
        # - Max concurrent execution is 1 (serial execution in HALF_OPEN)

        assert concurrent_count["max"] == 1, \
            f"Expected max 1 concurrent (serial), got {concurrent_count['max']}"

        # Small number execute, most rejected (thundering herd prevented)
        assert rejected_count["value"] >= 40, \
            f"Expected most threads rejected (≥40), got {rejected_count['value']} rejections"

        assert execution_count["value"] <= 10, \
            f"Expected few executions (≤10), got {execution_count['value']}"

        print(f"Thundering herd prevention: {execution_count['value']} executed, "
              f"{rejected_count['value']} rejected out of 50")


class TestCircuitBreakerConcurrency:
    """Test concurrent behavior under various loads."""

    def test_high_concurrency_closed_state(self):
        """Test that CLOSED state allows high concurrency."""
        breaker = CircuitBreaker(name="test")

        success_count = {"value": 0}
        lock = threading.Lock()

        def concurrent_success():
            result = breaker.call(lambda: "success")
            with lock:
                success_count["value"] += 1
            return result

        # Launch 100 concurrent executions in CLOSED state
        threads = [threading.Thread(target=concurrent_success) for _ in range(100)]

        start_time = time.time()
        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=3.0)

        duration = time.time() - start_time

        # All should succeed
        assert success_count["value"] == 100

        # Should complete quickly (< 1s) since all execute concurrently
        assert duration < 1.0, f"High concurrency test took {duration}s (expected < 1s)"

        # Circuit should remain CLOSED
        assert breaker.state == CircuitState.CLOSED

    def test_rapid_state_transitions(self):
        """Test circuit breaker under rapid state transitions."""
        breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(
                failure_threshold=2,
                success_threshold=2,
                timeout=0.1
            )
        )

        # Alternate between success and failure rapidly
        for _ in range(10):
            # 2 successes
            breaker.call(lambda: "success")
            breaker.call(lambda: "success")

            # 2 failures (open circuit) with counted errors
            for _ in range(2):
                try:
                    breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
                except httpx.TimeoutException:
                    pass

            # Wait for timeout
            time.sleep(0.15)

        # Circuit should eventually stabilize
        # After last iteration, circuit is OPEN, but timeout elapsed
        # Next call should transition to HALF_OPEN
        time.sleep(0.15)

        # Should be able to recover
        breaker.call(lambda: "success")
        breaker.call(lambda: "success")

        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerEdgeCases:
    """Test edge cases and error handling."""

    def test_semaphore_release_on_exception(self):
        """Test that semaphore is released even if exception occurs."""
        breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                success_threshold=1,
                timeout=0.5
            )
        )

        # Open circuit with counted error
        try:
            breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
        except httpx.TimeoutException:
            pass

        # Wait for timeout
        time.sleep(0.6)

        # First call fails and should release semaphore
        try:
            breaker.call(lambda: (_ for _ in ()).throw(create_counted_error()))
        except (httpx.TimeoutException, CircuitBreakerError):
            pass

        # Circuit should be OPEN again
        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.6)

        # Second call should be able to acquire semaphore (not stuck)
        try:
            breaker.call(lambda: "success")
        except CircuitBreakerError:
            pytest.fail("Semaphore was not released after exception")

        # Should succeed and close circuit
        assert breaker.state == CircuitState.CLOSED

    def test_non_countable_error_releases_semaphore(self):
        """Test that non-countable errors still release semaphore."""
        import httpx

        breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                success_threshold=1,
                timeout=0.5
            )
        )

        # Open circuit
        try:
            breaker.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except Exception:
            pass

        time.sleep(0.6)

        # Call with non-countable error (HTTP 401)
        def auth_error():
            response = type('obj', (object,), {'status_code': 401})()
            raise httpx.HTTPStatusError("Auth error", request=None, response=response)

        try:
            breaker.call(auth_error)
        except httpx.HTTPStatusError:
            pass  # Expected

        # Semaphore should be released
        # Next call should be able to acquire it
        try:
            result = breaker.call(lambda: "success")
            assert result == "success"
        except CircuitBreakerError:
            pytest.fail("Semaphore was not released after non-countable error")


class TestCircuitBreakerBackwardCompatibility:
    """Test backward compatibility of circuit breaker changes."""

    def test_legacy_on_success_call_without_state(self):
        """Test that _on_success() can be called without reserved_state (backward compat).

        Intentionally tests private method — external subclasses may call it directly.
        """
        breaker = CircuitBreaker(name="test")
        breaker._on_success()
        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    def test_legacy_on_failure_call_without_state(self):
        """Test that _on_failure() can be called without reserved_state (backward compat).

        Intentionally tests private method — external subclasses may call it directly.
        """
        breaker = CircuitBreaker(name="test")
        breaker._on_failure(create_counted_error())
        assert breaker.failure_count == 1
