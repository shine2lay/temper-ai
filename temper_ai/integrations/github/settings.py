"""temper's GitHub settings: ``configs/github/github.yaml``.

::

    github:
      app: temper-ai-bot             # the app's name on GitHub (its slug)
      allowed_authors: [shine2lay]   # the only people whose events start work

``app`` is how a comment calls on temper (``@temper-ai-bot ...``) and how
temper knows its own doings: the app acts on GitHub as ``<app>[bot]``, and
nothing that account does starts anything. ``allowed_authors`` are GitHub
logins; everyone else's labels, comments and pull requests start nothing
(the event is recorded as skipped). A trigger rule can narrow this further
with its own ``authors``, never widen it.

A ``configs/github/local/github.yaml`` (git-ignored) is used instead when it
exists. Read on every delivery, so a change needs no restart. The folder is
one of the importer's NON_CONFIG_DIRS: these are server settings, not a
workflow config.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_APP = "temper-ai-bot"
DEFAULT_AUTHORS = ("shine2lay",)


@dataclass(frozen=True)
class GitHubSettings:
    app: str = DEFAULT_APP
    allowed_authors: tuple[str, ...] = field(default=DEFAULT_AUTHORS)
    path: str = ""

    @property
    def bot_login(self) -> str:
        """The account the app acts as on GitHub."""
        return f"{self.app}[bot]"

    @property
    def mention(self) -> str:
        return f"@{self.app}"

    def allows(self, login: str | None) -> bool:
        wanted = {a.lower() for a in self.allowed_authors}
        return bool(login) and str(login).strip().lower() in wanted


def _config_root(config_dir: str | Path | None) -> Path:
    if config_dir:
        return Path(config_dir)
    return Path(__file__).resolve().parents[3] / "configs"


def settings_file(config_dir: str | Path | None = None) -> Path | None:
    root = _config_root(config_dir) / "github"
    for candidate in (root / "local" / "github.yaml", root / "github.yaml"):
        if candidate.is_file():
            return candidate
    return None


def _logins(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else [value]
    return tuple(str(v).strip().lstrip("@") for v in values if v is not None and str(v).strip())


def load_settings(config_dir: str | Path | None = None) -> GitHubSettings:
    """The settings, or the defaults (with a warning) if the file is missing or wrong."""
    path = settings_file(config_dir)
    if path is None:
        return GitHubSettings()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not read %s (%s); using the GitHub defaults", path, exc)
        return GitHubSettings(path=str(path))
    body = raw.get("github", raw) if isinstance(raw, dict) else {}
    if not isinstance(body, dict):
        body = {}
    app = str(body.get("app") or DEFAULT_APP).strip().lstrip("@")
    if app.endswith("[bot]"):
        app = app[: -len("[bot]")]
    authors = _logins(body["allowed_authors"]) if "allowed_authors" in body else DEFAULT_AUTHORS
    return GitHubSettings(app=app or DEFAULT_APP, allowed_authors=authors, path=str(path))
