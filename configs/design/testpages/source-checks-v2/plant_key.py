#!/usr/bin/env python3
"""source-checks-v2 key builder (Design, queue #143, 2026-10-23). Stdlib only; never imports or runs a kernel.

A public synthetic key for the widened A2-01 (one h1) and A1-02 (headline words) source checks, which H16
(Design #140, ~/design-lab/homepage-workflow/HYPOTHESES.md) widened to read the homepage build stage's real
dialect. Its real-page key stays off this public repo (configs/design/local/source-checks-real-v1, git-ignored),
so this key carries the same six variants on pages that are already public: the four converter fixtures in
../html-fixtures/ (harbor, pulse, rich, atlas).

Each page is brought into the build stage's dialect (NORMALIZE: the constructs the widened reader still
refuses are taken out, nothing else), its running text gets the build's Body mark (BODY_MARK_RULE), and it is
written as is (P0) plus five planted copies (P1-P5) into fixtures/. INPUTS.json and EXPECTED.jsonl for
a2-01-source-h1/ and a1-02-headline-words/ follow the d158dfa key formats. Every expected record is truth by
construction from the checks' documented rules, never from a kernel's output:

  A2-01  source_h1_count = the number of h1 elements in the source, hidden ones included;
         source_count_equals_one = (count == 1).
  A1-02  BOUND_H1 only when the declaration is a value-headline/1 for h1 with ASCII text, the page has exactly
         one h1, and that h1's text runs (joined, whitespace collapsed) equal the declared text; then
         source_word_count = the WORD matches and source_word_count_lte_12 = 1 <= count <= 12; otherwise
         UNBOUND_TARGET with no count.
  Both   the guard passes (no refusal) because every page is in the dialect (_Dialect) and the inventory is
         exactly the page's Body-marked identities (IDENTITY_RULE); guard_metadata = {"markers": that list}.

The builder checks its own pages against the dialect and the plants against the rules before it writes
anything, and refuses to overwrite a key that already exists (freeze: FREEZE.md holds the hashes).

    python3 plant_key.py
"""

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE.parent / "html-fixtures"
PAGES = ("harbor", "pulse", "rich", "atlas")
VARIANTS = ("P0", "P1", "P2", "P3", "P4", "P5")
ENVIRONMENT = [1440, 900, 1, 1, "static-loaded"]
WORD = r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*"  # the A1-02 word rule, verbatim
LIMIT = 12  # source_word_count_lte_12 = 1 <= count <= 12
P1_INSERT = "<h1>Planted second heading</h1>"
P3_INSERT = "<div hidden><h1>Planted hidden heading</h1></div>"
P4_WORDS = ["and", "these", "extra", "planted", "words", "push", "the", "headline", "well", "past", "twelve"]
P5_WORD = "Planted"
BODY_MARK = ' data-typography="Body"'

FLOW = {
    "main", "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "small", "span", "section", "nav", "header",
    "footer", "article", "figure", "figcaption", "a", "ul", "ol", "li", "dl", "dt", "dd", "strong", "em",
    "b", "code", "del", "dfn", "sup", "br", "svg",
}
SVG = {"g", "path", "circle", "rect", "polygon"}
VOID = {"meta", "link", "br"}
HEAD = {"html": {None}, "head": {"html"}, "body": {"html"}, "meta": {"head"}, "title": {"head"},
        "style": {"head"}, "link": {"head"}}
ID = r"[a-z][a-z0-9-]*"

