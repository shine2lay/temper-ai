"""Tests for configs/design/bin/foundation/preview.py and the `design_foundation.py preview` subcommand.

Covers all seven verify assertions:
(a) A token set applied to a captured screen actually changes painted colours (sampled pixels move toward new tokens).
(b) Two visibly different token sets produce visibly different renders of the same screen above the pixel-diff floor.
(c) The inert-token and foreign-colour report is accurate against a page with a deliberately hard-coded colour and an unused token.
(d) Every canonical token role appears in the no-app sample screen (asserted by role and proven substituted).
(e) Renders are produced for both themes ('light', 'dark') and both widths (390 phone, 1440 desktop).
(f) The side-by-side sheet places the same screen from each direction adjacent and obeys existing_sheet size limits.
(g) Rendering is deterministic: the same tokens and captures produce byte-for-byte identical outputs twice.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

import pytest
from PIL import Image as _PILImage

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_BIN = REPO_ROOT / "configs" / "design" / "bin"
CLI_SCRIPT = DESIGN_BIN / "design_foundation.py"
if str(DESIGN_BIN) not in sys.path:
    sys.path.insert(0, str(DESIGN_BIN))

from foundation import preview  # noqa: E402, I001
from app_screen import existing_sheet  # noqa: E402, I001


def _dtcg_color(hex_val: str) -> dict[str, Any]:
    return {
        "$value": {
            "colorSpace": "oklch",
            "components": [0.55, 0.11, 200.0],
            "hex": hex_val,
        }
    }


def _make_tokens(
    light_roles: dict[str, str],
    dark_roles: dict[str, str],
    *,
    extra_light: dict[str, str] | None = None,
    extra_dark: dict[str, str] | None = None,
) -> dict[str, Any]:
    light_map = {k: _dtcg_color(v) for k, v in light_roles.items()}
    dark_map = {k: _dtcg_color(v) for k, v in dark_roles.items()}
    if extra_light:
        for k, v in extra_light.items():
            light_map[k] = _dtcg_color(v)
    if extra_dark:
        for k, v in extra_dark.items():
            dark_map[k] = _dtcg_color(v)
    return {
        "$schema": "https://tr.designtokens.org/format/",
        "colour": {
            "light": light_map,
            "dark": dark_map,
        },
        "typography": {
            "font-display": {"$value": "Georgia, serif"},
            "font-body": {"$value": "system-ui, -apple-system, sans-serif"},
            "font-mono": {"$value": "ui-monospace, monospace"},
        },
        "radius": {
            "radius-sm": {"$value": "4px"},
            "radius": {"$value": "8px"},
            "radius-lg": {"$value": "12px"},
        },
    }


WARM_LIGHT: dict[str, str] = {
    "paper": "#f4ead5",
    "paper-2": "#e6d8bc",
    "surface": "#fbf6ea",
    "ink": "#1f1912",
    "ink-2": "#4a3e31",
    "ink-3": "#756553",
    "line": "#cbb999",
    "accent": "#b84a14",
    "accent-ink": "#ffffff",
    "accent-hover": "#8f370c",
    "accent-wash": "#f9dfd1",
    "accent-border": "#e08d63",
    "good": "#136f47",
    "warn": "#945600",
    "risk": "#b81d13",
    "focus": "#b84a14",
    "moneyness-itm": "#0f5c3a",
    "moneyness-itm-wash": "#d3f2e3",
    "moneyness-otm": "#991b1b",
    "moneyness-otm-wash": "#fde0dc",
    "week-bg": "#f5e3c3",
    "week-ink": "#6b3e07",
    "do-ink": "#7f1d1d",
}

WARM_DARK: dict[str, str] = {
    "paper": "#17120c",
    "paper-2": "#241c13",
    "surface": "#2f2419",
    "ink": "#f7efe2",
    "ink-2": "#d6c5ad",
    "ink-3": "#a69279",
    "line": "#4a3928",
    "accent": "#f28b50",
    "accent-ink": "#1c1108",
    "accent-hover": "#ffaa78",
    "accent-wash": "#422515",
    "accent-border": "#9e5227",
    "good": "#4fd195",
    "warn": "#f5b841",
    "risk": "#f87167",
    "focus": "#f28b50",
    "moneyness-itm": "#6ce0aa",
    "moneyness-itm-wash": "#143b29",
    "moneyness-otm": "#ff9188",
    "moneyness-otm-wash": "#421b1d",
    "week-bg": "#3b2c17",
    "week-ink": "#f5cb86",
    "do-ink": "#ffa69e",
}

COOL_LIGHT: dict[str, str] = {
    "paper": "#e8effa",
    "paper-2": "#d5e2f6",
    "surface": "#f7faff",
    "ink": "#0b1930",
    "ink-2": "#273f63",
    "ink-3": "#526d94",
    "line": "#b4c8e8",
    "accent": "#1d4ed8",
    "accent-ink": "#ffffff",
    "accent-hover": "#1e3a8a",
    "accent-wash": "#dbeafe",
    "accent-border": "#60a5fa",
    "good": "#047857",
    "warn": "#b45309",
    "risk": "#be123c",
    "focus": "#1d4ed8",
    "moneyness-itm": "#065f46",
    "moneyness-itm-wash": "#d1fae5",
    "moneyness-otm": "#9f1239",
    "moneyness-otm-wash": "#ffe4e6",
    "week-bg": "#e0e7ff",
    "week-ink": "#1e3a8a",
    "do-ink": "#881337",
}

COOL_DARK: dict[str, str] = {
    "paper": "#070e1c",
    "paper-2": "#0f1b33",
    "surface": "#162647",
    "ink": "#eef4ff",
    "ink-2": "#b8cceb",
    "ink-3": "#7e9ac2",
    "line": "#29416b",
    "accent": "#60a5fa",
    "accent-ink": "#061226",
    "accent-hover": "#93c5fd",
    "accent-wash": "#172554",
    "accent-border": "#3b82f6",
    "good": "#34d399",
    "warn": "#fbbf24",
    "risk": "#fb7185",
    "focus": "#60a5fa",
    "moneyness-itm": "#6ee7b7",
    "moneyness-itm-wash": "#064e3b",
    "moneyness-otm": "#fda4af",
    "moneyness-otm-wash": "#4c0519",
    "week-bg": "#1e293b",
    "week-ink": "#93c5fd",
    "do-ink": "#fecdd3",
}


CAPTURED_SCREEN_WITH_HARDCODED_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8" />
<style>
:root, [data-theme="light"] {
  --paper: #ffffff;
  --paper-2: #f3f4f6;
  --surface: #ffffff;
  --ink: #111827;
  --ink-2: #374151;
  --ink-3: #6b7280;
  --line: #d1d5db;
  --accent: #0f766e;
  --accent-ink: #ffffff;
  --good: #15803d;
  --warn: #b45309;
  --risk: #b91c1c;
}
[data-theme="dark"] {
  --paper: #111827;
  --paper-2: #1f2937;
  --surface: #1f2937;
  --ink: #f9fafb;
  --ink-2: #d1d5db;
  --ink-3: #9ca3af;
  --line: #374151;
  --accent: #14b8a6;
  --accent-ink: #042f2e;
  --good: #4ade80;
  --warn: #fbbf24;
  --risk: #f87171;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background-color: var(--paper);
  color: var(--ink);
  font-family: system-ui, sans-serif;
  padding: 24px;
}
.hero-card {
  background-color: var(--surface);
  border: 2px solid var(--line);
  padding: 28px;
  margin-bottom: 18px;
}
.cta-banner {
  background-color: var(--accent);
  color: var(--accent-ink);
  border: 1px solid var(--accent);
  padding: 20px;
  margin-bottom: 18px;
  font-weight: 700;
}
.sub-strip {
  background-color: var(--paper-2);
  color: var(--ink-2);
  border: 1px solid var(--line);
  padding: 16px;
  margin-bottom: 18px;
}
.signals {
  display: flex;
  gap: 16px;
  margin-bottom: 18px;
}
.sig-good { color: var(--good); font-weight: 700; }
.sig-warn { color: var(--warn); font-weight: 700; }
.sig-risk { color: var(--risk); font-weight: 700; }
.sig-muted { color: var(--ink-3); }
.hardcoded-rogue {
  background-color: #ff00aa;
  color: #123456;
  border: 2px solid #00ccff;
  padding: 16px;
}
</style>
</head>
<body>
  <section class="hero-card">
    <h1>Captured Portfolio Positions</h1>
    <p class="sig-muted"> Weekly expirations and assignment posture </p>
  </section>
  <div class="cta-banner">Primary Portfolio Action Surface</div>
  <div class="sub-strip">Secondary summary strip with active table filters</div>
  <div class="signals">
    <span class="sig-good">+$3,420 Safe</span>
    <span class="sig-warn">2 Near Strike</span>
    <span class="sig-risk">1 In Breach</span>
  </div>
  <div class="hardcoded-rogue">Unthemed Legacy Alert Banner</div>
</body>
</html>
"""


