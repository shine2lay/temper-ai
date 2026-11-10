"""Foundation preview renderer: re-skin captured screens (or a brief-built sample screen) via token substitution.

Loads one or more DTCG token sets (`tokens.json`), maps token roles to RollCall's 29 `shell.css` custom
properties (plus companion aliases in `tokens.css` and any custom colour tokens in the set), injects the
override into captured HTML pages or a no-app sample screen, renders both themes (`light`, `dark`) at both
widths (`390` phone, `1440` desktop) through `design_capture` (`playwright-mcp`), builds per-direction and
side-by-side contact sheets via `app_screen.existing_sheet.build`, and produces an honesty report recording
`substituted`, `inert`, and `foreign` colours plus pixel-shift and pairwise-diff measurements.
"""
from __future__ import annotations

import base64
import html
import json
import math
import os
import re
import shutil
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DESIGN_BIN = HERE.parent
if str(DESIGN_BIN) not in sys.path:
    sys.path.insert(0, str(DESIGN_BIN))
from app_screen import existing_sheet  # noqa: E402, I001
from foundation import brief as brief_mod  # noqa: E402, I001


class PreviewError(RuntimeError):
    """Raised when token loading, screen discovery, browser rendering, or sheet building fails."""


try:
    from PIL import Image, ImageChops, ImageStat  # noqa: E402, I001
except ImportError as _pil_exc:
    raise PreviewError(
        "Pillow (PIL) is required for foundation preview rendering and contact sheets; install pillow in the active environment"
    ) from _pil_exc


def _require_pillow() -> None:
    try:
        from PIL import (  # noqa: I001, PLC0415
            Image as _img,
            ImageChops as _chops,
            ImageStat as _stat,
        )
    except ImportError as exc:
        raise PreviewError(
            "Pillow (PIL) is required for foundation preview rendering and contact sheets; install pillow in the active environment"
        ) from exc
    if Image is None or ImageChops is None or ImageStat is None or _img is None or _chops is None or _stat is None:
        raise PreviewError(
            "Pillow (PIL) is required for foundation preview rendering and contact sheets; install pillow in the active environment"
        )
    existing_sheet._require_pillow()


THEMES: tuple[str, ...] = ("light", "dark")
WIDTHS: dict[int, int] = {
    390: 844,
    1440: 900,
}
DEFAULT_BROWSER_WORKER = "http://playwright-mcp:8931/mcp"
DEFAULT_BROWSER_HOST = "http://127.0.0.1:8931/mcp"
PIXEL_DIFF_FLOOR = 0.05
MIN_PAIRWISE_DIFF_RATIO = PIXEL_DIFF_FLOOR
PIXEL_CHANNEL_EPSILON = 6

# The 23 canonical colour roles from RollCall's frontend/src/app/styles/shell.css, with companion
# custom-property aliases from shared/styles/tokens.css so live RollCall screens re-colour cleanly.
CANONICAL_COLOR_ROLES: tuple[str, ...] = (
    "paper",
    "paper-2",
    "surface",
    "ink",
    "ink-2",
    "ink-3",
    "line",
    "accent",
    "accent-ink",
    "accent-hover",
    "accent-wash",
    "accent-border",
    "good",
    "warn",
    "risk",
    "focus",
    "moneyness-itm",
    "moneyness-itm-wash",
    "moneyness-otm",
    "moneyness-otm-wash",
    "week-bg",
    "week-ink",
    "do-ink",
)
CANONICAL_COLOUR_ROLES: tuple[str, ...] = CANONICAL_COLOR_ROLES

CANONICAL_NON_COLOR_ROLES: tuple[str, ...] = (
    "font-display",
    "font-body",
    "font-mono",
    "radius-sm",
    "radius",
    "radius-lg",
)

SHELL_CUSTOM_PROPERTIES: tuple[str, ...] = tuple(
    f"--{r}" for r in (*CANONICAL_COLOR_ROLES, *CANONICAL_NON_COLOR_ROLES)
)

ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "paper": ("--bg", "--surface-canvas"),
    "paper-2": ("--surface-2", "--surface-sunken"),
    "surface": ("--surface-raised",),
    "ink": ("--text",),
    "ink-2": ("--muted", "--text-2"),
    "ink-3": ("--ink-4", "--text-3"),
    "line": ("--border", "--line-2"),
    "accent": (),
    "accent-ink": ("--accent-on",),
    "accent-hover": ("--accent-strong",),
    "accent-wash": ("--accent-soft", "--accent-faint", "--accent-bg"),
    "accent-border": (),
    "good": ("--good-ink",),
    "warn": ("--warn-ink", "--close-ink", "--close-edge"),
    "risk": ("--risk-ink",),
    "focus": (),
    "moneyness-itm": ("--ok-ink", "--ok-edge", "--ok-solid"),
    "moneyness-itm-wash": ("--ok-bg", "--good-bg"),
    "moneyness-otm": ("--do-edge", "--do-solid"),
    "moneyness-otm-wash": ("--do-bg", "--risk-bg"),
    "week-bg": ("--close-bg", "--warn-bg"),
    "week-ink": ("--week-edge",),
    "do-ink": (),
}

# Candidate token paths inside `colour` (or `colour.<theme>`) for each of the 23 canonical colour roles.
ROLE_TOKEN_PATHS: dict[str, tuple[str, ...]] = {
    "paper": ("paper", "surface.canvas", "canvas"),
    "paper-2": ("paper-2", "paper_2", "surface.sunken", "sunken", "ramp.neutral.200"),
    "surface": ("surface", "surface.raised", "raised"),
    "ink": ("ink", "ink.primary", "primary"),
    "ink-2": ("ink-2", "ink_2", "ink.secondary", "muted", "secondary"),
    "ink-3": ("ink-3", "ink_3", "ink.muted", "ink.heading"),
    "line": ("line", "line.border", "border"),
    "accent": ("accent", "semantic.accent.solid", "accent.solid"),
    "accent-ink": ("accent-ink", "accent_ink", "accent_on", "accent-on", "semantic.accent.on_solid"),
    "accent-hover": ("accent-hover", "accent_hover", "semantic.accent.text", "ramp.accent.700"),
    "accent-wash": ("accent-wash", "accent_wash", "ramp.accent.100", "surface.ghost_fill"),
    "accent-border": ("accent-border", "accent_border", "semantic.accent.ui", "line.strong"),
    "good": ("good", "semantic.good.text", "good.text"),
    "warn": ("warn", "semantic.warn.text", "warn.text"),
    "risk": ("risk", "semantic.risk.text", "risk.text"),
    "focus": ("focus", "line.focus"),
    "moneyness-itm": ("moneyness-itm", "moneyness_itm", "semantic.good.ui"),
    "moneyness-itm-wash": ("moneyness-itm-wash", "moneyness_itm_wash", "ramp.good.100"),
    "moneyness-otm": ("moneyness-otm", "moneyness_otm", "semantic.risk.ui"),
    "moneyness-otm-wash": ("moneyness-otm-wash", "moneyness_otm_wash", "ramp.risk.100"),
    "week-bg": ("week-bg", "week_bg", "ramp.info.100"),
    "week-ink": ("week-ink", "week_ink", "semantic.info.text"),
    "do-ink": ("do-ink", "do_ink", "ramp.risk.800"),
}

NON_COLOR_TOKEN_PATHS: dict[str, tuple[str, ...]] = {
    "font-display": ("typography.font-display", "typography.font_display", "typography.family_display", "typography.display"),
    "font-body": ("typography.font-body", "typography.font_body", "typography.family_sans", "typography.family_body", "typography.body"),
    "font-mono": ("typography.font-mono", "typography.font_mono", "typography.family_mono", "typography.mono"),
    "radius-sm": ("radius.radius-sm", "radius.radius_sm", "radius.sm"),
    "radius": ("radius.radius", "radius.md", "radius.default"),
    "radius-lg": ("radius.radius-lg", "radius.radius_lg", "radius.lg"),
}


@dataclass(frozen=True)
class TokenBinding:
    token: str
    role: str
    css_var: str
    value: str
    alias_vars: tuple[str, ...] = field(default_factory=tuple)
    is_color: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "role": self.role,
            "css_var": self.css_var,
            "alias_vars": list(self.alias_vars),
            "value": self.value,
            "is_color": self.is_color,
        }


