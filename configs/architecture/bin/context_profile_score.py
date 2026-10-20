#!/usr/bin/env python3
"""Score context profiles against a known case's answer key (System architecture, queue #122, 2026-10-20).

Deterministic: no model, standard library only. A key (configs/architecture/fixtures/context_profile/known/
<case>/key.json, written before any model run) holds a reference profile and what to look for: the material
facts with the quote anchors that may carry each, the material unknowns, the hard constraints, the ranked
goals, the fields the brief leaves unknown, and traps (text that must not carry a given kind of item).
Matching is by text, never by a model: an item carries a fact when its quote contains one of the fact's
anchors, compared the way the checker compares quotes (context_profile_check.norm).

  context_profile_score.py --case DIR PROFILE.json      one profile against DIR/key.json and DIR/brief.md;
                                                        a planted file (a whole profile, or edits to the
                                                        key's reference profile) passes when it causes
                                                        exactly the failures it expects
  context_profile_score.py --case DIR --self            the key's own reference profile: must score 100%
  context_profile_score.py --case DIR --runs P1 P2 P3   several runs of one case: each scored, and whether
                                                        they agree (bar B5)
  context_profile_score.py --pool SCORE.json ...        one run's case scores pooled: bars B0-B4, B7-B10

Every mode lints the key first (anchors in the brief, the brief's sha256, ids, sections); a broken key
stops the run. Failure reasons and the bars: STANDARD.md, "The scorer" and "Bars".
Exit 0 = clean (no failure / consistent / bars met), 1 = not, 2 = cannot run (bad file, broken key).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_checker():
    spec = importlib.util.spec_from_file_location("context_profile_check", HERE / "context_profile_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cpc = _load_checker()

CATEGORIES = ("idea_stage", "startup_paying", "growing_b2b_saas", "large_consumer", "small_high_risk",
              "large_simple", "conflicting_priorities", "missing_budget_workload", "projected_as_observed",
              "misleading_claim", "privacy_vs_cost", "internal_tool_deadline")
FACT_SECTIONS = tuple(s for s in cpc.SECTIONS if s not in ("product", "privacy.sensitivity", "constraints", "goals"))
# Fields a brief can leave open (key fields_unknown): every fact field but maturity.evidence.
OPEN_FIELDS = tuple(s for s in (*cpc.LIST_FACTS, *cpc.WORKLOAD, *cpc.SCALAR_FACTS, "privacy.sensitivity")
                    if s != "maturity.evidence")
# What an unknown may name in its field: the contract's unknown.field enum (a test holds them equal).
UNKNOWN_FIELDS = ("maturity.stage", *OPEN_FIELDS, "constraints", "goals")
TRAP_SECTIONS = tuple(s for s in cpc.SECTIONS if s != "product")
# Checker reasons that mean a fact was made up, not just badly formed.
INVENTING = ("quote_not_in_brief", "number_not_in_quote", "observed_not_quoted")
PLANTED_FORMAT = "context_profile_planted/v1"
COMPONENTS = ("facts", "unknowns", "constraints", "goals", "goal_order", "maturity", "sensitivity",
              "unknown_fields", "no_invention")
RECALL_BAR, ORDER_BAR = 0.95, 0.90


class BrokenKey(Exception):
    """The key is broken: fix the key, not the profile."""


# ---------------------------------------------------------------- the key

def _anchors(entry: dict, where: str, problems: list[str]) -> list[str]:
    anchors = entry.get("anchors")
    if not isinstance(anchors, list) or not anchors or not all(isinstance(a, str) and a.strip() for a in anchors):
        problems.append(f"{where}: anchors must be a non-empty list of text")
        return []
    return anchors


def lint_key(key: object, brief_text: str, brief_sha256: str) -> list[str]:
    """Every way the key itself is broken; the scorer refuses to score with a broken key."""
    if not isinstance(key, dict) or key.get("key") != cpc.KEY_FORMAT:
        return [f"not a key: needs \"key\": \"{cpc.KEY_FORMAT}\""]
    problems: list[str] = []
    brief = cpc.norm(brief_text)
    if key.get("brief_sha256") != brief_sha256:
        problems.append(f"brief_sha256 {key.get('brief_sha256')} is not the brief's ({brief_sha256})")
    for name in ("case_id", "tests"):
        if not isinstance(key.get(name), str) or not key[name].strip():
            problems.append(f"{name} is missing")
    if key.get("category") not in CATEGORIES:
        problems.append(f"category {key.get('category')!r} is not one of {', '.join(CATEGORIES)}")
    for name, allowed in (("maturity", cpc.STAGES), ("sensitivity", (*cpc.LEVELS, "unknown"))):
        accepted = (key.get(name) or {}).get("accepted") if isinstance(key.get(name), dict) else None
        if not isinstance(accepted, list) or not accepted or any(a not in allowed for a in accepted):
            problems.append(f"{name}.accepted must list values from {', '.join(allowed)}")
    if not isinstance(key.get("profile"), dict):
        problems.append("profile (the reference profile) is missing")

    seen: set[str] = set()
    texts: list[tuple[str, str]] = []
    for group in ("facts", "constraints", "goals", "unknowns", "traps"):
        entries = key.get(group)
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            problems.append(f"{group} must be a list of objects")
            continue
        for i, entry in enumerate(entries):
            where = f"{group}[{i}]"
            ident = entry.get("id")
            if not isinstance(ident, str) or ident in seen:
                problems.append(f"{where}: id {ident!r} missing or used twice")
            seen.add(str(ident))
            if group != "unknowns":
                texts += [(f"{where} ({ident})", a) for a in _anchors(entry, where, problems)]
            if group == "facts":
                sections = entry.get("in")
                if not isinstance(sections, list) or not sections or any(s not in FACT_SECTIONS for s in sections):
                    problems.append(f"{where}: in must list sections from {', '.join(FACT_SECTIONS)}")
                if "value" in entry and not cpc._is_type(entry["value"], "number"):
                    problems.append(f"{where}: value must be a number")
            if group == "goals":
                criteria = entry.get("criterion")
                criteria = criteria if isinstance(criteria, list) else [criteria]
                if not criteria or any(c not in cpc.CRITERIA for c in criteria):
                    problems.append(f"{where}: criterion {entry.get('criterion')!r} is not a contract criterion (or a list of them)")
                if not cpc._is_type(entry.get("rank"), "integer"):
                    problems.append(f"{where}: rank must be an integer")
            if group == "unknowns":
                terms = entry.get("terms")
                if entry.get("field") is None and terms is None:
                    problems.append(f"{where}: needs a field, terms or both")
                if entry.get("field") is not None and entry["field"] not in UNKNOWN_FIELDS:
                    problems.append(f"{where}: field {entry['field']!r} is not a contract field")
                if terms is not None and (not isinstance(terms, list) or not terms or not all(
                        isinstance(g, list) and g and all(isinstance(t, str) and t.strip() for t in g) for g in terms)):
                    problems.append(f"{where}: terms must be a non-empty list of non-empty lists of text")
            if group == "traps":
                if not isinstance(entry.get("reason"), str) or not entry["reason"]:
                    problems.append(f"{where}: reason is missing")
                forbidden = entry.get("forbidden_in")
                if not isinstance(forbidden, list) or not forbidden or any(s not in TRAP_SECTIONS for s in forbidden):
                    problems.append(f"{where}: forbidden_in must list sections from {', '.join(TRAP_SECTIONS)}")

    goals = [g for g in key.get("goals") or [] if isinstance(g, dict) and cpc._is_type(g.get("rank"), "integer")]
    if sorted(g["rank"] for g in goals) != list(range(1, len(goals) + 1)):
        problems.append("goals: ranks must be 1 to n, each once")
    accepted = (key.get("goal_order") or {}).get("accepted_top3") if isinstance(key.get("goal_order"), dict) else None
    if key.get("goal_order") is not None and (not isinstance(accepted, list) or not accepted or not all(
            isinstance(seq, list) and 0 < len(seq) <= 3 and all(c in cpc.CRITERIA for c in seq) for seq in accepted)):
        problems.append("goal_order.accepted_top3 must list sequences of one to three contract criteria")

    unknown_fields = key.get("fields_unknown")
    if not isinstance(unknown_fields, list) or not all(isinstance(f, dict) for f in unknown_fields):
        problems.append("fields_unknown must be a list of objects")
        unknown_fields = []
    for i, entry in enumerate(unknown_fields):
        if entry.get("field") not in OPEN_FIELDS:
            problems.append(f"fields_unknown[{i}]: field {entry.get('field')!r} is not a fact field")
        open_anchors = entry.get("open_anchors", [])
        if not isinstance(open_anchors, list) or not all(isinstance(a, str) and a.strip() for a in open_anchors):
            problems.append(f"fields_unknown[{i}]: open_anchors must be a list of text")
        else:
            texts += [(f"fields_unknown[{i}]", a) for a in open_anchors]
    open_fields = {e.get("field") for e in unknown_fields}
    for fact in key.get("facts") or []:
        if isinstance(fact, dict) and isinstance(fact.get("in"), list) and open_fields & set(fact["in"]):
            problems.append(f"fact {fact.get('id')}: may sit in {sorted(open_fields & set(fact['in']))}, which fields_unknown says the brief leaves open")

    problems += [f"{where}: anchor {text!r} is not in the brief" for where, text in texts if cpc.norm(text) not in brief]
    return problems


# ---------------------------------------------------------------- one profile

def _fail(reason: str, ref: str, detail: str) -> dict:
    return {"reason": reason, "ref": ref, "detail": detail}


def _rate(right: int, total: int) -> float:
    return round(right / total, 4) if total else 1.0


def _carries(quote: str, anchors: list[str]) -> bool:
    return any(cpc.norm(anchor) in quote for anchor in anchors)


def criteria_of(goal: dict) -> list[str]:
    """A key goal's accepted criteria: one name, or a list where the brief fits more than one."""
    criterion = goal["criterion"]
    return criterion if isinstance(criterion, list) else [criterion]


