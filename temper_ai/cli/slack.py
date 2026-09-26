"""``temper slack check``: is temper's Slack app set up and working?

    temper slack check [--server URL]

Checks, in order: both tokens are set; the bot token works (who it is, which
workspace, whether it has every scope the manifest asks for); the app-level
token can open a Socket Mode connection; the Slack config file parses and
where each notice goes; the running server holds the socket; which
workflows have no description (so neither search nor @temper can find them
by what they do). Exit 1 if anything is wrong.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

DEFAULT_SERVER = "http://127.0.0.1:8420"


def _server_get(server: str, path: str) -> Any:
    headers = {}
    token = os.environ.get("TEMPER_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.get(f"{server.rstrip('/')}{path}", headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def check(server: str = DEFAULT_SERVER) -> int:
    from temper_ai.integrations.slack.client import (
        REQUIRED_SCOPES,
        SlackClient,
        SlackError,
        app_token,
        bot_token,
    )
    from temper_ai.integrations.slack.config import (
        KINDS,
        SlackConfigError,
        config_path,
        load_config,
    )

    problems = 0

    def line(ok: bool | None, text: str) -> None:
        nonlocal problems
        problems += 1 if ok is False else 0
        print(f"  {'ok ' if ok else ('-- ' if ok is None else 'NO ')} {text}")

    bot, app = bot_token(), app_token()
    line(bool(bot), f"SLACK_BOT_TOKEN is {'set' if bot else 'not set'}")
    line(bool(app), f"SLACK_APP_TOKEN is {'set' if app else 'not set'}")
    client = SlackClient(bot) if bot else None

    if client is not None:
        try:
            me = client.auth_test()
            line(True, f"bot: {me.get('user')} ({me.get('user_id')}) in {me.get('team')} ({me.get('team_id')})")
            missing = [s for s in REQUIRED_SCOPES if client.scopes and s not in client.scopes]
            line(not missing, "scopes: " + (f"MISSING {', '.join(missing)} (add them, then reinstall the app)"
                                            if missing else f"all {len(REQUIRED_SCOPES)} the app needs"))
        except (SlackError, httpx.HTTPError) as exc:
            line(False, f"bot token: {exc}")
    if app:
        try:
            url = SlackClient(app).open_socket_url(app)
            line(url.startswith("wss://"), "app token: can open a Socket Mode connection")
        except (SlackError, httpx.HTTPError) as exc:
            line(False, f"app token: {exc}")

    path = config_path()
    try:
        cfg = load_config()
        if path is None:
            line(None, "config: no configs/slack/slack.yaml or configs/slack/local/slack.yaml (no notices are sent)")
        else:
            line(True, f"config: {path}")
            for kind in KINDS:
                print(f"       {kind:9} -> {cfg.route(kind, None).describe()}")
            for name, kinds in sorted(cfg.workflows.items()):
                print(f"       {name}: " + ", ".join(f"{k} -> {d.describe()}" for k, d in kinds.items()))
            print(f"       agent tools may post to: {cfg.agents.describe()}")
            if client is not None:
                for channel in {c for d in cfg.notify.values() for c in d.channels} | set(cfg.agents.channels):
                    try:
                        client.resolve(channel)
                    except SlackError as exc:
                        line(False, f"config: channel {channel}: {exc.error}")
    except SlackConfigError as exc:
        line(False, f"config: {exc}")

    try:
        status = _server_get(server, "/api/slack/status")
        if status.get("running"):
            sock = status.get("socket") or {}
            line(bool(sock.get("connected")), f"server: Slack running; socket "
                 f"{'connected since ' + str(sock.get('connected_at')) if sock.get('connected') else 'NOT connected'}"
                 + (f" (last error: {sock.get('last_error')})" if sock.get("last_error") else ""))
            notifier = status.get("notifier") or {}
            line(not notifier.get("last_error"), f"server: notices checked at {notifier.get('last_tick_at')}, "
                 f"{notifier.get('sent', 0)} sent" + (f"; last error: {notifier['last_error']}"
                                                      if notifier.get("last_error") else ""))
            if status.get("auth_error"):
                line(False, f"server: bot token failed there: {status['auth_error']}")
        else:
            line(False, f"server: Slack is not running there ({status.get('reason')})")
    except (httpx.HTTPError, ValueError) as exc:
        line(False, f"server: {server}/api/slack/status: {exc}")

    try:
        found = _server_get(server, "/api/workflows/search?q=&limit=500")
        undescribed = found.get("undescribed") or []
        line(None if undescribed else True, f"workflows: {found.get('total', '?')}; "
             + (f"{len(undescribed)} have no description, so search and @temper only find them by name: "
                + ", ".join(undescribed) if undescribed else "every one has a description"))
    except (httpx.HTTPError, ValueError) as exc:
        line(False, f"workflows: {exc}")
    return 1 if problems else 0


def cmd_slack(args: Any) -> int:
    try:
        return check(args.server)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point of a CLI error
        print(f"temper slack {args.action}: {exc}", file=sys.stderr)
        return 1


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("slack", help="Check temper's Slack app setup")
    sub = parser.add_subparsers(dest="action", required=True)
    chk = sub.add_parser("check", help="tokens, scopes, the socket, the notice routing, undescribed workflows")
    chk.add_argument("--server", default=os.environ.get("TEMPER_SERVER_URL", DEFAULT_SERVER),
                     help=f"the temper server to ask about its socket (default {DEFAULT_SERVER})")
