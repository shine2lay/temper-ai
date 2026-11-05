"""Stage 2's measured checks: the model's journeys and problems held to the captures they cite. Model-free.

check_draft(context, draft) returns {"verdict": "ok"|"retry", "counts": {...}, "problems": [...]}, each
problem {"check", "where", "problem"}. The context is what the host's capture wrote: audit.json (every
capture's measures, per-width totals), texts.json (every capture's visible text) and app.json (the screens),
plus the stage-1 requirement ids. The checks:

    schema        the draft matches its contract (contracts.SCHEMAS["existing_draft"])
    ids           journey, problem and keep ids unique; every problem a journey names exists; requirement ids
                  exist in 01-request/requirements.json
    screens       every screen a journey names is one of the app's screens
    refs          every ref names a capture that exists, and a measure that capture has, or a total that exists
    values        a measure ref's value is the capture's value exactly (a list measure: the list, one of its
                  items, or its length); a total ref's value (and of) is the total's
    texts         a text ref's text is visible in that capture (texts.json, case and spacing aside)
    unsupported   a problem cites no capture, or none of its refs supports it: a measured kind needs one of its
                  kind's measures on the problem side (existing_measures.PROBLEM_WHEN); any other kind needs
                  visible text, a context measure, or a ruled measure on the problem side
    contradicted  a problem's only measures of its kind (or, for another kind, its only evidence) sit on the
                  OK side; a keep item cites a measure on the problem side
    invented      a claim or keep item states a number that is in none of its cited refs (values, texts,
                  totals, the capture's size), the app's screen sizes, or the fixed thresholds
    orphan        a problem no journey names

outputs(context, draft) turns a clean draft into journeys.json (contract "journeys"): each journey with its
problems written out, every ref also rendered as an evidence line (refs and keep_refs keep the refs themselves,
so draft_from_journeys() can hold the final output to the same checks).
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import contracts, existing_measures
from .intake_check import NUMBER

CHECKS = ("schema", "ids", "screens", "refs", "values", "texts", "unsupported", "contradicted", "invented", "orphan")
FAMILIES = {
    "layout-width": {"layout_width_px", "wider_than_screen_px", "side_scrolling_boxes", "side_scroll_content_px"},
    "text-size": {"text_runs_under_12px", "body_text_runs_under_16px", "smallest_text_px", "distinct_text_sizes",
                  "text_runs_under_16px"},
    "tap-target": {"targets_under_24px"},
    "truncation": {"truncated_count", "truncated_text"},
    "buried": {"content_px_in_first_view", "screens_tall", "always_open_blocks"},
    "error-recovery": {"error_messages_without_action"},
}
# Numbers a claim may state without citing them: WCAG's lines and success criteria, the Nielsen scale.
THRESHOLDS = {"0", "1", "2", "3", "4", "12", "14", "16", "24", "44", "48", "4.5", "2.5.8", "1.4.3", "1.4.4",
              "1.4.10", "1.4.11", "1.4.12", "2.4.11", "3.3.1", "3.3.3"}
MIN_TEXT = 4
CAPTURE_ID = re.compile(r"\b[a-z][a-z0-9-]*-\d{3,4}-[a-z][a-z0-9-]*\b")
MEASURE_KEY = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?:@\d{3,4})?\b")
ITEM_ID = re.compile(r"\b[PJRKQS]\d{1,3}\b")
FOLD = str.maketrans({"\u2026": "...", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-",
                      "\u2014": "-", "\u00a0": " ", "\u2212": "-"})


def in_family(kind: str, key: str) -> bool:
    return key in FAMILIES.get(kind, ()) or (kind == "buried" and key.endswith("_screens_down"))


def fold(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").translate(FOLD)).strip().casefold()


def numbers(text: str) -> set[str]:
    """The numbers a text states, ignoring capture ids, measure keys and item ids (P1, J2, R3)."""
    text = ITEM_ID.sub(" ", MEASURE_KEY.sub(" ", CAPTURE_ID.sub(" ", text or "")))
    return {n.replace(",", "") for n in NUMBER.findall(text)}


def _value_numbers(value: Any) -> set[str]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        out = {str(value), str(round(value))}
        if isinstance(value, float):
            out |= {f"{value:.1f}", f"{value:.0f}", str(value).rstrip("0").rstrip(".")}
        return out
    if isinstance(value, list):
        return {str(len(value))}.union(*[_value_numbers(v) for v in value]) if value else {"0"}
    return numbers(str(value))


def same(value: Any, actual: Any) -> bool:
    """A ref's value matches the measure: equal numbers or strings; for a list, the list, an item or its length."""
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    if num(value) and num(actual):
        return abs(float(value) - float(actual)) < 1e-9
    if isinstance(actual, list):
        if isinstance(value, list):
            return value == actual
        if isinstance(value, str):
            return value in actual
        return num(value) and value == len(actual)
    return value == actual and type(value) is type(actual)


