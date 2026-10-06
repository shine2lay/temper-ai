"""Design-owned logo v1 contracts: declarative vectors, not executable SVG.

No model/network/Penpot dependencies. A native human gate is a trusted host
boundary, not a model's JSON claim. No ordinary input can approve artwork.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

VERSION = 2
ROLES = ("ink", "paper", "accent", "accent_on", "muted", "surface")
# Concept families. Plain geometry alone was rejected by the owner in the first
# real Temper round as not memorable, so it may fill at most two of six slots.
FAMILIES = ("geometric", "letterform", "pictorial", "emblem")
EXPLORE_AGAIN = "explore-again"
# Optional per-shape colour: a part marked tone 'accent' draws in the palette accent in
# colour versions (two-tone mark); one-colour versions draw every part alike.
ACCENT_TONE = "accent"
CAPS = {"explore": 2.25, "revise": .75, "coldread": .5, "names": .4, "palette": 1.0, "critic": .85, "refine": 1.0}
# Every shown set of symbols gets a caption-free cold read and a same-name check.
COLD_RESERVE = round(CAPS["coldread"] + CAPS["names"], 2)  # .9
# Stage reserves before each budget gate: everything up to the next direction/final gate.
INITIAL_RESERVE = round(CAPS["explore"] + CAPS["revise"] + COLD_RESERVE + CAPS["palette"] + CAPS["critic"], 2)  # 5.75
REFINE_RESERVE = round(CAPS["refine"] + COLD_RESERVE + CAPS["critic"], 2)  # 2.75
FULL_ESTIMATE = round(INITIAL_RESERVE + 2 * REFINE_RESERVE + .35, 2)  # 11.6 incl. .35 headroom; not CLI caps
# Cold read: what a symbol looks like with no caption, at a glance (32 px) and close up (128 px).
COLD_SIZES = ("32", "128")
COLD_READINGS = 3
SIZES = (16, 24, 32, 48, 64)
SCHEMA = """Return only one JSON object (no Markdown/code fence).
Explore: {product:<exact brief product>, concepts:[exactly six objects]}.
Each concept: {id:<slug>, name:<up to32>, family:'geometric'|'letterform'|'pictorial'|'emblem',
 idea:<up to700>, ownable_detail:<up to300: the one visible detail people would remember>,
 generic_risk:<up to300: the common mark family it could be mistaken for>,
 source_ids:[brief source ids], tradeoff:<up to500>, symbol:[1..8 shape objects],
 minimum_symbol_px:16|24|32, wordmark_weight:'400'|'600'}.
At least three different families across the six; at most two 'geometric'.
letterform = an original drawn letter/monogram from the name (paths, not font
outlines); pictorial = a stylised, non-literal image of the idea; emblem = a
contained shape whose inner negative space carries the idea.
Revise: {product:<exact>, concepts:[the same six ids in the same order, full
 concept schema, symbols redrawn where the render did not show the idea],
 revisions:[up to6 {id, seen:<up to500: what the rendered PNG actually shows>,
 change:<up to500: what you redrew and why>}]}.
Rect: {kind:'rect',name:<up to48>,x:0..100,y:0..100,w:>0,h:>0,r:0..min(w,h)/2}.
Ellipse: {kind:'ellipse',name:<up to48>,x,y,w,h}.
Path: {kind:'path',name:<up to48>,commands:[["M",x,y],["L",x,y],
 ["C",c1x,c1y,c2x,c2y,x,y],["Z"]...]}. All coordinates finite 0..100.
