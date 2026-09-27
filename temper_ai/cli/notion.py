"""``temper notion check``: is temper's Notion connection set up and working?

    temper notion check [--server URL]

Checks, in order: NOTION_TOKEN works (the bot's name and workspace); the
Notion config parses, and each target is shared with Temper (a table's key
and mapped fields exist, with types temper can write); every ``source:
notion`` trigger rule names a real table and property; the webhook
(NOTION_WEBHOOK_SECRET set, the public route answers, the last events and
the verification token Notion sent, to paste back into Notion); the notify
file's Notion places; and whether the owner's own Notion sign-in (the MCP
grant, used by agents that declare notion.* tools) is connected. Exit 1 if
anything is wrong. Tokens are never printed. The verification token is
shown only while the owner still needs it (to paste into Notion and into
NOTION_WEBHOOK_SECRET); once that secret holds it, the check only says so,
because it is the key that signs every event.
"""

from __future__ import annotations

import hmac
import os
import sys
from typing import Any

import httpx

from temper_ai.cli.slack import DEFAULT_SERVER, _server_get

PUBLIC_HOOK = "https://hooks.wai2shine.com/api/hooks/notion"
WRITABLE = {"title", "rich_text", "number", "select", "multi_select", "status", "date", "url", "email",
            "phone_number", "checkbox", "people", "relation"}


def _verification_line(token_sent: str | None, secret: str | None) -> tuple[bool | None, str]:
    """The check's line for the verification token Notion sent.

    The token is the webhook's signing key. It is printed only while it still
    has to be pasted somewhere: before NOTION_WEBHOOK_SECRET is set, or when
    Notion sent a new one that the secret doesn't hold yet.
    """
    if not token_sent:
        return None, "verification token: none received yet (make the webhook subscription in Notion)"
    if not secret:
        return True, (f"verification token Notion sent: {token_sent} (paste it into Notion, and into "
                      "~/temper-ai/.env as NOTION_WEBHOOK_SECRET)")
    if hmac.compare_digest(token_sent.encode(), secret.encode()):
        return True, "verification token Notion sent: NOTION_WEBHOOK_SECRET holds it (not shown)"
    return False, (f"verification token Notion sent is not NOTION_WEBHOOK_SECRET: {token_sent} (a new "
                   "subscription? Put it in ~/temper-ai/.env and restart temper)")


