"""Grade one stage 3 (ground) run against its known case's answer key, by measurement only (no model).

    design_app_screen.py grade-ground --case DIR --workspace W

The case folder holds expected.json, written before any run (docs/design-app-screen.md, "Stage 3", Bar):

    design_files   the exact status design_files.inventory gives the product
    fixture        {"sha256": the frozen fixture's hash (optional), "invariants": "pass" | "fail",
                    "fails_on": text the failing check names (optional)}
    pages          page routes a screen must cite (not merely exclude); every other page is held to placed
                   or excluded with a reason by the re-check
    key            {"bar": 0.9, "items": [{"id", "group", "what", "screens": [screen terms; [] = any],
                    "groups": [[terms], ...], "in": "screen" | "action"}]}: an item is met when a screen whose
                    id or name holds one of its screen terms holds a term of every group in its text (name, id,
                    shown facts, states, actions and the ids it cites), or with "in": "action", when one of its
                    actions does in its id and what alone; terms compare lower-case with - and _ read as spaces
    planted        [{"id", "what", "measure": {...}}]: one measure each (below), all must be found
    clean          true: every planted-style measure in "false_gaps" must stay silent, and every screen must
                   cite a page, a stage 2 screen or a requirement

Measures: {"cited_by_screen": id} a screen cites the source id; {"action_cites": id} an action cites it;
{"state_on": id, "terms": [...]} a screen or action citing id has a state holding one of the terms;
{"new_screen": req id, "terms": [...], "not": [stage 2 screen ids]} a screen citing the requirement, holding a
term in its id or name, and not itself one of those screens; {"excluded_only": id} the id is excluded with a reason and
no screen cites it; {"fixture_fails": text} fixture-check.json fails and names the text ("" = fails at all);
{"screen_named": [terms]} a screen's id or name holds a term; {"action_named": [terms]} an action's id or what
holds a term (the last two for false gaps on a clean twin: a screen or action its sources never name).

Bar failures are misses (the run fails the bar); key items missed within the bar are notes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import ground, ground_check
from .ground_host import sha256_file
from .workspace import Workspace


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_]", " ", str(text).lower())).strip()


def screen_text(screen: dict) -> str:
    """Everything a screen says about itself, for the key's term match."""
    parts = [screen["id"], screen["name"], *screen.get("sources", []), *screen.get("states", [])]
    for srcs in screen.get("state_sources", {}).values():
        parts += srcs
    for show in screen.get("shows", []):
        parts += [show["what"], *show["sources"]]
    for a in screen.get("actions", []):
        parts += [a["id"], a["what"], *a["states"], *a["sources"]]
    return _norm(" | ".join(parts))


def _all_cited(screen: dict) -> set[str]:
    out = set(screen.get("sources", []))
    for srcs in screen.get("state_sources", {}).values():
        out |= set(srcs)
    for show in screen.get("shows", []):
        out |= set(show["sources"])
    for a in screen.get("actions", []):
        out |= set(a["sources"])
    return out


def _holds(text: str, groups: list[list[str]]) -> bool:
    return all(any(_norm(t) in text for t in group) for group in groups)


def key_met(item: dict, screens: list[dict]) -> bool:
    terms = [_norm(t) for t in item.get("screens", [])]
    for s in screens:
        head = _norm(f"{s['id']} {s['name']}")
        if terms and not any(t in head for t in terms):
            continue
        if item.get("in", "screen") == "action":
            if any(_holds(_norm(f"{a['id']} | {a['what']}"), item["groups"]) for a in s.get("actions", [])):
                return True
        elif _holds(screen_text(s), item["groups"]):
            return True
    return False


def _states_citing(ref: str, screens: list[dict]) -> list[str]:
    out = []
    for s in screens:
        if ref in s.get("sources", []) or any(ref in v for v in s.get("state_sources", {}).values()):
            out += s["states"]
        for a in s.get("actions", []):
            if ref in a["sources"]:
                out += a["states"]
        for name, srcs in s.get("state_sources", {}).items():
            if ref in srcs:
                out.append(name)
    return out


def measure(m: dict, inventory: dict, fixture_check: dict) -> bool:
    screens = inventory["screens"]
    if "cited_by_screen" in m:
        return any(m["cited_by_screen"] in _all_cited(s) for s in screens)
    if "action_cites" in m:
        return any(m["action_cites"] in a["sources"] for s in screens for a in s.get("actions", []))
    if "state_on" in m:
        states = _norm(" | ".join(_states_citing(m["state_on"], screens)))
        return any(_norm(t) in states for t in m["terms"])
    if "new_screen" in m:
        return any(m["new_screen"] in _all_cited(s) and s["id"] not in m.get("not", [])
                   and any(_norm(t) in _norm(f"{s['id']} {s['name']}") for t in m["terms"]) for s in screens)
    if "excluded_only" in m:
        ref = m["excluded_only"]
        return (any(e["source"] == ref and e["reason"].strip() for e in inventory.get("excluded", []))
                and not any(ref in _all_cited(s) for s in screens))
    if "fixture_fails" in m:
        named = " ".join(f"{p['where']} {p['problem']}" for p in fixture_check.get("problems", []))
        return fixture_check.get("verdict") == "fail" and m["fixture_fails"] in named
    if "screen_named" in m:
        return any(_norm(t) in _norm(f"{s['id']} {s['name']}") for s in screens for t in m["screen_named"])
    if "action_named" in m:
        return any(_norm(t) in _norm(f"{a['id']} {a['what']}")
                   for s in screens for a in s.get("actions", []) for t in m["action_named"])
    raise ValueError(f"unknown measure {sorted(m)}")


