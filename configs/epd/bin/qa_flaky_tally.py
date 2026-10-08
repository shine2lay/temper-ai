#!/usr/bin/env python3
"""qa_flaky_tally: which tests pass and fail on the same code, from N repetitions of task_test on one
commit (qa_flaky_report's last step). Deterministic; no model; python3 stdlib only.

    python3 /app/configs/epd/bin/qa_flaky_tally.py --out OUT --runs N --commit SHA
        [--repo R] [--subject S] [--parallel P] [--run-id ID] [--work-root DIR]
        [--history-api URL] [--history-workflows epd_loop,...] [--history-max-runs 300]

Reads OUT/runs/run_<i>/ for i in 0..N-1, as qa_flaky_keep wrote them: output.txt (task_test's
answer), step.json (how the step ended), tests.md (task_test's report). Writes OUT/report.json and
OUT/report.md, and prints a short JSON answer as its last stdout line.

Every repetition ran the live task_test with its base set to the commit itself, so task_test
skipped its base rerun and listed every failure under "preexisting", each as {check, failure}, and
gave each check's result in "checks". From that, per check and repetition:

  completed     the check passed, or failed with per-test lines (pytest's FAILED/ERROR lines,
                node's TAP or spec lines, TypeScript and ruff lines). A passing test is inferred:
                its check completed and the test is not among the check's failures.
  no test lines the check failed and only said how it exited (install or launch trouble):
                nothing is known about its tests in that repetition.
  timed out / not run, or a repetition with no answer at all: not completed either.

A failure list task_test cut short (preexisting_total above the items it printed) is read whole from
tests.md; when that cannot be read either, the check counts as not completed in that repetition.
A pytest ERROR for a whole file (no ::name: it did not import) is listed as its own entry, and that
file's tests count as neither passed nor failed in that repetition.

Classes, over the repetitions where the test's check completed:
  flaky   failed in at least one and passed in at least one
  broken  failed in every one
and per check: "infrastructure flake" when it failed without test lines in some repetitions and
completed in others, "never completes" when it completed in none.

History (optional, read-only): for each flaky or broken test, how often the live build's task_test
counted it as a NEW failure (one that sends a build back) and how often as an old one, read from the
runs API (GET only, no key): the runs list, each run's agent attempts, each task_test attempt's log.
An unreachable API makes the history "unavailable" and nothing else.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# A pytest summary line: the node id (path, ::names, then a parameter part that may hold " - "), then
# " - <message>" when pytest printed one.
PYTEST = re.compile(r"^(FAILED|ERROR) (\S+?\.py(?:::[^\s\[]+)*(?:\[.*?\](?= - |$))?)(?: - (.*))?$")
SPEC = re.compile(r"^\u2716 (.+?)(?: \([\d.]+m?s\))?$")
TS = re.compile(r"^(\S[^(\n]*)\((\d+),(\d+)\): error (TS\d+): (.*)$")
RUFF = re.compile(r"^(\S+?\.\w+):(\d+):(\d+): ([A-Z]{1,4}\d{2,4}) (.*)$")
SUFFIX = " (could not be checked on the base)"
# tests.md's failure sections: new ones (none when the base is the commit itself), old ones, and
# those of steps CI lets fail (continue-on-error), each "## <title> (<count>)" then "- check \u2014 line".
SECTION = re.compile(r"^## (Failures this change introduced|Failures that are on .* too \(not this change's\)"
                     r"|Failures in steps CI lets fail) \((\d+)\)$")
ROW = re.compile(r"^- (.+?) \u2014 (.*)$")
# task_test prints at most this many old failures and as many from continue-on-error steps.
LISTED = 20
ERRORISH = re.compile(r"(?i)\b(error|exception|fail(ed|ure)?|fatal|cannot|can't|could not|not found|missing"
                      r"|refused|denied|doesn't exist|no such)\b")
# Box drawing (U+2500-U+257F): the frame some tools draw around a message (Playwright's "\u2551 ... \u2551").
BOX = re.compile(r"[\u2500-\u257f]+")


# ---------------------------------------------------------------- reading one answer


def last_json(text: str) -> dict | None:
    """The last stdout line that is a JSON object with a verdict: task_test's answer."""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and "verdict" in data:
                return data
    return None


