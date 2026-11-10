"""Stage 3 deterministic token proof battery (`foundation/proof.py`).

Evaluates candidate `tokens.json` files over 8 deterministic rules before Gate 1 (`gate_direction`):
1. `contrast.text`     - every text token on every legal surface token in light and dark (WCAG 2.2 AA
                         4.5:1 normal text, 3.0:1 large text >=24px or >=18.66px bold).
2. `contrast.ui`       - UI part against its adjacent surface 3.0:1 per WCAG 1.4.11; text-button fill
                         is exempt (`ghost_fill` / `[ui-role:text_button_fill]`), while field borders,
                         icons, focus rings, and solid controls count.
3. `signal.separation` - simulate protanopia, deuteranopia, and tritanopia; require every signal pair
                         (`good`/`risk` at minimum) to stay distinguishable in perceptual lightness
                         `dL` and post-simulation Oklab colour difference `sim_dE` (never hue alone).
4. `gamut.srgb`        - every emitted colour inside sRGB `[0, 1]` and matching its hex fallback;
                         out-of-gamut colours or unrecorded clamps fail loud.
5. `scale.spacing`     - spacing tokens sit on the 8 px base and increase strictly monotonically.
6. `scale.type`        - type scale is strictly monotonic with a consistent ratio, body >=16 px,
                         and line height in 120-145% (`1.20..1.45`).
7. `type.fallback`     - every `type.family` token carries a fallback stack (`>=2` families).
8. `tokens.schema`     - validates against the closed DTCG `TOKENS_SCHEMA` in `contracts.py`.
"""
from __future__ import annotations

import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

DESIGN_BIN = Path(__file__).resolve().parent.parent
if str(DESIGN_BIN) not in sys.path:
    sys.path.insert(0, str(DESIGN_BIN))

from wcag_contrast import (  # noqa: E402, F401
    UI_EXEMPT_ROLES,
    check_text_contrast,
    check_ui_contrast,
    contrast_ratio,
    contrast_ratio_2dp,
    is_large_text,
    parse_color_rgb,
    relative_luminance,
    required_text_contrast,
)

from . import color, contracts  # noqa: E402
from .workspace import Workspace  # noqa: E402

RULE_IDS: tuple[str, ...] = (
    "contrast.text",
    "contrast.ui",
    "signal.separation",
    "gamut.srgb",
    "scale.spacing",
    "scale.type",
    "type.fallback",
    "tokens.schema",
)

# Viénot, Brettel & Mollon (1999) linear-sRGB dichromacy simulation matrices.
CVD_MATRICES_LINEAR_SRGB: dict[str, tuple[tuple[float, float, float], ...]] = {
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}

GENERIC_FONT_FAMILIES: frozenset[str] = frozenset(
    {
        "sans-serif",
        "serif",
        "monospace",
        "system-ui",
        "ui-sans-serif",
        "ui-serif",
        "ui-monospace",
        "cursive",
        "fantasy",
    }
)


