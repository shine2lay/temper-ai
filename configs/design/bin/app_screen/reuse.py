"""Step 4: whether stages 2 (existing) and 3 (ground) may reuse a product's stored work. Deterministic, no model.

A fingerprint says what the stored work was made from: the app's UI files (the app file's `ui_globs`, hashed
at the pinned commit with `git ls-tree`, or over the static folder), one hash over every other file, and one
over the app file's screens, sizes, page block, login and globs. Then for stage 2:

    reuse   a stored version exists, it validates, and the fingerprint is unchanged
    delta   only UI files changed, and each changed file maps to captured screens: a static page by its route;
            a server file by its path's words naming a capability-map page group, whose route a screen opens
    run     nothing stored, an invalid store, a screens/sizes/page change, a change outside the UI files, a
            changed file that maps to no screen, or forced

Stage 3's product part follows stage 2's decision; its request part (new requirements) is settled later by
ground_collect (ground_delta.py), because the requirements are known only after intake. Every decision carries
its reason, in plain words.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

STAGES = ("existing", "ground")
SCREEN_SPEC_KEYS = ("screens", "sizes", "page", "login", "sheet_width", "ui_globs")


class ReuseError(ValueError):
    """The fingerprint could not be taken (no repo, no commit, no folder); the message says which."""


@dataclass
class Decision:
    stage: str
    decision: str                      # reuse | delta | run | pending (ground, finished by ground_collect)
    reason: str
    screens: list[str] = field(default_factory=list)      # delta: the screens to capture again
    changed: list[str] = field(default_factory=list)      # delta: the changed UI files

    def record(self) -> dict:
        out = {"decision": self.decision, "reason": self.reason}
        if self.screens:
            out["screens"] = list(self.screens)
        return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def glob_regex(glob: str) -> re.Pattern:
    """A path glob as a regex: '**/' any folders (or none), '**' anything, '*' within a folder, '?' one char."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(f"^{out}$")


def is_ui(path: str, globs: list[str]) -> bool:
    return any(glob_regex(g).match(path) for g in globs)


def _tree(app: dict) -> dict[str, str]:
    """Every file of the app with its content hash: git blob ids at the pinned commit, or sha256 of the
    static folder's files."""
    spec = app["app"]
    if spec["kind"] == "server":
        try:
            done = subprocess.run(["git", "-C", spec["repo"], "ls-tree", "-r", "--full-tree", spec["commit"]],
                                  capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReuseError(f"git ls-tree {spec['commit']} in {spec['repo']} did not run: {exc}") from None
        if done.returncode:
            raise ReuseError(f"git ls-tree {spec['commit']} in {spec['repo']}: {done.stderr.strip()[:300]}")
        tree = {}
        for line in done.stdout.splitlines():
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) == 3 and parts[1] == "blob":
                tree[path] = parts[2]
        return tree
    root = Path(spec["root"])
    if not root.is_dir():
        raise ReuseError(f"static folder {root} is missing")
    tree = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            tree[path.relative_to(root).as_posix()] = sha256_file(path)
    return tree


def screen_spec(app: dict) -> dict:
    return {k: app.get(k) for k in SCREEN_SPEC_KEYS}


def fingerprint(app: dict) -> dict:
    """What stage 2's and 3's product part were made from (stored in each version's source.json)."""
    globs = list(app.get("ui_globs") or [])
    tree = _tree(app)
    ui = {p: h for p, h in sorted(tree.items()) if is_ui(p, globs)}
    other = [f"{h} {p}" for p, h in sorted(tree.items()) if p not in ui]
    out = {"kind": app["app"]["kind"], "ui_globs": globs, "ui": ui,
           "ui_sha256": sha256_text(json.dumps(ui, sort_keys=True)),
           "other_sha256": sha256_text("\n".join(other)),
           "screens_sha256": sha256_text(json.dumps(screen_spec(app), sort_keys=True, ensure_ascii=False)),
           "app_yaml_sha256": sha256_file(Path(app["path"])) if app.get("path") else None}
    if app["app"]["kind"] == "server":
        out["commit"] = app["app"]["commit"]
    else:
        out["root"] = app["app"]["root"]
    return out


def changed_ui(old: dict, new: dict) -> list[str]:
    """UI files added, removed or changed between two fingerprints."""
    a, b = old.get("ui", {}), new.get("ui", {})
    return sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))


def _route_path(route: str) -> str:
    return route.split("?", 1)[0].split("#", 1)[0]


