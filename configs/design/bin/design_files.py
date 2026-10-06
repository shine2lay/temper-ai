#!/usr/bin/env python3
"""A product's design files: the convention, the registry and the model-free inventory (Design queue #38).

docs/design-files.md describes the convention. In short:

* A product's design files are DESIGN.md plus tokens.json (DTCG 2025.10 format), with optional logo files
  (logo/) and a Penpot library link. Each part carries a status: draft or approved, who approved it
  (design; owner only for his own words, kept verbatim with their source; fixture-test in fixture
  registries) and the date.
* configs/design/products.yaml registers each product's design-files location and its approved parts:
  locations and statuses only (this repository is public).
* inventory() decides, without a model, whether a design job's product is defined (approved files cover
  every part the job needs), partial (some) or none, and which research the job needs.
* Host commands copy a product's design files into a run's source pack (pack), copy a run's saved design
  files back to the product (apply) and mark parts approved (approve). Runs never read other
  repositories directly: they read the pack, whose hashes the run checks.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REGISTRY = HERE.parent / "products.yaml"
FORMAT = "design-files v1"
EXT = "com.temper.design-files"  # DTCG $extensions key that carries a token part's status

PARTS = ("users", "direction", "colour", "type", "spacing", "radius", "elevation", "motion", "logo", "library")
TOKEN_PARTS = ("colour", "type", "spacing", "radius", "elevation", "motion")
DOC_PARTS = ("users", "direction", "logo", "library")
VISUAL = ("colour", "type", "spacing", "radius", "elevation", "motion")
# The parts each kind of design job needs. A job whose needed parts are all approved is "defined".
NEEDS = {
    "homepage": ("users", "direction", *VISUAL),
    "app_screen": ("users", "direction", *VISUAL),
    "logo": ("users", "direction", "logo", "colour"),
    "marketing": ("users", "direction", "colour", "type", "logo"),
}
# Approved parts a job does not need but follows when they exist (a homepage shows the approved logo).
USES = {"homepage": ("logo", "library"), "app_screen": ("logo", "library"), "logo": ("library",),
        "marketing": ("library",)}
DECIDERS = ("design", "owner")
FIXTURE_DECIDER = "fixture-test"
TITLES = {"users": "Users", "direction": "Direction", "logo": "Logo", "library": "Library"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
ALIAS = re.compile(r"^\{([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+)\}$")
STATUS_LINE = re.compile(r"^Status: (?:approved by (design|owner|fixture-test) on (\d{4}-\d{2}-\d{2})|(draft)|(missing))[ \t]*$")
MIRROR_LINE = re.compile(r"^- (\w+): (?:approved by (design|owner|fixture-test) on (\d{4}-\d{2}-\d{2})|(draft)|(missing))[ \t]*$")
APPROVAL_LINE = re.compile(r"^- (\w+): (design|owner|fixture-test) on (\d{4}-\d{2}-\d{2}): (.+)$")
OWNER_WORDS = re.compile(r"^[\"\u201c](.+?)[\"\u201d] \((.+)\)$")


def today() -> str:
    return dt.datetime.now(dt.UTC).astimezone().date().isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _date(value: Any) -> Any:
    """YAML reads an unquoted 2026-10-03 as a date; the registry keeps dates as text."""
    return value.isoformat() if isinstance(value, dt.date) else value


def _valid_date(text: Any) -> bool:
    if not isinstance(text, str) or not DATE.match(text):
        return False
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _safe_rel(path: Any) -> bool:
    if not isinstance(path, str) or not path.strip() or "\\" in path or path.startswith(("/", "~")):
        return False
    return ".." not in Path(path).parts


# ---------------------------------------------------------------- statuses

def check_status(part: str, value: Any, fixture: bool) -> list[str]:
    """One part's status record: {status: approved, approved_by, date} or {status: draft, date}."""
    if not isinstance(value, dict):
        return [f"{part}: a status is a mapping"]
    value = {k: _date(v) for k, v in value.items()}
    problems = []
    if set(value) - {"status", "approved_by", "date"}:
        problems.append(f"{part}: unknown status keys {sorted(set(value) - {'status', 'approved_by', 'date'})}")
    if value.get("status") not in ("approved", "draft"):
        problems.append(f"{part}: status is approved or draft")
    if not _valid_date(value.get("date")):
        problems.append(f"{part}: date is YYYY-MM-DD")
    allowed = (FIXTURE_DECIDER,) if fixture else DECIDERS
    if value.get("status") == "approved" and value.get("approved_by") not in allowed:
        problems.append(f"{part}: approved_by is {' or '.join(allowed)}"
                        + (" (a fixture never claims a Design or owner decision)" if fixture else ""))
    if value.get("status") == "draft" and "approved_by" in value:
        problems.append(f"{part}: a draft has no approved_by")
    return problems


def status_text(st: dict | None) -> str:
    if not st:
        return "missing"
    if st.get("status") == "approved":
        return f"approved by {st['approved_by']} on {st['date']}"
    return "draft"


# ---------------------------------------------------------------- registry

def check_registry(data: Any) -> list[str]:
    """Problems with a registry (configs/design/products.yaml, or a fixture registry for tests and trials)."""
    if not isinstance(data, dict):
        return ["the registry is a mapping"]
    problems = []
    if set(data) - {"version", "fixture", "repos", "products"}:
        problems.append(f"unknown registry keys {sorted(set(data) - {'version', 'fixture', 'repos', 'products'})}")
    if data.get("version") != 1:
        problems.append("version is 1")
    fixture = data.get("fixture", False)
    if not isinstance(fixture, bool):
        problems.append("fixture is true or false")
        fixture = False
    repos = data.get("repos") or {}
    if not isinstance(repos, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in repos.items()):
        problems.append("repos maps a repository name to its folder on the host")
        repos = {}
    products = data.get("products")
    if not isinstance(products, dict) or not products:
        return problems + ["products is a non-empty mapping"]
    for pid, entry in products.items():
        problems += [f"{pid}: {p}" for p in check_entry(str(pid), entry, repos, fixture)]
    return problems


