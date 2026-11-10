"""Foundation Stage 2 (`directions`): fenced brief-to-directions contract, deterministic check, and finish.

Division of labour (fixed by plan):
- The model (`design_foundation_directions_v1`) reads ONLY the approved brief (`01-brief/brief.json`
  rendered into `02-directions/task.md`) and proposes 2-3 genuinely distinct named directions.
  For each direction it returns words and discrete choices (`id`, `name`, `premise`, `anchor_hue_deg`,
  `chroma_intent`, `neutral_temp`, `type_family`, `why`, and `evidence` quoting the brief lines each
  claim rests on). It never computes a ramp, a contrast figure, or a gamut clamp.
- `color.py` generates every ramp and token set from the direction's discrete choices.
- `proof.py` grades the generated token set against the 8-rule proof battery (`proof_thresholds.json`).
- `directions_check` deterministically enforces all 5 Stage 2 rules (`directions.count`,
  `directions.hue_separation`, `directions.type_family`, `directions.evidence`, `directions.proof`)
  and fails with the offending rule name(s).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DESIGN_BIN = Path(__file__).resolve().parent.parent
if str(DESIGN_BIN) not in sys.path:
    sys.path.insert(0, str(DESIGN_BIN))

import design_files  # noqa: E402

from foundation import color, contracts, proof  # noqa: E402
from foundation.workspace import Workspace  # noqa: E402

RULE_IDS: tuple[str, ...] = (
    "directions.count",
    "directions.hue_separation",
    "directions.type_family",
    "directions.evidence",
    "directions.proof",
)

MIN_DIRECTIONS: int = 2
MAX_DIRECTIONS: int = 3
MIN_HUE_SEPARATION_DEG: float = contracts.MIN_ANCHOR_HUE_SEPARATION_DEG

CHROMA_INTENT_PEAK: dict[str, float] = {
    "muted": 0.10,
    "balanced": 0.16,
    "crisp": 0.20,
    "vivid": 0.24,
}

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}$")
_LINE_REF_RE = re.compile(r"\bL(\d{1,3})\b")
_WS_RE = re.compile(r"\s+")


class DirectionsError(contracts.ContractError):
    """Raised when `directions_check` or `directions_finish` fails a Stage 2 rule."""


def circular_hue_distance(h1: float, h2: float) -> float:
    """Shortest angular distance in degrees on the 360-degree OKLCH hue circle (`[0, 180]`)."""
    diff = abs((float(h1) - float(h2)) % 360.0)
    return round(min(diff, 360.0 - diff), 4)


def _norm_text(s: str) -> str:
    return _WS_RE.sub(" ", s.strip()).lower()


def _brief_sha(brief_doc: dict[str, Any]) -> str:
    return str(brief_doc.get("sha256") or brief_doc.get("brief_sha256") or "")


def brief_lines(brief_doc: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract numbered verifiable lines (`L01`, `L02`, ...) from `01-brief/brief.json`."""
    raw_items: list[tuple[str, str]] = []
    sections = brief_doc.get("sections")
    if isinstance(sections, list):
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec_id = str(sec.get("id") or "section")
            body = str(sec.get("body") or "").strip()
            if not body:
                continue
            for line in body.splitlines():
                cleaned = line.strip()
                if cleaned.startswith(("- ", "* ")):
                    cleaned = cleaned[2:].strip()
                if cleaned:
                    raw_items.append((sec_id, cleaned))
    elif isinstance(sections, dict):
        for sec_id, val in sections.items():
            if isinstance(val, str) and val.strip():
                for line in val.splitlines():
                    cleaned = line.strip()
                    if cleaned.startswith(("- ", "* ")):
                        cleaned = cleaned[2:].strip()
                    if cleaned:
                        raw_items.append((str(sec_id), cleaned))
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        raw_items.append((str(sec_id), item.strip()))

    for key, tag in (("constraints", "fixed_constraints"), ("taste_anchors", "taste_anchors"), ("facts", "fact")):
        items = brief_doc.get(key)
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and str(it.get("text") or "").strip():
                    raw_items.append((tag, str(it["text"]).strip()))
                elif isinstance(it, str) and it.strip():
                    raw_items.append((tag, it.strip()))

    seen: set[str] = set()
    numbered: list[tuple[str, str]] = []
    for sec_id, text in raw_items:
        norm = _norm_text(text)
        if norm in seen:
            continue
        seen.add(norm)
        lid = f"L{len(numbered) + 1:02d}"
        numbered.append((lid, f"[{sec_id}] {text}"))
    return numbered