def _states_value(item, expected: float) -> bool:
    values: set[float] = set()
    for text in item.texts:
        for _token, found in cpc.number_tokens(text, quote_side=True):
            values |= found
    return cpc._canon(float(expected)) in values


def score(key: dict, profile: object, brief_text: str, validator) -> dict:
    """One profile against one key: metrics, failures and score_pct. The key must already lint clean."""
    checked = cpc.check(profile, brief_text, key["brief_sha256"], validator)
    failures = [_fail(f"checker:{e['reason']}", e["path"], e["detail"]) for e in checked["errors"]]
    invented = sum(1 for e in checked["errors"] if e["reason"] in INVENTING)
    items = list(cpc.iter_items(profile))
    quoted = [(item, cpc.norm(item.quote)) for item in items if item.kind == "quote" and item.quote]

    # Material facts: quoted in a section the key allows, with the key's number when it names one.
    captured: list[str] = []
    for fact in key["facts"]:
        hits = [item for item, quote in quoted if _carries(quote, fact["anchors"])]
        placed = [item for item in hits if item.section in fact["in"]]
        if placed and ("value" not in fact or any(_states_value(item, fact["value"]) for item in placed)):
            captured.append(fact["id"])
        elif placed:
            failures.append(_fail("fact_wrong_value", fact["id"],
                                  f"quoted in {placed[0].path} without the value {fact['value']}"))
        elif hits:
            failures.append(_fail("fact_misplaced", fact["id"],
                                  f"quoted in {', '.join(sorted({i.section for i in hits}))}; belongs in {' or '.join(fact['in'])}"))
        else:
            failures.append(_fail("fact_missed", fact["id"],
                                  f"no item in {' or '.join(fact['in'])} quotes {fact['anchors'][0]!r}"))

    # Fields the brief leaves open stay open.
    open_kept = 0
    for entry in key["fields_unknown"]:
        node = cpc.at(profile, entry["field"])
        filled = [n for n in node if isinstance(n, dict)] if isinstance(node, list) else [node] if isinstance(node, dict) else []
        if not filled:
            open_kept += 1
        for n in filled:
            source = n.get("source") if isinstance(n.get("source"), dict) else {}
            quote = source.get("quote") if isinstance(source.get("quote"), str) else ""
            if source.get("kind") == "quote" and _carries(cpc.norm(quote), entry.get("open_anchors", [])):
                failures.append(_fail("open_field_filled", entry["field"],
                                      "the brief says this is open: leave it unknown and name it in unknowns"))
            elif source.get("kind") == "quote":
                invented += 1
                failures.append(_fail("unsupported_fill", entry["field"],
                                      f"the brief gives no {entry['field']}; the quote cannot carry it: {quote[:120]!r}"))
            else:
                invented += 1
                failures.append(_fail("guessed_unknown", entry["field"],
                                      f"the brief gives no {entry['field']}: unknown, never guessed"))

    # Material unknowns: flagged material, matched by field or by every term group.
    asked = []
    for u in profile.get("unknowns", []) if isinstance(profile, dict) and isinstance(profile.get("unknowns"), list) else []:
        if isinstance(u, dict):
            said = [u.get("question"), u.get("why_it_matters"), *(u.get("decisions_affected") or [])]
            asked.append((u, cpc.norm(" ".join(s for s in said if isinstance(s, str)))))
    flagged: list[str] = []
    for ku in key["unknowns"]:
        matches = [u for u, text in asked
                   if (ku.get("field") and u.get("field") == ku["field"])
                   or (ku.get("terms") and all(any(cpc.norm(t) in text for t in group) for group in ku["terms"]))]
        if any(u.get("material") is True for u in matches):
            flagged.append(ku["id"])
        elif matches:
            failures.append(_fail("unknown_not_material", ku["id"], "named, but not marked material"))
        else:
            hint = ku.get("field") or " + ".join("/".join(group) for group in ku["terms"])
            failures.append(_fail("unknown_not_flagged", ku["id"], f"no material unknown about {hint}"))

    # Hard constraints stay constraints; preferences stay goals with their criterion.
    c_quotes = [quote for item, quote in quoted if item.section == "constraints"]
    g_items = [(item, quote) for item, quote in quoted if item.section == "goals"]
    constraint_status: dict[str, str] = {}
    for kc in key["constraints"]:
        in_c = any(_carries(q, kc["anchors"]) for q in c_quotes)
        in_g = any(_carries(q, kc["anchors"]) for _, q in g_items)
        status = "constraint" if in_c and not in_g else "both" if in_c else "goal" if in_g else "missing"
        constraint_status[kc["id"]] = status
        if status != "constraint":
            reason = {"both": "constraint_also_goal", "goal": "constraint_as_goal", "missing": "constraint_missing"}[status]
            failures.append(_fail(reason, kc["id"], f"hard constraint {kc['anchors'][0]!r}: {status}"))
    goal_status: dict[str, str] = {}
    for kg in key["goals"]:
        as_goal = [item for item, q in g_items if _carries(q, kg["anchors"])]
        in_c = any(_carries(q, kg["anchors"]) for q in c_quotes)
        status = "goal" if as_goal and not in_c else "both" if as_goal else "constraint" if in_c else "missing"
        if status == "goal" and not any(item.node.get("criterion") in criteria_of(kg) for item in as_goal):
            status = "wrong_criterion"
        goal_status[kg["id"]] = status
        if status != "goal":
            reason = {"both": "goal_also_constraint", "constraint": "goal_as_constraint", "missing": "goal_missing",
                      "wrong_criterion": "goal_wrong_criterion"}[status]
            failures.append(_fail(reason, kg["id"], f"goal {kg['anchors'][0]!r} ({'/'.join(criteria_of(kg))}): {status}"))

    # Goal order: the profile's top three criteria against the key's (any accepted order).
    goals = [g for g in (profile.get("goals") if isinstance(profile, dict) and isinstance(profile.get("goals"), list) else [])
             if isinstance(g, dict) and cpc._is_type(g.get("rank"), "integer")]
    got = [g.get("criterion") for g in sorted(goals, key=lambda g: g["rank"])[:3]]
    accepted = (key.get("goal_order") or {}).get("accepted_top3") or [
        [criteria_of(g)[0] for g in sorted(key["goals"], key=lambda g: g["rank"])[:3]]]
    best = max(accepted, key=lambda seq: sum(1 for i, c in enumerate(seq) if i < len(got) and got[i] == c))
    agree = sum(1 for i, c in enumerate(best) if i < len(got) and got[i] == c)
    if agree < len(best):
        failures.append(_fail("goal_order", "goals", f"top three {got}; the key accepts {accepted}"))

    stage = profile.get("maturity", {}).get("stage") if isinstance(profile, dict) and isinstance(profile.get("maturity"), dict) else None
    if stage not in key["maturity"]["accepted"]:
        failures.append(_fail("maturity_mismatch", "maturity.stage", f"{stage!r}; the key accepts {key['maturity']['accepted']}"))
    sensitivity = cpc.at(profile, "privacy.sensitivity")
    level = sensitivity.get("level") if isinstance(sensitivity, dict) else sensitivity
    if level not in key["sensitivity"]["accepted"]:
        failures.append(_fail("sensitivity_mismatch", "privacy.sensitivity", f"{level!r}; the key accepts {key['sensitivity']['accepted']}"))

    # Traps: text the brief uses for something else must not carry these kinds of item.
    for trap in key["traps"]:
        for item, quote in quoted:
            if item.section in trap["forbidden_in"] and _carries(quote, trap["anchors"]):
                invented += 1
                failures.append(_fail(f"trap:{trap['reason']}", trap["id"], f"{item.path} stands on {trap['anchors'][0]!r}"))

    facts = {"captured": len(captured), "total": len(key["facts"]), "captured_ids": captured}
    unknowns = {"flagged": len(flagged), "total": len(key["unknowns"]), "flagged_ids": flagged}
    constraints = {"right": sum(s == "constraint" for s in constraint_status.values()), "total": len(constraint_status),
                   "status": constraint_status}
    goals_ = {"right": sum(s == "goal" for s in goal_status.values()), "total": len(goal_status), "status": goal_status}
    order = {"agree": agree, "total": len(best), "got": got, "accepted": accepted}
    rates = {
        "facts": _rate(facts["captured"], facts["total"]),
        "unknowns": _rate(unknowns["flagged"], unknowns["total"]),
        "constraints": _rate(constraints["right"], constraints["total"]),
        "goals": _rate(goals_["right"], goals_["total"]),
        "goal_order": _rate(agree, len(best)),
        "maturity": 1.0 if stage in key["maturity"]["accepted"] else 0.0,
        "sensitivity": 1.0 if level in key["sensitivity"]["accepted"] else 0.0,
        "unknown_fields": _rate(open_kept, len(key["fields_unknown"])),
        "no_invention": 1.0 if invented == 0 else 0.0,
    }
    return {
        "case_id": key["case_id"],
        "checker_ok": checked["ok"],
        "facts": facts,
        "unknowns": unknowns,
        "constraints": constraints,
        "goals": goals_,
        "goal_order": order,
        "maturity": {"got": stage, "accepted": key["maturity"]["accepted"]},
        "sensitivity": {"got": level, "accepted": key["sensitivity"]["accepted"]},
        "unknown_fields": {"kept": open_kept, "total": len(key["fields_unknown"])},
        "invented": invented,
        "rates": rates,
        "score_pct": round(100 * sum(rates[c] for c in COMPONENTS) / len(COMPONENTS), 1),
        "failures": failures,
        "clean": not failures,
    }