def check_entry(pid: str, entry: Any, repos: dict, fixture: bool) -> list[str]:
    problems = [] if SLUG.match(pid) else ["a product id is a lowercase slug"]
    if not isinstance(entry, dict):
        return problems + ["an entry is a mapping"]
    allowed = {"name", "location", "parts", "current_state", "force_research", "note"}
    if set(entry) - allowed:
        problems.append(f"unknown keys {sorted(set(entry) - allowed)} (the registry holds locations and statuses only)")
    name = entry.get("name")
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 60:
        problems.append("name is 1-60 characters")
    loc = entry.get("location")
    if not isinstance(loc, dict) or loc.get("kind") not in ("repo", "lab"):
        problems.append("location is {kind: repo, repo, path} or {kind: lab, path}")
    else:
        if set(loc) - {"kind", "repo", "path"}:
            problems.append(f"unknown location keys {sorted(set(loc) - {'kind', 'repo', 'path'})}")
        if not _safe_rel(loc.get("path")):
            problems.append("location path is relative, without ..")
        if loc["kind"] == "repo" and loc.get("repo") not in repos:
            problems.append("a repo location names a repository listed under repos")
        if loc["kind"] == "lab" and "repo" in loc:
            problems.append("a lab location has no repo")
    parts = entry.get("parts") or {}
    if not isinstance(parts, dict):
        problems.append("parts maps a part to its status")
        parts = {}
    for part, value in parts.items():
        if part not in PARTS:
            problems.append(f"unknown part {part} (parts: {', '.join(PARTS)})")
            continue
        problems += check_status(part, value, fixture)
    current = entry.get("current_state", [])
    if not isinstance(current, list) or not all(_safe_rel(p) for p in current):
        problems.append("current_state lists relative paths (an app's current CSS or screens: audited, not rules)")
    force = entry.get("force_research", False)
    if not (isinstance(force, bool) or (isinstance(force, list) and all(p in PARTS for p in force))):
        problems.append("force_research is true or a list of parts")
    note = entry.get("note", "")
    if not isinstance(note, str) or len(note) > 200:
        problems.append("note is at most 200 characters")
    return problems


def normalize_registry(data: dict) -> dict:
    for entry in (data.get("products") or {}).values():
        if isinstance(entry, dict) and isinstance(entry.get("parts"), dict):
            entry["parts"] = {p: {k: _date(v) for k, v in s.items()} if isinstance(s, dict) else s
                              for p, s in entry["parts"].items()}
    return data


def load_registry(path: Path | str = REGISTRY) -> dict:
    data = normalize_registry(yaml.safe_load(Path(path).read_text()) or {})
    problems = check_registry(data)
    if problems:
        raise ValueError(f"registry {path}: " + "; ".join(problems[:8]))
    return data


def write_registry(path: Path | str, data: dict) -> None:
    """Rewrite a registry, keeping the comment block at its top."""
    path = Path(path)
    head = []
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.startswith("#"):
                break
            head.append(line)
    problems = check_registry(data)
    if problems:
        raise ValueError("refusing to write a registry with problems: " + "; ".join(problems[:6]))
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=110)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(("\n".join(head) + "\n" if head else "") + body)
    tmp.replace(path)


def location_dir(registry: dict, entry: dict, lab_root: Path | str) -> Path:
    """Where a product's design files live on the host."""
    loc = entry["location"]
    if loc["kind"] == "repo":
        return Path(registry["repos"][loc["repo"]]).expanduser() / loc["path"]
    return Path(lab_root).expanduser() / loc["path"]


def state_root(registry: dict, entry: dict, lab_root: Path | str) -> Path:
    """The folder current_state paths are relative to: the product repo, or the lab location."""
    loc = entry["location"]
    if loc["kind"] == "repo":
        return Path(registry["repos"][loc["repo"]]).expanduser()
    return location_dir(registry, entry, lab_root)


# ---------------------------------------------------------------- DESIGN.md

def split_sections(text: str) -> tuple[list[str], dict[str, str]]:
    """Header lines before the first '## ' heading, and each '## Title' section's body."""
    head: list[str] = []
    sections: dict[str, str] = {}
    current = None
    body: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(body).strip("\n")
            current, body = m.group(1), []
        elif current is None:
            head.append(line)
        else:
            body.append(line)
    if current is not None:
        sections[current] = "\n".join(body).strip("\n")
    return head, sections


def _status_from_match(m: re.Match, offset: int = 0) -> dict | None:
    by, date, draft, missing = m.group(1 + offset), m.group(2 + offset), m.group(3 + offset), m.group(4 + offset)
    if missing:
        return None
    if draft:
        return {"status": "draft"}
    return {"status": "approved", "approved_by": by, "date": date}


