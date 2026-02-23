"""Plugin configuration schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PluginConfig(BaseModel):
    """Base plugin configuration for external framework agents."""

    framework: str = Field(description="External framework name (e.g., 'crewai')")
    framework_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Framework-specific configuration passed to the adapter",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the plugin",
    )


class CrewAIPluginConfig(PluginConfig):
    """CrewAI-specific plugin configuration."""

    framework: str = "crewai"
    role: str = Field(description="CrewAI agent role")
    goal: str = Field(description="CrewAI agent goal")
    backstory: str = Field(default="", description="CrewAI agent backstory")
    allow_delegation: bool = Field(default=False)
    verbose: bool = Field(default=False)


class LangGraphPluginConfig(PluginConfig):
    """LangGraph-specific plugin configuration."""

    framework: str = "langgraph"
    graph_module: str = Field(
        description="Python module path containing compiled graph"
    )
    state_schema: str | None = Field(
        default=None,
        description="Dotted path to state TypedDict class",
    )
    input_key: str = Field(
        default="input", description="Key for task input in graph state"
    )
    output_key: str = Field(
        default="output", description="Key for result in graph state"
    )


class OpenAIAgentsPluginConfig(PluginConfig):
    """OpenAI Agents SDK plugin configuration."""

    framework: str = "openai_agents"
    instructions: str = Field(default="", description="Agent system instructions")
    model: str = Field(default="gpt-4o", description="OpenAI model to use")


class AutoGenPluginConfig(PluginConfig):
    """AutoGen plugin configuration."""

    model_config = ConfigDict(protected_namespaces=())

    framework: str = "autogen"
    agent_class: str = Field(
        default="AssistantAgent",
        description="AutoGen agent class name",
    )
    model_client_config: dict[str, Any] = Field(
        default_factory=dict,
        description="AutoGen model client configuration",
    )
