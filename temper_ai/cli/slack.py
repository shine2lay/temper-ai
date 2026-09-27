"""``temper slack``: is temper's Slack app set up and working, and do its
flows work?

    temper slack check [--server URL]
    temper slack fake command|mention|click|submit ... [--wait [SECONDS]]
    temper slack e2e [--only ask,mention,form,approve,reject,stop]

``fake`` and ``e2e`` go through the server's Slack test entry (see
temper_ai/integrations/slack/door.py and docs/slack.md, "Testing without
the browser"); run them where SLACK_BOT_TOKEN and TEMPER_SLACK_TEST_TOKEN
are set, e.g. ``docker exec -w /app temper-ai-server-1 /app/.venv/bin/temper
slack e2e``.

``check``
Checks, in order: both tokens are set; the bot token works (who it is, which
workspace, whether it has every scope the manifest asks for); the app-level
token can open a Socket Mode connection; the Slack config file parses; the
running server holds the socket; the notify file (where notices and
questions go) is valid and names only places that exist; which
workflows have no description (so neither search nor @temper can find them
by what they do). Exit 1 if anything is wrong.
"""

from __future__ import annotations

import json
import os
import sys
import time
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
            if any(cfg.route(k, None) for k in KINDS) or any(d for kinds in cfg.workflows.values()
                                                              for d in kinds.values()):
                line(None, "config: its notify/workflows routes are not used any more; where notices go is set "
                           "in the notify file (below)")
            print(f"       agent tools may post to: {cfg.agents.describe()}")
            if client is not None:
                for channel in set(cfg.agents.channels):
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

    from temper_ai.cli.notify_check import check_notify

    check_notify(line, lambda path: _server_get(server, path), via="slack")

    try:
        found = _server_get(server, "/api/workflows/search?q=&limit=500")
        undescribed = found.get("undescribed") or []
        line(None if undescribed else True, f"workflows: {found.get('total', '?')}; "
             + (f"{len(undescribed)} have no description, so search and @temper only find them by name: "
                + ", ".join(undescribed) if undescribed else "every one has a description"))
    except (httpx.HTTPError, ValueError) as exc:
        line(False, f"workflows: {exc}")
    return 1 if problems else 0


def _tester(server: str) -> Any:
    from temper_ai.integrations.slack.client import SlackClient, bot_token
    from temper_ai.integrations.slack.e2e import Door, Tester

    bot = bot_token()
    if not bot:
        raise RuntimeError("SLACK_BOT_TOKEN is not set here; run it in the server container: "
                           "docker exec -w /app temper-ai-server-1 /app/.venv/bin/temper slack ...")
    return Tester(Door(server), SlackClient(bot))


def fake(args: Any) -> int:
    """``temper slack fake``: one fake Slack event, and (``--wait``) what came of it."""
    from temper_ai.integrations.slack import fakes
    from temper_ai.integrations.slack.e2e import (
        ACTIONS,
        E2EError,
        follow,
        message_line,
        picks_for,
        slack_ts,
    )

    t = _tester(args.server)
    since = slack_ts(time.time() - 1)
    text = " ".join(getattr(args, "text", None) or []).strip()
    thread, clicked = "", None
    if args.kind == "command":
        envelope = fakes.command(t.where, text, name=args.name)
    elif args.kind == "mention":
        ts = args.ts or str(t.slack.post(t.where.channel, f":test_tube: a fake @temper message: {text}")["ts"])
        envelope = fakes.mention(t.where, text, ts, thread_ts=args.thread or "")
        thread = args.thread or ts
    elif args.kind == "click":
        clicked = t.message(args.ts, args.thread or "")
        if clicked is None:
            raise E2EError(f"no message {args.ts} in {t.where.channel_name}"
                           + ("" if args.thread else " (a reply in a thread needs --thread)"))
        envelope = fakes.click(t.where, clicked, ACTIONS.get(args.button, args.button))
        thread = args.thread or args.ts
    else:
        forms = t.door.fake(args.fake).get("forms") or []
        if not forms:
            raise E2EError(f"fake {args.fake} opened no form (it has to be an Answer click)")
        view = forms[-1]["view"]
        picks = dict(p.split("=", 1) for p in args.pick) if args.pick else picks_for(view)[0]
        envelope = fakes.submit(t.where, view, picks)
        thread = args.thread or ""
        print(f"form filled in: {json.dumps(picks, ensure_ascii=False)}")
    sent = t.door.send(envelope)
    print(f"fake {sent['fake']} ({sent['kind']}) sent; inbox event {sent.get('event_id')}")
    if args.wait:
        follow(t, sent["fake"], args.wait, thread, since)
        if clicked is not None:
            now = t.message(args.ts, args.thread or "")
            if now is not None:
                print("the clicked message now:")
                print(message_line(now, t.where))
    return 0


