"""Fake Slack events for the test entry (door.py), built from templates/.

Each template is a Socket Mode envelope with its token removed. The
builders fill in the test channel, the owner, and what was typed or
clicked; the test entry then gives the fake its own ids, reply link and
trigger before temper handles it.

A click is built from the real message as Slack's API returns it, so its
button (and the value temper put in it) is the one temper really posted.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TEMPLATES = Path(__file__).parent / "templates"
KINDS = ("command", "click", "submit", "mention")
# What a real token looks like in an envelope; no template may carry one.
TOKEN_KEYS = ("token", "bot_access_token", "access_token")


@dataclass(frozen=True)
class Where:
    """Where fakes happen, as ``GET /api/test/slack`` tells it."""

    channel: str          # the test channel's id
    channel_name: str     # "#temper-qa"
    user: str             # the owner, whom fakes act as
    bot_user: str = ""    # temper's own Slack user
    team: str = ""

    @classmethod
    def from_info(cls, info: dict[str, Any]) -> Where:
        return cls(channel=str(info.get("channel_id") or ""), channel_name=str(info.get("channel") or ""),
                   user=str(info.get("user") or ""), bot_user=str(info.get("bot_user") or ""),
                   team=str(info.get("team") or ""))


def template(kind: str) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"no template {kind!r} (one of {', '.join(KINDS)})")
    return copy.deepcopy(json.loads((TEMPLATES / f"{kind}.json").read_text())["envelope"])


def _stamp() -> str:
    return f"{time.time():.6f}"


def command(where: Where, text: str, name: str = "/temper") -> dict[str, Any]:
    """``/temper <text>`` typed in the test channel."""
    env = template("command")
    env["payload"].update(team_id=where.team, channel_id=where.channel,
                          channel_name=where.channel_name.lstrip("#"), user_id=where.user, command=name,
                          text=text)
    return env


def mention(where: Where, text: str, ts: str, thread_ts: str = "") -> dict[str, Any]:
    """``@temper <text>``, as the message at ``ts`` (one the bot posted, so
    there is a real thread for the answer)."""
    env = template("mention")
    p, event = env["payload"], env["payload"]["event"]
    words = text.strip()
    body = words if words.startswith("<@") else f"<@{where.bot_user}> {words}"
    event.update(user=where.user, ts=ts, event_ts=ts, channel=where.channel, team=where.team, text=body,
                 client_msg_id=str(uuid.uuid4()),
                 blocks=[{"type": "rich_text", "block_id": uuid.uuid4().hex[:5], "elements": [
                     {"type": "rich_text_section", "elements": [
                         {"type": "user", "user_id": where.bot_user}, {"type": "text", "text": f" {words}"}]}]}])
    if thread_ts:
        event["thread_ts"] = thread_ts
    p.update(team_id=where.team, context_team_id=where.team, event_time=int(float(ts or 0)))
    p["authorizations"][0].update(team_id=where.team, user_id=where.bot_user)
    return env


def buttons(message: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(block id, button) for every button on a message."""
    out: list[tuple[str, dict[str, Any]]] = []
    for block in message.get("blocks") or []:
        if block.get("type") == "actions":
            out.extend((str(block.get("block_id") or ""), e) for e in block.get("elements") or []
                       if e.get("type") == "button")
        elif (block.get("accessory") or {}).get("type") == "button":
            out.append((str(block.get("block_id") or ""), block["accessory"]))
    return out


def click(where: Where, message: dict[str, Any], action_id: str) -> dict[str, Any]:
    """A click on ``message``'s button ``action_id`` (the message as
    conversations.history or conversations.replies return it)."""
    found = next(((b, e) for b, e in buttons(message) if e.get("action_id") == action_id), None)
    if found is None:
        have = ", ".join(e.get("action_id", "?") for _, e in buttons(message)) or "none"
        raise ValueError(f"the message has no {action_id} button (it has: {have})")
    block_id, button = found
    env = template("click")
    p = env["payload"]
    p["user"].update(id=where.user, team_id=where.team)
    p["team"]["id"] = where.team
    p["container"].update(message_ts=str(message.get("ts") or ""), channel_id=where.channel)
    if message.get("thread_ts"):
        p["container"]["thread_ts"] = message["thread_ts"]
    p["channel"] = {"id": where.channel, "name": where.channel_name.lstrip("#")}
    p["message"] = copy.deepcopy(message)
    act = {"action_id": action_id, "block_id": block_id, "text": button.get("text"),
           "value": str(button.get("value") or ""), "type": "button", "action_ts": _stamp()}
    if button.get("style"):
        act["style"] = button["style"]
    p["actions"] = [act]
    return env


def fill(view: dict[str, Any], picks: dict[str, Any] | None = None) -> dict[str, Any]:
    """A form's ``state.values`` as Slack sends them: ``picks`` maps a block
    id to option numbers (a list, or "0,2") or to text; the rest is empty."""
    picks = picks or {}
    values: dict[str, Any] = {}
    for block in view.get("blocks") or []:
        if block.get("type") != "input":
            continue
        bid, el = str(block.get("block_id") or ""), block.get("element") or {}
        kind, aid = str(el.get("type") or ""), str(el.get("action_id") or "")
        want = picks.get(bid)
        field: dict[str, Any] = {"type": kind}
        if kind in ("radio_buttons", "static_select", "checkboxes", "multi_static_select"):
            options = el.get("options") or []
            if isinstance(want, str):
                want = [int(n) for n in want.split(",") if n.strip()]
            elif isinstance(want, int):
                want = [want]
            chosen = [copy.deepcopy(options[n]) for n in (want or []) if 0 <= n < len(options)]
            if kind in ("checkboxes", "multi_static_select"):
                field["selected_options"] = chosen
            else:
                field["selected_option"] = chosen[0] if chosen else None
        else:
            field["value"] = None if want is None else str(want)
        values[bid] = {aid: field}
    return values


def submit(where: Where, view: dict[str, Any], picks: dict[str, Any] | None = None) -> dict[str, Any]:
    """The form ``view`` (as the test entry kept it for a fake Answer click) sent, filled in with ``picks``."""
    env = template("submit")
    p = env["payload"]
    p["user"].update(id=where.user, team_id=where.team)
    p["team"]["id"] = where.team
    sent = copy.deepcopy(view)
    sent["state"] = {"values": fill(view, picks)}
    sent.setdefault("team_id", where.team)
    p["view"] = sent
    return env


def token_paths(value: Any, path: str = "") -> list[str]:
    """Where a real-looking token sits in an envelope (for the no-token check)."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if key in TOKEN_KEYS and item:
                found.append(here)
            found.extend(token_paths(item, here))
    elif isinstance(value, list):
        for n, item in enumerate(value):
            found.extend(token_paths(item, f"{path}[{n}]"))
    elif isinstance(value, str) and value.startswith(("xoxb-", "xoxp-", "xapp-", "xoxe-")):
        found.append(path)
    return found