def evidence_matches_brief(citation: str, lines: list[tuple[str, str]]) -> tuple[bool, str]:
    """Verify that `citation` references a real brief line and quotes a verbatim substring (>= 6 chars)."""
    if not isinstance(citation, str) or not citation.strip():
        return False, "empty evidence string"
    text = citation.strip()
    line_map = {lid: body for lid, body in lines}
    full_corpus_norm = " || ".join(_norm_text(body) for _lid, body in lines)

    stripped = re.sub(r"^\s*L\d{1,3}\s*[:\-–—]\s*", "", text)
    stripped_no_sec = re.sub(r"^\s*\[[a-z_]+\]\s*", "", stripped)
    quote_norm = _norm_text(stripped_no_sec)

    refs = [f"L{int(m.group(1)):02d}" for m in _LINE_REF_RE.finditer(text)]
    for ref in refs:
        if ref not in line_map:
            return False, f"cites non-existent brief line {ref} (valid: L01..L{len(lines):02d})"

    if len(quote_norm) < 6:
        return False, f"evidence quote {text!r} is too short (< 6 chars of brief text)"

    if refs:
        for ref in refs:
            target_norm = _norm_text(line_map[ref])
            target_no_sec = _norm_text(re.sub(r"^\[[a-z_]+\]\s*", "", line_map[ref]))
            if quote_norm in target_norm or quote_norm in target_no_sec or target_no_sec in quote_norm:
                return True, ref
        for qm in re.finditer(r'["\']([^"\']{6,})["\']', text):
            sub_norm = _norm_text(qm.group(1))
            for ref in refs:
                target_norm = _norm_text(line_map[ref])
                if sub_norm in target_norm:
                    return True, ref
        return False, f"citation {text!r} does not match the text of {', '.join(refs)}"

    for lid, body in lines:
        body_norm = _norm_text(body)
        body_no_sec = _norm_text(re.sub(r"^\[[a-z_]+\]\s*", "", body))
        if quote_norm in body_norm or quote_norm in body_no_sec or (len(body_no_sec) >= 6 and body_no_sec in quote_norm):
            return True, lid
    for qm in re.finditer(r'["\']([^"\']{6,})["\']', text):
        sub_norm = _norm_text(qm.group(1))
        if sub_norm in full_corpus_norm:
            return True, "quote"

    return False, f"no brief line in 01-brief/brief.json backs claim evidence {text!r}"


