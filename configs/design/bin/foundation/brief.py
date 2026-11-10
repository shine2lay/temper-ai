"""Stage 1 (brief): read, validate, and extract <repo>/.temper/product/brief.md into 01-brief/brief.json.

Owner rules (2026-11-09):
  - The brief lives at <repo>/.temper/product/brief.md and is an input written outside this flow.
  - Stage 1 reads and validates it through Workspace (STEP_INPUTS['brief']) and NEVER writes or drafts brief.md.
  - A missing file fails loud immediately naming the resolved absolute path — no fallback, no draft, no skip.
  - Sections 1-6 are required and must be non-empty; missing or empty section 1-6 fails loud naming the section.
  - Section 7 (taste anchors) may be omitted or left empty (filled by the owner at gate_direction).
  - Section 6 constraints and Section 7 taste anchors are extracted into 01-brief/brief.json with 1-indexed
    source line numbers and .temper/README.md '<path>#L<n>' refs.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import contracts
from .contracts import ContractError
from .workspace import Workspace

DEFAULT_BRIEF_PATH = ".temper/product/brief.md"


class BriefError(ContractError):
    """Raised when the product brief is missing or violates the 7-section brief contract."""


@dataclass(frozen=True)
class BriefSectionSpec:
    number: int
    id: str
    title: str
    required: bool
    aliases: tuple[str, ...]


BRIEF_SECTIONS: tuple[BriefSectionSpec, ...] = (
    BriefSectionSpec(
        number=1,
        id="what_it_is",
        title="What it is",
        required=True,
        aliases=("what it is", "what this is", "what the product is"),
    ),
    BriefSectionSpec(
        number=2,
        id="who_for",
        title="Who for",
        required=True,
        aliases=("who for", "who it is for", "who its for", "who this is for", "audience", "users"),
    ),
    BriefSectionSpec(
        number=3,
        id="where_and_how_used",
        title="Where and how used",
        required=True,
        aliases=(
            "where and how used",
            "where and how it is used",
            "where and how its used",
            "where and how",
            "context of use",
        ),
    ),
    BriefSectionSpec(
        number=4,
        id="feel_and_anti_feel",
        title="How it should feel plus what it must not feel like",
        required=True,
        aliases=(
            "how it should feel plus what it must not feel like",
            "how it should feel and what it must not feel like",
            "how it should feel",
            "feel and what it must not feel like",
            "feel plus what it must not feel like",
        ),
    ),
    BriefSectionSpec(
        number=5,
        id="neighbours",
        title="The neighbours",
        required=True,
        aliases=("the neighbours", "neighbours", "the neighbors", "neighbors", "adjacent products"),
    ),
    BriefSectionSpec(
        number=6,
        id="fixed_constraints",
        title="What is fixed",
        required=True,
        aliases=("what is fixed", "whats fixed", "fixed constraints", "hard constraints", "fixed"),
    ),
    BriefSectionSpec(
        number=7,
        id="taste_anchors",
        title="Taste anchors",
        required=False,
        aliases=("taste anchors", "owner taste anchors", "taste"),
    ),
)

_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_LEADING_NUM_RE = re.compile(r"^(?:section\s+)?([1-9]\d*)\s*[.):\-–—]\s*(.+)$", re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")
_RENDER_SURFACE_MAP = {
    "app": "app",
    "sample": "sample_screen",
    "sample_screen": "sample_screen",
    "none": "sample_screen",
    "": "sample_screen",
}


def normalize_render_surface(raw: str | None) -> str:
    key = (raw or "app").strip().lower()
    if key not in _RENDER_SURFACE_MAP:
        raise ContractError(
            f"brief: invalid render_surface {raw!r}; expected one of 'app', 'sample', 'sample_screen', 'none'"
        )
    return _RENDER_SURFACE_MAP[key]


def _normalize_heading_key(raw_heading: str) -> str:
    text = raw_heading.strip()
    m = _LEADING_NUM_RE.match(text)
    if m:
        text = m.group(2).strip()
    text = re.sub(r"[()'\"`]", "", text.lower())
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


def _match_section_spec(raw_heading: str) -> BriefSectionSpec | None:
    norm = _normalize_heading_key(raw_heading)
    for spec in BRIEF_SECTIONS:
        if norm in spec.aliases:
            return spec
    if norm.startswith("how it should feel"):
        return BRIEF_SECTIONS[3]
    return None


def _strip_comments(text: str) -> str:
    return _HTML_COMMENT_RE.sub("", text)


def _format_ref(rel_path: str, start_line: int, end_line: int | None = None) -> str:
    if end_line is None or end_line <= start_line:
        return f"{rel_path}#L{start_line}"
    return f"{rel_path}#L{start_line}-L{end_line}"


def _extract_items(
    lines: list[tuple[int, str]],
    *,
    prefix: str,
    rel_path: str,
) -> list[dict[str, Any]]:
    """Extract bulleted or line-level items with 1-indexed source lines and <path>#L<n> refs."""
    items: list[dict[str, Any]] = []
    in_comment = False
    current_parts: list[str] = []
    start_ln = 0
    end_ln = 0
    saw_bullets = False

    def flush() -> None:
        nonlocal current_parts, start_ln, end_ln
        if not current_parts:
            return
        joined = " ".join(part.strip() for part in current_parts if part.strip()).strip()
        if joined:
            idx = len(items) + 1
            items.append(
                {
                    "id": f"{prefix}{idx}",
                    "text": joined,
                    "line": start_ln,
                    "source_ref": _format_ref(rel_path, start_ln, end_ln),
                }
            )
        current_parts = []
        start_ln = 0
        end_ln = 0

    cleaned_lines: list[tuple[int, str]] = []
    for line_no, raw in lines:
        line = raw
        if in_comment:
            if "-->" in line:
                line = line.split("-->", 1)[1]
                in_comment = False
            else:
                continue
        while "<!--" in line:
            before, after = line.split("<!--", 1)
            if "-->" in after:
                line = before + after.split("-->", 1)[1]
            else:
                line = before
                in_comment = True
                break
        cleaned_lines.append((line_no, line.rstrip()))

    for line_no, line in cleaned_lines:
        if not line.strip() or line.lstrip().startswith("#"):
            flush()
            continue
        m = _BULLET_RE.match(line)
        if m:
            saw_bullets = True
            flush()
            current_parts = [m.group(1)]
            start_ln = line_no
            end_ln = line_no
        elif saw_bullets and current_parts and (line.startswith("  ") or line.startswith("\t")):
            current_parts.append(line.strip())
            end_ln = line_no
        else:
            flush()
            current_parts = [line.strip()]
            start_ln = line_no
            end_ln = line_no

    flush()
    return items


