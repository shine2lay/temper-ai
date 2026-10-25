#!/usr/bin/env python3
"""Model-free preflight -> full-page capture -> independent evidence verification."""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import ipaddress
import json
import math
import pathlib
import re
import struct
import uuid
import zlib
from datetime import UTC, datetime
from urllib.parse import urlsplit

HERE = pathlib.Path(__file__).resolve().parent
SCHEMA = "design.web_capture.v2"
BROWSER = "http://playwright-mcp:8931/mcp"
DEFAULT_VIEWS = [{"name": "desktop", "width": 1440, "height": 900}, {"name": "mobile", "width": 390, "height": 844}]
REJECT_LABELS = {"reject all", "reject", "decline", "decline all", "only necessary", "necessary only",
                 "use necessary cookies only", "refuse", "deny"}
LIMITATION = ("Measured capture completeness, not semantic/visual quality certification. Sampled occlusion is not an "
              "all-pixels proof. CSS background loading, video, closed shadow roots and nested-frame clipping are not fully measured. "
              "Mobile width is not handset emulation. Cut-off, diagnostic and obstructed evidence is never usable.")


def now():
    return datetime.now(UTC).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def public_url(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise ValueError("URL must be HTTP(S) text without whitespace")
    parts = urlsplit(value)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        raise ValueError("URL must be public HTTP(S), without credentials")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
        raise ValueError("local/private URL is outside this capture contract")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host):
            raise ValueError("ambiguous numeric URL host") from None
    else:
        if not address.is_global:
            raise ValueError("local/private URL is outside this capture contract")
    return value


