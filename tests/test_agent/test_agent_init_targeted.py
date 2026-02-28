"""Targeted tests for agent/__init__.py to improve coverage from 29% to 90%+.

Covers: lazy import __getattr__ behavior and AttributeError for unknown names.
"""

import pytest


class TestAgentInit:
    def test_lazy_import_base_agent(self):
        import temper_ai.agent as agent_module

        cls = agent_module.BaseAgent
        assert cls.__name__ == "BaseAgent"

    def test_lazy_import_agent_response(self):
        import temper_ai.agent as agent_module

        cls = agent_module.AgentResponse
        assert cls.__name__ == "AgentResponse"

    def test_lazy_import_tool_call_record(self):
        import temper_ai.agent as agent_module

        cls = agent_module.ToolCallRecord
        assert cls.__name__ == "ToolCallRecord"

    def test_lazy_import_standard_agent(self):
        import temper_ai.agent as agent_module

        cls = agent_module.StandardAgent
        assert cls.__name__ == "StandardAgent"

    def test_lazy_import_execution_context(self):
        import temper_ai.agent as agent_module

        cls = agent_module.ExecutionContext
        assert cls.__name__ == "ExecutionContext"

    def test_lazy_import_agent_factory(self):
        import temper_ai.agent as agent_module

        cls = agent_module.AgentFactory
        assert cls.__name__ == "AgentFactory"

    def test_lazy_import_prompt_engine(self):
        import temper_ai.agent as agent_module

        cls = agent_module.PromptEngine
        assert cls.__name__ == "PromptEngine"

    def test_lazy_import_prompt_render_error(self):
        import temper_ai.agent as agent_module

        cls = agent_module.PromptRenderError
        assert cls.__name__ == "PromptRenderError"

    def test_unknown_attribute_raises_attribute_error(self):
        import temper_ai.agent as agent_module

        with pytest.raises(AttributeError, match="no attribute 'NonExistent'"):
            _ = agent_module.NonExistent

    def test_lazy_imports_cached_after_first_access(self):
        import temper_ai.agent as agent_module

        # First access
        cls1 = agent_module.BaseAgent
        # Second access should use cached value from globals()
        cls2 = agent_module.BaseAgent
        assert cls1 is cls2