def parse_design_md(text: str) -> dict:
    """Read DESIGN.md: header, sections, each document part's status, user groups, token mirror, approvals."""
    head, sections = split_sections(text)
    problems = []
    header = {}
    for line in head:
        m = re.match(r"^(Product|Updated|Format): (.+)$", line)
        if m:
            header[m.group(1).lower()] = m.group(2).strip()
    title = next((h[2:].strip() for h in head if h.startswith("# ")), "")
    if not title:
        problems.append("DESIGN.md starts with '# <Product> design files'")
    if header.get("format") != FORMAT:
        problems.append(f"DESIGN.md header says 'Format: {FORMAT}'")
    if not SLUG.match(header.get("product", "")):
        problems.append("DESIGN.md header says 'Product: <registry id>'")
    parts: dict[str, dict | None] = {}
    for part, name in TITLES.items():
        body = sections.get(name)
        if body is None:
            problems.append(f"DESIGN.md has a '## {name}' section (Status: missing when there is nothing yet)")
            parts[part] = None
            continue
        first = next((ln for ln in body.splitlines() if ln.strip()), "")
        m = STATUS_LINE.match(first)
        if not m:
            problems.append(f"'## {name}' starts with 'Status: approved by <design|owner> on YYYY-MM-DD', 'Status: draft' or 'Status: missing'")
            parts[part] = None
            continue
        parts[part] = _status_from_match(m)
    mirror: dict[str, dict | None] = {}
    for line in sections.get("Tokens", "").splitlines():
        m = MIRROR_LINE.match(line)
        if m and m.group(1) in TOKEN_PARTS:
            mirror[m.group(1)] = _status_from_match(m, 1)
    if "Tokens" not in sections:
        problems.append("DESIGN.md has a '## Tokens' section listing each token part's status (tokens.json is the source)")
    approvals: dict[str, dict] = {}
    for line in sections.get("Approvals", "").splitlines():
        if not line.strip():
            continue
        m = APPROVAL_LINE.match(line)
        if not m or m.group(1) not in PARTS:
            problems.append(f"Approvals line not understood: {line[:80]}")
            continue
        part, by, date, rest = m.groups()
        record = {"approved_by": by, "date": date}
        if by == "owner":
            w = OWNER_WORDS.match(rest.strip())
            if not w:
                problems.append(f"an owner approval of {part} quotes his own words and says where: \"<words>\" (<source>)")
            else:
                record.update({"words": w.group(1), "source": w.group(2)})
        else:
            record["reasons"] = rest.strip()
        approvals[part] = record
    groups = []
    users = sections.get("Users", "")
    group = None
    for line in users.splitlines():
        m = re.match(r"^### (.+?)\s*$", line)
        if m:
            group = {"name": m.group(1), "aliases": []}
            groups.append(group)
            continue
        a = re.match(r"^Also called: (.+)$", line)
        if a and group is not None:
            group["aliases"] += [x.strip() for x in re.split(r"[;,]", a.group(1)) if x.strip()]
    logo_files = []
    for line in sections.get("Logo", "").splitlines():
        m = re.match(r"^Files: (.+)$", line)
        if m:
            logo_files += [x.strip() for x in m.group(1).split(",") if x.strip()]
    return {"title": title, "header": header, "sections": sections, "parts": parts, "mirror": mirror,
            "approvals": approvals, "groups": groups, "logo_files": logo_files, "problems": problems}


# ---------------------------------------------------------------- tokens.json (DTCG 2025.10)

TOKEN_TYPES = ("color", "dimension", "fontFamily", "fontWeight", "duration", "cubicBezier", "number", "shadow", "typography")
WEIGHT_WORDS = {"thin", "hairline", "extra-light", "ultra-light", "light", "normal", "regular", "book", "medium",
                "semi-bold", "demi-bold", "bold", "extra-bold", "ultra-bold", "black", "heavy", "extra-black", "ultra-black"}


def color_token(hex_value: str, description: str = "") -> dict:
    """A DTCG colour value from #RRGGBB (sRGB): components 0-1 and the hex kept as given."""
    if not HEX.match(hex_value):
        raise ValueError(f"not a #RRGGBB colour: {hex_value}")
    comps = [round(int(hex_value[i:i + 2], 16) / 255, 4) for i in (1, 3, 5)]
    token: dict[str, Any] = {"$value": {"colorSpace": "srgb", "components": comps, "hex": hex_value}}
    if description:
        token["$description"] = description
    return token


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_value(t: str, v: Any) -> str | None:
    if isinstance(v, str) and ALIAS.match(v):
        return None
    if t == "color":
        if not isinstance(v, dict) or v.get("colorSpace") != "srgb":
            return "a colour is {colorSpace: srgb, components, hex}"
        comps = v.get("components")
        if not isinstance(comps, list) or len(comps) != 3 or not all(_num(c) and 0 <= c <= 1 for c in comps):
            return "colour components are three numbers 0-1"
        if "alpha" in v and not (_num(v["alpha"]) and 0 <= v["alpha"] <= 1):
            return "alpha is 0-1"
        h = v.get("hex")
        if not isinstance(h, str) or not HEX.match(h):
            return "a colour carries hex #RRGGBB"
        if any(abs(int(h[1 + 2 * i:3 + 2 * i], 16) / 255 - comps[i]) > 0.003 for i in range(3)):
            return f"hex {h} and components disagree"
        return None
    if t == "dimension":
        ok = isinstance(v, dict) and _num(v.get("value")) and v.get("unit") in ("px", "rem") and set(v) <= {"value", "unit"}
        return None if ok else "a dimension is {value, unit: px|rem}"
    if t == "duration":
        ok = isinstance(v, dict) and _num(v.get("value")) and v["value"] >= 0 and v.get("unit") in ("ms", "s")
        return None if ok else "a duration is {value >= 0, unit: ms|s}"
    if t == "fontFamily":
        ok = (isinstance(v, str) and v.strip()) or (isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v))
        return None if ok else "a font family is a name or a list of names"
    if t == "fontWeight":
        ok = (_num(v) and 1 <= v <= 1000) or (isinstance(v, str) and v in WEIGHT_WORDS)
        return None if ok else "a font weight is 1-1000 or a weight keyword"
    if t == "cubicBezier":
        ok = isinstance(v, list) and len(v) == 4 and all(_num(x) for x in v) and 0 <= v[0] <= 1 and 0 <= v[2] <= 1
        return None if ok else "a cubic bezier is [x1, y1, x2, y2] with x in 0-1"
    if t == "number":
        return None if _num(v) else "a number"
    if t == "shadow":
        layers = v if isinstance(v, list) else [v]
        for layer in layers:
            if not isinstance(layer, dict) or not {"color", "offsetX", "offsetY", "blur", "spread"} <= set(layer):
                return "a shadow is {color, offsetX, offsetY, blur, spread} or a list of them"
            for key in ("offsetX", "offsetY", "blur", "spread"):
                if _check_value("dimension", layer[key]):
                    return f"shadow {key} is a dimension"
            if _check_value("color", layer["color"]):
                return "a shadow colour is a colour value"
        return None
    if t == "typography":
        if not isinstance(v, dict) or not {"fontFamily", "fontSize", "fontWeight", "lineHeight"} <= set(v):
            return "a typography token is {fontFamily, fontSize, fontWeight, lineHeight}"
        for key, kind in (("fontFamily", "fontFamily"), ("fontSize", "dimension"), ("fontWeight", "fontWeight"),
                          ("lineHeight", "number")):
            if _check_value(kind, v[key]):
                return f"typography {key}: {_check_value(kind, v[key])}"
        if "letterSpacing" in v and _check_value("dimension", v["letterSpacing"]):
            return "typography letterSpacing is a dimension"
        return None
    return f"unknown token type {t}"


