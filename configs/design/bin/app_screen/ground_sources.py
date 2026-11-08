"""Stage 3's source items: everything the inventory must account for, each with a stable id the model cites.

    page:<route>          a page of the capability map (Pages)          must be placed or excluded
    api:<METHOD path>     an HTTP route of the capability map           must be placed or excluded
    screen:<id>           a screen stage 2 captured (02-existing/app.json)        must be placed
    req:<id>              a requirement from stage 1 (01-request/requirements.json) must be placed or excluded
    journey:<id>          a journey stage 2 found (02-existing/journeys.json)     context
    seen:<id>             the words stage 2's captures of that screen show (02-existing/texts.json), the app's
                          frame (words on half the screens or more) left out             context
    note:<file>#L<n>      one line of a knowledge file the product file names     must be placed or excluded

Commands (the map's cli entries) are left out: the design covers the app's screens. Also the design-file status,
from design_files.inventory on the host's pack (never worked out here). Model-free; runs in the worker.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .workspace import Workspace

DESIGN_BIN = Path(__file__).resolve().parent.parent      # configs/design/bin (design_files.py)
PLACED = ("page", "api", "screen", "req", "note")        # kinds every inventory must account for
EXCLUDABLE = ("page", "api", "req", "note")              # a screen the app has today is never left out
KIND_OF = {"page": "page", "http": "api"}
WORD_RUN = re.compile(r"[A-Za-z]{3}")                 # a visible text run worth reading: three letters or more
SEEN_JOIN = " · "
# an outcome code a source names ("refused with locker_full"): snake or kebab case, so "422 with paths" is not one
NAMED_CONDITION = re.compile(r"\b(?:refused|refuses|rejected|rejects|fails|failed|declined|denied|blocked)\s+with\s+"
                             r"`?([a-z][a-z0-9]*(?:[_-][a-z0-9]+)+)`?")


class SourcesError(ValueError):
    """A stage 3 input is missing or unreadable; the message says which and who writes it."""


def _read(ws: Workspace, path: Path, who: str):
    if not path.is_file():
        raise SourcesError(f"{path.name} is missing ({who})")
    ws_step = ws if ws.step else ws.for_step("ground_collect")
    try:
        return json.loads(ws_step.read_text(path))
    except ValueError as exc:
        raise SourcesError(f"{path.name}: not readable JSON ({exc})") from None


def named_conditions(text: str) -> list[str]:
    """The outcome codes a source item's text names ("refused with locker_full" -> locker_full), each one a state."""
    return sorted(set(NAMED_CONDITION.findall(text)))


def design_status(ground: Path) -> str:
    """defined, partial or none: design_files.inventory on the pack ground-prep made (hashes checked)."""
    if str(DESIGN_BIN) not in sys.path:
        sys.path.insert(0, str(DESIGN_BIN))
    import design_files
    try:
        manifest = design_files.verify_pack(ground)
        files = design_files.read_files(ground / "design-files")
        return design_files.inventory(manifest.get("registry_entry"), files, "app_screen",
                                      fixture=bool(manifest.get("fixture")))["status"]
    except ValueError as exc:
        raise SourcesError(f"design files: {exc}") from None


def seen(texts: dict, audit: dict) -> dict[str, str]:
    """Each stage 2 screen's visible words: its captures' text runs (every width and state), once each in the order
    first shown, without runs of the app's frame (shown on half the screens or more) or runs with no word."""
    runs: dict[str, list[str]] = {}
    for cap in audit.get("screens", []):
        if cap["id"] not in texts:
            raise SourcesError(f"texts.json has no text for capture {cap['id']} (stage 2's capture writes it)")
        mine = runs.setdefault(cap["screen"], [])
        for run in texts[cap["id"]].get("all", []):
            run = " ".join(str(run).split())
            if WORD_RUN.search(run) and run not in mine:
                mine.append(run)
    on = {}
    for screen_runs in runs.values():
        for run in screen_runs:
            on[run] = on.get(run, 0) + 1
    frame = {run for run, n in on.items() if len(runs) > 1 and n * 2 >= len(runs)}
    return {screen: SEEN_JOIN.join(r for r in screen_runs if r not in frame) for screen, screen_runs in runs.items()}


def items(ws: Workspace, prep: dict) -> list[dict]:
    """Every source item, in the task's order: pages, API, stage 2 screens, their visible words, requirements,
    journeys, notes."""
    out: list[dict] = []
    for cap in prep["capabilities"]["items"]:
        kind = KIND_OF.get(cap["kind"])
        if kind:
            out.append({"id": f"{kind}:{cap['key']}", "kind": kind, "text": cap["intent"] or "(undescribed)",
                        **({"group": cap["group"]} if cap.get("group") else {}),
                        **({"where": cap["where"]} if cap.get("where") else {})})
    app = _read(ws, ws.folder("existing") / "app.json", "stage 2's capture writes it")
    for s in app.get("screens", []):
        states = "; ".join(f"{name} ({spec.get('what', '')})" for name, spec in s.get("states", {}).items())
        out.append({"id": f"screen:{s['id']}", "kind": "screen", "text": f"{s['name']}. Captured states: {states}"})
    words = seen(_read(ws, ws.folder("existing") / "texts.json", "stage 2's capture writes it"),
                 _read(ws, ws.folder("existing") / "audit.json", "stage 2's capture writes it"))
    for s in app.get("screens", []):
        if words.get(s["id"]):
            out.append({"id": f"seen:{s['id']}", "kind": "seen", "text": words[s["id"]]})
    reqs = _read(ws, ws.folder("intake") / "requirements.json", "stage 1 (intake) writes it")
    for r in reqs.get("items", []):
        maps = ", ".join(r.get("maps_to", []))
        means = f"; means: {r['means'].rstrip('.')}" if r.get("means") else ""
        out.append({"id": f"req:{r['id']}", "kind": "req",
                    "text": f"\"{r['owner_words']}\" ({r.get('kind', '')}{means}{'; maps to ' + maps if maps else ''})"})
    journeys = _read(ws, ws.folder("existing") / "journeys.json", "stage 2 (existing) writes it")
    for j in journeys.get("journeys", []):
        screens = ", ".join(j.get("screens", []))
        out.append({"id": f"journey:{j['id']}", "kind": "journey",
                    "text": f"{j['name']}: {j['goal']}{' (screens ' + screens + ')' if screens else ''}"})
    ws_step = ws if ws.step else ws.for_step("ground_collect")
    for note in prep["notes"]:
        path = ws.folder("ground") / note["file"]
        if not path.is_file():
            raise SourcesError(f"03-ground/{note['file']} is missing (ground-prep writes it)")
        for n, line in enumerate(ws_step.read_text(path).splitlines(), 1):
            text = line.strip()
            if text and not text.startswith("#"):
                out.append({"id": f"note:{note['name']}#L{n}", "kind": "note", "text": text})
    ids = [i["id"] for i in out]
    twice = sorted({i for i in ids if ids.count(i) > 1})
    if twice:
        raise SourcesError(f"source ids used twice: {', '.join(twice[:8])}")
    return out
