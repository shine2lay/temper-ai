"""``temper events``: what temper received from Linear, Notion, Slack and Telegram.

    temper events list [--source S] [--status S] [--since 2h] [--limit N] [--json]
    temper events show ID [--json]
    temper events replay ID

Every event is saved in the server's event inbox before it is handled; these
commands ask the running server (``TEMPER_SERVER_URL``, default
http://127.0.0.1:8420, with ``TEMPER_API_TOKEN`` when it needs one).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

DEFAULT_SERVER = "http://127.0.0.1:8420"
STATUSES = ("unverified", "new", "handling", "done", "skipped", "failed", "gave_up", "expired")


def _call(method: str, server: str, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    headers = {}
    token = os.environ.get("TEMPER_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.request(method, f"{server.rstrip('/')}{path}", headers=headers, timeout=15,
                             params={k: v for k, v in (params or {}).items() if v not in (None, "")})
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    if response.status_code >= 400 and response.status_code != 409:
        detail = body.get("detail") if isinstance(body, dict) else body
        raise RuntimeError(f"{response.status_code}: {detail}")
    return response.status_code, body


def _when(iso: str | None) -> str:
    """A stored UTC time, shortened: 09-27 19:40."""
    return (iso or "")[5:16].replace("T", " ")


def _cut(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _runs(started: list[dict[str, Any]]) -> str:
    return ", ".join(f"{s.get('workflow')} {str(s.get('execution_id') or '')[:8]}" for s in started or [])


def cmd_list(server: str, source: str | None, status: str | None, since: str | None, limit: int,
             as_json: bool) -> int:
    _, body = _call("GET", server, "/api/events",
                    {"source": source, "status": status, "since": since, "limit": limit})
    if as_json:
        print(json.dumps(body, indent=2))
        return 0
    events = body.get("events") or []
    if not events:
        print("No events" + (" match" if source or status or since else " yet") + ".")
    else:
        print(f"{'ID':>6}  {'RECEIVED (UTC)':<11}  {'SOURCE':<8}  {'KIND':<24}  {'STATUS':<9}  {'TRIES':>5}  WHAT HAPPENED")
        for ev in events:
            what = ev.get("outcome") or ev.get("error") or ""
            if ev.get("status") == "failed" and ev.get("next_try_at"):
                what = f"{ev.get('error')} (next try {_when(ev.get('next_try_at'))})"
            print(f"{ev.get('id'):>6}  {_when(ev.get('received_at')):<11}  {ev.get('source', ''):<8}  "
                  f"{_cut(ev.get('kind', ''), 24):<24}  {ev.get('status', ''):<9}  {ev.get('tries', 0):>5}  "
                  f"{_cut(what, 90)}")
    sweeper = body.get("sweeper") or {}
    if not sweeper.get("running"):
        print("\nNote: the inbox's sweeper is not running in the server (failed events are not retried).")
    elif sweeper.get("last_error"):
        print(f"\nNote: the inbox's last sweep failed: {sweeper['last_error']}")
    return 0


def cmd_show(server: str, event_id: int, as_json: bool) -> int:
    _, ev = _call("GET", server, f"/api/events/{event_id}")
    if as_json:
        print(json.dumps(ev, indent=2))
        return 0
    lines = [
        ("event", f"{ev.get('id')}  ({ev.get('source')} {ev.get('delivery')})"),
        ("kind", ev.get("kind")),
        ("about", ev.get("subject")),
        ("received", ev.get("received_at")),
        ("status", f"{ev.get('status')} after {ev.get('tries')} tr{'y' if ev.get('tries') == 1 else 'ies'}"),
        ("handled", ev.get("handled_at")),
        ("next try", ev.get("next_try_at")),
        ("what happened", ev.get("outcome")),
        ("runs started", _runs(ev.get("started") or [])),
        ("last error", ev.get("error")),
    ]
    for label, value in lines:
        if value:
            print(f"{label + ':':<15}{value}")
    if ev.get("held_body_bytes"):
        print(f"{'held body:':<15}{ev['held_body_bytes']} bytes, waiting for the signing key")
    print("payload:")
    print(json.dumps(ev.get("payload") or {}, indent=2))
    return 0


def cmd_replay(server: str, event_id: int) -> int:
    code, body = _call("POST", server, f"/api/events/{event_id}/replay")
    if code == 409 or not body.get("replayed"):
        print(f"Not replayed: {body.get('reason') or body}")
        return 1
    print(f"Event {event_id}: {body.get('message')}. See it with: temper events show {event_id}")
    return 0


def cmd_events(args: Any) -> int:
    try:
        if args.action == "list":
            return cmd_list(args.server, args.source, args.status, args.since, args.limit, args.json)
        if args.action == "show":
            return cmd_show(args.server, args.id, args.json)
        if args.action == "replay":
            return cmd_replay(args.server, args.id)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point of a CLI error
        print(f"temper events {args.action}: {exc}", file=sys.stderr)
        return 1
    return 2


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("events", help="What temper received from Linear, Notion, Slack and Telegram")
    sub = parser.add_subparsers(dest="action", required=True)
    server_help = f"the temper server to ask (default {DEFAULT_SERVER})"
    default_server = os.environ.get("TEMPER_SERVER_URL", DEFAULT_SERVER)

    ls = sub.add_parser("list", help="newest first")
    ls.add_argument("--source", choices=["linear", "notion", "slack", "telegram"])
    ls.add_argument("--status", choices=STATUSES)
    ls.add_argument("--since", help="30m, 2h, 3d, 1w or a date like 2026-09-27 (UTC)")
    ls.add_argument("--limit", type=int, default=30)
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--server", default=default_server, help=server_help)

    show = sub.add_parser("show", help="one event: what came, what was done, the runs it started")
    show.add_argument("id", type=int)
    show.add_argument("--json", action="store_true")
    show.add_argument("--server", default=default_server, help=server_help)

    replay = sub.add_parser("replay", help="handle an event again (never starts its runs twice)")
    replay.add_argument("id", type=int)
    replay.add_argument("--server", default=default_server, help=server_help)
