"""What the research step must contain (docs/design-files.md, Design queue #38). Model-free.

The research agents write JSON files in the run's research/ folder; the stage script checks them with
these functions and assembles research.json. The rules:

- every claim about the product or its users is sourced (a pack file or a web page, with an exact quote
  that is found there) or marked an assumption; a statement the pack makes without evidence is an
  assumption or rejected, and an older fact a newer source contradicts is superseded;
- evidence ids exist in the context playbook (configs/design/knowledge/context-playbook.json);
- every direction candidate is a style family the playbook allows for its context, quoted exactly;
- gate answers say who decided (design; owner only with his own words and where he said them;
  fixture-test in fixture runs) and why.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

VERSION = 1
PLAYBOOK = Path(__file__).resolve().parent.parent / "knowledge" / "context-playbook.json"
CLAIM_ID = re.compile(r"^c\d{1,3}$")
SITE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
EVIDENCE_ID = re.compile(r"^E\d{3}$")
TASTE_ID = re.compile(r"^T\d{1,3}$")
CLAIM_STATUS = ("sourced", "assumption", "rejected", "superseded")
NOTE_MAX = 600  # characters in a claim's note (why it is an assumption, rejected or superseded)
TOPICS = ("product", "value", "meaning", "users", "jobs", "expertise", "frequency", "devices", "setting", "stakes",
          "access", "trust", "buying", "context")
ROLES = ("primary", "secondary", "buyer")
SITE_KINDS = ("leader", "competitor", "adjacent")
MARK_FAMILIES = ("geometric", "letterform", "pictorial", "emblem", "wordmark", "none")
# The five audience axes a direction sets (and the concepts are measured on, design_axes.py).
AXES = {"density": ("low", "medium", "high"),
        "type_scale": ("compact", "medium", "large"),
        "colour_energy": ("low", "medium", "high"),
        "motion": ("low", "medium", "high"),
        "copy_tone": ("expert", "neutral", "friendly")}
CONTEXT_ROLES = ("page", "product", "audience")
PLAYBOOK_FIELDS = ("styles", "density", "depth", "motion", "colour", "type", "imagery", "avoid", "trust_signals",
                   "test_with_users", "evidence", "confidence")
REAL_DECIDERS = ("design", "owner")
FIXTURE_DECIDER = "fixture-test"
MIN_QUOTE = 12


def load_playbook(path: Path | str = PLAYBOOK) -> dict:
    return json.loads(Path(path).read_text())


def contexts_by_id(playbook: dict) -> dict[str, dict]:
    return {c["id"]: c for c in playbook["contexts"]}


def evidence_ids(playbook: dict) -> set[str]:
    return {e["id"] for e in playbook["evidence"]}


def allowed_families(context: dict) -> list[str]:
    return list(context["styles"].get("preferred", [])) + list(context["styles"].get("acceptable", []))


# ---------------------------------------------------------------- quotes

_MARKUP = re.compile(r"[*_`>#|]+")


def norm(text: str) -> str:
    """Text as compared for quotes: NFKC, straight quotes and dashes, markdown marks and spacing removed, lower case."""
    t = unicodedata.normalize("NFKC", str(text))
    t = t.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r"[\u2010-\u2015\u2212]", "-", t)
    t = _MARKUP.sub(" ", t)
    t = re.sub(r"^\s*[-+]\s+", " ", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip().lower()


def quote_in(quote: str, text: str) -> bool:
    q = norm(quote).strip(" .,:;\"'")
    return len(q) >= MIN_QUOTE and q in norm(text)


def _str(v: Any, lo: int = 1, hi: int = 400) -> bool:
    return isinstance(v, str) and lo <= len(v.strip()) <= hi


def _strs(v: Any, lo: int, hi: int, each: int = 300) -> bool:
    return isinstance(v, list) and lo <= len(v) <= hi and all(_str(x, 1, each) for x in v)


def _safe_rel(path: Any) -> bool:
    return isinstance(path, str) and bool(path) and not path.startswith("/") and ".." not in Path(path).parts


# ---------------------------------------------------------------- users research

def check_users(users: Any, workspace: Path | str, *, web: dict[str, str | None] | None = None,
                audience_only: bool = False) -> list[str]:
    """users.json: the product, user groups and claims; every claim sourced (quote found) or an assumption.

    Pack sources are paths relative to the workspace under source/ (source/docs/..., source/current-state/...).
    Web sources are https URLs; ``web`` maps each URL to the page's text (None when it could not be opened);
    without ``web`` a URL claim is a problem (fixture runs have no web).
    """
    ws = Path(workspace)
    if not isinstance(users, dict):
        return ["users.json is an object"]
    problems: list[str] = []
    allowed = {"product", "groups", "claims", "assumptions", "audience", "notes"}
    if set(users) - allowed:
        problems.append(f"unknown keys {sorted(set(users) - allowed)}")
    claims = users.get("claims")
    if not isinstance(claims, list) or not 3 <= len(claims) <= 80:
        return problems + ["claims lists 3-80 claims"]
    ids: dict[str, dict] = {}
    for i, c in enumerate(claims):
        where = f"claim {i + 1}"
        if not isinstance(c, dict):
            problems.append(f"{where} is an object")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not CLAIM_ID.match(cid) or cid in ids:
            problems.append(f"{where}: id is a unique c<number>")
            continue
        ids[cid] = c
    groups = users.get("groups")
    group_names: set[str] = set()
    if not isinstance(groups, list) or not (0 if audience_only else 1) <= len(groups) <= 6:
        problems.append("groups lists 1-6 user groups")
        groups = []
    for g in groups:
        if not isinstance(g, dict) or not _str(g.get("name"), 2, 60):
            problems.append("a group has a name (2-60 characters)")
            continue
        group_names.add(g["name"])
        if g.get("role") not in ROLES:
            problems.append(f"group {g['name']}: role is {', '.join(ROLES)}")
        if not _str(g.get("summary"), 10, 400):
            problems.append(f"group {g['name']}: summary is 10-400 characters")
        if not isinstance(g.get("aliases", []), list) or not all(_str(a, 2, 60) for a in g.get("aliases", [])):
            problems.append(f"group {g['name']}: aliases are short names")
        refs = g.get("claims")
        if not isinstance(refs, list) or not refs or any(r not in ids for r in refs):
            problems.append(f"group {g['name']}: claims lists ids of its claims")
    if [g.get("role") for g in groups if isinstance(g, dict)].count("primary") != 1 and groups:
        problems.append("exactly one group is primary (the people the design is mainly for)")
    for cid, c in ids.items():
        problems += [f"{cid}: {p}" for p in _check_claim(c, ids, group_names, ws, web)]
    product = users.get("product")
    if not audience_only:
        if not isinstance(product, dict):
            problems.append("product is {name, what, for_whom, value, meaning, claims}")
        else:
            for key in ("name", "what", "for_whom", "value", "meaning"):
                if not _str(product.get(key), 2, 500):
                    problems.append(f"product.{key} is 2-500 characters")
            refs = product.get("claims")
            if not isinstance(refs, list) or not refs or any(r not in ids for r in refs):
                problems.append("product.claims lists the ids of the claims it rests on")
            elif all(ids[r].get("status") != "sourced" for r in refs):
                problems.append("product rests on at least one sourced claim")
    if not _strs(users.get("assumptions", []), 0, 12):
        problems.append("assumptions lists at most 12 things to confirm")
    sourced = [c for c in ids.values() if c.get("status") == "sourced"]
    if len(sourced) < 3:
        problems.append("at least 3 claims are sourced")
    return problems


def _check_claim(c: dict, ids: dict, groups: set[str], ws: Path, web: dict | None) -> list[str]:
    problems = []
    allowed = {"id", "topic", "group", "text", "status", "source", "superseded_by", "note"}
    if set(c) - allowed:
        problems.append(f"unknown keys {sorted(set(c) - allowed)}")
    if c.get("topic") not in TOPICS:
        problems.append(f"topic is one of {', '.join(TOPICS)}")
    if "group" in c and c["group"] not in groups:
        problems.append("group names one of the groups")
    if not _str(c.get("text"), 5, 400):
        problems.append("text is 5-400 characters")
    status = c.get("status")
    if status not in CLAIM_STATUS:
        return problems + [f"status is {', '.join(CLAIM_STATUS)}"]
    src = c.get("source")
    if status in ("sourced", "superseded"):
        problems += _check_source(src, ws, web)
    elif src is not None:
        # An assumption or a rejected claim may say where the statement appeared; its quote must be real too.
        problems += _check_source(src, ws, web)
    if status in ("assumption", "rejected", "superseded"):
        note = c.get("note")
        if not isinstance(note, str) or len(note.strip()) < 5:
            problems.append(f"a {status} claim says why in note")
        elif not _str(note, 5, NOTE_MAX):
            # Say which limit failed: "says why" alone made a researcher rewrite a note that was
            # there but too long, twice, until the loop gave up (#38 trial cf17bd67).
            problems.append(f"note is {len(note.strip())} characters; keep it under {NOTE_MAX}")
    if status == "superseded":
        new = ids.get(c.get("superseded_by"))
        if not new or new.get("status") != "sourced":
            problems.append("superseded_by names the sourced claim that replaces it")
    elif "superseded_by" in c:
        problems.append("only a superseded claim has superseded_by")
    return problems


def _check_source(src: Any, ws: Path, web: dict | None) -> list[str]:
    if not isinstance(src, dict) or not _str(src.get("quote"), MIN_QUOTE, 400) or (("file" in src) == ("url" in src)):
        return ["source is {file, quote} or {url, quote}: the exact words (at least 12 characters)"]
    if set(src) - {"file", "url", "quote", "date"}:
        return [f"unknown source keys {sorted(set(src) - {'file', 'url', 'quote', 'date'})}"]
    if "file" in src:
        rel = src["file"]
        if not _safe_rel(rel) or not rel.startswith("source/"):
            return ["source.file is a path in the pack (source/docs/... or source/current-state/...)"]
        path = ws / rel
        if not path.is_file():
            return [f"source.file {rel} is not in the pack"]
        if not quote_in(src["quote"], path.read_text(errors="replace")):
            return [f"the quote is not in {rel} (quote the exact words)"]
        return []
    url = src["url"]
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 500:
        return ["source.url is an https address"]
    if web is None:
        return [f"{url}: web sources are not checked in this run; cite the pack or mark an assumption"]
    text = web.get(url)
    if text is None:
        return [f"{url} could not be opened; cite a page that opens or mark the claim an assumption"]
    if not quote_in(src["quote"], text):
        return [f"the quote is not on {url} (quote the exact words)"]
    return []


def claim_urls(users: dict) -> list[str]:
    out = []
    for c in users.get("claims", []) if isinstance(users, dict) else []:
        src = c.get("source") if isinstance(c, dict) else None
        if isinstance(src, dict) and isinstance(src.get("url"), str) and src["url"] not in out:
            out.append(src["url"])
    return out


def source_label(c: dict) -> str:
    """How a claim's source reads in USERS.md and DESIGN.md: [source/docs/x.md], [https://...], or assumption."""
    src = c.get("source") or {}
    if c.get("status") == "sourced":
        return f"[{src.get('file') or src.get('url')}]"
    return "(assumption)" if c.get("status") == "assumption" else f"({c.get('status')})"


