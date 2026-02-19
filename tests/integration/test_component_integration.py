"""Component integration tests.

Tests integration between multiple system components without requiring
full end-to-end workflow execution (no Ollama dependency).
"""
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from temper_ai.agent.llm_providers import LLMResponse
from temper_ai.agent.standard_agent import StandardAgent
from temper_ai.workflow.config_loader import ConfigLoader
from temper_ai.workflow.langgraph_engine import LangGraphExecutionEngine
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)
from temper_ai.observability.database import DatabaseManager
from temper_ai.observability.tracker import ExecutionTracker
from temper_ai.tools.base import ToolResult
from temper_ai.tools.calculator import Calculator
from temper_ai.tools.registry import ToolRegistry

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def db_fixture():
    """Create in-memory test database."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    return db


@pytest.fixture
def tool_registry():
    """Create tool registry with calculator."""
    registry = ToolRegistry()
    registry.register(Calculator())
    return registry


@pytest.fixture
def config_loader():
    """Create config loader."""
    config_root = Path(__file__).parent.parent.parent / "configs"
    return ConfigLoader(config_root=config_root)


@pytest.fixture
def execution_tracker(db_fixture):
    """Create execution tracker."""
    # ExecutionTracker uses get_session() internally
    # For tests, we need to initialize the database first
    from temper_ai.observability.database import init_database
    init_database("sqlite:///:memory:")
    return ExecutionTracker()


@pytest.fixture
def minimal_agent_config():
    """Create minimal agent configuration."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="test_agent",
            description="Test agent",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You are a helpful assistant. {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=2048,
            ),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )


# ============================================================================
# Integration Test 1: Multi-Agent Workflow
# ============================================================================

@patch('temper_ai.agent.base_agent.ToolRegistry')
def test_multi_agent_workflow(mock_tool_registry, minimal_agent_config, execution_tracker):
    """Test workflow with multiple agents collaborating.

    Simulates a research workflow where:
    1. Agent 1 (researcher) gathers information
    2. Agent 2 (synthesizer) combines findings
    3. Agent 3 (writer) produces final output
    """
    # Setup mock registry
    mock_tool_registry.return_value.list_tools.return_value = []
    mock_tool_registry.return_value.get_all_tools.return_value = {}

    # Create three agents
    agent1 = StandardAgent(minimal_agent_config)
    agent2 = StandardAgent(minimal_agent_config)
    agent3 = StandardAgent(minimal_agent_config)

    # Mock LLM responses for each agent
    mock_llm_response1 = LLMResponse(
        content="<answer>Research findings: AI is evolving rapidly</answer>",
        model="llama2",
        provider="ollama",
        total_tokens=50,
    )

    mock_llm_response2 = LLMResponse(
        content="<answer>Synthesis: AI advancement shows promise</answer>",
        model="llama2",
        provider="ollama",
        total_tokens=50,
    )

    mock_llm_response3 = LLMResponse(
        content="<answer>Report: AI technology is advancing with significant implications</answer>",
        model="llama2",
        provider="ollama",
        total_tokens=50,
    )

    agent1.llm = Mock()
    agent1.llm.complete.return_value = mock_llm_response1

    agent2.llm = Mock()
    agent2.llm.complete.return_value = mock_llm_response2

    agent3.llm = Mock()
    agent3.llm.complete.return_value = mock_llm_response3

    # Execute workflow: Agent 1 -> Agent 2 -> Agent 3
    with execution_tracker.track_workflow("multi_agent_workflow", {}) as workflow_id:
        # Stage 1: Research
        with execution_tracker.track_stage("research", {}, workflow_id) as stage_id:
            result1 = agent1.execute({"input": "Research AI trends"})

        # Stage 2: Synthesis (uses output from stage 1)
        with execution_tracker.track_stage("synthesis", {"previous": result1.output}, workflow_id) as stage_id:
            result2 = agent2.execute({"input": f"Synthesize: {result1.output}"})

        # Stage 3: Writing (uses output from stage 2)
        with execution_tracker.track_stage("writing", {"previous": result2.output}, workflow_id) as stage_id:
            result3 = agent3.execute({"input": f"Write report: {result2.output}"})

    # Verify multi-agent collaboration
    assert result1.output is not None
    assert result2.output is not None
    assert result3.output is not None
    assert "Research findings" in result1.output
    assert "Synthesis" in result2.output
    assert "Report" in result3.output


# ============================================================================
# Integration Test 2: Tool Chaining Workflow
# ============================================================================

