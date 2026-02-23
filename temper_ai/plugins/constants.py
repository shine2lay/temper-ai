"""Constants for the plugin system."""

# Plugin type identifiers (used in agent config type field)
PLUGIN_TYPE_CREWAI = "crewai"
PLUGIN_TYPE_LANGGRAPH = "langgraph"
PLUGIN_TYPE_OPENAI_AGENTS = "openai_agents"
PLUGIN_TYPE_AUTOGEN = "autogen"

ALL_PLUGIN_TYPES = frozenset(
    {
        PLUGIN_TYPE_CREWAI,
        PLUGIN_TYPE_LANGGRAPH,
        PLUGIN_TYPE_OPENAI_AGENTS,
        PLUGIN_TYPE_AUTOGEN,
    }
)

# Timeout for external framework execution (seconds)
PLUGIN_DEFAULT_TIMEOUT = 600

# Config key names
PLUGIN_CONFIG_KEY = "plugin_config"
FRAMEWORK_CONFIG_KEY = "framework_config"