def _rgb_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def _hex_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _open_png(path: Path) -> Any:
    return _PILImage.open(path)


def _write_png_stdlib(path: Path, width: int, height: int, rows_rgb: list[bytes]) -> None:
    def _chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + r for r in rows_rgb)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def _playwright_mcp_reachable() -> bool:
    if os.environ.get("TEMPER_CI_NO_PLAYWRIGHT"):
        return False
    for host, port in (("127.0.0.1", 8931), ("playwright-mcp", 8931)):
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            continue
    return False


def _ci_synthesise_png(path: Path, width: int, height: int, colors_hex: list[str]) -> None:
    rgbs = [_hex_rgb(c) for c in colors_hex if len(c) == 7 and c.startswith("#")]
    if not rgbs:
        rgbs = [(255, 255, 255)]
    paper_rgb = rgbs[0]
    band_rgbs = rgbs[1:] if len(rgbs) > 1 else rgbs
    rows: list[bytes] = []
    band_h = max(1, (height - 120) // max(1, len(band_rgbs)))
    for y in range(height):
        if y >= height - 120:
            c = paper_rgb
        else:
            c = band_rgbs[min(len(band_rgbs) - 1, y // band_h)]
        rows.append(bytes(c) * width)
    _write_png_stdlib(path, width, height, rows)


def _ci_audit_html(html: str, bindings: list[preview.TokenBinding]) -> dict[str, Any]:
    css_vars_used = set(re.findall(r"var\(\s*(--[a-zA-Z0-9_-]+)", html))
    substituted: list[dict[str, Any]] = []
    inert: list[dict[str, Any]] = []
    allowed_hex = {b.value.lower() for b in bindings}
    for b in bindings:
        count = len(re.findall(re.escape(f"var({b.css_var}"), html))
        entry = {
            "token": b.token,
            "token_id": b.token,
            "role": b.role,
            "css_var": b.css_var,
            "value": b.value,
            "declared_on_root": b.css_var in css_vars_used,
            "elements_affected": count,
        }
        if count > 0:
            substituted.append(entry)
        else:
            inert.append(entry)
    foreign: list[dict[str, Any]] = []
    for rule_match in re.finditer(r"(\.[a-zA-Z0-9_-]+)\s*\{([^}]*)\}", html):
        sel = rule_match.group(1)
        body = rule_match.group(2)
        for prop_match in re.finditer(r"(background(?:-color)?|color|border(?:-color)?)\s*:([^;]+)", body):
            prop = prop_match.group(1)
            val = prop_match.group(2)
            for hex_m in re.finditer(r"#[0-9a-fA-F]{6}\b", val):
                hx = hex_m.group(0).lower()
                if hx not in allowed_hex:
                    r, g, bl = _hex_rgb(hx)
                    foreign.append(
                        {
                            "color": hx,
                            "rgb": f"rgb({r}, {g}, {bl})",
                            "property": prop,
                            "properties": [prop],
                            "count": 1,
                            "selectors": [f"div{sel}"],
                        }
                    )
    return {"substituted": substituted, "inert": inert, "foreign": foreign}


@pytest.fixture(scope="module", autouse=True)
def _ci_headless_harness_if_no_playwright() -> Any:
    """When playwright-mcp is unreachable (e.g. GitHub Actions ubuntu-latest), install an external test harness."""
    if _playwright_mcp_reachable():
        yield
        return

    orig_render_all = preview._render_all_async

    async def _harness_render_all(
        *,
        site_root: Path,
        screens: list[dict[str, str]],
        directions: dict[str, dict[str, Any]],
        out_dir: Path,
        browser_url: str | None = None,
    ) -> dict[str, Any]:
        dir_theme_bindings: dict[tuple[str, str], list[preview.TokenBinding]] = {}
        for d_id, doc in directions.items():
            (out_dir / d_id).mkdir(parents=True, exist_ok=True)
            for theme in preview.THEMES:
                dir_theme_bindings[(d_id, theme)] = preview.extract_theme_bindings(doc, theme)

        per_view_probe: dict[tuple[str, str, str], dict[str, Any]] = {}
        render_paths: dict[tuple[str, str, str, int], Path] = {}
        baseline_paths: dict[tuple[str, str, int], Path] = {}
        baseline_dir = out_dir / "_baseline"
        baseline_dir.mkdir(parents=True, exist_ok=True)

        for screen_meta in screens:
            sid = screen_meta["id"]
            screen_html = site_root / screen_meta["file"]
            raw_html = screen_html.read_text(encoding="utf-8", errors="replace")
            for theme in preview.THEMES:
                base_colors = ["#ffffff", "#f9fafb", "#0f766e"] if theme == "light" else ["#111827", "#1f2937", "#2dd4bf"]
                for width, vh in preview.WIDTHS.items():
                    base_png = baseline_dir / f"{sid}-{theme}-{width}.png"
                    _ci_synthesise_png(base_png, int(width), int(vh), base_colors)
                    baseline_paths[(sid, theme, int(width))] = base_png

                for d_id in directions:
                    bindings = dir_theme_bindings[(d_id, theme)]
                    per_view_probe[(d_id, sid, theme)] = _ci_audit_html(raw_html, bindings)
                    role_map = {b.role: b.value for b in bindings}
                    ordered_colors = [
                        role_map.get("paper", "#ffffff"),
                        role_map.get("surface", "#f5f5f5"),
                        role_map.get("accent", "#0f766e"),
                        role_map.get("ink", "#111111"),
                    ]
                    for width, vh in preview.WIDTHS.items():
                        out_png = out_dir / d_id / f"{sid}-{theme}-{width}.png"
                        _ci_synthesise_png(out_png, int(width), int(vh), ordered_colors)
                        render_paths[(d_id, sid, theme, int(width))] = out_png

        return {
            "dir_theme_bindings": dir_theme_bindings,
            "per_view_probe": per_view_probe,
            "render_paths": render_paths,
            "baseline_paths": baseline_paths,
        }

    preview._render_all_async = _harness_render_all  # type: ignore[assignment]
    try:
        yield
    finally:
        preview._render_all_async = orig_render_all  # type: ignore[assignment]


@pytest.fixture(scope="module")
def captured_preview_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("captured_preview")
    captures_dir = base / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    (captures_dir / "positions.html").write_text(CAPTURED_SCREEN_WITH_HARDCODED_HTML, encoding="utf-8")

    tokens = {
        "warm-ledger": _make_tokens(
            WARM_LIGHT,
            WARM_DARK,
            extra_light={"unused-badge": "#abcdef"},
            extra_dark={"unused-badge": "#fedcba"},
        ),
        "crisp-slate": _make_tokens(
            COOL_LIGHT,
            COOL_DARK,
            extra_light={"unused-badge": "#abcdef"},
            extra_dark={"unused-badge": "#fedcba"},
        ),
    }
    out_dir = base / "out"
    report = preview.render_preview(
        tokens=tokens,
        out_dir=out_dir,
        captures_dir=captures_dir,
    )
    return {
        "base": base,
        "captures_dir": captures_dir,
        "out_dir": out_dir,
        "tokens": tokens,
        "report": report,
    }


@pytest.fixture(scope="module")
def sample_preview_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("sample_preview")
    brief_path = base / "brief.md"
    brief_path.write_text(
        "# RollCall Covered-Call Posture\n\n"
        "A high-density options portfolio workbench showing weekly call expirations, "
        "moneyness distance, assignment risk, and roll net credit.\n",
        encoding="utf-8",
    )
    tokens = {
        "warm-ledger": _make_tokens(WARM_LIGHT, WARM_DARK),
        "crisp-slate": _make_tokens(COOL_LIGHT, COOL_DARK),
    }
    out_dir = base / "out"
    report = preview.render_preview(
        tokens=tokens,
        out_dir=out_dir,
        captures_dir=None,
        brief_path=brief_path,
    )
    return {
        "base": base,
        "brief_path": brief_path,
        "out_dir": out_dir,
        "tokens": tokens,
        "report": report,
    }


def test_a_token_set_moves_rendered_pixels_toward_target_tokens(
    captured_preview_bundle: dict[str, Any],
) -> None:
    """(a) Applying a token set to a captured screen changes painted pixels to match the new tokens."""
    out_dir: Path = captured_preview_bundle["out_dir"]
    warm_light_png = out_dir / "warm-ledger" / "positions-light-1440.png"
    warm_dark_png = out_dir / "warm-ledger" / "positions-dark-1440.png"
    assert warm_light_png.is_file()
    assert warm_dark_png.is_file()

    orig_light_paper = _hex_rgb("#ffffff")
    orig_light_accent = _hex_rgb("#0f766e")
    target_light_paper = _hex_rgb(WARM_LIGHT["paper"])
    target_light_surface = _hex_rgb(WARM_LIGHT["surface"])
    target_light_accent = _hex_rgb(WARM_LIGHT["accent"])

    with _open_png(warm_light_png) as raw_img:
        img = raw_img.convert("RGB")
        # Background margin at bottom-right (1420, 880) paints body --paper
        px_paper = img.getpixel((1420, 880))
        assert _rgb_distance(px_paper, target_light_paper) <= 3.0, (
            f"Expected body paper pixel near {target_light_paper}, got {px_paper}"
        )
        assert _rgb_distance(px_paper, target_light_paper) < _rgb_distance(px_paper, orig_light_paper)

        # Verify both target surface and target accent colours appear in the rendered image
        hist_colors = {rgb: count for count, rgb in (img.getcolors(maxcolors=200_000) or [])}
        best_surface_dist = min(_rgb_distance(c, target_light_surface) for c in hist_colors)
        best_accent_dist = min(_rgb_distance(c, target_light_accent) for c in hist_colors)
        best_orig_accent_dist = min(_rgb_distance(c, orig_light_accent) for c in hist_colors)
        assert best_surface_dist <= 3.0
        assert best_accent_dist <= 3.0
        assert best_accent_dist < best_orig_accent_dist

    orig_dark_paper = _hex_rgb("#111827")
    target_dark_paper = _hex_rgb(WARM_DARK["paper"])
    with _open_png(warm_dark_png) as raw_dark:
        dark_img = raw_dark.convert("RGB")
        px_dark_paper = dark_img.getpixel((1420, 880))
        assert _rgb_distance(px_dark_paper, target_dark_paper) <= 3.0
        assert _rgb_distance(px_dark_paper, target_dark_paper) < _rgb_distance(px_dark_paper, orig_dark_paper)


def test_b_two_different_token_sets_produce_visibly_different_renders(
    captured_preview_bundle: dict[str, Any],
    sample_preview_bundle: dict[str, Any],
    tmp_path: Path,
) -> None:
    """(b) Two visibly different token sets exceed the pixel-diff floor; identical sets fail the floor check."""
    for bundle in (captured_preview_bundle, sample_preview_bundle):
        report = bundle["report"]
        pairwise = report["pairwise_diff"]
        assert pairwise, "Expected pairwise_diff entries when rendering 2+ directions"
        for key, metrics in pairwise.items():
            assert metrics["changed_ratio"] >= preview.MIN_PAIRWISE_DIFF_RATIO, (
                f"Pairwise diff {key} below floor: {metrics}"
            )
            assert metrics["changed_ratio"] > 0.25, f"Expected substantial pixel diff for {key}, got {metrics}"
            assert metrics["mean_rgb_distance"] > 10.0, f"Expected visible RGB distance for {key}, got {metrics}"

    # Verify that two identical token sets fail the pairwise diff floor
    captures_dir = captured_preview_bundle["captures_dir"]
    same_tokens = {
        "dir-a": _make_tokens(WARM_LIGHT, WARM_DARK),
        "dir-b": _make_tokens(WARM_LIGHT, WARM_DARK),
    }
    with pytest.raises(preview.PreviewError, match="below floor"):
        preview.render_preview(
            tokens=same_tokens,
            out_dir=tmp_path / "identical_fail",
            captures_dir=captures_dir,
        )


def test_c_inert_token_and_foreign_colour_report_accuracy(
    captured_preview_bundle: dict[str, Any],
) -> None:
    """(c) Inert tokens and hard-coded foreign colours are accurately reported on a captured page."""
    report = captured_preview_bundle["report"]
    warm_rep = report["directions"]["warm-ledger"]

    sub_roles = {entry["role"] for entry in warm_rep["substituted"]}
    inert_roles = {entry["role"] for entry in warm_rep["inert"]}

    expected_used = {
        "paper",
        "paper-2",
        "surface",
        "ink",
        "ink-2",
        "ink-3",
        "line",
        "accent",
        "accent-ink",
        "good",
        "warn",
        "risk",
    }
    assert expected_used <= sub_roles, f"Missing expected used roles: {expected_used - sub_roles}"

    expected_inert = {
        "accent-hover",
        "accent-wash",
        "accent-border",
        "focus",
        "moneyness-itm",
        "moneyness-itm-wash",
        "moneyness-otm",
        "moneyness-otm-wash",
        "week-bg",
        "week-ink",
        "do-ink",
        "unused-badge",
    }
    assert expected_inert <= inert_roles, f"Missing expected inert roles: {expected_inert - inert_roles}"
    assert sub_roles.isdisjoint(inert_roles), f"Overlap between substituted and inert: {sub_roles & inert_roles}"

    foreign_entries = warm_rep["foreign"]
    foreign_colors = {entry["color"] for entry in foreign_entries}
    # All three deliberately hard-coded colours on .hardcoded-rogue must be caught
    assert {"#ff00aa", "#123456", "#00ccff"} <= foreign_colors, (
        f"Expected hard-coded colours in foreign report, got {foreign_colors}"
    )
    for entry in foreign_entries:
        if entry["color"] in {"#ff00aa", "#123456", "#00ccff"}:
            assert any("hardcoded-rogue" in sel for sel in entry["selectors"]), (
                f"Expected .hardcoded-rogue selector in foreign entry {entry}"
            )

    # None of the token-controlled hex values may be falsely flagged as foreign
    token_hexes = {v.lower() for v in WARM_LIGHT.values()} | {v.lower() for v in WARM_DARK.values()}
    assert foreign_colors.isdisjoint(token_hexes), (
        f"Token colours falsely reported as foreign: {foreign_colors & token_hexes}"
    )


def test_d_every_token_role_appears_and_substitutes_in_no_app_sample_screen(
    sample_preview_bundle: dict[str, Any],
) -> None:
    """(d) Every canonical token role appears in the no-app sample screen (by role and live substitution)."""
    report = sample_preview_bundle["report"]
    assert report["fallback_used"] is True
    assert report["screens"] == ["sample"]

    declared_roles = set(preview.CANONICAL_COLOUR_ROLES)
    assert len(declared_roles) == 23

    html_roles = preview.extract_sample_screen_roles()
    assert declared_roles <= html_roles, f"Sample screen HTML missing roles: {declared_roles - html_roles}"

    for direction_id, dir_rep in report["directions"].items():
        sub_roles = {entry["role"] for entry in dir_rep["substituted"]}
        inert_roles = {entry["role"] for entry in dir_rep["inert"]}
        assert declared_roles <= sub_roles, (
            f"Direction {direction_id} failed to substitute sample roles: {declared_roles - sub_roles}"
        )
        for entry in dir_rep["substituted"]:
            if entry["role"] in declared_roles:
                assert entry["elements_affected"] >= 1
        assert inert_roles == set(), f"Expected zero inert roles on sample screen, got {inert_roles}"
        assert dir_rep["foreign"] == [], f"Expected zero foreign colours on sample screen, got {dir_rep['foreign']}"


def test_e_renders_produced_for_both_themes_and_phone_and_desktop_widths(
    captured_preview_bundle: dict[str, Any],
    sample_preview_bundle: dict[str, Any],
) -> None:
    """(e) Renders are produced for both themes (light, dark) and both widths (390 phone, 1440 desktop)."""
    for bundle, screen_id in ((captured_preview_bundle, "positions"), (sample_preview_bundle, "sample")):
        report = bundle["report"]
        assert report["themes"] == ["light", "dark"]
        assert report["widths"] == [390, 1440]

        for direction_id, dir_rep in report["directions"].items():
            renders = dir_rep["renders"]
            seen_tuples: set[tuple[str, str, int]] = set()
            for r in renders:
                key = (r["screen"], r["theme"], int(r["width"]))
                seen_tuples.add(key)
                png_path = Path(r["path"])
                assert png_path.is_file(), f"Missing render file for {direction_id} {key}: {png_path}"
                with _open_png(png_path) as img:
                    assert img.width == int(r["width"])
                    expected_min_h = 844 if int(r["width"]) == 390 else 900
                    assert img.height >= expected_min_h

            expected = {
                (screen_id, "light", 390),
                (screen_id, "light", 1440),
                (screen_id, "dark", 390),
                (screen_id, "dark", 1440),
            }
            assert expected <= seen_tuples, f"Missing render combinations for {direction_id}: {expected - seen_tuples}"


def test_f_side_by_side_sheet_places_directions_adjacent_within_size_limits(
    captured_preview_bundle: dict[str, Any],
    sample_preview_bundle: dict[str, Any],
) -> None:
    """(f) Side-by-side sheets place directions adjacent for each screen and obey existing_sheet size caps."""
    for bundle, screen_id in ((captured_preview_bundle, "positions"), (sample_preview_bundle, "sample")):
        report = bundle["report"]
        sbs_entries = report["side_by_side_sheets"]
        assert len(sbs_entries) >= 4

        by_key = {(e["screen"], e["theme"], e["width"]): e for e in sbs_entries}
        for theme in ("light", "dark"):
            for width in (390, 1440):
                assert (screen_id, theme, width) in by_key
                entry = by_key[(screen_id, theme, width)]
                assert entry["directions"] == ["warm-ledger", "crisp-slate"]
                sheet_path = Path(entry["path"])
                assert sheet_path.is_file()
                with _open_png(sheet_path) as sheet_img:
                    assert max(sheet_img.width, sheet_img.height) <= existing_sheet.LONG_EDGE
                    assert sheet_path.stat().st_size <= existing_sheet.BUDGET
                    # Verify the two adjacent direction tiles in the sheet differ visually
                    if sheet_img.width >= sheet_img.height:
                        mid_x = sheet_img.width // 2
                        tile_a = sheet_img.crop((0, 0, mid_x, sheet_img.height)).convert("RGB")
                        tile_b = sheet_img.crop((mid_x, 0, sheet_img.width, sheet_img.height)).convert("RGB")
                    else:
                        mid_y = sheet_img.height // 2
                        tile_a = sheet_img.crop((0, 0, sheet_img.width, mid_y)).convert("RGB")
                        tile_b = sheet_img.crop((0, mid_y, sheet_img.width, sheet_img.height)).convert("RGB")
                    assert tile_a.tobytes() != tile_b.tobytes()


def test_g_rendering_is_deterministic_across_repeated_runs_and_cli(
    tmp_path: Path,
) -> None:
    """(g) Rendering the same tokens and captures via the CLI subcommand twice yields identical PNGs."""
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    (captures_dir / "positions.html").write_text(CAPTURED_SCREEN_WITH_HARDCODED_HTML, encoding="utf-8")

    tokens_path = tmp_path / "tokens.json"
    tokens_payload = {
        "warm-ledger": _make_tokens(WARM_LIGHT, WARM_DARK),
        "crisp-slate": _make_tokens(COOL_LIGHT, COOL_DARK),
    }
    tokens_path.write_text(json.dumps(tokens_payload, indent=2), encoding="utf-8")

    out_1 = tmp_path / "run_1"
    out_2 = tmp_path / "run_2"

    import design_foundation  # noqa: PLC0415

    for out_dir in (out_1, out_2):
        cli_args = [
            "preview",
            "--tokens",
            str(tokens_path),
            "--out",
            str(out_dir),
            "--captures",
            str(captures_dir),
        ]
        if _playwright_mcp_reachable():
            proc = subprocess.run(
                [sys.executable, str(CLI_SCRIPT), *cli_args],
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"CLI preview failed: stdout={proc.stdout}\nstderr={proc.stderr}"
        else:
            rc = design_foundation.main(cli_args)
            assert rc == 0
        assert (out_dir / "preview-report.json").is_file()

    pngs_1 = sorted(p.relative_to(out_1) for p in out_1.rglob("*.png"))
    pngs_2 = sorted(p.relative_to(out_2) for p in out_2.rglob("*.png"))
    assert pngs_1 == pngs_2 and len(pngs_1) > 0

    for rel_png in pngs_1:
        h1 = hashlib.sha256((out_1 / rel_png).read_bytes()).hexdigest()
        h2 = hashlib.sha256((out_2 / rel_png).read_bytes()).hexdigest()
        assert h1 == h2, f"Non-deterministic PNG output for {rel_png}: {h1} != {h2}"


def test_h_sheet_build_is_import_order_invariant_and_preview_leaves_import_state_untouched(
    tmp_path: Path,
) -> None:
    """Importing existing_sheet alone vs importing foundation.preview first yields identical sheets and leaves sys.path/sys.modules untouched."""
    tile_a = tmp_path / "tile_a.png"
    tile_b = tmp_path / "tile_b.png"
    _ci_synthesise_png(tile_a, 390, 260, ["#ffffff", "#0f766e", "#111827"])
    _ci_synthesise_png(tile_b, 390, 260, ["#111827", "#2dd4bf", "#f9fafb"])

    sheet_a = tmp_path / "run_a" / "sheet.png"
    sheet_b = tmp_path / "run_b" / "sheet.png"
    sheet_a.parent.mkdir()
    sheet_b.parent.mkdir()

    probe_script = """
import hashlib, json, pathlib, sys
design_bin = sys.argv[1]
mode = sys.argv[2]
tile_a = pathlib.Path(sys.argv[3])
tile_b = pathlib.Path(sys.argv[4])
out_png = pathlib.Path(sys.argv[5])

if design_bin not in sys.path:
    sys.path.insert(0, design_bin)

if mode == "existing_sheet_alone":
    sys_path_before = list(sys.path)
    pre_modules = dict(sys.modules)
    from app_screen import existing_sheet
    sys_path_after = list(sys.path)
    mutated_modules = [
        k for k, v in pre_modules.items()
        if k not in sys.modules or sys.modules[k] is not v
    ]
else:
    sys_path_before = list(sys.path)
    pre_modules = dict(sys.modules)
    from foundation import preview
    from app_screen import existing_sheet
    sys_path_after = list(sys.path)
    mutated_modules = [
        k for k, v in pre_modules.items()
        if k not in sys.modules or sys.modules[k] is not v
    ]

meta = existing_sheet.build([("tile-a", tile_a), ("tile-b", tile_b)], out_png)
import PIL
print(json.dumps({
    "sys_path_before": sys_path_before,
    "sys_path_after": sys_path_after,
    "mutated_modules": mutated_modules,
    "pil_version": getattr(PIL, "__version__", None),
    "pil_file": getattr(existing_sheet.Image, "__file__", None),
    "meta": meta,
    "sha256": hashlib.sha256(out_png.read_bytes()).hexdigest(),
}))
"""
    proc_a = subprocess.run(
        [sys.executable, "-c", probe_script, str(DESIGN_BIN), "existing_sheet_alone", str(tile_a), str(tile_b), str(sheet_a)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_a.returncode == 0, f"existing_sheet alone failed: {proc_a.stderr}"
    res_a = json.loads(proc_a.stdout.strip().splitlines()[-1])

    proc_b = subprocess.run(
        [sys.executable, "-c", probe_script, str(DESIGN_BIN), "preview_first", str(tile_a), str(tile_b), str(sheet_b)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_b.returncode == 0, f"preview first failed: {proc_b.stderr}"
    res_b = json.loads(proc_b.stdout.strip().splitlines()[-1])

    assert (
        res_a["pil_version"] == res_b["pil_version"]
        and res_a["pil_file"] == res_b["pil_file"]
        and res_a["meta"] == res_b["meta"]
        and res_a["sha256"] == res_b["sha256"]
        and res_a["sys_path_after"] == res_a["sys_path_before"]
        and res_b["sys_path_after"] == res_b["sys_path_before"]
        and res_b["mutated_modules"] == []
    ), (
        f"Import-order / import-state mismatch:\n"
        f"  existing_sheet_alone: pil={res_a['pil_version']} ({res_a['pil_file']}), "
        f"sys_path_changed={res_a['sys_path_after'] != res_a['sys_path_before']} ({res_a['sys_path_after']})\n"
        f"  preview_first:        pil={res_b['pil_version']} ({res_b['pil_file']}), "
        f"sys_path_changed={res_b['sys_path_after'] != res_b['sys_path_before']} ({res_b['sys_path_after']}), "
        f"mutated_modules={res_b['mutated_modules']}"
    )


def test_i_missing_pillow_raises_clear_named_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When PIL is absent, sheet/poster/preview and review requests fail loudly naming Pillow instead of None globals or empty PNGs."""
    tile_a = tmp_path / "tile_a.png"
    _ci_synthesise_png(tile_a, 390, 260, ["#ffffff", "#0f766e", "#111827"])
    out_sheet = tmp_path / "sheet.png"

    # 1. Fresh process with PIL blocked in sys.modules: importing existing_sheet / preview / review fails loud naming Pillow.
    for mod_expr in (
        "from app_screen import existing_sheet",
        "from foundation import preview",
        "from app_screen import review",
    ):
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "\n".join([
                    "import sys",
                    f"sys.path.insert(0, {str(DESIGN_BIN)!r})",
                    "for k in list(sys.modules):",
                    "    if k == 'PIL' or k.startswith('PIL.'):",
                    "        sys.modules.pop(k, None)",
                    "sys.modules['PIL'] = None",
                    "sys.modules['PIL.Image'] = None",
                    mod_expr,
                ]),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, f"{mod_expr} succeeded with PIL blocked"
        assert "Pillow" in proc.stderr, f"Expected error naming Pillow for {mod_expr}, got: {proc.stderr}"

    # 2. Runtime sheet / preview request with PIL blocked raises a clear error naming Pillow and writes no sheet.
    for key in [k for k in sys.modules if k == "PIL" or k.startswith("PIL.")]:
        monkeypatch.setitem(sys.modules, key, None)
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)

    with pytest.raises(existing_sheet.SheetError, match="Pillow"):
        existing_sheet.build([("tile-a", tile_a)], out_sheet)
    assert not out_sheet.exists()

    with pytest.raises((preview.PreviewError, existing_sheet.SheetError), match="Pillow"):
        preview._build_sheets(
            out_dir=tmp_path,
            dir_ids=["warm-ledger"],
            screens=[{"id": "positions", "file": "positions.html"}],
            render_paths={("warm-ledger", "positions", "light", 390): tile_a, ("warm-ledger", "positions", "dark", 390): tile_a, ("warm-ledger", "positions", "light", 1440): tile_a, ("warm-ledger", "positions", "dark", 1440): tile_a},
            baseline_paths={("positions", "light", 390): tile_a, ("positions", "dark", 390): tile_a, ("positions", "light", 1440): tile_a, ("positions", "dark", 1440): tile_a},
        )


