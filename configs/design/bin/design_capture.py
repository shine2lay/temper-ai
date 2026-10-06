#!/usr/bin/env python3
"""design_capture (design role): what a design review looks at, captured before any model sees it.

Target size is measured by WCAG 2.5.8 in full (label area and the spacing exception), inactive
controls' text is exempt from contrast, and facts.md lists the measured PASSES next to the
problems (a pass is a fact too: critics stop reporting failures the facts rule out, and
design_review_verify.py checks their claims against them). v2 2026-10-04, queue #7.

For each page and viewport it saves the page as screen-sized tiles (PNG) and a facts file:
axe-core 4.13.0 (WCAG 2.0-2.2 A/AA rules) plus design_measure.js (text contrast, type styles,
headings, long lines, target sizes, control boundaries, field names, unnamed graphics,
reflow) and a keyboard walk (every Tab stop and whether it shows a focus ring).

The browser is temper's playwright-mcp service. A local site folder is served over HTTP from
this process, at this machine's address on the network the browser sits on, so pages load
from a real origin (the browser refuses file:). A deployed site is given by --base-url.

    design_capture.py --out DIR --pages index.html,pricing.html --site SITE_DIR
    design_capture.py --out DIR --pages /,/pricing --base-url https://staging.example.com

Writes DIR/shots/*.png, DIR/facts/*.json, DIR/facts.md (the measured problems and passes and
the page's type, headings, fields and tab order, merged over viewports: what a reviewer reads
first) and DIR/capture.json; prints a JSON summary.

--page-checks (queue #39) adds the model-free page checks of design_page_checks.py to each view:
repeated copy, the primary action in the first phone screen (--primary-action, else the "Primary
action:" line of DIR/brief.md), the navigation on one phone line, empty columns, interactive
elements without a visible cue, text over images measured from the pixels behind it, small light
text on dark backgrounds and pictures per section; and, when the page offers a dark colour scheme,
a desktop pass in it (view desktop-dark). --context ID writes DIR/context.md from the design
context playbook. Without --page-checks the capture is unchanged.
"""

import argparse
import asyncio
import base64
import functools
import http.server
import json
import pathlib
import re
import socket
import socketserver
import sys
import threading
import urllib.parse

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design_page_checks as pc  # noqa: E402 - sits next to this script

AXE = HERE / "vendor" / "axe-4.13.0.min.js"
MEASURE = HERE / "design_measure.js"
VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}
MAX_TILES = 10
MAX_TABS = 60
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - silence the access log
        pass


