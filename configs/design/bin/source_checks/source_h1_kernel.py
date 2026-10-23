"""Finite static body-font component. No file I/O, case labels or answer access."""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

ENVIRONMENTS = (
    (1440, 900, 1, 1, "static-loaded"),
    (1024, 768, 1, 1, "static-loaded"),
    (768, 1024, 1, 1, "static-loaded"),
    (390, 844, 1, 1, "static-loaded"),
    (320, 844, 1, 1, "static-loaded"),
)
CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
ID = r"[a-z][a-z0-9-]*"
NUMBER = r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
BASE_CSS = "body{margin:8px;font-family:sans-serif}p{margin:0}"
# H16 (Design #140): the homepage build stage's dialect, as seen on the 48 real pages of
# probe-2026-10-23.json, read beside the fixture dialect above. An element without an id is
# identified by its document-order path; svg is a non-text subtree; stylesheets are not read.
PATH = r"body(?:>[a-z][a-z0-9]*\[[1-9][0-9]*\])+"
SVG_TAGS = {"g", "path", "circle", "rect", "polygon"}
FLOW_TAGS = {
    "main", "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "small", "span", "section", "nav", "header",
    "footer", "article", "figure", "figcaption", "a", "ul", "ol", "li", "dl", "dt", "dd", "strong", "em",
    "b", "code", "del", "dfn", "sup", "br", "svg",
}
VOID_TAGS = {"meta", "link", "br"}
REFUSED_TAGS = {"script": "script", "iframe": "iframe", "template": "template", "object": "object/embed",
                "embed": "object/embed", "base": "base"}


class Unsupported(ValueError):
    pass


def validate_inline(value):
    properties = set()
    for declaration in value.split(";"):
        if not declaration or declaration.count(":") != 1:
            raise Unsupported("empty/malformed inline declaration")
        prop, val = declaration.split(":")
        if prop in properties:
            raise Unsupported("duplicate inline property")
        properties.add(prop)
        if prop in {"font-size", "margin-top"}:
            if not re.fullmatch(NUMBER + "px", val):
                raise Unsupported("unsupported length")
            if prop == "font-size" and float(val[:-2]) <= 0:
                raise Unsupported("nonpositive font size")
        elif (prop, val) not in {("display", "none"), ("visibility", "hidden"), ("opacity", "0")}:
            raise Unsupported("unsupported property/value")