def load_thresholds(path: Path | str | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else (Path(__file__).resolve().parent / "proof_thresholds.json")
    return json.loads(target.read_text(encoding="utf-8"))


def _row(
    rule_id: str,
    value: float | int | str,
    threshold: float | int | str,
    result: str,
    evidence: str,
    *,
    token_a: str = "",
    token_b: str = "",
    theme: str = "all",
) -> dict[str, Any]:
    if result not in ("pass", "fail"):
        raise ValueError(f"row result must be 'pass' or 'fail', got {result!r}")
    if theme not in ("light", "dark", "all"):
        raise ValueError(f"row theme must be 'light', 'dark' or 'all', got {theme!r}")
    return {
        "id": rule_id,
        "value": value,
        "threshold": threshold,
        "result": result,
        "evidence": evidence,
        "token_a": token_a,
        "token_b": token_b,
        "theme": theme,
    }


def _token_hex(token_obj: Any) -> str | None:
    if not isinstance(token_obj, dict):
        return None
    val = token_obj.get("$value")
    if isinstance(val, dict) and isinstance(val.get("hex"), str):
        return val["hex"].upper()
    return None


def _token_oklch(token_obj: Any) -> tuple[float, float, float] | None:
    if not isinstance(token_obj, dict):
        return None
    val = token_obj.get("$value")
    if not isinstance(val, dict):
        return None
    if val.get("colorSpace") == "oklch":
        comps = val.get("components")
        if isinstance(comps, list) and len(comps) == 3 and all(isinstance(x, (int, float)) for x in comps):
            return (float(comps[0]), float(comps[1]), float(comps[2]))
    hex_str = val.get("hex")
    if isinstance(hex_str, str) and re.match(r"^#[0-9A-Fa-f]{6}$", hex_str):
        return color.hex_to_oklch(hex_str)
    return None


def _token_linear_srgb(token_obj: Any) -> tuple[float, float, float] | None:
    if not isinstance(token_obj, dict):
        return None
    val = token_obj.get("$value")
    if not isinstance(val, dict):
        return None
    if val.get("colorSpace") == "oklch":
        comps = val.get("components")
        if isinstance(comps, list) and len(comps) == 3 and all(isinstance(x, (int, float)) for x in comps):
            return color.oklch_to_linear_srgb(float(comps[0]), float(comps[1]), float(comps[2]))
    hex_str = val.get("hex")
    if isinstance(hex_str, str) and re.match(r"^#[0-9A-Fa-f]{6}$", hex_str):
        return tuple(color.srgb_01_to_linear(c) for c in color.hex_to_srgb_01(hex_str))  # type: ignore[return-value]
    return None


def simulate_cvd_oklab(
    lin_rgb: tuple[float, float, float],
    cvd_kind: str,
) -> tuple[float, float, float]:
    """Project linear sRGB `(r, g, b)` through `cvd_kind` dichromacy matrix and return Oklab `(L, a, b)`."""
    mat = CVD_MATRICES_LINEAR_SRGB[cvd_kind]
    r, g, b = (min(1.0, max(0.0, float(c))) for c in lin_rgb)
    sr = min(1.0, max(0.0, mat[0][0] * r + mat[0][1] * g + mat[0][2] * b))
    sg = min(1.0, max(0.0, mat[1][0] * r + mat[1][1] * g + mat[1][2] * b))
    sb = min(1.0, max(0.0, mat[2][0] * r + mat[2][1] * g + mat[2][2] * b))
    return color.linear_srgb_to_oklab(sr, sg, sb)


def _oklab_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _dimension_px(token_obj: Any) -> float | None:
    if not isinstance(token_obj, dict):
        return None
    val = token_obj.get("$value")
    if not isinstance(val, dict):
        return None
    num = val.get("value")
    unit = val.get("unit")
    if isinstance(num, (int, float)) and not isinstance(num, bool) and unit in ("px", "rem"):
        return round(float(num) * (16.0 if unit == "rem" else 1.0), 4)
    return None


# ---------------------------------------------------------------- Rule 1: contrast.text


def _check_contrast_text(tokens: dict[str, Any], th: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    colour_group = tokens.get("colour") if isinstance(tokens.get("colour"), dict) else {}
    scale_group = ((tokens.get("type") or {}).get("scale") or {}) if isinstance(tokens.get("type"), dict) else {}
    xl_px = _dimension_px(scale_group.get("xl")) or 24.0
    large_size = max(24.0, xl_px)
    body_size = _dimension_px(scale_group.get("base")) or 16.0

    for theme in ("light", "dark"):
        t_group = colour_group.get(theme)
        if not isinstance(t_group, dict):
            rows.append(
                _row(
                    "contrast.text",
                    "missing",
                    th["contrast"]["text"],
                    "fail",
                    f"colour.{theme} group is missing",
                    token_a=f"colour.{theme}",
                    theme=theme,
                )
            )
            continue

        surfaces = t_group.get("surface") if isinstance(t_group.get("surface"), dict) else {}
        surface_items: list[tuple[str, str]] = []
        for s_name in ("canvas", "raised", "sunken"):
            s_hex = _token_hex(surfaces.get(s_name))
            if s_hex:
                surface_items.append((f"colour.{theme}.surface.{s_name}", s_hex))

        ink_group = t_group.get("ink") if isinstance(t_group.get("ink"), dict) else {}
        for i_name, i_tok in ink_group.items():
            if str(i_name).startswith("$"):
                continue
            fg_hex = _token_hex(i_tok)
            if not fg_hex:
                continue
            desc = str(i_tok.get("$description") or "")
            is_heading = i_name in ("heading", "display") or "[text-scale:large]" in desc
            sz = large_size if is_heading else body_size
            wt = 700 if is_heading else 400
            for s_path, bg_hex in surface_items:
                ratio, need, passed = check_text_contrast(fg_hex, bg_hex, size_px=sz, weight=wt, thresholds=th)
                rows.append(
                    _row(
                        "contrast.text",
                        ratio,
                        need,
                        "pass" if passed else "fail",
                        f"{ratio}:1 {'meets' if passed else 'needs'} {need}:1 ({sz:g}px {wt}, {fg_hex} on {bg_hex})",
                        token_a=f"colour.{theme}.ink.{i_name}",
                        token_b=s_path,
                        theme=theme,
                    )
                )

        sem_group = t_group.get("semantic") if isinstance(t_group.get("semantic"), dict) else {}
        for role_name in ("good", "risk", "warn", "info", "accent"):
            role_obj = sem_group.get(role_name)
            if not isinstance(role_obj, dict):
                continue
            txt_tok = role_obj.get("text")
            fg_hex = _token_hex(txt_tok)
            if fg_hex:
                for s_path, bg_hex in surface_items:
                    ratio, need, passed = check_text_contrast(
                        fg_hex, bg_hex, size_px=body_size, weight=400, thresholds=th
                    )
                    rows.append(
                        _row(
                            "contrast.text",
                            ratio,
                            need,
                            "pass" if passed else "fail",
                            f"{ratio}:1 {'meets' if passed else 'needs'} {need}:1 ({body_size:g}px 400, {fg_hex} on {bg_hex})",
                            token_a=f"colour.{theme}.semantic.{role_name}.text",
                            token_b=s_path,
                            theme=theme,
                        )
                    )
            if role_name == "accent":
                solid_hex = _token_hex(role_obj.get("solid"))
                on_solid_hex = _token_hex(role_obj.get("on_solid"))
                if solid_hex and on_solid_hex:
                    ratio, need, passed = check_text_contrast(
                        on_solid_hex, solid_hex, size_px=body_size, weight=600, thresholds=th
                    )
                    rows.append(
                        _row(
                            "contrast.text",
                            ratio,
                            need,
                            "pass" if passed else "fail",
                            f"{ratio}:1 {'meets' if passed else 'needs'} {need}:1 ({body_size:g}px 600, {on_solid_hex} on {solid_hex})",
                            token_a=f"colour.{theme}.semantic.accent.on_solid",
                            token_b=f"colour.{theme}.semantic.accent.solid",
                            theme=theme,
                        )
                    )
    return rows


# ---------------------------------------------------------------- Rule 2: contrast.ui


def _ui_role_for_token(name: str, token_obj: dict[str, Any]) -> str:
    desc = str(token_obj.get("$description") or "")
    m = re.search(r"\[ui-role:([a-z0-9_-]+)\]", desc)
    if m:
        return m.group(1)
    if name in UI_EXEMPT_ROLES:
        return "text_button_fill"
    return "border"


def _check_contrast_ui(tokens: dict[str, Any], th: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    colour_group = tokens.get("colour") if isinstance(tokens.get("colour"), dict) else {}

    for theme in ("light", "dark"):
        t_group = colour_group.get(theme)
        if not isinstance(t_group, dict):
            rows.append(
                _row(
                    "contrast.ui",
                    "missing",
                    th["contrast"]["ui"],
                    "fail",
                    f"colour.{theme} group is missing",
                    token_a=f"colour.{theme}",
                    theme=theme,
                )
            )
            continue

        surfaces = t_group.get("surface") if isinstance(t_group.get("surface"), dict) else {}
        surface_items: list[tuple[str, str]] = []
        for s_name in ("canvas", "raised", "sunken"):
            s_hex = _token_hex(surfaces.get(s_name))
            if s_hex:
                surface_items.append((f"colour.{theme}.surface.{s_name}", s_hex))

        # Check text-button ghost fill exemption explicitly against canvas surface.
        ghost_tok = surfaces.get("ghost_fill")
        if isinstance(ghost_tok, dict) and surface_items:
            g_hex = _token_hex(ghost_tok)
            g_role = _ui_role_for_token("ghost_fill", ghost_tok)
            if g_hex:
                s_path, bg_hex = surface_items[0]
                ratio, need, passed = check_ui_contrast(g_hex, bg_hex, role=g_role, thresholds=th)
                if g_role in UI_EXEMPT_ROLES:
                    rows.append(
                        _row(
                            "contrast.ui",
                            ratio,
                            "exempt (1.4.11 text-button fill)",
                            "pass",
                            f"{ratio}:1 exempt per WCAG 1.4.11 (text button fill {g_hex} on {bg_hex}; text label identifies control)",
                            token_a=f"colour.{theme}.surface.ghost_fill",
                            token_b=s_path,
                            theme=theme,
                        )
                    )
                else:
                    rows.append(
                        _row(
                            "contrast.ui",
                            ratio,
                            need,
                            "pass" if passed else "fail",
                            f"{ratio}:1 {'meets' if passed else 'needs'} {need}:1 ({g_role} {g_hex} on {bg_hex})",
                            token_a=f"colour.{theme}.surface.ghost_fill",
                            token_b=s_path,
                            theme=theme,
                        )
                    )

        # Field borders, dividers, and focus rings count under WCAG 1.4.11 (3:1).
        line_group = t_group.get("line") if isinstance(t_group.get("line"), dict) else {}
        for l_name, l_tok in line_group.items():
            if str(l_name).startswith("$") or not isinstance(l_tok, dict):
                continue
            fg_hex = _token_hex(l_tok)
            if not fg_hex:
                continue
            role = _ui_role_for_token(l_name, l_tok)
            for s_path, bg_hex in surface_items:
                ratio, need, passed = check_ui_contrast(fg_hex, bg_hex, role=role, thresholds=th)
                rows.append(
                    _row(
                        "contrast.ui",
                        ratio,
                        need,
                        "pass" if passed else "fail",
                        f"{ratio}:1 {'meets' if passed else 'needs'} {need}:1 ({role} {fg_hex} on {bg_hex})",
                        token_a=f"colour.{theme}.line.{l_name}",
                        token_b=s_path,
                        theme=theme,
                    )
                )

        # Semantic UI icons/badges and primary solid control fill count under WCAG 1.4.11 (3:1).
        sem_group = t_group.get("semantic") if isinstance(t_group.get("semantic"), dict) else {}
        for role_name in ("good", "risk", "warn", "info", "accent"):
            role_obj = sem_group.get(role_name)
            if not isinstance(role_obj, dict):
                continue
            ui_tok = role_obj.get("ui")
            if isinstance(ui_tok, dict):
                fg_hex = _token_hex(ui_tok)
                ui_role = _ui_role_for_token("ui", ui_tok)
                if fg_hex:
                    for s_path, bg_hex in surface_items:
                        ratio, need, passed = check_ui_contrast(fg_hex, bg_hex, role=ui_role, thresholds=th)
                        rows.append(
                            _row(
                                "contrast.ui",
                                ratio,
                                need,
                                "pass" if passed else "fail",
                                f"{ratio}:1 {'meets' if passed else 'needs'} {need}:1 ({ui_role} {fg_hex} on {bg_hex})",
                                token_a=f"colour.{theme}.semantic.{role_name}.ui",
                                token_b=s_path,
                                theme=theme,
                            )
                        )
            if role_name == "accent" and isinstance(role_obj.get("solid"), dict):
                solid_tok = role_obj["solid"]
                s_hex = _token_hex(solid_tok)
                s_role = _ui_role_for_token("solid", solid_tok)
                if s_hex:
                    for s_path, bg_hex in surface_items:
                        ratio, need, passed = check_ui_contrast(s_hex, bg_hex, role=s_role, thresholds=th)
                        rows.append(
                            _row(
                                "contrast.ui",
                                ratio,
                                need,
                                "pass" if passed else "fail",
                                f"{ratio}:1 {'meets' if passed else 'needs'} {need}:1 ({s_role} {s_hex} on {bg_hex})",
                                token_a=f"colour.{theme}.semantic.accent.solid",
                                token_b=s_path,
                                theme=theme,
                            )
                        )
    return rows


# ---------------------------------------------------------------- Rule 3: signal.separation


def measure_signal_pair(
    tok_a: dict[str, Any],
    tok_b: dict[str, Any],
    *,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure lightness separation `dL` and post-CVD Oklab distance `sim_dE` between two signal tokens."""
    th = thresholds or load_thresholds()
    sig_th = th["signal"]
    min_dl = float(sig_th["min_lightness_diff"])
    min_de = float(sig_th["min_simulated_delta_e"])
    sims = list(sig_th.get("simulations") or ("protanopia", "deuteranopia", "tritanopia"))

    lch_a = _token_oklch(tok_a)
    lch_b = _token_oklch(tok_b)
    lin_a = _token_linear_srgb(tok_a)
    lin_b = _token_linear_srgb(tok_b)
    if lch_a is None or lch_b is None or lin_a is None or lin_b is None:
        return {
            "passed": False,
            "dL": 0.0,
            "min_sim_dE": 0.0,
            "worst_sim": "none",
            "sim_distances": {},
            "normal_dE": 0.0,
        }

    dL = abs(lch_a[0] - lch_b[0])
    normal_de = _oklab_distance(color.linear_srgb_to_oklab(*lin_a), color.linear_srgb_to_oklab(*lin_b))
    sim_distances: dict[str, float] = {}
    for sim_name in sims:
        lab_a = simulate_cvd_oklab(lin_a, sim_name)
        lab_b = simulate_cvd_oklab(lin_b, sim_name)
        sim_distances[sim_name] = _oklab_distance(lab_a, lab_b)

    worst_sim = min(sim_distances, key=lambda k: sim_distances[k])
    min_sim_de = sim_distances[worst_sim]
    passed = (dL >= min_dl) and (min_sim_de >= min_de)
    return {
        "passed": passed,
        "dL": round(dL, 4),
        "min_sim_dE": round(min_sim_de, 4),
        "worst_sim": worst_sim,
        "sim_distances": {k: round(v, 4) for k, v in sim_distances.items()},
        "normal_dE": round(normal_de, 4),
    }


def _check_signal_separation(tokens: dict[str, Any], th: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    colour_group = tokens.get("colour") if isinstance(tokens.get("colour"), dict) else {}
    sig_th = th["signal"]
    min_dl = float(sig_th["min_lightness_diff"])
    min_de = float(sig_th["min_simulated_delta_e"])
    pairs = sig_th.get("pairs") or [["good", "risk"]]

    for theme in ("light", "dark"):
        t_group = colour_group.get(theme) if isinstance(colour_group.get(theme), dict) else {}
        sem_group = t_group.get("semantic") if isinstance(t_group.get("semantic"), dict) else {}
        for role_a, role_b in pairs:
            for variant in ("text", "ui"):
                tok_a = (sem_group.get(role_a) or {}).get(variant) if isinstance(sem_group.get(role_a), dict) else None
                tok_b = (sem_group.get(role_b) or {}).get(variant) if isinstance(sem_group.get(role_b), dict) else None
                path_a = f"colour.{theme}.semantic.{role_a}.{variant}"
                path_b = f"colour.{theme}.semantic.{role_b}.{variant}"
                if not isinstance(tok_a, dict) or not isinstance(tok_b, dict):
                    rows.append(
                        _row(
                            "signal.separation",
                            "missing",
                            min_dl,
                            "fail",
                            f"missing signal pair token(s) {path_a} vs {path_b}",
                            token_a=path_a,
                            token_b=path_b,
                            theme=theme,
                        )
                    )
                    continue
                m = measure_signal_pair(tok_a, tok_b, thresholds=th)
                score = round(min(m["dL"], m["min_sim_dE"]), 4)
                sims_str = ", ".join(f"{k}={v:.4f}" for k, v in m["sim_distances"].items())
                rows.append(
                    _row(
                        "signal.separation",
                        score,
                        min_dl,
                        "pass" if m["passed"] else "fail",
                        (
                            f"dL={m['dL']:.4f} (need >={min_dl:.2f}), "
                            f"min_sim_dE={m['min_sim_dE']:.4f} under {m['worst_sim']} "
                            f"(need >={min_de:.2f}; {sims_str}; normal_dE={m['normal_dE']:.4f})"
                        ),
                        token_a=path_a,
                        token_b=path_b,
                        theme=theme,
                    )
                )
    return rows


# ---------------------------------------------------------------- Rule 4: gamut.srgb


def _check_gamut_srgb(tokens: dict[str, Any], th: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tol = float(th["gamut"]["srgb_tolerance"])
    hex_tol = int(th["gamut"].get("hex_channel_tolerance", 2))
    colour_group = tokens.get("colour") if isinstance(tokens.get("colour"), dict) else {}

    checked_by_theme: dict[str, int] = {"light": 0, "dark": 0, "all": 0}
    clamped_by_theme: dict[str, int] = {"light": 0, "dark": 0, "all": 0}
    failures: list[dict[str, Any]] = []

    def _theme_of(path: str) -> str:
        if path.startswith("colour.light."):
            return "light"
        if path.startswith("colour.dark."):
            return "dark"
        return "all"

    def _walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        if "$value" in node:
            val = node.get("$value")
            if not isinstance(val, dict):
                return
            theme = _theme_of(path)
            checked_by_theme[theme] += 1
            desc = str(node.get("$description") or "")
            if color.CLAMP_NOTE_RE.search(desc):
                clamped_by_theme[theme] += 1

            space = val.get("colorSpace")
            hex_str = val.get("hex", "")
            if space == "display-p3":
                failures.append(
                    _row(
                        "gamut.srgb",
                        "display-p3",
                        "sRGB [0, 1]",
                        "fail",
                        f"{path} uses wide-gamut colorSpace 'display-p3' outside sRGB contract",
                        token_a=path,
                        theme=theme,
                    )
                )
                return

            if space == "oklch":
                comps = val.get("components")
                if not (isinstance(comps, list) and len(comps) == 3 and all(isinstance(x, (int, float)) for x in comps)):
                    failures.append(
                        _row(
                            "gamut.srgb",
                            "missing-components",
                            "OKLCH [L, C, H] in sRGB [0, 1]",
                            "fail",
                            f"{path} has colorSpace 'oklch' without 3 numeric [L, C, H] components",
                            token_a=path,
                            theme=theme,
                        )
                    )
                    return
                L, C, H = float(comps[0]), float(comps[1]), float(comps[2])
                r_lin, g_lin, b_lin = color.oklch_to_linear_srgb(L, C, H)
                overflow = max(
                    0.0,
                    -r_lin,
                    r_lin - 1.0,
                    -g_lin,
                    g_lin - 1.0,
                    -b_lin,
                    b_lin - 1.0,
                    -L,
                    L - 1.0,
                    -C,
                )
                if overflow > tol:
                    failures.append(
                        _row(
                            "gamut.srgb",
                            round(overflow, 4),
                            "sRGB [0, 1]",
                            "fail",
                            (
                                f"OKLCH({L:.4f}, {C:.4f}, {H:.2f}) exceeds sRGB gamut by {overflow:.4f}: "
                                f"linear sRGB=({r_lin:.4f}, {g_lin:.4f}, {b_lin:.4f}) outside [0, 1]"
                            ),
                            token_a=path,
                            theme=theme,
                        )
                    )
                    return

                # Verify hex fallback matches the emitted OKLCH components (no silent browser clip).
                if isinstance(hex_str, str) and re.match(r"^#[0-9A-Fa-f]{6}$", hex_str):
                    expected_hex = color.oklch_to_hex(L, C, H)
                    actual_rgb = parse_color_rgb(hex_str)
                    expected_rgb = parse_color_rgb(expected_hex)
                    max_ch_diff = max(abs(a - b) for a, b in zip(actual_rgb, expected_rgb, strict=True))
                    if max_ch_diff > hex_tol:
                        failures.append(
                            _row(
                                "gamut.srgb",
                                f"{hex_str} != {expected_hex}",
                                "hex matches OKLCH",
                                "fail",
                                (
                                    f"{path} hex {hex_str} drifts from OKLCH({L:.4f}, {C:.4f}, {H:.2f}) -> "
                                    f"{expected_hex} by {max_ch_diff}/255 (silent clip or stale hex)"
                                ),
                                token_a=path,
                                theme=theme,
                            )
                        )
                        return

                # Verify any target_C exceeding sRGB gamut in description has an explicit [srgb-clamp: ...] record.
                m_target = re.search(r"target_C=([0-9.]+)", desc)
                if m_target:
                    target_c = float(m_target.group(1))
                    if target_c > C + 1e-4 and not color.CLAMP_NOTE_RE.search(desc):
                        failures.append(
                            _row(
                                "gamut.srgb",
                                "unrecorded-clamp",
                                "[srgb-clamp: ...] recorded",
                                "fail",
                                f"{path} clamped C from {target_c:.4f} to {C:.4f} without recording [srgb-clamp: ...]",
                                token_a=path,
                                theme=theme,
                            )
                        )
                        return
            return

        for k, v in node.items():
            if not str(k).startswith("$"):
                _walk(v, f"{path}.{k}")

    _walk(colour_group, "colour")
    if failures:
        rows.extend(failures)
    else:
        for theme in ("light", "dark"):
            n_checked = checked_by_theme[theme]
            n_clamped = clamped_by_theme[theme]
            rows.append(
                _row(
                    "gamut.srgb",
                    "in-gamut",
                    "sRGB [0, 1]",
                    "pass" if n_checked > 0 else "fail",
                    (
                        f"all {n_checked} {theme} colour tokens within linear sRGB [0, 1] "
                        f"({n_clamped} gamut clamp(s) recorded)"
                    ),
                    token_a=f"colour.{theme}",
                    theme=theme,
                )
            )
    return rows


# ---------------------------------------------------------------- Rule 5: scale.spacing


def _check_scale_spacing(tokens: dict[str, Any], th: dict[str, Any]) -> list[dict[str, Any]]:
    base_px = float(th["spacing"]["base_px"])
    min_steps = int(th["spacing"]["min_steps"])
    spacing_group = tokens.get("spacing")
    if not isinstance(spacing_group, dict):
        return [
            _row(
                "scale.spacing",
                "missing",
                f"{base_px:g}px base, monotonic",
                "fail",
                "spacing token group is missing",
                token_a="spacing",
            )
        ]

    steps: list[tuple[str, float, str]] = []
    for k, v in spacing_group.items():
        if str(k).startswith("$") or not isinstance(v, dict) or "$value" not in v:
            continue
        val = v["$value"]
        if not isinstance(val, dict) or not isinstance(val.get("value"), (int, float)):
            return [
                _row(
                    "scale.spacing",
                    "invalid",
                    f"{base_px:g}px base, monotonic",
                    "fail",
                    f"spacing.{k} does not carry a numeric dimension $value",
                    token_a=f"spacing.{k}",
                )
            ]
        unit = str(val.get("unit") or "")
        px = float(val["value"]) * (16.0 if unit == "rem" else 1.0)
        steps.append((str(k), px, unit))

    if len(steps) < min_steps:
        return [
            _row(
                "scale.spacing",
                len(steps),
                f">={min_steps} steps on {base_px:g}px base",
                "fail",
                f"spacing defines only {len(steps)} step(s) (need >={min_steps})",
                token_a="spacing",
            )
        ]

    off_base = [(k, px) for k, px, _u in steps if abs(math.remainder(px, base_px)) > 1e-6 or px < 0]
    if off_base:
        bad_k, bad_px = off_base[0]
        return [
            _row(
                "scale.spacing",
                f"{bad_px:g}px",
                f"{base_px:g}px base, monotonic",
                "fail",
                f"spacing.{bad_k} is {bad_px:g}px, which is not a multiple of the {base_px:g}px base",
                token_a=f"spacing.{bad_k}",
            )
        ]

    for idx in range(1, len(steps)):
        prev_k, prev_px, _ = steps[idx - 1]
        cur_k, cur_px, _ = steps[idx]
        if cur_px <= prev_px:
            return [
                _row(
                    "scale.spacing",
                    f"{prev_px:g}px -> {cur_px:g}px",
                    f"{base_px:g}px base, monotonic",
                    "fail",
                    f"spacing scale is not strictly monotonic: spacing.{prev_k}={prev_px:g}px -> spacing.{cur_k}={cur_px:g}px",
                    token_a=f"spacing.{cur_k}",
                    token_b=f"spacing.{prev_k}",
                )
            ]

    vals_str = ", ".join(f"{px:g}px" for _k, px, _u in steps)
    return [
        _row(
            "scale.spacing",
            f"{base_px:g}px base",
            f"{base_px:g}px base, monotonic",
            "pass",
            f"{len(steps)} monotonic spacing steps on {base_px:g}px base: [{vals_str}]",
            token_a="spacing",
        )
    ]


# ---------------------------------------------------------------- Rule 6: scale.type


def _check_scale_type(tokens: dict[str, Any], th: dict[str, Any]) -> list[dict[str, Any]]:
    t_th = th["type"]
    body_min = float(t_th["body_min_px"])
    r_min = float(t_th["ratio_min"])
    r_max = float(t_th["ratio_max"])
    r_spread = float(t_th["ratio_max_spread"])
    lh_min = float(t_th["line_height_min"])
    lh_max = float(t_th["line_height_max"])
    threshold_desc = (
        f"body>={body_min:g}px, ratio {r_min:.2f}..{r_max:.2f} (spread<={r_spread:.2f}), "
        f"lh {lh_min:.2f}..{lh_max:.2f}"
    )

    type_group = tokens.get("type") if isinstance(tokens.get("type"), dict) else {}
    scale_group = type_group.get("scale") if isinstance(type_group.get("scale"), dict) else {}
    lh_group = type_group.get("lineHeight") if isinstance(type_group.get("lineHeight"), dict) else {}

    steps: list[tuple[str, float]] = []
    for k, v in scale_group.items():
        if str(k).startswith("$"):
            continue
        px = _dimension_px(v)
        if px is not None:
            steps.append((str(k), px))

    if len(steps) < 3:
        return [
            _row(
                "scale.type",
                len(steps),
                threshold_desc,
                "fail",
                f"type.scale defines only {len(steps)} step(s) (need >=3)",
                token_a="type.scale",
            )
        ]

    body_tok = "base" if "base" in dict(steps) else ("body" if "body" in dict(steps) else "")
    body_px = dict(steps).get(body_tok)
    if body_px is None or body_px < body_min:
        return [
            _row(
                "scale.type",
                f"{body_px or 0:g}px",
                threshold_desc,
                "fail",
                f"body size type.scale.{body_tok or 'base'} is {body_px or 0:g}px (need >={body_min:g}px)",
                token_a=f"type.scale.{body_tok or 'base'}",
            )
        ]

    ratios: list[float] = []
    for idx in range(1, len(steps)):
        prev_k, prev_px = steps[idx - 1]
        cur_k, cur_px = steps[idx]
        if cur_px <= prev_px or prev_px <= 0:
            return [
                _row(
                    "scale.type",
                    f"{prev_px:g}px -> {cur_px:g}px",
                    threshold_desc,
                    "fail",
                    f"type.scale is not monotonic: {prev_k}={prev_px:g}px -> {cur_k}={cur_px:g}px",
                    token_a=f"type.scale.{cur_k}",
                    token_b=f"type.scale.{prev_k}",
                )
            ]
        ratios.append(cur_px / prev_px)

    min_r, max_r = min(ratios), max(ratios)
    spread = max_r - min_r
    if min_r < r_min - 1e-6 or max_r > r_max + 1e-6 or spread > r_spread + 1e-6:
        ratios_str = ", ".join(f"{r:.3f}" for r in ratios)
        return [
            _row(
                "scale.type",
                round(spread, 4),
                threshold_desc,
                "fail",
                (
                    f"type.scale step ratios [{ratios_str}] have range {min_r:.3f}..{max_r:.3f} "
                    f"(spread={spread:.3f} > {r_spread:.2f} or outside {r_min:.2f}..{r_max:.2f})"
                ),
                token_a="type.scale",
            )
        ]

    lh_vals: list[tuple[str, float]] = []
    for k, v in lh_group.items():
        if str(k).startswith("$") or not isinstance(v, dict):
            continue
        raw_lh = v.get("$value")
        if isinstance(raw_lh, (int, float)) and not isinstance(raw_lh, bool):
            lh_vals.append((str(k), float(raw_lh)))

    if not lh_vals:
        return [
            _row(
                "scale.type",
                "missing-lineHeight",
                threshold_desc,
                "fail",
                "type.lineHeight defines no numeric line-height tokens",
                token_a="type.lineHeight",
            )
        ]

    for lh_k, lh_v in lh_vals:
        if not (lh_min - 1e-6 <= lh_v <= lh_max + 1e-6):
            return [
                _row(
                    "scale.type",
                    round(lh_v, 3),
                    threshold_desc,
                    "fail",
                    f"type.lineHeight.{lh_k}={lh_v:.2f} ({lh_v * 100:.0f}%) outside 120-145% ({lh_min:.2f}..{lh_max:.2f})",
                    token_a=f"type.lineHeight.{lh_k}",
                )
            ]

    mean_ratio = round(sum(ratios) / len(ratios), 3)
    steps_str = ", ".join(f"{k}={px:g}px" for k, px in steps)
    lh_str = ", ".join(f"{k}={v:.2f}" for k, v in lh_vals)
    return [
        _row(
            "scale.type",
            mean_ratio,
            threshold_desc,
            "pass",
            f"body={body_px:g}px, ratio={mean_ratio:.3f} (spread={spread:.3f}), steps=[{steps_str}], lineHeight=[{lh_str}]",
            token_a="type.scale",
        )
    ]


# ---------------------------------------------------------------- Rule 7: type.fallback


def _check_type_fallback(tokens: dict[str, Any], th: dict[str, Any]) -> list[dict[str, Any]]:
    min_fams = int(th["type"]["fallback_min_families"])
    type_group = tokens.get("type") if isinstance(tokens.get("type"), dict) else {}
    fam_group = type_group.get("family") if isinstance(type_group.get("family"), dict) else {}
    if not fam_group:
        return [
            _row(
                "type.fallback",
                0,
                min_fams,
                "fail",
                "type.family group is missing",
                token_a="type.family",
            )
        ]

    rows: list[dict[str, Any]] = []
    for k, v in fam_group.items():
        if str(k).startswith("$") or not isinstance(v, dict):
            continue
        raw = v.get("$value")
        if isinstance(raw, str):
            parts = [p.strip().strip("'\"") for p in raw.split(",") if p.strip().strip("'\"")]
        elif isinstance(raw, list):
            parts = [str(p).strip().strip("'\"") for p in raw if str(p).strip().strip("'\"")]
        else:
            parts = []

        unique_parts: list[str] = []
        for p in parts:
            if p.lower() not in {u.lower() for u in unique_parts}:
                unique_parts.append(p)

        has_fallback = isinstance(raw, list) and len(unique_parts) >= min_fams
        rows.append(
            _row(
                "type.fallback",
                len(unique_parts),
                min_fams,
                "pass" if has_fallback else "fail",
                (
                    f"type.family.{k} stack has {len(unique_parts)} family/families "
                    f"({', '.join(unique_parts) or 'empty'}; need list of >={min_fams} families)"
                ),
                token_a=f"type.family.{k}",
            )
        )
    return rows


# ---------------------------------------------------------------- Rule 8: tokens.schema


def _check_tokens_schema(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        contracts.validate_tokens(tokens, step="proof", file="tokens.json", require_all_parts=True)
    except contracts.ContractError as exc:
        msg = str(exc)
        field = "<root>"
        m = re.search(r"tokens\.json:\s*([^:;\s]+):", msg)
        if m:
            field = m.group(1)
        return [
            _row(
                "tokens.schema",
                "invalid",
                "closed TOKENS_SCHEMA",
                "fail",
                msg,
                token_a=field,
            )
        ]
    return [
        _row(
            "tokens.schema",
            "valid",
            "closed TOKENS_SCHEMA",
            "pass",
            "validates against closed DTCG TOKENS_SCHEMA with all 6 required parts",
            token_a="<root>",
        )
    ]


# ---------------------------------------------------------------- Battery evaluation


def _summarize_rule(rule_id: str, rule_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fails = [r for r in rule_rows if r["result"] == "fail"]
    chosen = fails[0] if fails else rule_rows[0]
    if len(rule_rows) == 1:
        return dict(chosen)
    if fails:
        return _row(
            rule_id,
            chosen["value"],
            chosen["threshold"],
            "fail",
            f"{len(fails)}/{len(rule_rows)} check(s) failed; worst: {chosen['evidence']}",
            token_a=chosen["token_a"],
            token_b=chosen["token_b"],
            theme=chosen["theme"],
        )
    return _row(
        rule_id,
        chosen["value"],
        chosen["threshold"],
        "pass",
        f"all {len(rule_rows)} check(s) passed (e.g. {chosen['evidence']})",
        token_a=chosen["token_a"],
        token_b=chosen["token_b"],
        theme=chosen["theme"],
    )


def evaluate_tokens(
    tokens: dict[str, Any],
    *,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all 8 deterministic proof rules on `tokens` and return rows, rule summary, and verdict."""
    th = thresholds or load_thresholds()
    by_rule: dict[str, list[dict[str, Any]]] = {
        "contrast.text": _check_contrast_text(tokens, th),
        "contrast.ui": _check_contrast_ui(tokens, th),
        "signal.separation": _check_signal_separation(tokens, th),
        "gamut.srgb": _check_gamut_srgb(tokens, th),
        "scale.spacing": _check_scale_spacing(tokens, th),
        "scale.type": _check_scale_type(tokens, th),
        "type.fallback": _check_type_fallback(tokens, th),
        "tokens.schema": _check_tokens_schema(tokens),
    }

    all_rows: list[dict[str, Any]] = []
    rule_summaries: list[dict[str, Any]] = []
    for rid in RULE_IDS:
        r_list = by_rule[rid]
        all_rows.extend(r_list)
        rule_summaries.append(_summarize_rule(rid, r_list))

    failing_rows = [r for r in all_rows if r["result"] == "fail"]
    failing_rules = [r["id"] for r in rule_summaries if r["result"] == "fail"]
    verdict = "fail" if failing_rows else "pass"

    return {
        "verdict": verdict,
        "rules": rule_summaries,
        "rows": all_rows,
        "failing_rows": failing_rows,
        "failing_rules": failing_rules,
        "totals": {
            "rules_total": len(RULE_IDS),
            "rules_passed": len(RULE_IDS) - len(failing_rules),
            "rules_failed": len(failing_rules),
            "rows_total": len(all_rows),
            "rows_passed": len(all_rows) - len(failing_rows),
            "rows_failed": len(failing_rows),
        },
        "table_md": format_markdown_table(rule_summaries, all_rows, verdict=verdict),
    }


def format_markdown_table(
    rules: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    verdict: str,
    title: str = "Stage 3 Deterministic Token Proof",
) -> str:
    """Format the 8-rule summary and detailed row table as Markdown (`03-proof/table.md`)."""
    lines = [
        f"# {title}",
        "",
        f"**Verdict:** `{verdict.upper()}`",
        "",
        "## Rule Summary (8 rules)",
        "",
        "| Rule | Theme | Token A | Token B | Value | Threshold | Result | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rules:
        lines.append(
            f"| `{r['id']}` | `{r['theme']}` | `{r['token_a']}` | `{r['token_b'] or '-'}` "
            f"| `{r['value']}` | `{r['threshold']}` | **{r['result'].upper()}** | {r['evidence']} |"
        )
    lines.extend(
        [
            "",
            "## Detailed Check Rows",
            "",
            "| Rule | Theme | Token A | Token B | Value | Threshold | Result | Evidence |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for r in rows:
        lines.append(
            f"| `{r['id']}` | `{r['theme']}` | `{r['token_a']}` | `{r['token_b'] or '-'}` "
            f"| `{r['value']}` | `{r['threshold']}` | {r['result']} | {r['evidence']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- Stage 3 workflow step (`03-proof/`)


def _render_sample_screen_html(brief_doc: dict[str, Any], directions_doc: dict[str, Any]) -> str:
    product = html.escape(brief_doc["product"])
    sec_by_id = {s["id"]: s["body"] for s in brief_doc["sections"]}
    what_it_is = html.escape(sec_by_id.get("what_it_is") or "")
    who_for = html.escape(sec_by_id.get("who_for") or "")
    constraints_html = "".join(
        f"<li>{html.escape(item['text'])} <small>({html.escape(item['source_ref'])})</small></li>"
        for item in brief_doc["constraints"]
    ) or "<li>No fixed constraints listed.</li>"
    cards_html = "".join(
        f"<article data-direction='{html.escape(d['id'])}'>"
        f"<h2>{html.escape(d['name'])}</h2><p>{html.escape(d['summary'])}</p></article>"
        for d in directions_doc["directions"]
    )
    return (
        "<!doctype html>\n"
        "<html lang='en'>\n"
        "<head><meta charset='utf-8'><title>"
        f"{product} — Representative Foundation Sample Screen</title></head>\n"
        f"<body data-surface='sample_screen' data-product='{product}'>\n"
        f"<main><h1>{product}</h1><p>{what_it_is}</p><p>{who_for}</p>"
        f"<section><h2>Brief Constraints</h2><ul>{constraints_html}</ul></section>"
        f"<section><h2>Candidate Directions</h2>{cards_html}</section></main>\n"
        "</body>\n</html>\n"
    )


def _resolve_surface_record(
    brief_doc: dict[str, Any],
    *,
    base_url: str | None,
    commit: str | None,
    ref: str | None,
    allow_red_commit: bool,
    sample_rel: str,
) -> dict[str, Any]:
    clean_url = (base_url or "").strip()
    requested = brief_doc.get("render_surface", "app")
    if requested == "app" and clean_url:
        return {
            "kind": "app",
            "fallback": False,
            "reason": f"live app render surface at {clean_url}",
            "base_url": clean_url,
            "commit": (commit or "").strip() or None,
            "ref": (ref or "").strip() or None,
            "allow_red_commit": bool(allow_red_commit),
            "sample_screen": None,
        }
    return {
        "kind": "sample_screen",
        "fallback": True,
        "reason": "no live app render surface; using representative sample screen built from 01-brief/brief.json",
        "base_url": None,
        "commit": None,
        "ref": (ref or "").strip() or None,
        "allow_red_commit": bool(allow_red_commit),
        "sample_screen": sample_rel,
    }


def run(
    ws: Workspace,
    *,
    base_url: str | None = None,
    commit: str | None = None,
    ref: str | None = None,
    allow_red_commit: bool = False,
) -> dict[str, Any]:
    """Execute Stage 3 (`proof`): run the 8-rule battery over each candidate direction and write `03-proof/`."""
    step_ws = ws.for_step("proof")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    directions_doc = step_ws.read_json("02-directions/directions.json")

    out_dir = step_ws.folder("proof")
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_rel = "03-proof/sample-screen.html"
    surface = _resolve_surface_record(
        brief_doc,
        base_url=base_url,
        commit=commit,
        ref=ref,
        allow_red_commit=allow_red_commit,
        sample_rel=sample_rel,
    )
    if surface["kind"] == "sample_screen":
        sample_html = _render_sample_screen_html(brief_doc, directions_doc)
        (out_dir / "sample-screen.html").write_text(sample_html, encoding="utf-8")

    th = load_thresholds()
    previews: list[dict[str, Any]] = []
    direction_reports: list[dict[str, Any]] = []
    combined_rows: list[dict[str, Any]] = []
    md_sections: list[str] = []

    for entry in directions_doc["directions"]:
        did = entry["id"]
        dname = str(entry.get("name") or did)
        tok_rel = entry["tokens_file"]
        tokens_doc = step_ws.read_json(tok_rel)
        contracts.validate_tokens(tokens_doc, step="proof", file=tok_rel, require_all_parts=True)
        md_text = step_ws.read_text(entry["design_md_file"])
        contracts.validate_design_md(md_text, step="proof", file=entry["design_md_file"])

        ev = evaluate_tokens(tokens_doc, thresholds=th)
        direction_reports.append(
            {
                "direction": did,
                "name": dname,
                "tokens_file": tok_rel,
                "verdict": ev["verdict"],
                "rules": ev["rules"],
                "rows": ev["rows"],
                "failing_rows": ev["failing_rows"],
            }
        )
        combined_rows.extend(ev["rows"])
        md_sections.append(
            format_markdown_table(
                ev["rules"],
                ev["rows"],
                verdict=ev["verdict"],
                title=f"Direction `{did}` — {dname}",
            )
        )

        preview_rel = f"03-proof/preview-{did}.html"
        (out_dir / f"preview-{did}.html").write_text(
            f"<!doctype html><html lang='en'><body data-direction='{html.escape(did)}' "
            f"data-surface='{surface['kind']}' data-proof-verdict='{ev['verdict']}'>"
            f"<h1>{html.escape(dname)}</h1></body></html>\n",
            encoding="utf-8",
        )
        previews.append(
            {
                "direction": did,
                "surface_kind": surface["kind"],
                "artifact": preview_rel,
                "status": "ready",
            }
        )

    overall_verdict = "pass" if all(d["verdict"] == "pass" for d in direction_reports) else "fail"
    header_lines = [
        f"# Stage 3 Proof Table — `{brief_doc['product']}`",
        "",
        f"**Overall Verdict:** `{overall_verdict.upper()}`",
        "",
        "| Direction | Name | Verdict | Rules Passed | Failing Rules |",
        "| --- | --- | --- | --- | --- |",
    ]
    for d in direction_reports:
        failed_ids = [r["id"] for r in d["rules"] if r["result"] == "fail"]
        header_lines.append(
            f"| `{d['direction']}` | {d['name']} | **{d['verdict'].upper()}** "
            f"| {8 - len(failed_ids)}/8 | {', '.join(f'`{x}`' for x in failed_ids) or 'none'} |"
        )
    table_md = "\n".join(header_lines) + "\n\n" + "\n".join(md_sections)
    (out_dir / "table.md").write_text(table_md, encoding="utf-8")

    proof_doc = {
        "product": brief_doc["product"],
        "verdict": overall_verdict,
        "table_file": "03-proof/table.md",
        "surface": surface,
        "previews": previews,
        "directions": direction_reports,
        "rows": combined_rows,
    }
    contracts.validate("proof", proof_doc, step="proof")
    (out_dir / "proof.json").write_text(json.dumps(proof_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    step_ws.mark("proof", "done", surface_kind=surface["kind"])
    return {
        "ok": True,
        "step": "proof",
        "status": "done",
        "product": brief_doc["product"],
        "verdict": overall_verdict,
        "surface_kind": surface["kind"],
        "fallback": surface["fallback"],
        "previews_count": len(previews),
        "table": "03-proof/table.md",
        "sheet": "03-proof/table.md",
    }
