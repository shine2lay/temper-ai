"""Design-owned logo v1 contracts: declarative vectors, not executable SVG.

No model/network/Penpot dependencies. A native human gate is a trusted host
boundary, not a model's JSON claim. No ordinary input can approve artwork.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

VERSION = 1
ROLES = ("ink", "paper", "accent", "accent_on", "muted", "surface")
CAPS = {"explore": 2.25, "palette": 1.0, "critic": .85, "refine": 1.0}
FULL_ESTIMATE = 8.15  # 7.8 stage estimates + .35 retry/overrun headroom; not CLI caps
SIZES = (16, 24, 32, 48, 64)
SCHEMA = """Return only one JSON object (no Markdown/code fence).
Explore: {product:<exact brief product>, concepts:[exactly six objects]}.
Each concept: {id:<slug>, name:<up to32>, idea:<up to700>, source_ids:[brief source ids],
 tradeoff:<up to500>, symbol:[1..8 shape objects], minimum_symbol_px:16|24|32,
 wordmark_weight:'400'|'600'}.
Rect: {kind:'rect',name:<up to48>,x:0..100,y:0..100,w:>0,h:>0,r:0..min(w,h)/2}.
Ellipse: {kind:'ellipse',name:<up to48>,x,y,w,h}.
Path: {kind:'path',name:<up to48>,commands:[["M",x,y],["L",x,y],
 ["C",c1x,c1y,c2x,c2y,x,y],["Z"]...]}. All coordinates finite 0..100.
