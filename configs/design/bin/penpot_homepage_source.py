"""Penpot 2.18 change builders for Design's editable homepage workflow.

Ported from Design's verified host proof; only standard-library dependencies.
No credentials or browser protocol. Colours, text and component refs stay live.
"""
import re
import struct
import uuid

ROOT = "00000000-0000-0000-0000-000000000000"


def nid():
    return str(uuid.uuid4())


def geometry(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h,
            "selrect": {"x": x, "y": y, "width": w, "height": h,
                        "x1": x, "y1": y, "x2": x + w, "y2": y + h},
            "points": [{"x": x, "y": y}, {"x": x + w, "y": y},
                       {"x": x + w, "y": y + h}, {"x": x, "y": y + h}],
            "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
            "transform-inverse": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}}


def shape(kind, name, parent, frame, x, y, w, h, fills, radius=0, sid=None):
    s = {"id": sid or nid(), "name": name, "type": kind, "parent-id": parent,
         "frame-id": frame, "fills": fills, "strokes": [], "rotation": 0,
         "shapes": [], **geometry(x, y, w, h)}
    if radius:
        s.update({k: radius for k in ("r1", "r2", "r3", "r4")})
    if kind == "frame":
        s["show-content"] = False
    return s


def color(name, value):
    return {"id": nid(), "name": name, "path": "Quiet Atlas", "color": value, "opacity": 1}


def typography(name, size, weight="400"):
    return {"id": nid(), "name": name, "path": "Quiet Atlas", "font-id": "sourcesanspro",
            "font-family": "sourcesanspro", "font-variant-id": "600" if weight == "600" else "regular",
            "font-weight": weight, "font-style": "normal", "font-size": str(size),
            "line-height": "1.35", "letter-spacing": "0", "text-transform": "none"}


def fill(c, file_id):
    return [{"fill-color": c["color"], "fill-opacity": 1,
             "fill-color-ref-id": c["id"], "fill-color-ref-file": file_id}]


def content(lines, style, ink, file_id, align="left"):
    attrs = {k: v for k, v in style.items() if k not in ("id", "name", "path")}
    attrs.update({"typography-ref-id": style["id"], "typography-ref-file": file_id,
                  "fills": fill(ink, file_id), "text-decoration": "none"})
    return {"type": "root", "vertical-align": "top", "children": [{"type": "paragraph-set", "children": [
        {"type": "paragraph", "text-align": align, "text-direction": "ltr", **attrs,
         "children": [{"text": line, **attrs}]} for line in lines]}]}


class FontMetrics:
    """Advance widths from the installed OFL font; no runtime packages/downloads.

    This initial Latin/LTR layout cache is not a complex-script shaping engine.
    SVG/editor text and its styled content remain editable, not converted to paths.
    """
    def __init__(self, data):
        self.data = data
        tables = {}
        for i in range(struct.unpack_from(">H", data, 4)[0]):
            tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + 16 * i)
            tables[tag] = offset
        self.units = self.word(tables[b"head"] + 18)
        self.hmtx = tables[b"hmtx"]
        self.metric_count = self.word(tables[b"hhea"] + 34)
        cmap = tables[b"cmap"]
        choices = []
        for i in range(self.word(cmap + 2)):
            platform, encoding, offset = struct.unpack_from(">HHI", data, cmap + 4 + 8 * i)
            base = cmap + offset
            fmt = self.word(base)
            if platform in (0, 3) and fmt in (4, 12) and (platform == 0 or encoding in (1, 10)):
                choices.append((fmt, base))
        if not choices:
            raise ValueError("installed font has no supported Unicode cmap")
        self.format, self.base = max(choices)
        self.cache = {}

    def word(self, offset):
        return struct.unpack_from(">H", self.data, offset)[0]

    def glyph(self, cp):
        base = self.base
        if self.format == 12:
            count = struct.unpack_from(">I", self.data, base + 12)[0]
            for i in range(count):
                start, end, first = struct.unpack_from(">III", self.data, base + 16 + i * 12)
                if start <= cp <= end:
                    return first + cp - start
            return 0
        count = self.word(base + 6) // 2
        ends = base + 14
        starts = ends + 2 * count + 2
        deltas = starts + 2 * count
        offsets = deltas + 2 * count
        for i in range(count):
            start, end = self.word(starts + 2 * i), self.word(ends + 2 * i)
            if start <= cp <= end:
                delta = self.word(deltas + 2 * i)
                distance = self.word(offsets + 2 * i)
                if not distance:
                    return (cp + delta) & 65535
                glyph = self.word(offsets + 2 * i + distance + 2 * (cp - start))
                return (glyph + delta) & 65535 if glyph else 0
        return 0

    def width(self, text, size):
        total = 0
        for char in text:
            cp = ord(char)
            # The authored pilot is Latin/LTR. Refuse complex shaping rather than
            # silently showing an incorrect editable source for other scripts.
            if not (cp <= 0x024F or 0x2000 <= cp <= 0x206F):
                raise ValueError(f"unsupported pilot text character U+{cp:04X}; Latin/LTR only")
            if cp not in self.cache:
                glyph = self.glyph(cp)
                if not glyph:
                    raise ValueError(f"installed font lacks U+{cp:04X}")
                self.cache[cp] = self.word(self.hmtx + 4 * min(glyph, self.metric_count - 1))
            total += self.cache[cp]
        return total * size / self.units