def token_list(tokens: dict) -> list[tuple[str, str | None, Any]]:
    """Every token as (dotted path, $type, $value); $type is inherited from the nearest group."""
    out: list[tuple[str, str | None, Any]] = []

    def walk(node: dict, path: list[str], inherited: str | None) -> None:
        for key, value in node.items():
            if key.startswith("$") or not isinstance(value, dict):
                continue
            t = value.get("$type", inherited)
            if "$value" in value:
                out.append((".".join(path + [key]), t, value["$value"]))
            else:
                walk(value, path + [key], t)

    walk(tokens, [], None)
    return out


def check_tokens(tokens: Any) -> list[str]:
    """DTCG format checks plus this convention's rules: top-level groups are token parts with a status."""
    if not isinstance(tokens, dict):
        return ["tokens.json is a JSON object"]
    problems = []
    for key, value in tokens.items():
        if key.startswith("$"):
            if key not in ("$description", "$extensions", "$schema"):
                problems.append(f"unknown top-level key {key}")
            continue
        if key not in TOKEN_PARTS:
            problems.append(f"top-level group {key} is not a token part ({', '.join(TOKEN_PARTS)})")
            continue
        if not isinstance(value, dict):
            problems.append(f"{key} is a group")
            continue
        ext = (value.get("$extensions") or {}).get(EXT)
        if not isinstance(ext, dict) or ext.get("part") != key:
            problems.append(f"{key} carries $extensions.{EXT} {{part, status, approved_by, date}}")
        else:
            problems += check_status(key, {k: v for k, v in ext.items() if k != "part"}, fixture=ext.get("approved_by") == FIXTURE_DECIDER)
    names = re.compile(r"^[^${}.][^{}.]*$")
    paths = {}
    for path, t, v in token_list({k: v for k, v in tokens.items() if k in TOKEN_PARTS}):
        if not all(names.match(p) for p in path.split(".")):
            problems.append(f"token name {path} uses $, {{, }} or .")
        if t not in TOKEN_TYPES:
            problems.append(f"{path}: $type is one of {', '.join(TOKEN_TYPES)}")
            continue
        err = _check_value(t, v)
        if err:
            problems.append(f"{path}: {err}")
        paths[path] = (t, v)
    for path, (_t, v) in paths.items():
        refs = [v] if isinstance(v, str) else [x for x in (v.values() if isinstance(v, dict) else []) if isinstance(x, str)]
        for ref in refs:
            m = ALIAS.match(ref)
            if m and m.group(1) not in paths:
                problems.append(f"{path}: alias {ref} points at no token")
    return problems


def token_part_status(tokens: dict | None, part: str) -> dict | None:
    group = (tokens or {}).get(part)
    if not isinstance(group, dict):
        return None
    ext = dict((group.get("$extensions") or {}).get(EXT) or {})
    ext.pop("part", None)
    return ext or None


def canonical(value: Any) -> str:
    """The byte form two copies of an approved part must share."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def resolve(tokens: dict, value: Any, depth: int = 0) -> Any:
    if isinstance(value, str) and ALIAS.match(value) and depth < 8:
        node: Any = tokens
        for key in ALIAS.match(value).group(1).split("."):
            node = node.get(key, {}) if isinstance(node, dict) else {}
        return resolve(tokens, node.get("$value") if isinstance(node, dict) else None, depth + 1)
    return value


def token_hexes(tokens: dict | None, parts: tuple[str, ...] = TOKEN_PARTS) -> list[str]:
    """Every colour in the given token parts as #RRGGBB (upper case), shadows included."""
    out = []
    for _path, t, v in token_list({k: v for k, v in (tokens or {}).items() if k in parts}):
        v = resolve(tokens or {}, v)
        if t == "color" and isinstance(v, dict) and HEX.match(str(v.get("hex", ""))):
            out.append(v["hex"].upper())
        if t == "shadow":
            for layer in v if isinstance(v, list) else [v]:
                c = resolve(tokens or {}, layer.get("color")) if isinstance(layer, dict) else None
                if isinstance(c, dict) and HEX.match(str(c.get("hex", ""))):
                    out.append(c["hex"].upper())
    return sorted(set(out))


