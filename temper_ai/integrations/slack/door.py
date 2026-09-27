"""The Slack test entry: fake Slack events, handled exactly like real ones.

Temper's own tools can't drive Slack in a browser, so its Slack flows
(commands, button clicks, forms, @temper) are tested through a private
entry on temper's server instead (routes in ``api/slack_test.py``)::

    GET  /api/test/slack               on or off; the test channel and user
    POST /api/test/slack               a fake: an envelope shaped like Socket Mode's
    GET  /api/test/slack/fakes/{id}    what came of one fake
    POST /api/test/slack/replies/{id}  a fake's response link (temper answers there)

A fake goes where a real envelope goes: into the event inbox (its delivery
is ``test:<id>``, so it is listed and can be replayed like any other), then
to the same handler the socket uses. Messages temper posts land in Slack for
real. Only what can't be faked is swapped, at the edges:

- ``response_url``: Slack's reply link exists only for a real command or
  click. A fake's points back at this server, and what temper answers there
  is kept here for an hour (``temper slack fake`` prints it). An answer
  meant for everyone (``in_channel``) is posted in the channel by the bot,
  as Slack itself would post it.
- the user: a fake always acts as the owner (``test_door.user``, else the
  first person the Slack agent tools may DM), whatever it says.
- ``trigger_id``: a form opens only from a real click (the id lasts 3
  seconds). A fake click's starts with ``test.``; the form is still sent
  to Slack, which checks its blocks before it looks at the trigger, so
  ``invalid_trigger_id`` means Slack took the blocks. The form is kept
  here, so a fake submission can answer it.

The entry needs its own secret (``TEMPER_SLACK_TEST_TOKEN`` in
~/temper-ai/.env) or temper's API token, is never on the public hook
address, only takes fakes for the test channel (``test_door.channel``,
default #temper-qa), and ``test_door: false`` in the Slack config turns it
off.
"""

from __future__ import annotations

import copy
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from temper_ai.integrations.inbox import service as inbox
from temper_ai.integrations.slack.client import TEST_TRIGGER, SlackClient, SlackError
from temper_ai.integrations.slack.handlers import SOURCE, describe, inbox_key

logger = logging.getLogger(__name__)

SECRET_ENV = "TEMPER_SLACK_TEST_TOKEN"  # noqa: S105 - the variable's name
HEADER = "x-temper-test-token"
SELF_URL_ENV = "TEMPER_SELF_URL"
DEFAULT_SELF_URL = "http://127.0.0.1:8420"
REPLIES_PATH = "/api/test/slack/replies"
DELIVERY_PREFIX = "test:"
KINDS = ("slash_commands", "interactive", "events_api")
KEEP_S = 3600.0
MAX_FAKES = 500
MAX_ITEMS = 50  # replies, or forms, kept per fake
# Slack's answers for a trigger that can't open anything: it checked the form first.
DEAD_TRIGGER = ("invalid_trigger_id", "expired_trigger_id", "trigger_exchanged")


class DoorError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _iso(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds")


@dataclass
class Fake:
    id: str
    kind: str
    created: float
    channel: str = ""
    event_id: int | None = None
    replies: list[dict[str, Any]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)

    def brief(self) -> dict[str, Any]:
        return {"fake": self.id, "kind": self.kind, "channel": self.channel, "event_id": self.event_id,
                "created": _iso(self.created), "replies": copy.deepcopy(self.replies),
                "forms": copy.deepcopy(self.forms)}


class Fakes:
    """The last hour's fakes, in memory: their replies and forms."""

    def __init__(self, keep_s: float = KEEP_S, clock: Any = time.time) -> None:
        self._keep_s = keep_s
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, Fake] = {}

    def new(self, kind: str, channel: str = "") -> Fake:
        with self._lock:
            self._prune()
            fake = Fake(secrets.token_hex(12), kind, self._clock(), channel)
            self._items[fake.id] = fake
            return fake

    def get(self, fake_id: str) -> Fake | None:
        with self._lock:
            self._prune()
            return self._items.get(fake_id)

    def add_reply(self, fake_id: str, payload: Any, posted: str = "") -> bool:
        with self._lock:
            self._prune()
            fake = self._items.get(fake_id)
            if fake is None or len(fake.replies) >= MAX_ITEMS:
                return False
            item = {"at": _iso(self._clock()), "payload": copy.deepcopy(payload)}
            if posted:
                item["posted"] = posted
            fake.replies.append(item)
            return True

    def add_form(self, fake_id: str, view: dict[str, Any], verdict: str, problems: list[str]) -> bool:
        with self._lock:
            fake = self._items.get(fake_id)
            if fake is None or len(fake.forms) >= MAX_ITEMS:
                return False
            fake.forms.append({"at": _iso(self._clock()), "verdict": verdict, "problems": list(problems),
                               "view": copy.deepcopy(view)})
            return True

    def _prune(self) -> None:
        cutoff = self._clock() - self._keep_s
        for key in [k for k, f in self._items.items() if f.created < cutoff]:
            del self._items[key]
        while len(self._items) > MAX_FAKES:
            del self._items[next(iter(self._items))]


