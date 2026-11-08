"""A product's design capture spec (<repo>/.temper/design/app.yaml): how stage 2 (existing) reads the app.

Declares what to capture (product job, login form selectors, page shell selectors, viewport sizes, and
screens/states with the account name that reaches each state). Runtime provisioning (build, env, seed,
serve, port, commit) belongs in the project's standee.yaml, and credentials arrive at runtime as a
workflow input — never in this file.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .contracts import ID, STATE, TEXT, WIDTH, ContractError, items, obj
from .workspace import Workspace

DESIGN_SUBDIR = Path(".temper") / "design"
SPEC_FILENAME = "app.yaml"


class AppFileError(ContractError):
    """The product's app file is missing or wrong; the message names each problem."""


SLUG = {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,39}$"}
STEP = {"oneOf": [
    obj({"goto": {"type": "string", "pattern": "^/"}}),
    obj({"follow_first_link": {"type": "string", "pattern": "^/"}}),
    obj({"click_first": obj({"text": TEXT}, {"not": TEXT})}),
]}
STATE_SPEC = obj({}, {
    "account": {"type": "string", "pattern": "^[A-Za-z0-9._+@-]{1,64}$"},
    "delay_api": {"type": ["boolean", "integer"]},
    "widths": items(WIDTH),
    "what": TEXT,
    "query": TEXT,
    "route": {"type": "string", "pattern": "^/"},
    "steps": items(STEP),
})
SCREEN = obj(
    {"id": SLUG, "name": TEXT,
     "states": {"type": "object", "minProperties": 1, "propertyNames": STATE,
                "additionalProperties": STATE_SPEC}},
    {"widths": items(WIDTH), "route": {"type": "string", "pattern": "^/"}, "steps": items(STEP), "what": TEXT},
)
SOURCE_PATH = {"type": "string", "minLength": 1, "pattern": r"^[^\\]+$"}
DATA_PATH = {"type": "string", "pattern": r"^[A-Za-z_][A-Za-z0-9_]*(\[\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[\])?)*$"}
INVARIANTS = obj({}, {
    "same_value": items(obj({"key": DATA_PATH, "field": DATA_PATH})),
    "totals": items(obj({"total": DATA_PATH, "plus": items(DATA_PATH)}, {"minus": items(DATA_PATH)})),
})
FIXTURE = obj({"file": SOURCE_PATH}, {"parts": SOURCE_PATH, "invariants": INVARIANTS})

DELAY_API = {"oneOf": [
    obj({"match": TEXT, "delay_ms": {"type": "integer", "minimum": 100},
         "wait_ms": {"type": "integer", "minimum": 0}}, {"except": TEXT}),
    obj({"url": TEXT, "method": TEXT}, {"ms": {"type": "integer", "minimum": 100}}),
]}

LOGIN = obj(
    {"path": {"type": "string", "pattern": "^/"}, "submit": TEXT, "wait_for": TEXT},
    {
        "fields": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "string"}},
        "email_field": TEXT,
        "user_field": TEXT,
        "user_selector": TEXT,
        "password_field": TEXT,
        "password_selector": TEXT,
        "default_account": TEXT,
    },
)

APP_FILE = obj({
    "product": ID,
    "page": obj({"main": TEXT}, {
        "areas": {"type": "object", "additionalProperties": TEXT},
        "key_regions": {"type": "object", "propertyNames": {"pattern": "^[a-z][a-z0-9_]{0,39}$"},
                        "additionalProperties": TEXT},
        "loading_text": TEXT,
        "settle_ms": {"type": "integer", "minimum": 0, "maximum": 20000},
        "error_selector": TEXT,
        "delay_api": DELAY_API,
    }),
    "sizes": {"type": "object", "minProperties": 1, "propertyNames": {"pattern": "^[0-9]{3,4}$"},
              "additionalProperties": obj(
                  {"height": {"type": "integer", "minimum": 240, "maximum": 3000}},
                  {"phone": {"type": "boolean"}, "name": ID},
              )},
    "sheet_width": WIDTH,
    "screens": items(SCREEN),
}, {
    "name": TEXT,
    "job": TEXT,
    "what": TEXT,
    "login": LOGIN,
    "capabilities": SOURCE_PATH,
    "notes": items(SOURCE_PATH),
    "sources": items(SOURCE_PATH),
    "fixture": FIXTURE,
})

# Forbidden runtime/provisioning keys that belong in standee.yaml, not .temper/design/app.yaml
STANDEE_KEYS = frozenset({
    "app", "build", "env", "env_file", "env_file_variable",
    "port", "serve", "seed", "commit", "checkout", "ready", "ui_globs",
})

# Forbidden secret keys: passwords/credentials are runtime inputs, never stored in files
SECRET_KEYS = frozenset({"password", "secret", "token", "api_key", "credentials"})

INTERNAL_META_KEYS = frozenset({
    "path", "design_dir", "temper_dir", "spec_sha256",
    "base_url", "version",
    "_design_dir", "_spec_file", "_spec_hash",
})


def _where(error) -> str:
    return "/".join(str(p) for p in error.absolute_path) or "(top)"


