"""Closed contracts, schemas, and per-step input declarations for design_foundation_v1.

Every JSON contract in the foundation workspace is closed (additionalProperties: false), including tokens.json
(DTCG 2025.10). Every script step declares the exact workspace and product-repo files it may read in STEP_INPUTS;
Workspace.resolve_input calls check_input before every read and raises ContractError on any undeclared path.
Model steps declare empty tuples in MODEL_STEPS, tools: [], and receive no workspace_path.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import design_files
import jsonschema
from app_screen.contracts import ID, TEXT, ContractError

TOKEN_PARTS: tuple[str, ...] = design_files.TOKEN_PARTS
EXT = design_files.EXT
FORMAT = design_files.FORMAT
NON_EMPTY: dict[str, Any] = TEXT
SHA256: dict[str, Any] = {"type": "string", "pattern": r"^[0-9a-f]{64}$"}
GATE_DECIDED_BY: tuple[str, ...] = design_files.DECIDERS


def closed(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        schema["required"] = list(required)
    return schema

DESIGN_MD_SECTIONS: tuple[str, ...] = (
    "Users",
    "Direction",
    "Tokens",
    "Logo",
    "Library",
    "Approvals",
)
DIRECTION_SUBSECTIONS: tuple[str, ...] = (
    "Named direction",
    "Why",
    "How to use",
    "What not to do",
)

SURFACE_KINDS = ("app", "sample_screen")
CHECK_RESULTS = ("pass", "fail", "skipped")
SEVERITIES = ("blocker", "must", "should", "could", "wont", "info")

CHROMA_INTENTS: tuple[str, ...] = ("muted", "balanced", "crisp", "vivid")
NEUTRAL_TEMPS: tuple[str, ...] = ("cool", "slate", "neutral", "true", "warm")
NEUTRAL_TEMP_HUES: dict[str, float] = {
    "cool": 250.0,
    "slate": 225.0,
    "neutral": 210.0,
    "true": 210.0,
    "warm": 65.0,
}
TYPE_FAMILY_STACKS: dict[str, tuple[list[str], list[str]]] = {
    "IBM Plex Sans": (["IBM Plex Sans", "system-ui", "sans-serif"], ["IBM Plex Mono", "ui-monospace", "monospace"]),
    "Plus Jakarta Sans": (["Plus Jakarta Sans", "system-ui", "sans-serif"], ["JetBrains Mono", "ui-monospace", "monospace"]),
    "Space Grotesk": (["Space Grotesk", "system-ui", "sans-serif"], ["JetBrains Mono", "ui-monospace", "monospace"]),
    "Source Sans 3": (["Source Sans 3", "system-ui", "sans-serif"], ["Source Code Pro", "ui-monospace", "monospace"]),
    "Work Sans": (["Work Sans", "system-ui", "sans-serif"], ["IBM Plex Mono", "ui-monospace", "monospace"]),
    "DM Sans": (["DM Sans", "system-ui", "sans-serif"], ["JetBrains Mono", "ui-monospace", "monospace"]),
    "Public Sans": (["Public Sans", "system-ui", "sans-serif"], ["IBM Plex Mono", "ui-monospace", "monospace"]),
    "Geist": (["Geist", "system-ui", "sans-serif"], ["Geist Mono", "ui-monospace", "monospace"]),
    "Fraunces": (["Fraunces", "Georgia", "serif"], ["IBM Plex Mono", "ui-monospace", "monospace"]),
    "Newsreader": (["Newsreader", "Georgia", "serif"], ["IBM Plex Mono", "ui-monospace", "monospace"]),
    "Instrument Serif": (["Instrument Serif", "Georgia", "serif"], ["JetBrains Mono", "ui-monospace", "monospace"]),
    "Inter": (["Inter", "system-ui", "sans-serif"], ["JetBrains Mono", "ui-monospace", "monospace"]),
}
AVAILABLE_TYPE_FAMILIES: tuple[str, ...] = tuple(TYPE_FAMILY_STACKS.keys())
MIN_ANCHOR_HUE_SEPARATION_DEG: float = 40.0
DIRECTION_CLAIM_KEYS: tuple[str, ...] = (
    "premise",
    "anchor_hue_deg",
    "chroma_intent",
    "neutral_temp",
    "type_family",
    "why",
)

# ---------------------------------------------------------------- per-step input declarations

MODEL_STEPS: dict[str, tuple[str, ...]] = {
    "directions_read": (),
    "directions_revise": (),
    "build_read": (),
    "build_revise": (),
}

STEP_INPUTS: dict[str, tuple[str, ...]] = {
    "brief": (
        "run.json",
        ".temper/product/brief.md",
        "01-brief/brief.json",
    ),
    "directions_collect": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/task.md",
        "02-directions/directions.json",
        "02-directions/*/tokens.json",
        "02-directions/*/DESIGN.md",
    ),
    "directions_check": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/task.md",
        "02-directions/draft.json",
        "02-directions/check.json",
        "02-directions/directions.json",
        "02-directions/*/tokens.json",
        "02-directions/*/DESIGN.md",
    ),
    "directions_finish": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/task.md",
        "02-directions/draft.json",
        "02-directions/check.json",
        "02-directions/check-final.json",
        "02-directions/directions.json",
        "02-directions/*/tokens.json",
        "02-directions/*/DESIGN.md",
    ),
    "directions": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/task.md",
        "02-directions/draft.json",
        "02-directions/check.json",
        "02-directions/check-final.json",
        "02-directions/directions.json",
        "02-directions/*/tokens.json",
        "02-directions/*/DESIGN.md",
    ),
    "proof": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/directions.json",
        "02-directions/*/tokens.json",
        "02-directions/*/DESIGN.md",
        "03-proof/proof.json",
        "03-proof/table.md",
        "03-proof/sample-screen.html",
        "03-proof/preview-*.html",
    ),
    "gate_direction": (
        "run.json",
        "taste-owner.md",
        "01-brief/brief.json",
        "02-directions/directions.json",
        "03-proof/proof.json",
        "03-proof/table.md",
        "02-directions/gate_direction.json",
    ),
    "build_collect": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/directions.json",
        "02-directions/*/tokens.json",
        "02-directions/*/DESIGN.md",
        "02-directions/gate_direction.json",
        "05-checks/round-*/checks.json",
        "05-checks/gate_final.json",
    ),
    "build_check": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/gate_direction.json",
        "04-build/draft.json",
        "04-build/build.json",
        "04-build/tokens.json",
        "04-build/DESIGN.md",
    ),
    "build": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/directions.json",
        "02-directions/*/tokens.json",
        "02-directions/*/DESIGN.md",
        "02-directions/gate_direction.json",
        "04-build/draft.json",
        "04-build/build.json",
        "04-build/tokens.json",
        "04-build/DESIGN.md",
        "05-checks/round-*/checks.json",
        "05-checks/gate_final.json",
    ),
    "checks": (
        "run.json",
        "01-brief/brief.json",
        "03-proof/proof.json",
        "03-proof/table.md",
        "03-proof/sample-screen.html",
        "04-build/build.json",
        "04-build/tokens.json",
        "04-build/DESIGN.md",
        "05-checks/round-*/checks.json",
    ),
    "gate_final": (
        "run.json",
        "taste-owner.md",
        "04-build/build.json",
        "05-checks/round-*/checks.json",
        "05-checks/gate_final.json",
    ),
    "handoff": (
        "run.json",
        "01-brief/brief.json",
        "02-directions/gate_direction.json",
        "04-build/build.json",
        "04-build/tokens.json",
        "04-build/DESIGN.md",
        "05-checks/round-*/checks.json",
        "05-checks/gate_final.json",
        "06-handoff/handoff.json",
        "06-handoff/tokens.json",
        "06-handoff/DESIGN.md",
    ),
    **MODEL_STEPS,
}

REPO_INPUT_PATTERNS: frozenset[str] = frozenset({
    ".temper/product/brief.md",
})


def declared_inputs(step: str, *, extra_inputs: Iterable[str] = ()) -> list[str]:
    """Return the sorted list of input patterns declared for ``step``."""
    if step not in STEP_INPUTS:
        raise ContractError(f"unknown foundation step {step!r}; declared steps: {sorted(STEP_INPUTS)}")
    return sorted(set(STEP_INPUTS[step]) | {str(p) for p in extra_inputs if str(p).strip()})


def _normalize_rel_path(rel_path: str | Path, *, allow_absolute_extra: bool = False) -> str:
    raw = str(rel_path).strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        raise ValueError("empty path")
    if raw.startswith("/"):
        if allow_absolute_extra and ".." not in Path(raw).parts:
            return str(Path(raw))
        raise ValueError("absolute path not allowed")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise ValueError("path escapes workspace")
    return "/".join(parts)


def _matches_pattern(norm_path: str, pattern: str) -> bool:
    if pattern == norm_path:
        return True
    if "*" not in pattern and "?" not in pattern and "[" not in pattern:
        return False
    pat_parts = pattern.split("/")
    path_parts = norm_path.split("/")
    if len(pat_parts) != len(path_parts):
        return False
    return all(fnmatchcase(seg, pat) for seg, pat in zip(path_parts, pat_parts, strict=True))


def check_input(
    step: str,
    rel_path: str | Path,
    *,
    repo_input: bool = False,
    extra_inputs: Iterable[str] = (),
) -> str:
    """Validate that ``step`` declared ``rel_path`` in ``STEP_INPUTS``; return normalized path or fail loud."""
    if step not in STEP_INPUTS:
        raise ContractError(f"unknown foundation step {step!r}; declared steps: {sorted(STEP_INPUTS)}")
    extras = tuple(str(x).strip() for x in extra_inputs if str(x).strip())
    declared = declared_inputs(step, extra_inputs=extras)
    if step in MODEL_STEPS and not STEP_INPUTS[step]:
        raise ContractError(
            f"model step '{step}' has no workspace access and refused read of '{rel_path}'; "
            f"declared inputs: {declared}"
        )
    try:
        norm = _normalize_rel_path(rel_path, allow_absolute_extra=bool(extras))
    except ValueError as exc:
        raise ContractError(
            f"step '{step}' refused undeclared read of '{rel_path}' ({exc}); declared inputs: {declared}"
        ) from exc

    patterns = list(STEP_INPUTS[step]) + list(extras)
    matched = [pat for pat in patterns if _matches_pattern(norm, pat)]
    if not matched:
        raise ContractError(
            f"step '{step}' refused undeclared read of '{norm}'; declared inputs: {declared}"
        )
    is_repo_pattern = any(pat in REPO_INPUT_PATTERNS or pat.startswith("/") for pat in matched)
    if repo_input and not is_repo_pattern:
        raise ContractError(
            f"step '{step}' refused undeclared repo read of '{norm}'; declared inputs: {declared}"
        )
    return norm


check_read = check_input


# ---------------------------------------------------------------- closed tokens.json schema (DTCG 2025.10)

TOKEN_KEY_RE = r"^(?!\$)[A-Za-z0-9][A-Za-z0-9_-]*$"
ALIAS_RE = r"^\{[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+\}$"
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
HEX_RE = r"^#[0-9A-Fa-f]{6}$"


def _part_extension_schema(part: str) -> dict[str, Any]:
    inner = {
        "type": "object",
        "required": ["part", "status", "date"],
        "additionalProperties": False,
        "properties": {
            "part": {"const": part},
            "status": {"type": "string", "enum": ["draft", "approved"]},
            "approved_by": {
                "type": "string",
                "enum": [*design_files.DECIDERS, design_files.FIXTURE_DECIDER],
            },
            "date": {"type": "string", "pattern": DATE_RE},
        },
        "allOf": [
            {
                "if": {"properties": {"status": {"const": "approved"}}, "required": ["status"]},
                "then": {"required": ["approved_by", "date"]},
            },
            {
                "if": {"properties": {"status": {"const": "draft"}}, "required": ["status"]},
                "then": {"not": {"required": ["approved_by"]}},
            },
        ],
    }
    return closed(
        {EXT: inner},
        required=[EXT],
    )


def _part_group_schema(part: str, node_ref: str, allowed_types: list[str] | None = None) -> dict[str, Any]:
    props: dict[str, Any] = {
        "$description": {"type": "string"},
        "$extensions": _part_extension_schema(part),
    }
    if allowed_types:
        props["$type"] = {"type": "string", "enum": allowed_types}
    return {
        "type": "object",
        "required": ["$extensions"],
        "additionalProperties": False,
        "minProperties": 2,
        "properties": props,
        "patternProperties": {
            TOKEN_KEY_RE: {"$ref": f"#/$defs/{node_ref}"},
        },
    }


def _subgroup_or_token(token_ref: str, group_ref: str) -> dict[str, Any]:
    return {
        "type": "object",
        "if": {"required": ["$value"]},
        "then": {"$ref": f"#/$defs/{token_ref}"},
        "else": {"$ref": f"#/$defs/{group_ref}"},
    }


def _subgroup_schema(node_ref: str, allowed_types: list[str] | None = None) -> dict[str, Any]:
    props: dict[str, Any] = {
        "$description": {"type": "string"},
    }
    if allowed_types:
        props["$type"] = {"type": "string", "enum": allowed_types}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "minProperties": 1,
        "patternProperties": {
            TOKEN_KEY_RE: {"$ref": f"#/$defs/{node_ref}"},
        },
    }


def _leaf_token_schema(value_ref: str, allowed_types: list[str], *, require_type: bool = False) -> dict[str, Any]:
    req = ["$value", "$type"] if require_type else ["$value"]
    return closed(
        {
            "$type": {"type": "string", "enum": allowed_types},
            "$value": {"$ref": f"#/$defs/{value_ref}"},
            "$description": {"type": "string"},
        },
        required=req,
    )


_TOKENS_ROOT_PROPS: dict[str, Any] = {
    "$schema": {"type": "string", "minLength": 1},
    "$description": {"type": "string"},
    "$extensions": closed(
        {
            EXT: closed(
                {
                    "product": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{1,39}$"},
                    "format": {"const": FORMAT},
                },
                required=["product", "format"],
            )
        },
        required=[EXT],
    ),
    "colour": _part_group_schema("colour", "colourNode", ["color"]),
    "type": {
        "type": "object",
        "required": ["$extensions", "family"],
        "additionalProperties": False,
        "properties": {
            "$description": {"type": "string"},
            "$type": {
                "type": "string",
                "enum": ["fontFamily", "dimension", "fontWeight", "number", "typography"],
            },
            "$extensions": _part_extension_schema("type"),
            "family": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "$description": {"type": "string"},
                    "$type": {"type": "string", "enum": ["fontFamily"]},
                },
                "minProperties": 1,
                "patternProperties": {
                    TOKEN_KEY_RE: {"$ref": "#/$defs/fontFamilyToken"},
                },
            },
        },
        "patternProperties": {
            r"^(?!\$)(?!family$)[A-Za-z0-9][A-Za-z0-9_-]*$": {"$ref": "#/$defs/typeNode"},
        },
    },
    "spacing": _part_group_schema("spacing", "dimensionNode", ["dimension"]),
    "radius": _part_group_schema("radius", "dimensionNode", ["dimension"]),
    "elevation": _part_group_schema("elevation", "shadowNode", ["shadow"]),
    "motion": _part_group_schema("motion", "motionNode", ["duration", "cubicBezier"]),
}

_TOKENS_DEFS: dict[str, Any] = {
    "aliasRef": {"type": "string", "pattern": ALIAS_RE},
    "colourDirectValue": closed(
        {
            "colorSpace": {
                "type": "string",
                "enum": ["srgb", "oklch", "display-p3", "srgb-linear"],
            },
            "hex": {"type": "string", "pattern": HEX_RE},
            "components": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {"type": "number"},
            },
            "alpha": {"type": "number", "minimum": 0, "maximum": 1},
        },
        required=["colorSpace", "hex"],
    ),
    "colourValue": {
        "type": ["object", "string"],
        "if": {"type": "object"},
        "then": {"$ref": "#/$defs/colourDirectValue"},
        "else": {"$ref": "#/$defs/aliasRef"},
    },
    "colourToken": _leaf_token_schema("colourValue", ["color"]),
    "colourGroup": _subgroup_schema("colourNode", ["color"]),
    "colourNode": _subgroup_or_token("colourToken", "colourGroup"),
    "dimensionDirectValue": closed(
        {
            "value": {"type": "number"},
            "unit": {"type": "string", "enum": ["px", "rem"]},
        },
        required=["value", "unit"],
    ),
    "dimensionValue": {
        "type": ["object", "string"],
        "if": {"type": "object"},
        "then": {"$ref": "#/$defs/dimensionDirectValue"},
        "else": {"$ref": "#/$defs/aliasRef"},
    },
    "dimensionToken": _leaf_token_schema("dimensionValue", ["dimension"]),
    "dimensionGroup": _subgroup_schema("dimensionNode", ["dimension"]),
    "dimensionNode": _subgroup_or_token("dimensionToken", "dimensionGroup"),
    "fontFamilyDirectArray": {
        "type": "array",
        "minItems": 1,
        "items": NON_EMPTY,
    },
    "fontFamilyValue": {
        "type": ["array", "string"],
        "if": {"type": "array"},
        "then": {"$ref": "#/$defs/fontFamilyDirectArray"},
        "else": NON_EMPTY,
    },
    "fontFamilyToken": _leaf_token_schema("fontFamilyValue", ["fontFamily"]),
    "fontWeightValue": {
        "oneOf": [
            {"type": "number", "minimum": 1, "maximum": 1000},
            {"type": "string", "enum": sorted(design_files.WEIGHT_WORDS)},
            {"$ref": "#/$defs/aliasRef"},
        ]
    },
    "numberOrAlias": {
        "type": ["number", "string"],
        "if": {"type": "number"},
        "then": {"type": "number"},
        "else": {"$ref": "#/$defs/aliasRef"},
    },
    "typographyDirectValue": closed(
        {
            "fontFamily": {"$ref": "#/$defs/fontFamilyValue"},
            "fontSize": {"$ref": "#/$defs/dimensionValue"},
            "fontWeight": {"$ref": "#/$defs/fontWeightValue"},
            "lineHeight": {"$ref": "#/$defs/numberOrAlias"},
            "letterSpacing": {"$ref": "#/$defs/dimensionValue"},
        },
        required=["fontFamily", "fontSize", "fontWeight", "lineHeight"],
    ),
    "typeAnyValue": {
        "oneOf": [
            {"$ref": "#/$defs/dimensionDirectValue"},
            {"$ref": "#/$defs/typographyDirectValue"},
            {"$ref": "#/$defs/fontFamilyDirectArray"},
            {"type": "number"},
            {"type": "string", "minLength": 1},
        ]
    },
    "typeToken": _leaf_token_schema(
        "typeAnyValue",
        ["dimension", "fontFamily", "fontWeight", "number", "typography"],
    ),
    "typeGroup": _subgroup_schema(
        "typeNode",
        ["dimension", "fontFamily", "fontWeight", "number", "typography"],
    ),
    "typeNode": _subgroup_or_token("typeToken", "typeGroup"),
    "shadowLayer": closed(
        {
            "color": {"$ref": "#/$defs/colourValue"},
            "offsetX": {"$ref": "#/$defs/dimensionValue"},
            "offsetY": {"$ref": "#/$defs/dimensionValue"},
            "blur": {"$ref": "#/$defs/dimensionValue"},
            "spread": {"$ref": "#/$defs/dimensionValue"},
            "inset": {"type": "boolean"},
        },
        required=["color", "offsetX", "offsetY", "blur", "spread"],
    ),
    "shadowValue": {
        "type": ["object", "array", "string"],
        "if": {"type": "object"},
        "then": {"$ref": "#/$defs/shadowLayer"},
        "else": {
            "if": {"type": "array"},
            "then": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/shadowLayer"}},
            "else": {"$ref": "#/$defs/aliasRef"},
        },
    },
    "shadowToken": _leaf_token_schema("shadowValue", ["shadow"]),
    "shadowGroup": _subgroup_schema("shadowNode", ["shadow"]),
    "shadowNode": _subgroup_or_token("shadowToken", "shadowGroup"),
    "durationDirectValue": closed(
        {
            "value": {"type": "number", "minimum": 0},
            "unit": {"type": "string", "enum": ["ms", "s"]},
        },
        required=["value", "unit"],
    ),
    "cubicBezierDirectValue": {
        "type": "array",
        "minItems": 4,
        "maxItems": 4,
        "prefixItems": [
            {"type": "number", "minimum": 0, "maximum": 1},
            {"type": "number"},
            {"type": "number", "minimum": 0, "maximum": 1},
            {"type": "number"},
        ],
    },
    "motionValue": {
        "type": ["object", "array", "string"],
        "if": {"type": "object"},
        "then": {"$ref": "#/$defs/durationDirectValue"},
        "else": {
            "if": {"type": "array"},
            "then": {"$ref": "#/$defs/cubicBezierDirectValue"},
            "else": {"$ref": "#/$defs/aliasRef"},
        },
    },
    "motionToken": {
        "type": "object",
        "required": ["$value"],
        "additionalProperties": False,
        "properties": {
            "$type": {"type": "string", "enum": ["duration", "cubicBezier"]},
            "$value": {"$ref": "#/$defs/motionValue"},
            "$description": {"type": "string"},
        },
        "allOf": [
            {
                "if": {"properties": {"$type": {"const": "duration"}}, "required": ["$type"]},
                "then": {
                    "properties": {
                        "$value": {
                            "type": ["object", "string"],
                            "if": {"type": "object"},
                            "then": {"$ref": "#/$defs/durationDirectValue"},
                            "else": {"$ref": "#/$defs/aliasRef"},
                        }
                    }
                },
            },
            {
                "if": {"properties": {"$type": {"const": "cubicBezier"}}, "required": ["$type"]},
                "then": {
                    "properties": {
                        "$value": {
                            "type": ["array", "string"],
                            "if": {"type": "array"},
                            "then": {"$ref": "#/$defs/cubicBezierDirectValue"},
                            "else": {"$ref": "#/$defs/aliasRef"},
                        }
                    }
                },
            },
        ],
    },
    "motionGroup": _subgroup_schema("motionNode", ["duration", "cubicBezier"]),
    "motionNode": _subgroup_or_token("motionToken", "motionGroup"),
}

TOKENS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": list(TOKEN_PARTS),
    "additionalProperties": False,
    "properties": _TOKENS_ROOT_PROPS,
    "$defs": _TOKENS_DEFS,
}

PARTIAL_TOKENS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": _TOKENS_ROOT_PROPS,
    "$defs": _TOKENS_DEFS,
}


# ---------------------------------------------------------------- stage artifact schemas (all closed)

BRIEF_LINE_SPAN = closed(
    {
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
        "ref": {"type": "string", "pattern": r"^[^#\s]+#L\d+(-L\d+)?$"},
    },
    required=["start_line", "end_line", "ref"],
)

BRIEF_SECTION_ITEM = closed(
    {
        "number": {"type": "integer", "minimum": 1, "maximum": 7},
        "id": {
            "type": "string",
            "enum": [
                "what_it_is",
                "who_for",
                "where_and_how_used",
                "feel_and_anti_feel",
                "neighbours",
                "fixed_constraints",
                "taste_anchors",
            ],
        },
        "heading": NON_EMPTY,
        "required": {"type": "boolean"},
        "present": {"type": "boolean"},
        "empty": {"type": "boolean"},
        "body": {"type": "string"},
        "source": {"anyOf": [BRIEF_LINE_SPAN, {"type": "null"}]},
    },
    required=["number", "id", "heading", "required", "present", "empty", "body", "source"],
)

BRIEF_EXTRACTED_ITEM = closed(
    {
        "id": ID,
        "text": NON_EMPTY,
        "line": {"type": "integer", "minimum": 1},
        "source_ref": {"type": "string", "pattern": r"^[^#\s]+#L\d+(-L\d+)?$"},
    },
    required=["id", "text", "line", "source_ref"],
)

BRIEF_SCHEMA = closed(
    {
        "product": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,63}$"},
        "brief_path": NON_EMPTY,
        "brief_rel": NON_EMPTY,
        "sha256": SHA256,
        "render_surface": {"type": "string", "enum": ["app", "sample_screen"]},
        "sections": {
            "type": "array",
            "minItems": 7,
            "maxItems": 7,
            "items": BRIEF_SECTION_ITEM,
        },
        "constraints": {"type": "array", "items": BRIEF_EXTRACTED_ITEM},
        "taste_anchors": {"type": "array", "items": BRIEF_EXTRACTED_ITEM},
        "taste_anchors_empty": {"type": "boolean"},
    },
    required=[
        "product",
        "brief_path",
        "brief_rel",
        "sha256",
        "render_surface",
        "sections",
        "constraints",
        "taste_anchors",
        "taste_anchors_empty",
    ],
)

DIRECTION_EVIDENCE_SCHEMA = closed(
    {k: NON_EMPTY for k in DIRECTION_CLAIM_KEYS},
    required=list(DIRECTION_CLAIM_KEYS),
)

DIRECTION_DRAFT_ITEM_SCHEMA = closed(
    {
        "id": ID,
        "name": NON_EMPTY,
        "premise": NON_EMPTY,
        "anchor_hue_deg": {"type": "number", "minimum": 0.0, "maximum": 360.0},
        "chroma_intent": {"type": "string", "enum": list(CHROMA_INTENTS)},
        "neutral_temp": {"type": "string", "enum": list(NEUTRAL_TEMPS)},
        "type_family": NON_EMPTY,
        "why": NON_EMPTY,
        "evidence": DIRECTION_EVIDENCE_SCHEMA,
    },
    required=[
        "id",
        "name",
        "premise",
        "anchor_hue_deg",
        "chroma_intent",
        "neutral_temp",
        "type_family",
        "why",
        "evidence",
    ],
)

DIRECTION_CONTRACT_SCHEMA = DIRECTION_DRAFT_ITEM_SCHEMA

DIRECTIONS_DRAFT_SCHEMA = closed(
    {
        "recommended": ID,
        "directions": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": DIRECTION_DRAFT_ITEM_SCHEMA,
        },
    },
    required=["recommended", "directions"],
)

DIRECTION_ENTRY_SCHEMA = closed(
    {
        "id": ID,
        "name": NON_EMPTY,
        "premise": NON_EMPTY,
        "summary": NON_EMPTY,
        "anchor_hue_deg": {"type": "number", "minimum": 0.0, "maximum": 360.0},
        "chroma_intent": {"type": "string", "enum": list(CHROMA_INTENTS)},
        "neutral_temp": {"type": "string", "enum": list(NEUTRAL_TEMPS)},
        "type_family": {"type": "string", "enum": list(AVAILABLE_TYPE_FAMILIES)},
        "why": NON_EMPTY,
        "evidence": DIRECTION_EVIDENCE_SCHEMA,
        "tokens_file": NON_EMPTY,
        "design_md_file": NON_EMPTY,
    },
    required=[
        "id",
        "name",
        "premise",
        "summary",
        "anchor_hue_deg",
        "chroma_intent",
        "neutral_temp",
        "type_family",
        "why",
        "evidence",
        "tokens_file",
        "design_md_file",
    ],
)

DIRECTIONS_SCHEMA = closed(
    {
        "product": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,63}$"},
        "brief_sha256": SHA256,
        "recommended": ID,
        "directions": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": DIRECTION_ENTRY_SCHEMA,
        },
    },
    required=["product", "brief_sha256", "recommended", "directions"],
)

SURFACE_RECORD_SCHEMA = closed(
    {
        "kind": {"type": "string", "enum": list(SURFACE_KINDS)},
        "fallback": {"type": "boolean"},
        "reason": NON_EMPTY,
        "base_url": {"type": ["string", "null"]},
        "commit": {"type": ["string", "null"]},
        "ref": {"type": ["string", "null"]},
        "allow_red_commit": {"type": "boolean"},
        "sample_screen": {"type": ["string", "null"]},
    },
    required=[
        "kind",
        "fallback",
        "reason",
        "base_url",
        "commit",
        "ref",
        "allow_red_commit",
        "sample_screen",
    ],
)

PROOF_PREVIEW_ITEM = closed(
    {
        "direction": ID,
        "surface_kind": {"type": "string", "enum": list(SURFACE_KINDS)},
        "artifact": NON_EMPTY,
        "status": {"type": "string", "enum": ["ready"]},
    },
    required=["direction", "surface_kind", "artifact", "status"],
)

PROOF_ROW_SCHEMA = closed(
    {
        "id": {"type": "string", "pattern": r"^[a-z][a-z0-9_.-]{1,63}$"},
        "value": {"type": ["number", "string"]},
        "threshold": {"type": ["number", "string"]},
        "result": {"type": "string", "enum": ["pass", "fail"]},
        "evidence": NON_EMPTY,
        "token_a": {"type": "string"},
        "token_b": {"type": "string"},
        "theme": {"type": "string", "enum": ["light", "dark", "all"]},
    },
    required=["id", "value", "threshold", "result", "evidence", "token_a", "token_b", "theme"],
)

PROOF_DIRECTION_REPORT = closed(
    {
        "direction": ID,
        "name": NON_EMPTY,
        "tokens_file": NON_EMPTY,
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "rules": {"type": "array", "minItems": 8, "maxItems": 8, "items": PROOF_ROW_SCHEMA},
        "rows": {"type": "array", "minItems": 8, "items": PROOF_ROW_SCHEMA},
        "failing_rows": {"type": "array", "items": PROOF_ROW_SCHEMA},
    },
    required=["direction", "name", "tokens_file", "verdict", "rules", "rows", "failing_rows"],
)

PROOF_SCHEMA = closed(
    {
        "product": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,63}$"},
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "table_file": {"const": "03-proof/table.md"},
        "surface": SURFACE_RECORD_SCHEMA,
        "previews": {"type": "array", "minItems": 2, "items": PROOF_PREVIEW_ITEM},
        "directions": {"type": "array", "minItems": 2, "items": PROOF_DIRECTION_REPORT},
        "rows": {"type": "array", "minItems": 8, "items": PROOF_ROW_SCHEMA},
    },
    required=["product", "verdict", "table_file", "surface", "previews", "directions", "rows"],
)

GATE_PREDICTION = closed(
    {
        "choice": NON_EMPTY,
        "matched": {"type": "boolean"},
        "basis": NON_EMPTY,
    },
    required=["choice", "matched", "basis"],
)

GATE_DIRECTION_SCHEMA = closed(
    {
        "gate": {"const": "direction"},
        "choice": ID,
        "decided_by": {"type": "string", "enum": list(GATE_DECIDED_BY)},
        "owner_words": NON_EMPTY,
        "taste_anchors": {"type": "array", "items": NON_EMPTY},
        "source": NON_EMPTY,
        "reason": NON_EMPTY,
        "taste": {"type": "string", "enum": ["saved", "not-taste"]},
        "prediction": GATE_PREDICTION,
        "at": NON_EMPTY,
    },
    required=["gate", "choice", "decided_by", "source", "taste", "prediction", "at"],
)

BUILD_SCHEMA = closed(
    {
        "product": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,63}$"},
        "round": {"type": "integer", "minimum": 1},
        "direction": ID,
        "tokens_file": {"const": "04-build/tokens.json"},
        "design_md_file": {"const": "04-build/DESIGN.md"},
        "tokens_sha256": SHA256,
        "design_md_sha256": SHA256,
        "parts": {
            "type": "array",
            "minItems": len(TOKEN_PARTS),
            "maxItems": len(TOKEN_PARTS),
            "items": {"type": "string", "enum": list(TOKEN_PARTS)},
        },
    },
    required=[
        "product",
        "round",
        "direction",
        "tokens_file",
        "design_md_file",
        "tokens_sha256",
        "design_md_sha256",
        "parts",
    ],
)

CHECK_ROW_SCHEMA = closed(
    {
        "id": {"type": "string", "pattern": r"^[a-z][a-z0-9_.-]{1,63}$"},
        "result": {"type": "string", "enum": list(CHECK_RESULTS)},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "evidence": NON_EMPTY,
        "location": NON_EMPTY,
    },
    required=["id", "result", "severity", "evidence", "location"],
)

CHECKS_SCHEMA = closed(
    {
        "round": {"type": "integer", "minimum": 1},
        "verdict": {"type": "string", "enum": ["done", "revise"]},
        "surface": SURFACE_RECORD_SCHEMA,
        "summary": closed(
            {
                "total": {"type": "integer", "minimum": 1},
                "passed": {"type": "integer", "minimum": 0},
                "failed": {"type": "integer", "minimum": 0},
                "blockers": {"type": "integer", "minimum": 0},
            },
            required=["total", "passed", "failed", "blockers"],
        ),
        "checks": {"type": "array", "minItems": 1, "items": CHECK_ROW_SCHEMA},
    },
    required=["round", "verdict", "surface", "summary", "checks"],
)

GATE_FINAL_COMMENT = closed(
    {
        "id": NON_EMPTY,
        "place": {"type": "string"},
        "text": NON_EMPTY,
    },
    required=["id", "text"],
)

GATE_FINAL_SCHEMA = closed(
    {
        "gate": {"const": "final"},
        "round": {"type": "integer", "minimum": 1},
        "choice": {"type": "string", "enum": ["approve", "changes"]},
        "verdict": {"type": "string", "enum": ["approve", "changes"]},
        "decided_by": {"type": "string", "enum": list(GATE_DECIDED_BY)},
        "owner_words": NON_EMPTY,
        "source": NON_EMPTY,
        "reason": NON_EMPTY,
        "comments": {"type": "array", "items": GATE_FINAL_COMMENT},
        "taste": {"type": "string", "enum": ["saved", "not-taste"]},
        "prediction": GATE_PREDICTION,
        "at": NON_EMPTY,
    },
    required=[
        "gate",
        "round",
        "choice",
        "verdict",
        "decided_by",
        "source",
        "comments",
        "taste",
        "prediction",
        "at",
    ],
)

HANDOFF_TARGET_FILE = closed(
    {
        "source": NON_EMPTY,
        "target": {"type": "string", "enum": [".temper/design/DESIGN.md", ".temper/design/tokens.json"]},
        "sha256": SHA256,
    },
    required=["source", "target", "sha256"],
)

HANDOFF_SCHEMA = closed(
    {
        "product": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,63}$"},
        "round": {"type": "integer", "minimum": 1},
        "direction": ID,
        "approved_by": {"type": "string", "enum": list(GATE_DECIDED_BY)},
        "approved_at": NON_EMPTY,
        "landing_status": {"type": "string", "enum": ["ready_to_land", "landed"]},
        "files": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": HANDOFF_TARGET_FILE,
        },
    },
    required=[
        "product",
        "round",
        "direction",
        "approved_by",
        "approved_at",
        "landing_status",
        "files",
    ],
)

SCHEMAS: dict[str, tuple[str, dict[str, Any]]] = {
    "brief": ("01-brief/brief.json", BRIEF_SCHEMA),
    "tokens": ("tokens.json", TOKENS_SCHEMA),
    "directions_draft": ("02-directions/draft.json", DIRECTIONS_DRAFT_SCHEMA),
    "directions": ("02-directions/directions.json", DIRECTIONS_SCHEMA),
    "proof": ("03-proof/proof.json", PROOF_SCHEMA),
    "gate_direction": ("02-directions/gate_direction.json", GATE_DIRECTION_SCHEMA),
    "build": ("04-build/build.json", BUILD_SCHEMA),
    "checks": ("05-checks/round-<n>/checks.json", CHECKS_SCHEMA),
    "gate_final": ("05-checks/gate_final.json", GATE_FINAL_SCHEMA),
    "handoff": ("06-handoff/handoff.json", HANDOFF_SCHEMA),
}


# ---------------------------------------------------------------- validators

_UNEXPECTED_RE = re.compile(r"\('([^']+)' was unexpected\)")
_MISSING_REQ_RE = re.compile(r"^'([^']+)' is a required property$")


def _error_field(err: jsonschema.ValidationError) -> str:
    parts = [str(p) for p in err.absolute_path]
    if err.validator == "additionalProperties":
        m = _UNEXPECTED_RE.search(err.message)
        if m:
            parts.append(m.group(1))
    elif err.validator == "required":
        m = _MISSING_REQ_RE.match(err.message)
        if m:
            parts.append(m.group(1))
    return ".".join(parts) or "<root>"


def _schema_errors(schema: dict[str, Any], data: Any, label: str) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    out: list[str] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path]):
        field = _error_field(err)
        out.append(f"{label}: {field}: {err.message}")
    return out


def validate(name: str, data: Any, *, step: str | None = None, file_label: str | None = None) -> None:
    """Validate ``data`` against named closed schema ``name``; raise ContractError on any failure."""
    if name not in SCHEMAS:
        raise ContractError(f"unknown foundation contract {name!r}")
    default_label, schema = SCHEMAS[name]
    label = file_label or default_label
    who = step or name
    problems = _schema_errors(schema, data, label)
    if name == "tokens" and not problems:
        problems.extend(_semantic_token_errors(data, label, require_all_parts=True))
    if problems:
        raise ContractError(f"{who}: {len(problems)} problem(s): " + "; ".join(problems))


def _semantic_token_errors(
    data: dict[str, Any],
    label: str,
    *,
    require_all_parts: bool = True,
) -> list[str]:
    problems: list[str] = []
    present_parts = [p for p in TOKEN_PARTS if isinstance(data.get(p), dict)]
    target_parts = list(TOKEN_PARTS) if require_all_parts else present_parts

    paths: dict[str, tuple[str | None, Any]] = {}
    for part in target_parts:
        part_obj = data.get(part)
        if not isinstance(part_obj, dict):
            continue
        leaves = design_files.token_list({part: part_obj})
        if not leaves:
            problems.append(f"{label}: {part}: token part must contain at least one leaf token with $value")
            continue
        for dotted, tok_type, val in leaves:
            if tok_type is None:
                problems.append(
                    f"{label}: {dotted}.$type: leaf token has no $type (declare $type on the token or parent group)"
                )
                continue
            if tok_type == "color" and isinstance(val, dict) and val.get("colorSpace") == "srgb" and "components" in val:
                comps = val["components"]
                hex_val = val["hex"]
                if any(not (0 <= c <= 1) for c in comps):
                    problems.append(f"{label}: {dotted}.$value.components: srgb components must be in 0..1")
                elif any(abs(int(hex_val[1 + 2 * i : 3 + 2 * i], 16) / 255 - comps[i]) > 0.003 for i in range(3)):
                    problems.append(f"{label}: {dotted}.$value.hex: hex {hex_val} and srgb components disagree")
            elif tok_type != "color":
                val_err = design_files._check_value(tok_type, val)
                if val_err:
                    problems.append(f"{label}: {dotted}.$value: {val_err}")
            paths[dotted] = (tok_type, val)

    if "type" in target_parts and isinstance(data.get("type"), dict):
        fam = data["type"].get("family")
        if isinstance(fam, dict):
            fam_leaves = design_files.token_list({"family": fam})
            if not fam_leaves:
                problems.append(f"{label}: type.family: must declare at least one fontFamily token")

    for dotted, (_tok_type, val) in paths.items():
        refs: list[str] = []
        if isinstance(val, str):
            refs.append(val)
        elif isinstance(val, dict):
            refs.extend(x for x in val.values() if isinstance(x, str))
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    refs.extend(x for x in item.values() if isinstance(x, str))
        for ref in refs:
            m = design_files.ALIAS.match(ref)
            if m and m.group(1) not in paths:
                problems.append(f"{label}: {dotted}.$value: alias {ref} points at no token")
            elif m:
                resolved = design_files.resolve(data, ref)
                if resolved is None:
                    problems.append(f"{label}: {dotted}.$value: alias {ref} contains a cycle")

    return problems


def validate_tokens(
    data: Any,
    *,
    label: str = "tokens.json",
    file: str | None = None,
    step: str = "tokens",
    require_all_parts: bool = True,
) -> None:
    """Validate DTCG tokens.json against closed TOKENS_SCHEMA plus alias and leaf-type invariants."""
    effective_label = file or label
    schema = TOKENS_SCHEMA if require_all_parts else PARTIAL_TOKENS_SCHEMA
    problems = _schema_errors(schema, data, effective_label)
    if not problems and isinstance(data, dict):
        problems.extend(_semantic_token_errors(data, effective_label, require_all_parts=require_all_parts))
    if problems:
        raise ContractError(f"{step}: {len(problems)} problem(s): " + "; ".join(problems))


def _split_h3_subsections(section_body: str) -> dict[str, str]:
    subs: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in section_body.splitlines():
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            if current is not None:
                subs[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        subs[current] = "\n".join(buf).strip()
    return subs


def validate_design_md(
    text: str,
    *,
    product: str | None = None,
    label: str = "DESIGN.md",
    file: str | None = None,
    step: str = "design_md",
) -> dict[str, Any]:
    """Validate DESIGN.md against both design_files.parse_design_md and the foundation Direction contract.

    Requires:
      - '# <Product> design files' title and 'Product:', 'Updated:', 'Format: design-files v1' header lines;
      - All six top-level sections: Users, Direction, Tokens, Logo, Library, Approvals;
      - '## Direction' non-missing ('Status: draft' or 'Status: approved by ...') with non-empty subsections:
        '### Named direction', '### Why', '### How to use', '### What not to do';
      - '## Tokens' mirroring all six foundation token parts (colour, type, spacing, radius, elevation, motion)
        with non-missing status.
    """
    effective_label = file or label
    if not isinstance(text, str) or not text.strip():
        raise ContractError(f"{step}: 1 problem(s): {effective_label}: <root>: DESIGN.md is empty")

    parsed = design_files.parse_design_md(text)
    problems: list[str] = []

    if product is not None and parsed["header"].get("product") != product:
        problems.append(
            f"{effective_label}: Product: expected 'Product: {product}', got {parsed['header'].get('product')!r}"
        )

    sections = parsed["sections"]
    for sec in DESIGN_MD_SECTIONS:
        if sec not in sections:
            problems.append(f"{effective_label}: {sec}: missing required section '## {sec}'")

    for prob in parsed["problems"]:
        if any(f"missing required section '## {sec}'" in p for sec in DESIGN_MD_SECTIONS for p in problems if sec in prob):
            continue
        problems.append(f"{effective_label}: header: {prob}")

    if not design_files._valid_date(parsed["header"].get("updated", "")):
        problems.append(f"{effective_label}: Updated: header requires 'Updated: YYYY-MM-DD'")

    if "Direction" in sections:
        dir_status = parsed["parts"].get("direction")
        if dir_status is None:
            problems.append(
                f"{effective_label}: Direction: foundation DESIGN.md cannot leave '## Direction' as 'Status: missing'"
            )
        raw_subs = _split_h3_subsections(sections["Direction"])
        lower_map = {k.lower(): (k, v) for k, v in raw_subs.items()}
        for req_sub in DIRECTION_SUBSECTIONS:
            hit = lower_map.get(req_sub.lower())
            if hit is None:
                problems.append(
                    f"{effective_label}: Direction.{req_sub}: missing required subsection '### {req_sub}'"
                )
            elif not hit[1].strip():
                problems.append(
                    f"{effective_label}: Direction.{req_sub}: subsection '### {req_sub}' is empty"
                )

    if "Tokens" in sections:
        mirror = parsed["mirror"]
        for part in TOKEN_PARTS:
            if mirror.get(part) is None:
                problems.append(
                    f"{effective_label}: Tokens.{part}: '## Tokens' must declare draft or approved status for '{part}'"
                )

    if problems:
        raise ContractError(f"{step}: {len(problems)} problem(s): " + "; ".join(problems))

    parsed["direction_subsections"] = _split_h3_subsections(sections["Direction"])
    return parsed
