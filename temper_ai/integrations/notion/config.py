"""Which Notion pages and tables temper uses, by name.

The real ids go in ``configs/notion/local/notion.yaml`` (git-ignored), used
instead of the tracked example ``configs/notion/notion.yaml`` when it
exists. Changes are picked up without a restart::

    notion:
      targets:
        qa:                      # a page: agents may write under it
          page: 3e74cb8f6eaa801b96c5ceefb5206616
        crm:                     # a table: rows are found by `key`
          table: <database or data source id or URL>
          key: Company           # the property that identifies a row
          fields:                # what agents call a field -> the property
            company: Company
            website: Website
            employees: Employees
      answer_from: all           # or a list of target names / page ids
      zone: America/Los_Angeles

Agents and workflows name a target ("crm"), never an id. Temper writes only
to targets, pages under a target page, rows of a target table, and the page
a run was started from. Trigger rules (``source: notion``) live in
``configs/triggers/`` like the other sources.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from temper_ai.integrations.notion.client import normalize_id

logger = logging.getLogger(__name__)

DEFAULT_ZONE = "America/Los_Angeles"


class NotionConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    name: str
    page: str = ""                  # a page target
    table: str = ""                 # a table target (database or data source id)
    key: str = ""                   # the table's key property
    fields: dict[str, str] = field(default_factory=dict)  # field name -> property name

    @property
    def is_table(self) -> bool:
        return bool(self.table)

    @property
    def id(self) -> str:
        return self.table or self.page

    def prop(self, name: str) -> str:
        """The property for a field name (or the name itself if it is a property)."""
        if name in self.fields:
            return self.fields[name]
        lower = {k.lower(): v for k, v in self.fields.items()}
        return lower.get(name.lower(), name)


@dataclass(frozen=True)
class NotionConfig:
    targets: dict[str, Target] = field(default_factory=dict)
    answer_from: tuple[str, ...] | None = None   # None: every page shared with Temper
    zone: str = DEFAULT_ZONE
    path: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.zone)

    def target(self, name_or_id: str) -> Target | None:
        """A target by name, or by its id."""
        text = str(name_or_id or "").strip()
        if text in self.targets:
            return self.targets[text]
        nid = normalize_id(text)
        for t in self.targets.values():
            if nid and nid in (t.page, t.table):
                return t
        return None

    def answer_ids(self) -> list[str] | None:
        """Page/table ids answers may read, or None for everything shared."""
        if self.answer_from is None:
            return None
        out = []
        for item in self.answer_from:
            t = self.targets.get(item)
            out.append(t.id if t else normalize_id(item))
        return out

    def describe(self) -> str:
        if not self.targets:
            return "no targets"
        return ", ".join(f"{n} ({'table' if t.is_table else 'page'})" for n, t in sorted(self.targets.items()))


def _target(name: str, body: Any) -> Target:
    if isinstance(body, str):
        return Target(name=name, page=normalize_id(body))
    if not isinstance(body, dict):
        raise NotionConfigError(f"targets.{name}: expected `page: <id>` or `table: <id>`")
    unknown = set(body) - {"page", "table", "key", "fields"}
    if unknown:
        raise NotionConfigError(f"targets.{name}: unknown key(s) {', '.join(sorted(unknown))} "
                                "(page, table, key, fields)")
    page, table = str(body.get("page") or ""), str(body.get("table") or "")
    if bool(page) == bool(table):
        raise NotionConfigError(f"targets.{name}: give exactly one of page or table")
    fields = body.get("fields") or {}
    if not isinstance(fields, dict):
        raise NotionConfigError(f"targets.{name}.fields: expected field: Property pairs")
    if page and (body.get("key") or fields):
        raise NotionConfigError(f"targets.{name}: key and fields are for tables")
    key = str(body.get("key") or "")
    fmap = {str(k): str(v) for k, v in fields.items()}
    if table and not key:
        raise NotionConfigError(f"targets.{name}: a table needs `key:` (the property that identifies a row)")
    return Target(name=name, page=normalize_id(page), table=normalize_id(table), key=key, fields=fmap)


def parse_config(raw: Any, path: str = "") -> NotionConfig:
    if raw is None:
        return NotionConfig(path=path)
    if not isinstance(raw, dict) or not isinstance(raw.get("notion", {}), dict):
        raise NotionConfigError("expected a mapping under `notion:`")
    body = raw.get("notion") or {}
    unknown = set(body) - {"targets", "answer_from", "zone"}
    if unknown:
        raise NotionConfigError(f"unknown key(s): {', '.join(sorted(unknown))} (targets, answer_from, zone)")
    targets_raw = body.get("targets") or {}
    if not isinstance(targets_raw, dict):
        raise NotionConfigError("targets: expected name: {page|table: id} pairs")
    targets = {str(n): _target(str(n), b) for n, b in targets_raw.items()}
    answer = body.get("answer_from", "all")
    answer_from: tuple[str, ...] | None
    if answer in (None, "all"):
        answer_from = None
    elif isinstance(answer, list):
        answer_from = tuple(str(a) for a in answer)
    else:
        raise NotionConfigError("answer_from: `all` or a list of target names / page ids")
    zone = str(body.get("zone") or DEFAULT_ZONE)
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise NotionConfigError(f"zone: {zone!r} is not a time zone") from None
    return NotionConfig(targets=targets, answer_from=answer_from, zone=zone, path=path)


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "configs"


def config_path(config_dir: str | Path | None = None) -> Path | None:
    root = (Path(config_dir) if config_dir else default_config_dir()) / "notion"
    for candidate in (root / "local" / "notion.yaml", root / "notion.yaml"):
        if candidate.is_file():
            return candidate
    return None


def load_config(config_dir: str | Path | None = None) -> NotionConfig:
    path = config_path(config_dir)
    if path is None:
        return NotionConfig()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise NotionConfigError(f"{path}: not valid YAML: {exc}") from exc
    try:
        return parse_config(raw, str(path))
    except NotionConfigError as exc:
        raise NotionConfigError(f"{path}: {exc}") from exc


class ConfigWatcher:
    """Re-reads the file when it changes; keeps the last good settings when a
    change breaks them."""

    _shared: ConfigWatcher | None = None

    def __init__(self, config_dir: str | Path | None = None) -> None:
        self.config_dir = config_dir
        self._stamp: tuple[str, float] | None = None
        self._config = NotionConfig()
        self.error: str | None = None

    @classmethod
    def shared(cls) -> ConfigWatcher:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def get(self) -> NotionConfig:
        path = config_path(self.config_dir)
        stamp = (str(path), path.stat().st_mtime) if path else ("", 0.0)
        if stamp != self._stamp:
            self._stamp = stamp
            try:
                self._config = load_config(self.config_dir)
                self.error = None
            except NotionConfigError as exc:
                self.error = str(exc)
                logger.warning("Notion config not used (keeping the previous one): %s", exc)
        return self._config