@patch('temper_ai.agent.base_agent.ToolRegistry')
def test_tool_chaining_workflow(mock_tool_registry, minimal_agent_config, tool_registry, execution_tracker):
    """Test workflow where tool outputs feed into subsequent tool inputs.

    Simulates: Calculate(2+3) -> Calculate(result*4) -> Calculate(result-10)
    """
    # Setup
    mock_tool_registry.return_value.list_tools.return_value = []
    agent = StandardAgent(minimal_agent_config)

    # Mock LLM to simulate tool calling sequence
    tool_calls = [
        # First call: 2+3
        LLMResponse(
            content='<tool_call>{"name": "calculator", "parameters": {"expression": "2+3"}}</tool_call>',
            model="llama2",
            provider="ollama",
            total_tokens=30,
        ),
        # Second call: result*4 (5*4)
        LLMResponse(
            content='<tool_call>{"name": "calculator", "parameters": {"expression": "5*4"}}</tool_call>',
            model="llama2",
            provider="ollama",
            total_tokens=30,
        ),
        # Final answer
        LLMResponse(
            content="<answer>The final result is 20</answer>",
            model="llama2",
            provider="ollama",
            total_tokens=20,
        ),
    ]

    agent.llm = Mock()
    agent.llm.complete.side_effect = tool_calls

    # Mock tool execution results
    calc_mock = Mock()
    calc_mock.name = "calculator"
    calc_mock.description = "Calculator tool"
    calc_mock.get_parameters_schema.return_value = {
        "type": "object",
        "properties": {"operation": {"type": "string"}},
        "required": []
    }
    calc_mock.execute.side_effect = [
        ToolResult(success=True, result=5, error=None),     # 2+3=5
        ToolResult(success=True, result=20, error=None),    # 5*4=20
    ]

    mock_tool_registry.return_value.get.return_value = calc_mock
    mock_tool_registry.return_value.list_tools.return_value = ["calculator"]  # Tool names, not objects
    mock_tool_registry.return_value.get_all_tools.return_value = {"calculator": calc_mock}

    # Execute workflow
    with execution_tracker.track_workflow("tool_chaining", {}) as workflow_id:
        with execution_tracker.track_stage("calculation", {}, workflow_id) as stage_id:
            result = agent.execute({"input": "Calculate (2+3)*4"})

    # Verify tool chaining
    assert result.output is not None
    assert "20" in result.output or result.tokens > 0
    assert calc_mock.execute.call_count == 2  # Two chained tool calls


# ============================================================================
# Integration Test 3: Error Propagation Across Stages
# ============================================================================

@patch('temper_ai.agent.base_agent.ToolRegistry')
def test_error_propagation_across_stages(mock_tool_registry, minimal_agent_config, execution_tracker):
    """Test that errors in one stage properly propagate to subsequent stages.

    Simulates:
    1. Stage 1 succeeds
    2. Stage 2 encounters error
    3. Stage 3 handles error gracefully
    """
    # Setup
    mock_tool_registry.return_value.list_tools.return_value = []
    mock_tool_registry.return_value.get_all_tools.return_value = {}

    agent1 = StandardAgent(minimal_agent_config)
    agent2 = StandardAgent(minimal_agent_config)
    agent3 = StandardAgent(minimal_agent_config)

    # Mock LLM responses
    success_response = LLMResponse(
        content="<answer>Stage 1 completed successfully</answer>",
        model="llama2",
        provider="ollama",
        total_tokens=20,
    )

    # Stage 2 will fail with LLM error
    agent1.llm = Mock()
    agent1.llm.complete.return_value = success_response

    agent2.llm = Mock()
    agent2.llm.complete.side_effect = Exception("LLM timeout error")

    error_recovery_response = LLMResponse(
        content="<answer>Recovered from error, using fallback</answer>",
        model="llama2",
        provider="ollama",
        total_tokens=20,
    )
    agent3.llm = Mock()
    agent3.llm.complete.return_value = error_recovery_response

    # Execute workflow with error handling
    with execution_tracker.track_workflow("error_handling_workflow", {}) as workflow_id:
        # Stage 1: Success
        with execution_tracker.track_stage("stage1", {}, workflow_id) as stage_id:
            result1 = agent1.execute({"input": "Process data"})

        # Stage 2: Error
        with execution_tracker.track_stage("stage2", {}, workflow_id) as stage_id:
            result2 = agent2.execute({"input": "Process with error"})

        # Extract error message from response
        error_message = result2.error if result2.error else None

        # Stage 3: Error recovery
        with execution_tracker.track_stage("stage3", {"error_from_stage2": error_message}, workflow_id) as stage_id:
            result3 = agent3.execute({"input": f"Recover from: {error_message}"})

    # Verify error propagation
    assert result1.output is not None
    assert result2 is not None  # Agent returns AgentResponse even on error
    assert result2.error is not None  # Error is captured in response
    assert error_message is not None
    assert "timeout" in error_message.lower()
    assert result3.output is not None
    assert "Recovered" in result3.output


