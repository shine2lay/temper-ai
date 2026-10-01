"""Who may do what in Slack: ``configs/slack/access.yaml``.

Everything about access is here and in that file; no handler decides for
itself. One function, :func:`decide`, answers every case — a slash command,
a plain-words request, a Start it / Cancel button, a gate's Approve, Reject
or Answer — with allow or refuse and a line to show the person.

The file is built from named **roles**, so adding someone is one line::

    access:
      owner: U0123ABCD          # everything, everywhere
      default: readonly         # the role for anyone not named below
      repositories: [rollcall, roamee, temper-ai]   # every one temper knows
      people:
        U0456EFGH: {role: roamee, name: lomit}
      roles:
        readonly:
          commands: [help, list, search, status, ask]
          runs: none            # whose runs they may see and stop
          gates: none           # whose gates they may answer
        roamee:
          commands: [help, list, search, status, ask, pick, stop]
          workflows: [repo_answer, github_work, linear_work]
          force:                # put on every run this role builds
            github_work: {repo: shine2lay/roamee}
            linear_work: {repo: roamee}
          repos: [roamee]       # which repos they may ask about
          auto: [repo_answer]   # starts without a click
          runs: own
          gates: own
          channels: [C0123ABCD] # where the role applies (default: everywhere)

``commands`` are the things a person can set out to do: ``help``, ``list``,
``search``, ``status``, ``ask``, ``run`` (naming a workflow), ``pick``
(plain words, built by the role's interpreter), ``stop`` and ``gate``.

``workflows`` is the whole world the role's interpreter sees: it cannot
propose anything else, and ``run`` cannot name anything else. Leave it out
and the role may use every workflow.

``force`` is the fence that matters. The general workflows take a repo as
an input, so allowing one by name alone would let a roamee person aim it
at another repo; the forced values are applied **after** the interpreter
has filled the inputs, so no wording can talk it out of them. A ``"*"``
key forces values on every workflow the role may use.

``repos`` is the other half of that fence, for questions. Only those
repositories are copied for the answer, and a question that names one of
``repositories`` the role may not ask about is refused outright: one line,
no run, nothing copied. Leave ``repos`` out and the role may ask about any
of them.

``runs`` and ``gates`` are ``own``, ``all`` or ``none``: whose runs this
role may see, stop and start from a proposal, and whose gates it may answer.

``auto`` names the workflows that start the moment the interpreter picks
them, with no Start it button; everything else is proposed first.

``about`` is a line for people to read; temper does nothing with it.

``channels`` are channel ids (``C…``/``G…``/``D…``); a role that names some
applies only there, and its people fall back to the default role elsewhere.

With no access file at all, everyone may do everything, as temper's Slack
bot always did. The tracked ``configs/slack/access.yaml`` closes that: the
real file, with people's ids in it, is ``configs/slack/local/access.yaml``
(git-ignored), used instead when it exists.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Everything a person can set out to do. One of these reaches ``decide``
#: from each entry point; nothing else does.
ACTIONS = ("help", "list", "search", "status", "ask", "run", "pick", "stop", "gate")
#: Commands a role may be given. ``help`` is everyone's, always.
COMMANDS = ACTIONS
#: How far a role's reach goes over other people's runs.
SCOPES = ("none", "own", "all")
#: ``force`` under this name applies to every workflow the role may use.
ANY = "*"

ROLE_KEYS = {"commands", "workflows", "force", "repos", "runs", "gates", "auto", "channels", "about"}
TOP_KEYS = {"owner", "default", "roles", "people", "repositories"}

_USER = re.compile(r"^[UW][A-Z0-9]{6,}$")
_CHANNEL_ID = re.compile(r"^[CGD][A-Z0-9]{6,}$")

#: What a refused person is told. One line, in the thread, nothing else.
NO_COMMAND = "that isn't something you can do here."
NO_WORKFLOW = "that's outside what I can do for you here."
NO_RUN = "that run isn't yours."
NO_GATE = "that question isn't yours to answer."
NO_SEE = "that run isn't yours."
NO_REPO = "that's not a repository I can work on for you."


class AccessConfigError(ValueError):
    """The access file says something temper cannot use."""


@dataclass(frozen=True)
class Role:
    """What one kind of person may do."""

    name: str
    commands: frozenset[str] = frozenset()
    #: None: every workflow. Otherwise the only ones this role ever sees.
    workflows: tuple[str, ...] | None = None
    #: workflow name (or ``*``) -> inputs put on every run, after filling.
    force: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: (): every repo. Otherwise the only ones questions may be about.
    repos: tuple[str, ...] = ()
    runs: str = "own"
    gates: str = "own"
    #: Workflows that start straight away, with no Start it button.
    auto: frozenset[str] = frozenset()
    #: (): everywhere. Otherwise the channel ids the role applies in.
    channels: tuple[str, ...] = ()
    about: str = ""

    def applies_in(self, channel: str) -> bool:
        return not self.channels or channel in self.channels

    def may_use(self, workflow: str) -> bool:
        return self.workflows is None or workflow in self.workflows

    def forced(self, workflow: str) -> dict[str, Any]:
        """The inputs this role puts on a run of ``workflow``."""
        return {**self.force.get(ANY, {}), **self.force.get(workflow, {})}


#: Everyone may do everything: the role a missing access file gives.
OPEN = Role(name="", commands=frozenset(COMMANDS), workflows=None, runs="all", gates="all")


@dataclass(frozen=True)
class Verdict:
    """What :func:`decide` answers: allow or refuse, and why."""

    ok: bool
    why: str = ""
    role: str = ""
    #: What was asked (for the record a refusal leaves behind).
    action: str = ""
    #: Inputs to put on the run, after its inputs are filled.
    force: dict[str, Any] = field(default_factory=dict)
    #: May this one start without a Start it button?
    auto: bool = False
    #: The repos this person may ask about ((): every one).
    repos: tuple[str, ...] = ()
    #: The only workflows this person's interpreter may see (None: every one).
    workflows: tuple[str, ...] | None = None

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class AccessConfig:
    owner: str = ""
    default: str = ""
    roles: dict[str, Role] = field(default_factory=dict)
    #: Slack user id -> role name.
    people: dict[str, str] = field(default_factory=dict)
    #: Slack user id -> the name written beside it, for reports only.
    names: dict[str, str] = field(default_factory=dict)
    #: Every repository temper can answer about, so a question naming one a
    #: role may not ask about is refused before anything is started.
    repositories: tuple[str, ...] = ()
    path: str = ""
    #: False when there is no access file: everyone may do everything.
    on: bool = False

    def role_of(self, user: str, channel: str = "") -> Role:
        """The role deciding for ``user`` here.

        Their own, when it applies in this channel; the default role
        otherwise, so a role tied to one channel cannot be used from
        another. Without an access file, the open role.
        """
        if not self.on:
            return OPEN
        named = self.roles.get(self.people.get(user, ""))
        if named is not None and named.applies_in(channel):
            return named
        return self.roles.get(self.default) or Role(name=self.default or "none")

    def is_owner(self, user: str) -> bool:
        return bool(self.owner) and user == self.owner


def repos_named(text: str, known: Iterable[str]) -> tuple[str, ...]:
    """The repositories ``known`` that ``text`` names, in the order given.

    Whole words only, so "rollcall" in a sentence counts and "rollcalling"
    does not. Pure text matching, no model: it decides only whether to
    refuse, never what an allowed question is answered from.
    """
    low = text.lower()
    return tuple(name for name in known
                 if re.search(rf"(?<![\w-]){re.escape(name.lower())}(?![\w-])", low))


def decide(cfg: AccessConfig, user: str, action: str, *, channel: str = "", workflow: str = "",
           run_by: str | None = None, repo: str = "") -> Verdict:
    """May ``user`` do ``action`` here — and with what forced on it?

    ``workflow`` is the workflow being named, picked or started; ``run_by``
    is the Slack user whose run is being seen, stopped or gated ("" when
    nobody in Slack started it, e.g. a trigger did); ``repo`` is a
    repository the question names (:func:`repos_named` finds them).

    Pure: no Slack, no database, no clock. Every entry point asks this and
    nothing else.
    """
    if action not in ACTIONS:
        raise ValueError(f"no such action {action!r} (one of {', '.join(ACTIONS)})")
    if not cfg.on or cfg.is_owner(user):
        return Verdict(True, role="owner" if cfg.is_owner(user) else "", action=action)
    role = cfg.role_of(user, channel)
    allowed = Verdict(True, role=role.name, action=action, force=role.forced(workflow) if workflow else {},
                      auto=bool(workflow) and workflow in role.auto, repos=role.repos,
                      workflows=role.workflows)

    def no(why: str) -> Verdict:
        return Verdict(False, why, role.name, action)

    if action == "help":
        return allowed
    if action not in role.commands:
        return no(NO_COMMAND)
    # A question that names a repository the role may not ask about is
    # refused before anything starts: no run, no copy, nothing to answer
    # from. A role with no list of its own may ask about any of them.
    if repo and role.repos and repo not in role.repos:
        return no(NO_REPO)
    if action in ("run", "pick"):
        if workflow and not role.may_use(workflow):
            return no(NO_WORKFLOW)
        # A proposal built for someone else is their run to start.
        if run_by is not None and run_by != user and role.runs != "all":
            return no(NO_RUN)
        return allowed
    if action in ("status", "stop", "gate"):
        scope = role.gates if action == "gate" else role.runs
        why = NO_GATE if action == "gate" else (NO_SEE if action == "status" else NO_RUN)
        if scope == "all":
            return allowed
        if scope == "own" and run_by is not None and run_by and run_by == user:
            return allowed
        if run_by is None:   # no run in question (the list of what's going)
            return allowed if scope != "none" else no(why)
        return no(why)
    return allowed


def refusal(verdict: Verdict) -> str:
    """The one line a refused person sees, wherever they tried it."""
    return f":lock: Sorry — {verdict.why or NO_COMMAND}"


# -- reading the file -----------------------------------------------------------------


def _as_list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        return [value]
    if not isinstance(value, list):
        raise AccessConfigError(f"{where}: expected a list, got {value!r}")
    return list(value)


def _names(value: Any, where: str) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in _as_list(value, where) if str(item).strip())


def _scope(value: Any, where: str, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text not in SCOPES:
        raise AccessConfigError(f"{where}: expected one of {', '.join(SCOPES)}, got {value!r}")
    return text


def _force(value: Any, where: str) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AccessConfigError(f"{where}: expected a mapping of workflow name to inputs, got {value!r}")
    out: dict[str, dict[str, Any]] = {}
    for workflow, inputs in value.items():
        if not isinstance(inputs, dict):
            raise AccessConfigError(f"{where}.{workflow}: expected a mapping of input name to value, got {inputs!r}")
        out[str(workflow)] = dict(inputs)
    return out


def parse_role(name: str, raw: Any) -> Role:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise AccessConfigError(f"roles.{name}: expected a mapping, got {raw!r}")
    unknown = set(raw) - ROLE_KEYS
    if unknown:
        raise AccessConfigError(
            f"roles.{name}: unknown key(s) {', '.join(sorted(unknown))} (use {', '.join(sorted(ROLE_KEYS))})")
    commands = _names(raw.get("commands"), f"roles.{name}.commands")
    bad = [c for c in commands if c not in COMMANDS]
    if bad:
        raise AccessConfigError(
            f"roles.{name}.commands: {', '.join(bad)} is not a command (one of {', '.join(COMMANDS)})")
    channels = _names(raw.get("channels"), f"roles.{name}.channels")
    for channel in channels:
        if not _CHANNEL_ID.match(channel):
            raise AccessConfigError(
                f"roles.{name}.channels: {channel!r} is not a channel id (C…, G… or D…); a #name cannot be "
                "matched against what Slack sends")
    workflows = raw.get("workflows")
    return Role(
        name=name,
        commands=frozenset(commands),
        workflows=_names(workflows, f"roles.{name}.workflows") if workflows is not None else None,
        force=_force(raw.get("force"), f"roles.{name}.force"),
        repos=_names(raw.get("repos"), f"roles.{name}.repos"),
        runs=_scope(raw.get("runs"), f"roles.{name}.runs", "own"),
        gates=_scope(raw.get("gates"), f"roles.{name}.gates", "own"),
        auto=frozenset(_names(raw.get("auto"), f"roles.{name}.auto")),
        channels=channels,
        about=str(raw.get("about") or "").strip(),
    )


def parse_config(raw: Any, path: str = "") -> AccessConfig:
    body = raw.get("access", raw) if isinstance(raw, dict) else None
    if raw is None or body is None:
        return AccessConfig(path=path, on=True, default="", roles={})
    if not isinstance(body, dict):
        raise AccessConfigError("expected a mapping under 'access:'")
    unknown = set(body) - TOP_KEYS
    if unknown:
        raise AccessConfigError(
            f"unknown key(s) under access: {', '.join(sorted(unknown))} (use {', '.join(sorted(TOP_KEYS))})")
    cfg = AccessConfig(path=path, on=True)
    cfg.repositories = _names(body.get("repositories"), "repositories")
    owner = str(body.get("owner") or "").strip()
    if owner and not _USER.match(owner):
        raise AccessConfigError(f"owner: {owner!r} is not a user id (U…)")
    cfg.owner = owner
    roles = body.get("roles") or {}
    if not isinstance(roles, dict):
        raise AccessConfigError("roles: expected a mapping of role name to what it may do")
    cfg.roles = {str(name): parse_role(str(name), spec) for name, spec in roles.items()}
    cfg.default = str(body.get("default") or "").strip()
    if cfg.default and cfg.default not in cfg.roles:
        raise AccessConfigError(f"default: there is no role {cfg.default!r} (roles: {', '.join(cfg.roles) or 'none'})")
    people = body.get("people") or {}
    if not isinstance(people, dict):
        raise AccessConfigError("people: expected a mapping of Slack user id to a role")
    for user, spec in people.items():
        who = str(user).strip()
        if not _USER.match(who):
            raise AccessConfigError(f"people.{user}: {who!r} is not a Slack user id (U…)")
        if isinstance(spec, dict):
            unknown = set(spec) - {"role", "name"}
            if unknown:
                raise AccessConfigError(f"people.{who}: unknown key(s) {', '.join(sorted(unknown))} (use role, name)")
            role_name, person = str(spec.get("role") or "").strip(), str(spec.get("name") or "").strip()
        else:
            role_name, person = str(spec or "").strip(), ""
        if not role_name:
            raise AccessConfigError(f"people.{who}: no role (give a role name, or drop the line)")
        if role_name not in cfg.roles:
            raise AccessConfigError(
                f"people.{who}: there is no role {role_name!r} (roles: {', '.join(cfg.roles) or 'none'})")
        cfg.people[who] = role_name
        if person:
            cfg.names[who] = person
    return cfg


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "configs"


def config_path(config_dir: str | Path | None = None) -> Path | None:
    """The file in use: the local one if it exists, else the tracked one."""
    root = (Path(config_dir) if config_dir else default_config_dir()) / "slack"
    for candidate in (root / "local" / "access.yaml", root / "access.yaml"):
        if candidate.is_file():
            return candidate
    return None


def owner_fallback(config_dir: str | Path | None = None) -> str:
    """Who the owner is when the access file does not say: the first person
    the Slack agent tools may DM, the same one ``owner.py`` writes to."""
    try:
        from temper_ai.integrations.slack.config import load_config

        return next(iter(load_config(config_dir).agents.users), "")
    except Exception:  # noqa: BLE001 - a broken Slack config must not open the door
        logger.debug("no Slack config to take the owner from", exc_info=True)
        return ""


def load_config(config_dir: str | Path | None = None) -> AccessConfig:
    """The access rules in use; without a file, everyone may do everything."""
    path = config_path(config_dir)
    if path is None:
        return AccessConfig(on=False)
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise AccessConfigError(f"{path}: not valid YAML: {exc}") from exc
    try:
        cfg = parse_config(raw, str(path))
    except AccessConfigError as exc:
        raise AccessConfigError(f"{path}: {exc}") from exc
    if not cfg.owner:
        cfg.owner = owner_fallback(config_dir)
    return cfg


class AccessWatcher:
    """Re-reads the file when it changes; keeps the last good rules when a
    change breaks it (and says so once). A file that will not parse never
    opens the door: the rules in force stay as they were."""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        self.config_dir = config_dir
        self._stamp: tuple[str, float] | None = None
        self._config: AccessConfig | None = None
        self.error: str | None = None

    def get(self) -> AccessConfig:
        path = config_path(self.config_dir)
        stamp = (str(path), path.stat().st_mtime) if path else ("", 0.0)
        if stamp != self._stamp or self._config is None:
            self._stamp = stamp
            try:
                self._config = load_config(self.config_dir)
                self.error = None
            except AccessConfigError as exc:
                self.error = str(exc)
                logger.warning("Slack access rules not used (keeping the previous ones): %s", exc)
                if self._config is None:
                    # Nothing good was ever read: the file exists but is
                    # broken, so nobody but the owner gets through.
                    self._config = AccessConfig(on=True, owner=owner_fallback(self.config_dir))
        return self._config
