#!/usr/bin/env python3
"""Make the known answers of tests/test_e2e_shards.py from real Playwright reports.

Runs the tiny suite in suite/ (plain node tests: no page, no browser, no server) with the repo's
own Playwright, the way the CI shards run the server-free suite, and keeps what the checker reads.
Run `npm ci` in frontend/ first, then, from the repo root:

    python3 tests/fixtures/e2e_shards/generate.py

It writes reports/<set>/e2e-shard-<i>-of-3/ (playwright-junit.xml, list.json, test-list.txt,
meta.json) for two sets, "clean" and "failing" (clean plus a test that fails on every attempt),
and reports/single/ for flaky_report.py: the clean files' first one run without
PLAYWRIGHT_JUNIT_INCLUDE_RETRIES, and once with --retries=0 --repeat-each=2. Left out of the
reports: system-out, system-err, stack traces, failure messages and this machine's paths.
Re-run it after a Playwright upgrade and commit what changes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE / "suite"
OUT = HERE / "reports"
REPO = HERE.parents[2]
FRONTEND = REPO / "frontend"
CONFIG = SUITE / "playwright.config.js"

FIXTURE_SHA = "5ad0f1c7" * 5
SETS = {
    "clean": ("clean.txt", [["alpha.spec.ts"], ["beta.spec.ts"], ["gamma.spec.ts"]]),
    "failing": ("failing.txt", [["alpha.spec.ts"], ["beta.spec.ts"], ["gamma.spec.ts", "delta.spec.ts"]]),
}
TEXT_KEPT_OUT = {"system-out", "system-err", "stackTrace"}
RESULTS = {"failure", "error", "flakyFailure", "flakyError", "rerunFailure", "rerunError", "skipped"}


def playwright(args: list[str], env: dict[str, str]) -> None:
    """Run the repo's Playwright on the fixture suite; a red run is expected for failing tests."""
    inherited = {k: v for k, v in os.environ.items() if not k.startswith(("PLAYWRIGHT_", "PW_"))}
    subprocess.run(["npx", "--no-install", "playwright", "test", "-c", str(CONFIG), *args], cwd=FRONTEND,
                   env={**inherited, "NODE_PATH": str(FRONTEND / "node_modules"), **env},
                   stdout=subprocess.DEVNULL, check=False, timeout=300)


def scrub_junit(path: Path, to: Path) -> None:
    root = ET.parse(path).getroot()
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag in TEXT_KEPT_OUT:
                parent.remove(child)
    for element in root.iter():
        if element.tag in RESULTS:
            element.attrib.pop("message", None)
            element.text = None
    ET.indent(root)
    to.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n")


def scrub_json(path: Path, to: Path, tmp: Path) -> None:
    swaps = [(str(tmp), "<tmp>"), (str(REPO), "<repo>"), (str(Path.home()), "~")]

    def clean(value):
        if isinstance(value, str):
            for old, new in swaps:
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value

    to.write_text(json.dumps(clean(json.loads(path.read_text(encoding="utf-8"))), indent=2, ensure_ascii=False)
                  + "\n", encoding="utf-8")


def shard(name: str, files: list[str], i: int, of: int, tmp: Path) -> None:
    listing = SETS[name][0]
    where = OUT / name / f"e2e-shard-{i}-of-{of}"
    where.mkdir(parents=True)
    test_list = where / "test-list.txt"
    test_list.write_text("".join(f"{file}\n" for file in files), encoding="utf-8")
    common = {"E2E_SHARDS_FIXTURE_LIST": str(SUITE / listing), "E2E_SHARDS_FIXTURE_OUTPUT": str(tmp / "results")}
    playwright(["--list", "--reporter=json"], {**common, "PLAYWRIGHT_JSON_OUTPUT_NAME": str(tmp / "list.json")})
    playwright(["--test-list", str(test_list), "--reporter=junit"],
               {**common, "PLAYWRIGHT_JUNIT_OUTPUT_NAME": str(tmp / "junit.xml"), "PLAYWRIGHT_JUNIT_INCLUDE_RETRIES": "1"})
    scrub_json(tmp / "list.json", where / "list.json", tmp)
    scrub_junit(tmp / "junit.xml", where / "playwright-junit.xml")
    subprocess.run([sys.executable, str(REPO / "scripts" / "e2e_shards.py"), "meta", "--shard", str(i), "--of", str(of),
                    "--out", str(where / "meta.json")], check=True, timeout=120,
                   env={**os.environ, "GITHUB_SHA": FIXTURE_SHA, "GITHUB_RUN_ATTEMPT": "1",
                        "ImageOS": "fixture", "ImageVersion": "fixture"})


def single(to: str, args: list[str], env: dict[str, str], tmp: Path) -> None:
    alone = tmp / "alone.txt"
    alone.write_text("alpha.spec.ts\n", encoding="utf-8")
    playwright(["--reporter=junit", *args],
               {"E2E_SHARDS_FIXTURE_LIST": str(alone), "E2E_SHARDS_FIXTURE_OUTPUT": str(tmp / "results"),
                "PLAYWRIGHT_JUNIT_OUTPUT_NAME": str(tmp / "junit.xml"), **env})
    (OUT / "single").mkdir(parents=True, exist_ok=True)
    scrub_junit(tmp / "junit.xml", OUT / "single" / to)


def main() -> int:
    if not (FRONTEND / "node_modules" / "@playwright" / "test").is_dir():
        print("run `npm ci` in frontend/ first", file=sys.stderr)
        return 1
    os.umask(0o022)
    shutil.rmtree(OUT, ignore_errors=True)
    for name, (_, shards) in SETS.items():
        for i, files in enumerate(shards, 1):
            with tempfile.TemporaryDirectory() as tmp:
                shard(name, files, i, len(shards), Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        single("no-retries.xml", [], {}, Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        single("repeats.xml", ["--retries=0", "--repeat-each=2"], {}, Path(tmp))
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