def e2e(args: Any) -> int:
    """``temper slack e2e``: the whole Slack check set, in the test channel."""
    from temper_ai.integrations.slack.e2e import CHECKS, summary

    only = [n.strip() for n in (args.only or "").split(",") if n.strip()]
    unknown = [n for n in only if n not in CHECKS]
    if unknown:
        raise ValueError(f"no check {', '.join(unknown)} (they are: {', '.join(CHECKS)})")
    t = _tester(args.server)
    print(f"Slack checks in {t.where.channel_name} ({t.where.channel}), as {t.where.user}, through {args.server}")
    results = t.run(only or None)
    print(summary(results))
    return 0 if results and all(r.ok for r in results) else 1


def cmd_slack(args: Any) -> int:
    try:
        if args.action == "fake":
            return fake(args)
        if args.action == "e2e":
            return e2e(args)
        return check(args.server)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point of a CLI error
        print(f"temper slack {args.action}: {exc}", file=sys.stderr)
        return 1


def add_parser(subparsers: Any) -> None:
    server = os.environ.get("TEMPER_SERVER_URL", DEFAULT_SERVER)
    parser = subparsers.add_parser("slack", help="Check temper's Slack app setup, and test its Slack flows")
    sub = parser.add_subparsers(dest="action", required=True)
    chk = sub.add_parser("check", help="tokens, scopes, the socket, the notice routing, undescribed workflows")
    chk.add_argument("--server", default=server,
                     help=f"the temper server to ask about its socket (default {DEFAULT_SERVER})")

    fk = sub.add_parser("fake", help="send temper one fake Slack event through its test entry")
    kinds = fk.add_subparsers(dest="kind", required=True)
    cmd = kinds.add_parser("command", help="/temper <text>, typed in the test channel")
    cmd.add_argument("text", nargs="+", help='what follows /temper, e.g. "ask what does gate_smoke do?"')
    cmd.add_argument("--name", default="/temper", help="the command (default /temper)")
    men = kinds.add_parser("mention", help="@temper <text>: hung on a message the bot posts, unless --ts")
    men.add_argument("text", nargs="+")
    men.add_argument("--ts", help="the message it is (one in the test channel)")
    men.add_argument("--thread", help="the thread it is in, if it is a reply")
    clk = kinds.add_parser("click", help="click a button on a message temper posted in the test channel")
    clk.add_argument("ts", help="the message's ts")
    clk.add_argument("button", help="answer, approve, reject, stop, confirm, cancel, or an action id")
    clk.add_argument("--thread", help="the thread's first message, when the message is a reply")
    sbm = kinds.add_parser("submit", help="send the form a fake Answer click opened")
    sbm.add_argument("fake", help="the Answer click's fake id")
    sbm.add_argument("--pick", action="append", default=[], metavar="BLOCK=VALUE",
                     help="q0=1 picks option 1 of question 0; q1=0,2 two options; q2c=text types; "
                          "response=text; without any, the e2e's picks")
    sbm.add_argument("--thread", help="a thread to print after --wait (the run's)")
    for kind in (cmd, men, clk, sbm):
        kind.add_argument("--server", default=server, help=f"the temper server (default {DEFAULT_SERVER})")
        kind.add_argument("--wait", nargs="?", type=float, const=480.0, default=0.0, metavar="SECONDS",
                          help="print what temper does with it (replies, forms, its inbox event, the thread), "
                               "for up to SECONDS (default 480)")

    run = sub.add_parser("e2e", help="run the whole Slack check set in the test channel (pass/fail, times, cost)")
    run.add_argument("--only", help="a comma list of: ask, mention, form, approve, reject, stop")
    run.add_argument("--server", default=server, help=f"the temper server (default {DEFAULT_SERVER})")