NORMALIZE = (
    ("comments", "every HTML comment removed (the reader refuses comments)",
     lambda t: re.subn(r"<!--.*?-->", "", t, flags=re.S)),
    ("img-hr", "every img and hr element removed (void elements outside the reader's tag set)",
     lambda t: re.subn(r"<(?:img|hr)\b[^>]*>", "", t)),
    ("svg-line", "every svg line and polyline removed (outside the reader's svg set g, path, circle, rect, polygon)",
     lambda t: re.subn(r"<(?:line|polyline)\b[^>]*/>", "", t)),
    ("blockquote", "blockquote renamed figure, attributes and text kept (outside the reader's tag set)",
     lambda t: re.subn(r"<(/?)blockquote\b", r"<\1figure", t)),
    ("cite", "cite renamed figcaption, text kept (outside the reader's tag set)",
     lambda t: re.subn(r"<(/?)cite\b", r"<\1figcaption", t)),
    ("entity", "the entity &amp; written as the word and (the reader refuses entities)",
     lambda t: re.subn(r"&amp;", "and", t)),
    ("inline-style", "every inline style attribute removed (margin is outside the reader's inline properties)",
     lambda t: re.subn(r'\sstyle="[^"]*"', "", t)),
)
BODY_MARK_RULE = (
    "Running text = every p element whose start tag has no attributes (<p>); each gets data-typography=\"Body\", "
    "the homepage build stage's own type-role mark. Styled paragraphs (a class or another data-typography role: "
    "lede, kicker, fine print, prices) are not body copy and stay unmarked."
)
IDENTITY_RULE = (
    "Body-copy declarations are the elements whose data-typography attribute is exactly \"Body\", in document "
    "order. Identity = the element's id attribute when it has one; otherwise its document-order path: \"body\", "
    "then for each element from body's child down to the element, \">\" + tag name + \"[\" + n + \"]\", where n is "
    "the element's 1-based position among its parent's element children with the same tag name, counted in "
    "source order (void elements and self-closed svg children count). The inventory for a page = all its "
    "Body-marked identities, in document order. Same rule as H16's real-page key."
)
PLANTS = {
    "P0": "the normalized, Body-marked page as is",
    "P1": f"a second visible h1, {P1_INSERT}, inserted just before the page's last </section> (after the original h1)",
    "P2": "the page's one h1 demoted to h2: its <h1 and </h1> renamed <h2 and </h2>, attributes and content unchanged",
    "P3": f"a second h1 inside an element with the hidden attribute, {P3_INSERT}, inserted just before the page's "
          "last </section>",
    "P4": f"the headline lengthened to {LIMIT + 3} words (the A1-02 limit + 3) by inserting plain words from "
          f"{json.dumps(P4_WORDS)} just before </h1>",
    "P5": f"the first word of the h1's first text run replaced by \"{P5_WORD}\" (one word changed, count unchanged)",
}
DECLARATIONS = (
    "Synthetic key, so the headline declaration is part of the construction: P0, P1, P2, P3 and P5 declare the "
    "page's original h1 text (P0 binds: a clean case to pass; P1-P3 have two or no h1s; P5's headline is one word "
    "off); P4 declares its own lengthened headline."
)


