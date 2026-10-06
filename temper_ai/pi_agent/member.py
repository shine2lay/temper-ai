"""Pi member settings: the model, tools and add-ons a ``type: pi`` agent gets (owner, 2026-10-03).

* **Model.** Unless a config says otherwise: provider route ``anthropic``, model
  ``claude-opus-5-5``, thinking ``max`` (owner m02497), so a failed trial points at the platform,
  not the model. The turn reads back what Pi actually started with and refuses a member that
  didn't get exactly this (:mod:`temper_ai.pi_agent.turn`).
* **Tools.** One ``tools:`` list with Temper's tool names, as for every other Temper agent
  (owner m02525), mapped to Pi's built-ins. A tool with no Pi equivalent refuses the config by
  name; nothing is dropped silently.
* **Add-ons.** ``add_ons:`` defaults to every allowed add-on; the risky ones, and any that failed
  in the worker box, are refused by name with the reason. An add-on runs from a pinned copy named
  in the worker box config, never from the owner's live ``~/.pi/agent``
  (:class:`temper_ai.pi_agent.box.BoxConfig`).

The checks here return plain problem texts: the Pi step prefixes them with ``pi:``, the team's
pre-run check with the member's name. Only imported with the Pi switch (``TEMPER_PI_AGENT``) on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from temper_ai.pi_agent.box import ROLE_RE

DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_THINKING = "max"
#: Pi's thinking levels (the pinned Pi 0.87.1 accepts exactly these).
THINKING = ("off", "minimal", "low", "medium", "high", "xhigh", "max")

#: Temper's tool names and the Pi built-ins each one becomes.
TOOL_MAP: dict[str, tuple[str, ...]] = {
    "Read": ("read",),
    "Edit": ("edit",),
    "Write": ("write",),
    "Bash": ("bash",),
    "Grep": ("grep",),
    "Glob": ("find", "ls"),
}
DEFAULT_TOOLS = ("Read",)
#: Pi's own built-in tool names: written in a config, they get a hint to use Temper's name.
_PI_NAMES = {pi: temper for temper, pis in TOOL_MAP.items() for pi in pis}


@dataclass(frozen=True)
class AddOn:
    """An allowed add-on: the Pi tools it brings (added to the member's tool list)."""

    tools: tuple[str, ...] = ()


#: Allowed add-ons and the tools each one brings: the ones that passed the worker box test
#: (M2, 2026-10-04: the turn finished, no network beyond the model route, files only in the
#: run folder, no unexpected commands). The same two as the pins' DEFAULT_ADD_ONS, which the
#: pin check requires pinned and nothing else (pins.py, SW-29; tests/test_pi_agent/test_pins.py).
ADD_ONS: dict[str, AddOn] = {
    "pi-image-trim": AddOn(),
    "pi-tldr": AddOn(tools=("tldr",)),
}

#: Add-ons a member may not have, and why (build plan, "Pi agent config: model and tools").
REFUSED_ADD_ONS: dict[str, str] = {
    "pi-worktree": "needs the wt command, absent in the box; it would block every edit, and "
                   "the run's copy already isolates the work",
    "pi-subagents": "starts extra agents or sessions Temper can't see, count or limit",
    "relays": "starts extra agents or sessions Temper can't see, count or limit",
    "pi-memory": "writes the owner's real memory and daily log; the run-local notebook is the "
                 "run's memory",
    "pi-mcp-adapter": "needs the internet or other providers' keys; the box only reaches the "
                      "model provider",
    "pi-web-access": "needs the internet; the box only reaches the model provider",
    "pi-web-search": "needs the internet or other providers' keys; the box only reaches the "
                     "model provider",
    "pi-control-chrome": "drives the owner's signed-in Chrome on the host",
    "pi-multi-pass": "handles sign-ins and refresh tokens; the box gets only a short-lived token "
                     "from the host",
    "pi-queue": "belongs to the chat app",
    "pi-company": "belongs to the chat app and shared Company records",
    "team-messaging": "not available yet: Temper's team messaging add-on ships with T4",
    "pi-identity": "always loaded through 'role'; don't list it",
    "pi-anthropic-auth": "the provider route's own login extension is route config (the worker "
                         "box config's routes), not an add-on",
    "billion-context-pi": "left out after the worker box test: it writes its own file beside "
                          "the Pi session (<session>.jsonl.acp.json), which the turn's private "
                          "session check refuses, so every turn with it fails",
}


# --- the whole member config ------------------------------------------------------------------

def config_problems(cfg: dict) -> list[str]:
    """Every problem with a ``type: pi`` agent config, all at once."""
    problems = []
    role = cfg.get("role")
    if not isinstance(role, str) or not ROLE_RE.match(role):
        problems.append("'role' must be one role name (one role per Pi step)")
    if "roles" in cfg:
        problems.append("one role per Pi step ('roles' is not supported)")
    problems += model_problems(cfg)
    problems += tool_problems(cfg.get("tools"))
    problems += add_on_problems(cfg.get("add_ons"))
    if not isinstance(cfg.get("message", ""), str):
        problems.append("'message' must be text")
    files = cfg.get("workspace_files", {})
    if not isinstance(files, dict) or not all(
            isinstance(k, str) and "/" not in k and not k.startswith(".")
            and isinstance(v, str) for k, v in files.items()):
        problems.append("'workspace_files' must map plain file names to text")
    return problems


def settings(cfg: dict) -> dict:
    """The member's model settings, defaults filled in."""
    return {"provider": cfg.get("provider") or DEFAULT_PROVIDER,
            "model": cfg.get("model") or DEFAULT_MODEL,
            "thinking": cfg.get("thinking") or DEFAULT_THINKING}


def model_problems(cfg: dict) -> list[str]:
    problems = []
    for key, default in (("provider", DEFAULT_PROVIDER), ("model", DEFAULT_MODEL)):
        if key in cfg and (not isinstance(cfg[key], str) or not cfg[key]):
            problems.append(f"'{key}' must be a name (leave it out for {default})")
    if "thinking" in cfg and cfg["thinking"] not in THINKING:
        problems.append(f"'thinking' must be one of {', '.join(THINKING)}")
    return problems


# --- tools ------------------------------------------------------------------------------------

def tool_problems(tools: object) -> list[str]:
    """Problems with a member's ``tools:`` list (Temper's names; left out = Read)."""
    if tools is None:
        return []
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) for t in tools):
        return [f"'tools' must be a non-empty list of Temper tool names ({', '.join(TOOL_MAP)})"]
    problems = []
    for name in tools:
        if name in TOOL_MAP:
            continue
        if name in _PI_NAMES:
            problems.append(f"tool '{name}' is Pi's own name; use Temper's name "
                            f"'{_PI_NAMES[name]}'")
        else:
            problems.append(f"tool '{name}' has no Pi equivalent (a Pi member can use "
                            f"{', '.join(TOOL_MAP)})")
    return problems


