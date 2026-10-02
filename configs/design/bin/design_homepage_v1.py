#!/usr/bin/env python3
"""Design-owned, bounded, template-driven Penpot homepage workflow (v1).

Source/API state and exported artifacts only; never log credentials. Stage receipts
make repeat/resume idempotent. Real workflows require direction + final human gates.
Fictional pilot selection is provisional. No HTML canvas substitute.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import http.cookiejar
import json
import math
import os
import shutil
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import penpot_homepage_source as p

VERSION = 1
DIRECTIONS = ("product-led", "task-led", "explanation-led")
WIDTHS = (390, 768, 1440)
PROJECT = "d6e78769-4453-804d-8c55-fd6b40134048"
PALETTE = {"paper": "#FAF8F3", "ink": "#1E3430", "pine": "#24594B",
           "muted": "#51645C", "sage": "#E5EEE7", "clay": "#AB442A",
           "white": "#FFFFFF", "border": "#72867B", "disabled": "#D4DAD5"}
TYPO = {"display-phone": (36, "600"), "display-tablet": (44, "600"),
        "display-desktop": (56, "600"), "section": (28, "600"),
        "label": (20, "600"), "body": (16, "400"), "lead": (18, "400"),
        "button": (16, "600")}
DEFAULT = {
    "product": "Morrow Rooms", "fictional": True,
    "audience": "A first-time small-team organizer choosing a room and checking example booking terms.",
    "headline": "A room that fits.\nA meeting that flows.",
    "subhead": "Find the right space for your small team. Compare room size, equipment and example booking terms before you choose.",
    "cta": "Explore demo rooms", "disclosure": "Fictional demo — no bookings or payments.",
    "rooms": [
        {"name": "Cedar", "capacity": "4 people", "equipment": "Display + whiteboard", "price": "Example: $18 / hour"},
        {"name": "Oak", "capacity": "8 people", "equipment": "Video setup + whiteboard", "price": "Example: $30 / hour"},
        {"name": "Atlas", "capacity": "12 people", "equipment": "Display + breakout space", "price": "Example: $45 / hour"}],
    "steps": [{"title": "Set your meeting needs", "body": "Start with people, purpose and equipment."},
              {"title": "Compare the details", "body": "See capacity and facilities together, without guesswork."},
              {"title": "Check the terms", "body": "Review the duration and cancellation rules before a real booking."}],
    "terms": "Illustrative terms only: one-hour minimum; cancel at least 24 hours ahead. A real venue's current terms must be checked before booking.",
    "faq": [{"q": "Is this a live service?", "a": "No. Morrow Rooms is a fictional design study."},
            {"q": "Do I need an account to explore?", "a": "No. The proposed demo path needs no account."},
            {"q": "Can I make a booking here?", "a": "No. This study cannot take bookings or payments."}],
}
RUNTIME_ONLY = ["keyboard activation/order", "focus visibility/obscuration", "ARIA and screen-reader output",
                "400% zoom/320px reflow", "text-spacing overrides", "motion/timing",
                "actual demo navigation", "live availability/booking"]


def now():
    return datetime.now(UTC).isoformat()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def load(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def brief_contract(value):
    if not isinstance(value, dict) or not isinstance(value.get("fictional"), bool):
        raise ValueError("brief needs explicit fictional boolean")
    for key in ("product", "audience", "headline", "subhead", "cta", "disclosure", "terms"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"brief needs {key}")
    if len(value["headline"]) > 85 or len(value["cta"]) > 24 or len(value["product"]) > 24:
        raise ValueError("v1 copy exceeds its bounded template; adapt brief, do not silently clip")
    for key in ("rooms", "steps", "faq"):
        if len(value.get(key, [])) != 3:
            raise ValueError(f"v1 needs exactly three {key}")
    if value["fictional"] and "demo" not in value["cta"].lower():
        raise ValueError("fictional CTA must disclose demo")
    return value


def safe_gate(raw):
    # gate.response is free text, not the rendered Q/A prose. Only a JSON decision is accepted.
    try:
        value = json.loads(raw or "{}")
    except ValueError as exc:
        raise ValueError("gate response must be a saved JSON decision") from exc
    if not isinstance(value, dict):
        raise ValueError("gate response must be an object")
    return value


def direction_contract(brief, decision, pilot):
    if pilot and not brief["fictional"]:
        raise ValueError("pilot workflow refuses real deliverables")
    if decision.get("direction") not in DIRECTIONS:
        raise ValueError("direction must be product-led, task-led or explanation-led")
    if not brief["fictional"] and decision.get("approval") != "owner-direction":
        raise ValueError("real work requires owner direction gate")
    return {**decision, "approval": "provisional-fictional" if brief["fictional"] else "owner-direction",
            "owner_taste_approved": False}


def budget_contract(value, round_number):
    if not 1 <= round_number <= 3:
        raise ValueError("maximum three review rounds")
    day = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    if value.get("pacific_day") != day:
        raise ValueError("budget reservation expired; reserve current Pacific day")
    needed = ("reserve_usd", "day_spent_usd", "trial_spent_usd", "trial_envelope_usd")
    if any(not isinstance(value.get(k), (int, float)) or value[k] < 0 or not math.isfinite(value[k]) for k in needed):
        raise ValueError("budget fields must be finite non-negative numbers")
    if value["reserve_usd"] <= 0 or value["day_spent_usd"] + value["reserve_usd"] > 10:
        raise ValueError("Pacific-day $10 guard exceeded")
    if value["trial_envelope_usd"] > 10 or value["trial_spent_usd"] + value["reserve_usd"] > value["trial_envelope_usd"]:
        raise ValueError("full trial envelope exceeded; owner approval required")
    if not value.get("subscription_checked") or not value.get("one_design_experiment"):
        raise ValueError("subscription and duplicate experiment checks required")
    return value


class Penpot:
    def __init__(self):
        self.base = os.environ.get("PENPOT_URL", "").rstrip("/")
        if self.base != "https://spark.tailbb5055.ts.net:8790":
            raise ValueError("only the authorized Penpot host is allowed")
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.profile = None

    def request(self, url, body=None, ctype="application/json", timeout=90):
        # Export URI is not permitted to exfiltrate the authenticated session elsewhere.
        if not url.startswith(self.base + "/"):
            raise ValueError("Penpot URL left authorized host")
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Accept": "application/json", "Content-Type": ctype})
        try:
            with self.http.open(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Penpot HTTP {exc.code} (response suppressed)") from None
        except urllib.error.URLError:
            raise RuntimeError("Penpot transport unavailable (credentials suppressed)") from None

    def rpc(self, method, args=None):
        data = self.request(self.base + "/api/main/methods/" + method, args or {})
        return p.kebab(json.loads(data)) if data else None

    @staticmethod
    def password():
        value = os.getenv("PENPOT_AGENT_PASSWORD", "")
        if value:
            return value
        # Script Bash removes *_PASSWORD. The owner explicitly granted this
        # service login to run containers; read ONLY that key from this same
        # container's bootstrap environment, never a host/another run or output.
        box = os.getenv("TEMPER_RUN_CONTAINER", "")
        prefix = "temper-run-"
        try:
            if not box.startswith(prefix):
                return ""
            import uuid
            if str(uuid.UUID(box[len(prefix):])) != box[len(prefix):]:
                return ""
            raw = Path("/proc/1/environ").read_bytes()
            allowed = {"TEMPER_RUN_CONTAINER", "PENPOT_AGENT_EMAIL", "PENPOT_AGENT_PASSWORD"}
            boot = {}
            for item in raw.split(b"\0"):
                key, sep, data = item.partition(b"=")
                name = key.decode("ascii", errors="ignore")
                if sep and name in allowed:
                    boot[name] = data.decode("utf-8")
            if boot.get("TEMPER_RUN_CONTAINER") != box or boot.get("PENPOT_AGENT_EMAIL") != "design-agent@spark.local":
                return ""
            return boot.get("PENPOT_AGENT_PASSWORD", "")
        except (OSError, UnicodeError, ValueError):
            return ""

    def login(self):
        email = os.getenv("PENPOT_AGENT_EMAIL", "")
        password = self.password()
        if email != "design-agent@spark.local" or not password:
            raise ValueError("authorized Penpot login unavailable; never substitute a canvas")
        self.profile = self.rpc("login-with-password", {"email": email, "password": password})
        if self.profile.get("email") != email:
            raise ValueError("authenticated profile differs from design-agent")
        return self.profile

    def get(self, fid):
        return self.rpc("get-file", {"id": fid})

    def create(self, name):
        f = self.rpc("create-file", {"name": name, "project-id": PROJECT})
        return self.get(f["id"])

    def update(self, fid, changes):
        f = self.get(fid)
        self.rpc("update-file", {"id": fid, "session-id": p.nid(), "revn": f["revn"],
                                 "vern": f.get("vern", 0), "changes": changes})
        return self.get(fid)

    def export(self, state, board, kind, destination):
        params = {":cmd": ":export-shapes", ":profile-id": "uuid:" + self.profile["id"], ":wait": True,
                  ":exports": [{":file-id": "uuid:" + state["file_id"], ":page-id": "uuid:" + state["page_id"],
                                ":object-id": "uuid:" + board["id"], ":type": ":" + kind, ":suffix": "",
                                ":scale": 1, ":name": board["name"]}]}
        raw = self.request(self.base + "/api/export", p.transit(params), "application/transit+json", 240)
        result = p.untransit(json.loads(raw))
        uri = result.get("uri", "")
        # Exporter returns its public authenticated-resource URI on this same host.
        if uri.startswith("/"):
            uri = self.base + uri
        data = self.request(uri, timeout=120)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        if kind == "png":
            if data[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError("export is not PNG")
            w, h = struct.unpack(">II", data[16:24])
            if (w, h) != (board["width"], board["height"]):
                raise ValueError("PNG export dimensions differ from editable source")
        return {"path": str(destination), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def font_names(data):
    """Read the installed TTF's license/provenance strings without extra packages."""
    count = struct.unpack_from(">H", data, 4)[0]
    for i in range(count):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + 16 * i)
        if tag != b"name":
            continue
        _, records, strings = struct.unpack_from(">HHH", data, offset)
        values = {}
        for j in range(records):
            platform, _, _, name_id, length, start = struct.unpack_from(">HHHHHH", data, offset + 6 + 12 * j)
            if name_id not in (0, 1, 5, 13, 14):
                continue
            value = data[offset + strings + start:offset + strings + start + length]
            values[str(name_id)] = value.decode("utf-16-be" if platform in (0, 3) else "latin-1", errors="replace")
        return values
    raise ValueError("installed font has no name/license table")


