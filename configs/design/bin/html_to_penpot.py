#!/usr/bin/env python3
"""Turn a rendered web page into an editable Penpot file (Design role).

The page is opened in temper's browser (playwright-mcp) at each width. An
in-page extractor (html_dom_extract.js) reads the laid-out DOM into a "scene":
boards, groups, rects, text with the browser's own line boxes, and inline SVG
as absolute paths. This module turns those scenes into Penpot 2.18 changes:
one board per width, sections as named boards, real text layers, shared
colours (from CSS custom properties) and typographies, Penpot components for
elements marked data-component, fonts uploaded to the team with their licence
recorded, and images as Penpot media. It then reopens the file, exports PNG and
SVG from Penpot and compares each export with the browser's own screenshot.

Anything the converter cannot carry faithfully is listed in the report's
issues; nothing is silently dropped. Standard library + mcp only (run
containers have no PIL/numpy); pixel comparison runs in the browser's canvas.
Never logs credentials: Penpot login goes through design_homepage_v1.Penpot.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import functools
import hashlib
import http.server
import json
import mimetypes
import re
import socket
import socketserver
import struct
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import penpot_homepage_source as p

HERE = Path(__file__).resolve().parent
EXTRACTOR = HERE / "html_dom_extract.js"
WIDTHS = (390, 768, 1440)
VIEWPORT_HEIGHT = {390: 844, 768: 1024, 1440: 900}
BOARD_GAP = 200
LIBRARY_GAP = 400
CHUNK = 250
# Fidelity bar, fixed before any proof run (never loosened to make a run pass).
# A pixel differs when its largest RGB channel difference exceeds THRESHOLD after
# allowing a SHIFT-pixel offset either way (sub-pixel placement, anti-aliasing).
# Tile bars (added after harbor try 2 passed the page-wide bars while one card had lost
# its fill and text; a tightening): no TILE x TILE square may have more than tile_max_pct
# differing pixels or a mean difference above tile_mean_max levels.
FIDELITY = {"threshold": 48, "shift": 1, "overall_pct": 2.0, "nontext_pct": 1.0, "text_pct": 12.0,
            "tile": 32, "tile_max_pct": 20.0, "tile_mean_max": 40.0}
FALLBACK_FONT = "sourcesanspro"
FONT_MAGIC = {b"\x00\x01\x00\x00": ("font/ttf", "ttf"), b"true": ("font/ttf", "ttf"),
              b"OTTO": ("font/otf", "otf"), b"wOFF": ("font/woff", "woff")}
LICENCE_NAMES = ("OFL.txt", "OFL", "LICENSE.txt", "LICENSE", "LICENCE.txt", "LICENCE", "UFL.txt")
SYNC_GROUPS = ("geometry-group", "content-group", "fill-group", "stroke-group", "radius-group",
               "shadow-group", "layer-effects-group", "name-group")


def now() -> str:
    return datetime.now(UTC).isoformat()


def fmt(value: float) -> str:
    text = f"{round(float(value), 4):g}"
    return "0" if text == "-0" else text


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Local HTTP origin for the browser: serves the site, accepts uploads of the
# capture's screenshots and scenes, and serves the output folder for the
# in-browser pixel comparison.
# --------------------------------------------------------------------------

PUT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,80}\.(png|json)")
MAX_UPLOAD = 256 * 1024 * 1024


class _Handler(http.server.SimpleHTTPRequestHandler):
    out_dir: Path = Path(".")

    def log_message(self, *args: Any) -> None:  # silence the access log
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _name(self, prefix: str) -> str | None:
        name = urllib.parse.unquote(self.path.split("?", 1)[0][len(prefix):])
        return name if PUT_NAME.fullmatch(name) else None

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path.startswith("/__blank"):
            body = b"<!doctype html><meta charset=utf-8><title>compare</title><body></body>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/__out/"):
            name = self._name("/__out/")
            target = self.out_dir / name if name else None
            if not target or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_PUT(self) -> None:  # noqa: N802 - http.server API
        name = self._name("/__put/") if self.path.startswith("/__put/") else None
        length = int(self.headers.get("Content-Length") or 0)
        if not name or not 0 < length <= MAX_UPLOAD:
            self.send_error(403)
            return
        data = self.rfile.read(length)
        (self.out_dir / name).write_bytes(data)
        self.send_response(204)
        self.end_headers()


def serve(site: Path, out_dir: Path, browser_host: str) -> tuple[str, socketserver.BaseServer]:
    """Serve site + upload/output routes on the address the browser host can reach."""
    handler_cls = type("Handler", (_Handler,), {"out_dir": out_dir})
    handler = functools.partial(handler_cls, directory=str(site))
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


def mcp_result(res: Any) -> Any:
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


async def _browser(url: str, codes: list[str], timeout: float | None = None) -> list[Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    results = []
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            try:
                for code in codes:
                    call = s.call_tool("browser_run_code_unsafe", {"code": code})
                    results.append(mcp_result(await asyncio.wait_for(call, timeout)))
            finally:
                try:
                    await asyncio.wait_for(s.call_tool("browser_close", {}), 20)
                except Exception:  # noqa: BLE001 - closing is best effort
                    pass
    return results


def browser_run(url: str, codes: list[str], timeout: float | None = None) -> list[Any]:
    """Run playwright-mcp code snippets in one browser session; timeout is per snippet (None = no limit)."""
    return asyncio.run(_browser(url, codes, timeout))


FREEZE_CSS = ("*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;"
              "transition:none!important;caret-color:transparent!important;scroll-behavior:auto!important}"
              "html{scrollbar-width:none!important}::-webkit-scrollbar{display:none!important}")


def capture_code(base: str, page: str, widths: tuple[int, ...]) -> str:
    """playwright-mcp code: render each width, extract its scene, upload scene + screenshot."""
    src = EXTRACTOR.read_text()
    args = {"base": base, "page": page, "widths": list(widths), "heights": VIEWPORT_HEIGHT,
            "css": FREEZE_CSS, "src": src}
    return """async (page) => {
  const A = __ARGS__;
  const out = [];
  for (const w of A.widths) {
    await page.setViewportSize({width: w, height: A.heights[String(w)] || 900});
    await page.emulateMedia({reducedMotion: 'reduce', colorScheme: 'light'});
    await page.goto(A.base + '/' + A.page, {waitUntil: 'networkidle'});
    await page.addStyleTag({content: A.css});
    const total = await page.evaluate(() => document.documentElement.scrollHeight);
    const step = Math.round((A.heights[String(w)] || 900) * 0.8);
    for (let y = 0; y < total; y += step) {
      await page.evaluate((v) => window.scrollTo(0, v), y);
      await page.waitForTimeout(40);
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.evaluate(async () => {
      // Bounded: an image that never loads must not hang the conversion (the fidelity check shows the gap).
      const within = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(r, ms))]);
      await within(document.fonts.ready, 10000);
      await within(Promise.all([...document.images].map((i) => i.complete ? null : new Promise((r) => { i.onload = r; i.onerror = r; }))), 10000);
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    });
    await page.waitForTimeout(150);
    const scene = await page.evaluate('(' + A.src + ')({})');
    const shot = await page.screenshot({fullPage: true, animations: 'disabled', caret: 'hide', scale: 'css'});
    let r = await page.request.put(A.base + '/__put/browser-' + w + '.png', {data: shot, headers: {'content-type': 'application/octet-stream'}});
    if (!r.ok()) throw new Error('upload screenshot failed ' + r.status());
    r = await page.request.put(A.base + '/__put/scene-' + w + '.json', {data: JSON.stringify(scene), headers: {'content-type': 'application/octet-stream'}});
    if (!r.ok()) throw new Error('upload scene failed ' + r.status());
    out.push({width: w, height: scene.height, viewport: scene.viewport, issues: scene.issues.length, stats: scene.stats});
  }
  return out;
}""".replace("__ARGS__", json.dumps(args))


COMPARE_FN = r"""async (args) => {
  const load = (u) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('cannot load ' + u)); i.src = u; });
  const [a, b] = await Promise.all([load(args.a), load(args.b)]);
  const W = Math.min(a.naturalWidth, b.naturalWidth), H = Math.min(a.naturalHeight, b.naturalHeight);
  const pixels = (img) => { const c = document.createElement('canvas'); c.width = W; c.height = H;
    const g = c.getContext('2d', {willReadFrequently: true}); g.fillStyle = '#fff'; g.fillRect(0, 0, W, H); g.drawImage(img, 0, 0); return g.getImageData(0, 0, W, H).data; };
  const A = pixels(a), B = pixels(b);
  const mask = new Uint8Array(W * H);
  for (const r of args.text) {
    const x0 = Math.max(0, Math.floor(r[0] - 2)), y0 = Math.max(0, Math.floor(r[1] - 2));
    const x1 = Math.min(W, Math.ceil(r[0] + r[2] + 2)), y1 = Math.min(H, Math.ceil(r[1] + r[3] + 2));
    for (let y = y0; y < y1; y++) mask.fill(1, y * W + x0, y * W + x1);
  }
  const T = args.threshold, S = args.shift;
  const diff = (P, i, Q, j) => Math.max(Math.abs(P[i] - Q[j]), Math.abs(P[i + 1] - Q[j + 1]), Math.abs(P[i + 2] - Q[j + 2]));
  const near = (P, Q, x, y, i) => {
    let d = 255;
    for (let oy = -S; oy <= S; oy++) for (let ox = -S; ox <= S; ox++) {
      const xx = x + ox, yy = y + oy; if (xx < 0 || yy < 0 || xx >= W || yy >= H) continue;
      d = Math.min(d, diff(P, i, Q, (yy * W + xx) * 4)); if (d <= T) return d;
    }
    return d;
  };
  const lowest = (x, y, i) => {
    let d = 255;
    for (let oy = -S; oy <= S; oy++) for (let ox = -S; ox <= S; ox++) {
      const xx = x + ox, yy = y + oy; if (xx < 0 || yy < 0 || xx >= W || yy >= H) continue;
      d = Math.min(d, diff(A, i, B, (yy * W + xx) * 4)); if (d === 0) return 0;
    }
    return d;
  };
  const canvas = document.createElement('canvas'); canvas.width = W; canvas.height = H;
  const hg = canvas.getContext('2d'); const heat = hg.createImageData(W, H); const hd = heat.data;
  let raw = 0, tol = 0, textPx = 0, textTol = 0, ntTol = 0;
  const bands = new Array(Math.ceil(H / 100)).fill(0);
  // Local checks: a missing card or paragraph is small next to a whole page, so every
  // TILE x TILE square is also judged on its own (share of differing pixels, mean difference).
  const Z = args.tile, TX = Math.ceil(W / Z), TY = Math.ceil(H / Z);
  const tBad = new Float64Array(TX * TY), tSum = new Float64Array(TX * TY), tN = new Float64Array(TX * TY);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = (y * W + x) * 4, k = y * W + x;
    const d0 = diff(A, i, B, i);
    let bad = false;
    if (d0 > T) { raw++; bad = near(A, B, x, y, i) > T || near(B, A, x, y, i) > T; }
    const t = mask[k]; if (t) textPx++;
    if (bad) { tol++; if (t) textTol++; else ntTol++; bands[Math.floor(y / 100)]++; }
    const q = Math.floor(y / Z) * TX + Math.floor(x / Z);
    tN[q]++; tSum[q] += d0 === 0 ? 0 : lowest(x, y, i); if (bad) tBad[q]++;
    const g = (A[i] * 0.3 + A[i + 1] * 0.59 + A[i + 2] * 0.11) * 0.3 + 170;
    hd[i] = bad ? 225 : g; hd[i + 1] = bad ? 20 : g; hd[i + 2] = bad ? (t ? 160 : 20) : g; hd[i + 3] = 255;
  }
  hg.putImageData(heat, 0, 0);
  const blob = await new Promise((r) => canvas.toBlob(r, 'image/png'));
  const up = await fetch(args.put, {method: 'PUT', body: blob});
  const total = W * H, nontext = total - textPx;
  const pct = (n, d) => d ? Math.round(n / d * 100000) / 1000 : 0;
  const tiles = [];
  for (let q = 0; q < TX * TY; q++) if (tN[q] >= Z * Z / 4)
    tiles.push([(q % TX) * Z, Math.floor(q / TX) * Z, pct(tBad[q], tN[q]), Math.round(tSum[q] / tN[q] * 10) / 10]);
  const worst = (j) => tiles.slice().sort((p, q) => q[j] - p[j]).slice(0, 5);
  return {compared: [W, H], browser: [a.naturalWidth, a.naturalHeight], penpot: [b.naturalWidth, b.naturalHeight],
    pixels: total, text_pixels: textPx, raw_pct: pct(raw, total), overall_pct: pct(tol, total),
    text_pct: pct(textTol, textPx), nontext_pct: pct(ntTol, nontext), heatmap_uploaded: up.ok,
    tile_max_pct: tiles.length ? Math.max(...tiles.map((v) => v[2])) : 0,
    tile_mean_max: tiles.length ? Math.max(...tiles.map((v) => v[3])) : 0,
    worst_tiles_pct: worst(2), worst_tiles_mean: worst(3),
    worst_bands: bands.map((n, i) => [i * 100, n]).sort((p, q) => q[1] - p[1]).slice(0, 5).filter((x) => x[1] > 0)};
}"""


def compare_code(base: str, jobs: list[dict]) -> str:
    return """async (page) => {
  const jobs = __JOBS__;
  const fn = __FN__;
  await page.setViewportSize({width: 800, height: 600});
  await page.goto(__BASE__ + '/__blank', {waitUntil: 'load'});
  const out = [];
  for (const j of jobs) out.push(await page.evaluate(fn, j));
  return out;
}""".replace("__BASE__", json.dumps(base)).replace("__JOBS__", json.dumps(jobs)).replace("__FN__", COMPARE_FN)


def text_rects(scene: dict) -> list[list[float]]:
    """Every rendered line fragment of every text node, as [x, y, w, h] page boxes."""
    rects: list[list[float]] = []

    def walk(nodes: list[dict]) -> None:
        for n in nodes:
            if n["kind"] == "text":
                for frag in n["text"]["lines"]:
                    rects.append([frag["x"], frag["y"] - frag["h"], frag["w"], frag["h"]])
            walk(n.get("children", []))

    walk(scene["nodes"])
    return rects


# --------------------------------------------------------------------------
# Local assets the page used (fonts with licences, images)
# --------------------------------------------------------------------------

def local_file(site: Path, base: str, url: str) -> Path | None:
    """Map a URL the page loaded back to a file inside the site folder (never outside)."""
    if not url or not url.startswith(base + "/"):
        return None
    rel = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lstrip("/")
    target = (site / rel).resolve()
    root = site.resolve()
    if root != target and root not in target.parents:
        return None
    return target if target.is_file() else None


def font_kind(data: bytes) -> tuple[str, str]:
    kind = FONT_MAGIC.get(data[:4])
    if not kind:
        raise ValueError("font is not TTF, OTF or WOFF (WOFF2 must be converted to TTF first)")
    return kind


def licence_of(font: Path) -> dict:
    for name in LICENCE_NAMES:
        candidate = font.parent / name
        if candidate.is_file():
            text = candidate.read_text(errors="replace")
            first = next((line.strip() for line in text.splitlines() if line.strip()), "")
            return {"file": candidate.name, "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    "first_line": first[:160], "ofl": "SIL OPEN FONT LICENSE" in text.upper()}
    raise ValueError(f"font {font.name} has no licence file beside it ({', '.join(LICENCE_NAMES[:4])}); "
                     "fonts are uploaded only with their licence recorded")


def name_table(data: bytes) -> dict:
    """Family/version/licence strings from an sfnt name table (TTF/OTF)."""
    try:
        count = struct.unpack_from(">H", data, 4)[0]
        for i in range(count):
            tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + 16 * i)
            if tag != b"name":
                continue
            _, records, strings = struct.unpack_from(">HHH", data, offset)
            values: dict[str, str] = {}
            for j in range(records):
                platform, _, _, name_id, length, start = struct.unpack_from(">HHHHHH", data, offset + 6 + 12 * j)
                if name_id not in (0, 1, 5, 13, 14) or str(name_id) in values:
                    continue
                raw = data[offset + strings + start:offset + strings + start + length]
                values[str(name_id)] = raw.decode("utf-16-be" if platform in (0, 3) else "latin-1", errors="replace")
            return values
    except struct.error:
        pass
    return {}


def image_kind(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048].lower()):
        return "image/svg+xml"
    return None


def collect_assets(scenes: dict[int, dict], site: Path, base: str) -> dict:
    """Font faces and images the scenes use, read from the site folder only."""
    faces: dict[tuple, dict] = {}
    images: dict[str, dict] = {}
    issues: list[dict] = []
    for scene in scenes.values():
        for f in scene.get("fonts", []):
            key = (f["family"].lower(), int(float(f["weight"])), f["style"])
            if key in faces:
                continue
            path = local_file(site, base, f.get("url") or "")
            if not path:
                issues.append({"kind": "font-not-local", "where": f["family"], "detail": str(f.get("url"))[:120]})
                continue
            data = path.read_bytes()
            mtype, ext = font_kind(data)
            faces[key] = {"family": f["family"], "weight": int(float(f["weight"])), "style": f["style"],
                          "file": str(path.relative_to(site.resolve())), "mtype": mtype, "ext": ext,
                          "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                          "licence": licence_of(path), "name_table": {k: v[:200] for k, v in name_table(data).items()},
                          "data": data}

        def walk(nodes: list[dict]) -> None:
            for n in nodes:
                for fill in n.get("fills", []):
                    if fill.get("type") == "image" and fill["src"] not in images:
                        images[fill["src"]] = read_image(fill["src"], site, base, issues)
                walk(n.get("children", []))

        walk(scene["nodes"])
        for fill in scene.get("background", []):
            if fill.get("type") == "image" and fill["src"] not in images:
                images[fill["src"]] = read_image(fill["src"], site, base, issues)
    return {"faces": faces, "images": images, "issues": issues}


def read_image(src: str, site: Path, base: str, issues: list[dict]) -> dict:
    data = None
    if src.startswith("data:"):
        head, _, payload = src.partition(",")
        data = base64.b64decode(payload) if ";base64" in head else urllib.parse.unquote_to_bytes(payload)
    else:
        path = local_file(site, base, src)
        if path:
            data = path.read_bytes()
    if data is None:
        issues.append({"kind": "image-not-local", "where": src[:120], "detail": "only images inside the site folder are converted"})
        return {"src": src, "ok": False}
    mtype = image_kind(data)
    if not mtype:
        issues.append({"kind": "image-format-unsupported", "where": src[:120], "detail": ""})
        return {"src": src, "ok": False}
    name = Path(urllib.parse.urlsplit(src).path).name[:120] if not src.startswith("data:") else "inline-image"
    return {"src": src, "ok": True, "data": data, "mtype": mtype, "name": name or "image",
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


# --------------------------------------------------------------------------
# Library: shared colours (CSS custom properties), typographies, fonts
# --------------------------------------------------------------------------

class Library:
    def __init__(self, file_id: str):
        self.file_id = file_id
        self.colors: list[dict] = []
        self.by_value: dict[tuple, dict] = {}
        self.typographies: dict[tuple, dict] = {}
        self.typo_names: set[str] = set()
        self.color_uses: dict[str, int] = {}

    def add_vars(self, variables: list[dict]) -> None:
        names = {c["name"] for c in self.colors}
        for v in variables:
            name = re.sub(r"^--", "", v["name"])[:80]
            if name in names:
                continue
            names.add(name)
            c = {"id": p.nid(), "name": name, "path": "Colour", "color": v["color"].upper(),
                 "opacity": round(float(v["opacity"]), 2)}
            self.colors.append(c)
            self.by_value.setdefault((c["color"], c["opacity"]), c)

    def match(self, color: str, opacity: float) -> dict | None:
        c = self.by_value.get((color.upper(), round(float(opacity), 2)))
        if c:
            self.color_uses[c["id"]] = self.color_uses.get(c["id"], 0) + 1
        return c

    def typography(self, font: dict, size: float, line_height: float, spacing: float,
                   transform: str, role: str | None, tag: str) -> dict:
        key = (font["font-id"], font["font-variant-id"], fmt(size), fmt(line_height), fmt(spacing), transform)
        if key in self.typographies:
            return self.typographies[key]
        label = role or (tag.upper() if re.fullmatch(r"h[1-6]", tag) else
                         {"a": "Link", "button": "Button", "li": "List", "small": "Small"}.get(tag, "Text"))
        name = f"{label} {fmt(size)}"
        if name in self.typo_names:
            name = f"{name} {font['font-weight']}{' italic' if font['font-style'] == 'italic' else ''}"
        base, k = name, 2
        while name in self.typo_names:
            name, k = f"{base} ({k})", k + 1
        self.typo_names.add(name)
        t = {"id": p.nid(), "name": name, "path": "Type", "font-id": font["font-id"],
             "font-family": font["font-family"], "font-variant-id": font["font-variant-id"],
             "font-weight": font["font-weight"], "font-style": font["font-style"], "font-size": fmt(size),
             "line-height": fmt(line_height), "letter-spacing": fmt(spacing), "text-transform": transform}
        self.typographies[key] = t
        return t

    def changes(self) -> list[dict]:
        return ([{"type": "add-color", "color": c} for c in self.colors]
                + [{"type": "add-typography", "typography": t} for t in self.typographies.values()])


class Fonts:
    """Map a scene text style to Penpot font attributes (uploaded team fonts first)."""

    def __init__(self) -> None:
        self.faces: dict[tuple, dict] = {}
        self.issues: list[dict] = []
        self._seen: set[tuple] = set()

    def add(self, family: str, weight: int, style: str, penpot_font_id: str) -> None:
        self.faces[(family.lower(), weight, style)] = {
            "font-id": "custom-" + penpot_font_id, "font-family": family,
            "font-variant-id": f"{style}-{weight}", "font-weight": str(weight), "font-style": style}

    def _note(self, kind: str, where: str, detail: str) -> None:
        if (kind, where, detail) not in self._seen:
            self._seen.add((kind, where, detail))
            self.issues.append({"kind": kind, "where": where, "detail": detail})

    def resolve(self, st: dict) -> dict:
        family, style = st["family"], st["style"] if st["style"] in ("normal", "italic") else "normal"
        weight = int(float(st["weight"]))
        exact = self.faces.get((family.lower(), weight, style))
        if exact:
            return exact
        same = [(abs(w - weight), s != style, f) for (fam, w, s), f in self.faces.items() if fam == family.lower()]
        if same:
            same.sort(key=lambda x: (x[1], x[0]))
            face = same[0][2]
            self._note("font-variant-approximated", family,
                       f"wanted {weight} {style}, used {face['font-weight']} {face['font-style']} (browser may synthesize)")
            return face
        self._note("font-fallback", family, "font not uploaded; Penpot shows Source Sans Pro instead")
        variant = ("200" if weight <= 250 else "300" if weight <= 350 else "regular" if weight <= 500
                   else "600" if weight <= 650 else "bold" if weight <= 800 else "black")
        fw = {"200": "200", "300": "300", "regular": "400", "600": "600", "bold": "700", "black": "900"}[variant]
        if style == "italic":
            variant = "italic" if variant == "regular" else variant + "italic"
        return {"font-id": FALLBACK_FONT, "font-family": FALLBACK_FONT, "font-variant-id": variant,
                "font-weight": fw, "font-style": style}


# --------------------------------------------------------------------------
# Scene -> Penpot objects
# --------------------------------------------------------------------------

def shift_path(d: str, dx: float, dy: float) -> str:
    """Translate an absolute M/L/C/Z path (the extractor's normal form)."""
    out: list[str] = []
    for cmd, nums in re.findall(r"([MLCZ])([^MLCZ]*)", d):
        values = [float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", nums)]
        moved = [v + (dx if i % 2 == 0 else dy) for i, v in enumerate(values)]
        out.append(cmd + " ".join(_num(v) for v in moved))
    return "".join(out)


def _num(v: float) -> str:
    text = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def signature(n: dict) -> tuple:
    return (n["kind"], tuple(signature(c) for c in n.get("children", [])))


def bbox(n: dict) -> tuple[float, float, float, float] | None:
    if n["kind"] != "group":
        b = n["box"]
        return b["x"], b["y"], b["w"], b["h"]
    boxes = [bb for bb in (bbox(c) for c in n.get("children", [])) if bb]
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return x0, y0, x1 - x0, y1 - y0


def walk_scene(nodes: list[dict]):
    for n in nodes:
        yield n
        yield from walk_scene(n.get("children", []))


class Builder:
    def __init__(self, file_id: str, page_id: str, library: Library, fonts: Fonts, media: dict[str, dict]):
        self.fid, self.page = file_id, page_id
        self.lib, self.fonts, self.media = library, fonts, media
        self.objects: list[dict] = []
        self.segments: list[dict] = []
        self.issues: list[dict] = []
        self.mains: dict[tuple, dict] = {}
        self.instances: list[dict] = []
        self.boards: list[dict] = []
        self.plain: dict[str, str] = {}
        self._segment: dict | None = None
        self._noted: set[tuple] = set()

    # -- bookkeeping
    def note(self, kind: str, where: str, detail: str = "") -> None:
        if (kind, where) not in self._noted:
            self._noted.add((kind, where))
            self.issues.append({"kind": kind, "where": where, "detail": detail})

    def begin(self, label: str) -> None:
        self._segment = {"label": label, "objects": [], "after": []}
        self.segments.append(self._segment)

    def put(self, obj: dict) -> dict:
        assert self._segment is not None
        self.objects.append(obj)
        self._segment["objects"].append(obj)
        return obj

    # -- paint
    def color_fill(self, color: str, opacity: float) -> dict:
        f: dict[str, Any] = {"fill-color": color.upper(), "fill-opacity": round(float(opacity), 3)}
        c = self.lib.match(color, opacity)
        if c:
            f.update({"fill-color-ref-id": c["id"], "fill-color-ref-file": self.fid})
        return f

    def fill(self, f: dict, where: str) -> dict | None:
        if f["type"] == "color":
            return self.color_fill(f["color"], f.get("opacity", 1))
        if f["type"] in ("linear", "radial"):
            g = {"type": f["type"], "start-x": f["start"][0], "start-y": f["start"][1],
                 "end-x": f["end"][0], "end-y": f["end"][1], "width": f.get("width", 1),
                 "stops": [{"color": s["color"].upper(), "opacity": s["opacity"], "offset": s["offset"]}
                           for s in f["stops"]]}
            return {"fill-opacity": round(float(f.get("opacity", 1)), 3), "fill-color-gradient": g}
        if f["type"] == "image":
            m = self.media.get(f["src"])
            if not m:
                self.note("image-missing", where, f["src"][:100])
                return {"fill-color": "#D9D9D9", "fill-opacity": 1}
            if f.get("fit") == "contain":
                self.note("background-contain-approximated", where, "Penpot image fills cover or stretch")
            return {"fill-opacity": 1, "fill-image": {"id": m["id"], "width": m["width"], "height": m["height"],
                                                     "mtype": m["mtype"], "name": m["name"][:250],
                                                     "keep-aspect-ratio": f.get("fit") == "cover"}}
        self.note("fill-unsupported", where, f["type"])
        return None

    def fills(self, fills: list[dict], where: str) -> list[dict]:
        # The extractor lists fills bottom to top; Penpot draws fills[0] on top.
        out = [x for x in (self.fill(f, where) for f in fills) if x]
        return list(reversed(out))

    def strokes(self, strokes: list[dict]) -> list[dict]:
        out = []
        for s in strokes:
            st: dict[str, Any] = {"stroke-color": s["color"].upper(), "stroke-opacity": s.get("opacity", 1),
                                  "stroke-width": s["width"], "stroke-alignment": s.get("align", "inner"),
                                  "stroke-style": s.get("style", "solid")}
            c = self.lib.match(s["color"], s.get("opacity", 1))
            if c:
                st.update({"stroke-color-ref-id": c["id"], "stroke-color-ref-file": self.fid})
            if s.get("cap") == "round":
                st.update({"stroke-cap-start": "round", "stroke-cap-end": "round"})
            out.append(st)
        return out

    def shadows(self, shadows: list[dict], where: str) -> tuple[list[dict], list[dict]]:
        """Penpot shadows plus inset rings turned into strokes.

        Penpot 2.18.1 draws a shape that has an inner shadow as the shadow alone: its filter
        primitives lose their named inputs, so the fill and children vanish from exports. A CSS
        inset ring (no offset, no blur, only spread) is exactly an inner stroke, so it becomes
        one; any other inset shadow is kept but hidden (still editable) and reported.
        """
        out: list[dict] = []
        rings: list[dict] = []
        for s in reversed(shadows):
            inner = s["style"] == "inner-shadow"
            if inner and not s["x"] and not s["y"] and not s["blur"] and s["spread"] > 0:
                rings.append({"color": s["color"], "opacity": s["opacity"], "width": s["spread"], "align": "inner"})
                continue
            if inner:
                self.note("inset-shadow-hidden", where,
                          "Penpot 2.18.1 exports drop a shape's content under an inner shadow; kept hidden")
            out.append({"id": p.nid(), "style": s["style"], "offset-x": s["x"], "offset-y": s["y"],
                        "blur": s["blur"], "spread": s["spread"], "hidden": inner,
                        "color": {"color": s["color"].upper(), "opacity": s["opacity"]}})
        return out, rings

    def decorate(self, obj: dict, n: dict) -> None:
        strokes = list(n.get("strokes") or [])
        shadows, rings = self.shadows(n.get("shadows") or [], n.get("name", ""))
        if rings:
            border = max((float(s["width"]) for s in strokes), default=0.0)
            if strokes:
                self.note("inset-ring-with-border", n.get("name", ""), "ring drawn as a wider stroke under the border")
            strokes += [{**r, "width": r["width"] + border} for r in rings]
        if strokes:
            obj["strokes"] = self.strokes(strokes)
        radius = n.get("radius") or [0, 0, 0, 0]
        if any(radius):
            obj.update({"r1": radius[0], "r2": radius[1], "r3": radius[2], "r4": radius[3]})
        if shadows:
            obj["shadow"] = shadows
        if n.get("opacity", 1) < 0.999:
            obj["opacity"] = round(float(n["opacity"]), 3)

    # -- nodes
    def node(self, n: dict, parent: str, frame: str, dx: float, dy: float, in_component: bool = False) -> None:
        kind = n["kind"]
        if kind == "board" and n.get("component") and not in_component:
            self.component_instance(n, parent, frame, dx, dy)
            return
        if kind == "board":
            b = n["box"]
            if b["w"] < 0.5 or b["h"] < 0.5:
                if n.get("children"):
                    for c in n["children"]:
                        self.node(c, parent, frame, dx, dy, in_component)
                return
            if n.get("component") and in_component:
                self.note("nested-component-flattened", n["name"], "a component inside a component stays a plain board")
            obj = p.shape("frame", n["name"], parent, frame, b["x"] + dx, b["y"] + dy, b["w"], b["h"],
                          self.fills(n.get("fills", []), n["name"]))
            obj["show-content"] = not n.get("clip", False)
            self.decorate(obj, n)
            self.put(obj)
            for c in n.get("children", []):
                self.node(c, obj["id"], obj["id"], dx, dy, in_component)
            return
        if kind == "group":
            bb = bbox(n)
            if not bb:
                return
            obj = p.shape("group", n["name"], parent, frame, bb[0] + dx, bb[1] + dy, max(bb[2], 0.01), max(bb[3], 0.01), [])
            if n.get("opacity", 1) < 0.999:
                obj["opacity"] = round(float(n["opacity"]), 3)
            self.put(obj)
            for c in n.get("children", []):
                self.node(c, obj["id"], frame, dx, dy, in_component)
            return
        if kind == "rect":
            b = n["box"]
            if b["w"] < 0.5 or b["h"] < 0.5:
                return
            obj = p.shape("rect", n["name"], parent, frame, b["x"] + dx, b["y"] + dy, b["w"], b["h"],
                          self.fills(n.get("fills", []), n["name"]))
            self.decorate(obj, n)
            self.put(obj)
            return
        if kind == "path":
            self.path(n, parent, frame, dx, dy)
            return
        if kind == "text":
            self.text(n, parent, frame, dx, dy)
            return
        self.note("node-unsupported", n.get("name", kind), kind)

    def path(self, n: dict, parent: str, frame: str, dx: float, dy: float) -> None:
        b = n["box"]
        obj = p.shape("path", n["name"], parent, frame, b["x"] + dx, b["y"] + dy, max(b["w"], 0.01), max(b["h"], 0.01),
                      self.fills(n.get("fills", []), n["name"]))
        obj["content"] = shift_path(n["d"], dx, dy)
        if n.get("strokes"):
            obj["strokes"] = self.strokes(n["strokes"])
        if n.get("opacity", 1) < 0.999:
            obj["opacity"] = round(float(n["opacity"]), 3)
        for key in ("x", "y", "width", "height"):
            obj.pop(key, None)
        self.put(obj)

    def leaf(self, st: dict, block_line_height: float) -> dict:
        font = self.fonts.resolve(st)
        size = float(st["size"])
        line_px = st.get("lineHeight") or block_line_height or size * 1.2
        ratio = round(line_px / size, 4) if size else 1.2
        spacing = float(st.get("letterSpacing") or 0)
        transform = st.get("transform") or "none"
        if transform not in ("none", "uppercase", "lowercase", "capitalize"):
            transform = "none"
        typo = self.lib.typography(font, size, ratio, spacing, transform, st.get("role"), st.get("tag", "p"))
        return {**font, "font-size": fmt(size), "line-height": fmt(ratio), "letter-spacing": fmt(spacing),
                "text-transform": transform, "text-decoration": st.get("decoration") or "none",
                "fills": [self.color_fill(st["color"], st.get("opacity", 1))],
                "typography-ref-id": typo["id"], "typography-ref-file": self.fid}

    def text(self, n: dict, parent: str, frame: str, dx: float, dy: float) -> None:
        t, b = n["text"], n["box"]
        align = t.get("align", "left")
        slack = 0 if align == "justify" else 2
        x = b["x"] + dx - (slack / 2 if align == "center" else slack if align == "right" else 0)
        y = b["y"] + dy
        w, h = b["w"] + slack, max(b["h"], 1)
        paragraphs = []
        for para in t["paragraphs"]:
            kids = [{"text": leaf["text"], **self.leaf(leaf["style"], t.get("lineHeight") or 0)} for leaf in para]
            if not kids:
                continue
            head = {k: v for k, v in kids[0].items() if k != "text"}
            paragraphs.append({"type": "paragraph", "text-align": align, "text-direction": "ltr", **head, "children": kids})
        if not paragraphs:
            return
        obj = p.shape("text", n["name"], parent, frame, x, y, w, h, [])
        if t.get("plain") is not None:
            self.plain[obj["id"]] = t["plain"]
        obj["content"] = {"type": "root", "vertical-align": "top",
                          "children": [{"type": "paragraph-set", "children": paragraphs}]}
        obj["grow-type"] = "fixed"
        positions = []
        for frag in t.get("lines", []):
            try:
                leaf = paragraphs[frag["p"]]["children"][frag["l"]]
            except (IndexError, KeyError):
                continue
            fx, fy, fw, fh = frag["x"] + dx, frag["y"] + dy, frag["w"], frag["h"]
            spacing = float(leaf["letter-spacing"])
            positions.append({"x": fx, "y": fy, "width": fw, "height": fh,
                              "x1": fx - x, "y1": fy - fh - y, "x2": fx - x + fw, "y2": fy - y,
                              "font-style": leaf["font-style"], "text-transform": leaf["text-transform"],
                              "font-size": leaf["font-size"] + "px", "font-weight": leaf["font-weight"],
                              "text-decoration": leaf["text-decoration"],
                              "letter-spacing": f"{fmt(spacing)}px" if spacing else "normal",
                              "fills": leaf["fills"], "direction": "ltr", "font-family": leaf["font-family"],
                              "text": frag["text"]})
        if positions:
            obj["position-data"] = positions
        else:
            self.note("text-without-lines", n["name"], "no line boxes; Penpot lays it out itself")
        self.put(obj)

    # -- components
    def component_main(self, n: dict, x: float, y: float, name: str) -> dict:
        b = n["box"]
        start = len(self._segment["objects"]) if self._segment else 0
        self.node({**n, "component": None}, p.ROOT, p.ROOT, x - b["x"], y - b["y"], in_component=True)
        assert self._segment is not None
        objs = self._segment["objects"][start:]
        cid = p.nid()
        p.mark_main(objs[0], cid, self.fid)
        self._segment["after"].append({"type": "add-component", "id": cid, "name": name, "path": "Components",
                                       "main-instance-id": objs[0]["id"], "main-instance-page": self.page})
        return {"id": cid, "name": name, "root": objs[0]["id"], "objects": objs, "width": b["w"], "height": b["h"]}

    def component_instance(self, n: dict, parent: str, frame: str, dx: float, dy: float) -> None:
        key = (n["component"], signature(n))
        main = self.mains.get(key)
        assert self._segment is not None
        start = len(self._segment["objects"])
        self.node({**n, "component": None}, parent, frame, dx, dy, in_component=True)
        objs = self._segment["objects"][start:]
        if not objs:
            return
        if not main or len(main["objects"]) != len(objs):
            self.note("component-not-linked", n["component"], "structure differs from its main; kept as a plain board")
            return
        root, mroot = objs[0], main["objects"][0]
        p.mark_instance(root, main["id"], self.fid, mroot["id"])
        touched_count = 0
        for obj, src in zip(objs, main["objects"], strict=True):
            obj["shape-ref"] = src["id"]
            touched = sorted(touched_groups(obj, src, root, mroot))
            if touched:
                obj["touched"] = touched
                touched_count += 1
        self.instances.append({"component": main["name"], "root": root["id"], "objects": len(objs),
                               "touched_objects": touched_count})

    def plan_components(self, scenes: dict[int, dict], x: float) -> None:
        """One main per (name, structure), taken from its first occurrence at the widest width."""
        self.begin("components")
        y = 0.0
        names: dict[str, int] = {}
        for width in sorted(scenes, reverse=True):
            for n in walk_scene(scenes[width]["nodes"]):
                if n["kind"] != "board" or not n.get("component"):
                    continue
                key = (n["component"], signature(n))
                if key in self.mains:
                    continue
                count = names.get(n["component"], 0) + 1
                names[n["component"]] = count
                name = n["component"] if count == 1 else f"{n['component']} {count}"
                if count > 1:
                    self.note("component-variant", n["component"], f"a second structure became {name}")
                self.mains[key] = self.component_main(n, x, y, name)
                y += n["box"]["h"] + 120

    def page_board(self, scene: dict, x0: float, label: str) -> dict:
        self.begin(f"board-{scene['width']}")
        w, h = scene["width"], scene["height"]
        board = p.shape("frame", f"{label} — {w}", p.ROOT, p.ROOT, x0, 0, w, h,
                        self.fills(scene.get("background", []), "page"))
        board["show-content"] = False
        self.put(board)
        for n in scene["nodes"]:
            self.node(n, board["id"], board["id"], x0, 0)
        self.boards.append({"width": w, "id": board["id"], "name": board["name"], "height": h,
                            "objects": len(self._segment["objects"]) if self._segment else 0})
        return board


def touched_groups(obj: dict, src: dict, root: dict, mroot: dict) -> set[str]:
    def rel(o: dict, r: dict) -> list[float]:
        s, rs = o["selrect"], r["selrect"]
        if o is r:
            return [round(s["width"], 1), round(s["height"], 1)]
        return [round(s["x"] - rs["x"], 1), round(s["y"] - rs["y"], 1), round(s["width"], 1), round(s["height"], 1)]

    def strip(v: Any) -> Any:
        if isinstance(v, list):
            return [strip(x) for x in v]
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k != "id"}
        return v

    groups = set()
    if rel(obj, root) != rel(src, mroot):
        groups.add("geometry-group")
    if obj["type"] == "text" and json.dumps(obj.get("content"), sort_keys=True) != json.dumps(src.get("content"), sort_keys=True):
        groups.add("content-group")
    if obj["type"] == "path":
        rs, ms = root["selrect"], mroot["selrect"]
        if shift_path(obj["content"], -rs["x"], -rs["y"]) != shift_path(src["content"], -ms["x"], -ms["y"]):
            groups.add("content-group")
    for key, group in (("fills", "fill-group"), ("strokes", "stroke-group"), ("shadow", "shadow-group"),
                       ("opacity", "layer-effects-group"), ("name", "name-group")):
        if strip(obj.get(key)) != strip(src.get(key)):
            groups.add(group)
    if [obj.get(k) for k in ("r1", "r2", "r3", "r4")] != [src.get(k) for k in ("r1", "r2", "r3", "r4")]:
        groups.add("radius-group")
    return groups


def build(scenes: dict[int, dict], file_id: str, page_id: str, fonts: Fonts, media: dict[str, dict],
          label: str = "Homepage") -> dict:
    """Pure: scenes -> ordered Penpot change chunks + what was built (for verify/report)."""
    lib = Library(file_id)
    for width in sorted(scenes, reverse=True):
        lib.add_vars(scenes[width].get("vars", []))
    b = Builder(file_id, page_id, lib, fonts, media)
    widths = sorted(scenes)
    xs, x = {}, 0.0
    for width in widths:
        xs[width] = x
        x += width + BOARD_GAP
    b.plan_components(scenes, x - BOARD_GAP + LIBRARY_GAP)
    for width in widths:
        b.page_board(scenes[width], xs[width], label)
    chunks: list[dict] = [{"label": "library", "changes": lib.changes()}]
    for seg in b.segments:
        changes = [p.add_obj(o, page_id) for o in seg["objects"]] + seg["after"]
        for i in range(0, len(changes), CHUNK):
            chunks.append({"label": f"{seg['label']}#{i // CHUNK + 1}", "changes": changes[i:i + CHUNK]})
    issues = []
    for width in widths:
        for issue in scenes[width].get("issues", []):
            issues.append({**issue, "width": width})
    issues += fonts.issues + b.issues
    sections = [o["name"] for o in b.objects if o["type"] == "frame" and re.match(r"^(Section|Header|Footer|Navigation|Main)\b", o["name"])]
    return {"chunks": [c for c in chunks if c["changes"]], "objects": b.objects, "boards": b.boards,
            "components": [{"id": m["id"], "name": m["name"], "root": m["root"], "objects": len(m["objects"])}
                           for m in b.mains.values()],
            "instances": b.instances, "colors": lib.colors, "typographies": list(lib.typographies.values()),
            "color_uses": lib.color_uses, "issues": issues, "sections": sections, "plain": b.plain}


# --------------------------------------------------------------------------
# Penpot client additions (multipart media/font upload, asset-embedding export)
# --------------------------------------------------------------------------

def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----temper" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    for name, (filename, data, mtype) in files.items():
        safe = re.sub(r'["\r\n]', "_", filename)
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{safe}"\r\n'
                 f"Content-Type: {mtype}\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def penpot_client():
    """design_homepage_v1.Penpot plus raw/multipart requests, uploads and asset-embedding exports."""
    import urllib.error
    import urllib.request

    import design_homepage_v1 as v1

    class Client(v1.Penpot):
        def raw(self, url: str, data: bytes, ctype: str, timeout: int = 120) -> bytes:
            if not url.startswith(self.base + "/"):
                raise ValueError("Penpot URL left authorized host")
            req = urllib.request.Request(url, data=data, headers={"Accept": "application/json", "Content-Type": ctype})
            try:
                with self.http.open(req, timeout=timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"Penpot HTTP {exc.code} at {urllib.parse.urlsplit(url).path} (response suppressed)") from None
            except urllib.error.URLError:
                raise RuntimeError("Penpot transport unavailable (credentials suppressed)") from None

        def rpc_multipart(self, method: str, fields: dict[str, str], files: dict) -> dict:
            body, ctype = multipart(fields, files)
            data = self.raw(self.base + "/api/main/methods/" + method, body, ctype)
            return p.kebab(json.loads(data)) if data else {}

        def rpc_transit(self, method: str, params: dict) -> Any:
            data = self.raw(self.base + "/api/main/methods/" + method, json.dumps(p.transit(params)).encode(),
                            "application/transit+json")
            return p.kebab(json.loads(data)) if data else None

        def team(self) -> str:
            return self.profile["default-team-id"]

        def font_variants(self) -> list[dict]:
            return self.rpc("get-font-variants", {"team-id": self.team()}) or []

        def upload_font(self, face: dict, font_id: str) -> dict:
            session = self.rpc("create-upload-session", {"total-chunks": 1})
            sid = session["session-id"]
            self.rpc_multipart("upload-chunk", {"session-id": sid, "index": "0"},
                               {"content": (f"{face['family']}-{face['weight']}{face['style'][0]}.{face['ext']}",
                                            face["data"], face["mtype"])})
            return self.rpc_transit("create-font-variant", {
                ":team-id": "uuid:" + self.team(), ":font-id": "uuid:" + font_id, ":font-family": face["family"],
                ":font-weight": face["weight"], ":font-style": face["style"],
                ":uploads": {face["mtype"]: "uuid:" + sid}})

        def upload_media(self, file_id: str, image: dict) -> dict:
            return self.rpc_multipart("upload-file-media-object",
                                      {"file-id": file_id, "is-local": "true", "name": image["name"][:250]},
                                      {"content": (image["name"][:120] or "image", image["data"], image["mtype"])})

        def export_board(self, state: dict, board: dict, kind: str, destination: Path) -> dict:
            params = {":cmd": ":export-shapes", ":profile-id": "uuid:" + self.profile["id"], ":wait": True,
                      ":exports": [{":file-id": "uuid:" + state["file_id"], ":page-id": "uuid:" + state["page_id"],
                                    ":object-id": "uuid:" + board["id"], ":type": ":" + kind, ":suffix": "",
                                    ":scale": 1, ":name": board["name"]}]}
            raw = self.request(self.base + "/api/export", p.transit(params), "application/transit+json", 600)
            result = p.untransit(json.loads(raw))
            uri = result.get("uri", "") if isinstance(result, dict) else ""
            if uri.startswith("/"):
                uri = self.base + uri
            data = self.request(uri, timeout=300)
            embedded = 0
            if kind == "svg":
                data, embedded = embed_assets(data, self.base, lambda u: self.request(u, timeout=120))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            out = {"path": str(destination), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            if kind == "png":
                if data[:8] != b"\x89PNG\r\n\x1a\n":
                    raise ValueError("export is not PNG")
                w, h = struct.unpack(">II", data[16:24])
                out["size"] = [w, h]
                if (w, h) != (round(board["width"]), round(board["height"])):
                    out["size_mismatch"] = True
            else:
                out["embedded_assets"] = embedded
            return out

    return Client()


def embed_assets(data: bytes, base: str, fetch) -> tuple[bytes, int]:
    """Make a Penpot SVG export self-contained: same-host /assets/ fonts and images -> data: URIs."""
    text = data.decode("utf-8")
    cache: dict[str, str] = {}
    host = re.escape(base)
    pattern = re.compile(r"(url\(\s*[\"']?|(?:xlink:)?href=\")((?:" + host + r")?/assets/[^\"')\s]+)")

    def replace(match: re.Match) -> str:
        url = match[2] if match[2].startswith("http") else base + match[2]
        if url not in cache:
            blob = fetch(url)
            kind = image_kind(blob) or {b"wOFF": "font/woff", b"wOF2": "font/woff2", b"OTTO": "font/otf",
                                        b"\x00\x01\x00\x00": "font/ttf"}.get(blob[:4], "application/octet-stream")
            cache[url] = f"data:{kind};base64," + base64.b64encode(blob).decode("ascii")
        return match[1] + cache[url]

    out = pattern.sub(replace, text)
    return out.encode("utf-8"), len(cache)


# --------------------------------------------------------------------------
# Upload, save, verify
# --------------------------------------------------------------------------

def upload_fonts(client: Any, faces: dict[tuple, dict]) -> tuple[Fonts, list[dict]]:
    fonts = Fonts()
    records = []
    existing = client.font_variants()
    family_ids: dict[str, str] = {}
    have: dict[tuple, dict] = {}
    for v in existing:
        fam = str(v.get("font-family", "")).lower()
        family_ids.setdefault(fam, str(v.get("font-id")))
        have[(fam, int(v.get("font-weight", 400)), str(v.get("font-style", "normal")))] = v
    for key, face in sorted(faces.items()):
        fam = face["family"].lower()
        record = {k: v for k, v in face.items() if k != "data"}
        if key in have:
            font_id = str(have[key]["font-id"])
            record.update({"penpot_font_id": font_id, "reused": True})
        else:
            font_id = family_ids.get(fam) or p.nid()
            created = client.upload_font(face, font_id)
            family_ids[fam] = font_id
            record.update({"penpot_font_id": font_id, "reused": False,
                           "penpot_variant_id": (created or {}).get("id"),
                           "woff1": bool((created or {}).get("woff1-file-id"))})
        fonts.add(face["family"], face["weight"], face["style"], font_id)
        records.append(record)
    return fonts, records


def upload_images(client: Any, file_id: str, images: dict[str, dict]) -> tuple[dict[str, dict], list[dict]]:
    media, records = {}, []
    by_hash: dict[str, dict] = {}
    for src, image in images.items():
        if not image.get("ok"):
            continue
        if image["sha256"] in by_hash:
            media[src] = by_hash[image["sha256"]]
            continue
        m = client.upload_media(file_id, image)
        entry = {"id": m["id"], "width": int(m["width"]), "height": int(m["height"]),
                 "mtype": m.get("mtype", image["mtype"]), "name": m.get("name", image["name"])}
        media[src] = by_hash[image["sha256"]] = entry
        records.append({"src": src[:160], "sha256": image["sha256"], "bytes": image["bytes"], **entry})
    return media, records


def content_text(content: dict | None) -> str:
    out = []
    for ps in (content or {}).get("children", []):
        for para in ps.get("children", []):
            out.append("".join(leaf.get("text", "") for leaf in para.get("children", [])))
    return "\n".join(out)


def verify(file: dict, page_id: str, built: dict) -> dict:
    """Fresh reopen: every built layer, board size, text, path, library item and component link."""
    data = file.get("data", {})
    objects = data.get("pages-index", {}).get(page_id, {}).get("objects", {})
    missing, wrong, text_bad, pos_missing, path_bad, page_text_bad = [], [], [], [], [], []
    plain = built.get("plain", {})
    for o in built["objects"]:
        got = objects.get(o["id"])
        if not got:
            missing.append(o["name"])
            continue
        if got.get("type") != o["type"] or got.get("name") != o["name"]:
            wrong.append(o["name"])
        if o["type"] == "text":
            if content_text(got.get("content")) != content_text(o.get("content")):
                text_bad.append(o["name"])
            if o["id"] in plain and " ".join(content_text(got.get("content")).split()) != plain[o["id"]]:
                page_text_bad.append(o["name"])
            if o.get("position-data") and len(got.get("position-data") or []) != len(o["position-data"]):
                pos_missing.append(o["name"])
        if o["type"] == "path" and not got.get("content"):
            path_bad.append(o["name"])
    boards = []
    for b in built["boards"]:
        got = objects.get(b["id"], {})
        boards.append({"name": b["name"], "ok": bool(got) and abs(got.get("width", 0) - b["width"]) < 0.01
                       and abs(got.get("height", 0) - b["height"]) < 0.01})
    colors = data.get("colors", {})
    typos = data.get("typographies", {})
    comps = data.get("components", {})
    comp_ok = all(c["id"] in comps and not comps[c["id"]].get("deleted") for c in built["components"])
    refs = [o for o in built["objects"] if o.get("shape-ref")]
    refs_ok = all(objects.get(o["id"], {}).get("shape-ref") == o["shape-ref"] and o["shape-ref"] in objects for o in refs)
    custom = {t["font-id"] for t in built["typographies"] if t["font-id"].startswith("custom-")}
    checks = {
        "boards": all(b["ok"] for b in boards) and len(boards) == len(built["boards"]),
        "all_layers_present": not missing,
        "types_and_names": not wrong,
        "live_text_equal": not text_bad,
        "text_matches_page": not page_text_bad and len(plain) > 0,
        "text_line_boxes": not pos_missing,
        "paths_present": not path_bad,
        "named_sections": len(built["sections"]) > 0,
        "shared_colours": all(c["id"] in colors for c in built["colors"]) and len(built["colors"]) > 0,
        "shared_typographies": all(t["id"] in typos for t in built["typographies"]) and len(built["typographies"]) > 0,
        "components": comp_ok and len(built["components"]) > 0,
        "instances_linked": refs_ok and len(built["instances"]) > 0,
        "custom_fonts_used": len(custom) > 0,
    }
    return {"checks": checks, "passed": all(checks.values()), "boards": boards,
            "counts": {"objects": len(built["objects"]), "reopened_objects": len(objects),
                       "texts": sum(o["type"] == "text" for o in built["objects"]),
                       "paths": sum(o["type"] == "path" for o in built["objects"]),
                       "images": sum(any("fill-image" in f for f in o.get("fills", [])) for o in built["objects"]),
                       "frames": sum(o["type"] == "frame" for o in built["objects"]),
                       "groups": sum(o["type"] == "group" for o in built["objects"]),
                       "colors": len(built["colors"]), "typographies": len(built["typographies"]),
                       "components": len(built["components"]), "instances": len(built["instances"])},
            "problems": {"missing": missing[:20], "wrong": wrong[:20], "text": text_bad[:20],
                         "line_boxes": pos_missing[:20], "paths": path_bad[:20], "page_text": page_text_bad[:20]}}


def judge(fidelity: dict) -> dict:
    checks = {
        "same_size": fidelity["browser"] == fidelity["penpot"],
        "overall": fidelity["overall_pct"] <= FIDELITY["overall_pct"],
        "nontext": fidelity["nontext_pct"] <= FIDELITY["nontext_pct"],
        "text": fidelity["text_pct"] <= FIDELITY["text_pct"],
        "tiles_differing": fidelity.get("tile_max_pct", 100.0) <= FIDELITY["tile_max_pct"],
        "tiles_mean": fidelity.get("tile_mean_max", 255.0) <= FIDELITY["tile_mean_max"],
    }
    return {**fidelity, "checks": checks, "passed": all(checks.values())}


# --------------------------------------------------------------------------
# Whole conversion
# --------------------------------------------------------------------------

def capture(site: Path, page: str, out: Path, widths: tuple[int, ...], browser: str, serve_host: str | None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    host = serve_host or urllib.parse.urlparse(browser).hostname or "playwright-mcp"
    base, srv = serve(site, out, host)
    try:
        summary = browser_run(browser, [capture_code(base, page, widths)])[0]
    finally:
        srv.shutdown()
    scenes = {w: json.loads((out / f"scene-{w}.json").read_text()) for w in widths}
    return {"base": base, "summary": summary, "scenes": scenes}


def compare(out: Path, scenes: dict[int, dict], browser: str, serve_host: str | None) -> dict[int, dict]:
    host = serve_host or urllib.parse.urlparse(browser).hostname or "playwright-mcp"
    base, srv = serve(out, out, host)
    try:
        jobs = [{"a": f"{base}/__out/browser-{w}.png", "b": f"{base}/__out/penpot-{w}.png",
                 "put": f"{base}/__put/heat-{w}.png", "text": text_rects(scenes[w]),
                 "threshold": FIDELITY["threshold"], "shift": FIDELITY["shift"], "tile": FIDELITY["tile"]}
                for w in sorted(scenes)]
        results = browser_run(browser, [compare_code(base, jobs)])[0]
    finally:
        srv.shutdown()
    return {w: judge(r) for w, r in zip(sorted(scenes), results, strict=True)}


def convert(site: Path, page: str, out: Path, name: str, widths: tuple[int, ...] = WIDTHS,
            browser: str = "http://playwright-mcp:8931/mcp", serve_host: str | None = None,
            client: Any = None, label: str = "Homepage") -> dict:
    """Render, extract, build, save, reopen, export and compare. Returns the report (also saved)."""
    started = time.time()
    site = site.resolve()
    report: dict[str, Any] = {"version": 1, "started_at": now(), "site": str(site), "page": page, "widths": list(widths),
                              "fidelity_bar": FIDELITY, "passed": False}
    cap = capture(site, page, out, widths, browser, serve_host)
    scenes = cap["scenes"]
    report["capture"] = cap["summary"]
    assets = collect_assets(scenes, site, cap["base"])
    client = client or penpot_client()
    if not client.profile:
        client.login()
    pending = out / "pending.json"
    save_json(pending, {"name": name, "created_at": now(), "state": "creating"})
    file = client.create(name)
    page_id = file["data"]["pages"][0]
    state = {"file_id": file["id"], "page_id": page_id, "name": name}
    save_json(pending, {**state, "created_at": now(), "state": "uploading"})
    fonts, font_records = upload_fonts(client, assets["faces"])
    media, media_records = upload_images(client, file["id"], assets["images"])
    built = build(scenes, file["id"], page_id, fonts, media, label)
    built["issues"] = assets["issues"] + built["issues"]
    save_json(out / "changes-summary.json", [{"label": c["label"], "changes": len(c["changes"])} for c in built["chunks"]])
    for i, chunk in enumerate(built["chunks"]):
        save_json(pending, {**state, "created_at": now(), "state": f"saving {i + 1}/{len(built['chunks'])}"})
        client.update(file["id"], chunk["changes"])
    save_json(pending, {**state, "created_at": now(), "state": "saved"})
    fresh = client.get(file["id"])
    checked = verify(fresh, page_id, built)
    exports: dict[str, dict] = {}
    for b in built["boards"]:
        board = {"id": b["id"], "name": b["name"], "width": b["width"], "height": b["height"]}
        exports[f"png-{b['width']}"] = client.export_board(state, board, "png", out / f"penpot-{b['width']}.png")
        exports[f"svg-{b['width']}"] = client.export_board(state, board, "svg", out / f"penpot-{b['width']}.svg")
    fidelity = compare(out, scenes, browser, serve_host)
    issue_counts: dict[str, int] = {}
    for issue in built["issues"]:
        issue_counts[issue["kind"]] = issue_counts.get(issue["kind"], 0) + 1
    report.update({
        "file": {**state, "url": f"{client.base}/#/workspace?team-id={client.team()}&file-id={file['id']}&page-id={page_id}",
                 "revn": fresh.get("revn")},
        "boards": built["boards"], "components": built["components"], "instances": built["instances"],
        "colors": [{"name": c["name"], "color": c["color"], "opacity": c["opacity"],
                    "uses": built["color_uses"].get(c["id"], 0)} for c in built["colors"]],
        "typographies": [{k: t[k] for k in ("name", "font-family", "font-weight", "font-style", "font-size", "line-height",
                                            "letter-spacing", "text-transform")} for t in built["typographies"]],
        "sections": built["sections"], "fonts": font_records, "media": media_records,
        "issues": built["issues"], "issue_counts": issue_counts, "verify": checked, "exports": exports,
        "fidelity": {str(w): f for w, f in fidelity.items()},
        "fidelity_passed": all(f["passed"] for f in fidelity.values()),
        "seconds": round(time.time() - started, 1), "finished_at": now()})
    report["passed"] = checked["passed"] and report["fidelity_passed"]
    save_json(out / "conversion.json", report)
    pending.unlink(missing_ok=True)
    return report


def scene_build_only(out: Path, widths: tuple[int, ...]) -> dict:
    """Offline: saved scenes -> changes (no Penpot), with a stand-in font/media mapping."""
    scenes = {w: json.loads((out / f"scene-{w}.json").read_text()) for w in widths}
    fonts = Fonts()
    media: dict[str, dict] = {}
    for scene in scenes.values():
        for f in scene.get("fonts", []):
            fonts.add(f["family"], int(float(f["weight"])), f["style"], str(uuid.uuid5(uuid.NAMESPACE_URL, f["family"])))
        for n in walk_scene(scene["nodes"]):
            for fill in n.get("fills", []):
                if fill.get("type") == "image":
                    media.setdefault(fill["src"], {"id": p.nid(), "width": 10, "height": 10, "mtype": "image/png", "name": "x"})
    return build(scenes, p.nid(), p.nid(), fonts, media)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("capture", "convert"):
        s = sub.add_parser(cmd)
        s.add_argument("--site", required=True, type=Path)
        s.add_argument("--page", default="index.html")
        s.add_argument("--out", required=True, type=Path)
        s.add_argument("--widths", default=",".join(str(w) for w in WIDTHS))
        s.add_argument("--browser", default="http://playwright-mcp:8931/mcp")
        s.add_argument("--serve-host", default=None, help="address whose route reaches the browser (host runs: its container IP)")
        if cmd == "convert":
            s.add_argument("--name", required=True)
            s.add_argument("--label", default="Homepage")
    s = sub.add_parser("build")
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--widths", default=",".join(str(w) for w in WIDTHS))
    args = ap.parse_args()
    widths = tuple(int(w) for w in args.widths.split(","))
    if args.cmd == "capture":
        cap = capture(args.site.resolve(), args.page, args.out, widths, args.browser, args.serve_host)
        print(json.dumps(cap["summary"]))
        return 0
    if args.cmd == "build":
        built = scene_build_only(args.out, widths)
        summary = {"chunks": [(c["label"], len(c["changes"])) for c in built["chunks"]],
                   "objects": len(built["objects"]), "components": built["components"],
                   "instances": len(built["instances"]), "issues": len(built["issues"])}
        save_json(args.out / "build-offline.json", {k: v for k, v in built.items() if k != "chunks"})
        print(json.dumps(summary))
        return 0
    report = convert(args.site, args.page, args.out, args.name, widths, args.browser, args.serve_host, label=args.label)
    print(json.dumps({"passed": report["passed"], "file": report["file"], "verify": report["verify"]["checks"],
                      "fidelity": {w: {k: f[k] for k in ("overall_pct", "nontext_pct", "text_pct", "passed")}
                                   for w, f in report["fidelity"].items()},
                      "issues": report["issue_counts"]}))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