def pi_tools(tools: list[str] | None) -> list[str]:
    """The Pi built-ins for a member's Temper tool names, sorted, without repeats."""
    names = DEFAULT_TOOLS if tools is None else tools
    return sorted({pi for name in names for pi in TOOL_MAP[name]})


# --- add-ons ----------------------------------------------------------------------------------

def add_on_problems(add_ons: object) -> list[str]:
    """Problems with a member's ``add_ons:`` list (left out = every allowed add-on)."""
    if add_ons is None:
        return []
    if not isinstance(add_ons, list) or not all(isinstance(a, str) for a in add_ons):
        return ["'add_ons' must be a list of add-on names"]
    problems = []
    for name in add_ons:
        if name in ADD_ONS:
            continue
        if name in REFUSED_ADD_ONS:
            problems.append(f"add-on '{name}' is not allowed: {REFUSED_ADD_ONS[name]}")
        else:
            problems.append(f"unknown add-on '{name}' (allowed: {', '.join(sorted(ADD_ONS))})")
    if len(set(add_ons)) != len(add_ons):
        problems.append("'add_ons' names an add-on more than once")
    return problems


def add_on_names(cfg: dict) -> list[str]:
    """The member's add-ons: every allowed one unless its config lists fewer."""
    listed = cfg.get("add_ons")
    return sorted(ADD_ONS) if listed is None else sorted(listed)


def launched_tools(cfg: dict) -> list[str]:
    """Every tool the worker starts with: the mapped built-ins plus the add-ons' own tools."""
    tools = set(pi_tools(cfg.get("tools")))
    for name in add_on_names(cfg):
        tools.update(ADD_ONS[name].tools)
    return sorted(tools)


# --- a usage limit ----------------------------------------------------------------------------

_LIMIT_RE = re.compile(
    r"\b429\b|rate[ _-]?limit|usage[ _-]?limit|quota|limit (?:was |has been )?reached"
    r"|reached (?:your|the) (?:usage |rate )?limit|exceed(?:s|ed)? (?:your|the) .{0,40}limit|hit your (?:\w+ ){0,3}limit",
    re.IGNORECASE)


def usage_limit(error: str | None) -> str | None:
    """The reason to pause, when a turn's provider error is a usage or rate limit: the member
    waits for the owner (retry once the limit resets), never a quiet model or account switch."""
    if not error or not _LIMIT_RE.search(error):
        return None
    return "usage limit: " + " ".join(error.split())[:300]
