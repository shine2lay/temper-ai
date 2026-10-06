"""The team's own settings and fixed limits (M3 contract, E5, E6, E13, E15).

Settings come from two files under the configs root, read whenever they are needed (no
restart): ``configs/team/team.yaml`` (tracked, public: generic defaults only) and
``configs/team/local/team.yaml`` (this install's, git-ignored; the owner writes it at
switch-on). A key in the local file replaces the same key from the tracked one. The configs
importer never reads ``configs/team/`` (it holds settings, not workflow or agent configs).

Keys:

* ``project_roots`` -- the folders a team may work on (default none): an absolute path is that
  folder only; one ending in ``/*`` is any folder directly inside it. Absolute host paths,
  because inside the containers ``~`` is ``/app``.
* ``owner_callers`` -- the API guard's credential names that are the owner's own
  (:mod:`temper_ai.api.caller`): an action by one of them shows as by ``owner``.
* ``account_slots`` -- the account slots (the host helper's labels) a Pi run may use; the Pi
  lane picks one per run at its start, by room (:mod:`temper_ai.pi_agent.accounts`, ADR-M4-09
  and -14). None by default here: the tracked file lists them. The canonical provider's own
  slot (account 1) is never allowed.
* ``account_room_file`` -- an absolute path, readable where the Pi lane runs, of the account
  room figures (:func:`temper_ai.pi_agent.accounts.read_room`); none by default: a Pi run
  then can't pick its account and doesn't start.

A bad entry is dropped and named in :attr:`TeamConfig.problems`: a broken file never widens
what a team may touch.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from temper_ai.config.importer import TEAM_SETTINGS_DIR, TRIAL_PREFIX
from temper_ai.shared.text_limits import STOP_REASON_MAX_CHARS

logger = logging.getLogger(__name__)

#: The configs folder holding the team's settings; the importer skips it (configs root only).
TEAM_DIR = TEAM_SETTINGS_DIR
#: A team member's name: it reaches ``<team root>/git/<name>.git`` and message routing (E6).
NAME_PATTERN = r"^[a-z][a-z0-9_-]{0,39}$"
NAME_RE = re.compile(NAME_PATTERN)
#: TRIAL_PREFIX (config/importer.py): a trial's frozen workflow and agent configs (E7).
TRIAL_ID_RE = re.compile(r"^[0-9a-f]{12}$")
#: The longest owner texts the server takes (E13), in characters.
LIMITS = {
    "goal_max_chars": 20000,
    "message_max_chars": 20000,
    "guide_max_chars": 20000,
    "reply_max_chars": 20000,
    "nudge_max_chars": 4000,
    "stop_reason_max_chars": STOP_REASON_MAX_CHARS,
}
#: The owner's own credential names when the settings don't say (the dashboard's key).
DEFAULT_OWNER_CALLERS = ("owner-dashboard",)
_KEYS = ("project_roots", "owner_callers", "account_slots", "account_room_file")


@dataclass(frozen=True)
class TeamConfig:
    """The team settings as loaded, with every problem found in the files."""

    project_roots: tuple[str, ...] = ()
    owner_callers: tuple[str, ...] = DEFAULT_OWNER_CALLERS
    account_slots: tuple[str, ...] = ()
    account_room_file: str | None = None
    problems: tuple[str, ...] = ()
    files: tuple[str, ...] = field(default=())


def is_trial_name(name: str | None) -> bool:
    """Whether a config name is a trial's frozen config (``team-trial-...``, E7)."""
    return str(name or "").startswith(TRIAL_PREFIX)


def trial_id_of(workflow_name: str | None) -> str | None:
    """The trial id a trial's workflow is named after, or None for any other workflow."""
    name = str(workflow_name or "")
    if not name.startswith(TRIAL_PREFIX):
        return None
    tid = name[len(TRIAL_PREFIX):]
    return tid if TRIAL_ID_RE.match(tid) else None


def settings_paths(config_dir: str | Path | None = None) -> tuple[Path, Path]:
    """(tracked file, local file) under the configs root."""
    from temper_ai.shared.box_env import default_config_dir

    root = (Path(config_dir) if config_dir else default_config_dir()) / TEAM_DIR
    return root / "team.yaml", root / "local" / "team.yaml"