# ---------------------------------------------------------------- several runs, several cases

def consistency(results: list[dict]) -> dict:
    """Bar B5: do runs of one case give the same answers?"""
    dims = {
        "maturity": [r["maturity"]["got"] for r in results],
        "sensitivity": [r["sensitivity"]["got"] for r in results],
        "constraints": [r["constraints"]["status"] for r in results],
        "goals": [r["goals"]["status"] for r in results],
        "unknowns_flagged": [sorted(r["unknowns"]["flagged_ids"]) for r in results],
        "goal_order_top3": [r["goal_order"]["got"] for r in results],
    }
    differs = [name for name, values in dims.items() if any(v != values[0] for v in values)]
    sets = [set(r["facts"]["captured_ids"]) for r in results]
    union = set().union(*sets)
    agreement = round(len(set.intersection(*sets)) / len(union), 4) if union else 1.0
    return {"runs": len(results), "consistent": not differs, "differs": differs, "facts_agreement": agreement}


def pool(results: list[dict]) -> dict:
    """One run's scores over the case set, against bars B0-B4 and B7-B10 (B5: --runs; B6: run records)."""
    ids = [r["case_id"] for r in results]
    total = {name: sum(r[name][part] for r in results) for name, part in
             (("facts", "total"), ("unknowns", "total"), ("constraints", "total"), ("goal_order", "total"))}
    recall = _rate(sum(r["facts"]["captured"] for r in results), total["facts"])
    order = _rate(sum(r["goal_order"]["agree"] for r in results), total["goal_order"])
    promoted = [f"{r['case_id']} {f['ref']}" for r in results for f in r["failures"]
                if f["reason"] in ("goal_as_constraint", "goal_also_constraint")]
    bars = {
        "B0_contract": all(r["checker_ok"] for r in results),
        "B1_no_invented": sum(r["invented"] for r in results) == 0,
        "B2_fact_recall_95": recall >= RECALL_BAR,
        "B3_unknowns_flagged": sum(r["unknowns"]["flagged"] for r in results) == total["unknowns"],
        "B4_constraints_classified": sum(r["constraints"]["right"] for r in results) == total["constraints"],
        "B7_maturity": all(r["maturity"]["got"] in r["maturity"]["accepted"] for r in results),
        "B8_sensitivity": all(r["sensitivity"]["got"] in r["sensitivity"]["accepted"] for r in results),
        "B9_goal_order_90": order >= ORDER_BAR,
        "B10_goals_stay_goals": not promoted,
    }
    return {
        "cases": len(results),
        "duplicate_cases": sorted({i for i in ids if ids.count(i) > 1}),
        "fact_recall": recall,
        "goal_order": order,
        "invented": sum(r["invented"] for r in results),
        "bars": bars,
        "meets_bars": all(bars.values()) and len(set(ids)) == len(ids),
        "not_measured_here": {"B5_consistent_runs": "--runs, per case", "B6_cost_and_time": "the runs' records"},
        "per_case": [{"case_id": r["case_id"], "score_pct": r["score_pct"], "fact_recall": r["rates"]["facts"],
                      "failures": [f["reason"] for f in r["failures"]]} for r in results],
    }