class _Dialect(HTMLParser):
    """The widened reader's dialect as documented in H16's RESULT.md, held a little stricter (no inline style,
    no data-body-role, no CSP meta), so a page this accepts is one the reader accepts. Collects the Body-marked
    identities (IDENTITY_RULE) and whether any marked element sits inside another."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []  # [tag, path, {child tag: count so far}, marked]
        self.seen = {}
        self.ids = set()
        self.doctypes = 0
        self.metas = []
        self.markers = []
        self.nested = False

    def handle_decl(self, decl):
        if decl.lower() != "doctype html" or self.stack or self.seen or self.doctypes:
            raise ValueError("doctype")
        self.doctypes += 1

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if len(at) != len(attrs):
            raise ValueError("duplicate attribute on " + tag)
        parent = self.stack[-1][0] if self.stack else None
        if tag in SVG:
            allowed = parent in {"svg", "g"}
        elif tag in FLOW:
            allowed = parent == "body" or (parent in FLOW and parent not in VOID and parent != "svg")
        elif tag in HEAD:
            allowed = parent in HEAD[tag]
        else:
            raise ValueError("element outside the dialect: " + tag)
        if not allowed:
            raise ValueError(f"{tag} inside {parent}")
        path = None
        if self.stack:
            siblings = self.stack[-1][2]
            siblings[tag] = siblings.get(tag, 0) + 1
            if self.stack[-1][1] is not None:
                path = self.stack[-1][1] + ">" + tag + "[" + str(siblings[tag]) + "]"
        if tag == "body":
            path = "body"
        self.seen[tag] = self.seen.get(tag, 0) + 1
        marked = False
        if tag == "html":
            if at != {"lang": "en"}:
                raise ValueError("html attributes")
        elif tag in {"head", "body", "title", "style"}:
            if at:
                raise ValueError(tag + " attributes")
        elif tag == "meta":
            if at != {"charset": "utf-8"} and (set(at) != {"name", "content"}
                                               or not all(isinstance(x, str) for x in at.values())):
                raise ValueError("meta attributes")
            self.metas.append(at)
        elif tag == "link":
            if set(at) != {"rel", "href"} or at["rel"] != "stylesheet" or not isinstance(at["href"], str):
                raise ValueError("link attributes")
        else:
            identity = at.get("id", path)
            if "id" in at and (not isinstance(at["id"], str) or not re.fullmatch(ID, at["id"])):
                raise ValueError("bad id")
            if identity in self.ids:
                raise ValueError("duplicate id")
            self.ids.add(identity)
            in_svg = tag == "svg" or tag in SVG
            if "style" in at and not in_svg:
                raise ValueError("inline style on " + tag)
            if "data-body-role" in at:
                raise ValueError("data-body-role")
            marked = at.get("data-typography") == "Body"
            if marked:
                if in_svg:
                    raise ValueError("Body mark inside svg")
                if any(frame[3] for frame in self.stack):
                    self.nested = True
                self.markers.append(identity)
        if tag not in VOID:
            self.stack.append([tag, path, {}, marked])

    def handle_startendtag(self, tag, attrs):
        if tag not in SVG:
            raise ValueError("self-closing syntax on " + tag)
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError("unbalanced end tag " + tag)
        self.stack.pop()

    def handle_data(self, data):
        top = self.stack[-1][0] if self.stack else None
        if top == "style" or not data.strip():
            return
        if top in {None, "html", "head", "body"}:
            raise ValueError("uncontained text")
        if top == "svg" or top in SVG:
            raise ValueError("text in svg")

    def handle_entityref(self, name):
        raise ValueError("entity")

    def handle_charref(self, name):
        raise ValueError("character reference")

    def handle_comment(self, data):
        raise ValueError("comment")

    def handle_pi(self, data):
        raise ValueError("processing instruction")

    def unknown_decl(self, data):
        raise ValueError("unknown declaration")


def body_inventory(raw):
    """The page's Body-marked identities in document order, after checking the page is in the dialect."""
    reader = _Dialect()
    reader.feed(raw.decode("utf-8", errors="strict"))
    reader.close()
    if reader.stack or reader.doctypes != 1:
        raise ValueError("incomplete document")
    if any(reader.seen.get(x) != 1 for x in ("html", "head", "body", "title")) or reader.seen.get("style", 0) > 1:
        raise ValueError("document cardinality")
    if [x for x in reader.metas if "charset" in x] != [{"charset": "utf-8"}]:
        raise ValueError("required metadata")
    if not reader.markers or reader.nested or len(set(reader.markers)) != len(reader.markers):
        raise ValueError("bad Body marks")
    if not all(re.fullmatch(ID, x) or re.fullmatch(r"body(?:>[a-z][a-z0-9]*\[[1-9][0-9]*\])+", x)
               for x in reader.markers):
        raise ValueError("bad marker identity")
    return reader.markers


class _Headlines(HTMLParser):
    """The A1-02 headline rule: every character run between <h1> and </h1>."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.headlines = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.current = []
            self.headlines.append(self.current)

    def handle_endtag(self, tag):
        if tag == "h1":
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)


def headlines(text):
    parser = _Headlines()
    parser.feed(text)
    parser.close()
    return [" ".join("".join(x).split()) for x in parser.headlines]


def h1_count(text):
    """A2-01's rule, counted independently: h1 start tags in the source (hidden ones included)."""
    return len(re.findall(r"<h1[\s>]", text))


def normalize(text):
    counts = {}
    for name, _, step in NORMALIZE:
        text, counts[name] = step(text)
    text, counts["body-marks"] = re.subn(r"<p>", "<p" + BODY_MARK + ">", text)
    return text, counts


def _only(text, needle):
    if text.count(needle) != 1:
        raise ValueError("expected exactly one " + needle)
    return text.index(needle)