def token_fonts(tokens: dict | None) -> list[str]:
    """Every font family name in the type part (first names and fallbacks)."""
    out = []
    for _path, t, v in token_list({"type": (tokens or {}).get("type") or {}}):
        v = resolve(tokens or {}, v)
        if t == "fontFamily":
            out += [v] if isinstance(v, str) else list(v)
        if t == "typography" and isinstance(v, dict):
            fam = resolve(tokens or {}, v.get("fontFamily"))
            out += [fam] if isinstance(fam, str) else list(fam or [])
    return sorted({f.strip() for f in out if isinstance(f, str) and f.strip()})


# ---------------------------------------------------------------- a folder of design files

def read_files(folder: Path | str) -> dict | None:
    """Parse and check a product's design files; None when there are none."""
    folder = Path(folder)
    design_path = folder / "DESIGN.md"
    if not design_path.is_file():
        return None
    design = parse_design_md(design_path.read_text())
    problems = list(design["problems"])
    tokens = None
    if (folder / "tokens.json").is_file():
        try:
            tokens = json.loads((folder / "tokens.json").read_text())
        except json.JSONDecodeError as exc:
            problems.append(f"tokens.json is not JSON: {exc}")
        else:
            problems += check_tokens(tokens)
    parts: dict[str, dict | None] = dict(design["parts"])
    for part in TOKEN_PARTS:
        st = token_part_status(tokens, part) if isinstance(tokens, dict) else None
        parts[part] = st
        mirrored = design["mirror"].get(part)
        if (mirrored or {}).get("status") != (st or {}).get("status") or (
                st and st.get("status") == "approved" and mirrored and
                (mirrored.get("approved_by"), mirrored.get("date")) != (st.get("approved_by"), st.get("date"))):
            problems.append(f"DESIGN.md's Tokens line for {part} says {status_text(mirrored)}; tokens.json says {status_text(st)}")
    for part, st in parts.items():
        if st and st.get("status") == "approved":
            record = design["approvals"].get(part)
            if not record or (record["approved_by"], record["date"]) != (st["approved_by"], st["date"]):
                problems.append(f"approved part {part} has a matching '## Approvals' line (who, date, and the owner's "
                                "words with their source, or the reasons)")
    for name in design["logo_files"]:
        if not _safe_rel(name) or not (folder / name).is_file():
            problems.append(f"logo file {name} is missing")
    if (parts.get("logo") or {}).get("status") == "approved" and not design["logo_files"]:
        problems.append("an approved logo lists its files (Files: logo/...)")
    return {"design": design, "tokens": tokens, "parts": parts, "groups": design["groups"], "problems": problems,
            "product": design["header"].get("product")}


# ---------------------------------------------------------------- inventory

STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "with", "who", "that", "their", "our",
        "your", "people", "users", "user", "use", "using", "teams", "team"}


