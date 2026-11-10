"""Stage 2/3 deterministic colour engine (`foundation/color.py`).

Generates complete, valid DTCG `tokens.json` files from anchor hues and fixed brief constraints
using perceptual OKLCH curves, chroma tapering toward white and black, explicit sRGB gamut clamping
with every clamp recorded on the token, and hex fallback emission.

Invariants (AGENTS rule 12, deterministic first):
- Lightness steps across each ramp are even in perceptual OKLCH `L`, not sRGB.
- Chroma tapers toward both lightness extremes (`L -> 0` and `L -> 1`) via `4 * L * (1 - L)`.
- Every emitted colour is clamped into the sRGB gamut `[0, 1]` in linear sRGB; any clamp is
  recorded in `$description` (`[srgb-clamp: requested_C=... -> clamped_C=... (delta=...)]`),
  never silently applied.
- Dark theme is generated from its own perceptual lightness curve and reduced chroma factor
  (`DARK_CHROMA_FACTOR`), never by reversing or inverting the light ramp.
- Semantic roles (`good`, `risk`, `warn`, `info`, `accent`) and neutral ramps (`surface`, `ink`,
  `line`, `ramp`) are generated as a coordinated set so signal pairs (`good`/`risk`) stay separated
  in perceptual lightness and survive protanopia, deuteranopia, and tritanopia simulation.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from . import contracts

RAMP_STEPS: tuple[str, ...] = ("100", "200", "300", "400", "500", "600", "700", "800", "900")

# Light ramp: 9 even steps of -0.1000 in perceptual OKLCH lightness L (0.95 down to 0.15).
LIGHT_RAMP_L: tuple[float, ...] = (0.95, 0.85, 0.75, 0.65, 0.55, 0.45, 0.35, 0.25, 0.15)

# Dark ramp: 9 even steps of +0.0925 in perceptual OKLCH lightness L (0.14 up to 0.88).
# Distinct from reversed(LIGHT_RAMP_L) and from (1 - LIGHT_RAMP_L): deeper dark floor and softer
# highlight ceiling prevent dark-surface washout and halation.
DARK_RAMP_L: tuple[float, ...] = (0.14, 0.2325, 0.325, 0.4175, 0.51, 0.6025, 0.695, 0.7875, 0.88)

# Dark theme chroma reduction factor at equal lightness to prevent neon glow on dark surfaces.
DARK_CHROMA_FACTOR: float = 0.78

DEFAULT_ANCHOR_HUES: dict[str, float] = {
    "neutral": 250.0,
    "accent": 155.0,
    "good": 152.0,
    "risk": 24.0,
    "warn": 72.0,
    "info": 245.0,
}

DEFAULT_RAMP_PEAK_CHROMA: dict[str, float] = {
    "neutral": 0.016,
    "accent": 0.20,
    "good": 0.20,
    "risk": 0.20,
    "warn": 0.18,
    "info": 0.20,
}

CLAMP_NOTE_RE = re.compile(
    r"\[srgb-clamp:\s*requested_C=([0-9.]+)\s*->\s*clamped_C=([0-9.]+)\s*\(delta=(-[0-9.]+)\)\]"
)


@dataclass(frozen=True)
class ClampRecord:
    """Record of an OKLCH colour tested against (and if needed clamped into) the sRGB gamut."""

    L: float
    requested_C: float
    clamped_C: float
    H: float
    hex: str
    clamped: bool
    delta_C: float

    def format_tag(self) -> str:
        if not self.clamped:
            return ""
        return (
            f"[srgb-clamp: requested_C={self.requested_C:.6f} -> "
            f"clamped_C={self.clamped_C:.6f} (delta={self.delta_C:.6f})]"
        )


def hex_to_srgb_01(hex_str: str) -> tuple[float, float, float]:
    """Convert `#RRGGBB` into normalized sRGB `(r, g, b)` in `0.0..1.0`."""
    s = hex_str.strip()
    if not re.match(r"^#[0-9A-Fa-f]{6}$", s):
        raise ValueError(f"Expected #RRGGBB hex string, got {hex_str!r}")
    return (int(s[1:3], 16) / 255.0, int(s[3:5], 16) / 255.0, int(s[5:7], 16) / 255.0)


def srgb_01_to_linear(c: float) -> float:
    """IEC 61966-2-1 transfer function from gamma-encoded sRGB `0..1` to linear light."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb_01(c: float) -> float:
    """IEC 61966-2-1 transfer function from linear light `0..1` to gamma-encoded sRGB."""
    c_clamped = min(1.0, max(0.0, c))
    return 12.92 * c_clamped if c_clamped <= 0.0031308 else 1.055 * (c_clamped ** (1.0 / 2.4)) - 0.055


