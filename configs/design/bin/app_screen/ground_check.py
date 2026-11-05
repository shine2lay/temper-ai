"""Stage 3's script checks on the model's draft inventory, and the final inventory.json it becomes.

check_draft() holds a draft (contracts "ground_draft") to the source items (03-ground/sources.json):

    schema               the draft's shape
    ids                  screen ids, a screen's action ids and a screen's state names used once
    invented             a cited id that is no source item
    unsourced            a state beyond the base ones that cites nothing
    coverage             a page, API route or requirement neither cited nor excluded; a stage 2 screen not cited
    placed_and_excluded  an item both cited and excluded, or excluded twice; a stage 2 screen excluded
    base_states          a screen without loading, empty, error, partial and normal
    action_states        an action without pending, done and error
    named_conditions     an outcome code a cited source item names ("refused with locker_full") that no state
                         of an action, state or screen citing that item names

Model-free. outputs() turns a clean draft into inventory.json (widths from the product file, data_needed from
the fixture's states); draft_from() turns an inventory back into its draft, so a final file can be re-checked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import contracts, ground_fixture
from .ground_sources import EXCLUDABLE, PLACED, named_conditions

BASE_STATES = ("normal", "loading", "empty", "error", "partial")
ACTION_BASE = ("pending", "done", "error")
ACTION_UI = ACTION_BASE + ("confirm", "retry", "undo")   # an action's own steps: no special data needed
CHECKS = ("schema", "ids", "invented", "unsourced", "coverage", "placed_and_excluded", "base_states",
          "action_states", "named_conditions")


@dataclass
class Context:
    items: dict[str, dict]
    widths: list[int]
    fixture_states: set[str] = field(default_factory=set)

    @property
    def required(self) -> list[str]:
        return [i for i, it in self.items.items() if it["kind"] in PLACED]


class _Found:
    def __init__(self):
        self.problems: list[dict] = []
        self.counts = {c: 0 for c in CHECKS}

    def add(self, check: str, where: str, problem: str) -> None:
        self.problems.append({"check": check, "where": where, "problem": problem})
        self.counts[check] += 1


def _cited(screen: dict) -> list[tuple[str, str]]:
    """(where, id) for every id a screen cites."""
    out = [(f"screens/{screen['id']}/sources", s) for s in screen.get("sources", [])]
    for i, show in enumerate(screen.get("shows", [])):
        out += [(f"screens/{screen['id']}/shows/{i}", s) for s in show.get("sources", [])]
    for st in screen.get("states", []):
        out += [(f"screens/{screen['id']}/states/{st['name']}", s) for s in st.get("sources", [])]
    for a in screen.get("actions", []):
        out += [(f"screens/{screen['id']}/actions/{a['id']}", s) for s in a.get("sources", [])]
    return out


def _words(name: str) -> set[str]:
    return set(re.split(r"[-_\s]+", name.lower()))


def _states_citing(screens: list[dict], ref: str) -> list[str]:
    """State names a source item could be drawn as: its screens' states, states and actions citing it."""
    out: list[str] = []
    for s in screens:
        on_screen = ref in s["sources"]
        out += [st["name"] for st in s["states"] if on_screen or ref in st.get("sources", [])]
        for a in s.get("actions", []):
            if ref in a["sources"]:
                out += a["states"]
    return out


def _check_named_conditions(ctx: Context, screens: list[dict], cited: set[str], found: _Found) -> None:
    for ref in sorted(cited & set(ctx.items)):
        for code in named_conditions(ctx.items[ref]["text"]):
            words = _words(code)
            if not any(words <= _words(name) for name in _states_citing(screens, ref)):
                found.add("named_conditions", ref,
                          f"names the condition {code}; give the action or screen that cites it a state for it "
                          f"(e.g. refused-{code.replace('_', '-')})")


