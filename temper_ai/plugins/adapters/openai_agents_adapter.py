"""OpenAI Agents SDK adapter for Temper AI plugin system."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, ClassVar

from temper_ai.plugins.base import ExternalAgentPlugin
from temper_ai.plugins.constants import (  # noqa: F401
    PLUGIN_DEFAULT_TIMEOUT,
    PLUGIN_TYPE_OPENAI_AGENTS,
)

logger = logging.getLogger(__name__)

# OpenAI Agents adapter constants
DEFAULT_MODEL = "gpt-4o"


class OpenAIAgentsAgent(ExternalAgentPlugin):
    """Adapter that wraps an OpenAI Agents SDK Agent inside Temper AI."""

    FRAMEWORK_NAME: ClassVar[str] = "OpenAI Agents SDK"
    AGENT_TYPE: ClassVar[str] = PLUGIN_TYPE_OPENAI_AGENTS
    REQUIRED_PACKAGE: ClassVar[str] = "openai-agents"

    async def health_check(self) -> dict[str, Any]:
        """Check if openai package is importable and return its version."""
        # openai-agents SDK is imported as the 'agents' module at runtime
        spec = importlib.util.find_spec("openai")
        if spec is None:
            return {"status": "unavailable", "framework": self.FRAMEWORK_NAME}
        try:
            import openai

            version = getattr(openai, "__version__", "unknown")
        except ImportError:
            version = "unknown"
        return {"status": "ok", "framework": self.FRAMEWORK_NAME, "version": version}

    def _initialize_external_agent(self) -> None:
        """Create the OpenAI Agents SDK Agent from plugin config."""
        from agents import Agent  # lazy import from openai-agents package

        pc = self._get_plugin_config()
        self._external_agent = Agent(
            name=self.name,
            instructions=pc.get("instructions", self.description),
            model=pc.get("model", DEFAULT_MODEL),
        )

    def _execute_external(self, input_data: dict[str, Any]) -> str:
        """Execute the OpenAI agent via Runner.run_sync()."""
        from agents import Runner  # lazy import

        task = self._extract_task_description(input_data)
        result = Runner.run_sync(self._external_agent, task)
        return str(result.final_output)

    @classmethod
    def translate_config(cls, source_path: Path) -> list[dict[str, Any]]:
        """Translate OpenAI Agents config to Temper AI config dicts."""
        from temper_ai.plugins._import_helpers import (
            build_agent_config_dict,
            load_yaml_safe,
        )

        data = load_yaml_safe(source_path)
        configs: list[dict[str, Any]] = []

        agents = data.get("agents", [data] if "instructions" in data else [])
        for agent_data in agents:
            plugin_config = {
                "framework": PLUGIN_TYPE_OPENAI_AGENTS,
                "instructions": agent_data.get("instructions", ""),
                "model": agent_data.get("model", DEFAULT_MODEL),
                "framework_config": agent_data.get("config", {}),
            }
            config = build_agent_config_dict(
                name=agent_data.get("name", "openai_agent"),
                description=agent_data.get("instructions", "OpenAI agent")[
                    :100
                ],  # scanner: skip-magic
                agent_type=PLUGIN_TYPE_OPENAI_AGENTS,
                plugin_config=plugin_config,
            )
            configs.append(config)

        return configs