def linear_srgb_to_oklab(r_lin: float, g_lin: float, b_lin: float) -> tuple[float, float, float]:
    """Convert linear sRGB `(r, g, b)` to Björn Ottosson Oklab `(L, a, b)`."""
    l_ = 0.4122214708 * r_lin + 0.5363325363 * g_lin + 0.0514459929 * b_lin
    m_ = 0.2119034982 * r_lin + 0.6806995451 * g_lin + 0.1073969566 * b_lin
    s_ = 0.0883024619 * r_lin + 0.2817188376 * g_lin + 0.6299787005 * b_lin
    l_c = math.copysign(abs(l_) ** (1.0 / 3.0), l_)
    m_c = math.copysign(abs(m_) ** (1.0 / 3.0), m_)
    s_c = math.copysign(abs(s_) ** (1.0 / 3.0), s_)
    L = 0.2104542553 * l_c + 0.7936177850 * m_c - 0.0040720468 * s_c
    a = 1.9779984951 * l_c - 2.4285922050 * m_c + 0.4505937099 * s_c
    b = 0.0259040371 * l_c + 0.7827717662 * m_c - 0.8086757660 * s_c
    return (L, a, b)


def hex_to_oklch(hex_str: str) -> tuple[float, float, float]:
    """Convert `#RRGGBB` to `(L, C, H_deg)` in OKLCH."""
    r, g, b = (srgb_01_to_linear(c) for c in hex_to_srgb_01(hex_str))
    L, a, b_lab = linear_srgb_to_oklab(r, g, b)
    C = math.hypot(a, b_lab)
    H = (math.degrees(math.atan2(b_lab, a)) % 360.0) if C > 1e-7 else 0.0
    return (L, C, H)


def oklch_to_oklab(L: float, C: float, H: float) -> tuple[float, float, float]:
    """Convert `(L, C, H_deg)` in OKLCH to `(L, a, b)` in Oklab."""
    rad = math.radians(float(H) % 360.0)
    return (float(L), float(C) * math.cos(rad), float(C) * math.sin(rad))


def oklch_to_linear_srgb(L: float, C: float, H: float) -> tuple[float, float, float]:
    """Convert `(L, C, H_deg)` in OKLCH to unclipped linear sRGB `(r_lin, g_lin, b_lin)`."""
    L_val, a, b = oklch_to_oklab(L, C, H)
    l_ = L_val + 0.3963377774 * a + 0.2158037573 * b
    m_ = L_val - 0.1055613458 * a - 0.0638541728 * b
    s_ = L_val - 0.0894841775 * a - 1.2914855480 * b
    l3 = l_ * l_ * l_
    m3 = m_ * m_ * m_
    s3 = s_ * s_ * s_
    r_lin = +4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3
    g_lin = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3
    b_lin = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3
    return (r_lin, g_lin, b_lin)


def in_srgb_gamut(L: float, C: float, H: float, *, tol: float = 1e-6) -> bool:
    """True when `OKLCH(L, C, H)` maps inside the linear sRGB unit cube `[0, 1]^3` within `tol`."""
    if not (0.0 - tol <= L <= 1.0 + tol) or C < -tol:
        return False
    r_lin, g_lin, b_lin = oklch_to_linear_srgb(L, max(0.0, C), H)
    return (
        -tol <= r_lin <= 1.0 + tol
        and -tol <= g_lin <= 1.0 + tol
        and -tol <= b_lin <= 1.0 + tol
    )


def oklch_to_hex(L: float, C: float, H: float) -> str:
    """Convert in-gamut `OKLCH(L, C, H)` to uppercase `#RRGGBB`."""
    r_lin, g_lin, b_lin = oklch_to_linear_srgb(L, C, H)
    r = int(round(linear_to_srgb_01(r_lin) * 255.0))
    g = int(round(linear_to_srgb_01(g_lin) * 255.0))
    b = int(round(linear_to_srgb_01(b_lin) * 255.0))
    return f"#{min(255, max(0, r)):02X}{min(255, max(0, g)):02X}{min(255, max(0, b)):02X}"


