"""A product's app file (~/design-lab/products/<product>/app.yaml): how stage 2 (existing) reads the app today.

The file says how to start a throwaway copy of the app (a pinned commit of a server app with its seed command,
or a folder of static pages), how to log in, what the page's parts are called, and which screens to capture:
each screen has an id, a name, a route or click steps, its states and its widths. load() checks the whole file
and fails loud (AppFileError naming every problem); captures() expands it into one capture per
screen x state x width, in the file's order. Model-free; used on the host only (bin/app_screen/existing.py).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .contracts import ID, STATE, TEXT, WIDTH, items, obj

STORE = Path(os.environ.get("APP_SCREEN_PRODUCTS", "/home/shinelay/design-lab/products"))
LOOPBACK = ("127.0.0.1", "localhost")


class AppFileError(ValueError):
    """The product's app file is missing or wrong; the message names each problem."""


SLUG = {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,39}$"}
PORT = {"type": "integer", "minimum": 1024, "maximum": 65535}
ARGV = items({"type": "string", "minLength": 1})
STEP = {"oneOf": [
    obj({"goto": {"type": "string", "pattern": "^/"}}),
    obj({"follow_first_link": {"type": "string", "pattern": "^/"}}),
    obj({"click_first": obj({"text": TEXT}, {"not": TEXT})}),
]}
STATE_SPEC = obj({}, {"account": {"type": "string", "pattern": "^[A-Za-z0-9._+-]{1,64}$"},
                      "delay_api": {"type": "boolean"}, "widths": items(WIDTH), "what": TEXT, "query": TEXT})
SCREEN = obj({"id": SLUG, "name": TEXT, "widths": items(WIDTH),
              "states": {"type": "object", "minProperties": 1, "propertyNames": STATE,
                         "additionalProperties": STATE_SPEC}},
             {"route": {"type": "string", "pattern": "^/"}, "steps": items(STEP), "what": TEXT})
SERVER = obj({"kind": {"const": "server"}, "repo": TEXT, "commit": {"type": "string", "pattern": "^[0-9a-f]{7,40}$"},
              "checkout": TEXT, "port": PORT, "build": items(obj({"cwd": TEXT, "run": ARGV}), least=0),
              "seed": ARGV, "serve": ARGV, "ready": {"type": "string", "pattern": "^/"}},
             {"env_file": {"type": "object", "additionalProperties": {"type": "string"}},
              "env_file_variable": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]*$"},
              "env": {"type": "object", "additionalProperties": {"type": "string"}}})
STATIC = obj({"kind": {"const": "static"}, "root": TEXT, "port": PORT}, {"ready": {"type": "string", "pattern": "^/"}})
# Stage 3 (ground): where the product's own sources are. A path is inside the repo at app.commit for a server
# app, else absolute or beside this file; capabilities "derive" runs configs/epd/bin/capabilities.py on the
# throwaway checkout (ground_host.py). The fixture (one JSON file, and optionally a folder of part files, each
# added under its file name) is design data: absolute or beside this file, never read from the repo. A path in
# the invariants: dotted keys, "[]" fans out over a list.
SOURCE_PATH = {"type": "string", "minLength": 1, "pattern": r"^[^\\]+$"}
DATA_PATH = {"type": "string", "pattern": r"^[A-Za-z_][A-Za-z0-9_]*(\[\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[\])?)*$"}
INVARIANTS = obj({}, {
    "same_value": items(obj({"key": DATA_PATH, "field": DATA_PATH})),
    "totals": items(obj({"total": DATA_PATH, "plus": items(DATA_PATH)}, {"minus": items(DATA_PATH)}))})
FIXTURE = obj({"file": SOURCE_PATH}, {"parts": SOURCE_PATH, "invariants": INVARIANTS})
# Step 4 (reuse, reuse.py): the app's UI files, as globs relative to the repo (server) or the static folder; "**"
# crosses folders. A change only there can be a delta (re-capture the screens the files map to); a change anywhere
# else runs stage 2 in full. Left out, every file counts as outside, so any change runs in full.
UI_GLOB = {"type": "string", "minLength": 1, "pattern": r"^(?!/)(?!.*\.\./)[^\\]+$"}
APP_FILE = obj({
    "product": ID, "name": TEXT, "job": TEXT, "app": {"oneOf": [SERVER, STATIC]},
    "page": obj({"main": TEXT}, {
        "areas": {"type": "object", "additionalProperties": TEXT},
        "key_regions": {"type": "object", "propertyNames": {"pattern": "^[a-z][a-z0-9_]{0,39}$"},
                        "additionalProperties": TEXT},
        "loading_text": TEXT, "settle_ms": {"type": "integer", "minimum": 0, "maximum": 20000},
        "error_selector": TEXT,
        "delay_api": obj({"match": TEXT, "delay_ms": {"type": "integer", "minimum": 1000},
                          "wait_ms": {"type": "integer", "minimum": 0}}, {"except": TEXT})}),
    "sizes": {"type": "object", "minProperties": 1, "propertyNames": {"pattern": "^[0-9]{3,4}$"},
              "additionalProperties": obj({"height": {"type": "integer", "minimum": 300, "maximum": 3000},
                                           "phone": {"type": "boolean"}})},
    "sheet_width": WIDTH,
    "screens": items(SCREEN),
}, {"login": obj({"path": {"type": "string", "pattern": "^/"}, "fields": {"type": "object", "minProperties": 1,
                                                                      "additionalProperties": {"type": "string"}},
                  "submit": TEXT, "wait_for": TEXT}),
    "capabilities": SOURCE_PATH, "notes": items(SOURCE_PATH), "fixture": FIXTURE, "ui_globs": items(UI_GLOB)})


