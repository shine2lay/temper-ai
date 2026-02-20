"""AutoGen agent adapter for Temper AI plugin system."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar, Dict, List

from temper_ai.plugins.base import ExternalAgentPlugin
from temper_ai.plugins.constants import PLUGIN_DEFAULT_TIMEOUT, PLUGIN_TYPE_AUTOGEN  # noqa: F401

logger = logging.getLogger(__name__)

# AutoGen adapter constants
DEFAULT_AGENT_CLASS = "AssistantAgent"
DEFAULT_MODEL_NAME = "gpt-4o"


class AutoGenAgent(ExternalAgentPlugin):
    """Adapter that wraps an AutoGen agent inside Temper AI workflows.

    AutoGen is async-first; _execute_external() bridges to sync via asyncio.
    """

    FRAMEWORK_NAME: ClassVar[str] = "AutoGen"
    AGENT_TYPE: ClassVar[str] = PLUGIN_TYPE_AUTOGEN
    REQUIRED_PACKAGE: ClassVar[str] = "autogen-agentchat"

    def _initialize_external_agent(self) -> None:
        """Create the AutoGen agent from plugin config."""
        from autogen_agentchat.agents import AssistantAgent  # lazy import
        from autogen_ext.models.openai import OpenAIChatCompletionClient  # lazy import

        pc = self._get_plugin_config()
        agent_class_name = pc.get("agent_class", DEFAULT_AGENT_CLASS)

        if agent_class_name != DEFAULT_AGENT_CLASS:
            logger.warning(
                "Custom agent class '%s' not yet supported, using AssistantAgent",
                agent_class_name,
            )

        mc_config = pc.get("model_client_config", {})
        model_client = OpenAIChatCompletionClient(
            model=mc_config.get("model", DEFAULT_MODEL_NAME),
            **{k: v for k, v in mc_config.items() if k != "model"},
        )
        self._external_agent = AssistantAgent(
            name=self.name,
            model_client=model_client,
            system_message=self.description,
        )

    def _execute_external(self, input_data: Dict[str, Any]) -> str:
        """Execute AutoGen agent (async bridge to sync)."""
        import asyncio

        task = self._extract_task_description(input_data)
        return asyncio.run(self._run_autogen(task))

    async def _run_autogen(self, task: str) -> str:
        """Run AutoGen agent asynchronously."""
        from autogen_agentchat.messages import TextMessage  # lazy import
        from autogen_core import CancellationToken  # lazy import

        response = await self._external_agent.on_messages(
            [TextMessage(content=task, source="user")],
            CancellationToken(),
        )
        if response.chat_message:
            return str(response.chat_message.content)
        return ""

    @classmethod
    def translate_config(cls, source_path: Path) -> List[Dict[str, Any]]:
        """Translate AutoGen config to Temper AI config dicts."""
        from temper_ai.plugins._import_helpers import (
            build_agent_config_dict,
            load_yaml_safe,
        )

        data = load_yaml_safe(source_path)
        configs: List[Dict[str, Any]] = []

        agents = data.get("agents", [data] if "name" in data else [])
        for agent_data in agents:
            plugin_config = {
                "framework": PLUGIN_TYPE_AUTOGEN,
                "agent_class": agent_data.get("agent_class", DEFAULT_AGENT_CLASS),
                "model_client_config": agent_data.get("model_client_config", {}),
                "framework_config": agent_data.get("config", {}),
            }
            config = build_agent_config_dict(
                name=agent_data.get("name", "autogen_agent"),
                description=agent_data.get("system_message", "AutoGen agent"),
                agent_type=PLUGIN_TYPE_AUTOGEN,
                plugin_config=plugin_config,
            )
            configs.append(config)

        return configs
