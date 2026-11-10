"""Stage 2's contact sheet: the first views of every screen and state at one width, in one labelled PNG.

Temper's tool-free image input takes exactly one PNG per model call, and a script node's output (which carries
the PNG to the model node as base64) is capped at 256,000 characters. So build() tiles the sheet width's
captures (the app file's sheet_width, e.g. the 390 phone) in a grid no longer than LONG_EDGE px, each tile
labelled with its capture id, then quantizes and shrinks the sheet until it fits BUDGET bytes. Host only (Pillow).
"""
from __future__ import annotations

import io
import math
from pathlib import Path

from .workspace import Workspace

LONG_EDGE = 1568          # the model provider's long-edge size before it downsamples
BUDGET = 180_000          # raw PNG bytes: base64 (4/3) plus JSON must stay under the 256,000-character output cap
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
GAP = 6


class SheetError(RuntimeError):
    """The sheet could not be built within the budget."""


try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as _pil_exc:
    raise SheetError(
        "Pillow (PIL) is required to build contact sheets; install pillow in the active environment"
    ) from _pil_exc


def _require_pillow() -> None:
    try:
        from PIL import (  # noqa: I001, PLC0415
            Image as _img,
            ImageDraw as _draw_mod,
            ImageFont as _font_mod,
        )
    except ImportError as exc:
        raise SheetError(
            "Pillow (PIL) is required to build contact sheets; install pillow in the active environment"
        ) from exc
    if Image is None or ImageDraw is None or ImageFont is None or _img is None or _draw_mod is None or _font_mod is None:
        raise SheetError(
            "Pillow (PIL) is required to build contact sheets; install pillow in the active environment"
        )


def _font(size: int):
    if not Path(FONT).is_file():
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(FONT, size)
    except OSError as exc:
        raise SheetError(f"failed to load font {FONT}: {exc}") from exc


def _layout(n: int, tile_w: int, tile_h: int, label_h: int, long_edge: int) -> tuple[int, float]:
    """Columns and scale that make the tiles largest while the sheet's long edge stays within long_edge."""
    best = (1, 0.0)
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        scale = min((long_edge - GAP * (cols + 1)) / (cols * tile_w),
                    (long_edge - GAP * (rows + 1) - rows * label_h) / (rows * tile_h))
        if scale > best[1]:
            best = (cols, scale)
    return best


def _draw(tiles: list[tuple[str, Image.Image]], long_edge: int) -> Image.Image:
    tile_w, tile_h = tiles[0][1].size
    label_h = 18
    cols, scale = _layout(len(tiles), tile_w, tile_h, label_h, long_edge)
    w, h = max(1, int(tile_w * scale)), max(1, int(tile_h * scale))
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (GAP + cols * (w + GAP), GAP + rows * (h + label_h + GAP)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(tiles):
        x = GAP + (i % cols) * (w + GAP)
        y = GAP + (i // cols) * (h + label_h + GAP)
        size = 12
        font = _font(size)
        while size > 7 and draw.textlength(label, font=font) > w:
            size -= 1
            font = _font(size)
        draw.rectangle([x, y, x + w - 1, y + label_h - 2], fill=(20, 20, 20))
        draw.text((x + 3, y + 2), label, fill="white", font=font)
        sheet.paste(img.convert("RGB").resize((w, h), Image.LANCZOS), (x, y + label_h))
        draw.rectangle([x - 1, y + label_h - 1, x + w, y + label_h + h], outline=(120, 120, 120))
    return sheet


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
        buf, format="PNG", optimize=True)
    return buf.getvalue()


def build(captures: list[tuple[str, Path]], out: Path, budget: int = BUDGET) -> dict:
    """Write the sheet PNG for [(capture id, png path)], in order; return its size and tile order."""
    _require_pillow()
    if not captures:
        raise SheetError("no captures at the sheet width")
    tiles = []
    for cid, path in captures:
        if isinstance(path, Path) and path.parent.name == "captures" and path.parent.parent.name == "02-existing":
            ws = Workspace(path.parents[2], step="existing_collect")
            stream: object = io.BytesIO(ws.read_bytes(path))
        elif isinstance(path, Path) and path.parent.name == "views" and len(path.parents) >= 3 and path.parents[2].name == "06-checks":
            ws = Workspace(path.parents[3], step="review_collect")
            stream = io.BytesIO(ws.read_bytes(path))
        else:
            stream = path
        try:
            with Image.open(stream) as img:
                tiles.append((cid, img.copy()))
        except Exception as exc:
            raise SheetError(f"failed to decode PNG capture {cid!r} ({path}): {exc}") from exc
    sizes = {img.size for _, img in tiles}
    if len(sizes) != 1:
        raise SheetError(f"captures at the sheet width differ in size: {sorted(sizes)}")
    edge = LONG_EDGE
    while edge >= 600:
        data = _png(_draw(tiles, edge))
        if len(data) <= budget:
            out.write_bytes(data)
            with Image.open(io.BytesIO(data)) as img:
                w, h = img.size
            return {"file": out.name, "bytes": len(data), "width": w, "height": h,
                    "tiles": [cid for cid, _ in tiles]}
        edge = int(edge * 0.9)
    raise SheetError(f"the sheet of {len(tiles)} captures does not fit {budget} bytes even at 600 px")
