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
  lane picks one per run at its start, as ``account_pick`` says
  (:mod:`temper_ai.pi_agent.accounts`, ADR-M4-09 and -14). None by default here: the tracked
  file lists them. The canonical provider's own slot (account 1) is never allowed.
* ``account_room_file`` -- an absolute path, readable where the Pi lane runs, of the account
  room figures (:func:`temper_ai.pi_agent.accounts.read_room`); none by default: under the
  room pick a Pi run then can't pick its account and doesn't start.
* ``account_pick`` -- how a Pi run's account is picked: ``room`` (the default, ADR-M4-18), by
  the account-room file's figures; or ``settings_order`` (ADR-M4-19, the frozen first
  trial), the first allowed slot in ``account_slots`` order with **no capacity check**: no
  usage file is read and no usage is asked, and the run records its capacity as not checked
  (:attr:`TeamConfig.picks_without_capacity_check`). It must be said: an unset
  ``account_room_file`` alone still stops every Pi run. Any other value, or
  ``settings_order`` beside an ``account_room_file``, is a problem that stops every Pi run
  until it is fixed (:attr:`TeamConfig.account_pick_refusal`): it never turns into the other
  way of picking.

A bad entry is dropped (a bad ``account_pick`` stops every Pi run instead) and named in
:attr:`TeamConfig.problems`: a broken file never widens what a team may touch.
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
#: How a Pi run's account is picked (``account_pick``): by the account-room file's figures
#: (ADR-M4-18, the default), or the first allowed slot in the settings' order with no
#: capacity check (ADR-M4-19).
PICK_BY_ROOM = "room"
PICK_BY_SETTINGS_ORDER = "settings_order"
ACCOUNT_PICKS = (PICK_BY_ROOM, PICK_BY_SETTINGS_ORDER)
#: Why no Pi run's account is picked when the settings' ``account_pick`` can't be used.
ACCOUNT_PICK_REFUSAL = ("the team settings' account_pick can't be used (it must be room or "
                        "settings_order, and settings_order takes no account_room_file), so "
                        "no Pi run's account is picked until it is fixed")
_KEYS = ("project_roots", "owner_callers", "account_slots", "account_room_file",
         "account_pick")


@dataclass(frozen=True)
class TeamConfig:
    """The team settings as loaded, with every problem found in the files. ``account_pick``
    is None when the settings name one that can't be used (:attr:`account_pick_refusal`)."""

    project_roots: tuple[str, ...] = ()
    owner_callers: tuple[str, ...] = DEFAULT_OWNER_CALLERS
    account_slots: tuple[str, ...] = ()
    account_room_file: str | None = None
    account_pick: str | None = PICK_BY_ROOM
    problems: tuple[str, ...] = ()
    files: tuple[str, ...] = field(default=())

    @property
    def picks_without_capacity_check(self) -> bool:
        """Whether a Pi run's account is the first allowed slot in ``account_slots`` order
        with no capacity check (``account_pick: settings_order``, ADR-M4-19): no account-room
        file is read and no usage is asked. Never beside an ``account_room_file``: the
        settings refuse that pair, and a config built with both picks no account at all
        (:attr:`account_pick_refusal`)."""
        return self.account_pick == PICK_BY_SETTINGS_ORDER and not self.account_room_file

    @property
    def account_pick_refusal(self) -> str | None:
        """Why no Pi run's account can be picked under ``account_pick``, else None: it isn't
        room or settings_order (None: the settings named one that can't be used), or it is
        settings_order beside an ``account_room_file``. Every Pi run is then refused -- at
        the preflight, and at its claim before its kept account or any account reading --
        until the settings are fixed: a bad account_pick never turns into the other way of
        picking (ADR-M4-19; Architecture's #75 check, F1)."""
        if self.account_pick == PICK_BY_ROOM or self.picks_without_capacity_check:
            return None
        return ACCOUNT_PICK_REFUSAL


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
    account_pick: str | None = PICK_BY_ROOM
    if "account_pick" in merged:
        raw_pick = merged["account_pick"]
        where = sources["account_pick"]
        account_pick = None  # said, but can't be used: no Pi run's account is picked
        if raw_pick not in ACCOUNT_PICKS:
            problems.append(f"{where}: account_pick must be room or settings_order; no Pi "
                            "run starts until it is")
        elif raw_pick == PICK_BY_SETTINGS_ORDER and merged.get("account_room_file") is not None:
            # set at all, valid or not: the pair neither turns the room's check off nor on
            problems.append(f"{where}: account_pick settings_order reads no account-room "
                            "file; remove account_room_file or use room (no Pi run starts "
                            "until then)")
        else:
            account_pick = raw_pick
    for problem in problems:
        logger.warning("team settings: %s", problem)
    return TeamConfig(project_roots=tuple(roots), owner_callers=owners,
                      account_slots=tuple(slots), account_room_file=room_file or None,
                      account_pick=account_pick, problems=tuple(problems), files=tuple(files))


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
