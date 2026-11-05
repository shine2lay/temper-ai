"""Step 4, ground's delta: place only what is new on top of a product's stored inventory. Model-free.

    base(stored inventory, stored sources, fresh sources)
        the stored inventory as a draft, with citations of removed source items, and of placed items (pages,
        API routes, screens, requirements, knowledge lines) whose words changed, taken out; an entry left
        citing nothing leaves with them (a state or a shown fact that had sources, an action, a screen)
    unplaced(base, fresh sources)
        the placed-kind items the base neither cites nor excludes: new requirements above all
    changed_context(stored sources, fresh sources)
        what changed on screens already placed: new or changed words a screen shows (seen:), journeys
    placed_section(base)
        the task's added input section, "Already placed, keep", and how a delta reply is read
    merge(base, additions)
        the reply's additions put into the base: a stored screen's id adds sources, states, shows and actions
        to it (a state or action already there gains only new sources and states); a new id is a new screen;
        excluded entries are appended
    kept(base, merged)
        problems where a base entry is not kept unchanged (every base list a prefix of the merged one)

The merged draft is then held to every ground check, coverage over all items (ground_check.check_draft).
"""
from __future__ import annotations

import copy

from .ground_sources import PLACED

BASE, ADDITIONS = "base.json", "additions.json"
STORED = "stored"                      # 03-ground/stored/: the stored version prepare copied in


def prep_changes(stored_prep: dict, fresh_prep: dict) -> list[str]:
    """The prep parts outside the source items that changed (fixture, design-file status, app commit); their
    'from' paths differ by run and are left out. A change re-derives the inventory (no model unless items
    are unplaced) instead of copying the stored one."""
    def part(prep: dict, key: str):
        value = prep.get(key)
        return {k: v for k, v in value.items() if k != "from"} if isinstance(value, dict) else value
    return [k for k in ("fixture", "design_files", "commit") if part(stored_prep, k) != part(fresh_prep, k)]


def _texts(items: list[dict]) -> dict[str, str]:
    return {i["id"]: i.get("text", "") for i in items}


def stale_ids(stored_items: list[dict], fresh_items: list[dict]) -> set[str]:
    """Ids a base may no longer cite: removed items, and placed-kind items whose words changed."""
    old, new = _texts(stored_items), _texts(fresh_items)
    kinds = {i["id"]: i["kind"] for i in stored_items}
    return {i for i in old if i not in new or (kinds[i] in PLACED and old[i] != new[i])}


def base(inventory_draft: dict, stale: set[str]) -> tuple[dict, list[str]]:
    """The stored draft without stale citations, and a list of what left (for the record)."""
    draft = copy.deepcopy(inventory_draft)
    gone: list[str] = []

    def strip(entry: dict, where: str) -> bool:
        """True when the entry had sources and none is left."""
        had = entry.get("sources")
        if not had:
            return False
        kept = [s for s in had if s not in stale]
        gone.extend(f"{where}: {s}" for s in had if s in stale)
        entry["sources"] = kept
        return not kept

    def keep(entries: list[dict], where) -> list[dict]:
        out = []
        for e in entries:
            if strip(e, where(e)):
                gone.append(f"{where(e)}: left (no source left)")
            else:
                out.append(e)
        return out

    screens = []
    for s in draft["screens"]:
        sid = f"screens/{s['id']}"
        if strip(s, sid):
            gone.append(f"{sid}: the screen left (no source left)")
            continue
        s["states"] = keep(s["states"], lambda st, sid=sid: f"{sid}/states/{st['name']}")
        for key, name in (("shows", "what"), ("actions", "id")):
            if key in s:
                s[key] = keep(s[key], lambda e, sid=sid, key=key, name=name: f"{sid}/{key}/{e[name]}")
                if not s[key]:
                    del s[key]
        screens.append(s)
    draft["screens"] = screens
    excluded = []
    for e in draft.get("excluded", []):
        if e["source"] in stale:
            gone.append(f"excluded: {e['source']}")
        else:
            excluded.append(e)
    draft["excluded"] = excluded
    return draft, gone


def cited(draft: dict) -> set[str]:
    out: set[str] = set()
    for s in draft["screens"]:
        out.update(s.get("sources", []))
        for st in s.get("states", []):
            out.update(st.get("sources", []))
        for key in ("shows", "actions"):
            for e in s.get(key, []):
                out.update(e.get("sources", []))
    return out


def unplaced(draft: dict, fresh_items: list[dict]) -> list[dict]:
    done = cited(draft) | {e["source"] for e in draft.get("excluded", [])}
    return [i for i in fresh_items if i["kind"] in PLACED and i["id"] not in done]


def changed_context(stored_items: list[dict], fresh_items: list[dict]) -> list[dict]:
    """Context items (a screen's words, journeys) that are new or whose words changed."""
    old = _texts(stored_items)
    return [i for i in fresh_items if i["kind"] not in PLACED and old.get(i["id"]) != i.get("text", "")]


