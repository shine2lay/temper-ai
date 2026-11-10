"""Shared WCAG 2.2 AA contrast ratio and large-text / non-text UI rules.

Single source of truth imported by both `app_screen/checks_rules.py` (Stage 6a rendered checks)
and `foundation/proof.py` (Stage 3 deterministic token battery) so the two batteries cannot drift.
"""
from __future__ import annotations

import re
from typing import Any

_HEX6_RE = re.compile(r"^#([0-9A-Fa-f]{6})$")
_HEX3_RE = re.compile(r"^#([0-9A-Fa-f]{3})$")
_RGB_RE = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*[,/]\s*(?:1(?:\.0+)?|0?\.\d+|\d+%))?\s*\)$"
)

# Roles whose fill does not identify the control because the text label itself identifies it (WCAG 1.4.11).
UI_EXEMPT_ROLES: frozenset[str] = frozenset({"text_button_fill", "ghost_fill", "button_text_fill"})


def parse_color_rgb(value: Any) -> tuple[int, int, int]:
    """Parse `#RRGGBB`, `#RGB`, `rgb(r, g, b)` or `(r, g, b)` into 8-bit sRGB channels `0..255`."""
    if isinstance(value, (tuple, list)) and len(value) == 3:
        rgb = tuple(int(round(float(c))) for c in value)
        if all(0 <= c <= 255 for c in rgb):
            return (rgb[0], rgb[1], rgb[2])
        raise ValueError(f"RGB tuple out of 0..255 range: {value!r}")
    if not isinstance(value, str):
        raise ValueError(f"Unsupported colour representation: {value!r}")
    s = value.strip()
    m6 = _HEX6_RE.match(s)
    if m6:
        h = m6.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m3 = _HEX3_RE.match(s)
    if m3:
        h = m3.group(1)
        return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
    m_rgb = _RGB_RE.match(s)
    if m_rgb:
        rgb = (int(m_rgb.group(1)), int(m_rgb.group(2)), int(m_rgb.group(3)))
        if all(0 <= c <= 255 for c in rgb):
            return rgb
    raise ValueError(f"Cannot parse colour as #RRGGBB or rgb(r,g,b): {value!r}")


def srgb_channel_to_linear(channel_255: int | float) -> float:
    """Linearise one 8-bit sRGB channel `0..255` per WCAG 2.2 / IEC 61966-2-1."""
    v = float(channel_255) / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(color: Any) -> float:
    """WCAG 2.2 relative luminance `0.0..1.0` from `#RRGGBB`, `rgb(...)`, or `(r, g, b)`."""
    r, g, b = parse_color_rgb(color)
    return (
        0.2126 * srgb_channel_to_linear(r)
        + 0.7152 * srgb_channel_to_linear(g)
        + 0.0722 * srgb_channel_to_linear(b)
    )


def contrast_ratio(fg: Any, bg: Any) -> float:
    """Unrounded WCAG 2.2 contrast ratio `(L1 + 0.05) / (L2 + 0.05)` in `1.0..21.0`."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def contrast_ratio_2dp(fg: Any, bg: Any) -> float:
    """WCAG 2.2 contrast ratio rounded to 2 decimal places (`design_measure.js` convention)."""
    return round(contrast_ratio(fg, bg), 2)


def is_large_text(
    size_px: float,
    weight: int | float = 400,
    *,
    large_px: float = 24.0,
    large_bold_px: float = 18.66,
    bold_weight: int = 700,
) -> bool:
    """True when text qualifies as WCAG 2.2 large scale (`>=24px`, or `>=18.66px` at weight `>=700`)."""
    s = float(size_px)
    w = float(weight)
    return s >= float(large_px) or (s >= float(large_bold_px) and w >= float(bold_weight))


def required_text_contrast(
    size_px: float = 16.0,
    weight: int | float = 400,
    *,
    thresholds: dict[str, Any] | None = None,
) -> float:
    """WCAG 2.2 AA minimum contrast ratio for text (`3.0` for large text, `4.5` otherwise)."""
    ct = (thresholds or {}).get("contrast") or {}
    normal = float(ct.get("text", 4.5))
    large = float(ct.get("large_text", 3.0))
    large_px = float(ct.get("large_px", 24.0))
    large_bold_px = float(ct.get("large_bold_px", 18.66))
    bold_weight = int(ct.get("bold_weight", 700))
    if is_large_text(
        size_px,
        weight,
        large_px=large_px,
        large_bold_px=large_bold_px,
        bold_weight=bold_weight,
    ):
        return large
    return normal


def check_text_contrast(
    fg: Any,
    bg: Any,
    *,
    size_px: float = 16.0,
    weight: int | float = 400,
    thresholds: dict[str, Any] | None = None,
) -> tuple[float, float, bool]:
    """Return `(ratio_2dp, threshold, passed)` for a text colour on a background colour."""
    ratio = contrast_ratio_2dp(fg, bg)
    need = required_text_contrast(size_px, weight, thresholds=thresholds)
    return ratio, need, ratio >= need


def check_ui_contrast(
    fg: Any,
    bg: Any,
    *,
    role: str = "border",
    thresholds: dict[str, Any] | None = None,
) -> tuple[float, float, bool]:
    """Return `(ratio_2dp, threshold, passed)` for a UI part against its adjacent background (WCAG 1.4.11).

    A text button's fill (`role in UI_EXEMPT_ROLES`) is exempt because the text itself identifies the
    control; field borders, icons, focus rings and solid interactive controls require `3.0:1`.
    """
    ct = (thresholds or {}).get("contrast") or {}
    need = float(ct.get("ui", 3.0))
    ratio = contrast_ratio_2dp(fg, bg)
    if role in UI_EXEMPT_ROLES:
        return ratio, 0.0, True
    return ratio, need, ratio >= need
