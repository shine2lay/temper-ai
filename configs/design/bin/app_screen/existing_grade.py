"""Grade one stage-2 (existing) run against a case's answer key (host command grade-existing). Model-free.

A case folder holds requirements.json (stage 1's output the run was given) and expected.json, written before
any run. expected.json's bars say which parts apply:

    {"case", "product", "written", "captures": N,
     "bars": {"capture_failed": 0, "unsupported": 0,
              "measures_exact": true, "key_recall_min": 15, "journeys_min": 5,     (a real product)
              "recall_min": 6,                                                    (planted defects)
              "severe_max": 0, "severe_from": 2, "low_need_measure": true},       (a clean twin)
     "measured": "measured.json",
     "problems": {"P1": {"what", "groups": [[term, ...], ...]}},
     "journeys": [{"id", "name", "screens": [...], "terms": [...], "problems": ["P1", ...]}],
     "planted": [{"id", "kind", "what", "screens": [capture ids], "measures": [...], "terms": [...]}]}

capture      02-existing/capture.json lists no failed capture and audit.json holds every capture (N).
unsupported  the final journeys.json, turned back into its draft, checked again with stage 2's own checks
             (existing_check): every problem it still finds counts. A final output that is missing or breaks
             its contract fails the run.
measures     (measured.json) every listed capture's layout width, each exact measure and the 320 total
             equal the audit's.
key          each key journey is matched to one draft journey, one to one, best total: the draft journey names
             one of its screens and its name or goal holds one of its terms. A key problem entry is met when the
             matched journey's problems together (claims and evidence lines, case and dashes folded) hold a
             term of every group (intake's H1 rule: one problem or several).
recall       a planted defect is found when a problem cites (refs) a capture of one of its screens and either
             cites one of its measures with a value on the problem side, or has its kind and states one of its
             terms. Problems that find no defect are reported as other findings.
clean        problems at severity_from or more (bar severe_max); a lower one must cite a measure on its
             problem side.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import contracts, existing, existing_check, existing_measures
from .workspace import Workspace


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _problem_text(p: dict) -> str:
    return existing_check.fold(" ".join([str(p.get("claim", ""))] + [str(e) for e in p.get("evidence") or []]))


def _best_match(fits: list[list[int]], scores: list[dict[int, int]]) -> list[int | None]:
    """One draft journey per key journey, one to one: most journeys matched, then most entries met."""
    best: tuple[int, int, list[int | None]] = (-1, -1, [None] * len(fits))

    def walk(i: int, used: set[int], picked: list[int | None], matched: int, met: int) -> None:
        nonlocal best
        if i == len(fits):
            if (matched, met) > best[:2]:
                best = (matched, met, list(picked))
            return
        for j in fits[i]:
            if j not in used:
                walk(i + 1, used | {j}, picked + [j], matched + 1, met + scores[i][j])
        walk(i + 1, used, picked + [None], matched, met)

    walk(0, set(), [], 0, 0)
    return best[2]


def _key(expected: dict, journeys: list[dict], misses: list[str]) -> dict:
    groups = expected.get("problems", {})
    key_journeys = expected.get("journeys", [])
    texts = [_problem_text({"claim": " ".join(_problem_text(p) for p in j.get("problems") or [])})
             for j in journeys]

    def met(key_journey: dict, j: int) -> list[str]:
        return [pid for pid in key_journey["problems"]
                if all(any(existing_check.fold(t) in texts[j] for t in g) for g in groups[pid]["groups"])]

    fits, scores = [], []
    for k in key_journeys:
        terms = [existing_check.fold(t) for t in k["terms"]]
        fit = [j for j, d in enumerate(journeys)
               if set(k["screens"]) & set(d.get("screens") or [])
               and any(t in existing_check.fold(f"{d.get('name', '')} {d.get('goal', '')}") for t in terms)]
        fits.append(fit)
        scores.append({j: len(met(k, j)) for j in fit})
    picked = _best_match(fits, scores)
    entries_met, entries = 0, 0
    detail = {}
    for k, j in zip(key_journeys, picked, strict=True):
        entries += len(k["problems"])
        if j is None:
            misses.append(f"journey {k['id']} ({k['name']}) matched by no draft journey")
            detail[k["id"]] = None
            continue
        got = met(k, j)
        entries_met += len(got)
        detail[k["id"]] = {"journey": journeys[j].get("id"), "met": got}
        for pid in k["problems"]:
            if pid not in got:
                misses.append(f"key {k['id']}/{pid} not met in {journeys[j].get('id')}: {groups[pid]['what']}")
    matched = sum(1 for j in picked if j is not None)
    return {"key": f"{entries_met}/{entries}", "key_met": entries_met, "journeys_matched": f"{matched}/{len(key_journeys)}",
            "journeys_matched_n": matched, "key_detail": detail}


def _finds(defect: dict, p: dict, captures: dict) -> bool:
    refs = [r for r in p.get("refs") or [] if isinstance(r, dict) and r.get("capture") in defect["screens"]]
    if not refs:
        return False
    for r in refs:
        cap = captures.get(r["capture"])
        key = r.get("measure")
        if cap and key in defect["measures"] and key in cap["measures"]:
            if existing_measures.shows_problem(key, cap["measures"][key], cap):
                return True
    text = _problem_text(p)
    return p.get("kind") == defect["kind"] and any(existing_check.fold(t) in text for t in defect["terms"])


def _measures_exact(case_dir: Path, expected: dict, audit: dict, misses: list[str]) -> dict:
    key = _read(case_dir / expected["measured"])
    if key is None:
        raise ValueError(f"{case_dir}: needs {expected['measured']}")
    caps = {s["id"]: s for s in audit["screens"]}
    wrong = []
    for cid, width in key["layout_width_px"].items():
        got = caps.get(cid, {}).get("measures", {}).get("layout_width_px")
        if got != width:
            wrong.append(f"{cid} layout_width_px {got} (key {width})")
    for e in key["exact"]:
        got = caps.get(e["capture"], {}).get("measures", {}).get(e["measure"])
        if got != e["value"]:
            wrong.append(f"{e['capture']} {e['measure']} {got} (key {e['value']})")
    total = (audit.get("totals") or {}).get("layout_width_px@320")
    want = key["wider_at_320"]
    if not total or total["value"] != want["value"] or total["of"] != want["of"]:
        wrong.append(f"layout_width_px@320 {total} (key {want['value']} of {want['of']})")
    misses += [f"measure: {w}" for w in wrong]
    return {"measures_exact": not wrong, "measures_checked": len(key["layout_width_px"]) + len(key["exact"]) + 1,
            "measures_wrong": len(wrong)}


def grade(case_dir: Path | str, workspace: Path | str) -> dict:
    case_dir, ws = Path(case_dir), Workspace(workspace)
    expected = _read(case_dir / "expected.json")
    case_requirements = _read(case_dir / "requirements.json")
    if expected is None or case_requirements is None:
        raise ValueError(f"{case_dir}: needs requirements.json and expected.json")
    bars = expected["bars"]
    folder = ws.folder("existing")
    misses: list[str] = []
    if _read(ws.folder("intake") / "requirements.json") != case_requirements:
        misses.append("the run's 01-request/requirements.json is not the case's requirements.json")
    record = _read(folder / "capture.json") or {}
    audit = _read(folder / "audit.json") or {"screens": []}
    failed = record.get("failed", {"capture.json": "missing"})
    if len(failed) > bars.get("capture_failed", 0):
        misses.append(f"capture failed {len(failed)}: {', '.join(list(failed)[:6])}")
    if len(audit["screens"]) != expected["captures"]:
        misses.append(f"audit holds {len(audit['screens'])} captures (key {expected['captures']})")
    measures: dict = {"captures": len(audit["screens"]), "capture_failed": len(failed)}
    try:
        contracts.validate("existing", ws)
        final_ok = (folder / "check-final.json").is_file()
    except contracts.ContractError as exc:
        final_ok = False
        misses.append(f"final output: {str(exc)[:300]}")
    journeys_file = _read(folder / "journeys.json")
    if not final_ok or journeys_file is None:
        misses.append("existing did not write a clean final output")
        return {"case": expected.get("case", case_dir.name), "pass": False, "measures": measures, "misses": misses}
    journeys = journeys_file["journeys"]
    found = existing_check.check_draft(existing.context(ws), existing_check.draft_from_journeys(journeys_file))
    unsupported = len(found["problems"])
    misses += [f"unsupported: {p['check']} {p['where']}: {p['problem']}" for p in found["problems"][:12]]
    if unsupported > bars.get("unsupported", 0):
        misses.append(f"unsupported {unsupported} (bar {bars.get('unsupported', 0)})")
    problems = list({p["id"]: p for j in journeys for p in j["problems"]}.values())
    measures.update({"journeys": len(journeys), "problems": len(problems), "unsupported": unsupported,
                     "severity": {str(s): sum(1 for p in problems if p.get("severity") == s) for s in range(5)},
                     "revised": (folder / "draft-first.json").is_file()})
    if bars.get("measures_exact"):
        measures.update(_measures_exact(case_dir, expected, audit, misses))
    if "key_recall_min" in bars:
        measures.update(_key(expected, journeys, misses))
        if measures["key_met"] < bars["key_recall_min"]:
            misses.append(f"key recall {measures['key']} (bar {bars['key_recall_min']})")
        if measures["journeys_matched_n"] < bars["journeys_min"]:
            misses.append(f"journeys matched {measures['journeys_matched']} (bar {bars['journeys_min']})")
    captures = {s["id"]: s for s in audit["screens"]}
    if "recall_min" in bars:
        planted = expected["planted"]
        hits = {d["id"]: [p["id"] for p in problems if _finds(d, p, captures)] for d in planted}
        recalled = [d for d, ps in hits.items() if ps]
        other = [p["id"] for p in problems if not any(p["id"] in ps for ps in hits.values())]
        measures.update({"recall": f"{len(recalled)}/{len(planted)}", "planted_found": hits, "other_findings": other})
        misses += [f"planted {d['id']} ({d['kind']}) not found: {d['what']}" for d in planted if not hits[d["id"]]]
        if len(recalled) < bars["recall_min"]:
            misses.append(f"recall {len(recalled)}/{len(planted)} (bar {bars['recall_min']})")
    if "severe_max" in bars:
        line = bars.get("severe_from", 2)
        severe = [p for p in problems if (p.get("severity") or 0) >= line]
        unmeasured = [p for p in problems if (p.get("severity") or 0) < line and not any(
            isinstance(r, dict) and r.get("capture") in captures and r.get("measure") in captures[r["capture"]]["measures"]
            and existing_measures.shows_problem(r["measure"], captures[r["capture"]]["measures"][r["measure"]],
                                                captures[r["capture"]])
            for r in p.get("refs") or [])] if bars.get("low_need_measure") else []
        measures.update({"severe": len(severe), "low_unmeasured": len(unmeasured)})
        misses += [f"clean twin: {p['id']} severity {p.get('severity')}: {p['claim'][:120]}" for p in severe]
        misses += [f"clean twin: {p['id']} severity {p.get('severity')} cites no measure on its problem side: "
                   f"{p['claim'][:120]}" for p in unmeasured]
        if len(severe) > bars["severe_max"]:
            misses.append(f"severe {len(severe)} (bar {bars['severe_max']})")
    first = _read(folder / "draft-first.json")
    if first is not None:
        measures["first_draft_problems"] = len(existing_check.check_draft(existing.context(ws), first)["problems"])
    return {"case": expected.get("case", case_dir.name), "pass": not misses, "measures": measures, "misses": misses}
