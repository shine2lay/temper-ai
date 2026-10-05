#!/usr/bin/env python3
"""Score a seeded-defect round: what the build's two checks caught (epd_qa_grade).

A corpus is a manifest of cases. Each case is a copy of a past merged change, either with one known
bug planted in its code (a planted case) or with none (a control). Each case went through the checks
under test (epd_qa_case: task_test, the repository's own CI on the commit, and task_verify, the
browser check of the deployed change), and whoever ran them wrote one result file per case. This
script turns those files into a grade: for each check, the planted bugs it caught and missed, its
false alarms on the controls, the cases where the harness itself failed (listed apart, never counted
as misses), and cost and time per case. No model: the same files always give the same grade.

    qa_grade_score.py --manifest M.json --results DIR[,DIR...] --out DIR [--compare DIR]

Manifest (JSON), written before any run:
    {"name": str, "project": str,
     "cases": [{"id": str, "control": bool, "bet": str, "class": str,
                "expected": "test" | "verify" | "either" | "none",
                "criterion": str, "symptom": str,
                "symptom_patterns": [regex, ...], "same_value_match": regex | null}],
     "replaced": [{"id": str, "why": str, "replaced_by": str}]}   (optional)
Patterns are case-insensitive regexes over text with curly quotes, dashes and ellipses made plain.
None of them may match the bet's own criteria, so a match can only come from what the check saw.
A planted bug that turns out to change nothing (an equivalent mutant) is moved to "replaced", with
why, and a new case takes its place; the grade lists every replaced case, so none drops out unseen.
A symptom pattern added after a run (because, on hand reading, the check named the written symptom in
words the patterns missed) is recorded in an optional "pattern_changes" list, [{"case", "added",
"when", "why"}], which the grade lists too: the symptom itself never changes after a run.

Result file DIR/<id>.json, one per case:
    {"case": id, "run_id": str, "run_status": str, "run_error": str | null,
     "run_seconds": float | null, "run_cost_usd": float | null,
     "asked": {"test": bool, "verify": bool},
     "test":   null | {"status": str, "error": str | null, "output": task_test's structured output,
                       "seconds": float | null, "cost_usd": float | null},
     "verify": null | {... the same, output = task_verify's structured output,
                       "why_not_run": str | null}}
With several --results folders, each check of each case comes from the first folder that asked for
it, so one round's task_test and another's task_verify can be graded together.

The rules:
- task_test catches a planted case when its verdict is "fail": at least one new failure against the
  clean commit. "pass" is a miss.
- task_verify catches a planted case when its verdict is "fail" and what it found unmet names the
  symptom: a symptom pattern matches the evidence of an unmet threshold check, an unmet line, or the
  values of a same-value check whose build side differs; or same_value_match matches the name of a
  same-value check whose build side differs. Its "issues" do not count: they are notes beside the
  verdict, and they also describe quirks the clean code has. "pass" is a miss, and so is "fail"
  without the symptom (it failed for another reason, which is listed).
- On a control, any "fail" is a false alarm and "pass" is clean.
- Anything else is a harness fault: verdict "skipped", no verdict, the agent or the run failed, or
  the check was asked for and never ran. Faults are listed apart and left out of every rate.
- Together: a planted case is caught when either check caught it, and missed only when both ran and
  both missed; a control is a false alarm when either check raised one.

--compare DIR sets another round of the same cases beside the first --results folder: each check's
verdict per case, and for task_test each CI check whose result differs. A CI check that passes in one
round and fails in the other on the same commit is flaky.

Writes OUT/grade.json and OUT/grade.md, and prints a JSON summary as its last line.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

CHECKS = ("test", "verify")
NAMES = {"test": "task_test", "verify": "task_verify"}

# Typography a page or a model may use where a pattern has the plain character.
PLAIN = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2026": "...", "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u200b": "",
}


def plain(text) -> str:
    """Lower-case text with plain quotes, dashes and ellipses and single spaces."""
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    for fancy, simple in PLAIN.items():
        s = s.replace(fancy, simple)
    return re.sub(r"\s+", " ", s).strip().lower()


def money(x) -> str:
    return "-" if x is None else f"${float(x):.2f}"


def minutes(x) -> str:
    return "-" if x is None else f"{float(x) / 60:.1f} min"


def rate(caught: int, missed: int):
    n = caught + missed
    return round(caught / n, 3) if n else None


def rate_text(caught: int, missed: int) -> str:
    n = caught + missed
    return "no scored case" if not n else f"{caught} of {n} ({round(100 * caught / n)}%)"


# ---------------------------------------------------------------- loading

def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_round(folder: Path, ids) -> dict:
    got = {}
    for cid in ids:
        path = folder / f"{cid}.json"
        if path.is_file():
            got[cid] = load_json(path)
    return got


def merged(rounds: list[dict], cid: str) -> dict | None:
    """One result for a case: each check from the first round that asked for it."""
    found = [r[cid] for r in rounds if cid in r]
    if not found:
        return None
    out = dict(found[0])
    out["asked"] = dict(found[0].get("asked") or {})
    out["from_runs"] = {}
    used = []
    for check in CHECKS:
        src = next((r for r in found if (r.get("asked") or {}).get(check)), None)
        if src is not None:
            out[check] = src.get(check)
            out["asked"][check] = True
            out["from_runs"][check] = src.get("run_id")
            if not any(src is u for u in used):
                used.append(src)
    if used:
        # A case's checks may come from two runs (one round per check): its cost and time are both.
        for key in ("run_seconds", "run_cost_usd"):
            got = [u.get(key) for u in used if u.get(key) is not None]
            out[key] = round(sum(got), 6) if got else None
    return out


# ---------------------------------------------------------------- one check

def output_of(part) -> dict:
    out = part.get("output") if isinstance(part, dict) else None
    return out if isinstance(out, dict) else {}


def fault_why(part, result: dict, check: str) -> str:
    """Why a check asked for gave no pass or fail."""
    out = output_of(part)
    verdict = out.get("verdict")
    if isinstance(part, dict) and part.get("why_not_run"):
        return str(part["why_not_run"])
    if verdict:
        summary = out.get("summary") or ""
        return f"verdict {verdict}" + (f": {summary}" if summary else "")
    if isinstance(part, dict) and part.get("error"):
        return f"{NAMES[check]} {part.get('status') or 'failed'}: {part['error']}"
    if isinstance(part, dict) and part.get("status"):
        return f"{NAMES[check]} {part['status']} with no verdict"
    run = result.get("run_status") or "unknown"
    err = result.get("run_error")
    return f"{NAMES[check]} never ran (run {run}" + (f": {err})" if err else ")")


def excerpt(text: str, m: re.Match, room: int = 70) -> str:
    a, b = max(0, m.start() - room), min(len(text), m.end() + room)
    return ("..." if a else "") + text[a:b] + ("..." if b < len(text) else "")


def places(out: dict) -> list[tuple[str, str]]:
    """What task_verify found unmet, where a symptom may be named: (where, text)."""
    got = []
    for i, tc in enumerate(out.get("threshold_checks") or []):
        if isinstance(tc, dict) and str(tc.get("status") or "").lower() == "unmet":
            got.append((f"threshold_checks[{i}].evidence", str(tc.get("evidence") or "")))
    for i, line in enumerate(out.get("unmet") or []):
        got.append((f"unmet[{i}]", line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)))
    for i, sv in enumerate(out.get("same_value_checks") or []):
        if isinstance(sv, dict) and str(sv.get("build") or "").lower() == "differ":
            values = "; ".join(f"{v.get('screen', '')}: {v.get('value', '')}" if isinstance(v, dict) else str(v)
                               for v in sv.get("build_values") or [])
            got.append((f"same_value_checks[{i}]", f"{values}; {sv.get('note') or ''}"))
    return got


def symptom_matches(case: dict, out: dict) -> list[dict]:
    found = []
    patterns = [re.compile(p, re.IGNORECASE) for p in case.get("symptom_patterns") or []]
    for where, text in places(out):
        body = plain(text)
        for p in patterns:
            m = p.search(body)
            if m:
                found.append({"where": where, "by": p.pattern, "text": excerpt(body, m)})
    name = case.get("same_value_match")
    if name:
        named = re.compile(name, re.IGNORECASE)
        for i, sv in enumerate(out.get("same_value_checks") or []):
            if isinstance(sv, dict) and str(sv.get("build") or "").lower() == "differ":
                what = plain(sv.get("what") or "")
                if named.search(what):
                    found.append({"where": f"same_value_checks[{i}]", "by": "same_value_match", "text": what})
    return found


def beside(case: dict, out: dict) -> list[str]:
    """The unmet lines no symptom pattern names: what task_verify found besides the planted bug."""
    patterns = [re.compile(p, re.IGNORECASE) for p in case.get("symptom_patterns") or []]
    lines = [u if isinstance(u, str) else json.dumps(u, ensure_ascii=False) for u in out.get("unmet") or []]
    return [u for u in lines if not any(p.search(plain(u)) for p in patterns)]


def score_check(case: dict, result: dict | None, check: str) -> dict:
    """The outcome of one check on one case."""
    control = bool(case.get("control"))
    if result is None:
        return {"outcome": "not_run", "why": "no result for this case"}
    if not (result.get("asked") or {}).get(check):
        return {"outcome": "not_run", "why": f"{NAMES[check]} was not asked for"}
    part = result.get(check)
    out = output_of(part)
    verdict = out.get("verdict")
    row = {"verdict": verdict, "summary": out.get("summary"),
           "seconds": part.get("seconds") if isinstance(part, dict) else None,
           "cost_usd": part.get("cost_usd") if isinstance(part, dict) else None,
           "run_id": (result.get("from_runs") or {}).get(check) or result.get("run_id")}
    if verdict not in ("pass", "fail"):
        return row | {"outcome": "fault", "why": fault_why(part, result, check)}
    if check == "test":
        row["new_failures"] = [f for f in out.get("failures") or [] if isinstance(f, dict)]
        row["preexisting"] = [f for f in out.get("preexisting") or [] if isinstance(f, dict)]
    else:
        row["unmet"] = list(out.get("unmet") or [])
    if control:
        return row | {"outcome": "false_alarm" if verdict == "fail" else "clean"}
    if verdict == "pass":
        return row | {"outcome": "missed"}
    if check == "test":
        return row | {"outcome": "caught"}
    matches = symptom_matches(case, out)
    if matches:
        return row | {"outcome": "caught", "matched": matches, "also_unmet": beside(case, out)}
    return row | {"outcome": "missed", "failed_for_another_reason": True}


def together(case: dict, test: dict, verify: dict) -> str:
    outcomes = (test["outcome"], verify["outcome"])
    if case.get("control"):
        if "false_alarm" in outcomes:
            return "false_alarm"
        ran = [o for o in outcomes if o != "not_run"]
        if ran and all(o == "clean" for o in ran) and len(ran) == 2:
            return "clean"
        return "fault" if "fault" in outcomes else "not_run"
    if "caught" in outcomes:
        return "caught"
    if outcomes == ("missed", "missed"):
        return "missed"
    return "fault" if "fault" in outcomes else "not_run"


# ---------------------------------------------------------------- the grade

def tally(rows: list[dict], key) -> dict:
    planted = [r for r in rows if not r["control"]]
    controls = [r for r in rows if r["control"]]
    got = {"caught": [], "missed": [], "fault": [], "not_run": []}
    for r in planted:
        got.setdefault(key(r), []).append(r["id"])
    ctl = {"false_alarm": [], "clean": [], "fault": [], "not_run": []}
    for r in controls:
        ctl.setdefault(key(r), []).append(r["id"])
    return {"caught": got["caught"], "missed": got["missed"], "faults": got["fault"], "not_run": got["not_run"],
            "catch_rate": rate(len(got["caught"]), len(got["missed"])),
            "false_alarms": ctl["false_alarm"], "clean_controls": ctl["clean"],
            "control_faults": ctl["fault"], "controls_not_run": ctl["not_run"]}


def preexisting_checks(rows: list[dict]) -> list[dict]:
    """CI checks that failed on the clean commit too, so they could not count on any case."""
    seen: dict[str, set] = {}
    for r in rows:
        for f in r["test"].get("preexisting") or []:
            seen.setdefault(str(f.get("check") or "?"), set()).add(r["id"])
    return [{"check": k, "cases": sorted(v)} for k, v in sorted(seen.items())]


def failure_key(f: dict) -> str:
    """Which test a task_test failure is: its check and the failure's first line up to the message."""
    lines = str(f.get("failure") or "").strip().splitlines()
    text = lines[0] if lines else ""
    for sep in (" -- ", " - "):
        if sep in text:
            text = text.split(sep, 1)[0]
            break
    return f"{f.get('check')}: {text[:200]}"


