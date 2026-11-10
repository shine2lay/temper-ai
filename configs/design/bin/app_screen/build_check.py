"""Stage 5a's deterministic checks on a built prototype in 05-build/ (rule 17: script first, no model).

Mirrors intake_check.py, existing_check.py and ground_check.py in shape and naming:
check() returns {verdict, pass, counts, checks, problems} where each problem is {check, where, problem}.

Checks:
- screen_file_per_inventory_screen  every screen in inventory.json has screens/<id>.js and a build.json entry
- shell_loads_every_screen_file     index.html loads every screen's script and shell/router.js
- view_per_screen_state             build.json has a view for every (screen, state) in inventory.json
- view_has_routing_target           every build.json view has a valid #<screen>/<state> route target
- screen_has_data_screen_root       every screen file renders a root carrying data-screen="<id>" and placeholder
- routing_reaches_every_view        every (screen, state) is reachable by #<screen>/<state> in router and screen
- data_req_in_fixture               every data-req field exists in fixture.json (and requirements in 01-request)
- no_hardcoded_figures              no currency, percentage, decimal or fixture figure hardcoded in screens/*.js
- tokens_from_product_file          styles/tokens.css is linked and holds all tokens from design-files/tokens.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .build_scaffold import extract_token_vars, resolve_fixture_field
from .workspace import Workspace

CHECKS = (
    "screen_file_per_inventory_screen",
    "shell_loads_every_screen_file",
    "view_per_screen_state",
    "view_has_routing_target",
    "screen_has_data_screen_root",
    "routing_reaches_every_view",
    "data_req_in_fixture",
    "no_hardcoded_figures",
    "tokens_from_product_file",
    "no_placeholder_left",
    "every_screen_state_designed",
    "every_show_covered",
    "single_primary_action",
)

SPEC_RE = re.compile(r"const\s+SCREEN_SPEC\s*=\s*(\{.*?\n\});", re.S)
ROUTE_TABLE_RE = re.compile(r"const\s+(?:ROUTE_TABLE|ROUTES)\s*=\s*(\{.*?\n\});", re.S)
RENDER_BODY_RE = re.compile(r"function\s+render\s*\([^)]*\)\s*\{(.*?)\n\s*\}\n", re.S)
DATA_REQ_ATTR_RE = re.compile(r'data-req="([^"]*)"')
SCRIPT_SRC_RE = re.compile(r'<script\b[^>]*\bsrc="([^"]+)"[^>]*></script>')
HARDCODED_FIG_RE = re.compile(
    r"\$[0-9][0-9,]*(?:\.[0-9]+)?"
    r"|[+-]?[0-9]+(?:\.[0-9]+)?%"
    r"|\b[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?\b"
    r"|\b[0-9]+\.[0-9]+\b"
    r"|\b[0-9]{2,}\b"
)
BANNED_COPY_RE = re.compile(
    r"\b(?:lorem\s+ipsum|dolor\s+sit\s+amet|tbd|todo|placeholder(?:\s+text|\s+copy)?|"
    r"coming\s+soon|sample\s+text|insert\s+copy\s+here|foo\s+bar)\b",
    re.I,
)
REQ_ID_RE = re.compile(r"^R[0-9]+$")


def has_hardcoded_figure(text: str) -> re.Match[str] | None:
    """Return a match if text contains a hardcoded figure (ignoring R1/S1/ID codes)."""
    cleaned = re.sub(r"\b[A-Z]{1,4}-[0-9]+\b", "ID", str(text or ""))
    cleaned = re.sub(r"\b[RS][0-9]+\b", "R", cleaned)
    return HARDCODED_FIG_RE.search(cleaned)


def has_banned_copy(text: str) -> re.Match[str] | None:
    """Return a match if text contains banned filler or placeholder copy."""
    return BANNED_COPY_RE.search(str(text or ""))


def _prob(check_name: str, where: str, problem: str) -> dict[str, str]:
    return {"check": check_name, "where": where, "problem": problem}


def _parse_screen_spec(js_text: str, problems: list[dict[str, str]], where: str) -> dict[str, Any] | None:
    m = SPEC_RE.search(js_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        problems.append(_prob("screen_file_per_inventory_screen", where, f"invalid SCREEN_SPEC JSON: {exc}"))
        return None
    return data if isinstance(data, dict) else None


def _parse_route_table(router_text: str, problems: list[dict[str, str]], where: str) -> dict[str, Any] | None:
    m = ROUTE_TABLE_RE.search(router_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        problems.append(_prob("shell_loads_every_screen_file", where, f"invalid ROUTE_TABLE JSON: {exc}"))
        return None
    return data if isinstance(data, dict) else None


def _strip_spec_widths(js_text: str) -> str:
    """Remove structural field-path metadata so figure scanning checks screen content and strings."""
    cleaned = re.sub(r'"widths"\s*:\s*\[[^\]]*\]', '"widths": []', js_text)
    cleaned = re.sub(r'"req_fields"\s*:\s*\[[^\]]*\]', '"req_fields": []', cleaned)
    cleaned = re.sub(r'data-req="[^"]*"', 'data-req=""', cleaned)
    cleaned = re.sub(r'resolveFixtureField\(fixture,\s*"[^"]*"\)', 'resolveFixtureField(fixture, "")', cleaned)
    cleaned = re.sub(r'"ref"\s*:\s*"S[0-9]+"', '"ref": "S"', cleaned)
    cleaned = re.sub(r'"fields"\s*:\s*\[[^\]]*\]', '"fields": []', cleaned)
    return cleaned


def _read_path_text(path: Path, ws: Workspace | None = None) -> str:
    ws_obj = ws or Workspace(path.parents[1], step="build_check")
    ws_step = ws_obj if ws_obj.step else ws_obj.for_step("build_check")
    return ws_step.read_text(path)


def check(
    build_dir: Path,
    inventory: dict[str, Any],
    fixture: dict[str, Any],
    tokens: dict[str, Any],
    requirements: dict[str, Any] | None = None,
    pass_name: str = "final",
    require_built: bool = False,
    draft: dict[str, Any] | None = None,
    ws: Workspace | None = None,
) -> dict[str, Any]:
    """Run all deterministic Stage 5a build checks against 05-build/."""
    ws = ws or Workspace(build_dir.parent, step="build_check")
    problems: list[dict[str, str]] = []
    inv_screens = [s for s in (inventory.get("screens") or []) if isinstance(s, dict) and isinstance(s.get("id"), str)]
    inv_by_id = {s["id"]: s for s in inv_screens}

    build_json_path = build_dir / "build.json"
    build_doc: dict[str, Any] = {}
    if not build_json_path.is_file():
        problems.append(_prob("screen_file_per_inventory_screen", "05-build/build.json", "missing 05-build/build.json"))
    else:
        try:
            parsed = json.loads(_read_path_text(build_json_path, ws))
            if isinstance(parsed, dict):
                build_doc = parsed
            else:
                problems.append(_prob("screen_file_per_inventory_screen", "05-build/build.json", "build.json is not an object"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(_prob("screen_file_per_inventory_screen", "05-build/build.json", f"unreadable JSON: {exc}"))

    index_path = build_dir / "index.html"
    index_text = _read_path_text(index_path, ws) if index_path.is_file() else ""
    if not index_path.is_file():
        problems.append(_prob("shell_loads_every_screen_file", "05-build/index.html", "missing 05-build/index.html"))

    router_path = build_dir / "shell" / "router.js"
    router_text = _read_path_text(router_path, ws) if router_path.is_file() else ""
    route_table = _parse_route_table(router_text, problems, "05-build/shell/router.js") if router_text else None
    if not router_path.is_file():
        problems.append(_prob("shell_loads_every_screen_file", "05-build/shell/router.js", "missing 05-build/shell/router.js"))

    build_screens = {
        s["id"]: s
        for s in (build_doc.get("screens") or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }

    # 1. screen_file_per_inventory_screen
    screen_js_by_id: dict[str, str] = {}
    screen_spec_by_id: dict[str, dict[str, Any]] = {}
    for s in inv_screens:
        sid = s["id"]
        rel_file = f"screens/{sid}.js"
        abs_file = build_dir / rel_file
        if sid not in build_screens:
            problems.append(_prob(
                "screen_file_per_inventory_screen",
                "05-build/build.json",
                f"screen {sid!r} in inventory.json is missing from build.json screens[]",
            ))
        elif build_screens[sid].get("file") != rel_file:
            problems.append(_prob(
                "screen_file_per_inventory_screen",
                "05-build/build.json",
                f"screen {sid!r} file is {build_screens[sid].get('file')!r}, expected {rel_file!r}",
            ))
        if not abs_file.is_file() or abs_file.stat().st_size == 0:
            problems.append(_prob(
                "screen_file_per_inventory_screen",
                f"05-build/{rel_file}",
                f"screen {sid!r} in inventory.json has no screen file at 05-build/{rel_file}",
            ))
        else:
            js_text = _read_path_text(abs_file, ws)
            screen_js_by_id[sid] = js_text
            spec = _parse_screen_spec(js_text, problems, f"05-build/{rel_file}")
            if spec is not None:
                screen_spec_by_id[sid] = spec

    screens_dir = build_dir / "screens"
    if screens_dir.is_dir():
        for extra_js in sorted(screens_dir.glob("*.js")):
            if extra_js.stem not in inv_by_id:
                problems.append(_prob(
                    "screen_file_per_inventory_screen",
                    f"05-build/screens/{extra_js.name}",
                    f"extra screen file {extra_js.name!r} is not in inventory.json",
                ))

    # 2. shell_loads_every_screen_file
    script_srcs = SCRIPT_SRC_RE.findall(index_text) if index_text else []
    script_src_set = set(script_srcs)
    for s in inv_screens:
        sid = s["id"]
        want_src = f"screens/{sid}.js"
        if want_src not in script_src_set:
            problems.append(_prob(
                "shell_loads_every_screen_file",
                "05-build/index.html",
                f"shell index.html does not load {want_src!r} for screen {sid!r}",
            ))
    if "shell/router.js" not in script_src_set:
        problems.append(_prob(
            "shell_loads_every_screen_file",
            "05-build/index.html",
            "shell index.html does not load 'shell/router.js'",
        ))

    # 3. view_per_screen_state
    views = [v for v in (build_doc.get("views") or []) if isinstance(v, dict)]
    views_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for v in views:
        v_screen = v.get("screen")
        v_state = v.get("state")
        if isinstance(v_screen, str) and isinstance(v_state, str):
            views_by_pair[(v_screen, v_state)] = v

    for s in inv_screens:
        sid = s["id"]
        for st in s.get("states") or []:
            if (sid, st) not in views_by_pair:
                problems.append(_prob(
                    "view_per_screen_state",
                    "05-build/build.json",
                    f"missing build.json view for screen {sid!r} state {st!r}",
                ))

    # 4. view_has_routing_target
    for idx, v in enumerate(views):
        v_screen = v.get("screen")
        v_state = v.get("state")
        open_spec = v.get("open") if isinstance(v.get("open"), dict) else {}
        h = open_spec.get("hash")
        want_hash = f"#{v_screen}/{v_state}"
        where = f"05-build/build.json:views[{idx}]"
        if not isinstance(h, str) or not h.startswith("#") or "/" not in h:
            problems.append(_prob(
                "view_has_routing_target",
                where,
                f"view ({v_screen}/{v_state}) has no valid routing hash target ({h!r})",
            ))
            continue
        if h != want_hash:
            problems.append(_prob(
                "view_has_routing_target",
                where,
                f"view ({v_screen}/{v_state}) open.hash is {h!r}, expected {want_hash!r}",
            ))
            continue
        spec = screen_spec_by_id.get(str(v_screen))
        screen_routes = (spec or {}).get("routes") if isinstance((spec or {}).get("routes"), dict) else {}
        if screen_routes.get(h) != v_state:
            problems.append(_prob(
                "view_has_routing_target",
                where,
                f"view ({v_screen}/{v_state}) hash {h!r} has no routing target in screens/{v_screen}.js",
            ))
        elif route_table is None or route_table.get(h, {}).get("screen") != v_screen or route_table.get(h, {}).get("state") != v_state:
            problems.append(_prob(
                "view_has_routing_target",
                where,
                f"view ({v_screen}/{v_state}) hash {h!r} has no routing target in shell/router.js",
            ))

    # 5. screen_has_data_screen_root
    for s in inv_screens:
        sid = s["id"]
        js_text = screen_js_by_id.get(sid, "")
        if not js_text:
            continue
        where = f"05-build/screens/{sid}.js"
        if f'data-screen="{sid}"' not in js_text:
            problems.append(_prob(
                "screen_has_data_screen_root",
                where,
                f"screen {sid!r} has no data-screen=\"{sid}\" root element",
            ))
        if 'data-view-state="' not in js_text:
            problems.append(_prob(
                "screen_has_data_screen_root",
                where,
                f"screen {sid!r} has no data-view-state attribute on its root element",
            ))
        if not require_built and f'data-build-placeholder="{sid}"' not in js_text and f'data-built-screen="{sid}"' not in js_text:
            problems.append(_prob(
                "screen_has_data_screen_root",
                where,
                f"screen {sid!r} has no data-build-placeholder=\"{sid}\" placeholder element",
            ))

    # 5b. no_placeholder_left (when require_built=True)
    if require_built:
        if build_doc.get("placeholder") is not False:
            problems.append(_prob(
                "no_placeholder_left",
                "05-build/build.json",
                "build.json still has placeholder != false after Stage 5b render",
            ))
        for s in inv_screens:
            sid = s["id"]
            js_text = screen_js_by_id.get(sid, "")
            if not js_text:
                continue
            where = f"05-build/screens/{sid}.js"
            if "data-build-placeholder" in js_text:
                problems.append(_prob(
                    "no_placeholder_left",
                    where,
                    f"screen {sid!r} still has a data-build-placeholder element in {where}",
                ))
            elif f'data-built-screen="{sid}"' not in js_text:
                problems.append(_prob(
                    "no_placeholder_left",
                    where,
                    f"screen {sid!r} is missing data-built-screen=\"{sid}\" rendered body in {where}",
                ))

    # 6. routing_reaches_every_view
    for s in inv_screens:
        sid = s["id"]
        js_text = screen_js_by_id.get(sid, "")
        if not js_text:
            continue
        where = f"05-build/screens/{sid}.js"
        spec = screen_spec_by_id.get(sid)
        if spec is None:
            problems.append(_prob(
                "routing_reaches_every_view",
                where,
                f"screen {sid!r} is missing a parseable SCREEN_SPEC route definition",
            ))
            continue
        spec_states = spec.get("states") if isinstance(spec.get("states"), list) else []
        spec_routes = spec.get("routes") if isinstance(spec.get("routes"), dict) else {}
        render_m = RENDER_BODY_RE.search(js_text)
        render_body = render_m.group(1) if render_m else ""
        dynamic_state_ok = (
            'data-view-state="\' + esc(state) + \'"' in render_body
            or 'data-view-state="\' + state + \'"' in render_body
        )
        for st in s.get("states") or []:
            h = f"#{sid}/{st}"
            if st not in spec_states:
                problems.append(_prob(
                    "routing_reaches_every_view",
                    where,
                    f"state {st!r} of screen {sid!r} is missing from SCREEN_SPEC.states (unreachable by {h})",
                ))
            elif spec_routes.get(h) != st:
                problems.append(_prob(
                    "routing_reaches_every_view",
                    where,
                    f"state {st!r} of screen {sid!r} is unreachable by {h} (routes[{h!r}]={spec_routes.get(h)!r})",
                ))
            elif route_table is None or route_table.get(h, {}).get("state") != st or route_table.get(h, {}).get("screen") != sid:
                problems.append(_prob(
                    "routing_reaches_every_view",
                    "05-build/shell/router.js",
                    f"state {st!r} of screen {sid!r} is unreachable by {h} in shell/router.js ROUTE_TABLE",
                ))
            elif not dynamic_state_ok:
                problems.append(_prob(
                    "routing_reaches_every_view",
                    where,
                    f"screen {sid!r} render() does not bind data-view-state dynamically for {h}",
                ))
            elif f'href="#{sid}/{st}"' not in js_text:
                problems.append(_prob(
                    "routing_reaches_every_view",
                    where,
                    f"state {st!r} of screen {sid!r} has no #{sid}/{st} link in {where}",
                ))

    # 7. data_req_in_fixture
    build_fixture_path = build_dir / "fixture.json"
    build_fixture: dict[str, Any] = {}
    if not build_fixture_path.is_file():
        problems.append(_prob("data_req_in_fixture", "05-build/fixture.json", "missing 05-build/fixture.json"))
    else:
        try:
            parsed_fx = json.loads(_read_path_text(build_fixture_path, ws))
            if isinstance(parsed_fx, dict) and parsed_fx:
                build_fixture = parsed_fx
            else:
                problems.append(_prob("data_req_in_fixture", "05-build/fixture.json", "05-build/fixture.json is empty"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(_prob("data_req_in_fixture", "05-build/fixture.json", f"unreadable JSON: {exc}"))

    active_fixture = build_fixture or fixture
    known_req_ids: set[str] = set()
    if requirements and isinstance(requirements.get("items"), list):
        for item in requirements["items"]:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                known_req_ids.add(item["id"])

    for s in inv_screens:
        sid = s["id"]
        js_text = screen_js_by_id.get(sid, "")
        if not js_text:
            continue
        where = f"05-build/screens/{sid}.js"
        spec = screen_spec_by_id.get(sid) or {}
        req_fields = spec.get("req_fields") if isinstance(spec.get("req_fields"), list) else []
        attr_Matches = DATA_REQ_ATTR_RE.findall(js_text)
        fixture_field_seen = False

        for field_path in req_fields:
            if not isinstance(field_path, str) or not field_path.strip():
                problems.append(_prob("data_req_in_fixture", where, "empty entry in SCREEN_SPEC.req_fields"))
                continue
            found, _ = resolve_fixture_field(active_fixture, field_path.strip())
            if not found:
                problems.append(_prob(
                    "data_req_in_fixture",
                    where,
                    f"data-req field {field_path!r} in req_fields is absent from fixture.json",
                ))
            else:
                fixture_field_seen = True

        for raw_attr in attr_Matches:
            tokens_in_attr = [t for t in raw_attr.split() if t]
            if not tokens_in_attr:
                problems.append(_prob("data_req_in_fixture", where, "empty data-req attribute"))
                continue
            for tok in tokens_in_attr:
                found, _ = resolve_fixture_field(active_fixture, tok)
                if found:
                    fixture_field_seen = True
                    continue
                if REQ_ID_RE.match(tok) and tok in known_req_ids:
                    continue
                problems.append(_prob(
                    "data_req_in_fixture",
                    where,
                    f"data-req {tok!r} names a field absent from fixture.json",
                ))

        if not fixture_field_seen:
            problems.append(_prob(
                "data_req_in_fixture",
                where,
                f"screen {sid!r} has no data-req naming a field in fixture.json",
            ))

    if index_text:
        html_without_fixture_script = re.sub(
            r'<script id="fixture-json".*?</script>', "", index_text, flags=re.S
        )
        for raw_attr in DATA_REQ_ATTR_RE.findall(html_without_fixture_script):
            for tok in raw_attr.split():
                found, _ = resolve_fixture_field(active_fixture, tok)
                if found or (REQ_ID_RE.match(tok) and tok in known_req_ids):
                    continue
                problems.append(_prob(
                    "data_req_in_fixture",
                    "05-build/index.html",
                    f"data-req {tok!r} in index.html names a field absent from fixture.json",
                ))

    # 8. no_hardcoded_figures
    for s in inv_screens:
        sid = s["id"]
        js_text = screen_js_by_id.get(sid, "")
        if not js_text:
            continue
        where = f"05-build/screens/{sid}.js"
        cleaned = _strip_spec_widths(js_text)
        # Remove requirement IDs like "R12", show refs like "S1", identifier codes like "PX-2041", and stage comments like "5a"/"5b"
        cleaned = re.sub(r"\b[A-Z]{1,4}-[0-9]+\b", "ID", cleaned)
        cleaned = re.sub(r"\b[RS][0-9]+\b", "R", cleaned)
        cleaned = re.sub(r"\b5[ab]\b", "five", cleaned)
        for m in HARDCODED_FIG_RE.finditer(cleaned):
            fig = m.group(0)
            problems.append(_prob(
                "no_hardcoded_figures",
                where,
                f"hardcoded figure {fig!r} in {where}; figures must come from fixture.json",
            ))
            break

    # 8b. Stage 5b draft checks: every_screen_state_designed, every_show_covered, single_primary_action, draft figures
    active_draft = draft
    if active_draft is None and require_built:
        draft_path = build_dir / "draft.json"
        if draft_path.is_file():
            try:
                parsed_d = json.loads(_read_path_text(draft_path, ws))
                if isinstance(parsed_d, dict):
                    active_draft = parsed_d
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(_prob("every_screen_state_designed", "05-build/draft.json", f"unreadable JSON: {exc}"))
                active_draft = None

    if require_built:
        draft_screens = {
            s["id"]: s
            for s in ((active_draft or {}).get("screens") or [])
            if isinstance(s, dict) and isinstance(s.get("id"), str)
        }
        for s in inv_screens:
            sid = s["id"]
            where = f"05-build/draft.json:screens[{sid}]"
            ds = draft_screens.get(sid)
            if not ds:
                problems.append(_prob(
                    "every_screen_state_designed",
                    where,
                    f"screen {sid!r} is missing from 05-build/draft.json",
                ))
                continue
            d_states = ds.get("states") if isinstance(ds.get("states"), dict) else {}
            for st in s.get("states") or []:
                st_spec = d_states.get(st)
                if not isinstance(st_spec, dict) or not str(st_spec.get("headline") or "").strip() or not str(st_spec.get("summary") or "").strip():
                    problems.append(_prob(
                        "every_screen_state_designed",
                        f"{where}.states.{st}",
                        f"screen {sid!r} state {st!r} is missing a non-empty headline or summary in draft.json",
                    ))
                else:
                    for key in ("headline", "summary", "badge"):
                        val = str(st_spec.get(key) or "")
                        cleaned_val = re.sub(r"\b[A-Z]{1,4}-[0-9]+\b", "ID", val)
                        cleaned_val = re.sub(r"\b[RS][0-9]+\b", "R", cleaned_val)
                        m = HARDCODED_FIG_RE.search(cleaned_val)
                        if m:
                            problems.append(_prob(
                                "no_hardcoded_figures",
                                f"{where}.states.{st}.{key}",
                                f"hardcoded figure {m.group(0)!r} in {where}.states.{st}.{key}; bind figures via fields[] paths instead of prose",
                            ))
                            break

            inv_shows = s.get("shows") or []
            expected_refs = [f"S{idx}" for idx in range(1, len(inv_shows) + 1)]
            d_shows = ds.get("shows") if isinstance(ds.get("shows"), list) else []
            covered_refs: set[str] = set()
            for sh_idx, sh in enumerate(d_shows):
                if not isinstance(sh, dict):
                    continue
                ref = str(sh.get("ref") or "").strip()
                heading = str(sh.get("heading") or "").strip()
                copy_txt = str(sh.get("copy") or "").strip()
                if ref and heading and copy_txt:
                    covered_refs.add(ref)
                for key, val in (("heading", heading), ("copy", copy_txt)):
                    cleaned_val = re.sub(r"\b[A-Z]{1,4}-[0-9]+\b", "ID", val)
                    cleaned_val = re.sub(r"\b[RS][0-9]+\b", "R", cleaned_val)
                    m = HARDCODED_FIG_RE.search(cleaned_val)
                    if m:
                        problems.append(_prob(
                            "no_hardcoded_figures",
                            f"{where}.shows[{sh_idx}].{key}",
                            f"hardcoded figure {m.group(0)!r} in {where}.shows[{sh_idx}].{key}; bind figures via fields[] paths instead of prose",
                        ))
                        break
                for fpath in sh.get("fields") or []:
                    if isinstance(fpath, str) and fpath.strip():
                        found, _ = resolve_fixture_field(active_fixture, fpath.strip())
                        if not found:
                            problems.append(_prob(
                                "data_req_in_fixture",
                                f"{where}.shows[{sh_idx}].fields",
                                f"draft field {fpath!r} on screen {sid!r} is absent from fixture.json",
                            ))
            missing_refs = [r for r in expected_refs if r not in covered_refs]
            if missing_refs:
                problems.append(_prob(
                    "every_show_covered",
                    f"{where}.shows",
                    f"screen {sid!r} draft is missing shows[] refs {missing_refs} (expected {expected_refs})",
                ))

            d_actions = [a for a in (ds.get("actions") or []) if isinstance(a, dict)]
            primaries = [a.get("id") for a in d_actions if a.get("kind") == "primary"]
            if len(primaries) > 1:
                problems.append(_prob(
                    "single_primary_action",
                    f"{where}.actions",
                    f"screen {sid!r} has {len(primaries)} primary actions ({primaries}); at most 1 primary action per screen is allowed",
                ))
            for a_idx, act in enumerate(d_actions):
                for key in ("label", "feedback"):
                    val = str(act.get(key) or "")
                    cleaned_val = re.sub(r"\b[A-Z]{1,4}-[0-9]+\b", "ID", val)
                    cleaned_val = re.sub(r"\b[RS][0-9]+\b", "R", cleaned_val)
                    m = HARDCODED_FIG_RE.search(cleaned_val)
                    if m:
                        problems.append(_prob(
                            "no_hardcoded_figures",
                            f"{where}.actions[{a_idx}].{key}",
                            f"hardcoded figure {m.group(0)!r} in {where}.actions[{a_idx}].{key}; bind figures via fields[] paths instead of prose",
                        ))
                        break

    # 9. tokens_from_product_file
    tokens_css_path = build_dir / "styles" / "tokens.css"
    if not tokens_css_path.is_file():
        problems.append(_prob(
            "tokens_from_product_file",
            "05-build/styles/tokens.css",
            "missing 05-build/styles/tokens.css",
        ))
    else:
        css_text = _read_path_text(tokens_css_path, ws)
        if 'href="styles/tokens.css"' not in index_text:
            problems.append(_prob(
                "tokens_from_product_file",
                "05-build/index.html",
                "index.html does not link styles/tokens.css",
            ))
        expected_vars = extract_token_vars(tokens)
        if not expected_vars:
            problems.append(_prob(
                "tokens_from_product_file",
                "03-ground/design-files/tokens.json",
                "no CSS token variables found in product token file",
            ))
        for var_name, var_val in sorted(expected_vars.items()):
            decl = f"{var_name}: {var_val};"
            if decl not in css_text:
                problems.append(_prob(
                    "tokens_from_product_file",
                    "05-build/styles/tokens.css",
                    f"token {var_name} ({var_val}) from tokens.json is missing or altered in styles/tokens.css",
                ))

    return {
        "verdict": "ok" if not problems else "retry",
        "pass": pass_name,
        "counts": {
            "screens": len(inv_screens),
            "views": len(views),
            "problems": len(problems),
        },
        "checks": list(CHECKS),
        "problems": problems,
    }


def check_workspace(
    ws: Workspace,
    pass_name: str = "final",
    require_built: bool = False,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load ground/request inputs and run check() against ws.folder('build')."""
    ws_step = ws if ws.step else ws.for_step("build_check")
    ground_dir = ws_step.folder("ground")
    inv_path = ground_dir / "inventory.json"
    fx_path = ground_dir / "fixture.json"
    tok_path = ground_dir / "design-files" / "tokens.json"
    req_path = ws_step.folder("intake") / "requirements.json"

    inventory = json.loads(ws_step.read_text(inv_path)) if inv_path.is_file() else {}
    fixture = json.loads(ws_step.read_text(fx_path)) if fx_path.is_file() else {}
    tokens = json.loads(ws_step.read_text(tok_path)) if tok_path.is_file() else {}
    requirements = json.loads(ws_step.read_text(req_path)) if req_path.is_file() else None

    return check(
        build_dir=ws_step.folder("build"),
        inventory=inventory,
        fixture=fixture,
        tokens=tokens,
        requirements=requirements,
        pass_name=pass_name,
        require_built=require_built,
        draft=draft,
        ws=ws_step,
    )


