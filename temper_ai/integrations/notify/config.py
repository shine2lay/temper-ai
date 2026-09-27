"""Where temper's notices and questions go: ``configs/notify/notify.yaml``.

The real settings usually live in ``configs/notify/local/notify.yaml``
(git-ignored, since it names people's Slack and Telegram ids); when that
file exists it is used instead of the tracked one, which documents the
format and sends nothing. Changes are picked up without a restart::

    notify:
      dashboard_url: https://temper.example.com   # run links in messages
      stuck_after: 45m          # no new event for this long: "stuck"
      places:                   # names for the places messages can go
        slack:    {slack: {dm: U0123ABCD}}
        runs:     {slack: {channel: "#temper-runs"}}
        telegram: {telegram: 123456789}           # a chat id
      defaults:                 # every run, unless its workflow says otherwise
        question: origin        # back where the run was started from
        failed:   [origin, telegram]
      fallback:                 # when a run's list comes to nothing
        question: slack
        stuck: slack
        failed: slack
        finished: slack
      workflows:                # per workflow; replaces the kinds it names
        nightly_report: {finished: runs}
      quiet_hours: {from: "22:00", to: "07:00", zone: America/Los_Angeles,
                    still_ping: [question]}
      nudge: {after: 30m, to: telegram}   # a question nobody answered
      agents: [telegram]        # where the TelegramSend tool may post

Kinds: ``question`` (a gate is waiting), ``stuck``, ``failed`` and
``finished`` (completed or cancelled). A route is ``origin``, a place
name, a list of those, or ``off``. A workflow file may carry the same
settings under its own ``notify:`` key (see :func:`parse_block`); only
place names go there, never ids.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

logger = logging.getLogger(__name__)

KINDS = ("question", "stuck", "failed", "finished")
ORIGIN = "origin"
VIAS = ("slack", "telegram")
DEFAULT_STUCK_AFTER = timedelta(minutes=45)
DEFAULT_ZONE = "America/Los_Angeles"
BLOCK_KEYS = set(KINDS) | {"quiet_hours", "nudge"}

_OFF = ("off", "none", "no", "false")
_PLACE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_SLACK_CHANNEL = re.compile(r"^(?:[CG][A-Z0-9]{6,}|D[A-Z0-9]{6,}|#[a-z0-9][a-z0-9._-]{0,79})$")
_SLACK_USER = re.compile(r"^[UW][A-Z0-9]{6,}$")
_TELEGRAM_CHAT = re.compile(r"^-?\d{1,20}$")
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class NotifyConfigError(ValueError):
    """The notify settings say something temper cannot use."""


def _is_off(value: Any) -> bool:
    return value is None or value is False or (isinstance(value, str) and value.strip().lower() in _OFF)


@dataclass(frozen=True)
class Place:
    name: str
    via: str       # slack | telegram
    target: str    # slack: C…/#name/U…; telegram: a chat id

    def describe(self) -> str:
        return f"{self.name} ({self.via} {self.target})"


@dataclass(frozen=True)
class QuietHours:
    start: time
    end: time
    zone: str = DEFAULT_ZONE
    still_ping: tuple[str, ...] = ("question",)

    def _local(self, now: datetime) -> datetime:
        return now.astimezone(ZoneInfo(self.zone))

    def covers(self, now: datetime) -> bool:
        t = self._local(now).time()
        if self.start == self.end:
            return False
        if self.start < self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end

    def ends_after(self, now: datetime) -> datetime:
        """When the quiet window that ``now`` is in ends."""
        local = self._local(now)
        end = local.replace(hour=self.end.hour, minute=self.end.minute, second=0, microsecond=0)
        if end <= local:
            end += timedelta(days=1)
        return end

    def holds(self, kind: str, now: datetime) -> datetime | None:
        """When a notice of ``kind`` sent at ``now`` should go out instead; None: now."""
        if kind in self.still_ping or not self.covers(now):
            return None
        return self.ends_after(now)

    def describe(self) -> str:
        return (f"{self.start:%H:%M}-{self.end:%H:%M} {self.zone}"
                + (f", still pings for {', '.join(self.still_ping)}" if self.still_ping else ""))


@dataclass(frozen=True)
class Nudge:
    after: timedelta
    to: tuple[str, ...]

    def describe(self) -> str:
        return f"after {int(self.after.total_seconds() // 60)} min to {', '.join(self.to)}"


# A block's quiet_hours / nudge: None = not set here, False = turned off here.
QuietSetting = QuietHours | bool | None
NudgeSetting = Nudge | bool | None


@dataclass(frozen=True)
class Block:
    """One layer of settings: the shared defaults, a workflow's, a run's."""

    routes: dict[str, tuple[str, ...]] = field(default_factory=dict)   # () = off
    quiet_hours: QuietSetting = None
    nudge: NudgeSetting = None

    def names(self) -> set[str]:
        """The place names this block mentions (origin not included)."""
        out = {item for items in self.routes.values() for item in items}
        if isinstance(self.nudge, Nudge):
            out |= set(self.nudge.to)
        out.discard(ORIGIN)
        return out


EMPTY = Block()


@dataclass
class NotifyConfig:
    dashboard_url: str = ""
    stuck_after: timedelta = DEFAULT_STUCK_AFTER
    places: dict[str, Place] = field(default_factory=dict)
    defaults: Block = EMPTY
    fallback: dict[str, tuple[str, ...]] = field(default_factory=dict)
    workflows: dict[str, Block] = field(default_factory=dict)
    agents: tuple[str, ...] = ()
    path: str = ""

    def run_url(self, execution_id: str) -> str:
        base = self.dashboard_url.rstrip("/")
        return f"{base}/app/workflow/{execution_id}" if base else ""

    def layers(self, workflow: str | None, workflow_block: Block | None = None,
               run_block: Block | None = None) -> list[Block]:
        """Most specific first: the run's, the workflow file's, this file's
        per-workflow entry, the defaults."""
        return [b for b in (run_block, workflow_block, self.workflows.get(workflow or ""), self.defaults)
                if b is not None]

    def route(self, kind: str, workflow: str | None, workflow_block: Block | None = None,
              run_block: Block | None = None) -> tuple[str, ...]:
        """Where a ``kind`` notice about a run goes, before origin and names
        are looked up. () means off."""
        for block in self.layers(workflow, workflow_block, run_block):
            if kind in block.routes:
                return block.routes[kind]
        return (ORIGIN,)

    def quiet_hours(self, workflow: str | None, workflow_block: Block | None = None,
                    run_block: Block | None = None) -> QuietHours | None:
        for block in self.layers(workflow, workflow_block, run_block):
            if block.quiet_hours is not None:
                return block.quiet_hours if isinstance(block.quiet_hours, QuietHours) else None
        return None

    def nudge(self, workflow: str | None, workflow_block: Block | None = None,
              run_block: Block | None = None) -> Nudge | None:
        for block in self.layers(workflow, workflow_block, run_block):
            if block.nudge is not None:
                return block.nudge if isinstance(block.nudge, Nudge) else None
        return None

    def unknown_places(self, block: Block) -> list[str]:
        return sorted(n for n in block.names() if n not in self.places)

    def agent_places(self, via: str) -> dict[str, Place]:
        """The places of ``via`` an agent tool may post to, by name."""
        return {n: self.places[n] for n in self.agents if n in self.places and self.places[n].via == via}


# -- parsing -------------------------------------------------------------------


def _duration(value: Any, where: str) -> timedelta:
    from temper_ai.triggers.cron import CronError, parse_duration

    try:
        return timedelta(seconds=parse_duration(value))
    except (CronError, ValueError) as exc:
        raise NotifyConfigError(f"{where}: {exc}") from exc


def _clock(value: Any, where: str) -> time:
    if isinstance(value, int) and not isinstance(value, bool):
        # YAML reads an unquoted 22:00 as the number of minutes (1320).
        value = f"{value // 60}:{value % 60:02d}"
    match = _CLOCK.match(str(value or "").strip())
    if not match:
        raise NotifyConfigError(f"{where}: {value!r} is not a time like \"22:00\"")
    return time(int(match.group(1)), int(match.group(2)))


def _zone(value: Any, where: str) -> str:
    name = str(value or DEFAULT_ZONE).strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise NotifyConfigError(f"{where}: unknown time zone {name!r}") from exc
    return name


def parse_route(value: Any, where: str) -> tuple[str, ...]:
    """``origin``, a place name, a list of those, or off (())."""
    if _is_off(value):
        return ()
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        name = str(item or "").strip()
        if not isinstance(item, str) or not (name == ORIGIN or _PLACE_NAME.match(name)):
            raise NotifyConfigError(f"{where}: {item!r} is not origin or a place name "
                                    "(a place's id goes in the notify config, not here)")
        if name not in out:
            out.append(name)
    return tuple(out)


def parse_quiet_hours(value: Any, where: str) -> QuietSetting:
    if _is_off(value):
        return False
    if not isinstance(value, dict):
        raise NotifyConfigError(f"{where}: expected {{from: \"22:00\", to: \"07:00\", zone: ...}} or off")
    unknown = set(value) - {"from", "to", "zone", "still_ping"}
    if unknown:
        raise NotifyConfigError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    if "from" not in value or "to" not in value:
        raise NotifyConfigError(f"{where}: needs both from and to")
    still = value.get("still_ping", ["question"])
    still_items = () if _is_off(still) else tuple(str(k) for k in (still if isinstance(still, list) else [still]))
    for kind in still_items:
        if kind not in KINDS:
            raise NotifyConfigError(f"{where}.still_ping: unknown kind {kind!r} (one of {', '.join(KINDS)})")
    return QuietHours(start=_clock(value["from"], f"{where}.from"), end=_clock(value["to"], f"{where}.to"),
                      zone=_zone(value.get("zone"), f"{where}.zone"), still_ping=still_items)


def parse_nudge(value: Any, where: str) -> NudgeSetting:
    if _is_off(value):
        return False
    if not isinstance(value, dict):
        raise NotifyConfigError(f"{where}: expected {{after: 30m, to: <place>}} or off")
    unknown = set(value) - {"after", "to"}
    if unknown:
        raise NotifyConfigError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    to = parse_route(value.get("to"), f"{where}.to")
    if not to:
        raise NotifyConfigError(f"{where}: needs to: <place>")
    if ORIGIN in to:
        raise NotifyConfigError(f"{where}.to: a nudge goes somewhere else than origin; name a place")
    return Nudge(after=_duration(value.get("after", "30m"), f"{where}.after"), to=to)


def parse_block(value: Any, where: str = "notify") -> Block:
    """A ``notify:`` block: per kind a route, plus quiet_hours and nudge.

    ``off`` alone turns every kind off. Used for the shared defaults, the
    per-workflow entries, a workflow file's own ``notify:`` and a run's.
    """
    if _is_off(value):
        return Block(routes={kind: () for kind in KINDS})
    if not isinstance(value, dict):
        raise NotifyConfigError(f"{where}: expected a mapping of kinds ({', '.join(KINDS)}), "
                                "quiet_hours and nudge, or off")
    unknown = set(value) - BLOCK_KEYS
    if unknown:
        raise NotifyConfigError(f"{where}: unknown key(s) {', '.join(sorted(map(str, unknown)))} "
                                f"(use {', '.join(KINDS)}, quiet_hours, nudge)")
    routes = {kind: parse_route(value[kind], f"{where}.{kind}") for kind in KINDS if kind in value}
    quiet = parse_quiet_hours(value["quiet_hours"], f"{where}.quiet_hours") if "quiet_hours" in value else None
    nudge = parse_nudge(value["nudge"], f"{where}.nudge") if "nudge" in value else None
    return Block(routes=routes, quiet_hours=quiet, nudge=nudge)


def parse_place(name: str, value: Any) -> Place:
    where = f"places.{name}"
    if not _PLACE_NAME.match(name) or name == ORIGIN:
        raise NotifyConfigError(f"{where}: a place name is lower-case letters, digits, - and _ (not origin)")
    if not isinstance(value, dict) or len(value) != 1:
        raise NotifyConfigError(f"{where}: expected {{slack: {{dm: U…}}}}, {{slack: {{channel: C…}}}} "
                                "or {telegram: <chat id>}")
    via, spec = next(iter(value.items()))
    if via == "telegram":
        target = str(spec).strip()
        if not _TELEGRAM_CHAT.match(target):
            raise NotifyConfigError(f"{where}.telegram: {spec!r} is not a chat id (a number)")
        return Place(name, "telegram", target)
    if via == "slack":
        if not isinstance(spec, dict) or len(spec) != 1 or next(iter(spec)) not in ("dm", "channel"):
            raise NotifyConfigError(f"{where}.slack: expected {{dm: U…}} or {{channel: C…/#name}}")
        key, raw = next(iter(spec.items()))
        target = str(raw or "").strip()
        pattern = _SLACK_USER if key == "dm" else _SLACK_CHANNEL
        if not pattern.match(target):
            raise NotifyConfigError(f"{where}.slack.{key}: {raw!r} is not a "
                                    + ("user id (U…)" if key == "dm" else "channel id (C…) or #name"))
        return Place(name, "slack", target)
    raise NotifyConfigError(f"{where}: unknown kind of place {via!r} (one of {', '.join(VIAS)})")


def parse_config(raw: Any, path: str = "") -> NotifyConfig:
    body = raw.get("notify", raw) if isinstance(raw, dict) else None
    if body is None and raw is None:
        return NotifyConfig(path=path)
    if not isinstance(body, dict):
        raise NotifyConfigError("expected a mapping under 'notify:'")
    allowed = {"dashboard_url", "stuck_after", "places", "defaults", "fallback", "workflows",
               "quiet_hours", "nudge", "agents"}
    unknown = set(body) - allowed
    if unknown:
        raise NotifyConfigError(f"unknown key(s) under notify: {', '.join(sorted(unknown))}")
    cfg = NotifyConfig(path=path)
    cfg.dashboard_url = str(body.get("dashboard_url") or "").strip()
    if cfg.dashboard_url and not cfg.dashboard_url.startswith(("http://", "https://")):
        raise NotifyConfigError(f"dashboard_url: {cfg.dashboard_url!r} is not an http(s) URL")
    if body.get("stuck_after") is not None:
        cfg.stuck_after = _duration(body["stuck_after"], "stuck_after")
    places = body.get("places") or {}
    if not isinstance(places, dict):
        raise NotifyConfigError("places: expected a mapping of name to place")
    cfg.places = {str(n): parse_place(str(n), v) for n, v in places.items()}

    defaults = body.get("defaults") or {}
    base = parse_block(defaults, "defaults") if defaults else EMPTY
    if "quiet_hours" in body:
        base = Block(routes=base.routes, quiet_hours=parse_quiet_hours(body["quiet_hours"], "quiet_hours"),
                     nudge=base.nudge)
    if "nudge" in body:
        base = Block(routes=base.routes, quiet_hours=base.quiet_hours, nudge=parse_nudge(body["nudge"], "nudge"))
    cfg.defaults = base

    fallback = body.get("fallback") or {}
    if not isinstance(fallback, dict):
        raise NotifyConfigError("fallback: expected a mapping of kind to route")
    for kind, value in fallback.items():
        if kind not in KINDS:
            raise NotifyConfigError(f"fallback: unknown kind {kind!r} (one of {', '.join(KINDS)})")
        route = parse_route(value, f"fallback.{kind}")
        if ORIGIN in route:
            raise NotifyConfigError(f"fallback.{kind}: the fallback is for runs with no origin; name a place")
        cfg.fallback[str(kind)] = route

    workflows = body.get("workflows") or {}
    if not isinstance(workflows, dict):
        raise NotifyConfigError("workflows: expected a mapping of workflow name to a notify block")
    cfg.workflows = {str(n): parse_block(v, f"workflows.{n}") for n, v in workflows.items()}

    agents = body.get("agents") or []
    cfg.agents = parse_route(agents if isinstance(agents, list) else [agents], "agents")
    if ORIGIN in cfg.agents:
        raise NotifyConfigError("agents: name places; a run's own chat is always allowed")

    for where, block in [("defaults", cfg.defaults)] + [(f"workflows.{n}", b) for n, b in cfg.workflows.items()]:
        missing = cfg.unknown_places(block)
        if missing:
            raise NotifyConfigError(f"{where}: no place named {', '.join(missing)} under places")
    for kind, route in cfg.fallback.items():
        missing = sorted(n for n in route if n not in cfg.places)
        if missing:
            raise NotifyConfigError(f"fallback.{kind}: no place named {', '.join(missing)} under places")
    missing = sorted(n for n in cfg.agents if n not in cfg.places)
    if missing:
        raise NotifyConfigError(f"agents: no place named {', '.join(missing)} under places")
    return cfg


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "configs"


def config_path(config_dir: str | Path | None = None) -> Path | None:
    """The file in use: the local one if it exists, else the tracked one."""
    root = (Path(config_dir) if config_dir else default_config_dir()) / "notify"
    for candidate in (root / "local" / "notify.yaml", root / "notify.yaml"):
        if candidate.is_file():
            return candidate
    return None


def load_config(config_dir: str | Path | None = None) -> NotifyConfig:
    """The settings in use; an empty set (nothing is sent) when there are none."""
    path = config_path(config_dir)
    if path is None:
        return NotifyConfig()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise NotifyConfigError(f"{path}: not valid YAML: {exc}") from exc
    try:
        return parse_config(raw, str(path))
    except NotifyConfigError as exc:
        raise NotifyConfigError(f"{path}: {exc}") from exc


class ConfigWatcher:
    """Re-reads the file when it changes; keeps the last good settings when
    a change breaks them (and says so once)."""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        self.config_dir = config_dir
        self._stamp: tuple[str, float] | None = None
        self._config = NotifyConfig()
        self.error: str | None = None

    def get(self) -> NotifyConfig:
        path = config_path(self.config_dir)
        stamp = (str(path), path.stat().st_mtime) if path else ("", 0.0)
        if stamp != self._stamp:
            self._stamp = stamp
            try:
                self._config = load_config(self.config_dir)
                self.error = None
            except NotifyConfigError as exc:
                self.error = str(exc)
                logger.warning("Notify config not used (keeping the previous one): %s", exc)
        return self._config