def parse_brief(
    text: str,
    *,
    product: str,
    brief_path: Path,
    brief_rel: str,
    render_surface: str = "app",
) -> dict[str, Any]:
    """Parse and validate a 7-section brief.md string into the closed 01-brief/brief.json payload."""
    norm_surface = normalize_render_surface(render_surface)
    raw_lines = text.splitlines()

    raw_sections: list[tuple[str, int, list[tuple[int, str]]]] = []
    cur_heading: str | None = None
    cur_heading_line = 0
    cur_body: list[tuple[int, str]] = []

    for idx, line in enumerate(raw_lines, start=1):
        m = _H2_RE.match(line)
        if m:
            if cur_heading is not None:
                raw_sections.append((cur_heading, cur_heading_line, cur_body))
            cur_heading = m.group(1).strip()
            cur_heading_line = idx
            cur_body = []
        elif cur_heading is not None:
            cur_body.append((idx, line))
    if cur_heading is not None:
        raw_sections.append((cur_heading, cur_heading_line, cur_body))

    matched_by_num: dict[int, tuple[str, int, list[tuple[int, str]]]] = {}
    problems: list[str] = []

    for heading, heading_line, body_lines in raw_sections:
        spec = _match_section_spec(heading)
        if spec is None:
            problems.append(
                f"{brief_rel}: L{heading_line}: unknown brief section heading '## {heading}'"
            )
            continue
        if spec.number in matched_by_num:
            problems.append(
                f"{brief_rel}: section {spec.number} ({spec.id}: '{spec.title}'): duplicate section heading '## {heading}'"
            )
            continue
        matched_by_num[spec.number] = (heading, heading_line, body_lines)

    section_records: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    taste_anchors: list[dict[str, Any]] = []

    for spec in BRIEF_SECTIONS:
        hit = matched_by_num.get(spec.number)
        if hit is None:
            if spec.required:
                problems.append(
                    f"{brief_rel}: section {spec.number} ({spec.id}: '{spec.title}'): missing required section"
                )
            section_records.append(
                {
                    "number": spec.number,
                    "id": spec.id,
                    "heading": spec.title,
                    "required": spec.required,
                    "present": False,
                    "empty": True,
                    "body": "",
                    "source": None,
                }
            )
            continue

        heading, heading_line, body_lines = hit
        raw_body = "\n".join(ln for _, ln in body_lines)
        visible_body = _strip_comments(raw_body).strip()
        non_empty_lines = [ln_no for ln_no, ln in body_lines if _strip_comments(ln).strip()]
        end_line = non_empty_lines[-1] if non_empty_lines else heading_line
        is_empty = not bool(visible_body)

        if spec.required and is_empty:
            problems.append(
                f"{brief_rel}: section {spec.number} ({spec.id}: '{spec.title}'): required section is empty"
            )

        section_records.append(
            {
                "number": spec.number,
                "id": spec.id,
                "heading": heading,
                "required": spec.required,
                "present": True,
                "empty": is_empty,
                "body": visible_body,
                "source": {
                    "start_line": heading_line,
                    "end_line": end_line,
                    "ref": _format_ref(brief_rel, heading_line, end_line),
                },
            }
        )

        if spec.number == 6 and not is_empty:
            constraints = _extract_items(body_lines, prefix="C", rel_path=brief_rel)
        elif spec.number == 7 and not is_empty:
            taste_anchors = _extract_items(body_lines, prefix="T", rel_path=brief_rel)

    if problems:
        raise BriefError(f"brief: {len(problems)} problem(s): " + "; ".join(problems))

    payload: dict[str, Any] = {
        "product": product,
        "brief_path": str(brief_path.resolve()),
        "brief_rel": brief_rel,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "render_surface": norm_surface,
        "sections": section_records,
        "constraints": constraints,
        "taste_anchors": taste_anchors,
        "taste_anchors_empty": len(taste_anchors) == 0,
    }
    contracts.validate("brief", payload, step="brief")
    return payload


