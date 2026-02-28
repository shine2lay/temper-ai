"""Coverage tests for temper_ai/llm/__init__.py.

Covers: lazy __getattr__ for LLMService and LLMRunResult imports.
"""

from __future__ import annotations

import pytest


class TestLLMInit:
    def test_lazy_import_llm_service(self) -> None:
        from temper_ai.llm import LLMService

        assert LLMService is not None

    def test_lazy_import_llm_run_result(self) -> None:
        from temper_ai.llm import LLMRunResult

        assert LLMRunResult is not None

    def test_lazy_import_unknown_attr(self) -> None:
        with pytest.raises(AttributeError, match="no attribute"):
            from temper_ai import llm

            llm.__getattr__("NonExistentAttribute")

    def test_all_exports(self) -> None:
        import temper_ai.llm as llm_module

        assert "LLMService" in llm_module.__all__
        assert "LLMRunResult" in llm_module.__all__
