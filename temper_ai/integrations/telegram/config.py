"""Who may use temper's Telegram bot, and how it shows times.

The real settings go in ``configs/telegram/local/telegram.yaml``
(git-ignored: it holds people's Telegram ids), used instead of the tracked
``configs/telegram/telegram.yaml`` when it exists. Changes are picked up
without a restart::

    telegram:
      owners: [123456789]      # user ids: their private chats may use the bot,
                               # and a group one of them adds it to is allowed
      groups: [-1001234567890] # groups allowed even if no owner added the bot
      zone: America/Los_Angeles

Where notices and questions go is not set here but in the notify file
(configs/notify/...): a place there is ``{telegram: <chat id>}``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

logger = logging.getLogger(__name__)

DEFAULT_ZONE = "America/Los_Angeles"


class TelegramConfigError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramConfig:
    owners: frozenset[int] = frozenset()
    groups: frozenset[int] = frozenset()
    zone: str = DEFAULT_ZONE
    path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.zone)


def _ids(value: Any, where: str) -> frozenset[int]:
    if value is None:
        return frozenset()
    items = value if isinstance(value, list) else [value]
    out = set()
    for item in items:
        try:
            out.add(int(str(item).strip()))
        except ValueError:
            raise TelegramConfigError(f"{where}: {item!r} is not a Telegram id (a number)") from None
    return frozenset(out)


def parse_config(raw: Any, path: str = "") -> TelegramConfig:
    if raw is None:
        return TelegramConfig(path=path)
    if not isinstance(raw, dict) or not isinstance(raw.get("telegram", {}), dict):
        raise TelegramConfigError("expected a mapping under `telegram:`")
    body = raw.get("telegram") or {}
    unknown = set(body) - {"owners", "groups", "zone"}
    if unknown:
        raise TelegramConfigError(f"unknown key(s): {', '.join(sorted(unknown))} (owners, groups, zone)")
    zone = str(body.get("zone") or DEFAULT_ZONE)
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise TelegramConfigError(f"zone: {zone!r} is not a time zone (e.g. America/Los_Angeles)") from None
    groups = _ids(body.get("groups"), "groups")
    if any(g > 0 for g in groups):
        raise TelegramConfigError("groups: a group's id is negative (e.g. -1001234567890)")
    return TelegramConfig(owners=_ids(body.get("owners"), "owners"), groups=groups, zone=zone, path=path)


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "configs"


def config_path(config_dir: str | Path | None = None) -> Path | None:
    root = (Path(config_dir) if config_dir else default_config_dir()) / "telegram"
    for candidate in (root / "local" / "telegram.yaml", root / "telegram.yaml"):
        if candidate.is_file():
            return candidate
    return None


def load_config(config_dir: str | Path | None = None) -> TelegramConfig:
    path = config_path(config_dir)
    if path is None:
        return TelegramConfig()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise TelegramConfigError(f"{path}: not valid YAML: {exc}") from exc
    try:
        return parse_config(raw, str(path))
    except TelegramConfigError as exc:
        raise TelegramConfigError(f"{path}: {exc}") from exc


class ConfigWatcher:
    """Re-reads the file when it changes; keeps the last good settings when
    a change breaks them."""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        self.config_dir = config_dir
        self._stamp: tuple[str, float] | None = None
        self._config = TelegramConfig()
        self.error: str | None = None

    def get(self) -> TelegramConfig:
        path = config_path(self.config_dir)
        stamp = (str(path), path.stat().st_mtime) if path else ("", 0.0)
        if stamp != self._stamp:
            self._stamp = stamp
            try:
                self._config = load_config(self.config_dir)
                self.error = None
            except TelegramConfigError as exc:
                self.error = str(exc)
                logger.warning("Telegram config not used (keeping the previous one): %s", exc)
        return self._config