class Context:
    """audit.json, texts.json, app.json and the requirement ids, indexed for the checks."""

    def __init__(self, audit: dict, texts: dict, app: dict, requirement_ids: set[str] | None = None):
        self.audit, self.app = audit, app
        self.captures = {s["id"]: s for s in audit["screens"]}
        self.texts = {cid: fold("\n".join(t.get("all", []))) for cid, t in texts.items()}
        self.screen_ids = [s["id"] for s in app["screens"]]
        self.totals = audit.get("totals") or {}
        self.requirement_ids = requirement_ids
        self.size_numbers = {str(w) for w in app["sizes"]} | {str(s["height"]) for s in app["sizes"].values()}


def _dicts(value: Any) -> list[tuple[int, dict]]:
    return [(i, v) for i, v in enumerate(value) if isinstance(v, dict)] if isinstance(value, list) else []


class _Checker:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.problems: list[dict] = []

    def add(self, check: str, where: str, problem: str) -> None:
        self.problems.append({"check": check, "where": where, "problem": problem})

    def ref(self, ref: dict, where: str) -> str | None:
        """Check one ref; return how it stands: problem | ok-side | context | text | total | None (broken)."""
        ctx = self.ctx
        if "total" in ref:
            total = ctx.totals.get(ref["total"])
            if total is None:
                self.add("refs", where, f"total {ref['total']!r} does not exist (totals are <measure>@<width>, "
                         "see the task's totals)")
                return None
            if ref.get("value") != total["value"] or ("of" in ref and ref["of"] != total["of"]):
                self.add("values", where, f"total {ref['total']} is {total['value']} of {total['of']}, "
                         f"not {ref.get('value')}" + (f" of {ref['of']}" if "of" in ref else ""))
                return None
            return "total"
        cap = ctx.captures.get(ref.get("capture"))
        if cap is None:
            self.add("refs", where, f"capture {ref.get('capture')!r} does not exist; capture ids are "
                     "<screen>-<width>-<state> as in the task")
            return None
        if "text" in ref:
            text = fold(ref["text"])
            if len(text.replace(" ", "")) < MIN_TEXT:
                self.add("texts", where, f"text {ref['text']!r} is too short to show anything; quote the words")
                return None
            if text not in ctx.texts.get(cap["id"], ""):
                self.add("texts", where, f"{cap['id']} shows no text {ref['text']!r}; quote visible text exactly")
                return None
            return "text"
        key = ref.get("measure")
        if key not in cap["measures"]:
            self.add("refs", where, f"{cap['id']} has no measure {key!r}")
            return None
        actual = cap["measures"][key]
        if not same(ref.get("value"), actual):
            self.add("values", where, f"{cap['id']} {key} is {json.dumps(actual)}, not {json.dumps(ref.get('value'))}")
            return None
        side = existing_measures.shows_problem(key, actual, cap)
        return "context" if side is None else ("problem" if side else "ok-side")

    def allowed_numbers(self, refs: list[dict]) -> set[str]:
        out = set(THRESHOLDS) | self.ctx.size_numbers
        for ref in refs:
            if "total" in ref:
                total = self.ctx.totals.get(ref["total"], {})
                out |= {str(total.get("value")), str(total.get("of"))}
                continue
            cap = self.ctx.captures.get(ref.get("capture"))
            if cap is None:
                continue
            out |= {str(cap["width"]), str(cap.get("height", ""))}
            if "text" in ref:
                out |= numbers(ref["text"])
            elif ref.get("measure") in cap["measures"]:
                out |= _value_numbers(cap["measures"][ref["measure"]])
        return out

    def invented(self, text: str, refs: list[dict], where: str, label: str) -> None:
        for n in sorted(numbers(text) - self.allowed_numbers(refs)):
            self.add("invented", where, f"{label} states {n}, which none of its cited refs shows; cite the measure "
                     "or text that shows it, or drop the number")