# ---------------------------------------------------------------- command line

def load_case(case_dir: Path) -> tuple[dict, str, str]:
    """(key, brief text, brief sha256) of a known case; raises BrokenKey when the key is broken."""
    brief_bytes = (case_dir / "brief.md").read_bytes()
    key = json.loads((case_dir / "key.json").read_text(encoding="utf-8"))
    brief_text, brief_sha = brief_bytes.decode("utf-8"), cpc.sha256_bytes(brief_bytes)
    problems = lint_key(key, brief_text, brief_sha)
    if problems:
        raise BrokenKey(f"{case_dir / 'key.json'} is broken: " + "; ".join(problems))
    return key, brief_text, brief_sha


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


class BadPlant(Exception):
    """A planted file whose edits cannot be applied: fix the planted file."""


def apply_edits(base: object, edits: object) -> object:
    """A copy of base with a planted file's edits applied, in order.

    Each edit is {op: set|remove|append, path: [key or index, ...], value?}: set replaces (or adds) the
    value at path, remove deletes it, append adds value at the end of the list at path.
    """
    import copy
    profile = copy.deepcopy(base)
    if not isinstance(edits, list) or not edits:
        raise BadPlant("edits must be a non-empty list")
    for n, edit in enumerate(edits):
        if not isinstance(edit, dict) or edit.get("op") not in ("set", "remove", "append"):
            raise BadPlant(f"edits[{n}]: op must be set, remove or append")
        path = edit.get("path")
        if not isinstance(path, list) or not path:
            raise BadPlant(f"edits[{n}]: path must be a non-empty list")
        if edit["op"] != "remove" and "value" not in edit:
            raise BadPlant(f"edits[{n}]: {edit['op']} needs a value")
        try:
            parent = profile
            for step in path[:-1]:
                parent = parent[step]
            last = path[-1]
            if edit["op"] == "set":
                parent[last] = copy.deepcopy(edit["value"])
            elif edit["op"] == "remove":
                del parent[last]
            else:
                parent[last].append(copy.deepcopy(edit["value"]))
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise BadPlant(f"edits[{n}]: path {path} does not fit the profile ({exc!r})") from exc
    return profile


