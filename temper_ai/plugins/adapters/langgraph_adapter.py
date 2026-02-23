"""LangGraph agent adapter for Temper AI plugin system."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, ClassVar

from temper_ai.plugins.base import ExternalAgentPlugin
from temper_ai.plugins.constants import (  # noqa: F401
    PLUGIN_DEFAULT_TIMEOUT,
    PLUGIN_TYPE_LANGGRAPH,
)

logger = logging.getLogger(__name__)

# LangGraph adapter constants
DEFAULT_INPUT_KEY = "input"
DEFAULT_OUTPUT_KEY = "output"
DEFAULT_RECURSION_LIMIT = 25


class LangGraphAgent(ExternalAgentPlugin):
    """Adapter that wraps a pre-compiled LangGraph graph inside Temper AI."""

    FRAMEWORK_NAME: ClassVar[str] = "LangGraph"
    AGENT_TYPE: ClassVar[str] = PLUGIN_TYPE_LANGGRAPH
    REQUIRED_PACKAGE: ClassVar[str] = "langgraph"

    async def health_check(self) -> dict[str, Any]:
        """Check if langgraph package is importable and return its version."""
        spec = importlib.util.find_spec("langgraph")
        if spec is None:
            return {"status": "unavailable", "framework": self.FRAMEWORK_NAME}
        try:
            import langgraph

            version = getattr(langgraph, "__version__", "unknown")
        except ImportError:
            version = "unknown"
        return {"status": "ok", "framework": self.FRAMEWORK_NAME, "version": version}

    def _initialize_external_agent(self) -> None:
        """Load the compiled LangGraph graph from the configured module."""
        pc = self._get_plugin_config()
        graph_module = pc.get("graph_module", "")
        if not graph_module:
            raise ValueError(
                "LangGraph plugin requires 'graph_module' in plugin_config"
            )

        module = importlib.import_module(graph_module)
        graph = getattr(module, "graph", None) or getattr(module, "app", None)
        if graph is None:
            raise ValueError(
                f"Module '{graph_module}' has no 'graph' or 'app' attribute"
            )
        self._external_agent = graph

    def _execute_external(self, input_data: dict[str, Any]) -> str:
        """Invoke the LangGraph graph with task input."""
        pc = self._get_plugin_config()
        input_key = pc.get("input_key", DEFAULT_INPUT_KEY)
        output_key = pc.get("output_key", DEFAULT_OUTPUT_KEY)

        task = self._extract_task_description(input_data)
        state = {input_key: task}

        result = self._external_agent.invoke(
            state,
            config={"recursion_limit": DEFAULT_RECURSION_LIMIT},
        )
        return str(result.get(output_key, result))

    @classmethod
    def translate_config(cls, source_path: Path) -> list[dict[str, Any]]:
        """Translate LangGraph config to Temper AI config dicts."""
        from temper_ai.plugins._import_helpers import (
            build_agent_config_dict,
            load_yaml_safe,
        )

        data = load_yaml_safe(source_path)
        plugin_config = {
            "framework": PLUGIN_TYPE_LANGGRAPH,
            "graph_module": data.get("graph_module", ""),
            "input_key": data.get("input_key", DEFAULT_INPUT_KEY),
            "output_key": data.get("output_key", DEFAULT_OUTPUT_KEY),
            "framework_config": data.get("config", {}),
        }
        config = build_agent_config_dict(
            name=data.get("name", "langgraph_agent"),
            description=data.get("description", "LangGraph agent"),
            agent_type=PLUGIN_TYPE_LANGGRAPH,
            plugin_config=plugin_config,
        )
        return [config]