FAKES = Fakes()


# -- who may use it --------------------------------------------------------------------------

def secret() -> str:
    return os.environ.get(SECRET_ENV, "").strip()


def refused(test_token: str | None, api_token: str | None) -> tuple[int, str] | None:
    """None if the caller may use the entry, else (status, why not).

    The entry's own secret, or temper's API token (when one is set; the
    server's auth middleware has then checked it already)."""
    from temper_ai.api.auth import auth_enabled, identify

    mine = secret()
    if mine and test_token and hmac.compare_digest(test_token.encode(), mine.encode()):
        return None
    if api_token and auth_enabled() and identify(api_token):
        return None
    if not mine and not auth_enabled():
        return 403, (f"the Slack test entry takes nothing until it has a secret: set {SECRET_ENV} in "
                     "~/temper-ai/.env and recreate the server (or turn on temper's API token)")
    return 401, f"wrong or missing token (send {SECRET_ENV} as X-Temper-Test-Token, or the API token)"


def self_url() -> str:
    """Where this server answers itself: a fake's response link points here."""
    return (os.environ.get(SELF_URL_ENV, "").strip() or DEFAULT_SELF_URL).rstrip("/")


# -- where a fake may go ----------------------------------------------------------------------

_channel_ids: dict[str, str] = {}


def channel_id(client: SlackClient, channel: str) -> str:
    """The test channel's id (``#name`` looked up once)."""
    if not channel.startswith("#"):
        return channel
    if channel not in _channel_ids:
        _channel_ids[channel] = client.resolve(channel)
    return _channel_ids[channel]


def channel_of(envelope: dict[str, Any]) -> str:
    """The channel a fake happens in (a form: the one its question is in)."""
    kind, p = envelope.get("type"), envelope.get("payload") or {}
    if kind == "slash_commands":
        return str(p.get("channel_id") or "")
    if kind == "events_api":
        return str((p.get("event") or {}).get("channel") or "")
    if p.get("type") == "view_submission":
        try:
            meta = json.loads((p.get("view") or {}).get("private_metadata") or "{}")
        except ValueError:
            meta = {}
        return str(meta.get("channel") or "") if isinstance(meta, dict) else ""
    return str((p.get("channel") or {}).get("id") or (p.get("container") or {}).get("channel_id") or "")


# -- taking one -------------------------------------------------------------------------------

def owner_name(client: Any, user: str) -> str:
    """The owner's Slack name, which a real command or click carries (and
    temper writes down as who decided)."""
    try:
        name = str(client.user_name(user) or "")
    except Exception:  # noqa: BLE001 - without it the fake still works; temper shows the id
        return ""
    return "" if name == user else name


def prepare(envelope: dict[str, Any], fake: Fake, base_url: str, user: str, name: str = "") -> dict[str, Any]:
    """The fake as it is saved and handled: its own ids, reply link and
    trigger, and the owner (``user``, called ``name``) as the one who did it."""
    env = copy.deepcopy(envelope)
    env["envelope_id"] = f"test-{fake.id}"
    env["test"] = {"fake": fake.id}
    p = env["payload"]
    p.pop("token", None)
    kind = env.get("type")
    if kind == "slash_commands":
        p["user_id"], p["user_name"] = user, name
    elif kind == "interactive":
        who = p.get("user") if isinstance(p.get("user"), dict) else {}
        p["user"] = {**who, "id": user, "username": name, "name": name}
    elif isinstance(p.get("event"), dict):
        p["event"]["user"] = user
    if kind == "slash_commands" or (kind == "interactive" and p.get("type") == "block_actions"):
        p["response_url"] = f"{base_url.rstrip('/')}{REPLIES_PATH}/{fake.id}"
    if kind in ("slash_commands", "interactive"):
        p["trigger_id"] = f"{TEST_TRIGGER}{fake.id}"
    if kind == "interactive" and p.get("type") == "view_submission":
        p["response_urls"] = []
    if kind == "events_api":
        p["event_id"] = f"EvTEST{fake.id}"
    return env


