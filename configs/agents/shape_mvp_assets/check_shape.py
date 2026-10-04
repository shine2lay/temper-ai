#!/usr/bin/env python3
"""shape_mvp checker (product role, queue #11): the input contract, the pitch checks, the pitch
renderer and the final status. No network, no model, standard library only. Run it from the
workflow workspace (setup copies it to state/shape/check_shape.py).

    check_shape.py input OPPORTUNITY.json      setup: validate, write state/shape/{input.json,
                                               input.md, setup.json}; print the setup status
    check_shape.py pitch [PITCH.json] [--stage draft|final]
                                               validate a pitch, render PITCH.md next to it,
                                               write <dir>/check.json (final: state/shape/check.json)
    check_shape.py finalize                    combine setup, model, check and grade into
                                               state/shape/result.json and RESULT.md

The rules are the D/B checks registered for queue #11 (criteria.md in the product results
folder). A failed check is data (exit 0, verdict fail); only broken infrastructure exits non-zero.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SHAPE = Path("state/shape")
INPUT_SCHEMA = "shape_mvp.opportunity/1"
PITCH_SCHEMA = "shape_mvp.pitch/1"
EVIDENCE_KINDS = {"primary", "secondary", "vendor", "estimate", "assertion"}
PARTIES = {"neutral", "interested"}
UPSTREAM_STATES = {"open", "provisional", "parked", "validated", "killed"}
SOURCES = {"owner", "test_fixture"}
RISKS = {"value", "usability", "feasibility", "viability"}
SUPPORT = {"supported", "partial", "assumption"}
PREREQ_KINDS = {"data_access", "platform_permission", "legal", "privacy", "procurement", "security",
                "integration", "owner_input", "other"}
PREREQ_STATUS = {"unresolved", "resolved"}
BLOCKS = {"build", "serve", "sell", "test"}
THRESHOLD_SOURCES = {"owner", "test_fixture", "method", "proposed"}
SEVERITIES = {"must_fix", "should_fix", "note"}
ORDER = {"blocked": 0, "revise": 1, "shaped": 2}
GRADE_IDS = [f"G{n}" for n in range(1, 9)]
NOT_APPROVAL = "Not an approval to build: the owner decides at the betting table."
PLACEHOLDER = re.compile(r"^\s*(tbd|tba|todo|unknown|n/?a|none|null|nil|xxx+|\?+|<[^>]*>|-+|\.\.\.|placeholder)\s*\.?\s*$",
                         re.I)
HORIZON = re.compile(r"\d+(\.\d+)?\s*(-|to)?\s*\d*\s*(hours?|days?|weeks?|months?|quarters?|years?)\b", re.I)
LIMIT_TEXT = re.compile(r"you['\u2019]ve hit your (\w+ )?limit|usage limit reached|\b(5-hour|five-hour|weekly|session) "
                        r"limit reached|claude ai usage limit", re.I)
OWNER_GAPS = {
    "target_price": ("OG-target_price", "Target price for the first version",
                     "The owner sets price; the shaper must not invent it."),
    "success_bar": ("OG-success_bar", "Success bar (metric, threshold, horizon) the owner accepts",
                    "Success thresholds are the owner's call; proposals stay proposals until confirmed."),
}
SECTIONS = ["## Problem", "## Appetite", "## Solution", "## Rabbit holes", "## No-gos",
            "## Evidence and assumptions", "## Prerequisites", "## Success criteria",
            "## Verification plan", "## Owner inputs needed", "## Upstream status"]


# ---- small helpers -------------------------------------------------------------------------------


def text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def filled(value) -> bool:
    """A real value: a non-empty string that is not a placeholder."""
    return bool(text(value)) and not PLACEHOLDER.match(text(value))


def number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def norm(value: str) -> str:
    """Whitespace, quote marks and dashes normalised, lower case: for verbatim-quote checks."""
    table = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-", 0xA0: " "}
    return re.sub(r"\s+", " ", value.translate(table)).strip().lower()


def items(value) -> list:
    return value if isinstance(value, list) else []


def ids(rows: list, key: str = "id") -> list[str]:
    return [text(r.get(key)) for r in rows if isinstance(r, dict)]


def problem(code: str, message: str, unblock: str = "") -> dict:
    row = {"code": code, "message": message}
    if unblock:
        row["unblock"] = unblock
    return row


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# ---- the input contract -------------------------------------------------------------------------


def check_input(raw) -> dict:
    """Validate an opportunity. Critical problems block shaping; owner gaps never do."""
    crit: list[dict] = []
    warn: list[dict] = []
    if not isinstance(raw, dict):
        return {"status": "blocked", "problems": [problem("input", "The opportunity is not a JSON object",
                                                          "Supply a shape_mvp.opportunity/1 JSON object")],
                "warnings": [], "owner_input_gaps": [], "fixture_values": [], "capacity": None}
    if raw.get("schema") != INPUT_SCHEMA:
        crit.append(problem("schema", f"schema must be {INPUT_SCHEMA}", f"Set schema to {INPUT_SCHEMA}"))
    case_id = text(raw.get("id"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,80}", case_id):
        crit.append(problem("id", "id missing or not a lower-case slug", "Give the opportunity a slug id"))
    if not filled(raw.get("title")):
        crit.append(problem("title", "title missing", "Give the opportunity a title"))
    for field, what in (("buyer", "who pays"), ("job", "the job the product does for them")):
        if not filled(raw.get(field)):
            crit.append(problem(field, f"{field} missing or a placeholder ({what})",
                                f"State the {field} ({what}) from the evidence"))

    # Evidence: ids unique; at least one quoted, sourced item that is not a bare assertion.
    evidence = items(raw.get("evidence"))
    seen: set[str] = set()
    quoted = 0
    for row in evidence:
        if not isinstance(row, dict):
            crit.append(problem("evidence", "an evidence item is not an object", "Fix the evidence list"))
            continue
        eid = text(row.get("id"))
        if not eid or eid in seen:
            crit.append(problem("evidence", f"evidence id missing or repeated: {eid!r}", "Give each item a unique id"))
        seen.add(eid)
        kind = text(row.get("kind"))
        if kind not in EVIDENCE_KINDS:
            crit.append(problem("evidence", f"evidence {eid}: kind must be one of {sorted(EVIDENCE_KINDS)}",
                                "Label each evidence item's kind"))
        if row.get("party") is not None and text(row.get("party")) not in PARTIES:
            warn.append(problem("evidence", f"evidence {eid}: party should be neutral or interested"))
        if not filled(row.get("claim")) or not filled(row.get("source")):
            crit.append(problem("evidence", f"evidence {eid}: claim and source are required",
                                "Give each evidence item its claim and source"))
        if kind != "estimate" and not filled(row.get("quote")) and kind != "assertion":
            warn.append(problem("evidence", f"evidence {eid}: no exact quote; it cannot back a quoted claim"))
        if kind != "assertion" and filled(row.get("quote")) and filled(row.get("source")):
            quoted += 1
    if not evidence:
        crit.append(problem("evidence", "no evidence supplied",
                            "Supply evidence for the problem: quoted, sourced items (desk checks, briefs, interviews)"))
    elif not quoted:
        crit.append(problem("evidence", "no quoted, sourced evidence (bare assertions only)",
                            "Supply at least one quoted, sourced evidence item that is not an assertion"))

    # Appetite: fixed by the owner (or labelled a test fixture); never invented here.
    appetite = raw.get("appetite")
    capacity = None
    if not isinstance(appetite, dict):
        crit.append(problem("appetite", "appetite missing",
                            "The owner sets the appetite: time_weeks and builders (source owner)"))
    else:
        weeks, builders = number(appetite.get("time_weeks")), number(appetite.get("builders"))
        source = text(appetite.get("source"))
        if weeks is None or not 0 < weeks <= 52:
            crit.append(problem("appetite", "appetite.time_weeks missing or not in (0, 52]",
                                "The owner sets the appetite in weeks"))
        if builders is None or builders != int(builders) or not 1 <= builders <= 10:
            crit.append(problem("appetite", "appetite.builders missing or not a whole number 1-10",
                                "The owner sets how many builders the appetite pays for"))
        if source not in SOURCES:
            crit.append(problem("appetite", "appetite.source must be owner or test_fixture",
                                "Say whether the appetite is the owner's or a labelled test fixture"))
        if weeks and builders and weeks > 0 and builders >= 1:
            capacity = round(weeks * builders, 4)

    constraints = items(raw.get("constraints"))
    if not constraints:
        crit.append(problem("constraints", "constraints missing",
                            "List the constraints that bound the work (each with its source)"))
    for row in constraints:
        if not isinstance(row, dict) or not filled(row.get("id")) or not filled(row.get("text")) \
                or not filled(row.get("source")):
            crit.append(problem("constraints", "each constraint needs id, text and source",
                                "Give each constraint an id, text and source"))
            break

    upstream = raw.get("upstream_status")
    if not isinstance(upstream, dict) or text(upstream.get("state")) not in UPSTREAM_STATES \
            or not filled(upstream.get("source")):
        crit.append(problem("upstream_status", f"upstream_status needs state ({'|'.join(sorted(UPSTREAM_STATES))}) "
                                               "and source", "Record the idea's upstream status and where it is recorded"))
    elif upstream.get("state") == "killed" and not upstream.get("reopened"):
        crit.append(problem("upstream_killed",
                            f"the idea was killed upstream and not reopened: {text(upstream.get('summary'))}",
                            "Only the owner reopens a killed idea, with new evidence (upstream_status.reopened)"))

    unknowns = raw.get("open_unknowns")
    if unknowns is None:
        warn.append(problem("open_unknowns", "no open unknowns supplied: none will be carried"))
    seen_u: set[str] = set()
    for row in items(unknowns):
        if not isinstance(row, dict) or not filled(row.get("id")) or not filled(row.get("question")) \
                or not isinstance(row.get("fatal"), bool) or not filled(row.get("source")):
            crit.append(problem("open_unknowns", "each open unknown needs id, question, fatal (true/false) and source",
                                "Fix the open unknowns list"))
            break
        if row["id"] in seen_u:
            crit.append(problem("open_unknowns", f"repeated unknown id {row['id']}", "Give unknowns unique ids"))
        seen_u.add(row["id"])

    # Owner inputs: absent ones become gaps for the owner (never invented).
    gaps = []
    owner_inputs = raw.get("owner_inputs") if isinstance(raw.get("owner_inputs"), dict) else {}
    fixture_values = []
    for key, (gap_id, needed, why) in OWNER_GAPS.items():
        given = owner_inputs.get(key)
        if isinstance(given, dict) and filled(given.get("value")) and text(given.get("source")) in SOURCES:
            if given["source"] == "test_fixture":
                fixture_values.append(f"{key}: {text(given['value'])}")
        else:
            gaps.append({"id": gap_id, "needed": needed, "why": why})

    if isinstance(appetite, dict) and appetite.get("source") == "test_fixture" and capacity:
        fixture_values.insert(0, f"appetite: {appetite.get('time_weeks')} weeks x {appetite.get('builders')} "
                                 "builder(s)")
    fixture = raw.get("fixture") if isinstance(raw.get("fixture"), dict) else {}
    if fixture.get("fictional"):
        fixture_values.insert(0, "the whole opportunity is fictional: " + (text(fixture.get("label")) or "fixture"))
    proposal = raw.get("proposed_solution")
    if isinstance(proposal, dict):
        if proposal.get("source") == "test_fixture":
            fixture_values.append("proposed solution")
        seen_f: set[str] = set()
        for row in items(proposal.get("features")):
            if not isinstance(row, dict) or not filled(row.get("id")) or not filled(row.get("name")) \
                    or row["id"] in seen_f:
                crit.append(problem("proposed_solution", "each proposed feature needs a unique id and a name",
                                    "Fix the proposed features"))
                break
            seen_f.add(row["id"])
    for row in constraints:
        if isinstance(row, dict) and row.get("source") == "test_fixture":
            fixture_values.append(f"constraint {text(row.get('id'))}")

    return {"status": "blocked" if crit else "ready_to_shape", "problems": crit, "warnings": warn,
            "owner_input_gaps": gaps, "fixture_values": fixture_values, "capacity": capacity}


def render_input(raw: dict, setup: dict) -> str:
    """The opportunity as the model steps read it (input.json stays the source of truth)."""
    out = [f"# Opportunity: {text(raw.get('title'))} ({text(raw.get('id'))})", ""]
    if setup["fixture_values"]:
        out += ["TEST FIXTURE values (test data, never owner commitments): " + "; ".join(setup["fixture_values"]), ""]
    out += [f"Buyer: {text(raw.get('buyer'))}", f"User: {text(raw.get('user')) or '(not given)'}",
            f"Job: {text(raw.get('job'))}", ""]
    app = raw.get("appetite") if isinstance(raw.get("appetite"), dict) else {}
    out += ["## Appetite", f"{app.get('time_weeks')} weeks x {app.get('builders')} builder(s) = "
            f"{setup['capacity']} builder-weeks. Source: {app.get('source')}. {text(app.get('note'))}", ""]
    up = raw.get("upstream_status") if isinstance(raw.get("upstream_status"), dict) else {}
    out += ["## Upstream status", f"{up.get('state')}: {text(up.get('summary'))} (source: {text(up.get('source'))})", ""]
    out += ["## Constraints"] + [f"- {c.get('id')}: {text(c.get('text'))} (source: {text(c.get('source'))})"
                                 for c in items(raw.get("constraints")) if isinstance(c, dict)] + [""]
    out += ["## Evidence"]
    for e in items(raw.get("evidence")):
        if isinstance(e, dict):
            out.append(f"- {e.get('id')} [{e.get('kind')}{', ' + text(e.get('party')) if e.get('party') else ''}] "
                       f"{text(e.get('claim'))}")
            if filled(e.get("quote")):
                out.append(f"  Quote: \"{text(e.get('quote'))}\"")
            out.append(f"  Source: {text(e.get('source'))}" + (f" (checked {e.get('checked')})" if e.get("checked") else ""))
    out += ["", "## Open unknowns"]
    for u in items(raw.get("open_unknowns")):
        if isinstance(u, dict):
            out.append(f"- {u.get('id')}{' FATAL' if u.get('fatal') else ''}: {text(u.get('question'))} "
                       f"(source: {text(u.get('source'))})")
    proposal = raw.get("proposed_solution")
    if isinstance(proposal, dict):
        out += ["", "## Proposed solution (a proposal to shape, not a commitment)",
                f"{text(proposal.get('summary'))} (source: {text(proposal.get('source'))})"]
        for f in items(proposal.get("features")):
            if isinstance(f, dict):
                est = f.get("proposer_estimate_builder_weeks")
                out.append(f"- {f.get('id')} {text(f.get('name'))}: {text(f.get('does'))}"
                           + (f" (proposer's estimate {est} builder-weeks)" if est is not None else ""))
    owner_inputs = raw.get("owner_inputs") if isinstance(raw.get("owner_inputs"), dict) else {}
    out += ["", "## Owner inputs"]
    for key, value in owner_inputs.items():
        if isinstance(value, dict):
            out.append(f"- {key}: {text(value.get('value'))} (source: {text(value.get('source'))})")
    out += [f"- GAP {g['id']}: {g['needed']} ({g['why']})" for g in setup["owner_input_gaps"]]
    if raw.get("notes"):
        out += ["", "## Notes", text(raw.get("notes"))]
    return "\n".join(out) + "\n"


def run_input(source: Path) -> int:
    if (SHAPE / "setup.json").exists():
        raise SystemExit("Refusing to overwrite an existing shaping run: use a fresh workspace")
    SHAPE.mkdir(parents=True, exist_ok=True)
    try:
        raw = json.loads(source.read_text())
    except ValueError as error:
        raw = None
        print(f"input is not JSON: {error}", file=sys.stderr)
    setup = check_input(raw)
    (SHAPE / "input.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    setup["case_id"] = text(raw.get("id")) if isinstance(raw, dict) else ""
    if isinstance(raw, dict) and setup["status"] == "ready_to_shape":
        (SHAPE / "input.md").write_text(render_input(raw, setup))
    (SHAPE / "setup.json").write_text(json.dumps(setup, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": setup["status"], "case_id": setup["case_id"],
                      "problems": [p["code"] + ": " + p["message"] for p in setup["problems"]],
                      "owner_input_gaps": [g["id"] for g in setup["owner_input_gaps"]],
                      "fixture_values": setup["fixture_values"], "capacity_builder_weeks": setup["capacity"]}))
    return 0


# ---- the pitch checks ---------------------------------------------------------------------------


def evidence_index(inp: dict) -> dict[str, dict]:
    return {text(e.get("id")): e for e in items(inp.get("evidence")) if isinstance(e, dict)}


def check_pitch(pitch, inp: dict, setup: dict, stage: str = "final", critique=None) -> list[dict]:
    """D1-D13 for a shaped pitch, B for a blocked record. Returns problems (empty = pass)."""
    out: list[dict] = []
    if not isinstance(pitch, dict):
        return [problem("D1", "pitch is not a JSON object")]
    if pitch.get("schema") != PITCH_SCHEMA:
        out.append(problem("D1", f"schema must be {PITCH_SCHEMA}"))
    status = pitch.get("status")
    if status not in ("shaped", "blocked"):
        out.append(problem("D1", "status must be shaped or blocked"))
    if text(pitch.get("case_id")) != text(inp.get("id")):
        out.append(problem("D1", "case_id does not match the input id"))
    evidence = evidence_index(inp)
    app_in, app_out = inp.get("appetite") or {}, pitch.get("appetite") or {}
    for key in ("time_weeks", "builders", "source"):
        if not isinstance(app_out, dict) or app_out.get(key) != app_in.get(key):
            out.append(problem("D2", f"appetite.{key} must be copied exactly from the input ({app_in.get(key)!r})"))
    up_in, up_out = inp.get("upstream_status") or {}, pitch.get("upstream_status") or {}
    if not isinstance(up_out, dict) or up_out.get("state") != up_in.get("state"):
        out.append(problem("D10", f"upstream_status.state must be copied ({up_in.get('state')!r})"))

    cited: list[tuple[str, str]] = []  # (where, evidence id)

    def cite(where: str, row: dict, key: str = "evidence_ids") -> None:
        for eid in items(row.get(key)):
            cited.append((where, text(eid)))

    solution = pitch.get("solution") if isinstance(pitch.get("solution"), dict) else {}
    elements = items(solution.get("elements"))
    if status == "blocked":
        blocked = pitch.get("blocked") if isinstance(pitch.get("blocked"), dict) else {}
        if not [r for r in items(blocked.get("reasons")) if filled(r)]:
            out.append(problem("B", "a blocked record needs at least one reason"))
        if not [r for r in items(blocked.get("unblock_needs")) if filled(r)]:
            out.append(problem("B", "a blocked record needs at least one unblock need"))
        if elements:
            out.append(problem("B", "a blocked record must not carry solution elements"))
        cite("blocked", blocked)
        for row in items(pitch.get("claims")):
            if isinstance(row, dict):
                cite("claims", row)
    elif status == "shaped":
        out += check_shaped(pitch, inp, setup, solution, elements, evidence, cite, stage, critique)
    for where, eid in cited:
        if eid not in evidence:
            out.append(problem("D4", f"{where} cites unknown evidence id {eid!r}"))
    return out


def check_shaped(pitch, inp, setup, solution, elements, evidence, cite, stage, critique) -> list[dict]:
    out: list[dict] = []
    prob = pitch.get("problem") if isinstance(pitch.get("problem"), dict) else {}
    if not filled(prob.get("statement")):
        out.append(problem("D12", "problem.statement is required"))
    prob_ids = [text(e) for e in items(prob.get("evidence_ids"))]
    cite("problem", prob)
    if not [e for e in prob_ids if e in evidence and evidence[e].get("kind") != "assertion"]:
        out.append(problem("D4", "the problem must cite at least one non-assertion evidence item"))

    # D3 fit, D11 proposal coverage
    capacity = setup.get("capacity") or 0
    total = 0.0
    if not 1 <= len(elements) <= 12:
        out.append(problem("D3", "solution needs 1-12 elements"))
    for row in elements:
        if not isinstance(row, dict):
            out.append(problem("D3", "a solution element is not an object"))
            continue
        est = number(row.get("estimate_builder_weeks"))
        if est is None or est <= 0:
            out.append(problem("D3", f"element {row.get('id')}: estimate_builder_weeks must be a number > 0"))
        else:
            total += est
        if not filled(row.get("name")) or not filled(row.get("does")):
            out.append(problem("D12", f"element {row.get('id')}: name and does are required"))
        cite(f"element {row.get('id')}", row)
    if capacity and total > capacity + 1e-9:
        out.append(problem("D3", f"estimates total {round(total, 3)} builder-weeks, over the appetite's {capacity}: "
                                 "cut scope, never stretch the appetite"))
    if not filled(solution.get("summary")):
        out.append(problem("D12", "solution.summary is required"))
    if not isinstance(solution.get("human_steps"), list):
        out.append(problem("D12", "solution.human_steps must be a list (may be empty)"))
    proposal = inp.get("proposed_solution") if isinstance(inp.get("proposed_solution"), dict) else {}
    kept = {text(f) for row in elements if isinstance(row, dict) for f in items(row.get("from_features"))}
    cuts = items(pitch.get("scope_cuts"))
    cut = {text(row.get("feature")) for row in cuts if isinstance(row, dict)}
    for row in cuts:
        if not isinstance(row, dict) or not filled(row.get("item")) or not filled(row.get("why")):
            out.append(problem("D11", "each scope cut needs item and why"))
            break
    for feature in items(proposal.get("features")):
        fid = text(feature.get("id")) if isinstance(feature, dict) else ""
        if fid and fid not in kept and fid not in cut:
            out.append(problem("D11", f"proposed feature {fid} is neither kept in an element (from_features) "
                                      "nor named in a scope cut (feature)"))

    # D12 required lists
    holes = [r for r in items(pitch.get("rabbit_holes")) if isinstance(r, dict)]
    if not holes or any(not filled(r.get("risk")) or not filled(r.get("patch")) for r in holes):
        out.append(problem("D12", "rabbit_holes: at least one, each with risk and patch"))
    for r in holes:
        cite(f"rabbit hole {r.get('id')}", r)
    nogos = [r for r in items(pitch.get("no_gos")) if isinstance(r, dict)]
    if not nogos or any(not filled(r.get("item")) or not filled(r.get("why")) for r in nogos):
        out.append(problem("D12", "no_gos: at least one, each with item and why"))

    # D4 claims
    for row in items(pitch.get("claims")):
        if not isinstance(row, dict) or not filled(row.get("text")):
            out.append(problem("D4", "each claim needs text"))
            continue
        support = row.get("support")
        if support not in SUPPORT:
            out.append(problem("D4", f"claim {row.get('id')}: support must be one of {sorted(SUPPORT)}"))
        cite(f"claim {row.get('id')}", row)
        eids = [text(e) for e in items(row.get("evidence_ids"))]
        if support in ("supported", "partial") and not eids:
            out.append(problem("D4", f"claim {row.get('id')}: a {support} claim must cite evidence"))
        if filled(row.get("quote")):
            quote = norm(text(row.get("quote")))
            if not any(e in evidence and quote in norm(text(evidence[e].get("quote"))) for e in eids):
                out.append(problem("D4", f"claim {row.get('id')}: quote is not verbatim in any cited evidence quote"))

    # D5 unknowns kept, D6 tests
    assumptions = [r for r in items(pitch.get("assumptions")) if isinstance(r, dict)]
    prereqs = [r for r in items(pitch.get("prerequisites")) if isinstance(r, dict)]
    steps = [r for r in items(pitch.get("verification_plan")) if isinstance(r, dict)]
    step_by_id = {text(s.get("id")): s for s in steps}
    a_ids = ids(assumptions)
    carried: dict[str, list[dict]] = {}
    for row in assumptions + prereqs:
        for u in items(row.get("from_unknowns")):
            carried.setdefault(text(u), []).append(row)
    for unknown in items(inp.get("open_unknowns")):
        if not isinstance(unknown, dict):
            continue
        uid = text(unknown.get("id"))
        if uid not in carried:
            out.append(problem("D5", f"open unknown {uid} is not carried into any assumption or prerequisite"))
        elif unknown.get("fatal") and not any(r in assumptions and r.get("fatal") is True for r in carried[uid]):
            out.append(problem("D5", f"fatal unknown {uid} must become an assumption with fatal: true"))
    known_u = {text(u.get("id")) for u in items(inp.get("open_unknowns")) if isinstance(u, dict)}
    for u in carried:
        if u not in known_u:
            out.append(problem("D5", f"from_unknowns names {u!r}, which is not an input unknown"))
    for row in assumptions:
        aid = text(row.get("id"))
        if not filled(row.get("text")) or row.get("risk") not in RISKS or not isinstance(row.get("fatal"), bool):
            out.append(problem("D6", f"assumption {aid}: text, risk ({'|'.join(sorted(RISKS))}) and fatal are required"))
        cite(f"assumption {aid}", row)
        step = step_by_id.get(text(row.get("test")))
        if not step or aid not in [text(t) for t in items(step.get("tests"))]:
            out.append(problem("D6", f"assumption {aid}: test must name a verification step that lists it"))
    if not prereqs and not filled(pitch.get("prerequisites_none_reason")):
        out.append(problem("D12", "prerequisites: list them, or give prerequisites_none_reason"))
    for row in prereqs:
        pid = text(row.get("id"))
        if row.get("kind") not in PREREQ_KINDS or row.get("status") not in PREREQ_STATUS \
                or row.get("blocks") not in BLOCKS or not filled(row.get("text")):
            out.append(problem("D12", f"prerequisite {pid}: kind, text, status (unresolved|resolved) and "
                                      "blocks (build|serve|sell|test) are required"))
        cite(f"prerequisite {pid}", row)
        if row.get("status") == "resolved" and not items(row.get("evidence_ids")):
            out.append(problem("D5", f"prerequisite {pid} is marked resolved without evidence"))
    if not steps:
        out.append(problem("D12", "verification_plan: at least one step"))
    orders = [s.get("order") for s in steps]
    if len(set(map(str, orders))) != len(orders) or any(not isinstance(o, int) or isinstance(o, bool) for o in orders):
        out.append(problem("D6", "verification steps need unique whole-number order"))
    if len(step_by_id) != len(steps):
        out.append(problem("D6", "verification step ids must be unique"))
    for s in steps:
        sid = text(s.get("id"))
        tests = [text(t) for t in items(s.get("tests"))]
        if not tests or any(t not in a_ids for t in tests):
            out.append(problem("D6", f"step {sid}: tests must list existing assumption ids"))
        for key in ("method", "pass_if", "kill_if", "effort"):
            if not filled(s.get(key)):
                out.append(problem("D6", f"step {sid}: {key} is required"))
        if s.get("cost") not in ("free", "paid") or not isinstance(s.get("needs_owner_approval"), bool):
            out.append(problem("D6", f"step {sid}: cost (free|paid) and needs_owner_approval (true/false) are required"))
        elif s.get("cost") == "paid" and not s.get("needs_owner_approval"):
            out.append(problem("D6", f"step {sid}: a paid step needs owner approval"))
    out += fatal_first(inp, assumptions, steps)

    # D7 success criteria, D8 owner gaps
    gaps = [g for g in items(pitch.get("owner_input_gaps")) if isinstance(g, dict)]
    gap_ids = set(ids(gaps))
    for g in gaps:
        if not filled(g.get("id")) or not filled(g.get("needed")):
            out.append(problem("D8", "each owner input gap needs id and needed"))
            break
    for need in setup.get("owner_input_gaps", []):
        if need["id"] not in gap_ids:
            out.append(problem("D8", f"owner input gap {need['id']} ({need['needed']}) must be carried"))
    owner_inputs = inp.get("owner_inputs") if isinstance(inp.get("owner_inputs"), dict) else {}
    bar = owner_inputs.get("success_bar") if isinstance(owner_inputs.get("success_bar"), dict) else {}
    criteria = [c for c in items(pitch.get("success_criteria")) if isinstance(c, dict)]
    if not criteria:
        out.append(problem("D12", "success_criteria: at least one"))
    for c in criteria:
        cid = text(c.get("id"))
        gap = c.get("owner_input_gap")
        if gap is not None and text(gap) not in gap_ids:
            out.append(problem("D7", f"criterion {cid}: owner_input_gap {gap!r} is not in owner_input_gaps"))
        if not filled(c.get("metric")) or not filled(c.get("method")):
            out.append(problem("D7", f"criterion {cid}: metric and method are required"))
        if gap is None:
            if not re.search(r"\d", text(c.get("threshold"))):
                out.append(problem("D7", f"criterion {cid}: threshold needs a number (or an owner_input_gap)"))
            if not HORIZON.search(text(c.get("horizon"))):
                out.append(problem("D7", f"criterion {cid}: horizon needs a number and a time unit"))
        source = c.get("threshold_source")
        if source not in THRESHOLD_SOURCES:
            out.append(problem("D7", f"criterion {cid}: threshold_source must be one of {sorted(THRESHOLD_SOURCES)}"))
        elif source in ("owner", "test_fixture") and bar.get("source") != source:
            out.append(problem("D7", f"criterion {cid}: threshold_source {source} but the input gives no success "
                                     f"bar with that source"))
        elif source == "proposed" and gap is None:
            out.append(problem("D7", f"criterion {cid}: a proposed threshold needs an owner_input_gap"))

    # D9 labels
    if setup.get("fixture_values") and not [v for v in items(pitch.get("fixture_values")) if filled(v)]:
        out.append(problem("D9", "the input has test-fixture values: list them in fixture_values"))

    # D13 critique responses (final pitch only)
    if stage == "final":
        responses = {text(r.get("critique_id")): r for r in items(pitch.get("critique_responses"))
                     if isinstance(r, dict)}
        for k in items((critique or {}).get("items")):
            if isinstance(k, dict) and k.get("severity") in ("must_fix", "should_fix"):
                r = responses.get(text(k.get("id")))
                if not r or r.get("action") not in ("accepted", "rejected") or not filled(r.get("note")):
                    out.append(problem("D13", f"critique item {k.get('id')} ({k.get('severity')}) needs a response: "
                                              "action accepted|rejected and a note"))
    return out


# ---- rendering ----------------------------------------------------------------------------------


def fatal_first(inp: dict, assumptions: list[dict], steps: list[dict]) -> list[dict]:
    """D6, riskiest first: with k fatal input unknowns, each is tested within the first max(2, k + 1) steps.

    A fatal unknown is tested by a step that lists one of the fatal assumptions carried from it; steps
    count in order. A paid or contact test can come later if a free desk step that could already
    kill the assumption comes early.
    """
    fatal = [text(u.get("id")) for u in items(inp.get("open_unknowns")) if isinstance(u, dict) and u.get("fatal")]
    ranked = sorted((s for s in steps if isinstance(s.get("order"), int) and not isinstance(s.get("order"), bool)),
                    key=lambda s: s["order"])
    window = max(2, len(fatal) + 1)
    out = []
    for uid in fatal:
        carried = {text(a.get("id")) for a in assumptions
                   if a.get("fatal") is True and uid in [text(u) for u in items(a.get("from_unknowns"))]}
        if not carried:
            continue  # D5 reports it
        first = next((n for n, s in enumerate(ranked, 1) if carried & {text(t) for t in items(s.get("tests"))}), None)
        if first is None or first > window:
            where = f"first tested at step {first}" if first else "not tested by any step"
            out.append(problem("D6", f"fatal unknown {uid} (assumption {', '.join(sorted(carried))}) is {where}; with "
                                     f"{len(fatal)} fatal unknown(s) each must be tested within the first {window} "
                                     "steps by order: put a free desk test of it early, a paid or contact test can "
                                     "follow later"))
    return out


def bullet(rows, fmt) -> list[str]:
    return [fmt(r) for r in rows if isinstance(r, dict)] or ["- (none)"]


def render_pitch(pitch: dict, inp: dict, setup: dict) -> str:
    title = text(inp.get("title"))
    status = pitch.get("status")
    out = [f"# Pitch: {title}", "", f"Status: {status}", NOT_APPROVAL]
    if setup.get("fixture_values"):
        out.append("TEST FIXTURE (test data, not owner commitments): " + "; ".join(setup["fixture_values"]))
    up = inp.get("upstream_status") or {}
    out += [f"Upstream: {up.get('state')} ({text(up.get('summary'))})", ""]
    app = inp.get("appetite") or {}
    fixture_note = " TEST FIXTURE: not an owner commitment." if app.get("source") == "test_fixture" else ""
    claims = bullet(items(pitch.get("claims")), lambda c: (
        f"- {c.get('id')} [{c.get('support')}: {', '.join(map(str, items(c.get('evidence_ids')))) or 'no evidence'}] "
        f"{text(c.get('text'))}" + (f" Quote: \"{text(c.get('quote'))}\"" if filled(c.get("quote")) else "")))
    if status == "blocked":
        blocked = pitch.get("blocked") or {}
        out += ["## Why blocked"] + [f"- {text(r)}" for r in items(blocked.get("reasons"))] + [""]
        out += ["## What would unblock it"] + [f"- {text(r)}" for r in items(blocked.get("unblock_needs"))] + [""]
        if items(blocked.get("evidence_ids")):
            out += ["Evidence considered: " + ", ".join(map(str, items(blocked.get("evidence_ids")))), ""]
        out += ["## Evidence and assumptions"] + claims + [""]
        out += ["## Appetite", f"{app.get('time_weeks')} weeks x {app.get('builders')} builder(s) "
                f"(source: {app.get('source')}).{fixture_note}", ""]
        out += ["## Upstream status", f"{up.get('state')}: {text(up.get('summary'))} (source: {text(up.get('source'))})", ""]
        return "\n".join(out)
    prob = pitch.get("problem") or {}
    out += ["## Problem", text(prob.get("statement")), "",
            f"Buyer: {text(inp.get('buyer'))}", f"Job: {text(inp.get('job'))}",
            "Evidence: " + (", ".join(map(str, items(prob.get("evidence_ids")))) or "(none)"), ""]
    solution = pitch.get("solution") or {}
    elements = [e for e in items(solution.get("elements")) if isinstance(e, dict)]
    total = sum(number(e.get("estimate_builder_weeks")) or 0 for e in elements)
    out += ["## Appetite", f"{app.get('time_weeks')} weeks x {app.get('builders')} builder(s) = "
            f"{setup.get('capacity')} builder-weeks (source: {app.get('source')}).{fixture_note}"]
    if filled(app.get("note")):
        out.append("Input note: " + text(app.get("note")))
    if filled(pitch.get("appetite_note")):
        out.append("Shaping note: " + text(pitch.get("appetite_note")))
    out += ["", "## Solution", text(solution.get("summary")), "",
            "| Element | What it does | Builder-weeks | From proposal |", "|---|---|---|---|"]
    for e in elements:
        out.append(f"| {e.get('id')} {text(e.get('name'))} | {text(e.get('does'))} | {e.get('estimate_builder_weeks')} | "
                   f"{', '.join(map(str, items(e.get('from_features')))) or '-'} |")
    out += ["", f"Estimated total: {round(total, 2)} of {setup.get('capacity')} builder-weeks.", "",
            "Human steps (kept by design):"] + ([f"- {text(h)}" for h in items(solution.get("human_steps"))] or ["- (none)"])
    out += ["", "Scope cuts (not in this version):"] + bullet(items(pitch.get("scope_cuts")), lambda c: (
        f"- {text(c.get('item'))}" + (f" (proposed feature {c.get('feature')})" if c.get("feature") else "")
        + f": {text(c.get('why'))}"))
    out += ["", "## Rabbit holes"] + bullet(items(pitch.get("rabbit_holes")), lambda r: (
        f"- {r.get('id')}: {text(r.get('risk'))} Patch: {text(r.get('patch'))}"))
    out += ["", "## No-gos"] + bullet(items(pitch.get("no_gos")), lambda r: f"- {text(r.get('item'))}: {text(r.get('why'))}")
    out += ["", "## Evidence and assumptions", "Claims:"] + claims + ["", "Assumptions:"]
    out += bullet(items(pitch.get("assumptions")), lambda a: (
        f"- {a.get('id')} ({a.get('risk')}{', FATAL' if a.get('fatal') else ''}"
        + (f", from {', '.join(map(str, items(a.get('from_unknowns'))))}" if items(a.get("from_unknowns")) else "")
        + f") {text(a.get('text'))} Test: {a.get('test')}"))
    out += ["", "## Prerequisites"]
    if items(pitch.get("prerequisites")):
        out += bullet(items(pitch.get("prerequisites")), lambda p: (
            f"- {p.get('id')} [{p.get('kind')}, {str(p.get('status')).upper()}, blocks {p.get('blocks')}] "
            f"{text(p.get('text'))}" + (f" (from {', '.join(map(str, items(p.get('from_unknowns'))))})"
                                        if items(p.get("from_unknowns")) else "")))
    else:
        out.append("None: " + text(pitch.get("prerequisites_none_reason")))
    out += ["", "## Success criteria"] + bullet(items(pitch.get("success_criteria")), lambda c: (
        f"- {c.get('id')} {text(c.get('metric'))}. Method: {text(c.get('method'))}. Threshold: {text(c.get('threshold'))} "
        f"({c.get('threshold_source')}). Horizon: {text(c.get('horizon'))}."
        + (f" Owner gap: {c.get('owner_input_gap')}." if c.get("owner_input_gap") else "")))
    steps = sorted([s for s in items(pitch.get("verification_plan")) if isinstance(s, dict)],
                   key=lambda s: s.get("order") if isinstance(s.get("order"), int) else 999)
    out += ["", "## Verification plan"] + ([
        f"{s.get('order')}. {s.get('id')} tests {', '.join(map(str, items(s.get('tests'))))}: {text(s.get('method'))} "
        f"Pass if: {text(s.get('pass_if'))} Kill if: {text(s.get('kill_if'))} Effort: {text(s.get('effort'))}. "
        f"Cost: {s.get('cost')}. Owner approval needed: {'yes' if s.get('needs_owner_approval') else 'no'}."
        for s in steps] or ["(none)"])
    out += ["", "## Owner inputs needed"] + bullet(items(pitch.get("owner_input_gaps")), lambda g: (
        f"- {g.get('id')}: {text(g.get('needed'))}" + (f" ({text(g.get('why'))})" if filled(g.get("why")) else "")))
    if items(pitch.get("fixture_values")):
        out += ["", "Test-fixture values used: " + "; ".join(text(v) for v in items(pitch.get("fixture_values")))]
    out += ["", "## Upstream status", f"{up.get('state')}: {text(up.get('summary'))} (source: {text(up.get('source'))})"]
    if items(pitch.get("critique_responses")):
        out += ["", "## Critique responses"] + bullet(items(pitch.get("critique_responses")), lambda r: (
            f"- {r.get('critique_id')} {r.get('action')}: {text(r.get('note'))}"))
    return "\n".join(out) + "\n"


def section_order_ok(md: str) -> bool:
    positions = [md.find("\n" + s + "\n") for s in SECTIONS]
    return all(p >= 0 for p in positions) and positions == sorted(positions)


def run_pitch(path: Path, stage: str) -> int:
    inp = load_json(SHAPE / "input.json") or {}
    setup = load_json(SHAPE / "setup.json") or {}
    critique = load_json(SHAPE / "critique.json") if stage == "final" else None
    pitch = load_json(path)
    if pitch is None:
        problems = [problem("D1", f"{path} is missing or not valid JSON")]
    else:
        problems = check_pitch(pitch, inp, setup, stage, critique)
        md = render_pitch(pitch, inp, setup)
        if pitch.get("status") == "shaped" and not section_order_ok(md):
            problems.append(problem("D2", "rendered sections out of order (Appetite must precede Solution)"))
        path.with_suffix(".md").write_text(md)
    verdict = "pass" if not problems else "fail"
    report = {"verdict": verdict, "stage": stage, "pitch": str(path),
              "pitch_status": pitch.get("status") if isinstance(pitch, dict) else None, "problems": problems}
    target = SHAPE / "check.json" if stage == "final" else path.parent / "check.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": "completed", "verdict": verdict,
                      "problems": [p["code"] + ": " + p["message"] for p in problems]}))
    return 0


# ---- the final status ---------------------------------------------------------------------------


def limit_hits() -> list[str]:
    hits = []
    for path in sorted(SHAPE.rglob("*")):
        if path.is_file() and path.suffix in (".json", ".md") \
                and path.name not in ("input.json", "input.md", "opportunity.json", "contract.md"):
            try:
                if LIMIT_TEXT.search(path.read_text(errors="replace")):
                    hits.append(str(path))
            except OSError:
                continue
    return hits


def grade_gaps(grade: dict) -> list[str]:
    """Why a grade that says pass is not a whole pass: G1-G8 each once, every applicable one met."""
    rows = [c for c in items(grade.get("criteria")) if isinstance(c, dict)]
    seen = [c.get("id") for c in rows]
    gaps = [f"criterion {g} listed {seen.count(g)} times (must be once)" for g in GRADE_IDS if seen.count(g) != 1]
    gaps += [f"criterion {c.get('id')} applies but is not met" for c in rows
             if c.get("id") in GRADE_IDS and c.get("applies") is not False and c.get("met") is not True]
    return gaps


def pitch_brief(pitch, setup: dict) -> list[str]:
    """What a reader sees first in RESULT.md: problem, solution, fit, each fatal assumption and its first test."""
    if not isinstance(pitch, dict) or pitch.get("status") != "shaped":
        return []
    solution = pitch.get("solution") or {}
    elements = [e for e in items(solution.get("elements")) if isinstance(e, dict)]
    total = round(sum(number(e.get("estimate_builder_weeks")) or 0 for e in elements), 2)
    steps = sorted([s for s in items(pitch.get("verification_plan")) if isinstance(s, dict)
                    and isinstance(s.get("order"), int) and not isinstance(s.get("order"), bool)], key=lambda s: s["order"])
    out = ["## Pitch in brief", f"Problem: {text((pitch.get('problem') or {}).get('statement'))}", "",
           f"Solution: {text(solution.get('summary'))}", "",
           f"Fit: {total} of {setup.get('capacity')} builder-weeks in {len(elements)} element(s); "
           f"{len(items(pitch.get('scope_cuts')))} scope cut(s).", ""]
    for a in items(pitch.get("assumptions")):
        if isinstance(a, dict) and a.get("fatal") is True:
            first = next((s for s in steps if text(a.get("id")) in [text(t) for t in items(s.get("tests"))]), None)
            test = (f"step {first.get('order')} {first.get('id')} ({first.get('cost')}"
                    f"{', owner approval' if first.get('needs_owner_approval') else ''})") if first else "none"
            out.append(f"- Fatal assumption {a.get('id')}: {text(a.get('text'))} First test: {test}.")
    return out + [""]


def finalize() -> int:
    setup = load_json(SHAPE / "setup.json")
    inp = load_json(SHAPE / "input.json") or {}
    if not isinstance(setup, dict):
        raise SystemExit("No setup.json: setup did not run")
    result = {"schema": "shape_mvp.result/1", "case_id": setup.get("case_id"), "setup_status": setup.get("status"),
              "model_status": None, "check_verdict": None, "grade_verdict": None, "grade_status_view": None,
              "problems": [], "reasons": [], "unblock_needs": [], "owner_input_gaps": setup.get("owner_input_gaps", []),
              "owner_questions": [], "fixture_values": setup.get("fixture_values", [])}
    pitch = None
    if setup.get("status") != "ready_to_shape":
        result["final_status"] = "blocked"
        result["reasons"] = [p["code"] + ": " + p["message"] for p in setup.get("problems", [])]
        result["unblock_needs"] = [p["unblock"] for p in setup.get("problems", []) if p.get("unblock")]
        lines = [f"# Shaping result: {text(inp.get('title')) if isinstance(inp, dict) else ''}", "",
                 "Final status: blocked (input contract; no model was called)", NOT_APPROVAL, "", "## Why blocked"]
        lines += [f"- {r}" for r in result["reasons"]] + ["", "## What would unblock it"]
        lines += [f"- {r}" for r in result["unblock_needs"]] + [""]
        (SHAPE / "pitch.md").write_text("\n".join(lines))
    else:
        level = "shaped"
        expected = {"draft": SHAPE / "draft" / "pitch.json", "critique": SHAPE / "critique.json",
                    "revise": SHAPE / "pitch.json", "check": SHAPE / "check.json", "grade": SHAPE / "grade.json"}
        for step, path in expected.items():
            if load_json(path) is None:
                result["problems"].append(f"process: {step} did not write {path} (missing or not JSON)")
                level = "revise"
        for path in limit_hits():
            result["problems"].append(f"process: usage-limit text in {path}")
            level = "revise"
        pitch = load_json(SHAPE / "pitch.json")
        check = load_json(SHAPE / "check.json") or {}
        grade = load_json(SHAPE / "grade.json") or {}
        model = pitch.get("status") if isinstance(pitch, dict) else None
        result.update(model_status=model, check_verdict=check.get("verdict"), grade_verdict=grade.get("verdict"),
                      grade_status_view=grade.get("status_view"))
        if model not in ORDER or model == "revise":
            result["problems"].append(f"model: final pitch status {model!r} (must be shaped or blocked)")
            level = "revise"
        elif ORDER[model] < ORDER[level]:
            level = model
        if check.get("verdict") != "pass":
            result["problems"] += ["check: " + p.get("code", "") + ": " + p.get("message", "")
                                   for p in items(check.get("problems")) if isinstance(p, dict)] or ["check: no pass"]
            level = min(level, "revise", key=ORDER.get)
        if grade.get("verdict") != "pass":
            result["problems"] += ["grade: " + text(i) for i in items(grade.get("issues"))] or ["grade: no pass"]
            level = min(level, "revise", key=ORDER.get)
        elif grade_gaps(grade):
            result["problems"] += ["grade: verdict pass but " + g for g in grade_gaps(grade)]
            level = min(level, "revise", key=ORDER.get)
        elif grade.get("status_view") != "agree":
            result["problems"].append(f"grade: verdict pass but status_view {grade.get('status_view')!r} (must be agree)")
            level = min(level, "revise", key=ORDER.get)
        if isinstance(pitch, dict) and model == "blocked":
            blocked = pitch.get("blocked") or {}
            result["reasons"] = [text(r) for r in items(blocked.get("reasons"))]
            result["unblock_needs"] = [text(r) for r in items(blocked.get("unblock_needs"))]
        if isinstance(pitch, dict):
            known = {g.get("id") for g in result["owner_input_gaps"]}
            result["owner_questions"] = [{"id": text(g.get("id")), "needed": text(g.get("needed")), "why": text(g.get("why"))}
                                         for g in items(pitch.get("owner_input_gaps"))
                                         if isinstance(g, dict) and g.get("id") not in known]
        result["final_status"] = level
    lines = [f"# Shaping result: {text(inp.get('title')) if isinstance(inp, dict) else ''} ({result['case_id']})", "",
             f"Final status: {result['final_status']}", NOT_APPROVAL, "",
             f"Setup: {result['setup_status']}. Model: {result['model_status']}. Check: {result['check_verdict']}. "
             f"Grade: {result['grade_verdict']} (status view: {result['grade_status_view']}).", ""]
    if result["fixture_values"]:
        lines += ["TEST FIXTURE values: " + "; ".join(result["fixture_values"]), ""]
    for title, rows in (("Problems", result["problems"]), ("Why blocked", result["reasons"]),
                        ("What would unblock it", result["unblock_needs"])):
        if rows:
            lines += [f"## {title}"] + [f"- {r}" for r in rows] + [""]
    lines += pitch_brief(pitch, setup)
    if result["owner_input_gaps"]:
        lines += ["## Owner inputs missing from the input"] + [f"- {g['id']}: {g['needed']}"
                                                               for g in result["owner_input_gaps"]] + [""]
    if result["owner_questions"]:
        lines += ["## Owner decisions the pitch raises"] + [f"- {g['id']}: {g['needed']}"
                                                            for g in result["owner_questions"]] + [""]
    files = [f"state/shape/{name}" for name in ("pitch.md", "critique.md", "check.json", "grade.md")
             if (SHAPE / name).exists()]
    lines += ["Files: " + (", ".join(files) or "none") + ".", ""]
    (SHAPE / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    (SHAPE / "RESULT.md").write_text("\n".join(lines))
    print(json.dumps({"status": "completed", "final_status": result["final_status"], "case_id": result["case_id"],
                      "result_path": "state/shape/RESULT.md", "pitch_path": "state/shape/pitch.md",
                      "problems": result["problems"]}))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "input":
        return run_input(Path(argv[1]))
    if argv and argv[0] == "pitch":
        rest = argv[1:]
        stage = "final"
        if "--stage" in rest:
            i = rest.index("--stage")
            stage = rest[i + 1] if i + 1 < len(rest) else ""
            rest = rest[:i] + rest[i + 2:]
        if stage not in ("draft", "final"):
            raise SystemExit("--stage must be draft or final")
        return run_pitch(Path(rest[0]) if rest else SHAPE / "pitch.json", stage)
    if argv and argv[0] == "finalize":
        return finalize()
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
