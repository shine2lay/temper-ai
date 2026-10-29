#!/usr/bin/env python3
"""Run the server-free browser suite as time-balanced shards, and prove the shards ran all of it.

On one runner the suite (frontend/e2e/server-free.txt) took about 35 minutes, while every other
CI job ends by about 15. So CI runs it as the jobs "e2e shard (1/3)" to "(3/3)", each a third of
it by time, and the final job `e2e`, the check branch protection and `wt land` wait for, passes
only when every shard succeeded and together they ran every test of the listing exactly once.
How it works and how to refresh the weights: docs/ci-gate.md, "Browser test shards".

    e2e_shards.py plan    [--of 3] [--json]           every shard's files and predicted seconds
    e2e_shards.py split   --shard I --of 3 --out F    shard I's file list, for --test-list
    e2e_shards.py meta    --shard I --of 3 --out F    what ran: shard, attempt, commit, image, versions
    e2e_shards.py check   DIR --of 3 --sha SHA --needs JSON
    e2e_shards.py weights REPORT.xml [...] --out frontend/e2e/shard-weights.json [--source TEXT ...]

The split. Each listed file weighs the most seconds it took in recent reports
(frontend/e2e/shard-weights.json); a file without a weight gets the largest one and is named.
Heaviest first, ties by name, each file goes to the least-loaded of 3 x 2 worker slots, two slots
to a shard, as Playwright runs two workers on a GitHub runner. A shard's predicted time replays
Playwright's own schedule: its files in Playwright's order, each to whichever worker is free
first. Every shard works out the same split by itself, so no job has to plan it first.

The check reads only element names and the name, classname, hostname, time and tests attributes
of the reports, never system-out, system-err or failure text, and prints only test names and
counts. A missing artifact is MISSING; nothing falls back to job logs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "frontend" / "e2e" / "server-free.txt"
WEIGHTS = ROOT / "frontend" / "e2e" / "shard-weights.json"
PLAYWRIGHT_PACKAGE = ROOT / "frontend" / "node_modules" / "@playwright" / "test" / "package.json"

WORKERS = 2  # Playwright's default on a GitHub runner: half of its 4 cores
SEP = " \u203a "  # how Playwright's JUnit report joins a title path
ARTIFACT = "e2e-shard-{i}-of-{n}"
NEEDED = ("meta.json", "test-list.txt", "list.json", "playwright-junit.xml")
FLAKY = {"flakyFailure", "flakyError"}  # failed attempts of a test that then passed
RERUN = {"rerunFailure", "rerunError"}  # retries of a test that failed, which failed too
SHOWN = 20  # names listed per problem; the rest are counted

Identity = tuple[str, str, str]  # (project, file, title path joined by SEP)


# -- the split -------------------------------------------------------------------------------


def listed(path: Path = FILES) -> list[str]:
    """The spec files a list names, read as the workflow reads server-free.txt: no comments, no spaces."""
    lines = ("".join(line.split("#", 1)[0].split()) for line in path.read_text(encoding="utf-8").splitlines())
    return list(dict.fromkeys(line for line in lines if line))


def load_weights(path: Path = WEIGHTS) -> dict[str, float]:
    if not path.exists():
        return {}
    seconds = json.loads(path.read_text(encoding="utf-8"))["seconds"]
    return {str(file): float(value) for file, value in seconds.items()}


def playwright_order(files: list[str]) -> list[str]:
    """The order Playwright takes files in: it sorts directory entries with localeCompare, which
    for these names is a case-insensitive comparison."""
    return sorted(files, key=lambda file: (file.casefold(), file))


def simulate(files: list[str], weight: dict[str, float], workers: int = WORKERS) -> float:
    """Playwright's schedule replayed: one group per file, in its order, to the first free worker."""
    free = [0.0] * workers
    for file in playwright_order(files):
        worker = min(range(workers), key=lambda k: (free[k], k))
        free[worker] += weight[file]
    return max(free, default=0.0)


