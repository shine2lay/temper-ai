"""Tests for LangGraph execution engine adapter.

Tests the adapter that wraps LangGraphCompiler behind the ExecutionEngine interface.
Verifies that all M2 functionality is preserved through the adapter.
"""

from unittest.mock import Mock, patch

import pytest

from src.compiler.execution_engine import ExecutionMode
from src.compiler.langgraph_engine import LangGraphCompiledWorkflow, LangGraphExecutionEngine

# Sample workflow configs for testing
SIMPLE_WORKFLOW_CONFIG = {
    "workflow": {
        "stages": ["research", "synthesis"]
    }
}

COMPLEX_WORKFLOW_CONFIG = {
    "workflow": {
        "name": "complex_workflow",
        "stages": [
            {"name": "stage1"},
            {"name": "stage2"},
            {"name": "stage3"}
        ]
    }
}


class TestLangGraphCompiledWorkflow:
    """Tests for LangGraphCompiledWorkflow class."""

    def test_init(self):
        """Test initialization of compiled workflow."""
        mock_graph = Mock()
        workflow_config = SIMPLE_WORKFLOW_CONFIG

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=workflow_config
        )

        assert compiled.graph == mock_graph
        assert compiled.workflow_config == workflow_config
        assert compiled.tracker is None

    def test_init_with_tracker(self):
        """Test initialization with tracker."""
        mock_graph = Mock()
        mock_tracker = Mock()
        workflow_config = SIMPLE_WORKFLOW_CONFIG

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=workflow_config,
            tracker=mock_tracker
        )

        assert compiled.tracker == mock_tracker

    def test_invoke(self):
        """Test synchronous invocation."""
        mock_graph = Mock()
        mock_graph.invoke = Mock(return_value={"result": "success"})

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        result = compiled.invoke({"input": "test"})

        assert result == {"result": "success"}
        mock_graph.invoke.assert_called_once()
        call_args = mock_graph.invoke.call_args[0][0]
        assert call_args["input"] == "test"

    def test_invoke_with_tracker(self):
        """Test invocation with tracker injection."""
        mock_graph = Mock()
        mock_tracker = Mock()
        mock_graph.invoke = Mock(return_value={"result": "success"})

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG,
            tracker=mock_tracker
        )

        result = compiled.invoke({"input": "test"})

        # Verify tracker was injected into state
        call_args = mock_graph.invoke.call_args[0][0]
        assert call_args["tracker"] == mock_tracker

    @pytest.mark.asyncio
    async def test_ainvoke(self):
        """Test asynchronous invocation."""
        mock_graph = Mock()

        # Create async mock
        async def async_invoke(state):
            return {"result": "async_success"}

        mock_graph.ainvoke = async_invoke

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        result = await compiled.ainvoke({"input": "test"})

        assert result == {"result": "async_success"}

    def test_extract_stage_names_from_strings(self):
        """Test _extract_stage_names with list of strings."""
        mock_graph = Mock()
        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        stages = ["stage1", "stage2", "stage3"]
        result = compiled._extract_stage_names(stages)

        assert result == ["stage1", "stage2", "stage3"]

    def test_extract_stage_names_from_dicts(self):
        """Test _extract_stage_names with list of dictionaries."""
        mock_graph = Mock()
        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        stages = [
            {"name": "stage1"},
            {"stage_name": "stage2"},  # Alternative key
            {"name": "stage3", "other_field": "value"}
        ]
        result = compiled._extract_stage_names(stages)

        assert result == ["stage1", "stage2", "stage3"]

    def test_extract_stage_names_from_objects(self):
        """Test _extract_stage_names with objects/models."""
        mock_graph = Mock()
        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        # Create proper mock stage objects with spec to control attributes
        stage1 = Mock(spec=['name'])
        stage1.name = "stage1"

        stage2 = Mock(spec=['stage_name'])
        stage2.stage_name = "stage2"  # Alternative attribute

        stage3 = Mock(spec=['name'])
        stage3.name = "stage3"

        stages = [stage1, stage2, stage3]
        result = compiled._extract_stage_names(stages)

        assert result == ["stage1", "stage2", "stage3"]

    def test_extract_stage_names_mixed_formats(self):
        """Test _extract_stage_names with mixed input formats."""
        mock_graph = Mock()
        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        # Mock stage object
        stage_obj = Mock()
        stage_obj.name = "stage3"

        stages = [
            "stage1",                          # String
            {"name": "stage2"},                # Dict
            stage_obj                          # Object
        ]
        result = compiled._extract_stage_names(stages)

        assert result == ["stage1", "stage2", "stage3"]

    def test_extract_stage_names_empty_list(self):
        """Test _extract_stage_names with empty list."""
        mock_graph = Mock()
        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        stages = []
        result = compiled._extract_stage_names(stages)

        assert result == []

    def test_get_metadata_simple(self):
        """Test metadata extraction from simple config."""
        mock_graph = Mock()

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        metadata = compiled.get_metadata()

        assert metadata["engine"] == "langgraph"
        assert metadata["version"] == "0.2.0"
        assert metadata["config"] == SIMPLE_WORKFLOW_CONFIG
        assert metadata["stages"] == ["research", "synthesis"]

    def test_get_metadata_complex(self):
        """Test metadata extraction from complex config."""
        mock_graph = Mock()

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=COMPLEX_WORKFLOW_CONFIG
        )

        metadata = compiled.get_metadata()

        assert metadata["engine"] == "langgraph"
        assert metadata["stages"] == ["stage1", "stage2", "stage3"]

    def test_visualize_simple(self):
        """Test Mermaid diagram generation for simple workflow."""
        mock_graph = Mock()

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=SIMPLE_WORKFLOW_CONFIG
        )

        mermaid = compiled.visualize()

        # Verify Mermaid format
        assert "flowchart TD" in mermaid
        assert "START([Start])" in mermaid
        assert "END([End])" in mermaid
        assert "research[research]" in mermaid
        assert "synthesis[synthesis]" in mermaid
        assert "START --> research" in mermaid
        assert "research --> synthesis" in mermaid
        assert "synthesis --> END" in mermaid

    def test_visualize_complex(self):
        """Test Mermaid diagram generation for complex workflow."""
        mock_graph = Mock()

        compiled = LangGraphCompiledWorkflow(
            graph=mock_graph,
            workflow_config=COMPLEX_WORKFLOW_CONFIG
        )

        mermaid = compiled.visualize()

        assert "flowchart TD" in mermaid
        assert "stage1[stage1]" in mermaid
        assert "stage2[stage2]" in mermaid
        assert "stage3[stage3]" in mermaid
        assert "stage1 --> stage2" in mermaid
        assert "stage2 --> stage3" in mermaid