def parse_model_json(raw: Any) -> dict[str, Any]:
    """Parse strict JSON object from model output, rejecting free prose around or instead of JSON."""
    if isinstance(raw, dict):
        inner = raw.get("draft")
        return dict(inner) if isinstance(inner, dict) and "directions" in inner else dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        raise DirectionsError("directions model output is empty; expected a JSON object")
    s = raw.strip()
    if s.startswith("```"):
        m = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", s, flags=re.DOTALL)
        if not m:
            raise DirectionsError("directions model output contains prose outside code fence; reject free prose")
        s = m.group(1).strip()
    if not (s.startswith("{") and s.endswith("}")):
        raise DirectionsError("directions model output must be a single JSON object with no free prose")
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError as exc:
        raise DirectionsError(f"directions model output is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise DirectionsError("directions model output root must be a JSON object")
    if isinstance(parsed.get("draft"), dict) and "directions" in parsed["draft"]:
        return dict(parsed["draft"])
    return parsed


def build_direction_tokens(
    product: str,
    direction: dict[str, Any],
    *,
    date: str | None = None,
) -> dict[str, Any]:
    """Build a complete DTCG `tokens.json` for `direction` using `color.py` (no colour math here)."""
    hue_deg = float(direction["anchor_hue_deg"])
    neutral_temp = str(direction["neutral_temp"])
    chroma_intent = str(direction["chroma_intent"])
    type_family = str(direction["type_family"])

    neutral_hue = contracts.NEUTRAL_TEMP_HUES.get(neutral_temp, 250.0)
    peak_chroma = CHROMA_INTENT_PEAK.get(chroma_intent, 0.16)
    sans_stack, mono_stack = contracts.TYPE_FAMILY_STACKS.get(
        type_family,
        ([type_family, "system-ui", "sans-serif"], ["IBM Plex Mono", "ui-monospace", "monospace"]),
    )

    tokens = color.generate_tokens(
        product,
        anchor_hues={"accent": hue_deg, "neutral": neutral_hue},
        status="draft",
        date=date or design_files.today(),
        font_sans=list(sans_stack),
        font_mono=list(mono_stack),
    )
    tokens["colour"]["light"]["ramp"]["accent"] = color.generate_ramp(
        hue_deg, peak_chroma=peak_chroma, theme="light", role="accent"
    )
    tokens["colour"]["dark"]["ramp"]["accent"] = color.generate_ramp(
        hue_deg, peak_chroma=peak_chroma, theme="dark", role="accent"
    )
    return tokens


def render_direction_design_md(
    product: str,
    brief_doc: dict[str, Any],
    direction: dict[str, Any],
    tokens: dict[str, Any],
    *,
    date: str | None = None,
) -> str:
    """Render a candidate `02-directions/<id>/DESIGN.md` satisfying `contracts.validate_design_md`."""
    stamp_date = date or design_files.today()
    did = str(direction["id"])
    name = str(direction["name"])
    premise = str(direction["premise"])
    hue_deg = float(direction["anchor_hue_deg"])
    chroma_intent = str(direction["chroma_intent"])
    neutral_temp = str(direction["neutral_temp"])
    type_family = str(direction["type_family"])
    why = str(direction["why"])
    ev = direction.get("evidence") or {}

    sec_map: dict[str, str] = {}
    sections = brief_doc.get("sections")
    if isinstance(sections, list):
        for s in sections:
            if isinstance(s, dict) and s.get("id"):
                sec_map[str(s["id"])] = str(s.get("body") or "").strip()
    elif isinstance(sections, dict):
        for k, v in sections.items():
            sec_map[str(k)] = str(v or "").strip()

    who_for = sec_map.get("who_for") or sec_map.get("audience") or "Grounded from .temper/product/brief.md."
    where_used = sec_map.get("where_and_how_used") or sec_map.get("job") or ""
    users_text = f"{who_for} {where_used}".strip()

    light_acc = tokens["colour"]["light"]["semantic"]["accent"]["solid"]["$value"]["hex"]
    dark_acc = tokens["colour"]["dark"]["semantic"]["accent"]["solid"]["$value"]["hex"]
    mono_family = tokens["type"]["family"]["mono"]["$value"][0]
    mirror_lines = "\n".join(f"- {part}: draft" for part in contracts.TOKEN_PARTS)

    named_block = (
        f"{name} (direction `{did}`): {premise}\n"
        f"- Anchor hue: `{hue_deg:.1f} deg` OKLCH (`{chroma_intent}` chroma intent; light solid `{light_acc}`, dark solid `{dark_acc}`). Evidence: {ev.get('anchor_hue_deg', '')}\n"
        f"- Neutral temperature: `{neutral_temp}` (`{contracts.NEUTRAL_TEMP_HUES.get(neutral_temp, 250.0):.1f} deg`). Evidence: {ev.get('neutral_temp', '')}\n"
        f"- Type family: `{type_family}` paired with `{mono_family}`. Evidence: {ev.get('type_family', '')}"
    )
    why_block = (
        f"{why}\n"
        f"- Premise evidence: {ev.get('premise', '')}\n"
        f"- Why evidence: {ev.get('why', '')}\n"
        f"- Chroma intent evidence: {ev.get('chroma_intent', '')}"
    )
    how_to_use = (
        f"Lead with `{neutral_temp}` neutral surfaces and `{type_family}` hierarchy; reserve the `{hue_deg:.1f} deg` "
        f"`{chroma_intent}` accent (`colour.{{light,dark}}.semantic.accent.solid`) for the single primary action per view, "
        f"and use `{mono_family}` (`tabular-nums`) for every quantitative and financial comparison."
    )
    what_not_to_do = (
        "Never drift to generic AI purple/indigo gradients, never stack competing primary buttons in the same view, "
        "and never rely on hue alone to distinguish positive (`good`) from loss/exposure (`risk`)."
    )

    lines = [
        f"# {product.capitalize()} design files",
        "",
        f"Product: {product}",
        f"Updated: {stamp_date}",
        f"Format: {contracts.FORMAT}",
        "",
        "## Users",
        "Status: draft",
        "",
        "### Primary users",
        users_text,
        "",
        "## Direction",
        "Status: draft",
        "",
        "### Named direction",
        named_block,
        "",
        "### Why",
        why_block,
        "",
        "### How to use",
        how_to_use,
        "",
        "### What not to do",
        what_not_to_do,
        "",
        "## Tokens",
        "Values live in tokens.json (DTCG 2025.10); each part's status:",
        mirror_lines,
        "",
        "## Logo",
        "Status: missing",
        "",
        "## Library",
        "Status: missing",
        "",
        "## Approvals",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_task_md(brief_doc: dict[str, Any]) -> str:
    """Render the fenced Stage 2 prompt (`02-directions/task.md`) from `01-brief/brief.json` only."""
    product = str(brief_doc.get("product") or "product")
    brief_sha = _brief_sha(brief_doc)
    lines = brief_lines(brief_doc)
    numbered_block = "\n".join(f"- `{lid}:` {body}" for lid, body in lines)
    families_list = ", ".join(f'"{f}"' for f in contracts.AVAILABLE_TYPE_FAMILIES)
    chroma_list = ", ".join(f'"{c}"' for c in contracts.CHROMA_INTENTS)
    neutral_list = ", ".join(f'"{n}"' for n in contracts.NEUTRAL_TEMPS)

    return (
        f"# Foundation Stage 2 (`directions_read`) — `{product}`\n\n"
        "Propose **2 or 3 genuinely distinct visual directions** for Gate 1 from the approved brief below.\n"
        "You have NO workspace or repository access. Do not compute colour ramps, hex codes, contrast ratios,\n"
        "or gamut clamps — `foundation/color.py` computes all ramps/tokens from your discrete choices and\n"
        "`foundation/proof.py` grades them.\n\n"
        f"## Approved brief (`01-brief/brief.json`, sha256 `{brief_sha}`)\n\n"
        f"{numbered_block}\n\n"
        "## Hard rules enforced by `directions_check`\n\n"
        "1. **`directions.count`**: Return `2` or `3` directions (`id` values `\"a\"`, `\"b\"`, and optional `\"c\"`), and set `recommended` to one of those ids.\n"
        "2. **`directions.hue_separation`**: Every pair of directions must have `anchor_hue_deg` separated by **at least 40.0 degrees** on the 360-degree OKLCH hue circle (`min(|h1 - h2|, 360 - |h1 - h2|) >= 40.0`). Near-variants (such as purple and indigo within 40 degrees) are rejected.\n"
        f"3. **`directions.type_family`**: `type_family` must be one of the available families: `[{families_list}]`. `chroma_intent` must be one of `[{chroma_list}]`. `neutral_temp` must be one of `[{neutral_list}]`. Do not default every direction to `Inter`.\n"
        "4. **`directions.evidence`**: Every direction must include an `evidence` object with all 6 keys (`premise`, `anchor_hue_deg`, `chroma_intent`, `neutral_temp`, `type_family`, `why`). Each value must cite a line id (`L01`..`L"
        f"{len(lines):02d}`) and quote a verbatim substring (>= 6 characters) from that line in the approved brief above. Any ungrounded claim fails.\n"
        "5. **`directions.proof`**: Each direction's discrete choices are compiled by `color.py` and graded by `proof.py` (`contrast.text`, `contrast.ui`, `signal.separation`, `gamut.srgb`, `scale.spacing`, `scale.type`, `type.fallback`, `tokens.schema`).\n\n"
        "## Required output format (strict JSON only — NO prose, NO markdown fences)\n\n"
        "{\n"
        '  "recommended": "a",\n'
        '  "directions": [\n'
        "    {\n"
        '      "id": "a",\n'
        '      "name": "<short distinct direction name>",\n'
        '      "premise": "<one-sentence visual and UX premise grounded in the brief>",\n'
        '      "anchor_hue_deg": 155.0,\n'
        '      "chroma_intent": "balanced",\n'
        '      "neutral_temp": "cool",\n'
        '      "type_family": "IBM Plex Sans",\n'
        '      "why": "<why this direction fits the audience, job, and constraints>",\n'
        '      "evidence": {\n'
        '        "premise": "L01: <verbatim substring from L01>",\n'
        '        "anchor_hue_deg": "L04: <verbatim substring from L04>",\n'
        '        "chroma_intent": "L04: <verbatim substring from L04>",\n'
        '        "neutral_temp": "L02: <verbatim substring from L02>",\n'
        '        "type_family": "L05: <verbatim substring from L05>",\n'
        '        "why": "L03: <verbatim substring from L03>"\n'
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )


def render_revise_task_md(
    brief_doc: dict[str, Any],
    draft_obj: dict[str, Any],
    problems: list[dict[str, Any]],
) -> str:
    """Render bounded revision task prompt for `directions_revise` when `directions_check` finds problems."""
    base = render_task_md(brief_doc)
    prob_lines = "\n".join(
        f"- **[{p['rule']}]** (`{p.get('direction') or 'root'}` / `{p.get('field') or '*'}`): {p['message']}"
        for p in problems
    )
    prev_json = json.dumps(draft_obj, indent=2, ensure_ascii=False)
    return (
        f"{base}\n"
        "## Deterministic `directions_check` failures on your previous draft (fix ALL of these)\n\n"
        f"{prob_lines}\n\n"
        "## Previous draft JSON\n\n"
        f"{prev_json}\n\n"
        "Return the corrected JSON object only (no prose, no markdown fences).\n"
    )


def evaluate_directions(
    ws: Workspace | Path | str,
    *,
    draft: dict[str, Any] | None = None,
    use_existing_tokens: bool = True,
) -> dict[str, Any]:
    """Run all 5 deterministic Stage 2 checks on `draft` (or `02-directions/draft.json`)."""
    if not isinstance(ws, Workspace):
        ws = Workspace(Path(ws))
    step_ws = ws.for_step("directions_check")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    contracts.validate("brief", brief_doc, step="directions_check")
    product = str(brief_doc["product"])
    b_lines = brief_lines(brief_doc)

    if draft is None:
        draft_obj = step_ws.read_json("02-directions/draft.json")
    else:
        draft_obj = draft

    if not isinstance(draft_obj, dict):
        raise DirectionsError("directions draft must be a JSON object")

    raw_dirs = draft_obj.get("directions")
    rec = draft_obj.get("recommended")

    problems: list[dict[str, Any]] = []
    by_rule_problems: dict[str, list[dict[str, Any]]] = {rid: [] for rid in RULE_IDS}

    def _add_problem(rule: str, direction_id: str, field: str, message: str) -> None:
        item = {
            "rule": rule,
            "direction": direction_id,
            "field": field,
            "message": message,
        }
        problems.append(item)
        by_rule_problems[rule].append(item)

    extra_root = sorted(set(draft_obj.keys()) - {"recommended", "directions"})
    if extra_root:
        _add_problem(
            "directions.count",
            "root",
            "root",
            f"unexpected root properties in directions draft: {extra_root}",
        )

    # 1. directions.count (2..3 directions, valid unique ids, valid recommended)
    dir_list: list[dict[str, Any]] = []
    if not isinstance(raw_dirs, list):
        _add_problem("directions.count", "root", "directions", "directions must be a list of 2 to 3 direction objects")
    else:
        for idx, item in enumerate(raw_dirs):
            if isinstance(item, dict):
                dir_list.append(item)
            else:
                _add_problem("directions.count", f"#{idx}", "direction", "each direction entry must be a JSON object")
        n_dirs = len(dir_list)
        if n_dirs < MIN_DIRECTIONS or n_dirs > MAX_DIRECTIONS:
            _add_problem(
                "directions.count",
                "root",
                "directions",
                f"expected {MIN_DIRECTIONS}..{MAX_DIRECTIONS} directions, got {n_dirs}",
            )

    seen_ids: list[str] = []
    for idx, d in enumerate(dir_list):
        did = d.get("id")
        if not isinstance(did, str) or not _ID_RE.match(did):
            _add_problem("directions.count", str(did or f"#{idx}"), "id", f"invalid direction id {did!r}")
        elif did in seen_ids:
            _add_problem("directions.count", did, "id", f"duplicate direction id {did!r}")
        else:
            seen_ids.append(did)

    if not isinstance(rec, str) or (seen_ids and rec not in seen_ids):
        _add_problem(
            "directions.count",
            "root",
            "recommended",
            f"recommended {rec!r} must name one of the direction ids {seen_ids}",
        )

    # 2. directions.hue_separation (pairwise circular distance >= 40.0 deg in OKLCH hue)
    hue_entries: list[tuple[str, float]] = []
    for idx, d in enumerate(dir_list):
        did = str(d.get("id") or f"#{idx}")
        h_val = d.get("anchor_hue_deg")
        if not isinstance(h_val, (int, float)) or isinstance(h_val, bool) or not (0.0 <= float(h_val) <= 360.0):
            _add_problem(
                "directions.hue_separation",
                did,
                "anchor_hue_deg",
                f"direction {did!r} anchor_hue_deg {h_val!r} must be a number in [0, 360]",
            )
        else:
            hue_entries.append((did, float(h_val)))

    min_pair_dist: float | None = None
    closest_pair: tuple[str, str, float, float] | None = None
    for i in range(len(hue_entries)):
        for j in range(i + 1, len(hue_entries)):
            id_a, h_a = hue_entries[i]
            id_b, h_b = hue_entries[j]
            dist = circular_hue_distance(h_a, h_b)
            if min_pair_dist is None or dist < min_pair_dist:
                min_pair_dist = dist
                closest_pair = (id_a, id_b, h_a, h_b)
            if dist < MIN_HUE_SEPARATION_DEG:
                _add_problem(
                    "directions.hue_separation",
                    f"{id_a},{id_b}",
                    "anchor_hue_deg",
                    (
                        f"directions {id_a!r} ({h_a:g} deg) and {id_b!r} ({h_b:g} deg) are only "
                        f"{dist:g} deg apart in OKLCH hue (need >= {MIN_HUE_SEPARATION_DEG:g} deg)"
                    ),
                )

    # 3. directions.type_family (type_family in AVAILABLE_TYPE_FAMILIES; chroma_intent & neutral_temp in closed sets)
    checked_families: list[str] = []
    for idx, d in enumerate(dir_list):
        did = str(d.get("id") or f"#{idx}")
        tf = d.get("type_family")
        if not isinstance(tf, str) or tf not in contracts.AVAILABLE_TYPE_FAMILIES:
            _add_problem(
                "directions.type_family",
                did,
                "type_family",
                (
                    f"direction {did!r} type_family {tf!r} is not in AVAILABLE_TYPE_FAMILIES "
                    f"{list(contracts.AVAILABLE_TYPE_FAMILIES)}"
                ),
            )
        else:
            checked_families.append(tf)

        ci = d.get("chroma_intent")
        if not isinstance(ci, str) or ci not in contracts.CHROMA_INTENTS:
            _add_problem(
                "directions.type_family",
                did,
                "chroma_intent",
                f"direction {did!r} chroma_intent {ci!r} must be one of {list(contracts.CHROMA_INTENTS)}",
            )

        nt = d.get("neutral_temp")
        if not isinstance(nt, str) or nt not in contracts.NEUTRAL_TEMPS:
            _add_problem(
                "directions.type_family",
                did,
                "neutral_temp",
                f"direction {did!r} neutral_temp {nt!r} must be one of {list(contracts.NEUTRAL_TEMPS)}",
            )

    # 4. directions.evidence (every claim backed by a real brief line; no ungrounded claims or extra keys)
    allowed_dir_keys = {
        "id",
        "name",
        "premise",
        "anchor_hue_deg",
        "chroma_intent",
        "neutral_temp",
        "type_family",
        "why",
        "evidence",
    }
    verified_citations = 0
    for idx, d in enumerate(dir_list):
        did = str(d.get("id") or f"#{idx}")
        extra_keys = sorted(set(d.keys()) - allowed_dir_keys)
        if extra_keys:
            _add_problem(
                "directions.evidence",
                did,
                "direction",
                f"direction {did!r} contains unexpected properties {extra_keys}",
            )
        for text_key in ("name", "premise", "why"):
            val = d.get(text_key)
            if not isinstance(val, str) or not val.strip():
                _add_problem(
                    "directions.evidence",
                    did,
                    text_key,
                    f"direction {did!r} field {text_key!r} must be a non-empty string",
                )

        ev = d.get("evidence")
        if not isinstance(ev, dict):
            _add_problem(
                "directions.evidence",
                did,
                "evidence",
                f"direction {did!r} missing required evidence object",
            )
            continue

        extra_ev = sorted(set(ev.keys()) - set(contracts.DIRECTION_CLAIM_KEYS))
        if extra_ev:
            _add_problem(
                "directions.evidence",
                did,
                "evidence",
                f"direction {did!r} evidence has unexpected keys {extra_ev}",
            )

        for claim_key in contracts.DIRECTION_CLAIM_KEYS:
            raw_cite = ev.get(claim_key)
            if not isinstance(raw_cite, str) or not raw_cite.strip():
                _add_problem(
                    "directions.evidence",
                    did,
                    f"evidence.{claim_key}",
                    f"direction {did!r} claim {claim_key!r} has no brief line evidence behind it",
                )
                continue
            ok, reason = evidence_matches_brief(raw_cite, b_lines)
            if not ok:
                _add_problem(
                    "directions.evidence",
                    did,
                    f"evidence.{claim_key}",
                    f"direction {did!r} claim {claim_key!r} ungrounded in brief: {reason}",
                )
            else:
                verified_citations += 1

    # 5. directions.proof (generate tokens via color.py — or load pre-built case tokens when present — and grade via proof.py)
    generated_tokens: dict[str, dict[str, Any]] = {}
    proof_reports: dict[str, dict[str, Any]] = {}
    for idx, d in enumerate(dir_list):
        did = str(d.get("id") or f"#{idx}")
        tok_rel = f"02-directions/{did}/tokens.json"
        tok_obj: dict[str, Any] | None = None
        if use_existing_tokens and (step_ws.path / tok_rel).is_file():
            try:
                loaded = step_ws.read_json(tok_rel)
                if isinstance(loaded, dict):
                    tok_obj = loaded
            except Exception as exc:
                _add_problem(
                    "directions.proof",
                    did,
                    "tokens_file",
                    f"direction {did!r} {tok_rel} unreadable: {exc}",
                )
                continue

        if tok_obj is None:
            if (
                isinstance(d.get("anchor_hue_deg"), (int, float))
                and not isinstance(d.get("anchor_hue_deg"), bool)
                and 0.0 <= float(d["anchor_hue_deg"]) <= 360.0
                and isinstance(d.get("chroma_intent"), str)
                and d.get("chroma_intent") in contracts.CHROMA_INTENTS
                and isinstance(d.get("neutral_temp"), str)
                and d.get("neutral_temp") in contracts.NEUTRAL_TEMPS
                and isinstance(d.get("type_family"), str)
                and d.get("type_family") in contracts.AVAILABLE_TYPE_FAMILIES
            ):
                tok_obj = build_direction_tokens(product, d)

        if tok_obj is not None:
            generated_tokens[did] = tok_obj
            rep = proof.evaluate_tokens(tok_obj)
            proof_reports[did] = rep
            if rep["verdict"] != "pass":
                failed_rids = ", ".join(rep["failing_rules"])
                first_ev = rep["failing_rows"][0]["evidence"] if rep["failing_rows"] else "proof failed"
                _add_problem(
                    "directions.proof",
                    did,
                    "proof",
                    f"direction {did!r} generated ramps/tokens failed proof.py [{failed_rids}]: {first_ev}",
                )

    checks: list[dict[str, Any]] = []
    for rid in RULE_IDS:
        r_probs = by_rule_problems[rid]
        passed = len(r_probs) == 0
        if rid == "directions.count":
            measured: Any = len(dir_list)
            threshold: Any = f"{MIN_DIRECTIONS}..{MAX_DIRECTIONS}"
            ev_str = (
                f"{len(dir_list)} directions ({', '.join(seen_ids)}), recommended={rec!r}"
                if passed
                else r_probs[0]["message"]
            )
        elif rid == "directions.hue_separation":
            measured = min_pair_dist if min_pair_dist is not None else 0.0
            threshold = f">={MIN_HUE_SEPARATION_DEG:g} deg"
            if passed and closest_pair is not None:
                ev_str = (
                    f"min pairwise hue separation {min_pair_dist:g} deg between "
                    f"{closest_pair[0]!r} ({closest_pair[2]:g} deg) and {closest_pair[1]!r} ({closest_pair[3]:g} deg) "
                    f"(need >= {MIN_HUE_SEPARATION_DEG:g} deg)"
                )
            elif passed:
                ev_str = "all direction pairs meet minimum OKLCH hue separation"
            else:
                ev_str = r_probs[0]["message"]
        elif rid == "directions.type_family":
            measured = checked_families
            threshold = list(contracts.AVAILABLE_TYPE_FAMILIES)
            ev_str = (
                f"all type families in available set: {checked_families}"
                if passed
                else r_probs[0]["message"]
            )
        elif rid == "directions.evidence":
            measured = verified_citations
            threshold = len(dir_list) * len(contracts.DIRECTION_CLAIM_KEYS)
            ev_str = (
                f"all {verified_citations} direction claims backed by verbatim brief lines"
                if passed
                else r_probs[0]["message"]
            )
        else:
            measured = {did: rep["verdict"] for did, rep in proof_reports.items()}
            threshold = "all directions pass proof.py (8/8 rules)"
            ev_str = (
                f"all {len(proof_reports)} direction token sets pass proof.py"
                if passed
                else r_probs[0]["message"]
            )
        checks.append(
            {
                "id": rid,
                "passed": passed,
                "result": "pass" if passed else "fail",
                "measured": measured,
                "threshold": threshold,
                "evidence": ev_str,
            }
        )

    failing_rules = [c["id"] for c in checks if not c["passed"]]
    verdict = "pass" if not failing_rules else "fail"
    revise_task = render_revise_task_md(brief_doc, draft_obj, problems) if problems else ""

    return {
        "product": product,
        "verdict": verdict,
        "failing_rules": failing_rules,
        "checks": checks,
        "problems": problems,
        "revise_task": revise_task,
        "generated_tokens": generated_tokens,
        "proof_reports": {
            did: {
                "verdict": rep["verdict"],
                "failing_rules": rep["failing_rules"],
                "totals": rep["totals"],
            }
            for did, rep in proof_reports.items()
        },
    }


def directions_collect(ws: Workspace) -> dict[str, Any]:
    """Prepare `02-directions/task.md` from `01-brief/brief.json`, or skip if valid prior work exists."""
    step_ws = ws.for_step("directions_collect")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    contracts.validate("brief", brief_doc, step="directions_collect")
    product = str(brief_doc["product"])
    brief_sha = _brief_sha(brief_doc)

    # Rule 11-04 / 11-08: skip stage if valid prior work matching current brief sha256 already exists
    directions_path = step_ws.path / "02-directions" / "directions.json"
    if directions_path.is_file():
        try:
            existing = json.loads(directions_path.read_text(encoding="utf-8"))
            contracts.validate("directions", existing)
        except (OSError, json.JSONDecodeError, contracts.ContractError, ValueError, TypeError) as exc:
            raise DirectionsError(
                f"DirectionsError: corrupt prior directions record at {directions_path}: {exc}"
            ) from exc
        if existing.get("brief_sha256") == brief_sha:
            all_valid = True
            for entry in existing.get("directions", []):
                tok_rel = entry["tokens_file"]
                md_rel = entry["design_md_file"]
                tok_path = step_ws.path / tok_rel
                md_path = step_ws.path / md_rel
                if not (tok_path.is_file() and md_path.is_file()):
                    all_valid = False
                    break
                try:
                    tok = json.loads(tok_path.read_text(encoding="utf-8"))
                    contracts.validate_tokens(tok, label=tok_rel)
                    tok_eval = proof.evaluate_tokens(tok)
                except (
                    OSError,
                    json.JSONDecodeError,
                    contracts.ContractError,
                    ValueError,
                    KeyError,
                    TypeError,
                ) as exc:
                    raise DirectionsError(
                        f"DirectionsError: corrupt prior directions tokens at {tok_path}: {exc}"
                    ) from exc
                if tok_eval["verdict"] != "pass":
                    all_valid = False
                    break
                try:
                    md = md_path.read_text(encoding="utf-8")
                    contracts.validate_design_md(md, label=md_rel, product=product)
                except (OSError, contracts.ContractError, ValueError, TypeError) as exc:
                    raise DirectionsError(
                        f"DirectionsError: corrupt prior directions DESIGN.md at {md_path}: {exc}"
                    ) from exc
            if all_valid:
                if step_ws.run_file.is_file():
                    step_ws.mark("directions_collect", "reused", note="reused valid 02-directions/directions.json")
                return {
                    "ok": True,
                    "step": "directions_collect",
                    "status": "reused",
                    "model": "no",
                    "product": product,
                    "task": "",
                }

    task_md = render_task_md(brief_doc)
    out_dir = step_ws.folder("directions")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "task.md").write_text(task_md, encoding="utf-8")
    if step_ws.run_file.is_file():
        step_ws.mark("directions_collect", "done")
    return {
        "ok": True,
        "step": "directions_collect",
        "status": "done",
        "model": "yes",
        "product": product,
        "task": task_md,
    }


def directions_check(
    ws: Workspace,
    *,
    draft: dict[str, Any] | str | None = None,
    allow_retry: bool = False,
    use_existing_tokens: bool = True,
) -> dict[str, Any]:
    """Validate `02-directions/draft.json` against the 5 Stage 2 rules and grade generated ramps with `proof.py`."""
    step_ws = ws.for_step("directions_check")
    out_dir = step_ws.folder("directions")
    out_dir.mkdir(parents=True, exist_ok=True)

    if draft is not None and draft != "":
        try:
            draft_obj = parse_model_json(draft)
        except DirectionsError as exc:
            if allow_retry:
                brief_doc = step_ws.read_json("01-brief/brief.json")
                prob = {"rule": "directions.count", "direction": "root", "field": "root", "message": str(exc)}
                rev_md = render_revise_task_md(brief_doc, {}, [prob])
                return {
                    "ok": True,
                    "step": "directions_check",
                    "status": "retry",
                    "valid": "no",
                    "verdict": "retry",
                    "failing_rules": ["directions.count"],
                    "problems": [prob],
                    "revise_task": rev_md,
                }
            raise
        (out_dir / "draft.json").write_text(
            json.dumps(draft_obj, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        draft_obj = step_ws.read_json("02-directions/draft.json")

    report = evaluate_directions(ws, draft=draft_obj, use_existing_tokens=use_existing_tokens)
    check_doc = {
        "product": report["product"],
        "verdict": report["verdict"],
        "failing_rules": report["failing_rules"],
        "checks": report["checks"],
        "problems": report["problems"],
        "proof_reports": report["proof_reports"],
    }
    (out_dir / "check.json").write_text(
        json.dumps(check_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if report["verdict"] != "pass":
        rules_str = ", ".join(report["failing_rules"])
        first_msg = report["problems"][0]["message"] if report["problems"] else "check failed"
        if step_ws.run_file.is_file():
            step_ws.mark("directions_check", "failed", reason=f"{rules_str}: {first_msg}")
        if allow_retry:
            return {
                "ok": True,
                "step": "directions_check",
                "status": "retry",
                "valid": "no",
                "verdict": "retry",
                "failing_rules": report["failing_rules"],
                "problems": report["problems"],
                "revise_task": report["revise_task"],
            }
        raise DirectionsError(f"directions_check failed [{rules_str}]: {first_msg}")

    if step_ws.run_file.is_file():
        step_ws.mark("directions_check", "done")
    return {
        "ok": True,
        "step": "directions_check",
        "status": "done",
        "valid": "yes",
        "verdict": "ok",
        "failing_rules": [],
        "problems": [],
        "revise_task": "",
    }


def directions_finish(
    ws: Workspace,
    *,
    draft: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Persist the accepted directions set (`02-directions/directions.json` + `<id>/{tokens.json,DESIGN.md}`)."""
    step_ws = ws.for_step("directions")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    contracts.validate("brief", brief_doc, step="directions")
    product = str(brief_doc["product"])
    brief_sha = _brief_sha(brief_doc)

    # If `directions_collect` already reused valid prior work, honour the reuse.
    collect_status = (
        (step_ws.run().get("stages") or {}).get("directions_collect", {}).get("status")
        if step_ws.run_file.is_file()
        else None
    )
    if (
        (step_ws.path / "02-directions" / "directions.json").is_file()
        and not draft
        and (collect_status in ("reused", "skipped") or not (step_ws.path / "02-directions" / "draft.json").is_file())
    ):
        existing = step_ws.read_json("02-directions/directions.json")
        contracts.validate("directions", existing, step="directions")
        if step_ws.run_file.is_file():
            step_ws.mark("directions", "reused", note="reused existing 02-directions/directions.json")
        return {
            "ok": True,
            "step": "directions",
            "status": "reused",
            "product": product,
            "recommended": existing["recommended"],
            "count": len(existing["directions"]),
            "directions": [d["id"] for d in existing["directions"]],
            "direction_ids": [d["id"] for d in existing["directions"]],
        }

    out_dir = step_ws.folder("directions")
    out_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(draft, str) and draft.strip():
        draft_obj = parse_model_json(draft)
        (out_dir / "draft.json").write_text(
            json.dumps(draft_obj, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif isinstance(draft, dict) and draft:
        draft_obj = parse_model_json(draft)
        (out_dir / "draft.json").write_text(
            json.dumps(draft_obj, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        draft_obj = step_ws.read_json("02-directions/draft.json")

    report = evaluate_directions(ws, draft=draft_obj, use_existing_tokens=False)
    check_final_doc = {
        "product": report["product"],
        "verdict": report["verdict"],
        "failing_rules": report["failing_rules"],
        "checks": report["checks"],
        "problems": report["problems"],
        "proof_reports": report["proof_reports"],
    }
    (out_dir / "check-final.json").write_text(
        json.dumps(check_final_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if report["verdict"] != "pass":
        rules_str = ", ".join(report["failing_rules"])
        first_msg = report["problems"][0]["message"] if report["problems"] else "check failed"
        step_ws.mark("directions", "failed", reason=f"{rules_str}: {first_msg}")
        raise DirectionsError(f"directions_finish failed [{rules_str}]: {first_msg}")

    contracts.validate("directions_draft", draft_obj, step="directions", file_label="02-directions/draft.json")

    entries: list[dict[str, Any]] = []
    for d in draft_obj["directions"]:
        did = str(d["id"])
        d_dir = out_dir / did
        d_dir.mkdir(parents=True, exist_ok=True)
        tok = report["generated_tokens"][did]
        tok_rel = f"02-directions/{did}/tokens.json"
        md_rel = f"02-directions/{did}/DESIGN.md"

        (d_dir / "tokens.json").write_text(
            json.dumps(tok, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        contracts.validate_tokens(tok, step="directions", file=tok_rel)

        md = render_direction_design_md(product, brief_doc, d, tok)
        (d_dir / "DESIGN.md").write_text(md, encoding="utf-8")
        contracts.validate_design_md(md, product=product, step="directions", file=md_rel)

        entries.append(
            {
                "id": did,
                "name": str(d["name"]),
                "premise": str(d["premise"]),
                "summary": f"{d['premise']} ({d['why']})",
                "anchor_hue_deg": float(d["anchor_hue_deg"]),
                "chroma_intent": str(d["chroma_intent"]),
                "neutral_temp": str(d["neutral_temp"]),
                "type_family": str(d["type_family"]),
                "why": str(d["why"]),
                "evidence": dict(d["evidence"]),
                "tokens_file": tok_rel,
                "design_md_file": md_rel,
            }
        )

    directions_doc = {
        "product": product,
        "brief_sha256": brief_sha,
        "recommended": str(draft_obj["recommended"]),
        "directions": entries,
    }
    (out_dir / "directions.json").write_text(
        json.dumps(directions_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    contracts.validate("directions", directions_doc, step="directions")
    step_ws.mark("directions", "done")
    return {
        "ok": True,
        "step": "directions",
        "status": "done",
        "product": product,
        "recommended": directions_doc["recommended"],
        "count": len(entries),
        "directions": [e["id"] for e in entries],
        "direction_ids": [e["id"] for e in entries],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="foundation.directions",
        description="Run deterministic Stage 2 directions_check on a foundation workspace or known-case directory.",
    )
    parser.add_argument("target", help="Workspace directory containing 01-brief/brief.json and 02-directions/draft.json")
    parser.add_argument("--json", action="store_true", help="Emit JSON report to stdout")
    args = parser.parse_args(argv)
    ws = Workspace(Path(args.target).resolve())
    try:
        rep = evaluate_directions(ws)
    except Exception as exc:
        err_doc = {"ok": False, "verdict": "fail", "failing_rules": ["directions.count"], "error": str(exc)}
        print(json.dumps(err_doc, indent=2))
        return 1
    out_doc = {
        "product": rep["product"],
        "verdict": rep["verdict"],
        "failing_rules": rep["failing_rules"],
        "checks": rep["checks"],
        "problems": rep["problems"],
        "proof_reports": rep["proof_reports"],
    }
    print(json.dumps(out_doc, indent=2))
    return 0 if rep["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
