#!/usr/bin/env python3
"""Check a context profile against contract v2 and its brief (System architecture, queue #122; v2 #127, 2026-10-20).

The context stage (configs/architecture/stages/context_profile/STANDARD.md) turns a product brief into a
context profile that every later architecture stage reuses. This script is the stage's deterministic gate,
no model and standard library only: is the profile well formed, and does every quoted item stand on text
that is really in the brief?

  context_profile_check.py --brief brief.md profile.json   a profile
  context_profile_check.py --brief brief.md key.json       a known case's key: its reference profile

Reasons it reports (STANDARD.md, "The checker"):
  missing_section, bad_enum, schema    contract.v2.schema.json, by a small validator that knows only the
                                       keywords the schema uses and refuses any other
  brief_hash_mismatch                  brief_sha256, when given, is the brief's
  quote_not_in_brief, quote_too_short, each quote is one span of the brief (case, whitespace, quote marks,
  quote_too_long                       dashes and markdown emphasis normalised), 2 to 40 words
  number_not_in_quote                  each number a quoted item states is in its quote
  system_name_not_in_quote             a quoted external system's name is in its quote
  observed_not_quoted                  observed workload is quoted, never assumed
  current_system_not_quoted            current_system.state none or exists stands on a quote
  maturity_without_evidence            a stage other than unknown names its evidence
  unknown_field_unnamed                every unknown scalar or empty fact list is named in unknowns
  rank_duplicate, rank_gap             goal ranks are 1..n, each once
  duplicate_id                         constraint ids and goal ids are each unique
  constraint_goal_overlap              no constraint and goal stand on the same text

Prints one JSON report. Exit 0 = no errors, 1 = errors, 2 = cannot run (missing file, bad JSON, bad schema).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE.parent / "stages" / "context_profile" / "contract.v2.schema.json"
CONTRACT = "context_profile/v2"
KEY_FORMAT = "context_profile_key/v2"
STAGES = ("idea", "startup", "growing", "established", "unknown")
SYSTEM_STATES = ("none", "exists", "unknown")
LEVELS = ("none", "low", "moderate", "high")
CRITERIA = ("cost", "efficiency", "performance", "privacy", "security", "reliability", "delivery_speed",
            "operability", "change_cost", "scalability", "other")
QUOTE_WORDS = (2, 40)

# Where items with a source live. The scorer names sections the same way.
LIST_FACTS = ("maturity.evidence", "privacy.data_categories", "privacy.retention", "privacy.sharing",
              "privacy.jurisdictions_or_rules", "security.requirements", "security.threats",
              "security.compliance", "team.skills", "team.operating_capacity")
SCALAR_FACTS = ("reliability.availability", "reliability.data_loss_tolerance", "reliability.recovery_time",
                "team.size", "budget.build", "budget.run_monthly")
WORKLOAD = ("workload.observed", "workload.projected", "workload.peaks")
MEASURES = (*WORKLOAD, "performance.targets")
# current_system: the state's own source, and the items of the system as it is now.
SYSTEM = ("current_system", "current_system.items", "external_systems")
SECTIONS = ("product", *SYSTEM, *LIST_FACTS, *MEASURES, *SCALAR_FACTS, "privacy.sensitivity", "constraints",
            "goals")
# Fields a profile may leave "unknown": each must then be named in unknowns, with field = its path.
UNKNOWN_SCALARS = ("maturity.stage", "current_system.state", *SCALAR_FACTS, "privacy.sensitivity")


# ---------------------------------------------------------------- text

_PUNCT = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
})
_EMPHASIS = re.compile(r"[*_`]")
_SPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    """Text as quotes are compared: NFKC, straight quote marks and dashes, no markdown emphasis
    (* _ `), whitespace runs as one space, case folded."""
    text = unicodedata.normalize("NFKC", text).translate(_PUNCT)
    return _SPACE.sub(" ", _EMPHASIS.sub("", text)).strip().casefold()


# ---------------------------------------------------------------- numbers

_SCALES = {"hundred": 1e2, "k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
           "b": 1e9, "bn": 1e9, "billion": 1e9}
_NUMBER = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?)(?:\s?(hundred|k|thousand|mn|m|million|bn|b|billion)\b)?",
                     re.IGNORECASE)
_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen".split())}
_TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_BIG = {"thousand": 1e3, "million": 1e6, "billion": 1e9}
_TOKEN = re.compile(r"[a-z]+|\d[\d,.]*|[^\sa-z\d]")


def _canon(value: float) -> float:
    return float(f"{value:.9g}")


def _word_numbers(text: str, quote_side: bool) -> list[tuple[str, float]]:
    """Numbers written as words: "three", "twenty-five", "two hundred", "1.2 million" (the scale word after
    digits belongs to the digits). In a quote, "a million" and "one" count too; in an item "one" does not,
    because items use it as a pronoun ("one of the goals") far more often than as a number."""
    tokens = _TOKEN.findall(text.casefold().replace("-", " "))
    found: list[tuple[str, float]] = []
    words: list[str] = []
    total = current = 0.0
    active = False

    def flush() -> None:
        nonlocal total, current, active, words
        if active:
            found.append((" ".join(words), total + current))
        total = current = 0.0
        active = False
        words = []

    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok in _UNITS and (quote_side or tok != "one"):
            current += _UNITS[tok]
        elif tok in _TENS:
            current += _TENS[tok]
        elif tok in ("hundred", "dozen", *_BIG) and prev[:1].isdigit():
            flush()  # "1.2 million": the digits' scale, read with the digits
            continue
        elif tok == "hundred":
            current = (current or 1) * 100
        elif tok == "dozen":
            current = (current or 1) * 12
        elif tok in _BIG:
            total += (current or 1) * _BIG[tok]
            current = 0.0
        elif tok in ("a", "an") and quote_side and nxt in ("hundred", "dozen", *_BIG):
            flush()
            active = True
            words.append(tok)
            continue
        elif tok == "and" and active and (nxt in _UNITS or nxt in _TENS):
            words.append(tok)
            continue
        else:
            flush()
            continue
        active = True
        words.append(tok)
    flush()
    return found


def number_tokens(text: str, *, quote_side: bool) -> list[tuple[str, frozenset[float]]]:
    """Each number in ``text`` with the values it may stand for: "1.2M" is 1.2 or 1,200,000, "40k" is 40
    or 40,000, "1,100" is 1100, "99.9%" is 99.9. Digits inside a word on both sides (B2B, e2e) are not
    numbers; digits at a word's edge are (p95, 3x, SOC 2, S3)."""
    out: list[tuple[str, frozenset[float]]] = []
    for match in _NUMBER.finditer(text):
        start, end = match.span(1)
        if start and text[start - 1].isalpha() and end < len(text) and text[end].isalpha():
            continue
        mantissa = float(match.group(1).replace(",", ""))
        values = {_canon(mantissa)}
        if match.group(2):
            values.add(_canon(mantissa * _SCALES[match.group(2).lower()]))
        out.append((match.group(0), frozenset(values)))
    out += [(token, frozenset({_canon(value)})) for token, value in _word_numbers(text, quote_side)]
    return out


def unsupported_numbers(texts: list[str], quote: str) -> list[str]:
    """The numbers in ``texts`` that are nowhere in ``quote``."""
    available: set[float] = set()
    for _token, values in number_tokens(quote, quote_side=True):
        available |= values
    return [token.strip() for text in texts for token, values in number_tokens(text, quote_side=False)
            if not values & available]


# ---------------------------------------------------------------- the schema

class SchemaError(Exception):
    """The schema uses something this validator does not know: refuse it rather than skip it."""


KNOWN_KEYWORDS = {"$schema", "$id", "title", "description", "type", "additionalProperties", "required",
                  "properties", "$defs", "$ref", "const", "enum", "items", "minItems", "minLength", "pattern",
                  "minimum", "oneOf"}
TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}


def _is_type(value: object, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return name == "number" or isinstance(value, int) or value.is_integer()


def _type_name(value: object) -> str:
    for name in ("boolean", "object", "array", "string", "integer", "number", "null"):
        if _is_type(value, name):
            return name
    return type(value).__name__


class Validator:
    """JSON Schema (2020-12) for exactly the keywords contract.v2.schema.json uses."""

    def __init__(self, schema: dict):
        self.schema = schema
        self._audit(schema, "#")

    def _audit(self, node: object, where: str) -> None:
        if not isinstance(node, dict):
            raise SchemaError(f"{where}: a schema must be an object")
        for keyword in node:
            if keyword not in KNOWN_KEYWORDS:
                raise SchemaError(f"{where}: unsupported keyword {keyword!r}")
        types = node.get("type", [])
        for name in types if isinstance(types, list) else [types]:
            if name not in TYPES:
                raise SchemaError(f"{where}: unknown type {name!r}")
        if node.get("additionalProperties", False) is not False:
            raise SchemaError(f"{where}: only additionalProperties false is supported")
        for name, sub in node.get("properties", {}).items():
            self._audit(sub, f"{where}/properties/{name}")
        for name, sub in node.get("$defs", {}).items():
            self._audit(sub, f"{where}/$defs/{name}")
        for i, sub in enumerate(node.get("oneOf", [])):
            self._audit(sub, f"{where}/oneOf/{i}")
        if "items" in node:
            self._audit(node["items"], f"{where}/items")
        if "$ref" in node:
            self._resolve(node["$ref"])

    def _resolve(self, ref: str) -> dict:
        name = ref.removeprefix("#/$defs/")
        if name == ref or name not in self.schema.get("$defs", {}):
            raise SchemaError(f"unresolvable $ref {ref!r}")
        return self.schema["$defs"][name]

    def errors(self, value: object, node: dict | None = None, path: str = "$") -> list[tuple[str, str, str]]:
        """(keyword, path, detail) for each way ``value`` breaks the schema."""
        node = self.schema if node is None else node
        if "$ref" in node:
            return self.errors(value, self._resolve(node["$ref"]), path)
        if "oneOf" in node:
            return self._one_of(value, node["oneOf"], path)
        if "const" in node and value != node["const"]:
            return [("const", path, f"expected {node['const']!r}")]
        if "enum" in node and value not in node["enum"]:
            return [("enum", path, f"{value!r} is not one of {', '.join(map(str, node['enum']))}")]
        if "type" in node:
            types = node["type"] if isinstance(node["type"], list) else [node["type"]]
            if not any(_is_type(value, name) for name in types):
                return [("type", path, f"expected {' or '.join(types)}, got {_type_name(value)}")]
        out: list[tuple[str, str, str]] = []
        if isinstance(value, dict):
            out += [("required", path, f"missing {name!r}") for name in node.get("required", []) if name not in value]
            props = node.get("properties", {})
            for name, sub in value.items():
                if name in props:
                    out += self.errors(sub, props[name], f"{path}.{name}")
                elif "additionalProperties" in node:
                    out.append(("additionalProperties", f"{path}.{name}", "not in the contract"))
        if isinstance(value, list):
            if len(value) < node.get("minItems", 0):
                out.append(("minItems", path, f"needs at least {node['minItems']} item(s)"))
            if "items" in node:
                for i, sub in enumerate(value):
                    out += self.errors(sub, node["items"], f"{path}[{i}]")
        if isinstance(value, str):
            if len(value) < node.get("minLength", 0):
                out.append(("minLength", path, f"shorter than {node['minLength']} characters"))
            if "pattern" in node and not re.search(node["pattern"], value):
                out.append(("pattern", path, f"{value!r} does not match {node['pattern']}"))
        if _is_type(value, "number") and "minimum" in node and value < node["minimum"]:
            out.append(("minimum", path, f"{value} is below {node['minimum']}"))
        return out

    def _one_of(self, value: object, branches: list[dict], path: str) -> list[tuple[str, str, str]]:
        results = [self.errors(value, branch, path) for branch in branches]
        passing = sum(1 for result in results if not result)
        if passing == 1:
            return []
        if passing > 1:
            return [("oneOf", path, "matches more than one allowed form")]

        # None fits: report the form it was closest to. A form whose const or type failed right here is
        # a different kind of thing altogether; among the rest, the fewest errors.
        def distance(result: list[tuple[str, str, str]]) -> tuple[bool, int]:
            return (any(kind in ("const", "type") and where == path for kind, where, _ in result), len(result))

        return min(results, key=distance)


# ---------------------------------------------------------------- items

def at(profile: object, dotted: str) -> object:
    """The value at a dotted path ("privacy.retention"), or None."""
    node = profile
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _text(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return str(value)


class Item:
    """One profile item that carries a source: its section, JSON path, node and the texts that state it.
    (A plain class, not a dataclass: the tests load this file by path, outside sys.modules.)"""

    __slots__ = ("section", "path", "node", "texts")

    def __init__(self, section: str, path: str, node: dict, texts: list[str]):
        self.section, self.path, self.node, self.texts = section, path, node, texts

    @property
    def source(self) -> dict:
        source = self.node.get("source")
        return source if isinstance(source, dict) else {}

    @property
    def kind(self) -> object:
        return self.source.get("kind")

    @property
    def quote(self) -> str | None:
        quote = self.source.get("quote")
        return quote if isinstance(quote, str) else None


def iter_items(profile: object) -> Iterator[Item]:
    """Every item that carries a source, whatever else is wrong with the profile."""
    if not isinstance(profile, dict):
        return
    product = profile.get("product")
    if isinstance(product, dict):
        yield Item("product", "$.product", product, [_text(product.get("summary"))])
    system = profile.get("current_system")
    if isinstance(system, dict):
        if "source" in system:
            yield Item("current_system", "$.current_system", system, [])
        nodes = system.get("items")
        for i, node in enumerate(nodes if isinstance(nodes, list) else []):
            if isinstance(node, dict):
                yield Item("current_system.items", f"$.current_system.items[{i}]", node, [_text(node.get("text"))])
    nodes = profile.get("external_systems")
    for i, node in enumerate(nodes if isinstance(nodes, list) else []):
        if isinstance(node, dict):
            yield Item("external_systems", f"$.external_systems[{i}]", node,
                       [_text(node.get("name")), _text(node.get("role"))])
    for section in LIST_FACTS:
        nodes = at(profile, section)
        for i, node in enumerate(nodes if isinstance(nodes, list) else []):
            if isinstance(node, dict):
                yield Item(section, f"$.{section}[{i}]", node, [_text(node.get("value"))])
    for section in MEASURES:
        nodes = at(profile, section)
        for i, node in enumerate(nodes if isinstance(nodes, list) else []):
            if isinstance(node, dict):
                stated = f"{_text(node.get('value'))} {_text(node.get('unit'))}"
                yield Item(section, f"$.{section}[{i}]", node, [_text(node.get("what")), stated])
    for section in SCALAR_FACTS:
        node = at(profile, section)
        if isinstance(node, dict):
            yield Item(section, f"$.{section}", node, [_text(node.get("value"))])
    node = at(profile, "privacy.sensitivity")
    if isinstance(node, dict):
        yield Item("privacy.sensitivity", "$.privacy.sensitivity", node, [])
    for section, field in (("constraints", "text"), ("goals", "note")):
        nodes = profile.get(section)
        for i, node in enumerate(nodes if isinstance(nodes, list) else []):
            if isinstance(node, dict):
                yield Item(section, f"$.{section}[{i}]", node, [_text(node.get(field))])


# ---------------------------------------------------------------- the check

def _error(reason: str, path: str, detail: str) -> dict:
    return {"reason": reason, "path": path, "detail": detail}


def _dicts(value: object) -> list[dict]:
    return [node for node in value if isinstance(node, dict)] if isinstance(value, list) else []


def check(profile: object, brief_text: str, brief_sha256: str, validator: Validator) -> dict:
    """Every way ``profile`` breaks the contract or its brief: {"ok", "errors", "counts"}."""
    errors: list[dict] = []
    for keyword, path, detail in validator.errors(profile):
        reason = ("missing_section" if keyword == "required" and path == "$"
                  else "bad_enum" if keyword == "enum" else "schema")
        errors.append(_error(reason, path, detail))
    if not isinstance(profile, dict):
        return {"ok": False, "errors": errors, "counts": {}}

    if "brief_sha256" in profile and profile["brief_sha256"] != brief_sha256:
        errors.append(_error("brief_hash_mismatch", "$.brief_sha256", f"the brief's sha256 is {brief_sha256}"))

    brief = norm(brief_text)
    counts = {"items": 0, "quoted": 0, "assumed": 0}
    for item in iter_items(profile):
        counts["items"] += 1
        if item.kind == "quote" and item.quote is not None:
            counts["quoted"] += 1
            quote = norm(item.quote)
            where = f"{item.path}.source.quote"
            words = len(quote.split())
            if words < QUOTE_WORDS[0]:
                errors.append(_error("quote_too_short", where, f"a quote needs at least {QUOTE_WORDS[0]} words"))
            elif words > QUOTE_WORDS[1]:
                errors.append(_error("quote_too_long", where,
                                     f"{words} words; quote at most {QUOTE_WORDS[1]}, the shortest span that carries the item"))
            elif quote not in brief:
                errors.append(_error("quote_not_in_brief", where, f"not one span of the brief: {item.quote[:160]!r}"))
            else:
                missing = unsupported_numbers(item.texts, item.quote)
                if missing:
                    errors.append(_error("number_not_in_quote", item.path,
                                         f"{', '.join(missing)} not in its quote; a derived number is an assumption"))
                if item.section == "external_systems" and norm(item.texts[0]) not in quote:
                    errors.append(_error("system_name_not_in_quote", item.path,
                                         f"{item.texts[0]!r} is not in its quote: name a system as the brief names it"))
        elif item.kind == "assumption":
            counts["assumed"] += 1
        if item.section == "workload.observed" and item.kind != "quote":
            errors.append(_error("observed_not_quoted", item.path, "observed workload must quote the brief"))
        if (item.section == "current_system" and item.node.get("state") in ("none", "exists")
                and item.kind != "quote"):
            errors.append(_error("current_system_not_quoted", item.path,
                                 "whether a system exists now must quote the brief; if it does not say, the state is unknown"))

    system = profile.get("current_system")
    if isinstance(system, dict) and system.get("state") in ("none", "exists") and "source" not in system:
        errors.append(_error("current_system_not_quoted", "$.current_system",
                             f"state {system.get('state')!r} with no quote; if the brief does not say, the state is unknown"))

    named = {u.get("field") for u in _dicts(profile.get("unknowns"))}
    empty_lists = ("external_systems", *(f for f in LIST_FACTS if f != "maturity.evidence"),
                   *MEASURES, "constraints", "goals")
    if isinstance(system, dict) and system.get("state") == "exists":
        empty_lists = (*empty_lists, "current_system.items")
    open_fields = [f for f in UNKNOWN_SCALARS if at(profile, f) == "unknown"]
    open_fields += [f for f in empty_lists if at(profile, f) == []]
    for field in open_fields:
        if field not in named:
            errors.append(_error("unknown_field_unnamed", f"$.{field}",
                                 f"{field} is unknown or empty: name it in unknowns (field {field!r}, "
                                 "material true or false, why it matters)"))

    maturity = profile.get("maturity")
    if (isinstance(maturity, dict) and maturity.get("stage") in STAGES and maturity.get("stage") != "unknown"
            and not maturity.get("evidence")):
        errors.append(_error("maturity_without_evidence", "$.maturity.evidence",
                             f"stage {maturity.get('stage')!r} names no evidence; with none, the stage is unknown"))

    for section in ("constraints", "goals"):
        seen: dict[object, int] = {}
        for i, node in enumerate(_dicts(profile.get(section))):
            ident = node.get("id")
            if ident in seen:
                errors.append(_error("duplicate_id", f"$.{section}[{i}].id", f"{ident} is also {section}[{seen[ident]}]"))
            else:
                seen[ident] = i

    goals = _dicts(profile.get("goals"))
    ranks = [g["rank"] for g in goals if _is_type(g.get("rank"), "integer")]
    repeated = sorted({rank for rank in ranks if ranks.count(rank) > 1})
    if repeated:
        errors.append(_error("rank_duplicate", "$.goals", f"rank {', '.join(map(str, repeated))} given to more than one goal"))
    elif sorted(ranks) != list(range(1, len(ranks) + 1)):
        errors.append(_error("rank_gap", "$.goals", f"ranks {sorted(ranks)}; expected 1 to {len(ranks)}, each once"))

    quoted = [(item, norm(item.quote)) for item in iter_items(profile)
              if item.section in ("constraints", "goals") and item.kind == "quote" and item.quote]
    for c, c_quote in (pair for pair in quoted if pair[0].section == "constraints"):
        for g, g_quote in (pair for pair in quoted if pair[0].section == "goals"):
            if c_quote in g_quote or g_quote in c_quote:
                errors.append(_error("constraint_goal_overlap", g.path,
                                     f"stands on the same text as constraint {c.node.get('id')}: "
                                     "a must-hold is never also a tradeable goal"))
    return {"ok": not errors, "errors": errors, "counts": counts}


# ---------------------------------------------------------------- command line

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_validator(path: Path = SCHEMA_PATH) -> Validator:
    return Validator(json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a context profile (contract v2) against its brief.")
    parser.add_argument("profile", type=Path, help="a profile, or a known case's key.json (its reference profile)")
    parser.add_argument("--brief", type=Path, required=True, help="the brief the profile was made from")
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args(argv)
    try:
        brief_bytes = args.brief.read_bytes()
        brief_text = brief_bytes.decode("utf-8")
        document = json.loads(args.profile.read_text(encoding="utf-8"))
        validator = load_validator(args.schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot run: {exc}"}))
        return 2
    checked = "profile"
    if isinstance(document, dict) and document.get("key") == KEY_FORMAT:
        document, checked = document.get("profile"), "the reference profile of a key"
    report = check(document, brief_text, sha256_bytes(brief_bytes), validator)
    print(json.dumps({"checked": checked, "profile": str(args.profile), "brief": str(args.brief),
                      "brief_sha256": sha256_bytes(brief_bytes), **report}, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