def run(
    ws: Workspace,
    *,
    product: str,
    brief_path: str | Path | None = None,
    render_surface: str = "app",
) -> dict[str, Any]:
    """Execute Stage 1 (brief): read and validate brief.md, write 01-brief/brief.json, never write brief.md."""
    raw_brief = str(brief_path).strip() if brief_path is not None and str(brief_path).strip() else DEFAULT_BRIEF_PATH
    norm_surface = normalize_render_surface(render_surface)

    extra: tuple[str, ...] = ()
    cand_rel = raw_brief.replace("\\", "/")
    while cand_rel.startswith("./"):
        cand_rel = cand_rel[2:]
    if cand_rel != DEFAULT_BRIEF_PATH:
        if Path(raw_brief).is_absolute():
            resolved_override = Path(raw_brief).resolve(strict=False)
            if resolved_override.is_relative_to(ws.repo_root):
                extra = (resolved_override.relative_to(ws.repo_root).as_posix(),)
            else:
                extra = (resolved_override.as_posix(),)
        else:
            extra = (cand_rel,)

    step_ws = ws.for_step("brief", extra_inputs=extra)
    resolved_brief = step_ws.resolve_input(raw_brief, step="brief", repo_input=True)

    if not resolved_brief.is_file():
        raise BriefError(
            f"brief: missing required product brief at {resolved_brief} "
            f"(expected {DEFAULT_BRIEF_PATH}; no fallback, draft, or skip allowed)"
        )

    text = step_ws.read_text(raw_brief, step="brief", repo_input=True)
    if resolved_brief.is_relative_to(ws.repo_root):
        brief_rel = resolved_brief.relative_to(ws.repo_root).as_posix()
    else:
        brief_rel = resolved_brief.name

    payload = parse_brief(
        text,
        product=product,
        brief_path=resolved_brief,
        brief_rel=brief_rel,
        render_surface=norm_surface,
    )

    step_ws.start(product)
    out_dir = step_ws.folder("brief")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "brief.json"
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    step_ws.mark("brief", "done", render_surface=norm_surface)

    return {
        "ok": True,
        "step": "brief",
        "product": product,
        "brief_path": str(resolved_brief),
        "brief_file": "01-brief/brief.json",
        "render_surface": norm_surface,
        "constraints_count": len(payload["constraints"]),
        "taste_anchors_count": len(payload["taste_anchors"]),
        "taste_anchors_empty": payload["taste_anchors_empty"],
    }
