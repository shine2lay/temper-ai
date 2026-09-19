"""`temper connect` / `connections` / `disconnect` — one-time MCP authorization.

These are the human half of the OAuth story. Everything unattended (agents,
the API server, container workers) reads the grant these commands leave in
the database and refreshes it silently; nothing else ever needs a browser.

Named for what the operator is doing — connecting temper to Notion — rather
than for the protocol underneath, because the same commands will cover every
future OAuth integration.
"""

import asyncio
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _http_servers() -> dict[str, dict]:
    """Configured HTTP MCP servers, by name."""
    from temper_ai.tools.mcp_client import _load_mcp_configs

    servers = {}
    for config in _load_mcp_configs():
        if str(config.get("transport", "stdio")).lower() in ("http", "streamable_http"):
            servers[config.get("name", "unnamed")] = config
    return servers


def _init_db() -> None:
    from temper_ai.database.session import init_database

    init_database()


def cmd_connect(args: Any) -> int:
    """Authorize one MCP server interactively and store the grant."""
    from temper_ai.tools.mcp_auth import MCPAuthError, find_free_port, oauth_configured

    servers = _http_servers()
    config = servers.get(args.server)
    if config is None:
        print(f"No HTTP MCP server named '{args.server}' is configured.", file=sys.stderr)
        if servers:
            print(f"Configured: {', '.join(sorted(servers))}", file=sys.stderr)
        else:
            print(
                "Add one under configs/mcp_servers/ with `transport: http`.",
                file=sys.stderr,
            )
        return 1

    if not oauth_configured(config):
        print(
            f"MCP server '{args.server}' is not configured for OAuth "
            f"(no `auth: oauth` in its YAML). Nothing to authorize.",
            file=sys.stderr,
        )
        return 1

    _init_db()

    port = find_free_port(int(config.get("callback_port", args.port)))
    config = {**config, "callback_port": port}

    manual = bool(getattr(args, "manual", False))
    print(f"Connecting to '{args.server}' ({config['url']})...")
    try:
        asyncio.run(_run_login(config, manual=manual))
    except MCPAuthError as exc:
        print(f"\nAuthorization failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface any transport failure plainly
        print(f"\nAuthorization failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nConnected. '{args.server}' is authorized and the grant is stored.")
    print("Runs will refresh it automatically; you should not need to do this again.")
    return 0


async def _run_login(config: dict, *, manual: bool = False) -> None:
    """Drive one real session so the SDK performs the full flow and stores it.

    Authorization is lazy in the SDK: the provider only runs the flow when a
    request comes back 401. So the way to *complete* a login is to make a real
    connection and list tools — which doubles as proof the grant actually
    works, rather than reporting success on a token we never used.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    from temper_ai.tools.mcp_auth import build_oauth_provider

    auth = build_oauth_provider(config, interactive=True, manual=manual)
    async with create_mcp_http_client(
        headers=config.get("headers") or None, auth=auth
    ) as http_client:
        async with streamable_http_client(config["url"], http_client=http_client) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=300)
                page = await session.list_tools()
                print(f"Verified: server advertises {len(page.tools)} tool(s).")


def cmd_connections(args: Any) -> int:
    """Show every configured HTTP MCP server and whether it is authorized."""
    from temper_ai.tools.mcp_auth import DatabaseTokenStore, oauth_configured

    servers = _http_servers()
    if not servers:
        print("No HTTP MCP servers configured (configs/mcp_servers/*.yaml).")
        return 0

    _init_db()

    width = max(len(name) for name in servers)
    for name in sorted(servers):
        config = servers[name]
        if not oauth_configured(config):
            status = "no auth required"
            if config.get("headers"):
                status = "static headers"
            print(f"  {name:<{width}}  {status}")
            continue
        store = DatabaseTokenStore(name, server_url=config["url"])
        info = store.describe()
        if info["connected"]:
            refresh = "refreshable" if info["has_refresh_token"] else "no refresh token"
            print(f"  {name:<{width}}  connected ({refresh}, since {info['updated_at']:%Y-%m-%d})")
        else:
            print(f"  {name:<{width}}  not connected — {info['reason']}")
            print(f"  {'':<{width}}  run: temper connect {name}")
    return 0


def cmd_disconnect(args: Any) -> int:
    """Forget a stored grant."""
    from temper_ai.tools.mcp_auth import DatabaseTokenStore

    _init_db()
    store = DatabaseTokenStore(args.server)
    if store.delete():
        print(f"Disconnected '{args.server}'. The stored grant has been deleted.")
        print(
            "Note: this does not revoke access on the provider's side — "
            "do that in the provider's own connection settings."
        )
        return 0
    print(f"'{args.server}' was not connected.")
    return 0