Paths must close every subpath; max64 commands/path,192 total/concept. Filled
silhouettes only, no strokes, SVG strings, images, transforms, URLs, code or icons.
Use negative space between original shapes; do not fake counters with background
patches. No fixed Temper catalogue. Generate forms from this brief. Existing font
Source Sans Pro regular/semibold only; text remains live. No fabricated approval.
Palette: {product:<exact>,shortlist:[exactly3 objects],recommendation:<selected id>,
 recommendation_reason:<up to900>}. Each row: {id:<existing concept id>,
 palette:{ink,paper,accent,accent_on,muted,surface:<#RRGGBB>}, rationale:<up to700>}.
ink/paper, muted/paper, ink/surface, paper/ink, accent_on/accent must >=4.5;
accent/paper and accent/ink >=3 for demonstrated essential graphics. Logo/logotype
exemptions are separate from ordinary companion text/UI. Never use accent as a
status/error semantic. Shortlist THREE DIFFERENT ideas/forms, not recolours.
Refine: {product:<exact>,concept:<same concept schema and selected id>,
 palette:<same6role schema>, changes:[up to8 evidence-specific strings],
 declined:[up to8 reasoned strings]}. Respect real saved selection and owner note;
no silent change to direction, product or owner approval. Max TWO rounds.
Critic: {product:<exact>,observations:[up to14],recommendation:<id>,
 recommendation_reason:<up to900>,limitations:<up to1000>}.
Observation: {scope:'concept'|'contract',id:<concept id or contract cell A..E>,
 kind:'measured'|'visual'|'taste'|'similarity',element:<up to120>,
 location:<up to120>,evidence:<up to500>,suggestion:<up to400>}.
No aesthetic scores. Recommendations are advice, not owner decisions. Contract
board observations must be separate. Do not call logos WCAG text failures.
"""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError("unexpected or missing declarative fields")


def text(value, length=1000):
    if (not isinstance(value, str) or not value.strip() or len(value) > length
            or any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise ValueError("invalid bounded text")
    return value


def number(value, low=0, high=100):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("non-finite or unbounded geometry/value")
    return value


def brief_contract(b, mode="real"):
    keys(b, ("product", "secondary_name", "fictional", "audience", "positioning", "qualities", "avoid", "sources", "interpretations"))
    text(b["product"], 24)
    text(b["secondary_name"], 28)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 .&'-]{1,23}", b["product"]):
        raise ValueError("v1 supports bounded Latin/LTR brand names")
    if not isinstance(b["fictional"], bool) or mode not in ("real", "fixture"):
        raise ValueError("explicit real/fictional mode required")
    if mode == "real" and b["fictional"]:
        raise ValueError("real entry refuses fictional bypass; use separate fixture")
    if mode == "fixture" and (not b["fictional"] or "temper" in b["product"].casefold()):
        raise ValueError("fixture refuses real Temper artwork")
    for field in ("audience", "positioning"):
        text(b[field], 900)
    for field in ("qualities", "avoid", "interpretations"):
        if not isinstance(b[field], list) or not 1 <= len(b[field]) <= 12:
            raise ValueError("bounded brief list required")
        for item in b[field]:
            text(item, 600)
    if not isinstance(b["sources"], list) or not 1 <= len(b["sources"]) <= 16:
        raise ValueError("sourced brief required")
    ids = set()
    for row in b["sources"]:
        keys(row, ("id", "location", "fact", "status"))
        if not re.fullmatch(r"[a-z0-9-]{1,40}", row["id"]) or row["id"] in ids:
            raise ValueError("source ids must be unique slugs")
        ids.add(row["id"])
        text(row["location"], 350)
        text(row["fact"], 900)
        if row["status"] not in ("documented", "observed", "claim", "inference", "namesake"):
            raise ValueError("fact/interpretation status required")
    return b


def path_points(commands):
    if not isinstance(commands, list) or not 4 <= len(commands) <= 64:
        raise ValueError("bounded closed path required")
    opened = False
    points = []
    for c in commands:
        if not isinstance(c, list) or not c or c[0] not in {"M", "L", "C", "Z"}:
            raise ValueError("unsupported path command")
        if len(c) != {"M": 3, "L": 3, "C": 7, "Z": 1}[c[0]]:
            raise ValueError("wrong path command arity")
        if c[0] == "M":
            if opened:
                raise ValueError("unclosed subpath")
            opened = True
        elif not opened:
            raise ValueError("path must start with M")
        elif c[0] == "Z":
            opened = False
        for i in range(1, len(c), 2):
            points.append((number(c[i]), number(c[i + 1])))
    if opened or not points:
        raise ValueError("unclosed path")
    return points


def shape_contract(s):
    if not isinstance(s, dict):
        raise ValueError("shape object required")
    kind = s.get("kind")
    if kind == "path":
        keys(s, ("kind", "name", "commands"))
        pts = path_points(s["commands"])
        xs, ys = zip(*pts, strict=True)
        if max(xs) - min(xs) < 1 or max(ys) - min(ys) < 1:
            raise ValueError("degenerate path")
    elif kind in ("rect", "ellipse"):
        keys(s, ("kind", "name", "x", "y", "w", "h"), ("r",) if kind == "rect" else ())
        for k in ("x", "y", "w", "h"):
            number(s[k])
        if min(s["w"], s["h"]) < 1 or s["x"] + s["w"] > 100 or s["y"] + s["h"] > 100:
            raise ValueError("shape outside normalized symbol")
        if "r" in s:
            number(s["r"], 0, min(s["w"], s["h"]) / 2)
    else:
        raise ValueError("only original rect/ellipse/closed path shapes allowed")
    text(s["name"], 48)
    return s


def concept_contract(c, b):
    keys(c, ("id", "name", "idea", "source_ids", "tradeoff", "symbol", "minimum_symbol_px", "wordmark_weight"))
    if not isinstance(c["id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", c["id"]):
        raise ValueError("concept slug required")
    for field, maximum in (("name", 32), ("idea", 700), ("tradeoff", 500)):
        text(c[field], maximum)
    if not isinstance(c["source_ids"], list) or not c["source_ids"] or not set(c["source_ids"]) <= {r["id"] for r in b["sources"]}:
        raise ValueError("concept must cite supplied evidence, not invented sources")
    if not isinstance(c["symbol"], list) or not 1 <= len(c["symbol"]) <= 8:
        raise ValueError("bounded original symbol required")
    for s in c["symbol"]:
        shape_contract(s)
    if sum(len(s.get("commands", [])) for s in c["symbol"]) > 192:
        raise ValueError("too many path commands")
    if c["minimum_symbol_px"] not in (16, 24, 32) or c["wordmark_weight"] not in ("400", "600"):
        raise ValueError("unsupported size or licensed font variant")
    return c


def exploration_contract(v, b):
    keys(v, ("product", "concepts"))
    if v["product"] != b["product"] or not isinstance(v["concepts"], list) or len(v["concepts"]) != 6:
        raise ValueError("six brief-specific concepts required")
    for c in v["concepts"]:
        concept_contract(c, b)
    if len({c["id"] for c in v["concepts"]}) != 6 or len({digest(c["symbol"]) for c in v["concepts"]}) != 6:
        raise ValueError("duplicate concepts, not divergent exploration")
    return v


def luminance(c):
    vals = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    vals = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in vals]
    return sum(a * b for a, b in zip(vals, (.2126, .7152, .0722), strict=True))


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return round((hi + .05) / (lo + .05), 3)


def palette_contract(p):
    keys(p, ROLES)
    for v in p.values():
        if not isinstance(v, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            raise ValueError("palette needs sRGB hex roles")
    pairs = [("ink", "paper", 4.5), ("muted", "paper", 4.5), ("ink", "surface", 4.5),
             ("paper", "ink", 4.5), ("accent_on", "accent", 4.5), ("accent", "paper", 3), ("accent", "ink", 3)]
    if any(contrast(p[a], p[b]) < bar for a, b, bar in pairs):
        raise ValueError("companion palette contrast contract failed")
    return {k: v.upper() for k, v in p.items()}


def shortlist_contract(v, b, concepts):
    keys(v, ("product", "shortlist", "recommendation", "recommendation_reason"))
    if v["product"] != b["product"] or not isinstance(v["shortlist"], list) or len(v["shortlist"]) != 3:
        raise ValueError("three palette directions required")
    ids = {c["id"] for c in concepts}
    for row in v["shortlist"]:
        keys(row, ("id", "palette", "rationale"))
        if row["id"] not in ids:
            raise ValueError("unknown shortlisted symbol")
        row["palette"] = palette_contract(row["palette"])
        text(row["rationale"], 700)
    if len({r["id"] for r in v["shortlist"]}) != 3 or v["recommendation"] not in {r["id"] for r in v["shortlist"]}:
        raise ValueError("distinct shortlist and advisory recommendation required")
    text(v["recommendation_reason"], 900)
    return v


def critique_contract(v, b, ids):
    keys(v, ("product", "observations", "recommendation", "recommendation_reason", "limitations"))
    if v["product"] != b["product"] or v["recommendation"] not in ids or not isinstance(v["observations"], list) or len(v["observations"]) > 14:
        raise ValueError("bounded logo-specific critique required")
    for row in v["observations"]:
        keys(row, ("scope", "id", "kind", "element", "location", "evidence", "suggestion"))
        if row["scope"] not in ("concept", "contract") or row["id"] not in (ids if row["scope"] == "concept" else set("ABCDE")):
            raise ValueError("critic finding needs actual board location")
        if row["kind"] not in ("measured", "visual", "taste", "similarity"):
            raise ValueError("facts and taste must remain separate")
        for k, n in (("element", 120), ("location", 120), ("evidence", 500), ("suggestion", 400)):
            text(row[k], n)
    text(v["recommendation_reason"], 900)
    text(v["limitations"], 1000)
    return v


def refinement_contract(v, b, selected):
    keys(v, ("product", "concept", "palette", "changes", "declined"))
    if v["product"] != b["product"] or v["concept"]["id"] != selected:
        raise ValueError("refinement cannot rename product/change selected direction")
    concept_contract(v["concept"], b)
    v["palette"] = palette_contract(v["palette"])
    for k in ("changes", "declined"):
        if not isinstance(v[k], list) or len(v[k]) > 8:
            raise ValueError("bounded review disposition required")
        for row in v[k]:
            text(row, 600)
    return v


def budget_contract(v, cost_cap):
    day = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    for k in ("reserve_usd", "day_spent_usd", "trial_spent_usd", "trial_envelope_usd"):
        number(v.get(k), 0, 10)
    if v.get("pacific_day") != day or v["reserve_usd"] < cost_cap or v["day_spent_usd"] + v["reserve_usd"] > 10:
        raise ValueError("stale/insufficient Pacific-day reservation")
    if v["trial_spent_usd"] + v["reserve_usd"] > v["trial_envelope_usd"]:
        raise ValueError("whole trial envelope exceeded")
    if v.get("subscription_checked") is not True or v.get("one_design_experiment") is not True:
        raise ValueError("fresh allowance and one experiment checks required")
    text(v.get("reconciliation"), 1200)
    return v


def approval_contract(v, *, kind, run_id, brief_hash, artifact_hash, choices, gate_only, fictional=False):
    if not gate_only:
        raise ValueError("ordinary input cannot bypass native human gate")
    keys(v, ("approval", "run_id", "brief_hash", "artifact_hash", "decision", "reason"), ("owner_note",))
    if fictional:
        if v["approval"] != "fixture-test":
            raise ValueError("fictional fixture must not claim real owner approval")
    elif v["approval"] != "owner-" + kind:
        raise ValueError("real artwork requires actual owner gate answer")
    if (v["run_id"], v["brief_hash"], v["artifact_hash"]) != (run_id, brief_hash, artifact_hash):
        raise ValueError("approval is for a different run/brief/artifact")
    if v["decision"] not in choices:
        raise ValueError("unknown owner decision")
    text(v["reason"], 1200)
    if "owner_note" in v:
        text(v["owner_note"], 1200)
    return v


def safe_svg(data):
    """Verify real exported XML; inline licensed WOFF is the only data URL."""
    if len(data) > 8_000_000:
        raise ValueError("oversized SVG")
    source = data.decode("utf-8")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", source, re.I):
        raise ValueError("SVG document declarations/resources forbidden")
    root = ET.fromstring(source)
    tags = {"svg", "g", "defs", "clipPath", "mask", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "style", "title", "desc", "linearGradient", "radialGradient", "stop", "use"}
    vectors, texts = 0, 0
    for e in root.iter():
        tag = e.tag.split("}")[-1]
        if tag not in tags:
            raise ValueError("unsafe SVG element")
        vectors += tag in {"path", "rect", "circle", "ellipse", "polygon"}
        texts += tag in {"text", "tspan"}
        for key, value in e.attrib.items():
            key = key.split("}")[-1]
            if key.lower().startswith("on") or (key == "href" and not value.startswith("#")):
                raise ValueError("SVG event/external reference forbidden")
            if re.search(r"javascript:|data:|https?://|file:|(?<!:)//", value, re.I):
                raise ValueError("SVG external/embedded resource forbidden")
            if key in ("d", "transform", "viewBox", "x", "y", "width", "height", "rx", "ry", "r", "cx", "cy", "points"):
                if re.search(r"nan|inf", value, re.I):
                    raise ValueError("non-finite SVG geometry")
                for n in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", value):
                    number(float(n), -1_000_000, 1_000_000)
        if tag == "style":
            css = e.text or ""
            if re.search(r"@import|expression\s*\(|javascript:|https?://|file:", css, re.I):
                raise ValueError("external/active SVG CSS forbidden")
            for url in re.findall(r"url\(\s*['\"]?([^)'\"]+)", css):
                if not url.startswith("#") and not re.fullmatch(r"data:font/woff;base64,[A-Za-z0-9+/=]+", url):
                    raise ValueError("SVG CSS only permits local refs/embedded licensed fonts")
    if not vectors:
        raise ValueError("SVG lacks actual vectors")
    return {"vectors": vectors, "text_elements": texts, "external_resources": 0, "unsafe_elements": 0}
