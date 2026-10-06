"""The settings wait: a Pi conversation reopened under changed settings asks the owner (SW-85).

Every Pi conversation is pinned to what it was started with (:func:`temper_ai.pi_agent.host
.pin_for`: Pi's version, the box image, the model and thinking, the tools, the extensions'
and add-ons' digests, the route, the workflow, the agent config, the working folder and, for
a team member, the team's settings). Since C7 every owner answer reopens the conversation in a
new attempt, and every land deploys: a deploy that changes any of these while a conversation
waits for the owner is bound to happen. Instead of failing the step there, Temper asks the
owner at a ``settings`` wait, before anything else (no turn runs and no other answer is
applied on settings the owner hasn't confirmed):

* ``go on``: the conversation carries on with the new settings. The stored pin becomes the new
  one in the same transaction as the decision, compare-and-set on the old one, and only for the
  exact settings the wait named: when they changed again meanwhile, nothing is re-pinned and a
  new settings wait names the newer ones;
* ``stop``: the conversation ends there; the step (and its run) end cancelled, not failed --
  nothing failed, it was the owner's decision (M3 E18);
* anything else decides nothing: the owner is asked again (never a go on or a stop by default).

The wait's subject carries typed fields, so a page never parses its question
(``settings_changes``: one entry per changed setting, with its ``scope``, ``member``, a stable
``key``, ``value_kind`` and the ``old`` and ``new`` values; ``pins``: each named member's old
and new pin digests in full). A value is text only for the short settings
(:data:`TEXT_KEYS`); every other one is a full sha256 -- the setting's own digest where the pin
keeps one, else the digest of its canonical JSON. Never a file's contents or an environment
value. docs/pi-agent.md "Settings changed while a conversation waits".

Everything here is pure: the host (temper_ai/pi_agent/host.py) and the team
(temper_ai/pi_agent/team_runtime.py, team_leader.py) open, ask and decide the wait.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from temper_ai.pi_agent.ledger import SETTINGS_KIND, pin_digest

#: The wait kind (``pi_waits.kind``) and the page state while it is the one asked.
SETTINGS = SETTINGS_KIND
SETTINGS_STATE = "settings_changed"
GO_ON = "go on"
STOP = "stop"
#: The answers, in the order they are offered.
SETTINGS_OPTIONS = (GO_ON, STOP)
REPLY_HINT = "Reply 'go on' or 'stop'."
#: The pin's short settings, shown as they are; every other setting is shown as a digest.
TEXT_KEYS = ("pi_version", "image", "provider", "model", "thinking")
#: The pin's settings that hold one digest each by name (an extension, an add-on).
NESTED_KEYS = ("extensions", "add_ons")
#: Plain names for the question's text (the typed fields keep the key ids).
LABELS = {"pi_version": "Pi version", "image": "box image", "provider": "provider",
          "model": "model", "thinking": "thinking", "tools": "tools",
          "route_host": "worker route", "workflow": "workflow",
          "agent_config_sha256": "agent config", "cwd": "working folder",
          "team": "team settings"}
#: How many hex digits of a digest the question shows (as the Team page's fingerprint).
SHORT = 12

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"\Asha256:([0-9a-f]{64})\Z")


def flat_pin(pin: dict | None) -> dict[str, Any]:
    """A pin with its nested digests flattened to stable key ids: ``extensions.<name>`` and
    ``add_ons.<name>``; every other setting by its own name."""
    out: dict[str, Any] = {}
    for key, value in (pin or {}).items():
        if key in NESTED_KEYS and isinstance(value, dict):
            for name, digest in value.items():
                out[f"{key}.{name}"] = digest
        else:
            out[key] = value
    return out


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def value_kind(key: str) -> str:
    """``text`` for the short settings (:data:`TEXT_KEYS`), ``sha256`` for every other."""
    return "text" if key in TEXT_KEYS else "sha256"


def typed_value(key: str, value: Any) -> str | None:
    """A setting's value as the wait shows it: the text of a short setting; else a full
    sha256 -- the value itself when the pin keeps a digest there, the digest of its canonical
    JSON otherwise. None when the pin has no such setting."""
    if value is None:
        return None
    if value_kind(key) == "text":
        return str(value)
    if isinstance(value, str) and _HEX64.match(value):
        return value
    return _canonical_sha256(value)


def setting_changes(old: dict | None, new: dict | None, *, scope: str, member: str | None,
                    skip: tuple[str, ...] = ()) -> list[dict]:
    """One typed entry per setting that differs between two pins, by key id."""
    a, b = flat_pin(old), flat_pin(new)
    out = []
    for key in sorted(set(a) | set(b)):
        if key in skip or a.get(key) == b.get(key):
            continue
        out.append({"scope": scope, "member": member, "key": key,
                    "value_kind": value_kind(key),
                    "old": typed_value(key, a.get(key)), "new": typed_value(key, b.get(key))})
    return out


def _shown(change: dict, side: str) -> str:
    value = change.get(side)
    if value is None:
        return "(none)"
    if change.get("value_kind") == "sha256":
        return str(value)[:SHORT]
    image = _IMAGE.match(str(value))
    if image:
        return f"sha256:{image.group(1)[:SHORT]}"
    text = str(value)
    return text if len(text) <= 80 else text[:77] + "..."


def label(key: str) -> str:
    """A setting's plain name for the question: ``extension identity``, ``add-on pi-tldr``,
    ``model``...; an unknown key by its id."""
    head, _, name = key.partition(".")
    if name and head == "extensions":
        return f"extension {name}"
    if name and head == "add_ons":
        return f"add-on {name}"
    return LABELS.get(key, key)


def _change_text(change: dict) -> str:
    return f"{label(change['key'])} {_shown(change, 'old')} -> {_shown(change, 'new')}"


def _named(changes: list[dict]) -> str:
    """The changes grouped by whose they are: the team's first, then each member's."""
    groups: dict[str | None, list[dict]] = {}
    for c in changes:
        groups.setdefault(c["member"] if c["scope"] == "member" else None, []).append(c)
    parts = []
    for who in sorted(groups, key=lambda m: (m is not None, m or "")):
        text = ", ".join(_change_text(c) for c in groups[who])
        parts.append(f"whole team: {text}" if who is None else f"{who}: {text}")
    return "; ".join(parts)


def changed_names(changes: list[dict]) -> list[dict]:
    """What changed, without the values: ``scope``, ``member`` and ``key`` each (the record
    kept with the decision)."""
    return [{"scope": c["scope"], "member": c["member"], "key": c["key"]} for c in changes]


def _pin_entry(member: str, participant_id: str, old: dict, new: dict) -> dict:
    return {"member": member, "participant_id": participant_id,
            "pin_old": pin_digest(old), "pin_new": pin_digest(new)}


def _fingerprint(entry: dict) -> str:
    """A pins entry's two digests, shortened as the Team page's fingerprint."""
    return f"{entry['pin_old'][:SHORT]} -> {entry['pin_new'][:SHORT]}"


def step_subject(*, role: str, participant_id: str, old: dict, new: dict) -> dict:
    """The settings wait of a single Pi step: its role's changed settings (scope ``member``,
    the member named by its role) and its old and new pin digests."""
    changes = setting_changes(old, new, scope="member", member=role)
    pins = _pin_entry(role, participant_id, old, new)
    return {
        "header": SETTINGS, "role": role, "participant_id": participant_id,
        "question": ("The Pi step's settings changed since its conversation started: "
                     + "; ".join(_change_text(c) for c in changes)
                     + f". Settings fingerprint {_fingerprint(pins)}."
                     + " Go on with the new settings, or stop the step?"),
        "reply_hint": REPLY_HINT, "options": list(SETTINGS_OPTIONS),
        "settings_changes": changes,
        "pins": [pins],
        "pin_old": pins["pin_old"], "pin_new": pins["pin_new"],
    }


def team_subject(changed: list[tuple[str, str, dict, dict]]) -> dict:
    """The one settings wait of a team: (member, participant id, stored pin, current pin) for
    every member whose pin differs. The team's own settings (the ``team`` digest, the same in
    every member's pin) are one entry of scope ``team``; each member's own are entries of scope
    ``member``. ``pins`` names every member it re-pins, with both digests."""
    changes: list[dict] = []
    team_change = next((setting_changes({"team": o.get("team")}, {"team": n.get("team")},
                                        scope="team", member=None)
                        for _m, _p, o, n in changed if o.get("team") != n.get("team")), [])
    changes += team_change
    for name, _pid, old, new in sorted(changed, key=lambda c: c[0]):
        changes += setting_changes(old, new, scope="member", member=name, skip=("team",))
    pins = [_pin_entry(name, pid, old, new)
            for name, pid, old, new in sorted(changed, key=lambda c: c[0])]
    return {
        "header": SETTINGS,
        "question": ("The team's settings changed since its conversations started: "
                     + _named(changes) + ". Settings fingerprints: "
                     + ", ".join(f"{p['member']} {_fingerprint(p)}" for p in pins)
                     + ". Go on with the new settings, or stop the team?"),
        "reply_hint": REPLY_HINT, "options": list(SETTINGS_OPTIONS),
        "settings_changes": changes,
        "pins": pins,
    }


def same_change(subject: dict, now: list[dict]) -> bool:
    """Whether a settings wait names exactly the change there is now (``now``: the pins
    entries a fresh subject would carry): the same members, from the same stored pins to the
    same new ones. A go on applies only then."""
    def key(entries: list[dict]) -> set[tuple]:
        return {(e.get("participant_id"), e.get("pin_old"), e.get("pin_new")) for e in entries}
    return key(subject.get("pins") or []) == key(now)


def settings_word(choice: str, words: str) -> str | None:
    """The owner's answer at a settings wait, from :func:`~temper_ai.pi_agent.host.owner_reply`:
    ``go on`` (a pick of "go on", or typed "go on" / "go_on") or ``stop``. Anything else --
    empty, another word -- is None: never a go on or a stop by default."""
    choice = (choice or "").strip().lower()
    if choice == STOP:
        return STOP
    if choice in ("go on", "go_on"):
        return GO_ON
    if choice == "go" and re.match(r"on\b", (words or "").strip().lower()):
        return GO_ON
    return None


def settings_asked_again(subject: dict) -> dict:
    """A settings wait's subject when the answer named neither choice: the same change, asked
    again with the reason first."""
    first = str(subject.get("first_question") or subject.get("question") or "")
    return {**subject, "first_question": first,
            "asked_again": int(subject.get("asked_again") or 0) + 1,
            "question": (f"That answer was not one of: {', '.join(SETTINGS_OPTIONS)}. Nothing "
                         f"was decided. {first}").strip()}


def _keys_text(changes: list[dict], *, team: bool) -> str:
    if not team:
        return ", ".join(c["key"] for c in changes)
    groups: dict[str, list[str]] = {}
    for c in changes:
        who = c["member"] if c["scope"] == "member" else "whole team"
        groups.setdefault(who, []).append(c["key"])
    return "; ".join(f"{who}: {', '.join(keys)}" for who, keys in groups.items())


def step_stop_text(subject: dict) -> str:
    """The neutral text (M3 E16) of a single step stopped at its settings wait: it never names
    who answered."""
    keys = _keys_text(subject.get("settings_changes") or [], team=False)
    return ("the Pi step was stopped: its settings changed since its conversation started"
            + (f" ({keys})" if keys else ""))


def team_stop_text(subject: dict) -> str:
    """The neutral text (M3 E16) of a team stopped at its settings wait."""
    keys = _keys_text(subject.get("settings_changes") or [], team=True)
    return ("stopped when the team's settings changed since its conversations started"
            + (f" ({keys})" if keys else ""))