class TestLangGraphExecutionEngine:
    """Tests for LangGraphExecutionEngine class."""

    def test_init_default(self):
        """Test initialization with defaults."""
        engine = LangGraphExecutionEngine()

        assert engine.compiler is not None
        assert hasattr(engine.compiler, 'compile')

    def test_init_with_dependencies(self):
        """Test initialization with tool registry and config loader."""
        mock_registry = Mock()
        mock_loader = Mock()

        engine = LangGraphExecutionEngine(
            tool_registry=mock_registry,
            config_loader=mock_loader
        )

        assert engine.tool_registry == mock_registry
        assert engine.config_loader == mock_loader

    @patch('src.compiler.langgraph_engine.LangGraphCompiler')
    def test_compile(self, mock_compiler_class):
        """Test workflow compilation."""
        # Setup mock
        mock_compiler_instance = Mock()
        mock_graph = Mock()
        mock_compiler_instance.compile = Mock(return_value=mock_graph)
        mock_compiler_class.return_value = mock_compiler_instance

        engine = LangGraphExecutionEngine()
        compiled = engine.compile(SIMPLE_WORKFLOW_CONFIG)

        # Verify
        assert isinstance(compiled, LangGraphCompiledWorkflow)
        assert compiled.graph == mock_graph
        assert compiled.workflow_config == SIMPLE_WORKFLOW_CONFIG
        mock_compiler_instance.compile.assert_called_once_with(SIMPLE_WORKFLOW_CONFIG)

    def test_execute_sync_mode(self):
        """Test SYNC execution mode."""
        engine = LangGraphExecutionEngine()

        # Create mock compiled workflow
        mock_compiled = Mock(spec=LangGraphCompiledWorkflow)
        mock_compiled.invoke = Mock(return_value={"result": "success"})

        result = engine.execute(
            mock_compiled,
            {"input": "test"},
            mode=ExecutionMode.SYNC
        )

        assert result == {"result": "success"}
        mock_compiled.invoke.assert_called_once_with({"input": "test"})

    def test_execute_async_mode(self):
        """Test ASYNC execution mode."""
        engine = LangGraphExecutionEngine()

        # Create mock compiled workflow with async method
        mock_compiled = Mock(spec=LangGraphCompiledWorkflow)

        async def async_invoke(state):
            return {"result": "async_success"}

        mock_compiled.ainvoke = async_invoke

        # Execute in ASYNC mode (which wraps ainvoke with asyncio.run)
        result = engine.execute(
            mock_compiled,
            {"input": "test"},
            mode=ExecutionMode.ASYNC
        )

        assert result == {"result": "async_success"}

    def test_execute_stream_mode_not_supported(self):
        """Test STREAM mode raises NotImplementedError."""
        engine = LangGraphExecutionEngine()

        mock_compiled = Mock(spec=LangGraphCompiledWorkflow)

        with pytest.raises(NotImplementedError, match="STREAM mode not supported"):
            engine.execute(
                mock_compiled,
                {"input": "test"},
                mode=ExecutionMode.STREAM
            )

    def test_execute_wrong_workflow_type(self):
        """Test execute with wrong CompiledWorkflow type raises TypeError."""
        engine = LangGraphExecutionEngine()

        class FakeWorkflow:
            pass

        fake_workflow = FakeWorkflow()

        with pytest.raises(TypeError, match="Expected LangGraphCompiledWorkflow"):
            engine.execute(fake_workflow, {"input": "test"})

    def test_supports_feature_sequential_stages(self):
        """Test feature detection for sequential_stages."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("sequential_stages") is True

    def test_supports_feature_parallel_stages(self):
        """Test feature detection for parallel_stages."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("parallel_stages") is True

    def test_supports_feature_conditional_routing(self):
        """Test feature detection for conditional_routing."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("conditional_routing") is True

    def test_supports_feature_checkpointing(self):
        """Test feature detection for checkpointing."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("checkpointing") is True

    def test_supports_feature_state_persistence(self):
        """Test feature detection for state_persistence."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("state_persistence") is True

    def test_supports_feature_convergence_detection_not_supported(self):
        """Test that convergence_detection is not supported in M2."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("convergence_detection") is False

    def test_supports_feature_dynamic_stage_injection_not_supported(self):
        """Test that dynamic_stage_injection is not supported in M2."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("dynamic_stage_injection") is False

    def test_supports_feature_nested_workflows_not_supported(self):
        """Test that nested_workflows is not supported in M2."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("nested_workflows") is False

    def test_supports_feature_unknown(self):
        """Test feature detection for unknown feature."""
        engine = LangGraphExecutionEngine()
        assert engine.supports_feature("unknown_feature") is False