def _where(error) -> str:
    return "/".join(str(p) for p in error.absolute_path) or "(top)"


def check(app: Any, label: str = "app.yaml") -> list[str]:
    """Every problem in a parsed app file, each "<label>: <field>: <reason>"."""
    problems = [f"{label}: {_where(e)}: {e.message}"
                for e in sorted(Draft202012Validator(APP_FILE).iter_errors(app), key=lambda e: list(e.path))]
    if problems:
        return problems
    sizes = {int(w) for w in app["sizes"]}
    seen: set[str] = set()
    for i, screen in enumerate(app["screens"]):
        where = f"{label}: screens/{i}"
        if screen["id"] in seen:
            problems.append(f"{where}/id: {screen['id']} is used twice")
        seen.add(screen["id"])
        if ("route" in screen) == ("steps" in screen):
            problems.append(f"{where}: needs exactly one of route or steps")
        for state, spec in screen["states"].items():
            for w in spec.get("widths", screen["widths"]):
                if w not in sizes:
                    problems.append(f"{where}/states/{state}: width {w} is not in sizes")
            if "login" in app and "account" not in spec:
                problems.append(f"{where}/states/{state}: the app has a login, so the state needs an account")
            if spec.get("delay_api") and "delay_api" not in app["page"]:
                problems.append(f"{where}/states/{state}: delay_api needs page.delay_api")
        for w in screen["widths"]:
            if w not in sizes:
                problems.append(f"{where}/widths: {w} is not in sizes")
    if app["sheet_width"] not in sizes:
        problems.append(f"{label}: sheet_width: {app['sheet_width']} is not in sizes")
    for name, pattern in (("page/loading_text", app["page"].get("loading_text")),) + tuple(
            (f"screens/{i}/steps/{j}/click_first", step["click_first"][k])
            for i, s in enumerate(app["screens"]) for j, step in enumerate(s.get("steps", []))
            if "click_first" in step for k in step["click_first"]):
        if pattern is not None:
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"{label}: {name}: not a regular expression ({exc})")
    a = app["app"]
    if app.get("capabilities") == "derive" and a["kind"] != "server":
        problems.append(f"{label}: capabilities: derive needs a server app (a checkout to read)")
    if a["kind"] == "server":
        repo, checkout = Path(a["repo"]).resolve(), Path(a["checkout"]).resolve()
        if checkout == repo or repo in checkout.parents or checkout in repo.parents:
            problems.append(f"{label}: app/checkout: must be its own folder, never inside the repo or around it")
    return problems


def load(product: str, store: Path | None = None) -> dict[str, Any]:
    """The product's app file, checked; AppFileError lists every problem."""
    path = (store or STORE) / product / "app.yaml"
    try:
        app = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AppFileError(f"{path}: (file): not a readable app file ({exc.__class__.__name__}: {exc})") from None
    problems = check(app, str(path))
    if not problems and app["product"] != product:
        problems.append(f"{path}: product: is {app['product']!r}, but the folder is {product!r}")
    if problems:
        raise AppFileError(f"{len(problems)} problem(s): " + "; ".join(problems))
    app["base_url"] = f"http://{LOOPBACK[0]}:{app['app']['port']}"
    app["path"] = str(path)
    return app


def capture_id(screen: str, width: int, state: str) -> str:
    return f"{screen}-{width}-{state}"


def captures(app: dict[str, Any]) -> list[dict[str, Any]]:
    """One capture per screen x state x width, in the app file's order: what the browser opens and does."""
    out = []
    for screen in app["screens"]:
        steps = screen.get("steps") or [{"goto": screen["route"]}]
        for state, spec in screen["states"].items():
            route_steps = steps
            if spec.get("query"):
                route_steps = [({"goto": s["goto"] + spec["query"]} if "goto" in s else s) for s in steps]
            for width in spec.get("widths", screen["widths"]):
                size = app["sizes"][str(width)]
                out.append({
                    "id": capture_id(screen["id"], width, state), "screen": screen["id"], "name": screen["name"],
                    "state": state, "width": width, "height": size["height"], "phone": size["phone"],
                    "account": spec.get("account"), "delay_api": bool(spec.get("delay_api")),
                    "steps": route_steps, "what": spec.get("what") or screen.get("what") or screen["name"],
                })
    return out
