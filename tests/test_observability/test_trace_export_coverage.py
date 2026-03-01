"""Tests for trace_export.py to cover uncovered lines."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from temper_ai.observability.trace_export import (
    _build_agent_node,
    _build_llm_node,
    _build_stage_node,
    _build_tool_node,
    export_waterfall_trace,
)


def _make_mock_llm(
    id: str = "llm-1",
    provider: str = "openai",
    model: str = "gpt-4",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    latency_ms: int = 500,
    status: str = "success",
    total_tokens: int = 300,
    prompt_tokens: int = 200,
    completion_tokens: int = 100,
    estimated_cost_usd: float = 0.01,
    temperature: float = 0.7,
) -> MagicMock:
    """Create a mock LLM call record."""
    if start_time is None:
        start_time = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    if end_time is None:
        end_time = datetime(2024, 1, 1, 0, 0, 2, tzinfo=UTC)

    mock = MagicMock()
    mock.id = id
    mock.provider = provider
    mock.model = model
    mock.start_time = start_time
    mock.end_time = end_time
    mock.latency_ms = latency_ms
    mock.status = status
    mock.total_tokens = total_tokens
    mock.prompt_tokens = prompt_tokens
    mock.completion_tokens = completion_tokens
    mock.estimated_cost_usd = estimated_cost_usd
    mock.temperature = temperature
    return mock


def _make_mock_tool(
    id: str = "tool-1",
    tool_name: str = "web_search",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    duration_seconds: float = 1.0,
    status: str = "success",
    tool_version: str = "1.0",
    input_params: dict | None = None,
    safety_checks_applied: list | None = None,
) -> MagicMock:
    """Create a mock tool execution record."""
    if start_time is None:
        start_time = datetime(2024, 1, 1, 0, 0, 2, tzinfo=UTC)
    if end_time is None:
        end_time = datetime(2024, 1, 1, 0, 0, 3, tzinfo=UTC)

    mock = MagicMock()
    mock.id = id
    mock.tool_name = tool_name
    mock.start_time = start_time
    mock.end_time = end_time
    mock.duration_seconds = duration_seconds
    mock.status = status
    mock.tool_version = tool_version
    mock.input_params = input_params or {}
    mock.safety_checks_applied = safety_checks_applied or []
    return mock


def _make_mock_agent(
    id: str = "agent-1",
    agent_name: str = "researcher",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    duration_seconds: float = 3.0,
    status: str = "completed",
    total_tokens: int = 500,
    estimated_cost_usd: float = 0.05,
    num_llm_calls: int = 2,
    num_tool_calls: int = 1,
    llm_duration_seconds: float = 2.0,
    tool_duration_seconds: float = 1.0,
) -> MagicMock:
    """Create a mock agent execution record."""
    if start_time is None:
        start_time = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    if end_time is None:
        end_time = datetime(2024, 1, 1, 0, 0, 4, tzinfo=UTC)

    mock = MagicMock()
    mock.id = id
    mock.agent_name = agent_name
    mock.start_time = start_time
    mock.end_time = end_time
    mock.duration_seconds = duration_seconds
    mock.status = status
    mock.total_tokens = total_tokens
    mock.estimated_cost_usd = estimated_cost_usd
    mock.num_llm_calls = num_llm_calls
    mock.num_tool_calls = num_tool_calls
    mock.llm_duration_seconds = llm_duration_seconds
    mock.tool_duration_seconds = tool_duration_seconds
    return mock


def _make_mock_stage(
    id: str = "stage-1",
    stage_name: str = "analysis",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    duration_seconds: float = 5.0,
    status: str = "completed",
    num_agents_executed: int = 1,
    collaboration_rounds: int = 0,
) -> MagicMock:
    """Create a mock stage execution record."""
    if start_time is None:
        start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    if end_time is None:
        end_time = datetime(2024, 1, 1, 0, 0, 5, tzinfo=UTC)

    mock = MagicMock()
    mock.id = id
    mock.stage_name = stage_name
    mock.start_time = start_time
    mock.end_time = end_time
    mock.duration_seconds = duration_seconds
    mock.status = status
    mock.num_agents_executed = num_agents_executed
    mock.collaboration_rounds = collaboration_rounds
    return mock


def _make_mock_workflow(
    id: str = "wf-1",
    workflow_name: str = "test-workflow",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    duration_seconds: float = 10.0,
    status: str = "completed",
    total_tokens: int = 1000,
    total_cost_usd: float = 0.50,
    total_llm_calls: int = 5,
    total_tool_calls: int = 2,
    environment: str = "test",
) -> MagicMock:
    """Create a mock workflow execution record."""
    if start_time is None:
        start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    if end_time is None:
        end_time = datetime(2024, 1, 1, 0, 0, 10, tzinfo=UTC)

    mock = MagicMock()
    mock.id = id
    mock.workflow_name = workflow_name
    mock.start_time = start_time
    mock.end_time = end_time
    mock.duration_seconds = duration_seconds
    mock.status = status
    mock.total_tokens = total_tokens
    mock.total_cost_usd = total_cost_usd
    mock.total_llm_calls = total_llm_calls
    mock.total_tool_calls = total_tool_calls
    mock.environment = environment
    return mock


class TestBuildLlmNode:
    """Test _build_llm_node."""

    def test_basic_llm_node(self):
        llm = _make_mock_llm()
        node = _build_llm_node(llm, "agent-1")
        assert node["id"] == "llm-1"
        assert node["parent_id"] == "agent-1"
        assert node["type"] == "llm"
        assert node["name"] == "openai/gpt-4"
        assert node["metadata"]["provider"] == "openai"

    def test_llm_node_no_end_time(self):
        llm = _make_mock_llm(end_time=None)
        llm.end_time = None
        node = _build_llm_node(llm, "agent-1")
        assert node["end"] is None

    def test_llm_node_no_latency(self):
        llm = _make_mock_llm(latency_ms=None)
        llm.latency_ms = None
        node = _build_llm_node(llm, "agent-1")
        assert node["duration"] is None


class TestBuildToolNode:
    """Test _build_tool_node."""

    def test_basic_tool_node(self):
        tool = _make_mock_tool()
        node = _build_tool_node(tool, "agent-1")
        assert node["id"] == "tool-1"
        assert node["parent_id"] == "agent-1"
        assert node["type"] == "tool"

    def test_tool_node_no_end_time(self):
        tool = _make_mock_tool(end_time=None)
        tool.end_time = None
        node = _build_tool_node(tool, "agent-1")
        assert node["end"] is None


class TestBuildAgentNode:
    """Test _build_agent_node."""

    def test_agent_with_children(self):
        agent = _make_mock_agent()
        llm = _make_mock_llm()
        tool = _make_mock_tool()

        mock_session = MagicMock()
        mock_session.exec.side_effect = [
            MagicMock(all=MagicMock(return_value=[llm])),
            MagicMock(all=MagicMock(return_value=[tool])),
        ]

        with patch("temper_ai.observability.trace_export.select"):
            node = _build_agent_node(agent, "stage-1", mock_session)
            assert node["id"] == "agent-1"
            assert len(node["children"]) == 2

    def test_agent_no_children(self):
        agent = _make_mock_agent()

        mock_session = MagicMock()
        mock_session.exec.side_effect = [
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(all=MagicMock(return_value=[])),
        ]

        with patch("temper_ai.observability.trace_export.select"):
            node = _build_agent_node(agent, "stage-1", mock_session)
            assert len(node["children"]) == 0

    def test_agent_no_end_time(self):
        agent = _make_mock_agent()
        agent.end_time = None

        mock_session = MagicMock()
        mock_session.exec.side_effect = [
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(all=MagicMock(return_value=[])),
        ]

        with patch("temper_ai.observability.trace_export.select"):
            node = _build_agent_node(agent, "stage-1", mock_session)
            assert node["end"] is None


class TestBuildStageNode:
    """Test _build_stage_node."""

    def test_stage_with_agents(self):
        stage = _make_mock_stage()
        agent = _make_mock_agent()

        mock_session = MagicMock()
        # First call: agents for stage, then LLMs for agent, then tools for agent
        mock_session.exec.side_effect = [
            MagicMock(all=MagicMock(return_value=[agent])),
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(all=MagicMock(return_value=[])),
        ]

        with patch("temper_ai.observability.trace_export.select"):
            node = _build_stage_node(stage, "wf-1", mock_session)
            assert node["id"] == "stage-1"
            assert len(node["children"]) == 1


class TestExportWaterfallTrace:
    """Test export_waterfall_trace."""

    def test_workflow_not_found(self):
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = None

        with patch("temper_ai.observability.trace_export.get_session") as mock_get:
            mock_get.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get.return_value.__exit__ = MagicMock(return_value=False)

            with patch("temper_ai.observability.trace_export.select"):
                result = export_waterfall_trace("wf-missing")
                assert "error" in result

    def test_workflow_found(self):
        workflow = _make_mock_workflow()
        stage = _make_mock_stage()

        mock_session = MagicMock()
        mock_session.exec.side_effect = [
            MagicMock(first=MagicMock(return_value=workflow)),  # workflow query
            MagicMock(all=MagicMock(return_value=[stage])),  # stages query
            MagicMock(all=MagicMock(return_value=[])),  # agents for stage
        ]

        with patch("temper_ai.observability.trace_export.get_session") as mock_get:
            mock_get.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get.return_value.__exit__ = MagicMock(return_value=False)

            with (
                patch("temper_ai.observability.trace_export.select"),
                patch(
                    "temper_ai.observability.trace_export._build_stage_node"
                ) as mock_build,
            ):
                mock_build.return_value = {
                    "id": "stage-1",
                    "parent_id": "wf-1",
                    "name": "analysis",
                    "type": "stage",
                    "start": "2024-01-01T00:00:00+00:00",
                    "end": "2024-01-01T00:00:05+00:00",
                    "duration": 5.0,
                    "status": "completed",
                    "metadata": {},
                    "children": [],
                }
                result = export_waterfall_trace("wf-1")
                assert result["id"] == "wf-1"
                assert result["type"] == "workflow"
                assert len(result["children"]) == 1
