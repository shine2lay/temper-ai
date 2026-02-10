"""Bridge between backend DB, event bus, and API/WebSocket."""
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class DashboardDataService:
    """Provides query methods and event subscriptions for the dashboard.

    Wraps an ObservabilityBackend (for reads) and an ObservabilityEventBus
    (for real-time streaming).  Both are optional -- when absent the service
    returns empty/None results gracefully.
    """

    def __init__(self, backend=None, event_bus=None):
        self._backend = backend
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_workflow_snapshot(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Full workflow state from DB."""
        if self._backend is None:
            return None
        return self._backend.get_workflow(workflow_id)

    def list_workflows(
        self, limit: int = 50, offset: int = 0, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if self._backend is None:
            return []
        return self._backend.list_workflows(limit=limit, offset=offset, status=status)

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
        if self._backend is None:
            return None
        return self._backend.get_stage(stage_id)

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        if self._backend is None:
            return None
        return self._backend.get_agent(agent_id)

    def get_llm_call(self, llm_call_id: str) -> Optional[Dict[str, Any]]:
        if self._backend is None:
            return None
        return self._backend.get_llm_call(llm_call_id)

    def get_tool_call(self, tool_call_id: str) -> Optional[Dict[str, Any]]:
        if self._backend is None:
            return None
        return self._backend.get_tool_call(tool_call_id)

    def get_data_flow(self, workflow_id: str) -> Dict[str, Any]:
        """Extract data flow between stages, including agent nodes and collaboration edges."""
        workflow = self.get_workflow_snapshot(workflow_id)
        if not workflow:
            return {"nodes": [], "edges": []}

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        stages = workflow.get("stages", [])

        for i, stage in enumerate(stages):
            nodes.append(
                {
                    "id": stage["id"],
                    "name": stage["stage_name"],
                    "type": "stage",
                    "status": stage.get("status"),
                    "has_input": stage.get("input_data") is not None,
                    "has_output": stage.get("output_data") is not None,
                }
            )

            # Agent nodes as children of this stage
            for agent in stage.get("agents", []):
                agent_id = agent.get("id")
                if not agent_id:
                    continue
                config_snapshot = agent.get("agent_config_snapshot") or {}
                nodes.append(
                    {
                        "id": agent_id,
                        "name": agent.get("agent_name", "agent"),
                        "type": "agent",
                        "parent": stage["id"],
                        "status": agent.get("status"),
                        "model": config_snapshot.get("model"),
                        "total_tokens": agent.get("total_tokens"),
                        "estimated_cost_usd": agent.get("estimated_cost_usd"),
                        "num_llm_calls": agent.get("num_llm_calls"),
                        "num_tool_calls": agent.get("num_tool_calls"),
                    }
                )

            # Collaboration edges within stage
            for event in stage.get("collaboration_events", []):
                agents_involved = event.get("agents_involved", [])
                if len(agents_involved) >= 2:
                    edges.append(
                        {
                            "from": agents_involved[0],
                            "to": agents_involved[1],
                            "type": "collaboration",
                            "label": event.get("event_type", ""),
                        }
                    )

            # Connect stages sequentially
            if i > 0:
                prev_output = stages[i - 1].get("output_data") or {}
                data_keys = list(prev_output.keys())
                edges.append(
                    {
                        "from": stages[i - 1]["id"],
                        "to": stage["id"],
                        "type": "data_flow",
                        "data_keys": data_keys,
                        "label": ", ".join(data_keys) if data_keys else "",
                    }
                )

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Event-bus helpers
    # ------------------------------------------------------------------

    def subscribe_workflow(
        self, workflow_id: str, callback: Callable
    ) -> Optional[str]:
        """Subscribe to events for a specific workflow via event bus."""
        if self._event_bus is None:
            return None

        def filtered_callback(event):
            if event.workflow_id == workflow_id:
                callback(event)

        return self._event_bus.subscribe(filtered_callback)

    def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from event bus."""
        if self._event_bus and subscription_id:
            self._event_bus.unsubscribe(subscription_id)