def assets(client, destination):
    destination.mkdir(parents=True, exist_ok=True)
    evidence = []
    for variant in ("regular", "semibold"):
        name = f"sourcesanspro-{variant}.ttf"
        data = client.request(client.base + "/fonts/" + name)
        names = font_names(data)
        if "Open Font License" not in " ".join(names.values()):
            raise ValueError("installed font license cannot be verified")
        (destination / name).write_bytes(data)
        evidence.append({"file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "name_table": names,
                         "origin": client.base + "/fonts/" + name})
    license_text = evidence[0]["name_table"].get("13", "")
    if "SIL OPEN FONT LICENSE Version 1.1" not in license_text:
        raise ValueError("installed font's full license document could not be verified")
    (destination / "Source-Sans-OFL.txt").write_text(license_text)
    save(destination / "licenses.json", {"font_family": "Source Sans Pro", "installed_fonts": evidence,
         "license_document": "embedded name-ID 13 of installed regular TTF",
         "license": "SIL Open Font License 1.1", "original_vectors": True,
         "note": "Actual installed version/copyright and full OFL copied directly from the installed font name table. No new download source, modification or purchase."})
    return evidence


def wrapped(value, width, size):
    # Conservative initial box sizing; actual fit still requires editor/export inspection.
    lines = []
    limit = max(8, int(width / (size * .52)))
    for paragraph in value.split("\n"):
        current = ""
        for word in paragraph.split():
            if current and len(current + " " + word) > limit:
                lines.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        lines.append(current)
    return lines