def _root_problem(entry: object) -> str | None:
    if not isinstance(entry, str) or not entry.strip():
        return "must be a folder path"
    path = entry[:-2] if entry.endswith("/*") else entry
    if not path.startswith("/"):
        return "must be an absolute path (inside the containers ~ is /app)"
    if any(part in ("..", ".", "*") for part in path.split("/")) or os.path.normpath(path) != path:
        return "must be a plain absolute path: no '..', '.', doubled or trailing '/', and '*' only as a final '/*'"
    if path == "/":
        return "can't be / itself"
    return None


def _read(path: Path) -> tuple[dict, list[str]]:
    if not path.is_file():
        return {}, []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {}, [f"{path}: can't be read: {exc.__class__.__name__}"]
    if data is None:
        return {}, []
    if not isinstance(data, dict):
        return {}, [f"{path}: must be a mapping ({', '.join(_KEYS)})"]
    problems = [f"{path}: unknown key '{key}' (known: {', '.join(_KEYS)})"
                for key in data if key not in _KEYS]
    return {k: v for k, v in data.items() if k in _KEYS}, problems


def load_team_config(config_dir: str | Path | None = None) -> TeamConfig:
    """Both files merged, key by key (the local file wins). Never raises."""
    tracked, local = settings_paths(config_dir)
    merged: dict = {}
    problems: list[str] = []
    files: list[str] = []
    sources: dict[str, Path] = {}
    for path in (tracked, local):
        data, found = _read(path)
        problems += found
        if path.is_file():
            files.append(str(path))
        for key, value in data.items():
            merged[key] = value
            sources[key] = path
    roots: list[str] = []
    raw_roots = merged.get("project_roots") or []
    if not isinstance(raw_roots, list):
        problems.append(f"{sources['project_roots']}: project_roots must be a list of folders")
        raw_roots = []
    for i, entry in enumerate(raw_roots):
        why = _root_problem(entry)
        if why:
            problems.append(f"{sources['project_roots']}: project_roots[{i}] {why}")
        elif entry not in roots:
            roots.append(entry)
    owners: tuple[str, ...] = DEFAULT_OWNER_CALLERS
    if "owner_callers" in merged:
        raw_owners = merged["owner_callers"]
        if isinstance(raw_owners, list) and all(isinstance(o, str) and o.strip()
                                                for o in raw_owners):
            owners = tuple(dict.fromkeys(o.strip() for o in raw_owners))
        else:
            problems.append(f"{sources['owner_callers']}: owner_callers must be a list of "
                            "credential names")
    slots: list[str] = []
    raw_slots = merged.get("account_slots") or []
    if not isinstance(raw_slots, list):
        problems.append(f"{sources['account_slots']}: account_slots must be a list of slot "
                        "labels")
        raw_slots = []
    for i, entry in enumerate(raw_slots):
        why = slot_problem(entry)
        if why:
            problems.append(f"{sources['account_slots']}: account_slots[{i}] {why}")
        elif entry not in slots:
            slots.append(entry)
    room_file = merged.get("account_room_file")
    if room_file is not None and (not isinstance(room_file, str)
                                  or not os.path.isabs(room_file)
                                  or os.path.normpath(room_file) != room_file):
        problems.append(f"{sources['account_room_file']}: account_room_file must be a plain "
                        "absolute path")
        room_file = None
    for problem in problems:
        logger.warning("team settings: %s", problem)
    return TeamConfig(project_roots=tuple(roots), owner_callers=owners,
                      account_slots=tuple(slots), account_room_file=room_file or None,
                      problems=tuple(problems), files=tuple(files))


#: An account slot's label: the host helper's alias (``anthropic-2``), never an email or id.
SLOT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


def slot_problem(slot: object) -> str | None:
    """Why ``slot`` can't be a Pi run's account, else None. The canonical provider's own
    name is account 1's slot: never on a member's route (ADR-M4-14), refused by name."""
    from temper_ai.pi_agent.member import DEFAULT_PROVIDER

    if not isinstance(slot, str) or not SLOT_RE.match(slot):
        return "must be a slot label (lower-case letters, digits, '-' or '_')"
    if slot == DEFAULT_PROVIDER:
        return (f"'{slot}' is account 1, which is never on a Pi member's route (ADR-M4-14): "
                "list the other slots")
    return None