def check_draft(ctx: Context, draft: Any) -> dict:
    found = _Found()
    for line in contracts.check_json("ground_draft", draft, "draft"):
        where, _, reason = line.partition(": ")[2].partition(": ")
        found.add("schema", where, reason)
    if found.problems:
        return _verdict(found, {"screens": 0, "actions": 0, "excluded": 0, "required": len(ctx.required),
                                "placed": 0})
    screens, excluded = draft["screens"], draft["excluded"]
    cited: set[str] = set()
    seen_screens: set[str] = set()
    for s in screens:
        where = f"screens/{s['id']}"
        if s["id"] in seen_screens:
            found.add("ids", where, f"screen id {s['id']} is used twice")
        seen_screens.add(s["id"])
        names = [st["name"] for st in s["states"]]
        for n in sorted({n for n in names if names.count(n) > 1}):
            found.add("ids", f"{where}/states", f"state {n} is listed twice")
        actions = [a["id"] for a in s.get("actions", [])]
        for a in sorted({a for a in actions if actions.count(a) > 1}):
            found.add("ids", f"{where}/actions", f"action id {a} is used twice")
        for spot, ref in _cited(s):
            if ref not in ctx.items:
                found.add("invented", spot, f"{ref} is no source item in 03-ground/sources.json")
            cited.add(ref)
        for st in s["states"]:
            if st["name"] not in BASE_STATES and not st.get("sources"):
                found.add("unsourced", f"{where}/states/{st['name']}",
                          "a state beyond the base ones needs the source ids that name it")
        missing = [b for b in BASE_STATES if b not in names]
        if missing:
            found.add("base_states", f"{where}/states", f"lacks {', '.join(missing)}")
        for a in s.get("actions", []):
            lacks = [b for b in ACTION_BASE if b not in a["states"]]
            if lacks:
                found.add("action_states", f"{where}/actions/{a['id']}", f"lacks {', '.join(lacks)}")
    out: set[str] = set()
    for i, e in enumerate(excluded):
        ref, spot = e["source"], f"excluded/{i}"
        if ref not in ctx.items:
            found.add("invented", spot, f"{ref} is no source item in 03-ground/sources.json")
            continue
        kind = ctx.items[ref]["kind"]
        if ref in out:
            found.add("placed_and_excluded", spot, f"{ref} is excluded twice")
        elif kind not in EXCLUDABLE:
            found.add("placed_and_excluded", spot, f"{ref} is a {kind} item; only page, api, req and note items "
                                                   "can be left out")
        elif ref in cited:
            found.add("placed_and_excluded", spot, f"{ref} is cited by a screen and excluded")
        out.add(ref)
    for ref in ctx.required:
        if ref not in cited and ref not in out:
            kind = ctx.items[ref]["kind"]
            how = "cite it on the screen" if kind == "screen" else "cite it where it is used, or exclude it with a reason"
            found.add("coverage", ref, f"not placed: {how}")
    _check_named_conditions(ctx, screens, cited, found)
    return _verdict(found, {"screens": len(screens), "actions": sum(len(s.get("actions", [])) for s in screens),
                            "excluded": len(excluded), "required": len(ctx.required),
                            "placed": sum(1 for r in ctx.required if r in cited or r in out)})


def _verdict(found: _Found, sizes: dict) -> dict:
    return {"verdict": "retry" if found.problems else "ok", "counts": {**sizes, **found.counts},
            "problems": found.problems}


def data_needed(ctx: Context, screen: dict) -> list[str]:
    """States beyond the base ones (an action's own steps aside) the fixture's states lack, for build."""
    need = [st["name"] for st in screen["states"]
            if st["name"] not in BASE_STATES and ground_fixture.slug(st["name"]) not in ctx.fixture_states]
    for a in screen.get("actions", []):
        need += [f"{a['id']}: {st}" for st in a["states"]
                 if st not in ACTION_UI and ground_fixture.slug(st) not in ctx.fixture_states]
    return need


def outputs(ctx: Context, draft: dict, status: str, source: dict) -> dict:
    screens = []
    for s in draft["screens"]:
        out = {"id": s["id"], "name": s["name"], "states": [st["name"] for st in s["states"]],
               "widths": list(ctx.widths), "sources": list(s["sources"])}
        state_sources = {st["name"]: st["sources"] for st in s["states"] if st.get("sources")}
        if state_sources:
            out["state_sources"] = state_sources
        for key in ("shows", "actions"):
            if s.get(key):
                out[key] = s[key]
        need = data_needed(ctx, s)
        if need:
            out["data_needed"] = need
        screens.append(out)
    return {"design_files": status, "source": source, "screens": screens, "excluded": list(draft["excluded"])}


def draft_from(inventory: dict) -> dict:
    """An inventory turned back into the draft it came from (widths and data_needed are the script's)."""
    screens = []
    for s in inventory.get("screens", []):
        srcs = s.get("state_sources", {})
        d = {"id": s["id"], "name": s["name"], "sources": s.get("sources", []),
             "states": [{"name": n, **({"sources": srcs[n]} if n in srcs else {})} for n in s["states"]]}
        for key in ("shows", "actions"):
            if key in s:
                d[key] = s[key]
        screens.append(d)
    return {"screens": screens, "excluded": inventory.get("excluded", [])}
