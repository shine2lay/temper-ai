"""Tests for DashboardDataService."""

from unittest.mock import MagicMock

from temper_ai.interfaces.dashboard.data_service import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    DashboardDataService,
)


def _make_service(backend=None, event_bus=None) -> DashboardDataService:
    return DashboardDataService(backend=backend, event_bus=event_bus)


class TestModuleConstants:
    """Verify module-level constants."""

    def test_default_page_limit(self) -> None:
        assert DEFAULT_PAGE_LIMIT == 50

    def test_max_page_limit(self) -> None:
        assert MAX_PAGE_LIMIT == 500

    def test_max_greater_than_default(self) -> None:
        assert MAX_PAGE_LIMIT > DEFAULT_PAGE_LIMIT


class TestDashboardDataServiceInit:
    """Tests for DashboardDataService initialization."""

    def test_no_args_creates_service(self) -> None:
        svc = DashboardDataService()
        assert svc._backend is None
        assert svc._event_bus is None

    def test_stores_backend(self) -> None:
        backend = MagicMock()
        svc = DashboardDataService(backend=backend)
        assert svc._backend is backend

    def test_stores_event_bus(self) -> None:
        bus = MagicMock()
        svc = DashboardDataService(event_bus=bus)
        assert svc._event_bus is bus


