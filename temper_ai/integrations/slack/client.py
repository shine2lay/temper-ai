"""The few Slack Web API calls temper makes, over plain httpx.

Two tokens, both from the environment (``~/temper-ai/.env``):

* ``SLACK_BOT_TOKEN`` (``xoxb-``): acts as the temper bot. Posts, edits,
  reads threads, opens DMs.
* ``SLACK_APP_TOKEN`` (``xapp-``, scope ``connections:write``): only opens
  the Socket Mode connection Slack pushes commands, mentions and button
  clicks down (see :mod:`.socket`).

Every call is form-encoded (some read methods, e.g. conversations.replies,
do not take JSON bodies) with list/dict values sent as JSON strings. A
``429`` is waited out once, for as long as Slack's ``Retry-After`` says (up
to 30 s); a second one is an error like any other.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API = "https://slack.com/api"
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
APP_TOKEN_ENV = "SLACK_APP_TOKEN"
MAX_RETRY_AFTER_S = 30.0

# What the app needs (the manifest asks for these; `temper slack check` compares).
REQUIRED_SCOPES = (
    "app_mentions:read", "channels:history", "channels:read", "chat:write", "chat:write.public",
    "commands", "groups:history", "im:history", "im:write", "users:read",
)


class SlackError(RuntimeError):
    """Slack answered ``ok: false`` (``error`` is its code, e.g. not_in_channel)."""

    def __init__(self, method: str, error: str, detail: Any = None) -> None:
        super().__init__(f"{method}: {error}")
        self.method = method
        self.error = error
        self.detail = detail


def bot_token() -> str:
    return os.environ.get(BOT_TOKEN_ENV, "").strip()


def app_token() -> str:
    return os.environ.get(APP_TOKEN_ENV, "").strip()


def _form(params: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            out[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


class SlackClient:
    """A bot-token client. ``http`` is injectable for tests."""

    def __init__(self, token: str | None = None, *, api: str = API, timeout: float = 15.0,
                 http: httpx.Client | None = None) -> None:
        self.token = token if token is not None else bot_token()
        self.api = api.rstrip("/")
        self._http = http or httpx.Client(timeout=timeout)
        self._dm_cache: dict[str, str] = {}
        self._lock = threading.Lock()
        self.scopes: tuple[str, ...] = ()

    # -- the one primitive ------------------------------------------------

    def call(self, method: str, token: str | None = None, **params: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token or self.token}"}
        for attempt in (1, 2):
            response = self._http.post(f"{self.api}/{method}", data=_form(params), headers=headers)
            if response.status_code == 429 and attempt == 1:
                wait = min(float(response.headers.get("Retry-After", "1") or 1), MAX_RETRY_AFTER_S)
                logger.info("Slack %s rate limited; waiting %.0fs", method, wait)
                time.sleep(wait)
                continue
            break
        if response.status_code >= 400 and response.status_code != 429:
            raise SlackError(method, f"http_{response.status_code}", response.text[:300])
        try:
            data = response.json()
        except ValueError as exc:
            raise SlackError(method, "not_json", response.text[:300]) from exc
        if response.headers.get("x-oauth-scopes"):
            self.scopes = tuple(s.strip() for s in response.headers["x-oauth-scopes"].split(",") if s.strip())
        if not data.get("ok"):
            raise SlackError(method, str(data.get("error") or "unknown_error"), data)
        return data

    # -- what temper does with it ----------------------------------------

    def auth_test(self) -> dict[str, Any]:
        return self.call("auth.test")

    def post(self, channel: str, text: str, blocks: list[dict] | None = None,
             thread_ts: str | None = None, broadcast: bool = False) -> dict[str, Any]:
        """Post a message; returns Slack's answer (``channel`` and ``ts``).

        ``broadcast`` shows a thread reply in the channel too, so it is seen
        (and notifies) without opening the thread.
        """
        return self.call("chat.postMessage", channel=channel, text=text, blocks=blocks,
                         thread_ts=thread_ts, reply_broadcast=bool(thread_ts and broadcast) or None,
                         unfurl_links=False, unfurl_media=False)

    def update(self, channel: str, ts: str, text: str, blocks: list[dict] | None = None) -> dict[str, Any]:
        return self.call("chat.update", channel=channel, ts=ts, text=text,
                         blocks=blocks if blocks is not None else [])

    def replies(self, channel: str, ts: str, limit: int = 100) -> list[dict[str, Any]]:
        data = self.call("conversations.replies", channel=channel, ts=ts, limit=limit)
        return list(data.get("messages") or [])

    def open_dm(self, user: str) -> str:
        """The DM channel between the bot and ``user`` (cached)."""
        with self._lock:
            if user in self._dm_cache:
                return self._dm_cache[user]
        channel = self.call("conversations.open", users=user)["channel"]["id"]
        with self._lock:
            self._dm_cache[user] = channel
        return channel

    def resolve(self, target: str) -> str:
        """A channel id for a channel id, ``#name`` or user id (its DM)."""
        target = target.strip()
        if target.startswith(("U", "W")) and not target.startswith("#"):
            return self.open_dm(target)
        if target.startswith("#"):
            return self.channel_id(target[1:])
        return target

    def channel_id(self, name: str) -> str:
        cursor = None
        for _ in range(20):
            data = self.call("conversations.list", types="public_channel", exclude_archived=True,
                             limit=200, cursor=cursor)
            for ch in data.get("channels") or []:
                if ch.get("name") == name:
                    return str(ch["id"])
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
        raise SlackError("conversations.list", "channel_not_found", name)

    def user_name(self, user: str) -> str:
        try:
            info = self.call("users.info", user=user).get("user") or {}
        except SlackError:
            return user
        profile = info.get("profile") or {}
        return str(profile.get("display_name") or info.get("real_name") or info.get("name") or user)

    def respond(self, response_url: str, payload: dict[str, Any]) -> None:
        """Answer a slash command or button click through its response_url."""
        response = self._http.post(response_url, json=payload)
        if response.status_code >= 400:
            raise SlackError("response_url", f"http_{response.status_code}", response.text[:300])

    def open_socket_url(self, token: str | None = None) -> str:
        """A fresh Socket Mode URL (needs the app-level token)."""
        return str(self.call("apps.connections.open", token=token or app_token())["url"])