def compare(cases: list[dict], first: dict, other: dict) -> dict:
    rows, agree = [], 0
    for case in cases:
        cid = case["id"]
        a, b = first.get(cid), other.get(cid)
        row = {"id": cid}
        same = True
        for check in CHECKS:
            va = output_of((a or {}).get(check)).get("verdict") if (a or {}).get("asked", {}).get(check) else None
            vb = output_of((b or {}).get(check)).get("verdict") if (b or {}).get("asked", {}).get(check) else None
            row[check] = {"first": va, "other": vb, "agree": va == vb}
            same = same and va == vb
        flips = []
        ca = {str(c.get("check")): c.get("result") for c in output_of((a or {}).get("test")).get("checks") or []
              if isinstance(c, dict)}
        cb = {str(c.get("check")): c.get("result") for c in output_of((b or {}).get("test")).get("checks") or []
              if isinstance(c, dict)}
        for name in sorted(set(ca) & set(cb)):
            if ca[name] != cb[name]:
                flips.append({"check": name, "first": ca[name], "other": cb[name]})
        row["flipped_checks"] = flips
        # A CI check can fail in both rounds while the tests in it differ: a test counted as a new
        # failure in one round and not in the other, on the same commit, flipped too.
        fa, fb = ({failure_key(f) for f in output_of((r or {}).get("test")).get("failures") or []
                   if isinstance(f, dict)} for r in (a, b))
        row["flipped_tests"] = ([{"test": t, "new_failure_in": "first"} for t in sorted(fa - fb)]
                               + [{"test": t, "new_failure_in": "other"} for t in sorted(fb - fa)])
        row["agree"] = same
        agree += same
        rows.append(row)
    flaky: dict[str, list] = {}
    tests: dict[str, list] = {}
    for r in rows:
        for f in r["flipped_checks"]:
            flaky.setdefault(f["check"], []).append(r["id"])
        for t in r["flipped_tests"]:
            tests.setdefault(t["test"], []).append(r["id"])
    return {"cases": rows, "agree": agree, "disagree": len(rows) - agree,
            "flaky_candidates": [{"check": k, "cases": v} for k, v in sorted(flaky.items())],
            "flaky_tests": [{"test": k, "cases": v} for k, v in sorted(tests.items())]}


