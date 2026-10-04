"""Original logo schema -> named editable Penpot objects. No brand catalogue.

Reuses D3's authenticated client/font layout/Transit primitives only, never its
meeting-room templates. Deterministic boards display agent-generated geometry.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import logo_contracts as c
import logo_size_check as size_check
import penpot_homepage_source as p

MONO = {"ink": "#161616", "paper": "#FFFFFF", "accent": "#777777", "accent_on": "#FFFFFF", "muted": "#555555", "surface": "#F2F2F2"}


def shape_bounds(s):
    if s["kind"] != "path":
        return s["x"], s["y"], s["w"], s["h"]
    pts = c.path_points(s["commands"])
    xs, ys = zip(*pts, strict=True)
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


class LogoCanvas:
    def __init__(self, file, font_dir, product):
        self.file = file
        self.fid = file["id"]
        self.page = file["data"]["pages"][0]
        self.product = product
        self.objects, self.boards, self.changes = [], [], []
        self.colors, self.typos, self.metrics = {}, {}, []
        self.fonts = {weight: p.FontMetrics((Path(font_dir) / f"sourcesanspro-{variant}.ttf").read_bytes())
                      for weight, variant in (("400", "regular"), ("600", "semibold"))}
        self.palette("mono", MONO)
        for size in (14, 16, 18, 22, 28, 40, 50, 64):
            for weight in ("400", "600"):
                name = f"{size}-{weight}"
                style = p.typography(name, size, weight)
                style["path"] = product + "/Logo"
                style["line-height"] = "1.25"
                self.typos[name] = style
                self.changes.append({"type": "add-typography", "typography": style})

    def palette(self, name, palette):
        for role, hex_value in palette.items():
            key = name + "/" + role
            obj = p.color(role, hex_value)
            obj["path"] = self.product + "/" + name
            self.colors[key] = obj
            self.changes.append({"type": "add-color", "color": obj})

    def put(self, obj):
        self.objects.append(obj)
        self.changes.append(p.add_obj(obj, self.page))
        return obj

    def board(self, name, x, y, w, h, bg="mono/paper", transparent=False):
        fills = [] if transparent else p.fill(self.colors[bg], self.fid)
        obj = p.shape("frame", name, p.ROOT, p.ROOT, x, y, w, h, fills)
        obj["hide-fill-on-export"] = transparent
        self.boards.append(self.put(obj))
        return obj

    def rect(self, board, name, x, y, w, h, color, radius=0):
        return self.put(p.shape("rect", name, board["id"], board["id"], x, y, w, h,
                                p.fill(self.colors[color], self.fid), radius))

    def wrap(self, value, width, size, weight):
        font = self.fonts[weight]
        lines = []
        for paragraph in value.split("\n"):
            line = ""
            for word in paragraph.split():
                if line and font.width(line + " " + word, size) > width:
                    lines.append(line)
                    line = word
                else:
                    line = (line + " " + word).strip()
            lines.append(line)
        return lines

    def abridge(self, value, width, size, weight, max_lines):
        """Fit a description into max_lines by dropping whole words, never mid-word.

        An abridged text ends with an ellipsis after a complete word; the full text
        stays in the run's JSON artifacts and the measurements say so.
        """
        lines = self.wrap(value, width, size, weight)
        if len(lines) <= max_lines:
            return value, False
        words = " ".join(value.split()).split(" ")
        while words:
            words.pop()
            candidate = " ".join(words).rstrip(",;:-") + "\u2026"
            if len(self.wrap(candidate, width, size, weight)) <= max_lines:
                return candidate, True
        raise ValueError("text cannot be abridged to fit")

    def text(self, board, name, value, x, y, width, size=16, weight="400", color="mono/ink", bg="mono/paper", logo=False,
             max_lines=None):
        full = value
        abridged = False
        if max_lines:
            value, abridged = self.abridge(value, width, size, weight, max_lines)
        lines = self.wrap(value, width, size, weight)
        style = self.typos[f"{size}-{weight}"]
        height = math.ceil(len(lines) * size * 1.25 + 6)
        obj = p.shape("text", name, board["id"], board["id"], x, y, width, height, [])
        obj.update({"content": p.content(lines, style, self.colors[color], self.fid), "grow-type": "fixed"})
        obj["position-data"] = p.text_positions(obj, self.fonts)
        self.put(obj)
        self.metrics.append({"id": obj["id"], "board": board["name"], "name": name,
            "logo_exempt": logo, "text": value, "full_text": full, "abridged": abridged,
            "font_size": size, "fg": self.colors[color]["color"],
            "bg": self.colors[bg]["color"], "inside": x >= board["x"] and y >= board["y"] and
            x + width <= board["x"] + board["width"] and y + height <= board["y"] + board["height"],
            "advance_fit": all(s["width"] <= width + .01 for s in obj["position-data"])})
        return obj

    def symbol(self, board, concept, x, y, size, color="mono/ink", accent=None):
        """Draw the symbol in one colour, or with accent-toned parts in `accent` (colour versions)."""
        c.concept_contract(concept, {"sources": [{"id": i} for i in concept["source_ids"]]})
        result = []
        for i, spec in enumerate(concept["symbol"]):
            bx, by, bw, bh = shape_bounds(spec)
            scale = size / 100
            fill = accent if accent and spec.get("tone") == c.ACCENT_TONE else color
            obj = p.shape("circle" if spec["kind"] == "ellipse" else spec["kind"],
                          f'{concept["id"]}/{spec["name"]}/{i}', board["id"], board["id"],
                          x + bx * scale, y + by * scale, bw * scale, bh * scale,
                          p.fill(self.colors[fill], self.fid), spec.get("r", 0) * scale)
            if spec["kind"] == "path":
                commands = []
                for command in spec["commands"]:
                    vals = [x + command[j] * scale if j % 2 else y + command[j] * scale for j in range(1, len(command))]
                    commands.append(command[0] + " ".join(f"{v:.6f}" for v in vals))
                obj["content"] = " ".join(commands)
                # Native path schema uses selrect/points, not rectangle xywh.
                for field in ("x", "y", "width", "height"):
                    obj.pop(field, None)
            result.append(self.put(obj))
        return result

    def lockup(self, board, concept, name, x, y, symbol_size, text_size, palette="mono", fg="ink", bg="paper", colour=False):
        self.symbol(board, concept, x, y, symbol_size, palette + "/" + fg, palette + "/accent" if colour else None)
        gap = symbol_size * .25
        width = self.fonts[concept["wordmark_weight"]].width(name, text_size) + 8
        self.text(board, "Wordmark/" + name, name, x + symbol_size + gap,
                  y + (symbol_size - text_size * 1.25) / 2, width, text_size,
                  concept["wordmark_weight"], palette + "/" + fg, palette + "/" + bg, True)

    def rough_board(self, concepts, title="monochrome exploration"):
        board = self.board("Six monochrome explorations — " + self.product, 0, 0, 1080, 790)
        self.text(board, "Title", self.product + " / " + title, 28, 20, 1020, 28, "600")
        for i, concept in enumerate(concepts):
            x, y = 28 + (i % 3) * 354, 90 + (i // 3) * 340
            self.symbol(board, concept, x + 100, y + 10, 120)
            self.text(board, "Label", concept["name"], x, y + 146, 300, 22, "600", max_lines=1)
            self.text(board, "Family", concept["family"] + " / " + concept["id"], x, y + 180, 300, 14,
                      color="mono/muted", max_lines=1)
            self.text(board, "Ownable detail", concept["ownable_detail"], x, y + 206, 300, 16, max_lines=5)
        return board

    def comparison_board(self, concepts, rows):
        board = self.board("Three directions — " + self.product, 0, 1000, 1980, 1040)
        for i, row in enumerate(rows):
            concept = next(v for v in concepts if v["id"] == row["id"])
            palette = concept["id"]
            self.palette(palette, row["palette"])
            x, y = i * 660 + 28, 1028
            self.text(board, "Neutral direction label", chr(65 + i) + " / " + concept["name"], x, y, 600, 28, "600")
            self.lockup(board, concept, self.product, x + 32, y + 64, 104, 50)
            self.text(board, "Concept basis", concept["idea"], x, y + 208, 586, 18, max_lines=4)
            self.text(board, "Trade-off", concept["tradeoff"], x, y + 306, 586, 16, color="mono/muted", max_lines=4)
            for j, role in enumerate(c.ROLES):
                sx = x + j * 98
                self.rect(board, "Palette/" + role, sx, y + 408, 84, 52, palette + "/" + role)
                self.text(board, "Token label", role + "\n" + row["palette"][role], sx, y + 472, 94, 14)
            self.rect(board, "Local dark sidebar", x, y + 546, 602, 166, palette + "/ink")
            self.lockup(board, concept, self.product, x + 24, y + 570, 48, 28, palette, "paper", "ink")
            self.text(board, "Local sidebar companion", "Workflows   /   Runs   /   Studio", x + 24, y + 640, 550, 16,
                      color=palette + "/paper", bg=palette + "/ink")
            self.rect(board, "Local document card", x, y + 736, 602, 232, palette + "/surface")
            self.lockup(board, concept, self.product, x + 24, y + 750, 48, 28, palette, "ink", "surface")
            self.text(board, "Local document companion", "A deliberate structure for coordinated work.", x + 24, y + 828, 550, 18,
                      color=palette + "/ink", bg=palette + "/surface")
            self.rect(board, "Accent example", x + 24, y + 878, 160, 48, palette + "/accent", 4)
            self.text(board, "Accent label", "View workflow", x + 38, y + 890, 140, 16, "600",
                      palette + "/accent_on", palette + "/accent")
            self.text(board, "Disclosure", "LOCAL CONCEPT — NOT DEPLOYED", x + 208, y + 890, 340, 14,
                      color=palette + "/ink", bg=palette + "/surface")
        return board

    def actual_sizes_board(self, concept, palette, *, origin=2400, size=None):
        """size: the concept's size-check row; its measured minimum replaces the declared one."""
        key = concept["id"]
        board = self.board("Actual sizes and backgrounds — " + key, 0, origin, 768, 620, key + "/paper")
        self.text(board, "Title", "Actual-size checks / " + self.product, 24, origin + 18, 720, 28, "600", key + "/ink", key + "/paper")
        x = 30
        for px in c.SIZES:
            self.symbol(board, concept, x, origin + 100, px, key + "/ink", key + "/accent")
            self.text(board, "Size label", str(px) + " px", x, origin + 184, 85, 16, color=key + "/ink", bg=key + "/paper")
            x += 132
        note = (size_check.board_note(size) if size else
                f'Proposed symbol minimum: {concept["minimum_symbol_px"]}px. Lower sizes remain shown for inspection.')
        self.text(board, "Size limitation", note, 24, origin + 226, 720, 16,
                  color=key + "/ink", bg=key + "/paper", max_lines=3)
        for index, width in enumerate((160, 320)):
            self.lockup_fit(board, concept, self.product, 30 + index * 290, origin + 300, width, key, colour=True)
            self.text(board, "Lockup size", str(width) + "px lockup", 30 + index * 290, origin + 388, 230, 16,
                      color=key + "/ink", bg=key + "/paper")
        self.rect(board, "Dark application", 24, origin + 444, 720, 150, key + "/ink")
        self.lockup(board, concept, self.product, 48, origin + 484, 56, 40, key, "paper", "ink", True)
        self.text(board, "Reverse companion", "Reverse / local preview only", 402, origin + 510, 310, 16,
                  color=key + "/paper", bg=key + "/ink")
        return board

    def lockup_fit(self, board, concept, name, x, y, width, key, fg="ink", bg="paper", colour=False):
        # Native shared typography sizes. Choose the largest supported size that
        # leaves honest horizontal clear space; never squeeze/stretch glyphs.
        for size in (64, 50, 40, 28, 22, 18, 16, 14):
            symbol = size * 1.4
            needed = symbol * 1.25 + self.fonts[concept["wordmark_weight"]].width(name, size) + 8
            if needed <= width:
                self.lockup(board, concept, name, x, y, symbol, size, key, fg, bg, colour)
                return
        raise ValueError("wordmark does not fit supported lockup width")

    def contract_board(self):
        # New critic's neutral labelled fictional board. Truth lives host-only.
        board = self.board("Aster / contract board", 2200, 0, 960, 700)
        x, y = 2228, 28
        self.text(board, "Contract title", "Aster / inspection cells", x, y, 884, 28, "600")
        for i, label in enumerate("ABCDE"):
            bx, by = x + (i % 3) * 300, y + 90 + (i // 3) * 280
            self.text(board, "Cell label", label, bx, by, 260, 22, "600")
            if label == "A":
                # Deliberate visual truncation, not a normal generated-logo path.
                obj = self.text(board, "Wordmark/A", "Aster", bx, by + 64, 200, 50, "600", logo=True)
                obj["width"] = 50
                obj["selrect"]["width"] = 50
                obj["selrect"]["x2"] = bx + 50
                obj["position-data"][0]["text"] = "Ast"
                obj["position-data"][0]["width"] = self.fonts["600"].width("Ast", 50)
                self.changes[-1] = p.add_obj(obj, self.page)
                self.text(board, "Nominal A", "Intended spelling: Aster", bx, by + 166, 260, 16)
            elif label == "B":
                self.rect(board, "Gap left", bx, by + 80, 16, 80, "mono/ink")
                self.rect(board, "Gap right", bx + 18, by + 80, 16, 80, "mono/ink")
                self.rect(board, "Small left", bx + 80, by + 80, 3.2, 16, "mono/ink")
                self.rect(board, "Small right", bx + 83.6, by + 80, 3.2, 16, "mono/ink")
                self.text(board, "Scale B", "80px original / 16px use", bx, by + 166, 260, 16)
            elif label == "C":
                self.palette("contract-low", {**MONO, "muted": "#AAAAAA"})
                self.text(board, "Companion C", "Workflow ready to inspect", bx, by + 80, 260, 16, color="contract-low/muted")
            elif label == "D":
                self.palette("contract-logo", {**MONO, "ink": "#777777"})
                self.text(board, "Wordmark/D", "Aster", bx, by + 80, 260, 50, "600", color="contract-logo/ink", logo=True)
                self.text(board, "Role D", "Logo/logotype, not body copy", bx, by + 166, 260, 16)
            else:
                self.text(board, "Companion E", "Inspect workflow", bx, by + 80, 260, 16)
        return board

    def coldread_boards(self, concepts, labels, palettes=None):
        """Caption-free boards per symbol: alone at 32 px and 128 px, and a 32-px header lockup.

        Board names carry only neutral labels and nothing but the symbol is drawn on the
        32/128 boards: no caption, idea or name. The header board adds the live wordmark
        for the same-name check only. Selected rounds use their palette, sketches monochrome.
        """
        palettes = palettes or {}
        widths = [math.ceil(16 + 32 + 8 + self.fonts[o["wordmark_weight"]].width(self.product, 22) + 8 + 16) for o in concepts]
        step = max(400, max(widths, default=0) + 80)
        for i, (label, concept) in enumerate(zip(labels, concepts, strict=True)):
            key = "mono"
            if concept["id"] in palettes:
                key = concept["id"]
                self.palette(key, palettes[key])
            accent = key + "/accent" if key != "mono" else None
            x = i * step
            glance = self.board(label + " glance", x, 0, 64, 64, key + "/paper")
            self.symbol(glance, concept, x + 16, 16, 32, key + "/ink", accent)
            close = self.board(label + " close", x, 100, 192, 192, key + "/paper")
            self.symbol(close, concept, x + 32, 132, 128, key + "/ink", accent)
            header = self.board(label + " header", x, 340, max(320, widths[i]), 64, key + "/paper")
            self.lockup(header, concept, self.product, x + 16, 356, 32, 22, key, colour=accent is not None)
        return self.boards

    def final_boards(self, brief, concept, palette, size=None):
        key = concept["id"]
        self.palette(key, palette)
        x = 0
        specs = [("primary", 320, 96, "ink", brief["product"]),
                 ("secondary-ai", 360, 96, "ink", brief["secondary_name"]),
                 ("monochrome", 320, 96, "mono/ink", brief["product"]),
                 ("reverse", 320, 96, "paper", brief["product"])]
        for name, w, h, fg, label in specs:
            board = self.board(name, x, 0, w, h, transparent=True)
            pal, role = ("mono", "ink") if "/" in fg else (key, fg)
            # Colour versions draw accent-toned parts in the accent; monochrome stays one colour.
            self.lockup_fit(board, concept, label, x + 12, 22, w - 24, pal, role, "paper" if role != "paper" else "ink",
                            colour=pal == key)
            x += 430
        symbol = self.board("symbol", 0, 180, 128, 128, transparent=True)
        self.symbol(symbol, concept, 12, 192, 104, key + "/ink", key + "/accent")
        mono = self.board("symbol-mono", 220, 180, 128, 128, transparent=True)
        self.symbol(mono, concept, 232, 192, 104)
        rev = self.board("symbol-reverse", 440, 180, 128, 128, transparent=True)
        self.symbol(rev, concept, 452, 192, 104, key + "/paper", key + "/accent")
        wordmark = self.board("wordmark", 660, 180, 300, 96, transparent=True)
        self.text(wordmark, "Live wordmark", brief["product"], 672, 194, 276, 50, concept["wordmark_weight"], key + "/ink", key + "/paper", True)
        avatar = self.board("avatar-512", 0, 440, 512, 512, key + "/ink")
        self.symbol(avatar, concept, 88, 528, 336, key + "/paper", key + "/accent")
        self.actual_sizes_board(concept, palette, origin=1100, size=size)
        return self.boards

    def state(self):
        return {"file_id": self.fid, "page_id": self.page, "team_id": self.file["team-id"],
                "project_id": self.file["project-id"], "name": self.file["name"],
                "objects": self.objects, "boards": self.boards, "colors": self.colors,
                "typographies": self.typos, "metrics": self.metrics, "schema_version": c.VERSION}


def _path_tokens(value):
    """Command letters and numbers of a Penpot/SVG path string.

    Penpot stores coordinates as float32 and rewrites separators, so a saved path
    is compared by commands exactly and numbers within float32 precision.
    """
    if not isinstance(value, str):
        return None
    tokens = re.findall(r"[MLCZ]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value)
    if "".join(re.findall(r"[^\s,]", value)) != "".join(tokens):
        return None
    return tokens


def same_path(expected, actual):
    a, b = _path_tokens(expected), _path_tokens(actual)
    if a is None or b is None or len(a) != len(b):
        return False
    for left, right in zip(a, b, strict=True):
        if left.isalpha() or right.isalpha():
            if left != right:
                return False
        elif abs(float(left) - float(right)) > 1e-3 * max(1.0, abs(float(left))):
            return False
    return True


def _same_vector(expected, actual):
    for key in ("name", "type", "selrect", "points", "transform", "fills", "parent-id", "frame-id"):
        if actual.get(key) != expected.get(key):
            return False
    if expected["type"] == "path":
        return same_path(expected["content"], actual.get("content"))
    return actual.get("content") == expected.get("content")


def _same_library_item(expected, actual):
    # Penpot adds server metadata such as modified-at; every declared field stays exact.
    return isinstance(actual, dict) and all(actual.get(k) == v for k, v in expected.items())


def source_checks(file, state):
    objects = file["data"]["pages-index"][state["page_id"]]["objects"]
    checks = {
        "owned_identity": file["id"] == state["file_id"] and file["project-id"] == state["project_id"] and file["team-id"] == state["team_id"],
        "board_geometry": all(objects.get(b["id"], {}).get("selrect") == b["selrect"] for b in state["boards"]),
        "exact_object_set": set(objects) == {p.ROOT} | {o["id"] for o in state["objects"]},
        "editable_vectors_geometry": all(_same_vector(o, objects.get(o["id"], {}))
                                         for o in state["objects"] if o["type"] in ("rect", "circle", "path")),
        "live_wordmark_text": all(objects.get(o["id"], {}).get("content") == o["content"] for o in state["objects"] if o["type"] == "text"),
        "native_text_cache": all(objects.get(o["id"], {}).get("position-data") == o["position-data"] for o in state["objects"] if o["type"] == "text"),
        "shared_colors": all(_same_library_item(v, file["data"].get("colors", {}).get(v["id"])) for v in state["colors"].values()),
        "shared_typography": all(_same_library_item(v, file["data"].get("typographies", {}).get(v["id"])) for v in state["typographies"].values()),
    }
    if not all(checks.values()):
        raise ValueError("fresh Penpot source mismatch: " + ",".join(k for k, v in checks.items() if not v))
    return {"revn": file["revn"], "checks": checks, "editable_objects": len(objects) - 1, "schema_version": c.VERSION}


def whole_words(row):
    """A rendered text is either its full value or a whole-word prefix plus an ellipsis."""
    rendered, full = row["text"], row.get("full_text", row["text"])
    if rendered == full:
        return True
    prefix = rendered[:-1].rstrip()
    normal = " ".join(full.split())
    return (rendered.endswith("\u2026") and bool(prefix) and normal.startswith(prefix)
            and (len(normal) == len(prefix) or not normal[len(prefix)].isalnum()))


def _words(value):
    return " ".join(str(value).split())


def saved_text_facts(row, objects, boards):
    """Text facts measured on the final saved object, not at creation.

    A text edited after it was created (the contract board's cell A shows 'Ast'
    for 'Aster') must show here: live content, rendered cache, final width and
    final position are all read back from the object that is saved.
    """
    obj = objects.get(row["id"])
    if obj is None or obj.get("type") != "text":
        return {"saved_object": False, "inside": False, "advance_fit": False, "rendered_matches_content": False,
                "content_matches_intended": False}
    content = _words(" ".join("".join(leaf.get("text", "") for leaf in paragraph["children"])
                               for paragraph in obj["content"]["children"][0]["children"]))
    cache = obj.get("position-data") or []
    rendered = _words(" ".join(str(line.get("text", "")) for line in cache))
    box, frame = obj["selrect"], (boards.get(obj.get("frame-id")) or {}).get("selrect")
    inside = bool(frame) and (box["x1"] >= frame["x1"] and box["y1"] >= frame["y1"]
                              and box["x2"] <= frame["x2"] and box["y2"] <= frame["y2"])
    return {"saved_object": True, "content_text": content, "rendered_text": rendered,
            "content_matches_intended": content == _words(row["text"]),
            "rendered_matches_content": rendered == content,
            "inside": inside, "advance_fit": bool(cache) and all(line["width"] <= box["width"] + .01 for line in cache),
            "final_width": box["width"]}


def measurements(state, palettes):
    objects = {o["id"]: o for o in state["objects"]}
    boards = {b["id"]: b for b in state["boards"]}
    rows = []
    for obj in state["metrics"]:
        ratio = c.contrast(obj["fg"], obj["bg"])
        rows.append({**obj, **saved_text_facts(obj, objects, boards), "contrast": ratio,
                     "companion_aa": None if obj["logo_exempt"] else ratio >= (3 if obj["font_size"] >= 24 else 4.5)})
    violations = [o for o in rows if not o["inside"] or not o["advance_fit"] or o["companion_aa"] is False
                  or not whole_words(o) or not o["rendered_matches_content"] or not o["content_matches_intended"]]
    return {"text": rows, "violations": violations,
            "measured_from": "final saved objects: live content, rendered text cache, final width and position",
            "palette": {name: {a + "/" + b: c.contrast(pal[a], pal[b]) for a, b in
                         (("ink", "paper"), ("muted", "paper"), ("ink", "surface"), ("accent_on", "accent"), ("accent", "paper"), ("accent", "ink"))}
                        for name, pal in palettes.items()},
            "logo_exemption": "WCAG logotypes exempt; visibility and actual-size usability still require visual checks.",
            "not_verified": ["aesthetic quality", "trademark clearance", "runtime UI accessibility", "complex-script shaping", "publication"]}
