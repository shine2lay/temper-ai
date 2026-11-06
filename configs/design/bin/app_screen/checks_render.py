"""Opens every view of a build in a real browser and brings back what the checks measure.

Runs inside the Temper worker: it serves 05-build/ over HTTP on the worker's own address and drives
temper's playwright-mcp service, the same way configs/design/bin/design_capture.py does for the homepage
workflow. Its helpers are imported, never copied: serve (the local site), run/result (a playwright-mcp
call), FOCUS_FN and MAX_TABS (the Tab walk), AXE/AXE_TAGS (axe-core 4.13.0) and MEASURE
(design_measure.js). app_screen/measure_in_page.js adds truncation and the type histogram,
app_screen/checks_measure.js the contract marks, figures, used colours and hierarchy counts.

Look-only but for two things the contract asks to be proved: it clicks a `data-action` control to see
whether it answers the click, and it presses Tab to see the focus ring. Both reopen the view afterwards.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
DESIGN_BIN = HERE.parent
MEASURE_IN_PAGE = HERE / "measure_in_page.js"
CHECKS_MEASURE = HERE / "checks_measure.js"
BROWSER = "http://playwright-mcp:8931/mcp"
SETTLE_MS = 350


class RenderError(RuntimeError):
    """The browser could not be driven at all; one view failing is a measured fact, not this."""


def _design_capture():
    if str(DESIGN_BIN) not in sys.path:
        sys.path.insert(0, str(DESIGN_BIN))
    import design_capture  # noqa: PLC0415 - optional, worker-side only

    return design_capture


def _open_code(url: str, view: dict, settle: int) -> str:
    """One playwright-mcp call: listen, size, open, follow the view's steps, screenshot."""
    steps = []
    opening = view["open"]
    if "hash" in opening:
        steps.append(f"await page.goto({json.dumps(url + opening['hash'])}, {{waitUntil: 'load'}});")
    else:
        steps.append(f"await page.goto({json.dumps(url)}, {{waitUntil: 'load'}});")
        for step in opening.get("steps") or []:
            if "goto" in step:
                target = step["goto"]
                full = target if target.startswith("#") else target
                steps.append(f"await page.goto({json.dumps(url + full if full.startswith('#') else full)}, "
                             "{waitUntil: 'load'});")
            elif "click" in step:
                steps.append(f"await page.click({json.dumps(step['click'])}, {{timeout: 8000}});")
            elif "wait" in step:
                steps.append(f"await page.waitForTimeout({int(step['wait'])});")
    body = "\n    ".join(steps)
    return f"""async (page) => {{
    const errors = [], failed = [];
    const onConsole = (m) => {{ if (m.type() === 'error') errors.push(m.text().slice(0, 200)); }};
    const onError = (e) => errors.push('pageerror: ' + String(e.message).slice(0, 200));
    const onFailed = (r) => failed.push(r.url().split('/').slice(-2).join('/').slice(0, 120) + ' ' + ((r.failure() || {{}}).errorText || 'failed'));
    const onResponse = (r) => {{ if (r.status() >= 400) failed.push(r.url().split('/').slice(-2).join('/').slice(0, 120) + ' HTTP ' + r.status()); }};
    page.on('console', onConsole); page.on('pageerror', onError);
    page.on('requestfailed', onFailed); page.on('response', onResponse);
    // The browser asks for a favicon on its own, so the harness answers it: a prototype is judged for the
    // files it asks for, not for one the browser asks for behind its back.
    if (!page.__faviconAnswered) {{
      await page.route('**/favicon.ico', (route) => route.fulfill({{status: 200, contentType: 'image/png', body: ''}}));
      page.__faviconAnswered = true;
    }}
    let opened = true, why = '';
    try {{
      await page.setViewportSize({{width: {int(view['width'])}, height: {int(view['height'])}}});
      {body}
      await page.evaluate(() => document.fonts.ready.then(() => true));
      await page.waitForTimeout({int(settle)});
      await page.evaluate(() => window.scrollTo(0, 0));
    }} catch (e) {{ opened = false; why = String(e.message).slice(0, 240); }}
    const shot = opened ? (await page.screenshot({{type: 'png'}})).toString('base64') : '';
    page.off('console', onConsole); page.off('pageerror', onError);
    page.off('requestfailed', onFailed); page.off('response', onResponse);
    return {{opened, why, errors: [...new Set(errors)].slice(0, 12), failed: [...new Set(failed)].slice(0, 12), shot}};
  }}"""


async def _measure(dc, s, design_measure: str, in_page_cfg: str, checks_cfg: str) -> dict:
    """design_measure.js, measure_in_page.js and checks_measure.js, in one call."""
    code = ("async (page) => ({"
            f"dm: await page.evaluate({json.dumps(design_measure)}), "
            f"mp: await page.evaluate({json.dumps(in_page_cfg)}), "
            f"cm: await page.evaluate({json.dumps(checks_cfg)})"
            "})")
    return await dc.run(s, code) or {}


