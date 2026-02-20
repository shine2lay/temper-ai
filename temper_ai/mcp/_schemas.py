"""MCP configuration schemas."""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from temper_ai.mcp.constants import MCP_DEFAULT_CALL_TIMEOUT, MCP_DEFAULT_CONNECT_TIMEOUT


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server connection.

    Exactly one of ``command`` (stdio transport) or ``url`` (HTTP/SSE transport)
    must be provided.
    """

    name: str = Field(description="Unique server identifier")
    namespace: Optional[str] = Field(
        default=None,
        description="Tool namespace prefix (defaults to name)",
    )
    command: Optional[str] = Field(
        default=None,
        description="Executable for stdio transport",
    )
    args: List[str] = Field(
        default_factory=list,
        description="Arguments for the stdio command",
    )
    url: Optional[str] = Field(
        default=None,
        description="URL for HTTP/SSE transport",
    )
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="Extra environment variables for the server process",
    )
    connect_timeout: int = Field(
        default=MCP_DEFAULT_CONNECT_TIMEOUT,
        gt=0,
        description="Connection timeout in seconds",
    )
    call_timeout: int = Field(
        default=MCP_DEFAULT_CALL_TIMEOUT,
        gt=0,
        description="Tool call timeout in seconds",
    )

    @property
    def effective_namespace(self) -> str:
        """Return the namespace to use for tool prefixing."""
        return self.namespace or self.name

    @model_validator(mode="after")
    def validate_transport(self) -> "MCPServerConfig":
        """Ensure exactly one transport (command or url) is specified."""
        has_command = self.command is not None
        has_url = self.url is not None
        if has_command == has_url:
            raise ValueError(
                "Exactly one of 'command' (stdio) or 'url' (HTTP) must be specified, "
                f"got command={self.command!r}, url={self.url!r}"
            )
        return self