def request_config(url, selector="body", views=None, timeout_ms=30000, browser_url=BROWSER):
    public_url(url)
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("ready_selector must be a nonempty CSS selector")
    if type(timeout_ms) is not int or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    views = DEFAULT_VIEWS if views is None else views
    if not isinstance(views, list) or not views:
        raise ValueError("viewports must be a nonempty list")
    names = set()
    for view in views:
        if not isinstance(view, dict) or set(view) != {"name", "width", "height"}:
            raise ValueError("each viewport needs exactly name, width and height")
        if not isinstance(view["name"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", view["name"]) or view["name"] in names:
            raise ValueError("viewport names must be unique safe names")
        names.add(view["name"])
        if any(type(view[k]) is not int or view[k] <= 0 for k in ("width", "height")):
            raise ValueError("viewport dimensions must be positive integers")
    endpoint = urlsplit(browser_url)
    if endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError("browser_url must be an HTTP(S) MCP endpoint without credentials")
    return {"url": url, "ready_selector": selector, "viewports": views, "timeout_ms": timeout_ms,
            "settle_ms": 200, "network_quiet_ms": 300, "browser_url": browser_url}


def workspace_path(value):
    path = pathlib.Path(value).resolve(strict=True)
    if not path.is_dir():
        raise ValueError("workspace_path is not a directory")
    return path


def inside(path, workspace):
    path = pathlib.Path(path).resolve(strict=True)
    if not path.is_relative_to(workspace):
        raise ValueError("receipt/artifact is outside workspace_path")
    return path


def read_receipt(path, workspace, phase):
    path = inside(path, workspace)
    value = json.loads(path.read_text())
    if value.get("schema") != SCHEMA or value.get("phase") != phase or value.get("status") != ("completed" if phase == "capture" else "passed"):
        raise ValueError(f"{phase} did not complete; artifacts are diagnostic only")
    return path, value


def mcp_value(reply):
    text = "\n".join(getattr(item, "text", "") or "" for item in reply.content)
    if getattr(reply, "isError", False):
        raise RuntimeError("browser MCP tool failed: " + text[:1200])
    match = re.search(r"### Result\n(.*?)(?:\n### |\Z)", text, re.S)
    if text.startswith("### Error") or not match:
        raise RuntimeError("browser MCP returned no structured result")
    return json.loads(match.group(1).strip())


class BrowserClient:
    """One browser MCP session.

    A full-page capture can take longer than 5 minutes (a page that never goes network-quiet waits
    the full settle at every scroll step: Edenmoor desktop took 407 s). The MCP client's default
    300 s stream read timeout left such a call waiting forever (#150 R14). The read timeout here is
    above the capture stage's own 3600 s timeout, and a call with no answer by CALL_DEADLINE_S ends
    in a recorded error just before the stage would be killed. Not a new limit.
    """
    CALL_DEADLINE_S = 3500

    def __init__(self, url, deadline_s=CALL_DEADLINE_S):
        self.url = url
        self.deadline_s = deadline_s

    async def __aenter__(self):
        from contextlib import AsyncExitStack

        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        self.stack = AsyncExitStack()
        try:
            http = await self.stack.enter_async_context(httpx.AsyncClient(
                follow_redirects=True, timeout=httpx.Timeout(30, read=self.deadline_s + 120)))
            rd, wr, _ = await self.stack.enter_async_context(streamable_http_client(self.url, http_client=http))
            self.session = await self.stack.enter_async_context(ClientSession(rd, wr))
            await self.session.initialize()
            tools = await self.session.list_tools()
            if "browser_run_code_unsafe" not in {tool.name for tool in tools.tools}:
                raise RuntimeError("required browser tool unavailable; no installation attempted")
        except BaseException:
            await self.stack.aclose()
            raise
        return self

    async def __aexit__(self, *args):
        return await self.stack.__aexit__(*args)

    async def call(self, code):
        try:
            reply = await asyncio.wait_for(
                self.session.call_tool("browser_run_code_unsafe", {"code": code}), self.deadline_s)
        except TimeoutError:
            raise RuntimeError(f"browser call gave no answer within {self.deadline_s} s") from None
        return mcp_value(reply)


def preflight_code(selector):
    return """async (page) => {
      const browser = page.context().browser(); let context;
      const result = {isolated_context: false, png: false, context_closed: false, browser_version: browser.version()};
      try {
        context = await browser.newContext({viewport:{width:16,height:16},bypassCSP:false});
        const target = await context.newPage();
        await target.evaluate(selector => document.querySelector(selector) !== null, SELECTOR);
        const png = await target.screenshot({type:'png'});
        result.isolated_context = true; result.png = png.subarray(0,8).toString('hex') === '89504e470d0a1a0a';
      } finally { if (context) { await context.close(); result.context_closed = true; } }
      return result;
    }""".replace("SELECTOR", json.dumps(selector))


def capture_code(request, viewport, setup_js="null"):
    return ("async (page) => {\n" + (HERE / "design_web_capture.js").read_text()
            + "\nreturn await captureWithBrowser(page.context().browser()," + json.dumps(request) + ","
            + json.dumps(viewport) + "," + setup_js + ");\n}")


async def preflight(workspace, request, client_factory=BrowserClient):
    folder = workspace / "web-captures" / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / "preflight.json"
    receipt = {"schema": SCHEMA, "phase": "preflight", "capture_id": folder.name, "created_at": now(),
               "request": request, "request_sha256": digest(canonical(request)), "status": "failed"}
    try:
        async with client_factory(request["browser_url"]) as client:
            capability = await client.call(preflight_code(request["ready_selector"]))
        receipt["capabilities"] = capability
        if not all(capability.get(k) is True for k in ("isolated_context", "png", "context_closed")):
            raise RuntimeError("isolated screenshot/cleanup capability not proved")
        receipt["status"] = "passed"
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    save(path, receipt)
    return path, receipt


def png_chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)


def encode_png(width, height, pixels):
    if len(pixels) != width * height * 3:
        raise ValueError("RGB dimensions mismatch")
    stride = width * 3
    raw = b"".join(b"\0" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(raw)) + png_chunk(b"IEND", b""))