def check_draft(ctx: Context, draft: Any) -> dict:
    c = _Checker(ctx)
    for line in contracts.check_json("existing_draft", draft, "draft.json"):
        _, where, reason = (line.split(": ", 2) + ["", ""])[:3]
        c.add("schema", where, reason)
    draft = draft if isinstance(draft, dict) else {}
    journeys = _dicts(draft.get("journeys"))
    problems = _dicts(draft.get("problems"))
    problem_ids = [p.get("id") for _, p in problems]
    journey_ids = [j.get("id") for _, j in journeys]
    for kind, ids in (("journey", journey_ids), ("problem", problem_ids)):
        for dup in sorted({i for i in ids if i and ids.count(i) > 1}):
            c.add("ids", f"{kind}s", f"{kind} id {dup} is used more than once")
    named: set[str] = set()
    refs_total = 0
    keep_total = 0
    for i, j in journeys:
        where = f"journeys/{i}"
        for s in j.get("screens") or []:
            if s not in ctx.screen_ids:
                c.add("screens", f"{where}/screens", f"{j.get('id')}: {s!r} is not one of the app's screens "
                      f"({', '.join(ctx.screen_ids)})")
        for pid in j.get("problems") or []:
            named.add(pid)
            if pid not in problem_ids:
                c.add("ids", f"{where}/problems", f"{j.get('id')}: problem {pid} is not in problems")
        if ctx.requirement_ids is not None:
            for rid in j.get("requirements") or []:
                if rid not in ctx.requirement_ids:
                    c.add("ids", f"{where}/requirements", f"{j.get('id')}: {rid} is not a stage-1 requirement")
        for k, keep in _dicts(j.get("keep")):
            keep_total += 1
            kwhere = f"{where}/keep/{k}"
            refs = [r for r in keep.get("evidence") or [] if isinstance(r, dict)]
            refs_total += len(refs)
            sides = [c.ref(r, f"{kwhere}/evidence/{n}") for n, r in enumerate(refs)]
            if refs and not any(sides):
                c.add("unsupported", kwhere, f"{j.get('id')} keep {keep.get('what', '')[:60]!r}: no ref holds")
            for n, (r, side) in enumerate(zip(refs, sides, strict=True)):
                if side == "problem":
                    c.add("contradicted", f"{kwhere}/evidence/{n}", f"{j.get('id')} keep cites {r.get('capture')} "
                          f"{r.get('measure')}, which is on the problem side: a kept strength can't rest on it")
            c.invented(str(keep.get("what", "")), refs, kwhere, "keep")
    for i, p in problems:
        where = f"problems/{i}"
        pid, kind = p.get("id"), p.get("kind")
        refs = [r for r in p.get("evidence") or [] if isinstance(r, dict)]
        refs_total += len(refs)
        sides = [(r, c.ref(r, f"{where}/evidence/{n}")) for n, r in enumerate(refs)]
        if not any("capture" in r for r in refs):
            c.add("unsupported", where, f"{pid}: cites no capture; every problem rests on at least one capture")
        if kind in contracts.MEASURED_KINDS:
            fam = [(r, s) for r, s in sides if s and r.get("measure") and in_family(kind, r["measure"])]
            if any(s == "problem" for _, s in fam):
                pass
            elif fam:
                shown = ", ".join(f"{r['capture']} {r['measure']} = {json.dumps(r['value'])}" for r, _ in fam[:3])
                c.add("contradicted", where, f"{pid} ({kind}): its measures say OK ({shown}); "
                      "drop the problem or cite the capture where the measure shows it")
            else:
                c.add("unsupported", where, f"{pid} ({kind}): cites none of the {kind} measures "
                      f"({', '.join(sorted(FAMILIES[kind]))}{', <region>_screens_down' if kind == 'buried' else ''}) "
                      "with a value on the problem side")
        elif refs and not any(s in ("problem", "context", "text") for _, s in sides):
            if any(s == "ok-side" for _, s in sides):
                c.add("contradicted", where, f"{pid}: every measure it cites is on the OK side")
            elif not any(s == "total" for _, s in sides):
                c.add("unsupported", where, f"{pid}: none of its refs holds")
        c.invented(str(p.get("claim", "")), refs, where, pid or "the claim")
        if pid and pid not in named:
            c.add("orphan", where, f"{pid} is in no journey's problems")
    counts = {"journeys": len(journeys), "problems": len(problems), "keep": keep_total, "refs": refs_total,
              "severity": {str(s): sum(1 for _, p in problems if p.get("severity") == s) for s in range(5)},
              **{name: sum(1 for x in c.problems if x["check"] == name) for name in CHECKS}}
    return {"verdict": "retry" if c.problems else "ok", "counts": counts, "problems": c.problems}