def planted(text, variant, words):
    """Planted copy of a normalized page; words = the original headline's word count."""
    h1_start = _only(text, "<h1")
    h1_end = _only(text, "</h1>")
    if variant == "P0":
        return text
    if variant in ("P1", "P3"):
        at = text.rfind("</section>")
        if at < h1_end:
            raise ValueError("no section end after the h1")
        return text[:at] + (P1_INSERT if variant == "P1" else P3_INSERT) + text[at:]
    if variant == "P2":
        return text[:h1_start] + "<h2" + text[h1_start + 3:h1_end] + "</h2>" + text[h1_end + 5:]
    if variant == "P4":
        extra = LIMIT + 3 - words
        if not 0 < extra <= len(P4_WORDS):
            raise ValueError(f"cannot reach {LIMIT + 3} words")
        return text[:h1_end] + " " + " ".join(P4_WORDS[:extra]) + text[h1_end:]
    if variant == "P5":
        inner_start = text.index(">", h1_start) + 1
        for run in re.finditer(r"<[^>]*>|[^<]+", text[inner_start:h1_end]):
            word = None if run.group().startswith("<") else re.search(WORD, run.group())
            if word:
                if word.group() == P5_WORD:
                    raise ValueError("first word already " + P5_WORD)
                at = inner_start + run.start() + word.start()
                return text[:at] + P5_WORD + text[at + len(word.group()):]
        raise ValueError("no word in the h1")
    raise ValueError(variant)


def a2_record(markers, count):
    return {
        "guard_decision": None, "guard_metadata": {"markers": markers},
        "source_h1_count": count, "source_count_equals_one": count == 1,
        "actual_environment": None, "rendered_hierarchy": "UNMEASURED", "page_verdict": "UNQUALIFIED",
    }


def a1_record(markers, count):
    """count None = UNBOUND_TARGET (no count); else BOUND_H1 with the count."""
    return {
        "guard_decision": None, "guard_metadata": {"markers": markers},
        "binding_status": "UNBOUND_TARGET" if count is None else "BOUND_H1",
        "source_word_count": count, "source_word_count_lte_12": None if count is None else 1 <= count <= LIMIT,
        "actual_environment": None, "first_viewport_visibility": "UNMEASURED",
        "nomination_timing": "UNVERIFIED", "page_verdict": "UNQUALIFIED",
    }


def bound_count(text, declared):
    """A1-02's binding and count rule applied to a planted copy: the count when bound, else None."""
    if not isinstance(declared, str):
        return None
    declared = " ".join(declared.split())
    if not declared or not declared.isascii():
        return None
    found = headlines(text)
    if len(found) != 1 or found[0] != declared:
        return None
    return len(re.findall(WORD, found[0]))


def line(value):
    return json.dumps(value, separators=(",", ":")) + "\n"


