#!/usr/bin/env python3
"""The fixed signal_grade benchmark (queue #12): materialise its nine reports.

    python3 build.py --check     verify the frozen source copies against SOURCES.json and that
                                 every labelled mutation applies exactly (no output written)
    python3 build.py OUTDIR      write OUTDIR/<key>/ for every case in expected.json: the report
                                 laid out like a signal_harvest run (shortlist.txt,
                                 signal_scorecard.md, signal/<lens>.md), and print the sha256 of
                                 every file (refuses to overwrite a file with different content)

A control is a frozen source copy as it is. A mutant is a source copy with the labelled edits of
mutations.json applied to its scorecard only; the lens files and shortlist stay as they were, so
they are the evidence a grader must check the planted defect against. Case folders carry opaque
keys, and the expectations stay in expected.json: neither the case names nor the expected
findings reach a run. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "sources"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frozen() -> dict:
    return json.loads((HERE / "SOURCES.json").read_text())


def check_sources() -> None:
    expected = frozen()["sha256"]
    found = {
        str(p.relative_to(SOURCES)): sha(p.read_bytes())
        for p in sorted(SOURCES.rglob("*"))
        if p.is_file()
    }
    if found != expected:
        missing = sorted(set(expected) - set(found))
        extra = sorted(set(found) - set(expected))
        changed = sorted(k for k in set(found) & set(expected) if found[k] != expected[k])
        raise SystemExit(
            f"frozen sources differ from SOURCES.json: missing {missing}, extra {extra}, changed {changed}"
        )


def _one_line(lines: list[str], needle: str, what: str, start: int = 0) -> int:
    hits = [i for i in range(start, len(lines)) if needle in lines[i]]
    if start == 0 and len(hits) != 1:
        raise ValueError(f"{what}: {needle!r} is on {len(hits)} lines, expected exactly 1")
    if not hits:
        raise ValueError(f"{what}: {needle!r} not found after line {start + 1}")
    return hits[0]


def apply_op(text: str, op: dict, what: str) -> str:
    kind = op["op"]
    if kind == "replace":
        count = op.get("count", 1)
        found = text.count(op["find"])
        if found != count:
            raise ValueError(f"{what}: {op['find']!r} occurs {found} times, expected {count}")
        return text.replace(op["find"], op["with"])
    lines = text.split("\n")
    if kind == "replace_lines":
        first = _one_line(lines, op["start"], what)
        last = _one_line(lines, op["end"], what, start=first)
        new = op["with"].split("\n") if op["with"] else []
        return "\n".join(lines[:first] + new + lines[last + 1 :])
    if kind == "insert_after":
        at = _one_line(lines, op["anchor"], what)
        return "\n".join(lines[: at + 1] + op["text"].split("\n") + lines[at + 1 :])
    raise ValueError(f"{what}: unknown op {kind!r}")


def mutants() -> dict:
    return json.loads((HERE / "mutations.json").read_text())["mutants"]


def mutated_scorecard(mutant_id: str) -> str:
    mutant = mutants()[mutant_id]
    text = (SOURCES / mutant["base"] / "signal_scorecard.md").read_text()
    for defect_id, defect in mutant["defects"].items():
        for n, op in enumerate(defect["ops"], 1):
            text = apply_op(text, op, f"{mutant_id} {defect_id} op {n}")
    if text == (SOURCES / mutant["base"] / "signal_scorecard.md").read_text():
        raise ValueError(f"{mutant_id}: mutations changed nothing")
    return text


def cases() -> list[dict]:
    return json.loads((HERE / "expected.json").read_text())["cases"]


def case_files(case: dict) -> dict[str, bytes]:
    base = SOURCES / case["base"]
    files = {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}
    if case.get("mutant"):
        mutant = mutants()[case["mutant"]]
        if mutant["base"] != case["base"]:
            raise SystemExit(f"{case['case']}: mutant {case['mutant']} is built on {mutant['base']}")
        files["signal_scorecard.md"] = mutated_scorecard(case["mutant"]).encode()
    return files


def materialise(outdir: Path) -> dict[str, dict[str, str]]:
    check_sources()
    hashes: dict[str, dict[str, str]] = {}
    for case in cases():
        root = outdir / case["key"]
        hashes[case["key"]] = {}
        for rel, data in case_files(case).items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != data:
                raise SystemExit(f"{target} exists with different content: use a fresh folder")
            target.write_bytes(data)
            hashes[case["key"]][rel] = sha(data)
    return hashes


def check() -> None:
    check_sources()
    for mutant_id, mutant in mutants().items():
        original = (SOURCES / mutant["base"] / "signal_scorecard.md").read_text()
        text = mutated_scorecard(mutant_id)
        print(f"{mutant_id}: {len(mutant['defects'])} defects applied to {mutant['base']} "
              f"({len(original)} -> {len(text)} chars)")
    print("sources match SOURCES.json; every mutation applies exactly")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == "--check":
        check()
    else:
        for key, files in materialise(Path(sys.argv[1])).items():
            for rel, digest in files.items():
                print(f"{digest}  {key}/{rel}")
