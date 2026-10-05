#!/usr/bin/env python3
"""The fixed positioning_grade benchmark (queue #1, Product marketing): materialise its ten cases.

    python3 build.py --check     every labelled mutation applies exactly, and the checker alone (no
                                 model) finds what expected.json's "script" says for every case
    python3 build.py OUTDIR      write OUTDIR/<key>/ for every case in expected.json: positioning.md,
                                 positioning.json and evidence/, and print the sha256 of every file
                                 (refuses to overwrite a file with different content)

A control is a source document as it is. A mutant is a source document with the labelled edits of
mutations.json applied to positioning.md, and to positioning.json where section 6 is mirrored
there. The evidence folder is the same for every case and is never edited: it is what a grader
checks the document against. Case folders carry opaque keys and the expectations stay in
expected.json: neither the case names nor the planted defects reach a run. Everything here is
fictional (Kettlemark is a made-up product). Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "sources"
EVIDENCE = HERE / "evidence"
CHECKER = HERE.parents[2] / "configs" / "agents" / "positioning_grade_assets" / "check_positioning.py"
DOCUMENTS = ("positioning.md", "positioning.json")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(text: str) -> str:
    """Text as markers are matched: no emphasis marks, straight quotes, one space, any case."""
    text = text.translate(str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}))
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text)).strip().lower()


def cases() -> list[dict]:
    return json.loads((HERE / "expected.json").read_text())["cases"]


def mutants() -> dict:
    return json.loads((HERE / "mutations.json").read_text())["mutants"]


def _one_line(lines: list[str], needle: str, what: str, start: int = 0) -> int:
    hits = [i for i in range(start, len(lines)) if needle in lines[i]]
    if start == 0 and len(hits) != 1:
        raise ValueError(f"{what}: {needle!r} is on {len(hits)} lines, expected exactly 1")
    if not hits:
        raise ValueError(f"{what}: {needle!r} not found after line {start + 1}")
    return hits[0]


def _json_set(text: str, path: list, value, what: str) -> str:
    doc = json.loads(text)
    target = doc
    for key in path[:-1]:
        target = target[key]
    last = path[-1]
    present = (0 <= last < len(target)) if isinstance(target, list) and isinstance(last, int) else (
        isinstance(target, dict) and last in target)
    if not present:
        raise ValueError(f"{what}: positioning.json has no {path}")
    if target[last] == value:
        raise ValueError(f"{what}: {path} already holds that value")
    target[last] = value
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def apply_op(files: dict[str, str], op: dict, what: str) -> None:
    name, kind = op["file"], op["op"]
    if name not in files:
        raise ValueError(f"{what}: {name!r} is not one of {DOCUMENTS}")
    text = files[name]
    if kind == "replace":
        count = op.get("count", 1)
        found = text.count(op["find"])
        if found != count:
            raise ValueError(f"{what}: {op['find']!r} occurs {found} times, expected {count}")
        files[name] = text.replace(op["find"], op["with"])
    elif kind == "replace_lines":
        lines = text.split("\n")
        first = _one_line(lines, op["start"], what)
        last = _one_line(lines, op["end"], what, start=first)
        files[name] = "\n".join(lines[:first] + op["with"].split("\n") + lines[last + 1 :])
    elif kind == "json_set":
        if name != "positioning.json":
            raise ValueError(f"{what}: json_set edits positioning.json only")
        files[name] = _json_set(text, op["path"], op["value"], what)
    else:
        raise ValueError(f"{what}: unknown op {kind!r}")


def mutated(mutant_id: str) -> dict[str, str]:
    """The two documents of one mutant, its edits applied in order."""
    mutant = mutants()[mutant_id]
    base = SOURCES / mutant["base"]
    files = {name: (base / name).read_text() for name in DOCUMENTS}
    for n, op in enumerate(mutant["ops"], 1):
        apply_op(files, op, f"{mutant_id} op {n}")
    if files["positioning.md"] == (base / "positioning.md").read_text():
        raise ValueError(f"{mutant_id}: the document did not change")
    return files


def case_files(case: dict) -> dict[str, bytes]:
    """Every file of one case, by its path inside the case folder."""
    base = SOURCES / case["base"]
    files = {name: (base / name).read_bytes() for name in DOCUMENTS}
    for path in sorted(EVIDENCE.rglob("*")):
        if path.is_file():
            files[f"evidence/{path.relative_to(EVIDENCE).as_posix()}"] = path.read_bytes()
    if case.get("mutant"):
        mutant = mutants()[case["mutant"]]
        if mutant["base"] != case["base"]:
            raise SystemExit(f"{case['case']}: mutant {case['mutant']} is built on {mutant['base']}")
        for name, text in mutated(case["mutant"]).items():
            files[name] = text.encode()
    return files


def materialise(outdir: Path) -> dict[str, dict[str, str]]:
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


def load_checker() -> types.ModuleType:
    """check_positioning.py as a module, without leaving bytecode next to it."""
    module = types.ModuleType("check_positioning")
    module.__file__ = str(CHECKER)
    sys.modules["check_positioning"] = module
    exec(compile(CHECKER.read_text(), str(CHECKER), "exec"), module.__dict__)
    return module


def script_mismatches(case: dict, findings: list[dict]) -> list[str]:
    """How the checker's own findings for a case differ from expected.json's "script" list."""
    wanted = case["script"]

    def matches(finding: dict, want: dict) -> bool:
        return (finding["criterion"] == want["criterion"] and finding["kind"] == want["kind"]
                and any(norm(want["marker"]) in norm(p["text"]) for p in finding["passages"]))

    problems = [f"no {w['criterion']} {w['kind']} finding on \"{w['marker']}\""
                for w in wanted if not any(matches(f, w) for f in findings)]
    problems += [f"unexpected {f['criterion']} {f['kind']}: {f['problem']}"
                 for f in findings if not any(matches(f, w) for w in wanted)]
    return problems


def check() -> int:
    for mutant_id, mutant in mutants().items():
        files = mutated(mutant_id)
        print(f"{mutant_id} ({mutant['criterion']}): {len(mutant['ops'])} edits applied to {mutant['base']}")
        if mutant["base"] not in {c["base"] for c in cases() if c.get("mutant") == mutant_id}:
            raise SystemExit(f"{mutant_id} is in no case of expected.json")
        json.loads(files["positioning.json"])
    checker = load_checker()
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        materialise(Path(tmp))
        for case in cases():
            folder = Path(tmp) / case["key"]
            result = checker.run_check(folder / "positioning.md", folder / "positioning.json", folder / "evidence")
            problems = script_mismatches(case, result["findings"]) + result["problems"]
            failed += bool(problems)
            found = ", ".join(f"{f['criterion']} {f['kind']}" for f in result["findings"]) or "no finding"
            print(f"{case['case']} {case['key']}: {found}; {len(result['leads'])} leads"
                  + "".join(f"\n    MISMATCH {p}" for p in problems))
    print("every mutation applies exactly; the checker finds what expected.json says" if not failed
          else f"{failed} cases differ from expected.json")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == "--check":
        sys.exit(check())
    for key, digests in materialise(Path(sys.argv[1])).items():
        for rel, digest in digests.items():
            print(f"{digest}  {key}/{rel}")
