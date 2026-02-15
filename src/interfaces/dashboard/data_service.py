"""Bridge between backend DB, event bus, and API/WebSocket."""
import logging
from typing import Any, Callable, Dict, List, Optional

from src.observability.constants import ObservabilityFields

logger = logging.getLogger(__name__)

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 500


class DashboardDataService:
    """Provides query methods and event subscriptions for the dashboard.

    Wraps an ObservabilityBackend (for reads) and an ObservabilityEventBus
    (for real-time streaming).  Both are optional -- when absent the service
    returns empty/None results gracefully.
    """

    def __init__(self, backend: Any = None, event_bus: Any = None) -> None:
        self._backend = backend
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_workflow_snapshot(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Full workflow state from DB."""
        if self._backend is None:
            return None
        return self._backend.get_workflow(workflow_id)  # type: ignore

    def list_workflows(
        self, limit: int = DEFAULT_PAGE_LIMIT, offset: int = 0, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List workflow executions with optional filtering."""
        if self._backend is None:
            return []
        return self._backend.list_workflows(limit=limit, offset=offset, status=status)  # type: ignore

    def get_workflow_trace(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Hierarchical trace tree, reusing export_waterfall logic."""
        if self._backend is None:
            return None
        try:
            from examples.export_waterfall import export_waterfall_trace

            trace = export_waterfall_trace(workflow_id)
            if "error" in trace:
                return None
            return trace
        except (ImportError, RuntimeError):
            # ImportError: export_waterfall not available
            # RuntimeError: Database not initialized (uses direct DB access)
            return self.get_workflow_snapshot(workflow_id)

    def get_stage(self, stage_id: str) -> Optional[Dict[str, Any]]:
        """Get stage execution by ID."""
        if self._backend is None:
            return None
        return self._backend.get_stage(stage_id)  # type: ignore

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent execution by ID."""
        if self._backend is None:
            return None
        return self._backend.get_agent(agent_id)  # type: ignore

    def get_llm_call(self, llm_call_id: str) -> Optional[Dict[str, Any]]:
        """Get LLM call by ID."""
        if self._backend is None:
            return None
        return self._backend.get_llm_call(llm_call_id)  # type: ignore

    def get_tool_call(self, tool_call_id: str) -> Optional[Dict[str, Any]]:
        """Get tool call by ID."""
        if self._backend is None:
            return None
        return self._backend.get_tool_call(tool_call_id)  # type: ignore

    def get_data_flow(self, workflow_id: str) -> Dict[str, Any]:
        """Extract data flow between stages, including agent nodes and collaboration edges."""
        workflow = self.get_workflow_snapshot(workflow_id)
        if not workflow:
            return {"nodes": [], "edges": []}

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        stages = workflow.get("stages", [])

        for stage in stages:
            self._add_stage_nodes(nodes, stage)
            self._add_collaboration_edges(edges, stage)

        # Build data flow edges (DAG-aware when depends_on available)
        dag_info = self._extract_dependency_map(workflow)
        if dag_info:
            self._add_dag_flow_edges(edges, stages, dag_info)
        else:
            self._add_sequential_flow_edges(edges, stages)

        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _add_stage_nodes(nodes: List[Dict[str, Any]], stage: Dict[str, Any]) -> None:
        """Add stage and agent nodes to the node list."""
        stage_id = stage.get("id")
        if not stage_id:
            return
        nodes.append({
            "id": stage_id,
            "name": stage.get("stage_name", ""),
            "type": "stage",
            ObservabilityFields.STATUS: stage.get(ObservabilityFields.STATUS),
            "has_input": stage.get(ObservabilityFields.INPUT_DATA) is not None,
            "has_output": stage.get(ObservabilityFields.OUTPUT_DATA) is not None,
        })
        for agent in stage.get("agents", []):
            agent_id = agent.get("id")
            if not agent_id:
                continue
            config_snapshot = agent.get("agent_config_snapshot") or {}
            nodes.append({
                "id": agent_id,
                "name": agent.get(ObservabilityFields.AGENT_NAME, "agent"),
                "type": "agent",
                "parent": stage_id,
                ObservabilityFields.STATUS: agent.get(ObservabilityFields.STATUS),
                "model": config_snapshot.get("model"),
                ObservabilityFields.TOTAL_TOKENS: agent.get(ObservabilityFields.TOTAL_TOKENS),
                "estimated_cost_usd": agent.get("estimated_cost_usd"),
                "num_llm_calls": agent.get("num_llm_calls"),
                "num_tool_calls": agent.get("num_tool_calls"),
            })

    @staticmethod
    def _add_collaboration_edges(
        edges: List[Dict[str, Any]], stage: Dict[str, Any],
    ) -> None:
        """Add collaboration edges from stage events."""
        for event in stage.get("collaboration_events", []):
            agents_involved = event.get("agents_involved", [])
            if len(agents_involved) >= 2:
                edges.append({
                    "from": agents_involved[0],
                    "to": agents_involved[1],
                    "type": "collaboration",
                    "label": event.get("event_type", ""),
                })

    @staticmethod
    def _extract_dependency_map(
        workflow: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Extract DAG info from workflow config snapshot.

        Returns dict with 'dep_map' and 'loops_back_to', or None if no
        stage uses depends_on (sequential fallback).
        """
        config_snap = workflow.get("workflow_config_snapshot")
        if not config_snap:
            return None

        wf_config = config_snap.get("workflow", config_snap)
        config_stages = wf_config.get("stages", [])

        dep_map: Dict[str, List[str]] = {}
        loops_back_to: Dict[str, str] = {}
        has_deps = False
        for cs in config_stages:
            if not isinstance(cs, dict):
                continue
            name = cs.get("name", "")
            if not name:
                continue
            deps = cs.get("depends_on", [])
            dep_map[name] = deps
            if deps:
                has_deps = True
            loop_target = cs.get("loops_back_to")
            if loop_target:
                loops_back_to[name] = loop_target

        if not has_deps:
            return None
        return {"dep_map": dep_map, "loops_back_to": loops_back_to}

    @staticmethod
    def _add_dependency_edges(
        edges: List[Dict[str, Any]],
        stage_id: str,
        deps: List[str],
        name_to_latest: Dict[str, Dict[str, Any]],
    ) -> None:
        """Add edges from dependencies to current stage.

        Args:
            edges: List of edges to append to.
            stage_id: Current stage ID.
            deps: List of dependency stage names.
            name_to_latest: Map of stage names to their latest execution.
        """
        for dep_name in deps:
            dep_stage = name_to_latest.get(dep_name)
            if not dep_stage:
                continue
            dep_output = dep_stage.get(ObservabilityFields.OUTPUT_DATA) or {}
            data_keys = list(dep_output.keys())
            edges.append({
                "from": dep_stage["id"],
                "to": stage_id,
                "type": "data_flow",
                "data_keys": data_keys,
                "label": ", ".join(data_keys) if data_keys else "",
            })

    @staticmethod
    def _add_loop_back_edges(
        edges: List[Dict[str, Any]],
        stage_id: str,
        name: str,
        loops_back_to: Dict[str, str],
        name_to_latest: Dict[str, Dict[str, Any]],
    ) -> None:
        """Add loop-back edges if this stage is a loop target.

        Args:
            edges: List of edges to append to.
            stage_id: Current stage ID.
            name: Current stage name.
            loops_back_to: Map of source stage names to loop targets.
            name_to_latest: Map of stage names to their latest execution.
        """
        for src_name, target in loops_back_to.items():
            if target != name:
                continue
            src_stage = name_to_latest.get(src_name)
            if not src_stage or src_stage["id"] == stage_id:
                continue
            edges.append({
                "from": src_stage["id"],
                "to": stage_id,
                "type": "data_flow",
                "data_keys": [],
                "label": "loop",
            })

    @staticmethod
    def _add_dag_flow_edges(
        edges: List[Dict[str, Any]],
        stages: List[Dict[str, Any]],
        dag_info: Dict[str, Any],
    ) -> None:
        """Add data flow edges based on DAG depends_on relationships."""
        dep_map = dag_info["dep_map"]
        loops_back_to = dag_info["loops_back_to"]
        name_to_latest: Dict[str, Dict[str, Any]] = {}
        seen_names: set = set()

        for stage in stages:
            stage_id = stage.get("id")
            if not stage_id:
                continue
            name = stage.get("stage_name", "")
            deps = dep_map.get(name, [])

            # Add edges from dependencies
            DashboardDataService._add_dependency_edges(
                edges, stage_id, deps, name_to_latest
            )

            # Add loop-back edge if this name already appeared
            if name in seen_names:
                DashboardDataService._add_loop_back_edges(
                    edges, stage_id, name, loops_back_to, name_to_latest
                )

            seen_names.add(name)
            name_to_latest[name] = stage

    @staticmethod
    def _add_sequential_flow_edges(
        edges: List[Dict[str, Any]], stages: List[Dict[str, Any]],
    ) -> None:
        """Add sequential data flow edges (fallback when no depends_on)."""
        for i in range(1, len(stages)):
            prev_id = stages[i - 1].get("id")
            curr_id = stages[i].get("id")
            if not prev_id or not curr_id:
                continue
            prev_output = stages[i - 1].get(ObservabilityFields.OUTPUT_DATA) or {}
            data_keys = list(prev_output.keys())
            edges.append({
                "from": prev_id,
                "to": curr_id,
                "type": "data_flow",
                "data_keys": data_keys,
                "label": ", ".join(data_keys) if data_keys else "",
            })

    # ------------------------------------------------------------------
    # Event-bus helpers
    # ------------------------------------------------------------------

    def subscribe_workflow(
        self, workflow_id: str, callback: Callable
    ) -> Optional[str]:
        """Subscribe to events for a specific workflow via event bus."""
        if self._event_bus is None:
            return None

        def filtered_callback(event: Any) -> None:
            """Forward events matching the target workflow."""
            if event.workflow_id == workflow_id:
                callback(event)

        return self._event_bus.subscribe(filtered_callback)  # type: ignore

    def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from event bus."""
        if self._event_bus and subscription_id:
            self._event_bus.unsubscribe(subscription_id)