def _route_regex(route: str) -> re.Pattern:
    """A capability-map route ('/positions/:symbol') as a regex over a screen's path."""
    parts = [("[^/]+" if seg.startswith(":") else re.escape(seg)) for seg in _route_path(route).split("/")]
    return re.compile("^" + "/".join(parts) + "/?$")


def screen_paths(screen: dict) -> list[str]:
    """The paths a screen opens: its route, or its steps' goto targets."""
    if screen.get("route"):
        return [_route_path(screen["route"])]
    return [_route_path(s["goto"]) for s in screen.get("steps", []) if "goto" in s]


def _words(path: str) -> set[str]:
    parts = path.lower().split("/")
    return {p for p in parts[:-1]} | {parts[-1].split(".", 1)[0]}


def screens_for_files(app: dict, files: list[str], page_items: list[dict]) -> tuple[list[str], list[str]]:
    """(screens to capture again, files that map to no captured screen).

    Static app: a file is the page whose route is '/<file>'. Server app: a file's folder and stem words (lower
    case) naming a capability-map page's group give that page's route; the screens opening that route are
    the file's screens. A file naming no page, or a page no screen captures, maps to nothing."""
    static = app["app"]["kind"] == "static"
    screens: list[str] = []
    unmapped: list[str] = []
    for path in files:
        if static:
            routes = [_route_regex("/" + path)]
        else:
            words = _words(path)
            routes = [_route_regex(i["id"].removeprefix("page:")) for i in page_items
                      if i.get("kind") == "page" and str(i.get("group", "")).lower() in words]
        hit = [s["id"] for s in app["screens"]
               if any(r.match(p) for r in routes for p in screen_paths(s))]
        if not hit:
            unmapped.append(path)
        screens += [s for s in hit if s not in screens]
    order = [s["id"] for s in app["screens"]]
    return sorted(screens, key=order.index), unmapped


def decide_existing(app: dict, now: dict, stored: dict | None, problems: list[str], force: bool,
                    page_items: list[dict]) -> Decision:
    """Stage 2's decision. stored = the current version's source.json (None: nothing stored); problems = the
    stored version's validation problems; page_items = the stored ground's page source items (server mapping)."""
    if force:
        return Decision("existing", "run", "forced (--force existing)")
    if stored is None:
        return Decision("existing", "run", "nothing stored for this product")
    if problems:
        return Decision("existing", "run", f"the stored version v{stored.get('version')} is invalid: "
                                           + "; ".join(problems[:3]))
    old = stored.get("fingerprint", {})
    if old.get("screens_sha256") != now["screens_sha256"]:
        return Decision("existing", "run", "the app file's screens, sizes, page block, login or ui_globs changed")
    if old.get("other_sha256") != now["other_sha256"]:
        return Decision("existing", "run", "files outside the UI globs changed"
                        + (" (or no ui_globs: every file counts as outside)" if not now["ui_globs"] else ""))
    changed = changed_ui(old, now)
    if not changed:
        return Decision("existing", "reuse", f"fingerprint unchanged since v{stored.get('version')} "
                                             f"(run {stored.get('run')})")
    screens, unmapped = screens_for_files(app, changed, page_items)
    if unmapped:
        return Decision("existing", "run", f"{len(unmapped)} changed file(s) map to no captured screen: "
                                           + ", ".join(unmapped[:5]))
    return Decision("existing", "delta", f"{len(changed)} UI file(s) changed: {', '.join(changed[:5])}; "
                                         f"re-capture {', '.join(screens)}", screens, changed)


def decide_ground(existing: Decision, stored: dict | None, problems: list[str], force: bool) -> Decision:
    """Stage 3's decision at prepare: run, or pending (ground_collect settles reuse or delta once the new
    requirements are known)."""
    if force:
        return Decision("ground", "run", "forced (--force ground)")
    if stored is None:
        return Decision("ground", "run", "nothing stored for this product")
    if problems:
        return Decision("ground", "run", f"the stored version v{stored.get('version')} is invalid: "
                                         + "; ".join(problems[:3]))
    if existing.decision == "run":
        return Decision("ground", "run", f"stage 2 runs in full ({existing.reason})")
    return Decision("ground", "pending", f"stored v{stored.get('version')} (run {stored.get('run')}); stage 2 "
                                         f"{'reused' if existing.decision == 'reuse' else 'redid ' + ', '.join(existing.screens)}"
                                         "; ground_collect places what is new")


def parse_force(text: str | None) -> set[str]:
    stages = {s.strip() for s in (text or "").split(",") if s.strip()}
    unknown = stages - set(STAGES)
    if unknown:
        raise ReuseError(f"--force takes {','.join(STAGES)}, not {', '.join(sorted(unknown))}")
    return stages
