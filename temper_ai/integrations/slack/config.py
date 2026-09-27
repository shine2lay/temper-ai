"""Where Slack notices go: ``configs/slack/slack.yaml``.

The real routing usually lives in ``configs/slack/local/slack.yaml``
(git-ignored, since it names people's Slack ids); when that file exists it
is used instead of the tracked one, which documents the format. (Its own
directory, so the workflow-config importer passes it by.)::

    slack:
      dashboard_url: https://temper.example.com   # run links in messages
      stuck_after: 45m          # no new event for this long: "stuck"
      notify:                   # every workflow, unless overridden below
        gate:     {dm: U0123ABCD}             # a gate is waiting: Approve / Reject
        stuck:    {dm: U0123ABCD}
        failed:   {dm: U0123ABCD, channel: C0456EFGH}
        finished: {channel: "#temper-runs"}   # completed or cancelled
      workflows:                # per workflow: replaces the default for the kinds it names
        slack_pick: off         # every kind off
        epd_plan_grade: {finished: off}
      agents:                   # where the Slack agent tools may post; nowhere else
        - dm: U0123ABCD
        - channel: C0456EFGH
      test_door:                # the private test entry (docs/slack.md); false turns it off
        channel: "#temper-qa"   # the only channel fake events may name (a private one by its id)
        user: U0123ABCD         # who fake events come from (default: the first agents dm)

A destination is a channel and/or a DM: ``channel`` is a channel id
(``C…``/``G…``) or ``#name``; ``dm`` is a user id (``U…``/``W…``). Either
may be a list. ``off`` (or ``false``/``null``) sends nothing.

"finished" is every end but failure (completed, cancelled); a failed run
gets the "failed" notice instead, never both.

``test_door`` is on unless it is ``false``; it still needs its own secret
(``TEMPER_SLACK_TEST_TOKEN``) or the API token before it takes anything.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

KINDS = ("gate", "stuck", "failed", "finished")
DEFAULT_STUCK_AFTER = timedelta(minutes=45)

_CHANNEL = re.compile(r"^(?:[CG][A-Z0-9]{6,}|D[A-Z0-9]{6,}|#[a-z0-9][a-z0-9._-]{0,79})$")
_USER = re.compile(r"^[UW][A-Z0-9]{6,}$")
_OFF = ("off", "none", "no", "false")


class SlackConfigError(ValueError):
    """The Slack config file says something temper cannot use."""


@dataclass(frozen=True)
class Destination:
    channels: tuple[str, ...] = ()
    users: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.channels or self.users)

    def describe(self) -> str:
        parts = [c if c.startswith("#") else f"<#{c}>" for c in self.channels]
        parts += [f"DM <@{u}>" for u in self.users]
        return ", ".join(parts) or "nowhere"


NOWHERE = Destination()
DEFAULT_TEST_CHANNEL = "#temper-qa"


@dataclass(frozen=True)
class DoorSettings:
    """The Slack test entry (POST /api/test/slack): on or off, which
    channel fakes may name, and whose Slack user they act as."""

    on: bool = True
    channel: str = DEFAULT_TEST_CHANNEL
    user: str = ""


def channel_problem(channel: str, error: str) -> str:
    """Why the test channel can't be used, and what to do about it.

    The bot looks a ``#name`` up among public channels only: finding a
    private one by name needs Slack's groups:read, which temper's app
    doesn't ask for. A private test channel is given by its id instead.
    """
    text = f"can't find the test channel {channel}: {error}"
    if channel.startswith("#") and error == "channel_not_found":
        text += (". If it is a private channel, give its id (C…) as test_door.channel in "
                 "configs/slack/local/slack.yaml: the bot can't look up a private channel by name")
    return text


@dataclass
class SlackConfig:
    dashboard_url: str = ""
    stuck_after: timedelta = DEFAULT_STUCK_AFTER
    notify: dict[str, Destination] = field(default_factory=dict)
    workflows: dict[str, dict[str, Destination]] = field(default_factory=dict)
    agents: Destination = NOWHERE
    test_door: DoorSettings = field(default_factory=DoorSettings)
    path: str = ""

    def route(self, kind: str, workflow: str | None) -> Destination:
        """Where a notice of ``kind`` about a run of ``workflow`` goes."""
        per = self.workflows.get(workflow or "")
        if per is not None and kind in per:
            return per[kind]
        return self.notify.get(kind, NOWHERE)

    def run_url(self, execution_id: str) -> str:
        base = self.dashboard_url.rstrip("/")
        return f"{base}/app/workflow/{execution_id}" if base else ""

    def agent_may_post(self, channel: str) -> bool:
        return channel in self.agents.channels or channel in self.agents.users

    def test_user(self) -> str:
        """Who fake Slack events come from: ``test_door.user``, else the
        first person the agent tools may DM (the owner)."""
        return self.test_door.user or next(iter(self.agents.users), "")


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "configs"


def config_path(config_dir: str | Path | None = None) -> Path | None:
    """The file in use: the local one if it exists, else the tracked one."""
    root = (Path(config_dir) if config_dir else default_config_dir()) / "slack"
    for candidate in (root / "local" / "slack.yaml", root / "slack.yaml"):
        if candidate.is_file():
            return candidate
    return None


def _duration(value: Any, where: str) -> timedelta:
    from temper_ai.triggers.cron import CronError, parse_duration

    try:
        return timedelta(seconds=parse_duration(value))
    except (CronError, ValueError) as exc:
        raise SlackConfigError(f"{where}: {exc}") from exc


def _names(value: Any, pattern: re.Pattern[str], what: str, where: str) -> tuple[str, ...]:
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        text = str(item or "").strip()
        if not pattern.match(text):
            raise SlackConfigError(f"{where}: {text!r} is not a {what}")
        out.append(text)
    return tuple(out)


def parse_destination(value: Any, where: str) -> Destination:
    if value is None or value is False or (isinstance(value, str) and value.strip().lower() in _OFF):
        return NOWHERE
    if not isinstance(value, dict):
        raise SlackConfigError(f"{where}: expected {{channel: ..., dm: ...}} or off, got {value!r}")
    unknown = set(value) - {"channel", "dm"}
    if unknown:
        raise SlackConfigError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} (use channel and/or dm)")
    channels = _names(value["channel"], _CHANNEL, "channel id (C…) or #name", f"{where}.channel") if value.get("channel") else ()
    users = _names(value["dm"], _USER, "user id (U…)", f"{where}.dm") if value.get("dm") else ()
    return Destination(channels=channels, users=users)


def _kinds(value: Any, where: str) -> dict[str, Destination]:
    if value is None or value is False or (isinstance(value, str) and value.strip().lower() in _OFF):
        return {kind: NOWHERE for kind in KINDS}
    if not isinstance(value, dict):
        raise SlackConfigError(f"{where}: expected a mapping of kinds ({', '.join(KINDS)}) or off")
    out = {}
    for kind, dest in value.items():
        if kind not in KINDS:
            raise SlackConfigError(f"{where}: unknown kind {kind!r} (one of {', '.join(KINDS)})")
        out[kind] = parse_destination(dest, f"{where}.{kind}")
    return out


def parse_config(raw: Any, path: str = "") -> SlackConfig:
    body = raw.get("slack", raw) if isinstance(raw, dict) else None
    if body is None and raw is None:
        return SlackConfig(path=path)
    if not isinstance(body, dict):
        raise SlackConfigError("expected a mapping under 'slack:'")
    unknown = set(body) - {"dashboard_url", "stuck_after", "notify", "workflows", "agents", "test_door"}
    if unknown:
        raise SlackConfigError(f"unknown key(s) under slack: {', '.join(sorted(unknown))}")
    cfg = SlackConfig(path=path)
    cfg.dashboard_url = str(body.get("dashboard_url") or "").strip()
    if cfg.dashboard_url and not cfg.dashboard_url.startswith(("http://", "https://")):
        raise SlackConfigError(f"dashboard_url: {cfg.dashboard_url!r} is not an http(s) URL")
    if body.get("stuck_after") is not None:
        cfg.stuck_after = _duration(body["stuck_after"], "stuck_after")
    notify = body.get("notify") or {}
    cfg.notify = _kinds(notify, "notify") if notify else {}
    workflows = body.get("workflows") or {}
    if not isinstance(workflows, dict):
        raise SlackConfigError("workflows: expected a mapping of workflow name to kinds")
    cfg.workflows = {str(name): _kinds(kinds, f"workflows.{name}") for name, kinds in workflows.items()}
    agents = body.get("agents") or []
    if isinstance(agents, dict):
        agents = [agents]
    if not isinstance(agents, list):
        raise SlackConfigError("agents: expected a list of {channel: ...} / {dm: ...}")
    channels: list[str] = []
    users: list[str] = []
    for i, item in enumerate(agents):
        dest = parse_destination(item, f"agents[{i}]")
        channels += dest.channels
        users += dest.users
    cfg.agents = Destination(channels=tuple(channels), users=tuple(users))
    cfg.test_door = parse_door(body.get("test_door", True))
    return cfg


def parse_door(value: Any) -> DoorSettings:
    """``test_door``: true/false, or {on, channel, user}."""
    if value is None or isinstance(value, bool):
        return DoorSettings(on=value is not False)
    if isinstance(value, str) and value.strip().lower() in _OFF:
        return DoorSettings(on=False)
    if not isinstance(value, dict):
        raise SlackConfigError(f"test_door: expected true, false or {{channel: ..., user: ...}}, got {value!r}")
    unknown = set(value) - {"on", "channel", "user"}
    if unknown:
        raise SlackConfigError(f"test_door: unknown key(s) {', '.join(sorted(unknown))} (use on, channel, user)")
    on = value.get("on", True)
    if not isinstance(on, bool):
        raise SlackConfigError(f"test_door.on: expected true or false, got {on!r}")
    channel = str(value.get("channel") or DEFAULT_TEST_CHANNEL).strip()
    if not _CHANNEL.match(channel) or channel.startswith("D"):
        raise SlackConfigError(f"test_door.channel: {channel!r} is not a channel id (C…) or #name")
    user = str(value.get("user") or "").strip()
    if user and not _USER.match(user):
        raise SlackConfigError(f"test_door.user: {user!r} is not a user id (U…)")
    return DoorSettings(on=on, channel=channel, user=user)


def load_config(config_dir: str | Path | None = None) -> SlackConfig:
    """The Slack config in use; an empty one (nothing is sent) when there is none."""
    path = config_path(config_dir)
    if path is None:
        return SlackConfig()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise SlackConfigError(f"{path}: not valid YAML: {exc}") from exc
    try:
        return parse_config(raw, str(path))
    except SlackConfigError as exc:
        raise SlackConfigError(f"{path}: {exc}") from exc


class ConfigWatcher:
    """Re-reads the file when it changes; keeps the last good config when
    a change breaks it (and says so once)."""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        self.config_dir = config_dir
        self._stamp: tuple[str, float] | None = None
        self._config = SlackConfig()
        self.error: str | None = None

    def get(self) -> SlackConfig:
        path = config_path(self.config_dir)
        stamp = (str(path), path.stat().st_mtime) if path else ("", 0.0)
        if stamp != self._stamp:
            self._stamp = stamp
            try:
                self._config = load_config(self.config_dir)
                self.error = None
            except SlackConfigError as exc:
                self.error = str(exc)
                logger.warning("Slack config not used (keeping the previous one): %s", exc)
        return self._config