def max_srgb_chroma(L: float, H: float) -> float:
    """Maximum chroma `C >= 0` at `(L, H)` whose 6-decimal-place rounded OKLCH stays in sRGB."""
    L_r = round(float(L), 6)
    H_r = round(float(H) % 360.0, 4)
    if L_r <= 0.0 or L_r >= 1.0:
        return 0.0
    lo, hi = 0.0, 0.40
    for _ in range(44):
        mid = 0.5 * (lo + hi)
        if in_srgb_gamut(L_r, mid, H_r, tol=0.0):
            lo = mid
        else:
            hi = mid
    c_floor = math.floor(lo * 1_000_000.0) / 1_000_000.0
    while c_floor > 0.0 and not in_srgb_gamut(L_r, c_floor, H_r, tol=0.0):
        c_floor = round(max(0.0, c_floor - 1e-6), 6)
    return c_floor


def clamp_oklch_to_srgb(L: float, C: float, H: float) -> ClampRecord:
    """Clamp `(L, C, H)` into sRGB gamut by reducing chroma `C` at fixed `(L, H)` and record any clamp."""
    L_r = round(min(1.0, max(0.0, float(L))), 6)
    H_r = round(float(H) % 360.0, 4)
    req_c = round(max(0.0, float(C)), 6)
    limit_c = max_srgb_chroma(L_r, H_r)
    if req_c > limit_c + 1e-6:
        clamped_c = limit_c
        was_clamped = True
        delta_c = round(clamped_c - req_c, 6)
    else:
        clamped_c = min(req_c, limit_c)
        was_clamped = False
        delta_c = 0.0
    hex_val = oklch_to_hex(L_r, clamped_c, H_r)
    return ClampRecord(
        L=L_r,
        requested_C=req_c,
        clamped_C=clamped_c,
        H=H_r,
        hex=hex_val,
        clamped=was_clamped,
        delta_C=delta_c,
    )


def chroma_taper(L: float) -> float:
    """Parabolic perceptual chroma taper `4 * L * (1 - L)` peaking at `L = 0.5` and vanishing at 0 and 1."""
    L_c = min(1.0, max(0.0, float(L)))
    return round(4.0 * L_c * (1.0 - L_c), 6)


def target_chroma(L: float, peak_chroma: float, *, theme: str = "light") -> float:
    """Requested chroma before gamut clamping for lightness `L`, `peak_chroma`, and `theme`."""
    if theme not in ("light", "dark"):
        raise ValueError(f"theme must be 'light' or 'dark', got {theme!r}")
    factor = DARK_CHROMA_FACTOR if theme == "dark" else 1.0
    return round(float(peak_chroma) * factor * chroma_taper(L), 6)


def make_color_token(L: float, C: float, H: float, *, description: str = "") -> dict[str, Any]:
    """Build a closed-schema DTCG colour token in OKLCH with hex fallback and recorded sRGB clamp."""
    rec = clamp_oklch_to_srgb(L, C, H)
    token: dict[str, Any] = {
        "$value": {
            "colorSpace": "oklch",
            "components": [rec.L, rec.clamped_C, rec.H],
            "hex": rec.hex,
        }
    }
    notes = [s for s in (description.strip(), rec.format_tag()) if s]
    if notes:
        token["$description"] = " ".join(notes)
    return token


def generate_ramp(
    hue: float,
    *,
    peak_chroma: float = 0.18,
    theme: str = "light",
    role: str = "accent",
) -> dict[str, dict[str, Any]]:
    """Generate a 9-step (`100`..`900`) perceptual OKLCH ramp for `theme` (`light` or `dark`)."""
    if theme not in ("light", "dark"):
        raise ValueError(f"theme must be 'light' or 'dark', got {theme!r}")
    curve = LIGHT_RAMP_L if theme == "light" else DARK_RAMP_L
    out: dict[str, dict[str, Any]] = {}
    for step, L in zip(RAMP_STEPS, curve, strict=True):
        req_c = target_chroma(L, peak_chroma, theme=theme)
        out[step] = make_color_token(
            L,
            req_c,
            hue,
            description=f"{theme} {role} ramp {step} (L={L:.4f}, target_C={req_c:.4f})",
        )
    return out