def main():
    a2_dir = HERE / "a2-01-source-h1"
    a1_dir = HERE / "a1-02-headline-words"
    fixtures = HERE / "fixtures"
    if any((d / "EXPECTED.jsonl").exists() for d in (a2_dir, a1_dir)) or fixtures.exists():
        sys.exit("source-checks-v2 already built: frozen, not overwritten")
    expected_h1 = {"P0": 1, "P1": 2, "P2": 0, "P3": 2, "P4": 1, "P5": 1}
    built, pages = [], []
    for name in PAGES:
        source = SOURCES / (name + ".html")
        raw = source.read_bytes()
        text, counts = normalize(raw.decode("utf-8", errors="strict"))
        original = headlines(text)
        if len(original) != 1 or h1_count(text) != 1 or not original[0].isascii():
            sys.exit("page does not have exactly one ASCII h1: " + name)
        words = len(re.findall(WORD, original[0]))
        pages.append({"page": "configs/design/testpages/html-fixtures/" + source.name,
                      "sha256": hashlib.sha256(raw).hexdigest(), "normalized": counts,
                      "headline": original[0], "headline_words": words})
        for variant in VARIANTS:
            case = name + "-" + variant
            body = planted(text, variant, words).encode("utf-8")
            markers = body_inventory(body)  # the dialect check; refuses the page if anything is outside it
            if variant == "P4":
                declared = original[0] + " " + " ".join(P4_WORDS[:LIMIT + 3 - words])
                source_note = "frozen: this planted copy's lengthened headline"
            else:
                declared = original[0]
                source_note = "frozen: the page's original h1 text"
            count = bound_count(body.decode("utf-8"), declared)
            # The plant did what the construction says (each rule applied to the copy itself).
            copy = body.decode("utf-8")
            if h1_count(copy) != expected_h1[variant] or len(headlines(copy)) != expected_h1[variant]:
                sys.exit("plant check failed (h1 count) " + case)
            if (variant in ("P0", "P4")) != (count is not None):
                sys.exit("plant check failed (binding) " + case)
            if count is not None and count != (words if variant == "P0" else LIMIT + 3):
                sys.exit("plant check failed (word count) " + case)
            if variant == "P5" and (headlines(copy)[0] == original[0]
                                    or len(re.findall(WORD, headlines(copy)[0])) != words):
                sys.exit("plant check failed (P5) " + case)
            if variant != "P0" and markers != built[-1]["markers"]:
                sys.exit("plant check failed (Body marks moved) " + case)
            built.append({"case": case, "page": name, "body": body, "markers": markers, "declared": declared,
                          "declaration_source": source_note, "count": count, "h1": expected_h1[variant]})
    fixtures.mkdir()
    a2_dir.mkdir(exist_ok=True)
    a1_dir.mkdir(exist_ok=True)
    a2_cases, a1_cases, a2_lines, a1_lines = [], [], [], []
    for item in built:
        case, body = item["case"], item["body"]
        (fixtures / (case + ".html")).write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        inventory = {"schema": "body-roots/1", "roots": item["markers"]}
        slot = f"{case}@{ENVIRONMENT[0]}x{ENVIRONMENT[1]}"
        source_page = "configs/design/testpages/html-fixtures/" + item["page"] + ".html"
        a2_cases.append({"case": case, "source_page": source_page, "html": "../fixtures/" + case + ".html",
                         "actual_sha256": sha, "declared_sha256": sha, "inventory": inventory})
        a1_cases.append({"case": case, "source_page": source_page, "path": "../fixtures/" + case + ".html",
                         "actual_sha256": sha, "declared_sha256": sha, "role_inventory": inventory,
                         "headline_declaration": {"schema": "value-headline/1", "target_tag": "h1",
                                                  "declared_text": item["declared"]},
                         "declaration_source": item["declaration_source"]})
        a2_lines.append(line({"slot": slot, "record": a2_record(item["markers"], item["h1"])}))
        a1_lines.append(line({"slot": slot, "result": a1_record(item["markers"], item["count"])}))
    common = {
        "key": "source-checks-v2 (Design #143): 4 public converter fixtures x (normalized as is + 5 plants), frozen "
               "before the widened kernels were copied in; expected records are truth by construction from the "
               "checks' rules",
        "environments": [ENVIRONMENT],
        "environments_are": "input membership only, not observed viewports",
        "identity_format": "case@WIDTHxHEIGHT; case-major order; harness only",
        "normalize": {name: text for name, text, _ in NORMALIZE},
        "body_mark_rule": BODY_MARK_RULE,
        "identity_rule": IDENTITY_RULE,
        "plants": PLANTS,
        "pages": pages,
    }
    a2_true = sum(item["h1"] == 1 for item in built)
    a2_inputs = {"schema": "source-h1-inputs/1", **common,
                 "checker_arguments": ["html bytes", "declared_sha256", "inventory", "environment"],
                 "cases": a2_cases, "repetitions": 1, "slots_per_repetition": len(a2_cases),
                 "per_repetition_expected": {"source_true": a2_true, "source_false": len(built) - a2_true,
                                             "input_refuse": 0},
                 "actual_environment": None, "rendered_hierarchy": "UNMEASURED", "page_verdict": "UNQUALIFIED"}
    a1_inputs = {"schema": "a1-02-headline-inputs/1", **common, "declarations": DECLARATIONS,
                 "role_inventory": "per case (pages differ): cases[].role_inventory", "cases": a1_cases,
                 "transport": "in-process call with html_bytes, declared_sha256, role_inventory, environment_tuple, "
                              "headline_declaration in that order; slot identities stay in the harness."}
    for folder, inputs, lines in ((a2_dir, a2_inputs, a2_lines), (a1_dir, a1_inputs, a1_lines)):
        (folder / "INPUTS.json").write_text(json.dumps(inputs, indent=1) + "\n")
        (folder / "EXPECTED.jsonl").write_text("".join(lines))
    for page in pages:
        print(page["page"], page["normalized"], page["headline_words"], "words")
    print("cases", len(built), "A2-01 true", a2_true, "A1-02 bound", sum(i["count"] is not None for i in built),
          "Body marks per page", [len(i["markers"]) for i in built[::6]])


if __name__ == "__main__":
    main()