def grade(manifest: dict, rounds: list[dict], compare_with: dict | None = None) -> dict:
    cases = manifest.get("cases") or []
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("the manifest names a case twice")
    both = {str(r.get("id")) for r in manifest.get("replaced") or [] if isinstance(r, dict)} & set(ids)
    if both:
        raise ValueError(f"the manifest both counts and replaces {', '.join(sorted(both))}")
    rows = []
    for case in cases:
        result = merged(rounds, case["id"])
        test = score_check(case, result, "test")
        verify = score_check(case, result, "verify")
        rows.append({
            "id": case["id"], "bet": case.get("bet"), "class": case.get("class"),
            "control": bool(case.get("control")), "expected": case.get("expected"),
            "criterion": case.get("criterion"), "symptom": case.get("symptom"),
            "test": test, "verify": verify, "together": together(case, test, verify),
            "run_seconds": (result or {}).get("run_seconds"), "run_cost_usd": (result or {}).get("run_cost_usd"),
        })
    faults = [{"case": r["id"], "check": NAMES[c], "why": r[c].get("why")}
              for r in rows for c in CHECKS if r[c]["outcome"] == "fault"]
    by_expected = {}
    for r in rows:
        if r["control"]:
            continue
        e = by_expected.setdefault(r["expected"] or "?", {"cases": [], "test_caught": [], "verify_caught": [],
                                                          "together_caught": []})
        e["cases"].append(r["id"])
        for c in CHECKS:
            if r[c]["outcome"] == "caught":
                e[f"{c}_caught"].append(r["id"])
        if r["together"] == "caught":
            e["together_caught"].append(r["id"])
    surprises = []
    for r in rows:
        if r["control"]:
            continue
        t, v = r["test"]["outcome"], r["verify"]["outcome"]
        if r["expected"] == "verify" and t == "caught":
            surprises.append(f"{r['id']}: task_test caught a bug expected to show only live")
        if r["expected"] in ("either", "test") and t == "missed":
            surprises.append(f"{r['id']}: task_test missed a bug the repository's own tests were expected to catch")
        if r["expected"] in ("either", "verify") and v == "missed":
            why = " (it failed for another reason)" if r["verify"].get("failed_for_another_reason") else ""
            surprises.append(f"{r['id']}: task_verify missed a bug it was expected to see{why}")
    costs = [r["run_cost_usd"] for r in rows if r["run_cost_usd"] is not None]
    secs = [r["run_seconds"] for r in rows if r["run_seconds"] is not None]
    summary = {
        "planted": sum(not r["control"] for r in rows), "controls": sum(r["control"] for r in rows),
        "test": tally(rows, lambda r: r["test"]["outcome"]),
        "verify": tally(rows, lambda r: r["verify"]["outcome"]),
        "together": tally(rows, lambda r: r["together"]),
        "harness_faults": faults,
        "by_expected": by_expected,
        "surprises": surprises,
        "never_counted": preexisting_checks(rows),
        # Planted cases task_verify caught while also failing clauses no symptom pattern names: a sign
        # of what it flags on code the planted bug never touched (the controls measure that directly).
        "verify_found_beside": [{"case": r["id"], "lines": len(r["verify"]["also_unmet"])} for r in rows
                                if r["verify"].get("also_unmet")],
        "replaced": [{"id": str(r.get("id")), "why": str(r.get("why") or ""), "replaced_by": r.get("replaced_by")}
                     for r in manifest.get("replaced") or [] if isinstance(r, dict)],
        "pattern_changes": [{k: str(p.get(k) or "") for k in ("case", "added", "when", "why")}
                            for p in manifest.get("pattern_changes") or [] if isinstance(p, dict)],
        "cost_usd": round(sum(costs), 2) if costs else None,
        "seconds": round(sum(secs), 1) if secs else None,
    }
    out = {"corpus": manifest.get("name"), "project": manifest.get("project"),
           "scored_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "summary": summary, "cases": rows}
    if compare_with is not None:
        out["compare"] = compare(cases, rounds[0] if rounds else {}, compare_with)
    return out


# ---------------------------------------------------------------- the report

def cell(row: dict) -> str:
    o = row["outcome"]
    if o == "caught":
        n = len(row.get("new_failures") or row.get("matched") or [])
        return f"caught ({n} new failure{'s' if n != 1 else ''})" if "new_failures" in row else "caught"
    if o == "missed" and row.get("failed_for_another_reason"):
        return "missed (failed for another reason)"
    return o.replace("_", " ")


def render(g: dict, results: list[str], compare_dir: str | None) -> str:
    s = g["summary"]
    lines = [f"# Seeded-defect grade: {g.get('corpus') or '(unnamed corpus)'}", "",
             f"Project {g.get('project') or '-'}. {s['planted']} planted bugs, {s['controls']} controls. "
             f"Results: {', '.join(results)}. Scored {g['scored_at']}.", "",
             "## Catch rate on the planted bugs", "",
             "| Check | Caught | Missed | Harness faults | Not run | Catch rate |", "|---|---|---|---|---|---|"]
    for key, name in (("test", "task_test"), ("verify", "task_verify"), ("together", "the two together")):
        t = s[key]
        lines.append(f"| {name} | {len(t['caught'])} | {len(t['missed'])} | {len(t['faults'])} | {len(t['not_run'])} "
                     f"| {rate_text(len(t['caught']), len(t['missed']))} |")
    lines += ["", "## False alarms on the controls", "",
              "| Check | False alarms | Clean | Harness faults | Not run |", "|---|---|---|---|---|"]
    for key, name in (("test", "task_test"), ("verify", "task_verify"), ("together", "the two together")):
        t = s[key]
        lines.append(f"| {name} | {', '.join(t['false_alarms']) or 0} | {len(t['clean_controls'])} "
                     f"| {len(t['control_faults'])} | {len(t['controls_not_run'])} |")
    lines += ["", "## Harness faults (left out of every rate)", ""]
    lines += [f"- {f['case']} {f['check']}: {f['why']}" for f in s["harness_faults"]] or ["- none"]
    lines += ["", "## Replaced before scoring (not counted)", ""]
    lines += [f"- {r['id']}, replaced by {r['replaced_by'] or 'nothing'}: {r['why']}" for r in s["replaced"]] \
        or ["- none"]
    lines += ["", "## Symptom patterns added after a run", ""]
    lines += [f"- {p['case']}: added \"{p['added']}\" ({p['when']}): {p['why']}" for p in s["pattern_changes"]] \
        or ["- none"]
    lines += ["", "## By expected catcher", "",
              "| Expected | Cases | task_test caught | task_verify caught | Together caught |", "|---|---|---|---|---|"]
    for exp, e in sorted(s["by_expected"].items()):
        lines.append(f"| {exp} | {', '.join(e['cases'])} | {', '.join(e['test_caught']) or '-'} "
                     f"| {', '.join(e['verify_caught']) or '-'} | {', '.join(e['together_caught']) or '-'} |")
    if s["surprises"]:
        lines += ["", "Against expectation:", ""] + [f"- {x}" for x in s["surprises"]]
    if s["verify_found_beside"]:
        lines += ["", "task_verify also failed clauses no planted symptom names (the lines are in the case details):", ""]
        lines += [f"- {x['case']}: {x['lines']} unmet line{'s' if x['lines'] != 1 else ''}" for x in s["verify_found_beside"]]
    lines += ["", "## Cases", "",
              "| Case | Bet | Class | Expected | task_test | task_verify | Together | Verify cost | Run time |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in g["cases"]:
        lines.append(f"| {r['id']} | {r['bet'] or '-'} | {r['class'] or '-'} | {r['expected'] or '-'} "
                     f"| {cell(r['test'])} | {cell(r['verify'])} | {r['together'].replace('_', ' ')} "
                     f"| {money(r['verify'].get('cost_usd'))} | {minutes(r['run_seconds'])} |")
    lines += ["", f"Total: {money(s['cost_usd'])}, {minutes(s['seconds'])} of run time.", "", "## Case details", ""]
    for r in g["cases"]:
        lines.append(f"### {r['id']} ({r['bet'] or '-'}, {r['class'] or '-'})")
        if not r["control"]:
            lines += [f"Criterion: {r['criterion']}", f"Symptom: {r['symptom']}"]
        for c in CHECKS:
            row = r[c]
            head = f"- {NAMES[c]}: {cell(row)}"
            if row.get("verdict"):
                head += f", verdict {row['verdict']}"
            if row.get("run_id"):
                head += f", run {row['run_id']}"
            lines.append(head)
            if row.get("why"):
                lines.append(f"  - why: {row['why']}")
            for f in row.get("new_failures") or []:
                lines.append(f"  - new failure: {f.get('check')}: {str(f.get('failure') or '')[:300]}")
            for m in row.get("matched") or []:
                lines.append(f"  - symptom in {m['where']} ({m['by']}): {m['text']}")
            if row.get("failed_for_another_reason") or row.get("outcome") == "false_alarm":
                for u in row.get("unmet") or []:
                    lines.append(f"  - unmet: {str(u)[:300]}")
            for u in row.get("also_unmet") or []:
                lines.append(f"  - also unmet, no symptom pattern names it: {str(u)[:300]}")
        lines.append("")
    lines += ["## CI checks that failed on the clean commit too (they could count on no case)", ""]
    lines += [f"- {x['check']}: {', '.join(x['cases'])}" for x in s["never_counted"]] or ["- none"]
    if "compare" in g:
        c = g["compare"]
        lines += ["", f"## Beside {compare_dir}", "",
                  f"{c['agree']} of {c['agree'] + c['disagree']} cases agree on both checks' verdicts.", ""]
        for row in c["cases"]:
            if not row["agree"] or row["flipped_checks"] or row["flipped_tests"]:
                parts = [f"{NAMES[k]} {row[k]['first']} vs {row[k]['other']}" for k in CHECKS if not row[k]["agree"]]
                parts += [f"CI check {f['check']}: {f['first']} vs {f['other']}" for f in row["flipped_checks"]]
                parts += [f"new failure only in the {t['new_failure_in']} round: {t['test']}" for t in row["flipped_tests"]]
                lines.append(f"- {row['id']}: " + "; ".join(parts))
        lines += ["", "Flaky candidates (a CI check whose result differs on the same commit):", ""]
        lines += [f"- {f['check']}: {', '.join(f['cases'])}" for f in c["flaky_candidates"]] or ["- none"]
        lines += ["", "Flaky tests (counted as a new failure in one round and not the other, on the same commit):", ""]
        lines += [f"- {f['test']}: {', '.join(f['cases'])}" for f in c["flaky_tests"]] or ["- none"]
    return "\n".join(lines) + "\n"


def write_open(path: Path, text: str) -> None:
    """Write a file the host user may also replace (runs write as their own user)."""
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="Score a seeded-defect round (epd_qa_grade).")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--results", required=True, help="result folder(s), comma-separated, first wins per check")
    ap.add_argument("--out", required=True)
    ap.add_argument("--compare", default="", help="another round's result folder to set beside the first")
    a = ap.parse_args(argv)
    manifest = load_json(Path(a.manifest))
    ids = [c["id"] for c in manifest.get("cases") or []]
    folders = [x.strip() for x in a.results.split(",") if x.strip()]
    for f in folders + ([a.compare] if a.compare else []):
        if not Path(f).is_dir():
            raise SystemExit(f"no result folder at {f}")
    rounds = [load_round(Path(f), ids) for f in folders]
    other = load_round(Path(a.compare), ids) if a.compare else None
    g = grade(manifest, rounds, other)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out, 0o777)
    except OSError:
        pass
    write_open(out / "grade.json", json.dumps(g, indent=2, ensure_ascii=False) + "\n")
    write_open(out / "grade.md", render(g, folders, a.compare or None))
    s = g["summary"]
    brief = {"grade_json": str(out / "grade.json"), "grade_md": str(out / "grade.md"),
             "planted": s["planted"], "controls": s["controls"],
             "test_catch_rate": s["test"]["catch_rate"], "verify_catch_rate": s["verify"]["catch_rate"],
             "together_catch_rate": s["together"]["catch_rate"],
             "test_caught": s["test"]["caught"], "verify_caught": s["verify"]["caught"],
             "together_caught": s["together"]["caught"],
             "false_alarms": {"test": s["test"]["false_alarms"], "verify": s["verify"]["false_alarms"]},
             "harness_faults": s["harness_faults"], "cost_usd": s["cost_usd"], "seconds": s["seconds"]}
    if other is not None:
        brief["compare"] = {"agree": g["compare"]["agree"], "disagree": g["compare"]["disagree"],
                            "flaky_candidates": g["compare"]["flaky_candidates"],
                            "flaky_tests": g["compare"]["flaky_tests"]}
    print(json.dumps(brief, ensure_ascii=False))
    return g


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError, re.error) as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)
