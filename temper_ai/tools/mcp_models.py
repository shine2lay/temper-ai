"""Table backing stored MCP OAuth grants.

One row per HTTP MCP server the operator has authorized. The row is what
makes ``temper connect notion`` a one-time act: the authorization code flow
needs a browser and a human, but the refresh token it leaves behind lets
every later run — CLI, API server, container worker — get a fresh access
token on its own.

Both JSON payloads are encrypted before they reach this table (see
``temper_ai/tools/mcp_auth.py``); the columns hold ciphertext, never the
grant itself. ``key_id`` records which key sealed the row so a rotated or
missing key is a clear "re-authorize this server", not a decrypt traceback.
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class MCPCredential(SQLModel, table=True):
    """An authorized MCP server's stored OAuth grant.

    ``server_name`` is the primary key: it matches the ``name`` in the
    server's YAML config, which is already the identifier agents reference
    and the one the CLI takes.
    """

    __tablename__ = "mcp_credentials"

    server_name: str = Field(primary_key=True)
    # Ciphertext of the OAuthToken JSON (access token, refresh token, expiry).
    tokens_encrypted: str
    # Ciphertext of the OAuthClientInformationFull JSON from dynamic client
    # registration. Kept so re-authorizing reuses the registered client
    # instead of registering a new one on every login.
    client_info_encrypted: str | None = None
    # Which key sealed this row. Mismatch means the key changed since login.
    key_id: str = Field(default="")
    # The endpoint this grant is for. A config that repoints an existing
    # server name at a different URL must not silently reuse the old grant.
    server_url: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