@dataclass
class Plan:
    shards: list[list[str]]  # each shard's files, in Playwright's order
    seconds: list[float]  # each shard's predicted time
    unweighted: list[str]  # listed files with no weight, given the largest
    largest: float  # the largest weight in use


def plan(files: list[str], weights: dict[str, float], shards: int) -> Plan:
    files = list(dict.fromkeys(files))
    largest = max(weights.values(), default=1.0)
    weight = {file: weights.get(file, largest) for file in files}
    load = [0.0] * (shards * WORKERS)
    lists: list[list[str]] = [[] for _ in range(shards)]
    for file in sorted(files, key=lambda file: (-weight[file], file)):
        slot = min(range(len(load)), key=lambda s: (load[s], s))
        load[slot] += weight[file]
        lists[slot // WORKERS].append(file)
    lists = [playwright_order(names) for names in lists]
    return Plan(lists, [simulate(names, weight) for names in lists],
                sorted(file for file in files if file not in weights), max(weight.values(), default=largest))


def describe(p: Plan, only: int | None = None) -> str:
    lines = []
    for i, (names, seconds) in enumerate(zip(p.shards, p.seconds, strict=True), 1):
        if only is not None and i != only:
            continue
        lines.append(f"- shard {i}/{len(p.shards)}: {len(names)} file(s), predicted {seconds / 60:.1f} min: "
                     + (", ".join(f"`{file}`" for file in names) or "none"))
    if p.unweighted:
        lines.append(f"- no weight yet, so given the largest ({p.largest:.0f} s): "
                     + ", ".join(f"`{file}`" for file in p.unweighted))
    return "\n".join(lines) + "\n"


# -- what a shard leaves behind ------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    project: str
    file: str
    title: str
    outcome: str  # passed | failed | skipped
    retried: bool  # passed only on a retry (flaky* attempts)
    reruns: bool  # failed, and its retries failed too (rerun* attempts)

    @property
    def identity(self) -> Identity:
        return (self.project, self.file, self.title)


def junit(path: Path) -> tuple[int | None, list[Case]]:
    """A JUnit report's root `tests` counter and its testcases, from names and attributes only."""
    root = ET.parse(path).getroot()
    counter = root.get("tests")
    cases = []
    for suite in root.iter("testsuite"):
        project = suite.get("hostname") or ""
        for case in suite.iter("testcase"):
            tags = {child.tag for child in case}
            outcome = ("skipped" if "skipped" in tags
                       else "failed" if tags & {"failure", "error"} else "passed")
            cases.append(Case(project, case.get("classname") or suite.get("name") or "", case.get("name") or "",
                              outcome, outcome == "passed" and bool(tags & FLAKY), bool(tags & RERUN)))
    return (int(counter) if counter is not None and counter.isdigit() else None), cases


def listing(path: Path) -> tuple[list[Identity], int]:
    """Every test `playwright test --list --reporter=json` names, and how many load errors it had."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    found: list[Identity] = []

    def walk(suite: dict, file: str, titles: list[str]) -> None:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                found.append((test.get("projectName") or "", file, SEP.join([*titles, spec.get("title", "")])))
        for child in suite.get("suites", []):
            walk(child, file, [*titles, child["title"]] if child.get("title") else titles)

    for top in doc.get("suites", []):
        walk(top, top.get("file") or top.get("title", ""), [])
    return found, len(doc.get("errors") or [])


def label(identity: Identity) -> str:
    project, file, title = identity
    return (f"[{project}] " if project else "") + f"{file}{SEP}{title}"


def some(items) -> str:
    shown = sorted(items)
    text = "; ".join(label(item) if isinstance(item, tuple) else str(item) for item in shown[:SHOWN])
    return text + (f"; and {len(shown) - SHOWN} more" if len(shown) > SHOWN else "")


# -- the check -----------------------------------------------------------------------------


@dataclass
class Result:
    problems: list[str] = field(default_factory=list)
    retried: list[Identity] = field(default_factory=list)  # passed only on their retry
    failed_with_reruns: list[Identity] = field(default_factory=list)  # failed on their retry too
    failed: list[Identity] = field(default_factory=list)
    tests: int = 0  # the listing's size
    shards: int = 0
    nothing_listed: bool = False  # server-free.txt lists no file, and no shard left a report


def read_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def check(root: Path, of: int, sha: str, needs: dict, files: list[str]) -> Result:
    """Every way the shards could have missed, doubled or mixed up a test, as a list of problems."""
    result = Result(shards=of)
    problems = result.problems

    # Every shard job succeeded: a red, cancelled or skipped shard fails the check whatever its report says.
    if not needs:
        problems.append("no shard results were handed over (needs is empty)")
    for job, info in sorted(needs.items()):
        outcome = (info or {}).get("result") if isinstance(info, dict) else None
        if outcome != "success":
            problems.append(f"{job} ended {outcome}, not success")

    # Exactly the expected artifacts, each with its files and its own meta.
    expected = [ARTIFACT.format(i=i, n=of) for i in range(1, of + 1)]
    present = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if not files and not present:
        # As the one job did before the shards: nothing listed, nothing to run, and only the
        # shard jobs' results to look at.
        result.nothing_listed = True
        return result
    for extra in sorted(set(present) - set(expected)):
        problems.append(f"unexpected artifact {extra}")
    claims = Counter((read_json(root / d / "meta.json") or {}).get("shard") for d in present)
    for index, count in sorted(claims.items(), key=str):
        if index is not None and count > 1:
            problems.append(f"{count} artifacts say they are shard {index}")

    lists: dict[int, list[str]] = {}
    listings: dict[int, list[Identity]] = {}
    reports: dict[int, tuple[int | None, list[Case]]] = {}
    for i, artifact in enumerate(expected, 1):
        where = root / artifact
        if not where.is_dir():
            problems.append(f"MISSING artifact {artifact}")
            continue
        missing = [f for f in NEEDED if not (where / f).is_file()]
        if missing:
            problems.append(f"MISSING from {artifact}: {', '.join(missing)}")
            continue
        meta = read_json(where / "meta.json")
        if meta is None:
            problems.append(f"{artifact}: meta.json is not a JSON object")
            continue
        if meta.get("shard") != i or meta.get("of") != of:
            problems.append(f"{artifact}: its meta says shard {meta.get('shard')} of {meta.get('of')}")
        if meta.get("sha") != sha:
            problems.append(f"{artifact}: its meta is for commit {meta.get('sha')}, not {sha}")
        try:
            tests, errors = listing(where / "list.json")
        except (ValueError, KeyError, TypeError, AttributeError):
            problems.append(f"{artifact}: list.json is not a Playwright JSON listing")
            continue
        if errors:
            problems.append(f"{artifact}: the listing had {errors} load error(s)")
        try:
            reports[i] = junit(where / "playwright-junit.xml")
        except ET.ParseError:
            problems.append(f"{artifact}: playwright-junit.xml is not XML")
            continue
        lists[i] = listed(where / "test-list.txt")
        listings[i] = tests

    # One listing: every shard listed the same tests, and no test twice.
    expected_tests: list[Identity] = []
    if listings:
        first = min(listings)
        expected_tests = sorted(listings[first])
        for i in sorted(listings):
            if i != first and sorted(listings[i]) != expected_tests:
                differ = Counter(listings[i])
                differ.subtract(Counter(expected_tests))
                problems.append(f"shard {i}'s listing differs from shard {first}'s: "
                                + some(ident for ident, n in differ.items() if n))
        doubled = [ident for ident, n in Counter(expected_tests).items() if n > 1]
        if doubled:
            problems.append(f"ambiguous: the listing names {len(doubled)} test(s) more than once: {some(doubled)}")
    result.tests = len(expected_tests)

    # The file lists: disjoint, and together the files server-free.txt lists.
    owners: dict[str, list[int]] = defaultdict(list)
    for i, names in sorted(lists.items()):
        for file in names:
            owners[file].append(i)
    for file, shards in sorted(owners.items()):
        if len(shards) > 1:
            problems.append(f"{file} is on the lists of shards {', '.join(map(str, shards))}")
    if len(lists) == of:
        for file in sorted(set(files) - set(owners)):
            problems.append(f"{file} is listed in server-free.txt but on no shard's list")
    for file in sorted(set(owners) - set(files)):
        problems.append(f"{file} is on a shard's list but not in server-free.txt")

    # Every test of the listing ran exactly once, and nothing else ran.
    ran: Counter[Identity] = Counter()
    ran_in: dict[Identity, list[int]] = defaultdict(list)
    for i, (counter, cases) in sorted(reports.items()):
        for case in cases:
            ran[case.identity] += 1
            ran_in[case.identity].append(i)
        outside = sorted({case.file for case in cases} - set(lists.get(i, [])))
        if outside:
            problems.append(f"shard {i} ran file(s) not on its list: {some(outside)}")
        if counter != len(cases):
            problems.append(f"shard {i}'s report says tests={counter} but holds {len(cases)} testcase(s)")
    wanted = Counter(expected_tests)
    if listings:
        never = [ident for ident in wanted if not ran[ident]]
        if never:
            problems.append(f"{len(never)} test(s) of the listing never ran: {some(never)}")
        unlisted = [ident for ident in ran if ident not in wanted]
        if unlisted:
            problems.append(f"{len(unlisted)} test(s) ran but are not in the listing: {some(unlisted)}")
    twice = sorted(ident for ident, n in ran.items() if n > 1)
    if twice:
        problems.append(f"ambiguous: {len(twice)} test(s) ran more than once: "
                        + "; ".join(f"{label(ident)} (shards {', '.join(map(str, ran_in[ident]))})"
                                    for ident in twice[:SHOWN])
                        + (f"; and {len(twice) - SHOWN} more" if len(twice) > SHOWN else ""))
    counters = [counter for counter, _ in reports.values()]
    if len(reports) == of and listings and all(c is not None for c in counters):
        total = sum(c for c in counters if c is not None)
        if total != len(expected_tests):
            problems.append(f"the reports count {total} test(s), the listing {len(expected_tests)}")

    every = [case for _, cases in reports.values() for case in cases]
    result.retried = sorted({case.identity for case in every if case.retried})
    result.failed = sorted({case.identity for case in every if case.outcome == "failed"})
    result.failed_with_reruns = sorted({case.identity for case in every if case.outcome == "failed" and case.reruns})
    if result.failed:
        problems.append(f"{len(result.failed)} test(s) failed: {some(result.failed)}")
    return result


def markdown(result: Result) -> str:
    lines = ["### Browser test shards", ""]
    if result.problems:
        lines.append(f"**This check fails ({len(result.problems)} problem(s)).** The {result.shards} shards must all "
                     "succeed and, together, run each test of the listing exactly once; nothing is merged or "
                     "skipped over:")
        lines.append("")
        lines += [f"- {problem}" for problem in result.problems]
    elif result.nothing_listed:
        return "\n".join([*lines, "No spec file is listed in `frontend/e2e/server-free.txt`, so no shard ran a test."]) + "\n"
    else:
        lines.append(f"**All {result.tests} test(s) of the listing ran exactly once**, across {result.shards} shards.")
    lines.append("")
    if result.retried:
        lines.append(f"**{len(result.retried)} test(s) passed only on their retry.** A test that needs a retry is "
                     "broken; it gets fixed, not skipped:")
        lines += [f"- `{label(ident)}`" for ident in result.retried]
    else:
        lines.append("No test needed a retry to pass.")
    if result.failed:
        lines.append("")
        lines.append(f"{len(result.failed)} test(s) failed"
                     + (f", {len(result.failed_with_reruns)} of them on their retry too:" if result.failed_with_reruns
                        else ":"))
        lines += [f"- `{label(ident)}`" + (" (its retry failed too)" if ident in result.failed_with_reruns else "")
                  for ident in result.failed]
    return "\n".join(lines) + "\n"


# -- the rest ----------------------------------------------------------------------------------


def write_summary(text: str) -> None:
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    sys.stdout.write(text)


def version(command: list[str]) -> str | None:
    try:
        done = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (done.stdout.strip() or None) if done.returncode == 0 else None


def meta(shard: int, of: int) -> dict:
    playwright = read_json(PLAYWRIGHT_PACKAGE)
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    return {
        "shard": shard,
        "of": of,
        "run_attempt": int(attempt) if attempt.isdigit() else None,
        "sha": os.environ.get("GITHUB_SHA"),
        "image_os": os.environ.get("ImageOS"),
        "image_version": os.environ.get("ImageVersion"),
        "node": version(["node", "--version"]),
        "playwright": (playwright or {}).get("version"),
    }


def weights_from(reports: list[Path]) -> dict[str, int]:
    """Each file's most seconds over the reports: a testsuite's time, all its tests' attempts."""
    most: dict[str, float] = {}
    for path in reports:
        per_file: dict[str, float] = defaultdict(float)
        for suite in ET.parse(path).getroot().iter("testsuite"):
            per_file[suite.get("name") or ""] += float(suite.get("time") or 0)
        for file, seconds in per_file.items():
            most[file] = max(most.get(file, 0.0), seconds)
    return {file: math.ceil(seconds) for file, seconds in sorted(most.items()) if file}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "split", "meta", "check", "weights"):
        p = sub.add_parser(command)
        p.add_argument("--of", type=int, default=3, help="how many shards")
        p.add_argument("--files", type=Path, default=FILES, help="the list of spec files")
        p.add_argument("--weights", type=Path, default=WEIGHTS, help="seconds per spec file")
        if command in ("split", "meta"):
            p.add_argument("--shard", type=int, required=True)
        if command in ("split", "meta", "weights"):
            p.add_argument("--out", type=Path, required=True)
        if command == "plan":
            p.add_argument("--json", action="store_true")
        if command == "check":
            p.add_argument("dir", type=Path, help="one directory per downloaded shard artifact")
            p.add_argument("--sha", required=True, help="the commit every shard must have tested")
            p.add_argument("--needs", required=True, help="the shard jobs' results: toJSON(needs)")
        if command == "weights":
            p.add_argument("reports", nargs="+", type=Path)
            p.add_argument("--source", action="append", default=[], help="where the reports came from")
    args = parser.parse_args(argv)
    if args.of < 1 or (args.command in ("split", "meta") and not 1 <= args.shard <= args.of):
        parser.error("need 1 <= --shard <= --of")

    if args.command in ("plan", "split"):
        p = plan(listed(args.files), load_weights(args.weights), args.of)
        if args.command == "plan":
            if args.json:
                print(json.dumps({"shards": p.shards, "seconds": p.seconds, "unweighted": p.unweighted,
                                  "largest": p.largest}, indent=1))
            else:
                sys.stdout.write(describe(p))
            return 0
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(f"{file}\n" for file in p.shards[args.shard - 1]), encoding="utf-8")
        write_summary(f"### Browser tests, shard {args.shard}/{args.of}\n\n" + describe(p, args.shard))
        return 0

    if args.command == "meta":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(meta(args.shard, args.of), indent=1) + "\n", encoding="utf-8")
        return 0

    if args.command == "weights":
        doc = {
            "about": "Seconds each server-free spec file took: the most over the reports below. "
                     "scripts/e2e_shards.py balances the CI shards with it; docs/ci-gate.md says how to refresh it.",
            "sources": args.source,
            "seconds": weights_from(args.reports),
        }
        args.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print(f"{len(doc['seconds'])} file(s) -> {args.out}")
        return 0

    try:
        needs = json.loads(args.needs or "{}")
    except ValueError:
        needs = {}
    result = check(args.dir, args.of, args.sha, needs if isinstance(needs, dict) else {}, listed(args.files))
    write_summary(markdown(result))
    return 1 if result.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