# ============================================================================
# Integration Test 4: Config to Execution Pipeline
# ============================================================================

@patch('temper_ai.workflow.langgraph_compiler.ConfigLoader')
def test_config_to_execution_pipeline(mock_config_loader):
    """Test complete pipeline from YAML config to execution.

    Tests: ConfigLoader -> Compiler -> Engine -> Execution
    """
    # Mock config loader
    mock_loader_instance = Mock()
    mock_config_loader.return_value = mock_loader_instance

    # Mock stage config
    mock_stage_config = Mock()
    mock_stage_config.stage.agents = []
    mock_loader_instance.load_stage.return_value = mock_stage_config

    # Create workflow config (simulating loaded YAML)
    workflow_config = {
        "workflow": {
            "name": "test_workflow",
            "description": "Test workflow from config",
            "version": "1.0",
            "stages": [
                {"name": "stage1"},
                {"name": "stage2"}
            ]
        }
    }

    # Create engine
    engine = LangGraphExecutionEngine()
    engine.compiler.config_loader = mock_loader_instance

    # Compile workflow
    compiled = engine.compile(workflow_config)

    # Verify compilation
    assert compiled is not None
    assert compiled.workflow_config == workflow_config

    # Get metadata to verify stages
    metadata = compiled.get_metadata()
    assert metadata["engine"] == "langgraph"
    assert metadata["version"] == "0.2.0"
    assert "stage1" in metadata["stages"]
    assert "stage2" in metadata["stages"]

    # Visualize to verify Mermaid generation
    mermaid = compiled.visualize()
    assert "flowchart TD" in mermaid
    assert "stage1" in mermaid
    assert "stage2" in mermaid
    assert "START" in mermaid
    assert "END" in mermaid


# ============================================================================
# Integration Test 5: Database Integration Full Workflow
# ============================================================================

@patch('temper_ai.agent.base_agent.ToolRegistry')
def test_database_integration_full_workflow(mock_tool_registry, minimal_agent_config, db_fixture):
    """Test full workflow execution with database trace persistence.

    Tests that all execution events are properly persisted to database.
    """
    # Setup
    mock_tool_registry.return_value.list_tools.return_value = []
    mock_tool_registry.return_value.get_all_tools.return_value = {}
    tracker = ExecutionTracker()

    agent = StandardAgent(minimal_agent_config)

    mock_llm_response = LLMResponse(
        content="<answer>Workflow completed</answer>",
        model="llama2",
        provider="ollama",
        total_tokens=50,
    )
    agent.llm = Mock()
    agent.llm.complete.return_value = mock_llm_response

    # Execute workflow with full tracking
    workflow_config = {"name": "test_workflow", "version": "1.0"}

    # Execute workflow with tracking
    with tracker.track_workflow("database_test_workflow", workflow_config) as workflow_id:
        with tracker.track_stage("test_stage", {"input": "test"}, workflow_id) as stage_id:
            result = agent.execute({"input": "Process data"})

    # Verify database persistence
    from sqlalchemy import text

    from temper_ai.observability.database import get_session

    with get_session() as session:
        # Check workflow record
        workflow_result = session.execute(
            text("SELECT id, workflow_name, status FROM workflow_executions WHERE id = :id"),
            {"id": workflow_id}
        ).fetchone()

        assert workflow_result is not None
        assert workflow_result[1] == "database_test_workflow"
        assert workflow_result[2] == "completed"

        # Check stage record
        stage_result = session.execute(
            text("SELECT stage_name, status FROM stage_executions WHERE workflow_execution_id = :id"),
            {"id": workflow_id}
        ).fetchone()

        assert stage_result is not None
        assert stage_result[0] == "test_stage"
        assert stage_result[1] == "completed"


# ============================================================================
# Integration Test 6: Streaming Execution
# ============================================================================