class TestIntegration:
    """Integration tests with real LangGraphCompiler."""

    @pytest.fixture
    def mock_config_loader(self):
        """Create mock config loader."""
        loader = Mock()

        # Mock stage config
        loader.load_stage = Mock(return_value={
            "stage": {
                "agents": ["research_agent"]
            }
        })

        # Mock agent config (must match AgentConfig schema structure)
        loader.load_agent = Mock(return_value={
            "agent": {
                "name": "research_agent",
                "description": "Test agent",
                "type": "standard",
                "prompt": {
                    "inline": "Test prompt template"
                },
                "inference": {
                    "provider": "anthropic",
                    "model": "claude-3-5-sonnet-20241022",
                    "temperature": 0.7,
                    "max_tokens": 1000
                },
                "tools": [],
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 3,
                    "fallback": "GracefulDegradation"
                }
            }
        })

        return loader

    @pytest.fixture
    def mock_tool_registry(self):
        """Create mock tool registry."""
        return Mock()

    def test_compile_and_execute_integration(self, mock_config_loader, mock_tool_registry):
        """Test full compile and execute workflow (mocked)."""
        # This test verifies the adapter works end-to-end
        # In practice, this would be tested with real configs in integration tests

        engine = LangGraphExecutionEngine(
            tool_registry=mock_tool_registry,
            config_loader=mock_config_loader
        )

        workflow_config = {
            "workflow": {
                "stages": ["test_stage"]
            }
        }

        # Compile
        with patch('src.compiler.executors.sequential.AgentFactory.create') as mock_create, \
             patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create_p:
            # Mock agent execution
            mock_agent = Mock()
            mock_agent.execute = Mock(return_value=Mock(
                output="test output",
                reasoning="test reasoning",
                tokens=100,
                estimated_cost_usd=0.001,
                tool_calls=[]
            ))
            mock_create.return_value = mock_agent
            mock_create_p.return_value = mock_agent

            compiled = engine.compile(workflow_config)

            # Verify compilation
            assert isinstance(compiled, LangGraphCompiledWorkflow)
            assert compiled.workflow_config == workflow_config

            # Execute
            result = engine.execute(
                compiled,
                {"input": "test input"},
                mode=ExecutionMode.SYNC
            )

            # Verify result has expected structure
            assert "stage_outputs" in result

    def test_metadata_and_visualize_integration(self):
        """Test metadata and visualization work end-to-end."""
        engine = LangGraphExecutionEngine()

        workflow_config = {
            "workflow": {
                "name": "test_workflow",
                "stages": [
                    {"name": "stage1"},
                    {"name": "stage2"}
                ]
            }
        }

        with patch('src.compiler.langgraph_compiler.LangGraphCompiler.compile') as mock_compile:
            mock_graph = Mock()
            mock_compile.return_value = mock_graph

            compiled = engine.compile(workflow_config)

            # Test metadata
            metadata = compiled.get_metadata()
            assert metadata["engine"] == "langgraph"
            assert metadata["stages"] == ["stage1", "stage2"]

            # Test visualization
            mermaid = compiled.visualize()
            assert "flowchart TD" in mermaid
            assert "stage1" in mermaid
            assert "stage2" in mermaid
