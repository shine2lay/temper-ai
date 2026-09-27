"""``temper telegram check``: is temper's Telegram bot set up and working?

    temper telegram check [--server URL]

Checks, in order: the bot token is set and works (the bot's name, whether
it may join groups and reads every group message); no webhook is set (it
would stop polling); the Telegram config parses (who may use the bot, the
allowed groups, the time zone); the running server polls the bot; which
chats the bot talks in, which tried to talk to it and were refused, which
groups it left; the notify file (where notices and questions go) is valid
and its Telegram places are chats the bot can reach. Exit 1 if anything is
wrong. The token itself is never printed.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

from temper_ai.cli.slack import DEFAULT_SERVER, _server_get


def check(server: str = DEFAULT_SERVER) -> int:
    from temper_ai.cli.notify_check import check_notify
    from temper_ai.integrations.notify.config import NotifyConfigError
    from temper_ai.integrations.notify.config import load_config as load_notify
    from temper_ai.integrations.telegram.client import (
        TOKEN_ENV,
        TelegramClient,
        TelegramError,
        bot_token,
    )
    from temper_ai.integrations.telegram.config import (
        TelegramConfigError,
        config_path,
        load_config,
    )

    problems = 0

    def line(ok: bool | None, text: str) -> None:
        nonlocal problems
        problems += 1 if ok is False else 0
        print(f"  {'ok ' if ok else ('-- ' if ok is None else 'NO ')} {text}")

    token = bot_token()
    line(bool(token), f"{TOKEN_ENV} is {'set' if token else 'not set'}")
    client = TelegramClient(token) if token else None
    if client is not None:
        try:
            me = client.get_me()
            line(True, f"bot: @{me.get('username')} ({me.get('first_name')}, id {me.get('id')}); "
                       f"{'may' if me.get('can_join_groups') else 'may NOT'} join groups; "
                       + ("reads every group message (privacy mode off)" if me.get("can_read_all_group_messages")
                          else "in groups sees only commands, mentions and replies to it (privacy mode on)"))
            hook = client.get_webhook_info() or {}
            line(not hook.get("url"), "webhook: none, so temper can poll" if not hook.get("url")
                 else "webhook: SET, so polling is refused; remove it (deleteWebhook) to use the bot from temper")
        except (TelegramError, httpx.HTTPError) as exc:
            line(False, f"bot token: {exc}")
            client = None

    path = config_path()
    try:
        cfg = load_config()
        if path is None:
            line(False, "config: no configs/telegram/local/telegram.yaml, so nobody may use the bot")
        else:
            line(bool(cfg.owners), f"config: {path}; {len(cfg.owners)} owner(s), {len(cfg.groups)} group(s) "
                                   f"listed, times in {cfg.zone}" + ("" if cfg.owners else " (no owners: nobody "
                                                                                          "may use the bot)"))
    except TelegramConfigError as exc:
        line(False, f"config: {exc}")

    try:
        status = _server_get(server, "/api/telegram/status")
        if status.get("running"):
            poll = status.get("poll") or {}
            ok = not poll.get("conflict") and not status.get("last_error")
            line(ok, f"server: polling as @{(status.get('bot') or {}).get('username')}; last poll "
                     f"{poll.get('last_at')}; {poll.get('received', 0)} update(s) handled, "
                     f"{poll.get('skipped', 0)} skipped as too old"
                     + (f"; last error: {status.get('last_error')}" if status.get("last_error") else ""))
            chats = status.get("chats") or {}
            for chat in chats.get("allowed") or []:
                print(f"       talks in: {_chat(chat)}")
            refused = chats.get("refused") or []
            line(None if refused else True, "refused: " + ("; ".join(_chat(c) for c in refused)
                                                          + " (they got no answer)" if refused
                                                          else "no one else has tried to use the bot"))
            for chat in chats.get("left") or []:
                print(f"       left: {_chat(chat)}")
        else:
            line(False, f"server: the bot is not running there ({status.get('reason') or status.get('last_error')})")
    except (httpx.HTTPError, ValueError) as exc:
        line(False, f"server: {server}/api/telegram/status: {exc}")

    check_notify(line, lambda p: _server_get(server, p), via="telegram")

    if client is not None:
        try:
            places = [p for p in load_notify().places.values() if p.via == "telegram"]
        except NotifyConfigError:
            places = []   # already reported by check_notify
        for place in places:
            try:
                chat = client.get_chat(place.target)
                name = chat.get("title") or chat.get("first_name") or chat.get("username") or ""
                line(True, f"place {place.name}: the bot can reach {chat.get('type')} chat {name!r}")
            except (TelegramError, httpx.HTTPError) as exc:
                line(False, f"place {place.name}: the bot cannot reach chat {place.target}: {exc} "
                            "(for a private chat, send the bot /start first)")
    return 1 if problems else 0


def _chat(chat: dict[str, Any]) -> str:
    name = chat.get("title") or chat.get("chat_id")
    who = f", added by {chat['added_by']}" if chat.get("added_by") else ""
    tries = f", {chat['tries']} message(s)" if chat.get("tries") else ""
    return (f"{chat.get('type') or 'chat'} {name!r} ({chat.get('chat_id')}{who}{tries}; "
            f"last seen {str(chat.get('last_seen') or '')[:16]})")


def cmd_telegram(args: Any) -> int:
    try:
        return check(args.server)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point of a CLI error
        print(f"temper telegram {args.action}: {exc}", file=sys.stderr)
        return 1


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("telegram", help="Check temper's Telegram bot setup")
    sub = parser.add_subparsers(dest="action", required=True)
    chk = sub.add_parser("check", help="the token, the bot, who may use it, polling, the notice routing")
    chk.add_argument("--server", default=os.environ.get("TEMPER_SERVER_URL", DEFAULT_SERVER),
                     help=f"the temper server to ask about its polling (default {DEFAULT_SERVER})")