def check(server: str = DEFAULT_SERVER, public_url: str = PUBLIC_HOOK) -> int:
    from temper_ai.integrations.notion.client import (
        NotionClient,
        NotionError,
        normalize_id,
        token,
    )
    from temper_ai.integrations.notion.config import (
        NotionConfigError,
        config_path,
        load_config,
    )
    from temper_ai.triggers import notion as rules

    problems = 0

    def line(ok: bool | None, text: str) -> None:
        nonlocal problems
        problems += 1 if ok is False else 0
        print(f"  {'ok ' if ok else ('-- ' if ok is None else 'NO ')} {text}")

    client: NotionClient | None = NotionClient() if token() else None
    line(client is not None, f"NOTION_TOKEN is {'set' if client else 'not set'}")
    if client is not None:
        try:
            me = client.me()
            ws = (me.get("bot") or {}).get("workspace_name") or "?"
            line(True, f"connection: {me.get('name')!r} (bot {str(me.get('id'))[:8]}) in workspace {ws!r}")
        except (NotionError, httpx.HTTPError) as exc:
            line(False, f"NOTION_TOKEN: {exc}")
            client = None

    cfg = None
    path = config_path()
    try:
        cfg = load_config()
        line(bool(path) or None, f"config: {path or 'none (configs/notion/local/notion.yaml); no targets'}; "
                                 f"targets: {cfg.describe()}; answers read "
                                 + ("every page shared with Temper" if cfg.answer_from is None
                                    else ", ".join(cfg.answer_from) or "nothing"))
    except NotionConfigError as exc:
        line(False, f"config: {exc}")

    schemas: dict[str, dict[str, Any]] = {}
    if cfg is not None and client is not None:
        for t in sorted(cfg.targets.values(), key=lambda t: t.name):
            try:
                if not t.is_table:
                    page = client.page(t.page)
                    from temper_ai.integrations.notion.content import title_of
                    line(True, f"target {t.name}: page {title_of(page)!r} is shared with Temper")
                    continue
                ds = client.data_source_for(t.table)
                source = client.data_source(ds)
                props = source.get("properties") or {}
                schemas[t.name] = props
                from temper_ai.integrations.notion.content import title_of
                bad = []
                if t.key not in props:
                    bad.append(f"key {t.key!r} is not a column")
                for fname, prop in t.fields.items():
                    if prop not in props:
                        bad.append(f"field {fname} -> {prop!r} is not a column")
                    elif props[prop].get("type") not in WRITABLE:
                        bad.append(f"field {fname} -> {prop!r} is a {props[prop].get('type')} column temper "
                                   "cannot write")
                line(not bad, f"target {t.name}: table {title_of(source)!r} ({len(props)} columns, key "
                              f"{t.key!r})" + (": " + "; ".join(bad) if bad else ""))
            except (NotionError, httpx.HTTPError) as exc:
                line(False, f"target {t.name}: {exc} (share the page or table with the Temper connection)")

    try:
        from temper_ai.triggers.rules import load_triggers

        found = load_triggers(None, source=rules.SOURCE)
    except Exception as exc:  # noqa: BLE001 - a broken rule file is reported, not raised
        found = []
        line(False, f"trigger rules: {exc}")
    for trig in found:
        on = trig.on or {}
        try:
            rules.check_on(on)
            msg = ""
            table = str(on.get("table") or "")
            if table and cfg is not None:
                target = cfg.target(table)
                if target is None or not target.is_table:
                    msg = f"table {table!r} is not a table target in the Notion config"
                elif on.get("property") and target.name in schemas and \
                        target.prop(str(on["property"])) not in schemas[target.name]:
                    msg = f"property {on['property']!r} is not a column of {table}"
            line(not msg, f"rule {trig.name} -> {trig.workflow}"
                          + ("" if trig.enabled else " (off)") + (f": {msg}" if msg else ""))
        except ValueError as exc:
            line(False, f"rule {trig.name}: {exc}")

    line(bool(rules.signing_secret()) or None,
         f"{rules.SECRET_ENV} is " + ("set" if rules.signing_secret() else
                                      "not set: events are kept unchecked until it is (it is the verification "
                                      "token below)"))
    try:
        from temper_ai.cli.connect import _init_db
        from temper_ai.integrations.notion import store

        if not _init_db():
            raise RuntimeError("temper's database was not found")
        vt = store.get_state("verification_token")
        line(*_verification_line(vt, rules.signing_secret()))
        from temper_ai.integrations.inbox import store as inbox_store

        for ev in inbox_store.listing(source="notion", limit=5):
            print(f"       event {ev.id} {ev.received_at.isoformat()[:16]} {ev.kind}: "
                  f"{ev.status}{' - ' + ev.outcome if ev.outcome else ''}")
    except Exception as exc:  # noqa: BLE001
        line(False, f"events store: {exc}")

    try:
        resp = httpx.post(public_url, content=b"{}", timeout=10)
        # A body with no signature is refused (401): that answer means the route reaches temper.
        reach = resp.status_code in (400, 401, 503)
        line(reach, f"public route {public_url}: HTTP {resp.status_code}"
                    + ("" if reach else " (expected temper's 401; add the gateway route, see docs/notion.md)"))
    except httpx.HTTPError as exc:
        line(False, f"public route {public_url}: {exc}")

    try:
        from temper_ai.integrations.notify.config import NotifyConfigError
        from temper_ai.integrations.notify.config import load_config as load_notify

        places = [p for p in load_notify().places.values() if p.via == "notion"]
        for place in places:
            place_target = cfg.target(place.target) if cfg else None
            pid = place_target.page if place_target is not None and not place_target.is_table else normalize_id(place.target)
            try:
                if client is None or not pid:
                    raise NotionError("page", 0, "", "no page")
                client.page(pid)
                line(True, f"place {place.name}: Notion page {pid[:8]} is reachable")
            except (NotionError, httpx.HTTPError) as exc:
                line(False, f"place {place.name}: {place.target} is not a reachable page target ({exc})")
    except NotifyConfigError as exc:
        line(False, f"notify config: {exc}")

    try:
        status = _server_get(server, "/api/health")
        line(True, f"server: {server} is up ({status.get('status', 'ok')})")
    except (httpx.HTTPError, ValueError) as exc:
        line(None, f"server: {server}: {exc}")

    signin_line(line)
    return 1 if problems else 0


def signin_line(line: Any) -> None:
    """The owner's own Notion sign-in (the notion MCP server's OAuth grant)."""
    try:
        from temper_ai.cli.connect import _http_servers, _init_db
        from temper_ai.tools.mcp_auth import DatabaseTokenStore, oauth_configured

        config = _http_servers().get("notion")
        if config is None or not oauth_configured(config):
            line(None, "sign-in: no notion MCP server configured")
            return
        if not _init_db():
            line(False, "sign-in: temper's database was not found")
            return
        info = DatabaseTokenStore("notion", server_url=config["url"]).describe()
        if info["connected"]:
            line(True, f"sign-in: the owner's Notion sign-in is connected (since {info['updated_at']:%Y-%m-%d}); "
                       "agents that declare notion.* tools act as the owner")
        else:
            line(None, f"sign-in: not connected ({info['reason']}); `temper connect notion` to add it")
    except Exception as exc:  # noqa: BLE001
        line(False, f"sign-in: {exc}")


def cmd_notion(args: Any) -> int:
    try:
        return check(args.server, args.public_url)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point of a CLI error
        print(f"temper notion {args.action}: {exc}", file=sys.stderr)
        return 1


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("notion", help="Check temper's Notion connection")
    sub = parser.add_subparsers(dest="action", required=True)
    chk = sub.add_parser("check", help="the token, targets, trigger rules, webhook, places and sign-in")
    chk.add_argument("--server", default=os.environ.get("TEMPER_SERVER_URL", DEFAULT_SERVER),
                     help=f"the temper server (default {DEFAULT_SERVER})")
    chk.add_argument("--public-url", default=PUBLIC_HOOK, help="the public webhook URL to probe")
