"""Test support utilities for global state isolation.

Provides centralized reset of all module-level singletons so tests
can run in clean isolation without polluting each other's state.

Usage in tests::

    from src.shared.core.test_support import reset_all_globals, isolated_globals

    # Manual reset
    def teardown_function():
        reset_all_globals()

    # Context manager (auto-reset on exit)
    def test_something():
        with isolated_globals():
            ...  # globals are reset on entry and exit

Usage as a pytest fixture (see tests/conftest.py)::

    @pytest.fixture(autouse=True)
    def _clean_globals():
        yield
        reset_all_globals()
"""
import logging
from contextlib import contextmanager
from typing import Callable, Generator, List

logger = logging.getLogger(__name__)

# Registry of reset functions.
# Each entry is (module_path, reset_callable).
_reset_registry: List[Callable[[], None]] = []


def register_reset(fn: Callable[[], None]) -> None:
    """Register a reset function for global state cleanup.

    Args:
        fn: Callable that resets one module's global state.
    """
    _reset_registry.append(fn)


def reset_all_globals() -> None:
    """Reset all registered global singletons.

    Safe to call multiple times. Errors in individual resets are
    logged but don't prevent other resets from running.
    """
    for fn in _get_all_reset_functions():
        try:
            fn()
        except Exception as e:
            logger.debug(f"Reset function {fn.__module__}.{fn.__qualname__} failed: {e}")


@contextmanager
def isolated_globals() -> Generator[None, None, None]:
    """Context manager that resets globals on entry and exit.

    Ensures tests start and finish with clean global state::

        with isolated_globals():
            # all globals are fresh
            init_database("sqlite:///test.db")
            ...
        # globals are reset again
    """
    reset_all_globals()
    try:
        yield
    finally:
        reset_all_globals()


def _get_all_reset_functions() -> List[Callable[[], None]]:
    """Collect all known reset functions from framework modules.

    Uses lazy imports to avoid circular dependencies and to only
    collect from modules that are actually loaded.
    """
    fns: List[Callable[[], None]] = list(_reset_registry)

    # Observability
    try:
        from src.observability.hooks import reset_tracker
        fns.append(reset_tracker)
    except ImportError:
        pass

    try:
        from src.observability.performance import reset_performance_tracker
        fns.append(reset_performance_tracker)
    except ImportError:
        pass

    try:
        from src.storage.database import reset_database
        fns.append(reset_database)
    except ImportError:
        pass

    # Core
    try:
        from src.safety.service_mixin import reset_sanitizer
        fns.append(reset_sanitizer)
    except ImportError:
        pass

    # Security
    try:
        from src.safety.security.llm_security import reset_security_components
        fns.append(reset_security_components)
    except ImportError:
        pass

    # Registries
    try:
        from src.agent.strategies.registry import StrategyRegistry
        fns.append(StrategyRegistry.reset_for_testing)
    except ImportError:
        pass

    try:
        from src.agent.utils.agent_factory import AgentFactory
        fns.append(AgentFactory.reset_for_testing)
    except ImportError:
        pass

    try:
        from src.llm.pricing import PricingManager
        fns.append(PricingManager.reset_for_testing)
    except ImportError:
        pass

    return fns