def take(envelope: Any, *, service: Any, base_url: str | None = None, fakes: Fakes | None = None) -> dict[str, Any]:
    """Save a fake in the event inbox and give it to Slack's handler, as
    the socket does with a real one. Returns its id and inbox event."""
    fakes = FAKES if fakes is None else fakes
    if service is None:
        raise DoorError(503, "Slack is not running in this server (`temper slack check` says why)")
    door = service.config.get().test_door
    if not door.on:
        raise DoorError(403, "the Slack test entry is off (test_door: false in the Slack config)")
    if not isinstance(envelope, dict) or envelope.get("type") not in KINDS:
        raise DoorError(400, f"expected a Socket Mode envelope: type one of {', '.join(KINDS)}")
    if not isinstance(envelope.get("payload"), dict):
        raise DoorError(400, "the envelope has no payload")
    user = service.config.get().test_user()
    if not user:
        raise DoorError(503, "fakes act as the owner: set test_door.user (or an agents dm) in the Slack config")
    try:
        want = channel_id(service.client, door.channel)
    except SlackError as exc:
        raise DoorError(503, f"can't find the test channel {door.channel}: {exc.error}") from exc
    got = channel_of(envelope)
    if got != want:
        raise DoorError(400, f"fakes only go to {door.channel} ({want}); this one is for {got or 'no channel'}")
    fake = fakes.new(describe(envelope), got)
    env = prepare(envelope, fake, base_url or self_url(), user, owner_name(service.client, user))
    _, _, subject = inbox_key(env)
    try:
        event, _ = inbox.receive(SOURCE, f"{DELIVERY_PREFIX}{fake.id}", kind=f"test {fake.kind}",
                                 subject=subject, payload=env)
        fake.event_id = event.id
    except Exception:  # noqa: BLE001 - handled unsaved, as the socket does
        logger.exception("Slack test entry: could not save fake %s; handling it unsaved", fake.id)
    service.handler.submit(fake.event_id if fake.event_id is not None else env)
    logger.info("Slack test entry: fake %s (%s) in %s, inbox event %s", fake.id, fake.kind, got, fake.event_id)
    return {"fake": fake.id, "kind": fake.kind, "event_id": fake.event_id,
            "response_url": env["payload"].get("response_url"), "trigger_id": env["payload"].get("trigger_id")}


def reply(fake_id: str, payload: Any, *, service: Any, fakes: Fakes | None = None) -> bool:
    """Temper answered a fake's response link: keep it, and post an answer
    meant for everyone in the channel, as Slack does. False: no such fake."""
    fakes = FAKES if fakes is None else fakes
    fake = fakes.get(fake_id)
    if fake is None:
        return False
    posted = ""
    if (isinstance(payload, dict) and payload.get("response_type") == "in_channel" and fake.channel
            and service is not None):
        try:
            answer = service.client.post(fake.channel, str(payload.get("text") or " "), payload.get("blocks"))
            posted = str(answer.get("ts") or "")
        except SlackError as exc:
            posted = f"error: {exc.error}"
            logger.warning("Slack test entry: could not post fake %s's answer in %s: %s", fake_id, fake.channel, exc)
    return fakes.add_reply(fake_id, payload, posted)


def show(fake_id: str, fakes: Fakes | None = None) -> dict[str, Any] | None:
    """What came of a fake: its inbox event, its replies, its forms."""
    fakes = FAKES if fakes is None else fakes
    fake = fakes.get(fake_id)
    if fake is None:
        return None
    out = fake.brief()
    out["event"] = None
    if fake.event_id is not None:
        try:
            from temper_ai.integrations.inbox import store

            event = store.get(fake.event_id)
            out["event"] = event.brief() if event else None
        except Exception as exc:  # noqa: BLE001 - the rest is still worth showing
            out["event"] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def info(service: Any) -> dict[str, Any]:
    """Is the entry on, and which channel and user fakes use."""
    if service is None:
        return {"on": False, "slack": False, "reason": "Slack is not running in this server"}
    cfg = service.config.get()
    out: dict[str, Any] = {"on": cfg.test_door.on, "slack": True, "channel": cfg.test_door.channel,
                           "user": cfg.test_user(), "bot_user": getattr(service.handler, "bot_user", ""),
                           "team": str((getattr(service, "bot", None) or {}).get("team_id") or "")}
    try:
        out["channel_id"] = channel_id(service.client, cfg.test_door.channel)
    except SlackError as exc:
        out["channel_error"] = exc.error
    return out


# -- a fake click's form ----------------------------------------------------------------------

def slack_problems(exc: SlackError) -> list[str]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return [str(m) for m in ((detail.get("response_metadata") or {}).get("messages") or [])]


def open_view(client: SlackClient, trigger_id: str, view: dict[str, Any],
              fakes: Fakes | None = None) -> dict[str, Any]:
    """What ``views.open`` does for a fake click: Slack checks the form (its
    trigger can't open it), and the form is kept for a fake submission.

    Raises SlackError as a real ``views.open`` would when Slack refuses the
    form itself.
    """
    fakes = FAKES if fakes is None else fakes
    fake_id = trigger_id[len(TEST_TRIGGER):].split(".", 1)[0]
    verdict = "opened"
    try:
        client.call("views.open", trigger_id=trigger_id, view=view)
    except SlackError as exc:
        if exc.error not in DEAD_TRIGGER:
            fakes.add_form(fake_id, view, f"refused: {exc.error}", slack_problems(exc))
            raise
        verdict = "ok"
    # Kept as Slack would hand it back: its own id and hash (a submission
    # is handled once per id and hash), no answers yet.
    opened = {**view, "id": f"VTEST{secrets.token_hex(5).upper()}", "hash": f"{int(time.time())}.{secrets.token_hex(4)}",
              "state": {"values": {}}}
    fakes.add_form(fake_id, opened, verdict, [])
    return {"ok": True, "view": opened}