def parse_item(line: str) -> dict:
    """One failure line -> {kind, id, error}. kind: test, file (a pytest file that did not import),
    exit (no test lines), timeout, or line (a lint or type line, named by itself)."""
    line = (line or "").strip()
    if line.endswith(SUFFIX):
        line = line[: -len(SUFFIX)]
    if line.startswith("exited "):
        return {"kind": "exit", "id": None, "error": line}
    if line.startswith("did not finish in "):
        return {"kind": "timeout", "id": None, "error": line}
    m = PYTEST.match(line)
    if m:
        node = m.group(2)
        error = (m.group(3) or m.group(1)).strip()
        if "::" not in node:
            return {"kind": "file", "id": node, "error": error}
        return {"kind": "test", "id": node, "error": error}
    m = SPEC.match(line)
    if m:
        return {"kind": "test", "id": m.group(1).strip(), "error": line}
    if TS.match(line) or RUFF.match(line):
        return {"kind": "line", "id": line, "error": line}
    if " -- " in line:
        name, why = line.split(" -- ", 1)
        return {"kind": "test", "id": name.strip(), "error": why.strip()}
    return {"kind": "line", "id": line, "error": line}


def report_rows(path: Path) -> list[dict] | None:
    """Every {check, failure} row of tests.md's failure sections, or None when the report cannot be
    read or a section holds fewer rows than its title counts."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    rows: list[dict] = []
    sections: list[tuple[int, int]] = []  # (rows wanted, rows found)
    inside = soft = False
    for line in text.splitlines():
        m = SECTION.match(line)
        if m:
            inside, soft = True, m.group(1).startswith("Failures in steps CI lets fail")
            sections.append((int(m.group(2)), 0))
            continue
        if line.startswith("## "):
            inside = False
            continue
        if inside:
            r = ROW.match(line)
            if r:
                rows.append({"check": r.group(1), "failure": r.group(2), "soft": soft})
                want, found = sections[-1]
                sections[-1] = (want, found + 1)
    if not text.startswith("# Tests: ") or any(found != want for want, found in sections):
        return None
    return rows


def better_line(log: Path, said: str) -> str:
    """task_test names a failure without test lines by its log's last line; when that line is box
    drawing (a framed message), the log's last line that reads like an error says more."""
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return said
    for line in reversed(lines):
        line = line.strip()
        if ERRORISH.search(line) and not line.startswith(("File ", "^")):
            head = said.split(": ", 1)[0] if said.startswith("exited ") else "exited"
            return f"{head}: {line[:300]}"
    return said


def unframed(said: str) -> str:
    """The line without the frame drawn around it, so the report shows only the words."""
    return re.sub(r"\s+", " ", BOX.sub(" ", said)).strip()