class StaticDocument(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.counts = {}
        self.ids = set()
        self.markers = []
        self.marker_paths = {}
        self.css = ""
        self.metas = []
        self.doctypes = 0
        self.children = []

    def handle_decl(self, decl):
        if decl.lower() != "doctype html" or self.stack or self.counts or self.doctypes:
            raise Unsupported("unsupported doctype")
        self.doctypes += 1

    def handle_starttag(self, tag, attrs):
        if len({key for key, _ in attrs}) != len(attrs):
            raise Unsupported("duplicate attribute")
        at = dict(attrs)
        parent = self.stack[-1][0] if self.stack else None
        if tag in REFUSED_TAGS:
            raise Unsupported(REFUSED_TAGS[tag] + " element")
        allowed_parents = {
            "html": {None}, "head": {"html"}, "body": {"html"},
            "meta": {"head"}, "title": {"head"}, "style": {"head"}, "link": {"head"},
            **{x: {"svg", "g"} for x in SVG_TAGS},
            **{x: {"body"} | FLOW_TAGS - VOID_TAGS - {"svg"} for x in FLOW_TAGS},
        }
        if tag not in allowed_parents:
            raise Unsupported("unsupported element: " + tag)
        if parent not in allowed_parents[tag]:
            raise Unsupported("unsupported element/structure")
        path = "body" if tag == "body" else None
        if self.stack:
            siblings = self.children[-1]
            siblings[tag] = siblings.get(tag, 0) + 1
            if self.stack[-1][2] is not None:
                path = self.stack[-1][2] + ">" + tag + "[" + str(siblings[tag]) + "]"
        self.counts[tag] = self.counts.get(tag, 0) + 1
        identity = at.get("id")
        if tag == "html":
            if at != {"lang": "en"}:
                raise Unsupported("html attributes")
        elif tag in {"head", "body", "title", "style"}:
            if at:
                raise Unsupported("head/body attributes")
        elif tag == "meta":
            if (at not in ({"charset": "utf-8"}, {"http-equiv": "Content-Security-Policy", "content": CSP})
                    and (set(at) != {"name", "content"} or not all(isinstance(x, str) for x in at.values()))):
                raise Unsupported("meta attributes/CSP")
            self.metas.append(at)
        elif tag == "link":
            if set(at) != {"rel", "href"} or at["rel"] != "stylesheet" or not isinstance(at["href"], str):
                raise Unsupported("link attributes")
        else:
            if "id" not in at:
                identity = path
            elif not isinstance(identity, str) or not re.fullmatch(ID, identity) or identity in self.ids:
                raise Unsupported("missing/duplicate/invalid ID")
            self.ids.add(identity)
            in_svg = tag == "svg" or tag in SVG_TAGS
            if "style" in at and not in_svg:
                validate_inline(at["style"] or "")
            marked = at.get("data-typography") == "Body"
            if "data-body-role" in at:
                if at["data-body-role"] != "body":
                    raise Unsupported("body-role marker")
                marked = True
            if marked:
                if in_svg:
                    raise Unsupported("body-role marker")
                self.markers.append(identity)
                self.marker_paths[identity] = [x[1] for x in self.stack]
        if tag not in VOID_TAGS:
            self.stack.append((tag, identity, path))
            self.children.append({})

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise Unsupported("unbalanced element")
        self.stack.pop()
        self.children.pop()

    def handle_startendtag(self, tag, attrs):
        if tag not in SVG_TAGS:
            raise Unsupported("self-closing syntax")
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self.stack and self.stack[-1][0] == "style":
            self.css += data
        elif data.strip() and (not self.stack or self.stack[-1][0] in {"html", "head", "body"}):
            raise Unsupported("uncontained text")
        elif data.strip() and (self.stack[-1][0] == "svg" or self.stack[-1][0] in SVG_TAGS):
            raise Unsupported("text in svg")

    def handle_entityref(self, name):
        raise Unsupported("entity")

    def handle_charref(self, name):
        raise Unsupported("character reference")

    def handle_comment(self, data):
        raise Unsupported("comment")

    def handle_pi(self, data):
        raise Unsupported("processing instruction")

    def unknown_decl(self, data):
        raise Unsupported("unknown declaration")

    def finish(self):
        self.close()
        if self.stack or self.doctypes != 1:
            raise Unsupported("incomplete document")
        if any(self.counts.get(x) != 1 for x in ("html", "head", "body", "title")) or self.counts.get("style", 0) > 1:
            raise Unsupported("document cardinality")
        if [x for x in self.metas if "charset" in x] != [{"charset": "utf-8"}]:
            raise Unsupported("required metadata")


def refusal(environment, roots, reason, source=None, roles=None, observed=None):
    return {
        "attempted": list(environment), "actual": None, "route": "REFUSE", "reason": reason,
        "binding": [source, roles, None], "coverage": [roots, observed, None, None, False],
        "nodes": None, "excluded": None, "violations": None,
    }


def preflight(html: bytes, declared_sha256: str, inventory: dict, environment: list):
    """Return (refusal or None, metadata); independent of file names/case labels."""
    roots = inventory.get("roots") if isinstance(inventory, dict) else None
    source_matches = hashlib.sha256(html).hexdigest() == declared_sha256
    if not source_matches:
        return refusal(environment, roots, "SOURCE_HASH_MISMATCH", False), {}
    if (not isinstance(environment, list) or len(environment) != 5
            or any(type(x) is not int for x in environment[:4])
            or tuple(environment) not in ENVIRONMENTS):
        return refusal(environment, roots, "UNSUPPORTED_ENVIRONMENT", True), {}
    if (not isinstance(inventory, dict) or set(inventory) != {"schema", "roots"}
            or inventory["schema"] != "body-roots/1" or not isinstance(roots, list)
            or any(not isinstance(x, str) or not (re.fullmatch(ID, x) or re.fullmatch(PATH, x)) for x in roots)
            or len(roots) != len(set(roots))):
        return refusal(environment, roots, "INVALID_INVENTORY", True, False), {}
    try:
        document = StaticDocument()
        document.feed(html.decode("utf-8", errors="strict"))
        document.finish()
    except (Unsupported, UnicodeError, ValueError) as exc:
        return refusal(environment, roots, "UNSUPPORTED_STATIC_SYNTAX", True, None), {"diagnostic": str(exc)}
    markers = document.markers
    reason = None
    if not roots:
        reason = "INVENTORY_EMPTY"
    elif any(x not in document.ids for x in roots):
        reason = "ROOT_MISSING"
    elif any(x not in markers for x in roots):
        reason = "ROOT_UNMARKED"
    elif any(x not in roots for x in markers):
        reason = "ROOT_OMITTED"
    elif any(set(document.marker_paths[x]) & set(markers) for x in markers):
        reason = "NESTED_MARKED_ROOT"
    if reason:
        return refusal(environment, roots, reason, True, False, markers), {}
    return None, {"markers": markers}


async def check(context, html, declared_sha256, inventory, environment, extraction_source):
    decision, metadata = preflight(html, declared_sha256, inventory, environment)
    if decision is not None:
        return decision, {"phase": "preflight", **metadata}
    page = await context.new_page()
    try:
        await page.set_viewport_size({"width": environment[0], "height": environment[1]})
        session = await context.new_cdp_session(page)
        await session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
        await session.detach()
        await page.set_content(html.decode("utf-8"), wait_until="load", timeout=10000)
        await page.evaluate("document.fonts.ready.then(() => true)")
        raw = await page.evaluate(extraction_source, {"roots": inventory["roots"]})
        actual = raw["context"]
        environment_matches = actual == environment and raw["html_zoom"] == 1 and raw["ready_state"] == "complete" and raw["scroll"] == [0, 0]
        roles_match = raw["markers"] == metadata["markers"] and set(raw["markers"]) == set(inventory["roots"])
        result = {
            "attempted": list(environment), "actual": actual,
            "route": "REFUSE", "reason": "DOM_BINDING_MISMATCH",
            "binding": [True, roles_match, environment_matches],
            "coverage": [inventory["roots"], raw["markers"], len(raw["nodes"]), len(raw["excluded"]), raw["enumeration_complete"]],
            "nodes": raw["nodes"], "excluded": raw["excluded"], "violations": raw["violations"],
        }
        if not environment_matches:
            result["reason"] = "ENVIRONMENT_MISMATCH"
        elif not roles_match:
            result["reason"] = "DOM_BINDING_MISMATCH"
        elif raw["error"]:
            result["reason"] = raw["error"]
        else:
            result["route"] = "FAIL_LOCAL" if raw["violations"] else "PASS_LOCAL"
            result["reason"] = "BODY_LT16" if raw["violations"] else "ALL_BODY_GE16"
        return result, {"phase": "browser-measurement", **raw}
    finally:
        await page.close()


# New standalone source-fact component. The preceding 11983 bytes are immutable (shared reader/guard prefix, SHA5cdf2c23...; H16 widened it from 10462).
def source_h1(html: bytes, declared_sha256: str, inventory: dict, environment: list):
    decision, metadata = preflight(html, declared_sha256, inventory, environment)
    count = None
    equals_one = None
    if decision is None:
        document = StaticDocument()
        document.feed(html.decode("utf-8", errors="strict"))
        document.finish()
        count = document.counts.get("h1", 0)
        equals_one = count == 1
    return {
        "guard_decision": decision,
        "guard_metadata": metadata,
        "source_h1_count": count,
        "source_count_equals_one": equals_one,
        "actual_environment": None,
        "rendered_hierarchy": "UNMEASURED",
        "page_verdict": "UNQUALIFIED",
    }


def _main():
    import base64
    import json
    import os
    import sys

    flags = {name: getattr(sys.flags, name) for name in (
        "isolated", "no_user_site", "ignore_environment", "dont_write_bytecode", "safe_path"
    )}
    runtime = {
        "executable": sys.executable, "realpath": os.path.realpath(sys.executable),
        "implementation": sys.implementation.name, "version": list(sys.version_info[:3]),
        "version_string": sys.version, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "flags": flags, "pid": os.getpid(), "ppid": os.getppid(), "cwd": os.getcwd(),
        "environment": dict(os.environ),
    }
    valid = (runtime["executable"] == "/usr/bin/python3.12"
             and runtime["realpath"] == "/usr/bin/python3.12"
             and runtime["implementation"] == "cpython" and runtime["version"] == [3, 12, 3]
             and runtime["prefix"] == runtime["base_prefix"] == "/usr"
             and flags == {"isolated": 1, "no_user_site": 1, "ignore_environment": 1,
                           "dont_write_bytecode": 1, "safe_path": True})
    print(json.dumps({"runtime": runtime, "valid": valid}, separators=(",", ":")), flush=True)
    if not valid:
        return 3
    for raw in sys.stdin.buffer:
        arguments = json.loads(raw)
        if type(arguments) is not list or len(arguments) != 4:
            raise ValueError("exactly four arguments required")
        html_b64, declared_sha256, inventory, environment = arguments
        html = base64.b64decode(html_b64, validate=True)
        result = source_h1(html, declared_sha256, inventory, environment)
        print(json.dumps(result, separators=(",", ":"), allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