def _find_forbidden_keys(node: Any, path_prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            key_str = str(k)
            loc = f"{path_prefix}/{key_str}" if path_prefix else key_str
            low = key_str.lower()
            if low in STANDEE_KEYS and not path_prefix:
                found.append((loc, f"'{key_str}' belongs in the project's standee.yaml, not .temper/design/{SPEC_FILENAME}"))
            elif low in SECRET_KEYS and low not in ("password_field", "password_selector"):
                found.append((loc, f"'{key_str}' is a credential; pass credentials at runtime, never in .temper/design/{SPEC_FILENAME}"))
            found.extend(_find_forbidden_keys(v, loc))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            loc = f"{path_prefix}[{idx}]"
            found.extend(_find_forbidden_keys(item, loc))
    return found


def check(app: Any, label: str = "app.yaml") -> list[str]:
    """Every problem in a parsed app file, each '<label>: <field>: <reason>'."""
    if not isinstance(app, dict):
        return [f"{label}: (top): must be a YAML object"]
    clean = {k: v for k, v in app.items() if k not in INTERNAL_META_KEYS}
    forbidden = _find_forbidden_keys(clean)
    if forbidden:
        return [f"{label}: {loc}: {msg}" for loc, msg in forbidden]
    problems = [f"{label}: {_where(e)}: {e.message}"
                for e in sorted(Draft202012Validator(APP_FILE).iter_errors(clean), key=lambda e: list(e.path))]
    if problems:
        return problems
    if not (clean.get("job") or clean.get("what")):
        problems.append(f"{label}: job: 'job' (or 'what') is a required property")
    if "login" in clean:
        lg = clean["login"]
        has_fields = bool(lg.get("fields"))
        has_direct = bool(
            (lg.get("email_field") or lg.get("user_field") or lg.get("user_selector"))
            and (lg.get("password_field") or lg.get("password_selector"))
        )
        if not (has_fields or has_direct):
            problems.append(f"{label}: login: needs 'fields' or ('email_field'/'user_field'/'user_selector' + 'password_field'/'password_selector')")
    sizes = {int(w) for w in clean["sizes"]}
    seen: set[str] = set()
    default_account = (clean.get("login") or {}).get("default_account")
    for i, screen in enumerate(clean["screens"]):
        where = f"{label}: screens/{i}"
        if screen["id"] in seen:
            problems.append(f"{where}/id: {screen['id']} is used twice")
        seen.add(screen["id"])
        if ("route" in screen) == ("steps" in screen):
            problems.append(f"{where}: needs exactly one of route or steps")
        screen_widths = screen.get("widths", sorted(sizes))
        for state, spec in screen["states"].items():
            for w in spec.get("widths", screen_widths):
                if w not in sizes:
                    problems.append(f"{where}/states/{state}: width {w} is not in sizes")
            if "login" in clean and "account" not in spec and not default_account:
                problems.append(f"{where}/states/{state}: the app has a login, so the state needs an account")
            if spec.get("delay_api") and "delay_api" not in clean["page"]:
                problems.append(f"{where}/states/{state}: delay_api needs page.delay_api")
        for w in screen_widths:
            if w not in sizes:
                problems.append(f"{where}/widths: {w} is not in sizes")
    if clean["sheet_width"] not in sizes:
        problems.append(f"{label}: sheet_width: {clean['sheet_width']} is not in sizes")
    for name, pattern in (("page/loading_text", clean["page"].get("loading_text")),) + tuple(
            (f"screens/{i}/steps/{j}/click_first", step["click_first"][k])
            for i, s in enumerate(clean["screens"]) for j, step in enumerate(s.get("steps", []))
            if "click_first" in step for k in step["click_first"]):
        if pattern is not None:
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"{label}: {name}: not a regular expression ({exc})")
    return problems


def spec_path(product_or_repo: str | Path, store: Path | str | None = None) -> Path:
    """Resolve the path to <tree>/.temper/design/app.yaml from an explicit path or store."""
    if store is not None:
        base = Path(store)
        candidates = [
            base / str(product_or_repo) / DESIGN_SUBDIR / SPEC_FILENAME,
            base / DESIGN_SUBDIR / SPEC_FILENAME,
            base / str(product_or_repo) / SPEC_FILENAME,
            base / SPEC_FILENAME,
        ]
        for c in candidates:
            if c.is_file():
                return c
        if (base / str(product_or_repo)).exists():
            return base / str(product_or_repo) / DESIGN_SUBDIR / SPEC_FILENAME
        return base / DESIGN_SUBDIR / SPEC_FILENAME

    p = Path(product_or_repo)
    if p.is_file():
        return p
    if (p / DESIGN_SUBDIR / SPEC_FILENAME).is_file():
        return p / DESIGN_SUBDIR / SPEC_FILENAME
    if (p / SPEC_FILENAME).is_file() and p.name == "design" and p.parent.name == ".temper":
        return p / SPEC_FILENAME
    if p.name == ".temper" and (p / "design" / SPEC_FILENAME).is_file():
        return p / "design" / SPEC_FILENAME
    if isinstance(product_or_repo, Path) or "/" in str(product_or_repo) or "\\" in str(product_or_repo) or p.exists():
        if p.name == "design" and p.parent.name == ".temper":
            return p / SPEC_FILENAME
        return p / DESIGN_SUBDIR / SPEC_FILENAME
    raise AppFileError(
        f"product_app requires an explicit path to {DESIGN_SUBDIR / SPEC_FILENAME} (or --store), "
        f"not a bare product id: {product_or_repo!r}"
    )


