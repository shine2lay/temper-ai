#!/usr/bin/env python3
"""positioning workflow tools (Product marketing): derive positioning.json from section 6 of a
positioning document (FORMAT.md, positioning/1) and check the document with positioning_grade's
own checker, so the writers, the check step and the grade read a document the same way.
Standard library only. Imports check_positioning.py from --checker (default: next to this file;
the workflow's setup step copies both into state/positioning/). Run from the run workspace.

    positioning_tools.py json --doc positioning.md
        Write positioning.json next to the document: the messaging hierarchy of section 6 (value
        proposition, pillars, proof points, each with its citations and assumption tag), exactly
        as the checker reads it. Never hand-write positioning.json.
    positioning_tools.py lint --doc positioning.md --evidence DIR
        Write positioning.json, then print every format finding the checker would count (each with
        its line) and the leads a grade's reviewer will ask about. Exit 1 when there are findings.
    positioning_tools.py check --doc positioning.md --evidence DIR --round NAME [--strict]
        The workflow's check step: write positioning.json, check, and write
        state/positioning/check_NAME.json and check_NAME.md (the findings, each with its line).
        Prints the result as one JSON line. --strict exits 1 when findings remain.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path("state/positioning")
CITATION_KINDS = ("uncited", "missing_file", "quote_not_found", "number_mismatch", "empty_quote")


def load_checker(path: Path):
    if not path.is_file():
        raise SystemExit(f"no checker at {path}")
    spec = importlib.util.spec_from_file_location("check_positioning", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_positioning"] = module
    spec.loader.exec_module(module)
    return module


def derive(checker, text: str) -> dict:
    """positioning.json for a document: section 6 as the checker parses it."""
    parsed = checker.parse_document(text)

    def item(record: dict) -> dict:
        return {"text": record["text"],
                "citations": [{"file": c["file"], "quote": c["quote"]} for c in record["citations"]],
                "assumption": bool(record["assumption"])}

    lines = parsed["vp"]["lines"]
    return {"format": checker.FORMAT_VERSION, "product": checker.product_of(parsed["title"]),
            "value_proposition": item(lines[0]) if lines else None,
            "pillars": [{"benefit": p["benefit"], "proof_points": [item(r) for r in p["proofs"]]}
                        for p in parsed["pillars"]]}


def write_json(checker, doc: Path) -> Path:
    target = doc.with_name("positioning.json")
    target.write_text(json.dumps(derive(checker, doc.read_text(errors="replace")), indent=1,
                                 ensure_ascii=False) + "\n")
    return target


def line_of(finding: dict) -> int | None:
    return finding["passages"][0]["line"] if finding.get("passages") else None


def run(checker, doc: Path, evidence: Path) -> dict:
    """Check the document as the grade's check step does, after writing its positioning.json."""
    json_path = write_json(checker, doc)
    return checker.run_check(doc, json_path, evidence)


def report_md(result: dict, doc: Path, round_name: str) -> str:
    lines = doc.read_text(errors="replace").split("\n")
    out = [f"# Positioning check, round {round_name}", "",
           f"Document {doc}; positioning.json written from its section 6. Findings are format and "
           "evidence defects the grade counts as material: fix each one at its line.", ""]
    findings = result["findings"]
    out.append(f"## Findings ({len(findings)})")
    out.append("")
    for f in findings:
        n = line_of(f)
        out.append(f"- {f['id']} {f['criterion']} {f['kind']}" + (f", line {n}" if n else "") + f": {f['problem']}")
        if n and 1 <= n <= len(lines):
            out.append(f"  line {n}: {lines[n - 1].strip()}")
    if not findings:
        out.append("None.")
    out += ["", f"## Leads a grade's reviewer will ask about ({len(result['leads'])})", ""]
    out += [f"- {lead['criterion']} {lead['type']}: {lead['text']}" for lead in result["leads"]] or ["None."]
    if result.get("problems"):
        out += ["", "## Problems", ""] + [f"- {p}" for p in result["problems"]]
    return "\n".join(out) + "\n"


def summary(result: dict) -> dict:
    kinds: dict[str, int] = {}
    for f in result["findings"]:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    return {"findings": len(result["findings"]), "kinds": kinds,
            "citation_failures": sum(n for k, n in kinds.items() if k in CITATION_KINDS),
            "leads": len(result["leads"])}


def cmd_json(checker, args) -> int:
    doc = Path(args.doc)
    if not doc.is_file():
        print(f"no document at {doc}")
        return 1
    print(f"wrote {write_json(checker, doc)}")
    return 0


def cmd_lint(checker, args) -> int:
    doc, evidence = Path(args.doc), Path(args.evidence)
    if not doc.is_file() or not evidence.is_dir():
        print(f"need a document at {doc} and an evidence folder at {evidence}")
        return 1
    result = run(checker, doc, evidence)
    for f in result["findings"]:
        print(f"{f['id']} {f['criterion']} {f['kind']} line {line_of(f) or '-'}: {f['problem']}")
    for lead in result["leads"]:
        print(f"lead {lead['criterion']} {lead['type']}: {lead['text']}")
    for problem in result.get("problems") or []:
        print(f"problem: {problem}")
    print(f"{len(result['findings'])} findings, {len(result['leads'])} leads")
    return 1 if result["findings"] else 0


def cmd_check(checker, args) -> int:
    doc, evidence, name = Path(args.doc), Path(args.evidence), args.round
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise SystemExit(f"round {name!r}: letters, digits, _ and - only")
    OUT.mkdir(parents=True, exist_ok=True)
    problems = [p for p, bad in ((f"no document at {doc}", not doc.is_file()),
                                 (f"no evidence folder at {evidence}", not evidence.is_dir())) if bad]
    if problems:
        print(json.dumps({"status": "not_checked", "round": name, "findings": 0, "citation_failures": 0,
                          "kinds": {}, "check_path": "", "positioning_path": str(doc),
                          "json_path": "", "problems": problems}))
        return 1
    result = run(checker, doc, evidence)
    (OUT / f"check_{name}.json").write_text(json.dumps(
        {"round": name, "document": str(doc), "evidence": str(evidence), **summary(result),
         "findings": result["findings"], "leads": result["leads"], "problems": result.get("problems") or []},
        indent=1, ensure_ascii=False) + "\n")
    (OUT / f"check_{name}.md").write_text(report_md(result, doc, name))
    s = summary(result)
    print(json.dumps({"status": "findings" if s["findings"] else "clean", "round": name,
                      "findings": s["findings"], "citation_failures": s["citation_failures"], "kinds": s["kinds"],
                      "check_path": str(OUT / f"check_{name}.md"), "positioning_path": str(doc),
                      "json_path": str(doc.with_name("positioning.json")),
                      "problems": result.get("problems") or []}))
    return 1 if args.strict and s["findings"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checker", default=str(HERE / "check_positioning.py"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("json")
    p.add_argument("--doc", required=True)
    p = sub.add_parser("lint")
    p.add_argument("--doc", required=True)
    p.add_argument("--evidence", required=True)
    p = sub.add_parser("check")
    p.add_argument("--doc", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--round", required=True)
    p.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    checker = load_checker(Path(args.checker))
    return {"json": cmd_json, "lint": cmd_lint, "check": cmd_check}[args.cmd](checker, args)


if __name__ == "__main__":
    sys.exit(main())