def placed_section(draft: dict, version: int | None) -> list[str]:
    lines = [f"Stored inventory{f' v{version}' if version else ''}: these screens, states, actions and shown facts "
             "are already placed and stay as they are. Do not repeat or change them.",
             "Reply in the usual JSON shape, holding ONLY what the items in the sections below add: a screen "
             "entry with an id from this list adds to that screen (repeat its name; give only the new sources, "
             "states, shows or actions; sources and states may then be empty lists); a new id is a new screen "
             "with everything it needs; excluded lists only the items you newly exclude. Every item in the "
             "sections below ends up cited by a screen or excluded with a reason, as usual.", ""]
    for s in draft["screens"]:
        acts = "; ".join(f"{a['id']} ({', '.join(a['states'])})" for a in s.get("actions", []))
        shows = "; ".join(e["what"] for e in s.get("shows", []))
        lines.append(f"- {s['id']} ({s['name']}): states {', '.join(st['name'] for st in s['states'])}"
                     + (f". Actions: {acts}" if acts else "") + (f". Shows: {shows}" if shows else ""))
    if draft.get("excluded"):
        lines.append(f"- excluded already: {', '.join(e['source'] for e in draft['excluded'])}")
    return lines


def _append(into: list, more: list) -> None:
    for x in more:
        if x not in into:
            into.append(x)


def merge(base_draft: dict, additions: dict) -> dict:
    """The base with the additions put in (never removes or changes a base entry)."""
    merged = copy.deepcopy(base_draft)
    by_id = {s["id"]: s for s in merged["screens"]}
    for add in additions.get("screens", []):
        screen = by_id.get(add["id"])
        if screen is None:
            screen = copy.deepcopy(add)
            merged["screens"].append(screen)
            by_id[add["id"]] = screen
            continue
        _append(screen.setdefault("sources", []), add.get("sources", []))
        states = {st["name"]: st for st in screen["states"]}
        for st in add.get("states", []):
            if st["name"] in states:
                if st.get("sources"):
                    _append(states[st["name"]].setdefault("sources", []), st["sources"])
            else:
                screen["states"].append(copy.deepcopy(st))
                states[st["name"]] = screen["states"][-1]
        if add.get("shows"):
            _append(screen.setdefault("shows", []), copy.deepcopy(add["shows"]))
        actions = {a["id"]: a for a in screen.get("actions", [])}
        for a in add.get("actions", []):
            if a["id"] in actions:
                _append(actions[a["id"]]["states"], a.get("states", []))
                _append(actions[a["id"]]["sources"], a.get("sources", []))
            else:
                screen.setdefault("actions", []).append(copy.deepcopy(a))
                actions[a["id"]] = screen["actions"][-1]
    sources = {e["source"] for e in merged.get("excluded", [])}
    for e in additions.get("excluded", []):
        if e["source"] not in sources:
            merged.setdefault("excluded", []).append(copy.deepcopy(e))
            sources.add(e["source"])
    if additions.get("notes"):
        merged["notes"] = additions["notes"]
    return merged


def _prefix(old: list, new: list) -> bool:
    return new[:len(old)] == old


def kept(base_draft: dict, merged: dict) -> list[dict]:
    """A problem for every base entry the merged draft does not keep as it was (only appends are allowed)."""
    problems = []
    by_id = {s["id"]: s for s in merged.get("screens", [])}

    def miss(where: str, what: str) -> None:
        problems.append({"check": "kept", "where": where, "problem": what})

    for s in base_draft["screens"]:
        where, got = f"screens/{s['id']}", by_id.get(s["id"])
        if got is None:
            miss(where, "a stored screen is missing")
            continue
        if got["name"] != s["name"]:
            miss(where, f"name changed from {s['name']!r}")
        if not _prefix(s.get("sources", []), got.get("sources", [])):
            miss(f"{where}/sources", "stored sources changed")
        states = {st["name"]: st for st in got["states"]}
        if [st["name"] for st in s["states"]] != [st["name"] for st in got["states"]][:len(s["states"])]:
            miss(f"{where}/states", "stored states changed order or left")
        for st in s["states"]:
            if st["name"] in states and not _prefix(st.get("sources", []), states[st["name"]].get("sources", [])):
                miss(f"{where}/states/{st['name']}", "stored state sources changed")
        if not _prefix(s.get("shows", []), got.get("shows", [])):
            miss(f"{where}/shows", "stored shown facts changed")
        actions = {a["id"]: a for a in got.get("actions", [])}
        for a in s.get("actions", []):
            b = actions.get(a["id"])
            if b is None:
                miss(f"{where}/actions/{a['id']}", "a stored action is missing")
            elif b["what"] != a["what"] or not _prefix(a["states"], b["states"]) \
                    or not _prefix(a["sources"], b["sources"]):
                miss(f"{where}/actions/{a['id']}", "a stored action changed")
    if not _prefix(base_draft.get("excluded", []), merged.get("excluded", [])):
        miss("excluded", "stored exclusions changed")
    return problems