def users_md(users: dict, title: str = "Users") -> str:
    """USERS.md: one section per group, every line with its source or marked assumption (#12's format)."""
    ids = {c["id"]: c for c in users["claims"]}
    out = [f"# {title}", "", "Every line cites a file in the source pack or a web page, or is marked (assumption).", ""]
    product = users.get("product")
    if product:
        out += ["## Product", f"- What: {product['what']}", f"- For: {product['for_whom']}",
                f"- Value: {product['value']}", f"- Meaning: {product['meaning']}",
                "- Rests on: " + ", ".join(f"{r} {source_label(ids[r])}" for r in product["claims"]), ""]
    for g in users.get("groups", []):
        out.append(f"## {g['name']} ({g['role']})")
        if g.get("aliases"):
            out.append("Also called: " + "; ".join(g["aliases"]))
        out.append(g["summary"])
        for r in g["claims"]:
            c = ids[r]
            if c["status"] in ("sourced", "assumption"):
                out.append(f"- {c['text']} {source_label(c)}")
        out.append("")
    dropped = [c for c in users["claims"] if c["status"] in ("rejected", "superseded")]
    if dropped:
        out.append("## Not used")
        for c in dropped:
            extra = f" -> replaced by {c['superseded_by']}" if c["status"] == "superseded" else ""
            out.append(f"- {c['id']} ({c['status']}): {c['text']} -- {c['note']}{extra}")
        out.append("")
    if users.get("assumptions"):
        out += ["## Assumptions to confirm"] + [f"- {a}" for a in users["assumptions"]] + [""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- category scan

def check_category_pick(pick: Any) -> list[str]:
    if not isinstance(pick, dict) or not _str(pick.get("category"), 3, 200):
        return ["category.json is {category, sites[6-10]}"]
    sites = pick.get("sites")
    if not isinstance(sites, list) or not 6 <= len(sites) <= 10:
        return ["sites lists 6-10 category leaders and close competitors"]
    problems, seen_id, seen_url = [], set(), set()
    for s in sites:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not SITE_ID.match(s["id"]):
            problems.append("a site has an id (lowercase slug)")
            continue
        if s["id"] in seen_id:
            problems.append(f"site id {s['id']} repeats")
        seen_id.add(s["id"])
        url = s.get("url")
        if not isinstance(url, str) or not re.match(r"^https://[^\s/]+\.[^\s]+$", url) or url in seen_url:
            problems.append(f"{s['id']}: url is a distinct https address")
        seen_url.add(url)
        if not _str(s.get("name"), 2, 80) or s.get("kind") not in SITE_KINDS or not _str(s.get("why"), 5, 300):
            problems.append(f"{s['id']}: name, kind ({', '.join(SITE_KINDS)}) and why")
    if sum(1 for s in sites if isinstance(s, dict) and s.get("kind") in ("leader", "competitor")) < 4:
        problems.append("at least 4 sites are category leaders or close competitors")
    return problems


def check_category_read(read: Any, captured: list[str], *, marks_needed: bool) -> list[str]:
    """category_read.json: what users will expect (follow), where to stand out, and the competitors' marks."""
    if not isinstance(read, dict):
        return ["category_read.json is an object"]
    problems = []
    expect = read.get("expect")
    if not isinstance(expect, list) or not 3 <= len(expect) <= 12:
        problems.append("expect lists 3-12 conventions users will expect")
        expect = []
    for e in expect:
        if not isinstance(e, dict) or not _str(e.get("text"), 5, 300):
            problems.append("an expect item has text")
            continue
        sites = e.get("sites")
        if not isinstance(sites, list) or len(sites) < 2 or any(s not in captured for s in sites):
            problems.append(f"expect '{e['text'][:40]}' names at least 2 captured sites")
    stand = read.get("stand_out")
    if not isinstance(stand, list) or not 2 <= len(stand) <= 8 or not all(
            isinstance(s, dict) and _str(s.get("text"), 5, 300) and _str(s.get("why"), 5, 300) for s in stand):
        problems.append("stand_out lists 2-8 {text, why}: where the product can differ")
    marks = read.get("marks", [])
    if not isinstance(marks, list):
        problems.append("marks is a list")
        marks = []
    seen = set()
    for m in marks:
        if not isinstance(m, dict) or m.get("site") not in captured or m.get("family") not in MARK_FAMILIES \
                or not _str(m.get("description"), 3, 300):
            problems.append(f"a mark is {{site (captured), family ({', '.join(MARK_FAMILIES)}), description}}")
            continue
        seen.add(m["site"])
    if marks_needed and set(captured) - seen:
        problems.append(f"marks describes every captured site's mark (missing: {sorted(set(captured) - seen)})")
    return problems


# ---------------------------------------------------------------- context fit and directions

def check_direction(direction: Any, playbook: dict, *, job: str, fixed: list[str], expect_count: int = 0) -> list[str]:
    """direction.json: chosen contexts and 2-3 direction candidates the playbook allows."""
    if not isinstance(direction, dict):
        return ["direction.json is an object"]
    problems = []
    by_id = contexts_by_id(playbook)
    known = evidence_ids(playbook)
    contexts = direction.get("contexts")
    if not isinstance(contexts, list) or not 1 <= len(contexts) <= 3:
        return problems + ["contexts lists 1-3 playbook contexts"]
    chosen: dict[str, str] = {}
    for c in contexts:
        if not isinstance(c, dict) or c.get("id") not in by_id:
            problems.append(f"context {c.get('id') if isinstance(c, dict) else c!r} is not in the playbook")
            continue
        if c.get("role") not in CONTEXT_ROLES or not _str(c.get("why"), 10, 400):
            problems.append(f"context {c['id']}: role ({', '.join(CONTEXT_ROLES)}) and why")
        chosen[c["id"]] = c.get("role")
    if job in ("homepage", "app_screen", "marketing") and list(chosen.values()).count("page") != 1:
        problems.append("exactly one context has role page (the kind of page being designed)")
    cands = direction.get("candidates")
    if not isinstance(cands, list) or not 2 <= len(cands) <= 3:
        return problems + ["candidates lists 2-3 directions"]
    ids = []
    for d in cands:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not re.match(r"^D[1-3]$", d["id"]):
            problems.append("a candidate has id D1, D2 or D3")
            continue
        ids.append(d["id"])
        problems += [f"{d['id']}: {p}" for p in _check_candidate(d, chosen, by_id, known, fixed)]
    if len(set(ids)) != len(ids):
        problems.append("candidate ids are distinct")
    good = [d for d in cands if isinstance(d, dict) and isinstance(d.get("axes"), dict)]
    for i, a in enumerate(good):
        for b in good[i + 1:]:
            same_family = a.get("family") == b.get("family")
            diff = sum(a["axes"].get(k) != b["axes"].get(k) for k in AXES)
            if same_family and diff < 2:
                problems.append(f"{a.get('id')} and {b.get('id')} are the same direction (same family, <2 axes apart)")
    rec = direction.get("recommended")
    if not isinstance(rec, dict) or rec.get("id") not in ids or not _str(rec.get("reason"), 10, 600):
        problems.append("recommended is {id: a candidate, reason}")
    taste = direction.get("taste", {})
    if not isinstance(taste, dict) or not all(isinstance(t, str) and TASTE_ID.match(t) for t in taste.get("ids", [])) \
            or not _str(taste.get("note", "none"), 1, 600):
        problems.append("taste is {ids: [T..], note}: the owner's taste as a bias, kept apart from the evidence")
    if not _strs(direction.get("assumptions", []), 0, 12):
        problems.append("assumptions lists at most 12 things to confirm")
    return problems


def _check_candidate(d: dict, chosen: dict, by_id: dict, known: set[str], fixed: list[str]) -> list[str]:
    problems = []
    allowed_keys = {"id", "name", "context", "family", "why", "axes", "principles", "do", "dont", "follow",
                    "differentiate", "evidence", "palette", "type", "imagery", "motion_note"}
    if set(d) - allowed_keys:
        problems.append(f"unknown keys {sorted(set(d) - allowed_keys)}")
    if not _str(d.get("name"), 2, 60) or not _str(d.get("why"), 10, 600):
        problems.append("name and why (for these users)")
    ctx = d.get("context")
    if ctx not in chosen:
        problems.append("context is one of the chosen contexts")
    elif d.get("family") not in allowed_families(by_id[ctx]):
        problems.append(f"family is a style the playbook allows for {ctx}, quoted exactly: {allowed_families(by_id[ctx])}")
    axes = d.get("axes")
    if not isinstance(axes, dict) or set(axes) != set(AXES) or any(axes[k] not in v for k, v in AXES.items()):
        problems.append("axes sets " + "; ".join(f"{k} ({'|'.join(v)})" for k, v in AXES.items()))
    for key, lo, hi in (("principles", 2, 6), ("do", 2, 8), ("dont", 2, 8), ("follow", 1, 8), ("differentiate", 1, 6)):
        if not _strs(d.get(key), lo, hi):
            problems.append(f"{key} lists {lo}-{hi} short lines")
    ev = d.get("evidence")
    if not isinstance(ev, list) or len(ev) < 2 or not all(isinstance(e, str) and EVIDENCE_ID.match(e) for e in ev):
        problems.append("evidence lists at least 2 playbook evidence ids (E###)")
    else:
        unknown = [e for e in ev if e not in known]
        if unknown:
            problems.append(f"evidence ids not in the playbook: {unknown}")
    if "colour" in fixed and d.get("palette") != "fixed":
        problems.append('palette is "fixed": the colour part is approved and stays as it is')
    if "colour" not in fixed and not _str(d.get("palette"), 5, 300):
        problems.append("palette describes the colour idea (5-300 characters)")
    if "type" in fixed and d.get("type") != "fixed":
        problems.append('type is "fixed": the type part is approved and stays as it is')
    if "type" not in fixed and not _str(d.get("type"), 5, 300):
        problems.append("type describes the type idea (5-300 characters)")
    return problems


def playbook_recommendations(playbook: dict, contexts: list[dict]) -> list[dict]:
    """The chosen contexts with the playbook's recommendations copied verbatim (evidence ids and confidence)."""
    by_id = contexts_by_id(playbook)
    return [{"id": c["id"], "role": c["role"], "why": c["why"], "name": by_id[c["id"]]["name"],
             "recommendations": {k: by_id[c["id"]][k] for k in PLAYBOOK_FIELDS}} for c in contexts]


def cited_evidence(obj: Any) -> set[str]:
    return set(re.findall(r"\bE\d{3}\b", json.dumps(obj, ensure_ascii=False)))


# ---------------------------------------------------------------- research.json

def check_research(research: Any, playbook: dict) -> list[str]:
    """research.json as the stage script assembles it: complete, playbook copies verbatim, ids real."""
    if not isinstance(research, dict) or research.get("version") != VERSION:
        return [f"research.json is an object with version {VERSION}"]
    problems = []
    for key in ("product", "job", "inventory", "users", "contexts", "category", "directions", "recommended", "taste",
                "assumptions", "files_to_create", "fixed"):
        if key not in research:
            problems.append(f"research.json has {key}")
    if problems:
        return problems
    by_id = contexts_by_id(playbook)
    for c in research["contexts"]:
        if c.get("id") not in by_id:
            problems.append(f"context {c.get('id')} is not in the playbook")
            continue
        want = {k: by_id[c["id"]][k] for k in PLAYBOOK_FIELDS}
        if c.get("recommendations") != want:
            problems.append(f"context {c['id']}: the playbook's recommendations are copied verbatim")
    unknown = sorted(cited_evidence({k: research[k] for k in ("contexts", "directions")}) - evidence_ids(playbook))
    if unknown:
        problems.append(f"evidence ids not in the playbook: {unknown}")
    chosen = {c["id"] for c in research["contexts"]}
    for d in research["directions"]:
        if d.get("context") not in chosen or d.get("family") not in allowed_families(by_id.get(d.get("context"), {"styles": {}})):
            problems.append(f"{d.get('id')}: family not allowed for its context")
    if research["recommended"].get("id") not in {d.get("id") for d in research["directions"]}:
        problems.append("recommended names a direction")
    claims = research["users"].get("claims", []) if isinstance(research["users"], dict) else []
    for c in claims:
        if c.get("status") == "sourced" and not (c.get("source") or {}).get("quote"):
            problems.append(f"{c.get('id')}: a sourced claim carries its quote")
    return problems


# ---------------------------------------------------------------- the research gate

def gate_answer(raw: Any, direction_ids: list[str], deciders: tuple[str, ...]) -> dict:
    """The research gate's answer: who decided, the direction picked, users confirmed or corrected, why."""
    if isinstance(raw, str):
        raw = json.loads(raw) if raw.strip() else {}
    if not isinstance(raw, dict):
        raise ValueError("the research gate's answer is an object")
    if "approval" in raw or "approved" in raw:
        raise ValueError("the research gate records a decision (decided_by, direction, users, reasons), not an approval flag")
    allowed = {"decided_by", "direction", "users", "corrections", "reasons", "notes", "source"}
    if set(raw) - allowed:
        raise ValueError(f"unknown keys {sorted(set(raw) - allowed)}")
    by = raw.get("decided_by")
    if by not in deciders:
        raise ValueError(f"decided_by is {' or '.join(deciders)}")
    if raw.get("direction") not in direction_ids:
        raise ValueError(f"direction is one of {direction_ids}")
    if raw.get("users") not in ("confirm", "correct"):
        raise ValueError("users is confirm or correct")
    corrections = raw.get("corrections", [])
    if raw["users"] == "correct" and not _strs(corrections, 1, 12, 400):
        raise ValueError("users: correct lists the corrections (1-12 lines)")
    if raw["users"] == "confirm" and corrections:
        raise ValueError("corrections go with users: correct")
    if not _str(raw.get("reasons"), 5, 2000):
        raise ValueError("reasons says why (5-2000 characters)")
    if by == "owner":
        if not _str(raw.get("notes"), 1, 4000) or not _str(raw.get("source"), 3, 300):
            raise ValueError("an owner decision quotes his own words (notes) and where he said them (source)")
    elif "source" in raw:
        raise ValueError("source is for the owner's own words only")
    return {"decided_by": by, "direction": raw["direction"], "users": raw["users"], "corrections": list(corrections),
            "reasons": " ".join(raw["reasons"].split()), "notes": raw.get("notes", ""), "source": raw.get("source", "")}