async def _axe(dc, s, axe_src: str, tags: list[str]) -> list:
    code = ("async (page) => { await page.evaluate(" + json.dumps(axe_src) + "); "
            "return await page.evaluate(async () => { const r = await axe.run(document, "
            "{runOnly: {type: 'tag', values: " + json.dumps(tags) + "}, resultTypes: ['violations']}); "
            "return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help, "
            "wcag: v.tags.filter(t => /^wcag\\d/.test(t)), nodes: v.nodes.slice(0, 6).map(n => "
            "({target: n.target.join(' '), summary: (n.failureSummary || '').slice(0, 200)}))})); }); }")
    return await dc.run(s, code) or []


async def _tab_walk(dc, s, max_tabs: int, focus_fn: str) -> list:
    code = ("async (page) => { await page.evaluate(() => { window.scrollTo(0, 0); "
            "if (document.activeElement) document.activeElement.blur(); }); const out = []; "
            f"for (let i = 0; i < {max_tabs}; i++) {{ await page.keyboard.press('Tab'); "
            f"const f = await page.evaluate({focus_fn}); if (!f) break; "
            "if (out.length && f.sel === out[0].sel) break; out.push(f); } return out; }")
    return await dc.run(s, code) or []


# The element's own answer to the click (pressed, busy, disabled, colour, shadow, moved).
SIGN_FN = """(el) => {
  const cs = getComputedStyle(el);
  return {cls: el.className + '|' + (el.getAttribute('aria-pressed') || '') + (el.getAttribute('aria-busy') || '')
               + (el.getAttribute('aria-expanded') || '') + (el.disabled ? 'disabled' : ''),
          style: [cs.backgroundColor, cs.color, cs.opacity, cs.transform, cs.boxShadow].join('|'),
          on: el.getAttribute('aria-pressed') === 'true' || el.getAttribute('aria-current') !== null
              || /(^|[\\s-])(active|selected|current|on)($|[\\s-])/.test(el.className)};
}"""

# The page's answer to the click (new text, a new route, a dialog).
PAGE_SIGN_FN = """() => {
  const t = document.body.innerText.replace(/\\s+/g, ' ');
  return {text: t.length,
          hash: [...t].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7),
          scroll: Math.round(window.scrollY),
          url: location.hash + location.search};
}"""


async def _click_feedback(dc, s, url: str, view: dict, actions: list[dict], settle: int) -> list[dict]:
    """Click each action control and see whether anything visible answered before any server reply.

    The control is found again by its data-action mark, not by a CSS path: a page that re-renders between
    the measure and the click moves the path, and a control the step cannot find is not a fault of the
    prototype.
    """
    out = []
    reopen = _open_code(url, view, settle)
    for a in actions:
        code = ("async (page) => { const sel = " + json.dumps(f'[data-action="{a["action"]}"]') + "; "
                f"const idx = {int(a.get('idx') or 0)}; "
                "const all = page.locator(sel); const n = await all.count(); "
                "if (n <= idx) return {found: false, why: `the page has ${n} element(s) with this "
                "data-action`}; "
                "const loc = all.nth(idx); const sign = " + SIGN_FN + "; "
                "const pageSign = " + PAGE_SIGN_FN + "; "
                "let before = null, beforePage = null; "
                "try { before = await loc.evaluate(sign); beforePage = await page.evaluate(pageSign); } "
                "catch (e) { return {found: false, why: String(e.message).slice(0, 160)}; } "
                "let clicked = true, why = ''; "
                "try { await loc.click({timeout: 4000, noWaitAfter: true}); } "
                "catch (e) { clicked = false; why = String(e.message).slice(0, 160); } "
                "await page.waitForTimeout(220); "
                "let after = null; try { after = await loc.evaluate(sign); } catch (e) { after = null; } "
                "const afterPage = await page.evaluate(pageSign); "
                "return {found: true, clicked, why, before: {...before, ...beforePage}, "
                "after: {...(after || {}), ...afterPage}}; }")
        try:
            res = await dc.run(s, code) or {}
        except Exception as exc:                               # noqa: BLE001 - one control, not the run
            res = {"found": True, "clicked": False, "why": str(exc)[:160]}
        before, after = res.get("before") or {}, res.get("after") or {}
        # Scrolling to the thing the control points at is a visible answer too (H6a-7).
        changed = bool(after) and any(before.get(k) != after.get(k)
                                      for k in ("hash", "cls", "style", "url", "text", "scroll"))
        out.append({"action": a["action"], "sel": a["sel"], "label": a.get("label", ""),
                    "found": bool(res.get("found")), "clicked": bool(res.get("clicked")),
                    "feedback": changed, "already_on": bool(before.get("on")), "why": res.get("why", "")})
        await dc.run(s, reopen)
    return out