def read_repetition(folder: Path) -> dict:
    """One repetition -> {answered, why, checks: {check: {state, items}}}.
    state: completed, no test lines, timed out, not run, cut short."""
    rep = {"answered": False, "why": None, "checks": {}}
    try:
        text = (folder / "output.txt").read_text(encoding="utf-8")
    except OSError:
        text = ""
    answer = last_json(text)
    if answer is None:
        try:
            step = json.loads((folder / "step.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            step = {}
        why = step.get("error") or step.get("status") or "no answer"
        rep["why"] = f"task_test gave no answer ({str(why)[:200]})"
        return rep
    checks = answer.get("checks") or []
    if not checks:
        rep["why"] = f"task_test could not run: {str(answer.get('summary'))[:200]}"
        return rep
    rep["answered"] = True
    old = list(answer.get("preexisting") or [])
    new = list(answer.get("failures") or [])
    soft = [dict(x, soft=True) for x in answer.get("nonblocking") or []]
    items = old + new + soft
    # A list task_test cut short: its total says so, or (continue-on-error steps, no total) it is full.
    cut = (int(answer.get("preexisting_total") or 0) > len(old)
           or int(answer.get("failures_total") or 0) > len(new)
           or len(soft) >= LISTED)
    if cut:
        whole = report_rows(folder / "tests.md")
        if whole is not None:
            items, cut = whole, False
    by_check: dict[str, list[dict]] = {}
    for item in items:
        by_check.setdefault(str(item.get("check")), []).append(
            parse_item(str(item.get("failure"))) | {"soft": bool(item.get("soft"))})
    for c in checks:
        name = str(c.get("check"))
        result = c.get("result")
        mine = by_check.get(name, [])
        if result == "passed":
            state = "completed"
        elif result == "timed out":
            state = "timed out"
        elif result == "not run":
            state = "not run"
        elif cut:
            state = "cut short"
        elif mine and all(x["kind"] in ("exit", "timeout") for x in mine):
            state = "no test lines"
        elif mine:
            state = "completed"
        else:
            # Failed, but none of its lines reached the answer: nothing known.
            state = "cut short"
        said = next((x["error"] for x in mine if x["kind"] in ("exit", "timeout")), None)
        if state == "no test lines" and said and len(re.findall(r"[A-Za-z]", said.split(": ", 1)[-1])) < 3:
            said = better_line(folder / "logs" / Path(str(c.get("log") or "")).name, said)
        if said:
            said = unframed(said)
        rep["checks"][name] = {"state": state,
                               "items": [x for x in mine if x["kind"] in ("test", "file", "line")],
                               "said": said, "why": c.get("why")}
    return rep


# ---------------------------------------------------------------- the tally


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    z, p = 1.96, k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3))


def file_of(test_id: str) -> str:
    return test_id.split("::", 1)[0]


def tally(reps: list[dict]) -> dict:
    check_names: list[str] = []
    for rep in reps:
        for name in rep["checks"]:
            if name not in check_names:
                check_names.append(name)

    checks, tests = [], {}
    for name in check_names:
        states = {}
        for i, rep in enumerate(reps):
            states[i] = rep["checks"].get(name, {"state": "absent"})["state"] if rep["answered"] else "no answer"
        completed = [i for i, s in states.items() if s == "completed"]
        count = {s: sum(1 for v in states.values() if v == s)
                 for s in ("completed", "no test lines", "timed out", "not run", "cut short", "no answer", "absent")}
        passed = sum(1 for i in completed if not reps[i]["checks"][name]["items"])
        said = next((reps[i]["checks"][name]["said"] for i, s in states.items() if s == "no test lines"), None)
        why = next((reps[i]["checks"][name].get("why") for i, s in states.items() if s == "not run"), None)
        if not completed:
            klass = "never completes"
        elif count["no test lines"] or count["timed out"]:
            klass = "infrastructure flake"
        elif passed == len(completed):
            klass = "stable"
        else:
            klass = "has failing tests"
        checks.append({"check": name, "class": klass, "repetitions": len(reps), "passed": passed,
                       "completed": len(completed), **{k.replace(" ", "_"): v for k, v in count.items()
                                                       if k not in ("completed",)},
                       "said": said, "why_not_run": why,
                       "no_test_lines_in": [i for i, s in states.items() if s == "no test lines"],
                       "timed_out_in": [i for i, s in states.items() if s == "timed out"]})

        # Every test that failed at least once, in a repetition where its check completed.
        for i in completed:
            for item in reps[i]["checks"][name]["items"]:
                key = (name, item["id"])
                t = tests.setdefault(key, {"check": name, "id": item["id"], "kind": item["kind"],
                                           "failed_in": [], "errors": {}, "nonblocking": False})
                # Failed in a step CI lets fail (continue-on-error): it never sends a build back.
                t["nonblocking"] = t["nonblocking"] or item["soft"]
                if i not in t["failed_in"]:
                    t["failed_in"].append(i)
                    t["errors"].setdefault(item["error"], i)
        for key, t in tests.items():
            if key[0] != name:
                continue
            passed_in, unknown_in = [], []
            for i in completed:
                if i in t["failed_in"]:
                    continue
                broken_files = {x["id"] for x in reps[i]["checks"][name]["items"] if x["kind"] == "file"}
                if t["kind"] == "test" and file_of(t["id"]) in broken_files:
                    unknown_in.append(i)
                else:
                    passed_in.append(i)
            t["passed_in"] = passed_in
            t["unknown_in"] = unknown_in

    out = []
    for t in tests.values():
        failures, passes = len(t["failed_in"]), len(t["passed_in"])
        known = failures + passes
        lo, hi = wilson(failures, known)
        first_rep = min(t["failed_in"])
        first_error = next(e for e, i in t["errors"].items() if i == first_rep)
        out.append({"check": t["check"], "id": t["id"], "kind": t["kind"],
                    "class": "flaky" if passes else "broken", "nonblocking": t["nonblocking"],
                    "completed": known, "failures": failures, "passes": passes,
                    "rate": round(failures / known, 3) if known else None,
                    "rate_95": [lo, hi],
                    "first_error": first_error[:400],
                    "other_errors": [e[:400] for e in t["errors"] if e != first_error][:3],
                    "failed_in": sorted(t["failed_in"]), "unknown_in": sorted(t["unknown_in"])})
    order = {"flaky": 0, "broken": 1}
    out.sort(key=lambda t: (order[t["class"]], -(t["rate"] or 0), t["check"], t["id"]))
    return {"checks": checks, "tests": out}


