"""Stage 5 (`build`) of `design_foundation_v1`: compile chosen direction to `tokens.json` and `DESIGN.md`.

Division of labour:
- `compile_chosen_tokens` compiles the chosen direction's discrete choices (`anchor_hue_deg`,
  `chroma_intent`, `neutral_temp`, `type_family`) through `directions.build_direction_tokens` -> `color.py`
  into DTCG `04-build/tokens.json`. The model never writes a colour value, a size, a ratio, or any number.
- `design_foundation_build_v1` writes the structured prose (`04-build/draft.json`): `users`, `premise`,
  `why`, `how_to_use`, `what_not_to_do`, and `evidence` per claim.
- `build_check` deterministically enforces the seven build rules (`BUILD_RULE_ORDER`):
  1. `build.tokens_schema`          `04-build/tokens.json` validates against the closed `TOKENS_SCHEMA`.
  2. `build.proof_gate`             `04-build/tokens.json` passes `proof.evaluate_tokens` (`proof.py`).
  3. `build.tokens_from_color`      `04-build/tokens.json` is byte-identical to `compile_chosen_tokens`
                                    output from the chosen direction (`color.py`).
  4. `build.design_md_contract`     `04-build/DESIGN.md` passes `design_files.parse_design_md` and
                                    `contracts.validate_design_md`, names only the chosen direction,
                                    carries no rejected direction names, and does not hedge or offer
                                    alternative directions.
  5. `build.prose_tokens_agreement` Every token referenced in `DESIGN.md` prose exists as a leaf token in
                                    `04-build/tokens.json`, `how_to_use` and `what_not_to_do` cite real
                                    token paths, and palette/typography descriptors in prose agree with the
                                    chosen direction's `neutral_temp`, `chroma_intent`, and `type_family`.
  6. `build.no_raw_colour_literal`  `DESIGN.md` prose contains zero raw colour literals (`#hex`, `rgb(...)`,
                                    `oklch(...)`, `hsl(...)`) and zero raw numeric sizing/ratio values
                                    outside token paths.
  7. `build.brief_evidence`         Every claim section in `draft.json` carries a valid citation into
                                    `01-brief/brief.json` and uses domain vocabulary grounded in the brief.
- `build_finish` verifies `verdict == "ok"` and persists `04-build/tokens.json`, `04-build/DESIGN.md`,
  and `04-build/build.json`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import design_files

from . import contracts, directions, proof
from .contracts import (
    BUILD_CHECK_RULE_IDS,
    BUILD_CLAIM_KEYS,
    EXT,
    FORMAT,
    TOKEN_PARTS,
    ContractError,
)
from .workspace import Workspace


class BuildError(ContractError):
    """Raised when Stage 5 (`build`) fails a deterministic check or input invariant."""


BUILD_RULE_ORDER: tuple[str, ...] = BUILD_CHECK_RULE_IDS

_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")
_TOKEN_PATH_PREFIXES = ("colour.", "color.", "type.", "spacing.", "radius.", "elevation.", "motion.")
_INLINE_TOKEN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:colour|color|type|spacing|radius|elevation|motion)\.[A-Za-z0-9_.{}-]+)"
)
_BARE_COLOUR_RE = re.compile(
    r"#[0-9a-fA-F]{3,8}\b"
    r"|\b(?:oklch|oklab|rgb|rgba|hsl|hsla|color|lab|lch)\s*\([^)]*\)",
    re.IGNORECASE,
)
_PROSE_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?:"
    r"\d+(?:\.\d+)?\s*(?:px|rem|em|pt|ms|s|deg|%)\b"
    r"|\d+(?:\.\d+)?\s*:\s*1\b"
    r")",
    re.IGNORECASE,
)
_HEDGE_RE = re.compile(
    r"\b(?:"
    r"alternatively|"
    r"alternative\s+direction|"
    r"either\s+direction|"
    r"or\s+switch\s+to|"
    r"could\s+instead\s+use|"
    r"second\s+option|"
    r"fallback\s+direction"
    r")\b",
    re.IGNORECASE,
)

_NEUTRAL_OPPOSITES: dict[str, tuple[str, ...]] = {
    "warm": (
        "cool slate",
        "cool neutral",
        "cool-toned neutral",
        "icy slate",
        "ice-blue neutral",
        "steely blue-grey",
        "blue-grey canvas",
        "cool steel",
    ),
    "cool": (
        "warm stone",
        "warm ivory",
        "warm paper",
        "warm cream",
        "warm sand",
        "warm neutral",
        "warm-toned neutral",
        "parchment canvas",
    ),
    "true": (
        "warm ivory",
        "warm parchment",
        "warm cream",
        "icy blue-grey",
        "cool slate canvas",
    ),
}

_CHROMA_OPPOSITES: dict[str, tuple[str, ...]] = {
    "restrained": (
        "high-chroma",
        "high chroma",
        "vivid neon",
        "saturated signal",
        "electric accent",
        "hyper-saturated",
        "vibrant neon",
    ),
    "muted": (
        "high-chroma",
        "high chroma",
        "vivid neon",
        "saturated signal",
        "electric accent",
        "hyper-saturated",
        "vibrant neon",
    ),
    "balanced": (
        "high-chroma",
        "high chroma",
        "saturated signal",
        "monochrome-only",
        "zero-chroma",
        "vivid neon",
        "hyper-saturated",
        "electric neon",
    ),
    "crisp": (
        "muted pastel",
        "desaturated pastel",
        "washed-out accent",
        "low-chroma muted",
    ),
}

_STOPWORDS: frozenset[str] = frozenset(
    {
        "about", "above", "across", "after", "against", "all", "along", "also", "always",
        "among", "and", "any", "apply", "are", "around", "avoid", "back", "background",
        "base", "because", "been", "before", "being", "below", "between", "both", "body",
        "border", "borders", "button", "buttons", "can", "canvas", "card", "cards",
        "choice", "chosen", "clean", "clear", "color", "colour", "colours", "colors",
        "component", "components", "consistent", "consistently", "container", "containers",
        "contrast", "control", "controls", "copy", "core", "dark", "data", "default",
        "design", "direction", "display", "do", "does", "done", "dont", "down", "draft",
        "each", "elevation", "element", "elements", "emphasis", "ensure", "every",
        "existing", "family", "fast", "feel", "field", "fields", "file", "files", "fill",
        "fills", "first", "focus", "font", "fonts", "for", "foreground", "form", "forms",
        "from", "full", "given", "good", "group", "groups", "have", "header", "headers",
        "heading", "headings", "hierarchy", "high", "hold", "how", "hue", "icon", "icons",
        "info", "information", "ink", "inline", "input", "inputs", "instead", "intent",
        "interface", "into", "is", "it", "its", "keep", "key", "label", "labels", "large",
        "layout", "layouts", "lead", "left", "level", "levels", "light", "line", "lines",
        "link", "links", "list", "lists", "live", "main", "make", "makes", "making",
        "modal", "modals", "mode", "mono", "monospace", "more", "most", "motion", "must",
        "muted", "name", "named", "nav", "navigation", "neutral", "neutrals", "never",
        "new", "next", "no", "non", "normal", "not", "note", "notes", "number", "numbers",
        "numeric", "numerical", "off", "on", "one", "only", "open", "or", "other", "our",
        "out", "over", "overlay", "overlays", "page", "pages", "pair", "pairs", "palette",
        "panel", "panels", "paper", "part", "parts", "pass", "path", "paths", "pattern",
        "patterns", "per", "place", "plain", "point", "points", "prefer", "premise",
        "preserve", "primary", "product", "prose", "provide", "provides", "radius",
        "raised", "ramp", "ramps", "ratio", "read", "readable", "reading", "reference",
        "references", "regular", "remain", "remains", "render", "reserve", "reserved",
        "restrained", "right", "risk", "role", "roles", "row", "rows", "rule", "rules",
        "run", "running", "same", "sans", "scale", "scales", "screen", "screens",
        "secondary", "section", "sections", "see", "select", "selected", "semantic",
        "separate", "separation", "serif", "set", "sets", "setting", "shade", "shades",
        "shadow", "shadows", "shape", "shapes", "shared", "should", "show", "shows",
        "side", "signal", "signals", "single", "size", "sizes", "small", "solid", "some",
        "source", "space", "spacing", "span", "specific", "state", "states", "status",
        "stay", "stays", "step", "steps", "still", "strict", "strictly", "strong",
        "structure", "style", "styles", "subtle", "support", "supports", "surface",
        "surfaces", "system", "table", "tables", "tabular", "tag", "tags", "target",
        "targets", "temp", "temperature", "text", "than", "that", "the", "their", "them",
        "theme", "themes", "then", "there", "these", "they", "this", "those", "three",
        "through", "throughout", "tight", "title", "titles", "to", "token", "tokens",
        "tone", "tones", "too", "top", "trace", "traced", "transition", "transitions",
        "true", "trust", "two", "type", "typeface", "typefaces", "typography", "ui",
        "under", "unit", "units", "unless", "up", "update", "updated", "use", "used",
        "user", "users", "using", "valid", "value", "values", "var", "variant", "variants",
        "view", "views", "visual", "vivid", "warm", "warn", "warning", "warnings", "way",
        "weight", "weights", "well", "what", "when", "where", "which", "while", "white",
        "who", "why", "will", "with", "within", "without", "word", "words", "work",
        "workflow", "working", "works", "write", "written", "your",
    }
)


def _problem(rule: str, location: str, message: str) -> dict[str, str]:
    return {"rule": rule, "location": location, "message": message}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(raw)


def _extract_tokens_date(tok_doc: Any) -> str | None:
    if not isinstance(tok_doc, dict):
        return None
    colour_part = tok_doc.get("colour")
    if not isinstance(colour_part, dict):
        return None
    ext = colour_part.get("$extensions")
    if not isinstance(ext, dict):
        return None
    meta = ext.get(EXT)
    if not isinstance(meta, dict):
        return None
    d = meta.get("date")
    if isinstance(d, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return d
    return None


def _resolve_build_date(ws: Workspace, chosen: dict[str, Any]) -> str:
    chosen_id = str(chosen["id"])
    for rel in (f"02-directions/{chosen_id}/tokens.json", "04-build/tokens.json"):
        p = ws.path / rel
        if p.is_file():
            try:
                tok_doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BuildError(f"cannot read tokens file {p}: {exc}") from exc
            d = _extract_tokens_date(tok_doc)
            if d:
                return d
    return design_files.today()


def _collect_token_leaf_paths(node: Any, prefix: str = "") -> list[str]:
    if not isinstance(node, dict):
        return []
    if "$value" in node:
        return [prefix] if prefix else []
    paths: list[str] = []
    for k, v in node.items():
        if str(k).startswith("$"):
            continue
        child = f"{prefix}.{k}" if prefix else str(k)
        paths.extend(_collect_token_leaf_paths(v, child))
    return sorted(paths)


def _load_inputs(ws: Workspace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    brief_doc = ws.read_json("01-brief/brief.json")
    directions_doc = ws.read_json("02-directions/directions.json")
    gate_doc = ws.read_json("02-directions/gate_direction.json")
    choice = str(gate_doc.get("choice") or "").strip()
    if not choice:
        raise BuildError("02-directions/gate_direction.json has empty 'choice'")
    chosen: dict[str, Any] | None = None
    for item in directions_doc.get("directions", []):
        if isinstance(item, dict) and item.get("id") == choice:
            chosen = item
            break
    if chosen is None:
        available = [d.get("id") for d in directions_doc.get("directions", []) if isinstance(d, dict)]
        raise BuildError(
            f"02-directions/gate_direction.json choice {choice!r} not found in directions.json (available: {available})"
        )
    return brief_doc, directions_doc, gate_doc, chosen


def compile_chosen_tokens(
    product: str,
    chosen_direction: dict[str, Any],
    *,
    date: str | None = None,
) -> dict[str, Any]:
    """Deterministically compile `04-build/tokens.json` from the chosen direction via `color.py`."""
    if not isinstance(chosen_direction, dict):
        raise BuildError("chosen_direction must be a dict")
    tokens_doc = directions.build_direction_tokens(product, chosen_direction, date=date)
    contracts.validate_tokens(tokens_doc, step="build", file="04-build/tokens.json")
    return tokens_doc


def _canonical_tokens_bytes(tokens_doc: dict[str, Any]) -> bytes:
    return (json.dumps(tokens_doc, indent=2) + "\n").encode("utf-8")


def render_design_md(
    *,
    product: str,
    draft: dict[str, Any],
    chosen_direction: dict[str, Any],
    gate_direction: dict[str, Any] | None = None,
    status: str = "draft",
    approved_by: str | None = None,
    owner_words: str | None = None,
    source: str | None = None,
    date: str | None = None,
) -> str:
    """Deterministically render `04-build/DESIGN.md` from `draft` prose + `chosen_direction` contract."""
    stamp = date or design_files.today()
    dir_id = str(chosen_direction["id"])
    dir_name = str(chosen_direction["name"])
    premise = str(draft["premise"]).strip()
    neutral_temp = str(chosen_direction["neutral_temp"])
    chroma_intent = str(chosen_direction["chroma_intent"])
    type_family = str(chosen_direction["type_family"])

    users_bullets = "\n".join(f"- {str(line).strip()}" for line in draft["users"])
    why_bullets = "\n".join(f"- {str(line).strip()}" for line in draft["why"])
    how_bullets = "\n".join(f"- {str(line).strip()}" for line in draft["how_to_use"])
    not_bullets = "\n".join(f"- {str(line).strip()}" for line in draft["what_not_to_do"])

    status_line = (
        f"Status: approved by {approved_by} on {stamp}"
        if status == "approved" and approved_by
        else f"Status: {status}"
    )
    mirror_lines = "\n".join(
        (
            f"- {part}: approved by {approved_by} on {stamp}"
            if status == "approved" and approved_by
            else f"- {part}: {status}"
        )
        for part in TOKEN_PARTS
    )

    approvals_lines: list[str] = []
    if status == "approved" and approved_by:
        words = str(owner_words or "Approved foundation direction and tokens.").strip().replace('"', "'")
        src = str(source or "gate_final").strip()
        for part in ("users", "direction", *TOKEN_PARTS):
            if approved_by == "owner":
                approvals_lines.append(f'- {part}: owner on {stamp}: "{words}" ({src})')
            else:
                approvals_lines.append(f"- {part}: {approved_by} on {stamp}: {words}")
    approvals_tail = ("\n" + "\n".join(approvals_lines) + "\n") if approvals_lines else "\n"

    return (
        f"# {product} — Design system\n\n"
        f"Product: {product}\n"
        f"Updated: {stamp}\n"
        f"Format: {FORMAT}\n\n"
        f"## Users\n"
        f"{status_line}\n\n"
        f"### Primary users\n"
        f"{users_bullets}\n\n"
        f"## Direction\n"
        f"{status_line}\n\n"
        f"### Named direction\n"
        f"**{dir_name}** (`{dir_id}`) — {premise}\n"
        f"Palette profile: {neutral_temp} neutrals, {chroma_intent} accent chroma.\n"
        f"Typography profile: {type_family}.\n\n"
        f"### Why\n"
        f"{why_bullets}\n\n"
        f"### How to use\n"
        f"{how_bullets}\n\n"
        f"### What not to do\n"
        f"{not_bullets}\n\n"
        f"## Tokens\n"
        f"Values live in tokens.json (DTCG 2025.10); each part's status:\n"
        f"{mirror_lines}\n\n"
        f"## Logo\n"
        f"Status: missing\n\n"
        f"## Library\n"
        f"Status: missing\n\n"
        f"## Approvals{approvals_tail}"
    )


def promote_design_md_to_approved(
    raw_md: str,
    *,
    approved_by: str,
    date: str | None = None,
    owner_words: str | None = None,
    source: str | None = None,
) -> str:
    """Promote a Stage 5 draft DESIGN.md to approved status while preserving its prose."""
    stamp = date if (date and design_files._valid_date(date)) else design_files.today()
    out_lines: list[str] = []
    in_tokens = False
    in_approvals = False
    words = str(owner_words or "Approved foundation direction and tokens.").strip().replace("\n", " ").replace('"', "'")
    src = str(source or "gate_final").strip()

    for line in raw_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("Updated:"):
            out_lines.append(f"Updated: {stamp}")
            continue
        if stripped.startswith("## "):
            in_tokens = stripped == "## Tokens"
            in_approvals = stripped == "## Approvals"
            out_lines.append(line)
            continue
        if stripped == "Status: draft" and not in_tokens:
            out_lines.append(f"Status: approved by {approved_by} on {stamp}")
            continue
        if in_tokens and stripped.startswith("- "):
            for part in TOKEN_PARTS:
                if stripped.startswith(f"- {part}:"):
                    out_lines.append(f"- {part}: approved by {approved_by} on {stamp}")
                    break
            else:
                out_lines.append(line)
            continue
        if in_approvals:
            continue
        out_lines.append(line)

    for part in ("users", "direction", *TOKEN_PARTS):
        if approved_by == "owner":
            out_lines.append(f'- {part}: owner on {stamp}: "{words}" ({src})')
        else:
            out_lines.append(f"- {part}: {approved_by} on {stamp}: {words}")
    return "\n".join(out_lines).rstrip() + "\n"


def _format_build_task(
    brief_doc: dict[str, Any],
    chosen: dict[str, Any],
    gate_doc: dict[str, Any],
    tokens_doc: dict[str, Any],
) -> str:
    product = str(brief_doc["product"])
    numbered = directions.brief_lines(brief_doc)
    numbered_block = "\n".join(f"{lid}: {text}" for lid, text in numbered)
    leaf_paths = _collect_token_leaf_paths(tokens_doc)
    sample_leafs = [
        p
        for p in leaf_paths
        if p.startswith(("colour.paper", "colour.surface", "colour.ink", "colour.muted", "colour.accent"))
        or p.startswith(("colour.light.surface.", "colour.dark.surface."))
        or p.startswith(("colour.light.text.", "colour.dark.text."))
        or p.startswith(("colour.light.border.", "colour.dark.border."))
        or p.startswith(("colour.light.semantic.", "colour.dark.semantic."))
        or p.startswith(("type.", "spacing.", "radius.", "elevation.", "motion."))
    ]
    token_list_block = "\n".join(f"- `{p}`" for p in sample_leafs)

    return (
        f"# Stage 5 (`build`) — Write `DESIGN.md` prose for `{product}`\n\n"
        f"## Chosen direction at Gate 1 (write ONLY this direction)\n"
        f"- `product`: `{product}`\n"
        f"- `direction_id`: `{chosen['id']}`\n"
        f"- `direction_name`: `{chosen['name']}`\n"
        f"- `neutral_temp`: `{chosen['neutral_temp']}`\n"
        f"- `chroma_intent`: `{chosen['chroma_intent']}`\n"
        f"- `type_family`: `{chosen['type_family']}`\n"
        f"- Stage 2 premise: {chosen['premise']}\n"
        f"- Gate 1 rationale (`{gate_doc.get('decided_by')}`): {gate_doc.get('reason')}\n\n"
        f"## Numbered product brief lines (cite verbatim as `L<NN>: <exact substring >= 6 chars>`)\n"
        f"{numbered_block}\n\n"
        f"## Valid leaf token paths in `04-build/tokens.json` (compiled by `color.py`)\n"
        f"Reference ONLY real leaf token paths from this list wrapped in backticks (e.g. `` `colour.paper` ``):\n"
        f"{token_list_block}\n\n"
        f"## Hard rules enforced by `build_check`\n"
        f"1. Return ONLY a single JSON object matching `BUILD_DRAFT_SCHEMA` (`product`, `direction_id`,\n"
        f"   `direction_name`, `users`, `premise`, `why`, `how_to_use`, `what_not_to_do`, `evidence`).\n"
        f"2. Name ONLY `{chosen['name']}` (`{chosen['id']}`). Do not mention or hedge with any rejected candidate.\n"
        f"3. Do NOT write ANY colour literals (`#hex`, `oklch(...)`, `rgb(...)`, `hsl(...)`) or ANY numeric\n"
        f"   values (`16px`, `1.25rem`, `180ms`, `4.5:1`, `%`, `deg`) anywhere in prose. Every number lives in\n"
        f"   `04-build/tokens.json`; prose references token paths in backticks only.\n"
        f"4. Include backticked leaf token paths in `how_to_use` and `what_not_to_do`, and ensure every\n"
        f"   referenced token path exists in `04-build/tokens.json`.\n"
        f"5. Keep palette and typography prose aligned with `neutral_temp={chosen['neutral_temp']}`,\n"
        f"   `chroma_intent={chosen['chroma_intent']}`, and `type_family={chosen['type_family']}`.\n"
        f"6. Every claim section (`users`, `premise`, `why`, `how_to_use`, `what_not_to_do`) must cite a real\n"
        f"   numbered brief line in `evidence` and use domain vocabulary from the brief.\n"
    )


def _format_revise_task(base_task: str, draft: dict[str, Any], problems: list[dict[str, str]]) -> str:
    prob_lines = "\n".join(
        f"- [{p['rule']}] ({p['location']}): {p['message']}" for p in problems
    )
    return (
        f"{base_task}\n"
        f"## Revision required (`build_check` failed on your previous draft)\n"
        f"Fix every problem below and return the corrected JSON object only:\n"
        f"{prob_lines}\n\n"
        f"Previous draft JSON:\n"
        f"```json\n{json.dumps(draft, indent=2, sort_keys=True)}\n```\n"
    )


def _parse_draft_payload(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        if "draft" in raw and isinstance(raw["draft"], dict):
            return dict(raw["draft"])
        return dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        raise BuildError("empty build draft payload")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BuildError(f"build draft is not valid JSON: {exc.msg} at line {exc.lineno}") from None
    if not isinstance(parsed, dict):
        raise BuildError("build draft root must be a JSON object")
    if "draft" in parsed and isinstance(parsed["draft"], dict):
        return dict(parsed["draft"])
    return parsed


def _stem(word: str) -> str:
    for suffix in ("ings", "ing", "ers", "ies", "ied", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            if suffix in ("ies", "ied"):
                return word[: -len(suffix)] + "y"
            return word[: -len(suffix)]
    return word


def _content_stems(text: str) -> set[str]:
    clean = _BACKTICK_SPAN_RE.sub(" ", text)
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", clean.lower())
    stems: set[str] = set()
    for w in words:
        for part in re.split(r"[_-]+", w):
            if len(part) >= 3 and part not in _STOPWORDS:
                stems.add(_stem(part))
                stems.add(part)
    return stems


def _brief_vocabulary_stems(brief_doc: dict[str, Any]) -> set[str]:
    chunks: list[str] = [str(brief_doc.get("product") or "")]
    chunks.extend(text for _lid, text in directions.brief_lines(brief_doc))
    sections = brief_doc.get("sections", {})
    if isinstance(sections, dict):
        chunks.append(json.dumps(sections))
    return _content_stems(" ".join(chunks))


def _diff_token_leaves(expected: Any, actual: Any, prefix: str = "") -> list[str]:
    diffs: list[str] = []
    if type(expected) is not type(actual):
        return [prefix or "<root>"]
    if isinstance(expected, dict):
        keys = sorted(set(expected.keys()) | set(actual.keys()))
        for k in keys:
            child = f"{prefix}.{k}" if prefix else str(k)
            if k not in expected or k not in actual:
                diffs.append(child)
            else:
                diffs.extend(_diff_token_leaves(expected[k], actual[k], child))
        return diffs
    if expected != actual:
        return [prefix or "<root>"]
    return []


def _extract_prose_sections(draft: dict[str, Any] | None, design_md_text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "users": [],
        "premise": [],
        "why": [],
        "how_to_use": [],
        "what_not_to_do": [],
    }
    if isinstance(draft, dict) and all(k in draft for k in ("users", "premise", "why", "how_to_use", "what_not_to_do")):
        if isinstance(draft.get("users"), list):
            sections["users"].extend(str(x) for x in draft["users"])
        if isinstance(draft.get("premise"), str):
            sections["premise"].append(str(draft["premise"]))
        if isinstance(draft.get("why"), list):
            sections["why"].extend(str(x) for x in draft["why"])
        if isinstance(draft.get("how_to_use"), list):
            sections["how_to_use"].extend(str(x) for x in draft["how_to_use"])
        if isinstance(draft.get("what_not_to_do"), list):
            sections["what_not_to_do"].extend(str(x) for x in draft["what_not_to_do"])

    current: str | None = None
    for raw_line in design_md_text.splitlines():
        line = raw_line.strip()
        if line == "## Users":
            current = "users"
            continue
        if line == "### Named direction":
            current = "premise"
            continue
        if line == "### Why":
            current = "why"
            continue
        if line == "### How to use":
            current = "how_to_use"
            continue
        if line == "### What not to do":
            current = "what_not_to_do"
            continue
        if line.startswith("## ") or line.startswith("### "):
            current = None
            continue
        if current and line:
            if line.startswith("Status:"):
                continue
            if current == "premise" and (
                line.startswith("Palette profile:") or line.startswith("Typography profile:")
            ):
                continue
            cleaned = line.lstrip("- ").strip()
            if cleaned and cleaned not in sections[current]:
                sections[current].append(cleaned)
    return sections


def _check_design_md_contract(
    *,
    product: str,
    chosen: dict[str, Any],
    directions_doc: dict[str, Any],
    draft: dict[str, Any] | None,
    design_md_text: str,
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    chosen_id = str(chosen["id"])
    chosen_name = str(chosen["name"])

    if draft is not None:
        try:
            contracts.validate("build_draft", draft, step="build_check")
        except ContractError as exc:
            problems.append(_problem("build.design_md_contract", "04-build/draft.json", str(exc)))
        else:
            if draft.get("product") != product:
                problems.append(
                    _problem(
                        "build.design_md_contract",
                        "04-build/draft.json:product",
                        f"draft.product {draft.get('product')!r} does not match brief product {product!r}",
                    )
                )
            if draft.get("direction_id") != chosen_id:
                problems.append(
                    _problem(
                        "build.design_md_contract",
                        "04-build/draft.json:direction_id",
                        f"draft.direction_id {draft.get('direction_id')!r} does not match Gate 1 choice {chosen_id!r}",
                    )
                )
            if str(draft.get("direction_name") or "").strip().lower() != chosen_name.strip().lower():
                problems.append(
                    _problem(
                        "build.design_md_contract",
                        "04-build/draft.json:direction_name",
                        f"draft.direction_name {draft.get('direction_name')!r} does not match chosen direction {chosen_name!r}",
                    )
                )

    try:
        contracts.validate_design_md(
            design_md_text,
            step="build_check",
            file="04-build/DESIGN.md",
            product=product,
        )
    except ContractError as exc:
        problems.append(_problem("build.design_md_contract", "04-build/DESIGN.md", str(exc)))

    named_match = re.search(
        r"### Named direction\s*\n+(.+?)(?=\n### |\n## |\Z)",
        design_md_text,
         flags=re.DOTALL,
    )
    if not named_match:
        problems.append(
            _problem(
                "build.design_md_contract",
                "04-build/DESIGN.md:Direction.Named direction",
                "missing '### Named direction' subsection body",
            )
        )
    else:
        named_body = named_match.group(1).strip()
        if chosen_name.lower() not in named_body.lower():
            problems.append(
                _problem(
                    "build.design_md_contract",
                    "04-build/DESIGN.md:Direction.Named direction",
                    f"Named direction subsection must name the chosen direction {chosen_name!r} ({chosen_id!r})",
                )
            )
        if f"(`{chosen_id}`)" not in named_body and f"({chosen_id})" not in named_body:
            problems.append(
                _problem(
                    "build.design_md_contract",
                    "04-build/DESIGN.md:Direction.Named direction",
                    f"Named direction subsection must cite the chosen direction id {chosen_id!r}",
                )
            )

    other_dirs = [
        d for d in directions_doc.get("directions", [])
        if isinstance(d, dict) and str(d.get("id")) != chosen_id
    ]
    searchable_text = design_md_text
    if draft is not None:
        searchable_text = design_md_text + "\n" + json.dumps(
            {k: draft.get(k) for k in ("users", "premise", "why", "how_to_use", "what_not_to_do")}
        )
    for other in other_dirs:
        other_name = str(other.get("name") or "").strip()
        other_id = str(other.get("id") or "").strip()
        if other_name and re.search(rf"\b{re.escape(other_name)}\b", searchable_text, flags=re.IGNORECASE):
            problems.append(
                _problem(
                    "build.design_md_contract",
                    "04-build/DESIGN.md:Direction",
                    f"DESIGN.md names rejected candidate direction {other_name!r} ({other_id!r}); only {chosen_name!r} ({chosen_id!r}) is allowed",
                )
            )
        if other_id and re.search(
            rf"(?:direction\s+`?{re.escape(other_id)}`?|\(`{re.escape(other_id)}`\))",
            searchable_text,
            flags=re.IGNORECASE,
        ):
            problems.append(
                _problem(
                    "build.design_md_contract",
                    "04-build/DESIGN.md:Direction",
                    f"DESIGN.md references rejected direction id {other_id!r}; only {chosen_id!r} is allowed",
                )
            )

    hedge_hit = _HEDGE_RE.search(searchable_text)
    if hedge_hit:
        problems.append(
            _problem(
                "build.design_md_contract",
                "04-build/DESIGN.md:Direction",
                f"DESIGN.md hedges or offers an alternative direction ({hedge_hit.group(0)!r}); commit to {chosen_name!r} ({chosen_id!r}) only",
            )
        )

    return problems


def _extract_candidate_token_refs(text: str, chosen_id: str) -> list[str]:
    refs: list[str] = []
    for m in _BACKTICK_SPAN_RE.finditer(text):
        span = m.group(1).strip()
        if not span or span == chosen_id:
            continue
        if span.startswith(_TOKEN_PATH_PREFIXES) or ("." in span and not span.endswith(".json") and not span.endswith(".md") and "/" not in span):
            refs.append(span)
    stripped_backticks = _BACKTICK_SPAN_RE.sub(" ", text)
    for m in _INLINE_TOKEN_PATH_RE.finditer(stripped_backticks):
        span = m.group(1).rstrip(".,;:)")
        if span not in refs:
            refs.append(span)
    return refs


def _check_prose_tokens_agreement(
    *,
    chosen: dict[str, Any],
    tokens_doc: dict[str, Any],
    draft: dict[str, Any] | None,
    design_md_text: str,
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    chosen_id = str(chosen["id"])
    valid_leaf_paths = set(_collect_token_leaf_paths(tokens_doc))

    prose_sections = _extract_prose_sections(draft, design_md_text)
    all_refs: list[str] = []
    section_refs: dict[str, list[str]] = {}
    for sec_name, lines in prose_sections.items():
        sec_text = "\n".join(lines)
        refs = _extract_candidate_token_refs(sec_text, chosen_id)
        section_refs[sec_name] = refs
        for ref in refs:
            all_refs.append(ref)
            if "{" in ref or "}" in ref:
                problems.append(
                    _problem(
                        "build.prose_tokens_agreement",
                        f"04-build/DESIGN.md:{sec_name}",
                        f"token reference {ref!r} uses brace shorthand; cite exact leaf token paths in 04-build/tokens.json",
                    )
                )
            elif ref not in valid_leaf_paths:
                problems.append(
                    _problem(
                        "build.prose_tokens_agreement",
                        f"04-build/DESIGN.md:{sec_name}",
                        f"token {ref!r} referenced in DESIGN.md does not exist as a leaf token in 04-build/tokens.json",
                    )
                )

    for required_sec in ("how_to_use", "what_not_to_do"):
        valid_in_sec = [r for r in section_refs.get(required_sec, []) if r in valid_leaf_paths]
        if not valid_in_sec:
            problems.append(
                _problem(
                    "build.prose_tokens_agreement",
                    f"04-build/DESIGN.md:{required_sec}",
                    f"section {required_sec!r} must reference at least one valid leaf token path from 04-build/tokens.json",
                )
            )

    full_prose = "\n".join(
        line for sec in ("users", "premise", "why", "how_to_use", "what_not_to_do")
        for line in prose_sections.get(sec, [])
    )
    full_prose_lower = full_prose.lower()

    colour_ext = (
        tokens_doc.get("colour", {})
        .get("$extensions", {})
        .get(EXT, {})
    )
    neutral_temp = str(colour_ext.get("neutral_temp") or chosen.get("neutral_temp") or "")
    chroma_intent = str(colour_ext.get("chroma_intent") or chosen.get("chroma_intent") or "")
    type_family = str(chosen.get("type_family") or "")

    for bad_phrase in _NEUTRAL_OPPOSITES.get(neutral_temp, ()):
        if bad_phrase in full_prose_lower:
            problems.append(
                _problem(
                    "build.prose_tokens_agreement",
                    "04-build/DESIGN.md:Direction",
                    f"DESIGN.md prose describes {bad_phrase!r}, which contradicts tokens.json neutral_temp={neutral_temp!r}",
                )
            )

    for bad_phrase in _CHROMA_OPPOSITES.get(chroma_intent, ()):
        if bad_phrase in full_prose_lower:
            problems.append(
                _problem(
                    "build.prose_tokens_agreement",
                    "04-build/DESIGN.md:Direction",
                    f"DESIGN.md prose describes {bad_phrase!r}, which contradicts tokens.json chroma_intent={chroma_intent!r}",
                )
            )

    allowed_type_tokens: set[str] = {t.strip().lower() for t in type_family.split("+") if t.strip()}
    for fam_key in ("sans", "mono", "display"):
        fam_arr = (
            tokens_doc.get("type", {})
            .get("family", {})
            .get(fam_key, {})
            .get("$value", [])
        )
        if isinstance(fam_arr, list):
            for entry in fam_arr:
                allowed_type_tokens.add(str(entry).strip().lower())

    all_known_families: set[str] = set()
    for pairing in contracts.AVAILABLE_TYPE_FAMILIES:
        for part in pairing.split("+"):
            part_clean = part.strip()
            if part_clean:
                all_known_families.add(part_clean)

    for candidate_font in sorted(all_known_families):
        if candidate_font.lower() not in allowed_type_tokens:
            if re.search(rf"\b{re.escape(candidate_font)}\b", full_prose, flags=re.IGNORECASE):
                problems.append(
                    _problem(
                        "build.prose_tokens_agreement",
                        "04-build/DESIGN.md:Direction",
                        f"DESIGN.md prose names font family {candidate_font!r}, which contradicts tokens.json type_family={type_family!r}",
                    )
                )

    return problems


def _strip_allowed_tokens_for_literal_scan(text: str, valid_leaf_paths: set[str]) -> str:
    def _replace_backtick(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner in valid_leaf_paths or inner.startswith(_TOKEN_PATH_PREFIXES):
            return " "
        return f" {inner} "

    cleaned = _BACKTICK_SPAN_RE.sub(_replace_backtick, text)
    for token_path in sorted(valid_leaf_paths, key=len, reverse=True):
        cleaned = cleaned.replace(token_path, " ")
    return cleaned


def _check_no_raw_colour_literal(
    *,
    tokens_doc: dict[str, Any],
    draft: dict[str, Any] | None,
    design_md_text: str,
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    valid_leaf_paths = set(_collect_token_leaf_paths(tokens_doc))
    prose_sections = _extract_prose_sections(draft, design_md_text)

    for sec_name, lines in prose_sections.items():
        for idx, line in enumerate(lines, start=1):
            for bt in _BACKTICK_SPAN_RE.finditer(line):
                span = bt.group(1)
                for m in _BARE_COLOUR_RE.finditer(span):
                    problems.append(
                        _problem(
                            "build.no_raw_colour_literal",
                            f"04-build/DESIGN.md:{sec_name}[{idx}]",
                            f"raw colour literal {m.group(0)!r} inside backticks is forbidden; reference a token path from 04-build/tokens.json instead",
                        )
                    )
            scan_text = _strip_allowed_tokens_for_literal_scan(line, valid_leaf_paths)
            for m in _BARE_COLOUR_RE.finditer(scan_text):
                problems.append(
                    _problem(
                        "build.no_raw_colour_literal",
                        f"04-build/DESIGN.md:{sec_name}[{idx}]",
                        f"raw colour literal {m.group(0)!r} in DESIGN.md prose is forbidden; reference a token path in 04-build/tokens.json",
                    )
                )
            for m in _PROSE_NUMBER_RE.finditer(scan_text):
                problems.append(
                    _problem(
                        "build.no_raw_colour_literal",
                        f"04-build/DESIGN.md:{sec_name}[{idx}]",
                        f"raw numeric value {m.group(0)!r} in DESIGN.md prose is forbidden; all numbers belong in 04-build/tokens.json",
                    )
                )

    return problems


def _check_brief_evidence(
    *,
    brief_doc: dict[str, Any],
    draft: dict[str, Any] | None,
    design_md_text: str,
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    brief_map = directions.brief_lines(brief_doc)
    brief_stems = _brief_vocabulary_stems(brief_doc)

    if draft is None or not isinstance(draft.get("evidence"), dict):
        problems.append(
            _problem(
                "build.brief_evidence",
                "04-build/draft.json:evidence",
                "04-build/draft.json is missing the required 'evidence' map tracing each claim section to 01-brief/brief.json",
            )
        )
        return problems

    evidence_map = draft["evidence"]
    for key in BUILD_CLAIM_KEYS:
        cite = evidence_map.get(key)
        if isinstance(cite, dict):
            ref_m = re.search(r"#L(\d+)", str(cite.get("ref") or ""))
            cite_str = (
                f"L{int(ref_m.group(1)):02d}: {cite.get('quote', '')}"
                if ref_m
                else str(cite.get("quote") or "")
            )
        else:
            cite_str = str(cite or "")
        ok, reason = directions.evidence_matches_brief(cite_str, brief_map)
        if not ok:
            problems.append(
                _problem(
                    "build.brief_evidence",
                    f"04-build/draft.json:evidence.{key}",
                    f"claim {key!r} has invalid brief evidence: {reason}",
                )
            )

    prose_sections = _extract_prose_sections(draft, design_md_text)
    for sec_name in ("users", "why", "how_to_use", "what_not_to_do"):
        for idx, bullet in enumerate(prose_sections.get(sec_name, []), start=1):
            bullet_stems = _content_stems(bullet)
            if not bullet_stems:
                problems.append(
                    _problem(
                        "build.brief_evidence",
                        f"04-build/draft.json:{sec_name}[{idx}]",
                        f"claim bullet in {sec_name}[{idx}] carries no concrete product vocabulary from 01-brief/brief.json",
                    )
                )
                continue
            overlap = bullet_stems & brief_stems
            if not overlap:
                problems.append(
                    _problem(
                        "build.brief_evidence",
                        f"04-build/draft.json:{sec_name}[{idx}]",
                        f"unsourced product claim in {sec_name}[{idx}] shares zero domain vocabulary with 01-brief/brief.json: {bullet!r}",
                    )
                )

    return problems


def evaluate_build(
    *,
    brief_doc: dict[str, Any],
    directions_doc: dict[str, Any],
    gate_doc: dict[str, Any],
    tokens_doc: Any,
    tokens_raw_bytes: bytes,
    draft: dict[str, Any] | None,
    design_md_text: str,
) -> dict[str, Any]:
    """Run all seven deterministic Stage 5 (`build`) rules in `BUILD_RULE_ORDER`."""
    product = str(brief_doc.get("product") or "")
    choice = str(gate_doc.get("choice") or "").strip()
    chosen: dict[str, Any] | None = None
    for item in directions_doc.get("directions", []):
        if isinstance(item, dict) and item.get("id") == choice:
            chosen = item
            break
    if chosen is None:
        raise BuildError(f"Gate 1 choice {choice!r} not found in directions.json")

    by_rule: dict[str, list[dict[str, str]]] = {r: [] for r in BUILD_RULE_ORDER}

    # Rule 1: build.tokens_schema
    schema_ok = False
    try:
        contracts.validate_tokens(tokens_doc, step="build_check", file="04-build/tokens.json")
        schema_ok = True
    except ContractError as exc:
        by_rule["build.tokens_schema"].append(
            _problem("build.tokens_schema", "04-build/tokens.json", str(exc))
        )

    # Rule 2: build.proof_gate
    proof_ok = False
    if schema_ok and isinstance(tokens_doc, dict):
        proof_report = proof.evaluate_tokens(tokens_doc)
        if proof_report["verdict"] == "pass":
            proof_ok = True
        else:
            for row in proof_report.get("failing_rows", []):
                by_rule["build.proof_gate"].append(
                    _problem(
                        "build.proof_gate",
                        f"04-build/tokens.json:{row.get('rule', 'proof')}",
                        f"{row.get('rule', 'proof')}: {row.get('evidence', 'proof failed')}",
                    )
                )
            if not by_rule["build.proof_gate"]:
                failed_rids = ", ".join(proof_report.get("failing_rules", []))
                by_rule["build.proof_gate"].append(
                    _problem(
                        "build.proof_gate",
                        "04-build/tokens.json",
                        f"proof.py failed [{failed_rids}]",
                    )
                )

    # Rule 3: build.tokens_from_color (byte-for-byte identity against color.py output)
    tok_date = _extract_tokens_date(tokens_doc) or _extract_tokens_date(
        {"colour": {"$extensions": {EXT: {"date": design_files.today()}}}}
    )
    expected_tokens = compile_chosen_tokens(product, chosen, date=tok_date)
    expected_bytes = _canonical_tokens_bytes(expected_tokens)
    if schema_ok and proof_ok:
        if tokens_raw_bytes != expected_bytes:
            diff_paths = _diff_token_leaves(expected_tokens, tokens_doc)
            diff_summary = ", ".join(diff_paths[:6]) if diff_paths else "formatting/byte drift"
            by_rule["build.tokens_from_color"].append(
                _problem(
                    "build.tokens_from_color",
                    "04-build/tokens.json",
                    f"04-build/tokens.json is not byte-identical to color.py output for direction {choice!r} (differences at: {diff_summary})",
                )
            )

    # Rule 4: build.design_md_contract
    by_rule["build.design_md_contract"].extend(
        _check_design_md_contract(
            product=product,
            chosen=chosen,
            directions_doc=directions_doc,
            draft=draft,
            design_md_text=design_md_text,
        )
    )

    # Rule 5: build.prose_tokens_agreement
    ref_tokens_for_prose = tokens_doc if (schema_ok and isinstance(tokens_doc, dict)) else expected_tokens
    by_rule["build.prose_tokens_agreement"].extend(
        _check_prose_tokens_agreement(
            chosen=chosen,
            tokens_doc=ref_tokens_for_prose,
            draft=draft,
            design_md_text=design_md_text,
        )
    )

    # Rule 6: build.no_raw_colour_literal
    by_rule["build.no_raw_colour_literal"].extend(
        _check_no_raw_colour_literal(
            tokens_doc=ref_tokens_for_prose,
            draft=draft,
            design_md_text=design_md_text,
        )
    )

    # Rule 7: build.brief_evidence
    by_rule["build.brief_evidence"].extend(
        _check_brief_evidence(
            brief_doc=brief_doc,
            draft=draft,
            design_md_text=design_md_text,
        )
    )

    failing_rules = [r for r in BUILD_RULE_ORDER if by_rule[r]]
    problems = [p for r in BUILD_RULE_ORDER for p in by_rule[r]]
    rules_summary = {
        r: {
            "passed": len(by_rule[r]) == 0,
            "problem_count": len(by_rule[r]),
        }
        for r in BUILD_RULE_ORDER
    }
    return {
        "product": product,
        "direction_id": choice,
        "verdict": "pass" if not problems else "fail",
        "problem_count": len(problems),
        "failing_rules": failing_rules,
        "rules": rules_summary,
        "problems": problems,
    }


def build_collect(ws: Workspace) -> dict[str, Any]:
    """Stage 5a (`build_collect`): compile `04-build/tokens.json` via `color.py` and write `04-build/task.md`."""
    ws = ws.for_step("build_collect")
    brief_doc, _directions_doc, gate_doc, chosen = _load_inputs(ws)
    product = str(brief_doc["product"])
    chosen_id = str(chosen["id"])

    # Validate the Stage 2 candidate tokens.json declared in STEP_INPUTS["build_collect"]
    cand_tokens = ws.read_json(f"02-directions/{chosen_id}/tokens.json")
    contracts.validate_tokens(
        cand_tokens,
        step="build_collect",
        file=f"02-directions/{chosen_id}/tokens.json",
    )

    stamp = _resolve_build_date(ws, chosen)
    tokens_doc = compile_chosen_tokens(product, chosen, date=stamp)
    tokens_bytes = _canonical_tokens_bytes(tokens_doc)

    # Write 04-build/tokens.json deterministically from color.py (never touched by the model)
    build_dir = ws.folder("build")
    build_dir.mkdir(parents=True, exist_ok=True)
    tokens_path = build_dir / "tokens.json"
    tokens_path.write_bytes(tokens_bytes)

    input_digest = _sha256_json(
        {
            "brief": brief_doc,
            "chosen": chosen,
            "gate_direction": gate_doc,
            "tokens_sha256": _sha256_bytes(tokens_bytes),
        }
    )

    build_json_path = build_dir / "build.json"
    design_md_path = build_dir / "DESIGN.md"
    draft_path = build_dir / "draft.json"
    if build_json_path.is_file() and design_md_path.is_file() and draft_path.is_file():
        try:
            existing_build = json.loads(build_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildError(f"corrupt prior build record at {build_json_path}: {exc}") from exc
        try:
            existing_draft = json.loads(draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildError(f"corrupt prior build draft at {draft_path}: {exc}") from exc
        try:
            existing_md = design_md_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BuildError(f"cannot read prior DESIGN.md at {design_md_path}: {exc}") from exc
        if (
            isinstance(existing_build, dict)
            and existing_build.get("input_digest") == input_digest
            and existing_build.get("direction") == chosen_id
            and isinstance(existing_draft, dict)
        ):
            rep = evaluate_build(
                brief_doc=brief_doc,
                directions_doc=_directions_doc,
                gate_doc=gate_doc,
                tokens_doc=tokens_doc,
                tokens_raw_bytes=tokens_bytes,
                draft=existing_draft,
                design_md_text=existing_md,
            )
            if rep["verdict"] == "pass":
                task_text = _format_build_task(brief_doc, chosen, gate_doc, tokens_doc)
                (build_dir / "task.md").write_text(task_text, encoding="utf-8")
                ws.mark("build_collect", "done", direction=chosen_id, model="no")
                return {
                    "step": "build_collect",
                    "status": "reused",
                    "model": "no",
                    "direction_id": chosen_id,
                    "tokens": "04-build/tokens.json",
                    "task": "",
                }

    task_text = _format_build_task(brief_doc, chosen, gate_doc, tokens_doc)
    (build_dir / "task.md").write_text(task_text, encoding="utf-8")
    ws.mark("build_collect", "done", direction=chosen_id, model="yes")
    return {
        "step": "build_collect",
        "status": "ready",
        "model": "yes",
        "direction_id": chosen_id,
        "tokens": "04-build/tokens.json",
        "task": task_text,
    }


def build_check(
    ws: Workspace,
    draft: str | dict[str, Any] | None = None,
    *,
    allow_retry: bool = False,
) -> dict[str, Any]:
    """Stage 5b (`build_check`): deterministically validate `04-build/tokens.json` and `04-build/DESIGN.md`."""
    ws = ws.for_step("build_check")
    brief_doc, directions_doc, gate_doc, chosen = _load_inputs(ws)
    product = str(brief_doc["product"])
    chosen_id = str(chosen["id"])

    build_dir = ws.folder("build")
    build_dir.mkdir(parents=True, exist_ok=True)
    tokens_path = build_dir / "tokens.json"
    if not tokens_path.is_file():
        raise BuildError("04-build/tokens.json is missing; run build_collect before build_check")
    tokens_raw_bytes = tokens_path.read_bytes()
    try:
        tokens_doc = json.loads(tokens_raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildError(f"04-build/tokens.json is not valid JSON: {exc.msg}") from None

    draft_obj: dict[str, Any] | None = None
    if draft is not None and (isinstance(draft, dict) or str(draft).strip()):
        draft_obj = _parse_draft_payload(draft)
        (build_dir / "draft.json").write_text(
            json.dumps(draft_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    elif (build_dir / "draft.json").is_file():
        draft_obj = _parse_draft_payload(
            (build_dir / "draft.json").read_text(encoding="utf-8")
        )

    stamp = _extract_tokens_date(tokens_doc) or _resolve_build_date(ws, chosen)
    design_md_path = build_dir / "DESIGN.md"
    if draft_obj is not None and (draft is not None or not design_md_path.is_file()):
        if all(k in draft_obj for k in ("users", "premise", "why", "how_to_use", "what_not_to_do")):
            rendered_md = render_design_md(
                product=product,
                draft=draft_obj,
                chosen_direction=chosen,
                gate_direction=gate_doc,
                status="draft",
                date=stamp,
            )
            design_md_path.write_text(rendered_md, encoding="utf-8")

    if not design_md_path.is_file():
        raise BuildError("04-build/DESIGN.md is missing and could not be rendered from 04-build/draft.json")
    design_md_text = design_md_path.read_text(encoding="utf-8")

    eval_report = evaluate_build(
        brief_doc=brief_doc,
        directions_doc=directions_doc,
        gate_doc=gate_doc,
        tokens_doc=tokens_doc,
        tokens_raw_bytes=tokens_raw_bytes,
        draft=draft_obj,
        design_md_text=design_md_text,
    )

    verdict = "ok" if eval_report["verdict"] == "pass" else "retry"
    revise_task = ""
    if verdict == "retry":
        base_task = (
            (build_dir / "task.md").read_text(encoding="utf-8")
            if (build_dir / "task.md").is_file()
            else _format_build_task(brief_doc, chosen, gate_doc, tokens_doc if isinstance(tokens_doc, dict) else {})
        )
        revise_task = _format_revise_task(base_task, draft_obj or {}, eval_report["problems"])

    check_doc = {
        "step": "build_check",
        "product": product,
        "direction_id": chosen_id,
        "verdict": verdict,
        "problem_count": eval_report["problem_count"],
        "failing_rules": eval_report["failing_rules"],
        "rules": eval_report["rules"],
        "problems": eval_report["problems"],
        "revise_task": revise_task,
    }
    (build_dir / "check.json").write_text(
        json.dumps(check_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    ws.mark("build_check", "done", verdict=verdict, problem_count=eval_report["problem_count"])

    if verdict != "ok" and not allow_retry:
        rules_str = ", ".join(eval_report["failing_rules"])
        details = "; ".join(
            f"[{p['rule']}] {p['location']}: {p['message']}" for p in eval_report["problems"]
        )
        raise BuildError(f"build_check failed ({rules_str}): {details}")

    return check_doc


def build_finish(ws: Workspace, draft: str | dict[str, Any] | None = None) -> dict[str, Any]:
    """Stage 5c (`build_finish` / step `build`): verify `verdict == 'ok'` and persist `04-build/{tokens.json,DESIGN.md,build.json}`."""
    if draft is not None and (isinstance(draft, dict) or str(draft).strip()):
        build_check(ws, draft=draft, allow_retry=False)
    elif not (ws.path / "04-build" / "check.json").is_file():
        build_check(ws, draft=None, allow_retry=False)
    else:
        chk_existing = json.loads((ws.path / "04-build" / "check.json").read_text(encoding="utf-8"))
        if chk_existing.get("verdict") != "ok":
            build_check(ws, draft=None, allow_retry=False)

    ws_finish = ws.for_step("build")
    brief_doc, directions_doc, gate_doc, chosen = _load_inputs(ws_finish)
    product = str(brief_doc["product"])
    chosen_id = str(chosen["id"])

    check_doc = ws_finish.read_json("04-build/check.json")
    if check_doc.get("verdict") != "ok":
        raise BuildError(
            f"04-build/check.json verdict is {check_doc.get('verdict')!r}, not 'ok'; failing_rules={check_doc.get('failing_rules')}"
        )

    build_dir = ws_finish.folder("build")
    build_dir.mkdir(parents=True, exist_ok=True)
    stamp = _resolve_build_date(ws_finish, chosen)
    tokens_doc = compile_chosen_tokens(product, chosen, date=stamp)
    tokens_bytes = _canonical_tokens_bytes(tokens_doc)
    (build_dir / "tokens.json").write_bytes(tokens_bytes)

    draft_obj = ws_finish.read_json("04-build/draft.json")
    design_md_text = render_design_md(
        product=product,
        draft=draft_obj,
        chosen_direction=chosen,
        gate_direction=gate_doc,
        status="draft",
        date=stamp,
    )
    (build_dir / "DESIGN.md").write_text(design_md_text, encoding="utf-8")

    final_eval = evaluate_build(
        brief_doc=brief_doc,
        directions_doc=directions_doc,
        gate_doc=gate_doc,
        tokens_doc=tokens_doc,
        tokens_raw_bytes=tokens_bytes,
        draft=draft_obj,
        design_md_text=design_md_text,
    )
    if final_eval["verdict"] != "pass":
        rules_str = ", ".join(final_eval["failing_rules"])
        raise BuildError(f"build_finish verification failed ({rules_str}): {final_eval['problems']}")

    if ws_finish.round == 0:
        ws_finish.next_round()

    input_digest = _sha256_json(
        {
            "brief": brief_doc,
            "chosen": chosen,
            "gate_direction": gate_doc,
            "tokens_sha256": _sha256_bytes(tokens_bytes),
        }
    )
    out = {
        "step": "build",
        "status": "done",
        "product": product,
        "round": ws_finish.round,
        "direction": chosen_id,
        "direction_name": str(chosen["name"]),
        "tokens": "04-build/tokens.json",
        "design_md": "04-build/DESIGN.md",
        "tokens_file": "04-build/tokens.json",
        "design_md_file": "04-build/DESIGN.md",
        "tokens_sha256": _sha256_bytes(tokens_bytes),
        "design_md_sha256": _sha256_bytes(design_md_text.encode("utf-8")),
        "input_digest": input_digest,
        "parts": list(contracts.TOKEN_PARTS),
    }
    contracts.validate("build", out, step="build")
    (build_dir / "build.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    ws_finish.mark("build", "done", direction=chosen_id)
    return out


def check_workspace(workspace_dir: str | Path) -> dict[str, Any]:
    """Run `evaluate_build` on a workspace directory or known-case folder and return the report."""
    root = Path(workspace_dir).resolve()
    brief_path = root / "01-brief" / "brief.json"
    directions_path = root / "02-directions" / "directions.json"
    gate_path = root / "02-directions" / "gate_direction.json"
    tokens_path = root / "04-build" / "tokens.json"
    design_md_path = root / "04-build" / "DESIGN.md"
    draft_path = root / "04-build" / "draft.json"

    for req in (brief_path, directions_path, gate_path, tokens_path, design_md_path):
        if not req.is_file():
            raise BuildError(f"missing required build check input: {req}")

    brief_doc = json.loads(brief_path.read_text(encoding="utf-8"))
    directions_doc = json.loads(directions_path.read_text(encoding="utf-8"))
    gate_doc = json.loads(gate_path.read_text(encoding="utf-8"))
    tokens_raw_bytes = tokens_path.read_bytes()
    try:
        tokens_doc = json.loads(tokens_raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildError(f"{tokens_path} is not valid JSON: {exc.msg}") from None

    draft_obj: dict[str, Any] | None = None
    if draft_path.is_file():
        try:
            draft_obj = json.loads(draft_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BuildError(f"{draft_path} is not valid JSON: {exc.msg}") from None

    design_md_text = design_md_path.read_text(encoding="utf-8")
    return evaluate_build(
        brief_doc=brief_doc,
        directions_doc=directions_doc,
        gate_doc=gate_doc,
        tokens_doc=tokens_doc,
        tokens_raw_bytes=tokens_raw_bytes,
        draft=draft_obj,
        design_md_text=design_md_text,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m foundation.build",
        description="Run Stage 5 (build) deterministic checks on a foundation workspace or known-case directory.",
    )
    parser.add_argument("workspace", help="Path to .temper/design workspace or known-case folder")
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    args = parser.parse_args(argv)

    report = check_workspace(args.workspace)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"verdict={report['verdict']} direction={report['direction_id']} "
            f"problems={report['problem_count']} failing_rules={report['failing_rules']}"
        )
        for p in report["problems"]:
            print(f"  - [{p['rule']}] {p['location']}: {p['message']}")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