async def _render_async(site: pathlib.Path, plan: dict, out_dir: pathlib.Path, thresholds: dict,
                        browser_url: str) -> dict:
    dc = _design_capture()
    from mcp import ClientSession  # noqa: PLC0415 - worker-side only
    from mcp.client.streamable_http import streamablehttp_client  # noqa: PLC0415

    browser = urllib.parse.urlparse(browser_url)
    # The site is served on the address the browser can reach. In the worker that is the browser's own
    # host name; a host-side trial sets CHECKS_SITE_HOST to the browser container's address instead.
    base, srv = dc.serve(site, os.environ.get("CHECKS_SITE_HOST") or browser.hostname)
    url = base + "/" + plan["page"].lstrip("/")
    axe_src = dc.AXE.read_text()
    design_measure = dc.MEASURE.read_text()
    cfg = {"limit": thresholds["limits"]["rows_per_check_per_view"],
           "label_lines": thresholds["overflow"]["label_lines"],
           "label_max_words": thresholds["overflow"]["label_max_words"],
           "contrast_levels": thresholds["hierarchy"]["contrast_levels"],
           "min_bare_count": thresholds["figures"]["min_bare_count"],
           "max_figures": thresholds["figures"]["max_rows"] * 20}
    in_page_cfg = {"main": plan.get("main") or "body", "areas": plan.get("areas") or {},
                   "key_regions": {}, "loading_text": None, "error_selector": None}
    in_page_call = f"({MEASURE_IN_PAGE.read_text()})({json.dumps(in_page_cfg)})"
    checks_call = f"({CHECKS_MEASURE.read_text()})({json.dumps(cfg)})"
    shots = out_dir / "views"
    shots.mkdir(parents=True, exist_ok=True)
    measured: dict[str, dict] = {}
    try:
        async with streamablehttp_client(browser_url) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                for view in plan["views"]:
                    opened = await dc.run(s, _open_code(url, view, SETTLE_MS)) or {}
                    record = {"view": view["id"], "screen": view["screen"], "state": view["state"],
                              "width": view["width"], "opened": bool(opened.get("opened")),
                              "why": opened.get("why", ""), "console": opened.get("errors") or [],
                              "failed_requests": opened.get("failed") or []}
                    if opened.get("shot"):
                        (shots / f"{view['id']}.png").write_bytes(base64.b64decode(opened["shot"]))
                        record["capture"] = f"views/{view['id']}.png"
                    if record["opened"]:
                        facts = await _measure(dc, s, design_measure, in_page_call, checks_call)
                        record["dm"] = facts.get("dm") or {}
                        record["mp"] = _trim_in_page(facts.get("mp") or {})
                        record["cm"] = facts.get("cm") or {}
                        record["axe"] = await _axe(dc, s, axe_src, thresholds["axe"]["tags"])
                        if view.get("walk"):
                            stops = await _tab_walk(dc, s, thresholds["limits"]["tab_stops"], dc.FOCUS_FN)
                            record["tab_stops"] = stops
                            actions = [a for a in (record["cm"].get("actions") or []) if a.get("visible")]
                            seen, unique = set(), []
                            for a in actions:
                                if a["action"] in seen:
                                    continue
                                seen.add(a["action"])
                                unique.append(a)
                            cap = thresholds["limits"]["actions_per_screen"]
                            if unique:
                                record["action_feedback"] = await _click_feedback(
                                    dc, s, url, view, unique[:cap], SETTLE_MS)
                    measured[view["id"]] = record
                await s.call_tool("browser_close", {})
    finally:
        srv.shutdown()
    return measured


def _trim_in_page(mp: dict) -> dict:
    """measure_in_page.js without the parts the checks do not read (its 800 text runs)."""
    keep = ("viewport", "pageHeight", "horizontalScroll", "type", "targets", "overflow", "truncated",
            "fontsLoaded", "errors")
    out = {k: mp[k] for k in keep if k in mp}
    out["runs"] = [{"text": r.get("text", "")[:120], "size": r.get("size"), "first": r.get("first")}
                   for r in (mp.get("runs") or [])[:400]]
    return out


def render(site: pathlib.Path, plan: dict, out_dir: pathlib.Path, thresholds: dict,
           browser_url: str | None = None) -> dict:
    """Open every view and return {view id: measures}. Raises RenderError if the browser is unreachable.

    In the worker the browser is the run's playwright-mcp service; a host-side trial points CHECKS_BROWSER
    at the same service's published address and CHECKS_SITE_HOST at the address it can reach the host on.
    """
    import asyncio  # noqa: PLC0415 - only the real render needs it

    browser_url = browser_url or os.environ.get("CHECKS_BROWSER") or BROWSER

    try:
        return asyncio.run(_render_async(pathlib.Path(site), plan, pathlib.Path(out_dir), thresholds,
                                         browser_url))
    except RenderError:
        raise
    except Exception as exc:                                   # noqa: BLE001 - fail loud with the reason
        raise RenderError(f"the checks step could not drive {browser_url}: {exc.__class__.__name__}: {exc}") from exc