def generate_semantic_set(
    anchor_hues: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate coordinated `light` and `dark` token trees (`surface`, `ink`, `line`, `semantic`, `ramp`)."""
    hues = dict(DEFAULT_ANCHOR_HUES)
    if anchor_hues:
        for k, v in anchor_hues.items():
            if k in hues and v is not None:
                hues[k] = float(v) % 360.0

    n_h = hues["neutral"]
    acc_h = hues["accent"]
    good_h = hues["good"]
    risk_h = hues["risk"]
    warn_h = hues["warn"]
    info_h = hues["info"]

    light_group: dict[str, Any] = {
        "surface": {
            "canvas": make_color_token(0.97, 0.005, n_h, description="light canvas surface"),
            "raised": make_color_token(1.0, 0.0, n_h, description="light raised card surface"),
            "sunken": make_color_token(0.94, 0.007, n_h, description="light sunken well surface"),
            "ghost_fill": make_color_token(
                0.955, 0.005, n_h, description="light text-button ghost fill [ui-role:text_button_fill]"
            ),
        },
        "ink": {
            "primary": make_color_token(0.20, 0.012, n_h, description="light primary body ink"),
            "secondary": make_color_token(0.36, 0.012, n_h, description="light secondary body ink"),
            "muted": make_color_token(0.47, 0.010, n_h, description="light muted caption ink"),
            "heading": make_color_token(
                0.53, 0.012, n_h, description="light display heading ink [text-scale:large]"
            ),
        },
        "line": {
            "border": make_color_token(
                0.55, 0.012, n_h, description="light control field border [ui-role:field_border]"
            ),
            "strong": make_color_token(
                0.46, 0.014, n_h, description="light strong boundary [ui-role:field_border]"
            ),
            "focus": make_color_token(
                0.48, 0.16, acc_h, description="light focus ring [ui-role:focus_ring]"
            ),
        },
        "semantic": {
            "good": {
                "text": make_color_token(0.50, 0.15, good_h, description="light good status text"),
                "ui": make_color_token(0.56, 0.15, good_h, description="light good status icon [ui-role:icon]"),
            },
            "risk": {
                "text": make_color_token(0.37, 0.16, risk_h, description="light risk status text"),
                "ui": make_color_token(0.44, 0.17, risk_h, description="light risk status icon [ui-role:icon]"),
            },
            "warn": {
                "text": make_color_token(0.43, 0.13, warn_h, description="light warn status text"),
                "ui": make_color_token(0.50, 0.14, warn_h, description="light warn status icon [ui-role:icon]"),
            },
            "info": {
                "text": make_color_token(0.45, 0.14, info_h, description="light info status text"),
                "ui": make_color_token(0.52, 0.15, info_h, description="light info status icon [ui-role:icon]"),
            },
            "accent": {
                "text": make_color_token(0.44, 0.15, acc_h, description="light accent link text"),
                "ui": make_color_token(0.50, 0.16, acc_h, description="light accent control border [ui-role:icon]"),
                "solid": make_color_token(
                    0.42, 0.15, acc_h, description="light primary solid button fill [ui-role:solid_control]"
                ),
                "on_solid": make_color_token(
                    0.985, 0.005, acc_h, description="light text on primary solid button [on:accent.solid]"
                ),
            },
        },
        "ramp": {
            role: generate_ramp(hues[role], peak_chroma=DEFAULT_RAMP_PEAK_CHROMA[role], theme="light", role=role)
            for role in ("neutral", "accent", "good", "risk", "warn", "info")
        },
    }

    dark_group: dict[str, Any] = {
        "surface": {
            "canvas": make_color_token(0.15, 0.008, n_h, description="dark canvas surface"),
            "raised": make_color_token(0.19, 0.010, n_h, description="dark raised card surface"),
            "sunken": make_color_token(0.12, 0.006, n_h, description="dark sunken well surface"),
            "ghost_fill": make_color_token(
                0.17, 0.008, n_h, description="dark text-button ghost fill [ui-role:text_button_fill]"
            ),
        },
        "ink": {
            "primary": make_color_token(0.93, 0.008, n_h, description="dark primary body ink"),
            "secondary": make_color_token(0.79, 0.010, n_h, description="dark secondary body ink"),
            "muted": make_color_token(0.68, 0.010, n_h, description="dark muted caption ink"),
            "heading": make_color_token(
                0.61, 0.010, n_h, description="dark display heading ink [text-scale:large]"
            ),
        },
        "line": {
            "border": make_color_token(
                0.60, 0.012, n_h, description="dark control field border [ui-role:field_border]"
            ),
            "strong": make_color_token(
                0.70, 0.014, n_h, description="dark strong boundary [ui-role:field_border]"
            ),
            "focus": make_color_token(
                0.72, 0.13, acc_h, description="dark focus ring [ui-role:focus_ring]"
            ),
        },
        "semantic": {
            "good": {
                "text": make_color_token(0.83, 0.115, good_h, description="dark good status text"),
                "ui": make_color_token(0.77, 0.115, good_h, description="dark good status icon [ui-role:icon]"),
            },
            "risk": {
                "text": make_color_token(0.70, 0.13, risk_h, description="dark risk status text"),
                "ui": make_color_token(0.65, 0.13, risk_h, description="dark risk status icon [ui-role:icon]"),
            },
            "warn": {
                "text": make_color_token(0.78, 0.11, warn_h, description="dark warn status text"),
                "ui": make_color_token(0.71, 0.11, warn_h, description="dark warn status icon [ui-role:icon]"),
            },
            "info": {
                "text": make_color_token(0.75, 0.11, info_h, description="dark info status text"),
                "ui": make_color_token(0.68, 0.11, info_h, description="dark info status icon [ui-role:icon]"),
            },
            "accent": {
                "text": make_color_token(0.76, 0.12, acc_h, description="dark accent link text"),
                "ui": make_color_token(0.69, 0.12, acc_h, description="dark accent control border [ui-role:icon]"),
                "solid": make_color_token(
                    0.73, 0.12, acc_h, description="dark primary solid button fill [ui-role:solid_control]"
                ),
                "on_solid": make_color_token(
                    0.14, 0.010, acc_h, description="dark text on primary solid button [on:accent.solid]"
                ),
            },
        },
        "ramp": {
            role: generate_ramp(hues[role], peak_chroma=DEFAULT_RAMP_PEAK_CHROMA[role], theme="dark", role=role)
            for role in ("neutral", "accent", "good", "risk", "warn", "info")
        },
    }

    return {"light": light_group, "dark": dark_group}


def extract_clamp_records(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every `[srgb-clamp: ...]` record attached to colour tokens in `tokens`."""
    records: list[dict[str, Any]] = []

    def _walk(node: Any, prefix: str = "") -> None:
        if not isinstance(node, dict):
            return
        if "$value" in node:
            desc = str(node.get("$description") or "")
            m = CLAMP_NOTE_RE.search(desc)
            if m:
                val = node.get("$value") or {}
                records.append(
                    {
                        "token": prefix,
                        "requested_C": float(m.group(1)),
                        "clamped_C": float(m.group(2)),
                        "delta_C": float(m.group(3)),
                        "components": list(val.get("components") or []),
                        "hex": val.get("hex", ""),
                    }
                )
            return
        for k, v in node.items():
            if not str(k).startswith("$"):
                _walk(v, f"{prefix}.{k}" if prefix else str(k))

    _walk(tokens.get("colour") or {}, "colour")
    return records


def generate_tokens(
    product: str,
    *,
    anchor_hues: dict[str, float] | None = None,
    anchors: dict[str, float] | None = None,
    accent_hex: str | None = None,
    status: str = "draft",
    approved_by: str | None = None,
    date: str | None = None,
    font_sans: list[str] | None = None,
    font_mono: list[str] | None = None,
    body_px: float = 16.0,
    scale_ratio: float = 1.25,
) -> dict[str, Any]:
    """Generate a complete, deterministic DTCG `tokens.json` for `product`."""
    hues = dict(DEFAULT_ANCHOR_HUES)
    if accent_hex:
        _L, _C, h_from_hex = hex_to_oklch(accent_hex)
        hues["accent"] = round(h_from_hex, 4)
    merged_anchors = anchor_hues if anchor_hues is not None else anchors
    if merged_anchors:
        for k, v in merged_anchors.items():
            if k in hues and v is not None:
                hues[k] = round(float(v) % 360.0, 4)

    themes = generate_semantic_set(hues)
    light = themes["light"]

    eff_date = date or "2026-11-09"

    def part_ext(part: str) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "part": part,
            "status": status,
            "date": eff_date,
        }
        if status == "approved":
            meta["approved_by"] = approved_by or "design"
        elif approved_by is not None:
            meta["approved_by"] = approved_by
        return {contracts.EXT: meta}

    sans_stack = list(font_sans) if font_sans is not None else ["IBM Plex Sans", "system-ui", "sans-serif"]
    mono_stack = list(font_mono) if font_mono is not None else ["IBM Plex Mono", "ui-monospace", "monospace"]

    base_px = round(float(body_px), 2)
    ratio = float(scale_ratio)
    sm_px = round(base_px / ratio, 2)
    lg_px = round(base_px * ratio, 2)
    xl_px = round(lg_px * ratio, 2)
    xxl_px = round(xl_px * ratio, 2)

    return {
        "$description": f"{product} foundation design tokens (OKLCH light + dark).",
        "$extensions": {
            contracts.EXT: {
                "product": product,
                "format": contracts.FORMAT,
            }
        },
        "colour": {
            "$type": "color",
            "$extensions": part_ext("colour"),
            # Top-level canonical surface/ink/accent tokens for direct references (e.g. {colour.ink}).
            "ink": dict(light["ink"]["primary"]),
            "paper": dict(light["surface"]["canvas"]),
            "surface": dict(light["surface"]["raised"]),
            "muted": dict(light["ink"]["muted"]),
            "accent": dict(light["semantic"]["accent"]["solid"]),
            "accent_on": dict(light["semantic"]["accent"]["on_solid"]),
            "light": light,
            "dark": themes["dark"],
        },
        "type": {
            "$extensions": part_ext("type"),
            "family": {
                "$type": "fontFamily",
                "sans": {"$value": sans_stack},
                "mono": {"$value": mono_stack},
            },
            "scale": {
                "$type": "dimension",
                "sm": {"$value": {"value": sm_px, "unit": "px"}},
                "base": {"$value": {"value": base_px, "unit": "px"}},
                "lg": {"$value": {"value": lg_px, "unit": "px"}},
                "xl": {"$value": {"value": xl_px, "unit": "px"}},
                "2xl": {"$value": {"value": xxl_px, "unit": "px"}},
            },
            "weight": {
                "$type": "fontWeight",
                "regular": {"$value": 400},
                "medium": {"$value": 500},
                "bold": {"$value": 700},
            },
            "lineHeight": {
                "$type": "number",
                "tight": {"$value": 1.25},
                "normal": {"$value": 1.4},
            },
        },
        "spacing": {
            "$type": "dimension",
            "$extensions": part_ext("spacing"),
            "0": {"$value": {"value": 0, "unit": "px"}},
            "1": {"$value": {"value": 8, "unit": "px"}},
            "2": {"$value": {"value": 16, "unit": "px"}},
            "3": {"$value": {"value": 24, "unit": "px"}},
            "4": {"$value": {"value": 32, "unit": "px"}},
            "6": {"$value": {"value": 48, "unit": "px"}},
            "8": {"$value": {"value": 64, "unit": "px"}},
        },
        "radius": {
            "$type": "dimension",
            "$extensions": part_ext("radius"),
            "sm": {"$value": {"value": 4, "unit": "px"}},
            "md": {"$value": {"value": 8, "unit": "px"}},
            "lg": {"$value": {"value": 12, "unit": "px"}},
        },
        "elevation": {
            "$type": "shadow",
            "$extensions": part_ext("elevation"),
            "card": {
                "$value": {
                    "color": "{colour.ink}",
                    "offsetX": {"value": 0, "unit": "px"},
                    "offsetY": {"value": 2, "unit": "px"},
                    "blur": {"value": 8, "unit": "px"},
                    "spread": {"value": 0, "unit": "px"},
                }
            },
        },
        "motion": {
            "$extensions": part_ext("motion"),
            "fast": {"$type": "duration", "$value": {"value": 150, "unit": "ms"}},
            "normal": {"$type": "duration", "$value": {"value": 240, "unit": "ms"}},
            "ease": {"$type": "cubicBezier", "$value": [0.2, 0.0, 0.0, 1.0]},
        },
    }


DEFAULT_ANCHORS = DEFAULT_ANCHOR_HUES