def _kebab(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")


def _lookup_path(node: dict[str, Any], dotted: str) -> tuple[str, Any] | None:
    cur: Any = node
    parts = dotted.split(".")
    for part in parts:
        if not isinstance(cur, dict):
            return None
        if part in cur:
            cur = cur[part]
        elif part.replace("-", "_") in cur:
            part = part.replace("-", "_")
            cur = cur[part]
        elif part.replace("_", "-") in cur:
            part = part.replace("_", "-")
            cur = cur[part]
        else:
            return None
    return dotted, cur


def _format_token_value(leaf: Any, root: dict[str, Any], theme: str = "light", _depth: int = 0) -> str | None:
    if _depth > 8 or leaf is None:
        return None
    if isinstance(leaf, str):
        val = leaf.strip()
        if val.startswith("{") and val.endswith("}"):
            ref_path = val[1:-1].strip()
            found = _lookup_path(root, ref_path)
            if found is not None:
                return _format_token_value(found[1], root, theme=theme, _depth=_depth + 1)
        return val or None
    if isinstance(leaf, (int, float)):
        return str(leaf)
    if not isinstance(leaf, dict):
        return None

    # Support token-level dark mode extension if present.
    if theme == "dark":
        ext = leaf.get("$extensions")
        if isinstance(ext, dict):
            for ext_key in ("mode", "com.temper.design"):
                sub = ext.get(ext_key)
                if isinstance(sub, dict) and "dark" in sub:
                    dark_val = _format_token_value(sub["dark"], root, theme="light", _depth=_depth + 1)
                    if dark_val:
                        return dark_val

    raw = leaf.get("$value", leaf if ("hex" in leaf or "colorSpace" in leaf or "value" in leaf) else None)
    if raw is None:
        return None
    if isinstance(raw, str):
        return _format_token_value(raw, root, theme=theme, _depth=_depth + 1)
    if isinstance(raw, (int, float)):
        return str(raw)
    if isinstance(raw, list):
        return ", ".join(str(x) for x in raw if str(x).strip())
    if isinstance(raw, dict):
        if isinstance(raw.get("hex"), str) and raw["hex"].strip():
            return raw["hex"].strip().lower()
        if raw.get("colorSpace") == "oklch" and isinstance(raw.get("components"), list) and len(raw["components"]) == 3:
            l_val, c_val, h_val = raw["components"]
            return f"oklch({l_val} {c_val} {h_val})"
        if "value" in raw and "unit" in raw:
            return f"{raw['value']}{raw['unit']}"
    return None


def load_tokens(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Load and validate a token set from a JSON path or dict."""
    if isinstance(source, dict):
        doc = source
    else:
        path = Path(source)
        if not path.is_file():
            raise PreviewError(f"tokens file does not exist: {path}")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PreviewError(f"tokens file is not valid JSON ({path}): {exc}") from exc
    if not isinstance(doc, dict):
        raise PreviewError("tokens root must be a JSON object")
    if not isinstance(doc.get("colour") or doc.get("color"), dict):
        raise PreviewError("tokens.json must contain a 'colour' group")
    return doc


def _is_token_leaf(node: Any) -> bool:
    if isinstance(node, str) and node.strip():
        return True
    if not isinstance(node, dict):
        return False
    return "$value" in node or "hex" in node or "colorSpace" in node


def _walk_leaves(node: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for k, v in node.items():
        if str(k).startswith("$"):
            continue
        p = f"{prefix}.{k}" if prefix else str(k)
        if _is_token_leaf(v):
            out.append((p, v))
        elif isinstance(v, dict):
            out.extend(_walk_leaves(v, p))
    return out


def extract_theme_bindings(tokens_doc: dict[str, Any], theme: str = "light") -> list[TokenBinding]:
    """Map a DTCG token document to CSS custom property bindings for `theme` ('light' or 'dark')."""
    if theme not in THEMES:
        raise PreviewError(f"unsupported theme {theme!r}; expected one of {THEMES}")
    colour_group = tokens_doc.get("colour") or tokens_doc.get("color") or {}
    if not isinstance(colour_group, dict):
        raise PreviewError("tokens.colour must be an object")

    has_mode_subtrees = (
        isinstance(colour_group.get(theme), dict)
        and not _is_token_leaf(colour_group.get(theme))
    )
    mode_root: dict[str, Any] = colour_group[theme] if has_mode_subtrees else colour_group
    mode_prefix = f"colour.{theme}" if has_mode_subtrees else "colour"

    # Also check top-level $extensions dark map when flat colour group is used.
    top_dark_map: dict[str, Any] = {}
    if theme == "dark" and not has_mode_subtrees:
        ext = tokens_doc.get("$extensions")
        if isinstance(ext, dict):
            td = ext.get("com.temper.design") or ext.get("mode") or {}
            if isinstance(td, dict) and isinstance(td.get("dark"), dict):
                top_dark_map = td["dark"]
        if not top_dark_map and isinstance(colour_group.get("dark"), dict) and not _is_token_leaf(colour_group["dark"]):
            top_dark_map = colour_group["dark"]

    bindings: list[TokenBinding] = []
    consumed_paths: set[str] = set()

    for role in CANONICAL_COLOR_ROLES:
        candidates = ROLE_TOKEN_PATHS.get(role, (role,))
        matched: tuple[str, Any] | None = None
        source_prefix = mode_prefix
        for cand in candidates:
            if top_dark_map:
                found_dark = _lookup_path(top_dark_map, cand)
                if found_dark is not None and _is_token_leaf(found_dark[1]):
                    matched = found_dark
                    source_prefix = "colour.dark"
                    break
            found = _lookup_path(mode_root, cand)
            if found is not None and _is_token_leaf(found[1]):
                matched = found
                break
            if has_mode_subtrees:
                found_top = _lookup_path(colour_group, cand)
                if found_top is not None and _is_token_leaf(found_top[1]):
                    matched = found_top
                    source_prefix = "colour"
                    break
        if matched is None:
            continue
        rel_path, leaf = matched
        val = _format_token_value(leaf, tokens_doc, theme=theme)
        if not val:
            continue
        consumed_paths.add(rel_path)
        consumed_paths.add(rel_path.replace("-", "_"))
        consumed_paths.add(rel_path.replace("_", "-"))
        bindings.append(
            TokenBinding(
                token=f"{source_prefix}.{rel_path}",
                role=role,
                css_var=f"--{role}",
                value=val,
                alias_vars=ROLE_ALIASES.get(role, ()),
                is_color=True,
            )
        )

    # Also bind any explicit custom colour tokens declared in the token set (excluding raw ramp steps)
    # so unused declared tokens are honestly surfaced as `inert` by the browser probe.
    extra_sources: list[tuple[str, dict[str, Any]]] = [(mode_prefix, mode_root)]
    if has_mode_subtrees:
        extra_sources.append(("colour", {k: v for k, v in colour_group.items() if k not in THEMES}))

    bound_roles = {b.role for b in bindings}
    for src_prefix, tree in extra_sources:
        for rel_path, leaf in _walk_leaves(tree):
            if rel_path.startswith("ramp."):
                continue
            norm_rel = rel_path.replace("_", "-")
            if rel_path in consumed_paths or norm_rel in consumed_paths:
                continue
            role_name = _kebab(rel_path.split(".")[-1])
            if role_name == "accent-on":
                role_name = "accent-ink"
            elif role_name == "muted":
                role_name = "ink-2"
            if role_name in bound_roles:
                continue
            val = _format_token_value(leaf, tokens_doc, theme=theme)
            if not val:
                continue
            bound_roles.add(role_name)
            bindings.append(
                TokenBinding(
                    token=f"{src_prefix}.{rel_path}",
                    role=role_name,
                    css_var=f"--{role_name}",
                    value=val,
                    alias_vars=ROLE_ALIASES.get(role_name, ()),
                    is_color=True,
                )
            )

    for role, paths in NON_COLOR_TOKEN_PATHS.items():
        for cand in paths:
            found = _lookup_path(tokens_doc, cand)
            if found is not None and _is_token_leaf(found[1]):
                val = _format_token_value(found[1], tokens_doc, theme=theme)
                if val:
                    bindings.append(
                        TokenBinding(
                            token=cand,
                            role=role,
                            css_var=f"--{role}",
                            value=val,
                            alias_vars=(),
                            is_color=False,
                        )
                    )
                    break

    return bindings


def build_override_css(bindings: list[TokenBinding], theme: str = "light") -> str:
    """Build the deterministic CSS override stylesheet injected into captured or sample screens."""
    lines: list[str] = [
        "*, *::before, *::after {",
        "  animation: none !important;",
        "  transition: none !important;",
        "  caret-color: transparent !important;",
        "}",
        f":root, html, body, [data-theme], [data-theme='{theme}'], [data-theme='light'], [data-theme='dark'] {{",
        f"  color-scheme: {theme} !important;",
    ]
    seen_vars: set[str] = set()
    for b in bindings:
        for var_name in (b.css_var, *b.alias_vars):
            if var_name in seen_vars:
                continue
            seen_vars.add(var_name)
            lines.append(f"  {var_name}: {b.value} !important;")
    lines.append("}")
    return "\n".join(lines)


def _parse_brief_markdown(raw: str, *, product: str, brief_path: Path) -> dict[str, Any]:
    md_parser = getattr(brief_mod, "parse_brief_markdown", None)
    if callable(md_parser):
        doc = md_parser(raw, product=product)
    else:
        doc = brief_mod.parse_brief(
            raw,
            product=product,
            brief_path=brief_path,
            brief_rel=brief_path.name,
        )
    if not isinstance(doc, dict):
        raise PreviewError(f"markdown brief parser returned {type(doc).__name__}, expected dict")
    return doc


def _brief_fields(brief_source: str | Path | dict[str, Any] | None) -> dict[str, str]:
    defaults = {
        "product": "Foundation Sample Product",
        "what_it_is": "An operational workbench for reviewing portfolio exposure, active obligations, and weekly settlement signals.",
        "who_for": "Active operators who scan risk posture and execute time-sensitive adjustments.",
        "where_and_how_used": "Used across desktop workstations and mobile check-ins in both daylight and low-light environments.",
        "feel_and_anti_feel": "Calm, high-clarity, instrument-grade density; never decorative or noisy.",
        "constraints": "Must maintain WCAG AA contrast across light and dark themes with clear tabular alignment.",
    }
    if brief_source is None:
        return defaults
    if isinstance(brief_source, (str, Path)):
        if isinstance(brief_source, str) and not brief_source.strip():
            return defaults
        p = Path(brief_source)
        if p.exists():
            try:
                raw = p.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as read_exc:
                raise PreviewError(
                    f"unreadable brief {p}: {read_exc.__class__.__name__}: {read_exc}"
                ) from read_exc
            try:
                doc = json.loads(raw)
                if not isinstance(doc, dict) or not doc:
                    raise ValueError("brief JSON must be a non-empty object")
            except (json.JSONDecodeError, ValueError, TypeError) as json_exc:
                try:
                    doc = _parse_brief_markdown(raw, product=p.stem, brief_path=p)
                except (
                    brief_mod.BriefError,
                    ValueError,
                    TypeError,
                    KeyError,
                    AttributeError,
                    RuntimeError,
                ) as md_exc:
                    raise PreviewError(
                        f"malformed brief {p}: JSON parse failed ({json_exc.__class__.__name__}: {json_exc}); "
                        f"markdown parse failed ({md_exc.__class__.__name__}: {md_exc})"
                    ) from md_exc
        else:
            doc = {}
    elif isinstance(brief_source, dict):
        doc = brief_source
    else:
        doc = {}

    raw_sections = doc.get("sections")
    if isinstance(raw_sections, dict):
        sec: dict[str, Any] = raw_sections
    elif isinstance(raw_sections, list):
        sec = {
            str(s["id"]): s.get("body", "")
            for s in raw_sections
            if isinstance(s, dict) and isinstance(s.get("id"), str)
        }
        if "constraints" not in sec and isinstance(sec.get("fixed_constraints"), str):
            sec["constraints"] = sec["fixed_constraints"]
    else:
        sec = doc

    out = dict(defaults)
    if isinstance(doc.get("product"), str) and doc["product"].strip():
        out["product"] = doc["product"].strip()
    for k in ("what_it_is", "who_for", "where_and_how_used", "feel_and_anti_feel", "constraints"):
        v = sec.get(k) if isinstance(sec, dict) else None
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def build_sample_screen_html(brief_source: str | Path | dict[str, Any] | None = None) -> str:
    """Build the no-app representative sample screen exercising all 29 shell.css token roles."""
    info = _brief_fields(brief_source)
    prod = html.escape(info["product"])
    what = html.escape(info["what_it_is"])
    who = html.escape(info["who_for"])
    where = html.escape(info["where_and_how_used"])
    feel = html.escape(info["feel_and_anti_feel"])
    constraints = html.escape(info["constraints"])

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{prod} — Sample Screen</title>
<style>
:root, [data-theme="light"] {{
  --paper: #f6f1e6;
  --paper-2: #ede6d6;
  --surface: #fbf8f1;
  --ink: #0f1e32;
  --ink-2: #2f435d;
  --ink-3: #526781;
  --line: #d8ceb8;
  --accent: #0f6a7b;
  --accent-ink: #ffffff;
  --accent-hover: #0a4f5c;
  --accent-wash: #dff1f4;
  --accent-border: #82cbd6;
  --good: #0e6b50;
  --warn: #8a5200;
  --risk: #b42318;
  --focus: #0f6a7b;
  --moneyness-itm: #0b5d46;
  --moneyness-itm-wash: #d8f2e8;
  --moneyness-otm: #9e2a1c;
  --moneyness-otm-wash: #fde2dd;
  --week-bg: #e0eef9;
  --week-ink: #134e7a;
  --do-ink: #7f1d1d;
  --font-display: "Instrument Serif", Georgia, serif;
  --font-body: "Plus Jakarta Sans", system-ui, -apple-system, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
  --radius-sm: 4px;
  --radius: 8px;
  --radius-lg: 12px;
}}
[data-theme="dark"] {{
  --paper: #0b1523;
  --paper-2: #122136;
  --surface: #162840;
  --ink: #f4f0e6;
  --ink-2: #bfd0e2;
  --ink-3: #8aa2bd;
  --line: #263d5a;
  --accent: #3cbec9;
  --accent-ink: #071923;
  --accent-hover: #71cfd9;
  --accent-wash: #133648;
  --accent-border: #2c6d7a;
  --good: #4fd1a5;
  --warn: #f5b851;
  --risk: #f87268;
  --focus: #5ad2dc;
  --moneyness-itm: #5ce0b5;
  --moneyness-itm-wash: #123b34;
  --moneyness-otm: #ff8b80;
  --moneyness-otm-wash: #3d1d24;
  --week-bg: #17324d;
  --week-ink: #8ec8f6;
  --do-ink: #ffa198;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background-color: var(--paper);
  color: var(--ink);
  font-family: var(--font-body);
  line-height: 1.45;
  padding: 20px;
}}
.sample-shell {{
  max-width: 1360px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}}
.sample-header {{
  background-color: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}}
.eyebrow {{
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-3);
}}
.title {{
  font-family: var(--font-display);
  font-size: 26px;
  color: var(--ink);
}}
.subtitle {{
  font-size: 14px;
  color: var(--ink-2);
  max-width: 68ch;
}}
.actions-bar {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}}
.btn-primary {{
  background-color: var(--accent);
  color: var(--accent-ink);
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  padding: 8px 14px;
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 600;
}}
.btn-hover-preview {{
  background-color: var(--accent-wash);
  color: var(--accent-hover);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius);
  padding: 8px 14px;
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 600;
}}
.btn-focused {{
  background-color: var(--surface);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 8px 14px;
  font-family: var(--font-body);
  font-size: 13px;
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}}
.btn-disabled {{
  background-color: var(--paper-2);
  color: var(--ink-3);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 8px 14px;
  font-family: var(--font-body);
  font-size: 13px;
}}
.signal-strip {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}}
.signal-card {{
  background-color: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}}
.metric-val {{
  font-family: var(--font-mono);
  font-size: 22px;
  font-weight: 700;
}}
.metric-good {{ color: var(--good); }}
.metric-warn {{ color: var(--warn); }}
.metric-risk {{ color: var(--risk); }}
.table-card {{
  background-color: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  overflow: hidden;
}}
.table-toolbar {{
  background-color: var(--paper-2);
  border-bottom: 1px solid var(--line);
  padding: 10px 16px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}}
.week-pill {{
  background-color: var(--week-bg);
  color: var(--week-ink);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 3px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
}}
.do-pill {{
  background-color: var(--moneyness-otm-wash);
  color: var(--do-ink);
  border: 1px solid var(--moneyness-otm);
  border-radius: var(--radius-sm);
  padding: 3px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
}}
table.dense-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}}
table.dense-table th {{
  background-color: var(--paper-2);
  color: var(--ink-2);
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  font-weight: 600;
}}
table.dense-table td {{
  padding: 9px 12px;
  border-bottom: 1px solid var(--line);
  color: var(--ink);
}}
table.dense-table tr.row-selected td {{
  background-color: var(--accent-wash);
}}
.num {{
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}}
.badge-itm {{
  display: inline-block;
  background-color: var(--moneyness-itm-wash);
  color: var(--moneyness-itm);
  border: 1px solid var(--moneyness-itm);
  border-radius: var(--radius-sm);
  padding: 2px 7px;
  font-family: var(--font-mono);
  font-size: 11px;
}}
.badge-otm {{
  display: inline-block;
  background-color: var(--moneyness-otm-wash);
  color: var(--moneyness-otm);
  border: 1px solid var(--moneyness-otm);
  border-radius: var(--radius-sm);
  padding: 2px 7px;
  font-family: var(--font-mono);
  font-size: 11px;
}}
.brief-footer {{
  background-color: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 12px 16px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  font-size: 12px;
  color: var(--ink-2);
}}
</style>
</head>
<body data-token-role="paper font-body">
  <main class="sample-shell">
    <header class="sample-header" data-token-role="surface line radius-lg">
      <div>
        <div class="eyebrow" data-token-role="ink-3">Foundation Sample Surface · {who}</div>
        <h1 class="title" data-token-role="ink font-display">{prod}</h1>
        <p class="subtitle" data-token-role="ink-2">{what}</p>
      </div>
      <div class="actions-bar">
        <button type="button" class="btn-primary" data-token-role="accent accent-ink radius">Primary Action</button>
        <button type="button" class="btn-hover-preview" data-token-role="accent-wash accent-hover accent-border">Active Filter</button>
        <button type="button" class="btn-focused" data-token-role="focus">Focused Control</button>
        <button type="button" class="btn-disabled" disabled data-token-role="paper-2 ink-3 line">Disabled State</button>
      </div>
    </header>

    <section class="signal-strip" aria-label="Signal summary">
      <article class="signal-card" data-token-role="surface line">
        <span class="eyebrow" data-token-role="ink-3">Healthy Coverage</span>
        <strong class="metric-val metric-good" data-token-role="good font-mono">+14.8% ($4,820)</strong>
        <span class="subtitle" data-token-role="ink-2">8 positions clear of strike threshold</span>
      </article>
      <article class="signal-card" data-token-role="surface line">
        <span class="eyebrow" data-token-role="ink-3">Approaching Window</span>
        <strong class="metric-val metric-warn" data-token-role="warn font-mono">3 Expiring (2d)</strong>
        <span class="subtitle" data-token-role="ink-2">Delta between 0.28 and 0.35</span>
      </article>
      <article class="signal-card" data-token-role="surface line">
        <span class="eyebrow" data-token-role="ink-3">Immediate Attention</span>
        <strong class="metric-val metric-risk" data-token-role="risk font-mono">-2.4% ($1,190)</strong>
        <span class="subtitle" data-token-role="ink-2">1 contract requires roll review</span>
      </article>
    </section>

    <section class="table-card" data-token-role="surface line radius-lg">
      <div class="table-toolbar" data-token-role="paper-2 line">
        <h2 style="font-size:15px;color:var(--ink);font-family:var(--font-display);" data-token-role="ink font-display">Dense Schedule &amp; Signal Table</h2>
        <div style="display:flex;gap:8px;align-items:center;">
          <span class="week-pill" data-token-role="week-bg week-ink radius-sm">THIS WEEK · NOV 14</span>
          <span class="do-pill" data-token-role="do-ink moneyness-otm-wash moneyness-otm radius-sm">ACTION REQUIRED · 2</span>
        </div>
      </div>
      <table class="dense-table">
        <thead>
          <tr>
            <th data-token-role="paper-2 ink-2 line">Instrument</th>
            <th data-token-role="paper-2 ink-2 line">Contract</th>
            <th data-token-role="paper-2 ink-2 line">Spot / Strike</th>
            <th data-token-role="paper-2 ink-2 line">Moneyness</th>
            <th data-token-role="paper-2 ink-2 line">Net Yield</th>
            <th data-token-role="paper-2 ink-2 line">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr class="row-selected" data-token-role="accent-wash">
            <td data-token-role="ink"><strong>AAPL</strong> <span style="color:var(--ink-3);" data-token-role="ink-3">400 sh</span></td>
            <td class="num" data-token-role="font-mono">NOV 14 $230C</td>
            <td class="num" data-token-role="font-mono">$231.40 / $230.00</td>
            <td><span class="badge-itm" data-token-role="moneyness-itm moneyness-itm-wash radius-sm">ITM +0.6%</span></td>
            <td class="num metric-good" data-token-role="good font-mono">+$640.00</td>
            <td><span class="do-pill" data-token-role="do-ink">Roll Candidate</span></td>
          </tr>
          <tr>
            <td data-token-role="ink"><strong>MSFT</strong> <span style="color:var(--ink-3);" data-token-role="ink-3">200 sh</span></td>
            <td class="num" data-token-role="font-mono">NOV 21 $435C</td>
            <td class="num" data-token-role="font-mono">$424.10 / $435.00</td>
            <td><span class="badge-otm" data-token-role="moneyness-otm moneyness-otm-wash radius-sm">OTM -2.5%</span></td>
            <td class="num metric-warn" data-token-role="warn font-mono">+$410.00</td>
            <td><span class="week-pill" data-token-role="week-bg week-ink">Next Week</span></td>
          </tr>
          <tr>
            <td data-token-role="ink"><strong>NVDA</strong> <span style="color:var(--ink-3);" data-token-role="ink-3">300 sh</span></td>
            <td class="num" data-token-role="font-mono">NOV 14 $140C</td>
            <td class="num" data-token-role="font-mono">$144.80 / $140.00</td>
            <td><span class="badge-itm" data-token-role="moneyness-itm moneyness-itm-wash radius-sm">ITM +3.4%</span></td>
            <td class="num metric-risk" data-token-role="risk font-mono">-$380.00</td>
            <td><span class="badge-otm" data-token-role="moneyness-otm moneyness-otm-wash">In Breach</span></td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="brief-footer" data-token-role="paper-2 line radius">
      <div><strong style="color:var(--ink);">Context:</strong> {where}</div>
      <div><strong style="color:var(--ink);">Direction:</strong> {feel}</div>
      <div><strong style="color:var(--ink);">Constraints:</strong> {constraints}</div>
    </footer>
  </main>
</body>
</html>
"""


def sample_screen_roles(html_text: str | None = None) -> set[str]:
    """Return the set of token roles declared via `data-token-role` in the sample screen HTML."""
    doc = html_text if html_text is not None else build_sample_screen_html()
    roles: set[str] = set()
    for match in re.finditer(r'data-token-role="([^"]+)"', doc):
        for tok in match.group(1).split():
            if tok.strip():
                roles.add(tok.strip())
    return roles


extract_sample_screen_roles = sample_screen_roles


PROBE_IN_PAGE_JS = """(bindings) => {
    const toHex = (rgbStr) => {
        const m = String(rgbStr || '').match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
        if (!m) return String(rgbStr || '');
        const r = parseInt(m[1], 10), g = parseInt(m[2], 10), b = parseInt(m[3], 10);
        return '#' + [r, g, b].map(x => x.toString(16).padStart(2, '0')).join('');
    };
    const isTransparent = (v) => !v || v === 'transparent' || v === 'none' || /^rgba\\(\\d+,\\s*\\d+,\\s*\\d+,\\s*0(?:\\.0+)?\\)$/.test(v);
    const hasDirectText = (el) => {
        for (const n of el.childNodes) {
            if (n.nodeType === 3 && n.textContent.trim().length > 0) return true;
        }
        return false;
    };
    const selFor = (el) => {
        const tag = el.tagName.toLowerCase();
        if (el.id) return `${tag}#${el.id}`;
        if (typeof el.className === 'string' && el.className.trim()) {
            return `${tag}.${el.className.trim().split(/\\s+/).slice(0, 2).join('.')}`;
        }
        return tag;
    };
    const els = Array.from(document.querySelectorAll('body, body *')).filter(el => {
        const tag = el.tagName.toLowerCase();
        if (['script', 'style', 'link', 'meta', 'head', 'title', 'noscript'].includes(tag)) return false;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return false;
        const cs = getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity || '1') > 0;
    });
    const SVG_TAGS = new Set(['svg', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon']);
    const snapElem = (el) => {
        const cs = getComputedStyle(el);
        const out = {};
        if ((el === document.body || hasDirectText(el)) && !isTransparent(cs.color)) {
            out['color'] = cs.color;
        }
        if (!isTransparent(cs.backgroundColor)) out['background-color'] = cs.backgroundColor;
        if (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none' && !isTransparent(cs.borderTopColor)) out['border-top-color'] = cs.borderTopColor;
        if (parseFloat(cs.borderRightWidth) > 0 && cs.borderRightStyle !== 'none' && !isTransparent(cs.borderRightColor)) out['border-right-color'] = cs.borderRightColor;
        if (parseFloat(cs.borderBottomWidth) > 0 && cs.borderBottomStyle !== 'none' && !isTransparent(cs.borderBottomColor)) out['border-bottom-color'] = cs.borderBottomColor;
        if (parseFloat(cs.borderLeftWidth) > 0 && cs.borderLeftStyle !== 'none' && !isTransparent(cs.borderLeftColor)) out['border-left-color'] = cs.borderLeftColor;
        if (parseFloat(cs.outlineWidth) > 0 && cs.outlineStyle !== 'none' && !isTransparent(cs.outlineColor)) out['outline-color'] = cs.outlineColor;
        const tag = el.tagName.toLowerCase();
        if (SVG_TAGS.has(tag)) {
            if (el.hasAttribute('fill') && !isTransparent(cs.fill)) out['fill'] = cs.fill;
            if (el.hasAttribute('stroke') && !isTransparent(cs.stroke)) out['stroke'] = cs.stroke;
        }
        return out;
    };

    const baselineSnap = els.map(snapElem);
    const probeEl = document.createElement('style');
    probeEl.id = '__foundation_probe__';
    document.head.appendChild(probeEl);

    const setProbeVars = (varList, rgbVal) => {
        const decls = varList.map(v => `${v}: ${rgbVal} !important;`).join('\\n');
        probeEl.textContent = `:root, html, body, [data-theme], [data-theme="light"], [data-theme="dark"] {\\n${decls}\\n}`;
    };

    const colorBindings = bindings.filter(b => b.is_color !== false);
    const substituted = [];
    const inert = [];
    for (const b of colorBindings) {
        const vars = [b.css_var, ...(b.alias_vars || [])];
        setProbeVars(vars, 'rgb(1, 2, 3)');
        const lowSnap = els.map(snapElem);
        setProbeVars(vars, 'rgb(252, 253, 254)');
        const highSnap = els.map(snapElem);
        let affected = 0;
        for (let i = 0; i < els.length; i++) {
            const keys = new Set([...Object.keys(lowSnap[i]), ...Object.keys(highSnap[i])]);
            let changed = false;
            for (const k of keys) {
                if (lowSnap[i][k] !== highSnap[i][k]) {
                    changed = true;
                    break;
                }
            }
            if (changed) affected++;
        }
        if (affected > 0) {
            substituted.push({
                token: b.token,
                role: b.role,
                css_var: b.css_var,
                value: b.value,
                elements_affected: affected
            });
        } else {
            inert.push({
                token: b.token,
                role: b.role,
                css_var: b.css_var,
                value: b.value,
                reason: 'no visible element on the page references this token'
            });
        }
    }

    const allVars = [];
    for (const b of colorBindings) {
        allVars.push(b.css_var, ...(b.alias_vars || []));
    }
    setProbeVars(allVars, 'rgb(1, 2, 3)');
    const allLow = els.map(snapElem);
    setProbeVars(allVars, 'rgb(252, 253, 254)');
    const allHigh = els.map(snapElem);
    probeEl.remove();

    const foreignMap = new Map();
    for (let i = 0; i < els.length; i++) {
        for (const [prop, val] of Object.entries(baselineSnap[i])) {
            if (allLow[i][prop] === val && allHigh[i][prop] === val) {
                const hex = toHex(val);
                const key = `${hex}|${prop}`;
                if (!foreignMap.has(key)) {
                    foreignMap.set(key, { color: hex, rgb: val, property: prop, selectors: [], count: 0 });
                }
                const entry = foreignMap.get(key);
                entry.count++;
                const s = selFor(els[i]);
                if (!entry.selectors.includes(s) && entry.selectors.length < 10) {
                    entry.selectors.push(s);
                }
            }
        }
    }
    const foreign = Array.from(foreignMap.values()).sort(
        (a, b) => a.color.localeCompare(b.color) || a.property.localeCompare(b.property)
    );
    return { substituted, inert, foreign };
}"""


def _design_capture():
    if str(DESIGN_BIN) not in sys.path:
        sys.path.insert(0, str(DESIGN_BIN))
    import design_capture  # noqa: PLC0415

    return design_capture


def _resolve_browser_and_host(browser_url: str | None = None) -> tuple[str, str]:
    chosen = (browser_url or os.environ.get("CHECKS_BROWSER") or "").strip()
    if not chosen:
        if Path("/.dockerenv").exists():
            chosen = DEFAULT_BROWSER_WORKER
        else:
            chosen = DEFAULT_BROWSER_HOST
    parsed = urllib.parse.urlparse(chosen)
    host = parsed.hostname or "127.0.0.1"
    site_host = os.environ.get("CHECKS_SITE_HOST", "").strip()
    if not site_host:
        site_host = "8.8.8.8" if host in ("127.0.0.1", "localhost") else host
    return chosen, site_host


def _hex_to_rgb(val: str) -> tuple[int, int, int] | None:
    m = re.match(r"^#([0-9a-fA-F]{6})$", val.strip())
    if not m:
        return None
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def measure_pixel_diff(img_a_path: Path, img_b_path: Path) -> dict[str, Any]:
    """Compare two PNG renders and return changed pixel ratio and mean channel distance."""
    _require_pillow()
    with Image.open(img_a_path) as raw_a, Image.open(img_b_path) as raw_b:
        a = raw_a.convert("RGB")
        b = raw_b.convert("RGB")
        if a.size != b.size:
            b = b.resize(a.size, Image.NEAREST)
        total_pixels = a.width * a.height
        if total_pixels == 0:
            return {"changed_pixels": 0, "total_pixels": 0, "changed_ratio": 0.0, "mean_rgb_distance": 0.0}
        diff_img = ImageChops.difference(a, b)
        r_ch, g_ch, b_ch = diff_img.split()
        max_ch = ImageChops.lighter(ImageChops.lighter(r_ch, g_ch), b_ch)
        hist = max_ch.histogram()
        changed = sum(hist[PIXEL_CHANNEL_EPSILON + 1 :])
        means = ImageStat.Stat(diff_img).mean
        mean_dist = math.sqrt(means[0] ** 2 + means[1] ** 2 + means[2] ** 2)

    return {
        "changed_pixels": int(changed),
        "total_pixels": int(total_pixels),
        "changed_ratio": round(changed / total_pixels, 6),
        "mean_rgb_distance": round(mean_dist, 4),
    }


def measure_pixel_shift_toward_tokens(
    before_png: Path,
    after_png: Path,
    bindings: list[TokenBinding],
) -> dict[str, Any]:
    """Sample rendered pixels before and after applying `bindings` and assert movement toward target colours."""
    _require_pillow()
    diff = measure_pixel_diff(before_png, after_png)
    target_rgbs: list[tuple[int, int, int]] = []
    for b in bindings:
        if b.role in ("paper", "paper-2", "surface", "accent", "ink"):
            rgb = _hex_to_rgb(b.value)
            if rgb is not None:
                target_rgbs.append(rgb)

    if not target_rgbs:
        return {**diff, "moved_toward_tokens": diff["changed_ratio"] > 0.0}

    with Image.open(before_png) as raw_pre, Image.open(after_png) as raw_post:
        pre = raw_pre.convert("RGB")
        post = raw_post.convert("RGB")
        if pre.size != post.size:
            post = post.resize(pre.size, Image.NEAREST)
        pre_bytes = pre.tobytes()
        post_bytes = post.tobytes()

    # Sample on a uniform stride (~4,000 samples) for fast, deterministic distance-to-palette measurement.
    total_px = len(pre_bytes) // 3
    stride = max(1, total_px // 4096) * 3
    pre_dist_sum = 0.0
    post_dist_sum = 0.0
    samples = 0
    for idx in range(0, len(pre_bytes), stride):
        r0, g0, b0 = pre_bytes[idx], pre_bytes[idx + 1], pre_bytes[idx + 2]
        r1, g1, b1 = post_bytes[idx], post_bytes[idx + 1], post_bytes[idx + 2]
        d_pre = min(math.sqrt((r0 - tr) ** 2 + (g0 - tg) ** 2 + (b0 - tb) ** 2) for tr, tg, tb in target_rgbs)
        d_post = min(math.sqrt((r1 - tr) ** 2 + (g1 - tg) ** 2 + (b1 - tb) ** 2) for tr, tg, tb in target_rgbs)
        pre_dist_sum += d_pre
        post_dist_sum += d_post
        samples += 1

    mean_pre = pre_dist_sum / max(1, samples)
    mean_post = post_dist_sum / max(1, samples)
    return {
        **diff,
        "mean_palette_distance_before": round(mean_pre, 4),
        "mean_palette_distance_after": round(mean_post, 4),
        "moved_toward_tokens": bool(diff["changed_ratio"] > 0.0 and mean_post <= mean_pre),
    }


def discover_screens(
    captures: str | Path | None,
    *,
    staging_dir: Path,
    brief_source: str | Path | dict[str, Any] | None = None,
    warnings_out: list[str] | None = None,
) -> tuple[Path, list[dict[str, str]], str]:
    """Return `(site_root, screens_list, surface_mode)` where each screen has `id` and `file`."""
    if captures is not None and str(captures).strip():
        cap_path = Path(captures)
        if cap_path.is_file() and cap_path.suffix.lower() in (".html", ".htm"):
            return cap_path.parent, [{"id": _kebab(cap_path.stem) or "screen", "file": cap_path.name}], "captured"
        if cap_path.is_dir():
            html_dir = cap_path / "captures" if (cap_path / "captures").is_dir() else cap_path
            manifest_file = html_dir / "manifest.json"
            if manifest_file.exists():
                try:
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    if not isinstance(manifest, dict):
                        raise ValueError(f"expected JSON object in manifest, got {type(manifest).__name__}")
                    screens_raw = manifest.get("screens")
                    if not isinstance(screens_raw, list):
                        raise ValueError("manifest missing 'screens' list")
                    screens = [
                        {"id": _kebab(str(s["id"])), "file": str(s["file"]).lstrip("/")}
                        for s in screens_raw
                        if isinstance(s, dict) and s.get("id") and s.get("file") and (html_dir / str(s["file"]).lstrip("/")).is_file()
                    ]
                    if screens:
                        return html_dir, screens, "captured"
                    raise ValueError("manifest 'screens' list matched no existing HTML files")
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                    reason = (
                        f"manifest discovery failed for {manifest_file} "
                        f"({exc.__class__.__name__}: {exc}); fell back to globbing *.html"
                    )
                    if warnings_out is not None:
                        warnings_out.append(reason)
                    print(f"warning: {reason}", file=sys.stderr)
            html_files = sorted(
                p for p in html_dir.iterdir() if p.is_file() and p.suffix.lower() in (".html", ".htm")
            )
            if html_files:
                return (
                    html_dir,
                    [{"id": _kebab(p.stem) or f"screen-{i}", "file": p.name} for i, p in enumerate(html_files)],
                    "captured",
                )

    # No-app / no-captures fallback: build the representative sample screen from the brief.
    sample_dir = staging_dir / "_sample_site"
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_html = build_sample_screen_html(brief_source)
    (sample_dir / "sample.html").write_text(sample_html, encoding="utf-8")
    return sample_dir, [{"id": "sample", "file": "sample.html"}], "sample"


def _aggregate_colour_reports(per_view_reports: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sub_by_role: dict[str, dict[str, Any]] = {}
    inert_by_role: dict[str, dict[str, Any]] = {}
    foreign_by_key: dict[str, dict[str, Any]] = {}

    for rep in per_view_reports:
        for s in rep.get("substituted", []):
            role = s["role"]
            if role not in sub_by_role:
                sub_by_role[role] = dict(s)
            else:
                sub_by_role[role]["elements_affected"] = max(
                    int(sub_by_role[role].get("elements_affected", 0)),
                    int(s.get("elements_affected", 0)),
                )
        for inr in rep.get("inert", []):
            role = inr["role"]
            if role not in inert_by_role:
                inert_by_role[role] = dict(inr)
        for f in rep.get("foreign", []):
            key = f"{f['color']}|{f['property']}"
            if key not in foreign_by_key:
                foreign_by_key[key] = {
                    "color": f["color"],
                    "rgb": f["rgb"],
                    "property": f["property"],
                    "selectors": list(f.get("selectors", [])),
                    "count": int(f.get("count", 0)),
                }
            else:
                entry = foreign_by_key[key]
                entry["count"] = max(entry["count"], int(f.get("count", 0)))
                for sel in f.get("selectors", []):
                    if sel not in entry["selectors"] and len(entry["selectors"]) < 10:
                        entry["selectors"].append(sel)

    # A token role substituted on at least one view is substituted; only roles inert across all views stay inert.
    final_inert = [v for k, v in inert_by_role.items() if k not in sub_by_role]
    return {
        "substituted": list(sub_by_role.values()),
        "inert": final_inert,
        "foreign": sorted(foreign_by_key.values(), key=lambda x: (x["color"], x["property"])),
    }


async def _render_all_async(
    *,
    site_root: Path,
    screens: list[dict[str, str]],
    directions: dict[str, dict[str, Any]],
    out_dir: Path,
    browser_url: str | None = None,
) -> dict[str, Any]:
    dc = _design_capture()
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.streamable_http import streamablehttp_client  # noqa: PLC0415

    resolved_browser, site_host = _resolve_browser_and_host(browser_url)
    base_url, srv = dc.serve(site_root.resolve(), site_host)

    baseline_dir = out_dir / "_baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    dir_ids = list(directions.keys())

    # Precompute bindings and override CSS for every direction x theme.
    dir_theme_bindings: dict[tuple[str, str], list[TokenBinding]] = {}
    dir_theme_css: dict[tuple[str, str], str] = {}
    for dir_id, tok_doc in directions.items():
        (out_dir / dir_id).mkdir(parents=True, exist_ok=True)
        for theme in THEMES:
            b_list = extract_theme_bindings(tok_doc, theme=theme)
            dir_theme_bindings[(dir_id, theme)] = b_list
            dir_theme_css[(dir_id, theme)] = build_override_css(b_list, theme=theme)

    baseline_reset_css = (
        "*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }"
    )

    per_view_probe: dict[tuple[str, str, str], dict[str, Any]] = {}
    render_paths: dict[tuple[str, str, str, int], Path] = {}
    baseline_paths: dict[tuple[str, str, int], Path] = {}

    try:
        async with streamablehttp_client(resolved_browser) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                for screen in screens:
                    sid = screen["id"]
                    page_url = f"{base_url}/{screen['file'].lstrip('/')}"
                    screen_plan = []
                    for theme in THEMES:
                        t_dirs = [
                            {
                                "id": d_id,
                                "css": dir_theme_css[(d_id, theme)],
                                "bindings": [b.to_dict() for b in dir_theme_bindings[(d_id, theme)]],
                            }
                            for d_id in dir_ids
                        ]
                        screen_plan.append({"theme": theme, "dirs": t_dirs})

                    widths_list = [{"width": w, "height": h} for w, h in WIDTHS.items()]
                    js_code = f"""async (page) => {{
                        const ctx = await page.context().browser().newContext({{
                            viewport: {{ width: 1440, height: 900 }},
                            colorScheme: 'light',
                            deviceScaleFactor: 1,
                            reducedMotion: 'reduce'
                        }});
                        const p = await ctx.newPage();
                        await p.route('**/favicon.ico', (route) => route.fulfill({{ status: 200, contentType: 'image/png', body: '' }}));
                        try {{
                            await p.goto({json.dumps(page_url)}, {{ waitUntil: 'load', timeout: 20000 }});
                            await p.evaluate((resetCss) => {{
                                let rst = document.getElementById('__foundation_reset__');
                                if (!rst) {{
                                    rst = document.createElement('style');
                                    rst.id = '__foundation_reset__';
                                    document.head.appendChild(rst);
                                }}
                                rst.textContent = resetCss;
                                return document.fonts ? document.fonts.ready.then(() => true) : true;
                            }}, {json.dumps(baseline_reset_css)});

                            const probeFn = {PROBE_IN_PAGE_JS};
                            const plan = {json.dumps(screen_plan)};
                            const widths = {json.dumps(widths_list)};
                            const baselines = {{}};
                            const shots = {{}};
                            const probes = {{}};

                            for (const tItem of plan) {{
                                const theme = tItem.theme;
                                await p.emulateMedia({{ colorScheme: theme, reducedMotion: 'reduce' }});
                                await p.evaluate((th) => {{
                                    document.documentElement.setAttribute('data-theme', th);
                                    if (document.body) document.body.setAttribute('data-theme', th);
                                }}, theme);

                                for (const wItem of widths) {{
                                    const w = wItem.width, h = wItem.height;
                                    await p.setViewportSize({{ width: w, height: h }});
                                    await p.evaluate(() => {{
                                        const old = document.getElementById('foundation-token-override');
                                        if (old) old.remove();
                                    }});
                                    const baseBuf = await p.screenshot({{ fullPage: false, animations: 'disabled' }});
                                    baselines[`${{theme}}-${{w}}`] = baseBuf.toString('base64');

                                    for (const d of tItem.dirs) {{
                                        await p.evaluate((cssText) => {{
                                            let el = document.getElementById('foundation-token-override');
                                            if (!el) {{
                                                el = document.createElement('style');
                                                el.id = 'foundation-token-override';
                                                document.head.appendChild(el);
                                            }}
                                            el.textContent = cssText;
                                        }}, d.css);
                                        if (w === 1440) {{
                                            probes[`${{d.id}}:${{theme}}`] = await p.evaluate(probeFn, d.bindings);
                                        }}
                                        const shotBuf = await p.screenshot({{ fullPage: false, animations: 'disabled' }});
                                        shots[`${{d.id}}:${{theme}}:${{w}}`] = shotBuf.toString('base64');
                                    }}
                                }}
                            }}
                            return {{ baselines, shots, probes }};
                        }} finally {{
                            await ctx.close();
                        }}
                    }}"""
                    res = await dc.run(s, js_code) or {}
                    baselines_map = res.get("baselines") or {}
                    shots_map = res.get("shots") or {}
                    probes_map = res.get("probes") or {}
                    for theme in THEMES:
                        for width in WIDTHS:
                            base_png = baseline_dir / f"{sid}-{theme}-{width}.png"
                            base_png.write_bytes(base64.b64decode(baselines_map[f"{theme}-{width}"]))
                            baseline_paths[(sid, theme, width)] = base_png
                            for d_id in dir_ids:
                                out_png = out_dir / d_id / f"{sid}-{theme}-{width}.png"
                                out_png.write_bytes(base64.b64decode(shots_map[f"{d_id}:{theme}:{width}"]))
                                render_paths[(d_id, sid, theme, width)] = out_png
                        for d_id in dir_ids:
                            pkey = f"{d_id}:{theme}"
                            if pkey in probes_map:
                                per_view_probe[(d_id, sid, theme)] = probes_map[pkey]
    finally:
        srv.shutdown()

    return {
        "dir_theme_bindings": dir_theme_bindings,
        "per_view_probe": per_view_probe,
        "render_paths": render_paths,
        "baseline_paths": baseline_paths,
    }


def _build_sheets(
    *,
    out_dir: Path,
    dir_ids: list[str],
    screens: list[dict[str, str]],
    render_paths: dict[tuple[str, str, str, int], Path],
    baseline_paths: dict[tuple[str, str, int], Path],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Build per-direction sheets and side-by-side comparison sheets via `existing_sheet.build`."""
    _require_pillow()
    per_dir_sheets: dict[str, dict[str, Any]] = {}
    for d_id in dir_ids:
        d_out = out_dir / d_id
        d_sheets: dict[str, Any] = {}
        for width in WIDTHS:
            w_label = "phone" if width == 390 else "desktop"
            tiles_all_themes: list[tuple[str, Path]] = []
            for s in screens:
                sid = s["id"]
                for theme in THEMES:
                    tiles_all_themes.append(
                        (f"{sid}:{theme}:{width}", render_paths[(d_id, sid, theme, width)])
                    )
            sheet_path = d_out / f"sheet-{w_label}.png"
            meta = existing_sheet.build(tiles_all_themes, sheet_path)
            d_sheets[w_label] = {**meta, "path": f"{d_id}/{sheet_path.name}"}
        per_dir_sheets[d_id] = d_sheets

    sbs_dir = out_dir / "side-by-side"
    sbs_dir.mkdir(parents=True, exist_ok=True)
    sbs_sheets: dict[str, Any] = {"by_screen": {}, "by_theme_width": {}}

    # When 2+ directions are given, compare directions side-by-side; when 1 direction is given,
    # compare baseline vs the direction so single-direction runs still produce a valid comparison sheet.
    compare_ids = dir_ids if len(dir_ids) >= 2 else ["baseline", *dir_ids]

    def _tile_for(comp_id: str, sid: str, theme: str, width: int) -> tuple[str, Path]:
        if comp_id == "baseline":
            return f"{sid}:baseline:{theme}:{width}", baseline_paths[(sid, theme, width)]
        return f"{sid}:{comp_id}:{theme}:{width}", render_paths[(comp_id, sid, theme, width)]

    for s in screens:
        sid = s["id"]
        sbs_sheets["by_screen"][sid] = {}
        for theme in THEMES:
            for width in WIDTHS:
                tiles = [_tile_for(cid, sid, theme, width) for cid in compare_ids]
                out_p = sbs_dir / f"side-by-side-{sid}-{theme}-{width}.png"
                meta = existing_sheet.build(tiles, out_p)
                sbs_sheets["by_screen"][sid][f"{theme}-{width}"] = {
                    **meta,
                    "path": f"side-by-side/{out_p.name}",
                }

    for theme in THEMES:
        for width in WIDTHS:
            out_p = sbs_dir / f"side-by-side-{theme}-{width}.png"
            if len(screens) == 1:
                only_sid = screens[0]["id"]
                src_entry = sbs_sheets["by_screen"][only_sid][f"{theme}-{width}"]
                shutil.copyfile(sbs_dir / src_entry["file"], out_p)
                sbs_sheets["by_theme_width"][f"{theme}-{width}"] = {
                    **src_entry,
                    "file": out_p.name,
                    "path": f"side-by-side/{out_p.name}",
                }
            else:
                tiles = [
                    _tile_for(cid, s["id"], theme, width)
                    for s in screens
                    for cid in compare_ids
                ]
                meta = existing_sheet.build(tiles, out_p)
                sbs_sheets["by_theme_width"][f"{theme}-{width}"] = {
                    **meta,
                    "path": f"side-by-side/{out_p.name}",
                }

    return per_dir_sheets, sbs_sheets


def _expand_token_source(
    source: str | Path | dict[str, Any],
    default_label: str,
) -> dict[str, dict[str, Any]]:
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.is_file():
            raise PreviewError(f"tokens file does not exist: {p}")
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PreviewError(f"tokens file is not valid JSON ({p}): {exc}") from exc
    elif isinstance(source, dict):
        raw = source
    else:
        raise PreviewError(f"unsupported token source: {source!r}")

    if not isinstance(raw, dict):
        raise PreviewError("tokens root must be a JSON object")

    if "colour" in raw or "color" in raw:
        return {default_label: load_tokens(raw)}
    if "directions" in raw and isinstance(raw["directions"], dict) and raw["directions"]:
        out: dict[str, dict[str, Any]] = {}
        for k, v in raw["directions"].items():
            out[_kebab(str(k)) or f"direction-{len(out) + 1}"] = load_tokens(v)
        return out
    if raw and all(isinstance(v, dict) and ("colour" in v or "color" in v) for v in raw.values()):
        out = {}
        for k, v in raw.items():
            out[_kebab(str(k)) or f"direction-{len(out) + 1}"] = load_tokens(v)
        return out
    return {default_label: load_tokens(raw)}


def render_preview(
    *,
    tokens: dict[str, str | Path | dict[str, Any]] | list[str | Path | dict[str, Any]] | str | Path,
    out_dir: str | Path,
    captures: str | Path | None = None,
    captures_dir: str | Path | None = None,
    brief_source: str | Path | dict[str, Any] | None = None,
    brief_path: str | Path | dict[str, Any] | None = None,
    browser_url: str | None = None,
) -> dict[str, Any]:
    """Re-skin captured screens (or no-app sample screen) across themes and widths and write sheets + report."""
    import asyncio  # noqa: PLC0415

    if captures is None and captures_dir is not None:
        captures = captures_dir
    if brief_source is None and brief_path is not None:
        brief_source = brief_path

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Normalize `tokens` into `{direction_id: tokens_doc}`.
    directions: dict[str, dict[str, Any]] = {}
    if isinstance(tokens, dict):
        directions.update(_expand_token_source(tokens, "direction-1"))
    elif isinstance(tokens, (str, Path)):
        p = Path(tokens)
        d_id = _kebab(p.stem if p.stem != "tokens" else (p.parent.name or "direction-1")) or "direction-1"
        directions.update(_expand_token_source(p, d_id))
    elif isinstance(tokens, list):
        for idx, item in enumerate(tokens, start=1):
            if isinstance(item, (str, Path)):
                raw_s = str(item)
                if "=" in raw_s and not Path(raw_s).exists():
                    label, path_part = raw_s.split("=", 1)
                    d_id = _kebab(label) or f"direction-{idx}"
                    expanded = _expand_token_source(Path(path_part), d_id)
                else:
                    p = Path(raw_s)
                    stem = p.stem if p.stem != "tokens" else (p.parent.name or f"direction-{idx}")
                    d_id = _kebab(stem) or f"direction-{idx}"
                    expanded = _expand_token_source(p, d_id)
                for k, v in expanded.items():
                    key = k if k not in directions else f"{k}-{idx}"
                    directions[key] = v
            elif isinstance(item, dict):
                for k, v in _expand_token_source(item, f"direction-{idx}").items():
                    key = k if k not in directions else f"{k}-{idx}"
                    directions[key] = v
            else:
                raise PreviewError(f"unsupported token item: {item!r}")
    else:
        raise PreviewError("tokens must be a path, dict, or list of paths/dicts")

    if not directions:
        raise PreviewError("at least one token set is required")

    discovery_warnings: list[str] = []
    screen_root, screens, surface_mode = discover_screens(
        captures,
        staging_dir=out_path,
        brief_source=brief_source,
        warnings_out=discovery_warnings,
    )

    try:
        raw_res = asyncio.run(
            _render_all_async(
                site_root=screen_root,
                screens=screens,
                directions=directions,
                out_dir=out_path,
                browser_url=browser_url,
            )
        )
    except PreviewError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PreviewError(f"preview browser render failed: {exc.__class__.__name__}: {exc}") from exc

    dir_theme_bindings = raw_res["dir_theme_bindings"]
    per_view_probe = raw_res["per_view_probe"]
    render_paths = raw_res["render_paths"]
    baseline_paths = raw_res["baseline_paths"]
    dir_ids = list(directions.keys())

    per_dir_sheets, sbs_sheets = _build_sheets(
        out_dir=out_path,
        dir_ids=dir_ids,
        screens=screens,
        render_paths=render_paths,
        baseline_paths=baseline_paths,
    )

    directions_report: dict[str, Any] = {}
    for d_id in dir_ids:
        views_for_dir: dict[str, Any] = {}
        view_probes: list[dict[str, Any]] = []
        renders_list: list[dict[str, Any]] = []
        renders_map: dict[str, str] = {}
        pixel_shifts: dict[str, Any] = {}

        for s in screens:
            sid = s["id"]
            for theme in THEMES:
                probe = per_view_probe.get((d_id, sid, theme), {"substituted": [], "inert": [], "foreign": []})
                view_probes.append(probe)
                views_for_dir[f"{sid}:{theme}"] = probe
                for width in WIDTHS:
                    view_key = f"{sid}-{theme}-{width}"
                    png_path = render_paths[(d_id, sid, theme, width)]
                    rel_p = f"{d_id}/{png_path.name}"
                    renders_map[view_key] = rel_p
                    base_png = baseline_paths[(sid, theme, width)]
                    shift = measure_pixel_shift_toward_tokens(
                        base_png,
                        png_path,
                        dir_theme_bindings[(d_id, theme)],
                    )
                    pixel_shifts[view_key] = shift
                    renders_list.append(
                        {
                            "screen": sid,
                            "theme": theme,
                            "width": width,
                            "path": str(png_path),
                            "rel_path": rel_p,
                            "pixel_shift": shift,
                        }
                    )

        agg = _aggregate_colour_reports(view_probes)
        directions_report[d_id] = {
            "renders": renders_list,
            "renders_by_key": renders_map,
            "sheets": per_dir_sheets[d_id],
            "substituted": agg["substituted"],
            "inert": agg["inert"],
            "foreign": agg["foreign"],
            "by_view": views_for_dir,
            "pixel_shift_from_baseline": pixel_shifts,
        }

    compare_ids = dir_ids if len(dir_ids) >= 2 else ["baseline", *dir_ids]
    sbs_flat_list: list[dict[str, Any]] = []
    for s in screens:
        sid = s["id"]
        for theme in THEMES:
            for width in WIDTHS:
                meta = sbs_sheets["by_screen"][sid][f"{theme}-{width}"]
                sbs_flat_list.append(
                    {
                        "screen": sid,
                        "theme": theme,
                        "width": width,
                        "directions": compare_ids,
                        "path": str(out_path / meta["path"]),
                        "rel_path": meta["path"],
                        "sheet": meta,
                    }
                )

    pairwise_diff: dict[str, Any] = {}
    if len(dir_ids) >= 2:
        for i in range(len(dir_ids)):
            for j in range(i + 1, len(dir_ids)):
                da, db = dir_ids[i], dir_ids[j]
                for s in screens:
                    sid = s["id"]
                    for theme in THEMES:
                        for width in WIDTHS:
                            vk = f"{da}_vs_{db}:{sid}:{theme}:{width}"
                            diff = measure_pixel_diff(
                                render_paths[(da, sid, theme, width)],
                                render_paths[(db, sid, theme, width)],
                            )
                            pairwise_diff[vk] = {
                                "direction_a": da,
                                "direction_b": db,
                                "screen": sid,
                                "theme": theme,
                                "width": width,
                                **diff,
                            }
                            if diff["changed_ratio"] < MIN_PAIRWISE_DIFF_RATIO:
                                raise PreviewError(
                                    f"pairwise pixel diff below floor ({diff['changed_ratio']} < {MIN_PAIRWISE_DIFF_RATIO}) "
                                    f"for {da} vs {db} on {sid} ({theme}@{width})"
                                )

    report: dict[str, Any] = {
        "surface_mode": surface_mode,
        "fallback_used": surface_mode == "sample",
        "screens": [s["id"] for s in screens],
        "themes": list(THEMES),
        "widths": list(WIDTHS.keys()),
        "directions": directions_report,
        "side_by_side": sbs_sheets,
        "side_by_side_sheets": sbs_flat_list,
        "pairwise_diff": pairwise_diff,
    }
    if discovery_warnings:
        report["manifest_fallback_reason"] = (
            discovery_warnings[0] if len(discovery_warnings) == 1 else "; ".join(discovery_warnings)
        )
        report["warnings"] = list(discovery_warnings)
    if len(dir_ids) == 1:
        sole = directions_report[dir_ids[0]]
        report["substituted"] = sole["substituted"]
        report["inert"] = sole["inert"]
        report["foreign"] = sole["foreign"]

    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (out_path / "report.json").write_text(serialized, encoding="utf-8")
    (out_path / "preview-report.json").write_text(serialized, encoding="utf-8")
    return report


def parse_tokens_cli_args(tokens_args: list[str]) -> list[str]:
    """Flatten repeated or comma-separated `--tokens` CLI values."""
    items: list[str] = []
    for raw in tokens_args:
        for part in str(raw).split(","):
            cleaned = part.strip()
            if cleaned:
                items.append(cleaned)
    if not items:
        raise PreviewError("preview requires at least one --tokens path")
    return items


def run_cli(
    *,
    tokens_args: list[str],
    out_dir: str | Path,
    captures: str | Path | None = None,
    brief_path: str | Path | None = None,
    browser_url: str | None = None,
) -> dict[str, Any]:
    token_items = parse_tokens_cli_args(tokens_args)
    return render_preview(
        tokens=token_items,
        out_dir=out_dir,
        captures=captures,
        brief_source=brief_path,
        browser_url=browser_url,
    )