class TestGetWorkflowSnapshot:
    """Tests for get_workflow_snapshot()."""

    def test_returns_none_when_no_backend(self) -> None:
        svc = _make_service()
        result = svc.get_workflow_snapshot("wf-1")
        assert result is None

    def test_returns_none_when_backend_returns_none(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = None
        svc = _make_service(backend=backend)
        result = svc.get_workflow_snapshot("wf-1")
        assert result is None

    def test_returns_workflow_dict(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {"id": "wf-1", "status": "running"}
        svc = _make_service(backend=backend)
        result = svc.get_workflow_snapshot("wf-1")
        assert result == {"id": "wf-1", "status": "running"}

    def test_filters_by_tenant_id(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {"id": "wf-1", "tenant_id": "tenant-A"}
        svc = _make_service(backend=backend)
        # Wrong tenant
        result = svc.get_workflow_snapshot("wf-1", tenant_id="tenant-B")
        assert result is None

    def test_passes_correct_tenant_id(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {"id": "wf-1", "tenant_id": "tenant-A"}
        svc = _make_service(backend=backend)
        result = svc.get_workflow_snapshot("wf-1", tenant_id="tenant-A")
        assert result is not None

    def test_no_tenant_filter_skips_tenant_check(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {"id": "wf-1", "tenant_id": "any"}
        svc = _make_service(backend=backend)
        result = svc.get_workflow_snapshot("wf-1", tenant_id=None)
        assert result is not None


class TestListWorkflows:
    """Tests for list_workflows()."""

    def test_returns_empty_list_when_no_backend(self) -> None:
        svc = _make_service()
        result = svc.list_workflows()
        assert result == []

    def test_delegates_to_backend(self) -> None:
        backend = MagicMock()
        backend.list_workflows.return_value = [{"id": "wf-1"}, {"id": "wf-2"}]
        svc = _make_service(backend=backend)
        result = svc.list_workflows(limit=10, offset=0)
        assert len(result) == 2
        backend.list_workflows.assert_called_once_with(
            limit=10, offset=0, status=None, tenant_id=None
        )

    def test_passes_filters_to_backend(self) -> None:
        backend = MagicMock()
        backend.list_workflows.return_value = []
        svc = _make_service(backend=backend)
        svc.list_workflows(limit=5, offset=10, status="running", tenant_id="t1")
        backend.list_workflows.assert_called_once_with(
            limit=5, offset=10, status="running", tenant_id="t1"
        )


class TestGetStage:
    """Tests for get_stage()."""

    def test_returns_none_without_backend(self) -> None:
        svc = _make_service()
        assert svc.get_stage("stage-1") is None

    def test_returns_none_when_not_found(self) -> None:
        backend = MagicMock()
        backend.get_stage.return_value = None
        svc = _make_service(backend=backend)
        assert svc.get_stage("stage-1") is None

    def test_returns_stage(self) -> None:
        backend = MagicMock()
        backend.get_stage.return_value = {"id": "stage-1", "status": "completed"}
        svc = _make_service(backend=backend)
        result = svc.get_stage("stage-1")
        assert result["id"] == "stage-1"

    def test_tenant_filter(self) -> None:
        backend = MagicMock()
        backend.get_stage.return_value = {"id": "stage-1", "tenant_id": "A"}
        svc = _make_service(backend=backend)
        assert svc.get_stage("stage-1", tenant_id="B") is None
        assert svc.get_stage("stage-1", tenant_id="A") is not None


class TestGetAgent:
    """Tests for get_agent()."""

    def test_returns_none_without_backend(self) -> None:
        svc = _make_service()
        assert svc.get_agent("agent-1") is None

    def test_returns_agent(self) -> None:
        backend = MagicMock()
        backend.get_agent.return_value = {"id": "agent-1", "tenant_id": "T"}
        svc = _make_service(backend=backend)
        result = svc.get_agent("agent-1", tenant_id="T")
        assert result["id"] == "agent-1"

    def test_tenant_filter_excludes_wrong_tenant(self) -> None:
        backend = MagicMock()
        backend.get_agent.return_value = {"id": "agent-1", "tenant_id": "T1"}
        svc = _make_service(backend=backend)
        assert svc.get_agent("agent-1", tenant_id="T2") is None


class TestGetLlmCall:
    """Tests for get_llm_call()."""

    def test_returns_none_without_backend(self) -> None:
        svc = _make_service()
        assert svc.get_llm_call("llm-1") is None

    def test_returns_llm_call(self) -> None:
        backend = MagicMock()
        backend.get_llm_call.return_value = {"id": "llm-1", "tenant_id": "T"}
        svc = _make_service(backend=backend)
        result = svc.get_llm_call("llm-1", tenant_id="T")
        assert result is not None

    def test_tenant_filter(self) -> None:
        backend = MagicMock()
        backend.get_llm_call.return_value = {"id": "llm-1", "tenant_id": "T"}
        svc = _make_service(backend=backend)
        assert svc.get_llm_call("llm-1", tenant_id="other") is None


class TestGetToolCall:
    """Tests for get_tool_call()."""

    def test_returns_none_without_backend(self) -> None:
        svc = _make_service()
        assert svc.get_tool_call("tool-1") is None

    def test_returns_tool_call(self) -> None:
        backend = MagicMock()
        backend.get_tool_call.return_value = {"id": "tool-1", "tenant_id": "T"}
        svc = _make_service(backend=backend)
        result = svc.get_tool_call("tool-1", tenant_id="T")
        assert result is not None

    def test_tenant_filter_excludes_mismatch(self) -> None:
        backend = MagicMock()
        backend.get_tool_call.return_value = {"id": "tool-1", "tenant_id": "T"}
        svc = _make_service(backend=backend)
        assert svc.get_tool_call("tool-1", tenant_id="other") is None


class TestGetDataFlow:
    """Tests for get_data_flow()."""

    def test_returns_empty_when_no_workflow(self) -> None:
        svc = _make_service()
        result = svc.get_data_flow("wf-missing")
        assert result == {"nodes": [], "edges": []}

    def test_returns_empty_nodes_edges_for_missing(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = None
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_builds_stage_nodes(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {
            "stages": [
                {
                    "id": "s1",
                    "stage_name": "Ingest",
                    "status": "completed",
                    "input_data": {"x": 1},
                    "output_data": {"y": 2},
                    "agents": [],
                }
            ]
        }
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        nodes = result["nodes"]
        assert any(n["id"] == "s1" and n["type"] == "stage" for n in nodes)

    def test_includes_agent_nodes(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {
            "stages": [
                {
                    "id": "s1",
                    "stage_name": "Process",
                    "status": "running",
                    "input_data": None,
                    "output_data": None,
                    "agents": [
                        {
                            "id": "a1",
                            "agent_name": "ResearchAgent",
                            "status": "running",
                            "agent_config_snapshot": {"model": "gpt-4"},
                            "total_tokens": 1000,
                        }
                    ],
                }
            ]
        }
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        nodes = result["nodes"]
        agent_nodes = [n for n in nodes if n["type"] == "agent"]
        assert len(agent_nodes) == 1
        assert agent_nodes[0]["id"] == "a1"
        assert agent_nodes[0]["model"] == "gpt-4"
        assert agent_nodes[0]["parent"] == "s1"

    def test_sequential_edges_between_stages(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {
            "stages": [
                {
                    "id": "s1",
                    "stage_name": "A",
                    "status": "completed",
                    "output_data": {"result": 1},
                    "agents": [],
                    "collaboration_events": [],
                },
                {
                    "id": "s2",
                    "stage_name": "B",
                    "status": "running",
                    "output_data": None,
                    "agents": [],
                    "collaboration_events": [],
                },
            ]
        }
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        edges = result["edges"]
        flow_edges = [e for e in edges if e["type"] == "data_flow"]
        assert len(flow_edges) == 1
        assert flow_edges[0]["from"] == "s1"
        assert flow_edges[0]["to"] == "s2"

    def test_collaboration_edges(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {
            "stages": [
                {
                    "id": "s1",
                    "stage_name": "Collab",
                    "status": "completed",
                    "output_data": None,
                    "agents": [],
                    "collaboration_events": [
                        {
                            "agents_involved": ["a1", "a2"],
                            "event_type": "handoff",
                        }
                    ],
                }
            ]
        }
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        collab_edges = [e for e in result["edges"] if e["type"] == "collaboration"]
        assert len(collab_edges) == 1
        assert collab_edges[0]["from"] == "a1"
        assert collab_edges[0]["to"] == "a2"
        assert collab_edges[0]["label"] == "handoff"

    def test_collaboration_edge_requires_two_agents(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {
            "stages": [
                {
                    "id": "s1",
                    "stage_name": "Solo",
                    "status": "completed",
                    "output_data": None,
                    "agents": [],
                    "collaboration_events": [
                        {"agents_involved": ["a1"], "event_type": "solo"}
                    ],
                }
            ]
        }
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        collab_edges = [e for e in result["edges"] if e["type"] == "collaboration"]
        assert len(collab_edges) == 0

    def test_dag_edges_from_depends_on(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {
            "workflow_config_snapshot": {
                "workflow": {
                    "stages": [
                        {"name": "A", "depends_on": []},
                        {"name": "B", "depends_on": ["A"]},
                    ]
                }
            },
            "stages": [
                {
                    "id": "s1",
                    "stage_name": "A",
                    "status": "completed",
                    "output_data": {"key": "val"},
                    "agents": [],
                    "collaboration_events": [],
                },
                {
                    "id": "s2",
                    "stage_name": "B",
                    "status": "running",
                    "output_data": None,
                    "agents": [],
                    "collaboration_events": [],
                },
            ],
        }
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        flow_edges = [e for e in result["edges"] if e["type"] == "data_flow"]
        # B depends on A, so there should be an edge s1->s2
        assert any(e["from"] == "s1" and e["to"] == "s2" for e in flow_edges)

    def test_node_has_correct_stage_name(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {
            "stages": [
                {
                    "id": "s1",
                    "stage_name": "MyStage",
                    "status": "completed",
                    "input_data": None,
                    "output_data": None,
                    "agents": [],
                }
            ]
        }
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        stage_node = next(n for n in result["nodes"] if n["type"] == "stage")
        assert stage_node["name"] == "MyStage"

    def test_stage_node_missing_id_skipped(self) -> None:
        backend = MagicMock()
        backend.get_workflow.return_value = {
            "stages": [
                {
                    # No 'id' field
                    "stage_name": "Orphan",
                    "status": "unknown",
                    "agents": [],
                }
            ]
        }
        svc = _make_service(backend=backend)
        result = svc.get_data_flow("wf-1")
        assert result["nodes"] == []


class TestAddStageNodes:
    """Tests for _add_stage_nodes static method."""

    def test_adds_stage_node(self) -> None:
        nodes: list = []
        stage = {
            "id": "s1",
            "stage_name": "Fetch",
            "status": "completed",
            "input_data": {"url": "..."},
            "output_data": {"html": "..."},
            "agents": [],
        }
        DashboardDataService._add_stage_nodes(nodes, stage)
        assert len(nodes) == 1
        assert nodes[0]["type"] == "stage"
        assert nodes[0]["has_input"] is True
        assert nodes[0]["has_output"] is True

    def test_skips_stage_without_id(self) -> None:
        nodes: list = []
        DashboardDataService._add_stage_nodes(nodes, {"stage_name": "No ID"})
        assert nodes == []

    def test_adds_agent_nodes_under_stage(self) -> None:
        nodes: list = []
        stage = {
            "id": "s1",
            "stage_name": "Multi",
            "status": "running",
            "input_data": None,
            "output_data": None,
            "agents": [
                {
                    "id": "a1",
                    "agent_name": "Alpha",
                    "status": "running",
                    "agent_config_snapshot": {"model": "gpt-3.5"},
                    "total_tokens": 500,
                    "estimated_cost_usd": 0.01,
                    "num_llm_calls": 3,
                    "num_tool_calls": 1,
                }
            ],
        }
        DashboardDataService._add_stage_nodes(nodes, stage)
        assert len(nodes) == 2
        agent_node = next(n for n in nodes if n["type"] == "agent")
        assert agent_node["id"] == "a1"
        assert agent_node["parent"] == "s1"
        assert agent_node["model"] == "gpt-3.5"

    def test_skips_agent_without_id(self) -> None:
        nodes: list = []
        stage = {
            "id": "s1",
            "stage_name": "X",
            "status": "done",
            "input_data": None,
            "output_data": None,
            "agents": [{"agent_name": "NoId"}],
        }
        DashboardDataService._add_stage_nodes(nodes, stage)
        # Stage node added, agent skipped
        assert len(nodes) == 1
        assert nodes[0]["type"] == "stage"


class TestAddSequentialFlowEdges:
    """Tests for _add_sequential_flow_edges static method."""

    def test_empty_stages_no_edges(self) -> None:
        edges: list = []
        DashboardDataService._add_sequential_flow_edges(edges, [])
        assert edges == []

    def test_single_stage_no_edges(self) -> None:
        edges: list = []
        DashboardDataService._add_sequential_flow_edges(
            edges, [{"id": "s1", "output_data": {}}]
        )
        assert edges == []

    def test_two_stages_one_edge(self) -> None:
        edges: list = []
        stages = [
            {"id": "s1", "output_data": {"k": "v"}},
            {"id": "s2", "output_data": None},
        ]
        DashboardDataService._add_sequential_flow_edges(edges, stages)
        assert len(edges) == 1
        assert edges[0]["from"] == "s1"
        assert edges[0]["to"] == "s2"
        assert edges[0]["type"] == "data_flow"
        assert "k" in edges[0]["data_keys"]

    def test_three_stages_two_edges(self) -> None:
        edges: list = []
        stages = [
            {"id": "s1", "output_data": {}},
            {"id": "s2", "output_data": {}},
            {"id": "s3", "output_data": {}},
        ]
        DashboardDataService._add_sequential_flow_edges(edges, stages)
        assert len(edges) == 2

    def test_skips_edge_when_stage_has_no_id(self) -> None:
        edges: list = []
        stages = [
            {"output_data": {}},  # no id
            {"id": "s2", "output_data": {}},
        ]
        DashboardDataService._add_sequential_flow_edges(edges, stages)
        assert edges == []

    def test_empty_output_data_produces_empty_label(self) -> None:
        edges: list = []
        stages = [
            {"id": "s1", "output_data": {}},
            {"id": "s2", "output_data": None},
        ]
        DashboardDataService._add_sequential_flow_edges(edges, stages)
        assert edges[0]["label"] == ""


class TestSubscribeAndUnsubscribe:
    """Tests for subscribe_workflow() and unsubscribe()."""

    def test_subscribe_returns_none_without_event_bus(self) -> None:
        svc = _make_service()
        result = svc.subscribe_workflow("wf-1", lambda e: None)
        assert result is None

    def test_subscribe_calls_event_bus(self) -> None:
        bus = MagicMock()
        bus.subscribe.return_value = "sub-id-123"
        svc = _make_service(event_bus=bus)
        sub_id = svc.subscribe_workflow("wf-1", lambda e: None)
        assert sub_id == "sub-id-123"
        bus.subscribe.assert_called_once()

    def test_filtered_callback_forwards_matching_events(self) -> None:
        bus = MagicMock()
        captured_callbacks: list = []
        bus.subscribe.side_effect = lambda cb: captured_callbacks.append(cb) or "sid"

        received: list = []
        svc = _make_service(event_bus=bus)
        svc.subscribe_workflow("wf-target", received.append)

        # Simulate event dispatch
        matching_event = MagicMock()
        matching_event.workflow_id = "wf-target"
        other_event = MagicMock()
        other_event.workflow_id = "wf-other"

        cb = captured_callbacks[0]
        cb(matching_event)
        cb(other_event)

        assert len(received) == 1
        assert received[0] is matching_event

    def test_unsubscribe_calls_event_bus(self) -> None:
        bus = MagicMock()
        svc = _make_service(event_bus=bus)
        svc.unsubscribe("sub-id-123")
        bus.unsubscribe.assert_called_once_with("sub-id-123")

    def test_unsubscribe_without_event_bus_is_noop(self) -> None:
        svc = _make_service()
        # Should not raise
        svc.unsubscribe("sub-id-123")

    def test_unsubscribe_empty_id_skips_call(self) -> None:
        bus = MagicMock()
        svc = _make_service(event_bus=bus)
        svc.unsubscribe("")
        bus.unsubscribe.assert_not_called()


class TestExtractDependencyMap:
    """Tests for _extract_dependency_map static method."""

    def test_returns_none_when_no_config_snapshot(self) -> None:
        result = DashboardDataService._extract_dependency_map({})
        assert result is None

    def test_returns_none_when_no_deps(self) -> None:
        wf = {
            "workflow_config_snapshot": {
                "workflow": {
                    "stages": [
                        {"name": "A", "depends_on": []},
                        {"name": "B", "depends_on": []},
                    ]
                }
            }
        }
        result = DashboardDataService._extract_dependency_map(wf)
        assert result is None

    def test_returns_dep_map_when_deps_present(self) -> None:
        wf = {
            "workflow_config_snapshot": {
                "workflow": {
                    "stages": [
                        {"name": "A", "depends_on": []},
                        {"name": "B", "depends_on": ["A"]},
                    ]
                }
            }
        }
        result = DashboardDataService._extract_dependency_map(wf)
        assert result is not None
        assert "dep_map" in result
        assert result["dep_map"]["B"] == ["A"]

    def test_captures_loops_back_to(self) -> None:
        wf = {
            "workflow_config_snapshot": {
                "workflow": {
                    "stages": [
                        {"name": "A", "depends_on": []},
                        {
                            "name": "B",
                            "depends_on": ["A"],
                            "loops_back_to": "A",
                        },
                    ]
                }
            }
        }
        result = DashboardDataService._extract_dependency_map(wf)
        assert result["loops_back_to"]["B"] == "A"

    def test_skips_non_dict_stages(self) -> None:
        wf = {
            "workflow_config_snapshot": {
                "workflow": {
                    "stages": [
                        "not-a-dict",
                        {"name": "B", "depends_on": ["A"]},
                    ]
                }
            }
        }
        result = DashboardDataService._extract_dependency_map(wf)
        assert result is not None
        assert "B" in result["dep_map"]