def design_dir(product_or_repo: str | Path, store: Path | str | None = None) -> Path:
    return spec_path(product_or_repo, store).parent


def load(
    product: str | Path,
    store: Path | str | None = None,
    *,
    step: str = "existing_capture",
) -> dict[str, Any]:
    """The product's .temper/design/app.yaml, checked; AppFileError lists every problem."""
    path = spec_path(product, store)
    in_temper_design = path.parent.name == "design" and path.parent.parent.name == ".temper"
    try:
        if in_temper_design and path.parent.is_dir():
            ws_app = Workspace(path.parent, step=step)
            ws_app.resolve_input(".temper/design/app.yaml", repo_input=True)
            if not path.is_file() and (path.parent.parent / "topics").is_dir():
                res = subprocess.run(
                    ["git", "-C", str(path.parent.parent), "show", "HEAD:.temper/design/app.yaml"],
                    capture_output=True,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    path.write_bytes(res.stdout)
            raw_bytes = ws_app.read_bytes(
                ".temper/design/app.yaml", repo_input=True
            )
        else:
            with path.open("rb") as fh:
                raw_bytes = fh.read()
        app = yaml.safe_load(raw_bytes.decode("utf-8"))
    except ContractError as exc:
        raise AppFileError(str(exc)) from None
    except (OSError, yaml.YAMLError) as exc:
        raise AppFileError(
            f"{path}: (file): not a readable app file ({exc.__class__.__name__}: {exc})"
        ) from None
    problems = check(app, str(path))
    if (
        not problems
        and isinstance(product, str)
        and "/" not in product
        and "\\" not in product
        and not Path(product).exists()
        and app["product"] != product
    ):
        problems.append(f"{path}: product: is {app['product']!r}, but requested product is {product!r}")
    if problems:
        raise AppFileError(f"{len(problems)} problem(s): " + "; ".join(problems))
    if in_temper_design:
        notes_list = list(app.get("notes") or [])
        cap_ref = app.get("capabilities")
        refs_to_check = list(notes_list)
        if isinstance(cap_ref, str) and cap_ref and cap_ref != "derive":
            refs_to_check.append(cap_ref)
        allowed_topics = [r for r in refs_to_check if isinstance(r, str)]
        ws_repo = Workspace(path.parent, step=step)
        for rel in refs_to_check:
            try:
                ws_repo.resolve_input(rel, repo_input=True, allowed_topics=allowed_topics)
            except ContractError as exc:
                raise AppFileError(str(exc)) from None
    spec_sha = hashlib.sha256(raw_bytes).hexdigest()
    app.setdefault("name", app["product"])
    if "job" not in app and "what" in app:
        app["job"] = app["what"]
    if "what" not in app and "job" in app:
        app["what"] = app["job"]
    app["path"] = str(path)
    app["design_dir"] = str(path.parent)
    if in_temper_design:
        app["temper_dir"] = str(path.parent.parent)
    app["spec_sha256"] = spec_sha
    app["_design_dir"] = str(path.parent)
    app["_spec_file"] = str(path)
    app["_spec_hash"] = spec_sha
    return app


def capture_id(screen: str, width: int, state: str) -> str:
    return f"{screen}-{width}-{state}"


def captures(app: dict[str, Any]) -> list[dict[str, Any]]:
    """One capture per screen x state x width, in the app file's order: what the browser opens and does."""
    all_widths = sorted(int(w) for w in app["sizes"])
    default_account = (app.get("login") or {}).get("default_account")
    out = []
    for screen in app["screens"]:
        steps = screen.get("steps") or [{"goto": screen["route"]}]
        screen_widths = screen.get("widths", all_widths)
        for state, spec in screen["states"].items():
            if "steps" in spec:
                route_steps = list(spec["steps"])
            elif "route" in spec:
                route_steps = [{"goto": spec["route"]}]
            else:
                route_steps = list(steps)
            if spec.get("query"):
                route_steps = [({"goto": s["goto"] + spec["query"]} if "goto" in s else s) for s in route_steps]
            for width in spec.get("widths", screen_widths):
                size = app["sizes"][str(width)]
                phone = size.get("phone", int(width) < 768)
                wait_for = spec.get("wait_for") or screen.get("wait_for") or app["page"]["main"]
                account = spec.get("account") or default_account
                out.append({
                    "id": capture_id(screen["id"], width, state),
                    "screen": screen["id"],
                    "name": screen["name"],
                    "state": state,
                    "width": width,
                    "height": size["height"],
                    "phone": phone,
                    "account": account,
                    "delay_api": bool(spec.get("delay_api")),
                    "steps": route_steps,
                    "wait_for": wait_for,
                    "what": spec.get("what") or screen.get("what") or screen["name"],
                })
    return out