class Canvas:
    def __init__(self, fid, page, wire=False):
        self.fid, self.page, self.wire = fid, page, wire
        colours = PALETTE if not wire else {**PALETTE, "paper": "#FFFFFF", "ink": "#202020",
            "pine": "#333333", "muted": "#505050", "sage": "#ECECEC", "clay": "#454545",
            "border": "#808080", "disabled": "#CCCCCC"}
        self.colors = {k: p.color(k, v) for k, v in colours.items()}
        self.typos = {k: p.typography(k, *v) for k, v in TYPO.items()}
        self.objects, self.changes, self.boards, self.metrics, self.components = [], [], [], [], []
        self.changes += [{"type": "add-color", "color": v} for v in self.colors.values()]
        self.changes += [{"type": "add-typography", "typography": v} for v in self.typos.values()]
        self.library_x = 4100
        self.library_y = 0

    def put(self, obj):
        self.objects.append(obj)
        self.changes.append(p.add_obj(obj, self.page))
        return obj

    def rect(self, name, board, x, y, w, h, color="sage", radius=12, kind="rect"):
        return self.put(p.shape(kind, name, board["id"], board["id"], x, y, w, h,
                                p.fill(self.colors[color], self.fid), radius))

    def board(self, name, x, y, w, h):
        b = self.put(p.shape("frame", name, p.ROOT, p.ROOT, x, y, w, h,
                             p.fill(self.colors["paper"], self.fid)))
        self.boards.append(b)
        return b

    def text(self, name, value, board, x, y, w, style="body", color="ink", bg="paper", align="left"):
        size = float(self.typos[style]["font-size"])
        lines = wrapped(value, w, size)
        h = math.ceil(len(lines) * size * 1.35 + 6)
        obj = p.shape("text", name, board["id"], board["id"], x, y, w, h, [])
        obj.update({"content": p.content(lines, self.typos[style], self.colors[color], self.fid, align),
                    "grow-type": "fixed", "position-data": None})
        self.put(obj)
        self.metrics.append({"id": obj["id"], "board": board["name"], "kind": "text", "name": name,
                             "text": value, "size": size, "fg": self.colors[color]["color"],
                             "bg": self.colors[bg]["color"], "lines": len(lines), "x": x, "y": y, "w": w, "h": h})
        return h

    def component(self, name, width, height, build):
        x, y = self.library_x, self.library_y
        main = p.shape("frame", name, p.ROOT, p.ROOT, x, y, width, height,
                       p.fill(self.colors["paper"], self.fid), 12)
        cid = p.nid()
        p.mark_main(main, cid, self.fid)
        start = len(self.objects)
        self.put(main)
        build(main, x, y)
        members = copy.deepcopy(self.objects[start:])
        self.changes.append({"type": "add-component", "id": cid, "name": name, "path": "Quiet Atlas",
                             "main-instance-id": main["id"], "main-instance-page": self.page})
        result = {"id": cid, "name": name, "root": main["id"], "objects": members,
                  "width": width, "height": height}
        self.components.append(result)
        self.library_y += height + 48
        return result

    def instance(self, component, board, x, y, action=False):
        old = component["objects"]
        mapping = {s["id"]: p.nid() for s in old}
        dx, dy = x - old[0]["x"], y - old[0]["y"]
        for i, src in enumerate(old):
            obj = copy.deepcopy(src)
            obj.update({"id": mapping[src["id"]], "shape-ref": src["id"],
                        **p.geometry(src["x"] + dx, src["y"] + dy, src["width"], src["height"])})
            obj.pop("main-instance", None)
            obj["parent-id"] = board["id"] if i == 0 else mapping[src["parent-id"]]
            obj["frame-id"] = board["id"] if i == 0 else mapping[src["frame-id"]]
            if i == 0:
                p.mark_instance(obj, component["id"], self.fid, component["root"])
            self.put(obj)
            if obj["type"] == "text":
                metric = next(m for m in self.metrics if m.get("id") == src["id"])
                self.metrics.append({**metric, "id": obj["id"], "board": board["name"], "x": obj["x"], "y": obj["y"]})
        if action:
            self.metrics.append({"id": mapping[old[0]["id"]], "board": board["name"], "kind": "target",
                                 "name": component["name"], "x": x, "y": y,
                                 "w": component["width"], "h": component["height"]})
        return mapping[old[0]["id"]]

    def button(self, label, state="default"):
        color = "disabled" if state == "disabled" else ("ink" if state == "pressed" else "pine")
        def build(b, x, y):
            b["fills"] = p.fill(self.colors[color], self.fid)
            # put() stores the object by reference; add-obj contains the same object.
            if state == "focus":
                b["strokes"] = [{"stroke-color": PALETTE["clay"], "stroke-opacity": 1,
                                  "stroke-width": 3, "stroke-style": "solid", "stroke-alignment": "outside"}]
            self.text("Label — live text", "Opening demo…" if state == "loading" else label,
                      b, x + 8, y + 10, 192, "button", "muted" if state == "disabled" else "white", color, "center")
        return self.component("Primary / " + state, 208, 48, build)

    def room(self, room, width):
        def build(b, x, y):
            self.rect("Room-card surface", b, x, y, width, 244, "sage")
            self.rect("Original vector room plan", b, x + 20, y + 20, 64, 44, "border", 4)
            self.rect("Meeting table", b, x + 32, y + 30, 40, 24, "paper", 4)
            self.text("Room name", room["name"], b, x + 20, y + 82, width - 40, "label", bg="sage")
            self.text("Capacity", room["capacity"], b, x + 20, y + 116, width - 40, bg="sage")
            self.text("Equipment", room["equipment"], b, x + 20, y + 148, width - 40, bg="sage")
            self.text("Illustrative price", room["price"], b, x + 20, y + 210, width - 40, "body", "muted", "sage")
        return self.component(f"Room card / {room['name']} / {width}", width, 244, build)

    def disclosure(self, text, width):
        def build(b, x, y):
            self.text("Demo disclosure", text, b, x, y, width, color="muted")
        return self.component("Disclosure / " + str(width), width, 52, build)

    def homepage(self, brief, direction, width, x=0, y=0):
        mobile = width == 390
        tablet = width == 768
        pad = 24 if mobile else (48 if tablet else 64)
        gap = 24 if mobile else 32
        iw = width - pad * 2
        b = self.board(("Wireframe " if self.wire else "Homepage ") + f"{direction} / {width}", x, y, width, 4000)
        left = x + pad
        self.text("Brand", brief["product"], b, left, y + 24, 200, "label")
        if mobile:
            self.text("Demo badge", "Fictional demo", b, left + 210, y + 28, iw - 210, "body", "muted")
        else:
            self.text("Navigation: How it works", "How it works", b, x + width - pad - 300, y + 26, 140, "body")
            self.text("Navigation: Example terms", "Example terms", b, x + width - pad - 148, y + 26, 148, "body")
            for name, tx, tw in (("How it works anchor", x + width - pad - 300, 140), ("Example terms anchor", x + width - pad - 148, 148)):
                self.metrics.append({"board": b["name"], "kind": "target", "name": name, "x": tx, "y": y + 18, "w": tw, "h": 44})
        yy = y + 112
        style = "display-phone" if mobile else ("display-tablet" if tablet else "display-desktop")
        hero_w = iw if mobile or tablet or direction == "explanation-led" else int(iw * .52)
        h = self.text("H1 — product promise", brief["headline"], b, left, yy, hero_w, style)
        h += 20 + self.text("Value proposition", brief["subhead"], b, left, yy + h + 20, hero_w, "body" if mobile else "lead")
        button = self.button(brief["cta"])
        self.instance(button, b, left, yy + h + 24, action=True)
        disclosure = self.disclosure(brief["disclosure"], hero_w)
        self.instance(disclosure, b, left, yy + h + 84)
        hero_end = yy + h + 146
        if direction != "explanation-led" and not mobile and not tablet:
            px = left + hero_w + 40
            pw = iw - hero_w - 40
            ph = 270 if tablet else 300
            self.rect("Product illustration panel", b, px, yy, pw, ph, "sage", 20)
            self.text("Illustration label", "Sample floor plan", b, px + 24, yy + 20, pw - 48, "label", bg="sage")
            self.text("Illustration honesty", "Illustration only · not live availability", b, px + 24, yy + 58, pw - 48, color="muted", bg="sage")
            for i, name in enumerate(("Cedar", "Oak", "Atlas")):
                rw = (pw - 72) / 3
                rx = px + 24 + i * (rw + 12)
                self.rect("Floor-plan room " + name, b, rx, yy + 130, rw, 100, "pine", 6)
                self.rect("Original vector table", b, rx + 12, yy + 148, rw - 24, 40, "paper", 4)
                self.text("Plan label " + name, name, b, rx + 4, yy + 194, rw - 8, "body", "white", "pine", "center")
            hero_end = max(hero_end, yy + ph + 40)
        yy = hero_end + 32

        def task_summary(pos):
            panel_h = 204 if mobile else (176 if tablet else 160)
            self.rect("Meeting needs illustration", b, left, pos, iw, panel_h, "sage", 16)
            self.text("Needs heading", "Plan your meeting", b, left + 24, pos + 20, iw - 48, "label", bg="sage")
            text = "Team size: 2–12 people\nEquipment: display, video or whiteboard" if mobile else "Team size: 2–12 people  /  Equipment: display, video or whiteboard"
            self.text("Visible needs summary", text, b, left + 24, pos + 60, iw - 48, bg="sage")
            self.text("Needs illustration disclosure", "Demo illustration — filters are not interactive here", b, left + 24,
                      pos + (138 if mobile else 120 if tablet else 112), iw - 48, color="muted", bg="sage")
            return pos + panel_h + 56

        def steps(pos):
            self.text("H2 — How it works", "How it works", b, left, pos, iw, "section")
            pos += 60
            sw = iw if mobile else (iw - 2 * gap) / 3
            end = pos
            for i, step in enumerate(brief["steps"]):
                sx = left if mobile else left + i * (sw + gap)
                sy = end if mobile else pos
                self.text("Step number", f"0{i + 1}", b, sx, sy, sw, "label", "clay")
                hh = self.text("Step title", step["title"], b, sx, sy + 38, sw, "label")
                bh = self.text("Step explanation", step["body"], b, sx, sy + 46 + hh, sw, color="muted")
                end = sy + hh + bh + 78 if mobile else max(end, sy + hh + bh + 78)
            return end + 40

        def rooms(pos):
            self.text("H2 — room examples", "Three rooms. Different meetings.", b, left, pos, iw, "section")
            hh = self.text("Room example disclosure", "Fictional spaces and illustrative prices — not bookable inventory.", b,
                           left, pos + (88 if mobile else 50), iw, color="muted")
            pos += (88 if mobile else 50) + hh + 24
            cols = 1 if mobile else (2 if tablet else 3)
            cw = int((iw - (cols - 1) * gap) / cols)
            for i, room in enumerate(brief["rooms"]):
                comp = self.room(room, cw)
                self.instance(comp, b, left + (i % cols) * (cw + gap), pos + (i // cols) * 268)
            return pos + math.ceil(3 / cols) * 268 + 40

        if direction == "task-led":
            yy = task_summary(yy)
            yy = rooms(yy)
            yy = steps(yy)
        elif direction == "product-led":
            yy = rooms(yy)
            yy = steps(yy)
        else:
            yy = steps(yy)
            yy = task_summary(yy)
            yy = rooms(yy)
        self.rect("Example terms section", b, left, yy, iw, 224 if mobile else 160, "sage", 16)
        self.text("H2 — example terms", "Know the terms before you decide", b, left + 24, yy + 24, iw - 48, "label", bg="sage")
        hh = self.text("Example terms disclosure", brief["terms"], b, left + 24, yy + (86 if mobile else 62), iw - 48,
                       color="muted", bg="sage")
        yy += max(224 if mobile else 160, hh + (110 if mobile else 86)) + 56
        self.text("H2 — FAQ", "A few practical questions", b, left, yy, iw, "section")
        yy += 96 if mobile else 64
        for item in brief["faq"]:
            qh = self.text("FAQ question", item["q"], b, left, yy, iw, "label")
            ah = self.text("FAQ answer", item["a"], b, left, yy + qh + 8, iw, color="muted")
            yy += qh + ah + 36
        yy += 16
        self.text("Closing heading", "See what fits your next meeting.", b, left, yy, iw, "section")
        yy += 96 if mobile else 64
        self.instance(button, b, left, yy, action=True)
        yy += 64
        fh = self.text("Footer disclosure", "Morrow Rooms · Fictional design study. No bookings, payments or personal data collected.",
                       b, left, yy, iw, color="muted")
        yy += fh + 48
        b.update(p.geometry(x, y, width, math.ceil(yy - y)))
        return b

    def state(self, file):
        return {"file_id": self.fid, "page_id": self.page, "team_id": file["team-id"],
                "boards": [{k: b[k] for k in ("id", "name", "x", "y", "width", "height")} for b in self.boards],
                "colors": self.colors, "typographies": self.typos,
                "components": [{k: v[k] for k in ("id", "name", "root", "width", "height")} for v in self.components],
                "metrics": self.metrics, "objects": self.objects}


def file_page(file):
    return file["data"]["pages"][0]


def verify_source(client, state):
    file = client.get(state["file_id"])
    objects = file["data"]["pages-index"][state["page_id"]]["objects"]
    checks = {
        "boards_survive": all(b["id"] in objects and objects[b["id"]]["width"] == b["width"] and
                              objects[b["id"]]["height"] == b["height"] for b in state["boards"]),
        "live_text_survives": all(objects[o["id"]].get("content") == o["content"]
                                  for o in state["objects"] if o["type"] == "text"),
        "all_vectors_survive": all(o["id"] in objects for o in state["objects"]),
        "colors_survive": all(c["id"] in file["data"].get("colors", {}) for c in state["colors"].values()),
        "typographies_survive": all(t["id"] in file["data"].get("typographies", {}) for t in state["typographies"].values()),
        "main_components_survive": all(c["id"] in file["data"].get("components", {}) for c in state["components"]),
        "instances_linked": all(objects[o["id"]].get("shape-ref") == o["shape-ref"]
                                for o in state["objects"] if o.get("shape-ref")),
    }
    if not all(checks.values()):
        raise ValueError("Penpot persistence check failed: " + ",".join(k for k, v in checks.items() if not v))
    return {"at": now(), "revn": file["revn"], "checks": checks, "objects": len(objects)}


def luminance(value):
    ch = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    ch = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in ch]
    return sum(c * w for c, w in zip(ch, (.2126, .7152, .0722), strict=True))


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return round((hi + .05) / (lo + .05), 3)


def measure(state):
    by_board = {b["name"]: b for b in state["boards"]}
    results = []
    for metric in state["metrics"]:
        if metric["board"] not in by_board:
            continue
        board = by_board[metric["board"]]
        row = {**metric, "inside_board": metric["x"] >= board["x"] and metric["y"] >= board["y"] and
               metric["x"] + metric["w"] <= board["x"] + board["width"] + .01 and
               metric["y"] + metric["h"] <= board["y"] + board["height"] + .01}
        if metric["kind"] == "text":
            row["contrast"] = contrast(metric["fg"], metric["bg"])
            row["contrast_pass"] = row["contrast"] >= (3 if metric["size"] >= 24 else 4.5)
            row["size_pass"] = metric["size"] >= 16
        else:
            row["target_pass"] = metric["w"] >= 44 and metric["h"] >= 44
        results.append(row)
    violations = [r for r in results if any(r.get(k) is False for k in
                  ("inside_board", "contrast_pass", "size_pass", "target_pass"))]
    overlaps = []
    texts = [r for r in results if r["kind"] == "text"]
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if a["board"] != b["board"]:
                continue
            dx = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            dy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            if dx > 1 and dy > 1:
                overlaps.append({"board": a["board"], "a": a["name"], "b": b["name"], "overlap": [dx, dy]})
    return {"at": now(), "basis": "editable Penpot source; not a DOM or live accessibility audit",
            "objects": results, "violations": violations, "text_box_overlaps": overlaps,
            "runtime_not_checked": RUNTIME_ONLY}


class Job:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.packet = self.root / "homepage"
        self.packet.mkdir(parents=True, exist_ok=True)
        self.state_path = self.packet / "job.json"
        self.state = load(self.state_path) if self.state_path.exists() else {
            "version": VERSION, "created_at": now(), "stages": {}, "review_round": 0,
            "packet_verified": False, "owner_taste_approved": False}

    def commit(self):
        save(self.state_path, self.state)

    def receipt(self, stage, fingerprint, output):
        self.state["stages"][stage] = {"fingerprint": fingerprint, "completed_at": now(), "output": output}
        self.commit()
        return output

    def cached(self, stage, fingerprint):
        receipt = self.state["stages"].get(stage)
        if receipt:
            if receipt["fingerprint"] != fingerprint:
                raise ValueError("saved stage inputs changed; use a fresh workspace rather than silently repeating paid work")
            return receipt["output"]
        return None

    def brief(self, raw, pilot):
        value = brief_contract(json.loads(raw) if raw else copy.deepcopy(DEFAULT))
        if pilot and not value["fictional"]:
            raise ValueError("pilot workflow refuses real deliverables")
        fingerprint = digest(value)
        cached = self.cached("brief", fingerprint)
        if cached:
            return {**cached, "reused": True}
        save(self.packet / "brief.json", value)
        inventory = json.dumps(value, ensure_ascii=False, indent=2)
        (self.packet / "BRIEF.md").write_text("# Homepage brief\n\n" + inventory + "\n\n"
            "Widths: 390, 768, 1440. Editable Penpot + original vector shapes + licensed Source Sans Pro.\n"
            "WCAG 2.2 AA where assessable: contrast/body sizes/targets/bounds. Runtime checks remain in handoff.\n"
            "Three structural directions; fictional selection provisional. Real direction/final gates mandatory.\n"
            "No signup, booking, payment, analytics, lead collection or fabricated customer proof.\n"
            "Maximum 3 review rounds; full trial <=$10, Pacific day <=$10; saved per-round reservations.\n")
        self.state["brief_hash"] = fingerprint
        return self.receipt("brief", fingerprint, {"status": "completed", "brief_path": "homepage/BRIEF.md"})

    def explore(self):
        fingerprint = self.state["brief_hash"]
        cached = self.cached("explore", fingerprint)
        client = Penpot()
        client.login()
        if cached:
            state = load(self.packet / "wireframes.json")
            verify_source(client, state)
            return {**cached, "reused": True}
        if (self.packet / "wireframes.pending.json").exists():
            raise ValueError("incomplete Penpot exploration detected; inspect saved file identity before retry, never duplicate it")
        value = load(self.packet / "brief.json")
        file = client.create(value["product"] + " — structural wireframes (fictional pilot)" if value["fictional"] else value["product"] + " — structural wireframes")
        canvas = Canvas(file["id"], file_page(file), True)
        for i, direction in enumerate(DIRECTIONS):
            canvas.homepage(value, direction, 390, 0, i * 4600)
            canvas.homepage(value, direction, 1440, 530, i * 4600)
        state = canvas.state(file)
        # Persist identity before network save: a failed partial stage cannot create silent duplicates.
        save(self.packet / "wireframes.pending.json", state)
        file = client.update(file["id"], canvas.changes)
        state["revn"] = file["revn"]
        save(self.packet / "wireframes.json", state)
        evidence = verify_source(client, state)
        save(self.packet / "wireframes-reopen.json", evidence)
        exports = []
        for board in state["boards"]:
            width = board["width"]
            direction = board["name"].split(" / ")[0].removeprefix("Wireframe ")
            path = self.packet / "exports" / f"wire-{direction}-{width}.png"
            exports.append(client.export(state, board, "png", path))
        # Contact sheet is composed from actual Penpot exports, never an alternate design canvas.
        contact = self.packet / "contact-sheet.svg"
        rows = []
        for i, direction in enumerate(DIRECTIONS):
            rows.append(f'<text x="24" y="{30 + i * 390}" font-size="20">{direction} — 390 and 1440</text>')
            for width, bx, bw in ((390, 24, 110), (1440, 170, 500)):
                # Relative image URLs keep the exported originals separately inspectable.
                rows.append(f'<image href="exports/wire-{direction}-{width}.png" x="{bx}" y="{46 + i * 390}" width="{bw}" height="330" preserveAspectRatio="xMinYMin meet"/>')
        contact.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="700" height="1180"><rect width="700" height="1180" fill="white"/>' + ''.join(rows) + '</svg>')
        rationale = {
            "product-led": "Product illustration and room comparison precede the explanation: recognition first.",
            "task-led": "Meeting-needs summary precedes comparison, then explains the process: organizer's task first.",
            "explanation-led": "Three-step story precedes the product examples: novice understanding first.",
            "contact_sheet": "homepage/contact-sheet.svg", "editable_file_id": state["file_id"], "exports": exports}
        save(self.packet / "exploration.json", rationale)
        return self.receipt("explore", fingerprint, {"status": "completed", "file_id": state["file_id"],
            "contact_sheet": "homepage/contact-sheet.svg", "questions": [{"id": "direction", "question": "Choose a structural direction; fictional choice is provisional", "options": list(DIRECTIONS)}]})

    def direction(self, raw, pilot):
        brief = load(self.packet / "brief.json")
        decision = safe_gate(raw)
        if not decision and pilot:
            decision = {"direction": "task-led", "reason": "Meeting needs and comparison serve the organizer's task before the explanatory story; provisional fictional choice, not owner approval."}
        decision = direction_contract(brief, decision, pilot)
        fp = digest(decision)
        cached = self.cached("direction", fp)
        if cached:
            return {**cached, "reused": True}
        save(self.packet / "direction.json", {**decision, "saved_at": now()})
        self.state["direction"] = decision
        return self.receipt("direction", fp, {"status": "completed", **decision})

    def design(self):
        # Source stages don't run twice on resume; review revisions get their own receipts.
        round_number = self.state.get("next_design_round", 1)
        if round_number > 3:
            raise ValueError("maximum three review rounds")
        patch = self.state.get("patch", {})
        brief = load(self.packet / "brief.json")
        brief.update(patch)
        direction = self.state["direction"]["direction"]
        fp = digest({"brief": brief, "direction": direction, "round": round_number})
        key = f"design-{round_number}"
        cached = self.cached(key, fp)
        client = Penpot()
        client.login()
        if cached:
            verify_source(client, load(self.packet / f"source-r{round_number:02}.json"))
            return {**cached, "reused": True}
        if (self.packet / f"source-r{round_number:02}.pending.json").exists():
            raise ValueError("incomplete Penpot design detected; inspect saved file identity before retry, never duplicate it")
        file = client.create(brief["product"] + f" — Quiet Atlas — r{round_number:02}" + (" (provisional fictional)" if brief["fictional"] else ""))
        assets(client, self.packet / "assets")
        canvas = Canvas(file["id"], file_page(file))
        for width, x in ((390, 0), (768, 530), (1440, 1426)):
            canvas.homepage(brief, direction, width, x)
        # Reusable component states live outside the exported homepage boards, named and editable.
        for state_name in ("hover", "focus", "pressed", "disabled", "loading"):
            canvas.button(brief["cta"], state_name)
        system = canvas.board("Quiet Atlas — tokens and state catalogue", 3100, 0, 800, 1160)
        canvas.text("System heading", "Quiet Atlas", system, 3132, 32, 700, "section")
        canvas.text("System status", "Provisional direction. See named main components beside homepage boards.", system, 3132, 100, 700)
        for i, (name, c) in enumerate(canvas.colors.items()):
            canvas.rect("Swatch " + name, system, 3132, 180 + i * 80, 80, 48, name, 4)
            canvas.text("Token " + name, f"{name}  {c['color']}", system, 3236, 192 + i * 80, 580)
        canvas.text("Scales", "Spacing: 8 / 16 / 24 / 32 / 48 / 64.\nBreakpoints: stacked phone; two-card tablet; three-card desktop.\nSource Sans Pro · SIL Open Font License 1.1.\nFocus, disabled, loading and pressed are visual specs, not runtime proof.", system, 3132, 940, 700)
        state = canvas.state(file)
        save(self.packet / f"source-r{round_number:02}.pending.json", state)
        file = client.update(file["id"], canvas.changes)
        state["revn"] = file["revn"]
        save(self.packet / f"source-r{round_number:02}.json", state)
        save(self.packet / "source.json", state)
        fresh = Penpot()
        fresh.login()
        save(self.packet / f"source-r{round_number:02}-reopen.json", verify_source(fresh, state))
        exports = []
        for board in state["boards"]:
            if not board["name"].startswith("Homepage "):
                continue
            for kind in ("png", "svg"):
                dest = self.packet / "exports" / f"homepage-r{round_number:02}-{board['width']}.{kind}"
                exports.append(fresh.export(state, board, kind, dest))
        tokens = {"direction": "Quiet Atlas", "colors": PALETTE, "typography": TYPO,
                  "font": "Source Sans Pro", "spacing": [8, 16, 24, 32, 48, 64],
                  "contrast_pairs": {f"{a}/{b}": contrast(PALETTE[a], PALETTE[b]) for a, b in
                                     (("ink", "paper"), ("muted", "paper"), ("muted", "sage"), ("white", "pine"), ("clay", "paper"))},
                  "components": state["components"], "runtime_not_checked": RUNTIME_ONLY}
        save(self.packet / "tokens.json", tokens)
        save(self.packet / "final-copy.json", brief)
        self.state["review_round"] = round_number
        self.state["file_id"] = state["file_id"]
        self.state["final_exports"] = exports
        return self.receipt(key, fp, {"status": "completed", "round": round_number,
            "file_id": state["file_id"], "exports": exports})

    def measurement(self):
        state = load(self.packet / "source.json")
        number = self.state["review_round"]
        review = self.root / "review"
        fingerprint = digest({"file": state["file_id"], "revision": state["revn"], "round": number})
        cached = self.cached(f"measure-{number}", fingerprint)
        if cached:
            if not (review / "facts.md").exists() or not (review / "shots/homepage-390.png").exists():
                raise ValueError("saved measurement artifacts missing; refusing silent paid-stage repeat")
            return {**cached, "reused": True}
        if review.exists():
            archive = self.packet / "reviews" / f"before-r{number:02}"
            if not archive.exists():
                shutil.copytree(review, archive)
            shutil.rmtree(review)
        (review / "shots").mkdir(parents=True)
        (review / "facts").mkdir()
        (review / "critic").mkdir()
        facts = measure(state)
        save(review / "facts" / "penpot.json", facts)
        save(self.packet / f"measure-r{number:02}.json", facts)
        brief = load(self.packet / "brief.json")
        (review / "brief.md").write_text("# Penpot homepage review\n\n" + brief["audience"] + "\n\n"
            "Homepage goal: explain room comparison and example terms; primary action: " + brief["cta"] + ".\n"
            "Fictional study. Review homepage boards only, not the component catalogue. Static editable Penpot designs, not implemented pages.\n"
            "Desktop: 1440, tablet: 768, mobile: 390. Do not invent runtime behavior or infer ARIA/keyboard failures from static boards.\n"
            "Product illustration and needs panel are explicitly illustrations, not working inputs.\n")
        lines = ["# Measured facts — editable Penpot source", "", "NOT a DOM audit: no axe, Tab walk, ARIA, focus or runtime checks were performed.",
                 "Text boxes are conservative estimates; screenshots/export glyph fit must still be judged. Disabled-state contrast exempt; homepage actions are not disabled.", ""]
        for b in state["boards"]:
            if not b["name"].startswith("Homepage "):
                continue
            name = f"homepage-{b['width']}"
            src = self.packet / "exports" / f"homepage-r{number:02}-{b['width']}.png"
            dest = review / "shots" / f"{name}.png"
            shutil.copyfile(src, dest)
            rows = [r for r in facts["objects"] if r["board"] == b["name"]]
            lines.extend([f"## {name} / {'desktop' if b['width'] == 1440 else 'mobile' if b['width'] == 390 else 'tablet'}",
                          f"Source board: {b['id']}; {b['width']}×{b['height']}. Screenshot: shots/{name}.png (full-height Penpot export).",
                          "Body text minimum 16 px; intended action regions >=44×44 px. Source bounds below do NOT independently prove glyph fit."])
            for row in rows:
                if row["kind"] == "text":
                    lines.append(f"- {row['name']}: {row['size']}px; {row['fg']} on {row['bg']}; contrast {row['contrast']}:1; source bounds inside={row['inside_board']}; text={row['text']!r}")
                else:
                    lines.append(f"- Intended target {row['name']}: {row['w']}×{row['h']}; inside={row['inside_board']}")
        lines += ["", "## Source violations", json.dumps(facts["violations"], ensure_ascii=False),
                  "", "## Source text-box overlaps", json.dumps(facts["text_box_overlaps"], ensure_ascii=False),
                  "", "## Runtime not checked", ", ".join(RUNTIME_ONLY)]
        (review / "facts.md").write_text("\n".join(lines) + "\n")
        return self.receipt(f"measure-{number}", fingerprint, {"status": "completed", "round": number,
                "measured_violations": len(facts["violations"]), "facts_path": "review/facts.md", "screenshots": 3})

    def budget(self, raw):
        reservation = budget_contract(safe_gate(raw), self.state["review_round"])
        save(self.packet / f"budget-r{self.state['review_round']:02}.json", reservation)
        return {"status": "completed", "reserved_usd": reservation["reserve_usd"]}

    def disposition(self, raw):
        decision = safe_gate(raw)
        if decision.get("action") not in ("fix", "handoff"):
            raise ValueError("review checkpoint needs action=fix|handoff")
        findings = load(self.root / "review/findings.json")
        ids = {f["id"] for f in findings.get("findings", [])}
        if decision["action"] == "fix":
            if self.state["review_round"] >= 3:
                raise ValueError("three rounds exhausted; unresolved issues must be handed off")
            if not decision.get("issues") or not set(decision["issues"]).issubset(ids):
                raise ValueError("fix must cite existing evidence-backed finding IDs")
            patch = decision.get("patch", {})
            if not patch or set(patch) - {"headline", "subhead", "disclosure", "terms", "cta", "faq"}:
                raise ValueError("v1 fixes are bounded copy patches; layout problems require an explicit source revision")
            brief_contract({**load(self.packet / "brief.json"), **patch})
            self.state["patch"] = {**self.state.get("patch", {}), **patch}
            self.state["next_design_round"] = self.state["review_round"] + 1
        save(self.packet / f"disposition-r{self.state['review_round']:02}.json", decision)
        shutil.copytree(self.root / "review", self.packet / "reviews" / f"r{self.state['review_round']:02}", dirs_exist_ok=True)
        self.state["disposition"] = decision
        self.commit()
        return {"status": "completed", "verdict": "request_changes" if decision["action"] == "fix" else "handoff",
                "round": self.state["review_round"], "owner_taste_approved": False}

    def handoff(self):
        source = load(self.packet / "source.json")
        client = Penpot()
        client.login()
        reopened = verify_source(client, source)
        save(self.packet / "handoff-reopen.json", reopened)
        widths = {b["width"] for b in source["boards"] if b["name"].startswith("Homepage ")}
        if widths != set(WIDTHS) or not (self.root / "review/findings.json").exists():
            raise ValueError("actual responsive packet/review missing")
        if self.state.get("disposition", {}).get("action") != "handoff":
            raise ValueError("bounded review disposition missing")
        url = f"{client.base}/#/workspace?team-id={source['team_id']}&file-id={source['file_id']}&page-id={source['page_id']}"
        wire = load(self.packet / "wireframes.json")
        wire_url = f"{client.base}/#/workspace?team-id={wire['team_id']}&file-id={wire['file_id']}&page-id={wire['page_id']}"
        save(self.packet / "source-links.json", {"homepage": url, "wireframes": wire_url,
                                               "homepage_file_id": source["file_id"], "wireframe_file_id": wire["file_id"]})
        body = f"""# Implementation handoff — {load(self.packet / 'brief.json')['product']}

Provisional fictional design study; NOT owner taste approval or a real launch.

Editable hi-fi source: {url}
Editable structural alternatives: {wire_url}

## Source mapping
Source layers/board/component IDs: source.json and wireframes.json.
Semantic colours, typography, spacing, contrast pairs and reusable components: tokens.json.
Exact final words, room examples, terms and FAQ: final-copy.json. No rasterized final text.
PNG/SVG exports: exports/. SVG keeps live text but font URLs point to the tailnet Penpot host;
PNG is the portable visual reference. Bundle licensed fonts when implementing; do not outline
or flatten the canonical Penpot text. No stock/photo/customer/logo assets.
Source Sans Pro: SIL Open Font License 1.1; already installed in Penpot. Original vectors.
Installed regular/semibold fonts, full OFL text, actual name-table copyright/version and hashes: assets/.

## Responsive implementation
Use max-width 1312px content centred at desktop; 64px desktop / 48px tablet / 24px phone margins.
Desktop hero 52/48 text/illustration, three room columns. Tablet uses full-width hero text and two room columns;
tablet/phone omit the decorative hero diagram; phone stacks and keeps every content section and labelled demo action.
At widths below 390, fluid text/content and one column; validate 320px and 400% zoom explicitly.
Spacing scale 8/16/24/32/48/64; body 16px, lead 18px, headings 28/36/44/56px. Avoid hard-coded text-box heights in code.
Static boards are target compositions, not auto-layout/reflow proof.

## Components and states
Primary button: default/hover/focus/pressed/disabled/loading main components with linked instances.
Hover must also change boundary/weight (not colour alone); focus indicator 3px clay with offset;
verify contrast and no obscuration in runtime. Disabled state is non-interactive and not sole status copy.
Loading label 'Opening demo…' announces progress; failures say what happened and offer retry.
Room-card responsive variants contain name, capacity, equipment and explicitly illustrative price;
non-interactive examples use article, not button semantics. Demo disclosure stays adjacent to actions.
Meeting-needs and floor-plan panels are labelled illustrations, not form controls. Hide purely decorative
vector tables from accessibility APIs; all meaningful room details are live text.
No-results: explain that no example rooms match, offer clear-filter action. Error: 'Demo rooms could not
load. Try again.' Loading: honest progress; use reduced-motion preference. Those are handoff states,
not claimed live behaviors in this homepage-only study.

## Navigation and accessibility acceptance
Use header/nav/main/footer landmarks, exactly one H1 and ordered H2 section headings.
How it works and Example terms are in-page anchors, with 44px hit regions. Phone preserves access via
section reading order and footer anchors in implementation. Explore demo rooms links to a clearly
labelled fictional demo route or a transparent demo placeholder; no signup, transaction or lead capture.
Keyboard Tab/Shift-Tab/Enter/Space, visible/unobscured focus, useful accessible names, screen reader order,
zoom/reflow/text spacing, contrast of every rendered state, status announcements and reduced motion
must be tested in code. No static-board ARIA/keyboard/focus/axe/overall WCAG-compliance claim.

## Review and unresolved work
Two unchanged measured-review critics plus unchanged merge. Source measurements are separated from
judgement; review/findings.json and every homepage/reviews/rNN directory retain observations,
suggestions and disposition. disposition-rNN.json lists accepted/rejected/residual observations with
human reasoning. Critic agreement is not truth or owner aesthetic approval. Stop at three rounds.
Real workflows require direction and final owner gates; only the fictional pilot selects provisionally.

## Build acceptance
Verify exact copy and demo honesty; editable asset provenance; all three target compositions; fluid
reflow at 320/390/768/1440; no clipping/overlap; typography/font loading; target/contrast numbers;
keyboard, focus, names, landmarks and live states. No publishing is part of this workflow.
"""
        (self.packet / "HANDOFF.md").write_text(body)
        manifest = {"created_at": now(), "version": VERSION, "source_links": "homepage/source-links.json",
                    "exports": self.state["final_exports"], "widths": sorted(widths), "source_persistence": reopened,
                    "direction": self.state["direction"], "review_rounds": self.state["review_round"],
                    "disposition": self.state["disposition"], "runtime_not_checked": RUNTIME_ONLY,
                    "packet_built": True, "deployment_verified": False, "resume_verified": False,
                    "owner_taste_approved": False, "completion_verified": False,
                    "completion_note": "Host verification must add deployed revision, real-editor/export inspection, resume proof, actual cost/time and licenses. Workflow never self-attests task completion."}
        save(self.packet / "manifest.json", manifest)
        return {"status": "completed", "manifest_path": "homepage/manifest.json", "handoff_path": "homepage/HANDOFF.md",
                "source_url": url, "owner_taste_approved": False}

    def final(self, raw):
        decision = safe_gate(raw)
        if decision.get("approval") != "owner-final":
            raise ValueError("real workflow remains at final owner gate")
        save(self.packet / "owner-final.json", {**decision, "recorded_at": now()})
        return {"status": "completed", "owner_final_gate_recorded": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("brief", "explore", "direction", "design", "measure", "budget", "disposition", "handoff", "final"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    job = Job(args.workspace)
    raw = os.environ.get("HOMEPAGE_DATA", "")
    methods = {"brief": lambda: job.brief(raw, args.pilot), "explore": job.explore,
               "direction": lambda: job.direction(raw, args.pilot), "design": job.design,
               "measure": job.measurement, "budget": lambda: job.budget(raw),
               "disposition": lambda: job.disposition(raw), "handoff": job.handoff,
               "final": lambda: job.final(raw)}
    started = time.monotonic()
    try:
        result = methods[args.stage]()
    except (ValueError, RuntimeError, KeyError) as exc:
        # Safe errors are our own strings; no raw HTTP bodies/env/session payloads.
        raise SystemExit(str(exc)) from None
    result["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