def decode_png(data):
    """CRC/stream-checked 8-bit RGB/RGBA PNG decoder; no imaging dependency in worker."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG")
    pos, compressed, header, ended = 8, bytearray(), None, False
    while pos < len(data):
        if pos + 12 > len(data):
            raise ValueError("truncated PNG")
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + size + 8]
        if pos + size + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        if zlib.crc32(kind + body) & 0xffffffff != struct.unpack(">I", data[pos + size + 8:pos + size + 12])[0]:
            raise ValueError("PNG CRC mismatch")
        pos += size + 12
        if kind == b"IHDR":
            if header is not None or size != 13:
                raise ValueError("invalid PNG header")
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            ended = True
            break
    if not header or not ended or pos != len(data):
        raise ValueError("incomplete PNG")
    width, height, depth, color, compression, filtering, interlace = header
    if min(width, height) <= 0 or depth != 8 or color not in (2, 6) or compression or filtering or interlace:
        raise ValueError("unsupported PNG encoding")
    bpp = 3 if color == 2 else 4
    stride, previous = width * bpp, bytearray(width * bpp)
    expected = height * (stride + 1)
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(bytes(compressed), expected + 1)
    if len(raw) != expected or not decompressor.eof or decompressor.unused_data:
        raise ValueError("invalid PNG image stream")
    pixels = bytearray()
    for y in range(height):
        offset = y * (stride + 1)
        f, row = raw[offset], bytearray(raw[offset + 1:offset + stride + 1])
        if f > 4:
            raise ValueError("unsupported PNG row filter")
        if f:
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                b = previous[x]
                if f == 1:
                    predictor = a
                elif f == 2:
                    predictor = b
                elif f == 3:
                    predictor = (a + b) // 2
                else:
                    c = previous[x - bpp] if x >= bpp else 0
                    p = a + b - c
                    da, db, dc = abs(p - a), abs(p - b), abs(p - c)
                    predictor = a if da <= db and da <= dc else b if db <= dc else c
                row[x] = (row[x] + predictor) & 255
        if bpp == 3:
            pixels.extend(row)
        else:
            pixels.extend(bytes((v * row[x + 3] + 255 * (255 - row[x + 3])) // 255
                                for x in range(0, stride, 4) for v in row[x:x + 3]))
        previous = row
    return width, height, pixels


def artifact(folder, filename, raw):
    path = folder / filename
    if path.exists():
        raise ValueError("refuse evidence overwrite: " + filename)
    path.write_bytes(raw)
    return {"file": filename, "sha256": digest(raw), "bytes": len(raw)}


def slices_for(box, view_height):
    first = math.floor(max(0, box[1]) / view_height) + 1
    count = max(1, math.ceil((box[1] + box[3]) / view_height) - (first - 1))
    return list(range(first, first + count))


def bracket_changes(snapshot, view, kind):
    """Text items that changed between the observations taken just before and after a screenshot.

    Only items in the picture count: overlapping the visible column (for the first screen, also its
    rows) and painted in at least one state. Image source swaps are not text and are ignored.
    Material = wording, presence, visibility or slice changed (the text layer may not match the image).
    """
    if "after" not in snapshot:
        return {"bracketed": False, "changed": [], "material": [], "ignored_offscreen_or_hidden": 0,
                "document_height_changed": False}
    width, height = view["width"], view["height"]
    before = {n["id"]: n for n in snapshot.get("before", {}).get("text_nodes", [])}
    after = {n["id"]: n for n in snapshot["after"].get("text_nodes", [])}

    def in_picture(n):
        if not n or n.get("visibility") == "hidden":
            return False
        x, y, w, h = n["bbox"]
        return x < width and x + w > 0 and (kind != "first_screen" or (y < height and y + h > 0))

    def where(n):
        return slices_for(n["bbox"], height) if kind == "full_page" else [1]
    changed, material, ignored = [], [], 0
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key), after.get(key)
        if b and a and all(b.get(k) == a.get(k) for k in ("text", "bbox", "visibility")):
            continue
        if not (in_picture(b) or in_picture(a)):
            ignored += 1
            continue
        changed.append(key)
        if not b or not a or b["text"] != a["text"] or b.get("visibility") != a.get("visibility") or where(b) != where(a):
            material.append(key)
    height_changed = kind == "full_page" and snapshot.get("before", {}).get("document_height") != snapshot["after"].get("document_height")
    return {"bracketed": True, "changed": changed, "material": material, "ignored_offscreen_or_hidden": ignored,
            "document_height_changed": height_changed}


def export_nodes(snapshot, kind, view, changes):
    width, height = view["width"], view["height"]
    nodes = snapshot.get("text", snapshot.get("before", {}).get("text_nodes", []))
    if kind == "first_screen":
        nodes = [{**n, "slice_index": 1} for n in nodes if n["bbox"][1] < height and n["bbox"][1] + n["bbox"][3] > 0]
    changed = set(changes["changed"])
    return [{**n, "in_column": n["bbox"][0] < width and n["bbox"][0] + n["bbox"][2] > 0,
             "past_right_edge": n["bbox"][0] + n["bbox"][2] > width,
             "changed_during_capture": n["id"] in changed} for n in nodes]


def store_capture_record(folder, view, record):
    name = view["name"]
    for key in ("first_screen", "full_page"):
        snapshot = record.get(key)
        if not snapshot:
            continue
        b64 = snapshot.pop("png_base64", None)
        if b64:
            raw = base64.b64decode(b64, validate=True)
            snapshot["image"] = artifact(folder, f"{name}.{key}.png", raw)
            width, height, pixels = decode_png(raw)
            snapshot["dimensions"] = [width, height]
            if key == "full_page":
                snapshot["slices"] = []
                for i, y in enumerate(range(0, height, view["height"]), 1):
                    h = min(view["height"], height - y)
                    tile = encode_png(width, h, pixels[y * width * 3:(y + h) * width * 3])
                    snapshot["slices"].append({"index": i, "y": y, "height": h,
                        **artifact(folder, f"{name}.slice-{i:03}.png", tile)})
        changes = bracket_changes(snapshot, view, key)
        nodes = export_nodes(snapshot, key, view, changes)
        text = {"schema": "design.positioned_text.v2", "kind": key, "viewport": view, "text_nodes": nodes,
                "image_sha256": snapshot.get("image", {}).get("sha256"), "coherent": snapshot.get("coherent", False),
                "bracket": changes,
                "iframes": snapshot.get("before", {}).get("iframes", []),
                "frame_errors": snapshot.get("before", {}).get("frame_errors", [])}
        snapshot["text_artifact"] = artifact(folder, f"{name}.{key}.text.json", json.dumps(text, indent=2, ensure_ascii=False).encode())
    return record


async def capture(workspace, preflight_path, client_factory=BrowserClient):
    path, pre = read_receipt(preflight_path, workspace, "preflight")
    request = pre["request"]
    if request != request_config(request["url"], request["ready_selector"], request["viewports"], request["timeout_ms"], request["browser_url"]) or digest(canonical(request)) != pre["request_sha256"]:
        raise ValueError("preflight request binding invalid")
    output = path.parent / "capture.json"
    if output.exists():
        raise ValueError("capture already recorded; use a new preflight for a new run")
    result = {"schema": SCHEMA, "phase": "capture", "capture_id": pre["capture_id"], "created_at": now(),
              "request": request, "request_sha256": pre["request_sha256"], "status": "failed", "views": [],
              "preflight": {"file": str(path), "sha256": digest(path.read_bytes())}}
    try:
        async with client_factory(request["browser_url"]) as client:
            for view in request["viewports"]:
                record = await client.call(capture_code(request, view))
                result["views"].append(await asyncio.to_thread(store_capture_record, path.parent, view, record))
        result["status"] = "completed"  # Collection completed, NOT a usability assertion.
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    save(output, result)
    return output, result


def read_artifact(folder, entry):
    filename = entry["file"]
    if pathlib.Path(filename).name != filename:
        raise ValueError("artifact must be a local filename")
    path = inside(folder / filename, folder)
    raw = path.read_bytes()
    if len(raw) != entry.get("bytes") or digest(raw) != entry.get("sha256"):
        raise ValueError("artifact bytes/hash mismatch")
    return raw


def incomplete_measurements(width, height, pixels, observation, viewport_height):
    """Transparent measured heuristics, not a semantic judge. Thresholds calibrated in #150."""
    metrics = observation.get("metrics", {})
    reasons, bands = [], []
    # Only images a visitor could see in this picture: box overlaps x 0..width and y 0..height
    # (the PNG is the viewport's width; the first screen is one viewport high).
    broken = [i for i in observation.get("images", [])
              if i["bbox"][0] < width and i["bbox"][0] + i["bbox"][2] > 0 and i["bbox"][1] < height
              and i["bbox"][1] + i["bbox"][3] > 0 and (not i.get("complete") or not i.get("natural_width"))]
    if broken:
        reasons.append(f"{len(broken)} rendered images failed or remained unloaded")
    if metrics.get("body_chars", 0) < 30 and metrics.get("graphic_area", 0) < width * viewport_height * .03:
        reasons.append("implausibly little homepage content: under 30 characters and under 3% graphic area")
    if metrics.get("h1_count") == 0 and (metrics.get("main_chars") or 0) < 80:
        reasons.append("homepage shell: no sampled-visible primary heading and fewer than 80 main characters")
    # Dominant quantized colour at 96 interior samples. Only large interior bands count;
    # edge gutters and trailing space do not. A one-screen, one-heading section is exempt.
    flow = [n["bbox"] for n in observation.get("text_nodes", []) if not n.get("positioned_overlay") and n.get("visibility") != "hidden"]
    content_top = min((b[1] for b in flow), default=0)
    content_bottom = max((b[1] + b[3] for b in flow), default=height)
    step = max(1, width // 96)
    run = None
    for y in range(height + 1):
        uniform = False
        if y < height:
            counts = {}
            for x in range(int(width * .08), max(int(width * .08) + 1, int(width * .92)), step):
                p = (y * width + x) * 3
                color = tuple(v // 8 for v in pixels[p:p + 3])
                counts[color] = counts.get(color, 0) + 1
            uniform = max(counts.values(), default=0) / max(1, sum(counts.values())) >= .98
        if uniform and run is None:
            run = y
        if not uniform and run is not None:
            length = y - run
            hero = any(max(0, min(y, b) - max(run, a)) >= length * .8 for a, b in metrics.get("hero_ranges", []))
            if length >= viewport_height * .60 and run > content_top + 10 and y < content_bottom - 5 and not hero:
                bands.append({"y": run, "height": length, "slice_index": run // viewport_height + 1})
            run = None
    if bands:
        reasons.append(f"{len(bands)} near-uniform interior blank bands at least 60% of a viewport")
    return {"reasons": reasons, "blank_bands": bands, "unloaded_images": broken, "metrics": metrics,
            "thresholds": {"image_scope": "image box overlaps the picture", "uniform_row_dominance": .98, "blank_band_viewport_fraction": .60,
                           "small_body_chars": 30, "small_graphic_area_fraction": .03, "small_main_chars": 80}}


QUEUE_PAGE = r"sit tight|hang tight|automatically refresh|waiting room|you are (?:now )?in (?:a |the )?(?:queue|line)"


def page_status(record, measurements, changes, first=False):
    reasons = []
    if record.get("error"):
        return "not usable", [record["error"]]
    status = record.get("http_status")
    if type(status) is not int or not 200 <= status < 400:
        return "not usable", [f"HTTP {status}"]
    snapshot = record.get("first_screen" if first else "full_page", {})
    observation = snapshot.get("before", {})
    visible = " ".join(n["text"] for n in observation.get("text_nodes", []) if n.get("visibility") == "visible").lower()
    title = observation.get("title", "").lower()
    blocked = (r"verify (?:you are|you're) human|checking your browser|access denied|request blocked|"
               r"unusual traffic|enable javascript and cookies to continue|security verification|"
               r"captcha|just a moment|service unavailable|this site can.t be reached")
    if re.search(blocked, title) or (len(visible) < 1800 and re.search(blocked, visible)):
        return "not usable", ["security/robot/error page; no bypass attempted"]
    if (re.search(QUEUE_PAGE, title) or (len(visible) < 2500 and re.search(QUEUE_PAGE, visible)) or
            (len(visible) < 1000 and re.search(r"coming soon|under construction|maintenance mode|log in to continue|sign in to continue", visible))):
        return "not usable", ["holding page or login wall"]
    if not snapshot.get("image") or snapshot.get("diagnostic"):
        return "not usable", ["diagnostic or missing image"]
    reasons.extend(measurements["reasons"])
    if not first and record.get("cut_off"):
        reasons.append("cut_off: document reached the approved 25-screen endless-feed stop")
    if reasons:
        return "incomplete", reasons
    uncertainty = []
    if observation.get("frame_errors"):
        uncertainty.append("some iframe text could not be exported; frame errors recorded")
    moved = []
    if changes["material"]:
        moved.append(f"{len(changes['material'])} text items in the picture changed wording, visibility or slice "
                     "during the screenshot (moving content; flagged changed_during_capture)")
    if changes["document_height_changed"]:
        moved.append("page height changed during the screenshot")
    if moved:
        uncertainty.append("; ".join(moved))
    if not first:
        if record.get("cookie", {}).get("action") in ("cookie window left open", "reject clicked; cookie window still open"):
            uncertainty.append(record["cookie"]["action"])
        if any(not s.get("fonts_loaded") or not s.get("network", {}).get("quiet") for s in record.get("scroll_steps", [])):
            uncertainty.append("fonts or network did not settle at every scroll position")
    if uncertainty:
        return "uncertain", uncertainty
    return "usable", []


def verify_view(folder, record, expected, request):
    if record.get("viewport") != expected:
        raise ValueError("viewport record mismatch")
    if record.get("csp_bypass") is not False or record.get("context_closed") is not True or record.get("device_scale_factor") != 1:
        raise ValueError("security/isolation/cleanup contract failed")
    for click in record.get("cookie", {}).get("clicks", []):
        if click.get("label") not in REJECT_LABELS or re.search(r"accept|agree|allow|\bok\b", click.get("label", "")):
            raise ValueError("unsafe consent click")
        if click.get("clicked_at", "") < record.get("first_screen", {}).get("captured_at", ""):
            raise ValueError("consent click preceded as-is screenshot")
    result = {"name": expected["name"], "cookie": record.get("cookie"), "cut_off": record.get("cut_off", False),
              "requested_url": request["url"], "final_url": record.get("final_url"),
              "horizontal_overflow": record.get("horizontal_overflow"), "views": {}}
    if record.get("final_url"):
        public_url(record["final_url"])
    for kind in ("first_screen", "full_page"):
        snapshot = record.get(kind, {})
        if not snapshot.get("image"):
            result["views"][kind] = {"status": "not usable", "reasons": [record.get("error", "no image")]}
            continue
        width, height, pixels = decode_png(read_artifact(folder, snapshot["image"]))
        if width != expected["width"] or (kind == "first_screen" and height != expected["height"]):
            raise ValueError("PNG dimensions mismatch")
        text = json.loads(read_artifact(folder, snapshot["text_artifact"]))
        if text.get("image_sha256") != snapshot["image"]["sha256"] or text.get("viewport") != expected or text.get("kind") != kind:
            raise ValueError("text/image/viewport binding mismatch")
        changes = bracket_changes(snapshot, expected, kind)
        if text.get("bracket") != changes:
            raise ValueError("screenshot bracket record does not match source observations")
        if text["text_nodes"] != export_nodes(snapshot, kind, expected, changes):
            raise ValueError("positioned text does not match source observation")
        if kind == "full_page":
            y, tiles = 0, bytearray()
            for i, tile in enumerate(snapshot.get("slices", []), 1):
                tw, th, tp = decode_png(read_artifact(folder, tile))
                if (tile["index"], tile["y"], tw, th) != (i, y, width, min(expected["height"], height - y)):
                    raise ValueError("slice geometry/gap/overlap mismatch")
                y += th
                tiles.extend(tp)
            if y != height or tiles != pixels:
                raise ValueError("slices do not rejoin byte-exactly to full RGB image")
        for node in text["text_nodes"]:
            box = node["bbox"]
            if len(box) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in box):
                raise ValueError("invalid text bbox")
            index = 1 if kind == "first_screen" else math.floor(max(0, box[1]) / expected["height"]) + 1
            if node.get("slice_index") != index:
                raise ValueError("text slice index does not match bbox")
            if kind == "full_page":
                count = max(1, math.ceil((box[1] + box[3]) / expected["height"]) - math.floor(max(0, box[1]) / expected["height"]))
                if node.get("slice_indices") != list(range(index, index + count)):
                    raise ValueError("text intersecting-slice indices do not match bbox")
        measured = incomplete_measurements(width, height, pixels, snapshot.get("before", {}), expected["height"])
        status, reasons = page_status(record, measured, changes, first=kind == "first_screen")
        notes = []
        moved_only = len(changes["changed"]) - len(changes["material"])
        if moved_only:
            notes.append(f"{moved_only} visible text items moved within the same slice during the screenshot")
        if changes["ignored_offscreen_or_hidden"]:
            notes.append(f"{changes['ignored_offscreen_or_hidden']} text items changed outside the picture (ignored)")
        overflow = record.get("horizontal_overflow") or {}
        if overflow.get("overflow_px"):
            notes.append(f"page is {overflow['overflow_px']} px wider than the viewport; image shows the visible "
                         "column only, text past the right edge is marked past_right_edge")
        result["views"][kind] = {"status": status, "reasons": reasons, "notes": notes, "image": snapshot["image"],
            "text": snapshot["text_artifact"], "dimensions": [width, height], "measurements": measured,
            "slices": snapshot.get("slices", []), "slices_pixel_exact": kind == "full_page"}
    result["status"] = result["views"]["full_page"]["status"]
    result["reasons"] = result["views"]["full_page"]["reasons"]
    result["usable"] = result["status"] == "usable"
    return result


def verify(workspace, capture_path):
    path, previous = read_receipt(capture_path, workspace, "capture")
    output = path.parent / "verification.json"
    if output.exists():
        raise ValueError("verification already recorded; do not overwrite evidence")
    report = {"schema": SCHEMA, "phase": "verify", "capture_id": previous["capture_id"], "created_at": now(),
              "status": "failed", "verified": False, "captures": [], "errors": [],
              "capture_sha256": digest(path.read_bytes()), "limitation": LIMITATION}
    try:
        pre_path, pre = read_receipt(previous["preflight"]["file"], workspace, "preflight")
        if pre_path.parent != path.parent or digest(pre_path.read_bytes()) != previous["preflight"]["sha256"]:
            raise ValueError("preflight receipt changed or wrong capture")
        request = pre["request"]
        if previous["capture_id"] != pre["capture_id"] or previous["request"] != request or previous["request_sha256"] != digest(canonical(request)):
            raise ValueError("capture/request binding mismatch")
        if len(previous["views"]) != len(request["viewports"]):
            raise ValueError("missing/extra viewport captures")
        for record, view in zip(previous["views"], request["viewports"], strict=True):
            try:
                report["captures"].append(verify_view(path.parent, record, view, request))
            except (ValueError, OSError, KeyError, TypeError, zlib.error) as error:
                report["errors"].append(f"{view['name']}: {error}")
        if not report["errors"]:
            report["status"], report["verified"] = "passed", True
    except (ValueError, OSError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    save(output, report)
    return output, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "capture", "verify"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--url")
    parser.add_argument("--ready-selector", default="body")
    parser.add_argument("--viewports", default=json.dumps(DEFAULT_VIEWS))
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--browser", default=BROWSER)
    parser.add_argument("--receipt")
    args = parser.parse_args()
    try:
        workspace = workspace_path(args.workspace)
        if args.phase == "preflight":
            request = request_config(args.url, args.ready_selector, json.loads(args.viewports), args.timeout_ms, args.browser)
            path, result = asyncio.run(preflight(workspace, request))
        elif args.phase == "capture":
            path, result = asyncio.run(capture(workspace, args.receipt))
        else:
            path, result = verify(workspace, args.receipt)
        summary = {"ok": result["status"] in ("passed", "completed"), "verified": result.get("verified", False),
                   "verdict": result["status"], "phase": args.phase, "receipt_path": str(path), "capture_id": result["capture_id"],
                   "captures": result.get("captures", []), "errors": result.get("errors", [result["error"]] if result.get("error") else [])}
    except Exception as error:
        summary = {"ok": False, "phase": args.phase, "errors": [f"{type(error).__name__}: {error}"]}
    print(json.dumps(summary), flush=True)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