def _words(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", str(text).lower()):
        if w in STOP:
            continue
        out.append(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def match_audience(audience: str, groups: list[dict]) -> str | None:
    """The approved user group a job's audience names, or None (an audience gap: research that audience only)."""
    a = _words(audience)
    if not a:
        return None
    a_text, a_set = " " + " ".join(a) + " ", set(a)
    best = None
    for group in groups:
        for name in [group["name"], *group.get("aliases", [])]:
            n = _words(name)
            if not n:
                continue
            n_text = " " + " ".join(n) + " "
            if n_text in a_text or a_text in n_text:
                return group["name"]
            if best is None and len(a_set & set(n)) / len(a_set | set(n)) >= 0.5:
                best = group["name"]
    return best


def _force(value: Any, needed: tuple[str, ...]) -> list[str]:
    if value is True:
        return list(needed)
    if isinstance(value, list):
        bad = [p for p in value if p not in PARTS]
        if bad:
            raise ValueError(f"force names unknown parts {bad}")
        return [p for p in needed if p in value]
    if value in (None, False, "", []):
        return []
    raise ValueError("force is true or a list of parts")


def inventory(entry: dict | None, files: dict | None, job: str, *, audience: str = "", force: Any = None,
              fixture: bool = False) -> dict:
    """Model-free: defined, partial or none, the approved and missing parts, and the research the job needs.

    A part counts as approved only when the registry entry and the design files agree on it (status, who,
    date); a disagreement stops the run rather than guessing. Forced parts (Design or the owner) count as
    missing. Approved parts become fixed constraints for the job.
    """
    if job not in NEEDS:
        raise ValueError(f"job is one of {', '.join(NEEDS)}")
    entry = entry or {"parts": {}}
    if files and files.get("problems"):
        raise ValueError("the design files have problems: " + "; ".join(files["problems"][:6]))
    allowed = (FIXTURE_DECIDER,) if fixture else DECIDERS
    needed = NEEDS[job]
    forced = _force(force if force is not None else entry.get("force_research"), needed)
    approved: dict[str, dict] = {}
    missing, drafts = [], []
    for part in needed + USES[job]:
        reg = (entry.get("parts") or {}).get(part)
        got = (files or {}).get("parts", {}).get(part)
        reg_ok = bool(reg and reg.get("status") == "approved")
        got_ok = bool(got and got.get("status") == "approved")
        if reg_ok != got_ok or (reg_ok and (reg.get("approved_by"), _date(reg.get("date"))) !=
                                (got.get("approved_by"), got.get("date"))):
            raise ValueError(f"the registry and the design files disagree on {part}: registry {status_text(reg)}, "
                             f"files {status_text(got)}; fix one of them (design_files.py approve or apply)")
        if reg_ok and reg.get("approved_by") not in allowed:
            raise ValueError(f"{part} is approved by {reg.get('approved_by')}; this run accepts {' or '.join(allowed)}")
        if reg_ok and part not in forced:
            approved[part] = {"approved_by": reg["approved_by"], "date": _date(reg["date"])}
        elif part in needed:
            missing.append(part)
            if got and got.get("status") == "draft":
                drafts.append(part)
    status = "defined" if not missing else "partial" if any(p in approved for p in needed) else "none"
    groups = (files or {}).get("groups", []) if "users" in approved else []
    matched = match_audience(audience, groups) if groups else None
    gap = bool("users" in approved and audience.strip() and matched is None)
    users = "full" if "users" in missing else "audience" if gap else "none"
    direction = "direction" in missing
    category = direction or (job == "logo" and "logo" in missing)
    return {"job": job, "status": status, "needed": list(needed), "approved": approved, "missing": missing,
            "drafts": drafts, "forced": forced, "fixed": [p for p in needed + USES[job] if p in approved],
            "audience": {"text": audience, "group": matched, "gap": gap},
            "research": {"users": users, "direction": direction, "category": category,
                         "any": users != "none" or direction or category}}


# ---------------------------------------------------------------- source pack (host side + run side)

def _copy_tree(src: Path, dest: Path) -> dict[str, str]:
    """Copy regular files (no hidden files, no links) and return {relative path: sha256}."""
    hashes = {}
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if any(part.startswith(".") for part in rel.parts) or path.is_dir():
            continue
        if path.is_symlink():
            raise ValueError(f"{path} is a link; a pack holds plain files")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[rel.as_posix()] = sha256(target)
    return hashes


def pack(registry_path: Path | str, product: str, source: Path | str | None, workspace: Path | str,
         lab_root: Path | str = "~/design-lab") -> dict:
    """Copy a product's source material and design files into a run workspace, with a hash manifest."""
    registry = load_registry(registry_path)
    entry = registry["products"].get(product)
    if entry is None:
        raise ValueError(f"{product} is not in {registry_path}")
    ws = Path(workspace).expanduser().resolve()
    out, files_out = ws / "source", ws / "design-files"
    if (out / "pack.json").exists() or files_out.exists():
        raise ValueError(f"{ws} already holds a pack; use a fresh workspace")
    out.mkdir(parents=True, exist_ok=True)
    files = _copy_tree(Path(source).expanduser().resolve(), out / "docs") if source else {}
    location = location_dir(registry, entry, lab_root)
    design: dict[str, str] = {}
    if (location / "DESIGN.md").is_file():
        found = read_files(location)
        if found and found["problems"]:
            raise ValueError(f"{location}: " + "; ".join(found["problems"][:6]))
        for name in ["DESIGN.md", "tokens.json"]:
            if (location / name).is_file():
                files_out.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(location / name, files_out / name)
                design[name] = sha256(files_out / name)
        if (location / "logo").is_dir():
            design.update({f"logo/{k}": v for k, v in _copy_tree(location / "logo", files_out / "logo").items()})
    current: dict[str, str] = {}
    root = state_root(registry, entry, lab_root)
    for rel in entry.get("current_state", []):
        src = root / rel
        if not src.is_file():
            raise ValueError(f"current_state file {src} is missing")
        target = out / "current-state" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        current[rel] = sha256(target)
    manifest = {"version": 1, "product": product, "name": entry["name"], "fixture": bool(registry.get("fixture")),
                "registry_entry": entry, "files": files, "design_files": design, "current_state": current,
                "packed_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    (out / "pack.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def verify_pack(workspace: Path | str) -> dict:
    """Run side: the pack the host made, with every file's hash checked (a changed pack stops the run)."""
    ws = Path(workspace)
    path = ws / "source" / "pack.json"
    if not path.is_file():
        raise ValueError("no source pack: the host makes one with design_files.py pack before the run")
    manifest = json.loads(path.read_text())
    checks = [(ws / "source" / "docs" / rel, sha) for rel, sha in manifest.get("files", {}).items()]
    checks += [(ws / "design-files" / rel, sha) for rel, sha in manifest.get("design_files", {}).items()]
    checks += [(ws / "source" / "current-state" / rel, sha) for rel, sha in manifest.get("current_state", {}).items()]
    for file, sha in checks:
        if not file.is_file() or sha256(file) != sha:
            raise ValueError(f"the source pack changed after packing: {file.relative_to(ws)}; use a fresh workspace")
    entry = manifest.get("registry_entry")
    if entry is not None:
        loc = entry.get("location") if isinstance(entry, dict) else None
        repos = {loc["repo"]: "-"} if isinstance(loc, dict) and loc.get("kind") == "repo" and isinstance(loc.get("repo"), str) else {}
        problems = check_entry(str(manifest.get("product")), entry, repos, bool(manifest.get("fixture")))
        if problems:
            raise ValueError("the pack's registry entry has problems: " + "; ".join(problems[:4]))
    return manifest


# ---------------------------------------------------------------- writing design files

def render_design_md(model: dict) -> str:
    """DESIGN.md from a model; raw section text (an approved part copied as it was) wins over the model."""
    raw = model.get("raw", {})
    out = [f"# {model['name']} design files", "", f"Product: {model['product']}", f"Updated: {model['updated']}",
           f"Format: {FORMAT}", ""]
    if model.get("intro"):
        out += [model["intro"].strip(), ""]

    def section(title: str, status: dict | None, lines: list[str]) -> None:
        out.append(f"## {title}")
        if title in raw:
            out.append(raw[title])
        else:
            out.append(f"Status: {status_text(status)}")
            if lines:
                out.append("")
                out.extend(lines)
        out.append("")

    section("Users", model.get("status", {}).get("users"), model.get("users_lines", []))
    section("Direction", model.get("status", {}).get("direction"), model.get("direction_lines", []))
    out.append("## Tokens")
    out.append("Values live in tokens.json (DTCG 2025.10); each part's status:")
    for part in TOKEN_PARTS:
        out.append(f"- {part}: {status_text(model.get('status', {}).get(part))}")
    out.append("")
    section("Logo", model.get("status", {}).get("logo"), model.get("logo_lines", []))
    section("Library", model.get("status", {}).get("library"), model.get("library_lines", []))
    out.append("## Approvals")
    for a in model.get("approvals", []):
        if a["approved_by"] == "owner":
            out.append(f"- {a['part']}: owner on {a['date']}: \"{a['words']}\" ({a['source']})")
        else:
            out.append(f"- {a['part']}: {a['approved_by']} on {a['date']}: {' '.join(str(a['reasons']).split())}")
    return "\n".join(out).rstrip() + "\n"


def token_group(part: str, tokens: dict, status: dict) -> dict:
    """A token part's group with its status extension."""
    ext = {"part": part, **{k: v for k, v in status.items() if k in ("status", "approved_by", "date")}}
    return {"$extensions": {EXT: ext}, **tokens}


# ---------------------------------------------------------------- host commands

def apply(workspace: Path | str, registry_path: Path | str, lab_root: Path | str = "~/design-lab",
          dry_run: bool = False) -> dict:
    """Copy a run's saved design files (design-files-out/) to the product and update the registry."""
    ws = Path(workspace).expanduser().resolve()
    out = ws / "design-files-out"
    update = json.loads((out / "registry-update.json").read_text())
    registry = load_registry(registry_path)
    product = update.get("product")
    entry = registry["products"].get(product)
    if entry is None:
        raise ValueError(f"{product} is not in {registry_path}")
    manifest = json.loads((ws / "source" / "pack.json").read_text())
    if manifest.get("product") != product or bool(manifest.get("fixture")) != bool(registry.get("fixture")):
        raise ValueError("the run's pack is for another product or another registry (fixture vs real)")
    found = read_files(out)
    if found is None or found["problems"]:
        raise ValueError("the saved design files have problems: " + "; ".join((found or {"problems": ["no DESIGN.md"]})["problems"][:6]))
    fixture = bool(registry.get("fixture"))
    parts = update.get("parts") or {}
    for part, st in parts.items():
        problems = check_status(part, st, fixture) if part in PARTS else [f"unknown part {part}"]
        if problems:
            raise ValueError("; ".join(problems))
        got = found["parts"].get(part)
        if (got or {}).get("status") != st["status"] or (st["status"] == "approved" and
                                                         (got["approved_by"], got["date"]) != (st["approved_by"], st["date"])):
            raise ValueError(f"registry-update.json and the saved files disagree on {part}")
    for part, st in (entry.get("parts") or {}).items():
        got = found["parts"].get(part)
        if st.get("status") == "approved" and part not in parts and (
                (got or {}).get("status") != "approved" or (got["approved_by"], got["date"]) != (st["approved_by"], st["date"])):
            raise ValueError(f"the saved files drop or change approved part {part} ({status_text(st)}); a run copies "
                             "approved parts unchanged")
    target = location_dir(registry, entry, lab_root)
    result = {"product": product, "target": str(target), "parts": parts, "dry_run": dry_run}
    if entry["location"]["kind"] == "repo":
        # A product's own repo is landed by the chat that owns it; Design hands the files over.
        stamp = dt.datetime.now(dt.UTC).astimezone().strftime("%Y%m%d-%H%M%S")
        handoff = Path(lab_root).expanduser() / "handoff" / product / stamp
        result.update({"handoff": str(handoff), "registry_updated": False,
                       "next": f"the owning chat lands {handoff} at {entry['location']['repo']}:{entry['location']['path']}; "
                               "then run apply --registry-only"})
        if not dry_run:
            _copy_tree(out, handoff)
        return result
    if not dry_run:
        if target.exists():
            history = target / ".history" / dt.datetime.now(dt.UTC).astimezone().strftime("%Y%m%d-%H%M%S")
            for name in ("DESIGN.md", "tokens.json", "logo"):
                if (target / name).exists():
                    history.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target / name), str(history / name))
        target.mkdir(parents=True, exist_ok=True)
        for name in ("DESIGN.md", "tokens.json"):
            if (out / name).is_file():
                shutil.copyfile(out / name, target / name)
        if (out / "logo").is_dir():
            _copy_tree(out / "logo", target / "logo")
        entry.setdefault("parts", {}).update(parts)
        write_registry(registry_path, registry)
    result["registry_updated"] = not dry_run
    return result


def approve(registry_path: Path | str, product: str, part: str, by: str, lab_root: Path | str = "~/design-lab", *,
            reasons: str = "", words: str = "", source: str = "", date: str | None = None) -> dict:
    """Mark one part approved in a lab-kept product's files and in the registry."""
    registry = load_registry(registry_path)
    entry = registry["products"].get(product)
    if entry is None:
        raise ValueError(f"{product} is not in {registry_path}")
    fixture = bool(registry.get("fixture"))
    date = date or today()
    status = {"status": "approved", "approved_by": by, "date": date}
    problems = check_status(part, status, fixture)
    if by == "owner" and (not words.strip() or not source.strip()):
        problems.append("an owner approval needs his own words (--words) and where he said them (--source)")
    if by != "owner" and not reasons.strip():
        problems.append("an approval needs its reasons (--reasons)")
    if problems:
        raise ValueError("; ".join(problems))
    if entry["location"]["kind"] != "lab":
        raise ValueError("files in a product's own repo are approved there by the owning chat")
    folder = location_dir(registry, entry, lab_root)
    found = read_files(folder)
    if found is None:
        raise ValueError(f"{folder} has no DESIGN.md")
    text = (folder / "DESIGN.md").read_text()
    head, sections = split_sections(text)
    if part in TOKEN_PARTS:
        tokens = found["tokens"] or {}
        if part not in tokens:
            raise ValueError(f"tokens.json has no {part} group to approve")
        tokens[part]["$extensions"][EXT] = {"part": part, **status}
        (folder / "tokens.json").write_text(json.dumps(tokens, indent=2, ensure_ascii=False) + "\n")
        sections["Tokens"] = "\n".join(f"- {part}: {status_text(status)}" if ln.startswith(f"- {part}:") else ln
                                       for ln in sections["Tokens"].splitlines())
    else:
        body = sections[TITLES[part]].splitlines()
        first = next(i for i, ln in enumerate(body) if ln.strip())
        body[first] = f"Status: {status_text(status)}"
        sections[TITLES[part]] = "\n".join(body)
    line = (f"- {part}: owner on {date}: \"{words}\" ({source})" if by == "owner"
            else f"- {part}: {by} on {date}: {' '.join(reasons.split())}")
    lines = [ln for ln in sections.get("Approvals", "").splitlines() if ln.strip() and not ln.startswith(f"- {part}:")]
    sections["Approvals"] = "\n".join(lines + [line])
    (folder / "DESIGN.md").write_text("\n".join(head).rstrip() + "\n\n" +
                                      "\n\n".join(f"## {k}\n{v}" for k, v in sections.items()).rstrip() + "\n")
    again = read_files(folder)
    if again is None or again["problems"]:
        raise ValueError("after approval the files have problems: " + "; ".join((again or {"problems": ["?"]})["problems"][:4]))
    entry.setdefault("parts", {})[part] = status
    write_registry(registry_path, registry)
    return {"product": product, "part": part, **status}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A product's design files: registry, inventory, pack, apply, approve")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check a folder of design files")
    c.add_argument("folder")
    c.add_argument("--fixture", action="store_true")
    r = sub.add_parser("registry-check", help="check a registry")
    r.add_argument("--registry", default=str(REGISTRY))
    i = sub.add_parser("inventory", help="defined, partial or none for a product and job (host view)")
    i.add_argument("--registry", default=str(REGISTRY))
    i.add_argument("--product", required=True)
    i.add_argument("--job", required=True, choices=list(NEEDS))
    i.add_argument("--audience", default="")
    i.add_argument("--lab", default="~/design-lab")
    p = sub.add_parser("pack", help="copy a product's source material and design files into a run workspace")
    p.add_argument("--registry", default=str(REGISTRY))
    p.add_argument("--product", required=True)
    p.add_argument("--source", default=None, help="folder of source material (README, docs, notes)")
    p.add_argument("--workspace", required=True)
    p.add_argument("--lab", default="~/design-lab")
    a = sub.add_parser("apply", help="copy a run's saved design files to the product and update the registry")
    a.add_argument("--workspace", required=True)
    a.add_argument("--registry", default=str(REGISTRY))
    a.add_argument("--lab", default="~/design-lab")
    a.add_argument("--dry-run", action="store_true")
    v = sub.add_parser("approve", help="mark one part approved (lab-kept files) and update the registry")
    v.add_argument("--registry", default=str(REGISTRY))
    v.add_argument("--product", required=True)
    v.add_argument("--part", required=True, choices=list(PARTS))
    v.add_argument("--by", required=True, choices=[*DECIDERS, FIXTURE_DECIDER])
    v.add_argument("--reasons", default="")
    v.add_argument("--words", default="", help="the owner's own words, verbatim")
    v.add_argument("--source", default="", help="where the owner said them")
    v.add_argument("--date", default=None)
    v.add_argument("--lab", default="~/design-lab")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "check":
            found = read_files(args.folder)
            out: Any = {"ok": bool(found) and not found["problems"],
                        "problems": (found or {"problems": ["no DESIGN.md"]})["problems"],
                        "parts": {k: status_text(v) for k, v in (found or {}).get("parts", {}).items()}}
        elif args.cmd == "registry-check":
            load_registry(args.registry)
            out = {"ok": True}
        elif args.cmd == "inventory":
            registry = load_registry(args.registry)
            entry = registry["products"][args.product]
            found = read_files(location_dir(registry, entry, args.lab))
            out = inventory(entry, found, args.job, audience=args.audience, fixture=bool(registry.get("fixture")))
        elif args.cmd == "pack":
            out = pack(args.registry, args.product, args.source, args.workspace, args.lab)
        elif args.cmd == "apply":
            out = apply(args.workspace, args.registry, args.lab, args.dry_run)
        else:
            out = approve(args.registry, args.product, args.part, args.by, args.lab, reasons=args.reasons,
                          words=args.words, source=args.source, date=args.date)
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
