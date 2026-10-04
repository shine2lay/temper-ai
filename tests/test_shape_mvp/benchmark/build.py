#!/usr/bin/env python3
"""The fixed shape_mvp benchmark (queue #11): materialise its seven opportunities.

    python3 build.py OUTDIR      write OUTDIR/<CASE>.json for every case in expected.json and print
                                 their sha256 (refuses to overwrite a file with different content)

A derived case (a file with derive_from) is its base case with the named top-level fields removed
or set, so each controlled pair differs only in what its derivation names. The expectations stay
in expected.json and never reach a run. Standard library only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_case(name: str) -> dict:
    raw = json.loads((HERE / name).read_text())
    if "derive_from" not in raw:
        return raw
    out = copy.deepcopy(load_case(raw["derive_from"]))
    for key in raw.get("remove", []):
        out.pop(key, None)
    for key, value in raw.get("set", {}).items():
        out[key] = copy.deepcopy(value)
    return out


def cases() -> list[dict]:
    return json.loads((HERE / "expected.json").read_text())["cases"]


def rendered(case: dict) -> str:
    return json.dumps(load_case(case["file"]), indent=2, ensure_ascii=False) + "\n"


def materialise(outdir: Path) -> dict[str, str]:
    outdir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for case in cases():
        data = rendered(case)
        target = outdir / f"{case['case']}.json"
        if target.exists() and target.read_text() != data:
            raise SystemExit(f"{target} exists with different content: use a fresh folder")
        target.write_text(data)
        hashes[case["case"]] = hashlib.sha256(data.encode()).hexdigest()
    return hashes


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    for name, digest in materialise(Path(sys.argv[1])).items():
        print(f"{digest}  {name}.json")