def unwrap(document: object, base: object = None) -> tuple[object, dict | None]:
    """(profile, planted header or None): a planted file carries the failures it must cause and either a
    whole profile or edits to base, the case key's reference profile."""
    if isinstance(document, dict) and document.get("planted") == PLANTED_FORMAT:
        if "edits" in document:
            if "profile" in document:
                raise BadPlant("give a profile or edits, not both")
            return apply_edits(base, document["edits"]), document
        return document.get("profile"), document
    return document, None


def against_plant(result: dict, plant: dict) -> dict:
    """Does the score report exactly the failures the planted file expects, no more and no fewer?"""
    from collections import Counter
    got = Counter((f["reason"], f["ref"]) for f in result["failures"])
    want = Counter((e.get("reason"), e.get("ref")) for e in plant.get("expect") or [] if isinstance(e, dict))
    missing, unexpected = sorted((want - got).elements()), sorted((got - want).elements())
    same_case = plant.get("case_id") == result["case_id"]
    return {"plant_id": plant.get("plant_id"), "same_case": same_case, "expected": len(want),
            "missing": [list(m) for m in missing], "unexpected": [list(u) for u in unexpected],
            "as_expected": same_case and bool(want) and not missing and not unexpected}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score context profiles against a known case's key.")
    parser.add_argument("profiles", type=Path, nargs="*", help="profile(s), or score files with --pool")
    parser.add_argument("--case", type=Path, help="a known case folder (brief.md + key.json)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self", dest="self_check", action="store_true", help="score the key's reference profile")
    mode.add_argument("--runs", action="store_true", help="the profiles are runs of the case: score each, compare")
    mode.add_argument("--pool", action="store_true", help="the files are one run's case scores: pool them")
    parser.add_argument("--schema", type=Path, default=cpc.SCHEMA_PATH)
    args = parser.parse_args(argv)
    try:
        if args.pool:
            if not args.profiles:
                parser.error("--pool needs score files")
            report = pool([_read_json(p) for p in args.profiles])
            ok = report["meets_bars"]
        else:
            if args.case is None:
                parser.error("--case is needed unless --pool")
            key, brief_text, _sha = load_case(args.case)
            validator = cpc.load_validator(args.schema)
            if args.self_check:
                report = score(key, key["profile"], brief_text, validator)
                ok = report["clean"] and report["score_pct"] == 100.0
            elif args.runs:
                if len(args.profiles) < 2:
                    parser.error("--runs needs two or more profiles")
                runs = [score(key, _read_json(p), brief_text, validator) for p in args.profiles]
                report = {"case_id": key["case_id"], "consistency": consistency(runs), "runs": runs}
                ok = report["consistency"]["consistent"] and all(r["clean"] for r in runs)
            else:
                if len(args.profiles) != 1:
                    parser.error("give one profile (or --runs for several)")
                profile, plant = unwrap(_read_json(args.profiles[0]), key["profile"])
                report = score(key, profile, brief_text, validator)
                ok = report["clean"]
                if plant is not None:
                    report["planted"] = against_plant(report, plant)
                    ok = report["planted"]["as_expected"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, BrokenKey, BadPlant, cpc.SchemaError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot run: {exc}"}, ensure_ascii=False))
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
