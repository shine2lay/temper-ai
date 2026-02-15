"""Tests for code-high-except-broad-13.

Verifies that llm_cache.py uses specific exception types instead of broad
`except Exception:`, and that KeyboardInterrupt / SystemExit propagate.
"""

from unittest.mock import MagicMock

import pytest

from src.llm.cache.llm_cache import LLMCache


class TestLLMCacheSpecificExceptions:
    """Verify LLMCache.get/set catch only expected exception types."""

    def _make_cache(self):
        """Create an LLMCache with in-memory backend."""
        return LLMCache(backend="memory", ttl=300)

    def test_get_catches_os_error(self):
        """OSError from backend.get() should be caught gracefully."""
        cache = self._make_cache()
        cache._backend.get = MagicMock(side_effect=OSError("disk full"))

        result = cache.get("test-key")

        assert result is None
        assert cache.stats.errors == 1

    def test_get_catches_runtime_error(self):
        """RuntimeError from backend.get() should be caught gracefully."""
        cache = self._make_cache()
        cache._backend.get = MagicMock(side_effect=RuntimeError("lock failed"))

        result = cache.get("test-key")

        assert result is None
        assert cache.stats.errors == 1

    def test_get_catches_value_error(self):
        """ValueError from backend.get() should be caught gracefully."""
        cache = self._make_cache()
        cache._backend.get = MagicMock(side_effect=ValueError("bad data"))

        result = cache.get("test-key")

        assert result is None
        assert cache.stats.errors == 1

    def test_set_catches_os_error(self):
        """OSError from backend.set() should be caught gracefully."""
        cache = self._make_cache()
        cache._backend.set = MagicMock(side_effect=OSError("disk full"))

        result = cache.set("test-key", "value")

        assert result is False
        assert cache.stats.errors == 1

    def test_set_catches_runtime_error(self):
        """RuntimeError from backend.set() should be caught gracefully."""
        cache = self._make_cache()
        cache._backend.set = MagicMock(side_effect=RuntimeError("lock failed"))

        result = cache.set("test-key", "value")

        assert result is False
        assert cache.stats.errors == 1

    def test_set_catches_value_error(self):
        """ValueError from backend.set() should be caught gracefully."""
        cache = self._make_cache()
        cache._backend.set = MagicMock(side_effect=ValueError("bad data"))

        result = cache.set("test-key", "value")

        assert result is False
        assert cache.stats.errors == 1


class TestKeyboardInterruptPropagates:
    """KeyboardInterrupt must NOT be caught — it should propagate."""

    def _make_cache(self):
        return LLMCache(backend="memory", ttl=300)

    def test_get_propagates_keyboard_interrupt(self):
        """KeyboardInterrupt during get() must propagate."""
        cache = self._make_cache()
        cache._backend.get = MagicMock(side_effect=KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            cache.get("test-key")

    def test_set_propagates_keyboard_interrupt(self):
        """KeyboardInterrupt during set() must propagate."""
        cache = self._make_cache()
        cache._backend.set = MagicMock(side_effect=KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            cache.set("test-key", "value")


class TestSystemExitPropagates:
    """SystemExit must NOT be caught — it should propagate."""

    def _make_cache(self):
        return LLMCache(backend="memory", ttl=300)

    def test_get_propagates_system_exit(self):
        """SystemExit during get() must propagate."""
        cache = self._make_cache()
        cache._backend.get = MagicMock(side_effect=SystemExit(1))

        with pytest.raises(SystemExit):
            cache.get("test-key")

    def test_set_propagates_system_exit(self):
        """SystemExit during set() must propagate."""
        cache = self._make_cache()
        cache._backend.set = MagicMock(side_effect=SystemExit(1))

        with pytest.raises(SystemExit):
            cache.set("test-key", "value")


class TestUnexpectedExceptionsNotSwallowed:
    """Exceptions NOT in the catch list must propagate (not be silently swallowed)."""

    def _make_cache(self):
        return LLMCache(backend="memory", ttl=300)

    def test_get_propagates_type_error(self):
        """TypeError from backend.get() should propagate (not in catch list)."""
        cache = self._make_cache()
        cache._backend.get = MagicMock(side_effect=TypeError("wrong type"))

        with pytest.raises(TypeError):
            cache.get("test-key")

    def test_set_propagates_attribute_error(self):
        """AttributeError from backend.set() should propagate (not in catch list)."""
        cache = self._make_cache()
        cache._backend.set = MagicMock(side_effect=AttributeError("no such attr"))

        with pytest.raises(AttributeError):
            cache.set("test-key", "value")

    def test_get_propagates_import_error(self):
        """ImportError from backend.get() should propagate."""
        cache = self._make_cache()
        cache._backend.get = MagicMock(side_effect=ImportError("no module"))

        with pytest.raises(ImportError):
            cache.get("test-key")


class TestExceptionLogging:
    """Verify caught exceptions are logged with context."""

    def _make_cache(self):
        return LLMCache(backend="memory", ttl=300)

    def test_get_error_logged(self, caplog):
        """Caught get() errors should be logged with key context."""
        import logging
        cache = self._make_cache()
        cache._backend.get = MagicMock(side_effect=OSError("connection reset"))

        with caplog.at_level(logging.ERROR):
            cache.get("my-test-key-12345678")

        assert "Cache get error" in caplog.text
        assert "connection reset" in caplog.text

    def test_set_error_logged(self, caplog):
        """Caught set() errors should be logged with key context."""
        import logging
        cache = self._make_cache()
        cache._backend.set = MagicMock(side_effect=OSError("broken pipe"))

        with caplog.at_level(logging.ERROR):
            cache.set("my-test-key-12345678", "value")

        assert "Cache set error" in caplog.text
        assert "broken pipe" in caplog.text


class TestNoExceptException:
    """Verify no broad `except Exception:` remains in the module."""

    def test_no_except_exception_in_source(self):
        """The llm_cache module should not contain 'except Exception'."""
        import inspect

        import src.llm.cache.llm_cache as mod

        source = inspect.getsource(mod)
        # Count occurrences of 'except Exception' (not preceded by specific types)
        lines = source.split('\n')
        broad_catches = [
            line.strip() for line in lines
            if 'except Exception' in line and 'except Exception' == line.strip().rstrip(':').strip()
        ]
        assert len(broad_catches) == 0, (
            f"Found broad 'except Exception:' handlers: {broad_catches}"
        )

    def test_no_bare_except_in_source(self):
        """The llm_cache module should not contain bare 'except:'."""
        import inspect

        import src.llm.cache.llm_cache as mod

        source = inspect.getsource(mod)
        lines = source.split('\n')
        bare_catches = [
            line.strip() for line in lines
            if line.strip() == 'except:'
        ]
        assert len(bare_catches) == 0, (
            f"Found bare 'except:' handlers: {bare_catches}"
        )
