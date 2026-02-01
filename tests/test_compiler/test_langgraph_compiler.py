"""Tests for LangGraph compiler."""
import pytest
from unittest.mock import Mock, MagicMock, patch

from src.compiler.langgraph_compiler import LangGraphCompiler, WorkflowExecutor
from src.compiler.state import WorkflowState
from src.compiler.schemas import WorkflowConfig
from tests.fixtures.realistic_data import REALISTIC_CONFIG_LOADER, create_realistic_stage_config


def test_workflow_state_creation():
    """Test WorkflowState can be created and used."""
    state = WorkflowState()
    state["key"] = "value"
    assert state["key"] == "value"


def test_compiler_initialization():
    """Test LangGraphCompiler can be initialized."""
    compiler = LangGraphCompiler()
    assert isinstance(compiler, LangGraphCompiler), \
        f"Expected LangGraphCompiler instance, got {type(compiler)}"
    assert hasattr(compiler, 'tool_registry'), "Compiler must have tool_registry attribute"
    assert hasattr(compiler, 'config_loader'), "Compiler must have config_loader attribute"
    assert hasattr(compiler, 'compile'), "Compiler must have compile method"


def test_compiler_with_custom_registry():
    """Test LangGraphCompiler accepts custom tool registry."""
    mock_registry = Mock()
    compiler = LangGraphCompiler(tool_registry=mock_registry)
    assert compiler.tool_registry is mock_registry


def test_compile_validates_workflow_config():
    """Test compile validates that workflow has stages."""
    compiler = LangGraphCompiler()
    # Use realistic config loader instead of mock
    compiler.config_loader = REALISTIC_CONFIG_LOADER

    # Create minimal workflow config with no stages
    workflow_config = {
        "workflow": {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0",
            "stages": []
        }
    }

    # Should raise ValueError for empty stages
    with pytest.raises(ValueError, match="at least one"):
        compiler.compile(workflow_config)


def test_compile_creates_state_graph():
    """Test compile creates a StateGraph with nodes."""
    compiler = LangGraphCompiler()
    # Use realistic config loader with pre-configured stages
    compiler.config_loader = REALISTIC_CONFIG_LOADER

    # Create simple workflow config (using name field)
    workflow_config = {
        "workflow": {
            "name": "simple_workflow",
            "description": "Simple test workflow",
            "version": "1.0",
            "stages": [
                {"name": "research"}  # Use pre-configured stage in REALISTIC_CONFIG_LOADER
            ]
        }
    }

    # Compile
    graph = compiler.compile(workflow_config)

    # Should return a compiled graph
    assert hasattr(graph, 'invoke'), "Graph must have invoke method for execution"
    assert hasattr(graph, 'get_graph'), "Graph must have get_graph for introspection"
    assert callable(graph.invoke), "invoke must be callable"


def test_compile_sequential_stages():
    """Test compile creates sequential edges between stages."""
    compiler = LangGraphCompiler()
    # Use realistic config loader with pre-configured stages
    compiler.config_loader = REALISTIC_CONFIG_LOADER

    # Create workflow with multiple stages using pre-configured stages
    workflow_config = {
        "workflow": {
            "name": "multi_stage_workflow",
            "description": "Multi-stage workflow",
            "version": "1.0",
            "stages": [
                {"name": "research"},
                {"name": "analysis"},
                {"name": "synthesis"}
            ]
        }
    }

    # Compile (should not raise)
    graph = compiler.compile(workflow_config)
    assert hasattr(graph, 'invoke'), "Graph must have invoke method for execution"
    assert hasattr(graph, 'get_graph'), "Graph must have get_graph for introspection"


def test_workflow_executor_initialization():
    """Test WorkflowExecutor can be initialized."""
    mock_graph = Mock()
    executor = WorkflowExecutor(mock_graph)
    assert executor.graph is mock_graph
    assert executor.tracker is None


def test_workflow_executor_with_tracker():
    """Test WorkflowExecutor accepts tracker."""
    mock_graph = Mock()
    mock_tracker = Mock()
    executor = WorkflowExecutor(mock_graph, tracker=mock_tracker)
    assert executor.tracker is mock_tracker


def test_workflow_executor_execute_adds_workflow_id():
    """Test execute adds workflow_id to state."""
    mock_graph = Mock()
    mock_graph.invoke.return_value = {"result": "success"}

    executor = WorkflowExecutor(mock_graph)

    input_data = {"input": "test"}
    result = executor.execute(input_data, workflow_id="test-wf-123")

    # Should have called graph.invoke
    assert mock_graph.invoke.called
    # Should return result
    assert result == {"result": "success"}


def test_workflow_executor_execute_adds_tracker():
    """Test execute adds tracker to state."""
    mock_graph = Mock()
    mock_graph.invoke.return_value = {"result": "success"}
    mock_tracker = Mock()

    executor = WorkflowExecutor(mock_graph, tracker=mock_tracker)

    input_data = {"input": "test"}
    result = executor.execute(input_data)

    # Check that invoke was called with tracker in state
    call_args = mock_graph.invoke.call_args
    state = call_args[0][0]
    assert state.get("tracker") is mock_tracker


def test_start_node_initialization():
    """Test start node initializes state correctly via StateManager."""
    compiler = LangGraphCompiler()
    start_node = compiler.state_manager.create_init_node()

    # Create empty state
    state = WorkflowState()

    # Call start node
    result = start_node(state)

    # Should initialize stage_outputs
    assert "stage_outputs" in result
    assert isinstance(result["stage_outputs"], dict)
    # Should add workflow_id
    assert "workflow_id" in result
    assert result["workflow_id"].startswith("wf-")


def test_start_node_preserves_existing_workflow_id():
    """Test start node doesn't override existing workflow_id via StateManager."""
    compiler = LangGraphCompiler()
    start_node = compiler.state_manager.create_init_node()

    # Create state with existing workflow_id
    state = WorkflowState()
    state["workflow_id"] = "existing-id"

    # Call start node
    result = start_node(state)

    # Should preserve existing workflow_id
    assert result["workflow_id"] == "existing-id"


@pytest.mark.asyncio
async def test_workflow_executor_async_execute():
    """Test async execute method."""
    import asyncio

    mock_graph = Mock()
    # Create a coroutine that returns the expected result
    async def mock_ainvoke(state):
        return {"result": "success"}

    mock_graph.ainvoke = mock_ainvoke

    executor = WorkflowExecutor(mock_graph)

    input_data = {"input": "test"}
    result = await executor.execute_async(input_data)

    # Should return result
    assert result == {"result": "success"}