# ---------------------------------------------------------------- history (read-only)


def _get(api: str, path: str, timeout: float = 30) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(api.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def history(api: str, workflows: list[str], wanted: list[dict], max_runs: int) -> dict:
    """For each wanted (check, id): times a live task_test counted it new, and old."""
    counts = {(t["check"], t["id"]): {"as_new": 0, "as_old": 0, "new_in_runs": []} for t in wanted}
    seen_runs = steps_read = steps_without_answer = runs_unreadable = 0
    try:
        runs, offset = [], 0
        while True:
            page = _get(api, f"/api/workflows?limit=500&offset={offset}")
            batch = page.get("runs") or []
            runs += [r for r in batch if r.get("workflow_name") in workflows]
            offset += len(batch)
            if not batch or offset >= int(page.get("total") or 0):
                break
        runs = runs[:max_runs]
        for run in runs:
            seen_runs += 1
            rid = run.get("id")
            try:
                agents = _get(api, f"/api/workflows/{urllib.parse.quote(str(rid))}/agents").get("agents") or []
            except Exception:  # noqa: BLE001 - one run that cannot be read is counted, not fatal
                runs_unreadable += 1
                continue
            for a in agents:
                if a.get("agent_name") != "task_test":
                    continue
                steps_read += 1
                try:
                    log = _get(api, f"/api/runs/{urllib.parse.quote(str(rid))}/agents/"
                                    f"{urllib.parse.quote(str(a.get('id')))}/log?max_bytes=4000000")
                except Exception:  # noqa: BLE001 - a step without a saved log is counted, not fatal
                    steps_without_answer += 1
                    continue
                text = "".join(e.get("text") or "" for row in log.get("rows") or []
                               for e in row.get("entries") or [] if e.get("stream") == "stdout")
                answer = last_json(text)
                if answer is None:
                    steps_without_answer += 1
                    continue
                for field, where in (("failures", "as_new"), ("preexisting", "as_old")):
                    for item in answer.get(field) or []:
                        parsed = parse_item(str(item.get("failure")))
                        key = (str(item.get("check")), parsed["id"])
                        if key in counts:
                            counts[key][where] += 1
                            if where == "as_new" and rid not in counts[key]["new_in_runs"]:
                                counts[key]["new_in_runs"].append(rid)
    except Exception as e:  # noqa: BLE001 - the history is extra; the report stands without it
        return {"status": "unavailable", "why": f"{type(e).__name__}: {str(e)[:200]}",
                "runs_read": seen_runs, "test_steps_read": steps_read}
    return {"status": "read", "api": api, "workflows": workflows, "runs_read": seen_runs,
            "runs_unreadable": runs_unreadable,
            "test_steps_read": steps_read, "test_steps_without_saved_answer": steps_without_answer,
            "tests": [{"check": k[0], "id": k[1], **v} for k, v in counts.items()]}


# ---------------------------------------------------------------- the report


def pct(x: float | None) -> str:
    return "-" if x is None else f"{round(100 * x)}%"


def markdown(r: dict) -> str:
    md = [f"# Flaky tests: {r['commit'][:12]} ({r['subject']})", "",
          f"{r['runs']} repetitions of the repository's CI (the live task_test, unchanged) on one commit, "
          f"{r['parallel']} at a time; run {r['run_id'] or '(none)'}. {r['answered']} repetitions answered.", "",
          "## Summary", "", r["summary"], ""]
    for klass, title in (("flaky", "Flaky tests (failed and passed on the same code)"),
                         ("broken", "Broken tests (failed in every repetition that ran them)")):
        rows = [t for t in r["tests"] if t["class"] == klass]
        md += [f"## {title} ({len(rows)})", ""]
        if rows:
            md += ["| check | test | failed | rate (95%) | first error | failed in |", "|---|---|---|---|---|---|"]
            for t in rows:
                name = t["id"] + (" (in a step CI lets fail)" if t["nonblocking"] else "")
                md.append(f"| {t['check']} | {name} | {t['failures']} of {t['completed']} | {pct(t['rate'])} "
                          f"({pct(t['rate_95'][0])}-{pct(t['rate_95'][1])}) | {t['first_error'].replace('|', '/')} "
                          f"| {', '.join(map(str, t['failed_in']))} |")
        md.append("")
    odd = [c for c in r["checks"] if c["class"] in ("infrastructure flake", "never completes")]
    md += [f"## Checks that did not always run their tests ({len(odd)})", ""]
    if odd:
        md += ["| check | class | completed | no test lines | timed out | not run | what it said |", "|---|---|---|---|---|---|---|"]
        for c in odd:
            said = (c["said"] or c["why_not_run"] or "").replace("|", "/")[:200]
            md.append(f"| {c['check']} | {c['class']} | {c['completed']} of {c['repetitions']} | {c['no_test_lines']} "
                      f"| {c['timed_out']} | {c['not_run']} | {said} |")
    md += ["", "## Every check", "", "| check | class | completed | passed clean |", "|---|---|---|---|"]
    md += [f"| {c['check']} | {c['class']} | {c['completed']} of {c['repetitions']} | {c['passed']} |" for c in r["checks"]]
    h = r.get("history") or {}
    md += ["", "## In live builds", ""]
    if h.get("status") == "read":
        md.append(f"Read {h['test_steps_read']} task_test steps in {h['runs_read']} runs of "
                  f"{', '.join(h['workflows'])} ({h['test_steps_without_saved_answer']} without a saved answer"
                  + (f"; {h['runs_unreadable']} runs could not be read" if h.get("runs_unreadable") else "")
                  + ").")
        md += ["", "| check | test | counted new (sent a build back) | counted old |", "|---|---|---|---|"]
        md += [f"| {t['check']} | {t['id']} | {t['as_new']}{' (' + ', '.join(t['new_in_runs'][:5]) + ')' if t['new_in_runs'] else ''} "
               f"| {t['as_old']} |" for t in h["tests"]]
    else:
        md.append(f"Not read: {h.get('why') or 'off'}.")
    if r["no_answer"]:
        md += ["", "## Repetitions with no answer", ""] + [f"- {x['repetition']}: {x['why']}" for x in r["no_answer"]]
    md += ["", "## How to read this", "",
           "A test is flaky when it failed in at least one repetition and passed in at least one other in which its "
           "check completed; broken when it failed in every one. Passes are inferred: the check completed and the "
           "test is not among its failures. A check that failed without any test lines is counted apart. A rate "
           "from 20 repetitions is rough: the 95% range says how rough. Not finding a flake is not proof there is "
           "none: a test failing 5% of the time is missed by 20 repetitions about a third of the time."]
    md += [f"- {c}" for c in r["caveats"]]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--repo", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--run-id", default="")
    ap.add_argument("--work-root", default="")
    ap.add_argument("--history-api", default="")
    ap.add_argument("--history-workflows", default="epd_loop")
    ap.add_argument("--history-max-runs", type=int, default=300)
    a = ap.parse_args(argv)

    out = Path(a.out)
    reps = [read_repetition(out / "runs" / f"run_{i}") for i in range(a.runs)]
    t = tally(reps)
    flaky = [x for x in t["tests"] if x["class"] == "flaky"]
    broken = [x for x in t["tests"] if x["class"] == "broken"]
    infra = [c for c in t["checks"] if c["class"] == "infrastructure flake"]
    never = [c for c in t["checks"] if c["class"] == "never completes"]
    answered = sum(1 for r in reps if r["answered"])
    caveats = []
    if a.parallel > 1:
        caveats.append(f"{a.parallel} repetitions ran at a time in one run box: they share its network, /tmp and "
                       "caches, so a check that uses a fixed port or file can trip over another; re-check an "
                       "infrastructure flake with parallel 1 before blaming the repository. Load also makes "
                       "timing races fail more often than on an idle machine.")
    hist = {"status": "off", "why": "history was off for this run"}
    if a.history_api and not (flaky or broken):
        hist = {"status": "skipped", "why": "no flaky or broken test to look up"}
    elif a.history_api:
        hist = history(a.history_api, [w for w in a.history_workflows.split(",") if w],
                       flaky + broken, a.history_max_runs)
        if hist.get("status") == "read":
            by = {(x["check"], x["id"]): x for x in hist["tests"]}
            for x in flaky + broken:
                h = by.get((x["check"], x["id"]))
                x["live"] = {"as_new": h["as_new"], "as_old": h["as_old"], "new_in_runs": h["new_in_runs"]} if h else None

    def name(x: dict) -> str:
        return f"{x['id']} ({x['failures']} of {x['completed']})"

    summary = (f"{len(flaky)} flaky, {len(broken)} broken"
               + (f", {len(infra)} check(s) with infrastructure flakes" if infra else "")
               + (f", {len(never)} check(s) that never completed" if never else "")
               + f" in {answered} of {a.runs} repetitions on {a.commit[:12]}"
               + (": flaky " + "; ".join(name(x) for x in flaky[:5]) if flaky else ""))
    report = {"status": "reported", "summary": summary, "repo": a.repo, "commit": a.commit,
              "subject": a.subject, "run_id": a.run_id or None, "runs": a.runs, "parallel": a.parallel,
              "answered": answered,
              "no_answer": [{"repetition": i, "why": r["why"]} for i, r in enumerate(reps) if not r["answered"]],
              "checks": t["checks"], "tests": t["tests"], "history": hist, "caveats": caveats}
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    for p in (out / "report.json", out / "report.md"):
        try:
            p.chmod(0o666)
        except OSError:
            pass

    removed = False
    root = Path(a.work_root) if a.work_root else None
    if root and root.name.startswith("qa-flaky.") and (root / "base").is_dir():
        shutil.rmtree(root, ignore_errors=True)
        removed = not root.exists()

    print(f"{summary}; report in {out / 'report.md'}")

    def brief(xs: list[dict]) -> list[dict]:
        return [{k: x[k] for k in ("check", "id", "failures", "completed", "rate", "first_error")}
                for x in xs][:20]

    print(json.dumps({"status": "reported", "summary": summary, "answered": answered, "runs": a.runs,
                      "flaky": brief(flaky), "broken": brief(broken),
                      "infrastructure": [{"check": c["check"], "completed": c["completed"],
                                          "no_test_lines": c["no_test_lines"], "timed_out": c["timed_out"],
                                          "said": c["said"]} for c in infra],
                      "never_completes": [c["check"] for c in never],
                      "history": hist.get("status"),
                      "report": str(out / "report.md"), "report_json": str(out / "report.json"),
                      "work_removed": removed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