def _load(path: Path, what: str):
    if not path.is_file():
        raise ValueError(f"{path} is missing ({what})")
    return json.loads(path.read_text(encoding="utf-8"))


def grade(case: str | Path, workspace: str | Path) -> dict:
    case, ws = Path(case).expanduser(), Workspace(workspace)
    expected = _load(case / "expected.json", "the case's answer key")
    folder = ws.folder("ground")
    misses, notes, measures = [], [], {}
    try:
        inventory = _load(folder / "inventory.json", "the run's inventory")
        fixture_check = _load(folder / "fixture-check.json", "ground_collect's invariant check")
        ctx = ground.context(ws)
    except (ValueError, ground.GroundError) as exc:
        return {"pass": False, "misses": [f"run: {exc}"], "notes": [], "measures": {}}

    recheck = ground_check.check_draft(ctx, ground_check.draft_from(inventory))
    for check in ("invented", "unsourced", "coverage", "schema", "placed_and_excluded", "base_states",
                  "action_states", "named_conditions", "ids"):
        measures[check] = recheck["counts"].get(check, 0)
    for p in recheck["problems"]:
        misses.append(f"recheck {p['check']} {p['where']}: {p['problem']}")

    measures["design_files"] = inventory["design_files"]
    if inventory["design_files"] != expected["design_files"]:
        misses.append(f"design_files is {inventory['design_files']}, the key says {expected['design_files']}")

    fx = expected.get("fixture", {})
    sha = sha256_file(folder / "fixture.json") if (folder / "fixture.json").is_file() else ""
    measures["fixture_sha256"], measures["fixture_invariants"] = sha, fixture_check["verdict"]
    if fx.get("sha256") and sha != fx["sha256"]:
        misses.append(f"fixture.json sha256 {sha[:12]} is not the frozen {fx['sha256'][:12]}")
    if fx.get("invariants") and fixture_check["verdict"] != fx["invariants"]:
        misses.append(f"fixture invariants {fixture_check['verdict']}, the key says {fx['invariants']}")

    cited = set().union(*(_all_cited(s) for s in inventory["screens"])) if inventory["screens"] else set()
    pages = expected.get("pages", [])
    on = [p for p in pages if f"page:{p}" in cited]
    measures["pages"] = f"{len(on)}/{len(pages)}"
    for p in pages:
        if f"page:{p}" not in cited:
            misses.append(f"page {p} is on no screen")

    key = expected.get("key")
    if key:
        met = [i["id"] for i in key["items"] if key_met(i, inventory["screens"])]
        share = len(met) / len(key["items"])
        measures["key"] = f"{len(met)}/{len(key['items'])}"
        measures["key_share"] = round(share, 3)
        missed = [i for i in key["items"] if i["id"] not in met]
        for i in missed:
            notes.append(f"key {i['id']} ({i.get('group', 'no group')}): {i['what']}")
        if share < key["bar"]:
            misses.append(f"key {len(met)}/{len(key['items'])} = {share:.0%} is under the bar {key['bar']:.0%}")

    planted = expected.get("planted", [])
    if planted:
        found = [p["id"] for p in planted if measure(p["measure"], inventory, fixture_check)]
        measures["planted"] = f"{len(found)}/{len(planted)}"
        for p in planted:
            if p["id"] not in found:
                misses.append(f"planted {p['id']} not found: {p['what']}")

    if expected.get("clean"):
        gaps = [g["id"] for g in expected.get("false_gaps", []) if measure(g["measure"], inventory, fixture_check)]
        anchors = ("page:", "screen:", "req:")
        loose = [s["id"] for s in inventory["screens"] if not any(c.startswith(anchors) for c in _all_cited(s))]
        measures["false_gaps"] = len(gaps) + len(loose)
        misses += [f"false gap {g}" for g in gaps] + [f"false gap: screen {s} cites no page, screen or requirement"
                                                      for s in loose]
    measures["screens"] = len(inventory["screens"])
    measures["actions"] = sum(len(s.get("actions", [])) for s in inventory["screens"])
    measures["excluded"] = len(inventory.get("excluded", []))
    measures["data_needed"] = sum(len(s.get("data_needed", [])) for s in inventory["screens"])
    return {"pass": not misses, "misses": misses, "notes": notes, "measures": measures}
