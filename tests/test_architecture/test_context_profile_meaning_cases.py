"""Development gold for meaning, not acceptance (#137, H-CTX-6b).

Independent inventory/lint; no scorer, model, server, private authoring files or sealed
fixtures. A source-bearing fact/measure/item is one atomic claim including its metadata.
Maturity stage, system state, unknown scalars, unknown records and assumptions are also
claims. The JSON pointer names that atomic claim, not every scalar inside its quote.

Run this file as a script to print the same counts embedded in the development README.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "configs/architecture/fixtures/context_profile"
DEV = FIXTURES / "meaning/dev"
LABELS = {"supported", "contradicted", "unsupported", "uncertain"}
BAD = {"contradicted", "unsupported"}
FAMILIES = {f"F{i:02}" for i in range(1, 13)}
TRAPS = {"unit_conversion", "comparator_paraphrase", "reordering", "two_quote_summary"}
LIST_CLAIMS = (
    "maturity.evidence", "current_system.items", "external_systems", "performance.targets",
    "workload.observed", "workload.projected", "workload.peaks", "privacy.data_categories",
    "privacy.retention", "privacy.sharing", "privacy.jurisdictions_or_rules",
    "security.requirements", "security.threats", "security.compliance", "team.skills",
    "team.operating_capacity", "constraints", "goals", "unknowns", "assumptions",
)
SCALAR_CLAIMS = (
    "reliability.availability", "reliability.data_loss_tolerance", "reliability.recovery_time",
    "privacy.sensitivity", "team.size", "budget.build", "budget.run_monthly",
)
# Byte pins copied from #133's EXPECTED.json, never regenerated from these fixtures.
CLEAN_13 = "2cd525f6f980886a9fba9a7ecf89a3376e40f7461b01260525538f898cf56023"
IMPORT_PINS = {
    "p01-comparator-clean": CLEAN_13,
    "p01-comparator-bad": "d46b9c7d77d39298d91c34eb82c6ff06cf1b43985e66be7cc474e1ff4bfbefdd",
    "p02-unit-clean": CLEAN_13,
    "p02-unit-bad": "c380e08732f16976a65799c93372bae0ef59f02837b968e0aa44da7c5b295724",
    "p03-loss-clean": CLEAN_13,
    "p03-loss-bad": "27ec0bc5f0398dc2b9ae0062572ee382f90331cade32acae2e9a483a7b8c6d7f",
    "p04-security-clean": CLEAN_13,
    "p04-security-bad": "c7a0b68d8cc5f0eee5d131927fee6421de7c4174ffade40b164d20f64600a4cb",
    "p05-unknown-clean": "28855849988f97857bc2b66ddc9e38e3e13785910c5a8d577e2d51eff53c826c",
    "p05-unknown-bad": "a7c55067e2f392b159d4d943160ce43aa15e42d83b7ed78c31b43fc143ad7330",
}
INTENDED = {
    "p01-comparator": ("/constraints/0", ["$.constraints[0].text"], "F01"),
    "p02-unit": ("/performance/targets/0", ["$.performance.targets[0].unit"], "F02"),
    "p03-loss": ("/reliability/data_loss_tolerance", ["$.reliability.data_loss_tolerance.value"], "F04"),
    "p04-security": ("/security/requirements/1", ["$.security.requirements[1]"], "F06"),
    "p05-unknown": ("/unknowns/4", ["$.unknowns[4].question", "$.unknowns[4].why_it_matters",
                                  "$.unknowns[4].decisions_affected"], "F10"),
}


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _at(profile, dotted):
    value = profile
    for part in dotted.split("."):
        value = value[part]
    return value


def inventory(profile):
    """Written independently of the private generator and any candidate meaning checker."""
    claims = {"/product": profile["product"], "/maturity/stage": profile["maturity"]["stage"],
              "/current_system/state": {"state": profile["current_system"]["state"],
                                        "source": profile["current_system"].get("source")}}
    for field in SCALAR_CLAIMS:
        claims["/" + field.replace(".", "/")] = _at(profile, field)
    for field in LIST_CLAIMS:
        for index, value in enumerate(_at(profile, field)):
            claims[f'/{field.replace(".", "/")}/{index}'] = value
    return claims


def _span(reference, path, claim):
    if path == "/maturity/stage":
        evidence = reference["maturity"]["evidence"]
        source = evidence[0].get("source", {}) if evidence else {}
    else:
        source = (claim.get("source", {}) or {}) if isinstance(claim, dict) else {}
    return source["quote"] if source.get("kind") == "quote" else "none"


def _documents():
    for folder in sorted(p for p in DEV.iterdir() if p.is_dir()):
        labels = _json(folder / "labels.json")
        yield folder, _json(folder / "profile.json"), labels


def lint_labels(profile, reference, labels, brief):
    current, original = inventory(profile), inventory(reference)
    rows = labels["claims"]
    paths = [row["path"] for row in rows]
    assert len(paths) == len(set(paths)), "duplicate claim label"
    assert set(paths) == set(current), "claim dropped or invented"
    changed = {p for p in current if p not in original or current[p] != original[p]}
    removed = set(original) - set(current)
    assert labels["changed_paths"] == sorted(changed)
    assert labels["removed_paths"] == sorted(removed)
    assert len(changed | removed) <= 3, "more than three claim-root edits"
    assert not any(a != b and b.startswith(a + "/") for a in changed for b in changed)
    assert labels["reference_sha256"] == _canonical_sha(reference)
    assert labels["profile_sha256"] == _canonical_sha(profile)
    for row in rows:
        path = row["path"]
        assert row["label"] in LABELS
        assert row["family"] in FAMILIES if row["label"] in BAD else row["family"] is None
        assert isinstance(row["rationale"], str) and row["rationale"].strip()
        assert row["origin"] in {"hand", "reference"}
        if path in changed:
            assert row["origin"] == "hand", "changed claim lacks a hand label"
        if row["origin"] == "reference":
            assert path in original and current[path] == original[path]
            assert row["label"] == "supported"
            assert row["source_span"] == _span(reference, path, original[path])
        if "trap" in row:
            assert row["trap"] in TRAPS and row["label"] == "supported" and row["origin"] == "hand"
            if row["trap"] == "two_quote_summary":
                assert len(set(row["supporting_spans"])) >= 2
                assert row["source_span"] in row["supporting_spans"]
    omissions = labels["omissions"]
    obligations = [(o["obligation_kind"], o["obligation_id"]) for o in omissions]
    assert len(obligations) == len(set(obligations))
    accounted = [p for o in omissions for p in o["removed_paths"]]
    assert len(accounted) == len(set(accounted)) and set(accounted) == removed
    for omission in omissions:
        assert omission["label"] == "omission"
        # These variants deliberately omit final goals, not schema-required sections.
        assert omission["obligation_kind"] == "goals"
        ident = omission["obligation_id"]
        goal = next(g for g in reference["goals"] if g["id"] == ident)
        assert all(g["id"] != ident for g in profile["goals"])
        assert omission["source_span"] == goal["source"]["quote"]
        assert omission["rationale"].strip()
        assert len(omission["removed_paths"]) == 1
        assert original[omission["removed_paths"][0]] == goal
    for row in [*rows, *omissions]:
        spans = [row["source_span"], *row.get("supporting_spans", [])]
        for span in spans:
            assert isinstance(span, str) and span
            assert span == "none" or span.encode("utf-8") in brief, "source span is not byte-exact"


def calculate_counts():
    counts = {"authored_variants": 0, "imported_variants": 0, "cases": [], "claims": {},
              "hand_labels": {}, "bad_claims": 0, "traps": {}, "omission_variants": 0,
              "omissions": 0, "families": {}, "by_case": {}, "imported_claims": {}}
    total, hand, traps, imported = Counter(), Counter(), Counter(), Counter()
    families = {f: {"claims": 0, "cases": set()} for f in sorted(FAMILIES)}
    by_case = {}
    for _folder, _profile, labels in _documents():
        if labels["group"] == "imported_133":
            counts["imported_variants"] += 1
            imported.update(row["label"] for row in labels["claims"])
            continue
        counts["authored_variants"] += 1
        case_id = labels["case_id"]
        case = by_case.setdefault(case_id, {"variants": 0, "hand_supported": 0, "bad": 0,
                                            "uncertain": 0, "omissions": 0})
        case["variants"] += 1
        total.update(row["label"] for row in labels["claims"])
        hand.update(row["label"] for row in labels["claims"] if row["origin"] == "hand")
        case["omissions"] += len(labels["omissions"])
        counts["omissions"] += len(labels["omissions"])
        counts["omission_variants"] += bool(labels["omissions"])
        for row in labels["claims"]:
            if row["origin"] == "hand" and row["label"] == "supported":
                case["hand_supported"] += 1
            if row["label"] == "uncertain":
                case["uncertain"] += 1
            if "trap" in row:
                traps[row["trap"]] += 1
            if row["label"] in BAD:
                case["bad"] += 1
                families[row["family"]]["claims"] += 1
                families[row["family"]]["cases"].add(case_id)
    counts.update(cases=sorted(by_case), claims=dict(sorted(total.items())),
                  hand_labels=dict(sorted(hand.items())), traps=dict(sorted(traps.items())),
                  imported_claims=dict(sorted(imported.items())), by_case=dict(sorted(by_case.items())))
    counts["bad_claims"] = sum(total[label] for label in BAD)
    counts["families"] = {f: {"claims": v["claims"], "cases": sorted(v["cases"])} for f, v in families.items()}
    return counts


def test_every_variant_has_one_label_per_claim_and_byte_exact_spans():
    assert DEV.is_dir()
    for folder, profile, labels in _documents():
        assert labels["format"] == "context_profile_meaning_labels/dev-v1"
        assert labels["variant_id"] == folder.name and labels["set"] == "development"
        assert labels["group"] in {"authored", "imported_133"}
        assert {p.name for p in folder.iterdir()} == {"profile.json", "labels.json"}
        known = FIXTURES / "known" / labels["case_id"]
        key = _json(known / "key.json")
        brief = (known / "brief.md").read_bytes()
        assert profile["brief_sha256"] == key["brief_sha256"] == hashlib.sha256(brief).hexdigest()
        lint_labels(profile, key["profile"], labels, brief)


def test_every_variant_still_passes_the_frozen_v2_checker():
    spec = importlib.util.spec_from_file_location("context_profile_check", ROOT / "configs/architecture/bin/context_profile_check.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    validator = checker.load_validator()
    for folder, profile, labels in _documents():
        brief = (FIXTURES / "known" / labels["case_id"] / "brief.md").read_bytes()
        result = checker.check(profile, brief.decode("utf-8"), hashlib.sha256(brief).hexdigest(), validator)
        assert result["ok"], (folder.name, result["errors"])


def test_minimum_sizes_family_spread_and_all_known_cases():
    counts = calculate_counts()
    assert counts["authored_variants"] and counts["imported_variants"] == 10
    assert counts["bad_claims"] >= 60
    assert counts["hand_labels"]["supported"] >= 60
    assert counts["hand_labels"]["uncertain"] >= 15
    assert sum(counts["traps"].values()) >= 20 and set(counts["traps"]) == TRAPS
    assert counts["omission_variants"] >= 8
    assert len(counts["cases"]) == 14
    assert counts["cases"] == sorted(p.name for p in (FIXTURES / "known").iterdir() if p.is_dir())
    assert set(counts["families"]) == FAMILIES
    for family, spread in counts["families"].items():
        assert spread["claims"] >= 4 and len(spread["cases"]) >= 3, (family, spread)
    # Generated reference rows cannot inflate the hand-labelled good/bad/uncertain minimums.
    for _folder, _profile, labels in _documents():
        if labels["group"] == "authored":
            for row in labels["claims"]:
                if row["origin"] == "hand":
                    assert row["path"] in labels["changed_paths"]


def test_imported_133_profiles_match_external_pins_and_intended_paths():
    imports = {folder.name: (folder, labels) for folder, _profile, labels in _documents()
               if labels["group"] == "imported_133"}
    assert set(imports) == set(IMPORT_PINS)
    for name, (folder, labels) in imports.items():
        pin = labels["import"]
        assert hashlib.sha256((folder / "profile.json").read_bytes()).hexdigest() == IMPORT_PINS[name]
        assert pin["sha256"] == IMPORT_PINS[name] and pin["file"] == name + ".json"
        pair, side = name.rsplit("-", 1)
        root, leaves, family = INTENDED[pair]
        assert labels["case_id"] == ("k07-conflict-marketplace" if pair == "p05-unknown" else "k13-performance-docks")
        assert pin["fault_claim_path"] == root and pin["intended_fault_paths"] == leaves and pin["side"] == side
        rows = {row["path"]: row for row in labels["claims"]}
        if side == "bad":
            assert rows[root]["label"] in BAD and rows[root]["family"] == family
        elif pair == "p04-security":
            assert root not in rows  # the clean file has no invented appended security control
        else:
            assert rows[root]["label"] == "supported"
        if pair == "p05-unknown":
            # #135's retention fix postdates BOTH pinned #133 profiles. Do not bless that old flaw.
            assert rows["/unknowns/6"]["label"] == "contradicted"
            assert rows["/unknowns/6"]["family"] == "F09"


def test_readme_counts_and_every_variant_description_match_the_fixture_inventory():
    readme = (DEV / "README.md").read_text(encoding="utf-8")
    block = readme.split("<!-- computed-counts:start -->\n```json\n", 1)[1]
    recorded = json.loads(block.split("\n```\n<!-- computed-counts:end -->", 1)[0])
    assert recorded == calculate_counts()
    for folder, _profile, _labels in _documents():
        assert f"| {folder.name} |" in readme


def test_lint_refuses_dropped_duplicate_unlabelled_and_nonexact_claims():
    folder = DEV / "f01-k13"
    profile, labels = _json(folder / "profile.json"), _json(folder / "labels.json")
    known = FIXTURES / "known" / labels["case_id"]
    reference, brief = _json(known / "key.json")["profile"], (known / "brief.md").read_bytes()
    broken = []
    dropped = copy.deepcopy(labels)
    dropped["claims"].pop()
    broken.append(dropped)
    duplicate = copy.deepcopy(labels)
    duplicate["claims"].append(copy.deepcopy(duplicate["claims"][0]))
    broken.append(duplicate)
    unlabelled = copy.deepcopy(labels)
    next(r for r in unlabelled["claims"] if r["path"] == "/constraints/0")["origin"] = "reference"
    broken.append(unlabelled)
    no_family = copy.deepcopy(labels)
    next(r for r in no_family["claims"] if r["path"] == "/constraints/0")["family"] = None
    broken.append(no_family)
    nonexact = copy.deepcopy(labels)
    nonexact["claims"][0]["source_span"] = "DOCKPULSE shows warehouse dispatchers"
    broken.append(nonexact)
    for document in broken:
        try:
            lint_labels(profile, reference, document, brief)
        except AssertionError:
            continue
        raise AssertionError("lint accepted a deliberately broken label document")


if __name__ == "__main__":
    print(json.dumps(calculate_counts(), indent=2, ensure_ascii=False, sort_keys=True))
