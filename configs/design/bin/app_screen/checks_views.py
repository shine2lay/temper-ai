"""What the checks step opens: one view per screen, state and width of the round's build.

The prototype contract (docs/design-app-screen.md) says a view opens at `#<screen>/<state>`. A build that
cannot route by hash names its views in build.json's `views[]` instead, with steps to click through. This
module turns either into the flat list the renderer walks, and nothing else: no browser, no files beyond
05-build/build.json and 03-ground/inventory.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .contracts import ID, STATE
from .workspace import Workspace

SCREEN_RE = re.compile(ID["pattern"])
STATE_RE = re.compile(STATE["pattern"])

WALK_WIDTH = "widest"          # the width the Tab walk and the action clicks use, once per screen and state
HEIGHTS = {320: 640, 390: 844, 414: 896, 768: 1024, 1024: 768, 1280: 800, 1440: 900, 1920: 1080}


class ViewError(ValueError):
    """The build does not say what to open; the message names the file and what is missing."""


def height_for(width: int) -> int:
    """A viewport height for a width: the product's own if it has one, else the nearest known pair."""
    if width in HEIGHTS:
        return HEIGHTS[width]
    return 844 if width < 700 else 900


def view_id(screen: str, state: str, width: int) -> str:
    return f"{screen}-{state}-{width}"


def from_inventory(screens: list[dict], widths: list[int]) -> list[dict]:
    """The hash convention: every inventory screen x state, at every width the build names."""
    views = []
    for screen in screens:
        for state in screen.get("states") or []:
            for width in widths:
                views.append({"screen": screen["id"], "state": state, "width": width,
                              "open": {"hash": f"#{screen['id']}/{state}"}})
    return views


def check_ids(views: list[dict], where: str) -> None:
    """Refuse a screen or state the row contract cannot hold, before anything is opened.

    A state id is lowercase letters, digits and dashes, as the inventory writes it. The hash that opens
    the view is free text, so a view's state id may be `not-sent` while its hash stays `?state=not_sent`.
    """
    problems = []
    for i, v in enumerate(views):
        if not SCREEN_RE.match(str(v.get("screen") or "")):
            problems.append(f"views/{i}/screen: {v.get('screen')!r} is not an id "
                            "(letters, digits, dash, dot, underscore or @)")
        if not STATE_RE.match(str(v.get("state") or "")):
            problems.append(f"views/{i}/state: {v.get('state')!r} is not an id "
                            "(lowercase letters, digits and dashes)")
    if problems:
        raise ViewError(f"{where}: {len(problems)} problem(s): " + "; ".join(problems[:8])
                        + (" ..." if len(problems) > 8 else ""))


def from_build(declared: list[dict], widths: list[int]) -> list[dict]:
    """build.json's views[], one entry per width (a view may name its own widths)."""
    views = []
    check_ids(declared, "05-build/build.json")
    for v in declared:
        for width in v.get("widths") or widths:
            views.append({"screen": v["screen"], "state": v["state"], "width": int(width), "open": v["open"],
                          **({"what": v["what"]} if v.get("what") else {})})
    return views


def plan(ws: Workspace) -> dict:
    """The whole view plan for this round's build: {page, widths, views[], declared, inventory[]}.

    `declared` says whether the build named its views (so a missing inventory state is the build's word,
    not a guess). Each view carries its id, screen, state, width, height and how to open it; `walk` marks
    the one width per screen and state that the Tab walk and the action clicks use.
    """
    ws_step = ws.for_step(ws.step or "checks")
    build_file = ws_step.folder("build") / "build.json"
    if not build_file.is_file():
        raise ViewError(f"{build_file} is missing: the build step must run before the checks step")
    build = json.loads(ws_step.read_text(build_file))
    widths = [int(w) for w in build.get("widths") or []]
    if not widths:
        raise ViewError("05-build/build.json: widths: the build names no width to measure")
    page = Path(build.get("page") or "index.html")
    if not (ws_step.folder("build") / page).is_file():
        raise ViewError(f"05-build/build.json: page: {page} is not in 05-build/")

    inventory_file = ws_step.folder("ground") / "inventory.json"
    inventory = json.loads(ws_step.read_text(inventory_file))["screens"] if inventory_file.is_file() else []
    declared = build.get("views") or []
    if declared:
        views = from_build(declared, widths)
    else:
        views = from_inventory(inventory, widths)
        check_ids(views, "03-ground/inventory.json")
    if not views:
        raise ViewError("no view to open: 05-build/build.json has no views[] and 03-ground/inventory.json "
                        "no screen with a state")

    widest = max(widths)
    seen: set[tuple[str, str]] = set()
    out = []
    for v in sorted(views, key=lambda v: (v["screen"], v["state"], -v["width"])):
        key = (v["screen"], v["state"])
        walk = v["width"] == widest or (key not in seen and v["width"] == max(
            x["width"] for x in views if (x["screen"], x["state"]) == key))
        out.append({**v, "id": view_id(v["screen"], v["state"], v["width"]),
                    "height": height_for(v["width"]), "walk": bool(walk and key not in seen)})
        if walk:
            seen.add(key)
    return {"page": page.as_posix(), "widths": sorted(widths), "declared": bool(declared),
            "main": build.get("main") or "body", "areas": build.get("areas") or {},
            "inventory": inventory, "views": out}
