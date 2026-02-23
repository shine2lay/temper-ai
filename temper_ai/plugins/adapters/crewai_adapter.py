"""CrewAI agent adapter for Temper AI plugin system."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, ClassVar

from temper_ai.plugins.base import ExternalAgentPlugin
from temper_ai.plugins.constants import (  # noqa: F401
    PLUGIN_DEFAULT_TIMEOUT,
    PLUGIN_TYPE_CREWAI,
)

logger = logging.getLogger(__name__)

# CrewAI adapter constants
CREWAI_DEFAULT_VERBOSE = False
CREWAI_DEFAULT_DELEGATION = False
CREWAI_EXPECTED_OUTPUT = "Complete response"


class CrewAIAgent(ExternalAgentPlugin):
    """Adapter that wraps a CrewAI Agent inside Temper AI workflows."""

    FRAMEWORK_NAME: ClassVar[str] = "CrewAI"
    AGENT_TYPE: ClassVar[str] = PLUGIN_TYPE_CREWAI
    REQUIRED_PACKAGE: ClassVar[str] = "crewai"

    async def health_check(self) -> dict[str, Any]:
        """Check if crewai package is importable and return its version."""
        spec = importlib.util.find_spec("crewai")
        if spec is None:
            return {"status": "unavailable", "framework": self.FRAMEWORK_NAME}
        try:
            import crewai

            version = getattr(crewai, "__version__", "unknown")
        except ImportError:
            version = "unknown"
        return {"status": "ok", "framework": self.FRAMEWORK_NAME, "version": version}

    def _initialize_external_agent(self) -> None:
        """Create the underlying CrewAI Agent from plugin config."""
        import crewai  # lazy import — crewai is optional

        pc = self._get_plugin_config()
        self._external_agent = crewai.Agent(
            role=pc.get("role", self.name),
            goal=pc.get("goal", self.description),
            backstory=pc.get("backstory", ""),
            allow_delegation=pc.get("allow_delegation", CREWAI_DEFAULT_DELEGATION),
            verbose=pc.get("verbose", CREWAI_DEFAULT_VERBOSE),
        )

    def _execute_external(self, input_data: dict[str, Any]) -> str:
        """Execute CrewAI agent via Crew.kickoff()."""
        import crewai  # lazy import — crewai is optional

        task_desc = self._extract_task_description(input_data)
        pc = self._get_plugin_config()
        task = crewai.Task(
            description=task_desc,
            agent=self._external_agent,
            expected_output=CREWAI_EXPECTED_OUTPUT,
        )
        crew = crewai.Crew(
            agents=[self._external_agent],
            tasks=[task],
            verbose=pc.get("verbose", CREWAI_DEFAULT_VERBOSE),
        )
        result = crew.kickoff()
        return str(result)

    @classmethod
    def translate_config(cls, source_path: Path) -> list[dict[str, Any]]:
        """Translate CrewAI YAML config to Temper AI config dicts."""
        from temper_ai.plugins._import_helpers import (
            build_agent_config_dict,
            load_yaml_safe,
        )

        data = load_yaml_safe(source_path)
        configs: list[dict[str, Any]] = []

        agents = data.get("agents", [data] if "role" in data else [])
        for agent_data in agents:
            plugin_config = {
                "framework": PLUGIN_TYPE_CREWAI,
                "role": agent_data.get("role", "agent"),
                "goal": agent_data.get("goal", ""),
                "backstory": agent_data.get("backstory", ""),
                "allow_delegation": agent_data.get(
                    "allow_delegation", CREWAI_DEFAULT_DELEGATION
                ),
                "verbose": agent_data.get("verbose", CREWAI_DEFAULT_VERBOSE),
            }
            config = build_agent_config_dict(
                name=agent_data.get("role", "crewai_agent"),
                description=agent_data.get("goal", "CrewAI agent"),
                agent_type=PLUGIN_TYPE_CREWAI,
                plugin_config=plugin_config,
            )
            configs.append(config)

        return configs