Paths must close every subpath; max64 commands/path,192 total/concept. Filled
silhouettes only, no strokes, SVG strings, images, transforms, URLs, code or icons.
Optional colour: any shape may add tone:'accent' to draw that part in the palette
accent in colour versions (a two-tone colour mark); keep at least one shape untoned.
Monochrome/one-colour versions draw every shape alike, so the idea must still read
when accent parts merge with the rest.
Use negative space between original shapes; do not fake counters with background
patches. No fixed Temper catalogue. Generate forms from this brief. Existing font
Source Sans Pro regular/semibold only; text remains live. No fabricated approval.
Palette: {product:<exact>,shortlist:[exactly3 objects],recommendation:<selected id>,
 recommendation_reason:<up to900>}. Each row: {id:<existing concept id>,
 palette:{ink,paper,accent,accent_on,muted,surface:<#RRGGBB>}, rationale:<up to700>}.
ink/paper, muted/paper, ink/surface, paper/ink, accent_on/accent must >=4.5;
accent/paper and accent/ink >=3 for demonstrated essential graphics. Logo/logotype
exemptions are separate from ordinary companion text/UI. Never use accent as a
status/error semantic. Shortlist THREE DIFFERENT ideas/forms, not recolours,
from at least two different families.
Refine: {product:<exact>,concept:<same concept schema and selected id>,
 palette:<same6role schema>, changes:[up to8 evidence-specific strings],
 declined:[up to8 reasoned strings]}. Respect the saved selection and the gate note;
no silent change to direction, product or approval. Max TWO planned rounds;
the host allows one extra round only when the final gate asks for it.
Cold read: {readings:[one per shown symbol label: {label:<S1..>, glance_32:[exactly3
 distinct readings, up to80 each, most likely first], close_128:[exactly3, same rule]}]}.
A reading names what the image looks like (an object, letter, sign or shape), never
what it is meant to be; there is no caption, brief or product name to go on.
Name check: {resemblance:[one per lockup label and same-name mark: {label:<S1..>,
 mark:<mark file name>, close:true|false, why:<up to300>}]}.
First reads (palette rows and critic, whenever logo/coldread-*.saved.json exists):
 every saved cold-read reading of a symbol, quoted exactly, with its size:
 {reading:<exact saved text>, size:'32'|'128', fits_idea:true|false, note:<up to200:
 how it agrees or conflicts with the concept's idea>}; fits_idea false is a conflict.
 name_marks: one {mark, note:<up to300>} per same-name mark the check flagged close.
Palette row with a cold read: {id, palette, rationale, first_reads:[all six readings
 of that symbol], name_marks:[its close marks]}.
Critic with a cold read adds first_reads:[{id, reading, size, fits_idea, note}] for
 every reading of every reviewed id, and name_marks:[{id, mark, note}] for every close
 flag of a reviewed id.
Critic: {product:<exact>,observations:[up to14],recommendation:<id>,
 recommendation_reason:<up to900>,limitations:<up to1000>}.
Observation: {scope:'concept'|'contract',id:<concept id or contract cell A..E>,
 kind:'measured'|'visual'|'taste'|'similarity',element:<up to120>,
 location:<up to120>,evidence:<up to500>,suggestion:<up to400>}.
No aesthetic scores. Recommendations are advice, not gate decisions. Contract
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


def prose(value, length):
    """Model-written explanation: a modest overrun is shortened, not a failed paid stage.

    Real run ad5c270f lost its round-1 critic save to one 129-character location
    against a 120 bound, then its round-2 refinement save to a 49-character layer
    name against 48. Every model-written label or explanation (layer and concept
    names, concept prose, critic and palette prose) goes through here. Ids, enums,
    brief/owner words and geometry stay strict (text()); anything beyond four times
    its bound is still rejected as unbounded.
    """
    if isinstance(value, str) and length < len(value) <= 4 * length:
        value = value[:length - 1].rstrip() + "\u2026"
    return text(value, length)


def number(value, low=0, high=100):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("non-finite or unbounded geometry/value")
    return value


def research_contract(r):
    """Dated research screen handed to a run: host folder plus pinned file hashes.

    Files are research references (official pages, rejected earlier boards), never
    brand assets. The brief stage copies them into the run and re-checks hashes.
    """
    keys(r, ("dir", "files"), ("same_name",))
    folder = PurePosixPath(r["dir"]) if isinstance(r["dir"], str) else None
    if folder is None or not folder.is_absolute() or ".." in folder.parts or len(r["dir"]) > 300:
        raise ValueError("research folder must be an absolute path without ..")
    files = r["files"]
    if not isinstance(files, dict) or not 1 <= len(files) <= 16 or "comparison.md" not in files:
        raise ValueError("research needs comparison.md and at most 16 pinned files")
    for name, digest_value in files.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}\.(png|md)", name):
            raise ValueError("research file names are plain png/md names")
        if not isinstance(digest_value, str) or not re.fullmatch(r"[0-9a-f]{64}", digest_value):
            raise ValueError("research files are pinned by sha256")
    # Marks of other products with the same name: the cold read's name check compares
    # every shown lockup with each at small size.
    same = r.get("same_name", [])
    if (not isinstance(same, list) or len(same) > 6 or len(set(same)) != len(same)
            or not all(isinstance(n, str) and n.endswith(".png") and n in files for n in same)):
        raise ValueError("same-name marks must be distinct pinned research PNGs (at most six)")
    return r


# Who answers a gate (gate convention, Design DIRECTIVES 2026-10-04): the chat running the
# workflow answers as Design; "owner" only for the owner's own words (kept verbatim, they
# outrank); "fixture-test" for fictional fixture runs. Gates are named for what they decide.
REAL_DECIDERS = ("design", "owner")
FIXTURE_DECIDER = "fixture-test"
# Records written before 2026-10-05 named the answerer "owner" whoever answered. They are read
# through these fallbacks and never rewritten.
LEGACY_APPROVAL = {"owner-direction": "owner", "owner-final": "owner", "fixture-test": FIXTURE_DECIDER}


def decided_by(record):
    """Who answered a saved gate record, new or legacy (approval: owner-<gate>)."""
    if record.get("decided_by"):
        return record["decided_by"]
    return LEGACY_APPROVAL.get(record.get("approval"))


def gate_note(record):
    """The answer's own guidance note, new (note) or legacy (owner_note) record."""
    note = record.get("note")
    return note if note is not None else record.get("owner_note")


def prior_answer(row):
    """(answer, source, decided_by) of a prior-round row, new or legacy (owner_answer/owner_source)."""
    if "answer" in row:
        return row["answer"], row["source"], row["decided_by"]
    return row["owner_answer"], row["owner_source"], "owner"


def prior_round_contract(row, research_files, mode="real"):
    """An earlier round the direction gate rejected; carried so the next round avoids it.

    A real brief carries rounds decided_by design or owner; a fixture brief may also carry a
    fixture round (decided_by fixture-test), never claimed as anyone's decision.
    Legacy rows (owner_answer, owner_source) from briefs written before 2026-10-05 still load."""
    if "owner_answer" in row:
        keys(row, ("run_id", "owner_answer", "owner_source", "rejected", "evidence"))
    else:
        keys(row, ("run_id", "answer", "source", "decided_by", "rejected", "evidence"))
        allowed = REAL_DECIDERS + ((FIXTURE_DECIDER,) if mode == "fixture" else ())
        if row["decided_by"] not in allowed:
            raise ValueError("a prior round's answer is decided_by " + ", ".join(allowed[:-1]) + " or " + allowed[-1])
    answer, source, _ = prior_answer(row)
    uuid.UUID(str(row["run_id"]))
    text(answer, 600)
    text(source, 200)
    if not isinstance(row["rejected"], list) or not 1 <= len(row["rejected"]) <= 6:
        raise ValueError("rejected round lists its directions")
    for item in row["rejected"]:
        keys(item, ("id", "name", "idea"))
        text(item["id"], 32)
        text(item["name"], 32)
        text(item["idea"], 700)
    if (not isinstance(row["evidence"], list) or len(row["evidence"]) > 6
            or not set(row["evidence"]) <= set(research_files)):
        raise ValueError("rejected-round evidence must be pinned research files")
    return row


def brief_contract(b, mode="real"):
    keys(b, ("product", "secondary_name", "fictional", "audience", "positioning", "qualities", "avoid", "sources", "interpretations"),
         ("research", "prior_rounds", "context", "meaning", "fixed_palette"))
    text(b["product"], 24)
    # From the research step (design_research.py logo_brief): the playbook context id, the
    # product's meaning and an approved palette the logo must keep ({role: hex}).
    if "context" in b and not (isinstance(b["context"], str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,59}", b["context"])):
        raise ValueError("context is a playbook context id")
    if "meaning" in b:
        text(b["meaning"], 600)
    if "fixed_palette" in b:
        fp = b["fixed_palette"]
        if (not isinstance(fp, dict) or not 1 <= len(fp) <= 24
                or not all(isinstance(k, str) and re.fullmatch(r"[a-z0-9_.-]{1,40}", k) and isinstance(v, str)
                           and re.fullmatch(r"#[0-9A-Fa-f]{6}", v) for k, v in fp.items())):
            raise ValueError("fixed palette is {role: #RRGGBB}")
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
    files = research_contract(b["research"])["files"] if "research" in b else {}
    if "prior_rounds" in b:
        if not isinstance(b["prior_rounds"], list) or not 1 <= len(b["prior_rounds"]) <= 2:
            raise ValueError("at most two earlier rejected rounds")
        for row in b["prior_rounds"]:
            prior_round_contract(row, files, mode)
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
        keys(s, ("kind", "name", "commands"), ("tone",))
        pts = path_points(s["commands"])
        xs, ys = zip(*pts, strict=True)
        if max(xs) - min(xs) < 1 or max(ys) - min(ys) < 1:
            raise ValueError("degenerate path")
    elif kind in ("rect", "ellipse"):
        keys(s, ("kind", "name", "x", "y", "w", "h"), ("r", "tone") if kind == "rect" else ("tone",))
        for k in ("x", "y", "w", "h"):
            number(s[k])
        if min(s["w"], s["h"]) < 1 or s["x"] + s["w"] > 100 or s["y"] + s["h"] > 100:
            raise ValueError("shape outside normalized symbol")
        if "r" in s:
            number(s["r"], 0, min(s["w"], s["h"]) / 2)
    else:
        raise ValueError("only original rect/ellipse/closed path shapes allowed")
    if "tone" in s and s["tone"] != ACCENT_TONE:
        raise ValueError("shape tone may only be the palette accent role")
    s["name"] = prose(s["name"], 48)
    return s


def concept_contract(c, b):
    keys(c, ("id", "name", "family", "idea", "ownable_detail", "generic_risk", "source_ids", "tradeoff",
             "symbol", "minimum_symbol_px", "wordmark_weight"))
    if not isinstance(c["id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", c["id"]) or c["id"] == EXPLORE_AGAIN:
        raise ValueError("concept slug required")
    if c["family"] not in FAMILIES:
        raise ValueError("unknown concept family")
    for field, maximum in (("name", 32), ("idea", 700), ("ownable_detail", 300), ("generic_risk", 300), ("tradeoff", 500)):
        c[field] = prose(c[field], maximum)
    if not isinstance(c["source_ids"], list) or not c["source_ids"] or not set(c["source_ids"]) <= {r["id"] for r in b["sources"]}:
        raise ValueError("concept must cite supplied evidence, not invented sources")
    if not isinstance(c["symbol"], list) or not 1 <= len(c["symbol"]) <= 8:
        raise ValueError("bounded original symbol required")
    for s in c["symbol"]:
        shape_contract(s)
    if all(s.get("tone") == ACCENT_TONE for s in c["symbol"]):
        raise ValueError("a colour mark keeps at least one untoned part")
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
    families = [c["family"] for c in v["concepts"]]
    if len(set(families)) < 3 or families.count("geometric") > 2:
        raise ValueError("exploration needs three families and at most two plain geometric marks")
    return v


def revision_contract(v, b, draft):
    """The explorer's second pass after seeing its own render: same six slots."""
    keys(v, ("product", "concepts", "revisions"))
    exploration_contract({"product": v["product"], "concepts": v["concepts"]}, b)
    if [c["id"] for c in v["concepts"]] != [c["id"] for c in draft["concepts"]]:
        raise ValueError("revision keeps the same six concept ids in order")
    if not isinstance(v["revisions"], list) or len(v["revisions"]) > 6:
        raise ValueError("bounded revision notes required")
    seen = set()
    for row in v["revisions"]:
        keys(row, ("id", "seen", "change"))
        if row["id"] not in {c["id"] for c in v["concepts"]} or row["id"] in seen:
            raise ValueError("revision note must name one concept once")
        seen.add(row["id"])
        row["seen"] = prose(row["seen"], 500)
        row["change"] = prose(row["change"], 500)
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


def _reading_key(value):
    return " ".join(str(value).split()).casefold().rstrip(".!")


def readings_contract(v, labels):
    """Caption-free first readings: three distinct readings per symbol at 32 px and at 128 px."""
    keys(v, ("readings",))
    rows = v["readings"]
    if not isinstance(rows, list) or len(rows) != len(labels):
        raise ValueError("cold read must cover every shown symbol exactly once")
    by_label = {}
    for row in rows:
        keys(row, ("label", "glance_32", "close_128"))
        if row["label"] not in labels or row["label"] in by_label:
            raise ValueError("cold read must cover every shown symbol exactly once")
        for key in ("glance_32", "close_128"):
            if not isinstance(row[key], list) or len(row[key]) != COLD_READINGS:
                raise ValueError("three readings per symbol and size")
            row[key] = [prose(reading, 80) for reading in row[key]]
            if len({_reading_key(r) for r in row[key]}) != COLD_READINGS:
                raise ValueError("three distinct readings per symbol and size")
        by_label[row["label"]] = row
    return {"readings": [by_label[label] for label in labels]}


def names_contract(v, labels, marks):
    """Same-name check: every shown lockup against every same-name mark, close or not."""
    keys(v, ("resemblance",))
    rows = v["resemblance"]
    if not isinstance(rows, list):
        raise ValueError("name check needs a resemblance list")
    seen = {}
    for row in rows:
        keys(row, ("label", "mark", "close", "why"))
        pair = (row["label"], row["mark"])
        if row["label"] not in labels or row["mark"] not in marks or pair in seen or not isinstance(row["close"], bool):
            raise ValueError("name check rows must pair a shown lockup with a same-name mark once")
        row["why"] = prose(row["why"], 300)
        seen[pair] = row
    if len(seen) != len(labels) * len(marks):
        raise ValueError("name check must compare every shown lockup with every same-name mark")
    return {"resemblance": [seen[label, mark] for label in labels for mark in marks]}


def first_reads_contract(rows, readings, intended_id=None):
    """Every saved reading of one or more symbols, quoted exactly, each judged against the idea.

    readings: {id: [{size, reading}]}. With intended_id the rows carry no id (one symbol).
    """
    if not isinstance(rows, list):
        raise ValueError("first reads must be a list")
    wanted = {(i, r["size"], _reading_key(r["reading"])): r["reading"] for i, items in readings.items() for r in items}
    out, seen = [], set()
    for row in rows:
        if intended_id is None:
            keys(row, ("id", "reading", "size", "fits_idea", "note"))
            ident = row["id"]
        else:
            keys(row, ("reading", "size", "fits_idea", "note"))
            ident = intended_id
        # Sizes are the strings '32' and '128'; a model may write them as numbers.
        size = str(row["size"]) if isinstance(row["size"], (int, str)) and not isinstance(row["size"], bool) else ""
        reading = row["reading"] if isinstance(row["reading"], str) else ""
        key = (ident, size, _reading_key(reading))
        if key not in wanted or key in seen or not isinstance(row["fits_idea"], bool):
            raise ValueError("first reads must quote each saved cold-read reading exactly once")
        seen.add(key)
        item = {"reading": wanted[key], "size": size, "fits_idea": row["fits_idea"], "note": prose(row["note"], 200)}
        out.append(item if intended_id is not None else {"id": ident, **item})
    if seen != set(wanted):
        raise ValueError("first reads must cover every saved cold-read reading")
    return out


def name_marks_contract(rows, close, intended_id=None):
    """One note per same-name mark the name check flagged close. close: {id: [mark]}."""
    if not isinstance(rows, list):
        raise ValueError("name marks must be a list")
    wanted = {(i, m) for i, marks in close.items() for m in marks}
    out, seen = [], set()
    for row in rows:
        if intended_id is None:
            keys(row, ("id", "mark", "note"))
            ident = row["id"]
        else:
            keys(row, ("mark", "note"))
            ident = intended_id
        if (ident, row["mark"]) not in wanted or (ident, row["mark"]) in seen:
            raise ValueError("name marks must carry each close same-name flag exactly once")
        seen.add((ident, row["mark"]))
        item = {"mark": row["mark"], "note": prose(row["note"], 300)}
        out.append(item if intended_id is not None else {"id": ident, **item})
    if seen != wanted:
        raise ValueError("name marks must carry every close same-name flag")
    return out


def shortlist_contract(v, b, concepts, cold=None):
    """cold: the saved cold read of these concepts ({id: {readings, close}}); rows must quote it."""
    keys(v, ("product", "shortlist", "recommendation", "recommendation_reason"))
    if v["product"] != b["product"] or not isinstance(v["shortlist"], list) or len(v["shortlist"]) != 3:
        raise ValueError("three palette directions required")
    ids = {c["id"] for c in concepts}
    for row in v["shortlist"]:
        if cold is None:
            keys(row, ("id", "palette", "rationale"))
        else:
            keys(row, ("id", "palette", "rationale", "first_reads", "name_marks"))
        if row["id"] not in ids:
            raise ValueError("unknown shortlisted symbol")
        row["palette"] = palette_contract(row["palette"])
        row["rationale"] = prose(row["rationale"], 700)
        if cold is not None:
            if row["id"] not in cold:
                raise ValueError("shortlisted symbol has no saved cold read")
            row["first_reads"] = first_reads_contract(row["first_reads"], {row["id"]: cold[row["id"]]["readings"]}, row["id"])
            row["name_marks"] = name_marks_contract(row["name_marks"], {row["id"]: cold[row["id"]]["close"]}, row["id"])
    if len({r["id"] for r in v["shortlist"]}) != 3 or v["recommendation"] not in {r["id"] for r in v["shortlist"]}:
        raise ValueError("distinct shortlist and advisory recommendation required")
    family = {c["id"]: c["family"] for c in concepts}
    if len({family[r["id"]] for r in v["shortlist"]}) < 2:
        raise ValueError("shortlist needs at least two concept families")
    v["recommendation_reason"] = prose(v["recommendation_reason"], 900)
    return v


def fixed_palette_check(v, b):
    """An approved palette is a fixed constraint: every logo role takes one of the approved
    colours (or plain white paper). Role names are not matched, because a product's token
    names (dominant, accent, on-accent ...) mean other things than the logo roles."""
    fixed = {k: x.upper() for k, x in b.get("fixed_palette", {}).items()}
    if not fixed:
        return v
    allowed = set(fixed.values()) | {"#FFFFFF"}
    for row in v["shortlist"]:
        if not {x.upper() for x in row["palette"].values()} <= allowed:
            raise ValueError("shortlist uses colours outside the approved palette")
    return v


def fit_fixed_palette(fixed):
    """The logo roles filled from approved colours only, passing the companion contrast;
    roles named like an approved colour keep it where contrast allows."""
    import itertools
    fixed = {k: x.upper() for k, x in fixed.items()}
    colours = sorted(set(list(dict.fromkeys(fixed.values()))[:8]) | {"#FFFFFF"})  # bounded search
    best, score = None, -1
    for combo in itertools.product(colours, repeat=len(ROLES)):
        p = dict(zip(ROLES, combo, strict=True))
        try:
            palette_contract(p)
        except ValueError:
            continue
        s = sum(p[r] == fixed.get(r) for r in ROLES) * 2 + (p["paper"] == "#FFFFFF") + len(set(combo))
        if s > score:
            best, score = p, s
    if best is None:
        raise ValueError("approved palette cannot meet the companion contrast")
    return best


def critique_contract(v, b, ids, cold=None):
    """cold: saved cold read ({id: {readings, close}}); the critic must quote and judge it."""
    base = ("product", "observations", "recommendation", "recommendation_reason", "limitations")
    keys(v, base if cold is None else base + ("first_reads", "name_marks"))
    if cold is not None:
        if not set(ids) <= set(cold):
            raise ValueError("reviewed symbol has no saved cold read")
        v["first_reads"] = first_reads_contract(v["first_reads"], {i: cold[i]["readings"] for i in ids})
        v["name_marks"] = name_marks_contract(v["name_marks"], {i: cold[i]["close"] for i in ids})
    if v["product"] != b["product"] or v["recommendation"] not in ids or not isinstance(v["observations"], list) or len(v["observations"]) > 14:
        raise ValueError("bounded logo-specific critique required")
    for row in v["observations"]:
        keys(row, ("scope", "id", "kind", "element", "location", "evidence", "suggestion"))
        if row["scope"] not in ("concept", "contract") or row["id"] not in (ids if row["scope"] == "concept" else set("ABCDE")):
            raise ValueError("critic finding needs actual board location")
        if row["kind"] not in ("measured", "visual", "taste", "similarity"):
            raise ValueError("facts and taste must remain separate")
        for k, n in (("element", 120), ("location", 120), ("evidence", 500), ("suggestion", 400)):
            row[k] = prose(row[k], n)
    v["recommendation_reason"] = prose(v["recommendation_reason"], 900)
    v["limitations"] = prose(v["limitations"], 1000)
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
        v[k] = [prose(row, 600) for row in v[k]]
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


PLANNED_ROUNDS = 2
EXTRA_ROUND = PLANNED_ROUNDS + 1  # one more, only when the final gate asks for it; never a fourth


def extra_round_contract(record, reservation, *, run_id, brief_hash, artifact_hash):
    """A round past the planned two needs both: a real final-gate 'revise' with its own note
    (decided_by design or owner), recorded by the native final gate of the last planned round,
    and a fresh refine budget gate answer naming that same note. Neither alone starts paid work.
    Legacy final records (approval owner-final, owner_note) still count."""
    if decided_by(record) not in REAL_DECIDERS or record.get("fictional_test") is not False:
        raise ValueError("extra round needs a real final-gate answer")
    if (record.get("run_id"), record.get("brief_hash"), record.get("artifact_hash")) != (run_id, brief_hash, artifact_hash):
        raise ValueError("extra-round request is for a different run/brief/artifact")
    note = gate_note(record)
    if record.get("decision") != "revise" or not isinstance(note, str) or not note.strip():
        raise ValueError("extra round needs the final gate's revise with its own note")
    text(note, 1200)
    if reservation.get("extra_round_note", reservation.get("extra_round_owner_note")) != note:
        raise ValueError("refine budget gate must name the final gate's extra-round note")
    return note


def approval_contract(v, *, kind, run_id, brief_hash, artifact_hash, choices, gate_only, fictional=False):
    """A direction or final gate answer: who decided (decided_by), the choice and the reasons."""
    if not gate_only:
        raise ValueError("ordinary input cannot bypass native human gate")
    if "approval" in v or "owner_note" in v:
        raise ValueError("approval/owner_note are retired: answer with decided_by (design, owner or fixture-test), reason and note")
    keys(v, ("decided_by", "run_id", "brief_hash", "artifact_hash", "decision", "reason"), ("note", "source"))
    if fictional:
        if v["decided_by"] != FIXTURE_DECIDER:
            raise ValueError("fictional fixture answers are decided_by fixture-test")
    elif v["decided_by"] not in REAL_DECIDERS:
        raise ValueError(f"real artwork needs a {kind} gate answer decided_by design or owner")
    if v["decided_by"] == "owner":
        # Only the owner's own words make an owner answer: quoted in reason, with where he said them.
        if not isinstance(v.get("source"), str) or not v["source"].strip():
            raise ValueError("an owner answer needs source: where he said his words")
        text(v["source"], 300)
    elif "source" in v:
        raise ValueError("source names where the owner said his words; only decided_by owner has one")
    if (v["run_id"], v["brief_hash"], v["artifact_hash"]) != (run_id, brief_hash, artifact_hash):
        raise ValueError("approval is for a different run/brief/artifact")
    if v["decision"] not in choices:
        raise ValueError(f"unknown {kind} decision")
    text(v["reason"], 1200)
    if "note" in v:
        text(v["note"], 1200)
    if v["decision"] == EXPLORE_AGAIN and "note" not in v:
        raise ValueError("explore-again needs its own note")
    return {"gate": kind, **v}


def safe_svg(data):
    """Verify real exported XML; inline licensed WOFF is the only data URL."""
    if len(data) > 8_000_000:
        raise ValueError("oversized SVG")
    source = data.decode("utf-8")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", source, re.I):
        raise ValueError("SVG document declarations/resources forbidden")
    root = ET.fromstring(source)
    tags = {"svg", "g", "defs", "clipPath", "mask", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "style", "title", "desc", "linearGradient", "radialGradient", "stop", "use", "pattern"}
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
            if key in ("d", "transform", "patternTransform", "gradientTransform", "viewBox", "x", "y", "width", "height", "rx", "ry", "r", "cx", "cy", "points", "stroke-width", "font-size"):
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
