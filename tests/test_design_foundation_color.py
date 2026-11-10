"""Deterministic tests for Stage 2/3 OKLCH colour engine (`configs/design/bin/foundation/color.py`).

Covers Task #244 verify assertions:
- (c) generated dark ramp is NOT the reverse of the light ramp (asserted on the lightness curve),
      and dark chroma is lower at equal lightness;
- (d) lightness steps are even in perceptual terms across each ramp within a stated tolerance;
- (e) every emitted colour is inside sRGB and any clamp is recorded in the output rather than silent;
- (f) generation is deterministic: same anchors and constraints produce byte-identical tokens.json
      across three runs;
- (i) generated tokens.json validates against the landed closed DTCG schema (`contracts.validate_tokens`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FOUNDATION_BIN = REPO_ROOT / "configs" / "design" / "bin"
if str(FOUNDATION_BIN) not in sys.path:
    sys.path.insert(0, str(FOUNDATION_BIN))

from foundation import color, contracts  # noqa: E402


def test_c_dark_ramp_not_reverse_of_light_and_lower_chroma_at_equal_lightness() -> None:
    """Assertion (c): dark ramp is generated with its own lightness curve (not reversed light)
    and lower chroma at equal lightness so saturated hues do not glow on dark surfaces.
    """
    sem = color.generate_semantic_set({"accent": 155.0, "neutral": 250.0})

    for role in ("neutral", "accent", "good", "risk", "warn", "info"):
        light_ramp = sem["light"]["ramp"][role]
        dark_ramp = sem["dark"]["ramp"][role]
        light_l = [round(light_ramp[s]["$value"]["components"][0], 4) for s in color.RAMP_STEPS]
        dark_l = [round(dark_ramp[s]["$value"]["components"][0], 4) for s in color.RAMP_STEPS]
        reversed_light_l = list(reversed(light_l))
        inverted_light_l = [round(1.0 - x, 4) for x in light_l]

        assert dark_l != reversed_light_l, f"{role}: dark lightness curve must not be reversed light ramp"
        assert dark_l != inverted_light_l, f"{role}: dark lightness curve must not be 1 - light ramp"
        assert dark_l != light_l, f"{role}: dark lightness curve must differ from light ramp"
        assert light_l[0] >= 0.94 and light_l[-1] <= 0.16
        assert 0.12 <= dark_l[0] <= 0.16 and 0.86 <= dark_l[-1] <= 0.92

    # Assert dark chroma is strictly lower than light chroma at equal lightness across the mid-tone range.
    c_peak = 0.18
    for l_val in (0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85):
        c_light = color.target_chroma(l_val, c_peak, theme="light")
        c_dark = color.target_chroma(l_val, c_peak, theme="dark")
        assert c_dark < c_light, (
            f"At equal lightness L={l_val}, dark chroma ({c_dark:.6f}) must be lower than light chroma ({c_light:.6f})"
        )


def test_d_lightness_steps_are_perceptually_even_within_tolerance() -> None:
    """Assertion (d): lightness steps are even in perceptual OKLCH L across each ramp within tolerance."""
    tolerance = 0.002
    sem = color.generate_semantic_set({"accent": 155.0, "neutral": 250.0})

    for theme in ("light", "dark"):
        for role, ramp in sem[theme]["ramp"].items():
            l_values = [ramp[s]["$value"]["components"][0] for s in color.RAMP_STEPS]
            deltas = [abs(l_values[i + 1] - l_values[i]) for i in range(len(l_values) - 1)]
            mean_delta = sum(deltas) / len(deltas)
            max_dev = max(abs(d - mean_delta) for d in deltas)
            assert mean_delta > 0.05, f"{theme}.{role} ramp must span a meaningful perceptual range"
            assert max_dev <= tolerance, (
                f"{theme}.{role} perceptual step deviation {max_dev:.6f} exceeds tolerance {tolerance} "
                f"(deltas={deltas})"
            )


def test_e_every_emitted_colour_inside_srgb_and_clamps_recorded_never_silent() -> None:
    """Assertion (e): every emitted colour is inside sRGB and any gamut clamp is explicitly recorded."""
    tokens = color.generate_tokens(
        "rollcall",
        anchor_hues={"accent": 155.0, "neutral": 250.0, "good": 152.0, "risk": 24.0, "warn": 72.0, "info": 245.0},
    )

    colour_nodes: list[tuple[str, dict]] = []

    def _walk(node: object, prefix: str) -> None:
        if isinstance(node, dict):
            if "$value" in node and isinstance(node["$value"], dict) and "colorSpace" in node["$value"]:
                colour_nodes.append((prefix, node))
                return
            for k, v in node.items():
                if not str(k).startswith("$"):
                    _walk(v, f"{prefix}.{k}" if prefix else str(k))

    _walk(tokens["colour"], "colour")
    assert len(colour_nodes) >= 48

    for path, tok in colour_nodes:
        val = tok["$value"]
        assert val["colorSpace"] == "oklch", f"{path} must emit colorSpace='oklch'"
        l_val, c_val, h_val = val["components"]
        assert color.in_srgb_gamut(l_val, c_val, h_val), (
            f"{path} emitted out-of-gamut OKLCH components ({l_val}, {c_val}, {h_val})"
        )
        lin_rgb = color.oklch_to_linear_srgb(l_val, c_val, h_val)
        for ch_name, ch_val in zip(("r", "g", "b"), lin_rgb, strict=True):
            assert -1e-6 <= ch_val <= 1.0 + 1e-6, (
                f"{path} linear sRGB channel {ch_name}={ch_val} outside [0, 1]"
            )
        assert val["hex"] == color.oklch_to_hex(l_val, c_val, h_val), (
            f"{path} hex fallback {val['hex']} does not match OKLCH components"
        )

    clamps = color.extract_clamp_records(tokens)
    assert len(clamps) > 0, "Gamut clamps must be explicitly recorded on tokens rather than silently clipped"
    for rec in clamps:
        assert rec["requested_C"] > rec["clamped_C"]
        assert rec["delta_C"] < 0


def test_f_generation_is_deterministic_across_three_runs() -> None:
    """Assertion (f): same anchors and constraints produce byte-identical tokens.json across 3 runs."""
    kwargs = {
        "product": "rollcall",
        "anchor_hues": {
            "neutral": 250.0,
            "accent": 155.0,
            "good": 152.0,
            "risk": 24.0,
            "warn": 72.0,
            "info": 245.0,
        },
        "font_sans": ["IBM Plex Sans", "system-ui", "sans-serif"],
        "font_mono": ["IBM Plex Mono", "ui-monospace", "monospace"],
        "body_px": 16.0,
        "scale_ratio": 1.25,
        "status": "draft",
        "date": "2026-11-09",
    }
    runs = [
        json.dumps(color.generate_tokens(**kwargs), indent=2, sort_keys=True).encode("utf-8")
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2], "generate_tokens must produce byte-identical JSON across 3 runs"


@pytest.mark.parametrize(
    ("product", "accent_hue", "neutral_hue"),
    [
        ("rollcall", 155.0, 250.0),
        ("temper", 215.0, 240.0),
        ("inkflow", 32.0, 60.0),
    ],
)
def test_i_generated_tokens_validate_against_closed_schema(
    product: str, accent_hue: float, neutral_hue: float
) -> None:
    """Assertion (i): generated tokens.json validates against the landed closed schema."""
    tokens = color.generate_tokens(
        product,
        anchor_hues={"accent": accent_hue, "neutral": neutral_hue},
        status="draft",
        date="2026-11-09",
    )
    contracts.validate_tokens(tokens, step="proof", file=f"{product}/tokens.json", require_all_parts=True)
