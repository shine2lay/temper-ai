#!/usr/bin/env python3
"""Exhaustive inventory and conservative consistency; never semantic acceptance (#139).

See stages/context_profile/MEANING-CHECK.md. Completed checks exit 1; cannot-run exits 2.
Only standard library and the existing read-only checker/key loader. No model or server.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORMAT = "context_profile_meaning/v0-layers12"
DEFER = "needs_judgment"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cps = _load("context_profile_score")
cpc = cps.cpc


def text(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(value.translate(str.maketrans({"≤": "<=", "≥": ">=", "’": "'", "−": "-"})).split())


def pointer(parent: str, name: object) -> str:
    return parent + "/" + str(name).replace("~", "~0").replace("/", "~1")


# Exact fractions, never binary floating-point conversion arithmetic.
SCALES = {"": 1, "k": 1000, "thousand": 1000, "m": 1000000, "million": 1000000,
          "b": 1000000000, "billion": 1000000000}
NUMBER = re.compile(r"(?<![\w.])([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s*(thousand|million|billion)\b|([kmb])\b)?(?!\w|,\d|\.\d)")
TIME = {"ms": Fraction(1, 1000), "millisecond": Fraction(1, 1000), "s": Fraction(1),
        "second": Fraction(1), "min": Fraction(60), "minute": Fraction(60), "h": Fraction(3600),
        "hour": Fraction(3600)}
MEMORY = {"b": 1, "byte": 1, "kb": 10**3, "mb": 10**6, "gb": 10**9, "tb": 10**12,
          "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40}
PER = {"s": 1, "second": 1, "min": 60, "minute": 60, "h": 3600, "hour": 3600,
       "day": 86400, "month": None}
OPERATORS = ((r"at most|no more than|<=", "le"), (r"at least|no less than|>=", "ge"),
             (r"below|under|less than|<", "lt"), (r"above|over|more than|>", "gt"),
             (r"equal to|exactly|=", "eq"))
LIMIT = re.compile(r"\b(?:below|under|above|over|at most|at least|no more than|no less than|between|within|cap|limit|maximum|minimum)\b|[<>]=?")
AMBIGUOUS = re.compile(r"\b(?:about|roughly|approximately|around|nearly|almost|or|within|up to|no faster than|no slower than|not (?:below|under|above|over))\b|\d\s*[-–]\s*\d")
UNLISTED_UNITS = {"bit", "kbps", "mbps", "gbps", "tbps", "mbit", "gbit", "percentile"}


def singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and word not in ("ms", "s") else word


def unit(tail: str, prefix: str) -> tuple[str, Fraction] | None:
    currency = re.search(r"([$£€])\s*$", prefix)
    if currency:
        return "currency:" + currency[1], Fraction(1)
    if tail.lstrip().startswith("%"):
        return "ratio", Fraction(1, 100)
    found = re.match(r"\s*([a-z]+)\b", tail)
    word = singular(found[1]) if found else ""
    if word in ("percent", "percentage"):
        return "ratio", Fraction(1, 100)
    if word in UNLISTED_UNITS or not word:
        return None
    dimension, factor = ("seconds", TIME[word]) if word in TIME else (
        ("bytes", Fraction(MEMORY[word])) if word in MEMORY else ("count:" + word, Fraction(1)))
    rest = tail[found.end():]
    rate = re.match(r"\s*(?:per\s+|/\s*)([a-z]+)\b", rest)
    if rate:
        denominator = singular(rate[1])
        if denominator not in PER:
            return None
        seconds = PER[denominator]
        return (f"rate:{dimension}:month", factor) if seconds is None else (f"rate:{dimension}:second", factor / seconds)
    if re.match(r"\s*(?:per\b|/)", rest):
        return None
    return dimension, factor


def comparator(prefix: str) -> str | None:
    for pattern, name in OPERATORS:
        if re.search(r"(?<!\w)(?:" + pattern + r")\s*$", prefix):
            return name
    return None


def quantities(value: str) -> list[dict]:
    value = text(value)
    out = []
    for match in NUMBER.finditer(value):
        raw = Fraction(match[1].replace(",", ""))
        scale = SCALES[match[2] or match[3] or ""]
        parsed = unit(value[match.end():], value[:match.start()])
        out.append({"raw": raw, "amount": raw * scale * parsed[1] if parsed else None,
                    "dimension": parsed[0] if parsed else None, "factor": scale * parsed[1] if parsed else None,
                    "operator": comparator(value[:match.start()]), "start": match.start(), "end": match.end()})
    return out


def _side(q: dict) -> dict:
    return {k: str(v) if isinstance(v, Fraction) else v for k, v in q.items() if k not in ("start", "end")}


def finding(rule: str, claim: object, quote: object) -> dict:
    return {"rule": rule, "claim": claim, "quote": quote}


def numeric_findings(claim: str, quote: str) -> list[dict]:
    a, b = text(claim), text(quote)
    if AMBIGUOUS.search(a) or AMBIGUOUS.search(b):
        return []
    left, right = quantities(a), quantities(b)
    if len(left) == len(right) == 2 and a.startswith("between ") and b.startswith("between "):
        # Only the final unit may be inherited, and only in this explicit grammar.
        for value, items in ((a, left), (b, right)):
            if not re.fullmatch(r"\s+and\s+", value[items[0]["end"]:items[1]["start"]]):
                return []
            if items[0]["dimension"] == "count:and" and items[1]["factor"] is not None:
                items[0].update(dimension=items[1]["dimension"], factor=items[1]["factor"],
                                amount=items[0]["raw"] * items[1]["factor"])
        if all(x["dimension"] == y["dimension"] and x["amount"] is not None for x, y in zip(left, right, strict=True)):
            if any(x["amount"] != y["amount"] for x, y in zip(left, right, strict=True)):
                return [finding("range", [_side(q) for q in left], [_side(q) for q in right])]
        return []
    if len(left) != 1 or len(right) != 1:
        return []
    x, y = left[0], right[0]
    if x["amount"] is None or y["amount"] is None:
        return []
    if x["dimension"] != y["dimension"]:
        # Unlike months, a fixed day is exact. Unlike units, different count nouns need judgment.
        if x["dimension"].startswith(("count:", "rate:")) or y["dimension"].startswith(("count:", "rate:")):
            return []
        return [finding("unit_scale", _side(x), _side(y))]
    if x["amount"] != y["amount"]:
        rule = "unit_scale" if x["raw"] == y["raw"] and x["factor"] != y["factor"] else "number"
        return [finding(rule, _side(x), _side(y))]
    if x["operator"] and y["operator"] and x["operator"] != y["operator"]:
        return [finding("comparator", _side(x), _side(y))]
    return []


POLARITY = re.compile(r"\b(?:must not|must never|may not|must|may|allowed|forbidden)\b")
POLARITY_VALUES = {"must": "required", "must not": "prohibited", "must never": "prohibited",
                   "may": "permitted", "may not": "prohibited", "allowed": "permitted", "forbidden": "prohibited"}
TENSE = re.compile(r"\b(?:will be|would be|was|were|is|are|will|would)\b")
TENSE_VALUES = {"was": "past", "were": "past", "is": "present", "are": "present", "will": "future",
                "will be": "future", "would": "conditional", "would be": "conditional"}


def marked(value: str, pattern: re.Pattern, values: dict) -> dict | None:
    value = text(value).strip(" .")
    matches = list(pattern.finditer(value))
    if len(matches) != 1:
        return None
    m = matches[0]
    return {"body": " ".join((value[:m.start()] + value[m.end():]).split()), "marker": values[m[0]]}


def conditional(value: str) -> dict | None:
    value = text(value).strip(" .")
    if len(re.findall(r"\b(?:if|unless|when)\b", value)) != 1:
        return None
    prefix = re.fullmatch(r"(if|unless|when) (.+?), (.+)", value)
    suffix = re.fullmatch(r"(.+?) (if|unless|when) (.+)", value)
    if prefix:
        return {"body": prefix[3], "condition": prefix[2], "marker": prefix[1]}
    if suffix:
        return {"body": suffix[1], "condition": suffix[3], "marker": suffix[2]}
    return None


LABELS = {"stage": "maturity", "level": "sensitivity", "state": "system state", "criterion": "criterion", "kind": "item kind"}
SECTIONS = {"observed": "/workload/observed/", "projected": "/workload/projected/",
            "forecast": "/workload/projected/", "constraint": "/constraints/", "goal": "/goals/"}


def compare(claim: str, quote: str, path: str = "") -> list[dict]:
    """Return negative evidence only. An empty list is NOT evidence of entailment."""
    result = numeric_findings(claim, quote)
    for name, pattern, values in (("polarity", POLARITY, POLARITY_VALUES), ("time", TENSE, TENSE_VALUES)):
        a, b = marked(claim, pattern, values), marked(quote, pattern, values)
        if a and b and a["body"] == b["body"] and a["marker"] != b["marker"]:
            # required versus permitted is not incompatible; prohibition versus either is.
            if name != "polarity" or "prohibited" in (a["marker"], b["marker"]):
                result.append(finding(name, a, b))
    a, b = conditional(claim), conditional(quote)
    if a and b and a["body"] == b["body"] and a["condition"] == b["condition"] and {a["marker"], b["marker"]} == {"if", "unless"}:
        result.append(finding("condition", a, b))
    field = LABELS.get(path.rsplit("/", 1)[-1])
    label = re.fullmatch(re.escape(field) + r":\s*([a-z_]+)[.]?", text(quote)) if field else None
    if label and text(claim) != label[1]:
        result.append(finding("label", {"attribute": field, "value": text(claim)}, {"attribute": field, "value": label[1]}))
    section = re.match(r"^(observed|projected|forecast|constraint|goal):\s+", text(quote))
    if section:
        expected = SECTIONS[section[1]]
        opposite = {"/workload/observed/": "/workload/projected/", "/workload/projected/": "/workload/observed/",
                    "/constraints/": "/goals/", "/goals/": "/constraints/"}[expected]
        if path.startswith(opposite):
            result.append(finding("section", {"section": opposite}, {"section": expected}))
    return result


def direct(node: dict) -> dict:
    return {k: v for k, v in node.items() if k not in ("source", "id")
            and not isinstance(v, dict) and (not isinstance(v, list) or all(not isinstance(x, (dict, list)) for x in v))}


def inventory(profile: dict) -> list[dict]:
    claims = []

    def walk(node, path="", group="", quotes=None, source_kind=None):
        quotes = [] if quotes is None else quotes
        if isinstance(node, dict):
            source = node.get("source", {})
            is_group = "source" in node or path == "/maturity" or re.fullmatch(r"/(?:unknowns|assumptions)/\d+", path)
            if is_group:
                group = path
                source_kind = source.get("kind")
                quotes = [source["quote"]] if source_kind == "quote" else []
                if path == "/maturity":
                    quotes = [x["source"]["quote"] for x in node["evidence"] if x["source"].get("kind") == "quote"]
                claims.append({"path": path, "kind": "group", "value": direct(node), "group": group,
                               "quotes": quotes, "source_kind": source_kind})
            for name, value in node.items():
                if name in ("contract", "brief_sha256", "id"):
                    continue
                if name == "source":
                    if "why" in value:
                        claims.append({"path": pointer(pointer(path, name), "why"), "kind": "leaf", "value": value["why"],
                                       "group": group, "quotes": [], "source_kind": "assumption"})
                    continue
                walk(value, pointer(path, name), group, quotes, source_kind)
        elif isinstance(node, list):
            if not node or all(not isinstance(x, (dict, list)) for x in node):
                claims.append({"path": path, "kind": "collection" if node else "empty", "value": node,
                               "group": group, "quotes": [], "source_kind": None})
            for i, value in enumerate(node):
                walk(value, pointer(path, i), group, quotes, source_kind)
        else:
            claims.append({"path": path, "kind": "leaf", "value": node, "group": group,
                           "quotes": quotes, "source_kind": source_kind})

    walk(profile)
    return claims


def obligations(key: dict) -> list[dict]:
    result = []
    for category in ("facts", "constraints", "goals", "unknowns", "fields_unknown"):
        for i, entry in enumerate(key.get(category, [])):
            if entry.get("material") is False or entry.get("not_material_reason"):
                continue
            path = f"/{category}/{i}"
            result.append({"path": path, "id": entry.get("id", entry.get("field", path)),
                           "category": category, "data": entry, "claim_groups": []})
    return result


def maps(group: dict, obligation: dict) -> bool:
    category, data, path = obligation["category"], obligation["data"], group["path"]
    if category in ("unknowns", "fields_unknown"):
        value = group["value"]
        if not path.startswith("/unknowns/") or value.get("material") is not True:
            return False
        if data.get("field") and value.get("field") != data["field"]:
            return False
        # A field label is metadata, never evidence that the question asks about it.
        body = cpc.norm(" ".join(str(value.get(name, "")) for name in ("question", "why_it_matters", "decisions_affected")))
        return all(any(cpc.norm(term) in body for term in terms) for terms in data.get("terms", []))
    sections = [data["primary"], *([data["alt"]] if data.get("alt") else [])] if category == "facts" else [category]
    if not any(path == "/" + s.replace(".", "/") or path.startswith("/" + s.replace(".", "/") + "/") for s in sections):
        return False
    return any(cpc.norm(anchor) in cpc.norm(quote) for anchor in data.get("anchors", []) for quote in group["quotes"])


def check(profile: dict, brief: str, key: dict) -> dict:
    errors = cpc.load_validator().errors(profile)
    if errors:
        raise ValueError("invalid profile schema: " + repr(errors))
    sha = cpc.sha256_bytes(brief.encode("utf-8"))
    if key.get("brief_sha256") != sha or profile.get("brief_sha256", sha) != sha:
        raise ValueError("brief hash does not match key/profile")
    claims, owed = inventory(profile), obligations(key)
    groups = {c["path"]: c for c in claims if c["kind"] == "group"}
    for obligation in owed:
        obligation["claim_groups"] = [path for path, group in groups.items() if maps(group, obligation)]
    for claim in claims:
        claim["obligations"] = [o["path"] for o in owed if claim["group"] in o["claim_groups"]]
    results = []
    normalized_brief = cpc.norm(brief)
    for claim in claims:
        path, group = claim["path"], groups.get(claim["group"], {})
        findings = []
        quotes = claim["quotes"]
        if claim["kind"] != "group" and len(quotes) == 1 and cpc.norm(quotes[0]) in normalized_brief:
            value = claim["value"]
            body = group.get("value", {})
            measure = all(k in body for k in ("what", "value", "unit"))
            if measure:
                combined = " ".join(str(body[k]) for k in ("what", "value", "unit"))
                all_findings = compare(combined, quotes[0], path)
                owner = {"comparator": "what", "unit_scale": "unit", "number": "value", "range": "value"}
                findings = [f for f in all_findings if path.endswith("/" + owner.get(f["rule"], "what"))]
            elif isinstance(value, str) and value != "unknown":
                findings = compare(value, quotes[0], path)
        for f in findings:
            f["path"] = path
        results.append({"path": path, "outcome": "contradicted" if findings else DEFER, "findings": findings,
                        "reason": "unambiguous extraction disagrees" if findings else "requires judgment; no positive determination"})
    by_path = {r["path"]: r for r in results}
    for group_path in groups:
        findings = [f for c in claims if c["group"] == group_path and c["kind"] != "group" for f in by_path[c["path"]]["findings"]]
        if findings:
            by_path[group_path].update(outcome="contradicted", findings=findings, reason="contains a contradicted assertion")
    duplicate_groups = {}
    for path, group in groups.items():
        identity = json.dumps([group["value"], group["quotes"], group["source_kind"]], sort_keys=True)
        duplicate_groups.setdefault(identity, []).append(path)
    numeric_groups = [p for p, g in groups.items() if NUMBER.search(text(json.dumps(g["value"]))) or LIMIT.search(text(json.dumps(g["value"])))]
    n_contradicted = sum(r["outcome"] == "contradicted" for r in results)
    return {"format": FORMAT, "case_id": key["case_id"], "brief_sha256": sha,
            "inventory": {"claims": claims, "obligations": owed,
                          "unmapped": [c["path"] for c in claims if not c["obligations"]],
                          "missing": [o["path"] for o in owed if not o["claim_groups"]],
                          "duplicate_mappings": [{"obligation": o["path"], "claim_groups": o["claim_groups"]} for o in owed if len(o["claim_groups"]) > 1],
                          "duplicate_claims": [paths for paths in duplicate_groups.values() if len(paths) > 1]},
            "claims": results,
            "summary": {"entries": len(results), "contradicted": n_contradicted, "needs_judgment": len(results) - n_contradicted,
                        "numeric_limit_groups": len(numeric_groups),
                        "numeric_limit_deferred": sum(by_path[p]["outcome"] == DEFER for p in numeric_groups)}}


def _unique(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _nonfinite(value: str):
    raise ValueError("non-finite JSON number: " + value)


def read_profile(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)


class Parser(argparse.ArgumentParser):
    def exit(self, status=0, message=None):
        # argparse normally exits 0 for --help. This diagnostic has no successful route.
        super().exit(2, message)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args(argv)
    try:
        # Check JSON ambiguities before the existing read-only loader sees the key.
        read_profile(args.case / "key.json")
        key, brief, _sha = cps.load_case(args.case)
        result = check(read_profile(args.profile), brief, key)
    except (OSError, UnicodeError, ValueError, cps.BrokenKey, cpc.SchemaError, RecursionError) as exc:
        print(json.dumps({"format": FORMAT, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
