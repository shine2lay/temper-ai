"""``temper linear``: check the Linear setup, and read or comment by hand.

    temper linear check            the app's token, who it acts as, the MCP tools, the webhook secret
    temper linear issue ENG-123    an issue and its comments, as JSON
    temper linear comment ENG-123  comment on an issue; the body is read from stdin

All of it acts as the app configured by LINEAR_CLIENT_ID and
LINEAR_CLIENT_SECRET (see triggers.linear), the same identity agents use
through ``configs/mcp_servers/linear.yaml``, so a comment posted here shows
as temper, never as a person.

This is for people, not for script nodes: a script runs with every
``*_SECRET`` variable stripped from its environment (tools.bash), so it
cannot reach LINEAR_CLIENT_SECRET. Workflows read and write Linear through
the MCP tools (``linear.get_issue``, ``linear.save_comment``, ...), which run
inside temper.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from temper_ai.triggers import linear

ISSUE_QUERY = """
query Issue($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    description
    url
    priorityLabel
    state { name }
    team { key name }
    assignee { name }
    labels { nodes { name } }
    comments(first: 50) {
      nodes { id body createdAt user { id name } }
    }
  }
}
"""

COMMENT_MUTATION = """
mutation Comment($input: CommentCreateInput!) {
  commentCreate(input: $input) {
    success
    comment { id url }
  }
}
"""

# What the linear_reply agent calls. `check` says whether the server has them,
# since Linear has renamed tools before (update_issue became save_issue).
REPLY_TOOLS = ("get_issue", "list_comments", "save_comment")
MCP_SERVER = "linear"
MAX_COMMENT_CHARS = 20_000


def read_issue(issue_id: str) -> dict[str, Any]:
    """The issue and its comments, oldest comment first."""
    issue = linear.graphql(ISSUE_QUERY, {"id": issue_id}).get("issue")
    if not issue:
        raise RuntimeError(f"Linear has no issue {issue_id!r} that temper's app can see")
    me = linear.app_user_id()
    comments = []
    for node in (issue.get("comments") or {}).get("nodes") or []:
        user = node.get("user") or {}
        comments.append({
            "author": user.get("name") or "unknown",
            "by_temper": bool(me) and user.get("id") == me,
            "created_at": node.get("createdAt"),
            "body": node.get("body") or "",
        })
    comments.sort(key=lambda c: c["created_at"] or "")
    return {
        "id": issue.get("id"),
        "identifier": issue.get("identifier"),
        "title": issue.get("title"),
        "description": issue.get("description") or "",
        "url": issue.get("url"),
        "state": (issue.get("state") or {}).get("name"),
        "team": (issue.get("team") or {}).get("key"),
        "assignee": (issue.get("assignee") or {}).get("name"),
        "priority": issue.get("priorityLabel"),
        "labels": [n.get("name") for n in (issue.get("labels") or {}).get("nodes") or []],
        "comments": comments,
    }


def create_comment(issue_id: str, body: str) -> dict[str, Any]:
    body = body.strip()
    if not body:
        raise RuntimeError("refusing to post an empty comment")
    if len(body) > MAX_COMMENT_CHARS:
        raise RuntimeError(f"comment is {len(body)} characters; the limit here is {MAX_COMMENT_CHARS}")
    result = linear.graphql(COMMENT_MUTATION, {"input": {"issueId": issue_id, "body": body}})
    created = result.get("commentCreate") or {}
    if not created.get("success"):
        raise RuntimeError(f"Linear did not create the comment: {result}")
    comment = created.get("comment") or {}
    return {"id": comment.get("id"), "url": comment.get("url")}


async def _mcp_tool_names(config: dict) -> list[str]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    from temper_ai.tools.oauth_client_credentials import (
        ClientCredentials,
        ClientCredentialsAuth,
    )

    auth = ClientCredentialsAuth(ClientCredentials.from_config(config))
    async with create_mcp_http_client(headers=config.get("headers") or None, auth=auth) as http:
        async with streamable_http_client(config["url"], http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=60)
                names: list[str] = []
                cursor = None
                while True:
                    page = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
                    names.extend(tool.name for tool in page.tools)
                    cursor = getattr(page, "nextCursor", None)
                    if not cursor:
                        return sorted(names)


def check() -> int:
    """Say what works and what is missing; exit 1 if anything is."""
    problems = 0

    def line(ok: bool, text: str) -> None:
        nonlocal problems
        problems += 0 if ok else 1
        print(f"  {'ok ' if ok else 'NO '} {text}")

    creds = linear.app_credentials()
    if creds is None:
        line(False, f"app: {linear.CLIENT_ID_ENV} / {linear.CLIENT_SECRET_ENV} are not set")
    else:
        try:
            viewer = linear.graphql("query { viewer { id name } organization { name urlKey } }")
            me, org = viewer.get("viewer") or {}, viewer.get("organization") or {}
            line(True, f"app: acts as \"{me.get('name')}\" ({me.get('id')}) in {org.get('name')} "
                       f"(linear.app/{org.get('urlKey')}), scope {creds.scope}")
        except Exception as exc:  # noqa: BLE001
            line(False, f"app: {exc}")

    from temper_ai.cli.connect import _http_servers

    config = _http_servers().get(MCP_SERVER)
    if config is None:
        line(False, f"MCP: no HTTP MCP server named '{MCP_SERVER}' (configs/mcp_servers/linear.yaml)")
    elif creds is not None:
        try:
            names = asyncio.run(_mcp_tool_names(config))
            missing = [t for t in REPLY_TOOLS if t not in names]
            line(not missing, f"MCP: {len(names)} tools at {config['url']}"
                 + (f"; MISSING {', '.join(missing)} (renamed upstream?)" if missing else ""))
            print(f"       {', '.join(names)}")
        except Exception as exc:  # noqa: BLE001
            line(False, f"MCP: {config['url']}: {exc}")

    line(linear.signing_secret() is not None,
         f"webhook: {linear.SIGNING_SECRET_ENV} is {'set' if linear.signing_secret() else 'not set'}")
    return 1 if problems else 0


def cmd_linear(args: Any) -> int:
    try:
        if args.action == "check":
            return check()
        if args.action == "issue":
            out = read_issue(args.issue_id)
        else:
            out = create_comment(args.issue_id, sys.stdin.read())
    except Exception as exc:  # noqa: BLE001 - the message is the whole point of a CLI error
        print(f"temper linear {args.action}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("linear", help="Check the Linear setup; read or comment on an issue")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("check", help="the app token, who it acts as, the MCP tools, the webhook secret")
    issue = sub.add_parser("issue", help="print an issue and its comments as JSON")
    issue.add_argument("issue_id", help="issue id or identifier (ENG-123)")
    comment = sub.add_parser("comment", help="comment on an issue as temper; the body is read from stdin")
    comment.add_argument("issue_id", help="issue id or identifier (ENG-123)")
