"""Tests for temper_ai/shared/core/test_support.py.

Covers global-state reset utilities used in test isolation.
"""

from unittest.mock import MagicMock

import pytest

from temper_ai.shared.core.test_support import (
    _reset_registry,
    isolated_globals,
    register_reset,
    reset_all_globals,
)


class TestRegisterReset:
    """Tests for register_reset()."""

    def setup_method(self):
        """Save registry state before each test."""
        self._original_registry = list(_reset_registry)

    def teardown_method(self):
        """Restore registry state after each test."""
        _reset_registry.clear()
        _reset_registry.extend(self._original_registry)

    def test_registers_callable(self):
        """register_reset adds a callable to the registry."""
        fn = MagicMock()
        register_reset(fn)
        assert fn in _reset_registry

    def test_multiple_registrations(self):
        """Multiple callables can be registered."""
        fn1 = MagicMock()
        fn2 = MagicMock()
        register_reset(fn1)
        register_reset(fn2)
        assert fn1 in _reset_registry
        assert fn2 in _reset_registry

    def test_same_callable_registered_twice(self):
        """Registering same callable twice adds it twice."""
        fn = MagicMock()
        register_reset(fn)
        register_reset(fn)
        assert _reset_registry.count(fn) == 2


class TestResetAllGlobals:
    """Tests for reset_all_globals()."""

    def setup_method(self):
        self._original_registry = list(_reset_registry)

    def teardown_method(self):
        _reset_registry.clear()
        _reset_registry.extend(self._original_registry)

    def test_calls_registered_functions(self):
        """reset_all_globals calls all registered reset functions."""
        fn = MagicMock()
        register_reset(fn)
        reset_all_globals()
        fn.assert_called()

    def test_error_in_reset_does_not_propagate(self):
        """Errors in reset functions are swallowed (logged)."""

        def bad_reset():
            raise RuntimeError("boom")

        register_reset(bad_reset)
        # Should not raise
        reset_all_globals()

    def test_all_registered_called_even_after_error(self):
        """All functions are called even if one raises."""
        fn_good = MagicMock()

        def bad_reset():
            raise RuntimeError("boom")

        register_reset(bad_reset)
        register_reset(fn_good)
        reset_all_globals()
        fn_good.assert_called()

    def test_safe_to_call_multiple_times(self):
        """reset_all_globals is idempotent."""
        fn = MagicMock()
        register_reset(fn)
        reset_all_globals()
        reset_all_globals()
        assert fn.call_count >= 2

    def test_no_error_with_empty_registry(self):
        """reset_all_globals with no registered functions does not raise."""
        _reset_registry.clear()
        reset_all_globals()  # Should not raise


class TestIsolatedGlobals:
    """Tests for isolated_globals() context manager."""

    def setup_method(self):
        self._original_registry = list(_reset_registry)

    def teardown_method(self):
        _reset_registry.clear()
        _reset_registry.extend(self._original_registry)

    def test_reset_called_on_entry(self):
        """reset_all_globals is called when entering context."""
        fn = MagicMock()
        register_reset(fn)
        with isolated_globals():
            assert fn.call_count >= 1

    def test_reset_called_on_exit(self):
        """reset_all_globals is called when exiting context."""
        fn = MagicMock()
        register_reset(fn)
        with isolated_globals():
            count_inside = fn.call_count
        assert fn.call_count > count_inside

    def test_reset_called_on_exception(self):
        """reset_all_globals is called even when exception is raised inside."""
        fn = MagicMock()
        register_reset(fn)

        with pytest.raises(ValueError):
            with isolated_globals():
                raise ValueError("test error")

        # Was called at least once (entry) + once (exit on exception)
        assert fn.call_count >= 2

    def test_exception_propagates(self):
        """Exceptions inside isolated_globals are not swallowed."""
        with pytest.raises(RuntimeError, match="test"):
            with isolated_globals():
                raise RuntimeError("test")

    def test_is_reentrant(self):
        """isolated_globals can be nested."""
        fn = MagicMock()
        register_reset(fn)
        with isolated_globals():
            with isolated_globals():
                pass
        assert fn.call_count >= 4  # entry+exit for each level

    def test_returns_none(self):
        """Context manager yields None."""
        with isolated_globals() as value:
            assert value is None
