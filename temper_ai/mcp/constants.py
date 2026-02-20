"""Constants for MCP integration."""

# Namespace separator for tool names: e.g. github__create_pr
MCP_NAMESPACE_SEPARATOR = "__"

# Connection timeouts (seconds)
MCP_DEFAULT_CONNECT_TIMEOUT = 30
MCP_DEFAULT_CALL_TIMEOUT = 120
MCP_SESSION_INIT_TIMEOUT = 10

# Limits
MCP_MAX_SERVERS = 20

# Background event loop thread name
MCP_EVENT_LOOP_THREAD_NAME = "mcp-event-loop"