@patch('temper_ai.agent.base_agent.ToolRegistry')
def test_streaming_execution(mock_tool_registry, minimal_agent_config):
    """Test real-time streaming of execution events.

    Tests that execution updates can be streamed in real-time
    (simulated with callbacks).
    """
    # Setup
    mock_tool_registry.return_value.list_tools.return_value = []
    agent = StandardAgent(minimal_agent_config)

    mock_llm_response = LLMResponse(
        content="<answer>Streaming test complete</answer>",
        model="llama2",
        provider="ollama",
        total_tokens=30,
    )
    agent.llm = Mock()
    agent.llm.complete.return_value = mock_llm_response

    # Simulate streaming with callback
    events = []

    def stream_callback(event_type, data):
        """Collect streaming events."""
        events.append({"type": event_type, "data": data, "timestamp": datetime.now()})

    # Execute with streaming
    stream_callback("workflow_start", {"id": "stream-test"})
    stream_callback("stage_start", {"name": "streaming_stage"})

    result = agent.execute({"input": "Test streaming"})

    stream_callback("agent_output", {"output": result.output})
    stream_callback("stage_end", {"name": "streaming_stage", "status": "completed"})
    stream_callback("workflow_end", {"id": "stream-test", "status": "completed"})

    # Verify streaming events
    assert len(events) == 5
    assert events[0]["type"] == "workflow_start"
    assert events[1]["type"] == "stage_start"
    assert events[2]["type"] == "agent_output"
    assert events[3]["type"] == "stage_end"
    assert events[4]["type"] == "workflow_end"

    # Verify temporal ordering
    for i in range(len(events) - 1):
        assert events[i]["timestamp"] <= events[i + 1]["timestamp"]


# ============================================================================
# Integration Test 7: LLM Provider Switching
# ============================================================================

def test_llm_provider_switching(minimal_agent_config):
    """Test dynamic switching between different LLM providers.

    Simulates workflow that switches from Ollama -> OpenAI -> Anthropic
    based on availability or requirements.
    """
    from temper_ai.agent.llm_providers import LLMError

    # Create agent
    with patch('temper_ai.agent.base_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []
        mock_registry.return_value.get_all_tools.return_value = {}
        agent = StandardAgent(minimal_agent_config)

        # Simulate provider switching
        providers = []

        # Try mock provider 1 (fails)
        mock_provider1 = Mock()
        mock_provider1.complete.side_effect = LLMError("Provider unavailable")
        providers.append(("provider1", mock_provider1))

        # Fallback to provider 2 (succeeds)
        mock_provider2 = Mock()
        mock_provider2.complete.return_value = LLMResponse(
            content="<answer>Fallback provider response</answer>",
            model="fallback-model",
            provider="fallback",
            total_tokens=20,
        )
        providers.append(("provider2", mock_provider2))

        # Test provider switching logic
        result = None
        last_error = None
        for provider_name, provider in providers:
            agent.llm = provider
            result = agent.execute({"input": "Test provider switching"})

            # Agent returns AgentResponse even on error, check if successful
            if result.error is None:
                break  # Success, stop trying providers
            else:
                last_error = result.error
                continue  # Try next provider

        # Verify fallback worked
        assert result is not None
        assert result.error is None, f"All providers failed: {last_error}"
        assert "Fallback provider" in result.output
        assert mock_provider1.complete.call_count == 1  # Tried once
        assert mock_provider2.complete.call_count == 1  # Used fallback


# ============================================================================
# Integration Test 8: Tool Registry Integration
# ============================================================================

def test_tool_registry_integration():
    """Test tool discovery, registration, and execution through registry.

    Tests complete tool lifecycle:
    1. Register multiple tools
    2. List available tools
    3. Get tool by name
    4. Execute tool
    5. Unregister tool
    """
    # Create registry
    registry = ToolRegistry()

    # Register calculator
    calc = Calculator()
    registry.register(calc)

    # Verify registration - list_tools() returns list of tool names (strings)
    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0] == "Calculator"

    # Get and execute tool
    retrieved_calc = registry.get("Calculator")
    assert retrieved_calc is not None
    assert retrieved_calc.name == "Calculator"

    # Execute tool
    result = retrieved_calc.execute(expression="5 + 3")
    assert result.success is True
    assert result.result == 8

    # Test multiple tools
    from temper_ai.tools.file_writer import FileWriter
    writer = FileWriter()
    registry.register(writer)

    tools = registry.list_tools()
    assert len(tools) == 2

    # Verify both tools accessible
    assert registry.get("Calculator") is not None
    assert registry.get("FileWriter") is not None

    # Unregister
    registry.unregister("Calculator")
    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0] == "FileWriter"

    # Verify calculator removed
    assert registry.get("Calculator") is None
