"""Extended tests for temper_ai/shared/core/test_support.py.

Targets uncovered lines 94-155 (all the except ImportError branches
in _get_all_reset_functions).  We patch sys.modules so each import fails,
triggering the except ImportError: pass branches.
"""

import sys
from unittest.mock import MagicMock, patch

from temper_ai.shared.core.test_support import (
    _get_all_reset_functions,
    _reset_registry,
    register_reset,
    reset_all_globals,
)


class TestGetAllResetFunctionsImportErrors:
    """Test _get_all_reset_functions handles all ImportError branches."""

    def setup_method(self):
        self._original_registry = list(_reset_registry)

    def teardown_method(self):
        _reset_registry.clear()
        _reset_registry.extend(self._original_registry)

    def _block_imports(self, *module_names):
        """Return a context dict for patching sys.modules with None to simulate missing modules."""
        return dict.fromkeys(module_names)

    def test_all_imports_blocked_returns_just_registered(self):
        """When all optional imports fail, only registered functions returned."""
        fn = MagicMock()
        register_reset(fn)

        blocked = self._block_imports(
            "temper_ai.observability.hooks",
            "temper_ai.observability.performance",
            "temper_ai.storage.database",
            "temper_ai.safety.service_mixin",
            "temper_ai.safety.security.llm_security",
            "temper_ai.agent.strategies.registry",
            "temper_ai.agent.utils.agent_factory",
            "temper_ai.llm.pricing",
            "temper_ai.stage.executors",
            "temper_ai.stage.executors._agent_execution",
        )
        with patch.dict(sys.modules, blocked):
            fns = _get_all_reset_functions()

        assert fn in fns

    def test_observability_hooks_import_error_skipped(self):
        """ImportError for observability.hooks is silently skipped (lines 91-95)."""
        with patch.dict(sys.modules, {"temper_ai.observability.hooks": None}):
            fns = _get_all_reset_functions()
        # Should not raise; result is a list
        assert isinstance(fns, list)

    def test_observability_performance_import_error_skipped(self):
        """ImportError for observability.performance is skipped (lines 97-102)."""
        with patch.dict(sys.modules, {"temper_ai.observability.performance": None}):
            fns = _get_all_reset_functions()
        assert isinstance(fns, list)

    def test_storage_database_import_error_skipped(self):
        """ImportError for storage.database is skipped (lines 104-109)."""
        with patch.dict(sys.modules, {"temper_ai.storage.database": None}):
            fns = _get_all_reset_functions()
        assert isinstance(fns, list)

    def test_safety_service_mixin_import_error_skipped(self):
        """ImportError for safety.service_mixin is skipped (lines 112-117)."""
        with patch.dict(sys.modules, {"temper_ai.safety.service_mixin": None}):
            fns = _get_all_reset_functions()
        assert isinstance(fns, list)

    def test_safety_security_llm_security_import_error_skipped(self):
        """ImportError for safety.security.llm_security is skipped (lines 119-125)."""
        with patch.dict(sys.modules, {"temper_ai.safety.security.llm_security": None}):
            fns = _get_all_reset_functions()
        assert isinstance(fns, list)

    def test_agent_strategies_registry_import_error_skipped(self):
        """ImportError for agent.strategies.registry is skipped (lines 127-133)."""
        with patch.dict(sys.modules, {"temper_ai.agent.strategies.registry": None}):
            fns = _get_all_reset_functions()
        assert isinstance(fns, list)

    def test_agent_utils_agent_factory_import_error_skipped(self):
        """ImportError for agent.utils.agent_factory is skipped (lines 135-140)."""
        with patch.dict(sys.modules, {"temper_ai.agent.utils.agent_factory": None}):
            fns = _get_all_reset_functions()
        assert isinstance(fns, list)

    def test_llm_pricing_import_error_skipped(self):
        """ImportError for llm.pricing is skipped (lines 142-147)."""
        with patch.dict(sys.modules, {"temper_ai.llm.pricing": None}):
            fns = _get_all_reset_functions()
        assert isinstance(fns, list)

    def test_stage_executors_import_error_skipped(self):
        """ImportError for stage.executors is skipped (lines 149-155)."""
        with patch.dict(
            sys.modules,
            {
                "temper_ai.stage.executors": None,
                "temper_ai.stage.executors._agent_execution": None,
            },
        ):
            fns = _get_all_reset_functions()
        assert isinstance(fns, list)

    def test_registered_fn_always_included_even_with_import_errors(self):
        """Registered reset functions are always included regardless of import errors."""
        fn1 = MagicMock()
        fn2 = MagicMock()
        register_reset(fn1)
        register_reset(fn2)

        blocked = self._block_imports(
            "temper_ai.observability.hooks",
            "temper_ai.observability.performance",
            "temper_ai.storage.database",
        )
        with patch.dict(sys.modules, blocked):
            fns = _get_all_reset_functions()

        assert fn1 in fns
        assert fn2 in fns

    def test_reset_all_globals_with_import_errors_does_not_raise(self):
        """reset_all_globals works even if optional modules can't be imported."""
        blocked = self._block_imports(
            "temper_ai.observability.hooks",
            "temper_ai.observability.performance",
            "temper_ai.storage.database",
            "temper_ai.safety.service_mixin",
            "temper_ai.safety.security.llm_security",
        )
        with patch.dict(sys.modules, blocked):
            reset_all_globals()  # Should not raise


class TestGetAllResetFunctionsSuccessfulImports:
    """Test _get_all_reset_functions when optional modules ARE available."""

    def setup_method(self):
        self._original_registry = list(_reset_registry)

    def teardown_method(self):
        _reset_registry.clear()
        _reset_registry.extend(self._original_registry)

    def test_available_module_reset_added(self):
        """When a module is importable, its reset function is collected."""
        mock_reset = MagicMock()
        mock_hooks_module = MagicMock()
        mock_hooks_module.reset_tracker = mock_reset

        with patch.dict(
            sys.modules,
            {"temper_ai.observability.hooks": mock_hooks_module},
        ):
            fns = _get_all_reset_functions()

        assert mock_reset in fns

    def test_performance_reset_added_when_available(self):
        """When observability.performance is importable, its reset is collected."""
        mock_reset = MagicMock()
        mock_perf_module = MagicMock()
        mock_perf_module.reset_performance_tracker = mock_reset

        with patch.dict(
            sys.modules,
            {"temper_ai.observability.performance": mock_perf_module},
        ):
            fns = _get_all_reset_functions()

        assert mock_reset in fns