def text_positions(obj, metrics):
    """Seed Penpot's native text cache: required by its current WASM exporter.

    Font advance widths, explicit authored line breaks and stable line boxes.
    No kerning/complex shaping claim; editor edits may recompute the cache.
    """
    result = []
    for i, paragraph in enumerate(obj["content"]["children"][0]["children"]):
        leaf = paragraph["children"][0]
        text = "".join(n.get("text", "") for n in paragraph["children"])
        size = float(leaf["font-size"])
        font = metrics[leaf["font-weight"]]
        width = font.width(text, size)
        height = round(size * 4 / 3)
        line_height = size * float(leaf["line-height"])
        dx = max(0, (obj["width"] - width) / 2) if paragraph["text-align"] == "center" else 0
        dy = i * line_height + (line_height - height) / 2
        result.append({"x": obj["x"] + dx, "y": obj["y"] + dy + height,
                       "width": width, "height": height,
                       "x1": dx, "y1": dy, "x2": dx + width, "y2": dy + height,
                       "font-style": leaf["font-style"], "text-transform": "none",
                       "font-size": f"{size:g}px", "font-weight": leaf["font-weight"],
                       "text-decoration": "none", "letter-spacing": "normal",
                       "fills": leaf["fills"], "direction": "ltr",
                       "font-family": leaf["font-family"], "text": text})
    return result


def add_obj(obj, page):
    return {"type": "add-obj", "id": obj["id"], "page-id": page,
            "parent-id": obj["parent-id"], "frame-id": obj["frame-id"], "obj": obj}


def mod_obj(obj, page):
    return {"type": "mod-obj", "id": obj["id"], "page-id": page,
            "operations": [{"type": "assign", "value": {k: v for k, v in obj.items() if k != "id"}}]}


def mark_main(obj, component_id, file_id):
    obj.update({"component-id": component_id, "component-file": file_id,
                "component-root": True, "main-instance": True})


def mark_instance(obj, component_id, file_id, main_id):
    obj.update({"component-id": component_id, "component-file": file_id,
                "component-root": True, "shape-ref": main_id})


def kebab(value):
    if isinstance(value, dict):
        return {re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", str(k)).lower(): kebab(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [kebab(v) for v in value]
    return value


def transit(value):
    if isinstance(value, dict):
        result = ["^ "]
        for k, v in value.items():
            result.extend([transit(k), transit(v)])
        return result
    if isinstance(value, list):
        return [transit(v) for v in value]
    if isinstance(value, str) and value.startswith(":"):
        return "~:" + value[1:]
    if isinstance(value, str) and value.startswith("uuid:"):
        return "~u" + value[5:]
    return value


def untransit(value):
    if isinstance(value, dict):
        if "~#uri" in value:
            return value["~#uri"]
        return {str(k).removeprefix("~:"): untransit(v) for k, v in value.items()}
    if isinstance(value, str) and value[:2] in ("~:", "~u"):
        return value[2:]
    return value