def validate_screen_draft_spec(
    inv_screen: dict[str, Any],
    draft_screen: dict[str, Any],
    fixture: dict[str, Any],
    where: str,
    *,
    state_check: str = "every_screen_state_designed",
    show_check: str = "every_show_covered",
    field_check: str = "data_req_in_fixture",
    quality_check: str = "state_and_action_quality",
    require_error_recovery: bool = False,
) -> list[dict[str, str]]:
    """Shared validator for one screen draft against its inventory screen and fixture."""
    problems: list[dict[str, str]] = []
    sid = str(inv_screen.get("id") or "")
    req_states = list(dict.fromkeys([*(inv_screen.get("states") or []), "normal", "loading", "empty", "error"]))
    if not inv_screen.get("states"):
        req_states = ["normal", "loading", "empty", "error"]
    else:
        req_states = [str(st) for st in inv_screen.get("states") or []]
        for base_st in ("normal", "loading", "empty", "error"):
            if base_st not in req_states:
                req_states.append(base_st)

    for top_key in ("title", "lead"):
        top_val = str(draft_screen.get(top_key) or "").strip()
        if not top_val:
            problems.append(_prob(quality_check, f"{where}.{top_key}", f"screen {sid!r} is missing non-empty {top_key}"))
            continue
        m_ban = has_banned_copy(top_val)
        if m_ban:
            problems.append(_prob(
                quality_check,
                f"{where}.{top_key}",
                f"banned filler copy {m_ban.group(0)!r} in {where}.{top_key}",
            ))
        m_fig = has_hardcoded_figure(top_val)
        if m_fig:
            problems.append(_prob(
                quality_check,
                f"{where}.{top_key}",
                f"hardcoded figure {m_fig.group(0)!r} in {where}.{top_key}; bind figures via fields[] paths",
            ))

    d_states = draft_screen.get("states") if isinstance(draft_screen.get("states"), dict) else {}
    seen_headlines: dict[str, str] = {}
    seen_summaries: dict[str, str] = {}
    for st in req_states:
        st_spec = d_states.get(st)
        headline = str((st_spec or {}).get("headline") or "").strip() if isinstance(st_spec, dict) else ""
        summary = str((st_spec or {}).get("summary") or "").strip() if isinstance(st_spec, dict) else ""
        if not headline or not summary:
            problems.append(_prob(
                state_check,
                f"{where}.states.{st}",
                f"screen {sid!r} state {st!r} is missing a non-empty headline or summary",
            ))
            continue
        norm_h = headline.lower()
        norm_s = summary.lower()
        if norm_h in seen_headlines:
            problems.append(_prob(
                quality_check,
                f"{where}.states.{st}.headline",
                f"screen {sid!r} state {st!r} repeats headline of state {seen_headlines[norm_h]!r}",
            ))
        else:
            seen_headlines[norm_h] = st
        if norm_s in seen_summaries:
            problems.append(_prob(
                quality_check,
                f"{where}.states.{st}.summary",
                f"screen {sid!r} state {st!r} repeats summary of state {seen_summaries[norm_s]!r}",
            ))
        else:
            seen_summaries[norm_s] = st

        for key in ("headline", "summary", "badge"):
            val = str(st_spec.get(key) or "")
            m_ban = has_banned_copy(val)
            if m_ban:
                problems.append(_prob(
                    quality_check,
                    f"{where}.states.{st}.{key}",
                    f"banned filler copy {m_ban.group(0)!r} in {where}.states.{st}.{key}",
                ))
            m_fig = has_hardcoded_figure(val)
            if m_fig:
                problems.append(_prob(
                    quality_check,
                    f"{where}.states.{st}.{key}",
                    f"hardcoded figure {m_fig.group(0)!r} in {where}.states.{st}.{key}; bind figures via fields[] paths",
                ))

    inv_shows = inv_screen.get("shows") or []
    expected_refs = [f"S{idx}" for idx in range(1, max(1, len(inv_shows)) + 1)]
    expected_ref_set = set(expected_refs)
    d_shows = draft_screen.get("shows") if isinstance(draft_screen.get("shows"), list) else []
    covered_refs: set[str] = set()
    for sh_idx, sh in enumerate(d_shows):
        if not isinstance(sh, dict):
            continue
        ref = str(sh.get("ref") or "").strip()
        heading = str(sh.get("heading") or "").strip()
        copy_txt = str(sh.get("copy") or "").strip()
        fields = [f.strip() for f in (sh.get("fields") or []) if isinstance(f, str) and f.strip()]
        if ref not in expected_ref_set:
            problems.append(_prob(
                show_check,
                f"{where}.shows[{sh_idx}].ref",
                f"show ref {ref!r} on screen {sid!r} is not in inventory shows {expected_refs}",
            ))
        elif heading and copy_txt and fields:
            covered_refs.add(ref)
        if not fields:
            problems.append(_prob(
                field_check,
                f"{where}.shows[{sh_idx}].fields",
                f"show {ref or sh_idx!r} on screen {sid!r} has no fixture fields[] paths",
            ))
        for fpath in fields:
            found, _ = resolve_fixture_field(fixture, fpath)
            if not found:
                problems.append(_prob(
                    field_check,
                    f"{where}.shows[{sh_idx}].fields",
                    f"draft field {fpath!r} on screen {sid!r} is absent from fixture.json",
                ))
        for key, val in (("heading", heading), ("copy", copy_txt)):
            m_ban = has_banned_copy(val)
            if m_ban:
                problems.append(_prob(
                    quality_check,
                    f"{where}.shows[{sh_idx}].{key}",
                    f"banned filler copy {m_ban.group(0)!r} in {where}.shows[{sh_idx}].{key}",
                ))
            m_fig = has_hardcoded_figure(val)
            if m_fig:
                problems.append(_prob(
                    quality_check,
                    f"{where}.shows[{sh_idx}].{key}",
                    f"hardcoded figure {m_fig.group(0)!r} in {where}.shows[{sh_idx}].{key}; bind figures via fields[] paths",
                ))
    missing_refs = [r for r in expected_refs if r not in covered_refs]
    if missing_refs:
        problems.append(_prob(
            show_check,
            f"{where}.shows",
            f"screen {sid!r} draft is missing shows[] refs {missing_refs} (expected {expected_refs})",
        ))

    d_actions = [a for a in (draft_screen.get("actions") or []) if isinstance(a, dict)]
    primaries = [a.get("id") for a in d_actions if a.get("kind") == "primary"]
    if len(primaries) == 0:
        problems.append(_prob(
            quality_check,
            f"{where}.actions",
            f"screen {sid!r} has no primary action (kind='primary')",
        ))
    elif len(primaries) > 1:
        problems.append(_prob(
            quality_check,
            f"{where}.actions",
            f"screen {sid!r} has {len(primaries)} primary actions ({primaries}); exactly 1 primary action per screen is allowed",
        ))
    if require_error_recovery and "error" in req_states:
        has_error_action = any(
            "error" in [str(st) for st in (a.get("states") or [])]
            for a in d_actions
        )
        if not has_error_action:
            problems.append(_prob(
                quality_check,
                f"{where}.actions",
                f"screen {sid!r} has no error recovery action with 'error' in actions[].states",
            ))
    for a_idx, act in enumerate(d_actions):
        for key in ("label", "feedback"):
            val = str(act.get(key) or "").strip()
            if not val:
                problems.append(_prob(
                    quality_check,
                    f"{where}.actions[{a_idx}].{key}",
                    f"screen {sid!r} action {act.get('id')!r} is missing non-empty {key}",
                ))
                continue
            m_ban = has_banned_copy(val)
            if m_ban:
                problems.append(_prob(
                    quality_check,
                    f"{where}.actions[{a_idx}].{key}",
                    f"banned filler copy {m_ban.group(0)!r} in {where}.actions[{a_idx}].{key}",
                ))
            m_fig = has_hardcoded_figure(val)
            if m_fig:
                problems.append(_prob(
                    quality_check,
                    f"{where}.actions[{a_idx}].{key}",
                    f"hardcoded figure {m_fig.group(0)!r} in {where}.actions[{a_idx}].{key}; bind figures via fields[] paths",
                ))
    return problems