def serve(site: pathlib.Path, browser_host: str) -> tuple[str, socketserver.BaseServer]:
    handler = functools.partial(Quiet, directory=str(site))
    srv = socketserver.ThreadingTCPServer(("0.0.0.0", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((socket.gethostbyname(browser_host), 80))
        ip = probe.getsockname()[0]
    finally:
        probe.close()
    return f"http://{ip}:{srv.server_address[1]}", srv


def result(res) -> object:
    """The JSON value a playwright-mcp tool returned, or raise with its error."""
    text = "\n".join(getattr(c, "text", "") or "" for c in res.content)
    if getattr(res, "isError", False) or text.startswith("### Error"):
        raise RuntimeError(text[:800])
    m = re.search(r"### Result\n(.*?)(?:\n### |\Z)", text, re.S)
    if not m:
        return None
    body = m.group(1).strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


async def run(s: ClientSession, code: str) -> object:
    return result(await s.call_tool("browser_run_code_unsafe", {"code": code}))


def slug(path: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", path.strip("/")).strip("-").lower()
    return re.sub(r"-html?$", "", s) or "home"


FOCUS_FN = """() => {
  const e = document.activeElement;
  if (!e || e === document.body || e === document.documentElement) return null;
  const cs = getComputedStyle(e); const r = e.getBoundingClientRect();
  const path = []; for (let x = e; x && x !== document.body && path.length < 4; x = x.parentElement) {
    let s = x.tagName.toLowerCase(); if (x.id) { path.unshift('#' + x.id); break; }
    if (x.classList.length) s += '.' + [...x.classList].slice(0, 2).join('.');
    const sib = x.parentElement ? [...x.parentElement.children].filter(y => y.tagName === x.tagName) : [];
    if (sib.length > 1) s += ':nth-of-type(' + (sib.indexOf(x) + 1) + ')'; path.unshift(s); }
  const byIds = (ids) => ids.split(/\\s+/).map(i => document.getElementById(i)).filter(Boolean).map(x => x.innerText).join(' ');
  const name = (e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') && byIds(e.getAttribute('aria-labelledby')))
    || (e.labels && e.labels.length && [...e.labels].map(l => l.innerText).join(' ')) || e.innerText
    || e.getAttribute('placeholder') || e.value || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
  const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
  return {sel: path.join(' > '), name, ring, outline: cs.outlineStyle + ' ' + cs.outlineWidth, box_shadow: cs.boxShadow,
          box: [Math.round(r.left), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)]};
}"""


async def capture_one(
    s: ClientSession,
    url: str,
    name: str,
    vp: str,
    out: pathlib.Path,
    axe_src: str,
    measure_src: str,
    checks: dict | None = None,
    scheme: str | None = None,
) -> dict:
    """One page at one viewport. checks (page checks on): {"thresholds", "primary"}; scheme "dark"
    captures the page in its dark colour scheme as view <vp>-dark (no Tab walk: same as light)."""
    w, h = VIEWPORTS[vp]
    view = f"{vp}-{scheme}" if scheme else vp
    media = (
        f"await page.emulateMedia({{colorScheme: {json.dumps(scheme or 'light')}}}); "
        if checks is not None
        else ""
    )
    await run(
        s,
        f"async (page) => {{ await page.setViewportSize({{width: {w}, height: {h}}}); "
        + media
        + f"await page.goto({json.dumps(url)}, {{waitUntil: 'networkidle'}}); "
        "await page.evaluate(() => document.fonts.ready.then(() => true)); return true; }",
    )
    height = await run(
        s,
        "async (page) => await page.evaluate(() => document.documentElement.scrollHeight)",
    )
    tiles = []
    y = 0
    while y < int(height or h) and len(tiles) < MAX_TILES:
        th = min(h, int(height) - y)
        b64 = await run(
            s,
            f"async (page) => (await page.screenshot({{fullPage: true, type: 'png', "
            f"clip: {{x: 0, y: {y}, width: {w}, height: {th}}}}})).toString('base64')",
        )
        tile = out / "shots" / f"{name}-{view}-{len(tiles) + 1}.png"
        tile.write_bytes(base64.b64decode(b64))
        tiles.append({"file": str(tile.relative_to(out)), "y": y, "height": th})
        y += h
    axe = await run(
        s,
        "async (page) => { await page.evaluate(" + json.dumps(axe_src) + "); "
        "return await page.evaluate(async () => { const r = await axe.run(document, "
        "{runOnly: {type: 'tag', values: "
        + json.dumps(AXE_TAGS)
        + "}, resultTypes: ['violations']}); "
        "return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help, "
        "wcag: v.tags.filter(t => /^wcag\\d/.test(t)), nodes: v.nodes.slice(0, 10).map(n => "
        "({target: n.target.join(' '), summary: (n.failureSummary || '').slice(0, 300)}))})); }); }",
    )
    facts = await run(
        s, "async (page) => await page.evaluate(" + json.dumps(measure_src) + ")"
    )
    stops = []
    if not scheme:
        stops = await run(
            s,
            "async (page) => { await page.evaluate(() => { window.scrollTo(0, 0); "
            "if (document.activeElement) document.activeElement.blur(); }); const out = []; "
            f"for (let i = 0; i < {MAX_TABS}; i++) {{ await page.keyboard.press('Tab'); "
            f"const f = await page.evaluate({FOCUS_FN}); if (!f) break; "
            "if (out.length && f.sel === out[0].sel) break; out.push(f); } return out; }",
        )
    facts = facts if isinstance(facts, dict) else {"error": str(facts)[:500]}
    facts["axe"] = axe or []
    facts["tab_stops"] = stops or []
    facts["no_focus_ring"] = [t for t in (stops or []) if not t.get("ring")]
    facts["tiles"] = tiles
    if checks is not None:
        facts["page_checks"] = await page_checks(s, vp, view, checks)
    (out / "facts" / f"{name}-{view}.json").write_text(json.dumps(facts, indent=1))
    return {
        "viewport": view,
        "size": [w, h],
        "tiles": [t["file"] for t in tiles],
        "facts": f"facts/{name}-{view}.json",
        "axe_violations": len(facts["axe"]),
        "measured": {
            k: len(facts.get(k) or [])
            for k in (
                "contrast_failures",
                "small_targets",
                "weak_boundaries",
                "unnamed_graphics",
                "long_lines",
                "no_focus_ring",
            )
        }
        | {"overflows": bool((facts.get("page_width") or {}).get("overflows"))}
        | (
            {"page_checks": len(pc.judge(view, facts["page_checks"], checks["thresholds"],
                                         facts["page_checks"].get("pixels"))[0])}
            if checks is not None
            else {}
        ),
    }


async def page_checks(s: ClientSession, vp: str, view: str, checks: dict) -> dict:
    """design_page_checks.js in the page, then contrast from pixels for text over pictures."""
    t = checks["thresholds"]
    desktop = vp == "desktop" and view == vp
    src = pc.source(t, checks.get("primary", "") if vp == "mobile" else "", copy=desktop, columns=desktop,
                    visuals=view == vp)
    raw = await run(s, "async (page) => await page.evaluate(" + json.dumps(src) + ")")
    raw = raw if isinstance(raw, dict) else {"error": str(raw)[:500]}
    if raw.get("overlays"):
        try:
            raw["pixels"] = await run(s, pc.pixel_code(raw["overlays"], t))
        except Exception as exc:  # noqa: BLE001 - recorded; the rest of the page checks stand
            raw["pixels_error"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
    return raw


def _items(f: dict) -> list[tuple[str, str]]:
    """(kind, line) for each measured problem in one view's facts."""
    out = []
    for v in f.get("axe") or []:
        targets = "; ".join(n["target"] for n in v["nodes"][:6])
        out.append(
            (
                "axe",
                f"axe `{v['id']}` ({v['impact']}, {', '.join(v['wcag'])}): {v['help']}. Elements: {targets}",
            )
        )
    for t in f.get("contrast_failures") or []:
        out.append(
            (
                "contrast",
                f'text contrast {t["contrast"]}:1 (needs {t["needs"]}): `{t["sel"]}` "{t["text"]}" '
                f"{t['size']}px/{t['weight']} {t['color']} on {t['background']}",
            )
        )
    for t in f.get("small_targets") or []:
        out.append(("target", _target_line(t)))
    for t in f.get("weak_boundaries") or []:
        out.append(
            (
                "boundary",
                f'control boundary contrast {t["boundary_contrast"]}:1 (needs 3): `{t["sel"]}` "{t["name"]}"',
            )
        )
    for t in f.get("unnamed_graphics") or []:
        out.append(
            (
                "graphic",
                f"graphic without a text alternative: `{t['sel']}` {t['tag']} {t['src']}".rstrip(),
            )
        )
    for t in f.get("long_lines") or []:
        out.append(
            (
                "lines",
                f"long lines, ~{t['chars_per_line']} characters per line over {t['lines']} lines: "
                f'`{t["sel"]}` "{t["text"][:60]}"',
            )
        )
    for t in f.get("no_focus_ring") or []:
        out.append(
            (
                "focus",
                f'no visible focus indicator on Tab: `{t["sel"]}` "{t["name"]}" '
                f"(outline {t['outline']}, box-shadow {t['box_shadow']})",
            )
        )
    pw = f.get("page_width") or {}
    if pw.get("overflows"):
        els = "; ".join(
            f"`{o['sel']}` right edge {o['box'][0] + o['box'][2]} px"
            for o in f.get("overflowing") or []
        )
        out.append(
            (
                "reflow",
                f"page scrolls sideways: {pw['scroll']} px wide in a {pw['viewport']} px viewport. Elements: {els}",
            )
        )
    for t in f.get("fields") or []:
        if t["name_from"] in ("none", "placeholder only", "title"):
            out.append(
                (
                    "field",
                    f'form field named by {t["name_from"]}: `{t["sel"]}` ({t["type"]}) "{t["name"]}"',
                )
            )
    return out


def _target_line(t: dict) -> str:
    """A target that fails WCAG 2.5.8: under 24x24 px, and too close to another target."""
    line = (
        f"target smaller than 24x24 px without the 24 px spacing (WCAG 2.5.8): `{t['sel']}` "
        f'"{t["name"]}" {t["box"][2]}x{t["box"][3]} px'
    )
    n = t.get("too_close_to")
    if n:
        how = (
            f'its 24 px circle and the circle of `{n["sel"]}` "{n["name"]}" overlap '
            f"(centres {n['centre']} px apart, need 24)"
            if t.get("hit") == "circle"
            else f'`{n["sel"]}` "{n["name"]}" is {n["edge"]} px from its centre (needs 12)'
        )
        line += "; " + how
    return line


def _passes(f: dict) -> list[tuple[str, str]]:
    """(kind, line) for each measured PASS that a reviewer might otherwise report as a failure."""
    out = []
    for t in f.get("targets_pass") or []:
        size = f"{t['box'][2]}x{t['box'][3]} px"
        if t.get("passes") == "label":
            lb = t.get("label_box") or [0, 0, 0, 0]
            out.append(
                (
                    "target-pass",
                    f"meets WCAG 2.5.8 through its label (clicking the label works the control): `{t['sel']}` "
                    f'"{t["name"]}" control {size}, label {lb[2]}x{lb[3]} px',
                )
            )
        else:
            n = t.get("nearest")
            near = (
                f'; nearest other target `{n["sel"]}` "{n["name"]}" {n["edge"]} px from its centre'
                if n
                else "; no other target nearby"
            )
            out.append(
                (
                    "target-pass",
                    f"under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches "
                    f'no other target): `{t["sel"]}` "{t["name"]}" {size}{near}',
                )
            )
    for t in f.get("contrast_exempt") or []:
        out.append(
            (
                "contrast-exempt",
                f"text of an inactive (disabled) control, no contrast requirement (WCAG 1.4.3, 1.4.11): "
                f'`{t["sel"]}` "{t["text"]}" {t["contrast"]}:1',
            )
        )
    return out


def write_summary(out: pathlib.Path, index: dict) -> None:
    """facts.md: one section per page, measured problems merged over viewports."""
    lines = [
        "# Measured facts (design_capture)",
        "",
        "Measured by axe-core "
        + index["axe"]
        + " and design_measure.js in a real browser, per viewport "
        + ", ".join(f"{k} {w}x{h}" for k, (w, h) in index["viewports"].items())
        + ". A measured problem is a fact; so is a measured pass (never report a listed pass as a"
        " failure). Whether a problem matters, and everything about hierarchy, wording, flow and"
        " consistency, is the reviewer's to judge from the screenshots. The full numbers per view are"
        " in facts/<page>-<viewport>.json.",
        "",
    ]
    for p in index["pages"]:
        views = {
            v["viewport"]: json.loads((out / v["facts"]).read_text())
            for v in p["views"]
        }
        lines += [f"## {p['page']}", ""]
        first = next(iter(views.values()))
        lines.append(f"Title: {first.get('title', '')}")
        for vp, f in views.items():
            tiles = ", ".join(t["file"] for t in f.get("tiles", []))
            lines.append(f"Screenshots {vp} (top to bottom, one screen each): {tiles}")
        lines.append("")
        merged: dict[tuple[str, str], list[str]] = {}
        passed: dict[tuple[str, str], list[str]] = {}
        for vp, f in views.items():
            for item in _items(f):
                merged.setdefault(item, []).append(vp)
        checked = {vp: f["page_checks"] for vp, f in views.items() if isinstance(f.get("page_checks"), dict)}
        if checked:
            t = pc.thresholds()
            for vp, raw in checked.items():
                probs, oks = pc.judge(vp, raw, t, raw.get("pixels"))
                for item in probs:
                    merged.setdefault(item, []).append(vp)
                for item in oks:
                    passed.setdefault(item, []).append(vp)
            if "desktop" in checked:
                probs, oks = pc.copy_problems(checked["desktop"], t)
                for item in probs:
                    merged.setdefault(item, []).append("desktop")
                for item in oks:
                    passed.setdefault(item, []).append("desktop")
        lines.append("### Measured problems")
        if merged:
            for (_kind, text), vps in merged.items():
                lines.append(f"- [{'+'.join(vps)}] {text}")
        else:
            lines.append("- none measured")
        for vp, f in views.items():
            for item in _passes(f):
                passed.setdefault(item, []).append(vp)
        if passed:
            lines += ["", "### Measured passes (checked and fine: not failures)"]
            for (_kind, text), vps in passed.items():
                lines.append(f"- [{'+'.join(vps)}] {text}")
        first_block: list[str] = []
        for i, (vp, f) in enumerate(views.items()):
            block: list[str] = []
            block.append(
                "Type styles (size weight: count): "
                + ", ".join(
                    f"{s['style']}: {s['count']}" for s in f.get("type_styles", [])
                )
            )
            block.append(
                "Largest text: "
                + "; ".join(
                    f"{t['tag']} {t['size']}px/{t['weight']}{' uppercase' if t['transform'] == 'uppercase' else ''} "
                    f'{t["color"]} "{t["text"][:50]}"'
                    for t in f.get("largest_text", [])[:5]
                )
            )
            block.append(
                "Headings: "
                + "; ".join(
                    f'h{h["level"]} {h["size"]}px/{h["weight"]} "{h["text"][:50]}"'
                    for h in f.get("headings", [])
                )
            )
            stops = f.get("tab_stops") or []
            block.append(
                f"Tab order ({len(stops)} stops): "
                + " > ".join((s["name"] or s["sel"])[:30] for s in stops[:40])
            )
            fields = f.get("fields") or []
            if fields:
                block.append(
                    "Form fields (accessible name, where it comes from): "
                    + "; ".join(
                        f'"{x["name"]}" ({x["name_from"]}{", aria-invalid=" + x["aria_invalid"] if x["aria_invalid"] else ""})'
                        for x in fields
                    )
                )
            block.append(
                "Landmarks: " + ", ".join(lm["tag"] for lm in f.get("landmarks", []))
            )
            if i == 0:
                first_block = block
                lines += ["", f"### Text and structure ({vp})"] + block
            else:
                diff = [b for b in block if b not in first_block]
                lines += [
                    "",
                    f"### Text and structure ({vp}): "
                    + ("where it differs" if diff else "same as above"),
                ] + diff
        if checked:
            offered = bool((checked.get("desktop") or {}).get("dark"))
            lines += ["", "### Page checks: facts that are not pass or fail"]
            lines += pc.info_lines(checked, "desktop-dark" in checked, offered)
        lines.append("")
    (out / "facts.md").write_text("\n".join(lines))


async def main(args) -> dict:
    out = pathlib.Path(args.out).resolve()
    (out / "shots").mkdir(parents=True, exist_ok=True)
    (out / "facts").mkdir(parents=True, exist_ok=True)
    browser = urllib.parse.urlparse(args.browser)
    base = args.base_url.rstrip("/") if args.base_url else None
    srv = None
    if not base:
        base, srv = serve(pathlib.Path(args.site).resolve(), browser.hostname)
    axe_src, measure_src = AXE.read_text(), MEASURE.read_text()
    pages = [p.strip() for p in args.pages.split(",") if p.strip()]
    vps = [v.strip() for v in args.viewports.split(",") if v.strip()]
    index = {
        "base_url": base if args.base_url else "(local site)",
        "viewports": {v: VIEWPORTS[v] for v in vps},
        "axe": "4.13.0",
        "axe_tags": AXE_TAGS,
        "pages": [],
    }
    checks = None
    brief = out / "brief.md"
    brief_text = brief.read_text(encoding="utf-8") if brief.exists() else ""
    if getattr(args, "page_checks", False):
        primary = getattr(args, "primary_action", "") or pc.primary_action(brief_text)
        checks = {"thresholds": pc.thresholds(), "primary": primary}
        index["page_checks"] = {"primary_action": primary, "thresholds": pc.THRESHOLDS.name}
    # The design context: --context, else (page checks on) the brief's "Design context:" line.
    context = getattr(args, "context", "") or (pc.design_context(brief_text) if checks is not None else "")
    if context:
        (out / "context.md").write_text(pc.context_md(context), encoding="utf-8")
        index["context"] = context
    try:
        async with streamablehttp_client(args.browser) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                for p in pages:
                    url = base + "/" + p.lstrip("/")
                    entry = {"page": p, "name": slug(p), "views": []}
                    for vp in vps:
                        entry["views"].append(
                            await capture_one(
                                s, url, slug(p), vp, out, axe_src, measure_src, checks
                            )
                        )
                    if checks is not None and "desktop" in vps:
                        desk = json.loads((out / f"facts/{slug(p)}-desktop.json").read_text())
                        if (desk.get("page_checks") or {}).get("dark"):
                            entry["views"].append(
                                await capture_one(
                                    s, url, slug(p), "desktop", out, axe_src, measure_src, checks, "dark"
                                )
                            )
                    index["pages"].append(entry)
                await s.call_tool("browser_close", {})
    finally:
        if srv:
            srv.shutdown()
    (out / "capture.json").write_text(json.dumps(index, indent=1))
    write_summary(out, index)
    return index


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--pages", required=True, help="comma-separated paths, relative to the site"
    )
    ap.add_argument("--site", help="a local folder to serve")
    ap.add_argument("--base-url", help="a deployed site instead of --site")
    ap.add_argument("--viewports", default="desktop,mobile")
    ap.add_argument("--browser", default="http://playwright-mcp:8931/mcp")
    ap.add_argument("--page-checks", action="store_true", help="add the model-free page checks (queue #39)")
    ap.add_argument("--primary-action", default="", help="the page's primary action label (else brief.md)")
    ap.add_argument("--context", default="", help="a design context id from the playbook: writes context.md")
    a = ap.parse_args()
    if not (a.site or a.base_url):
        ap.error("give --site or --base-url")
    idx = asyncio.run(main(a))
    print(
        json.dumps(
            {
                "ok": True,
                "out": a.out,
                "pages": [
                    {
                        "page": p["page"],
                        "views": [
                            {
                                k: v[k]
                                for k in ("viewport", "axe_violations", "measured")
                            }
                            | {"tiles": len(v["tiles"])}
                            for v in p["views"]
                        ],
                    }
                    for p in idx["pages"]
                ],
            }
        )
    )
    sys.exit(0)