def render(ref: dict) -> str:
    if "total" in ref:
        return f"{ref['total']}: {ref['value']}" + (f" of {ref['of']}" if "of" in ref else "")
    if "text" in ref:
        return f'{ref["capture"]} shows "{ref["text"]}"'
    return f"{ref['capture']}: {ref['measure']} = {json.dumps(ref['value'], ensure_ascii=False)}"


def journey_problems(ctx: Context, draft: dict) -> dict[str, list[str]]:
    """Each journey's problems: the ones the model named, then every other problem seen on a screen the journey
    passes through (a ref to a capture of that screen, or to a total that flags a capture of it), in the draft's
    order. Where a problem was seen is a fact of its refs, so the script applies it (rule 17); the model only
    judges what hurts where else."""
    screen_of = {s["id"]: s.get("screen") for s in ctx.audit["screens"]}

    def seen(ref: dict) -> set:
        if "capture" in ref:
            return {screen_of.get(ref["capture"])}
        measure, _, width = str(ref.get("total", "")).rpartition("@")
        return {s.get("screen") for s in ctx.audit["screens"]
                if str(s["width"]) == width and existing_measures.shows_problem(measure, s["measures"].get(measure), s)}

    seen_on = {p["id"]: set().union(*[seen(r) for r in p["evidence"] if isinstance(r, dict)]) - {None}
               for p in draft["problems"]}
    out = {}
    for j in draft["journeys"]:
        named = list(j["problems"])
        out[j["id"]] = named + [p["id"] for p in draft["problems"]
                                 if p["id"] not in named and seen_on[p["id"]] & set(j["screens"])]
    return out


def outputs(ctx: Context, draft: dict) -> dict:
    """journeys.json from a draft that passed check_draft."""
    problems = {p["id"]: p for p in draft["problems"]}
    hurts = journey_problems(ctx, draft)
    journeys = []
    for j in draft["journeys"]:
        out = {"id": j["id"], "name": j["name"], "goal": j["goal"], "screens": j["screens"],
               "problems": [{"id": pid, "claim": problems[pid]["claim"], "severity": problems[pid]["severity"],
                             "kind": problems[pid]["kind"], "evidence": [render(r) for r in problems[pid]["evidence"]],
                             "refs": problems[pid]["evidence"]} for pid in hurts[j["id"]]],
               "keep": [f"{k['what']} ({'; '.join(render(r) for r in k['evidence'])})" for k in j["keep"]],
               "keep_refs": j["keep"]}
        for key in ("steps", "requirements"):
            if j.get(key):
                out[key] = j[key]
        journeys.append(out)
    return {"source": f"design_app_screen_v1 stage 2 (existing), from {ctx.audit['source']}", "journeys": journeys}


def draft_from_journeys(journeys: dict) -> dict:
    """The draft a journeys.json was written from (problems once each, with their refs), to check it again."""
    problems: dict[str, dict] = {}
    out = []
    for j in journeys.get("journeys") or []:
        for p in j.get("problems") or []:
            problems.setdefault(p.get("id"), {"id": p.get("id"), "claim": p.get("claim"), "severity": p.get("severity"),
                                              "kind": p.get("kind"), "evidence": p.get("refs") or []})
        entry = {"id": j.get("id"), "name": j.get("name"), "goal": j.get("goal"), "screens": j.get("screens") or [],
                 "problems": [p.get("id") for p in j.get("problems") or []], "keep": j.get("keep_refs") or []}
        for key in ("steps", "requirements"):
            if j.get(key):
                entry[key] = j[key]
        out.append(entry)
    return {"journeys": out, "problems": list(problems.values())}
